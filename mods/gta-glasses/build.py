"""Build the GTA V glasses (glasses.py): SR2's "designer shades" reshaped like each GTA V glasses prop
and printed with its colourway, lens tint and see-through included, each under a new name.

As mods/gta-shoes does with shoes: the game's vertices are pulled onto the GTA model's surface (the
vertex count stays, so the head-shape morphs still fit), then the GTA texture is baked onto the
game's UVs. A GTA glasses prop sits in the head bone's frame (x up the head, z across it, the lenses
toward +y); which way up and which way round it goes on the game's shades is the turn of it that
fits them best, a reflection included, since GTA is right-handed and SR2 left-handed.

    python build.py [game folder] [GTA clothes folder]     # writes out/STILWATER - GTA Glasses/
"""
import importlib.util
import itertools
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
import clothing  # noqa: E402
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402
from glasses import GLASSES, MODELS, SOURCE  # noqa: E402

spec = importlib.util.spec_from_file_location("uptempo", ROOT / "mods" / "holdonquietly-uptempo" / "build.py")
uptempo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uptempo)

DIFFUSE, BUMP, TINT = f"{SOURCE}_d.tga", f"{SOURCE}_n.tgn", f"{SOURCE}_p.tga"
MOD_NAME = "STILWATER - GTA Glasses"
SAMPLES = 300_000
WORK = 512


def rename(data, base):
    assert len(base) == len(SOURCE)
    return re.sub(re.escape(SOURCE.encode()), base.encode(), data, flags=re.I)


def gta_model(path):
    """(positions, normals, uvs, triangles) of a GTA prop's high LOD, in its own frame."""
    positions, normals, uvs, triangles = [], [], [], []
    count = 0
    for model in yft.read_dictionary(path)[0]["lods"]["high"]:
        for g in model["geometries"]:
            positions.append(g["positions"])
            normals.append(g["normals"])
            # GTA's v runs down the texture (bake.bilinear's runs up).
            uvs.append(g["uvs"] * [1, -1])
            triangles.append(g["triangles"].astype(np.int64) + count)
            count += len(g["positions"])
    normals = np.concatenate(normals)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return np.concatenate(positions), normals, np.concatenate(uvs), np.concatenate(triangles)


def orient(positions, target):
    """The 3x3 matrix taking a GTA prop onto the game's shades: across (GTA z) to x, up (x) to y,
    forward (y) to z, each either way round, with an odd number of flips (right- to left-handed);
    the one whose box-fitted shape lies closest to target."""
    best = None
    for signs in itertools.product((1, -1), repeat=3):
        if np.prod(signs) > 0:
            continue
        matrix = np.diag(signs) @ np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        fitted, _ = uptempo.fit_box(positions @ matrix.T, target)
        score = uptempo.chamfer(fitted[::7], target)
        if best is None or score < best[0]:
            best = (score, matrix, signs)
    print(f"   oriented {best[2]} (chamfer {best[0]:.4f})")
    return best[1]


def main(game, clothes):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), ("_pc.morph_pc", "meshes"),
                      (".peg_pc", "pegs"), (".g_peg_pc", "textures")):
        if not (original / f"{SOURCE}{ext}").exists():
            (original / f"{SOURCE}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{SOURCE}{ext}"))
    game_mesh = cmesh.load(original / f"{SOURCE}.cmesh_pc", original / f"{SOURCE}.g_cmesh_pc")

    header = peg.read_header(original / f"{SOURCE}.peg_pc")
    vanilla_data = (original / f"{SOURCE}.g_peg_pc").read_bytes()
    sizes = clothing.fit_sizes([e["name"] for e in header], len(vanilla_data),
                               {DIFFUSE: "diffuse_alpha", BUMP: "bump", TINT: "tint"})
    (dw, dh, dl), (bw, bh, bl), (tw, th, tl) = sizes[DIFFUSE], sizes[BUMP], sizes[TINT]
    tint, _ = peg.encode(Image.new("RGB", (tw, th), (0, 0, 255)), "DXT1", max_levels=tl)

    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    for name in sorted({g["model"] for g in GLASSES}):
        subfolder, ydd = MODELS[name]
        positions, normals, uvs, triangles = gta_model(clothes / subfolder / ydd)
        print(f"{name}: {len(positions)} vertices, {len(triangles)} triangles")
        matrix = orient(positions, game_mesh["positions"])
        fitted, scale = uptempo.fit_box(positions @ matrix.T, game_mesh["positions"])
        n = (normals @ matrix.T) / scale
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        points, sample_uvs, sample_normals, _ = bake.sample_surface(fitted, triangles, uvs, n, SAMPLES)

        new_p, new_n = uptempo.wrap(game_mesh["positions"], game_mesh["triangles"], game_mesh["normals"],
                                    points, sample_normals)
        moved = np.linalg.norm(new_p - game_mesh["positions"], axis=1)
        print(f"   moved {1000 * moved.mean():.1f} mm on average, up to {1000 * moved.max():.1f} mm")

        rows, cols, tris, w = bake.rasterize(game_mesh["uvs"], game_mesh["triangles"], WORK)
        corners = game_mesh["triangles"][tris]
        texel_points = (w[..., None] * new_p[corners]).sum(axis=1)
        texel_normals = (w[..., None] * new_n[corners]).sum(axis=1)
        texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
        nearest = bake.nearest_facing(cKDTree(points), sample_normals, texel_points, texel_normals)
        texel_uvs = sample_uvs[nearest]

        data = bytearray((original / f"{SOURCE}.g_cmesh_pc").read_bytes())
        stride = game_mesh["stride"]
        for i, (p, nn) in enumerate(zip(new_p, new_n)):
            struct.pack_into("<3f", data, i * stride, *p)
            data[i * stride + 20:i * stride + 23] = bytes(np.clip(np.round((nn + 1) * 127.5), 0, 255).astype(np.uint8))

        for item in [g for g in GLASSES if g["model"] == name]:
            (texture_name, (w_, h_, fmt, levels, buf, off)), = ytd.textures(clothes / subfolder / item["ytd"]).items()
            texture = np.asarray(ytd.to_image(w_, h_, fmt, buf, off).convert("RGBA")).astype(float) / 255
            image = np.zeros((WORK, WORK, 4))
            covered = np.zeros((WORK, WORK), bool)
            image[rows, cols] = bake.bilinear(texture, texel_uvs)
            covered[rows, cols] = True
            image = Image.fromarray((np.clip(bake.dilate(image, covered), 0, 1) * 255).astype(np.uint8), "RGBA")
            image.save(out / f"{item['base']}_diffuse.png")
            diffuse, _ = peg.encode(image.resize((dw, dh), Image.LANCZOS), "DXT5", max_levels=dl)
            bump, _ = peg.encode(clothing.bump_from(image.convert("RGB"), bw, bh).convert("RGBA"), "DXT5", max_levels=bl)
            replacements = {DIFFUSE: (dw, dh, clothing.DXT5, dl, diffuse), BUMP: (bw, bh, clothing.DXT5, bl, bump),
                            TINT: (tw, th, clothing.DXT1, tl, tint)}
            peg_header, pack = peg.rebuild(original / f"{SOURCE}.peg_pc", original / f"{SOURCE}.g_peg_pc", replacements)
            assert len(pack) == len(vanilla_data), (len(pack), len(vanilla_data))
            base = item["base"]
            (folder / f"{base}.peg_pc").write_bytes(rename(peg_header, base))
            (folder / f"{base}.g_peg_pc").write_bytes(pack)
            (folder / f"{base}.cmesh_pc").write_bytes(rename((original / f"{SOURCE}.cmesh_pc").read_bytes(), base))
            (folder / f"{base}.g_cmesh_pc").write_bytes(bytes(data))
            # The head shapes (the face sliders): without them the glasses don't sit on the face.
            (folder / f"{base}_pc.morph_pc").write_bytes((original / f"{SOURCE}_pc.morph_pc").read_bytes())
            print(f"   {item['name']}: {base} ({texture_name})")
    print(f"built {folder}: diffuse {dw}x{dh} ({dl} mips), bump {bw}x{bh} ({bl}), tint {tw}x{th} ({tl})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\gta-clothes"))
