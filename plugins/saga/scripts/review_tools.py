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
import signal
import stat
import subprocess  # nosec B404
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

import yaml

import coverage_lines
import review_diff
import review_diagnostics
import review_formula
import review_records

# Adapters import ``review_tools`` to raise ToolGap. Keep that name bound to
# this module during direct execution so their exceptions match our handler.
if __name__ == "__main__":
    sys.modules["review_tools"] = sys.modules[__name__]

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
    "plugins/saga/scripts/review_adapters_typescript.py",
    "plugins/saga/scripts/review_adapters_dart.py",
    "plugins/saga/scripts/review_adapters_rust.py",
    "plugins/saga/scripts/review_adapters_swift.py",
)
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_BARE_VERSION = re.compile(r"\d+")
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
_SAGA_RULES = "plugins/saga/references/semgrep"
#: The shared-update rule this card's render prepares: its file, its C1 row, the
#: degraded reason without a usable key, and the pattern that matches nothing.
_SHARED_UPDATE_FILE = "write-skips-shared-update-path.yaml"
_SHARED_UPDATE_ROW = "correctness.pattern.write-skips-shared-update"
_SHARED_UPDATE_REASON = "missing-shared-update-paths"
_SHARED_UPDATE_NEVER = "(?!)"
_SHARED_UPDATE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
#: Tool configs the C4c adapters strip (issue 153). Stripped in both scan trees;
#: the base copy is staged over the stripped name where one exists (KTD4).
_C4C_SETTINGS_NAMES = (
    "eslint.config.js",
    "eslint.config.mjs",
    "eslint.config.cjs",
    "eslint.config.ts",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".eslintrc.json",
    ".eslintrc.yml",
    ".eslintrc.yaml",
    "tsconfig.json",
    "analysis_options.yaml",
    "clippy.toml",
    ".clippy.toml",
    "rust-toolchain.toml",
    "rust-toolchain",
    "deny.toml",
    ".npmrc",
    "stryker.conf.json",
    "stryker.conf.js",
    "stryker.conf.mjs",
    "stryker.conf.cjs",
    "vitest.config.ts",
    "vitest.config.js",
    "vitest.config.mjs",
    "vitest.config.cjs",
    "vitest.config.mts",
    "vitest.config.cts",
    "vite.config.ts",
    "vite.config.js",
    "vite.config.mjs",
    "vite.config.cjs",
    "vite.config.mts",
    "vite.config.cts",
    "jest.config.ts",
    "jest.config.js",
    "jest.config.mjs",
    "jest.config.cjs",
    "jest.config.json",
    "babel.config.js",
    "babel.config.cjs",
    "babel.config.mjs",
    "babel.config.json",
    ".babelrc",
    ".babelrc.js",
    ".babelrc.json",
    ".swcrc",
    ".swcrc.json",
    "muter.conf.yml",
    "muter.conf.yaml",
    "muter.conf.json",
    "mutate4dart.yaml",
    "knip.json",
    "knip.jsonc",
    ".knip.json",
    ".knip.jsonc",
    "knip.js",
    "knip.ts",
    "knip.config.js",
    "knip.config.ts",
    ".dependency-cruiser.js",
    ".dependency-cruiser.cjs",
    ".dependency-cruiser.mjs",
    ".dependency-cruiser.json",
    "dependency-cruiser.config.js",
    ".swiftlint.yml",
    ".swiftlint.yaml",
)
_STRIP_NAMES = _SETTINGS_NAMES + _C4C_SETTINGS_NAMES
#: Cargo's config is matched by path, never by the bare name: a bare ``config.toml``
#: would strip unrelated project files.
_STRIP_PATHS = (".cargo/config.toml",)
#: Directory names whose whole file list is stripped at any depth. Cargo reads
#: ``.cargo/config`` too and prefers it when both names exist.
_STRIP_DIR_FILES = {".cargo": ("config", "config.toml")}
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
    ("eslint-disable", "correctness", "eslint", "eslint-disable"),
    ("ts-nocheck", "correctness", "tsc", "ts-nocheck"),
    ("ts-ignore", "correctness", "tsc", "ts-ignore"),
    ("swiftlint:disable", "correctness", "swiftlint", "swiftlint-disable"),
    ("// ignore:", "correctness", "dart", "dart-ignore"),
    ("//ignore:", "correctness", "dart", "dart-ignore"),
    ("#[allow(", "correctness", "clippy", "rust-allow"),
    ("#![allow(", "correctness", "clippy", "crate-allow"),
    ("cargo-machete", "architecture-maintainability", "cargo-machete", "machete-ignore"),
)
#: Language markers (basenames, matched recursively) for the C4c language gate.
_LANGUAGE_MARKERS = {
    "typescript": frozenset({
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    }),
    "dart": frozenset({"pubspec.yaml", "pubspec.lock"}),
    "rust": frozenset({"Cargo.toml", "Cargo.lock"}),
    "swift": frozenset({"Package.swift", "Package.resolved"}),
}
#: Prefix matches for marker basenames (``tsconfig.json``, ``tsconfig.base.json``).
_LANGUAGE_MARKER_PREFIXES = {
    "typescript": ("tsconfig.",),
}
SKIP_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__", ".saga"}
)
_SHEBANG = re.compile(r"^#!.*\b(?:sh|bash|zsh)\b")
#: Shell suffixes, the ones the shellcheck wrapper scans.
_SHELL_SUFFIXES = frozenset({".sh", ".bash", ".ksh"})
#: Any ``AWS::`` text or a top-level ``Resources`` key counts: the check errs toward
#: running the CloudFormation tools.
_CLOUDFORMATION = re.compile(
    rb"AWSTemplateFormatVersion|AWS::|^Resources\s*:|\"Resources\"\s*:", re.MULTILINE
)
#: Dependency manifests that keep a language's tools running with no source file
#: (a lockfile audit still applies). Python's join the commit markers above.
_PYTHON_GATE_MARKERS = frozenset({
    "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock",
    "uv.lock", "requirements.txt",
})
#: The suffixes the checkov and cfn-lint wrappers copy for scanning.
_CLOUDFORMATION_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".template"})

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
    #: The catalogue's sha256 is a stand-in, because the licence keeps the pack out of the
    #: repository. The machine record's digest for the pack is accepted in its place.
    placeholder: bool = False


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
    #: Base-commit files the adapter asked for, as ``(name, path)`` in the order
    #: ``Adapter.base_files`` names them. ``None`` means absent at base.
    base_files: tuple[tuple[str, Path | None], ...] = ()
    #: The reviewed change, so a mutation tool can scope itself to its lines.
    change: review_diff.Change | None = None
    #: The reviewed head commit, for values that must be the same on every run.
    head: str = ""
    #: A private folder outside the scanned tree, owned by the runner and removed
    #: after this adapter runs. Inputs saga writes for a tool go here, never into
    #: the reviewed tree, whose commit and build scripts could plant symlinks.
    scratch: Path | None = None
    #: Private local telemetry, deliberately outside emitted records and hashes.
    diagnostics_directory: Path | None = None
    #: Which tree this scan reads: ``head``, or ``base`` for a base-and-head comparison's first
    #: scan. It names the scan's folders under ``scratch`` so the two never share one.
    scan: str = "head"


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
    consequence: str | None = None


@dataclass(frozen=True)
class ParseResult:
    hits: tuple[Hit, ...] = ()
    unfinished: bool = False
    problems: tuple[str, ...] = ()
    items: tuple[Mapping[str, Any], ...] = ()
    gaps: tuple[tuple[str, str], ...] = ()
    #: A parse-time degraded input as ``(reason, row)``. Set when the output
    #: proves the run cannot answer its row (a shuffle run that executed zero
    #: tests) instead of emitting findings.
    gap: tuple[str, str] | None = None


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
    #: Saga's own trusted scripts keep the operator's environment, so operator
    #: configuration (``gh`` authentication) reaches the tools they call.
    #: Narrow wins: an adapter that runs untrusted code stays narrowed.
    ambient_env: bool = False
    #: Which stream ``parse`` reads: ``stdout``, ``stderr`` or ``both``.
    stream: str = "stdout"
    #: Machine report the tool writes under the scan root, read after the run.
    report_file: str | None = None
    #: Empty output plus exit 0 parses as zero hits, for checkers silent on
    #: success. Runners leave this false: empty test output is a broken harness.
    silent_ok: bool = False
    #: Known-gap adapters short-circuit before the platforms and version probes:
    #: ``[]`` without their language markers, ``known-gap`` with them.
    gap_first: bool = False
    #: Base-commit file names staged onto ``ScanContext.base_files``.
    base_files: tuple[str, ...] = ()
    #: Directories under the scan root searched for the tool before PATH.
    local_bins: tuple[str, ...] = ()
    #: Rewrites raw output before it is stored and hashed, removing what differs
    #: between two runs of the same change (timings, build order). Issue 244.
    stable_raw: Callable[[str], str] | None = None
    #: Cuts a report to what its findings depend on, before the scratch scrub and ``stable_raw``
    #: run: it gets the report, the paths of the files the change touches, and the anchors of the
    #: hits the review kept, and returns the report with only the entries that touch a changed
    #: file or stand behind a kept hit. A report that could not be read is returned as it came.
    stable_raw_for_change: Callable[[str, frozenset[str], frozenset[str]], str] | None = None
    #: A run that exits 0 without writing ``report_file`` is parsed from its
    #: console output (stdout then stderr) instead of counting as unparseable.
    report_optional: bool = False
    #: Non-zero exits that still wrote a complete report, parsed like exit 0.
    #: cargo-mutants exits 2 when a mutant survives and 3 when one times out.
    parsed_exits: tuple[int, ...] = ()
    #: Exits that mean the run could not answer, each with its own degraded
    #: reason instead of ``unparseable`` (cargo-mutants 4: the baseline failed).
    exit_reasons: tuple[tuple[int, str], ...] = ()
    #: Failure reasons that earn one more run of the same command before they are recorded
    #: (issue 260). A pass on the retry keeps its result and adds a ``baseline-flaky`` note.
    retry_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stream not in ("stdout", "stderr", "both"):
            raise RunnerFailure(2, f"{self.id}: stream must be stdout, stderr or both")
        if self.mutation and (self.comparison == "base-head" or self.type_checker):
            raise RunnerFailure(2, f"{self.id}: mutation adapters cannot use base-head comparison")


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
    import review_adapters_typescript as typescript
    import review_adapters_dart as dart
    import review_adapters_rust as rust
    import review_adapters_swift as swift
    import review_checks

    return [
        *every.ADAPTERS,
        *python_adapters.ADAPTERS,
        *infrastructure.ADAPTERS,
        *shell.ADAPTERS,
        *workflows.ADAPTERS,
        *markdown.ADAPTERS,
        *typescript.ADAPTERS,
        *dart.ADAPTERS,
        *rust.ADAPTERS,
        *swift.ADAPTERS,
        *review_checks.ADAPTERS,
    ]


def changed_lines(
    context: ScanContext, suffixes: tuple[str, ...]
) -> list[tuple[str, frozenset[int]]]:
    """``(path, lines)`` for changed files with one of ``suffixes`` and added lines, sorted."""
    if context.change is None:
        return []
    return sorted(
        (item.path, item.lines)
        for item in context.change.files
        if item.status in {"added", "modified", "renamed"}
        and item.path.endswith(suffixes)
        and item.lines
    )


def line_ranges(lines: frozenset[int]) -> list[tuple[int, int]]:
    """Consecutive runs of ``lines`` as inclusive ``(start, end)`` pairs."""
    ranges: list[tuple[int, int]] = []
    for line in sorted(lines):
        if ranges and line == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], line)
        else:
            ranges.append((line, line))
    return ranges


def change_seed(context: ScanContext) -> int:
    """A shuffle seed fixed by the change, so two runs of one change test one order (issue 244)."""
    digest = hashlib.sha256(f"{context.base}:{context.head}".encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def language_for(path: str) -> str:
    """Suffix to a formula language. An unmapped path is ``none``.

    CloudFormation is not inferred.
    """
    normalised = path.replace("\\", "/")
    if normalised.startswith(".github/workflows/") or "/.github/workflows/" in f"/{normalised}":
        return "github-workflow"
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


def _scratch_pattern() -> re.Pattern[str]:
    """Saga's own scratch folders: ``<tempdir>/saga-<prefix><random>``, either spelling.

    ``tempfile.mkdtemp`` adds eight random characters. macOS reports the temp
    directory under ``/var`` and resolves it under ``/private/var``.
    """
    base = tempfile.gettempdir().rstrip("/")
    spellings = sorted({base, os.path.realpath(base)}, key=len, reverse=True)
    choices = "|".join(re.escape(item) for item in spellings)
    return re.compile(rf"(?:{choices})/(saga-[a-z-]*-)[a-z0-9_]{{8}}")


def _scrub(text: str, root: Path | None = None) -> str:
    """Text with the scan root made relative and saga scratch folders named stably.

    Two runs of the same change get different scratch folders; anything recorded
    must not carry them (issue 244).
    """
    if root is not None:
        for spelling in sorted({root.as_posix(), os.path.realpath(root)}, key=len, reverse=True):
            text = text.replace(spelling + "/", "").replace(spelling, ".")
    return _scratch_pattern().sub(r"<tmp>/\1", text)


def stable_json(text: str, drop: Callable[[dict[str, Any]], None]) -> str:
    """A JSON report with its per-run fields removed, keys sorted. Text that is not JSON stays.

    ``drop`` edits a top-level object in place; any other JSON document is only re-keyed.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        drop(data)
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def sorted_items(items: object) -> object:
    """A list in canonical JSON order. Anything else is returned as it came."""
    if not isinstance(items, list):
        return items
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))


def stable_sorted_list(text: str) -> str:
    """A JSON list of reports in canonical order. Text that is not a JSON list stays."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(data, list):
        return text
    return json.dumps(sorted_items(data), indent=2, sort_keys=True) + "\n"


def _stable_raw(
    adapter: Adapter, text: str, change: review_diff.Change | None = None,
    anchors: frozenset[str] = frozenset(),
) -> str:
    """Raw output as stored and hashed: scratch folders named stably, then the adapter's rewrite.

    Colour codes go first. A folder name split by an escape sequence is not a folder name to the
    scrub, and Vite colours the code frame that quotes the worktree path (issue 147). An adapter
    that cuts its report to the change (``stable_raw_for_change``) does so on the text as the tool
    wrote it, because the anchors of the kept hits were made from those names.
    """
    text = _ANSI_ESCAPE.sub("", text)
    if adapter.stable_raw_for_change is not None and change is not None:
        paths = frozenset(item.path for item in change.files if item.status != "deleted")
        text = adapter.stable_raw_for_change(text, paths, anchors)
    text = _scrub(text)
    if adapter.stable_raw is not None:
        text = adapter.stable_raw(text)
    return text


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_NUMBER = r"\d+(?:\.\d+)?"
# One rewrite per per-run value a test runner prints. Each pattern is anchored to
# the runner's own line shape, so test names and assertion text are left alone.
_TRANSCRIPT_REWRITES: tuple[tuple[re.Pattern[str], str], ...] = (
    # pytest: "==== 1 failed, 3 passed in 0.05s ====" (the = padding follows the width).
    (re.compile(rf"^=+ (.+?) in {_NUMBER}s(?: \([\d:]+\))? =+$"), r"= \1 ="),
    # pytest -q: "1 failed, 3 passed in 0.05s", "no tests ran in 0.01s", no padding.
    (re.compile(
        rf"^((?:no tests ran|\d+ [a-z]+)(?:, \d+ [a-z]+)*) in {_NUMBER}s(?: \([\d:]+\))?$"
    ), r"\1"),
    (re.compile(rf"^{_NUMBER}s (setup|call|teardown) "), r"\1 "),
    # Vitest: "   Start at  01:47:55", "   Duration  289ms (transform ...)".
    (re.compile(r"^(\s+)Start at\s+\S.*$"), r"\1Start at"),
    (re.compile(rf"^(\s+)Duration\s+{_NUMBER}m?s.*$"), r"\1Duration"),
    (re.compile(rf"^(\s*[✓×❯↓✗√·] .*?) {_NUMBER}m?s$"), r"\1"),
    # Vite writes the loaded config to "vitest.config.ts.timestamp-1792130474945-3fa9c1d2e4b5.mjs".
    (re.compile(r"\.timestamp-\d+-[0-9a-f]+\.mjs"), ".timestamp.mjs"),
    # Jest: "Time:        0.623 s, estimated 1 s", "PASS ./a.test.js (5.1 s)", "✓ adds (2 ms)".
    (re.compile(r"^Time:\s+\S.*$"), "Time:"),
    (re.compile(rf"^(\s*(?:PASS|FAIL|[✓✕○√×]) .*?) \({_NUMBER} m?s\)$"), r"\1"),
    # cargo test and cargo: "finished in 0.00s", "target(s) in 0.52s".
    (re.compile(rf"\b(finished|target\(s\)) in {_NUMBER}s\b"), r"\1"),
    # go test: "--- FAIL: TestX (0.00s)", "ok  \tpkg\t0.012s", "ok  \tpkg\t(cached)".
    (re.compile(rf"^(\s*--- (?:PASS|FAIL|SKIP): .+?) \({_NUMBER}s\)$"), r"\1"),
    (re.compile(rf"^(ok|FAIL)(\s+\S+)\s+(?:{_NUMBER}s|\(cached\))$"), r"\1\2"),
    # XCTest: "Test Case '...' passed (0.001 seconds).", "Executed 3 tests, ... in 0.004
    # (0.005) seconds", "Test Suite 'All tests' started at 2026-10-16 01:00:00.123".
    (re.compile(rf"^(Test Case .+ (?:passed|failed|skipped)) \({_NUMBER} seconds\)\.$"), r"\1."),
    (re.compile(rf"^(\s*Executed \d+ tests?, with .+?) in {_NUMBER} \({_NUMBER}\) seconds$"), r"\1"),
    (re.compile(r"^(Test Suite .+ (?:started|passed|failed) at) .+$"), r"\1"),
)
# Dart's expanded reporter: "00:01 +3 ~1 -2: label". Elapsed time and running counts.
_DART_PROGRESS = re.compile(r"^\d+:\d\d(?::\d\d)? \+\d+(?: ~\d+)?(?: -\d+)?: (.*)$")
_DART_KEPT = ("Some tests failed.", "All tests passed!", "No tests ran.")
_JEST_SUITE = re.compile(r"^(?:PASS|FAIL) ")
_JEST_COVERAGE_WARNING = re.compile(r"^Failed to collect coverage from ")
_JEST_SUMMARY = re.compile(r"^(?:Seed|Test Suites|Tests|Snapshots|Time|Ran all test suites)\b")
_VITEST_FILE = re.compile(r"^ [✓×❯↓] ")
_LIBTEST_RESULT = re.compile(r"^test .+ \.\.\. \S+$")


def stable_transcript(text: str) -> str:
    """A test runner's console text without the values that change between two runs.

    Two runs of the same tests print different durations and clock times, and the
    runners that run files in parallel workers (Jest, Vitest, Dart, cargo test)
    print each file's result in the order the workers finished. This drops the
    durations and times, sorts what parallel workers print, and keeps Dart's
    failures and summary, since its progress lines name whichever test happened
    to be running. Only the stored, hashed copy is rewritten; parsing reads the
    runner's own text (issue 244).
    """
    lines = [line.rstrip() for line in _ANSI_ESCAPE.sub("", text).splitlines()]
    lines = _dart_failures(lines)
    rewritten = []
    for line in lines:
        for pattern, replacement in _TRANSCRIPT_REWRITES:
            line = pattern.sub(replacement, line)
        rewritten.append(line)
    rewritten = _sorted_jest(rewritten)
    rewritten = _sorted_blocks(rewritten, _VITEST_FILE.match, lambda line: line.startswith("   "))
    rewritten = _sorted_blocks(rewritten, _LIBTEST_RESULT.match, lambda _line: False)
    # Jest moves a blank line with a block's position; blank lines carry nothing.
    kept = [line for line in rewritten if line]
    return "\n".join(kept) + ("\n" if kept else "")


def _dart_failures(lines: list[str]) -> list[str]:
    """Dart's progress blocks reduced to its ``[E]`` failures and summary, unprefixed and sorted."""
    if not any(_DART_PROGRESS.match(line) for line in lines):
        return lines
    preamble: list[str] = []
    blocks: list[list[str]] = []
    keep = True
    for line in lines:
        progress = _DART_PROGRESS.match(line)
        if progress is None:
            if not blocks:
                preamble.append(line)
            elif keep:
                blocks[-1].append(line)
            continue
        label = progress.group(1)
        keep = label.endswith(" [E]") or label in _DART_KEPT
        if keep:
            blocks.append([label])
    failures = sorted(block for block in blocks if block[0] not in _DART_KEPT)
    summary = [block for block in blocks if block[0] in _DART_KEPT]
    return preamble + [line for block in failures + summary for line in block]


def _sorted_jest(lines: list[str]) -> list[str]:
    """Jest's suite blocks in one sorted run, then its other worker lines sorted, then its summary.

    Jest prints a suite's result when the worker finishes it, and its warnings (``Failed to
    collect coverage from ...`` with the ``ERROR:`` and ``STACK:`` lines under it) land between
    suites at whatever point the worker reached. Sorting only adjacent suites let each warning
    split them differently on each run (issue 147), so every suite block is collected first.
    A block is a ``PASS`` or ``FAIL`` line and the indented or blank lines under it. Text with no
    suite line is left alone.
    """
    if not any(_JEST_SUITE.match(line) for line in lines):
        return lines
    suites: list[list[str]] = []
    others: list[list[str]] = []
    summary: list[str] = []
    sink: list[str] | None = None
    in_warning = False
    for line in lines:
        indented = not line or line[0].isspace()
        if _JEST_SUITE.match(line):
            sink = [line]
            suites.append(sink)
            in_warning = False
        elif _JEST_SUMMARY.match(line):
            sink = summary
            summary.append(line)
            in_warning = False
        elif in_warning and (indented or line.startswith(("ERROR:", "STACK:"))):
            assert sink is not None
            sink.append(line)
        elif indented and sink is not None:
            sink.append(line)
        elif _JEST_COVERAGE_WARNING.match(line):
            sink = [line]
            others.append(sink)
            in_warning = True
        else:
            sink = [line]
            others.append(sink)
            in_warning = False
    return [
        line for group in (*sorted(suites), *sorted(others)) for line in group
    ] + summary


def _sorted_blocks(
    lines: list[str],
    starts: Callable[[str], object],
    continues: Callable[[str], object],
) -> list[str]:
    """Each run of adjacent blocks sorted. A block is a start line and the lines that continue it."""
    out: list[str] = []
    run: list[list[str]] = []

    def flush() -> None:
        for block in sorted(run):
            out.extend(block)
        run.clear()

    for line in lines:
        if starts(line):
            run.append([line])
        elif run and continues(line):
            run[-1].append(line)
        else:
            flush()
            out.append(line)
    flush()
    return out


def stable_coverage_report(data: bytes) -> bytes:
    """A coverage report as stored and hashed: no generation timestamp, scratch folders named stably.

    coverage.py writes ``meta.timestamp`` in its JSON and Cobertura XML carries a
    ``timestamp`` attribute; both change on every run (issue 244).
    """
    text = data.decode("utf-8", errors="replace")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = None
    if isinstance(document, dict):
        meta = document.get("meta")
        if isinstance(meta, dict):
            meta.pop("timestamp", None)
        text = json.dumps(document, sort_keys=True)
    else:
        text = re.sub(r'\btimestamp="[^"]*"', 'timestamp=""', text)
    return _scrub(text).encode()


def _stable_hit(hit: Hit, root: Path) -> Hit:
    """A hit whose rule, anchor and statement carry no scan root or scratch folder."""
    return replace(
        hit,
        rule_id=_scrub(hit.rule_id, root),
        anchor=_scrub(hit.anchor, root),
        statement=_scrub(hit.statement, root),
    )


def _relative_hit(hit: Hit, root: Path) -> Hit:
    """Rewrite an absolute hit path relative to the scanned root.

    Tools that print absolute paths (eslint, SwiftLint, the Swift compiler) would
    otherwise never match the change. Relative paths pass through untouched, so no
    C4a adapter changes. A path outside the root is matched by repo suffix (tools
    like Muter copy the tree elsewhere and report that copy); one without a
    unique match keeps its absolute form and the filters drop it.
    """
    candidate = Path(hit.path)
    if not candidate.is_absolute():
        return hit
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        mapped = _repo_relative(candidate, root)
        return replace(hit, path=mapped) if mapped is not None else hit
    return replace(hit, path=relative.as_posix())


@lru_cache(maxsize=128)
def _tracked_files(root: str) -> tuple[str, ...]:
    """Repo-relative tracked files under a scan root, cached per root."""
    result = _git(Path(root), ["ls-files", "-z"])
    if result.returncode != 0:
        return ()
    return tuple(
        entry for entry in result.stdout.split("\0") if entry and entry != ".git"
    )


#: Python source for the wrapper scripts that run as ``python3 -c``. It defines
#: ``tracked_files(root, prune)``, the same listing ``scan_files`` makes, because a wrapper
#: cannot import this module. ``plugins/saga/tests/test_review_scan_files.py`` runs both on
#: the same trees and compares them. Change the two together.
TRACKED_PRELUDE = r"""
import os, subprocess
from pathlib import Path

def regular_in_root(path, root):
    # A regular file, or a symlink whose target is a regular file inside root.
    if not path.is_file():
        return False
    if not path.is_symlink():
        return True
    try:
        path.resolve().relative_to(Path(root).resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True

def _tracked_names(directory):
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=directory, capture_output=True,
        )
        listed = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "--name-only", "HEAD"],
            cwd=directory, capture_output=True,
        )
    except OSError:
        return None
    if top.returncode != 0 or listed.returncode != 0:
        return None
    if Path(os.fsdecode(top.stdout).rstrip("\n")).resolve() != directory.resolve():
        return None
    return [os.fsdecode(entry) for entry in listed.stdout.split(b"\0") if entry]

def _tracked_under(root, directory, prune, depth=0):
    names = _tracked_names(directory)
    if names is None:
        return None
    found = []
    linked = {}
    for entry in sorted(names):
        path = directory / entry
        parts = path.relative_to(root).parts
        if set(parts[:-1]) & set(prune):
            continue
        # A tracked path under a symlinked directory is read through the link, so skip it.
        if any(
            linked.setdefault(parts[:i], root.joinpath(*parts[:i]).is_symlink())
            for i in range(1, len(parts))
        ):
            continue
        if path.is_symlink() or path.is_file():
            found.append(path)
        elif path.is_dir() and parts[-1] not in prune and depth < 8 and (path / ".git").exists():
            # A checked-out submodule: git records only its commit, so list its own files.
            found.extend(_tracked_under(root, path, prune, depth + 1) or [])
    return found

def tracked_files(root, prune=(".git",)):
    root = Path(root)
    found = _tracked_under(root, root, prune)
    if found is not None:
        return found
    # Not a git repository: read every file, skipping the pruned directories.
    found = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in set(prune) | {".git"})
        found.extend(Path(directory) / name for name in sorted(filenames))
    return found
"""


def _git_raw(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run git and keep stdout as bytes, so a ``-z`` listing is split on NUL, never decoded whole."""
    return subprocess.run(  # nosec B603
        ["git", *args], cwd=repo, capture_output=True, check=False,
    )


def _tracked_names(directory: Path) -> list[str] | None:
    """Names ``git ls-tree`` lists at HEAD of ``directory``, or None when it is no repository top."""
    top = _git_raw(directory, ["rev-parse", "--show-toplevel"])
    listed = _git_raw(directory, ["ls-tree", "-r", "-z", "--name-only", "HEAD"])
    if top.returncode != 0 or listed.returncode != 0:
        return None
    if Path(os.fsdecode(top.stdout).rstrip("\n")).resolve() != directory.resolve():
        return None
    return [os.fsdecode(entry) for entry in listed.stdout.split(b"\0") if entry]


def _tracked_under(
    root: Path, directory: Path, prune: frozenset[str] | set[str], depth: int = 0,
) -> list[Path] | None:
    names = _tracked_names(directory)
    if names is None:
        return None
    found: list[Path] = []
    linked: dict[tuple[str, ...], bool] = {}
    for entry in sorted(names):
        path = directory / entry
        parts = path.relative_to(root).parts
        if set(parts[:-1]) & set(prune):
            continue
        # A tracked path under a symlinked directory is read through the link, so skip it.
        if any(
            linked.setdefault(parts[:i], root.joinpath(*parts[:i]).is_symlink())
            for i in range(1, len(parts))
        ):
            continue
        if path.is_symlink() or path.is_file():
            found.append(path)
        elif path.is_dir() and parts[-1] not in prune and depth < 8 and (path / ".git").exists():
            # A checked-out submodule: git records only its commit, so list its own files.
            found.extend(_tracked_under(root, path, prune, depth + 1) or [])
    return found


def scan_files(root: Path, prune: frozenset[str] | set[str] = frozenset({".git"})) -> list[Path]:
    """The files a review check may read under a scan root, in a fixed order.

    Only files git tracks at HEAD of the scan root, and only those still on disk. Earlier
    prepare tools leave build output in the copy (``target/``, ``mutants.out/``, caches),
    and it changes from run to run, so a check that read it would write a different
    packet each time and point findings at files that are not in the repository. The
    listing is the same for a clean copy and for one a tool has written into.

    A directory name in ``prune`` drops every path under a directory of that name, even
    when git tracks it. A symlink leaf is returned as a path, never followed. A tracked
    path with a symlink anywhere above its leaf is dropped, because reading it would go
    through the link. A checked-out submodule contributes the files its own repository
    tracks at its HEAD; its untracked files and its ``.git`` file are not listed.

    When the scan root is not the top of a git repository (or git cannot read it, for
    example a ``safe.directory`` refusal), there is no tracked set to read, so this falls
    back to the old behaviour: every file under the root, with ``prune`` directories
    skipped and ``.git`` always skipped.
    """
    root = Path(root)
    found = _tracked_under(root, root, prune)
    if found is not None:
        return found
    found = []
    skipped = set(prune) | {".git"}
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in skipped)
        found.extend(Path(directory) / name for name in sorted(filenames))
    return found


def _repo_relative(candidate: Path, root: Path) -> str | None:
    """The repo file a foreign absolute path denotes, or None.

    The match is a boundary-aware suffix that is unique across tracked files:
    ``/tmp/muter_tmp/abc/Sources/a.swift`` denotes ``Sources/a.swift`` when no
    other tracked file ends that way. Ambiguous or unknown paths stay absolute
    so the filters drop them instead of misattributing the hit. Roots are
    unique worktrees, so the cached census cannot go stale within a run.
    """
    text = candidate.as_posix()
    matches = [
        entry for entry in _tracked_files(str(root)) if text.endswith("/" + entry)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def subprocess_runner(
    argv: Sequence[str] | str,
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    shell: bool,
    umask: int | None = None,
) -> ProcessResult:
    """Run one tool, shutting down its POSIX process group before returning.

    Descendants that deliberately start another session escape this lifetime boundary;
    it is not a sandbox. Other platforms retain subprocess.run's direct-process cleanup.
    A string command, or a shell, is a programming error.

    *umask*, when given, is the file-creation mask the child starts with (POSIX only); this
    process's own mask is not changed. Without it the child inherits the parent's mask.
    """
    if shell or isinstance(argv, str):
        raise RuntimeError("a review tool receives an argument vector and shell=False")
    if os.name != "posix":
        result = subprocess.run(  # nosec B603
            list(argv), cwd=cwd, env=dict(env), timeout=timeout, shell=False,
            capture_output=True, text=True, check=False,
        )
        return ProcessResult(result.returncode, result.stdout, result.stderr)
    proc = subprocess.Popen(  # nosec B603
        list(argv),
        cwd=cwd,
        env=dict(env),
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        umask=-1 if umask is None else umask,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return ProcessResult(proc.wait(), stdout, stderr)
    finally:
        # communicate() may have reaped a successful parent whose background
        # children still use our temporary directories. Always stop its group.
        try:
            _stop_tool_group(proc)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()


def _stop_tool_group(proc: subprocess.Popen[str]) -> None:
    """Give this invocation a bounded TERM grace, then KILL and reap its parent."""
    deadline = time.monotonic() + 0.5
    try:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            # A cooperating tool may flush diagnostics while unwinding. Draining
            # both pipes prevents that cleanup from blocking on a full pipe.
            # The original TimeoutExpired keeps its original partial bytes.
            proc.communicate(timeout=max(0.0, deadline - time.monotonic()))
        except (subprocess.TimeoutExpired, UnicodeError):
            # Cleanup bytes are discarded, so decoding them must not replace
            # the original timeout or cancellation.
            pass
        while time.monotonic() < deadline:
            proc.poll()
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.01)
    finally:
        # This also runs if cancellation interrupts the graceful shutdown.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


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
    diagnostics_directory: Path | str | None = None,
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
            Path(diagnostics_directory) if diagnostics_directory is not None else None,
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
    diagnostics_directory: Path | None = None,
) -> int:
    base_sha = _require_sha(repo, base)
    head_sha = _require_sha(repo, head)
    _rev.cache_clear()
    _blob.cache_clear()
    _clean_tree.cache_clear()
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
    rule_sources: dict[str, dict[str, Any]] = {}
    mutation_remaining = float(MUTATION_CAP_SECONDS)
    tool_env, tool_temps = _tool_env(home)
    base_markers = _tree_markers(repo, base_sha)
    head_markers = _tree_markers(repo, head_sha)
    extra: list[tuple[str, Path]] = []
    try:
        with _worktree(repo, head_sha) as head_root:
            degraded.extend(_strip_settings(head_root))
            degraded.extend(_allow_comments(head_root, change))
            for adapter in adapters:
                _link_env(adapter, repo, head_root, head_sha, head_sha)
            head_languages = run_languages(head_root)
            # What stands in the worktree now (the linked dependency folders, the stripped
            # settings files) is what every tool starts from; whatever a tool adds or edits
            # is undone before the next one runs.
            residue = _TreeResidue(head_root)
            for adapter in adapters:
                if adapter.mode == "fix" or not adapter.tool:
                    continue
                mutation_start = time.monotonic() if adapter.mutation else None
                deadline = (mutation_start + mutation_remaining
                            if mutation_start is not None else None)
                degraded_start, items_start = len(degraded), len(items)
                try:
                    try:
                        adapter_hits = _run_adapter(
                            adapter, repo, base_sha, head_sha, head_root, change, home, profile,
                            process, tool_env, deadline, degraded, items, base_markers,
                            head_markers, head_languages,
                            diagnostics_directory, rule_sources,
                        )
                        if _mutation_past_deadline(adapter, deadline):
                            del degraded[degraded_start:]
                            del items[items_start:]
                            degraded.append(_problem_entry(adapter, "cap"))
                        else:
                            pending.extend(adapter_hits)
                    except Exception:
                        if not _mutation_past_deadline(adapter, deadline):
                            raise
                        del degraded[degraded_start:]
                        del items[items_start:]
                        degraded.append(_problem_entry(adapter, "cap"))
                finally:
                    residue.clear(adapter.id, diagnostics_directory)
                    if mutation_start is not None:
                        mutation_remaining -= max(0.0, time.monotonic() - mutation_start)
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
            _emit(
                output, findings, measurements, degraded, builder_record, items, change.touched(),
                rule_sources,
            )
            return 0
    finally:
        for _language, path in extra:
            shutil.rmtree(path, ignore_errors=True)
        for path in tool_temps:
            shutil.rmtree(path, ignore_errors=True)


def _shebang_shell(path: Path) -> bool:
    # The reviewed tree is untrusted: a symlink to a FIFO or device must not be read.
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            line = handle.readline(200)
    except OSError:
        return False
    text = line.decode("utf-8", errors="ignore")
    return _SHEBANG.search(text) is not None


def _walk_files(root: Path) -> Iterator[tuple[Path, str]]:
    """``(path, posix path relative to root)`` for every file outside ``SKIP_DIRS``."""
    base = Path(root)
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(directory) / name
            yield path, path.relative_to(base).as_posix()


def _languages_in(files: Iterable[tuple[Path, str]]) -> set[str]:
    """Formula languages among ``(path, posix path relative to the root)`` pairs."""
    found: set[str] = set()
    for path, relative in files:
        name = path.name
        suffix = path.suffix.lower()
        if name == "Cargo.toml":
            found.add("rust")
        if suffix == ".py":
            found.add("python")
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            found.add("typescript")
        elif suffix == ".dart":
            found.add("dart")
        elif suffix == ".rs":
            found.add("rust")
        elif suffix == ".swift":
            found.add("swift")
        elif suffix == ".md":
            found.add("markdown")
        elif suffix in _SHELL_SUFFIXES:
            found.add("shell")
        elif suffix == "" and _shebang_shell(path):
            found.add("shell")
        if suffix in {".yml", ".yaml"} and (
            relative.startswith(".github/workflows/")
            or "/.github/workflows/" in f"/{relative}"
        ):
            found.add("github-workflow")
    return found


def detect_languages(root: Path) -> list[str]:
    """Formula languages present in *root*, in ``review_formula.LANGUAGES`` order.

    ``cloudformation`` is not detected. ``cdk.json`` does not add Python. ``/saga:setup``
    pins the tools this selects. ``SKIP_DIRS`` are not read.
    """
    found = _languages_in(_walk_files(root))
    return [language for language in review_formula.LANGUAGES if language in found]


def _cloudformation_present(files: Iterable[tuple[Path, str]]) -> bool:
    """True when ``files`` hold ``cdk.json`` or a CloudFormation template.

    A template-suffix symlink counts without reading its target: the wrappers may copy
    what it points at, and the check must never skip a file they would scan.
    """
    for path, _relative in files:
        if path.name == "cdk.json":
            return True
        if path.suffix.lower() not in _CLOUDFORMATION_SUFFIXES:
            continue
        if path.is_symlink():
            return True
        if not path.is_file():
            continue
        try:
            if _CLOUDFORMATION.search(path.read_bytes()):
                return True
        except OSError:
            continue
    return False


def run_languages(root: Path) -> frozenset[str]:
    """The languages an adapter may run for, read from the files the adapters scan.

    A suffix language is present when ``scan_files`` (``.git`` pruned only) holds a file
    of it, so Python under ``build/`` still runs bandit. ``cloudformation`` is added for
    ``cdk.json`` or a template, which setup does not detect.
    """
    root = Path(root)
    files = [(path, path.relative_to(root).as_posix()) for path in scan_files(root)]
    found = _languages_in(files)
    if _cloudformation_present(files):
        found.add("cloudformation")
    return frozenset(found)


def _language_absent(
    adapter: Adapter,
    languages: frozenset[str] | None,
    markers: frozenset[str] | None = None,
) -> bool:
    """True when none of the adapter's languages is in the reviewed tree.

    A language is present when setup's detection finds it or the head tree commits one
    of its marker files, so a dependency audit still runs on a lockfile alone. A ``*``
    adapter scans whatever the tree holds; ``None`` means the tree was not read.
    """
    if languages is None or "*" in adapter.languages:
        return False
    if languages & set(adapter.languages):
        return False
    if markers is None:
        return True
    for language in adapter.languages:
        if _marker_hit(language, markers):
            return False
        if language == "python" and any(
            name in _PYTHON_GATE_MARKERS or name.startswith("requirements")
            for name in markers
        ):
            return False
    return True


def _marker_hit(language: str, basenames: frozenset[str]) -> bool:
    """True when any marker basename for ``language`` is present."""
    if basenames & _LANGUAGE_MARKERS.get(language, frozenset()):
        return True
    return any(
        name.startswith(prefix)
        for prefix in _LANGUAGE_MARKER_PREFIXES.get(language, ())
        for name in basenames
    )


def _tree_markers(repo: Path, sha: str) -> frozenset[str] | None:
    """Marker basenames committed at ``sha``. None when git cannot answer."""
    result = _git(repo, ["ls-tree", "-r", "--name-only", sha, "--", "."])
    if result.returncode != 0:
        return None
    return frozenset(
        line.rsplit("/", 1)[-1] for line in result.stdout.splitlines() if line.strip()
    )


def _markers_present(adapter: Adapter, head_markers: frozenset[str]) -> bool:
    """True when the head tree carries any of the adapter's languages."""
    return any(
        language == "*" or _marker_hit(language, head_markers)
        for language in adapter.languages
    )


def _markers_removed(
    adapter: Adapter,
    base_markers: frozenset[str] | None,
    head_markers: frozenset[str] | None,
) -> bool:
    """True when every concrete language of the adapter lost its markers.

    The ``*`` language never counts: C4a adapters scan whatever the tree holds.
    Unknown trees (either side None) decline to judge.
    """
    concrete = [language for language in adapter.languages if language != "*"]
    if not concrete or base_markers is None or head_markers is None:
        return False
    return all(
        _marker_hit(language, base_markers) and not _marker_hit(language, head_markers)
        for language in concrete
    )


@contextmanager
def _staged_base_files(
    repo: Path, base_sha: str, names: Sequence[str]
) -> Iterator[tuple[tuple[str, Path | None], ...]]:
    """Materialize ``git show base:name`` content into temp files.

    Yields ``(name, path)`` in order; ``None`` means absent at base. Nothing is
    read from the reviewed tree.
    """
    staged: list[tuple[str, Path | None]] = []
    directory: str | None = None
    try:
        for name in names:
            try:
                result = _git(repo, ["show", f"{base_sha}:{name}"])
            except UnicodeDecodeError:
                staged.append((name, None))
                continue
            if result.returncode != 0:
                staged.append((name, None))
                continue
            if directory is None:
                directory = tempfile.mkdtemp(prefix="saga-base-files-")
            target = Path(directory) / name.replace("/", "_")
            target.write_bytes(result.stdout.encode())
            staged.append((name, target))
        yield tuple(staged)
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


def scan_folder(context: ScanContext, name: str) -> Path:
    """A fresh, empty folder for one scan's own files (copies, generated config, a session).

    It lives under the adapter's scratch folder, so nothing it holds outlives the adapter, and it
    is named by the scan (``base`` or ``head``), so the two scans of a comparison never see each
    other's files and a repeat of one scan starts empty (issue 147). A context with no scratch
    folder, which only a direct caller builds, gets ``<home>/<name>`` emptied first.
    """
    if context.scratch is not None:
        path = context.scratch / f"{name}-{context.scan}"
    else:
        path = context.home / name
    _remove_tree(path)
    path.mkdir(parents=True)
    return path


@contextmanager
def _scratch() -> Iterator[Path]:
    """A fresh owner-only folder outside every scan tree, removed afterwards."""
    path = Path(tempfile.mkdtemp(prefix="saga-adapter-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _tool_env(home: Path) -> tuple[dict[str, str], list[str]]:
    """The environment adapter tools run under, plus temp dirs to clean.

    An allow-list (PATH, locale, TZ, the Windows basics) with a fresh HOME and
    TMPDIR, mirroring the relocated run. ``CARGO_HOME`` points at a persistent
    credentials-free cache under ``.saga`` so public crates resolve without
    operator credentials. Cargo-family runs override it per invocation (see
    ``_execute``). ``RUSTUP_HOME`` passes through (defaulting to the real
    home's ``.rustup``) so a rustup proxy finds its toolchain under the fresh
    HOME, as does ``RUSTUP_TOOLCHAIN`` when set. Returns the env and the temp
    dirs the caller removes.
    """
    names = ("PATH", "PATHEXT", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
    if sys.platform == "win32":
        names += ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC")
    env = {name: os.environ[name] for name in names if name in os.environ}
    fresh_home = tempfile.mkdtemp(prefix="saga-tool-home-")
    fresh_tmp = tempfile.mkdtemp(prefix="saga-tool-tmp-")
    env["HOME"] = fresh_home
    env["TMPDIR"] = fresh_tmp
    # Python tools order sets and dicts of strings by a per-process hash seed. cfn-lint reported a
    # different subset of one rule's errors on each run until the seed was fixed (issue 147).
    env["PYTHONHASHSEED"] = "0"
    if sys.platform == "win32":
        env["TEMP"] = fresh_tmp
        env["TMP"] = fresh_tmp
    cache = _saga(home) / "cargo-home"
    existed = cache.exists()
    cache.mkdir(mode=0o700, exist_ok=True)
    if not existed:
        try:
            os.chmod(cache, 0o700)
        except OSError:  # pragma: no cover - Windows ACLs
            pass
    env["CARGO_HOME"] = str(cache)
    env["RUSTUP_HOME"] = os.environ.get("RUSTUP_HOME") or str(
        Path.home() / ".rustup"
    )
    if "RUSTUP_TOOLCHAIN" in os.environ:
        env["RUSTUP_TOOLCHAIN"] = os.environ["RUSTUP_TOOLCHAIN"]
    return env, [fresh_home, fresh_tmp]


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
    deadline: float | None,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
    base_markers: frozenset[str] | None,
    head_markers: frozenset[str] | None,
    head_languages: frozenset[str] | None = None,
    diagnostics_directory: Path | None = None,
    rule_sources: dict[str, dict[str, Any]] | None = None,
) -> list[Hit]:
    if _markers_removed(adapter, base_markers, head_markers):
        degraded.append(
            _degraded(adapter, _primary_row(adapter), "language-markers-removed")
        )
    if _language_absent(adapter, head_languages, head_markers):
        # Setup never pins a tool for a language the repository lacks, so running
        # it would only record a degraded row that no lens can use (issue 253).
        return []
    if adapter.gap_first and head_markers is not None:
        rows = adapter.gap_rows or adapter.rows[:1]
        if _markers_present(adapter, head_markers):
            for row in rows:
                degraded.append(_degraded(adapter, row, "known-gap"))
        return []
    if adapter.platforms and sys.platform not in adapter.platforms:
        degraded.append(_degraded(adapter, _primary_row(adapter), "unsupported-platform"))
        return []
    if adapter.gap_path is not None and not _present(_gap_target(adapter, head_root)):
        rows = adapter.gap_rows or adapter.rows[:1]
        for row in rows:
            degraded.append(_degraded(adapter, row, "known-gap"))
        return []
    rules, rules_source = _resolve_rules(adapter, profile, home)
    if rule_sources is not None and any(rule.pack for rule in rules):
        rule_sources[adapter.id] = {
            "source": rules_source,
            "rules": [
                {"pack": rule.pack, "sha256": rule.sha256} for rule in rules if rule.pack
            ],
        }
    review = profile.get("review") if isinstance(profile, Mapping) else None
    with _rule_config(adapter, rules, repo, home, base_sha, review) as (
        configs,
        cache_problem,
        saga_notes,
    ):
        degraded.extend(saga_notes)
        if cache_problem is not None:
            degraded.append(_degraded(adapter, _primary_row(adapter), cache_problem))
            return []
        probe_timeout: float | None = None
        if adapter.mutation:
            assert deadline is not None
            probe_timeout = deadline - time.monotonic()
        if probe_timeout is not None and probe_timeout <= 0:
            # Still ask the adapter whether it has work: an empty invocation must
            # not be reported as a capped scan.
            version, problem = None, None
        else:
            try:
                version, problem = _read_version(
                    adapter, profile, process, env, head_root,
                    timeout=probe_timeout, deadline=deadline,
                )
            except Exception:
                if not _mutation_past_deadline(adapter, deadline):
                    raise
                version, problem = None, "cap"
            if _mutation_past_deadline(adapter, deadline):
                version, problem = None, "cap"
        if problem == "cap":
            degraded.append(_problem_entry(adapter, problem))
            return []
        if problem in {"missing", "timeout"}:
            degraded.append(_degraded(adapter, _primary_row(adapter), problem))
            return []
        off_pin = problem in {"version-mismatch", "version-unreadable"}
        if off_pin:
            degraded.append(_degraded(adapter, _primary_row(adapter), str(problem)))
        # The budget is checked in ``_once``, after the tool says whether it has anything to run.
        timeout = adapter.timeout_seconds
        if adapter.mutation:
            assert deadline is not None
            timeout = max(1, min(timeout, int(deadline - time.monotonic())))
        ran = version or adapter.default_version
        comparison = "base-head" if adapter.type_checker else adapter.comparison
        with (
            _staged_base_files(repo, base_sha, adapter.base_files) as staged,
            _scratch() as scratch,
        ):
            context = ScanContext(
                head_root,
                head_root,
                home,
                configs,
                base=base_sha,
                test_command=_python_test_command(profile),
                commands=_scan_commands(profile),
                base_files=staged,
                change=change,
                head=head_sha,
                scratch=scratch,
                diagnostics_directory=diagnostics_directory,
            )
            if comparison == "base-head":
                hits, digests = _base_and_head(
                    adapter, repo, base_sha, head_sha, head_root, context, process, env,
                    timeout, ran, degraded, _rules_digest(rules), items,
                )
            else:
                hits, digests = _once(
                    adapter, context, process, env, timeout, "head", degraded, items,
                    deadline,
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


def _mutation_past_deadline(adapter: Adapter, deadline: float | None) -> bool:
    """A completed mutation step is late only strictly after its deadline."""
    return deadline is not None and adapter.mutation and time.monotonic() > deadline


def _once(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: int,
    label: str,
    degraded: list[dict[str, str]],
    items: list[Mapping[str, Any]],
    deadline: float | None = None,
) -> tuple[tuple[Hit, ...], dict[str, str]]:
    diagnostic = _attempt_diagnostic(adapter, context, label, "initial", deadline)
    try:
        result, problem, ran = _capture(
            adapter, context, process, env, timeout, diagnostic, deadline,
        )
    except ToolGap as exc:
        if _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap")
            degraded.append(_problem_entry(adapter, "cap"))
            return (), {}
        if diagnostic is not None:
            diagnostic.finish("skipped", exc.reason)
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    except BaseException as exc:
        if isinstance(exc, Exception) and _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap")
            degraded.append(_problem_entry(adapter, "cap"))
            return (), {}
        if diagnostic is not None:
            reason = "cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "execution-error"
            diagnostic.finish("failed", reason)
        raise
    if _mutation_past_deadline(adapter, deadline):
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code if result is not None else None)
        degraded.append(_problem_entry(adapter, "cap"))
        return (), {}
    if not ran:
        if diagnostic is not None:
            diagnostic.finish("skipped", "not-invoked")
        return (), {}
    if problem is not None:
        if diagnostic is not None:
            diagnostic.finish("failed", problem)
        degraded.append(_problem_entry(adapter, problem))
        return (), {}
    assert result is not None
    try:
        parsed, failure = _parsed(adapter, result, label)
    except ToolGap as exc:
        if _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap", result.code)
            degraded.append(_problem_entry(adapter, "cap"))
            return (), {}
        if diagnostic is not None:
            diagnostic.finish("skipped", exc.reason, result.code)
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    except Exception:
        if not _mutation_past_deadline(adapter, deadline):
            raise
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code)
        degraded.append(_problem_entry(adapter, "cap"))
        return (), {}
    if _mutation_past_deadline(adapter, deadline):
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code)
        degraded.append(_problem_entry(adapter, "cap"))
        return (), {}
    if diagnostic is not None:
        reason = failure or (parsed.gap[0] if parsed is not None and parsed.gap else None)
        diagnostic.finish("failed" if reason else "succeeded", reason, result.code)
    try:
        if failure in adapter.retry_failures:
            retried = _retry(adapter, context, process, env, timeout, label, deadline)
            if retried == "cap" or _mutation_past_deadline(adapter, deadline):
                degraded.append(_problem_entry(adapter, "cap"))
                return (), {}
            if retried is not None:
                result, parsed = retried
                failure = None
                degraded.append(_degraded(adapter, _primary_row(adapter), "baseline-flaky"))
    except ToolGap as exc:
        degraded.append(_problem_entry(adapter, "cap") if _mutation_past_deadline(adapter, deadline)
                        else _degraded(adapter, exc.row, exc.reason))
        return (), {}
    except Exception:
        if not _mutation_past_deadline(adapter, deadline):
            raise
        degraded.append(_problem_entry(adapter, "cap"))
        return (), {}
    if parsed is not None:
        _note_problems(adapter, parsed, degraded, context.root)
    if failure is not None:
        degraded.append(_with_raw(
            _degraded(adapter, _primary_row(adapter), failure),
            _failure_raw(adapter, result, context.home),
        ))
        return (), {}
    assert parsed is not None
    if parsed.gap is not None:
        reason, row = parsed.gap
        degraded.append(_degraded(adapter, row, reason))
        return (), {}
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
    anchors = frozenset(hit.anchor for hit in parsed.hits)
    digest = store_raw(
        _stable_raw(adapter, result.stdout or "", context.change, anchors).encode(), context.home,
    )
    hits = tuple(
        _stable_hit(_relative_hit(hit, context.root), context.root) for hit in parsed.hits
    )
    return hits, {label: digest}


def _retry(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: float,
    label: str,
    deadline: float | None = None,
) -> tuple[ProcessResult, ParseResult] | Literal["cap"] | None:
    """One more run of the command after a failure the adapter calls flaky (issue 260).

    The result and its parse when the second run succeeds, else None, so the first failure is
    what gets recorded. A second run that declines or cannot run is the same as a second failure.
    A mutation tool's retry stays inside the mutation cap: its timeout is clamped to the time
    left before ``deadline``; an exhausted allowance is reported as a cap.
    """
    diagnostic = _attempt_diagnostic(adapter, context, label, "retry", deadline)
    if adapter.mutation and deadline is not None:
        left = deadline - time.monotonic()
        if left <= 0:
            if diagnostic is not None:
                diagnostic.finish("skipped", "budget-exhausted")
            return "cap"
        timeout = min(timeout, left)
    try:
        result, problem, ran = _capture(adapter, context, process, env, timeout, diagnostic, deadline)
    except ToolGap as exc:
        if _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap")
            return "cap"
        if diagnostic is not None:
            diagnostic.finish("skipped", exc.reason)
        return None
    except BaseException as exc:
        if isinstance(exc, Exception) and _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap")
            return "cap"
        if diagnostic is not None:
            reason = "cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "execution-error"
            diagnostic.finish("failed", reason)
        raise
    if _mutation_past_deadline(adapter, deadline):
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code if result is not None else None)
        return "cap"
    if not ran or problem is not None or result is None:
        if diagnostic is not None:
            diagnostic.finish("failed" if ran else "skipped", problem or "not-invoked")
        if adapter.mutation and problem == "cap":
            return "cap"
        return None
    try:
        parsed, failure = _parsed(adapter, result, label)
    except ToolGap as exc:
        if _mutation_past_deadline(adapter, deadline):
            if diagnostic is not None:
                diagnostic.finish("failed", "cap", result.code)
            return "cap"
        if diagnostic is not None:
            diagnostic.finish("skipped", exc.reason, result.code)
        raise
    except Exception:
        if not _mutation_past_deadline(adapter, deadline):
            raise
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code)
        return "cap"
    if _mutation_past_deadline(adapter, deadline):
        if diagnostic is not None:
            diagnostic.finish("failed", "cap", result.code)
        return "cap"
    if diagnostic is not None:
        reason = failure or (parsed.gap[0] if parsed is not None and parsed.gap else None)
        diagnostic.finish("failed" if reason else "succeeded", reason, result.code)
    if failure is not None or parsed is None or parsed.gap is not None:
        return None
    return result, parsed


def _attempt_diagnostic(
    adapter: Adapter, context: ScanContext, label: str,
    attempt: Literal["initial", "retry"], deadline: float | None,
) -> review_diagnostics.Attempt | None:
    if context.diagnostics_directory is None or adapter.id != "cargo-mutants":
        return None
    try:
        return review_diagnostics.Attempt.create(
            context.diagnostics_directory, adapter.id, label, attempt, deadline,
        )
    except (OSError, ValueError):
        print("review diagnostics: private directory unavailable or refused", file=sys.stderr)
        return None


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
                _strip_settings(base_root, only=_C4C_SETTINGS_NAMES)
                _link_env(adapter, repo, base_root, base_sha, head_sha)
                base_hits, base_digest, base_problem, base_ran = _scan_root(
                    adapter, replace(context, repo=base_root, root=base_root, scan="base"),
                    process, env,
                    timeout, "base", degraded, items,
                )
        except ToolGap:
            # The base tree declined. Head is still compared against no earlier findings.
            base_hits = ()
            base_digest = ""
            base_problem = None
            base_ran = False
        if base_problem == "empty-output":
            degraded.append(_degraded(adapter, _primary_row(adapter), base_problem))
            base_hits = ()
        elif base_problem is not None:
            degraded.append(_with_raw(
                _degraded(adapter, _primary_row(adapter), base_problem), base_digest
            ))
            return (), {}
        else:
            _write_base_cache(
                context.home, adapter, version, base_sha, settings, key, base_hits,
                base_ran,
            )
    else:
        base_hits, base_ran = cached
    try:
        head_raw: list[str] = []
        head_hits, head_digest, head_problem, head_ran = _scan_root(
            adapter, replace(context, repo=head_root, root=head_root), process, env, timeout,
            "head", degraded, items, head_raw,
        )
    except ToolGap as exc:
        degraded.append(_degraded(adapter, exc.row, exc.reason))
        return (), {}
    if head_problem is not None:
        degraded.append(_with_raw(
            _degraded(adapter, _primary_row(adapter), head_problem), head_digest
        ))
        return (), {}
    if base_ran and not head_ran and _reads_lockfiles(adapter):
        # The base audit read a lockfile the head scan does not read. Comparing
        # against silence would drop base advisories as a clean result.
        degraded.append(_degraded(adapter, _primary_row(adapter), "lockfile-removed"))
    base_ids = {_identity(adapter, hit) for hit in base_hits}
    kept = tuple(hit for hit in head_hits if _identity(adapter, hit) not in base_ids)
    if head_raw:
        # The stored report holds every entry behind a kept hit, so a finding's proof is there.
        digest = store_raw(_stable_raw(
            adapter, head_raw[0], context.change, frozenset(hit.anchor for hit in kept),
        ).encode(), context.home)
        return kept, {"head": digest}
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
    raw_sink: list[str] | None = None,
) -> tuple[tuple[Hit, ...], str, str | None, bool]:
    """One scan. With a ``raw_sink`` the stored copy is left to the caller, which appends the
    report to the sink: an adapter that cuts its report to the kept hits needs them first."""
    result, problem, ran = _capture(adapter, context, process, env, timeout)
    if not ran:
        return (), "", None, False
    if problem is not None:
        return (), "", problem, True
    assert result is not None
    parsed, failure = _parsed(adapter, result, label)
    if parsed is not None:
        _note_problems(adapter, parsed, degraded, context.root)
    if failure is not None:
        return (), _failure_raw(adapter, result, context.home), failure, True
    assert parsed is not None
    if parsed.gap is not None:
        reason, row = parsed.gap
        degraded.append(_degraded(adapter, row, reason))
        return (), "", None, True
    if raw_sink is not None and adapter.stable_raw_for_change is not None:
        raw_sink.append(result.stdout or "")
        digest = ""
    else:
        digest = store_raw(
            _stable_raw(adapter, result.stdout or "", context.change).encode(), context.home,
        )
    hits = tuple(
        _stable_hit(_relative_hit(hit, context.root), context.root) for hit in parsed.hits
    )
    if parsed.unfinished:
        degraded.append(_degraded(adapter, "testing.surviving-mutant", "cap"))
        hits = tuple(replace(hit, degraded=True) for hit in hits)
    _absorb(adapter, parsed, label, degraded, items)
    return hits, digest, None, True


def _capture(
    adapter: Adapter,
    context: ScanContext,
    process: Process,
    env: Mapping[str, str],
    timeout: float,
    diagnostic: review_diagnostics.Attempt | None = None,
    deadline: float | None = None,
) -> tuple[ProcessResult | None, str | None, bool]:
    """Run ``invoke``. jscpd is parsed from a report outside either worktree.

    The third value is false when ``invoke`` returned no argument vector. ``ToolGap`` propagates.
    A mutation tool with an argument vector to run after ``deadline`` is not run and gets the
    problem ``cap``; one with nothing to run never reaches the budget (issue 147).
    When the adapter declares ``stream`` or ``report_file``, the parsed text replaces
    stdout on the returned result, so parsing and the stored raw output read the same bytes.
    """
    report_dir: Path | None = None
    scan = context
    executed = False
    if adapter.id == "jscpd":
        report_dir = Path(tempfile.mkdtemp(prefix="saga-jscpd-"))
        scan = replace(context, report_dir=report_dir)
    try:
        argv = adapter.invoke(scan)
        if not argv:
            return None, None, False
        if adapter.mutation and deadline is not None and time.monotonic() >= deadline:
            return None, "cap", True
        if adapter.report_file is not None:
            # A committed report (or a symlink where the report goes) must
            # not be what gets parsed. Refuse a report that would land
            # outside the scan root before anything runs or is deleted.
            report = scan.root / adapter.report_file
            if not _within_root(scan.root, report.parent):
                return None, "unparseable", True
            _remove_tree(report)
        if adapter.mutation and deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                return None, "cap", True
            # Invocation setup also spends mutation time. Do not use the stale
            # timeout calculated before the adapter prepared its command.
            timeout = min(timeout, left)
        executed = True
        result, problem = _execute(
            adapter, argv, scan.root, process, env, timeout, diagnostic, deadline,
        )
        if result is not None and problem is None:
            if adapter.report_file is not None:
                report = scan.root / adapter.report_file
                if report.is_symlink():
                    return None, "unparseable", True
                if adapter.report_optional and result.code == 0 and not os.path.lexists(report):
                    console = "\n".join(
                        part for part in (result.stdout or "", result.stderr or "") if part
                    )
                    return ProcessResult(result.code, console, result.stderr), None, True
                try:
                    text = report.read_bytes().decode("utf-8", errors="replace")
                except OSError:
                    return None, "unparseable", True
                result = ProcessResult(result.code, text, result.stderr)
            elif adapter.stream == "stderr":
                result = ProcessResult(result.code, result.stderr or "", result.stderr)
            elif adapter.stream == "both":
                combined = "\n".join(
                    part for part in (result.stdout or "", result.stderr or "") if part
                )
                result = ProcessResult(result.code, combined, result.stderr)
        if adapter.id == "jscpd" and result is not None and problem is None and report_dir is not None:
            report = report_dir / "jscpd-report.json"
            text = report.read_text(encoding="utf-8") if report.is_file() else ""
            result = ProcessResult(result.code, text, result.stderr)
        return result, problem, True
    finally:
        if diagnostic is not None and executed:
            diagnostic.logs(scan.root)
        if report_dir is not None:
            shutil.rmtree(report_dir, ignore_errors=True)


def _execute(
    adapter: Adapter,
    argv: list[str] | str,
    cwd: Path,
    process: Process,
    env: Mapping[str, str],
    timeout: float,
    diagnostic: review_diagnostics.Attempt | None = None,
    deadline: float | None = None,
) -> tuple[ProcessResult | None, str | None]:
    if isinstance(argv, str) or not isinstance(argv, list):
        raise RunnerFailure(1, f"{adapter.id}: invoke returned a string command")
    if argv and adapter.local_bins and not os.path.isabs(argv[0]):
        resolved = _resolve_tool(adapter, cwd, argv[0])
        argv = [resolved, *argv[1:]]
    run_env: Mapping[str, str] = env
    temps: list[Path] = []
    if adapter.narrow_env:
        run_env, temps = _relocated_env()
    elif adapter.ambient_env:
        run_env = dict(os.environ)
    if adapter.tool == "semgrep":
        # Semgrep phones home for a version check unless told not to; the scan
        # must stay off the network and never send the operator's token.
        run_env = {**run_env, "SEMGREP_ENABLE_VERSION_CHECK": "0"}
    if argv and Path(argv[0]).name.startswith("cargo"):
        # A commit's build script runs under this environment, so a shared
        # CARGO_HOME would let it plant config the next invocation reads.
        # Each cargo invocation gets a fresh home that dies with it.
        cargo_home = Path(tempfile.mkdtemp(prefix="saga-cargo-home-"))
        temps.append(cargo_home)
        run_env = {**run_env, "CARGO_HOME": str(cargo_home)}
    try:
        if deadline is not None and adapter.mutation:
            left = deadline - time.monotonic()
            if left <= 0:
                return None, "cap"
            timeout = min(timeout, left)
        try:
            result = process(argv, cwd=cwd, env=run_env, timeout=timeout, shell=False)
        except FileNotFoundError:
            return None, "missing"
        except subprocess.TimeoutExpired as exc:
            if diagnostic is not None:
                diagnostic.console(exc.output, exc.stderr)
            return None, "timeout"
        if diagnostic is not None:
            diagnostic.console(result.stdout, result.stderr)
        return result, None
    finally:
        for path in temps:
            shutil.rmtree(path, ignore_errors=True)


def _resolve_tool(adapter: Adapter, root: Path, tool: str) -> str:
    """A scan-root-local tool binary wins over PATH. Otherwise the bare name."""
    for directory in adapter.local_bins:
        candidate = root / directory / tool
        if candidate.is_file():
            return str(candidate)
        if sys.platform == "win32":
            for suffix in (".exe", ".cmd"):
                if candidate.with_suffix(suffix).is_file():
                    return str(candidate.with_suffix(suffix))
    return tool


def _parsed(
    adapter: Adapter, result: ProcessResult, label: str
) -> tuple[ParseResult | None, str | None]:
    """Empty success is ``empty-output`` unless the adapter is silent on success.

    A non-zero run with no hits cannot be compared. A parse-time gap wins over both.
    An exit in ``exit_reasons`` records its own reason; one in ``parsed_exits`` is success.
    """
    reason = dict(adapter.exit_reasons).get(result.code)
    if reason is not None:
        return None, reason
    succeeded = result.code == 0 or result.code in adapter.parsed_exits
    text = result.stdout or ""
    if not text.strip():
        if succeeded:
            if adapter.silent_ok:
                return ParseResult(()), None
            return None, "empty-output"
        if label == "base":
            return None, "base-deps-missing"
        return None, "unparseable"
    try:
        produced = adapter.parse(text)
    except ToolGap:
        raise
    except (ValueError, json.JSONDecodeError):
        if label == "base" and not succeeded:
            return None, "base-deps-missing"
        return None, "unparseable"
    if produced.gap is not None:
        return produced, None
    if not succeeded and not produced.hits and not produced.unfinished:
        if label == "base":
            return produced, "base-deps-missing"
        return produced, "unparseable"
    return produced, None


def _read_version(
    adapter: Adapter,
    profile: Mapping[str, Any],
    process: Process,
    env: Mapping[str, str],
    root: Path,
    timeout: float | None = None,
    deadline: float | None = None,
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
        if adapter.local_bins and probe_argv and not os.path.isabs(probe_argv[0]):
            probe_argv = [
                _resolve_tool(adapter, root, probe_argv[0]), *probe_argv[1:]
            ]
        # A probe executes the same tool binary as the scan, so by default it
        # gets the narrowed run environment. The exceptions keep C4b's pinned
        # contract: a narrow adapter's probe stays ambient while its scan is
        # relocated, and saga's own trusted scripts stay ambient throughout.
        if adapter.narrow_env or adapter.ambient_env:
            probe_env = dict(os.environ)
        else:
            probe_env = env
        if adapter.tool == "semgrep":
            probe_env = {**probe_env, "SEMGREP_ENABLE_VERSION_CHECK": "0"}
        if adapter.mutation and deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                return None, "cap"
            timeout = min(adapter.timeout_seconds if timeout is None else timeout, left)
        try:
            result = process(
                probe_argv,
                cwd=probe, env=probe_env,
                timeout=(adapter.timeout_seconds if timeout is None
                         else min(adapter.timeout_seconds, timeout)),
                shell=False,
            )
        except FileNotFoundError:
            return None, "missing"
        except subprocess.TimeoutExpired:
            return None, "timeout"
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    if result.code != 0:
        # A probe that failed is not a version, whatever dotted number its
        # traceback prints (``python@3.14`` read as 3.14, issue 253).
        return None, "missing"
    version = _found_version(result.stdout or result.stderr or "")
    if version is None:
        return pinned, "version-unreadable"
    if version != pinned:
        return version, "version-mismatch"
    return version, None


def _found_version(text: str) -> str | None:
    """Dotted version anywhere, else a bare integer only as the whole output.

    Muter tags its releases ``16``, ``15`` and prints the bare number, so the
    dotted match never fires for it. A bare number anywhere in longer output
    would read build counts and warning tallies as versions, hence the
    whole-output rule.
    """
    found = _VERSION.search(text)
    if found is not None:
        return found.group(0)
    bare = text.strip()
    if _BARE_VERSION.fullmatch(bare):
        return bare
    return None


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
    adapter: Adapter,
    parsed: ParseResult,
    degraded: list[dict[str, str]],
    root: Path | None = None,
) -> None:
    lens = adapter.lens if adapter.lens in review_formula.LENSES else "correctness"
    for problem in parsed.problems:
        degraded.append({
            "lens": lens,
            "language": "none",
            "input": _scrub(problem, root),
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


def _problem_entry(adapter: Adapter, problem: str) -> dict[str, str]:
    """The degraded entry for a run that did not finish.

    A mutation tool that ran out of time, its own or the run's shared budget, is recorded as
    ``cap`` either way. Whether it finished inside the budget on this run or the next is timing,
    and the two reasons used to depend on where the budget happened to run out (issue 147).
    """
    if adapter.mutation and problem in ("timeout", "cap"):
        return _degraded(adapter, "testing.surviving-mutant", "cap")
    return _degraded(adapter, _primary_row(adapter), problem)


def _failure_raw(adapter: Adapter, result: ProcessResult, home: Path) -> str:
    """The digest of a failed run's parsed output, or ``""`` when it printed nothing.

    Only the stream the adapter parses is kept, made stable first, so two runs of
    one change still record the same bytes (issue 244). Issue 253: a failed run
    used to keep no evidence at all.
    """
    text = result.stdout or ""
    if not text.strip():
        return ""
    return store_raw(_stable_raw(adapter, text).encode(), home)


def _with_raw(entry: dict[str, str], digest: str) -> dict[str, str]:
    """``entry`` naming the stored raw output under ``raw_output`` when there is one."""
    if digest:
        entry["raw_output"] = digest
    return entry


def _primary_row(adapter: Adapter) -> str:
    if adapter.rows:
        return adapter.rows[0]
    return f"{adapter.lens}.tool-unscoped"


def _reads_lockfiles(adapter: Adapter) -> bool:
    """True for dependency audits that read lockfiles as their scan input."""
    if not adapter.lockfiles:
        return False
    return any(row.startswith("security.dependency") for row in adapter.rows)


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


def _profile_rules(adapter: Adapter, profile: Mapping[str, Any]) -> tuple[RulePin, ...] | None:
    """The rules a profile pins for this adapter, or None when it pins none.

    A pin under the adapter id wins over a pin under the tool name, so one row can pin its
    own rules without replacing the rules of the other row that shares the binary.
    """
    pins = profile.get("pins") or {}
    rules = _pin_rules_of(pins.get(adapter.id))
    if rules is None:
        rules = _pin_rules_of(pins.get(adapter.tool))
    if rules is None:
        return None
    return tuple(
        RulePin(
            pack=item.get("pack") if isinstance(item, Mapping) else None,
            sha256=item.get("sha256") if isinstance(item, Mapping) else None,
            path=item.get("path") if isinstance(item, Mapping) else None,
        )
        for item in rules
    )


def machine_rule_digest(home: Path, pack: str) -> str:
    """The digest setup recorded for *pack*'s cache in ``<home>/.saga/machine.json``, or ``""``.

    The licence keeps the pack out of the repository, so the committed digest is a stand-in and
    the real one is a fact about this machine's cache.
    """
    try:
        loaded = json.loads((Path(home) / ".saga" / "machine.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    caches = loaded.get("rule_caches") if isinstance(loaded, dict) else None
    digest = caches.get(pack) if isinstance(caches, dict) else None
    return digest if isinstance(digest, str) and _SHA.fullmatch(digest) else ""


def _resolve_rules(
    adapter: Adapter, profile: Mapping[str, Any], home: Path
) -> tuple[tuple[RulePin, ...], str]:
    """The rules to run and where their digests came from: profile, machine or catalogue.

    A profile pin wins. Otherwise a catalogue digest marked as a placeholder is replaced by the
    machine record's digest for that pack, when the record has one.
    """
    pinned = _profile_rules(adapter, profile)
    if pinned is not None:
        return pinned, "profile"
    source = "catalogue"
    resolved: list[RulePin] = []
    for rule in adapter.rules:
        digest = machine_rule_digest(home, rule.pack) if rule.placeholder and rule.pack else ""
        if digest:
            rule = replace(rule, sha256=digest, placeholder=False)
            source = "machine"
        resolved.append(rule)
    return tuple(resolved), source


def _pin_rules_of(pin: object) -> object:
    return pin.get("rules") if isinstance(pin, Mapping) else None


def _shared_update_names(review: object) -> tuple[str, ...] | None:
    """Identifier-shaped shared-update names, or None when the key is unusable.

    A missing key, a non-mapping, a non-list language entry, and a name that is
    not identifier-shaped all take the degraded path. Setup stores extension
    answers unvalidated, so nothing here may crash or be trusted.
    """
    if not isinstance(review, Mapping):
        return None
    paths = review.get("shared_update_paths")
    if not isinstance(paths, Mapping):
        return None
    names: list[str] = []
    for value in paths.values():
        if not isinstance(value, list):
            return None
        for name in value:
            if not isinstance(name, str) or _SHARED_UPDATE_NAME.match(name) is None:
                return None
            names.append(name)
    return tuple(sorted(set(names))) or None


def _shared_update_slots(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """The shared-update rule's name slots: exactly one in a well-formed rule."""
    found: list[dict[str, Any]] = []

    def visit(node: object) -> None:
        if isinstance(node, dict):
            slot = node.get("metavariable-regex")
            if isinstance(slot, dict):
                found.append(slot)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(rule.get("patterns"))
    return found


def _render_saga_rules(
    adapter: Adapter, shipped: Path, review: object, target: Path
) -> tuple[dict[str, str], ...]:
    """Copy the shipped saga rules to ``target``, filling the shared-update slot.

    Only rule files are copied, never the rule-test targets beside them. Without
    the shared-update file or a usable key the slot renders the never-matching
    pattern and the run records the degraded input; the scan still runs.
    """
    for path in sorted((*shipped.glob("*.yaml"), *shipped.glob("*.yml"))):
        shutil.copy(path, target / path.name)
    shared = target / _SHARED_UPDATE_FILE
    if not shared.is_file():
        return (_degraded(adapter, _SHARED_UPDATE_ROW, _SHARED_UPDATE_REASON),)
    document = yaml.safe_load(shared.read_text(encoding="utf-8"))
    entries = document.get("rules") if isinstance(document, dict) else None
    if not isinstance(entries, list) or len(entries) != 1:
        raise RunnerFailure(2, f"{_SHARED_UPDATE_FILE}: expected one rule")
    rule = entries[0]
    metadata = rule.get("metadata") if isinstance(rule, dict) else None
    if not isinstance(metadata, dict) or metadata.get("row") != _SHARED_UPDATE_ROW:
        raise RunnerFailure(2, f"{_SHARED_UPDATE_FILE}: expected row {_SHARED_UPDATE_ROW}")
    slots = _shared_update_slots(rule)
    if len(slots) != 1:
        raise RunnerFailure(
            2, f"{_SHARED_UPDATE_FILE}: expected one shared-update slot, found {len(slots)}"
        )
    names = _shared_update_names(review)
    if names is None:
        rule["patterns"] = [{"pattern-regex": _SHARED_UPDATE_NEVER}]
        shared.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return (_degraded(adapter, _SHARED_UPDATE_ROW, _SHARED_UPDATE_REASON),)
    slots[0]["regex"] = "(?:" + "|".join(re.escape(name) for name in names) + ")"
    shared.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return ()


def _is_saga_render(adapter: Adapter, rules: Sequence[RulePin]) -> bool:
    """The saga adapter reading the plugin's own rule directory, not an override."""
    return (
        adapter.id == "semgrep-saga"
        and len(rules) > 0
        and all(rule.path and _is_saga_rules(rule.path) for rule in rules)
    )


@contextmanager
def _rule_config(
    adapter: Adapter,
    rules: Sequence[RulePin],
    repo: Path,
    home: Path,
    base_sha: str,
    review: object = None,
) -> Iterator[tuple[tuple[Path, ...], str | None, tuple[dict[str, str], ...]]]:
    """Local pack directories only. A missing cache is not a download.

    A relative rule path other than saga's rules is a directory inside a base
    worktree. That worktree stays open until the caller finishes its scans. The
    saga row renders the plugin's own rules into a fresh directory under the
    runner home, which stays open the same way; the third yield holds the
    degraded notes that render recorded, if any.
    """
    if _is_saga_render(adapter, rules):
        shipped = plugin_root() / "references" / "semgrep"
        home.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="saga-rules-", dir=str(home)) as tmp:
            notes = _render_saga_rules(adapter, shipped, review, Path(tmp))
            yield (Path(tmp),), None, notes
        return
    if not rules:
        yield (), None, ()
        return
    needs_base = any(
        rule.path and not Path(rule.path).is_absolute() and not _is_saga_rules(rule.path)
        for rule in rules
    )
    if not needs_base:
        configs, problem = _rule_paths(adapter, rules, home, None)
        yield configs, problem, ()
        return
    with _worktree(repo, base_sha) as base_root:
        configs, problem = _rule_paths(adapter, rules, home, base_root)
        yield configs, problem, ()


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
            if not digest:
                return (), "rule-cache-missing"
            if digest != (rule.sha256 or ""):
                return (), "rule-cache-mismatch"
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
        return plugin_root() / "references" / "semgrep"
    directory = Path(path)
    if directory.is_absolute():
        return directory
    if base_root is None:
        raise RunnerFailure(2, "a relative rule path needs the base commit")
    return base_root / path


def _gap_target(adapter: Adapter, head_root: Path) -> Path:
    if adapter.gap_path == _SAGA_RULES:
        return plugin_root() / "references" / "semgrep"
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
    review = data.get("review") or None
    block = data.get("review_tools")
    if block is None:
        return {
            "languages": {},
            "languages_present": False,
            "pins": {},
            "test_command": test_command,
            "review": review,
        }
    if not isinstance(block, dict):
        raise RunnerFailure(2, "review_tools must be an object")
    return {
        "languages": _languages(block.get("languages")),
        "languages_present": "languages" in block,
        "pins": _pins(block.get("pins")),
        "test_command": test_command,
        "review": review,
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
        "review": profile.get("review"),
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
    rows = load_tool_list()
    known = {str(row.get("tool")) for row in rows if row.get("tool")}
    ids = {str(row.get("id")) for row in rows if row.get("id")} - known
    known |= ids
    cleaned: dict[str, dict[str, Any]] = {}
    for tool, spec in value.items():
        if tool not in known:
            raise RunnerFailure(2, f"unknown tool {tool!r}")
        if not isinstance(spec, dict):
            raise RunnerFailure(2, f"pin {tool} must be an object")
        version = spec.get("version")
        if tool in ids and version is not None:
            raise RunnerFailure(2, f"pin {tool}: a row id takes rules only, not a version")
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


def _strip_settings(
    root: Path, only: tuple[str, ...] | None = None
) -> list[dict[str, str]]:
    """Unlink scanner settings under ``root``. Record each path once.

    ``only`` limits the strip to the named basenames (the base worktree strips
    the C4c names only, so C4a's base behavior is unchanged). ``_STRIP_PATHS``
    and ``_STRIP_DIR_FILES`` always apply: registry and cargo configs must not
    differ between trees.
    """
    names = _STRIP_NAMES if only is None else only
    found: list[str] = []
    # Deliberately not ``scan_files``: a settings file a tool or the user left untracked in the
    # copy still steers the scanners, so the strip has to see every file, tracked or not.
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if (
                name not in names
                and relative not in _STRIP_PATHS
                and name not in _STRIP_DIR_FILES.get(Path(relative).parent.name, ())
            ):
                continue
            found.append(relative)
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
        # Base hits cached before issue 244 kept scan-root paths in their text;
        # they must not be compared with scrubbed head hits.
        "hit_text": "scrubbed",
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
        raw_output=store_raw(
            stable_transcript(_scrub(_ANSI_ESCAPE.sub("", result.stdout or ""))).encode(), home,
        ),
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
    digest = store_raw(stable_coverage_report(report), home)
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
        "consequence": hit.consequence,
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
    changed_lines: Mapping[str, Any] | None = None,
    rule_sources: Mapping[str, Any] | None = None,
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
            "changed_lines": changed_lines,
        })
    except review_formula.FormulaError as exc:
        raise RunnerFailure(2, str(exc)) from exc
    _write_json(output / "findings.json", stable_order(findings))
    _write_json(output / "measurements.json", stable_order(measurements))
    _write_json(output / "degraded.json", stable_degraded(degraded))
    _write_json(output / "outcomes.json", outcomes)
    _write_json(output / "where-to-look.json", stable_order(items))
    _write_json(output / "rule-sources.json", dict(sorted((rule_sources or {}).items())))


def stable_order(records: Sequence[Any]) -> list[Any]:
    """Records in one order whatever order the tools printed them in (issue 244).

    The key is the canonical JSON ``review_formula`` sorts its outcomes by.
    """
    return sorted(records, key=lambda record: json.dumps(record, sort_keys=True, ensure_ascii=False))


def stable_degraded(entries: Sequence[Mapping[str, Any]]) -> list[Any]:
    """Degraded entries sorted, with any saga scratch folder named stably."""
    return stable_order([
        {key: _scrub(value) if isinstance(value, str) else value for key, value in entry.items()}
        for entry in entries
    ])


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
            # Resolved: tools compare their config's real path against the scan
            # root, and an unresolved TMPDIR (macOS /var -> /private/var) makes
            # every file read as outside the base path. Relative-path tools
            # cannot tell, so no C4a adapter changes.
            yield path.resolve()
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


def _link_env(
    adapter: Adapter, repo: Path, target_root: Path, target: str, head: str
) -> None:
    """Symlink dependency directories when this checkout carries the target's lockfiles.

    The working tree must sit at the reviewed head, every lockfile present in the
    target must match the working tree's committed copy, and the working copies
    must be clean. Lockfiles absent from the target are skipped, so multi-lockfile
    rows link for whichever manager the tree uses.
    """
    if not adapter.env_dirs:
        return
    if target == head:
        # The reviewed tree is untrusted: a committed dependency directory
        # would be the code the tools resolve and run. Remove it before the
        # operator tree is linked. The base tree keeps its own: base is
        # trusted, and removing it would lose the baseline whenever base and
        # head lockfiles differ.
        for name in adapter.env_dirs:
            _remove_tree(target_root / name)
    if _rev(repo, "HEAD") != _rev(repo, head):
        return
    for lock in adapter.lockfiles:
        target_blob = _blob(repo, target, lock)
        if target_blob is None:
            continue
        if _blob(repo, "HEAD", lock) != target_blob:
            return
        if not _clean_tree(repo, lock):
            return
    for name in adapter.env_dirs:
        source = repo / name
        dest = target_root / name
        if source.exists() and not os.path.lexists(dest):
            dest.symlink_to(source, target_is_directory=source.is_dir())


#: Git for the residue check runs with the same protections ``_worktree`` uses, and more: no hook,
#: no fsmonitor command, and no Git LFS filter, because the tree being cleaned is untrusted.
_RESIDUE_GIT = (
    "-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=false",
    "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=", "-c", "filter.lfs.required=false",
)
#: ``git status`` as the residue check reads it: NUL separated, untracked and ignored entries
#: named once per folder, and no look inside a submodule.
_RESIDUE_STATUS = (
    "status", "--porcelain=v1", "-z", "--untracked-files=normal", "--ignored=traditional",
    "--ignore-submodules=all",
)
_RESTORE_BATCH = 200
#: Build-cache folders a tool creates at the worktree root and the tools after it reuse: Rust's
#: ``target`` and Swift's ``.build`` and ``.saga-build``. Removing them after every tool made
#: cargo check, clippy, the shuffle run and the no-network run each build cold, and the cold builds
#: spend the 900 second mutation budget the mutation tools share (issue 147). They are kept only
#: as real folders at the root; a link by one of these names is removed like any other residue.
#: The reviewed commit's own sources never live here, and no tool reads a finding from them.
_BUILD_CACHES = frozenset({"target", ".build", ".saga-build"})
_DIR_FLAGS = (
    getattr(os, "O_RDONLY", 0) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
)
#: Removal and restoring walk the tree through directory descriptors opened without following
#: links. A platform without them gets no clean-up rather than a path-based one.
_FD_SAFE = (
    hasattr(os, "O_DIRECTORY") and hasattr(os, "O_NOFOLLOW") and hasattr(os, "fchmod")
    and os.open in os.supports_dir_fd and os.unlink in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd and os.mkdir in os.supports_dir_fd
    and os.stat in os.supports_dir_fd and os.symlink in os.supports_dir_fd
    and os.listdir in os.supports_fd
)


def _remove_at(dir_fd: int, name: str) -> None:
    """Remove ``name`` below the open directory ``dir_fd``. A link is unlinked, never followed.

    Every step is relative to a descriptor, and every directory is opened with ``O_NOFOLLOW``, so
    a path component swapped for a symlink after it was checked fails the open instead of leading
    out of the tree. A directory a tool left read-only is made owner-writable through its
    descriptor first.
    """
    info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=dir_fd)
        return
    child = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    try:
        os.fchmod(child, 0o700)
        for entry in os.listdir(child):
            _remove_at(child, entry)
    finally:
        os.close(child)
    os.rmdir(name, dir_fd=dir_fd)


class _TreeResidue:
    """Undo what one tool leaves in the shared head worktree before the next tool runs.

    The tools run one after another in one worktree. StrykerJS leaves ``.stryker-tmp/sandbox-*``
    when it fails, and knip then reports the copy, so what a tool saw depended on what ran before
    it and on a random folder name. The state taken at construction is the baseline: the linked
    dependency folders and the settings files the runner stripped. ``clear`` removes every
    untracked or ignored entry that is not in the baseline and puts back every tracked file the
    baseline did not already show as changed.

    The worktree is untrusted, so nothing here follows a symlink and nothing leaves the worktree:
    removal and restoring go through directory descriptors opened with ``O_NOFOLLOW``, and a
    tracked file is rewritten from the object database (the stored blob), which runs no filter,
    smudge or hook. The ``git status`` that finds the changes would run a configured clean filter
    on a file whose size and time match the index. It runs with the system and global git
    configuration switched off and, on git 2.40 or later, with the attributes read from the empty
    tree (``--attr-source``), so the reviewed tree names no filter and none runs, whether the
    driver is in the operator's global configuration or in the repository's own. On an older git
    the repository's own configuration is still read, and a filter driver defined there can run.
    ``subprocess_runner`` stops a tool's process group before it returns, so
    nothing it started is writing while this runs. A descendant that deliberately started its own
    session escapes that, as ``subprocess_runner`` documents; the descriptor-relative walk keeps
    such a process from steering a removal outside the worktree, but not from re-creating files.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root_real = os.path.realpath(root)
        self.env = {
            **os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_LITERAL_PATHSPECS": "1",
            "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.prefix: tuple[str, ...] = ()
        empty = self._git(["hash-object", "-t", "tree", os.devnull])
        if empty is not None:
            tree = empty.stdout.decode().strip()
            self.prefix = ("--attr-source", tree)
            if self._git(["status", "--porcelain=v1", "--ignore-submodules=all"]) is None:
                self.prefix = ()  # a git before 2.40 does not take --attr-source
        state = self._state()
        self.known: frozenset[str] = state[0] if state is not None else frozenset()
        self.changed: frozenset[str] = state[1] if state is not None else frozenset()
        self.readable = state is not None and _FD_SAFE

    def _git(self, args: Sequence[str]) -> subprocess.CompletedProcess[bytes] | None:
        try:
            result = subprocess.run(  # nosec B603
                ["git", *self.prefix, *_RESIDUE_GIT, *args],
                cwd=self.root, env=self.env, capture_output=True, check=False,
            )
        except OSError:
            return None
        return result if result.returncode == 0 else None

    def _state(self) -> tuple[frozenset[str], frozenset[str]] | None:
        """``(untracked and ignored names, changed tracked names)``, or None when git declined."""
        result = self._git(_RESIDUE_STATUS)
        if result is None:
            return None
        left: set[str] = set()
        changed: set[str] = set()
        entries = result.stdout.split(b"\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            index += 1
            if len(entry) < 4:
                continue
            code, name = entry[:2], os.fsdecode(entry[3:])
            if code[:1] in (b"R", b"C"):
                index += 1  # a rename or copy lists its source as the next entry
            if code in (b"??", b"!!"):
                left.add(name)
            else:
                changed.add(name)
        return frozenset(left), frozenset(changed)

    def clear(self, adapter_id: str, diagnostics_directory: Path | None = None) -> None:
        """Remove and restore what the tool that just ran left behind."""
        if not self.readable:
            return
        state = self._state()
        if state is None:
            return
        removed = sorted(
            name for name in state[0] - self.known
            if not self._is_build_cache(name) and self._remove(name)
        )
        restored = self._restore(sorted(state[1] - self.changed))
        if (removed or restored) and diagnostics_directory is not None:
            review_diagnostics.write_residue(
                diagnostics_directory, adapter_id, removed, restored
            )

    def _is_build_cache(self, name: str) -> bool:
        """A build-cache folder at the worktree root, which stays for the next tool."""
        if name.rstrip("/") not in _BUILD_CACHES:
            return False
        path = self.root / name.rstrip("/")
        return path.is_dir() and not path.is_symlink()

    def _parts(self, name: str) -> list[str] | None:
        parts = name.rstrip("/").split("/")
        if not parts or any(part in ("", ".", "..") or "\0" in part for part in parts):
            return None
        return parts

    def _open_parent(self, parts: Sequence[str], create: bool = False) -> int | None:
        """A descriptor for the folder holding ``parts[-1]``, every step opened without following."""
        try:
            fd = os.open(self.root_real, _DIR_FLAGS)
        except OSError:
            return None
        for part in parts[:-1]:
            try:
                try:
                    child = os.open(part, _DIR_FLAGS, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o777, dir_fd=fd)
                    child = os.open(part, _DIR_FLAGS, dir_fd=fd)
            except OSError:
                os.close(fd)
                return None
            os.close(fd)
            fd = child
        return fd

    def _remove(self, name: str) -> bool:
        """Delete one untracked or ignored entry inside the worktree. A symlink is unlinked."""
        parts = self._parts(name)
        if parts is None:
            return False
        fd = self._open_parent(parts)
        if fd is None:
            return False
        try:
            _remove_at(fd, parts[-1])
        except (OSError, RecursionError):
            return False
        finally:
            os.close(fd)
        return True

    def _restore(self, names: Sequence[str]) -> list[str]:
        """Put tracked files the tool changed back to the reviewed commit, from stored blobs."""
        restored: list[str] = []
        for start in range(0, len(names), _RESTORE_BATCH):
            batch = list(names[start:start + _RESTORE_BATCH])
            listed = self._git(["ls-tree", "-z", "HEAD", "--", *batch])
            if listed is None:
                continue
            for record in listed.stdout.split(b"\0"):
                header, _tab, raw = record.partition(b"\t")
                fields = header.split(b" ")
                if not raw or len(fields) != 3 or fields[1] != b"blob":
                    continue  # a submodule entry is not a file; nothing else changes here
                name = os.fsdecode(raw)
                blob = self._git(["cat-file", "blob", fields[2].decode()])
                if blob is not None and self._write(name, fields[0], blob.stdout):
                    restored.append(name)
        return restored

    def _write(self, name: str, mode: bytes, data: bytes) -> bool:
        """Write one tracked file, replacing whatever stands there. Nothing is followed."""
        parts = self._parts(name)
        if parts is None:
            return False
        fd = self._open_parent(parts, create=True)
        if fd is None:
            return False
        try:
            try:
                _remove_at(fd, parts[-1])
            except FileNotFoundError:
                pass
            if mode == b"120000":
                os.symlink(os.fsdecode(data), parts[-1], dir_fd=fd)
                return True
            handle = os.open(
                parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o755 if mode == b"100755" else 0o644, dir_fd=fd,
            )
            with os.fdopen(handle, "wb") as out:
                out.write(data)
            return True
        except (OSError, RecursionError):
            return False
        finally:
            os.close(fd)


def _remove_tree(path: Path) -> None:
    """Unlink a file or symlink, or remove a directory. Missing is fine."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _within_root(root: Path, path: Path) -> bool:
    """True when ``path`` resolves inside ``root``. Symlink escapes fail."""
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


@lru_cache(maxsize=1024)
def _rev(repo: Path, revision: str) -> str:
    result = _git(repo, ["rev-parse", revision])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


@lru_cache(maxsize=4096)
def _blob(repo: Path, revision: str, path: str) -> str | None:
    result = _git(repo, ["rev-parse", f"{revision}:{path}"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@lru_cache(maxsize=1024)
def _clean_tree(repo: Path, path: str) -> bool:
    """True when ``path`` matches HEAD with no staged, unstaged or untracked delta."""
    result = _git(repo, ["status", "--porcelain", "--", path])
    return result.returncode == 0 and not result.stdout.strip()


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
    ran: bool,
) -> None:
    target = _cache_path(home, adapter, version, base_sha, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = {"key": dict(key), "hits": [asdict(hit) for hit in hits], "ran": ran}
    target.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    target.chmod(0o600)


def _read_base_cache(
    home: Path,
    adapter: Adapter,
    version: str,
    base_sha: str,
    settings: str,
    key: Mapping[str, str],
) -> tuple[tuple[Hit, ...], bool] | None:
    """A miss leaves the file in place. A list, or a dict without ``ran``, is a miss."""
    target = _cache_path(home, adapter, version, base_sha, settings)
    if not target.is_file():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("key") != dict(key):
        return None
    if not isinstance(raw.get("ran"), bool):
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
    return tuple(hits), raw["ran"]


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
    run_parser.add_argument("--diagnostics-directory", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return run(
            args.repo, args.base, args.head, args.profile, args.output,
            home=args.home, builder=args.builder,
            diagnostics_directory=args.diagnostics_directory,
        )
    except Exception as exc:
        print(f"review tools: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
