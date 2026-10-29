"""Build the Undercover jeans: the photos in ref/ on a new item cloned from SR2's leather biker pants.

The photos are projected with the HOQ Jeans' projection (mods/holdonquietly-jeans/project.py) onto
the men's tight jeans' texture layout, using the outlines below, measured on the 700x933 photos (the
jeans traced against the floor by colour). The biker pants (which sit over the underwear where the
tight jeans let it through at the seat) take that texture through 3D: each texel of theirs the
colour of the nearest point of the tight jeans facing the same way, both being on the same body.
Their UVs repeat a leather tile, so they get a layout of their own first (uvtransfer.py), written
into the mesh. Their leather bump map gives way to one made from the denim, and the diffuse goes
from 256 to 512.

The clone is the biker pants' mesh and texture pack copied under a new name of the same length
(cmbot_ubiker01 becoming cmbot_ubikuc01), like the tees (mods/tees): the mesh and the pack name
their textures in plain text. mods/shared adds the item to customization_items, the stores and the
strings.

    python build.py [game folder]     # writes out/STILWATER - Undercover Jeans/
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
sys.path.insert(0, str(HERE.parent.parent / "tools" / "sr2"))
sys.path.insert(0, str(HERE.parent.parent / "tools" / "mesh"))
import bake  # noqa: E402
import clothing  # noqa: E402
import cmesh  # noqa: E402
import vpp  # noqa: E402
from uvtransfer import layout  # noqa: E402

_spec = importlib.util.spec_from_file_location("project", HERE.parent / "holdonquietly-jeans" / "project.py")
project = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(project)

JEANS = "cmbot_mjeansmf02_m"      # the tight jeans the photos are projected for
PACK = "cmbot_ubiker01_m"
DIFFUSE, BUMP = "cmbot_ubiker01_d.tga", "cmbot_ubiker01_n.tgn"
SOURCE, CLONE = "cmbot_ubiker01", "cmbot_ubikuc01"
MOD_NAME = "STILWATER - Undercover Jeans"
WORK = 1024

PHOTOS = {
    "front": dict(
        file=HERE / "ref" / "front.png",
        rows=[90, 125, 395, 873],
        edges=[(90, 207, 484), (125, 200, 488), (165, 191, 497), (205, 188, 505), (245, 185, 510),
               (325, 186, 514), (405, 189, 516), (485, 191, 520), (565, 188, 525), (645, 187, 530),
               (725, 187, 534), (805, 188, 535), (873, 190, 535)],
        inner=[(395, 353, 353), (405, 345, 361), (485, 344, 366), (565, 347, 368), (645, 352, 368),
               (873, 352, 368)],
        centre=[(90, 346), (395, 353)],
    ),
    "back": dict(
        file=HERE / "ref" / "back.png",
        rows=[84, 122, 390, 855],
        edges=[(84, 210, 506), (166, 200, 510), (206, 189, 511), (246, 190, 514), (326, 192, 517),
               (406, 194, 516), (486, 193, 518), (566, 191, 520), (646, 187, 522), (726, 185, 526),
               (806, 185, 528), (855, 188, 527)],
        inner=[(390, 356, 356), (406, 348, 363), (486, 345, 364), (566, 345, 364), (646, 344, 363),
               (686, 349, 363), (855, 345, 362)],
        centre=[(84, 358), (390, 356)],
    ),
}


def rename(data):
    return re.sub(re.escape(SOURCE.encode()), CLONE.encode(), data, flags=re.I)


def transfer(texture, source, target):
    """texture (on source's UVs) carried onto target's UVs through the nearest point of source
    facing the same way. The game's v runs down the texture and repeats."""
    points, uvs, normals, _ = bake.sample_surface(source["positions"], source["triangles"], source["uvs"],
                                                  source["normals"], 400_000)
    rows, cols, tris, w = bake.rasterize(target["uvs"], target["triangles"], WORK, wrap=True)
    corners = target["triangles"][tris]
    texel_points = (w[..., None] * target["positions"][corners]).sum(axis=1)
    texel_normals = (w[..., None] * target["normals"][corners]).sum(axis=1)
    texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
    nearest = bake.nearest_facing(cKDTree(points), normals, texel_points, texel_normals)
    image = np.asarray(texture.convert("RGB")).astype(float) / 255
    colour = bake.bilinear(image, uvs[nearest] * [1, -1])    # bilinear's v runs up
    out = np.zeros((WORK, WORK, 3))
    covered = np.zeros((WORK, WORK), bool)
    out[rows, cols] = colour
    covered[rows, cols] = True
    return Image.fromarray((np.clip(bake.dilate(out, covered), 0, 1) * 255).astype(np.uint8))


def main(game):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    for name in (JEANS, PACK):
        for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), (".peg_pc", "pegs"),
                          (".g_peg_pc", "textures"), ("_pc.morph_pc", "meshes")):
            if not (original / f"{name}{ext}").exists():
                (original / f"{name}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{name}{ext}"))

    out = HERE / "out"
    out.mkdir(exist_ok=True)
    texture = Image.fromarray(project.bake(PHOTOS))
    texture.save(out / "undercover_diffuse_1024.png")
    jeans = cmesh.load(original / f"{JEANS}.cmesh_pc", original / f"{JEANS}.g_cmesh_pc")
    biker = cmesh.load(original / f"{PACK}.cmesh_pc", original / f"{PACK}.g_cmesh_pc")
    biker["uvs"] = layout(biker)
    mesh_data = bytearray((original / f"{PACK}.g_cmesh_pc").read_bytes())
    for i, (u, v) in enumerate(biker["uvs"]):
        # cmesh: int16 u = u * 1024 and t, v = 1 + t / 1024.
        struct.pack_into("<hh", mesh_data, i * biker["stride"] + 28, round(u * 1024), round((v - 1) * 1024))
    image = transfer(texture, jeans, biker)
    image.save(out / "undercover_biker_diffuse_1024.png")

    folder = out / MOD_NAME
    for old in folder.glob("*"):
        old.unlink()
    folder.mkdir(exist_ok=True)
    work = out / "pack"
    # The leather bump map took most of the pack; the sizes must add up to it, so it may stay 512 wide.
    print(clothing.rebuild_pack(game, original, PACK, DIFFUSE, BUMP, image, work,
                                sides={"bump": (512, 256, 128, 64, 32, 16)}))
    clone = rename(PACK.encode()).decode()
    (folder / f"{clone}.peg_pc").write_bytes(rename((work / f"{PACK}.peg_pc").read_bytes()))
    (folder / f"{clone}.g_peg_pc").write_bytes((work / f"{PACK}.g_peg_pc").read_bytes())
    (folder / f"{clone}.cmesh_pc").write_bytes(rename((original / f"{PACK}.cmesh_pc").read_bytes()))
    (folder / f"{clone}.g_cmesh_pc").write_bytes(bytes(mesh_data))
    # The body shapes (thin to fat, the sliders): without them the pants are the wrong size.
    (folder / f"{clone}_pc.morph_pc").write_bytes((original / f"{PACK}_pc.morph_pc").read_bytes())
    print(f"built {folder}: {clone}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"))
