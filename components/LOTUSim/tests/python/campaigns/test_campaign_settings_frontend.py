"""Run the buildless settings editor contracts without a browser or service."""

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which('node'), 'Node is needed for frontend contracts')
class SettingsFrontendTests(unittest.TestCase):
    def test_continuous_capture_cadence(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_capture_cadence_ui.cjs')],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('capture-cadence UI checks passed', result.stdout)

    def test_settings_to_cooperative_traffic_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_settings_traffic_generation_ui.cjs')],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('settings-to-cooperative-traffic UI checks passed', result.stdout)

    def test_javascript_syntax(self):
        subprocess.run(
            ['node', '--check', str(ROOT / 'tools/ops_dashboard_ui/features/settings/settings.js')],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_functional_settings_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_campaign_settings_ui.cjs')],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('campaign settings UI checks passed', result.stdout)

    def test_dual_engine_settings_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_dual_engine_settings_ui.cjs')],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('baseline and dual-engine campaign settings UI checks passed', result.stdout)

    def test_engine_neutral_settings_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_engine_neutral_settings_ui.cjs')],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('baseline and engine-neutral settings UI checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
