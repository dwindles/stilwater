using System.Runtime.InteropServices;

namespace Stilwater.Launcher;

/// <summary>The launcher draws its own title bar (the page's top bar, with its own minimize,
/// maximize and close buttons). Windows keeps the rest of the frame: the resize borders, the
/// shadow and snapping.</summary>
internal static class WindowFrame
{
    private const int WM_NCCALCSIZE = 0x0083, WM_NCLBUTTONDOWN = 0x00A1;

    // What the page's edges stand for when it starts a drag (the top bar is the caption).
    private static readonly Dictionary<string, int> HitTests = new()
    {
        [""] = 2, ["left"] = 10, ["right"] = 11, ["top"] = 12, ["topleft"] = 13, ["topright"] = 14,
    };

    /// <summary>Handles WM_NCCALCSIZE so the page reaches the top of the window, where the title
    /// bar was. True when it handled the message.</summary>
    public static bool CalcSize(Form form, ref Message m)
    {
        if (m.Msg != WM_NCCALCSIZE || m.WParam == 0) return false;
        var top = Marshal.ReadInt32(m.LParam, 4);
        // Windows works out the borders; the caption it would add is taken back.
        DefWndProc(form, ref m);
        // A maximized window hangs its borders off the screen, so the page starts below them.
        if (form.WindowState == FormWindowState.Maximized)
        {
            var dpi = GetDpiForWindow(form.Handle);
            top += GetSystemMetricsForDpi(33 /* SM_CYSIZEFRAME */, dpi) + GetSystemMetricsForDpi(92 /* SM_CXPADDEDBORDER */, dpi);
        }
        Marshal.WriteInt32(m.LParam, 4, top);
        m.Result = 0;
        return true;
    }

    /// <summary>Moves the window (edge "") or resizes it from one of its top or side edges, as if
    /// the title bar or the border had been pressed.</summary>
    public static void Drag(Form form, string edge)
    {
        if (!HitTests.TryGetValue(edge, out var hit)) return;
        if (hit != 2 && form.WindowState != FormWindowState.Normal) return;
        ReleaseCapture();
        SendMessage(form.Handle, WM_NCLBUTTONDOWN, hit, 0);
    }

    private static void DefWndProc(Form form, ref Message m) =>
        m.Result = DefWindowProc(form.Handle, m.Msg, m.WParam, m.LParam);

    [DllImport("user32.dll")] private static extern bool ReleaseCapture();
    [DllImport("user32.dll")] private static extern IntPtr SendMessage(IntPtr window, int message, nint wParam, nint lParam);
    [DllImport("user32.dll")] private static extern IntPtr DefWindowProc(IntPtr window, int message, nint wParam, nint lParam);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr window);
    [DllImport("user32.dll")] private static extern int GetSystemMetricsForDpi(int index, uint dpi);
}
