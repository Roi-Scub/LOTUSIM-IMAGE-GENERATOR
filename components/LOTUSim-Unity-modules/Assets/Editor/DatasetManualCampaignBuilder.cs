using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    // Explicit, offline import only. No polling, auto-Play, process spawning,
    // new TCP client, or mutation of any pre-existing dataset scene/config.
    public static class DatasetManualCampaignBuilder
    {
        [Serializable] sealed class Manifest {public string schema,id,name,campaignSha256,relativeCampaignFile,engine,scene;public int totalImages;public DatasetImportedAssetRevision[] importedAssetRevisions;}
        [Serializable] sealed class Catalogue {public string schema;public Asset[] assets;}
        [Serializable] sealed class Asset {public string model,category,domain,importId,requestSha256,revisionSha256,prefabGuid,prefabSha256;public int classId;public float maxSpeedMps,maxAltitudeM,lengthM,beamM,heightM,bufferM;}
        sealed class Job {public DatasetSequenceConfig config;public DatasetManualPlanBundle bundle;public string yaml;}
        public static string CoreRoot=>Path.GetFullPath(Path.Combine(Application.dataPath,"..","..","LOTUSim"));
        [MenuItem("LOTUSim/Dataset/Manual campaigns/Import prepared campaign")]
        public static void Import()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode){EditorUtility.DisplayDialog("Manual campaign","Quitte Play avant l’import.","OK");return;}
            string file=EditorUtility.OpenFilePanel("Choisir manifest.json de la campagne préparée",Path.Combine(CoreRoot,"artifacts/campaign-settings/prepared"),"json");
            if(string.IsNullOrEmpty(file))return;
            try {ImportManifest(file,true);}catch(Exception e){Debug.LogError("[Manual Campaign] Import refused; no scenario launched. "+e);EditorUtility.DisplayDialog("Import refusé",e.Message,"OK");}
        }
        public static string ImportManifest(string file,bool openScene=false)
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode)throw new InvalidOperationException("Import outside Play only.");
            if(!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())throw new OperationCanceledException("Import cancelled; scenes unchanged.");
            if(Path.GetFileName(file)!="manifest.json")throw new InvalidDataException("Select manifest.json, not an arbitrary JSON/configuration.");
            var manifest=JsonUtility.FromJson<Manifest>(File.ReadAllText(file));
            if(manifest?.schema!="lotusim-manual-campaign-1"||!SafeId(manifest.id)||manifest.relativeCampaignFile!="campaign.json"||manifest.engine!="unity"||manifest.scene!="maritime_manual")throw new InvalidDataException("Unsupported prepared campaign manifest.");
            string json=File.ReadAllText(Path.Combine(Path.GetDirectoryName(Path.GetFullPath(file)),"campaign.json"));
            if(DatasetTrafficPlanBundle.Hash(json)!=manifest.campaignSha256)throw new InvalidDataException("Campaign hash mismatch; prepare it again in the dashboard.");
            var request=JsonUtility.FromJson<DatasetManualCampaignRequest>(json);ValidateRequest(request,manifest.totalImages);
            var original=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if(original==null||!File.Exists(DatasetLotusimSceneBuilder.ScenePath))throw new FileNotFoundException("Create the existing connected scene using Dataset menu 7 first.");
            var catalogue=ReadCatalogue(request,manifest);
            string folder="Assets/Dataset/ManualCampaigns/"+manifest.id;
            string scene="Assets/Scenes/Dataset/ManualCampaign_"+manifest.id+".unity";
            if(AssetDatabase.IsValidFolder(folder)||File.Exists(scene))throw new IOException("This prepared campaign was already imported. Prepare a new revision rather than overwriting its immutable assets.");
            var jobs=new List<Job>();
            try {
                int index=0;
                foreach(var block in request.blocks)for(int image=0;image<block.images;image++)
                    jobs.Add(BuildJob(original,request,block,image,index++,manifest.id,manifest.campaignSha256,json,catalogue.assets,manifest.importedAssetRevisions));
                // All inputs/plans/prefabs/capabilities validated before asset or
                // LOTUSim scenario writes. An import never launches simulation.
                EnsureFolder(folder);EnsureFolder("Assets/Scenes/Dataset");
                string scenarios=Path.Combine(CoreRoot,"assets/scenarios");
                foreach(var job in jobs) {
                    string target=Path.Combine(scenarios,job.config.ScenarioName+".yaml");
                    if(File.Exists(target))throw new IOException("Refusing to overwrite an existing scenario: "+target);
                }
                for(int i=0;i<jobs.Count;i++) {
                    var job=jobs[i];AssetDatabase.CreateAsset(job.bundle,folder+"/image_"+i.ToString("D5")+".plan.asset");
                    AssetDatabase.CreateAsset(job.config,folder+"/image_"+i.ToString("D5")+".asset");
                    DatasetSequenceExport.Atomic(Path.Combine(scenarios,job.config.ScenarioName+".yaml"),job.yaml);
                }
                var asset=ScriptableObject.CreateInstance<DatasetManualCampaignAsset>();asset.campaignId=manifest.id;asset.campaignJson=json;asset.campaignSha256=manifest.campaignSha256;
                asset.preparedManifestJson=File.ReadAllText(file);
                asset.jobs=jobs.Select(j=>j.config).ToArray();asset.scenarioFiles=jobs.Select(j=>j.config.ScenarioName+".yaml").ToArray();asset.Validate();
                AssetDatabase.CreateAsset(asset,folder+"/campaign.asset");AssetDatabase.SaveAssets();CreateScene(scene,asset);
                if(openScene){EditorSceneManager.OpenScene(scene,OpenSceneMode.Single);DatasetCampaignMonitor.ShowWindow();}
                Debug.Log("[Manual Campaign] Imported "+jobs.Count+" independent images. Play this new scene to run; existing scenes/configs unchanged. "+scene);
                return scene;
            }finally {
                foreach(var j in jobs) {if(!AssetDatabase.Contains(j.config))Object.DestroyImmediate(j.config);if(!AssetDatabase.Contains(j.bundle))Object.DestroyImmediate(j.bundle);}
            }
        }
        static void ValidateRequest(DatasetManualCampaignRequest r,int expected)
        {
            if(r?.schema!="lotusim-campaign-settings-1"||r.engine!="unity"||r.scene!="maritime_manual"||r.camera==null||r.observer==null||r.sensors==null||!r.sensors.rgb||r.sensors.thermal||r.sensors.nightVision||
                r.totalImages!=expected||expected<1||expected>2000||r.blocks==null||r.blocks.Length<1||r.blocks.Length>50||r.blocks.Any(b=>b==null||b.images<1||!SafeId(b.id)||b.environment==null||b.objects==null||b.objects.Length==0)||r.blocks.Sum(b=>b.images)!=expected||r.blocks.Select(b=>b.id).Distinct().Count()!=r.blocks.Length)
                throw new InvalidDataException("Invalid manual campaign blocks/image counts.");
            if(r.camera.station!="bridge"||r.camera.width<64||r.camera.width>4096||r.camera.height<64||r.camera.height>4096||
                !Range(r.camera.verticalFovDeg,30,90)||!Range(r.camera.farClipM,5000,100000)||!Range(r.camera.viewHeadingDeg,0,360)||!Range(r.camera.viewDownPitchDeg,-10,15)||
                !Range(r.observer.speedMps,0,13.89f)||!Range(r.observer.headingDeg,0,360)||!Range(r.observer.rollMaxDeg,0,12)||!Range(r.observer.pitchMaxDeg,0,8))throw new InvalidDataException("Invalid camera/observer settings.");
            foreach(var b in r.blocks) {
                b.environment.Validate();
                if(b.objects.Any(o=>o==null||!SafeId(o.id)||!SafeId(o.model)||o.count<1||o.count>12||!Range(o.distanceM,5,60000)||!Range(o.bearingDeg,-180,360)||!Range(o.spreadDeg,0,360)||
                    !Range(o.altitudeM,0,15000)||!Range(o.speedMps,0,350)||!Range(o.headingDeg,0,360)||!new[]{"metres","pixel_height"}.Contains(o.distanceMode))||
                    b.objects.Sum(o=>o.count)>40||b.objects.Select(o=>o.id).Distinct().Count()!=b.objects.Length)throw new InvalidDataException("Invalid manual object rows.");
            }
        }
        static Catalogue ReadCatalogue(DatasetManualCampaignRequest request,Manifest manifest)
        {
            var catalogue=JsonUtility.FromJson<Catalogue>(File.ReadAllText(Path.Combine(CoreRoot,"assets/scenarios/catalogs/traffic_assets.json")));
            if(catalogue?.assets==null)throw new InvalidDataException("Traffic asset capability catalogue missing.");
            var requested=request.blocks.SelectMany(b=>b.objects).Select(o=>o.model).Where(DatasetImportedAssetRegistry.ModelKey).Distinct().ToArray();
            var pins=manifest.importedAssetRevisions??Array.Empty<DatasetImportedAssetRevision>();
            if(pins.Any(p=>p==null)||pins.Length!=requested.Length||pins.Select(p=>p.model).Distinct().Count()!=pins.Length||pins.Any(p=>!requested.Contains(p.model)))
                throw new InvalidDataException("Imported asset revision pins are missing or inconsistent; prepare the campaign again.");
            if(requested.Length==0)return catalogue;
            string path=Path.Combine(CoreRoot,"assets/scenarios/catalogs/imported_assets.json");DatasetDashboardImportContract.NoLinks(path);
            var imports=JsonUtility.FromJson<Catalogue>(File.ReadAllText(path));
            if(imports?.schema!="lotusim-imported-catalogue-1"||imports.assets==null)throw new InvalidDataException("Imported ready catalogue missing.");
            var added=new List<Asset>();
            foreach(string model in requested) {
                var records=imports.assets.Where(a=>a!=null&&a.model==model).ToArray();if(records.Length!=1)throw new InvalidDataException("Imported model is not ready: "+model);
                var value=records[0];var pin=pins.Single(p=>p.model==model);string prefabPath=DatasetDashboardMeshBuilder.PrefabPath(model);
                var prefab=AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);var marker=prefab==null?null:prefab.GetComponent<DatasetImportedAsset>();
                if(marker==null||marker.model!=model||marker.importId!=value.importId||marker.category!=value.category||marker.domain!=value.domain||
                    marker.classId!=value.classId||marker.classId!=DatasetImportedAssetRegistry.ClassId(value.category)||
                    marker.requestSha256!=value.requestSha256||marker.revisionSha256!=value.revisionSha256||
                    pin.requestSha256!=value.requestSha256||pin.revisionSha256!=value.revisionSha256||pin.prefabGuid!=value.prefabGuid||pin.prefabSha256!=value.prefabSha256||
                    !DatasetImportedAssetRegistry.Hex(value.prefabGuid,32)||!DatasetImportedAssetRegistry.Hex(value.prefabSha256,64)||
                    AssetDatabase.AssetPathToGUID(prefabPath)!=value.prefabGuid||DatasetDashboardImportContract.FileHash(prefabPath)!=value.prefabSha256||
                    !DatasetImportedAssetRegistry.Matches(model,value.category)||Math.Abs(marker.maxSpeedMps-value.maxSpeedMps)>.0001f||Math.Abs(marker.maxAltitudeM-value.maxAltitudeM)>.0001f||
                    Math.Abs(marker.lengthM-value.lengthM)>.005f||Math.Abs(marker.beamM-value.beamM)>.005f||Math.Abs(marker.heightM-value.heightM)>.005f)
                    throw new InvalidDataException("Imported prefab/catalogue/pinned revision mismatch: "+model);
                added.Add(value);
            }
            catalogue.assets=catalogue.assets.Concat(added).ToArray();
            if(catalogue.assets.Select(a=>a.model).Distinct().Count()!=catalogue.assets.Length)throw new InvalidDataException("Duplicate model in merged catalogue.");
            return catalogue;
        }
        static Job BuildJob(DatasetSequenceConfig original,DatasetManualCampaignRequest request,DatasetManualBlock block,int image,int index,string id,string sha,string json,Asset[] catalogue,DatasetImportedAssetRevision[] pins)
        {
            var c=Object.Instantiate(original);var bundle=ScriptableObject.CreateInstance<DatasetManualPlanBundle>();
            try {
                c.name="Manual image "+index;c.trafficPlan=null;c.manualPlan=bundle;c.captureFrames=new[]{0};
                bundle.importedAssetRevisions=(pins??Array.Empty<DatasetImportedAssetRevision>()).Where(p=>block.objects.Any(o=>o.model==p.model)).ToArray();
                c.scenarioName="Manual_"+DatasetTrafficPlanBundle.Hash(id).Substring(0,12)+"_"+index.ToString("D5");
                c.seed=unchecked(request.seed*397^index*7919);c.durationSeconds=4;c.simulationFps=30;c.captureEveryFrames=1;c.warmupFrames=45;
                c.width=request.camera.width;c.height=request.camera.height;c.verticalFovDeg=request.camera.verticalFovDeg;c.farClipM=request.camera.farClipM;
                c.routeHeadingDeg=Mathf.Repeat(request.observer.headingDeg,360);c.viewHeadingDeg=Mathf.Repeat(c.routeHeadingDeg+request.camera.viewHeadingDeg,360);c.viewDownPitchDeg=request.camera.viewDownPitchDeg;
                c.observerSpeedMps=request.observer.speedMps;c.observerTurnDeg=0;c.observerDeckCamera=true;c.observerCameraStation="navigation_bridge_front";
                c.observerDeckOffsetM=new Vector3(30.3f,12.4f,-5.5f);c.observerHeightM=12.4f;c.observerMaxRollDeg=request.observer.rollMaxDeg;c.observerMaxPitchDeg=request.observer.pitchMaxDeg;
                c.origin=Vector3.zero;c.maxActiveObjects=40;c.outputRoot="artifacts/manual-image-jobs/"+id;c.renderTimeoutSeconds=Mathf.Max(c.renderTimeoutSeconds,90);
                c.seaEvolution=new DatasetSeaEvolution{enabled=false};c.requireSwell=false;c.lighting.cycleDayEveningNight=false;
                c.sensors.thermal=request.sensors.thermal;c.sensors.nightVision=request.sensors.nightVision;
                var events=new List<DatasetEncounter>();var placements=new List<DatasetManualObjectPlacement>();
                foreach(var definition in c.classes)definition.count=0;
                var random=new System.Random(c.seed);Vector3 eye=c.ObserverNominal(0);
                foreach(var row in block.objects) {
                    var a=catalogue.SingleOrDefault(v=>v.model==row.model);if(a==null)throw new InvalidDataException("Unknown model: "+row.model);
                    if(row.speedMps>a.maxSpeedMps+.0001f||a.domain=="moored"&&row.speedMps!=0||a.domain!="air"&&row.altitudeM!=0||a.maxAltitudeM>0&&row.altitudeM>a.maxAltitudeM)
                        throw new InvalidDataException("Speed/altitude exceeds the capability of "+row.model);
                    int classIndex=Array.FindIndex(c.classes,v=>v.category==a.category);
                    if(classIndex<0&&a.category=="other"&&a.classId==13&&a.domain=="moored") {
                        var imported=AssetDatabase.LoadAssetAtPath<GameObject>(DatasetDashboardMeshBuilder.PrefabPath(a.model));
                        if(imported==null||imported.GetComponent<DatasetImportedAsset>()==null)throw new InvalidDataException("Imported other-object prefab missing.");
                        c.classes=c.classes.Concat(new[]{new DatasetEncounterClass{category="other",displayName="Autre objet importé",classId=13,
                            prefab=imported,moored=true,distanceM=new Vector2(5,60000),altitudeM=Vector2.zero,speedMps=Vector2.zero,separationM=Mathf.Clamp(a.bufferM,.1f,200)}}).ToArray();
                        classIndex=c.classes.Length-1;
                    }
                    if(classIndex<0)throw new InvalidDataException("No Unity category for "+a.category);
                    var definition=c.classes[classIndex];definition.count+=row.count;if(definition.count>12)throw new InvalidDataException("At most 12 objects per category.");
                    var prefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+row.model+".prefab");if(prefab==null)throw new FileNotFoundException("Unity prefab missing: "+row.model);
                    definition.prefabVariants=(definition.prefabVariants??Array.Empty<GameObject>()).Concat(new[]{prefab}).Where(p=>p!=definition.prefab).Distinct().ToArray();
                    definition.distanceM=new Vector2(5,60000);definition.altitudeM=new Vector2(0,15000);definition.speedMps=definition.moored?Vector2.zero:new Vector2(.001f,350);
                    for(int n=0;n<row.count;n++) {
                        float angular=row.count==1?((float)random.NextDouble()-.5f)*row.spreadDeg:((n+.15f+.7f*(float)random.NextDouble())/row.count-.5f)*row.spreadDeg;
                        float bearing=c.viewHeadingDeg+row.bearingDeg+angular;
                        var position=eye+DatasetSequenceConfig.Bearing(bearing)*row.distanceM;position.y=c.origin.y+row.altitudeM;
                        string instance="ManualObject_"+(events.Count+1).ToString("D3");
                        events.Add(new DatasetEncounter{instance=instance,category=a.category,modelName=row.model,trackId=events.Count+1,classIndex=classIndex,
                            startSeconds=0,endSeconds=c.durationSeconds,centerSeconds=0,distanceRequestedM=row.distanceM,altitudeM=row.altitudeM,centerPosition=position,
                            velocity=DatasetSequenceConfig.Bearing(row.headingDeg)*row.speedMps,phase=(float)random.NextDouble()*Mathf.PI*2});
                        placements.Add(new DatasetManualObjectPlacement{requestId=row.id,instance=instance,model=row.model,distanceMode=row.distanceMode,
                            requestedHorizontalDistanceM=row.distanceM,nominalBearingDeg=bearing,requestedTargetHeightPx=row.targetHeightPx,headingDeg=row.headingDeg});
                    }
                }
                DatasetLightPreset light=block.environment.timeOfDay=="night"?c.lighting.night:block.environment.timeOfDay=="dusk"?c.lighting.evening:c.lighting.day;
                var plan=new DatasetSequencePlan{seed=c.seed,maxActive=events.Count,events=events.ToArray(),captureFrames=new[]{0},sea=block.environment.Sea(),light=light,
                    seaEvolution=c.seaEvolution,lightingPhases=new[]{new DatasetLightingPhase{startFrame=0,endFrame=c.SimulationFrames,timeOfDay=block.environment.timeOfDay,light=light}},
                    manual=new DatasetManualImageMetadata{campaignId=id,campaignSha256=sha,blockId=block.id,blockName=block.name,imageInBlock=image,imageInCampaign=index,
                        environment=block.environment,placements=placements.ToArray()}};
                bundle.planJson=JsonUtility.ToJson(plan,true);bundle.campaignJson=json;bundle.contentSha256=bundle.ComputeHash();c.Validate();c.MakePlan();
                return new Job{config=c,bundle=bundle,yaml=DatasetLotusimScenario.Yaml(c,plan)};
            }catch{Object.DestroyImmediate(c);Object.DestroyImmediate(bundle);throw;}
        }
        static void CreateScene(string path,DatasetManualCampaignAsset campaign)
        {
            var prior=SceneManager.GetActiveScene();var source=SceneManager.GetSceneByPath(DatasetLotusimSceneBuilder.ScenePath);bool opened=!source.IsValid()||!source.isLoaded;Scene destination=default(Scene);
            if(opened)source=EditorSceneManager.OpenScene(DatasetLotusimSceneBuilder.ScenePath,OpenSceneMode.Additive);
            try {
                if(source.isDirty)throw new InvalidOperationException("Save the connected source scene before importing a campaign.");
                if(!EditorSceneManager.SaveScene(source,path,true))throw new IOException("Cannot copy the connected scene.");
                destination=EditorSceneManager.OpenScene(path,OpenSceneMode.Additive);
                var runner=destination.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<DatasetSequenceRunner>(true)).Single();
                runner.configuration=campaign.jobs[0];runner.autoStart=false;runner.enabled=false;runner.lotusimSource.enabled=false;
                var batch=runner.gameObject.AddComponent<DatasetManualCampaignRunner>();batch.campaign=campaign;batch.template=runner;
                if(!EditorSceneManager.SaveScene(destination))throw new IOException("Cannot save manual campaign bindings.");
            }finally {if(destination.IsValid()&&destination.isLoaded)EditorSceneManager.CloseScene(destination,true);if(opened)EditorSceneManager.CloseScene(source,true);if(prior.IsValid()&&prior.isLoaded)SceneManager.SetActiveScene(prior);}
        }
        static bool SafeId(string s)=>!string.IsNullOrEmpty(s)&&s.Length<=100&&s.All(ch=>char.IsLetterOrDigit(ch)||ch=='_'||ch=='-');
        static bool Range(float v,float a,float b)=>DatasetManualEnvironment.Range(v,a,b);
        static void EnsureFolder(string path) {if(AssetDatabase.IsValidFolder(path))return;int split=path.LastIndexOf('/');EnsureFolder(path.Substring(0,split));AssetDatabase.CreateFolder(path.Substring(0,split),path.Substring(split+1));}
    }
}
