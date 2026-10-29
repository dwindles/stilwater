"""Build the Stilwater tees: printed shirts from photos, each a new item cloned from SR2's "tye-dye T-shirt".

A clone is that tee's eight meshes and texture packs (untucked/tucked high, mid and low, male and
female) copied under a new name of the same length, "cmuns_utshirt04" becoming the tee's `base`.
The meshes and packs name their textures in plain text, so the same rename points each copy at its
own textures. Stilwater core registers the new file names with the game, and mods/shared adds the
items (TEES in tees.py) to customization_items, the stores and the strings.

The print is baked like the HOQ Tee's: each texel of the diffuse gets its 3D surface point, and
texels facing forward sample the front photo, those facing back the back photo, projected straight
on. Photos are placed by the shirt's neckline and hem in them, against the game tee's own length.

Every pack keeps its exact vanilla size, because clothing streams into fixed-size slots: the
diffuse goes from 256x256 DXT5 to 512x512 DXT1 and the wrinkle normal map from 256 to 128.

    python build.py [game folder]     # writes out/STILWATER - Tees/
"""
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402
from tees import SOURCE, SUFFIXES, TEES  # noqa: E402

DIFFUSE, NORMAL, TINT = "_d_u.tga", "_n_u.tgn", "_p.tga"
MOD_NAME = "STILWATER - Tees"
SIZE, SUPERSAMPLE = 512, 2
LENGTH_PER_WIDTH = 1.06   # a flat tee's neck-to-hem length over its width under the arms (the Draco Party photo)


def rename(data, base):
    """The vanilla tee's name swapped for the clone's, in a mesh or a peg header."""
    assert len(base) == len(SOURCE)
    return re.sub(re.escape(SOURCE.encode()), base.encode(), data, flags=re.I)


def print_layer(spec):
    """(colour, alpha) of a print photo: whatever differs from the shirt's fabric inside the print's box."""
    rgb = np.asarray(Image.open(HERE / "ref" / spec["photo"]).convert("RGB")).astype(float) / 255
    x0, y0, x1, y1 = spec["box"]
    fx0, fy0, fx1, fy1 = spec["fabric"]
    fabric = np.median(rgb[fy0:fy1, fx0:fx1].reshape(-1, 3), axis=0)
    distance = np.linalg.norm(rgb - fabric, axis=-1)
    alpha = np.clip((distance - spec.get("threshold", 0.12)) / 0.18, 0, 1)
    inside = np.zeros(alpha.shape, dtype=bool)
    inside[y0:y1, x0:x1] = True
    return rgb, alpha * inside


def sample(colour, alpha, px, py):
    """Bilinear lookup; points outside the image get alpha 0."""
    h, w = alpha.shape
    inside = (px >= 0) & (py >= 0) & (px <= w - 1) & (py <= h - 1)
    x, y = np.clip(px, 0, w - 1.001), np.clip(py, 0, h - 1.001)
    x0, y0 = x.astype(int), y.astype(int)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]

    def at(img):
        img = img if img.ndim == 3 else img[..., None]
        top = img[y0, x0] * (1 - fx) + img[y0, x0 + 1] * fx
        bottom = img[y0 + 1, x0] * (1 - fx) + img[y0 + 1, x0 + 1] * fx
        return top * (1 - fy) + bottom * fy

    return at(colour), at(alpha)[..., 0] * inside


def project(spec, pos, neck, hem, sign):
    """Sample a photo at surface points; sign is the direction of +x as seen by the viewer."""
    colour, alpha = print_layer(spec)
    # A photo that cuts off the hem gives the body's width under the arms instead.
    length = spec["hem"] - spec["neck"] if "hem" in spec else (spec["width"][1] - spec["width"][0]) * LENGTH_PER_WIDTH
    metres_per_pixel = (neck - hem) / length * spec.get("scale", 1.0)
    dx = sign * pos[..., 0] / metres_per_pixel
    dy = (neck - pos[..., 1]) / metres_per_pixel
    # A shirt photographed at an angle: turn the shirt's axes by `rotate` degrees (clockwise in the photo).
    angle = np.radians(spec.get("rotate", 0))
    px = spec["centre"] + dx * np.cos(angle) - dy * np.sin(angle)
    py = spec["neck"] + dx * np.sin(angle) + dy * np.cos(angle)
    return sample(colour, alpha, px, py)


def fabric_colour(tee):
    """The shirt's colour: given, or the median of the front photo's fabric patch, a little darker."""
    if "fabric" in tee:
        return np.array(tee["fabric"]) / 255
    spec = tee["front"]
    rgb = np.asarray(Image.open(HERE / "ref" / spec["photo"]).convert("RGB")).astype(float) / 255
    x0, y0, x1, y1 = spec["fabric"]
    return np.median(rgb[y0:y1, x0:x1].reshape(-1, 3), axis=0) * 0.85


def bake_texture(tee, mesh, shade):
    p = mesh["positions"]
    centre = p[np.abs(p[:, 0]) < 0.03]
    hem = p[:, 1].min()
    front_neck = centre[centre[:, 2] > 0][:, 1].max()
    back_neck = centre[centre[:, 2] < 0][:, 1].max()

    n = SIZE * SUPERSAMPLE
    pos, nrm, covered = cmesh.bake(mesh, n, n)
    texture = fabric_colour(tee) * (0.55 + 0.45 * shade)
    for side, neck, sign, facing in (("front", front_neck, -1, 1), ("back", back_neck, 1, -1)):
        if side not in tee:
            continue
        c, a = project(tee[side], pos, neck, hem, sign)
        a = a * np.clip((facing * nrm[..., 2] - 0.15) / 0.25, 0, 1) * covered
        c = c * (0.75 + 0.25 * shade)
        texture = texture * (1 - a[..., None]) + c * a[..., None]
    image = Image.fromarray((np.clip(texture, 0, 1) * 255).astype(np.uint8)).resize((SIZE, SIZE), Image.LANCZOS)
    return image, pos, nrm, covered


def preview(pos, nrm, covered, texture, path):
    """Front and back views of the textured mesh (texel splats), as the viewer would see them."""
    views = []
    for facing, sign in ((1, -1), (-1, 1)):
        canvas = np.full((420, 360, 3), 200, dtype=np.uint8)
        sel = covered & (facing * nrm[..., 2] > 0.2)
        x = (180 + sign * pos[..., 0][sel] * 380).astype(int)
        y = (210 - (pos[..., 1][sel] - 1.26) * 380).astype(int)
        ok = (x >= 0) & (x < 360) & (y >= 0) & (y < 420)
        canvas[y[ok], x[ok]] = texture[sel][ok]
        views.append(Image.fromarray(canvas))
    sheet = Image.new("RGB", (730, 420), "white")
    sheet.paste(views[0], (0, 0))
    sheet.paste(views[1], (370, 0))
    sheet.save(path)


def main(game):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes, pegs, textures = (vpp.Packfile(game / f) for f in ("meshes.vpp_pc", "pegs.vpp_pc", "textures.vpp_pc"))
    for s in SUFFIXES:
        name = f"{SOURCE}_{s}"
        for ext, pack in ((".cmesh_pc", meshes), (".g_cmesh_pc", meshes), (".peg_pc", pegs), (".g_peg_pc", textures),
                          ("_pc.morph_pc", meshes)):
            if not (original / f"{name}{ext}").exists():
                (original / f"{name}{ext}").write_bytes(pack.read(f"{name}{ext}"))

    first = f"{SOURCE}_{SUFFIXES[0]}"
    mesh = cmesh.load(original / f"{first}.cmesh_pc", original / f"{first}.g_cmesh_pc")
    entries = {e["name"]: e for e in peg.read_header(original / f"{first}.peg_pc")}
    vanilla_data = (original / f"{first}.g_peg_pc").read_bytes()
    n = SIZE * SUPERSAMPLE
    shade = np.asarray(peg.to_image(entries[SOURCE + DIFFUSE], vanilla_data).convert("L").resize((n, n), Image.LANCZOS)) / 255
    shade = np.clip(shade / np.percentile(shade, 95), 0, 1)[..., None]
    normal_image = peg.to_image(entries[SOURCE + NORMAL], vanilla_data).resize((128, 128), Image.LANCZOS)
    normal, normal_mips = peg.encode(normal_image, "DXT5")
    # One tint region (the blue channel), so the in-game colour picker's first colour tints it all.
    tint, tint_mips = peg.encode(Image.new("RGB", (64, 64), (0, 0, 255)), "DXT1",
                                 max_levels=entries[SOURCE + TINT]["mips"])

    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    for tee in TEES:
        base = tee["base"]
        image, pos, nrm, covered = bake_texture(tee, mesh, shade)
        image.save(out / f"{base}_diffuse.png")
        preview(pos, nrm, covered, np.asarray(image.resize((n, n), Image.NEAREST)), out / f"{base}_preview.png")
        diffuse, diffuse_mips = peg.encode(image, "DXT1", max_levels=1)
        replacements = {SOURCE + DIFFUSE: (SIZE, SIZE, 0x190, diffuse_mips, diffuse),
                        SOURCE + NORMAL: (128, 128, 0x192, normal_mips, normal),
                        SOURCE + TINT: (64, 64, 0x190, tint_mips, tint)}
        for s in SUFFIXES:
            name, clone = f"{SOURCE}_{s}", f"{base}_{s}"
            header, data = peg.rebuild(original / f"{name}.peg_pc", original / f"{name}.g_peg_pc", replacements)
            assert len(data) == (original / f"{name}.g_peg_pc").stat().st_size, name
            (folder / f"{clone}.peg_pc").write_bytes(rename(header, base))
            (folder / f"{clone}.g_peg_pc").write_bytes(data)
            (folder / f"{clone}.cmesh_pc").write_bytes(rename((original / f"{name}.cmesh_pc").read_bytes(), base))
            (folder / f"{clone}.g_cmesh_pc").write_bytes((original / f"{name}.g_cmesh_pc").read_bytes())
            # The body shapes (thin to fat, the sliders): without them the tee is the wrong size.
            (folder / f"{clone}_pc.morph_pc").write_bytes((original / f"{name}_pc.morph_pc").read_bytes())
        print(f"{tee['name']}: {base}_*")
    print(f"built {folder}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
