#!/usr/bin/env python3
"""Every-language review adapters, built from review-tools.yaml (issue 151).

Importing this module reads the yaml and builds adapter objects. It does not run a tool and it
does not download a rule pack.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

import review_formula
import review_tools
from review_tools import Adapter, Hit, ParseResult, RulePin, ScanContext, ToolGap

_JS_SKIP = frozenset({"package-lock.json", "npm-shrinkwrap.json"})
_JS_OK = frozenset({"pnpm-lock.yaml", "yarn.lock"})
#: A real scan prefixes the check id with the config path, which for the saga row
#: is a fresh temporary directory every run. The rule id is the trailing segment.
_SAGA_RULE_ID = re.compile(r"saga\.[A-Za-z0-9-]+$")
_WORD_SCORE = {"CRITICAL": 9.0, "HIGH": 7.0, "MEDIUM": 4.0, "LOW": 0.1}
_PATTERN_ROWS = tuple(f"correctness.pattern.{name}" for name in review_formula._PATTERN_CHECKS)

_ROWS: dict[str, tuple[str, ...]] = {
    "semgrep-security": ("security.scanner-high", "security.scanner-medium-low"),
    "semgrep-saga": _PATTERN_ROWS,
    "gitleaks": ("security.secret-in-diff",),
    "osv-scanner": ("security.dependency-high", "security.dependency-medium-low"),
    "jscpd": ("architecture-maintainability.duplicate",),
    "lizard": ("architecture-maintainability.complexity-dead-code-naming",),
    "coverage": ("testing.uncovered-branch",),
    "relocated-test": ("architecture-maintainability.relocated-run-fails",),
}


def _document() -> dict[str, object]:
    loaded = yaml.safe_load(review_tools.TOOL_LIST.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise review_tools.RunnerFailure(2, "review-tools.yaml must be an object")
    return loaded


def _semgrep_argv(context: ScanContext) -> list[str]:
    argv = ["semgrep", "scan", "--metrics=off", "--disable-nosem", "--disable-version-check", "--json"]
    for config in context.configs:
        argv.extend(["--config", str(config)])
    argv.append(str(context.root))
    return argv


def _invoke_semgrep_security(context: ScanContext) -> list[str]:
    if not context.configs:
        raise ToolGap("rule-cache-missing", "security.scanner-high")
    return _semgrep_argv(context)


def _invoke_semgrep_saga(context: ScanContext) -> list[str]:
    if not context.configs:
        raise ToolGap("known-gap", _PATTERN_ROWS[0])
    return _semgrep_argv(context)


def _parse_semgrep(text: str, *, saga: bool) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("semgrep output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("semgrep output must be an object")
    hits: list[Hit] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        start_obj = item.get("start")
        start = start_obj.get("line") if isinstance(start_obj, dict) else None
        end = (item.get("end") or {}).get("line") if isinstance(item.get("end"), dict) else start
        check_id = str(item.get("check_id") or "semgrep")
        if saga:
            bare = _SAGA_RULE_ID.search(check_id)
            check_id = bare.group(0) if bare else check_id
        path = str(item.get("path") or ".")
        message = str(extra.get("message") or f"Semgrep reported {check_id}.")
        metadata = extra.get("metadata") if isinstance(extra.get("metadata"), dict) else {}
        row = str(metadata.get("row") or "") if saga else ""
        harm = str(metadata.get("harm") or "") if saga else ""
        hits.append(Hit(
            rule_id=check_id,
            path=path,
            statement=" ".join(message.split()),
            anchor=check_id,
            level=None if saga or extra.get("severity") is None else str(extra.get("severity")),
            start=int(start) if isinstance(start, int) else None,
            end=int(end) if isinstance(end, int) else None,
            row=row or None,
            consequence=harm or None,
        ))
    return ParseResult(tuple(hits), problems=_semgrep_problems(data.get("errors")))


def _semgrep_problems(errors: object) -> tuple[str, ...]:
    """Path, or else type and level. The message can quote source, so it is never stored."""
    if not isinstance(errors, list):
        return ()
    problems: list[str] = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        path = error.get("path")
        if isinstance(path, str) and path.strip():
            problems.append(" ".join(path.split()))
            continue
        kind = str(error.get("type") or "")
        level = str(error.get("level") or "")
        text = " ".join(part for part in (kind, level) if part)
        problems.append(text or "semgrep")
    return tuple(problems)


def _parse_semgrep_security(text: str) -> ParseResult:
    return _parse_semgrep(text, saga=False)


def _parse_semgrep_saga(text: str) -> ParseResult:
    return _parse_semgrep(text, saga=True)


def _invoke_gitleaks(context: ScanContext) -> list[str]:
    config = review_tools.plugin_root() / "references" / "gitleaks.toml"
    return [
        "gitleaks", "detect",
        "--report-format", "json",
        "--report-path", "-",
        "--config", str(config),
        "--ignore-gitleaks-allow",
        str(context.root),
    ]


def _parse_gitleaks(text: str) -> ParseResult:
    """Read RuleID, File and the line range. Match and Secret are never copied."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("gitleaks output is not json") from exc
    if isinstance(data, dict):
        data = data.get("findings") or data.get("leaks") or []
    if not isinstance(data, list):
        raise ValueError("gitleaks output must be a list")
    hits: list[Hit] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("RuleID") or "gitleaks")
        path = str(item.get("File") or ".")
        start = item.get("StartLine")
        end = item.get("EndLine")
        hits.append(Hit(
            rule_id=rule_id,
            path=path,
            statement=review_tools._SECRET_STATEMENT,
            anchor=f"{rule_id} {path}",
            start=int(start) if isinstance(start, int) else None,
            end=int(end) if isinstance(end, int) else None,
            row="security.secret-in-diff",
        ))
    return ParseResult(tuple(hits))


_SCAN_LOCKFILES = frozenset({
    "pnpm-lock.yaml",
    "yarn.lock",
    "pubspec.lock",
    "mix.lock",
    "go.mod",
    "composer.lock",
    "Pipfile.lock",
    "poetry.lock",
    "pdm.lock",
    "requirements.txt",
    "renv.lock",
    "Gemfile.lock",
    "Cargo.lock",
    "conan.lock",
    "gradle.lockfile",
    "buildscript-gradle.lockfile",
})


def _invoke_osv(npm_audit: bool):
    """osv-scanner over every scannable lockfile. The npm-only gap stands only
    while no ``npm-audit`` row owns npm's lockfiles (issue 153)."""

    def invoke(context: ScanContext) -> list[str]:
        found = [path for path in _lockfiles(context.root) if path.name in _SCAN_LOCKFILES | _JS_SKIP]
        names = {path.name for path in found}
        scannable = [path for path in found if path.name not in _JS_SKIP]
        if (names & _JS_SKIP) and not (names & _JS_OK) and not scannable:
            if npm_audit:
                return []
            raise ToolGap("known-gap", "security.dependency-high")
        if not scannable:
            return []
        argv = ["osv-scanner", "scan", "source", "--format", "json"]
        for path in scannable:
            relative = path.relative_to(context.root).as_posix()
            token = f"requirements.txt:{relative}" if path.name == "requirements.txt" else relative
            argv.extend(["--lockfile", token])
        return argv

    return invoke


def _lockfiles(root: Path) -> list[Path]:
    names = _SCAN_LOCKFILES | _JS_SKIP
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name in names:
            found.append(path)
    return found


def _advisory_score(vuln: Mapping[str, object]) -> float | None:
    severities = vuln.get("severity")
    for item in severities if isinstance(severities, list) else []:
        if not isinstance(item, Mapping):
            continue
        score = item.get("score")
        if isinstance(score, bool):
            continue
        if isinstance(score, (int, float)):
            return float(score)
        if isinstance(score, str):
            try:
                return float(score)
            except ValueError:
                continue
    specific = vuln.get("database_specific")
    word = ""
    if isinstance(specific, Mapping):
        word = str(specific.get("severity") or "")
    return _WORD_SCORE.get(word.upper())


def _parse_osv(text: str) -> ParseResult:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("osv-scanner output is not json") from exc
    if not isinstance(data, dict):
        raise ValueError("osv-scanner output must be an object")
    hits: list[Hit] = []
    for result in data.get("results") or []:
        if not isinstance(result, dict):
            continue
        source = result.get("source") if isinstance(result.get("source"), dict) else {}
        lock_path = str(source.get("path") or ".")
        for package in result.get("packages") or []:
            if not isinstance(package, dict):
                continue
            for vuln in package.get("vulnerabilities") or []:
                if not isinstance(vuln, dict):
                    continue
                identifiers = []
                if vuln.get("id"):
                    identifiers.append(str(vuln["id"]))
                for alias in vuln.get("aliases") or []:
                    if alias and str(alias) not in identifiers:
                        identifiers.append(str(alias))
                score = _advisory_score(vuln)
                row = review_formula.dependency_row(score)
                canonical = identifiers[0] if identifiers else "advisory"
                hits.append(Hit(
                    rule_id=canonical,
                    path=lock_path,
                    statement=f"Dependency advisory {canonical}.",
                    anchor=canonical,
                    advisory_ids=tuple(identifiers),
                    score=score,
                    row=row,
                    whole_project=True,
                ))
    return ParseResult(tuple(hits))


def _invoke_jscpd(min_lines: int, min_tokens: int):
    def invoke(context: ScanContext) -> list[str]:
        argv = [
            "jscpd",
            "--min-lines", str(min_lines),
            "--min-tokens", str(min_tokens),
            "--reporters", "json",
            "--silent",
        ]
        if context.report_dir is not None:
            argv.extend(["--output", str(context.report_dir)])
        argv.append(str(context.root))
        return argv
    return invoke


def _parse_jscpd(min_lines: int, min_tokens: int):
    def parse(text: str) -> ParseResult:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("jscpd output is not json") from exc
        if not isinstance(data, dict):
            raise ValueError("jscpd output must be an object")
        hits: list[Hit] = []
        for item in data.get("duplicates") or []:
            if not isinstance(item, dict):
                continue
            lines = int(item.get("lines") or 0)
            tokens = int(item.get("tokens") or 0)
            if lines < min_lines or tokens < min_tokens:
                continue
            first = item.get("firstFile") if isinstance(item.get("firstFile"), dict) else {}
            second = item.get("secondFile") if isinstance(item.get("secondFile"), dict) else {}
            first_name = str(first.get("name") or ".")
            second_name = str(second.get("name") or ".")
            anchor = hashlib.sha256(f"{first_name}\n{second_name}".encode()).hexdigest()[:16]
            hits.append(Hit(
                rule_id=anchor,
                path=first_name,
                statement=f"Duplicated lines in {first_name} and {second_name}.",
                anchor=anchor,
                row="architecture-maintainability.duplicate",
                whole_project=True,
            ))
        return ParseResult(tuple(hits))
    return parse


def _invoke_lizard(cyclomatic: int):
    def invoke(context: ScanContext) -> list[str]:
        return ["lizard", "-C", str(cyclomatic), "--csv", str(context.root)]
    return invoke


def _parse_lizard(cyclomatic: int):
    def parse(text: str) -> ParseResult:
        reader = csv.reader(io.StringIO(text))
        hits: list[Hit] = []
        for cells in reader:
            if not cells or cells[0] == "nloc":
                continue
            if len(cells) < 9:
                continue
            try:
                complexity = int(cells[1])
                start = int(cells[7])
                end = int(cells[8])
            except ValueError as exc:
                raise ValueError("lizard output is not the expected csv") from exc
            if complexity < cyclomatic:
                continue
            path = cells[5]
            function = cells[6] or None
            hits.append(Hit(
                rule_id=function or path,
                path=path,
                statement=(
                    f"Function {function or path} in {path} "
                    f"has cyclomatic complexity {complexity}."
                ),
                anchor=function or path,
                start=start,
                end=end,
                function=function,
                row="architecture-maintainability.complexity-dead-code-naming",
            ))
        return ParseResult(tuple(hits))
    return parse


def _rules(row: Mapping[str, object]) -> tuple[RulePin, ...]:
    rules = row.get("rules") or []
    if not isinstance(rules, list):
        return ()
    pins = []
    for entry in rules:
        if not isinstance(entry, dict):
            continue
        pins.append(RulePin(
            pack=entry.get("pack"),
            sha256=entry.get("sha256"),
            path=entry.get("path"),
        ))
    return tuple(pins)


def _level_map(row: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    mapping = row.get("level_map") or {}
    if not isinstance(mapping, dict):
        return ()
    return tuple((str(key), str(value)) for key, value in mapping.items())


def _build(document: Mapping[str, object]) -> list[Adapter]:
    tools = document.get("tools")
    if not isinstance(tools, list):
        raise review_tools.RunnerFailure(2, "review-tools.yaml tools must be a list")
    thresholds = document.get("thresholds") if isinstance(document.get("thresholds"), dict) else {}
    jscpd = thresholds.get("jscpd") if isinstance(thresholds.get("jscpd"), dict) else {}
    lizard = thresholds.get("lizard") if isinstance(thresholds.get("lizard"), dict) else {}
    min_lines = int(jscpd.get("min_lines") or 5)
    min_tokens = int(jscpd.get("min_tokens") or 50)
    cyclomatic = int(lizard.get("cyclomatic") or 15)
    npm_audit = any(
        isinstance(row, dict) and str(row.get("id") or "") == "npm-audit"
        for row in tools
    )
    invoke = {
        "semgrep-security": _invoke_semgrep_security,
        "semgrep-saga": _invoke_semgrep_saga,
        "gitleaks": _invoke_gitleaks,
        "osv-scanner": _invoke_osv(npm_audit),
        "jscpd": _invoke_jscpd(min_lines, min_tokens),
        "lizard": _invoke_lizard(cyclomatic),
        "coverage": lambda _context: [],
        "relocated-test": lambda _context: [],
    }
    parse = {
        "semgrep-security": _parse_semgrep_security,
        "semgrep-saga": _parse_semgrep_saga,
        "gitleaks": _parse_gitleaks,
        "osv-scanner": _parse_osv,
        "jscpd": _parse_jscpd(min_lines, min_tokens),
        "lizard": _parse_lizard(cyclomatic),
        "coverage": lambda _text: ParseResult(),
        "relocated-test": lambda _text: ParseResult(),
    }
    built: list[Adapter] = []
    for row in tools:
        if not isinstance(row, dict):
            continue
        tool_id = str(row.get("id") or "")
        if tool_id not in invoke:
            continue
        gap = row.get("gap_until_present")
        built.append(Adapter(
            id=tool_id,
            tool=str(row.get("tool") or ""),
            invoke=invoke[tool_id],
            parse=parse[tool_id],
            languages=tuple(str(item) for item in (row.get("languages") or ["*"])),
            rows=_ROWS[tool_id],
            comparison=str(row.get("comparison") or "lines"),
            lens=str(row.get("lens") or "correctness"),
            type_checker=bool(row.get("type_checker")),
            mutation=bool(row.get("mutation")),
            mode=str(row.get("mode") or "report"),
            timeout_seconds=int(row.get("timeout_seconds") or 120),
            platforms=tuple(str(item) for item in (row.get("platforms") or ())),
            env_dirs=tuple(str(item) for item in (row.get("env_dirs") or ())),
            lockfiles=tuple(str(item) for item in (row.get("lockfiles") or ())),
            version_args=tuple(str(item) for item in (row.get("version_args") or ("--version",))),
            default_version=str(row.get("default_version") or "not-recorded"),
            gap_path=str(gap) if isinstance(gap, str) else None,
            gap_rows=_PATTERN_ROWS if tool_id == "semgrep-saga" else (),
            curated_rules=tuple(str(item) for item in (row.get("curated_block_rules") or ())),
            level_map=_level_map(row),
            rules=_rules(row),
        ))
    return built


ADAPTERS: tuple[Adapter, ...] = tuple(_build(_document()))
