"""Read Need for Speed Most Wanted (2005) PC texture packs ("TPK", chunk 0xB3300000).

A TPK holds a header chunk (0xB3310000) and a data chunk (0xB3320000). Two layouts occur:

- Uncompressed (global bundles such as GLOBAL\\GLOBALB.BUN): 0x33310004 has a 0x7C texture header
  per texture and 0x33310005 a 0x20 format record (FourCC at +0x14); pixel data sits in 0x33320002
  at the header's data offset, counted from the end of that chunk's 0x11 alignment padding.
- Compressed (car packs, CARS\\<car>\\TEXTURES.BIN): 0x33310003 lists (u32 name hash, u32 file
  offset, u32 compressed size, u32 size, u32, u32) per texture. Each blob is JDLZ (EA HUFF also
  occurs and is skipped) and decompresses to the pixel data followed by the 0x7C header and the
  0x20 format record.

Texture header: name at +0x0C, hash +0x24, data offset +0x30, palette offset +0x34, data size +0x38,
palette size +0x3C, width/height (u16) +0x44, mip count +0x4E. FourCC 41 (D3DFMT_P8) is 8-bit
indices into a BGRA palette. Names hash with EA's bStringHash (h = h * 33 + c from 0xFFFFFFFF), as
geometry refers to them.

    python tpk.py <file> [out_dir]
"""
import io
import os
import struct
import sys

from PIL import Image

import jdlz


def bin_hash(name):
    h = 0xFFFFFFFF
    for c in name.encode("latin-1"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def _chunks(d, off, end):
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", d, off)
        yield cid, off + 8, size
        off += 8 + size


def _all(d, cid, off=0, end=None):
    """Every chunk with this id, at any depth: [(body offset, size)]."""
    out = []
    for c, body, size in _chunks(d, off, len(d) if end is None else end):
        if c == cid:
            out.append((body, size))
        elif c & 0x80000000:
            out += _all(d, cid, body, body + size)
    return out


def _header(raw, at, fmt_at):
    name = raw[at + 0x0C:at + 0x24].split(b"\0")[0].decode("latin-1")
    h, = struct.unpack_from("<I", raw, at + 0x24)
    offset, palette_offset, size, palette_size = struct.unpack_from("<4I", raw, at + 0x30)
    width, height = struct.unpack_from("<HH", raw, at + 0x44)
    return h, dict(name=name, width=width, height=height, mips=raw[at + 0x4E], offset=offset, size=size,
                   palette_offset=palette_offset, palette_size=palette_size,
                   fourcc=bytes(raw[fmt_at + 0x14:fmt_at + 0x18]), palette=b"")


def textures(path):
    """{hash: dict(name, width, height, fourcc, mips, data)} over every TPK in the file, and the
    hashes of textures skipped for an unsupported codec."""
    d = open(path, "rb").read()
    out, skipped = {}, []
    for tpk, tpk_size in _all(d, 0xB3300000):
        info = {c: (b, s) for c, b, s in _chunks(d, tpk, tpk + tpk_size)}
        head = {c: (b, s) for c, b, s in _chunks(d, *(lambda b, s: (b, b + s))(*info[0xB3310000]))}
        if 0x33310003 in head:
            body, size = head[0x33310003]
            for k in range(size // 24):
                h, off, csize, _, _, _ = struct.unpack_from("<6I", d, body + 24 * k)
                blob = d[off:off + csize]
                if blob[:4] != b"JDLZ":
                    skipped.append(h)
                    continue
                raw = jdlz.decompress(blob)
                _, tex = _header(raw, len(raw) - 0x9C, len(raw) - 0x20)
                tex["data"] = raw[:tex["size"]]
                out[h] = tex
        elif 0x33310004 in head:
            hb, hs = head[0x33310004]
            fb, _ = head[0x33310005]
            data_body, data_size = next((b, s) for c, b, s in _chunks(d, *(lambda b, s: (b, b + s))(*info[0xB3320000]))
                                        if c == 0x33320002)
            base = data_body
            while d[base:base + 4] == b"\x11\x11\x11\x11":
                base += 4
            for k in range(hs // 0x7C):
                h, tex = _header(d, hb + 0x7C * k, fb + 0x20 * k)
                tex["data"] = d[base + tex["offset"]:base + tex["offset"] + tex["size"]]
                if tex["palette_size"]:
                    p0 = base + tex["palette_offset"]
                    tex["palette"] = d[p0:p0 + tex["palette_size"]]
                out[h] = tex
    return out, skipped


PALETTE_8 = struct.pack("<I", 41)   # D3DFMT_P8


def _apply_palette(indices, lookup, w, h):
    image = Image.new("RGBA", (w, h))
    image.putdata([lookup[i] for i in indices])
    return image


def to_image(tex):
    w, h, four = tex["width"], tex["height"], tex["fourcc"]
    if four in (b"DXT1", b"DXT3", b"DXT5"):
        block = 8 if four == b"DXT1" else 16
        size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
        flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
        header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, h, w, size, 0, 1)
        header += struct.pack("<II4s20x", 32, 0x4, four)
        header += struct.pack("<I16x", 0x1000)
        return Image.open(io.BytesIO(header + tex["data"][:size])).convert("RGBA")
    if four == PALETTE_8 and tex["palette"]:
        palette = Image.frombytes("RGBA", (len(tex["palette"]) // 4, 1), tex["palette"], "raw", "BGRA")
        return _apply_palette(tex["data"][:w * h], list(palette.getdata()), w, h)
    if len(tex["data"]) >= w * h * 4:
        return Image.frombytes("RGBA", (w, h), tex["data"][:w * h * 4], "raw", "BGRA")
    raise ValueError(f"{tex['name']}: unsupported format {four!r}")


def main(argv):
    found, skipped = textures(argv[1])
    out = argv[2] if len(argv) > 2 else None
    for h, t in sorted(found.items(), key=lambda x: x[1]["name"]):
        print(f"{h:08x} {t['name']:32} {t['width']}x{t['height']} {t['fourcc'].decode('latin-1', 'replace')}")
        if out:
            os.makedirs(out, exist_ok=True)
            try:
                to_image(t).save(os.path.join(out, t["name"] + ".png"))
            except ValueError as e:
                print("   ", e)
    if skipped:
        print("not JDLZ (skipped):", " ".join(f"{h:08x}" for h in skipped))


if __name__ == "__main__":
    main(sys.argv)
