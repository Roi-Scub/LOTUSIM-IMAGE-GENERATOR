"""Trusted LOTUSim UE editor adapter. Loading this file changes no scene.

Explicit console calls: build(); sample(0); capture_rgb(0); capture_all().
Experimental RGB preview only; see scene-plan.json limitations. No ROS client,
external package, shell command, uploaded script, hydrodynamics or annotations.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shlex
import time
import uuid

_STATE = None
_CAPTURE = None
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')
_MAPS = {'map_Kd', 'map_Ka', 'map_Ks', 'map_d', 'map_Bump', 'map_bump', 'bump', 'norm'}


def _engine():
    try:
        import unreal
    except ImportError as exc:
        raise RuntimeError('Run this adapter explicitly inside Unreal Editor, not ordinary Python or the dashboard') from exc
    return unreal


def _load_plan(plan_file):
    path = Path(plan_file or Path(__file__).with_name('scene-plan.json'))
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Missing/unsafe/oversized scene-plan.json')
    plan = json.loads(path.read_text(encoding='utf-8'))
    identity = uuid.UUID(plan['id'])
    expected = '/Game/LOTUSim/Campaigns/' + identity.hex + '/Scene'
    if (plan.get('schema') != 'lotusim-unreal-scene-plan-1' or str(identity) != plan['id']
            or plan.get('scenePath') != expected or not _SHA.fullmatch(plan.get('campaignSha256', ''))):
        raise ValueError('Invalid Unreal plan identity/destination')
    campaign = plan['campaign']
    if (campaign.get('schema') != 'lotusim-campaign-settings-1' or campaign.get('engine') != 'unreal'
            or campaign.get('scene') != 'maritime_manual' or not campaign.get('sensors', {}).get('rgb')
            or campaign['sensors'].get('thermal') or campaign['sensors'].get('nightVision')):
        raise ValueError('Only validated Unreal manual RGB campaigns are supported')
    if (not isinstance(campaign.get('blocks'), list) or not 1 <= len(campaign['blocks']) <= 50
            or not 1 <= campaign.get('totalImages', 0) <= 2000
            or sum(block['images'] for block in campaign['blocks']) != campaign['totalImages']):
        raise ValueError('Invalid image allocation')
    if any(not 1 <= block['images'] <= 2000 or sum(row['count'] for row in block['objects']) > 40 for block in campaign['blocks']):
        raise ValueError('Invalid block allocation')
    def number(value, low, high):
        return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
    camera, observer = campaign['camera'], campaign['observer']
    if (not number(camera['width'], 64, 4096) or type(camera['width']) is not int
            or not number(camera['height'], 64, 4096) or type(camera['height']) is not int
            or not number(camera['verticalFovDeg'], 30, 90) or not number(camera['viewHeadingDeg'], 0, 360)
            or not number(camera['viewDownPitchDeg'], -10, 15) or not number(camera['farClipM'], 5000, 100000)
            or not number(observer['headingDeg'], 0, 360) or not number(observer['speedMps'], 0, 13.89)
            or not number(observer['rollMaxDeg'], 0, 12) or not number(observer['pitchMaxDeg'], 0, 8)):
        raise ValueError('Invalid camera/observer bounds')
    for block in campaign['blocks']:
        if len(block['objects']) > 40:
            raise ValueError('Too many object rows')
        for row in block['objects']:
            if (type(row['count']) is not int or not number(row['count'], 1, 40)
                    or not number(row['distanceM'], 5, 60000) or not number(row['bearingDeg'], -180, 180)
                    or not number(row['spreadDeg'], 0, 180) or not number(row['altitudeM'], 0, 15000)
                    or not number(row['speedMps'], 0, 350) or not number(row['headingDeg'], 0, 360)):
                raise ValueError('Invalid object placement bounds')
        environment = block['environment']
        if (environment['timeOfDay'] not in ('day', 'dusk', 'night')
                or not number(environment['waveHeightM'], 0, 8) or not number(environment['waveDirectionDeg'], 0, 360)
                or not number(environment['cloudCover'], 0, 1) or not number(environment['rainIntensity'], 0, 1)
                or not number(environment['windMps'], 0, 30)):
            raise ValueError('Invalid environment bounds')
    models = {row['model'] for block in campaign['blocks'] for row in block['objects']}
    if any(not _MODEL.fullmatch(model) for model in models) or {a['model'] for a in plan['bindings']} != models:
        raise ValueError('Invalid/incomplete static model bindings')
    if len({a['model'] for a in plan['bindings']}) != len(plan['bindings']):
        raise ValueError('Duplicate model bindings')
    return plan


def _source(plan, relative):
    root = Path(plan['coreRoot']).resolve(strict=True)
    if not isinstance(relative, str) or '\\' in relative:
        raise ValueError('Invalid source path')
    path = Path(os.path.abspath(root / relative))
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError('Asset path escapes the declared source roots') from exc
    models = len(parts) >= 4 and parts[:2] == ('assets', 'models')
    converted = (len(parts) == 7 and parts[:3] == ('artifacts', 'mesh-library', 'imports')
                 and re.fullmatch(r'import-[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}', parts[3])
                 and parts[4] == 'prepared' and _SHA.fullmatch(parts[5])
                 and (parts[6] in ('geometry.bytes', 'model-info.json', 'gazebo.obj', 'gazebo.mtl')
                      or re.fullmatch(r'[A-Za-z0-9_-]+\.png', parts[6])))
    if not models and not converted:
        raise ValueError('Asset path escapes the declared source roots')
    current = root
    for part in parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Symlink dependency refused')
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Missing/oversized source asset: ' + relative)
    return path


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def _verify_sources(plan):
    inventory = {}
    for binding in plan['bindings']:
        if binding.get('kind') not in ('static-obj', 'sdf-primitives'):
            raise ValueError('Unsupported binding kind')
        descriptors = binding.get('sourceFiles', [])
        if not 1 <= len(descriptors) <= 4096:
            raise ValueError('Invalid source inventory')
        for descriptor in descriptors:
            relative = descriptor['path']
            if not _SHA.fullmatch(descriptor.get('sha256', '')):
                raise ValueError('Invalid asset checksum')
            if relative in inventory and inventory[relative] != descriptor:
                raise ValueError('Conflicting dependency descriptors')
            inventory[relative] = descriptor
            path = _source(plan, relative)
            if path.stat().st_size != descriptor['bytes'] or _hash(path) != descriptor['sha256']:
                raise ValueError('Source model changed; prepare a new campaign: ' + relative)
        if binding['kind'] == 'static-obj':
            required = [binding['meshPath']] + [m['source'] for m in binding['materials']]
            required += [t['source'] for m in binding['materials'] for t in m['textures']]
            if any(relative not in inventory for relative in required):
                raise ValueError('Mesh dependency missing from hash inventory')
    return inventory


def sample_spec(plan, index):
    """Pure deterministic independent image plan, testable without Unreal."""
    campaign = plan['campaign']
    if type(index) is not int or not 0 <= index < campaign['totalImages']:
        raise ValueError('Image index outside campaign allocation')
    remaining = index
    for block in campaign['blocks']:
        if remaining < block['images']:
            break
        remaining -= block['images']
    seed = hashlib.sha256((str(campaign['seed']) + ':' + str(index)).encode('ascii')).digest()
    rng = random.Random(int.from_bytes(seed, 'big'))
    observer, camera = campaign['observer'], campaign['camera']
    heading = (observer['headingDeg'] + camera['viewHeadingDeg']) % 360
    roll = rng.uniform(-observer['rollMaxDeg'], observer['rollMaxDeg'])
    pitch = -camera['viewDownPitchDeg'] + rng.uniform(-observer['pitchMaxDeg'], observer['pitchMaxDeg'])
    actors = []
    for row in block['objects']:
        for instance in range(row['count']):
            angular = ((rng.random() - .5) if row['count'] == 1 else ((instance + .15 + .7 * rng.random()) / row['count'] - .5)) * row['spreadDeg']
            bearing = (heading + row['bearingDeg'] + angular) % 360
            angle = math.radians(bearing)
            east, north = math.sin(angle) * row['distanceM'], math.cos(angle) * row['distanceM']
            actors.append({'id': row['id'] + '_' + str(instance), 'model': row['model'],
                           'locationCm': [north * 100, east * 100, row['altitudeM'] * 100],
                           'yawDeg': row['headingDeg'], 'speedMpsDeclaredOnly': row['speedMps'],
                           'distanceM': row['distanceM'], 'nominalBearingDeg': bearing})
    return {'imageIndex': index, 'imageInBlock': remaining, 'blockId': block['id'],
            'environmentRequested': block['environment'], 'actors': actors,
            'cameraLocationCm': [0, 0, 1240], 'cameraRotationDeg': [pitch, heading, roll],
            'horizontalFovDeg': math.degrees(2 * math.atan(math.tan(math.radians(camera['verticalFovDeg']) / 2) * camera['width'] / camera['height'])),
            'limitations': plan['limitations']}


def _preflight(plan, ue):
    required = ('LevelEditorSubsystem', 'EditorActorSubsystem', 'UnrealEditorSubsystem', 'EditorLoadingAndSavingUtils',
                'EditorAssetLibrary', 'AssetToolsHelpers', 'AssetImportTask', 'FbxImportUI', 'FBXImportType',
                'StaticMeshActor', 'StaticMesh', 'CameraActor', 'DirectionalLight', 'SkyLight', 'SkyAtmosphere',
                'MaterialFactoryNew', 'MaterialExpressionConstant3Vector', 'MaterialEditingLibrary', 'MaterialProperty',
                'Material', 'StaticMeshComponent', 'CameraComponent', 'DirectionalLightComponent', 'SkyLightComponent',
                'CollisionEnabled', 'Vector', 'Rotator', 'LinearColor', 'Paths')
    missing = [name for name in required if not hasattr(ue, name)]
    if missing:
        raise RuntimeError('Unreal plugins/APIs unavailable: ' + ', '.join(missing))
    if ue.get_editor_subsystem(ue.UnrealEditorSubsystem).get_game_world() is not None:
        raise RuntimeError('Stop PIE before creating this preview scene')
    if (ue.EditorLoadingAndSavingUtils.get_dirty_map_packages()
            or ue.EditorLoadingAndSavingUtils.get_dirty_content_packages()):
        raise RuntimeError('Save existing modified levels/assets first; this script does not discard or globally save them')
    folder = plan['scenePath'].rsplit('/', 1)[0]
    if ue.EditorAssetLibrary.does_directory_exist(folder) or ue.EditorAssetLibrary.does_asset_exist(plan['scenePath']):
        raise RuntimeError('Destination already exists. Prepare a NEW campaign; no existing assets are overwritten')
    for shape in ('Cube', 'Cylinder', 'Sphere'):
        if not ue.EditorAssetLibrary.does_asset_exist('/Engine/BasicShapes/' + shape):
            raise RuntimeError('Required engine primitive missing: ' + shape)
    _verify_sources(plan)


def _normalize_obj(plan, binding, destination):
    """Create a fixed-format, static, cm/LH import cache. No external tools."""
    destination.mkdir(parents=False, exist_ok=False)
    root = Path(plan['coreRoot']).resolve()
    material_names = {}
    for n, record in enumerate(binding['materials']):
        source = _source(plan, record['source'])
        material_names[str(source)] = 'material_' + str(n) + '.mtl'
        textures = {}
        for t, texture in enumerate(record['textures']):
            original = _source(plan, texture['source'])
            target_name = 'texture_' + str(n) + '_' + str(t) + original.suffix.lower()
            target = destination / target_name
            with original.open('rb') as src, target.open('xb') as dst:
                for data in iter(lambda: src.read(1024 * 1024), b''):
                    dst.write(data)
            textures[(texture['directive'], texture['token'])] = target_name
        with source.open(encoding='utf-8-sig') as src, (destination / material_names[str(source)]).open('x', encoding='utf-8') as dst:
            for line in src:
                words = shlex.split(line, comments=True)
                if not words:
                    continue
                if words[0] in _MAPS:
                    key = (words[0], words[1]) if len(words) == 2 else None
                    if key not in textures:
                        raise ValueError('Unlisted raster map')
                    dst.write(words[0] + ' ' + textures[key] + '\n')
                elif words[0] in {'newmtl', 'Kd', 'Ka', 'Ks', 'Ke', 'Ns', 'Ni', 'd', 'Tr', 'illum'}:
                    dst.write(line.rstrip() + '\n')
    source = _source(plan, binding['meshPath'])
    result = destination / 'mesh.obj'
    with source.open(encoding='utf-8-sig') as src, result.open('x', encoding='utf-8') as dst:
        for line in src:
            if len(line) > 1024 * 1024:
                raise ValueError('Oversized mesh line')
            words = line.split()
            if not words or words[0].startswith('#'):
                continue
            kind = words[0]
            if kind in ('v', 'vn'):
                point = [float(v) for v in words[1:4]]
                if len(point) != 3 or not all(math.isfinite(v) for v in point):
                    raise ValueError('Invalid vertex/normal')
                scale = binding['meshScale'] if kind == 'v' else [1, 1, 1]
                if kind == 'vn':
                    # Inverse transpose for non-uniform SDF scale.
                    scale = [1 / v for v in binding['meshScale']]
                point = [point[n] * scale[n] * (100 if kind == 'v' else 1) * (-1 if n == 1 else 1) for n in range(3)]
                if kind == 'vn':
                    length = math.sqrt(sum(v * v for v in point))
                    if length > 0:
                        point = [v / length for v in point]
                dst.write(kind + ' ' + ' '.join(format(v, '.9g') for v in point) + '\n')
            elif kind == 'mtllib':
                names = shlex.split(line, comments=True)[1:]
                for name in names:
                    original = str(_source(plan, (source.parent / name).relative_to(root).as_posix()))
                    if original not in material_names:
                        raise ValueError('Unlisted MTL')
                    dst.write('mtllib ' + material_names[original] + '\n')
            elif kind == 'f':
                if len(words) < 4 or any(not re.fullmatch(r'-?[1-9][0-9]*(?:/-?[0-9]*(?:/-?[1-9][0-9]*)?)?', token) for token in words[1:]):
                    raise ValueError('Unsupported OBJ face')
                dst.write('f ' + ' '.join(reversed(words[1:])) + '\n')
            elif kind in ('vt', 'o', 'g', 's', 'usemtl'):
                dst.write(line.rstrip() + '\n')
    return result


def _import_mesh(plan, binding, cache, ue):
    obj = _normalize_obj(plan, binding, cache / binding['model'])
    _verify_sources({'coreRoot': plan['coreRoot'], 'bindings': [binding]})
    folder = plan['scenePath'].rsplit('/', 1)[0] + '/Meshes/' + binding['model']
    options = ue.FbxImportUI()
    options.set_editor_property('import_mesh', True)
    options.set_editor_property('import_as_skeletal', False)
    options.set_editor_property('import_materials', True)
    options.set_editor_property('import_textures', True)
    options.set_editor_property('automated_import_should_detect_type', False)
    options.set_editor_property('mesh_type_to_import', ue.FBXImportType.FBXIT_STATIC_MESH)
    settings = options.get_editor_property('static_mesh_import_data')
    for name, value in {'combine_meshes': True, 'convert_scene': False, 'convert_scene_unit': False,
                        'import_uniform_scale': 1.0, 'auto_generate_collision': False}.items():
        settings.set_editor_property(name, value)
    task = ue.AssetImportTask()
    for name, value in {'filename': str(obj), 'destination_path': folder, 'destination_name': 'Mesh',
                        'automated': True, 'replace_existing': False, 'save': True, 'options': options}.items():
        task.set_editor_property(name, value)
    ue.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    imported = [ue.load_asset(path) for path in task.get_editor_property('imported_object_paths')]
    meshes = [asset for asset in imported if isinstance(asset, ue.StaticMesh)]
    if len(meshes) != 1:
        raise RuntimeError('Static OBJ importer did not produce exactly one mesh: ' + binding['model'])
    bounds = meshes[0].get_bounds()
    ext = bounds.box_extent
    actual = [2 * ext.x, 2 * ext.y, 2 * ext.z]
    expected = [100 * n for n in binding['sourceDimensionsM']]
    if any(abs(a - b) > max(1.0, .02 * b) for a, b in zip(actual, expected)):
        raise RuntimeError('Importer changed mesh axes/units; refusing unverified scale for ' + binding['model'])
    return meshes[0]


def _material(name, color, state):
    ue = state['ue']
    folder = state['plan']['scenePath'].rsplit('/', 1)[0] + '/Materials'
    material = ue.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, ue.Material, ue.MaterialFactoryNew())
    if material is None:
        raise RuntimeError('Could not create preview material')
    expression = ue.MaterialEditingLibrary.create_material_expression(material, ue.MaterialExpressionConstant3Vector, -300, 0)
    expression.set_editor_property('constant', ue.LinearColor(*color))
    if not ue.MaterialEditingLibrary.connect_material_property(expression, '', ue.MaterialProperty.MP_BASE_COLOR):
        raise RuntimeError('Could not connect preview material')
    ue.MaterialEditingLibrary.recompile_material(material)
    if not ue.EditorAssetLibrary.save_loaded_asset(material):
        raise RuntimeError('Could not save preview material')
    return material


def _spawn_mesh(mesh, label, state, material=None):
    ue = state['ue']
    actor = state['actors_api'].spawn_actor_from_class(ue.StaticMeshActor, ue.Vector(0, 0, 0))
    if actor is None:
        raise RuntimeError('Could not spawn static preview actor')
    component = actor.get_component_by_class(ue.StaticMeshComponent)
    component.set_static_mesh(mesh)
    component.set_collision_enabled(ue.CollisionEnabled.NO_COLLISION)
    if material is not None:
        component.set_material(0, material)
    actor.set_actor_label(label)
    actor.set_actor_hidden_in_game(True)
    actor.set_is_temporarily_hidden_in_editor(True)
    return actor


def _scale_to(actor, dimensions_cm):
    mesh = actor.get_component_by_class(_STATE['ue'].StaticMeshComponent).get_editor_property('static_mesh')
    ext = mesh.get_bounds().box_extent
    extents = (ext.x, ext.y, ext.z)
    if any(v <= 0 for v in extents):
        raise RuntimeError('Invalid engine primitive bounds')
    actor.set_actor_scale3d(_STATE['ue'].Vector(*(dimensions_cm[n] / (2 * extents[n]) for n in range(3))))


def build(plan_file=None):
    """Create a new campaign-owned map. Refuse existing/dirty destinations."""
    global _STATE
    if _CAPTURE is not None or _STATE is not None:
        raise RuntimeError('A preview is already built/in use in this Python session; do not duplicate it')
    plan, ue = _load_plan(plan_file), _engine()
    _preflight(plan, ue)
    saved = Path(ue.Paths.convert_relative_path_to_full(ue.Paths.project_saved_dir())).resolve()
    output = saved / 'LOTUSim' / plan['id']
    parent = output.parent
    parent.mkdir(exist_ok=True)
    if parent.is_symlink() or output.exists() or output.is_symlink():
        raise RuntimeError('Preview output/cache already exists or is unsafe; prepare a NEW campaign')
    output.mkdir()
    cache = output / 'MeshCache'
    cache.mkdir()
    # Cache conversion and source checks finish before opening a new level.
    meshes = {}
    for binding in plan['bindings']:
        if binding['kind'] == 'static-obj':
            meshes[binding['model']] = _import_mesh(plan, binding, cache, ue)
    level_api = ue.get_editor_subsystem(ue.LevelEditorSubsystem)
    if not level_api.new_level(plan['scenePath']):
        raise RuntimeError('Unreal could not create the campaign map')
    state = {'plan': plan, 'ue': ue, 'level_api': level_api, 'actors_api': ue.get_editor_subsystem(ue.EditorActorSubsystem),
             'meshes': meshes, 'actors': [], 'output': output, 'samples': [], 'captureReceipts': []}
    _STATE = state
    camera = state['actors_api'].spawn_actor_from_class(ue.CameraActor, ue.Vector(0, 0, 1240))
    camera.set_actor_label('LOTUSim theoretical navigation bridge camera — no FREMM hull')
    state['camera'] = camera
    state['sun'] = state['actors_api'].spawn_actor_from_class(ue.DirectionalLight, ue.Vector(0, 0, 100000))
    state['sky'] = state['actors_api'].spawn_actor_from_class(ue.SkyLight, ue.Vector(0, 0, 100000))
    state['atmosphere'] = state['actors_api'].spawn_actor_from_class(ue.SkyAtmosphere, ue.Vector(0, 0, 0))
    state['sun'].get_component_by_class(ue.DirectionalLightComponent).set_editor_property('atmosphere_sun_light', True)
    sea = _spawn_mesh(ue.load_asset('/Engine/BasicShapes/Cube'), 'FLAT OCEAN PREVIEW — NO WAVES / NO HYDRODYNAMICS', state,
                      _material('FlatOceanPreview', [.015, .07, .1, 1], state))
    _scale_to(sea, [16000000, 16000000, 20])
    sea.set_actor_location(ue.Vector(0, 0, -10), False, False)
    sea.set_actor_hidden_in_game(False)
    sea.set_is_temporarily_hidden_in_editor(False)
    state['sea'] = sea
    state['primitiveMaterials'] = {}
    for binding in plan['bindings']:
        if binding['kind'] == 'sdf-primitives':
            for n, primitive in enumerate(binding['primitives']):
                state['primitiveMaterials'][(binding['model'], n)] = _material('Buoy_' + str(n), primitive['color'], state)
    sample(0)
    if not level_api.save_current_level():
        raise RuntimeError('Could not save the newly created campaign map')
    _write_status('scene-created-unvalidated')
    ue.log_warning('[LOTUSim Unreal] Experimental static RGB preview. Flat sea; no rain/cloud control, ROS, annotations or FREMM hull. Read scene-plan.json limitations.')
    return plan['scenePath']


def _require_state():
    if _STATE is None:
        raise RuntimeError('Call build() first in the same editor Python session')
    state = _STATE
    world = state['ue'].get_editor_subsystem(state['ue'].UnrealEditorSubsystem).get_editor_world()
    if world is None or world.get_path_name().split('.')[0] != state['plan']['scenePath']:
        raise RuntimeError('Campaign level is no longer active; refusing to change another map')
    return state


def sample(index):
    """Apply a deterministic independent sample, not a dynamic LOTUSim trajectory."""
    if _CAPTURE is not None and not _CAPTURE.get('applying', False):
        raise RuntimeError('A capture is pending; wait for completion before changing the sample')
    state = _require_state()
    ue, plan = state['ue'], state['plan']
    spec = sample_spec(plan, index)
    # Destroy only actors explicitly created by this running adapter, never scene discovery.
    for actor in state['actors']:
        state['actors_api'].destroy_actor(actor)
    state['actors'] = []
    for placement in spec['actors']:
        binding = next(b for b in plan['bindings'] if b['model'] == placement['model'])
        if binding['kind'] == 'static-obj':
            actor = _spawn_mesh(state['meshes'][placement['model']], placement['id'], state)
            entries = [(actor, [0, 0, 0])]
        else:
            entries = []
            for n, primitive in enumerate(binding['primitives']):
                actor = _spawn_mesh(ue.load_asset('/Engine/BasicShapes/' + primitive['kind']), placement['id'] + '_' + str(n), state,
                                    state['primitiveMaterials'][(binding['model'], n)])
                _scale_to(actor, [100 * v for v in primitive['dimensionsM']])
                local = primitive['localPositionM']
                entries.append((actor, [100 * local[0], -100 * local[1], 100 * local[2]]))
        for actor, local in entries:
            angle = math.radians(placement['yawDeg'])
            offset = [local[0] * math.cos(angle) - local[1] * math.sin(angle), local[0] * math.sin(angle) + local[1] * math.cos(angle), local[2]]
            actor.set_actor_location(ue.Vector(*(placement['locationCm'][n] + offset[n] for n in range(3))), False, False)
            actor.set_actor_rotation(ue.Rotator(0, placement['yawDeg'], 0), False)
            actor.set_actor_hidden_in_game(False)
            actor.set_is_temporarily_hidden_in_editor(False)
            state['actors'].append(actor)
    state['camera'].set_actor_location(ue.Vector(*spec['cameraLocationCm']), False, False)
    state['camera'].set_actor_rotation(ue.Rotator(*spec['cameraRotationDeg']), False)
    camera_component = state['camera'].get_component_by_class(ue.CameraComponent)
    camera_component.set_field_of_view(spec['horizontalFovDeg'])
    camera_component.set_editor_property('aspect_ratio', plan['campaign']['camera']['width'] / plan['campaign']['camera']['height'])
    camera_component.set_editor_property('constrain_aspect_ratio', True)
    # The perspective far clip request has no general CameraActor equivalent; record, do not misapply orthographic settings.
    preset = spec['environmentRequested']['timeOfDay']
    elevation, lux, sky_intensity = {'day': (45, 45000, 1), 'dusk': (4, 1800, .25), 'night': (-12, .05, .04)}[preset]
    state['sun'].set_actor_rotation(ue.Rotator(-elevation, -35, 0), False)
    sun_component = state['sun'].get_component_by_class(ue.DirectionalLightComponent)
    sun_component.set_intensity(lux)
    sky_component = state['sky'].get_component_by_class(ue.SkyLightComponent)
    sky_component.set_intensity(sky_intensity)
    sky_component.recapture_sky()
    state['level_api'].pilot_level_actor(state['camera'])
    spec['environmentApplied'] = {'lightingPreset': preset, 'sunElevationDeg': elevation, 'sunIntensityLux': lux,
                                  'skyIntensity': sky_intensity, 'water': 'flat opaque preview', 'wavesApplied': False,
                                  'rainApplied': False, 'cloudControlApplied': False, 'windPhysicsApplied': False,
                                  'farClipApplied': False, 'speedTrajectoriesApplied': False}
    state['sample'] = spec
    return spec


def _write_status(status):
    state = _STATE
    receipt = {'schema': 'lotusim-unreal-preview-status-1', 'campaignId': state['plan']['id'],
               'campaignSha256': state['plan']['campaignSha256'], 'scenePath': state['plan']['scenePath'],
               'status': status, 'nativeValidated': False, 'completedCaptures': state['captureReceipts'],
               'limitations': state['plan']['limitations']}
    path = state['output'] / 'unreal-status.json'
    temporary = state['output'] / 'unreal-status.tmp'
    if path.is_symlink() or temporary.is_symlink():
        raise RuntimeError('Unsafe receipt path')
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def _capture_tick(delta_seconds):
    global _CAPTURE
    capture = _CAPTURE
    if capture is None:
        return
    ue = _STATE['ue']
    try:
        state = _require_state()
        if capture['task'] is not None:
            task = capture['task']
            if not task.is_valid_task():
                raise RuntimeError('Unreal rejected the screenshot task')
            if not task.is_task_done():
                if time.monotonic() > capture['deadline']:
                    raise TimeoutError('Editor screenshot timed out after 120 seconds')
                return
            path = capture['path']
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError('Screenshot task finished without the requested PNG')
            metadata = dict(state['sample'], rgbFile=path.name, rgbSha256=_hash(path), annotationsProduced=False)
            meta = path.with_suffix('.json')
            with meta.open('x', encoding='utf-8') as stream:
                json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
            state['captureReceipts'].append({'imageIndex': metadata['imageIndex'], 'file': path.name, 'sha256': metadata['rgbSha256']})
            capture['task'] = None
            _write_status('rgb-preview-capturing')
            capture['position'] += 1
        if capture['position'] >= len(capture['indices']):
            ue.unregister_slate_post_tick_callback(capture['handle'])
            _CAPTURE = None
            _write_status('rgb-preview-complete-unvalidated')
            return
        index = capture['indices'][capture['position']]
        if capture['settleTicks'] == 0:
            capture['applying'] = True
            sample(index)
            capture['applying'] = False
        capture['settleTicks'] += 1
        if capture['settleTicks'] < 10:
            return
        path = state['output'] / ('rgb_' + str(index).zfill(5) + '.png')
        if path.exists() or path.is_symlink() or path.with_suffix('.json').exists():
            raise RuntimeError('Capture already exists; refusing to overwrite it')
        ue.AutomationLibrary.finish_loading_before_screenshot()
        camera = state['plan']['campaign']['camera']
        capture['path'] = path
        capture['task'] = ue.AutomationLibrary.take_high_res_screenshot(camera['width'], camera['height'], str(path), camera=state['camera'], delay=.2)
        capture['deadline'] = time.monotonic() + 120
        capture['settleTicks'] = 0
    except Exception as exc:
        ue.unregister_slate_post_tick_callback(capture['handle'])
        _CAPTURE = None
        _write_status('rgb-preview-failed: ' + str(exc))
        ue.log_error('[LOTUSim Unreal] ' + str(exc))


def _queue(indices):
    global _CAPTURE
    state = _require_state()
    if _CAPTURE is not None:
        raise RuntimeError('Screenshot worker already active')
    ue = state['ue']
    if not all(hasattr(ue, key) for key in ('AutomationLibrary', 'register_slate_post_tick_callback', 'unregister_slate_post_tick_callback')):
        raise RuntimeError('Editor screenshot/tick APIs unavailable')
    for index in indices:
        sample_spec(state['plan'], index)
        path = state['output'] / ('rgb_' + str(index).zfill(5) + '.png')
        if path.exists() or path.with_suffix('.json').exists():
            raise RuntimeError('Capture already exists for image ' + str(index))
    _CAPTURE = {'indices': list(indices), 'position': 0, 'task': None, 'settleTicks': 0, 'applying': False}
    _CAPTURE['handle'] = ue.register_slate_post_tick_callback(_capture_tick)
    _write_status('rgb-preview-capture-queued')
    return str(state['output'])


def capture_rgb(index):
    """Queue one asynchronous editor PNG, never imply annotation/renderer parity."""
    return _queue([index])


def capture_all():
    """Queue all independent RGB samples, allowing editor ticks between images."""
    return _queue(list(range(_require_state()['plan']['campaign']['totalImages'])))


def cancel_capture():
    """Stop only this adapter's pending work; retain completed files/scene."""
    global _CAPTURE
    if _CAPTURE is not None:
        _STATE['ue'].unregister_slate_post_tick_callback(_CAPTURE['handle'])
        _CAPTURE = None
        _write_status('rgb-preview-cancelled')
