using System.Diagnostics;
using System.Text.RegularExpressions;

namespace Stilwater.Launcher;

/// <summary>
/// The staff Upload button: publishes a release with tools\release.ps1 from the repo checkout that
/// [Stilwater] RepoFolder in juiced.ini names (it builds, commits, pushes and creates the GitHub
/// release players update from). Players don't have a checkout, so they don't see the button.
/// </summary>
internal static class Staff
{
    /// <summary>The repo checkout to publish from, or null on a player's machine.</summary>
    public static string? RepoFolder(GameInstall? game)
    {
        if (game is null) return null;
        var folder = new IniFile(game.JuicedIni).Get("Stilwater", "RepoFolder")?.Trim();
        return !string.IsNullOrEmpty(folder) && File.Exists(Path.Combine(folder, "tools", "release.ps1")) ? folder : null;
    }

    /// <summary>Runs the release script in its own window, which stays open to show how it went.</summary>
    public static void Upload(string repo, string version, string notes)
    {
        if (!Regex.IsMatch(version, @"^\d+\.\d+\.\d+$")) throw new ArgumentException("The version needs three numbers, like 0.2.1.");
        var start = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, WorkingDirectory = repo };
        foreach (var arg in new[] { "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(repo, "tools", "release.ps1"),
                                    "-Version", version, "-Notes", notes })
            start.ArgumentList.Add(arg);
        Process.Start(start);
    }
}
