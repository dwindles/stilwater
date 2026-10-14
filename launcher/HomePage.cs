using System.Diagnostics;

namespace Stilwater.Launcher;

/// <summary>Setup status, the Play button and the runtime log.</summary>
internal sealed class HomePage : UserControl
{
    private readonly GameInstall? _game;
    private readonly TableLayoutPanel _checks = new();
    private readonly Button _play = Theme.PrimaryButton("Play");
    private readonly Label _status = new();
    private readonly TextBox _log = new();
    private readonly System.Windows.Forms.Timer _logTimer = new() { Interval = 1000 };
    private Process? _gameProcess;

    public HomePage(GameInstall? game)
    {
        _game = game;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Body;
        Padding = new Padding(28, 20, 28, 20);

        var top = new Panel { Dock = DockStyle.Top, Height = 52 };
        _play.Size = new Size(140, 40);
        _play.Location = new Point(0, 0);
        _play.Click += (_, _) => Play();
        _status.ForeColor = Theme.Muted;
        _status.Location = new Point(156, 0);
        _status.Size = new Size(500, 40);
        _status.TextAlign = ContentAlignment.MiddleLeft;
        _status.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        top.Controls.AddRange([_play, _status]);

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
        var result = Runtime.Launch(_game);
        _status.Text = result.Message;
        _status.ForeColor = result.Ok ? Theme.Muted : Theme.Bad;
        if (!result.Ok)
        {
            _play.Enabled = true;
            return;
        }

        _gameProcess = Process.GetProcessById(result.ProcessId);
        _gameProcess.EnableRaisingEvents = true;
        _gameProcess.Exited += (_, _) => BeginInvoke(() =>
        {
            _status.Text = "Saints Row 2 closed.";
            _play.Enabled = true;
            RefreshLog();
            _logTimer.Stop();
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
