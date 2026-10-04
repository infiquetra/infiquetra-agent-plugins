#!/usr/bin/env python3
"""Cost per completed unit, by role and tier, from saga run records (issue 95).

Issue 90 moved saga's builder from Sonnet to Opus at medium effort on a priced argument: Opus costs
more per token, so it has to finish a unit with fewer tokens to come out ahead. This report is the
measurement that checks the argument. It reads the ``usage`` entries ``run_record.py usage add``
writes onto unit rows, prices them from ``references/model-prices.yaml``, and prints what each
(role, tier) pair spent per completed unit.

Three rules are contract, and the header of every report states the first two:

* **A completed unit** has a green build loop (``build_loop.handed_to_code_review`` is present)
  and its latest code-review result has a terminal outcome that finished the review: ``accepted``
  or ``cycle_cap_best_available``. ``review_incomplete`` is terminal for the review controller but
  the review did not finish, so it is not completed; counting it would make an unreviewed unit look
  cheap. Spend on units that are not completed is shown apart, with each unit's reason.
* **Cost per completed unit** for a (role, tier) group is the group's total cost on completed units
  divided by the number of completed units that have at least one entry in that group.
  The **all roles** line divides only over completed units whose usage is recorded and fully
  priced, and names how many completed units it left out and why (no usage recorded, or some usage
  unpriced), so the bottom line is never spend divided by units that recorded none.
* **The price table is dated.** Its age is always printed. Older than ``--max-age-days`` (30) and
  the report warns on standard output and standard error, then still prints: the warning is the
  point, not a refusal. A model the table does not price is named as unpriced and left out of the
  dollar figures, never priced at zero: a unit whose spend is all unpriced shows ``unpriced``, and
  a figure that leaves unpriced spend out is marked ``+ unpriced``.

Exit codes follow ``run_record.py``: 0 a report was printed (stale or not); 2 a refusal (a bad or
missing price table, PyYAML missing, no records, a record that is not JSON, a usage entry whose
counts are not non-negative integers); 3 an unknown record version. Each refusal is one line on
standard error from ``main``'s single catch.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_record  # noqa: E402  (after the sys.path shim, by design)

#: The price table's version token.
PRICES_SCHEMA = "model_prices.v1"

#: The shipped price table.
DEFAULT_PRICES = Path(__file__).resolve().parents[1] / "references" / "model-prices.yaml"

#: How old the price table may be before the report warns.
DEFAULT_MAX_AGE_DAYS = 30

#: The review-result schema whose entries count. ``review_result.RESULT_SCHEMA``; a test keeps the
#: two equal. Older ``review_result.v1`` entries carry no unit and are ignored.
REVIEW_SCHEMA = "review_result.v2"

#: The code-review outcomes that make a green unit completed. A subset of
#: ``review_consensus.ReviewOutcome``; a test keeps it one.
TERMINAL_REVIEW_OUTCOMES: tuple[str, ...] = ("accepted", "cycle_cap_best_available")

MILLION = Decimal(1_000_000)
MICRO = Decimal("0.000001")


class CostReportError(run_record.RunRecordError):
    """A refusal this script owns. Exit 2, one line."""


@dataclass(frozen=True)
class ModelPrice:
    """One model's row in the price table. ``rates`` is ``None`` when it is not priced."""

    model: str
    vendor: str
    tier: str
    aliases: tuple[str, ...]
    rates: Mapping[str, Decimal] | None


@dataclass(frozen=True)
class PriceTable:
    verified_on: date
    source: str
    path: Path
    models: tuple[ModelPrice, ...]


def _yaml() -> Any:
    """Import PyYAML at first use, so ``--help`` never needs it (the plan_save_contract pattern)."""
    try:
        import yaml
    except ImportError as exc:
        raise CostReportError(
            f"{exc}; install PyYAML (pyyaml>=6.0) into the interpreter running cost_report.py"
        ) from exc
    return yaml


def _as_date(value: Any, path: Path) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CostReportError(f"{path}: verified_on {value!r} is not a YYYY-MM-DD date") from exc


def _rates(model: str, raw: Any, path: Path) -> Mapping[str, Decimal] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CostReportError(f"{path}: {model}.usd_per_million must be a mapping or null")
    keys = set(raw)
    expected = set(run_record.TOKEN_CATEGORIES)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise CostReportError(
            f"{path}: {model}.usd_per_million must carry exactly "
            f"{', '.join(run_record.TOKEN_CATEGORIES)}; missing {missing}, unexpected {extra}"
        )
    rates: dict[str, Decimal] = {}
    for category in run_record.TOKEN_CATEGORIES:
        value = raw[category]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise CostReportError(
                f"{path}: {model}.usd_per_million.{category} must be a non-negative number"
            )
        rates[category] = Decimal(str(value))
    return rates


def load_prices(path: Path) -> PriceTable:
    """Read and validate the price table at *path*."""
    path = Path(path)
    if not path.is_file():
        raise CostReportError(f"no price table at {path}")
    yaml = _yaml()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CostReportError(f"{path} is not valid YAML: {' '.join(str(exc).split())}") from exc
    if not isinstance(raw, dict):
        raise CostReportError(f"{path} does not hold a mapping")
    if raw.get("schema") != PRICES_SCHEMA:
        raise CostReportError(
            f"{path}: unknown price table version {raw.get('schema')!r}; this report reads "
            f"{PRICES_SCHEMA}"
        )
    if "verified_on" not in raw:
        raise CostReportError(f"{path} has no verified_on date")
    verified_on = _as_date(raw["verified_on"], path)
    models_raw = raw.get("models")
    if not isinstance(models_raw, dict) or not models_raw:
        raise CostReportError(f"{path} has no models mapping")
    models = []
    for model, entry in models_raw.items():
        if not isinstance(entry, dict):
            raise CostReportError(f"{path}: model {model!r} is not a mapping")
        if "usd_per_million" not in entry:
            raise CostReportError(f"{path}: model {model!r} has no usd_per_million (use null)")
        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            raise CostReportError(f"{path}: {model}.aliases must be a list")
        models.append(
            ModelPrice(
                model=str(model),
                vendor=str(entry.get("vendor", "")),
                tier=str(entry.get("tier") or model),
                aliases=tuple(str(alias) for alias in aliases),
                rates=_rates(str(model), entry["usd_per_million"], path),
            )
        )
    return PriceTable(
        verified_on=verified_on,
        source=str(raw.get("source", "")),
        path=path,
        models=tuple(models),
    )


def price_age_days(table: PriceTable, today: date) -> int:
    return (today - table.verified_on).days


def is_stale(table: PriceTable, today: date, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> bool:
    """True when the table is MORE than *max_age_days* old: exactly 30 days is still fresh."""
    return price_age_days(table, today) > max_age_days


def resolve_price(table: PriceTable, vendor: str, model: str) -> ModelPrice | None:
    """The table row for *model* by id or alias, for the same vendor; ``None`` when unknown."""
    for row in table.models:
        if row.vendor and vendor and row.vendor != vendor:
            continue
        if model == row.model or model in row.aliases:
            return row
    return None


def tier_label(entry: Mapping[str, Any], table: PriceTable) -> str:
    """``vendor tier/effort``, e.g. ``claude opus/medium`` — the spelling ``staffing.py`` prints."""
    vendor = str(entry.get("vendor", ""))
    model = str(entry.get("model", ""))
    row = resolve_price(table, vendor, model)
    return f"{vendor} {row.tier if row else model}/{entry.get('effort', '')}"


def entry_cost(entry: Mapping[str, Any], price: ModelPrice) -> Decimal | None:
    """The entry's cost in dollars, or ``None`` when its model is not priced."""
    if price.rates is None:
        return None
    counts = entry.get("counts") or {}
    if not isinstance(counts, Mapping):
        raise CostReportError(f"a usage entry's counts are not an object: {counts!r}")
    total = Decimal(0)
    for category in run_record.TOKEN_CATEGORIES:
        value = counts.get(category, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CostReportError(
                f"a usage entry stores {category} as {value!r}, not a non-negative integer"
            )
        total += Decimal(value) * price.rates[category]
    return total / MILLION


def _code_review_history(record: run_record.RunRecord, unit: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in record.review_cycles
        if isinstance(entry, dict)
        and entry.get("schema") == REVIEW_SCHEMA
        and entry.get("unit") == unit
        and entry.get("loop") == "code_review"
    ]


def unit_completed(record: run_record.RunRecord, row: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether *row* is a completed unit, and the reason when it is not."""
    block = row.get("build_loop")
    if not (isinstance(block, dict) and isinstance(block.get("handed_to_code_review"), dict)):
        return False, "build loop not green"
    history = _code_review_history(record, run_record.unit_key(row))
    if not history:
        return False, "no code-review result"
    outcome = history[-1].get("outcome")
    if outcome not in TERMINAL_REVIEW_OUTCOMES:
        return False, f"latest code review is {outcome}"
    return True, ""


def _usage_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    block = row.get(run_record.USAGE_KEY)
    if not isinstance(block, dict):
        return []
    entries = block.get("entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _usd(value: Decimal) -> str:
    """A dollar amount for the report's data, to the millionth of a dollar."""
    return str(value.quantize(MICRO))


def _money(value: Decimal | str | None, *, partial: bool = False) -> str:
    """Dollars to the cent, or ``unpriced`` — never ``$0.00`` for a cost nobody priced.

    *partial* marks a figure that leaves some unpriced spend out: ``$1.20 + unpriced``.
    """
    if value is None:
        return "unpriced"
    text = f"${Decimal(value).quantize(Decimal('0.01'))}"
    return f"{text} + unpriced" if partial else text


def _text(value: Any) -> str:
    """A record-derived string made safe for one report line.

    Model names, roles, units and reasons come from records other writers produced. A newline or an
    escape sequence in one would forge or hide a report line, so a string holding any character
    that is not printable is shown through ``repr`` instead.
    """
    text = str(value)
    return text if text.isprintable() else repr(text)


#: How much of a unit's recorded usage the price table priced.
PRICING_NONE = "no usage"
PRICING_FULL = "priced"
PRICING_PARTIAL = "partial"
PRICING_UNPRICED = "unpriced"


def _pricing(priced: int, unpriced: int) -> str:
    if not priced and not unpriced:
        return PRICING_NONE
    if not unpriced:
        return PRICING_FULL
    return PRICING_PARTIAL if priced else PRICING_UNPRICED


def _unit_cost(cost: Decimal, pricing: str) -> str | None:
    """A unit's cost for the report's data: ``None`` when nothing it spent was priced."""
    return None if pricing in (PRICING_NONE, PRICING_UNPRICED) else _usd(cost)


def build_report(
    records: Iterable[run_record.RunRecord],
    table: PriceTable,
    today: date,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> dict[str, Any]:
    """Assemble the report as plain data; ``render`` turns it into text."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    overall_cost = Decimal(0)
    fully_priced_cost = Decimal(0)
    fully_priced_units = 0
    excluded = {PRICING_NONE: 0, PRICING_UNPRICED: 0}
    completed_units: list[dict[str, Any]] = []
    not_completed: list[dict[str, Any]] = []
    unpriced: dict[str, int] = {}

    for record in records:
        for row in record.units:
            if not isinstance(row, dict):
                continue
            entries = _usage_entries(row)
            unit = run_record.unit_key(row)
            done, reason = unit_completed(record, row)
            unit_cost = Decimal(0)
            priced_entries = unpriced_entries = 0
            # Per (role, tier): the priced spend, and whether any of this unit's spend in that
            # group was unpriced (a model listed with null rates can share a tier with a priced
            # one), so a group's per-unit figure divides only by units it fully priced.
            unit_groups: dict[tuple[str, str], dict[str, Any]] = {}
            for entry in entries:
                label = tier_label(entry, table)
                price = resolve_price(
                    table, str(entry.get("vendor", "")), str(entry.get("model", ""))
                )
                cost = entry_cost(entry, price) if price else None
                key = (str(entry.get("role", "")), label)
                slot = unit_groups.setdefault(key, {"cost": None, "unpriced": False})
                if cost is None:
                    model = str(entry.get("model", ""))
                    unpriced[model] = unpriced.get(model, 0) + 1
                    slot["unpriced"] = True
                    unpriced_entries += 1
                    continue
                slot["cost"] = (slot["cost"] or Decimal(0)) + cost
                unit_cost += cost
                priced_entries += 1
            pricing = _pricing(priced_entries, unpriced_entries)
            if not done:
                if entries:
                    not_completed.append(
                        {
                            "issue": record.issue,
                            "unit": unit,
                            "reason": reason,
                            "cost_usd": _unit_cost(unit_cost, pricing),
                            "pricing": pricing,
                        }
                    )
                continue
            iterations = row.get("build_loop", {}).get("iterations") or []
            cycles = len(_code_review_history(record, unit))
            completed_units.append(
                {
                    "issue": record.issue,
                    "unit": unit,
                    "cost_usd": _unit_cost(unit_cost, pricing),
                    "pricing": pricing,
                    "build_loop_iterations": len(iterations),
                    "code_review_cycles": cycles,
                }
            )
            overall_cost += unit_cost
            if pricing == PRICING_FULL:
                fully_priced_cost += unit_cost
                fully_priced_units += 1
            elif pricing == PRICING_NONE:
                excluded[PRICING_NONE] += 1
            else:
                excluded[PRICING_UNPRICED] += 1
            for key, slot in unit_groups.items():
                group = groups.setdefault(
                    key,
                    {
                        "cost": None,
                        "units": 0,
                        "fully_priced_cost": Decimal(0),
                        "fully_priced_units": 0,
                        "partial": False,
                        "iterations": 0,
                        "cycles": 0,
                    },
                )
                cost = slot["cost"]
                if cost is not None:
                    group["cost"] = (group["cost"] or Decimal(0)) + cost
                if slot["unpriced"]:
                    group["partial"] = True
                else:
                    group["fully_priced_cost"] += cost
                    group["fully_priced_units"] += 1
                group["units"] += 1
                group["iterations"] += len(iterations)
                group["cycles"] += cycles

    rows = []
    for (role, tier), group in sorted(groups.items()):
        units = group["units"]
        cost = group["cost"]
        priced_units = group["fully_priced_units"]
        rows.append(
            {
                "role": role,
                "tier": tier,
                "completed_units": units,
                "fully_priced_units": priced_units,
                "total_usd": None if cost is None else _usd(cost),
                "total_is_partial": group["partial"] and cost is not None,
                "per_completed_unit_usd": (
                    _usd(group["fully_priced_cost"] / priced_units) if priced_units else None
                ),
                "mean_build_loop_iterations": group["iterations"] / units,
                "mean_code_review_cycles": group["cycles"] / units,
            }
        )
    count = len(completed_units)
    age = price_age_days(table, today)
    return {
        "prices": {
            "path": str(table.path),
            "verified_on": table.verified_on.isoformat(),
            "age_days": age,
            "max_age_days": max_age_days,
            "stale": is_stale(table, today, max_age_days),
        },
        "completed_unit_count": count,
        "groups": rows,
        "overall": {
            "total_usd": _usd(overall_cost),
            "total_is_partial": excluded[PRICING_UNPRICED] > 0,
            "fully_priced_units": fully_priced_units,
            "per_completed_unit_usd": (
                _usd(fully_priced_cost / fully_priced_units) if fully_priced_units else None
            ),
            "excluded_no_usage": excluded[PRICING_NONE],
            "excluded_unpriced": excluded[PRICING_UNPRICED],
        },
        "completed_units": completed_units,
        "not_completed": not_completed,
        "unpriced": [{"model": model, "entries": n} for model, n in sorted(unpriced.items())],
    }


def stale_warning(report: Mapping[str, Any]) -> str | None:
    prices = report["prices"]
    if not prices["stale"]:
        return None
    return (
        f"WARNING: the price table was verified {prices['verified_on']}, {prices['age_days']} days "
        f"ago (more than {prices['max_age_days']}); re-verify "
        "plugins/saga/references/model-prices.yaml before trusting these figures"
    )


def render(report: Mapping[str, Any]) -> str:
    prices = report["prices"]
    lines = []
    warning = stale_warning(report)
    if warning:
        lines.append(warning)
    lines.append(
        f"Prices: {Path(prices['path']).name} verified {prices['verified_on']} "
        f"({prices['age_days']} days old)"
    )
    lines.append(
        "Completed unit: build loop green and latest code review "
        + " or ".join(TERMINAL_REVIEW_OUTCOMES)
        + ". Per completed unit = a group's spend on the completed units it fully priced / those"
        + " units."
    )
    lines.append("")
    if not report["completed_unit_count"]:
        lines.append("no completed units yet")
    else:
        lines.append(f"Cost per completed unit ({report['completed_unit_count']} completed units)")
        lines.append(
            "All roles = priced spend / completed units whose usage is recorded and fully priced."
        )
        header = (
            f"{'role':<18} {'tier':<24} {'units':>5} {'per unit':>10} {'total':>10} "
            f"{'loop passes':>11} {'review cycles':>13}"
        )
        lines.append(header)
        for row in report["groups"]:
            lines.append(
                f"{_text(row['role']):<18} {_text(row['tier']):<24} {row['completed_units']:>5} "
                f"{_money(row['per_completed_unit_usd']):>10} "
                f"{_money(row['total_usd'], partial=row['total_is_partial']):>10} "
                f"{row['mean_build_loop_iterations']:>11.1f} {row['mean_code_review_cycles']:>13.1f}"
            )
        for row in report["groups"]:
            if row["total_is_partial"] or row["fully_priced_units"] < row["completed_units"]:
                lines.append(
                    f"  {_text(row['role'])} {_text(row['tier'])}: per unit divides by "
                    f"{row['fully_priced_units']} of {row['completed_units']} completed units; "
                    "the rest had some spend in this row unpriced"
                )
        overall = report["overall"]
        lines.append(
            f"{'all roles':<18} {'':<24} {overall['fully_priced_units']:>5} "
            f"{_money(overall['per_completed_unit_usd']):>10} "
            f"{_money(overall['total_usd'], partial=overall['total_is_partial']):>10}"
        )
        left_out = []
        if overall["excluded_no_usage"]:
            left_out.append(f"{overall['excluded_no_usage']} with no usage recorded")
        if overall["excluded_unpriced"]:
            left_out.append(f"{overall['excluded_unpriced']} with some usage unpriced")
        if left_out:
            lines.append(
                "  completed units left out of the all-roles per-unit figure: "
                + ", ".join(left_out)
            )
    if report["not_completed"]:
        lines.append("")
        lines.append("Not completed (excluded from the figures above)")
        for row in report["not_completed"]:
            lines.append(
                f"  issue {row['issue']} unit {_text(row['unit'])}: {_text(row['reason'])}; "
                f"spent {_money(row['cost_usd'], partial=row['pricing'] == PRICING_PARTIAL)}"
            )
    if report["unpriced"]:
        lines.append("")
        lines.append("Unpriced (not in the price table, or listed without rates; left out of $)")
        for row in report["unpriced"]:
            lines.append(f"  {_text(row['model'])}: {row['entries']} entries")
    return "\n".join(lines) + "\n"


def _read_record(path: Path) -> run_record.RunRecord:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CostReportError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise CostReportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CostReportError(f"{path} does not hold a JSON object")
    return run_record.from_dict(raw, path=path, warn=None)


def collect_records(args: argparse.Namespace) -> list[run_record.RunRecord]:
    paths: list[Path] = [Path(p) for p in args.record or []]
    if args.issue or not paths:
        root = (
            Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
        )
        if args.issue:
            paths.extend(run_record.record_path(root, n) for n in args.issue)
        else:
            paths.extend(sorted(root.glob("issue-*.json")))
    if not paths:
        raise CostReportError("no run records found")
    for path in paths:
        if not path.is_file():
            raise CostReportError(f"no run record at {path}")
    return [_read_record(path) for path in paths]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_report.py",
        description=(
            "Print cost per completed unit, grouped by role and tier, from saga run records. "
            "A completed unit has a green build loop and a latest code review of accepted or "
            "cycle_cap_best_available. Prices come from a dated table; one more than 30 days old "
            "is flagged with a WARNING line."
        ),
    )
    parser.add_argument(
        "--store-root",
        default=None,
        help="Read records from this store instead of the resolved one.",
    )
    parser.add_argument(
        "--issue", type=int, action="append", help="Report on this issue's record (repeatable)."
    )
    parser.add_argument(
        "--record", action="append", help="Report on the record at this path (repeatable)."
    )
    parser.add_argument(
        "--prices", default=str(DEFAULT_PRICES), help="The price table (default: the shipped one)."
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="The date to age the price table against, YYYY-MM-DD (default: today).",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="Warn when the price table is older than this many days (default 30).",
    )
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        table = load_prices(Path(args.prices))
        records = collect_records(args)
        today = args.today or datetime.now(UTC).date()
        report = build_report(records, table, today, max_age_days=args.max_age_days)
    except run_record.UnknownRecordVersionError as exc:
        print(f"cost_report: {exc}", file=sys.stderr)
        return 3
    except run_record.RunRecordError as exc:
        print(f"cost_report: {exc}", file=sys.stderr)
        return 2
    warning = stale_warning(report)
    if warning:
        print(warning, file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        sys.stdout.write(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
