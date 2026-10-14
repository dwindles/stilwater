"""Put a GTA V car model (from a FiveM resource) on a Saints Row 2 car.

The GTA model goes in whole (every triangle, its own normals) as the SR2 car's two main shell
parts, which grow to fit; every other body part of the SR2 car is collapsed to a point. SR2's
wheels (separate rim models), collision, damage and handling stay, so the GTA car drives like the
SR2 one. Textures: the GTA car's main textures are packed into one atlas that replaces the SR2
car's own atlas, and each vertex's UVs are moved into its quarter of it.

Placement: GTA (x right, y forward, z up) becomes SR2 (x, z, y): both put the driver at -x and
the SR2 car faces +z. The model is scaled and shifted so its wheel bones land on the SR2 rig's
wheel positions. Materials are the SR2 car's own (paint follows the in-game colour picker and
multiplies the GTA livery, so white paint shows the livery as painted).

Writing the SR2 car (growth, damage data, submesh tables) is tools/sr2/carport.py.

    python build.py      # writes out/STILWATER - <name>/
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
TOOLS = HERE.parent.parent / "tools"
for sub in ("sr2", "gta5", "mesh"):
    sys.path.insert(0, str(TOOLS / sub))
import carport  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402

GAME = Path(r"E:\SteamLibrary\steamapps\common\Saints Row 2")
GTA_STREAM = Path(r"D:\GTA RELATED THINGS\GTASERVER\txData\CFXDefaultFiveM_11E1FE.base\resources\[cars]"
                  r"\HondaCivic\stream")
GTA_MODEL = GTA_STREAM / "HondaCivic.yft"
GTA_TEXTURES = GTA_STREAM / "HondaCivic.ytd"
SR2_CAR = "car_4dr_sports01"        # the Voxel
SR2_ATLAS = "car_4dr_sports01d.tga"
MOD_NAME = "STILWATER - Civic"

# GTA wheel bones (front/rear, from the .yft skeleton) and SR2 rig wheel centres.
GTA_WHEELS = dict(front_y=1.201, rear_y=-1.413, height=0.111)
SR2_WHEELS = dict(front_z=1.29, rear_z=-1.30, height=-0.316)

# Classes by the GTA shader's diffuse texture; anything unlisted is "detail".
TEXTURE_CLASS = {
    "honda_civic_r3_external": "paint",
    "honda_civic_r3_external_dynamic": "detail",
    "honda_civic_r3_internal": "interior",
    "honda_civic_r3_internal_transparent": "interior",
    "script_rt_dials_sultan": "interior",
    "citroen_c3_wrc17_internal": "cage",
    "honda_civic_r3_external_transparent": "glass",
    "vehicle_generic_tyrewallblack": None,     # tyres: SR2 keeps its own wheels
    "disk": None,
    "207_2012_external_dynamic": None,
    "vehicle_genericmud_car": None,            # number plate
}
# Atlas quarter (column, row) holding each class's texture; None = no texture (plain material).
ATLAS = {"paint": ((0, 0), "Honda_Civic_R3_external"),
         "detail": ((1, 0), "Honda_Civic_R3_external_dynamic"),
         "interior": ((0, 1), "Honda_Civic_R3_internal"),
         "cage": ((1, 1), "Citroen_C3_WRC17_internal"),
         "glass": (None, None)}
ATLAS_SIZE = 2048
# SR2 material per class: 0 paint, 3 interior (draws its texture as-is), 23 the Voxel's tinted
# window glass (see-through; the glass is double-sided so it shows from inside and out).
MATERIAL = {"paint": 0, "detail": 3, "interior": 3, "cage": 3, "glass": 23}
LAYOUT = {0: ["paint"], 1: ["detail", "interior", "cage", "glass"]}
DOUBLE_SIDED = {"glass"}


def shader_textures(res, drawable):
    """Diffuse texture name of each shader in the drawable's shader group (lower case)."""
    group = res.u64(drawable, 0x10)
    shaders, count = res.unpack("<QH", group, 0x10)
    names = []
    for i in range(count):
        shader = res.u64(shaders, 8 * i)
        params, = res.unpack("<Q", shader, 0x00)
        n, = res.unpack("<B", shader, 0x10)
        name = None
        for k in range(n):
            kind, = res.unpack("<B", params, 16 * k)
            pointer, = res.unpack("<Q", params, 16 * k + 8)
            if kind == 0 and pointer:
                buf, off = res.at(res.u64(pointer, 0x28))
                name = buf[off:buf.index(b"\0", off)].decode("latin-1").lower()
                break
        names.append(name)
    return names


def gta_geometry():
    """{class: (positions, normals, uvs, triangles)} in SR2 car space, the model as authored."""
    frag = yft.read_fragment(GTA_MODEL)
    textures = shader_textures(frag["resource"], frag["drawable"])

    scale = (SR2_WHEELS["front_z"] - SR2_WHEELS["rear_z"]) / (GTA_WHEELS["front_y"] - GTA_WHEELS["rear_y"])
    dz = SR2_WHEELS["front_z"] - GTA_WHEELS["front_y"] * scale
    dy = SR2_WHEELS["height"] - GTA_WHEELS["height"] * scale

    pieces = {}
    for model in frag["lods"]["high"]:
        for geo in model["geometries"]:
            cls = TEXTURE_CLASS.get(textures[geo["shader"]], "detail")
            if cls is None or not len(geo["triangles"]):
                continue
            p = geo["positions"][:, :3]
            sr2 = np.stack([p[:, 0], p[:, 2], p[:, 1]], axis=1) * scale + [0, dy, dz]
            tris = geo["triangles"].astype(int)
            n = geo["normals"][:, :3]
            n = np.stack([n[:, 0], n[:, 2], n[:, 1]], axis=1)
            tris = carport.orient(sr2, n, tris)
            uv = geo["uvs"][:, :2] if "uvs" in geo else np.zeros((len(p), 2))
            pieces.setdefault(cls, []).append((sr2, n, uv, tris))

    out = {}
    for cls, items in pieces.items():
        offset, P, N, U, T = 0, [], [], [], []
        for p, n, uv, t in items:
            P.append(p)
            N.append(n)
            U.append(uv)
            T.append(t + offset)
            offset += len(p)
        P, N, U, T = np.vstack(P), np.vstack(N), np.vstack(U), np.vstack(T)
        if cls in DOUBLE_SIDED:
            # One sheet in GTA; SR2 culls back faces.
            P, N, U, T = carport.double_sided(P, N, U, T)
        out[cls] = (P, N, U, T)
    return out


def build_atlas():
    """The SR2 car's new atlas: each class's GTA texture in its quarter."""
    found = ytd.textures(GTA_TEXTURES)
    by_name = {name.lower(): value for name, value in found.items()}
    half = ATLAS_SIZE // 2
    atlas = Image.new("RGB", (ATLAS_SIZE, ATLAS_SIZE), (128, 128, 128))
    for cls, (cell, name) in ATLAS.items():
        if cell is None:
            continue
        w, h, fmt, levels, buf, off = by_name[name.lower()]
        image = ytd.to_image(w, h, fmt, buf, off).convert("RGB").resize((half, half), Image.LANCZOS)
        atlas.paste(image, (cell[0] * half, cell[1] * half))
    return atlas


def atlas_uvs(cls, uv):
    """GTA UVs into the class's atlas quarter (tiled coordinates wrapped, a texel of margin)."""
    cell, _ = ATLAS[cls]
    if cell is None:
        return None
    u = np.mod(uv[:, 0], 1.0)
    v = np.mod(uv[:, 1], 1.0)
    margin = 1.0 / (ATLAS_SIZE // 2)
    u = (cell[0] + np.clip(u, margin, 1 - margin)) / 2
    v = (cell[1] + np.clip(v, margin, 1 - margin)) / 2
    return np.stack([u, v], axis=1)


def main():
    geometry = gta_geometry()
    groups = {}
    for c, (p, n, uv, t) in geometry.items():
        print(f"{c}: {len(p)} vertices, {len(t)} triangles")
        groups[c] = (p, n, atlas_uvs(c, uv), t)
    out = HERE / "out" / MOD_NAME
    atlas = build_atlas()
    out.mkdir(parents=True, exist_ok=True)
    atlas.save(HERE / "out" / "atlas.png")
    carport.port(GAME, SR2_CAR, SR2_ATLAS, groups, MATERIAL, LAYOUT, atlas, out, HERE / "original")


if __name__ == "__main__":
    main()
