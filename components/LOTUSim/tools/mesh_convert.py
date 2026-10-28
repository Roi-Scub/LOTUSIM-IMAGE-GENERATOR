"""Strict local static-mesh conversion for the automatic Unity import bridge.

No converter subprocess, source script, scene camera, light, animation or remote
resource is executed. Input bytes must already be quarantined by mesh_library.
Requires numpy and Pillow, deliberately isolated from the stdlib dashboard.
"""
import base64
import binascii
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import posixpath
import re
import struct
from urllib.parse import unquote, urlsplit

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_VERTICES = 2000000
MAX_INDICES = 6000000
MAX_MATERIALS = 200
MAX_NODES = 10000
MAX_IMAGE_PIXELS = 16777216
EPS = 1e-9


class MeshConvertError(ValueError):
    pass


def require(value, message):
    if not value:
        raise MeshConvertError(message)


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field.')
            result[key] = value
        return result
    def bad_constant(value):
        raise MeshConvertError('Nonfinite JSON value.')
    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_constant=bad_constant)
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            require(depth <= 64, 'JSON nesting limit exceeded.')
            if isinstance(value, float):
                require(math.isfinite(value), 'Nonfinite JSON value.')
            elif isinstance(value, dict):
                pending.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list):
                pending.extend((v, depth + 1) for v in value)
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        if isinstance(error, MeshConvertError):
            raise
        raise MeshConvertError('Invalid model JSON.') from error


def finite_vector(value, width, message):
    require(isinstance(value, (list, tuple)) and len(value) == width and
            all(type(x) in (int, float) and math.isfinite(x) for x in value), message)
    return np.asarray(value, dtype=np.float64)


def integer(value, low, high, message):
    require(type(value) is int and low <= value <= high, message)
    return value


def index(items, value, message):
    require(isinstance(items, list), message)
    return items[integer(value, 0, len(items) - 1, message)]


def scalar(value, low, high, message):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, message)
    return float(value)


def safe_path(name):
    require(isinstance(name, str) and 0 < len(name) <= 240 and '\\' not in name and '\0' not in name,
            'Invalid source resource path.')
    require(not name.startswith('/') and all(p and p not in ('.', '..') and not p.startswith('.') for p in name.split('/')),
            'Unsafe source resource path.')
    return name


def resolve_resource(uri, parent, files):
    require(isinstance(uri, str), 'Invalid resource URI.')
    if uri.startswith('data:'):
        match = re.fullmatch(r'data:(application/(?:octet-stream|gltf-buffer)|image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\r\n]+)', uri)
        require(match is not None, 'Unsupported embedded resource type.')
        try:
            value = base64.b64decode(match.group(2), validate=True)
        except binascii.Error as error:
            raise MeshConvertError('Invalid embedded base64 data.') from error
        require(len(value) <= MAX_SOURCE_BYTES, 'Embedded resource too large.')
        return value
    try:
        parts = urlsplit(uri)
    except ValueError as error:
        raise MeshConvertError('Invalid resource URI.') from error
    require(not (parts.scheme or parts.netloc or parts.query or parts.fragment) and
            not uri.startswith('/') and '\\' not in uri, 'Remote or absolute resources are not allowed.')
    name = posixpath.normpath(posixpath.join(str(PurePosixPath(parent).parent), unquote(parts.path)))
    safe_path(name)
    require(name in files, 'Missing local resource: ' + name)
    return files[name]


def default_material(name='Material'):
    return dict(name=str(name)[:150], color=[.65, .7, .75, 1.0], emission=[0.0, 0.0, 0.0],
                metallic=0.0, smoothness=.35, normalScale=1.0, coat=0.0,
                doubleSided=False, sourceAlpha='OPAQUE', baseMap='', normalMap='', maskMap='', emissionMap='')


class Images:
    def __init__(self):
        self.output = {}
        self.total = 0
    def decode(self, data):
        require(isinstance(data, bytes) and len(data) <= MAX_SOURCE_BYTES, 'Invalid image bytes.')
        try:
            with Image.open(io.BytesIO(data)) as source:
                require(source.width > 0 and source.height > 0 and source.width * source.height <= MAX_IMAGE_PIXELS,
                        'Texture exceeds the 16-megapixel limit.')
                require(source.format in ('PNG', 'JPEG', 'WEBP', 'TGA', 'BMP'), 'Unsupported texture encoding.')
                require(getattr(source, 'n_frames', 1) == 1, 'Animated textures are unsupported.')
                value = source.convert('RGBA')
                value.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                return value
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise MeshConvertError('Texture cannot be decoded safely.') from error
    def add(self, name, image, flip=False):
        require(len(self.output) < MAX_MATERIALS * 4, 'Too many texture maps.')
        stream = io.BytesIO()
        (ImageOps.flip(image) if flip else image).save(stream, format='PNG')
        data = stream.getvalue()
        self.total += len(data)
        require(self.total < MAX_OUTPUT_BYTES, 'Converted textures exceed the output limit.')
        self.output[name] = data
        return name


def normals_for(positions, triangles):
    result = np.zeros_like(positions, dtype=np.float64)
    a, b, c = positions[triangles[:, 0]], positions[triangles[:, 1]], positions[triangles[:, 2]]
    cross = np.cross(b - a, c - a)
    require(np.isfinite(cross).all(), 'Invalid triangle normal.')
    for corner in range(3):
        np.add.at(result, triangles[:, corner], cross)
    norm = np.linalg.norm(result, axis=1)
    require(np.all(norm > EPS), 'Mesh contains degenerate or unused vertices without usable normals.')
    return result / norm[:, None]


def obj_parts(entry, files, images):
    materials = [default_material()]
    material_names = {'': 0}
    current = 0
    groups = {}
    positions, uv, normals = [], [], []
    try:
        lines = files[entry].decode('utf-8-sig').splitlines()
    except UnicodeError as error:
        raise MeshConvertError('OBJ must be UTF-8 text.') from error
    for original in lines:
        line = original.split('#', 1)[0]
        tokens = line.strip().split()
        if not tokens or tokens[0].startswith('#'):
            continue
        kind = tokens[0]
        if kind == 'mtllib':
            require(len(tokens) >= 2, 'Missing OBJ material library.')
            name = line.strip()[len('mtllib'):].strip()
            raw = resolve_resource(name, entry, files)
            material_path = posixpath.normpath(posixpath.join(posixpath.dirname(entry), name))
            active = None
            for material_original in raw.decode('utf-8-sig').splitlines():
                material_line = material_original.split('#', 1)[0]
                fields = material_line.strip().split(None, 1)
                if not fields or fields[0].startswith('#'):
                    continue
                if fields[0] == 'newmtl':
                    require(len(fields) == 2 and len(materials) < MAX_MATERIALS, 'Invalid or excessive MTL materials.')
                    require(fields[1] not in material_names, 'Duplicate MTL material name.')
                    active = default_material(fields[1]); material_names[fields[1]] = len(materials); materials.append(active)
                elif active is not None and fields[0] in ('Kd', 'Ke'):
                    require(len(fields) == 2, 'Invalid MTL color.')
                    numbers = [float(x) for x in fields[1].split()]
                    color = finite_vector(numbers, 3, 'Invalid MTL color.')
                    require(np.all(color >= 0) and np.all(color <= (1 if fields[0] == 'Kd' else 100)), 'MTL color out of range.')
                    active['color' if fields[0] == 'Kd' else 'emission'] = color.tolist() + ([1.0] if fields[0] == 'Kd' else [])
                elif active is not None and fields[0] in ('d', 'Tr'):
                    opacity = float(fields[1]); require(math.isfinite(opacity) and 0 <= opacity <= 1, 'Invalid MTL opacity.')
                    if opacity != (1 if fields[0] == 'd' else 0):
                        active['sourceAlpha'] = 'BLEND'
                elif active is not None and fields[0].lower() in ('map_kd', 'map_ke', 'map_bump', 'bump'):
                    require(len(fields) == 2 and not fields[1].startswith('-'), 'MTL texture options unsupported; export GLB instead.')
                    slot = {'map_kd': 'baseMap', 'map_ke': 'emissionMap', 'map_bump': 'normalMap', 'bump': 'normalMap'}[fields[0].lower()]
                    # A bump map is a scalar height, not a tangent-space normal.
                    require(slot != 'normalMap', 'MTL height/bump maps need explicit normal conversion; export GLB.')
                    image = images.decode(resolve_resource(fields[1], material_path, files))
                    active[slot] = images.add('material_%03d_%s.png' % (len(materials) - 1, slot), image)
            continue
        if kind == 'v':
            require(len(tokens) in (4, 5), 'OBJ vertex colors are unsupported; export textured GLB.')
            vertex = [float(x) for x in tokens[1:4]]
            require(all(math.isfinite(x) and abs(x) < 1e9 for x in vertex), 'Invalid OBJ position.')
            if len(tokens) == 5:
                require(float(tokens[4]) == 1, 'Homogeneous OBJ vertex coordinates unsupported.')
            positions.append(vertex); require(len(positions) <= MAX_VERTICES, 'Too many OBJ positions.')
        elif kind == 'vt':
            require(len(tokens) in (3, 4), 'Invalid OBJ UV.')
            values = [float(x) for x in tokens[1:3]]
            require(all(math.isfinite(x) and abs(x) < 1e9 for x in values), 'Invalid OBJ UV.')
            uv.append(values); require(len(uv) <= MAX_VERTICES, 'Too many OBJ UVs.')
        elif kind == 'vn':
            require(len(tokens) == 4, 'Invalid OBJ normal.')
            values = [float(x) for x in tokens[1:]]
            require(all(math.isfinite(x) for x in values), 'Invalid OBJ normal.')
            normals.append(values); require(len(normals) <= MAX_VERTICES, 'Too many OBJ normals.')
        elif kind == 'usemtl':
            name = line.strip()[len('usemtl'):].strip()
            require(name in material_names, 'OBJ references an undeclared material.')
            current = material_names[name]
        elif kind == 'f':
            require(4 <= len(tokens) <= 1025, 'OBJ face must have 3–1024 corners.')
            group = groups.setdefault(current, {'map': {}, 'vertices': [], 'normals': [], 'uv': [], 'faces': [], 'missing': False})
            corners = []
            for token in tokens[1:]:
                fields = token.split('/'); require(1 <= len(fields) <= 3, 'Invalid OBJ face.')
                values = []
                for component, length in zip(fields + [''] * (3 - len(fields)), (len(positions), len(uv), len(normals))):
                    if not component:
                        values.append(None); continue
                    number = int(component); require(number != 0, 'OBJ indices start at one.')
                    resolved = number - 1 if number > 0 else length + number
                    require(0 <= resolved < length, 'OBJ index outside available data.'); values.append(resolved)
                require(values[0] is not None, 'OBJ position index required.')
                key = tuple(values)
                if key not in group['map']:
                    group['map'][key] = len(group['vertices']); group['vertices'].append(positions[key[0]])
                    group['uv'].append(uv[key[1]] if key[1] is not None else [0, 0])
                    group['normals'].append(normals[key[2]] if key[2] is not None else [0, 0, 0])
                    group['missing'] |= key[2] is None
                corners.append(group['map'][key])
            for n in range(1, len(corners) - 1):
                group['faces'].append([corners[0], corners[n], corners[n + 1]])
            require(sum(len(g['faces']) * 3 for g in groups.values()) <= MAX_INDICES and
                    sum(len(g['vertices']) for g in groups.values()) <= MAX_VERTICES, 'Expanded OBJ exceeds geometry limits.')
        elif kind in ('curv', 'curv2', 'surf', 'l', 'p'):
            raise MeshConvertError('Only OBJ polygon surfaces are supported; curves/lines/points need a mesh export.')
    parts = []
    for material, group in groups.items():
        p = np.asarray(group['vertices'], dtype=np.float64); f = np.asarray(group['faces'], dtype=np.int32)
        n = normals_for(p, f) if group['missing'] else np.asarray(group['normals'], dtype=np.float64)
        parts.append([material, p, n, np.asarray(group['uv'], dtype=np.float64), f])
    return parts, materials


def stl_parts(entry, files):
    raw = files[entry]
    binary = len(raw) >= 84 and 84 + struct.unpack_from('<I', raw, 80)[0] * 50 == len(raw)
    if binary:
        count = struct.unpack_from('<I', raw, 80)[0]
        require(0 < count <= MAX_INDICES // 3 and count * 3 <= MAX_VERTICES, 'STL exceeds triangle limit.')
        # STL normals are frequently zero or stale: derive from geometry.
        dtype = np.dtype([('normal', '<f4', (3,)), ('vertices', '<f4', (3, 3)), ('attribute', '<u2')])
        p = np.frombuffer(raw, dtype=dtype, count=count, offset=84)['vertices'].reshape(-1, 3).astype(np.float64)
    else:
        require(raw.lstrip().startswith(b'solid'), 'Invalid STL header.')
        vertices = []
        for line in raw.decode('ascii').splitlines():
            tokens = line.strip().split()
            if tokens and tokens[0] == 'vertex':
                require(len(tokens) == 4, 'Invalid STL vertex.')
                vertices.append([float(x) for x in tokens[1:]])
                require(len(vertices) <= MAX_VERTICES, 'STL exceeds vertex limit.')
        require(vertices and len(vertices) % 3 == 0 and b'endsolid' in raw, 'Incomplete STL triangles.')
        p = np.asarray(vertices, dtype=np.float64)
    require(np.isfinite(p).all() and np.abs(p).max() < 1e9, 'Invalid STL coordinates.')
    f = np.arange(len(p), dtype=np.int32).reshape(-1, 3)
    return [[0, p, normals_for(p, f), np.zeros((len(p), 2)), f]], [default_material('STL material')]


class Gltf:
    def __init__(self, entry, files, images):
        self.entry, self.files, self.images = entry, files, images
        raw = files[entry]
        embedded = None
        if entry.lower().endswith('.glb'):
            require(len(raw) >= 20, 'Incomplete GLB.')
            magic, version, length = struct.unpack_from('<III', raw)
            require(magic == 0x46546C67 and version == 2 and length == len(raw), 'Invalid GLB 2.0 header.')
            offset, chunks = 12, []
            while offset < len(raw):
                require(offset + 8 <= len(raw), 'Truncated GLB chunk.')
                size, kind = struct.unpack_from('<II', raw, offset)
                require(size % 4 == 0 and offset + 8 + size <= len(raw), 'Invalid GLB chunk size.')
                chunks.append((kind, raw[offset + 8:offset + 8 + size])); offset += 8 + size
            require(len(chunks) in (1, 2) and chunks[0][0] == 0x4E4F534A and
                    (len(chunks) == 1 or chunks[1][0] == 0x004E4942), 'GLB must contain JSON and optional BIN only.')
            self.doc = strict_json(chunks[0][1]); embedded = chunks[1][1] if len(chunks) == 2 else None
        else:
            self.doc = strict_json(raw)
        d = self.doc
        require(isinstance(d, dict) and isinstance(d.get('asset'), dict) and d['asset'].get('version') == '2.0', 'glTF 2.0 is required.')
        for key in ('nodes', 'meshes', 'scenes', 'accessors', 'bufferViews', 'buffers', 'materials', 'textures', 'images'):
            require(isinstance(d.get(key, []), list), 'Invalid glTF ' + key + ' array.')
        for key in ('animations', 'skins', 'extensionsRequired', 'extensionsUsed'):
            require(isinstance(d.get(key, []), list), 'Invalid glTF ' + key + ' array.')
        require(not d.get('animations') and not d.get('skins'), 'Animated or skinned glTF is unsupported; export a static mesh.')
        require(not d.get('extensionsRequired'), 'Required glTF extensions are unsupported; export core glTF 2.0.')
        require(0 < len(d.get('nodes', [])) <= MAX_NODES and len(d.get('materials', [])) <= MAX_MATERIALS,
                'Missing or excessive glTF nodes/materials.')
        self.buffers = []
        for number, buffer in enumerate(d.get('buffers', [])):
            require(isinstance(buffer, dict), 'Invalid glTF buffer.')
            data = resolve_resource(buffer['uri'], entry, files) if 'uri' in buffer else embedded if number == 0 else None
            require(isinstance(data, bytes), 'Missing glTF buffer.')
            expected = integer(buffer.get('byteLength'), 0, MAX_SOURCE_BYTES, 'Invalid glTF buffer length.')
            require(expected <= len(data) and len(data) - expected <= (3 if 'uri' not in buffer else 0), 'glTF buffer length mismatch.')
            self.buffers.append(data[:expected])
        require(sum(len(b) for b in self.buffers) <= MAX_SOURCE_BYTES, 'Decoded glTF buffers exceed input limit.')
        self.world, self.parents = {}, {}
        scene = index(d.get('scenes', []), d.get('scene', 0), 'Invalid glTF scene.')
        require(isinstance(scene, dict) and isinstance(scene.get('nodes'), list), 'Missing glTF scene roots.')
        for root in scene['nodes']:
            self.visit(root, np.eye(4), set())

    def visit(self, number, parent, ancestors):
        node = index(self.doc['nodes'], number, 'Invalid glTF node index.')
        require(isinstance(node, dict) and number not in ancestors and number not in self.world and len(ancestors) <= 128,
                'Cyclic/shared/deep glTF node hierarchy.')
        require('skin' not in node and 'weights' not in node, 'Skinned/morph node unsupported.')
        if 'matrix' in node:
            require(not any(key in node for key in ('translation', 'rotation', 'scale')), 'glTF node combines matrix and TRS.')
            matrix = finite_vector(node['matrix'], 16, 'Invalid glTF matrix.').reshape(4, 4, order='F')
            require(np.allclose(matrix[3], [0, 0, 0, 1]), 'Perspective glTF transform unsupported.')
        else:
            translation = finite_vector(node.get('translation', [0, 0, 0]), 3, 'Invalid glTF translation.')
            scaling = finite_vector(node.get('scale', [1, 1, 1]), 3, 'Invalid glTF scale.')
            q = finite_vector(node.get('rotation', [0, 0, 0, 1]), 4, 'Invalid glTF rotation.')
            require(abs(np.linalg.norm(q) - 1) < .001, 'glTF quaternion must be normalized.')
            x, y, z, w = q
            rotation = np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
            matrix = np.eye(4); matrix[:3, :3] = rotation @ np.diag(scaling); matrix[:3, 3] = translation
        world = parent @ matrix
        determinant = np.linalg.det(world[:3, :3])
        require(np.isfinite(world).all() and math.isfinite(determinant) and abs(determinant) > EPS,
                'Singular/nonfinite glTF transform.')
        self.world[number] = world
        children = node.get('children', []); require(isinstance(children, list), 'Invalid glTF children.')
        for child in children:
            self.visit(child, world, ancestors | {number})

    def view(self, number):
        view = index(self.doc.get('bufferViews', []), number, 'Invalid glTF buffer view.')
        require(isinstance(view, dict) and not view.get('extensions'), 'Compressed glTF buffer view unsupported.')
        data = index(self.buffers, view.get('buffer', 0), 'Invalid glTF buffer index.')
        begin = integer(view.get('byteOffset', 0), 0, len(data), 'Invalid buffer view offset.')
        length = integer(view.get('byteLength'), 0, len(data) - begin, 'Invalid buffer view length.')
        return view, data, begin, length

    def accessor(self, number, widths=None):
        value = index(self.doc.get('accessors', []), number, 'Invalid glTF accessor.')
        require(isinstance(value, dict) and not value.get('sparse'), 'Sparse/invalid glTF accessor unsupported.')
        types = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
        require(value.get('componentType') in types and value.get('type') in ('SCALAR', 'VEC2', 'VEC3', 'VEC4'), 'Unsupported glTF accessor type.')
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[value['type']]
        if widths is not None:
            require(width in widths, 'glTF accessor has the wrong width.')
        count = integer(value.get('count'), 1, MAX_INDICES if width == 1 else MAX_VERTICES, 'glTF accessor allocation exceeds limits.')
        view, data, begin, length = self.view(value.get('bufferView'))
        dtype = np.dtype(types[value['componentType']]); size = width * dtype.itemsize
        stride = integer(view.get('byteStride', size), size, 252, 'Invalid accessor stride.')
        offset = integer(value.get('byteOffset', 0), 0, length, 'Invalid accessor offset.')
        require(stride % dtype.itemsize == 0 and (begin + offset) % dtype.itemsize == 0 and
                offset + (count - 1) * stride + size <= length, 'glTF accessor extends beyond its buffer view.')
        result = np.ndarray((count, width), dtype=dtype, buffer=data, offset=begin + offset, strides=(stride, dtype.itemsize)).copy()
        if value.get('normalized'):
            require(value['componentType'] != 5126 and value['componentType'] != 5125, 'Invalid normalized glTF component type.')
            result = np.maximum(result.astype(np.float64) / np.iinfo(dtype).max, -1)
        require(np.isfinite(result).all(), 'Nonfinite glTF accessor.')
        return result

    def image(self, slot):
        require(isinstance(slot, dict) and slot.get('texCoord', 0) == 0 and not slot.get('extensions'), 'Secondary/transformed texture coordinates unsupported.')
        texture = index(self.doc.get('textures', []), slot.get('index'), 'Invalid glTF texture.')
        require(isinstance(texture, dict) and not texture.get('extensions'), 'Compressed/extended textures unsupported.')
        value = index(self.doc.get('images', []), texture.get('source'), 'Invalid glTF image.')
        require(isinstance(value, dict), 'Invalid glTF image.')
        if 'uri' in value:
            data = resolve_resource(value['uri'], self.entry, self.files)
        else:
            _, buffer, begin, length = self.view(value.get('bufferView'))
            data = buffer[begin:begin + length]
        return self.images.decode(data)

    def materials(self):
        values = self.doc.get('materials', []) or [{}]
        result = []
        for number, raw in enumerate(values):
            require(isinstance(raw, dict), 'Invalid glTF material.')
            pbr = raw.get('pbrMetallicRoughness', {}); require(isinstance(pbr, dict), 'Invalid glTF material PBR.')
            m = default_material(raw.get('name', 'material_%d' % number))
            color = finite_vector(pbr.get('baseColorFactor', [1, 1, 1, 1]), 4, 'Invalid glTF base color.')
            require(np.all(color >= 0) and np.all(color <= 1), 'glTF base color out of range.')
            color[3] = 1; m['color'] = color.tolist()
            m['metallic'] = scalar(pbr.get('metallicFactor', 1), 0, 1, 'Invalid metallic factor.')
            m['smoothness'] = 1 - scalar(pbr.get('roughnessFactor', 1), 0, 1, 'Invalid roughness factor.')
            emission = finite_vector(raw.get('emissiveFactor', [0, 0, 0]), 3, 'Invalid emission.')
            require(np.all(emission >= 0) and np.all(emission <= 100), 'Emission out of range.')
            m['emission'] = emission.tolist(); m['doubleSided'] = raw.get('doubleSided', False) is True
            m['sourceAlpha'] = raw.get('alphaMode', 'OPAQUE')
            require(m['sourceAlpha'] in ('OPAQUE', 'MASK', 'BLEND'), 'Invalid glTF alpha mode.')
            for slot, target in ((pbr.get('baseColorTexture'), 'baseMap'), (raw.get('normalTexture'), 'normalMap'), (raw.get('emissiveTexture'), 'emissionMap')):
                if slot is not None:
                    m[target] = self.images.add('material_%03d_%s.png' % (number, target), self.image(slot), flip=True)
                    if target == 'normalMap':
                        m['normalScale'] = scalar(slot.get('scale', 1), 0, 10, 'Invalid normal scale.')
            mr, ao = pbr.get('metallicRoughnessTexture'), raw.get('occlusionTexture')
            if mr is not None or ao is not None:
                image = self.image(mr if mr is not None else ao)
                width, height = image.size
                mask = np.full((height, width, 4), 255, dtype=np.uint8)
                mask[:, :, 0] = round(m['metallic'] * 255); mask[:, :, 3] = round(m['smoothness'] * 255)
                if mr is not None:
                    pixels = np.asarray(self.image(mr).resize((width, height)))
                    mask[:, :, 0] = np.rint(pixels[:, :, 2] * m['metallic']).astype(np.uint8)
                    mask[:, :, 3] = np.rint(255 - pixels[:, :, 1] * (1 - m['smoothness'])).astype(np.uint8)
                if ao is not None:
                    strength = scalar(ao.get('strength', 1), 0, 1, 'Invalid occlusion strength.')
                    pixels = np.asarray(self.image(ao).resize((width, height)))
                    mask[:, :, 1] = np.rint(255 + (pixels[:, :, 0].astype(float) - 255) * strength).astype(np.uint8)
                m['maskMap'] = self.images.add('material_%03d_mask.png' % number, Image.fromarray(mask), flip=True)
            result.append(m)
        return result

    def parts(self):
        result = []
        for number, matrix in self.world.items():
            node = self.doc['nodes'][number]
            if 'mesh' not in node:
                continue
            mesh = index(self.doc.get('meshes', []), node['mesh'], 'Invalid mesh index.')
            require(isinstance(mesh, dict) and isinstance(mesh.get('primitives'), list) and not mesh.get('weights'), 'Invalid/morph mesh.')
            for primitive in mesh['primitives']:
                require(isinstance(primitive, dict) and primitive.get('mode', 4) == 4 and not primitive.get('targets') and not primitive.get('extensions'),
                        'Only uncompressed static triangle primitives are supported.')
                a = primitive.get('attributes'); require(isinstance(a, dict) and 'POSITION' in a, 'glTF primitive needs positions.')
                require(not any(key.startswith(('JOINTS_', 'WEIGHTS_')) for key in a), 'Skin attributes unsupported.')
                require(not any(key.startswith('COLOR_') for key in a), 'Vertex-color glTF unsupported; bake to a texture.')
                require(not any(key.startswith('TEXCOORD_') and key != 'TEXCOORD_0' for key in a), 'Secondary UV sets unsupported.')
                position_accessor = index(self.doc.get('accessors', []), a['POSITION'], 'Invalid position accessor.')
                require(isinstance(position_accessor, dict) and position_accessor.get('componentType') == 5126,
                        'Core glTF positions must use FLOAT components.')
                p = self.accessor(a['POSITION'], (3,)).astype(np.float64)
                require(np.abs(p).max() < 1e9, 'glTF coordinates out of range.')
                if 'indices' in primitive:
                    accessor = index(self.doc['accessors'], primitive['indices'], 'Invalid indices accessor.')
                    require(accessor.get('componentType') in (5121, 5123, 5125) and not accessor.get('normalized'), 'glTF indices must be unsigned integers.')
                    indices = self.accessor(primitive['indices'], (1,)).reshape(-1)
                else:
                    indices = np.arange(len(p), dtype=np.int32)
                require(0 < len(indices) <= MAX_INDICES and len(indices) % 3 == 0 and indices.min() >= 0 and indices.max() < len(p), 'Invalid triangle indices.')
                f = indices.astype(np.int32).reshape(-1, 3)
                n = self.accessor(a['NORMAL'], (3,)).astype(np.float64) if 'NORMAL' in a else normals_for(p, f)
                uv = self.accessor(a['TEXCOORD_0'], (2,)).astype(np.float64) if 'TEXCOORD_0' in a else np.zeros((len(p), 2))
                raw_materials = self.doc.get('materials', [])
                if raw_materials and 'TEXCOORD_0' not in a:
                    raw_material = index(raw_materials, primitive.get('material', 0), 'Invalid material index.')
                    require(isinstance(raw_material, dict) and isinstance(raw_material.get('pbrMetallicRoughness', {}), dict),
                            'Invalid primitive material.')
                    pbr = raw_material.get('pbrMetallicRoughness', {})
                    require(not any(pbr.get(key) is not None for key in ('baseColorTexture', 'metallicRoughnessTexture')) and
                            not any(raw_material.get(key) is not None for key in ('normalTexture', 'emissiveTexture', 'occlusionTexture')),
                            'Textured glTF primitive needs TEXCOORD_0; UVs are not synthesized.')
                require(len(n) == len(p) and len(uv) == len(p), 'glTF vertex attribute length mismatch.')
                p = np.column_stack((p, np.ones(len(p)))) @ matrix.T
                n = n @ np.linalg.inv(matrix[:3, :3])
                if np.linalg.det(matrix[:3, :3]) < 0:
                    f = f[:, [0, 2, 1]]
                result.append([primitive.get('material', 0), p[:, :3], n, uv, f])
                require(sum(len(part[1]) for part in result) <= MAX_VERTICES and
                        sum(part[4].size for part in result) <= MAX_INDICES, 'Expanded glTF scene exceeds limits.')
        return result


def convert(entry, files, metadata, output):
    """Convert one validated upload into a neutral static bundle in an empty directory.

    metadata: model, category, label, license, sourceUrl, domain, upAxis,
    forwardAxis, metresPerUnit, draftM. Units/orientation are user assumptions,
    never inferred as real-world capabilities from geometry.
    """
    try:
        return _convert(entry, files, metadata, Path(output))
    except (MeshConvertError, OSError):
        raise
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError, struct.error, OverflowError, np.linalg.LinAlgError) as error:
        raise MeshConvertError('Invalid or unsupported static mesh data.') from error


def gazebo_files(grouped, materials, remaining):
    """Export the same static surfaces to Gazebo X-forward/Y-port/Z-up.

    The neutral bundle uses Unity Y-up. Swapping Y/Z is a reflection, hence
    winding is reversed again, rather than merely changing vertex coordinates.
    """
    obj, mtl = io.BytesIO(), io.BytesIO()
    def write(stream, value):
        stream.write(value.encode('utf-8'))
        require(obj.tell() + mtl.tell() <= remaining, 'Gazebo mesh makes the bundle exceed 256 MiB; use a lower-detail static export.')
    write(obj, '# Static local mesh. Metres; X forward, Y port, Z up.\nmtllib gazebo.mtl\n')
    offset = 1
    for material, vertices, faces in grouped:
        for vertex in vertices:
            write(obj, 'v %.8g %.8g %.8g\n' % (vertex[0], vertex[2], vertex[1]))
        for vertex in vertices:
            write(obj, 'vt %.8g %.8g\n' % (vertex[6], vertex[7]))
        for vertex in vertices:
            write(obj, 'vn %.8g %.8g %.8g\n' % (vertex[3], vertex[5], vertex[4]))
        write(obj, 'usemtl material_%d\n' % material)
        for face in faces[:, [0, 2, 1]] + offset:
            write(obj, 'f ' + ' '.join('%d/%d/%d' % (v, v, v) for v in face) + '\n')
        offset += len(vertices)
    for number, material in enumerate(materials):
        write(mtl, 'newmtl material_%d\nKd %.8g %.8g %.8g\nd 1\n' %
              (number, *material['color'][:3]))
        if material['baseMap']:
            write(mtl, 'map_Kd ' + material['baseMap'] + '\n')
        write(mtl, '\n')
    return obj.getvalue(), mtl.getvalue()


def _convert(entry, files, metadata, output):
    require(isinstance(files, dict) and 0 < len(files) <= 100 and isinstance(metadata, dict), 'Invalid conversion request.')
    require(all(isinstance(value, bytes) for value in files.values()) and sum(map(len, files.values())) <= MAX_SOURCE_BYTES, 'Source data exceeds 64 MiB.')
    for name in files:
        safe_path(name)
    require(entry in files, 'Entry file not found.')
    suffix = PurePosixPath(entry).suffix.lower(); require(suffix in ('.obj', '.stl', '.glb', '.gltf'), 'Unsupported conversion format.')
    model = metadata.get('model', metadata.get('key'))
    require(isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', model), 'Invalid model key.')
    category = metadata.get('category'); require(isinstance(category, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,59}', category), 'Invalid category.')
    unit = scalar(metadata.get('metresPerUnit', 1), .000001, 10000, 'Invalid metres-per-unit scale.')
    up = metadata.get('upAxis', 'Y'); require(up in ('Y', 'Z'), 'Up axis must be Y or Z.')
    forward = metadata.get('forwardAxis', '+X' if up == 'Z' else '+Z')
    axes = {'+X': [1, 0, 0], '-X': [-1, 0, 0], '+Y': [0, 1, 0], '-Y': [0, -1, 0], '+Z': [0, 0, 1], '-Z': [0, 0, -1]}
    require(forward in axes, 'Invalid forward axis.')
    u = np.array([0, 1, 0] if up == 'Y' else [0, 0, 1]); fwd = np.asarray(axes[forward])
    require(float(np.dot(u, fwd)) == 0, 'Forward and up axes must be perpendicular.')
    basis = np.array([fwd, u, np.cross(u, fwd)], dtype=np.float64)
    images = Images()
    if suffix == '.obj':
        parts, materials = obj_parts(entry, files, images)
    elif suffix == '.stl':
        parts, materials = stl_parts(entry, files)
    else:
        gltf = Gltf(entry, files, images)
        # glTF axes are Y-up by specification. A Z-up override would silently
        # contradict scene node transforms and source standard metadata.
        require(up == 'Y', 'glTF/GLB uses Y-up; export axes correctly rather than overriding to Z.')
        parts, materials = gltf.parts(), gltf.materials()
    require(parts and 0 < len(materials) <= MAX_MATERIALS, 'Mesh has no renderable triangle surfaces.')
    require(sum(len(p[1]) for p in parts) <= MAX_VERTICES and sum(p[4].size for p in parts) <= MAX_INDICES, 'Geometry exceeds conversion limits.')
    low = np.full(3, np.inf); high = np.full(3, -np.inf)
    for part in parts:
        material, positions, normals, uv, faces = part
        integer(material, 0, len(materials) - 1, 'Invalid material index.')
        require(len(positions) >= 3 and faces.ndim == 2 and faces.shape[1] == 3 and faces.size > 0, 'Invalid triangle batch.')
        require(np.isfinite(positions).all() and np.isfinite(normals).all() and np.isfinite(uv).all(), 'Nonfinite mesh geometry.')
        positions = positions @ basis.T * unit
        normals = normals @ basis.T
        norm = np.linalg.norm(normals, axis=1); require(np.all(norm > EPS), 'Zero normal vector.')
        part[1], part[2] = positions, normals / norm[:, None]
        if np.linalg.det(basis) < 0:
            part[4] = faces[:, [0, 2, 1]]
        low = np.minimum(low, positions.min(axis=0)); high = np.maximum(high, positions.max(axis=0))
    size = high - low
    require(np.isfinite(size).all() and size.max() > EPS and size.max() <= 1000000, 'Invalid or excessive model dimensions.')
    draft = scalar(metadata.get('draftM', 0), 0, max(float(size[1]), .001), 'Draft exceeds model height.')
    domain = metadata.get('domain', 'moored'); require(domain in ('air', 'sea', 'moored'), 'Invalid movement domain.')
    shift = -(low + high) / 2
    shift[1] = -(low[1] + high[1]) / 2 if domain == 'air' else -draft - low[1]
    for part in parts:
        part[1] += shift
    grouped = []
    for material in sorted(set(p[0] for p in parts)):
        selected = [p for p in parts if p[0] == material]
        vertices, faces, offset = [], [], 0
        for _, p, n, uv, f in selected:
            vertices.append(np.column_stack((p, n, uv)).astype('<f4'))
            faces.append(f + offset); offset += len(p)
        grouped.append((material, np.concatenate(vertices), np.concatenate(faces).astype('<i4')))
    stream = io.BytesIO(); stream.write(struct.pack('<II', 0x4C424D31, len(grouped)))
    for material, vertices, faces in grouped:
        stream.write(struct.pack('<III', material, len(vertices), faces.size)); stream.write(vertices.tobytes()); stream.write(faces.tobytes())
    require(stream.tell() + images.total <= MAX_OUTPUT_BYTES, 'Converted bundle exceeds 256 MiB.')
    changes = ['Static geometry only; no source scripts, cameras, lights, rig or animation imported',
               'User-declared units and axes; dimensions are geometric bounds, not certified real-world measurements',
               'Normalized to metres, Unity +X forward +Y up +Z port; pivot placed at declared waterline or air centre',
               'Opaque material approximation for existing nearest-depth annotation policy; transparency/transmission not physically equivalent',
               'glTF PBR factors/maps approximated by existing HDRP material workflow; no hydrodynamic calibration']
    if np.any(size < .001):
        changes.append('Zero/thin dimensions use a 1 mm bounding proxy; original geometry is not inflated')
    effective = np.maximum(size, .001)
    info = dict(key=model, category=category, title=str(metadata.get('label', model))[:150],
                author=str(metadata.get('author', 'User-supplied local asset'))[:200],
                source=str(metadata.get('sourceUrl', ''))[:1500], license=str(metadata.get('license', 'To verify'))[:1000],
                licenseUrl='', sha256=hashlib.sha256(files[entry]).hexdigest(),
                lengthM=float(effective[0]), heightM=float(effective[1]), beamM=float(effective[2]), draftM=draft,
                vertices=sum(len(v) for _, v, _ in grouped), triangles=sum(f.size // 3 for _, _, f in grouped),
                materialBatches=len(grouped), maxTextureSize=4096 if images.output else 0,
                boundsMin=(low + shift).tolist(), boundsMax=(high + shift).tolist(), materials=materials,
                normalization=dict(basis=basis.tolist(), scale=unit, shift=shift.tolist(), upAxis=up, forwardAxis=forward),
                sourceFiles={name: hashlib.sha256(data).hexdigest() for name, data in files.items()}, changes=changes,
                gazeboObj='gazebo.obj', gazeboMtl='gazebo.mtl')
    payloads = dict(images.output)
    payloads['geometry.bytes'] = stream.getvalue()
    remaining = MAX_OUTPUT_BYTES - sum(map(len, payloads.values())) - 1024 * 1024
    payloads['gazebo.obj'], payloads['gazebo.mtl'] = gazebo_files(grouped, materials, remaining)
    payloads['model-info.json'] = (json.dumps(info, allow_nan=False, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    require(sum(map(len, payloads.values())) <= MAX_OUTPUT_BYTES, 'Converted output exceeds limit.')
    absolute = output.absolute()
    require(not any(path.is_symlink() for path in (absolute, *absolute.parents)),
            'Output directory and its parents cannot be symlinks.')
    output.mkdir(parents=True, exist_ok=True)
    require(output.is_dir() and not any(output.iterdir()), 'Conversion output must be an empty owned directory.')
    for name, data in payloads.items():
        with (output / name).open('xb') as handle:
            handle.write(data)
    return info
