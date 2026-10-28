"""Local engine configuration is data, never an engine execution endpoint."""
import http.client
import io
import json
from pathlib import Path
import sys
import socket
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_ops_server as fixtures
from engine_registry import EngineRegistry
from test_campaign_settings_api import FakeSettings


class EngineApiTests(unittest.TestCase):
    request = fixtures.ServerTests.request
    tearDown = fixtures.ServerTests.tearDown

    def setUp(self):
        fixtures.ServerTests.setUp(self)
        self.server.engines = EngineRegistry(self.root, self.root / 'no-unity-project')
        self.server.settings = FakeSettings()

    def post(self, payload, headers=None):
        fields = {'Content-Type': 'application/json', 'X-LOTUSim-Engines': '1'}
        fields.update(headers or {})
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        client.request('POST', '/api/engines/select', body=json.dumps(payload).encode(), headers=fields)
        response = client.getresponse(); result = response.status, json.loads(response.read())
        client.close(); return result

    def test_catalogue_available_without_any_editor(self):
        status, _, body = self.request('/api/engines')
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data['selectedEngine']['id'], 'unity')
        self.assertTrue({'unity', 'unreal', 'godot', 'blender', 'o3de'} <= {e['id'] for e in data['engines']})

    def test_selecting_third_engine_persists_no_process_started(self):
        with mock.patch('subprocess.Popen', side_effect=AssertionError('No engine launch')):
            status, result = self.post({'engine': 'godot'})
        self.assertEqual(status, 200); self.assertEqual(result['selectedEngine']['id'], 'godot')
        again = EngineRegistry(self.root, self.root / 'still-no-editor')
        self.assertEqual(again.selection()['id'], 'godot')
        self.assertEqual(result['selectedEngine']['mode'], 'neutral_contract_only')

    def test_custom_name_is_a_data_profile_not_module_path(self):
        status, result = self.post({'engine': 'custom', 'name': 'Mon moteur maritime'})
        self.assertEqual(status, 200)
        self.assertTrue(result['selectedEngine']['id'].startswith('custom-'))
        self.assertEqual(result['selectedEngine']['label'], 'Mon moteur maritime')
        self.assertFalse(result['selectedEngine']['nativeValidated'])

    def test_intent_and_origin_are_required(self):
        for headers in ({'X-LOTUSim-Engines': ''}, {'Origin': 'https://evil.example'},
                        {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.post({'engine': 'godot'}, headers)[0], 403)
        self.assertEqual(self.server.engines.selection()['id'], 'unity')

    def test_wrong_type_and_extra_code_paths_refused(self):
        for payload in ({'engine': '../module'}, {'engine': 'godot', 'command': 'something'},
                        {'engine': 'custom', 'name': ''}, {'engine': 'unregistered-id'}):
            self.assertEqual(self.post(payload)[0], 400)
        self.assertEqual(self.post({'engine': 'godot'}, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.post({'engine': 'godot'}, {'Content-Length': '4097'})[0], 413)

    def test_no_engine_control_routes(self):
        for path in ('/api/engines/start', '/api/engines/stop', '/api/engines/execute', '/api/engines/run'):
            self.assertEqual(self.request(path, 'POST')[0], 405)

    def test_truncated_json_does_not_change_profile(self):
        client=http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        client.putrequest('POST','/api/engines/select')
        for name,value in {'Content-Type':'application/json','X-LOTUSim-Engines':'1','Content-Length':'100'}.items():
            client.putheader(name,value)
        client.endheaders();client.send(b'{"engine":"godot"}')
        client.sock.shutdown(socket.SHUT_WR)
        response=client.getresponse();self.assertEqual(response.status,400);response.read();client.close()
        self.assertEqual(self.server.engines.selection()['id'],'unity')

    def test_neutral_artifacts_download_only_as_fixed_attachments(self):
        for filename in ('scene-contract.json', 'adapter-requirements.json', 'engine-instructions.txt'):
            status, headers, body = self.request('/api/settings/prepared/' + 'a' * 32 + '/' + filename)
            self.assertEqual(status, 200)
            self.assertIn('attachment', headers['Content-Disposition'])
            self.assertTrue(body)


if __name__ == '__main__':
    unittest.main()
