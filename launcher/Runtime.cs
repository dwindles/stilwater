using System.Diagnostics;

namespace Stilwater.Launcher;

/// <summary>Starts the game with the Stilwater runtime loaded, via the 32-bit stilwater-loader.</summary>
public static class Runtime
{
    public static string Folder => AppContext.BaseDirectory;
    public static string Dll => Path.Combine(Folder, "stilwater.dll");
    public static string Loader => Path.Combine(Folder, "stilwater-loader.exe");
    public static string Log => Path.Combine(Folder, "logs", "runtime.log");

    public sealed record LaunchResult(bool Ok, int ProcessId, string Message);

    public static LaunchResult Launch(GameInstall game)
    {
        if (!File.Exists(Loader) || !File.Exists(Dll))
            return new(false, 0, "stilwater-loader.exe or stilwater.dll is missing next to the launcher.");
        if (game.GetExeKind() != ExeKind.Unencrypted)
            return new(false, 0, "SR2_pc.exe is still Steam's encrypted build. Install Juiced Patch and let it patch the exe first.");

        var start = new ProcessStartInfo(Loader)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add(game.Exe);
        start.ArgumentList.Add(Dll);

        using var loader = Process.Start(start)!;
        var stdout = loader.StandardOutput.ReadToEnd();
        var stderr = loader.StandardError.ReadToEnd();
        loader.WaitForExit();

        return loader.ExitCode == 0 && int.TryParse(stdout.Trim(), out var pid)
            ? new(true, pid, $"Saints Row 2 started (PID {pid}) with the Stilwater runtime.")
            : new(false, 0, $"Launch failed (loader exit code {loader.ExitCode}): {stderr.Trim()}");
    }
}
