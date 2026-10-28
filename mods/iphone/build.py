"""iPhone 17 Pro: a GTA V iPhone (the "iPhone 17 Pro" mod's replacement phone prop_phone_ing.ydr,
silver, and its default wallpaper, from its dlc.rpf) in place of the phone the player holds in
SR2 (item cellphone_PC, model cellphone_pc).

The model (tools/sr2/weaponport.py, which also fits SR2's item meshes): the phone (77k triangles)
is simplified for SR2's three detail levels and given a new atlas, which the body texture and the
wallpaper (on the screen; GTA draws its phone screen there) are baked onto. The black front glass
right behind the screen is left out, so the screen bakes cleanly. SR2's phone has its screen
towards -x, its top at +y and the hand on its back at the origin; the iPhone (screen towards GTA
-y, top at +z) is turned to match, at its own size, centred on SR2's phone with its back where
SR2's back is.

The textures: the baked atlas replaces cellphone1_pl.tga at 512 x 512; the bump and specular maps
(laid out for the old phone) become flat.

    python build.py [game folder] [mod folder]     # writes out/STILWATER - iPhone 17 Pro/
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
sys.path.insert(0, str(ROOT / "tools" / "gta5"))
import rpf  # noqa: E402
import unwrap  # noqa: E402
import weaponport  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402

MODEL = "cellphone_pc"
MOD_NAME = "STILWATER - iPhone 17 Pro"
GTA_ARCHIVE = "iPhone 17 Pro/iPhone17Pro/dlc.rpf"
GTA_MODEL = "x64/iphone17pro_replace.rpf/prop_phone_ing.ydr"
GTA_WALLPAPER = ("x64/iphone17pro_replace.rpf/phone_wallpaper_ifruitdefault.ytd", "phone_wallpaper_ifruitdefault")
SCREEN = "phone_screen"                 # the screen's material (GTA's phone render target)
DIFFUSE, BUMP, SPECULAR = "cellphone1_pl.tga", "cellphone1_nm.tgn", "cellphone1_sp.tga"
DIFFUSE_SIZE = 512
FLAT_BUMP = (128, 128, 128, 128)        # SR2's grey bump maps: 128 is flat
SPECULAR_LEVEL = (115, 115, 115, 255)   # the old phone's glossy plastic

LOD_TRIANGLES = (2500, 900, 300)
LOD_DENSITY = (1.0, 0.45, 0.25)         # share of the atlas detail per level
SAMPLES = 1_500_000                     # points on the full model for the bake
# GTA to SR2's phone: screen (GTA -y) towards -x, top (GTA +z) towards +y.
AXES = np.array([[0, 1, 0], [0, 0, 1], [-1, 0, 0]], dtype=float)


def without_hidden_glass(model):
    """The model without the body triangles lying just behind the screen (within 0.5 mm of its
    plane, facing the same way, inside its outline)."""
    p, t = model["positions"], model["triangles"]
    screen = model["textures"] == SCREEN
    sp = p[np.unique(t[screen])]
    plane = sp[:, 1].mean()
    centre = p[t].mean(axis=1)
    facing = model["normals"][t].sum(axis=1)[:, 1] < 0
    hidden = (~screen & facing & (np.abs(centre[:, 1] - plane) < 0.0005)
              & (centre[:, 0] > sp[:, 0].min()) & (centre[:, 0] < sp[:, 0].max())
              & (centre[:, 2] > sp[:, 2].min()) & (centre[:, 2] < sp[:, 2].max()))
    keep = ~hidden
    return dict(model, triangles=t[keep], textures=model["textures"][keep]), int(hidden.sum())


def main(game, mod_folder):
    original = HERE / "original"
    weaponport.extract(game, MODEL, original)
    header = bytearray((original / f"{MODEL}.smesh_pc").read_bytes())
    vanilla_data = (original / f"{MODEL}.g_smesh_pc").read_bytes()
    vanilla = weaponport.vanilla_positions(bytes(header), vanilla_data)
    box = weaponport.find_box(header, vanilla)

    files = rpf.files((mod_folder / GTA_ARCHIVE).read_bytes())
    work = HERE / "original" / "gta"
    work.mkdir(exist_ok=True)
    (work / "prop_phone_ing.ydr").write_bytes(files[GTA_MODEL])
    (work / "wallpaper.ytd").write_bytes(files[GTA_WALLPAPER[0]])
    gta, hidden = without_hidden_glass(weaponport.load_gta(work / "prop_phone_ing.ydr"))
    print(f"   GTA model: {len(gta['triangles'])} triangles ({hidden} hidden glass triangles left out)")

    drawable = yft.read_drawable(work / "prop_phone_ing.ydr")
    res = drawable["resource"]
    embedded = ytd.dictionary(res, res.u64(res.u64(drawable["drawable"], 0x10), 0x08))
    wallpaper = ytd.textures(work / "wallpaper.ytd")[GTA_WALLPAPER[1]]
    textures = {}
    for name, (width, height, fmt, _, buf, off) in [*embedded.items(), (SCREEN, wallpaper)]:
        textures[name] = np.asarray(ytd.to_image(width, height, fmt, buf, off).convert("RGB"), dtype=np.float32) / 255
    assert set(gta["textures"]) <= set(textures), set(gta["textures"])

    # Turned to SR2's phone, centred on it, its back (+x) on SR2's back.
    q = gta["positions"] @ AXES.T
    old = np.vstack(vanilla)
    offset = (old.min(axis=0) + old.max(axis=0)) / 2 - (q.min(axis=0) + q.max(axis=0)) / 2
    offset[0] = old[:, 0].max() - q[:, 0].max()

    shapes = weaponport.lods(original, gta, LOD_TRIANGLES)
    levels = [(s, t, uv) for s, t, uv, _ in unwrap.unwrap(shapes, LOD_DENSITY, DIFFUSE_SIZE)]
    image, covered = weaponport.bake_atlas(levels, gta, textures, DIFFUSE_SIZE, SAMPLES)
    (HERE / "out").mkdir(exist_ok=True)
    image.save(HERE / "out" / "iphone_atlas.png")
    print(f"   atlas {DIFFUSE_SIZE} x {DIFFUSE_SIZE}: {100 * covered.mean():.0f}% used")

    data = weaponport.write_mesh(header, levels, AXES, offset, box)
    weaponport.write_shadows(header, shapes, AXES, offset)
    flat = {BUMP: (Image.new("RGBA", (32, 32), FLAT_BUMP), "DXT5"),
            SPECULAR: (Image.new("RGBA", (32, 32), SPECULAR_LEVEL), "DXT1")}
    peg_header, pack = weaponport.retexture(original, MODEL, DIFFUSE, image, flat)
    folder = HERE / "out" / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{MODEL}.smesh_pc").write_bytes(bytes(header))
    (folder / f"{MODEL}.g_smesh_pc").write_bytes(bytes(data))
    (folder / f"{MODEL}.peg_pc").write_bytes(peg_header)
    (folder / f"{MODEL}.g_peg_pc").write_bytes(pack)
    print(f"built {folder}: mesh {len(data)} bytes (old {len(vanilla_data)}), textures {len(pack)} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\iphone"))
