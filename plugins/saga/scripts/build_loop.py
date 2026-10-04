#!/usr/bin/env python3
"""The build loop's check runner — the written exit criterion, run and recorded (issue #1027).

Before this module, "working software" was a judgment ``/work`` made about its own work at the end
of it: Phase 3 asked a worker to discover tests, weigh scenario completeness, and then apply
``requires_hard_test_gate`` to a change-kind list it had written itself. Nothing was written down
beforehand for the worker to check itself against.

This module makes the finish line a fact. The criterion is assembled from what admission already
recorded and from what the plan put on the unit's row, it is run, and every result is written back
into the run record. A worker can read it before the first line of code and can tell afterwards
exactly which commit it went green at.

Five decisions here are contract for every later reader.

* **One invocation is one iteration** (plan KTD3). The only thing that changes between iterations
  is the code, and only the worker can change that. A script that looped internally would either
  spin on an unchanged tree or have to invoke an implementer, and a check runner that implements is
  a different program. "Repeat until green" is an instruction to the worker, in the skill.
* **A failing check is a loop iteration, never a refusal** (plan R2, the card's second non-goal).
  ``EXIT_NOT_GREEN`` is a code of its own, distinct from every refusal code, precisely so a caller
  cannot read it as "stop". The instruction on seeing it is "implement again and run it again".
* **Nothing is guessed** (plan KTD7). An unexecutable check yields ``could-not-execute`` — the lens
  catalogue's own rule, which says such a check is never a pass and never a fail. A repository that
  declares a branch preview but names no command for it gets that status and its reason, not an
  invented deployment command. The functional-test environment the repository declares (issue #97)
  is read from the record, or the profile, and reported; this module never picks one, and a unit
  iteration does not run it (the combined-branch run is pre-review testing U4).
* **Absence is recorded, not shown as nothing** (plan KTD9). ``/plan`` writes the plan's
  child-scoped functional checks and its scenario smoke onto each unit's row through
  ``functional_checks.py write`` (issue #98). An absent key reads as an empty list carrying the
  reason ``none-prescribed``, so a reader of a green iteration can tell "the plan prescribed none"
  from "the plan prescribed three and the loop lost them". A check marked ``runs: environment`` is
  recorded in the criterion but not run in a unit iteration; a list holding only such checks
  carries the reason ``deferred-to-combined-branch`` instead.
* **The record's version does not change** (plan KTD2). ``run-record.md`` states that a unit row's
  key set is deliberately not fixed, because a row is one consumer's working state rather than a
  cross-consumer contract; issue 1025 added three keys under that rule. This module adds one,
  ``build_loop``, documented in ``references/mechanical-baseline.md``.

House testability pattern, mirroring ``run_record.py`` and ``saga.py``: every filesystem function
takes its root as an explicit argument, ``runner``, ``now`` and ``clock`` are injectable, and
nothing does I/O at import.
"""

from __future__ import annotations

import argparse
import glob as globlib
import json
import os
import shlex
import subprocess  # nosec B404  (the checks ARE subprocesses; never through a shell)
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import functional_environment  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402  (after the sys.path shim, by design)

#: The key this module owns on a unit's row. One key, documented in
#: ``plugins/saga/references/mechanical-baseline.md``; ``run_record.v1`` does not change (KTD2).
UNIT_KEY = "build_loop"

#: Where the repository profile lives, relative to the repository root.
PROFILE_FILENAME = ".saga-profile.json"

#: The three statuses, from the lens catalogue's mechanical-check rules at
#: ``infiquetra/infiquetra-sdlc`` revision ``5efc869f``: "An unexecutable check yields
#: could-not-execute and an environment problem, never a pass and never a fail."
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_COULD_NOT_EXECUTE = "could-not-execute"

#: Recorded in place of a check list the plan never prescribed (KTD9).
REASON_NONE_PRESCRIBED = "none-prescribed"

#: Recorded when every check in a prescribed list runs against the declared environment. Those
#: run once, on the combined branch before code review (pre-review testing U4), never in a unit
#: iteration: a shared environment only ever receives the combined branch.
REASON_DEFERRED = "deferred-to-combined-branch"

#: A check entry's ``runs`` value for the declared environment, as ``functional_checks.py`` writes
#: it. An entry with no ``runs`` runs locally, which is every entry written before issue #98.
RUNS_ENVIRONMENT = "environment"

#: Recorded on the preview entry where the repository declares no branch preview. The lifecycle
#: repository's run model: "Where the repository declares no preview, the criterion does not apply
#: and no unit is held back by it."
STATUS_NO_PREVIEW = "no-preview-declared"

#: The lens catalogue's check-to-dimension map for the ``python`` stack, at sdlc revision
#: ``5efc869f``: the four check identifiers and the tool token that identifies each one inside a
#: baseline command. The catalogue's pinned versions all read ``UNKNOWN`` and are owned by the
#: organisation context library, so this map cites the checks and re-declares no version.
CATALOGUE_CHECKS: dict[str, dict[str, str]] = {
    "ruff": {
        "tool": "ruff",
        "purpose": "lint and format conformance for Python source",
    },
    "mypy": {
        "tool": "mypy",
        "purpose": "static type checking in strict mode",
    },
    "bandit": {
        "tool": "bandit",
        "purpose": "static security analysis of Python source",
    },
    "pytest-coverage": {
        "tool": "pytest",
        "purpose": "measured statement coverage of the changed code",
    },
}

#: Scanners the card names as baseline entries "where configured". They are not lens-catalogue
#: checks, so they are reported separately from an uncovered catalogue check: a tool a repository
#: has never configured is a different fact from a catalogue check its baseline does not answer.
NAMED_SCANNERS: tuple[str, ...] = ("pip-audit", "gitleaks", "detect-secrets", "semgrep")

#: Why an uncovered catalogue check is uncovered. Deliberately general: the reason a PARTICULAR
#: repository leaves a check out belongs in that repository's reading of
#: ``references/mechanical-baseline.md``, not hard-coded into a script every repository runs.
UNCOVERED_REASON = (
    "no baseline command in the repository profile names this tool; "
    "see plugins/saga/references/mechanical-baseline.md"
)

#: Exit codes. The first four are ``run_record.py``'s, unchanged, so a caller learns one table.
EXIT_GREEN = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3
#: Not a refusal: the iteration ran and something is not green yet (plan R2).
EXIT_NOT_GREEN = 4

#: How long one check may run before it is recorded ``could-not-execute``.
DEFAULT_TIMEOUT_SECONDS = 1800


class BuildLoopError(ValueError):
    """A refusal this module owns. The command line maps it to ``EXIT_REFUSED``."""


# ---------------------------------------------------------------------------
# The criterion, read rather than judged.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Preview:
    """The branch preview half of the criterion."""

    declared: bool
    command: str | None = None


@dataclass(frozen=True)
class Criterion:
    """What a unit must clear, assembled from the record and the profile. Nothing invented."""

    baseline: tuple[str, ...] = ()
    functional_checks: tuple[dict[str, Any], ...] = ()
    scenario_smoke: tuple[dict[str, Any], ...] = ()
    preview: Preview = field(default_factory=lambda: Preview(declared=False))
    #: The repository's functional-test environment or waiver, resolved (issue #97); ``None`` when
    #: nothing is declared. Read and recorded here, run by the combined-branch pass (U4).
    environment: dict[str, Any] | None = None

    def as_record(self) -> dict[str, Any]:
        """The criterion as it is written onto the unit row, verbatim."""
        return {
            "baseline": list(self.baseline),
            "functional_checks": [dict(entry) for entry in self.functional_checks],
            "scenario_smoke": [dict(entry) for entry in self.scenario_smoke],
            "preview": {"declared": self.preview.declared, "command": self.preview.command},
            "environment": dict(self.environment) if self.environment is not None else None,
        }


def load_profile(repo_root: Path, *, profile_path: Path | None = None) -> dict[str, Any]:
    """Read the repository profile. A missing profile is not an error.

    *profile_path* names the file directly; otherwise it is ``.saga-profile.json`` under
    *repo_root*. The two are separate because ``repo_root`` also says which repository's ``HEAD``
    the iteration records, and a caller that wants a different profile is not thereby asking for a
    different repository -- conflating them made the profile override silently move the revision
    lookup to a directory that is not a checkout.

    ``repository-profile.md``: "A missing profile is not an error. Every parameter it would have
    filled simply stays ``unset`` and joins the question set." The same rule holds here: a missing
    profile means no declared preview command, not a refusal.
    """
    path = profile_path if profile_path is not None else repo_root / PROFILE_FILENAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildLoopError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuildLoopError(f"{path} does not hold a JSON object")
    return raw


def _configured_value(block: Any) -> Any:
    """Unwrap a run-configuration parameter's ``{value, chosen_by, source}`` envelope."""
    if isinstance(block, dict) and "value" in block:
        return block["value"]
    return block


def find_unit(record: run_record.RunRecord, unit_id: str | None) -> dict[str, Any] | None:
    """The unit row to run against, or ``None`` when the caller named none and none is implied.

    Naming no unit is legal for a dry run, which reports the repository-wide half of the criterion.
    For a real iteration the caller must land on exactly one row, and ambiguity refuses rather than
    picking: writing an iteration onto the wrong unit is worse than stopping. A unit's identity is
    ``run_record.unit_key``, the rule ``usage add`` and the cost report also read (``merge_turn``
    reads the same keys name-first; see run-record.md).
    """
    if unit_id is not None:
        try:
            return run_record.find_unit_row(record.units, unit_id)
        except run_record.RunRecordError as exc:
            raise BuildLoopError(str(exc)) from None
    if len(record.units) == 1:
        return record.units[0]
    return None


def read_criterion(
    record: run_record.RunRecord,
    unit: dict[str, Any] | None,
    profile: dict[str, Any],
) -> Criterion:
    """Assemble the criterion from *record*, *unit* and *profile*. Never invents an entry."""
    baseline_raw = _configured_value(record.run_configuration.get("mechanical_tool_baseline"))
    baseline = tuple(str(entry) for entry in (baseline_raw or []) if str(entry).strip())

    unit = unit or {}
    functional = tuple(_normalise_checks(unit.get("functional_checks")))
    smoke = tuple(_normalise_checks(unit.get("scenario_smoke")))

    declared = bool(record.admission.get("branch_preview"))
    command = profile.get("branch_preview_command")
    preview = Preview(declared=declared, command=str(command) if command else None)

    return Criterion(
        baseline=baseline,
        functional_checks=functional,
        scenario_smoke=smoke,
        preview=preview,
        environment=read_environment(record, profile),
    )


def read_environment(
    record: run_record.RunRecord, profile: dict[str, Any]
) -> dict[str, Any] | None:
    """The functional-test environment admission recorded, else what the profile declares.

    The record wins: it is what the run was admitted with. A record admitted before issue #97 has
    no ``admission.functional_test_environment``, so the profile is resolved instead, with the
    record's legacy ``branch_preview`` answer standing in where the profile no longer carries it.
    Never guessed: nothing declared reads as ``None``.
    """
    recorded = record.admission.get(functional_environment.PROFILE_KEY)
    if isinstance(recorded, dict) and recorded.get("mode"):
        return dict(recorded)
    view = dict(profile)
    if "branch_preview" not in view and record.admission.get("branch_preview") is not None:
        view["branch_preview"] = record.admission.get("branch_preview")
    try:
        return functional_environment.resolve(view)
    except functional_environment.DeclarationError as exc:
        raise BuildLoopError(f"{PROFILE_FILENAME}: {exc}") from exc


def _normalise_checks(raw: Any) -> list[dict[str, Any]]:
    """Accept a list of ``{name, command}`` objects or bare command strings; absent reads empty.

    An object's ``proves`` (the acceptance criteria it proves) and ``runs`` (``local`` or
    ``environment``) are kept when present, so the recorded criterion still says what each check
    is for and where it runs. Every other key is dropped.
    """
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(raw, start=1):
        if isinstance(entry, dict):
            command = str(entry.get("command", ""))
            check: dict[str, Any] = {
                "name": str(entry.get("name") or command or f"check-{index}"),
                "command": command,
            }
            if isinstance(entry.get("proves"), list):
                check["proves"] = [str(ref) for ref in entry["proves"]]
            if entry.get("runs") is not None:
                check["runs"] = str(entry["runs"])
            out.append(check)
        else:
            out.append({"name": str(entry), "command": str(entry)})
    return out


def runs_in_unit(entry: dict[str, Any]) -> bool:
    """Whether a unit iteration runs *entry*: every check but one bound for the environment."""
    return entry.get("runs") != RUNS_ENVIRONMENT


def _absence_reason(entries: Sequence[dict[str, Any]]) -> str | None:
    """Why a check list produced no result in a unit iteration, or ``None`` when one ran."""
    if not entries:
        return REASON_NONE_PRESCRIBED
    if not any(runs_in_unit(entry) for entry in entries):
        return REASON_DEFERRED
    return None


# ---------------------------------------------------------------------------
# The check map.
# ---------------------------------------------------------------------------


def _tokens(command: str) -> list[str]:
    """The command's argument tokens, by basename, for tool matching."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return []
    return [os.path.basename(part) for part in parts]


def catalogue_check_for(command: str) -> str | None:
    """Which lens-catalogue check *command* answers, or ``None`` for a repository-specific entry."""
    tokens = set(_tokens(command))
    for check_id, spec in CATALOGUE_CHECKS.items():
        if spec["tool"] in tokens:
            return check_id
    return None


def check_map(baseline: Sequence[str]) -> dict[str, Any]:
    """Map *baseline* onto the catalogue's checks and name what is not covered.

    A catalogue check no command answers is reported as uncovered with a reason. A command no
    catalogue check claims is reported as repository-specific, which is information rather than an
    error: a repository may run more than the catalogue names.
    """
    covered: dict[str, list[str]] = {}
    commands: list[dict[str, Any]] = []
    for command in baseline:
        check_id = catalogue_check_for(command)
        commands.append({"command": command, "catalogue_check": check_id})
        if check_id is not None:
            covered.setdefault(check_id, []).append(command)
    uncovered = [
        {"catalogue_check": check_id, "purpose": spec["purpose"], "reason": UNCOVERED_REASON}
        for check_id, spec in CATALOGUE_CHECKS.items()
        if check_id not in covered
    ]
    named_tokens = {token for command in baseline for token in _tokens(command)}
    unconfigured = [scanner for scanner in NAMED_SCANNERS if scanner not in named_tokens]
    return {
        "commands": commands,
        "uncovered": uncovered,
        "unconfigured_scanners": unconfigured,
    }


# ---------------------------------------------------------------------------
# Running a check.
# ---------------------------------------------------------------------------

#: A runner takes an argument vector, a timeout and a working directory, and returns
#: ``(exit_code, detail)``. It raises ``FileNotFoundError`` when the program is absent and
#: ``subprocess.TimeoutExpired`` on a timeout, which is what the real one does and therefore what a
#: fake must do.
Runner = Callable[[Sequence[str], int, "Path | None"], "tuple[int, str]"]


def subprocess_runner(
    argv: Sequence[str], timeout: int, cwd: Path | None = None
) -> tuple[int, str]:
    """Run *argv* with no shell. The profile's entries are data, and data never reaches a shell."""
    proc = subprocess.run(  # nosec B603  (shell=False, argv from a tracked config, never a string)
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        cwd=str(cwd) if cwd is not None else None,
    )
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return proc.returncode, (detail[-1] if detail else "")


def expand_globs(argv: Sequence[str], cwd: Path | None) -> list[str]:
    """Expand each glob token against *cwd*, the way a shell would, without being one.

    A profile entry is a command line a person wrote, and a command line legitimately carries a
    glob -- this repository's own baseline carries ``plugins/*/tests/``. Passing that through
    verbatim hands the program a literal path that does not exist, and the loop then records a
    ``fail`` indistinguishable from a real test failure. A token that matches nothing is passed
    through unchanged, which is also what a shell does: the program's own error about the path it
    was given is clearer than the loop silently dropping the argument.
    """
    if cwd is None:
        return list(argv)
    out: list[str] = []
    for token in argv:
        if not any(char in token for char in "*?["):
            out.append(token)
            continue
        matches = sorted(globlib.glob(token, root_dir=str(cwd)))
        out.extend(matches or [token])
    return out


def run_check(
    name: str,
    command: str,
    *,
    runner: Runner,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    catalogue_check: str | None = None,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run one check and return its record entry. Never raises for a check's own failure."""
    entry: dict[str, Any] = {
        "name": name,
        "command": command,
        "catalogue_check": catalogue_check,
        "status": STATUS_COULD_NOT_EXECUTE,
        "exit_code": None,
        "duration_seconds": 0.0,
        "detail": "",
    }
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        entry["detail"] = f"the command does not parse into an argument vector: {exc}"
        return entry
    if not argv:
        entry["detail"] = "the command is empty"
        return entry

    argv = expand_globs(argv, cwd)
    started = clock()
    try:
        code, detail = runner(argv, timeout, cwd)
    except FileNotFoundError as exc:
        entry["duration_seconds"] = round(clock() - started, 3)
        entry["detail"] = f"the program is not installed: {exc}"
        return entry
    except subprocess.TimeoutExpired:
        entry["duration_seconds"] = round(clock() - started, 3)
        entry["detail"] = f"the check did not finish within {timeout} seconds"
        return entry
    entry["duration_seconds"] = round(clock() - started, 3)
    entry["exit_code"] = code
    entry["status"] = STATUS_PASS if code == 0 else STATUS_FAIL
    entry["detail"] = detail
    return entry


def run_preview(
    preview: Preview,
    *,
    runner: Runner,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run the branch preview deployment, or record why it did not run. Never an error (plan R4)."""
    if not preview.declared:
        return {
            "declared": False,
            "status": STATUS_NO_PREVIEW,
            "command": None,
            "detail": "the repository profile declares no branch preview",
        }
    if not preview.command:
        return {
            "declared": True,
            "status": STATUS_COULD_NOT_EXECUTE,
            "command": None,
            "detail": "the profile declares a preview but names no command",
        }
    result = run_check(
        "branch-preview", preview.command, runner=runner, timeout=timeout, cwd=cwd, clock=clock
    )
    return {
        "declared": True,
        "status": result["status"],
        "command": preview.command,
        "exit_code": result["exit_code"],
        "duration_seconds": result["duration_seconds"],
        "detail": result["detail"],
    }


# ---------------------------------------------------------------------------
# One iteration.
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def head_revision(repo_root: Path, *, runner: Runner) -> str:
    """The full forty-character commit identifier of ``HEAD``.

    ``/code-review`` freezes exactly this value and refuses an abbreviation or a symbolic
    reference, so the loop records the same shape it will be read as.
    """
    try:
        code, detail = runner(["git", "-C", str(repo_root), "rev-parse", "HEAD"], 60, None)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BuildLoopError(f"the revision could not be read: {exc}") from exc
    if code != 0:
        raise BuildLoopError(f"the revision could not be read: git rev-parse exited {code}")
    revision = detail.strip()
    if len(revision) != 40:
        raise BuildLoopError(
            f"git rev-parse returned {revision!r}, which is not a forty-character revision"
        )
    return revision


def run_iteration(
    criterion: Criterion,
    revision: str,
    *,
    runner: Runner,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = _utc_now,
) -> tuple[dict[str, Any], bool]:
    """Run the whole criterion once and return ``(iteration, green)``, writing nothing.

    The iteration carries no number: ``apply_iteration``, the only code that writes the
    ``build_loop`` block, numbers it against the row it lands on.
    """
    mapping = check_map(criterion.baseline)
    by_command = {entry["command"]: entry["catalogue_check"] for entry in mapping["commands"]}

    started_at = now()
    baseline_results = [
        run_check(
            command,
            command,
            runner=runner,
            timeout=timeout,
            catalogue_check=by_command.get(command),
            cwd=cwd,
            clock=clock,
        )
        for command in criterion.baseline
    ]
    functional_results = [
        run_check(
            entry["name"], entry["command"], runner=runner, timeout=timeout, cwd=cwd, clock=clock
        )
        for entry in criterion.functional_checks
        if runs_in_unit(entry)
    ]
    preview_result = run_preview(
        criterion.preview, runner=runner, timeout=timeout, cwd=cwd, clock=clock
    )
    smoke_results = [
        run_check(
            entry["name"], entry["command"], runner=runner, timeout=timeout, cwd=cwd, clock=clock
        )
        for entry in criterion.scenario_smoke
        if runs_in_unit(entry)
    ]

    green = all(
        result["status"] == STATUS_PASS
        for result in (*baseline_results, *functional_results, *smoke_results)
    ) and preview_result["status"] in (STATUS_PASS, STATUS_NO_PREVIEW)

    iteration: dict[str, Any] = {
        "revision": revision,
        "started_at": started_at,
        "finished_at": now(),
        "green": green,
        "baseline": baseline_results,
        "functional_checks": functional_results,
        "preview": preview_result,
        "scenario_smoke": smoke_results,
    }
    functional_reason = _absence_reason(criterion.functional_checks)
    if functional_reason is not None:
        iteration["functional_checks_reason"] = functional_reason
    smoke_reason = _absence_reason(criterion.scenario_smoke)
    if smoke_reason is not None:
        iteration["scenario_smoke_reason"] = smoke_reason
    return iteration, green


def apply_iteration(
    unit: dict[str, Any], criterion: Criterion, iteration: dict[str, Any], green: bool
) -> dict[str, Any]:
    """Write one finished *iteration* onto *unit*, a row read after the record's lock was taken.

    This is the only code that writes the ``build_loop`` block. ``main`` runs the checks outside
    the lock, because they can take minutes; then it takes the lock, re-reads the record and lands
    the result here (issue 95). The block is added to, never replaced: the iteration is numbered
    against the fresh row, and every other key on it survives, including a ``usage`` entry a unit
    session added while the checks ran — the rule ``run-record.md`` states for every unit row.
    """
    block = unit.setdefault(UNIT_KEY, {})
    if not isinstance(block, dict):
        raise BuildLoopError(f"the unit's {UNIT_KEY!r} key is not an object")
    block["exit_criterion"] = criterion.as_record()
    iterations = block.setdefault("iterations", [])
    if not isinstance(iterations, list):
        raise BuildLoopError(f"the unit's {UNIT_KEY}.iterations key is not a list")
    landed = {**iteration, "iteration": len(iterations) + 1}
    iterations.append(landed)
    if green:
        block["handed_to_code_review"] = {
            "revision": landed["revision"],
            "at": landed["finished_at"],
        }
    return landed


# ---------------------------------------------------------------------------
# Reading and writing a record by path.
# ---------------------------------------------------------------------------


def load_record_file(path: Path) -> run_record.RunRecord:
    """Read a record from an explicit *path*, with ``run_record.py``'s own refusals."""
    if not path.is_file():
        raise BuildLoopError(f"no record at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildLoopError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuildLoopError(f"{path} does not hold a JSON object")
    return run_record.from_dict(raw, path=path)


def save_record_file(path: Path, record: run_record.RunRecord) -> Path:
    """Write *record* to *path* with the same atomic replace ``run_record.save`` uses."""
    payload = run_record.to_dict(
        run_record.RunRecord(
            **{
                **record.__dict__,
                "created_at": record.created_at or _utc_now(),
                "updated_at": _utc_now(),
            }
        )
    )
    return run_record.write_json_atomic(path, payload)


# ---------------------------------------------------------------------------
# The dry run.
# ---------------------------------------------------------------------------


def format_check(entry: dict[str, Any]) -> str:
    """One prescribed check as the dry run prints it: name, command, and what it proves and where.

    An entry written before issue #98 carries neither ``proves`` nor ``runs`` and prints as it
    always did, ``<name>: <command>``.
    """
    line = f"{entry['name']}: {entry['command']}"
    notes: list[str] = []
    if entry.get("proves"):
        notes.append("proves " + ", ".join(entry["proves"]))
    if entry.get("runs") == RUNS_ENVIRONMENT:
        notes.append("runs against the declared environment, on the combined branch")
    elif entry.get("runs"):
        notes.append("runs locally")
    return f"{line}  ({'; '.join(notes)})" if notes else line


def _check_lines(entries: Sequence[dict[str, Any]], indent: str = "  ") -> list[str]:
    if not entries:
        return [f"{indent}none prescribed in the run record"]
    return [f"{indent}{format_check(entry)}" for entry in entries]


def format_dry_run(
    criterion: Criterion,
    mapping: dict[str, Any],
    units: Sequence[tuple[str, Criterion]] | None = None,
) -> str:
    """The criterion as a reader sees it, run nothing and write nothing.

    *units*, when given, is every unit row's ``(id, criterion)``: the dry run of a record with more
    than one row and no ``--unit`` lists each unit's functional checks under its id, and the
    scenario smoke once when every unit carries the same list, otherwise per unit.
    """
    lines = ["The build loop's exit criterion for this repository.", ""]

    lines.append("Mechanical baseline, from the repository profile:")
    if mapping["commands"]:
        for entry in mapping["commands"]:
            answers = entry["catalogue_check"] or "no catalogue check (repository-specific entry)"
            lines.append(f"  {entry['command']}")
            lines.append(f"      answers: {answers}")
    else:
        lines.append("  none declared in the run record")

    lines.append("")
    lines.append("Catalogue checks this baseline does not cover:")
    if mapping["uncovered"]:
        for entry in mapping["uncovered"]:
            lines.append(f"  {entry['catalogue_check']} — {entry['purpose']}")
            lines.append(f"      {entry['reason']}")
    else:
        lines.append("  none — every catalogue check for this stack is covered")

    lines.append("")
    lines.append("Named scanners not configured in this repository's baseline:")
    if mapping["unconfigured_scanners"]:
        for scanner in mapping["unconfigured_scanners"]:
            lines.append(f"  {scanner}")
    else:
        lines.append("  none")

    lines.append("")
    lines.append("Child-scoped functional checks, from the plan:")
    if units:
        for unit_id, unit_criterion in units:
            lines.append(f"  Unit {unit_id}:")
            lines.extend(_check_lines(unit_criterion.functional_checks, "    "))
    else:
        lines.extend(_check_lines(criterion.functional_checks))

    lines.append("")
    lines.append("Scenario smoke, from the plan:")
    smokes = [list(unit_criterion.scenario_smoke) for _, unit_criterion in units or ()]
    if units and any(smoke != smokes[0] for smoke in smokes):
        for unit_id, unit_criterion in units:
            lines.append(f"  Unit {unit_id}:")
            lines.extend(_check_lines(unit_criterion.scenario_smoke, "    "))
    else:
        lines.extend(_check_lines(smokes[0] if units else criterion.scenario_smoke))

    lines.append("")
    environment = criterion.environment
    if environment is not None and environment.get("mode") == functional_environment.MODE_WAIVED:
        lines.append(
            f"Functional-test waiver, from {environment.get('source')}: {environment.get('reason')}"
        )
    else:
        source = f", from {environment.get('source')}" if environment is not None else ""
        lines.append(f"Functional-test environment{source}:")
        lines.extend(f"  {line}" for line in functional_environment.describe(environment))
        if environment is not None:
            lines.append(
                "  run on the combined branch before code review, never in a unit iteration"
            )

    lines.append("")
    if not criterion.preview.declared:
        lines.append("branch preview: none declared")
    elif criterion.preview.command:
        lines.append(f"branch preview: declared, command: {criterion.preview.command}")
    else:
        lines.append("branch preview: declared, but the profile names no command")

    return "\n".join(lines)


def format_iteration(iteration: dict[str, Any]) -> str:
    """One iteration's results, for a worker reading the terminal."""
    lines = [
        f"Iteration {iteration['iteration']} at {iteration['revision']}: "
        + ("green" if iteration["green"] else "not green yet"),
        "",
    ]
    for entry in iteration["baseline"]:
        lines.append(f"  [{entry['status']}] {entry['command']}")
        if entry["detail"]:
            lines.append(f"      {entry['detail']}")
    for entry in iteration["functional_checks"]:
        lines.append(f"  [{entry['status']}] functional: {entry['name']}")
    if not iteration["functional_checks"]:
        reason = iteration.get("functional_checks_reason", REASON_NONE_PRESCRIBED)
        lines.append(f"  [{reason}] functional checks")
    preview = iteration["preview"]
    lines.append(f"  [{preview['status']}] branch preview")
    for entry in iteration["scenario_smoke"]:
        lines.append(f"  [{entry['status']}] scenario smoke: {entry['name']}")
    if not iteration["scenario_smoke"]:
        reason = iteration.get("scenario_smoke_reason", REASON_NONE_PRESCRIBED)
        lines.append(f"  [{reason}] scenario smoke")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_loop.py",
        description=(
            "Run the build loop's written exit criterion once and record the result. "
            "A failing check is a loop iteration, never a refusal."
        ),
    )
    parser.add_argument("--record", default=None, help="The run record's path.")
    parser.add_argument("--issue", type=int, default=None, help="Resolve the record by issue.")
    parser.add_argument("--store-root", default=None, help="Override the resolved store directory.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help=f"The repository: where {PROFILE_FILENAME} lives and whose HEAD is recorded.",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help=f"Read the profile from this file instead of {PROFILE_FILENAME} under --repo-root.",
    )
    parser.add_argument("--unit", default=None, help="Which unit row to run against.")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Seconds per check."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the checks that would run and whether a preview is declared; write nothing.",
    )
    return parser


def _resolve_repo_root(args: argparse.Namespace) -> Path:
    if args.repo_root:
        return Path(args.repo_root).resolve()
    return Path.cwd()


def _resolve_record_path(args: argparse.Namespace) -> Path:
    if args.record:
        return Path(args.record).resolve()
    if args.issue is None:
        raise BuildLoopError("name the record with --record <path> or --issue <N>")
    root = Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
    return run_record.record_path(root, args.issue)


def main(argv: list[str] | None = None, *, runner: Runner = subprocess_runner) -> int:
    """Run the command line. Every loader call sits inside this one catch, as ``run_record.py`` does."""
    args = build_parser().parse_args(argv)
    try:
        path = _resolve_record_path(args)
        record = load_record_file(path)
        repo_root = _resolve_repo_root(args)
        profile = load_profile(
            repo_root, profile_path=Path(args.profile).resolve() if args.profile else None
        )
        unit = find_unit(record, args.unit)
        criterion = read_criterion(record, unit, profile)

        if args.dry_run:
            per_unit = None
            if unit is None and len(record.units) > 1:
                per_unit = [
                    (
                        run_record.unit_key(row) or f"row {index}",
                        read_criterion(record, row, profile),
                    )
                    for index, row in enumerate(record.units, start=1)
                    if isinstance(row, dict)
                ]
            print(format_dry_run(criterion, check_map(criterion.baseline), per_unit))
            return EXIT_GREEN

        if unit is None:
            raise BuildLoopError(
                "name the unit with --unit <id>: the record has "
                f"{len(record.units)} unit rows, so which one this iteration belongs to is not implied"
            )
        revision = head_revision(repo_root, runner=runner)
        # The checks run with no lock held: they can take minutes. The result lands on a row
        # re-read under the record's lock, so nothing another writer added meanwhile (a unit
        # session's usage entry, a review result) is lost (issue 95).
        iteration, green = run_iteration(
            criterion,
            revision,
            runner=runner,
            timeout=args.timeout,
            cwd=repo_root,
        )
        with run_record.file_lock(path):
            fresh = load_record_file(path)
            fresh_unit = find_unit(fresh, args.unit)
            if fresh_unit is None:
                raise BuildLoopError(
                    f"the record at {path} changed while the checks ran and no longer implies "
                    "one unit; name it with --unit <id>"
                )
            iteration = apply_iteration(fresh_unit, criterion, iteration, green)
            save_record_file(path, fresh)
        print(format_iteration(iteration))
        if green:
            print("")
            print(f"Handing to code review at {revision}.")
            return EXIT_GREEN
        print("")
        print("Not green yet. Implement again and run this again — this is a loop iteration.")
        return EXIT_NOT_GREEN
    except run_record.UnknownRecordVersionError as exc:
        print(f"build_loop: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except (BuildLoopError, run_record.RunRecordError) as exc:
        print(f"build_loop: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
