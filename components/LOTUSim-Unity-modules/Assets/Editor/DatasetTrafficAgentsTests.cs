using System;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Lotusim.EditorTools
{
    public static class DatasetTrafficAgentsTests
    {
        [MenuItem("LOTUSim/Dataset/Cooperative traffic/Validate compiled plan and runtime guard")]
        public static void Run()
        {
            var c = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetTrafficAgentsBuilder.ConfigPath);
            if (c == null)
                throw new Exception("Generate the cooperative traffic scenario first.");
            var p = c.MakePlan();
            foreach (float t in new[]
            {
                0,
                c.durationSeconds * .5f,
                c.durationSeconds - 1f / c.simulationFps
            }

            )
            {
                var actors = p.events.Select(e => new DatasetSequenceActor { encounter = e, sourcePose = new Pose(e.Position(t), Quaternion.identity) }).ToArray();
                var observer = new Pose(c.ObserverRoot(t), Quaternion.identity);
                DatasetTrafficRuntimeGuard.Check(c, p, t, actors, observer);
                var a = actors[0].sourcePose;
                a.position += Vector3.right * 10;
                actors[0].sourcePose = a;
                bool rejected = false;
                try
                {
                    DatasetTrafficRuntimeGuard.Check(c, p, t, actors, observer);
                }
                catch (InvalidOperationException)
                {
                    rejected = true;
                }

                if (!rejected)
                    throw new Exception("Unexpected source motion was not rejected.");
            }

            const string old = "{\"schema\":\"lotusim-dataset-capabilities-1\",\"snapshotSchema\":\"lotusim-dataset-step-1\",\"ownedStop\":true,\"steppedTimeline\":true,\"constantTurnTrajectories\":true}";
            bool incompatible = false;
            try
            {
                DatasetLotusimProtocol.CheckCapabilities(old, true, 230);
            }
            catch (InvalidOperationException)
            {
                incompatible = true;
            }

            if (!incompatible)
                throw new Exception("Legacy 200 m/s module was allowed to launch an airliner.");
            DatasetLotusimProtocol.CheckCapabilities(old.Substring(0, old.Length - 1) + ",\"maxDatasetSpeedMps\":350}", true, 230);
            var modern = old.Substring(0, old.Length - 1) + ",\"maxDatasetSpeedMps\":350}";
            incompatible = false;
            try
            {
                DatasetLotusimProtocol.CheckCapabilities(modern, true, 230, true);
            }
            catch (InvalidOperationException)
            {
                incompatible = true;
            }

            if (!incompatible)
                throw new Exception("Old backend without bounded turns accepted the fast flyby.");
            DatasetLotusimProtocol.CheckCapabilities(modern.Substring(0, modern.Length - 1) + ",\"boundedTurnTrajectories\":true}", true, 230, true);
            if (c.captureFrames != null && c.captureFrames.Length > 0 && Enumerable.Range(0, c.SimulationFrames).Count(c.ShouldCapture) != c.ImageCount)
                throw new Exception("Burst capture schedule/count mismatch");
            foreach (var e in p.events.Where(e => e.boundedTurn))
                foreach (var at in new[]
                {
                    e.turnStartSeconds,
                    e.centerSeconds,
                    e.turnEndSeconds
                }

                )
                {
                    const float h = .02f;
                    var finiteDifference = (e.Position(at + h) - e.Position(at - h)) / (2 * h);
                    if (Vector3.Distance(finiteDifference, e.Velocity(at)) > .2f)
                        throw new Exception("Turn velocity is discontinuous or inconsistent with position.");
                }

            Debug.Log("[Traffic Tests] PASS compiled model mapping, source deviation rejection, separation guard, bounded turns, burst schedule and high-speed backend preflight.");
        }

        [MenuItem("LOTUSim/Dataset/Cooperative traffic/Validate scene reference persistence")]
        public static void RunSceneReferences()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode)
                throw new InvalidOperationException("Validate scene references outside Play.");
            var config = AssetDatabase.LoadAssetAtPath<DatasetSequenceConfig>(DatasetTrafficAgentsBuilder.ConfigPath);
            if (config == null)
                throw new Exception("Generate the traffic configuration first.");
            var prior = SceneManager.GetActiveScene();
            var source = SceneManager.GetSceneByPath(DatasetTrafficAgentsBuilder.ScenePath);
            bool opened = !source.IsValid() || !source.isLoaded;
            string path = AssetDatabase.GenerateUniqueAssetPath("Assets/Dataset/TrafficSceneReferenceTest.unity");
            var before = File.ReadAllBytes(DatasetTrafficAgentsBuilder.ScenePath);
            Scene test = default(Scene), foreign = default(Scene);
            try
            {
                if (opened)
                    source = EditorSceneManager.OpenScene(DatasetTrafficAgentsBuilder.ScenePath, OpenSceneMode.Additive);
                if (source.isDirty)
                    throw new InvalidOperationException("Save the traffic scene before this persistence test.");
                if (!EditorSceneManager.SaveScene(source, path, true))
                    throw new Exception("Cannot copy test scene.");
                test = EditorSceneManager.OpenScene(path, OpenSceneMode.Additive);
                var runner = test.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<DatasetSequenceRunner>(true)).Single();
                runner.ValidateSceneReferences();
                var camera = runner.captureCamera;
                var ocean = runner.ocean;
                var sun = runner.sun;
                var volume = runner.environmentVolume;
                var sourceComponent = runner.lotusimSource;
                var pipeline = runner.waterPipeline;
                runner.configuration = null;
                runner.captureCamera = null;
                runner.ocean = null;
                runner.sun = null;
                runner.environmentVolume = null;
                runner.lotusimSource = null;
                runner.waterPipeline = null;
                bool precise = false;
                try
                {
                    runner.ValidateSceneReferences();
                }
                catch (InvalidOperationException e)
                {
                    precise = e.Message.Contains("captureCamera") && e.Message.Contains("ocean") && e.Message.Contains("waterPipeline");
                }

                if (!precise)
                    throw new Exception("Missing references were not diagnosed precisely.");
                if (!DatasetTrafficAgentsBuilder.BindSceneReferences(test, config) || runner.captureCamera != camera || runner.ocean != ocean || runner.sun != sun || runner.environmentVolume != volume || runner.lotusimSource != sourceComponent || runner.waterPipeline != pipeline)
                    throw new Exception("Missing references were not restored within the destination scene.");
                foreign = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Additive);
                var foreignCamera = new GameObject("Unrelated scene camera").AddComponent<Camera>();
                SceneManager.MoveGameObjectToScene(foreignCamera.gameObject, foreign);
                runner.captureCamera = foreignCamera;
                bool rejected = false;
                try
                {
                    runner.ValidateSceneReferences();
                }
                catch (InvalidOperationException e)
                {
                    rejected = e.Message.Contains("another scene");
                }

                if (!rejected)
                    throw new Exception("Cross-scene runtime reference was allowed.");
                DatasetTrafficAgentsBuilder.BindSceneReferences(test, config);
                if (runner.captureCamera != camera)
                    throw new Exception("Repair used another scene's camera.");
                var duplicate = new GameObject("Ambiguous test camera").AddComponent<Camera>();
                SceneManager.MoveGameObjectToScene(duplicate.gameObject, test);
                runner.captureCamera = null;
                rejected = false;
                try
                {
                    DatasetTrafficAgentsBuilder.BindSceneReferences(test, config);
                }
                catch (InvalidOperationException e)
                {
                    rejected = e.Message.Contains("captureCamera") && e.Message.Contains("found 2");
                }

                UnityEngine.Object.DestroyImmediate(duplicate.gameObject);
                if (!rejected)
                    throw new Exception("Ambiguous camera binding was silently accepted.");
                DatasetTrafficAgentsBuilder.BindSceneReferences(test, config);
                if (!EditorSceneManager.SaveScene(test))
                    throw new Exception("Cannot save repaired scene.");
                EditorSceneManager.CloseScene(test, true);
                test = EditorSceneManager.OpenScene(path, OpenSceneMode.Additive);
                runner = test.GetRootGameObjects().SelectMany(r => r.GetComponentsInChildren<DatasetSequenceRunner>(true)).Single();
                runner.ValidateSceneReferences();
                if (DatasetTrafficAgentsBuilder.BindSceneReferences(test, config))
                    throw new Exception("Saved scene references were not stable after closing the source and reloading.");
                if (!before.SequenceEqual(File.ReadAllBytes(DatasetTrafficAgentsBuilder.ScenePath)))
                    throw new Exception("Test modified the original traffic scene.");
                Debug.Log("[Traffic Scene Tests] PASS serialized copy/reload, missing-reference repair, local ownership, ambiguous camera rejection and idempotent binding. No ROS connection opened.");
            }
            finally
            {
                if (test.IsValid() && test.isLoaded)
                    EditorSceneManager.CloseScene(test, true);
                if (foreign.IsValid() && foreign.isLoaded)
                    EditorSceneManager.CloseScene(foreign, true);
                if (opened && source.IsValid() && source.isLoaded)
                    EditorSceneManager.CloseScene(source, true);
                if (prior.IsValid() && prior.isLoaded)
                    SceneManager.SetActiveScene(prior);
                if (File.Exists(path))
                    AssetDatabase.DeleteAsset(path);
            }
        }
    }
}
