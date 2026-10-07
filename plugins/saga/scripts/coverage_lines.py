#!/usr/bin/env python3
"""Changed-line coverage for LCOV, Cobertura XML, and coverage.py JSON (issue 151).

The module takes a ``Change`` from ``review_diff``. It does not call git. Branch data wins. A
report with no branch data for a changed file falls back to lines and is marked degraded.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from review_diff import Change

_CONDITION = re.compile(r"(\d+(?:\.\d+)?)%")


@dataclass(frozen=True)
class FileReport:
    """One file. ``branch_uncovered is None`` means the file has no branch data."""

    path: str
    branch_uncovered: frozenset[int] | None
    line_uncovered: frozenset[int]


@dataclass(frozen=True)
class Report:
    """A coverage report reduced to uncovered lines."""

    files: tuple[FileReport, ...]

    def by_path(self) -> dict[str, FileReport]:
        return {item.path: item for item in self.files}


@dataclass(frozen=True)
class CoverageNumbers:
    """What the runner turns into findings and one measurement."""

    uncovered: frozenset[tuple[str, int]]
    degraded: bool
    covered: int
    total: int


def parse_lcov(text: str) -> Report:
    """``BRDA`` means branch data. Otherwise ``DA`` hit counts are lines."""
    files: list[FileReport] = []
    path = ""
    da_uncovered: set[int] = set()
    branches: dict[int, list[str]] = {}
    saw_branch = False

    def finish() -> None:
        if not path:
            return
        if saw_branch:
            uncovered = frozenset(
                line
                for line, taken in branches.items()
                if any(item in {"0", "-"} for item in taken)
            )
            files.append(FileReport(path, uncovered, frozenset(da_uncovered)))
        else:
            files.append(FileReport(path, None, frozenset(da_uncovered)))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            finish()
            path = line[3:]
            da_uncovered = set()
            branches = {}
            saw_branch = False
        elif line.startswith("DA:"):
            number, hits = line[3:].split(",")[:2]
            if int(float(hits)) == 0:
                da_uncovered.add(int(number))
        elif line.startswith("BRDA:"):
            saw_branch = True
            parts = line[5:].split(",")
            if len(parts) >= 4:
                branches.setdefault(int(parts[0]), []).append(parts[3])
        elif line == "end_of_record":
            finish()
            path = ""
    finish()
    return Report(files=tuple(files))


def parse_cobertura(text: str) -> Report:
    """A line with ``branch="true"`` or a ``conditions`` child is branch data."""
    root = ET.fromstring(text)
    grouped: dict[str, list[ET.Element]] = {}
    for element in root.iter("class"):
        filename = element.get("filename") or ""
        grouped.setdefault(filename, []).extend(element.iter("line"))
    files: list[FileReport] = []
    for path, lines in grouped.items():
        branch_uncovered: set[int] = set()
        line_uncovered: set[int] = set()
        saw_branch = False
        for element in lines:
            number = int(element.get("number") or "0")
            hits = int(float(element.get("hits") or "0"))
            has_branch = element.get("branch") == "true" or element.find("conditions") is not None
            if has_branch:
                saw_branch = True
                if not _branch_covered(element):
                    branch_uncovered.add(number)
            elif hits == 0:
                line_uncovered.add(number)
        files.append(
            FileReport(
                path,
                frozenset(branch_uncovered) if saw_branch else None,
                frozenset(line_uncovered),
            )
        )
    return Report(files=tuple(files))


def parse_coverage_json(text: str) -> Report:
    """``missing_branches`` present, even empty, is branch data. Otherwise ``missing_lines``."""
    payload = json.loads(text)
    files: list[FileReport] = []
    for path, body in (payload.get("files") or {}).items():
        missing_lines = frozenset(int(item) for item in body.get("missing_lines") or ())
        if "missing_branches" in body:
            uncovered = frozenset(int(item[0]) for item in body.get("missing_branches") or ())
            files.append(FileReport(path, uncovered, missing_lines))
        else:
            files.append(FileReport(path, None, missing_lines))
    return Report(files=tuple(files))


def resolve_report(name: str, directory: Path) -> Path:
    """A coverage file inside ``directory``.

    An absolute path, a ``..`` part, and a symlink that resolves outside ``directory`` are refused.
    """
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"coverage report {name!r} is outside the relocated directory")
    root = directory.resolve()
    candidate = (directory / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"coverage report {name!r} is outside the relocated directory")
    return candidate


def parse_report(path: Path) -> Report:
    """Pick a parser from the suffix, then from the text."""
    text = path.read_text(encoding="utf-8")
    name = path.name.lower()
    if name.endswith(".json"):
        return parse_coverage_json(text)
    if name.endswith(".xml"):
        return parse_cobertura(text)
    if name.endswith(".lcov") or name == "lcov.info":
        return parse_lcov(text)
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return parse_coverage_json(text)
    if stripped.startswith("<"):
        return parse_cobertura(text)
    return parse_lcov(text)


def uncovered_changed(report: Report, change: Change) -> CoverageNumbers:
    """Uncovered added or modified lines. No branch data on a changed file degrades the report."""
    known = report.by_path()
    changed = [
        item
        for item in change.files
        if item.status in {"added", "modified", "renamed"} and item.lines
    ]
    degraded = any(
        item.path not in known or known[item.path].branch_uncovered is None for item in changed
    )
    uncovered: set[tuple[str, int]] = set()
    total = 0
    for item in changed:
        total += len(item.lines)
        found = known.get(item.path)
        if not degraded and found is not None and found.branch_uncovered is not None:
            missing = found.branch_uncovered
        elif found is not None:
            missing = found.line_uncovered
        else:
            missing = item.lines
        uncovered.update((item.path, line) for line in item.lines & missing)
    return CoverageNumbers(frozenset(uncovered), degraded, total - len(uncovered), total)


def _branch_covered(element: ET.Element) -> bool:
    text = element.get("condition-coverage") or ""
    if text:
        return _percent_complete(text)
    conditions = element.find("conditions")
    if conditions is not None:
        coverages = [child.get("coverage") or "" for child in list(conditions)]
        if coverages:
            return all(_percent_complete(item) for item in coverages)
    return element.get("hits") not in {None, "0"}


def _percent_complete(text: str) -> bool:
    match = _CONDITION.search(text)
    if match is None:
        return False
    return float(match.group(1)) >= 100.0
