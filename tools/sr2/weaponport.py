"""GTA V weapon models (.ydr drawables) in place of SR2 weapon models, for the weapon mods
(mods/glock-switch, mods/draco).

SR2 weapon meshes (.smesh_pc header, .g_smesh_pc data): per detail level (3) a car-style part
record in the header (car.find_parts; index count at +4, vertex count at +0x18) whose 32-byte
vertices (float3 position, u8x4 normal and tangent, int16 UV / 1024 with v down the texture) and
index strip follow each other in the data, 16-byte aligned. The header also keeps a positions-only
shadow mesh per level; those stay the vanilla gun's. The submesh table before the first part
record alternates each level's render submesh and its shadow submesh (flagged 0x10000). The
bounding box (6 floats) sits wherever the vanilla box is, the bounding sphere (centre, radius) at
0x14. Named nodes (muzzle_flash, shell_eject, weapon_handle, handle_left) keep their position at
name + 0x44; weapon_handle, the hand, is the origin.

GTA weapons are right-handed with x forward (the barrel), y left and z up; SR2's are left-handed
with z forward, y up and the gun's right side at +x, and canted a little (the top leaning towards
+x).

GTA models' UVs are cut into hundreds of small islands that a seam-keeping simplification can
barely reduce, so the simplified levels get a new box-projected atlas (tools/mesh/unwrap.py)
shared by all three, and the GTA textures are baked onto it from the full model (nearest point
facing the same way).
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).parent.parent / "mesh"))
sys.path.insert(0, str(Path(__file__).parent.parent / "gta5"))
import bake  # noqa: E402
import car  # noqa: E402
import carport  # noqa: E402
import peg  # noqa: E402
import simplify  # noqa: E402
import strips  # noqa: E402
import vpp  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402

STRIDE = 32
LEVELS = 3
DXT1, DXT5 = 0x190, 0x192


def gta_to_sr2(roll_degrees, scale=1.0):
    """3x3 matrix: GTA (x forward, y left, z up) to SR2 (x right, y up, z forward), then the SR2
    gun's cant about z."""
    axes = np.array([[0, -1, 0], [0, 0, 1], [1, 0, 0]], dtype=float)
    c, s = np.cos(np.radians(roll_degrees)), np.sin(np.radians(roll_degrees))
    roll = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
    return roll @ axes * scale


def extract(game, model, folder):
    """The vanilla model's files into folder, from the patch archive where it has them (it
    carries newer copies)."""
    folder.mkdir(parents=True, exist_ok=True)
    patch = vpp.Packfile(game / "m_pat.vpp_pc")
    patched = {e["name"] if isinstance(e, dict) else e[0] for e in patch.entries}
    for archive, ext in (("meshes.vpp_pc", "smesh_pc"), ("meshes.vpp_pc", "g_smesh_pc"),
                         ("pegs.vpp_pc", "peg_pc"), ("textures.vpp_pc", "g_peg_pc")):
        name = f"{model}.{ext}"
        source = patch if name in patched else vpp.Packfile(game / archive)
        (folder / name).write_bytes(source.read(name))


def vanilla_positions(header, data):
    """Each detail level's vertex positions in the vanilla mesh."""
    parts = car.find_parts(header)
    assert [p["stride"] for p in parts] == [STRIDE] * LEVELS, parts
    car.locate(parts, data)
    out = []
    for p in parts:
        raw = np.frombuffer(data[p["vb"]:p["vb"] + STRIDE * p["verts"]], dtype=np.uint8).reshape(-1, STRIDE)
        out.append(np.frombuffer(raw[:, :12].tobytes(), dtype="<f4").reshape(-1, 3).astype(float))
    return out


def vanilla_triangles(header, data, level=0):
    """A detail level's triangles in the vanilla mesh."""
    parts = car.find_parts(header)
    car.locate(parts, data)
    p = parts[level]
    strip = np.frombuffer(data[p["ib"]:p["ib"] + 2 * p["indices"]], dtype="<u2")
    return np.array(strips.triangles(strip.tolist()))


def shader_textures(res, drawable):
    """Diffuse texture name of each shader in a drawable's shader group (its first texture)."""
    group = res.u64(drawable, 0x10)
    shaders, count = res.unpack("<QH", group, 0x10)
    names = []
    for i in range(count):
        shader = res.u64(shaders, 8 * i)
        params, = res.unpack("<Q", shader, 0x00)
        n, = res.unpack("<B", shader, 0x10)
        name = None
        for k in range(n):
            kind, = res.unpack("<B", params, 16 * k)
            pointer, = res.unpack("<Q", params, 16 * k + 8)
            if kind == 0 and pointer:
                buf, off = res.at(res.u64(pointer, 0x28))
                name = buf[off:buf.index(b"\0", off)].decode("latin-1")
                break
        names.append(name)
    return names


def bones(res, drawable):
    """{name: (position, 3x3 rotation)} of the drawable's skeleton in model space."""
    skeleton = res.u64(drawable, 0x18)
    pointer, = res.unpack("<Q", skeleton, 0x20)
    count, = res.unpack("<H", skeleton, 0x5E)
    world = []
    out = {}
    for i in range(count):
        x, y, z, w = res.unpack("<4f", pointer, 0x50 * i)
        t = np.array(res.unpack("<3f", pointer, 0x50 * i + 0x10))
        parent, = res.unpack("<h", pointer, 0x50 * i + 0x32)
        buf, off = res.at(res.u64(pointer, 0x50 * i + 0x38))
        name = buf[off:buf.index(b"\0", off)].decode("latin-1")
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        if parent >= 0:
            pp, pr = world[parent]
            t, r = pp + pr @ t, pr @ r
        world.append((t, r))
        out[name] = (t, r)
    return out


def load_gta(path, offset=(0.0, 0.0, 0.0)):
    """dict(positions, normals, uvs (v down the texture), triangles, textures (diffuse name per
    triangle)) of a drawable's high detail, all geometries joined, moved by offset (GTA frame)."""
    drawable = yft.read_drawable(path)
    names = shader_textures(drawable["resource"], drawable["drawable"])
    positions, normals, uvs, triangles, textures, base = [], [], [], [], [], 0
    for model in drawable["lods"]["high"]:
        for g in model["geometries"]:
            positions.append(g["positions"] + offset)
            normals.append(g["normals"][:, :3])
            uvs.append(g["uvs"])
            triangles.append(g["triangles"] + base)
            textures += [names[g["shader"]]] * len(g["triangles"])
            base += len(g["positions"])
    p, n, uv, t = (np.concatenate(x) for x in (positions, normals, uvs, triangles))
    return dict(positions=p, normals=n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12), uvs=uv,
                triangles=t, textures=np.array(textures))


def join(models):
    """One model from several load_gta models."""
    base, triangles = 0, []
    for m in models:
        triangles.append(m["triangles"] + base)
        base += len(m["positions"])
    return dict(positions=np.concatenate([m["positions"] for m in models]),
                normals=np.concatenate([m["normals"] for m in models]),
                uvs=np.concatenate([m["uvs"] for m in models]),
                triangles=np.concatenate(triangles),
                textures=np.concatenate([m["textures"] for m in models]))


def load_textures(paths, names):
    """{name: (H, W, 3) floats} for the named textures, from the .ytd files."""
    out = {}
    for path in paths:
        for name, (width, height, fmt, _, buf, off) in ytd.textures(path).items():
            if name in names and name not in out:
                out[name] = np.asarray(ytd.to_image(width, height, fmt, buf, off).convert("RGB"), dtype=np.float32) / 255
    missing = set(names) - set(out)
    assert not missing, missing
    return out


def lods(cache, model, targets):
    """Simplified (positions, triangles) per detail level, from the mesh welded by position; cached
    in cache/shape{level}_{target}.npz (slow)."""
    p, t, _ = simplify.weld(model["positions"], model["triangles"], 1e-5)
    out = []
    for level, target in enumerate(targets):
        path = cache / f"shape{level}_{target}.npz"
        if not path.exists():
            q, tri = simplify.simplify(p, t, target)
            np.savez(path, positions=q, triangles=tri)
            print(f"   detail {level}: {len(t)} -> {len(tri)} triangles, {len(q)} vertices")
        d = np.load(path)
        out.append((d["positions"], d["triangles"]))
    return out


def bake_atlas(levels, model, textures, size, samples):
    """The model's textures baked onto the levels' shared atlas: [(positions, triangles, uvs)] ->
    (image, covered)."""
    p, n, uv, t = model["positions"], model["normals"], model["uvs"], model["triangles"]
    corners = t.reshape(-1)
    # FBX-style UVs (v from the bottom) for bake.bilinear; GTA's v runs down the texture.
    points, sample_uvs, sample_normals, pick = bake.sample_surface(
        p[corners], np.arange(len(corners)).reshape(-1, 3), uv[corners] * [1, -1] + [0, 1], n[corners], samples)
    sample_texture = model["textures"][pick]
    tree = cKDTree(points)
    image = np.zeros((size, size, 3))
    covered = np.zeros((size, size), bool)
    for q, tri, atlas in levels:
        normals = simplify.vertex_normals(q, tri)
        rows, cols, tris, w = bake.rasterize(atlas, tri, size)
        corner = tri[tris]
        texel = (w[..., None] * q[corner]).sum(axis=1)
        texel_n = (w[..., None] * normals[corner]).sum(axis=1)
        texel_n /= np.linalg.norm(texel_n, axis=1, keepdims=True) + 1e-12
        nearest = bake.nearest_facing(tree, sample_normals, texel, texel_n, k=12)
        for name, texture in textures.items():
            mine = sample_texture[nearest] == name
            image[rows[mine], cols[mine]] = bake.bilinear(texture, sample_uvs[nearest[mine]])
        covered[rows, cols] = True
    return Image.fromarray((np.clip(bake.dilate(image, covered, passes=6), 0, 1) * 255).astype(np.uint8)), covered


def outward(positions, normals, triangles):
    """Triangles wound so cross(b - a, c - a) points along the normals (SR2's front faces)."""
    fn = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                  positions[triangles[:, 2]] - positions[triangles[:, 0]])
    flip = (fn * normals[triangles].mean(axis=1)).sum(axis=1) < 0
    triangles = triangles.copy()
    triangles[flip] = triangles[flip][:, [0, 2, 1]]
    return triangles


def uv_sets(header, data):
    """How many UV sets the vanilla model fills (+20, and +24 when the second is in use: the T3K's
    material reads the second, the NR4's and the phone's leave it zero)."""
    part = car.find_parts(bytes(header))[0]
    vertices = np.frombuffer(data, dtype=np.uint8, count=part["verts"] * STRIDE).reshape(-1, STRIDE)
    return 2 if vertices[:, 24:28].any() else 1


def encode(positions, normals, uvs, sets=1):
    rows = np.zeros((len(positions), 16), dtype=np.uint8)
    st = np.clip(np.round(uvs * 1024), -32768, 32767).astype("<i2")
    for k in range(sets):
        rows[:, 4 * k:4 * k + 4] = np.frombuffer(st.tobytes(), dtype=np.uint8).reshape(-1, 4)
    return carport.encode_vertices(positions, normals, rows, STRIDE)


def write_mesh(header, levels, matrix, offset, box, sets=1):
    """New mesh data from the levels [(positions, triangles, uvs)] in GTA space, placed by matrix and
    offset; header (bytearray) gets the new counts and bounds (box: find_box's offset). sets is
    uv_sets() of the vanilla model. Returns the data."""
    parts = car.find_parts(bytes(header))
    data = bytearray()
    everything, strip_lengths = [], []
    for part, (p, t, uv) in zip(parts, levels):
        q = p @ matrix.T + offset
        normals = simplify.vertex_normals(q, t)
        # vertex_normals follows the winding; flip to point away from the gun's middle if needed.
        if ((q - q.mean(axis=0)) * normals).sum() < 0:
            normals = -normals
        t = outward(q, normals, t)
        strip = strips.build(t.tolist())
        assert len(q) <= 0xFFFF and len(strip) <= 0xFFFF
        data += encode(q, normals, uv, sets).tobytes()
        data += bytes(-len(data) % 16)
        data += np.asarray(strip, dtype="<u2").tobytes()
        data += bytes(-len(data) % 16) if part is not parts[-1] else b""
        record = part["record"]
        struct.pack_into("<I", header, record + 4, len(strip))
        struct.pack_into("<I", header, record + 0x18, len(q))
        everything.append(q)
        strip_lengths.append(len(strip))
        print(f"   detail level at {record:#x}: {len(t)} triangles, {len(q)} vertices, {len(strip)} strip indices")
    table = parts[0]["submeshes"][0]["record"]
    for level, count in enumerate(strip_lengths):
        entry = table + 32 * level + 12
        assert struct.unpack_from("<I", header, entry)[0] >> 16 == 0
        struct.pack_into("<I", header, entry, count)
    allp = np.vstack(everything)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    centre = (lo + hi) / 2
    struct.pack_into("<6f", header, box, *lo, *hi)
    struct.pack_into("<4f", header, 0x14, *centre, float(np.linalg.norm(allp - centre, axis=1).max()))
    return data


def _shadow(header, record):
    """(positions offset, vertex count, strip offset, index count) of the shadow mesh after a part
    record: its strip length at +0x28, its vertex count at +0x3C (12-byte positions), then the
    positions from the 16-byte boundary after +0x48 and the strip from the next one."""
    count, = struct.unpack_from("<I", header, record + 0x28)
    desc, verts = struct.unpack_from("<II", header, record + 0x38)
    assert desc == 0xC0000, hex(desc)
    positions = (record + 0x48 + 15) // 16 * 16
    strip = (positions + 12 * verts + 15) // 16 * 16
    assert max(struct.unpack_from(f"<{count}H", header, strip)) < verts
    return positions, verts, strip, count


def write_shadows(header, shapes, matrix, offset):
    """Replace each level's shadow mesh (which the gun's shadows come from, its own included) with
    its shape (positions, triangles in GTA space; simplified further until it fits). The vertex
    and index counts stay as they are, filled up with repeats (degenerate triangles), so nothing
    in the header moves."""
    for part, (p, t) in zip(car.find_parts(bytes(header)), shapes):
        at, verts, strip_at, count = _shadow(header, part["record"])
        target = len(t)
        while True:
            q, tri = (p, t) if target >= len(t) else simplify.simplify(p, t, target)
            q = q @ matrix.T + offset
            normals = simplify.vertex_normals(q, tri)
            if ((q - q.mean(axis=0)) * normals).sum() < 0:
                normals = -normals
            strip = strips.build(outward(q, normals, tri).tolist())
            if len(q) <= verts and len(strip) <= count:
                break
            target = int(min(target, len(t)) * 0.8)
        q = np.vstack([q, np.repeat(q[-1:], verts - len(q), axis=0)]).astype("<f4")
        strip = strip + [strip[-1]] * (count - len(strip))
        header[at:at + 12 * verts] = q.tobytes()
        header[strip_at:strip_at + 2 * count] = np.asarray(strip, dtype="<u2").tobytes()
        print(f"   shadow at {part['record']:#x}: {len(tri)} triangles ({verts} vertices, {count} indices available)")


def find_box(header, vanilla):
    """Offset of the bounding box (6 floats) matching the vanilla positions' bounds."""
    allp = np.vstack(vanilla)
    want = np.concatenate([allp.min(axis=0), allp.max(axis=0)])
    found = [k for k in range(0, len(header) - 24, 4)
             if np.allclose(struct.unpack_from("<6f", header, k), want, atol=2e-3)]
    assert len(found) == 1, found
    return found[0]


def set_node(header, name, position):
    """Move a named node (muzzle_flash, shell_eject, ...)."""
    at = bytes(header).index(name.encode() + b"\0")
    struct.pack_into("<3f", header, at + 0x44, *position)


def set_diffuse_colour(header, old, new=(1.0, 1.0, 1.0, 1.0)):
    """Change the material's diffuse colour, which multiplies the diffuse texture (the T3K's is
    0.133 grey over a light texture: left alone, a ported gun comes out nearly black)."""
    want = struct.pack("<4f", *old)
    at = bytes(header).find(want)
    assert at >= 0 and bytes(header).count(want) == 1, "diffuse colour not found once"
    struct.pack_into("<4f", header, at, *new)


def retexture(original, model, diffuse, image, others=None):
    """(peg header, data) with the diffuse texture replaced by image (DXT1), and others ({name:
    (image, "DXT1" or "DXT5")}) too."""
    replacements = {}
    for name, (img, fmt) in {diffuse: (image, "DXT1"), **(others or {})}.items():
        data, mips = peg.encode(img, fmt)
        replacements[name] = (img.width, img.height, DXT1 if fmt == "DXT1" else DXT5, mips, data)
    return peg.rebuild(original / f"{model}.peg_pc", original / f"{model}.g_peg_pc", replacements)
