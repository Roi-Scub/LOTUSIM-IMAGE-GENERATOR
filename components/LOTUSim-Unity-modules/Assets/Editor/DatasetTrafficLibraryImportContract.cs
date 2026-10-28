using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Lotusim.Dataset;
using UnityEngine;

namespace Lotusim.EditorTools
{
    [Serializable]
    public sealed class TrafficLibraryArtifact
    {
        public string name, sha256;
        public long bytes;
    }

    [Serializable]
    public sealed class TrafficLibraryRecord
    {
        public string id, name, auditStatus, planSha256, contextSha256;
        public bool ready, applied;
    }

    [Serializable]
    public sealed class TrafficLibraryManifest
    {
        public string schema;
        public bool applied;
        public TrafficLibraryRecord record;
        public TrafficLibraryArtifact[] artifacts;
    }

    [Serializable]
    public sealed class TrafficLibraryAudit
    {
        public string planSha256, contextSha256, inputSha256;
        public bool approved, continuousSafetyApproved, fullColregCompliance, notCertified;
        public int actors, pairChecks;
    }

    [Serializable]
    public sealed class TrafficLibraryObserver
    {
        public float speedKnots, headingDeg, turnDeg;
    }

    [Serializable]
    public sealed class TrafficLibraryWeather
    {
        public float localWindMps, windTowardsDeg, significantSwellHeightM;
    }

    [Serializable]
    public sealed class TrafficLibraryFastDrones
    {
        public bool enabled;
        public string model;
        public float minCameraDistanceM;
    }

    [Serializable]
    public sealed class TrafficLibrarySafety
    {
        public float seaClearanceM, observerBufferM, aircraftHorizontalM, aircraftVerticalM, planningMarginM, runtimePositionToleranceM;
        public DatasetTrafficSafetySettings Native()
        {
            if (!DatasetManualEnvironment.Range(seaClearanceM, 10, 500) || !DatasetManualEnvironment.Range(observerBufferM, 30, 500) || !DatasetManualEnvironment.Range(aircraftHorizontalM, 100, 5000) || !DatasetManualEnvironment.Range(aircraftVerticalM, 100, 1000) || !DatasetManualEnvironment.Range(planningMarginM, 1, 100) || !DatasetManualEnvironment.Range(runtimePositionToleranceM, .01f, 5))
                throw new InvalidDataException("Invalid attested safety domain/tolerance.");
            return new DatasetTrafficSafetySettings
            {
                seaClearanceM = seaClearanceM,
                observerBufferM = observerBufferM,
                aircraftHorizontalM = aircraftHorizontalM,
                aircraftVerticalM = aircraftVerticalM,
                planningMarginM = planningMarginM
            };
        }
    }

    [Serializable]
    public sealed class TrafficLibrarySchedule
    {
        public string schema, sha256;
        public int fps, simulationFrames, count;
        public float durationSeconds;
        public int[] frames;
    }

    [Serializable]
    public sealed class TrafficLibraryScope
    {
        public string schema, name;
        public int fps, captureEveryFrames;
        public float durationSeconds;
        public TrafficLibraryObserver observer;
        public TrafficLibraryWeather weather;
        public TrafficLibraryFastDrones fastDrones;
        public TrafficLibrarySafety safety;
        public DatasetManualEnvironment environmentRequested;
        public TrafficLibrarySchedule captureSchedule;
    }

    [Serializable]
    public sealed class TrafficLibraryTemplate
    {
        public int width, height;
        public float verticalFovDeg, farClipM, viewHeadingDeg, cameraPitchDeg, observerHeightM;
        public Vector3 origin, observerDeckOffsetM;
        public bool observerDeckCamera;
    }

    [Serializable]
    public sealed class TrafficLibraryCapability
    {
        public string model, category, domain, speedUnit, evidence, role;
        public float lengthM, beamM, heightM, bufferM, maxSpeedMps, maxAltitudeM, speedMax;
    }

    [Serializable]
    public sealed class TrafficLibraryCatalogue
    {
        public string schema;
        public TrafficLibraryCapability[] assets;
    }

    [Serializable]
    public sealed class TrafficLibraryPlanFlags
    {
        public bool containsUncompiledControlPoints, requiresNativeAdapter;
        public TrafficLibrarySchedule captureSchedule;
    }

    // Fixed artifact names only. Hashes attest integrity/provenance, not authorship,
    // navigation certification, a native render or an independent C# safety audit.
    public static class DatasetTrafficLibraryImportContract
    {
        public const int MaximumFileBytes = 4 * 1024 * 1024, MaximumBundleBytes = 16 * 1024 * 1024;
        public static readonly string[] Allowed =
        {
            "plan.json",
            "scope.snapshot.json",
            "catalogue.snapshot.json",
            "unity-template.json",
            "safety-report.json",
            "agent-messages.json",
            "scenario.yaml",
            "instructions.txt"
        };
        public static readonly string[] Required =
        {
            "plan.json",
            "scope.snapshot.json",
            "catalogue.snapshot.json",
            "unity-template.json",
            "safety-report.json",
            "agent-messages.json"
        };
        public static bool Hex(string value, int length) => value != null && value.Length == length && value.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f');
        public static bool Id(string value) => value != null && Regex.IsMatch(value, @"\A[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\z");
        public static byte[] Read(string path, int maximum = MaximumFileBytes)
        {
            DatasetDashboardImportContract.NoLinks(path);
            var info = new FileInfo(path);
            if (!info.Exists || info.Length < 2 || info.Length > maximum)
                throw new InvalidDataException("Missing or oversized library artifact.");
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (stream.Length < 2 || stream.Length > maximum)
                    throw new InvalidDataException("Library artifact grew beyond its budget.");
                byte[] data = new byte[(int)stream.Length];
                int offset = 0;
                while (offset < data.Length)
                {
                    int count = stream.Read(data, offset, data.Length - offset);
                    if (count == 0)
                        throw new InvalidDataException("Library artifact was truncated.");
                    offset += count;
                }

                if (stream.ReadByte() != -1)
                    throw new InvalidDataException("Library artifact grew beyond its budget.");
                DatasetDashboardImportContract.NoLinks(path);
                return data;
            }
        }

        public static Dictionary<string, string> Verify(string file, out TrafficLibraryManifest manifest)
        {
            file = Path.GetFullPath(file);
            if (Path.GetFileName(file) != "manifest.json")
                throw new InvalidDataException("Select the extracted library manifest.json.");
            string manifestJson = new UTF8Encoding(false, true).GetString(Read(file));
            manifest = JsonUtility.FromJson<TrafficLibraryManifest>(manifestJson);
            var record = manifest?.record;
            if (manifest?.schema != "lotusim-traffic-library-bundle-1" || manifest.applied || record == null || !Id(record.id) || !record.ready || record.applied || record.auditStatus != "approved" || !Hex(record.planSha256, 64) || !Hex(record.contextSha256, 64) || manifest.artifacts == null || manifest.artifacts.Length < Required.Length || manifest.artifacts.Length > Allowed.Length)
                throw new InvalidDataException("This bundle is not an approved, unapplied library export with an artifact inventory. Export it again from the dashboard.");
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            long total = 0;
            foreach (var item in manifest.artifacts)
            {
                if (item == null || !Allowed.Contains(item.name) || values.ContainsKey(item.name) || !Hex(item.sha256, 64) || item.bytes < 2 || item.bytes > MaximumFileBytes)
                    throw new InvalidDataException("Unsafe library artifact inventory.");
                total = checked(total + item.bytes);
                if (total > MaximumBundleBytes)
                    throw new InvalidDataException("Library bundle exceeds its byte budget.");
                byte[] data = Read(DatasetDashboardImportContract.SafeChild(Path.GetDirectoryName(file), item.name));
                if (data.LongLength != item.bytes || DatasetDashboardImportContract.Hash(data) != item.sha256)
                    throw new InvalidDataException("Library artifact SHA/length mismatch: " + item.name);
                values.Add(item.name, new UTF8Encoding(false, true).GetString(data));
            }

            if (Required.Any(name => !values.ContainsKey(name)))
                throw new InvalidDataException("Incomplete library export.");
            if (DatasetTrafficPlanBundle.Hash(values["plan.json"]) != record.planSha256)
                throw new InvalidDataException("Plan SHA differs from its library record.");
            var audit = JsonUtility.FromJson<TrafficLibraryAudit>(values["safety-report.json"]);
            if (audit == null || !audit.approved || !audit.continuousSafetyApproved || audit.fullColregCompliance || !audit.notCertified || audit.planSha256 != record.planSha256 || audit.contextSha256 != record.contextSha256 || !Hex(audit.inputSha256, 64))
                throw new InvalidDataException("Audit is not approved/bound to this exact plan and context. No COLREG certificate is inferred.");
            values.Add("manifest.json", manifestJson);
            return values;
        }

        public static void ValidateFrames(int[] frames, int fps, float duration)
        {
            if (fps < 1 || fps > 60 || !DatasetManualEnvironment.Range(duration, 4, 600) || frames == null || frames.Length < 1 || frames.Length > 2000)
                throw new InvalidDataException("Expected 1–2000 pinned capture frames and a bounded source timeline.");
            int count = Mathf.CeilToInt(fps * duration);
            if (frames.Where((frame, index) => frame < 0 || frame >= count || index > 0 && frame <= frames[index - 1]).Any())
                throw new InvalidDataException("Capture frames must be unique, sorted and inside the source timeline.");
        }
    }
}
