import copy
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ops_dashboard import DashboardServer, StateHub, safe_child


class FakeCollector:
    def __init__(self, root):
        self.root = root
        self.failed = False
        self.calls = 0
        self.files = {}

    def snapshot(self):
        self.calls += 1
        if self.failed:
            raise ValueError('do not expose this private diagnostic')
        return {
            'schema': 'test',
            'generatedAt': '2026-10-26T00:00:00Z',
            'health': {'state': 'ready'},
            'services': [{'id': 'docker', 'state': 'running'}],
            'agents': [{'id': 'rgb', 'state': 'running'}],
            'preview': {'live': True},
            'calls': self.calls,
        }

    def resolve_file(self, token):
        if token in self.files:
            return self.files[token]
        return (
            self.root / 'report/index.html'
            if token == 'report000'
            else self.root / 'picture.png' if token == 'picture00' else None
        )

    def file_url(self, path, kind='file'):
        path = Path(path).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError:
            return None
        token = 'registered' + str(len(self.files))
        self.files[token] = path
        return '/files/' + token + '/' + path.name


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ui = self.root / 'ui'
        self.ui.mkdir()
        for name, text in [
            ('index.html', '<!doctype html><title>Local ops</title>'),
            ('app.js', 'console.log(1)'),
            ('styles.css', 'body{}'),
            ('alerts.js', 'console.log("local alerts")'),
            ('operations-ux.css', '.alerts-center{}'),
        ]:
            (self.ui / name).write_text(text)
        self.data = self.root / 'artifacts'
        (self.data / 'report/input').mkdir(parents=True)
        (self.data / 'report/index.html').write_text('<img src="input/frame.png">')
        (self.data / 'report/input/frame.png').write_bytes(b'png')
        (self.data / 'picture.png').write_bytes(b'png')
        (self.data / 'secrets.env').write_text('not an allowed format')
        self.collector = FakeCollector(self.data)
        self.hub = StateHub(self.collector, 30)
        self.hub.refresh()
        self.server = DashboardServer(('127.0.0.1', 0), self.hub, self.ui, (self.data,))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.hub.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, method='GET', headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        client.request(method, path, headers=headers or {})
        response = client.getresponse()
        data = response.read()
        status = response.status
        meta = dict(response.getheaders())
        client.close()
        return status, meta, data

    def test_static_and_api_have_security_headers(self):
        status, headers, body = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'Local ops', body)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        status, _, body = self.request('/api/state')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['calls'], 1)

    def test_get_does_not_reprobe_docker(self):
        self.request('/api/state?refresh=1')
        self.request('/api/state?refresh=1')
        self.assertEqual(self.collector.calls, 1)

    def test_bad_host_and_cross_origin_denied(self):
        self.assertEqual(self.request('/api/state', headers={'Host': 'evil.example'})[0], 403)
        self.assertEqual(
            self.request('/api/state', headers={'Origin': 'https://evil.example'})[0], 403
        )
        self.assertEqual(
            self.request('/api/state', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403
        )

    def test_no_mutating_routes(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            self.assertEqual(self.request('/api/state', method)[0], 405)

    def test_report_relative_assets_and_preview_version(self):
        self.assertEqual(self.request('/files/report000/index.html')[0], 200)
        self.assertEqual(self.request('/files/report000/input/frame.png')[2], b'png')
        self.assertEqual(self.request('/files/picture00/picture.png?_frame=123')[2], b'png')

    def test_unknown_token_and_traversal_denied(self):
        for path in (
            '/files/unknown00/index.html',
            '/files/report000/../picture.png',
            '/files/report000/%2e%2e/picture.png',
            '/files/report000/../../outside.txt',
            '/files/picture00/secrets.env',
            '/files/report000/.hidden',
        ):
            self.assertEqual(self.request(path)[0], 404, path)

    def test_cross_directory_report_links_are_retokenized(self):
        (self.data / 'other.json').write_text('{"ok":true}')
        report = self.data / 'report/index.html'
        report.write_text('<a href="../other.json?q=1&amp;b=2#part">See</a>')
        status, headers, body = self.request('/files/report000/index.html')
        self.assertEqual(status, 200)
        self.assertIn(b'/files/registered0/other.json?q=1&amp;b=2#part', body)
        self.assertEqual(self.request('/files/registered0/other.json')[0], 200)
        self.assertNotIn(b'href="../', body)

    def test_only_real_tag_attributes_are_rewritten(self):
        report = self.data / 'report/index.html'
        script = '<script>const sample = \'<img src="input/frame.png">\';</script>'
        report.write_text(
            script + '<!-- <img src="input/frame.png"> --><img src="input/frame.png">'
        )
        body = self.request('/files/report000/index.html')[2].decode()
        self.assertIn(script, body)
        self.assertIn('<!-- <img src="input/frame.png"> -->', body)
        self.assertEqual(len(self.collector.files), 1)

    def test_report_cannot_register_outside_root(self):
        outside = self.root / 'private.png'
        outside.write_bytes(b'secret')
        (self.data / 'report/index.html').write_text('<img src="../../private.png">')
        self.request('/files/report000/index.html')
        self.assertEqual(self.collector.files, {})

    def test_symlink_escape_denied(self):
        outside = self.root / 'outside.png'
        outside.write_bytes(b'not allowed')
        (self.data / 'report/input/escape.png').symlink_to(outside)
        self.assertEqual(self.request('/files/report000/input/escape.png')[0], 404)

    def test_head_has_no_body(self):
        status, headers, body = self.request('/app.js', 'HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')
        self.assertTrue(int(headers['Content-Length']) > 0)

    def test_local_diagnostics_resources_are_explicitly_served(self):
        for path, expected in [
            ('/alerts.js', b'local alerts'),
            ('/operations-ux.css', b'alerts-center'),
        ]:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(expected, body)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.request('/anything-else.js')[0], 404)

    def test_sse_stream_matches_cached_state(self):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=2)
        client.request('GET', '/api/events')
        response = client.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.readline().strip(), b'id: 1')
        self.assertEqual(response.readline().strip(), b'event: state')
        self.assertEqual(json.loads(response.readline()[6:])['calls'], 1)
        response.close()
        client.close()

    def test_failed_collection_is_never_healthy_or_live(self):
        self.collector.failed = True
        state = self.hub.refresh()
        self.assertEqual(state['health']['state'], 'error')
        self.assertEqual(state['services'][0]['state'], 'unknown')
        self.assertEqual(state['agents'][0]['state'], 'unknown')
        self.assertFalse(state['preview']['live'])
        self.assertNotIn('private diagnostic', json.dumps(state))


class SafePathTests(unittest.TestCase):
    def test_path_checks_without_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'ok.json').write_text('{}')
            for name in ('../ok.json', '/ok.json', 'a\\ok.json', '.secret', 'ok.json\0'):
                self.assertIsNone(safe_child(root, name))
            self.assertEqual(safe_child(root, 'ok.json'), (root / 'ok.json').resolve())


if __name__ == '__main__':
    unittest.main()
