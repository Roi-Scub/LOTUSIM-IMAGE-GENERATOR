"""Fixture-only collector checks: no Docker, ROS, Unity or external services."""

import datetime as dt
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ops_collector import Collector, PROC_PROBE


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.core = self.root / 'LOTUSim'
        self.unity = self.root / 'LOTUSim-Unity-modules'
        (self.core / 'artifacts').mkdir(parents=True)
        (self.unity / 'artifacts').mkdir(parents=True)
        self.now = 1800000000.0

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value, age=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        os.utime(path, (self.now - age, self.now - age))
        return path

    def timestamp(self, age=0):
        return dt.datetime.fromtimestamp(self.now - age, dt.timezone.utc).isoformat()

    def collector(self, **kwargs):
        kwargs.setdefault('docker_enabled', False)
        return Collector(self.core, self.unity, clock=lambda: self.now, **kwargs)

    def campaign(self, name='seq_001', status='complete', age=60, captured=12):
        root = self.unity / 'artifacts/dataset-traffic-agents' / name
        self.write(
            root / 'status.json',
            {'status': status, 'captured': captured, 'expected': 20, 'boxes': 30},
            age,
        )
        return root

    def job(self, campaign, status='detecting', age=0, runtime=None, name='job1'):
        root = campaign / 'visual-observer' / name
        self.write(
            root / 'status.json',
            {
                'status': 'inferencing' if status == 'detecting' else status,
                'images': 12,
                'expected': 12,
            },
            age,
        )
        if status == 'detecting':
            self.write(
                root / 'predictions/status.json',
                {
                    'status': 'detecting',
                    'completed': 3,
                    'expected': 12,
                    'region': 8,
                    'regions': 16,
                    'currentImage': 'i000003.png',
                },
                age,
            )
        if runtime:
            self.write(root / 'predictions/runtime.json', runtime, age)
        return root

    def heartbeat(self, **changes):
        value = {
            'schema': 'lotusim-ops-unity-1',
            'updatedAt': self.timestamp(),
            'editorState': 'ready',
            'isPlaying': False,
            'isPaused': False,
            'isCompiling': False,
            'sceneName': 'MaritimeTrafficAgents',
            'ros': {
                'activeInstanceCount': 1,
                'connectionState': 'reply_observed',
                'connectedCount': 1,
            },
        }
        value.update(changes)
        self.write(self.unity / 'artifacts/operations/unity.json', value)
        return value

    def docker_runner(self, probe='P|gazebo|40\nP|ros|42\nL|ros|10000\n', running=True):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if 'inspect' in argv:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        {'Running': running, 'Status': 'running' if running else 'exited'}
                    ),
                    stderr='',
                )
            if 'exec' in argv:
                return SimpleNamespace(returncode=0, stdout=probe, stderr='')
            return SimpleNamespace(returncode=1, stdout='', stderr='unavailable')

        return run, calls

    def test_empty_checkout_is_unknown_not_faked_live(self):
        state = self.collector().snapshot()
        self.assertEqual(state['unity']['state'], 'unknown')
        self.assertEqual(state['vision']['state'], 'idle')
        self.assertFalse(state['preview']['live'])
        self.assertIsNone(state['preview']['url'])
        self.assertEqual(state['scene']['objects'], [])
        self.assertTrue(state['health']['noRosClientCreated'])

    def test_terminal_history_is_not_an_active_agent(self):
        root = self.campaign()
        self.job(root, status='complete', age=1000)
        state = self.collector().snapshot()
        self.assertEqual(state['vision']['status'], 'complete')
        self.assertFalse(state['vision']['live'])
        self.assertFalse(any(a['state'] == 'running' for a in state['agents']))

    def test_fresh_status_without_pid_is_not_running(self):
        self.job(self.campaign(), age=0)
        vision = self.collector().snapshot()['vision']
        self.assertEqual(vision['state'], 'unknown')
        self.assertFalse(vision['live'])

    def test_old_running_status_becomes_stale(self):
        self.job(self.campaign(), age=120)
        vision = self.collector().snapshot()['vision']
        self.assertEqual(vision['state'], 'stale')
        self.assertFalse(vision['live'])

    def test_orphaned_pid_is_stale_even_with_recent_status(self):
        self.job(self.campaign(), runtime={'pid': 999, 'processBirth': 'known'})
        vision = self.collector(process_probe=lambda r: False).snapshot()['vision']
        self.assertEqual(vision['state'], 'stale')

    def test_confirmed_worker_progress_is_fractional(self):
        self.job(self.campaign(), runtime={'pid': 999, 'processBirth': 'known'})
        vision = self.collector(process_probe=lambda r: True).snapshot()['vision']
        self.assertEqual(vision['state'], 'running')
        self.assertTrue(vision['live'])
        self.assertAlmostEqual(vision['progress'], 3.5 / 12)

    def test_active_unity_worker_corroborates_matching_output(self):
        root = self.job(self.campaign())
        self.heartbeat(rgbObserver={'running': True, 'outputDirectory': str(root)})
        vision = self.collector().snapshot()['vision']
        self.assertTrue(vision['live'])

    def test_stale_unity_cannot_corroborate_active_worker(self):
        root = self.job(self.campaign())
        self.heartbeat(
            updatedAt=self.timestamp(60),
            rgbObserver={'running': True, 'outputDirectory': str(root)},
        )
        self.assertFalse(self.collector().snapshot()['vision']['live'])

    def test_newest_empty_campaign_uses_older_rgb_as_historical(self):
        old = self.campaign('seq_old', age=100)
        image = old / 'rgb/f000011.png'
        image.parent.mkdir()
        image.write_bytes(b'fixture PNG')
        self.campaign('seq_empty', age=1, captured=0)
        state = self.collector().snapshot()
        self.assertEqual(state['capture']['outputName'], 'dataset-traffic-agents/seq_empty')
        self.assertEqual(state['preview']['kind'], 'historical')
        self.assertEqual(state['preview']['campaignName'], 'seq_old')
        self.assertIn('pas une vidéo', state['preview']['label'])
        token = state['preview']['url'].split('/')[2]
        self.assertEqual(self.collector().resolve_file(token), None)

    def test_live_unity_preview_requires_valid_timestamp_and_dimensions(self):
        path = self.unity / 'artifacts/operations/preview.jpg'
        path.parent.mkdir()
        path.write_bytes(b'fixture JPEG')
        self.heartbeat(
            isPlaying=True,
            preview={
                'file': 'preview.jpg',
                'width': 640,
                'height': 360,
                'updatedAt': self.timestamp(),
                'live': True,
                'source': 'dataset_render_texture',
            },
        )
        state = self.collector().snapshot()
        self.assertEqual(state['preview']['kind'], 'live')
        self.assertTrue(state['preview']['live'])
        self.assertEqual(state['preview']['source'], 'dataset_render_texture')
        self.heartbeat(
            isPlaying=True,
            preview={
                'file': 'preview.jpg',
                'width': 0,
                'height': 360,
                'updatedAt': self.timestamp(),
                'live': True,
            },
        )
        self.assertIsNone(self.collector().snapshot()['preview']['url'])

    def test_cached_preview_is_not_live_after_heartbeat_stales(self):
        path = self.unity / 'artifacts/operations/preview.jpg'
        path.parent.mkdir()
        path.write_bytes(b'fixture JPEG')
        self.heartbeat(
            updatedAt=self.timestamp(20),
            preview={
                'file': 'preview.jpg',
                'width': 640,
                'height': 360,
                'updatedAt': self.timestamp(),
                'live': True,
            },
        )
        self.assertFalse(self.collector().snapshot()['preview']['live'])

    def test_frozen_snapshot_does_not_look_live(self):
        campaign = self.campaign(status='capturing', age=0)
        objects = [
            {
                'id': 'ObserverBoat',
                'model': 'fremm_observer',
                'eastM': 0,
                'northM': 10,
                'altitudeM': 0,
            }
        ]
        self.heartbeat(
            isPlaying=True,
            capture={
                'status': 'capturing',
                'captured': 1,
                'expected': 20,
                'outputDirectory': str(campaign),
            },
            lotusim={
                'hasFrame': True,
                'frame': 12,
                'timeSeconds': 0.4,
                'snapshotUpdatedAt': self.timestamp(30),
                'objects': objects,
            },
        )
        state = self.collector().snapshot()
        self.assertTrue(state['capture']['live'])
        self.assertFalse(state['scene']['live'])
        self.assertEqual(state['scene']['ageSeconds'], 30)

    def test_autonomous_unity_capture_is_not_lotusim_sync(self):
        campaign = self.campaign(status='capturing', age=0)
        self.heartbeat(
            isPlaying=True,
            capture={
                'status': 'capturing',
                'captured': 1,
                'expected': 20,
                'outputDirectory': str(campaign),
            },
            lotusim={'hasFrame': False},
        )
        agents = {a['id']: a for a in self.collector().snapshot()['agents']}
        self.assertEqual(agents['renderer']['state'], 'running')
        self.assertEqual(agents['lotusim']['state'], 'idle')

    def test_docker_permission_denied_is_unknown_and_stderr_is_not_exposed(self):
        def run(argv, **kw):
            return SimpleNamespace(returncode=1, stdout='', stderr='SECRET_TOKEN=never show')

        with mock.patch('ops_collector.shutil.which', return_value='/test/docker'):
            state = self.collector(docker_enabled=True, probe_runner=run).snapshot()
        self.assertEqual(state['services'][0]['state'], 'unknown')
        self.assertNotIn('SECRET_TOKEN', json.dumps(state))

    def test_docker_probes_are_cached_and_never_connect_ros(self):
        run, calls = self.docker_runner()
        with mock.patch('ops_collector.shutil.which', return_value='/test/docker'):
            collector = self.collector(docker_enabled=True, probe_runner=run)
            first = collector.snapshot()
            collector.snapshot()
            self.assertEqual(len(calls), 2)
            self.assertEqual(
                next(s for s in first['services'] if s['id'] == 'ros')['state'], 'running'
            )
            self.now += 11
            collector.snapshot()
            self.assertEqual(len(calls), 4)
        self.assertNotIn('ros2 ', PROC_PROBE)
        self.assertNotIn('curl', PROC_PROBE)
        self.assertNotIn('socket', PROC_PROBE)

    def test_docker_running_without_gazebo_and_ros_is_degraded(self):
        self.heartbeat()
        run, _ = self.docker_runner(probe='')
        with mock.patch('ops_collector.shutil.which', return_value='/test/docker'):
            state = self.collector(docker_enabled=True, probe_runner=run).snapshot()
        self.assertEqual(state['health']['state'], 'degraded')

    def test_observed_required_services_and_fresh_unity_are_ready(self):
        self.heartbeat()
        run, _ = self.docker_runner()
        with mock.patch('ops_collector.shutil.which', return_value='/test/docker'):
            state = self.collector(docker_enabled=True, probe_runner=run).snapshot()
        self.assertEqual(state['health']['state'], 'ready')

    def test_stopped_container_is_explicit_not_unknown(self):
        run, calls = self.docker_runner(running=False)
        with mock.patch('ops_collector.shutil.which', return_value='/test/docker'):
            state = self.collector(docker_enabled=True, probe_runner=run).snapshot()
        self.assertEqual(state['services'][0]['state'], 'stopped')
        self.assertEqual(len(calls), 1)

    def test_malformed_or_nonfinite_json_does_not_break_dashboard(self):
        root = self.campaign()
        (root / 'status.json').write_text('{broken')
        self.write(
            self.unity / 'artifacts/operations/unity.json',
            {'schema': 'lotusim-ops-unity-1', 'updatedAt': self.timestamp(), 'bad': float('nan')},
        )
        state = self.collector().snapshot()
        self.assertEqual(state['campaigns'], [])
        self.assertEqual(state['unity']['state'], 'unknown')

    def test_unknown_symlink_and_outside_files_are_not_served(self):
        collector = self.collector()
        outside = self.root / 'secret.txt'
        outside.write_text('not public')
        linked = self.unity / 'artifacts/secret.txt'
        linked.symlink_to(outside)
        self.assertIsNone(collector._asset(linked))
        self.assertIsNone(collector._asset(outside))
        self.assertIsNone(collector.resolve_file('../../secret.txt'))
        good = self.unity / 'artifacts/report.html'
        good.write_text('<html>local</html>')
        url = collector._asset(good, 'report')
        token = url.split('/')[2]
        self.assertEqual(collector.resolve_file(token), good.resolve())

    def test_discovery_does_not_walk_mask_subtrees(self):
        root = self.campaign()
        (root / 'masks/f000000').mkdir(parents=True)
        self.write(root / 'masks/f000000/status.json', {'status': 'running'})
        with mock.patch.object(
            Path, 'rglob', side_effect=AssertionError('Unbounded recursion forbidden')
        ):
            state = self.collector().snapshot()
        self.assertEqual(len(state['campaigns']), 1)

    def test_runtime_planning_is_real_not_archived_animation(self):
        runtime = {
            'schema': 'lotusim-ops-job-1',
            'pid': 999,
            'processBirth': 'known',
            'role': 'traffic_planner',
            'state': 'running',
            'updatedAt': self.timestamp(),
            'currentAgent': 'SafetyAgent',
            'events': [
                {
                    'id': 'e1',
                    'at': self.timestamp(),
                    'source': 'SafetyAgent',
                    'kind': 'plan_approved',
                    'message': 'Plan approuvé',
                }
            ],
        }
        self.write(self.unity / 'artifacts/traffic-agents/ops-status.json', runtime)
        state = self.collector(process_probe=lambda r: True).snapshot()
        self.assertTrue(state['planner']['live'])
        self.assertEqual(
            next(a for a in state['agents'] if a['id'] == 'planner')['state'], 'running'
        )
        self.assertTrue(any(e['message'] == 'Plan approuvé' for e in state['events']))

    def test_dead_planner_runtime_is_stale(self):
        self.write(
            self.core / 'artifacts/traffic-agents/ops-status.json',
            {
                'schema': 'lotusim-ops-job-1',
                'pid': 999,
                'processBirth': 'known',
                'state': 'running',
            },
        )
        state = self.collector(process_probe=lambda r: False).snapshot()
        self.assertEqual(state['planner']['state'], 'stale')
        self.assertFalse(state['planner']['live'])

    def test_json_is_finite_and_has_no_root_paths(self):
        self.campaign()
        state = self.collector().snapshot()
        encoded = json.dumps(state, allow_nan=False)
        self.assertNotIn(str(self.root), encoded)

    def test_empty_error_summaries_are_valid(self):
        collector = self.collector()
        for error in (None, '', '\n'):
            self.assertEqual(collector._safe_error(error), '')
        self.campaign()
        self.assertEqual(collector.snapshot()['campaigns'][0]['error'], '')

    def test_unity_seven_fractional_digits_are_supported(self):
        self.heartbeat(updatedAt=self.timestamp().replace('+00:00', '.1234567+00:00'))
        self.assertTrue(self.collector().snapshot()['unity']['fresh'])

    def test_malformed_nested_fields_do_not_break_snapshot(self):
        root = self.campaign()
        job = self.job(root, status='complete')
        self.write(root / 'traffic-agent-messages.json', {'messages': None})
        self.write(job / 'status.json', {'status': {'invalid': 'phase'}})
        self.heartbeat(
            capture={'outputDirectory': {'not': 'path'}},
            rgbObserver=['bad'],
            lotusim={'hasFrame': True, 'objects': None},
        )
        state = self.collector().snapshot()
        self.assertEqual(state['scene']['objects'], [])

    def test_unity_missing_timestamp_is_unknown(self):
        self.heartbeat(updatedAt=None)
        self.assertEqual(self.collector().snapshot()['unity']['state'], 'unknown')

    def test_process_identity_requires_birth_fingerprint(self):
        collector = self.collector()
        self.assertIsNone(collector._process_alive({'pid': 123}))
        result = SimpleNamespace(returncode=0, stdout='Mon Oct 26 10:00:00 2026\n', stderr='')
        with (
            mock.patch('ops_collector.os.kill'),
            mock.patch.object(collector, '_command', return_value=result.stdout),
        ):
            self.assertTrue(
                collector._process_alive({'pid': 123, 'processBirth': 'Mon Oct 26 10:00:00 2026'})
            )
            self.assertFalse(
                collector._process_alive({'pid': 123, 'processBirth': 'different process birth'})
            )


if __name__ == '__main__':
    unittest.main()
