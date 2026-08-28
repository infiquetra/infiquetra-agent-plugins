"""Tests for the MCP authored-rendering surface and presence lifecycle (U3; R20, R21, R121, R122; KTD1, KTD2, KTD4, KTD8, KTD11).

Exercises:
- MCP JSON-RPC protocol framing and method dispatch (initialize, ping, tools/list, tools/call);
- AE26 surface reject-then-accept with no repair;
- Plain text forwarding verbatim with captured identifiers (R20, KTD4);
- Wire rejection vocabulary relay verbatim;
- Session mismatch, missing turn record, and identity refusal availability handling;
- Presence registration, renewal, re-discovery on 401, and delete on shutdown (KTD2);
- Lost-response reconciliation (F8);
- Executable entrypoint subprocess test running declared argv from installed-root copy.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapter_identity import AdapterIdentity, IdentityRefusal  # noqa: E402
from bridge_client import BridgeClient  # noqa: E402
from bridge_stub import DEFAULT_STUB_TOKEN, BridgeStub  # noqa: E402
from mcp_server import MCPServer, PresenceWorker, run_server  # noqa: E402
import turn_record  # noqa: E402

VALID_UUID_1 = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
VALID_UUID_2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
VALID_UUID_3 = "a1234567-89ab-4cde-8f01-23456789abcd"


class MCPProtocolTests(unittest.TestCase):
    """Protocol compliance tests for stdlib JSON-RPC 2.0 stdio framing (KTD8)."""

    def setUp(self) -> None:
        self.server = MCPServer(enable_presence=False)

    def test_initialize_echoes_supported_protocol_version(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        result = resp["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "auralis-voice")
        self.assertEqual(result["serverInfo"]["version"], "0.3.0")

    def test_initialize_falls_back_to_newest_version_when_unsupported(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "initialize",
            "params": {"protocolVersion": "1990-01-01"},
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["result"]["protocolVersion"], "2024-11-05")

    def test_notifications_initialized_returns_no_response(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        self.assertIsNone(self.server.handle_line(raw_req))

    def test_ping_returns_empty_result(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "ping",
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["result"], {})

    def test_tools_list_exposes_submit_spoken_rendering_with_closed_schema(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        tools = resp["result"]["tools"]
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], "submit_spoken_rendering")
        self.assertEqual(
            tool["inputSchema"],
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The plain spoken text to be rendered as speech.",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        )

    def test_unknown_method_returns_method_not_found_error(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "unknown_tool_or_method",
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["error"]["code"], -32601)
        self.assertIn("Method not found", resp["error"]["message"])

    def test_unknown_tool_call_returns_tool_not_found(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "invalid_tool", "arguments": {"text": "hi"}},
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["error"]["code"], -32601)

    def test_invalid_tool_call_arguments_returns_invalid_params(self) -> None:
        raw_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "submit_spoken_rendering", "arguments": {"not_text": 123}},
        })
        raw_resp = self.server.handle_line(raw_req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["error"]["code"], -32602)

    def test_malformed_json_returns_parse_error(self) -> None:
        raw_resp = self.server.handle_line("{ broken json")
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertEqual(resp["error"]["code"], -32700)


class AE26AndSurfaceRenderingTests(unittest.TestCase):
    """AE26 and surface gating tests against independent bridge_stub."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.record_path = self.state_dir / turn_record.TURN_RECORD_FILENAME

        self.stub = BridgeStub().start()
        self.addCleanup(self.stub.stop)

        self.identity = AdapterIdentity(
            agent_session_id="session-ae26",
            pane_id="w1:p1",
            terminal_id="term-1",
        )
        self.stub.set_binding(VALID_UUID_1, self.identity.to_dict())
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        self.bridge_file = self.stub.write_discovery_file(self.temp_dir.name)
        self.client = BridgeClient(
            bridge_file=self.bridge_file,
        )
        self.server = MCPServer(
            bridge_client_instance=self.client,
            identity_resolver=lambda: self.identity,
            turn_record_path=self.record_path,
            enable_presence=False,
        )

    def _call_submit(self, text: str, req_id: int = 1) -> dict:
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": text},
            },
        })
        raw_resp = self.server.handle_line(req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        self.assertFalse(resp.get("result", {}).get("isError", True))
        content_text = resp["result"]["content"][0]["text"]
        return json.loads(content_text)

    def test_ae26_reject_then_accept_no_repair(self) -> None:
        # Initialize turn record with prompt-time captured identifiers
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        # 1. Submission containing Markdown emphasis and fenced code block
        rejected_text = "Here is a **bold** proposal:\n```python\nprint('hello')\n```"
        tool_payload = self._call_submit(rejected_text, req_id=1)

        self.assertEqual(tool_payload["disposition"], "rejected_content")
        self.assertEqual(tool_payload["reason"], "fenced_code_block")
        self.assertIn("fenced_code_block", tool_payload["detail"]["detected_classes"])

        # Assert nothing was forwarded to the wire
        rendering_requests = [
            r for r in self.stub.requests if r.path == "/v1/rendering" and r.method == "POST"
        ]
        self.assertEqual(len(rendering_requests), 0)

        # Assert turn record recorded the rejected submission
        rec = turn_record.read_turn_record(self.record_path)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.submissions), 1)  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[0]["disposition"], "rejected_content")  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[0]["reason"], "fenced_code_block")  # type: ignore[union-attr]
        # Verify no cleaned text exists in state
        self.assertEqual(rec.submissions[0]["text"], rejected_text)  # type: ignore[union-attr]

        # 2. Resubmission with plain text on the same turn
        plain_text = "Here is a bold proposal, and we print hello."
        accept_payload = self._call_submit(plain_text, req_id=2)

        self.assertEqual(accept_payload["disposition"], "accepted")
        self.assertEqual(accept_payload["detail"], "accepted")

        # Assert stub received POST /v1/rendering with exact byte-identical text and captured IDs
        rendering_requests = [
            r for r in self.stub.requests if r.path == "/v1/rendering" and r.method == "POST"
        ]
        self.assertEqual(len(rendering_requests), 1)
        req_body = rendering_requests[0].body
        self.assertIsNotNone(req_body)
        self.assertEqual(req_body["binding_id"], VALID_UUID_1)  # type: ignore[index]
        self.assertEqual(req_body["turn_id"], VALID_UUID_2)  # type: ignore[index]
        self.assertEqual(req_body["text"], plain_text)  # type: ignore[index]
        self.assertEqual(req_body["identity"], self.identity.to_dict())  # type: ignore[index]

        # Assert turn record now carries both submissions
        rec = turn_record.read_turn_record(self.record_path)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.submissions), 2)  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[1]["disposition"], "accepted")  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[1]["text"], plain_text)  # type: ignore[union-attr]

    def test_forwarding_uses_captured_identifiers_not_stub_current(self) -> None:
        # Turn record holds captured turn VALID_UUID_2
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        # Advance stub's current turn to VALID_UUID_3
        self.stub.set_turn(VALID_UUID_3, VALID_UUID_1, state="open")

        # Submit plain text
        payload = self._call_submit("Plain text targeting captured turn", req_id=3)

        # The submission forwarded captured pair (VALID_UUID_2); stub adjudicated turn_not_current
        self.assertEqual(payload["disposition"], "rejected_by_core")
        self.assertEqual(payload["reason"], "turn_not_current")

        rec = turn_record.read_turn_record(self.record_path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.submissions[-1]["disposition"], "rejected_by_core")  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[-1]["reason"], "turn_not_current")  # type: ignore[union-attr]

    def test_wire_rejection_reasons_relayed_verbatim(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        wire_reasons = [
            ("canceled", "turn_canceled"),
            ("fallback_accepted", "fallback_already_began"),
            ("authored_accepted", "duplicate_rendering"),
        ]

        for stub_state, expected_reason in wire_reasons:
            with self.subTest(stub_state=stub_state, expected_reason=expected_reason):
                self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state=stub_state)
                payload = self._call_submit("Plain text", req_id=4)
                self.assertEqual(payload["disposition"], "rejected_by_core")
                self.assertEqual(payload["reason"], expected_reason)

    def test_no_turn_record_returns_unavailable_no_current_turn(self) -> None:
        # No turn record exists in state dir
        if self.record_path.exists():
            self.record_path.unlink()

        payload = self._call_submit("Plain text without active record", req_id=5)
        self.assertEqual(payload["disposition"], "unavailable")
        self.assertEqual(payload["reason"], "no_current_turn")

        # Zero wire calls
        rendering_requests = [
            r for r in self.stub.requests if r.path == "/v1/rendering" and r.method == "POST"
        ]
        self.assertEqual(len(rendering_requests), 0)

    def test_record_session_mismatch_returns_unavailable_no_current_turn(self) -> None:
        # Turn record for a different session
        turn_record.init_turn(
            session_id="other-session-id",
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        payload = self._call_submit("Plain text with mismatched session", req_id=6)
        self.assertEqual(payload["disposition"], "unavailable")
        self.assertEqual(payload["reason"], "no_current_turn")

    def test_identity_refusal_returns_unavailable_not_bound(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        def _refuse_identity() -> AdapterIdentity:
            raise IdentityRefusal("HERDR_PANE_ID missing")

        unbound_server = MCPServer(
            bridge_client_instance=self.client,
            identity_resolver=_refuse_identity,
            turn_record_path=self.record_path,
            enable_presence=False,
        )

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "Plain text"},
            },
        })
        raw_resp = unbound_server.handle_line(req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        tool_payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(tool_payload["disposition"], "unavailable")
        self.assertEqual(tool_payload["reason"], "not_bound")

    def test_gating_turn_record_busy_returns_unavailable_without_touching_wire(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        with mock.patch("mcp_server.record_submission", side_effect=turn_record.TurnRecordBusy("lock busy")):
            payload = self._call_submit("Heading:\n# Title", req_id=10)

        self.assertEqual(payload["disposition"], "unavailable")
        self.assertEqual(payload["reason"], "turn_record_busy")
        self.assertEqual(self.stub.requests, [])

    def test_accepted_rendering_with_turn_record_busy_after_wire_still_returns_accepted(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        with mock.patch("mcp_server.record_submission", side_effect=turn_record.TurnRecordBusy("lock busy")):
            payload = self._call_submit("Plain text rendering accepted by wire", req_id=11)

        self.assertEqual(payload["disposition"], "accepted")
        self.assertEqual(payload["detail"], "accepted")
        rendering_requests = [r for r in self.stub.requests if r.path == "/v1/rendering"]
        self.assertEqual(len(rendering_requests), 1)

    def test_rejected_rendering_with_turn_record_busy_after_wire_still_returns_rejected(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )
        self.stub.set_turn(VALID_UUID_3, VALID_UUID_1, state="open")

        with mock.patch("mcp_server.record_submission", side_effect=turn_record.TurnRecordBusy("lock busy")):
            payload = self._call_submit("Plain text rendering targeting old turn", req_id=12)

        self.assertEqual(payload["disposition"], "rejected_by_core")
        self.assertEqual(payload["reason"], "turn_not_current")


class LostResponseReconciliationSurfaceTests(unittest.TestCase):
    """Surface-level lost response reconciliation tests (F8; §8)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.record_path = self.state_dir / turn_record.TURN_RECORD_FILENAME

        self.stub = BridgeStub().start()
        self.addCleanup(self.stub.stop)

        self.identity = AdapterIdentity(
            agent_session_id="session-f8",
            pane_id="w1:p1",
            terminal_id="term-1",
        )
        self.stub.set_binding(VALID_UUID_1, self.identity.to_dict())
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        self.bridge_file = self.stub.write_discovery_file(self.temp_dir.name)
        self.client = BridgeClient(
            bridge_file=self.bridge_file,
        )
        self.server = MCPServer(
            bridge_client_instance=self.client,
            identity_resolver=lambda: self.identity,
            turn_record_path=self.record_path,
            enable_presence=False,
        )

    def test_lost_response_reconciles_to_accepted_on_retry(self) -> None:
        turn_record.init_turn(
            session_id=self.identity.agent_session_id,
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.record_path,
        )

        # Instruct stub to accept the first request but drop the HTTP response
        self.stub.drop_next_rendering_response()

        req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "Plain text with lost response"},
            },
        })
        raw_resp = self.server.handle_line(req)
        self.assertIsNotNone(raw_resp)
        resp = json.loads(raw_resp)  # type: ignore[arg-type]
        tool_payload = json.loads(resp["result"]["content"][0]["text"])

        # Tool result reports accepted with detail accepted_on_retry
        self.assertEqual(tool_payload["disposition"], "accepted")
        self.assertEqual(tool_payload["detail"], "accepted_on_retry")

        # Turn record records disposition accepted
        rec = turn_record.read_turn_record(self.record_path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.submissions[-1]["disposition"], "accepted")  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[-1]["detail"], {"detail": "accepted_on_retry"})  # type: ignore[union-attr]


class PresenceLifecycleTests(unittest.TestCase):
    """Presence background worker tests (KTD2; §6.2, §6.3)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.stub = BridgeStub().start()
        self.addCleanup(self.stub.stop)
        self.identity = AdapterIdentity(
            agent_session_id="session-presence",
            pane_id="w1:p1",
            terminal_id="term-1",
        )
        self.bridge_file = self.stub.write_discovery_file(self.temp_dir.name)
        self.client = BridgeClient(
            bridge_file=self.bridge_file,
        )

    def test_presence_registration_renewal_and_deletion(self) -> None:
        worker = PresenceWorker(
            bridge_client_instance=self.client,
            identity_resolver=lambda: self.identity,
        )
        # Initial registration
        self.assertTrue(worker.tick())
        self.assertEqual(worker.registration_count, 1)
        self.assertEqual(worker.renewal_count, 0)

        put_requests = [
            r for r in self.stub.requests if r.path == "/v1/presence" and r.method == "PUT"
        ]
        self.assertEqual(len(put_requests), 1)
        self.assertEqual(put_requests[0].body["identity"], self.identity.to_dict())  # type: ignore[index]

        # Renewal tick
        self.assertTrue(worker.tick())
        self.assertEqual(worker.registration_count, 1)
        self.assertEqual(worker.renewal_count, 1)

        # Deletion on stop / shutdown
        self.assertTrue(worker.delete_presence())
        del_requests = [
            r for r in self.stub.requests if r.path == "/v1/presence" and r.method == "DELETE"
        ]
        self.assertEqual(len(del_requests), 1)
        self.assertEqual(del_requests[0].body["identity"], self.identity.to_dict())  # type: ignore[index]

    def test_presence_re_discovery_on_token_rotation(self) -> None:
        worker = PresenceWorker(
            bridge_client_instance=self.client,
            identity_resolver=lambda: self.identity,
        )
        self.assertTrue(worker.tick())

        # Rotate token on stub
        new_token = "new_token_43_chars_base64url_alphabet_01234"
        self.stub.token = new_token
        # First tick gets 401 Unauthorized and resets client connection
        self.assertFalse(worker.tick())

        # Write updated discovery file
        self.stub.write_discovery_file(self.temp_dir.name)
        # Next tick re-discovers new token and succeeds
        self.assertTrue(worker.tick())

    def test_presence_re_discovery_on_connection_refusal(self) -> None:
        worker = PresenceWorker(
            bridge_client_instance=self.client,
            identity_resolver=lambda: self.identity,
        )
        self.assertTrue(worker.tick())
        self.assertEqual(worker.registration_count, 1)

        # Stop the stub to simulate connection refusal / bridge down
        self.stub.stop()

        # Tick fails and resets connection + registered_identity
        self.assertFalse(worker.tick())
        self.assertIsNone(worker.registered_identity)

        # Restart stub on a new port and write new discovery file
        self.stub = BridgeStub().start()
        self.stub.set_binding(VALID_UUID_1, self.identity.to_dict())
        self.stub.write_discovery_file(self.temp_dir.name)

        # Next tick re-reads discovery, connects to new stub, and registers anew
        self.assertTrue(worker.tick())
        self.assertEqual(worker.registration_count, 2)


class ExecutableEntrypointTests(unittest.TestCase):
    """Declared MCP server entrypoint subprocess test (AGENTS.md executable entrypoint rule)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        # Set up installed-root copy of plugins/voice
        repo_voice_root = Path(__file__).resolve().parents[1]
        self.installed_root = Path(self.temp_dir.name) / "voice"
        shutil.copytree(repo_voice_root, self.installed_root)

        # Set up state dir and home dir
        self.state_dir = Path(self.temp_dir.name) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.home_dir = Path(self.temp_dir.name) / "home"
        self.home_dir.mkdir(parents=True, exist_ok=True)

        # Set up bridge stub and write bridge.json into simulated HOME
        self.stub = BridgeStub().start()
        self.addCleanup(self.stub.stop)
        bridge_dir = self.home_dir / "Library" / "Application Support" / "Auralis"
        self.stub.write_discovery_file(bridge_dir)

        # Set up mock herdr executable
        self.herdr_path = Path(self.temp_dir.name) / "mock_herdr"
        mock_herdr_code = (
            "#!/bin/sh\n"
            'echo \'{"result": {"type": "agent_list", "agents": [{"pane_id": "pane-subproc-1", "terminal_id": "term-subproc-1", "agent_session": {"value": "session-subproc-1"}}]}}\'\n'
        )
        self.herdr_path.write_text(mock_herdr_code, encoding="utf-8")
        os.chmod(self.herdr_path, 0o755)

        # Set stub binding and turn
        self.identity_dict = {
            "agent_session_id": "session-subproc-1",
            "pane_id": "pane-subproc-1",
            "terminal_id": "term-subproc-1",
        }
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # Initialize turn record in VOICE_STATE_DIR
        turn_record.init_turn(
            session_id="session-subproc-1",
            binding_id=VALID_UUID_1,
            turn_id=VALID_UUID_2,
            path=self.state_dir / turn_record.TURN_RECORD_FILENAME,
        )

    def test_declared_mcp_server_entrypoint_subprocess(self) -> None:
        server_script = self.installed_root / "scripts" / "mcp_server.py"
        self.assertTrue(server_script.is_file())

        env = dict(os.environ)
        env["HOME"] = str(self.home_dir)
        env["VOICE_STATE_DIR"] = str(self.state_dir)
        env["HERDR_PANE_ID"] = "pane-subproc-1"
        env["HERDR_BIN_PATH"] = str(self.herdr_path)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        proc = subprocess.Popen(
            ["python3", str(server_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )

        def send_and_recv(msg: dict) -> dict:
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            if not line:
                stderr_text = proc.stderr.read() if proc.stderr else ""
                self.fail(f"server closed stdout unexpectedly; stderr:\n{stderr_text}")
            return json.loads(line)

        # 1. initialize
        init_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(init_resp["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "auralis-voice")

        # 2. tools/list
        list_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        tools = list_resp["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "submit_spoken_rendering")

        # 3. tools/call (rejected Markdown)
        call_rej_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "Heading:\n# Title\nSome **bold** prose."},
            },
        })
        rej_payload = json.loads(call_rej_resp["result"]["content"][0]["text"])
        self.assertEqual(rej_payload["disposition"], "rejected_content")
        self.assertEqual(rej_payload["reason"], "markdown_formatting")

        # 4. tools/call (accepted plain text)
        call_acc_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "Title. Some bold prose."},
            },
        })
        acc_payload = json.loads(call_acc_resp["result"]["content"][0]["text"])
        self.assertEqual(acc_payload["disposition"], "accepted")

        # 5. Clean termination on stdin EOF
        assert proc.stdin is not None
        proc.stdin.close()
        exit_code = proc.wait(timeout=5.0)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        self.assertEqual(exit_code, 0)

        # Verify turn record was updated by the subprocess
        rec = turn_record.read_turn_record(self.state_dir / turn_record.TURN_RECORD_FILENAME)
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec.submissions), 2)  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[0]["disposition"], "rejected_content")  # type: ignore[union-attr]
        self.assertEqual(rec.submissions[1]["disposition"], "accepted")  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
