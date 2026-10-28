"""Engine-neutral renderer heartbeat adapters; no engine/ROS SDK or execution.

Publisher contract (all paths are engine-scoped, never arbitrary host paths)::

    {
      "schema": "lotusim-renderer-state-1", "engineId": "godot",
      "updatedAt": "2026-10-28T12:00:00Z", "runtimeState": "ready",
      "isPlaying": true, "isPaused": false, "isCompiling": false,
      "sceneName": "Maritime", "scenePath": "res://maritime.tscn",
      "ros": {"activeInstanceCount": 1, "connectionState": "reply_observed"},
      "capture": {"status": "capturing", "captured": 3, "expected": 10,
                  "outputDirectory": "captures/run_01"},
      "preview": {"file": "operations/preview.jpg", "updatedAt": "...",
                  "width": 1280, "height": 720, "live": true,
                  "source": "renderer_rgb"},
      "lotusim": {"hasFrame": true, "snapshotUpdatedAt": "...", "frame": 3,
                  "objects": [{"id":"boat", "model":"sailboat",
                               "eastM":0, "northM":100, "altitudeM":0}]}
    }

Heartbeat: CORE/artifacts/operations/renderer.json. Artifact paths are relative
to CORE/artifacts/renderers/<actual engineId>/; a legacy preview filename
"preview.jpg" means operations/preview.jpg beneath that same engine root.
Absolute capture directories are accepted only beneath that root. A profile
selection never establishes source identity, freshness, native validation or
image provenance. Write RGB separately, then publish its timestamp/path.

``publish_renderer_state`` is an optional standard-library writer, not an
automatic engine bridge. It performs no engine launch, native render or ROS
connection. The old Unity heartbeat is translated only by UnityTelemetryAdapter.
"""

import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

SCHEMA = 'lotusim-renderer-state-1'
MAX_JSON = 2 * 1024 * 1024
_ENGINE_ID = re.compile(r'^[a-z][a-z0-9-]{0,63}$')


def epoch(value):
    if not isinstance(value, str):
        return None
    try:
        value = re.sub(
            r'([T ]\d{2}:\d{2}:\d{2})\.(\d+)',
            lambda match: match.group(1) + '.' + match.group(2)[:6].ljust(6, '0'),
            value,
        )
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def iso(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def text(value, limit=180):
    return ' '.join(value.split())[:limit] if isinstance(value, str) else ''


def number(value, default=None):
    try:
        return (
            value
            if not isinstance(value, bool)
            and isinstance(value, (int, float))
            and math.isfinite(value)
            else default
        )
    except OverflowError:
        return default


def safe_child(authority, relative, *, directory=False):
    """Resolve only non-symlink descendants of an explicit trusted authority."""
    authority = Path(authority)
    if not isinstance(relative, (str, Path)):
        return None
    value = str(relative)
    if not value or len(value) > 4096 or '\\' in value or '\0' in value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(authority)
        except ValueError:
            # macOS /var -> /private/var is a trusted-root alias, not an
            # artifact-subdirectory link. Preserve/check every component below
            # the authority rather than blindly resolving the entire request.
            relative = None
            for parent in list(candidate.parents)[:64]:
                try:
                    if parent.resolve() == authority.resolve():
                        relative = candidate.relative_to(parent)
                        break
                except OSError:
                    continue
            if relative is None:
                return None
            candidate = relative
    if not candidate.parts or any(
        part in ('.', '..') or part.startswith('.') for part in candidate.parts
    ):
        return None
    try:
        current = authority
        if current.is_symlink():
            return None
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                return None
        current.resolve(strict=True).relative_to(authority.resolve(strict=True))
        return current if (current.is_dir() if directory else current.is_file()) else None
    except (OSError, ValueError):
        return None


def read_json(authority, relative):
    """Bounded no-follow descriptor read; reject duplicate and non-finite JSON."""
    parts = str(relative).split('/')
    if any(not p or p in ('.', '..') or p.startswith('.') or '\\' in p or '\0' in p for p in parts):
        return None
    descriptor = None
    try:
        descriptor = os.open(str(authority), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        with os.fdopen(file_descriptor, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
                return None
            data = handle.read(MAX_JSON + 1)
        if len(data) > MAX_JSON:
            return None

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('Duplicate JSON field')
                result[key] = value
            return result

        def constant(value):
            raise ValueError('Non-finite JSON number')

        result = json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
        json.dumps(result, allow_nan=False)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, UnicodeError, RecursionError, OverflowError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def unknown(detail='Aucun signal du moteur graphique reçu'):
    return {
        'engineId': None,
        'label': None,
        'source': 'none',
        'type': 'unavailable',
        'state': 'unknown',
        'fresh': False,
        'detail': detail,
        'updatedAt': None,
        'ageSeconds': None,
        'isPlaying': None,
        'isPaused': None,
        'isCompiling': None,
        'sceneName': None,
        'nativeValidated': False,
    }


def normalize(raw, now, engine_id, label, source, kind):
    observed = epoch(raw.get('updatedAt'))
    if observed is None:
        result = unknown('Signal %s sans horodatage valide' % label)
        result.update(engineId=engine_id, label=label, source=source, type=kind)
        return result, {}
    age = max(0.0, now - observed)
    fresh = age <= 8 and observed <= now + 5

    def flag(key):
        value = raw.get(key)
        return value if isinstance(value, bool) else False if kind == 'unity_legacy' else None

    playing, paused, compiling = flag('isPlaying'), flag('isPaused'), flag('isCompiling')
    state = (
        'stale'
        if not fresh
        else (
            'paused'
            if paused is True
            else 'running' if playing is True else 'idle' if playing is False else 'unknown'
        )
    )
    runtime_state = raw.get('runtimeState', raw.get('editorState'))
    if runtime_state in ('quitting', 'stopped'):
        state, fresh = 'stopped', False
    elif runtime_state in ('reloading', 'compiling') and fresh:
        state = 'ready'
    result = {
        'engineId': engine_id,
        'label': label,
        'source': source,
        'type': kind,
        'state': state,
        'fresh': fresh,
        'updatedAt': iso(observed),
        'ageSeconds': round(age, 2),
        'sceneName': text(raw.get('sceneName'), 100),
        'scenePath': text(raw.get('scenePath'), 200),
        'isPlaying': playing,
        'isPaused': paused,
        'isCompiling': compiling,
        'nativeValidated': False,
        'detail': (
            'Rendu en pause'
            if state == 'paused'
            else (
                'Moteur en exécution'
                if state == 'running'
                else (
                    'Signal reçu ; exécution non mesurée'
                    if state == 'unknown'
                    else 'Moteur prêt' if fresh else 'Télémétrie %s ancienne' % label
                )
            )
        ),
    }
    # Virtual scene identifiers are useful; absolute host paths are not public
    # telemetry and must not leak through a producer's incidental file choice.
    scene_path = result['scenePath']
    if (scene_path.startswith('/') and not scene_path.startswith('/Game/')) or re.match(
        r'^[A-Za-z]:[\\/]', scene_path
    ):
        result['scenePath'] = '[chemin local]'
    ros = raw.get('ros') if isinstance(raw.get('ros'), dict) else {}
    result['ros'] = {
        key: number(ros.get(key))
        for key in (
            'instanceCount',
            'activeInstanceCount',
            'threadCount',
            'connectedCount',
            'lastMessageAgeSeconds',
        )
    }
    result['ros'].update(
        connectionState=text(ros.get('connectionState'), 80),
        hasConnectionError=ros.get('hasConnectionError') is True,
    )
    return result, raw


class UnityTelemetryAdapter:
    """The legacy Unity schema remains Unity-specific, regardless of selection."""

    def __init__(self, unity_root):
        self.root = Path(unity_root)

    def observe(self, now):
        raw = read_json(self.root, 'artifacts/operations/unity.json')
        if not isinstance(raw, dict) or raw.get('schema') != 'lotusim-ops-unity-1':
            return unknown('Aucun signal de l’éditeur Unity reçu'), {}
        return normalize(raw, now, 'unity', 'Unity', 'legacy_unity_adapter', 'unity_legacy')


class RendererTelemetryAdapter:
    def __init__(self, core_root, profiles):
        self.root = Path(core_root)
        self.profiles = {
            item['id']: item
            for item in profiles
            if isinstance(item, dict)
            and isinstance(item.get('id'), str)
            and _ENGINE_ID.fullmatch(item['id'])
        }

    def observe(self, now):
        raw = read_json(self.root, 'artifacts/operations/renderer.json')
        if not isinstance(raw, dict) or raw.get('schema') != SCHEMA:
            return unknown(), {}
        engine_id = raw.get('engineId')
        if not isinstance(engine_id, str) or engine_id not in self.profiles:
            return unknown('Signal du moteur rejeté : identifiant non enregistré'), {}
        if raw.get('engine') is not None and raw.get('engine') != engine_id:
            return unknown('Signal du moteur rejeté : identifiants source incohérents'), {}
        label = text(self.profiles[engine_id].get('label') or engine_id, 100)
        return normalize(raw, now, engine_id, label, 'renderer_heartbeat', 'neutral')


def choose_renderer(neutral, legacy):
    """Prefer fresh evidence, then its timestamp; selection is never consulted."""
    candidates = [item for item in (neutral, legacy) if item[0].get('updatedAt') is not None]
    return (
        max(
            candidates,
            key=lambda item: (
                bool(item[0].get('fresh')),
                epoch(item[0]['updatedAt']) or 0,
                item[0].get('type') == 'neutral',
            ),
        )
        if candidates
        else neutral
    )


def publish_renderer_state(core_root, engine_id, payload, *, unity_root=None, registry=None):
    """Atomically publish an explicit registered source; never selects an engine.

    ``payload`` follows the contract above, omitting schema/engineId if desired.
    ``updatedAt`` is required so cached data cannot silently become a heartbeat.
    Preview/capture paths are validated against the registered engine subtree;
    this helper never reads RGB bytes, copies media or launches an engine.
    """
    if registry is None:
        from engine_registry import EngineRegistry

        registry = EngineRegistry(core_root, unity_root)
    descriptor = registry.get(engine_id)
    if (
        not isinstance(engine_id, str)
        or not _ENGINE_ID.fullmatch(engine_id)
        or descriptor.get('id') != engine_id
    ):
        raise ValueError('Expected a registered renderer engine id')
    if not isinstance(payload, dict) or epoch(payload.get('updatedAt')) is None:
        raise ValueError('A renderer timestamp with a timezone is required')
    if (
        payload.get('engineId', engine_id) != engine_id
        or payload.get('engine', engine_id) != engine_id
    ):
        raise ValueError('Renderer source does not match the explicit engine id')
    result = dict(payload, schema=SCHEMA, engineId=engine_id)
    data = (
        json.dumps(result, allow_nan=False, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    ).encode('utf-8')
    if len(data) > MAX_JSON:
        raise ValueError('Renderer heartbeat exceeds 2 MiB')
    core = Path(core_root).resolve()
    for key, field in (('capture', 'outputDirectory'), ('preview', 'file')):
        part = payload.get(key)
        if part is not None and not isinstance(part, dict):
            raise ValueError(key + ' must be an object')
        value = part.get(field) if isinstance(part, dict) else None
        if value is not None:
            relative = str(value)
            authority = core / 'artifacts/renderers' / engine_id
            if Path(relative).is_absolute():
                try:
                    relative = str(Path(relative).relative_to(authority))
                except ValueError as error:
                    raise ValueError('Renderer artifact path escapes its engine root') from error
            if (
                not relative
                or len(relative) > 4096
                or '\\' in relative
                or '\0' in relative
                or any(
                    piece in ('', '.', '..') or piece.startswith('.')
                    for piece in relative.split('/')
                )
            ):
                raise ValueError('Unsafe renderer artifact path')
    descriptor_fd = os.open(str(core), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = 'renderer-' + uuid.uuid4().hex + '.tmp'
    try:
        for component in ('artifacts', 'operations'):
            try:
                os.mkdir(component, 0o700, dir_fd=descriptor_fd)
            except FileExistsError:
                pass
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor_fd
            )
            os.close(descriptor_fd)
            descriptor_fd = child
        try:
            existing = os.stat('renderer.json', dir_fd=descriptor_fd, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError(
                    'Renderer heartbeat must not replace a symlink or non-regular file'
                )
        except FileNotFoundError:
            pass
        file_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor_fd,
        )
        with os.fdopen(file_fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, 'renderer.json', src_dir_fd=descriptor_fd, dst_dir_fd=descriptor_fd)
        os.fsync(descriptor_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor_fd)
        except FileNotFoundError:
            pass
        os.close(descriptor_fd)
    return {
        'engineId': engine_id,
        'schema': SCHEMA,
        'updatedAt': result['updatedAt'],
        'relativeHeartbeatFile': 'artifacts/operations/renderer.json',
    }
