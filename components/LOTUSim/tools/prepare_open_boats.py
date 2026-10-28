#!/usr/bin/env python3
"""Bake the six audited CC-BY GLBs for Unity/Gazebo (numpy + Pillow).

No downloaded code is executed. Original GLBs and creator license records are
kept separately. This deliberately is a strict importer for this selection,
not a general glTF implementation: unsupported required features fail closed.
"""

import argparse
import hashlib
import io
import json
import pathlib
import shutil
import struct

import numpy as np
from PIL import Image, ImageOps

SPECS = {
    'speedboat_zefiro': (6.5, 0.52, False),
    'rib_assault': (9.5, 0.40, False),
    'motor_yacht_35': (10.7, 1.15, True),
    'jetski_seadoo_gti': (3.4, 0.27, False),
    'cabin_cruiser_minnow': (11.6, 0.92, False),
    'rib_zodiac': (5.5, 0.25, True),
}


def trs(node):
    if 'matrix' in node:
        return np.array(node['matrix']).reshape(4, 4, order='F')
    x, y, z, w = node.get('rotation', [0, 0, 0, 1])
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation @ np.diag(node.get('scale', [1, 1, 1]))
    matrix[:3, 3] = node.get('translation', [0, 0, 0])
    return matrix


class Glb:
    def __init__(self, path):
        self.raw = path.read_bytes()
        magic, version, length = struct.unpack_from('<III', self.raw)
        if magic != 0x46546C67 or version != 2 or length != len(self.raw):
            raise ValueError('Invalid GLB header')
        size, kind = struct.unpack_from('<II', self.raw, 12)
        if kind != 0x4E4F534A:
            raise ValueError('Missing GLB JSON')
        self.doc = json.loads(self.raw[20 : 20 + size])
        if set(self.doc.get('extensionsRequired', [])) - {'EXT_texture_webp'}:
            raise ValueError('Unsupported required glTF extensions')
        offset = 20 + size
        size, kind = struct.unpack_from('<II', self.raw, offset)
        if kind != 0x004E4942:
            raise ValueError('Missing embedded GLB buffer')
        self.binary = self.raw[offset + 8 : offset + 8 + size]
        self.world = {}
        self.roots = self.doc['scenes'][self.doc.get('scene', 0)]['nodes']
        for index in self.roots:
            self.visit(index, np.eye(4), set())

    def visit(self, index, parent, ancestors):
        if index in ancestors or index in self.world:
            raise ValueError('Cyclic/shared node hierarchy')
        node = self.doc['nodes'][index]
        self.world[index] = parent @ trs(node)
        for child in node.get('children', []):
            self.visit(child, self.world[index], ancestors | {index})

    def accessor(self, index):
        value = self.doc['accessors'][index]
        if value.get('sparse'):
            raise ValueError('Sparse accessors unsupported')
        view = self.doc['bufferViews'][value['bufferView']]
        if view.get('buffer', 0) != 0:
            raise ValueError('External buffers unsupported')
        dtype = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}[
            value['componentType']
        ]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[value['type']]
        step = np.dtype(dtype).itemsize
        stride = view.get('byteStride', width * step)
        result = np.ndarray(
            (value['count'], width),
            dtype=dtype,
            buffer=self.binary,
            offset=view.get('byteOffset', 0) + value.get('byteOffset', 0),
            strides=(stride, step),
        ).copy()
        if value.get('normalized') and value['componentType'] != 5126:
            result = np.maximum(result.astype(float) / np.iinfo(dtype).max, -1)
        return result

    def parts(self):
        parts = []
        for index, matrix in self.world.items():
            node = self.doc['nodes'][index]
            if 'mesh' not in node:
                continue
            for primitive in self.doc['meshes'][node['mesh']]['primitives']:
                if primitive.get('mode', 4) == 1:
                    continue  # SketchUp helper edges, not rendered surfaces.
                if primitive.get('mode', 4) != 4 or primitive.get('targets'):
                    raise ValueError('Only static triangle primitives supported')
                attributes = primitive['attributes']
                positions = self.accessor(attributes['POSITION']).astype(float)
                normals = self.accessor(attributes['NORMAL']).astype(float)
                uv = (
                    self.accessor(attributes['TEXCOORD_0'])
                    if 'TEXCOORD_0' in attributes
                    else np.zeros((len(positions), 2))
                )
                if 'COLOR_0' in attributes:
                    colors = self.accessor(attributes['COLOR_0'])
                    if not np.allclose(colors, 1):
                        raise ValueError('Non-white vertex colors need explicit material support')
                points = np.column_stack((positions, np.ones(len(positions))))
                if 'skin' in node:
                    # Freeze the actual rest-pose skin, including inverse binds.
                    skin = self.doc['skins'][node['skin']]
                    binds = self.accessor(skin['inverseBindMatrices'])
                    joints = self.accessor(attributes['JOINTS_0']).astype(int)
                    weights = self.accessor(attributes['WEIGHTS_0']).astype(float)
                    if not np.allclose(weights.sum(axis=1), 1, atol=1e-4):
                        raise ValueError('Invalid skin weights')
                    matrices = np.array(
                        [
                            self.world[j] @ b.reshape(4, 4, order='F')
                            for j, b in zip(skin['joints'], binds)
                        ]
                    )
                    blend = np.sum(matrices[joints] * weights[:, :, None, None], axis=1)
                    positions = np.einsum('nij,nj->ni', blend, points)[:, :3]
                    normals = np.einsum(
                        'nij,nj->ni', np.linalg.inv(blend[:, :3, :3]).transpose(0, 2, 1), normals
                    )
                else:
                    positions = (points @ matrix.T)[:, :3]
                    normals = normals @ np.linalg.inv(matrix[:3, :3])
                indices = (
                    (
                        self.accessor(primitive['indices']).reshape(-1)
                        if 'indices' in primitive
                        else np.arange(len(positions))
                    )
                    .astype(np.int32)
                    .reshape(-1, 3)
                )
                material = primitive.get('material', 0)
                # Registration is a floating alpha decal, unsupported by our
                # opaque geometric annotation policy. Keep the source intact.
                if self.doc['materials'][material].get('name') == 'Registration':
                    continue
                if np.linalg.det(matrix[:3, :3]) < 0:
                    indices = indices[:, [0, 2, 1]]
                parts.append([material, positions, normals, uv, indices])
        return parts

    def image(self, texture):
        if texture.get('texCoord', 0) != 0 or texture.get('extensions'):
            raise ValueError('Secondary/transformed texture coordinates unsupported')
        entry = self.doc['textures'][texture['index']]
        image = self.doc['images'][
            entry.get('extensions', {})
            .get('EXT_texture_webp', {})
            .get('source', entry.get('source'))
        ]
        view = self.doc['bufferViews'][image['bufferView']]
        begin = view.get('byteOffset', 0)
        return Image.open(io.BytesIO(self.binary[begin : begin + view['byteLength']])).convert(
            'RGBA'
        )


def bake(
    folder,
    output,
    originals,
    gazebo,
    *,
    specification=None,
    basis_override=None,
    airborne=False,
    vertical_scale=False,
):
    info = json.loads((folder / 'inspection.json').read_text())
    key = info['key']
    glb = Glb(folder / 'source.glb')
    if hashlib.sha256(glb.raw).hexdigest() != info['sha256'] or info['license'] != 'CC-BY-4.0':
        raise ValueError('Source identity/license mismatch')
    length, draft, reverse = specification or SPECS[key]
    parts = glb.parts()
    all_points = np.concatenate([p[1] for p in parts])
    size = np.ptp(all_points, axis=0)
    # Same source convention as the mirror's loader: longest axis -> +Z bow,
    # optional 180-degree reversal. Then convert to Unity +X bow, +Y up.
    angle = (np.pi / 2 if size[0] > size[2] else 0) + (np.pi if reverse else 0)
    rotation = np.array(
        [[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]]
    )
    basis = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]]) @ rotation
    if basis_override is not None:
        basis = np.array(basis_override, dtype=float)
    oriented_size = np.ptp(all_points @ basis.T, axis=0)
    scale = length / (oriented_size[1] if vertical_scale else oriented_size[0])
    rotated = all_points @ basis.T * scale
    lo, hi = rotated.min(axis=0), rotated.max(axis=0)
    shift = np.array([-(lo[0] + hi[0]) / 2, -draft - lo[1], -(lo[2] + hi[2]) / 2])
    if airborne:
        shift[1] = -(lo[1] + hi[1]) / 2
    for part in parts:
        part[1] = part[1] @ basis.T * scale + shift
        part[2] = part[2] @ basis.T
        norm = np.linalg.norm(part[2], axis=1)
        if np.any(norm < 1e-8) or not np.isfinite(part[1]).all():
            raise ValueError('Nonfinite geometry/zero normal')
        part[2] /= norm[:, None]
        part[4] = part[4][:, [0, 2, 1]]  # reflected basis
    target = output / key
    target.mkdir(parents=True, exist_ok=True)
    source = originals / key
    source.mkdir(parents=True, exist_ok=True)
    for file in ('source.glb', 'sketchfab-license.json', 'inspection.json'):
        if (folder / file).resolve() != (source / file).resolve():
            shutil.copy2(folder / file, source / file)
    materials = []
    max_texture = 0
    for i, material in enumerate(glb.doc['materials']):
        pbr = material.get('pbrMetallicRoughness', {})
        value = dict(
            name=material.get('name', f'material_{i}'),
            color=pbr.get('baseColorFactor', [1, 1, 1, 1]),
            metallic=pbr.get('metallicFactor', 1),
            smoothness=1 - pbr.get('roughnessFactor', 1),
            doubleSided=material.get('doubleSided', False),
            sourceAlpha=material.get('alphaMode', 'OPAQUE'),
            baseMap='',
            normalMap='',
            maskMap='',
            emissionMap='',
            normalScale=material.get('normalTexture', {}).get('scale', 1),
            emission=material.get('emissiveFactor', [0, 0, 0]),
            coat=material.get('extensions', {})
            .get('KHR_materials_clearcoat', {})
            .get('clearcoatFactor', 0),
        )
        strength = (
            material.get('extensions', {})
            .get('KHR_materials_emissive_strength', {})
            .get('emissiveStrength', 1)
        )
        value['emission'] = [v * strength for v in value['emission']]
        for source_key, dest_key in [
            ('baseColorTexture', 'baseMap'),
            ('normalTexture', 'normalMap'),
            ('emissiveTexture', 'emissionMap'),
        ]:
            slot = (
                pbr.get(source_key)
                if source_key == 'baseColorTexture'
                else material.get(source_key)
            )
            if slot is not None:
                image = glb.image(slot)
                max_texture = max(max_texture, *image.size)
                value[dest_key] = f'material_{i:02}_{dest_key}.png'
                ImageOps.flip(image).save(target / value[dest_key])
        mr = pbr.get('metallicRoughnessTexture')
        ao = material.get('occlusionTexture')
        if mr is not None or ao is not None:
            image = glb.image(mr or ao)
            width, height = image.size
            mask = np.full((height, width, 4), 255, dtype=np.uint8)
            mask[:, :, 0] = round(value['metallic'] * 255)
            mask[:, :, 3] = round(value['smoothness'] * 255)
            if mr is not None:
                pixels = np.asarray(glb.image(mr).resize((width, height)))
                mask[:, :, 0] = np.rint(pixels[:, :, 2] * value['metallic']).astype(np.uint8)
                mask[:, :, 3] = np.rint(255 - pixels[:, :, 1] * (1 - value['smoothness'])).astype(
                    np.uint8
                )
            if ao is not None:
                pixels = np.asarray(glb.image(ao).resize((width, height)))
                mask[:, :, 1] = np.rint(
                    255 + (pixels[:, :, 0].astype(float) - 255) * ao.get('strength', 1)
                ).astype(np.uint8)
            value['maskMap'] = f'material_{i:02}_mask.png'
            ImageOps.flip(Image.fromarray(mask)).save(target / value['maskMap'])
        materials.append(value)
    # Combine by material. Rest-pose skin is baked; no hidden duplicate scene,
    # rig, script, camera, or light comes from the downloaded file.
    groups = []
    for material in sorted(set(p[0] for p in parts)):
        selected = [p for p in parts if p[0] == material]
        vertices, faces, offset = [], [], 0
        for _, positions, normals, uv, indices in selected:
            vertices.append(np.column_stack((positions, normals, uv)).astype('<f4'))
            faces.append(indices + offset)
            offset += len(positions)
        groups.append((material, np.concatenate(vertices), np.concatenate(faces).astype('<i4')))
    with (target / 'geometry.bytes').open('wb') as file:
        file.write(struct.pack('<II', 0x4C424D31, len(groups)))
        for material, vertices, faces in groups:
            file.write(struct.pack('<III', material, len(vertices), faces.size))
            file.write(vertices.tobytes())
            file.write(faces.tobytes())
    info.update(
        lengthM=length,
        beamM=float(hi[2] - lo[2]),
        draftM=draft,
        heightM=float(hi[1] - lo[1]),
        vertices=sum(len(v) for _, v, _ in groups),
        triangles=sum(f.size // 3 for _, _, f in groups),
        materialBatches=len(groups),
        maxTextureSize=max_texture,
        boundsMin=(lo + shift).tolist(),
        boundsMax=(hi + shift).tolist(),
        materials=materials,
        normalization=dict(basis=basis.tolist(), scale=scale, shift=shift.tolist()),
        changes=[
            'Mirror GLB conversion retained',
            'Baked source node transforms/rest skin pose',
            'Simulation scale and artistic waterline; not certified dimensions',
            'Unity +X bow +Y up +Z port',
            'Grouped meshes by source material; helper line edges omitted, no surface simplification',
            'HDRP metallic/roughness/AO/normal map conversion',
            'Opaque glass/tints to match existing annotation policy; alpha registration decal omitted',
            'IOR/specular/transmission extensions approximated, not physically equivalent',
            'Existing approximate nine-point wave response added; no propulsion/hydrodynamic calibration',
        ],
    )
    (target / 'model-info.json').write_text(json.dumps(info, indent=2, ensure_ascii=False))
    credit = (
        f"{info['title']} — {info['author']}\nSource: {info['source']}\nLicense: CC BY 4.0 — https://creativecommons.org/licenses/by/4.0/\nMirror: {info['download']}\nSHA-256: {info['sha256']}\n\nChanges by LOTUSim integration:\n"
        + '\n'.join('- ' + c for c in info['changes'])
        + '\n\nThe creators do not endorse this project. Trademark/publicity rights are not licensed by CC BY. Keep this credit and the license with redistributions, including generated datasets.\n'
    )
    (target / 'ATTRIBUTION.txt').write_text(credit)
    (source / 'ATTRIBUTION.txt').write_text(credit)
    if gazebo:
        dest = gazebo / key
        if dest.exists() and not (dest / 'open-boat-info.json').exists():
            raise ValueError(f'Refusing to overwrite unrelated model {dest}')
        (dest / 'meshes').mkdir(parents=True, exist_ok=True)
        (dest / 'materials').mkdir(exist_ok=True)
        with (
            (dest / 'meshes' / f'{key}.obj').open('w') as obj,
            (dest / 'materials' / f'{key}.mtl').open('w') as mtl,
        ):
            obj.write(
                f'# CC BY 4.0; see ATTRIBUTION.txt. X bow, Y port, Z up, metres.\nmtllib ../materials/{key}.mtl\n'
            )
            offset = 1
            for material, vertices, faces in groups:
                for v in vertices:
                    obj.write(f'v {v[0]:.8g} {v[2]:.8g} {v[1]:.8g}\n')
                for v in vertices:
                    obj.write(f'vt {v[6]:.8g} {v[7]:.8g}\n')
                for v in vertices:
                    obj.write(f'vn {v[3]:.8g} {v[5]:.8g} {v[4]:.8g}\n')
                obj.write(f'usemtl material_{material}\n')
                for face in faces[:, [0, 2, 1]] + offset:
                    obj.write('f ' + ' '.join(f'{v}/{v}/{v}' for v in face) + '\n')
                offset += len(vertices)
            for i, value in enumerate(materials):
                mtl.write(
                    f"newmtl material_{i}\nKd {' '.join(str(v) for v in value['color'][:3])}\nd 1\n"
                )
                if value['baseMap']:
                    # OBJ/Gazebo UV is conventional bottom-up, unlike glTF.
                    image = Image.open(target / value['baseMap'])
                    image.save(dest / 'materials' / value['baseMap'])
                    mtl.write('map_Kd ' + value['baseMap'] + '\n')
            mtl.write('\n')
        label = {
            'buoy': 1,
            'drone': 2,
            'helicopter': 3,
            'airplane': 4,
            'bird': 5,
            'speedboat': 9,
            'motor_yacht': 8,
            'jetski': 10,
        }[info['category']]
        (dest / 'model.config').write_text(
            f'<?xml version="1.0"?><model><name>{key}</name><version>1.0</version><sdf version="1.10">model.sdf</sdf><description>CC BY 4.0 external visual; see ATTRIBUTION.txt. Approximate scale, no naval dynamics.</description></model>\n'
        )
        (dest / 'model.sdf').write_text(
            f'<?xml version="1.0"?><sdf version="1.10"><model name="{key}"><static>true</static><link name="hull"><visual name="appearance"><geometry><mesh><uri>model://{key}/meshes/{key}.obj</uri></mesh></geometry></visual></link><plugin filename="gz-sim-label-system" name="gz::sim::systems::Label"><label>{label}</label></plugin></model></sdf>\n'
        )
        (dest / 'open-boat-info.json').write_text(
            json.dumps({k: v for k, v in info.items() if k != 'materials'}, indent=2)
        )
        (dest / 'ATTRIBUTION.txt').write_text(credit)
    print(
        f"PASS {key}: {info['triangles']:,} triangles, {info['materialBatches']} material batches, textures up to {max_texture}px",
        flush=True,
    )
    return {k: v for k, v in info.items() if k not in ('materials', 'asset')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=pathlib.Path, required=True)
    parser.add_argument('--unity', type=pathlib.Path, required=True)
    parser.add_argument('--gazebo', type=pathlib.Path)
    args = parser.parse_args()
    output = args.unity / 'Assets/models/open_boats'
    originals = args.unity / 'ThirdParty/OpenBoats'
    values = [bake(args.sources / key, output, originals, args.gazebo) for key in SPECS]
    (originals / 'manifest.json').write_text(json.dumps(values, indent=2, ensure_ascii=False))
    if (args.sources / 'MIRROR_NOTICES.md').resolve() != (
        originals / 'MIRROR_NOTICES.md'
    ).resolve():
        shutil.copy2(args.sources / 'MIRROR_NOTICES.md', originals / 'MIRROR_NOTICES.md')
    print('PASS six baked assets; source data and attribution preserved')


if __name__ == '__main__':
    main()
