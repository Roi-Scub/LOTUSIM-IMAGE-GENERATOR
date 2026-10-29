#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.engines.unity."""

import sys

from lotusim_image_generator.engines import unity as _implementation

sys.modules[__name__] = _implementation
