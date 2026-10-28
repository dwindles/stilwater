"""Saints Row 2 character meshes (.cmesh_pc header + .g_cmesh_pc vertex/index data), as far as
needed to bake textures: positions, normals and diffuse UVs, and the triangles that use them.

Observed on cmUnS_uTShirt04_U (44-byte vertices): float3 position at +0, u8x4 bone weights at +12,
u8x4 bone indices at +16, packed u8x4 normal at +20 and tangent at +24, int16 UV at +28 (u = s/1024,
v = 1 + t/1024) and a second UV set at +32. The data file holds the vertices, then (16-byte aligned)
u16 indices as triangle strips. The header lists each strip as (0, count), (0, running end) pairs
and stores the vertex stride and count as a (u16 ?, u8 stride, u8 ?) u32 followed by the count.
"""
import struct

import numpy as np


def _find_vertex_info(header, data_size):
    """(stride, count, header offset) where stride * count fits the data file."""
    for k in range(0, len(header) - 8, 4):
        stride = header[k + 2]
        count, = struct.unpack_from("<I", header, k + 4)
        if 24 <= stride <= 64 and header[k + 3] == 0 and 3 <= count < 65536:
            vertex_bytes = (stride * count + 15) // 16 * 16
            if 0 < data_size - vertex_bytes < 8 * count:
                return stride, count, k
    raise ValueError("vertex stride/count not found")


def _find_strips(header, index_count):
    """[(start, count)] from the header's (0, count), (0, end) pairs: the longest table that fits in
    index_count (some meshes keep a second, smaller index set after the first)."""
    u = struct.unpack_from(f"<{len(header) // 4}I", header)
    best = None
    for k in range(len(u) - 4):
        if u[k] or u[k + 2] or not u[k + 1] or u[k + 1] != u[k + 3]:
            continue
        strips, end, j = [], 0, k
        # The last pair's second zero can carry a flag in its high half (0x10000 seen).
        while (j + 3 < len(u) and u[j] == 0 and u[j + 2] & 0xFFFF == 0 and u[j + 1]
               and u[j + 3] == end + u[j + 1]):
            strips.append((end, u[j + 1]))
            end = u[j + 3]
            j += 4
        if 0 < end <= index_count and (best is None or end > best[-1][0] + best[-1][1]):
            best = strips
    if best is None:
        raise ValueError("strip table not found")
    return best


def _part_triangles(header, data, stride, count):
    """Triangles from a car-style part record (0x00010000, index count, -1, -1, 0, format, vertices)
    and its submesh table, which some meshes (shoes) use instead of the strip pairs."""
    import car
    for part in car.find_parts(header):
        if part["stride"] == stride and part["verts"] == count:
            index_at = (stride * count + 15) // 16 * 16
            indices = np.frombuffer(data[index_at:index_at + 2 * part["indices"]], dtype="<u2")
            subs = part["submeshes"] or [dict(start=0, count=part["indices"], material=0)]
            return [(car.strip_triangles(indices[s["start"]:s["start"] + s["count"]]), s["material"]) for s in subs]
    return None


def load(header_path, data_path):
    """dict(positions (N,3), normals (N,3), uvs (N,2), triangles (M,3), materials (M,)), plus the
    raw vertex bytes ("raw") and their stride."""
    header = open(header_path, "rb").read()
    data = open(data_path, "rb").read()
    stride, count, _ = _find_vertex_info(header, len(data))
    raw = np.frombuffer(data[:stride * count], dtype=np.uint8).reshape(count, stride)

    positions = np.frombuffer(raw[:, 0:12].tobytes(), dtype="<f4").reshape(count, 3).astype(float)
    normals = raw[:, 20:23].astype(float) / 127.5 - 1.0
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-9
    st = np.frombuffer(raw[:, 28:32].tobytes(), dtype="<i2").reshape(count, 2).astype(float)
    uvs = np.stack([st[:, 0] / 1024.0, 1.0 + st[:, 1] / 1024.0], axis=1)

    # Two ways the header lists the draws (strip pairs, or a car-style part with submeshes); use
    # whichever covers more of the mesh.
    by_part = _part_triangles(header, data, stride, count)
    triangles = None
    try:
        index_at = (stride * count + 15) // 16 * 16
        strips = _find_strips(header, (len(data) - index_at) // 2)
        indices = np.frombuffer(data[index_at:index_at + 2 * (strips[-1][0] + strips[-1][1])], dtype="<u2")
        triangles = []
        for start, n in strips:
            s = indices[start:start + n]
            for i in range(n - 2):
                a, b, c = int(s[i]), int(s[i + 1]), int(s[i + 2])
                if a == b or b == c or a == c:
                    continue
                triangles.append((a, b, c) if i % 2 == 0 else (b, a, c))
        triangles = np.array(triangles)
        materials = np.zeros(len(triangles), dtype=int)
    except ValueError:
        if by_part is None:
            raise
    if by_part is not None and (triangles is None or sum(len(t) for t, _ in by_part) > len(triangles)):
        triangles = np.vstack([t for t, _ in by_part])
        materials = np.concatenate([np.full(len(t), m) for t, m in by_part])
    return dict(positions=positions, normals=normals, uvs=uvs, triangles=triangles, materials=materials,
                raw=raw, stride=stride)


def bake(mesh, width, height):
    """Per-texel surface position and normal: (pos (H,W,3), normal (H,W,3), mask (H,W))."""
    pos = np.zeros((height, width, 3))
    nrm = np.zeros((height, width, 3))
    mask = np.zeros((height, width), dtype=bool)
    uv = mesh["uvs"] * [width, height]
    for tri in mesh["triangles"]:
        p = uv[tri]
        x0, y0 = np.floor(p.min(axis=0)).astype(int)
        x1, y1 = np.ceil(p.max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width - 1), min(y1, height - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = p
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / det
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / det
        l3 = 1 - l1 - l2
        inside = (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4)
        if not inside.any():
            continue
        w = np.stack([l1, l2, l3], axis=-1)[inside]
        rows, cols = np.nonzero(inside)
        rows, cols = rows + y0, cols + x0
        pos[rows, cols] = w @ mesh["positions"][tri]
        nrm[rows, cols] = w @ mesh["normals"][tri]
        mask[rows, cols] = True
    nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9
    return pos, nrm, mask
