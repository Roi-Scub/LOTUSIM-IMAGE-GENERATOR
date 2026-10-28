"""Stdlib automatic mesh integration coordinator; conversion stays in an isolated worker.

Queue -> immutable neutral bundle -> Unity prefab/Addressable acknowledgement ->
owned Gazebo visual -> additional campaign catalogue. No Play, ROS or engine launch.
"""

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid
import xml.etree.ElementTree as ET

from mesh_library import MeshError, regular_bytes, read_json, strict_json, no_symlinks, safe_name

REQUEST_SCHEMA = 'lotusim-unity-mesh-import-1'
RESULT_SCHEMA = 'lotusim-unity-mesh-result-1'
CATALOG_SCHEMA = 'lotusim-imported-catalogue-1'
CLASSES = {
    name: n + 1
    for n, name in enumerate(
        (
            'buoy',
            'drone',
            'helicopter',
            'airplane',
            'bird',
            'fishing_trawler',
            'container_ship',
            'motor_yacht',
            'speedboat',
            'jetski',
            'ferry',
            'sailboat',
            'other',
        )
    )
}
AIR = {'drone', 'helicopter', 'airplane', 'bird'}
HEX = re.compile(r'[0-9a-f]{64}\Z')
MAX_SOURCE = 64 * 1024 * 1024
MAX_BUNDLE = 256 * 1024 * 1024
_REGISTRY_LOCK = threading.RLock()
_HASH_LOCK = threading.RLock()
_HASH_CACHE = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return (
        json.dumps(
            value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(',', ':')
        )
        + '\n'
    ).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path, limit, need_bytes=False):
    """Cache verified immutable content by inode, size, mtime AND ctime.

    Directory/symlink checks still run. Changing content or replacing a file
    invalidates the cache, even if a caller restores its previous mtime.
    """
    path = Path(path).absolute()
    if not no_symlinks(path):
        return None
    try:
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            return None
        key = (
            str(path),
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        if not need_bytes:
            with _HASH_LOCK:
                cached = _HASH_CACHE.get(key)
            if cached is not None:
                return cached, before.st_size, None
        data = regular_bytes(path, limit)
        if data is None:
            return None
        value = digest(data)
        after = os.lstat(path)
        current = (
            str(path),
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if current == key and len(data) == after.st_size:
            with _HASH_LOCK:
                if len(_HASH_CACHE) >= 4096:
                    for old in list(_HASH_CACHE)[:512]:
                        _HASH_CACHE.pop(old, None)
                _HASH_CACHE[key] = value
        return value, len(data), data if need_bytes else None
    except (OSError, ValueError):
        return None


def require(value, message):
    if not value:
        raise MeshError(message)


def identifier(value):
    require(
        isinstance(value, str) and value.startswith('import-'), 'Identifiant d’import invalide.'
    )
    try:
        parsed = uuid.UUID(value[7:])
    except (ValueError, TypeError, AttributeError) as error:
        raise MeshError('Identifiant d’import invalide.') from error
    require(
        parsed.version == 4 and value == 'import-' + str(parsed), 'Identifiant d’import invalide.'
    )
    return value


def domain_for(category):
    require(
        isinstance(category, str) and category in CLASSES,
        'Catégorie non intégrable : sélectionner une catégorie connue.',
    )
    return 'air' if category in AIR else 'moored' if category in ('buoy', 'other') else 'sea'


def normalize_options(category, up_axis, raw):
    domain = domain_for(category)
    require(up_axis in ('Y', 'Z'), 'Axe vertical Y ou Z requis.')
    require(raw is None or isinstance(raw, dict), 'Options d’intégration invalides.')
    raw = raw or {}
    fields = {'metresPerUnit', 'forwardAxis', 'draftM', 'maxSpeedMps', 'maxAltitudeM'}
    require(not (set(raw) - fields), 'Option d’intégration inconnue.')
    defaults = {
        'metresPerUnit': 1.0,
        'forwardAxis': '+X' if up_axis == 'Z' else '+Z',
        'draftM': 0.0,
        'maxSpeedMps': 0.0,
        'maxAltitudeM': 120.0 if domain == 'air' else 0.0,
    }
    result = dict(defaults, **raw)
    ranges = {
        'metresPerUnit': (0.000001, 10000),
        'draftM': (0, 25),
        'maxSpeedMps': (0, 350),
        'maxAltitudeM': (0, 15000),
    }
    for key, (low, high) in ranges.items():
        value = result[key]
        require(
            type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            'Valeur d’intégration invalide : ' + key,
        )
        result[key] = float(value)
    require(
        result['forwardAxis'] in ('+X', '-X', '+Y', '-Y', '+Z', '-Z')
        and result['forwardAxis'][1] != up_axis,
        'L’axe avant doit être perpendiculaire à l’axe vertical.',
    )
    require(
        domain != 'moored' or result['maxSpeedMps'] == 0,
        'Une bouée ou un objet fixe doit rester à vitesse nulle.',
    )
    require(
        domain == 'air' or result['maxAltitudeM'] == 0,
        'L’altitude maximale des objets non aériens doit être nulle.',
    )
    require(
        domain != 'air' or result['draftM'] == 0, 'Un objet aérien ne possède pas de tirant d’eau.'
    )
    return result


def root_for(core, import_id):
    identifier(import_id)
    core = Path(core).resolve()
    root = core / 'artifacts/mesh-library/imports' / import_id
    require(no_symlinks(root) and root.is_dir(), 'Import local introuvable ou chemin non sûr.')
    return root


def atomic(path, value):
    path = Path(path)
    require(
        no_symlinks(path.parent) and path.parent.is_dir() and not path.is_symlink(),
        'Stockage d’intégration non sûr.',
    )
    temporary = path.parent / ('.integration-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(encoded(value) if not isinstance(value, bytes) else value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_context(core, unity, import_id, source_bytes=False):
    root = root_for(core, import_id)
    receipt = read_json(root / 'asset.json')
    asset = receipt.get('asset')
    require(
        receipt.get('schema') == 'lotusim-imported-mesh-1'
        and isinstance(asset, dict)
        and asset.get('id') == import_id,
        'Reçu d’import invalide.',
    )
    category = asset.get('category')
    domain = domain_for(category)
    require(
        isinstance(asset.get('license'), str) and bool(asset['license'].strip()),
        'Licence déclarée manquante.',
    )
    preview = asset.get('preview', {})
    require(isinstance(preview, dict), 'Description du mesh invalide.')
    up_axis = preview.get('upAxis', 'Y')
    override_path = root / 'integration-options.json'
    overrides = read_json(override_path)
    if override_path.exists() or override_path.is_symlink():
        require(
            overrides.get('schema') == 'lotusim-integration-options-1'
            and overrides.get('id') == import_id,
            'Réglages d’intégration invalides.',
        )
    options = normalize_options(
        category, up_axis, overrides.get('options', asset.get('integrationOptions'))
    )
    token = overrides.get('attemptToken', 'initial')
    require(
        isinstance(token, str) and 0 < len(token) <= 64 and re.fullmatch(r'[a-zA-Z0-9_-]+', token),
        'Jeton de préparation invalide.',
    )
    hashes = receipt.get('sha256')
    require(
        isinstance(hashes, dict) and 0 < len(hashes) <= 100, 'Inventaire des fichiers manquant.'
    )
    files, total = {}, 0
    for name, expected in hashes.items():
        safe_name(name)
        require(isinstance(expected, str) and HEX.fullmatch(expected), 'Empreinte source invalide.')
        value = file_digest(root / 'files' / name, MAX_SOURCE, need_bytes=source_bytes)
        require(
            value is not None and value[0] == expected, 'Fichier source absent ou modifié : ' + name
        )
        total += value[1]
        require(total <= MAX_SOURCE, 'Import supérieur à 64 Mio.')
        if source_bytes:
            files[name] = value[2]
    entry = receipt.get('entryFile')
    if entry is None:
        # Compatibility with the previous dashboard, whose receipt kept only
        # a local preview URL. It never makes an arbitrary URI into a path.
        prefix = '/api/assets/files/' + import_id + '/'
        path = urlsplit(str(preview.get('url', ''))).path
        entry = unquote(path[len(prefix) :]) if path.startswith(prefix) else None
        if entry is None:
            candidates = [
                name
                for name in hashes
                if Path(name).suffix.lower() in ('.obj', '.stl', '.glb', '.gltf')
            ]
            entry = candidates[0] if len(candidates) == 1 else None
    require(
        entry in hashes and Path(entry).suffix.lower() in ('.obj', '.stl', '.glb', '.gltf'),
        'Fichier principal d’import introuvable.',
    )
    source = {
        'schema': REQUEST_SCHEMA,
        'converterVersion': 1,
        'id': import_id,
        'sha256': hashes,
        'category': category,
        'upAxis': up_axis,
        'options': options,
        'entryFile': entry,
        'label': str(asset.get('label', import_id))[:150],
        'license': str(asset.get('license', ''))[:1000],
        'sourceUrl': str(asset.get('sourceUrl', ''))[:1500],
    }
    return {
        'core': Path(core).resolve(),
        'unity': Path(unity).resolve(),
        'root': root,
        'id': import_id,
        'model': 'import_' + import_id[7:].replace('-', ''),
        'revision': digest(encoded(source)),
        'token': token,
        'category': category,
        'domain': domain,
        'classId': CLASSES[category],
        'asset': asset,
        'upAxis': up_axis,
        'options': options,
        'files': files,
        'sourceHashes': hashes,
        'entry': entry,
    }


def _current(context):
    try:
        current = load_context(context['core'], context['unity'], context['id'])
        return current['revision'] == context['revision'] and current['token'] == context['token']
    except (MeshError, OSError, ValueError):
        return False


def set_status(context, state, message):
    if _current(context):
        path = context['root'] / 'integration-status.json'
        prior = read_json(path)
        value = {
            'schema': 'lotusim-integration-status-1',
            'id': context['id'],
            'revisionSha256': context['revision'],
            'attemptToken': context['token'],
            'state': state,
            'message': str(message)[:300],
        }
        if all(prior.get(key) == item for key, item in value.items()):
            return
        atomic(path, dict(value, updatedAt=now()))


def _request(context, verify_files=True):
    data = regular_bytes(context['root'] / 'unity-request.json', 1024 * 1024)
    if data is None:
        return None
    try:
        request = strict_json(data)
        require(
            isinstance(request, dict)
            and request.get('schema') == REQUEST_SCHEMA
            and request.get('id') == context['id']
            and request.get('model') == context['model']
            and request.get('revisionSha256') == context['revision']
            and request.get('attemptToken', 'initial') == context['token']
            and request.get('category') == context['category']
            and request.get('classId') == context['classId']
            and request.get('domain') == context['domain'],
            'Préparation Unity obsolète.',
        )
        require(
            request.get('bundleDirectory') == 'prepared/' + context['revision']
            and request.get('geometryFile') == 'geometry.bytes'
            and request.get('infoFile') == 'model-info.json',
            'Chemin de préparation invalide.',
        )
        descriptors = request.get('files')
        require(
            isinstance(descriptors, list) and 4 <= len(descriptors) <= 805,
            'Inventaire de préparation invalide.',
        )
        names, total = set(), 0
        for item in descriptors:
            require(isinstance(item, dict), 'Descripteur de fichier invalide.')
            name, expected, size = item.get('path'), item.get('sha256'), item.get('bytes')
            safe_name(name)
            require(
                '/' not in name
                and name not in names
                and isinstance(expected, str)
                and HEX.fullmatch(expected)
                and type(size) is int
                and 0 < size <= MAX_BUNDLE,
                'Descripteur de fichier invalide.',
            )
            names.add(name)
            total += size
            require(
                name in ('geometry.bytes', 'model-info.json', 'gazebo.obj', 'gazebo.mtl')
                or re.fullmatch(r'[A-Za-z0-9_-]+\.png', name),
                'Type de fichier préparé non autorisé.',
            )
            require(total <= MAX_BUNDLE, 'Préparation trop volumineuse.')
            if verify_files:
                raw = file_digest(context['root'] / request['bundleDirectory'] / name, size)
                require(
                    raw is not None and raw[1] == size and raw[0] == expected,
                    'Fichier préparé absent ou modifié.',
                )
        require(
            {'geometry.bytes', 'model-info.json', 'gazebo.obj', 'gazebo.mtl'} <= names,
            'Préparation incomplète.',
        )
        dimensions = request.get('dimensions', {})
        require(isinstance(dimensions, dict), 'Dimensions préparées invalides.')
        for key in ('lengthM', 'beamM', 'heightM'):
            value = dimensions.get(key)
            require(
                type(value) in (int, float) and math.isfinite(value) and 0.001 <= value <= 1000,
                'Dimensions préparées invalides (0,001 à 1 000 m).',
            )
        require(
            dimensions.get('draftM') == context['options']['draftM'],
            'Tirant d’eau préparé différent du réglage courant.',
        )
        info = read_json(context['root'] / request['bundleDirectory'] / 'model-info.json')
        require(
            info.get('key') == context['model']
            and info.get('category') == context['category']
            and info.get('sourceFiles') == context['sourceHashes']
            and info.get('sha256') == context['sourceHashes'][context['entry']]
            and all(
                info.get(key) == dimensions[key]
                for key in ('lengthM', 'beamM', 'heightM', 'draftM')
            ),
            'Métadonnées préparées incohérentes.',
        )
        normalization = info.get('normalization', {})
        require(
            isinstance(normalization, dict)
            and normalization.get('upAxis') == context['upAxis']
            and normalization.get('forwardAxis') == context['options']['forwardAxis']
            and normalization.get('scale') == context['options']['metresPerUnit'],
            'Normalisation préparée incohérente.',
        )
        profile = {
            'maxSpeedMps': context['options']['maxSpeedMps'],
            'maxAltitudeM': context['options']['maxAltitudeM'],
            'bufferM': max(0.5, min(200, dimensions['lengthM'] * 0.8)),
        }
        require(
            request.get('profile') == profile
            and request.get('label') == str(context['asset'].get('label', context['model']))[:150]
            and request.get('license') == str(context['asset'].get('license', ''))[:1000]
            and request.get('sourceUrl') == str(context['asset'].get('sourceUrl', ''))[:1500],
            'Profil ou provenance préparés incohérents.',
        )
        return request, digest(data)
    except (MeshError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _acknowledged(context, request_and_sha):
    if not request_and_sha:
        return None
    request, request_sha = request_and_sha
    ack = read_json(context['root'] / 'unity-result.json')
    if not (
        ack.get('schema') == RESULT_SCHEMA
        and ack.get('id') == context['id']
        and ack.get('revisionSha256') == context['revision']
        and ack.get('requestSha256') == request_sha
    ):
        return None
    if ack.get('status') == 'failed':
        return {'failed': True}
    expected_path = 'Assets/Prefabs/' + context['model'] + '.prefab'
    try:
        require(
            ack.get('status') == 'ready'
            and ack.get('prefabPath') == expected_path
            and ack.get('addressableKey') == context['model']
            and isinstance(ack.get('unityProjectPath'), str)
            and Path(ack['unityProjectPath']).resolve() == context['unity'],
            'Accusé de réception Unity invalide.',
        )
        prefab_sha = ack.get('prefabSha256')
        guid = ack.get('prefabGuid')
        require(
            isinstance(prefab_sha, str)
            and HEX.fullmatch(prefab_sha)
            and isinstance(guid, str)
            and re.fullmatch(r'[0-9a-f]{32}', guid),
            'Identité du prefab invalide.',
        )
        prefab = file_digest(context['unity'] / expected_path, 16 * 1024 * 1024)
        meta = regular_bytes(context['unity'] / (expected_path + '.meta'), 65536)
        require(
            prefab is not None
            and prefab[0] == prefab_sha
            and meta is not None
            and re.findall(rb'(?m)^guid:\s*([0-9a-f]{32})\s*$', meta) == [guid.encode()],
            'Prefab Unity absent ou modifié.',
        )
        geometry = next(item for item in request['files'] if item['path'] == 'geometry.bytes')
        require(
            ack.get('geometrySha256') == geometry['sha256'],
            'Empreinte de géométrie Unity incohérente.',
        )
        return ack
    except (MeshError, OSError, ValueError, TypeError, KeyError, StopIteration):
        return None


def _owned_model(context, require_revision=True):
    root = context['core'] / 'assets/models' / context['model']
    marker = read_json(root / 'auto-import.json')
    if not (
        no_symlinks(root)
        and root.is_dir()
        and marker.get('schema') == 'lotusim-auto-model-1'
        and marker.get('importId') == context['id']
        and (not require_revision or marker.get('revisionSha256') == context['revision'])
    ):
        return None
    hashes = marker.get('sha256')
    if not isinstance(hashes, dict) or not {'model.sdf', 'model.config'} <= set(hashes):
        return None
    for name, expected in hashes.items():
        try:
            safe_name(name)
        except MeshError:
            return None
        raw = file_digest(root / name, MAX_BUNDLE)
        if raw is None or not isinstance(expected, str) or raw[0] != expected:
            return None
    return marker


def _catalog_path(core):
    return Path(core).resolve() / 'assets/scenarios/catalogs/imported_assets.json'


def _catalog_record(context, request, request_sha, ack):
    d, o = request['dimensions'], context['options']
    speed, altitude = o['maxSpeedMps'], o['maxAltitudeM']
    return {
        'model': context['model'],
        'category': context['category'],
        'domain': context['domain'],
        **d,
        'label': str(context['asset'].get('label', context['model']))[:150],
        'speedUnit': 'mps',
        'speedMin': 0,
        'speedMax': speed,
        'maxSpeedMps': speed,
        'maxAltitudeM': altitude,
        'altitudeM': [0, altitude],
        'rangeM': [50, 2000],
        'bufferM': max(0.5, min(200, d['lengthM'] * 0.8)),
        'priority': 5,
        'evidence': 'user_declared_static_import_bounds_and_limits_not_certified',
        'importId': context['id'],
        'requestSha256': request_sha,
        'revisionSha256': context['revision'],
        'prefabGuid': ack['prefabGuid'],
        'prefabSha256': ack['prefabSha256'],
        'classId': context['classId'],
    }


def _publish(context, request, request_sha, ack):
    require(_current(context), 'Préparation devenue obsolète.')
    models = context['core'] / 'assets/models'
    require(models.is_dir() and no_symlinks(models), 'Répertoire des modèles Gazebo indisponible.')
    destination = models / context['model']
    exists = destination.exists()
    if exists:
        require(
            _owned_model(context, False) is not None,
            'Le modèle Gazebo existant a été modifié ; aucun fichier écrasé.',
        )
    staging = Path(tempfile.mkdtemp(prefix='.auto-mesh-', dir=models))
    try:
        revision_dir = staging / 'revisions' / context['revision']
        revision_dir.mkdir(parents=True)
        source = context['root'] / request['bundleDirectory']
        hashes = {}
        for item in request['files']:
            name = item['path']
            if name not in ('gazebo.obj', 'gazebo.mtl') and not name.lower().endswith('.png'):
                continue
            raw = regular_bytes(source / name, item['bytes'])
            require(
                raw is not None and digest(raw) == item['sha256'],
                'Fichier visuel Gazebo absent ou modifié.',
            )
            (revision_dir / name).write_bytes(raw)
            hashes['revisions/' + context['revision'] + '/' + name] = digest(raw)
        d = request['dimensions']
        model = context['model']
        sdf = ET.Element('sdf', version='1.10')
        vessel = ET.SubElement(sdf, 'model', name=model)
        ET.SubElement(vessel, 'static').text = 'true'
        link = ET.SubElement(vessel, 'link', name='visual_body')
        visual = ET.SubElement(link, 'visual', name='appearance')
        mesh = ET.SubElement(ET.SubElement(visual, 'geometry'), 'mesh')
        ET.SubElement(mesh, 'uri').text = (
            'model://' + model + '/revisions/' + context['revision'] + '/gazebo.obj'
        )
        collision = ET.SubElement(link, 'collision', name='bounding_proxy')
        centre_z = d['heightM'] / 2 - d['draftM'] if context['domain'] != 'air' else 0
        ET.SubElement(collision, 'pose').text = '0 0 %.9g 0 0 0' % centre_z
        ET.SubElement(ET.SubElement(ET.SubElement(collision, 'geometry'), 'box'), 'size').text = (
            '%.9g %.9g %.9g' % (d['lengthM'], d['beamM'], d['heightM'])
        )
        plugin = ET.SubElement(
            vessel, 'plugin', filename='gz-sim-label-system', name='gz::sim::systems::Label'
        )
        ET.SubElement(plugin, 'label').text = str(context['classId'])
        config = ET.Element('model')
        ET.SubElement(config, 'name').text = model
        ET.SubElement(config, 'version').text = '1.0'
        ET.SubElement(config, 'sdf', version='1.10').text = 'model.sdf'
        ET.SubElement(config, 'description').text = (
            'Local static visual and bounding collision proxy. User-declared dimensions/limits; no calibrated hydrodynamics.'
        )
        for filename, xml in (('model.sdf', sdf), ('model.config', config)):
            raw = ET.tostring(xml, encoding='utf-8', xml_declaration=True)
            (staging / filename).write_bytes(raw)
            hashes[filename] = digest(raw)
        credit = {
            'title': request['label'],
            'license': request['license'],
            'sourceUrl': request['sourceUrl'],
            'sourceFiles': context['sourceHashes'],
            'rightsStatus': 'user_declared_not_legally_verified',
            'changes': 'Static conversion, user-declared units/axes, opaque material and bounding collision proxies; no calibrated hydrodynamics.',
        }
        attribution = (
            request['label']
            + '\nDeclared licence: '
            + request['license']
            + '\nSource: '
            + request['sourceUrl']
            + '\n\nRights and scale are user declarations, not an automatic certification.\n'
            + credit['changes']
            + '\n'
        ).encode('utf-8')
        (staging / 'ATTRIBUTION.txt').write_bytes(attribution)
        hashes['ATTRIBUTION.txt'] = digest(attribution)
        marker = {
            'schema': 'lotusim-auto-model-1',
            'importId': context['id'],
            'revisionSha256': context['revision'],
            'requestSha256': request_sha,
            'sha256': hashes,
            'credit': credit,
            'updatedAt': now(),
        }
        (staging / 'auto-import.json').write_bytes(encoded(marker))
        require(_current(context), 'Préparation devenue obsolète.')
        if exists:
            # Existing immutable revisions are retained. Changed current files
            # are refused before this point, never repaired behind the user's back.
            target_revision = destination / 'revisions' / context['revision']
            if not target_revision.exists():
                target_revision.parent.mkdir(exist_ok=True)
                revision_dir.rename(target_revision)
            for filename in ('model.sdf', 'model.config', 'ATTRIBUTION.txt'):
                atomic(destination / filename, (staging / filename).read_bytes())
            atomic(destination / 'auto-import.json', marker)
        else:
            staging.rename(destination)
        require(_owned_model(context) is not None, 'Validation du modèle Gazebo impossible.')
        catalog_path = _catalog_path(context['core'])
        require(no_symlinks(catalog_path.parent), 'Répertoire du catalogue importé non sûr.')
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with _REGISTRY_LOCK:
            catalog = read_json(catalog_path)
            require(
                not catalog_path.exists() or catalog.get('schema') == CATALOG_SCHEMA,
                'Catalogue importé existant non reconnu ; aucun écrasement.',
            )
            assets = catalog.get('assets', [])
            require(isinstance(assets, list), 'Catalogue importé invalide.')
            assets = [
                item
                for item in assets
                if isinstance(item, dict) and item.get('importId') != context['id']
            ]
            assets.append(_catalog_record(context, request, request_sha, ack))
            atomic(catalog_path, {'schema': CATALOG_SCHEMA, 'assets': assets, 'updatedAt': now()})
    finally:
        if staging.exists():
            shutil.rmtree(staging)  # Only this operation's unpublished private staging.


def ready_imports(core, unity):
    result = []
    catalog = read_json(_catalog_path(core))
    if catalog.get('schema') != CATALOG_SCHEMA or not isinstance(catalog.get('assets'), list):
        return result
    seen = set()
    for record in catalog['assets'][:500]:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get('importId'), str)
            or record['importId'] in seen
        ):
            continue
        try:
            context = load_context(core, unity, record.get('importId'))
            request_pair = _request(context)
            ack = _acknowledged(context, request_pair)
            require(ack and not ack.get('failed') and _owned_model(context), 'Import non confirmé.')
            expected = _catalog_record(context, *request_pair, ack)
            require(record == expected, 'Catalogue importé obsolète ou modifié.')
            result.append(expected)
            seen.add(context['id'])
        except (MeshError, OSError, ValueError, TypeError, KeyError):
            continue
    return result


def neutral_imports(core, unity=None):
    """Verified converted sources, independently of any engine prefab or SDK.

    This proves source geometry availability only. It neither installs models
    in a renderer nor claims native compatibility. Unity still uses ready_imports.
    All paths are relative to CORE and hashes bind the prepared immutable bundle.
    """
    core = Path(core).resolve()
    unity = Path(unity) if unity is not None else core.parent / 'LOTUSim-Unity-modules'
    directory = core / 'artifacts/mesh-library/imports'
    if not no_symlinks(directory) or not directory.is_dir():
        return []
    result = []
    with os.scandir(directory) as entries:
        for index, entry in enumerate(entries):
            if index >= 500:
                break
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                context = load_context(core, unity, entry.name)
                pair = _request(context)
                require(pair is not None, 'Neutral conversion is not verified.')
                request, request_sha = pair
                dimensions, options = request['dimensions'], context['options']
                relative = context['root'].relative_to(core) / request['bundleDirectory']
                files = [
                    {**item, 'path': (relative / item['path']).as_posix()}
                    for item in request['files']
                ]
                geometry = next(item for item in files if item['path'].endswith('/geometry.bytes'))
                obj = next(item for item in files if item['path'].endswith('/gazebo.obj'))
                result.append(
                    {
                        'model': context['model'],
                        'category': context['category'],
                        'domain': context['domain'],
                        **dimensions,
                        'label': request['label'],
                        'license': request['license'],
                        'sourceUrl': request['sourceUrl'],
                        'speedUnit': 'mps',
                        'speedMin': 0,
                        'speedMax': options['maxSpeedMps'],
                        'maxSpeedMps': options['maxSpeedMps'],
                        'maxAltitudeM': options['maxAltitudeM'],
                        'altitudeM': [0, options['maxAltitudeM']],
                        'rangeM': [50, 2000],
                        'bufferM': request['profile']['bufferM'],
                        'priority': 5,
                        'classId': context['classId'],
                        'importId': context['id'],
                        'revisionSha256': context['revision'],
                        'requestSha256': request_sha,
                        'geometrySha256': geometry['sha256'],
                        'neutralReady': True,
                        'rendererReady': False,
                        'evidence': 'verified_converted_geometry_not_native_renderer_compatibility',
                        'neutralSource': {
                            'root': 'core',
                            'obj': obj['path'],
                            'files': files,
                            'coordinates': 'model_m_X_forward_Y_port_Z_up',
                        },
                    }
                )
            except (MeshError, OSError, ValueError, TypeError, KeyError, StopIteration):
                continue
    return result


def integration_public(core, unity, import_id):
    public = {
        'state': 'queued',
        'message': 'En attente de préparation locale.',
        'model': '',
        'options': {},
        'updatedAt': None,
    }
    try:
        context = load_context(core, unity, import_id)
        public.update(model=context['model'], options=context['options'])
        pair = _request(context)
        ack = _acknowledged(context, pair)
        if ack and not ack.get('failed') and _owned_model(context):
            records = read_json(_catalog_path(core)).get('assets', [])
            if isinstance(records, list) and _catalog_record(context, *pair, ack) in records:
                marker = _owned_model(context)
                public.update(
                    state='ready',
                    message='Prefab Unity, visuel Gazebo et catalogue de scénarios disponibles.',
                    updatedAt=marker.get('updatedAt'),
                )
                return public
        status = read_json(context['root'] / 'integration-status.json')
        if (
            status.get('revisionSha256') == context['revision']
            and status.get('attemptToken', 'initial') == context['token']
        ):
            if status.get('state') in ('queued', 'preparing', 'waiting_unity', 'failed'):
                public.update(
                    state=status['state'],
                    message=str(status.get('message', ''))[:300],
                    updatedAt=status.get('updatedAt'),
                )
            elif status.get('state') == 'ready':
                public.update(
                    state='failed',
                    message='La confirmation précédente n’est plus valide : fichier, prefab ou catalogue modifié.',
                    updatedAt=status.get('updatedAt'),
                )
        elif pair:
            public.update(
                state='waiting_unity',
                message='Ouvrir le projet Unity hors Play pour terminer l’import automatiquement.',
            )
        if ack and ack.get('failed'):
            public.update(
                state='failed',
                message='Unity a refusé le prefab ; consulter son journal puis relancer la préparation.',
            )
    except (MeshError, OSError, ValueError, TypeError) as error:
        public.update(
            state='failed',
            message=(
                str(error)[:300]
                if isinstance(error, MeshError)
                else 'Lecture de l’intégration impossible.'
            ),
        )
    return public


def prepare_worker(core, unity, import_id):
    from mesh_convert import convert, MeshConvertError

    context = load_context(core, unity, import_id, source_bytes=True)
    prepared = context['root'] / 'prepared'
    require(no_symlinks(prepared), 'Répertoire de préparation non sûr.')
    prepared.mkdir(exist_ok=True)
    destination = prepared / context['revision']
    temporary = Path(tempfile.mkdtemp(prefix='.conversion-', dir=prepared))
    try:
        if destination.exists():
            require(
                no_symlinks(destination) and destination.is_dir(), 'Préparation existante non sûre.'
            )
            info = read_json(destination / 'model-info.json')
            require(
                info.get('key') == context['model']
                and info.get('sourceFiles') == context['sourceHashes'],
                'Préparation existante non reconnue.',
            )
        else:
            metadata = {
                'model': context['model'],
                'category': context['category'],
                'domain': context['domain'],
                'label': str(context['asset'].get('label', context['model']))[:150],
                'license': str(context['asset'].get('license', ''))[:1000],
                'sourceUrl': str(context['asset'].get('sourceUrl', ''))[:1500],
                'upAxis': context['upAxis'],
                **context['options'],
            }
            try:
                info = convert(context['entry'], context['files'], metadata, temporary)
            except MeshConvertError as error:
                raise MeshError(str(error)[:300]) from error
            require(
                _current(context), 'Préparation devenue obsolète ; nouveaux réglages conservés.'
            )
            temporary.rename(destination)
        files = []
        total = 0
        for path in sorted(destination.iterdir()):
            safe_name(path.name)
            raw = regular_bytes(path, MAX_BUNDLE)
            require(raw is not None, 'Fichier préparé invalide.')
            total += len(raw)
            require(total <= MAX_BUNDLE, 'Préparation trop volumineuse.')
            files.append({'path': path.name, 'sha256': digest(raw), 'bytes': len(raw)})
        dimensions = {key: info[key] for key in ('lengthM', 'beamM', 'heightM', 'draftM')}
        require(
            all(
                type(dimensions[key]) in (int, float)
                and math.isfinite(dimensions[key])
                and 0.001 <= dimensions[key] <= 1000
                for key in ('lengthM', 'beamM', 'heightM')
            ),
            'Dimensions hors limites Unity : chaque dimension doit être comprise entre 0,001 et 1 000 m. Vérifier l’échelle déclarée.',
        )
        request = {
            'schema': REQUEST_SCHEMA,
            'id': context['id'],
            'model': context['model'],
            'revisionSha256': context['revision'],
            'attemptToken': context['token'],
            'category': context['category'],
            'domain': context['domain'],
            'classId': context['classId'],
            'label': str(context['asset'].get('label', context['model']))[:150],
            'license': str(context['asset'].get('license', ''))[:1000],
            'sourceUrl': str(context['asset'].get('sourceUrl', ''))[:1500],
            'dimensions': dimensions,
            'profile': {
                'maxSpeedMps': context['options']['maxSpeedMps'],
                'maxAltitudeM': context['options']['maxAltitudeM'],
                'bufferM': max(0.5, min(200, dimensions['lengthM'] * 0.8)),
            },
            'bundleDirectory': 'prepared/' + context['revision'],
            'geometryFile': 'geometry.bytes',
            'infoFile': 'model-info.json',
            'files': files,
        }
        require(_current(context), 'Préparation devenue obsolète ; nouveaux réglages conservés.')
        atomic(context['root'] / 'unity-request.json', request)
        require(_request(context) is not None, 'Préparation publiée invalide.')
        set_status(
            context,
            'waiting_unity',
            'Ouvrir le projet Unity hors Play : le prefab et son adresse seront créés automatiquement.',
        )
        return request
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)  # Only this worker's unique unpublished output.


class MeshIntegrationService:
    def __init__(self, core, unity):
        self.core, self.unity = Path(core).resolve(), Path(unity).resolve()
        self.stop_event = threading.Event()
        self.thread = None
        self.child = None
        self.lock = threading.RLock()
        self.last_error = None

    def request(self, import_id, options):
        context = load_context(self.core, self.unity, import_id)
        normalized = normalize_options(context['category'], context['upAxis'], options)
        atomic(
            context['root'] / 'integration-options.json',
            {
                'schema': 'lotusim-integration-options-1',
                'id': import_id,
                'options': normalized,
                'attemptToken': uuid.uuid4().hex,
            },
        )
        context = load_context(self.core, self.unity, import_id)
        set_status(
            context, 'queued', 'Préparation automatique demandée ; aucun scénario en cours modifié.'
        )
        return integration_public(self.core, self.unity, import_id)

    def _run_worker(self, context):
        interpreter = self.core / '.venv-vision/bin/python'
        script = Path(__file__).resolve()
        require(
            interpreter.is_file(),
            'Python de conversion indisponible : installer l’environnement vision local.',
        )
        process = subprocess.Popen(
            [
                str(interpreter),
                str(script),
                '--worker',
                str(self.core),
                str(self.unity),
                context['id'],
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        with self.lock:
            self.child = process
        deadline = time.monotonic() + 180
        try:
            while True:
                if self.stop_event.is_set() or time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=3)
                    raise MeshError('Conversion arrêtée ou délai dépassé ; aucun scénario lancé.')
                try:
                    out, err = process.communicate(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                try:
                    result = strict_json(out[:8192])
                    message = result.get('error') if isinstance(result, dict) else None
                except ValueError:
                    message = None
                raise MeshError(
                    str(message)[:300]
                    if message
                    else 'Conversion refusée ; consulter les caractéristiques du fichier source.'
                )
        finally:
            with self.lock:
                self.child = None

    def tick(self):
        store = self.core / 'artifacts/mesh-library/imports'
        if not store.is_dir() or not no_symlinks(store):
            return
        directory = os.open(store, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = None
        try:
            descriptor = os.open(
                '.integration.lock',
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                0o600,
                dir_fd=directory,
            )
            require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'Verrou d’intégration invalide.')
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            self._tick_owned(store)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)

    def _tick_owned(self, store):
        for root in sorted(store.iterdir())[:500]:
            if self.stop_event.is_set():
                break
            try:
                identifier(root.name)
            except MeshError:
                continue
            context = None
            try:
                context = load_context(self.core, self.unity, root.name)
                pair = _request(context)
                ack = _acknowledged(context, pair)
                if ack:
                    if ack.get('failed'):
                        set_status(
                            context,
                            'failed',
                            'Unity a refusé le prefab ; consulter son journal puis réessayer.',
                        )
                    else:
                        if not _owned_model(context) or _catalog_record(
                            context, *pair, ack
                        ) not in read_json(_catalog_path(self.core)).get('assets', []):
                            _publish(context, *pair, ack)
                        set_status(
                            context,
                            'ready',
                            'Prefab Unity, visuel Gazebo et catalogue de scénarios disponibles.',
                        )
                    continue
                if pair:
                    set_status(
                        context,
                        'waiting_unity',
                        'Ouvrir le projet Unity hors Play pour terminer l’intégration automatiquement.',
                    )
                    continue
                status = read_json(root / 'integration-status.json')
                if (
                    status.get('state') == 'failed'
                    and status.get('revisionSha256') == context['revision']
                    and status.get('attemptToken', 'initial') == context['token']
                ):
                    continue
                set_status(
                    context,
                    'preparing',
                    'Conversion locale du mesh et préparation du prefab Unity…',
                )
                self._run_worker(context)
            except (MeshError, OSError, ValueError, TypeError, KeyError) as error:
                if context is not None:
                    try:
                        set_status(
                            context,
                            'failed',
                            (
                                str(error)[:300]
                                if isinstance(error, MeshError)
                                else 'Intégration interrompue ; aucun scénario modifié.'
                            ),
                        )
                    except (OSError, ValueError):
                        pass

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()

        def run():
            while not self.stop_event.is_set():
                try:
                    self.tick()
                    self.last_error = None
                except Exception as error:
                    self.last_error = {
                        'type': type(error).__name__,
                        'message': 'Le suivi des imports a rencontré une erreur locale.',
                    }
                    print(
                        '[Mesh integration] Local coordinator error: ' + type(error).__name__,
                        file=sys.stderr,
                        flush=True,
                    )
                self.stop_event.wait(2)

        self.thread = threading.Thread(target=run, name='lotusim-mesh-integration', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        with self.lock:
            if self.child and self.child.poll() is None:
                self.child.terminate()
        if self.thread:
            self.thread.join(timeout=4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('core', type=Path)
    parser.add_argument('unity', type=Path)
    parser.add_argument('import_id')
    args = parser.parse_args()
    if not args.worker:
        parser.error('This entry point is an isolated conversion worker only.')
    try:
        request = prepare_worker(args.core, args.unity, args.import_id)
        print(json.dumps({'success': True, 'revisionSha256': request['revisionSha256']}))
        return 0
    except (MeshError, OSError, ValueError, TypeError) as error:
        print(
            json.dumps(
                {
                    'success': False,
                    'error': (
                        str(error)[:300]
                        if isinstance(error, MeshError)
                        else 'Conversion locale impossible.'
                    ),
                }
            )
        )
        return 1


if __name__ == '__main__':
    sys.exit(main())
