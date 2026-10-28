"""Prepare data and a fixed editor script; never start or import Unreal here."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shlex
import uuid
import xml.etree.ElementTree as ET

SCHEMA = 'lotusim-unreal-scene-plan-1'
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')
SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_FILE = 256 * 1024 * 1024
RASTER = {'.png', '.jpg', '.jpeg', '.tga', '.bmp'}
MAPS = {'map_Kd', 'map_Ka', 'map_Ks', 'map_d', 'map_Bump', 'map_bump', 'bump', 'norm'}
REFERENCES = [
    'https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AssetImportTask?application_version=5.6',
    'https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/LevelEditorSubsystem?application_version=5.6',
    'https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/EditorActorSubsystem?application_version=5.6',
    'https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/AutomationLibrary?application_version=5.6',
    'https://dev.epicgames.com/documentation/en-us/unreal-engine/write-editor-tests-with-python-in-unreal-engine',
]


def _json(value):
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
        + '\n'
    ).encode('utf-8')


def _safe_file(root, candidate):
    """Only regular, non-symlink source files physically inside the model library."""
    root = Path(root).resolve(strict=True)
    candidate = Path(candidate)
    if not candidate.is_absolute():
        candidate = root / candidate
    # resolve .. lexically, but reject any actual symlink before dereferencing it.
    candidate = Path(__import__('os').path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError('Unreal mesh dependency escapes the model library') from exc
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError('Symlink mesh dependency refused: ' + str(relative))
    if not candidate.is_file() or candidate.stat().st_size > MAX_FILE:
        raise ValueError('Missing/oversized Unreal mesh dependency: ' + str(relative))
    return candidate


def _descriptor(root, path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {
        'path': path.relative_to(root).as_posix(),
        'bytes': path.stat().st_size,
        'sha256': digest.hexdigest(),
    }


def _words(line):
    try:
        return shlex.split(line, comments=True)
    except ValueError as exc:
        raise ValueError('Malformed OBJ/MTL dependency line') from exc


def _mesh_binding(core_root, model, record):
    if record.get('neutralReady') is True:
        return _neutral_mesh_binding(core_root, model, record)
    library = core_root / 'assets/models'
    model_root = _safe_file(library, library / model / 'model.sdf').parent
    sdf_path = model_root / 'model.sdf'
    if sdf_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Oversized model SDF')
    source = sdf_path.read_text(encoding='utf-8')
    if '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():
        raise ValueError('SDF entities are not allowed')
    # Some existing models use gz:type without declaring the namespace.
    source = re.sub(r'\bgz:type\s*=', 'gz_type=', source)
    try:
        sdf = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ValueError('Invalid SDF for ' + model) from exc
    for ancestor in sdf.findall('.//model') + sdf.findall('.//link'):
        pose = ancestor.find('pose')
        if pose is not None:
            values = [float(v) for v in (pose.text or '').split()]
            if (
                len(values) != 6
                or not all(math.isfinite(v) for v in values)
                or any(abs(v) > 0.00001 for v in values)
                or pose.get('relative_to')
            ):
                raise ValueError('Unreal preview requires baked model/link transforms: ' + model)
    visuals = sdf.findall('.//visual')
    mesh_visuals = [v for v in visuals if v.find('geometry/mesh/uri') is not None]
    if not mesh_visuals:
        if model != 'buoy':
            raise ValueError(
                'No vetted static OBJ binding for '
                + model
                + '; supply an imported static asset first'
            )
        primitives = []
        for visual in visuals:
            pose = [float(v) for v in (visual.findtext('pose') or '0 0 0 0 0 0').split()]
            if (
                len(pose) != 6
                or not all(math.isfinite(v) for v in pose)
                or any(abs(v) > 0.00001 for v in pose[3:])
            ):
                raise ValueError('Unsupported buoy visual pose')
            geometry = visual.find('geometry')
            if geometry is None:
                raise ValueError('Missing buoy geometry')
            if geometry.find('cylinder') is not None:
                radius = float(geometry.findtext('cylinder/radius'))
                length = float(geometry.findtext('cylinder/length'))
                kind, dimensions = 'Cylinder', [2 * radius, 2 * radius, length]
            elif geometry.find('sphere') is not None:
                radius = float(geometry.findtext('sphere/radius'))
                kind, dimensions = 'Sphere', [2 * radius] * 3
            else:
                raise ValueError('Unsupported buoy primitive')
            if not all(math.isfinite(v) and 0 < v <= 100 for v in dimensions):
                raise ValueError('Invalid buoy dimensions')
            color = [
                float(v) for v in (visual.findtext('material/diffuse') or '.8 .2 .05 1').split()
            ]
            if len(color) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in color):
                raise ValueError('Invalid buoy color')
            primitives.append(
                {
                    'kind': kind,
                    'dimensionsM': dimensions,
                    'localPositionM': pose[:3],
                    'color': color,
                }
            )
        return {
            'model': model,
            'kind': 'sdf-primitives',
            'primitives': primitives,
            'sourceFiles': [_descriptor(core_root, sdf_path)],
            'provenance': 'Gazebo SDF primitives, not the more detailed Unity buoy prefab',
            'category': record['category'],
        }
    if len(mesh_visuals) != 1 or len(visuals) != 1:
        raise ValueError('Unreal preview currently requires one static visual mesh: ' + model)
    visual = mesh_visuals[0]
    pose = visual.find('pose')
    values = [float(v) for v in (visual.findtext('pose') or '0 0 0 0 0 0').split()]
    if (
        len(values) != 6
        or not all(math.isfinite(v) for v in values)
        or any(abs(v) > 0.00001 for v in values)
        or pose is not None
        and pose.get('relative_to')
    ):
        raise ValueError('Unreal preview requires baked visual transforms: ' + model)
    mesh_node = visual.find('geometry/mesh')
    if mesh_node.find('submesh') is not None:
        raise ValueError(
            'Unreal preview requires a baked mesh, not an SDF submesh selection: ' + model
        )
    mesh_scale = [float(v) for v in (mesh_node.findtext('scale') or '1 1 1').split()]
    if len(mesh_scale) != 3 or not all(math.isfinite(v) and 0 < v <= 1000 for v in mesh_scale):
        raise ValueError('Invalid SDF mesh scale')
    uri = mesh_node.findtext('uri')
    if uri.startswith('model://'):
        relative = uri[len('model://') :]
        if '\\' in relative or PurePosixPath(relative).is_absolute():
            raise ValueError('Invalid mesh URI')
        mesh_path = _safe_file(library, library / relative)
    else:
        mesh_path = _safe_file(library, model_root / uri)
    return _static_obj_binding(
        core_root, library, model, record, mesh_path, mesh_scale, {mesh_path, sdf_path}
    )


def _neutral_mesh_binding(core_root, model, record):
    from mesh_integration import neutral_imports

    verified = next((item for item in neutral_imports(core_root) if item['model'] == model), None)
    if (
        verified is None
        or verified['neutralSource'] != record.get('neutralSource')
        or verified['revisionSha256'] != record.get('revisionSha256')
        or verified['requestSha256'] != record.get('requestSha256')
    ):
        raise ValueError('Converted source revision is not verified: ' + model)
    source = verified['neutralSource']
    bundle = (core_root / source['obj']).parent
    mesh_path = _safe_file(bundle, core_root / source['obj'])
    dependencies = {_safe_file(bundle, core_root / item['path']) for item in source['files']}
    result = _static_obj_binding(
        core_root, bundle, model, record, mesh_path, [1, 1, 1], dependencies
    )
    result['provenance'] = (
        'Verified engine-neutral converted source; no Unity prefab or native compatibility implied'
    )
    result['sourceRevisionSha256'] = verified['revisionSha256']
    return result


def _static_obj_binding(core_root, library, model, record, mesh_path, mesh_scale, dependencies):
    if mesh_path.suffix.lower() != '.obj':
        raise ValueError(
            'Unreal preview requires static OBJ for '
            + model
            + '; DAE/STL are not silently approximated'
        )
    dependencies = set(dependencies)
    materials = []
    low, high = [math.inf] * 3, [-math.inf] * 3
    vertices = 0
    with mesh_path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if len(line) > 1024 * 1024:
                raise ValueError('Oversized OBJ line')
            if line.startswith('v '):
                point = [float(v) * mesh_scale[n] for n, v in enumerate(line.split()[1:4])]
                if len(point) != 3 or not all(math.isfinite(v) and abs(v) <= 100000 for v in point):
                    raise ValueError('Invalid OBJ vertex')
                vertices += 1
                for n, value in enumerate(point):
                    low[n], high[n] = min(low[n], value), max(high[n], value)
            elif line.lstrip().startswith('mtllib '):
                names = _words(line)[1:]
                if not names:
                    raise ValueError('Empty OBJ material library')
                for name in names:
                    mtl = _safe_file(library, mesh_path.parent / name)
                    if mtl.suffix.lower() != '.mtl':
                        raise ValueError('Non-MTL material dependency')
                    materials.append(mtl)
                    dependencies.add(mtl)
    if not 3 <= vertices <= 10000000:
        raise ValueError('Invalid OBJ vertex count')
    material_records = []
    for mtl in dict.fromkeys(materials):
        textures = []
        with mtl.open(encoding='utf-8-sig') as stream:
            for line in stream:
                words = _words(line)
                if words and words[0] in MAPS:
                    # Normalize only explicit filenames, not unverified importer command/options syntax.
                    if len(words) != 2:
                        raise ValueError(
                            'Unsupported MTL map options; normalize the model before preparing: '
                            + model
                        )
                    texture = _safe_file(library, mtl.parent / words[1])
                    if texture.suffix.lower() not in RASTER:
                        raise ValueError('Unsupported raster map type')
                    dependencies.add(texture)
                    textures.append(
                        {
                            'directive': words[0],
                            'source': texture.relative_to(core_root).as_posix(),
                            'token': words[1],
                        }
                    )
        material_records.append(
            {'source': mtl.relative_to(core_root).as_posix(), 'textures': textures}
        )
    if len(dependencies) > 4096:
        raise ValueError('Too many mesh dependencies')
    return {
        'model': model,
        'kind': 'static-obj',
        'category': record['category'],
        'meshPath': mesh_path.relative_to(core_root).as_posix(),
        'meshScale': mesh_scale,
        'materials': material_records,
        'boundsMinM': low,
        'boundsMaxM': high,
        'sourceFiles': [_descriptor(core_root, f) for f in sorted(dependencies)],
        'provenance': 'Existing licensed LOTUSim static model; retain its original library credits',
        'sourceDimensionsM': [high[n] - low[n] for n in range(3)],
    }


def prepare_unreal(campaign, identifier, campaign_sha, core_root, unity_root, catalogue):
    """Return a local, immutable preview package. Does not launch editor/processes."""
    parsed_id = uuid.UUID(str(identifier))
    if str(parsed_id) != identifier or not SHA.fullmatch(str(campaign_sha)):
        raise ValueError('Invalid campaign UUID/hash')
    if (
        campaign.get('schema') != 'lotusim-campaign-settings-1'
        or campaign.get('engine') != 'unreal'
        or campaign.get('scene') != 'maritime_manual'
    ):
        raise ValueError('Unreal adapter requires a validated Unreal maritime_manual campaign')
    core_root = Path(core_root).resolve(strict=True)
    # unity_root deliberately is not read: Unreal must not need Unity binaries/assets.
    records = catalogue.get('assets', []) if isinstance(catalogue, dict) else []
    by_model = {}
    for record in records:
        model = record.get('model', '')
        if not MODEL.fullmatch(model) or model in by_model:
            raise ValueError('Invalid/duplicate catalogue model')
        by_model[model] = record
    used = sorted({row['model'] for block in campaign['blocks'] for row in block['objects']})
    bindings = []
    for model in used:
        if model not in by_model:
            raise ValueError('Unknown model: ' + model)
        binding = _mesh_binding(core_root, model, by_model[model])
        binding['catalogue'] = {
            key: copy.deepcopy(by_model[model][key])
            for key in (
                'lengthM',
                'beamM',
                'heightM',
                'maxSpeedMps',
                'maxAltitudeM',
                'domain',
                'category',
            )
            if key in by_model[model]
        }
        bindings.append(binding)
    scene_path = '/Game/LOTUSim/Campaigns/' + parsed_id.hex + '/Scene'
    limitations = [
        'Adaptateur Unreal expérimental : aucune exécution native ni qualité de rendu validée ici.',
        'Aperçu indépendant par image, pas une simulation temporelle : les vitesses sont conservées, sans trajectoire ni connexion ROS2/LOTUSim dans Unreal.',
        'Mer plane de prévisualisation uniquement ; houle, pluie, nuages et hydrodynamique non reproduits. Les paramètres demandés restent dans les métadonnées.',
        'Caméra au poste de navigation théorique (12,4 m) ; coque FREMM absente, pas de rambardes substituées.',
        'RGB éditeur seulement : aucune annotation, occultation, thermique ou vision nocturne Unreal implémentée ; far clip perspective non appliqué.',
        'Le cadrage en pixels est une estimation pinhole à partir des dimensions catalogue, pas une garantie de pixels visibles.',
        'Les matériaux OBJ/MTL sont importés sans garantie de parité avec les shaders Unity ; garder les crédits et restrictions des modèles sources.',
    ]
    script_path = (
        core_root / 'artifacts/campaign-settings/prepared' / identifier / 'scene_unreal.py'
    )
    instructions = [
        'Ouvrir LOTUSimPrepared.uproject avec Unreal Engine 5.5/5.6 (ou un projet UE compatible avec les plugins indiqués). Aucune ouverture automatique par le dashboard.',
        'Enregistrer/fermer les niveaux et assets modifiés avant de créer la scène ; le script refuse de perdre des modifications et refuse les destinations déjà présentes.',
        "Dans la console Python d'Unreal (Output Log, mode Python), charger le module explicitement et créer la scène : import runpy; scene = runpy.run_path("
        + repr(str(script_path))
        + "); scene['build']()",
        "Dans la même console : scene['sample'](0) applique la première image ; scene['capture_rgb'](0) demande un PNG ; scene['capture_all']() programme toute la campagne RGB. Ne pas capturer deux fois le même index : les fichiers existants ne sont jamais écrasés.",
        'Si le paquet est déplacé/extrait ailleurs, remplacer seulement le chemin du script dans la commande runpy. Tous les fichiers préparés doivent rester voisins. Aucune exécution automatique au chargement du script.',
        'Les captures et leur reçu technique sont enregistrés dans Saved/LOTUSim/<identifiant>/ du projet Unreal. Attendre les ticks éditeur, sans recharger le niveau pendant une capture.',
    ]
    plan = {
        'schema': SCHEMA,
        'id': identifier,
        'campaignSha256': campaign_sha,
        'coreRoot': str(core_root),
        'scenePath': scene_path,
        'campaign': copy.deepcopy(campaign),
        'bindings': bindings,
        'coordinates': {
            'sourceWorld': 'ENU metres: x=east,y=north,z=up',
            'unrealWorld': 'centimetres: x=north,y=east,z=up',
            'sourceGeometry': 'right-handed +X forward,+Y port,+Z up metres',
            'unrealGeometry': 'left-handed +X forward,+Y starboard,+Z up centimetres',
            'worldConversion': '[north*100,east*100,up*100]',
            'localMeshConversion': '[x*100,-y*100,z*100]; reverse face winding',
            'heading': '0=north,90=east -> Unreal yaw=headingDeg',
        },
        'nativeValidated': False,
        'limitations': limitations,
        'references': REFERENCES,
    }
    project = {
        'FileVersion': 3,
        'Category': 'LOTUSim prepared local preview',
        'Description': 'Experimental UE static maritime preview; not Unity/LOTUSim pipeline parity.',
        'Plugins': [
            {'Name': name, 'Enabled': True}
            for name in (
                'PythonScriptPlugin',
                'EditorScriptingUtilities',
                'SequencerScripting',
                'MovieRenderPipeline',
                'Water',
            )
        ],
    }
    script = Path(__file__).with_name('unreal_scene_template.py').read_bytes()
    files = {
        'LOTUSimPrepared.uproject': _json(project),
        'scene_unreal.py': script,
        'scene-plan.json': _json(plan),
        'unreal-instructions.txt': ('\n\n'.join(instructions + limitations) + '\n').encode('utf-8'),
    }
    if any(len(value) > 1024 * 1024 for value in files.values()):
        raise ValueError('Prepared Unreal package metadata exceeds 1 MiB per file')
    return {
        'files': files,
        'manifest': {
            'scenePath': scene_path,
            'nativeValidated': False,
            'runtimeRequirements': [
                'Unreal Editor 5.5/5.6 with Python/editor scripting and OBJ static import support',
                'Local access to unchanged CORE assets/models sources',
                'Interactive editor viewport for screenshot tasks',
            ],
            'limitations': limitations,
            'instructions': instructions,
            'references': REFERENCES,
            'annotationSupported': False,
            'rosConnectionSupported': False,
            'waveSimulationSupported': False,
            'rgbCaptureMethod': 'AutomationLibrary.take_high_res_screenshot; editor ticks required',
            'sampleSemantics': 'independent deterministic samples; not temporal trajectories',
        },
    }
