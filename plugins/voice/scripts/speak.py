"""Voice Forge synthesis and playback — the speak path (R5, R6, R7; KTD8).

Turns one completed response into speech through the declared
``voice-forge`` provider and nothing else. Two module-level entry points
serve the rest of the package: :func:`speak` synthesizes and plays a text
(U5 calls it for the audible blocked-state refusal), and
:func:`stop_playback` terminates any playback in progress immediately
(U6's stop key and barge-in). Run as the KTD2 child —
``python3 speak.py <payload.json>`` — it consumes one payload file,
deletes that file in a ``finally``, cleans the text through
``text_cleanup`` (KTD10), and speaks it.

Synthesis POSTs the OpenAI-compatible body — ``input``, ``voice`` from
``VOICE_FORGE_VOICE_ID``, ``response_format`` = ``wav`` — to
``{VOICE_FORGE_BASE_URL}/v1/audio/speech``, built on ``urllib.request``
with a 10-second connect deadline and a 300-second read deadline (KTD3d).
The wav response lands in a unique file under the state directory and is
played through ``VOICE_PLAYBACK_BIN`` under a deadline derived from the
audio's own duration plus a 2-second margin (KTD3b), so a long reply gets
a long deadline and is spoken whole. No length gate of any kind exists on
this path (R5): a deadline that passes is a named refusal, never a
shortened utterance. ``playback.json`` carries the live player pid and
the audio path while playback runs; the audio file is deleted when
playback ends, is stopped, or fails (D5's ephemeral posture).

An unreachable or unhealthy provider is a named refusal carrying the
provider name; nothing substitutes for it (R23). A response whose cleaned
text is empty — a reply that was only a fenced code block, for example —
synthesizes nothing and exits silently: that is R7's omission, not a
failure.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections.abc import Callable
from pathlib import Path

import process
import providers
import settings
import text_cleanup

__all__ = ["speak", "stop_playback", "run_payload", "main"]

SPEECH_PATH = "/v1/audio/speech"

#: The synthesis deadlines (KTD3d): connect is bounded tightly so an
#: unreachable endpoint refuses fast, while the read side stays generous —
#: it bounds the wait for a long utterance, it never shortens one.
SYNTHESIS_CONNECT_TIMEOUT = 10.0
SYNTHESIS_READ_TIMEOUT = 300.0

#: Playback's deadline is the audio's own duration plus this margin (KTD3b).
PLAYBACK_MARGIN_SECONDS = 2.0

_PAYLOAD_TEXT_KEY = "text"


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    """HTTP handler carrying the split synthesis deadlines."""

    def http_open(self, request):
        return self.do_open(_deadline_connection(http.client.HTTPConnection), request)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS handler carrying the split synthesis deadlines."""

    def https_open(self, request):
        return self.do_open(
            _deadline_connection(http.client.HTTPSConnection),
            request,
            context=self._context,
        )


def _deadline_connection(connection_class):
    """Build a connection that connects under one deadline, reads under the other.

    ``urllib.request`` hands a single socket timeout to both phases, so the
    pinned pair is enforced here: the connection opens under the connect
    deadline, and once it is up the socket is re-armed under the read
    deadline for the synthesis wait and the body transfer.
    """

    def connect(host, **kwargs):
        kwargs.pop("timeout", None)
        connection = connection_class(
            host, timeout=SYNTHESIS_CONNECT_TIMEOUT, **kwargs
        )
        connection.connect()
        connection.sock.settimeout(SYNTHESIS_READ_TIMEOUT)
        return connection

    return connect


def _default_http_open(request):
    """The default opener seam, built on ``urllib.request``."""
    opener = urllib.request.build_opener(
        _DeadlineHTTPHandler(), _DeadlineHTTPSHandler()
    )
    return opener.open(request, timeout=SYNTHESIS_READ_TIMEOUT)


def speak(
    text: str,
    *,
    http_open: Callable = _default_http_open,
    spawn: Callable = subprocess.Popen,
    wait: Callable | None = None,
) -> None:
    """Synthesize ``text`` through Voice Forge and play it.

    Any playback still running is stopped first, so a new utterance
    replaces it instead of overlapping. Empty text synthesizes nothing.
    Every failure on the path is a named refusal; nothing substitutes for
    the declared provider (R23). The seams mirror KTD12: HTTP through an
    opener seam, the player through U1's subprocess seam.
    """
    if not text or not text.strip():
        return
    stop_playback()
    audio_bytes = _synthesize(text, http_open=http_open)
    directory = settings.state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = directory / f"speak-{uuid.uuid4()}.wav"
    audio_path.write_bytes(audio_bytes)
    await_exit = wait if wait is not None else _await_exit
    try:
        deadline_seconds = _wav_duration_seconds(audio_path) + PLAYBACK_MARGIN_SECONDS
        argv = [settings.playback_bin(), str(audio_path)]
        try:
            pid = process.spawn_detached(argv, spawn=spawn)
        except OSError as error:
            raise providers.ProviderRefusal(
                providers.VOICE_FORGE, f"playback binary cannot start: {error}"
            ) from error
        _write_playback_state(pid, audio_path)
        try:
            status = await_exit(pid, deadline_seconds)
        finally:
            _clear_playback_state()
    finally:
        audio_path.unlink(missing_ok=True)
    if os.WIFSIGNALED(status):
        # Terminated from outside — the operator's stop key, or a barge-in
        # starting a recording. A stop is not a failure.
        return
    exit_code = os.WEXITSTATUS(status)
    if exit_code != 0:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE, f"playback exited with status {exit_code}"
        )


def stop_playback(*, kill: Callable = os.kill) -> None:
    """Terminate any live playback immediately (R8, R9 support).

    Reads ``playback.json`` for the live player pid and the audio path,
    terminates the process, deletes the audio file, and clears the state.
    Absent, stale, or unreadable state is a no-op: there is nothing to
    stop.
    """
    state = _read_playback_state()
    _clear_playback_state()
    if state is None:
        return
    try:
        kill(state["pid"], signal.SIGTERM)
    except OSError:
        pass  # Already gone — nothing to terminate.
    Path(state["audio_path"]).unlink(missing_ok=True)


def run_payload(
    payload_path,
    *,
    http_open: Callable = _default_http_open,
    spawn: Callable = subprocess.Popen,
    wait: Callable | None = None,
) -> None:
    """The KTD2 child body: consume one payload file and speak its text.

    The payload is deleted in a ``finally``, on every exit path. A
    malformed payload synthesizes nothing, and a response whose cleaned
    text is empty synthesizes nothing and exits silently — that is R7's
    omission, not a failure.
    """
    path = Path(payload_path)
    try:
        text = _read_payload_text(path)
    finally:
        path.unlink(missing_ok=True)
    if text is None:
        return
    cleaned = text_cleanup.clean(text)
    if not cleaned.strip():
        return
    speak(cleaned, http_open=http_open, spawn=spawn, wait=wait)


def main(argv=None) -> int:
    """Run as the detached speak child: ``python3 speak.py <payload.json>``."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: python3 speak.py <payload.json>", file=sys.stderr)
        return 2
    try:
        run_payload(Path(arguments[0]))
    except (providers.ProviderRefusal, settings.SettingsRefusal) as refusal:
        print(f"voice: {refusal}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"voice: {error}", file=sys.stderr)
        return 1
    return 0


def _synthesize(cleaned_text: str, *, http_open: Callable) -> bytes:
    """POST the synthesis request and return the provider's wav bytes."""
    url = settings.forge_base_url().rstrip("/") + SPEECH_PATH
    body = json.dumps(
        {
            "input": cleaned_text,
            "voice": settings.forge_voice_id(),
            "response_format": "wav",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        response = http_open(request)
        try:
            _refuse_non_success(response)
            audio_bytes = response.read()
        finally:
            close = getattr(response, "close", None)
            if close is not None:
                close()
    except urllib.error.HTTPError as error:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE,
            f"synthesis refused with HTTP status {error.code}",
        ) from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE, f"synthesis request failed: {error}"
        ) from error
    return audio_bytes


def _refuse_non_success(response) -> None:
    """Refuse a returned non-2xx status by name (R23)."""
    status = getattr(response, "status", None)
    if status is None:
        status = getattr(response, "code", None)
    if isinstance(status, int) and not 200 <= status < 300:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE,
            f"synthesis refused with HTTP status {status}",
        )


def _wav_duration_seconds(audio_path: Path) -> float:
    """Read the wav's real duration so the playback deadline follows it."""
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            rate = wav_file.getframerate()
    except (wave.Error, EOFError, OSError, ValueError) as error:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE,
            f"synthesis returned unusable audio: {error}",
        ) from error
    if rate <= 0:
        raise providers.ProviderRefusal(
            providers.VOICE_FORGE, "synthesis returned audio with no sample rate"
        )
    return frames / rate


def _await_exit(
    pid: int,
    deadline_seconds: float,
    *,
    poll_interval: float = 0.05,
    clock: Callable = time.monotonic,
    sleep: Callable = time.sleep,
) -> int:
    """Wait for the player to exit under its deadline; return the wait status.

    The deadline follows the audio's duration (KTD3b); passing it is a
    named refusal. The player is stopped and reaped before the refusal
    surfaces, so nothing keeps playing past its deadline.
    """
    limit = clock() + deadline_seconds
    while True:
        reaped, status = os.waitpid(pid, os.WNOHANG)
        if reaped == pid:
            return status
        if clock() >= limit:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except OSError:
                pass
            raise providers.ProviderRefusal(
                providers.VOICE_FORGE,
                "playback did not finish within its "
                f"{deadline_seconds:.1f}-second deadline and was stopped",
            )
        sleep(poll_interval)


def _read_payload_text(path: Path) -> str | None:
    """Read one KTD1 payload; ``None`` when it is absent or malformed."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    text = payload.get(_PAYLOAD_TEXT_KEY)
    if not isinstance(text, str):
        return None
    return text


def _playback_state_path() -> Path:
    return settings.state_dir() / "playback.json"


def _write_playback_state(pid: int, audio_path: Path) -> None:
    """Record the live player pid and audio path, atomically (KTD1)."""
    state_path = _playback_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(f"{state_path.name}.tmp-{os.getpid()}")
    temp_path.write_text(
        json.dumps({"pid": pid, "audio_path": str(audio_path)}),
        encoding="utf-8",
    )
    os.replace(temp_path, state_path)


def _read_playback_state() -> dict | None:
    try:
        raw = _playback_state_path().read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    audio_path = payload.get("audio_path")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if not isinstance(audio_path, str) or not audio_path:
        return None
    return {"pid": pid, "audio_path": audio_path}


def _clear_playback_state() -> None:
    _playback_state_path().unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
