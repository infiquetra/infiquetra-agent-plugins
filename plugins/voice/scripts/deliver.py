"""Delivery path for the voice package (R16, R17, R18, R19; KTD11).

Returns a transcript to the bound Herdr agent's input box — literal text,
unsubmitted, still editable (R16) — or refuses audibly when that agent is
blocked on a human decision, holding the transcript for the operator's
explicit use or discard (R18, R19).

Delivery is a two-step sequence against the installed Herdr CLI:

1. ``herdr agent get <agent>`` re-resolves the bound agent's pane id and
   current status from the closed agent-state set (``idle``, ``working``,
   ``blocked``, ``done``, ``unknown``) under the 10-second deadline pinned
   for bounded helper calls (KTD3a).
2. ``herdr pane send-text <pane_id> <text>`` sends the transcript,
   whitespace-normalized to a single line, as literal text without Enter —
   the unsubmitted, editable delivery R16 requires.

Only the bound agent is ever targeted (R17): no broadcast, no fallback
target, no recency inference. An unresolvable bound agent is a named error,
never a reason to try another pane.

Speech is never an approval channel. When the bound agent is blocked on a
permission, approval, or other human-decision prompt, keystrokes are
choices rather than text: nothing is sent, the refusal is spoken through
the speak path, and the transcript is held in ``refused-transcript.txt``
under the state directory — one current file, replaced rather than
appended, consumed or discarded only by an explicit operator act (R19,
KTD1). A refused transcript is never delivered automatically and never
queued for automatic delivery.

The blocked-state check is not atomic with the send: the agent can become
blocked between the resolution and the send. That race is the contract's
stated residual — narrowed here, deliberately not closed. The guard belongs
to Herdr's delivery command as a proposed enhancement, and no workaround
machinery is built in this module.

The entry points are module-level so the pane and the CLI can reach them
through their lazy-import seam (KTD16): :func:`deliver`,
:func:`use_refused`, and :func:`discard_refused`.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

import binding
import process
import settings
import speak

__all__ = [
    "DeliveryRefusal",
    "AGENT_STATUS_BLOCKED",
    "BLOCKED_REFUSAL_PHRASE",
    "HERDR_TIMEOUT_SECONDS",
    "REFUSED_TRANSCRIPT_FILENAME",
    "deliver",
    "use_refused",
    "discard_refused",
]

#: Both herdr calls are bounded helper invocations and share the 10-second
#: deadline pinned for that class (KTD3a).
HERDR_TIMEOUT_SECONDS = 10.0

#: The one state, out of the closed agent-state set, that must never
#: receive keystrokes: a blocked agent is waiting on a human decision, and
#: a keystroke there is a choice, not text (R18).
AGENT_STATUS_BLOCKED = "blocked"

REFUSED_TRANSCRIPT_FILENAME = "refused-transcript.txt"

#: The short fixed phrase spoken when a blocked agent refuses the delivery
#: (KTD8's refusal entry point).
BLOCKED_REFUSAL_PHRASE = (
    "The bound session is blocked on a prompt; not delivering that."
)


class DeliveryRefusal(Exception):
    """A named refusal on the delivery path.

    Carries the reason the delivery cannot proceed so the pane can report it
    by name. A refusal never selects a different target and never
    substitutes a delivery.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def deliver(
    text: str,
    *,
    spawn: Callable = subprocess.run,
    speak_text: Callable = speak.speak,
) -> None:
    """Deliver ``text`` to the bound agent's input box, unsubmitted.

    Resolves the bound agent's pane id and current status through
    ``herdr agent get``, then sends the whitespace-normalized single-line
    transcript with ``herdr pane send-text`` — literal text, no Enter
    (R16). A blocked agent receives nothing: the refusal is spoken and the
    transcript is held for the operator's explicit use or discard (R18,
    R19). Only the bound agent is ever targeted (R17).

    The transcript is held before the refusal is spoken, so the hold
    survives even when speech itself fails. Both herdr calls go through
    U1's process helper under the pinned deadline with standard input
    closed; the seams mirror KTD12 so tests never run the real CLI.
    """
    line = _single_line(text)
    if not line:
        raise DeliveryRefusal(
            "there is nothing to deliver; the transcript is empty"
        )
    report = binding.read_binding_report()
    if report.binding is None:
        raise DeliveryRefusal(_unbound_reason(report.status))
    agent_name = report.binding.agent

    state = _resolve_agent(agent_name, spawn=spawn)
    if state["agent_status"] == AGENT_STATUS_BLOCKED:
        _hold_refused(text)
        speak_text(BLOCKED_REFUSAL_PHRASE)
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} is blocked on a human decision; "
            "nothing was sent — the transcript is held for explicit use or "
            "discard"
        )
    _send_text(state["pane_id"], line, spawn=spawn)


def use_refused(
    *,
    spawn: Callable = subprocess.run,
    speak_text: Callable = speak.speak,
) -> None:
    """Explicitly use the held refused transcript (R19).

    Reads the hold file, deletes it, then delivers that text. When the
    agent is still blocked, delivery refuses again and the transcript is
    held anew — it is never forced through. A missing hold is refused by
    name.
    """
    path = _refused_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DeliveryRefusal(
            "there is no refused transcript to use"
        ) from error
    path.unlink(missing_ok=True)
    deliver(text, spawn=spawn, speak_text=speak_text)


def discard_refused() -> None:
    """Explicitly discard the held refused transcript (R19).

    Deletes the hold file without delivering anything. A missing hold is
    refused by name.
    """
    path = _refused_path()
    if not path.exists():
        raise DeliveryRefusal("there is no refused transcript to discard")
    path.unlink(missing_ok=True)


def _refused_path() -> Path:
    return settings.state_dir() / REFUSED_TRANSCRIPT_FILENAME


def _unbound_reason(status: str) -> str:
    if status == binding.STATUS_CORRUPT:
        return (
            "the binding store cannot be read; rebind with `voice bind "
            "<agent>` before delivering"
        )
    return (
        "voice is not bound to an agent; bind one with `voice bind <agent>` "
        "before delivering"
    )


def _single_line(text: str) -> str:
    """Whitespace-normalize the transcript to a single line.

    Speech has no meaningful line structure, and a raw newline must never
    reach the terminal as Enter, so every whitespace run collapses to one
    space.
    """
    return " ".join(text.split())


def _resolve_agent(agent_name: str, *, spawn: Callable) -> dict[str, str]:
    """Re-resolve the bound agent's pane id and status at send time (KTD7).

    The binding stores a pane id, but delivery does not trust the stored
    copy: panes move between bind and deliver, and herdr is the authority
    for both. An unresolvable bound agent is a named error; nothing falls
    back to another target (R17).
    """
    try:
        result = process.run(
            ["herdr", "agent", "get", agent_name],
            timeout=HERDR_TIMEOUT_SECONDS,
            spawn=spawn,
        )
    except subprocess.TimeoutExpired as error:
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} could not be resolved: "
            f"herdr agent get passed its "
            f"{HERDR_TIMEOUT_SECONDS:.0f}-second deadline"
        ) from error
    except subprocess.CalledProcessError as error:
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} could not be resolved: "
            f"herdr agent get exited with status {error.returncode}"
        ) from error
    except OSError as error:
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} could not be resolved: "
            f"the herdr CLI cannot start ({error})"
        ) from error
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError) as error:
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} could not be resolved: "
            "herdr agent get returned no parseable agent record"
        ) from error
    record = _agent_record(payload)
    pane_id = _stated_str(record, "pane_id")
    agent_status = _stated_str(record, "agent_status")
    if pane_id is None or agent_status is None:
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} could not be resolved: "
            "herdr agent get returned no usable pane id and status"
        )
    return {"pane_id": pane_id, "agent_status": agent_status}


def _agent_record(payload: object) -> dict | None:
    """Walk the herdr envelope to the agent record, or ``None``."""
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    agent = result.get("agent")
    if not isinstance(agent, dict):
        return None
    return agent


def _stated_str(record: dict | None, field: str) -> str | None:
    """A stated string field, or ``None`` when absent, non-string, or empty."""
    if record is None:
        return None
    value = record.get(field)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _send_text(pane_id: str, line: str, *, spawn: Callable) -> None:
    """Send one single-line transcript as literal text, without Enter."""
    try:
        process.run(
            ["herdr", "pane", "send-text", pane_id, line],
            timeout=HERDR_TIMEOUT_SECONDS,
            spawn=spawn,
        )
    except subprocess.TimeoutExpired as error:
        raise DeliveryRefusal(
            "delivery failed: herdr pane send-text passed its "
            f"{HERDR_TIMEOUT_SECONDS:.0f}-second deadline"
        ) from error
    except subprocess.CalledProcessError as error:
        raise DeliveryRefusal(
            "delivery failed: herdr pane send-text exited with status "
            f"{error.returncode}"
        ) from error
    except OSError as error:
        raise DeliveryRefusal(
            f"delivery failed: the herdr CLI cannot start ({error})"
        ) from error


def _hold_refused(text: str) -> None:
    """Hold the refused transcript transiently (R19, KTD1).

    One current file: the write replaces whatever was held before — never
    appends — so the hold is not a transcript log. The write is atomic on
    one filesystem: write-temp-then-replace.
    """
    path = _refused_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
