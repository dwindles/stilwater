"""A texture layout of its own for a mesh whose UVs repeat a tile (SR2's leather biker pants), so a
one-off print can be baked onto it: each of the mesh's UV islands (its vertices are already split
along their edges) is flattened by least-squares conformal maps (Levy et al. 2002) and packed into
the square (tools/mesh/unwrap.py's shelves). The vertex count stays, so the skinning and the body
shapes still fit.
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import lsqr

import unwrap


def islands(mesh):
    """UV island of each triangle: triangles joined through shared vertices."""
    t = mesh["triangles"]
    n = len(mesh["positions"])
    edges = np.concatenate([t[:, [0, 1]], t[:, [1, 2]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(n, n))
    return connected_components(graph, directed=False)[1][t[:, 0]]


def lscm(positions, normals, triangles):
    """2D coordinates (V, 2) for a disc-shaped piece, at its 3D scale. The strips' winding isn't
    consistent, so each triangle's facing comes from its vertex normals."""
    rows, cols, vals = [], [], []
    for k, tri in enumerate(triangles):
        p = positions[tri]
        e1 = p[1] - p[0]
        length = np.linalg.norm(e1)
        if length < 1e-9:
            continue
        x = e1 / length
        n = np.cross(e1, p[2] - p[0])
        area = np.linalg.norm(n) / 2
        if area < 1e-12:
            continue
        n /= 2 * area
        if np.dot(n, normals[tri].sum(axis=0)) < 0:
            n = -n
        y = np.cross(n, x)
        local = (p - p[0]) @ np.stack([x, y], axis=1)
        scale = 1 / np.sqrt(2 * area)
        for j in range(3):
            a, b = local[(j + 1) % 3], local[(j + 2) % 3]
            wr, wi = (b[0] - a[0]) * scale, (b[1] - a[1]) * scale
            # Real and imaginary parts of sum_j W_j (u_j + i v_j).
            rows += [2 * k, 2 * k, 2 * k + 1, 2 * k + 1]
            cols += [2 * tri[j], 2 * tri[j] + 1, 2 * tri[j], 2 * tri[j] + 1]
            vals += [wr, -wi, wi, wr]
    count = len(positions)
    matrix = coo_matrix((vals, (rows, cols)), shape=(2 * len(triangles), 2 * count)).tocsc()
    # Pin the two vertices furthest apart, at their distance along u.
    far = np.argmax(np.linalg.norm(positions - positions[0], axis=1))
    other = np.argmax(np.linalg.norm(positions - positions[far], axis=1))
    pinned = {2 * far: 0.0, 2 * far + 1: 0.0, 2 * other: np.linalg.norm(positions[far] - positions[other]),
              2 * other + 1: 0.0}
    free = np.array([c for c in range(2 * count) if c not in pinned])
    fixed = np.array(list(pinned))
    rhs = -matrix[:, fixed] @ np.array([pinned[c] for c in fixed])
    solution = lsqr(matrix[:, free], rhs, atol=1e-12, btol=1e-12)[0]
    out = np.zeros(2 * count)
    out[free] = solution
    out[fixed] = [pinned[c] for c in fixed]
    return out.reshape(-1, 2)


def layout(mesh, padding=4.0):
    """New UVs (V, 2) in 0..1, v down, every island flattened and packed at one density, about
    padding texels of a 1024 texture apart."""
    island = islands(mesh)
    charts, members = [], []
    for i in np.unique(island):
        tris = mesh["triangles"][island == i]
        verts = np.unique(tris)
        local = np.full(len(mesh["positions"]), -1)
        local[verts] = np.arange(len(verts))
        flat = lscm(mesh["positions"][verts], mesh["normals"][verts], local[tris])
        charts.append((None, flat[local[tris]]))
        members.append((tris, verts, local, flat))
    area = sum(np.abs(np.cross(f[:, 1] - f[:, 0], f[:, 2] - f[:, 0])).sum() / 2 for _, f in charts)
    placed, _ = unwrap.pack([(charts, 900 / np.sqrt(area))], padding)    # about 1024 texels across
    uv = np.zeros((len(mesh["positions"]), 2))
    for (tris, verts, local, flat), coords in zip(members, placed[0]):
        uv[tris.reshape(-1)] = coords.reshape(-1, 2)
    return uv
