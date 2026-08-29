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

import adapter_identity  # noqa: E402
import bridge_client  # noqa: E402
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


class BridgeClientApprovalOperationTests(unittest.TestCase):
    """Unit tests for BridgeClient.request_approval wire operation."""

    def setUp(self) -> None:
        self.identity = adapter_identity.AdapterIdentity(
            agent_session_id=AGENT_SESSION_ID,
            pane_id="pane-1",
            terminal_id="term-1",
        )
        self.conn = bridge_client.BridgeConnection(
            host="127.0.0.1",
            port=49152,
            token="test_token_43_chars_base64url_alphabet_0123",
            schema=1,
        )
        self.client = bridge_client.BridgeClient(connection=self.conn)

    def test_request_approval_allow_success(self) -> None:
        snapshot = {
            "classification": {
                "result": "voice_approvable",
                "allow_list_entry": "Read",
                "permission_mode": "manual",
            },
            "cwd": "/workspace",
            "read_back": "Read the file main.py",
            "tool_input": {"file_path": "main.py"},
            "tool_name": "Read",
            "tool_use_id": "toolu_01_read",
        }
        mock_response_data = {
            "schema": 1,
            "tool_use_id": "toolu_01_read",
            "decision": "allow",
            "reason": "approved",
            "snapshot": snapshot,
        }

        with mock.patch.object(self.client, "_request", return_value=(200, mock_response_data)) as mock_req:
            resp = self.client.request_approval(
                identity=self.identity,
                binding_id="b1111111-1111-4111-8111-111111111111",
                session_id=AGENT_SESSION_ID,
                tool_use_id="toolu_01_read",
                tool_name="Read",
                tool_input={"file_path": "main.py"},
                permission_mode="manual",
                cwd="/workspace",
            )
            self.assertEqual(resp.tool_use_id, "toolu_01_read")
            self.assertEqual(resp.decision, "allow")
            self.assertEqual(resp.reason, "approved")
            self.assertEqual(resp.snapshot, snapshot)
            self.assertEqual(resp.schema, 1)

            # Assert exact closed request shape
            mock_req.assert_called_once_with(
                "POST",
                "/v1/approval",
                {
                    "schema": 1,
                    "identity": self.identity.to_dict(),
                    "binding_id": "b1111111-1111-4111-8111-111111111111",
                    "session_id": AGENT_SESSION_ID,
                    "tool_use_id": "toolu_01_read",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "main.py"},
                    "permission_mode": "manual",
                    "cwd": "/workspace",
                },
                bridge_client.APPROVAL_TIMEOUT_SECONDS,
                self.conn,
            )

    def test_request_approval_defer_success(self) -> None:
        mock_response_data = {
            "schema": 1,
            "tool_use_id": "toolu_02_bash",
            "decision": "defer",
            "reason": "notAllowListed",
        }

        with mock.patch.object(self.client, "_request", return_value=(200, mock_response_data)):
            resp = self.client.request_approval(
                identity=self.identity,
                binding_id="b1111111-1111-4111-8111-111111111111",
                session_id=AGENT_SESSION_ID,
                tool_use_id="toolu_02_bash",
                tool_name="Bash",
                tool_input={"command": "rm -rf /"},
                permission_mode="manual",
                cwd="/workspace",
            )
            self.assertEqual(resp.tool_use_id, "toolu_02_bash")
            self.assertEqual(resp.decision, "defer")
            self.assertEqual(resp.reason, "notAllowListed")
            self.assertIsNone(resp.snapshot)

    def test_request_approval_401_unauthorized(self) -> None:
        with mock.patch.object(self.client, "_request", return_value=(401, {"error": "unauthorized"})):
            with self.assertRaises(bridge_client.BridgeUnauthorized):
                self.client.request_approval(
                    identity=self.identity,
                    binding_id="b1111111-1111-4111-8111-111111111111",
                    session_id=AGENT_SESSION_ID,
                    tool_use_id="toolu_01",
                    tool_name="Read",
                    tool_input={},
                    permission_mode="manual",
                    cwd="/workspace",
                )

    def test_request_approval_non_200_transport_error(self) -> None:
        for status, error_code in [(400, "invalid_request"), (500, "internal_error")]:
            with self.subTest(status=status):
                with mock.patch.object(self.client, "_request", return_value=(status, {"error": error_code})):
                    with self.assertRaises(bridge_client.BridgeTransportError) as caught:
                        self.client.request_approval(
                            identity=self.identity,
                            binding_id="b1111111-1111-4111-8111-111111111111",
                            session_id=AGENT_SESSION_ID,
                            tool_use_id="toolu_01",
                            tool_name="Read",
                            tool_input={},
                            permission_mode="manual",
                            cwd="/workspace",
                        )
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertEqual(caught.exception.error_code, error_code)

    def test_request_approval_schema_mismatch(self) -> None:
        for bad_schema in [2, "1", None, True]:
            with self.subTest(schema=bad_schema):
                data = {
                    "schema": bad_schema,
                    "tool_use_id": "toolu_01",
                    "decision": "defer",
                    "reason": "notAllowListed",
                }
                with mock.patch.object(self.client, "_request", return_value=(200, data)):
                    with self.assertRaises(bridge_client.BridgeTransportError) as caught:
                        self.client.request_approval(
                            identity=self.identity,
                            binding_id="b1111111-1111-4111-8111-111111111111",
                            session_id=AGENT_SESSION_ID,
                            tool_use_id="toolu_01",
                            tool_name="Read",
                            tool_input={},
                            permission_mode="manual",
                            cwd="/workspace",
                        )
                    self.assertIn("schema", str(caught.exception))

    def test_request_approval_missing_and_invalid_fields(self) -> None:
        cases = [
            ("missing tool_use_id", {"schema": 1, "decision": "defer", "reason": "r"}),
            ("non-string tool_use_id", {"schema": 1, "tool_use_id": 123, "decision": "defer", "reason": "r"}),
            ("missing decision", {"schema": 1, "tool_use_id": "t1", "reason": "r"}),
            ("missing reason", {"schema": 1, "tool_use_id": "t1", "decision": "defer"}),
            ("unknown decision", {"schema": 1, "tool_use_id": "t1", "decision": "ask", "reason": "r"}),
            ("allow missing snapshot", {"schema": 1, "tool_use_id": "t1", "decision": "allow", "reason": "approved"}),
            ("allow non-dict snapshot", {"schema": 1, "tool_use_id": "t1", "decision": "allow", "reason": "approved", "snapshot": "not a dict"}),
            ("defer with extra snapshot", {"schema": 1, "tool_use_id": "t1", "decision": "defer", "reason": "r", "snapshot": {}}),
            ("allow with extra field", {"schema": 1, "tool_use_id": "t1", "decision": "allow", "reason": "approved", "snapshot": {}, "extra": 1}),
        ]
        for name, data in cases:
            with self.subTest(case=name):
                with mock.patch.object(self.client, "_request", return_value=(200, data)):
                    with self.assertRaises(bridge_client.BridgeTransportError):
                        self.client.request_approval(
                            identity=self.identity,
                            binding_id="b1111111-1111-4111-8111-111111111111",
                            session_id=AGENT_SESSION_ID,
                            tool_use_id="t1",
                            tool_name="Read",
                            tool_input={},
                            permission_mode="manual",
                            cwd="/workspace",
                        )


class PreToolUseApprovalHookTests(unittest.TestCase):
    """Test suite for PreToolUse hook approval behavior and fail-closed deferral."""

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

        self.identity = adapter_identity.AdapterIdentity(
            agent_session_id=AGENT_SESSION_ID,
            pane_id="pane-1",
            terminal_id="term-1",
        )
        self.binding_id = "b1111111-1111-4111-8111-111111111111"
        self.snapshot_bound = bridge_client.CurrentSnapshot(
            binding=bridge_client.BindingEpoch(
                binding_id=self.binding_id,
                identity=self.identity,
            ),
            turn=None,
            schema=1,
        )

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

    def test_allow_path_on_exact_match(self) -> None:
        """Allow decision emitted on exact match of request identifier and complete snapshot."""
        tool_input = {"file_path": "src/main.py", "offset": 10}
        tool_use_id = "toolu_01_read_exact"
        tool_name = "Read"

        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": tool_use_id,
            "permission_mode": "manual",
            "cwd": "/Users/test/repo",
        }

        canonical_snapshot = {
            "classification": {
                "result": "voice_approvable",
                "allow_list_entry": "Read",
                "permission_mode": "manual",
            },
            "cwd": "/Users/test/repo",
            "read_back": "Read the file src/main.py from line 10",
            "tool_input": {"offset": 10, "file_path": "src/main.py"},  # key order variation
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
        }

        approval_resp = bridge_client.ApprovalResponse(
            tool_use_id=tool_use_id,
            decision="allow",
            reason="approved",
            snapshot=canonical_snapshot,
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp) as mock_approve,
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)

            # Assert allow decision emitted exactly
            parsed_output = json.loads(stdout_text)
            self.assertEqual(
                parsed_output,
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                },
            )

            # Assert request forwarded with exact fields
            mock_approve.assert_called_once_with(
                identity=self.identity,
                binding_id=self.binding_id,
                session_id=AGENT_SESSION_ID,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
                permission_mode="manual",
                cwd="/Users/test/repo",
            )

    def test_defer_on_identifier_mismatch(self) -> None:
        """Defer (exit 0 with no stdout) when returned tool_use_id mismatches."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_expected_id",
            "permission_mode": "manual",
            "cwd": "/workspace",
        }
        approval_resp = bridge_client.ApprovalResponse(
            tool_use_id="toolu_DIFFERENT_id",
            decision="allow",
            reason="approved",
            snapshot={
                "classification": {"result": "voice_approvable"},
                "tool_name": "Read",
                "tool_use_id": "toolu_expected_id",
                "tool_input": {"file_path": "main.py"},
                "cwd": "/workspace",
                "read_back": "Read the file main.py",
            },
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Identifier mismatch must DEFER with no output")

    def test_defer_on_snapshot_identifier_mismatch(self) -> None:
        """Defer when snapshot.tool_use_id mismatches request."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_expected_id",
        }
        approval_resp = bridge_client.ApprovalResponse(
            tool_use_id="toolu_expected_id",
            decision="allow",
            reason="approved",
            snapshot={
                "classification": {"result": "voice_approvable"},
                "tool_name": "Read",
                "tool_use_id": "toolu_DIFFERENT_in_snapshot",
                "tool_input": {"file_path": "main.py"},
                "cwd": "/workspace",
                "read_back": "Read the file main.py",
            },
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Snapshot identifier mismatch must DEFER with no output")

    def test_defer_on_snapshot_tool_name_mismatch(self) -> None:
        """Defer when snapshot.tool_name mismatches original tool_name."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        approval_resp = bridge_client.ApprovalResponse(
            tool_use_id="toolu_01",
            decision="allow",
            reason="approved",
            snapshot={
                "classification": {"result": "voice_approvable"},
                "tool_name": "Grep",  # mismatched
                "tool_use_id": "toolu_01",
                "tool_input": {"file_path": "main.py"},
                "cwd": "/workspace",
                "read_back": "Search for pattern",
            },
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Snapshot tool_name mismatch must DEFER with no output")

    def test_defer_on_snapshot_tool_input_mismatch(self) -> None:
        """Defer when snapshot.tool_input canonically differs from original tool_input."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py", "lines": [1, 2, 3]},
            "tool_use_id": "toolu_01",
        }
        approval_resp = bridge_client.ApprovalResponse(
            tool_use_id="toolu_01",
            decision="allow",
            reason="approved",
            snapshot={
                "classification": {"result": "voice_approvable"},
                "tool_name": "Read",
                "tool_use_id": "toolu_01",
                "tool_input": {"file_path": "other_file.py", "lines": [1, 2, 3]},  # modified input
                "cwd": "/workspace",
                "read_back": "Read the file other_file.py",
            },
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Snapshot tool_input mismatch must DEFER with no output")

    def test_defer_on_snapshot_classification_not_voice_approvable(self) -> None:
        """Defer when classification.result is not voice_approvable."""
        for result in ["always_visual", "unknown", "not_allow_listed", "", None]:
            with self.subTest(result=result):
                payload = {
                    "session_id": AGENT_SESSION_ID,
                    "tool_name": "Read",
                    "tool_input": {"file_path": "main.py"},
                    "tool_use_id": "toolu_01",
                }
                approval_resp = bridge_client.ApprovalResponse(
                    tool_use_id="toolu_01",
                    decision="allow",
                    reason="approved",
                    snapshot={
                        "classification": {"result": result} if result is not None else {},
                        "tool_name": "Read",
                        "tool_use_id": "toolu_01",
                        "tool_input": {"file_path": "main.py"},
                        "cwd": "/workspace",
                        "read_back": "Read the file main.py",
                    },
                    schema=1,
                )

                with (
                    mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
                    mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
                    mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
                ):
                    code, stdout_text = self.run_hook(json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout_text, "", "Non voice_approvable result must DEFER")

    def test_defer_on_core_decision_defer(self) -> None:
        """Defer when Core returns decision='defer' for any reason."""
        reasons = ["notAllowListed", "alwaysVisual", "permissionModeNotPrompting", "deadline", "sinkClosed"]
        for reason in reasons:
            with self.subTest(reason=reason):
                payload = {
                    "session_id": AGENT_SESSION_ID,
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls"},
                    "tool_use_id": "toolu_01",
                }
                approval_resp = bridge_client.ApprovalResponse(
                    tool_use_id="toolu_01",
                    decision="defer",
                    reason=reason,
                    snapshot=None,
                    schema=1,
                )

                with (
                    mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
                    mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
                    mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
                ):
                    code, stdout_text = self.run_hook(json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout_text, "", "Core defer must DEFER with no output")

    def test_defer_on_malformed_and_partial_responses(self) -> None:
        """Defer on malformed, partial, or non-conforming responses."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        malformed_snapshots = [
            None,
            "string snapshot",
            [1, 2, 3],
            {"tool_name": "Read"},  # missing other fields
            {"tool_name": "Read", "tool_use_id": "toolu_01", "tool_input": "not a dict"},
        ]
        for snapshot in malformed_snapshots:
            with self.subTest(snapshot=snapshot):
                approval_resp = bridge_client.ApprovalResponse(
                    tool_use_id="toolu_01",
                    decision="allow",
                    reason="approved",
                    snapshot=snapshot,  # type: ignore[arg-type]
                    schema=1,
                )

                with (
                    mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
                    mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
                    mock.patch.object(bridge_client.BridgeClient, "request_approval", return_value=approval_resp),
                ):
                    code, stdout_text = self.run_hook(json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout_text, "")

    def test_defer_on_transport_failure(self) -> None:
        """Defer on any bridge transport failure or exception."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        exceptions = [
            bridge_client.BridgeTransportError("connection refused", error_code="transport_error"),
            bridge_client.BridgeUnauthorized("unauthorized"),
            bridge_client.BridgeUnavailable("bridge unavailable"),
            OSError("connection reset"),
            ConnectionRefusedError("connection refused"),
            BrokenPipeError("broken pipe"),
            RuntimeError("unexpected crash"),
        ]
        for exc in exceptions:
            with self.subTest(exc=type(exc).__name__):
                with (
                    mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
                    mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
                    mock.patch.object(bridge_client.BridgeClient, "request_approval", side_effect=exc),
                ):
                    code, stdout_text = self.run_hook(json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout_text, "", f"{type(exc).__name__} must DEFER with no output")

    def test_defer_on_timeout(self) -> None:
        """Defer when bridge request times out."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        timeout_exceptions = [
            bridge_client.BridgeTransportError("operation timed out on deadline", error_code="transport_error"),
            TimeoutError("socket timed out"),
        ]
        for exc in timeout_exceptions:
            with self.subTest(exc=type(exc).__name__):
                with (
                    mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
                    mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=self.snapshot_bound),
                    mock.patch.object(bridge_client.BridgeClient, "request_approval", side_effect=exc),
                ):
                    code, stdout_text = self.run_hook(json.dumps(payload))
                    self.assertEqual(code, 0)
                    self.assertEqual(stdout_text, "", "Timeout must DEFER with no output")

    def test_defer_on_no_bridge_binding(self) -> None:
        """Defer when session is not covered by any active bridge binding."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        snapshot_unbound = bridge_client.CurrentSnapshot(binding=None, turn=None, schema=1)

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=snapshot_unbound),
            mock.patch.object(bridge_client.BridgeClient, "request_approval") as mock_approve,
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Unbound session must DEFER with no output")
            mock_approve.assert_not_called()

    def test_defer_on_session_mismatch_with_binding(self) -> None:
        """Defer when session_id does not match the active bridge binding."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        different_identity = adapter_identity.AdapterIdentity(
            agent_session_id="different-session-id",
            pane_id="pane-2",
            terminal_id="term-2",
        )
        snapshot_diff = bridge_client.CurrentSnapshot(
            binding=bridge_client.BindingEpoch(
                binding_id=self.binding_id,
                identity=different_identity,
            ),
            turn=None,
            schema=1,
        )

        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", return_value=self.identity),
            mock.patch.object(bridge_client.BridgeClient, "get_current", return_value=snapshot_diff),
            mock.patch.object(bridge_client.BridgeClient, "request_approval") as mock_approve,
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Session mismatch must DEFER with no output")
            mock_approve.assert_not_called()

    def test_defer_on_identity_resolution_failure(self) -> None:
        """Defer when adapter identity cannot be resolved."""
        payload = {
            "session_id": AGENT_SESSION_ID,
            "tool_name": "Read",
            "tool_input": {"file_path": "main.py"},
            "tool_use_id": "toolu_01",
        }
        with (
            mock.patch.object(adapter_identity, "resolve_adapter_identity", side_effect=Exception("no identity")),
            mock.patch.object(bridge_client.BridgeClient, "request_approval") as mock_approve,
        ):
            code, stdout_text = self.run_hook(json.dumps(payload))
            self.assertEqual(code, 0)
            self.assertEqual(stdout_text, "", "Identity failure must DEFER with no output")
            mock_approve.assert_not_called()

    def test_hooks_json_pre_tool_use_timeout_exceeds_50_seconds(self) -> None:
        """Verify registered PreToolUse timeout in hooks.json is > 50s (KTD15)."""
        hooks_json_path = (
            Path(__file__).resolve().parents[1]
            / "com.infiquetra.claude"
            / "hooks"
            / "hooks.json"
        )
        data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
        pre_tool_hooks = data["hooks"]["PreToolUse"]
        self.assertTrue(len(pre_tool_hooks) > 0)
        hook_def = pre_tool_hooks[0]["hooks"][0]
        timeout = hook_def["timeout"]
        self.assertIsInstance(timeout, int)
        self.assertGreater(
            timeout,
            50,
            f"PreToolUse timeout in hooks.json ({timeout}s) must exceed Core's 50s hold (KTD15)",
        )
        self.assertEqual(timeout, 60)


if __name__ == "__main__":
    unittest.main()
