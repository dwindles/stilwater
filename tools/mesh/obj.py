"""Read Wavefront OBJ meshes: positions, per-corner UVs and normals, triangles grouped by material,
enough to bake a model's textures.

    python obj.py <file.obj>      # lists the materials and their triangle counts
"""
import sys
from collections import defaultdict

import numpy as np


def read(path):
    """dict(positions (N,3), uvs (U,2), normals (K,3), groups {material: dict(vertex (M,3), uv (M,3),
    normal (M,3))}): faces fan-triangulated, -1 where a corner has no UV or normal."""
    positions, uvs, normals = [], [], []
    groups = defaultdict(lambda: ([], [], []))
    material = ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            kind = parts[0]
            if kind == "v":
                positions.append([float(x) for x in parts[1:4]])
            elif kind == "vt":
                uvs.append([float(x) for x in parts[1:3]])
            elif kind == "vn":
                normals.append([float(x) for x in parts[1:4]])
            elif kind == "usemtl":
                material = parts[1] if len(parts) > 1 else ""
            elif kind == "f":
                corners = []
                for c in parts[1:]:
                    fields = (c.split("/") + ["", ""])[:3]
                    v, t, n = (int(x) if x else 0 for x in fields)
                    # Negative indices count back from the end; 0 means absent.
                    corners.append((v - 1 if v > 0 else len(positions) + v,
                                    (t - 1 if t > 0 else len(uvs) + t) if t else -1,
                                    (n - 1 if n > 0 else len(normals) + n) if n else -1))
                g = groups[material]
                for k in range(1, len(corners) - 1):
                    tri = (corners[0], corners[k], corners[k + 1])
                    for slot in range(3):
                        g[slot].append([c[slot] for c in tri])
    return dict(positions=np.array(positions), uvs=np.array(uvs).reshape(-1, 2), normals=np.array(normals).reshape(-1, 3),
                groups={m: dict(vertex=np.array(v), uv=np.array(t), normal=np.array(n)) for m, (v, t, n) in groups.items()})


def main(argv):
    mesh = read(argv[1])
    p = mesh["positions"]
    print(f"{len(p)} vertices, bbox {np.round(p.min(0), 3)} .. {np.round(p.max(0), 3)}, {len(mesh['uvs'])} uvs")
    for name, g in mesh["groups"].items():
        print(f"  {name}: {len(g['vertex'])} triangles")


if __name__ == "__main__":
    main(sys.argv)
