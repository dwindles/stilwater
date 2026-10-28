"""Saints Row 2 string tables (.le_strings).

Layout: u32 magic 0xA84C7F73, u16 version (1), u16 bucket count, u32 string count; per bucket a u32
string count and the u32 file offset of its run in the index; the index (a u32 file offset per
string, grouped by bucket); then the records: a big-endian u32 key hash and a null-terminated
UTF-16BE string. A string's bucket is hash & (bucket count - 1).

The key hash is the game's string hash of the key name (e.g. CUST_ITEM_MEN'S_TIGHT_JEANS): CRC-32
of the lowercased name without the usual inversions (key_hash).

    python strings.py list <file.le_strings> [substring]
"""
import struct
import sys
import zlib

MAGIC = 0xA84C7F73


def key_hash(name):
    """The game's hash of a string key (CRC-32 table at 0xE843B8, starting from 0, lowercased)."""
    return zlib.crc32(name.lower().encode(), 0xFFFFFFFF) ^ 0xFFFFFFFF


def read(data):
    """[(hash, text)] in file order."""
    magic, _, buckets, _ = struct.unpack_from("<IHHI", data, 0)
    if magic != MAGIC:
        raise ValueError("not a string table")
    result = []
    for b in range(buckets):
        count, slot = struct.unpack_from("<II", data, 0x0C + b * 8)
        for k in range(count):
            record, = struct.unpack_from("<I", data, slot + 4 * k)
            key, = struct.unpack_from(">I", data, record)
            end = record + 4
            while data[end:end + 2] != b"\0\0":
                end += 2
            result.append((key, data[record + 4:end].decode("utf-16-be")))
    return result


def write(strings, buckets=32):
    """A string table holding strings ({hash: text}); buckets must be a power of two."""
    grouped = [[] for _ in range(buckets)]
    for key, text in strings.items():
        grouped[key & (buckets - 1)].append((key, text))

    index_at = 0x0C + buckets * 8
    records_at = index_at + 4 * len(strings)
    table, index, records = bytearray(), bytearray(), bytearray()
    for entries in grouped:
        table += struct.pack("<II", len(entries), index_at + len(index))
        for key, text in entries:
            index += struct.pack("<I", records_at + len(records))
            records += struct.pack(">I", key) + text.encode("utf-16-be") + b"\0\0"
    return struct.pack("<IHHI", MAGIC, 1, buckets, len(strings)) + table + index + records


def main(argv):
    command, path = argv[1], argv[2]
    needle = argv[3].lower() if len(argv) > 3 else ""
    if command == "list":
        with open(path, "rb") as f:
            for key, text in read(f.read()):
                if needle in text.lower():
                    print(f"{key:#010x}  {text}".encode("ascii", "replace").decode())


if __name__ == "__main__":
    main(sys.argv)
