"""The Claude Code ``SessionStart`` hook for the voice package.

herdr core runs the terminal this Claude session lives in, but it does not
know which Claude session that is. Voice needs the session id in two places
that cannot ask Claude directly: ``voice bind`` (run from the Voice pane, a
different terminal) and the Auralis bridge identity (resolved by the MCP
server, which receives no hook payload). Old Herdr learned the id from its
own SessionStart hook; herdr core has no such hook, so this one fills that
role for voice.

On every session start — startup, resume, clear and compact, since each can
change the session id — this hook labels its own terminal:

    hc label $HC_TERMINAL_ID voice.agent-session=<session_id>

It does nothing outside herdr core (``HC_TERMINAL_ID`` unset), for a
subagent's start (the payload carries ``agent_id``; the terminal's session
is the root one), or when the payload carries no session id. The label is
voice's own key; Herdr reads nothing from it.

A hook must never break a session, so every path, including malformed input
and a failed ``hc`` call, exits 0 and prints nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import herdr_core  # noqa: E402
import process  # noqa: E402
import settings  # noqa: E402

#: The label write is a bounded helper call under the identity budget.
HC_TIMEOUT_SECONDS = 2.0


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


def main(*, run_process=process.run) -> int:
    try:
        payload = _read_payload()
        if payload is None:
            return 0
        if payload.get("agent_id"):
            return 0
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return 0
        try:
            terminal = settings.hc_terminal_id()
        except settings.SettingsRefusal:
            return 0
        try:
            herdr_core.label_session(
                terminal,
                session_id,
                timeout=HC_TIMEOUT_SECONDS,
                run_process=run_process,
            )
        except herdr_core.CoreRefusal:
            return 0
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
