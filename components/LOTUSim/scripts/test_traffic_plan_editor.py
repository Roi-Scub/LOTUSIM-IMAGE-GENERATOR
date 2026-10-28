"""Offline traffic timeline/draft fixtures: never launch or modify a simulator."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from plan_maritime_traffic import position as planner_position
from traffic_plan_editor import (MAX_JSON, TrafficConflictError, TrafficPlanSecurityError,
                                 TrafficPlanStore, TrafficValidationError, position_enu)


class TrafficEditorTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='lotusim-traffic-draft-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.core=self.root/'core';self.core.mkdir()
        self.unity=self.root/'unity';self.unity.mkdir()
        self.store=TrafficPlanStore(self.core,self.unity,clock=lambda:1800000000)
        self.plan={'schema':'lotusim-unity-encounters-1','events':[
            self.event('boat_001','sailboat','sailboat',center=(0,0,100),velocity=(1,0,0)),
            self.event('buoy_001','buoy','buoy',center=(50,0,100)),
            self.event('drone_001','small_drone','drone',center=(0,80,100),velocity=(10,0,0),
                       boundedTurn=True,yawRateDegS=5,turnStartSeconds=8,turnEndSeconds=16)],
            'traffic':{'continuousSafetyApproved':True,'safetyApproved':True},
            'safetyReport':{'approved':True,'state':'approved'}}
        self.scope={'schema':'lotusim-traffic-scope-1','observer':{'speedKnots':12,'headingDeg':0,'turnDeg':-8},
                    'water':{'eastMinM':-5000,'eastMaxM':5000,'northMinM':-5000,'northMaxM':5000}}
        self.catalog={'schema':'lotusim-traffic-catalogue-1','assets':[
            {'model':'sailboat','domain':'sea','maxSpeedMps':4.5},
            {'model':'buoy','domain':'moored','maxSpeedMps':0},
            {'model':'small_drone','domain':'air','maxSpeedMps':15,'maxAltitudeM':120}]}
        self.write(self.core/'assets/scenarios/scopes/MaritimeTrafficAgents.json',self.scope)
        self.write(self.core/'assets/scenarios/catalogs/traffic_assets.json',self.catalog)
        self.source=self.write(self.unity/'artifacts/traffic-agents/plan.json',self.plan)

    @staticmethod
    def event(identifier,model,category,center=(0,0,0),velocity=(0,0,0),**changes):
        return {'instance':identifier,'modelName':model,'category':category,'startSeconds':0,
                'endSeconds':24,'centerSeconds':12,'centerPosition':dict(zip(('x','y','z'),center)),
                'velocity':dict(zip(('x','y','z'),velocity)),**changes}

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8');return path

    def payload(self,actor='boat_001',**changes):
        value={'actorId':actor,'centerENU':{'eastM':10,'northM':110,'altitudeM':0},'speedMps':2,'headingDeg':90}
        value.update(changes)
        return {'baseSha256':self.store.get()['baseSha256'],'name':'Manual draft','changes':[value]}

    def test_read_only_normalized_enu_timeline_and_true_source_sha(self):
        before=self.source.read_bytes();state=self.store.get()
        self.assertTrue(state['available']);self.assertEqual(state['baseSha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(state['source']['engineId'],'unity')
        self.assertFalse(state['source']['runtimeExecutionConfirmed'])
        self.assertEqual(state['timeline']['endSeconds'],24)
        self.assertEqual(state['summary']['actorCount'],3)
        self.assertEqual(state['summary']['classCounts'],{'sailboat':1,'buoy':1,'drone':1})
        actor=state['actors'][0];self.assertEqual(actor['id'],'boat_001')
        self.assertEqual(actor['centerENU'],{'eastM':0,'northM':100,'altitudeM':0})
        self.assertEqual(actor['points'][0],{'timeSeconds':0,'eastM':-12,'northM':100,'altitudeM':0})
        self.assertEqual(actor['points'][-1]['eastM'],12)
        self.assertTrue(all(len(actor['points'])<=181 for actor in state['actors']))
        self.assertTrue(state['observer']);self.assertFalse(state['observer']['editable'])
        self.assertEqual(self.source.read_bytes(),before)
        self.assertFalse((self.core/'artifacts').exists())
        self.assertNotIn(str(self.root),json.dumps(state,allow_nan=False))

    def test_bounded_turn_matches_existing_planner_before_during_after_turn(self):
        event=self.plan['events'][2]
        route={'center':[event['centerPosition'][key] for key in ('x','y','z')],
               'velocity':[event['velocity'][key] for key in ('x','y','z')],
               'focus':event['centerSeconds'],**{key:event[key] for key in ('boundedTurn','yawRateDegS','turnStartSeconds','turnEndSeconds')}}
        for at in (0,7.9,8,10,12,16,16.1,24):
            result=position_enu(event,at);expected=planner_position(route,at)
            self.assertAlmostEqual(result['eastM'],expected[0],places=8)
            self.assertAlmostEqual(result['northM'],expected[2],places=8)
            self.assertAlmostEqual(result['altitudeM'],expected[1],places=8)
        actor=self.store.get()['actors'][2]
        self.assertEqual(actor['trajectoryKind'],'bounded_turn')
        self.assertTrue({8,12,16}<={point['timeSeconds'] for point in actor['points']})

    def test_fixed_embedded_unity_asset_decoder_no_general_yaml_or_generation(self):
        self.source.unlink()
        raw=json.dumps(self.plan)
        quoted=json.dumps(raw)
        # Unity's physical wrapping is folded; the logical escaped JSON stays.
        quoted=quoted.replace(' \\"', '\n    \\"')
        asset=self.unity/'Assets/Dataset/MaritimeTrafficAgents.plan.asset'
        asset.parent.mkdir(parents=True);asset.write_text('%YAML 1.1\nMonoBehaviour:\n  planJson: '+quoted+'\n')
        result=self.store.get()
        self.assertTrue(result['available'])
        self.assertEqual(result['source']['kind'],'embedded_unity_asset')
        self.assertEqual(result['source']['sha256'],hashlib.sha256(asset.read_bytes()).hexdigest())
        self.assertEqual(result['plan'],self.plan)

    def test_no_source_never_falls_back_to_an_ambient_backup(self):
        self.source.unlink()
        backup=self.root/'old-backup/artifacts/traffic-agents/plan.json';self.write(backup,self.plan)
        result=self.store.get()
        self.assertFalse(result['available']);self.assertEqual(result['actors'],[])

    def test_latest_known_artifact_is_selected_without_arbitrary_file_queries(self):
        first=self.source
        other=self.core/'artifacts/traffic-agents/unity-plan.json';self.write(other,self.plan)
        os.utime(first,(100,100));os.utime(other,(200,200))
        result=self.store.get()
        self.assertEqual(result['source']['relativePath'],'artifacts/traffic-agents/unity-plan.json')
        self.assertTrue(result['source']['id'].startswith('core-'))

    def test_immutable_draft_never_modifies_original_and_revokes_every_safety_approval(self):
        original=self.source.read_bytes();result=self.store.save_draft(self.payload())
        draft=result['draft'];self.assertFalse(result['applied']);self.assertFalse(draft['applied'])
        self.assertTrue(draft['requiresRevalidation']);self.assertFalse(draft['collisionChecked'])
        self.assertTrue(draft['originalPlan']['traffic']['continuousSafetyApproved'])
        self.assertFalse(draft['kinematicPlan']['traffic']['continuousSafetyApproved'])
        self.assertFalse(draft['kinematicPlan']['traffic']['safetyApproved'])
        self.assertFalse(draft['kinematicPlan']['safetyReport']['approved'])
        self.assertEqual(draft['kinematicPlan']['safetyReport']['state'],'requires_revalidation')
        self.assertEqual(result['preview']['summary']['changedActors'],1)
        self.assertEqual(result['preview']['actors'][0]['centerENU']['eastM'],10)
        self.assertEqual(self.source.read_bytes(),original)
        raw=self.store.read_draft(result['id']);self.assertEqual(json.loads(raw),draft)
        second=self.store.save_draft(self.payload());self.assertNotEqual(result['id'],second['id'])
        self.assertEqual(self.store.read_draft(result['id']),raw)
        with mock.patch('traffic_plan_editor.uuid.uuid4',return_value=uuid.UUID(result['id'])):
            with self.assertRaises(FileExistsError):self.store.save_draft(self.payload())
        self.assertEqual(self.store.read_draft(result['id']),raw)

    def test_speed_heading_and_altitude_bounds(self):
        for changes in ({'speedMps':4.501},{'speedMps':-1},{'headingDeg':361},
                        {'centerENU':{'eastM':0,'northM':0,'altitudeM':1}},
                        {'centerENU':{'eastM':100001,'northM':0,'altitudeM':0}},
                        {'yawRateDegS':5}):
            with self.subTest(changes=changes):
                with self.assertRaises(TrafficValidationError):self.store.save_draft(self.payload(**changes))
        with self.assertRaises(TrafficValidationError):
            self.store.save_draft(self.payload(actor='drone_001',centerENU={'eastM':0,'northM':0,'altitudeM':121}))
        result=self.store.save_draft(self.payload(headingDeg=360))
        self.assertEqual(result['draft']['changes'][0]['headingDeg'],0)

    def test_moored_relocation_is_allowed_but_motion_is_not(self):
        with self.assertRaises(TrafficValidationError):self.store.save_draft(self.payload(actor='buoy_001',speedMps=1))
        draft=self.store.save_draft(self.payload(actor='buoy_001',speedMps=0))
        self.assertEqual(draft['preview']['actors'][1]['centerENU']['eastM'],10)

    def test_existing_bounded_turn_window_is_preserved_when_no_yaw_change_requested(self):
        result=self.store.save_draft(self.payload(actor='drone_001',centerENU={'eastM':0,'northM':50,'altitudeM':80},speedMps=10))
        actor=result['preview']['actors'][2]
        self.assertTrue(actor['boundedTurn']);self.assertEqual(actor['yawRateDegS'],5)
        self.assertEqual(actor['turnStartSeconds'],8);self.assertEqual(actor['turnEndSeconds'],16)

    def test_two_and_three_control_points_are_inert_piecewise_exports(self):
        controls=[{'timeSeconds':0,'eastM':0,'northM':0,'altitudeM':0},
                  {'timeSeconds':12,'eastM':12,'northM':0,'altitudeM':0},
                  {'timeSeconds':24,'eastM':12,'northM':12,'altitudeM':0}]
        payload=self.payload();payload['changes']=[{'actorId':'boat_001','controlPoints':controls}]
        result=self.store.save_draft(payload)
        self.assertEqual(result['preview']['actors'][0]['trajectoryKind'],'piecewise_linear')
        self.assertEqual(result['preview']['actors'][0]['controlPoints'],controls)
        self.assertTrue(result['draft']['requiresNativeAdapter'])
        self.assertTrue(result['draft']['kinematicPlan']['containsUncompiledControlPoints'])
        self.assertFalse(result['draft']['kinematicPlan']['traffic']['continuousSafetyApproved'])
        payload['changes'][0]['controlPoints']=controls[::2]
        self.assertTrue(self.store.save_draft(payload))

    def test_control_point_time_speed_and_domain_validation(self):
        valid=[{'timeSeconds':0,'eastM':0,'northM':0,'altitudeM':0},
               {'timeSeconds':24,'eastM':12,'northM':0,'altitudeM':0}]
        invalid=[]
        points=copy.deepcopy(valid);points[-1]['timeSeconds']=23;invalid.append(points)
        points=copy.deepcopy(valid);points[-1]['timeSeconds']=0;invalid.append(points)
        points=copy.deepcopy(valid);points[-1]['eastM']=1000;invalid.append(points)
        points=copy.deepcopy(valid);points[-1]['eastM']=1e308;invalid.append(points)
        points=copy.deepcopy(valid);points[-1]['altitudeM']=1;invalid.append(points)
        for points in invalid:
            payload=self.payload();payload['changes']=[{'actorId':'boat_001','controlPoints':points}]
            with self.assertRaises(TrafficValidationError):self.store.save_draft(payload)

    def test_water_rectangle_is_checked_across_the_edited_route(self):
        payload=self.payload(centerENU={'eastM':4999,'northM':0,'altitudeM':0},speedMps=4.5,headingDeg=90)
        with self.assertRaises(TrafficValidationError):self.store.save_draft(payload)

    def test_stale_base_sha_is_conflict_not_an_overwrite(self):
        payload=self.payload();self.plan['seed']=123;self.write(self.source,self.plan)
        with self.assertRaises(TrafficConflictError):self.store.save_draft(payload)
        self.assertFalse((self.core/'artifacts/traffic-drafts').exists())

    def test_source_change_during_validation_is_conflict(self):
        payload=self.payload();original_load=self.store._load;calls=[0]
        def changing():
            calls[0]+=1
            result=original_load()
            if calls[0]==2:result[0]['sha256']='0'*64
            return result
        with mock.patch.object(self.store,'_load',side_effect=changing):
            with self.assertRaises(TrafficConflictError):self.store.save_draft(payload)

    def test_unknown_ids_duplicates_unknown_fields_and_nonfinite_are_rejected(self):
        for payload in (None,[],{'baseSha256':'x'},self.payload(actor='ObserverBoat'),
                        self.payload(actor='../../private'),self.payload(speedMps=float('nan')),
                        self.payload(yawRateDegS=1e308)):
            with self.subTest(payload=repr(payload)[:80]):
                with self.assertRaises(TrafficValidationError):self.store.save_draft(payload)
        payload=self.payload();payload['changes'][0]['command']='do not run'
        with self.assertRaises(TrafficValidationError):self.store.save_draft(payload)
        payload=self.payload();payload['changes']*=2
        with self.assertRaises(TrafficValidationError):self.store.save_draft(payload)

    def test_source_symlink_fifo_oversize_and_nonfinite_do_not_get_loaded(self):
        outside=self.write(self.root/'private/plan.json',self.plan)
        self.source.unlink();self.source.symlink_to(outside)
        self.assertFalse(self.store.get()['available'])
        self.source.unlink();os.mkfifo(self.source)
        self.assertFalse(self.store.get()['available'])
        self.source.unlink();self.source.write_bytes(b' '*(MAX_JSON+1))
        self.assertFalse(self.store.get()['available'])
        self.source.write_text('{"x":1e999}')
        self.assertFalse(self.store.get()['available'])

    def test_symlinked_draft_storage_cannot_escape_or_change_user_files(self):
        payload=self.payload();outside=self.root/'private';outside.mkdir()
        artifacts=self.core/'artifacts';artifacts.mkdir();(artifacts/'traffic-drafts').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):self.store.save_draft(payload)
        self.assertEqual(list(outside.iterdir()),[])

    def test_download_ids_and_symlinked_files_are_refused(self):
        for identifier in ('../secret','/tmp/secret','',None,'a'*36):
            with self.assertRaises(TrafficPlanSecurityError):self.store.read_draft(identifier)
        result=self.store.save_draft(self.payload())
        path=self.core/'artifacts/traffic-drafts'/result['id']/'draft.json'
        outside=self.root/'private.json';outside.write_text('{"private":true}')
        path.unlink();path.symlink_to(outside)
        with self.assertRaises(OSError):self.store.read_draft(result['id'])


if __name__=='__main__':unittest.main(verbosity=2)
