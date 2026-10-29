"""Developer formatting guards use only synthetic temporary source files."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import format_csharp
import format_sources
import sync_source_patches


class FormattingToolsTests(unittest.TestCase):
    def test_patch_git_environment_cannot_redirect_a_repository(self):
        inherited = dict.fromkeys(
            (
                'GIT_DIR',
                'GIT_WORK_TREE',
                'GIT_INDEX_FILE',
                'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY',
                'GIT_CONFIG_PARAMETERS',
                'GIT_CONFIG_KEY_0',
                'GIT_CONFIG_VALUE_0',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES',
            ),
            '/outside',
        )
        inherited['GIT_CONFIG_COUNT'] = '1'
        with patch.dict(os.environ, inherited):
            result = sync_source_patches.environment()
        for key in inherited:
            if key == 'GIT_CONFIG_COUNT':
                self.assertEqual(result[key], '0')
            else:
                self.assertNotIn(key, result)
        self.assertEqual(result['GIT_NO_LAZY_FETCH'], '1')
        self.assertEqual(result['GIT_TERMINAL_PROMPT'], '0')

    def test_csharp_includes_new_source_but_not_generated_messages(self):
        names = (
            'components/LOTUSim-Unity-modules/Assets/Scripts/Dataset/NewSource.cs',
            'components/LOTUSim-Unity-modules/Assets/RosMessages/Lotusim/msg/Generated.cs',
            'runtime/LOTUSim-Unity-modules/Assets/Scripts/Live.cs',
        )
        with tempfile.TemporaryDirectory(prefix='lotusim-format-test-') as folder:
            root = Path(folder).resolve()
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('class Fixture {}\n', encoding='utf-8')
            with patch.object(
                format_csharp.subprocess,
                'check_output',
                return_value=('\0'.join(names) + '\0').encode(),
            ) as command:
                selected = format_csharp.tracked_sources(root)
        self.assertEqual(selected, [names[0]])
        self.assertIn('--others', command.call_args.args[0])
        self.assertIn('--exclude-standard', command.call_args.args[0])

    def test_source_listing_excludes_vendor_runtime_and_outputs(self):
        names = (
            'components/LOTUSim/tools/ops_dashboard_ui/shell/app.js',
            'components/LOTUSim/tools/ops_dashboard_ui/vendor/three/three.module.js',
            'components/LOTUSim/qa/frame.png',
            'runtime/LOTUSim/tools/live.py',
            'scripts/format_sources.py',
            'components/LOTUSim/tests/qa/browser/operations_ux.cjs',
        )
        with patch.dict(os.environ, {'GIT_DIR': '/outside'}):
            with patch.object(
                format_sources.subprocess,
                'check_output',
                return_value=('\0'.join(names) + '\0').encode(),
            ) as command:
                selected = format_sources.source_paths(Path('/fixture'))
        self.assertEqual(selected, sorted([names[0], names[4], names[5]]))
        self.assertNotIn('GIT_DIR', command.call_args.kwargs['env'])


if __name__ == '__main__':
    unittest.main()
