"""Optional private attempt telemetry; never an input to review packet hashes."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

MAX_BYTES = 256 * 1024
MAX_FILES = 8
_METADATA_RESERVE = 8192


def _read_owned(root: Path, relative: str, limit: int) -> bytes | None:
    """Read a regular file through no-follow directory descriptors, or decline."""
    if "\0" in relative:
        return None
    try:
        os.fsencode(relative)
    except UnicodeEncodeError:
        return None
    parts = relative.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts) or "\\" in relative:
        return None
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return None
    if os.open not in os.supports_dir_fd:
        return None
    directory: int | None = None
    descriptor: int | None = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            return handle.read(limit)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


@dataclass(frozen=True)
class AttemptRecord:
    schema: str
    adapter: str
    label: str
    attempt: Literal["initial", "retry"]
    status: Literal["succeeded", "failed", "skipped"]
    reason: str | None
    exit_code: int | None
    elapsed_seconds: float
    remaining_budget_seconds: float | None
    artifacts: dict[str, dict[str, int | bool]]
    rejected_logs: int
    errors: tuple[str, ...]


@dataclass
class Attempt:
    directory: Path
    adapter: str
    label: str
    attempt: Literal["initial", "retry"]
    remaining_budget_seconds: float | None
    started: float = field(default_factory=time.monotonic)
    artifacts: dict[str, dict[str, int | bool]] = field(default_factory=dict)
    rejected_logs: int = 0
    retained: int = 0
    errors: list[str] = field(default_factory=list)

    def note(self, reason: str) -> None:
        if reason not in self.errors:
            self.errors.append(reason)

    @classmethod
    def create(
        cls, root: Path, adapter: str, label: str,
        attempt: Literal["initial", "retry"], deadline: float | None,
    ) -> Attempt:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o777 != 0o700:
            raise ValueError("diagnostics directory must be a private mode-0700 directory")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ValueError("diagnostics directory must belong to the current user")
        directory = Path(tempfile.mkdtemp(prefix=f"{adapter}-{attempt}-", dir=root))
        left = None if deadline is None else max(0.0, deadline - time.monotonic())
        return cls(directory, adapter, label, attempt, left)

    def keep(self, name: str, data: bytes, *, truncated: bool = False) -> None:
        if len(self.artifacts) >= MAX_FILES - 1:
            return
        available = min(65536, max(0, MAX_BYTES - _METADATA_RESERVE - self.retained))
        kept = data[:available]
        # Reserve even a failed write's allowance: a partial file must not let
        # subsequent artifacts exceed either bound.
        self.retained += len(kept)
        self.artifacts[name] = {"bytes": 0, "truncated": truncated or len(data) > len(kept)}
        try:
            descriptor = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(kept)
        except OSError:
            self.artifacts[name]["capture_failed"] = True
            self.note("artifact-write-failed")
            return
        self.artifacts[name]["bytes"] = len(kept)

    def console(self, stdout: str | bytes | None, stderr: str | bytes | None) -> None:
        for name, data in (("stdout.txt", stdout), ("stderr.txt", stderr)):
            value = data.encode("utf-8", errors="replace") if isinstance(data, str) else data
            self.keep(name, value or b"")

    def logs(self, root: Path) -> None:
        # The tool report is untrusted, including every path it supplies.
        report = _read_owned(root, "mutants.out/outcomes.json", 65537)
        if report is None:
            self.note("report-unavailable-or-refused")
            return
        self.keep("outcomes.json", report[:65536], truncated=len(report) > 65536)
        if len(report) > 65536:
            self.note("report-truncated")
            return
        try:
            payload = json.loads(report)
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.note("report-unparseable")
            return
        outcomes = payload.get("outcomes") if isinstance(payload, dict) else None
        if not isinstance(outcomes, list):
            self.note("report-unparseable")
            return
        for entry in outcomes:
            if not isinstance(entry, dict) or entry.get("scenario") != "Baseline":
                continue
            relative = entry.get("log_path")
            if not isinstance(relative, str):
                continue
            if len(self.artifacts) >= MAX_FILES - 1:
                break
            data = _read_owned(root, "mutants.out/" + relative, 65537)
            if data is None:
                self.rejected_logs += 1
                self.note("baseline-log-unavailable-or-refused")
            else:
                self.keep(f"baseline-{len(self.artifacts)}.log", data[:65536], truncated=len(data) > 65536)

    def finish(
        self, status: Literal["succeeded", "failed", "skipped"], reason: str | None,
        exit_code: int | None = None,
    ) -> None:
        record = AttemptRecord(
            "review_diagnostics.v1", self.adapter, self.label, self.attempt, status,
            reason, exit_code, max(0.0, time.monotonic() - self.started),
            self.remaining_budget_seconds, self.artifacts, self.rejected_logs,
            tuple(self.errors),
        )
        data = (json.dumps(asdict(record), indent=2, sort_keys=True) + "\n").encode()
        if len(data) > _METADATA_RESERVE:
            print("review diagnostics: metadata exceeds its bound", file=sys.stderr)
            return
        try:
            descriptor = os.open(self.directory / "attempt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
        except OSError:
            print("review diagnostics: metadata write failed", file=sys.stderr)
