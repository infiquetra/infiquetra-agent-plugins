"""End-to-end review repair flow through Orchestrate and real Git.

The Git repository is real. The review result is canned JSON: either ``review_result.v2`` or a
review run. A tiny ``herdr`` executable stands in only for the transport that delivers
already-routed instructions; transport behavior is outside this test's contract.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from orchestrate_support import args as record_args
from orchestrate_support import ensure_origin, save_run, write_record

ROOT = Path(__file__).resolve().parents[3]

#: The issue whose record this run lives in. Since issue #1025 a run's state is the per-issue
#: ``run_record.v1`` document, so this end-to-end flow needs a record and an issue number where it
#: used to need only a run file beside the repository.
ISSUE = 1025
ORCHESTRATE_SCRIPT = (
    ROOT / "plugins" / "orchestrate" / "skills" / "orchestrate" / "scripts" / "orchestrate.py"
)
FINDING_ID = "rf:" + ("cd" * 16)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(cwd: Path, message: str, *paths: str) -> str:
    _git(cwd, "add", *paths)
    _git(cwd, "commit", "-m", message)
    return _git_out(cwd, "rev-parse", "HEAD")


def _install_herdr_transport(tmp_path: Path, monkeypatch: Any) -> Path:
    """Install a real process boundary for routing while keeping Herdr outside this test."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "herdr.log"
    executable = bin_dir / "herdr"
    executable.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$FAKE_HERDR_LOG"\n'
        'if [ "$1" = "agent" ] && [ "$2" = "list" ]; then\n'
        "  printf '%s\\n' "
        '\'{"result":{"agents":[{"name":"worker-agent",'
        '"pane_id":"pane-worker","agent_status":"idle"}]}}\'\n'
        "fi\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("FAKE_HERDR_LOG", str(log))
    monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)
    return log


def _v2(outcome: str, *requests: dict[str, Any]) -> str:
    return json.dumps(
        {"schema": "review_result.v2", "outcome": outcome, "fix_requests": list(requests)},
        ensure_ascii=False,
        sort_keys=True,
    )


def _prepare(orchestrate: ModuleType, tmp_path: Path, monkeypatch: Any) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "service.py").write_text("def ready() -> bool:\n    return False\n")
    base_revision = _commit(repo, "add broken service", "service.py")

    run_branch = "orch/review-run"
    worker_branch = f"{run_branch}-worker"
    _git(repo, "branch", run_branch)
    worker_tree = tmp_path / "worker"
    _git(repo, "worktree", "add", str(worker_tree), "-b", worker_branch, run_branch)
    ensure_origin(repo)
    transport_log = _install_herdr_transport(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)
    store = tmp_path / "store"
    write_record(store, ISSUE, units=[], branch=run_branch, base=base_revision)
    worker = orchestrate.Unit(
        name="worker",
        vendor="claude",
        task="/saga:work repair the reviewed service",
        role="review-fixer",
        paths=["service.py"],
        worktree=str(worker_tree),
        branch=worker_branch,
        branched_from=base_revision,
        pane_id="pane-worker",
        agent_name="worker-agent",
        status=orchestrate.DONE,
    )
    controller = orchestrate.Unit(
        name="code-review-controller",
        vendor="grok",
        task="/saga:code-review review the run branch",
        role="review-controller",
        merge=False,
        pane_id="pane-review",
        agent_name="review-agent",
        status=orchestrate.DONE,
    )
    run = orchestrate.Run(
        run_id="review-run",
        source="end-to-end test",
        base=base_revision,
        branch=run_branch,
        units=[worker, controller],
    )
    save_run(run, store, ISSUE)
    return {
        "repo": repo,
        "store": store,
        "worker_tree": worker_tree,
        "log": transport_log,
        "base": base_revision,
        "run_branch": run_branch,
    }


def _submit(orchestrate: ModuleType, store: Path, tmp_path: Path, raw: str, name: str) -> None:
    path = tmp_path / name
    path.write_text(raw)
    assert orchestrate.cmd_review_result(record_args(ISSUE, store, file=str(path), controller=None)) == 0


def test_failed_review_is_repaired_landed_resubmitted_and_accepted(
    tmp_path: Path, monkeypatch: Any
) -> None:
    orchestrate = _load_module("_review_loop_end_to_end_orchestrate", ORCHESTRATE_SCRIPT)
    world = _prepare(orchestrate, tmp_path, monkeypatch)
    store = world["store"]
    repo = world["repo"]
    first = _v2(
        "repairs_requested",
        {"owner": "review-fixer", "fix_id": "service-ready", "touched_paths": ["service.py"]},
    )
    _submit(orchestrate, store, tmp_path, first, "first-review.json")

    routed = orchestrate.Run.load(ISSUE, store)
    routed_worker = routed.unit("worker")
    assert [item["fix_id"] for item in routed_worker.fix_requests] == ["service-ready"]
    assert routed.review_resubmit_pending is True
    assert "agent prompt worker-agent" in world["log"].read_text()

    (world["worker_tree"] / "service.py").write_text("def ready() -> bool:\n    return True\n")
    repaired_revision = _commit(world["worker_tree"], "fix service ready value", "service.py")
    routed_worker.status = orchestrate.DONE
    routed.save()

    assert (
        orchestrate.cmd_merge(record_args(ISSUE, store, clean=False, remote="origin", compare="main"))
        == 0
    )
    landed_revision = _git_out(repo, "rev-parse", world["run_branch"])
    assert landed_revision != repaired_revision
    assert _git_out(repo, "show", f"{world['run_branch']}:service.py") == (
        "def ready() -> bool:\n    return True"
    )
    assert _git_out(repo, "merge-base", "--is-ancestor", repaired_revision, world["run_branch"]) == ""

    landed = orchestrate.Run.load(ISSUE, store)
    assert landed.unit("worker").fix_requests == []
    assert landed.review_resubmit_pending is False
    assert landed.review_controller().status == orchestrate.RUNNING
    log_after_resubmit = world["log"].read_text()
    assert "agent prompt review-agent" in log_after_resubmit
    assert landed_revision in log_after_resubmit

    changed_paths = _git_out(repo, "diff", "--name-only", f"{world['base']}..{landed_revision}")
    assert changed_paths.splitlines() == ["service.py"]
    final = _v2("accepted")
    _submit(orchestrate, store, tmp_path, final, "final-review.json")
    completed = orchestrate.Run.load(ISSUE, store)
    assert completed.review_outcome == "accepted"
    assert json.loads(completed.review_result)["schema"] == "review_result.v2"
    assert world["log"].read_text().count("agent prompt") == 2


def test_an_end_to_end_repair_comes_from_a_review_run(tmp_path: Path, monkeypatch: Any) -> None:
    orchestrate = _load_module("_review_loop_end_to_end_review_run", ORCHESTRATE_SCRIPT)
    world = _prepare(orchestrate, tmp_path, monkeypatch)
    store = world["store"]
    repo = world["repo"]
    raw = json.dumps(
        {
            "schema": "review_records.v1",
            "kind": "review_run",
            "round": 1,
            "merge": {"allowed": False, "blocking": [FINDING_ID]},
            "findings": [
                {
                    "id": FINDING_ID,
                    "statement": "CANARY",
                    "location": {"scope": "file", "file": "./service.py"},
                }
            ],
        },
        sort_keys=True,
    )
    _submit(orchestrate, store, tmp_path, raw, "review-run.json")
    routed = orchestrate.Run.load(ISSUE, store)
    assert [item["fix_id"] for item in routed.unit("worker").fix_requests] == [FINDING_ID]
    log = world["log"].read_text()
    assert "CANARY" not in log
    assert "service.py" in log

    (world["worker_tree"] / "service.py").write_text("def ready() -> bool:\n    return True\n")
    _commit(world["worker_tree"], "fix service ready value", "service.py")
    routed.unit("worker").status = orchestrate.DONE
    routed.save()
    assert (
        orchestrate.cmd_merge(record_args(ISSUE, store, clean=False, remote="origin", compare="main"))
        == 0
    )
    assert _git_out(repo, "show", f"{world['run_branch']}:service.py") == (
        "def ready() -> bool:\n    return True"
    )
