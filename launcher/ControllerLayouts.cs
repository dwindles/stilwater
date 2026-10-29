namespace Stilwater.Launcher;

/// <summary>
/// Control layouts for Saints Row 2's input.bin: (int32 keyboard key, int32 pad button) pairs indexed by
/// the game's PC_BTN_* action ids. Keyboard keys are DirectInput scan codes; 256/257 are the mouse buttons.
/// </summary>
internal static class ControllerLayouts
{
    public const string Keep = "keep";
    public const string GtaOnline = "gta";
    public const string Previous = "previous";

    public static readonly (string Value, string Text)[] Choices =
    [
        (Keep, "Keep current"),
        (GtaOnline, "GTA Online (controller + keyboard)"),
        (Previous, "Previous layout (backup)"),
    ];

    private const int A = 0, B = 1, X = 2, Y = 3, LB = 4, RB = 5, L3 = 8, R3 = 9, LT = 10, RT = 11;
    private const int DpadRight = 16, DpadLeft = 18;

    private const int KeyQ = 0x10, KeyE = 0x12, KeyT = 0x14, KeyY = 0x15, KeyF = 0x21, KeyG = 0x22, KeyX = 0x2D, KeyC = 0x2E, KeyM = 0x32;
    private const int KeyTab = 0x0F, KeyLCtrl = 0x1D, KeyComma = 0x33, KeyPeriod = 0x34, Numpad8 = 0x48, Numpad5 = 0x4C;
    private const int MouseLeft = 256, MouseRight = 257, Unbound = -1;

    // PC_BTN_* action id -> pad button. Mirrors tools/controls/gta_layout.py.
    private static readonly Dictionary<int, int> GtaOnlinePad = new()
    {
        [35] = RT, [16] = LT, [36] = RB, [18] = A, [5] = X, [14] = B, [4] = Y, [6] = LB, [15] = L3, [17] = R3,
        [37] = RT, [38] = LT, [7] = RB, [26] = L3, [49] = R3, [57] = A, [56] = X, [29] = DpadLeft, [30] = DpadRight,
        [50] = RT, [51] = LT, [47] = LB, [48] = RB,
    };

    // PC_BTN_* action id -> keyboard key or mouse button (GTA V PC defaults). Mirrors tools/controls/gta_layout.py.
    private static readonly Dictionary<int, int> GtaOnlineKeyboard = new()
    {
        [35] = MouseLeft, [16] = MouseRight, [36] = KeyQ, [4] = KeyF, [6] = KeyTab, [15] = KeyLCtrl, [17] = KeyG,
        [20] = KeyM, [31] = Unbound, [32] = Unbound, [84] = KeyT, [85] = KeyY, [26] = KeyE, [49] = KeyC, [27] = KeyX, [29] = KeyComma, [30] = KeyPeriod, [64] = Numpad8, [65] = Numpad5,
    };

    public static string InputBin =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "THQ", "Saints Row 2", "input.bin");

    // The layout from before Stilwater first changed it. Created once and never overwritten.
    private static string Backup => InputBin + ".bak";

    public static bool HasBackup => File.Exists(Backup);

    public static void Apply(string layout)
    {
        if (layout == Keep) return;
        if (!File.Exists(InputBin))
            throw new InvalidOperationException("input.bin doesn't exist yet. Open Options → Controls in game once and accept.");

        if (layout == Previous)
        {
            if (!HasBackup) throw new InvalidOperationException("There is no previous layout backup.");
            File.Copy(Backup, InputBin, overwrite: true);
            return;
        }

        if (!HasBackup) File.Copy(InputBin, Backup);
        var data = File.ReadAllBytes(InputBin);
        foreach (var (action, button) in GtaOnlinePad)
            BitConverter.TryWriteBytes(data.AsSpan(action * 8 + 4, 4), button);
        foreach (var (action, key) in GtaOnlineKeyboard)
            BitConverter.TryWriteBytes(data.AsSpan(action * 8, 4), key);
        File.WriteAllBytes(InputBin, data);
    }
}
