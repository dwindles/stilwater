"""Correspondence between two tops (hoodies, jackets) in different poses, for baking one's texture
onto the other's UVs.

Each garment is described by a Pose in SR2's frame (metres, y up, front +z, the wearer's right at
+x): the hem, shoulder line and top heights, the torso's half width, and the +x arm's shoulder and
wrist (the -x arm mirrors it). A point on the target maps to the source:

- on the torso and hood by the torso box: heights piecewise linearly (hem, shoulder line, top),
  across by the half widths, front to back by the depth ranges;
- on an arm (beyond the shoulder in x) along the arm: the fraction of the way from shoulder to
  wrist, and the offset around the arm turned from the target arm's direction to the source's
  (a raised arm's top becomes a lowered arm's outside, its front stays the front).

Between the two the maps blend over BLEND metres either side of the shoulder.
"""
from dataclasses import dataclass

import numpy as np

BLEND = 0.04


@dataclass
class Pose:
    hem: float              # height of the hem
    shoulder_line: float    # height of the top of the shoulders at the torso's side
    top: float              # height of the top (hood or collar)
    half_width: float       # torso half width (x)
    depth: tuple            # torso z range (back, front)
    shoulder: tuple         # +x arm's shoulder joint
    wrist: tuple            # +x arm's wrist (cuff centre)


def _rotation(a, b):
    """Rotation matrix turning unit vector a onto unit vector b."""
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k / (1 + c)


def to_source(points, normals, target, source):
    """Points (and normals) on the target garment mapped onto the source garment."""
    # Torso and hood.
    ys = [target.hem, target.shoulder_line, target.top]
    yd = [source.hem, source.shoulder_line, source.top]
    y = np.interp(points[:, 1], ys, yd, left=np.nan, right=np.nan)
    below = points[:, 1] < ys[0]
    above = points[:, 1] > ys[-1]
    y[below] = yd[0] + (points[below, 1] - ys[0]) * (yd[1] - yd[0]) / (ys[1] - ys[0])
    y[above] = yd[-1] + (points[above, 1] - ys[-1])
    x = points[:, 0] * source.half_width / target.half_width
    tz0, tz1 = target.depth
    sz0, sz1 = source.depth
    z = sz0 + (points[:, 2] - tz0) * (sz1 - sz0) / (tz1 - tz0)
    torso = np.stack([x, y, z], axis=1)
    scale = np.array([source.half_width / target.half_width,
                      (yd[1] - yd[0]) / (ys[1] - ys[0]), (sz1 - sz0) / (tz1 - tz0)])
    torso_n = normals / scale
    torso_n /= np.linalg.norm(torso_n, axis=1, keepdims=True) + 1e-12

    # Arms, per side.
    arm = np.empty_like(points)
    arm_n = np.empty_like(normals)
    for side in (1, -1):
        s = np.where(points[:, 0] * side >= 0)[0]
        mirror = np.array([side, 1, 1])
        t_sh, t_wr = np.array(target.shoulder) * mirror, np.array(target.wrist) * mirror
        s_sh, s_wr = np.array(source.shoulder) * mirror, np.array(source.wrist) * mirror
        t_axis, s_axis = t_wr - t_sh, s_wr - s_sh
        t_len, s_len = np.linalg.norm(t_axis), np.linalg.norm(s_axis)
        rot = _rotation(t_axis / t_len, s_axis / s_len)
        rel = points[s] - t_sh
        along = rel @ (t_axis / t_len)
        radial = rel - along[:, None] * (t_axis / t_len)
        arm[s] = s_sh + (along / t_len)[:, None] * s_axis + radial @ rot.T
        arm_n[s] = normals[s] @ rot.T

    weight = np.clip((np.abs(points[:, 0]) - (abs(target.shoulder[0]) - BLEND)) / (2 * BLEND), 0, 1)[:, None]
    out = torso * (1 - weight) + arm * weight
    out_n = torso_n * (1 - weight) + arm_n * weight
    out_n /= np.linalg.norm(out_n, axis=1, keepdims=True) + 1e-12
    return out, out_n
