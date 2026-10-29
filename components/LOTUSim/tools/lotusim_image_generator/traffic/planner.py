#!/usr/bin/env python3
# SPDX-License-Identifier: EPL-2.0
"""Deterministic cooperative planning agents for a synthetic LOTUSim episode.

Standard library only. No LLM, credentials, remote calls or simulator writes.
Agents negotiate complete routes; a separate validator proves clearance for the
bounded constant-velocity/constant-turn model. This is not a navigation system.
Coordinates in plans are Unity metres: X east, Y up, Z north.
"""

import argparse
import copy
import hashlib
import html
import json
import math
import pathlib
import random
import re

from lotusim_image_generator.traffic.kinematics import (
    KNOT,
    arr,
    bearing,
    dot,
    finite,
    interval,
    minus,
    mps,
    norm,
    plus,
    position,
    times,
    turn_time,
    vec,
    velocity_at,
)

SCHEMA = 'lotusim-traffic-scope-1'


class Blackboard:
    def __init__(self, telemetry=None):
        self.messages = []
        self.routes = []
        self.telemetry = telemetry

    def send(self, sender, recipient, kind, actor='', **payload):
        self.messages.append(
            dict(
                index=len(self.messages),
                sender=sender,
                recipient=recipient,
                kind=kind,
                actor=actor,
                **payload,
            )
        )
        if self.telemetry is not None:
            try:
                self.telemetry(self.messages[-1])
            except Exception:
                pass  # Observation must not change route planning.


class CatalogueAgent:
    def run(self, scope, catalogue, template, board):
        if (
            scope.get('schema') != SCHEMA
            or catalogue.get('schema') != 'lotusim-traffic-catalogue-1'
        ):
            raise ValueError('Unsupported scope/catalogue schema')
        name = scope.get('name', '')
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,63}', name):
            raise ValueError('Unsafe scenario name')
        if not isinstance(scope.get('seed'), int) or not 0 <= scope['seed'] <= 2147483647:
            raise ValueError('Seed must be a nonnegative int32')
        if not finite(scope.get('durationSeconds')) or not 4 <= scope['durationSeconds'] <= 600:
            raise ValueError('Duration must be 4–600 seconds')
        if not isinstance(scope.get('fps'), int) or not 1 <= scope['fps'] <= 60:
            raise ValueError('FPS must be 1–60')
        if (
            not isinstance(scope.get('captureEveryFrames'), int)
            or not 1 <= scope['captureEveryFrames'] <= scope['fps'] * 10
        ):
            raise ValueError('Invalid capture cadence')
        if (
            not isinstance(scope.get('maxPlanningAttempts'), int)
            or not 1 <= scope['maxPlanningAttempts'] <= 1024
        ):
            raise ValueError('Invalid planning attempt bound')
        obs = scope['observer']
        weather = scope['weather']
        safety = scope['safety']
        water = scope['water']
        for item, lo, hi in [
            (obs['speedKnots'], 0, 27),
            (obs['headingDeg'], 0, 359.999),
            (obs['turnDeg'], -20, 20),
            (weather['localWindMps'], 0, 30),
            (weather['windTowardsDeg'], 0, 359.999),
            (weather['significantSwellHeightM'], 0, 6),
            (safety['seaClearanceM'], 10, 500),
            (safety['observerBufferM'], 30, 500),
            (safety['aircraftHorizontalM'], 100, 5000),
            (safety['aircraftVerticalM'], 100, 1000),
            (safety['observerAuditStepSeconds'], 0.05, 2),
            (safety['planningMarginM'], 1, 100),
            (safety['runtimePositionToleranceM'], 0.01, 5),
        ]:
            if not finite(item) or not lo <= item <= hi:
                raise ValueError('Invalid observer/weather/safety setting')
        if not interval(weather['swellSpectrumProxyWindKmh'], 0, 110):
            raise ValueError('Invalid swell proxy')
        if not interval([water['eastMinM'], water['eastMaxM']], -50000, 50000) or not interval(
            [water['northMinM'], water['northMaxM']], -50000, 50000
        ):
            raise ValueError('Invalid open water rectangle')
        for zone in water.get('exclusionZones', []):
            if (
                not all(finite(zone.get(k)) for k in ('eastM', 'northM', 'radiusM'))
                or not 1 <= zone['radiusM'] <= 50000
            ):
                raise ValueError('Invalid no-go disk')
        overrides = scope.get('overrides', [])
        if len({o['model'] for o in overrides}) != len(overrides):
            raise ValueError('Duplicate model override')
        available = {p['model'] for p in catalogue['assets']}
        if len(available) != len(catalogue['assets']) or any(
            o['model'] not in available for o in overrides
        ):
            raise ValueError('Unknown or duplicate model')
        classes = {c['category']: i for i, c in enumerate(template['classes'])}
        profiles = []
        fast = scope.get('fastDrones', {'enabled': False})
        if not isinstance(fast, dict) or not isinstance(fast.get('enabled', False), bool):
            raise ValueError('Invalid fastDrones switch')
        if fast.get('enabled'):
            if (
                fast.get('model') not in available
                or not finite(fast.get('minCameraDistanceM'))
                or not 60 <= fast['minCameraDistanceM'] <= 500
            ):
                raise ValueError('Invalid fast-drone camera clearance/model')
            if not any(
                p['model'] == fast['model']
                and p.get('role') == 'fast_flyby'
                and p['category'] == 'drone'
                and p['domain'] == 'air'
                for p in catalogue['assets']
            ):
                raise ValueError('Fast-drone model requires its own synthetic flyby profile')
            if (
                not finite(fast.get('turnAngleDeg'))
                or not finite(fast.get('turnDurationSeconds'))
                or not 5 <= fast['turnAngleDeg'] <= 45
                or not 2 <= fast['turnDurationSeconds'] <= 20
                or fast['turnAngleDeg'] / fast['turnDurationSeconds'] > 5
            ):
                raise ValueError('Invalid fast-drone bounded turn')
            if (
                not isinstance(fast.get('captureHz'), int)
                or not 1 <= fast['captureHz'] <= scope['fps']
                or scope['fps'] % fast['captureHz']
                or not finite(fast.get('captureBurstSeconds'))
                or not 1 <= fast['captureBurstSeconds'] <= 6
            ):
                raise ValueError('Invalid fast-drone capture burst')
            if not isinstance(fast.get('passes'), list) or not 1 <= len(fast['passes']) <= 10:
                raise ValueError('Expected 1–10 fast-drone passes')
            for passage in fast['passes']:
                if (
                    set(passage) != {'kind', 'speedKmh', 'focusFraction', 'side'}
                    or passage['kind'] not in ('crossing', 'approach_bypass')
                    or not finite(passage['speedKmh'])
                    or not 60 <= passage['speedKmh'] <= 400
                    or not finite(passage['focusFraction'])
                    or not 0.05 <= passage['focusFraction'] <= 0.95
                    or passage['side'] not in (-1, 1)
                ):
                    raise ValueError('Invalid fast-drone pass')
                focus = (
                    round(
                        passage['focusFraction']
                        * scope['durationSeconds']
                        * scope['fps']
                        / scope['captureEveryFrames']
                    )
                    * scope['captureEveryFrames']
                    / scope['fps']
                )
                if (
                    passage['kind'] == 'approach_bypass'
                    and not fast['turnDurationSeconds'] / 2
                    <= focus
                    <= scope['durationSeconds'] - fast['turnDurationSeconds'] / 2
                ):
                    raise ValueError('Episode too short for the requested drone turn')
        for original in catalogue['assets']:
            p = copy.deepcopy(original)
            override = next((o for o in overrides if o['model'] == p['model']), {})
            if set(override) - {
                'model',
                'enabled',
                'count',
                'speedMin',
                'speedMax',
                'altitudeM',
                'rangeM',
            }:
                raise ValueError('Unsupported override field')
            count = override.get('count', scope['countPerModel'])
            if p.get('role') == 'fast_flyby':
                count = (
                    len(fast['passes'])
                    if fast.get('enabled') and fast['model'] == p['model']
                    else 0
                )
                if override.get('count') == 0:
                    count = 0
            if not isinstance(count, int) or not 0 <= count <= 12:
                raise ValueError('Count must be 0–12 per model')
            if not isinstance(override.get('enabled', True), bool):
                raise ValueError('enabled must be boolean')
            if not override.get('enabled', True) or not count:
                continue
            p.update({k: v for k, v in override.items() if k not in ('enabled', 'count')})
            if (
                not re.fullmatch('[a-z][a-z0-9_]{0,63}', p['model'])
                or p['category'] not in classes
                or p['domain'] not in ('air', 'sea', 'moored')
            ):
                raise ValueError('Invalid asset identity/domain')
            if (
                not interval([p['speedMin'], p['speedMax']], 0, 1000)
                or not interval(p['altitudeM'], 0, 15000)
                or not interval(p['rangeM'], 50, 60000)
            ):
                raise ValueError('Invalid ranges: ' + p['model'])
            if (
                any(
                    not finite(p.get(k)) or p[k] <= 0
                    for k in ('lengthM', 'beamM', 'heightM', 'bufferM')
                )
                or not finite(p['maxSpeedMps'])
                or p['maxSpeedMps'] < 0
            ):
                raise ValueError('Invalid dimensions/capabilities')
            p['minimumMps'] = mps(p['speedMin'], p['speedUnit'])
            p['maximumMps'] = mps(p['speedMax'], p['speedUnit'])
            if p['maximumMps'] > p['maxSpeedMps'] + 1e-5:
                raise ValueError('Requested speed exceeds capability: ' + p['model'])
            if p['domain'] == 'moored' and (p['maximumMps'] != 0 or p['altitudeM'] != [0, 0]):
                raise ValueError('Moored markers must be fixed on the water')
            if p['domain'] == 'sea' and p['altitudeM'] != [0, 0]:
                raise ValueError('Ships must remain at their waterline')
            if p['domain'] == 'air' and p['altitudeM'][0] <= 0:
                raise ValueError('Aircraft require positive altitude')
            if p['domain'] == 'air' and (
                not finite(p.get('maxAltitudeM')) or p['altitudeM'][1] > p['maxAltitudeM']
            ):
                raise ValueError('Altitude exceeds the model operational ceiling: ' + p['model'])
            if p.get('maxWindMps', 100) < weather['localWindMps']:
                raise ValueError(
                    'Wind exceeds ' + p['model'] + ' limit; reduce local wind or disable this model'
                )
            # Conservative operational caps, not measurements of these meshes.
            cap = p['maximumMps']
            hs = weather['significantSwellHeightM']
            if p['domain'] == 'sea' and p['lengthM'] < 15:
                cap = min(cap, max(5, (24 if p['category'] == 'jetski' else 30) - 8 * hs) * KNOT)
            if cap < p['minimumMps'] - 1e-6:
                raise ValueError(
                    'No feasible speed in this swell for '
                    + p['model']
                    + '; reduce swell or change operational range'
                )
            p['safeMaximumMps'] = cap
            p['classIndex'] = classes[p['category']]
            for n in range(count):
                item = copy.deepcopy(p)
                item['instance'] = p['model'] + '_' + str(n + 1).zfill(3)
                if p.get('role') == 'fast_flyby':
                    item['pass'] = copy.deepcopy(fast['passes'][n])
                    speed = item['pass']['speedKmh'] / 3.6
                    if not p['minimumMps'] <= speed <= p['safeMaximumMps']:
                        raise ValueError('Fast-drone speed exceeds catalogue capability')
                    if speed + weather['localWindMps'] > p['maxSpeedMps']:
                        raise ValueError(
                            'Fast-drone wind-relative upper bound exceeds synthetic capability'
                        )
                    item['minimumMps'] = item['safeMaximumMps'] = speed
                profiles.append(item)
        if not 1 <= len(profiles) <= 40:
            raise ValueError('Plan requires 1–40 actors plus observer')
        if any(sum(p['category'] == c for p in profiles) > 12 for c in classes):
            raise ValueError('At most 12 instances of each existing class')
        board.send(
            'CatalogueAgent',
            'Orchestrator',
            'scope_validated',
            actors=len(profiles),
            weather=weather,
        )
        return profiles


class ObserverAgent:
    def __init__(self, scope, template):
        self.scope = scope
        self.origin = arr(template.get('origin', vec([0, 0, 0])))
        self.speed = scope['observer']['speedKnots'] * KNOT
        self.heading = math.radians(scope['observer']['headingDeg'])
        self.w = math.radians(scope['observer']['turnDeg']) / scope['durationSeconds']
        self.profile = dict(
            model='fremm_observer',
            category='observer',
            domain='sea',
            lengthM=148,
            beamM=20,
            heightM=40,
            bufferM=scope['safety']['observerBufferM'],
        )
        self.template = template
        self.route = dict(
            instance='ObserverBoat',
            profile=self.profile,
            center=self.origin,
            velocity=times(bearing(scope['observer']['headingDeg']), self.speed),
            focus=0,
            observer=True,
            yawRateDegS=scope['observer']['turnDeg'] / scope['durationSeconds'],
        )

    def at(self, t):
        if abs(self.w) < 1e-9:
            return plus(self.origin, times(bearing(math.degrees(self.heading)), self.speed * t))
        return plus(
            self.origin,
            [
                self.speed
                * (math.cos(self.heading) - math.cos(self.heading + self.w * t))
                / self.w,
                0,
                self.speed
                * (math.sin(self.heading + self.w * t) - math.sin(self.heading))
                / self.w,
            ],
        )

    def eye(self, t):
        point = self.at(t)
        heading = math.degrees(self.heading + self.w * t)
        if self.template.get('observerDeckCamera'):
            o = arr(self.template['observerDeckOffsetM'])
            return plus(
                point,
                plus(
                    times(bearing(heading), o[0]),
                    plus([0, o[1], 0], times(bearing(heading + 90), -o[2])),
                ),
            )
        return plus(point, [0, self.template.get('observerHeightM', 12.4), 0])


class SafetyAgent:
    def __init__(self, scope, observer):
        self.scope = scope
        self.observer = observer
        self.duration = scope['durationSeconds']

    def required(self, a, b):
        pa, pb = a['profile'], b['profile']
        s = self.scope['safety']
        if pa['domain'] != 'air' and pb['domain'] != 'air':
            return (
                0.5 * pa['lengthM']
                + pa['bufferM']
                + 0.5 * pb['lengthM']
                + pb['bufferM']
                + s['seaClearanceM'],
                0,
            )
        if pa['domain'] == 'air' and pb['domain'] == 'air':
            large = pa['category'] in ('airplane', 'helicopter') or pb['category'] in (
                'airplane',
                'helicopter',
            )
            return (s['aircraftHorizontalM'] if large else 35), (
                s['aircraftVerticalM'] if large else 20
            )
        sea, air = (pa, pb) if pa['domain'] != 'air' else (pb, pa)
        return (
            sea['lengthM'] * 0.5 + sea['bufferM'] + air['bufferM'] + 30,
            sea['heightM'] + air['heightM'] * 0.5 + 15,
        )

    def pair(self, a, b):
        horizontal, vertical = self.required(a, b)
        altitude_a = a['center'][1]
        altitude_b = b['center'][1]
        if vertical and abs(altitude_a - altitude_b) >= vertical:
            return dict(
                a=a['instance'],
                b=b['instance'],
                safe=True,
                method='constant_vertical_separation',
                marginM=abs(altitude_a - altitude_b) - vertical,
                timeSeconds=0,
            )
        cuts = {0, self.duration}
        for route in (a, b):
            if route.get('boundedTurn'):
                cuts.update([route['turnStartSeconds'], route['turnEndSeconds']])
        cuts = sorted(cuts)
        lower = float('inf')
        at = 0
        curved = False
        for lo, hi in zip(cuts, cuts[1:]):
            midpoint = (lo + hi) / 2
            nonlinear = any(
                abs(r.get('yawRateDegS', 0)) > 1e-9
                and (
                    not r.get('boundedTurn')
                    or r['turnStartSeconds'] < midpoint < r['turnEndSeconds']
                )
                for r in (a, b)
            )
            if nonlinear:
                curved = True
                n = max(1, math.ceil((hi - lo) / self.scope['safety']['observerAuditStepSeconds']))
                dt = (hi - lo) / n
                sample = float('inf')
                when = lo
                for i in range(n + 1):
                    t = lo + dt * i
                    delta = minus(position(a, t), position(b, t))
                    d = math.hypot(delta[0], delta[2])
                    if d < sample:
                        sample, when = d, t
                value = sample - (norm(a['velocity']) + norm(b['velocity'])) * dt / 2
            else:
                r3 = minus(position(a, lo), position(b, lo))
                v3 = minus(velocity_at(a, midpoint), velocity_at(b, midpoint))
                r = [r3[0], r3[2]]
                v = [v3[0], v3[2]]
                relative = max(0, min(hi - lo, -dot(r, v) / dot(v, v))) if dot(v, v) > 1e-12 else 0
                value = norm(plus(r, times(v, relative)))
                when = lo + relative
            if value < lower:
                lower, at = value, when
        return dict(
            a=a['instance'],
            b=b['instance'],
            safe=lower >= horizontal,
            method='piecewise_CPA_curved_Lipschitz_bound' if curved else 'analytic_continuous_CPA',
            distanceLowerBoundM=lower,
            requiredM=horizontal,
            marginM=lower - horizontal,
            timeSeconds=at,
        )

    def geofence(self, route):
        p = route['profile']
        if p['domain'] == 'air':
            if not route.get('boundedTurn'):
                return all(abs(v) <= 100000 for t in [0, self.duration] for v in position(route, t))
            n = math.ceil(self.duration / 0.5)
            dt = self.duration / n
            pad = norm(route['velocity']) * dt / 2
            return all(
                abs(v) + pad <= 100000 for i in range(n + 1) for v in position(route, i * dt)
            )
        w = self.scope['water']
        radius = p['lengthM'] / 2 + p['bufferM']
        points = (
            [self.observer.at(i * self.duration / 100) for i in range(101)]
            if route.get('observer')
            else [position(route, 0), position(route, self.duration)]
        )
        padded = radius + (
            self.observer.speed * self.duration / 200 if route.get('observer') else 0
        )
        if any(
            not w['eastMinM'] + padded <= v[0] <= w['eastMaxM'] - padded
            or not w['northMinM'] + padded <= v[2] <= w['northMaxM'] - padded
            for v in points
        ):
            return False
        for zone in w.get('exclusionZones', []):
            if route.get('observer'):
                lower = (
                    min(math.hypot(v[0] - zone['eastM'], v[2] - zone['northM']) for v in points)
                    - self.observer.speed * self.duration / 200
                )
            else:
                r = position(route, 0)
                v = route['velocity']
                r = [r[0] - zone['eastM'], r[2] - zone['northM']]
                v = [v[0], v[2]]
                t = max(0, min(self.duration, -dot(r, v) / dot(v, v))) if dot(v, v) > 1e-12 else 0
                lower = norm(plus(r, times(v, t)))
            if lower < zone['radiusM'] + radius:
                return False
        return True

    def check(self, route, others):
        if not self.geofence(route):
            return dict(safe=False, b='navigable_water_or_air_extent', reason='geofence')
        if route['profile'].get('role') == 'fast_flyby':
            lower = self.camera_clearance(route)
            minimum = self.scope['fastDrones']['minCameraDistanceM']
            if lower < minimum + self.scope['safety']['planningMarginM']:
                return dict(
                    safe=False,
                    b='observer_camera_standoff',
                    reason='camera_clearance',
                    marginM=lower - minimum,
                )
        for other in others:
            result = self.pair(route, other)
            if not result['safe'] or result['marginM'] < self.scope['safety']['planningMarginM']:
                return result
        return None

    def camera_clearance(self, route):
        dt = self.scope['safety']['observerAuditStepSeconds']
        n = math.ceil(self.duration / dt)
        dt = self.duration / n
        eye_speed = self.observer.speed + abs(self.observer.w) * norm(
            arr(self.observer.template.get('observerDeckOffsetM', vec([0, 0, 0])))
        )
        return (
            min(
                norm(minus(position(route, i * dt), self.observer.eye(i * dt)))
                for i in range(n + 1)
            )
            - (norm(route['velocity']) + eye_speed) * dt / 2
        )


class ActorAgent:
    role = 'ActorAgent'

    def __init__(self, profile, scope, observer):
        self.profile = profile
        self.scope = scope
        self.observer = observer
        digest = hashlib.sha256((str(scope['seed']) + '|' + profile['instance']).encode()).digest()
        self.random = random.Random(int.from_bytes(digest[:8], 'big'))

    def propose(self, attempt):
        p = self.profile
        r = self.random
        duration = self.scope['durationSeconds']
        focus = r.uniform(duration * 0.25, duration * 0.75)
        distance = r.uniform(*p['rangeM'])
        if attempt > 48:
            distance *= min(1.8, 1 + (attempt - 48) / 300)
        heading = (
            self.scope['observer']['headingDeg']
            + self.scope['observer']['turnDeg'] * focus / duration
        )
        front = bearing(heading)
        right = bearing(heading + 90)
        center = plus(
            self.observer.at(focus),
            plus(times(front, distance), times(right, r.uniform(-0.42, 0.42) * distance)),
        )
        center[1] = r.uniform(*p['altitudeM'])
        speed = r.uniform(p['minimumMps'], p['safeMaximumMps'])
        course = heading + r.choice([0, 180, 80, 100, -80, -100]) + r.uniform(-5, 5)
        if p['domain'] == 'sea':
            # Parallel traffic keeps to opposite sides of a synthetic channel;
            # crossing traffic still has to negotiate complete safe reservations.
            if abs((course - heading + 180) % 360 - 180) < 15:
                center[0] = abs(center[0]) + 240
            if abs((course - heading) % 360 - 180) < 15:
                center[0] = -abs(center[0]) - 240
            if attempt > 0:
                speed = max(p['minimumMps'], speed * 0.9)
            if p['category'] == 'sailboat':
                wind_from = (self.scope['weather']['windTowardsDeg'] + 180) % 360
                if abs((course - wind_from + 180) % 360 - 180) < 40:
                    return None
        if p['domain'] == 'moored':
            center = plus(
                self.observer.origin,
                [(-1 if p['model'] == 'buoy' else 1) * r.uniform(220, 320), 0, distance],
            )
            speed = 0
            focus = 0
        velocity = times(bearing(course), speed)
        wind = times(
            bearing(self.scope['weather']['windTowardsDeg']), self.scope['weather']['localWindMps']
        )
        air_speed = norm(minus(velocity, wind)) if p['domain'] == 'air' else 0
        if p['domain'] == 'air' and air_speed > p['maxSpeedMps']:
            return None
        if p['model'] == 'airplane_a320':
            sound = math.sqrt(1.4 * 287.05 * max(216.65, 288.15 - 0.0065 * center[1]))
            if air_speed / sound > 0.82:
                return None
        return dict(
            instance=p['instance'],
            profile=p,
            center=center,
            velocity=velocity,
            focus=focus,
            groundSpeedMps=speed,
            airSpeedEstimateMps=air_speed,
            courseDeg=course % 360,
        )


class SeaTrafficAgent(ActorAgent):
    role = 'SeaTrafficAgent'


class AirTrafficAgent(ActorAgent):
    role = 'AirTrafficAgent'


class BuoyAgent(ActorAgent):
    role = 'BuoyAgent'


class FastDroneAgent(ActorAgent):
    role = 'FastDroneFlybyAgent'

    def propose(self, attempt):
        p = self.profile
        r = self.random
        spec = p['pass']
        scope = self.scope
        fast = scope['fastDrones']
        fps = scope['fps']
        cadence = scope['captureEveryFrames']
        focus = (
            round(spec['focusFraction'] * scope['durationSeconds'] * fps / cadence) * cadence / fps
        )
        heading = (
            self.observer.template.get('viewHeadingDeg', scope['observer']['headingDeg'])
            + scope['observer']['turnDeg'] * focus / scope['durationSeconds']
        )
        side = spec['side']
        distance = r.uniform(*p['rangeM'])
        center = plus(
            self.observer.eye(focus),
            plus(
                times(bearing(heading), distance),
                times(bearing(heading + 90), side * r.uniform(25, 50)),
            ),
        )
        center[1] = r.uniform(*p['altitudeM'])
        course = (
            heading + side * 90
            if spec['kind'] == 'crossing'
            else heading + 180 - side * r.uniform(28, 38)
        )
        speed = spec['speedKmh'] / 3.6
        route = dict(
            instance=p['instance'],
            profile=p,
            center=center,
            velocity=times(bearing(course), speed),
            focus=focus,
            groundSpeedMps=speed,
            airSpeedEstimateMps=norm(
                minus(
                    times(bearing(course), speed),
                    times(
                        bearing(scope['weather']['windTowardsDeg']),
                        scope['weather']['localWindMps'],
                    ),
                )
            ),
            courseDeg=course % 360,
            flightMode=spec['kind'],
            minCameraDistanceM=fast['minCameraDistanceM'],
        )
        if spec['kind'] == 'approach_bypass':
            route.update(
                boundedTurn=True,
                yawRateDegS=-side * fast['turnAngleDeg'] / fast['turnDurationSeconds'],
                turnStartSeconds=focus - fast['turnDurationSeconds'] / 2,
                turnEndSeconds=focus + fast['turnDurationSeconds'] / 2,
            )
        return route


class DirectorAgent:
    def fits(self, route, scope, template, observer):
        t = route['focus']
        turn = scope['observer']['turnDeg'] * t / scope['durationSeconds']
        heading = scope['observer']['headingDeg'] + turn
        eye = observer.at(t)
        if template.get('observerDeckCamera'):
            offset = arr(template['observerDeckOffsetM'])
            eye = plus(
                eye,
                plus(times(bearing(heading), offset[0]), times(bearing(heading + 90), -offset[2])),
            )
            eye[1] += offset[1]
        else:
            eye[1] += template.get('observerHeightM', 12.4)
        delta = minus(route['center'], eye)
        forward = bearing(template.get('viewHeadingDeg', 0) + turn)
        right = bearing(template.get('viewHeadingDeg', 0) + turn + 90)
        depth = dot(delta, forward)
        side = dot(delta, right)
        if depth <= 0:
            return False
        half = math.radians(template['verticalFovDeg'] / 2 - 3)
        horizontal = math.tan(half) * template['width'] / template['height']
        elevation = math.atan2(delta[1], depth) + math.radians(template.get('viewDownPitchDeg', 2))
        return (
            abs(side / depth) < horizontal
            and abs(elevation) < half
            and norm(delta) < template.get('farClipM', 80000) * 0.9
        )

    def describe(self, route, scope, template, observer):
        delta = minus(route['center'], observer.at(route['focus']))
        distance = norm(delta)
        diameter = max(route['profile']['lengthM'], route['profile']['beamM'])
        angular = 2 * math.atan2(diameter / 2, max(distance, 1))
        pixels = template['height'] * angular / math.radians(template['verticalFovDeg'])
        return dict(
            instance=route['instance'],
            model=route['profile']['model'],
            focusSeconds=route['focus'],
            rangeAtFocusM=distance,
            estimatedLargestSpanPixels=pixels,
            nominalCenterInsideFrustumAtFocus=self.fits(route, scope, template, observer),
            guaranteedVisible=False,
            notes='Geometric estimate only: no forced scaling, actual water/occlusion/haze/filter can remove visibility.',
        )


def planner_source_sha256(directory=None):
    """Pin both the planner and its equations, independently of installation path."""
    folder = pathlib.Path(directory) if directory is not None else pathlib.Path(__file__).parent
    value = hashlib.sha256()
    for name in ('planner.py', 'kinematics.py'):
        value.update(name.encode('ascii') + b'\0')
        value.update((folder / name).read_bytes())
        value.update(b'\0')
    return value.hexdigest()


class Orchestrator:
    def plan(
        self, scope, catalogue, template, telemetry=None, route_policy=None, route_transform=None
    ):
        board = Blackboard(telemetry)
        profiles = CatalogueAgent().run(scope, catalogue, template, board)
        observer = ObserverAgent(scope, template)
        safety = SafetyAgent(scope, observer)
        director = DirectorAgent()
        if not safety.geofence(observer.route):
            raise ValueError('Observer route leaves the navigable area')
        board.routes.append(observer.route)
        board.send(
            'ObserverAgent',
            'SafetyAgent',
            'route_reserved',
            actor='ObserverBoat',
            speedKnots=scope['observer']['speedKnots'],
        )
        for p in sorted(profiles, key=lambda p: (p['priority'], p['model'], p['instance'])):
            agent = (
                FastDroneAgent
                if p.get('role') == 'fast_flyby'
                else {'air': AirTrafficAgent, 'sea': SeaTrafficAgent, 'moored': BuoyAgent}[
                    p['domain']
                ]
            )(p, scope, observer)
            board.send(
                'Orchestrator',
                p['instance'],
                'plan_request',
                actor=p['instance'],
                specialist=agent.role,
                safeSpeedRangeMps=[p['minimumMps'], p['safeMaximumMps']],
                altitudeM=p['altitudeM'],
            )
            for attempt in range(scope['maxPlanningAttempts']):
                proposal = agent.propose(attempt)
                if proposal is None:
                    continue
                # Optional trusted application hooks. Defaults preserve the
                # original planner; user configuration never supplies code.
                if route_transform is not None:
                    proposal = route_transform(proposal, p)
                    if proposal is None:
                        continue
                if not director.fits(proposal, scope, template, observer):
                    board.send(
                        'DirectorAgent',
                        p['instance'],
                        'request_camera_crossing',
                        actor=p['instance'],
                        attempt=attempt,
                        reason='nominal_focus_outside_camera_frustum',
                    )
                    continue
                conflict = safety.check(proposal, board.routes)
                if conflict:
                    board.send(
                        'SafetyAgent',
                        p['instance'],
                        'yield_or_relocate',
                        actor=p['instance'],
                        attempt=attempt,
                        giveWayTo=conflict.get('b'),
                        reason=conflict.get('reason', 'predicted_close_approach'),
                        marginM=conflict.get('marginM'),
                    )
                    continue
                if route_policy is not None:
                    conflict = route_policy(proposal, board.routes, safety)
                    if conflict:
                        board.send(
                            'ColregAgent',
                            p['instance'],
                            'yield_or_relocate',
                            actor=p['instance'],
                            attempt=attempt,
                            giveWayTo=conflict.get('b'),
                            reason=conflict.get('reason', 'limited_colreg_geometry'),
                        )
                        continue
                board.routes.append(proposal)
                board.send(
                    p['instance'],
                    'Orchestrator',
                    'route_reserved',
                    actor=p['instance'],
                    attempt=attempt,
                    groundSpeedMps=proposal['groundSpeedMps'],
                    airSpeedEstimateMps=proposal['airSpeedEstimateMps'],
                )
                break
            else:
                raise ValueError(
                    'No safe placement for '
                    + p['instance']
                    + '; no scenario exported. Expand water or reduce counts/speeds.'
                )
        # Independent all-pairs pass, including routes reserved earlier.
        checks = [
            safety.pair(a, b) for i, a in enumerate(board.routes) for b in board.routes[i + 1 :]
        ]
        if any(not c['safe'] for c in checks):
            raise RuntimeError('Final continuous safety audit failed')
        board.send(
            'SafetyAgent',
            'Orchestrator',
            'plan_approved',
            pairChecks=len(checks),
            continuousModel='linear CPA and conservative curved-observer bound',
        )
        routes = {r['instance']: r for r in board.routes if not r.get('observer')}
        events = []
        decisions = []
        for i, p in enumerate(profiles):
            r = routes[p['instance']]
            events.append(
                dict(
                    instance=p['instance'],
                    category=p['category'],
                    modelName=p['model'],
                    trackId=i + 1,
                    classIndex=p['classIndex'],
                    startSeconds=0,
                    endSeconds=scope['durationSeconds'],
                    centerSeconds=r['focus'],
                    distanceRequestedM=norm(minus(r['center'], observer.at(r['focus']))),
                    altitudeM=r['center'][1],
                    centerPosition=vec(r['center']),
                    velocity=vec(r['velocity']),
                    phase=(i * 1.61803398875) % (2 * math.pi),
                )
            )
            if p.get('role') == 'fast_flyby':
                events[-1].update(
                    flightMode=r['flightMode'],
                    boundedTurn=r.get('boundedTurn', False),
                    yawRateDegS=r.get('yawRateDegS', 0),
                    turnStartSeconds=r.get('turnStartSeconds', 0),
                    turnEndSeconds=r.get('turnEndSeconds', 0),
                )
            decisions.append(
                dict(
                    instance=p['instance'],
                    model=p['model'],
                    category=p['category'],
                    domain=p['domain'],
                    lengthM=p['lengthM'],
                    heightM=p['heightM'],
                    bufferM=p['bufferM'],
                    groundSpeedMps=r['groundSpeedMps'],
                    speedKnots=r['groundSpeedMps'] / KNOT,
                    speedKmh=r['groundSpeedMps'] * 3.6,
                    airSpeedEstimateMps=r['airSpeedEstimateMps'],
                    safeMaximumMps=p['safeMaximumMps'],
                    maxSpeedMps=p['maxSpeedMps'],
                    altitudeM=r['center'][1],
                    evidence=p['evidence'],
                )
            )
            if p.get('role') == 'fast_flyby':
                decisions[-1].update(
                    flightMode=r['flightMode'],
                    syntheticPerformance=True,
                    minCameraDistanceM=r['minCameraDistanceM'],
                    cameraDistanceLowerBoundM=safety.camera_clearance(r),
                )
        planner_sha = planner_source_sha256()
        canonical = json.dumps(
            dict(scope=scope, catalogue=catalogue, plannerSha256=planner_sha),
            sort_keys=True,
            separators=(',', ':'),
        )
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        plan = dict(
            schema='lotusim-unity-encounters-1',
            motionSource='LOTUSim cooperative preplanned kinematic traffic; no reactive navigation solver',
            northAxis='Unity +Z',
            eastAxis='Unity +X',
            seed=scope['seed'],
            maxActive=len(events),
            events=events,
        )
        capture = set(
            range(
                0, math.ceil(scope['durationSeconds'] * scope['fps']), scope['captureEveryFrames']
            )
        )
        if scope.get('fastDrones', {}).get('enabled'):
            fast = scope['fastDrones']
            stride = scope['fps'] // fast['captureHz']
            radius = round(fast['captureBurstSeconds'] * scope['fps'] / 2)
            for e in events:
                if e.get('flightMode'):
                    center = round(e['centerSeconds'] * scope['fps'])
                    capture.update(
                        range(
                            max(0, center - radius),
                            min(
                                math.ceil(scope['durationSeconds'] * scope['fps']),
                                center + radius + 1,
                            ),
                            stride,
                        )
                    )
            plan['captureFrames'] = sorted(capture)
        metadata = dict(
            schema='lotusim-cooperative-traffic-1',
            scenarioName=scope['name'],
            inputSha256=digest,
            plannerSha256=planner_sha,
            localWindMps=scope['weather']['localWindMps'],
            significantSwellHeightM=scope['weather']['significantSwellHeightM'],
            runtimePositionToleranceM=scope['safety']['runtimePositionToleranceM'],
            continuousSafetyApproved=True,
            reactiveAvoidance=False,
            actorProfiles=decisions,
        )
        plan['traffic'] = metadata
        report = dict(
            schema='lotusim-traffic-audit-1',
            approved=True,
            actors=len(events),
            observer='ObserverBoat',
            seed=scope['seed'],
            inputSha256=digest,
            pairChecks=len(checks),
            minimumMarginM=min(c['marginM'] for c in checks),
            checks=checks,
            decisions=decisions,
            director=[
                DirectorAgent().describe(r, scope, template, observer)
                for r in board.routes
                if not r.get('observer')
            ],
            limitations=[
                'Synthetic open-water geofence; no chart/bathymetry/real traffic feed',
                'Pre-launch negotiation, NOT reactive avoidance of unknown objects',
                'Circular conservative hull domains, not hydrodynamics or a certified COLREG implementation',
                'Piecewise straight/constant-turn kinematics; wind-relative speed check approximate, no flight dynamics or validated fast-drone performance',
                'Local wind differs from HDRP groundswell spectrum proxy',
                'No promise all objects are recognisable/visible in each RGB image',
            ],
        )
        return plan, report, dict(schema='lotusim-agent-negotiation-1', messages=board.messages)


def write_dashboard(output, plan, report, messages):
    data = json.dumps(
        dict(plan=plan, report=report, messages=messages), ensure_ascii=False
    ).replace('</', '<\\/')
    page = '''<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trafic coopératif LOTUSim</title><style>body{margin:24px;background:#10212c;color:#e8f3fb;font:16px system-ui}a{color:#91d8ff}main{max-width:1450px;margin:auto}.cards{display:flex;gap:12px;flex-wrap:wrap}.cards p{background:#203a4c;padding:14px;border-radius:10px}canvas{width:100%;height:530px;background:#092d43;border:1px solid #42657a}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #42657a;text-align:left}input{width:65%}small{color:#afc4d1}details{margin:20px 0}#trace{white-space:pre-wrap;max-height:320px;overflow:auto}select,button{padding:8px;background:#244153;color:white;border:1px solid #527b95}</style><main><h1>MaritimeTrafficAgents — trafic coopératif</h1><p>Orchestrateur → catalogue et météo → agents de bouées, navigation et vol → négociation de chaque route → audit continu des distances → LOTUSim → une connexion ROS → Unity.</p><div class="cards"><p id="summary"></p><p>Agents logiciels déterministes<br>Sans LLM ni service distant</p><p>Évitement planifié avant lancement<br>Pas de navigation réactive certifiée</p></div><p><button id="play">Lecture du plan</button> <input id="time" type="range" min="0" step="0.5"><span id="clock"></span></p><label>Vue <select id="extent"><option value="6000">Trafic proche — 6 km</option><option value="45000">Inclure l’avion de ligne — 45 km</option></select></label><canvas id="map" width="1400" height="530"></canvas><p><small>Carte du plan (pas un rendu Unity ni une carte officielle). Nord vers le haut, distances à l’échelle. Les aéronefs de croisière ne sont pas rapprochés artificiellement de la caméra.</small></p><h2>Profils sélectionnés</h2><table><thead><tr><th>Objet</th><th>Vitesse sol</th><th>Altitude</th><th>Hypothèse / référence</th></tr></thead><tbody id="assets"></tbody></table><details><summary id="trace-title"></summary><pre id="trace"></pre></details><p><a href="plan.json">Plan</a> · <a href="safety-report.json">Audit des séparations</a> · <a href="agent-messages.json">Messages des agents</a> · <a href="scope.snapshot.json">Configuration</a> · <a href="catalogue.snapshot.json">Capacités et sources</a></p><p>La houle et les petites embarcations imposent des vitesses inférieures aux maxima. Les modèles génériques ont des valeurs représentatives, pas des performances constructeur mesurées. Aucun solveur hydrodynamique ou aérodynamique n’est revendiqué.</p><script>const DATA=__DATA__,p=DATA.plan,r=DATA.report,t=document.querySelector('#time'),canvas=document.querySelector('canvas'),ctx=canvas.getContext('2d');t.max=p.events[0].endSeconds;document.querySelector('#summary').textContent=r.actors+' objets + FREMM · '+r.pairChecks+' paires vérifiées · marge minimale '+r.minimumMarginM.toFixed(1)+' m';document.querySelector('#assets').innerHTML=r.decisions.map(o=>'<tr><td>'+o.model+'</td><td>'+o.speedKnots.toFixed(1)+' kn / '+o.speedKmh.toFixed(0)+' km/h</td><td>'+o.altitudeM.toFixed(0)+' m</td><td>'+o.evidence+'</td></tr>').join('');document.querySelector('#trace-title').textContent=DATA.messages.messages.length+' messages de planification / négociation';document.querySelector('#trace').textContent=DATA.messages.messages.map(m=>m.index+' '+m.sender+' → '+m.recipient+': '+m.kind+(m.giveWayTo?' / priorité à '+m.giveWayTo:'')).join('\n');function draw(){let s=+document.querySelector('#extent').value,now=+t.value;ctx.clearRect(0,0,1400,530);ctx.strokeStyle='#24516a';for(let x=0;x<1400;x+=100){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,530);ctx.stroke()}for(let y=0;y<530;y+=53){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(1400,y);ctx.stroke()}function at(v){return [700+v.x/s*700,440-v.z/s*700]}p.events.forEach((e,i)=>{let d=now-e.centerSeconds,v={x:e.centerPosition.x+e.velocity.x*d,z:e.centerPosition.z+e.velocity.z*d},a=at(v),b=at(e.centerPosition);ctx.fillStyle=e.category==='buoy'?'#ffc754':e.altitudeM>0?'#d6a9ff':'#74d9bd';ctx.beginPath();ctx.arc(a[0],a[1],5,0,7);ctx.fill();ctx.font='11px system-ui';ctx.fillText(e.modelName,a[0]+7,a[1]);});ctx.fillStyle='white';ctx.fillText('FREMM : route courbe réservée (voir plan Unity)',710,465);document.querySelector('#clock').textContent=now.toFixed(1)+' s'}t.oninput=draw;document.querySelector('#extent').onchange=draw;let timer;document.querySelector('#play').onclick=()=>{if(timer){clearInterval(timer);timer=null;return}timer=setInterval(()=>{t.value=(+t.value+.5)>+t.max?0:+t.value+.5;draw()},50)};draw();</script></main></html>'''
    # The preview uses the same bounded-turn equations as Python, Unity and
    # LOTUSim. It must not draw these new encounters as straight trajectories.
    page = page.replace(".join('\n')", r".join('\n')")
    page = page.replace(
        'function draw(){',
        '''function point(e,t){const v=e.velocity,w=(e.yawRateDegS||0)*Math.PI/180,d=t-e.centerSeconds;if(Math.abs(w)<1e-9)return{x:e.centerPosition.x+v.x*d,z:e.centerPosition.z+v.z*d};const q=(e.boundedTurn?Math.max(e.turnStartSeconds,Math.min(e.turnEndSeconds,t)):t)-e.centerSeconds,a=w*q;let x=e.centerPosition.x+(v.x*Math.sin(a)+v.z*(1-Math.cos(a)))/w,z=e.centerPosition.z+(v.x*(Math.cos(a)-1)+v.z*Math.sin(a))/w;if(e.boundedTurn)for(const [at,extra] of [[e.turnStartSeconds,Math.min(0,t-e.turnStartSeconds)],[e.turnEndSeconds,Math.max(0,t-e.turnEndSeconds)]]){let b=w*(at-e.centerSeconds);x+=(Math.cos(b)*v.x+Math.sin(b)*v.z)*extra;z+=(-Math.sin(b)*v.x+Math.cos(b)*v.z)*extra}return{x,z}}function draw(){''',
    )
    page = page.replace(
        'let d=now-e.centerSeconds,v={x:e.centerPosition.x+e.velocity.x*d,z:e.centerPosition.z+e.velocity.z*d},a=at(v),b=at(e.centerPosition);',
        'let v=point(e,now),a=at(v),b=at(e.centerPosition);',
    )
    fast = [e for e in plan['events'] if e.get('flightMode')]
    if fast:
        rows = ''.join(
            '<tr><td>'
            + html.escape(e['instance'])
            + '</td><td>'
            + ('Traversée latérale' if e['flightMode'] == 'crossing' else 'Approche puis déviation')
            + '</td><td>'
            + str(round(norm(arr(e['velocity'])) * 3.6))
            + ' km/h</td><td>'
            + str(round(e['centerSeconds'], 1))
            + ' s</td></tr>'
            for e in sorted(fast, key=lambda e: e['centerSeconds'])
        )
        hz = json.loads((output / 'scope.snapshot.json').read_text())['fastDrones']['captureHz']
        section = (
            '<h2>Passages rapides — banc visuel fictif non armé</h2><p>Petit drone à taille inchangée. Profils synthétiques, pas des performances mesurées. Les quadricoptères ordinaires gardent leurs limites. Captures de base conservées, rafales à '
            + str(hz)
            + ' Hz autour des passages : '
            + str(len(plan['captureFrames']))
            + ' instants au total.</p><table><tr><th>Drone</th><th>Passage</th><th>Vitesse</th><th>Centre du passage</th></tr>'
            + rows
            + '</table><h2>Profils sélectionnés</h2>'
        )
        page = page.replace('<h2>Profils sélectionnés</h2>', section)
    if (output / 'connected/index.html').exists():
        page = page.replace(
            '<h2>Profils sélectionnés</h2>',
            '<p><a href="connected/index.html">Validation connectée antérieure, avant ajout des passages rapides : 9 images 4K RGB / IR / nuit</a> · <a href="connected/verification.json">Vérification indépendante</a> · <a href="connected/connection-count.json">Une connexion ROS</a></p><h2>Profils sélectionnés</h2>',
        )
    (output / 'index.html').write_text(page.replace('__DATA__', data), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', type=pathlib.Path, required=True)
    parser.add_argument('--catalogue', type=pathlib.Path, required=True)
    parser.add_argument('--template', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    scope = json.loads(args.scope.read_text())
    catalogue = json.loads(args.catalogue.read_text())
    template = json.loads(args.template.read_text())
    from lotusim_image_generator.telemetry.runtime import OpsRuntime

    runtime = OpsRuntime(args.output / 'ops-status.json', 'traffic_planner')
    try:
        plan, report, messages = Orchestrator().plan(scope, catalogue, template, runtime.event)
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in [
            ('plan.json', plan),
            ('safety-report.json', report),
            ('agent-messages.json', messages),
            ('scope.snapshot.json', scope),
            ('catalogue.snapshot.json', catalogue),
        ]:
            target = args.output / name
            temporary = target.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
            temporary.replace(target)
        write_dashboard(args.output, plan, report, messages)
        runtime.complete()
    except Exception as error:
        runtime.fail(error)
        raise
    print(
        'APPROVED: '
        + str(report['actors'])
        + ' actors, '
        + str(report['pairChecks'])
        + ' continuous pair checks, '
        + str(len(messages['messages']))
        + ' agent messages. No simulator was modified.'
    )


if __name__ == '__main__':
    main()
