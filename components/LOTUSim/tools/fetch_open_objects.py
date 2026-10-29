#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.assets.fetch_objects."""

import sys

from lotusim_image_generator.assets import fetch_objects as _implementation

if __name__ == '__main__':
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
