"""Compatibility and relocatability of installed/portable Python entry points."""

import importlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from lotusim_image_generator.paths import CORE_ROOT, TOOLS_ROOT, UI_ROOT, legacy_script
from lotusim_image_generator.dashboard.web_assets import STATIC_FILES


class PackageLayoutTests(unittest.TestCase):
    def test_planner_provenance_includes_shared_equations_and_not_absolute_paths(self):
        import tempfile
        from lotusim_image_generator.traffic.planner import planner_source_sha256

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for folder in (Path(first), Path(second)):
                (folder / 'planner.py').write_text('planner fixture\n')
                (folder / 'kinematics.py').write_text('equations fixture\n')
            expected = planner_source_sha256(first)
            self.assertEqual(expected, planner_source_sha256(second))
            (Path(first) / 'kinematics.py').write_text('changed equations\n')
            self.assertNotEqual(expected, planner_source_sha256(first))

    def test_legacy_imports_share_identity_including_private_members(self):
        pairs = {
            'ops_dashboard': 'dashboard.server',
            'ops_runtime': 'telemetry.runtime',
            'mesh_integration': 'assets.integration',
            'mesh_library': 'assets.library',
            'engine_registry': 'engines.registry',
            'campaign_settings': 'campaigns.settings',
            'plan_maritime_traffic': 'traffic.planner',
            'rgb_observer_worker': 'vision.worker',
        }
        for old, current in pairs.items():
            with self.subTest(entry=old):
                self.assertIs(
                    importlib.import_module(old),
                    importlib.import_module('lotusim_image_generator.' + current),
                )
        old = importlib.import_module('ops_runtime')
        current = importlib.import_module('lotusim_image_generator.telemetry.runtime')
        with patch.object(old, 'process_birth', return_value='fixture'):
            self.assertEqual(current.process_birth(123), 'fixture')

    def test_paths_do_not_depend_on_working_directory(self):
        self.assertEqual(TOOLS_ROOT.parent, CORE_ROOT)
        self.assertEqual(UI_ROOT, CORE_ROOT / 'tools/ops_dashboard_ui')
        for name in ['rgb_observer_worker.py', 'rgb_verify_instances.py', 'mesh_integration.py']:
            self.assertEqual(legacy_script(name).parent, TOOLS_ROOT)
            self.assertTrue(legacy_script(name).is_file())
        for unsafe in ('../outside.py', '/outside.py', 'worker.txt', '..\\outside.py'):
            with self.assertRaises(ValueError):
                legacy_script(unsafe)

    def test_stable_entry_help_from_unrelated_working_directory(self):
        for name in (
            'ops_dashboard.py',
            'plan_maritime_traffic.py',
            'mesh_integration.py',
            'rgb_observer.py',
            'rgb_observer_worker.py',
            'rgb_verify_instances.py',
            'rgb_validate.py',
        ):
            with self.subTest(entry=name):
                result = subprocess.run(
                    [sys.executable, '-B', str(legacy_script(name)), '--help'],
                    cwd=Path('/private/tmp') if Path('/private/tmp').is_dir() else Path('/tmp'),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)

    def test_only_whitelisted_public_urls_map_to_regular_sources(self):
        self.assertEqual(STATIC_FILES['/app.js'], 'shell/app.js')
        self.assertEqual(STATIC_FILES['/mesh-viewer.js'], 'features/assets/mesh-viewer.js')
        self.assertNotIn('/resources.json', STATIC_FILES)
        for target in STATIC_FILES.values():
            self.assertTrue((UI_ROOT / target).is_file())
        from tests.python.dashboard.test_ops_server import ServerTests

        fixture = ServerTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.server.ui_root = UI_ROOT
        for route, relative in STATIC_FILES.items():
            with self.subTest(resource=route):
                status, headers, body = fixture.request(route)
                self.assertEqual(status, 200)
                self.assertEqual(body, (UI_ROOT / relative).read_bytes())
                self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(fixture.request('/resources.json')[0], 404)
        self.assertEqual(fixture.request('/shell/app.js')[0], 404)


if __name__ == '__main__':
    unittest.main()
