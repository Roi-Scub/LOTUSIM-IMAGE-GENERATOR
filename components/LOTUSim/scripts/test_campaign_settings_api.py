"""Loopback API tests: configuration writes never become simulation controls."""
import http.client
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_ops_server import ServerTests

class FakeSettings:
    def __init__(self):self.calls=[]
    def catalog(self):return {'assets':[],'engines':[],'scenes':[],'defaults':{}}
    def list(self):return [{'id':'a'*32,'name':'Stored'}]
    def get(self,identifier):return {'id':identifier,'campaign':{'name':'Stored'}}
    def validate(self,payload):self.calls.append(('validate',payload));return {'valid':True,'campaign':payload,'errors':[],'warnings':[]}
    def save(self,payload):return dict(self.validate(payload),id='a'*32)
    def prepare(self,payload):return dict(self.validate(payload),id='b'*32,manifest={})
    def read_prepared(self,identifier,filename):
        return b'{"exact_bytes": true}\n'
    def read_bundle(self,identifier):
        return {'campaign.json':b'{"engine":"unreal"}', 'manifest.json':b'{}',
                'scene_unreal.py':b'# trusted generated editor script\n'}

class SettingsApiTests(unittest.TestCase):
    request=ServerTests.request
    tearDown=ServerTests.tearDown
    def setUp(self):
        ServerTests.setUp(self);self.settings=FakeSettings();self.server.settings=self.settings
    def post(self,path='/api/settings/validate',body=b'{"name":"Test"}',headers=None):
        standard={'Content-Type':'application/json','X-LOTUSim-Settings':'1'}
        standard.update(headers or {})
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        client.request('POST',path,body=body,headers=standard)
        response=client.getresponse();result=(response.status,json.loads(response.read()));client.close();return result
    def test_catalog_list_and_single_campaign(self):
        for path in ('/api/settings/catalog','/api/settings/campaigns','/api/settings/campaigns/'+'a'*32):
            self.assertEqual(self.request(path)[0],200)
    def test_only_explicit_config_routes_accept_post(self):
        for path in ('/api/state','/api/settings/start','/api/settings/stop','/api/settings/run','/api/settings/open-scene'):
            self.assertEqual(self.post(path)[0],405)
        self.assertEqual(self.settings.calls,[])
    def test_validated_save_prepare_and_exact_download(self):
        self.assertEqual(self.post()[0],200)
        self.assertEqual(self.post('/api/settings/save')[1]['id'],'a'*32)
        status,payload=self.post('/api/settings/prepare')
        self.assertEqual(status,200);self.assertIn('/api/settings/prepared/',payload['downloadUrl'])
        self.assertEqual(self.request(payload['downloadUrl'])[2],b'{"exact_bytes": true}\n')
    def test_cross_origin_and_missing_custom_header_cannot_write(self):
        for headers in ({'Host':'evil.example'},{'Origin':'https://evil.example'},
                        {'Sec-Fetch-Site':'cross-site'},{'X-LOTUSim-Settings':''}):
            self.assertEqual(self.post(headers=headers)[0],403)
        self.assertEqual(self.settings.calls,[])
    def test_invalid_json_duplicate_fields_and_nonfinite_rejected(self):
        for body in (b'NaN',b'{"n":Infinity}',b'{"name":1,"name":2}',b'not json',b'\xff'):
            self.assertEqual(self.post(body=body)[0],400,body)
        self.assertEqual(self.settings.calls,[])
    def test_wrong_content_type_and_oversize_body_rejected(self):
        self.assertEqual(self.post(headers={'Content-Type':'text/plain'})[0],415)
        # Declare oversized before transmitting data: rejection must happen first.
        self.assertEqual(self.post(headers={'Content-Length':str(1048577)})[0],413)
    def test_other_mutating_methods_disabled(self):
        for method in ('PUT','PATCH','DELETE'):
            self.assertEqual(self.request('/api/settings/save',method)[0],405)
    def test_prepared_paths_are_bounded(self):
        for path in ('/api/settings/prepared/'+'a'*32+'/../../secret',
                     '/api/settings/prepared/'+'a'*32+'/other.json',
                     '/api/settings/campaigns/not-an-id'):
            self.assertEqual(self.request(path)[0],404)

    def test_generated_code_is_attachment_not_browser_script(self):
        status,headers,body=self.request('/api/settings/prepared/'+'a'*32+'/scene_unreal.py')
        self.assertEqual(status,200)
        self.assertIn('attachment',headers['Content-Disposition'])
        self.assertEqual(headers['Content-Type'],'application/octet-stream')
        self.assertEqual(headers['X-Content-Type-Options'],'nosniff')

    def test_bundle_download_preserves_files_without_execution(self):
        status,headers,body=self.request('/api/settings/prepared/'+'a'*32+'/bundle.zip')
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'application/zip')
        self.assertIn('attachment',headers['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            self.assertEqual(sorted(archive.namelist()),['campaign.json','manifest.json','scene_unreal.py'])
            self.assertEqual(archive.read('scene_unreal.py'),b'# trusted generated editor script\n')

    def test_bundle_cannot_download_unsafe_entry(self):
        self.settings.read_bundle=lambda _: {'../outside.txt':b'not allowed'}
        self.assertEqual(self.request('/api/settings/prepared/'+'a'*32+'/bundle.zip')[0],404)

    def test_prepared_download_allowlist_excludes_arbitrary_files(self):
        for name in ('other.py','startup.sh','LOTUSimPrepared.uproject.exe','scene_unreal.py/other'):
            self.assertEqual(self.request('/api/settings/prepared/'+'a'*32+'/'+name)[0],404)

    def test_unreal_prepare_response_has_bundle_but_no_unity_menu(self):
        status,result=self.post('/api/settings/prepare',body=b'{"engine":"unreal"}')
        self.assertEqual(status,200);self.assertTrue(result['bundleUrl'].endswith('/bundle.zip'))
        self.assertNotIn('unityMenu',result)

if __name__=='__main__':unittest.main()
