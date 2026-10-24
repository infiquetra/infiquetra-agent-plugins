#!/usr/bin/env python3
"""One diff reader for the changed-line filter, the coverage adapter, and C6's sweep (issue 151).

``read`` runs ``git diff`` as an argument vector and returns the added or modified lines in the
new file. Consumers take the ``Change``. They do not parse a diff.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path

# The end of the one range that stands for every line of a file (a renamed file's old path).
WHOLE_FILE = 2**31 - 1

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class ReviewDiffError(ValueError):
    """Base or head is not a commit, or git could not produce the diff."""


@dataclass(frozen=True)
class FileChange:
    """One path in the diff. ``lines`` are added or modified lines in the new file.

    ``removed_at`` holds the new-file lines on either side of a hunk that only removed lines. They
    are not added or modified, so ``lines`` leaves them out; ``Change.touched`` counts them.
    """

    path: str
    status: str
    lines: frozenset[int]
    old_path: str | None = None
    removed_at: frozenset[int] = frozenset()


@dataclass(frozen=True)
class Change:
    """The whole diff. A pure rename and a binary file contribute no lines."""

    files: tuple[FileChange, ...]

    def lines_for(self, path: str) -> frozenset[int]:
        """Added or modified lines of ``path``.

        A deletion, a binary and an unknown path are empty.
        """
        for item in self.files:
            if item.path == path and item.status in {"added", "modified", "renamed"}:
                return item.lines
        return frozenset()

    def touched(self) -> dict[str, list[list[int]]]:
        """``{path: [[start, end], ...]}``: the lines a finding can fairly be said to be about.

        Added or modified lines, plus the line on either side of a removal, because a finding
        about code that a change removed is anchored beside the gap. Inclusive ranges, sorted and
        merged; a path with none is left out. This is what ``review_formula`` reads as the
        changed lines. Added, modified and renamed files are covered.

        A renamed file's old path is listed too, as one range over the whole file, because the old
        file's line numbers do not map onto the new ones: a finding that cites the old path is
        then never placed outside the change.
        """
        touched: dict[str, list[list[int]]] = {}
        for item in self.files:
            if item.status not in {"added", "modified", "renamed"}:
                continue
            ranges: list[list[int]] = []
            for line in sorted(item.lines | item.removed_at):
                if ranges and line <= ranges[-1][1] + 1:
                    ranges[-1][1] = max(ranges[-1][1], line)
                else:
                    ranges.append([line, line])
            if ranges:
                touched[item.path] = ranges
            if item.status == "renamed" and item.old_path and item.old_path != item.path:
                touched[item.old_path] = [[1, WHOLE_FILE]]
        return dict(sorted(touched.items()))


def read(repo: Path | str, base: str, head: str) -> Change:
    """The change ``git diff`` reports between ``base`` and ``head``."""
    root = Path(repo)
    _require_commit(root, base)
    _require_commit(root, head)
    raw = _git(root, ["diff", "--raw", "-z", "--find-renames", base, head])
    patch = _git(root, ["diff", "-U0", "--no-color", "--find-renames", base, head])
    added, binary, removed = _parse_patch(patch)
    files: list[FileChange] = []
    for record in _parse_raw(raw):
        path = record["path"]
        code = record["status"]
        if path in binary:
            status = "binary"
            lines: frozenset[int] = frozenset()
        elif code == "D":
            status = "deleted"
            lines = frozenset()
        elif code.startswith("R"):
            status = "renamed"
            lines = frozenset(added.get(path, ()))
        elif code == "A" or code.startswith("C"):
            status = "added"
            lines = frozenset(added.get(path, ()))
        else:
            status = "modified"
            lines = frozenset(added.get(path, ()))
        around = (
            frozenset(removed.get(path, ())) if status in {"modified", "renamed"} else frozenset()
        )
        files.append(FileChange(
            path=path, status=status, lines=lines, old_path=record["old"], removed_at=around,
        ))
    return Change(files=tuple(files))


def _require_commit(repo: Path, revision: str) -> None:
    proc = subprocess.run(  # nosec B603
        ["git", "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ReviewDiffError(f"{revision} is not a commit")


def _git(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(  # nosec B603
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "git diff failed").strip()
        raise ReviewDiffError(detail)
    return proc.stdout


def _parse_raw(blob: str) -> list[dict[str, str | None]]:
    parts = blob.split("\0")
    if parts and parts[-1] == "":
        parts.pop()
    records: list[dict[str, str | None]] = []
    index = 0
    while index < len(parts):
        header = parts[index]
        index += 1
        if not header.startswith(":"):
            continue
        status = header[1:].split()[4]
        path = parts[index]
        index += 1
        old: str | None = None
        if status[:1] in {"R", "C"}:
            old = path
            path = parts[index]
            index += 1
        records.append({"status": status, "path": path, "old": old})
    return records


def _parse_patch(text: str) -> tuple[dict[str, set[int]], set[str], dict[str, set[int]]]:
    added: dict[str, set[int]] = {}
    removed: dict[str, set[int]] = {}
    binary: set[str] = set()
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = _new_path(line)
        elif line.startswith("rename to "):
            current = line[len("rename to "):]
        elif line.startswith("Binary files ") and current is not None:
            binary.add(current)
        elif line.startswith("@@") and current is not None:
            match = _HUNK.match(line)
            if match is None:
                continue
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            if count:
                added.setdefault(current, set()).update(range(start, start + count))
            else:
                # Lines were removed after new line ``start``: the gap sits between it and the next.
                removed.setdefault(current, set()).update({max(start, 1), start + 1})
    return added, binary, removed


def _new_path(header: str) -> str:
    """The ``b/`` path of a ``diff --git a/... b/...`` header."""
    marker = " b/"
    if marker not in header:
        return header.split()[-1]
    return header.split(marker, 1)[1]
