namespace Stilwater.Launcher;

/// <summary>The online account (Stilwater Online or OpenSpy), friends, friend requests, invites and how co-op works.</summary>
internal sealed class FriendsPage : UserControl
{
    private const int InputWidth = 200;

    private readonly Online _online;
    private readonly TableLayoutPanel _rows = new();
    private readonly Label _status = new() { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, ForeColor = Theme.Muted };
    // Kept across rebuilds (friends' status changes rebuild the page), so typing isn't lost.
    private readonly TextBox _addFriend = TextInput("");
    private string _serviceState = "Checking…";
    private Color _serviceColor = Theme.Muted;
    private bool _busy;

    public FriendsPage(Online online)
    {
        _online = online;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Body;

        var scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(28, 4, 28, 16) };
        _rows.Dock = DockStyle.Top;
        _rows.AutoSize = true;
        _rows.ColumnCount = 1;
        _rows.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        scroll.Controls.Add(_rows);
        var bar = new Panel { Dock = DockStyle.Bottom, Height = 44, BackColor = Theme.Panel, Padding = new Padding(28, 6, 28, 6) };
        bar.Controls.Add(_status);
        Controls.AddRange([scroll, bar]);

        _online.Changed += Build;
        Build();
        _ = CheckServiceAsync();
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _online.Changed -= Build;
        base.Dispose(disposing);
    }

    private async Task CheckServiceAsync()
    {
        var problem = await Online.CheckAsync();
        _serviceState = problem is null ? "Online" : $"Problem: {problem}";
        _serviceColor = problem is null ? Theme.Good : Theme.Bad;
        if (!IsDisposed) Build();
    }

    private void Build()
    {
        if (IsDisposed) return;
        _rows.SuspendLayout();
        _rows.Controls.Clear();

        AddSection(Online.ServiceName);
        AddRow("Service", Online.UsesOpenSpy
                   ? "The community servers that replace GameSpy for SR2's online co-op."
                   : $"Our own servers for SR2's online co-op ({Online.Server}). Change it in Settings → Co-op.",
               new Label { Text = _serviceState, ForeColor = _serviceColor, AutoSize = true });

        AddSection("Your account");
        if (_online.SignedIn) BuildSignedIn();
        else BuildSignIn();

        if (_online.SignedIn)
        {
            if (_online.Requests.Count > 0)
            {
                AddSection("Friend requests");
                foreach (var request in _online.Requests)
                    AddRow(request.Name, "wants to be your friend",
                           Buttons(("Accept", () => _online.AcceptAsync(request)), ("Ignore", () => { _online.Ignore(request); return Task.CompletedTask; })));
            }

            AddSection("Friends");
            _addFriend.PlaceholderText = "Their nick";
            AddRow("Add a friend", "They'll get a request in their launcher or game.",
                   WithButton(_addFriend, "Send", async () =>
                   {
                       var nick = _addFriend.Text.Trim();
                       await _online.AddFriendAsync(nick, "Stilwater co-op");
                       _addFriend.Clear();
                       Say($"Friend request sent to {nick}.");
                   }));
            foreach (var friend in _online.Friends.OrderByDescending(f => f.Status).ThenBy(f => f.Name, StringComparer.OrdinalIgnoreCase))
            {
                var detail = friend.Status switch
                {
                    Online.Status.Offline => "offline",
                    _ => friend.Activity.Length > 0 ? friend.Activity : "online",
                };
                var actions = friend.Status == Online.Status.Offline
                    ? Buttons(("Remove", () => _online.RemoveFriendAsync(friend)))
                    : Buttons(("Invite", async () => { await _online.InviteAsync(friend); Say($"Invited {friend.Name}. Start the game and host co-op."); }),
                              ("Remove", () => _online.RemoveFriendAsync(friend)));
                AddRow(friend.Name, detail, actions, friend.Status == Online.Status.Offline ? Theme.Muted : Theme.Good);
            }
            if (_online.Friends.Count == 0)
                _rows.Controls.Add(Note($"No friends yet. Add them by their {Online.ServiceName} nick."));
        }

        AddSection("Playing co-op");
        _rows.Controls.Add(Note(
            "Saints Row 2's co-op is drop-in: your friend joins your campaign. Both of you start the game from Stilwater " +
            "(the launcher signs out while the game is open, since the game signs in with the same account).\n\n" +
            "Host: load your save, open Co-op and choose Online to host. Friend: Co-op → Online, then join your game from the list " +
            "or accept your invite.\n\n" +
            "Compare mods codes on the Mods page first: different mods can desync or crash a session. If your friend can't connect, " +
            "turn on \"Open router ports\" in Settings."));
        _rows.ResumeLayout();
    }

    private void BuildSignedIn()
    {
        var signOut = Button("Sign out", () => { _online.SignOut(); return Task.CompletedTask; });
        AddRow($"Signed in as {_online.Nick}", "The game signs in with this account too.", signOut);
    }

    private void BuildSignIn()
    {
        var saved = GameLogin.Read();
        var nick = TextInput(saved?.Nick ?? "");
        var email = TextInput(saved?.Email ?? "");
        var password = TextInput(saved?.Password ?? "");
        password.UseSystemPasswordChar = true;
        AddRow("Nick", "Your name in co-op.", nick);
        AddRow("Email", "", email);
        AddRow("Password", "Saved for the game too, so it signs in by itself.", password);

        GameLogin Entered() => new(nick.Text.Trim(), email.Text.Trim(), password.Text, saved?.LanName is { Length: > 0 } lan ? lan : nick.Text.Trim());
        var actions = Buttons(
            ("Sign in", async () =>
            {
                var login = Entered();
                await _online.SignInAsync(login);
                login.Write();
                Say("Signed in.");
            }),
            ("Create account", async () =>
            {
                var login = Entered();
                await Online.CreateAccountAsync(login);
                await _online.SignInAsync(login);
                login.Write();
                Say("Account created and signed in.");
            }));
        AddRow("", $"No account yet? Create account makes one on {Online.ServiceName} with these details.", actions);
    }

    private void Say(string text, bool bad = false)
    {
        _status.Text = text;
        _status.ForeColor = bad ? Theme.Bad : Theme.Muted;
    }

    private Control Buttons(params (string Text, Func<Task> Action)[] actions)
    {
        var flow = new FlowLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false, Margin = Padding.Empty };
        foreach (var (text, action) in actions) flow.Controls.Add(Button(text, action));
        flow.Size = flow.PreferredSize;
        return flow;
    }

    private Button Button(string text, Func<Task> action)
    {
        var button = new Button
        {
            Text = text, FlatStyle = FlatStyle.Flat, BackColor = Theme.Input, ForeColor = Theme.Text,
            FlatAppearance = { BorderSize = 0 }, Cursor = Cursors.Hand, Margin = new Padding(6, 0, 0, 0),
            Size = new Size(TextRenderer.MeasureText(text, Theme.Body).Width + 24, 28),
        };
        button.Click += async (_, _) =>
        {
            if (_busy) return;
            _busy = true;
            Say("…");
            try { await action(); }
            catch (Exception e) when (e is InvalidOperationException or IOException or System.Net.Sockets.SocketException
                                          or TimeoutException or ArgumentException or UnauthorizedAccessException)
            {
                Say(e.Message, bad: true);
            }
            finally { _busy = false; }
        };
        return button;
    }

    private Control WithButton(Control input, string text, Func<Task> action)
    {
        var flow = new FlowLayoutPanel { AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false, Margin = Padding.Empty };
        input.Margin = new Padding(0, 3, 0, 0);
        flow.Controls.AddRange([input, Button(text, action)]);
        flow.Size = flow.PreferredSize;
        return flow;
    }

    private static TextBox TextInput(string value) => new()
    {
        Text = value, Width = InputWidth, BackColor = Theme.Input, ForeColor = Theme.Text, BorderStyle = BorderStyle.FixedSingle,
    };

    private static Label Note(string text) => new()
    {
        Text = text, ForeColor = Theme.Muted, AutoSize = true, MaximumSize = new Size(620, 0), Margin = new Padding(0, 4, 0, 8),
    };

    private void AddSection(string text) => _rows.Controls.Add(new Label
    {
        Text = text, Font = Theme.Strong, ForeColor = Theme.Muted, AutoSize = true, Margin = new Padding(0, 22, 0, 6),
    });

    private void AddRow(string label, string help, Control input, Color? labelColor = null)
    {
        var row = new Panel { Height = help.Length > 0 ? 54 : 42, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = Padding.Empty };
        row.Paint += (_, e) =>
        {
            using var pen = new Pen(Theme.Divider);
            e.Graphics.DrawLine(pen, 0, row.Height - 1, row.Width, row.Height - 1);
        };
        row.Controls.Add(new Label { Text = label, AutoSize = true, ForeColor = labelColor ?? Theme.Text, Location = new Point(0, help.Length > 0 ? 9 : 12) });
        if (help.Length > 0)
            row.Controls.Add(new Label { Text = help, AutoSize = true, Font = Theme.Small, ForeColor = Theme.Muted, Location = new Point(0, 29) });
        input.Anchor = AnchorStyles.Top | AnchorStyles.Right;
        row.Controls.Add(input);
        row.Layout += (_, _) => input.Location = new Point(row.Width - input.Width, (row.Height - input.Height) / 2);
        _rows.Controls.Add(row);
    }
}
