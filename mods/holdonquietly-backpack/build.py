"""HOQ Realtree Backpack: a GTA V backpack (Realtree camo with "130" patches; the freemode drawable
hand_005_u.ydd with hand_diff_005_a_uni.ytd) baked onto SR2's basic backpack (cmCoa_uBackpac05_C).

The SR2 mesh keeps its shape, and with it its skinning and body-shape morphs. The GTA model is put
in SR2's frame: its outer face looks along +y, its wearer is at -y and z is up, and GTA is
right-handed, so SR2's (x right, y up, z forward) is GTA's (-x, z, -y). The SR2 body (materials 0
and 4, the front pocket) is boxed onto the GTA model's main piece and the straps (1 the shoulder
straps, 2 the lower straps, 3 their buckles) onto all its other pieces; each texel of the diffuse
takes the colour of the nearest point of that part facing the same way.

The diffuse is mapped by the first UV set, (s/1024, 1 + t/1024), which repeats: both shoulder
straps share one strip a whole texture apart, and the front pocket reuses the middle of the body's
outer face. Triangles are baked from small to big with the pocket last, so where texels are shared
the surface that shows wins. The pack keeps its vanilla size; the diffuse and bump map are
replaced and the variants' pattern and detail textures stay.

    python build.py [game folder] [model folder]     # writes out/STILWATER - HOQ Realtree Backpack/
"""
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
sys.path.insert(0, str(ROOT / "tools" / "gta5"))
import bake  # noqa: E402
import clothing  # noqa: E402
import cmesh  # noqa: E402
import simplify  # noqa: E402
import vpp  # noqa: E402
import yft  # noqa: E402
import ytd  # noqa: E402

MOD_NAME = "STILWATER - HOQ Realtree Backpack"
MESH = "cmcoa_ubackpac05_c"
DIFFUSE = "cmpac_ubackpac05_d.tga"
BUMP = "cmpac_ubackpac05_n.tgn"
GTA_MODEL = "Realtree 130 Backpack/hand_005_u.ydd"
GTA_TEXTURES = "Realtree 130 Backpack/hand_diff_005_a_uni.ytd"

GTA_TO_SR2 = np.array([[-1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float)
STRAPS = (1, 2, 3)          # SR2 materials baked from the GTA straps
POCKET = 4                  # baked last: it shares texels with the body
SAMPLES = 1_000_000
WORK = 1024
SIDES = {"diffuse": (1024, 512, 256, 128), "bump": (512, 256, 128, 64)}


def load_gta(path):
    """(positions, triangles, uvs (v from the bottom, for bake.bilinear), normals, strap) in SR2's
    frame; strap marks the triangles outside the model's largest piece."""
    geometries = [g for model in yft.read_dictionary(path)[0]["lods"]["high"] for g in model["geometries"]]
    positions, triangles, uvs, normals, base = [], [], [], [], 0
    for g in geometries:
        positions.append(g["positions"] @ GTA_TO_SR2.T)
        normals.append(g["normals"][:, :3] @ GTA_TO_SR2.T)
        # GTA's v is negative, 0 at the top of the texture.
        uvs.append(g["uvs"] * [1, -1])
        triangles.append(g["triangles"] + base)
        base += len(g["positions"])
    p, t, uv, n = (np.concatenate(x) for x in (positions, triangles, uvs, normals))
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    # Pieces: connected by shared positions.
    welded, tw, _ = simplify.weld(p, t, 1e-5)
    edges = np.vstack([tw[:, [0, 1]], tw[:, [1, 2]], tw[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])), shape=(len(welded),) * 2)
    _, piece = connected_components(graph, directed=False)
    piece = piece[tw[:, 0]]
    area = 0.5 * np.linalg.norm(np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]]), axis=1)
    body = np.bincount(piece, weights=area).argmax()
    return p, t, uv, n, piece != body


def box(points, normals, source, target):
    """Points (and normals) in source's bounding box moved to the same place in target's."""
    lo, hi = source.min(axis=0), source.max(axis=0)
    tlo, thi = target.min(axis=0), target.max(axis=0)
    scale = (thi - tlo) / (hi - lo)
    n = normals / scale
    return tlo + (points - lo) * scale, n / (np.linalg.norm(n, axis=1, keepdims=True) + 1e-12)


def bake_diffuse(mesh, uvs, gta, texture, size):
    """The GTA texture baked onto the SR2 mesh's diffuse layout: (image, covered)."""
    p, t, uv, n, strap = gta
    q, tri, materials = mesh["positions"], mesh["triangles"], mesh["materials"]
    is_strap = np.isin(materials, STRAPS)
    area = 0.5 * np.linalg.norm(np.cross(q[tri[:, 1]] - q[tri[:, 0]], q[tri[:, 2]] - q[tri[:, 0]]), axis=1)
    order = np.lexsort((area, materials == POCKET))
    rows, cols, tris, w = bake.rasterize(uvs, tri[order], size, wrap=True)
    tris = order[tris]
    # Where triangles share a texel, the last one baked keeps it.
    texel = rows * size + cols
    _, last = np.unique(texel[::-1], return_index=True)
    keep = len(texel) - 1 - last
    rows, cols, tris, w = rows[keep], cols[keep], tris[keep], w[keep]
    corners = tri[tris]
    points = (w[..., None] * q[corners]).sum(axis=1)
    normals = (w[..., None] * mesh["normals"][corners]).sum(axis=1)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12

    image = np.zeros((size, size, 3))
    covered = np.zeros((size, size), bool)
    for part in (False, True):
        mine = is_strap[tris] == part
        faces = strap == part
        samples, sample_uvs, sample_normals, _ = bake.sample_surface(
            p, t[faces], uv, n, SAMPLES // 2)
        source = q[tri[is_strap == part].ravel()]
        mapped, mapped_normals = box(points[mine], normals[mine], source, p[t[faces].ravel()])
        nearest = bake.nearest_facing(cKDTree(samples), sample_normals, mapped, mapped_normals, k=16)
        image[rows[mine], cols[mine]] = bake.bilinear(texture, sample_uvs[nearest])
        covered[rows[mine], cols[mine]] = True
    image = bake.dilate(image, covered)
    return Image.fromarray((np.clip(image, 0, 1) * 255).astype(np.uint8)), covered


def main(game, models):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    meshes = vpp.Packfile(game / "meshes.vpp_pc")
    for ext in ("cmesh_pc", "g_cmesh_pc"):
        (original / f"{MESH}.{ext}").write_bytes(meshes.read(f"{MESH}.{ext}"))
    mesh = cmesh.load(original / f"{MESH}.cmesh_pc", original / f"{MESH}.g_cmesh_pc")

    gta = load_gta(models / GTA_MODEL)
    print(f"   GTA model: {len(gta[1])} triangles, {gta[4].sum()} of them straps")
    width, height, fmt, _, buf, off = ytd.textures(models / GTA_TEXTURES)["1"]
    texture = np.asarray(ytd.to_image(width, height, fmt, buf, off).convert("RGB"), dtype=np.float32) / 255

    image, covered = bake_diffuse(mesh, mesh["uvs"], gta, texture, WORK)
    (HERE / "out").mkdir(exist_ok=True)
    image.save(HERE / "out" / "realtree_backpack.png")
    print(f"   baked: {100 * covered.mean():.0f}% of the texture")
    folder = HERE / "out" / MOD_NAME
    print("   " + clothing.rebuild_pack(game, original, MESH, DIFFUSE, BUMP, image, folder, SIDES))
    print(f"built {folder}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\sr2-re\models\backpack"))
