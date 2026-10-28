#!/usr/bin/env python3
"""Start the loopback dashboard, preferring the complete local runtime if installed."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def default_roots():
    runtime = ROOT / 'runtime'
    complete = ((runtime / 'LOTUSim/tools/ops_dashboard.py').is_file() or
                ((runtime / 'LOTUSim/flake.nix').is_file() and
                 (runtime / 'LOTUSim-Unity-modules/ProjectSettings/ProjectVersion.txt').is_file()))
    base = runtime if complete else ROOT / 'components'
    return base / 'LOTUSim', base / 'LOTUSim-Unity-modules'


def main():
    core_default, unity_default = default_roots()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, default=core_default)
    parser.add_argument('--unity', type=Path, default=unity_default)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--no-docker', action='store_true')
    args = parser.parse_args()
    core = args.core.resolve(strict=True)
    unity = args.unity.resolve()
    server = core / 'tools/ops_dashboard.py'
    if not server.is_file():
        parser.error('Dashboard source not found in the selected LOTUSim root')
    command = [sys.executable, str(server), '--core', str(core), '--unity', str(unity),
               '--port', str(args.port)]
    if args.no_docker:
        command.append('--no-docker')
    print('LOTUSim data: ' + str(core), flush=True)
    print('Optional legacy Unity adapter data: ' + str(unity), flush=True)
    os.execv(sys.executable, command)


if __name__ == '__main__':
    main()
