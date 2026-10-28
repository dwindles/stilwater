"""XACT3 wave banks (.xwb, version 44 as SR2's audio.vpp_pc has them): replace waves with 16-bit PCM.

Header: "WBND", u32 version, u32 header version, then 5 regions (u32 offset, u32 length): bank
data (flags, entry count, name[64], entry size, name size, alignment, compact flag, build time),
entries (24 bytes each), seek tables (a u32 offset per entry, -1 for none, then the xWMA tables),
entry names (none in SR2's) and the wave data. An entry is u32 flags (low 4 bits) and duration in
samples (the rest), u32 format (tag:2 (0 PCM, 2 ADPCM, 3 xWMA), channels:3, rate:18,
block align:8, 16-bit:1), play region (offset into the wave data, bytes) and loop region (start,
length; samples).

The banks hold no names: SR2 finds a sound by its position among the bank's foley.xtbl entries,
which is its cue's index in the matching .xsb, and the cue plays waves by index (tools: see
mods/glock-switch).

Replaced waves are appended after the wave data (the old data stays, unused), so every other wave
keeps its offset.
"""
import struct

import numpy as np

PCM = 0
REGIONS = 12                # 5 x (offset, length)
ENTRY = 24


def pcm_format(channels, rate):
    return PCM | channels << 2 | rate << 5 | (2 * channels) << 23 | 1 << 31


def read_entries(data):
    """[(flags, samples, format tag, channels, rate, play offset, play length, loop start, loop
    length)] of the bank's waves."""
    entries_offset, = struct.unpack_from("<I", data, REGIONS + 8)
    bank_offset, = struct.unpack_from("<I", data, REGIONS)
    count, = struct.unpack_from("<I", data, bank_offset + 4)
    out = []
    for i in range(count):
        fd, fmt, po, pl, ls, ll = struct.unpack_from("<6I", data, entries_offset + ENTRY * i)
        out.append((fd & 0xF, fd >> 4, fmt & 3, fmt >> 2 & 7, fmt >> 5 & 0x3FFFF, po, pl, ls, ll))
    return out


def replace(data, waves):
    """The bank with waves replaced: {index: (int16 samples (n,) or (n, channels), rate, loop)}.
    A looping wave loops whole."""
    assert data[:4] == b"WBND"
    version, = struct.unpack_from("<I", data, 4)
    assert version == 44, version
    out = bytearray(data)
    bank_offset, = struct.unpack_from("<I", data, REGIONS)
    flags, count = struct.unpack_from("<II", data, bank_offset)
    alignment, = struct.unpack_from("<I", data, bank_offset + 8 + 64 + 8)
    entries_offset, = struct.unpack_from("<I", data, REGIONS + 8)
    seek_offset, seek_length = struct.unpack_from("<II", data, REGIONS + 16)
    wave_offset, wave_length = struct.unpack_from("<II", data, REGIONS + 32)
    assert wave_offset + wave_length == len(data)
    stored = {}                 # identical waves share their data
    for index, (samples, rate, loop) in sorted(waves.items()):
        assert 0 <= index < count
        samples = np.asarray(samples, dtype="<i2")
        channels = 1 if samples.ndim == 1 else samples.shape[1]
        frames = len(samples)
        raw = samples.tobytes()
        if raw not in stored:
            out += bytes(-(len(out) - wave_offset) % alignment)
            stored[raw] = len(out) - wave_offset
            out += raw
        start = stored[raw]
        struct.pack_into("<6I", out, entries_offset + ENTRY * index, frames << 4, pcm_format(channels, rate),
                         start, 2 * channels * frames, 0, frames if loop else 0)
        # PCM has no seek table.
        if flags & 0x80000:
            struct.pack_into("<I", out, seek_offset + 4 * index, 0xFFFFFFFF)
    struct.pack_into("<I", out, REGIONS + 36, len(out) - wave_offset)
    return bytes(out)
