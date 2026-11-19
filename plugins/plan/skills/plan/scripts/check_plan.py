#!/usr/bin/env python3
"""Check a saved plan for sections, file references, and placeholders.

The checker is read-only. It exits 0 when the plan is complete enough to hand
to a later session, and exits 1 with one finding per line otherwise.

A repo-relative path must exist on disk unless the same line marks it ``(new)``
or ``(create)``, or the word ``create`` introduces it. A marked path must stay
inside the repository. Its parent may be missing only when that parent, or a
closer ancestor, already exists or is itself marked as a new directory. The
repository root alone does not anchor a brand-new top-level directory; mark
that directory ``(new)`` as well.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SECTION_SLOTS: tuple[tuple[str, tuple[tuple[str, ...], ...]], ...] = (
    ("Summary", (("summary",),)),
    ("Non-Goals or Scope", (("non", "goals"), ("non", "goal"), ("scope",))),
    ("Key Decisions", (("key", "decisions"), ("key", "decision"), ("decisions",), ("decision",))),
    ("Units or Steps", (("units",), ("unit",), ("steps",), ("step",))),
    ("Verification or Tests", (("verification",), ("tests",), ("test",))),
)

PLACEHOLDERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bTBD\b", re.IGNORECASE), "TBD"),
    (re.compile(r"\bTODO\b", re.IGNORECASE), "TODO"),
    (re.compile(r"\bseveral files\b", re.IGNORECASE), '"several files"'),
)

BACKTICK = re.compile(r"`([^`\n]+)`")
BARE_PATH = re.compile(
    r"(?<![\w`./])((?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]*?)(?![\w/])"
)
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
MARKER_AFTER = re.compile(r"\(\s*(?:new|create)\s*\)", re.IGNORECASE)
CREATE_BEFORE = re.compile(r"\bcreate\b", re.IGNORECASE)
LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")
FENCE = re.compile(r"^\s*```")


def main(argv: list[str] | None = None) -> int:
    """Validate one plan file. ``--help`` exits 0 before any file is read."""
    parser = argparse.ArgumentParser(
        description=(
            "Check a saved plan markdown file for required sections, "
            "repo-relative file references, and placeholder text."
        )
    )
    parser.add_argument("plan", nargs="?", help="Path to the plan markdown file")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root used to resolve repo-relative paths (default: current directory)",
    )
    args = parser.parse_args(argv)
    if not args.plan:
        parser.error("a plan file is required")
    plan_path = Path(args.plan)
    if not plan_path.is_file():
        print(f"plan file not found: {plan_path}")
        return 1
    try:
        text = plan_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"plan file is not UTF-8: {plan_path}")
        return 1
    findings = check_text(text, args.root.resolve())
    for finding in findings:
        print(finding)
    return 1 if findings else 0


def check_text(text: str, root: Path) -> list[str]:
    """Return findings for ``text``. ``root`` is the repository the paths are relative to."""
    findings = _missing_sections(text)
    findings.extend(_placeholders(text))
    findings.extend(_paths(text, root))
    return findings


def _missing_sections(text: str) -> list[str]:
    headings = [_words(title) for title in _headings(text)]
    missing: list[str] = []
    for label, phrases in SECTION_SLOTS:
        if not any(_has_phrase(heading, phrase) for heading in headings for phrase in phrases):
            missing.append(f"missing section: {label}")
    return missing


def _placeholders(text: str) -> list[str]:
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, label in PLACEHOLDERS:
            if pattern.search(line):
                findings.append(f"line {number}: placeholder {label}")
    return findings


def _paths(text: str, root: Path) -> list[str]:
    references = _references(text)
    planned = {
        Path(path)
        for _number, path, marked, directory in references
        if marked and directory
    }
    findings: list[str] = []
    for number, path, marked, _directory in references:
        relative = Path(path)
        if not _inside_repository(relative):
            findings.append(f"line {number}: path escapes the repository: {path}")
            continue
        if (root / relative).exists():
            continue
        if not marked:
            findings.append(f"line {number}: unmarked path does not exist: {path}")
            continue
        if not _new_path_is_anchored(relative, root, planned):
            findings.append(
                f"line {number}: new path has no existing or planned parent: {path}"
            )
    return findings


def _references(text: str) -> list[tuple[int, str, bool, bool]]:
    """Each repo-relative reference as ``(line, path, marked_new, is_directory)``."""
    found: list[tuple[int, str, bool, bool]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        spans = _spans(line)
        for index, (start, end, raw) in enumerate(spans):
            normalized = _normalize(raw)
            if normalized is None:
                continue
            path, directory = normalized
            previous = spans[index - 1][1] if index else 0
            following = spans[index + 1][0] if index + 1 < len(spans) else len(line)
            before = line[previous:start]
            after = line[end:following]
            marked = bool(MARKER_AFTER.search(after) or CREATE_BEFORE.search(before))
            found.append((number, path, marked, directory))
    return found


def _spans(line: str) -> list[tuple[int, int, str]]:
    spans = [(match.start(1), match.end(1), match.group(1)) for match in BACKTICK.finditer(line)]
    for match in BARE_PATH.finditer(line):
        start, end = match.start(1), match.end(1)
        if any(start < span_end and end > span_start for span_start, span_end, _raw in spans):
            continue
        spans.append((start, end, match.group(1)))
    spans.sort()
    return spans


def _normalize(raw: str) -> tuple[str, bool] | None:
    """Return ``(repo-relative path, is_directory)``, or None when ``raw`` is not a path."""
    token = raw.strip()
    if not token or "://" in token or token.startswith(("<", "#")):
        return None
    directory = token.endswith("/")
    token = token.rstrip("/")
    while True:
        updated = LINE_SUFFIX.sub("", token)
        if updated == token:
            break
        token = updated
    token = token.rstrip(".,;:")
    if token.startswith("./"):
        token = token[2:]
    if not token or any(character in token for character in "*?<>| "):
        return None
    path = Path(token)
    if len(path.parts) == 1 and "." not in path.name and not directory:
        return None
    if len(path.parts) == 1 and "." not in path.name and directory:
        return token, True
    if "/" not in token and not directory and "." not in Path(token).name:
        return None
    return token, directory


def _inside_repository(relative: Path) -> bool:
    if relative.is_absolute() or not relative.parts:
        return False
    return ".." not in relative.parts


def _new_path_is_anchored(relative: Path, root: Path, planned: set[Path]) -> bool:
    """True when a parent exists on disk, or a missing parent was marked new.

    The repository root counts only for a file created directly at the root.
    A new top-level directory must be marked itself, so a typo such as
    ``plugnis/file.py (new)`` is still reported.
    """
    current = relative.parent
    if str(current) in ("", "."):
        return True
    while str(current) not in ("", "."):
        if current in planned or (root / current).is_dir():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent
    return False


def _headings(text: str) -> list[str]:
    titles: list[str] = []
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            titles.append(match.group(1))
    return titles


def _words(heading: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", heading.lower())


def _has_phrase(words: list[str], phrase: tuple[str, ...]) -> bool:
    width = len(phrase)
    return any(words[index : index + width] == list(phrase) for index in range(len(words) - width + 1))


if __name__ == "__main__":
    sys.exit(main())
