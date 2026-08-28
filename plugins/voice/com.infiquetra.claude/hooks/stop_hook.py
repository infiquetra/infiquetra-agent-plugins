"""The Claude Code ``Stop`` hook for the voice package (R22, R23, R122; KTD6).

Claude runs ``Stop`` hooks synchronously.

When this session is wire-bound to an active Auralis bridge (KTD6):
1. Resolves adapter identity and queries the bridge via ``GET /v1/current``.
2. When the active binding epoch matches this session's adapter identity:
   - Suppresses the legacy local speak path (Auralis owns speech custody);
   - Reconciles the turn record: if the captured turn reached an accepted
     authored rendering, records outcome ``authored``; otherwise records
     outcome ``fallback`` (R22, R23, R122; KTD6);
   - Exits 0 immediately without spawning a detached speak child.

On any bridge doubt (discovery failure, transport error, no active binding epoch,
or session mismatch), falls through to the legacy 0.2.1 standalone voice loop:
- Compares ``session_id`` against the local sticky binding;
- Only when bound, writes the response text to a unique payload file and
  spawns ``speak.py`` as a fully detached child (KTD2);
- If the spawn fails, cleans up the payload file;
- Exits 0 immediately.

A hook must never break a turn, so every path — including malformed input and
unexpected errors — exits 0.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import adapter_identity  # noqa: E402
import binding  # noqa: E402
import bridge_client  # noqa: E402
import process  # noqa: E402
import settings  # noqa: E402
import turn_record  # noqa: E402

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

        # KTD6: Check if this session is wire-bound to an active Auralis bridge
        is_wire_bound = False
        try:
            identity = adapter_identity.resolve_adapter_identity()
            if adapter_identity.matches_session(identity, session_id):
                # Check bridge snapshot with internal 1,000 ms budget (timeout budget table)
                client = bridge_client.BridgeClient()
                snapshot = client.get_current()
                if (
                    snapshot.binding is not None
                    and snapshot.binding.identity == identity
                ):
                    is_wire_bound = True
        except Exception:
            # Any bridge doubt -> fall through to legacy path
            is_wire_bound = False

        if is_wire_bound:
            # Wire-bound: reconcile turn record outcome and suppress local speech
            try:
                rec = turn_record.read_turn_record()
                if rec is not None and rec.session_id == session_id:
                    has_accepted = any(
                        sub.get("disposition") == "accepted"
                        for sub in rec.submissions
                        if isinstance(sub, dict)
                    )
                    outcome = (
                        turn_record.OUTCOME_AUTHORED
                        if has_accepted
                        else turn_record.OUTCOME_FALLBACK
                    )
                    turn_record.settle_outcome(session_id=session_id, outcome=outcome)
            except Exception:
                # On busy or error, leave outcome unsettled; still suppress speech
                pass
            return 0

        # Legacy 0.2.1 speak path
        record = binding.read_binding()
        if record is None or record.session_id != session_id:
            return 0
        text = payload.get("last_assistant_message")
        if not isinstance(text, str) or not text:
            return 0
        payload_path = settings.state_dir() / f"speak-{uuid.uuid4()}.json"
        payload_path.write_text(json.dumps({"text": text}) + "\n", encoding="utf-8")
        try:
            process.spawn_detached(
                [sys.executable, str(SPEAK_SCRIPT), str(payload_path)]
            )
        except Exception:
            # The spawn failed, so no child will consume this payload: remove
            # it so failed hooks do not accumulate orphaned files.
            payload_path.unlink(missing_ok=True)
            return 0
    except Exception:
        # A hook must never break a turn: any failure reads as silence.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
