"""Tests for the shared output_attestation.v1 helper (#388)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "output_attestation.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("output_attestation_under_test", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


OA = _load()


def test_emit_attestation_hashes_content() -> None:
    attestation = OA.emit_attestation(artifact="evidence", content="delegated output")

    assert attestation["schema"] == "output_attestation.v1"
    assert attestation["bytes"] == len(b"delegated output")
    assert attestation["empty"] is False
    assert OA.validate_attestation(attestation, expected_content="delegated output") == []


def test_validate_attestation_rejects_hash_mismatch() -> None:
    attestation = OA.emit_attestation(artifact="evidence", content="real delegated output")

    errors = OA.validate_attestation(attestation, expected_content="claude-only output")

    assert any("output-attestation-mismatch" in error for error in errors)


def test_validate_attestation_rejects_required_empty_output() -> None:
    attestation = OA.emit_attestation(artifact="diff.patch", content="")

    errors = OA.validate_attestation(attestation, require_non_empty=True)

    assert "proof-integrity: output-attestation-empty" in errors
