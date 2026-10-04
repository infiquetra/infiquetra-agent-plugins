#!/usr/bin/env python3
"""A plan's functional checks: read from the plan, written onto the run record, mapped to criteria.

Pre-review testing U3 (issue #98). ``build_loop.py`` has always read ``functional_checks`` and
``scenario_smoke`` from a unit's row, and recorded ``none-prescribed`` because no step wrote them.
This module is that step, and the check that the plan proves every acceptance criterion.

The plan grammar, documented for planners in ``skills/plan/references/plan-sections.md``:

* Under each ``### U<N>.`` heading inside ``## Implementation Units``, one fenced block whose info
  string is exactly ``functional-checks``. It holds a YAML list; each entry is
  ``{name, command, proves, runs}``. ``proves`` names the criteria it proves as ``AC-<n>``, the
  criterion's 1-based position in the issue's ``### Acceptance criteria`` list. ``runs`` is
  ``local`` (run in the unit's own loop) or ``environment`` (run against the repository's declared
  functional-test environment, on the combined branch).
* Under a plan-level ``## Scenario Smoke`` heading, one fenced ``scenario-smoke`` block in the same
  shape, every entry ``runs: environment``. Or, for a change that carries no code, one fenced
  ``functional-test-waiver`` block, ``reason: <why>``: the Planner's run-level waiver, which plan
  review checks. A plan carries the smoke or the waiver, not both.

Three subcommands:

* ``extract --plan P`` prints what the plan declares, as JSON.
* ``write --plan P (--issue N | --record PATH)`` sets each matched unit row's ``functional_checks``
  to that unit's entries and its ``scenario_smoke`` to the plan's smoke, in exactly the shape
  ``build_loop.py`` reads. Every other key on every row is left alone, and the write is idempotent.
  It holds the record's lock across the read and the write (``references/run-record.md``). In a
  record orchestrate drives, a plan unit with no row yet is reported as pending (exit 5), not
  refused: its row arrives with ``orchestrate expand``, and ``/work`` re-runs the write then.
* ``map --plan P (--issue N | --body-file F)`` says which criterion each check proves, and names
  each criterion no check proves. ``/doc-review`` turns every unmapped criterion into a blocking
  finding. A run whose functional testing is waived skips the mapping and says so.

House testability pattern, mirroring ``build_loop.py``: every filesystem function takes its path
or root as an explicit argument, the issue body reader is injectable, and nothing does I/O at
import.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_loop  # noqa: E402  (after the sys.path shim, by design)
import functional_environment  # noqa: E402
import parse_issue  # noqa: E402
import run_record  # noqa: E402

#: The fenced-block info strings this module reads. Exact matches only.
FENCE_CHECKS = "functional-checks"
FENCE_SMOKE = "scenario-smoke"
FENCE_WAIVER = "functional-test-waiver"

#: The plan sections the blocks live in.
UNITS_SECTION = "Implementation Units"
SMOKE_SECTION = "Scenario Smoke"

#: The two places a check runs. ``environment`` is the repository's declared functional-test
#: environment, run once on the combined branch before code review (pre-review testing U4).
RUNS_LOCAL = "local"
RUNS_ENVIRONMENT = "environment"
RUNS_VALUES: tuple[str, ...] = (RUNS_LOCAL, RUNS_ENVIRONMENT)

#: An entry's keys, in the order they are written onto a unit row.
ENTRY_KEYS: tuple[str, ...] = ("name", "command", "proves", "runs")

#: The unit-row keys this module writes. ``build_loop.py`` reads both.
ROW_CHECKS_KEY = "functional_checks"
ROW_SMOKE_KEY = "scenario_smoke"

#: A criterion reference: ``AC-<n>``, n from 1.
AC_REF_RE = re.compile(r"^AC-[1-9][0-9]*$")
_UNIT_HEADING_RE = re.compile(r"^(U[0-9]+)(?:[.:\s]|$)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)")

#: Mapping statuses.
STATUS_READY = "ready"
STATUS_NOT_READY = "not-ready"
STATUS_WAIVED = "waived"

#: Exit codes, the same table ``build_loop.py`` and ``run_record.py`` share for refusals.
EXIT_OK = 0
#: Not a refusal: the plan leaves a criterion unproven, or its blocks are malformed.
EXIT_NOT_READY = 1
EXIT_REFUSED = build_loop.EXIT_REFUSED
EXIT_UNKNOWN_VERSION = build_loop.EXIT_UNKNOWN_VERSION
#: ``write`` only, and not a refusal: the record is driven by orchestrate and some plan units have
#: no row yet. The rows that exist were written; the rest wait for the ``/work`` unit that
#: orchestrate's ``expand`` adds, which re-runs ``write`` before its first build-loop iteration.
#: Distinct from every ``build_loop.py`` code (0 to 4) so a caller can tell it apart.
EXIT_PENDING = 5


class FunctionalChecksError(ValueError):
    """A refusal this module owns. The command line maps it to ``EXIT_REFUSED``."""


# ---------------------------------------------------------------------------
# Reading the plan.
# ---------------------------------------------------------------------------


@dataclass
class PlanChecks:
    """What a plan declares. ``problems`` is empty when every block is well formed."""

    #: Every unit the plan names, in document order, each with its checks (possibly none).
    units: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    smoke: list[dict[str, Any]] = field(default_factory=list)
    #: The Planner's run-level waiver, ``{"reason": ...}``, or ``None``.
    waiver: dict[str, str] | None = None
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "units": {uid: [dict(e) for e in entries] for uid, entries in self.units.items()},
            "scenario_smoke": [dict(e) for e in self.smoke],
            "waiver": dict(self.waiver) if self.waiver is not None else None,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class _Fence:
    info: str
    line: int
    content: str
    section: str | None
    unit: str | None


def _scan(text: str) -> tuple[list[str], list[_Fence]]:
    """The unit ids under Implementation Units, and every fenced block with where it sits.

    Headings inside a fenced block are not headings, so the scan tracks fences as CommonMark does:
    a block closes on a line of the same fence character at least as long as the opening one.
    """
    units: list[str] = []
    fences: list[_Fence] = []
    section: str | None = None
    unit: str | None = None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        opened = _FENCE_OPEN_RE.match(line)
        if opened:
            marker, info = opened.group(1), opened.group(2)
            body: list[str] = []
            index += 1
            while index < len(lines):
                closing = lines[index].strip()
                if closing.startswith(marker[0] * len(marker)) and not closing.strip(marker[0]):
                    break
                body.append(lines[index])
                index += 1
            fences.append(_Fence(info, index - len(body), "\n".join(body), section, unit))
            index += 1
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if level <= 2:
                section, unit = title, None
            elif section is not None and UNITS_SECTION.lower() in section.lower():
                matched = _UNIT_HEADING_RE.match(title)
                if matched:
                    unit = matched.group(1)
                    units.append(unit)
                elif level == 3:
                    unit = None
        index += 1
    return units, fences


def _in_section(fence: _Fence, name: str) -> bool:
    return fence.section is not None and name.lower() in fence.section.lower()


def entry_problems(
    raw: Any, where: str, *, smoke: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """Check one block's YAML list and return ``(normalised entries, problems)``.

    Each entry is normalised to ``{name, command, proves, runs}``, with ``proves`` always a list.
    """
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{where}: the block must hold a YAML list of checks"]
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    for position, item in enumerate(raw, start=1):
        label = f"{where}, entry {position}"
        if not isinstance(item, dict):
            problems.append(f"{label}: each check is a mapping of {', '.join(ENTRY_KEYS)}")
            continue
        unexpected = sorted(str(key) for key in item if key not in ENTRY_KEYS)
        if unexpected:
            problems.append(f"{label}: unexpected keys {', '.join(unexpected)}")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{label}: needs a name")
            name = ""
        label = f"{where}, check {name.strip()!r}" if name.strip() else label
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            problems.append(f"{label}: needs a command")
            command = ""
        else:
            try:
                if not shlex.split(command):
                    problems.append(f"{label}: the command is empty")
            except ValueError as exc:
                problems.append(f"{label}: the command does not parse: {exc}")
        proves_raw = item.get("proves")
        proves = [proves_raw] if isinstance(proves_raw, str) else proves_raw
        if not isinstance(proves, list) or not proves:
            problems.append(f"{label}: needs proves, the AC-<n> criteria it proves")
            proves = []
        else:
            bad = [str(ref) for ref in proves if not AC_REF_RE.match(str(ref))]
            if bad:
                problems.append(
                    f"{label}: proves {', '.join(bad)}, which is not AC-<n> (the criterion's "
                    "position in the issue's Acceptance criteria list)"
                )
        runs = item.get("runs")
        if runs not in RUNS_VALUES:
            problems.append(f"{label}: runs must be {' or '.join(RUNS_VALUES)}, not {runs!r}")
        elif smoke and runs != RUNS_ENVIRONMENT:
            problems.append(
                f"{label}: the scenario smoke runs against the declared environment "
                f"(runs: {RUNS_ENVIRONMENT})"
            )
        entries.append(
            {
                "name": name.strip(),
                "command": command.strip(),
                "proves": [str(ref) for ref in proves],
                "runs": runs,
            }
        )
    return entries, problems


def _load_yaml(fence: _Fence, where: str) -> tuple[Any, str | None]:
    try:
        return yaml.safe_load(fence.content), None
    except yaml.YAMLError as exc:
        return None, f"{where}: the block is not valid YAML: {exc}"


def parse_plan(text: str) -> PlanChecks:
    """Read every functional-check block in *text*. Never raises for a malformed block."""
    unit_ids, fences = _scan(text)
    plan = PlanChecks()
    for uid in unit_ids:
        if uid in plan.units:
            plan.problems.append(f"unit {uid} is named by more than one heading")
        plan.units.setdefault(uid, [])
    seen_checks: set[str] = set()
    smoke_blocks = 0
    waiver_blocks = 0
    for fence in fences:
        where = f"line {fence.line}"
        if fence.info == FENCE_CHECKS:
            if fence.unit is None or not _in_section(fence, UNITS_SECTION):
                plan.problems.append(
                    f"{where}: a {FENCE_CHECKS} block sits outside a `### U<N>.` unit in "
                    f"{UNITS_SECTION}"
                )
                continue
            where = f"unit {fence.unit}"
            if fence.unit in seen_checks:
                plan.problems.append(f"{where}: more than one {FENCE_CHECKS} block")
                continue
            seen_checks.add(fence.unit)
            raw, error = _load_yaml(fence, where)
            if error:
                plan.problems.append(error)
                continue
            entries, problems = entry_problems(raw, where)
            plan.units[fence.unit] = entries
            plan.problems.extend(problems)
        elif fence.info in (FENCE_SMOKE, FENCE_WAIVER):
            if not _in_section(fence, SMOKE_SECTION):
                plan.problems.append(
                    f"{where}: a {fence.info} block sits outside the plan-level "
                    f"## {SMOKE_SECTION} section"
                )
                continue
            if fence.info == FENCE_SMOKE:
                smoke_blocks += 1
                if smoke_blocks > 1:
                    plan.problems.append(f"{where}: more than one {FENCE_SMOKE} block")
                    continue
                raw, error = _load_yaml(fence, "the scenario smoke")
                if error:
                    plan.problems.append(error)
                    continue
                entries, problems = entry_problems(raw, "the scenario smoke", smoke=True)
                plan.smoke = entries
                plan.problems.extend(problems)
            else:
                waiver_blocks += 1
                if waiver_blocks > 1:
                    plan.problems.append(f"{where}: more than one {FENCE_WAIVER} block")
                    continue
                raw, error = _load_yaml(fence, "the functional-test waiver")
                if error:
                    plan.problems.append(error)
                    continue
                reason = raw.get("reason") if isinstance(raw, dict) else None
                if not isinstance(raw, dict) or set(raw) != {"reason"}:
                    plan.problems.append(
                        "the functional-test waiver must be exactly `reason: <why>`"
                    )
                if not isinstance(reason, str) or not reason.strip():
                    plan.problems.append(
                        "the functional-test waiver needs a reason: say why this change carries "
                        "no code to test"
                    )
                else:
                    plan.waiver = {"reason": reason.strip()}

    names = [entry["name"] for entries in plan.units.values() for entry in entries]
    names += [entry["name"] for entry in plan.smoke]
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    if duplicates:
        plan.problems.append(f"check names must be unique in the plan: {', '.join(duplicates)}")
    if waiver_blocks and (smoke_blocks or any(plan.units.values())):
        plan.problems.append(
            "the plan carries a functional-test waiver and functional checks; keep one. A "
            "run-level waiver is only for a change that carries no code"
        )
    return plan


def read_plan(path: Path) -> PlanChecks:
    """Read and parse the plan at *path*, refusing a file that is not there."""
    if not path.is_file():
        raise FunctionalChecksError(f"no plan at {path}")
    return parse_plan(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Writing onto the run record.
# ---------------------------------------------------------------------------


def _row_matches(row: Any, unit_id: str) -> bool:
    """A row is the unit's when its ``id``, ``name`` or ``unit_id`` is the plan's U-ID.

    The same three keys ``run_record.unit_key`` and ``merge_turn.unit_name`` read, any of them.
    """
    return isinstance(row, dict) and any(
        str(row.get(key) or "") == unit_id for key in ("id", "name", "unit_id")
    )


def apply_checks(record: run_record.RunRecord, plan: PlanChecks) -> dict[str, list[str]]:
    """Write *plan*'s checks onto *record*'s unit rows in place, and say what happened.

    Each plan unit lands on the row it matches, or on a new ``{"id": "U<N>"}`` row when none does.
    Only the two keys this module owns change; every other key on every row is left alone, and a
    row the plan does not name is not touched. A record orchestrate drives (it carries a top-level
    ``orchestrate`` block) never gains a row: orchestrate owns which rows exist, and a row without
    its ``name``, ``vendor`` and ``task`` would not load there. A plan unit with no row there is
    listed as ``pending`` instead; ``orchestrate expand`` adds its ``/work`` row after ``/plan``
    finishes, named by the U-ID, and ``/work`` runs the write again before its first iteration.
    """
    driven = "orchestrate" in record.extra
    updated: list[str] = []
    added: list[str] = []
    pending: list[str] = []
    for uid, entries in plan.units.items():
        row = next((r for r in record.units if _row_matches(r, uid)), None)
        if row is None and driven:
            pending.append(uid)
            continue
        if row is None:
            row = {"id": uid}
            record.units.append(row)
            added.append(uid)
        else:
            updated.append(uid)
        row[ROW_CHECKS_KEY] = [dict(entry) for entry in entries]
        row[ROW_SMOKE_KEY] = [dict(entry) for entry in plan.smoke]
    untouched = [
        run_record.unit_key(r) or "?"
        for r in record.units
        if isinstance(r, dict) and not any(_row_matches(r, uid) for uid in plan.units)
    ]
    return {"updated": updated, "added": added, "pending": pending, "untouched": untouched}


def write_checks(path: Path, plan: PlanChecks) -> dict[str, list[str]]:
    """Write *plan* onto the record at *path* under the record's lock, and return the summary.

    The record is re-read after the lock is taken, so a key another writer added a moment ago (a
    unit session's usage entry, a build-loop iteration) survives. A record that is not there is
    refused: admission creates it, and this step never mints one.
    """
    if plan.problems:
        raise FunctionalChecksError(
            "the plan's functional-check blocks are malformed; nothing was written:\n  "
            + "\n  ".join(plan.problems)
        )
    if not plan.units:
        raise FunctionalChecksError(
            f"the plan names no `### U<N>.` unit under {UNITS_SECTION}; nothing was written"
        )
    with run_record.file_lock(path):
        record = build_loop.load_record_file(path)
        before = json.dumps(run_record.to_dict(record)["units"], sort_keys=True)
        summary = apply_checks(record, plan)
        if json.dumps(run_record.to_dict(record)["units"], sort_keys=True) != before:
            build_loop.save_record_file(path, record)
    return summary


# ---------------------------------------------------------------------------
# Mapping the checks to the issue's acceptance criteria.
# ---------------------------------------------------------------------------


def waiver_for(
    record: run_record.RunRecord | None, profile: dict[str, Any], plan: PlanChecks
) -> dict[str, Any] | None:
    """The waiver that skips the mapping, or ``None``.

    The repository-level waiver admission recorded comes first (``admission.
    functional_test_environment`` with ``mode: waived``); a record admitted before issue #97 falls
    back to the profile. Failing both, the plan's own run-level waiver, which plan review checks
    against the change: it applies only to a change that carries no code, so a plan that also
    declares a check or a smoke has none (``parse_plan`` names that as a problem).
    """
    recorded = record.admission.get(functional_environment.PROFILE_KEY) if record else None
    resolved: dict[str, Any] | None
    if isinstance(recorded, dict) and recorded.get("mode"):
        resolved = recorded
    else:
        try:
            resolved = functional_environment.resolve(profile)
        except functional_environment.DeclarationError as exc:
            raise FunctionalChecksError(
                f"{functional_environment.PROFILE_FILENAME}: {exc}"
            ) from exc
    if resolved is not None and resolved.get("mode") == functional_environment.MODE_WAIVED:
        return {
            "level": resolved.get("level", functional_environment.WAIVER_LEVEL),
            "reason": resolved.get("reason"),
            "source": resolved.get("source"),
        }
    if plan.waiver is not None and not plan.smoke and not any(plan.units.values()):
        return {"level": "run", "reason": plan.waiver["reason"], "source": "plan"}
    return None


def map_criteria(
    plan: PlanChecks,
    criteria: Sequence[dict[str, str]],
    *,
    waiver: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map every criterion to the checks that prove it, and name what is unmapped or unknown.

    A waiver skips the mapping only for a plan whose blocks are well formed. Malformed blocks are
    never hidden behind one: under a repository-level waiver the result is not ready and lists
    only the problems; any other waiver is ignored and the full mapping runs.
    """
    if waiver is not None and not plan.problems:
        return {
            "status": STATUS_WAIVED,
            "waiver": dict(waiver),
            "criteria": [dict(c) for c in criteria],
            "unmapped": [],
            "unknown_refs": [],
            "problems": [],
        }
    if waiver is not None and waiver.get("level") != "run":
        return {
            "status": STATUS_NOT_READY,
            "waiver": None,
            "waiver_withheld": dict(waiver),
            "criteria": [{**dict(c), "mapped_by": []} for c in criteria],
            "unmapped": [],
            "unknown_refs": [],
            "problems": list(plan.problems),
        }
    known = {criterion["id"] for criterion in criteria}
    proving: dict[str, list[dict[str, Any]]] = {cid: [] for cid in known}
    unknown: list[dict[str, Any]] = []
    sources: list[tuple[str | None, dict[str, Any]]] = [
        (uid, entry) for uid, entries in plan.units.items() for entry in entries
    ]
    sources += [(None, entry) for entry in plan.smoke]
    for unit, entry in sources:
        for ref in entry["proves"]:
            if ref in proving:
                proving[ref].append({"name": entry["name"], "unit": unit, "runs": entry["runs"]})
            else:
                unknown.append({"ref": ref, "check": entry["name"], "unit": unit})
    mapped = [{**dict(c), "mapped_by": proving[c["id"]]} for c in criteria]
    unmapped = [dict(c) for c in criteria if not proving[c["id"]]]
    ready = not unmapped and not unknown and not plan.problems
    return {
        "status": STATUS_READY if ready else STATUS_NOT_READY,
        "waiver": None,
        "criteria": mapped,
        "unmapped": unmapped,
        "unknown_refs": unknown,
        "problems": list(plan.problems),
    }


def format_mapping(result: dict[str, Any]) -> str:
    """The mapping as a reader sees it, one line per criterion."""
    if result["status"] == STATUS_WAIVED:
        waiver = result["waiver"]
        return (
            f"Functional testing is waived for this run ({waiver['level']} level: "
            f"{waiver['reason']}); the mapping check was skipped."
        )
    if result.get("waiver_withheld"):
        waiver = result["waiver_withheld"]
        return "\n".join(
            [
                (
                    f"Not ready: malformed check entries: {len(result['problems'])}. The "
                    f"{waiver['level']}-level waiver ({waiver['reason']}) does not skip a plan "
                    "whose blocks are malformed."
                ),
                *(f"  malformed: {problem}" for problem in result["problems"]),
            ]
        )
    lines: list[str] = []
    for criterion in result["criteria"]:
        if criterion["mapped_by"]:
            names = ", ".join(
                f"{p['unit']}: {p['name']}" if p["unit"] else f"smoke: {p['name']}"
                for p in criterion["mapped_by"]
            )
            lines.append(f"  {criterion['id']} proven by {names}")
        else:
            lines.append(f"  {criterion['id']} NOT MAPPED: {criterion['text']}")
    for ref in result["unknown_refs"]:
        lines.append(
            f"  {ref['ref']} is cited by {ref['check']!r} but the issue has no such criterion"
        )
    for problem in result["problems"]:
        lines.append(f"  malformed: {problem}")
    if result["status"] == STATUS_READY:
        head = "Every acceptance criterion maps to a functional check or the scenario smoke."
    else:
        reasons = []
        if result["unmapped"]:
            reasons.append(f"acceptance criteria with no check: {len(result['unmapped'])}")
        if result["unknown_refs"]:
            reasons.append(f"references to no criterion: {len(result['unknown_refs'])}")
        if result["problems"]:
            reasons.append(f"malformed check entries: {len(result['problems'])}")
        head = "Not ready: " + "; ".join(reasons) + "."
    return "\n".join([head, *lines])


# ---------------------------------------------------------------------------
# Command line.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="functional_checks.py",
        description=(
            "Read a plan's functional checks, write them onto the run record's unit rows, or map "
            "them to the issue's acceptance criteria."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Print the plan's functional checks as JSON.")
    extract.add_argument("--plan", required=True, help="The plan document.")

    write = sub.add_parser("write", help="Write the plan's checks onto the run record's units.")
    write.add_argument("--plan", required=True, help="The plan document.")
    write.add_argument("--record", default=None, help="The run record's path.")
    write.add_argument("--issue", type=int, default=None, help="Resolve the record by issue.")
    write.add_argument("--store-root", default=None, help="Override the resolved store directory.")

    mapping = sub.add_parser("map", help="Map the checks to the issue's acceptance criteria.")
    mapping.add_argument("--plan", required=True, help="The plan document.")
    mapping.add_argument("--issue", type=int, default=None, help="Read the issue body with gh.")
    mapping.add_argument("--repo", default=None, help="owner/repo for --issue.")
    mapping.add_argument("--body-file", default=None, help="Read the issue body from this file.")
    mapping.add_argument("--record", default=None, help="The run record's path, for its waiver.")
    mapping.add_argument(
        "--store-root", default=None, help="Override the resolved store directory."
    )
    mapping.add_argument(
        "--repo-root",
        default=None,
        help="Where .saga-profile.json lives, for a record admitted before it recorded a waiver.",
    )
    mapping.add_argument("--json", action="store_true", help="Print the mapping as JSON.")
    return parser


def _record_path(args: argparse.Namespace) -> Path | None:
    if args.record:
        return Path(args.record).resolve()
    if args.issue is None:
        return None
    root = Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
    return run_record.record_path(root, args.issue)


def _issue_body(args: argparse.Namespace, fetch: Callable[[int, str | None], str]) -> str:
    if args.body_file:
        path = Path(args.body_file)
        if not path.is_file():
            raise FunctionalChecksError(f"no issue body at {path}")
        return path.read_text(encoding="utf-8")
    if args.issue is None:
        raise FunctionalChecksError("name the issue with --issue <N> or --body-file <path>")
    try:
        return fetch(args.issue, args.repo)
    except (OSError, RuntimeError) as exc:
        raise FunctionalChecksError(f"the issue body could not be read: {exc}") from exc


def _run_map(args: argparse.Namespace, fetch: Callable[[int, str | None], str]) -> int:
    plan = read_plan(Path(args.plan))
    body = _issue_body(args, fetch)
    criteria = parse_issue.acceptance_criteria(body)
    if not criteria:
        raise FunctionalChecksError(
            f"the issue has no ### {parse_issue.ACCEPTANCE_HEADING} section with items, so there "
            "is nothing to map the plan's checks to"
        )
    path = _record_path(args)
    record = build_loop.load_record_file(path) if path is not None and path.is_file() else None
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
    try:
        profile = build_loop.load_profile(repo_root)
    except build_loop.BuildLoopError as exc:
        raise FunctionalChecksError(str(exc)) from exc
    result = map_criteria(plan, criteria, waiver=waiver_for(record, profile, plan))
    print(json.dumps(result, indent=2) if args.json else format_mapping(result))
    return EXIT_OK if result["status"] in (STATUS_READY, STATUS_WAIVED) else EXIT_NOT_READY


def main(
    argv: list[str] | None = None,
    *,
    fetch: Callable[[int, str | None], str] = parse_issue.fetch_issue_body,
) -> int:
    """Run the command line. Every loader call sits inside this one catch, as build_loop's does."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract":
            plan = read_plan(Path(args.plan))
            print(json.dumps(plan.as_dict(), indent=2))
            return EXIT_NOT_READY if plan.problems else EXIT_OK
        if args.command == "write":
            path = _record_path(args)
            if path is None:
                raise FunctionalChecksError("name the record with --record <path> or --issue <N>")
            summary = write_checks(path, read_plan(Path(args.plan)))
            print(json.dumps({"record": str(path), **summary}, indent=2))
            if summary["pending"]:
                print(
                    "functional_checks: pending, not refused: orchestrate drives this record and "
                    f"has no row yet for {', '.join(summary['pending'])}. `orchestrate expand` "
                    "adds them after /plan; /work runs this write again before its first "
                    "build-loop iteration. Name each /work unit by its plan U-ID.",
                    file=sys.stderr,
                )
                return EXIT_PENDING
            return EXIT_OK
        return _run_map(args, fetch)
    except run_record.UnknownRecordVersionError as exc:
        print(f"functional_checks: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except (FunctionalChecksError, build_loop.BuildLoopError, run_record.RunRecordError) as exc:
        print(f"functional_checks: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
