using System.IO.Compression;
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Stilwater.Launcher;

/// <summary>The player's own mods (ModList.Mod.IsYours): adding them from a folder or a .zip, and
/// sharing them with a code through Stilwater Online (server/mods.py). Files are sent and fetched
/// by their SHA-256, so only what the other side lacks moves. Only the game's own kinds of files
/// are shared, never programs.</summary>
internal static partial class ModShare
{
    private const string Api = "https://holdonquietly.com/stilwater/mods/";
    private const long MaxFile = 200L * 1024 * 1024;
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromMinutes(30) };

    // The same kinds of file server/mods.py takes.
    [GeneratedRegex(@"\.([a-z0-9_]+_pc|xtbl|lua|le_strings|cxt|xwb|xsb|xgs|vint_doc|vint_proj|txt|dat|png|jpg)$", RegexOptions.IgnoreCase)]
    private static partial Regex GameFile();
    [GeneratedRegex(@"^[A-Za-z0-9 _.,'()&+\-\[\]]{1,120}$")]
    private static partial Regex SafeSegment();

    public sealed record SharedFile(string Path, string Sha256, long Size);
    public sealed record SharedMod(string Name, bool Enabled, List<SharedFile> Files);
    public sealed record Share(string Code, string By, List<SharedMod> Mods);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    // --- adding

    /// <summary>Copies a mod folder into the game's mods and switches it on. Returns its name.</summary>
    public static string AddFolder(GameInstall game, string source)
    {
        var name = FreeName(game, ModList.CleanName(Path.GetFileName(source.TrimEnd('\\', '/'))));
        var target = Path.Combine(ModList.ModsFolder(game), name);
        var copied = 0;
        foreach (var file in Directory.GetFiles(source, "*", SearchOption.AllDirectories))
        {
            var to = Path.Combine(target, Path.GetRelativePath(source, file));
            Directory.CreateDirectory(Path.GetDirectoryName(to)!);
            File.Copy(file, to);
            copied++;
        }
        if (copied == 0) throw new InvalidOperationException("That folder is empty.");
        ModList.Add(game, name, true);
        return name;
    }

    /// <summary>Unpacks a mod .zip into the game's mods and switches it on. A zip holding one folder
    /// is that mod; otherwise the mod is named after the zip.</summary>
    public static string AddZip(GameInstall game, string zipPath)
    {
        using var zip = ZipFile.OpenRead(zipPath);
        var entries = zip.Entries.Where(e => e.Name.Length > 0).ToList();
        if (entries.Count == 0) throw new InvalidOperationException("That zip is empty.");
        var tops = entries.Select(e => e.FullName.Replace('\\', '/').Split('/')[0]).Distinct().ToList();
        var oneFolder = tops.Count == 1 && entries.All(e => e.FullName.Replace('\\', '/').Contains('/'));
        var name = FreeName(game, ModList.CleanName(oneFolder ? tops[0] : Path.GetFileNameWithoutExtension(zipPath)));
        var target = Path.GetFullPath(Path.Combine(ModList.ModsFolder(game), name)) + Path.DirectorySeparatorChar;
        foreach (var entry in entries)
        {
            var inside = entry.FullName.Replace('\\', '/');
            if (oneFolder) inside = inside[(inside.IndexOf('/') + 1)..];
            var to = Path.GetFullPath(Path.Combine(target, inside));
            // A zip can name paths outside the folder ("../"); those are skipped.
            if (!to.StartsWith(target, StringComparison.OrdinalIgnoreCase)) continue;
            Directory.CreateDirectory(Path.GetDirectoryName(to)!);
            entry.ExtractToFile(to);
        }
        ModList.Add(game, name, true);
        return name;
    }

    private static string FreeName(GameInstall game, string name)
    {
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first. It reads mods while running.");
        var candidate = name;
        for (var i = 2; Directory.Exists(Path.Combine(ModList.ModsFolder(game), candidate)); i++) candidate = $"{name} ({i})";
        return candidate;
    }

    // --- sharing

    /// <summary>Uploads the player's switched-on mods (only files the server doesn't have) and returns
    /// their code, and the files left out because they aren't game files.</summary>
    public static async Task<(string Code, List<string> Skipped)> ShareAsync(GameInstall game, string ticket, IProgress<string> progress)
    {
        if (string.IsNullOrEmpty(ticket)) throw new InvalidOperationException("Sign in to share mods.");
        var mine = ModList.Read(game).Where(m => m.IsYours && m.Enabled).ToList();
        if (mine.Count == 0) throw new InvalidOperationException("Switch on at least one of your mods to share.");
        var mods = new List<SharedMod>();
        var local = new Dictionary<string, string>();
        var skipped = new List<string>();
        foreach (var mod in mine)
        {
            progress.Report($"Reading {mod.Name}…");
            var folder = Path.Combine(ModList.ModsFolder(game), mod.Name);
            var files = new List<SharedFile>();
            foreach (var file in Directory.GetFiles(folder, "*", SearchOption.AllDirectories).Order(StringComparer.OrdinalIgnoreCase))
            {
                var path = Path.GetRelativePath(folder, file).Replace('\\', '/');
                var size = new FileInfo(file).Length;
                if (!GameFile().IsMatch(path) || !path.Split('/').All(SafeSegment().IsMatch) || size > MaxFile)
                {
                    skipped.Add($"{mod.Name}/{path}");
                    continue;
                }
                var hash = await HashAsync(file);
                local[hash] = file;
                files.Add(new SharedFile(path, hash, size));
            }
            if (files.Count > 0) mods.Add(new SharedMod(mod.Name, true, files));
        }
        if (mods.Count == 0) throw new InvalidOperationException("Your mods have no game files to share.");

        var missing = await PostAsync<MissingReply>("missing", new { hashes = local.Keys }, ticket);
        var done = 0;
        foreach (var hash in missing.Missing)
        {
            progress.Report($"Uploading {++done} of {missing.Missing.Count}…");
            await using var stream = File.OpenRead(local[hash]);
            using var request = new HttpRequestMessage(HttpMethod.Put, Api + "blob/" + hash) { Content = new StreamContent(stream) };
            request.Headers.Add("X-Stilwater-Ticket", ticket);
            await CheckAsync(await Http.SendAsync(request));
        }
        progress.Report("Making the code…");
        var share = await PostAsync<CodeReply>("share", new { mods }, ticket);
        return (share.Code, skipped);
    }

    /// <summary>What a code holds, without installing anything.</summary>
    public static async Task<Share> LookUpAsync(string code)
    {
        code = Regex.Replace(code.Trim().ToUpperInvariant(), "[^A-Z0-9-]", "");
        if (code.Length < 8) throw new InvalidOperationException("Enter a mod code like SW-ABCD-EFGH.");
        using var response = await Http.GetAsync(Api + "share/" + Uri.EscapeDataString(code));
        await CheckAsync(response);
        return await response.Content.ReadFromJsonAsync<Share>(Json) ?? throw new InvalidOperationException("That code couldn't be read.");
    }

    /// <summary>Downloads a code's mods (files checked against their hashes) and installs them, each
    /// switched on or off as shared. A mod with the same name is replaced; the old one goes to the
    /// Recycle Bin.</summary>
    public static async Task<int> InstallAsync(GameInstall game, Share share, IProgress<string> progress)
    {
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first. It reads mods while running.");
        var cache = Path.Combine(Runtime.Folder, "cache", "mods");
        Directory.CreateDirectory(cache);
        var hashes = share.Mods.SelectMany(m => m.Files).Select(f => f.Sha256).Distinct().ToList();
        var done = 0;
        foreach (var hash in hashes)
        {
            if (!Regex.IsMatch(hash, "^[0-9a-f]{64}$")) throw new InvalidOperationException("That code's list is damaged.");
            var file = Path.Combine(cache, hash);
            progress.Report($"Downloading {++done} of {hashes.Count}…");
            if (File.Exists(file) && await HashAsync(file) == hash) continue;
            using (var response = await Http.GetAsync(Api + "file/" + hash, HttpCompletionOption.ResponseHeadersRead))
            {
                await CheckAsync(response);
                await using var output = File.Create(file + ".part");
                await response.Content.CopyToAsync(output);
            }
            if (await HashAsync(file + ".part") != hash)
            {
                File.Delete(file + ".part");
                throw new InvalidOperationException("A file arrived damaged. Try again.");
            }
            File.Move(file + ".part", file, true);
        }

        foreach (var mod in share.Mods)
        {
            progress.Report($"Installing {mod.Name}…");
            var name = ModList.CleanName(mod.Name);
            var root = Path.GetFullPath(Path.Combine(ModList.ModsFolder(game), name)) + Path.DirectorySeparatorChar;
            if (Directory.Exists(root)) ModList.Remove(game, name);
            foreach (var f in mod.Files)
            {
                var to = Path.GetFullPath(Path.Combine(root, f.Path.Replace('/', Path.DirectorySeparatorChar)));
                if (!to.StartsWith(root, StringComparison.OrdinalIgnoreCase) || !GameFile().IsMatch(to)) continue;
                Directory.CreateDirectory(Path.GetDirectoryName(to)!);
                File.Copy(Path.Combine(cache, f.Sha256), to, true);
            }
            ModList.Add(game, name, mod.Enabled);
        }
        return share.Mods.Count;
    }

    // --- HTTP

    private sealed record MissingReply(List<string> Missing);
    private sealed record CodeReply(string Code);
    private sealed record ErrorReply(string? Error);

    private static async Task<T> PostAsync<T>(string path, object body, string ticket)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, Api + path) { Content = JsonContent.Create(body, options: Json) };
        request.Headers.Add("X-Stilwater-Ticket", ticket);
        using var response = await Http.SendAsync(request);
        await CheckAsync(response);
        return await response.Content.ReadFromJsonAsync<T>(Json) ?? throw new InvalidOperationException("The server's reply couldn't be read.");
    }

    private static async Task CheckAsync(HttpResponseMessage response)
    {
        if (response.IsSuccessStatusCode) return;
        string? text = null;
        try { text = (await response.Content.ReadFromJsonAsync<ErrorReply>(Json))?.Error; }
        catch (Exception e) when (e is JsonException or NotSupportedException) { }
        throw new InvalidOperationException(text ?? (response.StatusCode == HttpStatusCode.NotFound
            ? "That isn't on the server." : $"The server said {(int)response.StatusCode}. Try again later."));
    }

    private static async Task<string> HashAsync(string file)
    {
        await using var stream = File.OpenRead(file);
        return Convert.ToHexString(await SHA256.HashDataAsync(stream)).ToLowerInvariant();
    }
}
