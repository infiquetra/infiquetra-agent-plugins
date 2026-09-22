"""``output_attestation.v1`` -- hash-bound proof for bridge-produced output (#388).

The shape is intentionally small and transport-neutral. A bridge names the artifact it is
attesting, records its byte length and SHA-256 digest, and marks whether it was empty.
Dispatch can then reject a receipt whose attestation is missing, empty when output is required,
or hash-mismatched against the evidence text it is about to manifest.
"""

from __future__ import annotations

import hashlib
from typing import Any

SCHEMA_NAME = "output_attestation.v1"
SCHEMA_VERSIONS = (SCHEMA_NAME,)


def _bytes(content: str | bytes) -> bytes:
    return content if isinstance(content, bytes) else content.encode("utf-8")


def emit_attestation(*, artifact: str, content: str | bytes) -> dict[str, Any]:
    """Build an ``output_attestation.v1`` record for one produced artifact."""
    body = _bytes(content)
    return {
        "schema": SCHEMA_NAME,
        "artifact": artifact,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "empty": len(body) == 0,
    }


def validate_attestation(
    attestation: dict[str, Any],
    *,
    expected_content: str | bytes | None = None,
    require_non_empty: bool = False,
) -> list[str]:
    """Validate an attestation. Empty list means valid."""
    errors: list[str] = []
    if not isinstance(attestation, dict):
        return [f"output_attestation must be a dict, got {type(attestation).__name__}"]

    schema = attestation.get("schema")
    if schema not in SCHEMA_VERSIONS:
        errors.append(
            f"output_attestation unknown schema {schema!r} (expected one of {SCHEMA_VERSIONS})"
        )

    artifact = attestation.get("artifact")
    if not isinstance(artifact, str) or not artifact.strip():
        errors.append("output_attestation requires non-empty artifact")

    byte_count = attestation.get("bytes")
    if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
        errors.append("output_attestation bytes must be a non-negative integer")

    digest = attestation.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        errors.append("output_attestation sha256 must be a 64-character hex string")
    else:
        try:
            int(digest, 16)
        except ValueError:
            errors.append("output_attestation sha256 must be hex")

    empty = attestation.get("empty")
    if not isinstance(empty, bool):
        errors.append("output_attestation empty must be boolean")
    elif isinstance(byte_count, int) and empty != (byte_count == 0):
        errors.append("output_attestation empty must match bytes == 0")
    if require_non_empty and empty is True:
        errors.append("proof-integrity: output-attestation-empty")

    if expected_content is not None:
        body = _bytes(expected_content)
        expected_hash = hashlib.sha256(body).hexdigest()
        if isinstance(byte_count, int) and byte_count != len(body):
            errors.append(
                "proof-integrity: output-attestation-bytes-mismatch "
                f"expected={byte_count} observed={len(body)}"
            )
        if isinstance(digest, str) and len(digest) == 64 and digest != expected_hash:
            errors.append(
                "proof-integrity: output-attestation-mismatch "
                f"expected={digest[:12]} observed={expected_hash[:12]}"
            )

    return errors
