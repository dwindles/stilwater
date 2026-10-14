using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Stilwater.Launcher;

/// <summary>
/// Gameplay tuning as loose table overrides. Multipliers live in juiced.ini [StilwaterTuning]; applying
/// them reads the original tables from common.vpp_pc, scales the values and writes mods/STILWATER - Tuning.
/// Only the data section (before &lt;TableDescription&gt;) is edited, so the rest of each file is unchanged.
/// </summary>
internal static class Tuning
{
    public const string Section = "StilwaterTuning";
    private const string ModFolder = "STILWATER - Tuning";

    public static readonly Setting[] Settings =
    [
        Multiplier("Damage taken", "DamageTaken", "1.00 is vanilla. Applies on every difficulty."),
        Multiplier("Damage dealt", "DamageDealt", ""),
        Multiplier("Health regeneration", "HealthRegen", "Faster regen also starts sooner."),
        Multiplier("Wanted level decay", "WantedDecay", "Higher loses heat faster."),
        Multiplier("Police sensitivity", "PoliceHeat", "Wanted points per crime."),
        Multiplier("Gang sensitivity", "GangHeat", "Gang notoriety per crime."),
        Multiplier("Car damage taken", "CarDamage", ""),
    ];

    private static Setting Multiplier(string label, string key, string help) =>
        new("Difficulty", label, help, Section, key, SettingKind.Number, "1.0", 0.1, 4, 0.05, 2);

    public static void Apply(GameInstall game)
    {
        var ini = new IniFile(game.JuicedIni);
        double Get(string key) =>
            double.TryParse(ini.Get(Section, key), NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : 1.0;
        var m = Settings.ToDictionary(s => s.Key, s => Get(s.Key));

        var folder = Path.Combine(game.Folder, "mods", ModFolder);
        if (m.Values.All(v => Math.Abs(v - 1.0) < 0.001))
        {
            if (Directory.Exists(folder)) Directory.Delete(folder, recursive: true);
            SetLooseEntry(game, enabled: false);
            return;
        }

        var common = new Packfile(Path.Combine(game.Folder, "common.vpp_pc"));
        Directory.CreateDirectory(folder);

        Write(folder, "difficulty_levels.xtbl", common, data =>
        {
            data = Scale(data, "Damage_Received_Mult", m["DamageTaken"]);
            data = Scale(data, "Damage_Dealt_Mult", m["DamageDealt"]);
            data = Scale(data, "Health_Regen_Speed_Mult", m["HealthRegen"]);
            data = Scale(data, "Health_Regen_Wait_Mult", 1 / m["HealthRegen"]);
            data = Scale(data, "Notoriety_Decay_Mult", m["WantedDecay"]);
            return Scale(data, "Vehicle_Damage_Received_Mult", m["CarDamage"]);
        });
        Write(folder, "notoriety.xtbl", common, data =>
        {
            data = ScaleInside(data, "Police", "Points", m["PoliceHeat"]);
            return ScaleInside(data, "Gang", "Points", m["GangHeat"]);
        });
        SetLooseEntry(game, enabled: true);
    }

    private static void Write(string folder, string name, Packfile source, Func<string, string> edit)
    {
        var text = Encoding.UTF8.GetString(source.Read(name));
        var split = text.IndexOf("<TableDescription>", StringComparison.Ordinal);
        if (split < 0) split = text.Length;
        File.WriteAllText(Path.Combine(folder, name), edit(text[..split]) + text[split..], new UTF8Encoding(false));
    }

    // <Tag>number</Tag> -> scaled, keeping integers as integers.
    private static string Scale(string data, string tag, double factor) =>
        Regex.Replace(data, $@"<{tag}>\s*([-0-9.]+)\s*</{tag}>", match =>
        {
            var raw = match.Groups[1].Value;
            var value = double.Parse(raw, CultureInfo.InvariantCulture) * factor;
            var text = raw.Contains('.')
                ? value.ToString("0.0###", CultureInfo.InvariantCulture)
                : Math.Round(value).ToString(CultureInfo.InvariantCulture);
            return $"<{tag}>{text}</{tag}>";
        });

    // Scale <tag> only inside <parent>...</parent> blocks.
    private static string ScaleInside(string data, string parent, string tag, double factor) =>
        Regex.Replace(data, $@"<{parent}>.*?</{parent}>", block => Scale(block.Value, tag, factor), RegexOptions.Singleline);

    // Keep loose.txt's "mods/STILWATER - Tuning" line in step with the folder, preserving CRLF line endings.
    private static void SetLooseEntry(GameInstall game, bool enabled)
    {
        var path = Path.Combine(game.Folder, "loose.txt");
        var entry = "mods/" + ModFolder;
        var lines = File.Exists(path) ? File.ReadAllLines(path).Where(l => l.Length > 0).ToList() : [];
        var has = lines.Contains(entry, StringComparer.OrdinalIgnoreCase);
        if (enabled == has) return;
        if (enabled) lines.Add(entry);
        else lines.RemoveAll(l => l.Equals(entry, StringComparison.OrdinalIgnoreCase));
        File.WriteAllText(path, string.Join("\r\n", lines) + "\r\n", Encoding.ASCII);
    }
}
