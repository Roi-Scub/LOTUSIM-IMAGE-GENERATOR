#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.vision.gazebo."""

import sys

from lotusim_image_generator.vision import gazebo as _implementation

sys.modules[__name__] = _implementation
