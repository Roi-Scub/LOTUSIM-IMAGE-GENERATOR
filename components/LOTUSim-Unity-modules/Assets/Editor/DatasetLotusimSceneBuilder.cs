using System;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static partial class DatasetLotusimSceneBuilder
    {
        public const string ScenePath="Assets/Scenes/Dataset/MaritimeRandomLotusim.unity";
        public const string ConfigPath="Assets/Dataset/MaritimeRandomLotusim.asset";
        public const string ObserverPath="Assets/Prefabs/DatasetObserverFremm.prefab";
        [MenuItem("LOTUSim/Dataset/7 - Open multi-object sequence connected to LOTUSim")]
        public static void Open()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) {EditorUtility.DisplayDialog("Dataset","Quitte Play avant d’ouvrir le mode LOTUSim.","OK");return;}
            if(!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            Create();ExportScenario();EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Single);DatasetCampaignMonitor.ShowWindow();
        }
        public static void Create()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Exit Play before creating the connected scene.");
            if(!File.Exists(DatasetSequenceSceneBuilder.ScenePath)) DatasetSequenceSceneBuilder.Create();
            var config=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(ConfigPath);
            if(config==null) {
                config=Object.Instantiate(AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetSequenceSceneBuilder.ConfigPath));
                config.outputRoot="artifacts/dataset-lotusim";AssetDatabase.CreateAsset(config,ConfigPath);
            }
            if(config.connectedLightingVersion<1) ConfigureLighting(config);
            if(config.connectedVoyageVersion<1) ConfigureVoyage(config);
            if(config.connectedSensorsVersion<1) ConfigureSensors(config);
            if(config.connectedBridgeVersion<1) ConfigureBridge(config);
            config.Validate();var observer=CreateObserver();
            if(File.Exists(ScenePath)) {UpgradeObserver(config,observer);return;}
            ConfigureFremm(config);
            Scene previous=SceneManager.GetActiveScene(),source=default(Scene),scene=default(Scene);bool opened=false;
            try {
                source=SceneManager.GetSceneByPath(DatasetSequenceSceneBuilder.ScenePath);
                if(!source.IsValid()||!source.isLoaded) {source=EditorSceneManager.OpenScene(DatasetSequenceSceneBuilder.ScenePath,OpenSceneMode.Additive);opened=true;}
                var original=source.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<DatasetSequenceRunner>()).Single();
                scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);SceneManager.SetActiveScene(scene);
                var environment=Object.Instantiate(original.ocean.transform.root.gameObject);environment.name="LotusimDatasetEnvironment";
                var camera=Object.Instantiate(original.captureCamera);camera.name="LotusimObserverCamera";
                var host=new GameObject("MaritimeRandomLotusim");var sourceComponent=host.AddComponent<DatasetLotusimSource>();sourceComponent.observerPrefab=observer;sourceComponent.observerSetupVersion=2;
                var runner=host.AddComponent<DatasetSequenceRunner>();runner.lotusimSource=sourceComponent;runner.configuration=config;runner.captureCamera=camera;
                runner.ocean=environment.GetComponentInChildren<UnityEngine.Rendering.HighDefinition.WaterSurface>();
                runner.sun=environment.GetComponentsInChildren<Light>().First(l=>l.type==LightType.Directional);
                runner.environmentVolume=environment.GetComponentsInChildren<Volume>().First(v=>v.isGlobal&&v.sharedProfile!=null);runner.waterPipeline=original.waterPipeline;
                RenderSettings.sun=runner.sun;
                if(scene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Camera>()).Count()!=1) throw new InvalidOperationException("Connected dataset requires exactly one camera.");
                if(!EditorSceneManager.SaveScene(scene,ScenePath)) throw new IOException("Cannot save connected dataset scene.");AssetDatabase.SaveAssets();
            }
            finally {if(previous.IsValid()&&previous.isLoaded) SceneManager.SetActiveScene(previous);if(scene.IsValid()) EditorSceneManager.CloseScene(scene,true);if(opened&&source.IsValid()) EditorSceneManager.CloseScene(source,true);}
        }
        [MenuItem("LOTUSim/Dataset/8 - Export connected configuration to LOTUSim YAML")]
        public static void ExportScenario()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Exit Play before exporting the LOTUSim YAML.");
            var config=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(ConfigPath);
            if(config==null) throw new InvalidOperationException("Open Dataset menu 7 first.");
            string root=Path.GetFullPath(Path.Combine(Application.dataPath,"..","..","LOTUSim"));
            string folder=Path.Combine(root,"assets","scenarios");
            if(!Directory.Exists(folder)) throw new DirectoryNotFoundException("Expected the LOTUSim repository beside the Unity project: "+folder);
            string file=Path.Combine(folder,"MaritimeRandomLotusim.yaml");
            if(File.Exists(file)&&!File.ReadAllText(file).StartsWith("# Generated by LOTUSim Unity Dataset",StringComparison.Ordinal))
                throw new IOException("Refusing to overwrite a manually authored scenario: "+file);
            string yaml=DatasetLotusimScenario.Yaml(config,config.MakePlan());
            DatasetSequenceExport.Atomic(file,yaml);AssetDatabase.SaveAssets();
            Debug.Log("[LOTUSim Dataset] Exported "+config.ImageCount+" images / "+config.SimulationFrames+" source steps: "+file);
        }
        static GameObject CreateObserver()
        {
            var existing=AssetDatabase.LoadAssetAtPath<GameObject>(ObserverPath);if(existing!=null) return EnsureDeckObserver(existing);
            var model=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/models/boat/fremm.dae");
            if(model==null) throw new FileNotFoundException("The real FREMM model is required: Assets/models/boat/fremm.dae");
            if(!AssetDatabase.IsValidFolder("Assets/Dataset/FremmObserverMaterials")) AssetDatabase.CreateFolder("Assets/Dataset","FremmObserverMaterials");
            var root=new GameObject("DatasetObserverFremm");
            try {
                var visual=(GameObject)PrefabUtility.InstantiatePrefab(model);visual.name="FREMM";visual.transform.SetParent(root.transform,false);
                // Imported FREMM bow is local -Z. Dataset poses use local +X.
                visual.transform.localRotation=Quaternion.Euler(0,-90,0);
                foreach(var camera in visual.GetComponentsInChildren<Camera>(true)) Object.DestroyImmediate(camera);
                foreach(var light in visual.GetComponentsInChildren<Light>(true)) Object.DestroyImmediate(light);
                foreach(var collider in visual.GetComponentsInChildren<Collider>(true)) Object.DestroyImmediate(collider);
                foreach(var renderer in visual.GetComponentsInChildren<MeshRenderer>(true))
                    renderer.sharedMaterials=renderer.sharedMaterials.Select(FremmMaterial).ToArray();
                var renderers=visual.GetComponentsInChildren<MeshRenderer>(true);
                if(renderers.Length==0) throw new InvalidOperationException("FREMM mesh has no renderers.");
                var bounds=renderers[0].bounds;foreach(var r in renderers.Skip(1)) bounds.Encapsulate(r.bounds);
                if(bounds.size.x<130||bounds.size.x>160||bounds.max.y>43) throw new InvalidOperationException("Unexpected FREMM import axes/scale: "+bounds);
                return EnsureDeckObserver(PrefabUtility.SaveAsPrefabAsset(root,ObserverPath));
            }
            finally {Object.DestroyImmediate(root);}
        }
        static Material FremmMaterial(Material original)
        {
            string name=original==null?"Hull":original.name;
            name=new string(name.Select(c=>char.IsLetterOrDigit(c)||c=='_'?c:'_').ToArray());
            string path="Assets/Dataset/FremmObserverMaterials/"+name+".mat";
            var material=AssetDatabase.LoadAssetAtPath<Material>(path);if(material!=null) return material;
            var shader=Shader.Find("HDRP/Lit");if(shader==null) throw new InvalidOperationException("HDRP/Lit is required for FREMM.");
            material=new Material(shader){name="FREMM "+name};
            Color color=original!=null&&original.HasProperty("_Color")?original.GetColor("_Color"):new Color(.5f,.54f,.56f);
            material.SetColor("_BaseColor",new Color(color.r,color.g,color.b,1));material.SetFloat("_Smoothness",.3f);
            if(original!=null&&original.HasProperty("_MainTex")&&original.GetTexture("_MainTex")!=null)
                material.SetTexture("_BaseColorMap",original.GetTexture("_MainTex"));
            AssetDatabase.CreateAsset(material,path);return material;
        }
        public static void ConfigureFremm(DatasetSequenceConfig config)
        {
            if(config.observerDeckCamera) {config.observerHullHalfExtentsM=new Vector3(15,43,78);return;}
            // Above the imported mast (41.62 m), with 3.38 m clearance. Targets
            // must be farther away to remain in-frame from this elevated view.
            config.observerHeightM=45;config.observerHullHalfExtentsM=new Vector3(15,43,78);
            foreach(var c in config.classes) {
                float min=c.category=="buoy"?120:c.category=="drone"?80:c.category=="bird"?100:0;
                float max=c.category=="buoy"?220:c.category=="drone"?160:c.category=="bird"?200:0;
                if(min>0) c.distanceM=new Vector2(Mathf.Max(c.distanceM.x,min),Mathf.Max(c.distanceM.y,max));
            }
            config.Validate();config.MakePlan();EditorUtility.SetDirty(config);
        }
        public static void ConfigureLighting(DatasetSequenceConfig config)
        {
            // Version zero predates this feature. Replace only its new lighting
            // block, including values retained by Unity during script reloads.
            if(config.connectedLightingVersion<1||config.lighting==null) config.lighting=new DatasetSequenceLightingSettings();
            config.lighting.cycleDayEveningNight=true;config.connectedLightingVersion=1;
            config.Validate();EditorUtility.SetDirty(config);
            Debug.Log("[LOTUSim Dataset] Day / evening / full-moon night enabled in balanced capture blocks. Existing motion, image count and resolution preserved.");
        }
        static void UpgradeObserver(DatasetSequenceConfig config,GameObject observer)
        {
            var scene=SceneManager.GetSceneByPath(ScenePath);bool opened=!scene.IsValid()||!scene.isLoaded;
            if(!opened&&scene.isDirty) throw new InvalidOperationException("Save the connected scene before applying the FREMM observer update.");
            if(opened) scene=EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Additive);
            try {
                var source=scene.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<DatasetLotusimSource>(true)).Single();
                if(source.observerSetupVersion>=2) return;
                ConfigureFremm(config);source.observerPrefab=observer;source.observerSetupVersion=2;
                EditorUtility.SetDirty(source);EditorSceneManager.MarkSceneDirty(scene);
                if(!EditorSceneManager.SaveScene(scene)) throw new IOException("Cannot save FREMM observer update.");
                AssetDatabase.SaveAssets();Debug.Log("[LOTUSim Dataset] FREMM observer configured: camera 45 m above reference, hull keep-out enabled; existing image/timing settings preserved.");
            }
            finally {if(opened) EditorSceneManager.CloseScene(scene,true);}
        }
    }
}
