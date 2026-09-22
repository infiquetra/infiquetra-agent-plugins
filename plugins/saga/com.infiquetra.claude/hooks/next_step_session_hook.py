#!/usr/bin/env python3
"""SessionStart hook: announce the run record's next step, and suppress it when the step is done.

Issue #1029. A new session in a repository with a live run opens knowing where the run is; a new
session in a repository whose run is finished, or which has no run at all, opens knowing nothing —
which is the point. The session that produced this card opened carrying a ``next_step`` left over
from an old saga tick, and a step announced after it is finished is worse than no announcement,
because it reads as an instruction.

Matched on ``startup|resume``. The ``compact`` source is the spore's
(``compact_spore_session_hook.py``), which re-injects the whole frozen block including the run
record; this hook is the cold-start reader the plugin did not have.

The suppression rule itself lives in ``scripts/next_step_context.py`` so the spore's renderer and
the prompt-submission suggestion read the same rule (plan KTD1, KTD5).

Properties, all by design and all shared with the hooks beside it:
  - ADVISORY: it injects context and can never block, refuse, or fail a turn.
  - QUIET on every error: an unreadable payload, a missing store, a cwd outside a repository, and
    an unreadable record each produce no output.
  - Exit code: 0, always.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import next_step_context
except Exception:  # noqa: BLE001 — an uninstallable import is an absent announcement, not a failure
    sys.exit(0)

#: The sources this hook answers. ``compact`` belongs to the spore hook, which carries the record
#: in its frozen block; announcing it twice at one boundary is noise.
SOURCES = frozenset({"startup", "resume"})


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:  # noqa: BLE001
        sys.exit(0)
    if not isinstance(payload, dict):
        sys.exit(0)

    if payload.get("source") not in SOURCES:
        sys.exit(0)

    cwd = payload.get("cwd")
    if not cwd or not isinstance(cwd, str):
        sys.exit(0)

    try:
        announcement = next_step_context.next_step_for(Path(cwd))
    except Exception:  # noqa: BLE001
        sys.exit(0)

    if announcement is None:
        # No record, no resolvable issue, or a record whose step is done. Say nothing.
        sys.exit(0)

    with contextlib.suppress(Exception):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": next_step_context.render(announcement),
                    }
                }
            )
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
