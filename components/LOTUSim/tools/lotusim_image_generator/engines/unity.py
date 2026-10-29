"""Trusted optional Unity Editor bootstrap; existing manual import is unchanged."""

import json
from pathlib import Path
from lotusim_image_generator.engines.registry import UNITY_ADAPTER, UNITY_SCENE


def prepare_unity(campaign, identifier, campaign_sha, core_root, unity_root=None, catalogue=None):
    compact = identifier.replace('-', '')
    path = Path(core_root) / 'artifacts/campaign-settings/prepared' / identifier / 'manifest.json'
    literal = json.dumps(str(path), ensure_ascii=True)
    script = '''// Generated trusted template. Optional; never automatically installed or run.
#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using Lotusim.EditorTools;
public static class LOTUSimPrepared_%s
{
    [MenuItem("LOTUSim/Prepared campaigns/Import %s")]
    public static void Import()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode)
            throw new InvalidOperationException("Leave Play before importing a prepared campaign.");
        string file = %s;
        if (!File.Exists(file)) file = EditorUtility.OpenFilePanel("Select manifest.json for %s", "", "json");
        if (string.IsNullOrEmpty(file)) return;
        if (Path.GetFileName(file) != "manifest.json" || new DirectoryInfo(Path.GetDirectoryName(Path.GetFullPath(file))).Name != "%s")
            throw new InvalidDataException("Select this prepared campaign's manifest.json.");
        DatasetManualCampaignBuilder.ImportManifest(file, true);
    }
}
#endif
''' % (compact, identifier, literal, identifier, identifier)
    instructions = [
        'Keep the existing Unity project open, outside Play. No engine or service was started by preparation.',
        'Use LOTUSim > Dataset > Manual campaigns > Import prepared campaign and select this package\'s manifest.json.',
        'Alternatively, copy scene_unity.cs into the project Assets/Editor folder, wait for compilation, then invoke its explicit LOTUSim > Prepared campaigns menu. This is optional.',
        'The existing adapter creates a new scene and LOTUSim scenario files. It checks campaign and imported-prefab revision hashes.',
        'Open the new scene and enter Play explicitly only when your existing LOTUSim/ROS services are ready. Existing annotations and capture workflow remain in use.',
        'Check the generated RGB images and annotation quality; preparation and executable detection do not prove native rendering or calibrated weather.',
    ]
    plan = {
        'schema': 'lotusim-engine-scene-plan-1',
        'engine': 'unity',
        'id': identifier,
        'campaignSha256': campaign_sha,
        'scenePath': UNITY_SCENE.replace('<id>', identifier),
        'adapterPath': UNITY_ADAPTER,
        'entryPoint': 'DatasetManualCampaignBuilder.ImportManifest',
        'sampleCount': campaign['totalImages'],
        'imageSemantics': 'independent_seeded_samples',
        'sourceOfTruth': 'campaign.json',
        'automaticExecution': False,
        'environmentApplication': 'existing_manual_campaign_adapter',
        'nativeValidated': False,
    }
    return {
        'files': {
            'scene_unity.cs': script.encode('utf-8'),
            'scene-plan.json': (
                json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
            ).encode(),
            'unity-instructions.txt': ('\n\n'.join(instructions) + '\n').encode('utf-8'),
        },
        'manifest': {
            'scenePath': plan['scenePath'],
            'adapterPath': UNITY_ADAPTER,
            'instructions': instructions,
            'runtimeRequirements': [
                'Existing LOTUSim Unity project and manual campaign adapter',
                'Existing connected LOTUSim/ROS workflow for capture',
            ],
            'limitations': ['No native execution or rendering was performed during preparation.'],
            'nativeValidated': False,
        },
    }
