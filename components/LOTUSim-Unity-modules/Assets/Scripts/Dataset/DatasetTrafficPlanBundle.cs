using System;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
namespace Lotusim.Dataset
{
    [Serializable] public sealed class DatasetTrafficActorProfile
    {
        public string instance,model,category,domain,evidence;
        public float lengthM,heightM,bufferM,groundSpeedMps,speedKnots,speedKmh,airSpeedEstimateMps,safeMaximumMps,maxSpeedMps,altitudeM;
        public string flightMode;
        public bool syntheticPerformance;
        public float minCameraDistanceM,cameraDistanceLowerBoundM;
    }
    [Serializable] public sealed class DatasetTrafficMetadata
    {
        public string schema,scenarioName,inputSha256,plannerSha256;
        public float localWindMps,significantSwellHeightM,runtimePositionToleranceM;
        public bool continuousSafetyApproved,reactiveAvoidance;
        public DatasetTrafficActorProfile[] actorProfiles;
    }
    [Serializable] public sealed class DatasetTrafficSafetySettings
    {
        public float seaClearanceM=30,observerBufferM=90,aircraftHorizontalM=500,aircraftVerticalM=300,planningMarginM=5;
    }
    public sealed class DatasetTrafficPlanBundle : ScriptableObject
    {
        [TextArea(2,8)] public string planJson,scopeJson,catalogueJson,auditJson,messagesJson;
        public string contentSha256;
        public DatasetTrafficSafetySettings safety=new DatasetTrafficSafetySettings();
        public static string Hash(string value){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-","").ToLowerInvariant();}
        public string ComputeHash()=>Hash(planJson+"|"+scopeJson+"|"+catalogueJson+"|"+auditJson+"|"+messagesJson+"|"+JsonUtility.ToJson(safety));
        public DatasetSequencePlan Read(DatasetSequenceConfig config)
        {
            if(contentSha256!=ComputeHash())throw new InvalidOperationException("Traffic plan bundle changed: regenerate it with LOTUSim > Dataset > Cooperative traffic > Generate.");
            var p=JsonUtility.FromJson<DatasetSequencePlan>(planJson);var meta=p?.traffic;
            if(p==null||p.schema!="lotusim-unity-encounters-1"||p.seed!=config.seed||meta==null||meta.schema!="lotusim-cooperative-traffic-1"||meta.scenarioName!=config.ScenarioName||!meta.continuousSafetyApproved||meta.reactiveAvoidance||meta.runtimePositionToleranceM<.01f||meta.runtimePositionToleranceM>5||meta.actorProfiles==null||meta.actorProfiles.Length!=p.events?.Length||p.events.Length<1||p.events.Length>40||p.maxActive!=p.events.Length)
                throw new InvalidOperationException("Invalid/stale cooperative traffic plan. Regenerate before Play.");
            if(p.events.Select(e=>e.instance).Distinct().Count()!=p.events.Length||p.events.Select(e=>e.trackId).Distinct().Count()!=p.events.Length)throw new InvalidOperationException("Duplicate traffic identities.");
            if(!(p.captureFrames??Array.Empty<int>()).SequenceEqual(config.captureFrames??Array.Empty<int>()))throw new InvalidOperationException("Capture burst schedule differs from compiled plan; regenerate.");
            foreach(var e in p.events) {
                if(e==null||e.classIndex<0||e.classIndex>=config.classes.Length||e.category!=config.classes[e.classIndex].category||e.trackId<1||e.startSeconds!=0||Mathf.Abs(e.endSeconds-config.durationSeconds)>.001f||!Finite(e.centerSeconds)||!Finite(e.altitudeM)||!Finite(e.centerPosition.x)||!Finite(e.centerPosition.y)||!Finite(e.centerPosition.z)||!Finite(e.velocity.x)||!Finite(e.velocity.y)||!Finite(e.velocity.z)||e.velocity.y!=0||e.velocity.magnitude>350||Mathf.Abs(e.centerPosition.x)>100000||Mathf.Abs(e.centerPosition.z)>100000||e.centerPosition.y<0||e.centerPosition.y>15000)
                    throw new InvalidOperationException("Invalid cooperative traffic trajectory.");
                if(!Finite(e.yawRateDegS)||Mathf.Abs(e.yawRateDegS)>5||e.boundedTurn&&(!Finite(e.turnStartSeconds)||!Finite(e.turnEndSeconds)||e.turnStartSeconds<e.startSeconds||e.turnEndSeconds>e.endSeconds||e.turnEndSeconds<=e.turnStartSeconds||e.centerSeconds<e.turnStartSeconds||e.centerSeconds>e.turnEndSeconds)||Mathf.Abs(e.yawRateDegS)*(e.boundedTurn?e.turnEndSeconds-e.turnStartSeconds:e.endSeconds-e.startSeconds)>45.0001f)throw new InvalidOperationException("Invalid bounded turn in compiled traffic plan.");
                var profile=meta.actorProfiles.SingleOrDefault(a=>a.instance==e.instance);
                if(profile==null||profile.model!=e.modelName||profile.category!=e.category||profile.lengthM<=0||profile.heightM<=0||profile.bufferM<=0||e.velocity.magnitude>profile.safeMaximumMps+.002f||Mathf.Abs(profile.altitudeM-e.centerPosition.y)>.002f||DatasetBoatVariants.Resolve(config.classes[e.classIndex],e)==null)
                    throw new InvalidOperationException("Traffic capabilities/prefab mismatch: "+e.instance);
            }
            foreach(var c in config.classes)if(p.events.Count(e=>e.category==c.category)!=c.count)throw new InvalidOperationException("Traffic encounter counts changed; regenerate the scoped plan.");
            return p;
        }
        static bool Finite(float v)=>!float.IsNaN(v)&&!float.IsInfinity(v);
    }
}
