"""Synthetic Unity metadata and compiler-path fixtures; no Editor execution."""

import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import check_unity_layout as layout
import check_unity_refactor as compiler


class UnityLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lotusim-unity-layout-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.project = self.root / layout.PROJECT_PATH
        self.before = 'Assets/Scripts/Dataset/Example.cs'
        self.after = 'Assets/Scripts/Dataset/Campaigns/Example.cs'
        self.write(self.after, 'public class Example {}\n', '1' * 32)
        resource = 'Assets/Resources/Dataset/InstanceMask.shader'
        self.write(resource, 'Shader "Dataset/InstanceMask" {}\n', '2' * 32)
        for parent in (self.project / self.after).parents:
            if parent == self.project / 'Assets':
                break
            relative = parent.relative_to(self.project).as_posix()
            self.write(
                relative + '.meta',
                self.metadata(uuid.uuid5(uuid.NAMESPACE_URL, relative).hex, folder=True),
            )
        self.document = {
            'schema': layout.SCHEMA,
            'baselineCommit': 'a' * 40,
            'groups': {'Assets/Scripts/Dataset': ['Campaigns']},
            'moves': [
                {
                    'from': self.before,
                    'to': self.after,
                    'guid': '1' * 32,
                    'role': 'runtime',
                    'assembly': 'Assembly-CSharp',
                }
            ],
            'resources': [{'path': resource, 'guid': '2' * 32}],
        }
        self.save()

    @staticmethod
    def metadata(identifier, folder=False):
        return (
            'fileFormatVersion: 2\nguid: '
            + identifier
            + ('\nfolderAsset: yes\n' if folder else '\n')
        )

    def write(self, relative, contents, identifier=None):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
        if identifier is not None:
            path.with_name(path.name + '.meta').write_text(
                self.metadata(identifier), encoding='utf-8'
            )
        return path

    def save(self):
        path = self.root / layout.LAYOUT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.document), encoding='utf-8')

    def test_valid_move_preserves_identity_and_assembly(self):
        result = layout.check(self.root)
        self.assertEqual(result['scripts'], 1)
        self.assertEqual(result['resources'], 1)
        self.assertEqual(layout.source_aliases(self.root), {self.before: self.after})

    def test_dashboard_adapter_constant_matches_the_actual_unity_move(self):
        package = layout.ROOT / 'components/LOTUSim/tools/lotusim_image_generator'
        registry = ast.parse((package / 'engines/registry.py').read_text())
        declaration = next(
            node
            for node in registry.body
            if isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == 'UNITY_ADAPTER'
        )
        adapter = ast.literal_eval(declaration.value)
        actual = next(
            move
            for move in layout.load_layout()['moves']
            if move['from'].endswith('/DatasetManualCampaignBuilder.cs')
        )
        self.assertEqual(adapter, actual['to'])

    def test_changed_script_guid_is_refused(self):
        self.write(self.after + '.meta', self.metadata('3' * 32))
        with self.assertRaisesRegex(ValueError, 'identity changed'):
            layout.check(self.root)

    def test_obsolete_source_copy_is_refused(self):
        self.write(self.before, 'public class Example {}\n')
        with self.assertRaisesRegex(ValueError, 'Obsolete duplicate'):
            layout.check(self.root)

    def test_obsolete_metadata_is_refused_even_without_source(self):
        self.write(self.before + '.meta', self.metadata('1' * 32))
        with self.assertRaisesRegex(ValueError, 'Obsolete Unity metadata'):
            layout.check(self.root)

    def test_runtime_to_editor_relocation_is_refused(self):
        self.document['moves'][0]['to'] = 'Assets/Editor/Dataset/Example.cs'
        self.save()
        with self.assertRaisesRegex(ValueError, 'assembly'):
            layout.load_layout(self.root)

    def test_type_filename_change_is_not_a_safe_move(self):
        self.document['moves'][0]['to'] = 'Assets/Scripts/Dataset/Campaigns/Renamed.cs'
        self.save()
        with self.assertRaisesRegex(ValueError, 'name, GUID or assembly'):
            layout.load_layout(self.root)

    def test_host_and_traversal_paths_are_refused(self):
        for name in (
            '/tmp/Example.cs',
            'Assets/../Example.cs',
            'Assets//Example.cs',
            'Assets/./Example.cs',
            'Assets/Editor\\Example.cs',
            'Assets/\0Example.cs',
        ):
            with self.subTest(path=name), self.assertRaises(ValueError):
                layout.asset_path(name)

    def test_missing_script_and_folder_metadata_are_refused(self):
        metadata = self.project / (self.after + '.meta')
        metadata.unlink()
        with self.assertRaises(FileNotFoundError):
            layout.check(self.root)
        metadata.write_text(self.metadata('1' * 32))
        folder = self.project / 'Assets/Scripts/Dataset/Campaigns.meta'
        folder.unlink()
        with self.assertRaises(FileNotFoundError):
            layout.check(self.root)

    def test_duplicate_project_guid_is_refused(self):
        self.write('Assets/Extra.asset', 'fixture\n', '1' * 32)
        with self.assertRaisesRegex(ValueError, 'Duplicate Unity GUID'):
            layout.check(self.root)

    def test_new_assembly_definition_requires_explicit_migration(self):
        self.write('Assets/Scripts/Dataset/Campaigns/Unexpected.asmdef', '{}\n')
        with self.assertRaisesRegex(ValueError, 'Assembly boundaries changed'):
            layout.check(self.root)

    def test_sources_must_belong_to_a_declared_group(self):
        self.write('Assets/Scripts/Dataset/Loose.cs', 'public class Loose {}\n', '3' * 32)
        with self.assertRaisesRegex(ValueError, 'responsibility group'):
            layout.check(self.root)

    def test_symlink_source_is_refused(self):
        path = self.project / self.after
        path.unlink()
        outside = self.root / 'outside.cs'
        outside.write_text('public class Example {}\n')
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink refused'):
            layout.check(self.root)

    def test_missing_resources_shader_is_refused(self):
        (self.project / self.document['resources'][0]['path']).unlink()
        with self.assertRaises(FileNotFoundError):
            layout.check(self.root)

    def test_cached_compiler_paths_use_verified_alias_not_filename_matching(self):
        original = self.root / 'cached.rsp'
        original.write_text(
            '-out:"Library/original.dll"\n"' + self.before + '"\n"Assets/Unrelated/Example.cs"\n'
        )
        output = self.root / 'compiler-output'
        output.mkdir()
        seen = set()
        result = compiler.compile_response(
            original,
            'Assembly-CSharp',
            self.project,
            output,
            {self.after: self.project / self.after},
            seen,
            layout.source_aliases(self.root),
        )
        response = result.read_text()
        self.assertEqual(seen, {self.after})
        self.assertIn('"' + str(self.project / self.after) + '"', response)
        self.assertIn('"Assets/Unrelated/Example.cs"', response)
        self.assertNotIn('"' + self.before + '"', response)
        self.assertIn(str(output / 'original.dll'), response)

    def test_compiler_source_inventory_ignores_inherited_git_redirects(self):
        name = layout.PROJECT_PATH + '/' + self.after
        with (
            patch.dict(os.environ, {'GIT_DIR': '/outside'}),
            patch.object(
                compiler.subprocess, 'check_output', return_value=(name + '\0').encode()
            ) as command,
        ):
            sources = compiler.source_map(self.root)
        self.assertEqual(sources, {self.after: self.project / self.after})
        self.assertNotIn('GIT_DIR', command.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
