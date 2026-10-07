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


def _write_run(
    repo: Path,
    units: list[dict[str, Any]] | None = None,
    *,
    extra_top_level: dict[str, Any] | None = None,
    **overrides: Any,
) -> None:
    """Write this test's run into the per-issue run record (issue #1025).

    There is no `.orchestrate/run.json` any more. The store is derived from the repository rather
    than resolved, because the resolved store is the developer's own `.claude/saga/runs`.
    ``extra_top_level`` replaces top-level record keys, which is how a test sets ``admission``.
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
        extra_top_level=extra_top_level,
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
    """A high record pane-launches the controller only. The external seat stays unlaunched."""
    _write_run(
        repo,
        [_controller_row(), _grok_seat_row()],
        extra_top_level={"admission": {"destination": "pr", "risk_tier": "high"}},
    )
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

    assert launched == [("code-review-controller", "claude")]
    run = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    controller = run.unit("code-review-controller")
    seat = run.unit("grok-reviewer")
    assert controller.worktree and Path(controller.worktree).exists()
    assert seat.worktree is None
    assert seat.pane_id is None
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


# --- issue #159: review-launch and the risk tier -------------------------------------------------

CANARY = "CANARY-answer-must-stay-unread"
TARGETED_STAFF = {"vendor": "claude", "model": "opus", "effort": "high"}
GROK_WORKER_STAFF = {"vendor": "grok", "model": "grok-4.6", "effort": "medium"}
SAME_VENDOR_WORKER = {"vendor": "claude", "model": "sonnet", "effort": "low"}


def _head(repo: Path) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _branches(repo: Path) -> str:
    return subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "branch", "--list", "--format=%(refname:short)"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _record_top(tier: str | None, staffing: dict[str, dict[str, str]]) -> dict[str, Any]:
    admission: dict[str, Any] = {"destination": "pr"}
    if tier is not None:
        admission["risk_tier"] = tier
    return {
        "admission": admission,
        "run_configuration": {
            "concurrency_allocation": {
                "value": 10,
                "chosen_by": "delivery_manager",
                "source": "profile",
            },
            "staffing_models_and_efforts": {
                "value": staffing,
                "chosen_by": "delivery_manager",
                "source": "profile",
            },
        },
    }


def _targeted_row() -> dict[str, Any]:
    return {
        "name": "targeted",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "task": "Write the targeted reviewer's answer for this packet.",
        "role": "targeted-reviewer",
        "merge": False,
        "status": "pending",
    }


def _stub_start(orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "assert_agent_launcher_available",
        "assert_vendors_available",
        "assert_saga_reachable",
    ):
        monkeypatch.setattr(orchestrate, name, lambda *a, **k: None)


def _install_review_runner(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    code: int = 0,
    answer: str = CANARY,
    help_code: int = 0,
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(argv: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if "--help" in argv and "--vendor" not in argv:
            return subprocess.CompletedProcess(argv, help_code, "", "")
        if "--out" in argv:
            out = Path(argv[argv.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "answer.json").write_text(answer)
            (out / "result.json").write_text("{}\n")
        return subprocess.CompletedProcess(argv, code, "", "")

    monkeypatch.setattr(orchestrate, "_reviewer_process", fake)
    monkeypatch.setattr(orchestrate, "assert_agent_launcher_available", lambda: None)
    monkeypatch.setattr(
        orchestrate,
        "_reviewer_answer_paths",
        lambda: {"prompt": "/tmp/reviewer-prompt.md", "schema": "/tmp/reviewer-schema.json"},
    )
    return calls


def _session_argv(calls: list[list[str]]) -> list[str]:
    return next(argv for argv in calls if "--vendor" in argv)


def _flag_pairs(argv: list[str]) -> dict[str, str]:
    review_at = argv.index("review")
    flags = argv[review_at + 1 :]
    return dict(zip(flags[0::2], flags[1::2], strict=True))


def _assert_nine_flags(argv: list[str]) -> dict[str, str]:
    script = next(part for part in argv if part.endswith("launcher.py"))
    assert argv[argv.index(script) + 1] == "review"
    flags = argv[argv.index("review") + 1 :]
    assert flags[0::2] == [
        "--vendor",
        "--model",
        "--effort",
        "--repo",
        "--head",
        "--packet",
        "--prompt",
        "--schema",
        "--out",
    ]
    assert "--open-search-cap" not in argv
    assert "--timeout" not in argv
    assert "--settings" not in argv
    return _flag_pairs(argv)


def _launch(
    orchestrate: ModuleType,
    repo: Path,
    packet: Path,
    seat: str,
    *,
    out: str | None = None,
) -> int:
    fields: dict[str, object] = {
        "seat": seat,
        "packet": str(packet),
        "repo": str(repo),
        "head": "abc123",
    }
    if out is not None:
        fields["out"] = out
    return orchestrate.cmd_review_launch(NS(**fields))


def test_review_launch_calls_the_reviewer_launch_and_leaves_the_answer_unread(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_run(
        repo,
        [_controller_row(), _targeted_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 0
    flags = _assert_nine_flags(_session_argv(calls))
    assert (flags["--vendor"], flags["--model"], flags["--effort"]) == ("claude", "opus", "high")
    assert flags["--packet"] == str(packet.resolve())
    answer = Path(flags["--out"]) / "answer.json"
    assert answer.read_text() == CANARY
    captured = capsys.readouterr()
    assert CANARY not in captured.out
    assert str(answer) in captured.out
    assert "launcher exit 0" in captured.out
    note = orchestrate.Run.load(TEST_ISSUE, test_store()).unit("targeted").note
    assert note.startswith("review-launch out ")
    assert CANARY not in note
    assert flags["--out"] in note


def test_review_launch_returns_the_launcher_exit_when_the_answer_is_not_json(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_run(
        repo,
        [_controller_row(), _targeted_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    _install_review_runner(orchestrate, monkeypatch, answer="this is not json " + CANARY)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 0
    assert CANARY not in capsys.readouterr().out


def test_review_launch_refuses_before_a_session_when_the_packet_is_missing(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        repo,
        [_controller_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    calls = _install_review_runner(orchestrate, monkeypatch)
    missing = repo / "missing-packet"
    assert _launch(orchestrate, repo, missing, "targeted-reviewer") == 2
    assert calls == []


def test_review_launch_refuses_a_packet_outside_the_run(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        repo,
        [_controller_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    outside = tmp_path / "elsewhere" / "packet"
    outside.mkdir(parents=True)
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, outside, "targeted-reviewer") == 2
    assert calls == []


def test_review_launch_refuses_a_repo_that_is_not_the_run(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        repo,
        [_controller_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    other = tmp_path / "other-repo"
    other.mkdir()
    assert (
        orchestrate.cmd_review_launch(
            NS(seat="targeted-reviewer", packet=str(packet), repo=str(other), head="abc123")
        )
        == 2
    )
    assert calls == []


def test_review_launch_refuses_an_out_directory_outside_the_store(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        repo,
        [_controller_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    outside = tmp_path / "not-the-store"
    assert _launch(orchestrate, repo, packet, "targeted-reviewer", out=str(outside)) == 2
    assert calls == []


def test_review_launch_refuses_a_shared_out_directory(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    noted = test_store() / "review-launch" / "issue-1" / "noted"
    external = _grok_seat_row()
    external["note"] = f"review-launch out {noted}"
    _write_run(
        repo,
        [_controller_row(), external],
        extra_top_level=_record_top("high", {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    loaded = orchestrate.Run.load(TEST_ISSUE, test_store())
    other_default = orchestrate._default_review_out(loaded, "external-reviewer", None)
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer", out=str(other_default)) == 2
    assert _launch(orchestrate, repo, packet, "targeted-reviewer", out=str(noted)) == 2
    assert calls == []


def test_review_launch_refuses_a_packet_that_overlaps_the_second_reviewer_output(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The second packet must not contain, equal, or sit inside a reviewer output."""
    _write_run(
        repo,
        [_controller_row(), _targeted_row(), _grok_seat_row()],
        extra_top_level=_record_top(
            "high",
            {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF},
        ),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 0
    answer = (
        test_store() / "review-launch" / "issue-1" / "targeted-reviewer" / "answer.json"
    )
    parent = answer.parents[1]
    assert answer.is_relative_to(parent)
    before = len(calls)
    assert _launch(orchestrate, repo, parent, "external-reviewer") == 2
    nested = answer.parent / "nested"
    nested.mkdir()
    assert _launch(orchestrate, repo, nested, "external-reviewer") == 2
    assert len(calls) == before
    assert "overlaps reviewer output" in capsys.readouterr().err


def test_review_launch_refuses_an_out_inside_the_packet_for_the_second_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An output directory inside the packet would leave the answer where the next seat reads."""
    _write_run(
        repo,
        [_controller_row(), _targeted_row()],
        extra_top_level=_record_top(
            "high",
            {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF},
        ),
    )
    monkeypatch.chdir(repo)
    packet = test_store() / "pkt"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer", out=str(packet / "first")) == 2
    assert _launch(orchestrate, repo, packet, "external-reviewer", out=str(packet)) == 2
    assert calls == []
    assert "overlaps reviewer output" in capsys.readouterr().err


def test_review_launch_refuses_when_the_review_subcommand_is_missing(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_run(
        repo,
        [_controller_row()],
        extra_top_level=_record_top(None, {"targeted-reviewer": TARGETED_STAFF}),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch, help_code=2)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 2
    assert orchestrate._UPDATE_REMEDIATION in capsys.readouterr().err
    assert all("--vendor" not in argv for argv in calls)


def test_go_does_not_open_a_pane_for_the_targeted_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(repo, [_controller_row(), _targeted_row()])
    monkeypatch.chdir(repo)
    launched: list[str] = []
    worktrees: list[str] = []
    real = orchestrate.make_worktree

    def spy(unit: Any, r: Any, root: Path) -> str | None:
        worktrees.append(unit.name)
        return real(unit, r, root)

    monkeypatch.setattr(orchestrate, "make_worktree", spy)
    monkeypatch.setattr(
        orchestrate,
        "launch",
        lambda unit, backend="inline", **_: launched.append(unit.name),
    )
    assert orchestrate.cmd_go(NS(limit=0)) == 0
    assert launched == ["code-review-controller"]
    assert worktrees == ["code-review-controller"]
    seat = orchestrate.Run.load(TEST_ISSUE, test_store()).unit("targeted")
    assert seat.worktree is None
    assert seat.pane_id is None


def test_the_agent_launcher_floor_is_1_7_2(orchestrate: ModuleType) -> None:
    assert orchestrate._declared_agent_launcher_floor() == (1, 7, 2)
    portable = json.loads((ROOT / "plugins" / "orchestrate" / "plugin.json").read_text())
    assert portable["version"] == "6.1.0"


def _start_review(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tier: str | None,
    staffing: dict[str, dict[str, str]],
    units: list[dict[str, Any]] | None = None,
) -> None:
    _stub_start(orchestrate, monkeypatch)
    monkeypatch.chdir(repo)
    _support.write_record(
        test_store(),
        TEST_ISSUE,
        units=None,
        extra_top_level=_record_top(tier, staffing),
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"run_id": "r1", "units": units if units is not None else [_controller_row()]})
    )
    assert (
        orchestrate.main(
            [
                "start",
                "--issue",
                str(TEST_ISSUE),
                "--store-root",
                str(test_store()),
                "--plan",
                str(plan),
                "--branch",
                "orch/r1",
                "--base",
                _head(repo),
            ]
        )
        == 0
    )


def _external_units(orchestrate: ModuleType) -> list[Any]:
    run = orchestrate.Run.load(TEST_ISSUE, test_store())
    return [unit for unit in run.units if unit.role == "external-reviewer"]


def test_a_high_record_starts_a_second_reviewer_on_the_other_staffed_vendor(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staffing = {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF}
    _start_review(orchestrate, repo, tmp_path, monkeypatch, tier="high", staffing=staffing)
    seats = _external_units(orchestrate)
    assert len(seats) == 1
    assert (seats[0].vendor, seats[0].model, seats[0].effort) == ("grok", "grok-4.6", "medium")
    assert seats[0].merge is False
    assert seats[0].after == []
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 0
    assert _launch(orchestrate, repo, packet, "external-reviewer") == 0
    sessions = [_flag_pairs(argv) for argv in calls if "--vendor" in argv]
    assert sessions[0]["--vendor"] == "claude"
    assert (sessions[1]["--vendor"], sessions[1]["--model"], sessions[1]["--effort"]) == (
        "grok",
        "grok-4.6",
        "medium",
    )
    assert sessions[0]["--packet"] == sessions[1]["--packet"]


def test_a_very_high_record_starts_a_second_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staffing = {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF}
    _start_review(orchestrate, repo, tmp_path, monkeypatch, tier="very-high", staffing=staffing)
    seats = _external_units(orchestrate)
    assert len(seats) == 1
    assert (seats[0].vendor, seats[0].model, seats[0].effort) == ("grok", "grok-4.6", "medium")


def test_a_high_record_starts_a_second_reviewer_for_each_lifecycle(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staffing = {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF}
    units = [
        {**_controller_row(), "name": "cr-c2", "lifecycle": "c2"},
        {**_controller_row(), "name": "cr-c4", "lifecycle": "c4"},
    ]
    _start_review(
        orchestrate, repo, tmp_path, monkeypatch, tier="high", staffing=staffing, units=units
    )
    seats = {unit.name: unit for unit in _external_units(orchestrate)}
    assert set(seats) == {"external-reviewer-c2", "external-reviewer-c4"}
    assert all(
        (unit.vendor, unit.model, unit.effort) == ("grok", "grok-4.6", "medium")
        for unit in seats.values()
    )


def test_the_same_vendor_runs_when_no_other_is_staffed(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staffing = {"targeted-reviewer": TARGETED_STAFF, "worker": SAME_VENDOR_WORKER}
    _start_review(orchestrate, repo, tmp_path, monkeypatch, tier="high", staffing=staffing)
    seats = _external_units(orchestrate)
    assert len(seats) == 1
    assert (seats[0].vendor, seats[0].model, seats[0].effort) == ("claude", "opus", "high")
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "external-reviewer") == 0
    flags = _flag_pairs(_session_argv(calls))
    assert (flags["--vendor"], flags["--model"], flags["--effort"]) == ("claude", "opus", "high")


def _assert_existing_external_is_refused(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tier: str | None,
) -> None:
    _stub_start(orchestrate, monkeypatch)
    monkeypatch.chdir(repo)
    staffing = {"targeted-reviewer": TARGETED_STAFF}
    _support.write_record(
        test_store(),
        TEST_ISSUE,
        units=None,
        extra_top_level=_record_top(tier, staffing),
    )
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"run_id": "r1", "units": [_controller_row(), _grok_seat_row()]}))
    before = _branches(repo)
    with pytest.raises(SystemExit, match="external-reviewer"):
        orchestrate.main(
            [
                "start",
                "--issue",
                str(TEST_ISSUE),
                "--store-root",
                str(test_store()),
                "--plan",
                str(plan),
                "--branch",
                "orch/not-created",
                "--base",
                _head(repo),
            ]
        )
    assert _branches(repo) == before
    assert "orch/not-created" not in _branches(repo)

    _write_run(
        repo,
        [_controller_row(), _grok_seat_row()],
        extra_top_level=_record_top(tier, staffing),
    )

    def refuse_worktree(*_a: object, **_k: object) -> None:
        raise AssertionError("go reached make_worktree")

    monkeypatch.setattr(orchestrate, "make_worktree", refuse_worktree)
    with pytest.raises(SystemExit, match="external-reviewer"):
        orchestrate.cmd_go(NS(limit=0))

    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch)
    assert _launch(orchestrate, repo, packet, "external-reviewer") == 2
    assert calls == []


def test_a_medium_record_starts_one_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_existing_external_is_refused(orchestrate, repo, tmp_path, monkeypatch, "medium")


def test_a_low_record_starts_one_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_existing_external_is_refused(orchestrate, repo, tmp_path, monkeypatch, "low")


def test_a_missing_tier_starts_one_reviewer(
    orchestrate: ModuleType,
    repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_existing_external_is_refused(orchestrate, repo, tmp_path, monkeypatch, None)


def test_the_second_reviewer_is_blind_and_uses_its_own_vendor(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_run(
        repo,
        [_controller_row(), _targeted_row(), _grok_seat_row()],
        extra_top_level=_record_top(
            "high",
            {"targeted-reviewer": TARGETED_STAFF, "worker": GROK_WORKER_STAFF},
        ),
    )
    monkeypatch.chdir(repo)
    packet = repo / "packet"
    packet.mkdir()
    calls = _install_review_runner(orchestrate, monkeypatch, answer=CANARY)
    assert _launch(orchestrate, repo, packet, "targeted-reviewer") == 0
    assert _launch(orchestrate, repo, packet, "external-reviewer") == 0
    first, second = [_flag_pairs(argv) for argv in calls if "--vendor" in argv]
    assert first["--packet"] == second["--packet"]
    assert CANARY not in " ".join(calls[-1])
    assert first["--out"] not in " ".join(calls[-1])
    assert second["--vendor"] == "grok"
    assert "review" in calls[-1]
    assert any(part.endswith("launcher.py") for part in calls[-1])


def test_review_transport_records_a_review_run(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A review run is stored verbatim and routes to the same outcome words as review_result.v2."""
    _write_run(repo, [_controller_row()])
    monkeypatch.chdir(repo)
    raw = json.dumps(
        {
            "schema": "review_records.v1",
            "kind": "review_run",
            "round": 1,
            "merge": {"allowed": True, "blocking": []},
            "findings": [],
        },
        sort_keys=True,
    )
    result_path = tmp_path / "review-run.json"
    result_path.write_text(raw)
    assert orchestrate.cmd_review_result(NS(file=str(result_path))) == 0
    restored = orchestrate.Run.load(TEST_ISSUE, test_store())
    assert restored.review_result == raw
    assert restored.review_outcome == "accepted"
    assert json.loads(restored.review_result)["kind"] == "review_run"


def test_review_transport_refuses_a_contradictory_review_run(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """allowed true with blocking ids is not an acceptance. The outcome stays unset."""
    _write_run(repo, [_controller_row()])
    monkeypatch.chdir(repo)
    raw = json.dumps(
        {
            "schema": "review_records.v1",
            "kind": "review_run",
            "round": 1,
            "merge": {"allowed": True, "blocking": ["rf:" + "ab" * 16]},
            "findings": [],
        },
        sort_keys=True,
    )
    result_path = tmp_path / "contradiction.json"
    result_path.write_text(raw)
    with pytest.raises(SystemExit, match="disagrees with merge"):
        orchestrate.cmd_review_result(NS(file=str(result_path)))
    restored = orchestrate.Run.load(TEST_ISSUE, test_store())
    assert restored.review_outcome is None
    assert restored.review_result == raw
