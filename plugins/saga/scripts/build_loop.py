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

The combined-branch mode (issue #99, pre-review testing U4) adds three more decisions.

* **After integration and before code review, the combined branch is built, deployed or started,
  tested and torn down** through the commands the repository declared (``--combined``). Teardown
  runs on every exit path once the deploy step was reached, including a failed deploy, a failed
  test and an interrupt. A failing test is a loop pass (exit 4); a deploy that does not succeed, a
  timeout or a missing tool is ``could-not-execute``, never a pass and never a code defect.
* **Three consecutive could-not-execute passes are an environment stop, exit 5.** It names the
  environment problems for the operator. It is an exit code, not a refusal to run: the next
  invocation still runs, so a fixed environment resets the streak.
* **A shared environment is held by one run at a time** through the lease in
  ``environment_lease.py``, a reference on the git remote every deploying host pushes to. A second
  run waits a bounded time, saying what it waits on, then records a could-not-execute pass naming
  the holder. A lease belongs to the one invocation that took it (issues #139 and #140): a later
  invocation of the same run waits on it like any other holder, and a crashed invocation's lease is
  released by the operator. The pass number is read from the record when the lease is won, not
  before the wait. The run record itself still takes only its file lock; the combined passes live under
  the run-level top-level key ``combined_branch``, which ``run_record.py`` preserves as an unknown
  field.

The review gate (issue #100, pre-review testing U5) adds one more.

* **Code review starts only from ``--handoff``.** It reads, and writes nothing: exit 0 prints the
  revision to review only when the latest combined pass at it is green, waived or not; anything
  else is a refusal, exit 2, naming what is missing. A green unit loop alone admits nothing, and
  no override reaches this gate: the repository's recorded waiver is the only exception, and the
  closeout prints its reason.

House testability pattern, mirroring ``run_record.py`` and ``saga.py``: every filesystem function
takes its root as an explicit argument, ``runner``, ``now`` and ``clock`` are injectable, and
nothing does I/O at import.
"""

from __future__ import annotations

import argparse
import dataclasses
import glob as globlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess  # nosec B404  (the checks ARE subprocesses; never through a shell)
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import environment_lease  # noqa: E402  (after the sys.path shim, by design)
import functional_environment  # noqa: E402  (after the sys.path shim, by design)
import merge_turn  # noqa: E402  (after the sys.path shim, by design)
import review_tools  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402  (after the sys.path shim, by design)

#: The key this module owns on a unit's row. One key, documented in
#: ``plugins/saga/references/mechanical-baseline.md``; ``run_record.v1`` does not change (KTD2).
UNIT_KEY = "build_loop"

#: A full forty-character commit identifier, the only revision shape code review accepts.
FULL_REVISION = re.compile(r"^[0-9a-f]{40}$")

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

#: Why a review tool is uncovered. The list itself is ``review-tools.yaml``, not a copy of it.
UNCOVERED_REASON = (
    "no baseline command in the repository profile names this tool; "
    "see plugins/saga/references/review-tools.yaml"
)

#: Exit codes. The first four are ``run_record.py``'s, unchanged, so a caller learns one table.
EXIT_GREEN = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3
#: Not a refusal: the iteration ran and something is not green yet (plan R2).
EXIT_NOT_GREEN = 4
#: Not a refusal either: the third consecutive combined pass that could not execute. The
#: environment, not the code, needs the operator (issue #99).
EXIT_ENVIRONMENT_STOP = 5

#: The run-level top-level key the combined-branch mode owns. Not one of ``run_record``'s twelve
#: top-level keys: it round-trips as an unknown field, the extension point orchestrate's top-level
#: ``orchestrate`` block also uses, documented in ``references/run-record.md``.
COMBINED_KEY = "combined_branch"

#: Top-level keys another saga writer owns, which loading a record should not warn about.
KNOWN_EXTENSION_KEYS: tuple[str, ...] = (COMBINED_KEY, "orchestrate", "tier_judgments")

#: How many consecutive could-not-execute combined passes stop the loop for the operator.
COULD_NOT_EXECUTE_STOP = 3

#: How long a combined pass waits on a held shared lease, and how often it looks again.
DEFAULT_LEASE_WAIT_SECONDS = 1800
LEASE_POLL_SECONDS = 30

#: A combined pass's step statuses beyond the three check statuses.
STEP_NOT_DECLARED = "not-declared"
LEASE_NOT_REQUIRED = "not-required"

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


def _baseline_rows() -> list[dict[str, Any]]:
    """Review-tool rows a baseline command can answer.

    ``catalogue: false`` marks a row the setup survey checks and the build loop does not.
    Saga's own tools use binaries the baseline already names (``git``, ``python3``, ``uv``).
    Matching those strings would claim repository commands and list the rows as uncovered.
    """
    return [
        row
        for row in review_tools.load_tool_list()
        if row.get("tool") and row.get("catalogue") is not False
    ]


def catalogue_check_for(command: str) -> str | None:
    """Which review-tool row *command* answers, or ``None`` for a repository-specific entry.

    Several rows can share one binary. Their ids are sorted and joined, so ``semgrep scan``
    answers ``semgrep-saga,semgrep-security``. A row with an empty ``tool``, and a row with
    ``catalogue: false``, is not a baseline check.
    """
    tokens = set(_tokens(command))
    matched = sorted(
        str(row["id"]) for row in _baseline_rows() if str(row["tool"]) in tokens
    )
    if not matched:
        return None
    return ",".join(matched)


def check_map(baseline: Sequence[str]) -> dict[str, Any]:
    """Map *baseline* onto ``review-tools.yaml`` and name the tools no command answers.

    A command no row claims is repository-specific. It still runs: green is the profile's
    ``mechanical_tool_baseline``, not this map. Rows with an empty ``tool``, and rows with
    ``catalogue: false``, are not baseline checks and do not appear as uncovered.
    """
    rows = _baseline_rows()
    covered: set[str] = set()
    commands: list[dict[str, Any]] = []
    for command in baseline:
        check_id = catalogue_check_for(command)
        commands.append({"command": command, "catalogue_check": check_id})
        if check_id is not None:
            covered.update(check_id.split(","))
    uncovered = [
        {
            "catalogue_check": str(row["id"]),
            "purpose": str(row.get("purpose") or ""),
            "reason": UNCOVERED_REASON,
        }
        for row in rows
        if str(row["id"]) not in covered
    ]
    return {"commands": commands, "uncovered": uncovered}


# ---------------------------------------------------------------------------
# Running a check.
# ---------------------------------------------------------------------------

#: A runner takes an argument vector, a timeout and a working directory, and returns
#: ``(exit_code, detail)``. It raises ``FileNotFoundError`` when the program is absent and
#: ``subprocess.TimeoutExpired`` on a timeout, which is what the real one does and therefore what a
#: fake must do.
Runner = Callable[[Sequence[str], int, "Path | None"], "tuple[int, str]"]

#: ``(repo, base, head) ->`` the scan fields, without ``declarations`` or ``gate``.
Scan = Callable[[Path, str | None, str], Mapping[str, Any]]

#: ``(builder record or None, revision, repo) -> (status, lines)``.
Declare = Callable[[Mapping[str, Any] | None, str, Path], tuple[str, list[str]]]

#: ``(lens, language) ->`` one may-block line. True only when the line starts with ``yes``.
MayBlock = Callable[[str, str], str]


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
# The review a unit iteration and a combined pass record (issue #162).
# ---------------------------------------------------------------------------


def _plugin_dir() -> Path:
    """The saga plugin that contains this script. Policy and calibration are read from here."""
    return Path(__file__).resolve().parents[1]


def _one_line(exc: BaseException) -> str:
    text = str(exc).splitlines()
    return text[0] if text else type(exc).__name__


def _could_not_scan(head: str, *, base: str | None = None, detail: str = "") -> dict[str, Any]:
    scanned: dict[str, Any] = {
        "status": STATUS_COULD_NOT_EXECUTE,
        "base": base,
        "head": head,
        "findings": [],
        "degraded": [],
        "where_to_look": [],
    }
    if detail:
        scanned["detail"] = detail
    return scanned


def _copy_scan(scanned: Mapping[str, Any], head: str) -> dict[str, Any]:
    """The scan fields the review object keeps, including why a scan did not run."""
    status = scanned.get("status", STATUS_PASS)
    if status not in (STATUS_PASS, STATUS_FAIL, STATUS_COULD_NOT_EXECUTE):
        status = STATUS_COULD_NOT_EXECUTE
    raw = scanned.get("detail", "")
    text = raw.strip() if isinstance(raw, str) else ""
    detail = text.splitlines()[0] if text else ""
    return {
        "base": scanned.get("base"),
        "head": scanned.get("head") or head,
        "status": status,
        "findings": list(scanned.get("findings") or []),
        "degraded": list(scanned.get("degraded") or []),
        "where_to_look": list(scanned.get("where_to_look") or []),
        "detail": detail,
    }


def _resolve_base(repo: Path, head: str, runner: Runner) -> str | None:
    """Merge-base of *head* with its upstream, else ``origin/HEAD``. Never *head* itself."""
    for ref in ("@{upstream}", "origin/HEAD"):
        try:
            code, detail = runner(["git", "-C", str(repo), "merge-base", head, ref], 60, None)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        sha = detail.strip()
        if code == 0 and FULL_REVISION.fullmatch(sha) and sha != head:
            return sha
    return None


def _json_list(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise BuildLoopError(f"{path.name} is not a list")
    return data


def _degraded_input(lens: str, language: str, name: str, tool: str, reason: str) -> dict[str, str]:
    import review_formula  # noqa: PLC0415

    return {
        "lens": lens if lens in review_formula.LENSES else "correctness",
        "language": language if language in review_formula.LANGUAGES else "none",
        "input": name or "sweep",
        "tool": tool,
        "reason": reason,
    }


def _jev_rate() -> dict[str, float] | None:
    """The ``jev-latest`` prices, or ``None`` when the file cannot answer."""
    import yaml  # noqa: PLC0415

    path = _plugin_dir() / "references" / "model-prices.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    models = data.get("models") if isinstance(data, Mapping) else None
    if not isinstance(models, Mapping):
        return None
    for row in models.values():
        if not isinstance(row, Mapping) or "jev-latest" not in (row.get("aliases") or []):
            continue
        rates = row.get("usd_per_million")
        if not isinstance(rates, Mapping):
            return None
        parsed: dict[str, float] = {}
        for key in ("uncached_input", "cache_read", "cache_write_5m", "cache_write_1h", "output"):
            value = rates.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            parsed[key] = float(value)
        return parsed
    return None


def _map_sweep(
    entry: Mapping[str, Any], questions: Sequence[Any], pieces: Sequence[Any]
) -> dict[str, str]:
    import review_formula  # noqa: PLC0415

    question_id = entry.get("question")
    lens = "correctness"
    if isinstance(question_id, str):
        for question in questions:
            if isinstance(question, Mapping) and question.get("id") == question_id:
                named = question.get("lens")
                if named in review_formula.LENSES:
                    lens = str(named)
                break
    language = "none"
    piece_id = entry.get("piece")
    if isinstance(piece_id, str):
        for piece in pieces:
            if isinstance(piece, Mapping) and piece.get("id") == piece_id:
                named = piece.get("language")
                if named in review_formula.LANGUAGES:
                    language = str(named)
                break
    reason = entry.get("reason")
    name = question_id if isinstance(question_id, str) and question_id else "sweep"
    return _degraded_input(lens, language, name, "jev", str(reason) if reason else "sweep")


def _sweep_banks(
    repo: Path,
    base: str,
    head: str,
    *,
    ask: Any,
    sweep_home: Path | None,
) -> tuple[list[Any], list[dict[str, str]]]:
    """One sweep over the four approved banks. A refusal degrades the input and does not fail."""
    import question_banks  # noqa: PLC0415

    try:
        questions: list[Any] = []
        for lens in question_banks.LENSES:
            bank = question_banks.load_bank(lens, _plugin_dir())
            questions.extend(bank["questions"])
        bank_payload: dict[str, Any] = {
            "schema": question_banks.BANK_SCHEMA,
            "questions": questions,
        }
    except question_banks.BankRefusal as exc:
        return [], [_degraded_input("correctness", "none", "question-bank", "jev", _one_line(exc))]
    rate = _jev_rate()
    if rate is None:
        return [], [_degraded_input("correctness", "none", "model-prices", "jev", "no-rate")]
    try:
        import review_calibration  # noqa: PLC0415
        import sweep_pieces  # noqa: PLC0415

        calibration = review_calibration.default_calibration_path()
        cut = sweep_pieces.pieces(repo, base, head, bank_payload, calibration=calibration)
    except Exception as exc:  # noqa: BLE001  (a failed sweep degrades; it does not fail the pass)
        return [], [_degraded_input("correctness", "none", "sweep", "jev", _one_line(exc))]
    pieces = cut.get("pieces") if isinstance(cut, Mapping) else []
    if not isinstance(pieces, list):
        pieces = []
    home = sweep_home or Path.home()
    cache = home / ".saga" / "review-sweep" / head
    try:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "log").mkdir(parents=True, exist_ok=True)
        import bundled_fleet  # noqa: PLC0415

        result = bundled_fleet.load("jev_sweep").sweep(
            bank_payload,
            pieces,
            cut.get("thresholds") or {},
            rate,
            repo=str(repo),
            head=head,
            cache_dir=cache,
            log_dir=cache / "log",
            ask=ask,
        )
    except Exception as exc:  # noqa: BLE001  (a failed sweep degrades; it does not fail the pass)
        return [], [_degraded_input("correctness", "none", "sweep", "jev", _one_line(exc))]
    raw_items = result.get("items") if isinstance(result, Mapping) else []
    items: list[Any] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if isinstance(item, Mapping):
                copied = dict(item)
                copied.pop("_piece", None)
                items.append(copied)
    raw_degraded: list[Any] = []
    if isinstance(cut, Mapping):
        raw_degraded.extend(cut.get("degraded") or [])
    if isinstance(result, Mapping):
        raw_degraded.extend(result.get("degraded") or [])
    mapped = [
        _map_sweep(entry, questions, pieces)
        for entry in raw_degraded
        if isinstance(entry, Mapping)
    ]
    return items, mapped


def _run_production_scan(
    repo: Path, base: str, head: str, *, ask: Any, sweep_home: Path | None
) -> dict[str, Any]:
    output = Path(tempfile.mkdtemp(prefix="saga-build-loop-review-"))
    try:
        code = review_tools.run(
            repo, base, head, repo / PROFILE_FILENAME, output, framework=True
        )
        if code != 0:
            return _could_not_scan(head, base=base, detail=f"review tools exited {code}")
        findings = _json_list(output / "findings.json")
        degraded = _json_list(output / "degraded.json")
        where = _json_list(output / "where-to-look.json")
        items, extra = _sweep_banks(repo, base, head, ask=ask, sweep_home=sweep_home)
        degraded.extend(extra)
        where.extend(items)
        return {
            "status": STATUS_PASS,
            "base": base,
            "head": head,
            "findings": findings,
            "degraded": degraded,
            "where_to_look": where,
        }
    finally:
        shutil.rmtree(output, ignore_errors=True)


def _production_scan(
    repo: Path, head: str, *, runner: Runner, ask: Any, sweep_home: Path | None
) -> dict[str, Any]:
    """Resolve the base, run the tools, then the sweep. A failure is recorded, not raised."""
    try:
        base = _resolve_base(repo, head, runner)
        if base is None:
            return _could_not_scan(head, detail="no-base")
        return _run_production_scan(repo, base, head, ask=ask, sweep_home=sweep_home)
    except Exception as exc:  # noqa: BLE001  (a scan that raises is recorded, not an interrupt)
        return _could_not_scan(head, detail=_one_line(exc))


def _perform_scan(
    repo: Path,
    revision: str,
    *,
    runner: Runner,
    scan: Scan | None,
    ask: Any,
    sweep_home: Path | None,
) -> dict[str, Any]:
    """An injected scan replaces the production scan, base resolution included."""
    if scan is not None:
        return _copy_scan(scan(repo, None, revision), revision)
    if runner is subprocess_runner:
        produced = _production_scan(repo, revision, runner=runner, ask=ask, sweep_home=sweep_home)
        return _copy_scan(produced, revision)
    return _copy_scan(
        {
            "status": STATUS_PASS,
            "base": None,
            "head": revision,
            "findings": [],
            "degraded": [],
            "where_to_look": [],
        },
        revision,
    )


def _perform_declare(
    builder: Mapping[str, Any] | None,
    revision: str,
    repo: Path,
    *,
    runner: Runner,
    declare: Declare | None,
) -> dict[str, Any]:
    if declare is not None:
        status, lines = declare(builder, revision, repo)
        return {"status": status, "questions": list(lines)}
    if runner is subprocess_runner:
        import builder_record as builder_records  # noqa: PLC0415

        code, lines = builder_records.evaluate(builder, revision, repo)
        if code == 0:
            status = STATUS_PASS
        elif code == 1:
            status = STATUS_FAIL
        else:
            status = STATUS_COULD_NOT_EXECUTE
        return {"status": status, "questions": lines}
    return {"status": STATUS_PASS, "questions": []}


def _row_builder_records(record: run_record.RunRecord) -> list[Mapping[str, Any]]:
    found: list[Mapping[str, Any]] = []
    for row in record.units:
        if not isinstance(row, dict):
            continue
        value = row.get("builder_record")
        if isinstance(value, Mapping):
            found.append(value)
    return found


def _finding_label(finding: Mapping[str, Any]) -> str:
    ident = finding.get("id")
    return str(ident) if ident else "finding"


def _judge_findings(
    findings: Sequence[Any],
    builder_records: Sequence[Mapping[str, Any]],
    block_map: Mapping[str, Any] | None,
) -> tuple[str, list[str]]:
    """Gate lines. A preset key or a formula error fails closed. A secret fails the gate."""
    import review_formula  # noqa: PLC0415
    import review_records  # noqa: PLC0415

    fail_lines: list[str] = []
    closed_lines: list[str] = []
    for finding in findings:
        if not isinstance(finding, Mapping):
            closed_lines.append("finding: not an object")
            continue
        preset = next(
            (key for key in review_formula.COMPUTED_FINDING_KEYS if key in finding), None
        )
        if preset is not None:
            closed_lines.append(f"{_finding_label(finding)}: preset {preset}")
            continue
        try:
            computed = review_formula.outcome(finding, builder_records, may_block=block_map)
        except review_formula.FormulaError as exc:
            closed_lines.append(f"{_finding_label(finding)}: {exc}")
            continue
        if computed.get("severity") == "blocks" and computed.get("enforced") is True:
            fail_lines.append(f"{_finding_label(finding)}: enforced block")
        rule = finding.get("rule") if isinstance(finding.get("rule"), Mapping) else {}
        source = finding.get("source") if isinstance(finding.get("source"), Mapping) else {}
        secret = rule.get("row") == review_records.SECRET_ROW or source.get("name") == "gitleaks"
        if secret:
            fail_lines.append(f"{_finding_label(finding)}: secret in diff")
    if fail_lines:
        return STATUS_FAIL, [*fail_lines, *closed_lines]
    if closed_lines:
        return STATUS_COULD_NOT_EXECUTE, closed_lines
    return STATUS_PASS, []


def _languages_on(findings: Sequence[Any]) -> list[str]:
    found = {"none"}
    for finding in findings:
        if isinstance(finding, Mapping) and isinstance(finding.get("language"), str):
            found.add(str(finding["language"]))
    return sorted(found)


def _map_from_lines(findings: Sequence[Any], may_block: MayBlock) -> dict[str, dict[str, bool]]:
    import review_formula  # noqa: PLC0415

    mapping: dict[str, dict[str, bool]] = {}
    for lens in review_formula.LENSES:
        mapping[lens] = {}
        for language in _languages_on(findings):
            line = may_block(lens, language)
            mapping[lens][language] = isinstance(line, str) and line.startswith("yes")
    return mapping


def _base_profile(repo: Path, base: str) -> Path | None:
    """A temporary copy of ``.saga-profile.json`` at *base*. ``None`` when the blob is not JSON."""
    shown = subprocess.run(  # nosec B603  (shell=False; git show of one tracked file)
        ["git", "-C", str(repo), "show", f"{base}:.saga-profile.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = shown.stdout if shown.returncode == 0 else "{}\n"
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return None
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115  (unlinked by the caller)
        prefix="saga-base-profile-", suffix=".json", delete=False
    )
    handle.write(text.encode())
    handle.close()
    return Path(handle.name)


def _production_block_map(
    findings: Sequence[Any], repo: Path, base: str | None
) -> dict[str, dict[str, bool]]:
    import review_calibration  # noqa: PLC0415
    import review_formula  # noqa: PLC0415

    if base is None or FULL_REVISION.fullmatch(str(base)) is None:
        raise review_calibration.CalibrationError("no base commit to read the profile from")
    profile = _base_profile(repo, base)
    try:
        if profile is None:
            raise review_calibration.CalibrationError("base profile is not JSON")
        root = _plugin_dir()
        calibration = review_calibration.default_calibration_path()
        mapping: dict[str, dict[str, bool]] = {}
        for lens in review_formula.LENSES:
            mapping[lens] = {}
            for language in _languages_on(findings):
                line = review_calibration.may_block(
                    lens, language, root=root, calibration=calibration, profile=profile
                )
                mapping[lens][language] = line.startswith("yes")
        return mapping
    finally:
        if profile is not None:
            profile.unlink(missing_ok=True)


def _answers_for(
    findings: Sequence[Any],
    *,
    runner: Runner,
    may_block: MayBlock | None,
    block_map: Mapping[str, Any] | None,
    repo: Path,
    base: str | None,
) -> Mapping[str, Any]:
    if block_map is not None:
        return block_map
    if may_block is not None:
        return _map_from_lines(findings, may_block)
    if runner is not subprocess_runner:
        return {}
    return _production_block_map(findings, repo, base)


def _empty_review(head: str, *, declarations: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "base": None,
        "head": head,
        "status": STATUS_COULD_NOT_EXECUTE,
        "findings": [],
        "degraded": [],
        "where_to_look": [],
        "detail": "",
        "declarations": declarations,
        "gate": [],
    }


def _combined_review(
    record: run_record.RunRecord,
    revision: str,
    *,
    runner: Runner,
    scan: Scan | None,
    may_block: MayBlock | None,
    block_map: Mapping[str, Any] | None,
    ask: Any,
    sweep_home: Path | None,
    cwd: Path | None,
) -> dict[str, Any]:
    """The combined pass's review. ``declarations`` is null; ``gate`` holds the failing lines."""
    import review_calibration  # noqa: PLC0415

    repo = cwd or Path(".")
    scanned = _perform_scan(
        repo, revision, runner=runner, scan=scan, ask=ask, sweep_home=sweep_home
    )
    review = {**scanned, "declarations": None, "gate": []}
    if review["status"] == STATUS_COULD_NOT_EXECUTE:
        return review
    try:
        answers = _answers_for(
            review["findings"],
            runner=runner,
            may_block=may_block,
            block_map=block_map,
            repo=repo,
            base=review["base"] if isinstance(review["base"], str) else None,
        )
    except review_calibration.CalibrationError as exc:
        review["status"] = STATUS_COULD_NOT_EXECUTE
        review["gate"] = [_one_line(exc)]
        return review
    status, gate = _judge_findings(review["findings"], _row_builder_records(record), answers)
    review["status"] = status
    review["gate"] = gate
    return review


def _gate_skip_reason(review: Mapping[str, Any]) -> str:
    lines = review.get("gate") or []
    if lines:
        detail = "; ".join(str(line) for line in lines)
    else:
        status = str(review.get("status") or "")
        cause = review.get("detail")
        detail = f"{status}: {cause}" if isinstance(cause, str) and cause else status
    return f"the review gate is not pass, so nothing was deployed: {detail}"


def _review_work_lines() -> list[str]:
    """Tools, checks, sweep and declarations. Imported here so loading the loop starts nothing."""
    import question_banks  # noqa: PLC0415

    lines = ["", "Tools:"]
    for adapter in review_tools.default_adapters():
        if adapter.mode == "fix" or not adapter.tool:
            continue
        lines.append(f"  {adapter.id}")
    lines.extend(
        [
            "Checks:",
            "  those adapters include the pattern checks and the scripted checks",
            "Sweep:",
        ]
    )
    lines.extend(f"  {question_banks.bank_file(lens)}" for lens in question_banks.LENSES)
    lines.extend(["Declarations:", "  builder_record.py check", f"  {question_banks.POLICY_FILE}"])
    return lines


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
    repo: Path | None = None,
    builder_record: Mapping[str, Any] | None = None,
    scan: Scan | None = None,
    declare: Declare | None = None,
    ask: Any = None,
    sweep_home: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    """Run the whole criterion once and return ``(iteration, green)``, writing nothing.

    The iteration carries no number: ``apply_iteration``, the only code that writes the
    ``build_loop`` block, numbers it against the row it lands on. ``review`` is always present.
    A missing declaration, or a scan that did not run, keeps the iteration off green. Findings
    do not.
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

    checks_green = all(
        result["status"] == STATUS_PASS
        for result in (*baseline_results, *functional_results, *smoke_results)
    ) and preview_result["status"] in (STATUS_PASS, STATUS_NO_PREVIEW)
    repo_path = repo if repo is not None else (cwd or Path("."))
    scanned = _perform_scan(
        repo_path, revision, runner=runner, scan=scan, ask=ask, sweep_home=sweep_home
    )
    declarations = _perform_declare(
        builder_record, revision, repo_path, runner=runner, declare=declare
    )
    review = {**scanned, "declarations": declarations, "gate": []}
    green = (
        checks_green
        and declarations["status"] == STATUS_PASS
        and review["status"] != STATUS_COULD_NOT_EXECUTE
    )

    iteration: dict[str, Any] = {
        "revision": revision,
        "started_at": started_at,
        "finished_at": now(),
        "green": green,
        "baseline": baseline_results,
        "functional_checks": functional_results,
        "preview": preview_result,
        "scenario_smoke": smoke_results,
        "review": review,
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
    return run_record.from_dict(raw, path=path, warn=_warn_unknown_field)


def _warn_unknown_field(message: str) -> None:
    """``run_record``'s unknown-field warning, minus the run-level keys saga's own writers own."""
    if any(f"field {key!r}" in message for key in KNOWN_EXTENSION_KEYS):
        return
    print(message, file=sys.stderr)


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
    lines.append("Review tools this baseline does not name:")
    if mapping["uncovered"]:
        for entry in mapping["uncovered"]:
            lines.append(f"  {entry['catalogue_check']} — {entry['purpose']}")
            lines.append(f"      {entry['reason']}")
    else:
        lines.append("  none — every review tool with a binary is named")

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

    lines.extend(_review_work_lines())
    return "\n".join(lines)


def _review_status_lines(review: Mapping[str, Any]) -> list[str]:
    """The review status, and the scan's one-line reason when it has one."""
    lines = [f"  [{review.get('status')}] review"]
    detail = review.get("detail")
    if isinstance(detail, str) and detail:
        lines.append(f"      {detail}")
    return lines


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
    review = iteration.get("review")
    if isinstance(review, dict):
        declarations = review.get("declarations")
        if isinstance(declarations, dict):
            for line in declarations.get("questions") or []:
                lines.append(f"  {line}")
            lines.append(f"  [{declarations.get('status')}] declarations")
        lines.extend(_review_status_lines(review))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The combined-branch pass (issue #99, pre-review testing U4).
# ---------------------------------------------------------------------------


class CombinedPassInterrupted(BaseException):
    """An interrupt arrived mid-pass. Teardown and the lease release already ran; *entry* is the
    pass as far as it got, marked ``interrupted``, for the caller to record before re-raising."""

    def __init__(self, entry: dict[str, Any]) -> None:
        super().__init__("the combined-branch pass was interrupted")
        self.entry = entry


class _Terminated(BaseException):
    """SIGTERM, raised as an exception so every ``finally`` (teardown, release) still runs."""


def require_answered(environment: dict[str, Any] | None) -> dict[str, Any]:
    """The declared environment or waiver, or a refusal naming what is missing."""
    if environment is None:
        raise BuildLoopError(
            "the repository declares no functional-test environment and no waiver; admission asks "
            "for it once and writes it to .saga-profile.json (references/repository-profile.md)"
        )
    if environment.get("mode") not in functional_environment.ANSWERED_MODES:
        missing = ", ".join(environment.get("missing") or []) or "fields"
        raise BuildLoopError(
            f"the functional-test environment is incomplete (missing {missing}); answer the "
            "admission question before the combined-branch pass can run"
        )
    return environment


#: ``prod`` or ``production`` as its own word. Whether ``non``/``pre`` precedes it is checked in
#: code, because ``non-prod`` and ``pre_prod`` name non-production stacks.
_PRODUCTION_WORD = re.compile(r"prod(?:uction)?(?![a-z0-9])", re.IGNORECASE)


def production_tripwire(environment: dict[str, Any]) -> str | None:
    """Why the declaration looks like production, or ``None``. A tripwire, not a guarantee.

    No production deployment happens on any path of this loop (the card's non-goal and stop
    condition). The declaration is the authority on where a command deploys; this check only
    refuses a declaration that says production in its kind, its lease or a command.
    """
    lease = functional_environment.lease_of(environment) or {}
    fields = {
        "kind": environment.get("kind"),
        "deploy_command": environment.get("deploy_command"),
        "test_command": environment.get("test_command"),
        "teardown_command": environment.get("teardown_command"),
        "lease.name": lease.get("name"),
        "lease.remote": lease.get("remote"),
    }
    for label, value in fields.items():
        text = str(value or "")
        for match in _PRODUCTION_WORD.finditer(text):
            before = text[: match.start()].lower()
            if before and (before[-1].isalnum() or before.endswith(_NON_PRODUCTION_PREFIXES)):
                continue
            return (
                f"the functional-test environment's {label} ({text!r}) names production; the "
                "combined-branch pass never deploys to production. Fix the declaration or stop"
            )
    return None


_NON_PRODUCTION_PREFIXES = ("non-", "non_", "pre-", "pre_")


def environment_checks(record: run_record.RunRecord) -> list[dict[str, Any]]:
    """Every check the plan bound for the declared environment, from every unit row, once each.

    ``/plan`` marks such checks ``runs: environment`` (issue #98), and the scenario smoke is always
    one of them. A unit iteration defers them; the combined pass runs them after the declared test
    command. The same check copied onto several rows (the smoke is) runs once.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in record.units:
        if not isinstance(row, dict):
            continue
        for key in ("functional_checks", "scenario_smoke"):
            for entry in _normalise_checks(row.get(key)):
                if runs_in_unit(entry):
                    continue
                identity = (entry["name"], entry["command"])
                if identity not in seen:
                    seen.add(identity)
                    out.append(entry)
    return out


def integration_problem(
    record: run_record.RunRecord, revision: str, repo_root: Path, *, runner: Runner
) -> str | None:
    """Why the revision under test is not yet the combined branch, or ``None`` when it is.

    A run with one lane has nothing to integrate. Otherwise every lane must be merged, and every
    recorded merge must be contained in the revision under test: a pass on a checkout that misses
    a merge would hand review a branch that is not the combined one.
    """
    state = merge_turn.integration_state(record)
    if state["single_lane"]:
        return None
    if not state["complete"]:
        return (
            "the units are not brought together yet; still to merge: "
            + ", ".join(state["pending"])
            + ". Take the merge turn for each (merge_turn.py merge --unit <name>) first"
        )
    for name, tip in state["merged_tips"].items():
        try:
            code, _ = runner(
                ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", tip, revision], 60, None
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return f"whether {revision[:12]} contains unit {name}'s merge could not be read: {exc}"
        if code != 0:
            return (
                f"the revision under test ({revision[:12]}) does not contain unit {name}'s merge "
                f"({tip[:12]}); run the pass on the combined branch, after the last merge"
            )
    return None


def current_branch(repo_root: Path, *, runner: Runner) -> str | None:
    """The checked-out branch's name, for the record. ``None`` when it cannot be read."""
    try:
        code, detail = runner(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"], 60, None
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if code != 0:
        return None
    return detail.strip() or None


def _not_declared(name: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "command": None,
        "catalogue_check": None,
        "status": STEP_NOT_DECLARED,
        "exit_code": None,
        "duration_seconds": 0.0,
        "detail": detail,
    }


def _run_step(
    name: str,
    command: str,
    *,
    runner: Runner,
    timeout: int,
    cwd: Path | None,
    clock: Callable[[], float],
    environment_step: bool,
) -> dict[str, Any]:
    """Run one step. An environment step (deploy, teardown) that exits non-zero could not execute.

    A test that exits non-zero is a ``fail``: the code under test said no. A deploy or a teardown
    that exits non-zero is the environment saying no, so it is recorded ``could-not-execute`` with
    its exit code kept, and is never reported as a defect in the code.
    """
    try:
        entry = run_check(name, command, runner=runner, timeout=timeout, cwd=cwd, clock=clock)
    except OSError as exc:
        entry = {
            "name": name,
            "command": command,
            "catalogue_check": None,
            "status": STATUS_COULD_NOT_EXECUTE,
            "exit_code": None,
            "duration_seconds": 0.0,
            "detail": f"the program could not be started: {exc}",
        }
    if environment_step and entry["status"] == STATUS_FAIL:
        entry["status"] = STATUS_COULD_NOT_EXECUTE
        entry["detail"] = f"the {name} exited {entry['exit_code']}: {entry['detail']}".rstrip(": ")
    return entry


def acquire_lease(
    backend: environment_lease.LeaseBackend,
    name: str,
    holder: environment_lease.LeaseHolder,
    *,
    lease_wait: int,
    remote: str,
    repo_root: Path,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    wall_now: Callable[[], datetime],
    report: Callable[[str], None],
    next_pass: Callable[[], int] | None = None,
) -> tuple[environment_lease.AcquireResult, float]:
    """Take the lease, waiting up to *lease_wait* seconds on a holder and saying what it waits on.

    Every holder is waited on, this run's own earlier invocations included: nothing here replaces
    a lease (issues #139 and #140). *next_pass*, when given, is asked at each attempt, so a lease
    won after a wait names the pass number the record would hand out now, not the one it would
    have handed out when the wait began.
    """
    started = clock()
    while True:
        # The start time is stamped at each attempt, so a lease won after a wait does not carry
        # the wait as time held and is never described as stale the moment it is taken.
        attempt = dataclasses.replace(holder, started_at=environment_lease.iso_utc(wall_now()))
        if next_pass is not None:
            attempt = dataclasses.replace(attempt, pass_number=next_pass())
        try:
            result = backend.acquire(name, attempt)
        except environment_lease.LeaseError as exc:
            return (
                environment_lease.AcquireResult(environment_lease.COULD_NOT_EXECUTE, detail=str(exc)),
                round(clock() - started, 3),
            )
        waited = clock() - started
        if result.acquired or result.status != environment_lease.HELD:
            return result, round(waited, 3)
        state = environment_lease.LeaseState(
            name=name, held=True, token=result.token, holder=result.holder
        )
        report(
            "Waiting on the shared environment: "
            + environment_lease.describe(
                state, wall_now(), remote=remote, repo_root=str(repo_root)
            )
        )
        if waited >= lease_wait:
            return result, round(waited, 3)
        sleep(max(0.0, min(LEASE_POLL_SECONDS, lease_wait - waited)))


def _lease_block(lease: dict[str, str] | None) -> dict[str, Any]:
    if lease is None:
        return {"required": False, "status": LEASE_NOT_REQUIRED}
    return {
        "required": True,
        "status": None,
        "remote": lease["remote"],
        "ref": environment_lease.REF_PREFIX + lease["name"],
        "invocation": None,
        "token": None,
        "holder": None,
        "waited_seconds": 0.0,
        "release_status": None,
        "detail": "",
    }


def _holder_record(holder: Any) -> Any:
    if isinstance(holder, environment_lease.LeaseHolder):
        return {
            "repo": holder.repo,
            "issue": holder.issue,
            "revision": holder.revision,
            "host": holder.host,
            "started_at": holder.started_at,
            "bound_seconds": holder.bound_seconds,
            "pass_number": holder.pass_number,
            "invocation": holder.invocation,
        }
    return holder


def _pass_status(entry: dict[str, Any]) -> str:
    """A pass's status: ``fail`` when the code said no, else ``could-not-execute`` when the
    environment did, else ``pass``. A failing test outranks an environment problem, because the
    fix is in the code either way and the code is the worker's to change."""
    results = [*entry["baseline"], *entry.get("environment_checks", [])]
    for step in ("deploy", "test", "teardown"):
        if isinstance(entry.get(step), dict):
            results.append(entry[step])
    statuses = {result["status"] for result in results}
    review = entry.get("review")
    review_status = review.get("status") if isinstance(review, Mapping) else None
    if STATUS_FAIL in statuses or review_status == STATUS_FAIL:
        return STATUS_FAIL
    lease_status = entry["lease"].get("status")
    lease_ok = lease_status in (LEASE_NOT_REQUIRED, environment_lease.ACQUIRED)
    release_ok = entry["lease"].get("release_status") in (None, environment_lease.RELEASED)
    if (
        STATUS_COULD_NOT_EXECUTE in statuses
        or review_status == STATUS_COULD_NOT_EXECUTE
        or entry.get("environment_problems")
        or not lease_ok
        or not release_ok
        or entry.get("interrupted")
    ):
        return STATUS_COULD_NOT_EXECUTE
    return STATUS_PASS


def run_combined_pass(
    record: run_record.RunRecord,
    environment: dict[str, Any],
    baseline: Sequence[str],
    revision: str,
    *,
    runner: Runner,
    lease_backend: environment_lease.LeaseBackend | None = None,
    pass_number: int = 1,
    branch: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    lease_wait: int = DEFAULT_LEASE_WAIT_SECONDS,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], str] = _utc_now,
    wall_now: Callable[[], datetime] = environment_lease.utc_now,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
    host: str | None = None,
    invocation: str | None = None,
    next_pass: Callable[[], int] | None = None,
    scan: Scan | None = None,
    declare: Declare | None = None,
    may_block: MayBlock | None = None,
    block_map: Mapping[str, Any] | None = None,
    ask: Any = None,
    sweep_home: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    """Run one combined-branch pass and return ``(entry, green)``, writing nothing.

    Order: the mechanical baseline on the combined revision; the lease, on a shared environment;
    the deploy-or-start command; the declared test command and every environment-bound plan check;
    the teardown. Teardown runs on every exit path once the deploy step was reached, and the lease
    is released after it. A waived repository runs the baseline only and records the waiver.

    *invocation* names this invocation in the lease it takes (a fresh nonce when omitted).
    *next_pass* reads the pass number from the record when the lease is won; without it the pass
    keeps *pass_number*. The review gate runs after the baseline and before deploy, including on
    a waived repository. ``declare`` is accepted so a caller can pass the unit seams; this pass
    does not run the declaration check.
    """
    del declare
    waived = environment.get("mode") == functional_environment.MODE_WAIVED
    lease = None if waived else functional_environment.lease_of(environment)
    if lease is not None and lease_backend is None:
        raise BuildLoopError("a shared environment needs a lease backend; none was given")
    checks = [] if waived else environment_checks(record)
    entry: dict[str, Any] = {
        "pass": pass_number,
        "revision": revision,
        "branch": branch,
        "started_at": now(),
        "finished_at": None,
        "status": None,
        "green": False,
        "baseline": [],
        "lease": _lease_block(lease),
        "deploy": None,
        "test": None,
        "environment_checks": [],
        "teardown": None,
        "environment_problems": [],
    }
    problems: list[str] = entry["environment_problems"]
    mapping = check_map(baseline)
    by_command = {item["command"]: item["catalogue_check"] for item in mapping["commands"]}

    def step(name: str, command: str, *, environment_step: bool = False) -> dict[str, Any]:
        result = _run_step(
            name,
            command,
            runner=runner,
            timeout=timeout,
            cwd=cwd,
            clock=clock,
            environment_step=environment_step,
        )
        if result["status"] == STATUS_COULD_NOT_EXECUTE:
            problems.append(f"{name}: {result['detail']}")
        return result

    try:
        for command in baseline:
            result = run_check(
                command,
                command,
                runner=runner,
                timeout=timeout,
                catalogue_check=by_command.get(command),
                cwd=cwd,
                clock=clock,
            )
            entry["baseline"].append(result)
            if result["status"] == STATUS_COULD_NOT_EXECUTE:
                problems.append(f"baseline {command}: {result['detail']}")

        entry["review"] = _combined_review(
            record,
            revision,
            runner=runner,
            scan=scan,
            may_block=may_block,
            block_map=block_map,
            ask=ask,
            sweep_home=sweep_home,
            cwd=cwd,
        )
        if waived:
            entry["waiver"] = {
                "level": environment.get("level", functional_environment.WAIVER_LEVEL),
                "reason": environment.get("reason"),
            }
        if any(result["status"] != STATUS_PASS for result in entry["baseline"]):
            entry["skipped_reason"] = (
                "the mechanical baseline is not green on the combined branch, so nothing was "
                "deployed"
            )
        elif entry["review"].get("status") != STATUS_PASS:
            entry["skipped_reason"] = _gate_skip_reason(entry["review"])
        elif not waived:
            _deploy_test_teardown(
                entry,
                environment,
                lease,
                checks,
                step=step,
                lease_backend=lease_backend,
                record=record,
                revision=revision,
                pass_number=pass_number,
                timeout=timeout,
                lease_wait=lease_wait,
                cwd=cwd,
                clock=clock,
                wall_now=wall_now,
                sleep=sleep,
                report=report,
                host=host,
                invocation=invocation or environment_lease.new_invocation(),
                next_pass=next_pass,
            )
    except BaseException as exc:
        entry["interrupted"] = True
        problems.append(f"the pass was interrupted: {type(exc).__name__}")
        if not isinstance(entry.get("review"), dict):
            entry["review"] = _empty_review(revision, declarations=None)
        entry["finished_at"] = now()
        entry["status"] = _pass_status(entry)
        raise CombinedPassInterrupted(entry) from exc

    entry["finished_at"] = now()
    entry["status"] = _pass_status(entry)
    entry["green"] = entry["status"] == STATUS_PASS
    return entry, entry["green"]


def _deploy_test_teardown(
    entry: dict[str, Any],
    environment: dict[str, Any],
    lease: dict[str, str] | None,
    checks: Sequence[dict[str, Any]],
    *,
    step: Callable[..., dict[str, Any]],
    lease_backend: environment_lease.LeaseBackend | None,
    record: run_record.RunRecord,
    revision: str,
    pass_number: int,
    timeout: int,
    lease_wait: int,
    cwd: Path | None,
    clock: Callable[[], float],
    wall_now: Callable[[], datetime],
    sleep: Callable[[float], None],
    report: Callable[[str], None],
    host: str | None,
    invocation: str,
    next_pass: Callable[[], int] | None,
) -> None:
    """The lease, then deploy, test and teardown, with teardown and release on every exit path."""
    problems: list[str] = entry["environment_problems"]
    lease_block = entry["lease"]
    token: str | None = None
    if lease is not None and lease_backend is not None:
        holder = environment_lease.LeaseHolder(
            repo=record.repo,
            issue=record.issue,
            revision=revision,
            host=host or environment_lease.host_label(),
            started_at=environment_lease.iso_utc(wall_now()),
            bound_seconds=timeout * (3 + len(checks)),
            pass_number=pass_number,
            invocation=invocation,
        )
        result, waited = acquire_lease(
            lease_backend,
            lease["name"],
            holder,
            lease_wait=lease_wait,
            remote=lease["remote"],
            repo_root=cwd or Path("."),
            clock=clock,
            sleep=sleep,
            wall_now=wall_now,
            report=report,
            next_pass=next_pass,
        )
        lease_block.update(
            {
                "status": result.status,
                "invocation": invocation,
                "token": result.token if result.acquired else None,
                "holder": _holder_record(result.holder),
                "waited_seconds": waited,
                "detail": result.detail,
            }
        )
        if not result.acquired:
            if result.status == environment_lease.HELD:
                described = environment_lease.describe(
                    environment_lease.LeaseState(
                        name=lease["name"], held=True, token=result.token, holder=result.holder
                    ),
                    wall_now(),
                    remote=lease["remote"],
                    repo_root=str(cwd or "."),
                )
                lease_block["detail"] = described
                problems.append(f"lease: still held after {waited:.0f}s: {described}")
            else:
                problems.append(f"lease: could not be taken: {result.detail}")
            entry["skipped_reason"] = (
                "the shared environment's lease was not acquired, so nothing was deployed"
            )
            return
        token = result.token
        if isinstance(result.holder, environment_lease.LeaseHolder):
            # The number read when the lease was won, not the one read before any wait.
            entry["pass"] = result.holder.pass_number

    try:
        deploy_command = environment.get("deploy_command")
        if deploy_command:
            entry["deploy"] = step("deploy", deploy_command, environment_step=True)
        else:
            entry["deploy"] = _not_declared("deploy", "the local kind declares no deploy command")
        if entry["deploy"]["status"] in (STATUS_PASS, STEP_NOT_DECLARED):
            entry["test"] = step("test", str(environment.get("test_command") or ""))
            entry["environment_checks"] = [
                step(check["name"], check["command"]) for check in checks
            ]
        else:
            entry["skipped_reason"] = "the deploy did not succeed, so no test ran"
    finally:
        # The deploy step was reached, so the environment may hold something: tear it down
        # whatever happened above, a failed deploy, a failed test or an interrupt included.
        teardown_command = environment.get("teardown_command")
        if teardown_command:
            entry["teardown"] = step("teardown", teardown_command, environment_step=True)
        else:
            entry["teardown"] = _not_declared(
                "teardown", "the repository declares no teardown command"
            )
        if lease is not None and token is not None and lease_backend is not None:
            try:
                released = lease_backend.release(lease["name"], token)
                lease_block["release_status"] = released.status
                if released.status != environment_lease.RELEASED:
                    problems.append(f"lease release: {released.status}: {released.detail}")
            except environment_lease.LeaseError as exc:
                lease_block["release_status"] = environment_lease.COULD_NOT_EXECUTE
                problems.append(f"lease release: {exc}")


def could_not_execute_streak(passes: Sequence[dict[str, Any]]) -> int:
    """How many of the latest passes in a row could not execute."""
    streak = 0
    for entry in reversed(passes):
        if not isinstance(entry, dict) or entry.get("status") != STATUS_COULD_NOT_EXECUTE:
            break
        streak += 1
    return streak


def apply_combined_pass(
    record: run_record.RunRecord,
    environment: dict[str, Any],
    entry: dict[str, Any],
    green: bool,
) -> dict[str, Any]:
    """Land one finished pass on *record*, read under the record's lock. Added to, never replaced.

    The pass is numbered against the fresh block. A green pass writes ``handed_to_code_review``
    with the full revision, the pass number and whether the repository's waiver applied.
    """
    block = record.extra.setdefault(COMBINED_KEY, {})
    if not isinstance(block, dict):
        raise BuildLoopError(f"the record's {COMBINED_KEY!r} key is not an object")
    block["environment"] = dict(environment)
    passes = block.setdefault("passes", [])
    if not isinstance(passes, list):
        raise BuildLoopError(f"the record's {COMBINED_KEY}.passes key is not a list")
    landed = {**entry, "pass": len(passes) + 1}
    passes.append(landed)
    if green:
        block["handed_to_code_review"] = {
            "revision": landed["revision"],
            "at": landed["finished_at"],
            "pass": landed["pass"],
            "waived": "waiver" in landed,
        }
    return landed


def functional_evidence(record: Any, revision: str) -> dict[str, Any]:
    """Whether *record* carries a passing combined-branch functional run at *revision*.

    The question code review's gate asks (pre-review testing U5). *record* is a ``RunRecord`` or
    the record's raw JSON object. ``admits`` is true when the latest pass at exactly *revision* is
    green, including a waived one. A green pass at another revision is stale and admits nothing,
    and a later pass at the same revision that did not go green withdraws an earlier green one:
    the newest evidence about a revision is the evidence.
    """
    extra = getattr(record, "extra", None)
    source = extra if isinstance(extra, dict) else record if isinstance(record, dict) else {}
    block = source.get(COMBINED_KEY) if isinstance(source, dict) else None
    passes = block.get("passes") if isinstance(block, dict) else None
    at_revision = [
        entry
        for entry in (passes if isinstance(passes, list) else [])
        if isinstance(entry, dict) and entry.get("revision") == revision
    ]
    environment = block.get("environment") if isinstance(block, dict) else None
    evidence: dict[str, Any] = {
        "admits": False,
        "status": "missing",
        "pass": None,
        "pass_status": None,
        "revision": revision,
        "environment": {
            "kind": (environment or {}).get("kind"),
            "scope": (environment or {}).get("scope"),
        },
        "deploy": None,
        "test": None,
        "teardown": None,
        "waiver_reason": None,
    }
    if not at_revision:
        return evidence
    latest = at_revision[-1]
    for step in ("deploy", "test", "teardown"):
        result = latest.get(step)
        evidence[step] = result.get("status") if isinstance(result, dict) else None
    evidence["pass"] = latest.get("pass")
    evidence["pass_status"] = latest.get("status")
    if not latest.get("green"):
        evidence["status"] = "failed"
        return evidence
    waiver = latest.get("waiver")
    evidence["admits"] = True
    evidence["status"] = "waived" if isinstance(waiver, dict) else "passed"
    evidence["waiver_reason"] = waiver.get("reason") if isinstance(waiver, dict) else None
    return evidence


def _latest_green_revision(record: run_record.RunRecord) -> str | None:
    block = record.extra.get(COMBINED_KEY)
    handed = block.get("handed_to_code_review") if isinstance(block, dict) else None
    revision = handed.get("revision") if isinstance(handed, dict) else None
    return revision if isinstance(revision, str) and FULL_REVISION.match(revision) else None


def _commits_since(repo_root: Path, older: str, newer: str, *, runner: Runner) -> int | None:
    """How many commits *newer* has that *older* does not, or ``None`` when git cannot say."""
    try:
        code, detail = runner(
            ["git", "-C", str(repo_root), "rev-list", f"{older}..{newer}", "--count"], 60, None
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    text = detail.strip()
    return int(text) if code == 0 and text.isdigit() else None


def handoff(
    record: run_record.RunRecord,
    revision: str,
    *,
    repo_root: Path,
    runner: Runner,
    from_head: bool,
) -> dict[str, Any]:
    """The review gate: the evidence that admits *revision* to code review, or a refusal.

    Reads and writes nothing else. Returns the evidence when the latest combined pass at *revision*
    is green, waived or not, and raises ``BuildLoopError`` naming what is missing otherwise. When
    *revision* is ``HEAD`` and the green pass is at an earlier commit, the refusal says how far
    ``HEAD`` moved, because the fix is to run the combined pass again, not to review the old one.
    """
    evidence = functional_evidence(record, revision)
    if evidence["admits"]:
        waived = evidence["status"] == "waived"
        return {
            "revision": revision,
            "pass": evidence["pass"],
            "status": evidence["status"],
            "waived": waived,
            "waiver_reason": evidence["waiver_reason"],
            "environment": evidence["environment"],
            "deploy": evidence["deploy"],
            "test": evidence["test"],
            "teardown": evidence["teardown"],
        }
    if evidence["status"] == "failed":
        raise BuildLoopError(
            f"the latest combined pass at {revision} is {evidence['pass_status']}, not green; "
            "run the combined-branch loop until it is green before code review"
        )
    green = _latest_green_revision(record)
    if from_head and green is not None and green != revision:
        moved = _commits_since(repo_root, green, revision, runner=runner)
        count = f"{moved} commit{'s' if moved != 1 else ''}" if moved is not None else "on"
        raise BuildLoopError(
            f"HEAD moved {count} since the green pass at {green}; run the combined-branch loop "
            f"again at {revision} before code review"
        )
    raise BuildLoopError(
        f"no passing combined-branch functional run and no waiver at {revision}; run "
        "build_loop.py --combined on it before code review"
    )


def format_combined_pass(entry: dict[str, Any]) -> str:
    """One combined pass's results, for a worker reading the terminal."""
    verdict = {
        STATUS_PASS: "green",
        STATUS_FAIL: "not green yet (a test or check failed)",
        STATUS_COULD_NOT_EXECUTE: "could not execute (an environment problem)",
    }.get(entry["status"], entry["status"])
    lines = [f"Combined-branch pass {entry['pass']} at {entry['revision']}: {verdict}", ""]
    for result in entry["baseline"]:
        lines.append(f"  [{result['status']}] baseline: {result['command']}")
    if "waiver" in entry:
        lines.append(f"  [waived] functional testing: {entry['waiver']['reason']}")
    lease = entry["lease"]
    if lease.get("required"):
        lines.append(f"  [{lease.get('status') or 'not reached'}] lease {lease.get('ref')}")
    for name in ("deploy", "test"):
        result = entry.get(name)
        if isinstance(result, dict):
            lines.append(f"  [{result['status']}] {name}: {result.get('command') or ''}".rstrip())
    for result in entry.get("environment_checks", []):
        lines.append(f"  [{result['status']}] environment check: {result['name']}")
    teardown = entry.get("teardown")
    if isinstance(teardown, dict):
        lines.append(f"  [{teardown['status']}] teardown: {teardown.get('command') or ''}".rstrip())
    if lease.get("required") and lease.get("release_status"):
        lines.append(f"  [{lease['release_status']}] lease release")
    review = entry.get("review")
    if isinstance(review, dict):
        lines.extend(_review_status_lines(review))
    if entry.get("skipped_reason"):
        lines.append(f"  {entry['skipped_reason']}")
    for problem in entry.get("environment_problems", []):
        lines.append(f"  environment problem: {problem}")
    return "\n".join(lines)


def format_combined_dry_run(
    environment: dict[str, Any], integration: dict[str, Any], baseline: Sequence[str],
    checks: Sequence[dict[str, Any]],
) -> str:
    """The combined pass as a reader sees it: what would run, where, and under which lease."""
    lines = ["The combined-branch pass for this run, before code review.", ""]
    lines.append("Mechanical baseline, on the combined branch:")
    lines.extend(f"  {command}" for command in baseline)
    if not baseline:
        lines.append("  none declared in the run record")
    lines.append("")
    if environment.get("mode") == functional_environment.MODE_WAIVED:
        lines.append(
            f"Functional testing is waived ({environment.get('level')} level): "
            f"{environment.get('reason')}. Only the baseline runs."
        )
    else:
        lines.append(f"Functional-test environment, from {environment.get('source')}:")
        lines.extend(f"  {line}" for line in functional_environment.describe(environment))
        lines.append("")
        lines.append("Environment-bound plan checks, after the test command:")
        lines.extend(f"  {format_check(check)}" for check in checks)
        if not checks:
            lines.append("  none prescribed")
        lease = functional_environment.lease_of(environment)
        lines.append("")
        if lease is None:
            lines.append("Lease: not required, the environment is private to this run")
        else:
            lines.append(
                f"Lease: {environment_lease.REF_PREFIX}{lease['name']} on remote "
                f"{lease['remote']}, one run at a time"
            )
    lines.append("")
    if integration["single_lane"]:
        lines.append("Integration: one lane, so the pass runs on that branch")
    elif integration["complete"]:
        lines.append(f"Integration: all {integration['lanes']} lanes merged")
    else:
        lines.append("Integration: not complete; still to merge: " + ", ".join(integration["pending"]))
    return "\n".join(lines)


@contextmanager
def _sigterm_raises() -> Iterator[None]:
    """While a pass runs, SIGTERM raises, so teardown and the lease release still run."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def handler(signum: int, frame: Any) -> None:
        raise _Terminated(f"signal {signum}")

    previous = signal.signal(signal.SIGTERM, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_combined(
    args: argparse.Namespace,
    path: Path,
    record: run_record.RunRecord,
    repo_root: Path,
    profile: dict[str, Any],
    *,
    runner: Runner,
    lease_backend: environment_lease.LeaseBackend | None,
    sleep: Callable[[float], None],
    scan: Scan | None = None,
    declare: Declare | None = None,
    may_block: MayBlock | None = None,
    block_map: Mapping[str, Any] | None = None,
    ask: Any = None,
    sweep_home: Path | None = None,
) -> int:
    """The ``--combined`` command line: one pass, landed under the record's lock."""
    environment = require_answered(read_environment(record, profile))
    tripped = production_tripwire(environment)
    if tripped is not None:
        raise BuildLoopError(tripped)
    baseline = read_criterion(record, None, profile).baseline
    checks = environment_checks(record)
    if args.dry_run:
        integration = merge_turn.integration_state(record)
        print(format_combined_dry_run(environment, integration, baseline, checks))
        return EXIT_GREEN

    revision = head_revision(repo_root, runner=runner)
    problem = integration_problem(record, revision, repo_root, runner=runner)
    if problem is not None:
        raise BuildLoopError(problem)
    lease = functional_environment.lease_of(environment)
    if environment.get("mode") == functional_environment.MODE_WAIVED:
        lease = None
    if lease is not None and lease_backend is None:
        backend = environment_lease.GitRefLeaseBackend(repo_root, remote=lease["remote"])
        unusable = backend.check_remote()
        if unusable is not None:
            raise BuildLoopError(unusable)
        lease_backend = backend
    def next_pass() -> int:
        # Read from disk under the record's lock each time it is asked, so a pass that waited on
        # the lease takes the number after every pass that landed during the wait.
        with run_record.file_lock(path):
            fresh = load_record_file(path)
        block = fresh.extra.get(COMBINED_KEY)
        previous = block.get("passes") if isinstance(block, dict) else None
        return (len(previous) if isinstance(previous, list) else 0) + 1

    def land(entry: dict[str, Any], green: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with run_record.file_lock(path):
            fresh = load_record_file(path)
            landed = apply_combined_pass(fresh, environment, entry, green)
            save_record_file(path, fresh)
        passes: list[dict[str, Any]] = fresh.extra[COMBINED_KEY]["passes"]
        return landed, passes

    # The pass runs with no record lock held: a deploy can take many minutes (issue 95).
    try:
        with _sigterm_raises():
            entry, green = run_combined_pass(
                record,
                environment,
                baseline,
                revision,
                runner=runner,
                lease_backend=lease_backend,
                pass_number=next_pass(),
                next_pass=next_pass,
                branch=current_branch(repo_root, runner=runner),
                timeout=args.timeout,
                lease_wait=args.lease_wait,
                cwd=repo_root,
                sleep=sleep,
                report=lambda line: print(line, flush=True),
                scan=scan,
                declare=declare,
                may_block=may_block,
                block_map=block_map,
                ask=ask,
                sweep_home=sweep_home,
            )
    except CombinedPassInterrupted as stopped:
        landed, _ = land(stopped.entry, False)
        print(format_combined_pass(landed), file=sys.stderr)
        raise stopped.__cause__ or stopped from None

    landed, passes = land(entry, green)
    streak = could_not_execute_streak(passes)
    print(format_combined_pass(landed))
    print("")
    if green:
        print(f"Handing the combined branch to code review at {revision}.")
        return EXIT_GREEN
    if streak >= COULD_NOT_EXECUTE_STOP:
        print(
            f"Environment stop: {streak} consecutive combined passes could not execute. This is "
            "the environment, not the code; the operator needs to fix it:"
        )
        for past in passes[-streak:]:
            for problem_line in past.get("environment_problems") or ["(no detail recorded)"]:
                print(f"  pass {past['pass']}: {problem_line}")
        return EXIT_ENVIRONMENT_STOP
    print("Not green yet. Fix what the pass names and run it again — this is a loop pass.")
    return EXIT_NOT_GREEN


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--unit", default=None, help="Which unit row to run against.")
    mode.add_argument(
        "--combined",
        action="store_true",
        help=(
            "Run one combined-branch pass before code review: baseline, then deploy or start, "
            "test and teardown through the declared environment, one run at a time when shared."
        ),
    )
    mode.add_argument(
        "--handoff",
        action="store_true",
        help=(
            "The review gate: print the revision to review only when the latest combined pass at "
            "it is green or waived; refuse with exit 2 otherwise. Writes nothing."
        ),
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="With --handoff: the full revision to check instead of HEAD under --repo-root.",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="Seconds per check."
    )
    parser.add_argument(
        "--lease-wait",
        type=int,
        default=DEFAULT_LEASE_WAIT_SECONDS,
        help="With --combined: seconds to wait on a shared environment another run holds.",
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


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = subprocess_runner,
    lease_backend: environment_lease.LeaseBackend | None = None,
    sleep: Callable[[float], None] = time.sleep,
    scan: Scan | None = None,
    declare: Declare | None = None,
    may_block: MayBlock | None = None,
    block_map: Mapping[str, Any] | None = None,
    ask: Any = None,
    sweep_home: Path | None = None,
) -> int:
    """Run the command line. Every loader call sits inside this one catch, as ``run_record.py`` does."""
    args = build_parser().parse_args(argv)
    try:
        path = _resolve_record_path(args)
        record = load_record_file(path)
        repo_root = _resolve_repo_root(args)
        if args.revision is not None and not args.handoff:
            raise BuildLoopError("--revision belongs to --handoff, the review gate")
        if args.handoff:
            revision = args.revision
            if revision is not None and not FULL_REVISION.match(revision):
                raise BuildLoopError(
                    f"--revision {revision!r} is not a full forty-character commit identifier"
                )
            admitted = handoff(
                record,
                revision or head_revision(repo_root, runner=runner),
                repo_root=repo_root,
                runner=runner,
                from_head=revision is None,
            )
            print(json.dumps(admitted, sort_keys=True))
            return EXIT_GREEN
        profile = load_profile(
            repo_root, profile_path=Path(args.profile).resolve() if args.profile else None
        )
        if args.combined:
            return run_combined(
                args,
                path,
                record,
                repo_root,
                profile,
                runner=runner,
                lease_backend=lease_backend,
                sleep=sleep,
                scan=scan,
                declare=declare,
                may_block=may_block,
                block_map=block_map,
                ask=ask,
                sweep_home=sweep_home,
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
        raw_builder = unit.get("builder_record") if isinstance(unit, dict) else None
        recorded = raw_builder if isinstance(raw_builder, dict) else None
        iteration, green = run_iteration(
            criterion,
            revision,
            runner=runner,
            timeout=args.timeout,
            cwd=repo_root,
            repo=repo_root,
            builder_record=recorded,
            scan=scan,
            declare=declare,
            ask=ask,
            sweep_home=sweep_home,
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
