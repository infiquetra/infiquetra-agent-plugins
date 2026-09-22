"""The Orchestrate seam around Code Review's opaque typed result.

Code Review owns acceptance and cycle policy. These tests prove that Orchestrate has one controller,
stores the controller's bytes, routes repair ownership to Work, protects active workers, and never
turns operator-owned work or finding metadata into another acceptance gate.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import orchestrate_support as _support
import pytest

# --- issue #1025: every stateful subcommand takes --issue and --store-root -----------------------

TEST_ISSUE = 1


_STORE: Path | None = None


@pytest.fixture(autouse=True)
def _pin_the_record_store(tmp_path: Path) -> Iterator[None]:
    """Pin this test's record store to its own ``tmp_path``.

    Never the resolved store -- that is the developer's own ``.claude/saga/runs`` -- and never
    derived from the working directory either: a helper called before a test changes directory
    would then write one store and read another.
    """
    global _STORE
    _STORE = tmp_path / "orch-test-store"
    _STORE.mkdir(parents=True, exist_ok=True)
    yield
    _STORE = None


def test_store() -> Path:
    """This test's record store."""
    assert _STORE is not None, "the record store is pinned by an autouse fixture"
    return _STORE


def NS(**fields: object) -> argparse.Namespace:
    """A command Namespace carrying this test's issue and store."""
    # `merge` and `clean` carry optional flags the parser defaults; a Namespace built by
    # hand has to default them too, or the command reads an attribute that is not there.
    defaults = {"remote": "origin", "compare": "main"}
    return argparse.Namespace(
        issue=TEST_ISSUE,
        store_root=str(test_store()),
        **{**defaults, **fields},
    )


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_orchestrate_review_loop", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _controller(orchestrate: ModuleType) -> Any:
    return orchestrate.Unit(
        name="code-review-controller",
        vendor="grok",
        task="/saga:code-review review the run branch",
        role="review-controller",
        merge=False,
        pane_id="pane-review",
        agent_name="review-agent",
        status="done",
    )


def _worker(
    orchestrate: ModuleType,
    name: str,
    role: str,
    *paths: str,
    live: bool = True,
) -> Any:
    return orchestrate.Unit(
        name=name,
        vendor="claude",
        model="opus",
        effort="high",
        task="/saga:work docs/plans/build.md",
        role=role,
        paths=list(paths),
        pane_id=f"pane-{name}" if live else None,
        agent_name=f"agent-{name}" if live else None,
        status="done",
    )


def _run(orchestrate: ModuleType, *units: Any) -> Any:
    """A run attached to its own record, so ``save()`` has somewhere to write (issue #1025)."""
    run = orchestrate.Run(run_id="review-run", source="test", base="base", units=list(units))
    return _support.attach_record(run, test_store())


def _request(fix_id: str, owner: str, *paths: str) -> dict[str, Any]:
    return {
        "fix_id": fix_id,
        "finding_ids": [f"finding-{fix_id}"],
        "autofix_class": "safe_auto",
        "owner": owner,
        "touched_paths": list(paths),
        "summary": f"repair {fix_id}",
        "requires_verification": True,
    }


def _result(outcome: str, *requests: dict[str, Any], **extra: Any) -> str:
    payload: dict[str, Any] = {
        "schema": "review_result.v2",
        "outcome": outcome,
        "fix_requests": list(requests),
        **extra,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _live(*workers: Any) -> list[dict[str, str]]:
    return [
        {"name": worker.agent_name, "pane_id": worker.pane_id, "agent_status": "idle"}
        for worker in workers
    ]


def test_a_code_review_phase_has_exactly_one_controller(orchestrate: ModuleType) -> None:
    plan = {
        "units": [
            {
                "name": "builder",
                "vendor": "claude",
                "task": "/saga:work docs/plans/build.md",
                "role": "review-fixer",
                "paths": ["src"],
            },
            {
                "name": "review",
                "vendor": "grok",
                "task": "/saga:code-review the build",
            },
        ]
    }

    units = orchestrate.plan_units(plan)

    controllers = [unit for unit in units if unit.role == "review-controller"]
    assert [unit.name for unit in controllers] == ["review"]

    plan["units"].append(
        {"name": "review-two", "vendor": "codex", "task": "$saga:code-review the build"}
    )
    with pytest.raises(SystemExit, match="exactly one top-level Code Review controller"):
        orchestrate.plan_units(plan)


def test_explicit_work_role_wins_over_code_review_text_in_an_operator_plan(
    orchestrate: ModuleType,
) -> None:
    plan = {
        "units": [
            {
                "name": "review-fixer",
                "vendor": "claude",
                "task": (
                    "/saga:work repair "
                    "plugins/saga/skills/code-review/SKILL.md from the routed request"
                ),
                "role": "review-fixer",
                "paths": ["plugins/saga/skills/code-review/SKILL.md"],
            },
            {
                "name": "review",
                "vendor": "grok",
                "task": "/code-review the run branch",
                "role": "review-controller",
            },
        ]
    }

    units = orchestrate.plan_units(plan)

    assert [(unit.name, unit.role) for unit in units] == [
        ("review-fixer", "review-fixer"),
        ("review", "review-controller"),
    ]


def test_two_role_and_path_matches_reuse_live_workers_and_protect_them(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    resolver = _worker(
        orchestrate,
        "contract-builder",
        "downstream-resolver",
        "packages/contracts",
    )
    run = _run(orchestrate, fixer, resolver, controller)
    raw = _result(
        "repairs_requested",
        _request("fix-api", "review-fixer", "src/api/routes.py"),
        _request("fix-contract", "downstream-resolver", "packages/contracts/schema.json"),
    )

    routing = orchestrate.route_review_result(run, raw, agents=_live(fixer, resolver))
    sent: list[tuple[str, str]] = []
    dispatched = orchestrate.dispatch_review_routing(
        routing, sender=lambda unit, text: sent.append((unit.name, text))
    )

    assert dispatched == ["api-builder", "contract-builder"]
    assert [name for name, _ in sent] == dispatched
    assert [item["fix_id"] for item in fixer.fix_requests] == ["fix-api"]
    assert [item["fix_id"] for item in resolver.fix_requests] == ["fix-contract"]
    assert orchestrate.reapable(fixer, run) is False
    assert orchestrate.reapable(resolver, run) is False
    assert routing.replacements == []
    assert run.review_resubmit_pending is True


def test_a_missing_live_match_creates_a_replacement_work_worker(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    original = _worker(
        orchestrate,
        "retired-api-builder",
        "review-fixer",
        "src/api",
        live=False,
    )
    run = _run(orchestrate, original, controller)

    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request("fix-new-route", "review-fixer", "src/api/new_route.py"),
        ),
        agents=[],
    )

    assert routing.dispatches == []
    assert len(routing.replacements) == 1
    replacement = routing.replacements[0]
    assert replacement is run.units[-1]
    assert replacement.vendor == original.vendor
    assert replacement.model == original.model
    assert replacement.effort == original.effort
    assert replacement.role == "review-fixer"
    assert replacement.paths == ["src/api/new_route.py"]
    assert replacement.serialize == [controller.name]
    assert replacement.status == "pending"


def test_repeated_routing_reuses_the_pending_replacement_for_the_same_fix(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    original = _worker(
        orchestrate,
        "retired-api-builder",
        "review-fixer",
        "src/api",
        live=False,
    )
    run = _run(orchestrate, original, controller)
    raw = _result(
        "repairs_requested",
        _request("fix-new-route", "review-fixer", "src/api/new_route.py"),
    )

    routings = [orchestrate.route_review_result(run, raw, agents=[]) for _ in range(4)]

    replacement = routings[0].replacements[0]
    assert [routing.replacements for routing in routings] == [[replacement], [], [], []]
    assert run.units == [original, controller, replacement]
    assert [request["fix_id"] for request in replacement.fix_requests] == ["fix-new-route"]
    assert run.eligible() == [replacement]


def test_generated_replacement_with_a_code_review_path_never_becomes_a_controller(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    original = _worker(
        orchestrate,
        "retired-review-plugin-builder",
        "review-fixer",
        "plugins/saga/skills/code-review",
        live=False,
    )
    run = _run(orchestrate, original, controller)

    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request(
                "fix-review-skill",
                "review-fixer",
                "plugins/saga/skills/code-review/SKILL.md",
            ),
        ),
        agents=[],
    )

    replacement = routing.replacements[0]
    assert "code-review/SKILL.md" in replacement.task
    assert replacement.role == "review-fixer"
    assert run.review_controller() is controller
    orchestrate.assert_single_review_controller(run.units)


@pytest.mark.parametrize("owner", ["human", "release"])
def test_operator_owned_requests_are_surfaced_and_never_dispatched_as_work(
    orchestrate: ModuleType,
    owner: str,
) -> None:
    controller = _controller(orchestrate)
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, controller)

    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request(f"fix-{owner}", owner, "src/release.py")),
        agents=_live(worker),
    )

    assert routing.dispatches == []
    assert routing.replacements == []
    assert [item["owner"] for item in routing.operator_requests] == [owner]
    assert run.operator_fix_requests == routing.operator_requests
    assert run.review_resubmit_pending is False
    assert len(run.units) == 2
    assert (
        orchestrate.resubmit_review_if_ready(
            run,
            "landed-revision",
            sender=lambda _unit, _text: pytest.fail("operator-owned work was resubmitted"),
        )
        is False
    )


def test_outstanding_work_request_prevents_resubmission_before_landing(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    worker.fix_requests = [_request("fix-work", "review-fixer", "src/file.py")]
    run = _run(orchestrate, worker, controller)
    run.review_resubmit_pending = True

    assert (
        orchestrate.resubmit_review_if_ready(
            run,
            "not-yet-landed",
            sender=lambda _unit, _text: pytest.fail("outstanding Work repair was resubmitted"),
        )
        is False
    )


def test_mixed_work_and_operator_requests_block_resubmission_for_the_real_reason(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    controller = _controller(orchestrate)
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, controller)
    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request("fix-work", "review-fixer", "src/file.py"),
            _request("fix-operator", "human", "src/operator.txt"),
        ),
        agents=_live(worker),
    )
    orchestrate.dispatch_review_routing(routing, sender=lambda _unit, _text: None)

    assert run.review_resubmit_pending is True
    assert (
        orchestrate.resubmit_review_if_ready(
            run,
            "before-work-landed",
            sender=lambda _unit, _text: pytest.fail("outstanding Work repair was resubmitted"),
        )
        is False
    )

    assert orchestrate.complete_landed_fix_requests(run, [worker.name]) == ["fix-work"]
    assert (
        orchestrate.resubmit_review_if_ready(
            run,
            "after-work-landed",
            sender=lambda _unit, _text: pytest.fail("operator-owned repair was resubmitted"),
        )
        is False
    )

    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    assert orchestrate.cmd_status(NS()) == 0
    output = capsys.readouterr().out
    assert "resubmission held by operator-owned fix requests" in output
    assert "awaiting landed Work repairs" not in output
    assert "fix-operator" in output


def test_disjoint_review_fixes_route_to_different_path_owners(orchestrate: ModuleType) -> None:
    first = _worker(orchestrate, "worker-a", "review-fixer", "src/a")
    second = _worker(orchestrate, "worker-b", "review-fixer", "src/b")
    run = _run(orchestrate, first, second, _controller(orchestrate))

    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request("fix-a", "review-fixer", "src/a/a.py"),
            _request("fix-b", "review-fixer", "src/b/b.py"),
        ),
        agents=_live(first, second),
    )

    assert [unit.name for unit, _ in routing.dispatches] == ["worker-a", "worker-b"]


def test_typed_result_round_trips_byte_identically_without_policy_parsing(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = (
        '{\r\n  "schema": "review_result.v2",\r\n  "outcome": "accepted",\r\n'
        '  "fix_requests": [],\r\n  "lens_results": {"derived_overall": "not a number",'
        ' "dimensions": null},\r\n  "finding_metadata": {"priority": "P0",'
        ' "confidence": 100}\r\n}\r\n'
    )
    run = _run(orchestrate, _controller(orchestrate))
    result_path = tmp_path / "result.json"
    result_path.write_bytes(raw.encode("utf-8"))
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    restored = orchestrate.Run.load(_support.TEST_ISSUE, test_store())

    assert restored.review_outcome == "accepted"
    assert restored.review_result == raw
    assert restored.review_result.encode("utf-8") == raw.encode("utf-8")


def test_failed_live_dispatch_keeps_the_result_retryable_and_the_worker_protected(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, _controller(orchestrate))
    result_path = tmp_path / "result.json"
    raw = _result(
        "repairs_requested",
        _request("retry-dispatch", "review-fixer", "src/file.py"),
    )
    result_path.write_text(raw)
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: _live(worker))
    attempts: list[str] = []

    def flaky_prompt(handle: str, text: str) -> None:
        protected = next(
            u
            for u in orchestrate.Run.load(_support.TEST_ISSUE, test_store()).units
            if (u.agent_name or u.name) == handle
        )
        assert [request["fix_id"] for request in protected.fix_requests] == ["retry-dispatch"]
        attempts.append(text)
        if len(attempts) == 1:
            raise SystemExit("prompt transport failed")

    _stub_prompt_door(orchestrate, monkeypatch, flaky_prompt)

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 1
    failed = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert failed.review_result == raw
    assert failed.review_outcome is None
    assert [request["fix_id"] for request in failed.unit("builder").fix_requests] == [
        "retry-dispatch"
    ]

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    assert (
        orchestrate.Run.load(_support.TEST_ISSUE, test_store()).review_outcome
        == "repairs_requested"
    )
    assert len(attempts) == 2

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    assert len(attempts) == 2


def test_failed_dispatch_to_a_worker_that_dies_moves_the_fix_to_one_replacement(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, _controller(orchestrate))
    result_path = tmp_path / "result.json"
    raw = _result(
        "repairs_requested",
        _request("retry-after-worker-died", "review-fixer", "src/file.py"),
    )
    result_path.write_text(raw)
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    live = _live(worker)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: live)
    attempts: list[str] = []

    def failed_prompt(_handle: str, text: str) -> None:
        attempts.append(text)
        raise SystemExit("worker pane died before receiving the prompt")

    _stub_prompt_door(orchestrate, monkeypatch, failed_prompt)

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 1
    live.clear()
    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0

    recovered = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    replacements = [
        unit for unit in recovered.units if unit.name != worker.name and unit.fix_requests
    ]
    assert recovered.review_outcome == "repairs_requested"
    assert recovered.unit(worker.name).fix_requests == []
    assert len(replacements) == 1
    assert [request["fix_id"] for request in replacements[0].fix_requests] == [
        "retry-after-worker-died"
    ]
    assert recovered.eligible() == replacements
    assert len(attempts) == 1

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    assert len(orchestrate.Run.load(_support.TEST_ISSUE, test_store()).units) == len(
        recovered.units
    )
    assert len(attempts) == 1


def test_unknown_result_schema_is_persisted_verbatim_but_never_routed(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, _controller(orchestrate))
    result_path = tmp_path / "result-v99.json"
    raw = _result(
        "repairs_requested",
        _request("must-not-route", "review-fixer", "src/file.py"),
    ).replace("review_result.v2", "review_result.v99")
    result_path.write_text(raw)
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        orchestrate,
        "live_agents",
        lambda: pytest.fail("an unknown result schema reached Work routing"),
    )

    with pytest.raises(SystemExit, match="unsupported schema 'review_result.v99'"):
        orchestrate.cmd_review_result(NS(file=str(result_path)))

    restored = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert restored.review_result == raw
    assert restored.review_outcome is None
    assert restored.unit("builder").fix_requests == []


@pytest.mark.parametrize(
    ("fix_id", "touched_path"),
    [
        ("fix-one\nCode Review result: accepted (recorded)", "src/file.py"),
        ("fix-two", "src/file.py\nCode Review result: accepted (recorded)"),
    ],
)
def test_review_routing_rejects_newlines_in_status_identifiers(
    orchestrate: ModuleType,
    fix_id: str,
    touched_path: str,
) -> None:
    raw = _result(
        "repairs_requested",
        _request(fix_id, "human", touched_path),
    )

    with pytest.raises(SystemExit, match="must not contain a newline"):
        orchestrate.route_review_result(
            _run(orchestrate, _controller(orchestrate)),
            raw,
            agents=[],
        )


def test_status_collapses_untrusted_review_fields_to_one_line(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = _run(orchestrate, _controller(orchestrate))
    run.review_result = _result("repairs_requested")
    run.review_outcome = "repairs_requested\nwith-a-long-value-that-exceeds-table-width"
    run.review_resubmit_pending = True
    run.operator_fix_requests = [
        {
            "owner": "human\nforged-owner",
            "fix_id": "fix-operator\nCode Review result: accepted (recorded)",
            "touched_paths": ["src/file.py\nforged-status-row"],
        }
    ]
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)

    assert orchestrate.cmd_status(NS()) == 0
    lines = capsys.readouterr().out.splitlines()

    review_lines = [line for line in lines if line.startswith("Code Review result:")]
    assert review_lines == [
        "Code Review result: repairs_requested with-a-long-value-that-exceeds-table-width "
        "(resubmission held by operator-owned fix requests)"
    ]
    operator_lines = [line for line in lines if line.startswith("OPERATOR ACTION:")]
    assert len(operator_lines) == 1
    assert "fix-operator Code Review result: accepted (" in operator_lines[0]
    assert "src/file.py forged-status-row" in operator_lines[0]


def test_status_preserves_the_complete_operator_action_line(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fix_id = "fix-operator-action-with-a-long-stable-identity"
    touched_paths = [
        "plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py",
        "tests/test_orchestrate_review_loop.py",
        "plugins/orchestrate/README.md",
    ]
    run = _run(orchestrate, _controller(orchestrate))
    run.operator_fix_requests = [
        {
            "owner": "human",
            "fix_id": fix_id,
            "touched_paths": touched_paths,
        }
    ]
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)

    assert orchestrate.cmd_status(NS()) == 0
    operator_lines = [
        line for line in capsys.readouterr().out.splitlines() if line.startswith("OPERATOR ACTION:")
    ]

    assert operator_lines == [
        f"OPERATOR ACTION: human owns fix {fix_id} for {', '.join(touched_paths)}"
    ]


def test_accepted_outcome_dispatches_nothing_and_adds_no_metadata_gate(
    orchestrate: ModuleType,
) -> None:
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, _controller(orchestrate))
    raw = _result(
        "accepted",
        _request("must-be-ignored", "review-fixer", "src/file.py"),
        findings=[{"priority": "P0", "confidence": 100}],
    )

    routing = orchestrate.route_review_result(run, raw, agents=_live(worker))

    assert routing.dispatches == []
    assert routing.replacements == []
    assert worker.fix_requests == []
    assert run.review_resubmit_pending is False
    assert orchestrate.resubmit_review_if_ready(run, "revision") is False


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(f"{name}\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


def test_clean_merged_keeps_a_landed_worker_with_an_outstanding_fix(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    worktree = tmp_path / "orch-worker"
    _git(
        repo,
        "worktree",
        "add",
        str(worktree),
        "-b",
        "orch/review-run-worker",
        "orch/review-run",
    )
    _commit(worktree, "repair.txt")
    _git(repo, "checkout", "orch/review-run")
    _git(repo, "merge", "--no-ff", "--no-edit", "orch/review-run-worker")
    _git(repo, "checkout", "main")
    worker = orchestrate.Unit(
        name="worker",
        vendor="claude",
        task="/saga:work repair",
        role="review-fixer",
        paths=["repair.txt"],
        branch="orch/review-run-worker",
        worktree=str(worktree),
        status="done",
    )
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[worker],
    )
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    run.resolve_branch_once()
    assert orchestrate.reapable(worker, run) is True
    worker.fix_requests.append(_request("still-open", "review-fixer", "repair.txt"))
    assert orchestrate.reapable(worker, run) is True

    closed, kept = orchestrate.reap(run, merged_only=True)

    assert closed == []
    assert kept == ["worker"]
    assert worktree.exists()
    assert _git_out(repo, "rev-parse", "--verify", "orch/review-run-worker")

    closed, kept = orchestrate.reap(run, merged_only=False)
    assert closed == []
    assert kept == ["worker"]
    assert worktree.exists()


def test_clean_keeps_worktree_when_owned_tab_close_fails(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REL-04/ARCH-01/REL-05: the real close_run_session drives the note through a run stub,
    twice in a row -- a failed close followed by the operator's retry of `clean`. The
    recording has one owner (close_run_session, whose membership test is a substring: the
    failure message itself contains the note separator, so a split on it can never match),
    and one copy of the failure stands after both passes. At the frozen revision the first
    pass left two copies, because both dedup sites appended under a split test."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    worktree = tmp_path / "worker"
    worktree.mkdir()
    unit = orchestrate.Unit(
        name="worker",
        vendor="claude",
        task="work",
        worktree=str(worktree),
        tab_id="w1:t1",
        # The receipt is no longer persisted, so the ownership fact the close needs lives on the
        # unit itself (issue #1025). Both are set here: the receipt for the in-memory path, the
        # field for everything after a reload.
        launch_receipt={"tab_id": "w1:t1", "owned": True},
        owned=True,
        status="done",
    )
    run_record = orchestrate.Run(run_id="review-run", source="test", base="main", units=[unit])
    real_run = orchestrate.run

    def selective_run(cmd: list[str], **kwargs: object) -> Any:
        if cmd[:3] == ["herdr", "tab", "close"]:
            return subprocess.CompletedProcess(cmd, 1, "", "herdr refused; pane is busy")
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": "w1:t1", "label": "t"}]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(orchestrate, "run", selective_run)
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    _support.save_run(run_record, test_store())

    args = NS(merged=False, branches=False, all=False, remote="origin")
    # Exit 3: the close was attempted on a tab this run owns and could not be made, so something
    # this run owns was left behind and the status says so (issue #1025).
    assert orchestrate.cmd_clean(args) == 3
    first_output = capsys.readouterr().out
    saved = orchestrate.Run.load(_support.TEST_ISSUE, test_store()).unit("worker")

    assert worktree.exists()
    failure = "tab close failed (1) for w1:t1: herdr refused; pane is busy"
    assert saved.note == failure
    assert f"kept worker: {failure}" in first_output
    assert "kept (not done, or its work not on the run branch): worker" not in first_output

    assert orchestrate.cmd_clean(args) == 3
    second_output = capsys.readouterr().out
    assert f"kept worker: {failure}" in second_output
    assert orchestrate.Run.load(_support.TEST_ISSUE, test_store()).unit("worker").note == failure


@pytest.mark.parametrize(
    ("review_resubmit_pending", "operator_request"),
    [
        (True, None),
        (False, _request("operator-open", "human", "repair.txt")),
    ],
)
def test_clean_merged_keeps_the_review_controller_while_review_work_is_outstanding(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review_resubmit_pending: bool,
    operator_request: dict[str, Any] | None,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    worktree = tmp_path / "review-controller"
    _git(
        repo,
        "worktree",
        "add",
        str(worktree),
        "-b",
        "orch/review-controller",
        "orch/review-run",
    )
    _commit(worktree, "review.txt")
    _git(repo, "checkout", "orch/review-run")
    _git(repo, "merge", "--no-ff", "--no-edit", "orch/review-controller")
    _git(repo, "checkout", "main")
    controller = _controller(orchestrate)
    controller.branch = "orch/review-controller"
    controller.worktree = str(worktree)
    controller.merge = True
    controller.pane_id = None
    controller.agent_name = None
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[controller],
        review_resubmit_pending=review_resubmit_pending,
        operator_fix_requests=[operator_request] if operator_request is not None else [],
    )
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    run.resolve_branch_once()

    assert orchestrate.landed(controller.branch, run) is True
    assert orchestrate.reapable(controller, run) is False
    closed, kept = orchestrate.reap(run, merged_only=True)

    assert closed == []
    assert kept == [controller.name]
    assert worktree.exists()


def test_land_names_the_operator_request_holding_review_resubmission(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    fix_id = "operator-fix-with-a-long-stable-identity-that-must-remain-complete"
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[_controller(orchestrate)],
        review_result=_result("repairs_requested"),
        review_outcome="repairs_requested",
        review_resubmit_pending=True,
        operator_fix_requests=[_request(fix_id, "human", "src/operator.txt")],
    )
    _support.save_run(run, test_store())
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)

    assert orchestrate.cmd_merge(NS(clean=False)) == 4
    output = capsys.readouterr().out

    assert f"Code Review resubmission held by operator-owned fix request: {fix_id}" in output


def test_land_retries_a_failed_review_resubmission_after_the_repair_is_already_landed(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    worktree = tmp_path / "repair-worker"
    _git(
        repo,
        "worktree",
        "add",
        str(worktree),
        "-b",
        "orch/review-repair",
        "orch/review-run",
    )
    _commit(worktree, "repair.txt")

    worker = _worker(
        orchestrate,
        "builder",
        "review-fixer",
        "repair.txt",
        live=False,
    )
    worker.branch = "orch/review-repair"
    worker.worktree = str(worktree)
    worker.fix_requests = [_request("fix-work", "review-fixer", "repair.txt")]
    controller = _controller(orchestrate)
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[worker, controller],
        review_result=_result("repairs_requested"),
        review_outcome="repairs_requested",
        review_resubmit_pending=True,
    )
    _support.save_run(run, test_store())
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    attempts: list[str] = []

    def flaky_prompt(_handle: str, text: str) -> None:
        attempts.append(text)
        if len(attempts) == 1:
            raise SystemExit("controller prompt failed")

    _stub_prompt_door(orchestrate, monkeypatch, flaky_prompt)

    assert orchestrate.cmd_merge(NS(clean=False)) == 4
    first_output = capsys.readouterr().out
    landed_tip = _git_out(repo, "rev-parse", "orch/review-run")
    failed = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert "REVIEW RESUBMIT FAILED: controller prompt failed" in first_output
    assert failed.review_resubmit_pending is True
    assert failed.unit("builder").fix_requests == []

    assert orchestrate.cmd_merge(NS(clean=False)) == 0
    second_output = capsys.readouterr().out
    retried = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert "resubmitted landed revision" in second_output
    assert "merged onto orch/review-run: nothing new" in second_output
    assert _git_out(repo, "rev-parse", "orch/review-run") == landed_tip
    assert len(attempts) == 2
    assert all(landed_tip in prompt for prompt in attempts)
    assert retried.review_resubmit_pending is False
    assert retried.unit("code-review-controller").status == "running"


def test_landed_work_repairs_resubmit_the_exact_revision_to_the_same_controller(
    orchestrate: ModuleType,
) -> None:
    controller = _controller(orchestrate)
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, controller)
    run.review_resubmit_pending = True
    sent: list[tuple[Any, str]] = []

    resubmitted = orchestrate.resubmit_review_if_ready(
        run,
        "0123456789abcdef",
        sender=lambda unit, text: sent.append((unit, text)),
    )

    assert resubmitted is True
    assert sent[0][0] is controller
    assert "0123456789abcdef" in sent[0][1]
    assert "same Code Review controller" in sent[0][1]
    assert controller.status == "running"
    assert run.review_resubmit_pending is False
    assert len(run.units) == 2


def _claude_composer_pane(composer_line: str) -> str:
    """The same unbordered Claude/Grok composer geometry the launch tests use."""
    rule = "\x1b[2m──────────────────────────────\x1b[0m"
    return f"{rule}\n{composer_line}\n{rule}\n"


def _record_herdr_boundary(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    pane_dumps: list[str],
) -> list[list[str]]:
    """Stub only ``run`` and record every command the default sender issues."""
    dumps = iter(pane_dumps)
    recorded: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(list(cmd))
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, next(dumps), "")
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(orchestrate, "run", fake_run)
    return recorded


def _stub_prompt_door(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    on_prompt: Callable[[str, str], None],
) -> None:
    """Stub the prompt door at the Herdr boundary, never the writer: ``on_prompt(handle,
    text)`` may raise to model a transport failure; pane reads answer an empty composer;
    every other command reaches the real ``run``."""
    real_run = orchestrate.run

    def fake_run(cmd: list[str], *a: Any, **k: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            on_prompt(cmd[3], cmd[4])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            return subprocess.CompletedProcess(cmd, 0, _claude_composer_pane("❯ "), "")
        result: subprocess.CompletedProcess[str] = real_run(cmd, *a, **k)
        return result

    monkeypatch.setattr(orchestrate, "run", fake_run)


def _prompt_calls(recorded: list[list[str]]) -> list[list[str]]:
    return [cmd for cmd in recorded if cmd[:3] == ["herdr", "agent", "prompt"]]


def _pane_reads(recorded: list[list[str]]) -> list[list[str]]:
    return [cmd for cmd in recorded if cmd[:3] == ["herdr", "pane", "read"]]


def test_unowned_review_dispatch_with_draft_refuses(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-02: an unowned live worker holding a draft is not prompted.

    Evidence before the edit: at the frozen revision the default sender calls
    ``say`` with no inspection, so this test fails by observing an ``agent
    prompt`` and no StagedInputError-class stop on the unit.
    """
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.launch_receipt = {"owned": False}
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(
        orchestrate,
        monkeypatch,
        [_claude_composer_pane("❯ operator draft that was never sent")],
    )
    prior_status = fixer.status
    prior_requests = list(fixer.fix_requests)

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == []
    assert _prompt_calls(recorded) == []
    assert "already holds staged input" in fixer.note
    assert isinstance(orchestrate.StagedInputError, type)
    assert fixer.status == prior_status
    assert fixer.fix_requests == prior_requests


def test_unowned_review_dispatch_with_empty_sends(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the guard: an unowned empty pane is inspected, then sent."""
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.launch_receipt = {"owned": False}
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(
        orchestrate,
        monkeypatch,
        [_claude_composer_pane("❯ ")],
    )

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == ["api-builder"]
    assert len(_pane_reads(recorded)) == 1
    assert len(_prompt_calls(recorded)) == 1
    assert fixer.status == "running"


def test_owned_review_dispatch_inspects_once_before_its_send(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal review F06: an owned worker is inspected too. The launcher's owned exemption
    covers only the first write into a pane created seconds earlier; this write lands hours
    or days later into a session the operator has been watching, so it goes through
    should_guard_pane_write with wrote_before true. One read, one prompt, then running."""
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.launch_receipt = {"owned": True}
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(orchestrate, monkeypatch, [_claude_composer_pane("❯ ")])

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == ["api-builder"]
    assert len(_pane_reads(recorded)) == 1
    assert len(_prompt_calls(recorded)) == 1
    assert fixer.status == "running"
    assert fixer.launch_receipt["input_box"] == "empty"


def test_a_live_worker_with_no_pane_is_prompted_without_a_read(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal review cycle 2, F53: a live worker with an agent handle but no recorded pane
    cannot be inspected; the writer prompts it through the handle -- one prompt, zero pane
    reads, no stop."""
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.pane_id = None
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(orchestrate, monkeypatch, [])

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == ["api-builder"]
    assert _pane_reads(recorded) == []
    assert len(_prompt_calls(recorded)) == 1
    assert fixer.status == "running"


def test_owned_review_dispatch_with_draft_refuses(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The consequence F06 names: a draft in an owned worker's composer stops the dispatch
    instead of being concatenated onto and submitted."""
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.launch_receipt = {"owned": True}
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(
        orchestrate, monkeypatch, [_claude_composer_pane("❯ operator draft that was never sent")]
    )

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == []
    assert _prompt_calls(recorded) == []
    assert "already holds staged input" in fixer.note
    assert fixer.status != "running"


def test_adopted_review_dispatch_without_a_receipt_is_unowned(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REL-09: an adopted unit (no receipt, owned unset) is inspected as unowned."""
    controller = _controller(orchestrate)
    fixer = _worker(orchestrate, "api-builder", "review-fixer", "src/api")
    fixer.launch_receipt = {}
    run = _run(orchestrate, fixer, controller)
    routing = orchestrate.route_review_result(
        run,
        _result("repairs_requested", _request("fix-api", "review-fixer", "src/api/routes.py")),
        agents=_live(fixer),
    )
    recorded = _record_herdr_boundary(
        orchestrate,
        monkeypatch,
        [_claude_composer_pane("❯ operator draft that was never sent")],
    )
    prior_status = fixer.status

    dispatched = orchestrate.dispatch_review_routing(routing)

    assert dispatched == []
    assert _prompt_calls(recorded) == []
    assert "already holds staged input" in fixer.note
    assert fixer.status == prior_status


def test_unowned_land_resubmit_with_draft_refuses(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The land path: an unowned controller holding a draft is not resubmitted. The stop
    is recorded on the controller, reported, and raised so `land` exits 4 (cycle 2, F42);
    the pending flag stays set for the next land."""
    controller = _controller(orchestrate)
    controller.launch_receipt = {"owned": False}
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, controller)
    run.review_resubmit_pending = True
    recorded = _record_herdr_boundary(
        orchestrate,
        monkeypatch,
        [_claude_composer_pane("❯ operator draft that was never sent")],
    )
    prior_status = controller.status

    with pytest.raises(orchestrate.StagedInputError, match="already holds staged input"):
        orchestrate.resubmit_review_if_ready(run, "0123456789abcdef")

    assert _prompt_calls(recorded) == []
    assert "already holds staged input" in controller.note
    assert controller.status == prior_status
    assert run.review_resubmit_pending is True


def test_owned_land_resubmit_inspects_once_before_its_send(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal review F06 on the land path: an owned controller is inspected before the
    resubmission, exactly one read, then sent."""
    controller = _controller(orchestrate)
    controller.launch_receipt = {"owned": True}
    worker = _worker(orchestrate, "builder", "review-fixer", "src")
    run = _run(orchestrate, worker, controller)
    run.review_resubmit_pending = True
    recorded = _record_herdr_boundary(orchestrate, monkeypatch, [_claude_composer_pane("❯ ")])

    resubmitted = orchestrate.resubmit_review_if_ready(run, "0123456789abcdef")

    assert resubmitted is True
    assert len(_pane_reads(recorded)) == 1
    assert len(_prompt_calls(recorded)) == 1
    assert controller.status == "running"
    assert run.review_resubmit_pending is False


def test_a_staged_stop_on_one_controller_does_not_block_the_other_controllers_resubmit(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Terminal review F23: two scoped controllers both owed a resubmission. The first holds
    an operator draft; the second is clear. The stop is recorded on the first, printed with
    its name, and left pending for the next land; the second is still resubmitted. At the
    frozen revision the first controller's StagedInputError escaped the loop and the second
    was skipped silently, on every subsequent land, in the same order."""
    first = _controller(orchestrate)
    first.name, first.lifecycle, first.pane_id = "review-a", "a", "pane-a"
    first.launch_receipt = {"owned": True}
    second = _controller(orchestrate)
    second.name, second.lifecycle, second.pane_id = "review-b", "b", "pane-b"
    second.launch_receipt = {"owned": True}
    run = _run(orchestrate, first, second)
    run.write_review_slot(first, review_resubmit_pending=True)
    run.write_review_slot(second, review_resubmit_pending=True)
    recorded = _record_herdr_boundary(
        orchestrate,
        monkeypatch,
        [
            _claude_composer_pane("❯ operator draft that was never sent"),
            _claude_composer_pane("❯ "),
        ],
    )

    with pytest.raises(orchestrate.StagedInputError, match="withheld for review-a"):
        orchestrate.resubmit_review_if_ready(run, "0123456789abcdef")

    prompts = _prompt_calls(recorded)
    assert len(prompts) == 1
    assert prompts[0][3] == second.agent_name
    assert second.status == "running"
    assert run.review_slot(second)["review_resubmit_pending"] is False
    assert first.status == "done"
    assert run.review_slot(first)["review_resubmit_pending"] is True
    assert "already holds staged input" in first.note
    out = capsys.readouterr().out
    assert "review-a" in out and "already holds staged input" in out
    assert "resubmitted landed revision 0123456789abcdef through review-b" in out


def test_land_exits_4_when_the_resubmission_is_withheld_on_staged_input(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Terminal review cycle 2, F42: at 7aa0e3b7 a withheld resubmission returned False into
    land's success path and land exited 0, while every other resubmission failure exited 4.
    The stop now reaches the failure handler: exit 4, the reason printed, the pending flag
    kept; once the composer is clear the next land resubmits and exits 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    controller = _controller(orchestrate)
    controller.launch_receipt = {"owned": False}
    worker = _worker(orchestrate, "builder", "review-fixer", "src", live=False)
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[worker, controller],
        review_result=_result("repairs_requested"),
        review_outcome="repairs_requested",
        review_resubmit_pending=True,
    )
    _support.save_run(run, test_store())
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    dumps = iter(
        [_claude_composer_pane("❯ operator draft that was never sent"), _claude_composer_pane("❯ ")]
    )
    prompts: list[str] = []
    real_run = orchestrate.run

    def herdr_boundary(cmd: list[str], *a: Any, **k: Any) -> Any:
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            prompts.append(cmd[4])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, next(dumps), "")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(orchestrate, "run", herdr_boundary)

    assert orchestrate.cmd_merge(NS(clean=False)) == 4
    first_output = capsys.readouterr().out
    assert "REVIEW RESUBMIT FAILED" in first_output
    assert "already holds staged input" in first_output
    assert prompts == []
    withheld = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert withheld.review_resubmit_pending is True
    assert withheld.unit("code-review-controller").status == "done"

    assert orchestrate.cmd_merge(NS(clean=False)) == 0
    assert len(prompts) == 1
    assert orchestrate.Run.load(_support.TEST_ISSUE, test_store()).review_resubmit_pending is False


def test_the_documented_land_exit_codes_are_the_ones_the_command_returns() -> None:
    """Terminal review cycle 2, F66: two of land's exit codes were documented nowhere. The
    command document carries the table; this reads the codes out of it and out of cmd_merge's
    own return statements and requires the two sets to be equal."""
    doc = (SCRIPT.parents[3] / "com.infiquetra.claude" / "commands" / "orchestrate.md").read_text(encoding="utf-8")
    table = doc[doc.index("exit-code table:") :]
    documented = {int(m) for m in re.findall(r"^\| (\d) \|", table, re.MULTILINE)}
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    land = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "cmd_merge"
    )
    returned: set[int] = set()
    for node in ast.walk(land):
        if isinstance(node, ast.Return) and node.value is not None:
            for constant in ast.walk(node.value):
                if isinstance(constant, ast.Constant) and isinstance(constant.value, int):
                    returned.add(constant.value)
    assert documented == returned, (documented, returned)


def test_replacement_name_and_workspace_identify_the_controller_lifecycle(
    orchestrate: ModuleType,
) -> None:
    """#902: scoped mint names the lifecycle, not the template slice, and does not compound -fix-."""
    controller = orchestrate.Unit(
        name="codereview-providers",
        vendor="grok",
        task="/saga:code-review review the run branch",
        role="review-controller",
        merge=False,
        lifecycle="providers",
        status="done",
    )
    template = _worker(
        orchestrate,
        "work-shell-slice-shell-fix-old",
        "review-fixer",
        "src/shell",
        live=False,
    )
    template.workspace = "shell-ws"
    run = _run(orchestrate, template, controller)
    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request("fix-providers", "review-fixer", "src/providers/a.py"),
        ),
        agents=[],
        controller=controller,
    )
    replacement = routing.replacements[0]
    assert replacement.name.startswith("providers-repair-")
    assert "shell" not in replacement.name
    assert "-fix-fix-" not in replacement.name
    assert replacement.workspace == "providers-repair"
    assert "minted from" in replacement.note
    assert "work-shell-slice-shell-fix-old" in replacement.note


def test_route_review_result_skips_terminal_units_and_mints_instead(
    orchestrate: ModuleType,
) -> None:
    """#892: a failed live worker is not reused and is not flipped back to running."""
    controller = _controller(orchestrate)
    failed = _worker(orchestrate, "retired", "review-fixer", "src/api")
    failed.status = orchestrate.FAILED
    run = _run(orchestrate, failed, controller)
    routing = orchestrate.route_review_result(
        run,
        _result(
            "repairs_requested",
            _request("fix-retired", "review-fixer", "src/api/x.py"),
        ),
        agents=_live(failed),
        controller=controller,
    )
    assert routing.dispatches == []
    assert len(routing.replacements) == 1
    orchestrate.dispatch_review_routing(routing, sender=lambda _unit, _text: None)
    assert failed.status == orchestrate.FAILED

    live = _worker(orchestrate, "live-fixer", "review-fixer", "src/api")
    failed2 = _worker(orchestrate, "still-failed", "review-fixer", "src/api")
    failed2.status = orchestrate.FAILED
    run2 = _run(orchestrate, live, failed2, controller)
    routing2 = orchestrate.route_review_result(
        run2,
        _result(
            "repairs_requested",
            _request("fix-live", "review-fixer", "src/api/y.py"),
        ),
        agents=_live(live, failed2),
        controller=controller,
    )
    assert [unit.name for unit, _req in routing2.dispatches] == ["live-fixer"]
    assert routing2.replacements == []


def test_review_result_refuses_cycle_regressed_overwrite_of_a_terminal_slot(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#893: a cycle-1 accepted artifact cannot overwrite a stored cycle-cap result."""
    stored = json.dumps(
        {
            "schema": "review_result.v2",
            "outcome": "cycle_cap_best_available",
            "cycle_history": [{"cycle": 1}, {"cycle": 2}, {"cycle": 3}],
            "fix_requests": [],
        },
        sort_keys=True,
    )
    incoming = json.dumps(
        {
            "schema": "review_result.v2",
            "outcome": "accepted",
            "cycle_history": [{"cycle": 1}],
            "fix_requests": [],
        },
        sort_keys=True,
    )
    controller = _controller(orchestrate)
    run = _run(orchestrate, controller)
    run.write_review_slot(
        controller, review_result=stored, review_outcome="cycle_cap_best_available"
    )
    result_path = tmp_path / "incoming.json"
    result_path.write_text(incoming)
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="terminal review outcome"):
        orchestrate.cmd_review_result(NS(file=str(result_path)))
    reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert reloaded.review_slot(controller)["review_outcome"] == "cycle_cap_best_available"
    assert reloaded.review_slot(controller)["review_result"] == stored

    result_path.write_text(stored)
    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0

    shorter = json.dumps(
        {
            "schema": "review_result.v2",
            "outcome": "repairs_requested",
            "cycle_history": [{"cycle": 1}],
            "fix_requests": [],
        },
        sort_keys=True,
    )
    longer = json.dumps(
        {
            "schema": "review_result.v2",
            "outcome": "repairs_requested",
            "cycle_history": [{"cycle": 1}, {"cycle": 2}],
            "fix_requests": [],
        },
        sort_keys=True,
    )
    run2 = _run(orchestrate, _controller(orchestrate))
    run2.write_review_slot(
        run2.review_controller(), review_result=longer, review_outcome="repairs_requested"
    )
    _support.save_run(run2, test_store())
    result_path.write_text(shorter)
    with pytest.raises(SystemExit, match="cycle-regressed"):
        orchestrate.cmd_review_result(NS(file=str(result_path)))


def test_land_in_lifecycle_a_does_not_resubmit_a_running_controller_in_lifecycle_b(
    orchestrate: ModuleType,
) -> None:
    """#884: landing A does not retarget B, and a running controller is not resubmitted."""
    controller_a = orchestrate.Unit(
        name="cr-a",
        vendor="grok",
        task="/saga:code-review a",
        role="review-controller",
        lifecycle="cA",
        merge=False,
        status="done",
        pane_id="pane-a",
        agent_name="agent-a",
    )
    controller_b = orchestrate.Unit(
        name="cr-b",
        vendor="grok",
        task="/saga:code-review b",
        role="review-controller",
        lifecycle="cB",
        merge=False,
        status=orchestrate.RUNNING,
        pane_id="pane-b",
        agent_name="agent-b",
    )
    worker_a = orchestrate.Unit(
        name="fix-a",
        vendor="claude",
        task="/saga:work a",
        role="review-fixer",
        lifecycle="cA",
        status="done",
    )
    run = _run(orchestrate, worker_a, controller_a, controller_b)
    run.write_review_slot(controller_a, review_resubmit_pending=True)
    run.write_review_slot(controller_b, review_resubmit_pending=True)
    sent: list[tuple[str, str]] = []

    def capture(unit: Any, text: str) -> None:
        sent.append((unit.name, text))

    orchestrate.resubmit_review_if_ready(
        run,
        "HEAD-OF-B",
        sender=capture,
        landed_names=["fix-a"],
        landed_revisions={"fix-a": "REV-A"},
    )
    assert [name for name, _text in sent] == ["cr-a"]
    assert "REV-A" in sent[0][1]
    assert "HEAD-OF-B" not in sent[0][1]
    assert run.review_slot(controller_b)["review_resubmit_pending"] is True


def test_a_non_staged_resubmit_write_failure_does_not_abort_later_controllers(
    orchestrate: ModuleType,
) -> None:
    """#956: a SystemExit on the first controller still attempts the second."""
    first = orchestrate.Unit(
        name="review-a",
        vendor="grok",
        task="/saga:code-review a",
        role="review-controller",
        lifecycle="cA",
        merge=False,
        status="done",
        pane_id="pane-a",
        agent_name="agent-a",
    )
    second = orchestrate.Unit(
        name="review-b",
        vendor="grok",
        task="/saga:code-review b",
        role="review-controller",
        lifecycle="cB",
        merge=False,
        status="done",
        pane_id="pane-b",
        agent_name="agent-b",
    )
    run = _run(orchestrate, first, second)
    run.write_review_slot(first, review_resubmit_pending=True)
    run.write_review_slot(second, review_resubmit_pending=True)
    sent: list[str] = []

    def flaky(unit: Any, _text: str) -> None:
        if unit.name == "review-a":
            raise SystemExit("pane run failed")
        sent.append(unit.name)

    with pytest.raises(SystemExit, match="pane run failed"):
        orchestrate.resubmit_review_if_ready(run, "deadbeef", sender=flaky)
    assert sent == ["review-b"]


def test_land_exit_4_outranks_leftover_landing_path_exit_3(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#959: leftover landing-path cleanup does not hide an owed resubmission."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    controller = _controller(orchestrate)
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[controller],
        review_result=_result("repairs_requested"),
        review_outcome="repairs_requested",
        review_resubmit_pending=True,
        operator_fix_requests=[_request("held", "human", "src/x.py")],
    )
    _support.save_run(run, test_store())
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    # The landing worktree went with the landing bookkeeping (issue #1025); the turn's own
    # detached worktree is what can now be left behind, so that is the cleanup failure to
    # simulate. It only exists when a unit actually merges, so one does.
    _git(repo, "checkout", "-q", "-b", "orch/review-run-worker", "orch/review-run")
    _commit(repo, "worker.txt")
    _git(repo, "checkout", "-q", "main")
    run.units.append(
        orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="x",
            branch="orch/review-run-worker",
            status=orchestrate.DONE,
        )
    )
    _support.save_run(run, test_store())
    original_run = orchestrate.run

    def fail_remove(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ["git", "worktree", "remove", "--force"] and "merge-review-run" in cmd[-1]:
            return subprocess.CompletedProcess(cmd, 1, "", "simulated cleanup failure")
        return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

    monkeypatch.setattr(orchestrate, "run", fail_remove)
    assert orchestrate.cmd_merge(NS(clean=False)) == 4
    output = capsys.readouterr().out
    assert "CLEANUP FAILED" in output
    assert "operator-owned fix" in output


def test_land_exits_4_when_resubmission_is_held_by_operator_fix_requests(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#974: operator-hold is exit 4, not a green 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    base = _git_out(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "orch/review-run")
    run = orchestrate.Run(
        run_id="review-run",
        source="test",
        base=base,
        branch="orch/review-run",
        units=[_controller(orchestrate)],
        review_result=_result("repairs_requested"),
        review_outcome="repairs_requested",
        review_resubmit_pending=True,
        operator_fix_requests=[_request("held-fix", "human", "src/op.py")],
    )
    _support.save_run(run, test_store())
    # The merge turn refreshes its comparison ref and refuses when that fetch fails
    # (issue #1025), so every repository here gets the local bare remote.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)
    assert orchestrate.cmd_merge(NS(clean=False)) == 4
    assert "operator-owned fix" in capsys.readouterr().out


def test_retrying_review_result_does_not_reprompt_a_worker_that_already_took_its_repair(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#976: a partial dispatch retry must not prompt the worker that already took its repair."""
    first = _worker(orchestrate, "first", "review-fixer", "src/a.py")
    second = _worker(orchestrate, "second", "review-fixer", "src/b.py")
    run = _run(orchestrate, first, second, _controller(orchestrate))
    raw = _result(
        "repairs_requested",
        _request("fix-a", "review-fixer", "src/a.py"),
        _request("fix-b", "review-fixer", "src/b.py"),
    )

    result_path = tmp_path / "result.json"
    result_path.write_text(raw)
    _support.save_run(run, test_store())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: _live(first, second))
    sent: list[str] = []

    def sender(unit: Any, _text: str) -> None:
        sent.append(unit.name)
        if unit.name == "second":
            raise orchestrate.StagedInputError("composer holds staged input")

    monkeypatch.setattr(orchestrate, "_send_with_pane_guard", sender)
    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 1
    assert sent == ["first", "second"]
    sent.clear()
    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 1
    assert sent == ["second"]
