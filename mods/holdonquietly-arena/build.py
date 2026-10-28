"""HOQ Arena Highs: black crinkled-leather high-tops (Balenciaga Arena style) on SR2's canvas shoes.

Texture only (cmSho_uCasShoe01 keeps its mesh). The vanilla diffuse gives the regions and shading:
the lace panel (top left of the texture; u runs ankle to toe), its white laces, the tan outsole and
the sole strip (the mesh's second material). Everything is repainted: black leather with creases
from layered ridged noise, dark grey laces, black rubber, silver ring eyelets where the laces meet
the panel edges and the silver plate across the lowest lacing at the toe end.

Clothing packs must keep their exact vanilla size (they load into fixed slots), so the build picks
texture sizes and mip counts that add up to it, and checks.

    python build.py [game folder]     # writes out/STILWATER - HOQ Arena/
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import clothing  # noqa: E402
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402

MESH = PACK = "cmsho_ucasshoe01"
DIFFUSE, TINT, BUMP = f"{PACK}_d.tga", f"{PACK}_p.tga", f"{PACK}_n.tgn"
MOD_NAME = "STILWATER - HOQ Arena"
WORK = 512                                   # painting resolution (downsampled to the diffuse size)

LACE_PANEL = (0.0, 0.0, 0.575, 0.425)        # u0, v0, u1, v1 of the lace panel in the vanilla layout
LEATHER = np.array([24, 24, 27]) / 255
LACE = np.array([66, 63, 61]) / 255
RUBBER = np.array([17, 17, 18]) / 255
SILVER = np.array([176, 178, 184]) / 255

DXT1, DXT5 = clothing.DXT1, clothing.DXT5


def noise(size, cells, seed):
    """Smooth value noise in 0..1."""
    rng = np.random.default_rng(seed)
    grid = (rng.random((cells, cells)) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(grid).resize((size, size), Image.BICUBIC)) / 255.0


def crinkle(size):
    """Leather crease height in 0..1: ridged noise at a few scales."""
    h = np.zeros((size, size))
    for cells, weight, seed in ((12, 0.5, 1), (28, 0.3, 2), (64, 0.2, 3)):
        h += weight * (1 - np.abs(2 * noise(size, cells, seed) - 1)) ** 3
    return h / h.max()


def rasterize(uvs, triangles, size):
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    for t in triangles:
        draw.polygon([tuple(np.mod(uvs[i], 1.0) * size) for i in t], fill=255)
    return np.asarray(image) > 0


def eyelet_centres(laces):
    """Where laces reach the panel's long edges: peaks of lace coverage near each edge."""
    u0, v0, u1, v1 = (int(c * WORK) for c in LACE_PANEL)
    centres = []
    for band in ((v0 + 0.06 * WORK, v0 + 0.11 * WORK), (v1 - 0.11 * WORK, v1 - 0.06 * WORK)):
        rows = laces[int(band[0]):int(band[1]), u0:u1].mean(axis=0)
        rows = np.convolve(rows, np.ones(9) / 9, mode="same")
        v = (band[0] + band[1]) / 2
        for x in range(4, len(rows) - 4):
            if rows[x] > 0.25 and rows[x] == rows[x - 4:x + 5].max():
                if not centres or abs(centres[-1][0] - (u0 + x)) > 0.04 * WORK or abs(centres[-1][1] - v) > 1:
                    centres.append((u0 + x, v))
    return centres


def paint(mesh, vanilla):
    n = WORK
    shade = np.asarray(vanilla.convert("L").resize((n, n), Image.BICUBIC)) / 255.0
    rgb = np.asarray(vanilla.convert("RGB").resize((n, n), Image.BICUBIC)).astype(float)

    sole = (rgb[..., 0] - rgb[..., 2] > 18) & (shade > 0.45)            # the tan outsole
    strip = rasterize(mesh["uvs"], mesh["triangles"][mesh["materials"] == 1], n)
    yy, xx = np.mgrid[0:n, 0:n] / n
    u0, v0, u1, v1 = LACE_PANEL
    panel = (xx >= u0) & (xx < u1) & (yy >= v0) & (yy < v1)
    laces = panel & (shade > np.percentile(shade[panel], 62))

    crease = crinkle(n)
    leather = LEATHER * (0.8 + 0.5 * crease[..., None]) * (0.75 + 0.35 * shade[..., None])
    lace = LACE * (0.7 + 0.45 * shade[..., None])
    rubber = RUBBER * (0.7 + 0.6 * shade[..., None])
    texture = np.where((sole | strip)[..., None], rubber, leather)
    texture = np.where(laces[..., None], lace, texture)

    image = Image.fromarray((np.clip(texture, 0, 1) * 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    silver = tuple((SILVER * 255).astype(int))
    radius = 0.017 * n
    for x, y in eyelet_centres(laces.astype(float)):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=silver, width=max(2, int(radius * 0.45)))
    # The plate across the lowest lacing, at the toe end of the panel, with its fine grid.
    px0, px1 = (u1 - 0.07) * n, (u1 - 0.035) * n
    py0, py1 = (v0 + 0.12) * n, (v1 - 0.12) * n
    draw.rounded_rectangle((px0, py0, px1, py1), radius=3, fill=silver)
    for gx in np.arange(px0 + 3, px1 - 2, 4):
        for gy in np.arange(py0 + 3, py1 - 2, 4):
            draw.point((gx, gy), fill=(120, 121, 126))
    return image, crease


def main(game):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes, pegs, textures = (vpp.Packfile(game / f) for f in ("meshes.vpp_pc", "pegs.vpp_pc", "textures.vpp_pc"))
    for ext in ("cmesh_pc", "g_cmesh_pc"):
        (original / f"{MESH}.{ext}").write_bytes(meshes.read(f"{MESH}.{ext}"))
    (original / f"{PACK}.peg_pc").write_bytes(pegs.read(f"{PACK}.peg_pc"))
    (original / f"{PACK}.g_peg_pc").write_bytes(textures.read(f"{PACK}.g_peg_pc"))

    mesh = cmesh.load(original / f"{MESH}.cmesh_pc", original / f"{MESH}.g_cmesh_pc")
    vanilla_data = (original / f"{PACK}.g_peg_pc").read_bytes()
    header = peg.read_header(original / f"{PACK}.peg_pc")
    entries = {e["name"]: e for e in header}
    image, crease = paint(mesh, peg.to_image(entries[DIFFUSE], vanilla_data))

    sizes = clothing.fit_sizes([e["name"] for e in header], len(vanilla_data),
                               {DIFFUSE: "diffuse", BUMP: "bump", TINT: "tint"},
                               {"bump": (128, 64, 32, 16), "tint": (64, 32, 16, 8, 4)})
    (dw, dh, dl), (bw, bh, bl), (tw, th, tl) = sizes[DIFFUSE], sizes[BUMP], sizes[TINT]
    out = HERE / "out"
    out.mkdir(exist_ok=True)
    diffuse_image = image.resize((dw, dh), Image.LANCZOS)
    diffuse_image.save(out / "hoq_arena_diffuse.png")
    diffuse, _ = peg.encode(diffuse_image, "DXT1", max_levels=dl)
    # The "normal" map of SR2's clothing is a grey bump map (all channels alike around 128).
    bump_grey = Image.fromarray((128 + 60 * (crease - crease.mean())).clip(0, 255).astype(np.uint8))
    bump, _ = peg.encode(bump_grey.resize((bw, bh), Image.LANCZOS).convert("RGBA"), "DXT5", max_levels=bl)
    # One tint region (blue), so the colour picker's first colour (white by default) tints it all.
    tint, _ = peg.encode(Image.new("RGB", (tw, th), (0, 0, 255)), "DXT1", max_levels=tl)
    replacements = {DIFFUSE: (dw, dh, DXT1, dl, diffuse), BUMP: (bw, bh, DXT5, bl, bump), TINT: (tw, th, DXT1, tl, tint)}

    folder = out / MOD_NAME
    folder.mkdir(exist_ok=True)
    peg_header, data = peg.rebuild(original / f"{PACK}.peg_pc", original / f"{PACK}.g_peg_pc", replacements)
    assert len(data) == len(vanilla_data), (len(data), len(vanilla_data))
    (folder / f"{PACK}.peg_pc").write_bytes(peg_header)
    (folder / f"{PACK}.g_peg_pc").write_bytes(data)
    print(f"built {folder}: diffuse {dw}x{dh} ({dl} mips), bump {bw}x{bh} ({bl}), tint {tw}x{th} ({tl})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
