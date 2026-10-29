"""The GTA V jeans (mods/gta-jeans), shared with mods/shared, which adds them to the tables.

Each is a copy of SR2's "men's loose jeans" (SOURCE, worn at the waist, M, or low, L) under its own
name of the same length (`base`), shaped like a GTA V ped's jeans (MODELS: its .ydd in
D:/tools/gta-clothes) and printed with one of its colourways (`ytd`, in the model's folder).
"""
SOURCE = "cmbot_mjeansmf01"
SOURCE_ITEM = "men's loose jeans"
SOURCE_VARIANT = "Stonewash_jeans"
SUFFIXES = ("m", "l")

# Model: (folder under the GTA clothes folder, drawable dictionary, where its boxers are in its
# texture, [areas of its texture that are stretched filler, never shown]), areas as x0, y0, x1, y1
# fractions, y down. Traplanta's filler: between the legs, and between the boxers and the waistband.
MODELS = {
    "traplanta": ("Traplanta Sagged Jeans", "task_000_u.ydd", (0, 0, 1, 0.09),
                  [(0.43, 0.12, 0.56, 0.48), (0, 0.09, 1, 0.195)]),
    "jeans2024": ("2024jeans/2024jeans", "lowr_031_u.ydd", (0.37, 0.42, 0.59, 0.57), []),
}

JEANS = [
    dict(name="Traplanta Black Print Jeans", base="cmbot_mjeansgt01", model="traplanta", ytd="task_diff_000_a_uni.ytd"),
    dict(name="Traplanta Blue Print Jeans", base="cmbot_mjeansgt02", model="traplanta", ytd="task_diff_000_b_uni.ytd"),
    dict(name="Traplanta Star Jeans", base="cmbot_mjeansgt03", model="traplanta", ytd="task_diff_000_c_uni.ytd"),
    dict(name="Traplanta Wreath Jeans", base="cmbot_mjeansgt04", model="traplanta", ytd="task_diff_000_d_uni.ytd"),
    dict(name="Washed Grey Jeans", base="cmbot_mjeansgt05", model="jeans2024", ytd="lowr_diff_031_a_uni.ytd"),
    dict(name="Washed Black Jeans", base="cmbot_mjeansgt06", model="jeans2024", ytd="lowr_diff_031_c_uni.ytd"),
]
