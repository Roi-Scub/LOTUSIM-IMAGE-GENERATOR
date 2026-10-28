using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace Lotusim.EditorTools
{
    public static class DatasetTrafficLibraryBuilder
    {
        [Serializable]
        sealed class Receipt
        {
            public string schema = "lotusim-unity-library-import-1", libraryId, sourcePlanSha256, sourceContextSha256, nativePlanSha256, nativePlanId, scenarioFile, scenePath;
            public bool nativeRenderValidated = false, automaticExecution = false, navigationCertified = false;
            public int captureImages;
            public int[] captureFrames;
            public string[] limitations;
        }

        public static string CoreRoot => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "..", "LOTUSim"));

        [MenuItem("LOTUSim/Dataset/Cooperative traffic/Import library bundle manifest (no Play)")]
        public static void Import()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
            {
                EditorUtility.DisplayDialog("Library import", "Quitte Play avant l’import.", "OK");
                return;
            }

            string file = EditorUtility.OpenFilePanel("Select extracted library manifest.json", "", "json");
            if (string.IsNullOrEmpty(file))
                return;
            try
            {
                string scene = ImportManifest(file);
                EditorUtility.DisplayDialog("Plan importé sans exécution", "Nouvelle scène : " + scene + "\nAucun Play ni client ROS lancé. Ouvre cette scène seule, puis démarre explicitement la séquence lorsque les services existants sont prêts.", "OK");
            }
            catch (Exception error)
            {
                Debug.LogError("[Traffic Library] Import refused; no scenario launched. " + error.Message);
                EditorUtility.DisplayDialog("Import refusé", error.Message, "OK");
            }
        }

        public static string ImportManifest(string file)
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Import outside Play only.");
            TrafficLibraryManifest manifest;
            var originals = DatasetTrafficLibraryImportContract.Verify(file, out manifest);
            var scope = JsonUtility.FromJson<TrafficLibraryScope>(originals["scope.snapshot.json"]);
            var template = JsonUtility.FromJson<TrafficLibraryTemplate>(originals["unity-template.json"]);
            var catalogue = JsonUtility.FromJson<TrafficLibraryCatalogue>(originals["catalogue.snapshot.json"]);
            var audit = JsonUtility.FromJson<TrafficLibraryAudit>(originals["safety-report.json"]);
            var plan = JsonUtility.FromJson<DatasetSequencePlan>(originals["plan.json"]);
            var flags = JsonUtility.FromJson<TrafficLibraryPlanFlags>(originals["plan.json"]);
            if (scope?.schema != "lotusim-traffic-scope-1" || scope.observer == null || scope.weather == null || scope.safety == null || template == null || catalogue?.assets == null || plan?.schema != "lotusim-unity-encounters-1" || plan.events == null || plan.events.Length < 1 || plan.events.Length > 40 || flags == null || flags.containsUncompiledControlPoints || flags.requiresNativeAdapter || audit.actors != plan.events.Length || audit.pairChecks != (plan.events.Length + 1) * plan.events.Length / 2)
                throw new InvalidDataException("Unsupported, incomplete or unaudited cooperative plan.");
            if (flags.captureSchedule != null && flags.captureSchedule.simulationFrames != Mathf.CeilToInt(scope.durationSeconds * scope.fps))
                throw new InvalidDataException("Source double-precision duration and Unity float32 produce different frame counts. Use an integer duration and re-export; no frame is invented or dropped.");
            DatasetTrafficLibraryImportContract.ValidateFrames(plan.captureFrames, scope.fps, scope.durationSeconds);
            if (flags.captureSchedule != null && (flags.captureSchedule.schema != "lotusim-capture-schedule-1" || flags.captureSchedule.fps != scope.fps || Math.Abs(flags.captureSchedule.durationSeconds - scope.durationSeconds) > .0001f || flags.captureSchedule.count != plan.captureFrames.Length || flags.captureSchedule.frames == null || !flags.captureSchedule.frames.SequenceEqual(plan.captureFrames) || flags.captureSchedule.simulationFrames != Mathf.CeilToInt(scope.durationSeconds * scope.fps) || scope.captureSchedule == null || scope.captureSchedule.sha256 != flags.captureSchedule.sha256))
                throw new InvalidDataException("Pinned capture schedules disagree.");
            string scenario = "Library_" + manifest.record.id.Replace("-", "");
            string folder = "Assets/Dataset/TrafficLibrary/" + manifest.record.id;
            string scenePath = "Assets/Scenes/Dataset/" + scenario + ".unity";
            string scenarioPath = Path.Combine(CoreRoot, "assets/scenarios", scenario + ".yaml");
            foreach (string path in new[]
            {
                folder,
                scenePath,
                scenarioPath
            }

            )
            {
                DatasetDashboardImportContract.NoLinks(path);
                if (File.Exists(path) || Directory.Exists(path) || AssetDatabase.LoadMainAssetAtPath(path) != null)
                    throw new IOException("Import target already exists and was preserved: " + path);
            }

            var original = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetTrafficAgentsBuilder.ConfigPath);
            if (original == null)
                throw new FileNotFoundException("The existing MaritimeTrafficAgents configuration is required; no base scene is generated automatically.");
            if (!File.Exists(DatasetLotusimSceneBuilder.ScenePath))
                throw new FileNotFoundException("Existing connected dataset scene missing.");
            var loadedSource = SceneManager.GetSceneByPath(DatasetLotusimSceneBuilder.ScenePath);
            if (loadedSource.IsValid() && loadedSource.isLoaded && loadedSource.isDirty)
                throw new InvalidOperationException("The source scene is dirty; save it explicitly before importing. Nothing was changed.");
            var config = Object.Instantiate(original);
            var bundle = ScriptableObject.CreateInstance<DatasetTrafficPlanBundle>();
            try
            {
                config.name = scenario;
                config.scenarioName = scenario;
                config.trafficPlan = bundle;
                config.manualPlan = null;
                config.seed = plan.seed;
                config.durationSeconds = scope.durationSeconds;
                config.simulationFps = scope.fps;
                if (flags.captureSchedule != null && config.SimulationFrames != flags.captureSchedule.simulationFrames)
                    throw new InvalidDataException("The native configuration frame count differs from the pinned schedule; import refused without changing the timeline.");
                config.captureFrames = (int[])plan.captureFrames.Clone();
                config.captureEveryFrames = 1;
                config.warmupFrames = Math.Max(2, config.warmupFrames);
                config.width = template.width;
                config.height = template.height;
                config.verticalFovDeg = template.verticalFovDeg;
                config.farClipM = template.farClipM;
                config.origin = template.origin;
                config.routeHeadingDeg = scope.observer.headingDeg;
                config.observerSpeedMps = scope.observer.speedKnots * 1852 / 3600;
                config.observerTurnDeg = scope.observer.turnDeg;
                config.viewHeadingDeg = template.viewHeadingDeg;
                config.viewDownPitchDeg = template.cameraPitchDeg;
                config.observerDeckCamera = template.observerDeckCamera;
                config.observerDeckOffsetM = template.observerDeckOffsetM;
                config.observerHeightM = template.observerHeightM;
                config.maxActiveObjects = 40;
                config.renderTimeoutSeconds = Mathf.Max(config.renderTimeoutSeconds, 90);
                config.outputRoot = "artifacts/dataset-library-captures/" + manifest.record.id;
                config.seaEvolution = new DatasetSeaEvolution
                {
                    enabled = false
                };
                config.requireSwell = false;
                config.lighting.cycleDayEveningNight = false;
                var environment = scope.environmentRequested ?? new DatasetManualEnvironment
                {
                    waveHeightM = scope.weather.significantSwellHeightM,
                    windMps = scope.weather.localWindMps,
                    waveDirectionDeg = scope.weather.windTowardsDeg
                };
                environment.Validate();
                plan.sea = environment.Sea();
                plan.seaEvolution = config.seaEvolution;
                plan.light = environment.timeOfDay == "night" ? config.lighting.night : environment.timeOfDay == "dusk" ? config.lighting.evening : config.lighting.day;
                plan.lightingPhases = new[]
                {
                    new DatasetLightingPhase
                    {
                        startFrame = 0,
                        endFrame = config.SimulationFrames,
                        timeOfDay = environment.timeOfDay == "night" ? "23:00" : environment.timeOfDay == "dusk" ? "18:30" : "12:00",
                        light = plan.light
                    }
                };
                BuildProfiles(config, plan, scope, catalogue, audit);
                bundle.planJson = JsonUtility.ToJson(plan, true);
                bundle.scopeJson = originals["scope.snapshot.json"];
                bundle.catalogueJson = originals["catalogue.snapshot.json"];
                bundle.auditJson = originals["safety-report.json"];
                bundle.messagesJson = originals["agent-messages.json"];
                bundle.safety = scope.safety.Native();
                bundle.contentSha256 = bundle.ComputeHash();
                config.Validate();
                var compiled = config.MakePlan();
                string yaml = DatasetLotusimScenario.Yaml(config, compiled);
                string nativeId = DatasetLotusimScenario.PlanId(config, compiled);
                EnsureFolder(folder);
                EnsureFolder("Assets/Scenes/Dataset");
                AssetDatabase.CreateAsset(bundle, folder + "/plan.asset");
                AssetDatabase.CreateAsset(config, folder + "/config.asset");
                foreach (var item in originals)
                    WriteNew(Path.Combine(folder, "source-" + item.Key), item.Value);
                WriteNew(Path.Combine(folder, "compiled-plan.json"), bundle.planJson);
                WriteNew(scenarioPath, yaml);
                var receipt = new Receipt
                {
                    libraryId = manifest.record.id,
                    sourcePlanSha256 = manifest.record.planSha256,
                    sourceContextSha256 = manifest.record.contextSha256,
                    nativePlanSha256 = DatasetTrafficPlanBundle.Hash(bundle.planJson),
                    nativePlanId = nativeId,
                    scenarioFile = Path.GetFileName(scenarioPath),
                    scenePath = scenePath,
                    captureImages = config.ImageCount,
                    captureFrames = config.captureFrames,
                    limitations = new[]
                    {
                        "Original approved plan/audit retained byte-for-byte; native JSON adds only runtime capability/render bindings.",
                        "JSON numbers are represented by Unity float32; this is not a new native safety certificate or a rendered-image validation.",
                        "Python-exported YAML is archived, not used: the connected scenario is regenerated with the native C# PlanId.",
                        "Cloud/rain requests are archived only; this importer binds sea/light proxies, not manual-image weather shaders.",
                        "Weather is an existing uncalibrated visual proxy. No engine, Play or ROS client was started."
                    }
                };
                WriteNew(Path.Combine(folder, "import-receipt.json"), JsonUtility.ToJson(receipt, true));
                AssetDatabase.SaveAssetIfDirty(bundle);
                AssetDatabase.SaveAssetIfDirty(config);
                CopyScene(scenePath, config, Path.GetFileName(scenarioPath));
                AssetDatabase.Refresh();
                Debug.Log("[Traffic Library] Imported " + config.ImageCount + " pinned capture instants into " + scenePath + "; autoStart=false, no Play/ROS launched.");
                return scenePath;
            }
            finally
            {
                if (!AssetDatabase.Contains(config))
                    Object.DestroyImmediate(config);
                if (!AssetDatabase.Contains(bundle))
                    Object.DestroyImmediate(bundle);
            }
        }

        static void BuildProfiles(DatasetSequenceConfig config, DatasetSequencePlan plan, TrafficLibraryScope scope, TrafficLibraryCatalogue catalogue, TrafficLibraryAudit audit)
        {
            if (catalogue.assets.Any(a => a == null) || catalogue.assets.Select(a => a.model).Distinct().Count() != catalogue.assets.Length)
                throw new InvalidDataException("Invalid/duplicate catalogue models.");
            foreach (var definition in config.classes)
            {
                definition.count = 0;
                definition.prefabVariants = Array.Empty<GameObject>();
            }

            var profiles = new List<DatasetTrafficActorProfile>();
            foreach (var e in plan.events)
            {
                if (e == null || string.IsNullOrEmpty(e.modelName) || !Regex.IsMatch(e.modelName, @"\A[a-z][a-z0-9_]{0,63}\z") || e.modelName.StartsWith("import_", StringComparison.Ordinal))
                    throw new InvalidDataException("Only existing native catalogue prefabs are supported; dynamic imported revisions require their own pinned adapter.");
                var a = catalogue.assets.SingleOrDefault(item => item.model == e.modelName);
                int index = Array.FindIndex(config.classes, c => c.category == e.category);
                if (a == null || index < 0 || a.category != e.category || !DatasetManualEnvironment.Range(a.lengthM, .001f, 1000) || !DatasetManualEnvironment.Range(a.heightM, .001f, 1000) || !DatasetManualEnvironment.Range(a.bufferM, .1f, 200) || !DatasetManualEnvironment.Range(a.maxSpeedMps, 0, 350) || !new[]
                {
                    "air",
                    "sea",
                    "moored"
                }.Contains(a.domain))
                    throw new InvalidDataException("Missing or unsupported native catalogue capability: " + e.modelName);
                var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Prefabs/" + e.modelName + ".prefab");
                if (prefab == null)
                    throw new FileNotFoundException("Native prefab missing: " + e.modelName);
                var definition = config.classes[index];
                definition.count++;
                if (definition.count > 12)
                    throw new InvalidDataException("At most twelve appearances per native category.");
                if (definition.moored != (a.domain == "moored"))
                    throw new InvalidDataException("Category/domain mismatch: " + e.modelName);
                if (prefab != definition.prefab)
                    definition.prefabVariants = definition.prefabVariants.Concat(new[] { prefab }).Distinct().ToArray();
                definition.distanceM = new Vector2(5, 60000);
                definition.altitudeM = new Vector2(0, 15000);
                definition.speedMps = definition.moored ? Vector2.zero : new Vector2(.001f, 350);
                e.classIndex = index; // Resolve native class binding; preserve source track identity and all motion fields.
                float cap = Mathf.Min(a.maxSpeedMps, Speed(a.speedMax, a.speedUnit));
                if (a.domain == "sea" && a.lengthM < 15)
                    cap = Mathf.Min(cap, Mathf.Max(5, (a.category == "jetski" ? 24 : 30) - 8 * scope.weather.significantSwellHeightM) * 1852 / 3600);
                if (e.velocity.magnitude > cap + .002f || a.domain == "moored" && e.velocity != Vector3.zero || a.domain != "air" && e.centerPosition.y != 0 || a.domain == "air" && (!DatasetManualEnvironment.Range(e.centerPosition.y, .001f, a.maxAltitudeM) || e.velocity.magnitude + scope.weather.localWindMps > a.maxSpeedMps + .002f))
                    throw new InvalidDataException("Trajectory exceeds attested capability: " + e.instance);
                profiles.Add(new DatasetTrafficActorProfile { instance = e.instance, model = e.modelName, category = e.category, domain = a.domain, evidence = a.evidence, lengthM = a.lengthM, heightM = a.heightM, bufferM = a.bufferM, groundSpeedMps = e.velocity.magnitude, speedKnots = e.velocity.magnitude * 3600 / 1852, speedKmh = e.velocity.magnitude * 3.6f, airSpeedEstimateMps = a.domain == "air" ? (e.velocity - DatasetSequenceConfig.Bearing(scope.weather.windTowardsDeg) * scope.weather.localWindMps).magnitude : 0, safeMaximumMps = cap, maxSpeedMps = a.maxSpeedMps, altitudeM = e.centerPosition.y, minCameraDistanceM = a.role == "fast_flyby" && scope.fastDrones != null && scope.fastDrones.enabled ? scope.fastDrones.minCameraDistanceM : 0 });
            }

            string planner = plan.traffic == null ? "" : plan.traffic.plannerSha256;
            plan.maxActive = plan.events.Length;
            plan.traffic = new DatasetTrafficMetadata
            {
                schema = "lotusim-cooperative-traffic-1",
                scenarioName = config.ScenarioName,
                inputSha256 = audit.inputSha256,
                plannerSha256 = planner,
                continuousSafetyApproved = true,
                reactiveAvoidance = false,
                runtimePositionToleranceM = scope.safety.runtimePositionToleranceM,
                localWindMps = scope.weather.localWindMps,
                significantSwellHeightM = scope.weather.significantSwellHeightM,
                actorProfiles = profiles.ToArray()
            };
        }

        static float Speed(float value, string unit)
        {
            if (!DatasetManualEnvironment.Range(value, 0, 1000))
                throw new InvalidDataException("Invalid capability speed.");
            if (unit == "mps")
                return value;
            if (unit == "kn")
                return value * 1852 / 3600;
            if (unit == "kmh")
                return value / 3.6f;
            throw new InvalidDataException("Unknown explicit speed unit.");
        }

        static void CopyScene(string target, DatasetSequenceConfig config, string yaml)
        {
            var prior = SceneManager.GetActiveScene();
            var source = SceneManager.GetSceneByPath(DatasetLotusimSceneBuilder.ScenePath);
            bool opened = !source.IsValid() || !source.isLoaded;
            Scene destination = default(Scene);
            if (opened)
                source = EditorSceneManager.OpenScene(DatasetLotusimSceneBuilder.ScenePath, OpenSceneMode.Additive);
            try
            {
                if (source.isDirty)
                    throw new InvalidOperationException("Save the original connected source scene before importing; it was not modified.");
                if (!EditorSceneManager.SaveScene(source, target, true))
                    throw new IOException("Cannot copy the existing connected scene.");
                destination = EditorSceneManager.OpenScene(target, OpenSceneMode.Additive);
                DatasetTrafficAgentsBuilder.BindSceneReferences(destination, config);
                var runner = destination.GetRootGameObjects().SelectMany(g => g.GetComponentsInChildren<DatasetSequenceRunner>(true)).Single();
                runner.autoStart = false;
                runner.enabled = true;
                runner.lotusimSource.scenarioFile = yaml;
                runner.lotusimSource.enabled = true;
                runner.ValidateSceneReferences();
                EditorUtility.SetDirty(runner);
                EditorUtility.SetDirty(runner.lotusimSource);
                if (!EditorSceneManager.SaveScene(destination))
                    throw new IOException("Cannot save new library scene references.");
            }
            finally
            {
                if (destination.IsValid() && destination.isLoaded)
                    EditorSceneManager.CloseScene(destination, true);
                if (opened)
                    EditorSceneManager.CloseScene(source, true);
                if (prior.IsValid() && prior.isLoaded)
                    SceneManager.SetActiveScene(prior);
            }
        }

        static void WriteNew(string file, string value)
        {
            DatasetDashboardImportContract.NoLinks(file);
            string parent = Path.GetDirectoryName(file);
            Directory.CreateDirectory(parent);
            DatasetDashboardImportContract.NoLinks(parent);
            using (var stream = new FileStream(file, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            {
                byte[] data = new UTF8Encoding(false, true).GetBytes(value);
                stream.Write(data, 0, data.Length);
                stream.Flush(true);
            }
        }

        static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path))
                return;
            int split = path.LastIndexOf('/');
            EnsureFolder(path.Substring(0, split));
            AssetDatabase.CreateFolder(path.Substring(0, split), path.Substring(split + 1));
        }
    }
}
