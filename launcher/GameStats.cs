using System.Text.Json;
using System.Text.RegularExpressions;

namespace Stilwater.Launcher;

/// <summary>
/// The Play page's "Your game": time played (the launcher notes each session from Play to the game
/// closing, in logs\playtime.json) and the game's recent crash reports (Juiced writes one to
/// Juiced\CrashDumps for each crash, a .log with the address and a .dmp).
/// </summary>
internal static class GameStats
{
    private static string File_ => Path.Combine(Runtime.Folder, "logs", "playtime.json");

    private sealed record Totals(double Minutes, int Sessions, DateTime? Last);

    private static Totals Read()
    {
        try { return JsonSerializer.Deserialize<Totals>(File.ReadAllText(File_)) ?? new(0, 0, null); }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException) { return new(0, 0, null); }
    }

    /// <summary>A session that ran from <paramref name="started"/> until now.</summary>
    public static void AddSession(DateTime started)
    {
        var minutes = (DateTime.Now - started).TotalMinutes;
        if (minutes < 0.5) return;   // the game closed straight away
        var totals = Read();
        Directory.CreateDirectory(Path.GetDirectoryName(File_)!);
        File.WriteAllText(File_, JsonSerializer.Serialize(new Totals(totals.Minutes + minutes, totals.Sessions + 1, DateTime.Now)));
    }

    public static string CrashFolder(GameInstall game) => Path.Combine(game.Folder, "Juiced", "CrashDumps");

    private static readonly Regex Where = new(@"Unhandled exception at (0x[0-9A-Fa-f]+)[^:]*: (0x[0-9A-Fa-f]+): ([^\r\n.]+)");

    public static object State(GameInstall? game)
    {
        var totals = Read();
        var crashes = new List<object>();
        if (game is not null && Directory.Exists(CrashFolder(game)))
            foreach (var log in new DirectoryInfo(CrashFolder(game)).GetFiles("*.log").OrderByDescending(f => f.LastWriteTime).Take(3))
            {
                string where = "", what = "";
                try
                {
                    var match = Where.Match(File.ReadAllText(log.FullName));
                    if (match.Success) { where = match.Groups[1].Value; what = match.Groups[3].Value.Trim(); }
                }
                catch (IOException) { }
                crashes.Add(new { name = log.Name, when = log.LastWriteTime.ToString("MMM d, h:mm tt"), where, what });
            }
        return new
        {
            hours = Math.Round(totals.Minutes / 60, 1),
            sessions = totals.Sessions,
            last = totals.Last?.ToString("MMM d, h:mm tt"),
            crashes,
        };
    }

    /// <summary>A crash report's text, for sending to someone who can read it.</summary>
    public static string Crash(GameInstall game, string name)
    {
        var path = Path.Combine(CrashFolder(game), Path.GetFileName(name));
        if (!path.EndsWith(".log", StringComparison.OrdinalIgnoreCase) || !File.Exists(path))
            throw new FileNotFoundException("That crash report is gone.");
        var lines = File.ReadAllLines(path);
        return string.Join(Environment.NewLine, lines.Take(60));
    }
}
