"""The Claude Code ``Stop`` hook for the voice package.

Claude runs ``Stop`` hooks synchronously, so a hook that does the speaking
itself would stall every turn settle by the length of the speech. This hook
therefore detaches (KTD2): it reads the hook payload from standard input
once, compares the payload's ``session_id`` against the sticky binding with
a pure local file read, and — only when this session is the bound one —
writes the response text to a unique payload file and starts the speak
script as a fully detached child. It then exits 0 immediately. It never
blocks on, waits for, or reads back from the child; the harness timeout in
``hooks.json`` is a backstop, not a budget.

Only the bound session may speak (R3): unbound, mismatched, absent, or
unreadable binding, or an empty ``last_assistant_message``, reads as
silence — no spawn, no payload file, no sound. The response text comes
only from the payload's ``last_assistant_message``; this hook never reads
the screen or the transcript file. A hook must never break a turn, so
every path — including malformed input and unexpected failure — exits 0.

The hook does not import the speak script, clean Markdown, or call the
speech provider: it hands the text off by argv and file (KTD1/KTD2) and
the speak path owns the rest.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import binding  # noqa: E402
import process  # noqa: E402
import settings  # noqa: E402

#: The speak script the detached child runs, resolved from this hook file
#: to the portable package root. The hook spawns it by argv and never
#: imports it, so the speak path can land independently.
SPEAK_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "speak.py"


def _read_payload() -> dict | None:
    """Read the hook payload from stdin exactly once; ``None`` unless it is a JSON object."""
    try:
        raw = sys.stdin.read()
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def main() -> int:
    try:
        payload = _read_payload()
        if payload is None:
            return 0
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return 0
        record = binding.read_binding()
        if record is None or record.session_id != session_id:
            return 0
        text = payload.get("last_assistant_message")
        if not isinstance(text, str) or not text:
            return 0
        payload_path = settings.state_dir() / f"speak-{uuid.uuid4()}.json"
        payload_path.write_text(json.dumps({"text": text}) + "\n", encoding="utf-8")
        process.spawn_detached(
            [sys.executable, str(SPEAK_SCRIPT), str(payload_path)]
        )
    except Exception:
        # A hook must never break a turn: any failure reads as silence.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
