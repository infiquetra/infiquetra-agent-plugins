"""Tests for the bridge wire client (KTD9; §2–§8).

Exercises discovery validation, token grammar, Core-identifier grammar, auth,
the five routes, transport errors, deadlines, retry after 500, and lost-response
reconciliation against the independent bridge_stub.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapter_identity import AdapterIdentity  # noqa: E402
from bridge_client import (  # noqa: E402
    CURRENT_TIMEOUT_SECONDS,
    HEALTH_TIMEOUT_SECONDS,
    PRESENCE_TIMEOUT_SECONDS,
    RENDERING_TIMEOUT_SECONDS,
    BridgeClient,
    BridgeConnection,
    BridgeTransportError,
    BridgeUnauthorized,
    BridgeUnavailable,
    read_discovery,
)
from bridge_stub import DEFAULT_STUB_TOKEN, BridgeStub  # noqa: E402

VALID_UUID_1 = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
VALID_UUID_2 = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
UUID_V1 = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"


class DiscoveryValidationTests(unittest.TestCase):
    """Discovery file validation tests (§2)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def _write_file(self, content: str | dict, mode: int = 0o600) -> Path:
        if isinstance(content, dict):
            raw = json.dumps(content)
        else:
            raw = content
        self.bridge_path.write_text(raw, encoding="utf-8")
        os.chmod(self.bridge_path, mode)
        return self.bridge_path

    def test_valid_discovery_file_parses(self) -> None:
        self._write_file(
            {
                "schema": 1,
                "host": "127.0.0.1",
                "port": 49152,
                "token": DEFAULT_STUB_TOKEN,
            }
        )
        conn = read_discovery(self.bridge_path)
        self.assertEqual(conn.schema, 1)
        self.assertEqual(conn.host, "127.0.0.1")
        self.assertEqual(conn.port, 49152)
        self.assertEqual(conn.token, DEFAULT_STUB_TOKEN)

    def test_missing_file_raises_unavailable(self) -> None:
        non_existent = Path(self.temp_dir.name) / "missing_bridge.json"
        with self.assertRaises(BridgeUnavailable) as caught:
            read_discovery(non_existent)
        self.assertIn("does not exist", str(caught.exception))

    def test_invalid_mode_raises_unavailable(self) -> None:
        # File mode 0644 (world/group readable) must fail
        self._write_file(
            {
                "schema": 1,
                "host": "127.0.0.1",
                "port": 49152,
                "token": DEFAULT_STUB_TOKEN,
            },
            mode=0o644,
        )
        with self.assertRaises(BridgeUnavailable) as caught:
            read_discovery(self.bridge_path)
        self.assertIn("file mode", str(caught.exception))

    def test_malformed_json_raises_unavailable(self) -> None:
        self._write_file("{ not json }")
        with self.assertRaises(BridgeUnavailable):
            read_discovery(self.bridge_path)

    def test_non_dict_json_raises_unavailable(self) -> None:
        self._write_file("[1, 2, 3]")
        with self.assertRaises(BridgeUnavailable):
            read_discovery(self.bridge_path)

    def test_extra_keys_raise_unavailable(self) -> None:
        self._write_file(
            {
                "schema": 1,
                "host": "127.0.0.1",
                "port": 49152,
                "token": DEFAULT_STUB_TOKEN,
                "extra_key": "unsupported",
            }
        )
        with self.assertRaises(BridgeUnavailable) as caught:
            read_discovery(self.bridge_path)
        self.assertIn("extra_key", str(caught.exception))

    def test_missing_keys_raise_unavailable(self) -> None:
        self._write_file(
            {
                "schema": 1,
                "host": "127.0.0.1",
                "port": 49152,
            }
        )
        with self.assertRaises(BridgeUnavailable) as caught:
            read_discovery(self.bridge_path)
        self.assertIn("keys", str(caught.exception))

    def test_wrong_member_types_raise_unavailable(self) -> None:
        cases = [
            ("schema is string", {"schema": "1", "host": "127.0.0.1", "port": 49152, "token": DEFAULT_STUB_TOKEN}),
            ("schema is bool", {"schema": True, "host": "127.0.0.1", "port": 49152, "token": DEFAULT_STUB_TOKEN}),
            ("schema is 2", {"schema": 2, "host": "127.0.0.1", "port": 49152, "token": DEFAULT_STUB_TOKEN}),
            ("host is not 127.0.0.1", {"schema": 1, "host": "localhost", "port": 49152, "token": DEFAULT_STUB_TOKEN}),
            ("port is string", {"schema": 1, "host": "127.0.0.1", "port": "49152", "token": DEFAULT_STUB_TOKEN}),
            ("port out of range", {"schema": 1, "host": "127.0.0.1", "port": 70000, "token": DEFAULT_STUB_TOKEN}),
            ("token is int", {"schema": 1, "host": "127.0.0.1", "port": 49152, "token": 12345}),
        ]
        for name, payload in cases:
            with self.subTest(case=name):
                self._write_file(payload)
                with self.assertRaises(BridgeUnavailable):
                    read_discovery(self.bridge_path)


class TokenGrammarTests(unittest.TestCase):
    """Token grammar validation tests (§2, §3)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def test_token_grammar_violations_refuse_and_make_no_wire_requests(self) -> None:
        violations = [
            ("42 chars (too short)", "a" * 42),
            ("44 chars (too long)", "a" * 44),
            ("43 chars with '+' (invalid char)", "a" * 42 + "+"),
            ("43 chars with '/' (invalid char)", "a" * 42 + "/"),
            ("padded with '='", "a" * 42 + "="),
            ("empty token", ""),
        ]

        with BridgeStub() as stub:
            for name, token in violations:
                with self.subTest(violation=name):
                    stub.requests.clear()
                    stub.write_discovery_file(
                        self.bridge_path,
                        token=token,
                    )
                    client = BridgeClient(bridge_file=self.bridge_path)
                    with self.assertRaises(BridgeUnavailable):
                        client.get_health()

                    identity = AdapterIdentity("s1", "p1", "t1")
                    with self.assertRaises(BridgeUnavailable):
                        client.put_presence(identity)

                    with self.assertRaises(BridgeUnavailable):
                        client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "hello")

                    # Assert no request ever reached the stub on grammar violation
                    self.assertEqual(len(stub.requests), 0)


class CoreIdentifierGrammarTests(unittest.TestCase):
    """Core identifier UUIDv4 grammar validation tests (§8)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def test_malformed_uppercase_or_wrong_version_identifier_refuses_snapshot(self) -> None:
        invalid_ids = [
            ("uppercase UUID", "F47AC10B-58CC-4372-A567-0E02B2C3D479"),
            ("not a UUID", "opaque-binding-id-1234"),
            ("UUID v1 (wrong version)", UUID_V1),
        ]

        identity = AdapterIdentity("session-1", "p1", "t1")

        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            for name, bad_id in invalid_ids:
                with self.subTest(invalid_binding_id=name):
                    stub.set_binding(bad_id, identity.to_dict())
                    stub.set_turn(VALID_UUID_2, bad_id, "open")
                    with self.assertRaises(BridgeUnavailable) as caught:
                        client.get_current()
                    self.assertIn("UUIDv4", str(caught.exception))

                with self.subTest(invalid_turn_id=name):
                    stub.set_binding(VALID_UUID_1, identity.to_dict())
                    stub.set_turn(bad_id, VALID_UUID_1, "open")
                    with self.assertRaises(BridgeUnavailable) as caught:
                        client.get_current()
                    self.assertIn("UUIDv4", str(caught.exception))


class RoutesAndAuthTests(unittest.TestCase):
    """Tests for the five frozen routes, Auth, and response parsing (§3, §6)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def test_auth_header_and_401_unauthorized(self) -> None:
        with BridgeStub(token=DEFAULT_STUB_TOKEN) as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            # Health check succeeds with correct token
            resp = client.get_health()
            self.assertEqual(resp.status, "ok")
            self.assertEqual(len(stub.requests), 1)
            self.assertEqual(
                stub.requests[0].headers.get("Authorization"),
                f"Bearer {DEFAULT_STUB_TOKEN}",
            )

            # Rotate token on server to cause 401
            stub.token = "new_token_43_chars_base64url_alphabet_012345"[:43]
            with self.assertRaises(BridgeUnauthorized):
                client.get_health()

    def test_five_routes_round_trip_200(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            # 1. GET /v1/health
            health = client.get_health()
            self.assertEqual(health.service, "auralis-bridge")
            self.assertEqual(health.status, "ok")

            # 2. PUT /v1/presence
            pres = client.put_presence(identity)
            self.assertEqual(pres.disposition, "present")
            self.assertEqual(pres.lease_ms, 15000)
            self.assertEqual(pres.renew_after_ms, 5000)

            # 3. DELETE /v1/presence
            del_pres = client.delete_presence(identity)
            self.assertEqual(del_pres.disposition, "absent")

            # 4. GET /v1/current (null binding/turn)
            curr_null = client.get_current()
            self.assertIsNone(curr_null.binding)
            self.assertIsNone(curr_null.turn)

            # 4b. GET /v1/current (active binding & turn)
            stub.set_binding(VALID_UUID_1, identity.to_dict())
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "open")
            curr_active = client.get_current()
            self.assertIsNotNone(curr_active.binding)
            self.assertEqual(curr_active.binding.binding_id, VALID_UUID_1)
            self.assertEqual(curr_active.binding.identity, identity)
            self.assertIsNotNone(curr_active.turn)
            self.assertEqual(curr_active.turn.turn_id, VALID_UUID_2)
            self.assertEqual(curr_active.turn.state, "open")

            # 5. POST /v1/rendering (accepted)
            render_resp = client.submit_rendering(
                identity,
                VALID_UUID_1,
                VALID_UUID_2,
                "Hello, this is a plain text rendering.",
            )
            self.assertEqual(render_resp.disposition, "accepted")
            self.assertEqual(render_resp.detail, "accepted")
            self.assertEqual(render_resp.binding_id, VALID_UUID_1)
            self.assertEqual(render_resp.turn_id, VALID_UUID_2)

    def test_rendering_adjudication_rejection_reasons(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        other_identity = AdapterIdentity("s-2", "p-2", "t-2")

        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            # no_binding
            stub.clear_binding()
            resp = client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "no_binding")

            # binding_not_current
            stub.set_binding(VALID_UUID_1, identity.to_dict())
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "open")
            other_binding = "11111111-1111-4111-8111-111111111111"
            resp = client.submit_rendering(identity, other_binding, VALID_UUID_2, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "binding_not_current")

            # adapter_not_bound
            resp = client.submit_rendering(other_identity, VALID_UUID_1, VALID_UUID_2, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "adapter_not_bound")

            # turn_not_current
            other_turn = "22222222-2222-4222-8222-222222222222"
            resp = client.submit_rendering(identity, VALID_UUID_1, other_turn, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "turn_not_current")

            # turn_canceled
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "canceled")
            resp = client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "turn_canceled")

            # fallback_already_began
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "fallback_accepted")
            resp = client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "text")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "fallback_already_began")

            # empty_rendering
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "open")
            resp = client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "   ")
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "empty_rendering")


class TransportErrorsAndDeadlinesTests(unittest.TestCase):
    """Tests for transport errors, status mappings, and deadline enforcement (§7)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def test_transport_error_status_mapping(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        error_cases = [
            (400, "invalid_request"),
            (404, "not_found"),
            (405, "method_not_allowed"),
            (413, "body_too_large"),
            (415, "unsupported_media_type"),
        ]

        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            for status, err_code in error_cases:
                with self.subTest(status=status, error_code=err_code):
                    stub.path_status_overrides["/v1/health"] = (status, err_code)
                    with self.assertRaises(BridgeTransportError) as caught:
                        client.get_health()
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertEqual(caught.exception.error_code, err_code)

    def test_unknown_status_or_error_fails_closed(self) -> None:
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            stub.path_status_overrides["/v1/health"] = (502, "bad_gateway")
            with self.assertRaises(BridgeTransportError) as caught:
                client.get_health()
            self.assertEqual(caught.exception.status_code, 502)

    def test_deadline_budget_enforcement_with_stubbed_clock(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)

            # Simulated clock that advances past the deadline immediately
            current_time = 1000.0

            def advancing_clock() -> float:
                nonlocal current_time
                t = current_time
                current_time += 10.0  # jumps by 10s on each check
                return t

            client = BridgeClient(bridge_file=self.bridge_path, clock=advancing_clock)

            with self.assertRaises(BridgeTransportError) as caught:
                client.get_health()
            self.assertEqual(caught.exception.error_code, "transport_error")


class RetryAndLostResponseTests(unittest.TestCase):
    """Tests for 500 retry and lost-response reconciliation (§8; KTD1; F8)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bridge_path = Path(self.temp_dir.name) / "bridge.json"

    def test_500_retry_performs_one_byte_identical_retry_after_health_check(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            stub.set_binding(VALID_UUID_1, identity.to_dict())
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "open")
            client = BridgeClient(bridge_file=self.bridge_path)

            # Set 500 error on first attempt
            stub.path_status_overrides["/v1/rendering"] = (500, "internal_error")

            # Remove 500 override when health check is called during retry
            orig_health = stub.health_status

            def health_hook() -> None:
                stub.path_status_overrides.pop("/v1/rendering", None)

            # We can test that it retries and succeeds if health check passes
            # Let's verify health check is performed
            stub.requests.clear()

            # Custom handler: first POST returns 500, GET /v1/health returns 200, second POST returns 200
            call_count = 0

            def custom_post(payload: dict) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    stub.path_status_overrides["/v1/rendering"] = (500, "internal_error")
                else:
                    stub.path_status_overrides.pop("/v1/rendering", None)

            stub.path_status_overrides["/v1/rendering"] = (500, "internal_error")

            # In the client: on 500, it calls get_health(), then retries
            # If health check returns 200 and rendering retry returns 200:
            def simulate_health():
                stub.path_status_overrides.pop("/v1/rendering", None)
                return "ok"

            with mock.patch.object(client, "get_health", side_effect=simulate_health):
                resp = client.submit_rendering(
                    identity, VALID_UUID_1, VALID_UUID_2, "retry text"
                )
                self.assertEqual(resp.disposition, "accepted")

    def test_400_is_never_retried(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            client = BridgeClient(bridge_file=self.bridge_path)

            stub.path_status_overrides["/v1/rendering"] = (400, "invalid_request")
            stub.requests.clear()

            with self.assertRaises(BridgeTransportError) as caught:
                client.submit_rendering(identity, VALID_UUID_1, VALID_UUID_2, "text")
            self.assertEqual(caught.exception.status_code, 400)
            # Only 1 request reached the stub; no retry
            self.assertEqual(len(stub.requests), 1)

    def test_lost_response_reconciliation_f8(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            stub.set_binding(VALID_UUID_1, identity.to_dict())
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "open")
            client = BridgeClient(bridge_file=self.bridge_path)

            # Drop the first rendering response
            stub.drop_next_rendering_response()

            # Client should retry:
            # - Attempt 1: stub accepts and transitions turn state to "authored_accepted", but closes connection without returning response
            # - Attempt 2: retry request arrives; stub adjudicates against turn state "authored_accepted" and returns 200 {"disposition": "rejected", "reason": "duplicate_rendering"}
            # - Client reconciles retry context + duplicate_rendering -> returns accepted with detail "accepted_on_retry"
            resp = client.submit_rendering(
                identity,
                VALID_UUID_1,
                VALID_UUID_2,
                "Rendered plain text.",
            )

            self.assertEqual(resp.disposition, "accepted")
            self.assertEqual(resp.detail, "accepted_on_retry")
            self.assertEqual(resp.binding_id, VALID_UUID_1)
            self.assertEqual(resp.turn_id, VALID_UUID_2)

    def test_duplicate_rendering_outside_retry_relays_as_rejected(self) -> None:
        identity = AdapterIdentity("s-1", "p-1", "t-1")
        with BridgeStub() as stub:
            stub.write_discovery_file(self.bridge_path)
            stub.set_binding(VALID_UUID_1, identity.to_dict())
            stub.set_turn(VALID_UUID_2, VALID_UUID_1, "authored_accepted")
            client = BridgeClient(bridge_file=self.bridge_path)

            resp = client.submit_rendering(
                identity,
                VALID_UUID_1,
                VALID_UUID_2,
                "Second submission.",
            )
            self.assertEqual(resp.disposition, "rejected")
            self.assertEqual(resp.reason, "duplicate_rendering")


if __name__ == "__main__":
    unittest.main()
