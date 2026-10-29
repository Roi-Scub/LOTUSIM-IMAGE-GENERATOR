#!/usr/bin/env python3
"""Compatibility entry point; implementation: lotusim_image_generator.campaigns.settings."""

import sys

from lotusim_image_generator.campaigns import settings as _implementation

sys.modules[__name__] = _implementation
