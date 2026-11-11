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
- ``hc connect`` with ``terminal.attach`` pastes a transcript into the
  bound terminal the way a window does, as one bracketed paste with no
  Enter (R16). See :func:`paste_text`.

Voice never uses ``hc send`` (it always presses Enter, so the operator's
words would arrive submitted) and no longer uses ``hc keys``. A probe of
herdr core 0.1.20 on 2026-11-10, in an isolated core, showed ``hc keys``
takes key names, not text: it rejects ``? ! " : ( ) @ # $ % & * + _ ~ ^
{ } | < >`` and everything outside ASCII, types a bare ``A`` as ``a``, and
waits about three seconds for quiet before pressing anything. It could not
deliver a spoken question. The attach paste delivered every one of those
characters, and Chinese text and emoji, intact.

``get`` and ``label`` are bounded helper calls through ``process.run``:
argv only, no shell, standard input closed, and a deadline. The paste is a
bounded conversation through ``process.converse``: its standard input is a
pipe voice writes, never the operator's terminal, and a watchdog ends it at
its deadline. herdr core reports a failure
as ``{"error": {"kind", "message", "hint"}}`` on standard error; voice
carries that message into its own named refusal and never retries against
another terminal.
"""

from __future__ import annotations

import json
import struct
import subprocess
from collections.abc import Callable

import process
import settings

__all__ = [
    "CoreRefusal",
    "PasteRefusal",
    "PasteUncertain",
    "SESSION_LABEL",
    "STATUS_BLOCKED",
    "STATUS_IDLE",
    "STATUS_DONE",
    "STATE_LIVE",
    "get_terminal",
    "label_session",
    "paste_text",
    "paste_safe",
    "bracketed_paste_on",
    "status_word",
    "turn_of",
    "session_of",
    "is_live",
    "printable",
    "DISPLAY_LIMIT",
    "is_other_machine",
]

#: The label the Claude adapter writes on its own terminal: the Claude
#: session id running there. Voice owns this key; Herdr reads nothing from it.
SESSION_LABEL = "voice.agent-session"

#: The status word a program reports while it waits on a person (a
#: permission, a question, a login). Keystrokes there are answers, not text.
STATUS_BLOCKED = "blocked"

#: The status word of a program that is waiting for input and doing nothing.
STATUS_IDLE = "idle"

#: The status word of a program that finished its turn while nobody watched
#: its terminal. It is as settled as ``idle``; looking at it turns it idle.
STATUS_DONE = "done"

#: A terminal whose program is still running. The other state is
#: ``finished``.
STATE_LIVE = "live"

#: The most characters of program-supplied text voice shows the operator.
DISPLAY_LIMIT = 120

#: A frame on a framed herdr core connection: channel (u32), kind (u8),
#: payload length (u32), little-endian, then the payload. Channel 0 carries
#: JSON-RPC; an attach gets its own channel for the terminal's bytes. Read
#: from the frames ``hc attach`` exchanges with herdr core 0.1.20.
_FRAME = struct.Struct("<IBI")
_RPC_CHANNEL = 0
_KIND_DATA = 0
_KIND_CREDIT = 1
_KIND_CLOSE = 2
#: Input from automation rather than a person; used when the attach path
#: says it accepts it (``automatic_input``), else plain ``DATA``.
_KIND_AUTOMATIC_INPUT = 6

#: The bracketed paste markers a program asks for with mode 2004.
PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
_PASTE_MODE_ON = b"\x1b[?2004h"
_PASTE_MODE_OFF = b"\x1b[?2004l"


class CoreRefusal(Exception):
    """A named failure of one herdr core call.

    Carries the reason so the caller can wrap it in its own refusal. It
    never names or selects a different terminal.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PasteRefusal(CoreRefusal):
    """The paste was not sent: nothing reached the terminal."""


class PasteUncertain(CoreRefusal):
    """The paste was sent, but the exchange did not finish cleanly.

    The text may have reached the terminal; the caller must not send it
    again on its own.
    """


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


def paste_text(
    terminal: str,
    line: str,
    *,
    cols: int,
    rows: int,
    timeout: float,
    converse: Callable = process.converse,
    hc: str | None = None,
) -> dict:
    """Paste one line into ``terminal`` as a bracketed paste, without Enter.

    Opens ``hc connect``, switches it to framed mode, and attaches to the
    terminal as a viewer that may type (``observe`` false) at ``cols`` by
    ``rows``, the size ``hc get`` reported, so nothing is resized. It reads
    the terminal's first paint and refuses unless the program has turned on
    bracketed paste (mode 2004): a program that has not would read the
    markers as keys. It then writes ``ESC[200~`` + the line + ``ESC[201~``
    as one input frame, closes the attach, and waits for herdr core to
    confirm the close, so no viewer is left behind.

    ``line`` passes through :func:`paste_safe` first, so it carries no
    control character: no Enter, and no ESC to end the paste early.

    Returns the terminal record from the attach reply: its status and turn
    at the moment of attaching. Raises ``PasteRefusal`` when nothing was
    sent and ``PasteUncertain`` when the paste was sent but the exchange
    then failed.
    """
    text = paste_safe(line)
    if not text:
        raise PasteRefusal("there is no text to paste")
    talk = converse([_hc(hc), "connect"], timeout=timeout)
    sent = False
    try:
        record, channel, kind = _attach(talk, terminal, cols, rows)
        paint = _first_paint(talk, channel)
        if not bracketed_paste_on(paint):
            _write(talk, channel, _KIND_CLOSE, b"")
            _await_close(talk, channel)
            raise PasteRefusal(
                f"the program in {terminal} has not turned on bracketed paste, "
                "so a paste would arrive as keys"
            )
        _write(talk, channel, kind, PASTE_START + text.encode("utf-8") + PASTE_END)
        sent = True
        _write(talk, channel, _KIND_CLOSE, b"")
        _await_close(talk, channel)
    except PasteRefusal:
        talk.finish(timeout=1.0)
        raise
    except (CoreRefusal, OSError, EOFError, ValueError, AttributeError, TypeError) as error:
        expired = talk.expired
        talk.finish(timeout=1.0)
        reason = error.reason if isinstance(error, CoreRefusal) else str(error)
        if expired:
            reason = f"hc connect passed its {timeout:g}-second deadline"
        if sent:
            raise PasteUncertain(
                f"the paste was sent to {terminal}, but the attach did not close "
                f"cleanly ({printable(reason)})"
            ) from error
        raise PasteRefusal(f"the paste to {terminal} failed: {printable(reason)}") from error
    talk.finish(timeout=2.0)
    return record


def paste_safe(line: str) -> str:
    """``line`` with every control character removed, so it is safe to paste.

    C0 controls (CR, LF and ESC among them), DEL and the C1 range are
    removed: nothing can press Enter or end the bracketed paste early, and
    no ``ESC[201~`` can be planted inside it. Unlike :func:`printable`, the
    length is not capped and spacing is kept.
    """
    return "".join(
        character
        for character in line
        if not (
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0x80 <= ord(character) <= 0x9F
        )
    )


def bracketed_paste_on(paint: bytes) -> bool:
    """Whether a terminal's first paint leaves bracketed paste (mode 2004) on.

    A first paint resets the modes and then restores the program's own, so
    the last word about mode 2004 in it is the program's current setting.
    """
    return paint.rfind(_PASTE_MODE_ON) > paint.rfind(_PASTE_MODE_OFF)


def _write(talk, channel: int, kind: int, payload: bytes) -> None:
    talk.stdin.write(_FRAME.pack(channel, kind, len(payload)) + payload)
    talk.stdin.flush()


def _read_exact(talk, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = talk.stdout.read(size - len(data))
        if not chunk:
            raise EOFError("herdr core closed the connection")
        data += chunk
    return data


def _read_frame(talk) -> tuple[int, int, bytes]:
    channel, kind, length = _FRAME.unpack(_read_exact(talk, _FRAME.size))
    return channel, kind, _read_exact(talk, length)


def _attach(talk, terminal: str, cols: int, rows: int) -> tuple[dict, int, int]:
    """Say hello in framed mode and attach; return record, channel and input kind."""
    hello = {"jsonrpc": "2.0", "id": 0, "method": "hello", "params": {"framed": True}}
    talk.stdin.write(json.dumps(hello).encode("utf-8") + b"\n")
    talk.stdin.flush()
    line = talk.stdout.readline()
    if not line:
        raise EOFError("herdr core closed the connection before saying hello")
    result = json.loads(line).get("result")
    if (
        not isinstance(result, dict)
        or result.get("framed") is not True
        or "attach" not in (result.get("features") or [])
    ):
        raise PasteRefusal("this herdr core does not offer a framed attach")
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "terminal.attach",
        "params": {
            "caller": None,
            "cols": cols,
            "rows": rows,
            "history": 0,
            "observe": False,
            "terminal": terminal,
        },
    }
    _write(talk, _RPC_CHANNEL, _KIND_DATA, json.dumps(request).encode("utf-8"))
    while True:
        channel, _kind, payload = _read_frame(talk)
        if channel != _RPC_CHANNEL:
            continue
        reply = json.loads(payload)
        if reply.get("id") != 1:
            continue
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            message = str(error.get("message") or data.get("kind") or "refused")
            raise PasteRefusal(f"herdr core refused the attach: {printable(message)}")
        result = reply.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("channel"), int):
            raise PasteRefusal("herdr core answered the attach without a channel")
        record = result.get("terminal") if isinstance(result.get("terminal"), dict) else {}
        if record.get("address") not in (None, terminal):
            raise PasteRefusal(
                f"herdr core attached {printable(str(record.get('address')))}, not {terminal}"
            )
        kind = _KIND_AUTOMATIC_INPUT if result.get("automatic_input") is True else _KIND_DATA
        return record, result["channel"], kind


def _first_paint(talk, channel: int) -> bytes:
    """The first bytes the attach streams: the screen and the program's modes."""
    while True:
        frame_channel, kind, payload = _read_frame(talk)
        if frame_channel != channel:
            continue
        if kind == _KIND_CLOSE:
            raise PasteRefusal("herdr core closed the attach before the first paint")
        if kind == _KIND_DATA:
            _write(talk, channel, _KIND_CREDIT, struct.pack("<I", len(payload)))
            return payload


def _await_close(talk, channel: int) -> None:
    """Read until herdr core confirms the attach closed, granting credit meanwhile."""
    while True:
        frame_channel, kind, payload = _read_frame(talk)
        if frame_channel != channel:
            continue
        if kind == _KIND_CLOSE:
            return
        if kind == _KIND_DATA:
            _write(talk, channel, _KIND_CREDIT, struct.pack("<I", len(payload)))


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


def turn_of(record: dict) -> int | None:
    """The terminal's turn number, which goes up each time its status leaves ``working``."""
    turn = record.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int):
        return None
    return turn


def session_of(record: dict) -> str | None:
    """The Claude session id the terminal is labelled with, or ``None``."""
    labels = record.get("labels")
    if not isinstance(labels, dict):
        return None
    value = labels.get(SESSION_LABEL)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def printable(text: str, limit: int = DISPLAY_LIMIT) -> str:
    """``text`` made safe to show in a terminal: no control characters, capped.

    Text that a program reports through herdr core (a status message, a
    terminal name, an error) reaches the operator's terminal. Removing every
    C0 control character (below 0x20, line breaks and ESC included), DEL
    (0x7f) and every C1 control character (0x80 to 0x9f) means no escape
    sequence survives to move the cursor, rewrite the screen, or set the
    clipboard. Whitespace runs collapse to one space, and text longer than
    ``limit`` is cut with an ellipsis.
    """
    kept = "".join(
        " " if character in "\t\n\r" else character
        for character in text
        if character in "\t\n\r"
        or not (
            ord(character) < 0x20
            or ord(character) == 0x7F
            or 0x80 <= ord(character) <= 0x9F
        )
    )
    kept = " ".join(kept.split())
    if len(kept) > limit:
        kept = kept[: limit - 1].rstrip() + "…"
    return kept


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
        return printable(stderr.strip().splitlines()[-1]) or None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    for field in ("message", "kind"):
        value = error.get(field)
        if isinstance(value, str) and printable(value):
            return printable(value)
    return None
