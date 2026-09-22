"""Issue #923 (plan U2): surfaced plan-save failures and the finished-plan routing contract.

Two defects, two repairs, both pinned here:

* **Save failures name the stranded plan document** (plan KTD2: a named failure, not a
  transaction). A filesystem failure while writing the tick already exits non-zero, but a
  bare traceback never names the plan document now left on disk with NO saga state
  referencing it. The CLI save path catches the ``OSError`` and names the ``--plan-path``
  document. The negative test engineers a REAL filesystem failure — the saga directory
  exists as a regular file, so ``mkdir`` inside ``save()`` raises — and asserts the raised
  failure and the non-zero exit, not a log line.
* **A finished plan routes onward, never back into /plan** (plan KTD1: the producer
  changes, the router does not). Phase 5.3 writes ``--phase-status complete`` on every
  save variant; the ``/loop`` dispatch table routes ``plan`` / ``complete`` onward to
  ``/doc-review``. The three contract surfaces are pinned equal so they cannot drift apart
  again, and Phase 5.3's exit-status instruction is pinned present.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from saga_plan_contract import plan_phase_53 as _plan_phase_53
from saga_plan_contract import save_blocks, save_options

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "saga"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
PLAN_SKILL = PLUGIN_ROOT / "skills" / "plan" / "SKILL.md"
SAGA_SPEC = PLUGIN_ROOT / "references" / "saga-spec.md"


def _load_module(script_name: str) -> ModuleType:
    """Load a script module by file path, registered in ``sys.modules``.

    Registration matters: ``saga.py`` defines a frozen ``@dataclass`` and (on Python
    3.12+) dataclass processing looks the class's ``__module__`` up in ``sys.modules``
    while building it. Registering under the bare name also lets this file share the same
    engine instance the other saga test modules load.
    """
    name = script_name.removesuffix(".py")
    path = SCRIPTS_DIR / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def saga() -> ModuleType:
    """The loaded ``saga`` engine module."""
    return _load_module("saga.py")


def _run_main(
    module: ModuleType,
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, Any]]:
    """Invoke a script's ``main()`` with a faked argv; return (rc, parsed JSON)."""
    monkeypatch.setattr("sys.argv", ["script", *argv])
    rc = module.main()
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _set_runner(
    saga: ModuleType, monkeypatch: pytest.MonkeyPatch, runner: Callable[..., Any]
) -> None:
    """Install ``runner`` as the subprocess seam everywhere the engine uses it.

    Patches both ``saga.subprocess.run`` and each function's captured keyword-only
    ``runner`` default (defaults bind at definition time, so the attribute patch alone
    never reaches a call that omits ``runner=``). Tests never shell out to git/gh.
    """
    monkeypatch.setattr(saga.subprocess, "run", runner)
    for fn_name in ("save", "current_git_state", "aggregate_context", "prior_prs"):
        fn = getattr(saga, fn_name)
        new_kwdefaults = dict(fn.__kwdefaults__ or {})
        new_kwdefaults["runner"] = runner
        monkeypatch.setattr(fn, "__kwdefaults__", new_kwdefaults)


def _stub_no_git(saga: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the engine's subprocess seam a no-op (empty git/gh output)."""

    def fake_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    _set_runner(saga, monkeypatch, fake_run)


# ---------------------------------------------------------------------------
# Save half: a failing save surfaces an error that names the stranded document
# ---------------------------------------------------------------------------


def test_failed_save_surfaces_error_naming_the_stranded_plan_document(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A filesystem failure writing the tick surfaces as a clean error naming the plan.

    The saga directory exists as a regular FILE, so ``mkdir(parents=True, exist_ok=True)``
    inside ``save()`` raises ``FileExistsError`` — a real filesystem failure, no mocked
    write path. Before the repair this escaped as a bare traceback that never named the
    plan document left on disk without a tick.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga_id = saga.derive_saga_id("issue", "923")
    blocker = tmp_path / saga.SAGAS_DIR / saga_id
    blocker.parent.mkdir(parents=True)
    blocker.write_text("not a directory", encoding="utf-8")
    plan_doc = "docs/plans/2026-08-30-state-correctness-plan.md"
    plan_file = tmp_path / plan_doc
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# Plan\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "script",
            "save",
            "--id",
            "923",
            "--lifecycle-phase",
            "plan",
            "--phase-status",
            "complete",
            "--plan-path",
            plan_doc,
        ],
    )
    rc = saga.main()
    err = capsys.readouterr().err

    assert rc == 2
    assert plan_doc in err, "the surfaced error must name the stranded plan document"
    assert "Traceback" not in err, "the failure must surface as a clean error, not a traceback"
    # Nothing half-written: no tick may exist for a save that failed before the write.
    assert saga.restore(tmp_path, saga_id) is None


def test_index_only_save_failure_reports_the_tick_tracked_not_stranded(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Index-only failure: the envelope lands first, so the tick IS tracked (review F05).

    ``_atomic_write`` fails because ``state.json.tmp`` is pre-created as a directory —
    the review's own repro — after the envelope write already succeeded. The surfaced
    error must name the index failure and must NOT claim the plan lost its tick:
    ``restore`` reads the envelope directly and never opens ``state.json``, so the
    lifecycle still sees the plan.

    Harness discipline (review T01): the fixture plan path deliberately contains no
    ``index`` substring, and the assertions match the index handler's OWN words — so
    deleting the ``SagaTickIndexWriteError`` handler (the mutation T01 performed) turns
    this test red instead of being satisfied by the fixture's own filename.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga_id = saga.derive_saga_id("issue", "923")
    plan_doc = "docs/plans/2026-08-30-envelope-landed-plan.md"
    plan_file = tmp_path / plan_doc
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# Plan\n", encoding="utf-8")
    # Block ONLY the state.json index rewrite; the envelope write still succeeds.
    blocker = tmp_path / saga.STATE_DIR / "state.json.tmp"
    blocker.parent.mkdir(parents=True)
    blocker.mkdir()

    monkeypatch.setattr(
        "sys.argv",
        [
            "script",
            "save",
            "--id",
            "923",
            "--lifecycle-phase",
            "plan",
            "--phase-status",
            "complete",
            "--plan-path",
            plan_doc,
        ],
    )
    rc = saga.main()
    err = capsys.readouterr().err

    assert rc == 2
    assert "Traceback" not in err, "the failure must surface as a clean error, not a traceback"
    assert "rewrite the saga state.json index" in err, (
        "the error must name the write that actually failed, in the index handler's own words"
    )
    assert "IS still referenced by the" in err, (
        "the index handler must say the tick is tracked, in its own words"
    )
    assert "idempotent" not in err and "no duplicate tick" not in err, (
        "a save always allocates a fresh envelope: the re-run appends one additional "
        "tick, and the message must not claim otherwise (review C01/D03/P01/U09)"
    )
    assert "NO saga tick" not in err, (
        "an index-only failure must not claim the tick is missing — the envelope is on disk"
    )
    # The tick IS tracked: restore resolves it from the envelope, index or no index.
    restored = saga.restore(tmp_path, saga_id)
    assert restored is not None, "restore reads the envelope directly; the tick exists"
    assert restored.phase_status == "complete"


def test_envelope_failure_scans_all_prior_ticks_for_the_plan_document(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A plan referenced before the newest tick is still tracked (cycle-3 defect A2).

    Two successful saves record different plans. The saga directory is then made
    read-only, so a third save for the first plan fails with a real PermissionError.
    ``restore`` sees only the second plan, but ``read_ticks`` proves the first plan is
    still referenced. The surfaced error must inspect the full chain rather than claim
    the first plan is stranded.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga_id = saga.derive_saga_id("issue", "923")
    plan_doc = "docs/plans/2026-08-30-tracked-despite-failure-plan.md"
    latest_plan_doc = "docs/plans/2026-08-30-newest-tick-plan.md"
    for path in (plan_doc, latest_plan_doc):
        plan_file = tmp_path / path
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("# Plan\n", encoding="utf-8")
    argv = [
        "script",
        "save",
        "--id",
        "923",
        "--lifecycle-phase",
        "plan",
        "--phase-status",
        "complete",
        "--plan-path",
        plan_doc,
    ]

    monkeypatch.setattr("sys.argv", argv)
    assert saga.main() == 0
    capsys.readouterr()

    newest_argv = [*argv[:-1], latest_plan_doc]
    monkeypatch.setattr("sys.argv", newest_argv)
    assert saga.main() == 0
    capsys.readouterr()
    restored = saga.restore(tmp_path, saga_id)
    assert restored is not None and restored.plan_path == latest_plan_doc
    assert [tick.plan_path for tick in saga.read_ticks(tmp_path, saga_id)] == [
        plan_doc,
        latest_plan_doc,
    ]

    saga_dir = tmp_path / saga.SAGAS_DIR / saga_id
    saga_dir.chmod(0o500)  # the third envelope write fails with PermissionError
    try:
        monkeypatch.setattr("sys.argv", argv)
        rc = saga.main()
        err = capsys.readouterr().err
    finally:
        saga_dir.chmod(0o755)  # let pytest's tmp cleanup remove the tree

    assert rc == 2
    assert plan_doc in err, "the surfaced error must name the plan document"
    assert "Traceback" not in err
    assert "NO saga tick" not in err, (
        "an earlier tick still references the plan — the message must not claim it stranded"
    )
    assert "an earlier tick still references" in err, (
        "the envelope handler's own words must say the plan is tracked by the prior tick"
    )
    # The newest tick still names the other plan; only a full-chain scan finds this one.
    restored = saga.restore(tmp_path, saga_id)
    assert restored is not None and restored.plan_path == latest_plan_doc


def test_envelope_failure_normalizes_equivalent_plan_paths(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Equivalent spellings of one plan path remain tracked (cycle-3 defect A2)."""
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga_id = saga.derive_saga_id("issue", "923")
    recorded_plan_doc = "docs/plans/2026-08-30-equivalent-path-plan.md"
    requested_plan_doc = f"./{recorded_plan_doc}"
    plan_file = tmp_path / recorded_plan_doc
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# Plan\n", encoding="utf-8")
    recorded_argv = [
        "script",
        "save",
        "--id",
        "923",
        "--lifecycle-phase",
        "plan",
        "--phase-status",
        "complete",
        "--plan-path",
        recorded_plan_doc,
    ]

    monkeypatch.setattr("sys.argv", recorded_argv)
    assert saga.main() == 0
    capsys.readouterr()
    assert saga.restore(tmp_path, saga_id).plan_path == recorded_plan_doc

    saga_dir = tmp_path / saga.SAGAS_DIR / saga_id
    saga_dir.chmod(0o500)
    try:
        monkeypatch.setattr("sys.argv", [*recorded_argv[:-1], requested_plan_doc])
        rc = saga.main()
        err = capsys.readouterr().err
    finally:
        saga_dir.chmod(0o755)

    assert rc == 2
    assert requested_plan_doc in err
    assert "NO saga tick" not in err, (
        "normalized equivalent paths reference one document, so it must not be called stranded"
    )
    assert "an earlier tick still references" in err


def test_successful_plan_save_tick_resolves_to_the_written_document(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After a successful save carrying ``--plan-path``, ``restore`` resolves to that document."""
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    plan_doc = "docs/plans/2026-08-30-state-correctness-plan.md"
    plan_file = tmp_path / plan_doc
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# Plan\n", encoding="utf-8")

    rc, _ = _run_main(
        saga,
        [
            "save",
            "--id",
            "923",
            "--lifecycle-phase",
            "plan",
            "--phase-status",
            "complete",
            "--plan-path",
            plan_doc,
        ],
        capsys,
        monkeypatch,
    )
    assert rc == 0

    saga_id = saga.derive_saga_id("issue", "923")
    restored = saga.restore(tmp_path, saga_id)
    assert restored is not None
    assert restored.plan_path == plan_doc
    assert (tmp_path / restored.plan_path).is_file()
    # The written tick carries the exact value the /loop dispatch row routes onward on.
    assert restored.phase_status == "complete"


# ---------------------------------------------------------------------------
# Routing half: the producer and the router agree on a finished plan phase
# ---------------------------------------------------------------------------


def _spec_plan_write_phase_status() -> str:
    """Read ``phase_status`` from the ``/plan`` writes column of saga-spec.md §11."""
    for line in SAGA_SPEC.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("| **/plan**"):
            match = re.search(r"phase_status=([a-z_]+)", line)
            assert match, "the saga-spec /plan writes column must name phase_status"
            return match.group(1)
    raise AssertionError("no /plan row found in the saga-spec.md consumer table")


def test_plan_phase_status_agrees_end_to_end() -> None:
    """The producer and the spec row agree on a finished plan phase.

    Mutation proof (KTD1): removing ``--phase-status complete`` from Phase 5.3 fails this
    test. A third party used to be checked here — the router row in the /loop skill's
    dispatch table — and issue 1030 removed that skill with the command; the producer and
    the spec row are the two that remain, and they are the pair that can still drift. Only
    the runnable command blocks are pinned: the prose around them stays free.
    """
    blocks = save_blocks(_plan_phase_53())
    per_block = [save_options(block).get("phase_status", []) for block in blocks]
    assert all(len(values) == 1 for values in per_block), (
        f"{PLAN_SKILL} Phase 5.3: every save variant must pass --phase-status exactly once; "
        f"counts per variant: {[len(values) for values in per_block]}"
    )
    values = [values[0] for values in per_block]
    spec = _spec_plan_write_phase_status()
    assert set(values) == {spec}, (
        f"the finished-plan phase_status disagrees: Phase 5.3 writes {sorted(set(values))}, "
        f"saga-spec /plan writes {spec!r}"
    )


def test_phase_53_checks_save_exit_status_before_routing_onward() -> None:
    """Phase 5.3 carries the exit-status instruction; deleting it fails this test.

    A failed save must stop the run before Phase 5.4 routes onward, so the operator sees
    the stranded-document error instead of a route decision built on a tick that never
    landed.
    """
    section = _plan_phase_53().lower()
    assert "exit status" in section, "Phase 5.3 must instruct checking the save's exit status"
    assert re.search(r"\bstop\b", section), "Phase 5.3 must say to STOP on a failed save"
    assert "5.4" in section, "Phase 5.3 must forbid continuing to Phase 5.4 on a failed save"
