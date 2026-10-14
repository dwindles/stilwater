"""Put another game's car model on a Saints Row 2 car, keeping the SR2 car's rig, collision,
damage, wheels and handling.

The new model goes in whole as one or more of the SR2 car's body parts, which grow to fit (vertex
buffers keep their 64-byte phase, index buffers their 16-byte alignment, and the damage data
after the mesh region moves with its pointers). Every other body part is collapsed to a point.
The SR2 car's main texture is replaced by an atlas; vertex UVs point into it.

Input is per group (a set of triangles drawn with one SR2 material):
    groups = {name: (positions, normals, uvs, triangles)}
positions/normals in SR2 car space (x right, y up, z forward, driver at -x), uvs in atlas space
(0..1, or None for an untextured group), triangles indexing the group's vertices.

SR2 car file facts are in car.py; the growth rules are in port().
"""
import struct
from pathlib import Path

import numpy as np

import car
import peg
import strips
import vpp

MAX_DRAW_INDICES = 0xFFFF   # a submesh's index count is a u16


def orient(positions, normals, triangles):
    """SR2 winds front faces so cross(b - a, c - a) points outward (the SR2 cars' own strips,
    decoded per submesh, agree with their normals): flip triangles that disagree with the normals."""
    t = np.array(triangles, dtype=int)
    cross = np.cross(positions[t[:, 1]] - positions[t[:, 0]], positions[t[:, 2]] - positions[t[:, 0]])
    flip = np.einsum("ij,ij->i", cross, normals[t].sum(axis=1)) < 0
    t[flip] = t[flip][:, ::-1]
    return t


def double_sided(positions, normals, uvs, triangles):
    """Add the reverse side with flipped normals (SR2 culls back faces)."""
    n = len(positions)
    t = np.vstack([triangles, triangles[:, ::-1] + n])
    uv = None if uvs is None else np.vstack([uvs, uvs])
    return np.vstack([positions, positions]), np.vstack([normals, -normals]), uv, t


def load_parts(game, sr2_car):
    meshes = vpp.Packfile(Path(game) / "meshes.vpp_pc")
    header = bytearray(meshes.read(f"{sr2_car}.car_pc"))
    data = bytearray(meshes.read(f"{sr2_car}.g_car_pc"))
    parts = car.locate(car.find_parts(bytes(header)), bytes(data))
    for part in parts:
        part["raw"] = np.frombuffer(bytes(data[part["vb"]:part["vb"] + part["stride"] * part["verts"]]),
                                    dtype=np.uint8).reshape(part["verts"], part["stride"]).copy()
        part["strip"] = np.frombuffer(bytes(data[part["ib"]:part["ib"] + 2 * part["indices"]]), dtype="<u2")
    return header, data, parts


def uv_conventions(parts, materials):
    """Per SR2 material: (UV0 V stored as v - 1, copy of UV0 in the 4th set), as the SR2 car stores it."""
    out = {}
    for material in materials:
        t_values, mirrored = [], []
        for part in parts:
            if part["stride"] != 36:
                continue
            for sub in part["submeshes"]:
                if sub["material"] != material:
                    continue
                used = np.unique(part["strip"][sub["start"]:sub["start"] + sub["count"]])
                st0 = np.frombuffer(part["raw"][used, 20:24].tobytes(), dtype="<i2").reshape(-1, 2)
                st3 = np.frombuffer(part["raw"][used, 32:36].tobytes(), dtype="<i2").reshape(-1, 2)
                t_values.append(st0[:, 1])
                mirrored.append((st3[:, 0] == st0[:, 0]) & (st3[:, 1] == st0[:, 1] + 1024))
        t = np.concatenate(t_values) if t_values else np.zeros(1)
        m = np.concatenate(mirrored) if mirrored else np.zeros(1, dtype=bool)
        out[material] = (bool(np.mean(t <= 0) > 0.5), bool(np.mean(m) > 0.5))
    return out


def representative_uvs(parts, materials):
    """Bytes 20.. of a typical SR2 vertex for each material (for the UV sets not recomputed)."""
    out = {}
    for material in materials:
        rows = []
        for part in parts:
            for sub in part["submeshes"]:
                if sub["material"] != material:
                    continue
                used = np.unique(part["strip"][sub["start"]:sub["start"] + sub["count"]])
                block = np.zeros((len(used), 16), dtype=np.uint8)
                width = min(16, part["stride"] - 20)
                block[:, :width] = part["raw"][used, 20:20 + width]
                rows.append(block)
        if not rows:
            raise ValueError(f"the SR2 car has no material {material}")
        rows = np.vstack(rows)
        uv = np.frombuffer(rows[:, :4].tobytes(), dtype="<i2").reshape(-1, 2).astype(float)
        out[material] = rows[np.argmin(np.linalg.norm(uv - np.median(uv, axis=0), axis=1))]
    return out


def encode_vertices(positions, normals, uv_bytes, stride):
    """36-byte SR2 car vertices; uv_bytes is one 16-byte row per vertex."""
    raw = np.zeros((len(positions), stride), dtype=np.uint8)
    raw[:, 0:12] = np.frombuffer(positions.astype("<f4").tobytes(), dtype=np.uint8).reshape(-1, 12)
    raw[:, 12:15] = np.clip(np.round((normals + 1) * 127.5), 0, 255)
    raw[:, 15] = 127
    # Any unit vector perpendicular to the normal will do for the tangent.
    helper = np.where(np.abs(normals[:, 1:2]) < 0.9, [[0, 1, 0]], [[1, 0, 0]])
    tangent = np.cross(normals, helper)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-12
    raw[:, 16:19] = np.clip(np.round((tangent + 1) * 127.5), 0, 255)
    raw[:, 19] = 255
    raw[:, 20:stride] = uv_bytes[..., :stride - 20]
    return raw


def uv_bytes(uv, base_bytes, convention):
    """Per-vertex bytes 20..35: UV0 from atlas-space uv (s = u * 1024), other sets from base_bytes."""
    rows = np.repeat(base_bytes[None, :], len(uv) if uv is not None else 0, axis=0)
    if uv is None:
        return rows
    negative_v, mirror_to_set3 = convention
    s = np.round(uv[:, 0] * 1024).astype(np.int16)
    t = np.round(uv[:, 1] * 1024).astype(np.int16) - (1024 if negative_v else 0)
    rows[:, 0:4] = np.frombuffer(np.stack([s, t], axis=1).astype("<i2").tobytes(), dtype=np.uint8).reshape(-1, 4)
    if mirror_to_set3:
        rows[:, 12:16] = np.frombuffer(np.stack([s, t + 1024 if negative_v else t], axis=1)
                                       .astype("<i2").tobytes(), dtype=np.uint8).reshape(-1, 4)
    return rows


def strip_chunks(triangles):
    """Strips covering the triangles, each short enough for one submesh."""
    pieces = 1
    while True:
        chunks = np.array_split(np.asarray(triangles), pieces)
        out = [strips.build(c.tolist()) for c in chunks if len(c)]
        if all(len(s) <= MAX_DRAW_INDICES for s in out):
            return out
        pieces += 1


def build_part(names, groups, material, base_uvs, conventions, stride):
    """The groups for one part. Returns (vertex bytes, strip, [(start, count, material)])."""
    raw, strip, subs = [], [], []
    base = 0
    for name in names:
        if name not in groups:
            continue
        p, n, uv, t = groups[name]
        m = material[name]
        chunks = strip_chunks(t)
        print(f"   {name}: {len(t)} triangles, {len(p)} vertices, {sum(map(len, chunks))} indices in {len(chunks)} draws")
        rows = uv_bytes(uv, base_uvs[m], conventions[m]) if uv is not None else np.repeat(base_uvs[m][None, :], len(p), axis=0)
        raw.append(encode_vertices(p, n, rows, stride))
        for s in chunks:
            subs.append((len(strip), len(s), m))
            strip += [base + i for i in s]
        base += len(p)
    assert base <= 0xFFFF, f"{base} vertices: over the 16-bit index limit for one part"
    return np.vstack(raw), strip, subs


def write_textures(game, sr2_car, atlas_texture, atlas, out, work):
    """The SR2 car's texture pack with its atlas replaced (it grows; car packs aren't fixed-size)."""
    pegs, textures = vpp.Packfile(Path(game) / "pegs.vpp_pc"), vpp.Packfile(Path(game) / "textures.vpp_pc")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / f"{sr2_car}.peg_pc").write_bytes(pegs.read(f"{sr2_car}.peg_pc"))
    (work / f"{sr2_car}.g_peg_pc").write_bytes(textures.read(f"{sr2_car}.g_peg_pc"))
    blob, mips = peg.encode(atlas, "DXT1")
    size = atlas.size[0]
    header, data = peg.rebuild(work / f"{sr2_car}.peg_pc", work / f"{sr2_car}.g_peg_pc",
                               {atlas_texture: (size, atlas.size[1], 0x190, mips, blob)})
    (out / f"{sr2_car}.peg_pc").write_bytes(header)
    (out / f"{sr2_car}.g_peg_pc").write_bytes(data)
    print(f"atlas {size}x{atlas.size[1]}, {mips} mips; texture pack {len(data)} bytes")


def _move_triples(data, moves, tolerance=0.01):
    """Replace float triples close to each old position (or its negation, as rig bones store the
    inverse too) with the new one. Returns how many were replaced."""
    data = bytearray(data)
    count = 0
    for off in range(0, len(data) - 11, 4):
        v = np.array(struct.unpack_from("<3f", data, off))
        if not np.all(np.isfinite(v)):
            continue
        for old, new in moves:
            for sign in (1, -1):
                if np.all(np.abs(v - sign * np.asarray(old)) < tolerance):
                    struct.pack_into("<3f", data, off, *(sign * np.asarray(new, dtype=float)))
                    count += 1
    return bytes(data), count


def move_wheels(game, sr2_car, out, moves):
    """Move the SR2 car's wheels: moves = [((x, y, z) old centre, (x, y, z) new centre)].

    Wheel centres are stored as the wheel nodes' positions in the .car_pc (identity rotation, then
    the position; one node per wheel) and as the rig's wheel bones (PD_wheel_*: inverse translation
    then translation) in the .rig_pc. Patches out/<car>.car_pc (written by port()) and writes
    out/<car>.rig_pc.
    """
    out = Path(out)
    car_pc = out / f"{sr2_car}.car_pc"
    header, n = _move_triples(car_pc.read_bytes(), moves)
    assert n == len(moves), f"{n} wheel nodes moved in the .car_pc, expected {len(moves)}"
    car_pc.write_bytes(header)
    rig = vpp.Packfile(Path(game) / "meshes.vpp_pc").read(f"{sr2_car}.rig_pc")
    rig, n = _move_triples(rig, moves)
    assert n == 2 * len(moves), f"{n} rig values moved, expected {2 * len(moves)}"
    (out / f"{sr2_car}.rig_pc").write_bytes(rig)
    print(f"moved {len(moves)} wheels")


def move_nodes(out, sr2_car, prefixes, offset):
    """Shift named nodes (seats such as "driver", "passenger_1", "driver_l_foot") in out/<car>.car_pc.

    A node record is a 32-byte name, then its position (float3) at +0x44 and a unit quaternion at
    +0x50. offset is added to the position of every node whose name starts with one of prefixes.
    Returns the names moved.
    """
    path = Path(out) / f"{sr2_car}.car_pc"
    data = bytearray(path.read_bytes())
    moved = []
    for prefix in prefixes:
        start = 0
        while (at := data.find(prefix.encode(), start)) >= 0:
            start = at + 1
            if at and (chr(data[at - 1]).isalnum() or data[at - 1] == ord("_")):
                continue   # inside a longer name
            name = bytes(data[at:at + 32]).split(b"\0")[0].decode("latin-1")
            quat = np.array(struct.unpack_from("<4f", data, at + 0x50))
            if not name.startswith(prefix) or not np.all(np.isfinite(quat)) or abs(np.linalg.norm(quat) - 1) > 1e-3:
                continue
            pos = np.array(struct.unpack_from("<3f", data, at + 0x44)) + offset
            struct.pack_into("<3f", data, at + 0x44, *pos)
            moved.append(name)
    path.write_bytes(bytes(data))
    return moved


def port(game, sr2_car, atlas_texture, groups, material, layout, atlas, out, work):
    """Write out/<sr2_car>.car_pc, .g_car_pc, .peg_pc and .g_peg_pc.

    layout: {SR2 part index: [group names]}; material: {group name: SR2 material}.
    work: a folder for the SR2 car's original texture pack.
    """
    out = Path(out)
    header, data, parts = load_parts(game, sr2_car)
    materials = sorted(set(material.values()))
    base_uvs = representative_uvs(parts, materials)
    conventions = uv_conventions(parts, materials)

    region_end = struct.unpack_from("<I", header, 0x88)[0]       # damage data starts here
    damage_headers = struct.unpack_from("<I", header, 0x84)[0]   # first damage-block header
    original_header = bytes(header)
    new_data = bytearray()
    delta = 0
    for index, part in enumerate(parts):
        vb = part["vb"] + delta
        new_data += bytes(vb - len(new_data))
        if index in layout:
            subs = part["submeshes"]
            raw, strip, used = build_part(layout[index], groups, material, base_uvs, conventions, part["stride"])
            assert len(used) <= len(subs), f"part {index}: {len(used)} draws, only {len(subs)} submesh slots"
            # The SR2 car's crash-damage data moves this part's vertices by index. Those indices
            # belong to the SR2 mesh, so keep its vertex slots as undrawn placeholders and put the
            # new vertices after them: damage then moves only vertices no triangle uses.
            placeholders = part["raw"].copy()
            placeholders[:, 0:12] = 0
            raw = np.vstack([placeholders, raw])
            strip = [i + len(placeholders) for i in strip]
            assert len(raw) <= 0xFFFF, f"part {index}: {len(raw)} vertices with placeholders"
            # Each unused submesh keeps a 3-index degenerate draw at the end of the buffer.
            spare = 3 * (len(subs) - len(used))
            verts, count = len(raw), len(strip) + spare
            print(f"part {index}: {verts} vertices, {count} indices (SR2 {part['verts']}, {part['indices']})")
            vertices = raw
            indices = np.zeros(count, dtype="<u2")
            indices[:len(strip)] = strip
            # The part record holds both counts. The part's damage block (crash deformation: one packed
            # position change and normal per SR2 vertex) keeps the SR2 vertex count it was made for,
            # so it only ever moves the placeholders; raising it made crashes read past the block.
            struct.pack_into("<I", header, part["record"] + 4, count)
            struct.pack_into("<I", header, part["record"] + 24, verts)
            # The submesh table appears more than once in the part's stretch of the header (a second,
            # reordered list follows the part record and is what the game draws from), so every
            # copy of each original 16-byte entry is rewritten.
            lo = parts[index - 1]["record"] + 28 if index else 0
            nxt = parts[index + 1]
            hi = nxt["submeshes"][0]["record"] if nxt["submeshes"] else nxt["record"]
            for k, sub in enumerate(subs):
                start, n, m = used[k] if k < len(used) else (count - 3, 3, sub["material"])
                old = struct.pack("<4I", 0, sub["start"], 0, sub["count"] | sub["material"] << 16)
                new = struct.pack("<4I", 0, start, 0, n | m << 16)
                copies = [c for c in range(lo, hi - 15, 4) if original_header[c:c + 16] == old]
                assert sub["record"] in copies, (index, k)
                for c in copies:
                    header[c:c + 16] = new
        else:
            # Collapse: every vertex at the part's origin, so nothing is drawn.
            vertices = part["raw"].copy()
            vertices[:, 0:12] = 0
            indices = part["strip"]
        # Vertex buffer, then the index buffer on a 16-byte boundary (the game's layout).
        new_data += vertices.tobytes()
        new_data += bytes((-len(new_data)) % 16)
        new_data += np.asarray(indices, dtype="<u2").tobytes()
        # Keep every later part at its original 64-byte phase: shift by whole multiples of 64.
        following = parts[index + 1]["vb"] if index + 1 < len(parts) else region_end
        if following + delta < len(new_data):
            delta += (len(new_data) - following - delta + 63) // 64 * 64

    new_data += bytes(region_end + delta - len(new_data))
    new_data += data[region_end:]
    # The damage data moved: its start (0x88) and every (damage header, data offset) pair.
    for m in range(4, len(original_header) - 3, 4):
        previous, value = struct.unpack_from("<2I", original_header, m - 4)
        if (region_end <= value < len(data) and damage_headers <= previous < len(original_header)
                and original_header[previous:previous + 4] == b"\xef\xbe\x37\x13"):
            struct.pack_into("<I", header, m, value + delta)
    print(f"geometry grew by {delta} bytes; damage data now at {region_end + delta}")

    out.mkdir(parents=True, exist_ok=True)
    (out / f"{sr2_car}.car_pc").write_bytes(bytes(header))
    (out / f"{sr2_car}.g_car_pc").write_bytes(bytes(new_data))
    write_textures(game, sr2_car, atlas_texture, atlas, out, work)
    print(f"wrote {out}")
