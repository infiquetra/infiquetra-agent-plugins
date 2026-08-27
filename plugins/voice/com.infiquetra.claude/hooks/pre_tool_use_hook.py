"""The Claude Code ``PreToolUse`` hook for the voice package (KTD7; X1).

This hook observes tool invocations during an Auralis-originated voice turn:
1. Reads the hook payload from standard input once (``session_id``, ``tool_name``,
   ``tool_input``, ``tool_use_id``).
2. Verifies that the single current-turn record exists for ``session_id`` and is
   marked as an Auralis-originated turn (KTD7).
3. If an allow-list is configured in the voice policy store, only tool names
   present in the list are recorded; an empty allow-list records all tools (KTD7).
4. Records the observation into the current turn record via ``turn_record.record_tool_observation``.
5. Always exits 0 with no standard output on every path: observe-only, never
   emits a permission decision, and never mutates the permission flow (KTD7).

A hook must never break a turn, so every path — including malformed input,
unavailability, and unexpected errors — exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import turn_record  # noqa: E402
import voice_policy  # noqa: E402


def _read_payload() -> dict | None:
    """Read the hook payload from stdin exactly once; ``None`` unless a JSON object."""
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
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return 0
        tool_input = payload.get("tool_input")
        tool_use_id = payload.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not tool_use_id:
            return 0

        # Check that the active turn record is an Auralis-originated turn for this session (KTD7)
        rec = turn_record.read_turn_record()
        if rec is None or rec.session_id != session_id:
            return 0
        if rec.origin != turn_record.ORIGIN_AURALIS:
            return 0

        # Check policy tool allow-list (KTD7)
        policy = voice_policy.read_policy()
        if policy.tool_allowlist and tool_name not in policy.tool_allowlist:
            return 0

        # Record tool observation into the single turn record (KTD7, KTD11)
        try:
            turn_record.record_tool_observation(
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_use_id=tool_use_id,
            )
        except Exception:
            # On lock busy or error, drop observation and exit 0
            return 0

    except Exception:
        # A hook must never break a turn: any failure exits 0 silently.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
