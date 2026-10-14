using System.Drawing.Drawing2D;

namespace Stilwater.Launcher;

/// <summary>A small on/off switch, drawn to match the launcher theme.</summary>
internal sealed class ToggleSwitch : Control
{
    private bool _checked;

    public ToggleSwitch()
    {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.UserPaint | ControlStyles.SupportsTransparentBackColor, true);
        Size = new Size(36, 20);
        Cursor = Cursors.Hand;
        BackColor = Color.Transparent;
    }

    public bool Checked
    {
        get => _checked;
        set
        {
            _checked = value;
            Invalidate();
        }
    }

    protected override void OnClick(EventArgs e)
    {
        Checked = !Checked;
        base.OnClick(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        var track = new Rectangle(0, 0, Width - 1, Height - 1);
        using (var path = Pill(track))
        using (var fill = new SolidBrush(_checked ? Theme.Accent : Theme.Input))
            g.FillPath(fill, path);

        var knob = Height - 6;
        var x = _checked ? Width - knob - 3 : 3;
        using var white = new SolidBrush(_checked ? Color.White : Theme.Muted);
        g.FillEllipse(white, x, 3, knob, knob);
    }

    private static GraphicsPath Pill(Rectangle r)
    {
        var path = new GraphicsPath();
        path.AddArc(r.X, r.Y, r.Height, r.Height, 90, 180);
        path.AddArc(r.Right - r.Height, r.Y, r.Height, r.Height, 270, 180);
        path.CloseFigure();
        return path;
    }
}
