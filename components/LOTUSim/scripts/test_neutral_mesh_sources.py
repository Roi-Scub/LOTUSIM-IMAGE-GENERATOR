"""Geometry source availability must not require an installed Unity project."""

import sys
from pathlib import Path
import unittest
import copy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_mesh_integration as fixtures
import mesh_integration as mesh


class NeutralMeshTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.IntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.core = self.fixture.core

    def test_unconverted_upload_not_available(self):
        self.assertEqual(mesh.neutral_imports(self.core), [])

    def test_converted_source_is_available_without_prefab_ack_or_unity_project(self):
        self.fixture.prepare()
        self.fixture.unity.rmdir()
        records = mesh.neutral_imports(self.core)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertTrue(record['neutralReady'])
        self.assertFalse(record['rendererReady'])
        self.assertNotIn('prefabGuid', record)
        self.assertEqual(record['license'], 'CC0')
        self.assertEqual(record['sourceUrl'], 'https://example.org/own-model')
        self.assertEqual(record['neutralSource']['root'], 'core')
        self.assertTrue(record['neutralSource']['obj'].endswith('/gazebo.obj'))
        self.assertEqual(mesh.ready_imports(self.core, self.fixture.unity), [])

    def test_modified_prepared_geometry_is_not_available(self):
        request = self.fixture.prepare()
        (self.fixture.folder / request['bundleDirectory'] / 'gazebo.obj').write_text('changed')
        self.assertEqual(mesh.neutral_imports(self.core), [])

    def test_modified_upload_is_not_available(self):
        self.fixture.prepare()
        (self.fixture.folder / 'files/mesh.obj').write_text('changed')
        self.assertEqual(mesh.neutral_imports(self.core), [])

    def test_path_never_leaves_core_or_follows_import_symlink(self):
        self.fixture.prepare()
        for record in mesh.neutral_imports(self.core):
            for item in record['neutralSource']['files']:
                (self.core / item['path']).resolve().relative_to(self.core)
        duplicate = self.fixture.folder.parent / 'import-12345678-1234-4234-8234-123456789abc'
        duplicate.symlink_to(self.fixture.folder, target_is_directory=True)
        self.assertEqual(len(mesh.neutral_imports(self.core)), 1)

    def test_unreal_binding_accepts_verified_geometry_without_sdf_or_unity(self):
        import unreal_scene_adapter as unreal_adapter
        import unreal_scene_template as unreal_template

        self.fixture.prepare()
        self.fixture.unity.rmdir()
        record = mesh.neutral_imports(self.core)[0]
        binding = unreal_adapter._mesh_binding(self.core, record['model'], record)
        self.assertEqual(binding['kind'], 'static-obj')
        self.assertEqual(binding['sourceDimensionsM'], [2, 2, 1])
        self.assertTrue(
            unreal_template._verify_sources({'coreRoot': str(self.core), 'bindings': [binding]})
        )

    def test_unreal_binding_rejects_changed_neutral_declaration(self):
        import unreal_scene_adapter as unreal_adapter

        self.fixture.prepare()
        record = copy.deepcopy(mesh.neutral_imports(self.core)[0])
        record['neutralSource']['obj'] = 'assets/config-private.obj'
        with self.assertRaises(ValueError):
            unreal_adapter._mesh_binding(self.core, record['model'], record)


if __name__ == '__main__':
    unittest.main()
