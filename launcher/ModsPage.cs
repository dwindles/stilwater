using System.Diagnostics;

namespace Stilwater.Launcher;

/// <summary>Switches loose mods on and off, and shows the mods code co-op partners compare.</summary>
internal sealed class ModsPage : UserControl
{
    private readonly GameInstall _game;
    private readonly TableLayoutPanel _rows = new();
    private readonly Label _code = new() { AutoSize = true, Font = new Font("Consolas", 10.5f), Margin = new Padding(0, 10, 10, 0) };
    private readonly Label _status = new() { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Theme.Muted };

    public ModsPage(GameInstall game)
    {
        _game = game;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Body;

        var scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(28, 4, 28, 16) };
        _rows.Dock = DockStyle.Top;
        _rows.AutoSize = true;
        _rows.ColumnCount = 1;
        _rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        scroll.Controls.Add(_rows);

        var bar = new Panel { Dock = DockStyle.Bottom, Height = 60, BackColor = Theme.Panel, Padding = new Padding(28, 12, 28, 12) };
        var open = new Button
        {
            Text = "Open mods folder", Dock = DockStyle.Right, Width = 150, FlatStyle = FlatStyle.Flat,
            BackColor = Theme.Input, ForeColor = Theme.Text, FlatAppearance = { BorderSize = 0 }, Cursor = Cursors.Hand,
        };
        open.Click += (_, _) => Process.Start(new ProcessStartInfo(Path.Combine(_game.Folder, "mods")) { UseShellExecute = true });
        bar.Controls.AddRange([_status, open]);

        Controls.AddRange([scroll, bar]);
        Build();
    }

    private void Build()
    {
        _rows.SuspendLayout();
        _rows.Controls.Clear();

        var codeRow = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 16, 0, 0) };
        codeRow.Controls.Add(new Label { Text = "Mods code", Font = Theme.Strong, AutoSize = true, Margin = new Padding(0, 11, 12, 0) });
        _code.Text = "…";
        codeRow.Controls.Add(_code);
        var copy = new LinkLabel { Text = "Copy", AutoSize = true, LinkColor = Theme.Accent, Margin = new Padding(0, 12, 0, 0) };
        copy.LinkClicked += (_, _) => Clipboard.SetText(_code.Text);
        codeRow.Controls.Add(copy);
        _rows.Controls.Add(codeRow);
        _rows.Controls.Add(new Label
        {
            Text = "For co-op, you and your friend should have the same code: different weapons, cars or tables can desync or crash a session.",
            ForeColor = Theme.Muted, Font = Theme.Small, AutoSize = true, MaximumSize = new Size(600, 0), Margin = new Padding(0, 2, 0, 8),
        });

        string? group = null;
        foreach (var mod in ModList.Read(_game))
        {
            var g = mod.IsCore ? "Core fixes (Juiced)" : "Stilwater mods";
            if (g != group) AddSection(group = g);
            AddRow(mod);
        }
        _rows.ResumeLayout();
        _ = UpdateCodeAsync();
    }

    private async Task UpdateCodeAsync()
    {
        _code.Text = await Task.Run(() => ModList.Code(_game));
    }

    private void AddSection(string text) => _rows.Controls.Add(new Label
    {
        Text = text, Font = Theme.Strong, ForeColor = Theme.Muted, AutoSize = true, Margin = new Padding(0, 22, 0, 6),
    });

    private void AddRow(ModList.Mod mod)
    {
        var row = new Panel { Height = 48, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = Padding.Empty };
        row.Paint += (_, e) =>
        {
            using var pen = new Pen(Theme.Divider);
            e.Graphics.DrawLine(pen, 0, row.Height - 1, row.Width, row.Height - 1);
        };
        var name = mod.Name.StartsWith("STILWATER - ", StringComparison.OrdinalIgnoreCase) ? mod.Name[12..]
                 : mod.IsCore ? mod.Name[9..] : mod.Name;
        row.Controls.Add(new Label { Text = name, AutoSize = true, Location = new Point(0, 6) });
        row.Controls.Add(new Label
        {
            Text = $"{mod.Files} files, {mod.Bytes / 1024.0 / 1024.0:0.0} MB", AutoSize = true, Font = Theme.Small,
            ForeColor = Theme.Muted, Location = new Point(0, 26),
        });
        var toggle = new ToggleSwitch { Checked = mod.Enabled, Anchor = AnchorStyles.Top | AnchorStyles.Right };
        toggle.Location = new Point(row.Width - toggle.Width, (row.Height - toggle.Height) / 2);
        toggle.Click += (_, _) =>
        {
            try
            {
                ModList.SetEnabled(_game, mod.Name, toggle.Checked);
                _status.Text = $"{name} switched {(toggle.Checked ? "on" : "off")}. Applies next time the game starts.";
                _status.ForeColor = Theme.Muted;
                _ = UpdateCodeAsync();
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or InvalidOperationException)
            {
                _status.Text = e.Message;
                _status.ForeColor = Theme.Bad;
            }
        };
        row.Controls.Add(toggle);
        _rows.Controls.Add(row);
    }
}
