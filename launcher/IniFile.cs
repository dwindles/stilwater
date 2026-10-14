using System.Text;

namespace Stilwater.Launcher;

/// <summary>
/// Line-based INI editing that keeps comments, ordering and the file's encoding (including a
/// UTF-8 BOM, which the Win32 profile APIs misread).
/// </summary>
internal sealed class IniFile
{
    private readonly List<string> _lines;
    private readonly bool _utf8Bom;

    public string Path { get; }

    public IniFile(string path)
    {
        Path = path;
        if (File.Exists(path))
        {
            var bytes = File.ReadAllBytes(path);
            _utf8Bom = bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF;
            var text = Encoding.UTF8.GetString(bytes, _utf8Bom ? 3 : 0, bytes.Length - (_utf8Bom ? 3 : 0));
            _lines = text.Replace("\r\n", "\n").Split('\n').ToList();
        }
        else
        {
            _lines = [];
        }
    }

    public string? Get(string section, string key)
    {
        var index = FindKey(section, key);
        return index < 0 ? null : _lines[index][(_lines[index].IndexOf('=') + 1)..].Trim();
    }

    public void Set(string section, string key, string value)
    {
        var index = FindKey(section, key);
        if (index >= 0)
        {
            _lines[index] = $"{key}={value}";
            return;
        }

        var (start, end) = FindSection(section);
        if (start < 0)
        {
            if (_lines.Count > 0 && _lines[^1].Length > 0) _lines.Add("");
            _lines.Add($"[{section}]");
            _lines.Add($"{key}={value}");
            return;
        }

        // Insert after the section's last non-blank line.
        var insertAt = end;
        while (insertAt > start + 1 && _lines[insertAt - 1].Trim().Length == 0) insertAt--;
        _lines.Insert(insertAt, $"{key}={value}");
    }

    public void Save()
    {
        var text = string.Join("\r\n", _lines);
        var encoding = new UTF8Encoding(encoderShouldEmitUTF8Identifier: _utf8Bom);
        File.WriteAllText(Path, text, encoding);
    }

    private (int Start, int End) FindSection(string section)
    {
        var header = $"[{section}]";
        for (var i = 0; i < _lines.Count; i++)
        {
            if (!_lines[i].Trim().Equals(header, StringComparison.OrdinalIgnoreCase)) continue;
            var end = i + 1;
            while (end < _lines.Count && !_lines[end].TrimStart().StartsWith('[')) end++;
            return (i, end);
        }
        return (-1, -1);
    }

    private int FindKey(string section, string key)
    {
        var (start, end) = FindSection(section);
        for (var i = start + 1; start >= 0 && i < end; i++)
        {
            var line = _lines[i].TrimStart();
            if (line.StartsWith(';') || line.StartsWith('#')) continue;
            var eq = line.IndexOf('=');
            if (eq > 0 && line[..eq].Trim().Equals(key, StringComparison.OrdinalIgnoreCase)) return i;
        }
        return -1;
    }
}
