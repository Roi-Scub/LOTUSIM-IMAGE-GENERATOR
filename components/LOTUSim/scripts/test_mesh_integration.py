import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mesh_integration as m

OBJ = b'v 0 0 0\nv 2 0 0\nv 0 1 0\nv 0 0 2\nf 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n'


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.core, self.unity = self.root / 'LOTUSim', self.root / 'LOTUSim-Unity-modules'
        (self.core / 'assets/models').mkdir(parents=True)
        (self.core / 'assets/scenarios/catalogs').mkdir(parents=True)
        self.unity.mkdir()
        self.import_id = 'import-' + str(uuid.uuid4())
        self.folder = self.core / 'artifacts/mesh-library/imports' / self.import_id
        (self.folder / 'files').mkdir(parents=True)
        (self.folder / 'files/mesh.obj').write_bytes(OBJ)
        self.receipt = {'schema': 'lotusim-imported-mesh-1', 'entryFile': 'mesh.obj',
                        'sha256': {'mesh.obj': m.digest(OBJ)},
                        'asset': {'id': self.import_id, 'category': 'buoy', 'label': 'My original buoy',
                                  'license': 'CC0', 'sourceUrl': 'https://example.org/own-model',
                                  'preview': {'upAxis': 'Y'}}}
        m.atomic(self.folder / 'asset.json', self.receipt)
        self.service = m.MeshIntegrationService(self.core, self.unity)

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def write_receipt(self):
        m.atomic(self.folder / 'asset.json', self.receipt)

    def prepare(self):
        return m.prepare_worker(self.core, self.unity, self.import_id)

    def acknowledge(self, request=None, mutate=None):
        request = request or self.prepare()
        context = m.load_context(self.core, self.unity, self.import_id)
        prefab_path = 'Assets/Prefabs/' + context['model'] + '.prefab'
        prefab = self.unity / prefab_path; prefab.parent.mkdir(parents=True, exist_ok=True)
        prefab.write_text('%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: ' + context['model'] + '\n')
        guid = uuid.uuid4().hex; Path(str(prefab) + '.meta').write_text('fileFormatVersion: 2\nguid: ' + guid + '\n')
        geometry = next(value for value in request['files'] if value['path'] == 'geometry.bytes')
        result = {'schema': m.RESULT_SCHEMA, 'id': self.import_id, 'model': context['model'],
                  'revisionSha256': context['revision'], 'requestSha256': m.digest((self.folder / 'unity-request.json').read_bytes()),
                  'status': 'ready', 'prefabPath': prefab_path, 'prefabGuid': guid,
                  'prefabSha256': m.digest(prefab.read_bytes()), 'addressableKey': context['model'],
                  'unityProjectPath': str(self.unity), 'geometrySha256': geometry['sha256']}
        if mutate:
            result.update(mutate)
        m.atomic(self.folder / 'unity-result.json', result)
        return result

    def ready(self):
        self.acknowledge(); self.service.tick()
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'ready')
        self.assertEqual(len(m.ready_imports(self.core, self.unity)), 1)

    def test_defaults_are_conservative(self):
        self.assertEqual(m.normalize_options('buoy', 'Y', None),
                         dict(metresPerUnit=1.0, forwardAxis='+Z', draftM=0.0, maxSpeedMps=0.0, maxAltitudeM=0.0))
        self.assertEqual(m.normalize_options('drone', 'Z', {})['maxAltitudeM'], 120)

    def test_unknown_category_and_malformed_category_fail(self):
        for category in ('unknown', {}, None):
            with self.assertRaises(m.MeshError):
                m.normalize_options(category, 'Y', {})

    def test_unknown_option_fails(self):
        with self.assertRaises(m.MeshError):
            m.normalize_options('buoy', 'Y', {'execute': 'something'})

    def test_parallel_axes_fail(self):
        with self.assertRaises(m.MeshError):
            m.normalize_options('airplane', 'Y', {'forwardAxis': '+Y'})

    def test_nonfinite_scale_and_boolean_speed_fail(self):
        for options in ({'metresPerUnit': float('nan')}, {'maxSpeedMps': True}, {'maxSpeedMps': 351}):
            with self.assertRaises(m.MeshError):
                m.normalize_options('drone', 'Y', options)

    def test_draft_limits_match_unity_contract(self):
        self.assertEqual(m.normalize_options('sailboat', 'Y', {'draftM': 25})['draftM'], 25)
        for value in (-.001, 25.001, 1000):
            with self.assertRaises(m.MeshError):
                m.normalize_options('sailboat', 'Y', {'draftM': value})

    def test_large_ship_buffer_is_accepted_by_unity_contract(self):
        self.receipt['asset']['category'] = 'container_ship'
        self.receipt['asset']['integrationOptions'] = {'metresPerUnit': 200}
        self.write_receipt()
        request = self.prepare()
        self.assertEqual(request['dimensions']['lengthM'], 400)
        self.assertEqual(request['profile']['bufferM'], 200)
        self.acknowledge(request); self.service.tick()
        self.assertEqual(m.ready_imports(self.core, self.unity)[0]['bufferM'], 200)

    def test_oversized_model_fails_before_unity_request(self):
        self.receipt['asset']['integrationOptions'] = {'metresPerUnit': 501}
        self.write_receipt()
        with self.assertRaisesRegex(m.MeshError, 'Dimensions hors limites Unity'):
            self.prepare()
        self.assertFalse((self.folder / 'unity-request.json').exists())

    def test_moored_speed_and_sea_altitude_fail(self):
        with self.assertRaises(m.MeshError):
            m.normalize_options('buoy', 'Y', {'maxSpeedMps': 1})
        with self.assertRaises(m.MeshError):
            m.normalize_options('sailboat', 'Y', {'maxAltitudeM': 1})

    def test_queued_before_worker_and_no_catalogue(self):
        status = m.integration_public(self.core, self.unity, self.import_id)
        self.assertEqual(status['state'], 'queued')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])
        self.assertFalse(m._catalog_path(self.core).exists())

    def test_preparation_is_immutable_and_waits_for_unity(self):
        first = self.prepare(); context = m.load_context(self.core, self.unity, self.import_id)
        before = {p.name: m.digest(p.read_bytes()) for p in (self.folder / first['bundleDirectory']).iterdir()}
        second = self.prepare()
        self.assertEqual(first, second)
        self.assertEqual(before, {p.name: m.digest(p.read_bytes()) for p in (self.folder / second['bundleDirectory']).iterdir()})
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'waiting_unity')
        self.assertIsNotNone(m._request(context))
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_status_file_alone_cannot_promote_ready(self):
        context = m.load_context(self.core, self.unity, self.import_id)
        m.set_status(context, 'ready', 'not a proof')
        self.assertNotEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'ready')

    def test_ack_without_prefab_is_not_ready(self):
        self.acknowledge()
        context = m.load_context(self.core, self.unity, self.import_id)
        (self.unity / ('Assets/Prefabs/' + context['model'] + '.prefab')).unlink()
        self.service.tick()
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_correct_ack_registers_only_additional_catalogue(self):
        base = self.core / 'assets/scenarios/catalogs/traffic_assets.json'; base.write_text('{"keep":"unchanged"}')
        self.ready()
        self.assertEqual(base.read_text(), '{"keep":"unchanged"}')
        record = m.ready_imports(self.core, self.unity)[0]
        self.assertEqual(record['category'], 'buoy'); self.assertEqual(record['classId'], 1)
        self.assertEqual(record['maxSpeedMps'], 0)
        model = self.core / 'assets/models' / record['model']
        self.assertTrue((model / 'model.sdf').is_file())
        self.assertIn('revisions/' + record['revisionSha256'] + '/gazebo.obj', (model / 'model.sdf').read_text())
        self.assertIn('Declared licence: CC0', (model / 'ATTRIBUTION.txt').read_text())
        self.assertEqual(json.loads((model / 'auto-import.json').read_text())['credit']['license'], 'CC0')

    def test_ack_wrong_project_is_not_ready(self):
        self.acknowledge(mutate={'unityProjectPath': str(self.root / 'other-project')})
        self.service.tick(); self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_ack_wrong_geometry_hash_is_not_ready(self):
        self.acknowledge(mutate={'geometrySha256': '0' * 64})
        self.service.tick(); self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_ack_wrong_request_hash_is_not_ready(self):
        self.acknowledge(mutate={'requestSha256': '0' * 64})
        self.service.tick(); self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_prefab_change_invalidates_ready(self):
        self.ready(); record = m.ready_imports(self.core, self.unity)[0]
        (self.unity / ('Assets/Prefabs/' + record['model'] + '.prefab')).write_text('changed by user')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_guid_change_invalidates_ready(self):
        self.ready(); record = m.ready_imports(self.core, self.unity)[0]
        (self.unity / ('Assets/Prefabs/' + record['model'] + '.prefab.meta')).write_text('guid: ' + uuid.uuid4().hex)
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_duplicate_guid_metadata_is_not_a_valid_acknowledgement(self):
        result = self.acknowledge(); prefab = self.unity / result['prefabPath']
        Path(str(prefab) + '.meta').write_text('guid: ' + result['prefabGuid'] + '\nguid: ' + uuid.uuid4().hex + '\n')
        self.service.tick(); self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_source_change_invalidates_ready(self):
        self.ready(); (self.folder / 'files/mesh.obj').write_bytes(OBJ + b'# changed\n')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'failed')

    def test_bundle_change_invalidates_ready(self):
        self.ready(); context = m.load_context(self.core, self.unity, self.import_id)
        (self.folder / 'prepared' / context['revision'] / 'gazebo.obj').write_text('changed')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_model_sdf_change_invalidates_ready_and_is_not_overwritten(self):
        self.ready(); context = m.load_context(self.core, self.unity, self.import_id)
        sdf = self.core / 'assets/models' / context['model'] / 'model.sdf'; sdf.write_text('keep manual sdf')
        self.service.tick()
        self.assertEqual(sdf.read_text(), 'keep manual sdf')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'failed')

    def test_unrelated_model_directory_is_not_overwritten(self):
        context = m.load_context(self.core, self.unity, self.import_id)
        model = self.core / 'assets/models' / context['model']; model.mkdir(); (model / 'manual.txt').write_text('keep')
        self.acknowledge(); self.service.tick()
        self.assertEqual((model / 'manual.txt').read_text(), 'keep')
        self.assertFalse((model / 'model.sdf').exists())
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_registry_edit_is_not_trusted(self):
        self.ready(); path = m._catalog_path(self.core); value = json.loads(path.read_text())
        value['assets'][0]['maxSpeedMps'] = 99; m.atomic(path, value)
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_corrupt_registry_records_are_ignored(self):
        m.atomic(m._catalog_path(self.core), {'schema': m.CATALOG_SCHEMA, 'assets': [None, {'importId': []}]})
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_options_change_immediately_hides_old_ready_model(self):
        self.ready(); result = self.service.request(self.import_id, {'metresPerUnit': 1.5})
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_retry_same_options_reuses_bundle_but_invalidates_old_ack(self):
        self.ready(); old = m.load_context(self.core, self.unity, self.import_id)
        self.service.request(self.import_id, old['options'])
        current = m.load_context(self.core, self.unity, self.import_id)
        self.assertEqual(old['revision'], current['revision']); self.assertNotEqual(old['token'], current['token'])
        self.assertEqual(m.ready_imports(self.core, self.unity), [])
        self.prepare(); self.assertIsNone(m._acknowledged(current, m._request(current)))

    def test_late_worker_cannot_publish_obsolete_options(self):
        import mesh_convert
        actual = mesh_convert.convert
        def changed(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.service.request(self.import_id, {'metresPerUnit': 2})
            return result
        with mock.patch.object(mesh_convert, 'convert', side_effect=changed):
            with self.assertRaises(m.MeshError):
                self.prepare()
        self.assertFalse((self.folder / 'unity-request.json').exists())
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['options']['metresPerUnit'], 2)

    def test_failed_unity_result_is_reported_without_host_path(self):
        self.acknowledge(mutate={'status': 'failed', 'error': '/private/path/not-for-ui'})
        self.service.tick(); status = m.integration_public(self.core, self.unity, self.import_id)
        self.assertEqual(status['state'], 'failed'); self.assertNotIn('/private/path', status['message'])

    def test_tick_queues_conversion_once_then_waits(self):
        def work(context):
            self.prepare()
        with mock.patch.object(self.service, '_run_worker', side_effect=work) as run:
            self.service.tick(); self.service.tick()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'waiting_unity')

    def test_failed_conversion_is_not_retried_endlessly(self):
        with mock.patch.object(self.service, '_run_worker', side_effect=m.MeshError('Unsupported format')) as run:
            self.service.tick(); self.service.tick()
            self.assertEqual(run.call_count, 1)
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'failed')

    def test_source_symlink_is_refused(self):
        source = self.folder / 'files/mesh.obj'; source.unlink()
        elsewhere = self.root / 'elsewhere.obj'; elsewhere.write_bytes(OBJ); source.symlink_to(elsewhere)
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'failed')

    def test_unsafe_identifier_refused(self):
        for value in ('../other', 'import-../other', 'import-' + '0' * 32, None):
            with self.assertRaises(m.MeshError):
                m.root_for(self.core, value)

    def test_legacy_receipt_can_find_primary_preview_url(self):
        self.receipt.pop('entryFile')
        self.receipt['asset']['preview']['url'] = '/api/assets/files/' + self.import_id + '/mesh.obj'; self.write_receipt()
        self.assertEqual(m.load_context(self.core, self.unity, self.import_id)['entry'], 'mesh.obj')

    def test_missing_worker_python_fails_without_launching_unity(self):
        context = m.load_context(self.core, self.unity, self.import_id)
        with mock.patch.object(m.subprocess, 'Popen') as process:
            with self.assertRaises(m.MeshError):
                self.service._run_worker(context)
        process.assert_not_called()

    def test_public_invalid_receipt_returns_controlled_state(self):
        (self.folder / 'asset.json').write_text('not JSON')
        result = m.integration_public(self.core, self.unity, self.import_id)
        self.assertEqual(result['state'], 'failed'); self.assertIn('message', result)

    def test_nonfinite_options_rejected_before_writing(self):
        with self.assertRaises(m.MeshError):
            self.service.request(self.import_id, {'draftM': float('nan')})
        self.assertFalse((self.folder / 'integration-options.json').exists())

    def test_corrupt_override_cannot_fall_back_to_old_ready_options(self):
        self.ready(); (self.folder / 'integration-options.json').write_text('broken')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])
        self.assertEqual(m.integration_public(self.core, self.unity, self.import_id)['state'], 'failed')

    def test_unknown_catalogue_is_preserved(self):
        path = m._catalog_path(self.core); path.write_text('{"unrelated":"keep"}')
        self.acknowledge(); self.service.tick()
        self.assertEqual(path.read_text(), '{"unrelated":"keep"}')
        self.assertEqual(m.ready_imports(self.core, self.unity), [])

    def test_verified_hash_cache_avoids_repeated_reads(self):
        path = self.folder / 'files/mesh.obj'
        self.assertEqual(m.file_digest(path, 10000)[0], m.digest(OBJ))
        with mock.patch.object(m, 'regular_bytes', side_effect=AssertionError('cache miss')):
            self.assertEqual(m.file_digest(path, 10000)[0], m.digest(OBJ))

    def test_hash_cache_detects_changed_content_even_with_restored_mtime(self):
        path = self.folder / 'files/mesh.obj'; original = os.stat(path)
        old = m.file_digest(path, 10000)[0]
        path.write_bytes(OBJ.replace(b'v 2', b'v 3'))
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        self.assertNotEqual(m.file_digest(path, 10000)[0], old)

    def test_hash_cache_detects_replaced_inode(self):
        path = self.folder / 'files/mesh.obj'; old = m.file_digest(path, 10000)[0]
        replacement = self.folder / 'replacement.obj'; replacement.write_bytes(OBJ.replace(b'v 2', b'v 4'))
        os.replace(replacement, path)
        self.assertNotEqual(m.file_digest(path, 10000)[0], old)


if __name__ == '__main__':
    unittest.main()
