using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    // One fresh, single-shot runner/source at a time. The original source owns
    // every launch/step/stop request; this controller never opens a ROS socket.
    public sealed class DatasetManualCampaignRunner : MonoBehaviour
    {
        public DatasetManualCampaignAsset campaign;
        public DatasetSequenceRunner template;
        public bool autoStart = true;
        public string Status { get; private set; } = "idle";
        public int Completed
        {
            get; private set;
        }
        public int Boxes
        {
            get; private set;
        }
        public int Expected => campaign?.jobs?.Length ?? 0;
        public string OutputDirectory
        {
            get; private set;
        }

        GameObject host;
        DatasetSequenceRunner current;
        DatasetLotusimSource currentSource;
        [Serializable]
        sealed class Record
        {
            public string schema = "lotusim-manual-campaign-status-1", status, error, campaignId;
            public int completed, captured, expected, boxes;
            public string[] imageDirectories;
        }

        [Serializable]
        sealed class ImageRecord
        {
            public string imageId, rgbFile, overlayFile, annotationFile, sourceDirectory, sourceImageId = "f000000", blockId;
            public int imageInBlock;
        }

        [Serializable]
        sealed class ImageManifest
        {
            public string schema = "lotusim-manual-campaign-images-1", campaignId;
            public bool continuousVideo = false, aggregateCoco = false;
            public ImageRecord[] images;
        }

        [Serializable]
        sealed class ExclusionFrame
        {
            public string imageFile, maskFile, rgbSha256, maskSha256;
            public int unityFrame;
        }

        [Serializable]
        sealed class ExclusionManifest
        {
            public string schema = "lotusim-observer-exclusion-1", coordinateSystem = "image_pixels_top_left", maskDirectory = "observer-exclusion", source = "unity_observer_visible_depth";
            public bool observerOnly = true, rgbSameRender = true, observerExclusionOnlyScope = true;
            public string maskMeaning = "Visible ownship pixels only; no target categories, poses or annotations are inference input.";
            public int foregroundValue = 255, width, height;
            public ExclusionFrame[] frames;
        }

        readonly System.Collections.Generic.List<string> directories = new System.Collections.Generic.List<string>();
        readonly System.Collections.Generic.List<ImageRecord> images = new System.Collections.Generic.List<ImageRecord>();
        readonly System.Collections.Generic.List<ExclusionFrame> exclusions = new System.Collections.Generic.List<ExclusionFrame>();
        string error;
        void Start()
        {
            if (autoStart)
                StartCampaign();
        }

        public void StartCampaign()
        {
            if (Status != "idle")
                return;
            try
            {
                campaign.Validate();
                if (template == null || template.autoStart || template.enabled || template.lotusimSource == null || template.lotusimSource.enabled)
                    throw new InvalidOperationException("The manual campaign requires one disabled runner/source template, never an auto-starting legacy runner.");
                template.ValidateSceneReferences();
                OutputDirectory = Path.GetFullPath(Path.Combine(Application.dataPath, "..", "artifacts/manual-campaigns", campaign.campaignId + "_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss") + "_" + Guid.NewGuid().ToString("N").Substring(0, 8)));
                Directory.CreateDirectory(OutputDirectory);
                foreach (string dir in new[]
                {
                    "rgb",
                    "overlays",
                    "annotations",
                    "labels",
                    "labels-recognizable",
                    "masks",
                    "amodal",
                    "observer-exclusion"
                }

                )
                    Directory.CreateDirectory(Path.Combine(OutputDirectory, dir));
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "campaign.json"), campaign.campaignJson);
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "prepared-manifest.json"), campaign.preparedManifestJson);
                Status = "running";
                WriteStatus();
                StartCoroutine(Run());
            }
            catch (Exception e)
            {
                Fail(e);
            }
        }

        IEnumerator Run()
        {
            // Move the disabled template source off the scene: Begin counts
            // inactive consumers as well, so keeping it would be a duplicate.
            var source = template.lotusimSource;
            string address = source.rosAddress, ns = source.rosNamespace;
            int port = source.rosPort;
            float timeout = source.timeoutSeconds;
            var prefab = source.observerPrefab;
            int version = source.observerSetupVersion;
            template.lotusimSource = null;
            Destroy(source);
            yield return null;
            for (int i = 0; i < campaign.jobs.Length; i++)
            {
                try
                {
                    host = new GameObject("Manual campaign image " + (i + 1));
                    currentSource = host.AddComponent<DatasetLotusimSource>();
                    currentSource.rosAddress = address;
                    currentSource.rosNamespace = ns;
                    currentSource.rosPort = port;
                    currentSource.timeoutSeconds = timeout;
                    currentSource.observerPrefab = prefab;
                    currentSource.observerSetupVersion = version;
                    currentSource.scenarioFile = campaign.scenarioFiles[i];
                    current = host.AddComponent<DatasetSequenceRunner>();
                    current.autoStart = false;
                    current.configuration = campaign.jobs[i];
                    current.lotusimSource = currentSource;
                    current.captureCamera = template.captureCamera;
                    current.ocean = template.ocean;
                    current.sun = template.sun;
                    current.environmentVolume = template.environmentVolume;
                    current.waterPipeline = template.waterPipeline;
                    current.StartSequence();
                }
                catch (Exception e)
                {
                    Fail(e);
                    yield break;
                }

                while (current.Status != "complete" && current.Status != "failed" && current.Status != "cancelled" && current.Status != "complete_cleanup_unconfirmed")
                    yield return null;
                if (current.Status != "complete" || !currentSource.CleanupConfirmed)
                {
                    Fail(new InvalidOperationException("Image " + (i + 1) + " ended as " + current.Status + "; batch stopped. No foreign scenario was stopped."));
                    yield break;
                }

                try
                {
                    Aggregate(current.OutputDirectory, i);
                    directories.Add(current.OutputDirectory);
                    Completed++;
                    WriteStatus();
                }
                catch (Exception e)
                {
                    Fail(e);
                    yield break;
                }

                current.enabled = false;
                currentSource.enabled = false;
                Destroy(host);
                host = null;
                current = null;
                currentSource = null;
                yield return null; // deferred destruction and render hooks must finish
            }

            Status = "complete";
            WriteStatus();
            Debug.Log("[Manual Campaign] COMPLETE: " + Completed + " independent annotated images. " + OutputDirectory);
        }

        void Aggregate(string source, int index)
        {
            string oldId = "f000000", id = "f" + index.ToString("D6");
            var frame = JsonUtility.FromJson<DatasetSequenceFrame>(File.ReadAllText(Path.Combine(source, "annotations", oldId + ".json")));
            if (frame?.manualCampaign == null || frame.manualCampaign.imageInCampaign != index)
                throw new InvalidDataException("Independent-image result does not match its requested campaign index.");
            foreach (string folder in new[]
            {
                "rgb",
                "overlays",
                "labels",
                "labels-recognizable"
            }

            )
                Copy(source, folder + "/" + oldId + (folder.StartsWith("labels", StringComparison.Ordinal) ? ".txt" : ".png"), folder + "/" + id + (folder.StartsWith("labels", StringComparison.Ordinal) ? ".txt" : ".png"));
            foreach (string folder in new[]
            {
                "masks",
                "amodal"
            }

            )
            {
                string original = Path.Combine(source, folder, oldId);
                if (!Directory.Exists(original))
                    throw new DirectoryNotFoundException(original);
                foreach (string mask in Directory.GetFiles(original, "*.png"))
                    Copy(source, folder + "/" + oldId + "/" + Path.GetFileName(mask), folder + "/" + id + "/" + Path.GetFileName(mask));
            }

            if (index == 0)
                foreach (string name in new[]
                {
                    "class-map.json",
                    "classes.txt",
                    "recognition-policy.json",
                    "sensor-models.json"
                }

                )
                    if (File.Exists(Path.Combine(source, name)))
                        Copy(source, name, name);
            frame.sequenceId = campaign.campaignId;
            frame.imageId = id;
            frame.imageIndex = index;
            foreach (var annotation in frame.annotations ?? Array.Empty<DatasetFrameAnnotation>())
            {
                annotation.maskFile = annotation.maskFile.Replace(oldId + "/", id + "/");
                annotation.amodalMaskFile = annotation.amodalMaskFile.Replace(oldId + "/", id + "/");
                annotation.overlayFile = "overlays/" + id + ".png";
            }

            if (!string.IsNullOrEmpty(frame.observerExclusionFile))
            {
                string original = frame.observerExclusionFile;
                frame.observerExclusionFile = "observer-exclusion/" + id + ".png";
                Copy(source, original, frame.observerExclusionFile);
                var manifest = JsonUtility.FromJson<ExclusionManifest>(File.ReadAllText(Path.Combine(source, "observer-exclusion.json")));
                if (manifest?.frames?.Length != 1 || manifest.width != frame.width || manifest.height != frame.height)
                    throw new InvalidDataException("Ownship exclusion pair is incomplete.");
                var entry = manifest.frames[0];
                entry.imageFile = "rgb/" + id + ".png";
                entry.maskFile = frame.observerExclusionFile;
                exclusions.Add(entry);
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "observer-exclusion.json"), JsonUtility.ToJson(new ExclusionManifest { width = frame.width, height = frame.height, frames = exclusions.ToArray() }, true));
            }

            DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "annotations", id + ".json"), JsonUtility.ToJson(frame, true));
            string snapshot = "annotations/" + oldId + ".lotusim.json";
            if (File.Exists(Path.Combine(source, snapshot)))
                Copy(source, snapshot, "annotations/" + id + ".lotusim.json");
            images.Add(new ImageRecord { imageId = id, rgbFile = "rgb/" + id + ".png", overlayFile = "overlays/" + id + ".png", annotationFile = "annotations/" + id + ".json", sourceDirectory = source, blockId = frame.manualCampaign.blockId, imageInBlock = frame.manualCampaign.imageInBlock });
            Boxes += (frame.annotations ?? Array.Empty<DatasetFrameAnnotation>()).Length;
            DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "images.json"), JsonUtility.ToJson(new ImageManifest { campaignId = campaign.campaignId, images = images.ToArray() }, true));
            var html = new System.Text.StringBuilder("<!doctype html><html lang=fr><meta charset=utf-8><title>Campagne Unity annotée</title><style>body{font:16px system-ui;background:#10212c;color:#e8f3fb;margin:24px}a{color:#9adfff}article{display:inline-block;vertical-align:top;width:350px;margin:8px}img{width:100%}</style><h1>Campagne Unity — images indépendantes</h1><p>RGB, annotations géométriques, masques et exclusion du bateau observateur. Chaque image conserve son scénario/source original. Pas une vidéo continue ; pas de COCO fusionné.</p>");
            foreach (var entry in images)
            {
                string url = new Uri(OutputDirectory + Path.DirectorySeparatorChar).MakeRelativeUri(new Uri(Path.Combine(entry.sourceDirectory, "index.html"))).ToString();
                html.Append("<article><a href=\"").Append(entry.overlayFile).Append("\"><img loading=lazy src=\"").Append(entry.overlayFile).Append("\"></a><p>").Append(entry.imageId).Append(" · ").Append(System.Net.WebUtility.HtmlEncode(entry.blockId)).Append("</p><a href=\"").Append(entry.rgbFile).Append("\">RGB</a> · <a href=\"").Append(entry.annotationFile).Append("\">JSON</a> · <a href=\"").Append(url).Append("\">Source / COCO / YOLO</a></article>");
            }

            DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "index.html"), html.Append("</html>").ToString());
        }

        void Copy(string source, string relative, string destination)
        {
            string target = Path.Combine(OutputDirectory, destination);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(Path.Combine(source, relative), target, false);
        }

        void WriteStatus()
        {
            if (OutputDirectory != null)
                DatasetSequenceExport.Atomic(Path.Combine(OutputDirectory, "status.json"), JsonUtility.ToJson(new Record { status = Status, error = error, campaignId = campaign.campaignId, completed = Completed, captured = Completed, expected = Expected, boxes = Boxes, imageDirectories = directories.ToArray() }, true));
        }

        void Fail(Exception e)
        {
            Status = "failed";
            error = e.ToString();
            if (current != null)
                current.enabled = false;
            if (currentSource != null)
                currentSource.CancelOwned();
            try
            {
                WriteStatus();
            }
            catch (Exception io)
            {
                Debug.LogWarning("[Manual Campaign] Status write failed: " + io.Message);
            }

            Debug.LogError("[Manual Campaign] FAILED: " + e + ". Existing images preserved: " + OutputDirectory);
        }

        void OnDisable()
        {
            StopAllCoroutines();
            if (current != null)
                current.enabled = false;
            currentSource?.CancelOwned();
            if (host != null)
                Destroy(host);
            if (Status == "running")
            {
                Status = "cancelled";
                try
                {
                    WriteStatus();
                }
                catch (Exception e)
                {
                    Debug.LogWarning(e.Message);
                }
            }
        }
    }
}
