#!/usr/bin/env python3
"""
SessionStart hook: surface a stale default-branch warning (and auto-fix when safe).

After a squash-merge lands on ``origin/<default>``, the local default branch is
silently behind until explicitly fast-forwarded — a failure mode that has cost
builds (#shipped-on-origin-not-in-stale-local-tree). This hook detects that
state at session start and either auto-fast-forwards (only when you are cleanly
ON the default branch) or warns, injecting the result as SessionStart
``additionalContext``.

Generalized — runs in ANY git repo
-----------------------------------
The saga plugin is DISTRIBUTED and installs at user scope, so this hook fires in
EVERY repo. Rather than gate on a repo-local tool, it is fully self-contained and
generic. Preconditions (each failure → exit 0 SILENT):
  1. CWD is inside a git repo (``git rev-parse --show-toplevel``).
  2. An ``origin`` remote exists (``git remote get-url origin``).
  3. The default branch is determinable (see below).
It no longer depends on ``tools/stale_main_guard.py`` (that remains the repo-local
manual tool / R18 artifact).

Default-branch detection (generic — never hardcoded to ``main``)
----------------------------------------------------------------
``git symbolic-ref --short refs/remotes/origin/HEAD`` → strip the leading
``origin/``. If that fails, probe ``origin/main`` then ``origin/master`` via
``git show-ref --verify``. If none resolve → exit 0 silent.

Auto-fast-forward policy (the chosen behavior)
----------------------------------------------
If the local default branch is behind ``origin/<default>``:
  - AUTO-FF WHEN SAFE: if the current branch IS the default branch AND the tree
    is clean → ``git merge --ff-only origin/<default>`` and confirm. Being ON the
    default branch means you hold its checkout (git forbids the same branch in two
    worktrees), so this is inherently worktree-safe.
  - OTHERWISE (feature branch, dirty, or a linked worktree) → WARN ONLY; mutate
    nothing.

Output
------
When there is a message (ff-confirmation or warning), emit the official
SessionStart JSON shape and nothing otherwise:
  {"hookSpecificOutput": {"hookEventName": "SessionStart",
                          "additionalContext": "<message>"}}

Properties (all by design):
  - NON-blocking: always exits 0 (SessionStart cannot block anyway).
  - QUIET on error: any subprocess error/timeout degrades to no output.

Exit codes:
  0 — always.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _run(args: list[str], *, cwd: str | None, timeout: int = 15) -> tuple[int, str, str]:
    """Run a git subprocess; return (returncode, stdout, stderr). Degrades quietly."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except Exception:
        return 1, "", "error"
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _read_cwd_from_stdin() -> str | None:
    """
    Read the SessionStart hook JSON from stdin and return its ``cwd`` field.

    Tolerates empty/malformed stdin by returning None (caller falls back to the
    process CWD).
    """
    try:
        raw = sys.stdin.read()
    except Exception:
        return None
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None


def _repo_root(cwd: str | None) -> str | None:
    """Return the git repository root for ``cwd``, or None if not a git repo."""
    rc, root, _ = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, timeout=5)
    if rc != 0 or not root:
        return None
    return root


def _has_origin_remote(cwd: str | None) -> bool:
    """Return True if an ``origin`` remote is configured."""
    rc, url, _ = _run(["git", "remote", "get-url", "origin"], cwd=cwd, timeout=5)
    return rc == 0 and bool(url)


def _default_branch(cwd: str | None) -> str | None:
    """
    Resolve the repo's default branch generically (never hardcoded to ``main``).

    Strategy:
      1. ``git symbolic-ref --short refs/remotes/origin/HEAD`` → strip ``origin/``.
      2. Fall back to probing ``origin/main`` then ``origin/master`` for an
         existing remote-tracking ref.
    Returns the bare branch name (e.g. ``main``), or None if undeterminable.
    """
    rc, ref, _ = _run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=cwd,
        timeout=5,
    )
    if rc == 0 and ref:
        # e.g. "origin/main" -> "main"
        return ref[len("origin/") :] if ref.startswith("origin/") else ref

    for candidate in ("main", "master"):
        rc, _, _ = _run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{candidate}"],
            cwd=cwd,
            timeout=5,
        )
        if rc == 0:
            return candidate
    return None


def _commits_behind(branch: str, cwd: str | None) -> int | None:
    """
    Return how many commits local ``<branch>`` is behind ``origin/<branch>``.

    Returns None if the comparison cannot be made or the count is unparseable.
    """
    rc, stdout, _ = _run(
        ["git", "rev-list", "--count", f"{branch}..origin/{branch}"],
        cwd=cwd,
    )
    if rc != 0:
        return None
    try:
        return int(stdout)
    except ValueError:
        return None


def _current_branch(cwd: str | None) -> str | None:
    """Return the currently checked-out branch, or None on detached HEAD / error."""
    rc, stdout, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    if rc != 0 or not stdout:
        return None
    return stdout if stdout != "HEAD" else None  # 'HEAD' = detached


def _working_tree_is_clean(cwd: str | None) -> bool:
    """Return True if there are no uncommitted changes (staged or unstaged)."""
    rc, stdout, _ = _run(["git", "status", "--porcelain"], cwd=cwd)
    if rc != 0:
        return False  # Treat unknown state as dirty (conservative)
    return stdout == ""


def _fast_forward(branch: str, cwd: str | None) -> bool:
    """Fast-forward the current (== default) branch to ``origin/<branch>``."""
    rc, _, _ = _run(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=cwd)
    return rc == 0


def _compute_message(cwd: str | None) -> str | None:
    """
    Run the full stale-default-branch logic. Returns the context message to
    surface, or None when there is nothing to say (silent).
    """
    if _repo_root(cwd) is None:
        return None  # Not a git repo.
    if not _has_origin_remote(cwd):
        return None  # No origin remote.

    branch = _default_branch(cwd)
    if branch is None:
        return None  # Default branch undeterminable.

    # Refresh remote-tracking refs. Degrade quietly on failure (offline): the
    # behind-count below still compares against whatever origin/<branch> we have.
    _run(["git", "fetch", "origin"], cwd=cwd, timeout=20)

    behind = _commits_behind(branch, cwd)
    if not behind:  # None or 0
        return None

    current = _current_branch(cwd)
    clean = _working_tree_is_clean(cwd)
    ff_cmd = f"git fetch origin {branch}:{branch}"

    if current == branch and clean:
        # On the default branch with a clean tree — safe to fast-forward.
        if _fast_forward(branch, cwd):
            return (
                f"[stale-main] Auto-fast-forwarded '{branch}' by {behind} commit(s) "
                f"to match origin/{branch}."
            )
        # FF failed unexpectedly — fall through to a warning rather than lie.
        return (
            f"[stale-main] WARNING: local '{branch}' is {behind} commit(s) behind "
            f"origin/{branch} and auto-fast-forward failed. Run: {ff_cmd}"
        )

    # Feature branch, dirty tree, or a linked worktree — warn only, mutate nothing.
    return (
        f"[stale-main] WARNING: local '{branch}' is {behind} commit(s) behind "
        f"origin/{branch}. Fast-forward when ready: {ff_cmd}"
    )


def main() -> None:
    cwd = _read_cwd_from_stdin()

    message = _compute_message(cwd)
    if not message:
        # Nothing to surface (silent precondition failure, up to date, or error).
        sys.exit(0)

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
