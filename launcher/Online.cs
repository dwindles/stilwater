using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;

namespace Stilwater.Launcher;

/// <summary>
/// The online service the game's co-op uses for accounts, friends and the game list: Stilwater
/// Online (server/ in the repo) by default, or OpenSpy. Both replace GameSpy, so this speaks
/// GameSpy Presence (GP) the way the game does (product 11405, namespace 1, game name srow2pc,
/// found in SR2_pc.exe) and the launcher can sign in with the same account, show friends and send
/// invites. Messages are \key\value pairs ending in \final\. The server comes from
/// [Stilwater] OnlineServer in juiced.ini, which the core reads too.
/// </summary>
internal sealed class Online : IDisposable
{
    public const string GameName = "srow2pc";
    public const int ProductId = 11405;
    public const int NamespaceId = 1;
    public const string DefaultServer = "155.138.222.253";
    private const int PresencePort = 29900;
    private const int SearchPort = 29901;
    // Launcher-to-launcher messages ride on GP text messages.
    private const string InvitePrefix = "STILWATER_INVITE|";

    public enum Status { Offline = 0, Online = 1, Playing = 2 }

    public sealed record Friend(int ProfileId, string Name, Status Status, string Activity);
    public sealed record Request(int ProfileId, string Name, string Signature);

    public event Action? Changed;
    public event Action<Friend>? Invited;
    public event Action<string>? Disconnected;

    private readonly SynchronizationContext _ui = SynchronizationContext.Current ?? new SynchronizationContext();
    private readonly Dictionary<int, Friend> _friends = [];
    private readonly Dictionary<int, Request> _requests = [];
    private readonly Dictionary<int, string> _names = [];
    private TcpClient? _client;
    private NetworkStream? _stream;
    private CancellationTokenSource? _stop;
    private int _sessionKey;
    private int _nextId = 2;

    public int ProfileId { get; private set; }
    public string Nick { get; private set; } = "";
    public bool SignedIn => _stream is not null && _sessionKey != 0;
    public IReadOnlyCollection<Friend> Friends => _friends.Values;
    public IReadOnlyCollection<Request> Requests => _requests.Values;

    /// <summary>The game install whose juiced.ini names the server.</summary>
    public static GameInstall? Game { get; set; }

    /// <summary>The configured server: an address, or "openspy".</summary>
    public static string Server
    {
        get
        {
            var value = Game is null ? null : new IniFile(Game.JuicedIni).Get("Stilwater", "OnlineServer")?.Trim();
            return string.IsNullOrEmpty(value) ? DefaultServer : value;
        }
    }

    public static bool UsesOpenSpy => Server.Equals("openspy", StringComparison.OrdinalIgnoreCase);
    public static string ServiceName => UsesOpenSpy ? "OpenSpy" : "Stilwater Online";
    private static string Presence => UsesOpenSpy ? "gpcm.openspy.net" : Server;
    private static string Search => UsesOpenSpy ? "gpsp.openspy.net" : Server;
    private static string Available => UsesOpenSpy ? $"{GameName}.available.openspy.net" : Server;

    /// <summary>Whether the service answers for Saints Row 2: its account server and the game's
    /// availability check. Returns null when fine, otherwise what failed.</summary>
    public static async Task<string?> CheckAsync()
    {
        try
        {
            using var tcp = new TcpClient();
            await tcp.ConnectAsync(Presence, PresencePort).WaitAsync(TimeSpan.FromSeconds(5));
            var reply = await ReadMessageAsync(tcp.GetStream(), CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(5));
            if (!reply.StartsWith(@"\lc\1")) return "account server answered oddly";

            using var udp = new UdpClient();
            var probe = new byte[] { 9, 0, 0, 0, 0 }.Concat(Encoding.ASCII.GetBytes(GameName + "\0")).ToArray();
            await udp.SendAsync(probe, probe.Length, Available, 27900);
            var answer = await udp.ReceiveAsync().WaitAsync(TimeSpan.FromSeconds(5));
            return answer.Buffer.Length >= 7 && answer.Buffer[^4..].All(b => b == 0) ? null : "Saints Row 2 is listed as unavailable";
        }
        catch (Exception e) when (e is SocketException or TimeoutException or IOException)
        {
            return $"not reachable ({e.Message})";
        }
    }

    /// <summary>Signs in with the game's login (nick and email, as SR2 does). Throws with
    /// the service's message when it refuses.</summary>
    public async Task SignInAsync(GameLogin login)
    {
        Close();
        _client = new TcpClient();
        await _client.ConnectAsync(Presence, PresencePort).WaitAsync(TimeSpan.FromSeconds(10));
        _stream = _client.GetStream();
        var hello = Parse(await ReadMessageAsync(_stream, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10)));
        var serverChallenge = hello.GetValueOrDefault("challenge", "");

        var clientChallenge = new string(Enumerable.Range(0, 32).Select(_ => (char)('A' + RandomNumberGenerator.GetInt32(26))).ToArray());
        var user = $"{login.Nick}@{login.Email}";
        var passwordHash = Md5(login.Password);
        var response = Md5(passwordHash + new string(' ', 48) + user + clientChallenge + serverChallenge + passwordHash);
        await SendAsync($@"\login\\challenge\{clientChallenge}\user\{user}\partnerid\0\response\{response}\firewall\1\port\0" +
                        $@"\productid\{ProductId}\gamename\{GameName}\namespaceid\{NamespaceId}\sdkrevision\11\quiet\0\id\1\final\");

        var reply = Parse(await ReadMessageAsync(_stream, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(15)));
        if (reply.ContainsKey("error"))
        {
            Close();
            throw new InvalidOperationException(reply.GetValueOrDefault("errmsg", "Sign-in refused."));
        }
        if (!reply.ContainsKey("sesskey") || !reply.ContainsKey("profileid"))
        {
            Close();
            throw new InvalidOperationException($"{ServiceName} didn't sign you in.");
        }
        _sessionKey = int.Parse(reply["sesskey"]);
        ProfileId = int.Parse(reply["profileid"]);
        Nick = login.Nick;
        _stop = new CancellationTokenSource();
        _ = ReadLoopAsync(_stop.Token);
        _ = KeepAliveAsync(_stop.Token);
        await SetStatusAsync(Status.Online, "In the Stilwater launcher");
    }

    /// <summary>Creates an account (what the game's Create account does).</summary>
    public static async Task CreateAccountAsync(GameLogin login)
    {
        using var tcp = new TcpClient();
        await tcp.ConnectAsync(Presence, PresencePort).WaitAsync(TimeSpan.FromSeconds(10));
        var stream = tcp.GetStream();
        await ReadMessageAsync(stream, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));
        var message = $@"\newuser\\email\{login.Email}\nick\{login.Nick}\passwordenc\{EncodePassword(login.Password)}" +
                      $@"\productid\{ProductId}\gamename\{GameName}\namespaceid\{NamespaceId}\uniquenick\\partnerid\0\id\1\final\";
        var bytes = Encoding.ASCII.GetBytes(message);
        await stream.WriteAsync(bytes);
        var reply = Parse(await ReadMessageAsync(stream, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(15)));
        if (reply.ContainsKey("error"))
            throw new InvalidOperationException(reply.GetValueOrDefault("errmsg", "Account not created."));
    }

    public Task SetStatusAsync(Status status, string activity) =>
        SendAsync($@"\status\{(int)status}\sesskey\{_sessionKey}\statstring\{Clean(activity)}\locstring\\final\");

    /// <summary>Sends a friend request to the player with this nick.</summary>
    public async Task AddFriendAsync(string nick, string message)
    {
        var id = await FindAsync(nick) ?? throw new InvalidOperationException($"No {ServiceName} player called {nick}.");
        _names[id] = nick;
        await SendAsync($@"\addbuddy\\sesskey\{_sessionKey}\newprofileid\{id}\reason\{Clean(message)}\final\");
    }

    public async Task AcceptAsync(Request request)
    {
        await SendAsync($@"\authadd\\sesskey\{_sessionKey}\fromprofileid\{request.ProfileId}\sig\{request.Signature}\final\");
        _requests.Remove(request.ProfileId);
        Raise();
    }

    public void Ignore(Request request)
    {
        _requests.Remove(request.ProfileId);
        Raise();
    }

    public async Task RemoveFriendAsync(Friend friend)
    {
        await SendAsync($@"\delbuddy\\sesskey\{_sessionKey}\delprofileid\{friend.ProfileId}\final\");
        _friends.Remove(friend.ProfileId);
        Raise();
    }

    /// <summary>Asks a friend to join your co-op game (shown in their launcher).</summary>
    public Task InviteAsync(Friend friend) =>
        SendAsync($@"\bm\1\sesskey\{_sessionKey}\t\{friend.ProfileId}\msg\{InvitePrefix}{Clean(Nick)}\final\");

    /// <summary>Signs out (the game signs in with the same account, and an account has one session).</summary>
    public void SignOut()
    {
        if (SignedIn)
        {
            try { SendAsync($@"\logout\\sesskey\{_sessionKey}\final\").Wait(TimeSpan.FromSeconds(2)); }
            catch (AggregateException) { }
        }
        Close();
        _friends.Clear();
        _requests.Clear();
        Raise();
    }

    public void Dispose() => SignOut();

    private void Close()
    {
        _stop?.Cancel();
        _stream?.Dispose();
        _client?.Dispose();
        _stream = null;
        _client = null;
        _sessionKey = 0;
    }

    private async Task ReadLoopAsync(CancellationToken stop)
    {
        try
        {
            while (!stop.IsCancellationRequested && _stream is not null)
            {
                var message = Parse(await ReadMessageAsync(_stream, stop));
                _ui.Post(_ => Handle(message), null);
            }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or OperationCanceledException or SocketException)
        {
            if (stop.IsCancellationRequested) return;
            _ui.Post(_ =>
            {
                Close();
                Disconnected?.Invoke(e.Message);
                Raise();
            }, null);
        }
    }

    private async Task KeepAliveAsync(CancellationToken stop)
    {
        try
        {
            while (!stop.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(60), stop);
                await SendAsync(@"\ka\\final\");
            }
        }
        catch (Exception e) when (e is OperationCanceledException or IOException or ObjectDisposedException) { }
    }

    private void Handle(Dictionary<string, string> m)
    {
        if (m.TryGetValue("bdy", out _) && m.TryGetValue("list", out var list))
        {
            foreach (var part in list.Split(',', StringSplitOptions.RemoveEmptyEntries))
                if (int.TryParse(part, out var id) && !_friends.ContainsKey(id))
                    Track(id, Status.Offline, "");
        }
        else if (m.TryGetValue("bm", out var kind) && m.TryGetValue("f", out var from) && int.TryParse(from, out var id))
        {
            var text = m.GetValueOrDefault("msg", "");
            switch (kind)
            {
                case "100":             // status: |s|<status>|ss|<status text>|ls|...
                    var fields = text.Split('|');
                    string Field(string key) { var i = Array.IndexOf(fields, key); return i >= 0 && i + 1 < fields.Length ? fields[i + 1] : ""; }
                    var status = int.TryParse(Field("s"), out var s) ? s : 0;
                    Track(id, status == 0 ? Status.Offline : Field("ss").Contains("co-op", StringComparison.OrdinalIgnoreCase) || Field("ss").Contains("Playing") ? Status.Playing : Status.Online, Field("ss"));
                    break;
                case "2":               // friend request: <reason>|signed|<signature>
                    var signed = text.IndexOf("|signed|", StringComparison.Ordinal);
                    _requests[id] = new Request(id, Name(id), signed >= 0 ? text[(signed + 8)..] : "");
                    LookUp(id);
                    break;
                case "1" when text.StartsWith(InvitePrefix, StringComparison.Ordinal):
                    if (_friends.TryGetValue(id, out var friend)) Invited?.Invoke(friend);
                    break;
                case "4":               // they accepted us
                    Track(id, Status.Online, "");
                    break;
                case "6":               // they removed us
                    _friends.Remove(id);
                    break;
            }
        }
        else if (m.ContainsKey("pi") && m.TryGetValue("profileid", out var pid) && int.TryParse(pid, out var profile))
        {
            _names[profile] = m.GetValueOrDefault("uniquenick") is { Length: > 0 } unique ? unique : m.GetValueOrDefault("nick", $"#{profile}");
            if (_friends.TryGetValue(profile, out var f)) _friends[profile] = f with { Name = _names[profile] };
            if (_requests.TryGetValue(profile, out var r)) _requests[profile] = r with { Name = _names[profile] };
        }
        else if (m.ContainsKey("error") && m.ContainsKey("fatal"))
        {
            Close();
            Disconnected?.Invoke(m.GetValueOrDefault("errmsg", $"Signed out by {ServiceName}."));
        }
        Raise();
    }

    private void Track(int id, Status status, string activity)
    {
        _friends[id] = new Friend(id, Name(id), status, activity);
        LookUp(id);
    }

    private string Name(int id) => _names.TryGetValue(id, out var n) ? n : $"#{id}";

    private void LookUp(int id)
    {
        if (!_names.ContainsKey(id))
            _ = SendAsync($@"\getprofile\\sesskey\{_sessionKey}\profileid\{id}\id\{_nextId++}\final\");
    }

    /// <summary>The profile id of the player with this nick (the search server).</summary>
    private async Task<int?> FindAsync(string nick)
    {
        using var tcp = new TcpClient();
        await tcp.ConnectAsync(Search, SearchPort).WaitAsync(TimeSpan.FromSeconds(10));
        var stream = tcp.GetStream();
        var bytes = Encoding.ASCII.GetBytes($@"\search\\sesskey\{_sessionKey}\profileid\{ProfileId}\namespaceid\{NamespaceId}" +
                                            $@"\partnerid\0\nick\{Clean(nick)}\gamename\{GameName}\final\");
        await stream.WriteAsync(bytes);
        var reply = await ReadMessageAsync(stream, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));
        var parts = reply.Split('\\');
        for (var i = 1; i + 1 < parts.Length; i += 2)
            if (parts[i] == "bsr" && int.TryParse(parts[i + 1], out var id)) return id;
        return null;
    }

    private async Task SendAsync(string message)
    {
        var stream = _stream ?? throw new InvalidOperationException("Not signed in.");
        var bytes = Encoding.ASCII.GetBytes(message);
        await stream.WriteAsync(bytes);
    }

    private void Raise() => Changed?.Invoke();

    private static async Task<string> ReadMessageAsync(NetworkStream stream, CancellationToken stop)
    {
        var text = new StringBuilder();
        var buffer = new byte[1];
        while (!text.ToString().EndsWith(@"\final\", StringComparison.Ordinal))
        {
            if (await stream.ReadAsync(buffer, stop) == 0) throw new IOException("Connection closed.");
            text.Append((char)buffer[0]);
        }
        return text.ToString();
    }

    private static Dictionary<string, string> Parse(string message)
    {
        var parts = message.Split('\\');
        var result = new Dictionary<string, string>();
        for (var i = 1; i + 1 < parts.Length; i += 2) result.TryAdd(parts[i], parts[i + 1]);
        return result;
    }

    private static string Clean(string text) => text.Replace("\\", "").Replace("|", "");

    private static string Md5(string text) => Convert.ToHexString(MD5.HashData(Encoding.ASCII.GetBytes(text))).ToLowerInvariant();

    /// <summary>GameSpy's password encoding for new accounts: XOR with a fixed pseudo-random sequence
    /// (seed "gspy"), then base64 with [, ] and _ for +, / and =.</summary>
    private static string EncodePassword(string password)
    {
        var bytes = Encoding.ASCII.GetBytes(password);
        var num = 0x79707367 & 0x7FFFFFFF;
        for (var i = 0; i < bytes.Length; i++)
        {
            num = Lame(num);
            bytes[i] ^= (byte)(num % 0xFF % 256);
        }
        return Convert.ToBase64String(bytes).Replace('+', '[').Replace('/', ']').Replace('=', '_');
    }

    private static int Lame(int num)
    {
        var c = (num >> 16) & 0xFFFF;
        var a = num & 0xFFFF;
        c *= 0x41A7;
        a *= 0x41A7;
        a += (c & 0x7FFF) << 16;
        if (a < 0) { a &= 0x7FFFFFFF; a++; }
        a += c >> 15;
        if (a < 0) { a &= 0x7FFFFFFF; a++; }
        return a;
    }
}
