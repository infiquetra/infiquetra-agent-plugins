"""Tests for U1 (R2): the machine-readable work-shape -> tier registry.

Asserts the `work_shapes` block of `staffing.json` parses as JSON, every `default_model` / `default_effort`
is a member of the canonical `MODELS` / `EFFORTS` vocabulary (tier_palette.py), and
all generated work-shape rows from `plugins/saga/skills/plan/SKILL.md:298-304` are
represented as registry keys.
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
    assert result.effort == "low"
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
    assert (tester.model, tester.effort) == ("sonnet", "medium")

    scanner = resolve(None, "mechanical-scan")
    assert (scanner.model, scanner.effort) == ("haiku", "low")


def test_cheaper_fallback_one_rung_down() -> None:
    # opus/high -> sonnet/high (weaken model first, per KTD3 and the CLI smoke test).
    result = resolve(None, "judgment")
    assert result.cheaper_fallback == ("sonnet", "high")


def test_cheaper_fallback_one_rung_with_floor_no_op() -> None:
    # haiku/low is already the ladder floor (weakest model, lowest effort): the
    # fallback is a no-op equal to the resolved tier, never an error (R3).
    result = resolve(None, "purely-mechanical")
    assert result.model == "haiku"
    assert result.effort == "low"
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
    assert payload["effort"] == "low"


def test_cli_resolve_unknown_work_shape_errors(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = tier_resolver.main(["resolve", "--work-shape", "not-a-real-work-shape"])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err
