"""Explicit public routes remain stable when frontend source files move."""

import json

from lotusim_image_generator.paths import UI_ROOT

STATIC_FILES = json.loads((UI_ROOT / 'resources.json').read_text(encoding='utf-8'))
