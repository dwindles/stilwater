"""Saints Row 2 texture container (.peg_pc header + .g_peg_pc pixel data, "GEKV" version 10).

Header (0x18 bytes): magic "GEKV", u16 version (10), u16 platform, u32 header file size,
u32 data file size, u16 bitmap count, u16 flags, u16 entry count, u16 alignment.
Entries (0x30 bytes each): u32 data offset, u16 width, u16 height, u16 format, u16 palette format,
u32 fps/flags, u16 frames, ..., u8 mip levels at +0x1B, u32 data size at +0x1C. Names follow.

    python peg.py list <file.peg_pc>
    python peg.py export <file.peg_pc> <file.g_peg_pc> <out_dir>
"""
import io
import struct
import sys
from pathlib import Path

from PIL import Image

FORMATS = {0x190: "DXT1", 0x191: "DXT3", 0x192: "DXT5", 0x197: "A8R8G8B8"}
ENTRY_SIZE = 0x30


def read_header(path):
    d = Path(path).read_bytes()
    magic, version, _, _, data_size, bitmaps, _, entries, _ = struct.unpack_from("<4sHHIIHHHH", d, 0)
    if magic != b"GEKV" or version != 10:
        raise ValueError(f"{path}: not a version 10 peg ({magic!r} v{version})")
    names_at = 0x18 + entries * ENTRY_SIZE
    names = d[names_at:].split(b"\0")
    result = []
    for i in range(entries):
        e = 0x18 + i * ENTRY_SIZE
        offset, width, height, fmt = struct.unpack_from("<IHHH", d, e)
        mips = d[e + 0x1B]
        size, = struct.unpack_from("<I", d, e + 0x1C)
        result.append(dict(name=names[i].decode("latin-1"), offset=offset, width=width, height=height,
                           format=fmt, mips=mips, size=size))
    return result


def to_image(entry, data):
    """Decode the top mip level with Pillow by wrapping it in a DDS header."""
    w, h, fmt = entry["width"], entry["height"], FORMATS.get(entry["format"])
    pixels = data[entry["offset"]:entry["offset"] + entry["size"]]
    if fmt == "A8R8G8B8":
        return Image.frombytes("RGBA", (w, h), pixels[:w * h * 4], "raw", "BGRA")
    if fmt is None:
        raise ValueError(f"unsupported format {entry['format']:#x}")
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    linear = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == "DXT1" else 16)
    header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, h, w, linear, 0, 1)
    header += struct.pack("<II4s20x", 32, 0x4, fmt.encode())
    header += struct.pack("<I16x", 0x1000)
    return Image.open(io.BytesIO(header + pixels))


def encode_dxt1(image, max_levels=None):
    """DXT1 data for image plus its mip chain down to 4x4 (or max_levels levels), as SR2 stores it."""
    return encode(image, "DXT1", max_levels)


def encode(image, pixel_format, max_levels=None):
    """DXT1 or DXT5 data for image plus its mip chain down to 4x4 (or max_levels levels)."""
    image = image.convert("RGB" if pixel_format == "DXT1" else "RGBA")
    levels, blobs = 0, []
    w, h = image.size
    while True:
        buf = io.BytesIO()
        image.resize((w, h), Image.LANCZOS).save(buf, "DDS", pixel_format=pixel_format)
        blobs.append(buf.getvalue()[128:])
        levels += 1
        if w <= 4 or h <= 4 or levels == max_levels:
            break
        w, h = w // 2, h // 2
    return b"".join(blobs), levels


def rebuild(peg_path, gpeg_path, replacements=None):
    """Rebuild a peg pair, swapping textures by name.

    replacements: {texture name: (width, height, format, mip levels, pixel data)}.
    Returns (peg bytes, g_peg bytes). Data blocks are re-laid out on 16-byte boundaries.
    """
    replacements = replacements or {}
    header = bytearray(Path(peg_path).read_bytes())
    data = Path(gpeg_path).read_bytes()
    entries = [e["name"] for e in read_header(peg_path)]

    out = bytearray()
    for i, name in enumerate(entries):
        e = 0x18 + i * ENTRY_SIZE
        offset, = struct.unpack_from("<I", header, e)
        size, = struct.unpack_from("<I", header, e + 0x1C)
        if name in replacements:
            width, height, fmt, mips, blob = replacements[name]
            struct.pack_into("<HHH", header, e + 4, width, height, fmt)
            header[e + 0x1B] = mips
            size = len(blob)
        else:
            blob = data[offset:offset + size]
        struct.pack_into("<I", header, e, len(out))
        struct.pack_into("<I", header, e + 0x1C, size)
        out += blob
        out += b"\0" * (-len(out) % 16)

    struct.pack_into("<I", header, 12, len(out))
    return bytes(header), bytes(out)


def main(argv):
    if argv[1] == "list":
        for e in read_header(argv[2]):
            print(f"{e['name']:40} {e['width']}x{e['height']} {FORMATS.get(e['format'], hex(e['format']))} "
                  f"mips={e['mips']} offset={e['offset']} size={e['size']}")
    elif argv[1] == "export":
        data = Path(argv[3]).read_bytes()
        out = Path(argv[4])
        out.mkdir(parents=True, exist_ok=True)
        for e in read_header(argv[2]):
            image = to_image(e, data)
            target = out / (Path(e["name"]).stem + ".png")
            image.save(target)
            print(f"exported {target.name} {image.size} {image.mode}")


if __name__ == "__main__":
    main(sys.argv)
