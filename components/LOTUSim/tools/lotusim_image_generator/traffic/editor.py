"""Read known cooperative plans and save inert immutable trajectory drafts.

Unity X/Y/Z are explicitly translated to East/Up/North. Sampling mirrors the
existing planner's straight and bounded constant-turn kinematics. A draft is
never written into the active plan, a Unity asset, ROS or a simulation.
"""

import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from lotusim_image_generator.traffic.kinematics import position

MAX_JSON = 2 * 1024 * 1024
MAX_DRAFT = 4 * 1024 * 1024
MAX_ACTORS = 64
MAX_POINTS = 181
SCHEMA = 'lotusim-traffic-editor-1'
DRAFT_SCHEMA = 'lotusim-traffic-draft-1'
_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,79}$')
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
LIMITATIONS = [
    'Trajectoires prévues, pas des positions mesurées en direct. La présence dans le plan ne garantit pas la visibilité sur une image.',
    'Les brouillons sont des exports locaux : ils ne sont appliqués ni au plan en cours, ni à ROS, ni à un moteur 3D.',
    'Toute modification invalide la validation coopérative d’origine. Les collisions, les règles COLREG, les distances entre coques et la dynamique de vol ne sont pas certifiées ici.',
    'Les limites de vitesse et d’altitude du catalogue sont des hypothèses de scénario, pas des performances certifiées.',
    'Les courbes sont échantillonnées. Les limites de zone portent sur le centre des objets, sans carte nautique ni contrôle des fonds.',
]


class TrafficPlanSecurityError(ValueError):
    pass


class TrafficConflictError(ValueError):
    pass


class TrafficValidationError(ValueError):
    def __init__(self, errors):
        super().__init__('Invalid trajectory draft')
        self.validation = {'valid': False, 'errors': errors}


def _finite(value):
    try:
        return (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        )
    except OverflowError:
        return False


def _decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result

    def constant(_):
        raise ValueError('Non-finite JSON')

    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    json.dumps(value, allow_nan=False)
    return value


def _encode(value):
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
    ).encode('utf-8')


def _read(root, relative, maximum=MAX_JSON):
    """Read fixed relative sources by no-follow descriptors, never user paths."""
    pieces = relative.split('/')
    if any(not p or p in ('.', '..') or '\\' in p or '\0' in p for p in pieces):
        raise TrafficPlanSecurityError('Unsafe traffic plan path')
    descriptor = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for piece in pieces[:-1]:
            child = os.open(piece, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file_fd = os.open(
            pieces[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        with os.fdopen(file_fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise TrafficPlanSecurityError('Traffic plan must be a bounded regular file')
            data = stream.read(maximum + 1)
            if len(data) > maximum:
                raise TrafficPlanSecurityError('Traffic plan exceeds the byte limit')
            return data, info.st_mtime
    finally:
        os.close(descriptor)


def _embedded_plan(raw):
    """Only Unity's single double-quoted planJson scalar; no general YAML."""
    text = raw.decode('utf-8')
    matches = list(re.finditer(r'^  planJson:[ \t]*("(?:[^"\\]|\\.)*")', text, re.M | re.S))
    if len(matches) != 1:
        raise ValueError('Expected one quoted embedded planJson')
    # YAML double-quoted flow scalars fold physical wrapping whitespace; the
    # literal backslash-n escapes carrying actual JSON newlines remain intact.
    scalar = re.sub(r'\r?\n[ \t]*', ' ', matches[0].group(1))
    decoded = _decode(scalar.encode('utf-8'))
    if not isinstance(decoded, str):
        raise ValueError('Expected embedded JSON text')
    return _decode(decoded.encode('utf-8'))


def _xyz(value):
    if not isinstance(value, dict) or not all(_finite(value.get(key)) for key in ('x', 'y', 'z')):
        raise ValueError('Invalid Unity vector')
    return [value['x'], value['y'], value['z']]


def position_enu(event, at):
    """Apply the shared planner equations and expose explicit ENU metre fields."""
    route = {
        'center': _xyz(event['centerPosition']),
        'velocity': _xyz(event['velocity']),
        'focus': event['centerSeconds'],
        'yawRateDegS': event.get('yawRateDegS', 0),
        'boundedTurn': event.get('boundedTurn', False),
        'turnStartSeconds': event.get('turnStartSeconds', 0),
        'turnEndSeconds': event.get('turnEndSeconds', 0),
    }
    point = position(route, at)
    return {'timeSeconds': at, 'eastM': point[0], 'northM': point[2], 'altitudeM': point[1]}


def _times(event):
    start, end = event['startSeconds'], event['endSeconds']
    anchors = {start, end, event['centerSeconds']}
    if event.get('boundedTurn'):
        anchors.update((event['turnStartSeconds'], event['turnEndSeconds']))
    # Reserve space for exact focus/turn boundaries without exceeding 181.
    count = MAX_POINTS - len(anchors) + 2
    return sorted(anchors | {start + (end - start) * i / (count - 1) for i in range(count)})[
        :MAX_POINTS
    ]


def _iso(value):
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


class TrafficPlanStore:
    def __init__(self, core_root, unity_root, *, clock=time.time):
        self.core = Path(core_root).resolve()
        self.unity = Path(unity_root).resolve()
        self.clock = clock

    def _sources(self):
        candidates = []
        for root, label in ((self.core, 'LOTUSim'), (self.unity, 'Unity')):
            for filename in ('plan.json', 'unity-plan.json'):
                candidates.append(
                    (
                        root,
                        'artifacts/traffic-agents/' + filename,
                        'existing_plan',
                        label + ' · plan coopératif enregistré',
                    )
                )
        candidates.append(
            (
                self.unity,
                'Assets/Dataset/MaritimeTrafficAgents.plan.asset',
                'embedded_unity_asset',
                'Unity · plan intégré MaritimeTrafficAgents',
            )
        )
        return candidates

    @staticmethod
    def _check_plan(plan):
        if not isinstance(plan, dict) or plan.get('schema') != 'lotusim-unity-encounters-1':
            raise ValueError('Unsupported traffic plan schema')
        events = plan.get('events')
        if not isinstance(events, list) or not 1 <= len(events) <= MAX_ACTORS:
            raise ValueError('Expected 1–64 actor events')
        identifiers = set()
        for event in events:
            if (
                not isinstance(event, dict)
                or not isinstance(event.get('instance'), str)
                or not _ID.fullmatch(event['instance'])
            ):
                raise ValueError('Invalid actor identity')
            if event['instance'] in identifiers:
                raise ValueError('Duplicate actor identity')
            identifiers.add(event['instance'])
            if (
                not isinstance(event.get('modelName'), str)
                or not _ID.fullmatch(event['modelName'])
                or not isinstance(event.get('category'), str)
                or not _ID.fullmatch(event['category'])
            ):
                raise ValueError('Invalid actor model/category')
            center, velocity = _xyz(event.get('centerPosition')), _xyz(event.get('velocity'))
            start, end, focus = (
                event.get(key) for key in ('startSeconds', 'endSeconds', 'centerSeconds')
            )
            if (
                not all(_finite(value) for value in (start, end, focus))
                or not 0 <= start < end <= 600
                or not start <= focus <= end
                or velocity[1] != 0
                or any(abs(value) > 100000 for value in (center[0], center[2]))
                or not 0 <= center[1] <= 15000
                or math.hypot(*velocity) > 350
            ):
                raise ValueError('Invalid bounded actor kinematics')
            yaw = event.get('yawRateDegS', 0)
            if (
                not _finite(yaw)
                or abs(yaw) > 5
                or not isinstance(event.get('boundedTurn', False), bool)
            ):
                raise ValueError('Invalid turn rate')
            if event.get('boundedTurn'):
                left, right = event.get('turnStartSeconds'), event.get('turnEndSeconds')
                if (
                    not all(_finite(v) for v in (left, right))
                    or not start <= left <= focus <= right <= end
                    or left == right
                ):
                    raise ValueError('Invalid bounded turn window')
                duration = right - left
            else:
                duration = end - start
            if abs(yaw) * duration > 45.0001:
                raise ValueError('Turn exceeds existing 45 degree model')
        return plan

    def _load(self):
        loaded = []
        for root, relative, kind, label in self._sources():
            try:
                raw, modified = _read(root, relative)
                plan = _embedded_plan(raw) if kind == 'embedded_unity_asset' else _decode(raw)
                self._check_plan(plan)
                loaded.append(
                    (
                        kind != 'embedded_unity_asset',
                        modified,
                        root,
                        relative,
                        kind,
                        label,
                        raw,
                        plan,
                    )
                )
            except (OSError, ValueError, UnicodeError, RecursionError, OverflowError):
                continue
        if not loaded:
            return None
        _, modified, root, relative, kind, label, raw, plan = max(loaded, key=lambda item: item[:2])
        source = {
            'id': ('core-' if root == self.core else 'unity-') + kind,
            'engineId': 'unity',
            'label': label,
            'relativePath': relative,
            'kind': kind,
            'sha256': hashlib.sha256(raw).hexdigest(),
            'updatedAt': _iso(modified),
            'ageSeconds': round(max(0, self.clock() - modified), 2),
            'runtimeExecutionConfirmed': False,
        }
        scope, catalogue = {}, {}
        for name, target, expected in (
            ('scope.snapshot.json', scope, 'lotusim-traffic-scope-1'),
            ('catalogue.snapshot.json', catalogue, 'lotusim-traffic-catalogue-1'),
        ):
            try:
                content, _ = _read(root, str(Path(relative).parent / name))
                value = _decode(content)
                if isinstance(value, dict) and value.get('schema') == expected:
                    target.update(value)
            except (OSError, ValueError, UnicodeError, RecursionError):
                pass
        for target, relative_path, expected in (
            (
                scope,
                'assets/scenarios/scopes/MaritimeTrafficAgents.json',
                'lotusim-traffic-scope-1',
            ),
            (
                catalogue,
                'assets/scenarios/catalogs/traffic_assets.json',
                'lotusim-traffic-catalogue-1',
            ),
        ):
            if target:
                continue
            try:
                content, _ = _read(self.core, relative_path)
                value = _decode(content)
                if isinstance(value, dict) and value.get('schema') == expected:
                    target.update(value)
            except (OSError, ValueError, UnicodeError, RecursionError):
                pass
        template = {}
        try:
            content, _ = _read(root, str(Path(relative).parent / 'unity-template.json'))
            value = _decode(content)
            if isinstance(value, dict):
                template = value
        except (OSError, ValueError, UnicodeError, RecursionError):
            pass
        if not template:
            try:
                content, _ = _read(self.unity, 'Assets/Dataset/MaritimeTrafficAgents.asset')
                text = content.decode('utf-8')
                for key in ('observerSpeedMps', 'routeHeadingDeg', 'observerTurnDeg'):
                    found = re.search(r'^  ' + key + r': ([0-9eE+.-]+)\s*$', text, re.M)
                    if found and _finite(float(found.group(1))):
                        template[key] = float(found.group(1))
                origin = re.search(
                    r'^  origin: \{x: ([0-9eE+.-]+), y: ([0-9eE+.-]+), z: ([0-9eE+.-]+)\}',
                    text,
                    re.M,
                )
                if origin:
                    template['origin'] = dict(zip(('x', 'y', 'z'), map(float, origin.groups())))
            except (OSError, ValueError, UnicodeError):
                pass
        return source, plan, scope, catalogue, template

    @staticmethod
    def _assets(catalogue):
        return (
            {
                item['model']: item
                for item in catalogue.get('assets', [])
                if isinstance(item, dict)
                and isinstance(item.get('model'), str)
                and item.get('domain') in ('air', 'sea', 'moored')
                and _finite(item.get('maxSpeedMps'))
                and 0 <= item['maxSpeedMps'] <= 350
                and (
                    item['domain'] != 'air'
                    or (_finite(item.get('maxAltitudeM')) and 0 < item['maxAltitudeM'] <= 15000)
                )
            }
            if isinstance(catalogue.get('assets', []), list)
            else {}
        )

    def _normalize(self, loaded, *, changes=None):
        source, plan, scope, catalogue, template = loaded
        assets = self._assets(catalogue)
        actors = []
        for event in plan['events']:
            asset = assets.get(event.get('modelName'), {})
            velocity = _xyz(event['velocity'])
            center = _xyz(event['centerPosition'])
            speed = math.hypot(*velocity)
            yaw = event.get('yawRateDegS', 0)
            actor = {
                'id': event['instance'],
                'model': event.get('modelName'),
                'category': event.get('category'),
                'domain': asset.get('domain', 'unknown'),
                'startSeconds': event['startSeconds'],
                'endSeconds': event['endSeconds'],
                'centerSeconds': event['centerSeconds'],
                'centerENU': {'eastM': center[0], 'northM': center[2], 'altitudeM': center[1]},
                'speedMps': speed,
                'headingDeg': (
                    math.degrees(math.atan2(velocity[0], velocity[2])) % 360 if speed else 0
                ),
                'maxSpeedMps': asset.get('maxSpeedMps'),
                'maxAltitudeM': asset.get('maxAltitudeM', 0),
                'editable': bool(asset and _finite(asset.get('maxSpeedMps'))),
                'trajectoryKind': (
                    'bounded_turn'
                    if event.get('boundedTurn') and yaw
                    else 'constant_turn' if yaw else 'linear'
                ),
                'boundedTurn': event.get('boundedTurn', False),
                'yawRateDegS': yaw,
                'turnStartSeconds': event.get('turnStartSeconds', 0),
                'turnEndSeconds': event.get('turnEndSeconds', 0),
                'points': [position_enu(event, at) for at in _times(event)],
            }
            if (
                changes
                and event['instance'] in changes
                and 'controlPoints' in changes[event['instance']]
            ):
                controls = changes[event['instance']]['controlPoints']
                actor.update(
                    trajectoryKind='piecewise_linear',
                    controlPoints=controls,
                    points=self._sample_controls(controls),
                    boundedTurn=False,
                    yawRateDegS=0,
                )
                actor['speedMps'] = max(self._segment_speeds(controls))
            actors.append(actor)
        start = min(event['startSeconds'] for event in plan['events'])
        end = max(event['endSeconds'] for event in plan['events'])
        observer = None
        config = scope.get('observer') if isinstance(scope.get('observer'), dict) else {}
        speed = template.get(
            'observerSpeedMps',
            (
                config.get('speedKnots', 0) * 1852 / 3600
                if _finite(config.get('speedKnots'))
                else None
            ),
        )
        heading = template.get('routeHeadingDeg', config.get('headingDeg'))
        turn = template.get('observerTurnDeg', config.get('turnDeg'))
        if (
            all(_finite(v) for v in (speed, heading, turn))
            and 0 <= speed <= 30
            and 0 <= heading <= 360
            and abs(turn) <= 45
        ):
            try:
                origin = _xyz(template.get('origin', {'x': 0, 'y': 0, 'z': 0}))
                event = {
                    'centerPosition': dict(zip(('x', 'y', 'z'), origin)),
                    'velocity': {
                        'x': speed * math.sin(math.radians(heading)),
                        'y': 0,
                        'z': speed * math.cos(math.radians(heading)),
                    },
                    'centerSeconds': 0,
                    'startSeconds': start,
                    'endSeconds': end,
                    'yawRateDegS': turn / (end - start),
                }
                observer = {
                    'id': 'ObserverBoat',
                    'model': 'fremm_observer',
                    'domain': 'sea',
                    'editable': False,
                    'speedMps': speed,
                    'headingDeg': heading,
                    'points': [position_enu(event, at) for at in _times(event)],
                }
            except ValueError:
                pass
        counts = {}
        for actor in actors:
            counts[actor['category']] = counts.get(actor['category'], 0) + 1
        return {
            'schema': SCHEMA,
            'available': True,
            'baseSha256': source['sha256'],
            'source': source,
            'timeline': {
                'startSeconds': start,
                'endSeconds': end,
                'durationSeconds': end - start,
                'sampleStepSeconds': (end - start) / (MAX_POINTS - 5),
                'maxPointsPerActor': MAX_POINTS,
            },
            'actors': actors,
            'observer': observer,
            'waterBounds': self._water(scope),
            'plan': plan,
            'warnings': list(LIMITATIONS),
            'applied': False,
            'collisionChecked': False if changes else None,
            'draftPreview': bool(changes),
            'requiresRevalidation': bool(changes),
            'summary': {
                'actorCount': len(actors),
                'changedActors': len(changes or {}),
                'classCounts': counts,
            },
        }

    @staticmethod
    def _water(scope):
        water = scope.get('water') if isinstance(scope.get('water'), dict) else {}
        names = ('eastMinM', 'eastMaxM', 'northMinM', 'northMaxM')
        return (
            {key: water[key] for key in names}
            if all(_finite(water.get(key)) for key in names)
            else None
        )

    def get(self):
        loaded = self._load()
        if loaded is None:
            return {
                'schema': SCHEMA,
                'available': False,
                'baseSha256': None,
                'source': None,
                'timeline': None,
                'actors': [],
                'observer': None,
                'waterBounds': None,
                'plan': None,
                'warnings': ['Aucun plan coopératif enregistré dans les emplacements autorisés.']
                + LIMITATIONS,
                'applied': False,
                'collisionChecked': False,
            }
        return self._normalize(loaded)

    @staticmethod
    def _segment_speeds(points):
        return [
            math.hypot(*(right[key] - left[key] for key in ('eastM', 'northM', 'altitudeM')))
            / (right['timeSeconds'] - left['timeSeconds'])
            for left, right in zip(points, points[1:])
        ]

    @staticmethod
    def _sample_controls(controls):
        start, end = controls[0]['timeSeconds'], controls[-1]['timeSeconds']
        times = sorted(
            {start + (end - start) * i / 178 for i in range(179)}
            | {p['timeSeconds'] for p in controls}
        )
        result = []
        for at in times:
            left, right = next(
                (
                    (a, b)
                    for a, b in zip(controls, controls[1:])
                    if a['timeSeconds'] <= at <= b['timeSeconds']
                ),
                (controls[-2], controls[-1]),
            )
            fraction = (at - left['timeSeconds']) / (right['timeSeconds'] - left['timeSeconds'])
            result.append(
                {
                    'timeSeconds': at,
                    **{
                        key: left[key] + fraction * (right[key] - left[key])
                        for key in ('eastM', 'northM', 'altitudeM')
                    },
                }
            )
        return result

    def build_draft(self, payload, loaded):
        """Explicit trusted in-memory source injection for the plan library.

        Validation/normalization are identical to file drafts, but no source or
        export file is written. The library owns revision checks/transactions.
        """
        return self.save_draft(payload, loaded=loaded, persist=False)

    def save_draft(self, payload, *, loaded=None, persist=True):
        errors = []

        def error(path, message):
            errors.append({'path': path, 'message': message})

        try:
            if len(_encode(payload)) > MAX_JSON:
                raise ValueError('Draft request exceeds 2 MiB')
        except (TypeError, ValueError, RecursionError, OverflowError) as exc:
            raise TrafficValidationError(
                [{'path': '$', 'message': 'Expected bounded finite JSON'}]
            ) from exc
        if not isinstance(payload, dict) or set(payload) != {'baseSha256', 'name', 'changes'}:
            raise TrafficValidationError(
                [{'path': '$', 'message': 'Expected only baseSha256, name and changes'}]
            )
        base = payload.get('baseSha256')
        if not isinstance(base, str) or not re.fullmatch(r'[0-9a-f]{64}', base):
            error('$.baseSha256', 'Expected the displayed source SHA-256')
        injected = loaded is not None
        loaded = loaded if injected else self._load()
        if loaded is None or (not errors and loaded[0]['sha256'] != base):
            raise TrafficConflictError(
                'The source plan changed or is unavailable; reload it before saving a draft'
            )
        name = payload.get('name')
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 120
            or any(ord(c) < 32 for c in name)
        ):
            error('$.name', 'Use 1–120 printable characters')
        changes = payload.get('changes')
        if not isinstance(changes, list) or not 1 <= len(changes) <= MAX_ACTORS:
            error('$.changes', 'Use 1–64 existing actor changes')
            changes = []
        source, original, scope, catalogue, template = loaded
        plan = copy.deepcopy(original)
        events = {item['instance']: item for item in plan['events']}
        assets = self._assets(catalogue)
        seen = set()
        normalized = []
        water = self._water(scope)
        for index, change in enumerate(changes):
            path = '$.changes[%d]' % index
            if not isinstance(change, dict):
                error(path, 'Expected an actor change')
                continue
            actor_id = change.get('actorId')
            if not isinstance(actor_id, str) or actor_id not in events:
                error(path + '.actorId', 'Only existing actor IDs can be changed')
                continue
            if actor_id in seen:
                error(path + '.actorId', 'Duplicate actor change')
                continue
            seen.add(actor_id)
            event = events[actor_id]
            asset = assets.get(event.get('modelName'), {})
            if not asset or not _finite(asset.get('maxSpeedMps')):
                error(path, 'Catalogue capability is unavailable; this actor is read-only')
                continue
            controls = change.get('controlPoints')
            if controls is not None:
                if (
                    set(change) != {'actorId', 'controlPoints'}
                    or not isinstance(controls, list)
                    or not 2 <= len(controls) <= 3
                ):
                    error(path, 'Use actorId and 2–3 timed controlPoints only')
                    continue
                controls_valid = True
                for j, point in enumerate(controls):
                    if (
                        not isinstance(point, dict)
                        or set(point) != {'timeSeconds', 'eastM', 'northM', 'altitudeM'}
                        or not all(
                            _finite(point.get(k))
                            for k in ('timeSeconds', 'eastM', 'northM', 'altitudeM')
                        )
                        or abs(point['eastM']) > 100000
                        or abs(point['northM']) > 100000
                        or not 0 <= point['altitudeM'] <= 15000
                    ):
                        error(
                            path + '.controlPoints[%d]' % j,
                            'Expected finite timeSeconds, eastM, northM, altitudeM',
                        )
                        controls_valid = False
                if not controls_valid:
                    continue
                if (
                    controls[0]['timeSeconds'] != event['startSeconds']
                    or controls[-1]['timeSeconds'] != event['endSeconds']
                    or any(
                        a['timeSeconds'] >= b['timeSeconds'] for a, b in zip(controls, controls[1:])
                    )
                ):
                    error(
                        path + '.controlPoints',
                        'Times must increase strictly and preserve the original start/end times',
                    )
                    continue
                speeds = self._segment_speeds(controls)
                if max(speeds) > asset['maxSpeedMps'] + 1e-6:
                    error(path + '.controlPoints', 'A segment exceeds the catalogue maximum speed')
                points = self._sample_controls(controls)
                normalized.append(
                    {
                        'actorId': actor_id,
                        'controlPoints': copy.deepcopy(controls),
                        'segmentSpeedsMps': speeds,
                    }
                )
            else:
                required = {'actorId', 'centerENU', 'speedMps', 'headingDeg'}
                if not required <= set(change) or set(change) - required - {'yawRateDegS'}:
                    error(
                        path,
                        'Expected actorId, centerENU, speedMps, headingDeg and optional yawRateDegS',
                    )
                    continue
                center = change.get('centerENU')
                speed = change.get('speedMps')
                heading = change.get('headingDeg')
                yaw = change.get('yawRateDegS', event.get('yawRateDegS', 0))
                if (
                    not isinstance(center, dict)
                    or set(center) != {'eastM', 'northM', 'altitudeM'}
                    or not all(_finite(center.get(k)) for k in ('eastM', 'northM', 'altitudeM'))
                    or not all(_finite(v) for v in (speed, heading, yaw))
                ):
                    error(path, 'Expected finite centre, speed, heading and yaw')
                    continue
                turn_duration = (
                    event['turnEndSeconds'] - event['turnStartSeconds']
                    if event.get('boundedTurn')
                    else event['endSeconds'] - event['startSeconds']
                )
                if not 0 <= speed <= asset['maxSpeedMps']:
                    error(path + '.speedMps', 'Speed exceeds catalogue capability or is negative')
                if not 0 <= heading <= 360:
                    error(path + '.headingDeg', 'Heading must be 0–360 degrees')
                if abs(yaw) > 5 or abs(yaw) * turn_duration > 45.0001:
                    error(
                        path + '.yawRateDegS',
                        'Preserve the bounded model: at most 5 deg/s and 45 degrees total turn',
                    )
                if (
                    not 0 <= speed <= asset['maxSpeedMps']
                    or not 0 <= heading <= 360
                    or abs(yaw) > 5
                    or abs(yaw) * turn_duration > 45.0001
                    or abs(center['eastM']) > 100000
                    or abs(center['northM']) > 100000
                    or not 0 <= center['altitudeM'] <= 15000
                ):
                    if (
                        abs(center['eastM']) > 100000
                        or abs(center['northM']) > 100000
                        or not 0 <= center['altitudeM'] <= 15000
                    ):
                        error(path + '.centerENU', 'Centre exceeds coordinate/altitude bounds')
                    continue
                event.update(
                    centerPosition={
                        'x': center['eastM'],
                        'y': center['altitudeM'],
                        'z': center['northM'],
                    },
                    altitudeM=center['altitudeM'],
                    velocity={
                        'x': speed * math.sin(math.radians(heading)),
                        'y': 0,
                        'z': speed * math.cos(math.radians(heading)),
                    },
                    yawRateDegS=yaw,
                )
                points = [position_enu(event, at) for at in _times(event)]
                normalized.append(
                    {
                        'actorId': actor_id,
                        'centerENU': copy.deepcopy(center),
                        'speedMps': speed,
                        'headingDeg': heading % 360,
                        'yawRateDegS': yaw,
                    }
                )
            for point in points:
                east, north, altitude = (point[key] for key in ('eastM', 'northM', 'altitudeM'))
                if abs(east) > 100000 or abs(north) > 100000:
                    error(path, 'Trajectory exceeds the ±100000 m coordinate bound')
                    break
                if asset.get('domain') in ('sea', 'moored'):
                    if altitude != 0:
                        error(path, 'Sea and moored actors must remain at altitude 0')
                        break
                    if water and not (
                        water['eastMinM'] <= east <= water['eastMaxM']
                        and water['northMinM'] <= north <= water['northMaxM']
                    ):
                        error(path, 'Trajectory centre leaves the synthetic water rectangle')
                        break
                elif asset.get('domain') == 'air':
                    if not 0 < altitude <= min(15000, asset.get('maxAltitudeM', 0)):
                        error(
                            path,
                            'Aircraft altitude must be positive and within the catalogue ceiling',
                        )
                        break
                else:
                    error(path, 'Unsupported catalogue domain')
                    break
            if asset.get('domain') == 'moored':
                first = points[0]
                if any(
                    any(abs(p[key] - first[key]) > 1e-8 for key in ('eastM', 'northM', 'altitudeM'))
                    for p in points[1:]
                ):
                    error(path, 'Moored actors cannot move')
        if errors:
            raise TrafficValidationError(errors)
        # Re-read immediately before publication: an externally replaced plan
        # cannot be accepted under a stale browser revision.
        refreshed = loaded if injected else self._load()
        if refreshed is None or refreshed[0]['sha256'] != base:
            raise TrafficConflictError('The source plan changed while validating the draft')
        self._revoke_approval(plan)
        plan.update(
            requiresRevalidation=True,
            applied=False,
            collisionChecked=False,
            containsUncompiledControlPoints=any('controlPoints' in change for change in normalized),
        )
        identifier = str(uuid.uuid4())
        class_counts = {}
        for event in plan['events']:
            category = event['category']
            class_counts[category] = class_counts.get(category, 0) + 1
        draft = {
            'schema': DRAFT_SCHEMA,
            'id': identifier,
            'name': name.strip(),
            'createdAt': _iso(self.clock()),
            'baseSha256': base,
            'source': source,
            'applied': False,
            'collisionChecked': False,
            'requiresRevalidation': True,
            'originalPlan': original,
            'changes': normalized,
            'kinematicPlan': plan,
            'requiresNativeAdapter': any('controlPoints' in change for change in normalized),
            'warnings': list(LIMITATIONS),
            'summary': {
                'actorCount': len(plan['events']),
                'changedActors': len(normalized),
                'classCounts': class_counts,
            },
        }
        data = _encode(draft)
        if len(data) > MAX_DRAFT:
            raise TrafficValidationError([{'path': '$', 'message': 'Draft export exceeds 4 MiB'}])
        if persist:
            descriptor = os.open(str(self.core), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for component in ('artifacts', 'traffic-drafts'):
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(
                        component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                    os.close(descriptor)
                    descriptor = child
                os.mkdir(identifier, 0o700, dir_fd=descriptor)
                child = os.open(
                    identifier, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
                fd = os.open(
                    'draft.json',
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(descriptor)
        preview = self._normalize(
            (source, plan, scope, catalogue, template),
            changes={item['actorId']: item for item in normalized},
        )
        return {'id': identifier, 'draft': draft, 'preview': preview, 'applied': False}

    @staticmethod
    def _revoke_approval(value):
        """Approval belongs to originalPlan only, never to edited kinematics."""
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub('[^a-z]', '', key.lower())
                if isinstance(item, bool) and (
                    any(
                        token in normalized
                        for token in (
                            'approved',
                            'validated',
                            'certified',
                            'collisionfree',
                            'safetychecked',
                            'collisionchecked',
                        )
                    )
                    or normalized in ('safe', 'colregcompliant')
                ):
                    value[key] = False
                elif key in ('status', 'state') and item == 'approved':
                    value[key] = 'requires_revalidation'
                else:
                    TrafficPlanStore._revoke_approval(item)
        elif isinstance(value, list):
            for item in value:
                TrafficPlanStore._revoke_approval(item)

    def read_draft(self, identifier):
        if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
            raise TrafficPlanSecurityError('Expected an opaque draft UUID')
        return _read(
            self.core, 'artifacts/traffic-drafts/' + identifier + '/draft.json', MAX_DRAFT
        )[0]
