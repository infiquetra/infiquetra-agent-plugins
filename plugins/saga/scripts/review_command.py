#!/usr/bin/env python3
"""One review command, from a change to records (issue 160, card C10a).

``prepare`` writes the packet. ``finish`` checks one or two answers, re-runs reproductions, and
writes the review run. This command does not start a reviewer session. ``/code-review`` (after
card C10b) and the corpus harness are the callers. Orchestrate and agent-launcher start sessions.

The reproduction re-run is this process, confined, not a model. A non-zero exit is not enough:
the re-run has to fail with the recorded failure, on a tree of the change's head.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import review_calibration  # noqa: E402
import review_diff  # noqa: E402
import review_formula  # noqa: E402
import review_records  # noqa: E402
import review_tools  # noqa: E402
import reviewer_answer  # noqa: E402
import run_record  # noqa: E402
import saga_setup  # noqa: E402

RERUN_TIMEOUT = 120
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "env"})
_ENV_COPIED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
_READ_PREFIXES = ("/usr", "/bin", "/opt", "/opt/homebrew", "/Library", "/System", "/dev")
# /etc and the zoneinfo tree. Not /private/tmp and not the per-user temporary folder.
_NARROW_READS = ("/etc", "/private/etc", "/private/var/db/timezone")
# pytest and the dynamic linker write these. Other device nodes stay read-only.
_DEVICE_WRITES = ("/dev/null", "/dev/zero", "/dev/dtracehelper")
# /usr/bin/python3 is a shim into one of these. They are read-only toolchain trees.
_TOOLCHAIN_PREFIXES = (
    "/Applications/Xcode.app",
    "/Library/Developer/CommandLineTools",
)
# A recorded line that is only one of these matches every Python or pytest failure.
_GENERIC_LINES = frozenset({
    "Traceback (most recent call last):",
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
})
_PACKET_FILES = (
    "change.json",
    "diff.patch",
    "findings.json",
    "measurements.json",
    "degraded.json",
    "builder-record.json",
    "where-to-look.json",
    "missing-tools.json",
    "may-block.json",
    "open-search-cap.json",
    "grades.json",
)
_ZERO_USAGE = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0, "seconds": 0}

Process = Callable[..., review_tools.ProcessResult]
Confine = Callable[[Sequence[str], Path, Mapping[str, str], Path], review_tools.ProcessResult]
Ask = Callable[..., Any]


class CommandFailure(Exception):
    """A refusal this command prints and exits with."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def build_parser() -> argparse.ArgumentParser:
    """The two subcommands. ``--help`` loads none of the sweep client."""
    parser = argparse.ArgumentParser(
        prog="review_command.py",
        description=(
            "Prepare a review packet from a change, or finish one or two answers into a review "
            "run. This command starts no reviewer session."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Write the packet for a change.")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--base", required=True)
    prepare.add_argument("--head", required=True)
    prepare.add_argument("--profile", type=Path, required=True)
    prepare.add_argument("--builder-record", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    finish = commands.add_parser("finish", help="Check answers and write the review run.")
    finish.add_argument("--packet", type=Path, required=True)
    finish.add_argument("--answer", type=Path, action="append", default=[])
    finish.add_argument("--result", type=Path, action="append", default=[])
    for command in (prepare, finish):
        command.add_argument("--issue", type=int)
        command.add_argument("--card", type=int)
        command.add_argument("--round", type=int, default=1)
        command.add_argument("--unit")
        command.add_argument("--bank", type=Path)
        command.add_argument("--calibration", type=Path)
        command.add_argument("--store-root", type=Path)
        command.add_argument("--home", type=Path)
    finish.add_argument("--final", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    adapters: Sequence[review_tools.Adapter] | None = None,
    runner: Process | None = None,
    ask: Ask | None = None,
    confine: Confine | None = None,
) -> int:
    """Run one subcommand. The keyword arguments are the test seams. The CLI does not expose them."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    process = runner or review_tools.subprocess_runner
    try:
        if args.command == "prepare":
            _prepare(args, adapters=adapters, runner=process, ask=ask)
        else:
            _finish(args, runner=process, ask=ask, confine=confine)
    except CommandFailure as exc:
        if exc.message:
            print(exc.message, file=sys.stderr)
        return exc.code
    return 0


def child_environment(scratch: Path) -> dict[str, str]:
    """The re-run environment: a few locale variables, plus ``HOME`` and ``TMPDIR``.

    Credential variables in the parent are not copied.
    """
    env = {name: os.environ[name] for name in _ENV_COPIED if os.environ.get(name)}
    env["HOME"] = str(scratch)
    env["TMPDIR"] = str(scratch / "tmp")
    return env


def run_confined(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    scratch: Path,
    *,
    runner: Process,
    timeout: int = RERUN_TIMEOUT,
) -> review_tools.ProcessResult:
    """Run ``argv`` inside the platform helper. The caller has already decided one exists."""
    helper = platform_helper()
    if helper is None:
        raise CommandFailure(2, "no reproduction helper")
    if helper == "sandbox-exec":
        wrapped: list[str] = [
            "/usr/bin/sandbox-exec", "-p", _seatbelt(scratch, argv), *list(argv),
        ]
    else:
        wrapped = _bwrap(scratch, argv)
    return runner(wrapped, cwd=cwd, env=dict(env), timeout=timeout, shell=False)


def platform_helper() -> str | None:
    """``sandbox-exec`` on macOS, ``bwrap`` on Linux, or None."""
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        return "sandbox-exec"
    if sys.platform == "linux" and shutil.which("bwrap"):
        return "bwrap"
    return None


def reproduction_available(home: Path, confine: Confine | None) -> bool:
    """True when a test injected confinement, or the machine record says the helper is available."""
    if confine is not None:
        return True
    machine = saga_setup.load_machine(home)
    if not isinstance(machine, dict):
        return False
    survey = machine.get("survey")
    sandbox = survey.get("sandbox") if isinstance(survey, Mapping) else None
    if not isinstance(sandbox, Mapping) or sandbox.get("reproduction") != "available":
        return False
    return platform_helper() is not None


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------


def _prepare(
    args: argparse.Namespace,
    *,
    adapters: Sequence[review_tools.Adapter] | None,
    runner: Process,
    ask: Ask | None,
) -> None:
    repo = Path(args.repo)
    out = Path(args.out)
    home = Path(args.home) if args.home is not None else Path.home()
    builder_path = Path(args.builder_record)
    builder = _read_json(builder_path, "builder record")
    problems = review_records.validate(builder)
    if problems:
        raise CommandFailure(2, "\n".join(problems))
    if not isinstance(builder, Mapping):
        raise CommandFailure(2, "builder record: must be a JSON object")
    store = _existing_store(args)
    base = _resolve(runner, repo, args.base)
    head = _resolve(runner, repo, args.head)
    calibration = _calibration_path(args)
    given_profile = Path(args.profile)
    profile = _may_block_profile(runner, repo, base, given_profile)
    temporary = profile.resolve() != given_profile.resolve()
    staging = Path(tempfile.mkdtemp(prefix="saga-review-packet-"))
    try:
        _probe_calibration(calibration, profile)
        code = review_tools.run(
            repo, base, head, given_profile, staging, home, builder_path,
            adapters=list(adapters) if adapters is not None else None,
            runner=runner,
            framework=False,
        )
        if code != 0:
            raise CommandFailure(code, "")
        findings = _read_json(staging / "findings.json", "findings")
        measurements = _read_json(staging / "measurements.json", "measurements")
        degraded = list(_read_json(staging / "degraded.json", "degraded"))
        if not isinstance(findings, list) or not isinstance(measurements, list):
            raise CommandFailure(2, "the tool runner wrote records that are not lists")
        try:
            change = review_diff.read(repo, base, head)
        except review_diff.ReviewDiffError as exc:
            raise CommandFailure(2, str(exc)) from exc
        patch = _git(runner, repo, ["diff", "--find-renames", base, head])
        if patch.code != 0:
            detail = (patch.stderr or patch.stdout or "git diff failed").strip()
            raise CommandFailure(2, detail)
        items, sweep_degraded = _sweep(
            repo, base, head, args, calibration, home, ask,
        )
        degraded.extend(sweep_degraded)
        gaps = [entry for entry in degraded if entry.get("reason") in {"missing", "known-gap"}]
        where = [*items, *(_gap_item(entry) for entry in gaps)]
        may_block, reasons = _may_block_map(findings, measurements, calibration, profile)
        try:
            grades = review_formula.compute({
                "findings": findings,
                "measurements": measurements,
                "builder_records": [builder],
                "may_block": may_block,
                "degraded_inputs": degraded,
            })
        except review_formula.FormulaError as exc:
            raise CommandFailure(2, str(exc)) from exc
        files = [{"path": item.path, "status": item.status} for item in change.files]
        _write_json(staging / "change.json", {
            "repo": str(repo.resolve()), "base": base, "head": head, "files": files,
        })
        (staging / "diff.patch").write_text(patch.stdout, encoding="utf-8")
        _write_json(staging / "builder-record.json", builder)
        _write_json(staging / "degraded.json", degraded)
        _write_json(staging / "where-to-look.json", where)
        _write_json(staging / "missing-tools.json", [_gap_question(entry) for entry in gaps])
        _write_json(staging / "may-block.json", reasons)
        _write_json(staging / "open-search-cap.json", {"cap": reviewer_answer.OPEN_SEARCH_CAP})
        _write_json(staging / "grades.json", grades)
        if store is not None:
            try:
                review_records.record_run(store, int(args.issue), {
                    "card": _card(args),
                    "repo": str(repo.resolve()),
                    "base": base,
                    "head": head,
                    "saga_version": _saga_version(),
                    "round": args.round,
                    "tool_versions": _tool_versions(findings),
                    "usage": dict(_ZERO_USAGE),
                    "where_to_look": [],
                    "raw_outputs": [],
                    "findings": findings,
                    "measurements": measurements,
                    "builder_records": [builder],
                    "may_block": may_block,
                    "degraded_inputs": degraded,
                })
            except review_records.ReviewRecordError as exc:
                raise CommandFailure(2, "\n".join(exc.problems)) from exc
            except (run_record.RunRecordError, review_formula.FormulaError) as exc:
                raise CommandFailure(2, str(exc)) from exc
        _publish(staging, out)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if temporary:
            profile.unlink(missing_ok=True)


def _sweep(
    repo: Path,
    base: str,
    head: str,
    args: argparse.Namespace,
    calibration: Path,
    home: Path,
    ask: Ask | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    bank_path = Path(args.bank) if args.bank is not None else (
        _SCRIPTS_DIR.parent / "references" / "question-bank.json"
    )
    if not bank_path.is_file():
        return [], [_degraded("correctness", "none", "question-bank", "jev", "no-bank")]
    try:
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [_degraded("correctness", "none", "question-bank", "jev", _one_line(exc))]
    rate = _jev_rate()
    if rate is None:
        return [], [_degraded("correctness", "none", "model-prices", "jev", "no-rate")]
    import sweep_pieces  # noqa: PLC0415

    try:
        cut = sweep_pieces.pieces(repo, base, head, bank, calibration=calibration)
    except sweep_pieces.SweepPiecesError as exc:
        return [], [_degraded("correctness", "none", "sweep", "jev", _one_line(exc))]
    questions = bank.get("questions") if isinstance(bank, Mapping) else []
    if not isinstance(questions, list):
        questions = []
    pieces = cut.get("pieces") if isinstance(cut, Mapping) else []
    if not isinstance(pieces, list):
        pieces = []
    cache = home / ".saga" / "review-sweep" / head
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "log").mkdir(parents=True, exist_ok=True)
    try:
        import bundled_fleet  # noqa: PLC0415

        module = bundled_fleet.load("jev_sweep")
        result = module.sweep(
            bank, pieces, cut.get("thresholds") or {}, rate,
            repo=str(repo), head=head, cache_dir=cache, log_dir=cache / "log", ask=ask,
        )
    except Exception as exc:  # noqa: BLE001  (a failed sweep degrades; it does not stop the review)
        return [], [_degraded("correctness", "none", "sweep", "jev", _one_line(exc))]
    raw_items = result.get("items") if isinstance(result, Mapping) else []
    raw_degraded = []
    if isinstance(cut, Mapping):
        raw_degraded.extend(cut.get("degraded") or [])
    if isinstance(result, Mapping):
        raw_degraded.extend(result.get("degraded") or [])
    mapped = [_map_sweep(entry, questions, pieces) for entry in raw_degraded if isinstance(entry, Mapping)]
    items = [item for item in raw_items if isinstance(item, Mapping)] if isinstance(raw_items, list) else []
    for item in items:
        item.pop("_piece", None)
    return items, mapped


def _map_sweep(
    entry: Mapping[str, Any], questions: Sequence[Any], pieces: Sequence[Any],
) -> dict[str, str]:
    question_id = entry.get("question")
    piece_id = entry.get("piece")
    lens = "correctness"
    if isinstance(question_id, str):
        for question in questions:
            if isinstance(question, Mapping) and question.get("id") == question_id:
                named = question.get("lens")
                if named in review_formula.LENSES:
                    lens = str(named)
                break
    language = "none"
    if isinstance(piece_id, str):
        for piece in pieces:
            if isinstance(piece, Mapping) and piece.get("id") == piece_id:
                named = piece.get("language")
                if named in review_formula.LANGUAGES:
                    language = str(named)
                break
    reason = entry.get("reason")
    return _degraded(
        lens, language, question_id if isinstance(question_id, str) and question_id else "sweep",
        "jev", str(reason) if reason else "sweep",
    )


def _jev_rate() -> dict[str, float] | None:
    import yaml  # noqa: PLC0415

    path = _SCRIPTS_DIR.parent / "references" / "model-prices.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    models = data.get("models") if isinstance(data, Mapping) else None
    if not isinstance(models, Mapping):
        return None
    for row in models.values():
        if not isinstance(row, Mapping):
            continue
        aliases = row.get("aliases") or []
        if "jev-latest" not in aliases:
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


def _gap_item(entry: Mapping[str, Any]) -> dict[str, Any]:
    tool = str(entry.get("tool") or "tool")
    question = entry.get("input") or tool
    return {
        "kind": "where_to_look",
        "schema": review_records.SCHEMA,
        "lens": entry.get("lens"),
        "language": entry.get("language"),
        "location": {"scope": "whole-project", "file": ".", "anchor": tool},
        "questions": [{"id": question, "probability": 1}],
        "classifier": {"name": "missing-tool", "model": "none"},
        "degraded": True,
    }


def _gap_question(entry: Mapping[str, Any]) -> dict[str, str]:
    tool = str(entry.get("tool") or "tool")
    reason = str(entry.get("reason") or "")
    return {
        "tool": tool,
        "lens": str(entry.get("lens") or ""),
        "language": str(entry.get("language") or ""),
        "reason": reason,
        "question": f"The tool {tool} did not run ({reason}). Answer the check it would have run.",
    }


def _may_block_map(
    findings: Sequence[Any],
    measurements: Sequence[Any],
    calibration: Path,
    profile: Path,
) -> tuple[dict[str, dict[str, bool]], dict[str, dict[str, dict[str, Any]]]]:
    pairs: set[tuple[str, str]] = set()
    for record in (*findings, *measurements):
        if not isinstance(record, Mapping):
            continue
        lens = record.get("lens")
        language = record.get("language")
        if lens in review_formula.LENSES and language in review_formula.LANGUAGES:
            pairs.add((str(lens), str(language)))
            pairs.add((str(lens), "none"))
    if not pairs:
        pairs.add(("correctness", "none"))
    bools: dict[str, dict[str, bool]] = {}
    reasons: dict[str, dict[str, dict[str, Any]]] = {}
    root = review_calibration.package_dir()
    for lens, language in sorted(pairs):
        try:
            line = review_calibration.may_block(
                lens, language, root=root, calibration=calibration, profile=profile,
            )
        except review_calibration.CalibrationError as exc:
            raise CommandFailure(2, str(exc)) from exc
        blocks = line.startswith("yes")
        bools.setdefault(lens, {})[language] = blocks
        reasons.setdefault(lens, {})[language] = {"blocks": blocks, "reason": line}
    return bools, reasons


def _probe_calibration(calibration: Path, profile: Path) -> None:
    try:
        review_calibration.may_block(
            "correctness", "none",
            root=review_calibration.package_dir(), calibration=calibration, profile=profile,
        )
    except review_calibration.CalibrationError as exc:
        raise CommandFailure(2, str(exc)) from exc


def _may_block_profile(runner: Process, repo: Path, base: str, profile: Path) -> Path:
    shown = _git(runner, repo, ["show", f"{base}:.saga-profile.json"])
    if shown.code == 0:
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115  (lives until the process exits)
            prefix="saga-base-profile-", suffix=".json", delete=False,
        )
        handle.write(shown.stdout.encode())
        handle.close()
        return Path(handle.name)
    if _outside(repo, profile):
        return profile
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
        prefix="saga-empty-profile-", suffix=".json", delete=False,
    )
    handle.write(b"{}\n")
    handle.close()
    return Path(handle.name)


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------


def _finish(
    args: argparse.Namespace,
    *,
    runner: Process,
    ask: Ask | None,
    confine: Confine | None,
) -> None:
    packet = Path(args.packet)
    cap = _open_search_cap(packet)
    answers, results = _pairs(args)
    items = _read_json(packet / "where-to-look.json", "where-to-look")
    if not isinstance(items, list):
        raise CommandFailure(2, "where-to-look.json: must be a JSON array")
    problems: list[str] = []
    for index, (answer, result) in enumerate(zip(answers, results, strict=True)):
        problems.extend(
            f"answers.{index}.{line}" if not line.startswith("scratch") else line
            for line in reviewer_answer.check(
                answer, items, open_search_cap=cap, result=result,
            )
        )
    if problems:
        raise CommandFailure(1, "\n".join(problems))
    change = _read_json(packet / "change.json", "change")
    if not isinstance(change, Mapping):
        raise CommandFailure(2, "change.json: must be a JSON object")
    repo = Path(str(change.get("repo") or ""))
    home = Path(args.home) if args.home is not None else Path.home()
    store = _existing_store(args)
    builder = _read_json(packet / "builder-record.json", "builder record")
    if not isinstance(builder, Mapping):
        raise CommandFailure(2, "builder record: must be a JSON object")
    unit = _unit(store, args, builder) if store is not None else None
    converted = []
    for answer, result in zip(answers, results, strict=True):
        try:
            converted.append(reviewer_answer.to_records(
                answer, items, result, ask=ask, use_jev=True, open_search_cap=cap,
            ))
        except reviewer_answer.AnswerRefused as exc:
            raise CommandFailure(1, "\n".join(exc.problems)) from exc
    degraded = list(_read_json(packet / "degraded.json", "degraded"))
    available = reproduction_available(home, confine)
    for produced, result in zip(converted, results, strict=True):
        degraded.extend(_rerun_findings(
            produced["findings"], result, repo, str(change.get("head") or ""),
            home, runner, confine, available,
        ))
    findings, owners = _merge_findings(converted, _read_json(packet / "findings.json", "findings"))
    where = _merge_where([produced["where_to_look"] for produced in converted])
    _mark_missing_tool(findings, where)
    if args.final:
        degraded.extend(_final_round(
            findings, owners, results, repo, str(change.get("head") or ""), home, runner, confine,
            available,
        ))
    may_block = _bools_from_packet(packet)
    reviewers, usage_specs, usage_totals = _reviewers_and_usage(
        results, calibration=_calibration_path(args),
    )
    for reason in usage_specs["degraded"]:
        degraded.append(reason)
    inputs: dict[str, Any] = {
        "card": _card(args),
        "repo": str(change.get("repo") or ""),
        "base": str(change.get("base") or ""),
        "head": str(change.get("head") or ""),
        "saga_version": _saga_version(),
        "round": args.round,
        "tool_versions": _tool_versions(findings),
        "usage": usage_totals,
        "where_to_look": where,
        "raw_outputs": [],
        "findings": findings,
        "measurements": _read_json(packet / "measurements.json", "measurements"),
        "builder_records": [builder],
        "may_block": may_block,
        "degraded_inputs": degraded,
        "reviewers": reviewers,
    }
    try:
        run = review_records.build_run(inputs)
    except review_records.ReviewRecordError as exc:
        raise CommandFailure(2, "\n".join(exc.problems)) from exc
    except review_formula.FormulaError as exc:
        raise CommandFailure(2, str(exc)) from exc
    if store is not None and unit is not None:
        _store_run(store, int(args.issue), unit, run, usage_specs["add"])
    _write_json(packet / "review-run.json", run)


def _open_search_cap(packet: Path) -> int:
    path = packet / "open-search-cap.json"
    if not path.exists():
        return reviewer_answer.OPEN_SEARCH_CAP
    data = _read_json(path, "open-search cap")
    cap = data.get("cap") if isinstance(data, Mapping) else None
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        raise CommandFailure(2, "open-search-cap.json: cap must be a non-negative integer")
    return cap


def _pairs(args: argparse.Namespace) -> tuple[list[Any], list[Any]]:
    answer_paths = list(args.answer or [])
    result_paths = list(args.result or [])
    if not answer_paths or len(answer_paths) != len(result_paths) or len(answer_paths) > 2:
        raise CommandFailure(2, "finish takes one or two answer files and the same number of results")
    answers = [_read_json(Path(path), "answer") for path in answer_paths]
    results = [_read_json(Path(path), "result") for path in result_paths]
    return answers, results


def _rerun_findings(
    findings: list[dict[str, Any]],
    result: Mapping[str, Any],
    repo: Path,
    head: str,
    home: Path,
    runner: Process,
    confine: Confine | None,
    available: bool,
) -> list[dict[str, str]]:
    reproduced = [finding for finding in findings if finding.get("evidence") == "reproduced"]
    if not reproduced:
        return []
    if not available:
        for finding in reproduced:
            _downgrade(finding)
        return [_degraded(
            reproduced[0].get("lens") or "correctness", "none", "sandbox", "review-command",
            "no-sandbox",
        )]
    source = _scratch_source(result, repo)
    if source is None:
        for finding in reproduced:
            _downgrade(finding)
        return [_degraded(
            reproduced[0].get("lens") or "correctness", "none", "scratch", "review-command",
            "bad-scratch",
        )]
    scratch = Path(tempfile.mkdtemp(prefix="saga-review-rerun-"))
    scratch.chmod(0o700)
    degraded: list[dict[str, str]] = []
    try:
        if not _export_head(runner, repo, head, scratch):
            for finding in reproduced:
                _downgrade(finding)
            return [_degraded(
                reproduced[0].get("lens") or "correctness", "none", "head", "review-command",
                "head-export",
            )]
        _copy_shared_tests(source, scratch, result)
        for finding in reproduced:
            degraded.extend(_rerun_one(
                finding, source, scratch, home, runner, confine,
            ))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return degraded


def _rerun_one(
    finding: dict[str, Any],
    source: Path,
    scratch: Path,
    home: Path,
    runner: Process,
    confine: Confine | None,
) -> list[dict[str, str]]:
    proof = finding.get("proof") if isinstance(finding.get("proof"), Mapping) else {}
    test = proof.get("test") if isinstance(proof, Mapping) else None
    relative = reviewer_answer.test_file_of(test) if isinstance(test, str) else ""
    if not _copy_one(source, scratch, relative):
        _downgrade(finding)
        return [_degraded(
            str(finding.get("lens") or "correctness"),
            str(finding.get("language") or "none"),
            relative or "test",
            "review-command",
            "missing-test-file",
        )]
    if not _make_tmp(scratch):
        _downgrade(finding)
        return [_degraded(
            str(finding.get("lens") or "correctness"), "none", "tmp", "review-command",
            "re-run-could-not-start",
        )]
    command = proof.get("command") if isinstance(proof, Mapping) else None
    argv = _argv(command)
    if argv is None:
        _downgrade(finding)
        return [_degraded(
            str(finding.get("lens") or "correctness"),
            str(finding.get("language") or "none"),
            str(command or ""),
            "review-command",
            "re-run-not-argv",
        )]
    env = child_environment(scratch)
    try:
        if confine is not None:
            ran = confine(argv, scratch, env, scratch)
        else:
            ran = run_confined(argv, scratch, env, scratch, runner=runner, timeout=RERUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        _downgrade(finding)
        return [_degraded(
            str(finding.get("lens") or "correctness"), "none", "re-run", "review-command",
            "re-run-timeout",
        )]
    except OSError:
        _downgrade(finding)
        return [_degraded(
            str(finding.get("lens") or "correctness"), "none", str(argv[0]), "review-command",
            "re-run-could-not-start",
        )]
    recorded = proof.get("output") if isinstance(proof, Mapping) else ""
    test = proof.get("test") if isinstance(proof, Mapping) else ""
    if _matches(
        ran,
        recorded if isinstance(recorded, str) else "",
        test if isinstance(test, str) else "",
    ):
        return []
    _downgrade(finding)
    return []


def _final_round(
    findings: list[dict[str, Any]],
    owners: dict[str, int],
    results: Sequence[Mapping[str, Any]],
    repo: Path,
    head: str,
    home: Path,
    runner: Process,
    confine: Confine | None,
    available: bool,
) -> list[dict[str, str]]:
    try:
        graded = review_formula.compute({"findings": findings})
    except review_formula.FormulaError as exc:
        raise CommandFailure(2, str(exc)) from exc
    blocking = []
    for item in graded["findings"]:
        proof = item.get("proof") if isinstance(item.get("proof"), Mapping) else {}
        if item.get("severity") == "blocks" and isinstance(proof, Mapping) and proof.get("command"):
            blocking.append(item["id"])
    if not blocking:
        return []
    if not available or not repo.is_dir():
        for finding in findings:
            if finding.get("id") in blocking:
                _downgrade(finding)
        return [_degraded("correctness", "none", "worktree", "review-command", "final-worktree")]
    path, hooks = _worktree(runner, repo, head)
    if path is None:
        for finding in findings:
            if finding.get("id") in blocking:
                _downgrade(finding)
        return [_degraded("correctness", "none", "worktree", "review-command", "final-worktree")]
    degraded: list[dict[str, str]] = []
    try:
        by_id = {finding.get("id"): finding for finding in findings}
        for ident in blocking:
            finding = by_id.get(ident)
            owner = owners.get(str(ident))
            if finding is None or owner is None:
                continue
            result = results[owner]
            source = _scratch_source(result, repo)
            if source is None:
                _downgrade(finding)
                degraded.append(_degraded(
                    "correctness", "none", "scratch", "review-command", "bad-scratch",
                ))
                continue
            _copy_shared_tests(source, path, result)
            degraded.extend(_rerun_one(finding, source, path, home, runner, confine))
    finally:
        _remove_worktree(runner, repo, path, hooks)
    return degraded


def _worktree(runner: Process, repo: Path, head: str) -> tuple[Path | None, Path | None]:
    path = Path(tempfile.mkdtemp(prefix="saga-review-final-"))
    hooks = Path(tempfile.mkdtemp(prefix="saga-hooks-"))
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    added = runner(
        ["git", "-c", f"core.hooksPath={hooks}", "worktree", "add", "--detach", str(path), head],
        cwd=repo, env=env, timeout=RERUN_TIMEOUT, shell=False,
    )
    if added.code != 0:
        shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(hooks, ignore_errors=True)
        return None, None
    return path, hooks


def _remove_worktree(runner: Process, repo: Path, path: Path, hooks: Path | None) -> None:
    try:
        runner(
            ["git", "worktree", "remove", "--force", str(path)],
            cwd=repo, env=dict(os.environ), timeout=RERUN_TIMEOUT, shell=False,
        )
    finally:
        shutil.rmtree(path, ignore_errors=True)
        if hooks is not None:
            shutil.rmtree(hooks, ignore_errors=True)


def _merge_findings(
    converted: Sequence[Mapping[str, Any]], tool_findings: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    order: list[str] = []
    for index, produced in enumerate(converted):
        for finding in produced.get("findings") or []:
            if not isinstance(finding, Mapping):
                continue
            ident = str(finding.get("id"))
            grouped.setdefault(ident, []).append((index, dict(finding)))
            if ident not in order:
                order.append(ident)
    merged: list[dict[str, Any]] = []
    owners: dict[str, int] = {}
    for ident in order:
        sides = grouped[ident]
        reproduced = [pair for pair in sides if pair[1].get("evidence") == "reproduced"]
        kept_index, kept = reproduced[0] if len(reproduced) == 1 else sides[0]
        record = copy.deepcopy(kept)
        record["degraded"] = any(item.get("degraded") for _, item in sides)
        if record.get("evidence") != "reproduced":
            record["unconfirmed"] = False
        elif record.get("consequence_jev") is None and (record.get("source") or {}).get("kind") == "llm":
            record["unconfirmed"] = True
        else:
            record["unconfirmed"] = False
        merged.append(record)
        owners[ident] = kept_index
    tools = tool_findings if isinstance(tool_findings, list) else []
    by_id = {str(finding.get("id")): finding for finding in merged}
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        ident = str(tool.get("id"))
        answer = by_id.get(ident)
        if answer is None:
            merged.append(copy.deepcopy(dict(tool)))
            continue
        if answer.get("evidence") == "reproduced":
            continue
        replacement = copy.deepcopy(dict(tool))
        by_id[ident] = replacement
        merged = [replacement if str(item.get("id")) == ident else item for item in merged]
        owners.pop(ident, None)
    return merged, owners


def _merge_where(lists: Sequence[Sequence[Any]]) -> list[Any]:
    if not lists:
        return []
    if len(lists) == 1:
        return list(lists[0])
    merged = []
    for index, item in enumerate(lists[0]):
        other = lists[1][index] if index < len(lists[1]) else item
        first = item.get("answer") if isinstance(item, Mapping) else None
        second = other.get("answer") if isinstance(other, Mapping) else None
        if (
            isinstance(first, Mapping) and first.get("kind") == "cleared"
            and isinstance(second, Mapping) and second.get("kind") == "finding"
        ):
            merged.append(other)
        else:
            merged.append(item)
    return merged


def _mark_missing_tool(findings: Sequence[dict[str, Any]], where: Sequence[Any]) -> None:
    linked: set[str] = set()
    for item in where:
        if not isinstance(item, Mapping):
            continue
        classifier = item.get("classifier")
        if not isinstance(classifier, Mapping) or classifier.get("name") != "missing-tool":
            continue
        answer = item.get("answer")
        if isinstance(answer, Mapping) and answer.get("kind") == "finding":
            linked.add(str(answer.get("finding_id")))
    for finding in findings:
        if str(finding.get("id")) in linked:
            finding["degraded"] = True


def _reviewers_and_usage(
    results: Sequence[Mapping[str, Any]], *, calibration: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, float]]:
    expected = _reviewer_configuration(calibration)
    reviewers: list[dict[str, Any]] = []
    add: list[dict[str, Any]] = []
    degraded: list[dict[str, str]] = []
    tokens_in = 0
    tokens_out = 0
    cost = 0.0
    seconds = 0.0
    for index, result in enumerate(results):
        usage = result.get("usage") if isinstance(result.get("usage"), Mapping) else {}
        prompt = _hex_or_none(result.get("prompt_sha256"))
        configuration = result.get("configuration")
        fingerprint = _hex_or_none(
            configuration.get("fingerprint") if isinstance(configuration, Mapping) else None
        )
        vendor, vendor_ok = _identifier(result.get("vendor"))
        model, model_ok = _identifier(_model_name(result.get("model")))
        effort, effort_ok = _identifier(result.get("effort"))
        role = result.get("role")
        if not isinstance(role, str) or run_record.ROLE_PATTERN.fullmatch(role) is None:
            role = "targeted-reviewer" if index == 0 else "external-reviewer"
        note = None
        if expected is None or fingerprint is None or fingerprint != expected:
            note = "reviewer-configuration"
        reviewers.append({
            "vendor": vendor if vendor_ok else "unknown",
            "model": model if model_ok else "unknown",
            "role": role,
            "prompt_sha256": prompt,
            "configuration_sha256": fingerprint,
            "note": note,
        })
        counts = _counts(usage)
        tokens_in += counts["uncached_input"] + counts["cache_read"] + counts["cache_write_1h"]
        tokens_out += counts["output"]
        cost += _number(usage.get("cost_usd", result.get("cost_usd")))
        seconds += _number(usage.get("seconds", result.get("seconds")))
        session = result.get("session_id") or usage.get("session_id")
        if not isinstance(session, str) or run_record.SESSION_ID_PATTERN.fullmatch(session) is None:
            degraded.append(_degraded("correctness", "none", "usage", "review-command", "no-session-id"))
            continue
        if not (vendor_ok and model_ok and effort_ok):
            degraded.append(_degraded(
                "correctness", "none", "usage", "review-command", "usage-unreadable",
            ))
            continue
        agent = result.get("agent_id") or usage.get("agent_id")
        add.append({
            "session_id": session,
            "agent_id": agent if isinstance(agent, str) else "",
            "role": role,
            "vendor": vendor,
            "model": model,
            "effort": effort,
            "counts": counts,
        })
    totals = {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost,
        "seconds": seconds,
    }
    return reviewers, {"add": add, "degraded": degraded}, totals


def _store_run(
    store: Path, issue: int, unit: str, run: Mapping[str, Any], additions: Sequence[Mapping[str, Any]],
) -> None:
    def change(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        if existing is None:
            raise run_record.RunRecordError(f"no record for issue {issue}")
        entry = {**run, "loop": review_records.STORED_LOOP}
        updated = run_record.RunRecord(
            **{**existing.__dict__, "review_cycles": [*existing.review_cycles, entry]},
        )
        for spec in additions:
            if _session_recorded(updated, unit, spec["session_id"], spec["agent_id"]):
                continue
            updated = run_record.add_usage(
                updated, unit,
                session_id=spec["session_id"], role=spec["role"], vendor=spec["vendor"],
                model=spec["model"], effort=spec["effort"], counts=spec["counts"],
            )
        return updated

    try:
        run_record.update(store, issue, change)
    except run_record.RunRecordError as exc:
        raise CommandFailure(2, str(exc)) from exc


def _session_recorded(record: run_record.RunRecord, unit: str, session_id: str, agent_id: str) -> bool:
    try:
        row = run_record.find_unit_row(record.units, unit)
    except run_record.RunRecordError:
        return False
    block = row.get("usage") if isinstance(row, Mapping) else None
    entries = block.get("entries") if isinstance(block, Mapping) else []
    if not isinstance(entries, list):
        return False
    combined = f"{session_id}/{agent_id}" if agent_id else ""
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        existing = str(entry.get("session_id") or "")
        if existing == session_id or (combined and existing == combined):
            return True
        if existing.startswith(f"{session_id}/"):
            return True
    return False


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def _existing_store(args: argparse.Namespace) -> Path | None:
    if args.issue is None:
        return None
    store = Path(args.store_root) if args.store_root is not None else run_record.resolve_store_root()
    if run_record.load(store, int(args.issue), warn=None) is None:
        raise CommandFailure(2, f"no record for issue {args.issue}")
    return store


def _unit(store: Path | None, args: argparse.Namespace, builder: Mapping[str, Any]) -> str:
    if store is None or args.issue is None:
        return ""
    record = run_record.load(store, int(args.issue), warn=None)
    if record is None:
        raise CommandFailure(2, f"no record for issue {args.issue}")
    rows = [row for row in record.units if isinstance(row, dict)]
    if args.unit:
        if not any(run_record.unit_key(row) == args.unit for row in rows):
            raise CommandFailure(2, f"no unit {args.unit!r} in the record")
        return str(args.unit)
    if len(rows) != 1 or run_record.unit_key(rows[0]) != builder.get("unit"):
        raise CommandFailure(2, "the record has no single unit row matching the builder record")
    return str(builder.get("unit"))


def _card(args: argparse.Namespace) -> int:
    if args.card is not None:
        return int(args.card)
    if args.issue is not None:
        return int(args.issue)
    return 1


def _calibration_path(args: argparse.Namespace) -> Path:
    if args.calibration is not None:
        return Path(args.calibration)
    return review_calibration.default_calibration_path()


def _resolve(runner: Process, repo: Path, name: str) -> str:
    result = _git(runner, repo, ["rev-parse", "--verify", f"{name}^{{commit}}"])
    sha = result.stdout.strip()
    if result.code != 0 or not sha:
        raise CommandFailure(2, f"unknown commit: {name}")
    return sha


def _git(runner: Process, repo: Path, args: Sequence[str]) -> review_tools.ProcessResult:
    return runner(
        ["git", *args], cwd=repo, env=dict(os.environ), timeout=RERUN_TIMEOUT, shell=False,
    )


def _scratch_source(result: Mapping[str, Any], repo: Path) -> Path | None:
    scratch = result.get("scratch") if isinstance(result.get("scratch"), Mapping) else None
    raw = scratch.get("path") if isinstance(scratch, Mapping) else None
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if not path.is_dir():
        return None
    resolved = path.resolve()
    home = Path.home().resolve()
    root = repo.resolve()
    if resolved == home or resolved == root:
        return None
    if _inside(root, resolved):
        return None
    return path


def _copy_shared_tests(source: Path, dest: Path, result: Mapping[str, Any]) -> None:
    scratch = result.get("scratch") if isinstance(result.get("scratch"), Mapping) else None
    changes = scratch.get("changes") if isinstance(scratch, Mapping) else None
    if not isinstance(changes, Mapping):
        return
    for kind in ("added", "modified"):
        for raw in changes.get(kind) or []:
            text = str(raw).lstrip("./")
            if reviewer_answer.looks_like_a_test(text):
                _copy_one(source, dest, text)


def _copy_one(source: Path, dest: Path, relative: str) -> bool:
    """Copy one regular file. A symlink is refused, including one whose target is inside."""
    if not relative:
        return False
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return False
    origin = source / path
    if origin.is_symlink() or not origin.is_file():
        return False
    try:
        resolved = origin.resolve(strict=True)
    except OSError:
        return False
    root = source.resolve()
    if resolved.is_symlink() or not _inside(root, resolved):
        return False
    target = dest / path
    cursor = dest.resolve()
    for part in path.parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resolved, target)
    return True


def _export_head(runner: Process, repo: Path, head: str, dest: Path) -> bool:
    """Extract the head tree into ``dest``. Links and paths that escape are skipped."""
    if not head or not repo.is_dir():
        return False
    handle = tempfile.NamedTemporaryFile(prefix="saga-review-head-", suffix=".tar", delete=False)
    handle.close()
    archive = Path(handle.name)
    try:
        result = _git(runner, repo, ["archive", "--format=tar", "-o", str(archive), head])
        if result.code != 0 or not archive.is_file():
            return False
        with tarfile.open(archive, "r:") as bundle:
            _extract_tree(bundle, dest)
        return True
    except (tarfile.TarError, OSError, ValueError):
        return False
    finally:
        archive.unlink(missing_ok=True)


def _extract_tree(bundle: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in bundle.getmembers():
        if not (member.isdir() or member.isfile()) or member.issym() or member.islnk():
            continue
        name = member.name[2:] if member.name.startswith("./") else member.name
        relative = Path(name)
        if not name or relative.is_absolute() or ".." in relative.parts:
            continue
        target = root.joinpath(*relative.parts)
        if target.is_symlink() or not _inside(root, target) and target != root:
            continue
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        parent = target.parent
        if parent.is_symlink() or not (_inside(root, parent) or parent == root):
            continue
        parent.mkdir(parents=True, exist_ok=True)
        source = bundle.extractfile(member)
        if source is None:
            continue
        with source, target.open("wb") as handle:
            shutil.copyfileobj(source, handle)
        mode = member.mode & 0o777
        target.chmod(0o755 if mode & 0o111 else 0o644)


def _make_tmp(scratch: Path) -> bool:
    temporary = scratch / "tmp"
    try:
        temporary.mkdir(parents=True, exist_ok=True)
        temporary.chmod(0o700)
    except OSError:
        return False
    return temporary.is_dir() and not temporary.is_symlink()


def _publish(staging: Path, out: Path) -> None:
    """Move a finished packet into place. A failure before this leaves ``out`` uncreated."""
    if out.exists():
        raise CommandFailure(2, f"packet directory already exists: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        staging.rename(out)
    except OSError:
        shutil.copytree(staging, out)


def _argv(command: Any) -> list[str] | None:
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    token = parts[0]
    name = Path(token).name if "/" in token or "\\" in token else token
    if name in _SHELLS:
        return None
    return parts


def _matches(result: review_tools.ProcessResult, output: str, test: str = "") -> bool:
    """True when the re-run failed with the recorded failure, not with a generic header."""
    if result.code == 0:
        return False
    captured = f"{result.stdout}{result.stderr}"[:8000]
    line = _specific_line(output, test)
    if line is None or line not in captured:
        return False
    if "::" in test and test not in captured:
        return False
    return True


def _specific_line(output: str, test: str) -> str | None:
    """The last recorded line that names this failure.

    A traceback header matches every Python crash. The test id matches every failure of that
    test. Neither is the failure.
    """
    file = test.split("::", 1)[0] if test else ""
    chosen = ""
    for raw in output.splitlines():
        line = raw.strip()[:200]
        if not line or _generic_line(line):
            continue
        if test and line == test:
            continue
        if file and line == file:
            continue
        chosen = line
    return chosen or None


def _generic_line(line: str) -> bool:
    if line in _GENERIC_LINES or line.startswith("INTERNALERROR"):
        return True
    if line.startswith(("====", "----", "++++")):
        return True
    return line.strip("=+- ") == ""


def _downgrade(finding: dict[str, Any]) -> None:
    location = finding.get("location") if isinstance(finding.get("location"), Mapping) else {}
    file = str(location.get("file") or ".") if isinstance(location, Mapping) else "."
    lines = location.get("lines") if isinstance(location, Mapping) else None
    start = lines.get("start") if isinstance(lines, Mapping) else 1
    if not isinstance(start, int):
        start = 1
    finding["evidence"] = "traced"
    finding["unconfirmed"] = False
    finding["proof"] = {
        "steps": [f"{file}:{start} re-run did not reproduce the recorded failure"],
    }


def _bools_from_packet(packet: Path) -> dict[str, dict[str, bool]]:
    data = _read_json(packet / "may-block.json", "may-block")
    bools: dict[str, dict[str, bool]] = {}
    if not isinstance(data, Mapping):
        return bools
    for lens, languages in data.items():
        if not isinstance(languages, Mapping):
            continue
        bools[str(lens)] = {
            str(language): bool(entry.get("blocks")) if isinstance(entry, Mapping) else False
            for language, entry in languages.items()
        }
    return bools


def _tool_versions(findings: Sequence[Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        source = finding.get("source")
        if isinstance(source, Mapping) and source.get("kind") == "tool":
            versions[str(source.get("name") or "tool")] = str(source.get("version") or "not-recorded")
    return dict(sorted(versions.items()))


def _saga_version() -> str:
    path = _SCRIPTS_DIR.parent / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "not-recorded"
    version = data.get("version") if isinstance(data, Mapping) else None
    if isinstance(version, str) and version.strip():
        return version
    return "not-recorded"


def _reviewer_configuration(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    return _hex_or_none(data.get("reviewer_configuration"))


def _hex_or_none(value: Any) -> str | None:
    if isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value):
        return value
    return None


def _identifier(value: Any) -> tuple[str, bool]:
    if isinstance(value, str) and run_record.IDENTIFIER_PATTERN.fullmatch(value):
        return value, True
    return "unknown", False


def _model_name(model: Any) -> Any:
    if isinstance(model, str):
        return model
    if not isinstance(model, Mapping):
        return None
    resolved = model.get("resolved")
    if isinstance(resolved, list) and resolved and isinstance(resolved[0], str):
        return resolved[0]
    requested = model.get("requested")
    return requested if isinstance(requested, str) else None


def _counts(usage: Mapping[str, Any]) -> dict[str, int]:
    return {
        "uncached_input": _count(usage.get("input_tokens")),
        "cache_read": _count(usage.get("cache_read_input_tokens")),
        "cache_write_5m": 0,
        "cache_write_1h": _count(usage.get("cache_creation_input_tokens")),
        "output": _count(usage.get("output_tokens")),
    }


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0.0
    return float(value)


def _degraded(lens: str, language: str, name: str, tool: str, reason: str) -> dict[str, str]:
    return {
        "lens": lens if lens in review_formula.LENSES else "correctness",
        "language": language if language in review_formula.LANGUAGES else "none",
        "input": name or "sweep",
        "tool": tool,
        "reason": reason,
    }


def _seatbelt(scratch: Path, argv: Sequence[str]) -> str:
    home = str(Path.home().resolve())
    root = str(scratch.resolve())
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow signal)",
        "(allow sysctl-read)",
        "(allow file-ioctl)",
        "(allow file-read-metadata)",
        # dyld reads the root directory before it maps a toolchain binary.
        '(allow file-read-data (literal "/"))',
    ]
    for prefix in (*_READ_PREFIXES, *_NARROW_READS, *_TOOLCHAIN_PREFIXES):
        if Path(prefix).exists():
            lines.append(f'(allow file-read* (subpath "{prefix}"))')
            lines.append(f'(allow file-map-executable (subpath "{prefix}"))')
    interpreter = Path(argv[0])
    if interpreter.is_absolute():
        parent = str(interpreter.resolve().parent)
        lines.append(f'(allow file-read* (subpath "{parent}"))')
        lines.append(f'(allow file-map-executable (subpath "{parent}"))')
    for node in _DEVICE_WRITES:
        if Path(node).exists():
            lines.append(f'(allow file-read* (literal "{node}"))')
            lines.append(f'(allow file-write* (literal "{node}"))')
    lines.append(f'(deny file-read* (subpath "{home}"))')
    lines.append(f'(deny file-write* (subpath "{home}"))')
    lines.append(f'(allow file-read* (subpath "{root}"))')
    lines.append(f'(allow file-write* (subpath "{root}"))')
    # No mach-lookup allow. The pasteboard and other named services stay unreachable.
    lines.append("(deny mach-lookup)")
    lines.append("(deny network*)")
    return "\n".join(lines) + "\n"


def _bwrap(scratch: Path, argv: Sequence[str]) -> list[str]:
    command = ["bwrap", "--unshare-net"]
    for prefix in ("/usr", "/bin", "/lib", "/lib64", "/opt", "/etc"):
        if Path(prefix).exists():
            command.extend(["--ro-bind", prefix, prefix])
    root = str(scratch.resolve())
    # A fresh dev mount has null, zero and urandom, and not the host disks.
    command.extend(["--dev", "/dev", "--bind", root, root, "--chdir", root, "--", *list(argv)])
    return command


def _outside(repo: Path, path: Path) -> bool:
    return not _inside(repo.resolve(), path.resolve())


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _one_line(exc: BaseException) -> str:
    return " ".join(str(exc).split())


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandFailure(2, f"{label}: {exc}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
