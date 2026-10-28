"""Texture baking helpers: sample a model's surface, rasterize a target mesh's UV triangles and fill
the gaps, to carry a model's texture onto another mesh's UV layout.
"""
import numpy as np


def sample_surface(positions, triangles, corner_uv, corner_normal, count, seed=7):
    """count random points on a surface (positions per corner, triangles of corner ids), with their
    UVs, normals and triangles."""
    rng = np.random.default_rng(seed)
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    pick = rng.choice(len(triangles), size=count, p=area / area.sum())
    r1, r2 = rng.random(count), rng.random(count)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    w = np.stack([1 - r1 - r2, r1, r2], axis=1)
    corners = triangles[pick]
    points = (w[..., None] * positions[corners]).sum(axis=1)
    uvs = (w[..., None] * corner_uv[corners]).sum(axis=1)
    normals = (w[..., None] * corner_normal[corners]).sum(axis=1)
    normals /= np.linalg.norm(normals, axis=1, keepdims=True) + 1e-12
    return points, uvs, normals, pick


def rasterize(uvs, triangles, size, wrap=False):
    """(texel rows, cols, triangle, barycentric weights) for every texel centre covered; UV v runs
    down the image. wrap: triangles outside the 0..1 square (repeating textures) are moved into it
    by whole texture widths."""
    rows, cols, tris, weights = [], [], [], []
    for t, tri in enumerate(triangles):
        p = uvs[tri]
        if wrap:
            p = p - np.floor(p.mean(axis=0))
        p = p * size
        x0, y0 = np.floor(p.min(axis=0)).astype(int)
        x1, y1 = np.ceil(p.max(axis=0)).astype(int)
        xs, ys = np.meshgrid(np.arange(max(x0, 0), min(x1, size - 1) + 1) + 0.5,
                             np.arange(max(y0, 0), min(y1, size - 1) + 1) + 0.5)
        xs, ys = xs.ravel(), ys.ravel()
        d = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(d) < 1e-12:
            continue
        w0 = ((p[1, 1] - p[2, 1]) * (xs - p[2, 0]) + (p[2, 0] - p[1, 0]) * (ys - p[2, 1])) / d
        w1 = ((p[2, 1] - p[0, 1]) * (xs - p[2, 0]) + (p[0, 0] - p[2, 0]) * (ys - p[2, 1])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        rows.append(ys[inside].astype(int))
        cols.append(xs[inside].astype(int))
        tris.append(np.full(inside.sum(), t))
        weights.append(np.stack([w0, w1, w2], axis=1)[inside])
    return np.concatenate(rows), np.concatenate(cols), np.concatenate(tris), np.concatenate(weights)


def bilinear(image, uv):
    """Sample image (H, W, C floats) at UVs whose v starts at the bottom (FBX, OBJ), wrapping."""
    h, w = image.shape[:2]
    x = np.mod(uv[:, 0], 1) * w - 0.5
    y = (1 - np.mod(uv[:, 1], 1)) * h - 0.5
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x - x0)[:, None], (y - y0)[:, None]
    x0, x1 = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1)
    y0, y1 = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    return ((image[y0, x0] * (1 - fx) + image[y0, x1] * fx) * (1 - fy)
            + (image[y1, x0] * (1 - fx) + image[y1, x1] * fx) * fy)


def dilate(colour, covered, passes=12):
    """Spread colours into uncovered texels so seams don't bleed background into mips."""
    colour, covered = colour.copy(), covered.copy()
    for _ in range(passes):
        total = np.zeros_like(colour)
        count = np.zeros(covered.shape)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            shifted = np.roll(np.roll(covered, dy, 0), dx, 1)
            total += np.roll(np.roll(colour * covered[..., None], dy, 0), dx, 1)
            count += shifted
        grow = ~covered & (count > 0)
        colour[grow] = total[grow] / count[grow][:, None]
        covered = covered | grow
    colour[~covered] = colour[covered].mean(axis=0)
    return colour


def nearest_facing(tree, normals, points, point_normals, k=12, outermost=False):
    """Index of the nearest sample (in a cKDTree over samples with normals) facing the same way as
    each point, or the nearest one if none does. outermost: of the k nearest facing samples, the one
    furthest out along the point's normal, so layered models (a pocket stitched over a panel) give
    the top layer rather than alternating between them."""
    _, near = tree.query(points, k=k)
    facing = (normals[near] * point_normals[:, None, :]).sum(axis=2) > 0
    if outermost:
        height = ((tree.data[near] - points[:, None, :]) * point_normals[:, None, :]).sum(axis=2)
        choice = np.where(facing.any(axis=1), np.where(facing, height, -np.inf).argmax(axis=1), 0)
    else:
        choice = np.where(facing.any(axis=1), facing.argmax(axis=1), 0)
    return near[np.arange(len(points)), choice]


def bake_mapped(uvs, triangles, positions, normals, mapping, tree, sample_uvs, sample_normals, texture,
                size, wrap=False, k=16):
    """Bake texture onto a mesh's UV layout through a model sampled as (tree, sample_uvs,
    sample_normals): each texel's point and normal on the mesh go through mapping(points, normals) into
    the model's space and take the colour (texture: sampler(uvs) or an image for bilinear) of the
    nearest model point facing the same way. Returns (colour (size, size, 3), facing (size, size): how
    far the model's surface turns from the mesh's there, 1 where flat or unmatched, covered)."""
    rows, cols, tris, w = rasterize(uvs, triangles, size, wrap)
    corners = triangles[tris]
    points = (w[..., None] * positions[corners]).sum(axis=1)
    point_normals = (w[..., None] * normals[corners]).sum(axis=1)
    point_normals /= np.linalg.norm(point_normals, axis=1, keepdims=True) + 1e-12
    source, source_normals = mapping(points, point_normals)
    nearest = nearest_facing(tree, sample_normals, source, source_normals, k=k)
    image = np.zeros((size, size, 4))
    covered = np.zeros((size, size), bool)
    image[rows, cols, :3] = texture(sample_uvs[nearest]) if callable(texture) else bilinear(texture, sample_uvs[nearest])
    facing = (sample_normals[nearest] * source_normals).sum(axis=1)
    image[rows, cols, 3] = np.where(facing > 0, facing, 1)
    covered[rows, cols] = True
    image = dilate(image, covered)
    return image[..., :3], image[..., 3], covered
