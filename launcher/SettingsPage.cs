using System.Globalization;

namespace Stilwater.Launcher;

/// <summary>Edits juiced.ini, the controller layout, the ReShade look and the DXVK FPS counter.</summary>
internal sealed class SettingsPage : UserControl
{
    private const int InputWidth = 150;

    private readonly GameInstall _game;
    private readonly TableLayoutPanel _rows = new();
    private readonly Dictionary<Setting, Control> _inputs = new();
    private readonly ComboBox _controller = Combo(ControllerLayouts.Choices);
    private readonly ComboBox _reshade = Combo(ReShadeLook.Choices);
    private readonly ToggleSwitch _fpsCounter = new();
    private readonly Label _status = new();

    public SettingsPage(GameInstall game)
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
        var save = Theme.PrimaryButton("Save");
        save.Dock = DockStyle.Right;
        save.Click += (_, _) => Save();
        _status.Dock = DockStyle.Fill;
        _status.TextAlign = ContentAlignment.MiddleLeft;
        _status.ForeColor = Theme.Muted;
        bar.Controls.AddRange([_status, save]);

        Controls.AddRange([scroll, bar]);
        Build();
    }

    private void Build()
    {
        var ini = new IniFile(_game.JuicedIni);
        string? group = null;
        foreach (var setting in GameSettings.Juiced.Concat(Tuning.Settings))
        {
            if (setting.Group != group) AddSection(group = setting.Group);
            var input = CreateInput(setting, ini.Get(setting.Section, setting.Key) ?? setting.Default);
            _inputs[setting] = input;
            AddRow(setting.Label, setting.Help, input);
        }

        AddSection("Controls");
        AddRow("Layout", "Controller and keyboard/mouse. Close the game first.", _controller);

        AddSection("Look");
        if (ReShadeLook.IsInstalled(_game))
            AddRow("ReShade", "Press F2 in game to fine-tune.", _reshade);
        _fpsCounter.Checked = _game.FpsCounterEnabled;
        AddRow("FPS counter", "", _fpsCounter);
    }

    private static Control CreateInput(Setting setting, string value) => setting.Kind switch
    {
        SettingKind.Toggle => new ToggleSwitch { Checked = value.Trim() == "1" },
        SettingKind.Number => new NumericUpDown
        {
            Minimum = (decimal)setting.Min,
            Maximum = (decimal)setting.Max,
            Increment = (decimal)setting.Step,
            DecimalPlaces = setting.Decimals,
            Value = Math.Clamp(decimal.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d
                : decimal.Parse(setting.Default, CultureInfo.InvariantCulture), (decimal)setting.Min, (decimal)setting.Max),
            Width = InputWidth,
            BackColor = Theme.Input,
            ForeColor = Theme.Text,
            BorderStyle = BorderStyle.None,
            TextAlign = HorizontalAlignment.Right,
        },
        SettingKind.Choice => SelectValue(Combo(setting.Choices!), value.Trim()),
        _ => TextInput(value),
    };

    private static TextBox TextInput(string value)
    {
        var box = new TextBox { Text = value, Width = InputWidth, BackColor = Theme.Input, ForeColor = Theme.Text, BorderStyle = BorderStyle.None };
        // Don't select the whole value when the page opens with focus on this box.
        box.Enter += (_, _) => box.BeginInvoke(() => box.SelectionLength = 0);
        return box;
    }

    private static string ReadInput(Setting setting, Control input) => input switch
    {
        ToggleSwitch toggle => toggle.Checked ? "1" : "0",
        NumericUpDown number => setting.Decimals > 0
            ? number.Value.ToString("0.000000", CultureInfo.InvariantCulture)
            : ((int)number.Value).ToString(CultureInfo.InvariantCulture),
        ComboBox combo => ((Choice)combo.SelectedItem!).Value,
        _ => input.Text.Trim(),
    };

    private void Save()
    {
        if (GameInstall.IsRunning())
        {
            ShowStatus("Close Saints Row 2 first. It rewrites these files while running.", Theme.Bad);
            return;
        }

        try
        {
            var ini = new IniFile(_game.JuicedIni);
            foreach (var (setting, input) in _inputs)
                ini.Set(setting.Section, setting.Key, ReadInput(setting, input));
            ini.Save();
            Tuning.Apply(_game);

            ControllerLayouts.Apply(((Choice)_controller.SelectedItem!).Value);
            if (ReShadeLook.IsInstalled(_game)) ReShadeLook.Apply(_game, ((Choice)_reshade.SelectedItem!).Value);
            _game.SetFpsCounter(_fpsCounter.Checked);

            _controller.SelectedIndex = 0;
            _reshade.SelectedIndex = 0;
            ShowStatus("Saved. Applies next time the game starts.", Theme.Muted);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or InvalidOperationException
                                      or InvalidDataException or KeyNotFoundException)
        {
            ShowStatus(e.Message, Theme.Bad);
        }
    }

    private void ShowStatus(string text, Color color)
    {
        _status.Text = text;
        _status.ForeColor = color;
    }

    private void AddSection(string text) => _rows.Controls.Add(new Label
    {
        Text = text,
        Font = Theme.Strong,
        ForeColor = Theme.Muted,
        AutoSize = true,
        Margin = new Padding(0, 22, 0, 6),
    });

    private void AddRow(string label, string help, Control input)
    {
        var row = new Panel { Height = help.Length > 0 ? 54 : 42, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = Padding.Empty };
        row.Paint += (_, e) =>
        {
            using var pen = new Pen(Theme.Divider);
            e.Graphics.DrawLine(pen, 0, row.Height - 1, row.Width, row.Height - 1);
        };

        row.Controls.Add(new Label { Text = label, AutoSize = true, Location = new Point(0, help.Length > 0 ? 9 : 12) });
        if (help.Length > 0)
            row.Controls.Add(new Label { Text = help, AutoSize = true, Font = Theme.Small, ForeColor = Theme.Muted, Location = new Point(0, 29) });

        input.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        input.Location = new Point(row.Width - input.Width, (row.Height - input.Height) / 2);
        row.Controls.Add(input);
        _rows.Controls.Add(row);
    }

    private sealed record Choice(string Value, string Text)
    {
        public override string ToString() => Text;
    }

    private static ComboBox Combo((string Value, string Text)[] choices)
    {
        var combo = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            FlatStyle = FlatStyle.Flat,
            BackColor = Theme.Input,
            ForeColor = Theme.Text,
            Width = InputWidth,
        };
        foreach (var (value, text) in choices) combo.Items.Add(new Choice(value, text));
        combo.SelectedIndex = 0;
        return combo;
    }

    private static ComboBox SelectValue(ComboBox combo, string value)
    {
        var match = combo.Items.Cast<Choice>().FirstOrDefault(c => c.Value == value);
        if (match is not null) combo.SelectedItem = match;
        return combo;
    }
}
