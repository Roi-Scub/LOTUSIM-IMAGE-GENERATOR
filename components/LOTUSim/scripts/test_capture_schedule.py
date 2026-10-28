#!/usr/bin/env python3
"""Pure cadence and fixture cooperative-library regression tests, no engine."""

import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from capture_schedule import (
    build_schedule,
    legacy_count_schedule,
    legacy_frame_schedule,
    validate_plan_schedule,
)
from cooperative_scenario import generate, revalidate_plan, render_scenario_yaml
from campaign_settings import CampaignStore
from traffic_plan_library import TrafficPlanLibrary


class ScheduleTests(unittest.TestCase):
    def test_sixty_seconds_every_two_seconds_is_thirty_simulated_captures(self):
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 2}, 60)
        self.assertEqual(value['frames'], list(range(0, 1800, 60)))
        self.assertEqual(value['count'], 30)
        self.assertEqual(value['effectiveTimesSeconds'], list(range(0, 60, 2)))
        self.assertEqual(value['lastCaptureSeconds'], 58)
        self.assertEqual(value['clock'], 'simulated_seconds')
        self.assertEqual(value['maxQuantizationErrorSeconds'], 0)

    def test_explicit_count_has_start_inclusive_end_exclusive_requested_times(self):
        value = build_schedule({'mode': 'count', 'count': 30}, 60)
        self.assertEqual(value['frames'], list(range(0, 1800, 60)))
        self.assertEqual(value['requestedTimesSeconds'], list(range(0, 60, 2)))
        self.assertIsNone(value['requestedIntervalSeconds'])

    def test_half_up_fractional_intervals_alternate_one_and_two_frames(self):
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 0.05}, 4)
        self.assertEqual(value['frames'][:8], [0, 2, 3, 5, 6, 8, 9, 11])
        self.assertEqual(value['count'], 80)
        self.assertAlmostEqual(value['maxQuantizationErrorSeconds'], 1 / 60)
        self.assertLessEqual(value['maxQuantizationErrorFrames'], 0.5)
        self.assertIsNone(value['effectiveIntervalSeconds'])

    def test_absolute_instants_do_not_accumulate_rounded_stride_drift(self):
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 0.07}, 10)
        self.assertEqual(value['frames'][-1], 298)
        self.assertNotEqual(value['frames'][-1], 2 * (value['count'] - 1))
        for index, frame in enumerate(value['frames']):
            target = Fraction(index * 7, 100) * 30
            self.assertLessEqual(abs(Fraction(frame) - target), Fraction(1, 2))

    def test_minimum_interval_json_float_is_accepted(self):
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 1 / 30}, 4)
        self.assertEqual(value['frames'], list(range(120)))
        self.assertEqual(value['discardedAtOrAfterEndCount'], 1)

    def test_frame_budget_matches_existing_float_duration_formula(self):
        duration = 128 / 30
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 0.1}, duration)
        self.assertEqual(value['simulationFrames'], math.ceil(duration * 30))
        self.assertEqual(value['simulationFrames'], 128)
        self.assertTrue(all(frame < 128 for frame in value['frames']))

    def test_rounding_to_or_after_terminal_frame_is_skipped_not_clamped(self):
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 0.04}, 0.08)
        self.assertEqual(value['frames'], [0, 1])
        self.assertTrue(all(frame < value['simulationFrames'] for frame in value['frames']))
        # Decimal min-interval creates a last sub-end candidate which rounds
        # exactly to the terminal source frame; it is dropped.
        value = build_schedule({'mode': 'interval', 'intervalSeconds': 1 / 30}, 60)
        self.assertEqual(value['count'], 1800)
        self.assertEqual(value['discardedAtOrAfterEndCount'], 1)

    def test_count_one_and_interval_longer_than_episode_capture_t0_only(self):
        for capture in (
            {'mode': 'count', 'count': 1},
            {'mode': 'interval', 'intervalSeconds': 1000},
        ):
            self.assertEqual(build_schedule(capture, 60)['frames'], [0])

    def test_2000_is_a_hard_new_schedule_limit(self):
        self.assertEqual(build_schedule({'mode': 'count', 'count': 2000}, 600)['count'], 2000)
        self.assertEqual(
            build_schedule({'mode': 'interval', 'intervalSeconds': 0.3}, 600)['count'], 2000
        )
        for capture in (
            {'mode': 'count', 'count': 2001},
            {'mode': 'interval', 'intervalSeconds': 0.29999},
            {'mode': 'interval', 'intervalSeconds': 0.299},
        ):
            with self.subTest(capture=capture), self.assertRaises(ValueError):
                build_schedule(capture, 600)

    def test_unrepresentable_count_is_refused_without_dedup_or_clamping(self):
        with self.assertRaisesRegex(ValueError, 'duplicate|represented'):
            build_schedule({'mode': 'count', 'count': 121}, 4.01)

    def test_bad_numbers_shapes_fields_and_boolean_values_are_refused(self):
        bad = [
            None,
            [],
            {},
            {'mode': 'legacy'},
            {'mode': 'count', 'count': True},
            {'mode': 'count', 'count': 0},
            {'mode': 'count', 'count': 2.0},
            {'mode': 'count', 'count': 10**500},
            {'mode': 'count', 'count': 1, 'extra': 1},
            {'mode': 'interval', 'intervalSeconds': True},
            {'mode': 'interval', 'intervalSeconds': 0},
            {'mode': 'interval', 'intervalSeconds': -0.1},
            {'mode': 'interval', 'intervalSeconds': 0.01},
            {'mode': 'interval', 'intervalSeconds': float('inf')},
            {'mode': 'interval', 'intervalSeconds': float('nan')},
            {'mode': 'interval', 'intervalSeconds': 10**500},
            {'mode': 'interval', 'intervalSeconds': '.5'},
            {'mode': 'interval', 'intervalSeconds': 0.5, 'count': 3},
        ]
        for capture in bad:
            with self.subTest(capture=capture), self.assertRaises(ValueError):
                build_schedule(capture, 60)

    def test_invalid_duration_fps_and_count_over_source_frames_are_refused(self):
        for duration in (True, 0, -1, 601, float('inf'), 10**500):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                build_schedule({'mode': 'count', 'count': 1}, duration)
        for fps in (True, 0, 121, 30.0):
            with self.subTest(fps=fps), self.assertRaises(ValueError):
                build_schedule({'mode': 'count', 'count': 1}, 60, fps)
        with self.assertRaises(ValueError):
            build_schedule({'mode': 'count', 'count': 121}, 4)

    def test_legacy_count_placement_is_byte_for_byte_same_frames(self):
        for duration, count in ((60, 30), (180, 3), (4.1, 100), (4, 1), (4, 120)):
            total = math.ceil(duration * 30)
            expected = (
                [0]
                if count == 1
                else [round(index * (total - 1) / (count - 1)) for index in range(count)]
            )
            self.assertEqual(legacy_count_schedule(count, duration)['frames'], expected)
        self.assertNotEqual(
            legacy_count_schedule(30, 60)['frames'],
            build_schedule({'mode': 'count', 'count': 30}, 60)['frames'],
        )

    def test_historical_absent_null_and_empty_frame_arrays_remain_compatible(self):
        scope = {'durationSeconds': 60, 'fps': 30, 'captureEveryFrames': 15}
        for plan in (
            {},
            {'captureFrames': None},
            {'captureFrames': []},
            {'captureFrames': [0, 15, 30]},
        ):
            with self.subTest(plan=plan):
                self.assertIsNone(validate_plan_schedule(plan, scope))

    def test_integrity_copies_frames_context_and_sha_are_all_checked(self):
        schedule = build_schedule({'mode': 'interval', 'intervalSeconds': 2}, 60)
        plan = {'captureFrames': schedule['frames'], 'captureSchedule': schedule}
        scope = {'durationSeconds': 60, 'fps': 30, 'captureSchedule': copy.deepcopy(schedule)}
        self.assertEqual(validate_plan_schedule(plan, scope), schedule)
        for edit in (
            'frames',
            'scope',
            'sha',
            'times',
            'context',
            'missing',
            'boolean_frame',
            'float_fps',
        ):
            p, s = copy.deepcopy(plan), copy.deepcopy(scope)
            if edit == 'frames':
                p['captureFrames'][-1] -= 1
            if edit == 'scope':
                s['captureSchedule']['count'] -= 1
            if edit == 'sha':
                p['captureSchedule']['sha256'] = s['captureSchedule']['sha256'] = '0' * 64
            if edit == 'times':
                p['captureSchedule']['effectiveTimesSeconds'][-1] = s['captureSchedule'][
                    'effectiveTimesSeconds'
                ][-1] = 59
            if edit == 'context':
                s['durationSeconds'] = 61
            if edit == 'missing':
                p.pop('captureSchedule')
            if edit == 'boolean_frame':
                p['captureFrames'][0] = False
            if edit == 'float_fps':
                p['captureSchedule']['fps'] = s['captureSchedule']['fps'] = 30.0
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                validate_plan_schedule(p, s)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-cadence-test-')
        self.addCleanup(self.temporary.cleanup)
        self.core = Path(self.temporary.name) / 'core'
        self.unity = Path(self.temporary.name) / 'unity'
        self.unity.mkdir()
        target = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        target.parent.mkdir(parents=True)
        target.write_bytes((ROOT / 'assets/scenarios/catalogs/traffic_assets.json').read_bytes())
        self.request = {
            'name': 'Cadence test',
            'seed': 20261028,
            'durationSeconds': 60,
            'actionProfile': 'open_water',
        }

    def generate(self, **changes):
        return generate(self.core, self.unity, dict(self.request, **changes))

    def test_only_cadence_change_preserves_all_trajectories_and_geometric_checks(self):
        old = self.generate()
        new = self.generate(capture={'mode': 'interval', 'intervalSeconds': 2})
        self.assertEqual(new['plan']['events'], old['plan']['events'])
        self.assertEqual(new['audit']['checks'], old['audit']['checks'])
        self.assertEqual(new['audit']['motionSha256'], old['audit']['motionSha256'])
        self.assertEqual(new['plan']['captureFrames'], list(range(0, 1800, 60)))
        self.assertEqual(new['captureSummary']['plannedCaptureImages'], 30)

    def test_explicit_schedule_replaces_fast_drone_bursts(self):
        old = self.generate()
        self.assertGreater(len(old['plan']['captureFrames']), 30)
        new = self.generate(capture={'mode': 'count', 'count': 30})
        self.assertEqual(len(new['plan']['captureFrames']), 30)
        self.assertEqual(new['plan']['captureSchedule']['source'], 'explicit')
        self.assertEqual(new['plan']['captureFrames'], list(range(0, 1800, 60)))

    def test_omitted_capture_preserves_legacy_campaign_block_count(self):
        campaign = CampaignStore(self.core, self.unity).defaults()
        old = self.generate(campaign=campaign, blockId='day')
        self.assertEqual(old['plan']['captureFrames'], [0, 900, 1799])
        self.assertEqual(old['plan']['captureSchedule']['source'], 'campaign_block')
        new = self.generate(
            campaign=campaign, blockId='day', capture={'mode': 'interval', 'intervalSeconds': 2}
        )
        self.assertEqual(len(new['plan']['captureFrames']), 30)
        self.assertEqual(new['plan']['traffic']['campaignBlockImagesRequested'], 3)
        self.assertEqual(new['plan']['events'], old['plan']['events'])

    def test_reaudit_and_yaml_export_refuse_changed_capture_frames(self):
        result = self.generate(capture={'mode': 'interval', 'intervalSeconds': 2})
        plan = copy.deepcopy(result['plan'])
        plan['captureFrames'][1] += 1
        audit = revalidate_plan(plan, result['scope'], result['catalogue'], result['template'])
        self.assertFalse(audit['approved'])
        self.assertTrue(any('Capture' in line for line in audit['errors']))
        with self.assertRaisesRegex(ValueError, 'export refused'):
            render_scenario_yaml(plan, result['scope'], result['template'])

    def test_yaml_informative_schedule_binds_count_frames_and_sha(self):
        result = self.generate(capture={'mode': 'interval', 'intervalSeconds': 2})
        yaml = result['scenarioYaml']
        self.assertIn('capture_schedule:', yaml)
        self.assertIn('  clock: simulated_seconds', yaml)
        self.assertIn('  count: 30', yaml)
        self.assertIn('  interval_seconds: 2.0', yaml)
        self.assertIn('  sha256: ' + result['plan']['captureSchedule']['sha256'], yaml)
        self.assertTrue(result['audit']['captureScheduleValidated'])

    def test_library_summary_and_manifest_artifacts_are_persisted_and_bound(self):
        library = TrafficPlanLibrary(self.core, self.unity)
        response = library.generate(
            dict(self.request, capture={'mode': 'interval', 'intervalSeconds': 2})
        )
        record = library.list()['plans'][0]
        self.assertEqual(record['plannedCaptureImages'], 30)
        self.assertEqual(record['captureMode'], 'interval')
        self.assertEqual(record['captureIntervalSeconds'], 2)
        self.assertEqual(record['captureDurationSeconds'], 60)
        preview = library.get(response['id'])
        self.assertEqual(preview['captureSchedule']['count'], 30)
        manifest = json.loads(library.read_file(response['id'], 'manifest.json'))
        self.assertEqual({item['name'] for item in manifest['artifacts']}, set(manifest['files']))
        for item in manifest['artifacts']:
            self.assertEqual(
                {key: item[key] for key in ('sha256', 'bytes')}, manifest['files'][item['name']]
            )
            raw = library.read_file(response['id'], item['name'])
            self.assertEqual(item['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(item['bytes'], len(raw))


if __name__ == '__main__':
    unittest.main()
