"""Micro Draco: a GTA V Micro Draco (ThatS2K's s2kmicrodraco 1.2, a Compact Rifle replacement:
w_ar_assaultrifle_smg.ydr/.ytd, magazine w_ar_assaultrifle_smg_mag1.ydr/.ytd) in place of SR2's
T3K Urban (weapon "tec9", model p_tec9).

The model (tools/sr2/weaponport.py): the gun's three materials (receiver and grip, rear plate and
front sight, handguard; a texture each) and the magazine, hung from the skeleton's WAPClip bone,
are joined, simplified for SR2's three detail levels and given a new atlas that the textures are
baked onto. The T3K is canted 12.5 degrees, and the Draco is turned the same way at its own size,
its pistol grip centred on the T3K's (both measured over their surfaces: the grips are a few big
polygons). The muzzle flash goes to the flash hider's tip (the skeleton's muzzle bone is the
replaced rifle's, past this barrel) and the shell ejection to the ejection port bone.

The textures: the baked atlas replaces tec9_sp.tga (the T3K's only texture, 128 x 128, used for
both colour and shine), at 512 x 512. The T3K's material darkens its texture to 0.133 grey; the
Draco's colours are in the atlas, so that goes to white.

Its sounds (the K6 Krukov's) and name are in mods/shared.

    python build.py [game folder] [model folder]     # writes out/STILWATER - Micro Draco/
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
sys.path.insert(0, str(ROOT / "tools" / "gta5"))
import bake  # noqa: E402
import unwrap  # noqa: E402
import weaponport  # noqa: E402
import yft  # noqa: E402

MODEL = "p_tec9"
MOD_NAME = "STILWATER - Micro Draco"
GTA_MODEL = "w_ar_assaultrifle_smg.ydr"
GTA_MAGAZINE = "w_ar_assaultrifle_smg_mag1.ydr"
GTA_TEXTURES = ["w_ar_assaultrifle_smg+hi.ytd", "w_ar_assaultrifle_smg_mag1.ytd"]
DIFFUSE = "tec9_sp.tga"
DIFFUSE_SIZE = 512

LOD_TRIANGLES = (4500, 1700, 700)
LOD_DENSITY = (1.0, 0.45, 0.25)         # share of the atlas detail per level
SAMPLES = 1_500_000                     # points on the full model for the bake
SCALE = 1.0
ROLL = 12.5                             # the T3K's cant: its top leans towards +x
# The pistol grips: below the receiver and behind the trigger guard (the T3K's magazine is ahead
# of z 0.09; the Draco's ahead of GTA x -0.025).
T3K_DIFFUSE_COLOUR = (0.133333, 0.133333, 0.133333, 1.0)
T3K_GRIP = dict(y=(-1.0, 0.03), z=(-1.0, 0.09))
GTA_GRIP = dict(x=(-1.0, -0.025), z=(-1.0, -0.005))
GTA_EJECTION_BONE = "Gun_VFX_Eject"


def surface(positions, triangles, count=200_000):
    """Points spread evenly over a mesh's surface."""
    corners = triangles.reshape(-1)
    points, *_ = bake.sample_surface(positions[corners], np.arange(len(corners)).reshape(-1, 3),
                                     np.zeros((len(corners), 2)), np.zeros((len(corners), 3)), count)
    return points


def inside(points, box, axes="xyz"):
    keep = np.ones(len(points), bool)
    for axis, (lo, hi) in box.items():
        k = axes.index(axis)
        keep &= (points[:, k] > lo) & (points[:, k] < hi)
    return points[keep]


def place(vanilla_surface, gta_surface):
    """(matrix, offset) taking GTA positions to SR2's: the Draco's pistol grip centred on the T3K's."""
    m = weaponport.gta_to_sr2(ROLL, SCALE)
    t3k_grip = inside(vanilla_surface, T3K_GRIP)
    draco_grip = inside(gta_surface, GTA_GRIP) @ m.T
    return m, t3k_grip.mean(axis=0) - draco_grip.mean(axis=0)


def main(game, gta_folder):
    original = HERE / "original"
    weaponport.extract(game, MODEL, original)
    header = bytearray((original / f"{MODEL}.smesh_pc").read_bytes())
    vanilla_data = (original / f"{MODEL}.g_smesh_pc").read_bytes()
    vanilla = weaponport.vanilla_positions(bytes(header), vanilla_data)
    box = weaponport.find_box(header, vanilla)

    drawable = yft.read_drawable(gta_folder / GTA_MODEL)
    bones = weaponport.bones(drawable["resource"], drawable["drawable"])
    gun = weaponport.load_gta(gta_folder / GTA_MODEL)
    magazine = weaponport.load_gta(gta_folder / GTA_MAGAZINE, bones["WAPClip"][0])
    gta = weaponport.join([gun, magazine])
    print(f"   GTA model: {len(gta['triangles'])} triangles, {len(gta['positions'])} vertices")

    vanilla_triangles = weaponport.vanilla_triangles(bytes(header), vanilla_data)
    matrix, offset = place(surface(vanilla[0], vanilla_triangles), surface(gta["positions"], gta["triangles"]))

    shapes = weaponport.lods(original, gta, LOD_TRIANGLES)
    levels = [(q, t, uv) for q, t, uv, _ in unwrap.unwrap(shapes, LOD_DENSITY, DIFFUSE_SIZE)]
    textures = weaponport.load_textures([gta_folder / f for f in GTA_TEXTURES], set(gta["textures"]))
    image, covered = weaponport.bake_atlas(levels, gta, textures, DIFFUSE_SIZE, SAMPLES)
    (HERE / "out").mkdir(exist_ok=True)
    image.save(HERE / "out" / "draco_atlas.png")
    print(f"   atlas {DIFFUSE_SIZE} x {DIFFUSE_SIZE}: {100 * covered.mean():.0f}% used")

    data = weaponport.write_mesh(header, levels, matrix, offset, box, weaponport.uv_sets(header, vanilla_data))
    weaponport.write_shadows(header, shapes, matrix, offset)
    weaponport.set_diffuse_colour(header, T3K_DIFFUSE_COLOUR)
    to_sr2 = lambda v: np.asarray(v) @ matrix.T + offset  # noqa: E731
    p = gta["positions"]
    tip = p[p[:, 0] > p[:, 0].max() - 0.004]
    bore = np.array([p[:, 0].max(), 0.0, (tip[:, 2].min() + tip[:, 2].max()) / 2])
    weaponport.set_node(header, "muzzle_flash", to_sr2(bore))
    weaponport.set_node(header, "shell_eject", to_sr2(bones[GTA_EJECTION_BONE][0]))
    print(f"   muzzle {np.round(to_sr2(bore), 4)} (T3K 0.0286 0.1072 0.3662), "
          f"ejection {np.round(to_sr2(bones[GTA_EJECTION_BONE][0]), 4)} (T3K 0.0504 0.117 0.102)")

    peg_header, pack = weaponport.retexture(original, MODEL, DIFFUSE, image)
    folder = HERE / "out" / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{MODEL}.smesh_pc").write_bytes(bytes(header))
    (folder / f"{MODEL}.g_smesh_pc").write_bytes(bytes(data))
    (folder / f"{MODEL}.peg_pc").write_bytes(peg_header)
    (folder / f"{MODEL}.g_peg_pc").write_bytes(pack)
    print(f"built {folder}: mesh {len(data)} bytes (T3K {len(vanilla_data)}), textures {len(pack)} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\draco"))
