using System.Diagnostics;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace Stilwater.Launcher;

/// <summary>
/// Makes Steam's Play button for Saints Row 2 open the launcher, through the game's launch options
/// ("launcher" %command%). Steam keeps them per account in userdata\&lt;id&gt;\config\localconfig.vdf,
/// under apps\9480\LaunchOptions, and rewrites that file when it exits, so it can only be changed
/// while Steam is closed; otherwise the user pastes the line into the game's Properties.
/// </summary>
internal static class SteamPlay
{
    public static string LaunchOptions => $"\"{Environment.ProcessPath}\" %command%";

    public static bool SteamRunning => Process.GetProcessesByName("steam").Length > 0;

    private static IEnumerable<string> ConfigFiles()
    {
        var steam = Registry.GetValue(@"HKEY_CURRENT_USER\Software\Valve\Steam", "SteamPath", null) as string;
        if (steam is null) yield break;
        var userdata = Path.Combine(steam, "userdata");
        if (!Directory.Exists(userdata)) yield break;
        foreach (var user in Directory.GetDirectories(userdata))
        {
            var file = Path.Combine(user, "config", "localconfig.vdf");
            if (File.Exists(file)) yield return file;
        }
    }

    /// <summary>Whether every Steam account on this PC opens the launcher from Play.</summary>
    public static bool IsSetUp() =>
        ConfigFiles().Any() && ConfigFiles().All(f => CurrentOptions(File.ReadAllText(f)) == LaunchOptions);

    /// <summary>Writes the launch options (Steam must be closed).</summary>
    public static int SetUp()
    {
        if (SteamRunning) throw new InvalidOperationException("Close Steam first: it rewrites its settings when it exits.");
        var count = 0;
        foreach (var file in ConfigFiles())
        {
            var text = File.ReadAllText(file);
            var updated = WithOptions(text, LaunchOptions);
            if (updated is null) continue;
            File.Copy(file, file + ".stilwater.bak", overwrite: true);
            File.WriteAllText(file, updated);
            count++;
        }
        return count;
    }

    /// <summary>The block of app 9480 under "apps" (its braces' offsets), if the account has one.</summary>
    private static (int Open, int Close)? AppBlock(string text)
    {
        var apps = Regex.Match(text, "\"apps\"\\s*\\{", RegexOptions.IgnoreCase);
        if (!apps.Success || Closing(text, apps.Index + apps.Length - 1) is not { } appsEnd) return null;
        var app = new Regex($"\"{GameInstall.SteamAppId}\"\\s*\\{{").Match(text, apps.Index + apps.Length);
        if (!app.Success || app.Index > appsEnd) return null;
        var open = app.Index + app.Length - 1;
        return Closing(text, open) is { } close ? (open, close) : null;
    }

    private static int? Closing(string text, int open)
    {
        var depth = 0;
        for (var i = open; i < text.Length; i++)
        {
            if (text[i] == '{') depth++;
            else if (text[i] == '}' && --depth == 0) return i;
        }
        return null;
    }

    private static string? CurrentOptions(string text)
    {
        if (AppBlock(text) is not { } block) return null;
        var m = Regex.Match(text[block.Open..block.Close], "\"LaunchOptions\"\\s*\"((?:[^\"\\\\]|\\\\.)*)\"");
        return m.Success ? m.Groups[1].Value.Replace("\\\"", "\"").Replace("\\\\", "\\") : null;
    }

    private static string? WithOptions(string text, string options)
    {
        var escaped = options.Replace("\\", "\\\\").Replace("\"", "\\\"");
        if (AppBlock(text) is not { } block)
        {
            // An account that hasn't played SR2 yet has no block for it: add one to "apps".
            var apps = Regex.Match(text, "\"apps\"\\s*\\{", RegexOptions.IgnoreCase);
            if (!apps.Success) return null;
            var at = apps.Index + apps.Length;
            return text[..at] + $"\n\t\t\t\t\t\"{GameInstall.SteamAppId}\"\n\t\t\t\t\t{{\n\t\t\t\t\t\t\"LaunchOptions\"\t\t\"{escaped}\"\n\t\t\t\t\t}}" + text[at..];
        }
        var inside = text[(block.Open + 1)..block.Close];
        var m = Regex.Match(inside, "(\"LaunchOptions\"\\s*\")((?:[^\"\\\\]|\\\\.)*)\"");
        inside = m.Success
            ? inside[..m.Index] + m.Groups[1].Value + escaped + "\"" + inside[(m.Index + m.Length)..]
            : $"\n\t\t\t\t\t\t\"LaunchOptions\"\t\t\"{escaped}\"" + inside;
        return text[..(block.Open + 1)] + inside + text[block.Close..];
    }
}
