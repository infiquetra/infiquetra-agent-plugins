"""Bridge wire client for the Auralis Local Bridge v1 (portable core; §2–§8).

Implements the five frozen routes, discovery, authentication, timeout budget,
identifier grammar validation, transport error mapping, and retry/lost-response
reconciliation for the Auralis Bridge Contract v1.

Standard library only: ``http.client``, ``json``, ``time``, ``os``, ``re``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adapter_identity import AdapterIdentity

__all__ = [
    "BridgeConnection",
    "HealthResponse",
    "PresenceResponse",
    "PresenceDeleteResponse",
    "BindingEpoch",
    "TurnSnapshot",
    "CurrentSnapshot",
    "RenderingResponse",
    "ApprovalResponse",
    "BridgeError",
    "BridgeUnavailable",
    "BridgeUnauthorized",
    "BridgeTransportError",
    "DEFAULT_BRIDGE_FILE",
    "CONNECT_TIMEOUT_SECONDS",
    "HEALTH_TIMEOUT_SECONDS",
    "CURRENT_TIMEOUT_SECONDS",
    "PRESENCE_TIMEOUT_SECONDS",
    "RENDERING_TIMEOUT_SECONDS",
    "APPROVAL_TIMEOUT_SECONDS",
    "read_discovery",
    "BridgeClient",
]

DEFAULT_BRIDGE_FILE = Path("~/Library/Application Support/Auralis/bridge.json")

# Timeout budget table constants (seconds)
CONNECT_TIMEOUT_SECONDS = 0.250
HEALTH_TIMEOUT_SECONDS = 1.000
CURRENT_TIMEOUT_SECONDS = 1.000
PRESENCE_TIMEOUT_SECONDS = 2.000
RENDERING_TIMEOUT_SECONDS = 2.000
APPROVAL_TIMEOUT_SECONDS = 55.000

_TOKEN_REGEX = re.compile(r"^[A-Za-z0-9_-]{43}$")
_UUID_V4_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_VALID_TURN_STATES = {"open", "authored_accepted", "fallback_accepted", "canceled"}
_VALID_REJECTION_REASONS = {
    "no_binding",
    "binding_not_current",
    "adapter_not_bound",
    "turn_not_current",
    "turn_canceled",
    "fallback_already_began",
    "duplicate_rendering",
    "empty_rendering",
}
_VALID_ERROR_CODES = {
    "invalid_json",
    "invalid_request",
    "unsupported_schema",
    "unauthorized",
    "not_found",
    "method_not_allowed",
    "body_too_large",
    "unsupported_media_type",
    "internal_error",
}


class BridgeError(Exception):
    """Base exception for all bridge operations."""


class BridgeUnavailable(BridgeError):
    """The bridge is unavailable (discovery failed, connection refused, or unreadable)."""


class BridgeUnauthorized(BridgeError):
    """The bridge returned 401 Unauthorized (credentials invalid or rotated)."""


class BridgeTransportError(BridgeError):
    """A transport or contract-level protocol error occurred."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


@dataclass(frozen=True)
class BridgeConnection:
    """Connection parameters discovered from bridge.json (§2)."""

    host: str
    port: int
    token: str
    schema: int = 1


@dataclass(frozen=True)
class HealthResponse:
    """Response from GET /v1/health (§6.1)."""

    service: str
    status: str
    schema: int = 1


@dataclass(frozen=True)
class PresenceResponse:
    """Response from PUT /v1/presence (§6.2)."""

    disposition: str
    lease_ms: int
    renew_after_ms: int
    schema: int = 1


@dataclass(frozen=True)
class PresenceDeleteResponse:
    """Response from DELETE /v1/presence (§6.3)."""

    disposition: str
    schema: int = 1


@dataclass(frozen=True)
class BindingEpoch:
    """An active binding epoch from GET /v1/current (§6.4)."""

    binding_id: str
    identity: AdapterIdentity


@dataclass(frozen=True)
class TurnSnapshot:
    """An active turn snapshot from GET /v1/current (§6.4)."""

    turn_id: str
    binding_id: str
    state: str


@dataclass(frozen=True)
class CurrentSnapshot:
    """Response from GET /v1/current (§6.4)."""

    binding: BindingEpoch | None
    turn: TurnSnapshot | None
    schema: int = 1


@dataclass(frozen=True)
class RenderingResponse:
    """Response from POST /v1/rendering (§6.5)."""

    disposition: str  # "accepted" or "rejected"
    binding_id: str
    turn_id: str
    reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ApprovalResponse:
    """Response from POST /v1/approval."""

    tool_use_id: str
    decision: str  # "allow" or "defer"
    reason: str
    snapshot: dict[str, Any] | None = None
    schema: int = 1


def read_discovery(bridge_file: Path | str | None = None) -> BridgeConnection:
    """Read and strictly validate the discovery bridge.json file (§2).

    Must have file mode 0600, exact 4 keys (schema, host, port, token),
    schema=1, host='127.0.0.1', valid TCP port, and 43-character unpadded
    base64url token. Any deviation raises BridgeUnavailable.
    """
    path = Path(bridge_file).expanduser() if bridge_file is not None else DEFAULT_BRIDGE_FILE.expanduser()

    if not path.exists():
        raise BridgeUnavailable(f"bridge.json does not exist: {path}")

    try:
        st = path.stat()
    except OSError as err:
        raise BridgeUnavailable(f"cannot stat bridge.json: {err}") from err

    # Permissions check: mode 0600 (owner read/write only)
    if (st.st_mode & 0o777) != 0o600:
        raise BridgeUnavailable(
            f"bridge.json file mode is {oct(st.st_mode & 0o777)}, expected 0600"
        )

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except Exception as err:
        raise BridgeUnavailable(f"cannot read or parse bridge.json: {err}") from err

    if not isinstance(data, dict):
        raise BridgeUnavailable("bridge.json content is not a JSON object")

    expected_keys = {"schema", "host", "port", "token"}
    if set(data.keys()) != expected_keys:
        raise BridgeUnavailable(
            f"bridge.json keys {set(data.keys())} do not match exact required keys {expected_keys}"
        )

    schema_val = data.get("schema")
    if type(schema_val) is not int or schema_val != 1:
        raise BridgeUnavailable(f"bridge.json schema must be integer 1, got {schema_val!r}")

    host_val = data.get("host")
    if host_val != "127.0.0.1":
        raise BridgeUnavailable(f"bridge.json host must be '127.0.0.1', got {host_val!r}")

    port_val = data.get("port")
    if type(port_val) is not int or not (1 <= port_val <= 65535):
        raise BridgeUnavailable(f"bridge.json port must be integer 1..65535, got {port_val!r}")

    token_val = data.get("token")
    if not isinstance(token_val, str) or not _TOKEN_REGEX.fullmatch(token_val):
        raise BridgeUnavailable(
            "bridge.json token must be exactly 43 unpadded base64url characters"
        )

    return BridgeConnection(
        host=host_val,
        port=port_val,
        token=token_val,
        schema=1,
    )


def _validate_uuid_v4(val: Any, field_name: str) -> str:
    """Validate that val is a lowercase UUIDv4 string (§8)."""
    if not isinstance(val, str):
        raise BridgeUnavailable(f"{field_name} must be a string, got {type(val).__name__}")
    if val != val.lower():
        raise BridgeUnavailable(f"{field_name} must be lowercase UUIDv4, got {val!r}")
    if not _UUID_V4_REGEX.fullmatch(val):
        raise BridgeUnavailable(f"{field_name} is not a valid UUIDv4 string, got {val!r}")
    return val


class BridgeClient:
    """The HTTP client for Auralis Local Bridge v1 (§4–§8)."""

    def __init__(
        self,
        bridge_file: Path | str | None = None,
        connection: BridgeConnection | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bridge_file = bridge_file
        self._connection = connection
        self.clock = clock

    def get_connection(self) -> BridgeConnection:
        """Resolve or return the cached BridgeConnection."""
        if self._connection is None:
            self._connection = read_discovery(self.bridge_file)
        return self._connection

    def reset_connection(self) -> None:
        """Clear cached connection to force re-discovery."""
        self._connection = None

    def _request(
        self,
        method: str,
        path: str,
        body_dict: dict[str, Any] | None,
        timeout_budget: float,
        conn: BridgeConnection,
    ) -> tuple[int, dict[str, Any]]:
        """Perform one HTTP request under monotonic clock deadline discipline."""
        start_time = self.clock()
        deadline = start_time + timeout_budget

        def remaining() -> float:
            rem = deadline - self.clock()
            if rem <= 0:
                raise BridgeTransportError(
                    f"operation timed out on deadline ({timeout_budget}s budget)",
                    error_code="transport_error",
                )
            return rem

        headers = {
            "Authorization": f"Bearer {conn.token}",
        }

        body_bytes = b""
        if body_dict is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            body_bytes = json.dumps(body_dict).encode("utf-8")
            headers["Content-Length"] = str(len(body_bytes))

        # Use connect timeout for initial socket connection if within remaining budget
        initial_timeout = min(CONNECT_TIMEOUT_SECONDS, remaining())

        try:
            http_conn = http.client.HTTPConnection(
                conn.host,
                conn.port,
                timeout=initial_timeout,
            )
            # Connect explicitly
            http_conn.connect()
            # Reset timeout to remaining total deadline
            http_conn.sock.settimeout(remaining())

            http_conn.request(method, path, body=body_bytes if body_bytes else None, headers=headers)

            http_conn.sock.settimeout(remaining())
            response = http_conn.getresponse()
            status = response.status
            raw_resp_body = response.read()
            http_conn.close()
        except (socket.timeout, TimeoutError) as err:
            raise BridgeTransportError(
                f"operation timed out on deadline ({timeout_budget}s): {err}",
                error_code="transport_error",
            ) from err
        except (ConnectionRefusedError, ConnectionResetError, BrokenPipeError, socket.error, OSError) as err:
            raise BridgeTransportError(
                f"transport error during {method} {path}: {err}",
                error_code="transport_error",
            ) from err

        try:
            resp_json = json.loads(raw_resp_body.decode("utf-8"))
        except Exception as err:
            raise BridgeTransportError(
                f"malformed JSON in response from {method} {path} (status {status}): {err}",
                status_code=status,
                error_code="invalid_json",
            ) from err

        if not isinstance(resp_json, dict):
            raise BridgeTransportError(
                f"response from {method} {path} is not a JSON object",
                status_code=status,
            )

        return status, resp_json

    def get_health(self) -> HealthResponse:
        """Call GET /v1/health (§6.1)."""
        conn = self.get_connection()
        status, data = self._request(
            "GET",
            "/v1/health",
            None,
            HEALTH_TIMEOUT_SECONDS,
            conn,
        )
        if status == 401:
            self.reset_connection()
            raise BridgeUnauthorized("unauthorized health check")
        if status != 200:
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"health check returned status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        service = data.get("service")
        st = data.get("status")
        if not isinstance(service, str) or not isinstance(st, str):
            raise BridgeTransportError("health check missing required string fields")

        return HealthResponse(service=service, status=st, schema=data.get("schema", 1))

    def put_presence(self, identity: AdapterIdentity) -> PresenceResponse:
        """Call PUT /v1/presence (§6.2)."""
        conn = self.get_connection()
        body = {
            "schema": 1,
            "identity": identity.to_dict(),
        }
        status, data = self._request(
            "PUT",
            "/v1/presence",
            body,
            PRESENCE_TIMEOUT_SECONDS,
            conn,
        )
        if status == 401:
            self.reset_connection()
            raise BridgeUnauthorized("unauthorized presence registration")
        if status != 200:
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"presence PUT returned status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        disposition = data.get("disposition")
        lease_ms = data.get("lease_ms")
        renew_after_ms = data.get("renew_after_ms")

        if not isinstance(disposition, str) or type(lease_ms) is not int or type(renew_after_ms) is not int:
            raise BridgeTransportError("presence response missing or invalid required fields")

        return PresenceResponse(
            disposition=disposition,
            lease_ms=lease_ms,
            renew_after_ms=renew_after_ms,
            schema=data.get("schema", 1),
        )

    def delete_presence(self, identity: AdapterIdentity) -> PresenceDeleteResponse:
        """Call DELETE /v1/presence (§6.3)."""
        conn = self.get_connection()
        body = {
            "schema": 1,
            "identity": identity.to_dict(),
        }
        status, data = self._request(
            "DELETE",
            "/v1/presence",
            body,
            PRESENCE_TIMEOUT_SECONDS,
            conn,
        )
        if status == 401:
            self.reset_connection()
            raise BridgeUnauthorized("unauthorized presence deletion")
        if status != 200:
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"presence DELETE returned status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        disposition = data.get("disposition")
        if not isinstance(disposition, str):
            raise BridgeTransportError("presence DELETE response missing disposition")

        return PresenceDeleteResponse(disposition=disposition, schema=data.get("schema", 1))

    def get_current(self) -> CurrentSnapshot:
        """Call GET /v1/current and validate identifier grammar (§6.4, §8)."""
        conn = self.get_connection()
        status, data = self._request(
            "GET",
            "/v1/current",
            None,
            CURRENT_TIMEOUT_SECONDS,
            conn,
        )
        if status == 401:
            self.reset_connection()
            raise BridgeUnauthorized("unauthorized current snapshot read")
        if status != 200:
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"current GET returned status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        binding_raw = data.get("binding")
        turn_raw = data.get("turn")

        binding_epoch: BindingEpoch | None = None
        if binding_raw is not None:
            if not isinstance(binding_raw, dict):
                raise BridgeUnavailable("binding in current snapshot is not an object")
            b_id = _validate_uuid_v4(binding_raw.get("binding_id"), "binding_id")
            id_dict = binding_raw.get("identity")
            if not isinstance(id_dict, dict):
                raise BridgeUnavailable("identity in binding snapshot is not an object")
            sess_id = id_dict.get("agent_session_id")
            p_id = id_dict.get("pane_id")
            t_id = id_dict.get("terminal_id")
            if not isinstance(sess_id, str) or not isinstance(p_id, str) or not isinstance(t_id, str):
                raise BridgeUnavailable("identity in binding snapshot has missing or non-string components")
            binding_epoch = BindingEpoch(
                binding_id=b_id,
                identity=AdapterIdentity(
                    agent_session_id=sess_id,
                    pane_id=p_id,
                    terminal_id=t_id,
                ),
            )

        turn_snapshot: TurnSnapshot | None = None
        if turn_raw is not None:
            if binding_epoch is None:
                raise BridgeUnavailable("turn is present when binding is null in current snapshot")
            if not isinstance(turn_raw, dict):
                raise BridgeUnavailable("turn in current snapshot is not an object")
            t_id = _validate_uuid_v4(turn_raw.get("turn_id"), "turn_id")
            t_b_id = _validate_uuid_v4(turn_raw.get("binding_id"), "turn.binding_id")
            state = turn_raw.get("state")
            if state not in _VALID_TURN_STATES:
                raise BridgeUnavailable(f"turn state {state!r} is not one of {_VALID_TURN_STATES}")
            turn_snapshot = TurnSnapshot(
                turn_id=t_id,
                binding_id=t_b_id,
                state=state,
            )

        return CurrentSnapshot(
            binding=binding_epoch,
            turn=turn_snapshot,
            schema=data.get("schema", 1),
        )

    def submit_rendering(
        self,
        identity: AdapterIdentity,
        binding_id: str,
        turn_id: str,
        text: str,
    ) -> RenderingResponse:
        """Call POST /v1/rendering with retry & lost-response reconciliation (§6.5, §8)."""
        conn = self.get_connection()
        body = {
            "schema": 1,
            "identity": identity.to_dict(),
            "binding_id": binding_id,
            "turn_id": turn_id,
            "text": text,
        }

        # Attempt 1
        server_error_500 = False
        lost_response = False
        status = 0
        data: dict[str, Any] = {}

        try:
            status, data = self._request(
                "POST",
                "/v1/rendering",
                body,
                RENDERING_TIMEOUT_SECONDS,
                conn,
            )
        except BridgeTransportError as err:
            if err.status_code == 500:
                server_error_500 = True
            elif err.status_code is not None:
                # Received an HTTP response with a status code (e.g. 4xx client error, invalid JSON).
                # Section 8: 4xx Client Errors must not be retried without correcting the request or contract violation.
                raise
            else:
                # No response status received: transport error / network failure before response -> lost response
                lost_response = True

        if not (server_error_500 or lost_response):
            if status == 200:
                return self._parse_rendering_200(data, is_retry=False)
            if status == 401:
                self.reset_connection()
                raise BridgeUnauthorized("unauthorized rendering submission")
            if status == 500:
                server_error_500 = True
            else:
                # 4xx client error or other status (§8: must not be retried)
                err_code = data.get("error", "unknown_error")
                raise BridgeTransportError(
                    f"rendering submission rejected: status {status}, code {err_code}",
                    status_code=status,
                    error_code=err_code,
                )

        # Retry logic per §8
        if server_error_500:
            # Confirm health first per §8
            try:
                health = self.get_health()
                if health.status != "ok":
                    raise BridgeTransportError(
                        f"500 Internal Error and health check reported status {health.status!r}",
                        status_code=500,
                        error_code="internal_error",
                    )
            except Exception as health_err:
                raise BridgeTransportError(
                    f"500 Internal Error and health check failed: {health_err}",
                    status_code=500,
                    error_code="internal_error",
                ) from health_err

            # One byte-identical retry
            try:
                status, data = self._request(
                    "POST",
                    "/v1/rendering",
                    body,
                    RENDERING_TIMEOUT_SECONDS,
                    conn,
                )
            except BridgeTransportError as retry_err:
                raise BridgeTransportError(
                    f"rendering retry after 500 failed: {retry_err}",
                    status_code=retry_err.status_code or 500,
                    error_code=retry_err.error_code or "internal_error",
                ) from retry_err

            if status == 200:
                return self._parse_rendering_200(data, is_retry=False)
            if status == 401:
                self.reset_connection()
                raise BridgeUnauthorized("unauthorized rendering submission on retry")
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"rendering retry after 500 failed with status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        if lost_response:
            # Single byte-equivalent retry for lost rendering response (§8; F8)
            try:
                status, data = self._request(
                    "POST",
                    "/v1/rendering",
                    body,
                    RENDERING_TIMEOUT_SECONDS,
                    conn,
                )
            except BridgeTransportError as retry_err:
                raise BridgeTransportError(
                    f"rendering submission failed and retry also failed: {retry_err}",
                    status_code=retry_err.status_code,
                    error_code=retry_err.error_code or "transport_error",
                ) from retry_err

            if status == 200:
                return self._parse_rendering_200(data, is_retry=True)
            if status == 401:
                self.reset_connection()
                raise BridgeUnauthorized("unauthorized rendering submission on retry")
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"rendering retry after lost response failed with status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        raise BridgeTransportError("unexpected rendering submission state")

    def _parse_rendering_200(self, data: dict[str, Any], *, is_retry: bool) -> RenderingResponse:
        b_id = data.get("binding_id")
        t_id = data.get("turn_id")
        disp = data.get("disposition")
        reason = data.get("reason")

        if not isinstance(b_id, str) or not isinstance(t_id, str) or not isinstance(disp, str):
            raise BridgeTransportError("rendering response missing required fields")

        if disp == "accepted":
            return RenderingResponse(
                disposition="accepted",
                binding_id=b_id,
                turn_id=t_id,
                detail="accepted",
            )
        elif disp == "rejected":
            if reason not in _VALID_REJECTION_REASONS:
                raise BridgeTransportError(f"unknown rendering rejection reason: {reason!r}")

            # Lost-response reconciliation (F8 / §8):
            if is_retry and reason == "duplicate_rendering":
                return RenderingResponse(
                    disposition="accepted",
                    binding_id=b_id,
                    turn_id=t_id,
                    detail="accepted_on_retry",
                )

            return RenderingResponse(
                disposition="rejected",
                binding_id=b_id,
                turn_id=t_id,
                reason=reason,
            )
        else:
            raise BridgeTransportError(f"unknown rendering disposition: {disp!r}")

    def request_approval(
        self,
        identity: AdapterIdentity,
        binding_id: str,
        session_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        permission_mode: str,
        cwd: str,
    ) -> ApprovalResponse:
        """Call POST /v1/approval and hold for the Core's decision."""
        conn = self.get_connection()
        body = {
            "schema": 1,
            "identity": identity.to_dict(),
            "binding_id": binding_id,
            "session_id": session_id,
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "permission_mode": permission_mode,
            "cwd": cwd,
        }
        status, data = self._request(
            "POST",
            "/v1/approval",
            body,
            APPROVAL_TIMEOUT_SECONDS,
            conn,
        )
        if status == 401:
            self.reset_connection()
            raise BridgeUnauthorized("unauthorized approval request")
        if status != 200:
            err_code = data.get("error", "unknown_error")
            raise BridgeTransportError(
                f"approval POST returned status {status}: {err_code}",
                status_code=status,
                error_code=err_code,
            )

        schema_val = data.get("schema")
        if type(schema_val) is not int or schema_val != 1:
            raise BridgeTransportError(
                f"approval response schema must be 1, got {schema_val!r}",
                status_code=status,
                error_code="unsupported_schema",
            )

        resp_tool_use_id = data.get("tool_use_id")
        decision = data.get("decision")
        reason = data.get("reason")
        if (
            not isinstance(resp_tool_use_id, str)
            or not isinstance(decision, str)
            or not isinstance(reason, str)
        ):
            raise BridgeTransportError(
                "approval response missing or invalid required string fields",
                status_code=status,
                error_code="invalid_request",
            )

        if decision == "allow":
            expected_keys = {"schema", "tool_use_id", "decision", "reason", "snapshot"}
            if set(data.keys()) != expected_keys:
                raise BridgeTransportError(
                    f"unexpected keys in allow response: {set(data.keys())}",
                    status_code=status,
                    error_code="invalid_request",
                )
            snapshot = data.get("snapshot")
            if not isinstance(snapshot, dict):
                raise BridgeTransportError(
                    "approval response with allow decision missing snapshot object",
                    status_code=status,
                    error_code="invalid_request",
                )
            return ApprovalResponse(
                tool_use_id=resp_tool_use_id,
                decision="allow",
                reason=reason,
                snapshot=snapshot,
                schema=1,
            )
        elif decision == "defer":
            expected_keys = {"schema", "tool_use_id", "decision", "reason"}
            if set(data.keys()) != expected_keys:
                raise BridgeTransportError(
                    f"unexpected keys in defer response: {set(data.keys())}",
                    status_code=status,
                    error_code="invalid_request",
                )
            return ApprovalResponse(
                tool_use_id=resp_tool_use_id,
                decision="defer",
                reason=reason,
                snapshot=None,
                schema=1,
            )
        else:
            raise BridgeTransportError(
                f"unknown approval decision: {decision!r}",
                status_code=status,
                error_code="invalid_request",
            )
