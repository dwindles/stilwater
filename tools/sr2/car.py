"""Saints Row 2 vehicle meshes (.car_pc structure + .g_car_pc geometry), enough to edit geometry
in place: same vertex and index counts per part, so nothing else in the structure file changes.

Each render part is described in the .car_pc by a record
    u32 0x00010000, u32 index count, u32 -1, u32 -1, u32 0, u16 format, u8 stride, u8 0, u32 vertex count
preceded by its submesh table, 16 bytes per entry: u32 0, u32 first index, u32 0, u16 index count,
u16 material. Indices are u16 triangle strips (degenerate triangles join the runs).

In the .g_car_pc the parts' vertex buffers and index buffers follow one another in record order;
vertex buffers start on 16-byte boundaries but the padding isn't fixed, so their offsets are found
by scanning (every vertex's normal has 127 in its fourth byte). The mesh region ends at the size
stored at .car_pc offset 0x88.

Vertex layout of the 36-byte format (0x0404): float3 position (x across, y up, z along the car),
u8x4 normal (n/127.5 - 1, w = 127), u8x4 tangent, then four int16x2 UV sets.
"""
import struct

import numpy as np


def find_parts(header):
    parts = []
    for k in range(0, len(header) - 28, 4):
        a, n, f1, f2, z, desc, verts = struct.unpack_from("<7I", header, k)
        stride = desc >> 16 & 0xFF
        if (a == 0x00010000 and f1 == f2 == 0xFFFFFFFF and z == 0 and desc >> 24 == 0
                and 12 <= stride <= 80 and 0 < verts < 65536):
            # The 16 bytes just before the record hold flags, not a submesh; the table ends there.
            subs, s = [], k - 32
            while s >= 0:
                z0, start, z1, cm = struct.unpack_from("<4I", header, s)
                if z0 or z1 or (subs and start > subs[-1][0]):
                    break
                subs.append((start, cm & 0xFFFF, cm >> 16, s))
                s -= 16
            subs.reverse()
            parts.append(dict(record=k, indices=n, format=desc & 0xFFFF, stride=stride, verts=verts,
                              submeshes=[dict(start=a_, count=c_, material=m_, record=r_) for a_, c_, m_, r_ in subs]))
    return parts


def locate(parts, data):
    """Fill in each part's vertex buffer ("vb") and index buffer ("ib") offsets."""
    g = np.frombuffer(data, dtype=np.uint8)
    offset = 0
    for part in parts:
        stride, verts, count = part["stride"], part["verts"], part["indices"]
        for vb in range(offset, len(data) - stride * verts + 1, 16):
            raw = g[vb:vb + stride * verts].reshape(verts, stride)
            if not np.all(raw[:, 15] == 127):
                continue
            pos = np.frombuffer(raw[:, :12].tobytes(), dtype="<f4")
            with np.errstate(all="ignore"):
                if not np.all(np.isfinite(pos) & (np.abs(pos) < 6)):
                    continue
            ib = (vb + stride * verts + 15) // 16 * 16
            ix = np.frombuffer(data[ib:ib + 2 * count], dtype="<u2")
            if len(ix) == count and ix.max() < verts:
                part["vb"], part["ib"] = vb, ib
                offset = (ib + 2 * count + 15) // 16 * 16
                break
        else:
            raise ValueError(f"part at {part['record']:#x}: buffers not found after {offset}")
    return parts


def load(header_path, data_path):
    header = open(header_path, "rb").read()
    data = open(data_path, "rb").read()
    parts = locate(find_parts(header), data)
    for part in parts:
        raw = np.frombuffer(data[part["vb"]:part["vb"] + part["stride"] * part["verts"]],
                            dtype=np.uint8).reshape(part["verts"], part["stride"])
        part["raw"] = raw
        part["positions"] = np.frombuffer(raw[:, :12].tobytes(), dtype="<f4").reshape(-1, 3).astype(float)
        part["strip"] = np.frombuffer(data[part["ib"]:part["ib"] + 2 * part["indices"]], dtype="<u2")
    return header, data, parts


def strip_triangles(ix):
    tris = []
    for i in range(len(ix) - 2):
        a, b, c = int(ix[i]), int(ix[i + 1]), int(ix[i + 2])
        if a == b or b == c or a == c:
            continue
        tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return np.array(tris, dtype=int).reshape(-1, 3)
