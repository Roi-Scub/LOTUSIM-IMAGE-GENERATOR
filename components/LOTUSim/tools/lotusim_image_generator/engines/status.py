"""Owned preparation lifecycle telemetry and bounded, hash-checked backfill.

This records offline package preparation only. It neither starts an engine nor
interprets a saved package or a recently created directory as a running agent.
"""

from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from lotusim_image_generator.engines.registry import (
    EngineRegistry,
    EngineRegistryError,
    PREPARED_FILES,
    expected_artifacts,
)

SCHEMA = 'lotusim-scene-preparation-status-1'
STATUS_FILE = 'scene-preparation.json'
ROLES = (
    ('planner', 'Planification'),
    ('scene_script_builder', 'Création du script de scène'),
    ('validator', 'Validation du paquet'),
)
MAX_STATUS = 65536
MAX_ARTIFACT = 1048576
MAX_HISTORY = 128
ACTIVE_SECONDS = 300
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
_PROCESS_TOKEN = uuid.uuid4().hex


def _registered(core, identifier):
    try:
        return EngineRegistry(core).get(identifier)
    except (OSError, ValueError):
        return None


class ScenePreparationStorageError(ValueError):
    pass


def _iso(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def _epoch(value):
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.timestamp() if stamp.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _text(value, size=220):
    return ' '.join(value.split())[:size] if isinstance(value, str) else ''


def _safe_error(error):
    return (type(error).__name__ + ': ' + _redact(str(error)))[:240]


def _redact(value):
    text = _text(value)
    # Logs exposed through the dashboard must not copy arbitrary local paths,
    # URLs or complete exception representations supplied by an adapter.
    text = re.sub(r'(?:[A-Za-z]:[\\/]|/)[^\s,;<>]+', '[chemin local]', text)
    return text


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result

    def reject(value):
        raise ValueError('Non-finite JSON')

    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=reject)
    json.dumps(value, allow_nan=False)
    return value


@contextmanager
def _directory(core, components, create=False):
    """Traverse only known components without following directory symlinks."""
    descriptor = None
    try:
        descriptor = os.open(str(core), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in ('artifacts', *components):
            if not re.fullmatch(r'[A-Za-z0-9-]+', component):
                raise ScenePreparationStorageError('Unsafe preparation storage component')
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
            raise ScenePreparationStorageError(
                'Preparation storage must not contain symlinks'
            ) from error
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read(descriptor, filename, maximum, budget=None):
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    with os.fdopen(fd, 'rb') as stream:
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
            raise ValueError('Invalid preparation artifact type or size')
        if budget is not None:
            if details.st_size > budget[0]:
                budget[0] = 0
                raise ValueError('Preparation observation budget exhausted')
            budget[0] -= details.st_size
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('Preparation artifact exceeds budget')
        return raw


@contextmanager
def _locked(descriptor):
    fd = os.open(
        'scene-preparation.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor
    )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ScenePreparationStorageError('Expected a regular preparation lock')
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class PreparationStatus:
    """One attempt owns its updates; a late older attempt cannot replace it."""

    def __init__(self, core, identifier, campaign, *, clock=time.time):
        if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
            raise ValueError('Expected an opaque campaign UUID')
        self.core, self.clock = Path(core), clock
        payload = campaign if isinstance(campaign, dict) else {}
        self.data = {
            'schema': SCHEMA,
            'campaignId': identifier,
            'runId': uuid.uuid4().hex,
            'engine': (
                payload.get('engine') if _registered(self.core, payload.get('engine')) else None
            ),
            'campaignName': _text(payload.get('name'), 128) or 'Campagne sans nom',
            'pid': os.getpid(),
            'processToken': _PROCESS_TOKEN,
            'phase': 'queued',
            'currentRole': 'planner',
            'startedAt': _iso(clock()),
            'updatedAt': _iso(clock()),
            'nativeValidated': False,
            'steps': [
                {'role': role, 'label': label, 'state': 'idle', 'detail': 'En attente'}
                for role, label in ROLES
            ],
            'events': [],
        }
        self.started = False

    def _write(self, initial=False):
        self.data['updatedAt'] = _iso(self.clock())
        raw = (
            json.dumps(self.data, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n'
        ).encode()
        if len(raw) > MAX_STATUS:
            raise ValueError('Preparation telemetry exceeds budget')
        with _directory(self.core, ('operations',), create=True) as descriptor:
            with _locked(descriptor):
                return self._write_locked(descriptor, raw, initial)

    def _write_locked(self, descriptor, raw, initial):
        # The shared advisory lock makes this compare-and-replace atomic
        # relative to a newer preparation starting in another thread/process.
        try:
            details = os.stat(STATUS_FILE, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(details.st_mode):
                raise ScenePreparationStorageError('Preparation status must be a regular file')
        except FileNotFoundError:
            pass
        if not initial:
            try:
                current = _json(_read(descriptor, STATUS_FILE, MAX_STATUS))
                if current.get('runId') != self.data['runId']:
                    return False
            except FileNotFoundError:
                return False
        temporary = '.scene-preparation-' + uuid.uuid4().hex + '.tmp'
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, STATUS_FILE, src_dir_fd=descriptor, dst_dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass
        return True

    def _event(self, role, kind, message):
        self.data['events'] = (
            self.data['events']
            + [
                {
                    'id': uuid.uuid4().hex,
                    'at': _iso(self.clock()),
                    'source': 'scene_preparation',
                    'role': role,
                    'kind': kind,
                    'message': _text(message),
                }
            ]
        )[-16:]

    def __enter__(self):
        self._event('planner', 'queued', 'Préparation de scène demandée ; aucun moteur lancé.')
        self._write(initial=True)
        self.started = True
        return self

    def step(self, role):
        if role not in dict(ROLES):
            raise ValueError('Unknown preparation role')
        for step in self.data['steps']:
            if step['state'] == 'running':
                step.update(state='complete', detail='Étape de préparation terminée')
            if step['role'] == role:
                step.update(state='running', detail='Exécution déterministe en cours')
        self.data.update(phase='preparing', currentRole=role)
        self._event(role, 'preparing', dict(ROLES)[role] + ' en cours ; préparation hors ligne.')
        self._write()

    def complete(self):
        for step in self.data['steps']:
            step.update(state='complete', detail='Étape de préparation terminée')
        self.data.update(phase='complete', currentRole='validator', completedAt=_iso(self.clock()))
        self._event(
            'validator',
            'complete',
            'Paquet de scène préparé et fichiers vérifiés ; moteur non exécuté.',
        )
        self._write()

    def __exit__(self, kind, error, traceback):
        if error is None and self.data['phase'] != 'complete':
            error = RuntimeError('Preparation ended without a verified package')
        if error is not None and self.started:
            for step in self.data['steps']:
                if step['role'] == self.data['currentRole']:
                    step.update(state='failed', detail='Préparation interrompue')
            self.data.update(
                phase='failed', error=_safe_error(error), completedAt=_iso(self.clock())
            )
            self._event(
                self.data['currentRole'], 'failed', 'Échec de préparation : ' + _safe_error(error)
            )
            try:
                self._write()
            except (OSError, ValueError):
                # Preserve the original failure, never manufacture completion.
                pass
        return False


def _package(descriptor, identifier, budget, core):
    manifest_raw = _read(descriptor, 'manifest.json', MAX_ARTIFACT, budget)
    manifest = _json(manifest_raw)
    if (
        not isinstance(manifest, dict)
        or manifest.get('schema') != 'lotusim-manual-campaign-1'
        or manifest.get('id') != identifier
    ):
        return None
    engine = _registered(core, manifest.get('engine'))
    if engine is None:
        return None
    campaign_raw = _read(descriptor, 'campaign.json', MAX_ARTIFACT, budget)
    campaign = _json(campaign_raw)
    digest = hashlib.sha256(campaign_raw).hexdigest()
    if (
        not isinstance(campaign, dict)
        or campaign.get('schema') != 'lotusim-campaign-settings-1'
        or campaign.get('engine') != manifest['engine']
        or campaign.get('scene') != manifest.get('scene')
        or digest != manifest.get('campaignSha256')
    ):
        return None
    rows = manifest.get('artifacts')
    if not isinstance(rows, list) or len(rows) > 10:
        return None
    inventory = {}
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {'name', 'sha256', 'bytes'}
            or not isinstance(row['name'], str)
            or row['name'] not in PREPARED_FILES - {'manifest.json'}
            or row['name'] in inventory
            or type(row['bytes']) is not int
            or not 0 <= row['bytes'] <= MAX_ARTIFACT
            or not isinstance(row['sha256'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', row['sha256'])
        ):
            return None
        inventory[row['name']] = row
    if set(inventory) not in (expected_artifacts(engine), expected_artifacts(engine, legacy=True)):
        return None
    files = {'campaign.json': campaign_raw}
    for name, row in inventory.items():
        raw = (
            campaign_raw
            if name == 'campaign.json'
            else _read(descriptor, name, MAX_ARTIFACT, budget)
        )
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            return None
        if name == 'engine-agent.json':
            files[name] = raw
    trace_raw = files['engine-agent.json']
    trace = _json(trace_raw)
    if (
        not isinstance(trace, dict)
        or trace.get('schema') != 'lotusim-render-engine-agent-1'
        or trace.get('kind') != 'deterministic_role_pipeline'
        or trace.get('id') != identifier
        or trace.get('engine') != manifest['engine']
        or trace.get('campaignSha256') != digest
        or trace.get('nativeValidated') is not False
    ):
        return None
    traces = trace.get('traces')
    if (
        not isinstance(traces, list)
        or len(traces) != 3
        or [item.get('role') for item in traces if isinstance(item, dict)]
        != [role for role, _ in ROLES]
        or any(item.get('state') != 'completed' for item in traces)
    ):
        return None
    return {
        'campaignId': identifier,
        'campaignName': _text(campaign.get('name'), 128),
        'engine': manifest['engine'],
        'updatedAt': manifest.get('createdAt'),
        'steps': [
            {
                'role': role,
                'label': label,
                'state': 'complete',
                'detail': 'Étape archivée, non active',
            }
            for role, label in ROLES
        ],
    }


def _prepared(core, identifier, budget=None):
    try:
        with _directory(core, ('campaign-settings', 'prepared', identifier)) as descriptor:
            return _package(
                descriptor, identifier, budget if budget is not None else [16 * MAX_ARTIFACT], core
            )
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        return None


def _latest(core):
    try:
        with _directory(core, ('campaign-settings', 'prepared')) as descriptor:
            candidates = []
            with os.scandir(descriptor) as entries:
                for count, entry in enumerate(entries):
                    if count >= MAX_HISTORY:
                        break
                    if _UUID.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                        candidates.append((entry.stat(follow_symlinks=False).st_mtime, entry.name))
            budget = [16 * MAX_ARTIFACT]
            for _, identifier in sorted(candidates, reverse=True):
                if budget[0] <= 0:
                    break
                result = _prepared(core, identifier, budget)
                if result:
                    return result
    except (OSError, ValueError):
        pass
    return None


def observe_preparation(core, *, now=None, process_alive=None):
    """Read-only agent/event view. Saved plans cannot produce an active state."""
    now = time.time() if now is None else now
    process_alive = process_alive or (lambda pid: False)
    public = {
        'id': 'scene_preparation',
        'label': 'Agent de préparation de scène',
        'group': 'Préparation',
        'state': 'idle',
        'phase': 'idle',
        'detail': 'En veille — aucune préparation observée',
        'engine': None,
        'campaignId': None,
        'campaignName': None,
        'updatedAt': None,
        'historical': False,
        'nativeValidated': False,
        'live': False,
        'links': {},
        'steps': [
            {'role': role, 'label': label, 'state': 'idle', 'detail': 'En attente'}
            for role, label in ROLES
        ],
    }
    source = None
    try:
        with _directory(Path(core), ('operations',)) as descriptor:
            source = _json(_read(descriptor, STATUS_FILE, MAX_STATUS))
    except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
        pass
    valid = (
        isinstance(source, dict)
        and source.get('schema') == SCHEMA
        and isinstance(source.get('campaignId'), str)
        and _UUID.fullmatch(source['campaignId'])
        and source.get('phase') in ('queued', 'preparing', 'complete', 'failed')
        and source.get('nativeValidated') is False
    )
    events = []
    if valid:
        phase, stamp = source['phase'], _epoch(source.get('updatedAt'))
        age = now - stamp if stamp is not None else float('inf')
        pid = source.get('pid')
        # A fresh PID alone can belong to a different process after PID reuse.
        # Dashboard preparations run in this interpreter; its non-persisted
        # token proves the owning process incarnation without reading argv.
        owner_confirmed = pid == os.getpid() and source.get('processToken') == _PROCESS_TOKEN
        live = False
        if (
            phase in ('queued', 'preparing')
            and 0 <= age <= ACTIVE_SECONDS
            and type(pid) is int
            and pid > 0
            and owner_confirmed
        ):
            try:
                live = bool(process_alive(pid))
            except (OSError, ValueError, TypeError):
                pass
        public.update(
            phase=phase,
            engine=source.get('engine') if _registered(core, source.get('engine')) else None,
            campaignId=source['campaignId'],
            campaignName=_text(source.get('campaignName'), 128),
            updatedAt=_iso(stamp) if stamp is not None else None,
            live=live,
            historical=not live and (phase in ('queued', 'preparing') or age > 15),
        )
        steps = source.get('steps')
        if isinstance(steps, list) and len(steps) == 3:
            for original, candidate in zip(public['steps'], steps):
                if isinstance(candidate, dict) and candidate.get('role') == original['role']:
                    original.update(
                        state=(
                            candidate.get('state')
                            if candidate.get('state') in ('idle', 'running', 'complete', 'failed')
                            else 'idle'
                        ),
                        detail=_text(candidate.get('detail')),
                    )
        if phase in ('queued', 'preparing'):
            public.update(
                state='running' if live else 'stale',
                detail=(
                    'Préparation hors ligne en cours ; moteur non lancé'
                    if live
                    else 'Ancienne préparation en cours — processus ou fraîcheur non confirmés'
                ),
            )
            if not live:
                for step in public['steps']:
                    if step['state'] == 'running':
                        step.update(state='idle', detail='Ancienne étape — activité non confirmée')
        elif phase == 'failed':
            public.update(
                state='failed', detail='Échec de préparation : ' + _redact(source.get('error'))
            )
        else:
            package = _prepared(Path(core), source['campaignId'])
            if package:
                public.update(
                    package,
                    state='complete',
                    detail='Paquet préparé et vérifié — moteur non exécuté',
                )
                public['updatedAt'] = _iso(stamp) if stamp is not None else package['updatedAt']
            else:
                public.update(
                    state='failed',
                    detail='Paquet de préparation absent ou modifié ; succès non confirmé',
                )
        values = source.get('events')
        if isinstance(values, list):
            for index, item in enumerate(values[-16:]):
                if not isinstance(item, dict):
                    continue
                at = _epoch(item.get('at'))
                if at is None:
                    continue
                events.append(
                    {
                        'id': 'scene-preparation-' + _text(item.get('id'), 40),
                        'at': _iso(at),
                        'source': 'scene_preparation',
                        'level': 'error' if item.get('kind') == 'failed' else 'info',
                        'message': _redact(item.get('message')),
                        'historical': not live or now - at > 15,
                    }
                )
    else:
        package = _latest(Path(core))
        if package:
            public.update(
                package,
                state='complete',
                phase='complete',
                historical=True,
                detail='Paquet préparé vérifié — historique, moteur non exécuté',
            )
            stamp = _epoch(package.get('updatedAt'))
            if stamp is not None:
                events.append(
                    {
                        'id': 'scene-preparation-archive-' + package['campaignId'],
                        'at': _iso(stamp),
                        'source': 'scene_preparation',
                        'level': 'info',
                        'message': 'Paquet de scène '
                        + package['engine']
                        + ' archivé et vérifié ; aucun agent actif.',
                        'historical': True,
                    }
                )
    if public['state'] == 'complete':
        prefix = '/api/settings/prepared/' + public['campaignId'] + '/'
        public['links'] = {
            'bundleUrl': prefix + 'bundle.zip',
            'manifestUrl': prefix + 'manifest.json',
            'traceUrl': prefix + 'engine-agent.json',
        }
    return public, events
