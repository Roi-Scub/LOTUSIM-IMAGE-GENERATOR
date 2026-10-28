#!/bin/bash
# Local, read-only operations dashboard. Ctrl+C stops this dashboard only.
set -e
task_root="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$task_root"
if [ -x "$task_root/.venv-vision/bin/python" ]; then
  task_python="$task_root/.venv-vision/bin/python"
else
  task_python="$(command -v python3)"
fi
exec "$task_python" "$task_root/tools/ops_dashboard.py" "$@"
