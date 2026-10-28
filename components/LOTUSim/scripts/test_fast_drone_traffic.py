import importlib.util, json, math, pathlib, unittest, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'fast_traffic', ROOT / 'tools/plan_maritime_traffic.py'
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
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


class FastDrones(unittest.TestCase):
    def setUp(self):
        self.scope = json.loads(
            (ROOT / 'assets/scenarios/scopes/MaritimeTrafficAgents.json').read_text()
        )
        self.catalogue = json.loads(
            (ROOT / 'assets/scenarios/catalogs/traffic_assets.json').read_text()
        )
        self.template = dict(
            origin=m.vec([0, 0, 0]),
            width=3840,
            height=2160,
            verticalFovDeg=55,
            viewHeadingDeg=15,
            viewDownPitchDeg=2,
            observerDeckCamera=True,
            observerDeckOffsetM=m.vec([30.3, 12.4, -5.5]),
            classes=[dict(category=c) for c in CATEGORIES],
        )

    def plan(self):
        return m.Orchestrator().plan(self.scope, self.catalogue, self.template)

    def test_speeds_schedule_and_preserved_ordinary_drones(self):
        p, r, messages = self.plan()
        fast = [e for e in p['events'] if e['modelName'] == 'drone_racer_sim']
        self.assertEqual(len(p['events']), 32)
        self.assertEqual(len(fast), 6)
        self.assertEqual(r['pairChecks'], 528)
        self.assertEqual(
            sorted(round(m.norm(m.arr(e['velocity'])) * 3.6) for e in fast),
            [60, 180, 240, 300, 400, 400],
        )
        self.assertEqual(sum(e['flightMode'] == 'approach_bypass' for e in fast), 3)
        self.assertEqual(len(p['captureFrames']), 504)
        self.assertEqual(p['captureFrames'], sorted(set(p['captureFrames'])))
        self.assertTrue(set(range(0, 5400, 15)) <= set(p['captureFrames']))
        for e in p['events']:
            if e['modelName'] in ('small_drone', 'drone_amvlab'):
                self.assertLessEqual(m.norm(m.arr(e['velocity'])), 8)
        for e in fast:
            center = round(e['centerSeconds'] * 30)
            self.assertTrue(
                all(i in p['captureFrames'] for i in range(center - 45, center + 46, 3))
            )
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / 'scope.snapshot.json').write_text(json.dumps(self.scope))
            m.write_dashboard(output, p, r, messages)
            page = (output / 'index.html').read_text()
            self.assertIn('function point(e,t)', page)
            self.assertNotIn(".join('\n')", page)
            self.assertIn(r".join('\n')", page)

    def test_100_seeds_continuous_clearances(self):
        for seed in range(100):
            self.scope['seed'] = seed
            p, r, _ = self.plan()
            self.assertEqual(r['pairChecks'], 528)
            self.assertGreaterEqual(r['minimumMarginM'], 5)
            for d in r['decisions']:
                if d.get('flightMode'):
                    self.assertGreaterEqual(d['cameraDistanceLowerBoundM'], 85)
                    self.assertTrue(d['syntheticPerformance'])
            self.assertTrue(all(v['nominalCenterInsideFrustumAtFocus'] for v in r['director']))

    def test_tangent_continuity_and_turn_angle(self):
        p, _, _ = self.plan()
        for e in p['events']:
            if not e.get('boundedTurn'):
                continue
            route = dict(
                center=m.arr(e['centerPosition']),
                velocity=m.arr(e['velocity']),
                focus=e['centerSeconds'],
                boundedTurn=True,
                yawRateDegS=e['yawRateDegS'],
                turnStartSeconds=e['turnStartSeconds'],
                turnEndSeconds=e['turnEndSeconds'],
            )
            for at in [
                0,
                route['turnStartSeconds'],
                route['focus'],
                route['turnEndSeconds'],
                179.9,
            ]:
                h = 1e-5
                a = m.position(route, at - h)
                b = m.position(route, at + h)
                v = m.velocity_at(route, at)
                self.assertLess(m.norm(m.minus(m.times(m.minus(b, a), 1 / (2 * h)), v)), 0.001)
                self.assertAlmostEqual(m.norm(v), m.norm(route['velocity']), places=8)
            a = m.velocity_at(route, route['turnStartSeconds'])
            b = m.velocity_at(route, route['turnEndSeconds'])
            self.assertAlmostEqual(
                math.degrees(math.acos(max(-1, min(1, m.dot(a, b) / (m.norm(a) * m.norm(b)))))),
                40,
                places=7,
            )

    def test_bad_speed_or_turn_refused(self):
        self.scope['fastDrones']['passes'][0]['speedKmh'] = 401
        with self.assertRaisesRegex(ValueError, 'pass'):
            self.plan()
        self.setUp()
        self.scope['fastDrones']['turnDurationSeconds'] = 2
        with self.assertRaisesRegex(ValueError, 'turn'):
            self.plan()
        self.setUp()
        self.scope['overrides'] = [dict(model='small_drone', speedMax=400)]
        with self.assertRaisesRegex(ValueError, 'capability'):
            self.plan()

    def test_impossible_close_camera_request_refused(self):
        self.scope['fastDrones']['minCameraDistanceM'] = 500
        self.scope['maxPlanningAttempts'] = 8
        with self.assertRaisesRegex(ValueError, 'No safe placement'):
            self.plan()


if __name__ == '__main__':
    unittest.main(verbosity=2)
