#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.vision.regions."""

import sys

from lotusim_image_generator.vision import regions as _implementation

sys.modules[__name__] = _implementation
