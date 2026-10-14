"""Read Need for Speed Most Wanted (2005) PC model files (CARS\\<car>\\GEOMETRY.BIN).

The file is EA "bChunk" data: u32 id, u32 size, body; ids with the top bit set contain chunks.
Each 0x80134010 chunk is one solid (model part):

- 0x00134011 header: bounding box at +0x20, transform at +0x40, name at +0xA0.
- 0x00134012 texture list: (u32 texture name hash, u32 0) per slot.
- 0x80134100 mesh:
  - 0x00134900 mesh header: u32 material count at +0x10, u32 total index count at +0x2C.
  - 0x00134B02 materials, 0x68 bytes each after 0x11 alignment padding: bbox min/max (+0x00,
    +0x0C), texture slot indices (u8 x5 at +0x18), u32 vertex count +0x3C, triangle count +0x40,
    first index +0x44, index count +0x5C.
  - 0x00134B03 indices: u16 triangle list.
  - 0x00134B01 vertices after 0x11 padding: 36 bytes each, position f32x3, normal f32x3,
    colour u32, uv f32x2.
  - 0x00134C02 per material: its name (e.g. WINDOW_FRONT).

Car space: x forward, y left, z up, metres.

    python geometry.py <GEOMETRY.BIN> [name filter]
"""
import struct
import sys

import numpy as np

VERTEX = np.dtype([("pos", "<f4", 3), ("normal", "<f4", 3), ("color", "<u4"), ("uv", "<f4", 2)])


def _chunks(d, off, end):
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", d, off)
        yield cid, off + 8, size
        off += 8 + size


def _skip_padding(d, off, end):
    while off < end and d[off:off + 4] == b"\x11\x11\x11\x11":
        off += 4
    return off


def _solid(d, body, size):
    solid = {"materials": [], "textures": [], "vertices": None, "indices": None}
    for cid, b, s in _chunks(d, body, body + size):
        if cid == 0x00134011:
            solid["name"] = d[b + 0xA0:b + s].split(b"\0")[0].decode("latin-1")
            solid["bbox"] = struct.unpack_from("<3f4x3f", d, b + 0x20)
        elif cid == 0x00134012:
            solid["textures"] = [struct.unpack_from("<I", d, b + 8 * k)[0] for k in range(s // 8)]
        elif cid == 0x80134100:
            mesh_names = []
            for mid, mb, ms in _chunks(d, b, b + s):
                if mid == 0x00134B02:
                    start = _skip_padding(d, mb, mb + ms)
                    for k in range((mb + ms - start) // 0x68):
                        m = start + k * 0x68
                        solid["materials"].append(dict(
                            bbox=struct.unpack_from("<6f", d, m),
                            texture_slots=list(d[m + 0x18:m + 0x1D]),
                            vertex_count=struct.unpack_from("<I", d, m + 0x3C)[0],
                            triangle_count=struct.unpack_from("<I", d, m + 0x40)[0],
                            first_index=struct.unpack_from("<I", d, m + 0x44)[0],
                            index_count=struct.unpack_from("<I", d, m + 0x5C)[0]))
                elif mid == 0x00134B03:
                    start = _skip_padding(d, mb, mb + ms)
                    solid["indices"] = np.frombuffer(d[start:mb + ms], dtype="<u2").copy()
                elif mid == 0x00134B01:
                    start = _skip_padding(d, mb, mb + ms)
                    n = (mb + ms - start) // VERTEX.itemsize
                    v = np.frombuffer(d[start:start + n * VERTEX.itemsize], dtype=VERTEX).copy()
                    solid["vertices"] = v if solid["vertices"] is None else np.concatenate([solid["vertices"], v])
                elif mid == 0x00134C02:
                    mesh_names.append(d[mb:mb + ms].split(b"\0")[0].decode("latin-1"))
            for m, name in zip(solid["materials"], mesh_names):
                m["name"] = name
    return solid


def read(path):
    """[solid]: name, bbox, textures (hashes), materials, vertices (VERTEX array), indices."""
    d = open(path, "rb").read()
    solids = []

    def walk(off, end):
        for cid, body, size in _chunks(d, off, end):
            if cid == 0x80134010:
                solids.append(_solid(d, body, size))
            elif cid & 0x80000000:
                walk(body, body + size)
    walk(0, len(d))
    return solids


def triangles(solid, material):
    """(n, 3) vertex indices of one material's triangles."""
    idx = solid["indices"][material["first_index"]:material["first_index"] + material["index_count"]]
    return idx.reshape(-1, 3).astype(int)


def main(argv):
    pattern = argv[2] if len(argv) > 2 else ""
    for s in read(argv[1]):
        if pattern not in s["name"]:
            continue
        nv = 0 if s["vertices"] is None else len(s["vertices"])
        print(f"{s['name']}: {nv} vertices, {len(s['materials'])} materials")
        for m in s["materials"]:
            tex = [f"{s['textures'][i]:08x}" if i < len(s["textures"]) else "-" for i in m["texture_slots"][:1]]
            print(f"   {m.get('name', ''):24} tris {m['triangle_count']:5} verts {m['vertex_count']:5} tex {tex}")


if __name__ == "__main__":
    main(sys.argv)
