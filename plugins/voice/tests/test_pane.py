"""Tests for the Voice pane controls (R4, R8, R9, R11, R13; KTD16).

Every seam is injected per KTD12: playback stop, the capture toggle,
transcription, and the delivery seams are fakes, so no test touches the
network, spawns a platform binary, or needs ``deliver.py`` to exist. The
delivery seam is exercised through a fake precisely because U5 and U6
dispatch concurrently (KTD16): ``pane`` must not import ``deliver`` at
module load.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import binding  # noqa: E402
import pane  # noqa: E402
import providers  # noqa: E402
import record  # noqa: E402
import transcribe  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

AGENT_NAME = "work-agent"
SESSION_ID = "34ed4762-0000-4000-8000-000000000000"
PANE_ID = "w1:p1"


def _bound_report() -> binding.BindingReport:
    return binding.BindingReport(
        binding=binding.Binding(
            agent=AGENT_NAME,
            session_id=SESSION_ID,
            pane_id=PANE_ID,
            bound_at="2026-08-25T00:00:00+00:00",
        ),
        status=binding.STATUS_BOUND,
    )


class _Seam:
    """One recorded seam call site; optionally raises or returns a value."""

    def __init__(self, name, order=None, result=None, error=None):
        self.name = name
        self.calls: list[tuple[tuple, dict]] = []
        self._order = order
        self._result = result
        self._error = error

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._order is not None:
            self._order.append(self.name)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeRecorder:
    """The recorder a spawn seam returns instead of a platform binary."""

    pid = 4242


class _SpawnSeam:
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


def _alive(pid: int) -> bool:
    return True


class PaneTestBase(unittest.TestCase):
    """Shared fixture: a temp state dir and inert settings."""

    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        env = mock.patch.dict(os.environ, {"VOICE_STATE_DIR": state.name})
        env.start()
        self.addCleanup(env.stop)
        self.order: list[str] = []
        self.stop_playback = _Seam("stop_playback", self.order)
        self.toggle = _Seam("toggle", self.order, result=None)
        self.transcription = transcribe.Transcription(
            transcript="please fix the build", provider="xai"
        )
        self.transcribe_path = _Seam("transcribe", self.order, result=self.transcription)
        self.deliver = _Seam("deliver", self.order)
        self.use_refused = _Seam("use_refused", self.order)
        self.discard_refused = _Seam("discard_refused", self.order)
        self.read_binding_report = _Seam(
            "read_binding_report", result=_bound_report()
        )
        # Neither carries the shared order list: the restore seam fires at
        # construction and the abandon seam at quit, and the key-order
        # assertions below count keypress sequences only.
        self.abandon_recording = _Seam("abandon_recording", result=False)
        self.read_recording_active = _Seam("read_recording_active", result=False)

    def make_pane(self) -> pane.VoicePane:
        return pane.VoicePane(
            stop_playback=self.stop_playback,
            toggle=self.toggle,
            transcribe_path=self.transcribe_path,
            deliver=self.deliver,
            use_refused=self.use_refused,
            discard_refused=self.discard_refused,
            read_binding_report=self.read_binding_report,
            abandon_recording=self.abandon_recording,
            read_recording_active=self.read_recording_active,
        )


class DisplayTests(PaneTestBase):
    def test_bound_identity_and_recording_state_are_both_displayed(self) -> None:
        session = self.make_pane()
        lines = session.status_lines()
        joined = "\n".join(lines)
        self.assertIn(AGENT_NAME, joined)
        self.assertIn(SESSION_ID, joined)
        self.assertIn("recording: idle", joined)

    def test_recording_indicator_literal_present_while_recording(self) -> None:
        session = self.make_pane()
        session.recording = True
        joined = "\n".join(session.status_lines())
        self.assertIn(pane.RECORDING_INDICATOR, joined)
        self.assertIn("*** RECORDING ***", joined)

    def test_recording_indicator_absent_when_idle(self) -> None:
        session = self.make_pane()
        joined = "\n".join(session.status_lines())
        self.assertNotIn("RECORDING", joined)

    def test_absent_binding_is_reported_by_name(self) -> None:
        self.read_binding_report._result = binding.BindingReport(
            binding=None, status=binding.STATUS_ABSENT
        )
        joined = "\n".join(self.make_pane().status_lines())
        self.assertIn("not bound", joined)

    def test_corrupt_binding_is_reported_by_name(self) -> None:
        self.read_binding_report._result = binding.BindingReport(
            binding=None, status=binding.STATUS_CORRUPT
        )
        joined = "\n".join(self.make_pane().status_lines())
        self.assertIn("unreadable", joined)

    def test_a_leftover_live_recorder_is_restored_as_recording_on_start(self) -> None:
        # F01: a recorder left running by an earlier pane (or by the CLI
        # toggle) must be recognised, never mistaken for idle.
        self.read_recording_active._result = True
        session = self.make_pane()
        self.assertTrue(session.recording)
        joined = "\n".join(session.status_lines())
        self.assertIn(pane.RECORDING_INDICATOR, joined)
        self.assertNotIn("recording: idle", joined)


class KeyTests(PaneTestBase):
    def test_s_stops_playback_immediately_on_keypress(self) -> None:
        session = self.make_pane()
        messages = session.handle_key("s")
        self.assertEqual(len(self.stop_playback.calls), 1)
        self.assertEqual(messages, ["playback stopped"])

    def test_t_while_idle_stops_playback_before_starting_recording(self) -> None:
        session = self.make_pane()
        messages = session.handle_key("t")
        self.assertEqual(self.order, ["stop_playback", "toggle"])
        self.assertTrue(session.recording)
        self.assertTrue(any("recording started" in message for message in messages))

    def test_t_while_recording_transcribes_and_delivers_the_transcript(self) -> None:
        session = self.make_pane()
        session.recording = True
        wav_path = Path(tempfile.gettempdir()) / "capture-test.wav"
        self.toggle._result = wav_path
        messages = session.handle_key("t")
        self.assertEqual(self.order, ["stop_playback", "toggle", "transcribe", "deliver"])
        self.assertEqual(self.transcribe_path.calls[0][0], (wav_path,))
        self.assertEqual(
            self.deliver.calls[0][0], (self.transcription.transcript,)
        )
        self.assertFalse(session.recording)
        self.assertEqual(messages, ["transcript delivered unsubmitted"])

    def test_t_while_recording_restarts_when_the_recorder_died(self) -> None:
        session = self.make_pane()
        session.recording = True
        self.toggle._result = None  # record.toggle cleaned up and restarted
        session.handle_key("t")
        self.assertTrue(session.recording)
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)

    def test_t_on_a_restored_recording_is_an_explicit_stop_and_delivers(self) -> None:
        # F01: once the leftover recorder is recognised, the operator's press
        # is an informed explicit stop — the capture is transcribed and
        # delivered, exactly as a press on a recording the pane started.
        self.read_recording_active._result = True
        session = self.make_pane()
        wav_path = Path(tempfile.gettempdir()) / "capture-leftover.wav"
        self.toggle._result = wav_path
        session.handle_key("t")
        self.assertEqual(self.order, ["stop_playback", "toggle", "transcribe", "deliver"])
        self.assertEqual(self.transcribe_path.calls[0][0], (wav_path,))
        self.assertEqual(self.deliver.calls[0][0], (self.transcription.transcript,))
        self.assertFalse(session.recording)

    def test_u_and_d_call_the_use_and_discard_seams(self) -> None:
        session = self.make_pane()
        self.assertEqual(session.handle_key("u"), ["refused transcript delivered"])
        self.assertEqual(session.handle_key("d"), ["refused transcript discarded"])
        self.assertEqual(len(self.use_refused.calls), 1)
        self.assertEqual(len(self.discard_refused.calls), 1)

    def test_unknown_keys_are_ignored(self) -> None:
        session = self.make_pane()
        self.assertEqual(session.handle_key("x"), [])
        self.assertEqual(session.handle_key("\r"), [])
        self.assertEqual(self.order, [])

    def test_capital_keys_apply_too(self) -> None:
        session = self.make_pane()
        session.handle_key("S")
        self.assertEqual(len(self.stop_playback.calls), 1)

    def test_a_toggle_refusal_surfaces_as_a_pane_message(self) -> None:
        session = self.make_pane()
        self.toggle._error = providers.ProviderRefusal(
            providers.VOICE_FORGE, "the playback binary cannot start"
        )
        messages = session.handle_key("t")
        self.assertTrue(any("voice: " in message for message in messages))
        self.assertFalse(session.recording)
        # The pane stays usable after a refusal.
        self.assertEqual(session.handle_key("s"), ["playback stopped"])

    def test_a_delivery_refusal_surfaces_without_crashing(self) -> None:
        session = self.make_pane()
        session.recording = True
        self.toggle._result = Path(tempfile.gettempdir()) / "capture-test.wav"
        self.deliver._error = providers.ProviderRefusal(
            providers.HERMES_XAI, "the bound agent is unresolvable"
        )
        messages = session.handle_key("t")
        self.assertTrue(any("voice: " in message for message in messages))
        self.assertFalse(session.recording)


class RunLoopTests(PaneTestBase):
    def _run(self, keys: list[str]) -> tuple[int, list[str]]:
        written: list[str] = []
        stream = iter(keys + [""])
        exit_code = pane.run(
            pane=self.make_pane(),
            read_key=lambda: next(stream),
            write_line=written.append,
        )
        return exit_code, written

    def test_run_displays_identity_help_and_quits_on_q(self) -> None:
        exit_code, written = self._run(["q"])
        self.assertEqual(exit_code, 0)
        joined = "\n".join(written)
        self.assertIn(AGENT_NAME, joined)
        self.assertIn(SESSION_ID, joined)
        self.assertIn("t toggle recording", joined)
        self.assertIn("[voice] pane stopped", joined)

    def test_run_processes_keys_without_enter(self) -> None:
        exit_code, written = self._run(["t", "s", "t", "q"])
        self.assertEqual(exit_code, 0)
        # One start press and one stop press reached the toggle seam; the
        # dedicated stop key and both toggle presses each stop playback
        # first (R9), and the quit cleanup stops playback once more (F01),
        # so four stop calls in total.
        self.assertEqual(len(self.toggle.calls), 2)
        self.assertEqual(len(self.stop_playback.calls), 4)
        joined = "\n".join(written)
        self.assertIn("*** RECORDING ***", joined)

    def test_run_reports_end_of_input_as_a_clean_exit(self) -> None:
        exit_code, _written = self._run([])
        self.assertEqual(exit_code, 0)

    def test_q_after_t_leaves_no_live_recorder_and_transcribes_nothing(
        self,
    ) -> None:
        # F01: quitting after a start press abandons the capture — nothing
        # keeps recording after the pane is gone, and nothing that was
        # captured is transcribed or delivered.
        self.abandon_recording._result = True  # a recording runs at the quit
        exit_code, written = self._run(["t", "q"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(self.abandon_recording.calls), 1)
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)
        joined = "\n".join(written)
        self.assertIn("recording abandoned", joined)
        self.assertIn("[voice] pane stopped", joined)

    def test_q_while_recording_is_active_abandons_without_delivering(
        self,
    ) -> None:
        # F01's run-loop gap: the pane starts with a restored live recorder
        # and the operator quits without pressing the toggle.
        self.read_recording_active._result = True
        self.abandon_recording._result = True  # the restored recorder is live
        exit_code, written = self._run(["q"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(self.abandon_recording.calls), 1)
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)
        self.assertEqual(len(self.toggle.calls), 0)
        joined = "\n".join(written)
        self.assertIn("recording abandoned", joined)

    def test_end_of_input_while_recording_also_abandons(self) -> None:
        self.abandon_recording._result = True  # a recording runs at the quit
        exit_code, _written = self._run(["t"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(self.abandon_recording.calls), 1)
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)

    def test_keyboard_interrupt_while_recording_also_abandons(self) -> None:
        self.abandon_recording._result = True  # a recording runs at the quit
        written: list[str] = []
        keys = iter(["t"])

        def read_key() -> str:
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt() from None

        exit_code = pane.run(
            pane=self.make_pane(),
            read_key=read_key,
            write_line=written.append,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(self.abandon_recording.calls), 1)
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)
        self.assertIn("[voice] pane stopped", "\n".join(written))

    def test_t_then_q_terminates_a_real_recorder_and_clears_the_state(
        self,
    ) -> None:
        # F01 end-to-end through the real capture module (KTD12 seams for
        # the spawn and reap, so no platform binary runs): after the quit
        # the recorder pid was reaped and no recording state is left for a
        # later pane to mistake for idle.
        spawn = _SpawnSeam()
        reap = _ReapSeam()
        session = pane.VoicePane(
            stop_playback=self.stop_playback,
            toggle=lambda: record.toggle(spawn=spawn, alive=_alive, reap=reap),
            transcribe_path=self.transcribe_path,
            deliver=self.deliver,
            use_refused=self.use_refused,
            discard_refused=self.discard_refused,
            read_binding_report=self.read_binding_report,
            abandon_recording=lambda: record.abandon(alive=_alive, reap=reap),
            read_recording_active=lambda: record.is_active(alive=_alive),
        )
        stream = iter(["t", "q", ""])
        exit_code = pane.run(pane=session, read_key=lambda: next(stream))
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(spawn.calls), 1)
        self.assertEqual(reap.pids, [_FakeRecorder.pid])
        self.assertEqual(len(self.transcribe_path.calls), 0)
        self.assertEqual(len(self.deliver.calls), 0)
        self.assertFalse(
            (Path(os.environ["VOICE_STATE_DIR"]) / "recording.json").exists(),
            "the quit left no recording state behind",
        )


class LazyDeliveryImportTests(unittest.TestCase):
    def test_pane_does_not_import_deliver_at_module_load(self) -> None:
        # Run in a fresh interpreter so a sibling test's import of deliver
        # (U5) cannot mask a module-level import here.
        script = (
            "import sys\n"
            f"sys.path.insert(0, {str(SCRIPTS_DIR)!r})\n"
            "import pane\n"
            "assert 'deliver' not in sys.modules\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"importing pane pulled in deliver at module load:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
