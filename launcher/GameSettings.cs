namespace Stilwater.Launcher;

internal enum SettingKind { Toggle, Number, Choice, Text }

/// <summary>One option stored in juiced.ini.</summary>
internal sealed record Setting(
    string Group, string Label, string Help, string Section, string Key, SettingKind Kind, string Default,
    double Min = 0, double Max = 1, double Step = 1, int Decimals = 0, (string Value, string Text)[]? Choices = null);

internal static class GameSettings
{
    public static readonly Setting[] Juiced =
    [
        new("Stilwater", "Main menu text", "Shown in capitals. Empty hides it.",
            "Stilwater", "MenuText", SettingKind.Text, "holdonquietly.com"),
        new("Stilwater", "Tree distance", "Multiple of vanilla.",
            "Stilwater", "TreeDistance", SettingKind.Number, "1.5", 1, 4, 0.25, 2),
        new("Stilwater", "Shadow distance", "Meters. Vanilla 125, max 255, 0 keeps vanilla.",
            "Stilwater", "ShadowDistance", SettingKind.Number, "255", 0, 255, 5),

        new("Graphics", "Borderless window", "",
            "Graphics", "Borderless", SettingKind.Toggle, "1"),
        new("Graphics", "Clearer lighting", "Removes the orange-yellow filter (VanillaFX+).",
            "Graphics", "VanillaFXPlus", SettingKind.Toggle, "0"),
        new("Graphics", "Dynamic render distance", "Draws further when there is headroom.",
            "Graphics", "DynamicRenderDistance", SettingKind.Toggle, "0"),
        new("Graphics", "Shadow quality", "",
            "Graphics", "ShadowMapRes", SettingKind.Choice, "960",
            Choices: [("960", "Vanilla"), ("2048", "High"), ("4096", "Very high"), ("8192", "Ultra")]),
        new("Graphics", "Smooth shadows", "",
            "Graphics", "ShadowFiltering", SettingKind.Toggle, "0"),
        new("Graphics", "Xbox 360 gamma", "",
            "Graphics", "X360Gamma", SettingKind.Toggle, "1"),
        new("Graphics", "Distance fog", "",
            "Graphics", "DisableFog", SettingKind.Choice, "0", Choices: [("0", "On"), ("1", "Off")]),
        new("Graphics", "Remove vignette", "",
            "Graphics", "RemoveVignette", SettingKind.Toggle, "0"),
        new("Graphics", "Remove cutscene black bars", "",
            "Graphics", "RemoveBlackBars", SettingKind.Toggle, "0"),
        new("Graphics", "Uncap FPS", "Above 100 FPS. Uses more CPU.",
            "Debug", "UncapFPS", SettingKind.Toggle, "0"),

        new("Gameplay", "Skip intro videos", "",
            "Gameplay", "SkipIntros", SettingKind.Toggle, "0"),
        new("Gameplay", "Field of view", "",
            "Gameplay", "FOVMultiplier", SettingKind.Number, "1.0", 1, 2, 0.05, 2),
        new("Gameplay", "Aim assist", "",
            "Gameplay", "DisableAimAssist", SettingKind.Choice, "1",
            Choices: [("0", "On"), ("1", "Off for mouse"), ("2", "Off")]),
        new("Gameplay", "Hold to aim", "Aim only while the button is held, like GTA. Off makes it a toggle.",
            "Input", "HoldFineAim", SettingKind.Toggle, "0"),
        new("Gameplay", "Hide tutorials", "",
            "Gameplay", "DisableTutorials", SettingKind.Toggle, "0"),
        new("Gameplay", "Fast doors", "",
            "Gameplay", "FastDoors", SettingKind.Toggle, "0"),
    ];
}
