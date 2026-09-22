"""Tests U2 (R7/R8, KTD1/KTD2): the fleet effort-honoring seam.

`EFFORT_RIDER` carries one prompt-preamble directive per canonical `tier_palette.EFFORTS` value;
`inject_effort(prompt, effort, spawn_kind)` prepends the rider only on the native Agent-tool
(`spawn_kind="agent"`) path and passes through the two real-knob paths (`workflow`,
`external-engine`) without double-injecting. Unknown effort or spawn_kind raises.

Loaded two ways: directly via sys.path (fast unit assertions) and cross-plugin via
`fleet_commons_shim.load("effort_rider")` (R8: consumed like tier_palette / tier_resolver).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

FLEET_CORE_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "plugins" / "fleet-core" / "scripts"
sys.path.insert(0, str(FLEET_CORE_SCRIPTS))

from fleet_commons import effort_rider  # noqa: E402
from fleet_commons.tier_palette import EFFORTS  # noqa: E402


def test_rider_has_nonempty_directive_for_every_effort() -> None:
    # No missing key, and no empty/whitespace directive.
    assert set(effort_rider.EFFORT_RIDER) == set(EFFORTS)
    for effort in EFFORTS:
        assert effort_rider.EFFORT_RIDER[effort].strip()


def test_agent_kind_prepends_rider() -> None:
    prompt = "do the thing"
    out = effort_rider.inject_effort(prompt, "high", "agent")
    assert out == effort_rider.EFFORT_RIDER["high"] + "\n\n" + prompt
    assert out.startswith(effort_rider.EFFORT_RIDER["high"])
    assert out.endswith(prompt)


def test_workflow_kind_is_pass_through() -> None:
    # Real knob already rides in agent({effort}) opts — do NOT double-inject.
    prompt = "do the thing"
    assert effort_rider.inject_effort(prompt, "high", "workflow") == prompt


def test_external_engine_kind_is_pass_through() -> None:
    prompt = "do the thing"
    assert effort_rider.inject_effort(prompt, "xhigh", "external-engine") == prompt


@pytest.mark.parametrize("effort", EFFORTS)
def test_agent_kind_prepends_for_all_efforts(effort: str) -> None:
    prompt = "payload"
    out = effort_rider.inject_effort(prompt, effort, "agent")
    assert out == effort_rider.EFFORT_RIDER[effort] + "\n\n" + prompt


def test_unknown_spawn_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown spawn_kind"):
        effort_rider.inject_effort("p", "high", "bogus")


def test_unknown_effort_raises() -> None:
    with pytest.raises(ValueError, match="unknown effort"):
        effort_rider.inject_effort("p", "extreme", "agent")


def test_rider_text_present_in_constructed_teammate_spawn_prompt() -> None:
    """U4 (R7/R8): a teammate's constructed Agent-tool spawn prompt carries the rider text.

    Mirrors team-execution SKILL.md Step B1 ("Persistent Resident Workers"): the resident
    worker's task prompt is built first, then run through inject_effort(..., "agent") before
    the Agent-tool spawn — the resolved effort's rider directive must be present verbatim in
    the final prompt handed to the spawn call.
    """
    task_prompt = "Implement U1: add the effort field to the frontmatter schema."
    resolved_effort = "high"
    spawn_prompt = effort_rider.inject_effort(task_prompt, resolved_effort, "agent")
    assert effort_rider.EFFORT_RIDER[resolved_effort] in spawn_prompt
    assert task_prompt in spawn_prompt


def test_reconcile_effort_real_knob_match_emits_none() -> None:
    # R9: a match emits nothing on either real-knob path.
    assert effort_rider.reconcile_effort("high", "workflow", manifest_effort="high") is None
    assert (
        effort_rider.reconcile_effort("xhigh", "external-engine", manifest_effort="xhigh") is None
    )


def test_reconcile_effort_real_knob_mismatch_emits_named_drift_line() -> None:
    line = effort_rider.reconcile_effort("high", "workflow", manifest_effort="medium")
    assert line is not None
    assert "tiering-drift" in line
    assert "workflow" in line
    assert "high" in line
    assert "medium" in line


def test_reconcile_effort_agent_path_match_emits_none() -> None:
    prompt = effort_rider.inject_effort("do the thing", "high", "agent")
    assert effort_rider.reconcile_effort("high", "agent", spawn_prompt=prompt) is None


def test_reconcile_effort_agent_path_mismatch_names_rider_text_not_reasoning_spend() -> None:
    """KTD7: the Agent-tool-path drift line names 'rider-text' as the compared quantity — it
    must never claim to observe actual harness reasoning spend."""
    prompt = "no rider directive was prepended here"
    line = effort_rider.reconcile_effort("high", "agent", spawn_prompt=prompt)
    assert line is not None
    assert "tiering-drift" in line
    assert "rider-text" in line
    # The line may explain what it does NOT claim ("not reasoning spend"), but must never
    # assert reasoning spend as the thing it compared.
    assert "compared quantity reasoning spend" not in line


def test_reconcile_effort_real_knob_requires_manifest_effort() -> None:
    with pytest.raises(ValueError, match="requires manifest_effort"):
        effort_rider.reconcile_effort("high", "workflow")


def test_reconcile_effort_agent_path_requires_spawn_prompt() -> None:
    with pytest.raises(ValueError, match="requires spawn_prompt"):
        effort_rider.reconcile_effort("high", "agent")


def test_reconcile_effort_unknown_effort_raises() -> None:
    with pytest.raises(ValueError, match="unknown effort"):
        effort_rider.reconcile_effort("extreme", "workflow", manifest_effort="extreme")


def test_reconcile_effort_unknown_spawn_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown spawn_kind"):
        effort_rider.reconcile_effort("high", "bogus", manifest_effort="high")


def test_loadable_from_its_own_directory() -> None:
    """The portable package loads the module from fleet_commons, not the discovery shim."""
    assert set(effort_rider.EFFORT_RIDER) == set(EFFORTS)
    assert effort_rider.inject_effort("p", "low", "workflow") == "p"
    assert effort_rider.inject_effort("p", "low", "agent") == effort_rider.EFFORT_RIDER["low"] + "\n\np"
