"""Read unencrypted ("OPEN") GTA V RPF7 archives, such as mods' dlc.rpf, including archives nested in
them. AES- and NG-encrypted archives (the game's own) need the game's keys and aren't supported.

Header: "RPF7", u32 entry count, u32 names length, u32 encryption ("OPEN" = 0x4E45504F), then
16-byte entries and the names (NUL-terminated, by offset). Entry 0 is the root directory.
- Directory: u32 name offset, 0x7FFFFF00, u32 first entry, u32 entry count.
- File: u16 name offset, u24 stored size, u24 offset in 512-byte blocks (bit 23 set for
  resources), then for a binary file u32 uncompressed size (stored deflated when it differs) and
  u32 encryption, for a resource u32 system and u32 graphics flags. A resource's stored data is the
  whole RSC7 file, header included; a stored size of 0xFFFFFF means the size is in that header.
Layouts follow CodeWalker's (MIT) definitions.

    python rpf.py <archive.rpf>      # lists the files, nested archives included
"""
import struct
import sys
import zlib

OPEN = 0x4E45504F


def files(data, prefix=""):
    """{path: bytes} of every file in the archive (bytes), nested .rpf archives expanded as
    "inner.rpf/path"."""
    magic, count, names_length, encryption = struct.unpack_from("<4sIII", data, 0)
    assert magic == b"7FPR", magic
    if encryption != OPEN:
        raise ValueError(f"encrypted archive ({encryption:#x})")
    names = data[16 + 16 * count:16 + 16 * count + names_length]

    def name(offset):
        return names[offset:names.index(b"\0", offset)].decode("latin-1")

    out = {}

    def walk(index, path):
        first, = struct.unpack_from("<I", data, 16 + 16 * index + 8)
        n, = struct.unpack_from("<I", data, 16 + 16 * index + 12)
        for i in range(first, first + n):
            at = 16 + 16 * i
            head, ident = struct.unpack_from("<II", data, at)
            if ident == 0x7FFFFF00:
                walk(i, f"{path}{name(head)}/")
                continue
            bits, = struct.unpack_from("<Q", data, at)
            entry_name = name(bits & 0xFFFF)
            size = bits >> 16 & 0xFFFFFF
            resource = bool(bits >> 63)
            offset = (bits >> 40 & 0x7FFFFF) * 512
            if resource:
                if size == 0xFFFFFF:
                    header = data[offset:offset + 16]
                    size = header[7] | header[14] << 8 | header[5] << 16 | header[2] << 24
                blob = data[offset:offset + size]
            else:
                uncompressed, = struct.unpack_from("<I", data, at + 8)
                blob = data[offset:offset + (size or uncompressed)]
                if size and size != uncompressed:
                    blob = zlib.decompress(blob, -15)
            full = f"{prefix}{path}{entry_name}"
            out[full] = blob
            if entry_name.lower().endswith(".rpf"):
                out.update(files(blob, full + "/"))

    walk(0, "")
    return out


def main(argv):
    for path, blob in files(open(argv[1], "rb").read()).items():
        print(f"{len(blob):10}  {path}")


if __name__ == "__main__":
    main(sys.argv)
