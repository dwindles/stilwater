using System.Security.Cryptography;
using System.Text;

namespace Stilwater.Launcher;

/// <summary>The game's loose mods: folders in mods\ that loose.txt lists as "mods/name" ("#mods/name"
/// keeps one switched off). The core loads them in that order, and the first copy of a file wins.</summary>
internal static class ModList
{
    public sealed record Mod(string Name, bool Enabled, long Bytes, int Files)
    {
        public bool IsCore => Name.StartsWith("JUICED - ", StringComparison.OrdinalIgnoreCase);
    }

    private static string LooseTxt(GameInstall game) => Path.Combine(game.Folder, "loose.txt");
    private static string ModsFolder(GameInstall game) => Path.Combine(game.Folder, "mods");

    public static IReadOnlyList<Mod> Read(GameInstall game)
    {
        var lines = File.Exists(LooseTxt(game)) ? File.ReadAllLines(LooseTxt(game)) : [];
        var enabled = lines.Where(l => l.StartsWith("mods/", StringComparison.OrdinalIgnoreCase))
                           .Select(l => l[5..]).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!Directory.Exists(ModsFolder(game))) return [];
        return Directory.GetDirectories(ModsFolder(game))
            .Select(dir =>
            {
                var files = Directory.GetFiles(dir, "*", SearchOption.AllDirectories);
                var name = Path.GetFileName(dir);
                return new Mod(name, enabled.Contains(name), files.Sum(f => new FileInfo(f).Length), files.Length);
            })
            .OrderBy(m => m.IsCore ? 0 : 1).ThenBy(m => m.Name, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public static void SetEnabled(GameInstall game, string name, bool enabled)
    {
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first. It reads mods while running.");
        var entry = $"mods/{name}";
        var lines = (File.Exists(LooseTxt(game)) ? File.ReadAllLines(LooseTxt(game)) : ["mods"]).Where(l => l.Length > 0).ToList();
        var at = lines.FindIndex(l => l.TrimStart('#').Equals(entry, StringComparison.OrdinalIgnoreCase));
        var line = enabled ? entry : "#" + entry;
        if (at >= 0) lines[at] = line;
        else lines.Add(line);
        // CRLF with a trailing newline, as the loader and tools\install-mods.ps1 expect.
        File.WriteAllText(LooseTxt(game), string.Join("\r\n", lines) + "\r\n", Encoding.ASCII);
    }

    /// <summary>A short fingerprint of the switched-on mods' files. Co-op partners with different
    /// codes run different weapons, cars or tables, which can desync or crash a session.</summary>
    public static string Code(GameInstall game)
    {
        using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        foreach (var mod in Read(game).Where(m => m.Enabled))
        {
            var dir = Path.Combine(ModsFolder(game), mod.Name);
            foreach (var file in Directory.GetFiles(dir, "*", SearchOption.AllDirectories).Order(StringComparer.OrdinalIgnoreCase))
            {
                sha.AppendData(Encoding.UTF8.GetBytes(Path.GetRelativePath(ModsFolder(game), file).ToLowerInvariant()));
                sha.AppendData(File.ReadAllBytes(file));
            }
        }
        var hex = Convert.ToHexString(sha.GetHashAndReset());
        return $"{hex[..4]}-{hex[4..8]}";
    }
}
