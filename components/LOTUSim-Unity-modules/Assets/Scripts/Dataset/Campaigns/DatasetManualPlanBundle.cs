using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    public sealed class DatasetManualPlanBundle : ScriptableObject
    {
        [TextArea(2, 6)]
        public string planJson, campaignJson;
        public string contentSha256;
        public DatasetImportedAssetRevision[] importedAssetRevisions = Array.Empty<DatasetImportedAssetRevision>();
        [Serializable]
        sealed class PinManifest
        {
            public DatasetImportedAssetRevision[] pins;
        }

        // Preserve the exact hash of legacy bundles without imported objects.
        public string ComputeHash() => DatasetTrafficPlanBundle.Hash(planJson + "|" + campaignJson + (importedAssetRevisions != null && importedAssetRevisions.Length > 0 ? "|" + JsonUtility.ToJson(new PinManifest { pins = importedAssetRevisions }) : ""));
        public DatasetSequencePlan Read(DatasetSequenceConfig config)
        {
            if (contentSha256 != ComputeHash())
                throw new InvalidOperationException("Manual image plan changed; reimport its prepared campaign.");
            foreach (var pin in importedAssetRevisions ?? Array.Empty<DatasetImportedAssetRevision>())
            {
                if (pin == null || !DatasetImportedAssetRegistry.ModelKey(pin.model))
                    throw new InvalidOperationException("Invalid imported asset revision pin.");
                var choices = config.classes.SelectMany(c => new[] { c.prefab }.Concat(c.prefabVariants ?? Array.Empty<GameObject>())).Where(p => p != null && p.name == pin.model).Distinct().ToArray();
                var marker = choices.Length == 1 ? choices[0].GetComponent<DatasetImportedAsset>() : null;
                if (marker == null || marker.model != pin.model || marker.requestSha256 != pin.requestSha256 || marker.revisionSha256 != pin.revisionSha256 || !DatasetImportedAssetRegistry.Matches(pin.model, marker.category))
                    throw new InvalidOperationException("Imported model changed after campaign preparation: " + pin.model + ". Prepare and import a new campaign revision.");
            }

            var p = JsonUtility.FromJson<DatasetSequencePlan>(planJson);
            if (p?.schema != "lotusim-unity-encounters-1" || p.manual?.schema != "lotusim-manual-image-1" || p.seed != config.seed || p.traffic != null || !p.manual.independentImage || p.manual.continuousVideo || p.manual.environment == null || p.sea == null || p.light == null || p.events == null || p.events.Length < 1 || p.events.Length > 40 || p.maxActive != p.events.Length || p.manual.placements?.Length != p.events.Length || p.captureFrames == null || !p.captureFrames.SequenceEqual(new[] { 0 }) || !p.captureFrames.SequenceEqual(config.captureFrames))
                throw new InvalidOperationException("Invalid manual independent-image plan.");
            p.manual.environment.Validate();
            if (p.events.Select(e => e.instance).Distinct().Count() != p.events.Length || p.events.Select(e => e.trackId).Distinct().Count() != p.events.Length)
                throw new InvalidOperationException("Duplicate manual image identities.");
            foreach (var e in p.events)
            {
                if (e.classIndex < 0 || e.classIndex >= config.classes.Length || config.classes[e.classIndex].category != e.category || e.trackId < 1 || e.startSeconds != 0 || Mathf.Abs(e.endSeconds - config.durationSeconds) > .001f || e.centerSeconds != 0 || e.boundedTurn || e.yawRateDegS != 0 || !Finite(e.centerPosition) || !Finite(e.velocity) || e.velocity.y != 0 || e.velocity.magnitude > 350 || e.centerPosition.y < 0 || e.centerPosition.y > 15000 || Mathf.Abs(e.centerPosition.x) > 100000 || Mathf.Abs(e.centerPosition.z) > 100000 || DatasetBoatVariants.Resolve(config.classes[e.classIndex], e) == null)
                    throw new InvalidOperationException("Invalid manual object placement: " + e.instance);
            }

            foreach (var c in config.classes)
                if (p.events.Count(e => e.category == c.category) != c.count)
                    throw new InvalidOperationException("Manual image category counts differ from its plan.");
            return p;
        }

        static bool Finite(Vector3 v) => DatasetManualEnvironment.Range(v.x, -100000, 100000) && DatasetManualEnvironment.Range(v.y, -100000, 100000) && DatasetManualEnvironment.Range(v.z, -100000, 100000);
    }
}
