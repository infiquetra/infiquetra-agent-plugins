"""#776: Orchestrate owns reviewer-session transport; saga's runner is gone.

The required regression is one Opus review-controller plus one Grok 4.6 reviewer
seat, both launched as Orchestrate-owned named units, one typed review_result.v2,
and no engine_session_runner process. Mutation: a plain review prompt or a direct
reviewer launch is refused before any session is created.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

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


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "orchestrate" / "skills" / "orchestrate" / "scripts" / "orchestrate.py"
REGISTRY = ROOT / "plugins" / "saga" / "references" / "engine-registry.yaml"
STAGE_SKILLS = (
    ROOT / "plugins" / "saga" / "skills" / "code-review" / "SKILL.md",
    ROOT / "plugins" / "saga" / "skills" / "doc-review" / "SKILL.md",
    ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md",
    ROOT / "plugins" / "saga" / "skills" / "ideate" / "SKILL.md",
)
RETIRED_LAUNCH = (
    "engine_session_runner.py launch",
    "engine_offer.py offer",
    "engine_offer.py remember",
)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_orchestrate_review_transport", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name + "\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
    return r


def _write_run(repo: Path, units: list[dict[str, Any]] | None = None, **overrides: Any) -> None:
    """Write this test's run into the per-issue run record (issue #1025).

    There is no `.orchestrate/run.json` any more. The store is derived from the repository rather
    than resolved, because the resolved store is the developer's own `.claude/saga/runs`.
    """
    _support.ensure_origin(repo)
    base = subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "rev-parse", "HEAD"], cwd=repo, check=False, capture_output=True, text=True
    ).stdout.strip()
    block: dict[str, Any] = {"run_id": "r1", "source": "a test", "base": base, "branch": "orch/r1"}
    block.update(overrides)
    _support.write_record(
        test_store(),
        TEST_ISSUE,
        units=[_support.fill_unit_row(u) for u in (units or [])],
        **block,
    )


def _controller_row() -> dict[str, Any]:
    return {
        "name": "code-review-controller",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "task": "/saga:code-review the run branch",
        "role": "review-controller",
        "merge": False,
        "status": "pending",
    }


def _grok_seat_row(
    *, task: str | None = None, role: str | None = "external-reviewer"
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "grok-reviewer",
        "vendor": "grok",
        "model": "grok-4.6",
        "effort": "high",
        "task": task
        or "advisory whole-diff findings for the frozen revision; emit findings-schema",
        "status": "pending",
    }
    if role is not None:
        row["role"] = role
    return row


def _accepted_result() -> str:
    return json.dumps(
        {
            "schema": "review_result.v2",
            "outcome": "accepted",
            "fix_requests": [],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def test_review_transport_controller_plus_grok_seat_plan_is_admitted(
    orchestrate: ModuleType,
) -> None:
    units = orchestrate.plan_units({"units": [_controller_row(), _grok_seat_row()]})

    assert [(u.name, u.role, u.vendor, u.model) for u in units] == [
        ("code-review-controller", "review-controller", "claude", "opus"),
        ("grok-reviewer", "external-reviewer", "grok", "grok-4.6"),
    ]
    orchestrate.assert_review_transport(units)


def test_review_transport_go_launches_both_via_orchestrate_not_the_retired_runner(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(repo, [_controller_row(), _grok_seat_row()])
    monkeypatch.chdir(repo)
    launched: list[tuple[str, str]] = []

    def fake_launch(unit: Any, backend: str = "inline", *, review_elsewhere: bool = False) -> None:
        launched.append((unit.name, unit.vendor))
        unit.status = orchestrate.RUNNING
        unit.agent_name = f"{unit.name}-agent"
        unit.pane_id = f"pane-{unit.name}"
        unit.tab_id = f"tab-{unit.name}"

    monkeypatch.setattr(orchestrate, "launch", fake_launch)
    assert orchestrate.cmd_go(NS(limit=0)) == 0

    assert launched == [
        ("code-review-controller", "claude"),
        ("grok-reviewer", "grok"),
    ]
    run = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert {u.name: u.worktree for u in run.units}
    assert all(u.worktree and Path(u.worktree).exists() for u in run.units)
    assert not (SCRIPT.parent / "engine_session_runner.py").exists()
    assert not (ROOT / "plugins" / "saga" / "scripts" / "engine_session_runner.py").exists()


def test_review_transport_records_one_typed_result_and_no_duplicate_review(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_run(repo, [_controller_row(), _grok_seat_row()])
    monkeypatch.chdir(repo)
    result_path = tmp_path / "result.json"
    result_path.write_text(_accepted_result())

    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    restored = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert restored.review_outcome == "accepted"
    assert json.loads(restored.review_result)["schema"] == "review_result.v2"
    with pytest.raises(SystemExit, match="exactly one top-level Code Review controller"):
        orchestrate.plan_units(
            {
                "units": [
                    _controller_row(),
                    {**_controller_row(), "name": "second-controller"},
                    _grok_seat_row(),
                ]
            }
        )


def test_review_transport_mutation_refuses_plain_review_prompt_before_session(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutated = _grok_seat_row(task="review this PR for bugs", role=None)
    _write_run(repo, [_controller_row(), mutated])
    monkeypatch.chdir(repo)
    launched: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "launch",
        lambda unit, backend="inline", **_: launched.append(unit.name),
    )
    monkeypatch.setattr(
        orchestrate,
        "make_worktree",
        lambda *args, **kwargs: pytest.fail("session worktree created for a refused review"),
    )

    with pytest.raises(SystemExit, match="plain review prompt"):
        orchestrate.cmd_go(NS(limit=0))
    assert launched == []


def test_review_transport_mutation_refuses_direct_reviewer_launch_before_session(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct = _grok_seat_row(task="review the run branch", role=None)
    _write_run(repo, [_controller_row(), direct])
    monkeypatch.chdir(repo)
    launched: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "launch",
        lambda unit, backend="inline", **_: launched.append(unit.name),
    )
    monkeypatch.setattr(
        orchestrate,
        "make_worktree",
        lambda *args, **kwargs: pytest.fail("session worktree created for a direct launch"),
    )

    with pytest.raises(SystemExit, match="plain review prompt"):
        orchestrate.cmd_go(NS(limit=0))
    assert launched == []


def test_review_transport_admits_a_named_seat_whose_task_reads_like_a_review(
    orchestrate: ModuleType,
) -> None:
    """A seat's task reads like a review instruction because that is what a seat is for.

    Refusing it left the run record with no way to express the reviewer the leaf
    requires, while the docs told authors to use exactly this shape.
    """
    for task in (
        "review the diff at 41e318c1",
        "Please review this whole diff and return findings",
        "code review the frozen revision",
    ):
        units = orchestrate.plan_units({"units": [_controller_row(), _grok_seat_row(task=task)]})
        orchestrate.assert_review_transport(units)
        assert [u.role for u in units] == ["review-controller", "external-reviewer"]


@pytest.mark.parametrize(
    "task",
    [
        "review PR #831 for bugs",
        "Review changes on the branch",
        "do a code review of the branch",
        "take a look and review my diff",
    ],
)
def test_review_transport_refuses_rephrased_bespoke_reviews(
    orchestrate: ModuleType, task: str
) -> None:
    """Refusal keys on the missing role, not on one blessed phrasing.

    A wording match admitted every one of these while refusing the seats above.
    """
    with pytest.raises(SystemExit, match="plain review prompt"):
        orchestrate.plan_units({"units": [_controller_row(), _grok_seat_row(task=task, role=None)]})


def test_review_transport_leaves_declared_work_roles_alone(orchestrate: ModuleType) -> None:
    """A review-fixer talks about review findings; it is not a bespoke review."""
    fixer = {
        "name": "fixer",
        "vendor": "claude",
        "model": "sonnet",
        "effort": "medium",
        "task": "address review findings in plugins/saga",
        "role": "review-fixer",
        "paths": ["plugins/saga"],
        "status": "pending",
    }
    units = orchestrate.plan_units({"units": [_controller_row(), fixer]})
    orchestrate.assert_review_transport(units)


def test_review_transport_refuses_engine_prefs_and_the_retired_runner(
    orchestrate: ModuleType,
) -> None:
    with pytest.raises(SystemExit, match="engine_prefs"):
        orchestrate.assert_no_engine_prefs({"engine_prefs": {"code-review": {"intent": "none"}}})
    with pytest.raises(SystemExit, match="retired saga external-engine runner"):
        orchestrate.plan_units(
            {
                "units": [
                    _controller_row(),
                    {
                        **_grok_seat_row(),
                        "task": "python3 plugins/saga/scripts/engine_session_runner.py launch",
                    },
                ]
            }
        )


@pytest.mark.parametrize(
    "task",
    [
        "run engine_session_runner.py launch",
        "use engine_offer to pick a vendor",
        "admit the roster with external_only first",
    ],
)
def test_review_transport_refuses_every_retired_transport_name(
    orchestrate: ModuleType, task: str
) -> None:
    """All three retired modules, with or without the .py suffix."""
    with pytest.raises(SystemExit, match="retired saga external-engine runner"):
        orchestrate.plan_units({"units": [_controller_row(), _grok_seat_row(task=task)]})


def test_review_transport_loads_legacy_run_files_without_engine_prefs(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A record carrying the retired `engine_prefs` key: the record preserves an unknown
    # top-level field, and orchestrate ignores this one on load exactly as it always has.
    _support.write_record(
        test_store(),
        _support.TEST_ISSUE,
        units=[_support.fill_unit_row(_controller_row())],
        run_id="legacy",
        source="old",
        base="0" * 40,
        branch="",
        extra_top_level={"engine_prefs": {"code-review": {"intent": "none"}}},
    )
    monkeypatch.chdir(tmp_path)
    loaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert not hasattr(loaded, "engine_prefs")
    loaded.save()
    # The retired key is PRESERVED by the record rather than dropped -- that is the record's own
    # unknown-top-level-field rule -- and orchestrate never reads it. Both halves matter: the
    # key survives a newer writer, and this plugin ignores it.
    saved = _support.read_record(test_store(), _support.TEST_ISSUE)
    assert "engine_prefs" not in saved["orchestrate"]
    assert saved["engine_prefs"] == {"code-review": {"intent": "none"}}


def test_stage_skills_do_not_invoke_retired_transport_as_launch_path() -> None:
    """Guards saga's stage skills. Those files are not in this catalog until saga is imported."""
    missing = [path for path in STAGE_SKILLS if not path.is_file()]
    if missing:
        pytest.skip(
            "saga stage skills are not in this catalog yet; "
            "the check is the upstream repository layout"
        )
    for path in STAGE_SKILLS:
        text = path.read_text(encoding="utf-8")
        for needle in RETIRED_LAUNCH:
            assert needle not in text, f"{path} still invokes {needle}"
        assert "HALT" in text
        assert "engine-registry.yaml" in text
        assert "capability metadata" in text


def test_review_transport_admits_explicit_plan_unit_mentioning_review_records(
    orchestrate: ModuleType,
) -> None:
    """A role-less /saga:plan unit mentioning review records is not a standalone review prompt (#837)."""
    plan_unit = {
        "name": "plan-fable",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "task": "/saga:plan #847: improve plugins and check the two review records",
        "status": "done",
    }
    units = orchestrate.plan_units({"units": [plan_unit, _controller_row()]})
    orchestrate.assert_review_transport(units)
    assert units[0].name == "plan-fable"
    assert units[0].role is None
    assert units[1].name == "code-review-controller"
    assert units[1].role == "review-controller"


def test_review_transport_admits_explicit_doc_review_unit(
    orchestrate: ModuleType,
) -> None:
    """A role-less $saga:doc-review unit reviewing a plan is not a standalone Code Review prompt (#837)."""
    for task in (
        "$saga:doc-review docs/plans/2026-08-25-voice-plan.md implementation plan",
        "/doc-review docs/plans/2026-08-25-voice-plan.md implementation plan",
        "/saga:doc-review docs/plans/2026-08-25-voice-plan.md implementation plan",
    ):
        doc_review_unit = {
            "name": "docreview-grok",
            "vendor": "grok",
            "model": "grok-4.6",
            "effort": "high",
            "task": task,
            "status": "done",
        }
        units = orchestrate.plan_units({"units": [doc_review_unit, _controller_row()]})
        orchestrate.assert_review_transport(units)
        assert units[0].name == "docreview-grok"
        assert units[0].role is None
        assert units[1].name == "code-review-controller"
        assert units[1].role == "review-controller"


def test_review_transport_voice_run_regression_preserves_loadability_and_rejects_untyped(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate orch-2026-08-25-voice: completed plan + doc-review units stay loadable (#837).

    Appending exactly one typed review-controller allows status/go/expand to proceed without
    raising plain review prompt, while genuine untyped prompts remain rejected before launch.
    """
    plan_unit = {
        "name": "plan-fable",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "task": "/saga:plan #847: improve plugins and check the two review records",
        "status": "done",
    }
    docreview_unit = {
        "name": "docreview-grok",
        "vendor": "grok",
        "model": "grok-4.6",
        "effort": "high",
        "task": "$saga:doc-review docs/plans/2026-08-25-voice-plan.md",
        "status": "done",
    }
    _write_run(repo, [plan_unit, docreview_unit, _controller_row()])
    monkeypatch.chdir(repo)

    # Run loads cleanly
    run = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert len(run.units) == 3
    orchestrate.assert_review_transport(run.units)

    # Launching eligible units works without review-transport assertion failure
    launched: list[str] = []
    monkeypatch.setattr(
        orchestrate,
        "launch",
        lambda unit, backend="inline", **_: launched.append(unit.name),
    )
    assert orchestrate.cmd_go(NS(limit=0)) == 0
    assert launched == ["code-review-controller"]

    # If a genuine untyped review prompt is added, it is still rejected before launch
    untyped = _grok_seat_row(task="review this PR for bugs", role=None)
    _write_run(repo, [plan_unit, docreview_unit, _controller_row(), untyped])
    with pytest.raises(SystemExit, match="plain review prompt"):
        orchestrate.cmd_go(NS(limit=0))


@pytest.mark.parametrize(
    "task",
    [
        "/saga:plan #847: check review records",
        "$saga:plan #847: check review records",
        "/plan #847: check review records",
        "/saga:doc-review docs/plans/plan.md",
        "$saga:doc-review docs/plans/plan.md",
        "/doc-review docs/plans/plan.md",
        "/saga:founder-review STRATEGY.md",
        "/founder-review STRATEGY.md",
        "/ceo-review STRATEGY.md",
        "/saga:work 847-o2-837: fix review transport",
        "/work 847-o2-837: address review findings",
        "/qa #847: verify review fixes",
        "/retro #847: review learnings",
    ],
)
def test_review_transport_admits_explicit_non_code_review_capabilities(
    orchestrate: ModuleType, task: str
) -> None:
    """Explicit non-Code-Review capabilities with the word 'review' are admitted (#837)."""
    unit = {
        "name": "explicit-unit",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "task": task,
        "status": "pending",
    }
    units = orchestrate.plan_units({"units": [unit, _controller_row()]})
    orchestrate.assert_review_transport(units)
    assert units[0].role is None


@pytest.mark.parametrize(
    "task",
    [
        "/saga:review this PR for bugs",
        "$saga:review this PR for bugs",
        "/saga:not-a-real-capability review this PR for bugs",
        "$saga:unknown-capability review this PR for bugs",
        "/review this PR for bugs",
        "$review this PR for bugs",
        "/not-a-capability review this PR for bugs",
    ],
)
def test_review_transport_refuses_non_allowlisted_namespaced_review_prompts(
    orchestrate: ModuleType, task: str
) -> None:
    """Non-allowlisted namespaced or pseudo-capability review prompts are refused (#837)."""
    unit = _grok_seat_row(task=task, role=None)
    with pytest.raises(SystemExit, match="plain review prompt"):
        orchestrate.plan_units({"units": [_controller_row(), unit]})
