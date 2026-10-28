using System;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using Object=UnityEngine.Object;

namespace Lotusim.EditorTools
{
    [InitializeOnLoad]
    public static class DatasetSequenceSceneBuilder
    {
        public const string ScenePath="Assets/Scenes/Dataset/MaritimeRandomSequence.unity";
        public const string ConfigPath="Assets/Dataset/MaritimeRandomSequence.asset";
        static readonly string[] Prefabs={"buoy","small_drone","helicopter","airplane","seagull"};
        static bool attempted;
        static DatasetSequenceSceneBuilder() {EditorApplication.update+=Ensure;}
        static void Ensure()
        {
            if(attempted||EditorApplication.isCompiling||EditorApplication.isUpdating||EditorApplication.isPlayingOrWillChangePlaymode) return;
            if(Prefabs.Any(name=>AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+name+".prefab")==null)) return;
            attempted=true;EditorApplication.update-=Ensure;
            if(!File.Exists(ScenePath)) try {Create();} catch(Exception exception) {Debug.LogException(exception);}
        }
        [MenuItem("LOTUSim/Dataset/6 - Open randomized multi-object sequence (no ROS)")]
        public static void Open()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) {EditorUtility.DisplayDialog("Dataset","Quitte Play avant d'ouvrir le randomizer.","OK");return;}
            Create();if(!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.OpenScene(ScenePath,OpenSceneMode.Single);DatasetCampaignMonitor.ShowWindow();
        }
        public static void Create()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Exit Play before creating the randomizer scene.");
            DatasetPilotSceneBuilder.CreateScenes();
            var config=AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(ConfigPath);
            if(config==null) {
                config=ScriptableObject.CreateInstance<DatasetSequenceConfig>();
                for(int i=0;i<Prefabs.Length;i++) config.classes[i].prefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/"+Prefabs[i]+".prefab");
                config.Validate();AssetDatabase.CreateAsset(config,ConfigPath);
            }
            config.Validate();if(File.Exists(ScenePath)) return;
            Scene previous=SceneManager.GetActiveScene(),source=default(Scene),destination=default(Scene);bool opened=false;
            try {
                source=SceneManager.GetSceneByPath(DatasetPilotSceneBuilder.SmokeScene);
                if(!source.IsValid()||!source.isLoaded) {source=EditorSceneManager.OpenScene(DatasetPilotSceneBuilder.SmokeScene,OpenSceneMode.Additive);opened=true;}
                var original=source.GetRootGameObjects().FirstOrDefault(g=>g.name=="DatasetEnvironment");if(original==null) throw new InvalidOperationException("Dataset maritime environment missing.");
                destination=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);SceneManager.SetActiveScene(destination);
                var environment=Object.Instantiate(original);environment.name="SequenceEnvironment";
                var camera=new GameObject("SequenceObserverCamera").AddComponent<Camera>();camera.tag="MainCamera";camera.gameObject.AddComponent<HDAdditionalCameraData>();
                var runner=new GameObject("MaritimeRandomizer_v1").AddComponent<DatasetSequenceRunner>();runner.configuration=config;runner.captureCamera=camera;
                runner.ocean=environment.GetComponentInChildren<WaterSurface>();runner.sun=environment.GetComponentsInChildren<Light>().FirstOrDefault(l=>l.type==LightType.Directional);
                runner.environmentVolume=environment.GetComponentsInChildren<Volume>().FirstOrDefault(v=>v.isGlobal&&v.sharedProfile!=null);
                runner.waterPipeline=AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>("Assets/Settings/HDRP High Fidelity.asset");RenderSettings.sun=runner.sun;
                if(runner.ocean==null||runner.sun==null||runner.environmentVolume==null||runner.waterPipeline==null) throw new InvalidOperationException("Randomizer HDRP environment incomplete.");
                if(destination.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Camera>()).Count()!=1) throw new InvalidOperationException("Randomizer requires exactly one camera.");
                if(!EditorSceneManager.SaveScene(destination,ScenePath)) throw new IOException("Cannot save sequence scene.");AssetDatabase.SaveAssets();
                Debug.Log("[Sequence] Randomizer ready: "+config.ImageCount+" images, no ROS/Launcher/Photon/Leap. Use Dataset menu 6, then Play.");
            }
            finally {if(previous.IsValid()&&previous.isLoaded) SceneManager.SetActiveScene(previous);if(destination.IsValid()) EditorSceneManager.CloseScene(destination,true);if(opened&&source.IsValid()) EditorSceneManager.CloseScene(source,true);}
        }
    }
}
