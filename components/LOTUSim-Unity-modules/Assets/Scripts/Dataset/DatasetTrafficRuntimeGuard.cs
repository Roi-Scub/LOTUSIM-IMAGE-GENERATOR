using System;
using System.Linq;
using UnityEngine;
namespace Lotusim.Dataset
{
    // Fail-closed monitor, NOT a second controller or a reactive navigator.
    public static class DatasetTrafficRuntimeGuard
    {
        public static void Check(DatasetSequenceConfig c,DatasetSequencePlan plan,float time,DatasetSequenceActor[] actors,Pose observer)
        {
            if(plan.traffic==null)return;
            float tolerance=plan.traffic.runtimePositionToleranceM;
            if(actors.Length!=plan.events.Length||Vector3.Distance(observer.position,c.ObserverRoot(time))>tolerance)throw new InvalidOperationException("Traffic source differs from the reserved observer/actor plan; owned run stopped before capture.");
            foreach(var actor in actors)if(Vector3.Distance(actor.sourcePose.position,actor.encounter.Position(time))>tolerance)throw new InvalidOperationException("Unplanned motion of "+actor.encounter.instance+". No evasive teleport was applied; owned run stopped.");
            foreach(var actor in actors){var p=plan.traffic.actorProfiles.Single(a=>a.instance==actor.encounter.instance);if(p.minCameraDistanceM>0&&Vector3.Distance(actor.sourcePose.position,c.ObserverNominal(time))<p.minCameraDistanceM)throw new InvalidOperationException("Drone camera stand-off violated; owned run stopped before capture.");}
            var profiles=plan.traffic.actorProfiles.Concat(new[]{new DatasetTrafficActorProfile{instance=DatasetLotusimScenario.Observer,category="observer",domain="sea",lengthM=148,heightM=40,bufferM=c.trafficPlan.safety.observerBufferM}}).ToArray();
            var positions=actors.Select(a=>a.sourcePose.position).Concat(new[]{observer.position}).ToArray();
            // Actor order and metadata order are tied by unique instance name.
            for(int i=0;i<actors.Length;i++)profiles[i]=plan.traffic.actorProfiles.Single(p=>p.instance==actors[i].encounter.instance);
            for(int i=0;i<positions.Length;i++)for(int j=i+1;j<positions.Length;j++) {
                var a=profiles[i];var b=profiles[j];var s=c.trafficPlan.safety;float horizontal,vertical=0;
                if(a.domain!="air"&&b.domain!="air")horizontal=a.lengthM*.5f+a.bufferM+b.lengthM*.5f+b.bufferM+s.seaClearanceM;
                else if(a.domain=="air"&&b.domain=="air") {bool large=a.category=="airplane"||a.category=="helicopter"||b.category=="airplane"||b.category=="helicopter";horizontal=large?s.aircraftHorizontalM:35;vertical=large?s.aircraftVerticalM:20;}
                else {var sea=a.domain=="air"?b:a;var air=a.domain=="air"?a:b;horizontal=sea.lengthM*.5f+sea.bufferM+air.bufferM+30;vertical=sea.heightM+air.heightM*.5f+15;}
                var delta=positions[i]-positions[j];if(vertical>0&&Mathf.Abs(delta.y)>=vertical)continue;
                if(new Vector2(delta.x,delta.z).magnitude<horizontal-.01f)throw new InvalidOperationException("Traffic safety domain violated: "+a.instance+" / "+b.instance+". Owned run stopped before capture.");
            }
        }
    }
}
