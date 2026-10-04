#!/usr/bin/env python3
"""The tier judgment at admission and in ``/plan``'s tier table (issue #96).

Fleet Core's staffing component owns the judgment itself: the question it asks TypeSafe Jev,
the bands an answer falls into, the one-step raise, and the resolver that honors a recorded raise.
This module is saga's half, shared by ``admission.py`` and ``/plan``:

* :func:`issue_state` builds the issue part of the state Jev judges from: the issue's title and
  body and the four keyword flags ``parse_issue.extract`` computes (security, API, infrastructure,
  privacy). Every one is permitted by the data rule in fleet-core's ``references/typesafe.md``.
  It never calls ``parse_issue.widen_flags``, which would be a second request.
* :func:`log_labels` writes each judgment's verdict once the operator's final tier is known,
  labeled ``below``, ``same`` or ``above`` relative to the default, and marks the block so it is
  never logged twice.
* The ``plan`` command asks once for every plan unit and records each unit's judgment, and any
  automatic raise as ``jev_raise``, under the plan unit's id in the run record's top-level
  ``tier_judgments`` map. The ``label`` command records the tier ``/plan`` finally chose for each
  unit there as ``planned_tier`` and logs the labels. The ``raise`` command prints one unit's
  recorded ``jev_raise`` (or ``null``) for ``/work`` to pipe into ``--jev-raise -``.

The plan-unit judgments live in a top-level map of their own, never on the ``units`` rows: those
rows belong to the writers that run units (orchestrate, the build loop), and a row this module
invented (one holding only an ``id``) cannot be loaded by orchestrate and is dropped by its save.

``INFIQUETRA_TYPESAFE_TIERING=off`` switches the judgment off: no request is made and every unit
keeps its default. Exit codes are the run record's: 0 success, 2 a refusal, 3 an unknown record
version.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import run_record  # noqa: E402  (after the sys.path shim, by design)

#: The ``parse_issue.extract`` flags the judgment sends: the four the card names. ``has_refactor``
#: says nothing about the tier a unit needs, so it stays home.
ISSUE_FLAGS: tuple[str, ...] = ("has_security", "has_api", "has_infra", "has_privacy")

#: The request budget at admission and in ``/plan``: a slow endpoint costs at most this long, and
#: then the defaults stand (the fail-open rule).
TOTAL_DEADLINE_SECONDS = 20.0
MAX_ATTEMPTS = 2

#: The run-wide key in the staffing map that says whether the judgment ran (``status``, ``note``).
RUN_WIDE_KEY = "_tier_judgment"

#: The run record's top-level key holding ``/plan``'s per-unit judgments, keyed by plan unit id.
#: Each entry holds ``tier_judgment``, ``jev_raise`` (an automatic raise only) and
#: ``planned_tier``. It is an unknown top-level field to ``run_record.py``, so every reader and
#: writer preserves it unchanged, orchestrate's ``Run.save`` included.
PLAN_KEY = "tier_judgments"


class TierJudgmentError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


def load_staffing() -> Any:
    """Fleet Core's staffing component from saga's bundle, or ``None`` when it is unreachable."""
    try:
        import bundled_fleet  # noqa: PLC0415

        return bundled_fleet.load("staffing")
    except Exception:
        return None


def issue_state(title: str, body: str) -> dict[str, Any]:
    """The issue as the judgment sees it: title, body and the four keyword flags."""
    import parse_issue  # noqa: PLC0415

    flags = parse_issue.extract(body or "").get("flags") or {}
    return {
        "title": title or "",
        "body": body or "",
        "flags": {name: bool(flags.get(name)) for name in ISSUE_FLAGS},
    }


def decision_prefix(staffing: Any, repo: str, issue: int, kind: str) -> str:
    """``staffing/tier-direction:<repo>#<issue>:<kind>``: run-scoped, so ``jev eval`` can score
    the same role or unit across many runs instead of once in total."""
    return f"{staffing.JUDGMENT_DECISION_PREFIX}:{repo or 'unknown'}#{int(issue)}:{kind}"


def consult(
    staffing: Any,
    units: Mapping[str, Mapping[str, Any]],
    *,
    issue: Mapping[str, Any],
    prefix: str,
    ask: Any = None,
    getenv: Any = None,
    cache: bool = False,
) -> dict[str, Any]:
    """One batched consult with saga's request budget; a missing entry point reads as an error."""
    entry = getattr(staffing, "consult_tier_suggestions", None)
    if not callable(entry):
        return {
            "status": "error",
            "note": "the staffing component has no tier judgment entry point",
            "judgments": {},
        }
    try:
        outcome = entry(
            units,
            issue=issue,
            decision_prefix=prefix,
            ask=ask,
            getenv=getenv,
            cache=cache,
            max_attempts=MAX_ATTEMPTS,
            total_deadline=TOTAL_DEADLINE_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 - the defaults stand whatever happens here
        return {
            "status": "error",
            "note": f"the tier judgment raised {type(exc).__name__}",
            "judgments": {},
        }
    return outcome if isinstance(outcome, dict) else {"status": "error", "judgments": {}}


def _tier(value: Any) -> dict[str, str] | None:
    if isinstance(value, Mapping) and value.get("model") and value.get("effort"):
        return {"model": str(value["model"]), "effort": str(value["effort"])}
    if isinstance(value, str) and value.count("/") == 1:
        model, effort = value.split("/")
        return {"model": model, "effort": effort}
    return None


def log_labels(
    staffing: Any,
    blocks: Mapping[str, dict[str, Any]],
    finals: Mapping[str, Any],
    *,
    log_dir: Path | None = None,
) -> dict[str, str]:
    """Log each unlabeled judgment with its label, and mark the block ``labeled`` in place.

    ``finals`` maps the same keys to the tier the operator finally accepted. The label is
    ``staffing.tier_direction(default, final)``: what the operator's answer says the right
    direction was. A block already labeled, a block with no answer, and a key with no final tier
    are left alone. Returns ``{key: label}`` for what was logged.
    """
    pending: dict[str, dict[str, Any]] = {}
    labels: dict[str, str] = {}
    for key, block in blocks.items():
        final = _tier(finals.get(key))
        default = _tier(block.get("default")) if isinstance(block, Mapping) else None
        if (
            final is None
            or default is None
            or block.get("labeled")
            or not isinstance(block.get("answer"), Mapping)
        ):
            continue
        try:
            labels[key] = staffing.tier_direction(default, final)
        except Exception:  # noqa: BLE001 - an off-palette final tier has no direction to label
            continue
        pending[key] = block
    if not pending:
        return {}
    try:
        written = staffing.record_tier_verdicts(pending, labels, log_dir=log_dir)
    except Exception:  # noqa: BLE001 - evidence is never worth failing a run for
        return {}
    for key in written:
        pending[key]["labeled"] = labels[key]
    return {key: labels[key] for key in written}


# ---------------------------------------------------------------------------
# /plan: one consult for every unit, recorded under the record's ``tier_judgments`` map
# ---------------------------------------------------------------------------


def _read_json(path: str) -> Any:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, ValueError) as exc:
        raise TierJudgmentError(f"could not read JSON from {path}: {exc}") from exc


def read_units(path: str) -> list[dict[str, Any]]:
    """The units file: a JSON list of ``{id, goal, files, work_shape}``; ``work_shape`` optional."""
    units = _read_json(path)
    if not isinstance(units, list) or not units:
        raise TierJudgmentError("the units file must be a non-empty JSON list of unit objects")
    seen: set[str] = set()
    for unit in units:
        if not isinstance(unit, dict) or not str(unit.get("id") or "").strip():
            raise TierJudgmentError(f"every unit needs an id, got {unit!r}")
        if str(unit["id"]) in seen:
            raise TierJudgmentError(f"unit id {unit['id']!r} appears twice")
        seen.add(str(unit["id"]))
        files = unit.get("files", [])
        if not isinstance(files, list):
            raise TierJudgmentError(f"unit {unit['id']!r}: files must be a list of paths")
    return units


def plan_units(
    staffing: Any, units: list[dict[str, Any]], *, root: Path | None = None
) -> dict[str, dict[str, Any]]:
    """Each plan unit as a judgment unit, its default from the one staffing resolver.

    A unit with no work shape runs at the ``worker`` role's. A tier the repository overlay set is
    operator-set, so an automatic raise never overrides it.
    """
    built: dict[str, dict[str, Any]] = {}
    for unit in units:
        shape = str(unit.get("work_shape") or staffing.unit_work_shape_default())
        try:
            decision = staffing.resolve_shape(shape, root=root)
        except Exception as exc:
            raise TierJudgmentError(f"unit {unit['id']!r}: {exc}") from exc
        task = {
            "description": str(unit.get("goal") or unit.get("label") or unit["id"]),
            "work_shape": decision.work_shape,
            "goal": str(unit.get("goal") or ""),
            "files": [str(path) for path in unit.get("files") or []],
        }
        built[str(unit["id"])] = staffing.judgment_unit(
            task,
            {"model": decision.model, "effort": decision.effort},
            operator_set=decision.source in ("operator", "overlay"),
        )
    return built


def plan_judgments(record: run_record.RunRecord) -> dict[str, dict[str, Any]]:
    """A deep copy of *record*'s ``tier_judgments`` map, ``{}`` when it has none or it is malformed.

    Entries that are not objects are dropped: they carry nothing this module could use.
    """
    raw = record.extra.get(PLAN_KEY)
    if not isinstance(raw, Mapping):
        return {}
    copied = json.loads(json.dumps(raw))
    return {str(key): value for key, value in copied.items() if isinstance(value, dict)}


def plan_entry(record: run_record.RunRecord, unit_id: str) -> dict[str, Any] | None:
    """The ``tier_judgments`` entry for *unit_id*, or ``None``. ``/work`` reads ``jev_raise`` here."""
    return plan_judgments(record).get(str(unit_id))


def _with_plan_judgments(
    record: run_record.RunRecord, judgments: dict[str, dict[str, Any]]
) -> run_record.RunRecord:
    extra = {**record.extra, PLAN_KEY: judgments}
    return run_record.RunRecord(**{**record.__dict__, "extra": extra})


def _summary(unit_id: str, block: Mapping[str, Any]) -> dict[str, Any]:
    default = block.get("default")
    proposed = block.get("proposed")
    applied = bool(block.get("applied"))
    return {
        "id": unit_id,
        "default": default,
        "proposed": proposed,
        "tier": proposed if applied else default,
        "band": block.get("band"),
        "confidence": block.get("confidence"),
        "applied": applied,
        "shown": bool(block.get("shown")),
        "reason": block.get("reason", ""),
    }


def run_plan(
    issue: int,
    repo: str,
    *,
    store_root: Path,
    units: list[dict[str, Any]],
    title: str,
    body: str,
    staffing: Any,
    root: Path | None = None,
    dry_run: bool = False,
    ask: Any = None,
    getenv: Any = None,
) -> dict[str, Any]:
    """Judge every plan unit in one request and record each judgment under ``tier_judgments``.

    Each plan unit's entry, keyed by its id, gets its ``tier_judgment`` block and, for an
    automatic raise, its ``jev_raise``, which ``/work`` pipes into
    ``lifecycle_state.py resolve-build-unit-tier --jev-raise -``. The ``units`` rows are never
    touched. Returns the rows to show in ``/plan``'s tier table.
    """
    if not dry_run and run_record.load(store_root, issue, warn=None) is None:
        raise TierJudgmentError(
            f"no run record for issue {issue}; run admission.py --issue {issue} first"
        )
    judgment_units = plan_units(staffing, units, root=root)
    outcome = consult(
        staffing,
        judgment_units,
        issue=issue_state(title, body),
        prefix=decision_prefix(staffing, repo, issue, "unit"),
        ask=ask,
        getenv=getenv,
        cache=True,
    )
    judgments = outcome.get("judgments") or {}
    blocks: dict[str, dict[str, Any]] = {}
    for unit_id, unit in judgment_units.items():
        block = judgments.get(unit_id)
        if not isinstance(block, dict):
            block = {
                "band": "not-consulted",
                "default": unit["default"],
                "proposed": None,
                "applied": False,
                "shown": False,
                "reason": outcome.get("note") or "not consulted",
            }
        blocks[unit_id] = block

    # Only an answered consult writes: a switched-off or failed one leaves every entry, and any
    # raise an earlier consult recorded, exactly as it was.
    if not dry_run and outcome.get("status") == "ok":

        def change(current: run_record.RunRecord | None) -> run_record.RunRecord:
            if current is None:
                raise TierJudgmentError(f"the run record for issue {issue} disappeared")
            judgments = plan_judgments(current)
            for unit_id, block in blocks.items():
                entry = judgments.setdefault(unit_id, {})
                entry["tier_judgment"] = block
                raised = staffing.jev_raise_from(block)
                if raised is not None:
                    entry["jev_raise"] = raised
                else:
                    entry.pop("jev_raise", None)
            return _with_plan_judgments(current, judgments)

        run_record.update(store_root, issue, change)

    return {
        "status": outcome.get("status"),
        "note": outcome.get("note", ""),
        "units": [_summary(unit_id, block) for unit_id, block in blocks.items()],
    }


def run_label(
    issue: int,
    *,
    store_root: Path,
    finals: Mapping[str, Any],
    staffing: Any,
    log_dir: Path | None = None,
) -> dict[str, str]:
    """Record each unit's final tier as ``planned_tier`` and log its judgment's label, once.

    The entry is created when the plan consult wrote none (the judgment was off or failed), so the
    final tier is recorded either way.
    """
    parsed: dict[str, dict[str, str]] = {}
    for unit_id, value in finals.items():
        tier = _tier(value)
        if tier is None:
            raise TierJudgmentError(f"unit {unit_id!r}: the final tier must be 'model/effort'")
        parsed[str(unit_id)] = tier
    logged: dict[str, str] = {}

    def change(current: run_record.RunRecord | None) -> run_record.RunRecord:
        if current is None:
            raise TierJudgmentError(f"no run record for issue {issue}")
        judgments = plan_judgments(current)
        blocks: dict[str, dict[str, Any]] = {}
        for unit_id, tier in parsed.items():
            entry = judgments.setdefault(unit_id, {})
            entry["planned_tier"] = tier
            if isinstance(entry.get("tier_judgment"), dict):
                blocks[unit_id] = entry["tier_judgment"]
        logged.update(log_labels(staffing, blocks, parsed, log_dir=log_dir))
        return _with_plan_judgments(current, judgments)

    run_record.update(store_root, issue, change)
    return logged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tier_judgment.py",
        description=(
            "Ask TypeSafe Jev whether each plan unit needs a weaker, the same, or a stronger "
            "tier than its default, and record the answer in the run record's "
            "tier_judgments map. "
            "INFIQUETRA_TYPESAFE_TIERING=off makes no request."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="judge every plan unit in one request")
    plan.add_argument("--issue", type=int, required=True)
    plan.add_argument("--repo", default=None, help="owner/name; defaults to the origin remote")
    plan.add_argument("--units", required=True, help="JSON list of {id, goal, files, work_shape}")
    plan.add_argument("--store-root", default=None)
    plan.add_argument("--repo-root", default=None, help="where the tier overlay is read")
    plan.add_argument("--dry-run", action="store_true", help="print the rows; write nothing")
    label = sub.add_parser("label", help="record each unit's final tier and log the labels")
    label.add_argument("--issue", type=int, required=True)
    label.add_argument("--final", required=True, help='JSON {"<unit id>": "model/effort"}')
    label.add_argument("--store-root", default=None)
    raised = sub.add_parser(
        "raise", help="print a plan unit's recorded jev_raise as JSON, or null when it has none"
    )
    raised.add_argument("--issue", type=int, required=True)
    raised.add_argument("--unit", required=True, help="the plan unit's id")
    raised.add_argument("--store-root", default=None)
    return parser


def _store_root(value: str | None) -> Path:
    return Path(value).resolve() if value else run_record.resolve_store_root()


def main(argv: list[str] | None = None) -> int:
    # Imported here, not at the top: admission imports this module.
    import admission  # noqa: PLC0415

    args = build_parser().parse_args(argv)
    try:
        staffing = load_staffing()
        if staffing is None:
            raise TierJudgmentError("fleet-core's staffing component could not be loaded")
        store_root = _store_root(args.store_root)
        if args.command == "plan":
            repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
            repo = args.repo or admission.default_repo(repo_root)
            units = read_units(args.units)
            payload = admission.fetch_issue(args.issue, repo)
            result = run_plan(
                args.issue,
                repo,
                store_root=store_root,
                units=units,
                title=str(payload.get("title") or ""),
                body=str(payload.get("body") or ""),
                staffing=staffing,
                root=repo_root,
                dry_run=args.dry_run,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "raise":
            record = run_record.load(store_root, args.issue, warn=None)
            if record is None:
                raise TierJudgmentError(f"no run record for issue {args.issue}")
            entry = plan_entry(record, args.unit) or {}
            raise_ = entry.get("jev_raise")
            print(json.dumps(raise_ if isinstance(raise_, dict) else None, sort_keys=True))
            return 0
        finals = _read_json(args.final)
        if not isinstance(finals, dict):
            raise TierJudgmentError('the final file must be a JSON object {"<unit id>": "m/e"}')
        logged = run_label(args.issue, store_root=store_root, finals=finals, staffing=staffing)
        print(json.dumps({"labeled": logged}, indent=2, sort_keys=True))
        return 0
    except run_record.UnknownRecordVersionError as exc:
        print(f"tier_judgment: {exc}", file=sys.stderr)
        return 3
    except (TierJudgmentError, admission.AdmissionError, run_record.RunRecordError) as exc:
        print(f"tier_judgment: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
