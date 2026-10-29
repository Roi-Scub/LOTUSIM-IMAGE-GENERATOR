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

namespace Lotusim.EditorTools
{
    public static partial class MarineLibraryBuilder
    {
        public const string ShowcaseScene = "Assets/Scenes/Models/MarineLibrary.unity";
        [MenuItem("LOTUSim/Models/Open marine library — waves and physics")]
        public static void OpenShowcase()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play before opening the marine library.");
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;
            CreateShowcase();
            EditorSceneManager.OpenScene(ShowcaseScene, OpenSceneMode.Single);
        }

        [MenuItem("LOTUSim/Models/Add marine categories to connected dataset (count 0)")]
        public static void AddMarineCategories()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play before editing dataset categories.");
            var config = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if (config == null)
                throw new InvalidOperationException("Open Dataset menu 7 first.");
            var classes = config.classes.ToList();
            for (int i = 0; i < MarineVesselCatalog.Models.Length; i++)
            {
                string name = MarineVesselCatalog.Models[i];
                if (classes.Any(c => c.category == name))
                    continue;
                if (classes.Any(c => c.classId == i + 6))
                    throw new InvalidOperationException("Class ID already used: " + (i + 6) + ". No categories were changed.");
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + name + ".prefab");
                if (prefab == null)
                    throw new FileNotFoundException("Build/import marine library first: " + name);
                float[] near =
                {
                    240,
                    650,
                    140,
                    110,
                    110,
                    450,
                    150
                }, far =
                {
                    350,
                    950,
                    240,
                    200,
                    180,
                    750,
                    260
                };
                classes.Add(new DatasetEncounterClass { category = name, displayName = MarineVesselCatalog.DisplayNames[i], classId = i + 6, count = 0, prefab = prefab, moored = true, distanceM = new Vector2(near[i], far[i]), altitudeM = Vector2.zero, speedMps = Vector2.zero, separationM = Mathf.Max(5, MarineVesselCatalog.Parameters(i).lengthM * .55f) });
            }

            Undo.RecordObject(config, "Add inactive marine dataset categories");
            config.classes = classes.ToArray();
            config.Validate();
            EditorUtility.SetDirty(config);
            AssetDatabase.SaveAssets();
            Debug.Log("[Marine Library] Marine classes added with count=0; existing encounters unchanged. Enable chosen counts, then export with Dataset menu 8. Moored boats still react to waves.");
        }

        public static void CreateShowcase()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play before creating the marine showcase.");
            if (File.Exists(ShowcaseScene))
                return;
            Folder("Assets/Scenes/Models");
            var previous = SceneManager.GetActiveScene();
            bool emptyUntitled = string.IsNullOrEmpty(previous.path) && !previous.isDirty && previous.rootCount == 0;
            if (string.IsNullOrEmpty(previous.path) && !emptyUntitled)
                throw new InvalidOperationException("Enregistre la scène courante avant de créer la bibliothèque marine.");
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, emptyUntitled ? NewSceneMode.Single : NewSceneMode.Additive);
            try
            {
                SceneManager.SetActiveScene(scene);
                var host = new GameObject("Marine library showcase (no ROS)").AddComponent<MarineLibraryShowcase>();
                host.prefabs = Array.ConvertAll(MarineVesselCatalog.Models, n => AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + n + ".prefab"));
                if (Array.Exists(host.prefabs, p => p == null))
                    throw new InvalidOperationException("Build or import all seven marine prefabs first.");
                host.ocean = new GameObject("Ocean").AddComponent<WaterSurface>();
                host.ocean.cpuSimulation = true;
                host.ocean.cpuFullResolution = true;
                host.sun = new GameObject("Sun").AddComponent<Light>();
                host.sun.type = LightType.Directional;
                host.viewCamera = new GameObject("Marine inspection camera").AddComponent<Camera>();
                host.viewCamera.gameObject.tag = "MainCamera";
                host.viewCamera.gameObject.AddComponent<HDAdditionalCameraData>();
                host.environment = new GameObject("Sky and fog").AddComponent<Volume>();
                host.environment.isGlobal = true;
                host.environment.priority = 1000;
                host.environment.sharedProfile = AssetDatabase.LoadAssetAtPath<VolumeProfile>("Assets/Settings/SkyandFogSettingsProfile.asset");
                host.waterPipeline = AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>("Assets/Settings/HDRP High Fidelity.asset");
                if (host.waterPipeline == null || host.environment.sharedProfile == null)
                    throw new InvalidOperationException("HDRP water asset or sky profile missing.");
                RenderSettings.sun = host.sun;
                if (!EditorSceneManager.SaveScene(scene, ShowcaseScene))
                    throw new IOException("Cannot save marine showcase.");
                AssetDatabase.SaveAssets();
            }
            finally
            {
                if (previous.IsValid() && previous.isLoaded)
                    SceneManager.SetActiveScene(previous);
                if (SceneManager.sceneCount > 1)
                    EditorSceneManager.CloseScene(scene, true);
            }

            Debug.Log("[Marine Library] Standalone wave/physics inspection scene ready: " + ShowcaseScene);
        }
    }
}
