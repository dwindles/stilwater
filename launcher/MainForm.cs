using System.Diagnostics;

namespace Stilwater.Launcher;

public sealed class MainForm : Form
{
    private readonly GameInstall? _game = GameInstall.FindSteamInstall();
    private readonly Panel _host = new() { Dock = DockStyle.Fill };
    private readonly Panel _banner = new() { Dock = DockStyle.Top, Height = 44, BackColor = Theme.Accent, Visible = false, Padding = new Padding(28, 0, 28, 0) };
    private readonly Label _bannerText = new() { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Color.White, Font = Theme.Strong };
    private readonly Online _online;
    private readonly List<(Label Tab, Func<Control> Create)> _tabs = [];
    private int _active = -1;
    private Control? _page;

    public MainForm(int startPage = 0)
    {
        Text = "Stilwater";
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Body;
        ClientSize = new Size(720, 640);
        MinimumSize = new Size(620, 520);
        StartPosition = FormStartPosition.CenterScreen;
        // Created now that the form exists, so its events arrive on the UI thread.
        Updater.CleanUp();
        Online.Game = _game;
        _online = new Online();
        _online.Invited += ShowInvite;

        var header = new Panel { Dock = DockStyle.Top, Height = 64, Padding = new Padding(28, 0, 28, 0) };
        header.Paint += (_, e) =>
        {
            using var pen = new Pen(Theme.Divider);
            e.Graphics.DrawLine(pen, 0, header.Height - 1, header.Width, header.Height - 1);
        };

        var brand = new FlowLayoutPanel { Dock = DockStyle.Left, AutoSize = true, WrapContents = false, Padding = new Padding(0, 20, 0, 0) };
        brand.Controls.Add(new Label
        {
            Text = "Stilwater",
            Font = new Font("Segoe UI Semibold", 15f),
            AutoSize = true,
            Margin = new Padding(0, 0, 10, 0),
        });
        var maker = new LinkLabel
        {
            Text = "by holdonquietly.com",
            Font = Theme.Small,
            LinkColor = Theme.Muted,
            ActiveLinkColor = Theme.Text,
            LinkBehavior = LinkBehavior.HoverUnderline,
            AutoSize = true,
            Margin = new Padding(0, 9, 0, 0),
        };
        maker.LinkClicked += (_, _) =>
            Process.Start(new ProcessStartInfo("https://holdonquietly.com") { UseShellExecute = true });
        brand.Controls.Add(maker);

        var nav = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true, WrapContents = false, Padding = new Padding(0, 22, 0, 0) };
        AddTab(nav, "Play", () => new HomePage(_game, _online));
        AddTab(nav, "Friends", () => new FriendsPage(_online));
        AddTab(nav, "Mods", () => _game is null
            ? new Label { Text = "Saints Row 2 was not found.", ForeColor = Theme.Bad, Padding = new Padding(28) }
            : new ModsPage(_game));
        AddTab(nav, "Settings", () => _game is null
            ? new Label { Text = "Saints Row 2 was not found.", ForeColor = Theme.Bad, Padding = new Padding(28) }
            : new SettingsPage(_game));

        header.Controls.AddRange([brand, nav]);

        var join = new Button
        {
            Text = "Play", Dock = DockStyle.Right, Width = 90, FlatStyle = FlatStyle.Flat, BackColor = Color.White,
            ForeColor = Theme.Accent, Font = Theme.Strong, FlatAppearance = { BorderSize = 0 }, Cursor = Cursors.Hand,
        };
        join.Click += (_, _) => { _banner.Visible = false; ShowPage(0); };
        _banner.Controls.AddRange([_bannerText, join]);
        Controls.AddRange([_host, _banner, header]);
        SetIcon();
        ShowPage(Math.Clamp(startPage, 0, _tabs.Count - 1));
        _ = SignInSavedAsync();
    }

    public const int SettingsTab = 3;

    /// <summary>Signs in with the login the game keeps, when there is one and the game isn't
    /// already signed in with it.</summary>
    private async Task SignInSavedAsync()
    {
        if (GameLogin.Read() is not { IsComplete: true } login || GameInstall.IsRunning()) return;
        try { await _online.SignInAsync(login); }
        catch (Exception e) when (e is InvalidOperationException or IOException or System.Net.Sockets.SocketException or TimeoutException) { }
    }

    private void ShowInvite(Online.Friend friend)
    {
        _bannerText.Text = $"{friend.Name} invited you to co-op. Start the game, then join them from Co-op → Online.";
        _banner.Visible = true;
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _online.Dispose();
        base.OnFormClosed(e);
    }

    private void AddTab(FlowLayoutPanel nav, string text, Func<Control> create)
    {
        var index = _tabs.Count;
        var tab = new Label
        {
            Text = text,
            Font = Theme.Strong,
            AutoSize = true,
            Padding = new Padding(2, 0, 2, 12),
            Margin = new Padding(20, 0, 0, 0),
            Cursor = Cursors.Hand,
        };
        tab.Paint += (_, e) =>
        {
            if (index != _active) return;
            using var accent = new SolidBrush(Theme.Accent);
            e.Graphics.FillRectangle(accent, 0, tab.Height - 2, tab.Width, 2);
        };
        tab.Click += (_, _) => ShowPage(index);
        nav.Controls.Add(tab);
        _tabs.Add((tab, create));
    }

    private void ShowPage(int index)
    {
        _active = index;
        foreach (var (tab, _) in _tabs)
        {
            tab.ForeColor = tab == _tabs[index].Tab ? Theme.Text : Theme.Muted;
            tab.Invalidate();
        }

        _page?.Dispose();
        _page = _tabs[index].Create();
        _page.Dock = DockStyle.Fill;
        _host.Controls.Add(_page);
    }

    // The holdonquietly.com logo from assets\logo.png, used as the window icon.
    private void SetIcon()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "assets", "logo.png");
        if (!File.Exists(path)) return;
        using var logo = new Bitmap(path);
        Icon = Icon.FromHandle(new Bitmap(logo, 64, 64).GetHicon());
    }
}
