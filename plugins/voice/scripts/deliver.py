"""Delivery path for the voice package (R16, R17, R18, R19; KTD11).

Returns a transcript to the bound agent's input box — literal text,
unsubmitted, still editable (R16) — or refuses audibly when that agent is
blocked on a human decision, holding the transcript for the operator's
explicit use or discard (R18, R19).

Delivery is a three-step sequence against herdr core (``hc``), the program
that runs the bound agent's terminal:

1. ``hc get <terminal> --json`` re-reads the bound terminal at send time.
   It must still be live, and its status word must be ``idle`` or
   ``done`` (a turn that finished while nobody watched): a settled agent
   is waiting for input and raises no dialog on its own. ``blocked``,
   ``working``, ``error``, any other word, or no status at all holds the
   transcript instead. The call runs under the 10-second deadline pinned
   for bounded helper calls (KTD3a).
2. ``herdr_core.paste_text`` attaches to the terminal through ``hc
   connect`` at the size step 1 reported, and pastes the transcript,
   whitespace-normalized to a single line with every control character
   removed, as one bracketed paste — no Enter, the unsubmitted, editable
   delivery R16 requires — then detaches. A program that has not turned on
   bracketed paste gets nothing, and the transcript is held.
3. The status is checked again: the status and turn in the attach reply
   (the moment of attaching), then a fresh ``hc get``. If either is not
   ``idle`` or ``done``, or the turn moved, the transcript may have reached
   a prompt instead of the input box. Voice says so, out loud and in the
   pane, and never presses Enter; it cannot take the paste back.

``hc send`` is never used, and nothing falls back to it: it always presses
Enter, so a misheard transcript would be submitted to the agent. ``hc
keys`` is not used either: it cannot type ``?``, ``!``, quotes or anything
outside ASCII, so it could not deliver a spoken question.

A transcript that starts with ``/`` or ``!`` is held rather than pasted:
in Claude Code's input box those start a command or a shell command, so
pressing Enter would run it instead of sending text.

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

The status check is not atomic with the paste. On the scratch core the
whole read-attach-paste-detach sequence took about 50 milliseconds, but
nothing in herdr core stops the agent from raising a menu or a permission
dialog inside that window, and a paste that lands in a dialog could answer
it. That race is the residual: narrowed by pasting only into a settled
agent and by the speed of the paste, detected after the fact by step 3,
and closed only when herdr core offers a paste (``hc send --no-enter``) or
keys (``hc keys --if idle``) that refuse unless the program is settled at
the moment they land.

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
    "COMMAND_REFUSAL_PHRASE",
    "UNCERTAIN_DELIVERY_PHRASE",
    "TYPABLE_STATUSES",
    "DeliveryUncertain",
    "HC_TIMEOUT_SECONDS",
    "REFUSED_TRANSCRIPT_FILENAME",
    "deliver",
    "use_refused",
    "discard_refused",
]

#: The hc calls (``get``, and the ``connect`` conversation that pastes) are
#: bounded and share the 10-second deadline pinned for helper calls (KTD3a).
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

#: The only status words delivery pastes into: a settled turn waiting for
#: input, which raises no dialog on its own. ``done`` is what a Claude
#: session reports after its turn while nobody views its terminal, which is
#: the usual state when the operator answers by voice. Everything else holds
#: the transcript.
TYPABLE_STATUSES = (herdr_core.STATUS_IDLE, herdr_core.STATUS_DONE)

#: The short fixed phrase spoken when the bound agent is not settled.
BUSY_REFUSAL_PHRASE = "The bound session is busy; not delivering that."

#: The short fixed phrase spoken when the agent changed around the paste.
UNCERTAIN_DELIVERY_PHRASE = (
    "That transcript may have reached a prompt. Check the session before pressing Enter."
)

#: The short fixed phrase spoken when a transcript would run as a command.
COMMAND_REFUSAL_PHRASE = "That transcript would run as a command; it is held."

#: Leading characters that turn Claude Code's input into a command (``/``)
#: or a shell command (``!``) when the operator presses Enter.
_COMMAND_PREFIXES = ("/", "!")


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
    """The transcript was pasted, but the agent changed around the paste.

    A paste cannot be taken back and Enter was never pressed. The operator
    has to look at the session: the transcript may sit in a prompt or
    dialog rather than the input box.
    """


def deliver(
    text: str,
    *,
    spawn: Callable = subprocess.run,
    converse: Callable = process.converse,
    speak_text: Callable = speak.speak,
) -> None:
    """Deliver ``text`` to the bound agent's input box, unsubmitted.

    Re-reads the bound terminal through ``hc get`` and pastes the
    whitespace-normalized single-line transcript through an attach — one
    bracketed paste, no Enter (R16) — then checks the terminal again. A
    blocked or busy agent receives nothing: the refusal is spoken and the
    transcript is held for the operator's explicit use or discard (R18,
    R19). So is a transcript that would run as a command, and one whose
    paste could not be sent. Only the bound terminal is ever targeted
    (R17).

    The transcript is held before the refusal is spoken, so the hold
    survives even when speech itself fails. ``hc get`` goes through U1's
    process helper and the paste through its bounded conversation, both
    under the pinned deadline; the seams mirror KTD12 so tests never run
    the real CLI.
    """
    line = herdr_core.paste_safe(_single_line(text))
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

    if line.startswith(_COMMAND_PREFIXES):
        _hold_refused(text)
        speak_text(COMMAND_REFUSAL_PHRASE)
        raise DeliveryRefusal(
            f"the transcript starts with {line[0]!r}, which Claude Code would run "
            "as a command when you press Enter; nothing was pasted — the "
            "transcript is held for explicit use or discard"
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
            f"the bound agent {agent_name!r} is {shown}, not idle or done; nothing was "
            "pasted — the transcript is held for explicit use or discard"
        )
    cols, rows = before.get("cols"), before.get("rows")
    change = None
    try:
        if not _is_size(cols) or not _is_size(rows):
            raise herdr_core.PasteRefusal(
                "hc get reported no terminal size to attach at, and a guessed "
                "size would resize the terminal"
            )
        attached = herdr_core.paste_text(
            terminal,
            line,
            cols=cols,
            rows=rows,
            timeout=HC_TIMEOUT_SECONDS,
            converse=converse,
        )
    except herdr_core.PasteUncertain as uncertain:
        change = uncertain.reason
    except herdr_core.CoreRefusal as refusal:
        _hold_refused(text)
        raise DeliveryRefusal(
            f"delivery failed: {refusal.reason} — nothing was pasted; the "
            "transcript is held for explicit use or discard"
        ) from refusal
    else:
        change = _change_while_pasting(
            terminal, before, attached, run_process=run_process
        )
    if change is not None:
        warning = (
            f"the transcript was pasted into {agent_name!r}, but {change}; it may "
            "have reached a prompt instead of the input box. Nothing was "
            "submitted — check the session before pressing Enter"
        )
        try:
            speak_text(UNCERTAIN_DELIVERY_PHRASE)
        except Exception as error:  # the written warning must still surface
            warning += f" (the spoken warning failed: {error})"
        raise DeliveryUncertain(warning)


def _is_size(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def use_refused(
    *,
    spawn: Callable = subprocess.run,
    converse: Callable = process.converse,
    speak_text: Callable = speak.speak,
) -> None:
    """Explicitly use the held refused transcript (R19).

    Reads the hold file and delivers that text, deleting the hold only
    after the paste was sent (including a paste the agent may have caught
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
        deliver(text, spawn=spawn, converse=converse, speak_text=speak_text)
    except DeliveryUncertain:
        # The paste was sent; keeping the hold would invite pasting it twice.
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


def _change_while_pasting(
    terminal: str, before: dict, attached: dict, *, run_process: Callable
) -> str | None:
    """What changed around the paste, or ``None`` when nothing did.

    Compares the terminal record in the attach reply (its status and turn
    at the moment of attaching), then a fresh ``hc get``, against the
    settled record read before pasting. A status that is not idle or done
    (a blocked one names its question when the program gave one), a turn
    that moved, or a terminal that can no longer be read all count.
    """
    turn = herdr_core.turn_of(before)
    for label, record in (("when the paste attached", attached), (None, None)):
        if record is None:
            try:
                record = herdr_core.get_terminal(
                    terminal, timeout=HC_TIMEOUT_SECONDS, run_process=run_process
                )
            except herdr_core.CoreRefusal as refusal:
                return f"it could not be read again after the paste ({refusal.reason})"
            label = "now"
        status = herdr_core.status_word(record)
        if status not in TYPABLE_STATUSES:
            return f"its status was {status!r} {label}{_question(record)}"
        if herdr_core.turn_of(record) != turn:
            return f"its turn had moved {label}"
    return None


def _question(record: dict) -> str:
    """The question a blocked program asked, cleaned for display, or nothing."""
    reported = record.get("status")
    question = reported.get("msg") if isinstance(reported, dict) else None
    if isinstance(question, str) and herdr_core.printable(question):
        # The program wrote this text; strip anything that could act as a
        # terminal escape sequence before the operator sees it.
        return f" ({herdr_core.printable(question)})"
    return ""


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
