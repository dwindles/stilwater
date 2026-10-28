"""HOQ Uptempo: the Nike Air More Uptempo on SR2's sports shoes with strap (cmSho_uSporSho01).

From a scanned Uptempo (a binary FBX of one shoe and its diffuse texture):

1. The scan is put in SR2's shoe frame (toe +z, up +y, the feet either side of x = 0) and stretched
   to the box of each game shoe, mirrored for the other foot; which of the two mirror images goes
   on which foot is the one that fits the game shoe best. FBX is right-handed and SR2 left-handed
   (x right, y up, z forward: a car's driver seat is at -x), so the frame change includes a
   reflection and the unmirrored scan is the real shoe.
2. The game shoe's vertices are pulled onto the scan's surface (shrink-wrap), with the moves
   smoothed so the mesh doesn't crumple. Vertex and triangle counts stay the same, so the shoe
   keeps its skinning and morphs (body shape sliders) and takes the Uptempo's chunky shape.
   Normals are recomputed.
3. The scan's texture is baked onto the game shoe's UVs: each texel's point on the wrapped shoe
   takes the colour of the nearest point of the scan facing the same way. The game's feet share
   their UVs (one is the other's mirror image), which would show the AIR lettering backwards on
   one shoe, so each foot gets its own half of the texture (the UVs are squeezed into it), and on
   the mirrored foot the two big side panels are read back to front along the shoe, which turns
   the mirrored lettering the right way round (a real pair reads the same on its right-facing
   sides, A at the heel, and on its left-facing sides, A at the toe).

The texture pack keeps its exact vanilla size (clothing streams into fixed slots): sizes and mip
counts are picked to add up to it. The tint mask is one region, so the shoe shows its own colours
under the default white (mods/shared).

    python build.py [game folder] [scan folder]     # writes out/STILWATER - HOQ Uptempo/
"""
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
import bake  # noqa: E402
import clothing  # noqa: E402
import cmesh  # noqa: E402
import fbx  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402

MESH = PACK = "cmsho_usporsho01"
DIFFUSE, BUMP, TINT = f"{PACK}_d.tga", f"{PACK}_n.tgn", f"{PACK}_p1.tga"
MOD_NAME = "STILWATER - HOQ Uptempo"
SCAN_FBX = "source/Nike air uptempo.fbx"
SCAN_TEXTURE = "textures/Shoe_Diffuse.png"

SAMPLES = 400_000          # points sampled on the scan's surface for nearest-point lookups
MAX_MOVE = 0.035           # metres a game vertex may move onto the scan
SMOOTH = 4                 # passes of smoothing over the moves
WORK = 1024                # bake resolution (downsampled to the diffuse size)
BRIGHTNESS = 1.15          # the scan's texture is a little dark under the game's lighting


def scan_frame(root, positions):
    """The 3x3 matrix taking the scan into SR2's shoe frame (before stretching): its model rotation
    applied, then the length along z with the toe (the lower end) at +z, up +y."""
    model = next(m for m in root.find("Objects").find_all("Model")
                 if any(p.props[0] == b"Lcl Rotation" for p in m.find("Properties70").children))
    rx, ry, rz = next(p.props[4:7] for p in model.find("Properties70").children if p.props[0] == b"Lcl Rotation")

    def rot(axis, degrees):
        a = np.radians(degrees)
        c, s = np.cos(a), np.sin(a)
        return np.array({"x": [[1, 0, 0], [0, c, -s], [0, s, c]], "y": [[c, 0, s], [0, 1, 0], [-s, 0, c]],
                         "z": [[c, -s, 0], [s, c, 0], [0, 0, 1]]}[axis])

    # FBX's default rotation order (XYZ): x first.
    rotation = rot("z", rz) @ rot("y", ry) @ rot("x", rx)
    p = positions @ rotation.T
    extent = p.max(axis=0) - p.min(axis=0)
    length = 0 if extent[0] >= extent[2] else 2
    axes = np.zeros((3, 3))
    axes[0, 2 - length], axes[1, 1], axes[2, length] = 1, 1, 1
    matrix = axes @ rotation
    if np.linalg.det(matrix) > 0:
        matrix = np.diag([-1, 1, 1]) @ matrix      # right-handed FBX to left-handed SR2
    out = positions @ matrix.T
    # The heel end is the taller one.
    z0, z1 = out[:, 2].min(), out[:, 2].max()
    front = out[out[:, 2] > z1 - 0.2 * (z1 - z0), 1].max()
    back = out[out[:, 2] < z0 + 0.2 * (z1 - z0), 1].max()
    if front > back:
        matrix = np.diag([-1, 1, -1]) @ matrix     # turn around (keeps the handedness)
    return matrix


def fit_box(points, target):
    """(points stretched to the bounding box of target per axis, the per-axis scale)."""
    lo, hi = points.min(axis=0), points.max(axis=0)
    tlo, thi = target.min(axis=0), target.max(axis=0)
    scale = (thi - tlo) / (hi - lo)
    return tlo + (points - lo) * scale, scale


def side_panels(shoe, positions, corner_normals):
    """(panel index or -1 per scan triangle, [UV direction along the shoe per panel]) for the scan's
    big side panels: its UV islands of over a tenth of the surface facing +-x."""
    vertex, uv, triangles = shoe["corner_vertex"], shoe["corner_uv"], shoe["triangles"]
    _, corner_id = np.unique(np.round(np.column_stack([vertex, uv * 4096])), axis=0, return_inverse=True)
    corner_id = corner_id.reshape(-1)
    edges = np.concatenate([corner_id[triangles[:, [0, 1]]], corner_id[triangles[:, [1, 2]]]])
    count = corner_id.max() + 1
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(count, count))
    island = connected_components(graph, directed=False)[1][corner_id[triangles[:, 0]]]
    p = positions[vertex[triangles]]
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    facing = corner_normals[triangles].mean(axis=1)[:, 0]

    panel = np.full(len(triangles), -1)
    directions = []
    for i in np.unique(island):
        s = island == i
        if area[s].sum() < 0.1 * area.sum() or abs((facing[s] * area[s]).sum() / area[s].sum()) < 0.8:
            continue
        uvs = uv[triangles[s]].reshape(-1, 2)
        z = p[s][..., 2].reshape(-1)
        d = np.array([np.polyfit(z, uvs[:, k], 1)[0] for k in (0, 1)])
        panel[s] = len(directions)
        directions.append(d / np.linalg.norm(d))
    return panel, directions


def back_to_front(uvs, along, bins=48):
    """UVs of one side panel read back to front along the shoe, within the panel's outline: the
    position along the panel is mirrored and the height kept as a fraction of the panel's height
    there (the panel is taller at the heel than at the toe)."""
    across = np.array([-along[1], along[0]])
    a, b = uvs @ along, uvs @ across
    lo, hi = np.percentile(a, [0.5, 99.5])
    edges = np.linspace(lo, hi, bins + 1)
    centres = (edges[:-1] + edges[1:]) / 2
    k = np.clip(np.digitize(a, edges) - 1, 0, bins - 1)
    bottom, top = (np.array([np.percentile(b[k == i], q) if (k == i).sum() > 20 else np.nan for i in range(bins)])
                   for q in (1, 99))
    known = ~np.isnan(bottom)
    bottom, top = (np.interp(centres, centres[known], v[known]) for v in (bottom, top))

    def outline(x):
        return np.interp(x, centres, bottom), np.interp(x, centres, top)

    flipped = lo + hi - a
    b0, b1 = outline(a)
    f0, f1 = outline(flipped)
    height = (b - b0) / np.maximum(b1 - b0, 1e-6)
    return flipped[:, None] * along + (f0 + height * (f1 - f0))[:, None] * across


def chamfer(a, b):
    return cKDTree(b).query(a)[0].mean() + cKDTree(a).query(b)[0].mean()


def weld(positions):
    """(unique index per vertex, unique positions): UV seams split vertices that must move together."""
    keys = np.round(positions, 5)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return inverse.reshape(-1), positions[first]


def vertex_normals(positions, triangles):
    n = np.zeros_like(positions)
    face = np.cross(positions[triangles[:, 1]] - positions[triangles[:, 0]],
                    positions[triangles[:, 2]] - positions[triangles[:, 0]])
    for k in range(3):
        np.add.at(n, triangles[:, k], face)
    return n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


def wrap(positions, triangles, normals, scan_points, scan_normals):
    """Game vertices pulled onto the scan surface (nearest scan point facing the same way)."""
    ids, unique = weld(positions)
    welded = ids[triangles]
    unique_normals = np.zeros_like(unique)
    np.add.at(unique_normals, ids, normals)
    unique_normals /= np.linalg.norm(unique_normals, axis=1, keepdims=True) + 1e-12

    tree = cKDTree(scan_points)
    dist, near = tree.query(unique, k=16)
    facing = (scan_normals[near] * unique_normals[:, None, :]).sum(axis=2) > 0.2
    choice = np.where(facing.any(axis=1), facing.argmax(axis=1), 0)
    target = scan_points[near[np.arange(len(unique)), choice]]
    move = target - unique
    length = np.linalg.norm(move, axis=1, keepdims=True)
    move *= np.minimum(1, MAX_MOVE / (length + 1e-12))

    neighbours = [set() for _ in range(len(unique))]
    for a, b, c in welded:
        neighbours[a] |= {b, c}
        neighbours[b] |= {a, c}
        neighbours[c] |= {a, b}
    neighbours = [np.array(sorted(n)) for n in neighbours]
    for _ in range(SMOOTH):
        move = 0.5 * move + 0.5 * np.array([move[n].mean(axis=0) if len(n) else move[i]
                                            for i, n in enumerate(neighbours)])
    moved = unique + move
    new_normals = vertex_normals(moved, welded)
    # Keep the game's facing (its winding isn't consistent across the two feet's strips).
    flip = (new_normals * unique_normals).sum(axis=1) < 0
    new_normals[flip] *= -1
    return moved[ids], new_normals[ids]


def bake_foot(game_mesh, positions, normals, foot, scan_points, scan_uvs, scan_normals, texture):
    triangles = game_mesh["triangles"][(np.sign(game_mesh["positions"][game_mesh["triangles"]][..., 0]) == foot).all(axis=1)]
    rows, cols, tris, w = bake.rasterize(game_mesh["uvs"], triangles, WORK)
    corners = triangles[tris]
    points = (w[..., None] * positions[corners]).sum(axis=1)
    point_normals = (w[..., None] * normals[corners]).sum(axis=1)
    point_normals /= np.linalg.norm(point_normals, axis=1, keepdims=True) + 1e-12
    _, near = cKDTree(scan_points).query(points, k=12)
    facing = (scan_normals[near] * point_normals[:, None, :]).sum(axis=2) > 0
    choice = np.where(facing.any(axis=1), facing.argmax(axis=1), 0)
    colours = bake.bilinear(texture, scan_uvs[near[np.arange(len(points)), choice]])
    image = np.zeros((WORK, WORK, 3))
    covered = np.zeros((WORK, WORK), bool)
    image[rows, cols] = colours
    covered[rows, cols] = True
    return bake.dilate(image, covered), covered


def main(game, scan):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes, pegs, textures = (vpp.Packfile(game / f) for f in ("meshes.vpp_pc", "pegs.vpp_pc", "textures.vpp_pc"))
    for ext in ("cmesh_pc", "g_cmesh_pc"):
        (original / f"{MESH}.{ext}").write_bytes(meshes.read(f"{MESH}.{ext}"))
    (original / f"{PACK}.peg_pc").write_bytes(pegs.read(f"{PACK}.peg_pc"))
    (original / f"{PACK}.g_peg_pc").write_bytes(textures.read(f"{PACK}.g_peg_pc"))
    game_mesh = cmesh.load(original / f"{MESH}.cmesh_pc", original / f"{MESH}.g_cmesh_pc")

    root = fbx.read(scan / SCAN_FBX)
    shoe = fbx.meshes(scan / SCAN_FBX)[0]
    matrix = scan_frame(root, shoe["positions"])
    base = shoe["positions"] @ matrix.T
    base_normals = shoe["corner_normal"] @ matrix.T
    corners = shoe["corner_vertex"]

    positions, normals = game_mesh["positions"].copy(), game_mesh["normals"].copy()
    side_of = np.sign(game_mesh["positions"][:, 0])
    # Which handedness goes on the +x foot: the one that fits it best.
    fits = {}
    for mirror in (1, -1):
        p = base * [mirror, 1, 1]
        fits[mirror] = chamfer(fit_box(p, game_mesh["positions"][side_of > 0])[0], game_mesh["positions"][side_of > 0])
    plus = min(fits, key=fits.get)
    print(f"   scan fits the +x foot {'as is' if plus == 1 else 'mirrored'} (chamfer {fits[1]:.4f} / {fits[-1]:.4f})")

    panel, directions = side_panels(shoe, base, base_normals)
    print(f"   {len(directions)} side panels in the scan")
    texture = np.asarray(Image.open(scan / SCAN_TEXTURE).convert("RGB")).astype(float) / 255
    bakes = {}
    for foot in (1, -1):
        mirror = plus * foot
        on_foot = side_of == foot
        p, scale = fit_box(base * [mirror, 1, 1], game_mesh["positions"][on_foot])
        p = p[corners]
        # Normals take the mirror and the inverse of the stretch.
        n = base_normals * [mirror, 1, 1] / scale
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        points, uvs, scan_normals, triangle = bake.sample_surface(p, shoe["triangles"], shoe["corner_uv"], n, SAMPLES)
        if mirror < 0:
            # Read the side panels back to front along the shoe (see the top).
            for k, along in enumerate(directions):
                s = panel[triangle] == k
                uvs[s] = back_to_front(uvs[s], along)
        foot_tris = game_mesh["triangles"][on_foot[game_mesh["triangles"]].all(axis=1)]
        used = np.unique(foot_tris)
        local = np.full(len(positions), -1)
        local[used] = np.arange(len(used))
        new_p, new_n = wrap(positions[used], local[foot_tris], normals[used], points, scan_normals)
        moved = np.linalg.norm(new_p - positions[used], axis=1)
        positions[used], normals[used] = new_p, new_n
        print(f"   foot {foot:+d}: {len(used)} vertices, moved {100 * moved.mean():.1f} cm on average, "
              f"up to {100 * moved.max():.1f} cm")
        colour, covered = bake_foot(game_mesh, positions, normals, foot, points, uvs, scan_normals, texture)
        bakes[foot] = Image.fromarray((np.clip(colour * BRIGHTNESS, 0, 1) * 255).astype(np.uint8))
        print(f"   foot {foot:+d}: {100 * covered.mean():.0f}% of its texture baked")

    # Positions, normals, and each foot's UVs squeezed into its half of the texture (+x foot left).
    data = bytearray((original / f"{MESH}.g_cmesh_pc").read_bytes())
    stride = game_mesh["stride"]
    for i, (p, n) in enumerate(zip(positions, normals)):
        at = i * stride
        struct.pack_into("<3f", data, at, *p)
        data[at + 20:at + 23] = bytes(np.clip(np.round((n + 1) * 127.5), 0, 255).astype(np.uint8))
        u, = struct.unpack_from("<h", data, at + 28)
        struct.pack_into("<h", data, at + 28, round((u + (0 if side_of[i] > 0 else 1024)) / 2))

    header = peg.read_header(original / f"{PACK}.peg_pc")
    vanilla_data = (original / f"{PACK}.g_peg_pc").read_bytes()
    sizes = clothing.fit_sizes([e["name"] for e in header], len(vanilla_data),
                               {DIFFUSE: "diffuse", BUMP: "bump", TINT: "tint"})
    (dw, dh, dl), (bw, bh, bl), (tw, th, tl) = sizes[DIFFUSE], sizes[BUMP], sizes[TINT]

    def halves(make, width, height):
        image = Image.new(make(bakes[1], width // 2, height).mode, (width, height))
        image.paste(make(bakes[1], width // 2, height), (0, 0))
        image.paste(make(bakes[-1], width // 2, height), (width // 2, 0))
        return image

    def bump_half(baked, width, height):
        # The clothing "normal" map is a grey bump map: the scan's fine detail (stitching, the AIR
        # lettering's raised edges) from its brightness, high-passed.
        grey = np.asarray(baked.convert("L").resize((width, height), Image.LANCZOS)).astype(float)
        blurred = np.asarray(Image.fromarray(grey.astype(np.uint8)).resize((width // 8, height // 8), Image.BILINEAR)
                             .resize((width, height), Image.BICUBIC)).astype(float)
        return Image.fromarray(np.clip(128 + 0.6 * (grey - blurred), 0, 255).astype(np.uint8))

    out = HERE / "out"
    out.mkdir(exist_ok=True)
    diffuse_image = halves(lambda baked, w, h: baked.resize((w, h), Image.LANCZOS), dw, dh)
    diffuse_image.save(out / "hoq_uptempo_diffuse.png")
    diffuse, _ = peg.encode(diffuse_image, "DXT1", max_levels=dl)
    bump, _ = peg.encode(halves(bump_half, bw, bh).convert("RGBA"), "DXT5", max_levels=bl)
    # One tint region (blue), so the colour picker's first colour (white by default) tints it all.
    tint, _ = peg.encode(Image.new("RGB", (tw, th), (0, 0, 255)), "DXT1", max_levels=tl)
    replacements = {DIFFUSE: (dw, dh, clothing.DXT1, dl, diffuse), BUMP: (bw, bh, clothing.DXT5, bl, bump),
                    TINT: (tw, th, clothing.DXT1, tl, tint)}

    folder = out / MOD_NAME
    folder.mkdir(exist_ok=True)
    peg_header, pack = peg.rebuild(original / f"{PACK}.peg_pc", original / f"{PACK}.g_peg_pc", replacements)
    assert len(pack) == len(vanilla_data), (len(pack), len(vanilla_data))
    (folder / f"{PACK}.peg_pc").write_bytes(peg_header)
    (folder / f"{PACK}.g_peg_pc").write_bytes(pack)
    (folder / f"{MESH}.cmesh_pc").write_bytes((original / f"{MESH}.cmesh_pc").read_bytes())
    (folder / f"{MESH}.g_cmesh_pc").write_bytes(bytes(data))
    print(f"built {folder}: diffuse {dw}x{dh} ({dl} mips), bump {bw}x{bh} ({bl}), tint {tw}x{th} ({tl})")
    return game_mesh, positions


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\uptempo"))
