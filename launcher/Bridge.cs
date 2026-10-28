using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace Stilwater.Launcher;

/// <summary>
/// Connects the launcher's web UI (ui\ next to the exe; app.js) to the launcher. The page sends
/// {id, method, args} and gets {id, result} or {id, error} back; the launcher sends it events
/// {event, data}: online (friends, requests, profiles), invite, notice, progress, gameExited.
/// </summary>
internal sealed class Bridge
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private const int PictureSize = 160;

    private readonly Form _form;
    private readonly CoreWebView2 _web;
    private readonly GameInstall? _game;
    private readonly Online _online;
    private Process? _gameProcess;

    public Bridge(Form form, CoreWebView2 web, GameInstall? game, Online online)
    {
        _form = form;
        _web = web;
        _game = game;
        _online = online;
        _web.WebMessageReceived += OnMessage;
        _online.Changed += () => Emit("online", OnlineState());
        _online.Disconnected += reason => Emit("notice", $"Signed out: {reason}");
        _online.Invited += friend =>
        {
            Emit("invite", new { name = friend.Name });
            if (_form.WindowState == FormWindowState.Minimized && _gameProcess is null) _form.WindowState = FormWindowState.Normal;
            _form.Activate();
        };
    }

    /// <summary>The Play page's picture (Steam's art for the game), or null for none.</summary>
    public string? Art { get; init; }

    public void Emit(string name, object? data) => Send(new { @event = name, data });

    private void Send(object value) => _web.PostWebMessageAsJson(JsonSerializer.Serialize(value, Json));

    private async void OnMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        var id = 0;
        // Only the launcher's own page talks to the launcher (not the music player's frame).
        if (!e.Source.StartsWith("https://stilwater.app/", StringComparison.OrdinalIgnoreCase)) return;
        try
        {
            using var message = JsonDocument.Parse(e.WebMessageAsJson);
            id = message.RootElement.GetProperty("id").GetInt32();
            var result = await CallAsync(message.RootElement.GetProperty("method").GetString() ?? "", message.RootElement.GetProperty("args"));
            Send(new { id, result });
        }
        // Whatever goes wrong is shown on the page rather than closing the launcher.
        catch (Exception error)
        {
            Send(new { id, error = error.Message });
        }
    }

    private async Task<object?> CallAsync(string method, JsonElement args)
    {
        string Text(string name) => args.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
        int Id() => args.GetProperty("id").GetInt32();
        var game = _game;
        switch (method)
        {
            case "window.drag": WindowFrame.Drag(_form, Text("edge")); return null;
            case "window.minimize": _form.WindowState = FormWindowState.Minimized; return null;
            case "window.maximize":
                _form.WindowState = _form.WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
                return null;
            case "window.close": _form.Close(); return null;
            case "app.state": return State();
            case "app.update": return await Updater.CheckAsync() is { } update ? new { version = update.Version.ToString() } : null;
            case "app.release": return await LatestReleaseAsync();
            case "app.installUpdate": await InstallUpdateAsync(); return null;
            case "app.nextVersion": return await NextVersionAsync();
            case "app.upload":
                Staff.Upload(Staff.RepoFolder(game) ?? throw new InvalidOperationException("This PC has no Stilwater repo set up."), Text("version"), Text("notes"));
                return null;
            case "app.play": return Play();
            case "app.log": return ReadLog();
            case "app.openUrl": OpenUrl(Text("url")); return null;
            case "app.openFolder": OpenFolder(Text("which")); return null;

            case "online.status": return OnlineState();
            case "online.check":
                var problem = await Online.CheckAsync();
                return new { ok = problem is null, problem, server = Online.UsesOpenSpy ? "openspy.net" : Online.Server };
            case "online.ping": return await Online.PingAsync();
            case "online.savedLogin":
                var saved = GameLogin.Read();
                return new { nick = saved?.Nick ?? "", email = saved?.Email ?? "", hasPassword = !string.IsNullOrEmpty(saved?.Password) };
            case "online.signIn":
            {
                var login = Login(args);
                await _online.SignInAsync(login);
                login.Write();
                return null;
            }
            case "online.createAccount":
            {
                var login = Login(args);
                await Online.CreateAccountAsync(login);
                await _online.SignInAsync(login);
                login.Write();
                return null;
            }
            case "online.signOut": _online.SignOut(); return null;
            case "online.addFriend": await _online.AddFriendAsync(Text("nick"), "Stilwater co-op"); return null;
            case "online.accept": await _online.AcceptAsync(RequestFrom(Id())); return null;
            case "online.ignore": _online.Ignore(RequestFrom(Id())); return null;
            case "online.remove": await _online.RemoveFriendAsync(FriendFrom(Id())); return null;
            case "online.invite": await _online.InviteAsync(FriendFrom(Id())); return null;

            case "profile.pickAvatar":
            {
                using var dialog = new OpenFileDialog { Title = "Choose a profile picture", Filter = "Pictures|*.jpg;*.jpeg;*.png;*.bmp;*.gif|All files|*.*" };
                if (dialog.ShowDialog(_form) != DialogResult.OK) return false;
                await _online.SetProfileAsync(Picture(dialog.FileName), null);
                return true;
            }
            case "profile.clearAvatar": await _online.SetProfileAsync([], null); return null;
            case "profile.setBio": await _online.SetProfileAsync(null, Text("bio")); return null;

            case "mods.list":
                return new
                {
                    mods = ModList.Read(Required()).Select(m => new
                    {
                        name = m.Name, display = DisplayName(m), enabled = m.Enabled, core = m.IsCore, yours = m.IsYours,
                        files = m.Files, mb = Math.Round(m.Bytes / 1024.0 / 1024.0, 1),
                    }).ToList(),
                };
            case "mods.code": return await Task.Run(() => ModList.Code(Required()));
            case "mods.set":
                ModList.SetEnabled(Required(), Text("name"), args.GetProperty("enabled").GetBoolean());
                return null;
            case "mods.addFolder":
            {
                using var dialog = new FolderBrowserDialog { Description = "Choose the mod's folder (the one with its game files)", UseDescriptionForTitle = true };
                if (dialog.ShowDialog(_form) != DialogResult.OK) return null;
                var install = Required();
                return await Task.Run(() => ModShare.AddFolder(install, dialog.SelectedPath));
            }
            case "mods.addZip":
            {
                using var dialog = new OpenFileDialog { Title = "Choose a mod .zip", Filter = "Zip files|*.zip" };
                if (dialog.ShowDialog(_form) != DialogResult.OK) return null;
                var install = Required();
                return await Task.Run(() => ModShare.AddZip(install, dialog.FileName));
            }
            case "mods.remove":
            {
                var name = Text("name");
                var install = Required();
                if (ModList.Read(install).FirstOrDefault(m => m.Name.Equals(name, StringComparison.OrdinalIgnoreCase)) is not { IsYours: true })
                    throw new InvalidOperationException("Only mods you added can be removed here.");
                ModList.Remove(install, name);
                return null;
            }
            case "mods.share":
            {
                if (!_online.SignedIn) throw new InvalidOperationException("Sign in to share mods.");
                var (code, skipped) = await ModShare.ShareAsync(Required(), _online.LoginTicket, ModProgress());
                return new { code, skipped };
            }
            case "mods.lookUp":
            {
                _share = await ModShare.LookUpAsync(Text("code"));
                return new
                {
                    code = _share.Code, by = _share.By,
                    mods = _share.Mods.Select(m => new { name = m.Name, files = m.Files.Count, mb = Math.Round(m.Files.Sum(f => f.Size) / 1024.0 / 1024.0, 1) }),
                };
            }
            case "mods.install":
            {
                if (_share is null || !_share.Code.Equals(Text("code"), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Look the code up first.");
                return await ModShare.InstallAsync(Required(), _share, ModProgress());
            }

            case "settings.list": return SettingsList();
            case "settings.save": SaveSettings(args.GetProperty("values")); return null;
            case "settings.action": return SetUpSteam();
        }
        throw new InvalidOperationException($"Unknown request {method}.");
    }

    // The mod code looked up last, which mods.install installs.
    private ModShare.Share? _share;

    private Progress<string> ModProgress() => new(text => Emit("modsProgress", text));

    private GameInstall Required() => _game ?? throw new InvalidOperationException("Saints Row 2 wasn't found. Install Stilwater with install.bat.");

    // --- Play page

    private object State()
    {
        var checks = new List<object>();
        string? problem = null;
        var canPlay = false;
        if (_game is null)
        {
            checks.Add(Check(false, "Saints Row 2", "Not found: install Stilwater with install.bat"));
            problem = "Saints Row 2 wasn't found. Install Stilwater with install.bat.";
        }
        else
        {
            var exe = _game.GetExeKind();
            var runtime = File.Exists(Runtime.Dll) && File.Exists(Runtime.Loader);
            var juiced = Directory.Exists(Path.Combine(_game.Folder, "mods")) &&
                         Directory.GetDirectories(Path.Combine(_game.Folder, "mods"), "JUICED - *").Length > 0;
            checks.Add(Check(true, "Game", _game.Folder));
            checks.Add(Check(exe == ExeKind.Unencrypted, "Executable", exe switch
            {
                ExeKind.Unencrypted => _game.IsLargeAddressAware() ? "Unencrypted, 4 GB aware" : "Unencrypted",
                ExeKind.SteamEncrypted => "Steam's encrypted build: run install.bat",
                _ => "Missing",
            }));
            checks.Add(Check(_game.HasJuiced(), "Stilwater core", _game.HasJuiced() ? "Installed" : "Not installed: run install.bat"));
            checks.Add(Check(juiced, "Juiced Patch", juiced ? "Mods present" : "Missing: run install.bat"));
            checks.Add(Check(runtime, "Runtime", runtime ? "Ready" : "stilwater.dll or stilwater-loader.exe missing"));
            checks.Add(Check(true, "DXVK", _game.HasDxvk() ? "Installed" : "Not used (DirectX 9)"));
            canPlay = exe == ExeKind.Unencrypted && runtime;
            if (!canPlay) problem = exe != ExeKind.Unencrypted ? "SR2_pc.exe isn't ready yet: run install.bat." : "The Stilwater runtime is missing: run install.bat.";
        }
        return new { version = Updater.Current.ToString(), staff = Staff.RepoFolder(_game) is not null, canPlay, problem, serviceName = Online.ServiceName, art = Art, checks };
    }

    private static object Check(bool ok, string name, string detail) => new { ok, name, detail };

    private object Play()
    {
        var game = Required();
        if (GameInstall.IsRunning()) return new { ok = false, message = "Saints Row 2 is already running." };
        // Stilwater Online keeps the launcher signed in beside the game (the in-game menu uses it for
        // friends and invites); OpenSpy has one session per account, which the game takes.
        var wasSignedIn = _online.SignedIn && Online.UsesOpenSpy;
        if (wasSignedIn) _online.SignOut();
        var result = Runtime.Launch(game);
        if (!result.Ok) return new { ok = false, message = result.Message };

        _form.WindowState = FormWindowState.Minimized;
        _gameProcess = Process.GetProcessById(result.ProcessId);
        _gameProcess.EnableRaisingEvents = true;
        _gameProcess.Exited += (_, _) => _form.BeginInvoke(async () =>
        {
            _gameProcess?.Dispose();
            _gameProcess = null;
            _form.WindowState = FormWindowState.Normal;
            Emit("gameExited", null);
            if (wasSignedIn && GameLogin.Read() is { IsComplete: true } login)
            {
                try { await _online.SignInAsync(login); }
                catch (Exception e) when (e is InvalidOperationException or IOException or System.Net.Sockets.SocketException or TimeoutException) { }
            }
        });
        return new { ok = true, message = "Saints Row 2 is running." };
    }

    private static string ReadLog()
    {
        if (!File.Exists(Runtime.Log)) return "";
        using var stream = new FileStream(Runtime.Log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        stream.Position = Math.Max(0, stream.Length - 40_000);
        return new StreamReader(stream).ReadToEnd();
    }

    private static async Task<object?> LatestReleaseAsync()
    {
        try
        {
            return await Updater.LatestAsync() is { } release
                ? new
                {
                    version = release.Tag,
                    date = release.Published == DateTime.MinValue ? "" : release.Published.ToLocalTime().ToString("MMMM d, yyyy", CultureInfo.InvariantCulture),
                    notes = release.Notes,
                }
                : null;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or InvalidDataException) { return null; }
    }

    private async Task InstallUpdateAsync()
    {
        var release = await Updater.CheckAsync() ?? throw new InvalidOperationException("You have the newest version.");
        await Updater.StartInstallAsync(release, Required(), new Progress<string>(text => Emit("progress", text)));
        Application.Exit();
    }

    private static async Task<string> NextVersionAsync()
    {
        Updater.Release? latest = null;
        try { latest = await Updater.LatestAsync(); }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException or InvalidDataException) { }
        // One past the newest release; the first release takes the launcher's own version.
        return (latest is null ? Updater.Current : new Version(latest.Version.Major, latest.Version.Minor, latest.Version.Build + 1)).ToString();
    }

    private static void OpenUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps) throw new ArgumentException("That isn't a web address.");
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private void OpenFolder(string which)
    {
        var folder = which switch
        {
            "mods" => Path.Combine(Required().Folder, "mods"),
            "game" => Required().Folder,
            _ => Path.Combine(Runtime.Folder, "logs"),
        };
        Directory.CreateDirectory(folder);
        Process.Start(new ProcessStartInfo(folder) { UseShellExecute = true });
    }

    // --- Friends

    private object OnlineState()
    {
        string? PictureOf(int id) => _online.ProfileOf(id)?.Picture is { } p ? DataUrl(p) : null;
        return new
        {
            signedIn = _online.SignedIn,
            nick = _online.Nick,
            profileId = _online.ProfileId,
            bio = _online.ProfileOf(_online.ProfileId)?.Bio ?? "",
            avatar = PictureOf(_online.ProfileId),
            friends = _online.Friends.Select(f => new
            {
                id = f.ProfileId, name = f.Name, activity = f.Activity, avatar = PictureOf(f.ProfileId),
                status = f.Status switch { Online.Status.Playing => "playing", Online.Status.Online => "online", _ => "offline" },
            }).ToList(),
            requests = _online.Requests.Select(r => new { id = r.ProfileId, name = r.Name, avatar = PictureOf(r.ProfileId) }).ToList(),
        };
    }

    private static string DataUrl(byte[] image) =>
        $"data:{(image.Length > 0 && image[0] == 0x89 ? "image/png" : "image/jpeg")};base64,{Convert.ToBase64String(image)}";

    private Online.Request RequestFrom(int id) =>
        _online.Requests.FirstOrDefault(r => r.ProfileId == id) ?? throw new InvalidOperationException("That request is gone.");

    private Online.Friend FriendFrom(int id) =>
        _online.Friends.FirstOrDefault(f => f.ProfileId == id) ?? throw new InvalidOperationException("That player isn't on your friends list.");

    private static GameLogin Login(JsonElement args)
    {
        string Text(string name) => args.TryGetProperty(name, out var v) ? (v.GetString() ?? "").Trim() : "";
        var saved = GameLogin.Read();
        var password = args.TryGetProperty("password", out var p) ? p.GetString() ?? "" : "";
        var login = new GameLogin(Text("nick"), Text("email"), password.Length > 0 ? password : saved?.Password ?? "",
                                  saved?.LanName is { Length: > 0 } lan ? lan : Text("nick"));
        if (!login.IsComplete) throw new ArgumentException("Enter your nick, email and password.");
        return login;
    }

    /// <summary>The picture at path, cropped square from its centre, as a 160 x 160 JPEG.</summary>
    private static byte[] Picture(string path)
    {
        Image source;
        try { source = Image.FromFile(path); }
        catch (Exception e) when (e is OutOfMemoryException or ArgumentException) { throw new ArgumentException("That file isn't a picture."); }
        using (source)
        {
            var side = Math.Min(source.Width, source.Height);
            using var bitmap = new Bitmap(PictureSize, PictureSize);
            using (var g = Graphics.FromImage(bitmap))
            {
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.DrawImage(source, new Rectangle(0, 0, PictureSize, PictureSize),
                            new Rectangle((source.Width - side) / 2, (source.Height - side) / 2, side, side), GraphicsUnit.Pixel);
            }
            var jpeg = ImageCodecInfo.GetImageEncoders().First(c => c.FormatID == ImageFormat.Jpeg.Guid);
            using var quality = new EncoderParameters(1);
            quality.Param[0] = new EncoderParameter(System.Drawing.Imaging.Encoder.Quality, 88L);
            using var output = new MemoryStream();
            bitmap.Save(output, jpeg, quality);
            return output.ToArray();
        }
    }

    // --- Mods

    private static string DisplayName(ModList.Mod mod) =>
        mod.Name.StartsWith("STILWATER - ", StringComparison.OrdinalIgnoreCase) ? mod.Name[12..]
        : mod.IsCore ? mod.Name[9..] : mod.Name;

    // --- Settings

    private object SettingsList()
    {
        var game = Required();
        var ini = new IniFile(game.JuicedIni);
        var sections = GameSettings.Juiced.Concat(Tuning.Settings).GroupBy(s => s.Group)
            .Select(g => (object)new { title = g.Key, items = g.Select(s => Item(s, ini.Get(s.Section, s.Key) ?? s.Default)).ToList() })
            .ToList();
        sections.Add(new { title = "Controls", items = new[] { Choice("controls.layout", "Layout", "Controller and keyboard/mouse. Close the game first.", ControllerLayouts.Choices) } });
        var look = new List<object>();
        if (ReShadeLook.IsInstalled(game)) look.Add(Choice("look.reshade", "ReShade look", "Press F2 in game to fine-tune.", ReShadeLook.Choices));
        look.Add(new { id = "look.fps", label = "FPS counter", help = "", kind = "toggle", value = game.FpsCounterEnabled ? "1" : "0" });
        sections.Add(new { title = "Look", items = look });
        sections.Add(new
        {
            title = "Steam",
            items = new[]
            {
                new
                {
                    id = "steam.setup", label = "Play button opens Stilwater", kind = "button", value = "Set up",
                    help = SteamPlay.IsSetUp() ? "Set up: Steam's Play opens this launcher." : "Steam's Play starts the game without Stilwater.",
                },
            },
        });
        return new { sections };
    }

    private static object Item(Setting s, string value)
    {
        var id = $"{s.Section}.{s.Key}";
        return s.Kind switch
        {
            SettingKind.Toggle => new { id, label = s.Label, help = s.Help, kind = "toggle", value = value.Trim() == "1" ? "1" : "0" },
            SettingKind.Number => (object)new
            {
                id, label = s.Label, help = s.Help, kind = "number", min = s.Min, max = s.Max, step = s.Step, decimals = s.Decimals,
                value = (double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? Math.Clamp(d, s.Min, s.Max)
                         : double.Parse(s.Default, CultureInfo.InvariantCulture)).ToString("0.######", CultureInfo.InvariantCulture),
            },
            SettingKind.Choice => Choice(id, s.Label, s.Help, s.Choices!, value.Trim()),
            _ => new { id, label = s.Label, help = s.Help, kind = "text", value },
        };
    }

    private static object Choice(string id, string label, string help, (string Value, string Text)[] choices, string? value = null) => new
    {
        id, label, help, kind = "choice", value = value ?? choices[0].Value,
        choices = choices.Select(c => new { value = c.Value, text = c.Text }).ToList(),
    };

    private void SaveSettings(JsonElement values)
    {
        var game = Required();
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first. It rewrites these files while running.");
        var ini = new IniFile(game.JuicedIni);
        var settings = GameSettings.Juiced.Concat(Tuning.Settings).ToDictionary(s => $"{s.Section}.{s.Key}");
        foreach (var change in values.EnumerateObject())
        {
            var value = change.Value.GetString() ?? "";
            if (settings.TryGetValue(change.Name, out var setting)) ini.Set(setting.Section, setting.Key, Format(setting, value));
            else if (change.Name == "controls.layout" && value != ControllerLayouts.Choices[0].Value) ControllerLayouts.Apply(value);
            else if (change.Name == "look.reshade" && value != ReShadeLook.Keep) ReShadeLook.Apply(game, value);
            else if (change.Name == "look.fps") game.SetFpsCounter(value == "1");
        }
        ini.Save();
        Tuning.Apply(game);
    }

    private static string Format(Setting setting, string value) => setting.Kind switch
    {
        SettingKind.Toggle => value == "1" ? "1" : "0",
        SettingKind.Number when double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) =>
            setting.Decimals > 0 ? d.ToString("0.000000", CultureInfo.InvariantCulture) : ((int)Math.Round(d)).ToString(CultureInfo.InvariantCulture),
        _ => value.Trim(),
    };

    private static string SetUpSteam()
    {
        if (SteamPlay.SteamRunning)
        {
            Clipboard.SetText(SteamPlay.LaunchOptions);
            return "Copied. In Steam: Saints Row 2 → Properties → Launch Options, and paste. (Or close Steam and press Set up.)";
        }
        return SteamPlay.SetUp() > 0 ? "Done: Steam's Play button now opens Stilwater." : "Play Saints Row 2 from Steam once, then try again.";
    }
}
