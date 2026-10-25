"""Optional private attempt telemetry; never an input to review packet hashes."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

MAX_BYTES = 256 * 1024
MAX_FILES = 8
_METADATA_RESERVE = 8192
_OMISSION = b"\n\n[... middle bytes omitted; see attempt.json ...]\n\n"
ArtifactValue = int | bool | str | None


@dataclass(frozen=True)
class TextSample:
    data: bytes
    observed_bytes: int
    head_bytes: int
    tail_bytes: int
    mode: Literal["full", "head-tail", "tail-only", "no-text"]
    source_changed: bool = False

    def metadata(self) -> dict[str, ArtifactValue]:
        omitted = self.head_bytes + self.tail_bytes < self.observed_bytes
        return {
            "sample_mode": self.mode,
            "observed_bytes": self.observed_bytes,
            "original_bytes": None if self.source_changed else self.observed_bytes,
            "omitted_start": None if self.source_changed else self.head_bytes,
            "omitted_end": None if self.source_changed else self.observed_bytes - self.tail_bytes,
            "source_changed": self.source_changed,
            "complete": not omitted and not self.source_changed,
            "truncated": omitted or self.source_changed,
        }


def _text_layout(size: int, limit: int) -> tuple[int, int, bytes]:
    if size <= limit:
        return size, 0, b""
    if limit < len(_OMISSION) + 2:
        return 0, limit, b""
    payload = limit - len(_OMISSION)
    return payload // 2, payload - payload // 2, _OMISSION


def _text_sample(prefix: bytes, suffix: bytes, size: int, limit: int) -> TextSample:
    head, tail, separator = _text_layout(size, limit)
    mode: Literal["full", "head-tail", "tail-only", "no-text"]
    mode = "full" if size <= limit else "head-tail" if separator else "tail-only" if tail else "no-text"
    data = prefix[:head] + separator + (suffix[-tail:] if tail else b"")
    return TextSample(data, size, head, tail, mode)


def _console_sample(data: str | bytes, limit: int) -> TextSample:
    if isinstance(data, bytes):
        return _text_sample(data, data, len(data), limit)
    # Encoding a large captured string must not allocate another full-size copy.
    prefix = bytearray()
    suffix = bytearray()
    size = 0
    for offset in range(0, len(data), 4096):
        chunk = data[offset:offset + 4096].encode("utf-8", errors="replace")
        size += len(chunk)
        prefix.extend(chunk[:max(0, limit - len(prefix))])
        suffix.extend(chunk)
        if len(suffix) > limit:
            del suffix[:len(suffix) - limit]
    return _text_sample(bytes(prefix), bytes(suffix), size, limit)


def _open_owned(root: Path, relative: str) -> BinaryIO | None:
    """Open a regular file through no-follow directory descriptors, or decline."""
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
        handle = os.fdopen(descriptor, "rb")
        descriptor = None
        return handle
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def _read_owned(root: Path, relative: str, limit: int) -> bytes | None:
    handle = _open_owned(root, relative)
    if handle is None:
        return None
    try:
        with handle:
            return handle.read(limit)
    except OSError:
        return None


def _read_owned_text(root: Path, relative: str, limit: int) -> TextSample | None:
    handle = _open_owned(root, relative)
    if handle is None:
        return None
    try:
        with handle:
            before = os.fstat(handle.fileno())
            head, tail, _separator = _text_layout(before.st_size, limit)
            prefix = handle.read(head)
            if tail:
                handle.seek(before.st_size - tail)
                suffix = handle.read(tail)
            else:
                suffix = b""
            after = os.fstat(handle.fileno())
        sample = _text_sample(prefix, suffix, before.st_size, limit)
        changed = (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ) or len(prefix) != head or len(suffix) != tail
        return TextSample(sample.data, before.st_size, head, tail, sample.mode, changed)
    except OSError:
        return None


def _private_root(root: Path) -> None:
    """Create the diagnostics directory if needed, and refuse one that is not private."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o777 != 0o700:
        raise ValueError("diagnostics directory must be a private mode-0700 directory")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("diagnostics directory must belong to the current user")


#: The most names one residue record lists; the counts are always exact.
MAX_RESIDUE_NAMES = 200


def write_residue(
    root: Path, adapter: str, removed: Sequence[str], restored: Sequence[str],
) -> None:
    """Record which entries the runner removed or restored after ``adapter`` ran.

    The names can reveal paths in the reviewed repository, so they live only in this private
    directory and never in a record, a hash or a packet.
    """
    try:
        _private_root(root)
        directory = Path(tempfile.mkdtemp(prefix=f"{adapter}-residue-", dir=root))
        body = {
            "schema": "review_diagnostics.v1",
            "adapter": adapter,
            "removed_count": len(removed),
            "removed": list(removed[:MAX_RESIDUE_NAMES]),
            "restored_count": len(restored),
            "restored": list(restored[:MAX_RESIDUE_NAMES]),
        }
        data = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
        descriptor = os.open(directory / "residue.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except (OSError, ValueError):
        print("review diagnostics: residue record not written", file=sys.stderr)


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
    artifacts: dict[str, dict[str, ArtifactValue]]
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
    artifacts: dict[str, dict[str, ArtifactValue]] = field(default_factory=dict)
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
        _private_root(root)
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

    def _text_limit(self) -> int:
        return min(65536, max(0, MAX_BYTES - _METADATA_RESERVE - self.retained))

    def _keep_text(self, name: str, sample: TextSample) -> None:
        self.keep(name, sample.data)
        if name in self.artifacts:
            self.artifacts[name].update(sample.metadata())
            if self.artifacts[name].get("capture_failed"):
                self.artifacts[name]["complete"] = False

    def console(self, stdout: str | bytes | None, stderr: str | bytes | None) -> None:
        for name, data in (("stdout.txt", stdout), ("stderr.txt", stderr)):
            self._keep_text(name, _console_sample(data or b"", self._text_limit()))

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
            sample = _read_owned_text(root, "mutants.out/" + relative, self._text_limit())
            if sample is None:
                self.rejected_logs += 1
                self.note("baseline-log-unavailable-or-refused")
            else:
                self._keep_text(f"baseline-{len(self.artifacts)}.log", sample)

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
