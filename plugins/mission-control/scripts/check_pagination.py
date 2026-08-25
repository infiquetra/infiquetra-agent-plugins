#!/usr/bin/env python3
"""Pagination-completeness lint for mission-control's GitHub list calls (#424, T9-F4-5).

Scans mission-control's own Python scripts and skill/agent/command reference
docs for `gh` list invocations that fetch a bounded page of results with no
cursor loop and no explicit `--limit` guard -- the call-site shape named in
the grounding brief's session-mining synthesis as a recurring fleet defect:
"mission-control board/field drift ... item-list pagination silently
truncating at 200 of 375 items"
(docs/plans/2026-07-03-plugin-fleet-grounding-brief.md §7, pattern 3).

Three guarded patterns, one violation kind each:

  1. Raw CLI list calls (``gh project item-list ...``) with no ``--limit``
     on the same line -- ``gh``'s own default page size silently caps
     output at 30 items with no visible truncation signal.
  2. Bare REST list fetches (``_rest_get(...per_page=...)``) instead of the
     shared ``_rest_list_paginated()`` helper (``sdlc_manager.py``, #424)
     that loops pages until a short page proves the list is exhausted.
  3. A GraphQL query literal that sets a page-size arg (``first:``) without
     checking ``hasNextPage`` -- such a query has no way to detect that it
     stopped short of the full list.

Exit 0 = no unguarded call sites found; exit 1 = at least one violation.

Usage::

    python3 check_pagination.py             # scans mission-control's own tree
    python3 check_pagination.py <path> ...   # scans explicit paths instead
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_MISSION_CONTROL_DIR = _SCRIPTS_DIR.parent

DEFAULT_ROOTS = (
    _MISSION_CONTROL_DIR / "scripts",
    _MISSION_CONTROL_DIR / "skills",
    _MISSION_CONTROL_DIR / "commands",
    _MISSION_CONTROL_DIR / "agents",
)

# This lint script's own docstring/body legitimately mentions the guarded
# patterns by name; exclude it from its own scan.
_SELF_PATH = Path(__file__).resolve()

RAW_ITEM_LIST_RE = re.compile(r"gh\s+project\s+item-list\b")
BARE_REST_PAGE_RE = re.compile(r"_rest_get\([^)]*per_page=")
GRAPHQL_FIRST_RE = re.compile(r"\bfirst\s*:\s*\d+")
COMMENT_LINE_RE = re.compile(r"^\s*#")
SUPPRESS_MARKER = "# pagination-lint: allow"

SCAN_SUFFIXES = (".py", ".md")

# How many lines (including the match line) to search for a `--limit` guard,
# so a `--limit` on a wrapped/continuation line still counts as a guard.
_INVOCATION_WINDOW = 3


def iter_files(roots: list[Path]) -> list[Path]:
    """Collect scannable files under `roots`, de-duplicated, order-preserving."""
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for suffix in SCAN_SUFFIXES:
            files.extend(sorted(root.rglob(f"*{suffix}")))

    seen: set[Path] = set()
    ordered: list[Path] = []
    for f in files:
        resolved = f.resolve()
        if resolved == _SELF_PATH or resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(f)
    return ordered


def _extract_graphql_queries(path: Path, text: str) -> list[tuple[int, str, int, int]]:
    """Extract individual GraphQL query literals / fenced code blocks.

    Each entry is `(1-based start line, block text, block start offset, block
    end offset)`. The offsets let `check_file` tell which `first:` occurrences
    the extractor actually placed inside a query, so an occurrence it could not
    parse falls back to the whole-file check instead of going unchecked."""
    queries: list[tuple[int, str, int, int]] = []

    if path.suffix == ".md":
        # Any fence language, not a whitelist: an unpaginated query pasted into
        # a `json`/`text`/untagged fence is the same defect as one in a
        # `graphql` fence, and a whitelist also lets the regex mis-window from
        # a *closing* fence when it skips an untagged opener.
        for match in re.finditer(r"```[^\n`]*\n(.*?)\n```", text, re.DOTALL):
            lineno = text[: match.start()].count("\n") + 1
            queries.append((lineno, match.group(1), match.start(1), match.end(1)))
        return queries

    # The delimiter must match itself (backreference), not merely be *a* triple
    # quote: an alternation lets an opening triple-double-quote close on a
    # triple-single-quote occurring inside it, which desynchronizes every
    # literal after it in the file.
    for match in re.finditer(r'("""|\'\'\')(.*?)\1', text, re.DOTALL):
        lineno = text[: match.start()].count("\n") + 1
        queries.append((lineno, match.group(2), match.start(2), match.end(2)))

    for match in re.finditer(r'(?<!\\)(["\'])(.*?)(?<!\\)\1', text):
        block = match.group(2)
        if "\n" not in block and GRAPHQL_FIRST_RE.search(block):
            lineno = text[: match.start()].count("\n") + 1
            queries.append((lineno, block, match.start(2), match.end(2)))

    return queries


def check_file(path: Path) -> list[str]:
    """Return human-readable violations for one file; empty list = clean."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    violations: list[str] = []

    for lineno, line in enumerate(lines, start=1):
        if SUPPRESS_MARKER in line:
            continue
        if RAW_ITEM_LIST_RE.search(line):
            # A comment line mentioning the command by name (e.g. explaining its
            # flattening behavior) is documentation, not an invocation to guard.
            if COMMENT_LINE_RE.match(line):
                continue
            window = "\n".join(lines[lineno - 1 : lineno - 1 + _INVOCATION_WINDOW])
            if "--limit" not in window:
                violations.append(
                    f"{path}:{lineno}: unguarded `gh project item-list` (no cursor "
                    f"loop, no --limit) -- add --limit N or route through a "
                    f"documented pagination loop"
                )
        if BARE_REST_PAGE_RE.search(line):
            violations.append(
                f"{path}:{lineno}: bare per_page REST fetch via `_rest_get` -- use "
                f"`_rest_list_paginated()` (sdlc_manager.py, #424) instead"
            )

    extracted_queries = _extract_graphql_queries(path, text)
    for q_lineno, query_text, _start, _end in extracted_queries:
        if SUPPRESS_MARKER in query_text:
            continue
        if GRAPHQL_FIRST_RE.search(query_text) and "hasNextPage" not in query_text:
            violations.append(
                f"{path}:{q_lineno}: GraphQL query sets a page-size arg (`first:`) "
                f"without checking `hasNextPage` -- the query cannot detect truncation"
            )

    # Fail safe, never fail open. A `first:` the extractor could not place inside
    # any query block still gets the original whole-file check, so an unparsed
    # literal shape can never silently switch the GraphQL guard off for the rest
    # of the file -- the exact blindness the query-scoped rewrite exists to end.
    spans = [(start, end) for _, _, start, end in extracted_queries]
    uncovered = [
        match
        for match in GRAPHQL_FIRST_RE.finditer(text)
        if not any(start <= match.start() and match.end() <= end for start, end in spans)
    ]
    if uncovered and "hasNextPage" not in text and SUPPRESS_MARKER not in text:
        lineno = text[: uncovered[0].start()].count("\n") + 1
        violations.append(
            f"{path}:{lineno}: GraphQL query sets a page-size arg (`first:`) without "
            f"checking `hasNextPage` -- the query cannot detect truncation"
        )

    return violations


def run_lint(roots: list[Path] | None = None) -> list[str]:
    """Return all violations across `roots` (defaults to mission-control's own tree)."""
    all_violations: list[str] = []
    for path in iter_files(roots if roots is not None else list(DEFAULT_ROOTS)):
        all_violations.extend(check_file(path))
    return all_violations


def main(argv: list[str]) -> int:
    roots = [Path(p) for p in argv] if argv else None
    violations = run_lint(roots)

    if violations:
        for v in violations:
            print(f"FAIL {v}")
        print(f"\npagination lint FAILED: {len(violations)} unguarded call site(s)")
        return 1

    print("pagination lint passed: no unguarded list call sites found")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
