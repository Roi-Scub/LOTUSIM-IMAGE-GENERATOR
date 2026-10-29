#!/usr/bin/env python3
"""Planning regression tests; no Unity, ROS, network or simulator required."""

import json
import math
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
from lotusim_image_generator.traffic import planner as traffic

CATEGORIES = [
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
]


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.scope = json.loads(
            (ROOT / 'assets/scenarios/scopes/MaritimeTrafficAgents.json').read_text()
        )
        self.scope['fastDrones'][
            'enabled'
        ] = False  # Preserve the original 26-model regression suite.
        self.catalogue = json.loads(
            (ROOT / 'assets/scenarios/catalogs/traffic_assets.json').read_text()
        )
        self.template = dict(
            origin=dict(x=0, y=0, z=0),
            width=3840,
            height=2160,
            verticalFovDeg=55,
            classes=[dict(category=c) for c in CATEGORIES],
        )

    def plan(self):
        return traffic.Orchestrator().plan(self.scope, self.catalogue, self.template)

    def test_replay_and_complete_coverage(self):
        first = self.plan()
        second = self.plan()
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        p, r, m = first
        self.assertEqual(len({e['modelName'] for e in p['events']}), 26)
        self.assertEqual(r['pairChecks'], 351)
        self.assertTrue(
            all(
                c['safe'] and c['marginM'] >= self.scope['safety']['planningMarginM']
                for c in r['checks']
            )
        )
        self.assertTrue(all(c['nominalCenterInsideFrustumAtFocus'] for c in r['director']))
        self.assertTrue(any(v['kind'] == 'yield_or_relocate' for v in m['messages']))
        a = next(x for x in r['decisions'] if x['model'] == 'airplane_a320')
        self.assertTrue(810 <= a['speedKmh'] <= 870 and 9500 <= a['altitudeM'] <= 11500)

    def test_100_seeds(self):
        for seed in range(100):
            self.scope['seed'] = seed
            p, r, _ = self.plan()
            self.assertEqual(len(p['events']), 26)
            self.assertEqual(r['pairChecks'], 351)
            self.assertGreaterEqual(r['minimumMarginM'], self.scope['safety']['planningMarginM'])

    def test_overspeed_refused(self):
        self.scope['overrides'] = [dict(model='airplane_a320', speedMin=1000, speedMax=1000)]
        with self.assertRaisesRegex(ValueError, 'capability'):
            self.plan()

    def test_ceiling_refused(self):
        self.scope['overrides'] = [dict(model='airplane_c172', altitudeM=[5000, 5500])]
        with self.assertRaisesRegex(ValueError, 'ceiling'):
            self.plan()

    def test_storm_drone_refused(self):
        self.scope['weather']['localWindMps'] = 20
        with self.assertRaisesRegex(ValueError, 'Wind exceeds'):
            self.plan()

    def test_impossible_geofence_refused(self):
        self.scope['water'].update(eastMinM=-100, eastMaxM=100, northMinM=-100, northMaxM=100)
        with self.assertRaisesRegex(ValueError, 'Observer'):
            self.plan()

    def test_unknown_and_overcrowding_refused(self):
        self.scope['overrides'] = [dict(model='arbitrary_external_model')]
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            self.plan()
        self.scope['overrides'] = []
        self.scope['countPerModel'] = 2
        with self.assertRaisesRegex(ValueError, '40'):
            self.plan()

    def test_moored_buoys_and_model_specific_speeds(self):
        p, r, _ = self.plan()
        for e in p['events']:
            if e['category'] == 'buoy':
                self.assertEqual(e['velocity'], dict(x=0, y=0, z=0))
            if e['category'] in (
                'fishing_trawler',
                'container_ship',
                'motor_yacht',
                'speedboat',
                'jetski',
                'ferry',
                'sailboat',
            ):
                self.assertEqual(e['altitudeM'], 0)
        d = {v['model']: v for v in r['decisions']}
        self.assertLess(d['sailboat']['speedKnots'], 7)
        self.assertLess(d['jetski']['speedKnots'], 15)
        self.assertLess(d['airplane_c172']['speedKmh'], 230)

    def test_cpa_catches_collision_between_samples(self):
        observer = traffic.ObserverAgent(self.scope, self.template)
        safety = traffic.SafetyAgent(self.scope, observer)
        profile = dict(domain='sea', lengthM=1, bufferM=1, heightM=1, category='speedboat')
        a = dict(instance='a', profile=profile, center=[-100, 0, 0], velocity=[200, 0, 0], focus=0)
        b = dict(instance='b', profile=profile, center=[0, 0, -100], velocity=[0, 0, 200], focus=0)
        result = safety.pair(a, b)
        self.assertFalse(result['safe'])
        self.assertAlmostEqual(result['timeSeconds'], 0.5)
        self.assertEqual(result['distanceLowerBoundM'], 0)

    def test_curved_observer_bound(self):
        observer = traffic.ObserverAgent(self.scope, self.template)
        safety = traffic.SafetyAgent(self.scope, observer)
        p = dict(domain='sea', lengthM=10, bufferM=20, heightM=2, category='speedboat')
        a = dict(instance='other', profile=p, center=[700, 0, 700], velocity=[-2, 0, 3], focus=0)
        result = safety.pair(a, observer.route)
        sampled = min(
            math.hypot(
                traffic.position(a, i * 0.02)[0] - observer.at(i * 0.02)[0],
                traffic.position(a, i * 0.02)[2] - observer.at(i * 0.02)[2],
            )
            for i in range(int(self.scope['durationSeconds'] / 0.02) + 1)
        )
        self.assertLessEqual(result['distanceLowerBoundM'], sampled + 0.00001)


if __name__ == '__main__':
    unittest.main(verbosity=2)
