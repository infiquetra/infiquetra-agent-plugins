"""The Voice pane: operator surface and listen-path sequencer (KTD16).

The pane is the package's one long-running process. It runs in its own
Herdr pane (R13), because an interactive Claude session owns the pane it
occupies, and it is started through ``voice_cli.py pane``.

The pane displays the bound agent's identity continuously, alongside the
recording state (R4): the Herdr agent name and the bound Claude session
id from ``binding.json``, re-read on every redraw so a rebind becomes
visible. While a recording runs it shows the literal ``*** RECORDING ***``
(R11).

Keys apply immediately, without Enter: the loop reads single characters
through ``tty.setcbreak`` on its standard input (no ``curses``, no
third-party TUI, no ``input()``).

- ``t`` toggle recording. Starting a recording stops any playback first
  (R9); an explicit second press takes the wav path from the capture
  toggle, transcribes it through the declared relay, and delivers the
  transcript through the delivery seam (KTD16).
- ``s`` stop playback immediately (R8).
- ``u`` use a refused transcript, ``d`` discard it — the delivery seam
  owns the transient hold (R19).
- ``q`` quit the pane.

The pane sequences the listen path without owning it: it never implements
send-text and never does HTTP itself. Delivery is imported lazily inside
the seam functions — U5 and U6 dispatch concurrently, so ``deliver`` is
never a module-level import here (KTD16); tests fake the seam.
"""

from __future__ import annotations

import sys
import termios
import tty
from collections.abc import Callable
from pathlib import Path

import binding
import record
import speak
import transcribe

__all__ = ["RECORDING_INDICATOR", "VoicePane", "toggle_once", "run"]

#: The loud, unmistakable in-pane recording indicator (R11).
RECORDING_INDICATOR = "*** RECORDING ***"

_HELP_LINE = (
    "keys: t toggle recording · s stop playback · u use refused · "
    "d discard refused · q quit"
)


def _deliver_default(text: str) -> None:
    """The delivery seam (KTD16): a function-level import, never module-level."""
    import deliver

    deliver.deliver(text)


def _use_refused_default() -> None:
    """The refused-transcript use seam (KTD16), lazily imported."""
    import deliver

    deliver.use_refused()


def _discard_refused_default() -> None:
    """The refused-transcript discard seam (KTD16), lazily imported."""
    import deliver

    deliver.discard_refused()


def toggle_once(
    *,
    stop_playback: Callable[[], None] = speak.stop_playback,
    toggle: Callable[[], Path | None] = record.toggle,
    transcribe_path: Callable[[Path], transcribe.Transcription] = transcribe.transcribe,
    deliver: Callable[[str], None] = _deliver_default,
) -> tuple[bool, list[str]]:
    """One toggle press, with the full completion sequence on an explicit stop.

    Playback stops first — starting a recording must silence any utterance
    in progress (R9), and the stop is a no-op when nothing plays. The
    toggle then either starts a recording (returns ``None``) or completes
    one: the wav path is transcribed through the declared relay and the
    transcript is delivered through the delivery seam — nothing is
    transcribed or sent before that explicit second press (R12). The pane
    key and the CLI ``toggle`` command share this one sequencer, so the
    listen path is sequenced in exactly one place (KTD16).

    Returns whether a recording now runs, plus operator-facing messages.
    Every failure propagates as the named refusal it already is; the
    caller is the surface that displays it.
    """
    stop_playback()
    wav_path = toggle()
    if wav_path is None:
        return True, ["recording started — press t to stop and deliver"]
    transcription = transcribe_path(wav_path)
    deliver(transcription.transcript)
    return False, ["transcript delivered unsubmitted"]


class VoicePane:
    """One pane's state machine: the seams, the indicator, and the keys."""

    def __init__(
        self,
        *,
        stop_playback: Callable[[], None] = speak.stop_playback,
        toggle: Callable[[], Path | None] = record.toggle,
        transcribe_path: Callable[[Path], transcribe.Transcription] = transcribe.transcribe,
        deliver: Callable[[str], None] = _deliver_default,
        use_refused: Callable[[], None] = _use_refused_default,
        discard_refused: Callable[[], None] = _discard_refused_default,
        read_binding_report: Callable[[], binding.BindingReport] = binding.read_binding_report,
    ) -> None:
        self._stop_playback = stop_playback
        self._toggle = toggle
        self._transcribe_path = transcribe_path
        self._deliver = deliver
        self._use_refused = use_refused
        self._discard_refused = discard_refused
        self._read_binding_report = read_binding_report
        self.recording = False

    def status_lines(self) -> list[str]:
        """The bound identity alongside the recording state (R4, R11).

        The binding is re-read on every redraw: the pane displays whatever
        is bound now, so a rebind or a stale binding becomes visible
        rather than surprising.
        """
        report = self._read_binding_report()
        lines: list[str] = []
        if report.status == binding.STATUS_BOUND and report.binding is not None:
            lines.append(
                f"bound: agent {report.binding.agent} · "
                f"session {report.binding.session_id}"
            )
        elif report.status == binding.STATUS_ABSENT:
            lines.append("not bound — run: voice_cli.py bind <herdr-agent>")
        else:
            lines.append(
                "binding unreadable — rebind: voice_cli.py bind <herdr-agent>"
            )
        if self.recording:
            lines.append(f"recording: {RECORDING_INDICATOR}")
        else:
            lines.append("recording: idle")
        return lines

    def handle_key(self, key: str) -> list[str]:
        """One keypress, applied immediately; returns the pane messages."""
        key = key.lower()
        if key == "t":
            return self._handle_toggle()
        if key == "s":
            return self._guarded(self._stop_playback, "playback stopped")
        if key == "u":
            return self._guarded(self._use_refused, "refused transcript delivered")
        if key == "d":
            return self._guarded(self._discard_refused, "refused transcript discarded")
        return []

    def _handle_toggle(self) -> list[str]:
        try:
            self.recording, messages = toggle_once(
                stop_playback=self._stop_playback,
                toggle=self._toggle,
                transcribe_path=self._transcribe_path,
                deliver=self._deliver,
            )
            return messages
        except Exception as error:
            # The pane is the error surface. A failed start leaves the pane
            # idle; a failed stop means the capture is already gone — the
            # recorder's own refusal says why.
            self.recording = False
            return [f"voice: {error}"]

    def _guarded(self, action: Callable[[], object], success: str) -> list[str]:
        try:
            action()
        except Exception as error:
            return [f"voice: {error}"]
        return [success]


class _TerminalKeys:
    """Single-character reads under ``tty.setcbreak``, restored on exit.

    The stream is left untouched when it is not a terminal — the loop then
    reads characters as they arrive, which is also how tests drive it.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._fd: int | None = None
        self._saved: list | None = None

    def __enter__(self) -> "_TerminalKeys":
        try:
            is_tty = self._stream.isatty()
            fd = self._stream.fileno()
        except (AttributeError, OSError, ValueError):
            return self
        if not is_tty:
            return self
        try:
            self._saved = termios.tcgetattr(fd)
        except termios.error:
            return self
        tty.setcbreak(fd)
        self._fd = fd
        return self

    def __exit__(self, *exc_info) -> None:
        if self._fd is not None and self._saved is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        return None

    def read_key(self) -> str:
        character = self._stream.read(1)
        return "" if character is None else character


def run(
    *,
    pane: VoicePane | None = None,
    read_key: Callable[[], str] | None = None,
    write_line: Callable[[str], None] | None = None,
    input_stream=None,
    output_stream=None,
) -> int:
    """Run the pane loop until ``q`` or end of input; returns the exit code.

    The status lines redraw after every keypress, so the bound identity
    and the recording state stay visible for the life of the pane (R4).
    """
    session = pane if pane is not None else VoicePane()
    output = output_stream if output_stream is not None else sys.stdout
    source = input_stream if input_stream is not None else sys.stdin

    def emit(line: str) -> None:
        if write_line is not None:
            write_line(line)
            return
        output.write(line + "\n")
        output.flush()

    emit("[voice] pane starting")
    for line in session.status_lines():
        emit(line)
    emit(_HELP_LINE)
    try:
        with _TerminalKeys(source) as keys:
            read = read_key if read_key is not None else keys.read_key
            while True:
                key = read()
                if key == "" or key.lower() == "q":
                    break
                for message in session.handle_key(key):
                    emit(message)
                for line in session.status_lines():
                    emit(line)
    except KeyboardInterrupt:
        pass  # The operator left the pane; the terminal is restored below.
    emit("[voice] pane stopped")
    return 0
