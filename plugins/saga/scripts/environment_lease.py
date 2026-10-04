#!/usr/bin/env python3
"""The one lease saga holds: a shared non-production environment, one run at a time (issue #99).

Pre-review testing U4 deploys the combined branch to the environment the repository declares, and
on a *shared* environment only one run may hold it at a time (issue #91, operator ruling 3). The
lease that enforces that must be visible to every host that can deploy, so a lock file in one
checkout is not enough. This module keeps it on the git remote every deploying host already pushes
to, as the reference ``refs/saga/leases/<name>``:

* **Acquire is a compare-and-swap push.** The holder is written as the message of a commit on the
  empty tree, and pushed with ``--force-with-lease=<ref>:`` -- an empty expected value, which means
  "only if the reference does not exist". The push sends that expected value and the server's ref
  transaction compares it, so two hosts racing for the lease get exactly one winner.
* **Release is a compare-and-swap delete** with the object id the holder was given when it
  acquired. Someone else's lease is never deleted by a release.
* **A lease belongs to exactly one invocation, and nobody takes over a lease it does not hold**
  (issues #139 and #140). The holder names the repository, the issue, the host, the pass number
  and an ``invocation`` nonce drawn once per build-loop invocation. Acquire never replaces an
  existing holder, whether it is another run or an earlier invocation of the same run: a pass
  number cannot prove the earlier invocation finished, because any other invocation of the run
  that records a pass moves the count while the holder is still deploying. Every holder is
  ``HELD``; the waiting invocation reports it, and a dead one is released by the operator with
  ``release --expect``.
* **A stale lease is reported, never broken.** The holder carries its start time and the bound the
  pass expected to finish within. Past the bound it is described as ``STALE`` with the exact
  command that releases it, and the operator decides. Clock skew between hosts therefore only
  changes the wording of a report, never who holds the environment.

Pushes run with ``--no-verify``, so a repository's own pre-push hook (which may run its whole test
suite) does not run for a lease, and with ``GIT_TERMINAL_PROMPT=0`` and an inert author, so a host
with no git identity still works and a missing credential fails rather than prompts.

This is not the run record's lock. The record still takes only the advisory file lock described in
``references/run-record.md``; nothing here is ever written into the record's file.

The holder's ``host`` is a short label: ``SAGA_LEASE_HOLDER`` when set, else the host name's first
label. A public repository's lease reference is world-readable, so nothing more goes in it.

House pattern: an injectable runner shaped like ``subprocess.run``, an injectable clock, no I/O at
import, and one-line refusals on standard error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import socket
import subprocess  # nosec B404  (git is the lease store; argument vectors only, never a shell)
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

#: Where every lease lives on the remote.
REF_PREFIX = "refs/saga/leases/"

#: Where a fetched lease is kept locally so its commit can be read. Never pushed.
OBSERVED_PREFIX = "refs/saga/observed-leases/"

#: The holder payload's schema.
LEASE_SCHEMA = "environment_lease.v1"

DEFAULT_REMOTE = "origin"
DEFAULT_NAME = "shared-nonprod"

#: A lease name is one path component of a reference: lowercase, short, no slashes.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

ACQUIRED = "acquired"
HELD = "held"
COULD_NOT_EXECUTE = "could-not-execute"
RELEASED = "released"
NOT_HELD = "not-held"

#: Inert identity for the lease commit, so a host or a CI runner with no git identity still works.
_IDENTITY = {
    "GIT_AUTHOR_NAME": "saga environment lease",
    "GIT_AUTHOR_EMAIL": "saga-lease@example.invalid",
    "GIT_COMMITTER_NAME": "saga environment lease",
    "GIT_COMMITTER_EMAIL": "saga-lease@example.invalid",
}

#: Seconds one git call may take.
GIT_TIMEOUT_SECONDS = 120

Runner = Callable[..., Any]


class LeaseError(ValueError):
    """A refusal this module owns: a bad name or an unusable remote."""


def ref_for(name: str) -> str:
    """The remote reference for lease *name*. Refuses a name that is not one path component."""
    if not NAME_RE.match(name or ""):
        raise LeaseError(
            f"lease name {name!r} is not usable: lowercase letters, digits, '.', '_' and '-', "
            "starting with a letter or digit, at most 63 characters"
        )
    return REF_PREFIX + name


def host_label() -> str:
    """The short label the holder records for this host."""
    override = os.environ.get("SAGA_LEASE_HOLDER", "").strip()
    if override:
        return override
    return socket.gethostname().split(".")[0] or "unknown-host"


def iso_utc(now: datetime) -> str:
    """*now* as an ISO-8601 UTC timestamp to the second, the holder's started_at shape."""
    return now.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_invocation() -> str:
    """A fresh nonce naming one build-loop invocation, the only one that may release its lease."""
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# The holder and the results.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseHolder:
    """Who holds the environment: the run, the revision under test, the host, and since when."""

    repo: str
    issue: int
    revision: str
    host: str
    started_at: str
    bound_seconds: int
    pass_number: int = 0
    invocation: str = ""
    schema: str = LEASE_SCHEMA

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> LeaseHolder | dict[str, Any]:
        """The holder, or ``{"unparseable": True, "raw": ...}`` for a payload this cannot read.

        An unreadable payload is reported as a held lease, never treated as free: something put a
        reference there, and deleting what it does not understand is how a lease gets broken.
        """
        try:
            raw = json.loads(text)
            return cls(
                repo=str(raw["repo"]),
                issue=int(raw["issue"]),
                revision=str(raw["revision"]),
                host=str(raw["host"]),
                started_at=str(raw["started_at"]),
                bound_seconds=int(raw["bound_seconds"]),
                pass_number=int(raw.get("pass_number", 0)),
                invocation=str(raw.get("invocation", "")),
                schema=str(raw.get("schema", LEASE_SCHEMA)),
            )
        except (ValueError, KeyError, TypeError):
            return {"unparseable": True, "raw": text.strip()[:500]}

    def same_run(self, other: LeaseHolder) -> bool:
        return self.repo == other.repo and self.issue == other.issue


@dataclass(frozen=True)
class LeaseState:
    """What the remote says about one lease. ``held`` false means the reference does not exist."""

    name: str
    held: bool
    token: str | None = None
    holder: LeaseHolder | dict[str, Any] | None = None


@dataclass(frozen=True)
class AcquireResult:
    status: str
    token: str | None = None
    holder: LeaseHolder | dict[str, Any] | None = None
    detail: str = ""

    @property
    def acquired(self) -> bool:
        return self.status == ACQUIRED


@dataclass(frozen=True)
class ReleaseResult:
    status: str
    detail: str = ""


class LeaseBackend(Protocol):
    """Where leases live. The git backend is the real one; tests inject a fake."""

    def acquire(self, name: str, holder: LeaseHolder) -> AcquireResult: ...

    def read(self, name: str) -> LeaseState: ...

    def release(self, name: str, token: str) -> ReleaseResult: ...


# ---------------------------------------------------------------------------
# Staleness and the one-line description.
# ---------------------------------------------------------------------------


def _parse_time(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def age_seconds(holder: LeaseHolder, now: datetime) -> int | None:
    started = _parse_time(holder.started_at)
    if started is None:
        return None
    return int((now - started).total_seconds())


def is_stale(holder: LeaseHolder | dict[str, Any] | None, now: datetime) -> bool:
    """Whether *holder* has outlived the bound it declared. An unreadable holder is not judged."""
    if not isinstance(holder, LeaseHolder):
        return False
    age = age_seconds(holder, now)
    return age is not None and age > holder.bound_seconds


def release_command(name: str, token: str | None, *, remote: str, repo_root: str = ".") -> str:
    return (
        f"python3 plugins/saga/scripts/environment_lease.py --repo-root {repo_root} "
        f"--remote {remote} release --name {name} --expect {token or '<object id>'}"
    )


def describe(
    state: LeaseState, now: datetime, *, remote: str = DEFAULT_REMOTE, repo_root: str = "."
) -> str:
    """One line naming who holds the lease and since when, and what to do if it is stale."""
    ref = REF_PREFIX + state.name
    if not state.held:
        return f"{ref} on {remote} is free"
    holder = state.holder
    if not isinstance(holder, LeaseHolder):
        raw = holder.get("raw", "") if isinstance(holder, dict) else ""
        return (
            f"{ref} on {remote} is held by a payload this saga cannot read ({raw[:80]!r}); "
            "it is never deleted automatically. If nothing is deploying, release it: "
            + release_command(state.name, state.token, remote=remote, repo_root=repo_root)
        )
    age = age_seconds(holder, now)
    age_text = f"{age}s" if age is not None else "unknown"
    who = f"{holder.repo}#{holder.issue}"
    if holder.pass_number:
        who += f" pass {holder.pass_number}"
    if holder.invocation:
        who += f" (invocation {holder.invocation})"
    line = (
        f"{ref} on {remote} is held by {who} at revision "
        f"{holder.revision[:12]} from host {holder.host}, since {holder.started_at} "
        f"(age {age_text}, bound {holder.bound_seconds}s)"
    )
    if is_stale(holder, now):
        line += (
            " — STALE: past its bound. If that run is dead, release it: "
            + release_command(state.name, state.token, remote=remote, repo_root=repo_root)
        )
    return line


# ---------------------------------------------------------------------------
# The git backend.
# ---------------------------------------------------------------------------


def _out(result: Any) -> str:
    return str(getattr(result, "stdout", "") or "").strip()


def _err(result: Any) -> str:
    """The line of git's output that says what went wrong: its first ``fatal:`` or ``error:``."""
    text = str(getattr(result, "stderr", "") or "").strip() or _out(result)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    named = [line for line in lines if line.startswith(("fatal:", "error:", "!"))]
    if named:
        return named[0]
    return lines[-1] if lines else "unknown error"


def _ok(result: Any) -> bool:
    return getattr(result, "returncode", 1) == 0


class GitRefLeaseBackend:
    """Leases as references on a git remote, read and written with plain ``git``."""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        remote: str = DEFAULT_REMOTE,
        runner: Runner | None = None,
    ) -> None:
        self.repo_root = str(repo_root)
        self.remote = remote
        self._runner = runner

    def _git(self, *argv: str, stdin: str | None = None) -> Any:
        call = self._runner if self._runner is not None else subprocess.run
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **_IDENTITY}
        try:
            return call(
                ["git", "-C", self.repo_root, *argv],
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                env=env,
                input=stdin if stdin is not None else "",
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(argv, 127, "", f"git could not run: {exc}")

    def check_remote(self) -> str | None:
        """``None`` when *remote* is usable, else why not. A URL is accepted as it stands."""
        if "://" in self.remote or self.remote.startswith("/") or "@" in self.remote:
            return None
        result = self._git("remote", "get-url", self.remote)
        if _ok(result):
            return None
        return (
            f"the lease remote {self.remote!r} is not configured in {self.repo_root}: a shared "
            "environment's lease must live where every deploying host can see it"
        )

    def _commit(self, holder: LeaseHolder) -> tuple[str | None, str]:
        tree = self._git("mktree", stdin="")
        if not _ok(tree):
            return None, f"git mktree failed: {_err(tree)}"
        # A nonce paragraph keeps two identical holders written in the same second from making
        # the same object id, which the remote would accept as an up-to-date push for both.
        commit = self._git(
            "commit-tree",
            _out(tree),
            "-m",
            holder.to_json(),
            "-m",
            f"nonce: {secrets.token_hex(8)}",
        )
        if not _ok(commit):
            return None, f"git commit-tree failed: {_err(commit)}"
        return _out(commit), ""

    def _push(self, *refspec: str, expect: str) -> Any:
        return self._git(
            "push",
            "--no-verify",
            "--porcelain",
            f"--force-with-lease={expect}",
            self.remote,
            *refspec,
        )

    def read(self, name: str) -> LeaseState:
        ref = ref_for(name)
        listed = self._git("ls-remote", self.remote, ref)
        if not _ok(listed):
            raise LeaseError(f"cannot read {ref} on {self.remote}: {_err(listed)}")
        line = next((row for row in _out(listed).splitlines() if row.endswith(ref)), "")
        if not line:
            return LeaseState(name=name, held=False)
        token = line.split()[0]
        fetched = self._git(
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            self.remote,
            f"+{ref}:{OBSERVED_PREFIX}{name}",
        )
        if not _ok(fetched):
            return LeaseState(
                name=name,
                held=True,
                token=token,
                holder={"unparseable": True, "raw": f"could not fetch: {_err(fetched)}"},
            )
        body = self._git("cat-file", "commit", token)
        message = _out(body).split("\n\n", 1)[1] if "\n\n" in _out(body) else ""
        # The holder is the message's first paragraph; a nonce paragraph follows it.
        message = message.split("\n\n", 1)[0]
        return LeaseState(name=name, held=True, token=token, holder=LeaseHolder.from_json(message))

    def acquire(self, name: str, holder: LeaseHolder) -> AcquireResult:
        ref = ref_for(name)
        oid, problem = self._commit(holder)
        if oid is None:
            return AcquireResult(COULD_NOT_EXECUTE, detail=problem)
        pushed = self._push(f"{oid}:{ref}", expect=f"{ref}:")
        if _ok(pushed):
            return AcquireResult(ACQUIRED, token=oid, holder=holder)
        # The push failed. Whether that is a lost race or a broken remote is read, not guessed.
        try:
            state = self.read(name)
        except LeaseError as exc:
            return AcquireResult(COULD_NOT_EXECUTE, detail=f"{_err(pushed)}; {exc}")
        if not state.held:
            return AcquireResult(
                COULD_NOT_EXECUTE, detail=f"the lease push to {self.remote} failed: {_err(pushed)}"
            )
        # Any holder, this run's earlier invocations included, is held: nothing proves it is done.
        return AcquireResult(HELD, token=state.token, holder=state.holder)

    def release(self, name: str, token: str) -> ReleaseResult:
        ref = ref_for(name)
        pushed = self._push(f":{ref}", expect=f"{ref}:{token}")
        if _ok(pushed):
            return ReleaseResult(RELEASED)
        try:
            state = self.read(name)
        except LeaseError as exc:
            return ReleaseResult(COULD_NOT_EXECUTE, detail=f"{_err(pushed)}; {exc}")
        if not state.held or state.token != token:
            return ReleaseResult(
                NOT_HELD,
                detail=f"{ref} is not held at {token[:12]}; nothing was deleted",
            )
        return ReleaseResult(COULD_NOT_EXECUTE, detail=f"the release push failed: {_err(pushed)}")


# ---------------------------------------------------------------------------
# Command line: status and the operator's release. Acquiring is the build loop's.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="environment_lease.py",
        description=(
            "Read or release the lease on a shared non-production environment, kept as "
            f"{REF_PREFIX}<name> on a git remote. The build loop acquires it."
        ),
    )
    parser.add_argument("--repo-root", default=".", help="A checkout whose remote holds the lease.")
    parser.add_argument("--remote", default=DEFAULT_REMOTE, help="The remote, or its URL.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    status = sub.add_parser("status", help="Print who holds the lease, as JSON.")
    status.add_argument("--name", default=DEFAULT_NAME)
    release = sub.add_parser(
        "release", help="Delete the lease, only if it is still at --expect (compare-and-swap)."
    )
    release.add_argument("--name", default=DEFAULT_NAME)
    release.add_argument("--expect", required=True, help="The object id the lease must still hold.")
    return parser


def _holder_json(holder: LeaseHolder | dict[str, Any] | None) -> Any:
    if isinstance(holder, LeaseHolder):
        return asdict(holder)
    return holder


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner | None = None,
    now: Callable[[], datetime] = utc_now,
) -> int:
    args = build_parser().parse_args(argv)
    backend = GitRefLeaseBackend(args.repo_root, remote=args.remote, runner=runner)
    try:
        if args.cmd == "status":
            state = backend.read(args.name)
            moment = now()
            print(
                json.dumps(
                    {
                        "name": state.name,
                        "ref": ref_for(state.name),
                        "remote": args.remote,
                        "held": state.held,
                        "token": state.token,
                        "holder": _holder_json(state.holder),
                        "stale": is_stale(state.holder, moment),
                        "description": describe(
                            state, moment, remote=args.remote, repo_root=args.repo_root
                        ),
                    },
                    indent=1,
                )
            )
            return 0
        result = backend.release(args.name, args.expect)
        if result.status == RELEASED:
            print(f"released {ref_for(args.name)} on {args.remote} at {args.expect[:12]}")
            return 0
        print(f"environment_lease: {result.status}: {result.detail}", file=sys.stderr)
        return 2
    except LeaseError as exc:
        print(f"environment_lease: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
