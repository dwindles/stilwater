"""Read meshes from binary glTF 2.0 (.glb): positions, normals, UVs and triangles of every mesh
primitive, placed by the node hierarchy, enough to bake a model's textures.

GLB: "glTF", version, length; then chunks (u32 length, u32 type): JSON, then BIN.

    python glb.py <file.glb>      # lists the primitives
"""
import json
import struct
import sys

import numpy as np

_COMPONENTS = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _accessor(doc, binary, index):
    a = doc["accessors"][index]
    view = doc["bufferViews"][a["bufferView"]]
    dtype = np.dtype(_COMPONENTS[a["componentType"]])
    width = _WIDTH[a["type"]]
    start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = view.get("byteStride", 0) or dtype.itemsize * width
    rows = np.ndarray((a["count"], width), dtype=dtype, buffer=binary, offset=start, strides=(stride, dtype.itemsize))
    out = rows.astype(np.float64 if dtype == np.float32 else np.int64)
    if a.get("normalized"):
        out = out / np.iinfo(dtype).max
    return out


def _matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]))
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    s = np.array(node.get("scale", [1, 1, 1]))
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def read(path):
    """[dict(name, positions (N,3), normals (N,3), uvs (N,2), triangles (M,3), material)] in world space."""
    data = open(path, "rb").read()
    if data[:4] != b"glTF":
        raise ValueError(f"{path}: not a binary glTF")
    doc, binary, at = None, None, 12
    while at < len(data):
        length, kind = struct.unpack_from("<II", data, at)
        chunk = data[at + 8:at + 8 + length]
        if kind == 0x4E4F534A:
            doc = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
        at += 8 + length
    out = []

    def visit(index, parent):
        node = doc["nodes"][index]
        world = parent @ _matrix(node)
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            for k, prim in enumerate(mesh["primitives"]):
                if prim.get("mode", 4) != 4:
                    continue
                attrs = prim["attributes"]
                p = _accessor(doc, binary, attrs["POSITION"])
                p = p @ world[:3, :3].T + world[:3, 3]
                n = _accessor(doc, binary, attrs["NORMAL"]) if "NORMAL" in attrs else np.zeros_like(p)
                n = n @ np.linalg.inv(world[:3, :3])
                n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
                uv = _accessor(doc, binary, attrs["TEXCOORD_0"]) if "TEXCOORD_0" in attrs else np.zeros((len(p), 2))
                idx = _accessor(doc, binary, prim["indices"]).reshape(-1, 3) if "indices" in prim else \
                    np.arange(len(p)).reshape(-1, 3)
                out.append(dict(name=f"{mesh.get('name', node.get('name', index))}/{k}", positions=p, normals=n,
                                uvs=uv, triangles=idx, material=prim.get("material")))
        for child in node.get("children", []):
            visit(child, world)

    scene = doc["scenes"][doc.get("scene", 0)]
    for index in scene["nodes"]:
        visit(index, np.eye(4))
    return out


def main(argv):
    for m in read(argv[1]):
        p = m["positions"]
        print(f"{m['name']}: {len(p)} vertices, {len(m['triangles'])} triangles, material {m['material']}, "
              f"bbox {np.round(p.min(0), 3)} .. {np.round(p.max(0), 3)}")


if __name__ == "__main__":
    main(sys.argv)
