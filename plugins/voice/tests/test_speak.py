"""Tests for the Voice Forge speak path (R5, R6, R7, R23; KTD8, KTD3).

Every external seam is injected per KTD12 — HTTP through the opener seam,
the player through U1's subprocess seam, playback waiting through the
wait seam — so no test touches the network, spawns a platform binary, or
plays audio. The state directory points at a temp dir for the same
reason.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import providers  # noqa: E402
import settings  # noqa: E402
import speak  # noqa: E402

FORGE_BASE_URL = "http://forge.voice.example.invalid:8080"
FORGE_VOICE_ID = "example-voice"
PLAYBACK_BIN = "/usr/bin/afplay"


def _wav_bytes(frames: int, rate: int) -> bytes:
    """Build a real wav with a known duration: frames / rate seconds."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.closed = False

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        self.closed = True


class _HttpSeam:
    """Records the synthesis request and returns the configured response."""

    def __init__(self, audio_bytes: bytes, status: int = 200) -> None:
        self.requests: list = []
        self.response = _FakeResponse(audio_bytes, status=status)

    def __call__(self, request):
        self.requests.append(request)
        return self.response


class _PlayerSpawnSeam:
    """Records the player spawn instead of starting a platform binary."""

    pid = 4242

    def __init__(self, order: list | None = None) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._order = order

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if self._order is not None:
            self._order.append("spawn")
        return self

    def wait(self, *args, **kwargs):  # unused; spawn_detached never waits
        raise AssertionError("a detached spawn never waits on the child")


class SpeakTestBase(unittest.TestCase):
    """Shared fixture: inert settings and a temp state directory."""

    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_dir = Path(state.name)
        env = mock.patch.dict(
            os.environ,
            {
                "VOICE_FORGE_BASE_URL": FORGE_BASE_URL,
                "VOICE_FORGE_VOICE_ID": FORGE_VOICE_ID,
                "VOICE_STATE_DIR": str(self.state_dir),
                "VOICE_PLAYBACK_BIN": PLAYBACK_BIN,
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def _state_path(self, name: str) -> Path:
        return self.state_dir / name

    def _write_playback_state(self, pid: int, audio_path: Path) -> None:
        self._state_path("playback.json").write_text(
            json.dumps({"pid": pid, "audio_path": str(audio_path)}),
            encoding="utf-8",
        )


class SynthesisRequestTests(SpeakTestBase):
    """The request shape the declared provider receives."""

    def test_the_request_targets_the_speech_endpoint_with_the_configured_voice(
        self,
    ) -> None:
        http = _HttpSeam(_wav_bytes(100, 100))
        speak.speak(
            "Hello.",
            http_open=http,
            spawn=_PlayerSpawnSeam(),
            wait=lambda pid, deadline: 0,
        )
        (request,) = http.requests
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_full_url(), FORGE_BASE_URL + "/v1/audio/speech")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            body,
            {"input": "Hello.", "voice": FORGE_VOICE_ID, "response_format": "wav"},
        )

    def test_the_base_url_is_taken_from_settings_not_hard_coded(self) -> None:
        http = _HttpSeam(_wav_bytes(100, 100))
        with mock.patch.dict(
            os.environ, {"VOICE_FORGE_BASE_URL": "http://other.example.invalid:9090/"}
        ):
            speak.speak(
                "Hello.",
                http_open=http,
                spawn=_PlayerSpawnSeam(),
                wait=lambda pid, deadline: 0,
            )
        (request,) = http.requests
        self.assertEqual(
            request.get_full_url(), "http://other.example.invalid:9090/v1/audio/speech"
        )


class PlaybackLifecycleTests(SpeakTestBase):
    """Wav handling, the duration-derived deadline, and ephemeral audio."""

    def test_wav_bytes_land_in_the_state_dir_and_are_deleted_after_playback(
        self,
    ) -> None:
        observed: dict = {}

        def wait(pid, deadline):
            observed["pid"] = pid
            observed["deadline"] = deadline
            observed["wav_files"] = list(self.state_dir.glob("speak-*.wav"))
            observed["playback_state"] = json.loads(
                self._state_path("playback.json").read_text(encoding="utf-8")
            )
            return 0

        speak.speak(
            "Hello.",
            http_open=_HttpSeam(_wav_bytes(100, 100)),
            spawn=_PlayerSpawnSeam(),
            wait=wait,
        )
        (wav_path,) = observed["wav_files"]
        self.assertEqual(wav_path.parent, self.state_dir)
        self.assertEqual(observed["pid"], _PlayerSpawnSeam.pid)
        self.assertEqual(
            observed["playback_state"],
            {"pid": _PlayerSpawnSeam.pid, "audio_path": str(wav_path)},
        )
        # Ephemeral posture: nothing survives a successful utterance.
        self.assertFalse(wav_path.exists())
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])
        self.assertFalse(self._state_path("playback.json").exists())

    def test_the_playback_deadline_derives_from_the_wav_duration(self) -> None:
        cases = [
            (_wav_bytes(100, 100), 100 / 100 + 2.0),  # one second of audio
            (_wav_bytes(200, 50), 200 / 50 + 2.0),  # four seconds of audio
        ]
        for audio_bytes, expected_deadline in cases:
            with self.subTest(expected_deadline=expected_deadline):
                deadlines: list[float] = []
                speak.speak(
                    "Hello.",
                    http_open=_HttpSeam(audio_bytes),
                    spawn=_PlayerSpawnSeam(),
                    wait=lambda pid, deadline: deadlines.append(deadline) or 0,
                )
                self.assertEqual(len(deadlines), 1)
                self.assertAlmostEqual(deadlines[0], expected_deadline)

    def test_the_player_starts_detached_with_closed_stdin(self) -> None:
        spawn = _PlayerSpawnSeam()
        speak.speak(
            "Hello.",
            http_open=_HttpSeam(_wav_bytes(100, 100)),
            spawn=spawn,
            wait=lambda pid, deadline: 0,
        )
        ((command, kwargs),) = spawn.calls
        self.assertEqual(command[0], PLAYBACK_BIN)
        self.assertTrue(command[1].endswith(".wav"))
        self.assertEqual(Path(command[1]).parent, self.state_dir)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_a_missing_playback_binary_is_a_named_refusal(self) -> None:
        absent = str(self.state_dir / "no-such-player-binary")
        with mock.patch.dict(os.environ, {"VOICE_PLAYBACK_BIN": absent}):
            with self.assertRaises(providers.ProviderRefusal) as caught:
                speak.speak(
                    "Hello.",
                    http_open=_HttpSeam(_wav_bytes(100, 100)),
                    spawn=subprocess.Popen,  # real Popen; the binary is absent
                    wait=lambda pid, deadline: 0,
                )
        self.assertEqual(caught.exception.provider, providers.VOICE_FORGE)
        # The synthesized audio is deleted on this failure path too.
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])

    def test_a_nonzero_player_exit_is_a_named_refusal(self) -> None:
        with self.assertRaises(providers.ProviderRefusal):
            speak.speak(
                "Hello.",
                http_open=_HttpSeam(_wav_bytes(100, 100)),
                spawn=_PlayerSpawnSeam(),
                wait=lambda pid, deadline: 1 << 8,  # exited with status 1
            )
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])
        self.assertFalse(self._state_path("playback.json").exists())

    def test_a_player_stopped_by_signal_exits_silently(self) -> None:
        # The operator's stop key terminates the player mid-utterance; the
        # speak child treats that as a stop, not a failure.
        speak.speak(
            "Hello.",
            http_open=_HttpSeam(_wav_bytes(100, 100)),
            spawn=_PlayerSpawnSeam(),
            wait=lambda pid, deadline: signal.SIGTERM,
        )
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])

    def test_a_deadline_that_passes_stops_the_player_and_refuses_by_name(
        self,
    ) -> None:
        killed: list[tuple[int, int]] = []
        # The clock reads 0.0 when the deadline is set, then jumps past it,
        # so the first expiry check is already expired.
        clock_values = iter([0.0, 99.0])
        with mock.patch.object(speak.os, "waitpid", return_value=(0, 0)):
            with mock.patch.object(
                speak.os,
                "kill",
                side_effect=lambda pid, signum: killed.append((pid, signum)),
            ):
                with self.assertRaises(providers.ProviderRefusal):
                    speak.speak(
                        "Hello.",
                        http_open=_HttpSeam(_wav_bytes(100, 100)),
                        spawn=_PlayerSpawnSeam(),
                        wait=lambda pid, deadline: speak._await_exit(
                            pid,
                            deadline,
                            clock=lambda: next(clock_values),
                            sleep=lambda seconds: None,
                        ),
                    )
        self.assertEqual(killed, [(_PlayerSpawnSeam.pid, signal.SIGKILL)])
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])


class SynthesisFailureTests(SpeakTestBase):
    """Unreachable or unhealthy synthesis refuses by name (R23)."""

    def _assert_refusal(self, error: Exception) -> None:
        spawn = _PlayerSpawnSeam()
        with self.assertRaises(providers.ProviderRefusal) as caught:
            speak.speak("Hello.", http_open=error, spawn=spawn, wait=None)
        self.assertEqual(caught.exception.provider, providers.VOICE_FORGE)
        self.assertEqual(spawn.calls, [], "nothing substitutes for the provider")
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])

    def test_an_unreachable_provider_raises_the_named_refusal(self) -> None:
        def unreachable(request):
            raise urllib.error.URLError(ConnectionRefusedError("refused"))

        self._assert_refusal(unreachable)

    def test_a_timeout_raises_the_named_refusal(self) -> None:
        def timed_out(request):
            raise urllib.error.URLError(TimeoutError("timed out"))

        self._assert_refusal(timed_out)

    def test_a_non_2xx_response_raises_the_named_refusal(self) -> None:
        def refused(request):
            raise urllib.error.HTTPError(
                request.get_full_url(), 503, "unhealthy", hdrs=None, fp=None
            )

        self._assert_refusal(refused)

    def test_a_returned_non_2xx_status_raises_the_named_refusal(self) -> None:
        http = _HttpSeam(_wav_bytes(100, 100), status=500)
        with self.assertRaises(providers.ProviderRefusal):
            speak.speak(
                "Hello.", http_open=http, spawn=_PlayerSpawnSeam(), wait=None
            )

    def test_unusable_audio_is_a_named_refusal(self) -> None:
        http = _HttpSeam(b"this is not a wav file")
        with self.assertRaises(providers.ProviderRefusal):
            speak.speak(
                "Hello.", http_open=http, spawn=_PlayerSpawnSeam(), wait=None
            )
        self.assertEqual(list(self.state_dir.glob("speak-*.wav")), [])

    def test_missing_forge_settings_refuse_by_name(self) -> None:
        env = {"VOICE_STATE_DIR": str(self.state_dir)}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(settings.SettingsRefusal):
                speak.speak(
                    "Hello.", http_open=_HttpSeam(b""), spawn=_PlayerSpawnSeam()
                )


class StopPlaybackTests(SpeakTestBase):
    """The stop handle U6 binds to its key and barge-in."""

    def test_stop_playback_terminates_the_recorded_pid(self) -> None:
        audio_path = self.state_dir / "live.wav"
        audio_path.write_bytes(b"placeholder")
        self._write_playback_state(4242, audio_path)
        kills: list[tuple[int, int]] = []
        speak.stop_playback(kill=lambda pid, signum: kills.append((pid, signum)))
        self.assertEqual(kills, [(4242, signal.SIGTERM)])
        self.assertFalse(audio_path.exists())
        self.assertFalse(self._state_path("playback.json").exists())

    def test_stop_playback_with_no_state_is_a_noop(self) -> None:
        kills: list[tuple[int, int]] = []
        speak.stop_playback(kill=lambda pid, signum: kills.append((pid, signum)))
        self.assertEqual(kills, [])

    def test_stop_playback_with_corrupt_state_is_a_noop(self) -> None:
        self._state_path("playback.json").write_text("not json", encoding="utf-8")
        kills: list[tuple[int, int]] = []
        speak.stop_playback(kill=lambda pid, signum: kills.append((pid, signum)))
        self.assertEqual(kills, [])
        self.assertFalse(self._state_path("playback.json").exists())

    def test_stop_playback_tolerates_an_already_gone_process(self) -> None:
        audio_path = self.state_dir / "live.wav"
        audio_path.write_bytes(b"placeholder")
        self._write_playback_state(4242, audio_path)

        def kill(pid, signum):
            raise ProcessLookupError(pid)

        speak.stop_playback(kill=kill)
        self.assertFalse(audio_path.exists())
        self.assertFalse(self._state_path("playback.json").exists())

    def test_speak_stops_any_current_playback_before_starting_a_new_one(
        self,
    ) -> None:
        stale_audio = self.state_dir / "stale.wav"
        stale_audio.write_bytes(b"placeholder")
        self._write_playback_state(4321, stale_audio)
        order: list[str] = []
        spawn = _PlayerSpawnSeam(order=order)
        with mock.patch.object(
            speak, "stop_playback", side_effect=lambda **kwargs: order.append("stop")
        ):
            speak.speak(
                "Hello.",
                http_open=_HttpSeam(_wav_bytes(100, 100)),
                spawn=spawn,
                wait=lambda pid, deadline: 0,
            )
        self.assertEqual(order, ["stop", "spawn"])


class RefusalEntryPointTests(SpeakTestBase):
    """U5's audible refusal speaks through this same entry point."""

    def test_the_refusal_entry_point_speaks_a_supplied_message(self) -> None:
        phrase = "The bound session is blocked on a prompt; not delivering that."
        http = _HttpSeam(_wav_bytes(100, 100))
        speak.speak(
            phrase,
            http_open=http,
            spawn=_PlayerSpawnSeam(),
            wait=lambda pid, deadline: 0,
        )
        (request,) = http.requests
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["input"], phrase)

    def test_empty_text_synthesizes_nothing(self) -> None:
        for text in ("", "   ", "\n"):
            with self.subTest(text=text):
                http = _HttpSeam(_wav_bytes(100, 100))
                speak.speak(
                    text,
                    http_open=http,
                    spawn=_PlayerSpawnSeam(),
                    wait=lambda pid, deadline: 0,
                )
                self.assertEqual(http.requests, [])


class PayloadChildTests(SpeakTestBase):
    """The KTD2 child: consume the payload, delete it in a finally."""

    def _write_payload(self, payload) -> Path:
        path = self.state_dir / "speak-payload.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
        return path

    def test_the_child_speaks_the_cleaned_text_verbatim(self) -> None:
        payload_path = self._write_payload(
            {"text": "## Done\n\nTests are `green`.\n\n```\nhidden\n```\n"}
        )
        http = _HttpSeam(_wav_bytes(100, 100))
        speak.run_payload(
            payload_path,
            http_open=http,
            spawn=_PlayerSpawnSeam(),
            wait=lambda pid, deadline: 0,
        )
        (request,) = http.requests
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["input"], "Done\nTests are green.")
        self.assertFalse(payload_path.exists())

    def test_the_payload_is_deleted_when_cleaning_leaves_nothing_to_say(
        self,
    ) -> None:
        payload_path = self._write_payload({"text": "```python\nprint('hidden')\n```"})
        http = _HttpSeam(_wav_bytes(100, 100))
        speak.run_payload(
            payload_path,
            http_open=http,
            spawn=_PlayerSpawnSeam(),
            wait=lambda pid, deadline: 0,
        )
        self.assertFalse(payload_path.exists())
        self.assertEqual(http.requests, [], "R7's omission synthesizes nothing")

    def test_the_payload_is_deleted_when_synthesis_fails(self) -> None:
        payload_path = self._write_payload({"text": "Hello."})

        def unreachable(request):
            raise urllib.error.URLError(ConnectionRefusedError("refused"))

        with self.assertRaises(providers.ProviderRefusal):
            speak.run_payload(
                payload_path,
                http_open=unreachable,
                spawn=_PlayerSpawnSeam(),
                wait=lambda pid, deadline: 0,
            )
        self.assertFalse(payload_path.exists())

    def test_a_malformed_payload_synthesizes_nothing_and_is_deleted(self) -> None:
        for payload in ("not json", "[1, 2, 3]", '{"text": 42}', "{}"):
            with self.subTest(payload=payload):
                payload_path = self._write_payload(payload)
                http = _HttpSeam(_wav_bytes(100, 100))
                speak.run_payload(
                    payload_path,
                    http_open=http,
                    spawn=_PlayerSpawnSeam(),
                    wait=lambda pid, deadline: 0,
                )
                self.assertFalse(payload_path.exists())
                self.assertEqual(http.requests, [])

    def test_main_returns_zero_and_deletes_the_payload_on_a_silent_skip(
        self,
    ) -> None:
        payload_path = self._write_payload({"text": "```\nonly code\n```"})
        self.assertEqual(speak.main([str(payload_path)]), 0)
        self.assertFalse(payload_path.exists())

    def test_main_returns_zero_and_deletes_a_missing_payload(self) -> None:
        payload_path = self.state_dir / "never-written.json"
        self.assertEqual(speak.main([str(payload_path)]), 0)

    def test_main_returns_one_when_synthesis_refuses(self) -> None:
        payload_path = self._write_payload({"text": "Hello."})
        refusal = providers.ProviderRefusal(providers.VOICE_FORGE, "unreachable")
        with mock.patch.object(speak, "speak", side_effect=refusal):
            self.assertEqual(speak.main([str(payload_path)]), 1)
        self.assertFalse(payload_path.exists())

    def test_main_without_one_payload_argument_is_a_usage_error(self) -> None:
        self.assertEqual(speak.main([]), 2)
        self.assertEqual(speak.main(["one", "two"]), 2)


if __name__ == "__main__":
    unittest.main()
