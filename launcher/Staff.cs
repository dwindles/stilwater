using System.Diagnostics;

namespace Stilwater.Launcher;

/// <summary>
/// The staff Upload button: publishes a release with tools\release.ps1 from the repo checkout that
/// [Stilwater] RepoFolder in juiced.ini names (it builds, commits, pushes and creates the GitHub
/// release players update from). Players don't have a checkout, so they don't see the button.
/// </summary>
internal static class Staff
{
    /// <summary>The repo checkout to publish from, or null on a player's machine.</summary>
    public static string? RepoFolder(GameInstall? game)
    {
        if (game is null) return null;
        var folder = new IniFile(game.JuicedIni).Get("Stilwater", "RepoFolder")?.Trim();
        return !string.IsNullOrEmpty(folder) && File.Exists(Path.Combine(folder, "tools", "release.ps1")) ? folder : null;
    }

    /// <summary>Asks for the version and notes, then runs the release script in its own window,
    /// which stays open to show how it went.</summary>
    public static void Upload(IWin32Window owner, string repo, Version suggested)
    {
        using var dialog = new ReleaseDialog(suggested);
        if (dialog.ShowDialog(owner) != DialogResult.OK) return;

        var start = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, WorkingDirectory = repo };
        foreach (var arg in new[] { "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(repo, "tools", "release.ps1"),
                                    "-Version", dialog.Version, "-Notes", dialog.Notes })
            start.ArgumentList.Add(arg);
        Process.Start(start);
    }

    private sealed class ReleaseDialog : Form
    {
        private readonly TextBox _version = new() { BackColor = Theme.Input, ForeColor = Theme.Text, BorderStyle = BorderStyle.FixedSingle, Width = 120 };
        private readonly TextBox _notes = new()
        {
            Multiline = true, BackColor = Theme.Input, ForeColor = Theme.Text, BorderStyle = BorderStyle.FixedSingle,
            ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, PlaceholderText = "What's new (shown on the release page)",
        };

        public string Version => _version.Text.Trim();
        public string Notes => _notes.Text.Trim();

        public ReleaseDialog(Version suggested)
        {
            Text = "Upload a release";
            BackColor = Theme.Background;
            ForeColor = Theme.Text;
            Font = Theme.Body;
            ClientSize = new Size(460, 300);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            StartPosition = FormStartPosition.CenterParent;
            Padding = new Padding(20);
            _version.Text = suggested.ToString();

            var top = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 64, WrapContents = false };
            top.Controls.Add(new Label { Text = "Version", AutoSize = true, Margin = new Padding(0, 4, 12, 0) });
            top.Controls.Add(_version);
            top.Controls.Add(new Label
            {
                Text = $"Builds everything, commits and pushes the repo, and publishes it to {Updater.Repository}. Players get it from Update.",
                ForeColor = Theme.Muted, Font = Theme.Small, AutoSize = true, MaximumSize = new Size(420, 0), Margin = new Padding(0, 8, 0, 0),
            });
            top.SetFlowBreak(_version, true);

            var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 52, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(0, 12, 0, 0) };
            var publish = Theme.PrimaryButton("Upload");
            publish.Click += (_, _) =>
            {
                if (!System.Version.TryParse(Version, out var v) || v.Build < 0 || Version.Count(c => c == '.') != 2)
                {
                    MessageBox.Show(this, "The version needs three numbers, like 0.2.1.", Text);
                    return;
                }
                DialogResult = DialogResult.OK;
            };
            var cancel = new Button
            {
                Text = "Cancel", Size = new Size(90, 36), FlatStyle = FlatStyle.Flat, BackColor = Theme.Input, ForeColor = Theme.Text,
                FlatAppearance = { BorderSize = 0 }, DialogResult = DialogResult.Cancel,
            };
            buttons.Controls.AddRange([publish, cancel]);
            CancelButton = cancel;

            Controls.AddRange([_notes, buttons, top]);
        }
    }
}
