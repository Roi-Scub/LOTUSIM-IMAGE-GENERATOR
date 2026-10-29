#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.dashboard.collector."""

import sys

from lotusim_image_generator.dashboard import collector as _implementation

sys.modules[__name__] = _implementation
