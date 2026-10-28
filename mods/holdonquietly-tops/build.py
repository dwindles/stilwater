"""HOQ tops: hoodies and jackets from downloaded models, baked onto SR2's tops.

- HOQ Balenciaga Hoodie on the hoodie (cmCoa_uHoody01: closed _C and hood-up _CH meshes),
- HOQ Atom Hoodie (a black hoodie with an atom print) on the hoodie with hat (cmCoa_uHoodyHat),
- HOQ Tech Fleece (a black Nike Tech Fleece full zip) on the track jacket (cmCoa_uTrack01: closed
  _C and open _O; the jacket has no hood, so the fleece's hood isn't used),
- HOQ Black Jacket (the jacket of a scanned all-black outfit, a GLB) on the men's leather biker
  jacket (cmCoa_mBiker01_C).

The SR2 meshes keep their shape. Each model (put in SR2's frame: metres, x mirrored because FBX
and glTF are right-handed and SR2 left-handed) is described by a pose (tools/mesh/garment.py),
and each texel of the SR2 top's texture takes the colour of the point of the model that
corresponds to it (torso and hood by the torso box, sleeves along the arm), the nearest model
point facing the same way. Where a model's detail is in its geometry rather than its texture, the
folds can be shaded in from how far its surface turns from the SR2 top's.

The diffuse is mapped by the first UV set, (s/1024, 1 + t/1024), on the hoodies and track jacket
(both sleeves share their texture: one sits a whole texture to the right, so the first sleeve
baked covers both) and by the second, (s/1024, t/1024), on the biker jacket.

Packs keep their exact vanilla size; only the diffuse and the bump map are replaced, the others
(tint masks, detail textures, the hat's, the studs') stay as they are. An open jacket's diffuse
keeps its alpha (cut-outs) and stays DXT5.

    python build.py [game folder] [models folder]     # writes out/STILWATER - HOQ .../
"""
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
import cmesh  # noqa: E402
import fbx  # noqa: E402
import glb  # noqa: E402
import vpp  # noqa: E402
from garment import Pose, to_source  # noqa: E402

SAMPLES = 1_000_000
WORK = 1024
# Tops have big packs (512 x 512 bump maps); sizes tried when filling them.
SIDES = {"diffuse": (1024, 512, 256, 128), "diffuse_alpha": (1024, 512, 256, 128), "bump": (512, 256, 128, 64, 32)}

# SR2 meshes' poses (measured from the meshes).
SR2 = {
    "cmcoa_uhoody01_c": Pose(0.929, 1.519, 1.650, 0.18, (-0.170, 0.118), (0.20, 1.38, -0.058), (0.612, 1.074, 0.048)),
    "cmcoa_uhoody01_ch": Pose(0.929, 1.519, 1.859, 0.18, (-0.170, 0.118), (0.20, 1.38, -0.058), (0.612, 1.074, 0.048)),
    "cmcoa_uhoodyhat_c": Pose(0.835, 1.545, 1.650, 0.18, (-0.202, 0.137), (0.20, 1.38, -0.055), (0.612, 1.075, 0.048)),
    "cmcoa_utrack01_c": Pose(0.982, 1.521, 1.594, 0.18, (-0.131, 0.118), (0.20, 1.38, -0.052), (0.603, 1.085, 0.043)),
    "cmcoa_utrack01_o": Pose(0.982, 1.521, 1.594, 0.18, (-0.131, 0.118), (0.20, 1.38, -0.052), (0.603, 1.085, 0.042)),
    "cmcoa_mbiker01_c": Pose(0.929, 1.530, 1.577, 0.18, (-0.143, 0.115), (0.20, 1.40, -0.049), (0.610, 1.074, 0.042)),
}

GARMENTS = [
    dict(mod="STILWATER - HOQ Balenciaga Hoodie",
         model="balenciaga-hoodie/source/bal hodi khali.fbx", unit=0.01,
         texture="balenciaga-hoodie/textures/hodi_diffuse_1.png", brightness=1.0,
         pose=Pose(0.896, 1.588, 1.907, 0.19, (-0.170, 0.134), (0.22, 1.55, -0.027), (0.27, 1.00, 0.020)),
         # Both meshes share the diffuse layout; the hood-up one matches the model.
         packs=[("cmcoa_uhoody01_c", "cmcoa_uhoody01_ch", "cmcoa_uhoody01_d.tga", "cmcoa_uhoody01_n.tgn"),
                ("cmcoa_uhoody01_ch", "cmcoa_uhoody01_ch", "cmcoa_uhoody01_d.tga", "cmcoa_uhoody01_n.tgn")]),
    dict(mod="STILWATER - HOQ Atom Hoodie",
         model="hoodie-tshirt/source/hoodie_Tshirt.fbx", unit=1.0,
         texture="hoodie-tshirt/textures/Default_1Surface_Color.png", brightness=1.0,
         pose=Pose(0.604, 1.153, 1.228, 0.17, (-0.138, 0.154), (0.16, 1.07, -0.040), (0.44, 0.71, 0.051)),
         packs=[("cmcoa_uhoodyhat_c", "cmcoa_uhoodyhat_c", "cmcoa_uhoody01_d.tga", "cmcoa_uhoody01_n.tgn"),
                ("cmcoa_uhoodyhat_ch", "cmcoa_uhoodyhat_c", "cmcoa_uhoody01_d.tga", "cmcoa_uhoody01_n.tgn")]),
    dict(mod="STILWATER - HOQ Tech Fleece",
         model="nike-tech-fleece-full-zip-hoodie/source/nike tech.fbx", unit=1.0,
         texture="nike-tech-fleece-full-zip-hoodie/textures/(Default_for_Simulation)_FRONT_2260_Base_c.png",
         # The model's black is nearly 0 and its normal map flat (the detail is in its geometry):
         # lifted to a dark heather, with the folds and panel seams shaded in from its surface.
         brightness=1.0, lift=0.10, folds=0.8,
         # Top at the collar: the jacket has no hood.
         pose=Pose(0.992, 1.599, 1.68, 0.19, (-0.206, 0.092), (0.21, 1.56, -0.068), (0.40, 0.98, 0.016)),
         packs=[("cmcoa_utrack01_c", "cmcoa_utrack01_c", "cmcoa_utrack01_d.tga", "cmcoa_utrack01_n.tgn"),
                ("cmcoa_utrack01_o", "cmcoa_utrack01_o", "cmcoa_utrack01_do.tga", "cmcoa_utrack01_no.tgn")]),
    dict(mod="STILWATER - HOQ Black Jacket",
         # Scaled to SR2's height: the scan is 1 unit from the boot soles to the collar.
         model="shirt-with-pants-3d-model-free/source/Shirt with pants 3d model free.glb", unit=1.58,
         texture="shirt-with-pants-3d-model-free/textures/Shirt+with+pants+3d+model+free.glb_basecolor.jpg_0.jpeg",
         brightness=1.0, uv_set=2,
         pose=Pose(0.903, 1.497, 1.580, 0.174, (-0.178, 0.144), (0.221, 1.39, -0.005), (0.49, 1.02, 0.052)),
         packs=[("cmcoa_mbiker01_c", "cmcoa_mbiker01_c", "cmcoa_mbiker01_d.tga", "cmcoa_mbiker01_n.tgn")]),
]


def load_model(path, unit):
    """(positions per corner, triangles, corner UVs (v from the bottom of the texture), corner
    normals) of all the model's meshes (FBX or GLB) in SR2's frame."""
    positions, triangles, uvs, normals, offset = [], [], [], [], 0
    if str(path).lower().endswith(".glb"):
        # Per triangle corner. glTF's v starts at the top, but the downloaded texture is stored upside
        # down, so (as checked by rendering the model) its v reads from the bottom like FBX's.
        parts = [(m["positions"][m["triangles"]].reshape(-1, 3), np.arange(3 * len(m["triangles"])).reshape(-1, 3),
                  m["uvs"][m["triangles"]].reshape(-1, 2), m["normals"][m["triangles"]].reshape(-1, 3))
                 for m in glb.read(path)]
    else:
        parts = [(m["positions"][m["corner_vertex"]], m["triangles"], m["corner_uv"], m["corner_normal"])
                 for m in fbx.meshes(path)]
    for p, tris, uv, n in parts:
        positions.append(p * unit * [-1, 1, 1])
        triangles.append(tris + offset)
        uvs.append(uv)
        n = n * [-1, 1, 1]
        normals.append(n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12))
        offset += len(p)
    return np.concatenate(positions), np.concatenate(triangles), np.concatenate(uvs), np.concatenate(normals)


def diffuse_uvs(mesh, uv_set=1):
    """The diffuse UVs (v down the texture): set 1 at +28 as (s/1024, 1 + t/1024), set 2 at +32 as
    (s/1024, t/1024)."""
    at = 28 if uv_set == 1 else 32
    st = np.frombuffer(mesh["raw"][:, at:at + 4].tobytes(), dtype="<i2").reshape(-1, 2).astype(float)
    return np.stack([st[:, 0] / 1024, (1 if uv_set == 1 else 0) + st[:, 1] / 1024], axis=1)


def main(game, models):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes = vpp.Packfile(game / "meshes.vpp_pc")
    out = HERE / "out"
    for garment in GARMENTS:
        print(garment["mod"])
        p, tris, uvs, normals = load_model(models / garment["model"], garment["unit"])
        points, sample_uvs, sample_normals, _ = bake.sample_surface(p, tris, uvs, normals, SAMPLES)
        tree = cKDTree(points)
        texture = np.asarray(Image.open(models / garment["texture"]).convert("RGB"), dtype=np.float32) / 255
        folder = out / garment["mod"]
        folder.mkdir(parents=True, exist_ok=True)
        baked = {}
        for pack, bake_mesh, diffuse_name, bump_name in garment["packs"]:
            if bake_mesh not in baked:
                for ext in ("cmesh_pc", "g_cmesh_pc"):
                    (original / f"{bake_mesh}.{ext}").write_bytes(meshes.read(f"{bake_mesh}.{ext}"))
                mesh = cmesh.load(original / f"{bake_mesh}.cmesh_pc", original / f"{bake_mesh}.g_cmesh_pc")
                pose = SR2[bake_mesh]
                colour, facing, covered = bake.bake_mapped(
                    diffuse_uvs(mesh, garment.get("uv_set", 1)), mesh["triangles"], mesh["positions"], mesh["normals"],
                    lambda q, n: to_source(q, n, pose, garment["pose"]), tree, sample_uvs, sample_normals,
                    texture, WORK, wrap=True)
                colour = (colour + garment.get("lift", 0)) * garment["brightness"]
                colour *= 1 - garment.get("folds", 0) * (1 - facing[..., None])
                colour = np.clip(colour, 0, 1)
                baked[bake_mesh] = Image.fromarray((colour * 255).astype(np.uint8))
                baked[bake_mesh].save(out / f"{garment['mod'][len('STILWATER - '):].lower().replace(' ', '_')}_{bake_mesh}.png")
                print(f"   baked {bake_mesh}: {100 * covered.mean():.0f}% of the texture")
            print("   " + clothing.rebuild_pack(game, original, pack, diffuse_name, bump_name, baked[bake_mesh],
                                                folder, SIDES))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models"))
