using System;
using System.Collections;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace Lotusim.Dataset
{
    public sealed class DatasetManualCampaignAsset : ScriptableObject
    {
        public string campaignId,campaignJson,campaignSha256,preparedManifestJson;
        public DatasetSequenceConfig[] jobs;
        public string[] scenarioFiles;
        public void Validate()
        {
            if(string.IsNullOrEmpty(campaignId)||string.IsNullOrEmpty(preparedManifestJson)||campaignSha256!=DatasetTrafficPlanBundle.Hash(campaignJson)||jobs==null||jobs.Length==0||
                jobs.Length>2000||scenarioFiles?.Length!=jobs.Length||jobs.Any(c=>c==null||c.manualPlan==null)||
                jobs.Distinct().Count()!=jobs.Length||scenarioFiles.Any(s=>s!=Path.GetFileName(s)||!s.EndsWith(".yaml",StringComparison.Ordinal)))
                throw new InvalidOperationException("Invalid/stale manual campaign asset; import the prepared campaign again.");
            foreach(var c in jobs) {c.Validate();var p=c.MakePlan();if(c.ImageCount!=1||p.manual.campaignId!=campaignId||p.manual.campaignSha256!=campaignSha256)throw new InvalidOperationException("A campaign job belongs to another manifest.");}
        }
    }
}
