"""End-to-end review repair flow through Code Review, Orchestrate, and real Git.

The review roster, scoring engine, and Git repository are the production implementations. A tiny
``herdr`` executable stands in only for the transport that delivers already-routed instructions;
transport behavior is outside this test's contract.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from orchestrate_support import args as record_args
from orchestrate_support import ensure_origin, save_run, write_record

ROOT = Path(__file__).resolve().parents[3]

#: The issue whose record this run lives in. Since issue #1025 a run's state is the per-issue
#: ``run_record.v1`` document, so this end-to-end flow needs a record and an issue number where it
#: used to need only a run file beside the repository.
ISSUE = 1025
CONSENSUS_SCRIPT = ROOT / "plugins" / "saga" / "scripts" / "review_consensus.py"

if not CONSENSUS_SCRIPT.is_file():
    pytest.skip(
        "saga's review_consensus.py is not in this catalog yet; "
        "this cross-plugin test waits for that package",
        allow_module_level=True,
    )
ORCHESTRATE_SCRIPT = (
    ROOT / "plugins" / "orchestrate" / "skills" / "orchestrate" / "scripts" / "orchestrate.py"
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def consensus() -> ModuleType:
    return _load_module("_review_loop_end_to_end_consensus", CONSENSUS_SCRIPT)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    return _load_module("_review_loop_end_to_end_orchestrate", ORCHESTRATE_SCRIPT)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(cwd: Path, message: str, *paths: str) -> str:
    _git(cwd, "add", *paths)
    _git(cwd, "commit", "-m", message)
    return _git_out(cwd, "rev-parse", "HEAD")


def _score(consensus: ModuleType, policy: Any, lens_id: str, value: float) -> Any:
    dimensions = dict.fromkeys(policy.dimensions_for(lens_id), value)
    return consensus.score_lens_review(lens_id, dimensions, policy=policy)


def _install_herdr_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_failed_review_is_repaired_landed_resubmitted_and_accepted(
    consensus: ModuleType,
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    _git(
        repo,
        "worktree",
        "add",
        str(worker_tree),
        "-b",
        worker_branch,
        run_branch,
    )

    ensure_origin(repo)

    transport_log = _install_herdr_transport(tmp_path, monkeypatch)
    monkeypatch.chdir(repo)

    # The record store is a directory under ``tmp_path``; nothing here touches the developer's own
    # ``.claude/saga/runs``.
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

    # The thresholds come from a resolved roster since issue 1001; the plugin
    # ships no policy file of its own to load.
    policy = consensus.policy_from_roster(
        {
            "schema": "review_roster.v1",
            "hash": "sha256:loop-test",
            "lenses": [
                {
                    "id": lens_id,
                    "scorable": True,
                    "threshold": {
                        "strictness": "standard",
                        "derived_overall_minimum": 9.0,
                        "applicable_dimension_minimum": 7,
                    },
                    "dimensions": [{"id": f"{lens_id}-d{i}"} for i in range(1, 4)],
                }
                for lens_id in ("correctness", "testing")
            ],
        }
    )
    review = consensus.ReviewCycleState(
        ("correctness", "testing"),
        policy=policy,
    )
    finding = consensus.ReviewFinding(
        finding_id="correctness-ready-value",
        lens_id="correctness",
        dimension_id=policy.dimensions_for("correctness")[0],
        title="Service reports that it is not ready",
        severity="P1",
        file="service.py",
        line=2,
        why_it_matters="The service cannot enter its ready state.",
        autofix_class="safe_auto",
        owner="review-fixer",
        requires_verification=True,
        confidence=100,
        evidence=("service.py:2",),
        suggested_fix="Return the ready value.",
        touched_paths=("service.py",),
    )
    first_result = review.record_cycle(
        base_revision,
        {
            "correctness": _score(consensus, policy, "correctness", 8.9),
            "testing": _score(consensus, policy, "testing", 9.4),
        },
        findings=(finding,),
    )
    assert first_result.outcome == "repairs_requested"
    assert len(first_result.fix_requests) == 1

    first_result_path = tmp_path / "first-review.json"
    first_result_path.write_text(first_result.to_json())
    assert (
        orchestrate.cmd_review_result(
            record_args(ISSUE, store, file=str(first_result_path), controller=None)
        )
        == 0
    )

    routed = orchestrate.Run.load(ISSUE, store)
    routed_worker = routed.unit("worker")
    assert [item["fix_id"] for item in routed_worker.fix_requests] == [
        first_result.fix_requests[0].fix_id
    ]
    assert routed.review_resubmit_pending is True
    assert "agent prompt worker-agent" in transport_log.read_text()

    (worker_tree / "service.py").write_text("def ready() -> bool:\n    return True\n")
    repaired_revision = _commit(worker_tree, "fix service ready value", "service.py")
    routed_worker.status = orchestrate.DONE
    routed.save()

    # `land` became `merge` in issue #1025. The command is renamed and its state moved into the
    # record; the repair-lands-then-resubmits behaviour this test is about is unchanged.
    assert (
        orchestrate.cmd_merge(
            record_args(ISSUE, store, clean=False, remote="origin", compare="main")
        )
        == 0
    )
    landed_revision = _git_out(repo, "rev-parse", run_branch)
    assert landed_revision != repaired_revision
    assert _git_out(repo, "show", f"{run_branch}:service.py") == (
        "def ready() -> bool:\n    return True"
    )
    assert _git_out(repo, "merge-base", "--is-ancestor", repaired_revision, run_branch) == ""

    landed = orchestrate.Run.load(ISSUE, store)
    assert landed.unit("worker").fix_requests == []
    assert landed.review_resubmit_pending is False
    assert landed.review_controller().status == orchestrate.RUNNING
    log_after_resubmit = transport_log.read_text()
    assert "agent prompt review-agent" in log_after_resubmit
    assert landed_revision in log_after_resubmit

    changed_paths = _git_out(repo, "diff", "--name-only", f"{base_revision}..{landed_revision}")
    assert changed_paths.splitlines() == ["service.py"]
    final_result = review.record_cycle(
        landed_revision,
        {"correctness": _score(consensus, policy, "correctness", 9.4)},
        delta_checks=(
            consensus.DeltaCheckResult(
                lens_id="testing",
                reviewed_revision=base_revision,
                checked_revision=landed_revision,
                passed=True,
                cause="The bounded repair changed only the reviewed service implementation.",
                evidence_refs=(f"git-diff:{base_revision}..{landed_revision}:service.py",),
            ),
        ),
    )

    assert final_result.outcome == "accepted"
    assert final_result.best_available_revision == landed_revision
    assert final_result.fix_requests == ()
    assert {check.lens_id for check in final_result.cycle_history[-1].delta_checks} == {"testing"}
    assert all(
        lens.reviewed_revision == landed_revision
        or (
            lens.delta_check is not None
            and lens.delta_check.passed
            and lens.delta_check.checked_revision == landed_revision
        )
        for lens in final_result.lens_results
    )

    final_result_path = tmp_path / "final-review.json"
    final_result_path.write_text(final_result.to_json())
    assert (
        orchestrate.cmd_review_result(
            record_args(ISSUE, store, file=str(final_result_path), controller=None)
        )
        == 0
    )
    completed = orchestrate.Run.load(ISSUE, store)
    assert completed.review_outcome == "accepted"
    assert completed.review_result == final_result.to_json()
    assert transport_log.read_text().count("agent prompt") == 2
