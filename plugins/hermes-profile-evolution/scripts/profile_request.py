#!/usr/bin/env python3
"""Safe Claude Code adapter for the canonical ``hermes profile-request`` CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

PROFILE_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SSH_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PROHIBITED_REFERENCE_RE = re.compile(
    r"(?i)(?:^|[/_.-])(?:session|transcript|auth|credential|secret|token|\\.env|"
    r".*\\.db|.*\\.sqlite|.*\\.log)(?:$|[/_.-])"
)
SECRET_LITERAL_RE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"(?:api[_-]?key|password|secret|token)\s*[:=]\s*[\"']?[A-Za-z0-9+/=_-]{12,})"
)
COMMAND_TIMEOUT_SECONDS = 45
ENVELOPE_KEYS = {
    "schema_version",
    "record_type",
    "proposal_id",
    "revision_digest",
    "target",
    "requester",
    "delegation_chain",
    "intent",
    "evidence_references",
    "created_at",
}
FORBIDDEN = {"host", "url", "endpoint", "api_key", "model", "provider", "system_prompt", "tools"}


class RequestError(ValueError):
    """A request cannot safely cross the harness boundary."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _validate_target(target: object) -> str:
    if (
        not isinstance(target, str)
        or not PROFILE_RE.fullmatch(target)
        or target in {"default", "custom"}
    ):
        raise RequestError("target must be a named Hermes profile")
    return target


def _validate_references(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 128:
        raise RequestError("evidence references are invalid")
    references: list[str] = []
    for reference in value:
        if (
            not isinstance(reference, str)
            or not reference
            or len(reference) > 512
            or reference.startswith("/")
            or ".." in reference.split("/")
            or PROHIBITED_REFERENCE_RE.search(reference)
        ):
            raise RequestError("evidence references must be safe repository-relative references")
        references.append(reference)
    if len(references) != len(set(references)):
        raise RequestError("evidence references must be unique")
    return references


def _validate_hop(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) - {
        "actor_kind",
        "actor_id",
        "verification",
        "source_event_digest",
    }:
        raise RequestError("delegation hop contains unsupported fields")
    kind, actor, verification = (
        value.get("actor_kind"),
        value.get("actor_id"),
        value.get("verification"),
    )
    if kind not in {"operator", "harness", "profile", "external_agent"} or verification not in {
        "verified",
        "claimed",
    }:
        raise RequestError("delegation hop kind or verification is invalid")
    if not isinstance(actor, str) or not actor or len(actor) > 128:
        raise RequestError("delegation hop actor is invalid")
    source_digest = value.get("source_event_digest")
    if source_digest is not None and (
        not isinstance(source_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", source_digest)
    ):
        raise RequestError("delegation source event digest is invalid")
    if kind == "profile" and verification == "verified":
        raise RequestError("verified profile identity requires resolved outbound evidence")
    result = {"actor_kind": kind, "actor_id": actor, "verification": verification}
    if source_digest is not None:
        result["source_event_digest"] = source_digest
    return result


def _validate_envelope(envelope: object) -> dict[str, Any]:
    if (
        not isinstance(envelope, dict)
        or set(envelope) != ENVELOPE_KEYS
        or any(key in envelope for key in FORBIDDEN)
    ):
        raise RequestError("proposal envelope fields do not match the closed version-1 schema")
    if envelope["schema_version"] != 1 or envelope["record_type"] != "proposal_envelope":
        raise RequestError("proposal envelope schema version or record type is unsupported")
    if not isinstance(envelope["proposal_id"], str) or not OPAQUE_ID_RE.fullmatch(
        envelope["proposal_id"]
    ):
        raise RequestError("proposal identifier is invalid")
    target = _validate_target(envelope["target"])
    requester = _validate_hop(envelope["requester"])
    chain = envelope["delegation_chain"]
    if not isinstance(chain, list) or not 1 <= len(chain) <= 32:
        raise RequestError("delegation chain must contain between 1 and 32 hops")
    parsed_chain = [_validate_hop(hop) for hop in chain]
    intent = envelope["intent"]
    if (
        not isinstance(intent, str)
        or not intent.strip()
        or len(intent) > 8192
        or SECRET_LITERAL_RE.search(intent)
    ):
        raise RequestError("intent is empty, too large, or contains secret-bearing material")
    references = _validate_references(envelope["evidence_references"])
    revision = envelope["revision_digest"]
    body = {
        key: envelope[key]
        for key in (
            "schema_version",
            "target",
            "requester",
            "delegation_chain",
            "intent",
            "evidence_references",
        )
    }
    if (
        not isinstance(revision, str)
        or not re.fullmatch(r"[a-f0-9]{64}", revision)
        or revision != hashlib.sha256(_canonical(body)).hexdigest()
    ):
        raise RequestError("proposal revision digest is invalid")
    if not isinstance(envelope["created_at"], str):
        raise RequestError("proposal created_at is invalid")
    try:
        datetime.fromisoformat(envelope["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise RequestError("proposal created_at is invalid") from exc
    return {
        **envelope,
        "target": target,
        "requester": requester,
        "delegation_chain": parsed_chain,
        "evidence_references": references,
    }


def build_envelope(
    target: str, intent: str, *, requester: str = "claude-code", evidence: list[str] | None = None
) -> dict[str, Any]:
    """Build the Hermes closed v1 envelope; requester identity remains claimed."""
    target = _validate_target(target)
    references = _validate_references(evidence or [])
    requester_hop = {"actor_kind": "harness", "actor_id": requester, "verification": "claimed"}
    body: dict[str, Any] = {
        "schema_version": 1,
        "target": target,
        "requester": requester_hop,
        "delegation_chain": [requester_hop],
        "intent": intent,
        "evidence_references": references,
    }
    revision = hashlib.sha256(_canonical(body)).hexdigest()
    return _validate_envelope(
        {
            **body,
            "record_type": "proposal_envelope",
            "proposal_id": f"proposal-{revision[:16]}",
            "revision_digest": revision,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )


def _ssh_command(alias: str, arguments: list[str]) -> list[str]:
    if not SSH_ALIAS_RE.fullmatch(alias):
        raise RequestError("governed SSH alias is invalid")
    remote = "exec hermes profile-request" + "".join(
        f" {shlex.quote(argument)}" for argument in arguments
    )
    return ["ssh", "--", alias, remote]


def _run(arguments: list[str], payload: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    alias = os.environ.get("HERMES_PROFILE_REQUEST_SSH_ALIAS")
    command = _ssh_command(alias, arguments) if alias else ["hermes", "profile-request", *arguments]
    try:
        return subprocess.run(
            command,
            input=payload,
            capture_output=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RequestError("Hermes profile-request service is unavailable") from exc


def assert_healthy(target: str) -> None:
    """Reject absent or version-skewed canonical CLI before accepting a proposal."""
    response = _run(["doctor", "--target", _validate_target(target)])
    try:
        status = json.loads(response.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestError(
            "Hermes profile-request health check returned no valid response"
        ) from exc
    required = {"target", "route_registered", "credential_available", "service_available"}
    if (
        response.returncode != 0
        or not isinstance(status, dict)
        or set(status) != required
        or status.get("target") != target
        or not all(status.get(name) is True for name in required - {"target"})
    ):
        raise RequestError("Hermes profile-request is unavailable or incompatible")


def invoke(action: str, envelope: dict[str, Any], *, message: str | None = None) -> str:
    """Run a closed canonical action with an envelope on standard input only."""
    if action not in {"suggest", "reply", "resume"}:
        raise RequestError("unsupported proposal action")
    validated = _validate_envelope(envelope)
    args = [action]
    if action == "reply":
        if (
            not isinstance(message, str)
            or not message.strip()
            or len(message) > 16384
            or SECRET_LITERAL_RE.search(message)
        ):
            raise RequestError("reply is empty, too large, or contains secret-bearing material")
        args.extend(["--message", message])
    assert_healthy(validated["target"])
    result = _run(args, _canonical(validated))
    if result.returncode != 0:
        raise RequestError("Hermes profile-request rejected the proposal")
    return result.stdout.decode("utf-8", errors="replace")


def read_only(action: str, arguments: list[str], payload: bytes | None = None) -> str:
    if action not in {"status", "census"}:
        raise RequestError("unsupported read-only action")
    result = _run([action, *arguments], payload)
    if result.returncode != 0:
        raise RequestError("Hermes profile-request read failed")
    return result.stdout.decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Expose only the canonical submit, continuation, and read-only actions."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    suggest = commands.add_parser("suggest")
    suggest.add_argument("target")
    suggest.add_argument("intent")
    suggest.add_argument("--evidence", action="append", default=[])
    reply = commands.add_parser("reply")
    reply.add_argument("--message", required=True)
    commands.add_parser("resume")
    status = commands.add_parser("status")
    status.add_argument("--proposal-id", required=True)
    status.add_argument("--revision", required=True)
    status.add_argument("--target", required=True)
    commands.add_parser("census")
    args = parser.parse_args(argv)
    try:
        if args.action == "suggest":
            print(
                invoke("suggest", build_envelope(args.target, args.intent, evidence=args.evidence))
            )
        elif args.action in {"reply", "resume"}:
            envelope = json.loads(sys.stdin.read())
            print(invoke(args.action, envelope, message=getattr(args, "message", None)))
        elif args.action == "status":
            print(
                read_only(
                    "status",
                    [
                        "--proposal-id",
                        args.proposal_id,
                        "--revision",
                        args.revision,
                        "--target",
                        args.target,
                    ],
                )
            )
        else:
            print(read_only("census", [], sys.stdin.buffer.read()))
    except (RequestError, json.JSONDecodeError) as exc:
        print(f"[hermes-profile-evolution] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
