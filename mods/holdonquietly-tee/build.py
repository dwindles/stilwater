"""Build the holdonquietly tee: the shirt in ref/ on SR2's "Tie Dye Tee" (internally "tye-dye T-shirt").

That tee is worn by only a few NPCs, so the print rarely turns up on strangers. Its texture is baked
from the mesh: each texel of the diffuse gets its 3D surface point, and texels facing forward
sample the front print, those facing back the back print, projected straight on. The front faces
+z (the neckline dips lower on that side). Assuming the usual left-handed Direct3D space, +x is on
the viewer's left seen from the front and on the viewer's right seen from behind; if the text
comes out mirrored in game, flip the two signs in main().

Every pack keeps its exact vanilla size, because clothing streams into fixed-size slots: the
diffuse goes from 256x256 DXT5 to 512x512 DXT1 and the wrinkle normal map from 256 to 128.

    python build.py [game folder]     # writes out/STILWATER - HOQ Tee/
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402

MESH = "cmuns_utshirt04_u"
# Every mesh of the item (untucked/tucked, male/female) uses the same _D_U texture.
PACKS = [f"cmuns_utshirt04_{s}" for s in ("u", "uf", "h", "hf", "m", "mf", "l", "lf")]
DIFFUSE, NORMAL, TINT = "cmuns_utshirt04_d_u.tga", "cmuns_utshirt04_n_u.tgn", "cmuns_utshirt04_p.tga"
MOD_NAME = "STILWATER - HOQ Tee"
SIZE, SUPERSAMPLE = 512, 2
FABRIC = np.array([30, 30, 33]) / 255
STROKE_GROW = 7                          # max-filter size (photo pixels) thickening the handwriting
INK_BOOST = np.array([1.3, 0.85, 0.85])   # the photographed ink reads darker and duller than the print

# Print placement, measured on the flat-lay photos and scaled by shirt length (neck to hem).
# box: the print's reference rectangle in the close-up photo; size: that rectangle on the body in
# metres (the front is 12% up on the photos' ratio, since the game's tee is boxier); below_neck:
# from the neckline at the centre to the rectangle's top.
FRONT = dict(photo="front-close.jpg", box=(354, 264, 1004, 1008), size=(0.181, 0.208), below_neck=0.073,
             quad=[(355, 262), (1008, 266), (1000, 1012), (352, 1003)])
BACK = dict(photo="back-close.jpg", box=(170, 125, 1215, 605), size=(0.243, 0.105), below_neck=0.078)


def red_strokes(rgb):
    """Soft mask of the red screen print on black fabric."""
    return np.clip((rgb[..., 0] - np.maximum(rgb[..., 1], rgb[..., 2]) - 0.12) / 0.18, 0, 1)


def layer(spec, shrink):
    """(colour, alpha) of one print, shrunk by `shrink` so it isn't minified when sampled."""
    image = Image.open(HERE / "ref" / spec["photo"]).convert("RGB")
    rgb = np.asarray(image).astype(float) / 255
    alpha = red_strokes(rgb)
    photo = np.zeros(alpha.shape, dtype=bool)
    if "quad" in spec:
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).polygon(spec["quad"], fill=255)
        photo = np.asarray(mask) > 127
    ink = np.clip(np.median(rgb[(alpha > 0.9) & ~photo], axis=0) * INK_BOOST, 0, 1)
    # The handwriting is a few pixels wide in the photos, under a texel once it's on the shirt, so
    # it is thickened before shrinking or it fades into the black fabric.
    thick = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(STROKE_GROW))
    alpha = np.asarray(thick).astype(float) / 255
    colour = np.where(photo[..., None], rgb, ink)
    alpha = np.where(photo, 1.0, alpha)

    size = (round(image.width / shrink), round(image.height / shrink))
    rgba = np.dstack([colour, alpha]) * 255
    small = Image.fromarray(rgba.astype(np.uint8), "RGBA").resize(size, Image.LANCZOS)
    small = np.asarray(small).astype(float) / 255
    return small[..., :3], small[..., 3]


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


def project(spec, colour, alpha, shrink, pos, top, sign):
    """Sample a print at surface points; sign is the direction of +x as seen by the viewer."""
    x0, y0, x1, y1 = spec["box"]
    width, height = spec["size"]
    u = 0.5 + sign * pos[..., 0] / width
    v = (top - pos[..., 1]) / height
    px = (x0 + u * (x1 - x0)) / shrink
    py = (y0 + v * (y1 - y0)) / shrink
    return sample(colour, alpha, px, py)


def main(game):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes, pegs, textures = (vpp.Packfile(game / f) for f in ("meshes.vpp_pc", "pegs.vpp_pc", "textures.vpp_pc"))
    for ext, pack in (("cmesh_pc", meshes), ("g_cmesh_pc", meshes)):
        (original / f"{MESH}.{ext}").write_bytes(pack.read(f"{MESH}.{ext}"))
    for name in PACKS:
        (original / f"{name}.peg_pc").write_bytes(pegs.read(f"{name}.peg_pc"))
        (original / f"{name}.g_peg_pc").write_bytes(textures.read(f"{name}.g_peg_pc"))

    mesh = cmesh.load(original / f"{MESH}.cmesh_pc", original / f"{MESH}.g_cmesh_pc")
    p = mesh["positions"]
    centre = p[np.abs(p[:, 0]) < 0.03]
    front_neck = centre[centre[:, 2] > 0][:, 1].max()
    back_neck = centre[centre[:, 2] < 0][:, 1].max()

    n = SIZE * SUPERSAMPLE
    pos, nrm, covered = cmesh.bake(mesh, n, n)

    # Black fabric, keeping the vanilla diffuse's baked folds and shading.
    vanilla_data = (original / f"{PACKS[0]}.g_peg_pc").read_bytes()
    entries = {e["name"]: e for e in peg.read_header(original / f"{PACKS[0]}.peg_pc")}
    shade = np.asarray(peg.to_image(entries[DIFFUSE], vanilla_data).convert("L").resize((n, n), Image.LANCZOS)) / 255
    shade = np.clip(shade / np.percentile(shade, 95), 0, 1)[..., None]
    texture = FABRIC * (0.55 + 0.45 * shade)

    for spec, top, sign, facing in ((FRONT, front_neck - FRONT["below_neck"], -1, 1),
                                    (BACK, back_neck - BACK["below_neck"], 1, -1)):
        shrink = 2.5
        colour, alpha = layer(spec, shrink)
        c, a = project(spec, colour, alpha, shrink, pos, top, sign)
        a = a * np.clip((facing * nrm[..., 2] - 0.15) / 0.25, 0, 1) * covered
        c = c * (0.75 + 0.25 * shade)
        texture = texture * (1 - a[..., None]) + c * a[..., None]

    image = Image.fromarray((np.clip(texture, 0, 1) * 255).astype(np.uint8)).resize((SIZE, SIZE), Image.LANCZOS)
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    image.save(out / "hoq_tee_diffuse.png")
    preview(pos, nrm, covered, np.asarray(image.resize((n, n), Image.NEAREST)), out)

    diffuse, diffuse_mips = peg.encode(image, "DXT1", max_levels=1)
    normal_image = peg.to_image(entries[NORMAL], vanilla_data).resize((128, 128), Image.LANCZOS)
    normal, normal_mips = peg.encode(normal_image, "DXT5")
    # One tint region (the blue channel), so the in-game colour picker's first colour tints it all.
    tint, tint_mips = peg.encode(Image.new("RGB", (64, 64), (0, 0, 255)), "DXT1", max_levels=entries[TINT]["mips"])
    replacements = {DIFFUSE: (SIZE, SIZE, 0x190, diffuse_mips, diffuse),
                    NORMAL: (128, 128, 0x192, normal_mips, normal),
                    TINT: (64, 64, 0x190, tint_mips, tint)}

    folder = out / MOD_NAME
    folder.mkdir(exist_ok=True)
    for name in PACKS:
        header, data = peg.rebuild(original / f"{name}.peg_pc", original / f"{name}.g_peg_pc", replacements)
        vanilla_size = (original / f"{name}.g_peg_pc").stat().st_size
        assert len(data) == vanilla_size, (name, len(data), vanilla_size)
        (folder / f"{name}.peg_pc").write_bytes(header)
        (folder / f"{name}.g_peg_pc").write_bytes(data)
    print(f"built {folder}: {len(PACKS)} packs, diffuse {SIZE}x{SIZE}")


def preview(pos, nrm, covered, texture, out):
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
    sheet.save(out / "preview.png")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
