#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.vision.postprocess."""

import sys

from lotusim_image_generator.vision import postprocess as _implementation

sys.modules[__name__] = _implementation
