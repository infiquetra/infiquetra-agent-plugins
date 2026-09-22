"""``bridge_receipt.v1`` — the one proof-of-execution contract every engine bridge emits (#383, U1).

Rationale (plan ``2026-07-06-external-engine-http-bridge-receipt-pair-plan.md``, KTD6/KTD7): three
consumers across two plugins today (saga's dispatch manifest gating, saga's HTTP bridge, agy's
delegate), a fourth coming (#476 ``plugins/codex/``). A saga-local module imported by agy would break
at install time (journal ``{#marketplace-install-layout-no-import-path}``), so the schema, the builder,
and the validator live once here in fleet-commons and are loaded by consumers through their vendored
``fleet_commons_shim`` (``fleet_commons_shim.load("bridge_receipt")``).

A receipt has a common core (present on every transport) plus a transport-discriminated ``runner``
section that proves what actually ran:

* ``transport: cli``  — ``runner`` carries ``pid``, ``argv``, ``exit_code``.
* ``transport: http`` — ``runner`` carries ``url``, ``status_code``, ``model``.

``emit_receipt(...)`` builds a schema-valid receipt from keyword data (dispatching the ``runner``
section shape off ``transport``). ``validate_receipt(receipt)`` returns a list of human-readable
error strings — empty means valid — so callers can gate on ``not validate_receipt(receipt)`` without
raising, and can surface *why* a receipt is rejected (missing field, wrong section for the declared
transport, unknown schema version) rather than a bare boolean.

No secrets ever belong in a receipt: callers must resolve credentials at call time and never pass
them through ``emit_receipt`` (see plan's "no receipts/telemetry ever carry a resolved API key").
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_sibling(name: str) -> ModuleType:
    try:
        module = __import__(f"{__package__}.{name}", fromlist=[name]) if __package__ else None
    except ImportError:
        module = None
    if module is not None:
        return module
    cache_key = f"_fleet_commons_{name}"
    if cache_key in sys.modules:
        return sys.modules[cache_key]
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(cache_key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load fleet-commons sibling module {name!r}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = loaded
    spec.loader.exec_module(loaded)
    return loaded


output_attestation = _load_sibling("output_attestation")

SCHEMA_NAME = "bridge_receipt.v1"
SCHEMA_VERSIONS = (SCHEMA_NAME,)

TRANSPORT_CLI = "cli"
TRANSPORT_HTTP = "http"
TRANSPORTS = (TRANSPORT_CLI, TRANSPORT_HTTP)

# Common core fields present on every receipt regardless of transport.
COMMON_FIELDS = (
    "schema",
    "engine_id",
    "variant",
    "transport",
    "wall_time_s",
    "bytes_produced",
)

# Transport-discriminated ``runner`` section field requirements.
RUNNER_FIELDS: dict[str, tuple[str, ...]] = {
    TRANSPORT_CLI: ("pid", "argv", "exit_code"),
    TRANSPORT_HTTP: ("url", "status_code", "model"),
}


def emit_receipt(
    *,
    engine_id: str,
    variant: str,
    transport: str,
    wall_time_s: float,
    bytes_produced: int,
    runner: dict[str, Any],
    receipt_emitter: str = "",
    run_id: str = "",
    external_tokens: int | float | None = None,
    output_attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a schema-valid ``bridge_receipt.v1`` dict.

    ``runner`` must carry exactly the fields required for ``transport`` (see ``RUNNER_FIELDS``); a
    ``cli`` receipt's runner section is ``{"pid": ..., "argv": ..., "exit_code": ...}`` and an
    ``http`` receipt's is ``{"url": ..., "status_code": ..., "model": ...}``. Extra keys in
    ``runner`` are passed through unchanged (forward-compatible), but the required keys for the
    declared transport must all be present or the built receipt will fail ``validate_receipt``.

    Raises ``ValueError`` for an unknown ``transport`` — callers can't accidentally mislabel a
    receipt with a transport this module doesn't know how to validate.
    """
    if transport not in TRANSPORTS:
        raise ValueError(f"unknown transport {transport!r}; expected one of {TRANSPORTS}")

    receipt: dict[str, Any] = {
        "schema": SCHEMA_NAME,
        "engine_id": engine_id,
        "variant": variant,
        "transport": transport,
        "wall_time_s": wall_time_s,
        "bytes_produced": bytes_produced,
        "runner": dict(runner),
    }
    if receipt_emitter:
        receipt["receipt_emitter"] = receipt_emitter
    if run_id:
        receipt["run_id"] = run_id
    if external_tokens is not None:
        receipt["external_tokens"] = external_tokens
    if output_attestation is not None:
        receipt["output_attestation"] = dict(output_attestation)
    return receipt


def validate_receipt(receipt: dict[str, Any]) -> list[str]:
    """Validate a receipt dict against ``bridge_receipt.v1``. Empty list means valid.

    Checks, in order: receipt is a dict; ``schema`` is present and a known version; every common
    field is present; ``transport`` is a known transport; ``runner`` is present and is a dict
    carrying exactly the fields required for the declared transport (missing fields are named;
    fields belonging to the *other* transport's section are flagged as a transport/section
    mismatch rather than silently accepted).
    """
    errors: list[str] = []

    if not isinstance(receipt, dict):
        return [f"receipt must be a dict, got {type(receipt).__name__}"]

    schema = receipt.get("schema")
    if schema is None:
        errors.append("missing required field: schema")
    elif schema not in SCHEMA_VERSIONS:
        errors.append(f"unknown schema version: {schema!r} (expected one of {SCHEMA_VERSIONS})")

    for field in COMMON_FIELDS:
        if field == "schema":
            continue
        if field not in receipt:
            errors.append(f"missing required field: {field}")

    transport = receipt.get("transport")
    if transport is not None and transport not in TRANSPORTS:
        errors.append(f"unknown transport: {transport!r} (expected one of {TRANSPORTS})")

    runner = receipt.get("runner")
    if "runner" not in receipt:
        errors.append("missing required field: runner")
    elif not isinstance(runner, dict):
        errors.append(f"runner must be a dict, got {type(runner).__name__}")
    elif transport in RUNNER_FIELDS:
        required = RUNNER_FIELDS[transport]
        missing = [f for f in required if f not in runner]
        for field in missing:
            errors.append(
                f"runner section missing required field for transport {transport!r}: {field}"
            )

        other_transport = TRANSPORT_HTTP if transport == TRANSPORT_CLI else TRANSPORT_CLI
        other_only = set(RUNNER_FIELDS[other_transport]) - set(required)
        present_other_only = other_only & set(runner)
        if present_other_only and missing:
            errors.append(
                f"runner section looks like {other_transport!r} shape but transport is "
                f"{transport!r}: found {sorted(present_other_only)}, missing {missing}"
            )

    receipt_emitter = receipt.get("receipt_emitter")
    if receipt_emitter is not None and (
        not isinstance(receipt_emitter, str) or not receipt_emitter.strip()
    ):
        errors.append("receipt_emitter must be a non-empty string when present")

    run_id = receipt.get("run_id")
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        errors.append("run_id must be a non-empty string when present")

    external_tokens = receipt.get("external_tokens")
    if external_tokens is not None and (
        isinstance(external_tokens, bool) or not isinstance(external_tokens, (int, float))
    ):
        errors.append("external_tokens must be numeric when present")

    attestation = receipt.get("output_attestation")
    if attestation is not None:
        if not isinstance(attestation, dict):
            errors.append(f"output_attestation must be a dict, got {type(attestation).__name__}")
        else:
            errors.extend(output_attestation.validate_attestation(attestation))

    return errors
