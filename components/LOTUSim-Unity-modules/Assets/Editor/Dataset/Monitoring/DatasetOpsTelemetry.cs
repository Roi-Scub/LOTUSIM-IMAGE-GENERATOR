using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Lotusim.Dataset;
using Unity.Robotics.ROSTCPConnector;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace Lotusim.EditorTools
{
    // Read-only editor observation. This class never opens a ROS connection,
    // creates a camera, advances LOTUSim or starts/stops a capture.
    [InitializeOnLoad]
    public static class DatasetOpsTelemetry
    {
        const string SessionKey = "LOTUSim.Operations.Session";
        const double HeartbeatPeriod = 1.0, PreviewPeriod = 2.0;
        static readonly string SessionId;
        static readonly int EditorPid;
        static double nextHeartbeat, nextPreview;
        static bool closing;
        static Texture2D thumbnail;
        static PreviewState lastPreview;
        static string lastSnapshotKey, snapshotUpdatedAt;
        static string previewError = "";
        static Camera observedCamera;
        static double lastObservedRender = -1000;
        [Serializable]
        sealed class Heartbeat
        {
            public string schema = "lotusim-ops-unity-1", updatedAt, sessionId, editorState, sceneName, scenePath;
            public int editorPid;
            public bool isPlaying, isPaused, isCompiling;
            public CaptureState capture;
            public ObserverState rgbObserver;
            public RosState ros;
            public LotusimState lotusim;
            public PreviewState preview;
            public string error;
        }

        [Serializable]
        sealed class CaptureState
        {
            public string status, outputDirectory, motionSource;
            public int captured, expected, boxes;
        }

        [Serializable]
        sealed class ObserverState
        {
            public bool running;
            public string outputDirectory;
        }

        [Serializable]
        sealed class RosState
        {
            public int instanceCount, activeInstanceCount, threadCount, connectedCount;
            public string connectionState;
            public bool hasConnectionError;
            public double lastMessageAgeSeconds = -1;
        }

        [Serializable]
        sealed class LotusimState
        {
            public string status, error, observerId, scenario, runId, snapshotUpdatedAt;
            public bool hasFrame;
            public int frame = -1, objectCount;
            public double timeSeconds, worldTimeSeconds;
            public ObjectState[] objects = Array.Empty<ObjectState>();
        }

        [Serializable]
        sealed class ObjectState
        {
            public string id, model;
            public float eastM, northM, altitudeM;
        }

        [Serializable]
        sealed class PreviewState
        {
            public string file = "preview.jpg", updatedAt, source = "dataset_render_texture", error, captureOutputDirectory;
            public int width, height, captured;
            public bool live;
        }

        static DatasetOpsTelemetry()
        {
            if (Application.isBatchMode)
                return;
            EditorPid = Process.GetCurrentProcess().Id;
            SessionId = SessionState.GetString(SessionKey, "");
            if (string.IsNullOrEmpty(SessionId))
            {
                SessionId = Guid.NewGuid().ToString("N");
                SessionState.SetString(SessionKey, SessionId);
            }

            EditorApplication.update += Tick;
            RenderPipelineManager.endContextRendering += ObserveRender;
            EditorApplication.quitting += Quit;
            AssemblyReloadEvents.beforeAssemblyReload += Reload;
        }

        [MenuItem("LOTUSim/Dataset/Operations/Open local dashboard")]
        static void OpenDashboard() => Application.OpenURL("http://127.0.0.1:8766/");
        static string UtcNow() => DateTime.UtcNow.ToString("o");
        static string DirectoryPath => Path.GetFullPath(Path.Combine(Application.dataPath, "..", "artifacts", "operations"));

        static bool SceneObject(Component component) => component != null && component.gameObject.scene.IsValid() && component.gameObject.scene.isLoaded;
        static bool Active(Component component) => SceneObject(component) && component.gameObject.activeInHierarchy && (!(component is Behaviour behaviour) || behaviour.enabled);
        static T FirstActive<T>()
            where T : Component => UnityEngine.Object.FindObjectsOfType<T>(true).FirstOrDefault(Active);
        static void Tick()
        {
            if (closing || Application.isBatchMode || EditorApplication.timeSinceStartup < nextHeartbeat)
                return;
            nextHeartbeat = EditorApplication.timeSinceStartup + HeartbeatPeriod;
            Publish("ready", true);
        }

        static void ObserveRender(ScriptableRenderContext context, System.Collections.Generic.List<Camera> cameras)
        {
            if (observedCamera != null && cameras.Contains(observedCamera))
                lastObservedRender = EditorApplication.timeSinceStartup;
        }

        static RosState ReadRos()
        {
            var connections = UnityEngine.Object.FindObjectsOfType<ROSConnection>(true).Where(SceneObject).ToArray();
            var active = connections.Where(Active).ToArray();
            var state = new RosState
            {
                instanceCount = connections.Length,
                activeInstanceCount = active.Length,
                threadCount = active.Count(r => r.HasConnectionThread),
                hasConnectionError = active.Any(r => r.HasConnectionThread && r.HasConnectionError)
            };
            var observed = active.Where(r => r.HasConnectionThread && !r.HasConnectionError && r.LastMessageReceivedRealtime > 0).ToArray();
            state.connectedCount = observed.Length;
            if (observed.Length > 0)
                state.lastMessageAgeSeconds = Math.Max(0, Time.realtimeSinceStartup - observed.Max(r => r.LastMessageReceivedRealtime));
            state.connectionState = active.Length > 1 ? "multiple_instances" : connections.Length == 0 ? "absent" : active.Length == 0 ? "inactive" : state.hasConnectionError ? "connection_error" : observed.Length > 0 ? "reply_observed" : state.threadCount > 0 ? "thread_started" : "not_started";
            // reply_observed is historical evidence from the existing client,
            // not an active TCP probe and not a guarantee of present liveness.
            return state;
        }

        static LotusimState ReadLotusim(DatasetLotusimSource source)
        {
            if (source == null)
                return new LotusimState
                {
                    status = "not_present"
                };
            var value = new LotusimState
            {
                status = source.Status,
                error = FirstLine(source.Error),
                hasFrame = source.HasFrame
            };
            var frame = source.Current;
            if (frame == null)
                return value;
            string key = (frame.runId ?? "") + ":" + frame.frame;
            if (lastSnapshotKey != key)
            {
                lastSnapshotKey = key;
                snapshotUpdatedAt = UtcNow();
            }

            value.snapshotUpdatedAt = snapshotUpdatedAt;
            value.frame = frame.frame;
            value.timeSeconds = frame.timeSeconds;
            value.worldTimeSeconds = frame.worldTimeSeconds;
            value.observerId = frame.observer;
            value.scenario = frame.scenario;
            value.runId = frame.runId;
            value.objects = (frame.objects ?? Array.Empty<DatasetLotusimObject>()).Where(o => o != null).Take(41).Select(o => new ObjectState { id = o.instance, model = o.model, eastM = o.position.x, northM = o.position.y, altitudeM = o.position.z }).ToArray();
            value.objectCount = value.objects.Length;
            return value;
        }

        static bool TerminalStatus(string status) => status == "complete" || status == "complete_cleanup_unconfirmed" || status == "failed" || status == "cancelled" || status == "idle";
        static void UpdatePreview(DatasetSequenceRunner runner, bool captureAllowed)
        {
            if (lastPreview != null)
                lastPreview.live = false;
            if (!captureAllowed || !EditorApplication.isPlaying || EditorApplication.isPaused || runner == null || runner.Captured < 1 || TerminalStatus(runner.Status) || EditorApplication.timeSinceStartup - lastObservedRender > 3)
                return;
            var source = runner.Preview;
            if (source == null || !source.IsCreated())
                return;
            if (EditorApplication.timeSinceStartup < nextPreview)
            {
                if (lastPreview != null && lastPreview.captureOutputDirectory == runner.OutputDirectory && lastPreview.captured <= runner.Captured)
                    lastPreview.live = true;
                return;
            }

            nextPreview = EditorApplication.timeSinceStartup + PreviewPeriod;
            var oldActive = RenderTexture.active;
            RenderTexture temporary = null;
            try
            {
                int width = Math.Min(640, source.width), height = Math.Max(1, Mathf.RoundToInt(width * (float)source.height / source.width));
                if (height > 360)
                {
                    height = 360;
                    width = Math.Max(1, Mathf.RoundToInt(height * (float)source.width / source.height));
                }

                temporary = RenderTexture.GetTemporary(width, height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
                Graphics.Blit(source, temporary);
                if (thumbnail == null || thumbnail.width != width || thumbnail.height != height)
                {
                    if (thumbnail != null)
                        UnityEngine.Object.DestroyImmediate(thumbnail);
                    thumbnail = new Texture2D(width, height, TextureFormat.RGB24, false, false)
                    {
                        hideFlags = HideFlags.HideAndDontSave
                    };
                }

                RenderTexture.active = temporary;
                thumbnail.ReadPixels(new Rect(0, 0, width, height), 0, 0, false);
                thumbnail.Apply(false, false);
                Directory.CreateDirectory(DirectoryPath);
                Atomic(Path.Combine(DirectoryPath, "preview.jpg"), thumbnail.EncodeToJPG(78));
                previewError = "";
                lastPreview = new PreviewState
                {
                    updatedAt = UtcNow(),
                    width = width,
                    height = height,
                    captured = runner.Captured,
                    captureOutputDirectory = runner.OutputDirectory,
                    live = true,
                    error = ""
                };
            }
            catch (Exception exception)
            {
                previewError = FirstLine(exception.Message);
                if (lastPreview != null)
                    lastPreview.live = false;
            }
            finally
            {
                RenderTexture.active = oldActive;
                if (temporary != null)
                    RenderTexture.ReleaseTemporary(temporary);
            }
        }

        static void Publish(string editorState, bool allowPreview)
        {
            try
            {
                var scene = SceneManager.GetActiveScene();
                var runner = FirstActive<DatasetSequenceRunner>();
                if (observedCamera != (runner == null ? null : runner.captureCamera))
                {
                    observedCamera = runner == null ? null : runner.captureCamera;
                    lastObservedRender = -1000;
                }

                var source = runner != null && runner.lotusimSource != null ? runner.lotusimSource : FirstActive<DatasetLotusimSource>();
                var batch = FirstActive<DatasetManualCampaignRunner>();
                UpdatePreview(runner, allowPreview);
                var data = new Heartbeat
                {
                    updatedAt = UtcNow(),
                    sessionId = SessionId,
                    editorPid = EditorPid,
                    editorState = editorState,
                    isPlaying = EditorApplication.isPlaying,
                    isPaused = EditorApplication.isPaused,
                    isCompiling = EditorApplication.isCompiling,
                    sceneName = scene.IsValid() ? scene.name : "",
                    scenePath = scene.IsValid() ? scene.path : "",
                    capture = batch != null ? new CaptureState
                    {
                        status = batch.Status,
                        captured = batch.Completed,
                        expected = batch.Expected,
                        boxes = batch.Boxes,
                        outputDirectory = batch.OutputDirectory,
                        motionSource = "LOTUSim independent-image campaign"
                    }

                    : runner == null ? null : new CaptureState
                    {
                        status = runner.Status,
                        captured = runner.Captured,
                        expected = runner.Expected,
                        boxes = runner.Boxes,
                        outputDirectory = runner.OutputDirectory,
                        motionSource = runner.MotionSource
                    },
                    rgbObserver = new ObserverState
                    {
                        running = DatasetRgbObserverTools.Running,
                        outputDirectory = DatasetRgbObserverTools.OutputDirectory
                    },
                    ros = ReadRos(),
                    lotusim = ReadLotusim(source),
                    preview = lastPreview,
                    error = previewError
                };
                Directory.CreateDirectory(DirectoryPath);
                Atomic(Path.Combine(DirectoryPath, "unity.json"), System.Text.Encoding.UTF8.GetBytes(JsonUtility.ToJson(data, false)));
            }
            catch (Exception)
            {
                // Telemetry must never fail the simulation or advance/stop it.
                // Missing/stale heartbeats are deliberately visible as unknown
                // or stale in the dashboard instead of manufactured health.
            }
        }

        static string FirstLine(string text)
        {
            if (string.IsNullOrEmpty(text))
                return "";
            int end = text.IndexOfAny(new[] { '\r', '\n' });
            if (end >= 0)
                text = text.Substring(0, end);
            return text.Length > 512 ? text.Substring(0, 512) : text;
        }

        static void Atomic(string path, byte[] bytes)
        {
            string temporary = path + ".partial";
            File.WriteAllBytes(temporary, bytes);
            if (File.Exists(path))
                File.Replace(temporary, path, null);
            else
                File.Move(temporary, path);
        }

        static void Reload()
        {
            closing = true;
            Publish("reloading", false);
            Cleanup();
        }

        static void Quit()
        {
            closing = true;
            Publish("quitting", false);
            Cleanup();
        }

        static void Cleanup()
        {
            EditorApplication.update -= Tick;
            RenderPipelineManager.endContextRendering -= ObserveRender;
            if (thumbnail != null)
            {
                UnityEngine.Object.DestroyImmediate(thumbnail);
                thumbnail = null;
            }
        }
    }
}
