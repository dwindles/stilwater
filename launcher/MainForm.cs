using System.Diagnostics;

namespace Stilwater.Launcher;

public sealed class MainForm : Form
{
    private static readonly Color Background = Color.FromArgb(18, 16, 24);
    private static readonly Color Panel = Color.FromArgb(30, 27, 40);
    private static readonly Color TextColor = Color.FromArgb(232, 228, 240);
    private static readonly Color Muted = Color.FromArgb(150, 143, 168);
    private static readonly Color Purple = Color.FromArgb(124, 58, 237);
    private static readonly Color Good = Color.FromArgb(74, 222, 128);
    private static readonly Color Bad = Color.FromArgb(248, 113, 113);

    private readonly GameInstall? _game = GameInstall.FindSteamInstall();
    private readonly FlowLayoutPanel _checks = new();
    private readonly Button _play = new();
    private readonly Label _status = new();
    private readonly TextBox _log = new();
    private readonly System.Windows.Forms.Timer _logTimer = new() { Interval = 1000 };
    private Process? _gameProcess;

    public MainForm()
    {
        Text = "Stilwater";
        BackColor = Background;
        ForeColor = TextColor;
        Font = new Font("Segoe UI", 10f);
        ClientSize = new Size(720, 560);
        MinimumSize = new Size(600, 480);
        StartPosition = FormStartPosition.CenterScreen;

        var title = new Label
        {
            Text = "STILWATER",
            Font = new Font("Segoe UI", 26f, FontStyle.Bold),
            ForeColor = Purple,
            AutoSize = true,
            Location = new Point(24, 18),
        };
        var subtitle = new Label
        {
            Text = "Saints Row 2 custom client",
            ForeColor = Muted,
            AutoSize = true,
            Location = new Point(28, 66),
        };

        _checks.FlowDirection = FlowDirection.TopDown;
        _checks.WrapContents = false;
        _checks.BackColor = Panel;
        _checks.Padding = new Padding(14, 10, 14, 10);
        _checks.Location = new Point(24, 100);
        _checks.Size = new Size(672, 170);
        _checks.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;

        _play.Text = "PLAY";
        _play.Font = new Font("Segoe UI", 14f, FontStyle.Bold);
        _play.ForeColor = Color.White;
        _play.BackColor = Purple;
        _play.FlatStyle = FlatStyle.Flat;
        _play.FlatAppearance.BorderSize = 0;
        _play.Size = new Size(180, 52);
        _play.Location = new Point(24, 286);
        _play.Cursor = Cursors.Hand;
        _play.Click += (_, _) => Play();

        _status.ForeColor = Muted;
        _status.AutoSize = false;
        _status.Location = new Point(220, 286);
        _status.Size = new Size(476, 52);
        _status.TextAlign = ContentAlignment.MiddleLeft;
        _status.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;

        _log.Multiline = true;
        _log.ReadOnly = true;
        _log.ScrollBars = ScrollBars.Vertical;
        _log.BackColor = Panel;
        _log.ForeColor = TextColor;
        _log.BorderStyle = BorderStyle.None;
        _log.Font = new Font("Consolas", 9f);
        _log.Location = new Point(24, 354);
        _log.Size = new Size(672, 182);
        _log.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;

        Controls.AddRange([title, subtitle, _checks, _play, _status, _log]);
        _logTimer.Tick += (_, _) => RefreshLog();
        RefreshChecks();
    }

    private void RefreshChecks()
    {
        _checks.Controls.Clear();
        if (_game is null)
        {
            AddCheck(false, "Saints Row 2 not found in your Steam libraries");
            _play.Enabled = false;
            return;
        }

        var exe = _game.GetExeKind();
        AddCheck(true, $"Game folder: {_game.Folder}");
        AddCheck(exe == ExeKind.Unencrypted, exe switch
        {
            ExeKind.Unencrypted => "SR2_pc.exe: unencrypted build",
            ExeKind.SteamEncrypted => "SR2_pc.exe: Steam's encrypted build (Juiced needs to patch it)",
            _ => "SR2_pc.exe: missing",
        });
        AddCheck(_game.IsLargeAddressAware(), "4 GB memory patch (LAA)");
        AddCheck(_game.HasJuiced(), "Juiced Patch installed");
        AddCheck(_game.HasDxvk(), "DXVK installed");
        AddCheck(File.Exists(Runtime.Dll) && File.Exists(Runtime.Loader), "Stilwater runtime ready");
        _play.Enabled = exe == ExeKind.Unencrypted;
    }

    private void AddCheck(bool ok, string text) =>
        _checks.Controls.Add(new Label
        {
            Text = $"{(ok ? "✔" : "✖")}  {text}",
            ForeColor = ok ? Good : Bad,
            AutoSize = true,
            Margin = new Padding(0, 3, 0, 3),
        });

    private void Play()
    {
        if (_game is null) return;
        _play.Enabled = false;
        _status.Text = "Starting…";
        var result = Runtime.Launch(_game);
        _status.Text = result.Message;
        _status.ForeColor = result.Ok ? Good : Bad;
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
            _status.ForeColor = Muted;
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

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _logTimer.Dispose();
        _gameProcess?.Dispose();
        base.OnFormClosed(e);
    }
}
