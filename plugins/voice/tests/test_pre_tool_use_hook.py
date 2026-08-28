"""Tests for the Claude PreToolUse hook (U4; KTD7, KTD11; X1).

Exercises:
- Auralis-originated turn tool observation recording (observe-only, no stdout output ever);
- Policy tool allow-list filtering;
- Non-originated turn: no observation recorded;
- Session ID mismatch / missing turn record: no observation recorded;
- Turn record lock busy / exceptions: silent exit 0;
- Malformed inputs: silent exit 0.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "com.infiquetra.claude" / "hooks"))

import pre_tool_use_hook  # noqa: E402
import turn_record  # noqa: E402
import voice_policy  # noqa: E402

AGENT_SESSION_ID = "session-test-pretool-1"


class PreToolUseHookTests(unittest.TestCase):
    """Test suite for pre_tool_use_hook.py."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.env_patcher = mock.patch.dict(
            os.environ, {"VOICE_STATE_DIR": str(self.state_dir)}
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    def run_hook(self, stdin_text: str) -> tuple[int, str]:
        """Run pre_tool_use_hook.main() with injected stdin and captured stdout."""
        stdin_stream = io.StringIO(stdin_text)
        stdout_stream = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", stdin_stream),
            mock.patch.object(sys, "stdout", stdout_stream),
        ):
            code = pre_tool_use_hook.main()
        return code, stdout_stream.getvalue()

    def test_originated_turn_records_observation(self) -> None:
        # Initialize an Auralis-originated turn
        turn_record.init_turn(
            session_id=AGENT_SESSION_ID,
            binding_id="b1111111-1111-4111-8111-111111111111",
            turn_id="t1111111-1111-4111-8111-111111111111",
            origin=turn_record.ORIGIN_AURALIS,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
            "tool_use_id": "toolu_01ABC",
        }
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "", "PreToolUse hook must never emit output")

        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.tool_observations), 1)  # type: ignore[union-attr]
        obs = rec.tool_observations[0]  # type: ignore[union-attr]
        self.assertEqual(obs["tool_name"], "Bash")
        self.assertEqual(obs["tool_input"], {"command": "git status"})
        self.assertEqual(obs["tool_use_id"], "toolu_01ABC")

    def test_allowlist_filtering_records_only_allowed_tools(self) -> None:
        turn_record.init_turn(
            session_id=AGENT_SESSION_ID,
            origin=turn_record.ORIGIN_AURALIS,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        # Set allow-list in policy
        voice_policy.write_policy(
            tool_allowlist=["Read", "Write"],
            path=self.state_dir / voice_policy.POLICY_FILENAME,
        )

        # 1. Tool not in allow-list -> not recorded
        payload_bash = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "toolu_bash",
        }
        code, stdout_text = self.run_hook(json.dumps(payload_bash))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.tool_observations), 0)  # type: ignore[union-attr]

        # 2. Tool in allow-list -> recorded
        payload_read = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file": "main.py"},
            "tool_use_id": "toolu_read",
        }
        code, stdout_text = self.run_hook(json.dumps(payload_read))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.tool_observations), 1)  # type: ignore[union-attr]
        self.assertEqual(rec.tool_observations[0]["tool_name"], "Read")  # type: ignore[union-attr]

    def test_non_originated_turn_records_nothing(self) -> None:
        turn_record.init_turn(
            session_id=AGENT_SESSION_ID,
            origin=turn_record.ORIGIN_NOT_ORIGINATED,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "toolu_01",
        }
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.tool_observations), 0)  # type: ignore[union-attr]

    def test_session_id_mismatch_records_nothing(self) -> None:
        turn_record.init_turn(
            session_id="session-other",
            origin=turn_record.ORIGIN_AURALIS,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "toolu_01",
        }
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.tool_observations), 0)  # type: ignore[union-attr]

    def test_no_turn_record_exits_zero_with_no_output(self) -> None:
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_use_id": "toolu_01",
        }
        code, stdout_text = self.run_hook(json.dumps(payload))
        self.assertEqual(code, 0)
        self.assertEqual(stdout_text, "")

    def test_turn_record_busy_exits_zero_and_drops_observation(self) -> None:
        turn_record.init_turn(
            session_id=AGENT_SESSION_ID,
            origin=turn_record.ORIGIN_AURALIS,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

        with mock.patch.object(
            turn_record,
            "record_tool_observation",
            side_effect=turn_record.TurnRecordBusy("turn_record_busy"),
        ):
            payload = {
                "session_id": AGENT_SESSION_ID,
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
                "tool_use_id": "toolu_01",
            }
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "")

    def test_malformed_input_exits_zero_with_no_output(self) -> None:
        for malformed in [
            "",
            "not json",
            "[]",
            json.dumps({"session_id": AGENT_SESSION_ID}),
            json.dumps({"session_id": AGENT_SESSION_ID, "tool_name": "Bash"}),
            json.dumps({"session_id": "", "tool_name": "Bash", "tool_use_id": "1"}),
        ]:
            with self.subTest(malformed=malformed):
                code, stdout_text = self.run_hook(malformed)
                self.assertEqual(code, 0)
                self.assertEqual(stdout_text, "")


if __name__ == "__main__":
    unittest.main()
