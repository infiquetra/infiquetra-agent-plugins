"""Import bootstrap for Fleet Core's own tests.

Tests import ``fleet_commons`` from this package's ``scripts/`` directory.
They never load ``fleet_commons_shim``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
