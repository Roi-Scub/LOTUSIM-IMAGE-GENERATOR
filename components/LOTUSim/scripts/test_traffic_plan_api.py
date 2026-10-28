"""Loopback traffic preview/draft endpoints never become simulator controls."""
import http.client
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_ops_server as fixtures
from traffic_plan_editor import TrafficConflictError, TrafficValidationError

ID='12345678-1234-4234-8234-123456789abc'


class FakeTraffic:
    def __init__(self):self.calls=[];self.failure=None
    def get(self):return {'available':True,'summary':{'actorCount':32},'applied':False}
    def save_draft(self,payload):
        self.calls.append(payload)
        if self.failure:raise self.failure
        return {'id':ID,'draft':{'requiresRevalidation':True},'preview':{},'applied':False}
    def read_draft(self,identifier):return b'{"applied":false}\n'


class TrafficApiTests(unittest.TestCase):
    request=fixtures.ServerTests.request
    tearDown=fixtures.ServerTests.tearDown

    def setUp(self):
        fixtures.ServerTests.setUp(self)
        self.store=FakeTraffic();self.server.traffic=self.store

    def post(self,payload=None,headers=None,path='/api/traffic/drafts'):
        values={'Content-Type':'application/json','X-LOTUSim-Traffic':'1'};values.update(headers or {})
        client=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        client.request('POST',path,body=json.dumps(payload or {}).encode(),headers=values)
        response=client.getresponse();result=response.status,json.loads(response.read());client.close();return result

    def test_read_only_plan_route(self):
        status,_,raw=self.request('/api/traffic/plan')
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['summary']['actorCount'],32)
        self.assertEqual(self.store.calls,[])

    def test_explicit_draft_has_download_and_is_not_applied(self):
        status,result=self.post({'baseSha256':'a'*64,'changes':[]})
        self.assertEqual(status,200);self.assertFalse(result['applied'])
        self.assertTrue(result['draft']['requiresRevalidation'])
        status,headers,body=self.request(result['downloadUrl'])
        self.assertEqual(status,200);self.assertIn('attachment',headers['Content-Disposition'])
        self.assertFalse(json.loads(body)['applied'])

    def test_origin_and_explicit_intent_required(self):
        for headers in ({'X-LOTUSim-Traffic':''},{'Origin':'https://evil.example'},
                        {'Host':'evil.example'},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.post(headers=headers)[0],403)
        self.assertEqual(self.store.calls,[])

    def test_conflict_and_validation_are_not_generic_success(self):
        self.store.failure=TrafficConflictError('source changed')
        self.assertEqual(self.post()[0],409)
        self.store.failure=TrafficValidationError([{'path':'changes','message':'bad trajectory'}])
        status,result=self.post();self.assertEqual(status,400);self.assertFalse(result['valid'])
        self.assertEqual(result['errors'][0]['path'],'changes')

    def test_body_limits_and_type(self):
        self.assertEqual(self.post(headers={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.post(headers={'Content-Length':'1048577'})[0],413)
        self.assertEqual(self.store.calls,[])

    def test_no_live_apply_or_arbitrary_source_routes(self):
        for path in ('/api/traffic/apply','/api/traffic/start','/api/traffic/stop','/api/traffic/load'):
            self.assertEqual(self.post(path=path)[0],405)
        for path in ('/api/traffic/drafts/'+ID+'/../../secret','/api/traffic/drafts/not-an-id/draft.json',
                     '/api/traffic/drafts/'+ID+'/other.json'):
            self.assertEqual(self.request(path)[0],404)


if __name__=='__main__':unittest.main()
