"""Local declarative engine profiles, never executable plugin registration.

Only repository-owned adapters can be dispatched. Custom names create neutral
export profiles, not Python modules, paths, shell commands or native adapters.
"""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid

SCHEMA = 'lotusim-engine-catalog-1'
PROFILE_SCHEMA = 'lotusim-engine-profile-1'
MAX_PROFILE = 32768
MAX_CUSTOM = 32
UNITY_ADAPTER = 'Assets/Editor/DatasetManualCampaignBuilder.cs'
UNITY_SCENE = 'Assets/Scenes/Dataset/ManualCampaign_<id>.unity'
UNREAL_SCENE = '/Game/LOTUSim/Campaigns/<id>/Scene'
CUSTOM_ID = re.compile(r'^custom-[0-9a-f]{16}$')
COMMON_FILES = frozenset(('campaign.json', 'engine-agent.json', 'scene-contract.json'))
ADAPTER_FILES = {
    'unity': frozenset(('scene_unity.cs', 'scene-plan.json', 'unity-instructions.txt')),
    'unreal': frozenset(
        (
            'scene_unreal.py',
            'scene-plan.json',
            'LOTUSimPrepared.uproject',
            'unreal-instructions.txt',
        )
    ),
    'neutral': frozenset(('adapter-requirements.json', 'engine-instructions.txt')),
}
PREPARED_FILES = (
    frozenset(('manifest.json',)) | COMMON_FILES | frozenset().union(*ADAPTER_FILES.values())
)
_BUILTINS = (
    ('unity', 'Unity', 'unity'),
    ('unreal', 'Unreal Engine', 'unreal'),
    ('godot', 'Godot', 'neutral'),
    ('blender', 'Blender', 'neutral'),
    ('o3de', 'O3DE', 'neutral'),
)


class EngineRegistryError(ValueError):
    pass


def custom_name(value):
    if not isinstance(value, str):
        raise EngineRegistryError('Custom engine name must be text')
    if any(unicodedata.category(character).startswith('C') for character in value):
        raise EngineRegistryError('Custom engine names must not contain control characters')
    name = ' '.join(unicodedata.normalize('NFKC', value).split())
    if (
        not 1 <= len(name) <= 64
        or not any(character.isalnum() for character in name)
        or any(not (character.isalnum() or character in ' ._-') for character in name)
    ):
        raise EngineRegistryError(
            'Use 1–64 letters, digits, spaces, dots, underscores or hyphens for the engine name'
        )
    return name


def custom_id(name):
    return 'custom-' + hashlib.sha256(custom_name(name).casefold().encode('utf-8')).hexdigest()[:16]


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EngineRegistryError('Duplicate engine profile field')
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode('utf-8'),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(
                EngineRegistryError('Invalid profile number')
            ),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise EngineRegistryError('Invalid engine profile JSON') from error


def _regular(path):
    try:
        return path.is_file()
    except OSError:
        return False


def _runtime_candidates(engine, unity_root):
    if engine == 'unity':
        paths = [
            Path('/Applications/Unity/Unity.app/Contents/MacOS/Unity'),
            Path('/opt/unity/Editor/Unity'),
        ]
        if unity_root is not None:
            try:
                with (unity_root / 'ProjectSettings/ProjectVersion.txt').open(
                    encoding='utf-8'
                ) as stream:
                    match = re.search(
                        r'^m_EditorVersion: ([0-9A-Za-z.]+)$', stream.read(4096), re.M
                    )
                if match:
                    paths += [
                        Path('/Applications/Unity/Hub/Editor')
                        / match.group(1)
                        / 'Unity.app/Contents/MacOS/Unity',
                        Path('C:/Program Files/Unity/Hub/Editor')
                        / match.group(1)
                        / 'Editor/Unity.exe',
                    ]
            except (OSError, UnicodeError):
                pass
        return paths
    if engine != 'unreal':
        return []
    paths = [Path('/opt/unreal-engine/Engine/Binaries/Linux/UnrealEditor')]
    for base in (
        Path('/Users/Shared/Epic Games'),
        Path('/Applications/Epic Games'),
        Path('C:/Program Files/Epic Games'),
        Path('/opt/unreal-engine'),
    ):
        try:
            with os.scandir(base) as entries:
                for index, entry in enumerate(entries):
                    if index >= 128:
                        break
                    if not re.fullmatch(r'UE_[0-9][0-9A-Za-z_.-]{0,48}', entry.name):
                        continue
                    child = Path(entry.path)
                    paths += [
                        child / 'Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor',
                        child / 'Engine/Binaries/Win64/UnrealEditor.exe',
                        child / 'Engine/Binaries/Linux/UnrealEditor',
                    ]
        except OSError:
            pass
    return paths


def expected_artifacts(descriptor, *, legacy=False):
    names = COMMON_FILES | ADAPTER_FILES[descriptor['adapterId']]
    return (
        names - {'scene-contract.json'}
        if legacy and descriptor['adapterId'] != 'neutral'
        else names
    )


class EngineRegistry:
    def __init__(self, core_root, unity_root=None):
        self.core_root = Path(core_root).resolve()
        self.unity_root = Path(unity_root).resolve() if unity_root is not None else None

    @contextmanager
    def _directory(self, create=False):
        descriptor = None
        try:
            descriptor = os.open(str(self.core_root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for component in ('artifacts', 'render-engines'):
                if create:
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                child = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            yield descriptor
        except OSError as error:
            if error.errno in (20, 40, 62):
                raise EngineRegistryError(
                    'Engine profile storage must not contain symlinks'
                ) from error
            raise
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _load_at(self, descriptor):
        try:
            fd = os.open(
                'profile.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
        except FileNotFoundError:
            return {'schema': PROFILE_SCHEMA, 'selectedEngine': 'unity', 'customEngines': []}
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_PROFILE:
                raise EngineRegistryError('Invalid engine profile file')
            raw = stream.read(MAX_PROFILE + 1)
            if len(raw) > MAX_PROFILE:
                raise EngineRegistryError('Engine profile exceeds budget')
        source = _decode(raw)
        if (
            not isinstance(source, dict)
            or set(source) != {'schema', 'selectedEngine', 'customEngines'}
            or source.get('schema') != PROFILE_SCHEMA
            or not isinstance(source['customEngines'], list)
            or len(source['customEngines']) > MAX_CUSTOM
        ):
            raise EngineRegistryError('Invalid declarative engine profile')
        identifiers = {item[0] for item in _BUILTINS}
        for item in source['customEngines']:
            if (
                not isinstance(item, dict)
                or set(item) != {'id', 'name'}
                or item['name'] != custom_name(item['name'])
                or item['id'] != custom_id(item['name'])
                or item['id'] in identifiers
            ):
                raise EngineRegistryError('Invalid custom engine profile')
            identifiers.add(item['id'])
        if (
            not isinstance(source['selectedEngine'], str)
            or source['selectedEngine'] not in identifiers
        ):
            raise EngineRegistryError('Selected engine is not registered')
        return source

    def _profile(self):
        try:
            with self._directory() as descriptor:
                return self._load_at(descriptor)
        except FileNotFoundError:
            return {'schema': PROFILE_SCHEMA, 'selectedEngine': 'unity', 'customEngines': []}

    def _descriptor(self, identifier, label, adapter):
        if adapter == 'unity':
            available = False
            if self.unity_root is not None:
                path = self.unity_root / UNITY_ADAPTER
                try:
                    path.resolve().relative_to(self.unity_root)
                    available = _regular(path)
                except (OSError, ValueError):
                    pass
            mode = 'native_adapter_installed' if available else 'native_adapter_unavailable'
            detail = 'Adaptateur Unity existant. La préparation des fichiers ne valide ni ne déclenche leur exécution dans le moteur.'
            scene_path, adapter_path = UNITY_SCENE, UNITY_ADAPTER
        elif adapter == 'unreal':
            available = all(
                _regular(Path(__file__).parent / name)
                for name in ('unreal.py', 'templates/unreal_scene.py')
            )
            mode, detail = (
                'prototype',
                'Prototype de préparation Unreal : aperçu RGB statique sur mer plane, sans ROS, houle ni annotations. Exécution native à valider dans Unreal Editor.',
            )
            scene_path, adapter_path = UNREAL_SCENE, 'tools/unreal_scene_adapter.py'
        else:
            available = _regular(Path(__file__).with_name('contract.py'))
            mode, detail = (
                'neutral_contract_only',
                'Contrat de scène neutre uniquement. Aucun adaptateur natif de rendu, d’annotation ou de connexion n’est implémenté pour ce profil.',
            )
            scene_path, adapter_path = 'scene-contract.json', 'tools/neutral_scene_adapter.py'
        native = adapter == 'unity' and available
        return {
            'id': identifier,
            'label': label,
            'adapterId': adapter,
            'mode': mode,
            'available': available,
            'preparationAvailable': available,
            'runtimeDetected': any(
                _regular(path) for path in _runtime_candidates(identifier, self.unity_root)
            ),
            'nativeValidated': False,
            'validationState': 'not_native_validated',
            'detail': detail,
            'scenePath': scene_path,
            'adapterPath': adapter_path,
            'capabilities': {
                'scenePreparation': available,
                'neutralExport': True,
                'rgbCapture': native,
                'annotations': native,
                'livePoses': native,
                'waves': native,
            },
            'capabilitySemantics': 'Declared adapter implementation, not a native validation or runtime health assertion',
        }

    def _entries(self, profile):
        return [self._descriptor(*entry) for entry in _BUILTINS] + [
            self._descriptor(item['id'], item['name'], 'neutral')
            for item in profile['customEngines']
        ]

    def catalog(self):
        profile = self._profile()
        entries = self._entries(profile)
        return {
            'schema': SCHEMA,
            'selectedEngine': next(
                item for item in entries if item['id'] == profile['selectedEngine']
            ),
            'engines': entries,
        }

    def get(self, identifier):
        if not isinstance(identifier, str):
            raise EngineRegistryError('Expected a registered engine identifier')
        profile = self._profile()
        for entry in _BUILTINS:
            if entry[0] == identifier:
                return self._descriptor(*entry)
        for entry in profile['customEngines']:
            if entry['id'] == identifier:
                return self._descriptor(entry['id'], entry['name'], 'neutral')
        raise EngineRegistryError(
            'Unknown engine; register a custom name through engine selection first'
        )

    def selection(self):
        return self.catalog()['selectedEngine']

    def select(self, payload):
        if (
            not isinstance(payload, dict)
            or 'engine' not in payload
            or not isinstance(payload['engine'], str)
        ):
            raise EngineRegistryError('Expected an engine selection object')
        target = payload['engine']
        if target == 'custom':
            if set(payload) != {'engine', 'name'}:
                raise EngineRegistryError('Custom selection requires only engine and name')
            name = custom_name(payload['name'])
            target = custom_id(name)
        elif set(payload) != {'engine'}:
            raise EngineRegistryError('Selection requires only engine')
        with self._directory(create=True) as descriptor:
            fd = os.open(
                'profile.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor
            )
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise EngineRegistryError('Expected a regular engine profile lock')
                fcntl.flock(fd, fcntl.LOCK_EX)
                profile = self._load_at(descriptor)
                known = {item[0] for item in _BUILTINS} | {
                    item['id'] for item in profile['customEngines']
                }
                if payload['engine'] == 'custom' and target not in known:
                    if len(profile['customEngines']) >= MAX_CUSTOM:
                        raise EngineRegistryError('At most 32 custom engine profiles are supported')
                    profile['customEngines'].append({'id': target, 'name': name})
                elif target not in known:
                    raise EngineRegistryError('Unknown registered engine identifier')
                profile['selectedEngine'] = target
                raw = (
                    json.dumps(profile, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n'
                ).encode('utf-8')
                temporary = '.profile-' + uuid.uuid4().hex + '.tmp'
                output = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
                try:
                    with os.fdopen(output, 'wb') as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(
                        temporary, 'profile.json', src_dir_fd=descriptor, dst_dir_fd=descriptor
                    )
                    os.fsync(descriptor)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=descriptor)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(fd)
        return self.catalog()
