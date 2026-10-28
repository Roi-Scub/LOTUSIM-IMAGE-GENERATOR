using System;
using Lotusim.Dataset;
using UnityEditor;
using UnityEngine;

namespace Lotusim.EditorTools
{
    public static class DatasetLotusimTests
    {
        [MenuItem("LOTUSim/Dataset/Validate connected LOTUSim sequence")]
        public static void Run()
        {
            DatasetLotusimSceneBuilder.Create();
            var config=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            var plan=config.MakePlan();string id=DatasetLotusimScenario.PlanId(config,plan);
            Assert(id.Length==64&&id==DatasetLotusimScenario.PlanId(config,config.MakePlan()),"Stable plan hash");
            string yaml=DatasetLotusimScenario.Yaml(config,plan);
            Assert(yaml.Contains("model: "+DatasetLotusimScenario.ObserverModel)&&yaml.Contains("plan_id: "+id)&&yaml.Contains("velocity_enu_mps:"),"Scenario authoring");
            Assert((config.observerDeckCamera?config.observerDeckOffsetM.y>7:config.observerHeightM==45)&&config.observerHullHalfExtentsM.z>=78,"FREMM camera and hull clearance");
            var copy=UnityEngine.Object.Instantiate(config);
            try {
                for(int seed=0;seed<100;seed++) {
                    copy.seed=seed;
                    foreach(var e in copy.MakePlan().events) Assert(!copy.IntersectsObserverHull(e,copy.classes[e.classIndex].separationM),"No encounter intersects FREMM hull");
                }
                var crossing=new DatasetEncounter{centerPosition=copy.origin+DatasetSequenceConfig.Bearing(copy.routeHeadingDeg)*100,
                    velocity=Vector3.zero,startSeconds=0,endSeconds=60};
                copy.durationSeconds=60;copy.observerSpeedMps=4;
                Assert(copy.IntersectsObserverHull(crossing,5),"Stationary target in bow path rejected");
                crossing.centerPosition+=Vector3.up*150;
                Assert(!copy.IntersectsObserverHull(crossing,5),"High overhead target allowed");
            } finally {UnityEngine.Object.DestroyImmediate(copy);}
            CheckSnapshot();CheckProtocol();CheckLighting();CheckSeaEvolution();
            Assert(plan.lightingPhases!=null&&plan.lightingPhases[0].light.name=="day"&&yaml.Contains("unity_render_lighting:"),"Connected lighting schedule export");
            Debug.Log("[LOTUSim Dataset] PASS FREMM, day/evening/night, protocol preflight, scenario hash, ENU conversion, snapshots and stale-frame rejection.");
        }
        public static void CheckSnapshot()
        {
            var item=new DatasetLotusimObject{instance="ObserverBoat",model=DatasetLotusimScenario.ObserverModel,entity=42,position=new Vector3(1,2,3),rotation=Quaternion.identity};
            Assert(item.UnityPose.position==new Vector3(1,3,2),"ENU / Unity Y-up conversion");
            var frame=new DatasetLotusimFrame{schema="lotusim-dataset-step-1",scenario=DatasetLotusimScenario.Name,observer=DatasetLotusimScenario.Observer,
                runId="owned",planId="plan",frame=3,fps=30,frames=120,timeSeconds=.1,worldTimeSeconds=10,objects=new[]{item}};
            frame.Validate("owned","plan",3,30,120);
            Reject(()=>frame.Validate("stale","plan",3,30,120));Reject(()=>frame.Validate("owned","different-plan",3,30,120));
            Reject(()=>frame.Validate("owned","plan",4,30,120));
            item.rotation=new Quaternion(0,0,0,0);Reject(()=>frame.Validate("owned","plan",3,30,120));item.rotation=Quaternion.identity;
            frame.objects=new[]{item,item};Reject(()=>frame.Validate("owned","plan",3,30,120));
        }
        public static void CheckProtocol()
        {
            DatasetLotusimProtocol.CheckCapabilities("{\"schema\":\"lotusim-dataset-capabilities-1\",\"snapshotSchema\":\"lotusim-dataset-step-1\",\"steppedTimeline\":true,\"ownedStop\":true}");
            Reject(()=>DatasetLotusimProtocol.CheckCapabilities("Scenario launched: MaritimeRandomLotusim"));
            Reject(()=>DatasetLotusimProtocol.CheckCapabilities("{\"schema\":\"old\"}"));
            Reject(()=>DatasetLotusimProtocol.ReadFrame("Scenario launched: MaritimeRandomLotusim","launching"));
            Reject(()=>DatasetLotusimProtocol.ReadFrame("{not valid json}","stepping"));
            Reject(()=>DatasetLotusimProtocol.CheckCapabilities("{\"schema\":\"lotusim-dataset-capabilities-1\",\"snapshotSchema\":\"lotusim-dataset-step-1\",\"ownedStop\":true,\"steppedTimeline\":true}",true));
            DatasetLotusimProtocol.CheckCapabilities("{\"schema\":\"lotusim-dataset-capabilities-1\",\"snapshotSchema\":\"lotusim-dataset-step-1\",\"ownedStop\":true,\"steppedTimeline\":true,\"constantTurnTrajectories\":true}",true);
        }
        public static void CheckSeaEvolution()
        {
            var settings=new DatasetSeaEvolution{enabled=true};settings.Validate();
            float low=200,high=0;
            for(int i=0;i<18000;i++) {
                float time=i/30f;var a=settings.Evaluate(time,42);var b=settings.Evaluate(time,42);
                Assert(a.windKmh>=settings.minWindKmh&&a.windKmh<=settings.maxWindKmh&&a.band0>=settings.minBand&&a.band1>0,"Never flat evolving sea");
                Assert(a.windKmh==b.windKmh,"Seeded sea replay");low=Mathf.Min(low,a.windKmh);high=Mathf.Max(high,a.windKmh);
                Assert(Mathf.Abs(a.windKmh-settings.Evaluate(time+1f/30,42).windKmh)<.2f,"Smooth evolution between source steps");
            }
            Assert(high-low>25,"Strong sea variation");
        }
        public static void CheckLighting()
        {
            var settings=new DatasetSequenceLightingSettings{cycleDayEveningNight=true};
            for(int images=3;images<=401;images++) foreach(int stride in new[]{1,5,17}) {
                int frames=(images-1)*stride+1;var phases=settings.Build(frames,stride);
                var plan=new DatasetSequencePlan{lightingPhases=phases};var counts=new int[3];
                for(int frame=0;frame<frames;frame+=stride) counts[plan.LightingPhaseAt(frame)]++;
                Assert(counts[0]+counts[1]+counts[2]==images&&Math.Abs(counts[0]-counts[1])<=1&&Math.Abs(counts[0]-counts[2])<=1,"Balanced capture counts");
                Assert(phases[0].startFrame==0&&phases[2].endFrame==frames&&phases[0].endFrame==phases[1].startFrame&&phases[1].endFrame==phases[2].startFrame,"Gap-free frame coverage");
                Assert(plan.LightingPhaseAt(phases[1].startFrame)==1&&plan.LightingPhaseAt(phases[2].startFrame)==2,"Exact half-open phase boundaries");
            }
            var normal=settings.Build(1800,5);
            Assert(normal[0].endFrame==600&&normal[1].endFrame==1200&&normal[2].endFrame==1800,"360 captures: 120 day / 120 evening / 120 night");
            Assert(settings.day.exposureEV100==13&&settings.evening.intensityLux==8000&&settings.night.illuminant=="full_moon"&&settings.night.exposureEV100<0,"Readable exposure defaults");
            try {settings.Build(2,1);throw new Exception("Two captures accepted for three lighting phases");} catch(ArgumentException) {}
            settings.night.exposureEV100=float.NaN;
            try {settings.Validate();throw new Exception("NaN exposure accepted");} catch(ArgumentException) {}
        }
        static void Reject(Action check) {try {check();} catch(InvalidOperationException) {return;}throw new Exception("Invalid snapshot was accepted");}
        static void Assert(bool value,string label) {if(!value) throw new InvalidOperationException(label);}
    }
}
