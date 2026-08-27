"""Independent-literals bridge HTTP server stub for tests (KTD9; §6, §7).

This module is the single shared stub fixture for all bridge-facing tests:
U1 client tests, U3 server tests, U4 hook tests, and the U4 adapter-boundary
scenario. Wire literals live here and in ``bridge_client.py`` only.

Runs a stdlib ``http.server.HTTPServer`` on loopback (127.0.0.1) with an
ephemeral port, speaks the exact literals of ``docs/bridge-v1-from-c10.md``,
records incoming requests, and allows fault injection (custom statuses, dropped
connections, clock/timing simulation).
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "BridgeStub",
    "CapturedRequest",
    "DEFAULT_STUB_TOKEN",
]

#: A valid 43-character unpadded base64url token for tests.
DEFAULT_STUB_TOKEN = "test_token_43_chars_base64url_alphabet_0123"

_UUID_V4_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@dataclass
class CapturedRequest:
    """A record of one HTTP request received by the bridge stub."""

    method: str
    path: str
    headers: dict[str, str]
    body: dict[str, Any] | None
    raw_body: bytes


class _BridgeHTTPRequestHandler(BaseHTTPRequestHandler):
    server: _StubHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard logging to keep test output clean
        pass

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body_bytes = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body_bytes)

    def _send_transport_error(
        self,
        status: int,
        error_code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._send_json(status, {"schema": 1, "error": error_code}, headers=headers)

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def _handle_request(self, method: str) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        raw_query = parsed_url.query

        content_length_str = self.headers.get("Content-Length", "0")
        try:
            content_length = int(content_length_str)
        except ValueError:
            content_length = 0

        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        # Record captured request
        body_json: dict[str, Any] | None = None
        if raw_body:
            try:
                body_json = json.loads(raw_body.decode("utf-8"))
            except Exception:
                body_json = None

        captured = CapturedRequest(
            method=method,
            path=self.path,
            headers=dict(self.headers),
            body=body_json,
            raw_body=raw_body,
        )
        self.server.stub.requests.append(captured)

        # Check explicit path error override
        if path in self.server.stub.path_status_overrides:
            status, error_code = self.server.stub.path_status_overrides[path]
            if status == 200:
                self._send_json(200, {"schema": 1, "status": "ok"})
            else:
                self._send_transport_error(status, error_code)
            return

        # Processing precedence (§7):
        # 1. Path matching: non-existent path -> 404 not_found
        valid_paths = {"/v1/health", "/v1/current", "/v1/presence", "/v1/rendering"}
        if path not in valid_paths:
            self._send_transport_error(404, "not_found")
            return

        # 2. Method matching: disallowed method -> 405 method_not_allowed with Allow header
        allowed_methods = {
            "/v1/health": ["GET"],
            "/v1/current": ["GET"],
            "/v1/presence": ["PUT", "DELETE"],
            "/v1/rendering": ["POST"],
        }
        if method not in allowed_methods[path]:
            allow_header = ", ".join(allowed_methods[path])
            self._send_transport_error(405, "method_not_allowed", headers={"Allow": allow_header})
            return

        # 3. Authentication: Missing or invalid Bearer token -> 401 unauthorized
        auth_header = self.headers.get("Authorization", "")
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer" or parts[1] != self.server.stub.token:
            self._send_transport_error(401, "unauthorized")
            return

        # 4. HTTP version and query string
        if raw_query:
            self._send_transport_error(400, "invalid_request")
            return

        # 5. GET-body prohibition / Media type
        if method == "GET":
            if content_length > 0 or raw_body:
                self._send_transport_error(400, "invalid_request")
                return
        else:
            content_type = self.headers.get("Content-Type", "")
            media_type = content_type.split(";")[0].strip().lower()
            if media_type != "application/json":
                self._send_transport_error(415, "unsupported_media_type")
                return

        # 6. Body size cap (> 1 MiB -> 413 body_too_large)
        if len(raw_body) > 1048576:
            self._send_transport_error(413, "body_too_large")
            return

        # For body-bearing requests, validate JSON decoding and schema
        if method in {"PUT", "DELETE", "POST"}:
            if not raw_body:
                self._send_transport_error(400, "invalid_json")
                return
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except Exception:
                self._send_transport_error(400, "invalid_json")
                return

            if not isinstance(payload, dict):
                self._send_transport_error(400, "invalid_json")
                return

            # 8. Schema validation
            schema_val = payload.get("schema")
            if type(schema_val) is not int:
                self._send_transport_error(400, "invalid_request")
                return
            if schema_val != 1:
                self._send_transport_error(400, "unsupported_schema")
                return

            # Execute Endpoint
            if path == "/v1/presence" and method == "PUT":
                self._handle_put_presence(payload)
                return
            elif path == "/v1/presence" and method == "DELETE":
                self._handle_delete_presence(payload)
                return
            elif path == "/v1/rendering" and method == "POST":
                self._handle_post_rendering(payload)
                return

        elif method == "GET":
            if path == "/v1/health":
                self._handle_get_health()
                return
            elif path == "/v1/current":
                self._handle_get_current()
                return

    def _validate_identity_dict(self, identity: Any) -> bool:
        if not isinstance(identity, dict):
            return False
        expected_keys = {"agent_session_id", "pane_id", "terminal_id"}
        if set(identity.keys()) != expected_keys:
            return False
        for k in expected_keys:
            v = identity.get(k)
            if not isinstance(v, str) or not v.strip():
                return False
        return True

    def _handle_get_health(self) -> None:
        self._send_json(
            200,
            {
                "schema": 1,
                "service": "auralis-bridge",
                "status": self.server.stub.health_status,
            },
        )

    def _handle_put_presence(self, payload: dict[str, Any]) -> None:
        if set(payload.keys()) != {"schema", "identity"}:
            self._send_transport_error(400, "invalid_request")
            return
        identity = payload.get("identity")
        if not self._validate_identity_dict(identity):
            self._send_transport_error(400, "invalid_request")
            return

        self._send_json(
            200,
            {
                "schema": 1,
                "disposition": self.server.stub.presence_disposition,
                "lease_ms": self.server.stub.lease_ms,
                "renew_after_ms": self.server.stub.renew_after_ms,
            },
        )

    def _handle_delete_presence(self, payload: dict[str, Any]) -> None:
        if set(payload.keys()) != {"schema", "identity"}:
            self._send_transport_error(400, "invalid_request")
            return
        identity = payload.get("identity")
        if not self._validate_identity_dict(identity):
            self._send_transport_error(400, "invalid_request")
            return

        self._send_json(
            200,
            {
                "schema": 1,
                "disposition": self.server.stub.presence_delete_disposition,
            },
        )

    def _handle_get_current(self) -> None:
        binding = self.server.stub.current_binding
        turn = self.server.stub.current_turn
        self._send_json(
            200,
            {
                "schema": 1,
                "binding": binding,
                "turn": turn,
            },
        )

    def _handle_post_rendering(self, payload: dict[str, Any]) -> None:
        expected_keys = {"schema", "identity", "binding_id", "turn_id", "text"}
        if set(payload.keys()) != expected_keys:
            self._send_transport_error(400, "invalid_request")
            return

        identity = payload.get("identity")
        if not self._validate_identity_dict(identity):
            self._send_transport_error(400, "invalid_request")
            return

        binding_id = payload.get("binding_id")
        turn_id = payload.get("turn_id")
        text = payload.get("text")

        if not isinstance(binding_id, str) or not isinstance(turn_id, str) or not isinstance(text, str):
            self._send_transport_error(400, "invalid_request")
            return

        # Adjudication order (§6.5):
        stub = self.server.stub

        # 1. no_binding
        if stub.current_binding is None:
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "no_binding",
                },
            )
            return

        # 2. binding_not_current
        if binding_id != stub.current_binding.get("binding_id"):
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "binding_not_current",
                },
            )
            return

        # 3. adapter_not_bound
        if identity != stub.current_binding.get("identity"):
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "adapter_not_bound",
                },
            )
            return

        # 4. turn_not_current
        if stub.current_turn is None or turn_id != stub.current_turn.get("turn_id"):
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "turn_not_current",
                },
            )
            return

        # 5. turn_canceled
        if stub.current_turn.get("state") == "canceled":
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "turn_canceled",
                },
            )
            return

        # 6. fallback_already_began
        if stub.current_turn.get("state") == "fallback_accepted":
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "fallback_already_began",
                },
            )
            return

        # 7. duplicate_rendering
        if stub.current_turn.get("state") == "authored_accepted":
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "duplicate_rendering",
                },
            )
            return

        # 8. empty_rendering
        if not text.strip():
            self._send_json(
                200,
                {
                    "schema": 1,
                    "binding_id": binding_id,
                    "turn_id": turn_id,
                    "disposition": "rejected",
                    "reason": "empty_rendering",
                },
            )
            return

        # 9. Accepted
        stub.current_turn["state"] = "authored_accepted"
        if stub.drop_rendering_responses_count > 0:
            stub.drop_rendering_responses_count -= 1
            self.close_connection = True
            return

        self._send_json(
            200,
            {
                "schema": 1,
                "binding_id": binding_id,
                "turn_id": turn_id,
                "disposition": "accepted",
            },
        )


class _StubHTTPServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], stub: BridgeStub) -> None:
        self.stub = stub
        super().__init__(server_address, _BridgeHTTPRequestHandler)


class BridgeStub:
    """The test stub HTTP server implementing the Auralis Bridge Contract v1."""

    def __init__(
        self,
        token: str = DEFAULT_STUB_TOKEN,
        *,
        host: str = "127.0.0.1",
    ) -> None:
        self.token = token
        self.host = host
        self.port = 0
        self.health_status = "ok"
        self.presence_disposition = "present"
        self.lease_ms = 15000
        self.renew_after_ms = 5000
        self.presence_delete_disposition = "absent"
        self.current_binding: dict[str, Any] | None = None
        self.current_turn: dict[str, Any] | None = None
        self.drop_rendering_responses_count = 0
        self.path_status_overrides: dict[str, tuple[int, str]] = {}
        self.requests: list[CapturedRequest] = []

        self._server: _StubHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> BridgeStub:
        """Start the stub HTTP server on a background thread."""
        self._server = _StubHTTPServer((self.host, 0), self)
        self.port = self._server.server_port
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        """Shut down the stub HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self) -> BridgeStub:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def set_binding(self, binding_id: str, identity: dict[str, str]) -> None:
        self.current_binding = {
            "binding_id": binding_id,
            "identity": dict(identity),
        }

    def clear_binding(self) -> None:
        self.current_binding = None
        self.current_turn = None

    def set_turn(self, turn_id: str, binding_id: str, state: str = "open") -> None:
        self.current_turn = {
            "turn_id": turn_id,
            "binding_id": binding_id,
            "state": state,
        }

    def clear_turn(self) -> None:
        self.current_turn = None

    def drop_next_rendering_response(self) -> None:
        self.drop_rendering_responses_count += 1

    def write_discovery_file(
        self,
        dest_path_or_dir: Path | str,
        *,
        mode: int = 0o600,
        schema: int = 1,
        host: str | None = None,
        port: int | None = None,
        token: str | None = None,
        extra_keys: dict[str, Any] | None = None,
    ) -> Path:
        """Write a discovery bridge.json file pointing to this stub."""
        target = Path(dest_path_or_dir)
        if target.is_dir() or target.suffix != ".json":
            file_path = target / "bridge.json"
        else:
            file_path = target

        file_path.parent.mkdir(parents=True, exist_ok=True)

        payload: dict[str, Any] = {
            "schema": schema,
            "host": host if host is not None else self.host,
            "port": port if port is not None else self.port,
            "token": token if token is not None else self.token,
        }
        if extra_keys:
            payload.update(extra_keys)

        file_path.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(file_path, mode)
        return file_path
