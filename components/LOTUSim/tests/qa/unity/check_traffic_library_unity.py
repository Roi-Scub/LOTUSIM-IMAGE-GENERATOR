#!/usr/bin/env python3
"""Compatibility command: verify all portable C# sources using cached Unity references.

The full checker understands the new source/GUID layout, including the importer
and its relocated Editor tests. No editor, scene import, Play or ROS call occurs.
"""

from pathlib import Path
import runpy
import sys

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[5]
    sys.path.insert(0, str(root / 'scripts'))
    runpy.run_path(str(root / 'scripts/check_unity_refactor.py'), run_name='__main__')
