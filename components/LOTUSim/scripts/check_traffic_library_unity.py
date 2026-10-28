#!/usr/bin/env python3
"""Compile only new library importer against cached Editor refs, never run Unity.

The full cached Editor response compiles existing sources plus the staged files;
all compiler outputs go to an isolated temporary directory. No project file,
scene, AssetDatabase, license client, Play, GPU or ROS process is started.
"""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unity', type=Path, required=True)
    parser.add_argument('--editor', type=Path, required=True, help='Unity.app/Contents')
    args = parser.parse_args()
    unity = args.unity.resolve(strict=True)
    stage = Path(__file__).resolve().parents[1]
    source_directory = stage / 'unity/Assets/Editor'
    if not source_directory.is_dir():
        source_directory = unity / 'Assets/Editor'
    sources = sorted(source_directory.glob('DatasetTrafficLibrary*.cs'))
    if len(sources) != 3:
        raise SystemExit('Expected contract, builder and Editor test sources')
    responses = list((unity / 'Library/Bee/artifacts').glob('*.dag/Assembly-CSharp-Editor.rsp'))
    if not responses:
        raise SystemExit('No cached Unity Editor references; no native compile claimed')
    response = max(responses, key=lambda p: p.stat().st_mtime_ns).read_text(encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='lotusim-library-csharp-') as folder:
        output = Path(folder)
        response = re.sub(
            r'-out:"[^"]+"', '-out:"' + str(output / 'Assembly-CSharp-Editor.dll') + '"', response
        )
        response = re.sub(
            r'-refout:"[^"]+"',
            '-refout:"' + str(output / 'Assembly-CSharp-Editor.ref.dll') + '"',
            response,
        )
        additions = []
        for source in sources:
            try:
                relative = source.relative_to(unity).as_posix()
            except ValueError:
                relative = None
            if relative is None or relative not in response:
                additions.append('"' + str(source) + '"')
        response += '\n' + '\n'.join(additions) + '\n'
        target = output / 'Editor.rsp'
        target.write_text(response, encoding='utf-8')
        command = [
            str(args.editor / 'NetCoreRuntime/dotnet'),
            str(args.editor / 'DotNetSdkRoslyn/csc.dll'),
            '@' + str(target),
        ]
        completed = subprocess.run(
            command,
            cwd=unity,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=90,
        )
        print(completed.stdout)
        if completed.returncode:
            raise SystemExit(completed.returncode)
        print(
            'PASS: new library importer + 4 Editor test methods compile against cached Unity references. No Unity execution or project edit.'
        )


if __name__ == '__main__':
    main()
