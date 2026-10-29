#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.traffic.library."""

import sys

from lotusim_image_generator.traffic import library as _implementation

sys.modules[__name__] = _implementation
