namespace Stilwater.Launcher;

internal static class Theme
{
    public static readonly Color Background = Color.FromArgb(17, 17, 19);
    public static readonly Color Panel = Color.FromArgb(26, 26, 30);
    public static readonly Color Input = Color.FromArgb(34, 34, 39);
    public static readonly Color Divider = Color.FromArgb(40, 40, 46);
    public static readonly Color Text = Color.FromArgb(236, 236, 238);
    public static readonly Color Muted = Color.FromArgb(139, 139, 147);
    public static readonly Color Accent = Color.FromArgb(139, 92, 246);
    public static readonly Color Good = Color.FromArgb(74, 222, 128);
    public static readonly Color Bad = Color.FromArgb(248, 113, 113);

    public static readonly Font Body = new("Segoe UI", 9.75f);
    public static readonly Font Small = new("Segoe UI", 8.5f);
    public static readonly Font Strong = new("Segoe UI Semibold", 9.75f);

    public static Button PrimaryButton(string text) => new()
    {
        Text = text,
        Font = Strong,
        ForeColor = Color.White,
        BackColor = Accent,
        FlatStyle = FlatStyle.Flat,
        FlatAppearance = { BorderSize = 0 },
        Cursor = Cursors.Hand,
        Size = new Size(110, 36),
    };
}
