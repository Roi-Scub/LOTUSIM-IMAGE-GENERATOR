#!/usr/bin/env python3
"""Prepare the audited second CC-BY asset lot; no remote code is executed.

Uses the same strict glTF/material conversion as prepare_open_boats.py.
Bird FBX animation is baked separately by Unity's native model importer.
"""

import argparse
import copy
import json
import pathlib
import shutil
import struct

import numpy as np
from lotusim_image_generator.assets.prepare_boats import Glb, bake

SPECS = {
    'buoy_navigation_ozzy': ((2.5, 0.45, False), [[1, 0, 0], [0, 1, 0], [0, 0, -1]], False, True),
    'drone_amvlab': ((0.82, 0, False), [[1, 0, 0], [0, 1, 0], [0, 0, -1]], True, False),
    'helicopter_utility_gb': ((20, 0, False), [[0, 0, 1], [0, 1, 0], [1, 0, 0]], True, False),
    'airplane_a320': ((37.57, 0, False), [[1, 0, 0], [0, 1, 0], [0, 0, -1]], True, False),
    'airplane_c172': ((8.28, 0, False), [[-1, 0, 0], [0, 1, 0], [0, 0, 1]], True, False),
    'speedboat_smolbot': ((6, 0.55, False), None, False, False),
    'speedboat_racing': ((12.8, 0.50, True), None, False, False),
}


def group_parts(parts, normalization):
    basis = np.array(normalization['basis'])
    scale = normalization['scale']
    shift = np.array(normalization['shift'])
    groups = []
    for material in sorted({p[0] for p in parts}):
        vv, ff, offset = [], [], 0
        for _, positions, normals, uv, indices in [p for p in parts if p[0] == material]:
            positions = positions @ basis.T * scale + shift
            normals = normals @ basis.T
            normals /= np.linalg.norm(normals, axis=1)[:, None]
            vv.append(np.column_stack((positions, normals, uv)).astype('<f4'))
            ff.append(indices[:, [0, 2, 1]] + offset)
            offset += len(positions)
        groups.append((material, np.concatenate(vv), np.concatenate(ff).astype('<i4')))
    return groups


def write_mesh(path, groups):
    with path.open('wb') as file:
        file.write(struct.pack('<II', 0x4C424D31, len(groups)))
        for material, vertices, indices in groups:
            file.write(struct.pack('<III', material, len(vertices), indices.size))
            file.write(vertices.tobytes())
            file.write(indices.tobytes())


def drone_rotors(vertices, faces):
    # Weld only for component labelling: keep all original normals/UV seams.
    unique, inverse = np.unique(np.round(vertices, 5), axis=0, return_inverse=True)
    parents = list(range(len(unique)))

    def root(a):
        while a != parents[a]:
            parents[a] = parents[parents[a]]
            a = parents[a]
        return a

    for a, b, c in inverse[faces]:
        parents[root(int(b))] = root(int(a))
        parents[root(int(c))] = root(int(a))
    labels = np.array([root(int(i)) for i in inverse])
    groups = [np.where(labels == label)[0] for label in set(labels)]
    motors = [
        g
        for g in groups
        if len(g) == 72 and vertices[g].min(0)[1] > 0.14 and vertices[g].max(0)[1] > 0.18
    ]
    blades = [g for g in groups if len(g) == 60 and vertices[g].min(0)[1] > 0.145]
    assert len(motors) == 4 and len(blades) == 8, 'Unexpected drone topology'
    hubs = [(vertices[g].min(0) + vertices[g].max(0)) / 2 for g in motors]
    masks = [np.zeros(len(vertices), dtype=bool) for _ in hubs]
    for blade in blades:
        center = vertices[blade].mean(0)
        index = int(np.argmin([np.linalg.norm((center - h)[[0, 2]]) for h in hubs]))
        masks[index][blade] = True
    for mask in masks:
        assert mask.sum() == 120 and not np.any(
            (mask[faces].sum(1) > 0) & (mask[faces].sum(1) < 3)
        ), 'Rotor split a source face'
    return hubs, masks


def export_bird(unity, gazebo):
    key = 'seagull_dayvable'
    source = unity / 'Assets/models/open_objects' / key
    info = json.loads((source / 'model-info.json').read_text())
    data = (source / 'geometry.bytes').read_bytes()
    magic, parts = struct.unpack_from('<II', data)
    assert magic == 0x4C424D31 and parts == 1
    material, count, indices = struct.unpack_from('<III', data, 8)
    assert material == 0 and count > 0 and indices % 3 == 0
    vertices = np.frombuffer(data, dtype='<f4', count=count * 8, offset=20).reshape(count, 8)
    faces = np.frombuffer(data, dtype='<i4', offset=20 + count * 32).reshape(-1, 3)
    assert faces.size == indices
    target = gazebo / key
    if target.exists() and not (target / 'open-object-info.json').exists():
        raise ValueError('Refusing unrelated bird overwrite')
    (target / 'meshes').mkdir(parents=True, exist_ok=True)
    (target / 'materials').mkdir(exist_ok=True)
    with (target / 'meshes' / f'{key}.obj').open('w') as file:
        file.write(f'# CC BY 4.0; see ATTRIBUTION.txt.\nmtllib ../materials/{key}.mtl\n')
        for v in vertices:
            file.write(f'v {v[0]} {v[2]} {v[1]}\n')
        for v in vertices:
            file.write(f'vt {v[6]} {v[7]}\n')
        for v in vertices:
            file.write(f'vn {v[3]} {v[5]} {v[4]}\n')
        file.write('usemtl feathers\n')
        for face in faces[:, [0, 2, 1]] + 1:
            file.write('f ' + ' '.join(f'{v}/{v}/{v}' for v in face) + '\n')
    (target / 'materials' / f'{key}.mtl').write_text(
        'newmtl feathers\nKd 1 1 1\nd 1\nmap_Kd Seagull-Base_Color.png\n'
    )
    shutil.copy2(source / 'Seagull-Base_Color.png', target / 'materials/Seagull-Base_Color.png')
    (target / 'model.config').write_text(
        f'<?xml version="1.0"?><model><name>{key}</name><version>1.0</version><sdf version="1.10">model.sdf</sdf><description>Seagull by Dayvable; derived FBX by viniciusbarros; CC BY 4.0. See ATTRIBUTION.txt. Static appearance for kinematic trajectories; no bird aerodynamics.</description></model>\n'
    )
    (target / 'model.sdf').write_text(
        f'<?xml version="1.0"?><sdf version="1.10"><model name="{key}"><static>true</static><link name="body"><visual name="appearance"><geometry><mesh><uri>model://{key}/meshes/{key}.obj</uri></mesh></geometry></visual></link><plugin filename="gz-sim-label-system" name="gz::sim::systems::Label"><label>5</label></plugin></model></sdf>\n'
    )
    (target / 'open-object-info.json').write_text(json.dumps(info, indent=2))
    shutil.copy2(source / 'ATTRIBUTION.txt', target / 'ATTRIBUTION.txt')
    print('PASS bird Gazebo static equivalent and class label 5')


def sample_glb(glb, time):
    original = glb.doc['nodes']
    glb.doc['nodes'] = copy.deepcopy(original)
    try:
        for animation in glb.doc.get('animations', [])[:1]:
            for channel in animation['channels']:
                sampler = animation['samplers'][channel['sampler']]
                times = glb.accessor(sampler['input']).ravel()
                values = glb.accessor(sampler['output'])
                index = min(
                    len(times) - 2, max(0, int(np.searchsorted(times, time, side='right') - 1))
                )
                t = float(np.clip((time - times[index]) / (times[index + 1] - times[index]), 0, 1))
                method = sampler.get('interpolation', 'LINEAR')
                path = channel['target']['path']
                if method not in ('LINEAR', 'STEP') or path not in (
                    'rotation',
                    'translation',
                    'scale',
                ):
                    raise ValueError('Unsupported glTF animation channel')
                a, b = values[index].astype(float), values[index + 1].astype(float)
                if method == 'STEP':
                    value = a
                elif path == 'rotation':
                    dot = float(a @ b)
                    if dot < 0:
                        b = -b
                        dot = -dot
                    if dot > 0.9995:
                        value = a + (b - a) * t
                    else:
                        angle = np.arccos(np.clip(dot, -1, 1))
                        value = (a * np.sin((1 - t) * angle) + b * np.sin(t * angle)) / np.sin(
                            angle
                        )
                    value /= np.linalg.norm(value)
                else:
                    value = a + (b - a) * t
                node = glb.doc['nodes'][channel['target']['node']]
                if 'matrix' in node:
                    raise ValueError('Animation targets matrix node')
                node[path] = value.tolist()
        glb.world = {}
        for index in glb.roots:
            glb.visit(index, np.eye(4), set())
        return glb.parts()
    finally:
        glb.doc['nodes'] = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=pathlib.Path)
    parser.add_argument('--unity', type=pathlib.Path, required=True)
    parser.add_argument('--gazebo', type=pathlib.Path, required=True)
    parser.add_argument('--finish-bird', action='store_true')
    args = parser.parse_args()
    if args.finish_bird:
        export_bird(args.unity, args.gazebo)
        return
    if args.sources is None:
        parser.error('--sources is required for source preparation')
    output = args.unity / 'Assets/models/open_objects'
    originals = args.unity / 'ThirdParty/OpenObjects'
    output.mkdir(parents=True, exist_ok=True)
    originals.mkdir(parents=True, exist_ok=True)
    records = []
    for key, (spec, basis, airborne, vertical) in SPECS.items():
        folder = args.sources / key
        if (folder / 'creator-license.json').exists():
            shutil.copy2(folder / 'creator-license.json', folder / 'sketchfab-license.json')
        else:
            # This is explicitly a repository assertion, not a creator API snapshot.
            (folder / 'sketchfab-license.json').write_text(
                json.dumps(
                    {
                        'provenance': 'author repository (not Sketchfab)',
                        'source': 'https://github.com/amvlab/aircraft-models',
                        'license': 'CC-BY-4.0',
                        'evidence': '../amv-LICENSE and ../amv-README.md',
                    }
                )
            )
        # The AMV author's repository licence is retained as a named text file,
        # not presented as a Sketchfab creator API response.
        info = bake(
            folder,
            output,
            originals,
            args.gazebo,
            specification=spec,
            basis_override=basis,
            airborne=airborne,
            vertical_scale=vertical,
        )
        target = output / key
        doc = json.loads((target / 'model-info.json').read_text())
        glb = Glb(folder / 'source.glb')
        doc.update(
            kind=(
                'buoy'
                if key.startswith('buoy')
                else 'marine' if key.startswith('speedboat') else 'aircraft'
            ),
            animationFrames=0,
            animationSeconds=0,
        )
        if vertical:
            doc['lengthM'] = doc['boundsMax'][0] - doc['boundsMin'][0]
        doc['changes'] = [
            'Source retained with pinned mirror/hash and original creator attribution',
            'Node transforms and simulation units baked; no downloaded scripts imported',
            'Opaque HDRP adaptation; alpha/IOR/transmission may differ from source',
            'Rigid source pose is owned by LOTUSim; Unity changes only visual child',
            'Visual/collision body parameters are approximate, not validated naval/aeronautical engineering',
        ]
        if glb.doc.get('animations'):
            duration = max(
                float(glb.accessor(s['input'])[-1, 0]) for s in glb.doc['animations'][0]['samplers']
            )
            count = 30
            for frame in range(count):
                write_mesh(
                    target / f'animation_{frame:03}.bytes',
                    group_parts(sample_glb(glb, duration * frame / count), doc['normalization']),
                )
            doc.update(animationFrames=count, animationSeconds=duration)
            doc['changes'].append(
                'Original rotor animation sampled into opaque mesh frames (same geometry for RGB and annotations)'
            )
        if key == 'drone_amvlab':
            # Rotate only the disconnected, high propeller surfaces around the
            # four authored motor hubs, not the arms or the body.
            parts = glb.parts()
            base = parts[0][1]
            count = 24
            hubs, masks = drone_rotors(base, parts[0][4])
            membership = np.stack(masks)
            assert np.max(membership.sum(0)) <= 1, 'Overlapping rotor partitions'
            assert all(np.count_nonzero(m) > 50 for m in masks), 'Drone rotor partition empty'
            for frame in range(count):
                sample = copy.deepcopy(parts)
                for index, (hub, mask) in enumerate(zip(hubs, masks)):
                    angle = frame / count * 2 * np.pi * (1 if index % 2 else -1)
                    c, s = np.cos(angle), np.sin(angle)
                    rotation = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
                    sample[0][1][mask] = (base[mask] - hub) @ rotation.T + hub
                    sample[0][2][mask] = parts[0][2][mask] @ rotation.T
                write_mesh(
                    target / f'animation_{frame:03}.bytes',
                    group_parts(sample, doc['normalization']),
                )
            doc.update(animationFrames=count, animationSeconds=0.4)
            doc['changes'].append(
                'Procedural opposite propeller rotation; visual cadence, not calibrated RPM'
            )
        (target / 'model-info.json').write_text(json.dumps(doc, indent=2, ensure_ascii=False))
        credit = (
            f"{doc['title']} — {doc['author']}\nSource: {doc['source']}\nCC BY 4.0 — https://creativecommons.org/licenses/by/4.0/\nDownload: {doc['download']}\nSHA-256: {doc['sha256']}\nChanges:\n"
            + '\n'.join('- ' + c for c in doc['changes'])
            + '\nCreator does not endorse this integration. Trademark/publicity rights not granted. Retain credits with redistributed models/datasets.\n'
        )
        for path in [target, originals / key, args.gazebo / key]:
            (path / 'ATTRIBUTION.txt').write_text(credit)
        records.append({k: v for k, v in doc.items() if k not in ('materials', 'asset')})
    key = 'seagull_dayvable'
    target = output / key
    target.mkdir(exist_ok=True)
    (target / 'Source').mkdir(exist_ok=True)
    (originals / key).mkdir(exist_ok=True)
    for dest in [target / 'Source/source.fbx', originals / key / 'source.fbx']:
        shutil.copy2(args.sources / key / 'source.fbx', dest)
    shutil.copy2(
        args.sources / 'bird-ExternalMedia_Magpie_textures_Seagull-Base_Color.png',
        target / 'Seagull-Base_Color.png',
    )
    info = json.loads((args.sources / key / 'inspection.json').read_text())
    info.update(
        kind='bird',
        lengthM=0.95,
        beamM=1.45,
        draftM=0,
        heightM=0.3,
        vertices=0,
        triangles=0,
        maxTextureSize=1024,
        animationFrames=24,
        animationSeconds=1,
        materials=[],
        changes=[
            'Derived FBX by viniciusbarros from Dayvable Seagull, retained with original white feather texture',
            'Unity source wing-flap clip baked to opaque MeshRenderer frames; source retained',
            'Approximate scale and collider/weight; source trajectory owned by LOTUSim',
            'No lights added to bird; no validated bird aerodynamics',
        ],
    )
    (target / 'model-info.json').write_text(json.dumps(info, indent=2))
    shutil.copy2(
        args.sources / key / 'creator-license.json', originals / key / 'creator-license.json'
    )
    records.append(info)
    credit = (
        'Seagull — Dayvable; FBX/rig adaptation by viniciusbarros.\nSource: '
        + info['source']
        + '\nDerived source: '
        + info['download']
        + '\nCC BY 4.0 — https://creativecommons.org/licenses/by/4.0/\nSHA-256: '
        + info['sha256']
        + '\nChanges:\n'
        + '\n'.join('- ' + c for c in info['changes'])
        + '\nNo creator endorsement. Keep credits with redistributed assets/datasets.\n'
    )
    for path in [target, originals / key]:
        (path / 'ATTRIBUTION.txt').write_text(credit)
    for source in args.sources.iterdir():
        if source.is_file() and source.name != 'manifest.json':
            shutil.copy2(source, originals / source.name)
    (originals / 'manifest.json').write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print('PASS second lot ready for Unity prefab/animation authoring')


if __name__ == '__main__':
    main()
