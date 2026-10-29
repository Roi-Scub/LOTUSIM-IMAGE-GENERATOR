#!/usr/bin/env python3
"""Offline engine preparation contract checks; no editor, network or services."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lotusim_image_generator.campaigns.settings import (
    ADAPTER_PATH,
    CampaignSecurityError,
    CampaignStore,
    CampaignValidationError,
    SCENE_PATH,
)
from lotusim_image_generator.engines import preparation as agents

ASSETS = [
    {
        'model': 'buoy',
        'category': 'buoy',
        'domain': 'moored',
        'heightM': 3,
        'lengthM': 2,
        'beamM': 2,
        'draftM': 0.5,
        'maxSpeedMps': 0,
        'altitudeM': [0, 0],
        'evidence': 'test_assumption',
    }
]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-engines-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core, self.unity = self.root / 'core', self.root / 'unity'
        catalog = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalog.parent.mkdir(parents=True)
        catalog.write_text(json.dumps({'schema': 'lotusim-traffic-catalogue-1', 'assets': ASSETS}))
        sdf = self.core / 'assets/models/buoy/model.sdf'
        sdf.parent.mkdir(parents=True)
        sdf.write_text(
            '<sdf version="1.10"><model name="buoy"><link name="base">'
            '<visual name="body"><geometry><cylinder><radius>1</radius>'
            '<length>3</length></cylinder></geometry></visual></link></model></sdf>'
        )
        adapter = self.unity / ADAPTER_PATH
        adapter.parent.mkdir(parents=True)
        adapter.write_text('// fixture installed adapter')
        self.store = CampaignStore(self.core, self.unity)
        self.plan = self.store.defaults()

    def prepare(self):
        with patch.object(agents, '_runtime_candidates', return_value=[]):
            return self.store.prepare(self.plan)

    def location(self, identifier):
        return self.core / 'artifacts/campaign-settings/prepared' / identifier

    def edit_manifest(self, identifier, mutate):
        path = self.location(identifier) / 'manifest.json'
        data = json.loads(path.read_bytes())
        mutate(data)
        path.write_text(json.dumps(data))

    def test_preparation_and_runtime_are_separate_capabilities(self):
        with patch.object(agents, '_runtime_candidates', return_value=[]):
            catalog = self.store.catalog()
        for engine in catalog['engines']:
            self.assertTrue(engine['preparationAvailable'])
            self.assertTrue(engine['available'])
            self.assertFalse(engine['runtimeDetected'])
            self.assertFalse(engine['nativeValidated'])
            self.assertEqual(engine['validationState'], 'not_native_validated')
        self.assertEqual(
            {entry['engine'] for entry in catalog['scenes']},
            {'unity', 'unreal', 'godot', 'blender', 'o3de'},
        )

    def test_detection_only_checks_executable_file_presence(self):
        editor = self.root / 'UnrealEditor'
        editor.write_bytes(b'not executed')
        with (
            patch.object(agents, '_runtime_candidates', return_value=[editor]),
            patch('subprocess.Popen', side_effect=AssertionError('Must not start engine')),
        ):
            for engine in self.store._engines():
                self.assertTrue(engine['runtimeDetected'])
                self.assertFalse(engine['nativeValidated'])

    def test_epic_launcher_is_not_an_unreal_runtime(self):
        with patch.object(
            Path,
            'iterdir',
            return_value=iter([Path('/example/EpicGamesLauncher.app'), Path('/example/Launcher')]),
        ):
            candidates = agents._runtime_candidates('unreal', self.unity)
        self.assertFalse(any('Launcher' in str(path) for path in candidates))

    def test_missing_unity_adapter_does_not_disable_unreal_preparation(self):
        (self.unity / ADAPTER_PATH).unlink()
        with self.assertRaises(CampaignValidationError):
            self.prepare()
        self.plan['engine'] = 'unreal'
        result = self.prepare()
        self.assertEqual(result['engineActions']['engine'], 'unreal')

    def test_unity_preserves_existing_manifest_contract_and_adds_inert_script(self):
        result = self.prepare()
        manifest, actions = result['manifest'], result['engineActions']
        self.assertEqual(manifest['schema'], 'lotusim-manual-campaign-1')
        self.assertEqual(manifest['relativeCampaignFile'], 'campaign.json')
        self.assertEqual(manifest['provenance']['scenePath'], SCENE_PATH)
        self.assertEqual(manifest['provenance']['adapterPath'], ADAPTER_PATH)
        self.assertEqual(actions['engine'], 'unity')
        self.assertEqual(actions['preparationState'], 'prepared')
        self.assertFalse(actions['nativeValidated'])
        self.assertFalse(actions['runtimeDetected'])
        script = self.store.read_prepared(result['id'], 'scene_unity.cs').decode()
        self.assertIn(
            'public static class LOTUSimPrepared_' + result['id'].replace('-', ''), script
        )
        self.assertIn('DatasetManualCampaignBuilder.ImportManifest(file, true);', script)
        self.assertIn('EditorApplication.isPlayingOrWillChangePlaymode', script)
        for automatic in (
            'InitializeOnLoad',
            'InitializeOnLoadMethod',
            'ExecuteInEditMode',
            'EditorApplication.isPlaying =',
            'Process.Start',
        ):
            self.assertNotIn(automatic, script)
        self.assertEqual(script.count('{'), script.count('}'))
        self.assertEqual(script.count('#if UNITY_EDITOR'), 1)
        self.assertEqual(script.count('#endif'), 1)

    def test_unity_generated_path_is_a_safely_escaped_csharp_literal(self):
        value = agents._unity(
            self.plan,
            'd58d5558-cbe2-4e59-87d4-949a12ff076f',
            'a' * 64,
            Path('/tmp/a"b\\c\n\u2028d'),
        )
        script = value['files']['scene_unity.cs'].decode()
        line = next(line for line in script.splitlines() if 'string file =' in line)
        self.assertIn('\\"', line)
        self.assertIn('\\\\', line)
        self.assertIn('\\n', line)
        self.assertIn('\\u2028', line)

    def test_traces_describe_software_roles_not_native_or_llm_success(self):
        result = self.prepare()
        report = json.loads(self.store.read_prepared(result['id'], 'engine-agent.json'))
        self.assertEqual(report, result['engineAgent'])
        self.assertEqual(report['kind'], 'deterministic_role_pipeline')
        self.assertEqual(
            [step['role'] for step in report['traces']],
            ['planner', 'scene_script_builder', 'validator'],
        )
        self.assertTrue(all(step['state'] == 'completed' for step in report['traces']))
        self.assertFalse(report['nativeValidated'])
        self.assertTrue(any('not autonomous LLM' in text for text in report['limitations']))

    def test_bundle_inventory_pins_every_artifact_and_excludes_manifest(self):
        result = self.prepare()
        files = self.store.read_bundle(result['id'])
        inventory = result['manifest']['artifacts']
        self.assertEqual(set(files), {row['name'] for row in inventory} | {'manifest.json'})
        self.assertNotIn('manifest.json', {row['name'] for row in inventory})
        for row in inventory:
            self.assertEqual(row['bytes'], len(files[row['name']]))
            self.assertEqual(row['sha256'], hashlib.sha256(files[row['name']]).hexdigest())
        self.assertEqual(len(result['engineActions']['files']), len(inventory))

    def test_artifact_tampering_invalidates_download_and_bundle(self):
        result = self.prepare()
        (self.location(result['id']) / 'scene_unity.cs').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.store.read_prepared(result['id'], 'scene_unity.cs')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.store.read_bundle(result['id'])

    def test_flat_whitelist_and_per_package_inventory_are_required(self):
        result = self.prepare()
        for name in (
            '../scene_unity.cs',
            '/tmp/secret',
            'other.cs',
            'scene_unity.cs/child',
            'scene_unreal.py',
        ):
            with self.subTest(name=name), self.assertRaises(CampaignSecurityError):
                self.store.read_prepared(result['id'], name)

    def test_malformed_inventory_cannot_enable_arbitrary_or_duplicate_files(self):
        for bad in (
            [{'name': '../secret', 'sha256': 'a' * 64, 'bytes': 1}],
            [{'name': [], 'sha256': 'a' * 64, 'bytes': 1}],
            [{'name': 'campaign.json', 'sha256': 'a' * 64, 'bytes': True}],
            [{'name': 'campaign.json', 'sha256': 'a' * 64, 'bytes': 1}] * 2,
        ):
            with self.subTest(inventory=bad):
                result = self.prepare()
                self.edit_manifest(result['id'], lambda value: value.update(artifacts=bad))
                with self.assertRaises(ValueError):
                    self.store.read_bundle(result['id'])

    def test_missing_artifact_or_symlink_refuses_bundle(self):
        result = self.prepare()
        path = self.location(result['id']) / 'scene_unity.cs'
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.store.read_bundle(result['id'])
        outside = self.root / 'outside'
        outside.write_text('private')
        path.symlink_to(outside)
        with self.assertRaises(CampaignSecurityError):
            self.store.read_bundle(result['id'])

    def test_old_two_file_packages_remain_readable(self):
        result = self.prepare()
        self.edit_manifest(result['id'], lambda data: data.pop('artifacts'))
        files = self.store.read_bundle(result['id'])
        self.assertEqual(set(files), {'campaign.json', 'manifest.json'})
        self.assertEqual(
            self.store.read_prepared(result['id'], 'campaign.json'), files['campaign.json']
        )

    def test_preparation_is_immutable_and_does_not_execute_scripts(self):
        with patch('subprocess.Popen', side_effect=AssertionError('No worker or engine allowed')):
            first = self.prepare()
            before = self.store.read_bundle(first['id'])
            self.plan['blocks'][0]['environment']['waveHeightM'] = 3
            second = self.prepare()
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.store.read_bundle(first['id']), before)
        self.assertNotEqual(
            first['manifest']['campaignSha256'], second['manifest']['campaignSha256']
        )

    def test_unreal_has_engine_specific_provenance_and_never_unity_script(self):
        self.plan['engine'] = 'unreal'
        result = self.prepare()
        files = self.store.read_bundle(result['id'])
        self.assertTrue(
            {
                'scene_unreal.py',
                'scene-plan.json',
                'LOTUSimPrepared.uproject',
                'unreal-instructions.txt',
                'engine-agent.json',
            }
            <= set(files)
        )
        self.assertNotIn('scene_unity.cs', files)
        self.assertEqual(result['manifest']['provenance']['renderEngine'], 'unreal')
        self.assertEqual(
            result['manifest']['provenance']['adapterPath'], 'tools/unreal_scene_adapter.py'
        )
        self.assertTrue(result['manifest']['provenance']['scenePath'].startswith('/Game/LOTUSim/'))
        self.assertFalse(result['engineActions']['nativeValidated'])

    def test_unsafe_adapter_outputs_are_refused_before_prepared_directory(self):
        self.plan['engine'] = 'unreal'
        for files in (
            {'../escape.py': b'x'},
            {'scene_unreal.py': b'x' * 1_048_577},
            {'scene_unreal.py': 'not bytes'},
        ):
            with (
                self.subTest(names=list(files)),
                patch(
                    'lotusim_image_generator.engines.unreal.prepare_unreal',
                    return_value={'files': files, 'manifest': {}},
                ),
            ):
                with self.assertRaises(CampaignValidationError):
                    self.prepare()
        self.assertFalse((self.core / 'artifacts/campaign-settings/prepared').exists())


if __name__ == '__main__':
    unittest.main()
