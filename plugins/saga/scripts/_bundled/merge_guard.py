# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.32.0
# source-commit: authored
# source-path: scripts/fleet_commons/merge_guard.py
# source-sha256: de69ceee48497b61ae1714e4c268a3dabb8c8f4c0d7ce63087a7bf09554d022d
# output-sha256: de69ceee48497b61ae1714e4c268a3dabb8c8f4c0d7ce63087a7bf09554d022d
# --- end generated bundle stamp ---
#!/usr/bin/env python3
"""merge_guard — the one implementation of "never publish a merge that reverts a newer branch".

Card 875 asked for a guard that refuses a merge which would take a file backwards relative to the
branch it is measured against. Issue 1025 built it inside the orchestrate driver; issue 1028 gives
saga a merge turn of its own and needs the same refusal, so the rule lives here, in the component
saga already resolves through ``fleet_commons_shim``.

**The orchestrate driver keeps its own copy, deliberately.** ``orchestrate.py`` documents at its
plugin resolver why it must not take a resolution dependency on another plugin for something it
needs when that plugin is absent, and a safety guard is exactly the thing that must not depend on an
install. Two copies of a safety rule is still how one of them stops matching the other, so
``tests/test_merge_guard.py`` drives both through one case table and fails if they diverge. The
equivalence test is what keeps one rule from becoming two, in place of an import that would make
orchestrate fail to load on a machine without fleet-core.

Two functions, and the order between them is the whole point:

* :func:`fetch_comparison_branch` refreshes ``<remote>/<branch>`` and returns a refusal when the
  fetch fails. A guard evaluated against a stale remote-tracking reference passes silently, which
  is the failure card 875 actually reported, so a failed fetch refuses the turn rather than
  letting the comparison run on whatever was last pulled.
* :func:`regression_files` names the files the merge would take backwards. Empty means it reverts
  nothing.

Neither function merges, writes, or decides anything. The caller owns the turn; this owns the
question "would publishing this result undo work that is already on the comparison branch?".

The reading in :func:`regression_files` is deliberately narrow: only a file the comparison branch
has changed since the two diverged, AND that this merge result also touches, can be reverted by
publishing the merge. Refusing every merge whose branch is merely behind the comparison branch
would make ordinary parallel work unmergeable, which is a refusal nobody would keep.

House pattern: pure functions over explicit values, an injectable runner so a test drives real git
in a temporary repository (or a fake, where the point is the refusal text), and no I/O at import.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from typing import Any

#: How long a fetch may take before the turn is refused. A fetch that hangs is a refusal, not a
#: wait: the caller is holding a merge turn, and a held turn blocks every other worker.
FETCH_TIMEOUT_SECONDS = 180

Runner = Callable[..., Any]


def _run(
    runner: Runner | None,
    argv: Sequence[str],
    *,
    cwd: Any = None,
    timeout: int | None = None,
) -> Any:
    """Run one git command.

    ``cwd`` is threaded through rather than assumed, because a merge turn runs against a repository
    that is not whatever directory the calling process happens to be sitting in, and a guard that
    silently answers about the wrong repository is worse than one that fails.
    """
    call = runner if runner is not None else subprocess.run
    return call(list(argv), capture_output=True, text=True, cwd=cwd, timeout=timeout)


def _text(result: Any, field: str) -> str:
    return str(getattr(result, field, "") or "")


def fetch_comparison_branch(
    remote: str, branch: str, *, cwd: Any = None, runner: Runner | None = None
) -> str | None:
    """Refresh ``<remote>/<branch>``; return a refusal reason, or ``None`` when it is current.

    The refusal names the branch and says which guard it blocks, because "fetch failed" on its own
    reads as a network hiccup a caller might shrug off, and the consequence here is that the
    regression guard cannot be evaluated at all.
    """
    fetched = _run(runner, ["git", "fetch", remote, branch], cwd=cwd, timeout=FETCH_TIMEOUT_SECONDS)
    if getattr(fetched, "returncode", 0) == 0:
        return None
    detail = (_text(fetched, "stderr") or _text(fetched, "stdout") or "unknown error").strip()
    lines = [line for line in detail.splitlines() if line.strip()]
    return (
        f"`git fetch {remote} {branch}` failed"
        + (f": {lines[-1]}" if lines else "")
        + f"; the guard against reverting a newer {branch} cannot be evaluated against a current "
        "ref, so this merge turn is refused"
    )


def regression_files(
    merged_tip: str, compare_ref: str, *, cwd: Any = None, runner: Runner | None = None
) -> list[str]:
    """Files publishing *merged_tip* would take backwards relative to *compare_ref*.

    Returns a sorted list; empty means the merge reverts nothing. A merge result that already
    contains the comparison reference reverts nothing by construction and short-circuits.
    """
    ancestor = _run(
        runner, ["git", "merge-base", "--is-ancestor", compare_ref, merged_tip], cwd=cwd
    )
    if getattr(ancestor, "returncode", 1) == 0:
        return []
    base_result = _run(runner, ["git", "merge-base", compare_ref, merged_tip], cwd=cwd)
    if getattr(base_result, "returncode", 1) != 0:
        return []
    base = _text(base_result, "stdout").strip()
    if not base:
        return []
    theirs = _run(runner, ["git", "diff", "--name-only", f"{base}..{compare_ref}"], cwd=cwd)
    ours = _run(runner, ["git", "diff", "--name-only", f"{base}..{merged_tip}"], cwd=cwd)
    if getattr(theirs, "returncode", 1) != 0 or getattr(ours, "returncode", 1) != 0:
        return []
    theirs_files = {line.strip() for line in _text(theirs, "stdout").splitlines() if line.strip()}
    ours_files = {line.strip() for line in _text(ours, "stdout").splitlines() if line.strip()}
    return sorted(theirs_files & ours_files)


def refusal_for(files: Sequence[str], *, branch: str, compare_ref: str, limit: int = 20) -> str:
    """The one-line refusal naming what the merge would revert.

    Naming the files is the requirement: "this merge reverts something" sends the reader to a diff,
    while a list of paths tells them immediately whether the overlap is real work or a changelog
    both sides touched.
    """
    shown = ", ".join(files[:limit]) + (" ..." if len(files) > limit else "")
    return (
        f"merging {branch} would take {len(files)} file(s) backwards relative to {compare_ref} "
        f"and is refused: {shown}"
    )
