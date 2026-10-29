import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from lotusim_image_generator.assets.library import MeshLibrary, MAX_UPLOAD
from lotusim_image_generator.dashboard.server import DashboardServer, StateHub


class Collector:
    def snapshot(self):
        return {'health': {'state': 'unknown'}}


class MeshApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.root = Path(self.temp.name).resolve()
        self.core, self.unity = self.root / 'core', self.root / 'unity'
        self.core.mkdir()
        self.unity.mkdir()
        self.hub = StateHub(Collector(), 30)
        self.server = DashboardServer(
            ('127.0.0.1', 0), self.hub, self.root, assets=MeshLibrary(self.core, self.unity)
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def upload(self, headers=None, body=b'broken'):
        request_headers = {
            'X-LOTUSim-Asset-Import': '1',
            'Content-Type': 'multipart/form-data; boundary=qa-boundary',
        }
        request_headers.update(headers or {})
        return self.request('/api/assets/import', 'POST', body, request_headers)

    def test_catalog_is_local_and_does_not_create_storage(self):
        status, headers, body = self.request('/api/assets/catalog')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['assets'], [])
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertFalse((self.core / 'artifacts').exists())

    def test_health_declares_edit_scope(self):
        status, _, data = self.request('/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)['simulationReadOnly'])
        self.assertTrue(json.loads(data)['assetLibraryEditing'])

    def test_cross_origin_import_denied(self):
        self.assertEqual(self.upload({'Origin': 'https://example.org'})[0], 403)
        self.assertEqual(self.upload({'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_missing_intent_header_denied(self):
        status, _, _ = self.request(
            '/api/assets/import', 'POST', b'x', {'Content-Type': 'multipart/form-data; boundary=x'}
        )
        self.assertEqual(status, 403)

    def test_wrong_host_denied(self):
        self.assertEqual(self.upload({'Host': 'evil.example'})[0], 403)

    def test_content_type_required(self):
        self.assertEqual(self.upload({'Content-Type': 'application/json'})[0], 415)

    def test_size_limits_without_reading_body(self):
        self.assertEqual(self.upload({'Content-Length': str(MAX_UPLOAD + 1)})[0], 413)
        self.assertEqual(self.upload({'Content-Length': 'not-number'})[0], 400)
        self.assertEqual(self.upload({'Content-Length': '0'}, b'')[0], 413)

    def test_chunked_transfer_denied(self):
        self.assertEqual(self.upload({'Transfer-Encoding': 'chunked'})[0], 400)

    def test_corrupt_multipart_is_400(self):
        status, _, body = self.upload()
        self.assertEqual(status, 400)
        self.assertNotIn(str(self.core).encode(), body)

    def test_import_lock_prevents_duplicate_parse(self):
        self.server.import_slot.acquire()
        try:
            self.assertEqual(self.upload()[0], 409)
        finally:
            self.server.import_slot.release()

    def test_file_traversal_and_unlisted_id_denied(self):
        for path in (
            '/api/assets/files/unknown/model.obj',
            '/api/assets/files/model/%2e%2e/secret.obj',
            '/api/assets/files/model/.hidden.obj',
            '/api/assets/files/model/a%5cb.obj',
        ):
            self.assertEqual(self.request(path)[0], 404)

    def test_no_mutating_simulation_endpoint_added(self):
        self.assertEqual(self.request('/api/assets/catalog', 'POST')[0], 405)
        self.assertEqual(self.request('/api/assets/import', 'DELETE')[0], 405)


if __name__ == '__main__':
    unittest.main()
