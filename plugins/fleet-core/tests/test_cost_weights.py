"""Tests for #366 U1: the ordinal cost-weight table + ``to_spend()``.

Covers the acceptance criterion `uv run pytest tests/test_cost_weights.py -k monotonicity`
plus the load-time completeness / off-palette / drift guards that keep the hand-authored
16-cell table honest against the live ``tier_palette`` ordering.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

FLEET_CORE_SCRIPTS = pathlib.Path(__file__).resolve().parents[3] / "plugins" / "fleet-core" / "scripts"
sys.path.insert(0, str(FLEET_CORE_SCRIPTS))

from fleet_commons import cost_weights as CW  # noqa: E402,N812
from fleet_commons.tier_palette import EFFORTS, MODELS  # noqa: E402


def test_to_spend_monotonicity() -> None:
    """Every single step up either axis strictly increases weight; the strongest/highest
    corner outranks the weakest/lowest (fable/xhigh > every haiku cell)."""
    # Effort axis (weakest-first): weight strictly increases along EFFORTS for each model.
    for model in MODELS:
        for weaker, stronger in zip(EFFORTS, EFFORTS[1:], strict=False):
            assert CW.to_spend(model, stronger) > CW.to_spend(model, weaker)
    # Model axis (strongest-first): the stronger model is strictly more expensive per effort.
    for effort in EFFORTS:
        for stronger_model, weaker_model in zip(MODELS, MODELS[1:], strict=False):
            assert CW.to_spend(stronger_model, effort) > CW.to_spend(weaker_model, effort)
    # Corner invariant (AC1): fable/xhigh exceeds every haiku cell.
    strongest_model, weakest_model = MODELS[0], MODELS[-1]
    highest_effort = EFFORTS[-1]
    for effort in EFFORTS:
        assert CW.to_spend(strongest_model, highest_effort) > CW.to_spend(weakest_model, effort)


def test_cost_weights_completeness_all_cells() -> None:
    """load_cost_weights() returns every MODELS x EFFORTS cell (the full 16-cell grid)."""
    table = CW.load_cost_weights()
    assert set(table) == set(MODELS)
    for model in MODELS:
        assert set(table[model]) == set(EFFORTS)
    assert sum(len(row) for row in table.values()) == len(MODELS) * len(EFFORTS)


def test_load_cost_weights_returns_defensive_copy() -> None:
    """Mutating the returned grid does not corrupt the module cache."""
    table = CW.load_cost_weights()
    table[MODELS[0]][EFFORTS[0]] = -999
    assert CW.to_spend(MODELS[0], EFFORTS[0]) != -999


def test_cost_weights_drift_guard_fails_loud() -> None:
    """A non-monotonic or missing-cell table fails validation loudly (drift guard)."""
    # Non-monotonic on the effort axis: flatten a step so `stronger <= weaker`.
    broken = CW.load_cost_weights()
    broken[MODELS[0]][EFFORTS[1]] = broken[MODELS[0]][EFFORTS[0]]
    with pytest.raises(CW.CostWeightsError, match="non-monotonic"):
        CW._validate_table(broken)
    # Missing a cell entirely.
    incomplete = CW.load_cost_weights()
    del incomplete[MODELS[-1]][EFFORTS[-1]]
    with pytest.raises(CW.CostWeightsError, match="missing"):
        CW._validate_table(incomplete)


def test_off_palette_key_rejected() -> None:
    """A cell for a model/effort outside the closed palette fails validation."""
    off_model = CW.load_cost_weights()
    off_model["gpt5"] = dict(off_model[MODELS[0]])
    with pytest.raises(CW.CostWeightsError, match="off-palette model"):
        CW._validate_table(off_model)
    off_effort = CW.load_cost_weights()
    off_effort[MODELS[0]]["ultra"] = 999
    with pytest.raises(CW.CostWeightsError, match="off-palette effort"):
        CW._validate_table(off_effort)


def test_to_spend_unknown_tier_raises() -> None:
    """to_spend() on a tier outside the palette raises rather than returning a default."""
    with pytest.raises(CW.CostWeightsError):
        CW.to_spend("gpt5", "high")
    with pytest.raises(CW.CostWeightsError):
        CW.to_spend(MODELS[0], "ultra")


def test_load_table_rejects_non_int_cell(tmp_path: pathlib.Path) -> None:
    """A bool or non-int weight in the JSON fails the load (bool is an int subclass)."""
    bad = tmp_path / "cost_weights.json"
    bad.write_text('{"weights": {"fable": {"low": true}}}', encoding="utf-8")
    with pytest.raises(CW.CostWeightsError, match="must be an int"):
        CW._load_table(bad)
