"""Static UI contracts and dependency-free Node behavior checks; no services."""

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
UI = ROOT / 'tools/ops_dashboard_ui'


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = []
        self.resources = []
        self.labels = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'id' in values:
            self.ids.append(values['id'])
        if tag in ('script', 'link', 'img'):
            self.resources.extend(values[k] for k in ('src', 'href') if k in values)
        if tag == 'label' and 'for' in values:
            self.labels.append(values['for'])


class OpsUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required for local diagnostics contracts')
    def test_local_diagnostics_and_frozen_journal(self):
        for name, expected in [
            ('test_ops_alerts.cjs', 'alert classification'),
            ('test_ops_journal.cjs', 'journal freeze'),
            ('test_context_disclosures_ui.cjs', 'contextual disclosure'),
        ]:
            result = subprocess.run(
                ['node', str(ROOT / 'tests/web' / name), str(UI)],
                capture_output=True,
                text=True,
                check=True,
                timeout=20,
            )
            self.assertIn(expected, result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for traffic-library UI contracts')
    def test_traffic_library_generation_and_revisions(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_traffic_library_ui.cjs'), str(UI)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('traffic-library generation and UI checks passed', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for traffic UI contracts')
    def test_offline_traffic_editing_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_traffic_ui.cjs'), str(UI)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('traffic math and UI checks passed', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for UI contracts')
    def test_engine_neutral_renderer_provenance(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_engine_neutral_ops_ui.cjs'), str(UI)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('baseline and engine-neutral operations UI checks passed', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for UI contracts')
    def test_scene_preparation_agent_behavior(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_scene_preparation_ui.cjs'), str(UI)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        self.assertIn('scene-preparation behavior checks passed', result.stdout)

    @classmethod
    def setUpClass(cls):
        cls.html = (UI / 'index.html').read_text()
        cls.js = (UI / 'shell/app.js').read_text()
        cls.css = (UI / 'shell/styles.css').read_text()
        cls.document = Document(cls.html)

    def test_unique_element_ids(self):
        self.assertEqual(len(self.document.ids), len(set(self.document.ids)))

    def test_literal_script_targets_exist(self):
        targets = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", self.js))
        self.assertFalse(targets - set(self.document.ids))

    def test_labels_point_to_real_inputs(self):
        self.assertFalse(set(self.document.labels) - set(self.document.ids))

    def test_no_external_dependencies(self):
        self.assertTrue(self.document.resources)
        self.assertTrue(all(value.startswith('/') for value in self.document.resources))
        self.assertNotRegex(self.css, r'@import|https?://')

    def test_four_functional_routes(self):
        for key in ('overview', 'agents', 'journal', 'reports'):
            self.assertIn('id="page-' + key + '"', self.html)
            self.assertIn('href="#' + key + '"', self.html)
        self.assertIn("window.addEventListener('hashchange', navigate)", self.js)

    def test_real_sse_and_polling_contract(self):
        self.assertIn("new EventSource('/api/events')", self.js)
        self.assertIn("addEventListener('state', receive)", self.js)
        self.assertIn("fetch('/api/state'", self.js)

    def test_no_simulation_mutation_controls(self):
        self.assertNotRegex(self.js, r'method\s*:\s*[\'"](?:POST|PUT|PATCH|DELETE)')
        self.assertNotIn('innerHTML', self.js)
        self.assertNotIn('document.write', self.js)

    def test_live_preview_requires_recency(self):
        self.assertRegex(
            self.js,
            r"preview\.live\s*===\s*true\s*&&\s*preview\.kind\s*===\s*['\"]live['\"]",
        )
        self.assertRegex(self.js, r'\bpreviewAge\s*<=\s*15(?![\d.])')
        self.assertIn('Dernière image · historique', self.js)

    def test_responsive_and_reduced_motion(self):
        self.assertRegex(self.css, r'@media\s*\(\s*max-width\s*:\s*760px\s*\)')
        self.assertRegex(self.css, r'@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)')
        self.assertRegex(self.css, r'\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;?\s*\}')

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable; UI source checks still run')
    def test_javascript_parse(self):
        subprocess.run(
            ['node', '--check', str(UI / 'shell/app.js')],
            check=True,
            capture_output=True,
            text=True,
        )

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable; UI source checks still run')
    def test_interactive_data_contract(self):
        result = subprocess.run(
            ['node', str(ROOT / 'tests/web/test_ops_ui_behavior.cjs'), str(UI)],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertIn('behavior checks passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
