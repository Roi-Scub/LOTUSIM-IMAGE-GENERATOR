#!/usr/bin/env python3
"""Compile the generated optional C# entry point against cached Unity references.

This invokes Roslyn only: no Unity launch, project edit, import, Play or ROS call.
Requires a compatible already-compiled Unity project and local bundled compiler.
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from render_engine_agents import _unity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unity', type=Path, required=True)
    parser.add_argument('--editor', type=Path, required=True, help='Unity.app/Contents directory')
    args = parser.parse_args()
    unity = args.unity.resolve(strict=True)
    candidates = list(unity.glob('Library/Bee/artifacts/*.dag/Assembly-CSharp-Editor.rsp'))
    if not candidates:
        raise SystemExit('No cached Editor compiler response; open and compile the project first.')
    response_source = max(candidates, key=lambda item: item.stat().st_mtime_ns)
    output = Path(tempfile.mkdtemp(prefix='lotusim-generated-scene-', dir='/private/tmp'))
    # Exercise a host path with quotes, backslashes and non-ASCII characters too.
    result = _unity(
        {'totalImages': 1},
        '12345678-1234-4234-8234-123456789abc',
        'b' * 64,
        Path('/private/tmp/test "quoted"/é\\lotusim'),
    )
    generated = output / 'scene_unity.cs'
    generated.write_bytes(result['files']['scene_unity.cs'])
    response = response_source.read_text(encoding='utf-8')
    response = re.sub(r'-out:"[^"]+"', '-out:"' + str(output / 'Editor.dll') + '"', response)
    response = re.sub(
        r'-refout:"[^"]+"', '-refout:"' + str(output / 'Editor.ref.dll') + '"', response
    )
    response += '\n"' + str(generated) + '"\n'
    target = output / 'Editor.rsp'
    target.write_text(response, encoding='utf-8')
    command = [
        str(args.editor / 'NetCoreRuntime/dotnet'),
        str(args.editor / 'DotNetSdkRoslyn/csc.dll'),
        '@' + str(target),
    ]
    completed = subprocess.run(
        command, cwd=unity, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    print(completed.stdout)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    print('PASS: generated Unity scene entry point compiles; no engine execution. ' + str(output))


if __name__ == '__main__':
    main()
