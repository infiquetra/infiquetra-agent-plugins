"""The Claude Code ``UserPromptSubmit`` hook for the voice package (R106, R107; KTD3, KTD4, KTD5).

This hook runs on every user prompt submission in Claude Code:
1. Reads the hook payload from standard input once to obtain ``session_id``.
2. Resolves the three-part adapter identity (``adapter_identity.resolve_adapter_identity``)
   and verifies that ``session_id`` matches ``agent_session_id`` (§5).
3. Reads the active bridge state via ``GET /v1/current`` (KTD3, §6.4).
4. Matches the binding epoch against this session's adapter identity.
5. If the session is wire-bound:
   - On an Auralis-originated turn (open turn matching this binding):
     captures ``(binding_id, turn_id)`` into the single current-turn record
     (KTD4, KTD11), consumes the armed Brief Next Turn one-shot override on
     transmission (KTD5, R107), and injects context via
     ``hookSpecificOutput.additionalContext`` containing the origin statement,
     the rendering expectation, the submission tool pointer, the plain text
     rule, and the rendered policy instructions (R106, R107).
   - On a bound turn that did not originate via Auralis (no open turn):
     injects the explicit negative signal ("This turn did not originate through
     Auralis voice. No spoken rendering is expected.") and transmits no policy
     (KTD3, R106, R107).
6. When unbound, bridge unavailable, identity unresolvable, or on session
   mismatch: emits no output and remains silent (KTD3).

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

import adapter_identity  # noqa: E402
import bridge_client  # noqa: E402
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

        # 1. Resolve adapter identity (§5)
        try:
            identity = adapter_identity.resolve_adapter_identity()
        except Exception:
            # Identity resolution refusal / missing setting -> silent exit
            return 0

        if not adapter_identity.matches_session(identity, session_id):
            return 0

        # 2. Query bridge GET /v1/current (§6.4)
        try:
            client = bridge_client.BridgeClient()
            snapshot = client.get_current()
        except Exception:
            # Bridge unavailable / discovery failed / transport error -> silent exit
            return 0

        # 3. Check binding epoch match (§6.4, §8, KTD3)
        if snapshot.binding is None or snapshot.binding.identity != identity:
            return 0

        # 4. Determine turn origin under the active binding
        is_originated = (
            snapshot.turn is not None
            and snapshot.turn.state == "open"
            and snapshot.turn.binding_id == snapshot.binding.binding_id
        )

        if is_originated:
            assert snapshot.turn is not None
            # Initialize turn record with captured identifiers (KTD4, KTD11)
            try:
                turn_record.init_turn(
                    session_id=session_id,
                    binding_id=snapshot.binding.binding_id,
                    turn_id=snapshot.turn.turn_id,
                    origin=turn_record.ORIGIN_AURALIS,
                )
            except turn_record.TurnRecordBusy:
                # Timeout budget table: emit no injection and exit 0
                return 0
            except Exception:
                return 0

            # Consume brief_next_turn one-shot override on transmission (KTD5, R107)
            was_brief_armed = voice_policy.consume_brief_next_turn()
            policy_instructions = voice_policy.render_instructions(brief=was_brief_armed)

            context_lines = [
                "This turn originated through Auralis voice.",
                "A spoken rendering is expected for this turn.",
                "Submit your spoken rendering via the submit_spoken_rendering tool.",
                "The rendering surface accepts plain spoken text only. Do not include Markdown formatting or fenced code blocks.",
            ]
            if policy_instructions:
                context_lines.append(policy_instructions)
            context_text = "\n\n".join(context_lines)

            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context_text,
                }
            }
            sys.stdout.write(json.dumps(output) + "\n")
            return 0
        else:
            # Bound, but non-originated turn (KTD3, R106)
            try:
                turn_record.init_turn(
                    session_id=session_id,
                    binding_id=snapshot.binding.binding_id,
                    turn_id=None,
                    origin=turn_record.ORIGIN_NOT_ORIGINATED,
                )
            except Exception:
                pass

            context_text = (
                "This turn did not originate through Auralis voice. "
                "No spoken rendering is expected."
            )
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context_text,
                }
            }
            sys.stdout.write(json.dumps(output) + "\n")
            return 0

    except Exception:
        # A hook must never break a turn: any failure exits 0 with no output.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
