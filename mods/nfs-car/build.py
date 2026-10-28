"""Put a Need for Speed Most Wanted (2005) car on a Saints Row 2 car.

The NFS car's stock body (kit 00, top detail level "_A") goes in whole: body, interior, windows and
lights. Wheels, brakes, the driver, damage variants and decals are left out; the SR2 car keeps its
own wheels, collision, damage and handling (tools/sr2/carport.py writes the SR2 files).

Textures come from the car's TEXTURES.BIN and the shared GLOBAL\\GLOBALB.BUN (geometry refers to
them by name hash, tools/nfsmw). They are packed into one atlas that replaces the SR2 car's texture:
- paint: the body skin (white, so SR2's paint colour shows) and the door lines over white,
- detail: chrome, trim, carbon, underside, window masks, lights (flat colours: the light textures
  are EA-HUFF compressed and stored per car under other names),
- interior, and glass (the SR2 car's see-through glass, no texture).
Badges and the number plate are left out: their transparency would show as solid rectangles.

Placement: NFS (x forward, y left, z up, driver at +y) becomes SR2 (x = -y, y = z, z = x), scaled by
SCALE and centred on the SR2 car's wheelbase at its wheel height. The SR2 car's wheels then move
to the NFS car's wheel arches (carport.move_wheels).

    python build.py      # writes out/STILWATER - <name>/
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
TOOLS = HERE.parent.parent / "tools"
for sub in ("sr2", "mesh", "nfsmw"):
    sys.path.insert(0, str(TOOLS / sub))
import carport  # noqa: E402
import geometry  # noqa: E402
import tpk  # noqa: E402

GAME = Path(r"E:\SteamLibrary\steamapps\common\Saints Row 2")
NFS = Path(r"D:\GAMEZ\Need For Speed Most Wanted Black Edition")
CAR = "BMWM3GTR"
SR2_CAR = "car_4dr_sports01"        # the Voxel
SR2_ATLAS = "car_4dr_sports01d.tga"
MOD_NAME = "STILWATER - M3 GTR"

# Wheel-arch centres (circles fitted to the arch edges of the NFS body: x, the wheel centre height
# z) and half the track.
NFS_WHEELS = dict(front_x=1.602, rear_x=-1.151, height=0.18, track=0.76)
# The SR2 car's wheel centres (x, y, z), front left/right then rear left/right.
SR2_WHEELS = [(-0.741, -0.316, 1.29), (0.741, -0.316, 1.29), (-0.74, -0.316, -1.30), (0.741, -0.316, -1.30)]
# NFS metres to SR2 units: SR2's cars run larger than life (the Voxel is 4.66 m long).
SCALE = 1.10
# The SR2 car's seats (and the feet positions that go with them) move down by this much, so the
# occupants' heads clear the NFS car's lower roof.
SEAT_DROP = 0.05
SEATS = ("driver", "passenger", "front_passenger", "driveby_shooter")

# Solids making up the stock car (top detail level).
PARTS = ("_KIT00_BODY_A", "_KIT00_INTERIOR_A", "_WINDOW_A", "_HEADLIGHT_A", "_HEADLIGHT_GLASS_A",
         "_BRAKELIGHT_A")
FLAT = {"white": (255, 255, 255), "light": (205, 205, 210), "brakelight": (150, 18, 18)}
SKIP_TEXTURES = {f"{CAR}_BADGING", "LICENSEPLATE"}

MATERIAL = {"paint": 0, "detail": 3, "interior": 3, "glass": 23}
# NFS bodies are single sheets. Glass shows from inside and out; the body and trim get a back side
# because the game's shadows only come from one side of a sheet: without it light passes through
# the body and the interior shell's window frames throw bars of shadow onto the outside.
DOUBLE_SIDED = {"glass", "paint", "detail"}
# Part 0 is what the game draws up close; part 1 is the low-detail model it swaps to at a distance
# (it uses its own materials, 11-21, in the original car). Doors, hood and bumpers are separate
# parts in their own local space and stay collapsed.
LAYOUT = {0: ["paint", "detail", "interior", "glass"], 1: ["paint", "detail", "glass"]}
PADDING = 4


def classify(material, texture):
    """(class, atlas cell) for one NFS material, or None to leave it out."""
    if texture in SKIP_TEXTURES:
        return None
    if texture == f"{CAR}_SKIN1":
        return "paint", "white"
    if texture == "DOORLINE":
        return "paint", "DOORLINE"
    if material.startswith("WINDOW_") and not material.endswith("_MASK") or "HEADLIGHT_GLASS" in (texture or ""):
        return "glass", None
    if "BRAKELIGHT" in material:
        return "detail", "brakelight"
    if "HEADLIGHT" in material:
        return "detail", "light"
    if texture == f"{CAR}_INTERIOR":
        return "interior", texture
    if texture is None:
        raise ValueError(f"no texture found for material {material}")
    return "detail", texture


def load_textures():
    found = {}
    for path in (NFS / "GLOBAL" / "GLOBALB.BUN", NFS / "CARS" / CAR / "TEXTURES.BIN"):
        textures, _ = tpk.textures(path)
        found.update(textures)
    return found


def cell_images(cells, textures):
    """{cell name: RGB image} for the cells in use."""
    by_name = {t["name"]: t for t in textures.values()}
    out = {}
    for name in cells:
        if name in FLAT:
            out[name] = Image.new("RGB", (16, 16), FLAT[name])
            continue
        image = tpk.to_image(by_name[name])
        if name == "DOORLINE":
            # Door seams drawn with paint: the line over white, so the paint colour tints the rest.
            white = Image.new("RGBA", image.size, (255, 255, 255, 255))
            image = Image.alpha_composite(white, image)
        out[name] = image.convert("RGB")
    return out


def pack(images):
    """Shelf-pack the cells; returns (atlas, {name: (x, y, w, h)})."""
    order = sorted(images, key=lambda n: (-images[n].size[1], -images[n].size[0]))
    for size in (1024, 2048):
        rects, x, y, shelf = {}, 0, 0, 0
        for name in order:
            w, h = images[name].size
            if x + w + 2 * PADDING > size:
                x, y, shelf = 0, y + shelf, 0
            rects[name] = (x + PADDING, y + PADDING, w, h)
            x += w + 2 * PADDING
            shelf = max(shelf, h + 2 * PADDING)
        if y + shelf <= size:
            break
    else:
        raise ValueError("textures don't fit a 2048 atlas")
    atlas = Image.new("RGB", (size, size), (128, 128, 128))
    for name, (x, y, w, h) in rects.items():
        image = images[name]
        # Repeat the edge into the padding so filtering at the cell border doesn't pick up neighbours.
        padded = image.resize((w + 2 * PADDING, h + 2 * PADDING), Image.NEAREST)
        padded.paste(image, (PADDING, PADDING))
        atlas.paste(padded, (x - PADDING, y - PADDING))
    return atlas, rects


def placement():
    """(dy, dz): SR2 = NFS * SCALE + shift; the wheelbase centred where the SR2 car's is."""
    sr2_mid = (SR2_WHEELS[0][2] + SR2_WHEELS[2][2]) / 2
    nfs_mid = (NFS_WHEELS["front_x"] + NFS_WHEELS["rear_x"]) / 2
    return SR2_WHEELS[0][1] - NFS_WHEELS["height"] * SCALE, sr2_mid - nfs_mid * SCALE


def wheel_moves():
    """[(SR2 wheel centre, new centre)]: the SR2 wheels into the NFS car's arches."""
    dy, dz = placement()
    front = NFS_WHEELS["front_x"] * SCALE + dz
    rear = NFS_WHEELS["rear_x"] * SCALE + dz
    track = NFS_WHEELS["track"] * SCALE
    new = [(-track, SR2_WHEELS[0][1], front), (track, SR2_WHEELS[0][1], front),
           (-track, SR2_WHEELS[0][1], rear), (track, SR2_WHEELS[0][1], rear)]
    return list(zip(SR2_WHEELS, new))


def to_sr2(positions, normals):
    dy, dz = placement()
    p = np.stack([-positions[:, 1], positions[:, 2], positions[:, 0]], axis=1) * SCALE + [0, dy, dz]
    n = np.stack([-normals[:, 1], normals[:, 2], normals[:, 0]], axis=1)
    return p, n


def nfs_geometry(texture_names):
    """[(class, cell, positions, normals, uvs, triangles)] in SR2 car space."""
    out = []
    for solid in geometry.read(NFS / "CARS" / CAR / "GEOMETRY.BIN"):
        name = solid["name"]
        if not name.endswith(PARTS) or "DAMAGE" in name or "DECAL" in name:
            continue
        v = solid["vertices"]
        positions, normals = to_sr2(v["pos"].astype(float), v["normal"].astype(float))
        for m in solid["materials"]:
            texture = texture_names.get(solid["textures"][m["texture_slots"][0]])
            kind = classify(m.get("name", ""), texture)
            if kind is None:
                continue
            tris = geometry.triangles(solid, m)
            used = np.unique(tris)
            remap = np.zeros(len(v), dtype=int)
            remap[used] = np.arange(len(used))
            out.append((kind[0], kind[1], positions[used], normals[used], v["uv"][used].astype(float), remap[tris]))
    return out


def atlas_uvs(uv, rect, atlas_size, flat):
    x, y, w, h = rect
    if flat:
        u = np.full(len(uv), x + w / 2)
        v = np.full(len(uv), y + h / 2)
    else:
        u = x + np.clip(uv[:, 0], 0, 1) * (w - 1) + 0.5
        v = y + np.clip(uv[:, 1], 0, 1) * (h - 1) + 0.5
    return np.stack([u, v], axis=1) / atlas_size


def main():
    textures = load_textures()
    names = {h: t["name"] for h, t in textures.items()}
    for n in ("HEADLIGHT_LEFT", "HEADLIGHT_RIGHT", "BRAKELIGHT_LEFT", "BRAKELIGHT_RIGHT",
              "HEADLIGHT_GLASS_LEFT", "HEADLIGHT_GLASS_RIGHT", f"{CAR}_SKIN1"):
        names.setdefault(tpk.bin_hash(n), n)
    pieces = nfs_geometry(names)
    cells = sorted({cell for _, cell, *_ in pieces if cell})
    atlas, rects = pack(cell_images(cells, textures))
    size = atlas.size[0]
    print(f"atlas {size}x{size}: {', '.join(cells)}")

    groups = {}
    for cls, cell, p, n, uv, t in pieces:
        uv = None if cell is None else atlas_uvs(uv, rects[cell], size, cell in FLAT)
        groups.setdefault(cls, []).append((p, n, uv, carport.orient(p, n, t)))
    merged = {}
    for cls, items in groups.items():
        offset, P, N, U, T = 0, [], [], [], []
        for p, n, uv, t in items:
            P.append(p)
            N.append(n)
            U.append(uv)
            T.append(t + offset)
            offset += len(p)
        U = None if U[0] is None else np.vstack(U)
        P, N, T = np.vstack(P), np.vstack(N), np.vstack(T)
        if cls in DOUBLE_SIDED:
            P, N, U, T = carport.double_sided(P, N, U, T)
        merged[cls] = (P, N, U, T)
        print(f"{cls}: {len(P)} vertices, {len(T)} triangles")

    out = HERE / "out" / MOD_NAME
    out.mkdir(parents=True, exist_ok=True)
    atlas.save(HERE / "out" / "atlas.png")
    carport.port(GAME, SR2_CAR, SR2_ATLAS, merged, MATERIAL, LAYOUT, atlas, out, HERE / "original")
    moves = wheel_moves()
    for old, new in moves:
        print(f"wheel {old} -> ({new[0]:.3f}, {new[1]:.3f}, {new[2]:.3f})")
    carport.move_wheels(GAME, SR2_CAR, out, moves)
    print("seats lowered:", ", ".join(carport.move_nodes(out, SR2_CAR, SEATS, (0, -SEAT_DROP, 0))))


if __name__ == "__main__":
    main()
