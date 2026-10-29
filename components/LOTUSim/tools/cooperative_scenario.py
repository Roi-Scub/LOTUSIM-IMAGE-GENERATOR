#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.traffic.scenario."""

import sys

from lotusim_image_generator.traffic import scenario as _implementation

sys.modules[__name__] = _implementation
