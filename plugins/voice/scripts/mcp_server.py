#!/usr/bin/env python3
"""MCP stdio server exposing submit_spoken_rendering and presence lifecycle (U3; R20, R21, R121, R122; KTD1, KTD2, KTD4, KTD8, KTD11).

This module implements the adapter's long-lived Model Context Protocol (MCP)
stdio server in the Claude Code process space:
1. Exposes the single `submit_spoken_rendering` tool with a closed `{text: string}`
   input schema over newline-delimited JSON-RPC 2.0 stdio framing (KTD8);
2. Evaluates candidate rendering text against the R121 plain-spoken-text gate
   before anything reaches the wire (KTD1);
3. Forwards plain text byte-identical to `POST /v1/rendering` using the
   prompt-time captured identifier pair from the turn record (R20, KTD4);
4. Relays Core's adjudication vocabulary verbatim, including lost-response
   reconciliation (KTD1, §8);
5. Writes all submissions and dispositions to the turn record through
   `turn_record.mutate` (KTD11);
6. Runs the background presence registration and renewal lifecycle over
   `PUT /v1/presence` and `DELETE /v1/presence` (KTD2).
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_PACKAGE_SCRIPTS = Path(__file__).resolve().parent
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import adapter_identity
import bridge_client
import rendering_gate
import turn_record
from adapter_identity import AdapterIdentity, IdentityRefusal, resolve_adapter_identity
from bridge_client import (
    BridgeClient,
    BridgeError,
    BridgeTransportError,
    BridgeUnauthorized,
    BridgeUnavailable,
    RenderingResponse,
)
from turn_record import (
    TurnRecord,
    TurnRecordBusy,
    TurnRecordSessionMismatch,
    mutate,
    read_turn_record,
    record_submission,
)

__all__ = [
    "MCPServer",
    "PresenceWorker",
    "main",
    "run_server",
]


class PresenceWorker:
    """Background worker managing presence registration, lease renewal, and deletion (KTD2; §6.2, §6.3)."""

    def __init__(
        self,
        bridge_client_instance: BridgeClient | None = None,
        identity_resolver: Callable[[], AdapterIdentity] = resolve_adapter_identity,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bridge_client = bridge_client_instance or BridgeClient()
        self.identity_resolver = identity_resolver
        self.clock = clock
        self.sleep = sleep
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.registered_identity: AdapterIdentity | None = None
        self.registration_count = 0
        self.renewal_count = 0

    def start(self) -> PresenceWorker:
        """Start the presence background thread."""
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the presence loop to stop and perform best-effort DELETE /v1/presence."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        else:
            self.delete_presence()

    def tick(self) -> bool:
        """Perform one synchronous registration/renewal iteration (for testing)."""
        try:
            identity = self.identity_resolver()
        except IdentityRefusal:
            self.registered_identity = None
            return False

        try:
            resp = self.bridge_client.put_presence(identity)
            if self.registered_identity != identity:
                self.registered_identity = identity
                self.registration_count += 1
            else:
                self.renewal_count += 1
            return True
        except BridgeUnauthorized:
            self.bridge_client.reset_connection()
            return False
        except (BridgeUnavailable, BridgeTransportError, BridgeError, OSError):
            return False
        except Exception:
            return False

    def delete_presence(self) -> bool:
        """Send best-effort DELETE /v1/presence on shutdown."""
        if self.registered_identity is not None:
            try:
                self.bridge_client.delete_presence(self.registered_identity)
                self.registered_identity = None
                return True
            except Exception:
                return False
        return False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                identity = self.identity_resolver()
            except IdentityRefusal:
                self.registered_identity = None
                if self._stop_event.wait(1.0):
                    break
                continue

            try:
                resp = self.bridge_client.put_presence(identity)
                if self.registered_identity != identity:
                    self.registered_identity = identity
                    self.registration_count += 1
                else:
                    self.renewal_count += 1

                renew_seconds = max(0.05, resp.renew_after_ms / 1000.0)
                if self._stop_event.wait(renew_seconds):
                    break
            except BridgeUnauthorized:
                self.bridge_client.reset_connection()
                if self._stop_event.wait(1.0):
                    break
            except (BridgeUnavailable, BridgeTransportError, BridgeError, OSError):
                if self._stop_event.wait(1.0):
                    break
            except Exception:
                if self._stop_event.wait(1.0):
                    break

        self.delete_presence()


class MCPServer:
    """MCP stdio server exposing submit_spoken_rendering (KTD8)."""

    def __init__(
        self,
        *,
        stdin: io.TextIOBase | Any = sys.stdin,
        stdout: io.TextIOBase | Any = sys.stdout,
        bridge_client_instance: BridgeClient | None = None,
        identity_resolver: Callable[[], AdapterIdentity] = resolve_adapter_identity,
        turn_record_path: Path | None = None,
        turn_record_reader: Callable[..., TurnRecord | None] | None = None,
        presence_worker: PresenceWorker | None = None,
        enable_presence: bool = True,
    ) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.bridge_client = bridge_client_instance or BridgeClient()
        self.identity_resolver = identity_resolver
        self.turn_record_path = turn_record_path
        if turn_record_reader is not None:
            self.turn_record_reader = turn_record_reader
        else:
            self.turn_record_reader = lambda: read_turn_record(self.turn_record_path)
        self.enable_presence = enable_presence
        if presence_worker is not None:
            self.presence_worker = presence_worker
        elif enable_presence:
            self.presence_worker = PresenceWorker(
                bridge_client_instance=self.bridge_client,
                identity_resolver=self.identity_resolver,
            )
        else:
            self.presence_worker = None

    def _execute_submit_spoken_rendering(self, text: str) -> dict[str, Any]:
        # 1. Resolve identity (§5)
        try:
            identity = self.identity_resolver()
        except IdentityRefusal:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "not_bound"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

        # 2. Read turn record (KTD4)
        record = self.turn_record_reader()
        if (
            record is None
            or record.binding_id is None
            or record.turn_id is None
            or record.session_id != identity.agent_session_id
        ):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "no_current_turn"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

        # 3. Gate candidate text (R121, KTD1)
        verdict = rendering_gate.evaluate(text)
        if not verdict.is_plain:
            detail = verdict.detail
            try:
                record_submission(
                    session_id=record.session_id,
                    text=text,
                    disposition="rejected_content",
                    reason=verdict.reason,
                    detail=detail,
                    path=self.turn_record_path,
                )
            except TurnRecordBusy:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"disposition": "unavailable", "reason": "turn_record_busy"},
                                sort_keys=True,
                            ),
                        }
                    ],
                    "isError": False,
                }
            except Exception:
                pass

            payload: dict[str, Any] = {
                "disposition": "rejected_content",
                "reason": verdict.reason,
            }
            if detail is not None:
                payload["detail"] = detail

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, sort_keys=True),
                    }
                ],
                "isError": False,
            }

        # 4. Forward plain text byte-identical to Core (§6.5, R20)
        try:
            resp = self.bridge_client.submit_rendering(
                identity=identity,
                binding_id=record.binding_id,
                turn_id=record.turn_id,
                text=text,
            )
        except BridgeUnavailable:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "bridge_unavailable"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }
        except BridgeUnauthorized:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "bridge_unavailable"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }
        except (BridgeTransportError, BridgeError, OSError):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "transport_error"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }
        except Exception:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "transport_error"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

        if resp.disposition == "accepted":
            detail_str = resp.detail or "accepted"
            try:
                record_submission(
                    session_id=record.session_id,
                    text=text,
                    disposition="accepted",
                    detail={"detail": detail_str} if detail_str != "accepted" else None,
                    path=self.turn_record_path,
                )
            except TurnRecordBusy:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"disposition": "unavailable", "reason": "turn_record_busy"},
                                sort_keys=True,
                            ),
                        }
                    ],
                    "isError": False,
                }
            except Exception:
                pass

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"detail": detail_str, "disposition": "accepted"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

        elif resp.disposition == "rejected":
            try:
                record_submission(
                    session_id=record.session_id,
                    text=text,
                    disposition="rejected_by_core",
                    reason=resp.reason,
                    path=self.turn_record_path,
                )
            except TurnRecordBusy:
                return {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"disposition": "unavailable", "reason": "turn_record_busy"},
                                sort_keys=True,
                            ),
                        }
                    ],
                    "isError": False,
                }
            except Exception:
                pass

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "rejected_by_core", "reason": resp.reason},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"disposition": "unavailable", "reason": "transport_error"},
                            sort_keys=True,
                        ),
                    }
                ],
                "isError": False,
            }

    def handle_line(self, line: str) -> str | None:
        """Handle one input line of JSON-RPC 2.0 framing."""
        raw = line.strip()
        if not raw:
            return None

        try:
            req = json.loads(raw)
        except Exception:
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            })

        if not isinstance(req, dict):
            return json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            })

        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params")
        is_notification = "id" not in req

        if method == "initialize":
            client_version = params.get("protocolVersion") if isinstance(params, dict) else None
            supported_versions = {"2024-11-05", "2024-10-07", "latest"}
            protocol_version = client_version if client_version in supported_versions else "2024-11-05"
            result = {
                "protocolVersion": protocol_version,
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "auralis-voice",
                    "version": "0.3.0",
                },
            }
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}})

        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "submit_spoken_rendering",
                        "description": (
                            "Submit an authored spoken rendering for the current Auralis voice turn. "
                            "Accepts plain spoken text only; Markdown formatting and fenced code blocks are rejected."
                        ),
                        "inputSchema": {
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
                    }
                ]
            }
            return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

        elif method == "tools/call":
            if not isinstance(params, dict):
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: params must be an object"},
                })
            tool_name = params.get("name")
            arguments = params.get("arguments")
            if tool_name != "submit_spoken_rendering":
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name!r}"},
                })
            if not isinstance(arguments, dict) or "text" not in arguments or not isinstance(arguments["text"], str):
                return json.dumps({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Invalid params: arguments.text string required"},
                })

            tool_result = self._execute_submit_spoken_rendering(arguments["text"])
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": tool_result,
            })

        else:
            if is_notification:
                return None
            return json.dumps({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method!r}"},
            })

    def serve(self) -> int:
        """Run the server loop on self.stdin and self.stdout until EOF."""
        if self.enable_presence and self.presence_worker:
            self.presence_worker.start()

        try:
            while True:
                line = self.stdin.readline()
                if not line:
                    break
                response_line = self.handle_line(line)
                if response_line is not None:
                    self.stdout.write(response_line + "\n")
                    self.stdout.flush()
        except (KeyboardInterrupt, BrokenPipeError):
            pass
        finally:
            if self.presence_worker:
                self.presence_worker.stop()

        return 0


def run_server(
    stdin: io.TextIOBase | Any = sys.stdin,
    stdout: io.TextIOBase | Any = sys.stdout,
    *,
    bridge_client_instance: BridgeClient | None = None,
    identity_resolver: Callable[[], AdapterIdentity] = resolve_adapter_identity,
    enable_presence: bool = True,
) -> int:
    """Run the MCP server instance."""
    server = MCPServer(
        stdin=stdin,
        stdout=stdout,
        bridge_client_instance=bridge_client_instance,
        identity_resolver=identity_resolver,
        enable_presence=enable_presence,
    )
    return server.serve()


def main(argv: list[str] | None = None) -> int:
    """Entrypoint for `python3 scripts/mcp_server.py`."""
    return run_server()


if __name__ == "__main__":
    sys.exit(main())
