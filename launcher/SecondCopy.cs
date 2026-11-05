namespace Stilwater.Launcher;

/// <summary>
/// More copies of the game on this PC (core Stilwater/SecondCopy.cpp), to try co-op past two
/// players with one friend or none: started with --second-copy, --third-copy or --fourth-copy, each
/// keeps its saves, controls and settings.dat (with its own sign-in) in "Second copy" (and so on)
/// under the game's save folder.
/// </summary>
internal static class SecondCopy
{
    private static readonly string[] Folders = ["", "", "Second copy", "Third copy", "Fourth copy"];

    /// <summary>The command line switch for each copy, 2 to 4.</summary>
    public static readonly string[] Switches = ["--second-copy", "--third-copy", "--fourth-copy"];

    public static string Folder(int copy) => Path.Combine(GameLogin.Folder, Folders[copy]);

    /// <summary>The copy to start next while the game runs: the first of 2 to 4 that isn't running,
    /// or null when all are. Running copies are in the core's shared memory (Local\StilwaterCopies4:
    /// an address, then per copy a process id and 16 ports, 36 bytes).</summary>
    public static int? Next()
    {
        try
        {
            using var shared = System.IO.MemoryMappedFiles.MemoryMappedFile.OpenExisting(@"Local\StilwaterCopies4",
                System.IO.MemoryMappedFiles.MemoryMappedFileRights.Read);
            using var view = shared.CreateViewAccessor(0, 4 + 4 * 36, System.IO.MemoryMappedFiles.MemoryMappedFileAccess.Read);
            for (var copy = 2; copy <= 4; copy++)
                if (!Running(view.ReadInt32(4 + (copy - 1) * 36)))
                    return copy;
            return null;
        }
        catch (FileNotFoundException) { return 2; }
    }

    private static bool Running(int pid)
    {
        if (pid == 0) return false;
        try
        {
            using var process = System.Diagnostics.Process.GetProcessById(pid);
            return !process.HasExited && process.ProcessName.StartsWith("SR2", StringComparison.OrdinalIgnoreCase);
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception) { return false; }
    }

    /// <summary>The first time: the first copy's saves, profile, controls and settings, signed out,
    /// so the copy's Co-op → Online asks for its own account.</summary>
    public static void Prepare(int copy)
    {
        var folder = Folder(copy);
        if (Directory.Exists(folder)) return;
        if (!Directory.Exists(GameLogin.Folder))
            throw new InvalidOperationException("Start Saints Row 2 once first, so it has a save folder to copy.");
        Directory.CreateDirectory(folder);
        foreach (var file in Directory.GetFiles(GameLogin.Folder))
            File.Copy(file, Path.Combine(folder, Path.GetFileName(file)));
        var login = GameLogin.Read();
        new GameLogin("", "", "", login?.LanName ?? "").Write(folder);
    }
}
