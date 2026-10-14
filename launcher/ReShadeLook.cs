using System.Globalization;

namespace Stilwater.Launcher;

/// <summary>Writes the Stilwater ReShade preset at one of a few strengths.</summary>
internal static class ReShadeLook
{
    public const string PresetFile = "Stilwater-SR2-Clear.ini";
    public const string Keep = "keep";

    public static readonly (string Value, string Text)[] Choices =
    [
        (Keep, "Keep current"),
        ("off", "Off"),
        ("subtle", "Subtle"),
        ("clear", "Clear"),
        ("vivid", "Vivid"),
    ];

    private sealed record Strength(double DehazeAlpha, double DehazeStrength, double Clarity, double ClarityDark,
        double Contrast, double Vibrance, double Sharpening);

    private static readonly Dictionary<string, Strength> Strengths = new()
    {
        ["subtle"] = new(0.30, -0.45, 0.20, 0.25, 0.08, 0.15, 0.35),
        ["clear"] = new(0.45, -0.35, 0.30, 0.30, 0.12, 0.25, 0.45),
        ["vivid"] = new(0.60, -0.25, 0.45, 0.40, 0.16, 0.40, 0.60),
    };

    private const string Techniques =
        "DeHaze@Dehaze.fx,Clarity@Clarity.fx,Curves@Curves.fx,Vibrance@Vibrance.fx,ContrastAdaptiveSharpen@CAS.fx";

    public static bool IsInstalled(GameInstall game) => File.Exists(Path.Combine(game.Folder, "ReShade.ini"));

    public static void Apply(GameInstall game, string look)
    {
        if (look == Keep) return;
        var path = Path.Combine(game.Folder, PresetFile);
        if (look == "off")
        {
            File.WriteAllText(path, "Techniques=\r\nTechniqueSorting=" + Techniques + "\r\n");
            return;
        }

        var s = Strengths[look];
        string F(double v) => v.ToString("0.000000", CultureInfo.InvariantCulture);
        File.WriteAllText(path, string.Join("\r\n",
        [
            $"Techniques={Techniques}",
            $"TechniqueSorting={Techniques}",
            "",
            "[CAS.fx]", "Contrast=0.000000", $"Sharpening={F(s.Sharpening)}",
            "",
            "[Clarity.fx]", "ClarityBlendIfDark=50", "ClarityBlendIfLight=205", "ClarityBlendMode=1",
            $"ClarityDarkIntensity={F(s.ClarityDark)}", "ClarityLightIntensity=0.000000", "ClarityOffset=2.000000",
            "ClarityRadius=3", $"ClarityStrength={F(s.Clarity)}", "ClarityViewBlendIfMask=0", "ClarityViewMask=0",
            "",
            "[Curves.fx]", $"Contrast={F(s.Contrast)}", "Formula=2", "Mode=0",
            "",
            "[Dehaze.fx]", $"Alpha={F(s.DehazeAlpha)}", "Debug=0", "DepthMultiplier=0.250000", "IgnoreSky=0",
            $"TransmissionMultiplier={F(s.DehazeStrength)}",
            "",
            "[Vibrance.fx]", $"Vibrance={F(s.Vibrance)}", "VibranceRGBBalance=1.000000,1.000000,1.000000", "Vibrance_Luma=0",
            "",
        ]));
    }
}
