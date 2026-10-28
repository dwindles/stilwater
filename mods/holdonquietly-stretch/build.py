"""HOQ Stretch Jeans: the medium-wash jeans of a CLO "T-shirt and Jeans" model on SR2's men's tight
torn jeans (cmBot_mJeansMF04_M, "Men's Jeans 2"), cut slim and straight.

- The mesh gets the slim straight fit of tools/sr2/legfit.py.
- The model's jeans (its denim pieces and their buttons and rivets, an OBJ with UDIM textures) are
  put in SR2's frame (y up, front +z, centimetres to metres, x mirrored: CLO is right-handed, SR2
  left-handed) and stretched to the box of the slimmed jeans. Each texel of the jeans' texture
  takes the colour of the nearest point of the model facing the same way.
- This mesh's diffuse is mapped by its second UV set (the first tiles the tear detail). The
  diffuse becomes DXT1 without tears (the original's DXT5 alpha cut them). The textures the pack
  shares by name with the other men's jeans (tint masks, detail, "lop") stay as they are.

The pack keeps its exact vanilla size (clothing streams into fixed slots).

    python build.py [game folder] [model folder]     # writes out/STILWATER - HOQ Stretch Jeans/
"""
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
import bake  # noqa: E402
import clothing  # noqa: E402
import legfit  # noqa: E402
import obj  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402

MESH = PACK = "cmbot_mjeansmf04_m"
DIFFUSE, BUMP = "cmbot_mjeansmf04_d.tga", "cmbot_mjeansmf04_n.tgn"
MOD_NAME = "STILWATER - HOQ Stretch Jeans"
MODEL = "Tshirt and Jeans.obj"
MODEL_TEXTURE = "Tshirt and Jeans_diffuse_{tile}.png"      # UDIM tiles
JEANS_MATERIALS = ("Denim_Lightweight_FRONT_1394546", "Material744700")   # denim, buttons and rivets

SAMPLES = 800_000          # points sampled on the model's jeans for nearest-point lookups
WORK = 1024                # bake resolution (resized to the diffuse size)
# The model's denim weave is drawn at different scales per piece (the back pockets' is coarse) and
# turns to speckle at game resolution; the game's jeans add their own tiling weave (dt_jeans), so
# the model's textures are softened to this size first, keeping the fading and the pieces.
MODEL_TEXTURE_SIZE = 384
UV_OFFSET = 32             # this mesh's diffuse UVs: int16 / 1024, v down the texture


def model_jeans(folder, cache):
    """(positions per corner, triangles, corner UVs, corner normals) of the model's jeans in its own
    frame; parsing the whole OBJ is slow, so the jeans are cached."""
    source = folder / MODEL
    if cache.exists() and cache.stat().st_mtime > source.stat().st_mtime:
        d = np.load(cache)
        return d["positions"], d["triangles"], d["uvs"], d["normals"]
    mesh = obj.read(source)
    parts = [mesh["groups"][m] for m in JEANS_MATERIALS if m in mesh["groups"]]
    vertex = np.concatenate([g["vertex"] for g in parts])
    uv = np.concatenate([g["uv"] for g in parts])
    normal = np.concatenate([g["normal"] for g in parts])
    positions = mesh["positions"][vertex.reshape(-1)]
    uvs = mesh["uvs"][uv.reshape(-1)]
    normals = mesh["normals"][normal.reshape(-1)]
    triangles = np.arange(len(positions)).reshape(-1, 3)
    np.savez(cache, positions=positions, triangles=triangles, uvs=uvs, normals=normals)
    return positions, triangles, uvs, normals


def sample_udim(folder, uvs):
    """Colours (0..1) at UDIM UVs: tile 1001 + floor(u) + 10 floor(v), v from the bottom."""
    colours = np.zeros((len(uvs), 3))
    tiles = 1001 + np.floor(uvs[:, 0]).astype(int) + 10 * np.floor(uvs[:, 1]).astype(int)
    for tile in np.unique(tiles):
        image = Image.open(folder / MODEL_TEXTURE.format(tile=tile)).convert("RGB")
        image = np.asarray(image.resize((MODEL_TEXTURE_SIZE, MODEL_TEXTURE_SIZE), Image.BOX), dtype=np.float32) / 255
        s = tiles == tile
        colours[s] = bake.bilinear(image, uvs[s])
    return colours


def vertex_normals(positions, triangles):
    n = np.zeros_like(positions)
    face = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                    positions[triangles[:, 2]] - positions[triangles[:, 0]])
    for k in range(3):
        np.add.at(n, triangles[:, k], face)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


def main(game, model):
    original = HERE / "original"
    meshes = vpp.Packfile(game / "meshes.vpp_pc")
    jeans, positions = legfit.fit(meshes, original, MESH)
    (original / f"{PACK}.peg_pc").write_bytes(vpp.Packfile(game / "pegs.vpp_pc").read(f"{PACK}.peg_pc"))
    (original / f"{PACK}.g_peg_pc").write_bytes(vpp.Packfile(game / "textures.vpp_pc").read(f"{PACK}.g_peg_pc"))
    triangles = jeans["triangles"]
    used = np.unique(triangles)

    # The model's jeans in SR2's frame, stretched to the slimmed jeans' box.
    p, model_triangles, model_uvs, model_normals = model_jeans(model, original / "model_jeans.npz")
    p = p * [-0.01, 0.01, 0.01]
    n = model_normals * [-1, 1, 1]
    lo, hi = p.min(axis=0), p.max(axis=0)
    tlo, thi = positions[used].min(axis=0), positions[used].max(axis=0)
    scale = (thi - tlo) / (hi - lo)
    p = tlo + (p - lo) * scale
    n = n / scale
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    print(f"   model jeans {np.round(100 * (hi - lo), 1)} cm stretched by {np.round(scale * 100, 2)} %")
    points, uvs, normals, _ = bake.sample_surface(p, model_triangles, model_uvs, n, SAMPLES)

    # Normals of the slimmed jeans, facing the way the game's do (strip winding varies).
    new_normals = vertex_normals(positions, triangles)
    flip = (new_normals * jeans["normals"]).sum(axis=1) < 0
    new_normals[flip] *= -1

    raw = jeans["raw"]
    game_uvs = np.frombuffer(raw[:, UV_OFFSET:UV_OFFSET + 4].tobytes(), dtype="<i2").reshape(-1, 2) / 1024.0
    rows, cols, tris, w = bake.rasterize(game_uvs, triangles, WORK)
    corners = triangles[tris]
    texel_points = (w[..., None] * positions[corners]).sum(axis=1)
    texel_normals = (w[..., None] * new_normals[corners]).sum(axis=1)
    texel_normals /= np.linalg.norm(texel_normals, axis=1, keepdims=True) + 1e-12
    nearest = bake.nearest_facing(cKDTree(points), normals, texel_points, texel_normals)
    image = np.zeros((WORK, WORK, 3))
    covered = np.zeros((WORK, WORK), bool)
    image[rows, cols] = sample_udim(model, uvs[nearest])
    covered[rows, cols] = True
    baked = Image.fromarray((np.clip(bake.dilate(image, covered), 0, 1) * 255).astype(np.uint8))
    print(f"   {100 * covered.mean():.0f}% of the texture baked")

    header = peg.read_header(original / f"{PACK}.peg_pc")
    vanilla_data = (original / f"{PACK}.g_peg_pc").read_bytes()
    keep = {e["name"]: (e["width"], e["height"], e["mips"], e["format"]) for e in header
            if e["name"] not in (DIFFUSE, BUMP)}
    sizes = clothing.fit_sizes([e["name"] for e in header], len(vanilla_data), {DIFFUSE: "diffuse", BUMP: "bump"},
                               keep=keep, tall=True)
    (dw, dh, dl), (bw, bh, bl) = sizes[DIFFUSE], sizes[BUMP]
    out = HERE / "out"
    diffuse_image = baked.resize((dw, dh), Image.LANCZOS)
    diffuse_image.save(out / "hoq_stretch_diffuse.png")
    diffuse, _ = peg.encode(diffuse_image, "DXT1", max_levels=dl)
    # The clothing "normal" map is a grey bump map: the denim's seams, pockets and weave from its
    # brightness, high-passed.
    grey = np.asarray(baked.convert("L").resize((bw, bh), Image.LANCZOS)).astype(float)
    blurred = np.asarray(Image.fromarray(grey.astype(np.uint8)).resize((max(bw // 8, 1), max(bh // 8, 1)), Image.BILINEAR)
                         .resize((bw, bh), Image.BICUBIC)).astype(float)
    bump_grey = Image.fromarray(np.clip(128 + 0.8 * (grey - blurred), 0, 255).astype(np.uint8))
    bump, _ = peg.encode(bump_grey.convert("RGBA"), "DXT5", max_levels=bl)
    replacements = {DIFFUSE: (dw, dh, clothing.DXT1, dl, diffuse), BUMP: (bw, bh, clothing.DXT5, bl, bump)}

    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    peg_header, pack = peg.rebuild(original / f"{PACK}.peg_pc", original / f"{PACK}.g_peg_pc", replacements)
    assert len(pack) == len(vanilla_data), (len(pack), len(vanilla_data))
    data = bytearray((original / f"{MESH}.g_cmesh_pc").read_bytes())
    for i, q in enumerate(positions):
        struct.pack_into("<3f", data, i * jeans["stride"], *q)
    (folder / f"{PACK}.peg_pc").write_bytes(peg_header)
    (folder / f"{PACK}.g_peg_pc").write_bytes(pack)
    (folder / f"{MESH}.cmesh_pc").write_bytes((original / f"{MESH}.cmesh_pc").read_bytes())
    (folder / f"{MESH}.g_cmesh_pc").write_bytes(bytes(data))
    print(f"built {folder}: diffuse {dw}x{dh} ({dl} mips), bump {bw}x{bh} ({bl})")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\tshirt_jeans"))
