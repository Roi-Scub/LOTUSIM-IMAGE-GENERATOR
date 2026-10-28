"""Isolated ready-import/campaign and handler tests; no TCP server or Unity process."""
import copy
from http.client import HTTPMessage
import io
import json
from pathlib import Path
import sys
import types
import unittest
from unittest import mock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import campaign_settings as settings
import mesh_integration as integration
from mesh_library import MeshLibrary
from ops_dashboard import DashboardHandler
import test_mesh_integration as fixtures


BASE_ASSETS = [{'model': 'buoy', 'category': 'buoy', 'domain': 'moored', 'heightM': 3,
                'lengthM': 1.3, 'beamM': 1.3, 'maxSpeedMps': 0, 'altitudeM': [0, 0]}]


class ImportedCampaignTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntegrationTests('test_queued_before_worker_and_no_catalogue')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.core, self.unity = self.fixture.core, self.fixture.unity
        self.base = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        self.base.write_text(json.dumps({'schema': 'lotusim-traffic-catalogue-1', 'assets': BASE_ASSETS}))
        adapter = self.unity / settings.ADAPTER_PATH; adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.write_text('// isolated adapter presence fixture\n')
        self.store = settings.CampaignStore(self.core, self.unity)
        self.model = integration.load_context(self.core, self.unity, self.fixture.import_id)['model']

    def plan(self, imported=True):
        plan = self.store.defaults()
        if imported:
            for block in plan['blocks']:
                block['objects'][0]['model'] = self.model
        return plan

    def ready(self):
        self.fixture.ready()
        return integration.ready_imports(self.core, self.unity)[0]

    def test_pending_import_is_not_in_scenario_catalogue(self):
        self.assertEqual([a['model'] for a in self.store.catalog()['assets']], ['buoy'])
        result = self.store.validate(self.plan())
        self.assertFalse(result['valid'])
        self.assertTrue(any(e['path'].endswith('.model') for e in result['errors']))

    def test_prepared_waiting_unity_import_is_not_selectable(self):
        self.fixture.prepare()
        self.assertFalse(self.store.validate(self.plan())['valid'])
        self.assertEqual([a['model'] for a in self.store.catalog()['assets']], ['buoy'])

    def test_prefab_ack_without_owned_gazebo_registration_is_not_selectable(self):
        self.fixture.acknowledge()
        self.assertFalse(self.store.validate(self.plan())['valid'])
        self.assertEqual([a['model'] for a in self.store.catalog()['assets']], ['buoy'])

    def test_ready_import_is_merged_with_label_and_class_id(self):
        record = self.ready(); catalogue = self.store.catalog()['assets']
        imported = next(a for a in catalogue if a['model'] == self.model)
        self.assertEqual(len(catalogue), 2)
        self.assertEqual(imported['label'], 'My original buoy')
        self.assertEqual(imported['classId'], 1)
        self.assertEqual(imported['prefabGuid'], record['prefabGuid'])
        self.assertEqual(imported['maxSpeedMps'], 0)
        self.assertTrue(self.store.validate(self.plan())['valid'])

    def test_ready_import_does_not_modify_base_catalogue(self):
        before = self.base.read_bytes(); self.ready()
        self.store.catalog(); self.store.prepare(self.plan())
        self.assertEqual(self.base.read_bytes(), before)

    def test_prepared_manifest_pins_exact_import_revision_and_prefab(self):
        record = self.ready(); prepared = self.store.prepare(self.plan())
        pins = prepared['manifest']['importedAssetRevisions']
        self.assertEqual(pins, [{key: record[key] for key in
            ('model', 'revisionSha256', 'requestSha256', 'prefabGuid', 'prefabSha256')}])
        stored = json.loads(self.store.read_prepared(prepared['id'], 'manifest.json'))
        self.assertEqual(stored['importedAssetRevisions'], pins)

    def test_multiple_uses_pin_one_revision(self):
        self.ready(); plan = self.plan()
        plan['blocks'][0]['objects'].append(dict(plan['blocks'][0]['objects'][0], id='another-instance'))
        prepared = self.store.prepare(plan)
        self.assertEqual(len(prepared['manifest']['importedAssetRevisions']), 1)

    def test_base_only_campaign_has_no_import_pins(self):
        self.ready(); prepared = self.store.prepare(self.plan(False))
        self.assertEqual(prepared['manifest']['importedAssetRevisions'], [])

    def test_manifest_does_not_pin_an_unused_ready_import(self):
        first = self.ready()
        fixture = self.fixture
        prior = fixture.import_id, fixture.folder, fixture.receipt
        second_id = 'import-' + str(uuid.uuid4())
        second_folder = self.core / 'artifacts/mesh-library/imports' / second_id
        (second_folder / 'files').mkdir(parents=True)
        (second_folder / 'files/mesh.obj').write_bytes(fixtures.OBJ)
        receipt = copy.deepcopy(fixture.receipt); receipt['asset']['id'] = second_id
        receipt['asset']['label'] = 'Another ready model not requested in this plan'
        integration.atomic(second_folder / 'asset.json', receipt)
        try:
            fixture.import_id, fixture.folder, fixture.receipt = second_id, second_folder, receipt
            fixture.acknowledge(); fixture.service.tick()
        finally:
            fixture.import_id, fixture.folder, fixture.receipt = prior
        self.assertEqual(len(integration.ready_imports(self.core, self.unity)), 2)
        prepared = self.store.prepare(self.plan())
        self.assertEqual([a['model'] for a in prepared['manifest']['importedAssetRevisions']], [first['model']])

    def test_prepared_manifest_is_immutable_after_import_options_change(self):
        self.ready(); prepared = self.store.prepare(self.plan())
        before = self.store.read_prepared(prepared['id'], 'manifest.json')
        self.fixture.service.request(self.fixture.import_id, {'metresPerUnit': 2})
        self.assertFalse(self.store.validate(self.plan())['valid'])
        self.assertEqual(self.store.read_prepared(prepared['id'], 'manifest.json'), before)

    def test_new_preparation_pins_new_revision_after_reintegration(self):
        first = self.ready(); old = self.store.prepare(self.plan())
        self.fixture.service.request(self.fixture.import_id, {'metresPerUnit': 2})
        self.fixture.acknowledge(); self.fixture.service.tick()
        current = integration.ready_imports(self.core, self.unity)[0]
        self.assertNotEqual(current['revisionSha256'], first['revisionSha256'])
        new = self.store.prepare(self.plan())
        self.assertEqual(new['manifest']['importedAssetRevisions'][0]['revisionSha256'], current['revisionSha256'])
        old_read = json.loads(self.store.read_prepared(old['id'], 'manifest.json'))
        self.assertEqual(old_read['importedAssetRevisions'][0]['revisionSha256'], first['revisionSha256'])

    def test_modified_prefab_is_removed_from_available_settings(self):
        record = self.ready()
        (self.unity / ('Assets/Prefabs/' + record['model'] + '.prefab')).write_text('user edit')
        self.assertFalse(self.store.validate(self.plan())['valid'])
        self.assertFalse(any(a['model'] == self.model for a in self.store.catalog()['assets']))

    def test_imported_moored_object_cannot_exceed_declared_speed(self):
        self.ready(); plan = self.plan(); plan['blocks'][0]['objects'][0]['speedMps'] = 1
        result = self.store.validate(plan)
        self.assertFalse(result['valid'])
        self.assertTrue(any(e['path'].endswith('.speedMps') for e in result['errors']))

    def test_import_conflicting_with_base_name_fails_without_overwrite(self):
        record = self.ready()
        self.base.write_text(json.dumps({'schema': 'lotusim-traffic-catalogue-1', 'assets': BASE_ASSETS + [record]}))
        before = self.base.read_bytes()
        with self.assertRaises(ValueError):
            self.store.catalog()
        self.assertEqual(self.base.read_bytes(), before)

    def test_air_import_uses_only_declared_speed_and_altitude_limits(self):
        self.fixture.receipt['asset']['category'] = 'drone'; self.fixture.write_receipt()
        self.fixture.service.request(self.fixture.import_id, {'maxSpeedMps': 7, 'maxAltitudeM': 300})
        self.ready(); plan = self.plan()
        for block in plan['blocks']:
            block['objects'][0].update(altitudeM=50, speedMps=6)
        self.assertTrue(self.store.validate(plan)['valid'])
        plan['blocks'][0]['objects'][0]['speedMps'] = 8
        self.assertFalse(self.store.validate(plan)['valid'])

    def test_mesh_library_ready_status_matches_campaign_catalogue(self):
        self.ready()
        catalogue = MeshLibrary(self.core, self.unity).catalog()['assets']
        imported = next(a for a in catalogue if a['id'] == self.fixture.import_id)
        self.assertEqual(imported['integrationStatus'], 'integrated')
        self.assertEqual(imported['integration']['state'], 'ready')
        self.assertEqual(imported['dimensions']['heightM'], integration.ready_imports(self.core, self.unity)[0]['heightM'])

    def test_ready_import_does_not_duplicate_its_generated_mesh_card(self):
        self.ready()
        catalogue = MeshLibrary(self.core, self.unity).catalog()['assets']
        generated = [a for a in catalogue if a['id'] in (self.model, self.fixture.import_id)]
        self.assertEqual(len(generated), 1, 'The generated Gazebo backing mesh is not a second user model')


class RetryHandlerTests(unittest.TestCase):
    """Exercise the real handler methods with in-memory request bytes, no sockets."""
    def setUp(self):
        self.fixture = fixtures.IntegrationTests('test_queued_before_worker_and_no_catalogue')
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)

    def invoke(self, body=b'{"options":{}}', headers=None, import_id=None, integration=None, path=None):
        handler = object.__new__(DashboardHandler)
        handler.path = path or '/api/assets/' + (import_id or self.fixture.import_id) + '/integrate'
        handler.headers = HTTPMessage()
        values = {'Host': '127.0.0.1:8766', 'Content-Type': 'application/json',
                  'Content-Length': str(len(body)), 'X-LOTUSim-Asset-Import': '1'}
        values.update(headers or {})
        for key, value in values.items():
            if value is not None:
                handler.headers[key] = value
        server = types.SimpleNamespace(integration=self.fixture.service if integration is None else integration,
            assets=types.SimpleNamespace(_updated=123), server_address=('127.0.0.1', 8766), settings=None)
        handler.server = server
        handler.connection = types.SimpleNamespace(settimeout=lambda value: None)
        handler.rfile = io.BytesIO(body)
        result = []
        handler._json = lambda status, payload, *args, **kwargs: result.append((status, payload))
        handler.do_POST()
        return result[0], server

    def test_valid_retry_queues_options_and_invalidates_library_cache_without_process(self):
        with mock.patch.object(integration.subprocess, 'Popen') as process:
            (status, body), server = self.invoke()
        self.assertEqual(status, 202); self.assertEqual(body['integration']['state'], 'queued')
        self.assertEqual(server.assets._updated, 0); process.assert_not_called()

    def test_retry_accepts_only_known_options(self):
        (status, _), _ = self.invoke(b'{"options":{"execute":"something"}}')
        self.assertEqual(status, 400)

    def test_retry_requires_intent_header(self):
        (status, _), _ = self.invoke(headers={'X-LOTUSim-Asset-Import': None})
        self.assertEqual(status, 403)

    def test_retry_denies_cross_origin_and_wrong_host(self):
        for headers in ({'Origin': 'https://example.org'}, {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            (status, _), _ = self.invoke(headers=headers)
            self.assertEqual(status, 403)

    def test_retry_requires_json_and_rejects_chunked(self):
        for headers in ({'Content-Type': 'text/plain'}, {'Transfer-Encoding': 'chunked'}):
            (status, _), _ = self.invoke(headers=headers)
            self.assertEqual(status, 415)

    def test_retry_size_limit_and_invalid_length(self):
        for value, expected in (('8193', 413), ('0', 413), ('no', 400)):
            (status, _), _ = self.invoke(headers={'Content-Length': value})
            self.assertEqual(status, expected)

    def test_retry_rejects_truncated_body(self):
        (status, _), _ = self.invoke(headers={'Content-Length': '15'})
        self.assertEqual(status, 400)

    def test_retry_rejects_duplicate_nonfinite_or_wrong_json_shape(self):
        for body in (b'{"options":{},"options":{}}', b'{"options":{"metresPerUnit":NaN}}',
                     b'[]', b'{"options":{},"extra":1}', b'{"not_options":{}}'):
            (status, _), _ = self.invoke(body)
            self.assertEqual(status, 400)

    def test_retry_rejects_invalid_uuid_and_traversal_route(self):
        (status, _), _ = self.invoke(import_id='import-00000000-0000-0000-0000-000000000000')
        self.assertEqual(status, 400)
        (status, _), _ = self.invoke(path='/api/assets/../elsewhere/integrate')
        self.assertEqual(status, 405)

    def test_retry_unavailable_service_is_503(self):
        # Invoke the method directly because the simple namespace sentinel
        # above is not a service; actual absence is represented by None.
        handler = object.__new__(DashboardHandler); result = []
        handler.server = types.SimpleNamespace(integration=None)
        handler._json = lambda status, payload: result.append(status)
        handler._asset_integrate(self.fixture.import_id)
        self.assertEqual(result, [503])

    def test_retry_disk_error_has_no_host_path_in_response(self):
        service = mock.Mock(); service.request.side_effect = OSError('/private/sensitive/path')
        (status, payload), _ = self.invoke(integration=service)
        self.assertEqual(status, 503)
        self.assertNotIn('/private/sensitive', json.dumps(payload))


if __name__ == '__main__':
    unittest.main()
