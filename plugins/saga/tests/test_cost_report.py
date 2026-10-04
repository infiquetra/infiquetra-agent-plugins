"""Tests for the cost-per-completed-unit report (issue 95).

Every record lives under ``tmp_path``; nothing here reads or writes the primary checkout's store.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import typing
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
SCRIPT = SCRIPTS / "cost_report.py"
SHIPPED_PRICES = REPO_ROOT / "plugins" / "saga" / "references" / "model-prices.yaml"
VERIFIED = date(2026, 10, 3)
SHA = "a" * 40


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cr() -> ModuleType:
    return _load("cost_report")


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store" / "runs"
    root.mkdir(parents=True)
    return root


def _entry(session: str, role: str, model: str, effort: str, **counts: int) -> dict[str, Any]:
    full = dict.fromkeys(
        ("uncached_input", "cache_read", "cache_write_5m", "cache_write_1h", "output"), 0
    )
    full.update(counts)
    return {
        "session_id": session,
        "role": role,
        "vendor": "claude",
        "model": model,
        "effort": effort,
        "counts": full,
        "first_added_at": "2026-10-03T00:00:00+00:00",
        "last_added_at": "2026-10-03T00:00:00+00:00",
        "additions": 1,
    }


def _row(unit: str, *entries: dict[str, Any], green: bool = True, key: str = "id") -> dict:
    build_loop: dict[str, Any] = {"iterations": [{"iteration": 1, "green": False}]}
    if green:
        build_loop["iterations"].append({"iteration": 2, "green": True})
        build_loop["handed_to_code_review"] = {"revision": SHA, "at": "2026-10-03T00:00:00Z"}
    return {key: unit, "build_loop": build_loop, "usage": {"entries": list(entries)}}


def _review(unit: str, outcome: str, cycle: int = 1, loop: str = "code_review") -> dict:
    return {
        "schema": "review_result.v2",
        "unit": unit,
        "loop": loop,
        "cycle": cycle,
        "revision": SHA,
        "outcome": outcome,
    }


def _write(store: Path, issue: int, units: list[dict], reviews: list[dict]) -> Path:
    path = store / f"issue-{issue}.json"
    path.write_text(
        json.dumps(
            {"schema": "run_record.v1", "issue": issue, "units": units, "review_cycles": reviews}
        ),
        encoding="utf-8",
    )
    return path


def _fixture(store: Path) -> Path:
    """Two completed units (Opus builder, Sonnet builder), one lens review each, one incomplete."""
    units = [
        _row(
            "u1",
            _entry(
                "w1",
                "worker",
                "claude-opus-5-5",
                "medium",
                uncached_input=1_000_000,
                output=1_000_000,
            ),
            _entry("r1", "lens-reviewer", "claude-opus-5-5", "high", cache_read=1_000_000),
        ),
        _row(
            "u2",
            _entry(
                "w2",
                "worker",
                "claude-sonnet-5-5",
                "medium",
                uncached_input=1_000_000,
                output=1_000_000,
            ),
            _entry("r2", "lens-reviewer", "claude-opus-5-5", "high", cache_read=3_000_000),
            key="name",
        ),
        _row("u3", _entry("w3", "worker", "claude-opus-5-5", "medium", output=500_000)),
    ]
    reviews = [
        _review("u1", "repairs_requested", 1),
        _review("u1", "accepted", 2),
        _review("u2", "cycle_cap_best_available", 1),
        _review("u3", "repairs_requested", 1),
    ]
    return _write(store, 95, units, reviews)


def _run(store: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--store-root", str(store), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def _report(cr: ModuleType, store: Path, today: date = VERIFIED) -> dict:
    table = cr.load_prices(SHIPPED_PRICES)
    rr = sys.modules["run_record"]
    records = [
        rr.load(store, int(p.stem.split("-")[1]), warn=None)
        for p in sorted(store.glob("issue-*.json"))
    ]
    return cr.build_report(records, table, today)


# ---------------------------------------------------------------------------
# Grouping by role and tier
# ---------------------------------------------------------------------------


def test_cost_per_completed_unit_is_grouped_by_role_and_tier(cr: ModuleType, store: Path) -> None:
    _fixture(store)
    report = _report(cr, store)
    groups = {(g["role"], g["tier"]): g for g in report["groups"]}
    assert set(groups) == {
        ("worker", "claude opus/medium"),
        ("worker", "claude sonnet/medium"),
        ("lens-reviewer", "claude opus/high"),
    }
    opus = groups[("worker", "claude opus/medium")]
    assert Decimal(opus["per_completed_unit_usd"]) == Decimal("24.00")  # 1M x $4 + 1M x $20
    assert opus["completed_units"] == 1
    sonnet = groups[("worker", "claude sonnet/medium")]
    assert Decimal(sonnet["per_completed_unit_usd"]) == Decimal("12.00")  # 1M x $2 + 1M x $10
    lens = groups[("lens-reviewer", "claude opus/high")]
    assert lens["completed_units"] == 2
    assert Decimal(lens["total_usd"]) == Decimal("0.80")  # 4M cache reads x $0.20
    assert Decimal(lens["per_completed_unit_usd"]) == Decimal("0.40")
    assert lens["mean_code_review_cycles"] == 1.5  # u1 took two cycles, u2 one
    assert lens["mean_build_loop_iterations"] == 2
    assert report["completed_unit_count"] == 2
    assert Decimal(report["overall"]["total_usd"]) == Decimal("36.80")
    assert Decimal(report["overall"]["per_completed_unit_usd"]) == Decimal("18.40")


def test_the_report_prints_the_groups_on_a_fixture_record(store: Path) -> None:
    _fixture(store)
    result = _run(store, "--today", "2026-10-03")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "Prices: model-prices.yaml verified 2026-10-03 (0 days old)" in out
    assert "Cost per completed unit (2 completed units)" in out
    assert "claude opus/medium" in out and "$24.00" in out
    assert "claude sonnet/medium" in out and "$12.00" in out
    assert "lens-reviewer" in out and "$0.40" in out
    assert "WARNING" not in out and result.stderr == ""


# ---------------------------------------------------------------------------
# The completed-unit rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("green", "reviews", "completed", "reason"),
    [
        (True, [_review("u", "accepted")], True, ""),
        (True, [_review("u", "cycle_cap_best_available")], True, ""),
        (
            True,
            [_review("u", "accepted", 1), _review("u", "repairs_requested", 2)],
            False,
            "latest code review is repairs_requested",
        ),
        (
            True,
            [_review("u", "review_incomplete")],
            False,
            "latest code review is review_incomplete",
        ),
        (False, [_review("u", "accepted")], False, "build loop not green"),
        (True, [], False, "no code-review result"),
        (True, [_review("u", "accepted", loop="post_merge")], False, "no code-review result"),
        (
            True,
            [{**_review("u", "accepted"), "schema": "review_result.v1"}],
            False,
            "no code-review result",
        ),
        (True, [_review("other", "accepted")], False, "no code-review result"),
    ],
)
def test_the_completed_unit_rule(
    cr: ModuleType, green: bool, reviews: list, completed: bool, reason: str
) -> None:
    rr = sys.modules["run_record"]
    row = _row("u", green=green)
    record = rr.RunRecord(issue=1, units=[row], review_cycles=reviews)
    assert cr.unit_completed(record, row) == (completed, reason)


def test_unit_identity_matches_by_id_then_name(cr: ModuleType) -> None:
    rr = sys.modules["run_record"]
    by_name = _row("u", key="name")
    record = rr.RunRecord(issue=1, units=[by_name], review_cycles=[_review("u", "accepted")])
    assert cr.unit_completed(record, by_name) == (True, "")
    both = {**_row("u"), "name": "ignored"}
    record = rr.RunRecord(issue=1, units=[both], review_cycles=[_review("u", "accepted")])
    assert cr.unit_completed(record, both) == (True, "")


def test_spend_on_incomplete_units_is_shown_apart(cr: ModuleType, store: Path) -> None:
    _fixture(store)
    report = _report(cr, store)
    assert report["not_completed"] == [
        {
            "issue": 95,
            "unit": "u3",
            "reason": "latest code review is repairs_requested",
            "cost_usd": "10.000000",
        }
    ]
    out = cr.render(report)
    assert "Not completed (excluded from the figures above)" in out
    assert "issue 95 unit u3: latest code review is repairs_requested; spent $10.00" in out


def test_no_completed_units_says_so_and_never_prints_zero_dollars(store: Path) -> None:
    _write(
        store, 7, [_row("u1", _entry("w", "worker", "opus", "medium", output=1), green=False)], []
    )
    result = _run(store, "--today", "2026-10-03")
    assert result.returncode == 0, result.stderr
    assert "no completed units yet" in result.stdout
    assert "Cost per completed unit (" not in result.stdout


# ---------------------------------------------------------------------------
# The stale price-table flag
# ---------------------------------------------------------------------------


def test_a_table_exactly_30_days_old_is_not_flagged(store: Path) -> None:
    _fixture(store)
    result = _run(store, "--today", (VERIFIED + timedelta(days=30)).isoformat())
    assert result.returncode == 0
    assert "WARNING" not in result.stdout and "WARNING" not in result.stderr
    assert "(30 days old)" in result.stdout


def test_a_table_31_days_old_is_flagged_on_stdout_and_stderr(store: Path) -> None:
    _fixture(store)
    result = _run(store, "--today", (VERIFIED + timedelta(days=31)).isoformat())
    assert result.returncode == 0
    warning = (
        "WARNING: the price table was verified 2026-10-03, 31 days ago (more than 30); "
        "re-verify plugins/saga/references/model-prices.yaml before trusting these figures"
    )
    assert result.stdout.splitlines()[0] == warning
    assert result.stderr.strip() == warning
    assert "$24.00" in result.stdout, "a stale table still prints the report"


def test_is_stale_boundary(cr: ModuleType) -> None:
    table = cr.load_prices(SHIPPED_PRICES)
    assert not cr.is_stale(table, VERIFIED + timedelta(days=30))
    assert cr.is_stale(table, VERIFIED + timedelta(days=31))
    assert cr.is_stale(table, VERIFIED + timedelta(days=8), max_age_days=7)


# ---------------------------------------------------------------------------
# Unpriced models
# ---------------------------------------------------------------------------


def test_unpriced_and_unknown_models_are_named_and_never_shown_as_zero(
    cr: ModuleType, tmp_path: Path, store: Path
) -> None:
    prices = tmp_path / "prices.yaml"
    prices.write_text(
        SHIPPED_PRICES.read_text(encoding="utf-8").replace(
            "    usd_per_million:\n      uncached_input: 1.00\n      cache_read: 0.10\n"
            "      cache_write_5m: 1.25\n      cache_write_1h: 2.00\n      output: 5.00\n",
            "    usd_per_million: null\n",
        ),
        encoding="utf-8",
    )
    assert "usd_per_million: null" in prices.read_text(encoding="utf-8")
    units = [
        _row(
            "u1",
            _entry("w", "worker", "claude-opus-5-5", "medium", output=1_000_000),
            _entry("h", "worker", "claude-haiku-4-5", "low", output=1_000_000),
            _entry("x", "worker", "claude-unknown-9", "low", output=1_000_000),
        )
    ]
    _write(store, 3, units, [_review("u1", "accepted")])
    result = _run(store, "--prices", str(prices), "--today", "2026-10-03", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["unpriced"] == [
        {"model": "claude-haiku-4-5", "entries": 1},
        {"model": "claude-unknown-9", "entries": 1},
    ]
    groups = {g["tier"]: g for g in report["groups"]}
    assert groups["claude haiku/low"]["per_completed_unit_usd"] is None
    assert groups["claude claude-unknown-9/low"]["total_usd"] is None
    assert Decimal(report["overall"]["total_usd"]) == Decimal("20")

    text = _run(store, "--prices", str(prices), "--today", "2026-10-03").stdout
    haiku_line = next(line for line in text.splitlines() if "claude haiku/low" in line)
    assert "unpriced" in haiku_line and "$0.00" not in haiku_line
    assert "claude-unknown-9: 1 entries" in text


# ---------------------------------------------------------------------------
# The price table
# ---------------------------------------------------------------------------


def _table_with(tmp_path: Path, old: str, new: str) -> Path:
    path = tmp_path / "bad.yaml"
    text = SHIPPED_PRICES.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("      cache_write_1h: 8.00\n", ""),
        ("      output: 20.00\n", "      output: 20.00\n      cache_write_2h: 9.00\n"),
        ("      output: 20.00\n", "      output: -20.00\n"),
        ("schema: model_prices.v1", "schema: model_prices.v2"),
        ("verified_on: 2026-10-03", "verified_on: last tuesday"),
    ],
)
def test_a_malformed_price_table_exits_2_with_one_line(
    tmp_path: Path, store: Path, old: str, new: str
) -> None:
    _fixture(store)
    result = _run(store, "--prices", str(_table_with(tmp_path, old, new)))
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.count("\n") == 1 and "Traceback" not in result.stderr


def test_no_records_and_an_unknown_record_version_refuse_with_one_line(store: Path) -> None:
    result = _run(store)
    assert result.returncode == 2 and result.stderr.startswith("cost_report: no run records found")
    (store / "issue-1.json").write_text(json.dumps({"schema": "run_record.v2"}), encoding="utf-8")
    result = _run(store)
    assert result.returncode == 3
    assert result.stderr.count("\n") == 1 and "run_record.v2" in result.stderr


def test_the_shipped_table_carries_the_verified_rates(cr: ModuleType) -> None:
    table = cr.load_prices(SHIPPED_PRICES)
    assert table.verified_on == VERIFIED
    opus = cr.resolve_price(table, "claude", "claude-opus-5-5")
    sonnet = cr.resolve_price(table, "claude", "sonnet")
    assert opus is not None and sonnet is not None
    assert {k: str(v) for k, v in opus.rates.items()} == {
        "uncached_input": "4.0",
        "cache_read": "0.2",
        "cache_write_5m": "5.0",
        "cache_write_1h": "8.0",
        "output": "20.0",
    }
    assert {k: str(v) for k, v in sonnet.rates.items()} == {
        "uncached_input": "2.0",
        "cache_read": "0.2",
        "cache_write_5m": "2.5",
        "cache_write_1h": "4.0",
        "output": "10.0",
    }
    assert cr.resolve_price(table, "codex", "opus") is None, "a vendor never borrows Claude's rates"


# ---------------------------------------------------------------------------
# Cross-checks, so the constants cannot drift from their owners
# ---------------------------------------------------------------------------


def test_terminal_outcomes_are_review_consensus_outcomes(cr: ModuleType) -> None:
    consensus = _load("review_consensus")
    assert set(cr.TERMINAL_REVIEW_OUTCOMES) <= set(typing.get_args(consensus.ReviewOutcome))
    assert "review_incomplete" not in cr.TERMINAL_REVIEW_OUTCOMES


def test_review_schema_is_the_review_result_schema(cr: ModuleType) -> None:
    assert cr.REVIEW_SCHEMA == _load("review_result").RESULT_SCHEMA


def test_the_shipped_table_prices_exactly_the_record_categories(cr: ModuleType) -> None:
    rr = sys.modules["run_record"]
    for row in cr.load_prices(SHIPPED_PRICES).models:
        assert row.rates is None or tuple(row.rates) == rr.TOKEN_CATEGORIES


def test_json_output_carries_the_groups_and_the_staleness_fields(store: Path) -> None:
    _fixture(store)
    result = _run(store, "--today", "2026-11-04", "--json")
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["prices"] == {
        "path": str(SHIPPED_PRICES),
        "verified_on": "2026-10-03",
        "age_days": 32,
        "max_age_days": 30,
        "stale": True,
    }
    assert {(g["role"], g["tier"]) for g in report["groups"]} == {
        ("worker", "claude opus/medium"),
        ("worker", "claude sonnet/medium"),
        ("lens-reviewer", "claude opus/high"),
    }
    assert "WARNING" in result.stderr


def test_help_exits_0() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "completed unit" in result.stdout and "30 days" in result.stdout
