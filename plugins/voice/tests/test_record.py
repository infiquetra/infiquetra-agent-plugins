"""Tests for the capture toggle (R10, R12; KTD1, KTD3c, D3, D5).

Every seam is injected, so no test spawns a platform binary or issues a
request: the recorder spawn, the pid liveness probe, and the terminate-and-
reap step are fakes, and this module carries no seam that could transcribe.
The retention scenarios compose the capture toggle with the transcription
entry point the Voice pane sequences, because audio deletion after a
completed or failed transcription is what the ephemeral posture promises.
"""

from __future__ import annotations

import base64
import inspect
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import providers  # noqa: E402
import record  # noqa: E402
import settings  # noqa: E402
import transcribe  # noqa: E402

_AUDIO_BYTES = b"RIFF-inert-example-audio"
_TOKEN_PAGE = (
    "<html><script>window.__HERMES_SESSION_TOKEN__ = "
    '"inert-session-token-1";</script></html>'
).encode("utf-8")


class _FakeRecorder:
    pid = 4242


class _RecorderSeam:
    """Records the recorder spawn instead of spawning a platform binary."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return _FakeRecorder()


class _ReapSeam:
    """Records the terminate-and-reap step instead of signalling a pid."""

    def __init__(self) -> None:
        self.pids: list[int] = []

    def __call__(self, pid: int) -> None:
        self.pids.append(pid)


class _OpenerSeam:
    """Replays canned relay answers and records every request."""

    def __init__(self, answers) -> None:
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        if not self.answers:
            raise AssertionError("an unexpected request was issued")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _alive(pid: int) -> bool:
    return True


def _dead(pid: int) -> bool:
    return False


def _transcription_ok(transcript: str = "example transcript") -> tuple[int, bytes]:
    payload = {"transcript": transcript, "provider": "xai", "ok": True}
    return 200, json.dumps(payload).encode("utf-8")


class RecordTestCase(unittest.TestCase):
    """A controlled state directory and environment for every scenario."""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.state_dir = Path(self._temp.name)
        env = {
            settings.STATE_DIR: str(self.state_dir),
            settings.CAPTURE_BIN: "/example/capture",
        }
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def recording_file(self) -> Path:
        return self.state_dir / "recording.json"

    def read_recording(self) -> dict:
        return json.loads(self.recording_file().read_text(encoding="utf-8"))

    def write_stale_recording(self, wav_name: str = "capture-stale.wav") -> Path:
        """A recording state whose recorder is already dead."""
        wav_path = self.state_dir / wav_name
        wav_path.write_bytes(_AUDIO_BYTES)
        self.recording_file().write_text(
            json.dumps({"pid": 424242, "wav_path": str(wav_path)}),
            encoding="utf-8",
        )
        return wav_path


class ToggleSemanticsTests(RecordTestCase):
    """One press starts, a second press stops (R10)."""

    def test_one_press_starts_and_the_second_stops_and_returns_the_wav_path(
        self,
    ) -> None:
        seam = _RecorderSeam()
        reap = _ReapSeam()
        self.assertIsNone(
            record.toggle(spawn=seam, alive=_alive, reap=reap)
        )
        wav = record.toggle(spawn=seam, alive=_alive, reap=reap)
        self.assertIsInstance(wav, Path)
        self.assertEqual(wav.parent, self.state_dir)
        self.assertEqual(reap.pids, [_FakeRecorder.pid])
        self.assertEqual(len(seam.calls), 1, "the stop press spawns no second recorder")
        self.assertFalse(self.recording_file().exists())

    def test_the_first_press_writes_the_active_recording_state(self) -> None:
        seam = _RecorderSeam()
        self.assertIsNone(record.toggle(spawn=seam, alive=_alive, reap=_ReapSeam()))
        state = self.read_recording()
        self.assertEqual(state["pid"], _FakeRecorder.pid)
        wav_path = Path(state["wav_path"])
        self.assertEqual(wav_path.parent, self.state_dir)
        self.assertTrue(wav_path.name.startswith("capture-"))
        self.assertTrue(wav_path.name.endswith(".wav"))

    def test_the_recorder_argv_carries_the_settled_shape_with_ceiling_and_closed_stdin(
        self,
    ) -> None:
        seam = _RecorderSeam()
        record.start(spawn=seam, alive=_alive)
        ((command, kwargs),) = seam.calls
        wav_path = self.read_recording()["wav_path"]
        self.assertEqual(
            command,
            [
                "/example/capture",
                "-f",
                "avfoundation",
                "-i",
                ":0",
                "-t",
                "600",
                wav_path,
            ],
        )
        # The -t ceiling is both the media ceiling and the subprocess
        # deadline (KTD3c); the recorder carries it internally because its
        # parent never waits for it.
        self.assertEqual(record.CAPTURE_CEILING_SECONDS, 600)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_nothing_is_transcribed_before_the_second_press(self) -> None:
        seam = _RecorderSeam()
        self.assertIsNone(record.toggle(spawn=seam, alive=_alive, reap=_ReapSeam()))
        self.assertEqual(len(seam.calls), 1)
        self.assertTrue(self.recording_file().exists())
        # Capture carries no seam that could issue a transcription request:
        # the module never imports or calls the transcription module. The
        # Voice pane sequences transcription after an explicit stop (KTD16).
        self.assertNotIn("import transcribe", inspect.getsource(record))

    def test_a_corrupt_state_file_reads_as_no_active_recording(self) -> None:
        self.recording_file().write_text("{not json", encoding="utf-8")
        with self.assertRaises(record.RecordRefusal):
            record.stop(alive=_alive, reap=_ReapSeam())
        seam = _RecorderSeam()
        self.assertIsNone(record.toggle(spawn=seam, alive=_alive, reap=_ReapSeam()))
        self.assertEqual(len(seam.calls), 1)


class StopFailureTests(RecordTestCase):
    """Named refusals for the stop path; nothing is ever substituted."""

    def test_stop_with_no_active_recording_is_refused_by_name(self) -> None:
        with self.assertRaises(record.RecordRefusal) as caught:
            record.stop(alive=_alive, reap=_ReapSeam())
        self.assertIn("no recording is active", caught.exception.reason)

    def test_a_double_start_is_refused_by_name(self) -> None:
        seam = _RecorderSeam()
        record.start(spawn=seam, alive=_alive)
        with self.assertRaises(record.RecordRefusal) as caught:
            record.start(spawn=seam, alive=_alive)
        self.assertIn("already in progress", caught.exception.reason)
        self.assertEqual(len(seam.calls), 1, "a refused start spawns nothing")

    def test_stop_terminates_the_live_recorder_and_returns_the_wav(self) -> None:
        seam = _RecorderSeam()
        reap = _ReapSeam()
        record.start(spawn=seam, alive=_alive)
        recorded = self.read_recording()["wav_path"]
        wav = record.stop(alive=_alive, reap=reap)
        self.assertEqual(reap.pids, [_FakeRecorder.pid])
        self.assertEqual(str(wav), recorded)
        self.assertFalse(self.recording_file().exists())


class AbandonedAndCeilingTests(RecordTestCase):
    """A recording that never reaches an explicit stop is deleted, never sent."""

    def test_an_abandoned_recording_is_cleaned_up_and_never_transcribed(
        self,
    ) -> None:
        wav_path = self.write_stale_recording()
        seam = _RecorderSeam()
        self.assertIsNone(record.toggle(spawn=seam, alive=_dead, reap=_ReapSeam()))
        self.assertFalse(wav_path.exists(), "the abandoned wav is deleted")
        # The same press starts a fresh recording; nothing was transcribed.
        self.assertEqual(len(seam.calls), 1)
        state = self.read_recording()
        self.assertNotEqual(state["wav_path"], str(wav_path))

    def test_ceiling_expiry_deletes_the_wav_and_issues_no_request(self) -> None:
        wav_path = self.write_stale_recording()
        with self.assertRaises(record.RecordRefusal) as caught:
            record.stop(alive=_dead, reap=_ReapSeam())
        self.assertIn("nothing was transcribed", caught.exception.reason)
        self.assertFalse(wav_path.exists(), "the ceiling-expired wav is deleted")
        self.assertFalse(self.recording_file().exists())

    def test_the_capture_executable_refusing_to_start_is_refused_by_name(
        self,
    ) -> None:
        def missing(_command, **_kwargs):
            raise FileNotFoundError("/example/capture")

        with self.assertRaises(record.RecordRefusal) as caught:
            record.start(spawn=missing, alive=_alive)
        self.assertIn("capture executable", caught.exception.reason)
        self.assertFalse(self.recording_file().exists())


class LiveStateTests(RecordTestCase):
    """The liveness query the pane restores on start (F01)."""

    def test_no_state_reads_as_inactive(self) -> None:
        self.assertFalse(record.is_active(alive=_alive))

    def test_a_live_recorder_reads_as_active(self) -> None:
        record.start(spawn=_RecorderSeam(), alive=_alive)
        self.assertTrue(record.is_active(alive=_alive))

    def test_a_dead_recorder_reads_as_inactive(self) -> None:
        self.write_stale_recording()
        self.assertFalse(record.is_active(alive=_dead))

    def test_a_corrupt_state_reads_as_inactive(self) -> None:
        self.recording_file().write_text("{not json", encoding="utf-8")
        self.assertFalse(record.is_active(alive=_alive))


class PaneExitAbandonTests(RecordTestCase):
    """Pane-exit abandonment (F01): end the capture, delete it, transcribe nothing."""

    def test_abandon_with_no_active_recording_is_a_noop(self) -> None:
        reap = _ReapSeam()
        self.assertFalse(record.abandon(alive=_alive, reap=reap))
        self.assertEqual(reap.pids, [])

    def test_abandon_terminates_a_live_recorder_and_deletes_the_capture(self) -> None:
        reap = _ReapSeam()
        record.start(spawn=_RecorderSeam(), alive=_alive)
        wav_path = Path(self.read_recording()["wav_path"])
        wav_path.write_bytes(_AUDIO_BYTES)  # the recorder wrote its wav
        self.assertTrue(record.abandon(alive=_alive, reap=reap))
        self.assertEqual(reap.pids, [_FakeRecorder.pid])
        self.assertFalse(wav_path.exists(), "the abandoned wav is deleted")
        self.assertFalse(self.recording_file().exists())

    def test_abandon_of_a_dead_recorder_cleans_up_without_reaping(self) -> None:
        wav_path = self.write_stale_recording()
        reap = _ReapSeam()
        self.assertTrue(record.abandon(alive=_dead, reap=reap))
        self.assertEqual(reap.pids, [])
        self.assertFalse(wav_path.exists())
        self.assertFalse(self.recording_file().exists())

    def test_a_toggle_after_abandon_starts_a_fresh_recording(self) -> None:
        record.start(spawn=_RecorderSeam(), alive=_alive)
        record.abandon(alive=_alive, reap=_ReapSeam())
        seam = _RecorderSeam()
        self.assertIsNone(record.toggle(spawn=seam, alive=_alive, reap=_ReapSeam()))
        self.assertEqual(len(seam.calls), 1)
        self.assertEqual(self.read_recording()["pid"], _FakeRecorder.pid)


class RetentionTests(RecordTestCase):
    """Audio is gone after a successful run and after a deliberately failed one.

    Named ``retention`` for #31's ``-k retention`` gate. The successful and
    failed runs compose the toggle with the transcription entry point exactly
    as the Voice pane sequences them; the abandoned and ceiling-expired runs
    cover audio that never reached transcription at all (D5).
    """

    def test_retention_audio_is_gone_after_a_successful_run(self) -> None:
        seam = _RecorderSeam()
        reap = _ReapSeam()
        record.toggle(spawn=seam, alive=_alive, reap=reap)
        wav = record.toggle(spawn=seam, alive=_alive, reap=reap)
        wav.write_bytes(_AUDIO_BYTES)  # the recorder wrote its wav
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _transcription_ok()])
        result = transcribe.transcribe(wav, open_url=opener)
        self.assertEqual(result.transcript, "example transcript")
        self.assertFalse(wav.exists(), "audio is deleted after success")

    def test_retention_audio_is_gone_after_a_deliberately_failed_run(self) -> None:
        seam = _RecorderSeam()
        reap = _ReapSeam()
        record.toggle(spawn=seam, alive=_alive, reap=reap)
        wav = record.toggle(spawn=seam, alive=_alive, reap=reap)
        wav.write_bytes(_AUDIO_BYTES)
        opener = _OpenerSeam([(200, _TOKEN_PAGE), (500, b"relay failure")])
        with self.assertRaises(providers.ProviderRefusal):
            transcribe.transcribe(wav, open_url=opener)
        self.assertFalse(wav.exists(), "audio is deleted after failure")

    def test_retention_an_abandoned_recording_deletes_its_audio(self) -> None:
        wav_path = self.write_stale_recording()
        seam = _RecorderSeam()
        record.toggle(spawn=seam, alive=_dead, reap=_ReapSeam())
        self.assertFalse(wav_path.exists())

    def test_retention_ceiling_expiry_deletes_its_audio(self) -> None:
        wav_path = self.write_stale_recording()
        with self.assertRaises(record.RecordRefusal):
            record.stop(alive=_dead, reap=_ReapSeam())
        self.assertFalse(wav_path.exists())


class Base64RoundTripSanityTests(RecordTestCase):
    """The recorded bytes survive into the transcription request verbatim."""

    def test_the_wav_bytes_reach_the_request_as_a_data_url(self) -> None:
        wav = self.state_dir / "capture-roundtrip.wav"
        wav.write_bytes(_AUDIO_BYTES)
        opener = _OpenerSeam([(200, _TOKEN_PAGE), _transcription_ok()])
        transcribe.transcribe(wav, open_url=opener)
        body = json.loads(opener.requests[1].data.decode("utf-8"))
        expected = "data:audio/wav;base64," + base64.b64encode(_AUDIO_BYTES).decode(
            "ascii"
        )
        self.assertEqual(body["data_url"], expected)


if __name__ == "__main__":
    unittest.main()
