#!/usr/bin/env python3
"""Fixture-only preparation lifecycle, historical evidence and collector checks."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_settings import (
    ADAPTER_PATH,
    CampaignSecurityError,
    CampaignStore,
    CampaignValidationError,
)
from ops_collector import Collector
from scene_preparation_status import (
    ACTIVE_SECONDS,
    MAX_STATUS,
    PreparationStatus,
    ScenePreparationStorageError,
    observe_preparation,
)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-preparation-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core, self.unity = self.root / 'core', self.root / 'unity'
        catalog = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalog.parent.mkdir(parents=True)
        catalog.write_text(
            json.dumps(
                {
                    'schema': 'lotusim-traffic-catalogue-1',
                    'assets': [
                        {
                            'model': 'buoy',
                            'category': 'buoy',
                            'domain': 'moored',
                            'heightM': 3,
                            'maxSpeedMps': 0,
                            'altitudeM': [0, 0],
                        }
                    ],
                }
            )
        )
        adapter = self.unity / ADAPTER_PATH
        adapter.parent.mkdir(parents=True)
        adapter.write_text('// fixture')
        self.store = CampaignStore(self.core, self.unity)
        self.plan = self.store.defaults()
        self.now = [1800000000.0]

    @property
    def status_path(self):
        return self.core / 'artifacts/operations/scene-preparation.json'

    def observe(self, **kwargs):
        return observe_preparation(
            self.core, now=self.now[0], process_alive=lambda pid: True, **kwargs
        )

    def writer(self):
        return PreparationStatus(self.core, str(uuid.uuid4()), self.plan, clock=lambda: self.now[0])

    def prepared(self, name=None):
        if name:
            self.plan['name'] = name
        with (
            patch(
                'campaign_settings.engine_catalog',
                return_value=[
                    {'id': 'unity', 'preparationAvailable': True, 'runtimeDetected': False}
                ],
            ),
            patch(
                'campaign_settings.PreparationStatus',
                side_effect=lambda core, identifier, plan: PreparationStatus(
                    core, identifier, plan, clock=lambda: self.now[0]
                ),
            ),
        ):
            return self.store.prepare(self.plan)

    def bundle(self, result):
        return self.core / 'artifacts/campaign-settings/prepared' / result['id']

    def alter_status(self, **changes):
        source = json.loads(self.status_path.read_bytes())
        source.update(changes)
        self.status_path.write_text(json.dumps(source))

    def test_no_history_agent_is_idle_without_writes(self):
        agent, events = self.observe()
        self.assertEqual(agent['state'], 'idle')
        self.assertEqual(agent['group'], 'Préparation')
        self.assertFalse(agent['live'])
        self.assertEqual(events, [])
        self.assertFalse((self.core / 'artifacts').exists())

    def test_real_owned_writer_has_running_steps_and_events(self):
        with self.writer() as status:
            status.step('planner')
            agent, events = self.observe()
            self.assertEqual(agent['state'], 'running')
            self.assertTrue(agent['live'])
            self.assertFalse(agent['historical'])
            self.assertEqual(agent['steps'][0]['state'], 'running')
            self.assertEqual(len(events), 2)
            self.assertEqual(agent['links'], {})
            status.step('scene_script_builder')
            agent, _ = self.observe()
            self.assertEqual(
                [step['state'] for step in agent['steps']], ['complete', 'running', 'idle']
            )

    def test_collector_snapshot_with_actual_running_writer_never_calls_runtime_dict_probe(self):
        with self.writer() as status:
            status.step('planner')
            collector = Collector(
                self.core,
                self.unity,
                clock=lambda: self.now[0],
                docker_enabled=False,
                process_probe=lambda runtime: runtime.get('pid') == 42,
            )
            result = collector.snapshot()
            self.assertEqual(result['agents'][0]['id'], 'scene_preparation')
            self.assertEqual(result['agents'][0]['state'], 'running')
            self.assertTrue(result['preparation']['live'])
            self.assertTrue(
                any(event['source'] == 'scene_preparation' for event in result['events'])
            )
            self.assertEqual(len(result['agents']), 8)

    def test_reused_pid_token_is_never_live(self):
        with self.writer() as status:
            status.step('planner')
            self.alter_status(processToken='another-interpreter')
            agent, _ = self.observe()
            self.assertEqual(agent['state'], 'stale')
            self.assertFalse(agent['live'])
            self.assertFalse(any(step['state'] == 'running' for step in agent['steps']))

    def test_foreign_pid_even_if_alive_does_not_prove_the_writer_incarnation(self):
        with self.writer() as status:
            status.step('planner')
            self.alter_status(pid=os.getpid() + 100)
            self.assertEqual(self.observe()[0]['state'], 'stale')

    def test_dead_pid_or_old_active_timestamp_is_stale(self):
        with self.writer() as status:
            status.step('planner')
            agent, _ = observe_preparation(
                self.core, now=self.now[0], process_alive=lambda pid: False
            )
            self.assertEqual(agent['state'], 'stale')
            self.now[0] += ACTIVE_SECONDS + 1
            self.assertEqual(self.observe()[0]['state'], 'stale')

    def test_future_active_timestamp_is_not_live(self):
        with self.writer() as status:
            status.step('planner')
            self.now[0] -= 20
            self.assertEqual(self.observe()[0]['state'], 'stale')

    def test_context_without_verified_completion_is_failed(self):
        with self.writer() as status:
            status.step('planner')
        self.assertEqual(self.observe()[0]['state'], 'failed')

    def test_error_is_failed_bounded_and_redacted(self):
        with self.assertRaises(ValueError):
            with self.writer() as status:
                status.step('scene_script_builder')
                raise ValueError('/Users/private/secret/model.obj ' + 'x' * 2000)
        agent, events = self.observe()
        self.assertEqual(agent['state'], 'failed')
        self.assertNotIn('/Users/private', json.dumps([agent, events]))
        self.assertLess(len(agent['detail']), 300)
        self.assertEqual(agent['steps'][1]['state'], 'failed')
        self.assertFalse(agent['nativeValidated'])

    def test_success_exists_only_after_all_artifacts_written_and_verified(self):
        original = self.store._write_file
        snapshots = []

        def write(descriptor, name, data):
            snapshots.append((name, self.observe()[0]['state']))
            return original(descriptor, name, data)

        with patch.object(self.store, '_write_file', side_effect=write):
            result = self.prepared()
        self.assertTrue(all(state == 'running' for _, state in snapshots))
        self.assertEqual(snapshots[-1][0], 'manifest.json')
        agent, events = self.observe()
        self.assertEqual(agent['state'], 'complete')
        self.assertEqual(agent['campaignId'], result['id'])
        self.assertFalse(agent['live'])
        self.assertTrue(all(step['state'] == 'complete' for step in agent['steps']))
        self.assertEqual(
            agent['links']['bundleUrl'], '/api/settings/prepared/' + result['id'] + '/bundle.zip'
        )
        self.assertTrue(any('moteur non exécuté' in event['message'] for event in events))

    def test_save_and_validate_never_emit_preparation(self):
        self.store.validate(self.plan)
        self.store.save(self.plan)
        self.assertFalse(self.status_path.exists())
        self.assertEqual(self.observe()[0]['state'], 'idle')

    def test_invalid_prepare_is_failed_not_a_success_or_written_bundle(self):
        self.plan['totalImages'] += 1
        with self.assertRaises(CampaignValidationError):
            self.prepared()
        self.assertEqual(self.observe()[0]['state'], 'failed')
        self.assertFalse((self.core / 'artifacts/campaign-settings/prepared').exists())

    def test_failed_adapter_does_not_reuse_older_success(self):
        first = self.prepared('First')
        with patch('campaign_settings.prepare_engine', side_effect=ValueError('mesh unavailable')):
            with self.assertRaises(CampaignValidationError):
                self.prepared('Second')
        agent, _ = self.observe()
        self.assertEqual(agent['state'], 'failed')
        self.assertEqual(agent['campaignName'], 'Second')
        self.assertNotEqual(agent['campaignId'], first['id'])
        self.assertEqual(agent['links'], {})

    def test_failed_file_write_never_marks_complete(self):
        with patch.object(self.store, '_write_file', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.prepared()
        self.assertEqual(self.observe()[0]['state'], 'failed')

    def test_older_attempt_cannot_overwrite_newer_status(self):
        with self.writer() as older:
            older.step('planner')
            with self.writer() as newer:
                newer.step('scene_script_builder')
                newer_id = newer.data['campaignId']
                older.complete()
                current = json.loads(self.status_path.read_bytes())
                self.assertEqual(current['campaignId'], newer_id)
                self.assertEqual(current['phase'], 'preparing')

    def test_historical_backfill_two_existing_packages_is_not_active(self):
        first = self.prepared('First')
        second = self.prepared('Second')
        os.utime(self.bundle(first), (self.now[0] - 100, self.now[0] - 100))
        os.utime(self.bundle(second), (self.now[0], self.now[0]))
        self.status_path.unlink()
        agent, events = self.observe()
        self.assertEqual(agent['state'], 'complete')
        self.assertEqual(agent['campaignName'], 'Second')
        self.assertTrue(agent['historical'])
        self.assertFalse(agent['live'])
        self.assertTrue(events[0]['historical'])
        self.assertEqual(len(agent['steps']), 3)

    def test_recent_empty_directory_is_never_an_active_agent(self):
        directory = self.core / 'artifacts/campaign-settings/prepared' / str(uuid.uuid4())
        directory.mkdir(parents=True)
        self.assertEqual(self.observe()[0]['state'], 'idle')

    def test_missing_or_corrupt_trace_cannot_backfill(self):
        result = self.prepared()
        self.status_path.unlink()
        (self.bundle(result) / 'engine-agent.json').write_text('{}')
        self.assertEqual(self.observe()[0]['state'], 'idle')

    def test_modified_campaign_cannot_backfill(self):
        result = self.prepared()
        self.status_path.unlink()
        (self.bundle(result) / 'campaign.json').write_text('{}')
        self.assertEqual(self.observe()[0]['state'], 'idle')

    def test_deleted_or_modified_scene_script_invalidates_complete(self):
        result = self.prepared()
        path = self.bundle(result) / 'scene_unity.cs'
        path.write_text('// changed')
        self.assertEqual(self.observe()[0]['state'], 'failed')
        self.status_path.unlink()
        self.assertEqual(self.observe()[0]['state'], 'idle')
        path.unlink()
        self.assertEqual(self.observe()[0]['state'], 'idle')

    def test_cross_job_trace_even_with_updated_inventory_hash_is_rejected(self):
        first = self.prepared('First')
        second = self.prepared('Second')
        self.status_path.unlink()
        trace = (self.bundle(first) / 'engine-agent.json').read_bytes()
        (self.bundle(second) / 'engine-agent.json').write_bytes(trace)
        manifest_path = self.bundle(second) / 'manifest.json'
        manifest = json.loads(manifest_path.read_bytes())
        for row in manifest['artifacts']:
            if row['name'] == 'engine-agent.json':
                row.update(bytes=len(trace), sha256=hashlib.sha256(trace).hexdigest())
        manifest_path.write_text(json.dumps(manifest))
        # The valid older package remains the only acceptable evidence.
        self.assertEqual(self.observe()[0]['campaignId'], first['id'])

    def test_malformed_or_oversized_status_falls_back_safely(self):
        result = self.prepared()
        self.status_path.write_bytes(b'x' * (MAX_STATUS + 1))
        self.assertEqual(self.observe()[0]['campaignId'], result['id'])
        self.status_path.write_bytes(b'{"phase":NaN}')
        self.assertTrue(self.observe()[0]['historical'])

    def test_symlinked_status_is_not_followed_or_replaced(self):
        self.status_path.parent.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.write_text('private')
        self.status_path.symlink_to(outside)
        self.assertEqual(self.observe()[0]['state'], 'idle')
        with self.assertRaises(CampaignSecurityError):
            self.prepared()
        self.assertTrue(self.status_path.is_symlink())
        self.assertEqual(outside.read_text(), 'private')

    def test_symlinked_operations_directory_cannot_escape(self):
        artifacts = self.core / 'artifacts'
        artifacts.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (artifacts / 'operations').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(CampaignSecurityError):
            self.prepared()
        self.assertEqual(list(outside.iterdir()), [])

    def test_package_symlink_cannot_backfill_or_leak(self):
        result = self.prepared()
        self.status_path.unlink()
        path = self.bundle(result) / 'scene_unity.cs'
        path.unlink()
        outside = self.root / 'outside'
        outside.write_text('private')
        path.symlink_to(outside)
        self.assertEqual(self.observe()[0]['state'], 'idle')
        self.assertNotIn('private', json.dumps(self.observe()))

    def test_journal_is_bounded(self):
        with self.writer() as status:
            for index in range(100):
                status.step('planner')
            self.assertEqual(len(json.loads(self.status_path.read_bytes())['events']), 16)
            self.assertEqual(len(self.observe()[1]), 16)


if __name__ == '__main__':
    unittest.main()
