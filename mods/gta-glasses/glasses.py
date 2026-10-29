"""The GTA V glasses (mods/gta-glasses), shared with mods/shared, which adds them to the tables.

Each is a copy of SR2's "designer shades" (SOURCE) under its own name of the same length (`base`),
shaped like a GTA V ped glasses prop (MODELS: its .ydd in D:/tools/gta-clothes) and printed with
one of its colourways (`ytd`, in the model's folder), the lens tint included.
"""
SOURCE = "cmgla_ushogo"
SOURCE_ITEM = "designer shades"
SOURCE_VARIANT = "orig_14 - Default"

MODELS = {
    "cartier": ("Drakos Old Cartiers/Plains", "p_eyes_000.ydd"),
    "cartier_iced": ("Drakos Old Cartiers/Iced", "p_eyes_000.ydd"),
}

GLASSES = [
    dict(name="Cartier White Buffs", base="cmgla_ucart1", model="cartier", ytd="p_eyes_diff_000_a.ytd"),
    dict(name="Cartier White Buffs Orange", base="cmgla_ucart2", model="cartier", ytd="p_eyes_diff_000_c.ytd"),
    dict(name="Cartier Brown Wood", base="cmgla_ucart3", model="cartier", ytd="p_eyes_diff_000_d.ytd"),
    dict(name="Cartier Red Wood", base="cmgla_ucart4", model="cartier", ytd="p_eyes_diff_000_g.ytd"),
    dict(name="Cartier Iced Out", base="cmgla_ucart5", model="cartier_iced", ytd="p_eyes_diff_000_a.ytd"),
]
