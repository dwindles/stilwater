"""The GTA V tops (mods/gta-tops), shared with mods/shared, which adds them to the tables.

Each group is an SR2 item (`item`, its style `variant`) whose meshes (`source` + suffix) are copied
under each top's `base` (same length) and reshaped like a GTA V ped top: per mesh suffix, the GTA
model it takes the shape of (a .ydd in D:/tools/gta-clothes), the folder of that model's colourways,
the mesh's diffuse and bump texture names (after the source name), and optionally an area of the
GTA texture left out (x0, y0, x1, y1 fractions, y down): the open Nike Tech's model has a white tee
under the jacket, the right half of its texture, which SR2's open jacket would otherwise show. A top names its colourway
by the texture dictionary's letter (`colour`), the same in every folder of its group.
"""
GROUPS = {
    "baseball": dict(
        source="cmuns_utshirt03", item="three-quarter t-shirt", variant="Sleeves",
        meshes={
            "u": ("baseball tee/baseball tee/jbib_001_u.ydd", "baseball tee/baseball tee", "jbib_diff_001", "_d.tga", "_n.tgn"),
            "uf": ("baseball tee/baseball tee/jbib_001_u.ydd", "baseball tee/baseball tee", "jbib_diff_001", "_d.tga", "_n.tgn"),
        },
    ),
    "tech": dict(
        source="cmcoa_utrack01", item="track jacket", variant="Pattern A",
        meshes={
            "c": ("niketec/NikeTech/Zipped/Models/jbib_001_u.ydd", "niketec/NikeTech/Zipped/Textures", "jbib_diff_007",
                  "_d.tga", "_n.tgn"),
            "o": ("niketec/NikeTech/Unzipped/Models/jbib_003_u.ydd", "niketec/NikeTech/Unzipped/Textures", "jbib_diff_007",
                  "_do.tga", "_no.tgn", (0.5, 0, 1, 1)),
        },
    ),
}

TOPS = [
    dict(name="Lead Never Follow Baseball Tee", base="cmuns_ubbtee001", group="baseball", colour="a"),
    dict(name="Red Sleeve Baseball Tee", base="cmuns_ubbtee002", group="baseball", colour="b"),
    dict(name="Cross Baseball Tee", base="cmuns_ubbtee003", group="baseball", colour="c"),
    dict(name="Camo Sleeve Baseball Tee", base="cmuns_ubbtee004", group="baseball", colour="f"),
    dict(name="Nike Tech Black", base="cmcoa_utech001", group="tech", colour="a"),
    dict(name="Nike Tech Grey", base="cmcoa_utech002", group="tech", colour="c"),
    dict(name="Nike Tech Blue", base="cmcoa_utech003", group="tech", colour="e"),
    dict(name="Nike Tech Green", base="cmcoa_utech004", group="tech", colour="h"),
    dict(name="Nike Tech Grey Red", base="cmcoa_utech005", group="tech", colour="j"),
]
