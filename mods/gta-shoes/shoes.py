"""The GTA V sneakers (mods/gta-shoes), shared with mods/shared, which adds them to the tables.

Each is a copy of SR2's "sports shoes with strap" (SOURCE) under its own name of the same length
(`base`), shaped like a GTA V ped shoe (MODELS: its .ydd in D:/tools/gta-clothes) and printed with
one of that shoe's colourways (`ytd`, the texture dictionary in the model's folder).
"""
SOURCE = "cmsho_usporsho01"
SOURCE_ITEM = "sports shoes with strap"
SOURCE_VARIANT = "leather"

# Model: (folder under the GTA clothes folder, drawable dictionary).
MODELS = {
    "jordan4": ("JORDAN 4 RETRO PACK/Jumpman heel", "feet_025_u.ydd"),
    "jordan4air": ("JORDAN 4 RETRO PACK/Nike air heel", "feet_024_u.ydd"),
    "jordan5": ("Nike Air Jordan 5/Nike Air Jordan 5", "feet_080_u.ydd"),
    "jordan1": ("85vintage", "feet_006_u.ydd"),
}

SHOES = [
    dict(name="Jordan 4 Fire Red", base="cmsho_uaj4_fired", model="jordan4", ytd="feet_diff_025_b_uni.ytd"),
    dict(name="Jordan 4 Motorsports", base="cmsho_uaj4_motor", model="jordan4", ytd="feet_diff_025_c_uni.ytd"),
    dict(name="Jordan 4 Thunder", base="cmsho_uaj4_thund", model="jordan4", ytd="feet_diff_025_d_uni.ytd"),
    dict(name="Jordan 4 Lightning", base="cmsho_uaj4_light", model="jordan4", ytd="feet_diff_025_e_uni.ytd"),
    dict(name="Jordan 4 Military Blue", base="cmsho_uaj4_milbl", model="jordan4", ytd="feet_diff_025_f_uni.ytd"),
    dict(name="Jordan 4 White Cement", base="cmsho_uaj4_wcemt", model="jordan4", ytd="feet_diff_025_h_uni.ytd"),
    dict(name="Jordan 4 Raptors", base="cmsho_uaj4_rapts", model="jordan4", ytd="feet_diff_025_m_uni.ytd"),
    dict(name="Jordan 4 Bred", base="cmsho_uaj4_bred1", model="jordan4air", ytd="feet_diff_024_a_uni.ytd"),
    dict(name="Jordan 5 Black Red", base="cmsho_uaj5_blred", model="jordan5", ytd="feet_diff_080_l_uni.ytd"),
    dict(name="Jordan 5 Grape", base="cmsho_uaj5_grape", model="jordan5", ytd="feet_diff_080_c_uni.ytd"),
    dict(name="Jordan 5 White", base="cmsho_uaj5_white", model="jordan5", ytd="feet_diff_080_j_uni.ytd"),
    dict(name="Jordan 5 Green Bean", base="cmsho_uaj5_green", model="jordan5", ytd="feet_diff_080_g_uni.ytd"),
    dict(name="Jordan 1 '85 Chicago", base="cmsho_uaj1_chi85", model="jordan1", ytd="feet_diff_006_a_uni.ytd"),
    dict(name="Jordan 1 '85 Bred", base="cmsho_uaj1_bred8", model="jordan1", ytd="feet_diff_006_b_uni.ytd"),
    dict(name="Jordan 1 '85 Royal", base="cmsho_uaj1_royal", model="jordan1", ytd="feet_diff_006_d_uni.ytd"),
]
