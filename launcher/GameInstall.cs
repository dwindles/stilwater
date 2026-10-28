using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace Stilwater.Launcher;

public enum ExeKind { Missing, SteamEncrypted, Unencrypted }

/// <summary>A Saints Row 2 install and the state of the pieces Stilwater depends on.</summary>
public sealed record GameInstall(string Folder)
{
    public const int SteamAppId = 9480;

    public string Exe => Path.Combine(Folder, "SR2_pc.exe");
    public string JuicedIni => Path.Combine(Folder, "juiced.ini");
    public string DxvkConf => Path.Combine(Folder, "dxvk.conf");

    public static bool IsRunning() =>
        System.Diagnostics.Process.GetProcessesByName("SR2_pc").Length > 0 ||
        System.Diagnostics.Process.GetProcessesByName("SR2MP").Length > 0;

    public bool FpsCounterEnabled =>
        File.Exists(DxvkConf) && File.ReadAllLines(DxvkConf).Any(l => l.TrimStart().StartsWith("dxvk.hud") && l.Contains("fps"));

    public void SetFpsCounter(bool enabled) => File.WriteAllLines(DxvkConf,
    [
        "# On-screen FPS counter and frame-time graph (Stilwater launcher setting).",
        enabled ? "dxvk.hud = fps,frametimes" : "# dxvk.hud = fps,frametimes",
    ]);

    /// <summary>The game this launcher belongs to: the folder above it when it's installed in
    /// &lt;game&gt;\Stilwater\ (any copy of the game, from Steam or not), otherwise Steam's install.</summary>
    public static GameInstall? Find()
    {
        var parent = Directory.GetParent(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar))?.FullName;
        return parent is not null && File.Exists(Path.Combine(parent, "SR2_pc.exe")) ? new GameInstall(parent) : FindSteamInstall();
    }

    public static GameInstall? FindSteamInstall()
    {
        var steam = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamPath", null) as string;
        if (steam is null) return null;

        var libraries = new List<string> { steam };
        var vdf = Path.Combine(steam, "steamapps", "libraryfolders.vdf");
        if (File.Exists(vdf))
        {
            foreach (Match m in Regex.Matches(File.ReadAllText(vdf), "\"path\"\\s+\"([^\"]+)\""))
                libraries.Add(m.Groups[1].Value.Replace(@"\\", @"\"));
        }

        foreach (var library in libraries.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var manifest = Path.Combine(library, "steamapps", $"appmanifest_{SteamAppId}.acf");
            if (!File.Exists(manifest)) continue;
            var dir = Regex.Match(File.ReadAllText(manifest), "\"installdir\"\\s+\"([^\"]+)\"");
            if (!dir.Success) continue;
            var folder = Path.Combine(library, "steamapps", "common", dir.Groups[1].Value);
            if (Directory.Exists(folder)) return new GameInstall(Path.GetFullPath(folder));
        }
        return null;
    }

    /// <summary>Saints Row 2's library art (library_hero.jpg) in Steam's cache, when this PC's Steam
    /// has shown the game: in librarycache\9480\ (or a subfolder) on newer Steam, as
    /// 9480_library_hero.jpg on older.</summary>
    public static string? SteamHeroArt()
    {
        if (Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamPath", null) is not string steam) return null;
        var cache = Path.Combine(steam, "appcache", "librarycache");
        var folder = Path.Combine(cache, SteamAppId.ToString());
        try
        {
            var art = Directory.Exists(folder) ? Directory.EnumerateFiles(folder, "library_hero.jpg", SearchOption.AllDirectories).FirstOrDefault() : null;
            art ??= Path.Combine(cache, $"{SteamAppId}_library_hero.jpg");
            return File.Exists(art) ? Path.GetFullPath(art) : null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }

    public ExeKind GetExeKind()
    {
        if (!File.Exists(Exe)) return ExeKind.Missing;
        // Steam's DRM wrapper adds a ".bind" section and encrypts .text on disk.
        return Pe.Read(Exe).Sections.Contains(".bind") ? ExeKind.SteamEncrypted : ExeKind.Unencrypted;
    }

    public bool IsLargeAddressAware() => File.Exists(Exe) && Pe.Read(Exe).LargeAddressAware;

    public bool HasJuiced() =>
        File.Exists(Path.Combine(Folder, "juiced.ini")) &&
        File.Exists(Path.Combine(Folder, "DFEngine.dll")) &&
        new FileInfo(Path.Combine(Folder, "DFEngine.dll")).Length > 1_000_000; // stock DFEngine.dll is ~660 KB

    public bool HasDxvk() =>
        File.Exists(Path.Combine(Folder, "d3d9.dll")) && File.Exists(Path.Combine(Folder, "dxgi.dll"));
}

/// <summary>Just enough PE header parsing to inspect the game executable.</summary>
internal sealed record Pe(bool LargeAddressAware, HashSet<string> Sections)
{
    public static Pe Read(string path)
    {
        using var reader = new BinaryReader(File.OpenRead(path));
        reader.BaseStream.Position = 0x3C;
        var peOffset = reader.ReadInt32();
        reader.BaseStream.Position = peOffset + 6;
        var sectionCount = reader.ReadUInt16();
        reader.BaseStream.Position = peOffset + 20;
        var optionalHeaderSize = reader.ReadUInt16();
        var characteristics = reader.ReadUInt16();

        var sections = new HashSet<string>();
        reader.BaseStream.Position = peOffset + 24 + optionalHeaderSize;
        for (var i = 0; i < sectionCount; i++)
        {
            var name = System.Text.Encoding.ASCII.GetString(reader.ReadBytes(8)).TrimEnd('\0');
            sections.Add(name);
            reader.BaseStream.Position += 32;
        }
        return new Pe((characteristics & 0x20) != 0, sections);
    }
}
