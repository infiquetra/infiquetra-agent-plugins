"""``bridge_receipt.v1`` schema module tests (plan U1, #383 DoD 1).

Scenarios: valid CLI receipt round-trips; valid HTTP receipt round-trips; a missing common field
is named in the errors; a runner section shaped for the wrong transport is rejected; an unknown
schema version is rejected; ``emit_receipt`` output always passes ``validate_receipt`` for both
transports (property-style check).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "bridge_receipt.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bridge_receipt_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


br = _load_module()


CLI_RUNNER = {"pid": 12345, "argv": ["codex", "run"], "exit_code": 0}
HTTP_RUNNER = {
    "url": "https://api.deepseek.com/chat/completions",
    "status_code": 200,
    "model": "deepseek-chat",
}


def test_valid_cli_receipt_round_trips() -> None:
    receipt = br.emit_receipt(
        engine_id="codex",
        variant="codex-medium",
        transport="cli",
        wall_time_s=1.23,
        bytes_produced=456,
        runner=CLI_RUNNER,
    )
    assert br.validate_receipt(receipt) == []
    assert receipt["schema"] == br.SCHEMA_NAME
    assert receipt["runner"] == CLI_RUNNER


def test_valid_http_receipt_round_trips() -> None:
    receipt = br.emit_receipt(
        engine_id="deepseek",
        variant="deepseek-high",
        transport="http",
        wall_time_s=4.56,
        bytes_produced=789,
        runner=HTTP_RUNNER,
    )
    assert br.validate_receipt(receipt) == []
    assert receipt["runner"] == HTTP_RUNNER


def test_missing_common_field_named_in_errors() -> None:
    receipt = br.emit_receipt(
        engine_id="codex",
        variant="codex-medium",
        transport="cli",
        wall_time_s=1.0,
        bytes_produced=1,
        runner=CLI_RUNNER,
    )
    del receipt["engine_id"]
    errors = br.validate_receipt(receipt)
    assert any("engine_id" in e for e in errors)


def test_wrong_runner_section_for_declared_transport_rejected() -> None:
    # Declares cli transport but supplies an http-shaped runner section.
    receipt = {
        "schema": br.SCHEMA_NAME,
        "engine_id": "codex",
        "variant": "codex-medium",
        "transport": "cli",
        "wall_time_s": 1.0,
        "bytes_produced": 1,
        "runner": HTTP_RUNNER,
    }
    errors = br.validate_receipt(receipt)
    assert errors
    assert any("pid" in e or "argv" in e or "exit_code" in e for e in errors)


def test_unknown_schema_version_rejected() -> None:
    receipt = br.emit_receipt(
        engine_id="codex",
        variant="codex-medium",
        transport="cli",
        wall_time_s=1.0,
        bytes_produced=1,
        runner=CLI_RUNNER,
    )
    receipt["schema"] = "bridge_receipt.v2"
    errors = br.validate_receipt(receipt)
    assert any("schema" in e for e in errors)


@pytest.mark.parametrize(
    "transport,runner",
    [("cli", CLI_RUNNER), ("http", HTTP_RUNNER)],
)
def test_emit_receipt_output_always_passes_validate(transport: str, runner: dict) -> None:
    receipt = br.emit_receipt(
        engine_id="engine-x",
        variant="engine-x-medium",
        transport=transport,
        wall_time_s=0.1,
        bytes_produced=0,
        runner=runner,
    )
    assert br.validate_receipt(receipt) == []


def test_emit_receipt_rejects_unknown_transport() -> None:
    with pytest.raises(ValueError):
        br.emit_receipt(
            engine_id="x",
            variant="x-medium",
            transport="grpc",
            wall_time_s=0.1,
            bytes_produced=0,
            runner={},
        )


def test_missing_runner_field_named() -> None:
    receipt = {
        "schema": br.SCHEMA_NAME,
        "engine_id": "codex",
        "variant": "codex-medium",
        "transport": "cli",
        "wall_time_s": 1.0,
        "bytes_produced": 1,
        "runner": {"pid": 1, "argv": []},  # missing exit_code
    }
    errors = br.validate_receipt(receipt)
    assert any("exit_code" in e for e in errors)
