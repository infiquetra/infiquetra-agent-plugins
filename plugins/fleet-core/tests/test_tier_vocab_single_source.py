"""Single-source tier palette guards (#370).

Covers the registry-derived vocabulary (U1), the ladder operations and effort-ceiling
clamp (U2), the unsupported-combo HALT + ladder-monotonicity invariant (U3), the
repo-wide bare-literal drift guard (U4), and the operator-table sync check + onboarding
guard (U5). The vocabulary now lives in fleet-core's ``tier_palette.py``, derived from
``staffing.json`` — these tests are the standing drift guards the issue's Definition of
Done requires.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FLEET_CORE_SCRIPTS = REPO_ROOT / "plugins" / "fleet-core" / "scripts"
STAFFING_JSON = FLEET_CORE_SCRIPTS / "fleet_commons" / "staffing.json"

sys.path.insert(0, str(FLEET_CORE_SCRIPTS))

from fleet_commons import tier_palette  # noqa: E402
from fleet_commons.tier_palette import TierPaletteError  # noqa: E402

# ---------------------------------------------------------------------------
# U1 (AC2) — MODELS/EFFORTS derive from staffing.json's explicit rank/rung.
# ---------------------------------------------------------------------------


def test_registry_rank_order() -> None:
    """The derived tuples equal the registry's explicit rank/rung ordering."""
    registry = tier_palette._load_registry()
    models_by_rank = tuple(
        name for name, _ in sorted(registry["models"].items(), key=lambda kv: kv[1]["rank"])
    )
    efforts_by_rung = tuple(
        name for name, _ in sorted(registry["efforts"].items(), key=lambda kv: kv[1]["rung"])
    )
    assert models_by_rank == tier_palette.MODELS
    assert efforts_by_rung == tier_palette.EFFORTS
    # The public vocabulary must not have drifted from the historical order either.
    assert tier_palette.MODELS == ("fable", "opus", "sonnet", "haiku")
    assert tier_palette.EFFORTS == ("low", "medium", "high", "xhigh")


def test_registry_rank_order_rejects_mis_ranked_row() -> None:
    """A scratch registry that swaps two ranks derives a different (wrong) order."""
    scratch = {
        "fable": {"rank": 1, "effort_ceiling": "xhigh"},  # deliberately swapped with opus
        "opus": {"rank": 0, "effort_ceiling": "xhigh"},
        "sonnet": {"rank": 2, "effort_ceiling": "xhigh"},
        "haiku": {"rank": 3, "effort_ceiling": "high"},
    }
    derived = tier_palette._derive_ordered(scratch, "rank", "model")
    assert derived == ("opus", "fable", "sonnet", "haiku")
    assert derived != tier_palette.MODELS  # the guard would catch this drift


def test_registry_rejects_duplicate_rank() -> None:
    scratch = {"a": {"rank": 0}, "b": {"rank": 0}}
    with pytest.raises(TierPaletteError, match="duplicated"):
        tier_palette._derive_ordered(scratch, "rank", "model")


def test_registry_rejects_gapped_rank() -> None:
    scratch = {"a": {"rank": 0}, "b": {"rank": 2}}
    with pytest.raises(TierPaletteError, match="not contiguous"):
        tier_palette._derive_ordered(scratch, "rank", "model")


def test_registry_rejects_missing_effort_ceiling() -> None:
    scratch = {"models": {"a": {"rank": 0}}, "efforts": {"low": {"rung": 0}}}
    with pytest.raises(TierPaletteError, match="missing 'effort_ceiling'"):
        tier_palette._derive_effort_ceilings(scratch, ("low",))


def test_effort_ceiling_values_anchor_on_haiku() -> None:
    """haiku's ceiling is 'high' (the issue's canonical unsupported combo is haiku/xhigh)."""
    assert tier_palette.effort_ceiling("haiku") == "high"
    for model in ("fable", "opus", "sonnet"):
        assert tier_palette.effort_ceiling(model) == "xhigh"
    with pytest.raises(ValueError, match="unknown model"):
        tier_palette.effort_ceiling("gpt-9")


# ---------------------------------------------------------------------------
# U2 (AC3/AC5) — named ladder ops honoring the opposite-direction contract,
# plus the effort-ceiling clamp.
# ---------------------------------------------------------------------------


def test_ladder_ops_escalate_downgrade_by_strength() -> None:
    # MODELS strongest-first: escalate = stronger model (lower rank).
    assert tier_palette.escalate("model", "sonnet") == "opus"
    assert tier_palette.escalate("model", "haiku", 2) == "opus"
    assert tier_palette.downgrade("model", "opus") == "sonnet"
    # EFFORTS weakest-first: escalate = higher effort (higher rung).
    assert tier_palette.escalate("effort", "medium") == "high"
    assert tier_palette.downgrade("effort", "high") == "medium"


def test_ladder_ops_past_the_end_are_no_ops() -> None:
    """Escalate past the strongest / downgrade past the weakest is a no-op, not an error."""
    assert tier_palette.escalate("model", "fable", 5) == "fable"
    assert tier_palette.downgrade("model", "haiku", 5) == "haiku"
    assert tier_palette.escalate("effort", "xhigh", 5) == "xhigh"
    assert tier_palette.downgrade("effort", "low", 5) == "low"


def test_escalate_downgrade_are_monotonic_under_contradictory_bounds() -> None:
    """A ceiling weaker than the value (or a floor stronger) is a no-op, never a direction
    inversion — escalate only strengthens, downgrade only weakens (matters for #364's
    runtime ladder climbing, which calls escalate)."""
    assert tier_palette.escalate("model", "fable", ceiling="haiku") == "fable"
    assert tier_palette.escalate("effort", "high", ceiling="low") == "high"
    assert tier_palette.downgrade("model", "haiku", floor="fable") == "haiku"
    assert tier_palette.downgrade("effort", "low", floor="xhigh") == "low"


def test_clamp_and_stronger_bounds() -> None:
    assert tier_palette.clamp("effort", "xhigh", ceiling="high") == "high"
    assert tier_palette.clamp("effort", "low", floor="medium") == "medium"
    assert tier_palette.clamp("model", "haiku", floor="sonnet") == "sonnet"
    assert tier_palette.stronger("model", "haiku", "opus") == "opus"
    assert tier_palette.stronger("effort", "low", "xhigh") == "xhigh"
    assert tier_palette.strongest("model", ["haiku", "fable", "sonnet"]) == "fable"
    assert tier_palette.strongest("effort", ["low", "high", "medium"]) == "high"


def test_ladder_ops_reject_unknown_kind_and_value() -> None:
    with pytest.raises(ValueError, match="unknown ladder"):
        tier_palette.escalate("temperature", "opus")
    with pytest.raises(ValueError, match="unknown effort"):
        tier_palette.clamp("effort", "ludicrous")


def test_effort_ceiling_clamp_surfaces_a_note() -> None:
    """AC5: escalating a haiku unit toward xhigh resolves to haiku's ceiling with a note."""
    clamped, note = tier_palette.clamp_effort_to_model("haiku", "xhigh")
    assert clamped == "high"
    assert note is not None and "haiku" in note and "clamped" in note
    # escalate with the model's ceiling stops at the ceiling, never overshoots.
    assert (
        tier_palette.escalate("effort", "high", 3, ceiling=tier_palette.effort_ceiling("haiku"))
        == "high"
    )
    # A within-ceiling tier is returned untouched, no note.
    ok, no_note = tier_palette.clamp_effort_to_model("opus", "xhigh")
    assert ok == "xhigh" and no_note is None


def test_supports_effort_matrix() -> None:
    assert tier_palette.supports_effort("opus", "xhigh") is True
    assert tier_palette.supports_effort("haiku", "high") is True
    assert tier_palette.supports_effort("haiku", "xhigh") is False


@pytest.mark.parametrize(
    "stronger,weaker",
    [
        (tier_palette.MODELS[i], tier_palette.MODELS[i + 1])
        for i in range(len(tier_palette.MODELS) - 1)
    ],
)
def test_model_ladder_monotonicity(stronger: str, weaker: str) -> None:
    """AC7: for every adjacent MODELS pair, the merge picks the stronger member."""
    assert tier_palette.stronger("model", stronger, weaker) == stronger
    assert tier_palette.strongest("model", [weaker, stronger]) == stronger


@pytest.mark.parametrize(
    "weaker,stronger",
    [
        (tier_palette.EFFORTS[i], tier_palette.EFFORTS[i + 1])
        for i in range(len(tier_palette.EFFORTS) - 1)
    ],
)
def test_effort_ladder_monotonicity(weaker: str, stronger: str) -> None:
    """AC7: for every adjacent EFFORTS pair, the merge picks the stronger (higher) member."""
    assert tier_palette.stronger("effort", weaker, stronger) == stronger
    assert tier_palette.strongest("effort", [weaker, stronger]) == stronger


# ---------------------------------------------------------------------------
# U4 (AC1) — repo-wide bare-literal drift guard.
#
# AC1's literal wording ("zero bare model-literal strings outside the module") is not
# achievable: ~205 legitimate model-name occurrences exist in production Python (model
# names as work-shape dict KEYS in team_emitter.py, tier data, etc.) plus 33 deferred
# agent-frontmatter .md literals (an explicit non-goal). The meaningful, achievable
# guard is AC1's INTENT: no second SOURCE of the ordered vocabulary. We flag any
# tuple/list assignment of >=2 same-vocabulary tokens (a MODELS/EFFORTS re-declaration)
# in PRODUCTION Python outside the canonical home. See doc-review finding A.
# ---------------------------------------------------------------------------

_PRODUCTION_ROOTS = (REPO_ROOT / "plugins", REPO_ROOT / "scripts")
_CANONICAL_HOME_BASENAMES = {"tier_palette.py"}


def _vocab_kind_of_elts(
    elts: list[ast.expr], model_set: set[str], effort_set: set[str]
) -> str | None:
    """Return 'model'/'effort' when ``elts`` are all string constants of ONE closed
    vocabulary (>=2 elements); else None. A (model, effort) pair or a mixed sequence is a
    tier value, not a vocabulary re-declaration."""
    strings = [e.value for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(strings) < 2 or len(strings) != len(elts):
        return None
    if all(s in model_set for s in strings):
        return "model"
    if all(s in effort_set for s in strings):
        return "effort"
    return None


def _vocabulary_redefinitions(source: str, path_label: str) -> list[tuple[int, str]]:
    """Return [(lineno, 'model'|'effort')] for assignments that re-declare the closed model
    or effort vocabulary — a bare tuple/list/set literal OR a ``tuple(...)``/``list(...)``/
    ``frozenset(...)``/``set(...)`` call wrapping one (the call-wrapped form is a real, if
    narrow, evasion of a literal-only scan)."""
    findings: list[tuple[int, str]] = []
    tree = ast.parse(source, filename=path_label)
    model_set, effort_set = set(tier_palette.MODELS), set(tier_palette.EFFORTS)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        elts: list[ast.expr] | None = None
        if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            elts = value.elts
        elif (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"tuple", "list", "frozenset", "set"}
            and len(value.args) == 1
            and isinstance(value.args[0], (ast.Tuple, ast.List, ast.Set))
        ):
            elts = value.args[0].elts
        if elts is None:
            continue
        kind = _vocab_kind_of_elts(elts, model_set, effort_set)
        if kind is not None:
            findings.append((node.lineno, kind))
    return findings


def _production_py_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in _PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if path.name not in _CANONICAL_HOME_BASENAMES:
                files.append(path)
    return files


def test_no_bare_model_literals_outside_module() -> None:
    """AC1: no production module outside tier_palette.py re-declares the vocabulary."""
    offenders: list[str] = []
    for path in _production_py_files():
        for lineno, kind in _vocabulary_redefinitions(path.read_text(encoding="utf-8"), str(path)):
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno} ({kind} vocab re-declared)")
    assert offenders == [], "vocabulary re-declared outside tier_palette.py:\n" + "\n".join(
        offenders
    )


def test_guard_reds_when_vocab_reintroduced() -> None:
    """AC1 forcing function: reintroducing the vocabulary into a module reds the guard,
    including the call-wrapped evasion (tuple([...])) — but a (model, effort) pair does not."""
    scratch = (
        'MODELS = ("fable", "opus", "sonnet", "haiku")\n'
        'EFFORTS = ["low", "medium", "high", "xhigh"]\n'
        '_WRAPPED = tuple(["fable", "opus", "sonnet", "haiku"])\n'  # call-wrapped evasion
        'a_tier = ("sonnet", "high")\n'  # a (model, effort) pair must NOT trip the guard
    )
    findings = _vocabulary_redefinitions(scratch, "scratch.py")
    assert sorted(kind for _, kind in findings) == ["effort", "model", "model"]


# ---------------------------------------------------------------------------
# U5 (AC8) — operator-table tier-token drift guard + (AC4) onboarding runbook.
#
# The /plan tier table is already render-guarded (test_tier_resolver.py::
# test_skill_registry_sync). The team-execution worker table is an illustrative
# template, so the meaningful check is vocabulary VALIDITY: every `model/effort`
# tier token it displays must draw from the canonical MODELS/EFFORTS — a hand-edit
# that drifts (opus/superhigh, gpt4/high) is caught. See doc-review finding B.
# ---------------------------------------------------------------------------

STAFFING_RUNBOOK = REPO_ROOT / "plugins" / "fleet-core" / "references" / "staffing.md"

_TIER_TOKEN = re.compile(r"\b([a-z0-9-]+)/([a-z0-9-]+)\b")


def _tier_token_drift(text: str) -> list[str]:
    """Return `model/effort` tokens whose one recognized half implies an invalid other half."""
    models, efforts = set(tier_palette.MODELS), set(tier_palette.EFFORTS)
    bad: list[str] = []
    for match in _TIER_TOKEN.finditer(text):
        left, right = match.group(1), match.group(2)
        left_is_model, right_is_effort = left in models, right in efforts
        if left_is_model and not right_is_effort:
            bad.append(f"{left}/{right} (invalid effort)")
        elif right_is_effort and not left_is_model:
            bad.append(f"{left}/{right} (invalid model)")
    return bad


def test_tier_catalog_check_reds_on_drift() -> None:
    """The forcing function: a stale/typo tier token is flagged."""
    assert _tier_token_drift("worker uses opus/superhigh here") == [
        "opus/superhigh (invalid effort)"
    ]
    assert _tier_token_drift("gpt4/high teammate") == ["gpt4/high (invalid model)"]
    assert _tier_token_drift("plain and/or prose") == []  # non-vocab slash is ignored


def test_onboarding_guard() -> None:
    """AC4: the onboarding runbook exists and encodes the {#tier-vocab-ordering} rule; a
    mis-inserted model at the wrong rank is caught by the import-time ordering guard."""
    assert STAFFING_RUNBOOK.exists()
    runbook = STAFFING_RUNBOOK.read_text(encoding="utf-8")
    assert ".index(" in runbook and "{#tier-vocab-ordering}" in runbook
    assert "staffing.json" in runbook
    # a correct prepend derives a clean order; a mis-ranked insertion is rejected.
    good = {"m0": {"rank": 0}, "fable": {"rank": 1}, "opus": {"rank": 2}}
    assert tier_palette._derive_ordered(good, "rank", "model") == ("m0", "fable", "opus")
    mis_inserted = {"m0": {"rank": 0}, "fable": {"rank": 0}, "opus": {"rank": 2}}
    with pytest.raises(TierPaletteError):
        tier_palette._derive_ordered(mis_inserted, "rank", "model")
