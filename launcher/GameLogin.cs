using System.Text;

namespace Stilwater.Launcher;

/// <summary>
/// The online login Saints Row 2 keeps in %LOCALAPPDATA%\THQ\Saints Row 2\settings.dat, which its
/// Co-op → Online menu signs in with on its own (see docs/re-notes.md). After the 0x54-byte display
/// record come four 0x40-byte strings, each XORed with the low byte of successive MSVC rand()
/// values after srand(0xADF0 + i): password, nick, email, LAN name.
/// </summary>
internal sealed record GameLogin(string Nick, string Email, string Password, string LanName)
{
    private const int DisplayRecord = 0x54;
    private const int Block = 0x40;
    private const int ProfileDisplayRecord = 0x6DA;     // profile.dat keeps a copy of the display record

    public static string Folder => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "THQ", "Saints Row 2");
    public static string SettingsPath => Path.Combine(Folder, "settings.dat");

    public bool IsComplete => Nick.Length > 0 && Email.Length > 0 && Password.Length > 0;

    public static GameLogin? Read()
    {
        if (!File.Exists(SettingsPath)) return null;
        var data = File.ReadAllBytes(SettingsPath);
        if (data.Length < DisplayRecord + 4 * Block) return null;
        string Field(int i) => Decode(data.AsSpan(DisplayRecord + i * Block, Block), i);
        return new GameLogin(Field(1), Field(2), Field(0), Field(3));
    }

    /// <summary>Saves the login. A missing settings.dat starts from profile.dat's display record.</summary>
    public void Write()
    {
        if (GameInstall.IsRunning()) throw new InvalidOperationException("Close Saints Row 2 first. It rewrites settings.dat while running.");
        byte[] data;
        if (File.Exists(SettingsPath))
        {
            data = File.ReadAllBytes(SettingsPath);
            if (data.Length < DisplayRecord + 4 * Block) Array.Resize(ref data, DisplayRecord + 4 * Block);
        }
        else
        {
            var profile = Path.Combine(Folder, "profile.dat");
            if (!File.Exists(profile)) throw new InvalidOperationException("Start Saints Row 2 once first, so it saves its settings.");
            data = new byte[DisplayRecord + 4 * Block];
            File.ReadAllBytes(profile).AsSpan(ProfileDisplayRecord, DisplayRecord).CopyTo(data);
        }

        foreach (var (i, text) in new[] { (0, Password), (1, Nick), (2, Email), (3, LanName) })
            Encode(text, i).CopyTo(data, DisplayRecord + i * Block);
        File.WriteAllBytes(SettingsPath, data);
    }

    private static IEnumerable<byte> Keystream(int block)
    {
        uint seed = 0xADF0u + (uint)block;
        for (var i = 0; i < Block; i++)
        {
            seed = seed * 214013 + 2531011;
            yield return (byte)(seed >> 16 & 0x7FFF);
        }
    }

    private static string Decode(ReadOnlySpan<byte> block, int index)
    {
        var plain = block.ToArray();
        var i = 0;
        foreach (var k in Keystream(index)) plain[i++] ^= k;
        var end = Array.IndexOf(plain, (byte)0);
        return Encoding.ASCII.GetString(plain, 0, end < 0 ? plain.Length : end);
    }

    private static byte[] Encode(string text, int index)
    {
        var plain = new byte[Block];
        var bytes = Encoding.ASCII.GetBytes(text);
        if (bytes.Length >= Block) throw new ArgumentException("Too long (63 characters at most).");
        bytes.CopyTo(plain, 0);
        var i = 0;
        foreach (var k in Keystream(index)) plain[i++] ^= k;
        return plain;
    }
}
