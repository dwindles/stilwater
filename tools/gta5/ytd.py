"""Read GTA V texture dictionaries (.ytd, RSC7) into Pillow images.

TextureDictionary (system segment root): pointer list of name hashes at 0x20 and of textures at
0x30 (ResourcePointerList64). Texture: name pointer at 0x28, width/height/depth/stride (u16) at
0x50, format (u32, a FourCC or D3DFORMAT) at 0x58, mip levels (u8) at 0x5D, pixel data pointer
(graphics segment) at 0x70. Layouts follow CodeWalker's (MIT) definitions.

    python ytd.py <file.ytd> [out_dir]
"""
import io
import os
import struct
import sys

from PIL import Image

from yft import Resource

FOURCC = {b"DXT1": "DXT1", b"DXT3": "DXT3", b"DXT5": "DXT5", b"ATI1": "BC4", b"ATI2": "BC5", b"BC7\0": "BC7"}


def textures(path):
    """{name: (width, height, format, levels, bytes of all levels)}"""
    res = Resource(path)
    root = 0x50000000
    out = {}
    for pointer in res.pointer_list(root + 0x30):
        name = _cstr(res, res.u64(pointer, 0x28))
        width, height, depth, stride = res.unpack("<4H", pointer, 0x50)
        fmt, = res.unpack("<I", pointer, 0x58)
        levels, = res.unpack("<B", pointer, 0x5D)
        data_pointer = res.u64(pointer, 0x70)
        buf, off = res.at(data_pointer)
        out[name] = (width, height, fmt, levels, buf, off)
    return out


def _cstr(res, pointer):
    buf, off = res.at(pointer)
    return buf[off:buf.index(b"\0", off)].decode("latin-1")


def to_image(width, height, fmt, buf, off):
    four = struct.pack("<I", fmt)
    kind = FOURCC.get(four)
    if kind in ("DXT1", "DXT3", "DXT5"):
        block = 8 if kind == "DXT1" else 16
        size = max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block
        flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
        header = struct.pack("<4sIIIIIII44x", b"DDS ", 124, flags, height, width, size, 0, 1)
        header += struct.pack("<II4s20x", 32, 0x4, kind.encode())
        header += struct.pack("<I16x", 0x1000)
        return Image.open(io.BytesIO(header + buf[off:off + size])).convert("RGBA")
    if fmt == 21:   # D3DFMT_A8R8G8B8
        return Image.frombytes("RGBA", (width, height), buf[off:off + width * height * 4], "raw", "BGRA")
    raise ValueError(f"unsupported texture format {four!r} / {fmt}")


def main(argv):
    found = textures(argv[1])
    out = argv[2] if len(argv) > 2 else None
    for name, (w, h, fmt, levels, buf, off) in found.items():
        four = struct.pack("<I", fmt)
        print(f"{name:45} {w}x{h} {FOURCC.get(four, fmt)} levels {levels}")
        if out:
            os.makedirs(out, exist_ok=True)
            try:
                to_image(w, h, fmt, buf, off).save(os.path.join(out, name + ".png"))
            except Exception as e:
                print("   ", e)


if __name__ == "__main__":
    main(sys.argv)
