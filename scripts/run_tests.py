#!/usr/bin/env python3
"""Run isolated regression suites; never launches a simulator, engine or browser.

Python discovery and portable-tooling discovery run in separate processes so
their tests packages cannot shadow each other. Browser QA and live integration
scripts are opt-in commands documented in docs/ARCHITECTURE_CODE.md.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'components/LOTUSim'


def environment(*import_roots):
    result = dict(os.environ)
    inherited = result.get('PYTHONPATH', '')
    result['PYTHONPATH'] = os.pathsep.join(
        [*(str(path) for path in import_roots), *([inherited] if inherited else [])]
    )
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all', 'python', 'tooling', 'web'), default='all')
    parser.add_argument('--pattern', default='test_*.py', help='Python test filename pattern')
    args = parser.parse_args()
    suites = ('tooling', 'python', 'web') if args.suite == 'all' else (args.suite,)
    if 'python' in suites:
        missing = [name for name in ('numpy', 'PIL') if importlib.util.find_spec(name) is None]
        if missing:
            parser.error(
                'Missing test dependencies: '
                + ', '.join(missing)
                + '. Install requirements-test.txt in the development environment.'
            )
    for suite in suites:
        print('Regression suite: ' + suite, flush=True)
        if suite in ('python', 'tooling'):
            component = suite == 'python'
            directory = CORE if component else ROOT
            test_root = 'tests/python' if component else 'tests/tooling'
            command = [
                sys.executable,
                '-m',
                'unittest',
                'discover',
                '-s',
                test_root,
                '-t',
                '.',
                '-p',
                args.pattern,
            ]
            subprocess.run(
                command,
                cwd=directory,
                env=environment(directory / ('tools' if component else 'scripts'), directory),
                check=True,
            )
        else:
            node = shutil.which('node')
            if node is None:
                parser.error('Node.js is required for the Web regression suite')
            for path in sorted((CORE / 'tests/web').glob('test_*.cjs')):
                subprocess.run(
                    [node, str(path), str(CORE / 'tools/ops_dashboard_ui')],
                    cwd=CORE,
                    check=True,
                )
    print('Regression suites passed. Runtime and open services were not changed.')


if __name__ == '__main__':
    main()
