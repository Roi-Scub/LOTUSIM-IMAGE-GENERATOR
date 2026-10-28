"""Renderer-neutral observation/provenance fixtures; no native engine required."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from engine_registry import EngineRegistry
from ops_collector import Collector
from renderer_telemetry import MAX_JSON, publish_renderer_state, read_json


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='lotusim-renderer-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.core=self.root/'core';self.core.mkdir()
        self.unity=self.root/'unity-project-not-installed'
        self.now=1800000000.0
        self.registry=EngineRegistry(self.core,self.unity)

    def timestamp(self,age=0):
        return dt.datetime.fromtimestamp(self.now-age,dt.timezone.utc).isoformat()

    def write(self,path,value,age=0):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
        os.utime(path,(self.now-age,self.now-age))
        return path

    def file(self,path,value=b'fixture image'):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        return path

    def engine_root(self,engine='godot'):
        return self.core/'artifacts/renderers'/engine

    def heartbeat(self,engine='godot',**changes):
        value={'schema':'lotusim-renderer-state-1','engineId':engine,'updatedAt':self.timestamp(),
               'isPlaying':True,'isPaused':False,'sceneName':'Maritime','runtimeState':'ready'}
        value.update(changes)
        self.write(self.core/'artifacts/operations/renderer.json',value)
        return value

    def legacy(self,**changes):
        value={'schema':'lotusim-ops-unity-1','updatedAt':self.timestamp(),'isPlaying':True,
               'isPaused':False,'sceneName':'Legacy maritime'}
        value.update(changes)
        self.write(self.unity/'artifacts/operations/unity.json',value)
        return value

    def collector(self):
        return Collector(self.core,self.unity,clock=lambda:self.now,docker_enabled=False,
                         process_probe=lambda runtime:None)

    def test_godot_is_observed_without_a_unity_project(self):
        self.registry.select({'engine':'godot'})
        output=self.engine_root()/'captures/run_01';output.mkdir(parents=True)
        self.file(self.engine_root()/'operations/preview.jpg')
        self.heartbeat(capture={'status':'capturing','captured':3,'expected':10,'outputDirectory':'captures/run_01'},
                       preview={'file':'operations/preview.jpg','updatedAt':self.timestamp(),'width':640,'height':360,'live':True},
                       lotusim={'hasFrame':True,'snapshotUpdatedAt':self.timestamp(),'frame':3,
                                'objects':[{'id':'boat','model':'sailboat','eastM':0,'northM':100,'altitudeM':0}]})
        state=self.collector().snapshot()
        self.assertFalse(self.unity.exists())
        self.assertEqual(state['engineProfile']['id'],'godot')
        self.assertEqual(state['renderer']['engineId'],'godot')
        self.assertEqual(state['renderer']['type'],'neutral')
        self.assertTrue(state['renderer']['fresh']);self.assertEqual(state['renderer']['state'],'running')
        self.assertEqual(state['unity']['state'],'unknown')
        self.assertTrue(state['capture']['live']);self.assertTrue(state['preview']['live'])
        self.assertTrue(state['scene']['live']);self.assertIn('Godot',state['scene']['source'])
        for item in (state['capture'],state['preview'],state['scene']):
            self.assertEqual(item['sourceEngine'],{'id':'godot','label':'Godot'})
        renderer_service=next(s for s in state['services'] if s['id']=='renderer')
        self.assertEqual(renderer_service['label'],'Moteur graphique')
        self.assertIn('Godot',renderer_service['detail'])
        self.assertEqual(next(a for a in state['agents'] if a['id']=='renderer')['label'],'Rendu graphique')
        self.assertFalse(state['renderer']['nativeValidated'])
        self.assertNotIn(str(self.root),json.dumps(state,allow_nan=False))

    def test_selection_is_not_evidence_of_a_running_renderer(self):
        self.registry.select({'engine':'godot'})
        before=sorted(str(path) for path in self.core.rglob('*'))
        state=self.collector().snapshot()
        self.assertEqual(state['engineProfile']['id'],'godot')
        self.assertEqual(state['renderer']['state'],'unknown')
        self.assertIsNone(state['renderer']['engineId'])
        self.assertFalse(state['capture']['live']);self.assertIsNone(state['preview']['engineId'])
        self.assertEqual(before,sorted(str(path) for path in self.core.rglob('*')))

    def test_corrupt_profile_does_not_hide_legacy_evidence_or_register_sources(self):
        self.registry.select({'engine':'godot'})
        profile=self.core/'artifacts/render-engines/profile.json';profile.write_text('{broken')
        original=profile.read_bytes();self.legacy();self.heartbeat(engine='godot')
        state=self.collector().snapshot()
        self.assertIsNone(state['engineProfile']['id'])
        self.assertEqual(state['engineProfile']['state'],'error')
        self.assertEqual(state['renderer']['engineId'],'unity')
        self.assertTrue(state['unity']['fresh'])
        self.assertEqual(profile.read_bytes(),original)

    def test_selected_godot_does_not_relabel_legacy_unity_rgb(self):
        self.registry.select({'engine':'godot'})
        output=self.unity/'artifacts/dataset-existing/run_01';output.mkdir(parents=True)
        self.file(self.unity/'artifacts/operations/preview.jpg')
        self.legacy(capture={'status':'capturing','outputDirectory':str(output)},
                    preview={'file':'preview.jpg','updatedAt':self.timestamp(),'width':640,'height':360,'live':True})
        state=self.collector().snapshot()
        self.assertEqual(state['engineProfile']['id'],'godot')
        self.assertEqual(state['renderer']['engineId'],'unity')
        self.assertEqual(state['renderer']['source'],'legacy_unity_adapter')
        self.assertTrue(state['unity']['fresh']);self.assertTrue(state['renderer']['profileMismatch'])
        self.assertEqual(state['preview']['engineId'],'unity');self.assertEqual(state['capture']['engineId'],'unity')
        self.assertTrue(any('Profil configuré Godot' in warning and 'Unity' in warning for warning in state['health']['warnings']))

    def test_neutral_unity_source_is_unity_not_the_selected_profile(self):
        self.registry.select({'engine':'godot'})
        self.heartbeat(engine='unity')
        state=self.collector().snapshot()
        self.assertEqual(state['renderer']['engineId'],'unity')
        self.assertEqual(state['renderer']['source'],'renderer_heartbeat')
        self.assertTrue(state['renderer']['profileMismatch'])
        self.assertEqual(state['unity']['state'],'unknown')

    def test_unknown_or_conflicting_source_ids_are_rejected(self):
        for value in ('not-registered','../unity','/tmp/secret',None,{'id':'godot'}):
            with self.subTest(value=value):
                self.heartbeat(engine=value)
                state=self.collector().snapshot()
                self.assertEqual(state['renderer']['state'],'unknown')
                self.assertIsNone(state['renderer']['engineId'])
        raw=self.heartbeat();raw['engine']='unreal'
        self.write(self.core/'artifacts/operations/renderer.json',raw)
        self.assertFalse(self.collector().snapshot()['renderer']['fresh'])

    def test_custom_registered_source_gets_its_real_descriptor(self):
        registered=self.registry.select({'engine':'custom','name':'Research Renderer'})['selectedEngine']
        self.heartbeat(engine=registered['id'])
        state=self.collector().snapshot()
        self.assertEqual(state['renderer']['engineId'],registered['id'])
        self.assertEqual(state['renderer']['label'],'Research Renderer')

    def test_missing_runtime_flags_do_not_claim_play_was_stopped(self):
        raw=self.heartbeat();raw.pop('isPlaying');raw.pop('isPaused')
        self.write(self.core/'artifacts/operations/renderer.json',raw)
        state=self.collector().snapshot()
        self.assertTrue(state['renderer']['fresh'])
        self.assertEqual(state['renderer']['state'],'unknown')
        self.assertIsNone(state['renderer']['isPlaying'])

    def test_preparation_target_label_comes_from_its_own_registered_engine(self):
        registered=self.registry.select({'engine':'custom','name':'Research Renderer'})['selectedEngine']
        self.registry.select({'engine':'godot'})
        preparation={'id':'scene_preparation','label':'Préparation','state':'idle','engine':registered['id']}
        with mock.patch('ops_collector.observe_preparation',return_value=(preparation,[])):
            state=self.collector().snapshot()
        self.assertEqual(state['engineProfile']['id'],'godot')
        self.assertEqual(state['preparation']['engineLabel'],'Research Renderer')

    def test_stale_and_future_heartbeats_cannot_mark_new_preview_live(self):
        self.file(self.engine_root()/'operations/preview.jpg')
        for age in (20,-100):
            self.heartbeat(updatedAt=self.timestamp(age),preview={'file':'preview.jpg','updatedAt':self.timestamp(),
                            'width':640,'height':360,'live':True})
            state=self.collector().snapshot()
            self.assertEqual(state['renderer']['state'],'stale');self.assertFalse(state['renderer']['fresh'])
            self.assertFalse(state['preview']['live']);self.assertEqual(state['preview']['engineId'],'godot')

    def test_fresh_legacy_evidence_beats_a_stale_neutral_heartbeat(self):
        self.heartbeat(updatedAt=self.timestamp(40));self.legacy()
        state=self.collector().snapshot()
        self.assertEqual(state['renderer']['engineId'],'unity')
        self.assertTrue(state['renderer']['fresh'])

    def test_stale_lotusim_frame_is_not_a_live_snapshot(self):
        output=self.engine_root()/'captures/run';output.mkdir(parents=True)
        self.heartbeat(capture={'status':'capturing','outputDirectory':'captures/run'},
                       lotusim={'hasFrame':True,'snapshotUpdatedAt':self.timestamp(30),'frame':3,'objects':[]})
        state=self.collector().snapshot()
        self.assertTrue(state['capture']['live']);self.assertFalse(state['scene']['live'])
        self.assertEqual(state['scene']['engineId'],'godot')

    def test_preview_and_capture_cannot_borrow_another_engine_root(self):
        other=self.engine_root('unity')/'captures/run';other.mkdir(parents=True)
        outside=self.file(self.engine_root('unity')/'operations/preview.jpg')
        self.heartbeat(capture={'status':'capturing','outputDirectory':str(other)},
                       preview={'file':str(outside),'updatedAt':self.timestamp(),'width':640,'height':360,'live':True})
        state=self.collector().snapshot()
        self.assertFalse(state['capture']['live']);self.assertIsNone(state['preview']['url'])
        self.assertIsNone(state['capture']['engineId'])

    def test_preview_traversal_and_symlinked_artifact_directories_are_refused(self):
        outside=self.file(self.root/'private/image.jpg')
        artifact_root=self.engine_root();artifact_root.mkdir(parents=True)
        (artifact_root/'linked').symlink_to(outside.parent,target_is_directory=True)
        for value in ('../../../private/image.jpg','linked/image.jpg',str(outside),'operations\\preview.jpg'):
            self.heartbeat(preview={'file':value,'updatedAt':self.timestamp(),'width':640,'height':360,'live':True})
            self.assertIsNone(self.collector().snapshot()['preview']['url'])

    def test_symlinked_neutral_heartbeat_or_parent_is_not_read(self):
        outside=self.write(self.root/'outside/renderer.json',self.heartbeat())
        heartbeat=self.core/'artifacts/operations/renderer.json';heartbeat.unlink();heartbeat.symlink_to(outside)
        self.assertFalse(self.collector().snapshot()['renderer']['fresh'])
        heartbeat.unlink();heartbeat.parent.rmdir();heartbeat.parent.symlink_to(outside.parent,target_is_directory=True)
        self.assertFalse(self.collector().snapshot()['renderer']['fresh'])

    def test_neutral_and_legacy_campaigns_preserve_independent_provenance(self):
        neutral=self.engine_root()/'captures/godot_run'
        legacy=self.unity/'artifacts/datasets/unity_run'
        self.write(neutral/'status.json',{'status':'complete','captured':2,'expected':2},age=10)
        self.write(legacy/'status.json',{'status':'complete','captured':3,'expected':3},age=20)
        self.file(neutral/'rgb/f000001.png');self.file(neutral/'index.html',b'<title>Godot</title>')
        self.file(legacy/'rgb/f000002.png');self.file(legacy/'index.html',b'<title>Unity</title>')
        state=self.collector().snapshot()
        self.assertEqual({item['engineId'] for item in state['campaigns']},{'godot','unity'})
        self.assertEqual(state['capture']['engineId'],'godot')
        self.assertEqual(state['preview']['engineId'],'godot');self.assertFalse(state['preview']['live'])
        self.assertEqual({item['engineId'] for item in state['reports'] if item['kind']=='capture'},{'godot','unity'})

    def test_matching_neutral_rgb_observer_can_corroborate_only_its_engine_job(self):
        job=self.engine_root()/'rgb-validation/job_01'
        self.write(job/'status.json',{'status':'detecting','completed':1,'expected':3})
        self.heartbeat(rgbObserver={'running':True,'outputDirectory':'rgb-validation/job_01'})
        state=self.collector().snapshot()
        self.assertTrue(state['vision']['live']);self.assertEqual(state['vision']['engineId'],'godot')
        self.heartbeat(engine='unreal',rgbObserver={'running':True,'outputDirectory':str(job)})
        self.assertFalse(self.collector().snapshot()['vision']['live'])

    def test_finite_bounded_heartbeat_and_no_process_commands(self):
        heartbeat=self.core/'artifacts/operations/renderer.json';heartbeat.parent.mkdir(parents=True)
        for raw in (b'{"x":1e999}',b'{"x":NaN}',b'{"x":1,"x":2}',b' '* (MAX_JSON+1)):
            heartbeat.write_bytes(raw)
            self.assertIsNone(read_json(self.core,'artifacts/operations/renderer.json'))
            with mock.patch('ops_collector.subprocess.run',side_effect=AssertionError('No renderer CLI execution')):
                self.assertFalse(self.collector().snapshot()['renderer']['fresh'])
        self.assertIsNone(read_json(self.core,'../renderer.json'))

    def test_malformed_nested_telemetry_does_not_leak_host_paths(self):
        self.heartbeat(sceneName={'not':'a name'},scenePath=str(self.root/'secret.blend'),
                       ros={'activeInstanceCount':10 ** 400,'connectionState':{'secret':'no'}},
                       preview={'file':'a/' * 5000,'updatedAt':self.timestamp(),'width':1,'height':1,'live':True})
        state=self.collector().snapshot()
        self.assertNotIn(str(self.root),json.dumps(state,allow_nan=False))
        self.assertIsNone(state['preview']['url'])
        self.assertIsNone(state['renderer']['ros']['activeInstanceCount'])

    def test_named_pipe_heartbeat_does_not_block_the_collector(self):
        path=self.core/'artifacts/operations/renderer.json';path.parent.mkdir(parents=True)
        os.mkfifo(path)
        self.assertIsNone(read_json(self.core,'artifacts/operations/renderer.json'))
        self.assertFalse(self.collector().snapshot()['renderer']['fresh'])

    def test_optional_writer_has_explicit_source_and_does_not_select_engine(self):
        result=publish_renderer_state(self.core,'godot',{'updatedAt':self.timestamp(),'isPlaying':True},registry=self.registry)
        self.assertEqual(result['engineId'],'godot')
        self.assertEqual(self.registry.selection()['id'],'unity')
        state=self.collector().snapshot();self.assertEqual(state['renderer']['engineId'],'godot')
        self.assertTrue(state['renderer']['profileMismatch'])
        self.assertFalse(self.unity.exists())

    def test_writer_rejects_unknown_source_timestamp_conflicts_and_escapes(self):
        for engine,payload in (('unknown',{'updatedAt':self.timestamp()}),
                               ('godot',{'isPlaying':True}),
                               ('godot',{'updatedAt':self.timestamp(),'engineId':'unity'}),
                               ('godot',{'updatedAt':self.timestamp(),'preview':{'file':'../secret.png'}}),
                               ('godot',{'updatedAt':self.timestamp(),'capture':{'outputDirectory':'/tmp/private'}}),
                               ('godot',{'updatedAt':self.timestamp(),'x':float('nan')}),
                               ('godot',{'updatedAt':self.timestamp(),'x':'a' * MAX_JSON})):
            with self.subTest(engine=engine,payload=list(payload)):
                with self.assertRaises(ValueError):
                    publish_renderer_state(self.core,engine,payload,registry=self.registry)
        self.assertFalse((self.core/'artifacts/operations/renderer.json').exists())

    def test_writer_refuses_symlinked_heartbeat_and_storage_parent(self):
        outside=self.file(self.root/'private/renderer.json',b'keep user data')
        operations=self.core/'artifacts/operations';operations.mkdir(parents=True)
        heartbeat=operations/'renderer.json';heartbeat.symlink_to(outside)
        with self.assertRaises(ValueError):
            publish_renderer_state(self.core,'godot',{'updatedAt':self.timestamp()},registry=self.registry)
        self.assertEqual(outside.read_bytes(),b'keep user data')
        heartbeat.unlink();operations.rmdir();operations.symlink_to(outside.parent,target_is_directory=True)
        with self.assertRaises(OSError):
            publish_renderer_state(self.core,'godot',{'updatedAt':self.timestamp()},registry=self.registry)
        self.assertEqual(outside.read_bytes(),b'keep user data')


if __name__=='__main__':
    unittest.main(verbosity=2)
