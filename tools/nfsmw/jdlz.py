"""JDLZ, EA's LZ compression used by Need for Speed Most Wanted (2005) texture packs.

Header (16 bytes): "JDLZ", 0x02, 0x10, u16 0, u32 uncompressed size, u32 compressed size. Two flag
bytes are read as needed: the first says literal (0) or copy (1); for copies the second picks
the short form (1: 4-bit distance, 12-bit length) or the long form (0: 11-bit distance, 5-bit
length).
"""
import struct


def decompress(data):
    if data[:4] != b"JDLZ":
        raise ValueError("not JDLZ data")
    size, = struct.unpack_from("<I", data, 8)
    out = bytearray(size)
    i, o = 16, 0
    flags1 = flags2 = 1
    while i < len(data) and o < size:
        if flags1 == 1:
            flags1 = data[i] | 0x100
            i += 1
        if flags2 == 1:
            flags2 = data[i] | 0x100
            i += 1
        if flags1 & 1:
            if flags2 & 1:
                length = (data[i + 1] | ((data[i] & 0xF0) << 4)) + 3
                distance = (data[i] & 0x0F) + 1
            else:
                distance = (data[i + 1] | ((data[i] & 0xE0) << 3)) + 17
                length = (data[i] & 0x1F) + 3
            i += 2
            for k in range(length):
                out[o + k] = out[o + k - distance]
            o += length
            flags2 >>= 1
        else:
            out[o] = data[i]
            o += 1
            i += 1
        flags1 >>= 1
    if o != size:
        raise ValueError(f"JDLZ stream ended at {o} of {size} bytes")
    return bytes(out)
