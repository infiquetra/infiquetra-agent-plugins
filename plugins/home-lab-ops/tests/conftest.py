"""Put the team-scaffold package on sys.path for these tests.

The launcher and the tests import ``team_scaffold`` without an editable
install. Pytest loads this file before the test modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "team-scaffold" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
