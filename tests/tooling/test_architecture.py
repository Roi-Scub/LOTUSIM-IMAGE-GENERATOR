"""Source-only architecture contracts; no runtime import, process or service."""

import ast
from pathlib import Path
import unittest

import check_architecture


class ArchitectureTests(unittest.TestCase):
    def test_package_boundaries_and_public_resources(self):
        result = check_architecture.check()
        self.assertEqual(result['domains'], 7)
        self.assertEqual(result['routes'], 13)
        self.assertGreaterEqual(result['modules'], 35)

    def test_import_scanner_includes_lazy_and_aliased_imports(self):
        source = ast.parse(
            'import a as x\nfrom b.c import y\n'
            'def f():\n    from d.e import z\n    import q as w\n'
        )
        self.assertEqual(set(check_architecture.imported_names(source)), {'a', 'b.c', 'd.e', 'q'})

    def test_relative_and_root_imports_cannot_bypass_domain_rules(self):
        source = ast.parse(
            'from .. import dashboard\nfrom ..engines import registry\nfrom lotusim_image_generator import assets\n'
        )
        self.assertEqual(
            set(check_architecture.imported_names(source, 'lotusim_image_generator.traffic')),
            {
                'lotusim_image_generator.dashboard',
                'lotusim_image_generator.engines',
                'lotusim_image_generator.assets',
            },
        )

    def test_all_first_party_python_is_compatible_with_python_39(self):
        root = check_architecture.ROOT
        folders = [
            root / 'scripts',
            root / 'tests',
            root / 'components/LOTUSim/tools',
            root / 'components/LOTUSim/tests',
        ]
        for folder in folders:
            for path in folder.rglob('*.py'):
                with self.subTest(source=path.relative_to(root).as_posix()):
                    ast.parse(path.read_text(encoding='utf-8'), feature_version=(3, 9))


if __name__ == '__main__':
    unittest.main()
