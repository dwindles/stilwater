"""Build the GTA V tops (tops.py): SR2 tops reshaped like GTA V ones and printed with their colourways,
each under a new name.

As mods/gta-jeans does with jeans: each of the item's meshes has its vertices pulled onto the GTA
top's surface, stretched to the mesh's box (the vertex count stays, so the skinning and body-shape
morphs still fit), and that mesh's texture is baked from the GTA texture, the outermost layer where
the GTA top has several (pockets, zips). The GTA ped frame is turned as for the shoes (gta-shoes).
Each pack keeps its exact vanilla size (tools/sr2/clothing.py picks the texture sizes), with a bump
map made from the new diffuse.

    python build.py [game folder] [GTA clothes folder]     # writes out/STILWATER - GTA Tops/
"""
import importlib.util
import re
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
sys.path.insert(0, str(ROOT / "tools" / "gta5"))
sys.path.insert(0, str(ROOT / "mods" / "gta-shoes"))
import bake  # noqa: E402
import clothing  # noqa: E402
import cmesh  # noqa: E402
import vpp  # noqa: E402
import ytd  # noqa: E402
from tops import GROUPS, TOPS  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uptempo = load("uptempo", ROOT / "mods" / "holdonquietly-uptempo" / "build.py")
shoes = load("gta_shoes", ROOT / "mods" / "gta-shoes" / "build.py")
uptempo.MAX_MOVE = 0.06    # a GTA top sits further from the game's than a shoe from a shoe

MOD_NAME = "STILWATER - GTA Tops"
SAMPLES = 600_000
WORK = 1024


def rename(data, source, base):
    assert len(base) == len(source)
    return re.sub(re.escape(source.encode()), base.encode(), data, flags=re.I)


def fit(mesh, model):
    """(positions, normals of mesh pulled onto model, the model's surface samples (points, uvs, normals))."""
    positions, normals, uvs, triangles = model
    fitted, scale = uptempo.fit_box(positions, mesh["positions"])
    n = normals / scale
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    points, sample_uvs, sample_normals, _ = bake.sample_surface(fitted, triangles, uvs, n, SAMPLES)
    new_p, new_n = uptempo.wrap(mesh["positions"], mesh["triangles"], mesh["normals"], points, sample_normals)
    return new_p, new_n, (points, sample_uvs, sample_normals)


def texel_lookup(mesh, positions, normals, samples, left_out=None):
    """(rows, cols, the model UV each texel of mesh's layout shows), none from the left_out area."""
    points, sample_uvs, sample_normals = samples
    if left_out:
        x, y = np.mod(sample_uvs[:, 0], 1), 1 - np.mod(sample_uvs[:, 1], 1)
        keep = ~((x >= left_out[0]) & (y >= left_out[1]) & (x <= left_out[2]) & (y <= left_out[3]))
        points, sample_uvs, sample_normals = points[keep], sample_uvs[keep], sample_normals[keep]
    rows, cols, tris, w = bake.rasterize(mesh["uvs"], mesh["triangles"], WORK, wrap=True)
    corners = mesh["triangles"][tris]
    texel_points = (w[..., None] * positions[corners]).sum(axis=1)
    texel_normals = (w[..., None] * normals[corners]).sum(axis=1)
    texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
    nearest = bake.nearest_facing(cKDTree(points), sample_normals, texel_points, texel_normals, outermost=True)
    return rows, cols, sample_uvs[nearest]


def main(game, clothes):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    work = out / "pack"
    for group_name, group in GROUPS.items():
        source = group["source"]
        for suffix, (ydd, textures, prefix, diffuse, bump, *left_out) in group["meshes"].items():
            name = f"{source}_{suffix}"
            for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), ("_pc.morph_pc", "meshes")):
                if not (original / f"{name}{ext}").exists():
                    (original / f"{name}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{name}{ext}"))
            mesh = cmesh.load(original / f"{name}.cmesh_pc", original / f"{name}.g_cmesh_pc")
            model = shoes.gta_shoe(clothes / ydd)
            new_p, new_n, samples = fit(mesh, model)
            moved = np.linalg.norm(new_p - mesh["positions"], axis=1)
            print(f"{name} onto {ydd}: moved {100 * moved.mean():.1f} cm on average, up to {100 * moved.max():.1f} cm")
            raw = bytearray((original / f"{name}.g_cmesh_pc").read_bytes())
            for i, (p, n) in enumerate(zip(new_p, new_n)):
                struct.pack_into("<3f", raw, i * mesh["stride"], *p)
                raw[i * mesh["stride"] + 20:i * mesh["stride"] + 23] = bytes(np.clip(np.round((n + 1) * 127.5), 0, 255).astype(np.uint8))
            rows, cols, texel_uvs = texel_lookup(mesh, new_p, new_n, samples, left_out[0] if left_out else None)

            for top in [t for t in TOPS if t["group"] == group_name]:
                path = clothes / textures / f"{prefix}_{top['colour']}_uni.ytd"
                (texture_name, (w_, h_, fmt, levels, buf, off)), = ytd.textures(path).items()
                texture = np.asarray(ytd.to_image(w_, h_, fmt, buf, off).convert("RGB")).astype(float) / 255
                image = np.zeros((WORK, WORK, 3))
                covered = np.zeros((WORK, WORK), bool)
                image[rows, cols] = bake.bilinear(texture, texel_uvs)
                covered[rows, cols] = True
                image = Image.fromarray((np.clip(bake.dilate(image, covered), 0, 1) * 255).astype(np.uint8))
                base = top["base"]
                clone = f"{base}_{suffix}"
                image.save(out / f"{clone}_diffuse.png")
                summary = clothing.rebuild_pack(game, original, name, source + diffuse, source + bump, image, work,
                                                sides={"bump": (512, 256, 128, 64, 32, 16)})
                (folder / f"{clone}.peg_pc").write_bytes(rename((work / f"{name}.peg_pc").read_bytes(), source, base))
                (folder / f"{clone}.g_peg_pc").write_bytes((work / f"{name}.g_peg_pc").read_bytes())
                (folder / f"{clone}.cmesh_pc").write_bytes(rename((original / f"{name}.cmesh_pc").read_bytes(), source, base))
                (folder / f"{clone}.g_cmesh_pc").write_bytes(bytes(raw))
                # The body shapes (the sliders): without them the top is the wrong size.
                (folder / f"{clone}_pc.morph_pc").write_bytes((original / f"{name}_pc.morph_pc").read_bytes())
                print(f"   {top['name']}: {clone} ({texture_name}; {summary.split(': ', 1)[1]})")
    print(f"built {folder}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\gta-clothes"))
