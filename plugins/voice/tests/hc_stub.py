"""A fake herdr core command for tests that run voice code as a real process.

``write_fake_hc`` writes an executable that answers ``hc get <t> --json``
with one terminal record, the shape herdr core prints, and exits 0 for any
other command. Tests point ``VOICE_HC_BIN`` at it and set ``HC_TERMINAL_ID``
to the record's address, so no test reaches the real herdr core.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

__all__ = ["terminal_record", "write_fake_hc"]


def terminal_record(
    *,
    address: str,
    session_id: str | None,
    state: str = "live",
    status: str | None = "idle",
) -> dict:
    """One ``hc get --json`` record with inert example values."""
    labels = {} if session_id is None else {"voice.agent-session": session_id}
    return {
        "address": address,
        "name": "example-agent",
        "state": state,
        "labels": labels,
        "status": None if status is None else {"state": status},
        "argv": ["claude"],
        "cwd": "/tmp/example",
    }


def write_fake_hc(path: Path, record: dict) -> Path:
    """Write an executable fake ``hc`` that prints ``record`` for ``get``."""
    code = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:2] == ['get']:\n"
        f"    sys.stdout.write({json.dumps(json.dumps(record))} + '\\n')\n"
    )
    path.write_text(code, encoding="utf-8")
    os.chmod(path, 0o755)
    return path
