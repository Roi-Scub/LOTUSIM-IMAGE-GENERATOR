#!/usr/bin/env python3
"""Fixture-only cooperative generation/re-audit; no engine, ROS or DB writes."""

import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import cooperative_scenario as coop
from campaign_settings import CampaignStore
import plan_maritime_traffic as traffic


class CooperativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-cooperative-test-')
        self.addCleanup(self.temporary.cleanup)
        self.core = Path(self.temporary.name)
        source = ROOT / 'assets/scenarios/catalogs/traffic_assets.json'
        target = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        self.request = {
            'name': 'Trafic coopératif',
            'seed': 20261028,
            'durationSeconds': 180,
            'actionProfile': 'open_water',
        }

    def generate(self, **changes):
        request = dict(self.request, **changes)
        return coop.generate(self.core, None, request)

    def campaign(self, **row_changes):
        campaign = CampaignStore(self.core).defaults()
        for block in campaign['blocks']:
            block['objects'][0].update(row_changes)
        return campaign

    def audit(self, result, plan=None):
        return coop.revalidate_plan(
            plan or result['plan'], result['scope'], result['catalogue'], result['template']
        )

    def test_actual_32_actors_all_three_profiles_two_reference_seeds(self):
        for seed in (20261016, 20261028):
            for profile in ('open_water', 'crossing', 'parallel'):
                with self.subTest(seed=seed, profile=profile):
                    result = self.generate(seed=seed, actionProfile=profile)
                    self.assertEqual(result['audit']['actors'], 32)
                    self.assertEqual(result['audit']['pairChecks'], 528)
                    self.assertTrue(result['audit']['approved'])
                    self.assertTrue(result['audit']['continuousSafetyApproved'])
                    self.assertTrue(all(check['safe'] for check in result['audit']['checks']))
                    self.assertGreaterEqual(result['audit']['minimumMarginM'], 5)

    def test_deterministic_replay(self):
        first, second = self.generate(), self.generate()
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_no_runtime_process_or_production_write(self):
        before = {path.relative_to(self.core) for path in self.core.rglob('*')}
        with patch('subprocess.Popen', side_effect=AssertionError('No engine allowed')):
            self.generate()
        self.assertEqual({path.relative_to(self.core) for path in self.core.rglob('*')}, before)

    def test_no_full_colreg_or_native_certification_claim(self):
        result = self.generate()
        self.assertFalse(result['fullColregCompliance'])
        self.assertTrue(result['notCertified'])
        self.assertFalse(result['audit']['fullColregCompliance'])
        limited = result['audit']['limitedColreg']
        self.assertTrue(limited['notCertified'])
        self.assertTrue(any('règle 18' in line for line in result['audit']['limitations']))
        self.assertTrue(any('règle 19' in line for line in result['audit']['limitations']))
        self.assertTrue(
            all(
                'imo.org' in item['url'] or 'uscg.gov' in item['url']
                for item in limited['references']
            )
        )

    def test_limited_rules_really_participate_in_negotiation(self):
        result = self.generate(seed=20261016)
        self.assertTrue(result['audit']['limitedColreg']['checks'])
        self.assertTrue(
            all(check['passed'] for check in result['audit']['limitedColreg']['checks'])
        )
        self.assertTrue(
            any(message['sender'] == 'ColregAgent' for message in result['messages']['messages'])
        )

    def test_name_is_human_readable_but_yaml_identifier_is_safe(self):
        result = self.generate(name='Mer agitée — test 1')
        self.assertEqual(result['name'], 'Mer agitée — test 1')
        self.assertRegex(result['scope']['name'], r'^Coop_[0-9a-f]{16}$')

    def test_request_bounds_and_unknown_fields_are_refused(self):
        for changes in (
            {'seed': True},
            {'seed': -1},
            {'seed': 2147483648},
            {'seed': 10**500},
            {'seed': 1.5},
            {'durationSeconds': 3},
            {'durationSeconds': 601},
            {'durationSeconds': float('nan')},
            {'name': ''},
            {'name': 'x\ncommand'},
            {'actionProfile': 'collision'},
            {'speedPolicy': 'all_out'},
            {'headingPolicy': 'random_code'},
            {'campaign': None},
            {'arbitraryPath': '/tmp/source'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.generate(**changes)

    def test_requested_policies_require_a_campaign(self):
        for changes in (
            {'speedPolicy': 'requested'},
            {'headingPolicy': 'requested'},
            {'blockId': 'day'},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.generate(**changes)

    def test_campaign_multiple_blocks_requires_explicit_choice(self):
        campaign = self.campaign()
        with self.assertRaisesRegex(ValueError, 'blockId'):
            self.generate(campaign=campaign)
        with self.assertRaisesRegex(ValueError, 'blockId'):
            self.generate(campaign=campaign, blockId='unknown')

    def test_one_block_preserves_exact_counts_environment_range_and_capture_count(self):
        campaign = self.campaign(count=2, distanceM=800, spreadDeg=90)
        result = self.generate(campaign=campaign, blockId='day')
        self.assertEqual(result['scope']['cooperativeRequest']['blockId'], 'day')
        self.assertEqual(
            result['scope']['environmentRequested'], campaign['blocks'][0]['environment']
        )
        self.assertEqual(len(result['plan']['events']), 2)
        self.assertEqual(len(result['plan']['captureFrames']), 3)
        self.assertEqual(len(set(result['plan']['captureFrames'])), 3)
        observer = traffic.ObserverAgent(result['scope'], result['template'])
        for event in result['plan']['events']:
            eye = observer.eye(event['centerSeconds'])
            center = traffic.arr(event['centerPosition'])
            self.assertAlmostEqual(math.hypot(center[0] - eye[0], center[2] - eye[2]), 800)
        self.assertTrue(result['audit']['approved'])

    def test_requested_speed_and_heading_are_not_silently_adjusted(self):
        campaign = self.campaign(model='motor_yacht', distanceM=1500, speedMps=3.2, headingDeg=90)
        result = self.generate(
            campaign=campaign, blockId='day', speedPolicy='requested', headingPolicy='requested'
        )
        event = result['plan']['events'][0]
        self.assertAlmostEqual(event['velocity']['x'], 3.2)
        self.assertAlmostEqual(event['velocity']['z'], 0, places=8)
        decision = result['plan']['traffic']['actorProfiles'][0]
        self.assertEqual(decision['requestedSpeedMps'], decision['actualSpeedMps'])
        self.assertEqual(decision['requestedHeadingDeg'], decision['actualHeadingDeg'])

    def test_requested_unsafe_overlap_is_refused_not_displaced(self):
        campaign = self.campaign(count=2, distanceM=400, spreadDeg=0)
        with self.assertRaisesRegex(ValueError, 'EXACT requested'):
            self.generate(campaign=campaign, blockId='day')

    def test_too_close_and_unsupported_swell_are_refused(self):
        with self.assertRaisesRegex(ValueError, '50 m'):
            self.generate(campaign=self.campaign(distanceM=20), blockId='day')
        campaign = self.campaign()
        campaign['blocks'][0]['environment']['waveHeightM'] = 7
        with self.assertRaisesRegex(ValueError, '6 m'):
            self.generate(campaign=campaign, blockId='day')

    def test_capture_count_cannot_exceed_available_frames(self):
        campaign = self.campaign()
        campaign['blocks'][0]['images'] = 121
        campaign['totalImages'] = 128
        with self.assertRaisesRegex(ValueError, 'available source frames'):
            self.generate(campaign=campaign, blockId='day', durationSeconds=4)

    def test_reaudit_ignores_forged_prior_approval_and_detects_actual_collision(self):
        result = self.generate()
        plan = copy.deepcopy(result['plan'])
        for event in plan['events'][:2]:
            event.update(
                centerPosition={'x': 500, 'y': 0, 'z': 500},
                velocity={'x': 0, 'y': 0, 'z': 0},
                centerSeconds=0,
            )
        plan['traffic']['continuousSafetyApproved'] = True
        audit = self.audit(result, plan)
        self.assertFalse(audit['approved'])
        self.assertFalse(audit['continuousSafetyApproved'])
        self.assertTrue(any(not check['safe'] for check in audit['checks']))
        with self.assertRaisesRegex(ValueError, 'export refused'):
            coop.render_scenario_yaml(plan, result['scope'], result['template'])

    def test_fast_drone_cannot_pass_above_camera_inside_declared_standoff(self):
        result = self.generate()
        plan = copy.deepcopy(result['plan'])
        event = next(item for item in plan['events'] if item['modelName'] == 'drone_racer_sim')
        observer = traffic.ObserverAgent(result['scope'], result['template'])
        eye = observer.eye(0)
        event.update(
            centerPosition={'x': eye[0], 'y': 70, 'z': eye[2]},
            velocity={'x': 0, 'y': 0, 'z': 0},
            centerSeconds=0,
            yawRateDegS=0,
            boundedTurn=False,
        )
        audit = self.audit(result, plan)
        self.assertFalse(audit['approved'])
        self.assertTrue(any('camera standoff' in message for message in audit['errors']))

    def test_unknown_actor_and_vertical_motion_are_unsupported(self):
        result = self.generate()
        for changes in (
            {'instance': 'unregistered'},
            {'velocity': {'x': 0, 'y': 1, 'z': 0}},
            {'velocity': {'x': float('inf'), 'y': 0, 'z': 0}},
            {'controlPoints': []},
        ):
            plan = copy.deepcopy(result['plan'])
            plan['events'][0].update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(self.audit(result, plan)['approved'])
                self.assertEqual(self.audit(result, plan)['status'], 'unsupported')

    def test_uncompiled_control_points_are_never_approved_as_linear_motion(self):
        result = self.generate()
        plan = copy.deepcopy(result['plan'])
        plan['containsUncompiledControlPoints'] = True
        self.assertFalse(self.audit(result, plan)['approved'])

    def test_sailing_fishing_and_rule19_are_explicitly_unassessed(self):
        result = self.generate()
        self.assertTrue(
            any(
                item['reason'] == 'sailing_fishing_or_uncertain_status'
                for item in result['audit']['limitedColreg']['excludedPairs']
            )
        )
        scope = copy.deepcopy(result['scope'])
        scope['colregAssumptions']['vesselsInSightAssumed'] = False
        audit = coop.revalidate_plan(result['plan'], scope, result['catalogue'], result['template'])
        self.assertFalse(audit['limitedColreg']['vesselsInSightAssumed'])
        self.assertFalse(audit['limitedColreg']['checks'])
        self.assertTrue(
            any(
                item['reason'] == 'Rule19_not_assessed'
                for item in audit['limitedColreg']['excludedPairs']
            )
        )

    def test_yaml_uses_lotusim_enu_trajectory_contract_and_hash(self):
        result = self.generate()
        yaml = result['scenarioYaml']
        self.assertIn('dataset_sequence:', yaml)
        self.assertIn('  plan_id: ' + result['audit']['inputSha256'], yaml)
        self.assertIn('    model: fremm_observer', yaml)
        self.assertEqual(yaml.count('    trajectory:'), 33)
        event = result['plan']['events'][0]
        point = event['centerPosition']
        self.assertIn(
            '      center_enu_m: ' + json.dumps([point['x'], point['z'], point['y']]), yaml
        )
        self.assertEqual(
            coop.render_scenario_yaml(result['plan'], result['scope'], result['template']), yaml
        )

    def test_legacy_orchestrator_hooks_are_optional_and_policy_runs_before_reservation(self):
        result = self.generate()
        calls = []

        def policy(proposal, reserved, safety):
            calls.append(proposal['instance'])
            return {'b': 'test', 'reason': 'fixture_rejection'}

        with self.assertRaisesRegex(ValueError, 'No safe placement'):
            traffic.Orchestrator().plan(
                result['scope'], result['catalogue'], result['template'], route_policy=policy
            )
        self.assertTrue(calls)


if __name__ == '__main__':
    unittest.main()
