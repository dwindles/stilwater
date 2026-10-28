"""Stilwater minimal HUD: the game's hud.lua with minimal_hud.lua appended, plus a rectangular minimap.

The appended code redefines a few hud.lua functions (each wrapping the original) to shrink the
health/weapon ring and cash, fade them out when nothing is happening, and restyle the minimap.
See minimal_hud.lua for the rules.

The minimap's round shape comes from the bitmap ui_hud_base_mm_mask (a white circle with alpha),
which the map code loads by name and draws the map through; the black disc behind the map uses
it too. It lives at (496, 83), 140x140, in sheet ui_bms_00 (1024x1024 DXT5) of
interface-backend.g_peg_pc (m_pat.vpp_pc), per bitmap_sheets.xtbl. Replacing the circle with a
filled rectangle (MASK_SIZE wide, MAP_HEIGHT tall, centred) changes the map's shape; the map still
keeps far-off blips on a circle, so a much shorter rectangle would cut them off at the top and
bottom. Only the DXT blocks under the mask are re-encoded, so the rest of the sheet is unchanged.

    python build.py [game folder]     # writes out/STILWATER - Minimal HUD/
"""
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
import peg  # noqa: E402
import vpp  # noqa: E402

MOD_NAME = "STILWATER - Minimal HUD"
SHEET, MASK_X, MASK_Y, MASK_SIZE = "ui_bms_00.tga", 496, 83, 140
MAP_HEIGHT = 112   # the map: MASK_SIZE wide and this tall, a slightly wide rectangle


def square_mask(game, out):
    pack = vpp.Packfile(game / "m_pat.vpp_pc")
    header_bytes = pack.read("interface-backend.peg_pc")
    data = bytearray(pack.read("interface-backend.g_peg_pc"))
    (out / "interface-backend.peg_pc").write_bytes(header_bytes)
    entry = next(e for e in peg.read_header(out / "interface-backend.peg_pc") if e["name"] == SHEET)
    assert peg.FORMATS[entry["format"]] == "DXT5" and entry["mips"] == 1
    sheet = peg.to_image(entry, data).convert("RGBA")

    # Whole 4x4 blocks covering the mask. The block row holding the mask's top row also holds
    # the bottom row of ui_menu_tmp_frm_trm_b, so it is left alone (the mask's row there is clear).
    x0, y0 = MASK_X // 4 * 4, -(-MASK_Y // 4) * 4
    x1, y1 = -(-(MASK_X + MASK_SIZE) // 4) * 4, -(-(MASK_Y + MASK_SIZE) // 4) * 4
    region = sheet.crop((x0, y0, x1, y1))
    top = MASK_Y + (MASK_SIZE - MAP_HEIGHT) // 2
    region.paste((255, 255, 255, 0), (MASK_X - x0, 0, MASK_X - x0 + MASK_SIZE, MASK_Y + MASK_SIZE - y0))
    region.paste((255, 255, 255, 255), (MASK_X - x0, top - y0, MASK_X - x0 + MASK_SIZE, top - y0 + MAP_HEIGHT))
    blocks, _ = peg.encode(region, "DXT5", max_levels=1)

    cols, rows, stride = (x1 - x0) // 4, (y1 - y0) // 4, entry["width"] // 4
    assert len(blocks) == cols * rows * 16
    for r in range(rows):
        src = r * cols * 16
        dst = entry["offset"] + ((y0 // 4 + r) * stride + x0 // 4) * 16
        data[dst:dst + cols * 16] = blocks[src:src + cols * 16]
    (out / "interface-backend.g_peg_pc").write_bytes(data)


def main(game):
    out = HERE / "out" / MOD_NAME
    out.mkdir(parents=True, exist_ok=True)

    vanilla = vpp.Packfile(game / "patch.vpp_pc").read("hud.lua").decode("latin-1")
    newline = "\r\n" if "\r\n" in vanilla else "\n"
    extra = (HERE / "minimal_hud.lua").read_text(encoding="utf-8").replace("\r\n", "\n")
    extra = extra.replace("%MASK_SIZE%", str(MASK_SIZE)).replace("%MAP_HEIGHT%", str(MAP_HEIGHT))
    text = vanilla.rstrip() + newline + newline.join(extra.split("\n"))
    (out / "hud.lua").write_bytes(text.encode("latin-1"))

    square_mask(game, out)
    print(f"built {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
