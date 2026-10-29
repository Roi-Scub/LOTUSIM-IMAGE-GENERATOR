#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.engines.templates.unreal_scene."""

import sys

from lotusim_image_generator.engines.templates import unreal_scene as _implementation

sys.modules[__name__] = _implementation
