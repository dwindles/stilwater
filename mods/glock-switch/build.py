"""Glock 19 with a switch: a GTA V Glock 19 Gen5 model (w_pi_appistol.ydr/.ytd, an AP pistol
replacement) in place of SR2's NR4 (weapon "glock", model p_glock21c).

The model (tools/sr2/weaponport.py): the GTA drawable's high detail (35k triangles, split in two
geometries at the 16-bit index limit) is joined, simplified for SR2's three detail levels and
given a new atlas that the GTA texture is baked onto. The NR4 is canted 12 degrees, and the new
gun is turned the same way, scaled to the NR4's size (SR2's hands are sized for it), its grip put
where the NR4's grip is and its slide top at the same height. The muzzle flash and shell ejection
points move to the new barrel and ejection port.

The textures: the baked atlas replaces Glock21C_256 (weapon packs vary in size, so it grows to
512 x 512); the specular map stays.

The sounds: SR2's automatics loop their fire sound while the trigger is held and play a release
sound after it, so the Glock uses the MAC-10's cues (set in mods/shared, which gives the MAC-10 the
T3K's freed sounds). Their waves in Weapons.xwb (audio.vpp_pc; loose) become GTA V's AP pistol
(ptl_px4 in the "menchos free sound pack 2" WEAPONS_PLAYER.rpf, NG-encrypted, exported to .wav
with D:	ools\sr2-re\gtaaudio, which takes the keys from GTA5.exe): a loop of shots at the
switch's fire rate, each one of its four crack variations over its shot body, and its reverb
tail for the release. A cue's waves come from Weapons.xsb, and its number from the game's
audio_boot.idx_map (tools/sr2/xsb.py; the banks hold no names).

The weapon's full-auto stats and ammo (weapons.xtbl, ammo.xtbl) and its name are in mods/shared,
because only one copy of each table loads.

    python build.py [game folder] [model folder] [sound folder]   # writes out/STILWATER - Glock Switch/
"""
import sys
from pathlib import Path

import wave

import numpy as np

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
import unwrap  # noqa: E402
import vpp  # noqa: E402
import weaponport  # noqa: E402
import xsb  # noqa: E402
import xwb  # noqa: E402

MODEL = "p_glock21c"
MOD_NAME = "STILWATER - Glock Switch"
GTA_MODEL = "gen5 v2/w_pi_appistol.ydr"
GTA_TEXTURES = "gen5 v2/w_pi_appistol+hi.ytd"
GTA_DIFFUSE = "DefaultMaterial_2D_View_1"
DIFFUSE = "glock21c_256.tga"
DIFFUSE_SIZE = 512

LOD_TRIANGLES = (4000, 1500, 600)
LOD_DENSITY = (1.0, 0.45, 0.25)         # share of the atlas detail per level
SAMPLES = 1_500_000                     # points on the full model for the bake
SCALE = 1.15
ROLL = 11.9                             # the NR4's cant: its top leans towards +x
GRIP_BAND = (-0.03, 0.0)                # heights (SR2 y) where both guns are only grip
GTA_BORE = (0.091, 0.0, 0.034)          # muzzle: front of the slide, bore height (GTA frame)
GTA_EJECTION = (-0.005, -0.012, 0.040)  # ejection port, on the gun's right (-y in GTA)

# Sounds (GTA V's AP pistol, ptl_px4 streams).
CRACKS = ["ptl_px4__0x0C29618F", "ptl_px4__0x0E43B847", "ptl_px4__0x158B0031", "ptl_px4__0x1CA53BEF"]
BODY = "ptl_px4__0x138A0BBA"            # the shot's body, 0.28 s
TAIL = "ptl_px4__0x0A98ECBC"            # a shot with its reverb, 0.9 s
RATE = 44100
SHOT_INTERVAL = 0.050                   # mods/shared's Refire_Delay for the glock
LOOP_SHOTS = 16
TAIL_FROM = 0.07                        # the release starts after the shot's own crack
# The MAC-10's cues the Glock takes over: the fire cues loop their wave while the trigger is held.
FIRE_CUES = ("MAC10_FIRE_PLAYER", "MAC10_FIRE_NPC")
RELEASE_CUES = ("MAC10_RELEASE_PLAYER", "MAC10_RELEASE_NPC")


def place(vanilla, gta_positions):
    """(matrix, offset) taking GTA positions to SR2's: slide top at the NR4's height (y), grip
    centred on the NR4's grip (x, z) between the GRIP_BAND heights."""
    m = weaponport.gta_to_sr2(ROLL, SCALE)
    q = gta_positions @ m.T
    lift = vanilla[:, 1].max() - q[:, 1].max()
    q[:, 1] += lift

    def grip_centre(points):
        band = points[(points[:, 1] > GRIP_BAND[0]) & (points[:, 1] < GRIP_BAND[1])]
        return (band.min(axis=0) + band.max(axis=0)) / 2

    offset = grip_centre(vanilla) - grip_centre(q)
    offset[1] = lift
    return m, offset


def load_wav(path):
    """Mono floats at RATE."""
    with wave.open(str(path)) as w:
        assert w.getsampwidth() == 2
        a = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels()).mean(axis=1) / 32768
        rate = w.getframerate()
    t = np.arange(int(len(a) * RATE / rate)) / RATE
    return np.interp(t, np.arange(len(a)) / rate, a)


def to_pcm(a, peak):
    return np.round(a * (peak / np.abs(a).max()) * 32767).astype("<i2")


def sounds(game, folder):
    """Weapons.xwb with the MAC-10's waves replaced by the AP pistol's."""
    cracks = [load_wav(folder / f"{name}.wav") for name in CRACKS]
    body = load_wav(folder / f"{BODY}.wav")[:int(0.15 * RATE)]
    body *= np.clip((0.15 - np.arange(len(body)) / RATE) / 0.08, 0, 1)      # fade out over the last 80 ms
    period = int(round(SHOT_INTERVAL * RATE))
    loop = np.zeros(period * LOOP_SHOTS)
    for i in range(LOOP_SHOTS):
        shot = 0.6 * body.copy()
        crack = cracks[i % len(cracks)]
        shot[:len(crack)] += crack[:len(shot)]
        at = (i * period + np.arange(len(shot))) % len(loop)                 # wraps round: seamless
        np.add.at(loop, at, shot)
    loop = np.tanh(2.0 * loop / np.abs(loop).max())                          # overlapping shots, soft-limited
    tail = load_wav(folder / f"{TAIL}.wav")[int(TAIL_FROM * RATE):]
    tail[:int(0.005 * RATE)] *= np.linspace(0, 1, int(0.005 * RATE))
    loop, tail = to_pcm(loop, 0.9), to_pcm(tail, 0.6)
    waves = {}
    for cue in FIRE_CUES:
        waves.update({w: (loop, RATE, True) for w in xsb.waves_of(game, "Weapons", cue)})
    for cue in RELEASE_CUES:
        waves.update({w: (tail, RATE, False) for w in xsb.waves_of(game, "Weapons", cue)})
    print(f"   sounds: {LOOP_SHOTS}-shot loop {len(loop) / RATE:.2f} s, tail {len(tail) / RATE:.2f} s, Weapons.xwb waves {sorted(waves)}")
    return xwb.replace(vpp.Packfile(game / "audio.vpp_pc").read("Weapons.xwb"), waves)


def main(game, gta_folder, sound_folder):
    original = HERE / "original"
    weaponport.extract(game, MODEL, original)
    header = bytearray((original / f"{MODEL}.smesh_pc").read_bytes())
    vanilla_data = (original / f"{MODEL}.g_smesh_pc").read_bytes()
    vanilla = weaponport.vanilla_positions(bytes(header), vanilla_data)
    box = weaponport.find_box(header, vanilla)

    gta = weaponport.load_gta(gta_folder / GTA_MODEL)
    # Every material samples the one diffuse.
    gta["textures"][:] = GTA_DIFFUSE
    print(f"   GTA model: {len(gta['triangles'])} triangles, {len(gta['positions'])} vertices")
    matrix, offset = place(vanilla[0], gta["positions"])
    shapes = weaponport.lods(original, gta, LOD_TRIANGLES)
    levels = [(q, t, uv) for q, t, uv, _ in unwrap.unwrap(shapes, LOD_DENSITY, DIFFUSE_SIZE)]

    textures = weaponport.load_textures([gta_folder / GTA_TEXTURES], {GTA_DIFFUSE})
    image, covered = weaponport.bake_atlas(levels, gta, textures, DIFFUSE_SIZE, SAMPLES)
    (HERE / "out").mkdir(exist_ok=True)
    image.save(HERE / "out" / "glock_atlas.png")
    print(f"   atlas {DIFFUSE_SIZE} x {DIFFUSE_SIZE}: {100 * covered.mean():.0f}% used")

    data = weaponport.write_mesh(header, levels, matrix, offset, box)
    weaponport.write_shadows(header, shapes, matrix, offset)
    to_sr2 = lambda v: np.asarray(v) @ matrix.T + offset  # noqa: E731
    weaponport.set_node(header, "muzzle_flash", to_sr2(GTA_BORE))
    weaponport.set_node(header, "shell_eject", to_sr2(GTA_EJECTION))
    print(f"   muzzle {np.round(to_sr2(GTA_BORE), 4)} (NR4 0.0275 0.095 0.2036), "
          f"ejection {np.round(to_sr2(GTA_EJECTION), 4)}")

    peg_header, pack = weaponport.retexture(original, MODEL, DIFFUSE, image)
    folder = HERE / "out" / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    for stale in ("weapons.xtbl", "ammo.xtbl"):     # now in mods/shared
        (folder / stale).unlink(missing_ok=True)
    (folder / f"{MODEL}.smesh_pc").write_bytes(bytes(header))
    (folder / f"{MODEL}.g_smesh_pc").write_bytes(bytes(data))
    (folder / f"{MODEL}.peg_pc").write_bytes(peg_header)
    (folder / f"{MODEL}.g_peg_pc").write_bytes(pack)
    (folder / "Weapons.xwb").write_bytes(sounds(game, sound_folder))
    print(f"built {folder}: mesh {len(data)} bytes (NR4 {len(vanilla_data)}), textures {len(pack)} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\glock"),
         Path(sys.argv[3] if len(sys.argv) > 3 else r"D:\tools\sr2-re\models\glock-sounds\wav"))
