"""The one place voice talks to herdr core (portable core).

Herdr is two programs: herdr core (``hc``) runs every terminal and agent on
its machine, and the Herdr app is the window that shows them. Voice needs
only the core, and only three of its commands:

- ``hc get <terminal> --json`` reads one terminal: its address, whether it
  is still live, the status word its program reports, and its labels.
- ``hc label <terminal> voice.agent-session=<id>`` records which Claude
  session runs in a terminal. herdr core does not know that on its own, and
  the binding and the Auralis bridge identity both need it, so the Claude
  adapter's ``SessionStart`` hook labels its own terminal.
- ``hc keys <terminal> <key>...`` types a transcript into the bound
  terminal one key at a time, with no Enter. Voice never uses ``hc send``:
  it always presses Enter, so the operator's words would arrive submitted
  (R16).

``hc keys`` takes key names, not text, and only a small set of characters
can be typed with them. Probing herdr core 0.1.20 on 2026-11-10 in an
isolated core showed: lowercase letters, digits, the backslash and
``. , ' - ; / = ` [ ]`` type as themselves; ``space`` types a space;
``shift+a`` types ``A`` while a bare ``A`` types ``a``; ``shift+/`` types
``/``, not ``?``; and every other character (``? ! " : ( ) @ # $ % & * +
_ ~ ^ { } | < >``, a literal space, and anything outside ASCII) is rejected
as an unknown key. A rejected key fails
the whole call before anything is typed. ``key_names`` therefore maps only
the characters known to type correctly and refuses the whole line otherwise,
so nothing partial and nothing wrong is ever typed.

Every call is a bounded helper call through ``process.run``: argv only, no
shell, standard input closed, and a deadline. herdr core reports a failure
as ``{"error": {"kind", "message", "hint"}}`` on standard error; voice
carries that message into its own named refusal and never retries against
another terminal.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

import process
import settings

__all__ = [
    "CoreRefusal",
    "UntypableText",
    "SESSION_LABEL",
    "STATUS_BLOCKED",
    "STATE_LIVE",
    "get_terminal",
    "label_session",
    "type_text",
    "key_names",
    "status_word",
    "session_of",
    "is_live",
    "is_other_machine",
]

#: The label the Claude adapter writes on its own terminal: the Claude
#: session id running there. Voice owns this key; Herdr reads nothing from it.
SESSION_LABEL = "voice.agent-session"

#: The status word a program reports while it waits on a person (a
#: permission, a question, a login). Keystrokes there are answers, not text.
STATUS_BLOCKED = "blocked"

#: A terminal whose program is still running. The other state is
#: ``finished``.
STATE_LIVE = "live"

#: How ``hc keys`` names the space bar.
_SPACE_KEY = "space"

#: Characters ``hc keys`` types exactly as themselves (herdr core 0.1.20,
#: probed 2026-11-10). A backslash also types as itself but is left out:
#: Claude Code reads a backslash before Enter as "new line", so a transcript
#: ending in one would not submit when the operator presses Enter.
_TYPED_AS_ITSELF = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.,'-;/=`[]")


class CoreRefusal(Exception):
    """A named failure of one herdr core call.

    Carries the reason so the caller can wrap it in its own refusal. It
    never names or selects a different terminal.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class UntypableText(CoreRefusal):
    """A line holding characters ``hc keys`` cannot type correctly.

    Raised before any ``hc`` call; ``characters`` lists each offending
    character once, in the order it first appears.
    """

    def __init__(self, characters: list[str]) -> None:
        self.characters = characters
        shown = " ".join(repr(character) for character in characters)
        super().__init__(f"hc keys cannot type these characters: {shown}")


def get_terminal(
    target: str,
    *,
    timeout: float,
    run_process: Callable = process.run,
    hc: str | None = None,
) -> dict:
    """One terminal's record from ``hc get <target> --json``.

    ``target`` is an address (``t7``) or a name. The record is returned as
    herdr core printed it, after checking it names a non-empty address.
    """
    command = [_hc(hc), "get", target, "--json"]
    completed = _run(command, f"hc get {target}", timeout, run_process)
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError) as error:
        raise CoreRefusal(
            f"hc get {target} printed no JSON terminal record"
        ) from error
    # Some herdr core versions wrap the record as {"terminal": {...}}.
    if isinstance(payload, dict) and isinstance(payload.get("terminal"), dict):
        payload = payload["terminal"]
    if not isinstance(payload, dict):
        raise CoreRefusal(f"hc get {target} printed no JSON terminal record")
    address = payload.get("address")
    if not isinstance(address, str) or not address.strip():
        raise CoreRefusal(f"hc get {target} returned a record with no address")
    return payload


def label_session(
    terminal: str,
    session_id: str,
    *,
    timeout: float,
    run_process: Callable = process.run,
    hc: str | None = None,
) -> None:
    """Record ``session_id`` as the Claude session running in ``terminal``."""
    command = [_hc(hc), "label", terminal, f"{SESSION_LABEL}={session_id}"]
    _run(command, f"hc label {terminal}", timeout, run_process)


def type_text(
    terminal: str,
    line: str,
    *,
    timeout: float,
    run_process: Callable = process.run,
    hc: str | None = None,
) -> None:
    """Type one line into ``terminal`` key by key, without pressing Enter."""
    keys = key_names(line)
    if not keys:
        raise CoreRefusal("there is no text to type")
    command = [_hc(hc), "keys", terminal, *keys]
    _run(command, f"hc keys {terminal}", timeout, run_process)


def key_names(line: str) -> list[str]:
    """The ``hc keys`` names that type ``line`` exactly: one per character.

    A space is ``space``, a capital letter is ``shift+<letter>``, and the
    characters in ``_TYPED_AS_ITSELF`` are their own names. Any other
    character raises ``UntypableText`` for the whole line, so a caller never
    types part of it. No name here is ``enter``, so nothing can submit.
    """
    keys: list[str] = []
    untypable: list[str] = []
    for character in line:
        if character == " ":
            keys.append(_SPACE_KEY)
        elif character in _TYPED_AS_ITSELF:
            keys.append(character)
        elif "A" <= character <= "Z":
            keys.append(f"shift+{character.lower()}")
        elif character not in untypable:
            untypable.append(character)
    if untypable:
        raise UntypableText(untypable)
    return keys


def status_word(record: dict) -> str | None:
    """The status word the terminal's program last reported, or ``None``.

    herdr core reports it as ``status: {"state": "idle" | "working" |
    "done" | "blocked" | "error", ...}``, and ``status: null`` when the
    program never reported one.
    """
    status = record.get("status")
    if not isinstance(status, dict):
        return None
    state = status.get("state")
    if not isinstance(state, str) or not state.strip():
        return None
    return state.strip()


def session_of(record: dict) -> str | None:
    """The Claude session id the terminal is labelled with, or ``None``."""
    labels = record.get("labels")
    if not isinstance(labels, dict):
        return None
    value = labels.get(SESSION_LABEL)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def is_live(record: dict) -> bool:
    """Whether the terminal's program is still running."""
    return record.get("state") == STATE_LIVE


def is_other_machine(address: str) -> bool:
    """Whether an address names a terminal on another machine (``mini/t3``).

    Voice records and plays audio on this machine, and its Stop hook reads
    this machine's binding, so it only ever binds a terminal here.
    """
    return "/" in address


def _hc(hc: str | None) -> str:
    if hc is not None:
        return hc
    try:
        return settings.hc_bin()
    except settings.SettingsRefusal as refusal:
        raise CoreRefusal(
            f"the herdr core command is unusable: {refusal}"
        ) from refusal


def _run(
    command: list[str], label: str, timeout: float, run_process: Callable
) -> subprocess.CompletedProcess:
    try:
        return run_process(command, timeout=timeout, check=True)
    except subprocess.TimeoutExpired as error:
        raise CoreRefusal(
            f"{label} passed its {timeout:g}-second deadline"
        ) from error
    except subprocess.CalledProcessError as error:
        message = _error_message(error.stderr)
        detail = f": {message}" if message else ""
        raise CoreRefusal(
            f"{label} exited with status {error.returncode}{detail}"
        ) from error
    except OSError as error:
        raise CoreRefusal(f"herdr core cannot start ({error})") from error


def _error_message(stderr: object) -> str | None:
    """The message from herdr core's ``{"error": {...}}`` report, if any."""
    if not isinstance(stderr, str) or not stderr.strip():
        return None
    try:
        payload = json.loads(stderr)
    except ValueError:
        return stderr.strip().splitlines()[-1][:200]
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    kind = error.get("kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    return None
