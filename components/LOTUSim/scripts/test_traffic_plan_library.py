"""SQLite library fixture tests: no native engine, services or runtime writes."""

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import traceback
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from traffic_plan_editor import (
    TrafficConflictError,
    TrafficPlanSecurityError,
    TrafficValidationError,
)
from traffic_plan_library import TrafficPlanLibrary, CONTEXT_VERSION


def _process_generate(core, unity, bundle, request, queue):
    try:
        library = TrafficPlanLibrary(core, unity, generator=lambda *args: copy.deepcopy(bundle))
        queue.put(('ok', library.generate(request)['id']))
    except Exception as error:
        queue.put(('error', traceback.format_exc()))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-library-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core = self.root / 'core'
        self.core.mkdir()
        self.unity = self.root / 'unity'
        self.unity.mkdir()
        self.plan = {
            'schema': 'lotusim-unity-encounters-1',
            'events': [
                {
                    'instance': 'boat_001',
                    'modelName': 'sailboat',
                    'category': 'sailboat',
                    'startSeconds': 0,
                    'endSeconds': 24,
                    'centerSeconds': 12,
                    'centerPosition': {'x': 0, 'y': 0, 'z': 100},
                    'velocity': {'x': 1, 'y': 0, 'z': 0},
                }
            ],
            'traffic': {'continuousSafetyApproved': True},
        }
        self.scope = {
            'schema': 'lotusim-traffic-scope-1',
            'name': 'FixtureScenario',
            'durationSeconds': 24,
            'observer': {'speedKnots': 0, 'headingDeg': 0, 'turnDeg': 0},
            'water': {'eastMinM': -5000, 'eastMaxM': 5000, 'northMinM': -5000, 'northMaxM': 5000},
        }
        self.catalogue = {
            'schema': 'lotusim-traffic-catalogue-1',
            'assets': [
                {'model': 'sailboat', 'category': 'sailboat', 'domain': 'sea', 'maxSpeedMps': 4.5}
            ],
        }
        self.audit = {
            'schema': 'fixture-audit-1',
            'approved': True,
            'pairChecks': 1,
            'checks': [],
            'continuousSafetyApproved': True,
            'notCertified': True,
            'fullColregCompliance': False,
        }
        self.request = {
            'name': 'Fixture scenario',
            'seed': 123,
            'durationSeconds': 24,
            'actionProfile': 'crossing',
        }
        self.db = self.core / 'artifacts/traffic-library/library.sqlite3'
        self.library = self.new_library()

    def generator(self, core, unity, payload):
        return copy.deepcopy(
            {
                'plan': self.plan,
                'scope': self.scope,
                'catalogue': self.catalogue,
                'template': {},
                'audit': self.audit,
                'messages': {'messages': []},
                'scenarioYaml': 'name: FixtureScenario\nagents: {}\n',
            }
        )

    def new_library(self, **kwargs):
        defaults = {
            'clock': lambda: 1800000000,
            'generator': self.generator,
            'auditor': lambda *args: copy.deepcopy(self.audit),
            'scenario_writer': lambda *args: 'name: RevalidatedScenario\nagents: {}\n',
        }
        defaults.update(kwargs)
        return TrafficPlanLibrary(self.core, self.unity, **defaults)

    def generated(self):
        return self.library.generate(copy.deepcopy(self.request))

    def draft_payload(self, parent, **changes):
        change = {
            'actorId': 'boat_001',
            'centerENU': {'eastM': 10, 'northM': 110, 'altitudeM': 0},
            'speedMps': 2,
            'headingDeg': 90,
        }
        change.update(changes)
        return {
            'planId': parent['id'],
            'baseSha256': parent['record']['planSha256'],
            'name': 'Manual revision',
            'changes': [change],
        }

    def test_empty_list_is_read_only_and_not_a_default_active_plan(self):
        self.assertEqual(self.library.list()['plans'], [])
        self.assertFalse((self.core / 'artifacts').exists())

    def test_sqlite_is_standard_persistent_and_restarts_without_serialize_api(self):
        result = self.generated()
        identifier = result['id']
        self.assertEqual(self.db.read_bytes()[:16], b'SQLite format 3\0')
        with sqlite3.connect('file:' + str(self.db) + '?mode=ro', uri=True) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM plans').fetchone()[0], 1)
        restarted = self.new_library()
        dto = restarted.get(identifier)
        self.assertEqual(dto['planId'], identifier)
        self.assertEqual(dto['record']['name'], 'Fixture scenario')
        self.assertTrue(dto['record']['ready'])
        self.assertFalse(dto['applied'])
        self.assertEqual(dto['source']['kind'], 'library_record')
        self.assertIsNone(dto['source']['engineId'])
        self.assertEqual(dto['record']['sourceContextVersion'], CONTEXT_VERSION)
        self.assertEqual(len(restarted.list()['plans']), 1)
        self.assertFalse((self.core / 'artifacts/operations').exists())
        self.assertFalse((self.unity / 'Assets').exists())

    def test_plan_context_audit_and_export_hashes_are_bound(self):
        result = self.generated()
        identifier = result['id']
        plan = self.library.read_file(identifier, 'plan.json')
        self.assertEqual(hashlib.sha256(plan).hexdigest(), result['record']['planSha256'])
        audit = json.loads(self.library.read_file(identifier, 'safety-report.json'))
        self.assertEqual(audit['planSha256'], result['record']['planSha256'])
        self.assertEqual(audit['contextSha256'], result['record']['contextSha256'])
        manifest = json.loads(self.library.read_file(identifier, 'manifest.json'))
        for name, details in manifest['files'].items():
            raw = self.library.read_file(identifier, name)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), details['sha256'])
            self.assertEqual(len(raw), details['bytes'])
        self.assertNotIn(str(self.root), json.dumps(result, allow_nan=False))

    def test_concurrent_generations_do_not_lose_committed_records(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            ids = list(
                pool.map(lambda _: self.new_library().generate(self.request)['id'], range(10))
            )
        self.assertEqual(len(set(ids)), 10)
        self.assertEqual({row['id'] for row in self.library.list()['plans']}, set(ids))

    def test_processes_share_the_advisory_lock_and_keep_all_transactions(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue()
        bundle = self.generator(self.core, self.unity, self.request)
        processes = [
            context.Process(
                target=_process_generate,
                args=(str(self.core), str(self.unity), bundle, self.request, queue),
            )
            for _ in range(4)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
                self.fail('Library process exceeded test deadline')
            self.assertEqual(process.exitcode, 0)
        results = [queue.get(timeout=2) for _ in processes]
        self.assertTrue(all(status == 'ok' for status, _ in results), results)
        self.assertEqual(len(self.library.list()['plans']), 4)

    def test_manual_revision_is_immutable_child_and_invalidates_old_approval(self):
        parent = self.generated()
        original = self.library.read_file(parent['id'], 'plan.json')
        result = self.library.save_draft(self.draft_payload(parent))
        self.assertNotEqual(result['id'], parent['id'])
        self.assertEqual(result['record']['parentId'], parent['id'])
        self.assertEqual(result['record']['kind'], 'manual_revision')
        self.assertEqual(result['record']['auditStatus'], 'requires_revalidation')
        self.assertFalse(result['record']['ready'])
        self.assertTrue(result['preview']['requiresRevalidation'])
        self.assertFalse(result['preview']['plan']['traffic']['continuousSafetyApproved'])
        self.assertEqual(result['preview']['actors'][0]['centerENU']['eastM'], 10)
        self.assertEqual(self.library.read_file(parent['id'], 'plan.json'), original)
        self.assertFalse((self.core / 'artifacts/traffic-drafts').exists())
        with self.assertRaises(TrafficPlanSecurityError):
            self.library.read_file(result['id'], 'scenario.yaml')

    def test_stale_hash_is_409_compatible_without_creating_revision(self):
        parent = self.generated()
        payload = self.draft_payload(parent)
        payload['baseSha256'] = '0' * 64
        with self.assertRaises(TrafficConflictError):
            self.library.save_draft(payload)
        self.assertEqual(len(self.library.list()['plans']), 1)

    def test_failed_revalidation_is_saved_not_ready_and_does_not_modify_trajectories(self):
        parent = self.generated()
        revision = self.library.save_draft(self.draft_payload(parent))
        original = self.library.read_file(revision['id'], 'plan.json')
        failing = self.new_library(
            auditor=lambda *args: {
                'approved': False,
                'reason': 'Predicted close approach',
                'checks': [{'safe': False}],
            }
        )
        result = failing.revalidate(revision['id'])
        self.assertEqual(result['record']['auditStatus'], 'failed')
        self.assertFalse(result['record']['ready'])
        self.assertFalse(result['applied'])
        self.assertEqual(result['record']['parentId'], revision['id'])
        self.assertEqual(failing.read_file(result['id'], 'plan.json'), original)
        self.assertEqual(
            self.library.get(revision['id'])['record']['auditStatus'], 'requires_revalidation'
        )
        with self.assertRaises(TrafficPlanSecurityError):
            failing.read_file(result['id'], 'scenario.yaml')

    def test_successful_revalidation_binds_same_unchanged_plan_and_exports_yaml(self):
        parent = self.generated()
        revision = self.library.save_draft(self.draft_payload(parent))
        result = self.library.revalidate(revision['id'])
        self.assertTrue(result['record']['ready'])
        self.assertEqual(result['record']['auditStatus'], 'approved')
        self.assertEqual(result['record']['planSha256'], revision['record']['planSha256'])
        self.assertEqual(result['record']['contextSha256'], revision['record']['contextSha256'])
        self.assertEqual(
            self.library.read_file(result['id'], 'scenario.yaml'),
            b'name: RevalidatedScenario\nagents: {}\n',
        )
        self.assertFalse(result['preview']['requiresRevalidation'])

    def test_scenario_export_rejection_downgrades_an_approved_audit(self):
        parent = self.generated()

        def rejected(*args):
            raise ValueError('Unsafe collision')

        library = self.new_library(scenario_writer=rejected)
        result = library.revalidate(parent['id'])
        self.assertFalse(result['record']['ready'])
        self.assertEqual(result['record']['auditStatus'], 'failed')
        self.assertFalse(result['preview']['audit']['continuousSafetyApproved'])

    def test_nonready_bundle_is_json_and_audit_only_with_no_executable_yaml(self):
        parent = self.generated()
        revision = self.library.save_draft(self.draft_payload(parent))
        first = self.library.read_bundle(revision['id'])
        self.assertEqual(first, self.library.read_bundle(revision['id']))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertNotIn('scenario.yaml', archive.namelist())
            self.assertIn('safety-report.json', archive.namelist())
            self.assertTrue(
                all('/' not in name and '\\' not in name for name in archive.namelist())
            )
            for name in archive.namelist():
                self.assertEqual(archive.read(name), self.library.read_file(revision['id'], name))
        with zipfile.ZipFile(io.BytesIO(self.library.read_bundle(parent['id']))) as archive:
            self.assertIn('scenario.yaml', archive.namelist())

    def test_waypoint_revision_is_unsupported_not_audited_as_old_straight_plan(self):
        parent = self.generated()
        payload = self.draft_payload(parent)
        payload['changes'] = [
            {
                'actorId': 'boat_001',
                'controlPoints': [
                    {'timeSeconds': 0, 'eastM': 0, 'northM': 0, 'altitudeM': 0},
                    {'timeSeconds': 24, 'eastM': 12, 'northM': 12, 'altitudeM': 0},
                ],
            }
        ]
        revision = self.library.save_draft(payload)
        with mock.patch.object(
            self.library, 'auditor', side_effect=AssertionError('Do not audit uncompiled old event')
        ):
            result = self.library.revalidate(revision['id'])
        self.assertEqual(result['record']['auditStatus'], 'unsupported')
        self.assertFalse(result['record']['ready'])

    def test_legacy_source_snapshot_and_revision_commit_together(self):
        source = self.unity / 'artifacts/traffic-agents/plan.json'
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(self.plan))
        for relative, value in (
            ('scope.snapshot.json', self.scope),
            ('catalogue.snapshot.json', self.catalogue),
        ):
            (source.parent / relative).write_text(json.dumps(value))
        displayed = self.library.editor.get()
        payload = self.draft_payload(
            {'id': 'source', 'record': {'planSha256': displayed['baseSha256']}}
        )
        result = self.library.save_draft(payload)
        rows = self.library.list()['plans']
        self.assertEqual(len(rows), 2)
        snapshot = next(row for row in rows if row['kind'] == 'legacy_snapshot')
        self.assertEqual(result['record']['parentId'], snapshot['id'])
        self.assertEqual(json.loads(self.library.read_file(snapshot['id'], 'plan.json')), self.plan)
        self.assertEqual(source.read_text(), json.dumps(self.plan))
        self.library.save_draft(payload)
        self.assertEqual(len(self.library.list()['plans']), 3)  # Reuse immutable source snapshot.

    def test_generation_constraint_errors_are_useful_validation_errors(self):
        def rejected(*args):
            raise ValueError('No safe placement for sailboat_001')

        with self.assertRaises(TrafficValidationError) as caught:
            self.new_library(generator=rejected).generate(self.request)
        self.assertIn('Scénario refusé', caught.exception.validation['errors'][0]['message'])
        self.assertIn('sailboat_001', caught.exception.validation['errors'][0]['message'])
        self.assertFalse(self.db.exists())

    def test_campaign_block_metadata_persists_across_revisions(self):
        request = dict(
            self.request,
            blockId='night',
            campaign={
                'name': 'Campaign',
                'engine': 'godot',
                'totalImages': 9,
                'blocks': [{'id': 'day', 'images': 4}, {'id': 'night', 'images': 5}],
            },
        )
        parent = self.library.generate(request)
        self.assertEqual(parent['record']['metadata']['blockId'], 'night')
        self.assertEqual(parent['record']['metadata']['engineId'], 'godot')
        self.assertEqual(parent['record']['metadata']['requestedImages'], 5)
        revised = self.library.save_draft(self.draft_payload(parent))
        self.assertEqual(revised['record']['metadata'], parent['record']['metadata'])

    def test_unsafe_ids_names_and_paths_never_become_sql_or_filesystem_paths(self):
        parent = self.generated()
        for identifier in ('../library.sqlite3', "' OR 1=1 --", '/tmp/secret', '', None):
            with self.assertRaises(TrafficPlanSecurityError):
                self.library.get(identifier)
        for name in ('../scenario.yaml', '/tmp/secret', 'library.sqlite3', 'other.json'):
            with self.assertRaises(TrafficPlanSecurityError):
                self.library.read_file(parent['id'], name)
        self.assertEqual(len(self.library.list()['plans']), 1)

    def test_symlinked_storage_and_database_are_refused_without_outside_writes(self):
        outside = self.root / 'outside'
        outside.mkdir()
        artifacts = self.core / 'artifacts'
        artifacts.mkdir()
        (artifacts / 'traffic-library').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(TrafficPlanSecurityError):
            self.generated()
        self.assertEqual(list(outside.iterdir()), [])
        (artifacts / 'traffic-library').unlink()
        self.generated()
        original = self.db.read_bytes()
        outside_file = outside / 'private.sqlite3'
        outside_file.write_bytes(original)
        self.db.unlink()
        self.db.symlink_to(outside_file)
        with self.assertRaises((TrafficPlanSecurityError, OSError)):
            self.library.list()
        self.assertEqual(outside_file.read_bytes(), original)

    def test_tampered_payload_or_metadata_fails_integrity_before_export(self):
        parent = self.generated()
        with sqlite3.connect(str(self.db)) as connection:
            connection.execute('UPDATE plans SET name=? WHERE id=?', ('Tampered', parent['id']))
        with self.assertRaises(TrafficPlanSecurityError):
            self.library.get(parent['id'])
        with self.assertRaises(TrafficPlanSecurityError):
            self.library.list()

    def test_failed_transaction_preserves_previous_database_bytes(self):
        self.generated()
        before = self.db.read_bytes()
        with mock.patch('traffic_plan_library.MAX_RECORDS', 1):
            with self.assertRaises(ValueError):
                self.generated()
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(len(self.library.list()['plans']), 1)

    def test_bounded_nonfinite_requests_do_not_create_a_database(self):
        for payload in (
            None,
            {'name': 'x', 'seed': float('nan')},
            {'name': 'x', 'data': 'a' * (1024 * 1024)},
        ):
            with self.assertRaises(TrafficValidationError):
                self.library.generate(payload)
        self.assertFalse(self.db.exists())

    def test_real_cooperative_generator_and_independent_collision_reaudit(self):
        assets = []
        for model in ('buoy', 'buoy_navigation_ozzy'):
            assets.append(
                {
                    'model': model,
                    'category': 'buoy',
                    'domain': 'moored',
                    'lengthM': 1.3,
                    'beamM': 1.3,
                    'heightM': 3,
                    'bufferM': 15,
                    'priority': 1,
                    'speedUnit': 'kn',
                    'speedMin': 0,
                    'speedMax': 0,
                    'maxSpeedMps': 0,
                    'altitudeM': [0, 0],
                    'rangeM': [220, 650],
                    'evidence': 'fixture_assumption',
                }
            )
        assets.append(
            {
                'model': 'sailboat',
                'category': 'sailboat',
                'domain': 'sea',
                'lengthM': 12,
                'beamM': 3.5,
                'heightM': 18,
                'bufferM': 45,
                'priority': 3,
                'speedUnit': 'kn',
                'speedMin': 3,
                'speedMax': 6,
                'maxSpeedMps': 4.5,
                'altitudeM': [0, 0],
                'rangeM': [450, 1500],
                'evidence': 'fixture_assumption',
            }
        )
        catalog = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalog.parent.mkdir(parents=True)
        catalog.write_text(json.dumps({'schema': 'lotusim-traffic-catalogue-1', 'assets': assets}))
        library = self.new_library(generator=None, auditor=None, scenario_writer=None)
        generated = library.generate(
            dict(self.request, seed=20261028, durationSeconds=180, actionProfile='open_water')
        )
        self.assertTrue(generated['record']['ready'])
        self.assertFalse(generated['preview']['audit']['fullColregCompliance'])
        first, second = [
            actor for actor in generated['preview']['actors'] if actor['domain'] == 'moored'
        ]
        revised = library.save_draft(
            {
                'planId': generated['id'],
                'baseSha256': generated['record']['planSha256'],
                'name': 'Deliberate overlap',
                'changes': [
                    {
                        'actorId': second['id'],
                        'centerENU': first['centerENU'],
                        'speedMps': 0,
                        'headingDeg': 0,
                    }
                ],
            }
        )
        audit = library.revalidate(revised['id'])
        self.assertFalse(audit['record']['ready'])
        self.assertEqual(audit['record']['status'], 'refused')
        self.assertTrue(
            any(check.get('safe') is False for check in audit['preview']['audit']['checks'])
        )
        with self.assertRaises(TrafficPlanSecurityError):
            library.read_file(audit['id'], 'scenario.yaml')


if __name__ == '__main__':
    unittest.main(verbosity=2)
