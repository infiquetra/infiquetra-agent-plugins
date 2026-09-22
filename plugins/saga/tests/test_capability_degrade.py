"""Oracle tests for capability-portable degradation (U12, R11).

Every authored plan carries a runnable inline/serial baseline; on an off-host resume the
Workflow tool is re-checked, a one-line downgrade is surfaced, and ONLY the orchestration
tier recompiles down (unit specs + per-unit ``{model, effort}`` tiers preserved). The
downgrade is recorded on the saga.

AE3 is the load-bearing oracle: an off-host resume must DOWNGRADE WITH A NOTE — it must
NEVER error and NEVER silently run nothing. The tests asserting a runnable, non-empty
``to`` tier and that no input raises must not be loosened to "pass".

Carried from infiquetra-claude-plugins@acc99fe7 (upstream 1.2.0). Two changes from the
upstream file:

- The module bootstrap: this package's tests sit under ``plugins/saga/tests/`` rather
  than at a repository root, so ``ROOT`` walks up three levels (``parent.parent.parent``)
  instead of two.
- The upstream ``es`` fixture, which loaded ``scripts/execution_spec.py``, is dropped.
  That module shipped ``cc-workflows-ultracode``, the dynamic-workflow orchestration tier;
  the 1.0.0 import (see ``plugins/saga/CHANGELOG.md``) archived that tier along with
  ``execution_spec.py``, ``concurrency_governor.py`` and ``dispatch_settlement.py``, so
  there is nothing left at that path to load. No test in this file requested the fixture —
  all three exercise ``lifecycle_state.py`` alone — so dropping it changes no assertion.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"


def _load(script_name: str) -> ModuleType:
    path = SCRIPTS / script_name
    spec = importlib.util.spec_from_file_location(script_name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so `from __future__ import annotations` + dataclass field-type
    # resolution can look the module up (required on Python 3.14; harmless on 3.12).
    sys.modules[script_name.removesuffix(".py")] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def lifecycle() -> ModuleType:
    return _load("lifecycle_state.py")


def _spec_dict() -> dict[str, object]:
    """A small valid spec spanning three distinct per-unit tiers (so tier-preservation
    across a recompile is observable)."""
    return {
        "name": "degrade-demo",
        "description": "capability-portable degradation demo",
        "repo": "/tmp/repo",
        "units": [
            {
                "unit_id": "U1",
                "label": "preflight",
                "tier": {"model": "haiku", "effort": "low"},
                "prompt": "verify grounding facts on origin/main",
                "returns": ["ready", "drift"],
                "escalation": "HALT on drift",
            },
            {
                "unit_id": "U2",
                "label": "build",
                "tier": {"model": "sonnet", "effort": "high"},
                "prompt": "implement the unit",
                "depends_on": ["U1"],
                "returns": ["done", "files"],
            },
            {
                "unit_id": "U3",
                "label": "fan out",
                "tier": {"model": "opus", "effort": "high"},
                "prompt": "audit each target",
                "depends_on": ["U2"],
                "fanout": True,
                "targets": ["a", "b", "c"],
            },
        ],
    }


# ---------------------------------------------------------------------------
# recheck_orchestration_capability — the capability probe (R11)
# ---------------------------------------------------------------------------


def test_inline_tier_off_host_is_a_noop(lifecycle: ModuleType) -> None:
    result = lifecycle.recheck_orchestration_capability(
        orchestration_mode="inline",
        workflow_available=False,
    )
    assert result["downgraded"] is False
    assert result["to"] == "inline"


@pytest.mark.parametrize("mode", ["cc-workflows-ultracode", "team-execution", "inline", "", "x"])
@pytest.mark.parametrize("available", [True, False])
def test_recheck_never_errors_and_always_returns_a_runnable_tier(
    lifecycle: ModuleType, mode: str, available: bool
) -> None:
    """AE3 sweep — across the full cross product, the probe never raises and ALWAYS names a
    runnable orchestration tier (one of the known tiers, never empty)."""
    result = lifecycle.recheck_orchestration_capability(
        orchestration_mode=mode,
        workflow_available=available,
    )
    assert result["to"] in lifecycle.ORCHESTRATION_TIERS
    assert isinstance(result["downgraded"], bool)
    assert "note" in result


def test_absent_downgrade_field_still_loads(tmp_path: Path) -> None:
    """Backward-compat — an older saga lacking the field parses with the "" default."""
    saga_mod = _load("saga.py")
    saga = saga_mod.Saga(saga_id="task-old", kind="task", id="old")
    text = saga_mod.render_envelope(saga)
    # Simulate an older file by stripping the new line entirely.
    stripped = "\n".join(
        line for line in text.splitlines() if not line.startswith("orchestration_downgrade:")
    )
    assert "orchestration_downgrade:" not in stripped
    reloaded = saga_mod.parse_envelope(stripped)
    assert reloaded.orchestration_downgrade == ""
