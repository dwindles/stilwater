"""Read meshes from binary FBX files (versions 7.x): vertex positions, triangulated polygons and
per-corner UVs and normals, enough to port a model.

Binary FBX: "Kaydara FBX Binary  \\0", then nested node records. A record (before 7.5) is u32 end
offset, u32 property count, u32 property list length, u8 name length, name, properties, children,
and ends with a 13-byte null record. 7.5 and later use 64-bit end offset, count and length.
Properties are typed by one character: Y C I F D L scalars, f d l i b arrays (u32 count,
u32 encoding (1 = zlib), u32 byte length, data), S R strings/raw (u32 length, data).

    python fbx.py <file.fbx>      # lists the geometries
"""
import struct
import sys
import zlib

import numpy as np

_SCALARS = {b"Y": "<h", b"C": "<?", b"I": "<i", b"F": "<f", b"D": "<d", b"L": "<q"}
_ARRAYS = {b"f": "<f4", b"d": "<f8", b"l": "<i8", b"i": "<i4", b"b": "<u1"}


class Node:
    def __init__(self, name, props, children):
        self.name, self.props, self.children = name, props, children

    def find(self, name):
        return next((c for c in self.children if c.name == name), None)

    def find_all(self, name):
        return [c for c in self.children if c.name == name]


def _read_node(d, off, wide):
    if wide:
        end, count, _, = struct.unpack_from("<QQQ", d, off)
        off += 24
    else:
        end, count, _ = struct.unpack_from("<III", d, off)
        off += 12
    name_len = d[off]
    off += 1
    if end == 0:
        return None, off + name_len
    name = d[off:off + name_len].decode("latin-1")
    off += name_len
    props = []
    for _ in range(count):
        kind = d[off:off + 1]
        off += 1
        if kind in _SCALARS:
            fmt = _SCALARS[kind]
            props.append(struct.unpack_from(fmt, d, off)[0])
            off += struct.calcsize(fmt)
        elif kind in _ARRAYS:
            n, encoding, length = struct.unpack_from("<III", d, off)
            off += 12
            raw = d[off:off + length]
            off += length
            if encoding == 1:
                raw = zlib.decompress(raw)
            props.append(np.frombuffer(raw, dtype=_ARRAYS[kind], count=n))
        elif kind in (b"S", b"R"):
            n, = struct.unpack_from("<I", d, off)
            off += 4
            props.append(d[off:off + n])
            off += n
        else:
            raise ValueError(f"unknown FBX property type {kind!r} at {off - 1}")
    children = []
    while off < end:
        child, off = _read_node(d, off, wide)
        if child is None:
            break
        children.append(child)
    return Node(name, props, children), end


def read(path):
    """The FBX root node."""
    d = open(path, "rb").read()
    if not d.startswith(b"Kaydara FBX Binary"):
        raise ValueError(f"{path}: not a binary FBX")
    version, = struct.unpack_from("<I", d, 23)
    wide = version >= 7500
    off, children = 27, []
    while off < len(d) - 13:
        node, off = _read_node(d, off, wide)
        if node is None:
            break
        children.append(node)
    return Node("", [], children)


def _layer(geom, layer, values, indices):
    element = geom.find(layer)
    if element is None:
        return None, None
    mapping = element.find("MappingInformationType").props[0].decode()
    reference = element.find("ReferenceInformationType").props[0].decode()
    data = element.find(values).props[0]
    index = element.find(indices).props[0] if element.find(indices) is not None else None
    return (mapping, reference, data, index), element


def meshes(path):
    """[dict(name, positions (N,3), triangles (M,3) of corner ids, corner_vertex (C,), corner_uv (C,2),
    corner_normal (C,3))]: corners are polygon vertices, so UV/normal seams are kept."""
    root = read(path)
    objects = root.find("Objects")
    out = []
    for geom in objects.find_all("Geometry"):
        if geom.find("Vertices") is None:
            continue
        positions = geom.find("Vertices").props[0].reshape(-1, 3).astype(float)
        poly = geom.find("PolygonVertexIndex").props[0].astype(np.int64)
        corner_vertex = np.where(poly < 0, -poly - 1, poly)
        # Fan-triangulate each polygon (a negative index ends one).
        tris, start = [], 0
        for i, v in enumerate(poly):
            if v < 0:
                for k in range(start + 1, i):
                    tris.append((start, k, k + 1))
                start = i + 1
        result = dict(name=geom.props[1].split(b"\x00")[0].decode("latin-1"), positions=positions,
                      triangles=np.array(tris, dtype=np.int64), corner_vertex=corner_vertex)
        for layer, values, indices, key, width in (("LayerElementUV", "UV", "UVIndex", "corner_uv", 2),
                                                  ("LayerElementNormal", "Normals", "NormalsIndex", "corner_normal", 3)):
            info, _ = _layer(geom, layer, values, indices)
            if info is None:
                continue
            mapping, reference, data, index = info
            data = data.reshape(-1, width).astype(float)
            if mapping == "ByPolygonVertex":
                per_corner = data[index] if reference == "IndexToDirect" else data
            elif mapping in ("ByVertice", "ByVertex", "ByControlPoint"):
                per_corner = (data[index] if reference == "IndexToDirect" else data)[corner_vertex]
            else:
                raise ValueError(f"unsupported {layer} mapping {mapping}")
            result[key] = per_corner
        out.append(result)
    return out


def main(argv):
    for m in meshes(argv[1]):
        p = m["positions"]
        print(f"{m['name']}: {len(p)} vertices, {len(m['triangles'])} triangles, "
              f"bbox {np.round(p.min(0), 3)} .. {np.round(p.max(0), 3)}, "
              f"uv {'yes' if 'corner_uv' in m else 'no'}, normals {'yes' if 'corner_normal' in m else 'no'}")


if __name__ == "__main__":
    main(sys.argv)
