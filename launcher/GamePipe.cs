using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;

namespace Stilwater.Launcher;

/// <summary>The in-game menu (core Stilwater/InviteMenu.cpp) talks to the launcher over a named pipe,
/// \\.\pipe\stilwater-launcher, open only to this Windows user. The launcher stays signed in while
/// the game runs, so the menu shows its friends, sends invites and joins through it.
///
/// One message per line (UTF-8), fields separated by U+001F and list items by U+001E:
///   launcher -> game: me &lt;nick&gt; | friends &lt;id␞status␞name␞activity&gt;... | invite &lt;id&gt; &lt;name&gt; |
///                     joining &lt;id&gt; &lt;name&gt; | world &lt;address&gt; &lt;name&gt; | note &lt;text&gt;
///   game -> launcher: hello | invite &lt;id&gt; | join &lt;id&gt; | world &lt;id&gt;
/// Status is 0 offline, 1 online, 2 playing.</summary>
internal sealed class GamePipe : IDisposable
{
    private const string Name = "stilwater-launcher";
    private const char Field = '\u001f', Item = '\u001e';

    private readonly Form _form;
    private readonly Online _online;
    private readonly CancellationTokenSource _stop = new();
    private readonly object _writing = new();
    private StreamWriter? _writer;
    private Online.Friend? _world;     // the world to join, told to the game when it connects (joined from the launcher)

    public GamePipe(Form form, Online online)
    {
        _form = form;
        _online = online;
        _online.Changed += () => { Send(MeMessage()); Send(FriendsMessage()); };
        _online.Invited += friend => Send("invite", friend.ProfileId.ToString(), friend.Name);
        _online.Joined += friend => OnUi(() => { _world = friend; SendWorld(); });
        _ = Task.Run(ServeAsync);
    }

    private async Task ServeAsync()
    {
        while (!_stop.IsCancellationRequested)
        {
            try
            {
                var security = new PipeSecurity();
                security.AddAccessRule(new PipeAccessRule(WindowsIdentity.GetCurrent().User!, PipeAccessRights.FullControl, AccessControlType.Allow));
                await using var pipe = NamedPipeServerStreamAcl.Create(Name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte,
                    PipeOptions.Asynchronous, 0, 0, security);
                await pipe.WaitForConnectionAsync(_stop.Token);
                using var reader = new StreamReader(pipe, new UTF8Encoding(false));
                lock (_writing) _writer = new StreamWriter(pipe, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" };
                OnUi(() => { Send(MeMessage()); Send(FriendsMessage()); SendWorld(); });
                while (await reader.ReadLineAsync(_stop.Token) is { } line)
                    OnUi(() => Handle(line.Split(Field)));
            }
            catch (Exception e) when (e is IOException or OperationCanceledException or ObjectDisposedException) { }
            finally { lock (_writing) _writer = null; }
        }
    }

    private void OnUi(Action action)
    {
        if (_form.IsHandleCreated && !_form.IsDisposed) _form.BeginInvoke(action);
    }

    private async void Handle(string[] message)
    {
        var friend = message.Length > 1 && int.TryParse(message[1], out var id) ? _online.Friends.FirstOrDefault(f => f.ProfileId == id) : null;
        try
        {
            switch (message[0])
            {
                case "hello":
                    Send(MeMessage());
                    Send(FriendsMessage());
                    break;
                case "invite" when friend is not null:
                    await _online.InviteAsync(friend);
                    Send("note", $"Invited {friend.Name}.");
                    break;
                case "join" when friend is not null:
                    await _online.JoinAsync(friend);
                    Send("joining", friend.ProfileId.ToString(), friend.Name);
                    break;
                case "world" when friend is not null:
                    if (friend.Address.Length > 0) Send("world", friend.Address, friend.Name);
                    else Send("note", $"Can't find {friend.Name}'s address yet. Try again in a moment.");
                    break;
            }
        }
        catch (Exception e) when (e is InvalidOperationException or IOException or TimeoutException)
        {
            Send("note", e.Message);
        }
    }

    /// <summary>Tells the game to join the world of the friend joined last, once it's connected.</summary>
    private void SendWorld()
    {
        if (_world is null || _writer is null) return;
        if (_world.Address.Length > 0) Send("world", _world.Address, _world.Name);
        else Send("note", $"Can't find {_world.Name}'s address yet. Join them again in a moment.");
        _world = null;
    }

    // me <nick> <style>: the style is the profile's look; the game draws our name tag with it.
    private string MeMessage() => string.Join(Field, "me", _online.SignedIn ? _online.Nick : "",
        _online.SignedIn ? _online.ProfileOf(_online.ProfileId)?.Style ?? "" : "");

    private string FriendsMessage() => string.Join(Field, new[] { "friends" }.Concat(
        _online.Friends.OrderBy(f => f.Status == Online.Status.Offline).ThenBy(f => f.Name, StringComparer.OrdinalIgnoreCase)
            .Select(f => string.Join(Item, f.ProfileId, f.Status switch { Online.Status.Playing => 2, Online.Status.Online => 1, _ => 0 },
                                     Clean(f.Name), Clean(f.Activity)))));

    private void Send(params string[] fields) => Send(string.Join(Field, fields.Select(Clean)));

    private void Send(string line)
    {
        lock (_writing)
        {
            try { _writer?.WriteLine(line); }
            catch (Exception e) when (e is IOException or ObjectDisposedException) { _writer = null; }
        }
    }

    // Fields can't hold line breaks or the separators.
    private static string Clean(string text) => new(text.Where(c => c >= ' ').ToArray());

    public void Dispose() => _stop.Cancel();
}
