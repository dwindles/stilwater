"""Build the GTA V sneakers (shoes.py): SR2's "sports shoes with strap" reshaped like each GTA V shoe
and printed with its colourway, each under a new name.

The way HOQ Uptempo (mods/holdonquietly-uptempo) puts a scanned shoe on the game's: the game shoe's
vertices are pulled onto the GTA shoe's surface (its skinning and body-shape morphs stay as they
are), then its texture is baked onto the game shoe's UVs, each foot into its own half since the
game's feet share one UV layout. The GTA ped frame is right-handed with z up, so
SR2's (x, y, z) is GTA's (-x, z, -y) (TURN), which also turns it left-handed like SR2; a GTA pair has both
feet (the ped faces -y), and the turn puts the right one at +x as in SR2, so each game foot takes the GTA foot on its side.

A clone is the shoe's mesh, texture pack and body shapes copied under the shoe's `base` (same
length as SOURCE, which the mesh and pack name their textures after). Every pack keeps its exact
vanilla size, because clothing streams into fixed-size slots.

    python build.py [game folder] [GTA clothes folder]     # writes out/STILWATER - GTA Shoes/
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
import clothing  # noqa: E402
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402
from shoes import MODELS, SHOES, SOURCE  # noqa: E402

spec = importlib.util.spec_from_file_location("uptempo", ROOT / "mods" / "holdonquietly-uptempo" / "build.py")
uptempo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uptempo)

DIFFUSE, BUMP, TINT = f"{SOURCE}_d.tga", f"{SOURCE}_n.tgn", f"{SOURCE}_p1.tga"
MOD_NAME = "STILWATER - GTA Shoes"
SAMPLES = 400_000
WORK = 1024
BRIGHTNESS = 1.05
# GTA ped shoes point their toes down -y (their heels are the taller end there), SR2's down +z:
# a half turn about the vertical, after the swap of y and z.
TURN = np.array([-1, 1, -1])


def rename(data, base):
    assert len(base) == len(SOURCE)
    return re.sub(re.escape(SOURCE.encode()), base.encode(), data, flags=re.I)


def gta_shoe(path):
    """(positions, normals, uvs, triangles) of a GTA ped shoe's high LOD, in SR2's frame."""
    positions, normals, uvs, triangles = [], [], [], []
    count = 0
    for model in yft.read_dictionary(path)[0]["lods"]["high"]:
        for g in model["geometries"]:
            p = g["positions"][:, [0, 2, 1]] * TURN
            n = g["normals"][:, [0, 2, 1]] * TURN if "normals" in g else None
            positions.append(p)
            normals.append(n)
            # GTA's v runs down the texture (bake.bilinear's runs up).
            uvs.append(g["uvs"] * [1, -1])
            triangles.append(g["triangles"].astype(np.int64) + count)
            count += len(p)
    positions, triangles = np.concatenate(positions), np.concatenate(triangles)
    if any(n is None for n in normals):
        normals = uptempo.vertex_normals(positions, triangles)
    else:
        normals = np.concatenate(normals)
        normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return positions, normals, np.concatenate(uvs), triangles


def foot_samples(model, game_foot, foot):
    """Points sampled on the GTA foot on this side, fitted to the game foot's box, with their UVs
    and normals."""
    positions, normals, uvs, triangles = model
    side = np.sign(positions[triangles].mean(axis=1)[:, 0]) == foot
    tris = triangles[side]
    used = np.unique(tris)
    fitted, scale = uptempo.fit_box(positions[used], game_foot)
    p = positions.copy()
    p[used] = fitted
    n = normals / scale
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    points, sample_uvs, sample_normals, _ = bake.sample_surface(p, tris, uvs, n, SAMPLES)
    return points, sample_uvs, sample_normals


def main(game, clothes):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), ("_pc.morph_pc", "meshes"),
                      (".peg_pc", "pegs"), (".g_peg_pc", "textures")):
        if not (original / f"{SOURCE}{ext}").exists():
            (original / f"{SOURCE}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{SOURCE}{ext}"))
    game_mesh = cmesh.load(original / f"{SOURCE}.cmesh_pc", original / f"{SOURCE}.g_cmesh_pc")
    side_of = np.sign(game_mesh["positions"][:, 0])

    header = peg.read_header(original / f"{SOURCE}.peg_pc")
    vanilla_data = (original / f"{SOURCE}.g_peg_pc").read_bytes()
    sizes = clothing.fit_sizes([e["name"] for e in header], len(vanilla_data),
                               {DIFFUSE: "diffuse", BUMP: "bump", TINT: "tint"})
    (dw, dh, dl), (bw, bh, bl), (tw, th, tl) = sizes[DIFFUSE], sizes[BUMP], sizes[TINT]
    tint, _ = peg.encode(Image.new("RGB", (tw, th), (0, 0, 255)), "DXT1", max_levels=tl)

    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    for name in sorted({shoe["model"] for shoe in SHOES}):
        subfolder, ydd = MODELS[name]
        model = gta_shoe(clothes / subfolder / ydd)
        print(f"{name}: {len(model[0])} vertices, {len(model[3])} triangles")

        # Wrap each game foot onto its GTA foot, and find which GTA point each texel of it shows.
        positions, normals = game_mesh["positions"].copy(), game_mesh["normals"].copy()
        lookups = {}
        for foot in (1, -1):
            on_foot = side_of == foot
            points, sample_uvs, sample_normals = foot_samples(model, game_mesh["positions"][on_foot], foot)
            foot_tris = game_mesh["triangles"][on_foot[game_mesh["triangles"]].all(axis=1)]
            used = np.unique(foot_tris)
            local = np.full(len(positions), -1)
            local[used] = np.arange(len(used))
            new_p, new_n = uptempo.wrap(positions[used], local[foot_tris], normals[used], points, sample_normals)
            moved = np.linalg.norm(new_p - positions[used], axis=1)
            positions[used], normals[used] = new_p, new_n
            print(f"   foot {foot:+d}: moved {100 * moved.mean():.1f} cm on average, up to {100 * moved.max():.1f} cm")

            rows, cols, tris, w = bake.rasterize(game_mesh["uvs"], foot_tris, WORK)
            corners = foot_tris[tris]
            texel_points = (w[..., None] * positions[corners]).sum(axis=1)
            texel_normals = (w[..., None] * normals[corners]).sum(axis=1)
            texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
            nearest = bake.nearest_facing(cKDTree(points), sample_normals, texel_points, texel_normals)
            lookups[foot] = (rows, cols, sample_uvs[nearest])

        # The mesh: positions, normals, and each foot's UVs squeezed into its half (+x foot left).
        data = bytearray((original / f"{SOURCE}.g_cmesh_pc").read_bytes())
        stride = game_mesh["stride"]
        for i, (p, n) in enumerate(zip(positions, normals)):
            at = i * stride
            struct.pack_into("<3f", data, at, *p)
            data[at + 20:at + 23] = bytes(np.clip(np.round((n + 1) * 127.5), 0, 255).astype(np.uint8))
            u, = struct.unpack_from("<h", data, at + 28)
            struct.pack_into("<h", data, at + 28, round((u + (0 if side_of[i] > 0 else 1024)) / 2))

        for shoe in [s for s in SHOES if s["model"] == name]:
            (texture_name, (w, h, fmt, levels, buf, off)), = ytd.textures(clothes / subfolder / shoe["ytd"]).items()
            texture = np.asarray(ytd.to_image(w, h, fmt, buf, off).convert("RGB")).astype(float) / 255
            halves = {}
            for foot, (rows, cols, sample_uvs) in lookups.items():
                image = np.zeros((WORK, WORK, 3))
                covered = np.zeros((WORK, WORK), bool)
                image[rows, cols] = bake.bilinear(texture, sample_uvs)
                covered[rows, cols] = True
                image = bake.dilate(image, covered)
                halves[foot] = Image.fromarray((np.clip(image * BRIGHTNESS, 0, 1) * 255).astype(np.uint8))

            def both(make, width, height):
                left, right = make(halves[1], width // 2, height), make(halves[-1], width // 2, height)
                image = Image.new(left.mode, (width, height))
                image.paste(left, (0, 0))
                image.paste(right, (width // 2, 0))
                return image

            diffuse_image = both(lambda im, w, h: im.resize((w, h), Image.LANCZOS), dw, dh)
            diffuse_image.save(out / f"{shoe['base']}_diffuse.png")
            diffuse, _ = peg.encode(diffuse_image, "DXT1", max_levels=dl)
            bump, _ = peg.encode(both(lambda im, w, h: clothing.bump_from(im, w, h), bw, bh).convert("RGBA"),
                                 "DXT5", max_levels=bl)
            replacements = {DIFFUSE: (dw, dh, clothing.DXT1, dl, diffuse), BUMP: (bw, bh, clothing.DXT5, bl, bump),
                            TINT: (tw, th, clothing.DXT1, tl, tint)}
            peg_header, pack = peg.rebuild(original / f"{SOURCE}.peg_pc", original / f"{SOURCE}.g_peg_pc", replacements)
            assert len(pack) == len(vanilla_data), (len(pack), len(vanilla_data))
            base = shoe["base"]
            (folder / f"{base}.peg_pc").write_bytes(rename(peg_header, base))
            (folder / f"{base}.g_peg_pc").write_bytes(pack)
            (folder / f"{base}.cmesh_pc").write_bytes(rename((original / f"{SOURCE}.cmesh_pc").read_bytes(), base))
            (folder / f"{base}.g_cmesh_pc").write_bytes(bytes(data))
            # The body shapes (the sliders): without them the shoe is the wrong size.
            (folder / f"{base}_pc.morph_pc").write_bytes((original / f"{SOURCE}_pc.morph_pc").read_bytes())
            print(f"   {shoe['name']}: {base} ({texture_name})")
    print(f"built {folder}: diffuse {dw}x{dh} ({dl} mips), bump {bw}x{bh} ({bl}), tint {tw}x{th} ({tl})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\gta-clothes"))
