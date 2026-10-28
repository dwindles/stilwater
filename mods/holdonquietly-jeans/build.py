"""Build the holdonquietly distressed jeans mod for men's tight jeans.

Pulls the original cmbot_mjeansmf02_m texture pack from the game's archives, swaps its diffuse
for the projected photo texture (DXT1 at the original's size and mip count) and writes a loose-file
mod folder, then slims the mesh to a straight stretch fit (fit.py).
In game the item is "Men's Jeans 1" (internally "men's tight jeans"); mods/shared renames it,
sells it in more stores and makes white its default colour.

    python build.py [game folder]     # writes out/STILWATER - HOQ Jeans/
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import peg  # noqa: E402
import vpp  # noqa: E402
import project  # noqa: E402
import fit  # noqa: E402

PACK = "cmbot_mjeansmf02_m"
DIFFUSE = "cmbot_mjeansmf01_d.tga"
MOD_NAME = "STILWATER - HOQ Jeans"


def main(game):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    (original / f"{PACK}.peg_pc").write_bytes(vpp.Packfile(game / "pegs.vpp_pc").read(f"{PACK}.peg_pc"))
    (original / f"{PACK}.g_peg_pc").write_bytes(vpp.Packfile(game / "textures.vpp_pc").read(f"{PACK}.g_peg_pc"))

    project.main()
    # Same size and mip count as the original: clothing streams into fixed-size slots, and a
    # bigger texture pack makes the item fail to load.
    vanilla = next(e for e in peg.read_header(original / f"{PACK}.peg_pc") if e["name"] == DIFFUSE)
    texture = Image.open(project.OUT / "hq_jeans_diffuse_1024.png").resize(
        (vanilla["width"], vanilla["height"]), Image.LANCZOS)
    blob, mips = peg.encode_dxt1(texture, max_levels=vanilla["mips"])
    assert len(blob) == vanilla["size"], (len(blob), vanilla["size"])
    header, data = peg.rebuild(original / f"{PACK}.peg_pc", original / f"{PACK}.g_peg_pc",
                               {DIFFUSE: (texture.width, texture.height, 0x190, mips, blob)})

    out = project.OUT / MOD_NAME
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{PACK}.peg_pc").write_bytes(header)
    (out / f"{PACK}.g_peg_pc").write_bytes(data)

    # Read the result back to make sure it decodes.
    entry = next(e for e in peg.read_header(out / f"{PACK}.peg_pc") if e["name"] == DIFFUSE)
    peg.to_image(entry, data).save(project.OUT / "readback.png")
    print(f"built {out} ({len(data)} bytes of texture data, {mips} mip levels)")
    fit.main(game)


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
