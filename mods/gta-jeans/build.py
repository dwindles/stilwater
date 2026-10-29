"""Build the GTA V jeans (jeans.py): SR2's "men's loose jeans" reshaped like each GTA V pair and printed
with its colourway, each under a new name.

As mods/gta-shoes does with shoes: each of the game's two meshes (worn at the waist, M, and low, L)
has its vertices pulled onto the GTA jeans' surface, stretched to the mesh's box (the vertex count
stays, so the skinning and body-shape morphs still fit), and the GTA texture is baked onto the
game's UVs from the M mesh; both packs get that texture, since they share the texture names. The
GTA ped frame is turned the same way as for the shoes (gta-shoes TURN). The GTA jeans sag lower at
the back than at the front, which would put their boxers and lining on the seat: for the texture
they are stretched up from their hems until their denim reaches just under the game's waistband at the back, and below
the height where the boxers then start at the front, the texture takes the nearest denim. Parts of
the GTA texture that are stretched filler (between the legs, where GTA never shows them) are left
out, so the game's crotch takes the nearest proper denim.

The pack keeps its exact vanilla size, because clothing streams into fixed-size slots: only the
diffuse changes, at its vanilla size.

    python build.py [game folder] [GTA clothes folder]     # writes out/STILWATER - GTA Jeans/
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
import bake  # noqa: E402
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402
import ytd  # noqa: E402
from jeans import JEANS, MODELS, SOURCE, SUFFIXES  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


uptempo = load("uptempo", ROOT / "mods" / "holdonquietly-uptempo" / "build.py")
sys.path.insert(0, str(ROOT / "mods" / "gta-shoes"))
shoes = load("gta_shoes", ROOT / "mods" / "gta-shoes" / "build.py")
uptempo.MAX_MOVE = 0.06    # baggy jeans sit further from the game's than a shoe from a shoe

DIFFUSE = f"{SOURCE}_d.tga"
MOD_NAME = "STILWATER - GTA Jeans"
SAMPLES = 600_000
WORK = 1024
WAISTBAND = 0.03   # metres of the game's waistband above the GTA denim at the back of the seat


def rename(data, base):
    assert len(base) == len(SOURCE)
    return re.sub(re.escape(SOURCE.encode()), base.encode(), data, flags=re.I)


def main(game, clothes):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    for s in SUFFIXES:
        name = f"{SOURCE}_{s}"
        for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), ("_pc.morph_pc", "meshes"),
                          (".peg_pc", "pegs"), (".g_peg_pc", "textures")):
            if not (original / f"{name}{ext}").exists():
                (original / f"{name}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{name}{ext}"))
    meshes = {s: cmesh.load(original / f"{SOURCE}_{s}.cmesh_pc", original / f"{SOURCE}_{s}.g_cmesh_pc") for s in SUFFIXES}
    vanilla = next(e for e in peg.read_header(original / f"{SOURCE}_m.peg_pc") if e["name"] == DIFFUSE)

    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    for model_name in sorted({j["model"] for j in JEANS}):
        subfolder, ydd, boxers, filler = MODELS[model_name]
        positions, normals, uvs, triangles = shoes.gta_shoe(clothes / subfolder / ydd)
        print(f"{model_name}: {len(positions)} vertices, {len(triangles)} triangles")

        data, lookup = {}, None
        for s in SUFFIXES:
            mesh = meshes[s]
            fitted, scale = uptempo.fit_box(positions, mesh["positions"])
            n = normals / scale
            n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
            points, sample_uvs, sample_normals, _ = bake.sample_surface(fitted, triangles, uvs, n, SAMPLES)
            new_p, new_n = uptempo.wrap(mesh["positions"], mesh["triangles"], mesh["normals"], points, sample_normals)
            moved = np.linalg.norm(new_p - mesh["positions"], axis=1)
            print(f"   {s}: moved {100 * moved.mean():.1f} cm on average, up to {100 * moved.max():.1f} cm")

            raw = bytearray((original / f"{SOURCE}_{s}.g_cmesh_pc").read_bytes())
            stride = mesh["stride"]
            for i, (p, nn) in enumerate(zip(new_p, new_n)):
                struct.pack_into("<3f", raw, i * stride, *p)
                raw[i * stride + 20:i * stride + 23] = bytes(np.clip(np.round((nn + 1) * 127.5), 0, 255).astype(np.uint8))
            data[s] = bytes(raw)

            if s == "m":
                rows, cols, tris, w = bake.rasterize(mesh["uvs"], mesh["triangles"], WORK)
                corners = mesh["triangles"][tris]
                texel_points = (w[..., None] * new_p[corners]).sum(axis=1)
                texel_normals = (w[..., None] * new_n[corners]).sum(axis=1)
                texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
                def inside(box, x, y):
                    return (x >= box[0]) & (y >= box[1]) & (x <= box[2]) & (y <= box[3])

                x, y = np.mod(sample_uvs[:, 0], 1), 1 - np.mod(sample_uvs[:, 1], 1)
                shown = ~np.any([inside(box, x, y) for box in filler], axis=0) if filler else np.ones(len(x), bool)
                points, sample_uvs, sample_normals = points[shown], sample_uvs[shown], sample_normals[shown]
                underwear = inside(boxers, x[shown], y[shown])
                # Stretch the GTA jeans up from their hems (for the texture only) until their denim
                # at the back of the seat reaches just under the game's waistband there.
                seat = ~underwear & (sample_normals[:, 2] < -0.5) & (np.abs(points[:, 0]) < 0.1)
                back = mesh["positions"][(mesh["positions"][:, 2] < 0) & (np.abs(mesh["positions"][:, 0]) < 0.1)]
                hem, top = points[:, 1].min(), np.percentile(points[seat, 1], 99)
                stretch = max(1.0, (back[:, 1].max() - WAISTBAND - hem) / (top - hem))
                points = points.copy()
                points[:, 1] = hem + (points[:, 1] - hem) * stretch
                print(f"   texture stretched up {100 * (stretch - 1):.0f}%")
                nearest = bake.nearest_facing(cKDTree(points), sample_normals, texel_points, texel_normals, outermost=True)
                front = underwear[nearest] & (texel_normals[:, 2] > 0.3)
                cut = np.percentile(texel_points[front, 1], 5)
                denim = np.flatnonzero(~underwear)
                low = underwear[nearest] & (texel_points[:, 1] < cut)
                nearest[low] = denim[bake.nearest_facing(cKDTree(points[denim]), sample_normals[denim],
                                                         texel_points[low], texel_normals[low], outermost=True)]
                print(f"   boxers from {cut:.3f} m up; {low.sum()} texels below that moved to denim")
                lookup = (rows, cols, sample_uvs[nearest])
                cells = rows * WORK + cols
                print(f"   UV texels shared by more than one triangle: {100 * (1 - len(np.unique(cells)) / len(cells)):.0f}%")

        for item in [j for j in JEANS if j["model"] == model_name]:
            (texture_name, (w_, h_, fmt, levels, buf, off)), = ytd.textures(clothes / subfolder / item["ytd"]).items()
            texture = np.asarray(ytd.to_image(w_, h_, fmt, buf, off).convert("RGB")).astype(float) / 255
            rows, cols, texel_uvs = lookup
            image = np.zeros((WORK, WORK, 3))
            covered = np.zeros((WORK, WORK), bool)
            image[rows, cols] = bake.bilinear(texture, texel_uvs)
            covered[rows, cols] = True
            image = Image.fromarray((np.clip(bake.dilate(image, covered), 0, 1) * 255).astype(np.uint8))
            image.save(out / f"{item['base']}_diffuse.png")
            image = image.resize((vanilla["width"], vanilla["height"]), Image.LANCZOS)
            blob, mips = peg.encode_dxt1(image, max_levels=vanilla["mips"])
            assert len(blob) == vanilla["size"], (len(blob), vanilla["size"])
            base = item["base"]
            for s in SUFFIXES:
                name, clone = f"{SOURCE}_{s}", f"{base}_{s}"
                header, pack = peg.rebuild(original / f"{name}.peg_pc", original / f"{name}.g_peg_pc",
                                           {DIFFUSE: (image.width, image.height, 0x190, mips, blob)})
                assert len(pack) == (original / f"{name}.g_peg_pc").stat().st_size, name
                (folder / f"{clone}.peg_pc").write_bytes(rename(header, base))
                (folder / f"{clone}.g_peg_pc").write_bytes(pack)
                (folder / f"{clone}.cmesh_pc").write_bytes(rename((original / f"{name}.cmesh_pc").read_bytes(), base))
                (folder / f"{clone}.g_cmesh_pc").write_bytes(data[s])
                # The body shapes (the sliders): without them the jeans are the wrong size.
                (folder / f"{clone}_pc.morph_pc").write_bytes((original / f"{name}_pc.morph_pc").read_bytes())
            print(f"   {item['name']}: {base}_m/_l ({texture_name})")
    print(f"built {folder}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\gta-clothes"))
