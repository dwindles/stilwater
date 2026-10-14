using System.IO.Compression;
using System.Text;

namespace Stilwater.Launcher;

/// <summary>
/// Reads Saints Row 2 packfiles (.vpp_pc, version 4): a 0x180-byte header, 0x1C-byte entries, file names,
/// extensions, then data, each block on a 2048-byte boundary. Data is raw, zlib per file, or (when also
/// "condensed") one zlib stream over all files. See tools/sr2/vpp.py.
/// </summary>
internal sealed class Packfile
{
    private const uint Compressed = 0x01, Condensed = 0x02;

    private readonly string _path;
    private readonly uint _flags;
    private readonly long _dataAt;
    private readonly Dictionary<string, (uint Start, uint Size, uint CompressedSize)> _entries =
        new(StringComparer.OrdinalIgnoreCase);

    public Packfile(string path)
    {
        _path = path;
        using var file = File.OpenRead(path);
        var header = new byte[0x180];
        file.ReadExactly(header);
        if (BitConverter.ToUInt32(header, 4) != 4) throw new InvalidDataException($"{path} is not a version 4 packfile.");
        _flags = BitConverter.ToUInt32(header, 0x14C);
        var count = BitConverter.ToUInt32(header, 0x154);
        var indexSize = BitConverter.ToUInt32(header, 0x15C);
        var namesSize = BitConverter.ToUInt32(header, 0x160);
        var extensionsSize = BitConverter.ToUInt32(header, 0x164);

        long indexAt = Align(0x180), namesAt = Align(indexAt + indexSize), extensionsAt = Align(namesAt + namesSize);
        _dataAt = Align(extensionsAt + extensionsSize);

        var index = ReadAt(file, indexAt, (int)indexSize);
        var names = ReadAt(file, namesAt, (int)namesSize);
        var extensions = ReadAt(file, extensionsAt, (int)extensionsSize);
        for (var i = 0; i < count; i++)
        {
            var e = i * 0x1C;
            var name = CString(names, BitConverter.ToInt32(index, e)) + "." + CString(extensions, BitConverter.ToInt32(index, e + 4));
            _entries[name] = (BitConverter.ToUInt32(index, e + 12), BitConverter.ToUInt32(index, e + 16), BitConverter.ToUInt32(index, e + 20));
        }
    }

    public bool Contains(string name) => _entries.ContainsKey(name);

    public byte[] Read(string name)
    {
        var (start, size, compressedSize) = _entries[name];
        using var file = File.OpenRead(_path);
        if ((_flags & Compressed) == 0) return ReadAt(file, _dataAt + start, (int)size);

        var result = new byte[size];
        if ((_flags & Condensed) != 0)
        {
            // One stream over every file: decompress up to the end of this one.
            file.Seek(_dataAt, SeekOrigin.Begin);
            using var all = new ZLibStream(file, CompressionMode.Decompress);
            all.ReadExactly(new byte[start]);
            all.ReadExactly(result);
            return result;
        }

        using var compressed = new MemoryStream(ReadAt(file, _dataAt + start, (int)compressedSize));
        using var zlib = new ZLibStream(compressed, CompressionMode.Decompress);
        zlib.ReadExactly(result);
        return result;
    }

    private static long Align(long value) => (value + 2047) / 2048 * 2048;

    private static byte[] ReadAt(FileStream file, long offset, int length)
    {
        var buffer = new byte[length];
        file.Seek(offset, SeekOrigin.Begin);
        file.ReadExactly(buffer);
        return buffer;
    }

    private static string CString(byte[] data, int offset)
    {
        var end = Array.IndexOf(data, (byte)0, offset);
        return Encoding.Latin1.GetString(data, offset, (end < 0 ? data.Length : end) - offset);
    }
}
