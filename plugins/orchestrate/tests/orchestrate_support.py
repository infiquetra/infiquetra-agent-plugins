"""Shared scaffolding for the Orchestrate tests, against the per-issue run record (issue #1025).

Every Orchestrate test builds a throwaway git repository under pytest's ``tmp_path`` and a
throwaway record store beside it. **Nothing here ever touches the primary checkout's live record
store, a live herdr, or this repository's own worktrees**, and every module that drives the plugin
goes through these helpers so that rule is stated once rather than re-derived per file.

The one thing worth knowing: ``run_record.resolve_store_root`` asks git for the *common*
directory, so a test that let it resolve would write into the developer's own
``.claude/saga/runs``. Every helper therefore passes ``--store-root`` explicitly, which is the
override the record module documents for exactly this reason.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess  # nosec B404 - fixed argv against a temporary repository
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

#: The issue number every migrated Orchestrate test drives its run under.
TEST_ISSUE = 1

REPO_ROOT = Path(__file__).resolve().parents[3]
ORCHESTRATE_SCRIPT = (
    REPO_ROOT / "plugins" / "orchestrate" / "skills" / "orchestrate" / "scripts" / "orchestrate.py"
)
_SIBLING_RUN_RECORD = REPO_ROOT / "plugins" / "saga" / "scripts" / "run_record.py"
_FIXTURE_RUN_RECORD = (
    REPO_ROOT / "plugins" / "orchestrate" / "tests" / "fixtures" / "saga_run_record.py"
)
RUN_RECORD_SCRIPT = _SIBLING_RUN_RECORD if _SIBLING_RUN_RECORD.is_file() else _FIXTURE_RUN_RECORD


def load_orchestrate(module_name: str, script: Path) -> ModuleType:
    """Load the driver under a per-module name, so two test modules never share its globals.

    *script* is the production driver, and every caller passes it rather than letting this helper
    supply a default. That is deliberate: a test module that drives real code should name the real
    file on its own face, so a reader of that module -- and the fake-only test-shape lint in
    ``scripts/lint_test_shape.py`` -- can see the boundary being crossed without following a helper.
    """
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_run_record() -> ModuleType:
    """Load saga's record module the same way the driver does."""
    spec = importlib.util.spec_from_file_location("run_record_for_tests", RUN_RECORD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(cwd: Path, *args: str) -> str:
    """Run one git command in *cwd* and return its stdout."""
    return subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_file(cwd: Path, name: str, body: str | None = None) -> str:
    """Write, add and commit one file; return the new commit."""
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body is not None else name + "\n")
    git(cwd, "add", name)
    git(cwd, "commit", "-m", f"add {name}")
    return git(cwd, "rev-parse", "HEAD")


def make_repo(tmp_path: Path, name: str = "repo", *, branch: str = "issue/1") -> Path:
    """A temporary git repository with one commit and one run branch."""
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    commit_file(repo, "base.txt")
    git(repo, "branch", branch)
    return repo


def ensure_origin(repo: Path) -> None:
    """Give *repo* a bare local remote with ``main`` on it, once.

    The merge turn refreshes its comparison ref before evaluating the guard against reverting a
    newer ``main``, and refuses when that fetch fails -- a guard that reads a stale ref passes
    silently, which is the failure card 875 reported. A repository with no remote at all would
    therefore refuse every merge, so every test repository gets one. It is a bare directory beside
    the repository: nothing here reaches the network.
    """
    existing = subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "remote"], cwd=repo, check=False, capture_output=True, text=True
    ).stdout.split()
    if "origin" in existing:
        return
    remote = repo.parent / f"{repo.name}-origin.git"
    if not remote.exists():
        git(repo, "init", "--bare", str(remote))
    # ``check=False``: two helpers in one module may both ask for a remote, and "it is already
    # there" is the state this function exists to reach, not a failure.
    subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "remote", "add", "origin", str(remote)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(  # nosec B603 B607 - a local push into a bare directory
        ["git", "push", "-q", "origin", "main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(  # nosec B603 B607
        ["git", "fetch", "-q", "origin"], cwd=repo, check=False, capture_output=True, text=True
    )


def unit_row(name: str, **over: Any) -> dict[str, Any]:
    """One unit row in the shape the record stores, with this card's fields defaulted."""
    row: dict[str, Any] = {
        "name": name,
        "vendor": "claude",
        "task": "do work",
        "branch": f"orch/1-{name}",
        "status": "pending",
        "merge": True,
        "merge_state": "ready",
        "merge_worktree": None,
        "launch_started_at": None,
        "shared_blockers": [],
        "after": [],
        "serialize": [],
    }
    row.update(over)
    return row


#: The unit-row keys issue #1025 added. A migrated test that never heard of them still needs them
#: present, and nothing else about its row may be invented -- a row that omits ``branch`` omits it
#: on purpose, and filling one in would quietly change what that test is about.
ADDED_UNIT_FIELDS: dict[str, Any] = {
    "merge_state": "ready",
    "merge_worktree": None,
    "launch_started_at": None,
    "shared_blockers": [],
}


def fill_unit_row(row: dict[str, Any]) -> dict[str, Any]:
    """A migrated test's unit row, with only this card's added fields defaulted.

    A row that expresses tab ownership the old way -- ``launch_receipt={"owned": True}`` -- has it
    carried onto the ``owned`` field, which is where that fact lives now that the receipt is not
    persisted. The test keeps saying what it meant; only the storage moved.
    """
    filled = {**ADDED_UNIT_FIELDS, **row}
    receipt = filled.get("launch_receipt")
    if isinstance(receipt, dict) and "owned" in receipt and "owned" not in row:
        filled["owned"] = receipt["owned"] is True
    return filled


def write_record(
    store_root: Path,
    issue: int,
    units: list[dict[str, Any]] | None = None,
    *,
    concurrency: int | None = 10,
    roster: list[dict[str, Any]] | None = None,
    extra_top_level: dict[str, Any] | None = None,
    **block: Any,
) -> Path:
    """Write one ``run_record.v1`` document with an ``orchestrate`` block, and return its path.

    *block* fills the orchestrate block (``run_id``, ``base``, ``branch``, ``issues`` and the
    rest). Passing ``units=None`` writes a record with NO orchestrate block at all, which is what
    a record straight out of admission looks like -- the state ``start`` is required to find.
    """
    store_root.mkdir(parents=True, exist_ok=True)
    configuration: dict[str, Any] = {}
    if concurrency is not None:
        configuration["concurrency_allocation"] = {
            "value": concurrency,
            "chosen_by": "delivery_manager",
            "source": "profile",
        }
    payload: dict[str, Any] = {
        "schema": "run_record.v1",
        "issue": issue,
        "repo": "infiquetra/infiquetra-claude-plugins",
        "created_at": "2026-09-19T00:00:00+00:00",
        "updated_at": "2026-09-19T00:00:00+00:00",
        "admission": {"destination": "pr"},
        "run_configuration": configuration,
        # The seven categories, written out: the record module fills an absent or empty block
        # with them on read, so a fixture that wrote ``{}`` would make every round-trip assertion
        # compare a normalised block against an un-normalised one and fail for the wrong reason.
        "approval_scope": dict.fromkeys(
            (
                "production changes",
                "destructive operations",
                "secrets or credential changes",
                "IAM or permission changes",
                "billing or cost-impacting actions",
                "external commitments",
                "major team or process authority changes",
            )
        ),
        "roster": roster or [],
        "units": units or [],
        "review_cycles": [],
        "next_step": "work",
    }
    if units is not None:
        defaults: dict[str, Any] = {
            "run_id": str(issue),
            "source": "a test",
            "base": "",
            "backend": "inline",
            "branch": f"issue/{issue}",
            "workspaces_created": [],
            "issues": {},
            "status_map": {},
            "workspace": None,
            "account": None,
            "review_result": None,
            "review_outcome": None,
            "review_resubmit_pending": False,
            "operator_fix_requests": [],
            "review_states": {},
            "review_controller_ceiling": None,
        }
        defaults.update(block)
        payload["orchestrate"] = defaults
    payload.update(extra_top_level or {})
    path = store_root / f"issue-{issue}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_record(store_root: Path, issue: int) -> dict[str, Any]:
    """The record as it is on disk, for asserting what a command actually wrote."""
    loaded: dict[str, Any] = json.loads(
        (store_root / f"issue-{issue}.json").read_text(encoding="utf-8")
    )
    return loaded


def attach_record(run: Any, store_root: Path, issue: int = TEST_ISSUE) -> Any:
    """Give a hand-built ``Run`` a record to save into.

    ``Run.save`` takes no path any more: it writes the unit rows and this plugin's block back into
    the issue's record. A test that builds a ``Run`` directly therefore has to say which record it
    belongs to, and this is that one line.
    """
    path = Path(store_root) / f"issue-{issue}.json"
    if not path.is_file():
        write_record(Path(store_root), issue, units=[])
    module = load_run_record()
    run.store_root = Path(store_root)
    run.issue = issue
    run.record = module.load(Path(store_root), issue, warn=None)
    return run


def save_run(run: Any, store_root: Path, issue: int = TEST_ISSUE) -> Path:
    """Attach *run* to its record if it is not already, then write it."""
    if getattr(run, "record", None) is None or getattr(run, "store_root", None) is None:
        attach_record(run, store_root, issue)
    return Path(run.save())


def args(issue: int, store_root: Path, **fields: Any) -> argparse.Namespace:
    """A Namespace shaped like the parser's, for calling a command function directly."""
    return argparse.Namespace(issue=issue, store_root=str(store_root), **fields)


class FakeProc:
    """What the fake runner hands back: the three fields the driver actually reads."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def failing_runner(
    real: Any,
    *,
    fails_when: Any,
    returncode: int = 128,
    stderr: str = "fatal: injected failure",
) -> Any:
    """Wrap the driver's runner so one named command fails, on every machine identically.

    This is how a cleanup failure is produced in these tests. The old fixture chose one of three
    host mechanisms -- ``chflags uchg`` on macOS, ``chattr +i`` on Linux, a worktree lock
    otherwise -- so which failure shape ran differed per machine, a defect appearing under only
    one would pass continuous integration, and every run left an undeletable directory behind
    (issue 991). Injecting the failure at the runner removes all three problems at once.
    """

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        if fails_when(cmd):
            return FakeProc(returncode=returncode, stderr=stderr)
        return real(cmd, **kwargs)

    return runner
