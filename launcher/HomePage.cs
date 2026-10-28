using System.Diagnostics;

namespace Stilwater.Launcher;

/// <summary>Setup status, the Play button and the runtime log.</summary>
internal sealed class HomePage : UserControl
{
    private readonly GameInstall? _game;
    private readonly Online _online;
    private readonly TableLayoutPanel _checks = new();
    private readonly Button _play = Theme.PrimaryButton("Play");
    private readonly Button _update = Theme.PrimaryButton("Update");
    private readonly Button _upload = new()
    {
        Text = "Upload", Size = new Size(90, 40), Margin = new Padding(8, 0, 0, 0), FlatStyle = FlatStyle.Flat, BackColor = Theme.Input,
        ForeColor = Theme.Text, Font = Theme.Strong, FlatAppearance = { BorderSize = 0 }, Cursor = Cursors.Hand,
    };
    private Updater.Release? _release;
    private readonly Label _status = new();
    private readonly TextBox _log = new();
    private readonly System.Windows.Forms.Timer _logTimer = new() { Interval = 1000 };
    private Process? _gameProcess;

    public HomePage(GameInstall? game, Online online)
    {
        _game = game;
        _online = online;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Body;
        Padding = new Padding(28, 20, 28, 20);

        var top = new TableLayoutPanel { Dock = DockStyle.Top, Height = 52, ColumnCount = 3, RowCount = 1 };
        top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        _play.Size = new Size(140, 40);
        _play.Margin = new Padding(0, 0, 16, 0);
        _play.Click += (_, _) => Play();
        _status.ForeColor = Theme.Muted;
        _status.Dock = DockStyle.Fill;
        _status.Margin = Padding.Empty;
        _status.TextAlign = ContentAlignment.MiddleLeft;
        // Update appears when a newer release is out; Upload only on a staff machine (Staff.cs).
        var actions = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = Padding.Empty };
        _update.Visible = false;
        _update.Size = new Size(150, 40);
        _update.Click += async (_, _) => await UpdateAsync();
        _upload.Visible = Staff.RepoFolder(game) is not null;
        _upload.Click += async (_, _) => await UploadAsync();
        actions.Controls.AddRange([_update, _upload]);
        top.Controls.Add(_play, 0, 0);
        top.Controls.Add(_status, 1, 0);
        top.Controls.Add(actions, 2, 0);

        _checks.Dock = DockStyle.Top;
        _checks.AutoSize = true;
        _checks.ColumnCount = 2;
        _checks.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        _checks.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        _checks.Padding = new Padding(0, 4, 0, 12);

        var logLabel = new Label { Text = "Runtime log", Font = Theme.Strong, ForeColor = Theme.Muted, Dock = DockStyle.Top, Height = 28 };
        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.BackColor = Theme.Panel;
        _log.ForeColor = Theme.Muted;
        _log.BorderStyle = BorderStyle.None;
        _log.Font = new Font("Consolas", 8.75f);
        _log.Dock = DockStyle.Fill;

        // Docked controls lay out in reverse order of addition.
        Controls.AddRange([_log, logLabel, _checks, top]);
        _logTimer.Tick += (_, _) => RefreshLog();
        RefreshChecks();
        _log.Text = "No log yet. Play starts the game with the Stilwater runtime, which logs here.";
        RefreshLog();
        _ = ShowUpdateAsync();
    }

    private async Task ShowUpdateAsync()
    {
        _release = await Updater.CheckAsync();
        if (_release is null || IsDisposed || _game is null) return;
        _update.Text = $"Update to {_release.Version}";
        _update.Width = TextRenderer.MeasureText(_update.Text, Theme.Strong).Width + 36;
        _update.Visible = true;
    }

    private async Task UpdateAsync()
    {
        if (_release is null || _game is null) return;
        var ask = $"Update Stilwater to {_release.Version}? The launcher closes, installs the update and opens again.";
        if (MessageBox.Show(FindForm(), ask, "Update", MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return;
        _update.Enabled = _play.Enabled = false;
        _status.ForeColor = Theme.Muted;
        try
        {
            await Updater.StartInstallAsync(_release, _game, new Progress<string>(text => _status.Text = text));
            Application.Exit();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException or UnauthorizedAccessException
                                      or InvalidOperationException or InvalidDataException or System.ComponentModel.Win32Exception)
        {
            _status.Text = $"Update failed: {e.Message}";
            _status.ForeColor = Theme.Bad;
            _update.Enabled = true;
            RefreshChecks();
        }
    }

    private async Task UploadAsync()
    {
        if (Staff.RepoFolder(_game) is not { } repo) return;
        Updater.Release? latest = null;
        try { latest = await Updater.LatestAsync(); }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException or InvalidDataException) { }
        // One past the newest release; the first release takes the launcher's own version.
        var suggested = latest is null ? Updater.Current : new Version(latest.Version.Major, latest.Version.Minor, latest.Version.Build + 1);
        Staff.Upload(FindForm()!, repo, suggested);
    }

    private void RefreshChecks()
    {
        _checks.Controls.Clear();
        if (_game is null)
        {
            AddCheck(false, "Saints Row 2", "not found in your Steam libraries");
            _play.Enabled = false;
            return;
        }

        var exe = _game.GetExeKind();
        AddCheck(true, "Game", _game.Folder);
        AddCheck(exe == ExeKind.Unencrypted, "Executable", exe switch
        {
            ExeKind.Unencrypted => "unencrypted build",
            ExeKind.SteamEncrypted => "Steam's encrypted build, needs the core's exe patch",
            _ => "missing",
        });
        AddCheck(_game.IsLargeAddressAware(), "4 GB memory patch", _game.IsLargeAddressAware() ? "applied" : "not applied");
        AddCheck(_game.HasJuiced(), "Stilwater core", _game.HasJuiced() ? "installed" : "not installed");
        AddCheck(_game.HasDxvk(), "DXVK", _game.HasDxvk() ? "installed" : "not installed");
        var runtime = File.Exists(Runtime.Dll) && File.Exists(Runtime.Loader);
        AddCheck(runtime, "Runtime", runtime ? "ready" : "stilwater.dll or stilwater-loader.exe missing");
        _play.Enabled = exe == ExeKind.Unencrypted;
    }

    private void AddCheck(bool ok, string name, string detail)
    {
        var dot = new Label { Text = "●", ForeColor = ok ? Theme.Good : Theme.Bad, Font = Theme.Small, AutoSize = true, Margin = new Padding(0, 6, 8, 0) };
        var text = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 3, 0, 3) };
        text.Controls.Add(new Label { Text = name, AutoSize = true, Margin = new Padding(0, 0, 8, 0) });
        text.Controls.Add(new Label { Text = detail, ForeColor = Theme.Muted, AutoSize = true, Margin = Padding.Empty });
        _checks.Controls.Add(dot);
        _checks.Controls.Add(text);
    }

    private void Play()
    {
        if (_game is null) return;
        _play.Enabled = false;
        _status.Text = "Starting…";
        _status.ForeColor = Theme.Muted;
        // An account has one session at a time, and the game signs in with the same one.
        var wasSignedIn = _online.SignedIn;
        if (wasSignedIn) _online.SignOut();
        var result = Runtime.Launch(_game);
        _status.Text = result.Message;
        _status.ForeColor = result.Ok ? Theme.Muted : Theme.Bad;
        if (!result.Ok)
        {
            _play.Enabled = true;
            return;
        }

        var form = FindForm();
        if (form is not null) form.WindowState = FormWindowState.Minimized;

        _gameProcess = Process.GetProcessById(result.ProcessId);
        _gameProcess.EnableRaisingEvents = true;
        _gameProcess.Exited += (_, _) => BeginInvoke(async () =>
        {
            _status.Text = "Saints Row 2 closed.";
            _play.Enabled = true;
            RefreshLog();
            _logTimer.Stop();
            if (form is not null) form.WindowState = FormWindowState.Normal;
            if (wasSignedIn && GameLogin.Read() is { IsComplete: true } login)
            {
                try { await _online.SignInAsync(login); }
                catch (Exception e) when (e is InvalidOperationException or IOException or System.Net.Sockets.SocketException or TimeoutException) { }
            }
        });
        _logTimer.Start();
    }

    private void RefreshLog()
    {
        if (!File.Exists(Runtime.Log)) return;
        using var stream = new FileStream(Runtime.Log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        var text = new StreamReader(stream).ReadToEnd();
        if (text == _log.Text) return;
        _log.Text = text;
        _log.SelectionStart = _log.TextLength;
        _log.ScrollToCaret();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _logTimer.Dispose();
            _gameProcess?.Dispose();
        }
        base.Dispose(disposing);
    }
}
