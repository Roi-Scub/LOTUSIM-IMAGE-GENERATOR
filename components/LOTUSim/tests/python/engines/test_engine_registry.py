#!/usr/bin/env python3
"""Fixture-only neutral-engine profiles, contracts, pinning and storage safety."""

import json
import math
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from lotusim_image_generator.campaigns.settings import CampaignStore, CampaignValidationError
from lotusim_image_generator.engines.registry import (
    EngineRegistry,
    EngineRegistryError,
    MAX_CUSTOM,
    MAX_PROFILE,
    PROFILE_SCHEMA,
    custom_id,
)
from lotusim_image_generator.engines.status import observe_preparation


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-neutral-engine-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core = self.root / 'core'
        self.core.mkdir()
        self.registry = EngineRegistry(self.core)
        self.profile = self.core / 'artifacts/render-engines/profile.json'
        catalogue = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalogue.parent.mkdir(parents=True)
        catalogue.write_text(
            json.dumps(
                {
                    'schema': 'lotusim-traffic-catalogue-1',
                    'assets': [
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
                            'license': 'Fixture declared licence',
                        }
                    ],
                }
            )
        )

    def generic_store(self, engine='godot'):
        self.registry.select({'engine': engine})
        return CampaignStore(self.core), None

    def test_default_catalogue_is_declarative_and_does_not_write(self):
        result = self.registry.catalog()
        self.assertEqual(result['schema'], 'lotusim-engine-catalog-1')
        self.assertEqual(result['selectedEngine']['id'], 'unity')
        self.assertEqual(
            [item['id'] for item in result['engines']],
            ['unity', 'unreal', 'godot', 'blender', 'o3de'],
        )
        self.assertFalse((self.core / 'artifacts').exists())
        self.assertFalse(any(item['nativeValidated'] for item in result['engines']))

    def test_generic_capabilities_never_promise_a_native_adapter(self):
        for engine in ('godot', 'blender', 'o3de'):
            item = self.registry.get(engine)
            self.assertEqual(item['mode'], 'neutral_contract_only')
            self.assertTrue(item['preparationAvailable'])
            self.assertTrue(item['capabilities']['neutralExport'])
            for capability in ('rgbCapture', 'annotations', 'livePoses', 'waves'):
                self.assertFalse(item['capabilities'][capability])

    def test_selection_persists_without_unity_and_drives_new_defaults(self):
        result = self.registry.select({'engine': 'godot'})
        self.assertEqual(result['selectedEngine']['id'], 'godot')
        self.assertEqual(EngineRegistry(self.core).selection()['id'], 'godot')
        store = CampaignStore(self.core)
        self.assertIsNone(store.unity_root)
        self.assertEqual(store.defaults()['engine'], 'godot')
        self.assertEqual(store.catalog()['selectedEngine']['id'], 'godot')
        self.assertEqual(len(store.catalog()['scenes']), 5)

    def test_custom_name_has_stable_safe_id_and_is_reusable(self):
        first = self.registry.select({'engine': 'custom', 'name': '  Mon   Moteur 3D '})
        selected = first['selectedEngine']
        self.assertRegex(selected['id'], r'^custom-[0-9a-f]{16}$')
        self.assertEqual(selected['label'], 'Mon Moteur 3D')
        self.assertEqual(selected['adapterId'], 'neutral')
        self.assertEqual(custom_id('mon moteur 3d'), selected['id'])
        again = self.registry.select({'engine': 'custom', 'name': 'MON MOTEUR 3D'})
        self.assertEqual(again['selectedEngine']['id'], selected['id'])
        self.assertEqual(len(again['engines']), 6)
        self.assertEqual(
            self.registry.select({'engine': selected['id']})['selectedEngine']['id'], selected['id']
        )

    def test_custom_unicode_label_normalization_never_becomes_a_path(self):
        selected = self.registry.select({'engine': 'custom', 'name': 'Écume ３D'})['selectedEngine']
        self.assertEqual(selected['label'], 'Écume 3D')
        self.assertNotIn('É', selected['id'])
        self.assertEqual(selected['id'], custom_id('écume 3d'))

    def test_custom_limit_is_bounded_and_preserves_previous_profile(self):
        for index in range(MAX_CUSTOM):
            self.registry.select({'engine': 'custom', 'name': 'Engine ' + str(index)})
        before = self.profile.read_bytes()
        with self.assertRaises(EngineRegistryError):
            self.registry.select({'engine': 'custom', 'name': 'Too many'})
        self.assertEqual(self.profile.read_bytes(), before)

    def test_unknown_id_is_not_implicitly_registered_or_dispatched(self):
        for identifier in (
            'arbitrary',
            'custom-' + '0' * 16,
            '../godot',
            '/tmp/engine.py',
            None,
            ['godot'],
        ):
            with self.subTest(identifier=identifier), self.assertRaises(EngineRegistryError):
                self.registry.get(identifier)

    def test_selection_payload_cannot_register_paths_modules_commands_or_options(self):
        for payload in (
            {'engine': 'godot', 'module': 'evil'},
            {'engine': 'godot', 'path': '/tmp/x'},
            {'engine': 'custom', 'name': 'Test', 'command': 'touch file'},
            {'engine': 'custom'},
            {'engine': 4},
            [],
            {'engine': 'unknown'},
        ):
            with self.subTest(payload=payload), self.assertRaises(EngineRegistryError):
                self.registry.select(payload)

    def test_custom_name_validation_rejects_code_path_and_excess_length(self):
        for value in (
            '../native.py',
            '/tmp/native',
            'a;b',
            'x$(cmd)',
            '<script>',
            '',
            '.' * 5,
            'a' * 65,
            None,
        ):
            with self.subTest(value=value), self.assertRaises(EngineRegistryError):
                self.registry.select({'engine': 'custom', 'name': value})

    def test_selection_cannot_overwrite_unrelated_profile_json(self):
        self.profile.parent.mkdir(parents=True)
        self.profile.write_text('{"unrelated":true}')
        before = self.profile.read_bytes()
        with self.assertRaises(EngineRegistryError):
            self.registry.select({'engine': 'godot'})
        self.assertEqual(self.profile.read_bytes(), before)

    def test_profile_json_is_bounded_strict_and_regular(self):
        self.profile.parent.mkdir(parents=True)
        for raw in (b'x' * (MAX_PROFILE + 1), b'{"schema":1,"schema":2}', b'{"schema":NaN}'):
            self.profile.write_bytes(raw)
            with self.subTest(raw=raw[:40]), self.assertRaises(EngineRegistryError):
                self.registry.catalog()

    def test_symlinked_profile_is_neither_followed_nor_overwritten(self):
        self.profile.parent.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.write_text('private')
        self.profile.symlink_to(outside)
        with self.assertRaises((EngineRegistryError, OSError)):
            self.registry.select({'engine': 'godot'})
        self.assertTrue(self.profile.is_symlink())
        self.assertEqual(outside.read_text(), 'private')

    def test_symlinked_profile_directory_cannot_escape(self):
        artifacts = self.core / 'artifacts'
        artifacts.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (artifacts / 'render-engines').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(EngineRegistryError):
            self.registry.select({'engine': 'godot'})
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlinked_lock_cannot_escape(self):
        self.profile.parent.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.write_text('private')
        (self.profile.parent / 'profile.lock').symlink_to(outside)
        with self.assertRaises(EngineRegistryError):
            self.registry.select({'engine': 'godot'})
        self.assertEqual(outside.read_text(), 'private')

    def test_profile_permissions_and_atomic_temp_cleanup(self):
        self.registry.select({'engine': 'godot'})
        self.assertEqual(stat.S_IMODE(self.profile.stat().st_mode), 0o600)
        self.assertFalse(any(path.name.endswith('.tmp') for path in self.profile.parent.iterdir()))

    def test_third_engine_prepares_end_to_end_without_any_unity_project(self):
        store, _ = self.generic_store()
        campaign = store.defaults()
        with patch('subprocess.Popen', side_effect=AssertionError('No engine process allowed')):
            result = store.prepare(campaign)
        files = store.read_bundle(result['id'])
        self.assertEqual(
            set(files),
            {
                'campaign.json',
                'manifest.json',
                'engine-agent.json',
                'scene-contract.json',
                'adapter-requirements.json',
                'engine-instructions.txt',
            },
        )
        self.assertFalse(any(name.endswith(('.cs', '.py', '.uproject')) for name in files))
        self.assertEqual(result['engineActions']['engine'], 'godot')
        self.assertEqual(result['engineActions']['mode'], 'neutral_contract_only')
        self.assertFalse(result['engineActions']['nativeValidated'])
        self.assertFalse(result['engineAgent']['nativeScriptGenerated'])

    def test_custom_engine_prepares_and_is_accepted_by_telemetry(self):
        selected = self.registry.select({'engine': 'custom', 'name': 'Mon moteur'})[
            'selectedEngine'
        ]
        store = CampaignStore(self.core)
        result = store.prepare(store.defaults())
        agent, _ = observe_preparation(self.core)
        self.assertEqual(agent['state'], 'complete')
        self.assertEqual(agent['engine'], selected['id'])
        self.assertEqual(agent['campaignId'], result['id'])
        self.assertFalse(agent['nativeValidated'])

    def test_unknown_campaign_engine_is_invalid_but_registered_custom_is_valid(self):
        store, _ = self.generic_store()
        campaign = store.defaults()
        campaign['engine'] = 'other_engine'
        result = store.validate(campaign)
        self.assertFalse(result['valid'])
        self.assertIn('$.engine', [error['path'] for error in result['errors']])
        selected = self.registry.select({'engine': 'custom', 'name': 'Other Engine'})[
            'selectedEngine'
        ]
        campaign['engine'] = selected['id']
        self.assertTrue(store.validate(campaign)['valid'])

    def test_scene_contract_is_si_enu_factorized_and_has_pinhole_intrinsics(self):
        store, _ = self.generic_store('blender')
        campaign = store.defaults()
        result = store.prepare(campaign)
        contract = json.loads(store.read_prepared(result['id'], 'scene-contract.json'))
        self.assertEqual(contract['schema'], 'lotusim-neutral-scene-contract-1')
        self.assertEqual(contract['coordinates']['world'], 'ENU')
        self.assertEqual(contract['coordinates']['units'], 'SI')
        self.assertEqual(contract['sampling']['sampleCount'], 10)
        self.assertEqual(sum(block['frameCount'] for block in contract['blocks']), 10)
        self.assertEqual([block['firstFrameIndex'] for block in contract['blocks']], [0, 3, 8])
        self.assertEqual(contract['classes'], [{'id': 1, 'name': 'buoy'}])
        self.assertEqual(contract['models'][0]['dimensionsM']['heightM'], 3)
        self.assertEqual(
            contract['models'][0]['sourceBinding']['license'], 'Fixture declared licence'
        )
        self.assertEqual(contract['models'][0]['sourceBinding']['uri'], 'model://buoy')
        fy = 720 / (2 * math.tan(math.radians(60) / 2))
        self.assertAlmostEqual(contract['camera']['intrinsicsPx']['fy'], fy)
        self.assertTrue(contract['observerRequested']['excludeFromAnnotations'])
        self.assertFalse(contract['annotationContract']['automaticAnnotationsProduced'])

    def test_scene_contract_instance_ids_are_stable_and_block_unique(self):
        store, _ = self.generic_store('o3de')
        first = store.prepare(store.defaults())
        second = store.prepare(store.defaults())
        contracts = [
            json.loads(store.read_prepared(item['id'], 'scene-contract.json'))
            for item in (first, second)
        ]
        ids = [
            [
                key
                for block in contract['blocks']
                for row in block['objects']
                for key in row['instanceIds']
            ]
            for contract in contracts
        ]
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(ids[0]), len(set(ids[0])))

    def test_generic_manifest_pins_geometry_not_unity_prefab_ack(self):
        store, _ = self.generic_store()
        record = {
            'model': 'import_' + 'a' * 32,
            'category': 'buoy',
            'domain': 'moored',
            'heightM': 2,
            'maxSpeedMps': 0,
            'altitudeM': [0, 0],
            'classId': 1,
            'importId': 'import-fixture',
            'revisionSha256': 'a' * 64,
            'requestSha256': 'b' * 64,
            'geometrySha256': 'c' * 64,
            'neutralSource': {'root': 'core', 'obj': 'artifacts/fixed/gazebo.obj', 'files': []},
        }
        campaign = store.defaults()
        for block in campaign['blocks']:
            block['objects'][0]['model'] = record['model']
        with (
            patch(
                'lotusim_image_generator.assets.integration.neutral_imports', return_value=[record]
            ),
            patch(
                'lotusim_image_generator.assets.integration.ready_imports',
                side_effect=AssertionError('Unity ACK must not gate neutral preparation'),
            ),
        ):
            result = store.prepare(campaign)
        self.assertEqual(result['manifest']['importedAssetRevisions'], [])
        self.assertEqual(
            result['manifest']['neutralSourceRevisions'][0]['geometrySha256'], 'c' * 64
        )
        self.assertNotIn('prefabGuid', result['manifest']['neutralSourceRevisions'][0])
        contract = json.loads(store.read_prepared(result['id'], 'scene-contract.json'))
        self.assertEqual(
            contract['models'][0]['sourceBinding']['preparedSource'], record['neutralSource']
        )

    def test_real_converted_bundle_prepares_for_third_engine_without_unity_ack(self):
        from tests.python.assets.test_mesh_integration import IntegrationTests

        fixture = IntegrationTests(methodName='runTest')
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.prepare()
        catalog_path = fixture.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalog_path.write_bytes(
            (self.core / 'assets/scenarios/catalogs/traffic_assets.json').read_bytes()
        )
        EngineRegistry(fixture.core).select({'engine': 'godot'})
        store = CampaignStore(fixture.core)
        imported = next(item for item in store.catalog()['assets'] if item.get('importId'))
        campaign = store.defaults()
        for block in campaign['blocks']:
            block['objects'][0]['model'] = imported['model']
        result = store.prepare(campaign)
        self.assertEqual(
            result['manifest']['neutralSourceRevisions'][0]['geometrySha256'],
            imported['geometrySha256'],
        )
        self.assertFalse((fixture.folder / 'unity-result.json').exists())
        self.assertFalse((fixture.unity / 'Assets').exists())
        self.assertIsNone(store.unity_root)

    def test_generic_downloads_require_exact_inventory_and_intact_hashes(self):
        store, _ = self.generic_store()
        result = store.prepare(store.defaults())
        path = (
            self.core
            / 'artifacts/campaign-settings/prepared'
            / result['id']
            / 'adapter-requirements.json'
        )
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            store.read_bundle(result['id'])
        self.assertEqual(observe_preparation(self.core)[0]['state'], 'failed')

    def test_legacy_unity_inventory_without_common_contract_is_still_readable(self):
        from lotusim_image_generator.campaigns.settings import ADAPTER_PATH

        unity = self.root / 'unity'
        adapter = unity / ADAPTER_PATH
        adapter.parent.mkdir(parents=True)
        adapter.write_text('// fixture adapter')
        store = CampaignStore(self.core, unity)
        result = store.prepare(store.defaults())
        folder = self.core / 'artifacts/campaign-settings/prepared' / result['id']
        manifest = json.loads((folder / 'manifest.json').read_bytes())
        manifest['artifacts'] = [
            row for row in manifest['artifacts'] if row['name'] != 'scene-contract.json'
        ]
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        (folder / 'scene-contract.json').unlink()
        self.assertIn('scene_unity.cs', store.read_bundle(result['id']))
        self.assertEqual(observe_preparation(self.core)[0]['state'], 'complete')


if __name__ == '__main__':
    unittest.main()
