"""Loopback library routes are explicit local edits, never simulator commands."""

import http.client
import json
import unittest

from tests.python.dashboard import test_ops_server as fixtures
from lotusim_image_generator.traffic.editor import TrafficValidationError, TrafficConflictError

ID = '12345678-1234-4234-8234-123456789abc'


class Library:
    def __init__(self):
        self.calls = []
        self.failure = None

    def list(self):
        return {
            'schema': 'lotusim-traffic-library-1',
            'plans': [{'id': ID, 'name': 'Saved traffic', 'status': 'ready'}],
        }

    def get(self, identifier):
        self.calls.append(('get', identifier))
        if identifier != ID:
            raise FileNotFoundError()
        return {
            'schema': 'lotusim-traffic-editor-1',
            'planId': ID,
            'available': True,
            'record': {'status': 'ready'},
            'applied': False,
        }

    def result(self, kind, payload):
        self.calls.append((kind, payload))
        if self.failure:
            raise self.failure
        return {
            'id': ID,
            'record': {'status': 'needs_revalidation' if kind == 'draft' else 'ready'},
            'preview': {'planId': ID},
            'applied': False,
        }

    def generate(self, payload):
        return self.result('generate', payload)

    def save_draft(self, payload):
        return self.result('draft', payload)

    def revalidate(self, identifier):
        return self.result('revalidate', identifier)

    def read_bundle(self, identifier):
        self.calls.append(('zip', identifier))
        return b'PK-fixture'

    def read_file(self, identifier, name):
        self.calls.append(('file', (identifier, name)))
        return b'{"applied":false}\n'


class Source:
    def get(self):
        return {'available': True, 'source': {'id': 'legacy'}, 'applied': False}


class LibraryApiTests(unittest.TestCase):
    request = fixtures.ServerTests.request
    tearDown = fixtures.ServerTests.tearDown

    def setUp(self):
        fixtures.ServerTests.setUp(self)
        self.library = Library()
        self.server.traffic_library = self.library
        self.server.traffic = Source()

    def post(self, path, payload=None, headers=None):
        values = {'Content-Type': 'application/json', 'X-LOTUSim-Traffic': '1'}
        values.update(headers or {})
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        client.request(
            'POST',
            path,
            body=json.dumps({} if payload is None else payload).encode(),
            headers=values,
        )
        response = client.getresponse()
        result = response.status, json.loads(response.read())
        client.close()
        return result

    def test_library_list_and_explicit_selected_plan(self):
        status, _, raw = self.request('/api/traffic/plans')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['plans'][0]['id'], ID)
        status, _, raw = self.request('/api/traffic/plan?planId=' + ID)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['planId'], ID)

    def test_legacy_source_remains_explicit_and_unchanged(self):
        for path in ('/api/traffic/plan', '/api/traffic/plan?planId=source'):
            status, _, raw = self.request(path)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)['source']['id'], 'legacy')
        self.assertFalse(self.library.calls)

    def test_bad_or_missing_plan_id_is_not_a_filesystem_path(self):
        for identifier in ('../../private', 'anything', '', ID.replace('1234', '9876', 1)):
            self.assertEqual(self.request('/api/traffic/plan?planId=' + identifier)[0], 404)
        self.assertEqual(self.request('/api/traffic/plan?planId=source&planId=' + ID)[0], 400)
        self.assertEqual(self.request('/api/traffic/plan?file=secret')[0], 400)

    def test_generate_returns_readable_immutable_plan_without_live_apply(self):
        payload = {
            'name': 'Test',
            'seed': 17,
            'durationSeconds': 120,
            'actionProfile': 'open_water',
        }
        status, result = self.post('/api/traffic/generate', payload)
        self.assertEqual(status, 200)
        self.assertFalse(result['applied'])
        self.assertEqual(self.library.calls, [('generate', payload)])
        self.assertEqual(result['downloadUrl'], '/api/traffic/plans/' + ID + '/plan.json')
        self.assertEqual(result['bundleUrl'], '/api/traffic/plans/' + ID + '/bundle.zip')

    def test_manual_revision_is_saved_to_selected_plan_library(self):
        payload = {'planId': ID, 'baseSha256': 'a' * 64, 'name': 'Manual revision', 'changes': []}
        status, result = self.post('/api/traffic/drafts', payload)
        self.assertEqual(status, 200)
        self.assertEqual(result['record']['status'], 'needs_revalidation')
        self.assertEqual(self.library.calls, [('draft', payload)])

    def test_revalidation_is_explicit_and_cannot_receive_changed_routes(self):
        path = '/api/traffic/plans/' + ID + '/revalidate'
        self.assertEqual(self.post(path, {'changes': []})[0], 400)
        self.assertEqual(self.library.calls, [])
        self.assertEqual(self.post(path)[0], 200)
        self.assertEqual(self.library.calls, [('revalidate', ID)])

    def test_generation_single_flight_prevents_duplicate_workers(self):
        self.server.traffic_generation_slot.acquire()
        try:
            self.assertEqual(self.post('/api/traffic/generate')[0], 409)
        finally:
            self.server.traffic_generation_slot.release()
        self.assertEqual(self.library.calls, [])

    def test_generation_validation_failure_releases_slot(self):
        self.library.failure = TrafficValidationError(
            [{'path': '$.campaign', 'message': 'Unsafe routes'}]
        )
        self.assertEqual(self.post('/api/traffic/generate')[0], 400)
        self.library.failure = None
        self.assertEqual(self.post('/api/traffic/generate')[0], 200)

    def test_conflict_cannot_be_reported_as_success(self):
        self.library.failure = TrafficConflictError('source changed')
        self.assertEqual(self.post('/api/traffic/drafts', {'planId': ID})[0], 409)

    def test_explicit_intent_and_same_origin_are_required(self):
        for path in ('/api/traffic/generate', '/api/traffic/plans/' + ID + '/revalidate'):
            for headers in (
                {'X-LOTUSim-Traffic': ''},
                {'Origin': 'https://evil.invalid'},
                {'Host': 'evil.invalid'},
                {'Sec-Fetch-Site': 'cross-site'},
            ):
                self.assertEqual(self.post(path, headers=headers)[0], 403)
        self.assertEqual(self.library.calls, [])

    def test_bounded_typed_json(self):
        self.assertEqual(
            self.post('/api/traffic/generate', headers={'Content-Type': 'text/plain'})[0], 415
        )
        self.assertEqual(
            self.post('/api/traffic/generate', headers={'Content-Length': '1048577'})[0], 413
        )
        self.assertEqual(self.post('/api/traffic/generate', payload=[])[0], 400)
        self.assertEqual(self.library.calls, [])

    def test_invalid_duplicate_and_nonfinite_json_never_reaches_library(self):
        for raw in (
            b'{"seed":1,"seed":2}',
            b'{"seed":NaN}',
            b'{"seed":1e999}',
            b'null',
            b'bad-json',
        ):
            client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
            client.request(
                'POST',
                '/api/traffic/generate',
                body=raw,
                headers={'Content-Type': 'application/json', 'X-LOTUSim-Traffic': '1'},
            )
            response = client.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            client.close()
        self.assertEqual(self.library.calls, [])

    def test_download_whitelist_and_attachment(self):
        status, headers, body = self.request('/api/traffic/plans/' + ID + '/bundle.zip')
        self.assertEqual(status, 200)
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertEqual(body, b'PK-fixture')
        self.assertEqual(self.request('/api/traffic/plans/' + ID + '/plan.json')[0], 200)
        for filename in ('scope.snapshot.json', 'catalogue.snapshot.json'):
            status, headers, _ = self.request('/api/traffic/plans/' + ID + '/' + filename)
            self.assertEqual(status, 200)
            self.assertEqual(
                headers['Content-Disposition'], 'attachment; filename="' + filename + '"'
            )
        for name in ('../secret', 'library.sqlite3', 'apply', 'scene.py'):
            self.assertEqual(self.request('/api/traffic/plans/' + ID + '/' + name)[0], 404)

    def test_no_execution_route_is_introduced(self):
        for command in ('apply', 'start', 'stop', 'launch'):
            self.assertEqual(self.post('/api/traffic/' + command)[0], 405)


if __name__ == '__main__':
    unittest.main()
