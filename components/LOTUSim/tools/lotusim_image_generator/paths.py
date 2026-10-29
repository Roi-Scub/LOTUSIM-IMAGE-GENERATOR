"""Installation-relative paths shared by application domains.

The portable overlay and installed checkout have the same tools/ layout. No
working-directory assumptions, hard-coded user paths or runtime discovery are
needed. Resolving these paths does not create files or start services.
"""

from pathlib import Path
import re

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = TOOLS_ROOT.parent
UI_ROOT = TOOLS_ROOT / 'ops_dashboard_ui'


def legacy_script(name):
    """Return a stable CLI path for a subprocess, not an internal module file."""
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*\.py', name):
        raise ValueError('Expected a local Python entry point filename')
    return TOOLS_ROOT / name
