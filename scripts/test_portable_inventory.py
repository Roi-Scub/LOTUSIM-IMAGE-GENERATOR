"""Portable inventory regression tests using temporary synthetic files only."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'refresh_manifest', Path(__file__).with_name('refresh_manifest.py')
)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class PortableInventoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='lotusim-inventory-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        for name in ('AGENTS.md', 'README.md', '.gitignore'):
            (self.root / name).write_text('fixture\n', encoding='utf-8')
        self.manifest = {'files': []}

    def put(self, name, body='fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')

    def refresh(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with (
            patch.object(inventory, 'ROOT', self.root),
            patch.object(sys, 'argv', ['refresh_manifest.py', '--write']),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            inventory.main()
        return json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))

    def test_generated_qa_outputs_are_not_portable_sources(self):
        for prefix in inventory.GENERATED_QA_ROOTS:
            self.put(prefix + 'capture.png')
            self.put(prefix + 'result.json')
        self.put('components/LOTUSim/scripts/qa_operations_ux.cjs')
        files = {item['path'] for item in self.refresh()['files']}
        self.assertIn('components/LOTUSim/scripts/qa_operations_ux.cjs', files)
        self.assertFalse(any(inventory.generated_qa(name) for name in files))

    def test_old_qa_entries_are_removed_even_if_the_file_is_gone(self):
        self.manifest['files'] = [{'path': 'components/LOTUSim/qa/old/capture.png'}]
        self.assertFalse(any('old/capture.png' in item['path'] for item in self.refresh()['files']))

    def test_source_images_and_unity_metadata_remain_included(self):
        for name in (
            'components/LOTUSim-Unity-modules/Assets/Textures/sea.png',
            'components/LOTUSim-Unity-modules/Assets/Textures/sea.png.meta',
            'components/LOTUSim/scripts/qa_helpers/source.cjs',
        ):
            self.put(name)
        result = self.refresh()
        files = {item['path'] for item in result['files']}
        self.assertIn('components/LOTUSim-Unity-modules/Assets/Textures/sea.png', files)
        self.assertIn('components/LOTUSim-Unity-modules/Assets/Textures/sea.png.meta', files)
        self.assertIn('components/LOTUSim/scripts/qa_helpers/source.cjs', files)
        self.assertEqual(result['totalBytes'], sum(item['bytes'] for item in result['files']))

    def test_unsafe_legacy_entry_is_still_refused(self):
        self.manifest['files'] = [{'path': '../private.png'}]
        with self.assertRaises(ValueError):
            self.refresh()

    def test_development_style_configuration_is_portable(self):
        names = (
            '.editorconfig',
            '.prettierrc.json',
            '.prettierignore',
            '.clang-format',
            'pyproject.toml',
            'requirements-dev.txt',
            'package.json',
            'package-lock.json',
        )
        for name in names:
            self.put(name)
        files = {item['path'] for item in self.refresh()['files']}
        self.assertTrue(set(names).issubset(files))


if __name__ == '__main__':
    unittest.main()
