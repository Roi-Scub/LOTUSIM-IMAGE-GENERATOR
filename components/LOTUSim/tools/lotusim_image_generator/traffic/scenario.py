"""Pure, bounded cooperative scenario generation and independent re-audit.

No SDK, subprocess, ROS client or write. Separation is checked for the explicit
kinematic model only; limited COLREG-inspired geometric checks are NOT a legal
compliance certificate or an operational navigation system.
"""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat
import unicodedata

from lotusim_image_generator.traffic import planner as traffic
from lotusim_image_generator.campaigns.settings import CampaignStore, load_json_bytes
from lotusim_image_generator.engines.contract import CLASS_IDS
from lotusim_image_generator.campaigns.schedule import (
    build_schedule,
    legacy_count_schedule,
    legacy_frame_schedule,
    validate_plan_schedule,
    summary as capture_summary,
)

REFERENCES = [
    {
        'title': 'IMO — COLREG convention, scope of Rules 11–19',
        'url': 'https://www.imo.org/en/about/conventions/pages/colreg.aspx',
    },
    {
        'title': 'USCG Navigation Center — International Rules 13–17 and 19',
        'url': 'https://www.navcen.uscg.gov/navigation-rules-amalgamated',
    },
    {
        'title': 'USCG Navigation Rules Handbook — International Rules 13–17',
        'url': 'https://www.navcen.uscg.gov/sites/default/files/pdf/navRules/Handbook/Nav%20Rules%20Handbook_Corrected_08-12-2024.pdf',
    },
]
LIMITATIONS = [
    'Zone de pleine mer synthétique, sans carte nautique, bathymétrie, dispositif de séparation, veille ou radar.',
    'La vérification continue porte uniquement sur les trajectoires déclarées à altitude constante et les virages bornés, avec des enveloppes de coque circulaires conservatrices.',
    'Trajectoires négociées avant lancement, sans évitement réactif des objets inconnus ou déviants.',
    'Contrôles géométriques COLREG partiels : passage bâbord à bâbord, croisement par l’arrière et distance de dépassement. Les manœuvres et l’ensemble des règles 13 à 17 ne sont pas certifiés.',
    'Voile, pêche ou statuts incertains, responsabilités de la règle 18, visibilité restreinte de la règle 19, feux, signaux et autres obligations ne sont pas évalués réglementairement.',
    'Vitesses, restrictions liées à la mer et dimensions proviennent du catalogue ; ce ne sont pas des performances certifiées.',
    'Le scénario YAML est exporté sans lancement. La présence des modèles et le rendu dans un moteur restent à vérifier avec son adaptateur.',
]
_ID = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,79}$')
_MODEL = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
_POWER = {'observer', 'container_ship', 'motor_yacht', 'speedboat', 'jetski', 'ferry'}


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')
        ).encode()
    ).hexdigest()


def _number(value, lo, hi, integer=False):
    return (
        type(value) in (int, float)
        and lo <= value <= hi
        and math.isfinite(value)
        and (not integer or type(value) is int)
    )


def _read(core, relative):
    descriptor = os.open(str(core), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split('/')
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1048576:
                raise ValueError('Expected a bounded regular scenario source')
            return load_json_bytes(stream.read(1048577))
    finally:
        os.close(descriptor)


def _request(request):
    fields = {'name', 'seed', 'durationSeconds', 'actionProfile'}
    optional = {'campaign', 'blockId', 'speedPolicy', 'headingPolicy', 'capture'}
    if (
        not isinstance(request, dict)
        or not fields <= set(request)
        or set(request) - fields - optional
    ):
        raise ValueError(
            'Expected name, seed, durationSeconds and actionProfile; unsupported request field'
        )
    name = request['name']
    if (
        not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 80
        or any(unicodedata.category(c).startswith('C') for c in name)
    ):
        raise ValueError('Scenario name must contain 1–80 printable characters')
    if not _number(request['seed'], 0, 2147483647, True):
        raise ValueError('Seed must be a nonnegative int32')
    if not _number(request['durationSeconds'], 4, 600):
        raise ValueError('Duration must be 4–600 seconds')
    if request['actionProfile'] not in ('open_water', 'crossing', 'parallel'):
        raise ValueError('Unknown actionProfile')
    if request.get('speedPolicy', 'catalogue') not in ('catalogue', 'requested') or request.get(
        'headingPolicy', 'profile'
    ) not in ('profile', 'requested'):
        raise ValueError('Unknown speedPolicy or headingPolicy')
    result = copy.deepcopy(request)
    result['name'] = name.strip()
    result.setdefault('speedPolicy', 'catalogue')
    result.setdefault('headingPolicy', 'profile')
    if result.get('blockId') is not None and not isinstance(result['blockId'], str):
        raise ValueError('blockId must be text')
    if 'campaign' in result and not isinstance(result['campaign'], dict):
        raise ValueError('campaign must be a validated campaign object')
    if 'campaign' not in result and (
        result['speedPolicy'] == 'requested' or result['headingPolicy'] == 'requested'
    ):
        raise ValueError('Requested speed/heading policies require a campaign block')
    if 'capture' in result:
        build_schedule(result['capture'], result['durationSeconds'], 30)
    return result


def _template(campaign=None):
    camera = campaign['camera'] if campaign else {}
    return {
        'origin': traffic.vec([0, 0, 0]),
        'width': camera.get('width', 3840),
        'height': camera.get('height', 2160),
        'verticalFovDeg': camera.get('verticalFovDeg', 55),
        'farClipM': camera.get('farClipM', 80000),
        'viewHeadingDeg': 0,
        'observerDeckCamera': True,
        'observerHeightM': 12.4,
        'observerDeckOffsetM': traffic.vec([30.3, 12.4, -5.5]),
        'classes': [
            {'category': key, 'classId': value}
            for key, value in sorted(CLASS_IDS.items(), key=lambda p: p[1])
        ],
    }


def _inputs(core, unity, request):
    store = CampaignStore(core, unity)
    campaign = request.get('campaign')
    selected = None
    if campaign is not None:
        valid = store.validate(campaign)
        if not valid['valid']:
            raise ValueError(
                'Invalid campaign: '
                + '; '.join(error['path'] + ' ' + error['message'] for error in valid['errors'][:3])
            )
        campaign = valid['campaign']
        blocks = campaign['blocks']
        if len(blocks) > 1 and not request.get('blockId'):
            raise ValueError(
                'Choose blockId explicitly: one continuous scenario cannot silently merge independent image blocks'
            )
        selected = next(
            (block for block in blocks if block['id'] == request.get('blockId', blocks[0]['id'])),
            None,
        )
        if selected is None:
            raise ValueError('Unknown campaign blockId')
        catalogue = store._catalogue(campaign['engine'])
    else:
        if request.get('blockId') is not None:
            raise ValueError('blockId requires a campaign')
        catalogue = _read(core, 'assets/scenarios/catalogs/traffic_assets.json')
    scope = {
        'schema': traffic.SCHEMA,
        'name': 'Coop_' + _hash(request)[:16],
        'seed': request['seed'],
        'durationSeconds': request['durationSeconds'],
        'fps': 30,
        'captureEveryFrames': 15,
        'countPerModel': 1,
        'maxPlanningAttempts': 192,
        'observer': {'speedKnots': 12, 'headingDeg': 0, 'turnDeg': 0},
        'weather': {
            'localWindMps': 6,
            'windTowardsDeg': 55,
            'significantSwellHeightM': 1.2,
            'swellSpectrumProxyWindKmh': [52, 72],
        },
        'water': {
            'eastMinM': -10000,
            'eastMaxM': 10000,
            'northMinM': -10000,
            'northMaxM': 45000,
            'exclusionZones': [],
        },
        'safety': {
            'seaClearanceM': 30,
            'observerBufferM': 90,
            'aircraftHorizontalM': 500,
            'aircraftVerticalM': 300,
            'observerAuditStepSeconds': 0.5,
            'planningMarginM': 5,
            'runtimePositionToleranceM': 0.5,
        },
        'overrides': [],
        'fastDrones': {'enabled': False},
        'cooperativeRequest': {
            'displayName': request['name'],
            'actionProfile': request['actionProfile'],
            'speedPolicy': request['speedPolicy'],
            'headingPolicy': request['headingPolicy'],
            'blockId': selected['id'] if selected else None,
            'placements': {},
        },
        'colregAssumptions': {'vesselsInSightAssumed': True, 'restrictedVisibilityAssessed': False},
    }
    template = _template(campaign)
    if selected:
        environment = selected['environment']
        if environment['waveHeightM'] > 6:
            raise ValueError(
                'Requested wave height exceeds the 6 m cooperative safety model; no silent clipping'
            )
        scope['weather'].update(
            localWindMps=environment['windMps'],
            windTowardsDeg=environment['waveDirectionDeg'],
            significantSwellHeightM=environment['waveHeightM'],
        )
        scope['environmentRequested'] = copy.deepcopy(environment)
        scope['colregAssumptions']['vesselsInSightAssumed'] = environment['rainIntensity'] == 0
        observer = campaign['observer']
        scope['observer'].update(
            speedKnots=observer['speedMps'] / traffic.KNOT, headingDeg=observer['headingDeg']
        )
        template['viewHeadingDeg'] = (
            observer['headingDeg'] + campaign['camera']['viewHeadingDeg']
        ) % 360
        template['cameraPitchDeg'] = campaign['camera']['viewDownPitchDeg']
    # Normalize capability records without guessing absent geometry.
    normalized = []
    selected_models = {row['model'] for row in selected['objects']} if selected else None
    for original in catalogue.get('assets', []):
        if selected_models is not None and original['model'] not in selected_models:
            continue
        item = copy.deepcopy(original)
        if not all(_number(item.get(key), 0.001, 1000) for key in ('lengthM', 'beamM', 'heightM')):
            raise ValueError(
                'Missing/invalid physical dimensions for ' + item.get('model', 'asset')
            )
        item.setdefault('bufferM', max(8, min(200, item['lengthM'] * 0.8)))
        item.setdefault('priority', 5)
        item.setdefault('evidence', 'catalogue_assumption')
        lo = traffic.mps(item.get('speedMin', 0), item.get('speedUnit', 'mps'))
        hi = traffic.mps(item.get('speedMax', item['maxSpeedMps']), item.get('speedUnit', 'mps'))
        cap = item['maxSpeedMps']
        if item['domain'] == 'sea' and item['lengthM'] < 15:
            cap = min(
                cap,
                max(
                    5,
                    (24 if item['category'] == 'jetski' else 30)
                    - 8 * scope['weather']['significantSwellHeightM'],
                )
                * traffic.KNOT,
            )
        item.update(speedUnit='mps', speedMin=min(lo, cap), speedMax=min(hi, cap))
        if item['domain'] == 'air' and item.get('altitudeM', [0, 0])[0] <= 0:
            ceiling = item.get('maxAltitudeM', 0)
            item['altitudeM'] = [min(30, ceiling), min(80, ceiling)]
        if selected:
            rows = [row for row in selected['objects'] if row['model'] == item['model']]
            count = sum(row['count'] for row in rows)
            ranges = [row['distanceM'] for row in rows]
            heights = [row['altitudeM'] for row in rows]
            item['rangeM'] = [min(ranges), max(ranges)]
            item['altitudeM'] = [min(heights), max(heights)]
            if min(ranges) < 50:
                raise ValueError(
                    'Cooperative planning requires at least 50 m nominal range; no silent displacement'
                )
            if request['speedPolicy'] == 'requested':
                speeds = [row['speedMps'] for row in rows]
                item.update(speedMin=min(speeds), speedMax=max(speeds))
            # A campaign racer is an ordinary unarmed visual actor, not the special pass recipe.
            item.pop('role', None)
            scope['overrides'].append({'model': item['model'], 'count': count})
            index = 0
            for row in rows:
                for copy_index in range(row['count']):
                    index += 1
                    scope['cooperativeRequest']['placements'][
                        item['model'] + '_' + str(index).zfill(3)
                    ] = dict(copy.deepcopy(row), copyIndex=copy_index, sourceRowId=row['id'])
        normalized.append(item)
    catalogue = dict(catalogue, assets=normalized)
    if not selected:
        fast = next((item for item in normalized if item.get('role') == 'fast_flyby'), None)
        if fast:
            scope['fastDrones'] = {
                'enabled': True,
                'model': fast['model'],
                'minCameraDistanceM': 80,
                'turnAngleDeg': 40,
                'turnDurationSeconds': 8,
                'captureHz': 10,
                'captureBurstSeconds': 3,
                'passes': [
                    {'kind': 'crossing', 'speedKmh': speed, 'focusFraction': fraction, 'side': side}
                    for speed, fraction, side in [
                        (60, 0.1, -1),
                        (180, 0.25, 1),
                        (240, 0.4, 1),
                        (300, 0.55, -1),
                        (400, 0.7, -1),
                        (400, 0.85, 1),
                    ]
                ],
            }
    return scope, catalogue, template, selected


def _course(route):
    velocity = traffic.velocity_at(route, 0)
    return math.degrees(math.atan2(velocity[0], velocity[2])) % 360


def _profile_course(profile, index, heading):
    if profile == 'parallel':
        return heading
    if profile == 'crossing':
        return (heading + (90 if index % 2 else -90)) % 360
    return (heading + [0, 180, 85, -85][index % 4]) % 360


def _limited_colreg(routes, safety, scope):
    checks, excluded = [], []
    in_sight = scope.get('colregAssumptions', {}).get('vesselsInSightAssumed') is True
    for index, a in enumerate(routes):
        for b in routes[index + 1 :]:
            if a['profile']['domain'] != 'sea' or b['profile']['domain'] != 'sea':
                continue
            if not in_sight or any(route['profile']['category'] not in _POWER for route in (a, b)):
                excluded.append(
                    {
                        'a': a['instance'],
                        'b': b['instance'],
                        'reason': (
                            'Rule19_not_assessed'
                            if not in_sight
                            else 'sailing_fishing_or_uncertain_status'
                        ),
                    }
                )
                continue
            if any(abs(route.get('yawRateDegS', 0)) > 1e-9 for route in (a, b)):
                excluded.append(
                    {
                        'a': a['instance'],
                        'b': b['instance'],
                        'reason': 'curved_rule_manoeuvre_not_assessed',
                    }
                )
                continue
            cpa = safety.pair(a, b)
            if (
                cpa['timeSeconds'] <= 0
                or cpa.get('distanceLowerBoundM', math.inf) > cpa.get('requiredM', 0) * 3
            ):
                continue
            pa, pb = traffic.position(a, 0), traffic.position(b, 0)
            va, vb = a['velocity'], b['velocity']
            ha, hb = _course(a), _course(b)
            if min(traffic.norm(va), traffic.norm(vb)) < 0.01:
                continue
            delta = traffic.minus(pb, pa)
            angle = abs((ha - hb + 180) % 360 - 180)
            ahead_a = traffic.dot(delta, traffic.bearing(ha)) > 0
            ahead_b = traffic.dot(traffic.times(delta, -1), traffic.bearing(hb)) > 0
            if angle >= 165 and ahead_a and ahead_b:
                at = cpa['timeSeconds']
                separation = traffic.minus(traffic.position(b, at), traffic.position(a, at))
                ports = (
                    traffic.dot(separation, traffic.bearing(ha + 90)) <= 0
                    and traffic.dot(traffic.times(separation, -1), traffic.bearing(hb + 90)) <= 0
                )
                checks.append(
                    {
                        'a': a['instance'],
                        'b': b['instance'],
                        'rule': '14',
                        'control': 'planned_port_to_port_starboard_side_routing',
                        'passed': ports,
                        'manoeuvreVerified': False,
                        'detail': 'Pre-separated geometry only; no claim of an early starboard alteration.',
                    }
                )
                continue
            # An overtaker remains responsible for clearance; no crossing reclassification.
            overtaker = None
            for follower, leader in ((a, b), (b, a)):
                relative = traffic.minus(traffic.position(follower, 0), traffic.position(leader, 0))
                bearing_to_follower = math.degrees(math.atan2(relative[0], relative[2])) % 360
                astern = abs((bearing_to_follower - _course(leader) + 180) % 360 - 180) > 112.5
                closing = (
                    traffic.dot(
                        traffic.minus(follower['velocity'], leader['velocity']),
                        traffic.times(relative, -1),
                    )
                    > 0
                )
                if astern and closing and angle < 67.5:
                    overtaker = follower['instance']
                    break
            if overtaker:
                checks.append(
                    {
                        'a': a['instance'],
                        'b': b['instance'],
                        'rule': '13',
                        'control': 'overtaker_keep_clear',
                        'giveWay': overtaker,
                        'passed': cpa['safe']
                        and cpa['marginM'] >= scope['safety']['planningMarginM'],
                    }
                )
                continue
            det = va[0] * vb[2] - va[2] * vb[0]
            if abs(det) < 1e-8:
                continue
            ta = (delta[0] * vb[2] - delta[2] * vb[0]) / det
            tb = (delta[0] * va[2] - delta[2] * va[0]) / det
            if not 0 <= ta <= safety.duration or not 0 <= tb <= safety.duration:
                continue
            a_yields = traffic.dot(delta, traffic.bearing(ha + 90)) > 0
            checks.append(
                {
                    'a': a['instance'],
                    'b': b['instance'],
                    'rule': '15/16',
                    'control': 'crossing_give_way_astern',
                    'giveWay': a['instance'] if a_yields else b['instance'],
                    'passed': ta > tb if a_yields else tb > ta,
                    'arrivalASeconds': ta,
                    'arrivalBSeconds': tb,
                    'manoeuvreVerified': False,
                }
            )
    return {
        'approved': all(check['passed'] for check in checks),
        'checks': checks,
        'excludedPairs': excluded,
        'fullColregCompliance': False,
        'notCertified': True,
        'vesselsInSightAssumed': in_sight,
        'encounterGate': 'Future CPA inside three conservative clearance radii; engineering filter, not legal risk definition',
        'references': REFERENCES,
    }


def _route_policy(scope):
    def check(proposal, reserved, safety):
        for other in reserved:
            audit = _limited_colreg([proposal, other], safety, scope)
            if not audit['approved']:
                return {'b': other['instance'], 'reason': 'limited_colreg_geometry'}
        return None

    return check


def _transform(scope):
    profile = scope['cooperativeRequest']['actionProfile']

    def apply(route, asset):
        if asset['domain'] != 'sea' or profile == 'open_water':
            return route
        index = int(_hash(asset['instance'])[:4], 16)
        course = _profile_course(profile, index, scope['observer']['headingDeg'])
        if asset['category'] == 'sailboat':
            wind_from = (scope['weather']['windTowardsDeg'] + 180) % 360
            if abs((course - wind_from + 180) % 360 - 180) < 40:
                course = (course + 180) % 360
        route['velocity'] = traffic.times(traffic.bearing(course), route['groundSpeedMps'])
        route['courseDeg'] = course
        return route

    return apply


def _routes(plan, scope, catalogue, template):
    board = traffic.Blackboard()
    profiles = traffic.CatalogueAgent().run(scope, catalogue, template, board)
    observer = traffic.ObserverAgent(scope, template)
    by_id = {item['instance']: item for item in profiles}
    if (
        not isinstance(plan, dict)
        or plan.get('schema') != 'lotusim-unity-encounters-1'
        or plan.get('containsUncompiledControlPoints')
        or plan.get('requiresNativeAdapter')
    ):
        raise ValueError('Unsupported plan or uncompiled control points; no continuous approval')
    events = plan.get('events')
    if not isinstance(events, list) or len(events) != len(profiles) or len(events) > 40:
        raise ValueError('Event count does not match the immutable scope')
    routes, seen = [observer.route], set()
    for event in events:
        if (
            not isinstance(event, dict)
            or 'controlPoints' in event
            or event.get('trajectoryKind') == 'piecewise_linear'
        ):
            raise ValueError('Control-point trajectories require a separate continuous solver')
        identifier = event.get('instance')
        profile = by_id.get(identifier)
        if (
            profile is None
            or identifier in seen
            or event.get('modelName') != profile['model']
            or event.get('category') != profile['category']
        ):
            raise ValueError('Unknown, duplicated or mismatched actor identity')
        seen.add(identifier)
        center, velocity = [], []
        for field, destination in (('centerPosition', center), ('velocity', velocity)):
            value = event.get(field)
            if (
                not isinstance(value, dict)
                or set(value) != {'x', 'y', 'z'}
                or any(not _number(value[key], -100000, 100000) for key in ('x', 'y', 'z'))
            ):
                raise ValueError('Invalid finite actor vector')
            destination.extend(value[key] for key in ('x', 'y', 'z'))
        if abs(velocity[1]) > 1e-9:
            raise ValueError(
                'Changing altitude is unsupported by the constant-height separation proof'
            )
        if (
            not all(
                _number(event.get(key), 0, scope['durationSeconds'])
                for key in ('startSeconds', 'endSeconds', 'centerSeconds')
            )
            or event['startSeconds'] > event['endSeconds']
        ):
            raise ValueError('Invalid event time interval')
        speed = traffic.norm(velocity)
        if speed > profile['safeMaximumMps'] + 1e-6 or (
            profile['domain'] == 'moored' and speed > 1e-9
        ):
            raise ValueError('Speed exceeds the catalogue/sea-state capability')
        if profile['domain'] != 'air' and abs(center[1]) > 1e-8:
            raise ValueError('Sea and moored objects must stay at the waterline')
        if profile['domain'] == 'air' and not 0 < center[1] <= profile['maxAltitudeM']:
            raise ValueError('Aircraft exceeds its positive altitude/ceiling')
        if (
            profile['domain'] == 'air'
            and speed + scope['weather']['localWindMps'] > profile['maxSpeedMps'] + 1e-6
        ):
            raise ValueError('Conservative wind-relative airspeed cap exceeded')
        yaw = event.get('yawRateDegS', 0)
        if not _number(yaw, -5, 5):
            raise ValueError('Yaw rate exceeds bounded kinematic model')
        route = {
            'instance': identifier,
            'profile': profile,
            'center': center,
            'velocity': velocity,
            'focus': event['centerSeconds'],
            'yawRateDegS': yaw,
            'startSeconds': event['startSeconds'],
            'endSeconds': event['endSeconds'],
        }
        if event.get('boundedTurn'):
            lo, hi = event.get('turnStartSeconds'), event.get('turnEndSeconds')
            if (
                not _number(lo, 0, scope['durationSeconds'])
                or not _number(hi, 0, scope['durationSeconds'])
                or lo >= hi
                or abs(yaw) * (hi - lo) > 45.000001
            ):
                raise ValueError('Invalid bounded turn interval')
            route.update(boundedTurn=True, turnStartSeconds=lo, turnEndSeconds=hi)
        elif abs(yaw) > 0 and abs(yaw) * scope['durationSeconds'] > 45:
            raise ValueError('Unbounded large-turn trajectories are unsupported')
        routes.append(route)
    return routes, observer


def revalidate_plan(plan, scope, catalogue, template):
    """Audit the supplied motion, never re-plan or trust a previous approval."""
    result = {
        'schema': 'lotusim-cooperative-scenario-audit-1',
        'approved': False,
        'continuousSafetyApproved': False,
        'fullColregCompliance': False,
        'notCertified': True,
        'checks': [],
        'pairChecks': 0,
        'errors': [],
        'limitations': list(LIMITATIONS),
        'references': REFERENCES,
    }
    try:
        if not isinstance(plan, dict):
            raise ValueError('Expected a kinematic plan object')
        capture_schedule = validate_plan_schedule(plan, scope)
        routes, observer = _routes(plan, scope, catalogue, template)
        safety = traffic.SafetyAgent(scope, observer)
        for route in routes:
            if not safety.geofence(route):
                result['errors'].append('Geofence failed for ' + route['instance'])
            if route['profile'].get('role') == 'fast_flyby':
                minimum = (
                    scope['fastDrones']['minCameraDistanceM'] + scope['safety']['planningMarginM']
                )
                if safety.camera_clearance(route) < minimum:
                    result['errors'].append(
                        'Observer camera standoff failed for ' + route['instance']
                    )
            if abs(route.get('yawRateDegS', 0)) > 0 and route['profile']['domain'] != 'air':
                count = math.ceil(scope['durationSeconds'] / 0.5)
                pad = traffic.norm(route['velocity']) * scope['durationSeconds'] / count / 2
                radius = route['profile']['lengthM'] / 2 + route['profile']['bufferM'] + pad
                for index in range(count + 1):
                    point = traffic.position(route, index * scope['durationSeconds'] / count)
                    water = scope['water']
                    if (
                        not water['eastMinM'] + radius <= point[0] <= water['eastMaxM'] - radius
                        or not water['northMinM'] + radius
                        <= point[2]
                        <= water['northMaxM'] - radius
                        or any(
                            math.hypot(point[0] - zone['eastM'], point[2] - zone['northM'])
                            < zone['radiusM'] + radius
                            for zone in water.get('exclusionZones', [])
                        )
                    ):
                        result['errors'].append(
                            'Conservative curved geofence failed for ' + route['instance']
                        )
                        break
        checks = [safety.pair(a, b) for index, a in enumerate(routes) for b in routes[index + 1 :]]
        continuous = not result['errors'] and all(
            check['safe'] and check['marginM'] >= scope['safety']['planningMarginM']
            for check in checks
        )
        colreg = _limited_colreg(routes, safety, scope)
        result.update(
            continuousSafetyApproved=continuous,
            limitedColreg=colreg,
            checks=checks,
            pairChecks=len(checks),
            actors=len(routes) - 1,
            minimumMarginM=min(check['marginM'] for check in checks),
            approved=continuous and colreg['approved'],
            status='approved_limited' if continuous and colreg['approved'] else 'unsafe',
        )
        motion = {key: plan.get(key) for key in ('schema', 'seed', 'maxActive', 'events')}
        result['inputSha256'] = _hash(
            {'plan': motion, 'scope': scope, 'catalogue': catalogue, 'template': template}
        )
        result['motionSha256'] = _hash(
            {
                'plan': motion,
                'observer': scope['observer'],
                'durationSeconds': scope['durationSeconds'],
                'template': template,
            }
        )
        if capture_schedule:
            result['captureScheduleSha256'] = capture_schedule['sha256']
            result['captureScheduleValidated'] = True
            result['plannedCaptureImages'] = capture_schedule['count']
    except (ValueError, KeyError, TypeError, OverflowError, ArithmeticError) as error:
        result.update(status='unsupported', errors=[str(error)[:240]])
    return result


audit_plan = revalidate_plan


def _campaign_plan(scope, catalogue, template, attempt):
    board = traffic.Blackboard()
    profiles = traffic.CatalogueAgent().run(scope, catalogue, template, board)
    observer = traffic.ObserverAgent(scope, template)
    safety = traffic.SafetyAgent(scope, observer)
    reserved, events, decisions = [observer.route], [], []
    spec = scope['cooperativeRequest']
    duration = scope['durationSeconds']
    focus = duration / 2
    for index, profile in enumerate(profiles):
        row = spec['placements'][profile['instance']]
        rng = random.Random(int(_hash([scope['seed'], attempt, profile['instance']])[:16], 16))
        board.send('Orchestrator', profile['instance'], 'plan_request', actor=profile['instance'])
        for retry in range(192):
            fraction = (
                (row['copyIndex'] + 0.15 + 0.7 * rng.random()) / row['count']
                if row['count'] > 1
                else rng.random()
            )
            angular = (fraction - 0.5) * row['spreadDeg']
            bearing = template['viewHeadingDeg'] + row['bearingDeg'] + angular
            center = traffic.plus(
                observer.eye(focus), traffic.times(traffic.bearing(bearing), row['distanceM'])
            )
            center[1] = row['altitudeM']
            speed = (
                row['speedMps']
                if spec['speedPolicy'] == 'requested'
                else rng.uniform(profile['minimumMps'], profile['safeMaximumMps'])
            )
            course = (
                row['headingDeg']
                if spec['headingPolicy'] == 'requested'
                else _profile_course(spec['actionProfile'], index, scope['observer']['headingDeg'])
            )
            route = {
                'instance': profile['instance'],
                'profile': profile,
                'center': center,
                'velocity': traffic.times(traffic.bearing(course), speed),
                'focus': focus,
            }
            conflict = safety.check(route, reserved)
            if conflict is None:
                conflict = _route_policy(scope)(route, reserved, safety)
            if conflict:
                board.send(
                    'SafetyAgent',
                    profile['instance'],
                    'yield_or_relocate',
                    actor=profile['instance'],
                    attempt=retry,
                    reason='requested_range_or_heading_conflict',
                    giveWayTo=conflict.get('b'),
                )
                continue
            reserved.append(route)
            events.append(
                {
                    'instance': profile['instance'],
                    'modelName': profile['model'],
                    'category': profile['category'],
                    'classIndex': profile['classIndex'],
                    'trackId': index + 1,
                    'startSeconds': 0,
                    'endSeconds': duration,
                    'centerSeconds': focus,
                    'distanceRequestedM': row['distanceM'],
                    'altitudeM': center[1],
                    'centerPosition': traffic.vec(center),
                    'velocity': traffic.vec(route['velocity']),
                    'phase': index * 0.7,
                }
            )
            decisions.append(
                {
                    'instance': profile['instance'],
                    'model': profile['model'],
                    'requestedSpeedMps': row['speedMps'],
                    'actualSpeedMps': speed,
                    'requestedHeadingDeg': row['headingDeg'],
                    'actualHeadingDeg': course,
                    'distanceM': row['distanceM'],
                    'sourceRowId': row['sourceRowId'],
                    'speedPolicy': spec['speedPolicy'],
                    'headingPolicy': spec['headingPolicy'],
                }
            )
            board.send(
                profile['instance'], 'Orchestrator', 'route_reserved', actor=profile['instance']
            )
            break
        else:
            raise ValueError(
                'No safe route within the EXACT requested distance/spread for '
                + profile['instance']
                + '; increase distance/spread or reduce counts'
            )
    return {
        'schema': 'lotusim-unity-encounters-1',
        'motionSource': 'LOTUSim cooperative preplanned traffic; no reactive navigation',
        'northAxis': 'Unity +Z',
        'eastAxis': 'Unity +X',
        'seed': scope['seed'],
        'maxActive': len(events),
        'events': events,
        'traffic': {
            'continuousSafetyApproved': False,
            'fullColregCompliance': False,
            'reactiveAvoidance': False,
            'actorProfiles': decisions,
        },
    }, {'schema': 'lotusim-agent-negotiation-1', 'messages': board.messages}


def render_scenario_yaml(plan, scope, template, catalogue=None):
    """Write-compatible LOTUSim trajectory text, never import or launch it."""
    catalogue = catalogue or scope.get('catalogueSnapshot')
    if catalogue is None:
        raise ValueError(
            'A trusted catalogue snapshot is required for independent YAML export audit'
        )
    audit = revalidate_plan(plan, scope, catalogue, template)
    if not audit['approved']:
        raise ValueError('Unsafe or unsupported plan: executable scenario export refused')
    lines = [
        '# Offline cooperative export; limited kinematic audit, NOT certified COLREG navigation.',
        'name: ' + scope['name'],
        'description: '
        + json.dumps(
            'Preplanned kinematic traffic; no reactive avoidance or calibrated wave dynamics.'
        ),
        'reference_position: {latitude: 1.2421, longitude: 103.7198, altitude: 0}',
        'dataset_sequence:',
        '  plan_id: ' + audit['inputSha256'],
        '  observer: ObserverBoat',
        '  fps: ' + str(scope['fps']),
        '  frames: ' + str(math.ceil(scope['durationSeconds'] * scope['fps'])),
    ]
    schedule = plan.get('captureSchedule')
    if schedule:
        lines += [
            '# Capture metadata uses simulated seconds; no wall-clock timer or hidden burst.',
            'capture_schedule:',
            '  schema: ' + schedule['schema'],
            '  mode: ' + schedule['mode'],
            '  source: ' + schedule['source'],
            '  clock: simulated_seconds',
            '  duration_seconds: ' + repr(schedule['durationSeconds']),
            '  fps: ' + str(schedule['fps']),
            '  count: ' + str(schedule['count']),
            '  frames: ' + json.dumps(schedule['frames']),
            '  sha256: ' + schedule['sha256'],
        ]
        if schedule['requestedIntervalSeconds'] is not None:
            lines += ['  interval_seconds: ' + repr(schedule['requestedIntervalSeconds'])]
    lines += ['agents:']
    routes, _ = _routes(plan, scope, catalogue, template)
    for route in routes:
        observer = route.get('observer', False)
        model = 'fremm_observer' if observer else route['profile']['model']
        if not _ID.fullmatch(route['instance']) or not _MODEL.fullmatch(model):
            raise ValueError('Unsafe model/actor identifier')

        def vector(value):
            return json.dumps([value[0], value[2], value[1]], allow_nan=False)

        heading = 90 - math.degrees(math.atan2(route['velocity'][0], route['velocity'][2]))
        lines += [
            '  ' + route['instance'] + ':',
            '    model: ' + model,
            '    heading: ' + repr(heading),
            '    render_interface: {enabled: '
            + ('false' if observer else 'true')
            + ', renderer_type: '
            + model
            + '}',
            '    trajectory:',
            '      center_enu_m: ' + vector(route['center']),
            '      velocity_enu_mps: ' + vector(route['velocity']),
            '      center_seconds: ' + repr(route['focus']),
            '      start_seconds: ' + repr(route.get('startSeconds', 0)),
            '      end_seconds: ' + repr(route.get('endSeconds', scope['durationSeconds'])),
        ]
        if route.get('yawRateDegS'):
            lines += ['      yaw_rate_deg_s: ' + repr(-route['yawRateDegS'])]
        if route.get('boundedTurn'):
            lines += [
                '      turn_start_seconds: ' + repr(route['turnStartSeconds']),
                '      turn_end_seconds: ' + repr(route['turnEndSeconds']),
            ]
    return '\n'.join(lines) + '\n'


def generate(core_root, unity_root, request):
    request = _request(request)
    core = Path(core_root).resolve()
    scope, catalogue, template, block = _inputs(core, unity_root, request)
    last = None
    for attempt in range(8):
        try:
            if block:
                plan, messages = _campaign_plan(scope, catalogue, template, attempt)
            else:
                # Reuse the existing cooperative specialists and reservation planner.
                candidate_scope = copy.deepcopy(scope)
                candidate_scope['seed'] = (scope['seed'] + 7919 * attempt) % 2147483648
                plan, _, messages = traffic.Orchestrator().plan(
                    candidate_scope,
                    catalogue,
                    template,
                    route_policy=_route_policy(scope),
                    route_transform=_transform(scope),
                )
            audit = revalidate_plan(plan, scope, catalogue, template)
            if not audit['approved']:
                last = 'Continuous safety or limited encounter geometry did not pass'
                continue
            plan.setdefault('traffic', {}).update(
                continuousSafetyApproved=True,
                fullColregCompliance=False,
                notCertified=True,
                reactiveAvoidance=False,
                scenarioName=scope['name'],
            )
            if 'capture' in request:
                schedule = build_schedule(
                    request['capture'], scope['durationSeconds'], scope['fps']
                )
            elif block:
                schedule = legacy_count_schedule(
                    block['images'], scope['durationSeconds'], scope['fps']
                )
            else:
                frames = plan.get(
                    'captureFrames',
                    list(
                        range(
                            0,
                            math.ceil(scope['durationSeconds'] * scope['fps']),
                            scope['captureEveryFrames'],
                        )
                    ),
                )
                schedule = legacy_frame_schedule(frames, scope['durationSeconds'], scope['fps'])
            plan['captureFrames'] = list(schedule['frames'])
            plan['captureSchedule'] = copy.deepcopy(schedule)
            scope['captureSchedule'] = copy.deepcopy(schedule)
            plan['traffic'].update(
                captureScheduleVersion=1, requestedCaptureImages=schedule['count']
            )
            if block:
                plan['traffic'].update(
                    campaignBlockImagesRequested=block['images'],
                    requestedRangeSemantics='Exact horizontal camera range at each actor centerSeconds, not every moving-episode frame',
                )
            # Stored snapshots make three-argument YAML re-export independently auditable.
            scope['catalogueSnapshot'] = copy.deepcopy(catalogue)
            audit = revalidate_plan(plan, scope, catalogue, template)
            scenario = render_scenario_yaml(plan, scope, template, catalogue)
            return {
                'schema': 'lotusim-generated-cooperative-scenario-1',
                'name': request['name'],
                'request': request,
                'plan': plan,
                'scope': scope,
                'catalogue': catalogue,
                'template': template,
                'audit': audit,
                'messages': messages,
                'scenarioYaml': scenario,
                'captureSummary': capture_summary(schedule),
                'warnings': list(LIMITATIONS),
                'engineId': request.get('campaign', {}).get('engine')
                or CampaignStore(core, unity_root).engine_registry.selection()['id'],
                'generationAttempts': attempt + 1,
                'fullColregCompliance': False,
                'notCertified': True,
            }
        except (ValueError, RuntimeError) as error:
            last = str(error)
            if block and 'EXACT requested' in last:
                break
    raise ValueError(
        'No approved cooperative plan was produced: ' + (last or 'constraints are infeasible')[:300]
    )
