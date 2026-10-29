#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.vision.confidence."""

import sys

from lotusim_image_generator.vision import confidence as _implementation

sys.modules[__name__] = _implementation
