"""Tests for the Claude ``Stop`` hook and its descriptor (R1, R3; KTD1, KTD2, KTD12).

The spawn seam is injected at the Popen level through U1's real
``process.spawn_detached``, so the suite asserts the detached-child
contract (argv, closed stdin, new session, no wait) against a fake rather
than a wall clock or a platform binary. U2 never imports or executes
``speak.py``: the hook hands the text off by argv and file.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PACKAGE / "scripts"))
sys.path.insert(0, str(_PACKAGE / "com.infiquetra.claude" / "hooks"))

import binding  # noqa: E402
import process  # noqa: E402
import stop_hook  # noqa: E402

AGENT = "example-agent"
BOUND_SESSION = "example-session-bound"
OTHER_SESSION = "example-session-other"
PANE_ID = "example-pane-one"
BOUND_AT = "2026-08-25T00:00:00+00:00"
RESPONSE_TEXT = "Example response text for the spoken loop."


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
        self.state_dir = Path(temporary.name)
        environment = patch.dict(
            os.environ, {"VOICE_STATE_DIR": str(self.state_dir)}
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.seam = _SpawnSeam()
        self.real_spawn_detached = process.spawn_detached

    def bind(self, session_id: str = BOUND_SESSION) -> None:
        binding.write_binding(AGENT, session_id, PANE_ID, bound_at=BOUND_AT)

    def spawn_through_seam(self, argv):
        return self.real_spawn_detached(argv, spawn=self.seam)

    def run_hook(self, stdin_text: str) -> int:
        stream = io.StringIO(stdin_text)
        with (
            patch.object(sys, "stdin", stream),
            patch.object(
                process, "spawn_detached", side_effect=self.spawn_through_seam
            ),
        ):
            return stop_hook.main()

    def run_hook_payload(self, **fields) -> int:
        payload = {
            "session_id": BOUND_SESSION,
            "hook_event_name": "Stop",
            "transcript_path": "/nonexistent/example-transcript.jsonl",
            "last_assistant_message": RESPONSE_TEXT,
        }
        payload.update(fields)
        return self.run_hook(json.dumps(payload))

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
        for (command, _kwargs), path in zip(self.seam.calls, files):
            self.assertEqual(command[2], str(path))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"text": RESPONSE_TEXT},
            )

    def test_the_spawn_is_recorded_whether_or_not_speak_has_landed(self) -> None:
        # U3's speak.py lands concurrently; the hook spawns by argv either
        # way and never checks existence, so the seam records the call.
        self.bind()
        self.assertEqual(self.run_hook_payload(), 0)
        self.assertEqual(len(self.seam.calls), 1)


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


class DescriptorAndLayoutTests(StopHookTestCase):
    """The client extension matches the repository's extension convention."""

    def test_hooks_json_declares_the_stop_entry(self) -> None:
        descriptor_path = (
            _PACKAGE / "com.infiquetra.claude" / "hooks" / "hooks.json"
        )
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        self.assertIn("Stop", descriptor["hooks"])
        entries = [
            entry
            for group in descriptor["hooks"]["Stop"]
            for entry in group["hooks"]
        ]
        commands = [
            entry["command"] for entry in entries if entry.get("type") == "command"
        ]
        self.assertIn(
            'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py"', commands
        )
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
