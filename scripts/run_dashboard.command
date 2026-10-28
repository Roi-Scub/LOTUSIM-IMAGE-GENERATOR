#!/bin/bash
set -eu
relocation_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$relocation_root"
exec /usr/bin/python3 scripts/start_local_stack.py run dashboard
