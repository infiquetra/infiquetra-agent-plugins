"""Tests for the Claude UserPromptSubmit hook (U4; R106, R107; KTD3, KTD4, KTD5, KTD11).

Exercises:
- Auralis-originated turn: context injection (origin, expectation, tool pointer, plain text rule),
  identifier pair capture into turn record, and armed one-shot consumption on transmission;
- Un-armed subsequent turn: preferences without brief directive;
- Bound but non-originated turn: explicit negative injection, no policy transmitted, one-shot preserved;
- Unbound / bridge unavailable / identity resolution failure / session mismatch: silent exit 0;
- Turn record busy: no injection, exit 0;
- Malformed inputs: silent exit 0.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "com.infiquetra.claude" / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge_stub import DEFAULT_STUB_TOKEN, BridgeStub  # noqa: E402
import turn_record  # noqa: E402
import user_prompt_submit_hook  # noqa: E402
import voice_policy  # noqa: E402

VALID_UUID_1 = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
VALID_UUID_2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"

AGENT_SESSION_ID = "session-test-prompt-1"
PANE_ID = "pane-test-prompt-1"
TERMINAL_ID = "term-test-prompt-1"


class UserPromptSubmitHookTests(unittest.TestCase):
    """Test suite for user_prompt_submit_hook.py."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

        self.home_dir = self.root / "home"
        self.home_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Set up BridgeStub
        self.stub = BridgeStub()
        self.stub.start()
        self.addCleanup(self.stub.stop)

        # Write discovery bridge.json (mode 0600)
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

        # Write mock Herdr script
        self.herdr_path = self.root / "fake_herdr"
        herdr_envelope = {
            "type": "agent_list",
            "agents": [
                {
                    "pane_id": PANE_ID,
                    "terminal_id": TERMINAL_ID,
                    "agent_session": {"value": AGENT_SESSION_ID},
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

        # Environment patch
        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home_dir),
                "VOICE_STATE_DIR": str(self.state_dir),
                "HERDR_PANE_ID": PANE_ID,
                "HERDR_BIN_PATH": str(self.herdr_path),
            },
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

        # Default identity dictionary matching Herdr fixture
        self.identity_dict = {
            "agent_session_id": AGENT_SESSION_ID,
            "pane_id": PANE_ID,
            "terminal_id": TERMINAL_ID,
        }

    def run_hook(self, stdin_text: str) -> tuple[int, str]:
        """Run user_prompt_submit_hook.main() with injected stdin and captured stdout."""
        stdin_stream = io.StringIO(stdin_text)
        stdout_stream = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", stdin_stream),
            mock.patch.object(sys, "stdout", stdout_stream),
        ):
            code = user_prompt_submit_hook.main()
        return code, stdout_stream.getvalue()

    def test_originated_turn_injects_context_and_captures_identifiers_and_consumes_brief(
        self,
    ) -> None:
        # 1. Stub has binding + open turn
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # 2. Write policy with preferences and armed brief_next_turn
        voice_policy.write_policy(
            preferences=["Speak naturally without lists.", "Keep answers under 3 sentences."],
            brief_next_turn=True,
            path=self.state_dir / voice_policy.POLICY_FILENAME,
        )

        # 3. Run hook
        payload = {"session_id": AGENT_SESSION_ID, "prompt": "Explain photosynthesis"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)

        # 4. Verify context output
        self.assertTrue(stdout_text.strip())
        output = json.loads(stdout_text)
        self.assertIn("hookSpecificOutput", output)
        hook_out = output["hookSpecificOutput"]
        self.assertEqual(hook_out["hookEventName"], "UserPromptSubmit")
        context = hook_out["additionalContext"]

        self.assertIn("This turn originated through Auralis voice.", context)
        self.assertIn("A spoken rendering is expected for this turn.", context)
        self.assertIn("submit_spoken_rendering", context)
        self.assertIn("plain spoken text only", context)
        self.assertIn("Brief Next Turn override active", context)
        self.assertIn("Speak naturally without lists.", context)
        self.assertIn("Keep answers under 3 sentences.", context)

        # 5. Verify turn record created on disk (KTD4, KTD11)
        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.session_id, AGENT_SESSION_ID)  # type: ignore[union-attr]
        self.assertEqual(rec.binding_id, VALID_UUID_1)  # type: ignore[union-attr]
        self.assertEqual(rec.turn_id, VALID_UUID_2)  # type: ignore[union-attr]
        self.assertEqual(rec.origin, turn_record.ORIGIN_AURALIS)  # type: ignore[union-attr]

        # 6. Verify brief_next_turn was consumed on transmission (KTD5, R107)
        pol = voice_policy.read_policy(self.state_dir / voice_policy.POLICY_FILENAME)
        self.assertFalse(pol.brief_next_turn)

        # 7. Run a second turn: preferences remain, brief directive is gone
        self.stub.set_turn("b2345678-89ab-4cde-8f01-23456789abcd", VALID_UUID_1, state="open")
        code2, stdout_text2 = self.run_hook(json.dumps(payload))
        self.assertEqual(code2, 0)
        output2 = json.loads(stdout_text2)
        context2 = output2["hookSpecificOutput"]["additionalContext"]
        self.assertIn("This turn originated through Auralis voice.", context2)
        self.assertNotIn("Brief Next Turn override active", context2)
        self.assertIn("Speak naturally without lists.", context2)

    def test_bound_turn_not_originated_injects_explicit_negative_signal_and_preserves_policy(
        self,
    ) -> None:
        # Stub has binding epoch, but no active turn (or state != open)
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.clear_turn()

        # Arm brief_next_turn in policy
        voice_policy.write_policy(
            preferences=["Speak concisely."],
            brief_next_turn=True,
            path=self.state_dir / voice_policy.POLICY_FILENAME,
        )

        payload = {"session_id": AGENT_SESSION_ID, "prompt": "Typed in terminal"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)

        output = json.loads(stdout_text)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("This turn did not originate through Auralis voice.", context)
        self.assertIn("No spoken rendering is expected.", context)
        self.assertNotIn("Speak concisely.", context)
        self.assertNotIn("Brief Next Turn override active", context)

        # Verify brief_next_turn was NOT consumed
        pol = voice_policy.read_policy(self.state_dir / voice_policy.POLICY_FILENAME)
        self.assertTrue(pol.brief_next_turn)

        # Verify turn record initialized as not_originated
        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.session_id, AGENT_SESSION_ID)  # type: ignore[union-attr]
        self.assertEqual(rec.origin, turn_record.ORIGIN_NOT_ORIGINATED)  # type: ignore[union-attr]
        self.assertIsNone(rec.turn_id)  # type: ignore[union-attr]

    def test_unbound_session_emits_no_context(self) -> None:
        # Stub has no binding
        self.stub.clear_binding()
        self.stub.clear_turn()

        payload = {"session_id": AGENT_SESSION_ID, "prompt": "Hello"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

    def test_bridge_bound_to_different_identity_emits_no_context(self) -> None:
        # Stub has binding for different session
        other_identity = {
            "agent_session_id": "session-other",
            "pane_id": "pane-other",
            "terminal_id": "term-other",
        }
        self.stub.set_binding(VALID_UUID_1, other_identity)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        payload = {"session_id": AGENT_SESSION_ID, "prompt": "Hello"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

    def test_bridge_unavailable_emits_no_context(self) -> None:
        # Stop stub server
        self.stub.stop()

        payload = {"session_id": AGENT_SESSION_ID, "prompt": "Hello"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

    def test_identity_resolution_failure_emits_no_context(self) -> None:
        # Invalid Herdr path
        with mock.patch.dict(os.environ, {"HERDR_BIN_PATH": "/nonexistent/herdr"}):
            payload = {"session_id": AGENT_SESSION_ID, "prompt": "Hello"}
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "")

    def test_session_id_mismatch_emits_no_context(self) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # Payload has different session_id than Herdr fixture
        payload = {"session_id": "mismatched-session-id", "prompt": "Hello"}
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

    def test_turn_record_busy_emits_no_context(self) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        with mock.patch.object(
            turn_record,
            "init_turn",
            side_effect=turn_record.TurnRecordBusy("turn_record_busy"),
        ):
            payload = {"session_id": AGENT_SESSION_ID, "prompt": "Hello"}
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "")

    def test_malformed_stdin_exits_zero_with_no_output(self) -> None:
        for malformed in ["", "not json", "[]", "123", json.dumps({"session_id": ""})]:
            with self.subTest(malformed=malformed):
                code, stdout_text = self.run_hook(malformed)
                self.assertEqual(code, 0)
                self.assertEqual(stdout_text, "")


if __name__ == "__main__":
    unittest.main()
