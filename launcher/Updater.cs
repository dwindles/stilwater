using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Text.Json;

namespace Stilwater.Launcher;

/// <summary>
/// Updates from Stilwater's GitHub releases. Each release is a zip with the core, the launcher, the
/// mods and install.ps1 (installer/ in the repo), the same package new players run install.bat
/// from. Updating downloads it, starts its installer and closes the launcher; the installer waits
/// for that, installs, and opens the new launcher.
/// </summary>
internal static class Updater
{
    public const string Repository = "dwindles/stilwater";

    public sealed record Release(Version Version, string Tag, string ZipUrl, long Size, string Notes, DateTime Published);

    /// <summary>This launcher's version (the release's, for installed builds).</summary>
    public static Version Current { get; } = Normalize(Assembly.GetExecutingAssembly().GetName().Version ?? new Version(0, 0, 0));

    private static readonly HttpClient Http = CreateClient();
    private static Task<Release?>? _check;

    public static string UpdatesFolder => Path.Combine(Runtime.Folder, "updates");

    /// <summary>The newest release when it's newer than this launcher, otherwise null. Checked once
    /// per run; failures (offline, no releases yet) count as no update.</summary>
    public static Task<Release?> CheckAsync() => _check ??= CheckOnceAsync();

    private static async Task<Release?> CheckOnceAsync()
    {
        try
        {
            var latest = await LatestAsync();
            return latest is not null && latest.Version > Current ? latest : null;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or InvalidDataException)
        {
            return null;
        }
    }

    /// <summary>The newest published release, or null when there is none yet.</summary>
    public static async Task<Release?> LatestAsync()
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, $"https://api.github.com/repos/{Repository}/releases/latest");
        request.Headers.Accept.ParseAdd("application/vnd.github+json");
        using var reply = await Http.SendAsync(request);
        if (reply.StatusCode == System.Net.HttpStatusCode.NotFound) return null;
        reply.EnsureSuccessStatusCode();
        using var json = await JsonDocument.ParseAsync(await reply.Content.ReadAsStreamAsync());
        var tag = json.RootElement.GetProperty("tag_name").GetString() ?? "";
        if (!Version.TryParse(tag.TrimStart('v'), out var version)) throw new InvalidDataException($"Release tag {tag} isn't a version.");
        foreach (var asset in json.RootElement.GetProperty("assets").EnumerateArray())
        {
            var name = asset.GetProperty("name").GetString() ?? "";
            if (name.StartsWith("Stilwater", StringComparison.OrdinalIgnoreCase) && name.EndsWith(".zip", StringComparison.OrdinalIgnoreCase))
                return new Release(Normalize(version), tag, asset.GetProperty("browser_download_url").GetString()!, asset.GetProperty("size").GetInt64(),
                                   json.RootElement.TryGetProperty("body", out var body) ? body.GetString() ?? "" : "",
                                   json.RootElement.TryGetProperty("published_at", out var at) && at.TryGetDateTime(out var when) ? when : DateTime.MinValue);
        }
        throw new InvalidDataException($"Release {tag} has no Stilwater zip.");
    }

    /// <summary>Downloads the release and starts its installer, which waits for this launcher to
    /// exit. The caller closes the launcher afterwards.</summary>
    public static async Task StartInstallAsync(Release release, GameInstall game, IProgress<string> progress)
    {
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first: the update replaces files it uses.");
        if (Directory.Exists(UpdatesFolder)) Directory.Delete(UpdatesFolder, recursive: true);
        Directory.CreateDirectory(UpdatesFolder);

        var zip = Path.Combine(UpdatesFolder, $"Stilwater-{release.Version}.zip");
        using (var reply = await Http.GetAsync(release.ZipUrl, HttpCompletionOption.ResponseHeadersRead))
        {
            reply.EnsureSuccessStatusCode();
            await using var source = await reply.Content.ReadAsStreamAsync();
            await using var target = File.Create(zip);
            var buffer = new byte[1 << 16];
            long done = 0;
            int read;
            while ((read = await source.ReadAsync(buffer)) > 0)
            {
                await target.WriteAsync(buffer.AsMemory(0, read));
                done += read;
                progress.Report($"Downloading v{release.Version}… {done * 100 / Math.Max(1, release.Size)}%");
            }
        }

        progress.Report("Unpacking…");
        var folder = Path.Combine(UpdatesFolder, release.Tag);
        await Task.Run(() => ZipFile.ExtractToDirectory(zip, folder));
        var script = Path.Combine(folder, "install.ps1");
        if (!File.Exists(script)) throw new InvalidDataException("The update has no installer.");

        var install = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, WorkingDirectory = folder };
        foreach (var arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Game", game.Folder,
                                    "-WaitFor", Environment.ProcessId.ToString(), "-NoShortcut" })
            install.ArgumentList.Add(arg);
        Process.Start(install);
    }

    /// <summary>Removes what the last update left behind (its installer can't delete itself).</summary>
    public static void CleanUp()
    {
        try { if (Directory.Exists(UpdatesFolder)) Directory.Delete(UpdatesFolder, recursive: true); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
    }

    private static Version Normalize(Version v) => new(v.Major, v.Minor, Math.Max(0, v.Build));

    private static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
        // GitHub's API refuses requests without a User-Agent.
        client.DefaultRequestHeaders.UserAgent.ParseAdd($"StilwaterLauncher/{Current}");
        return client;
    }
}
