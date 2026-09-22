#!/usr/bin/env python3
"""Run the agy delegation wrapper at its historical catalog path.

The implementation lives at ``skills/agy-delegate/scripts/agy_delegate.py`` so a
harness that installs the skill directory, and not the package root, still
receives the executable and the Fleet Core bundle beside it. This path remains
because the guarded-command identity, the agent prompts, and the bridge
discriminator all name ``plugins/agy/scripts/agy_delegate.py``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_IMPLEMENTATION = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "agy-delegate"
    / "scripts"
    / "agy_delegate.py"
)


if __name__ == "__main__":
    sys.argv[0] = str(_IMPLEMENTATION)
    runpy.run_path(str(_IMPLEMENTATION), run_name="__main__")
