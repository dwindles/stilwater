"""Saints Row 2 packfile (.vpp_pc / .str2_pc, version 4) reader.

Layout: a 0x180-byte header, then 0x1C-byte entries, then file names, then extensions, then
data. Each block starts on a 2048-byte boundary. Data is stored raw, zlib-compressed per file,
or (when also "condensed") as a single zlib stream over all files.

    python vpp.py list <packfile> [substring]
    python vpp.py extract <packfile> <substring> <out_dir>
"""
import mmap
import struct
import sys
import zlib
from pathlib import Path

COMPRESSED, CONDENSED = 0x01, 0x02


def _align(value, alignment=2048):
    return (value + alignment - 1) // alignment * alignment


def _cstring(data, offset):
    return data[offset:data.find(b"\0", offset)].decode("latin-1")


class Packfile:
    def __init__(self, path):
        self.path = Path(path)
        # Mapped rather than read: meshes.vpp_pc and the chunk packfiles are over a gigabyte.
        with open(self.path, "rb") as f:
            self.data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        d = self.data
        magic, version = struct.unpack_from("<II", d, 0)
        if version != 4:
            raise ValueError(f"{path}: packfile version {version}, expected 4")
        self.flags, = struct.unpack_from("<I", d, 0x14C)
        count, _, index_size, names_size, ext_size = struct.unpack_from("<5I", d, 0x154)

        index_at = _align(0x180)
        names_at = _align(index_at + index_size)
        ext_at = _align(names_at + names_size)
        self.data_at = _align(ext_at + ext_size)

        self.entries = []
        for i in range(count):
            name_off, ext_off, _, start, size, csize, _ = struct.unpack_from("<7I", d, index_at + i * 0x1C)
            name = _cstring(d, names_at + name_off) + "." + _cstring(d, ext_at + ext_off)
            self.entries.append((name, start, size, csize))
        self._condensed = None

    def read(self, name):
        for entry_name, start, size, csize in self.entries:
            if entry_name.lower() == name.lower():
                return self._read(start, size, csize)
        raise KeyError(name)

    def _read(self, start, size, csize):
        if not self.flags & COMPRESSED:
            return self.data[self.data_at + start:self.data_at + start + size]
        if self.flags & CONDENSED:
            if self._condensed is None:
                self._condensed = zlib.decompressobj().decompress(self.data[self.data_at:])
            return self._condensed[start:start + size]
        return zlib.decompress(self.data[self.data_at + start:self.data_at + start + csize])[:size]


def main(argv):
    command, path = argv[1], argv[2]
    pack = Packfile(path)
    needle = argv[3].lower() if len(argv) > 3 else ""
    matches = [e for e in pack.entries if needle in e[0].lower()]
    if command == "list":
        print(f"{pack.path.name}: {len(pack.entries)} files, flags {pack.flags:#x}")
        for name, _, size, csize in matches:
            print(f"  {size:>10}  {name}".encode("ascii", "replace").decode())
    elif command == "extract":
        out = Path(argv[4])
        out.mkdir(parents=True, exist_ok=True)
        for name, start, size, csize in matches:
            (out / name).write_bytes(pack._read(start, size, csize))
            print(f"extracted {name} ({size} bytes)")


if __name__ == "__main__":
    main(sys.argv)
