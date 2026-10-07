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

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class ReviewDiffError(ValueError):
    """Base or head is not a commit, or git could not produce the diff."""


@dataclass(frozen=True)
class FileChange:
    """One path in the diff. ``lines`` are added or modified lines in the new file."""

    path: str
    status: str
    lines: frozenset[int]
    old_path: str | None = None


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


def read(repo: Path | str, base: str, head: str) -> Change:
    """The change ``git diff`` reports between ``base`` and ``head``."""
    root = Path(repo)
    _require_commit(root, base)
    _require_commit(root, head)
    raw = _git(root, ["diff", "--raw", "-z", "--find-renames", base, head])
    patch = _git(root, ["diff", "-U0", "--no-color", "--find-renames", base, head])
    added, binary = _parse_patch(patch)
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
        files.append(FileChange(path=path, status=status, lines=lines, old_path=record["old"]))
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


def _parse_patch(text: str) -> tuple[dict[str, set[int]], set[str]]:
    added: dict[str, set[int]] = {}
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
    return added, binary


def _new_path(header: str) -> str:
    """The ``b/`` path of a ``diff --git a/... b/...`` header."""
    marker = " b/"
    if marker not in header:
        return header.split()[-1]
    return header.split(marker, 1)[1]
