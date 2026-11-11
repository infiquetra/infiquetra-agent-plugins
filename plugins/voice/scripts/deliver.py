"""Delivery path for the voice package (R16, R17, R18, R19; KTD11).

Returns a transcript to the bound agent's input box — literal text,
unsubmitted, still editable (R16) — or refuses audibly when that agent is
blocked on a human decision, holding the transcript for the operator's
explicit use or discard (R18, R19).

Delivery is a two-step sequence against herdr core (``hc``), the program
that runs the bound agent's terminal:

1. ``hc get <terminal> --json`` re-reads the bound terminal at send time:
   it must still be live, and its status word (``idle``, ``working``,
   ``done``, ``blocked``, ``error``, or none) decides whether text may go
   in. The call runs under the 10-second deadline pinned for bounded
   helper calls (KTD3a).
2. ``hc keys <terminal> <key>...`` types the transcript, whitespace-
   normalized to a single line, one key per character (``space`` for a
   space, ``shift+<letter>`` for a capital) and no Enter — the
   unsubmitted, editable delivery R16 requires.

``hc send`` is never used, and nothing falls back to it: it always presses
Enter, so a misheard transcript would be submitted to the agent.

``hc keys`` types only lowercase and capital letters, digits, spaces and
``. , ' - ; / = ` [ ]`` correctly (see ``herdr_core``). A transcript with
any other character — a question mark, an exclamation mark, a colon,
quotes, anything outside ASCII — is not typed at all: it is held for the
operator's explicit use or discard, and the refusal is spoken, before any
``hc`` call. So is a transcript that starts with ``/``, which would open
Claude Code's command menu instead of landing as text. If the ``hc keys``
call itself fails, the transcript is held as well.

Only the bound terminal is ever targeted (R17): no broadcast, no fallback
target, no recency inference. The binding stores the terminal's address,
which herdr core never reuses, so a terminal that has ended is a named
error, never a reason to try another one.

Speech is never an approval channel. When the bound agent is blocked on a
permission, approval, or other human-decision prompt, keystrokes are
choices rather than text: nothing is sent, the refusal is spoken through
the speak path, and the transcript is held in ``refused-transcript.txt``
under the state directory — one current file, replaced rather than
appended, consumed or discarded only by an explicit operator act (R19,
KTD1). A refused transcript is never delivered automatically and never
queued for automatic delivery.

The blocked-state check is not atomic with the typing: the agent can
become blocked between the read and the keys. That race is the contract's
stated residual — narrowed here, deliberately not closed. ``hc send``
refuses a blocked program on its own, but it submits; ``hc keys`` does not
check. The guard belongs to herdr core as a proposed enhancement (keys
that refuse a blocked program), and no workaround machinery is built in
this module.

The entry points are module-level so the pane and the CLI can reach them
through their lazy-import seam (KTD16): :func:`deliver`,
:func:`use_refused`, and :func:`discard_refused`.
"""

from __future__ import annotations

import functools
import os
import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path

import binding
import herdr_core
import process
import settings
import speak

__all__ = [
    "DeliveryRefusal",
    "AGENT_STATUS_BLOCKED",
    "BLOCKED_REFUSAL_PHRASE",
    "UNTYPABLE_REFUSAL_PHRASE",
    "HC_TIMEOUT_SECONDS",
    "REFUSED_TRANSCRIPT_FILENAME",
    "deliver",
    "use_refused",
    "discard_refused",
]

#: Both hc calls are bounded helper invocations and share the 10-second
#: deadline pinned for that class (KTD3a). ``hc keys`` waits for about three
#: seconds of quiet from the person before it types, which fits inside it.
HC_TIMEOUT_SECONDS = 10.0

#: The one status that must never receive keystrokes: a blocked agent is
#: waiting on a human decision, and a keystroke there is a choice, not
#: text (R18).
AGENT_STATUS_BLOCKED = herdr_core.STATUS_BLOCKED

REFUSED_TRANSCRIPT_FILENAME = "refused-transcript.txt"

#: The short fixed phrase spoken when a blocked agent refuses the delivery
#: (KTD8's refusal entry point).
BLOCKED_REFUSAL_PHRASE = (
    "The bound session is blocked on a prompt; not delivering that."
)

#: The short fixed phrase spoken when a transcript cannot be typed exactly.
UNTYPABLE_REFUSAL_PHRASE = "Voice cannot type that transcript exactly; it is held."

#: Leading characters that Claude Code treats as a command rather than text
#: when they open its input box. ``hc keys`` can type ``/``; the others it
#: cannot type at all.
_COMMAND_PREFIXES = ("/",)


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

    Checks first that every character can be typed exactly; if not,
    nothing is typed, the refusal is spoken, and the transcript is held.
    Then re-reads the bound terminal through ``hc get`` and types the
    whitespace-normalized single-line transcript with ``hc keys`` — one
    key per character, no Enter (R16). A blocked agent receives nothing:
    the refusal is spoken and the transcript is held for the operator's
    explicit use or discard (R18, R19). A failed ``hc keys`` call holds it
    too. Only the bound terminal is ever targeted (R17).

    The transcript is held before the refusal is spoken, so the hold
    survives even when speech itself fails. Both hc calls go through U1's
    process helper under the pinned deadline with standard input closed;
    the seams mirror KTD12 so tests never run the real CLI.
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
    terminal = report.binding.terminal
    run_process = functools.partial(process.run, spawn=spawn)

    untypable = _untypable_reason(line)
    if untypable is not None:
        _hold_refused(text)
        speak_text(UNTYPABLE_REFUSAL_PHRASE)
        raise DeliveryRefusal(
            f"{untypable}; nothing was typed — the transcript is held for "
            "explicit use or discard"
        )

    status = _resolve_status(agent_name, terminal, run_process=run_process)
    if status == AGENT_STATUS_BLOCKED:
        _hold_refused(text)
        speak_text(BLOCKED_REFUSAL_PHRASE)
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} is blocked on a human decision; "
            "nothing was sent — the transcript is held for explicit use or "
            "discard"
        )
    try:
        herdr_core.type_text(
            terminal, line, timeout=HC_TIMEOUT_SECONDS, run_process=run_process
        )
    except herdr_core.CoreRefusal as refusal:
        _hold_refused(text)
        raise DeliveryRefusal(
            f"delivery failed: {refusal.reason} — the transcript is held for "
            "explicit use or discard"
        ) from refusal


def _untypable_reason(line: str) -> str | None:
    """Why ``line`` cannot be typed exactly, or ``None`` when it can."""
    try:
        herdr_core.key_names(line)
    except herdr_core.UntypableText as untypable:
        return untypable.reason
    if line.startswith(_COMMAND_PREFIXES):
        return (
            f"the transcript starts with {line[0]!r}, which would open Claude "
            "Code's command menu instead of landing as text"
        )
    return None


def use_refused(
    *,
    spawn: Callable = subprocess.run,
    speak_text: Callable = speak.speak,
) -> None:
    """Explicitly use the held refused transcript (R19).

    Reads the hold file and delivers that text, deleting the hold only
    after a successful send. When the agent is still blocked, delivery
    refuses again and the transcript is held anew — it is never forced
    through. Any other delivery failure likewise leaves the hold in
    place, so a failed send never consumes the only remaining copy of a
    refused transcript. A missing hold is refused by name.
    """
    path = _refused_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DeliveryRefusal(
            "there is no refused transcript to use"
        ) from error
    deliver(text, spawn=spawn, speak_text=speak_text)
    path.unlink(missing_ok=True)


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
            "<terminal>` before delivering"
        )
    return (
        "voice is not bound to an agent; bind one with `voice bind <terminal>` "
        "before delivering"
    )


def _single_line(text: str) -> str:
    """Whitespace-normalize the transcript to a single line.

    Speech has no meaningful line structure, and a raw newline must never
    reach the terminal as Enter, so every whitespace run collapses to one
    space.
    """
    return " ".join(text.split())


def _resolve_status(
    agent_name: str, terminal: str, *, run_process: Callable
) -> str | None:
    """Re-read the bound terminal at send time and return its status word (KTD7).

    The terminal must still answer to its own address and still be live.
    Anything else is a named error; nothing falls back to another target
    (R17).
    """
    unresolved = f"the bound agent {agent_name!r} (terminal {terminal}) could not be resolved"
    try:
        record = herdr_core.get_terminal(
            terminal, timeout=HC_TIMEOUT_SECONDS, run_process=run_process
        )
    except herdr_core.CoreRefusal as refusal:
        raise DeliveryRefusal(f"{unresolved}: {refusal.reason}") from refusal
    if record["address"] != terminal:
        raise DeliveryRefusal(
            f"{unresolved}: hc get answered for terminal {record['address']!r}"
        )
    if not herdr_core.is_live(record):
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} (terminal {terminal}) has finished; "
            "rebind with `voice bind <terminal>`"
        )
    return herdr_core.status_word(record)


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
