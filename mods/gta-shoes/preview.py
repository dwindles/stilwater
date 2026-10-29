"""Side views of built shoes (texel splats of the finished mesh and texture): python preview.py base..."""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import cmesh  # noqa: E402

folder = HERE / "out" / "STILWATER - GTA Shoes"
rows = []
for base in sys.argv[1:]:
    mesh = cmesh.load(folder / f"{base}.cmesh_pc", folder / f"{base}.g_cmesh_pc")
    texture = np.asarray(Image.open(HERE / "out" / f"{base}_diffuse.png").convert("RGB").resize((1024, 512)))
    pos, nrm, covered = cmesh.bake(mesh, 1024, 512)
    views = []
    for axis, sign, horizontal in ((0, 1, 2), (0, -1, 2), (1, 1, 2)):
        canvas = np.full((300, 300, 3), 220, np.uint8)
        depth = np.full((300, 300), -1e9)
        sel = covered & (sign * nrm[..., axis] > 0.1)
        p, c = pos[sel], texture[sel]
        centre = pos[covered].mean(axis=0)
        h = ((p[:, horizontal] - centre[horizontal]) * sign * (1 if axis == 0 else 1) * 900 + 150).astype(int)
        v_axis = 1 if axis == 0 else 0
        v = (150 - (p[:, v_axis] - centre[v_axis]) * 900).astype(int)
        d = sign * p[:, axis]
        order = np.argsort(d)
        for i in order:
            if 0 <= h[i] < 300 and 0 <= v[i] < 300:
                canvas[v[i], h[i]] = c[i]
        views.append(canvas)
    rows.append(np.concatenate(views, axis=1))
Image.fromarray(np.concatenate(rows, axis=0)).save(HERE / "out" / "preview.png")
