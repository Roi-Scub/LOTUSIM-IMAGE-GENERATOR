"""Keep the documentation links and model credits consistent with the export."""

import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


class DocumentationTests(unittest.TestCase):
    def test_local_documentation_links_resolve(self):
        documents = [ROOT / 'README.md', ROOT / 'CHANGELOG.md', *(ROOT / 'docs').glob('*.md')]
        for document in documents:
            prose = re.sub(r'(?ms)^```.*?^```[^\n]*$', '', document.read_text())
            prose = re.sub(r'`[^`\n]+`', '', prose)
            for target in re.findall(r'\[[^\]]+\]\(([^)\n]+)\)', prose):
                parsed = urlsplit(target.strip('<>'))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                path = (document.parent / unquote(parsed.path)).resolve()
                with self.subTest(document=document.name, link=target):
                    self.assertTrue(path.is_relative_to(ROOT))
                    self.assertTrue(path.exists(), str(path))

    def test_readme_credits_every_external_model(self):
        readme = (ROOT / 'README.md').read_text()
        library = ROOT / 'components/LOTUSim-Unity-modules/ThirdParty'
        records = []
        for group in ('OpenBoats', 'OpenObjects'):
            records.extend(json.loads((library / group / 'manifest.json').read_text()))
        self.assertEqual(len(records), len({record['key'] for record in records}))
        for record in records:
            with self.subTest(model=record['key']):
                self.assertIn('`' + record['key'] + '`', readme)
                self.assertIn(record['author'], readme)
                self.assertIn(record['source'], readme)

    def test_all_exported_models_have_an_explicit_credit_group(self):
        readme = (ROOT / 'README.md').read_text()
        for model in (ROOT / 'components/LOTUSim/assets/models').iterdir():
            if model.is_dir():
                with self.subTest(model=model.name):
                    self.assertIn('`' + model.name + '`', readme)

    def test_asset_grants_preserve_code_and_third_party_boundaries(self):
        notices = [
            ROOT / 'components/LOTUSim/ORIGINAL_ASSETS_LICENSE.md',
            ROOT / 'components/LOTUSim-Unity-modules/ORIGINAL_ASSETS_LICENSE.md',
        ]
        for path in notices:
            text = path.read_text()
            with self.subTest(notice=str(path.relative_to(ROOT))):
                self.assertIn('Gabriel Ricardon', text)
                self.assertIn('https://creativecommons.org/licenses/by/4.0/', text)
                self.assertIn('EPL-2.0', text)
                self.assertIn('Exclusions', text)
                self.assertIn('fremm', text.lower())


if __name__ == '__main__':
    unittest.main()
