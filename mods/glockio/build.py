"""Build GLOCKIO: a Glock tucked in the waistband, from the GTA V ped accessory (accs_028, the extended
magazine; accs_029, the drum), on a copy of SR2's police utility belt.

SR2 meshes can't take new geometry here (their skinning and body shapes are per vertex), and the
belt's pieces are small open strips, too few and too flat to pull onto a pistol. So the pistol is
made of cards: its vertices split into the grip and the slide (two clusters), a box fitted round
each (its principal axes), and twelve of the belt's strips laid flat on those boxes' faces. Every
other piece of the belt is folded to one point inside the hips, where its triangles have no area and
draw nothing; the vertex count stays. The cards get a texture layout of their own
(mods/undercover-jeans/uvtransfer.py) with the GTA pistol's texture baked on, the colour of the
nearest point of the pistol facing the same way, and all three of the belt's diffuse textures carry
it (each card keeps its material). The cards are skinned like the belt's front (the hips).

The GTA accessory sits in the ped's frame, whose root is about a metre up, at the hips (the GTA
jeans' waist lands on SR2's at +1 m); its x, y, z go to SR2's as the shoes' do (gta-shoes TURN).

    python build.py [game folder] [GTA clothes folder]     # writes out/STILWATER - GLOCKIO/
"""
import importlib.util
import re
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools" / "sr2"))
sys.path.insert(0, str(ROOT / "tools" / "mesh"))
sys.path.insert(0, str(ROOT / "tools" / "gta5"))
sys.path.insert(0, str(ROOT / "mods" / "gta-shoes"))
sys.path.insert(0, str(ROOT / "mods" / "undercover-jeans"))
import bake  # noqa: E402
import cmesh  # noqa: E402
import peg  # noqa: E402
import vpp  # noqa: E402
import ytd  # noqa: E402
from uvtransfer import islands, layout, lscm  # noqa: E402

spec = importlib.util.spec_from_file_location("gta_shoes", ROOT / "mods" / "gta-shoes" / "build.py")
shoes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shoes)

SOURCE = "cmx03_ucoputil01"
MOD_NAME = "STILWATER - GLOCKIO"
GLOCKS = [
    dict(name="GLOCKIO Extended", base="cmx03_uglockx001", ydd="accs_028_u.ydd", ytd="accs_diff_028_a_uni.ytd"),
    dict(name="GLOCKIO Drum", base="cmx03_uglockd001", ydd="accs_029_u.ydd", ytd="accs_diff_029_a_uni.ytd"),
]
OFFSET = np.array([0.0, 1.0, 0.0])      # the GTA ped root above SR2's ground
HIDDEN = np.array([0.0, 1.0, -0.02])     # inside the hips
CARDS = 12
WORK = 512


def rename(data, base):
    assert len(base) == len(SOURCE)
    return re.sub(re.escape(SOURCE.encode()), base.encode(), data, flags=re.I)


def boxes(points):
    """Two oriented boxes round the pistol's grip and slide: [(centre, axes (3x3, rows), half sizes)]."""
    # Two clusters (k-means from the ends of the longest axis).
    centre = points.mean(axis=0)
    axis = np.linalg.svd(points - centre)[2][0]
    t = (points - centre) @ axis
    means = np.stack([points[t < np.median(t)].mean(axis=0), points[t >= np.median(t)].mean(axis=0)])
    for _ in range(20):
        label = np.linalg.norm(points[:, None] - means[None], axis=2).argmin(axis=1)
        means = np.stack([points[label == k].mean(axis=0) for k in range(2)])
    out = []
    for k in range(2):
        p = points[label == k]
        c = p.mean(axis=0)
        axes = np.linalg.svd(p - c)[2]
        local = (p - c) @ axes.T
        lo, hi = np.percentile(local, 1, axis=0), np.percentile(local, 99, axis=0)
        out.append((c + ((lo + hi) / 2) @ axes, axes, (hi - lo) / 2))
    return out


def faces(box):
    """The six faces of a box: (corner 00, edge u, edge v, outward normal)."""
    centre, axes, half = box
    out = []
    for a in range(3):
        b, c = (a + 1) % 3, (a + 2) % 3
        for sign in (1, -1):
            normal = sign * axes[a]
            origin = centre + normal * half[a] - axes[b] * half[b] - axes[c] * half[c]
            u, v = 2 * half[b] * axes[b], 2 * half[c] * axes[c]
            if np.dot(np.cross(u, v), normal) < 0:
                origin, u = origin + u, -u
            out.append((origin, u, v, normal))
    return out


def card_coords(positions, normals, triangles):
    """Each vertex of a strip (two rows of points) at (s, t) on a rectangle: its row on one of the
    long edges (t 0 or 1), its place along the row stretched from end to end (s)."""
    flat = lscm(positions, normals, triangles)
    flat -= flat.mean(axis=0)
    flat = flat @ np.linalg.svd(flat)[2].T
    row = (flat[:, 1] > np.median(flat[:, 1])).astype(float)
    s = np.zeros(len(flat))
    for r in (0, 1):
        along = flat[row == r, 0]
        s[row == r] = (along - along.min()) / max(np.ptp(along), 1e-9)
    return np.stack([s, row], axis=1)


def main(game, clothes):
    original = HERE / "original"
    original.mkdir(exist_ok=True)
    for ext, pack in ((".cmesh_pc", "meshes"), (".g_cmesh_pc", "meshes"), ("_pc.morph_pc", "meshes"),
                      (".peg_pc", "pegs"), (".g_peg_pc", "textures")):
        if not (original / f"{SOURCE}{ext}").exists():
            (original / f"{SOURCE}{ext}").write_bytes(vpp.Packfile(game / f"{pack}.vpp_pc").read(f"{SOURCE}{ext}"))
    belt = cmesh.load(original / f"{SOURCE}.cmesh_pc", original / f"{SOURCE}.g_cmesh_pc")
    raw0 = (original / f"{SOURCE}.g_cmesh_pc").read_bytes()
    stride = belt["stride"]
    island = islands(belt)
    pieces = []
    for i in np.unique(island):
        tris = belt["triangles"][island == i]
        pieces.append((len(np.unique(tris)), i, tris))
    # The cards: strips of eight vertices (two rows of four), the most even ones.
    strips = [p for p in pieces if p[0] == 8][:CARDS]
    assert len(strips) == CARDS, len(strips)
    # Skinning of the belt's front: the vertex nearest the front of the hips.
    front = np.argmin(np.linalg.norm(belt["positions"] - [0.08, 1.02, 0.1], axis=1))
    weights = raw0[front * stride + 12:front * stride + 20]

    out = HERE / "out"
    folder = out / MOD_NAME
    folder.mkdir(parents=True, exist_ok=True)
    header = peg.read_header(original / f"{SOURCE}.peg_pc")
    for glock in GLOCKS:
        positions, normals, uvs, triangles = shoes.gta_shoe(clothes / "GLOCKIO" / "GLOCKIO" / glock["ydd"])
        positions = positions + OFFSET
        pistol = boxes(positions)
        quads = [f for box in pistol for f in faces(box)]

        new_p = np.repeat(HIDDEN[None], len(belt["positions"]), axis=0)
        new_n = np.repeat(np.array([[0.0, 0.0, 1.0]]), len(belt["positions"]), axis=0)
        used = []
        for (_, _, tris), (origin, u, v, normal) in zip(strips, quads):
            verts = np.unique(tris)
            local = np.full(len(belt["positions"]), -1)
            local[verts] = np.arange(len(verts))
            st = card_coords(belt["positions"][verts], belt["normals"][verts], local[tris])
            new_p[verts] = origin + st[:, :1] * u + st[:, 1:] * v
            new_n[verts] = normal
            used.append(tris)
        cards = dict(positions=new_p, normals=new_n, triangles=np.concatenate(used))
        card_uv = layout(cards)
        uv = np.zeros((len(new_p), 2))
        card_verts = np.unique(cards["triangles"])
        uv[card_verts] = card_uv[card_verts]

        points, sample_uvs, sample_normals, _ = bake.sample_surface(positions, triangles, uvs, normals, 300_000)
        rows, cols, tris, w = bake.rasterize(uv, cards["triangles"], WORK)
        corners = cards["triangles"][tris]
        texel_points = (w[..., None] * new_p[corners]).sum(axis=1)
        texel_normals = (w[..., None] * new_n[corners]).sum(axis=1)
        nearest = bake.nearest_facing(cKDTree(points), sample_normals, texel_points, texel_normals)
        (texture_name, (w_, h_, fmt, levels, buf, off)), = ytd.textures(clothes / "GLOCKIO" / "GLOCKIO" / glock["ytd"]).items()
        texture = np.asarray(ytd.to_image(w_, h_, fmt, buf, off).convert("RGB")).astype(float) / 255
        image = np.zeros((WORK, WORK, 3))
        covered = np.zeros((WORK, WORK), bool)
        image[rows, cols] = bake.bilinear(texture, sample_uvs[nearest])
        covered[rows, cols] = True
        image = Image.fromarray((np.clip(bake.dilate(image, covered), 0, 1) * 255).astype(np.uint8))
        base = glock["base"]
        image.save(out / f"{base}_diffuse.png")

        data = bytearray(raw0)
        for i in range(len(new_p)):
            at = i * stride
            struct.pack_into("<3f", data, at, *new_p[i])
            data[at + 12:at + 20] = weights
            data[at + 20:at + 23] = bytes(np.clip(np.round((new_n[i] + 1) * 127.5), 0, 255).astype(np.uint8))
            struct.pack_into("<hh", data, at + 28, round(uv[i, 0] * 1024), round((uv[i, 1] - 1) * 1024))

        # Every diffuse of the belt carries the pistol (each card keeps its material); same sizes.
        replacements = {}
        for e in header:
            if re.search(r"_2d\d\.tga$", e["name"]):
                fmt = "DXT1" if e["format"] == 0x190 else "DXT5"
                img = image.resize((e["width"], e["height"]), Image.LANCZOS).convert("RGBA")
                blob, mips = peg.encode(img, fmt, max_levels=e["mips"])
                replacements[e["name"]] = (e["width"], e["height"], e["format"], mips, blob)
        peg_header, pack = peg.rebuild(original / f"{SOURCE}.peg_pc", original / f"{SOURCE}.g_peg_pc", replacements)
        assert len(pack) == (original / f"{SOURCE}.g_peg_pc").stat().st_size
        (folder / f"{base}.peg_pc").write_bytes(rename(peg_header, base))
        (folder / f"{base}.g_peg_pc").write_bytes(pack)
        (folder / f"{base}.cmesh_pc").write_bytes(rename((original / f"{SOURCE}.cmesh_pc").read_bytes(), base))
        (folder / f"{base}.g_cmesh_pc").write_bytes(bytes(data))
        (folder / f"{base}_pc.morph_pc").write_bytes((original / f"{SOURCE}_pc.morph_pc").read_bytes())
        print(f"{glock['name']}: {base} ({texture_name}), boxes", [np.round(2 * b[2], 3).tolist() for b in pistol])
    print(f"built {folder}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else r"E:\SteamLibrary\steamapps\common\Saints Row 2"),
         Path(sys.argv[2] if len(sys.argv) > 2 else r"D:\tools\gta-clothes"))
