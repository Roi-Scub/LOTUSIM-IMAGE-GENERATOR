#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.telemetry.renderer."""

import sys

from lotusim_image_generator.telemetry import renderer as _implementation

sys.modules[__name__] = _implementation
