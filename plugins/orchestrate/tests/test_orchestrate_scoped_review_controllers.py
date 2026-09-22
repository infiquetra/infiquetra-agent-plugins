"""Several independent Code Review controllers in one run, each owning its own target (#877).

One review phase is still one controller.  What this proves is the *other* shape: a run carrying
several independent child lifecycles, each with its own frozen review target and its own typed
``review_result.v2``.  Before this, Orchestrate refused that at both load and expand, so a campaign
with three ready targets could only review them serially through a single run-global controller --
and that controller carries ``review_outcome``, ``review_resubmit_pending`` and
``operator_fix_requests``, so serial reuse risks reading one target's typed state as another's.

The guard itself is not weakened.  An *unscoped* second controller is still the accidental panel it
has always been, and still fails with the same message.  What distinguishes the deliberate shape is
that every controller declares its own ``lifecycle``.
"""

from __future__ import annotations

import argparse
import contextlib
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
    spec = importlib.util.spec_from_file_location("_orchestrate_scoped_controllers", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _controller(
    orchestrate: ModuleType,
    name: str,
    *,
    lifecycle: str | None = None,
    status: str | None = None,
) -> Any:
    return orchestrate.Unit(
        name=name,
        vendor="grok",
        task="/saga:code-review review the frozen target",
        role="review-controller",
        lifecycle=lifecycle,
        merge=False,
        status=status or orchestrate.PENDING,
    )


def _run(orchestrate: ModuleType, *units: Any, ceiling: int | None = None) -> Any:
    """A run attached to its own throwaway record, so ``save()`` has somewhere to write.

    ``Run.save`` takes no path any more -- it writes the unit rows and this plugin's block back
    into the issue's record (issue #1025) -- so a run built by hand has to say which record it
    belongs to. These tests never touch a repository; the store is a temporary directory.
    """
    run = orchestrate.Run(
        run_id="scoped-run",
        source="test",
        base="base",
        units=list(units),
        review_controller_ceiling=ceiling,
    )
    return _support.attach_record(run, test_store())


# --- 1. the single-controller default is untouched, including today's error ------------------


def test_single_controller_run_still_resolves_to_that_controller(orchestrate: ModuleType) -> None:
    run = _run(orchestrate, _controller(orchestrate, "cr"))
    assert run.review_controller().name == "cr"
    assert orchestrate.assert_single_review_controller(run.units) is None


def test_two_unscoped_controllers_still_fail_with_todays_message(orchestrate: ModuleType) -> None:
    """The accidental panel must keep failing exactly as it did, or the guard is weakened."""
    units = [_controller(orchestrate, "cr-a"), _controller(orchestrate, "cr-b")]

    # Assert the FULL accessor string by equality. A substring check is not enough: the phrase
    # "create exactly one" appears in 3.0.7 as well, so asserting it proves nothing about whether
    # this message survived the change.
    with pytest.raises(SystemExit) as accessor:
        _run(orchestrate, *units).review_controller()
    assert str(accessor.value) == (
        "this run has more than one Code Review controller; one review phase is one "
        "top-level controller invocation"
    )

    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert str(excinfo.value) == (
        "review phase has 2 controller units (cr-a, cr-b); create exactly one "
        "top-level Code Review controller, or give each one its own `lifecycle`"
    )


def test_partially_scoped_controllers_are_refused(orchestrate: ModuleType) -> None:
    """Scoping is all-or-nothing; one missing lifecycle is still the accidental panel."""
    units = [
        _controller(orchestrate, "cr-a", lifecycle="c2"),
        _controller(orchestrate, "cr-b"),
    ]
    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert "create exactly one" in str(excinfo.value)


def test_two_controllers_claiming_one_lifecycle_are_refused(orchestrate: ModuleType) -> None:
    units = [
        _controller(orchestrate, "cr-a", lifecycle="c2"),
        _controller(orchestrate, "cr-b", lifecycle="c2"),
    ]
    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert "both claim" in str(excinfo.value)


# --- 2. several scoped controllers load, and each owns its own typed state -------------------


def test_three_scoped_controllers_load(orchestrate: ModuleType) -> None:
    """The blocked Auralis shape: three ready targets, three independent controllers."""
    units = [
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        _controller(orchestrate, "cr-c6", lifecycle="c6"),
    ]
    assert orchestrate.assert_single_review_controller(units) is None
    run = _run(orchestrate, *units)
    assert [u.name for u in run.review_controllers()] == ["cr-c2", "cr-c4", "cr-c6"]


def test_each_scoped_controller_keeps_its_own_typed_state(orchestrate: ModuleType) -> None:
    """The whole point: one controller's typed state is never legible as another's."""
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        _controller(orchestrate, "cr-c6", lifecycle="c6"),
    )
    c2, c4, c6 = run.review_controllers()

    run.write_review_slot(c2, review_outcome="accepted", review_resubmit_pending=False)
    run.write_review_slot(c4, review_outcome="repairs_requested", review_resubmit_pending=True)

    assert run.review_slot(c2)["review_outcome"] == "accepted"
    assert run.review_slot(c4)["review_outcome"] == "repairs_requested"
    assert run.review_slot(c6)["review_outcome"] is None
    assert run.review_slot(c2)["review_resubmit_pending"] is False
    assert run.review_slot(c4)["review_resubmit_pending"] is True

    # And nothing leaked into the run-level single-controller view.
    assert run.review_outcome is None
    assert run.review_resubmit_pending is False


def test_operator_fix_requests_do_not_leak_between_controllers(orchestrate: ModuleType) -> None:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
    )
    c2, c4 = run.review_controllers()
    run.review_slot(c2)["operator_fix_requests"].append({"fix_id": "only-c2"})
    assert run.review_slot(c4)["operator_fix_requests"] == []
    assert run.operator_fix_requests == []


def test_scoped_state_round_trips_through_save_and_load(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        ceiling=2,
    )
    run.write_review_slot(run.review_controllers()[0], review_outcome="accepted")
    run.save()

    reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert reloaded.review_controller_ceiling == 2
    assert reloaded.review_states["cr-c2"]["review_outcome"] == "accepted"
    assert reloaded.review_states.get("cr-c4", {}).get("review_outcome") is None
    assert [u.lifecycle for u in reloaded.review_controllers()] == ["c2", "c4"]


# --- 3. a result routed to the wrong controller is refused ----------------------------------


def test_selecting_a_controller_by_name_or_lifecycle(orchestrate: ModuleType) -> None:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
    )
    assert run.review_controller_for("cr-c4").name == "cr-c4"
    assert run.review_controller_for("c4").name == "cr-c4"


def test_result_aimed_at_a_non_controller_unit_is_refused(orchestrate: ModuleType) -> None:
    worker = orchestrate.Unit(
        name="w1", vendor="claude", task="/saga:work build it", role="review-fixer"
    )
    run = _run(orchestrate, _controller(orchestrate, "cr-c2", lifecycle="c2"), worker)
    with pytest.raises(SystemExit) as excinfo:
        run.review_controller_for("w1")
    assert "is not a Code Review controller" in str(excinfo.value)


def test_result_aimed_at_an_unknown_controller_is_refused(orchestrate: ModuleType) -> None:
    run = _run(orchestrate, _controller(orchestrate, "cr-c2", lifecycle="c2"))
    with pytest.raises(SystemExit) as excinfo:
        run.review_controller_for("cr-c9")
    assert "no Code Review controller" in str(excinfo.value)


def test_ambiguous_result_is_refused_rather_than_guessed(orchestrate: ModuleType) -> None:
    """Guessing would write one target's typed state into another's slot."""
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
    )
    with pytest.raises(SystemExit) as excinfo:
        run.review_controller()
    assert "--controller" in str(excinfo.value)


# --- 4. the declared concurrency ceiling is honoured -----------------------------------------


def test_ceiling_holds_back_surplus_controllers(orchestrate: ModuleType) -> None:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        _controller(orchestrate, "cr-c6", lifecycle="c6"),
        ceiling=2,
    )
    assert [u.name for u in run.eligible()] == ["cr-c2", "cr-c4"]


def test_ceiling_counts_already_running_controllers(orchestrate: ModuleType) -> None:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.RUNNING),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        _controller(orchestrate, "cr-c6", lifecycle="c6"),
        ceiling=2,
    )
    assert [u.name for u in run.eligible()] == ["cr-c4"]


def test_no_ceiling_means_no_holdback(orchestrate: ModuleType) -> None:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        _controller(orchestrate, "cr-c6", lifecycle="c6"),
    )
    assert len(run.eligible()) == 3


def test_ceiling_never_holds_back_non_controller_units(orchestrate: ModuleType) -> None:
    worker = orchestrate.Unit(
        name="w1", vendor="claude", task="/saga:work build", role="review-fixer"
    )
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.RUNNING),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        worker,
        ceiling=1,
    )
    assert [u.name for u in run.eligible()] == ["w1"]


# --- 5. a code-review PATH segment is not an invocation ---------------------------------------


@pytest.mark.parametrize(
    "task",
    [
        "/saga:doc-review docs/code-review/2026-08-27-target.md",
        "/saga:work write the result to docs/code-review/out.md",
        "/saga:plan consult the docs/code-review directory",
        "see plugins/saga/code-review/references for the lens list",
        "read a/b/code-review.md first",
        # These two are rejected only by the RIGHT-hand command boundary. Without them that
        # boundary can regress unnoticed, because the left lookbehind already handles mid-path.
        "/code-review.md",
        "see /code-review.md first",
    ],
)
def test_a_code_review_path_segment_is_not_a_controller(orchestrate: ModuleType, task: str) -> None:
    """The misclassification that made the one-controller error unreadable.

    Three ordinary Document Review units were classified as Code Review controllers purely because
    their brief named the directory where committed typed results live, so an operator hitting the
    error could not tell a real second controller from a false positive.
    """
    assert orchestrate.is_code_review_task(task) is False
    unit = orchestrate.Unit(name="u", vendor="claude", task=task)
    assert orchestrate.is_review_controller(unit) is False


@pytest.mark.parametrize(
    "task",
    [
        "/saga:code-review review the frozen target",
        "$saga:code-review at revision 9c06fb4",
        "/code-review the diff",
        "First fetch, then /saga:code-review the run branch",
        # A trailing period terminates a sentence, not the command's claim to be one.
        "invoke /code-review.",
        "/saga:code-review, then stop",
    ],
)
def test_real_invocations_still_classify(orchestrate: ModuleType, task: str) -> None:
    """Narrowing must not cost a genuine invocation in any supported spelling."""
    assert orchestrate.is_code_review_task(task) is True


def test_explicit_role_still_wins_over_task_text(orchestrate: ModuleType) -> None:
    """An explicit role is authoritative in both directions; text is only the legacy fallback."""
    pathy = orchestrate.Unit(
        name="cr",
        vendor="grok",
        task="/saga:doc-review docs/code-review/x.md",
        role="review-controller",
    )
    assert orchestrate.is_review_controller(pathy) is True

    worker = orchestrate.Unit(
        name="w", vendor="claude", task="/saga:code-review something", role="review-fixer"
    )
    assert orchestrate.is_review_controller(worker) is False


# --- 6. the command paths themselves, not just the accessors -------------------------------
#
# The first version of this suite tested accessors and never called a command, so every consumer
# of the review state -- land, reap, status, start -- stayed unwired while the suite went green.


def _scoped_run_on_disk(orchestrate: ModuleType, tmp_path: Path) -> Any:
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE),
        _controller(orchestrate, "cr-c4", lifecycle="c4", status=orchestrate.DONE),
        ceiling=2,
    )
    for unit in run.units:
        unit.branch = f"orch/{unit.name}"
    run.save()
    return run


def test_reapable_keeps_a_controller_whose_own_slot_is_pending(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reaping here closes the session the controller still needs in order to resubmit."""
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, c4 = run.review_controllers()
    run.write_review_slot(c2, review_resubmit_pending=True)
    monkeypatch.setattr(orchestrate, "landed", lambda *a, **k: True)

    assert orchestrate.reapable(c2, run) is False, "pending controller must not be reaped"
    assert orchestrate.reapable(c4, run) is True, "a clear controller stays reapable"


def test_reapable_keeps_a_controller_holding_operator_requests(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, _ = run.review_controllers()
    run.review_slot(c2)["operator_fix_requests"].append({"fix_id": "held"})
    monkeypatch.setattr(orchestrate, "landed", lambda *a, **k: True)
    assert orchestrate.reapable(c2, run) is False


def test_status_shows_each_scoped_controller_outcome(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Consulting only run-level fields showed a scoped run as having no Code Review result."""
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, c4 = run.review_controllers()
    run.write_review_slot(c2, review_outcome="accepted")
    run.write_review_slot(c4, review_outcome="repairs_requested", review_resubmit_pending=True)
    run.save()

    orchestrate.cmd_status(NS())
    out = capsys.readouterr().out
    assert "cr-c2 (lifecycle c2)" in out and "accepted" in out
    assert "cr-c4 (lifecycle c4)" in out and "repairs_requested" in out
    assert "awaiting Code Review resubmission" in out


def test_resubmit_sends_each_pending_controller_independently(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two independent targets must both recover; one must not block the other."""
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, c4 = run.review_controllers()
    run.write_review_slot(c2, review_resubmit_pending=True)
    run.write_review_slot(c4, review_resubmit_pending=True)

    sent: list[str] = []
    assert orchestrate.resubmit_review_if_ready(
        run, "deadbeef", sender=lambda unit, _text: sent.append(unit.name)
    )
    assert sorted(sent) == ["cr-c2", "cr-c4"]
    assert run.review_slot(c2)["review_resubmit_pending"] is False
    assert run.review_slot(c4)["review_resubmit_pending"] is False


def test_one_controller_operator_hold_does_not_block_the_other(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, c4 = run.review_controllers()
    run.write_review_slot(c2, review_resubmit_pending=True)
    run.write_review_slot(c4, review_resubmit_pending=True)
    run.review_slot(c2)["operator_fix_requests"].append({"fix_id": "held"})

    sent: list[str] = []
    assert orchestrate.resubmit_review_if_ready(
        run, "deadbeef", sender=lambda unit, _text: sent.append(unit.name)
    )
    assert sent == ["cr-c4"], "the unblocked controller still resubmits"
    assert run.review_slot(c2)["review_resubmit_pending"] is True


def test_a_worker_in_another_lifecycle_does_not_block_resubmit(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker belonging to another lifecycle is not this controller's business."""
    monkeypatch.chdir(tmp_path)
    run = _scoped_run_on_disk(orchestrate, tmp_path)
    c2, _ = run.review_controllers()
    other = orchestrate.Unit(
        name="w-c4", vendor="claude", task="/saga:work build", role="review-fixer", lifecycle="c4"
    )
    other.fix_requests.append({"fix_id": "belongs-to-c4"})
    run.units.append(other)
    run.write_review_slot(c2, review_resubmit_pending=True)

    sent: list[str] = []
    assert orchestrate.resubmit_review_if_ready(
        run, "deadbeef", sender=lambda unit, _text: sent.append(unit.name)
    )
    assert sent == ["cr-c2"]


def test_cmd_start_carries_and_validates_the_ceiling(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ceiling that silently fails to load is worse than none."""
    assert orchestrate.review_ceiling_from_plan({}) is None
    assert orchestrate.review_ceiling_from_plan({"review_controller_ceiling": 3}) == 3
    for bad in (0, -1, "3", True, 2.5):
        with pytest.raises(SystemExit):
            orchestrate.review_ceiling_from_plan({"review_controller_ceiling": bad})

    # And prove cmd_start itself ingests it. Building the Run by hand would stay green if a
    # regression dropped review_ceiling_from_plan from cmd_start, which is the whole risk.
    repo = tmp_path / "startrepo"
    repo.mkdir()

    def run_git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run_git("init", "-q", "-b", "main")
    run_git("config", "user.email", "t@t")
    run_git("config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    run_git("add", "-A")
    run_git("commit", "-qm", "seed")
    monkeypatch.chdir(repo)

    for stub in (
        "assert_agent_launcher_available",
        "assert_vendors_available",
        "assert_saga_reachable",
    ):
        monkeypatch.setattr(orchestrate, stub, lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "make_worktree", lambda *a, **k: None)

    plan_path = repo / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "run_id": "ceil",
                "source": "t",
                "review_controller_ceiling": 2,
                "units": [
                    {
                        "name": "cr-c2",
                        "vendor": "grok",
                        "role": "review-controller",
                        "lifecycle": "c2",
                        "merge": False,
                        "task": "/saga:code-review t",
                    },
                    {
                        "name": "cr-c4",
                        "vendor": "grok",
                        "role": "review-controller",
                        "lifecycle": "c4",
                        "merge": False,
                        "task": "/saga:code-review t",
                    },
                ],
            }
        )
    )
    # `start` requires the record and never creates one (issue #1025): admission writes it, so
    # this fixture stands in for that step before the command runs.
    _support.write_record(test_store(), _support.TEST_ISSUE, units=None)
    # Worktree creation may still refuse in a bare fixture; the record is written before that,
    # and the record is what this test is about.
    with contextlib.suppress(SystemExit):
        orchestrate.cmd_start(NS(plan=str(plan_path), base=None, branch=None))
    assert orchestrate.Run.load(_support.TEST_ISSUE, test_store()).review_controller_ceiling == 2


def test_late_lifecycle_assignment_migrates_run_global_review_state(
    orchestrate: ModuleType,
) -> None:
    """#898: a controller reviewed unscoped, then gained a lifecycle, must still see its result."""
    controller = _controller(orchestrate, "cr-late")
    run = _run(orchestrate, controller)
    raw = json.dumps({"schema": "review_result.v2", "outcome": "accepted"}, sort_keys=True)
    requests = [{"fix_id": "held"}]
    run.write_review_slot(
        controller,
        review_result=raw,
        review_outcome="accepted",
        review_resubmit_pending=True,
        operator_fix_requests=requests,
    )
    assert run.review_result == raw
    controller.lifecycle = "c2"
    slot = run.review_slot(controller)
    assert slot["review_result"] == raw
    assert slot["review_outcome"] == "accepted"
    assert slot["review_resubmit_pending"] is True
    assert slot["operator_fix_requests"] == requests
    assert slot["operator_fix_requests"] is not run.operator_fix_requests


def test_late_lifecycle_assignment_refuses_a_conflicting_named_slot(
    orchestrate: ModuleType,
) -> None:
    """#898: a named slot that already holds different bytes is a stop, not an overwrite."""
    controller = _controller(orchestrate, "cr-late", lifecycle="c2")
    run = _run(orchestrate, controller)
    named = json.dumps({"schema": "review_result.v2", "outcome": "accepted"}, sort_keys=True)
    global_raw = json.dumps(
        {"schema": "review_result.v2", "outcome": "cycle_cap_best_available"},
        sort_keys=True,
    )
    run.review_states[controller.name] = {
        "review_result": named,
        "review_outcome": "accepted",
        "review_resubmit_pending": False,
        "operator_fix_requests": [],
    }
    run.review_result = global_raw
    run.review_outcome = "cycle_cap_best_available"
    with pytest.raises(SystemExit, match="conflicts with run-global"):
        run.review_slot(controller)
    assert run.review_states[controller.name]["review_result"] == named
    assert run.review_result == global_raw


def test_wait_reason_names_the_ceiling_holdback(orchestrate: ModuleType) -> None:
    """An empty wait_reason means eligible-not-yet-launched, so starvation must not look like that."""
    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.RUNNING),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
        ceiling=1,
    )
    held = [u for u in run.units if u.name == "cr-c4"][0]
    assert "ceiling" in run.wait_reason(held)


def test_an_ambiguous_selector_is_refused(orchestrate: ModuleType) -> None:
    """A name equal to another controller's lifecycle would silently store the wrong verdict."""
    run = _run(
        orchestrate,
        _controller(orchestrate, "c4", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
    )
    with pytest.raises(SystemExit) as excinfo:
        run.review_controller_for("c4")
    assert "matches 2" in str(excinfo.value)


def test_a_controller_name_colliding_with_a_lifecycle_is_refused_at_load(
    orchestrate: ModuleType,
) -> None:
    units = [
        _controller(orchestrate, "c4", lifecycle="c2"),
        _controller(orchestrate, "cr-c4", lifecycle="c4"),
    ]
    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert "could not tell them apart" in str(excinfo.value)


def test_whitespace_only_lifecycles_do_not_bypass_the_guard(orchestrate: ModuleType) -> None:
    """`c2` and `c2 ` must not count as two distinct lifecycles."""
    units = [
        _controller(orchestrate, "cr-a", lifecycle="c2"),
        _controller(orchestrate, "cr-b", lifecycle="c2 "),
    ]
    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert "both claim" in str(excinfo.value)


def test_a_blank_lifecycle_counts_as_unscoped(orchestrate: ModuleType) -> None:
    units = [
        _controller(orchestrate, "cr-a", lifecycle="c2"),
        _controller(orchestrate, "cr-b", lifecycle="   "),
    ]
    with pytest.raises(SystemExit) as excinfo:
        orchestrate.assert_single_review_controller(units)
    assert "create exactly one" in str(excinfo.value)


# --- 7. routing, land and start: the commands the first two suites never called -------------


def test_a_replacement_worker_stays_inside_its_controller_lifecycle(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A replacement minted without a lifecycle leaves the child lifecycle entirely.

    `_lifecycle_units` then cannot see it, so resubmit stops waiting on its outstanding repair and
    land resubmits the frozen target before the repair exists.
    """
    monkeypatch.chdir(tmp_path)
    controller = _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE)
    template = orchestrate.Unit(
        name="w-c2",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        lifecycle="c2",
        paths=["src/"],
    )
    run = _run(orchestrate, controller, template)
    request = {
        "fix_id": "fix-1",
        "owner": "review-fixer",
        "touched_paths": ["src/"],
        "summary": "s",
    }
    replacement = orchestrate._replacement_worker(template, request, controller, {"w-c2"})
    assert replacement.lifecycle == "c2", "replacement must not leave its controller's lifecycle"
    run.units.append(replacement)
    assert replacement in orchestrate._lifecycle_units(run, controller)


def test_an_unscoped_worker_is_a_mint_template_not_a_shared_holder(
    orchestrate: ModuleType,
) -> None:
    """A lifecycle-less Work unit stays reachable as a TEMPLATE, never as a shared live holder.

    Reusing one live lifecycle-less worker from several scoped controllers couples the very targets
    this scoping isolates. It remains a mint template, and `_replacement_worker` stamps the copy.
    """
    controller = _controller(orchestrate, "cr-c2", lifecycle="c2")
    plain = orchestrate.Unit(
        name="w", vendor="claude", task="/saga:work build", role="review-fixer", paths=["src/"]
    )
    run = _run(orchestrate, controller, plain)
    assert plain in orchestrate._lifecycle_units(run, controller, shared_ok=True)
    assert plain not in orchestrate._lifecycle_units(run, controller)


def test_two_scoped_controllers_do_not_share_one_live_unscoped_fixer(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The residual the third review cycle caught: one shared session couples two frozen targets.

    Landing that worker would discharge both repairs, and until then each child's parked bag blocks
    the other's resubmit. Each controller must get its own stamped replacement instead.
    """
    monkeypatch.chdir(tmp_path)
    c2 = _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE)
    c4 = _controller(orchestrate, "cr-c4", lifecycle="c4", status=orchestrate.DONE)
    shared = orchestrate.Unit(
        name="w-shared",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        paths=["src/"],
        pane_id="pane-shared",
        agent_name="agent-shared",
    )
    run = _run(orchestrate, c2, c4, shared)
    run.save()
    live = [{"name": "agent-shared", "agent_status": "idle"}]

    def _result(fix_id: str) -> str:
        return json.dumps(
            {
                "schema": "review_result.v2",
                "outcome": "repairs_requested",
                "best_available_revision": "a" * 40,
                "fix_requests": [
                    {
                        "fix_id": fix_id,
                        "owner": "review-fixer",
                        "touched_paths": ["src/"],
                        "summary": "s",
                    }
                ],
            }
        )

    orchestrate.route_review_result(run, _result("fix-c2"), agents=live, controller=c2)
    orchestrate.route_review_result(run, _result("fix-c4"), agents=live, controller=c4)

    # The shared worker must not be carrying both targets' repairs.
    assert len(shared.fix_requests) <= 1, "one live worker must not hold two targets' repairs"
    holders = {
        orchestrate._fix_request_id(req): unit.name
        for unit in run.units
        for req in unit.fix_requests
    }
    assert holders.get("fix-c2") != holders.get("fix-c4"), "each target needs its own holder"
    for unit in run.units:
        if unit.fix_requests and unit is not shared:
            assert unit.lifecycle in {"c2", "c4"}, "a minted holder must carry a lifecycle"


def test_another_lifecycles_worker_is_not_reachable(orchestrate: ModuleType) -> None:
    controller = _controller(orchestrate, "cr-c2", lifecycle="c2")
    foreign = orchestrate.Unit(
        name="w-c4",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        lifecycle="c4",
    )
    run = _run(orchestrate, controller, foreign)
    assert foreign not in orchestrate._lifecycle_units(run, controller)


def test_cmd_merge_resubmits_a_scoped_pending_controller(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Land exited 0 without ever telling a scoped controller to resubmit.

    Driven through the real command against a real repository, because the whole finding was that
    the helper worked while the command that calls it did not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    def run_git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run_git("init", "-q", "-b", "main")
    run_git("config", "user.email", "t@t")
    run_git("config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    run_git("add", "-A")
    run_git("commit", "-qm", "seed")
    run_git("branch", "orch/proof-run")
    # The merge turn refreshes its comparison ref and refuses when that fetch fails (issue
    # #1025), so this repository gets the local bare remote every migrated fixture gets.
    _support.ensure_origin(repo)
    monkeypatch.chdir(repo)

    run = _run(
        orchestrate,
        _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE),
        ceiling=1,
    )
    run.branch = "orch/proof-run"
    run.write_review_slot(run.review_controllers()[0], review_resubmit_pending=True)
    run.save()

    reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert reloaded.review_slot(reloaded.review_controllers()[0])["review_resubmit_pending"] is True

    sent: list[str] = []
    real_run = orchestrate.run

    def prompt_door(cmd: list[str], *a: Any, **k: Any) -> Any:
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            sent.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["herdr", "pane", "read"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(orchestrate, "run", prompt_door)
    orchestrate.cmd_merge(NS(clean=False))

    after = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    controller = after.review_controllers()[0]
    assert sent == [controller.agent_name or controller.name], (
        "land must tell the scoped controller to resubmit"
    )
    assert after.review_slot(after.review_controllers()[0])["review_resubmit_pending"] is False


def test_run_load_validates_the_ceiling_from_a_hand_edited_record(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`false` or `0` in a hand-edited run.json would otherwise become a hold-all ceiling."""
    monkeypatch.chdir(tmp_path)
    run = _run(orchestrate, _controller(orchestrate, "cr-c2", lifecycle="c2"), ceiling=2)
    run.save()

    path = test_store() / f"issue-{_support.TEST_ISSUE}.json"
    record = json.loads(path.read_text())
    for bad in (False, 0, "2"):
        record["orchestrate"]["review_controller_ceiling"] = bad
        path.write_text(json.dumps(record))
        with pytest.raises(SystemExit):
            orchestrate.Run.load(_support.TEST_ISSUE, test_store())


def test_lifecycle_whitespace_is_normalised_at_load(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """review-result, land, status and reap load without passing through the plan guard."""
    monkeypatch.chdir(tmp_path)
    run = _run(orchestrate, _controller(orchestrate, "cr-c2", lifecycle="c2"))
    run.save()
    path = test_store() / f"issue-{_support.TEST_ISSUE}.json"
    record = json.loads(path.read_text())
    record["units"][0]["lifecycle"] = "  c2  "
    path.write_text(json.dumps(record))

    reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    assert reloaded.review_controllers()[0].lifecycle == "c2"
    assert reloaded.review_controller_for("c2").name == "cr-c2"


def test_status_binds_work_by_identity_not_name_prefix(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """One controller name prefixing another must not steal the longer name's outstanding Work."""
    monkeypatch.chdir(tmp_path)
    short = _controller(orchestrate, "cr", lifecycle="c2", status=orchestrate.DONE)
    longer = _controller(orchestrate, "cr-extra", lifecycle="c4", status=orchestrate.DONE)
    worker = orchestrate.Unit(
        name="w-c4",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        lifecycle="c4",
    )
    worker.fix_requests.append({"fix_id": "belongs-to-c4"})
    run = _run(orchestrate, short, longer, worker)
    run.write_review_slot(short, review_outcome="accepted")
    run.write_review_slot(longer, review_outcome="repairs_requested", review_resubmit_pending=True)
    run.save()

    orchestrate.cmd_status(NS())
    out = capsys.readouterr().out
    # The short-named controller has no outstanding Work of its own; only cr-extra does.
    assert "cr (lifecycle c2)" in out and "(recorded)" in out
    assert "awaiting landed Work repairs" in out


def test_unscoped_review_state_round_trips_through_the_slot(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unscoped run must behave exactly as before, and the two views must not diverge."""
    monkeypatch.chdir(tmp_path)
    run = _run(orchestrate, _controller(orchestrate, "cr"))
    controller = run.review_controllers()[0]
    run.write_review_slot(controller, review_outcome="accepted", review_resubmit_pending=False)

    assert run.review_outcome == "accepted", "run-level mirror keeps older readers working"
    assert run.review_slot(controller)["review_outcome"] == "accepted"
    run.save()

    reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    only = reloaded.review_controllers()[0]
    assert reloaded.review_outcome == "accepted"
    assert reloaded.review_slot(only)["review_outcome"] == "accepted"


def test_one_scoped_controller_also_mints_rather_than_sharing(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No carve-out for a single scoped controller.

    The controller count is read at route time, so a run that parks while it has one controller and
    later gains a second through `expand` would strand the first controller's repairs on a worker
    its own resubmit gate cannot see. Even with one controller the gate reads `shared_ok=False`, so
    a bag parked on an unscoped worker is invisible and land resubmits before the repair exists.
    """
    monkeypatch.chdir(tmp_path)
    only = _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE)
    plain = orchestrate.Unit(
        name="w-plain",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        paths=["src/"],
        pane_id="pane-plain",
        agent_name="agent-plain",
    )
    run = _run(orchestrate, only, plain)
    run.save()

    orchestrate.route_review_result(
        run,
        json.dumps(
            {
                "schema": "review_result.v2",
                "outcome": "repairs_requested",
                "best_available_revision": "b" * 40,
                "fix_requests": [
                    {
                        "fix_id": "fix-solo",
                        "owner": "review-fixer",
                        "touched_paths": ["src/"],
                        "summary": "s",
                    }
                ],
            }
        ),
        agents=[{"name": "agent-plain", "agent_status": "idle"}],
        controller=only,
    )

    assert plain.fix_requests == [], "a scoped controller must not park on a live unscoped worker"
    holders = [u for u in run.units if u.fix_requests]
    assert holders, "the repair must be parked somewhere"
    for holder in holders:
        assert holder.lifecycle == "c2", "the minted holder must carry the controller's lifecycle"
        assert holder in orchestrate._lifecycle_units(run, only), "resubmit must be able to see it"


def test_expanding_a_second_controller_does_not_orphan_the_first_ones_repairs(
    orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The expand-time hazard the carve-out created.

    `shared_hazard` was computed at route time from the controller count, so a run that parked while
    it had one scoped controller and then gained a second would leave the first controller's repairs
    on a worker its own resubmit gate can no longer see. With the carve-out gone, the holder is
    stamped at park time and stays owned however the run grows afterwards.
    """
    monkeypatch.chdir(tmp_path)
    first = _controller(orchestrate, "cr-c2", lifecycle="c2", status=orchestrate.DONE)
    plain = orchestrate.Unit(
        name="w-plain",
        vendor="claude",
        task="/saga:work build",
        role="review-fixer",
        paths=["src/"],
        pane_id="pane-plain",
        agent_name="agent-plain",
    )
    run = _run(orchestrate, first, plain)
    orchestrate.route_review_result(
        run,
        json.dumps(
            {
                "schema": "review_result.v2",
                "outcome": "repairs_requested",
                "best_available_revision": "c" * 40,
                "fix_requests": [
                    {
                        "fix_id": "fix-first",
                        "owner": "review-fixer",
                        "touched_paths": ["src/"],
                        "summary": "s",
                    }
                ],
            }
        ),
        agents=[{"name": "agent-plain", "agent_status": "idle"}],
        controller=first,
    )
    holders_before = {u.name for u in run.units if u.fix_requests}
    assert holders_before, "the repair must be parked"

    # Now a second controller arrives, as `expand` would add it.
    run.units.append(_controller(orchestrate, "cr-c4", lifecycle="c4"))

    owned = {u.name for u in orchestrate._lifecycle_units(run, first)}
    assert holders_before <= owned, (
        "the first controller's repairs must still be visible to its own resubmit gate "
        "after a second controller is expanded in"
    )
