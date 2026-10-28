"""Texture sizing for clothing packs.

Clothing texture packs stream into fixed-size slots, so a rebuilt pack must keep its exact vanilla
size: fit_sizes picks a size and mip count for each texture that add up to it.
"""
import itertools

import numpy as np
from PIL import Image

import peg
import vpp

DXT1, DXT5 = 0x190, 0x192
BLOCK_BYTES = {DXT1: 8, DXT5: 16}
# Sizes tried per texture role, and the DXT block size of each.
# "diffuse_alpha" is a diffuse whose alpha matters (cut-outs), kept DXT5.
SIDES = {"diffuse": (512, 256, 128), "diffuse_alpha": (512, 256, 128), "bump": (256, 128, 64, 32, 16),
         "tint": (128, 64, 32, 16, 8, 4)}
FORMATS = {"diffuse": DXT1, "diffuse_alpha": DXT5, "bump": DXT5, "tint": DXT1}


def dxt_size(width, height, block, levels):
    total = 0
    for _ in range(levels):
        total += max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block
        width, height = max(1, width // 2), max(1, height // 2)
    return total


def max_levels(width, height):
    """Mip levels peg.encode writes: halving until a side reaches 4."""
    levels = 1
    while width > 4 and height > 4:
        width, height = width // 2, height // 2
        levels += 1
    return levels


def shapes(sides, tall=False):
    """(width, height) pairs from sides, up to twice as wide as tall (or as tall as wide)."""
    wide = [(w, h) for w in sides for h in sides if h <= w <= 2 * h]
    return [(h, w) for w, h in wide] if tall else wide


def fit_sizes(order, budget, roles, sides=None, keep=None, tall=False):
    """{name: (width, height, mip levels)} so the rebuilt pack is exactly budget bytes, with the most
    diffuse detail, then bump detail, then the fewest diffuse mips. order: texture names as stored;
    roles: {name: "diffuse" | "diffuse_alpha" | "bump" | "tint"} for the textures to resize; sides: optional {role:
    sizes to try}; keep: {name: (width, height, mip levels, format)} for textures left as they are
    (e.g. ones other packs share by name); tall: try textures taller than wide instead of wider than
    tall (UV layouts of long pieces such as trouser legs)."""
    sides = {**SIDES, **(sides or {})}
    keep = keep or {}
    choices = {name: [keep[name][:3]] if name in keep else
               [(w, h, l) for w, h in shapes(sides[roles[name]], tall) for l in range(1, max_levels(w, h) + 1)]
               for name in order}
    blocks = {name: BLOCK_BYTES[keep[name][3] if name in keep else FORMATS[roles[name]]] for name in order}
    by_role = {role: name for name, role in roles.items()}
    best = None
    for combo in itertools.product(*(choices[n] for n in order)):
        total = 0
        for name, (w, h, levels) in zip(order, combo):
            total += dxt_size(w, h, blocks[name], levels)
            total += -total % 16
        if total != budget:
            continue
        chosen = dict(zip(order, combo))
        d = chosen[by_role.get("diffuse", by_role.get("diffuse_alpha"))]
        b = chosen[by_role["bump"]]
        score = (d[0] * d[1], b[0] * b[1], -d[2])
        if best is None or score > best[0]:
            best = (score, chosen)
    if best is None:
        raise ValueError(f"no texture sizes add up to {budget} bytes")
    return best[1]


def bump_from(image, width, height, strength=0.6):
    """SR2 clothing's "normal" map is a grey bump map: detail from image's brightness, high-passed."""
    grey = np.asarray(image.convert("L").resize((width, height), Image.LANCZOS)).astype(float)
    blurred = np.asarray(Image.fromarray(grey.astype(np.uint8))
                         .resize((max(width // 8, 1), max(height // 8, 1)), Image.BILINEAR)
                         .resize((width, height), Image.BICUBIC)).astype(float)
    return Image.fromarray(np.clip(128 + strength * (grey - blurred), 0, 255).astype(np.uint8))


def rebuild_pack(game, original, pack, diffuse_name, bump_name, image, folder, sides=None, tall=False,
                 bump_strength=0.6):
    """Write folder/<pack>.peg_pc and .g_peg_pc with the diffuse replaced by image (a PIL image, any
    size; resized) and the bump map made from it, everything else as in the vanilla pack (saved to
    original/), at the vanilla size. A DXT5 diffuse keeps its vanilla alpha (cut-outs)."""
    (original / f"{pack}.peg_pc").write_bytes(vpp.Packfile(game / "pegs.vpp_pc").read(f"{pack}.peg_pc"))
    (original / f"{pack}.g_peg_pc").write_bytes(vpp.Packfile(game / "textures.vpp_pc").read(f"{pack}.g_peg_pc"))
    header = peg.read_header(original / f"{pack}.peg_pc")
    vanilla_data = (original / f"{pack}.g_peg_pc").read_bytes()
    entries = {e["name"]: e for e in header}
    alpha = entries[diffuse_name]["format"] == DXT5
    keep = {e["name"]: (e["width"], e["height"], e["mips"], e["format"]) for e in header
            if e["name"] not in (diffuse_name, bump_name)}
    sizes = fit_sizes([e["name"] for e in header], len(vanilla_data),
                      {diffuse_name: "diffuse_alpha" if alpha else "diffuse", bump_name: "bump"}, sides, keep, tall)
    (dw, dh, dl), (bw, bh, bl) = sizes[diffuse_name], sizes[bump_name]
    diffuse_image = image.convert("RGB").resize((dw, dh), Image.LANCZOS)
    if alpha:
        vanilla_alpha = peg.to_image(entries[diffuse_name], vanilla_data).convert("RGBA").getchannel("A")
        diffuse_image = diffuse_image.convert("RGBA")
        diffuse_image.putalpha(vanilla_alpha.resize((dw, dh), Image.LANCZOS))
    diffuse, _ = peg.encode(diffuse_image, "DXT5" if alpha else "DXT1", max_levels=dl)
    bump, _ = peg.encode(bump_from(image, bw, bh, bump_strength).convert("RGBA"), "DXT5", max_levels=bl)
    replacements = {diffuse_name: (dw, dh, DXT5 if alpha else DXT1, dl, diffuse), bump_name: (bw, bh, DXT5, bl, bump)}
    peg_header, data = peg.rebuild(original / f"{pack}.peg_pc", original / f"{pack}.g_peg_pc", replacements)
    assert len(data) == len(vanilla_data), (pack, len(data), len(vanilla_data))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pack}.peg_pc").write_bytes(peg_header)
    (folder / f"{pack}.g_peg_pc").write_bytes(data)
    return f"{pack}: diffuse {dw}x{dh} ({dl} mips{', alpha' if alpha else ''}), bump {bw}x{bh} ({bl})"
