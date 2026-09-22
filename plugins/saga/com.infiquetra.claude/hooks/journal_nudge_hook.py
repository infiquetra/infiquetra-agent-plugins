#!/usr/bin/env python3
"""
PostToolUse hook: nudge when a commit that earned a journal entry omits one.

Fires after a Bash tool call that issues a `git commit`.  When the committed
diff touches code files, includes NO `docs/engineering-journal/` path, and
either the message starts with `feat`/`fix` or a model judges the commit to
have earned an entry, prints a one-line nudge to stderr.

The `feat`/`fix` prefix is a FLOOR, never a ceiling (issue 1036): the model is
asked only when the prefix did not already nudge, and it can only add a nudge,
never suppress one.  A `refactor` or `perf` commit carrying a non-obvious
mechanism is exactly the commit whose learning is worth writing down, and the
prefix rule passed every one of them in silence.

Properties (all by design):
  - NON-blocking: always exits 0.
  - NON-writing: never creates or edits journal files.
  - Cross-repo-safe: degrades quietly when the journal dir is absent or git
    is unavailable.
  - Silent on any model failure: a missing key, an error, a timeout or a slow
    vendor produces no output at all and costs at most `_JUDGMENT_DEADLINE`
    seconds.  `INFIQUETRA_TYPESAFE_JOURNAL_NUDGE=off` skips the call entirely.
  - Sends the commit's own message and file list, never a session transcript,
    a diff, or customer content.

Exit codes:
  0 — always (nudge or not, pass or error).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Commit message prefixes that warrant a journal nudge.
_FEAT_FIX_RE = re.compile(r"^(feat|fix)\b", re.IGNORECASE)

# Extensions considered "code" (not pure docs/config/chore).
_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".sh",
        ".bash",
        ".go",
        ".rs",
        ".rb",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".cpp",
        ".h",
        ".cs",
        ".php",
        ".r",
        ".sql",
    }
)

# Prefix that marks a journal entry in the committed diff.
_JOURNAL_PREFIX = "docs/engineering-journal/"

# The switch that turns the model judgment off entirely.  Default is on; any of
# these values turns it off.
_JUDGMENT_ENV = "INFIQUETRA_TYPESAFE_JOURNAL_NUDGE"
_OFF_VALUES = frozenset({"off", "0", "false", "no"})

# One attempt, two seconds, three seconds of total wall clock.  A hook runs
# after every commit, so an unreachable vendor must cost a noticeable pause at
# most -- never a retry ladder, and never a blocked terminal.
_JUDGMENT_TIMEOUT = 2.0
_JUDGMENT_ATTEMPTS = 1
_JUDGMENT_DEADLINE = 3.0


def _is_git_commit_command(command: str) -> bool:
    """Return True if the shell command performs a `git commit`."""
    # Match plain `git commit` and `git -C <dir> commit` variants.
    return bool(re.search(r"\bgit\b.*\bcommit\b", command))


def _extract_commit_message(command: str) -> str:
    """
    Extract the commit message from a git commit command string.

    Handles `-m "msg"`, `-m 'msg'`, and heredoc-via-$() forms.
    Returns '' if not found.
    """
    # -m "..." or -m '...' (greedy across newlines)
    m = re.search(r"-m\s+(['\"])(.*?)\1", command, re.DOTALL)
    if m:
        return m.group(2)
    # -m msg (no quotes, single token)
    m2 = re.search(r"-m\s+(\S+)", command)
    if m2:
        return m2.group(1)
    return ""


def _parse_git_dash_c(command: str) -> str | None:
    """Return the path from `git -C <path>` if present, else None."""
    m = re.search(r"\bgit\s+-C\s+(['\"]?)([^'\" ]+)\1", command)
    if m:
        return m.group(2)
    return None


def _git_show_files(cwd: str | None) -> list[str]:
    """
    Return the list of file paths touched by HEAD (the just-committed commit).

    Returns [] on any error (git unavailable, not a repo, etc.).
    """
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        # --format= suppresses the commit header; output is one filename per line.
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def _journal_dir_exists(cwd: str | None) -> bool:
    """Return True if docs/engineering-journal/ exists in the repo root."""
    base = Path(cwd) if cwd else Path.cwd()
    # Try to find the repo root via git rev-parse for cross-repo accuracy.
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            base = Path(result.stdout.strip())
    except Exception:
        pass

    return (base / "docs" / "engineering-journal").is_dir()


def _has_code_files(files: list[str]) -> bool:
    """Return True if at least one committed file has a code extension."""
    return any(Path(f).suffix.lower() in _CODE_EXTENSIONS for f in files)


def _has_journal_entry(files: list[str]) -> bool:
    """Return True if at least one committed file is under docs/engineering-journal/."""
    return any(f.startswith(_JOURNAL_PREFIX) for f in files)


def _commit_message(cwd: str | None) -> str:
    """Return HEAD's own commit message, or '' on any error.

    `_extract_commit_message` reads the message out of the shell command and
    only handles the `-m` forms, so a here-document or `-F` commit yields an
    empty string.  The model is asked about the real message; the `feat`/`fix`
    floor keeps reading the parsed one, so nothing about today's behaviour
    depends on this.
    """
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%B", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def _judgment_enabled(getenv: Any = None) -> bool:
    """Return False when the operator switched the model judgment off."""
    read = getenv if getenv is not None else os.environ.get
    value = (read(_JUDGMENT_ENV) or "").strip().lower()
    return value not in _OFF_VALUES


def _earned_a_journal_entry(message: str, files: list[str], widen: Any = None) -> bool:
    """Ask the model whether this commit earned an entry.  False on any failure.

    The floor is `False` here, so this function can only ever ADD a nudge.  The
    state is the commit's own message and its file list -- the data rule in
    `plugins/fleet-core/references/typesafe.md` forbids sending a transcript.
    """
    try:
        if widen is None:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
            import bundled_fleet  # noqa: PLC0415

            widen = bundled_fleet.load("jev_widen").widen

        result = widen(
            {"message": message, "files": files},
            "journal-nudge",
            {"earns_entry": False},
            decision_prefix="journal-nudge",
            timeout=_JUDGMENT_TIMEOUT,
            max_attempts=_JUDGMENT_ATTEMPTS,
            total_deadline=_JUDGMENT_DEADLINE,
        )
        return bool(result.judgments["earns_entry"].union)
    except Exception:
        # Fleet-core absent, the module moved, the vendor unreachable: the quiet
        # side is the safe side, and the hook has no way to report anyway.
        return False


def _nudge(from_model: bool) -> None:
    """Print the advisory line.  stderr only, never blocking."""
    because = (
        "this commit looks like it recorded a non-obvious mechanism or a pattern decision"
        if from_model
        else "this feat/fix commit touches code"
    )
    print(
        f"[saga/journal-nudge] Heads up: {because} but "
        "includes no docs/engineering-journal/ entry. "
        "Add a LEARNINGS.md or DECISIONS.md entry if the change earned one "
        "(non-obvious fix, pattern decision, tooling choice).",
        file=sys.stderr,
    )


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception:
        # Malformed envelope — pass through silently.
        sys.exit(0)

    tool_name: str = payload.get("tool_name", "")
    tool_input: dict = payload.get("tool_input", {})

    if tool_name != "Bash":
        sys.exit(0)

    command: str = tool_input.get("command", "")

    if not _is_git_commit_command(command):
        sys.exit(0)

    # The floor: the commit-message prefix, read from the shell command exactly
    # as it always was.
    msg = _extract_commit_message(command)
    matches_prefix = bool(_FEAT_FIX_RE.match(msg))

    # Determine the working directory from `git -C <path>` if present.
    cwd: str | None = _parse_git_dash_c(command)

    # Cross-repo safety: if the journal dir doesn't exist, degrade silently.
    if not _journal_dir_exists(cwd):
        sys.exit(0)

    # Inspect the committed files.
    files = _git_show_files(cwd)
    if not files:
        # Cannot determine committed files — be conservative, stay silent.
        sys.exit(0)

    if not _has_code_files(files):
        # Docs-only or non-code commit — no nudge.  This precondition is
        # deliberately NOT widened: the model widens which MESSAGE earns an
        # entry, not which kind of file does.
        sys.exit(0)

    if _has_journal_entry(files):
        # Journal entry present — all good, no nudge.
        sys.exit(0)

    if matches_prefix:
        # The floor fired: nudge without asking anything.  Asking here could
        # only ever agree, and it would cost a request on every feat/fix commit.
        _nudge(from_model=False)
        sys.exit(0)

    if not _judgment_enabled():
        sys.exit(0)

    message = _commit_message(cwd) or msg
    if not message:
        sys.exit(0)

    if _earned_a_journal_entry(message, files):
        _nudge(from_model=True)

    # Always exit 0 — never block.
    sys.exit(0)


if __name__ == "__main__":
    main()
