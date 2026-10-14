"""Triangle lists to a single triangle strip with degenerate joins.

Strip semantics (as Saints Row 2 draws them): triangle i of a strip is (s[i], s[i+1], s[i+2]),
with the winding of odd triangles reversed, i.e. odd i is read as (s[i+1], s[i], s[i+2]). Joins
repeat vertices so that the joining triangles are degenerate and every real triangle keeps the
winding it had in the input list.
"""
from collections import defaultdict


def _edge(a, b):
    return (a, b) if a < b else (b, a)


def build(triangles):
    """Return strip indices covering every triangle of `triangles` (list of (a, b, c))."""
    tris = [tuple(int(v) for v in t) for t in triangles]
    by_edge = defaultdict(list)
    for i, (a, b, c) in enumerate(tris):
        for e in (_edge(a, b), _edge(b, c), _edge(c, a)):
            by_edge[e].append(i)
    used = [False] * len(tris)

    def neighbours(i):
        a, b, c = tris[i]
        return {j for e in (_edge(a, b), _edge(b, c), _edge(c, a)) for j in by_edge[e] if j != i}

    def extend(start, order):
        """Walk forward from triangle `start` laid out as `order` (a rotation of its vertices)."""
        strip = list(order)
        taken = [start]
        mark = {start}
        while True:
            a, b = strip[-2], strip[-1]
            # next triangle must contain edge (a, b) and, at this parity, wind as the input does
            found = None
            for j in by_edge[_edge(a, b)]:
                if used[j] or j in mark:
                    continue
                t = tris[j]
                third = [v for v in t if v != a and v != b]
                if len(third) != 1:
                    continue
                c = third[0]
                # triangle index of the new one within the strip
                k = len(strip) - 2
                drawn = (a, b, c) if k % 2 == 0 else (b, a, c)
                if _same_winding(drawn, t):
                    found = (j, c)
                    break
            if not found:
                return strip, taken
            strip.append(found[1])
            taken.append(found[0])
            mark.add(found[0])

    out = []
    order = sorted(range(len(tris)), key=lambda i: sum(1 for j in neighbours(i) if not used[j]))
    for i in order:
        if used[i]:
            continue
        a, b, c = tris[i]
        best = None
        for rot in ((a, b, c), (b, c, a), (c, a, b)):
            strip, taken = extend(i, rot)
            if best is None or len(taken) > len(best[1]):
                best = (strip, taken)
        strip, taken = best
        for j in taken:
            used[j] = True
        if out:
            # Join: repeat the previous end and the new start; keep the new strip starting on an
            # even position so its first triangle keeps its winding.
            out += [out[-1], strip[0]]
            if len(out) % 2 == 1:
                out.append(strip[0])
        out += strip
    return out


def _same_winding(drawn, original):
    """True if `drawn` is a rotation of `original` (same orientation)."""
    a, b, c = original
    return drawn in ((a, b, c), (b, c, a), (c, a, b))


def triangles(strip):
    """Decode a strip back to its non-degenerate triangles (for checking)."""
    out = []
    for i in range(len(strip) - 2):
        a, b, c = strip[i], strip[i + 1], strip[i + 2]
        if a == b or b == c or a == c:
            continue
        out.append((a, b, c) if i % 2 == 0 else (b, a, c))
    return out
