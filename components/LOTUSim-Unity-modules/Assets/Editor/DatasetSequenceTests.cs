using System;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetSequenceTests
    {
        [MenuItem("LOTUSim/Dataset/Validate randomized sequence planning")]
        public static void Run()
        {
            DatasetSequenceSceneBuilder.Create();var source=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetSequenceSceneBuilder.ConfigPath);
            var config=UnityEngine.Object.Instantiate(source);try {Check(config);Debug.Log("[Sequence] Planning PASS: 100 seeds, ranges, timing, separation, IDs, capacities and beacon cadence.");} finally {UnityEngine.Object.DestroyImmediate(config);}
        }
        public static void Check(DatasetSequenceConfig config,bool nativeRotation=true)
        {
            config.Validate(false);Assert(config.ImageCount==(config.SimulationFrames+config.captureEveryFrames-1)/config.captureEveryFrames,"Sample count");
            if(Mathf.Abs(config.observerTurnDeg)<.0001f) Assert(Vector3.Distance(config.ObserverNominal(10)-config.ObserverNominal(0),DatasetSequenceConfig.Bearing(config.routeHeadingDeg)*config.observerSpeedMps*10)<.001f,"Linear route independent of gaze");
            int seed=config.seed;
            try {
                for(int i=0;i<100;i++) {
                    config.seed=i;var a=config.MakePlan();var b=config.MakePlan();
                    Assert(a.events.Length==config.classes.Sum(c=>c.count)&&a.maxActive<=config.maxActiveObjects,"Event count and mask capacity");
                    Assert(a.events.Select(e=>e.instance).Distinct().Count()==a.events.Length&&a.events.Select(e=>e.trackId).Distinct().Count()==a.events.Length,"Unique persistent IDs");
                    for(int j=0;j<a.events.Length;j++) {
                        var e=a.events[j];var c=config.classes[e.classIndex];
                        Assert(e.centerPosition==b.events[j].centerPosition&&e.velocity==b.events[j].velocity,"Seed replay");
                        Assert(e.distanceRequestedM>=c.distanceM.x&&e.distanceRequestedM<=c.distanceM.y&&e.altitudeM>=c.altitudeM.x&&e.altitudeM<=c.altitudeM.y,"Class-specific distance/altitude ranges");
                        Assert(e.Active(e.centerSeconds)&&!e.Active(e.endSeconds),"Half-open lifetime");
                        Assert(Vector3.Distance(e.Position(e.centerSeconds),e.centerPosition)<.001f,"Crossing center");
                        if(c.moored) Assert(e.Position(0)==e.Position(50),"Buoy fixed in world, not camera-relative");
                        else {
                            Assert(e.velocity.magnitude>=c.speedMps.x-.001f&&e.velocity.magnitude<=c.speedMps.y+.001f,"Aircraft/bird speed bounds");
                            if(nativeRotation) CheckRotation(e.velocity);
                            float edge=Mathf.Tan(config.verticalFovDeg*Mathf.Deg2Rad/2)*config.width/config.height;
                            foreach(float t in new[]{e.startSeconds,e.endSeconds}) if(t>0&&t<config.durationSeconds) {
                                var f=DatasetSequenceConfig.Bearing(config.ViewHeading(t));var r=DatasetSequenceConfig.Bearing(config.ViewHeading(t)+90);
                                var relative=e.Position(t)-config.ObserverNominal(t);float depth=Vector3.Dot(relative,f);
                                Assert(depth<=0||Mathf.Abs(Vector3.Dot(relative,r))>edge*depth+5,"No spawn/despawn in nominal image field");
                            }
                        }
                        for(int k=0;k<j;k++) Assert(!DatasetSequenceConfig.TooClose(e,a.events[k],Mathf.Max(c.separationM,config.classes[a.events[k].classIndex].separationM),config.durationSeconds),"Synthetic separation constraint");
                        var observer=new DatasetEncounter{centerPosition=config.ObserverNominal(0),velocity=DatasetSequenceConfig.Bearing(config.routeHeadingDeg)*config.observerSpeedMps,startSeconds=0,endSeconds=config.durationSeconds};
                        if(c.moored) observer.centerPosition.y=config.origin.y;
                        if(Mathf.Abs(config.observerTurnDeg)<.0001f) Assert(!DatasetSequenceConfig.TooClose(e,observer,Mathf.Max(5,c.separationM),config.durationSeconds),"Observer route clear of encounters");
                        else Assert(!config.IntersectsObserverHull(e,c.separationM),"Curved observer route clear of encounters");
                    }
                }
            }
            finally {config.seed=seed;}
            Assert(DatasetAircraftLights.BeaconLevel(.06f,0)>.99f&&DatasetAircraftLights.BeaconLevel(.5f,0)==0&&DatasetAircraftLights.BeaconLevel(1.26f,0)>.99f,"Beacon on/off/repetition");
            Assert(DatasetAnnotationExport.Yolo(new[]{0,0,10,10},100,100,4).StartsWith("4 "),"Multi-class YOLO index");
        }
        static void CheckRotation(Vector3 velocity)
        {
            var rotation=Quaternion.LookRotation(velocity.normalized,Vector3.up)*Quaternion.Euler(0,-90,0);
            Assert(Vector3.Dot(rotation*Vector3.right,velocity.normalized)>.999f,"Prefab +X nose follows trajectory");
        }
        static void Assert(bool value,string message) {if(!value) throw new InvalidOperationException("Sequence test failed: "+message);}
    }
}
