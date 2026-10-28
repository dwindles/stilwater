"""Triangle mesh simplification by quadric error edge collapse (Garland & Heckbert), plus welding.

Pure Python + numpy, written for game-asset sizes (tens of thousands of triangles). Open boundary
edges get extra constraint planes so silhouettes and holes keep their shape.

Textured meshes: keep vertices split at UV seams (weld only identical position + UV), pass the UVs
(and normals) as attributes and lock_boundary=True. Seams are then open boundaries whose vertices
never move, so neighbouring UV islands stay joined, and the attributes of collapsed vertices are
interpolated along the collapsed edge.
"""
import heapq

import numpy as np


def weld(positions, triangles, tolerance=1e-4):
    """Merge vertices closer than tolerance. Returns (positions, triangles, old -> new index map)."""
    keys = np.round(positions / tolerance).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    tris = inverse[triangles]
    keep = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    return positions[first], tris[keep], inverse


def _plane_quadric(p0, n):
    d = -np.dot(n, p0)
    v = np.array([n[0], n[1], n[2], d])
    return np.outer(v, v)


def simplify(positions, triangles, target, boundary_weight=100.0, attributes=None, lock_boundary=False):
    """Collapse edges until at most `target` triangles remain. Returns (positions, triangles), plus
    the surviving vertices' attributes ((N, k) per-vertex values) when given."""
    pos = [np.asarray(p, dtype=float) for p in positions]
    attr = None if attributes is None else [np.asarray(a, dtype=float) for a in attributes]
    tris = [list(t) for t in triangles]
    alive = [True] * len(tris)
    vert_tris = [set() for _ in pos]
    for i, t in enumerate(tris):
        for v in t:
            vert_tris[v].add(i)

    quad = [np.zeros((4, 4)) for _ in pos]
    edge_count = {}
    for i, t in enumerate(tris):
        a, b, c = (pos[v] for v in t)
        n = np.cross(b - a, c - a)
        area = np.linalg.norm(n)
        if area < 1e-14:
            continue
        n = n / area
        q = _plane_quadric(a, n) * area
        for v in t:
            quad[v] += q
        for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            key = (min(e), max(e))
            edge_count[key] = edge_count.get(key, 0) + 1
    # Boundary edges: a plane through the edge, perpendicular to its face, keeps the outline.
    for i, t in enumerate(tris):
        a, b, c = (pos[v] for v in t)
        fn = np.cross(b - a, c - a)
        if np.linalg.norm(fn) < 1e-14:
            continue
        fn /= np.linalg.norm(fn)
        for u, w in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            if edge_count[(min(u, w), max(u, w))] == 1:
                ev = pos[w] - pos[u]
                length = np.linalg.norm(ev)
                if length < 1e-12:
                    continue
                n = np.cross(ev / length, fn)
                q = _plane_quadric(pos[u], n) * boundary_weight * length
                quad[u] += q
                quad[w] += q

    version = [0] * len(pos)
    locked = set()
    if lock_boundary:
        for (u, w), count in edge_count.items():
            if count == 1:
                locked.update((u, w))

    def cost(u, w):
        q = quad[u] + quad[w]
        if u in locked or w in locked:
            if u in locked and w in locked:
                return float("inf"), None
            p = pos[u] if u in locked else pos[w]
            v4 = np.append(p, 1.0)
            return float(v4 @ q @ v4), p
        best, best_err = None, None
        a = q.copy()
        a[3] = [0, 0, 0, 1]
        try:
            if abs(np.linalg.det(a)) > 1e-10:
                best = np.linalg.solve(a, [0, 0, 0, 1])[:3]
        except np.linalg.LinAlgError:
            best = None
        # Nearly flat or thin regions make the quadric nearly singular, and its optimum can land far
        # off the surface (spikes); keep it only near the edge.
        if best is not None and np.linalg.norm(best - (pos[u] + pos[w]) / 2) > np.linalg.norm(pos[u] - pos[w]):
            best = None
        candidates = [pos[u], pos[w], (pos[u] + pos[w]) / 2] + ([best] if best is not None else [])
        for p in candidates:
            v4 = np.append(p, 1.0)
            err = float(v4 @ q @ v4)
            if best_err is None or err < best_err:
                best_err, best_p = err, p
        return best_err, best_p

    heap = []
    for (u, w) in edge_count:
        err, p = cost(u, w)
        heap.append((err, u, w, version[u], version[w]))
    heapq.heapify(heap)

    live = sum(alive)
    while live > target and heap:
        err, u, w, vu, vw = heapq.heappop(heap)
        if err == float("inf"):
            break
        if version[u] != vu or version[w] != vw or not vert_tris[u] or not vert_tris[w]:
            continue
        shared = vert_tris[u] & vert_tris[w]
        if not shared:
            continue
        err, p = cost(u, w)
        if p is None:
            continue
        # Reject collapses that flip a surviving triangle around u or w.
        flips = False
        for t_index in (vert_tris[u] | vert_tris[w]) - shared:
            t = tris[t_index]
            before = np.cross(pos[t[1]] - pos[t[0]], pos[t[2]] - pos[t[0]])
            moved = [p if v in (u, w) else pos[v] for v in t]
            after = np.cross(moved[1] - moved[0], moved[2] - moved[0])
            if np.dot(before, after) <= 0:
                flips = True
                break
        if flips:
            continue
        # Collapse w into u.
        if attr is not None:
            if w in locked:
                attr[u] = attr[w]
            elif u not in locked:
                edge = pos[w] - pos[u]
                t = float(np.clip(np.dot(p - pos[u], edge) / max(np.dot(edge, edge), 1e-20), 0, 1))
                attr[u] = attr[u] * (1 - t) + attr[w] * t
        if w in locked:
            locked.discard(w)
            locked.add(u)
        pos[u] = p
        quad[u] = quad[u] + quad[w]
        for t_index in shared:
            alive[t_index] = False
            for v in tris[t_index]:
                vert_tris[v].discard(t_index)
            live -= 1
        for t_index in list(vert_tris[w]):
            t = tris[t_index]
            tris[t_index] = [u if v == w else v for v in t]
            vert_tris[u].add(t_index)
        vert_tris[w] = set()
        version[u] += 1
        version[w] += 1
        neighbours = {v for t_index in vert_tris[u] for v in tris[t_index]} - {u}
        for v in neighbours:
            e, _ = cost(u, v)
            if e != float("inf"):
                heapq.heappush(heap, (e, min(u, v), max(u, v), version[min(u, v)], version[max(u, v)]))

    used = sorted({v for i, t in enumerate(tris) if alive[i] for v in t})
    remap = {v: k for k, v in enumerate(used)}
    out_tris = np.array([[remap[v] for v in t] for i, t in enumerate(tris) if alive[i]], dtype=int).reshape(-1, 3)
    if attr is None:
        return np.array([pos[v] for v in used]), out_tris
    return np.array([pos[v] for v in used]), out_tris, np.array([attr[v] for v in used])


def vertex_normals(positions, triangles):
    n = np.zeros_like(positions)
    fn = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                  positions[triangles[:, 2]] - positions[triangles[:, 0]])
    for k in range(3):
        np.add.at(n, triangles[:, k], fn)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)
