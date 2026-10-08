"""Tests for U1 (R2): the machine-readable work-shape -> tier registry.

Asserts the `work_shapes` block of `staffing.json` parses as JSON, every `default_model` / `default_effort`
is a member of the canonical `MODELS` / `EFFORTS` vocabulary (tier_palette.py), and
all generated work-shape rows of the tier table in `plugins/saga/skills/plan/SKILL.md` are
represented as registry keys.

Issue #93 adds the implementation work shape, the one staffing resolver's precedence, the
Claude-only refusal, and the render-sync guard the tier table's marker has always named.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

FLEET_CORE_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "plugins" / "fleet-core" / "scripts"
STAFFING_PATH = FLEET_CORE_SCRIPTS / "fleet_commons" / "staffing.json"


def _work_shapes() -> dict[str, dict[str, str]]:
    """The work-shape registry, read from the one staffing data file (issue #1021)."""
    document: dict[str, dict[str, dict[str, str]]] = json.loads(
        STAFFING_PATH.read_text(encoding="utf-8")
    )
    return document["work_shapes"]  # type: ignore[return-value]


sys.path.insert(0, str(FLEET_CORE_SCRIPTS))

from fleet_commons.tier_palette import EFFORTS, MODELS  # noqa: E402

# The generated work-shape rows authored at plugins/saga/skills/plan/SKILL.md:298-304.
# "mechanical" splits into two registry keys per R2 (mechanical / purely-mechanical)
# to preserve the sonnet-vs-haiku distinction the prose table draws within one row.
SKILL_MD_ROWS = (
    "judgment",
    "implementation",
    "mechanical",
    "read-only-survey",
    "offload-test-gated",
    "offload",
    "second-opinion",
    "divergence",
)


@pytest.fixture(scope="module")
def registry() -> dict[str, dict[str, str]]:
    return _work_shapes()


def test_tier_policy_is_valid_json() -> None:
    """The staffing registry's work_shapes block parses as JSON and is a non-empty object."""
    data = _work_shapes()
    assert isinstance(data, dict)
    assert data


def test_every_row_has_required_fields(registry: dict[str, dict[str, str]]) -> None:
    for work_shape, row in registry.items():
        assert set(row.keys()) >= {"default_model", "default_effort", "rationale"}, (
            f"{work_shape!r} row missing required fields"
        )


def test_default_model_in_models(registry: dict[str, dict[str, str]]) -> None:
    for work_shape, row in registry.items():
        assert row["default_model"] in MODELS, (
            f"{work_shape!r} default_model {row['default_model']!r} not in {MODELS}"
        )


def test_default_effort_in_efforts(registry: dict[str, dict[str, str]]) -> None:
    for work_shape, row in registry.items():
        assert row["default_effort"] in EFFORTS, (
            f"{work_shape!r} default_effort {row['default_effort']!r} not in {EFFORTS}"
        )


def test_all_skill_md_rows_present(registry: dict[str, dict[str, str]]) -> None:
    """Every generated SKILL.md:298-304 work-shape row is represented.

    "mechanical" is represented by either the bare `mechanical` key or its
    purely-mechanical split (`mechanical` / `purely-mechanical`).
    """
    keys = set(registry.keys())
    for row in SKILL_MD_ROWS:
        if row == "mechanical":
            assert "mechanical" in keys or "purely-mechanical" in keys, (
                "mechanical row (or its purely-mechanical split) missing from registry"
            )
        else:
            assert row in keys, f"SKILL.md row {row!r} missing from registry"


def test_rationale_is_nonempty_string(registry: dict[str, dict[str, str]]) -> None:
    for work_shape, row in registry.items():
        assert isinstance(row["rationale"], str) and row["rationale"].strip(), (
            f"{work_shape!r} rationale must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# U2 (R1/R3/R4, KTD2-KTD4): the resolve() callable and its CLI.
# ---------------------------------------------------------------------------

from fleet_commons import tier_resolver  # noqa: E402
from fleet_commons.tier_resolver import Resolution, TierResolverError, resolve  # noqa: E402


def test_resolve_shapes_judgment() -> None:
    result = resolve(None, "judgment")
    assert isinstance(result, Resolution)
    assert result.model == "opus"
    assert result.effort == "high"
    assert result.because
    assert result.needs_confirm is False


def test_resolve_shapes_purely_mechanical() -> None:
    result = resolve(None, "purely-mechanical")
    assert result.model == "haiku"
    assert result.effort == "medium"
    assert result.needs_confirm is False


def test_resolve_shapes_all_registry_rows() -> None:
    policy = tier_resolver.load_policy()
    for work_shape, row in policy.items():
        result = resolve(None, work_shape)
        assert result.model == row["default_model"]
        assert result.effort == row["default_effort"]


def test_divergence_resolves_to_high_tier_adversarial_chaperone() -> None:
    result = resolve(None, "divergence")
    assert (result.model, result.effort) == ("opus", "high")


def test_resolve_unknown_work_shape_raises() -> None:
    with pytest.raises(TierResolverError):
        resolve(None, "not-a-real-work-shape")


def test_role_tier_alias_resolves_through_registry() -> None:
    # KTD7: role-tier aliases map onto work-shape registry rows and preserve
    # each pre-migration agent tier.
    reviewer = resolve(None, "adversarial-review")
    assert (reviewer.model, reviewer.effort) == ("opus", "high")

    tester = resolve(None, "contract-test")
    assert (tester.model, tester.effort) == ("haiku", "xhigh")

    scanner = resolve(None, "mechanical-scan")
    assert (scanner.model, scanner.effort) == ("haiku", "medium")


def test_cheaper_fallback_one_rung_down() -> None:
    # opus/high -> sonnet/high (weaken model first, per KTD3 and the CLI smoke test).
    result = resolve(None, "judgment")
    assert result.cheaper_fallback == ("sonnet", "high")


def test_cheaper_fallback_one_rung_with_floor_no_op() -> None:
    # haiku/low is the ladder floor (weakest model, lowest effort): the fallback is a
    # no-op equal to the tier, never an error (R3). No policy row sits on the floor since
    # 2026-10-07, so the floor is checked directly and one rung above it through policy.
    assert tier_resolver.cheaper_fallback("haiku", "low") == ("haiku", "low")
    result = resolve(None, "purely-mechanical")
    assert (result.model, result.effort) == ("haiku", "medium")
    assert result.cheaper_fallback == ("haiku", "low")


def test_cheaper_fallback_drops_effort_once_model_is_weakest() -> None:
    # Weakest model (haiku) with a non-floor effort steps effort down one rung
    # instead of the (already-exhausted) model axis.
    assert tier_resolver.cheaper_fallback("haiku", "medium") == ("haiku", "low")


def test_expensive_tier_confirm_gate() -> None:
    # fable (strongest model) or xhigh (highest effort) resolved via override gates
    # operator confirm (KTD4); the ordinary judgment default does not.
    fable_result = resolve(None, "judgment", operator_override={"model": "fable"})
    assert fable_result.needs_confirm is True

    xhigh_result = resolve(None, "judgment", operator_override={"effort": "xhigh"})
    assert xhigh_result.needs_confirm is True

    assert resolve(None, "judgment").needs_confirm is False


def test_operator_override_replaces_model_and_effort() -> None:
    result = resolve(None, "mechanical", operator_override={"model": "haiku", "effort": "low"})
    assert result.model == "haiku"
    assert result.effort == "low"
    assert "operator override" in result.because


def test_operator_override_invalid_model_raises() -> None:
    with pytest.raises(TierResolverError):
        resolve(None, "judgment", operator_override={"model": "not-a-model"})


def test_operator_override_invalid_effort_raises() -> None:
    with pytest.raises(TierResolverError):
        resolve(None, "judgment", operator_override={"effort": "not-an-effort"})


def test_envelope_ceiling_clamps_model() -> None:
    # judgment defaults to opus; a sonnet ceiling clamps it down.
    result = resolve(None, "judgment", envelope_ceiling="sonnet")
    assert result.model == "sonnet"


def test_envelope_ceiling_none_is_ignored() -> None:
    result = resolve(None, "judgment", envelope_ceiling=None)
    assert result.model == "opus"


def test_envelope_ceiling_does_not_upgrade_weaker_model() -> None:
    # purely-mechanical defaults to haiku; an opus ceiling is stronger, so it is a
    # no-op (the ceiling only ever clamps down, never upgrades).
    result = resolve(None, "purely-mechanical", envelope_ceiling="opus")
    assert result.model == "haiku"


def test_envelope_ceiling_invalid_raises() -> None:
    with pytest.raises(TierResolverError):
        resolve(None, "judgment", envelope_ceiling="not-a-model")


def test_imports_from_tier_palette_not_redeclared() -> None:
    # R2/KTD1: tier_resolver must import the vocabulary tuples from tier_palette via
    # fleet_commons_shim rather than re-declaring its own copies.
    from fleet_commons import tier_palette

    # Different import paths (direct package import here vs. tier_resolver's
    # fleet_commons_shim.load) legitimately produce distinct module objects, so
    # compare values, not identity — the load-bearing invariant is that
    # tier_resolver never re-declares its own MODELS/EFFORTS tuples.
    assert tier_resolver.MODELS == tier_palette.MODELS
    assert tier_resolver.EFFORTS == tier_palette.EFFORTS
    assert tier_resolver.model_rank("opus") == tier_palette.model_rank("opus")
    assert tier_resolver.effort_rank("high") == tier_palette.effort_rank("high")


def test_cli_resolve_judgment(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = tier_resolver.main(["resolve", "--work-shape", "judgment"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "opus"
    assert payload["effort"] == "high"
    assert payload["cheaper_fallback"] == {"model": "sonnet", "effort": "high"}


def test_cli_resolve_purely_mechanical(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = tier_resolver.main(["resolve", "--work-shape", "purely-mechanical"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "haiku"
    assert payload["effort"] == "medium"


def test_cli_resolve_unknown_work_shape_errors(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = tier_resolver.main(["resolve", "--work-shape", "not-a-real-work-shape"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Issue #93 (staffing U1): the implementation work shape, the one resolver, the
# Claude-only refusal, and the tier table's render-sync guard.
# ---------------------------------------------------------------------------

from fleet_commons import render_tier_table, staffing  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PLAN_SKILL = REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md"


@pytest.fixture
def no_overlay(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Run from an empty directory so no machine-local overlay can change an answer."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_overlay(root: pathlib.Path, overlay: dict[str, dict[str, str]]) -> None:
    (root / ".saga").mkdir(exist_ok=True)
    (root / ".saga" / "tier-defaults.json").write_text(json.dumps(overlay), encoding="utf-8")


def _registry_with_worker_vendor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, role: str, vendor: str
) -> None:
    document = json.loads(STAFFING_PATH.read_text(encoding="utf-8"))
    document["roles"][role]["vendor"] = vendor
    copy = tmp_path / "staffing.json"
    copy.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(staffing, "STAFFING_PATH", copy)


def test_implementation_resolves_sonnet_high_in_the_policy_layer() -> None:
    result = resolve(None, "implementation")
    assert (result.model, result.effort) == ("sonnet", "high")
    assert result.needs_confirm is False


def test_only_the_implementation_shapes_are_declared_claude_only(
    registry: dict[str, dict[str, str]],
) -> None:
    flagged = {shape for shape, row in registry.items() if "claude_only" in row}
    assert flagged == {"implementation", "implementation-test-gated"}
    assert registry["implementation"]["claude_only"] is True
    assert registry["implementation-test-gated"]["claude_only"] is True


def test_resolve_shape_implementation_is_sonnet_high_from_policy(no_overlay: pathlib.Path) -> None:
    decision = staffing.resolve_shape("implementation")
    assert (decision.vendor, decision.model, decision.effort) == ("claude", "sonnet", "high")
    assert decision.source == "policy"


def test_worker_role_resolves_claude_sonnet_high(no_overlay: pathlib.Path) -> None:
    decision = staffing.resolve_role("worker")
    assert (decision.vendor, decision.model, decision.effort) == ("claude", "sonnet", "high")
    assert decision.work_shape == "implementation"


@pytest.mark.parametrize("role", ["merging-worker", "release-worker"])
def test_merging_and_release_workers_stay_on_mechanical(
    no_overlay: pathlib.Path, role: str
) -> None:
    decision = staffing.resolve_role(role)
    assert (decision.vendor, decision.model, decision.effort) == ("claude", "haiku", "xhigh")
    assert decision.work_shape == "mechanical"
    assert staffing.resolve_shape("mechanical").tier == "haiku/xhigh"


def test_claude_only_shape_refuses_another_vendor(no_overlay: pathlib.Path) -> None:
    with pytest.raises(staffing.StaffingError) as caught:
        staffing.resolve_shape("implementation", vendor="codex")
    assert "implementation" in str(caught.value)
    assert "codex" in str(caught.value)


def test_a_role_pinned_to_another_vendor_through_implementation_fails_loud(
    no_overlay: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_with_worker_vendor(no_overlay, monkeypatch, "worker", "codex")
    with pytest.raises(staffing.StaffingError, match="codex"):
        staffing.resolve_role("worker")


def test_the_claude_only_guard_is_per_shape(
    no_overlay: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The same pin on a judgment-shape role still translates, so the guard is the row's flag and
    # not a blanket refusal of every pinned vendor.
    _registry_with_worker_vendor(no_overlay, monkeypatch, "planner", "codex")
    decision = staffing.resolve_role("planner")
    assert decision.vendor == "codex"
    assert decision.vendor_pinned_by_role is True
    assert decision.model == staffing.vendors()["codex"]["models"]["gpt-5.6-terra"]


def test_the_claude_only_guard_precedes_the_overlay(no_overlay: pathlib.Path) -> None:
    _write_overlay(no_overlay, {"implementation": {"model": "sonnet", "effort": "high"}})
    with pytest.raises(staffing.StaffingError, match="codex"):
        staffing.resolve_shape("implementation", vendor="codex", root=no_overlay)


def test_a_non_boolean_claude_only_flag_fails_loud(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = json.loads(STAFFING_PATH.read_text(encoding="utf-8"))
    document["work_shapes"]["implementation"]["claude_only"] = "yes"
    copy = tmp_path / "staffing.json"
    copy.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(staffing, "STAFFING_PATH", copy)
    with pytest.raises(staffing.StaffingError, match="claude_only"):
        staffing.resolve_shape("implementation", root=tmp_path)


def test_precedence_is_written_once() -> None:
    assert staffing.TIER_PRECEDENCE == ("operator", "overlay", "jev-raise", "policy")


def test_operator_answer_wins_over_every_other_layer(no_overlay: pathlib.Path) -> None:
    _write_overlay(no_overlay, {"implementation": {"model": "sonnet", "effort": "high"}})
    decision = staffing.resolve_shape(
        "implementation",
        root=no_overlay,
        answer={"model": "haiku", "effort": "low"},
        jev_raise={"model": "opus", "effort": "high"},
    )
    assert (decision.tier, decision.source) == ("haiku/low", "operator")


def test_overlay_wins_over_a_recorded_raise(no_overlay: pathlib.Path) -> None:
    _write_overlay(no_overlay, {"implementation": {"model": "sonnet", "effort": "high"}})
    decision = staffing.resolve_shape(
        "implementation", root=no_overlay, jev_raise={"model": "opus", "effort": "high"}
    )
    assert (decision.tier, decision.source) == ("sonnet/high", "overlay")


def test_a_recorded_raise_wins_over_the_policy_default(no_overlay: pathlib.Path) -> None:
    raise_ = {
        "model": "opus",
        "effort": "high",
        "confidence": 0.85,
        "reason": "touches IAM policy",
        "decision_id": "staffing/tier:93",
    }
    decision = staffing.resolve_shape("implementation", root=no_overlay, jev_raise=raise_)
    assert (decision.tier, decision.source) == ("opus/high", "jev-raise")


def test_a_one_model_rung_raise_is_accepted(no_overlay: pathlib.Path) -> None:
    decision = staffing.resolve_shape(
        "purely-mechanical", root=no_overlay, jev_raise={"model": "sonnet", "effort": "medium"}
    )
    assert (decision.tier, decision.source) == ("sonnet/medium", "jev-raise")


@pytest.mark.parametrize(
    ("work_shape", "model", "effort"),
    [("implementation", "sonnet", "xhigh"), ("mechanical", "haiku", "max")],
)
def test_a_raise_above_the_raise_ceiling_is_refused(
    no_overlay: pathlib.Path, work_shape: str, model: str, effort: str
) -> None:
    """One effort rung, on the palette, and still refused: one_step_raise never proposes it."""
    with pytest.raises(staffing.StaffingError, match="raise ceiling"):
        staffing.resolve_shape(
            work_shape, root=no_overlay, jev_raise={"model": model, "effort": effort}
        )


def test_no_layer_present_falls_to_policy(no_overlay: pathlib.Path) -> None:
    decision = staffing.resolve_shape("implementation", root=no_overlay)
    assert (decision.tier, decision.source) == ("sonnet/high", "policy")


@pytest.mark.parametrize(
    ("model", "effort", "why"),
    [
        ("sonnet", "medium", "a lowering"),
        ("opus", "low", "a lowering"),
        ("opus", "medium", "no step at all"),
        ("opus", "xhigh", "two effort rungs"),
        ("fable", "medium", "the strongest model"),
        ("fable", "high", "two axes at once"),
    ],
)
def test_a_raise_that_is_not_exactly_one_step_up_is_refused(
    no_overlay: pathlib.Path, model: str, effort: str, why: str
) -> None:
    with pytest.raises(staffing.StaffingError, match="jev raise"):
        staffing.resolve_shape(
            "implementation", root=no_overlay, jev_raise={"model": model, "effort": effort}
        )


@pytest.mark.parametrize(
    ("model", "effort"),
    [("gpt-5", "high"), ("opus", "max"), ("haiku", "xhigh")],
)
def test_an_off_palette_or_unrunnable_raise_is_refused(
    no_overlay: pathlib.Path, model: str, effort: str
) -> None:
    with pytest.raises(staffing.StaffingError):
        staffing.resolve_shape(
            "implementation", root=no_overlay, jev_raise={"model": model, "effort": effort}
        )


def test_a_malformed_raise_fails_loud_even_when_the_overlay_hides_it(
    no_overlay: pathlib.Path,
) -> None:
    _write_overlay(no_overlay, {"implementation": {"model": "sonnet", "effort": "high"}})
    with pytest.raises(staffing.StaffingError, match="jev raise"):
        staffing.resolve_shape(
            "implementation", root=no_overlay, jev_raise={"model": "sonnet", "effort": "low"}
        )


def test_resolve_role_passes_the_raise_through(no_overlay: pathlib.Path) -> None:
    decision = staffing.resolve_role("worker", jev_raise={"model": "opus", "effort": "high"})
    assert (decision.tier, decision.source) == ("opus/high", "jev-raise")


def test_the_targeted_reviewer_resolves_at_the_judgment_tier(no_overlay: pathlib.Path) -> None:
    """Issue #158: one reviewer per review, tiered like the lens reviewer it will replace."""
    decision = staffing.resolve_role("targeted-reviewer", require_lens=False)
    assert (decision.vendor, decision.model, decision.effort) == ("claude", "opus", "high")
    assert decision.work_shape == "judgment"
    # It reviews, so asking without saying it needs no lens fails loud rather than guessing.
    with pytest.raises(staffing.StaffingError, match="needs a lens"):
        staffing.resolve_role("targeted-reviewer")


def test_undeclared_build_units_run_at_the_worker_shape() -> None:
    assert staffing.unit_work_shape_default() == staffing.roles()["worker"]["work_shape"]
    assert staffing.unit_work_shape_default() == "implementation"


def test_implementation_keeps_its_tier_on_an_unattended_run() -> None:
    assert staffing.unattended_step_down("implementation") is False
    assert staffing.unattended_step_down("judgment") is True


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["resolve", "--shape", "implementation"], "sonnet/high"),
        (["resolve", "--shape", "implementation-test-gated"], "haiku/xhigh"),
        (["resolve", "--role", "worker"], "claude sonnet/high"),
        (["resolve", "--role", "merging-worker"], "claude haiku/xhigh"),
        (["resolve", "--role", "release-worker"], "claude haiku/xhigh"),
    ],
)
def test_staffing_cli_short_forms(
    no_overlay: pathlib.Path, capsys: pytest.CaptureFixture[str], argv: list[str], expected: str
) -> None:
    assert staffing.main(argv) == 0
    assert capsys.readouterr().out.strip() == expected


def _skill_tier_block() -> str:
    text = PLAN_SKILL.read_text(encoding="utf-8")
    begin = text.index(render_tier_table.TIER_TABLE_BEGIN)
    end = text.index(render_tier_table.TIER_TABLE_END) + len(render_tier_table.TIER_TABLE_END)
    return text[begin:end]


def test_skill_registry_sync() -> None:
    """The generated tier table in /plan's skill is byte-identical to the renderer's output."""
    assert _skill_tier_block() == render_tier_table.render_block()


def test_skill_registry_sync_catches_seeded_divergence() -> None:
    policy = json.loads(json.dumps(tier_resolver.load_policy()))
    policy["implementation"]["default_model"] = "opus"
    assert render_tier_table.render_block(policy) != _skill_tier_block()
