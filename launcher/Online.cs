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
    /// <summary>A player's public profile (Stilwater Online only): bio and picture (JPEG or PNG).</summary>
    public sealed record Profile(int ProfileId, string Bio, string Hash, byte[]? Picture);

    public event Action? Changed;
    public event Action<Friend>? Invited;
    public event Action<string>? Disconnected;

    private readonly SynchronizationContext _ui = SynchronizationContext.Current ?? new SynchronizationContext();
    private readonly Dictionary<int, Friend> _friends = [];
    private readonly Dictionary<int, Request> _requests = [];
    private readonly Dictionary<int, string> _names = [];
    private readonly Dictionary<int, Profile> _profiles = [];
    // Requests waiting for their reply, by \id\.
    private readonly Dictionary<string, TaskCompletionSource<Dictionary<string, string>>> _waiting = [];
    private TcpClient? _client;
    private NetworkStream? _stream;
    private MessageReader? _reader;
    private readonly SemaphoreSlim _writing = new(1, 1);
    private CancellationTokenSource? _stop;
    private int _sessionKey;
    private int _nextId = 2;

    public int ProfileId { get; private set; }
    public string Nick { get; private set; } = "";
    /// <summary>The login ticket (\lt\) from signing in: what shows the server's web side (shared
    /// mods) who this is.</summary>
    public string LoginTicket { get; private set; } = "";
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

    /// <summary>The round trip to the account server in milliseconds (an ICMP echo, so the
    /// server does no work for it), or null when it doesn't reply.</summary>
    public static async Task<long?> PingAsync()
    {
        try
        {
            using var ping = new System.Net.NetworkInformation.Ping();
            var reply = await ping.SendPingAsync(Presence, 1500);
            return reply.Status == System.Net.NetworkInformation.IPStatus.Success ? reply.RoundtripTime : null;
        }
        catch (System.Net.NetworkInformation.PingException) { return null; }
    }

    /// <summary>Signs in with the game's login (nick and email, as SR2 does). Throws with
    /// the service's message when it refuses.</summary>
    public async Task SignInAsync(GameLogin login)
    {
        Close();
        _client = new TcpClient();
        await _client.ConnectAsync(Presence, PresencePort).WaitAsync(TimeSpan.FromSeconds(10));
        _stream = _client.GetStream();
        _reader = new MessageReader(_stream);
        var hello = Parse(await _reader.ReadAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10)));
        var serverChallenge = hello.GetValueOrDefault("challenge", "");

        var clientChallenge = new string(Enumerable.Range(0, 32).Select(_ => (char)('A' + RandomNumberGenerator.GetInt32(26))).ToArray());
        var user = $"{login.Nick}@{login.Email}";
        var passwordHash = Md5(login.Password);
        var response = Md5(passwordHash + new string(' ', 48) + user + clientChallenge + serverChallenge + passwordHash);
        await SendAsync($@"\login\\challenge\{clientChallenge}\user\{user}\partnerid\0\response\{response}\firewall\1\port\0" +
                        $@"\productid\{ProductId}\gamename\{GameName}\namespaceid\{NamespaceId}\sdkrevision\11\quiet\0" +
                        // Stilwater Online keeps the launcher signed in beside the game when it knows which is which.
                        (UsesOpenSpy ? "" : @"\swlauncher\1") + @"\id\1\final\");

        var reply = Parse(await _reader.ReadAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(15)));
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
        LoginTicket = reply.GetValueOrDefault("lt", "");
        Nick = login.Nick;
        _stop = new CancellationTokenSource();
        _ = ReadLoopAsync(_stop.Token);
        _ = KeepAliveAsync(_stop.Token);
        await SetStatusAsync(Status.Online, "In the Stilwater launcher");
        if (!UsesOpenSpy)
        {
            // Stilwater Online's own extensions: tells the server this is the launcher (it then
            // sends profile changes), and loads our profile.
            await SendAsync(@"\swhello\\final\");
            _ = LoadProfileAsync(ProfileId);
        }
    }

    public Profile? ProfileOf(int profileId) => _profiles.GetValueOrDefault(profileId);

    /// <summary>Accepts a friend's invite: for the next few minutes the game's co-op matchmaking
    /// finds only that friend's game (server/presence.py cmd_swjoin), so it joins them.</summary>
    public async Task JoinAsync(Friend friend)
    {
        if (UsesOpenSpy) throw new InvalidOperationException("Joining from an invite is a Stilwater Online feature.");
        await RequestAsync($@"\swjoin\sesskey\{_sessionKey}\profileid\{friend.ProfileId}");
    }

    /// <summary>Changes your picture (an empty array removes it) and/or bio; null leaves either as it is.</summary>
    public async Task SetProfileAsync(byte[]? picture, string? bio)
    {
        if (UsesOpenSpy) throw new InvalidOperationException("Profiles are a Stilwater Online feature.");
        var message = new StringBuilder($@"\swsetprofile\\sesskey\{_sessionKey}");
        if (bio is not null) message.Append($@"\bio\{Clean(bio)}");
        if (picture is not null) message.Append($@"\avatar\{Convert.ToBase64String(picture)}");
        var reply = await RequestAsync(message.ToString());
        var old = _profiles.GetValueOrDefault(ProfileId);
        var hash = reply.GetValueOrDefault("hash", "");
        var kept = picture ?? old?.Picture;
        _profiles[ProfileId] = new Profile(ProfileId, bio ?? old?.Bio ?? "", hash, kept is { Length: > 0 } ? kept : null);
        AvatarCache.Write(ProfileId, hash, _profiles[ProfileId].Picture);
        Raise();
    }

    /// <summary>Fetches a profile; the picture only comes when it differs from the cached one.</summary>
    private async Task LoadProfileAsync(int profileId)
    {
        if (UsesOpenSpy || !SignedIn) return;
        var cached = AvatarCache.Read(profileId);
        try
        {
            var reply = await RequestAsync($@"\swgetprofile\\sesskey\{_sessionKey}\profileid\{profileId}\have\{cached?.Hash ?? ""}");
            var hash = reply.GetValueOrDefault("hash", "");
            byte[]? picture = null;
            if (reply.TryGetValue("avatar", out var data)) picture = Convert.FromBase64String(data);
            else if (hash.Length > 0 && cached?.Hash == hash) picture = cached.Value.Data;
            _profiles[profileId] = new Profile(profileId, reply.GetValueOrDefault("bio", ""), hash, picture);
            if (reply.ContainsKey("avatar") || hash.Length == 0) AvatarCache.Write(profileId, hash, picture);
            Raise();
        }
        catch (Exception e) when (e is InvalidOperationException or IOException or TimeoutException or FormatException) { }
    }

    private async Task<Dictionary<string, string>> RequestAsync(string body)
    {
        var id = (_nextId++).ToString();
        var reply = new TaskCompletionSource<Dictionary<string, string>>(TaskCreationOptions.RunContinuationsAsynchronously);
        _waiting[id] = reply;
        try
        {
            await SendAsync($@"{body}\id\{id}\final\");
            return await reply.Task.WaitAsync(TimeSpan.FromSeconds(15));
        }
        finally { _waiting.Remove(id); }
    }

    /// <summary>Profile pictures kept between runs: &lt;launcher&gt;\cache\avatars\&lt;profile id&gt;-&lt;hash&gt;.img.</summary>
    private static class AvatarCache
    {
        private static string Folder => Path.Combine(Runtime.Folder, "cache", "avatars");

        public static (string Hash, byte[] Data)? Read(int profileId)
        {
            try
            {
                var file = Directory.Exists(Folder) ? Directory.GetFiles(Folder, $"{profileId}-*.img").FirstOrDefault() : null;
                return file is null ? null : (Path.GetFileNameWithoutExtension(file)[(profileId.ToString().Length + 1)..], File.ReadAllBytes(file));
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
        }

        public static void Write(int profileId, string hash, byte[]? data)
        {
            try
            {
                Directory.CreateDirectory(Folder);
                foreach (var old in Directory.GetFiles(Folder, $"{profileId}-*.img")) File.Delete(old);
                if (data is { Length: > 0 } && hash.Length > 0) File.WriteAllBytes(Path.Combine(Folder, $"{profileId}-{hash}.img"), data);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
    }

    /// <summary>Creates an account (what the game's Create account does).</summary>
    public static async Task CreateAccountAsync(GameLogin login)
    {
        using var tcp = new TcpClient();
        await tcp.ConnectAsync(Presence, PresencePort).WaitAsync(TimeSpan.FromSeconds(10));
        var stream = tcp.GetStream();
        var reader = new MessageReader(stream);
        await reader.ReadAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(10));
        var message = $@"\newuser\\email\{login.Email}\nick\{login.Nick}\passwordenc\{EncodePassword(login.Password)}" +
                      $@"\productid\{ProductId}\gamename\{GameName}\namespaceid\{NamespaceId}\uniquenick\\partnerid\0\id\1\final\";
        var bytes = Encoding.ASCII.GetBytes(message);
        await stream.WriteAsync(bytes);
        var reply = Parse(await reader.ReadAsync(CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(15)));
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
        _reader = null;
        _client = null;
        _sessionKey = 0;
        LoginTicket = "";
    }

    private async Task ReadLoopAsync(CancellationToken stop)
    {
        try
        {
            var reader = _reader ?? throw new IOException("Not connected.");
            while (!stop.IsCancellationRequested)
            {
                var message = Parse(await reader.ReadAsync(stop));
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
        // A reply to one of our requests, or an error about it.
        if (m.TryGetValue("id", out var replyTo) && _waiting.TryGetValue(replyTo, out var waiter) &&
            (m.ContainsKey("swprofile") || m.ContainsKey("swjoined") || m.ContainsKey("error")))
        {
            if (m.ContainsKey("error")) waiter.TrySetException(new InvalidOperationException(m.GetValueOrDefault("errmsg", $"{ServiceName} refused.")));
            else waiter.TrySetResult(m);
            return;
        }
        if (m.ContainsKey("swprofilechanged") && int.TryParse(m.GetValueOrDefault("profileid"), out var changed))
        {
            _ = LoadProfileAsync(changed);
            return;
        }
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
                    if (!_profiles.ContainsKey(id)) _ = LoadProfileAsync(id);
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
        if (!_profiles.ContainsKey(id)) _ = LoadProfileAsync(id);
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
        var bytes = Encoding.Latin1.GetBytes(message);
        // Requests go out from several places at once (status, profile lookups); one at a time on the wire.
        await _writing.WaitAsync();
        try { await stream.WriteAsync(bytes); }
        finally { _writing.Release(); }
    }

    private void Raise() => Changed?.Invoke();

    private static Task<string> ReadMessageAsync(NetworkStream stream, CancellationToken stop) =>
        new MessageReader(stream).ReadAsync(stop);

    /// <summary>Splits a connection's bytes into \final\-terminated messages. Several can arrive in
    /// one read, and a profile picture makes one tens of kilobytes long.</summary>
    private sealed class MessageReader(NetworkStream stream)
    {
        private static readonly byte[] Final = Encoding.ASCII.GetBytes(@"\final\");
        private readonly List<byte> _pending = [];
        private readonly byte[] _buffer = new byte[16 * 1024];

        public async Task<string> ReadAsync(CancellationToken stop)
        {
            var searchFrom = 0;
            while (true)
            {
                var end = IndexOfFinal(searchFrom);
                if (end >= 0)
                {
                    var message = Encoding.Latin1.GetString(_pending.GetRange(0, end + Final.Length).ToArray());
                    _pending.RemoveRange(0, end + Final.Length);
                    return message;
                }
                searchFrom = Math.Max(0, _pending.Count - Final.Length + 1);
                var read = await stream.ReadAsync(_buffer, stop);
                if (read == 0) throw new IOException("Connection closed.");
                _pending.AddRange(_buffer.AsSpan(0, read).ToArray());
            }
        }

        private int IndexOfFinal(int from)
        {
            for (var i = from; i + Final.Length <= _pending.Count; i++)
            {
                var j = 0;
                while (j < Final.Length && _pending[i + j] == Final[j]) j++;
                if (j == Final.Length) return i;
            }
            return -1;
        }
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
