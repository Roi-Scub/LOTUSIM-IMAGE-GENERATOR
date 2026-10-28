#!/usr/bin/env python3
"""Native ECM/ROS regression, isolated domain 96; never stops a live simulator."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid

from test_dataset_scenario_lifecycle import WORLD


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plugin-dir', required=True)
    parser.add_argument('--world', help='Also exercise the dedicated production world, with an isolated world name')
    args = parser.parse_args()
    plugins = Path(args.plugin_dir).resolve()
    if not (plugins/'libmulti_agent_system_plugin.so').is_file():
        parser.error('missing compiled MAS library')
    output = Path(tempfile.mkdtemp(prefix='lotusim-connected-native-'))
    os.environ.update(ROS_DOMAIN_ID='96', GZ_PARTITION='dataset-'+uuid.uuid4().hex,
                      LOTUSIM_SCENARIOS_PATH=str(output))
    for key in ('GZ_SIM_SYSTEM_PLUGIN_PATH', 'LD_LIBRARY_PATH'):
        os.environ[key] = str(plugins)+':/workspace/install/lib:'+os.environ.get(key, '')
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from lotusim_msgs.msg import VesselPositionArray
    from lotusim_msgs.srv import String
    import yaml

    actors = [
        ('ObserverBoat', 'fremm_observer', [0,0,0], [0,4,0], 0, 0, 4),
        ('buoy_001', 'buoy', [20,50,0], [0,0,0], 0, 0, 4),
        ('drone_001', 'small_drone', [-10,30,12], [5,0,0], 0, 0, 2),
        ('helicopter_001', 'helicopter', [300,400,80], [-30,0,0], 0, 1, 4),
        ('airplane_001', 'airplane', [500,1000,200], [-60,0,0], 0, 0, 4),
        ('bird_001', 'seagull', [30,40,10], [-10,0,0], 0, 2, 4),
        ('fast_drone_001','drone_racer_sim',[100,200,70],[400/3.6,0,0],2,0,4),
    ]
    config = dict(name='MaritimeRandomLotusim', reference_position=dict(latitude=1.2421, longitude=103.7198, altitude=0),
                  dataset_sequence=dict(plan_id='native-fixture', observer='ObserverBoat', fps=10, frames=40), agents={})
    for name,model,center,velocity,focus,start,end in actors:
        config['agents'][name] = dict(model=model, render_interface=dict(enabled=name!='ObserverBoat', renderer_type=model),
            trajectory=dict(center_enu_m=center, velocity_enu_mps=velocity, center_seconds=focus, start_seconds=start, end_seconds=end))
    (output/'fixture.yaml').write_text(yaml.safe_dump(config))
    config['agents']['ObserverBoat']['trajectory']['yaw_rate_deg_s']=.5
    config['agents']['fast_drone_001']['trajectory'].update(yaw_rate_deg_s=-5,turn_start_seconds=1,turn_end_seconds=3)
    (output/'fixture.yaml').write_text(yaml.safe_dump(config))
    bad = json.loads(json.dumps(config));bad['agents']['drone_001']['physics_interface']={'enabled': True}
    (output/'bad.yaml').write_text(yaml.safe_dump(bad))
    world=Path(args.world).read_text().replace('name="lotusim"','name="dataset_cycle_check"',1) if args.world else WORLD
    (output/'world.sdf').write_text(world)
    result={'passed':False, 'output':str(output), 'isolated_ros_domain':96}
    process=None;node=None
    try:
        with (output/'gazebo.log').open('w') as console:
            process=subprocess.Popen(['gz','sim','-s','-r','-v','1',str(output/'world.sdf')],stdout=console,stderr=subprocess.STDOUT,start_new_session=True)
        rclpy.init();node=rclpy.create_node('connected_dataset_test')
        qos=QoSProfile(depth=100)
        poses=[]
        node.create_subscription(VesselPositionArray,'/dataset_cycle_check/poses',poses.append,qos)
        launch=node.create_client(String,'/dataset_cycle_check/launch_scenario')
        control=node.create_client(String,'/dataset_cycle_check/dataset_control')
        def wait(predicate,label,timeout=20):
            deadline=time.monotonic()+timeout
            while not predicate():
                if process.poll() is not None:raise RuntimeError('isolated Gazebo exited')
                if time.monotonic()>deadline:raise TimeoutError(label)
                rclpy.spin_once(node,timeout_sec=.02)
        def call(client,data,success=True):
            request=String.Request();request.data=data if isinstance(data,str) else json.dumps(data)
            future=client.call_async(request);wait(future.done,'service response')
            response=future.result()
            assert response.success==success, response.message
            return response.message
        wait(lambda:launch.service_is_ready() and control.service_is_ready(),'services',40)
        capabilities=json.loads(call(control,dict(operation='capabilities')))
        assert capabilities==dict(schema='lotusim-dataset-capabilities-1',snapshotSchema='lotusim-dataset-step-1',ownedStop=True,steppedTimeline=True,constantTurnTrajectories=True,maxDatasetSpeedMps=350,boundedTurnTrajectories=True)
        call(control,dict(operation='inspect'),False)  # preflight did not launch anything
        call(launch,'bad.yaml',False)
        launched=json.loads(call(launch,'fixture.yaml'));token=launched['runId']
        assert json.loads(call(control,dict(operation='capabilities')))==capabilities
        call(launch,'fixture.yaml',False)
        call(control,dict(operation='step',runId='wrong-token',frame=1),False)
        call(control,dict(operation='stop',runId='wrong-token'),False)
        call(control,dict(operation='step',runId=token,frame=3),False)
        snapshots=[]
        for frame in range(40):
            snapshot=json.loads(call(control,dict(operation='step',runId=token,frame=frame)))
            assert snapshot['frame']==frame and abs(snapshot['timeSeconds']-frame/10)<1e-9
            expected={a[0]:a for a in actors if a[5]<=frame/10<a[6]}
            assert {o['instance'] for o in snapshot['objects']}==set(expected)
            for obj in snapshot['objects']:
                actor=expected[obj['instance']]
                dt=frame/10-actor[4];w=math.radians(.5) if obj['instance']=='ObserverBoat' else math.radians(-5) if obj['instance']=='fast_drone_001' else 0
                q=max(1,min(3,frame/10))-actor[4] if obj['instance']=='fast_drone_001' else dt
                velocity=actor[3]
                for i,key in enumerate(('x','y','z')):
                    delta=velocity[i]*dt
                    if w and i==0:delta=(velocity[0]*math.sin(w*q)+velocity[1]*(math.cos(w*q)-1))/w
                    if w and i==1:delta=(velocity[0]*(1-math.cos(w*q))+velocity[1]*math.sin(w*q))/w
                    if obj['instance']=='fast_drone_001' and i<2:
                        for at,extra in [(1,min(0,frame/10-1)),(3,max(0,frame/10-3))]:
                            a=w*(at-actor[4]);rotated=[math.cos(a)*velocity[0]-math.sin(a)*velocity[1],math.sin(a)*velocity[0]+math.cos(a)*velocity[1]];delta+=extra*rotated[i]
                    wanted=actor[2][i]+delta
                    assert abs(obj['position'][key]-wanted)<1e-7
                assert obj['entity']>0
                if math.hypot(*actor[3][:2])>0:
                    yaw=2*math.atan2(obj['rotation']['z'],obj['rotation']['w'])
                    target=math.atan2(velocity[1],velocity[0])+w*q
                    assert abs(math.sin(yaw)-math.sin(target))<1e-7 and abs(math.cos(yaw)-math.cos(target))<1e-7
                    vx=math.cos(w*q)*velocity[0]-math.sin(w*q)*velocity[1]
                    vy=math.sin(w*q)*velocity[0]+math.cos(w*q)*velocity[1]
                    assert abs(obj['velocity']['x']-vx)<1e-7 and abs(obj['velocity']['y']-vy)<1e-7
            snapshots.append(snapshot)
            if frame in (0,15,39):
                # Let the normal MAS PostUpdate publisher expose the same ECM.
                poses.clear()
                wait(lambda:poses and all(any(v.vessel_name==o['instance'] and abs(v.pose.position.x-o['position']['x'])<1e-6 and abs(v.pose.position.y-o['position']['y'])<1e-6 for v in poses[-1].vessels) for o in snapshot['objects']),'published ECM poses')
                again=json.loads(call(control,dict(operation='step',runId=token,frame=frame)))
                assert again==snapshot, 'retry changed the snapshot'
        time.sleep(.2)
        assert json.loads(call(control,dict(operation='step',runId=token,frame=39)))==snapshots[-1], 'dataset moved without permission'
        call(control,dict(operation='step',runId=token,frame=40),False)
        call(control,dict(operation='stop',runId=token))
        poses.clear();wait(lambda:poses and not poses[-1].vessels,'owned actor cleanup')
        second=json.loads(call(launch,'fixture.yaml'))
        assert second['runId']!=token
        call(control,dict(operation='stop',runId=token),False)
        assert json.loads(call(control,dict(operation='inspect')))['runId']==second['runId']
        call(control,dict(operation='stop',runId=second['runId']))
        result.update(passed=True,frames=40,checks=['read-only protocol preflight before/after launch','real FREMM observer mesh','seven native entities including a 400 km/h bounded-turn drone','ENU trajectories and orientation','delayed spawn/deletion','MAS ECM topic matches snapshots','idempotent retry','invalid frame rejected','competing scenario rejected','stale token cannot stop new run','cleanup and restart'])
        (output/'snapshots.json').write_text(json.dumps(snapshots,indent=2))
        print('PASS native LOTUSim stepped timeline: 40 frames, actual ECM + ROS, ownership, cleanup and restart',flush=True)
    except Exception as error:
        result['error']=str(error);raise
    finally:
        (output/'result.json').write_text(json.dumps(result,indent=2))
        if node is not None:node.destroy_node();rclpy.shutdown()
        if process is not None and process.poll() is None:
            for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGKILL):
                os.killpg(process.pid,sig)
                try:process.wait(timeout=5);break
                except subprocess.TimeoutExpired:pass
        print('TEST_RESULT',output/'result.json',flush=True)

if __name__=='__main__':main()
