"""Slim, straight "stretch" fit for SR2 jeans meshes, edited in place.

Only vertex positions move (in the .g_cmesh_pc), so a mesh keeps its skinning, UVs and morph
targets (body shape sliders, applied as offsets).

Each leg below the crotch is measured in height bands against the body it covers (cmbod_human):
leg centre and mean radius. The jeans are re-centred on the leg (straightened below the knee) and
scaled towards the leg's radius plus a little ease, keeping the leg straight below the knee (a
slight taper, not hugging the calf), and never made wider. The change fades out towards the crotch
so the hips and waist keep their shape. The items hide the leg body parts they cover, so nothing
pokes through; the hem is then pushed back out where needed to keep covering the shoes the vanilla
jeans covered.
"""
import numpy as np

import cmesh

BODY = "cmbod_human"

BAND = 0.03                       # half height of a measuring band, metres
KNEE = 0.50                       # height of the knee
BLEND = (0.70, 0.80)              # full change below the first height, none above the second
# Ease over the body (metres) by height: snug at the thigh and knee, a little room at the ankle.
EASE = [(0.10, 0.012), (0.30, 0.008), (0.42, 0.006), (0.60, 0.006), (0.80, 0.009)]
TAPER = 0.85                      # hem width relative to the knee, for a straight leg
# The hem must still cover the shoes the vanilla jeans covered (ankle boots and high-tops reach up
# inside the leg): it is pushed back out, towards its vanilla position, to clear them by this much.
SHOE_CLEARANCE = 0.006
SHOE_TOP = 0.45                   # only the lower leg can meet a shoe
SHOE_POKE_LIMIT = 0.01            # shoes poking through the vanilla jeans more than this are tall
                                  # boots that clip anyway, and are ignored


def bands(points, side, heights):
    """(centre xz, mean radius) of one leg's points around each height."""
    centres, radii = [], []
    for y in heights:
        s = points[(np.abs(points[:, 1] - y) < BAND) & (side * points[:, 0] > 0.02)]
        c = s[:, [0, 2]].mean(axis=0)
        centres.append(c)
        radii.append(np.linalg.norm(s[:, [0, 2]] - c, axis=1).mean())
    smooth = np.ones(5) / 5
    radii = np.convolve(np.pad(radii, 2, mode="edge"), smooth, mode="valid")
    centres = np.stack([np.convolve(np.pad(np.array(centres)[:, k], 2, mode="edge"), smooth, mode="valid")
                        for k in (0, 1)], axis=1)
    return centres, radii


def straighten(heights, centres):
    """Leg centres with the part below the knee replaced by a straight line (fitted from the ankle
    to just above the knee), blending back to the measured centres over the next 10 cm."""
    fit = heights < KNEE + 0.05
    line = np.stack([np.polyval(np.polyfit(heights[fit], centres[fit, k], 1), heights) for k in (0, 1)], axis=1)
    w = np.clip((heights - KNEE) / 0.10, 0, 1)[:, None]
    return line * (1 - w) + centres * w


def ring(points, side, y, band=0.015):
    return points[(np.abs(points[:, 1] - y) < band) & (side * points[:, 0] > 0.02)]


def poke(shoe, jeans):
    """How far (metres) a shoe sticks out through the jeans' legs, above the foot."""
    worst = 0.0
    for y in np.arange(0.13, min(shoe[:, 1].max(), SHOE_TOP), 0.02):
        for side in (-1, 1):
            s, j = ring(shoe, side, y), ring(jeans, side, y)
            if len(s) < 3 or len(j) < 3:
                continue
            c = j[:, [0, 2]].mean(axis=0)
            js, ss = j[:, [0, 2]] - c, s[:, [0, 2]] - c
            ja = np.arctan2(js[:, 1], js[:, 0])
            jr = np.linalg.norm(js, axis=1)
            for a, r in zip(np.arctan2(ss[:, 1], ss[:, 0]), np.linalg.norm(ss, axis=1)):
                near = jr[np.abs((ja - a + np.pi) % (2 * np.pi) - np.pi) < 0.4]
                if len(near):
                    worst = max(worst, r - near.max())
    return worst


def clear_shoes(original, slimmed, shoes):
    """Push slimmed hem vertices back towards their vanilla positions until they clear the shoes."""
    out = slimmed.copy()
    for side in (-1, 1):
        for i in np.flatnonzero((side * slimmed[:, 0] > 0) & (slimmed[:, 1] < SHOE_TOP)):
            y = slimmed[i, 1]
            j = ring(slimmed, side, y)
            s = ring(shoes, side, y)
            if len(s) == 0:
                continue
            c = j[:, [0, 2]].mean(axis=0)
            offsets = s[:, [0, 2]] - c
            d = slimmed[i, [0, 2]] - c
            a = np.arctan2(d[1], d[0])
            near = np.abs((np.arctan2(offsets[:, 1], offsets[:, 0]) - a + np.pi) % (2 * np.pi) - np.pi) < 0.3
            if not near.any():
                continue
            needed = np.linalg.norm(offsets[near], axis=1).max() + SHOE_CLEARANCE
            for t in np.linspace(0, 1, 21):
                p = slimmed[i] + t * (original[i] - slimmed[i])
                if np.linalg.norm(p[[0, 2]] - c) >= needed:
                    break
            out[i] = p
    return out


def slim(positions, body):
    heights = np.arange(0.08, BLEND[1] + 0.001, 0.01)
    ease = np.interp(heights, *zip(*EASE))
    out = positions.copy()
    for side in (-1, 1):
        body_c, body_r = bands(body, side, heights)
        body_c = straighten(heights, body_c)
        jeans_c, jeans_r = bands(positions, side, heights)
        target = body_r + ease
        knee = np.interp(KNEE, heights, target)
        below = heights < KNEE
        straight = knee * (TAPER + (1 - TAPER) * (heights - heights[0]) / (KNEE - heights[0]))
        target[below] = np.maximum(target[below], straight[below])
        target = np.minimum(target, jeans_r)              # only ever tighter
        scale = target / jeans_r

        leg = side * positions[:, 0] > 0
        y = positions[leg, 1]
        w = np.clip((BLEND[1] - y) / (BLEND[1] - BLEND[0]), 0, 1)[:, None]
        jc = np.stack([np.interp(y, heights, jeans_c[:, k]) for k in (0, 1)], axis=1)
        bc = np.stack([np.interp(y, heights, body_c[:, k]) for k in (0, 1)], axis=1)
        s = np.interp(y, heights, scale)[:, None]
        xz = positions[leg][:, [0, 2]]
        moved = bc + (xz - jc) * s
        out_leg = out[leg]
        out_leg[:, [0, 2]] = xz + (moved - xz) * w
        out[leg] = out_leg
        for h in (0.15, 0.3, 0.45, 0.6, 0.75):
            print(f"   side {side:+d} y {h:.2f}: radius {100 * np.interp(h, heights, jeans_r):.1f} -> "
                  f"{100 * np.interp(h, heights, target):.1f} cm (leg {100 * np.interp(h, heights, body_r):.1f})")
    return out




def covered_shoes(meshes, folder, jeans):
    """Points of the men's and unisex shoes the vanilla jeans cover (shoes poking through them more
    than SHOE_POKE_LIMIT are tall boots that clip anyway). Shoe meshes are written to folder."""
    folder.mkdir(exist_ok=True)
    covered = []
    for entry in meshes.entries:
        name = entry[0]
        if not (name.lower().startswith(("cmsho_m", "cmsho_u")) and name.lower().endswith(".cmesh_pc")):
            continue
        stem = name[:-len(".cmesh_pc")]
        for ext in ("cmesh_pc", "g_cmesh_pc"):
            (folder / f"{stem}.{ext}").write_bytes(meshes.read(f"{stem}.{ext}"))
        shoe = cmesh.load(folder / f"{stem}.cmesh_pc", folder / f"{stem}.g_cmesh_pc")
        points = shoe["positions"][np.unique(shoe["triangles"])]
        if poke(points, jeans) <= SHOE_POKE_LIMIT:
            covered.append(points)
    return np.concatenate(covered)


def fit(meshes, original, mesh):
    """(vanilla mesh, slimmed positions) for mesh (a name in meshes.vpp_pc); the vanilla files and
    the body and shoes measured against go into original/."""
    original.mkdir(exist_ok=True)
    for name in (mesh, BODY):
        for ext in ("cmesh_pc", "g_cmesh_pc"):
            (original / f"{name}.{ext}").write_bytes(meshes.read(f"{name}.{ext}"))
    jeans = cmesh.load(original / f"{mesh}.cmesh_pc", original / f"{mesh}.g_cmesh_pc")
    body = cmesh.load(original / f"{BODY}.cmesh_pc", original / f"{BODY}.g_cmesh_pc")
    body_points = body["positions"][np.unique(body["triangles"])]
    shoes = covered_shoes(meshes, original / "shoes", jeans["positions"])
    new = slim(jeans["positions"], body_points)
    return jeans, clear_shoes(jeans["positions"], new, shoes)
