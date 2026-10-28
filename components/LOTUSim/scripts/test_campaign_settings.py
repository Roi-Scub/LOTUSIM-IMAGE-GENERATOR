#!/usr/bin/env python3
"""Standard-library regression and file-safety checks for manual settings."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from campaign_settings import (ADAPTER_PATH, CampaignSecurityError, CampaignStore,
                               CampaignValidationError, MAX_JSON_BYTES, load_json_bytes)


ASSETS = [
    {'model': 'buoy', 'category': 'buoy', 'domain': 'moored', 'heightM': 3,
     'maxSpeedMps': 0, 'altitudeM': [0, 0], 'evidence': 'generic_assumption'},
    {'model': 'buoy_navigation_ozzy', 'category': 'buoy', 'domain': 'moored', 'heightM': 2.5,
     'maxSpeedMps': 0, 'altitudeM': [0, 0], 'evidence': 'generic_assumption'},
    {'model': 'sailboat', 'category': 'sailboat', 'domain': 'sea', 'heightM': 18,
     'maxSpeedMps': 4.5, 'altitudeM': [0, 0], 'evidence': 'generic_assumption'},
    {'model': 'small_drone', 'category': 'drone', 'domain': 'air', 'heightM': 0.3,
     'maxSpeedMps': 15, 'maxAltitudeM': 120, 'maxWindMps': 10,
     'altitudeM': [60, 100], 'evidence': 'reference_class_drone'},
]


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-settings-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.core = self.root / 'core'
        self.unity = self.root / 'unity'
        catalog = self.core / 'assets/scenarios/catalogs/traffic_assets.json'
        catalog.parent.mkdir(parents=True)
        catalog.write_text(json.dumps({'schema': 'lotusim-traffic-catalogue-1',
                                       'notes': 'Test catalogue assumptions', 'assets': ASSETS}))
        adapter = self.unity / ADAPTER_PATH
        adapter.parent.mkdir(parents=True)
        adapter.write_text('// installed test adapter marker\n')
        self.store = CampaignStore(self.core, self.unity)
        self.plan = self.store.defaults()

    def first(self, plan=None):
        return (plan or self.plan)['blocks'][0]['objects'][0]

    def paths(self, plan=None):
        validation = self.store.validate(plan or self.plan)
        self.assertFalse(validation['valid'])
        self.assertIsNone(validation['campaign'])
        return [error['path'] for error in validation['errors']]

    def test_default_and_catalogue_are_valid(self):
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['summary']['totalImages'], 10)
        self.assertEqual(result['summary']['allocatedImages'], 10)
        self.assertEqual(result['summary']['objectImageCounts'], {'buoy': 10})
        catalog = self.store.catalog()
        self.assertTrue(catalog['engines'][0]['available'])
        self.assertTrue(catalog['engines'][1]['available'])
        self.assertFalse(catalog['engines'][1]['nativeValidated'])
        self.assertEqual(len(catalog['assets']), len(ASSETS))
        self.assertEqual(catalog['campaigns'], [])

    def test_mixed_allocation_counts_actor_images_not_video_frames(self):
        self.first()['model'] = 'sailboat'
        self.first()['count'] = 3
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'])
        self.assertEqual(result['summary']['objectImageCounts'], {'sailboat': 9, 'buoy': 7})
        self.assertEqual(result['summary']['imageSemantics'], 'independent_seeded_samples')

    def test_allocation_must_match_exactly(self):
        self.plan['totalImages'] += 1
        self.assertIn('$.totalImages', self.paths())
        with self.assertRaises(CampaignValidationError):
            self.store.save(self.plan)
        self.assertFalse((self.core / 'artifacts').exists())

    def test_limits_images_blocks_and_actor_instances(self):
        for total in (0, 2001, 1.5, True):
            plan = copy.deepcopy(self.plan)
            plan['totalImages'] = total
            self.assertIn('$.totalImages', self.paths(plan))
        plan = copy.deepcopy(self.plan)
        plan['blocks'] *= 17
        self.assertIn('$.blocks', self.paths(plan))
        self.first()['count'] = 41
        self.assertIn('$.blocks[0].objects[0].count', self.paths())
        self.first()['count'] = 13
        self.assertIn('$.blocks[0].objects', self.paths())

    def test_category_limit_combines_distinct_models(self):
        row = self.first()
        row['count'] = 7
        other = dict(row, id='other', model='buoy_navigation_ozzy')
        self.plan['blocks'][0]['objects'].append(other)
        self.assertIn('$.blocks[0].objects', self.paths())

    def test_unknown_models_fields_duplicate_ids_and_scalar_shapes(self):
        for field, value, path in (
                ('bogus', True, '$.bogus'), ('schema', 'old', '$.schema'),
                ('engine', 'gazebo', '$.engine'), ('blocks', None, '$.blocks'),
                ('name', '\n', '$.name')):
            plan = copy.deepcopy(self.plan)
            plan[field] = value
            self.assertIn(path, self.paths(plan))
        self.first()['model'] = '../../model'
        self.assertIn('$.blocks[0].objects[0].model', self.paths())
        self.plan = self.store.defaults()
        self.plan['blocks'][1]['id'] = self.plan['blocks'][0]['id']
        self.assertIn('$.blocks[1].id', self.paths())
        self.plan = self.store.defaults()
        self.plan['blocks'][0]['objects'].append(copy.deepcopy(self.first()))
        self.assertIn('$.blocks[0].objects[1].id', self.paths())
        for payload in (None, [], 3, 'test'):
            self.assertFalse(self.store.validate(payload)['valid'])

    def test_nested_unknown_fields_are_rejected(self):
        self.first()['path'] = '/tmp/untrusted'
        self.assertIn('$.blocks[0].objects[0].path', self.paths())
        self.plan = self.store.defaults()
        self.plan['camera']['outputPath'] = '/tmp/untrusted'
        self.assertIn('$.camera.outputPath', self.paths())

    def test_nonfinite_and_overflow_json(self):
        for value in (math.nan, math.inf, -math.inf, 10 ** 400):
            plan = copy.deepcopy(self.plan)
            plan['camera']['verticalFovDeg'] = value
            self.assertFalse(self.store.validate(plan)['valid'])
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}',
                    b'{"x":1,"x":2}', b'\xff', b'{}' + b' ' * MAX_JSON_BYTES):
            with self.subTest(raw=raw[:30]):
                with self.assertRaises(ValueError):
                    load_json_bytes(raw)
        self.assertEqual(load_json_bytes(b'{"x":1}'), {'x': 1})

    def test_speed_moored_altitude_and_catalogue_limits(self):
        self.first()['speedMps'] = 0.1
        self.assertIn('$.blocks[0].objects[0].speedMps', self.paths())
        self.first()['speedMps'] = 0
        self.first()['altitudeM'] = 1
        self.assertIn('$.blocks[0].objects[0].altitudeM', self.paths())
        self.first().update(model='small_drone', altitudeM=120, speedMps=15)
        self.assertTrue(self.store.validate(self.plan)['valid'])
        self.first()['speedMps'] = 15.001
        self.assertIn('$.blocks[0].objects[0].speedMps', self.paths())
        self.first()['speedMps'] = 15
        self.first()['altitudeM'] = 120.001
        self.assertIn('$.blocks[0].objects[0].altitudeM', self.paths())

    def test_camera_and_observer_preserve_runtime_bounds(self):
        for section, key, value in (
                ('camera', 'width', 4097), ('camera', 'height', 63),
                ('camera', 'verticalFovDeg', 29), ('camera', 'verticalFovDeg', 91),
                ('camera', 'farClipM', 4999), ('camera', 'viewDownPitchDeg', 16),
                ('observer', 'speedMps', 13.90), ('observer', 'rollMaxDeg', 13),
                ('observer', 'pitchMaxDeg', 9)):
            plan = copy.deepcopy(self.plan)
            plan[section][key] = value
            self.assertIn('$.' + section + '.' + key, self.paths(plan))

    def test_heading_360_is_normalized_without_mutating_input(self):
        self.plan['camera']['viewHeadingDeg'] = 360
        self.plan['observer']['headingDeg'] = 360
        self.first()['headingDeg'] = 360
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'])
        self.assertEqual(result['campaign']['camera']['viewHeadingDeg'], 0)
        self.assertEqual(result['campaign']['observer']['headingDeg'], 0)
        self.assertEqual(self.first()['headingDeg'], 360)

    def test_pixel_height_computes_range_without_model_scaling(self):
        self.first().update(distanceMode='pixel_height', targetHeightPx=20)
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'], result['errors'])
        row = result['campaign']['blocks'][0]['objects'][0]
        expected = 3 * 720 / (2 * math.tan(math.radians(60) / 2) * 20)
        self.assertAlmostEqual(row['distanceM'], expected)
        self.assertNotIn('scale', row)
        self.assertTrue(any('Approximate pixel' in warning['message'] for warning in result['warnings']))
        self.assertEqual(self.first()['distanceM'], 400)

    def test_infeasible_pixel_target_and_sensor_flags(self):
        self.first().update(distanceMode='pixel_height', targetHeightPx=720)
        self.assertIn('$.blocks[0].objects[0].targetHeightPx', self.paths())
        for key, value in (('rgb', False), ('thermal', True), ('nightVision', True), ('rgb', 1)):
            plan = self.store.defaults()
            plan['sensors'][key] = value
            self.assertIn('$.sensors.' + key, self.paths(plan))

    def test_composition_warnings_do_not_reject_valid_plans(self):
        self.first()['bearingDeg'] = 90
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'])
        self.assertTrue(any('outside horizontal camera FOV' in warning['message'] for warning in result['warnings']))
        self.first().update(bearingDeg=0, distanceM=5)
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'])
        self.assertTrue(any('outside vertical camera FOV' in warning['message'] for warning in result['warnings']))
        self.first().update(distanceM=400, count=2, spreadDeg=0)
        result = self.store.validate(self.plan)
        self.assertTrue(result['valid'])
        self.assertTrue(any('same nominal 3D centre' in warning['message'] for warning in result['warnings']))
        self.assertEqual(result['summary']['countSemantics'], 'planned_actor_image_instances_not_verified_visible_objects')

    def test_scene_path_is_generated_manual_scene_not_existing_traffic_scene(self):
        catalog = self.store.catalog()
        self.assertEqual(catalog['scenes'][0]['path'], 'Assets/Scenes/Dataset/ManualCampaign_<id>.unity')
        manifest = self.store.prepare(self.plan)['manifest']
        self.assertEqual(manifest['provenance']['scenePath'], catalog['scenes'][0]['path'])

    def test_save_load_list_are_immutable_and_path_free(self):
        first = self.store.save(self.plan)
        location = self.core / 'artifacts/campaign-settings/saved' / (first['id'] + '.json')
        original = location.read_bytes()
        self.plan['name'] = 'Second plan'
        second = self.store.save(self.plan)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(location.read_bytes(), original)
        self.assertEqual(self.store.get(first['id']), first)
        self.assertEqual(self.store.list()[0]['id'], second['id'])
        self.assertNotIn(str(self.root), json.dumps(first))
        with patch('campaign_settings.uuid.uuid4', return_value=uuid.UUID(first['id'])):
            with self.assertRaises(FileExistsError):
                self.store.save(self.plan)
        self.assertEqual(location.read_bytes(), original)

    def test_prepare_manifest_hash_and_immutable_independent_plan(self):
        first = self.store.prepare(self.plan)
        data = self.store.read_prepared(first['id'], 'campaign.json')
        manifest = load_json_bytes(self.store.read_prepared(first['id'], 'manifest.json'))
        self.assertEqual(manifest['campaignSha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(manifest['schema'], 'lotusim-manual-campaign-1')
        self.assertEqual(manifest['relativeCampaignFile'], 'campaign.json')
        self.assertEqual(manifest['provenance']['distanceReference'], 'bridge_camera_horizontal_range_m')
        self.assertEqual(load_json_bytes(data), first['campaign'])
        second = self.store.prepare(self.plan)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.store.read_prepared(first['id'], 'campaign.json'), data)
        with patch('campaign_settings.uuid.uuid4', return_value=uuid.UUID(first['id'])):
            with self.assertRaises(FileExistsError):
                self.store.prepare(self.plan)

    def test_unreal_can_save_but_unresolved_mesh_bindings_cannot_prepare(self):
        self.plan['engine'] = 'unreal'
        self.assertTrue(self.store.validate(self.plan)['valid'])
        self.assertTrue(self.store.save(self.plan)['valid'])
        with self.assertRaises(CampaignValidationError) as context:
            self.store.prepare(self.plan)
        self.assertEqual(context.exception.validation['errors'][0]['path'], '$.engine')
        self.assertFalse((self.core / 'artifacts/campaign-settings/prepared').exists())

    def test_missing_unity_adapter_is_not_marked_ready(self):
        (self.unity / ADAPTER_PATH).unlink()
        self.assertFalse(self.store.catalog()['engines'][0]['available'])
        with self.assertRaises(CampaignValidationError):
            self.store.prepare(self.plan)

    def test_opaque_identifiers_and_download_whitelist(self):
        for identifier in ('../secret', '/tmp/secret', 'a' * 36, '%2e%2e', '', None):
            with self.subTest(identifier=identifier):
                with self.assertRaises(CampaignSecurityError):
                    self.store.get(identifier)
        prepared = self.store.prepare(self.plan)
        for filename in ('../campaign.json', '/tmp/secret', 'other.json', 'manifest.json/x', ''):
            with self.assertRaises(CampaignSecurityError):
                self.store.read_prepared(prepared['id'], filename)

    def test_symlink_artifacts_root_cannot_escape(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.core / 'artifacts').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(CampaignSecurityError):
            self.store.save(self.plan)
        with self.assertRaises(CampaignSecurityError):
            self.store.prepare(self.plan)
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_saved_and_prepared_files_cannot_escape(self):
        saved = self.store.save(self.plan)
        location = self.core / 'artifacts/campaign-settings/saved' / (saved['id'] + '.json')
        outside = self.root / 'outside.json'
        outside.write_text('{"secret":"not downloadable"}')
        location.unlink()
        location.symlink_to(outside)
        with self.assertRaises(CampaignSecurityError):
            self.store.get(saved['id'])
        self.assertEqual(self.store.list(), [])
        prepared = self.store.prepare(self.plan)
        location = self.store.prepared_file(prepared['id'], 'campaign.json')
        location.unlink()
        location.symlink_to(outside)
        with self.assertRaises(CampaignSecurityError):
            self.store.read_prepared(prepared['id'], 'campaign.json')

    def test_symlink_prepared_directory_cannot_escape(self):
        prepared = self.store.prepare(self.plan)
        root = self.core / 'artifacts/campaign-settings/prepared'
        identifier = str(uuid.uuid4())
        outside = self.root / 'outside-dir'
        outside.mkdir()
        (outside / 'campaign.json').write_text('{"secret":true}')
        (root / identifier).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(CampaignSecurityError):
            self.store.read_prepared(identifier, 'campaign.json')
        self.assertTrue(self.store.read_prepared(prepared['id'], 'manifest.json'))

    def test_regular_file_and_size_are_checked_on_load(self):
        saved = self.store.save(self.plan)
        location = self.core / 'artifacts/campaign-settings/saved' / (saved['id'] + '.json')
        location.write_bytes(b' ' * (MAX_JSON_BYTES + 1))
        with self.assertRaises(ValueError):
            self.store.get(saved['id'])
        location.unlink()
        os.mkfifo(location)
        with self.assertRaises(CampaignSecurityError):
            self.store.get(saved['id'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
