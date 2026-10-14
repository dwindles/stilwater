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

        ApplicationConfiguration.Initialize();
        // --settings opens straight onto the Settings page.
        Application.Run(new MainForm(args.Contains("--settings", StringComparer.OrdinalIgnoreCase) ? 1 : 0));
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
