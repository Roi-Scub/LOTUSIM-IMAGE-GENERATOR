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
    public static class DatasetPilotSceneBuilder
    {
        public const string PilotScene="Assets/Scenes/Dataset/BuoyDatasetPilot.unity";
        public const string SmokeScene="Assets/Scenes/Dataset/BuoyDatasetSmoke.unity";
        public const string WaveScene="Assets/Scenes/Dataset/BuoyDatasetWaves.unity";
        const string SourceScene="Assets/Scenes/Defense/defenseScenario.unity";
        static bool attempted;
        static DatasetPilotSceneBuilder() {EditorApplication.update+=EnsureScene;}

        static void EnsureScene()
        {
            if(attempted||EditorApplication.isCompiling||EditorApplication.isUpdating||EditorApplication.isPlayingOrWillChangePlaymode) return;
            if(AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/buoy.prefab")==null) return;
            attempted=true;EditorApplication.update-=EnsureScene;
            if(File.Exists(PilotScene)&&File.Exists(SmokeScene)) return;
            try {CreateScenes();} catch(Exception exception) {Debug.LogException(exception);}
        }

        [MenuItem("LOTUSim/Dataset/1 - Create pilot scenes")]
        public static void CreateScenes()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Exit Play before creating the dataset scenes.");
            Folder("Assets/Dataset");Folder("Assets/Scenes/Dataset");
            var config=AssetDatabase.LoadAssetAtPath<DatasetCampaignConfig>("Assets/Dataset/BuoyPilot.asset");
            if(config==null) {
                config=ScriptableObject.CreateInstance<DatasetCampaignConfig>();
                config.localPreviewPrefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/buoy.prefab");
                AssetDatabase.CreateAsset(config,"Assets/Dataset/BuoyPilot.asset");
            }
            var smoke=AssetDatabase.LoadAssetAtPath<DatasetCampaignConfig>("Assets/Dataset/BuoySmoke.asset");
            if(smoke==null) {
                smoke=Object.Instantiate(config);smoke.objectSource=DatasetObjectSource.LocalPreview;smoke.launchScenario=false;
                smoke.cameraMotion.enabled=false;
                smoke.distancesM=new[]{10f};smoke.azimuthsDeg=new[]{0f};smoke.elevationsDeg=new[]{5f};
                smoke.seas=new[]{config.seas[0]};smoke.lights=new[]{config.lights[0]};smoke.samplesPerCondition=1;
                smoke.settleRenderedFrames=30;smoke.outputRoot="artifacts/dataset-smoke";
                AssetDatabase.CreateAsset(smoke,"Assets/Dataset/BuoySmoke.asset");
            }
            config.Validate();smoke.Validate();
            if(!File.Exists(PilotScene)) BuildScene(PilotScene,config);
            if(!File.Exists(SmokeScene)) BuildScene(SmokeScene,smoke);
            AssetDatabase.SaveAssets();
            Debug.Log("[Dataset] Scenes ready. Pilot: "+config.ConditionCount()+" conditions, "+config.ImageCount()+" images. Smoke: 1 image, no ROS.");
        }

        static void BuildScene(string path,DatasetCampaignConfig config)
        {
            Scene previous=SceneManager.GetActiveScene(),source=default(Scene),destination=default(Scene);
            bool openedSource=false;
            try {
                source=SceneManager.GetSceneByPath(SourceScene);
                if(!source.IsValid()||!source.isLoaded) {source=EditorSceneManager.OpenScene(SourceScene,OpenSceneMode.Additive);openedSource=true;}
                var sourceEnvironment=source.GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).FirstOrDefault(t=>t.name=="Environment");
                if(sourceEnvironment==null) throw new InvalidOperationException("Environment not found in the original defense scene.");
                destination=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Additive);SceneManager.SetActiveScene(destination);
                var environment=new GameObject("DatasetEnvironment");
                string[] include={"Sun","Ocean","Sky and Fog Volume","Seabed","Hostages_Island","Underwater Area"};
                foreach(Transform child in sourceEnvironment) if(include.Contains(child.name)) {
                    var clone=Object.Instantiate(child.gameObject);clone.name=child.name;clone.transform.SetParent(environment.transform,true);
                    clone.transform.SetPositionAndRotation(child.position,child.rotation);clone.transform.localScale=child.lossyScale;
                    RemoveInteractiveComponents(clone);
                }
                var ocean=environment.GetComponentInChildren<WaterSurface>();
                var sun=environment.GetComponentsInChildren<Light>().FirstOrDefault(l=>l.type==LightType.Directional);
                var volume=environment.GetComponentsInChildren<Volume>().FirstOrDefault(v=>v.isGlobal&&v.sharedProfile!=null);
                var hdrp=AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>("Assets/Settings/HDRP High Fidelity.asset");
                if(ocean==null||sun==null||volume==null||hdrp==null) throw new InvalidOperationException("Required ocean, sun, sky volume or HDRP water asset is missing.");
                RenderSettings.sun=sun;RenderSettings.ambientMode=AmbientMode.Skybox;
                var cameraObject=new GameObject("DatasetCamera");var camera=cameraObject.AddComponent<Camera>();
                cameraObject.tag="MainCamera";cameraObject.AddComponent<HDAdditionalCameraData>();
                var rosRoot=new GameObject("DatasetROS");
                rosRoot.AddComponent<ROSConnectionConfigurator>();
                var connector=rosRoot.AddComponent<LotusimInterface>();var serialized=new SerializedObject(connector);
                serialized.FindProperty("m_namespace").stringValue=config.rosNamespace;
                serialized.FindProperty("selectedInterfaceType").stringValue="ROS2";serialized.ApplyModifiedPropertiesWithoutUndo();
                rosRoot.SetActive(config.objectSource==DatasetObjectSource.Lotusim);
                var runnerObject=new GameObject("DatasetPilot_Generated_v1");var runner=runnerObject.AddComponent<DatasetCampaignRunner>();
                runner.configuration=config;runner.captureCamera=camera;runner.ocean=ocean;runner.sun=sun;
                runner.environmentVolume=volume;runner.waterPipeline=hdrp;runner.rosRoot=rosRoot;
                if(destination.GetRootGameObjects().SelectMany(g=>g.GetComponentsInChildren<Camera>()).Count()!=1)
                    throw new InvalidOperationException("Dataset scene must contain exactly one camera.");
                if(!EditorSceneManager.SaveScene(destination,path)) throw new IOException("Could not save dataset scene: "+path);
                Directory.CreateDirectory("artifacts/dataset-pilot");
                File.WriteAllText("artifacts/dataset-pilot/scene-validation-"+config.objectSource+".json",
                    "{\"scene\":\""+path+"\",\"conditions\":"+config.ConditionCount()+",\"images\":"+config.ImageCount()+",\"cameras\":1,\"launcher\":false,\"leap\":false,\"annotations\":"+(config.annotations.enabled?"true":"false")+"}");
            }
            finally {
                if(previous.IsValid()&&previous.isLoaded) SceneManager.SetActiveScene(previous);
                if(destination.IsValid()) EditorSceneManager.CloseScene(destination,true);
                if(openedSource&&source.IsValid()) EditorSceneManager.CloseScene(source,true);
            }
        }

        static void RemoveInteractiveComponents(GameObject root)
        {
            foreach(var camera in root.GetComponentsInChildren<Camera>(true)) Object.DestroyImmediate(camera.gameObject);
            foreach(var audio in root.GetComponentsInChildren<AudioListener>(true)) Object.DestroyImmediate(audio);
            foreach(var behaviour in root.GetComponentsInChildren<MonoBehaviour>(true)) {
                if(behaviour==null) continue;
                string ns=behaviour.GetType().Namespace??"";
                if(behaviour is Volume||ns.StartsWith("UnityEngine.Rendering",StringComparison.Ordinal)) continue;
                Object.DestroyImmediate(behaviour);
            }
            foreach(var transform in root.GetComponentsInChildren<Transform>(true)) GameObjectUtility.RemoveMonoBehavioursWithMissingScript(transform.gameObject);
        }

        static void Folder(string path)
        {
            if(AssetDatabase.IsValidFolder(path)) return;
            string parent=Path.GetDirectoryName(path).Replace('\\','/');Folder(parent);AssetDatabase.CreateFolder(parent,Path.GetFileName(path));
        }

        [MenuItem("LOTUSim/Dataset/2 - Open one-image smoke test (no ROS)")]
        public static void OpenSmoke() => Open(SmokeScene);
        [MenuItem("LOTUSim/Dataset/3 - Open 432-image LOTUSim pilot")]
        public static void OpenPilot() => Open(PilotScene);
        [MenuItem("LOTUSim/Dataset/5 - Open floating buoy wave test (no ROS)")]
        public static void OpenWaves()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) {EditorUtility.DisplayDialog("Dataset","Quitte le mode Play avant d’ouvrir le test des vagues.","OK");return;}
            CreateWavePreview();Open(WaveScene);
        }

        public static void CreateWavePreview()
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) throw new InvalidOperationException("Exit Play before creating the wave preview.");
            CreateScenes();
            var waves=AssetDatabase.LoadAssetAtPath<DatasetCampaignConfig>("Assets/Dataset/BuoyWaves.asset");
            if(waves==null) {
                // Independent settings, not shared with or written into the pilot.
                waves=ScriptableObject.CreateInstance<DatasetCampaignConfig>();
                waves.objectSource=DatasetObjectSource.LocalPreview;waves.launchScenario=false;
                waves.cameraMotion.enabled=false;
                waves.localPreviewPrefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/buoy.prefab");
                waves.distancesM=new[]{6f};waves.azimuthsDeg=new[]{0f};waves.elevationsDeg=new[]{12f};
                waves.lights=new[]{waves.lights[0]};waves.samplesPerCondition=4;
                waves.sampleIntervalSeconds=1;waves.settleRenderedFrames=60;
                waves.outputRoot="artifacts/dataset-waves";
                AssetDatabase.CreateAsset(waves,"Assets/Dataset/BuoyWaves.asset");
            }
            waves.Validate();
            if(!File.Exists(WaveScene)) BuildScene(WaveScene,waves);
            AssetDatabase.SaveAssets();
            Debug.Log("[Dataset] Wave preview ready: "+waves.ImageCount()+" images, calm/moderate/rough, visual flotation, no ROS.");
        }
        static void Open(string path)
        {
            if(EditorApplication.isPlayingOrWillChangePlaymode) {EditorUtility.DisplayDialog("Dataset","Quitte le mode Play avant d’ouvrir la scène de génération.","OK");return;}
            CreateScenes();if(!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            EditorSceneManager.OpenScene(path,OpenSceneMode.Single);DatasetCampaignMonitor.ShowWindow();
        }
    }

    public sealed class DatasetCampaignMonitor : EditorWindow
    {
        [MenuItem("LOTUSim/Dataset/4 - Campaign monitor")]
        public static void ShowWindow() {GetWindow<DatasetCampaignMonitor>("Dataset — suivi");}
        void OnInspectorUpdate() {Repaint();}
        void OnGUI()
        {
            var sequence=Object.FindObjectOfType<DatasetSequenceRunner>();
            if(sequence!=null) {DrawSequence(sequence);return;}
            var runner=Object.FindObjectOfType<DatasetCampaignRunner>();
            if(runner==null) {GUILayout.Label("Ouvre une scène Dataset avec le menu LOTUSim → Dataset.");return;}
            GUILayout.Label("État : "+runner.Status,EditorStyles.boldLabel);
            GUILayout.Label("Images : "+runner.Captured+" / "+runner.Expected);
            GUILayout.Label("Images annotées : "+runner.AnnotatedFrames+" · boîtes : "+runner.AnnotationBoxes);
            if(runner.Status=="complete_cleanup_unconfirmed")
                EditorGUILayout.HelpBox("Toutes les captures sont enregistrées. L’arrêt du scénario reste à vérifier avant de relancer.",MessageType.Warning);
            GUILayout.Label("Le suivi est dans l’éditeur, jamais dans les PNG.",EditorStyles.wordWrappedLabel);
            if(runner.Preview!=null) {
                Rect rect=GUILayoutUtility.GetAspectRect((float)runner.Preview.width/runner.Preview.height);
                GUI.DrawTexture(rect,runner.Preview,ScaleMode.ScaleToFit,false);
            }
            if(!string.IsNullOrEmpty(runner.OutputDirectory)) {
                EditorGUILayout.SelectableLabel(runner.OutputDirectory,EditorStyles.wordWrappedLabel,GUILayout.Height(46));
                if(GUILayout.Button("Afficher le dossier de sortie")) EditorUtility.RevealInFinder(runner.OutputDirectory);
                string gallery=Path.Combine(runner.OutputDirectory,"index.html");
                if(File.Exists(gallery)&&GUILayout.Button("Ouvrir la galerie")) EditorUtility.OpenWithDefaultApp(gallery);
            }
        }
        static void DrawSequence(DatasetSequenceRunner runner)
        {
            GUILayout.Label("Séquence aléatoire · état : "+runner.Status,EditorStyles.boldLabel);
            GUILayout.Label("Images : "+runner.Captured+" / "+runner.Expected+" · annotations : "+runner.Boxes);
            GUILayout.Label(runner.lotusimSource==null?"Caméra mobile, trajectoires Unity, sans ROS. Le suivi n'est pas dans les PNG.":
                "Caméra et objets pilotés par LOTUSim · ROS TCP unique · captures synchronisées pas à pas.",EditorStyles.wordWrappedLabel);
            if(runner.Status=="complete_cleanup_unconfirmed") EditorGUILayout.HelpBox("Images terminées ; arrêt du scénario non confirmé. Vérifie LOTUSim avant de relancer.",MessageType.Warning);
            if(runner.Preview!=null) {Rect rect=GUILayoutUtility.GetAspectRect((float)runner.Preview.width/runner.Preview.height);GUI.DrawTexture(rect,runner.Preview,ScaleMode.ScaleToFit,false);}
            if(!string.IsNullOrEmpty(runner.OutputDirectory)) {
                EditorGUILayout.SelectableLabel(runner.OutputDirectory,EditorStyles.wordWrappedLabel,GUILayout.Height(46));
                if(GUILayout.Button("Afficher le dossier de sortie")) EditorUtility.RevealInFinder(runner.OutputDirectory);
                string gallery=Path.Combine(runner.OutputDirectory,"index.html");if(File.Exists(gallery)&&GUILayout.Button("Ouvrir la galerie")) EditorUtility.OpenWithDefaultApp(gallery);
                DatasetRgbObserverTools.Draw(runner.OutputDirectory);
            }
        }
    }
}
