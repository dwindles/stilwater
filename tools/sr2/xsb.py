"""XACT sound banks (.xsb, content version 44 as SR2's audio.vpp_pc has them): which waves each cue
plays.

Header: "SDBK", u16 content version, u16 tool version, u16 CRC, u64 last modified, u8 platform,
u16 simple cue count, u16 complex cue count, u16 ?, u16 total cue count, u8 wave bank count,
u16 sound count, u16 cue name table length, u16 ?, then offsets (u32): simple cues, complex cues,
cue names, ?, variation tables, ?, wave bank names, cue name hashes, cue name hash entries, sounds;
then the bank's name (64 bytes).

Cues are numbered simple cues first, then complex ones. A simple cue is u8 flags and the offset of
its sound; a complex cue is u8 flags, u32 offset (its sound when flags & 4, otherwise a variation
table of sounds), u32 transition offset, u8 instance limit, u16 fade in, u16 fade out,
u8 instance behaviour.

A sound is u8 flags (1 complex, 0x0E RPCs, 0x10 DSP presets), u16 category, u8 volume, s16 pitch,
u8 priority, u16 entry length. A simple sound then has u16 wave and u8 wave bank. A complex sound
has u8 track count, its RPC/DSP blocks, then per track u8 volume, u32 event list offset, u8
filter, u8 Q, u16 frequency; each event list is u8 count and events of u32 info (type in the low
5 bits), u16 random offset, u8 separator and a type-specific body (play wave: u8 flags, u16 wave, u8 bank, u8 loop
count (255 = forever), u16 position, u16 angle).

    python xsb.py <bank.xsb>          # lists every cue and its waves
"""
import struct
import sys

PLAY_WAVE, PLAY_WAVE_TRACK_VARIATION, PLAY_WAVE_EFFECT_VARIATION, PLAY_WAVE_TRACK_EFFECT_VARIATION = 1, 3, 4, 6
# Pitch (2 x s16), volume (2 x u8), filter frequency and Q (4 x f32) ranges and u16 flags.
EFFECT_VARIATION = 4 + 2 + 16 + 2


class Reader:
    def __init__(self, data: bytes, at: int = 0):
        self.data, self.at = data, at

    def take(self, fmt: str):
        values = struct.unpack_from("<" + fmt, self.data, self.at)
        self.at += struct.calcsize("<" + fmt)
        return values if len(values) > 1 else values[0]


def read_sound(data: bytes, offset: int) -> dict:
    """{'complex', 'waves': [(wave, bank, loops)], 'length'} for the sound at offset."""
    r = Reader(data, offset)
    flags, category, volume, pitch, priority, length = r.take("BHBhBH")
    waves = []
    if not flags & 1:
        wave, bank = r.take("HB")
        return {"complex": False, "waves": [(wave, bank, 0)], "length": length, "category": category}
    tracks = r.take("B")
    if flags & 0x0E:
        size = r.take("H")
        r.at += size - 2
    if flags & 0x10:
        size = r.take("H")
        r.at += size - 2
    lists = []
    for _ in range(tracks):
        _volume, events, _filter, _q, _frequency = r.take("BIBBH")
        lists.append(events)
    for events in lists:
        e = Reader(data, events)
        for _ in range(e.take("B")):
            info = e.take("I")
            kind = info & 0x1F
            e.at += 3       # u16 random offset, u8 separator
            if kind in (PLAY_WAVE, PLAY_WAVE_EFFECT_VARIATION):
                _flags, wave, bank, loops, _position, _angle = e.take("BHBBHH")
                waves.append((wave, bank, loops))
                if kind == PLAY_WAVE_EFFECT_VARIATION:
                    e.at += EFFECT_VARIATION
            elif kind in (PLAY_WAVE_TRACK_VARIATION, PLAY_WAVE_TRACK_EFFECT_VARIATION):
                _flags, loops, _position, _angle = e.take("BBHH")
                if kind == PLAY_WAVE_TRACK_EFFECT_VARIATION:
                    e.at += EFFECT_VARIATION
                count, _variation = e.take("HH")
                e.at += 4
                for _ in range(count):
                    wave, bank, _low, _high = e.take("HBBB")
                    waves.append((wave, bank, loops))
            else:
                break       # other events (volume, pitch, markers) don't play waves
    return {"complex": True, "waves": waves, "length": length, "category": category}


def read_cues(data: bytes) -> list:
    """One dict per cue, in cue order: {'index', 'simple', 'sounds': [offsets], 'waves'}."""
    r = Reader(data)
    assert r.take("4s") == b"SDBK", "not an XACT sound bank"
    _content, _tool, _crc, _modified, _platform = r.take("HHHQB")
    simple_count, complex_count, _, _total, bank_count, sound_count, _names, _ = r.take("HHHHBHHH")
    simple_at, complex_at, _names_at, _, variations_at, _, banks_at, *_ = r.take("10I")
    cues = []
    c = Reader(data, simple_at)
    for _ in range(simple_count):
        _flags, sound = c.take("BI")
        cues.append({"simple": True, "sounds": [sound]})
    c = Reader(data, complex_at)
    for _ in range(complex_count):
        flags, target, _transition, _limit, _fade_in, _fade_out, _behaviour = c.take("BIIBHHB")
        if flags & 4:
            sounds = [target]
        else:
            v = Reader(data, target)
            entries, vflags, _, _ = v.take("HHHH")
            kind = (vflags >> 3) & 7
            sounds = []
            for _ in range(entries):
                if kind == 0:         # wave entries: u16 wave, u8 bank, u8 weight min, u8 weight max
                    wave, bank, _, _ = v.take("HBBB")
                    sounds.append(("wave", wave, bank))
                elif kind in (1, 3):  # sound entries: u32 sound, u8 weight min, u8 weight max
                    sound, _, _ = v.take("IBB")
                    sounds.append(sound)
                elif kind == 4:       # sound entries with a 32-bit weight pair
                    sound, _, _ = v.take("Iff")
                    sounds.append(sound)
                else:
                    sound, = (v.take("I"),)
                    v.at += 2
                    sounds.append(sound)
        cues.append({"simple": False, "sounds": sounds})
    for index, cue in enumerate(cues):
        cue["index"] = index
        cue["waves"] = []
        for sound in cue["sounds"]:
            if isinstance(sound, tuple):
                cue["waves"].append((sound[1], sound[2], 0))
            else:
                cue["waves"] += read_sound(data, sound)["waves"]
    return cues


def cue_names(game) -> dict:
    """{bank: [cue names in cue order]} from audio_boot.idx_map and audio_level.idx_map
    (meshes.vpp_pc): text files of "bank" count, then index and "name" per cue. The banks carry
    no names; the game finds a sound's cue through these (0x0046FA40). foley.xtbl's order isn't
    the cue order."""
    import re
    from pathlib import Path
    import vpp
    meshes = vpp.Packfile(Path(game) / "meshes.vpp_pc")
    banks = {}
    for name in ("audio_boot.idx_map", "audio_level.idx_map"):
        text = meshes.read(name).decode("latin-1").replace("\r", "")
        for bank, rows in re.findall(r'^"([^"]+)"\t+\d+\n((?:\t.*\n?)+)', text, re.M):
            cues = re.findall(r'\t(\d+)\t+"([^"]*)"', rows)
            banks[bank] = [n for _, n in sorted(cues, key=lambda c: int(c[0]))]
    return banks


def waves_of(game, bank: str, cue: str) -> list:
    """The waves (indices into the bank's .xwb) the named cue plays."""
    from pathlib import Path
    import vpp
    index = cue_names(game)[bank].index(cue)
    data = vpp.Packfile(Path(game) / "audio.vpp_pc").read(f"{bank}.xsb")
    return [wave for wave, _bank, _loops in read_cues(data)[index]["waves"]]


def main(argv):
    data = open(argv[1], "rb").read()
    for cue in read_cues(data):
        waves = ", ".join(f"{w}{'(loop)' if loops == 255 else ''}" for w, _bank, loops in cue["waves"])
        print(f"{cue['index']:4d} {'simple ' if cue['simple'] else 'complex'} {waves}")


if __name__ == "__main__":
    main(sys.argv)
