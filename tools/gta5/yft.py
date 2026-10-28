"""Read GTA V models (.yft fragments, .ydr drawables; RSC7 resources) far enough to get their meshes.

RSC7 resource: "RSC7", u32 version, u32 system flags, u32 graphics flags, then raw deflate data
that inflates to the system segment (pointers 0x5XXXXXXX) followed by the graphics segment
(pointers 0x6XXXXXXX). Layouts follow CodeWalker's (MIT) resource definitions.

    python yft.py <file.yft>      # summary of models and geometries
"""
import struct
import sys
import zlib

import numpy as np

# Vertex components in declaration order, and the byte size of each component type.
COMPONENTS = ["position", "blend_weights", "blend_indices", "normal", "colour0", "colour1",
              "uv0", "uv1", "uv2", "uv3", "uv4", "uv5", "uv6", "uv7", "tangent", "binormal"]
TYPE_SIZES = {0: 2, 1: 4, 2: 4, 3: 8, 4: 4, 5: 8, 6: 12, 7: 16, 8: 4, 9: 4, 10: 4}


def segment_size(flags):
    pages = (((flags >> 27) & 1) + (((flags >> 26) & 1) << 1) + (((flags >> 25) & 1) << 2)
             + (((flags >> 24) & 1) << 3) + (((flags >> 17) & 0x7F) << 4) + (((flags >> 11) & 0x3F) << 5)
             + (((flags >> 7) & 0xF) << 6) + (((flags >> 5) & 0x3) << 7) + (((flags >> 4) & 1) << 8))
    return (0x200 << (flags & 0xF)) * pages


class Resource:
    def __init__(self, path):
        raw = open(path, "rb").read()
        magic, self.version, system_flags, graphics_flags = struct.unpack_from("<4sIII", raw, 0)
        if magic != b"RSC7":
            raise ValueError(f"{path}: not an RSC7 resource")
        data = zlib.decompress(raw[16:], -15)
        self.system_size = segment_size(system_flags)
        self.graphics_size = segment_size(graphics_flags)
        self.system = data[:self.system_size]
        self.graphics = data[self.system_size:self.system_size + self.graphics_size]

    def at(self, pointer):
        """(buffer, offset) for a resource pointer."""
        if pointer >> 28 == 5:
            return self.system, pointer & 0x0FFFFFFF
        if pointer >> 28 == 6:
            return self.graphics, pointer & 0x0FFFFFFF
        raise ValueError(f"bad pointer {pointer:#x}")

    def u64(self, pointer, offset=0):
        buf, base = self.at(pointer)
        return struct.unpack_from("<Q", buf, base + offset)[0]

    def unpack(self, fmt, pointer, offset=0):
        buf, base = self.at(pointer)
        return struct.unpack_from(fmt, buf, base + offset)

    def pointer_list(self, pointer):
        """ResourcePointerList64: (entries pointer, u16 count, u16 capacity)."""
        entries, count = self.unpack("<QH", pointer)
        return [self.u64(entries, 8 * i) for i in range(count)] if entries else []


def read_geometry(res, pointer):
    vertex_buffer, = res.unpack("<Q", pointer, 0x18)
    index_buffer, = res.unpack("<Q", pointer, 0x38)
    stride, = res.unpack("<H", vertex_buffer, 0x08)
    data_pointer, count = res.unpack("<QI", vertex_buffer, 0x10)
    if not data_pointer:                              # some resources only fill the second pointer
        data_pointer, = res.unpack("<Q", vertex_buffer, 0x20)
    info_pointer, = res.unpack("<Q", vertex_buffer, 0x30)
    flags, decl_stride, _, _, types = res.unpack("<IHBBQ", info_pointer)
    if decl_stride != stride:
        raise ValueError(f"stride mismatch {decl_stride} != {stride}")

    buf, base = res.at(data_pointer)
    raw = np.frombuffer(buf[base:base + stride * count], dtype=np.uint8).reshape(count, stride)
    layout, offset = {}, 0
    for i, name in enumerate(COMPONENTS):
        if flags >> i & 1:
            kind = types >> (4 * i) & 0xF
            layout[name] = (offset, kind)
            offset += TYPE_SIZES[kind]

    def component(name):
        start, kind = layout[name]
        chunk = raw[:, start:start + TYPE_SIZES[kind]].tobytes()
        if kind in (5, 6, 7, 2):                      # float2/3/4, float
            return np.frombuffer(chunk, dtype="<f4").reshape(count, -1).astype(float)
        if kind in (1, 3):                            # half2, half4
            return np.frombuffer(chunk, dtype="<f2").reshape(count, -1).astype(float)
        return np.frombuffer(chunk, dtype=np.uint8).reshape(count, -1).astype(float)

    index_count, = res.unpack("<I", index_buffer, 0x08)
    indices_pointer, = res.unpack("<Q", index_buffer, 0x10)
    ibuf, ibase = res.at(indices_pointer)
    indices = np.frombuffer(ibuf[ibase:ibase + 2 * index_count], dtype="<u2").reshape(-1, 3)
    geometry = dict(positions=component("position"), triangles=indices, layout=layout, stride=stride)
    if "normal" in layout:
        geometry["normals"] = component("normal")
    if "uv0" in layout:
        geometry["uvs"] = component("uv0")
    return geometry


def read_model(res, pointer):
    geometries_pointer, count = res.unpack("<QH", pointer, 0x08)
    shader_map, = res.unpack("<Q", pointer, 0x20)
    bone, = res.unpack("<I", pointer, 0x28)
    geometries = []
    for i in range(count):
        g = read_geometry(res, res.u64(geometries_pointer, 8 * i))
        g["shader"], = res.unpack("<H", shader_map, 2 * i)
        geometries.append(g)
    return dict(geometries=geometries, skeleton_binding=bone)


def read_fragment(path):
    """dict(lods={'high': [models], ...}, bounds=(min, max)) for the fragment's main drawable."""
    res = Resource(path)
    return _read_drawable(res, res.u64(0x50000000, 0x30))


def read_drawable(path):
    """The same for a .ydr, whose root is the drawable."""
    return _read_drawable(Resource(path), 0x50000000)


def read_dictionary(path):
    """The drawables of a .ydd (drawable dictionary), whose root lists them at +0x30."""
    res = Resource(path)
    return [_read_drawable(res, d) for d in res.pointer_list(0x50000000 + 0x30)]


def _read_drawable(res, drawable):
    box_min = res.unpack("<3f", drawable, 0x30)
    box_max = res.unpack("<3f", drawable, 0x40)
    lods = {}
    for name, offset in (("high", 0x50), ("medium", 0x58), ("low", 0x60), ("very_low", 0x68)):
        pointer = res.u64(drawable, offset)
        if pointer:
            lods[name] = [read_model(res, m) for m in res.pointer_list(pointer)]
    return dict(lods=lods, bounds=(box_min, box_max), resource=res, drawable=drawable)


def main(argv):
    frag = read_fragment(argv[1])
    print("bounds", [round(v, 3) for v in frag["bounds"][0]], [round(v, 3) for v in frag["bounds"][1]])
    for lod, models in frag["lods"].items():
        verts = sum(len(g["positions"]) for m in models for g in m["geometries"])
        tris = sum(len(g["triangles"]) for m in models for g in m["geometries"])
        print(f"{lod}: {len(models)} models, {verts} vertices, {tris} triangles")
        for i, m in enumerate(models[:40]):
            geos = m["geometries"]
            print(f"   model {i} bone {m['skeleton_binding'] >> 24 & 0xFF}: "
                  + ", ".join(f"{len(g['positions'])}v/{len(g['triangles'])}t s{g['shader']}" for g in geos[:6])
                  + (" ..." if len(geos) > 6 else ""))


if __name__ == "__main__":
    main(sys.argv)
