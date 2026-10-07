#!/usr/bin/env python3
"""Run the pinned review tools and report only what a change introduces (issue 151).

The command takes a repository, two commits, a profile and an output directory. It does not
take a run record. Line findings stay on added or modified lines. A whole-project result stays
only when its identity is new at the head commit. A missing tool is a degraded input, never a
pass and never a fail.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterator

import yaml

import coverage_lines
import review_diff
import review_formula
import review_records

SCHEMA = "review_records.v1"
TOOL_LIST = Path(__file__).resolve().parent.parent / "references" / "review-tools.yaml"


def plugin_root() -> Path:
    """The ``plugins/saga`` directory that contains this file's ``scripts`` folder."""
    return Path(__file__).resolve().parents[1]


MUTATION_CAP_SECONDS = 900
FINGERPRINT_COMPONENTS = (
    "plugins/saga/scripts/review_tools.py",
    "plugins/saga/scripts/review_diff.py",
    "plugins/saga/scripts/coverage_lines.py",
    "plugins/saga/scripts/review_adapters_all_languages.py",
    "plugins/saga/references/review-tools.yaml",
    "plugins/saga/scripts/review_adapters_python.py",
    "plugins/saga/scripts/review_adapters_infrastructure.py",
    "plugins/saga/scripts/review_adapters_shell.py",
    "plugins/saga/scripts/review_adapters_workflows.py",
    "plugins/saga/scripts/review_adapters_markdown.py",
)
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SUFFIXES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "typescript",
    ".jsx": "typescript",
    ".dart": "dart",
    ".rs": "rust",
    ".swift": "swift",
    ".md": "markdown",
    ".sh": "shell",
}
_REPORT_NAMES = ("coverage.json", "coverage.xml", "coverage.lcov", "lcov.info")
_SETTINGS_NAMES = (
    ".semgrepignore",
    ".gitleaks.toml",
    ".gitleaksignore",
    ".jscpd.json",
    "whitelizard.txt",
    "osv-scanner.toml",
)
_SAGA_RULES = "plugins/saga/references/semgrep-rules"
_ENV_COPIED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
_ENV_WINDOWS = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT")
# needle, lens, tool, reason. One degraded input per changed file that contains the needle.
_COMMENT_MARKERS = (
    ("gitleaks:allow", "security", "gitleaks", "gitleaks-allow"),
    ("jscpd:ignore", "architecture-maintainability", "jscpd", "jscpd-ignore"),
    ("lizard forgives", "architecture-maintainability", "lizard", "lizard-forgives"),
    ("noqa", "correctness", "ruff", "ruff-noqa"),
    ("ruff: ignore", "correctness", "ruff", "ruff-ignore"),
    ("nosec", "security", "bandit", "bandit-nosec"),
    ("shellcheck disable", "correctness", "shellcheck", "shellcheck-disable"),
)

Process = Callable[..., "ProcessResult"]


class RunnerFailure(Exception):
    """A run that stops with an exit code. Two is a refusal. One is unexpected."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class ToolGap(Exception):
    """The adapter declined to run and named the degraded reason and row."""

    def __init__(self, reason: str, row: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.row = row


@dataclass(frozen=True)
class ProcessResult:
    code: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class RulePin:
    pack: str | None = None
    sha256: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ScanContext:
    repo: Path
    root: Path
    home: Path
    configs: tuple[Path, ...] = ()
    report_dir: Path | None = None
    base: str = ""
    test_command: str = ""
    commands: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Hit:
    """One raw tool hit, before it becomes a finding."""

    rule_id: str
    path: str
    statement: str
    anchor: str
    level: str | None = None
    start: int | None = None
    end: int | None = None
    function: str | None = None
    advisory_ids: tuple[str, ...] = ()
    score: float | None = None
    whole_project: bool = False
    row: str | None = None
    language: str | None = None
    degraded: bool = False
    raw_output: str = ""
    tool: str = ""
    version: str = ""


@dataclass(frozen=True)
class ParseResult:
    hits: tuple[Hit, ...] = ()
    unfinished: bool = False
    problems: tuple[str, ...] = ()
    items: tuple[Mapping[str, Any], ...] = ()
    gaps: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Adapter:
    """The object C4b, C4c and C5b implement.

    ``invoke`` builds an argument vector and does not run it.
    """

    id: str
    tool: str
    invoke: Callable[[ScanContext], list[str]]
    parse: Callable[[str], ParseResult]
    languages: tuple[str, ...] = ("*",)
    rows: tuple[str, ...] = ()
    comparison: str = "lines"
    lens: str = "correctness"
    type_checker: bool = False
    mutation: bool = False
    mode: str = "report"
    timeout_seconds: int = 120
    platforms: tuple[str, ...] = ()
    env_dirs: tuple[str, ...] = ()
    lockfiles: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)
    default_version: str = "not-recorded"
    gap_path: str | None = None
    gap_rows: tuple[str, ...] = ()
    curated_rules: tuple[str, ...] = ()
    level_map: tuple[tuple[str, str], ...] = ()
    rules: tuple[RulePin, ...] = ()
    version_argv: tuple[str, ...] = ()
    narrow_env: bool = False


def load_tool_list(path: Path | None = None) -> list[dict[str, Any]]:
    """The default tool list. A pure read: importing this module does not run a tool."""
    target = Path(path) if path is not None else TOOL_LIST
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "review_tools.v1":
        raise RunnerFailure(2, f"{target}: schema must be review_tools.v1")
    tools = data.get("tools")
    if not isinstance(tools, list):
        raise RunnerFailure(2, f"{target}: tools must be a list")
    return [item for item in tools if isinstance(item, dict)]


def default_adapters() -> list[Adapter]:
    """Every adapter. Imported here so loading the tool list starts nothing."""
    import review_adapters_all_languages as every
    import review_adapters_infrastructure as infrastructure
    import review_adapters_markdown as markdown
    import review_adapters_python as python_adapters
    import review_adapters_shell as shell
    import review_adapters_workflows as workflows
    import review_checks

    return [
        *every.ADAPTERS,
        *python_adapters.ADAPTERS,
        *infrastructure.ADAPTERS,
        *shell.ADAPTERS,
        *workflows.ADAPTERS,
        *markdown.ADAPTERS,
        *review_checks.ADAPTERS,
    ]


def language_for(path: str) -> str:
    """Suffix to a formula language. An unmapped path is ``none``.

    CloudFormation is not inferred.
    """
    normalised = path.replace("\\", "/")
    if normalised.startswith(".github/workflows/") or "/.github/workflows/" in f"/{normalised}":
        return "github-workflows"
    return _SUFFIXES.get(Path(normalised).suffix.lower(), "none")


def filter_to_change(hits: Sequence[Hit], change: review_diff.Change) -> tuple[Hit, ...]:
    """Keep a line hit only when one of its lines was added or modified. Whole-project hits stay."""
    return tuple(hit for hit in hits if hit.whole_project or _overlaps(hit, change))


def _overlaps(hit: Hit, change: review_diff.Change) -> bool:
    if hit.start is None:
        return False
    covered = change.lines_for(_display_path(hit.path))
    end = hit.end or hit.start
    return any(line in covered for line in range(hit.start, end + 1))


def _display_path(path: str) -> str:
    text = path.replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def subprocess_runner(
    argv: Sequence[str] | str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    shell: bool,
) -> ProcessResult:
    """Run one tool. A string command, or a shell, is a programming error."""
    if shell or isinstance(argv, str):
        raise RuntimeError("a review tool receives an argument vector and shell=False")
    proc = subprocess.run(  # nosec B603
        list(argv),
        cwd=cwd,
        env=dict(env),
        timeout=timeout,
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    return ProcessResult(proc.returncode, proc.stdout, proc.stderr)


def store_raw(data: bytes, home: Path) -> str:
    """Write raw bytes under ``<home>/.saga/review-output/<sha256>``, owner-only.

    ``<home>/.saga`` is created mode 0700 when this call creates it, and left alone when it
    already exists. The path with no ``--home`` is ``Path.home() / ".saga" / "review-output"``.
    """
    digest = hashlib.sha256(data).hexdigest()
    parent = _saga(home)
    out = parent / "review-output"
    out_existed = out.exists()
    out.mkdir(mode=0o700, exist_ok=True)
    if not out_existed:
        out.chmod(0o700)
    target = out / digest
    if not target.exists():
        target.write_bytes(data)
        target.chmod(0o600)
    return digest


def semgrep_cache(home: Path, pack: str) -> Path:
    """The local pack cache. The pack name is a directory, never a registry URL."""
    return home / ".saga" / "semgrep-rules" / pack.replace("/", "--")


def digest_tree(directory: Path) -> str:
    """SHA-256 of the files under ``directory``. An empty directory is a missing cache."""
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        return ""
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(directory).as_posix().encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def run(
    repo: Path | str,
    base: str,
    head: str,
    profile: Path | str,
    output: Path | str,
    home: Path | str | None = None,
    builder: Path | str | None = None,
    adapters: Sequence[Adapter] | None = None,
    runner: Process | None = None,
    *,
    framework: bool = True,
) -> int:
    """Write the record files, including where-to-look items.

    Exit 0 when they are written, including all-degraded. The command does not take a run record.
    """
    try:
        return _run(
            Path(repo), base, head, Path(profile), Path(output),
            Path(home) if home is not None else Path.home(),
            Path(builder) if builder is not None else None,
            default_adapters() if adapters is None else list(adapters),
            runner or subprocess_runner,
            framework,
        )
    except RunnerFailure as exc:
        print(str(exc), file=sys.stderr)
        return exc.code


def _run(
    repo: Path,
    base: str,
    head: str,
    profile_path: Path,
    output: Path,
    home: Path,
    builder: Path | None,
    adapters: list[Adapter],
    process: Process,
    framework: bool,
) -> int:
    base_sha = _require_sha(repo, base)
    head_sha = _require_sha(repo, head)
    profile, profile_notes = _profile_for_run(repo, base_sha, head_sha, profile_path)
    builder_record = _load_builder(builder)
    try:
        change = review_diff.read(repo, base_sha, head_sha)
    except review_diff.ReviewDiffError as exc:
        raise RunnerFailure(2, str(exc)) from exc
    output.mkdir(parents=True, exist_ok=True)
    pending: list[Hit] = []
    items: list[Mapping[str, Any]] = []
    degraded: list[dict[str, str]] = list(profile_notes)
    deadline = time.monotonic() + MUTATION_CAP_SECONDS
    base_env = dict(os.environ)
    extra: list[tuple[str, Path]] = []
    try:
        with _worktree(repo, head_sha) as head_root:
            degraded.extend(_strip_settings(head_root))
            degraded.extend(_allow_comments(head_root, change))
            for adapter in adapters:
                _link_env(adapter, repo, head_root, base_sha, head_sha)
            for adapter in adapters:
                if adapter.mode == "fix" or not adapter.tool:
                    continue
                pending.extend(_run_adapter(
                    adapter, repo, base_sha, head_sha, head_root, change, home, profile,
                    process, base_env, deadline, degraded, items,
                ))
            measurements: list[dict[str, Any]] = []
            cov_findings: list[dict[str, Any]] = []
            if framework:
                relocated_hits, extra = _relocated(
                    head_root, profile, process, home, degraded
                )
                pending.extend(relocated_hits)
                cov_findings, measurements = _coverage(
                    change, profile, home, degraded, extra
                )
            findings = _findings_from(pending) + cov_findings
            _emit(output, findings, measurements, degraded, builder_record, items)
            return 0
    finally:
        for _language, path in extra:
            shutil.rmtree(path, ignore_errors=True)


def _run_adapter(
    adapter: Adapter,
    repo: Path,
    base_sha: str,
    head_sha: str,
    head_root: Path,
    change: review_diff.Change,
    home: Path,
    profile: Mapping[str, Any],
    process: Process,
    env: dict[str, str],
    deadline: float,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
) -> list[Hit]:
    if adapter.platforms and sys.platform not in adapter.platforms:
        degraded.append(_degraded(adapter, _primary_row(adapter), "unsupported-platform"))
        return []
    if adapter.gap_path is not None and not _present(_gap_target(adapter, head_root)):
        rows = adapter.gap_rows or adapter.rows[:1]
        for row in rows:
            degraded.append(_degraded(adapter, row, "known-gap"))
        return []
    rules = _rules_for(adapter, profile)
    with _rule_config(adapter, rules, repo, home, base_sha) as (configs, cache_problem):
        if cache_problem is not None:
            degraded.append(_degraded(adapter, _primary_row(adapter), cache_problem))
            return []
        version, problem = _read_version(adapter, profile, process, env)
        if problem in {"missing", "timeout"}:
            degraded.append(_degraded(adapter, _primary_row(adapter), problem))
            return []
        off_pin = problem in {"version-mismatch", "version-unreadable"}
        if off_pin:
            degraded.append(_degraded(adapter, _primary_row(adapter), str(problem)))
        if adapter.mutation and time.monotonic() >= deadline:
            degraded.append(_degraded(adapter, "testing.surviving-mutant", "cap"))
            return []
        timeout = adapter.timeout_seconds
        if adapter.mutation:
            timeout = max(1, min(timeout, int(deadline - time.monotonic())))
        ran = version or adapter.default_version
        context = ScanContext(
            head_root,
            head_root,
            home,
            configs,
            base=base_sha,
            test_command=_python_test_command(profile),
            commands=_scan_commands(profile),
        )
        comparison = "base-head" if adapter.type_checker else adapter.comparison
        if comparison == "base-head":
            hits, digests = _base_and_head(
                adapter, repo, base_sha, head_sha, head_root, context, process, env, timeout,
                ran, degraded, _rules_digest(rules), items,
            )
        else:
            hits, digests = _once(
                adapter, context, process, env, timeout, "head", degraded, items
            )
        if not hits and not digests:
            return []
        digest = digests.get("head") or digests.get("base") or store_raw(b"", home)
        kept: list[Hit] = []
        for hit in hits:
            hit = replace(hit, path=_display_path(hit.path))
            if adapter.type_checker:
                hit = replace(hit, whole_project=True)
            elif comparison != "base-head" and not filter_to_change((hit,), change):
                continue
            try:
                row = _row_for(adapter, hit)
            except review_formula.FormulaError as exc:
                raise RunnerFailure(2, str(exc)) from exc
            _require_pattern_row(adapter, row)
            kept.append(replace(
                hit,
                row=row,
                tool=adapter.tool or adapter.id,
                version=ran,
                degraded=hit.degraded or off_pin,
                raw_output=digest,
                language=hit.language or language_for(hit.path),
            ))
        return kept


def _once(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
    label: str,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
) -> tuple[tuple[Hit, ...], dict[str, str]]:
    try:
        result, problem, ran = _capture(adapter, context, process, env, timeout)
    except ToolGap as exc:
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    if not ran:
        return (), {}
    if problem is not None:
        degraded.append(_degraded(adapter, _primary_row(adapter), problem))
        return (), {}
    assert result is not None
    try:
        parsed, failure = _parsed(adapter, result, label)
    except ToolGap as exc:
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    if parsed is not None:
        _note_problems(adapter, parsed, degraded)
    if failure is not None:
        degraded.append(_degraded(adapter, _primary_row(adapter), failure))
        return (), {}
    assert parsed is not None
    if parsed.unfinished:
        degraded.append(_degraded(adapter, "testing.surviving-mutant", "cap"))
        parsed = ParseResult(
            tuple(replace(hit, degraded=True) for hit in parsed.hits),
            unfinished=True,
            problems=parsed.problems,
            items=parsed.items,
            gaps=parsed.gaps,
        )
    _absorb(adapter, parsed, label, degraded, items)
    digest = store_raw((result.stdout or "").encode(), context.home)
    return parsed.hits, {label: digest}


def _base_and_head(
    adapter: Adapter,
    repo: Path,
    base_sha: str,
    head_sha: str,
    head_root: Path,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
    version: str,
    degraded: list[dict[str, str]],
    rules_digest: str,
    items: list[Mapping[str, Any]],
) -> tuple[tuple[Hit, ...], dict[str, str]]:
    settings = _settings_digest(adapter, rules_digest)
    key = {"base": base_sha, "adapter": adapter.id, "version": version, "settings": settings}
    cached = _read_base_cache(context.home, adapter, version, base_sha, settings, key)
    if cached is None:
        try:
            with _worktree(repo, base_sha) as base_root:
                _link_env(adapter, repo, base_root, base_sha, head_sha)
                base_hits, _base_digest, base_problem = _scan_root(
                    adapter, replace(context, repo=base_root, root=base_root), process, env,
                    timeout, "base", degraded, items,
                )
        except ToolGap:
            # The base tree declined. Head is still compared against no earlier findings.
            base_hits = ()
            base_problem = None
        if base_problem == "empty-output":
            degraded.append(_degraded(adapter, _primary_row(adapter), base_problem))
            base_hits = ()
        elif base_problem is not None:
            degraded.append(_degraded(adapter, _primary_row(adapter), base_problem))
            return (), {}
        else:
            _write_base_cache(
                context.home, adapter, version, base_sha, settings, key, base_hits
            )
    else:
        base_hits = cached
    try:
        head_hits, head_digest, head_problem = _scan_root(
            adapter, replace(context, repo=head_root, root=head_root), process, env, timeout,
            "head", degraded, items,
        )
    except ToolGap as exc:
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    if head_problem is not None:
        degraded.append(_degraded(adapter, _primary_row(adapter), head_problem))
        return (), {}
    base_ids = {_identity(adapter, hit) for hit in base_hits}
    kept = tuple(hit for hit in head_hits if _identity(adapter, hit) not in base_ids)
    return kept, {"head": head_digest}


def _scan_root(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
    label: str,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
) -> tuple[tuple[Hit, ...], str, str | None]:
    result, problem, ran = _capture(adapter, context, process, env, timeout)
    if not ran:
        return (), "", None
    if problem is not None:
        return (), "", problem
    assert result is not None
    parsed, failure = _parsed(adapter, result, label)
    if parsed is not None:
        _note_problems(adapter, parsed, degraded)
    if failure is not None:
        return (), "", failure
    assert parsed is not None
    digest = store_raw((result.stdout or "").encode(), context.home)
    hits = parsed.hits
    if parsed.unfinished:
        degraded.append(_degraded(adapter, "testing.surviving-mutant", "cap"))
        hits = tuple(replace(hit, degraded=True) for hit in hits)
    _absorb(adapter, parsed, label, degraded, items)
    return hits, digest, None


def _capture(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
) -> tuple[ProcessResult | None, str | None, bool]:
    """Run ``invoke``. jscpd is parsed from a report outside either worktree.

    The third value is false when ``invoke`` returned no argument vector. ``ToolGap`` propagates.
    """
    report_dir: Path | None = None
    scan = context
    if adapter.id == "jscpd":
        report_dir = Path(tempfile.mkdtemp(prefix="saga-jscpd-"))
        scan = replace(context, report_dir=report_dir)
    try:
        argv = adapter.invoke(scan)
        if not argv:
            return None, None, False
        result, problem = _execute(adapter, argv, scan.root, process, env, timeout)
        if adapter.id == "jscpd" and result is not None and problem is None and report_dir is not None:
            report = report_dir / "jscpd-report.json"
            text = report.read_text(encoding="utf-8") if report.is_file() else ""
            result = ProcessResult(result.code, text, result.stderr)
        return result, problem, True
    finally:
        if report_dir is not None:
            shutil.rmtree(report_dir, ignore_errors=True)


def _execute(
    adapter: Adapter,
    argv: list[str] | str,
    cwd: Path,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
) -> tuple[ProcessResult | None, str | None]:
    if isinstance(argv, str) or not isinstance(argv, list):
        raise RunnerFailure(1, f"{adapter.id}: invoke returned a string command")
    run_env: Mapping[str, str] = env
    temps: list[Path] = []
    if adapter.narrow_env:
        run_env, temps = _relocated_env()
    try:
        try:
            result = process(argv, cwd=cwd, env=run_env, timeout=timeout, shell=False)
        except FileNotFoundError:
            return None, "missing"
        except subprocess.TimeoutExpired:
            return None, "timeout"
        return result, None
    finally:
        for path in temps:
            shutil.rmtree(path, ignore_errors=True)


def _parsed(
    adapter: Adapter, result: ProcessResult, label: str
) -> tuple[ParseResult | None, str | None]:
    """Empty success is ``empty-output``. A non-zero run with no hits cannot be compared."""
    text = result.stdout or ""
    if not text.strip():
        if result.code == 0:
            return None, "empty-output"
        if label == "base":
            return None, "base-deps-missing"
        return None, "unparseable"
    try:
        produced = adapter.parse(text)
    except ToolGap:
        raise
    except (ValueError, json.JSONDecodeError):
        if label == "base" and result.code != 0:
            return None, "base-deps-missing"
        return None, "unparseable"
    if result.code != 0 and not produced.hits and not produced.unfinished:
        if label == "base":
            return produced, "base-deps-missing"
        return produced, "unparseable"
    return produced, None


def _read_version(
    adapter: Adapter,
    profile: Mapping[str, Any],
    process: Process,
    env: Mapping[str, str],
) -> tuple[str | None, str | None]:
    pinned = _pinned_version(adapter, profile)
    if not adapter.tool:
        return pinned, None
    probe = Path(tempfile.mkdtemp(prefix="saga-version-"))
    try:
        probe_argv = (
            list(adapter.version_argv)
            if adapter.version_argv
            else [adapter.tool, *adapter.version_args]
        )
        try:
            result = process(
                probe_argv,
                cwd=probe, env=env, timeout=adapter.timeout_seconds, shell=False,
            )
        except FileNotFoundError:
            return None, "missing"
        except subprocess.TimeoutExpired:
            return None, "timeout"
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    found = _VERSION.search(result.stdout or result.stderr or "")
    if found is None:
        return pinned, "version-unreadable"
    if found.group(0) != pinned:
        return found.group(0), "version-mismatch"
    return found.group(0), None


def _saga(home: Path) -> Path:
    """``<home>/.saga``, created mode 0700 when this call creates it."""
    parent = home / ".saga"
    existed = parent.exists()
    parent.mkdir(mode=0o700, exist_ok=True)
    if not existed:
        parent.chmod(0o700)
    return parent


_PATTERN_ROWS = tuple(
    f"correctness.pattern.{name}" for name in review_formula._PATTERN_CHECKS
)
_RELOCATED_ROW = "architecture-maintainability.relocated-run-fails"
_COVERAGE_ROW = "testing.uncovered-branch"
_SECRET_STATEMENT = "A secret scanner reported a match in this file."


def _gap(lens: str, language: str, row: str, tool: str, reason: str) -> dict[str, str]:
    return {"lens": lens, "language": language, "input": row, "tool": tool, "reason": reason}


def _note_problems(
    adapter: Adapter, parsed: ParseResult, degraded: list[dict[str, str]]
) -> None:
    lens = adapter.lens if adapter.lens in review_formula.LENSES else "correctness"
    for problem in parsed.problems:
        degraded.append({
            "lens": lens,
            "language": "none",
            "input": problem,
            "tool": adapter.tool or adapter.id,
            "reason": "semgrep-error",
        })


def _absorb(
    adapter: Adapter,
    parsed: ParseResult,
    label: str,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
) -> None:
    """Record gaps without dropping hits. Where-to-look items come from the head scan only."""
    for reason, row in parsed.gaps:
        degraded.append(_degraded(adapter, row, reason))
    if label == "head":
        items.extend(parsed.items)


def _degraded(adapter: Adapter, row: str, reason: str) -> dict[str, str]:
    lens = row.split(".", 1)[0]
    if lens not in review_formula.LENSES:
        lens = adapter.lens if adapter.lens in review_formula.LENSES else "correctness"
    language = "none"
    if len(adapter.languages) == 1 and adapter.languages[0] in review_formula.LANGUAGES:
        language = adapter.languages[0]
    return _gap(lens, language, row, adapter.tool or adapter.id, reason)


def _primary_row(adapter: Adapter) -> str:
    if adapter.rows:
        return adapter.rows[0]
    return f"{adapter.lens}.tool-unscoped"


def _present(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return path.stat().st_size > 0
    return any(item.is_file() for item in path.rglob("*"))


def _rules_digest(rules: Sequence[RulePin]) -> str:
    payload = [
        {"pack": rule.pack, "path": rule.path, "sha256": rule.sha256} for rule in rules
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _python_test_command(profile: Mapping[str, Any]) -> str:
    """The Python test command from the base profile, or the functional command."""
    languages = profile.get("languages") or {}
    python = languages.get("python") if isinstance(languages, Mapping) else None
    if isinstance(python, Mapping):
        command = python.get("test_command")
        if isinstance(command, str) and command.strip():
            return command
    command = profile.get("test_command")
    if isinstance(command, str) and command.strip():
        return command
    return ""


def _pinned_version(adapter: Adapter, profile: Mapping[str, Any]) -> str:
    pin = (profile.get("pins") or {}).get(adapter.tool) or {}
    version = pin.get("version") if isinstance(pin, Mapping) else None
    if isinstance(version, str) and version:
        return version
    return adapter.default_version


def _rules_for(adapter: Adapter, profile: Mapping[str, Any]) -> tuple[RulePin, ...]:
    """A profile rules list replaces the yaml rules. A version-only pin keeps them."""
    pin = (profile.get("pins") or {}).get(adapter.tool) or {}
    rules = pin.get("rules") if isinstance(pin, Mapping) else None
    if rules is None:
        return adapter.rules
    return tuple(
        RulePin(
            pack=item.get("pack") if isinstance(item, Mapping) else None,
            sha256=item.get("sha256") if isinstance(item, Mapping) else None,
            path=item.get("path") if isinstance(item, Mapping) else None,
        )
        for item in rules
    )


@contextmanager
def _rule_config(
    adapter: Adapter, rules: Sequence[RulePin], repo: Path, home: Path, base_sha: str
) -> Iterator[tuple[tuple[Path, ...], str | None]]:
    """Local pack directories only. A missing cache is not a download.

    A relative rule path other than saga's rules is a directory inside a base
    worktree. That worktree stays open until the caller finishes its scans.
    """
    if not rules:
        yield (), None
        return
    needs_base = any(
        rule.path and not Path(rule.path).is_absolute() and not _is_saga_rules(rule.path)
        for rule in rules
    )
    if not needs_base:
        yield _rule_paths(adapter, rules, home, None)
        return
    with _worktree(repo, base_sha) as base_root:
        yield _rule_paths(adapter, rules, home, base_root)


def _rule_paths(
    adapter: Adapter,
    rules: Sequence[RulePin],
    home: Path,
    base_root: Path | None,
) -> tuple[tuple[Path, ...], str | None]:
    paths: list[Path] = []
    for rule in rules:
        if rule.pack:
            cache = semgrep_cache(home, rule.pack)
            digest = digest_tree(cache) if cache.is_dir() else ""
            if not digest or digest != (rule.sha256 or ""):
                return (), "rule-cache-missing"
            paths.append(cache)
            continue
        if rule.path:
            directory = _rule_directory(rule.path, base_root)
            if not _present(directory):
                return (), "known-gap"
            paths.append(directory)
            continue
        raise RunnerFailure(2, f"{adapter.id}: a rule needs a pack or a path")
    return tuple(paths), None


def _is_saga_rules(path: str) -> bool:
    return path.replace("\\", "/") == _SAGA_RULES


def _rule_directory(path: str, base_root: Path | None) -> Path:
    if _is_saga_rules(path):
        return plugin_root() / "references" / "semgrep-rules"
    directory = Path(path)
    if directory.is_absolute():
        return directory
    if base_root is None:
        raise RunnerFailure(2, "a relative rule path needs the base commit")
    return base_root / path


def _gap_target(adapter: Adapter, head_root: Path) -> Path:
    if adapter.gap_path == _SAGA_RULES:
        return plugin_root() / "references" / "semgrep-rules"
    if adapter.gap_path is None:
        raise RunnerFailure(1, f"{adapter.id}: gap_path is missing")
    return head_root / adapter.gap_path


def _row_for(adapter: Adapter, hit: Hit) -> str:
    if hit.row:
        return hit.row
    table = {key: value for key, value in adapter.level_map}
    if hit.level in table:
        return table[str(hit.level)]
    upper = {key.upper(): value for key, value in table.items()}
    if hit.level and hit.level.upper() in upper:
        return upper[hit.level.upper()]
    level = (hit.level or "").lower()
    if level in {"", "none"}:
        mapped: str | None = None
    elif level == "information":
        mapped = "info"
    else:
        mapped = level
    return review_formula.tool_row(adapter.lens, mapped, hit.rule_id, adapter.curated_rules)


def _require_pattern_row(adapter: Adapter, row: str) -> None:
    if adapter.id == "semgrep-saga" and row not in _PATTERN_ROWS:
        raise RunnerFailure(2, f"semgrep-saga metadata.row {row!r} is not a pattern row")


def _identity(adapter: Adapter, hit: Hit) -> str:
    """The same identity ``review_records`` stores, resolved before base and head are compared."""
    try:
        row = hit.row or _row_for(adapter, hit)
    except review_formula.FormulaError as exc:
        raise RunnerFailure(2, str(exc)) from exc
    lens = row.split(".", 1)[0]
    rule = {"row": row, "ref": hit.rule_id}
    location = {
        "file": _display_path(hit.path),
        "function": hit.function,
        "anchor": hit.anchor or hit.rule_id,
    }
    return review_records.finding_identity(lens, rule, location)


def _load_profile(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RunnerFailure(2, f"{path}: {exc}") from exc
    return _load_profile_text(text, str(path))


def _load_profile_text(text: str, label: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RunnerFailure(2, f"{label}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunnerFailure(2, f"{label}: profile must be an object")
    test_command = _functional_command(data)
    block = data.get("review_tools")
    if block is None:
        return {
            "languages": {},
            "languages_present": False,
            "pins": {},
            "test_command": test_command,
        }
    if not isinstance(block, dict):
        raise RunnerFailure(2, "review_tools must be an object")
    return {
        "languages": _languages(block.get("languages")),
        "languages_present": "languages" in block,
        "pins": _pins(block.get("pins")),
        "test_command": test_command,
    }


def _profile_for_run(
    repo: Path, base_sha: str, head_sha: str, profile_path: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Pins and the test command come from the base blob. Head edits are recorded."""
    notes: list[dict[str, str]] = []
    base_text = _show_text(repo, base_sha, ".saga-profile.json")
    if base_text is None:
        profile = _absent_profile() if _inside_repo(repo, profile_path) else _load_profile(profile_path)
    else:
        profile = _load_profile_text(base_text, f"{base_sha}:.saga-profile.json")
    head_text = _show_text(repo, head_sha, ".saga-profile.json")
    if head_text is None:
        if base_text is not None and _configuring(profile) != _configuring(_absent_profile()):
            notes.append(_profile_change())
        return profile, notes
    try:
        head_profile = _load_profile_text(head_text, f"{head_sha}:.saga-profile.json")
    except RunnerFailure:
        notes.append(_profile_change())
        return profile, notes
    if _configuring(head_profile) != _configuring(profile):
        notes.append(_profile_change())
    return profile, notes


def _absent_profile() -> dict[str, Any]:
    return _load_profile_text("{}", "absent")


def _configuring(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pins": profile.get("pins") or {},
        "languages": profile.get("languages") or {},
        "test_command": profile.get("test_command"),
    }


def _profile_change() -> dict[str, str]:
    return {
        "lens": "security",
        "language": "none",
        "input": "head-profile",
        "tool": "review-tools",
        "reason": "head-profile-change",
    }


def _inside_repo(repo: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    return True


def _show_text(repo: Path, revision: str, path: str) -> str | None:
    result = _git(repo, ["show", f"{revision}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout


def _require_sha(repo: Path, revision: str) -> str:
    sha = _rev(repo, revision)
    if not sha:
        raise RunnerFailure(2, f"{revision}: not a commit")
    return sha


def _functional_command(data: Mapping[str, Any]) -> str | None:
    environment = data.get("functional_test_environment")
    if environment is None:
        return None
    if not isinstance(environment, dict):
        raise RunnerFailure(2, "functional_test_environment must be an object")
    command = environment.get("test_command")
    if command is None:
        return None
    if not isinstance(command, str):
        raise RunnerFailure(2, "functional_test_environment.test_command must be a string")
    return command


def _languages(value: Any) -> dict[str, dict[str, str | None]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RunnerFailure(2, "review_tools.languages must be an object")
    cleaned: dict[str, dict[str, str | None]] = {}
    for name, spec in value.items():
        if name not in review_formula.LANGUAGES:
            raise RunnerFailure(2, f"language {name!r} is not a formula language")
        if not isinstance(spec, dict):
            raise RunnerFailure(2, f"review_tools.languages.{name} must be an object")
        command = spec.get("test_command")
        report = spec.get("coverage_report")
        if command is not None and not isinstance(command, str):
            raise RunnerFailure(2, f"review_tools.languages.{name}.test_command must be a string")
        if report is not None and not isinstance(report, str):
            raise RunnerFailure(
                2, f"review_tools.languages.{name}.coverage_report must be a string"
            )
        cleaned[str(name)] = {"test_command": command, "coverage_report": report}
    return cleaned


def _pins(value: Any) -> dict[str, dict[str, Any]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RunnerFailure(2, "review_tools.pins must be an object")
    known = {str(row.get("tool")) for row in load_tool_list() if row.get("tool")}
    cleaned: dict[str, dict[str, Any]] = {}
    for tool, spec in value.items():
        if tool not in known:
            raise RunnerFailure(2, f"unknown tool {tool!r}")
        if not isinstance(spec, dict):
            raise RunnerFailure(2, f"pin {tool} must be an object")
        version = spec.get("version")
        if version is not None and not isinstance(version, str):
            raise RunnerFailure(2, f"pin {tool}.version must be a string")
        cleaned[str(tool)] = {"version": version, "rules": _pin_rules(str(tool), spec.get("rules"))}
    return cleaned


def _pin_rules(tool: str, rules: Any) -> list[dict[str, Any]] | None:
    if rules is None:
        return None
    if not isinstance(rules, list):
        raise RunnerFailure(2, f"pin {tool}.rules must be a list")
    cleaned = []
    for entry in rules:
        if not isinstance(entry, dict) or ("pack" not in entry and "path" not in entry):
            raise RunnerFailure(2, f"pin {tool}.rules entry needs pack or path")
        sha = entry.get("sha256")
        if "pack" in entry and (not isinstance(sha, str) or not _SHA.match(sha)):
            raise RunnerFailure(2, f"pin {tool}.sha256 must be 64 hex characters")
        if sha is not None and (not isinstance(sha, str) or not _SHA.match(sha)):
            raise RunnerFailure(2, f"pin {tool}.sha256 must be 64 hex characters")
        cleaned.append({"pack": entry.get("pack"), "path": entry.get("path"), "sha256": sha})
    return cleaned


def _load_builder(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunnerFailure(2, f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RunnerFailure(2, f"{path}: builder record must be an object")
    return data


def _strip_settings(root: Path) -> list[dict[str, str]]:
    """Unlink scanner settings in the head worktree. Record each path once."""
    found: list[str] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            if name not in _SETTINGS_NAMES:
                continue
            path = Path(directory) / name
            found.append(path.relative_to(root).as_posix())
            path.unlink()
    notes = []
    for relative in sorted(set(found)):
        notes.append({
            "lens": "security",
            "language": "none",
            "input": relative,
            "tool": "review-tools",
            "reason": "scanner-settings",
        })
    return notes


def _allow_comments(head_root: Path, change: review_diff.Change) -> list[dict[str, str]]:
    """One record per changed file and silence marker on its new lines.

    The file is read in the head worktree and is not rewritten. A symlink is not followed.
    """
    notes: list[dict[str, str]] = []
    for item in change.files:
        if item.status not in {"added", "modified", "renamed"} or not item.lines:
            continue
        path = head_root / item.path
        if path.is_symlink() or not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        changed = [
            lines[number - 1] for number in item.lines if 1 <= number <= len(lines)
        ]
        language = language_for(item.path)
        if language not in review_formula.LANGUAGES:
            language = "none"
        for needle, lens, tool, reason in _COMMENT_MARKERS:
            if any(needle in line for line in changed):
                notes.append({
                    "lens": lens,
                    "language": language,
                    "input": item.path,
                    "tool": tool,
                    "reason": reason,
                })
    return notes


def _settings_digest(adapter: Adapter, rules_digest: str) -> str:
    """SHA-256 of the settings that change what a base scan would report."""
    if adapter.id.startswith("semgrep") or adapter.tool == "semgrep":
        flags: list[str] = ["--disable-nosem"]
    elif adapter.id == "gitleaks" or adapter.tool == "gitleaks":
        config = plugin_root() / "references" / "gitleaks.toml"
        file_digest = hashlib.sha256(config.read_bytes()).hexdigest() if config.is_file() else ""
        flags = ["--ignore-gitleaks-allow", file_digest]
    else:
        flags = []
    payload = {
        "adapter": adapter.id,
        "rules": rules_digest,
        "flags": flags,
        "filenames": sorted(_SETTINGS_NAMES),
        "thresholds": _row_thresholds(adapter.id),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _row_thresholds(adapter_id: str) -> dict[str, int]:
    for row in load_tool_list():
        if str(row.get("id") or "") != adapter_id:
            continue
        raw = row.get("thresholds")
        if not isinstance(raw, dict):
            return {}
        numbers: dict[str, int] = {}
        for key, value in raw.items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            numbers[str(key)] = value
        return numbers
    return {}


def _relocated(
    head_root: Path,
    profile: Mapping[str, Any],
    process: Process,
    home: Path,
    degraded: list[dict[str, str]],
) -> tuple[list[Hit], list[tuple[str, Path]]]:
    commands = _relocated_commands(profile)
    if not commands:
        degraded.append(_gap(
            "architecture-maintainability", "none", _RELOCATED_ROW, "relocated-test", "known-gap"
        ))
        return [], []
    hits: list[Hit] = []
    directories: list[tuple[str, Path]] = []
    try:
        for language, command in commands:
            work = Path(tempfile.mkdtemp(prefix="saga-relocated-"))
            directories.append((language, work))
            hit = _one_relocated(head_root, language, command, process, work, home, degraded)
            if hit is not None:
                hits.append(hit)
    except Exception:
        # A later command can refuse after earlier directories exist.
        for _language, path in directories:
            shutil.rmtree(path, ignore_errors=True)
        raise
    return hits, directories


def _scan_commands(profile: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """Language commands, plus the functional command when it is not already listed.

    The pairs come from the profile object the runner already loaded. That profile is the base
    commit's, or the external ``--profile`` when the base commit has no profile blob.
    """
    pairs = list(_relocated_commands(profile))
    functional = profile.get("test_command")
    if isinstance(functional, str) and functional.strip():
        if not any(command == functional for _language, command in pairs):
            pairs.append(("none", functional))
    return tuple(pairs)


def _relocated_commands(profile: Mapping[str, Any]) -> list[tuple[str, str]]:
    if profile.get("languages_present"):
        commands = []
        for language, spec in (profile.get("languages") or {}).items():
            command = spec.get("test_command") if isinstance(spec, Mapping) else None
            if isinstance(command, str) and command.strip():
                commands.append((str(language), command))
        return commands
    command = profile.get("test_command")
    if isinstance(command, str) and command.strip():
        return [("none", command)]
    return []


def _relocated_env() -> tuple[dict[str, str], list[Path]]:
    """Allow-listed names only. ``HOME`` and the temp directory are fresh and removed by the caller."""
    env: dict[str, str] = {}
    names = _ENV_COPIED + (_ENV_WINDOWS if sys.platform == "win32" else ())
    for name in names:
        if name in os.environ:
            env[name] = os.environ[name]
    home_dir = Path(tempfile.mkdtemp(prefix="saga-home-"))
    tmp_dir = Path(tempfile.mkdtemp(prefix="saga-tmp-"))
    env["HOME"] = str(home_dir)
    env["TMPDIR"] = str(tmp_dir)
    env["TMP"] = str(tmp_dir)
    env["TEMP"] = str(tmp_dir)
    return env, [home_dir, tmp_dir]


def _one_relocated(
    head_root: Path,
    language: str,
    command: str,
    process: Process,
    work: Path,
    home: Path,
    degraded: list[dict[str, str]],
) -> Hit | None:
    argv = _rewrite_command(head_root, command)
    env, temps = _relocated_env()
    try:
        try:
            result = process(argv, cwd=work, env=env, timeout=120, shell=False)
        except FileNotFoundError:
            degraded.append(_gap(
                "architecture-maintainability", language, _RELOCATED_ROW,
                "relocated-test", "missing",
            ))
            return None
        except subprocess.TimeoutExpired:
            degraded.append(_gap(
                "architecture-maintainability", language, _RELOCATED_ROW,
                "relocated-test", "timeout",
            ))
            return None
    finally:
        for path in temps:
            shutil.rmtree(path, ignore_errors=True)
    if result.code == 0:
        return None
    return Hit(
        rule_id=command,
        path=".",
        statement="The relocated test command failed.",
        anchor=command,
        whole_project=True,
        row=_RELOCATED_ROW,
        language=language,
        raw_output=store_raw((result.stdout or "").encode(), home),
        tool="relocated-test",
        version="not-recorded",
    )


def _rewrite_command(head_root: Path, command: str) -> list[str]:
    """Rewrite tokens that exist in the head worktree. Flags and absolute paths stay."""
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise RunnerFailure(2, f"relocated command: {exc}") from exc
    argv: list[str] = []
    for token in tokens:
        if token.startswith("-") or token.startswith("/"):
            argv.append(token)
            continue
        candidate = head_root / token
        if candidate.exists():
            argv.append(str(candidate.resolve()))
            continue
        argv.append(token)
    return argv


def _coverage(
    change: review_diff.Change,
    profile: Mapping[str, Any],
    home: Path,
    degraded: list[dict[str, str]],
    pairs: Sequence[tuple[str, Path]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = _report_paths(pairs, profile)
    if not paths:
        degraded.append(_gap(
            "testing", _one_language(profile), _COVERAGE_ROW, "coverage", "no-report",
        ))
        return [], []
    parsed: list[tuple[bytes, coverage_lines.CoverageNumbers]] = []
    for path in paths:
        try:
            report = coverage_lines.parse_report(path)
            parsed.append((path.read_bytes(), coverage_lines.uncovered_changed(report, change)))
        except (OSError, ValueError, SyntaxError, json.JSONDecodeError) as exc:
            raise RunnerFailure(2, f"{path}: {exc}") from exc
    uncovered = {item.uncovered for _, item in parsed}
    if len(uncovered) > 1:
        raise RunnerFailure(2, "coverage reports disagree on the uncovered set")
    language = _coverage_language(profile, parsed[0][1])
    findings, measurement, extra = records_for_coverage(
        parsed[0][1], parsed[0][0], home, language=language
    )
    degraded.extend(extra)
    return findings, [measurement]


def _report_paths(
    pairs: Sequence[tuple[str, Path]], profile: Mapping[str, Any]
) -> list[Path]:
    """Reports from the relocated directories only. A path outside one of them is a refusal."""
    languages = profile.get("languages") or {}
    configured = False
    named: list[Path] = []
    for language, directory in pairs:
        spec = languages.get(language) if isinstance(languages, Mapping) else None
        report = spec.get("coverage_report") if isinstance(spec, Mapping) else None
        if not isinstance(report, str) or not report:
            continue
        configured = True
        try:
            candidate = coverage_lines.resolve_report(report, directory)
        except ValueError as exc:
            raise RunnerFailure(2, str(exc)) from exc
        if candidate.is_file():
            named.append(candidate)
    if configured:
        return named
    found: list[Path] = []
    for _language, directory in pairs:
        for name in _REPORT_NAMES:
            try:
                candidate = coverage_lines.resolve_report(name, directory)
            except ValueError as exc:
                raise RunnerFailure(2, str(exc)) from exc
            if candidate.is_file():
                found.append(candidate)
    return found


def _one_language(profile: Mapping[str, Any]) -> str:
    names = [name for name in (profile.get("languages") or {}) if name in review_formula.LANGUAGES]
    if len(names) == 1:
        return names[0]
    return "none"


def _coverage_language(profile: Mapping[str, Any], numbers: coverage_lines.CoverageNumbers) -> str:
    languages = {language_for(path) for path, _line in numbers.uncovered}
    languages.discard("none")
    if len(languages) == 1:
        return next(iter(languages))
    return _one_language(profile)


def records_for_coverage(
    numbers: coverage_lines.CoverageNumbers,
    report: bytes,
    home: Path,
    *,
    language: str,
    version: str = "not-recorded",
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    """Findings and one measurement. Line fallback is degraded, so it cannot block."""
    digest = store_raw(report, home)
    extra: list[dict[str, str]] = []
    if numbers.degraded:
        extra.append(_gap("testing", language, _COVERAGE_ROW, "coverage", "no-branch-data"))
    findings = []
    if numbers.total:
        for path, line in sorted(numbers.uncovered):
            findings.append(
                _coverage_finding(path, line, digest, language, version, numbers.degraded)
            )
    value = 1.0 if numbers.total == 0 else numbers.covered / numbers.total
    measurement = {
        "kind": "measurement",
        "schema": SCHEMA,
        "lens": "testing",
        "row": _COVERAGE_ROW,
        "tool": {"name": "coverage", "version": version},
        "language": language,
        "metric": "changed-line branch coverage",
        "value": value,
        "threshold": 1.0,
        "direction": "at-least",
    }
    return findings, measurement, extra


def _coverage_finding(
    path: str, line: int, digest: str, language: str, version: str, degraded: bool
) -> dict[str, Any]:
    file_language = language_for(path)
    if file_language == "none":
        file_language = language
    location = {
        "scope": "lines",
        "file": path,
        "lines": {"start": line, "end": line},
        "function": None,
        "anchor": f"{path}:{line}",
    }
    rule = {"row": _COVERAGE_ROW, "ref": f"{path}:{line}"}
    return {
        "kind": "finding",
        "schema": SCHEMA,
        "id": review_records.finding_identity("testing", rule, location),
        "subject": "code",
        "lens": "testing",
        "rule": rule,
        "source": {"kind": "tool", "name": "coverage", "version": version},
        "location": location,
        "language": file_language,
        "statement": f"Line {line} of {path} is not covered.",
        "consequence": None,
        "trigger": None,
        "evidence": "tool-result",
        "proof": {"raw_output": digest},
        "introduced": True,
        "degraded": degraded,
        "consequence_jev": None,
        "unconfirmed": False,
        "merge_outcome": None,
    }


def _findings_from(hits: Sequence[Hit]) -> list[dict[str, Any]]:
    plain = [hit for hit in hits if not hit.advisory_ids]
    advisory = [hit for hit in hits if hit.advisory_ids]
    findings = [_finding_from_hit(hit) for hit in plain]
    payloads = [
        {
            "advisory_ids": list(hit.advisory_ids),
            "tool": hit.tool,
            "score": hit.score,
            "row": hit.row,
            "hit": hit,
        }
        for hit in advisory
    ]
    for item in review_formula.merge_advisories(payloads):
        hit = item["hit"]
        canonical = str(item.get("canonical_id") or hit.rule_id)
        findings.append(_finding_from_hit(replace(
            hit, rule_id=canonical, anchor=canonical, row=str(item.get("row") or hit.row)
        )))
    return findings


def _finding_from_hit(hit: Hit) -> dict[str, Any]:
    row = hit.row or f"{hit.tool or 'tool'}.tool-unscoped"
    lens = row.split(".", 1)[0]
    ref = hit.rule_id or row
    anchor = hit.anchor or ref
    statement = hit.statement
    if row == review_records.SECRET_ROW:
        statement = _SECRET_STATEMENT
        anchor = f"{hit.rule_id} {hit.path}".strip()
    statement = " ".join((statement or f"{hit.tool} reported {ref}.").split())
    path = _display_path(hit.path) or "."
    if hit.whole_project or hit.start is None:
        location: dict[str, Any] = {"scope": "whole-project", "file": path, "anchor": anchor}
    else:
        location = {
            "scope": "lines",
            "file": path,
            "lines": {"start": hit.start, "end": hit.end or hit.start},
            "function": hit.function,
            "anchor": anchor,
        }
    rule = {"row": row, "ref": ref}
    return {
        "kind": "finding",
        "schema": SCHEMA,
        "id": review_records.finding_identity(lens, rule, location),
        "subject": "code",
        "lens": lens,
        "rule": rule,
        "source": {
            "kind": "tool",
            "name": hit.tool or "tool",
            "version": hit.version or "not-recorded",
        },
        "location": location,
        "language": hit.language or language_for(path),
        "statement": statement,
        "consequence": None,
        "trigger": None,
        "evidence": "tool-result",
        "proof": {"raw_output": hit.raw_output},
        "introduced": True,
        "degraded": bool(hit.degraded),
        "consequence_jev": None,
        "unconfirmed": False,
        "merge_outcome": None,
    }


def _emit(
    output: Path,
    findings: Sequence[Mapping[str, Any]],
    measurements: Sequence[Mapping[str, Any]],
    degraded: Sequence[Mapping[str, str]],
    builder: Mapping[str, Any] | None,
    items: Sequence[Mapping[str, Any]] = (),
) -> None:
    for record in (*findings, *measurements):
        problems = review_records.validate(record)
        if problems:
            raise RunnerFailure(2, "; ".join(problems))
    if builder is not None:
        problems = review_records.validate(builder)
        if problems:
            raise RunnerFailure(2, "; ".join(problems))
    try:
        outcomes = review_formula.compute({
            "findings": list(findings),
            "measurements": list(measurements),
            "builder_records": [builder] if builder else [],
            "degraded_inputs": list(degraded),
        })
    except review_formula.FormulaError as exc:
        raise RunnerFailure(2, str(exc)) from exc
    _write_json(output / "findings.json", list(findings))
    _write_json(output / "measurements.json", list(measurements))
    _write_json(output / "degraded.json", list(degraded))
    _write_json(output / "outcomes.json", outcomes)
    _write_json(output / "where-to-look.json", list(items))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@contextmanager
def _worktree(repo: Path, revision: str) -> Iterator[Path]:
    """Check out ``revision`` without running its hooks or Git LFS smudge filters.

    ``core.hooksPath`` can point at a directory the commit itself tracks. An empty directory,
    set only for this git process, is not that path.
    """
    path = Path(tempfile.mkdtemp(prefix="saga-review-"))
    hooks = Path(tempfile.mkdtemp(prefix="saga-hooks-"))
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        added = _git(
            repo,
            ["-c", f"core.hooksPath={hooks}", "worktree", "add", "--detach", str(path), revision],
            env,
        )
        if added.returncode != 0:
            shutil.rmtree(path, ignore_errors=True)
            detail = (added.stderr or added.stdout or "git worktree add failed").strip()
            raise RunnerFailure(2, detail)
        try:
            yield path
        finally:
            _git(repo, ["worktree", "remove", "--force", str(path)])
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
    finally:
        shutil.rmtree(hooks, ignore_errors=True)


def _git(
    repo: Path, args: list[str], env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=None if env is None else dict(env),
    )


def _link_env(adapter: Adapter, repo: Path, base_root: Path, base: str, head: str) -> None:
    """Symlink dependency directories only when this checkout is the requested head."""
    if not adapter.env_dirs:
        return
    if _rev(repo, "HEAD") != _rev(repo, head):
        return
    for lock in adapter.lockfiles:
        base_blob = _blob(repo, base, lock)
        if not base_blob or base_blob != _blob(repo, head, lock):
            return
    for name in adapter.env_dirs:
        source = repo / name
        dest = base_root / name
        if source.exists() and not dest.exists():
            dest.symlink_to(source, target_is_directory=source.is_dir())


def _rev(repo: Path, revision: str) -> str:
    result = _git(repo, ["rev-parse", revision])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _blob(repo: Path, revision: str, path: str) -> str | None:
    result = _git(repo, ["rev-parse", f"{revision}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _cache_path(home: Path, adapter: Adapter, version: str, base_sha: str, settings: str) -> Path:
    return _saga(home) / "review-cache" / adapter.id / version / base_sha / f"{settings}.json"


def _write_base_cache(
    home: Path,
    adapter: Adapter,
    version: str,
    base_sha: str,
    settings: str,
    key: Mapping[str, str],
    hits: Sequence[Hit],
) -> None:
    target = _cache_path(home, adapter, version, base_sha, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {"key": dict(key), "hits": [asdict(hit) for hit in hits]}
    target.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    target.chmod(0o600)


def _read_base_cache(
    home: Path,
    adapter: Adapter,
    version: str,
    base_sha: str,
    settings: str,
    key: Mapping[str, str],
) -> tuple[Hit, ...] | None:
    """A miss leaves the file in place. A list in the old shape is a miss."""
    target = _cache_path(home, adapter, version, base_sha, settings)
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("key") != dict(key):
        return None
    items = raw.get("hits")
    if not isinstance(items, list):
        return None
    hits: list[Hit] = []
    for item in items:
        if not isinstance(item, dict):
            return None
        payload = dict(item)
        payload["advisory_ids"] = tuple(payload.get("advisory_ids") or ())
        try:
            hits.append(Hit(**payload))
        except TypeError:
            return None
    return tuple(hits)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_tools.py",
        description=(
            "Run the pinned review tools and write findings for what a change introduces. "
            "The command takes a repository, two commits, a profile and an output directory. "
            "It does not take a run record."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser(
        "run", help="Write the record files, including where-to-look items."
    )
    run_parser.add_argument("--repo", required=True, type=Path)
    run_parser.add_argument("--base", required=True)
    run_parser.add_argument("--head", required=True)
    run_parser.add_argument("--profile", required=True, type=Path)
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument("--home", type=Path)
    run_parser.add_argument("--builder", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(
            args.repo, args.base, args.head, args.profile, args.output,
            home=args.home, builder=args.builder,
        )
    except Exception as exc:
        print(f"review tools: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
