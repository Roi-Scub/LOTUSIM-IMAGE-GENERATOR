#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.telemetry.runtime."""

import sys

from lotusim_image_generator.telemetry import runtime as _implementation

sys.modules[__name__] = _implementation
