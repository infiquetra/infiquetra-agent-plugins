"""Tests for the Claude ``Stop`` hook and its descriptor (R1, R3, R22, R23, R122; KTD1, KTD2, KTD6, KTD11, KTD12).

The spawn seam is injected at the Popen level through U1's real
``process.spawn_detached``, so the suite asserts the detached-child
contract (argv, closed stdin, new session, no wait) against a fake rather
than a wall clock or a platform binary. U2 never imports or executes
``speak.py``: the hook hands the text off by argv and file.

Wire-bound tests assert KTD6 bridged reconciliation (authored vs fallback)
and local speech suppression against a local BridgeStub and Herdr fixture.
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PACKAGE / "scripts"))
sys.path.insert(0, str(_PACKAGE / "com.infiquetra.claude" / "hooks"))
sys.path.insert(0, str(_PACKAGE / "tests"))

import binding  # noqa: E402
from bridge_stub import DEFAULT_STUB_TOKEN, BridgeStub  # noqa: E402
import process  # noqa: E402
import stop_hook  # noqa: E402
import turn_record  # noqa: E402

AGENT = "example-agent"
BOUND_SESSION = "example-session-bound"
OTHER_SESSION = "example-session-other"
PANE_ID = "example-pane-one"
TERMINAL_ID = "example-term-one"
BOUND_AT = "2026-08-25T00:00:00+00:00"
RESPONSE_TEXT = "Example response text for the spoken loop."

VALID_UUID_1 = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
VALID_UUID_2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"


class _FakeChild:
    pid = 4242

    def __init__(self) -> None:
        self.waited = False

    def wait(self, *args, **kwargs) -> int:
        self.waited = True
        return 0

    def poll(self):
        self.waited = True
        return None


class _SpawnSeam:
    """Records the Popen-level call instead of starting a real child."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.children: list[_FakeChild] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        child = _FakeChild()
        self.children.append(child)
        return child


class StopHookTestCase(unittest.TestCase):
    """Common fixture: fresh state dir, bound-or-not binding, spawn seam."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.home_dir = self.root / "home"
        self.home_dir.mkdir(parents=True, exist_ok=True)

        environment = patch.dict(
            os.environ,
            {
                "VOICE_STATE_DIR": str(self.state_dir),
                "HOME": str(self.home_dir),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.seam = _SpawnSeam()
        self.real_spawn_detached = process.spawn_detached

    def bind(self, session_id: str = BOUND_SESSION) -> None:
        binding.write_binding(AGENT, session_id, PANE_ID, bound_at=BOUND_AT)

    def spawn_through_seam(self, argv):
        return self.real_spawn_detached(argv, spawn=self.seam)

    def run_hook(self, stdin_text: str, spawn_side_effect=None) -> int:
        side_effect = (
            self.spawn_through_seam if spawn_side_effect is None else spawn_side_effect
        )
        stream = io.StringIO(stdin_text)
        with (
            patch.object(sys, "stdin", stream),
            patch.object(process, "spawn_detached", side_effect=side_effect),
        ):
            return stop_hook.main()

    def run_hook_payload(self, spawn_side_effect=None, **fields) -> int:
        payload = {
            "session_id": BOUND_SESSION,
            "hook_event_name": "Stop",
            "transcript_path": "/nonexistent/example-transcript.jsonl",
            "last_assistant_message": RESPONSE_TEXT,
        }
        payload.update(fields)
        return self.run_hook(json.dumps(payload), spawn_side_effect=spawn_side_effect)

    def speak_files(self) -> list[Path]:
        return sorted(self.state_dir.glob("speak-*.json"))


class SingleSpeakerGuardTests(StopHookTestCase):
    """Only the bound session speaks; every other session is silence (R3)."""

    def test_an_unbound_session_returns_without_spawning(self) -> None:
        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_a_mismatched_session_returns_without_spawning(self) -> None:
        self.bind(session_id=OTHER_SESSION)
        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_a_corrupt_binding_reads_unbound_on_the_hot_path(self) -> None:
        (self.state_dir / binding.BINDING_FILENAME).write_text(
            "not json {", encoding="utf-8"
        )
        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_an_absent_state_directory_reads_unbound(self) -> None:
        missing = self.state_dir / "does-not-exist"
        with patch.dict(os.environ, {"VOICE_STATE_DIR": str(missing)}):
            result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])

    def test_an_empty_response_speaks_nothing(self) -> None:
        self.bind()
        result = self.run_hook_payload(last_assistant_message="")
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])


class DetachedSpawnTests(StopHookTestCase):
    """A bound session writes one unique payload and spawns one detached child."""

    def test_a_bound_session_writes_one_payload_and_spawns_once(self) -> None:
        self.bind()
        result = self.run_hook_payload()
        self.assertEqual(result, 0)

        files = self.speak_files()
        self.assertEqual(len(files), 1)
        payload_file = files[0]
        self.assertEqual(
            json.loads(payload_file.read_text(encoding="utf-8")),
            {"text": RESPONSE_TEXT},
        )

        self.assertEqual(len(self.seam.calls), 1)
        (command, kwargs), = self.seam.calls
        self.assertEqual(
            command, [sys.executable, str(stop_hook.SPEAK_SCRIPT), str(payload_file)]
        )
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        for child in self.seam.children:
            self.assertFalse(
                child.waited, "the hook never waits on the detached child"
            )

    def test_the_speak_script_resolves_to_the_portable_package_root(self) -> None:
        self.assertEqual(
            stop_hook.SPEAK_SCRIPT,
            Path(stop_hook.__file__).resolve().parents[2] / "scripts" / "speak.py",
        )

    def test_each_bound_stop_gets_a_fresh_unique_payload(self) -> None:
        self.bind()
        self.assertEqual(self.run_hook_payload(), 0)
        self.assertEqual(self.run_hook_payload(), 0)
        files = self.speak_files()
        self.assertEqual(len(files), 2)
        self.assertEqual(len(self.seam.calls), 2)
        spawned_paths = sorted(command[2] for command, _kwargs in self.seam.calls)
        self.assertEqual(spawned_paths, [str(path) for path in files])
        for path in files:
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"text": RESPONSE_TEXT},
            )

    def test_the_spawn_is_recorded_whether_or_not_speak_has_landed(self) -> None:
        self.bind()
        self.assertEqual(self.run_hook_payload(), 0)
        self.assertEqual(len(self.seam.calls), 1)


class SpawnFailureCleanupTests(StopHookTestCase):
    """A failed spawn removes the payload it wrote and still exits 0 (F03)."""

    def setUp(self) -> None:
        super().setUp()
        self.attempts: list[list[str]] = []

    def failing_spawn(self, error: Exception):
        attempts = self.attempts

        def refuse(command, **kwargs):
            attempts.append(command)
            raise error

        def spawn_through_refusal(argv):
            return self.real_spawn_detached(argv, spawn=refuse)

        return spawn_through_refusal

    def test_a_failed_spawn_removes_the_payload_and_exits_zero(self) -> None:
        self.bind()
        result = self.run_hook_payload(
            spawn_side_effect=self.failing_spawn(OSError("spawn refused"))
        )
        self.assertEqual(result, 0)
        self.assertEqual(
            len(self.attempts), 1, "the spawn was attempted exactly once"
        )
        attempted_path = Path(self.attempts[0][2])
        self.assertTrue(attempted_path.name.startswith("speak-"))
        self.assertFalse(
            attempted_path.exists(),
            "a failed spawn must not leave its payload file behind",
        )
        self.assertEqual(self.speak_files(), [])

    def test_a_failed_spawn_still_gets_a_unique_payload_name(self) -> None:
        self.bind()
        for _ in range(2):
            result = self.run_hook_payload(
                spawn_side_effect=self.failing_spawn(OSError("spawn refused"))
            )
            self.assertEqual(result, 0)
        attempted_paths = [command[2] for command in self.attempts]
        self.assertEqual(len(attempted_paths), 2)
        self.assertEqual(len(set(attempted_paths)), 2)
        self.assertEqual(self.speak_files(), [])

    def test_a_cleanup_failure_still_exits_zero(self) -> None:
        self.bind()
        with patch.object(Path, "unlink", side_effect=OSError("disk gone")):
            result = self.run_hook_payload(
                spawn_side_effect=self.failing_spawn(OSError("spawn refused"))
            )
        self.assertEqual(result, 0)


class NeverBreakTheTurnTests(StopHookTestCase):
    """Every malformed input exits 0 silently; a hook never breaks a turn."""

    def test_invalid_json_exits_zero_without_spawning(self) -> None:
        self.bind()
        self.assertEqual(self.run_hook("this is not json {"), 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_empty_stdin_exits_zero_without_spawning(self) -> None:
        self.bind()
        self.assertEqual(self.run_hook(""), 0)
        self.assertEqual(self.seam.calls, [])

    def test_a_non_object_payload_exits_zero_without_spawning(self) -> None:
        self.bind()
        self.assertEqual(self.run_hook(json.dumps([BOUND_SESSION])), 0)
        self.assertEqual(self.seam.calls, [])

    def test_a_missing_session_id_exits_zero_without_spawning(self) -> None:
        self.bind()
        result = self.run_hook(json.dumps({"last_assistant_message": RESPONSE_TEXT}))
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])

    def test_a_missing_message_exits_zero_without_spawning(self) -> None:
        self.bind()
        result = self.run_hook(json.dumps({"session_id": BOUND_SESSION}))
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_an_unusable_state_dir_setting_exits_zero_without_spawning(self) -> None:
        self.bind()
        with patch.dict(os.environ, {"VOICE_STATE_DIR": ""}):
            result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])


class WireBoundReconciliationTests(StopHookTestCase):
    """Tests for the KTD6 bridged reconciliation and local speech suppression branch."""

    def setUp(self) -> None:
        super().setUp()
        # Set up BridgeStub
        self.stub = BridgeStub()
        self.stub.start()
        self.addCleanup(self.stub.stop)

        # Write discovery bridge.json
        self.bridge_dir = self.home_dir / "Library" / "Application Support" / "Auralis"
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_file = self.bridge_dir / "bridge.json"
        bridge_payload = {
            "schema": 1,
            "host": "127.0.0.1",
            "port": self.stub.port,
            "token": DEFAULT_STUB_TOKEN,
        }
        self.bridge_file.write_text(json.dumps(bridge_payload), encoding="utf-8")
        os.chmod(self.bridge_file, stat.S_IRUSR | stat.S_IWUSR)

        # Mock Herdr script
        self.herdr_path = self.root / "fake_herdr"
        herdr_envelope = {
            "type": "agent_list",
            "agents": [
                {
                    "pane_id": PANE_ID,
                    "terminal_id": TERMINAL_ID,
                    "agent_session": {"value": BOUND_SESSION},
                }
            ],
        }
        mock_herdr_code = (
            f"#!/usr/bin/env python3\n"
            f"import sys\n"
            f"sys.stdout.write({json.dumps(json.dumps(herdr_envelope))} + '\\n')\n"
        )
        self.herdr_path.write_text(mock_herdr_code, encoding="utf-8")
        os.chmod(self.herdr_path, 0o755)

        self.env_patcher_bridge = patch.dict(
            os.environ,
            {
                "HERDR_PANE_ID": PANE_ID,
                "HERDR_BIN_PATH": str(self.herdr_path),
            },
        )
        self.env_patcher_bridge.start()
        self.addCleanup(self.env_patcher_bridge.stop)

        self.identity_dict = {
            "agent_session_id": BOUND_SESSION,
            "pane_id": PANE_ID,
            "terminal_id": TERMINAL_ID,
        }

    def test_wire_bound_with_accepted_rendering_settles_authored_and_suppresses_speech(
        self,
    ) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="authored_accepted")

        # Initialize turn record with an accepted submission
        turn_record.init_turn(
            session_id=BOUND_SESSION,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )
        turn_record.record_submission(
            session_id=BOUND_SESSION,
            text="Spoken rendering",
            disposition="accepted",
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        # Also have local legacy binding present
        self.bind(session_id=BOUND_SESSION)

        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        # Suppresses local speak spawn
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

        # Reconciled outcome is authored
        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.outcome, turn_record.OUTCOME_AUTHORED)  # type: ignore[union-attr]

    def test_wire_bound_without_accepted_rendering_settles_fallback_and_suppresses_speech(
        self,
    ) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # Initialize turn record with a rejected submission (R122 path)
        turn_record.init_turn(
            session_id=BOUND_SESSION,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )
        turn_record.record_submission(
            session_id=BOUND_SESSION,
            text="**Markdown**",
            disposition="rejected_content",
            reason="markdown_formatting",
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        # Also have local legacy binding present
        self.bind(session_id=BOUND_SESSION)

        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        # Suppresses local speak spawn
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

        # Reconciled outcome is fallback
        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.outcome, turn_record.OUTCOME_FALLBACK)  # type: ignore[union-attr]

    def test_wire_bound_with_no_turn_record_still_suppresses_speech(self) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.bind(session_id=BOUND_SESSION)

        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        self.assertEqual(self.seam.calls, [])
        self.assertEqual(self.speak_files(), [])

    def test_bridge_unavailable_falls_back_to_legacy_speak_path(self) -> None:
        self.stub.stop()
        self.bind(session_id=BOUND_SESSION)

        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        # Spawns through legacy path
        self.assertEqual(len(self.seam.calls), 1)
        self.assertEqual(len(self.speak_files()), 1)

    def test_bridge_bound_to_different_session_falls_back_to_legacy_speak_path(
        self,
    ) -> None:
        other_identity = {
            "agent_session_id": "session-other",
            "pane_id": "pane-other",
            "terminal_id": "term-other",
        }
        self.stub.set_binding(VALID_UUID_1, other_identity)
        self.bind(session_id=BOUND_SESSION)

        result = self.run_hook_payload()
        self.assertEqual(result, 0)
        # Spawns through legacy path
        self.assertEqual(len(self.seam.calls), 1)
        self.assertEqual(len(self.speak_files()), 1)

    def test_turn_record_busy_on_wire_bound_still_suppresses_speech(self) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.bind(session_id=BOUND_SESSION)

        with patch.object(
            turn_record,
            "settle_outcome",
            side_effect=turn_record.TurnRecordBusy("turn_record_busy"),
        ):
            result = self.run_hook_payload()
            self.assertEqual(result, 0)
            self.assertEqual(self.seam.calls, [])
            self.assertEqual(self.speak_files(), [])


class DescriptorAndLayoutTests(StopHookTestCase):
    """The client extension matches the repository's extension convention."""

    def test_hooks_json_declares_the_required_entries(self) -> None:
        descriptor_path = (
            _PACKAGE / "com.infiquetra.claude" / "hooks" / "hooks.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))

        for hook_name in ("UserPromptSubmit", "PreToolUse", "Stop"):
            with self.subTest(hook_name=hook_name):
                self.assertIn(hook_name, descriptor["hooks"])
                entries = [
                    entry
                    for group in descriptor["hooks"][hook_name]
                    for entry in group["hooks"]
                ]
                commands = [
                    entry["command"]
                    for entry in entries
                    if entry.get("type") == "command"
                ]
                for command in commands:
                    relative = command.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1].rstrip('"')
                    self.assertTrue((_PACKAGE / relative).is_file())
                for entry in entries:
                    self.assertEqual(entry["timeout"], 5)

    def test_the_client_manifest_exists_with_an_identity(self) -> None:
        manifest_path = _PACKAGE / "com.infiquetra.claude" / "plugin.json"
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("name", "version", "description"):
            with self.subTest(field=field):
                self.assertIsInstance(manifest[field], str)
                self.assertTrue(manifest[field].strip())

    def test_the_invented_adapters_path_does_not_exist(self) -> None:
        self.assertFalse((_PACKAGE / "adapters").exists())


if __name__ == "__main__":
    unittest.main()
