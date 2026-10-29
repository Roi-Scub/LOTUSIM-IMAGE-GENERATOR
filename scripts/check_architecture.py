#!/usr/bin/env python3
"""Check source boundaries and naming without importing or starting the application."""

import ast
from importlib.util import resolve_name
import json
from pathlib import Path
import re

import check_unity_layout

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PREFIX = 'lotusim_image_generator'
ALLOWED_DEPENDENCIES = {
    'assets': {'assets', 'paths'},
    'campaigns': {'campaigns', 'assets', 'engines', 'paths'},
    'engines': {'engines', 'assets', 'paths'},
    'traffic': {'traffic', 'campaigns', 'engines', 'telemetry', 'paths'},
    'vision': {'vision', 'telemetry', 'paths'},
    'telemetry': {'telemetry', 'engines', 'paths'},
    'dashboard': {'dashboard', 'assets', 'campaigns', 'engines', 'traffic', 'telemetry', 'paths'},
}


def imported_names(tree, package=PACKAGE_PREFIX):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = (
                resolve_name('.' * node.level + (node.module or ''), package)
                if node.level
                else node.module
            )
            if base == PACKAGE_PREFIX:
                yield from (base + '.' + alias.name for alias in node.names)
            elif base:
                yield base
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)


def check(root=ROOT):
    root = Path(root)
    core = root / 'components/LOTUSim'
    tools = core / 'tools'
    package = tools / PACKAGE_PREFIX
    legacy_names = {path.stem for path in tools.glob('*.py')}
    errors = []
    for path in sorted(package.rglob('*.py')):
        relative = path.relative_to(package)
        if not re.fullmatch(r'[a-z_][a-z0-9_]*', path.stem):
            errors.append(str(relative) + ': Python modules use snake_case')
        tree = ast.parse(
            path.read_text(encoding='utf-8'), filename=str(relative), feature_version=(3, 9)
        )
        domain = relative.parts[0] if len(relative.parts) > 1 else None
        if domain is not None and domain not in ALLOWED_DEPENDENCIES:
            errors.append(str(relative) + ': undeclared application domain')
        current_package = PACKAGE_PREFIX + (
            '.' + '.'.join(relative.parts[:-1]) if len(relative.parts) > 1 else ''
        )
        if path.stem == '__init__' and len(relative.parts) > 1:
            current_package = PACKAGE_PREFIX + '.' + '.'.join(relative.parts[:-1])
        for dependency in imported_names(tree, current_package):
            first = dependency.split('.')[0]
            if first in legacy_names:
                errors.append(str(relative) + ': internal import uses compatibility entry ' + first)
            if first in {'tests', 'scripts'}:
                errors.append(
                    str(relative) + ': application must not import tests or repository scripts'
                )
            if first == PACKAGE_PREFIX and domain is not None:
                target = dependency.split('.')[1]
                if target not in ALLOWED_DEPENDENCIES.get(domain, set()):
                    errors.append(str(relative) + ': forbidden domain dependency ' + target)
        for folder in path.parents:
            if folder == tools:
                break
            if not (folder / '__init__.py').is_file():
                errors.append(str(relative) + ': missing package initializer')

    # These scripts are compatibility entry points, not a second business-logic tree.
    for path in sorted(tools.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        implementations = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(PACKAGE_PREFIX + '.')
        ]
        if len(implementations) != 1 or any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            for node in tree.body
        ):
            errors.append(path.name + ': compatibility entries must only delegate')

    ui = tools / 'ops_dashboard_ui'
    routes = json.loads((ui / 'resources.json').read_text(encoding='utf-8'))
    if set(routes) != {
        '/',
        '/index.html',
        '/app.js',
        '/alerts.js',
        '/styles.css',
        '/operations-ux.css',
        '/settings.js',
        '/settings.css',
        '/assets.js',
        '/assets.css',
        '/mesh-viewer.js',
        '/traffic.js',
        '/traffic.css',
    }:
        errors.append('Unexpected public static routes')
    for route, value in routes.items():
        relative = Path(value)
        if relative.is_absolute() or '..' in relative.parts:
            errors.append('Unsafe static resource: ' + route)
            continue
        target = ui / relative
        if target.is_symlink() or not target.is_file():
            errors.append('Missing regular static resource: ' + route)
        elif not target.resolve().is_relative_to(ui.resolve()):
            errors.append('Static resource escapes UI root: ' + route)
    html = (ui / 'index.html').read_text(encoding='utf-8')
    for route in re.findall(r'(?:src|href)="(/[^"#?]+\.(?:js|css))"', html):
        if route not in routes:
            errors.append('HTML resource has no static route: ' + route)
    for folder in (root / 'scripts', core / 'scripts'):
        for path in folder.iterdir():
            if path.is_file() and path.name.startswith(('test_', 'qa_')):
                errors.append(str(path.relative_to(root)) + ': test belongs under tests/')
    if errors:
        raise ValueError('\n'.join(errors))
    unity = check_unity_layout.check(root)
    return {
        'unityScripts': unity['scripts'],
        'domains': len(ALLOWED_DEPENDENCIES),
        'modules': len(list(package.rglob('*.py'))),
        'routes': len(routes),
    }


def main():
    result = check()
    print(
        'Architecture PASS: {domains} domains, {modules} Python modules, {routes} stable Web routes.'.format(
            **result
        )
    )


if __name__ == '__main__':
    main()
