"""Capture path for the voice package: toggled recording, nothing left behind.

Recording is toggled (R10): one press starts it, a second press stops it.
Version one does not implement press-and-hold. The active recorder — its pid
and the wav path it writes — is tracked in ``recording.json`` under the state
directory (KTD1), written atomically.

Nothing is transcribed and nothing is sent until the operator explicitly
stops the recording (R12). This module never touches the transcription path:
after an explicit stop it returns the wav path, and the Voice pane sequences
transcription. A recording that never reaches an explicit stop — abandoned,
or ended by the capture ceiling — is deleted, not transcribed: the ephemeral
posture (D5) covers audio that never reached transcription, not only the
after-transcription case (R25).

The recorder is the operator-supplied capture executable (D3) with the macOS
AVFoundation input device. The argv is fixed: ``-f avfoundation``, ``-i :0``
(the version-one default microphone — a non-zero recorder exit is a named
refusal, never device discovery), and ``-t 600``. The ceiling is both the
media ceiling and the subprocess deadline (KTD3c): the recorder stops itself
when it expires, and a detached child carries its deadline internally because
its parent never waits for it. The recorder is spawned through the package's
subprocess discipline: its own session, standard input closed, no shell.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import process
import settings

__all__ = [
    "RecordRefusal",
    "CAPTURE_CEILING_SECONDS",
    "toggle",
    "start",
    "stop",
]

#: The capture ceiling in seconds (KTD3c): both the media ceiling and the
#: recorder's deadline. Expiry ends capture, deletes the wav, and never
#: transcribes — transcription happens only on an explicit stop press (R12).
CAPTURE_CEILING_SECONDS = 600

CAPTURE_FORMAT = "avfoundation"
CAPTURE_DEVICE = ":0"

#: How long an explicit stop waits for the recorder to flush the wav before
#: escalating. Bounded, so the stop path carries a deadline like every child.
STOP_WAIT_SECONDS = 5.0

_RECORDING_FILE_NAME = "recording.json"


class RecordRefusal(Exception):
    """A named refusal on the capture path.

    Carries the reason capture cannot proceed, so the pane can report it by
    name. Voice never substitutes a capture result for a refusal.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _recording_file() -> Path:
    return settings.state_dir() / _RECORDING_FILE_NAME


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write state as a JSON file via write-temp-then-replace (KTD1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _read_active() -> dict | None:
    """The active recording state, or None.

    Absent and corrupt both read as no active recording; the distinction a
    caller needs is carried by the recorder pid's liveness, not by the file.
    """
    try:
        payload = json.loads(_recording_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    wav_path = payload.get("wav_path")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    if not isinstance(wav_path, str) or not wav_path.strip():
        return None
    return {"pid": pid, "wav_path": wav_path}


def _pid_alive(pid: int) -> bool:
    """Probe whether the recorder pid is still running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        # The process exists but the probe is not permitted to signal it;
        # for the single-operator case that still means it is running.
        return True
    return True


def _terminate_and_reap(pid: int) -> None:
    """Give the recorder a graceful stop and wait for it under a deadline.

    The recorder flushes the wav on a termination signal; the bounded wait
    guarantees the stop path never hangs on it, and escalation ends it if it
    does not exit in time.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            waited, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return  # Not this process's child (a pane restart); nothing to reap.
        if waited == pid:
            return
        time.sleep(0.02)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def _abandon(active: dict) -> None:
    """Delete a recording that never reached an explicit stop.

    An abandoned recording and a ceiling-expired one produce no transcription
    request (R12): the wav is deleted, the state is cleared, and nothing else
    happens. This is the ephemeral posture covering audio that never reached
    transcription.
    """
    Path(active["wav_path"]).unlink(missing_ok=True)
    _recording_file().unlink(missing_ok=True)


def start(
    *,
    spawn: Callable = subprocess.Popen,
    alive: Callable[[int], bool] = _pid_alive,
) -> None:
    """Start one recording; a second start while one runs is refused by name.

    The recorder is spawned detached with the fixed capture argv — the
    operator-supplied executable, the AVFoundation default microphone, the
    ceiling as both media ceiling and deadline — and the active state is
    recorded for the toggle and for stop.
    """
    active = _read_active()
    if active is not None:
        if alive(active["pid"]):
            raise RecordRefusal(
                "a recording is already in progress; press the toggle to stop it"
            )
        _abandon(active)
    wav_path = settings.state_dir() / f"capture-{uuid.uuid4().hex}.wav"
    argv = [
        settings.capture_bin(),
        "-f",
        CAPTURE_FORMAT,
        "-i",
        CAPTURE_DEVICE,
        "-t",
        str(CAPTURE_CEILING_SECONDS),
        str(wav_path),
    ]
    try:
        pid = process.spawn_detached(argv, spawn=spawn)
    except OSError as exc:
        raise RecordRefusal(f"the capture executable refused to start: {exc}") from exc
    _atomic_write_json(_recording_file(), {"pid": pid, "wav_path": str(wav_path)})


def stop(
    *,
    alive: Callable[[int], bool] = _pid_alive,
    reap: Callable[[int], None] = _terminate_and_reap,
) -> Path:
    """End the active recording on the operator's explicit stop press.

    Returns the recorded wav path for the pane to transcribe; the file stays
    on disk until transcription deletes it (R25). A stop with no active
    recording is refused by name, and a recorder that already exited —
    ceiling expiry or crash — deletes its wav and is refused by name, never
    transcribed (R12).
    """
    active = _read_active()
    if active is None:
        raise RecordRefusal("no recording is active; there is nothing to stop")
    if not alive(active["pid"]):
        _abandon(active)
        raise RecordRefusal(
            "the recorder exited before an explicit stop; the capture was "
            "deleted and nothing was transcribed"
        )
    reap(active["pid"])
    _recording_file().unlink(missing_ok=True)
    return Path(active["wav_path"])


def toggle(
    *,
    spawn: Callable = subprocess.Popen,
    alive: Callable[[int], bool] = _pid_alive,
    reap: Callable[[int], None] = _terminate_and_reap,
) -> Path | None:
    """One key press, one toggle (R10).

    Returns ``None`` when a recording just started and the wav path when an
    explicit stop just completed. A press that finds a dead recorder —
    abandoned or ceiling-expired — cleans that capture up without
    transcribing it, then starts a fresh recording.
    """
    active = _read_active()
    if active is not None:
        if alive(active["pid"]):
            return stop(alive=alive, reap=reap)
        _abandon(active)
    start(spawn=spawn, alive=alive)
    return None
