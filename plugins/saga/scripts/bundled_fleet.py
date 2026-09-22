#!/usr/bin/env python3
"""Load a Fleet Core module from the build-time bundle beside this file.

The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
resolution ladder is Claude-specific runtime discovery this package must not
retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
disk at install time and Fleet Core is never installed separately.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any


def load(name: str) -> Any:
    """Return the bundled Fleet Core module ``name`` (``tier_palette``, ``jev_widen``, ...)."""
    bundled = str(Path(__file__).resolve().parent / "_bundled")
    if bundled not in sys.path:
        sys.path.insert(0, bundled)
    return importlib.import_module(name)
