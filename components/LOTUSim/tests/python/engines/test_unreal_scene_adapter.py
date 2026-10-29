"""Pure contract/safety checks. These tests do NOT validate a native UE render."""

import copy
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


from lotusim_image_generator.engines import unreal as adapter
from lotusim_image_generator.engines.templates import unreal_scene as template

IDENTITY = '6d408dbf-79c7-480c-a5be-b897547b9600'
CAMPAIGN = {
    'schema': 'lotusim-campaign-settings-1',
    'engine': 'unreal',
    'scene': 'maritime_manual',
    'name': 'Test',
    'seed': 42,
    'totalImages': 2,
    'camera': {
        'station': 'bridge',
        'width': 1280,
        'height': 720,
        'verticalFovDeg': 60,
        'farClipM': 50000,
        'viewHeadingDeg': 0,
        'viewDownPitchDeg': 0,
    },
    'observer': {'headingDeg': 0, 'speedMps': 0, 'rollMaxDeg': 0, 'pitchMaxDeg': 0},
    'sensors': {'rgb': True, 'thermal': False, 'nightVision': False},
    'blocks': [
        {
            'id': 'day',
            'name': 'Day',
            'images': 1,
            'environment': {
                'timeOfDay': 'day',
                'cloudCover': 0.2,
                'rainIntensity': 0,
                'waveHeightM': 2,
                'waveDirectionDeg': 0,
                'windMps': 3,
            },
            'objects': [
                {
                    'id': 'b',
                    'model': 'buoy',
                    'count': 1,
                    'distanceM': 100,
                    'bearingDeg': 0,
                    'spreadDeg': 0,
                    'altitudeM': 0,
                    'speedMps': 0,
                    'headingDeg': 0,
                    'distanceMode': 'metres',
                }
            ],
        },
        {
            'id': 'night',
            'name': 'Night',
            'images': 1,
            'environment': {
                'timeOfDay': 'night',
                'cloudCover': 0.2,
                'rainIntensity': 0,
                'waveHeightM': 2,
                'waveDirectionDeg': 0,
                'windMps': 3,
            },
            'objects': [],
        },
    ],
}
BUOY = '<sdf version="1.10"><model name="buoy"><link name="body"><visual name="v"><pose>0 0 .5 0 0 0</pose><geometry><cylinder><radius>.4</radius><length>1</length></cylinder></geometry><material><diffuse>1 .2 .1 1</diffuse></material></visual></link></model></sdf>'
CATALOGUE = {
    'assets': [
        {
            'model': 'buoy',
            'category': 'buoy',
            'domain': 'moored',
            'lengthM': 1.3,
            'beamM': 1.3,
            'heightM': 3,
            'maxSpeedMps': 0,
        }
    ]
}


class UnrealAdapterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='lotusim-unreal-contract-')
        self.root = Path(self.directory.name)
        self.models = self.root / 'assets/models'
        buoy = self.models / 'buoy'
        buoy.mkdir(parents=True)
        (buoy / 'model.sdf').write_text(BUOY)
        self.campaign = copy.deepcopy(CAMPAIGN)
        self.catalogue = copy.deepcopy(CATALOGUE)
        template._STATE = None
        template._CAPTURE = None

    def tearDown(self):
        template._STATE = None
        template._CAPTURE = None
        self.directory.cleanup()

    def prepared(self):
        return adapter.prepare_unreal(
            self.campaign, IDENTITY, 'a' * 64, self.root, '/unused/Unity', self.catalogue
        )

    def plan(self):
        return json.loads(self.prepared()['files']['scene-plan.json'])

    def fixture_mesh(self, material=True):
        model = self.models / 'sample'
        (model / 'meshes').mkdir(parents=True)
        (model / 'materials').mkdir()
        (model / 'model.sdf').write_text(
            '<sdf><model name="sample"><link name="body"><visual name="v"><geometry><mesh><uri>model://sample/meshes/sample.obj</uri></mesh></geometry></visual></link></model></sdf>'
        )
        obj = 'mtllib ../materials/sample.mtl\n' if material else ''
        obj += 'v 0 0 0\nv 2 0 0\nv 0 3 4\nvn 0 1 0\nf 1//1 2//1 3//1\n'
        (model / 'meshes/sample.obj').write_text(obj)
        (model / 'materials/sample.mtl').write_text('newmtl solid\nKd 1 .2 .1\nmap_Kd image.png\n')
        (model / 'materials/image.png').write_bytes(b'fixture-raster-content')
        self.catalogue['assets'].append(
            {
                'model': 'sample',
                'category': 'other',
                'domain': 'moored',
                'lengthM': 2,
                'beamM': 3,
                'heightM': 4,
                'maxSpeedMps': 0,
            }
        )
        self.campaign['blocks'][0]['objects'][0]['model'] = 'sample'
        return model

    def test_four_flat_outputs_and_plugins(self):
        result = self.prepared()
        self.assertEqual(
            set(result['files']),
            {
                'LOTUSimPrepared.uproject',
                'scene_unreal.py',
                'scene-plan.json',
                'unreal-instructions.txt',
            },
        )
        self.assertTrue(
            all(
                isinstance(value, bytes) and len(value) < 1048576
                for value in result['files'].values()
            )
        )
        project = json.loads(result['files']['LOTUSimPrepared.uproject'])
        self.assertEqual(
            {p['Name'] for p in project['Plugins']},
            {
                'PythonScriptPlugin',
                'EditorScriptingUtilities',
                'SequencerScripting',
                'MovieRenderPipeline',
                'Water',
            },
        )
        self.assertFalse(result['manifest']['nativeValidated'])
        self.assertFalse(result['manifest']['annotationSupported'])

    def test_fixed_script_not_user_interpolation(self):
        original = self.prepared()['files']['scene_unreal.py']
        self.campaign['name'] = "__import__('os').system('NOT_EXECUTED')"
        self.assertEqual(original, self.prepared()['files']['scene_unreal.py'])

    def test_unique_uuid_destination(self):
        self.assertEqual(
            self.plan()['scenePath'],
            '/Game/LOTUSim/Campaigns/6d408dbf79c7480ca5beb897547b9600/Scene',
        )
        with self.assertRaises(ValueError):
            adapter.prepare_unreal(
                self.campaign, '../../escape', 'a' * 64, self.root, '', self.catalogue
            )

    def test_invalid_hash_and_engine_refused(self):
        with self.assertRaises(ValueError):
            adapter.prepare_unreal(
                self.campaign, IDENTITY, 'not-sha', self.root, '', self.catalogue
            )
        self.campaign['engine'] = 'unity'
        with self.assertRaises(ValueError):
            self.prepared()

    def test_buoy_primitive_provenance_and_source_hash(self):
        binding = self.plan()['bindings'][0]
        self.assertEqual(binding['kind'], 'sdf-primitives')
        self.assertEqual(binding['primitives'][0]['dimensionsM'], [0.8, 0.8, 1.0])
        self.assertIn('not the more detailed Unity', binding['provenance'])
        self.assertEqual(len(template._verify_sources(self.plan())), 1)

    def test_plan_load_validation(self):
        path = self.root / 'scene-plan.json'
        path.write_bytes(self.prepared()['files']['scene-plan.json'])
        self.assertEqual(template._load_plan(path)['id'], IDENTITY)
        plan = self.plan()
        plan['campaign']['camera']['viewHeadingDeg'] = 300
        plan['campaign']['camera']['width'] = 64
        plan['campaign']['camera']['height'] = 64
        path.write_text(json.dumps(plan))
        template._load_plan(path)
        plan['campaign']['blocks'][0]['objects'][0]['count'] = -100
        path.write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            template._load_plan(path)

    def test_changed_source_refused(self):
        plan = self.plan()
        (self.models / 'buoy/model.sdf').write_text(BUOY + ' ')
        with self.assertRaisesRegex(ValueError, 'changed'):
            template._verify_sources(plan)

    def test_obj_binding_inventory_and_actual_bounds(self):
        self.fixture_mesh()
        binding = self.plan()['bindings'][0]
        self.assertEqual(binding['sourceDimensionsM'], [2, 3, 4])
        self.assertEqual(len(binding['sourceFiles']), 4)
        self.assertEqual(binding['materials'][0]['textures'][0]['directive'], 'map_Kd')

    def test_cm_handedness_winding_and_material_normalization(self):
        self.fixture_mesh()
        plan = self.plan()
        result = template._normalize_obj(plan, plan['bindings'][0], self.root / 'cache')
        data = result.read_text()
        self.assertIn('v 200 -0 0', data)
        self.assertIn('v 0 -300 400', data)
        self.assertIn('vn 0 -1 0', data)
        self.assertIn('f 3//1 2//1 1//1', data)
        self.assertIn('mtllib material_0.mtl', data)
        self.assertIn('map_Kd texture_0_0.png', (result.parent / 'material_0.mtl').read_text())

    def test_material_escape_refused(self):
        model = self.fixture_mesh()
        (model / 'materials/sample.mtl').write_text('map_Kd ../../../../outside.png\n')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            self.prepared()

    def test_symlink_dependency_refused(self):
        model = self.fixture_mesh()
        texture = model / 'materials/image.png'
        texture.unlink()
        target = self.root / 'private.png'
        target.write_bytes(b'private')
        texture.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.prepared()

    def test_native_dae_never_silently_replaced(self):
        model = self.fixture_mesh()
        sdf = model / 'model.sdf'
        sdf.write_text(sdf.read_text().replace('sample.obj', 'sample.dae'))
        (model / 'meshes/sample.dae').write_text('not needed')
        with self.assertRaisesRegex(ValueError, 'static OBJ'):
            self.prepared()

    def test_unbaked_parent_transform_refused(self):
        model = self.fixture_mesh()
        sdf = model / 'model.sdf'
        sdf.write_text(
            sdf.read_text().replace(
                '<link name="body">', '<link name="body"><pose>1 0 0 0 0 0</pose>'
            )
        )
        with self.assertRaisesRegex(ValueError, 'baked model/link'):
            self.prepared()

    def test_unsupported_submesh_refused(self):
        model = self.fixture_mesh()
        sdf = model / 'model.sdf'
        sdf.write_text(
            sdf.read_text().replace('</mesh>', '<submesh><name>Hull</name></submesh></mesh>')
        )
        with self.assertRaisesRegex(ValueError, 'submesh'):
            self.prepared()

    def test_sdf_entity_refused(self):
        (self.models / 'buoy/model.sdf').write_text(
            '<!DOCTYPE sdf [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + BUOY
        )
        with self.assertRaisesRegex(ValueError, 'entities'):
            self.prepared()

    def test_coordinates_fov_and_independent_block_sampling(self):
        plan = self.plan()
        first = template.sample_spec(plan, 0)
        self.assertEqual(first['actors'][0]['locationCm'], [10000, 0, 0])
        self.assertAlmostEqual(first['horizontalFovDeg'], 91.4928445, places=5)
        self.assertEqual(template.sample_spec(plan, 1)['actors'], [])
        self.assertEqual(first, template.sample_spec(plan, 0))
        plan['campaign']['camera']['viewHeadingDeg'] = 90
        east = template.sample_spec(plan, 0)['actors'][0]['locationCm']
        self.assertAlmostEqual(east[0], 0, places=6)
        self.assertAlmostEqual(east[1], 10000)
        with self.assertRaises(ValueError):
            template.sample_spec(plan, -1)

    def test_roll_is_seeded_and_not_claimed_hydrodynamic(self):
        plan = self.plan()
        plan['campaign']['observer']['rollMaxDeg'] = 6
        plan['campaign']['observer']['pitchMaxDeg'] = 3
        sample = template.sample_spec(plan, 0)
        self.assertTrue(-6 <= sample['cameraRotationDeg'][2] <= 6)
        self.assertEqual(sample, template.sample_spec(plan, 0))
        self.assertTrue(any('hydrodynamique' in value for value in sample['limitations']))

    def test_map_change_during_capture_unregisters_callback(self):
        calls = []
        ue = types.SimpleNamespace(
            unregister_slate_post_tick_callback=lambda h: calls.append(h),
            log_error=lambda text: calls.append(text),
        )
        template._STATE = {'ue': ue}
        template._CAPTURE = {'handle': 7, 'task': None}
        with (
            patch.object(template, '_require_state', side_effect=RuntimeError('wrong level')),
            patch.object(template, '_write_status') as status,
        ):
            template._capture_tick(0.01)
        self.assertIsNone(template._CAPTURE)
        self.assertEqual(calls[0], 7)
        status.assert_called_once_with('rgb-preview-failed: wrong level')

    def test_explicit_editor_requirement(self):
        with patch.dict('sys.modules', {'unreal': None}):
            with self.assertRaisesRegex(RuntimeError, 'inside Unreal Editor'):
                template._engine()


if __name__ == '__main__':
    unittest.main()
