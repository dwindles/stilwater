"""Project the flat-lay jeans photos onto Saints Row 2's men's tight jeans texture layout.

SR2 jeans (cmbot_mjeansmf01_d, 512x512) are unwrapped as two legs side by side. Each half wraps
one leg all the way round: the front panel runs from the fly / front inseam at the centre out to
the side seam, and the back panel runs from the side seam out to the back seam / back inseam at
the texture edge. The left half is the wearer's right leg.

The photo outlines (outseams, inseams, fly and back seam) are the hand-traced ones from the
Skate 3 version of this mod. Every texel samples the matching point between those outlines.

    python project.py            # writes out/hq_jeans_diffuse_1024.png and out/compare.png
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "out"
SIZE = 1024

# SR2 texture layout as fractions of the 512px original.
TEX_ROWS = np.array([4, 22, 184, 504]) / 512    # waist top, waistband bottom, crotch, hem
OUTSEAM_L, INSEAM_L = 136 / 512, 244 / 512      # left half: side seam, front inseam / fly
INSEAM_R, OUTSEAM_R = 257 / 512, 361 / 512      # right half
SEAM_BLEND = 0.008                              # cross-fade width at the side seams
INSET = 3                                       # px kept inside the photo outline

# Photo outlines (800x1067 photos). rows: waistband top, waistband bottom, crotch, hem.
# edges: (y, left, right); inner: (y, inner-left, inner-right) from the crotch apex down;
# centre: (y, x) of the fly / back seam from the waist to the crotch apex.
PHOTOS = {
    "front": dict(
        file=HERE / "ref" / "front.webp",
        rows=[42, 80, 330, 1028],
        edges=[(42, 214, 578), (100, 198, 588), (200, 186, 598), (300, 178, 607), (400, 170, 612),
               (500, 163, 620), (600, 157, 625), (700, 152, 630), (800, 150, 632), (900, 148, 633),
               (1000, 147, 635), (1030, 147, 636)],
        inner=[(330, 398, 398), (400, 370, 425), (500, 345, 452), (600, 335, 462), (700, 330, 466),
               (800, 328, 466), (1000, 325, 465), (1030, 325, 465)],
        centre=[(42, 405), (330, 398)],
    ),
    "back": dict(
        file=HERE / "ref" / "back.webp",
        rows=[38, 76, 335, 1028],
        edges=[(38, 225, 597), (100, 210, 603), (200, 200, 613), (300, 188, 625), (400, 182, 633),
               (500, 175, 640), (600, 170, 645), (700, 163, 648), (800, 158, 650), (900, 153, 652),
               (1000, 150, 655), (1030, 150, 657)],
        inner=[(335, 408, 408), (400, 375, 440), (500, 348, 455), (600, 338, 462), (700, 335, 466),
               (800, 332, 468), (1000, 328, 470), (1030, 326, 472)],
        centre=[(38, 410), (335, 408)],
    ),
}


def outline(spec, py):
    """Left, right, inner-left and inner-right photo x for photo rows py."""
    e = np.array(spec["edges"], float)
    left, right = np.interp(py, e[:, 0], e[:, 1]), np.interp(py, e[:, 0], e[:, 2])
    i = np.array(spec["inner"], float)
    c = np.array(spec["centre"], float)
    centre = np.interp(py, c[:, 0], c[:, 1])
    below = py >= i[0, 0]
    inner_left = np.where(below, np.interp(py, i[:, 0], i[:, 1]), centre)
    inner_right = np.where(below, np.interp(py, i[:, 0], i[:, 2]), centre)
    pad = INSET * (inner_left < inner_right - 1)
    return left + INSET, right - INSET, inner_left - pad, inner_right + pad


def sample(spec, photo, u, tv, panels):
    """Sample one photo. panels: list of (mask, t, from_edge, to_edge) in photo-outline terms."""
    py = np.interp(tv, TEX_ROWS, spec["rows"])
    L, R, GL, GR = outline(spec, py)
    edge = {"L": L, "R": R, "GL": GL, "GR": GR}
    px = np.zeros_like(u)
    for mask, t, a, b in panels:
        t = np.clip(t, 0, 1)
        px = np.where(mask, edge[a] + t * (edge[b] - edge[a]), px)
    return cv2.remap(photo, px.astype(np.float32), py.astype(np.float32), cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REFLECT)


def main():
    OUT.mkdir(exist_ok=True)
    photos = {k: np.asarray(Image.open(s["file"]).convert("RGB")) for k, s in PHOTOS.items()}
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64)
    u = (xx + 0.5) / SIZE
    tv = np.clip((yy + 0.5) / SIZE, TEX_ROWS[0], TEX_ROWS[-1])

    left_half = u < 0.5
    # Front panels: the wearer's right leg is on the photo's left (front view).
    front = sample(PHOTOS["front"], photos["front"], u, tv, [
        (left_half, (u - OUTSEAM_L) / (INSEAM_L - OUTSEAM_L), "L", "GL"),
        (~left_half, (u - INSEAM_R) / (OUTSEAM_R - INSEAM_R), "GR", "R"),
    ]).astype(np.float64)
    # Back panels: seen from behind, the wearer's right leg is on the photo's right.
    back = sample(PHOTOS["back"], photos["back"], u, tv, [
        (left_half, u / OUTSEAM_L, "GR", "R"),
        (~left_half, (u - OUTSEAM_R) / (1 - OUTSEAM_R), "L", "GL"),
    ]).astype(np.float64)

    # 1 on the front panels, 0 on the back, cross-faded at the side seams.
    to_front = np.where(left_half, u - OUTSEAM_L, OUTSEAM_R - u)
    w = np.clip((to_front + SEAM_BLEND) / (2 * SEAM_BLEND), 0, 1)[..., None]
    result = (front * w + back * (1 - w)).clip(0, 255).astype(np.uint8)
    Image.fromarray(result).save(OUT / "hq_jeans_diffuse_1024.png")

    original = Image.open(HERE / "original" / "cmbot_mjeansmf01_d.png").convert("RGB").resize((512, 512))
    compare = Image.new("RGB", (1040, 512), (24, 24, 24))
    compare.paste(original, (0, 0))
    compare.paste(Image.fromarray(result).resize((512, 512), Image.LANCZOS), (528, 0))
    compare.save(OUT / "compare.png")
    print("wrote", OUT / "hq_jeans_diffuse_1024.png")


if __name__ == "__main__":
    main()
