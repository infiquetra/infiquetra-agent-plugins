"""Make the portable ``server`` package importable from these tests.

The upstream suite lived in the Claude repository's root ``tests/`` directory
and inserted ``plugins/redis-channel`` on ``sys.path`` from that repository's
``conftest.py``. The package root is now the parent of this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))
