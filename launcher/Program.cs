namespace Stilwater.Launcher;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        // --play launches straight away without the window, for shortcuts and testing.
        // The outcome is written to logs\launcher.log.
        if (args.Contains("--play", StringComparer.OrdinalIgnoreCase))
            return PlayHeadless();
        // --setup-steam makes Steam's Play button open this launcher (the installer runs it with Steam
        // closed). Exit code: Steam accounts set up, or -1 when Steam is running or the files can't be written.
        if (args.Contains("--setup-steam", StringComparer.OrdinalIgnoreCase))
        {
            try { return SteamPlay.SetUp(); }
            catch (Exception e) when (e is InvalidOperationException or IOException or UnauthorizedAccessException) { return -1; }
        }

        ApplicationConfiguration.Initialize();
        // --page play|friends|mods|settings (or --settings) opens straight onto that page. Steam's Play
        // button (launch options "launcher" %command%) passes the game's own command line, which the
        // launcher doesn't need.
        var page = args.Contains("--settings", StringComparer.OrdinalIgnoreCase) ? MainForm.SettingsTab : 0;
        var at = Array.FindIndex(args, a => a.Equals("--page", StringComparison.OrdinalIgnoreCase));
        if (at >= 0 && at + 1 < args.Length)
            page = Math.Max(0, Array.IndexOf(["play", "friends", "mods", "settings"], args[at + 1].ToLowerInvariant()));
        Application.Run(new MainForm(page));
        return 0;
    }

    private static int PlayHeadless()
    {
        var game = GameInstall.FindSteamInstall();
        var result = game is null
            ? new Runtime.LaunchResult(false, 0, "Saints Row 2 was not found in any Steam library.")
            : Runtime.Launch(game);

        var log = Path.Combine(Runtime.Folder, "logs", "launcher.log");
        Directory.CreateDirectory(Path.GetDirectoryName(log)!);
        File.WriteAllText(log, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {(result.Ok ? "OK" : "FAILED")}: {result.Message}{Environment.NewLine}");
        return result.Ok ? 0 : 1;
    }
}
