#!/usr/bin/env python3
"""Validated, immutable manual campaign plans. No simulator/process control.

All user-controlled files are addressed by opaque UUIDs. Directory descriptors
and O_NOFOLLOW keep storage accesses beneath the configured trusted core root,
including when an artifacts directory or an individual file is a symlink.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

from lotusim_image_generator.engines.preparation import (
    PREPARED_FILES,
    UNREAL_SCENE,
    engine_catalog,
    prepare_engine,
)
from lotusim_image_generator.engines.status import PreparationStatus, ScenePreparationStorageError
from lotusim_image_generator.engines.registry import (
    UNITY_ADAPTER as ADAPTER_PATH,
    EngineRegistry,
    EngineRegistryError,
    expected_artifacts,
)

SCHEMA = 'lotusim-campaign-settings-1'
MANIFEST_SCHEMA = 'lotusim-manual-campaign-1'
MAX_JSON_BYTES = 1_048_576
MAX_IMAGES = 2000
MAX_BLOCKS = 50
MAX_ROWS = 40
MAX_ACTORS = 40
MAX_CATEGORY_ACTORS = 12
SCENE_PATH = 'Assets/Scenes/Dataset/ManualCampaign_<id>.unity'

_IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
LIMITATIONS = [
    'Each image is an independent seeded scene sample, not continuous video.',
    'Distances are nominal horizontal ranges from the bridge camera, not a visibility guarantee.',
    'Object-image counts describe planned actor instances, not verified visible objects or detections.',
    'Pixel-height targeting uses catalogue height and a pinhole approximation; models are never rescaled.',
    'Catalogue speeds and dimensions are scenario assumptions, not certified real-world performance limits.',
    'Cloud, rain and wave settings are visual proxies, not calibrated sensor or weather physics.',
    'Only RGB requests are supported; actual capture/annotation support depends on the selected native adapter.',
    'Preparing a campaign writes a plan only; it never starts any engine, Play mode, ROS or services.',
]


class CampaignValidationError(ValueError):
    def __init__(self, validation):
        super().__init__('Campaign settings are invalid')
        self.validation = validation


class CampaignSecurityError(ValueError):
    """An opaque identifier or storage component was unsafe."""


def load_json_bytes(raw):
    """Decode bounded strict JSON, rejecting duplicate keys and non-finite data."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if not isinstance(raw, bytes):
        raise ValueError('Expected JSON bytes')
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError('JSON exceeds the 1 MiB limit')

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValueError('Non-finite JSON number: ' + value)

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        # json.loads also turns ordinary numbers such as 1e999 into infinity.
        json.dumps(value, allow_nan=False)
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as error:
        raise ValueError('Invalid UTF-8 JSON') from error
    return value


def _json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
    ).encode('utf-8')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _opaque_id(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise CampaignSecurityError('Expected an opaque campaign UUID')
    return value


class _Validator:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, message):
        self.errors.append({'path': path, 'message': message})

    def warn(self, path, message):
        self.warnings.append({'path': path, 'message': message})

    def obj(self, value, path, required, optional=()):
        if not isinstance(value, dict):
            self.error(path, 'Expected an object')
            return {}
        for key in required:
            if key not in value:
                self.error(path + '.' + key, 'Required field')
        for key in value:
            if key not in required and key not in optional:
                self.error(path + '.' + str(key), 'Unknown field')
        return value

    def number(self, value, path, low, high, integer=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.error(path, 'Expected an integer' if integer else 'Expected a finite number')
            return None
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            self.error(path, 'Expected a finite number')
            return None
        if integer and not isinstance(value, int):
            self.error(path, 'Expected an integer')
            return None
        if not low <= value <= high:
            self.error(path, 'Must be between %s and %s' % (low, high))
            return None
        return value

    def enum(self, value, path, choices):
        if not isinstance(value, str) or value not in choices:
            self.error(path, 'Expected one of: ' + ', '.join(choices))
            return None
        return value

    def text(self, value, path, identifier=False):
        if not isinstance(value, str):
            self.error(path, 'Expected text')
            return None
        value = value.strip()
        if identifier:
            if not _IDENTIFIER.fullmatch(value):
                self.error(path, 'Use 1–64 letters, digits, underscores or hyphens')
                return None
        elif not value or len(value) > 120 or any(ord(c) < 32 for c in value):
            self.error(path, 'Use 1–120 printable characters')
            return None
        return value


class CampaignStore:
    def __init__(self, core_root, unity_root=None):
        self.core_root = Path(core_root).resolve()
        self.unity_root = Path(unity_root).resolve() if unity_root is not None else None
        self.engine_registry = EngineRegistry(self.core_root, self.unity_root)

    @contextmanager
    def _directory(self, components, create=False):
        """Traverse fixed storage components without following any symlink."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(str(self.core_root), flags)
        try:
            for component in ('artifacts', 'campaign-settings', *components):
                if not re.fullmatch(r'[a-zA-Z0-9-]+', component):
                    raise CampaignSecurityError('Unsafe storage component')
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as error:
                    if error.errno in (20, 40, 62):
                        raise CampaignSecurityError(
                            'Storage directories must not be symlinks'
                        ) from error
                    raise
                os.close(descriptor)
                descriptor = child
            yield descriptor
        finally:
            os.close(descriptor)

    @staticmethod
    def _read_file(descriptor, name):
        try:
            file_descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
        except OSError as error:
            if error.errno in (20, 40, 62):
                raise CampaignSecurityError('Stored files must not be symlinks') from error
            raise
        with os.fdopen(file_descriptor, 'rb') as handle:
            details = os.fstat(handle.fileno())
            if not stat.S_ISREG(details.st_mode):
                raise CampaignSecurityError('Expected a regular stored file')
            if details.st_size > MAX_JSON_BYTES:
                raise ValueError('Stored JSON exceeds the 1 MiB limit')
            data = handle.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                raise ValueError('Stored JSON exceeds the 1 MiB limit')
            return data

    @staticmethod
    def _write_file(descriptor, name, data):
        if len(data) > MAX_JSON_BYTES:
            raise ValueError('Stored JSON exceeds the 1 MiB limit')
        file_descriptor = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor
        )
        with os.fdopen(file_descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _catalogue(self, engine=None):
        path = self.core_root / 'assets/scenarios/catalogs/traffic_assets.json'
        try:
            path.resolve().relative_to(self.core_root)
        except ValueError as error:
            raise CampaignSecurityError(
                'Traffic catalogue must remain inside the core root'
            ) from error
        with path.open('rb') as handle:
            data = handle.read(MAX_JSON_BYTES + 1)
        catalog = load_json_bytes(data)
        if not isinstance(catalog, dict) or not isinstance(catalog.get('assets'), list):
            raise ValueError('Invalid traffic catalogue')
        from lotusim_image_generator.assets.integration import ready_imports, neutral_imports

        descriptor = (
            self.engine_registry.get(engine)
            if engine is not None
            else self.engine_registry.selection()
        )
        imported = (
            ready_imports(self.core_root, self.unity_root)
            if descriptor['adapterId'] == 'unity' and self.unity_root is not None
            else (
                neutral_imports(self.core_root, self.unity_root)
                if descriptor['adapterId'] != 'unity'
                else []
            )
        )
        names = {item['model'] for item in catalog['assets']}
        if any(item['model'] in names for item in imported):
            raise ValueError('Imported model conflicts with the base catalogue')
        catalog = dict(catalog, assets=catalog['assets'] + imported)
        return catalog

    def _engines(self):
        try:
            return engine_catalog(self.core_root, self.unity_root)
        except EngineRegistryError as error:
            raise CampaignSecurityError(str(error)) from error

    def defaults(self):
        def block(identifier, label, images, daytime):
            return {
                'id': identifier,
                'name': label,
                'images': images,
                'environment': {
                    'timeOfDay': daytime,
                    'cloudCover': 0.2,
                    'rainIntensity': 0,
                    'waveHeightM': 0.5,
                    'waveDirectionDeg': 0,
                    'windMps': 3,
                },
                'objects': [
                    {
                        'id': 'buoy-1',
                        'model': 'buoy',
                        'count': 1,
                        'distanceM': 400,
                        'bearingDeg': 0,
                        'spreadDeg': 0,
                        'altitudeM': 0,
                        'speedMps': 0,
                        'headingDeg': 0,
                        'distanceMode': 'metres',
                    }
                ],
            }

        return {
            'schema': SCHEMA,
            'name': 'Campagne maritime manuelle',
            'engine': self.engine_registry.selection()['id'],
            'scene': 'maritime_manual',
            'seed': 20261027,
            'totalImages': 10,
            'camera': {
                'width': 1280,
                'height': 720,
                'verticalFovDeg': 60,
                'farClipM': 50000,
                'station': 'bridge',
                'viewHeadingDeg': 0,
                'viewDownPitchDeg': 0,
            },
            'observer': {'speedMps': 0, 'headingDeg': 0, 'rollMaxDeg': 0, 'pitchMaxDeg': 0},
            'sensors': {'rgb': True, 'thermal': False, 'nightVision': False},
            'blocks': [
                block('day', 'Jour', 3, 'day'),
                block('night', 'Nuit', 5, 'night'),
                block('dusk', 'Crépuscule', 2, 'dusk'),
            ],
        }

    def catalog(self):
        catalog = self._catalogue()
        engines = self._engines()
        return {
            'schema': 'lotusim-campaign-catalog-1',
            'engines': engines,
            'selectedEngine': self.engine_registry.selection(),
            'scenes': [
                {
                    'id': 'maritime_manual',
                    'label': 'Maritime · ' + engine['label'],
                    'path': engine['scenePath'],
                    'engine': engine['id'],
                }
                for engine in engines
            ],
            'assets': [
                dict(asset, label=asset.get('label') or asset['model'].replace('_', ' ').title())
                for asset in catalog['assets']
            ],
            'catalogueNotes': catalog.get('notes', ''),
            'limitations': list(LIMITATIONS),
            'defaults': self.defaults(),
            'campaigns': self.list(),
        }

    def validate(self, payload):
        check = _Validator()
        empty_summary = {
            'totalImages': 0,
            'allocatedImages': 0,
            'blocks': 0,
            'objectImageCounts': {},
            'categoryImageCounts': {},
            'blockSummaries': [],
        }
        try:
            encoded = _json_bytes(payload)
            if len(encoded) > MAX_JSON_BYTES:
                raise ValueError('Campaign exceeds the 1 MiB limit')
            normalized = copy.deepcopy(payload)
        except (ValueError, TypeError, OverflowError, RecursionError) as error:
            check.error('$', 'Expected finite JSON within 1 MiB: ' + str(error)[:120])
            return {
                'valid': False,
                'campaign': None,
                'errors': check.errors,
                'warnings': [],
                'summary': empty_summary,
            }
        root_fields = (
            'schema',
            'name',
            'engine',
            'scene',
            'seed',
            'totalImages',
            'camera',
            'observer',
            'sensors',
            'blocks',
        )
        root = check.obj(normalized, '$', root_fields)
        check.enum(root.get('schema'), '$.schema', (SCHEMA,))
        name = check.text(root.get('name'), '$.name')
        if name is not None:
            root['name'] = name
        engine = check.enum(
            root.get('engine'), '$.engine', tuple(item['id'] for item in self._engines())
        )
        check.enum(root.get('scene'), '$.scene', ('maritime_manual',))
        check.number(root.get('seed'), '$.seed', 0, 2147483647, True)
        total = check.number(root.get('totalImages'), '$.totalImages', 1, MAX_IMAGES, True)
        camera = check.obj(
            root.get('camera'),
            '$.camera',
            (
                'width',
                'height',
                'verticalFovDeg',
                'farClipM',
                'station',
                'viewHeadingDeg',
                'viewDownPitchDeg',
            ),
        )
        width = check.number(camera.get('width'), '$.camera.width', 64, 4096, True)
        height = check.number(camera.get('height'), '$.camera.height', 64, 4096, True)
        if width is not None and height is not None and width * height > 16777216:
            check.error('$.camera', 'Image area must not exceed 16,777,216 pixels')
        fov = check.number(camera.get('verticalFovDeg'), '$.camera.verticalFovDeg', 30, 90)
        far_clip = check.number(camera.get('farClipM'), '$.camera.farClipM', 5000, 100000)
        check.enum(camera.get('station'), '$.camera.station', ('bridge',))
        check.number(camera.get('viewHeadingDeg'), '$.camera.viewHeadingDeg', 0, 360)
        if camera.get('viewHeadingDeg') == 360:
            camera['viewHeadingDeg'] = 0
        down_pitch = check.number(
            camera.get('viewDownPitchDeg'), '$.camera.viewDownPitchDeg', -10, 15
        )
        observer = check.obj(
            root.get('observer'),
            '$.observer',
            ('speedMps', 'headingDeg', 'rollMaxDeg', 'pitchMaxDeg'),
        )
        check.number(observer.get('speedMps'), '$.observer.speedMps', 0, 13.89)
        check.number(observer.get('headingDeg'), '$.observer.headingDeg', 0, 360)
        if observer.get('headingDeg') == 360:
            observer['headingDeg'] = 0
        check.number(observer.get('rollMaxDeg'), '$.observer.rollMaxDeg', 0, 12)
        check.number(observer.get('pitchMaxDeg'), '$.observer.pitchMaxDeg', 0, 8)
        sensors = check.obj(root.get('sensors'), '$.sensors', ('rgb', 'thermal', 'nightVision'))
        for sensor, expected in (('rgb', True), ('thermal', False), ('nightVision', False)):
            if sensors.get(sensor) is not expected:
                check.error(
                    '$.sensors.' + sensor,
                    'Only RGB requests are supported; expected ' + str(expected).lower(),
                )
        descriptor = self.engine_registry.get(engine) if engine is not None else None
        if descriptor is not None and descriptor['mode'] in ('prototype', 'neutral_contract_only'):
            check.warn('$.engine', descriptor['detail'])
        assets = {asset['model']: asset for asset in self._catalogue(engine)['assets']}
        blocks = root.get('blocks')
        if not isinstance(blocks, list):
            check.error('$.blocks', 'Expected an array')
            blocks = []
        if not 1 <= len(blocks) <= MAX_BLOCKS:
            check.error('$.blocks', 'Use 1–50 blocks')
        allocated = 0
        object_images = {}
        category_images = {}
        block_summaries = []
        block_ids = set()
        for index, value in enumerate(blocks[:MAX_BLOCKS]):
            path = '$.blocks[%d]' % index
            block = check.obj(value, path, ('id', 'name', 'images', 'environment', 'objects'))
            block_id = check.text(block.get('id'), path + '.id', True)
            if block_id in block_ids:
                check.error(path + '.id', 'Block identifiers must be unique')
            if block_id is not None:
                block_ids.add(block_id)
                block['id'] = block_id
            label = check.text(block.get('name'), path + '.name')
            if label is not None:
                block['name'] = label
            images = check.number(block.get('images'), path + '.images', 1, MAX_IMAGES, True)
            allocated += images or 0
            environment = check.obj(
                block.get('environment'),
                path + '.environment',
                (
                    'timeOfDay',
                    'cloudCover',
                    'rainIntensity',
                    'waveHeightM',
                    'waveDirectionDeg',
                    'windMps',
                ),
            )
            check.enum(
                environment.get('timeOfDay'),
                path + '.environment.timeOfDay',
                ('day', 'dusk', 'night'),
            )
            for key, low, high in (
                ('cloudCover', 0, 1),
                ('rainIntensity', 0, 1),
                ('waveHeightM', 0, 8),
                ('waveDirectionDeg', 0, 360),
                ('windMps', 0, 30),
            ):
                check.number(environment.get(key), path + '.environment.' + key, low, high)
            objects = block.get('objects')
            if not isinstance(objects, list):
                check.error(path + '.objects', 'Expected an array')
                objects = []
            if len(objects) > MAX_ROWS:
                check.error(path + '.objects', 'Use at most 40 object rows per block')
            instances = 0
            categories = {}
            row_ids = set()
            for row_index, row_value in enumerate(objects[:MAX_ROWS]):
                row_path = path + '.objects[%d]' % row_index
                row = check.obj(
                    row_value,
                    row_path,
                    (
                        'id',
                        'model',
                        'count',
                        'distanceM',
                        'bearingDeg',
                        'spreadDeg',
                        'altitudeM',
                        'speedMps',
                        'headingDeg',
                        'distanceMode',
                    ),
                    ('targetHeightPx',),
                )
                row_id = check.text(row.get('id'), row_path + '.id', True)
                if row_id in row_ids:
                    check.error(
                        row_path + '.id', 'Object row identifiers must be unique within a block'
                    )
                if row_id is not None:
                    row_ids.add(row_id)
                    row['id'] = row_id
                asset = assets.get(row.get('model')) if isinstance(row.get('model'), str) else None
                if asset is None:
                    check.error(row_path + '.model', 'Unknown catalogue model')
                count = check.number(row.get('count'), row_path + '.count', 1, MAX_ACTORS, True)
                instances += count or 0
                mode = check.enum(
                    row.get('distanceMode'), row_path + '.distanceMode', ('metres', 'pixel_height')
                )
                distance = check.number(row.get('distanceM'), row_path + '.distanceM', 5, 60000)
                bearing = check.number(row.get('bearingDeg'), row_path + '.bearingDeg', -180, 180)
                check.number(row.get('spreadDeg'), row_path + '.spreadDeg', 0, 180)
                check.number(row.get('headingDeg'), row_path + '.headingDeg', 0, 360)
                if row.get('headingDeg') == 360:
                    row['headingDeg'] = 0
                altitude_max = min(asset.get('maxAltitudeM', 0), 15000) if asset else 15000
                altitude = check.number(
                    row.get('altitudeM'), row_path + '.altitudeM', 0, altitude_max
                )
                check.number(
                    row.get('speedMps'),
                    row_path + '.speedMps',
                    0,
                    asset.get('maxSpeedMps', 0) if asset else 250,
                )
                if mode == 'pixel_height':
                    target = check.number(
                        row.get('targetHeightPx'), row_path + '.targetHeightPx', 0.1, height or 4096
                    )
                    if asset and target is not None and height is not None and fov is not None:
                        distance = (
                            asset['heightM']
                            * height
                            / (2 * math.tan(math.radians(fov) / 2) * target)
                        )
                        if not 5 <= distance <= 60000:
                            check.error(
                                row_path + '.targetHeightPx',
                                'Pixel target implies a nominal distance outside 5–60000 m',
                            )
                        else:
                            row['distanceM'] = distance
                        check.warn(
                            row_path + '.targetHeightPx',
                            'Approximate pixel height only: catalogue dimensions, altitude, orientation and occlusion affect visibility; no model scaling',
                        )
                elif 'targetHeightPx' in row:
                    check.number(
                        row.get('targetHeightPx'), row_path + '.targetHeightPx', 0.1, height or 4096
                    )
                    check.warn(row_path + '.targetHeightPx', 'Ignored in metres mode')
                if distance is not None and far_clip is not None and distance > far_clip:
                    check.warn(
                        row_path + '.distanceM',
                        'Nominal range exceeds camera far clip; the object may not be visible',
                    )
                if count and count > 1 and row.get('spreadDeg') == 0:
                    check.warn(
                        row_path + '.spreadDeg',
                        'Multiple actors share the same nominal 3D centre when spread is zero; they may overlap or hide one another',
                    )
                if (
                    asset
                    and distance is not None
                    and bearing is not None
                    and altitude is not None
                    and fov is not None
                    and width is not None
                    and height is not None
                    and down_pitch is not None
                ):
                    # Approximate centre, fixed nominal bridge eye height, no wave/roll tilt.
                    # This is a composition warning only: catalogue pivots/bounds may differ.
                    yaw = math.radians(bearing)
                    pitch = math.radians(down_pitch)
                    horizontal_x = distance * math.sin(yaw)
                    forward_z = distance * math.cos(yaw)
                    vertical_y = altitude + asset['heightM'] / 2 - 12.4
                    camera_y = vertical_y * math.cos(pitch) + forward_z * math.sin(pitch)
                    camera_z = forward_z * math.cos(pitch) - vertical_y * math.sin(pitch)
                    half_vertical = math.tan(math.radians(fov) / 2)
                    if camera_z <= 0:
                        check.warn(
                            row_path + '.bearingDeg',
                            'Approximate nominal object centre is behind the camera; planned counts do not guarantee visible objects',
                        )
                    else:
                        if abs(horizontal_x / camera_z) > half_vertical * width / height:
                            check.warn(
                                row_path + '.bearingDeg',
                                'Approximate nominal object centre is outside horizontal camera FOV; spread, model bounds and wave motion can change visibility',
                            )
                        if abs(camera_y / camera_z) > half_vertical:
                            check.warn(
                                row_path + '.altitudeM',
                                'Approximate nominal object centre is outside vertical camera FOV at the 12.4 m bridge viewpoint; planned counts are not verified visible counts',
                            )
                if asset:
                    category = asset['category']
                    categories[category] = categories.get(category, 0) + (count or 0)
                    object_images[asset['model']] = object_images.get(asset['model'], 0) + (
                        count or 0
                    ) * (images or 0)
                    category_images[category] = category_images.get(category, 0) + (count or 0) * (
                        images or 0
                    )
                    wind = environment.get('windMps')
                    if (
                        asset.get('maxWindMps') is not None
                        and isinstance(wind, (int, float))
                        and wind > asset['maxWindMps']
                    ):
                        check.warn(
                            path + '.environment.windMps',
                            'Wind exceeds the catalogue assumption for ' + asset['model'],
                        )
            if instances > MAX_ACTORS:
                check.error(path + '.objects', 'A block supports at most 40 actor instances')
            for category, count in categories.items():
                if count > MAX_CATEGORY_ACTORS:
                    check.error(
                        path + '.objects',
                        'Category %s supports at most 12 actor instances per block' % category,
                    )
            block_summaries.append(
                {
                    'id': block_id,
                    'images': images or 0,
                    'actorsPerImage': instances,
                    'objectRows': len(objects),
                    'categories': categories,
                }
            )
        if total is not None and allocated != total:
            check.error(
                '$.totalImages',
                'Block allocation is %d; it must equal totalImages (%d)' % (allocated, total),
            )
        summary = {
            'totalImages': total or 0,
            'allocatedImages': allocated,
            'blocks': len(blocks),
            'objectImageCounts': object_images,
            'categoryImageCounts': category_images,
            'blockSummaries': block_summaries,
            'imageSemantics': 'independent_seeded_samples',
            'sensor': 'rgb',
            'countSemantics': 'planned_actor_image_instances_not_verified_visible_objects',
        }
        check.warn(
            '$',
            'Catalogue limits are scenario assumptions; weather and pixel-height targets are uncalibrated visual proxies',
        )
        return {
            'valid': not check.errors,
            'campaign': normalized if not check.errors else None,
            'errors': check.errors,
            'warnings': check.warnings,
            'summary': summary,
        }

    def save(self, payload):
        validation = self.validate(payload)
        if not validation['valid']:
            raise CampaignValidationError(validation)
        identifier = str(uuid.uuid4())
        result = dict(validation, id=identifier, savedAt=_now())
        with self._directory(('saved',), create=True) as descriptor:
            self._write_file(descriptor, identifier + '.json', _json_bytes(result))
        return result

    def get(self, identifier):
        identifier = _opaque_id(identifier)
        with self._directory(('saved',)) as descriptor:
            data = self._read_file(descriptor, identifier + '.json')
        result = load_json_bytes(data)
        if (
            not isinstance(result, dict)
            or result.get('id') != identifier
            or not isinstance(result.get('campaign'), dict)
        ):
            raise ValueError('Invalid saved campaign')
        return result

    def list(self):
        try:
            with self._directory(('saved',)) as descriptor:
                names = sorted(
                    name
                    for name in os.listdir(descriptor)
                    if name.endswith('.json') and _UUID.fullmatch(name[:-5])
                )
                results = []
                for name in names[:500]:
                    try:
                        saved = load_json_bytes(self._read_file(descriptor, name))
                        campaign = saved['campaign']
                        if saved['id'] != name[:-5]:
                            continue
                        results.append(
                            {
                                'id': saved['id'],
                                'name': campaign['name'],
                                'engine': campaign['engine'],
                                'scene': campaign['scene'],
                                'totalImages': campaign['totalImages'],
                                'blocks': len(campaign['blocks']),
                                'savedAt': saved['savedAt'],
                            }
                        )
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
                return sorted(results, key=lambda row: row['savedAt'], reverse=True)
        except FileNotFoundError:
            return []

    def prepare(self, payload):
        identifier = str(uuid.uuid4())
        try:
            with PreparationStatus(self.core_root, identifier, payload) as status:
                status.step('planner')
                return self._prepare(payload, identifier, status)
        except ScenePreparationStorageError as error:
            raise CampaignSecurityError(str(error)) from error

    def _prepare(self, payload, identifier, status):
        validation = self.validate(payload)
        if not validation['valid']:
            raise CampaignValidationError(validation)
        campaign = validation['campaign']
        engine = next(item for item in self._engines() if item['id'] == campaign['engine'])
        if not engine['preparationAvailable']:
            validation = dict(
                validation,
                valid=False,
                campaign=None,
                errors=[
                    {
                        'path': '$.engine',
                        'message': 'Preparation requires an installed '
                        + campaign['engine']
                        + ' adapter',
                    }
                ],
            )
            raise CampaignValidationError(validation)
        campaign_data = _json_bytes(campaign)
        campaign_sha = hashlib.sha256(campaign_data).hexdigest()
        catalogue = self._catalogue(campaign['engine'])
        engine_profile = self.engine_registry.get(campaign['engine'])
        status.step('scene_script_builder')
        try:
            prepared = prepare_engine(
                campaign, identifier, campaign_sha, self.core_root, self.unity_root, catalogue
            )
        except (ValueError, OSError, ImportError) as error:
            message = (
                'Required local engine template or model resource is missing or inaccessible'
                if isinstance(error, OSError)
                else str(error)[:300]
            )
            invalid = dict(
                validation,
                valid=False,
                campaign=None,
                errors=[{'path': '$.engine', 'message': 'Scene preparation refused: ' + message}],
            )
            raise CampaignValidationError(invalid) from error
        metadata = prepared['manifest']
        status.step('validator')
        files = dict(prepared['files'], **{'campaign.json': campaign_data})
        artifacts = [
            {'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            for name, data in sorted(files.items())
        ]
        manifest = {
            'schema': MANIFEST_SCHEMA,
            'id': identifier,
            'name': campaign['name'],
            'createdAt': _now(),
            'engine': campaign['engine'],
            'scene': campaign['scene'],
            'totalImages': campaign['totalImages'],
            'relativeCampaignFile': 'campaign.json',
            'campaignSha256': campaign_sha,
            'summary': validation['summary'],
            'warnings': validation['warnings'],
            'artifacts': artifacts,
            'engineAgentFile': 'engine-agent.json',
            'enginePreparation': metadata,
            'provenance': {
                'settingsSchema': SCHEMA,
                'catalogueSchema': catalogue.get('schema'),
                'scenePath': engine_profile['scenePath'],
                'adapterPath': engine_profile['adapterPath'],
                'renderEngine': campaign['engine'],
                'nativeValidated': False,
                'imageSemantics': 'independent_seeded_samples',
                'distanceReference': 'bridge_camera_horizontal_range_m',
                'pixelHeightFormula': 'catalogueHeightM * imageHeightPx / (2 * tan(verticalFovRadians/2) * distanceM)',
                'modelScaling': 'catalogue_native_scale_only',
                'limitations': list(LIMITATIONS),
            },
        }
        used_models = {row['model'] for block in campaign['blocks'] for row in block['objects']}
        manifest['importedAssetRevisions'] = [
            {
                key: item[key]
                for key in (
                    'model',
                    'revisionSha256',
                    'requestSha256',
                    'prefabGuid',
                    'prefabSha256',
                )
            }
            for item in catalogue['assets']
            if item['model'] in used_models
            and item.get('importId')
            and engine_profile['adapterId'] == 'unity'
        ]
        manifest['neutralSourceRevisions'] = [
            {
                key: item[key]
                for key in ('model', 'revisionSha256', 'requestSha256', 'geometrySha256')
            }
            for item in catalogue['assets']
            if item['model'] in used_models
            and item.get('importId')
            and engine_profile['adapterId'] != 'unity'
        ]
        with self._directory(('prepared',), create=True) as parent:
            os.mkdir(identifier, 0o700, dir_fd=parent)
            descriptor = os.open(
                identifier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            try:
                for name, data in sorted(files.items()):
                    self._write_file(descriptor, name, data)
                self._write_file(descriptor, 'manifest.json', _json_bytes(manifest))
            finally:
                os.close(descriptor)
        labels = {
            'campaign.json': 'Configuration',
            'engine-agent.json': 'Agent preparation trace',
            'scene-plan.json': 'Scene plan',
            'scene_unity.cs': 'Unity Editor scene script',
            'unity-instructions.txt': 'Unity instructions',
            'scene_unreal.py': 'Unreal Editor scene script',
            'LOTUSimPrepared.uproject': 'Unreal project descriptor',
            'unreal-instructions.txt': 'Unreal instructions',
            'scene-contract.json': 'Neutral SI/ENU scene contract',
            'adapter-requirements.json': 'Native adapter requirements',
            'engine-instructions.txt': 'Engine profile instructions',
        }
        actions = {
            'engine': campaign['engine'],
            'preparationState': 'prepared',
            'runtimeDetected': engine['runtimeDetected'],
            'nativeValidated': False,
            'instructions': metadata['instructions'],
            'scenePath': metadata['scenePath'],
            'mode': engine_profile['mode'],
            'capabilities': engine_profile['capabilities'],
            'files': [
                {'name': row['name'], 'label': labels[row['name']], 'sha256': row['sha256']}
                for row in artifacts
            ],
        }
        self.read_bundle(identifier)
        status.complete()
        return dict(
            validation,
            id=identifier,
            manifest=manifest,
            engineActions=actions,
            engineAgent=prepared['report'],
        )

    def _prepared_inventory(self, descriptor, identifier):
        data = self._read_file(descriptor, 'manifest.json')
        manifest = load_json_bytes(data)
        if (
            not isinstance(manifest, dict)
            or manifest.get('schema') != MANIFEST_SCHEMA
            or manifest.get('id') != identifier
        ):
            raise ValueError('Invalid prepared campaign manifest')
        rows = manifest.get('artifacts')
        # Older immutable Unity packages contained the two original files.
        if rows is None:
            rows = [
                {'name': 'campaign.json', 'sha256': manifest.get('campaignSha256'), 'bytes': None}
            ]
        if not isinstance(rows, list) or not 1 <= len(rows) < len(PREPARED_FILES):
            raise ValueError('Invalid prepared artifact inventory')
        inventory = {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'name', 'sha256', 'bytes'}:
                raise ValueError('Invalid prepared artifact metadata')
            name, digest, size = row['name'], row['sha256'], row['bytes']
            if (
                not isinstance(name, str)
                or name not in PREPARED_FILES - {'manifest.json'}
                or name in inventory
                or not isinstance(digest, str)
                or not re.fullmatch(r'[0-9a-f]{64}', digest)
                or size is not None
                and (type(size) is not int or not 0 <= size <= MAX_JSON_BYTES)
            ):
                raise ValueError('Invalid prepared artifact metadata')
            inventory[name] = row
        if 'campaign.json' not in inventory or inventory['campaign.json']['sha256'] != manifest.get(
            'campaignSha256'
        ):
            raise ValueError('Prepared campaign hash is not pinned')
        if manifest.get('artifacts') is not None:
            descriptor = self.engine_registry.get(manifest.get('engine'))
            if set(inventory) not in (
                expected_artifacts(descriptor),
                expected_artifacts(descriptor, legacy=True),
            ):
                raise ValueError(
                    'Prepared artifact inventory does not match the registered adapter'
                )
        return data, inventory

    def _read_artifact(self, descriptor, filename, row):
        data = self._read_file(descriptor, filename)
        if (row['bytes'] is not None and len(data) != row['bytes']) or hashlib.sha256(
            data
        ).hexdigest() != row['sha256']:
            raise ValueError('Prepared artifact integrity check failed')
        return data

    def read_prepared(self, identifier, filename):
        identifier = _opaque_id(identifier)
        if filename not in PREPARED_FILES:
            raise CampaignSecurityError('Only fixed prepared campaign artifacts can be downloaded')
        with self._directory(('prepared', identifier)) as descriptor:
            manifest_data, inventory = self._prepared_inventory(descriptor, identifier)
            if filename == 'manifest.json':
                return manifest_data
            if filename not in inventory:
                raise CampaignSecurityError('Artifact is not part of this prepared package')
            return self._read_artifact(descriptor, filename, inventory[filename])

    def read_bundle(self, identifier):
        """Return verified flat files for the HTTP layer to ZIP, without writes."""
        identifier = _opaque_id(identifier)
        with self._directory(('prepared', identifier)) as descriptor:
            manifest_data, inventory = self._prepared_inventory(descriptor, identifier)
            files = {'manifest.json': manifest_data}
            for filename, row in inventory.items():
                files[filename] = self._read_artifact(descriptor, filename, row)
            return files

    def prepared_file(self, identifier, filename):
        """Compatibility path accessor; prefer read_prepared for race-safe reads."""
        self.read_prepared(identifier, filename)
        return (
            self.core_root / 'artifacts' / 'campaign-settings' / 'prepared' / identifier / filename
        )
