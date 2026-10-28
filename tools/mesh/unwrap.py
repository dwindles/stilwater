"""Box-projection UV unwrapping and atlas packing, for meshes whose original UVs are lost (simplified
models whose texture is then baked from the full-detail model).

Faces are grouped by the axis their normal points along most (6 directions) and by edge
connectivity; each group is projected onto its axis' plane (without mirroring), and triangles that
would overlap earlier ones in the projection start a new chart. Charts from several meshes are
packed into one atlas on shelves, each mesh at its own texel density.
"""
from collections import defaultdict, deque

import numpy as np

# For each direction (axis, sign): the 3D axes giving (u, v), chosen so faces aren't mirrored.
_PLANES = {(0, 1): (2, 1, -1, 1), (0, -1): (2, 1, 1, 1), (1, 1): (0, 2, 1, -1), (1, -1): (0, 2, 1, 1),
           (2, 1): (0, 1, 1, 1), (2, -1): (0, 1, -1, 1)}


def _face_normals(positions, triangles):
    n = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                 positions[triangles[:, 2]] - positions[triangles[:, 0]])
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-20)


def _overlaps(a, b):
    """Whether 2D triangles a and b (3x2) overlap with positive area (shared edges allowed)."""
    def axes(t):
        e = np.roll(t, -1, axis=0) - t
        return np.stack([-e[:, 1], e[:, 0]], axis=1)
    for axis in np.vstack([axes(a), axes(b)]):
        length = np.linalg.norm(axis)
        if length < 1e-20:
            continue
        axis = axis / length
        pa, pb = a @ axis, b @ axis
        if pa.max() <= pb.min() + 1e-9 or pb.max() <= pa.min() + 1e-9:
            return False
    return True


def charts(positions, triangles):
    """[(triangle indices, (T, 3, 2) projected corners)] for a mesh."""
    fn = _face_normals(positions, triangles)
    axis = np.abs(fn).argmax(axis=1)
    sign = np.where(fn[np.arange(len(fn)), axis] >= 0, 1, -1)
    by_edge = defaultdict(list)
    for i, t in enumerate(triangles):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            by_edge[(min(a, b), max(a, b))].append(i)
    assigned = np.zeros(len(triangles), bool)
    out = []
    for seed in range(len(triangles)):
        if assigned[seed]:
            continue
        key = (axis[seed], sign[seed])
        ua, va, us, vs = _PLANES[key]

        def project(i):
            p = positions[triangles[i]]
            return np.stack([p[:, ua] * us, p[:, va] * vs], axis=1)

        members, flat = [], []
        cells = defaultdict(list)       # coarse grid of the chart's triangles, for overlap tests
        size = None
        queue = deque([seed])
        queued = {seed}
        while queue:
            i = queue.popleft()
            tri = project(i)
            if size is None:
                size = max(np.ptp(tri, axis=0).max(), 1e-6) * 2
            lo, hi = np.floor(tri.min(axis=0) / size).astype(int), np.floor(tri.max(axis=0) / size).astype(int)
            near = {j for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1) for j in cells[(x, y)]}
            if any(_overlaps(tri, flat[j]) for j in near):
                continue                     # left for a later chart
            k = len(members)
            members.append(i)
            flat.append(tri)
            assigned[i] = True
            for x in range(lo[0], hi[0] + 1):
                for y in range(lo[1], hi[1] + 1):
                    cells[(x, y)].append(k)
            t = triangles[i]
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                for j in by_edge[(min(a, b), max(a, b))]:
                    if j not in queued and not assigned[j] and axis[j] == key[0] and sign[j] == key[1]:
                        queued.add(j)
                        queue.append(j)
        out.append((np.array(members), np.array(flat)))
    return out


def pack(groups, padding):
    """Pack charts on shelves. groups: [(charts, texels per unit)]. Returns (per group a list of
    per-chart (T, 3, 2) atlas coordinates in 0..1, atlas side in texels)."""
    items = []
    for g, (chart_list, density) in enumerate(groups):
        for c, (_, flat) in enumerate(chart_list):
            lo = flat.reshape(-1, 2).min(axis=0)
            extent = np.ptp(flat.reshape(-1, 2), axis=0) * density
            items.append((g, c, lo, density, extent + 2 * padding))
    area = sum(w * h for *_, (w, h) in items)
    side = max(64.0, np.sqrt(area) * 1.1)
    while True:
        placed, x, y, shelf = {}, 0.0, 0.0, 0.0
        ok = True
        for g, c, lo, density, (w, h) in sorted(items, key=lambda it: -it[4][1]):
            if w > side:
                ok = False
                break
            if x + w > side:
                x, y, shelf = 0.0, y + shelf, 0.0
            if y + h > side:
                ok = False
                break
            placed[(g, c)] = (x, y)
            x += w
            shelf = max(shelf, h)
        if ok:
            break
        side *= 1.05
    out = [[None] * len(chart_list) for chart_list, _ in groups]
    for g, c, lo, density, (w, h) in items:
        x, y = placed[(g, c)]
        flat = groups[g][0][c][1]
        out[g][c] = ((flat - lo) * density + [x + padding, y + padding]) / side
    return out, side


def unwrap(meshes, densities, size, padding=2.0):
    """New UVs for several meshes sharing one atlas of size x size texels. meshes: [(positions,
    triangles)]; densities: relative texel density per mesh. Returns [(positions, triangles, uvs,
    source vertex)]: vertices are split where charts meet; source vertex maps each new vertex to
    the old one."""
    chart_sets = [charts(p, t) for p, t in meshes]
    # Find the texel density (texels per unit) that fills the atlas.
    scale = 1.0
    for _ in range(40):
        placed, side = pack([(c, d * scale) for c, d in zip(chart_sets, densities)], padding)
        ratio = size / side
        if 0.97 <= ratio <= 1.0:
            break
        scale *= ratio * 0.99 if ratio < 1 else min(ratio, 2.0) * 0.99
    result = []
    for (p, t), chart_list, coords in zip(meshes, chart_sets, placed):
        new_pos, new_uv, source, new_tris = [], [], [], []
        for (members, _), uv in zip(chart_list, coords):
            local = {}
            for k, i in enumerate(members):
                tri = []
                for corner in range(3):
                    v = int(t[i][corner])
                    if v not in local:
                        local[v] = len(new_pos)
                        new_pos.append(p[v])
                        new_uv.append(uv[k][corner] * side / size)
                        source.append(v)
                    tri.append(local[v])
                new_tris.append(tri)
        result.append((np.array(new_pos), np.array(new_tris), np.array(new_uv), np.array(source)))
    return result
