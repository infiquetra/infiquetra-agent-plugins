"""Integration test for R122 at the adapter boundary across production processes (U4; R122, R22, R23, R121; KTD1, KTD3, KTD4, KTD6, KTD11).

Exercises the complete adapter-side lifecycle with real subprocesses and real pipes:
1. The BridgeStub on loopback port hosts an open turn bound to the adapter identity;
2. Real ``user_prompt_submit_hook.py`` runs as a subprocess, captures the (binding_id, turn_id)
   pair into the turn record, and injects context;
3. Real ``mcp_server.py`` runs as a subprocess at its declared argv and receives a Markdown
   rendering via ``tools/call submit_spoken_rendering``; the gate rejects it with a named
   ``rejected_content`` reason, and nothing is forwarded to the bridge;
4. No replacement rendering is submitted;
5. Real ``stop_hook.py`` runs as a subprocess for the completing turn;
6. The resulting turn record on disk contains the full audit trail: the prompt-time captured
   identifiers, the named content rejection, and the reconciled ``fallback`` outcome, with
   no local speak child spawned.

This proves the adapter-side half of R122 entirely through production entrypoints.
The Core-side half (turn marked fallback_accepted in Core) is proven by the joint AE36 test.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bridge_stub import DEFAULT_STUB_TOKEN, BridgeStub  # noqa: E402
import turn_record  # noqa: E402

VALID_UUID_1 = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
VALID_UUID_2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"

AGENT_SESSION_ID = "session-r122-proc-1"
PANE_ID = "pane-r122-proc-1"
TERMINAL_ID = "term-r122-proc-1"


class R122AdapterBoundaryTests(unittest.TestCase):
    """Adapter-boundary lifecycle test across production subprocesses."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

        self.home_dir = self.root / "home"
        self.home_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir = self.root / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Mirror installed plugin directory structure
        self.package_source = Path(__file__).resolve().parents[1]
        self.installed_root = self.root / "installed_plugin"
        shutil.copytree(self.package_source, self.installed_root)

        # Stand up BridgeStub
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

        # Subprocess environment
        self.env = dict(os.environ)
        self.env["HOME"] = str(self.home_dir)
        self.env["VOICE_STATE_DIR"] = str(self.state_dir)
        self.env["HERDR_PANE_ID"] = PANE_ID
        self.env["HERDR_BIN_PATH"] = str(self.herdr_path)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

        self.identity_dict = {
            "agent_session_id": AGENT_SESSION_ID,
            "pane_id": PANE_ID,
            "terminal_id": TERMINAL_ID,
        }

    def test_r122_adapter_boundary_rejection_no_replacement_settles_fallback(
        self,
    ) -> None:
        # Configure bridge with an active binding epoch and open turn
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # ---------------------------------------------------------------------
        # Step 1: Real UserPromptSubmit hook subprocess runs
        # ---------------------------------------------------------------------
        prompt_script = (
            self.installed_root
            / "com.infiquetra.claude"
            / "hooks"
            / "user_prompt_submit_hook.py"
        )
        self.assertTrue(prompt_script.is_file())

        prompt_payload = {
            "session_id": AGENT_SESSION_ID,
            "prompt": "Operator spoken prompt transcribed by Auralis",
        }
        prompt_proc = subprocess.run(
            [sys.executable, str(prompt_script)],
            input=json.dumps(prompt_payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )
        self.assertEqual(prompt_proc.returncode, 0)
        prompt_output = json.loads(prompt_proc.stdout)
        self.assertIn(
            "This turn originated through Auralis voice.",
            prompt_output["hookSpecificOutput"]["additionalContext"],
        )

        # Verify prompt hook captured identifiers into the turn record
        rec_after_prompt = turn_record.read_turn_record(
            self.state_dir / turn_record.TURN_RECORD_FILENAME
        )
        self.assertIsNotNone(rec_after_prompt)
        assert rec_after_prompt is not None
        self.assertEqual(rec_after_prompt.session_id, AGENT_SESSION_ID)
        self.assertEqual(rec_after_prompt.binding_id, VALID_UUID_1)
        self.assertEqual(rec_after_prompt.turn_id, VALID_UUID_2)
        self.assertEqual(rec_after_prompt.origin, turn_record.ORIGIN_AURALIS)
        self.assertIsNone(rec_after_prompt.outcome)
        self.assertEqual(rec_after_prompt.submissions, [])

        # ---------------------------------------------------------------------
        # Step 2: Real MCP Server subprocess runs and rejects Markdown rendering
        # ---------------------------------------------------------------------
        server_script = self.installed_root / "scripts" / "mcp_server.py"
        self.assertTrue(server_script.is_file())

        server_proc = subprocess.Popen(
            [sys.executable, str(server_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )

        def send_and_recv(msg: dict) -> dict:
            assert server_proc.stdin is not None
            assert server_proc.stdout is not None
            server_proc.stdin.write(json.dumps(msg) + "\n")
            server_proc.stdin.flush()
            line = server_proc.stdout.readline()
            if not line:
                stderr_text = server_proc.stderr.read() if server_proc.stderr else ""
                self.fail(f"server closed stdout unexpectedly; stderr:\n{stderr_text}")
            return json.loads(line)

        # Initialize MCP session
        init_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })
        self.assertEqual(init_resp["result"]["protocolVersion"], "2024-11-05")

        # Submit Markdown formatting (R121 rejection)
        rej_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {
                    "text": "Here is the summary:\n- Item 1: **bold**\n- Item 2: `code`"
                },
            },
        })
        rej_content = json.loads(rej_resp["result"]["content"][0]["text"])
        self.assertEqual(rej_content["disposition"], "rejected_content")
        self.assertEqual(rej_content["reason"], "markdown_formatting")

        # Assert nothing reached the wire / POST /v1/rendering
        rendering_requests = [
            req for req in self.stub.requests if req.path == "/v1/rendering"
        ]
        self.assertEqual(rendering_requests, [])

        # Close MCP server
        assert server_proc.stdin is not None
        server_proc.stdin.close()
        exit_code = server_proc.wait(timeout=5.0)
        if server_proc.stdout:
            server_proc.stdout.close()
        if server_proc.stderr:
            server_proc.stderr.close()
        self.assertEqual(exit_code, 0)

        # Verify turn record contains the rejected submission
        rec_after_mcp = turn_record.read_turn_record(
            self.state_dir / turn_record.TURN_RECORD_FILENAME
        )
        self.assertIsNotNone(rec_after_mcp)
        assert rec_after_mcp is not None
        self.assertEqual(len(rec_after_mcp.submissions), 1)
        self.assertEqual(rec_after_mcp.submissions[0]["disposition"], "rejected_content")
        self.assertEqual(rec_after_mcp.submissions[0]["reason"], "markdown_formatting")

        # ---------------------------------------------------------------------
        # Step 3: No replacement is submitted. Turn completes.
        # Step 4: Real Stop hook subprocess runs
        # ---------------------------------------------------------------------
        stop_script = (
            self.installed_root
            / "com.infiquetra.claude"
            / "hooks"
            / "stop_hook.py"
        )
        self.assertTrue(stop_script.is_file())

        stop_payload = {
            "session_id": AGENT_SESSION_ID,
            "last_assistant_message": "Here is the summary:\n- Item 1: **bold**\n- Item 2: `code`",
        }
        stop_proc = subprocess.run(
            [sys.executable, str(stop_script)],
            input=json.dumps(stop_payload),
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )
        self.assertEqual(stop_proc.returncode, 0)

        # ---------------------------------------------------------------------
        # Step 5: Assert final turn record state on disk
        # ---------------------------------------------------------------------
        final_rec = turn_record.read_turn_record(
            self.state_dir / turn_record.TURN_RECORD_FILENAME
        )
        self.assertIsNotNone(final_rec)
        assert final_rec is not None
        self.assertEqual(final_rec.session_id, AGENT_SESSION_ID)
        self.assertEqual(final_rec.binding_id, VALID_UUID_1)
        self.assertEqual(final_rec.turn_id, VALID_UUID_2)
        self.assertEqual(final_rec.origin, turn_record.ORIGIN_AURALIS)
        self.assertEqual(final_rec.outcome, turn_record.OUTCOME_FALLBACK)
        self.assertEqual(len(final_rec.submissions), 1)
        self.assertEqual(final_rec.submissions[0]["disposition"], "rejected_content")

        # Verify no local speak payload files were spawned
        speak_files = list(self.state_dir.glob("speak-*.json"))
        self.assertEqual(speak_files, [])

    def test_r122_adapter_boundary_rejection_then_resubmission_settles_authored(
        self,
    ) -> None:
        self.stub.set_binding(VALID_UUID_1, self.identity_dict)
        self.stub.set_turn(VALID_UUID_2, VALID_UUID_1, state="open")

        # 1. Prompt hook
        prompt_script = (
            self.installed_root
            / "com.infiquetra.claude"
            / "hooks"
            / "user_prompt_submit_hook.py"
        )
        subprocess.run(
            [sys.executable, str(prompt_script)],
            input=json.dumps({"session_id": AGENT_SESSION_ID, "prompt": "Prompt"}),
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )

        # 2. MCP Server: reject Markdown, then accept plain text resubmission
        server_script = self.installed_root / "scripts" / "mcp_server.py"
        server_proc = subprocess.Popen(
            [sys.executable, str(server_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=self.env,
        )

        def send_and_recv(msg: dict) -> dict:
            assert server_proc.stdin is not None
            assert server_proc.stdout is not None
            server_proc.stdin.write(json.dumps(msg) + "\n")
            server_proc.stdin.flush()
            line = server_proc.stdout.readline()
            return json.loads(line)

        send_and_recv({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        })

        # Rejected call
        rej_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "# Title with markdown"},
            },
        })
        rej_content = json.loads(rej_resp["result"]["content"][0]["text"])
        self.assertEqual(rej_content["disposition"], "rejected_content")

        # Accepted resubmission
        acc_resp = send_and_recv({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "submit_spoken_rendering",
                "arguments": {"text": "Title with plain spoken text."},
            },
        })
        acc_content = json.loads(acc_resp["result"]["content"][0]["text"])
        self.assertEqual(acc_content["disposition"], "accepted")

        # Close server
        assert server_proc.stdin is not None
        server_proc.stdin.close()
        server_proc.wait(timeout=5.0)
        if server_proc.stdout:
            server_proc.stdout.close()
        if server_proc.stderr:
            server_proc.stderr.close()

        # 3. Stop hook
        stop_script = (
            self.installed_root
            / "com.infiquetra.claude"
            / "hooks"
            / "stop_hook.py"
        )
        subprocess.run(
            [sys.executable, str(stop_script)],
            input=json.dumps({
                "session_id": AGENT_SESSION_ID,
                "last_assistant_message": "Title with plain spoken text.",
            }),
            capture_output=True,
            text=True,
            env=self.env,
            check=True,
        )

        # 4. Assert final outcome is authored
        final_rec = turn_record.read_turn_record(
            self.state_dir / turn_record.TURN_RECORD_FILENAME
        )
        self.assertIsNotNone(final_rec)
        assert final_rec is not None
        self.assertEqual(final_rec.outcome, turn_record.OUTCOME_AUTHORED)
        self.assertEqual(len(final_rec.submissions), 2)
        self.assertEqual(final_rec.submissions[0]["disposition"], "rejected_content")
        self.assertEqual(final_rec.submissions[1]["disposition"], "accepted")


if __name__ == "__main__":
    unittest.main()
