"""Both owned Unity source layouts remain supported without launching Unity."""

import json
from pathlib import Path
import tempfile
import unittest

from lotusim_image_generator.campaigns.settings import ADAPTER_PATH
from lotusim_image_generator.engines.registry import (
    EngineRegistry,
    UNITY_ADAPTER,
    LEGACY_UNITY_ADAPTER,
    find_unity_adapter,
)
from lotusim_image_generator.engines.unity import prepare_unity


class UnityAdapterLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-unity-adapter-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.core, self.unity = self.root / 'core', self.root / 'unity'
        self.core.mkdir()
        self.unity.mkdir()
        self.registry = EngineRegistry(self.core, self.unity)

    def source(self, relative):
        path = self.unity / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('// inert adapter fixture\n')
        return path

    def test_canonical_builder_is_discovered(self):
        self.source(UNITY_ADAPTER)
        self.assertEqual(ADAPTER_PATH, UNITY_ADAPTER)
        descriptor = self.registry.get('unity')
        self.assertTrue(descriptor['preparationAvailable'])
        self.assertEqual(descriptor['adapterPath'], UNITY_ADAPTER)
        self.assertFalse(descriptor['nativeValidated'])

    def test_legacy_builder_is_discovered_without_changing_project(self):
        path = self.source(LEGACY_UNITY_ADAPTER)
        before = path.read_bytes()
        descriptor = self.registry.get('unity')
        self.assertTrue(descriptor['preparationAvailable'])
        self.assertEqual(descriptor['adapterPath'], LEGACY_UNITY_ADAPTER)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.unity / UNITY_ADAPTER).exists())

    def test_prepared_package_names_the_actual_legacy_adapter(self):
        self.source(LEGACY_UNITY_ADAPTER)
        prepared = prepare_unity(
            {'totalImages': 1},
            '12345678-1234-4234-8234-123456789abc',
            'a' * 64,
            self.core,
            self.unity,
        )
        self.assertEqual(prepared['manifest']['adapterPath'], LEGACY_UNITY_ADAPTER)
        self.assertEqual(
            json.loads(prepared['files']['scene-plan.json'])['adapterPath'], LEGACY_UNITY_ADAPTER
        )
        self.assertFalse((self.core / 'artifacts').exists())

    def test_canonical_path_has_priority_when_both_exist(self):
        self.source(LEGACY_UNITY_ADAPTER)
        self.source(UNITY_ADAPTER)
        self.assertEqual(find_unity_adapter(self.unity), UNITY_ADAPTER)

    def test_missing_adapter_is_not_marked_available(self):
        self.assertIsNone(find_unity_adapter(None))
        self.assertIsNone(find_unity_adapter(self.unity))
        self.assertFalse(self.registry.get('unity')['preparationAvailable'])

    def test_external_symlink_cannot_appear_as_an_installed_adapter(self):
        path = self.source(UNITY_ADAPTER)
        path.unlink()
        outside = self.root / 'outside.cs'
        outside.write_text('// outside project\n')
        path.symlink_to(outside)
        self.assertIsNone(find_unity_adapter(self.unity))
        self.assertFalse(self.registry.get('unity')['preparationAvailable'])

    def test_invalid_new_path_does_not_hide_a_valid_legacy_adapter(self):
        path = self.source(UNITY_ADAPTER)
        path.unlink()
        outside = self.root / 'outside.cs'
        outside.write_text('// outside project\n')
        path.symlink_to(outside)
        self.source(LEGACY_UNITY_ADAPTER)
        self.assertEqual(find_unity_adapter(self.unity), LEGACY_UNITY_ADAPTER)


if __name__ == '__main__':
    unittest.main()
