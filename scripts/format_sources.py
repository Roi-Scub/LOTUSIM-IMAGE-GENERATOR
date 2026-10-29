#!/usr/bin/env python3
"""Check (default) or format first-party sources without touching running projects."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = (
    'scripts/',
    'tests/',
    'components/LOTUSim/tests/',
    'components/LOTUSim/scripts/',
    'components/LOTUSim/tools/',
    'components/LOTUSim/systems/',
    'components/LOTUSim-Unity-modules/Assets/Editor/',
    'components/LOTUSim-Unity-modules/Assets/Scripts/Dataset/',
    'components/LOTUSim-Unity-modules/Assets/Resources/Dataset/',
    'references/modified-sources/LOTUSim/systems/',
    'references/modified-sources/LOTUSim-Unity-modules/Assets/Scripts/',
)


def source_paths(root):
    output = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=root,
        env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
    ).decode('utf-8')
    return sorted(
        set(
            name
            for name in output.split('\0')
            if name
            and name.startswith(PREFIXES)
            and '/vendor/' not in name
            and '/RosMessages/' not in name
            and '/artifacts/' not in name
            and not name.startswith(
                ('qa/', 'components/LOTUSim/qa/', 'components/LOTUSim-Unity-modules/qa/')
            )
        )
    )


def run(command, root):
    subprocess.run(command, cwd=root, check=True)


def shader_text(source, clang_format, root):
    """Format only HLSL regions; ShaderLab commands are not C++ syntax."""
    pattern = re.compile(r'(?ms)^([ \t]*)(HLSLINCLUDE|HLSLPROGRAM)\s*\n(.*?)^\1ENDHLSL\b')

    def region(match):
        indent, keyword, body = match.groups()
        code = textwrap.dedent(body).strip() + '\n'
        formatted = subprocess.check_output(
            [
                clang_format,
                '--assume-filename=' + str(root / 'shader.hlsl'),
                '--style={BasedOnStyle: InheritParentConfig, BreakBeforeBraces: Allman}',
            ],
            input=code.encode('utf-8'),
            cwd=root,
        ).decode('utf-8')
        return indent + keyword + '\n' + textwrap.indent(formatted, indent) + indent + 'ENDHLSL'

    result, count = pattern.subn(region, source)
    if not count:
        raise ValueError('No recognized HLSL region; source preserved')
    result = re.sub(
        r'(?m)^([ \t]*)Blend (\w+) ZWrite (\w+) ZTest (\w+) Cull (\w+)[ \t]*$',
        lambda m: '\n'.join(
            m[1] + key + ' ' + m[index]
            for index, key in enumerate(('Blend', 'ZWrite', 'ZTest', 'Cull'), 2)
        ),
        result,
    )
    return result


def require_executable(name):
    result = shutil.which(name)
    if not result:
        raise ValueError('Development tool missing: ' + name + '; see docs/CONVENTIONS_CODE.md')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Verify only (default)')
    mode.add_argument(
        '--write', action='store_true', help='Format explicitly selected source files'
    )
    parser.add_argument(
        '--language', choices=('all', 'python', 'web', 'cpp', 'csharp', 'shell'), default='all'
    )
    parser.add_argument('--black', default='black')
    parser.add_argument('--clang-format', default='clang-format')
    args = parser.parse_args()
    names = source_paths(ROOT)
    for name in names:
        target = ROOT / name
        if not target.is_file() or target.is_symlink():
            raise ValueError('Source must be a regular file: ' + name)
        target.resolve(strict=True).relative_to(ROOT)

    if args.language in ('all', 'python'):
        paths = [
            name for name in names if name.endswith('.py') and not name.startswith('references/')
        ]
        run(
            [
                require_executable(args.black),
                '--safe',
                '--quiet',
                *([] if args.write else ['--check']),
                *paths,
            ],
            ROOT,
        )
        print('Python:', len(paths), 'files checked' if not args.write else 'files formatted')

    if args.language in ('all', 'web'):
        paths = [name for name in names if name.endswith(('.js', '.cjs', '.mjs', '.css', '.html'))]
        prettier = ROOT / 'node_modules/prettier/bin/prettier.cjs'
        if not prettier.is_file():
            raise ValueError('Run npm ci --ignore-scripts before checking web formatting')
        run(
            [
                require_executable('node'),
                str(prettier),
                '--write' if args.write else '--check',
                *paths,
            ],
            ROOT,
        )

    if args.language in ('all', 'cpp'):
        tool = require_executable(args.clang_format)
        paths = [name for name in names if name.endswith(('.cpp', '.hpp', '.h', '.c'))]
        run(
            [tool, '--style=file', *(['-i'] if args.write else ['--dry-run', '--Werror']), *paths],
            ROOT,
        )
        shaders = [name for name in names if name.endswith('.shader')]
        for name in shaders:
            path = ROOT / name
            before = path.read_text(encoding='utf-8')
            after = shader_text(before, tool, ROOT)
            if before == after:
                continue
            if not args.write:
                raise ValueError('Shader formatting required: ' + name)
            path.write_text(after, encoding='utf-8')
        print('C++:', len(paths), 'files; HLSL:', len(shaders), 'files')

    if args.language in ('all', 'csharp'):
        run(
            [
                sys.executable,
                str(ROOT / 'scripts/format_csharp.py'),
                '--write' if args.write else '--check',
            ],
            ROOT,
        )

    if args.language in ('all', 'shell'):
        paths = [name for name in names if name.endswith(('.sh', '.bash', '.command'))]
        for name in paths:
            run([require_executable('bash'), '-n', name], ROOT)
        print('Bash:', len(paths), 'syntax checks; existing launcher layout preserved')
    print('Running projects, assets, generated messages and datasets were not modified.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print('Formatting refused: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
