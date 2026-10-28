using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Stilwater.Launcher;

/// <summary>The launcher window: the web UI in ui\ (index.html, app.css, app.js) shown with WebView2
/// and connected to the launcher through Bridge.</summary>
public sealed class MainForm : Form
{
    public const int SettingsTab = 3;
    private const string Origin = "https://stilwater.app/";
    private static readonly string[] Pages = ["play", "friends", "mods", "settings"];

    private readonly GameInstall? _game = GameInstall.Find();
    private readonly WebView2 _web = new() { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(11, 10, 16) };
    private readonly Online _online;
    private readonly int _startPage;
    private Bridge? _bridge;
    private GamePipe? _pipe;

    public MainForm(int startPage = 0)
    {
        Text = "Stilwater";
        BackColor = Color.FromArgb(11, 10, 16);
        ClientSize = new Size(1180, 760);
        MinimumSize = new Size(980, 660);
        StartPosition = FormStartPosition.CenterScreen;
        _startPage = Math.Clamp(startPage, 0, Pages.Length - 1);
        Updater.CleanUp();
        // Created now that the form exists, so its events arrive on the UI thread.
        Online.Game = _game;
        _online = new Online();
        Controls.Add(_web);
        SetIcon();
        Load += async (_, _) => await StartAsync();
    }

    private async Task StartAsync()
    {
        try
        {
            // Browser data next to the launcher (on the game's drive), not in AppData.
            // The background music starts by itself, without waiting for a click.
            var options = new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required");
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(Runtime.Folder, "cache", "webview"), options);
            await _web.EnsureCoreWebView2Async(environment);
        }
        catch (Exception e) when (e is WebView2RuntimeNotFoundException or COMException)
        {
            var answer = MessageBox.Show(this, "Stilwater needs the Microsoft Edge WebView2 Runtime, which isn't installed. Open its download page?",
                                         "Stilwater", MessageBoxButtons.YesNo, MessageBoxIcon.Warning);
            if (answer == DialogResult.Yes)
                Process.Start(new ProcessStartInfo("https://developer.microsoft.com/microsoft-edge/webview2/") { UseShellExecute = true });
            Close();
            return;
        }

        var web = _web.CoreWebView2;
        web.SetVirtualHostNameToFolderMapping("stilwater.app", Path.Combine(AppContext.BaseDirectory, "ui"), CoreWebView2HostResourceAccessKind.DenyCors);
        web.Settings.AreDefaultContextMenusEnabled = false;
        web.Settings.IsZoomControlEnabled = false;
        web.Settings.IsStatusBarEnabled = false;
        web.Settings.AreBrowserAcceleratorKeysEnabled = false;
#if !DEBUG
        web.Settings.AreDevToolsEnabled = false;
#endif
        // The page stays the launcher: links go to the browser instead.
        web.NavigationStarting += (_, e) =>
        {
            if (e.Uri.StartsWith(Origin, StringComparison.OrdinalIgnoreCase)) return;
            e.Cancel = true;
            if (e.Uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true });
        };
        web.NewWindowRequested += (_, e) => e.Handled = true;
        // The Play page shows the game's art from Steam's cache; Stilwater doesn't ship any.
        string? art = null;
        if (GameInstall.SteamHeroArt() is { } artFile)
        {
            web.SetVirtualHostNameToFolderMapping("art.stilwater.app", Path.GetDirectoryName(artFile)!, CoreWebView2HostResourceAccessKind.DenyCors);
            art = "https://art.stilwater.app/" + Uri.EscapeDataString(Path.GetFileName(artFile));
        }
        _bridge = new Bridge(this, web, _game, _online) { Art = art };
        _pipe = new GamePipe(this, _online);
        // The page's maximize button shows restore while the window is maximized.
        var maximized = false;
        Resize += (_, _) =>
        {
            if (WindowState == FormWindowState.Minimized || maximized == (WindowState == FormWindowState.Maximized)) return;
            maximized = WindowState == FormWindowState.Maximized;
            _bridge.Emit("window", new { maximized });
        };
        web.Navigate($"{Origin}index.html#{Pages[_startPage]}");
        // For checking the UI while developing: STILWATER_SNAPSHOT=<file.png> saves the page a few
        // seconds after it opens and closes the window, without signing in.
        if (Environment.GetEnvironmentVariable("STILWATER_SNAPSHOT") is { Length: > 0 } snapshot)
        {
            await Task.Delay(4000);
            await using (var file = File.Create(snapshot))
                await web.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, file);
            Close();
            return;
        }
        await SignInSavedAsync();
    }

    /// <summary>Signs in with the login the game keeps, when there is one and the game isn't
    /// already signed in with it.</summary>
    private async Task SignInSavedAsync()
    {
        if (GameLogin.Read() is not { IsComplete: true } login || (GameInstall.IsRunning() && Online.UsesOpenSpy)) return;
        try { await _online.SignInAsync(login); }
        catch (Exception e) when (e is InvalidOperationException or IOException or System.Net.Sockets.SocketException or TimeoutException) { }
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        // Dark window chrome to match (Windows 10 20H1+ and 11); the page draws the title bar.
        var on = 1;
        DwmSetWindowAttribute(Handle, 20, ref on, sizeof(int));
        // Has Windows measure the frame again, now without the title bar (WindowFrame.CalcSize).
        SetWindowPos(Handle, 0, 0, 0, 0, 0, 0x0027 /* SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED */);
    }

    protected override void WndProc(ref Message m)
    {
        if (!WindowFrame.CalcSize(this, ref m)) base.WndProc(ref m);
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        _pipe?.Dispose();
        _online.Dispose();
        base.OnFormClosed(e);
    }

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    [DllImport("user32.dll")]
    private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

    // The window and taskbar icon: assets\logo.ico, the same one the exe carries, with every size
    // Windows asks for.
    private void SetIcon()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "assets", "logo.ico");
        if (File.Exists(path)) Icon = new Icon(path);
    }
}
