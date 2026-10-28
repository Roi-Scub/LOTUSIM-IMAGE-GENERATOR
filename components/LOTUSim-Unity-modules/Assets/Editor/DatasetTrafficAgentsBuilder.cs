using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;
using UnityEngine.SceneManagement;
using Debug = UnityEngine.Debug;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    // Editor-side compilation only. No child process, LLM or extra socket runs
    // in the simulation. The verified plan is an immutable runtime asset.
    public static class DatasetTrafficAgentsBuilder
    {
        public const string Name = "MaritimeTrafficAgents", ScenePath = "Assets/Scenes/Dataset/MaritimeTrafficAgents.unity", ConfigPath = "Assets/Dataset/MaritimeTrafficAgents.asset", BundlePath = "Assets/Dataset/MaritimeTrafficAgents.plan.asset";
        public static string CoreRootOverride; // Isolated batch fixtures only.
        public static string CoreRoot => Application.isBatchMode && !string.IsNullOrEmpty(CoreRootOverride) ? Path.GetFullPath(CoreRootOverride) : Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "LOTUSim"));

        [Serializable]
        sealed class Observer
        {
            public float speedKnots, headingDeg, turnDeg;
        }

        [Serializable]
        sealed class Weather
        {
            public float localWindMps, significantSwellHeightM;
            public float[] swellSpectrumProxyWindKmh;
        }

        [Serializable]
        sealed class Scope
        {
            public string schema, name;
            public int seed, fps, captureEveryFrames;
            public float durationSeconds;
            public Observer observer;
            public Weather weather;
            public DatasetTrafficSafetySettings safety;
        }

        [Serializable]
        sealed class Audit
        {
            public bool approved;
            public int actors, pairChecks;
        }

        [InitializeOnLoadMethod]
        static void Register()
        {
            EditorApplication.playModeStateChanged += state =>
            {
                if (state != PlayModeStateChange.ExitingEditMode || SceneManager.GetActiveScene().path != ScenePath)
                    return;
                try
                {
                    Generate(true);
                }
                catch (Exception e)
                {
                    Debug.LogError("[Traffic Agents] Planning failed; Play cancelled, no scenario launched. " + e);
                    EditorApplication.isPlaying = false;
                }
            };
        }

        [MenuItem("LOTUSim/Dataset/Cooperative traffic/1 - Generate and open all-model scenario")]
        public static void Open()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Quit Play first.");
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                return;
            Generate();
            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            DatasetCampaignMonitor.ShowWindow();
        }

        [MenuItem("LOTUSim/Dataset/Cooperative traffic/2 - Regenerate from scope")]
        public static void GenerateMenu() => Generate();
        [MenuItem("LOTUSim/Dataset/Cooperative traffic/3 - Open scope configuration")]
        public static void ScopeFile() => EditorUtility.OpenWithDefaultApp(Path.Combine(CoreRoot, "assets/scenarios/scopes/MaritimeTrafficAgents.json"));
        [MenuItem("LOTUSim/Dataset/Cooperative traffic/4 - Open visibility and recognition thresholds")]
        public static void RecognitionFile() => EditorUtility.OpenWithDefaultApp(Path.Combine(CoreRoot, "assets/perception/recognition_policy.json"));
        public static void Generate(bool enteringPlay = false)
        {
            if (EditorApplication.isPlaying || (!enteringPlay && EditorApplication.isPlayingOrWillChangePlaymode))
                throw new InvalidOperationException("Generate outside Play.");
            string core = CoreRoot, scopeFile = Path.Combine(core, "assets/scenarios/scopes/MaritimeTrafficAgents.json"), catalogueFile = Path.Combine(core, "assets/scenarios/catalogs/traffic_assets.json"), script = Path.Combine(core, "tools/plan_maritime_traffic.py");
            if (!File.Exists(scopeFile) || !File.Exists(catalogueFile) || !File.Exists(script))
                throw new FileNotFoundException("Expected the LOTUSim repository beside Unity, including the traffic scope/catalogue/planner.");
            string scopeJson = File.ReadAllText(scopeFile), catalogueJson = File.ReadAllText(catalogueFile);
            var scope = JsonUtility.FromJson<Scope>(scopeJson);
            if (scope == null || scope.schema != "lotusim-traffic-scope-1" || scope.name != Name || scope.observer == null || scope.weather == null || scope.safety == null || scope.weather.swellSpectrumProxyWindKmh?.Length != 2)
                throw new InvalidDataException("Invalid scope; this dedicated scene requires name MaritimeTrafficAgents.");
            var original = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetLotusimSceneBuilder.ConfigPath);
            if (original == null)
                throw new FileNotFoundException("Create the existing connected scene with Dataset menu 7 first.");
            DatasetFastDroneBuilder.Ensure();
            var working = Object.Instantiate(original);
            var temporaryBundle = ScriptableObject.CreateInstance<DatasetTrafficPlanBundle>();
            try
            {
                working.trafficPlan = null;
                working.captureFrames = Array.Empty<int>();
                working.scenarioName = Name;
                working.seed = scope.seed;
                working.durationSeconds = scope.durationSeconds;
                working.simulationFps = scope.fps;
                working.captureEveryFrames = scope.captureEveryFrames;
                working.observerSpeedMps = scope.observer.speedKnots * 1852 / 3600;
                working.routeHeadingDeg = scope.observer.headingDeg;
                working.observerTurnDeg = scope.observer.turnDeg;
                working.farClipM = 80000;
                working.maxActiveObjects = 40;
                working.outputRoot = "artifacts/dataset-traffic-agents";
                working.renderTimeoutSeconds = Mathf.Max(90, working.renderTimeoutSeconds);
                string recognitionFile = Path.Combine(core, "assets/perception/recognition_policy.json");
                if (File.Exists(recognitionFile))
                {
                    working.annotations.recognition = JsonUtility.FromJson<DatasetRecognitionSettings>(File.ReadAllText(recognitionFile));
                    if (working.annotations.recognition == null)
                        throw new InvalidDataException("Invalid recognition policy");
                    working.annotations.recognition.Validate();
                }

                working.seaEvolution = new DatasetSeaEvolution
                {
                    enabled = true,
                    periodSeconds = 36,
                    minWindKmh = scope.weather.swellSpectrumProxyWindKmh[0],
                    maxWindKmh = scope.weather.swellSpectrumProxyWindKmh[1],
                    minBand = .7f,
                    maxBand = .95f,
                    patchSizeM = 512,
                    directionDeg = 35
                };
                string output = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "artifacts", "traffic-agents"));
                Directory.CreateDirectory(output);
                string template = Path.Combine(output, "unity-template.json");
                DatasetSequenceExport.Atomic(template, JsonUtility.ToJson(working, true));
                RunPython(script, scopeFile, catalogueFile, template, output);
                var audit = JsonUtility.FromJson<Audit>(File.ReadAllText(Path.Combine(output, "safety-report.json")));
                var plan = JsonUtility.FromJson<DatasetSequencePlan>(File.ReadAllText(Path.Combine(output, "plan.json")));
                if (audit == null || !audit.approved || plan?.traffic == null || plan.events == null || audit.actors != plan.events.Length || audit.pairChecks != (audit.actors + 1) * audit.actors / 2)
                    throw new InvalidDataException("Planner did not produce a complete approved safety audit.");
                working.captureFrames = plan.captureFrames ?? Array.Empty<int>();
                // Resolve every appearance by its own model key, not one random
                // appearance per class. Defaults/IDs remain the existing ones.
                foreach (var c in working.classes)
                {
                    var selected = plan.events.Where(e => e.category == c.category).ToArray();
                    c.count = selected.Length;
                    var added = selected.Select(e => AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + e.modelName + ".prefab")).ToArray();
                    if (added.Any(p => p == null))
                        throw new FileNotFoundException("A scoped appearance has no Unity prefab: " + c.category);
                    c.prefabVariants = (c.prefabVariants ?? Array.Empty<GameObject>()).Concat(added).Where(p => p != c.prefab).Distinct().ToArray();
                    if (selected.Length > 0)
                    {
                        c.distanceM = new Vector2(50, 60000);
                        c.altitudeM = new Vector2(selected.Min(e => e.altitudeM), selected.Max(e => e.altitudeM));
                        c.speedMps = new Vector2(selected.Min(e => e.velocity.magnitude), selected.Max(e => e.velocity.magnitude));
                    }
                }

                plan.seaEvolution = working.seaEvolution;
                plan.sea = working.seaEvolution.Evaluate(0, working.seed);
                plan.sea.name = "remote_groundswell_spectrum_proxy";
                plan.lightingPhases = working.lighting != null && working.lighting.cycleDayEveningNight ? working.lighting.Build(working.SimulationFrames, working.captureEveryFrames) : null;
                plan.light = plan.lightingPhases == null ? working.lighting.day : plan.lightingPhases[0].light;
                temporaryBundle.planJson = JsonUtility.ToJson(plan, true);
                temporaryBundle.scopeJson = scopeJson;
                temporaryBundle.catalogueJson = catalogueJson;
                temporaryBundle.auditJson = File.ReadAllText(Path.Combine(output, "safety-report.json"));
                temporaryBundle.messagesJson = File.ReadAllText(Path.Combine(output, "agent-messages.json"));
                temporaryBundle.safety = scope.safety;
                temporaryBundle.contentSha256 = temporaryBundle.ComputeHash();
                working.trafficPlan = temporaryBundle;
                working.Validate();
                working.MakePlan();
                string yaml = DatasetLotusimScenario.Yaml(working, plan);
                string target = Path.Combine(core, "assets/scenarios/MaritimeTrafficAgents.yaml");
                if (File.Exists(target) && !File.ReadAllText(target).StartsWith("# Generated by LOTUSim Unity Dataset", StringComparison.Ordinal))
                    throw new IOException("Refusing to overwrite a manual scenario: " + target);
                MarineOpenBoatsBuilder.Folder("Assets/Dataset");
                var savedBundle = AssetDatabase.LoadAssetAtPath<DatasetTrafficPlanBundle>(BundlePath);
                if (savedBundle == null)
                {
                    savedBundle = Object.Instantiate(temporaryBundle);
                    AssetDatabase.CreateAsset(savedBundle, BundlePath);
                }
                else
                {
                    EditorUtility.CopySerialized(temporaryBundle, savedBundle);
                    EditorUtility.SetDirty(savedBundle);
                }

                working.trafficPlan = savedBundle;
                var config = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(ConfigPath);
                if (config == null)
                {
                    config = Object.Instantiate(working);
                    AssetDatabase.CreateAsset(config, ConfigPath);
                }
                else
                {
                    EditorUtility.CopySerialized(working, config);
                    EditorUtility.SetDirty(config);
                }

                DatasetSequenceExport.Atomic(target, yaml);
                DatasetSequenceExport.Atomic(Path.Combine(output, "MaritimeTrafficAgents.yaml"), yaml);
                DatasetSequenceExport.Atomic(Path.Combine(output, "unity-plan.json"), temporaryBundle.planJson);
                AssetDatabase.SaveAssets();
                EnsureScene(config);
                Debug.Log("[Traffic Agents] APPROVED: " + audit.actors + " appearances + FREMM, " + audit.pairChecks + " continuously checked pairs; " + config.ImageCount + " capture instants. One ROS connection. Scope: " + scopeFile);
            }
            finally
            {
                Object.DestroyImmediate(temporaryBundle);
                Object.DestroyImmediate(working);
            }
        }

        static string Quote(string value) => "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        static void RunPython(string script, string scope, string catalogue, string template, string output)
        {
            string python = Application.platform == RuntimePlatform.WindowsEditor ? "python" : "/usr/bin/python3";
            var info = new ProcessStartInfo
            {
                FileName = python,
                Arguments = "-I " + Quote(script) + " --scope " + Quote(scope) + " --catalogue " + Quote(catalogue) + " --template " + Quote(template) + " --output " + Quote(output),
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            using (var child = Process.Start(info))
            {
                var stdout = child.StandardOutput.ReadToEndAsync();
                var stderr = child.StandardError.ReadToEndAsync();
                if (!child.WaitForExit(30000))
                {
                    child.Kill();
                    throw new TimeoutException("Traffic planning exceeded 30 seconds; no scenario launched.");
                }

                if (child.ExitCode != 0)
                    throw new InvalidOperationException("Traffic planning refused the scope: " + stderr.Result);
                Debug.Log("[Traffic Agents] " + stdout.Result.Trim());
            }
        }

        static void CreateScene(DatasetSequenceConfig config)
        {
            if (!File.Exists(DatasetLotusimSceneBuilder.ScenePath))
                throw new FileNotFoundException("Original connected scene missing");
            var prior = SceneManager.GetActiveScene();
            var source = SceneManager.GetSceneByPath(DatasetLotusimSceneBuilder.ScenePath);
            bool opened = !source.IsValid() || !source.isLoaded;
            if (opened)
                source = EditorSceneManager.OpenScene(DatasetLotusimSceneBuilder.ScenePath, OpenSceneMode.Additive);
            try
            {
                if (source.isDirty)
                    throw new InvalidOperationException("Save the original connected scene before copying it.");
                // Copy the complete serialized scene graph. Instantiating roots
                // separately leaves the runner pointing into the source scene;
                // Unity then serializes those cross-scene references as null.
                if (!EditorSceneManager.SaveScene(source, ScenePath, true))
                    throw new IOException("Cannot copy connected traffic scene");
            }
            finally
            {
                if (opened)
                    EditorSceneManager.CloseScene(source, true);
                if (prior.IsValid() && prior.isLoaded)
                    SceneManager.SetActiveScene(prior);
            }
        }

        static void EnsureScene(DatasetSequenceConfig config)
        {
            if (!File.Exists(ScenePath))
                CreateScene(config);
            var prior = SceneManager.GetActiveScene();
            var scene = SceneManager.GetSceneByPath(ScenePath);
            bool opened = !scene.IsValid() || !scene.isLoaded;
            if (opened)
                scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Additive);
            bool wasDirty = scene.isDirty;
            try
            {
                if (!BindSceneReferences(scene, config))
                    return;
                // Do not silently save unrelated edits in an already dirty scene.
                if (!wasDirty && !EditorSceneManager.SaveScene(scene))
                    throw new IOException("Cannot save traffic scene references");
                Debug.Log("[Traffic Agents] Scene references repaired and validated locally: camera, ocean, sun, volume and LOTUSim source.");
            }
            finally
            {
                if (opened)
                    EditorSceneManager.CloseScene(scene, true);
                if (prior.IsValid() && prior.isLoaded)
                    SceneManager.SetActiveScene(prior);
            }
        }

        public static bool BindSceneReferences(Scene scene, DatasetSequenceConfig config)
        {
            if (!scene.IsValid() || !scene.isLoaded || config == null)
                throw new InvalidOperationException("Traffic scene and configuration must be loaded before binding.");
            var runners = scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<DatasetSequenceRunner>(true)).ToArray();
            if (runners.Length != 1)
                throw new InvalidOperationException("Traffic scene requires exactly one DatasetSequenceRunner; found " + runners.Length);
            var runner = runners[0];
            // Resolve only within the destination scene, never a global lookup
            // which might accidentally use another loaded scene's camera/ocean.
            var camera = LocalOrSingle(runner.captureCamera, scene, "captureCamera");
            var ocean = LocalOrSingle(runner.ocean, scene, "ocean");
            var sun = LocalOrSingle(runner.sun, scene, "sun", l => l.type == LightType.Directional);
            var volume = LocalOrSingle(runner.environmentVolume, scene, "environmentVolume", v => v.isGlobal && v.sharedProfile != null);
            var source = LocalOrSingle(runner.lotusimSource, scene, "lotusimSource");
            var pipeline = runner.waterPipeline != null ? runner.waterPipeline : AssetDatabase.LoadAssetAtPath<HDRenderPipelineAsset>("Assets/Settings/HDRP High Fidelity.asset");
            if (pipeline == null)
                throw new InvalidOperationException("Traffic scene is missing its HDRP waterPipeline asset.");
            bool changed = runner.configuration != config || runner.captureCamera != camera || runner.ocean != ocean || runner.sun != sun || runner.environmentVolume != volume || runner.lotusimSource != source || runner.waterPipeline != pipeline || !runner.autoStart || source.scenarioFile != Name + ".yaml" || camera.farClipPlane != config.farClipM;
            runner.configuration = config;
            runner.captureCamera = camera;
            runner.ocean = ocean;
            runner.sun = sun;
            runner.environmentVolume = volume;
            runner.lotusimSource = source;
            runner.waterPipeline = pipeline;
            runner.autoStart = true;
            source.scenarioFile = Name + ".yaml";
            camera.farClipPlane = config.farClipM;
            runner.ValidateSceneReferences();
            if (changed)
            {
                EditorUtility.SetDirty(runner);
                EditorUtility.SetDirty(source);
                EditorUtility.SetDirty(camera);
                EditorSceneManager.MarkSceneDirty(scene);
            }

            return changed;
        }

        static T LocalOrSingle<T>(T current, Scene scene, string field, Func<T, bool> predicate = null)
            where T : Component
        {
            if (current != null && current.gameObject.scene == scene && (predicate == null || predicate(current)))
                return current;
            var matches = scene.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<T>(true)).Where(c => predicate == null || predicate(c)).ToArray();
            if (matches.Length != 1)
                throw new InvalidOperationException("Cannot bind traffic field '" + field + "': expected exactly one local component, found " + matches.Length + ". No scenario launched.");
            return matches[0];
        }
    }
}
