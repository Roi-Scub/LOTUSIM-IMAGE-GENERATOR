#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.assets.conversion."""

import sys

from lotusim_image_generator.assets import conversion as _implementation

sys.modules[__name__] = _implementation
