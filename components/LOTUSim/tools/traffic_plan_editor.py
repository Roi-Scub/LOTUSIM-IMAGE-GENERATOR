#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.traffic.editor."""

import sys

from lotusim_image_generator.traffic import editor as _implementation

sys.modules[__name__] = _implementation
