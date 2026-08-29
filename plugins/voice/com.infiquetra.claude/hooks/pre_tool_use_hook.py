"""The Claude Code ``PreToolUse`` hook for the voice package (KTD7; X1; C8 Prerequisite 1).

This hook handles tool use approval and observation:
1. Reads the hook payload from standard input once (``session_id``, ``tool_name``,
   ``tool_input``, ``tool_use_id``, ``permission_mode``, ``cwd``).
2. If an Auralis-originated turn record exists for this session, records the tool observation
   into the turn record (observe-only recording; KTD7).
3. Resolves the adapter identity and checks the active bridge binding via GET /v1/current.
   If the session is covered by an active bridge binding, forwards the structured approval
   request to POST /v1/approval and holds the connection awaiting Core's decision.
4. Validates the Core's response:
   - decision must be "allow"
   - returned tool_use_id must exactly equal the sent tool_use_id
   - complete action snapshot must match in full:
     * snapshot.tool_name == original tool_name
     * snapshot.tool_use_id == original tool_use_id
     * snapshot.tool_input canonically equals original tool_input
     * snapshot.classification.result == "voice_approvable"
5. Emits allow ONLY on exact match of both identifier and complete snapshot.
6. On every other outcome (defer decision, identifier mismatch, snapshot mismatch,
   malformed response, transport error, timeout, no bridge binding, session mismatch),
   defers with no output and exits 0.

A hook must never break a turn, so every failure path exits 0 with no standard output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_PACKAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_PACKAGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SCRIPTS))

import adapter_identity  # noqa: E402
import bridge_client  # noqa: E402
import turn_record  # noqa: E402
import voice_policy  # noqa: E402


def _read_payload() -> dict[str, Any] | None:
    """Read the hook payload from stdin exactly once; ``None`` unless a JSON object."""
    try:
        raw = sys.stdin.read()
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _canonical_json_equal(val1: Any, val2: Any) -> bool:
    """Check if two JSON-compatible data structures are canonically identical."""
    try:
        b1 = json.dumps(val1, sort_keys=True, separators=(",", ":"))
        b2 = json.dumps(val2, sort_keys=True, separators=(",", ":"))
        return b1 == b2
    except Exception:
        return False


def _validate_snapshot_and_identifier(
    response: bridge_client.ApprovalResponse,
    expected_tool_use_id: str,
    expected_tool_name: str,
    expected_tool_input: dict[str, Any],
) -> bool:
    """Validate that the Core response matches the request identifier and complete snapshot."""
    if response.decision != "allow":
        return False

    # 1. Identifier exact match (R111, R113)
    if response.tool_use_id != expected_tool_use_id:
        return False

    snapshot = response.snapshot
    if not isinstance(snapshot, dict):
        return False

    # 2. Snapshot identifier match
    if snapshot.get("tool_use_id") != expected_tool_use_id:
        return False

    # 3. Snapshot tool_name match
    if snapshot.get("tool_name") != expected_tool_name:
        return False

    # 4. Snapshot tool_input canonical match (KTD2)
    snapshot_input = snapshot.get("tool_input")
    if not isinstance(snapshot_input, dict):
        return False
    if not _canonical_json_equal(snapshot_input, expected_tool_input):
        return False

    # 5. Snapshot classification result must be "voice_approvable"
    classification = snapshot.get("classification")
    if not isinstance(classification, dict):
        return False
    if classification.get("result") != "voice_approvable":
        return False

    return True


def main() -> int:
    try:
        payload = _read_payload()
        if payload is None:
            return 0

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return 0

        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            return 0

        tool_use_id = payload.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not tool_use_id:
            return 0

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0

        permission_mode = payload.get("permission_mode")
        if not isinstance(permission_mode, str) or not permission_mode:
            permission_mode = "default"

        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = os.getcwd()

        # Step A: Best-effort tool observation for Auralis-originated turn (KTD7)
        try:
            rec = turn_record.read_turn_record()
            if (
                rec is not None
                and rec.session_id == session_id
                and rec.origin == turn_record.ORIGIN_AURALIS
            ):
                policy = voice_policy.read_policy()
                if not policy.tool_allowlist or tool_name in policy.tool_allowlist:
                    turn_record.record_tool_observation(
                        session_id=session_id,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_use_id=tool_use_id,
                    )
        except Exception:
            pass

        # Step B: Check bridge binding coverage (Prerequisite 1 obligation 1)
        try:
            identity = adapter_identity.resolve_adapter_identity()
        except Exception:
            return 0

        if not adapter_identity.matches_session(identity, session_id):
            return 0

        try:
            client = bridge_client.BridgeClient()
            snapshot = client.get_current()
        except Exception:
            return 0

        if snapshot.binding is None or snapshot.binding.identity != identity:
            return 0

        binding_id = snapshot.binding.binding_id

        # Step C: Forward approval request and hold for decision
        try:
            resp = client.request_approval(
                identity=identity,
                binding_id=binding_id,
                session_id=session_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
                permission_mode=permission_mode,
                cwd=cwd,
            )
        except Exception:
            # Transport error, timeout, 401, 500, socket close -> defer
            return 0

        # Step D: Validate response before emitting allow decision
        if not _validate_snapshot_and_identifier(
            resp,
            expected_tool_use_id=tool_use_id,
            expected_tool_name=tool_name,
            expected_tool_input=tool_input,
        ):
            return 0

        # Step E: Emit allow decision
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
        sys.stdout.write(json.dumps(output) + "\n")
        return 0

    except Exception:
        # Fail-closed: any unhandled exception defers with no output and exits 0.
        return 0


if __name__ == "__main__":
    sys.exit(main())
