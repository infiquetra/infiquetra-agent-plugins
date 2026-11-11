"""Delivery path for the voice package (R16, R17, R18, R19; KTD11).

Returns a transcript to the bound agent's input box — literal text,
unsubmitted, still editable (R16) — or refuses audibly when that agent is
blocked on a human decision, holding the transcript for the operator's
explicit use or discard (R18, R19).

Delivery is a two-step sequence against herdr core (``hc``), the program
that runs the bound agent's terminal:

1. ``hc get <terminal> --json`` re-reads the bound terminal at send time.
   It must still be live, and its status word must be exactly ``idle``:
   an idle agent is waiting for input and raises no dialog on its own.
   ``blocked``, ``working``, ``done``, ``error``, any other word, or no
   status at all holds the transcript instead. The call runs under the
   10-second deadline pinned for bounded helper calls (KTD3a).
2. ``hc keys <terminal> <key>...`` types the transcript, whitespace-
   normalized to a single line, one key per character (``space`` for a
   space, ``shift+<letter>`` for a capital) and no Enter — the
   unsubmitted, editable delivery R16 requires.
3. The status is checked again: the status and turn ``hc keys`` reports
   for the moment its keys went in, and a fresh ``hc get``. If either is
   not ``idle``, or the turn moved, the transcript may have reached a
   prompt instead of the input box. Voice says so, out loud and in the
   pane, and never presses Enter; it cannot take the keys back.

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

The status check is not atomic with the typing. ``hc keys`` waits for
about three seconds of quiet from the person before it presses anything,
and has no guard of its own (``hc send`` refuses a blocked program, but it
submits). If the agent raises a menu or a permission dialog in that
window, single characters of the transcript (a ``1``, a ``y``) can answer
it. That race is the residual: narrowed by typing only into an idle agent,
detected after the fact by step 3, and closed only when herdr core gives
``terminal.keys`` a guard that refuses unless the program is idle.

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
    "BUSY_REFUSAL_PHRASE",
    "UNCERTAIN_DELIVERY_PHRASE",
    "TYPABLE_STATUSES",
    "DeliveryUncertain",
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

#: The only status words delivery types into. Everything else holds the
#: transcript: a program waiting for input raises no dialog on its own.
TYPABLE_STATUSES = (herdr_core.STATUS_IDLE,)

#: The short fixed phrase spoken when the bound agent is not idle.
BUSY_REFUSAL_PHRASE = "The bound session is not idle; not delivering that."

#: The short fixed phrase spoken when the agent changed while keys went in.
UNCERTAIN_DELIVERY_PHRASE = (
    "That transcript may have reached a prompt. Check the session before pressing Enter."
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


class DeliveryUncertain(DeliveryRefusal):
    """The transcript was typed, but the agent changed while the keys went in.

    The keys cannot be taken back and Enter was never pressed. The operator
    has to look at the session: the transcript may sit in a prompt or
    dialog rather than the input box.
    """


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

    before = _resolve_terminal(agent_name, terminal, run_process=run_process)
    status = herdr_core.status_word(before)
    if status == AGENT_STATUS_BLOCKED:
        _hold_refused(text)
        speak_text(BLOCKED_REFUSAL_PHRASE)
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} is blocked on a human decision; "
            "nothing was sent — the transcript is held for explicit use or "
            "discard"
        )
    if status not in TYPABLE_STATUSES:
        _hold_refused(text)
        speak_text(BUSY_REFUSAL_PHRASE)
        shown = repr(status) if status is not None else "not reporting a status"
        raise DeliveryRefusal(
            f"the bound agent {agent_name!r} is {shown}, not idle; nothing was "
            "typed — the transcript is held for explicit use or discard"
        )
    try:
        typed = herdr_core.type_text(
            terminal, line, timeout=HC_TIMEOUT_SECONDS, run_process=run_process
        )
    except herdr_core.CoreRefusal as refusal:
        _hold_refused(text)
        raise DeliveryRefusal(
            f"delivery failed: {refusal.reason} — the transcript is held for "
            "explicit use or discard"
        ) from refusal
    change = _change_while_typing(
        terminal, before, typed, run_process=run_process
    )
    if change is not None:
        warning = (
            f"the transcript was typed into {agent_name!r}, but {change}; it may "
            "have reached a prompt instead of the input box. Nothing was "
            "submitted — check the session before pressing Enter"
        )
        try:
            speak_text(UNCERTAIN_DELIVERY_PHRASE)
        except Exception as error:  # the written warning must still surface
            warning += f" (the spoken warning failed: {error})"
        raise DeliveryUncertain(warning)


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
    after the keys went in (including a typing the agent may have caught
    in a prompt, which is reported, not retried). When the agent is still blocked, delivery
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
    try:
        deliver(text, spawn=spawn, speak_text=speak_text)
    except DeliveryUncertain:
        # The keys went in; keeping the hold would invite typing it twice.
        path.unlink(missing_ok=True)
        raise
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


def _resolve_terminal(
    agent_name: str, terminal: str, *, run_process: Callable
) -> dict:
    """Re-read the bound terminal at send time and return its record (KTD7).

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
    return record


def _change_while_typing(
    terminal: str, before: dict, typed: dict, *, run_process: Callable
) -> str | None:
    """What changed while the keys went in, or ``None`` when nothing did.

    Compares the status and turn ``hc keys`` reported for the moment its
    keys went in, then a fresh ``hc get``, against the idle record read
    before typing. A status that is not idle (a blocked one names its
    question when the program gave one), a turn that moved, or a terminal
    that can no longer be read all count as a change.
    """
    turn = herdr_core.turn_of(before)
    status = typed.get("status")
    if status not in TYPABLE_STATUSES:
        return f"hc keys reported its status as {status!r} when the keys went in"
    if typed.get("turn") != turn:
        return "its turn moved while the keys went in"
    try:
        after = herdr_core.get_terminal(
            terminal, timeout=HC_TIMEOUT_SECONDS, run_process=run_process
        )
    except herdr_core.CoreRefusal as refusal:
        return f"it could not be read again after typing ({refusal.reason})"
    status = herdr_core.status_word(after)
    if status not in TYPABLE_STATUSES:
        reported = after.get("status")
        question = reported.get("msg") if isinstance(reported, dict) else None
        asked = ""
        if isinstance(question, str) and herdr_core.printable(question):
            # The program wrote this text; strip anything that could act as a
            # terminal escape sequence before the operator sees it.
            asked = f" ({herdr_core.printable(question)})"
        return f"its status is now {status!r}{asked}"
    if herdr_core.turn_of(after) != turn:
        return "its turn moved while the keys went in"
    return None


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
