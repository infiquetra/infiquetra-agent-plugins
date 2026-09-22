"""Tests for the unified saga saga engine + its thin wrappers.

Two layers:

* **Engine unit tests** drive ``saga.py`` directly (id derivation, save/restore/
  scan, ``aggregate_context``, the index, snapshot list semantics). These call
  the pure functions with an injected ``root: Path`` and an injected ``now`` /
  ``runner`` so they are deterministic and never shell out.
* **Wrapper characterization tests** drive the three legacy scripts
  (``scaffold_checkpoint.py`` / ``find_inflight_work.py`` /
  ``load_saga_context.py``) through their ``main()`` to pin the *new* 0.4.0
  behavior (``sagas/<saga_id>/<ts>.md`` layout, filename ordering, append-only)
  while asserting the legacy CLI-flag and JSON-output-key PARITY survives.

Determinism / offline discipline:

* Engine tests pass ``root=tmp_path`` and a fixed ``now`` (and a stub ``runner``
  for git/gh), so nothing depends on the real filesystem, clock, or network.
* Wrapper tests ``monkeypatch.chdir(tmp_path)`` because the wrappers resolve
  ``root = Path.cwd()`` internally, then monkeypatch ``saga.subprocess.run`` (the
  single subprocess seam the engine uses) so git/gh never run.
* A suite guard asserts no ``.claude/`` directory is created under the repo root
  during the run — ``.gitignore`` hides it, so without the guard a missing
  ``chdir`` would silently pollute the working tree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "saga"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
STATE_DIR = Path(".claude") / "saga"
SAGAS_DIR = STATE_DIR / "sagas"
LEGACY_CHECKPOINT_DIR = STATE_DIR / "checkpoints"

# A fixed instant for deterministic timestamps / filenames.
FIXED_NOW = datetime(2026, 6, 2, 14, 5, 10, tzinfo=UTC)


def _load_module(script_name: str) -> ModuleType:
    """Load a script module by file path, registered in ``sys.modules``.

    Registration matters: ``saga.py`` defines a frozen ``@dataclass`` and (on
    Python 3.12+) dataclass processing looks the class's ``__module__`` up in
    ``sys.modules`` while building it. A module loaded via ``importlib`` but not
    registered resolves to ``None`` there and the class build raises. Wrappers
    also ``import saga``; registering the engine under the name ``saga`` lets
    that bare import resolve to this same loaded instance (so tests and wrappers
    share one module + its monkeypatched ``subprocess``).
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
    """The loaded ``saga`` engine module (shared with wrappers via sys.modules)."""
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

    The engine threads a ``runner: Callable`` first-class through every function
    that shells out (``save`` / ``current_git_state`` / ``aggregate_context`` /
    ``prior_prs``), defaulting it to ``subprocess.run``. That default is captured
    at definition time, so monkeypatching ``saga.subprocess.run`` alone does NOT
    reach a call that omits ``runner=`` — notably the thin wrappers, which call
    ``saga.save`` / ``saga.aggregate_context`` with no runner. We therefore patch
    both ``saga.subprocess.run`` (covers explicit-attribute calls) and the
    captured runner default on each function (covers default-path calls), so the
    engine and its wrappers never hit the real network or git during tests.
    """
    monkeypatch.setattr(saga.subprocess, "run", runner)
    for fn_name in ("save", "current_git_state", "aggregate_context", "prior_prs"):
        fn = getattr(saga, fn_name)
        # ``runner`` is keyword-only, so its captured default lives in
        # ``__kwdefaults__``. Rebind that slot to our test runner.
        new_kwdefaults = dict(fn.__kwdefaults__ or {})
        new_kwdefaults["runner"] = runner
        monkeypatch.setattr(fn, "__kwdefaults__", new_kwdefaults)


def _stub_no_git(saga: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the engine's subprocess seam a no-op (empty git/gh output)."""

    def fake_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    _set_runner(saga, monkeypatch, fake_run)


def _make_saga(saga: ModuleType, **overrides: Any) -> Any:
    """Build a minimal ``Saga`` with a derived id; overrides win."""
    kind = overrides.pop("kind", "issue")
    id_ = overrides.pop("id", "42")
    saga_id = overrides.pop("saga_id", saga.derive_saga_id(kind, id_))
    return saga.Saga(saga_id=saga_id, kind=kind, id=str(id_), **overrides)


# ===========================================================================
# Engine: identity / id-derivation
# ===========================================================================


def test_derive_saga_id_issue_is_round_agnostic(saga: ModuleType) -> None:
    # The id is derived from kind + id only; round/phase are FIELDS, not identity.
    assert saga.derive_saga_id("issue", "42") == "issue-42"
    assert saga.derive_saga_id("issue", 42) == "issue-42"
    assert saga.derive_saga_id("issue", " 42 ") == "issue-42"


def test_derive_saga_id_task_slugifies(saga: ModuleType) -> None:
    assert saga.derive_saga_id("task", "Saga Foundation") == "task-saga-foundation"
    assert saga.derive_saga_id("task", "Saga_Foundation!!") == "task-saga-foundation"
    assert saga.derive_saga_id("task", "  Multi  Word  ") == "task-multi-word"


def test_derive_saga_id_is_deterministic(saga: ModuleType) -> None:
    first = saga.derive_saga_id("task", "My Cool Feature")
    second = saga.derive_saga_id("task", "My Cool Feature")
    assert first == second == "task-my-cool-feature"


def test_slugify_empty_falls_back_to_saga(saga: ModuleType) -> None:
    # An all-symbol slug must not collapse to an empty (collision-prone) dir name.
    assert saga.slugify("") == "saga"
    assert saga.slugify("!!!") == "saga"
    assert saga.derive_saga_id("task", "***") == "task-saga"


def test_save_collision_guard_appends_seq_suffix(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two saves in the SAME second must not overwrite; the 2nd gets a -1 suffix."""
    _stub_no_git(saga, monkeypatch)
    s = _make_saga(saga)
    first = saga.save(tmp_path, s, now=FIXED_NOW)
    second = saga.save(tmp_path, s, now=FIXED_NOW)

    assert Path(first["envelope_path"]).name == "20260602-140510.md"
    assert Path(second["envelope_path"]).name == "20260602-140510-1.md"
    files = sorted(p.name for p in (tmp_path / SAGAS_DIR / "issue-42").glob("*.md"))
    assert files == ["20260602-140510-1.md", "20260602-140510.md"]


# ===========================================================================
# Engine: render / parse round-trip
# ===========================================================================


def test_render_parse_round_trip_preserves_fields_and_extra(saga: ModuleType) -> None:
    s = _make_saga(
        saga,
        lifecycle_phase="work",
        phase_status="in_progress",
        status="active",
        next_step="finish the thing",
        round=2,
        phase=3,
        progress_pct=40,
        plan_path="docs/plans/x.md",
        open_questions=["q1", "q2"],
        adr_refs=["ADR-0004"],
        rounds_seen=[1, 2],
        summary="A summary",
        decisions="Chose X over Y",
        remaining="Do Z",
        notes="Tried W",
        extra={"custom_future_key": "kept"},
    )
    restored = saga.parse_envelope(saga.render_envelope(s))

    assert restored.saga_id == "issue-42"
    assert restored.lifecycle_phase == "work"
    assert restored.phase_status == "in_progress"
    assert restored.round == 2
    assert restored.phase == 3
    assert restored.progress_pct == 40
    assert restored.open_questions == ["q1", "q2"]
    assert restored.adr_refs == ["ADR-0004"]
    assert restored.rounds_seen == [1, 2]  # ints, not strings
    assert restored.summary == "A summary"
    assert restored.decisions == "Chose X over Y"
    assert restored.remaining == "Do Z"
    assert restored.notes == "Tried W"
    # Unknown frontmatter keys survive the round-trip via ``extra``.
    assert restored.extra["custom_future_key"] == "kept"


def test_parse_envelope_quotes_tricky_scalars(saga: ModuleType) -> None:
    s = _make_saga(saga, next_step="do: a thing", blockers="value: with colon")
    restored = saga.parse_envelope(saga.render_envelope(s))
    assert restored.next_step == "do: a thing"
    assert restored.blockers == "value: with colon"


# ===========================================================================
# Engine: save
# ===========================================================================


def test_save_writes_timestamped_envelope_and_full_frontmatter(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    s = _make_saga(
        saga,
        lifecycle_phase="work",
        phase_status="in_progress",
        status="active",
        destination="pr",
        next_step="do X",
        plan_path="docs/plans/example.md",
    )
    result = saga.save(tmp_path, s, now=FIXED_NOW)

    envelope = Path(result["envelope_path"])
    assert envelope.name == "20260602-140510.md"
    assert envelope.parent == tmp_path / SAGAS_DIR / "issue-42"
    text = envelope.read_text(encoding="utf-8")
    # Full frontmatter machine fields present, except fields that render no key when empty
    # (artifact_pointers omits when absent, keeping pre-field sagas byte-identical).
    for key in saga.FRONTMATTER_FIELDS:
        if key in saga._OMIT_WHEN_EMPTY_FIELDS:
            continue
        assert f"{key}:" in text
    assert "lifecycle_phase: work" in text
    assert "## Summary" in text and "## Decisions" in text
    assert "## Remaining" in text and "## Notes / Tried" in text


def test_save_state_json_has_current_work_plan_path(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """handoff_envelope.discover_active_source reads current_work.plan_path."""
    _stub_no_git(saga, monkeypatch)
    s = _make_saga(saga, plan_path="docs/plans/example.md", phase=1)
    saga.save(tmp_path, s, now=FIXED_NOW)

    state = json.loads((tmp_path / STATE_DIR / "state.json").read_text(encoding="utf-8"))
    assert state["current_work"]["plan_path"] == "docs/plans/example.md"
    assert state["active_saga_id"] == "issue-42"
    assert "issue-42" in state["sagas"]


def test_save_is_append_only_second_save_writes_second_file(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    s = _make_saga(saga, phase=1)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, s, now=FIXED_NOW)
    saga.save(tmp_path, _make_saga(saga, phase=2), now=later)

    files = sorted(p.name for p in (tmp_path / SAGAS_DIR / "issue-42").glob("*.md"))
    assert files == ["20260602-140510.md", "20260602-141233.md"]
    # Neither tick was mutated: the first still says phase 1.
    first = saga.parse_envelope((tmp_path / SAGAS_DIR / "issue-42" / files[0]).read_text())
    assert first.phase == 1


def test_save_writes_atomically_leaving_no_tmp(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW)
    leftovers = list((tmp_path / STATE_DIR).glob("*.tmp"))
    assert leftovers == []
    # state.json is valid JSON (atomic temp+rename, never a partial write).
    json.loads((tmp_path / STATE_DIR / "state.json").read_text(encoding="utf-8"))


def test_save_snapshot_list_can_shrink(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later tick's shorter list REPLACES the prior (not union) — it shrinks."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, open_questions=["a", "b", "c"]), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, open_questions=["a"]), now=later)

    restored = saga.restore(tmp_path, "issue-42")
    assert restored.open_questions == ["a"]  # shrank, not unioned to a,b,c


def test_save_absent_list_carries_forward(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A list left ABSENT (not supplied) carries the prior tick's value forward."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, open_questions=["keep1", "keep2"]), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    # ABSENT default for open_questions -> carry forward; bump only the phase.
    saga.save(tmp_path, _make_saga(saga, phase=9), now=later)

    restored = saga.restore(tmp_path, "issue-42")
    assert restored.open_questions == ["keep1", "keep2"]
    assert restored.phase == 9


def test_save_empty_list_clears(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, open_questions=["x"]), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, open_questions=[]), now=later)
    assert saga.restore(tmp_path, "issue-42").open_questions == []


def test_save_returns_back_compat_keys(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    result = saga.save(
        tmp_path, _make_saga(saga, phase=2, phase_status="complete", status="active"), now=FIXED_NOW
    )
    assert {"saga_id", "envelope_path", "state_path", "phase", "status"} <= set(result)
    assert result["phase"] == 2
    assert result["status"] == "active"
    # next_phase = phase + 1 when phase_status == complete.
    assert result["next_phase"] == 3


def test_save_captures_git_state_from_runner(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """save records git branch/sha from the injected runner; restore later reads them."""

    def fake_git(args: list[str], **_kwargs: Any) -> SimpleNamespace:
        if "--show-current" in args:
            return SimpleNamespace(returncode=0, stdout="feature/saga\n", stderr="")
        if "--short" in args:
            return SimpleNamespace(returncode=0, stdout="abc1234\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="abc1234def\n", stderr="")

    _set_runner(saga, monkeypatch, fake_git)
    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW)
    restored = saga.restore(tmp_path, "issue-42")
    assert restored.branch == "feature/saga"
    assert restored.head_sha == "abc1234"


def test_save_refreshes_branch_on_later_save(saga: ModuleType, tmp_path: Path) -> None:
    """``branch`` tracks the CURRENT git branch on EVERY save, not just the first (issue #480).

    Mirrors the ``/plan`` mints-on-``main`` then ``/work`` re-saves-on-branch lifecycle: the
    first save captures ``main``; a later save on the work branch must OVERWRITE it, not carry
    ``main`` forward through scalar merge.
    """

    def git_on(branch: str) -> Callable[..., SimpleNamespace]:
        def fake_git(args: list[str], **_kwargs: Any) -> SimpleNamespace:
            if "--show-current" in args:
                return SimpleNamespace(returncode=0, stdout=f"{branch}\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="abc1234\n", stderr="")

        return fake_git

    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW, runner=git_on("main"))
    assert saga.restore(tmp_path, "issue-42").branch == "main"

    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga), now=later, runner=git_on("fix/pf-work"))
    assert saga.restore(tmp_path, "issue-42").branch == "fix/pf-work"


def test_save_empty_branch_does_not_clobber_stored_branch(saga: ModuleType, tmp_path: Path) -> None:
    """A detached-HEAD / no-git save (empty ``git branch --show-current``) must NOT wipe a
    previously-stored branch — the ``git["branch"]`` non-empty guard preserves carry-forward
    (issue #480, R2)."""

    def fake_git_on_branch(args: list[str], **_kwargs: Any) -> SimpleNamespace:
        if "--show-current" in args:
            return SimpleNamespace(returncode=0, stdout="fix/pf-work\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="abc1234\n", stderr="")

    def fake_git_detached(args: list[str], **_kwargs: Any) -> SimpleNamespace:
        if "--show-current" in args:
            return SimpleNamespace(returncode=0, stdout="\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="def5678\n", stderr="")

    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW, runner=fake_git_on_branch)
    assert saga.restore(tmp_path, "issue-42").branch == "fix/pf-work"

    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga), now=later, runner=fake_git_detached)
    assert saga.restore(tmp_path, "issue-42").branch == "fix/pf-work"


def test_save_on_default_branch_preserves_stored_work_branch(
    saga: ModuleType, tmp_path: Path
) -> None:
    """Once a real work branch is recorded, a later save made back on ``main`` must NOT overwrite
    it (issue #480). The ship ceremony's ``checkout_main`` progress-save ran on ``main`` right
    before ``branch_delete`` — which still needed the work branch — so this mirrors that exact
    sequence and guards against the refresh downgrading a real branch to the default one. The
    ceremony was removed in #1027; the guard stays, because the property is true of any caller that
    saves while standing on the default branch.
    """

    def git_on(branch: str) -> Callable[..., SimpleNamespace]:
        def fake_git(args: list[str], **_kwargs: Any) -> SimpleNamespace:
            if "--show-current" in args:
                return SimpleNamespace(returncode=0, stdout=f"{branch}\n", stderr="")
            return SimpleNamespace(returncode=0, stdout="abc1234\n", stderr="")

        return fake_git

    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW, runner=git_on("feat/pf-throwaway-345"))
    assert saga.restore(tmp_path, "issue-42").branch == "feat/pf-throwaway-345"

    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga), now=later, runner=git_on("main"))
    assert saga.restore(tmp_path, "issue-42").branch == "feat/pf-throwaway-345"


def test_save_refreshes_head_and_last_commit_on_later_save(
    saga: ModuleType, tmp_path: Path
) -> None:
    """`head_sha`/`last_commit_sha` track the current commit on EVERY save, not just the first
    (the #480 follow-up). Unlike `branch`, SHAs have no default-branch downgrade concern, so a
    plain non-empty guard suffices."""

    def git_at(short: str, full: str) -> Callable[..., SimpleNamespace]:
        def fake_git(args: list[str], **_kwargs: Any) -> SimpleNamespace:
            if "--show-current" in args:
                return SimpleNamespace(returncode=0, stdout="feat/work\n", stderr="")
            if "--short" in args:
                return SimpleNamespace(returncode=0, stdout=f"{short}\n", stderr="")
            return SimpleNamespace(returncode=0, stdout=f"{full}\n", stderr="")

        return fake_git

    saga.save(tmp_path, _make_saga(saga), now=FIXED_NOW, runner=git_at("aaa1111", "aaa1111ffff"))
    first = saga.restore(tmp_path, "issue-42")
    assert first.head_sha == "aaa1111"
    assert first.last_commit_sha == "aaa1111ffff"

    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga), now=later, runner=git_at("bbb2222", "bbb2222ffff"))
    second = saga.restore(tmp_path, "issue-42")
    assert second.head_sha == "bbb2222"
    assert second.last_commit_sha == "bbb2222ffff"


# ===========================================================================
# Engine: restore
# ===========================================================================


def test_restore_round_trips_including_extra(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assert_reads_from_boundary: Any,
) -> None:
    # Converted to the #458 T11-F4-7 boundary-crossing convention: the summary assertion re-reads
    # from the persisted tick (the boundary), not the in-memory Saga the producer built.
    _stub_no_git(saga, monkeypatch)
    result = saga.save(
        tmp_path,
        _make_saga(saga, summary="hello", adr_refs=["ADR-0004"], extra={"future": "v"}),
        now=FIXED_NOW,
    )
    envelope_path = Path(result["envelope_path"])
    assert_reads_from_boundary(
        lambda: saga.restore(tmp_path, "issue-42").summary,
        "hello",
        boundary=envelope_path,
        description="saga.summary",
    )
    restored = saga.restore(tmp_path, "issue-42")
    assert restored is not None
    assert restored.adr_refs == ["ADR-0004"]
    assert restored.extra["future"] == "v"


def test_boundary_crossing_roundtrip(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assert_reads_from_boundary: Any,
) -> None:
    """Worked example of the boundary-crossing convention (#458 T11-F4-7).

    ``assert_reads_from_boundary`` first proves the tick file was actually written to disk (the
    persistence boundary), THEN re-reads the value via ``restore`` from that boundary — never from
    the in-memory ``Saga`` the producer built. Stubbing out the envelope write (a throwaway
    ``monkeypatch`` of ``Path.write_text`` / ``saga.save``) makes the boundary-existence assertion
    fail, which is the proof the assertion reads from disk rather than an in-memory shared variable.
    """
    _stub_no_git(saga, monkeypatch)
    result = saga.save(tmp_path, _make_saga(saga, summary="persisted-value"), now=FIXED_NOW)
    envelope_path = Path(result["envelope_path"])
    read_back = assert_reads_from_boundary(
        lambda: saga.restore(tmp_path, "issue-42").summary,
        "persisted-value",
        boundary=envelope_path,
        description="saga.summary",
    )
    assert read_back == "persisted-value"


def test_restore_picks_latest_by_filename_even_with_newer_mtime(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordering is by FILENAME, never mtime: give the OLDER file a NEWER mtime."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, phase=1, summary="OLD"), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, phase=2, summary="NEW"), now=later)

    saga_dir = tmp_path / SAGAS_DIR / "issue-42"
    older_file = saga_dir / "20260602-140510.md"
    newer_file = saga_dir / "20260602-141233.md"
    # Make the lexically-older file the most-recently-modified one on disk.
    os.utime(older_file, (9_000_000_000, 9_000_000_000))
    os.utime(newer_file, (1_000_000, 1_000_000))

    restored = saga.restore(tmp_path, "issue-42")
    # Newest FILENAME wins regardless of mtime: the later-named "NEW" tick.
    assert restored.summary == "NEW"
    assert restored.phase == 2
    assert saga.latest_envelope_for(tmp_path, "issue-42").name == "20260602-141233.md"


def test_restore_absent_saga_returns_none(saga: ModuleType, tmp_path: Path) -> None:
    assert saga.restore(tmp_path, "issue-999") is None
    assert saga.latest_envelope_for(tmp_path, "issue-999") is None


def test_restore_is_branch_agnostic_never_calls_subprocess(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """restore must read the envelope only — it must NOT shell out to git."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, summary="branch-agnostic"), now=FIXED_NOW)

    def boom(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        raise AssertionError("restore must not call subprocess.run")

    monkeypatch.setattr(saga.subprocess, "run", boom)
    restored = saga.restore(tmp_path, "issue-42")
    assert restored is not None
    assert restored.summary == "branch-agnostic"


# ===========================================================================
# Engine: scan
# ===========================================================================


def test_scan_orders_by_filename_desc_one_per_saga(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, id="42"), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, id="7"), now=later)
    # A second tick for issue-42 must NOT add a second candidate (one per saga).
    latest = datetime(2026, 6, 2, 14, 20, 0, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, id="42", phase=5), now=latest)

    candidates = saga.scan(tmp_path)
    saga_ids = [c["saga_id"] for c in candidates]
    assert saga_ids == ["issue-42", "issue-7"]  # newest filename first
    # The issue-42 candidate is its LATEST tick (phase 5).
    assert next(c for c in candidates if c["saga_id"] == "issue-42")["phase"] == 5


def test_scan_max_candidates_caps(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, id="1"), now=FIXED_NOW)
    saga.save(tmp_path, _make_saga(saga, id="2"), now=datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC))
    saga.save(tmp_path, _make_saga(saga, id="3"), now=datetime(2026, 6, 2, 14, 7, 0, tzinfo=UTC))
    assert len(saga.scan(tmp_path, max_candidates=2)) == 2


def test_scan_skips_non_matching_files_and_dirs(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, id="42"), now=FIXED_NOW)
    # A stray dir with no valid envelope, and a stray file in the sagas root.
    (tmp_path / SAGAS_DIR / "empty-dir").mkdir(parents=True)
    (tmp_path / SAGAS_DIR / "stray.txt").write_text("x", encoding="utf-8")
    (tmp_path / SAGAS_DIR / "issue-42" / "not-a-tick.md").write_text("x", encoding="utf-8")

    candidates = saga.scan(tmp_path)
    assert [c["saga_id"] for c in candidates] == ["issue-42"]
    assert candidates[0]["name"] == "20260602-140510.md"


def test_scan_reads_legacy_checkpoints_as_flagged_fallback(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, id="42"), now=FIXED_NOW)
    legacy = tmp_path / LEGACY_CHECKPOINT_DIR
    legacy.mkdir(parents=True)
    (legacy / "issue-7-round-2-phase3-complete.md").write_text("legacy", encoding="utf-8")
    (legacy / "not-a-checkpoint.md").write_text("skip", encoding="utf-8")

    candidates = saga.scan(tmp_path)
    new = [c for c in candidates if not c["legacy"]]
    old = [c for c in candidates if c["legacy"]]
    assert [c["saga_id"] for c in new] == ["issue-42"]
    assert len(old) == 1
    assert old[0]["saga_id"] == "issue-7"
    assert old[0]["phase"] == 3
    assert old[0]["phase_status"] == "complete"
    assert old[0]["next_phase"] == 4
    # New (envelope) candidates sort BEFORE the legacy fallback.
    assert candidates[0]["legacy"] is False
    assert candidates[-1]["legacy"] is True


def test_scan_empty_returns_empty_list(saga: ModuleType, tmp_path: Path) -> None:
    assert saga.scan(tmp_path) == []


def test_scan_still_works_with_corrupt_state_json(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt index is never fatal — scan rebuilds the picture from envelopes."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, id="42"), now=FIXED_NOW)
    (tmp_path / STATE_DIR / "state.json").write_text("{not json", encoding="utf-8")
    candidates = saga.scan(tmp_path)
    assert [c["saga_id"] for c in candidates] == ["issue-42"]


# ===========================================================================
# Engine: read_ticks / ticks subcommand (the heavy-forensic ALL-ticks reader)
# ===========================================================================


def test_saga_read_ticks_returns_full_chain(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """read_ticks surfaces the WHOLE tick chain (oldest->newest by FILENAME).

    restore() sees only the latest tick, so the early ``next_step`` (and an
    early blocker that a later tick replaced via a snapshot list) are invisible
    to it. The ALL-ticks reader is the forensic view /resume needs: every tick
    is a full snapshot, in filename order. A regression guard pins restore() to
    still return ONLY the latest.
    """
    _stub_no_git(saga, monkeypatch)
    t1 = FIXED_NOW
    t2 = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    t3 = datetime(2026, 6, 2, 14, 20, 0, tzinfo=UTC)
    # Tick 1: an early step with an open blocker (open_questions = snapshot list).
    saga.save(
        tmp_path,
        _make_saga(saga, phase=1, next_step="early step", open_questions=["blocked: review"]),
        now=t1,
    )
    # Tick 2: mid-flight, blocker cleared (explicit [] snapshot-clears the list).
    saga.save(tmp_path, _make_saga(saga, phase=2, next_step="mid step", open_questions=[]), now=t2)
    # Tick 3: the late step (this is all restore() ever sees).
    saga.save(tmp_path, _make_saga(saga, phase=3, next_step="late step"), now=t3)

    chain = saga.read_ticks(tmp_path, "issue-42")
    assert len(chain) == 3
    # FILENAME order, oldest -> newest (NOT mtime, NOT insertion-into-dict).
    assert [t.phase for t in chain] == [1, 2, 3]
    assert [t.next_step for t in chain] == ["early step", "mid step", "late step"]
    # Each tick is a FULL snapshot, not a delta.
    assert all(t.saga_id == "issue-42" for t in chain)
    assert all(t.kind == "issue" for t in chain)

    # The tick-1 content restore() DROPS (the early step + the blocker that
    # tick 2 later cleared) is recoverable from the chain head.
    assert chain[0].next_step == "early step"
    assert chain[0].open_questions == ["blocked: review"]

    # Regression guard: restore() still returns ONLY the latest tick.
    latest = saga.restore(tmp_path, "issue-42")
    assert latest is not None
    assert latest.phase == 3
    assert latest.next_step == "late step"
    assert latest.open_questions == []  # the cleared list, not the tick-1 blocker


def test_saga_ticks_subcommand_emits_full_chain_oldest_first(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The ``ticks`` CLI emits {"ticks": [...], "count": N}, oldest->newest.

    Each tick dict carries the trajectory fields (next_step / blockers /
    open_questions / rounds_seen) so the SKILL's all-ticks reader can replay the
    work-state evolution. Drives main() in-process (matches the harness's
    no-shell, fixed-cwd discipline).
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    t1 = FIXED_NOW
    t2 = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(
        tmp_path,
        _make_saga(saga, phase=1, next_step="early step", open_questions=["q-early"]),
        now=t1,
    )
    saga.save(
        tmp_path,
        _make_saga(saga, phase=2, next_step="late step", open_questions=["q-late"]),
        now=t2,
    )

    rc, payload = _run_main(saga, ["ticks", "--saga-id", "issue-42"], capsys, monkeypatch)
    assert rc == 0
    assert payload["count"] == 2
    ticks = payload["ticks"]
    assert [t["phase"] for t in ticks] == [1, 2]  # oldest -> newest
    assert [t["next_step"] for t in ticks] == ["early step", "late step"]
    # Per-tick trajectory fields are present in the emitted dict.
    assert ticks[0]["open_questions"] == ["q-early"]
    assert ticks[1]["open_questions"] == ["q-late"]
    for key in ("saga_id", "lifecycle_phase", "phase_status", "status", "blockers", "updated_at"):
        assert key in ticks[0]


def test_saga_ticks_subcommand_empty_for_unknown_saga(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown saga yields an empty chain, never an error."""
    monkeypatch.chdir(tmp_path)
    assert saga.read_ticks(tmp_path, "issue-999") == []
    rc, payload = _run_main(saga, ["ticks", "--saga-id", "issue-999"], capsys, monkeypatch)
    assert rc == 0
    assert payload == {"ticks": [], "count": 0}


# ===========================================================================
# Engine: re-entry tick reuse (the /resume C2 mint-safety smoke test)
# ===========================================================================


def test_resume_reentry_tick_reuses_saga_id_no_mint(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-entry tick that REUSES the restored saga_id APPENDS — never mints.

    save() mints a new saga dir unconditionally for a *new* saga_id (no
    scan-first guard), so /resume MUST write its re-entry tick with the
    RESTORED saga_id, not a paraphrase. This pins that: an existing task saga
    gains a 2nd envelope and the SAGAS_DIR still holds exactly ONE saga dir.
    """
    _stub_no_git(saga, monkeypatch)
    # Existing task saga with one tick.
    saga.save(
        tmp_path,
        _make_saga(saga, kind="task", id="foo", lifecycle_phase="work", next_step="first"),
        now=FIXED_NOW,
    )
    saga_id = saga.derive_saga_id("task", "foo")
    assert saga_id == "task-foo"
    sagas_root = tmp_path / SAGAS_DIR
    assert [p.name for p in sagas_root.iterdir() if p.is_dir()] == ["task-foo"]

    # The /resume re-entry tick: reuse the restored saga_id verbatim.
    restored = saga.restore(tmp_path, saga_id)
    assert restored is not None
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(
        tmp_path,
        saga.Saga(
            saga_id=restored.saga_id,  # reuse, never re-derive from a paraphrase
            kind=restored.kind,
            id=restored.id,
            status="paused",
            next_step="resumed: re-entered loop",
        ),
        now=later,
    )

    # APPENDED to task-foo (now 2 ticks), and NO second saga dir was minted.
    saga_dirs = [p.name for p in sagas_root.iterdir() if p.is_dir()]
    assert saga_dirs == ["task-foo"]
    tick_files = sorted(p.name for p in (sagas_root / "task-foo").glob("*.md"))
    assert tick_files == ["20260602-140510.md", "20260602-141233.md"]
    # The re-entry tick is the latest and carries the paused disposition.
    latest = saga.restore(tmp_path, saga_id)
    assert latest.status == "paused"
    assert latest.next_step == "resumed: re-entered loop"


# ===========================================================================
# Engine + CLI: explicit scalar flags vs default carry-forward (issue-157)
# ===========================================================================


def test_cli_save_explicit_status_reactivates_paused_saga(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--status active`` on a paused saga must persist ``active``.

    Regression (2026-07-09, team-norns issue-157): the argparse default was
    "active", so an explicit ``--status active`` was indistinguishable from an
    omitted flag and ``_merge`` carried the prior ``paused`` forward — two
    consecutive reactivation saves both persisted ``paused``.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, status="paused"), now=FIXED_NOW)

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    rc, payload = _run_main(
        saga,
        ["save", "--kind", "issue", "--id", "42", "--status", "active"],
        capsys,
        monkeypatch,
    )

    assert rc == 0
    assert payload["status"] == "active"
    assert saga.restore(tmp_path, "issue-42").status == "active"


def test_cli_save_omitted_status_still_carries_prior_forward(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A progress tick with NO --status must keep inheriting the prior disposition."""
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, status="paused"), now=FIXED_NOW)

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    rc, payload = _run_main(
        saga,
        ["save", "--kind", "issue", "--id", "42", "--next-step", "progress tick"],
        capsys,
        monkeypatch,
    )

    assert rc == 0
    assert payload["status"] == "paused"
    assert saga.restore(tmp_path, "issue-42").status == "paused"


def test_cli_save_omitted_kind_preserves_prior_task_kind(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A save with --saga-id and NO --kind must not flip a task saga to "issue".

    Regression (issue-157 residual, saga 0.75.19): --kind argparse-defaulted to
    "issue" and kind has no dataclass default, so _merge's default-equality
    carry-forward never fired for it — an omitted --kind stamped "issue" over a
    prior task saga's sticky identity kind.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    # Birth a task saga.
    rc, payload = _run_main(saga, ["save", "--kind", "task", "--id", "foo"], capsys, monkeypatch)
    assert rc == 0
    assert payload["saga_id"] == "task-foo"
    assert saga.restore(tmp_path, "task-foo").kind == "task"

    # A progress tick targeting it by --saga-id with NO --kind must keep kind=task.
    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    rc, payload = _run_main(
        saga,
        ["save", "--saga-id", "task-foo", "--id", "foo", "--next-step", "progress tick"],
        capsys,
        monkeypatch,
    )
    assert rc == 0
    assert saga.restore(tmp_path, "task-foo").kind == "task"


def test_cli_save_explicit_kind_contradicting_prior_is_rejected(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An explicit --kind that contradicts an existing saga's recorded kind is rejected.

    Identity is fixed at birth; a save must never silently flip it, and an explicit
    attempt to change it is a loud error (exit 2), not a stamp.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    rc, _ = _run_main(saga, ["save", "--kind", "task", "--id", "foo"], capsys, monkeypatch)
    assert rc == 0

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    monkeypatch.setattr(
        "sys.argv", ["script", "save", "--saga-id", "task-foo", "--kind", "issue", "--id", "foo"]
    )
    rc = saga.main()
    err = capsys.readouterr().err
    assert rc == 2
    assert "sticky identity field" in err
    # The prior task kind is untouched on disk.
    assert saga.restore(tmp_path, "task-foo").kind == "task"


def test_cli_save_explicit_phase_status_pending_resets_completed_phase(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--phase-status pending`` must override a prior ``complete`` (same bug class).

    Without the explicit-flag signal the carried-forward ``complete`` also kept
    advancing the derived ``next_phase`` on every subsequent tick.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga.save(
        tmp_path,
        _make_saga(saga, phase=2, phase_status="complete"),
        now=FIXED_NOW,
    )

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    rc, payload = _run_main(
        saga,
        ["save", "--kind", "issue", "--id", "42", "--phase", "3", "--phase-status", "pending"],
        capsys,
        monkeypatch,
    )

    assert rc == 0
    restored = saga.restore(tmp_path, "issue-42")
    assert restored.phase_status == "pending"
    assert restored.phase == 3
    assert payload["next_phase"] == 3  # pending does not advance the derived next phase


def test_cli_save_explicit_inline_mode_overrides_richer_prior_tier(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Explicit ``--orchestration-mode inline`` must win over a richer prior mode.

    Same absent-vs-default ambiguity: "inline" is the dataclass default, so the
    carried-forward prior mode diverged from the freshly stamped operator_choice
    and the save-time provenance guard rejected the save outright.
    """
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    saga.save(
        tmp_path,
        _make_saga(
            saga,
            orchestration_mode="team-execution",
            orchestration_operator_choice="team-execution",
        ),
        now=FIXED_NOW,
    )

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    monkeypatch.setattr(saga, "_utc_now", lambda: later)
    rc, _payload = _run_main(
        saga,
        ["save", "--kind", "issue", "--id", "42", "--orchestration-mode", "inline"],
        capsys,
        monkeypatch,
    )

    assert rc == 0
    restored = saga.restore(tmp_path, "issue-42")
    assert restored.orchestration_mode == "inline"
    assert restored.orchestration_operator_choice == "inline"


def test_save_explicit_fields_bypass_default_carry_forward(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine seam: ``explicit_fields`` makes a default-valued scalar win in _merge."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, status="paused"), now=FIXED_NOW)

    later = datetime(2026, 6, 2, 14, 6, 0, tzinfo=UTC)
    # incoming.status is the dataclass default "active"; without explicit_fields
    # this carries "paused" forward (pinned by the omitted-flag CLI test above).
    result = saga.save(tmp_path, _make_saga(saga), now=later, explicit_fields=frozenset({"status"}))

    assert result["status"] == "active"
    assert saga.restore(tmp_path, "issue-42").status == "active"


# ===========================================================================
# Engine: aggregate_context
# ===========================================================================


def _gh_pr_payload() -> str:
    # ROUND_RE = r"round-(\d+)" needs the hyphenated "round-N" form in the title.
    return json.dumps(
        [
            {
                "number": 11,
                "title": "feat: #42 round-1 first pass",
                "state": "MERGED",
                "mergedAt": "2026-05-01T00:00:00Z",
                "url": "https://example/11",
                "reviewDecision": "APPROVED",
                "body": "Implements ADR-0004 work.",
            },
            {
                "number": 22,
                "title": "feat: #42 round-2 follow up",
                "state": "OPEN",
                "mergedAt": None,
                "url": "https://example/22",
                "reviewDecision": None,
                "body": "Round 2 body.",
            },
        ]
    )


def test_aggregate_context_gh_success_parses_rounds_and_adrs(
    saga: ModuleType, tmp_path: Path
) -> None:
    def fake_gh(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout=_gh_pr_payload(), stderr="")

    context = saga.aggregate_context(tmp_path, "infiquetra", "core", 42, runner=fake_gh)
    assert context["repo"] == "infiquetra/core"
    assert context["issue"] == 42
    assert [pr["round"] for pr in context["prior_prs"]] == [1, 2]
    assert context["prior_prs"][0]["body_preview"] == "Implements ADR-0004 work."
    assert context["rounds_seen"] == [1, 2]
    assert context["next_round"] == 3
    assert context["saga"] is None  # no saga saved yet


def test_aggregate_context_gh_failure_returns_empty_prs(saga: ModuleType, tmp_path: Path) -> None:
    def fake_gh_fail(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=1, stdout="", stderr="boom")

    context = saga.aggregate_context(tmp_path, "infiquetra", "core", 1, runner=fake_gh_fail)
    assert context["prior_prs"] == []
    assert context["rounds_seen"] == []
    assert context["next_round"] == 1


def test_aggregate_context_missing_gh_does_not_raise(saga: ModuleType, tmp_path: Path) -> None:
    """A missing ``gh`` binary (FileNotFoundError) must not crash offline resume."""

    def missing_gh(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        raise FileNotFoundError("gh: command not found")

    context = saga.aggregate_context(tmp_path, "infiquetra", "core", 7, runner=missing_gh)
    assert context["prior_prs"] == []
    assert context["next_round"] == 1


def test_aggregate_context_finds_renamed_saga_envelope(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The renamed glob (sagas/issue-N/*.md) resolves the issue's saga summary."""
    _stub_no_git(saga, monkeypatch)
    saga.save(
        tmp_path,
        _make_saga(saga, id="42", lifecycle_phase="work", summary="prior context"),
        now=FIXED_NOW,
    )

    def fake_gh(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    context = saga.aggregate_context(tmp_path, "infiquetra", "core", 42, runner=fake_gh)
    assert context["saga"] is not None
    assert context["saga"]["saga_id"] == "issue-42"
    assert context["saga"]["name"] == "20260602-140510.md"
    assert context["saga"]["lifecycle_phase"] == "work"
    assert "prior context" in context["saga"]["content_preview"]


def test_aggregate_context_extracts_adr_and_journal(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    # Save a saga whose body references an ADR — adr_refs flow into journal search.
    saga.save(
        tmp_path,
        _make_saga(saga, id="42", summary="See ADR-0004 and ADR 12 for context"),
        now=FIXED_NOW,
    )
    journal_dir = tmp_path / "docs" / "engineering-journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "LEARNINGS.md").write_text(
        "# Learnings\n\n## Entry about #42 work\nSomething learned.\n", encoding="utf-8"
    )
    (journal_dir / "DECISIONS.md").write_text(
        "# Decisions\n\n## Unrelated\nNo refs here.\n", encoding="utf-8"
    )

    def fake_gh(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    context = saga.aggregate_context(tmp_path, "infiquetra", "core", 42, runner=fake_gh)
    assert context["adr_refs"] == ["ADR-0004", "ADR-0012"]
    learnings = context["journal"]["learnings"]
    assert len(learnings) == 1
    assert learnings[0]["title"] == "Entry about #42 work"
    assert context["journal"]["decisions"] == []


# ===========================================================================
# Engine: index / current_work + two-saga semantics
# ===========================================================================


def test_two_saga_current_work_most_recent_wins_and_carries_saga_id(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """current_work mirrors the most-recently-saved saga and carries its saga_id.

    Also confirms handoff_envelope.discover_active_source still resolves the
    plan_path from current_work after a multi-saga interleave (legacy contract).
    """
    _stub_no_git(saga, monkeypatch)
    saga.save(
        tmp_path,
        _make_saga(saga, id="42", plan_path="docs/plans/forty-two.md"),
        now=FIXED_NOW,
    )
    later = datetime(2026, 6, 2, 14, 30, 0, tzinfo=UTC)
    saga.save(
        tmp_path,
        _make_saga(saga, kind="task", id="my feature", plan_path="docs/plans/my-feature.md"),
        now=later,
    )

    state = json.loads((tmp_path / STATE_DIR / "state.json").read_text(encoding="utf-8"))
    # Both sagas tracked in the index.
    assert set(state["sagas"]) == {"issue-42", "task-my-feature"}
    # current_work mirrors the LAST saved (task) and carries its saga_id.
    assert state["active_saga_id"] == "task-my-feature"
    assert state["current_work"]["saga_id"] == "task-my-feature"
    assert state["current_work"]["plan_path"] == "docs/plans/my-feature.md"

    # handoff_envelope still resolves the active source from current_work.plan_path.
    handoff = _load_module("handoff_envelope.py")
    assert handoff.discover_active_source(tmp_path) == "docs/plans/my-feature.md"


def test_update_index_recovers_from_corrupt_state(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_no_git(saga, monkeypatch)
    state_path = tmp_path / STATE_DIR / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{not json", encoding="utf-8")
    saga.save(tmp_path, _make_saga(saga, id="42", plan_path="docs/plans/x.md"), now=FIXED_NOW)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["current_work"]["plan_path"] == "docs/plans/x.md"
    assert state["active_saga_id"] == "issue-42"


# ===========================================================================
# Wrappers: scaffold_checkpoint.py (NEW 0.4.0 behavior + parity)
# ===========================================================================


def _patch_gh(
    saga: ModuleType, monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0
) -> None:
    """Install a fake ``gh`` runner across the engine (wrappers omit ``runner=``)."""

    def fake_run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    _set_runner(saga, monkeypatch, fake_run)


def test_load_saga_context_preserves_eight_keys(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    module = _load_module("load_saga_context.py")
    _patch_gh(saga, monkeypatch, _gh_pr_payload())

    rc, payload = _run_main(
        module, ["--repo", "infiquetra/core", "--issue", "42"], capsys, monkeypatch
    )

    assert rc == 0
    # PARITY: exactly the eight legacy top-level keys survive (note "checkpoint").
    assert set(payload) == {
        "repo",
        "issue",
        "rounds_seen",
        "next_round",
        "checkpoint",
        "prior_prs",
        "adr_refs",
        "journal",
    }
    assert payload["repo"] == "infiquetra/core"
    assert payload["issue"] == 42
    assert [pr["round"] for pr in payload["prior_prs"]] == [1, 2]
    assert payload["prior_prs"][0]["number"] == 11
    assert payload["prior_prs"][0]["body_preview"] == "Implements ADR-0004 work."
    assert payload["rounds_seen"] == [1, 2]
    assert payload["next_round"] == 3
    # No saga saved -> the legacy "checkpoint" key is None.
    assert payload["checkpoint"] is None
    assert payload["journal"] == {"learnings": [], "decisions": []}


def test_load_saga_context_default_owner_when_no_slash(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    module = _load_module("load_saga_context.py")
    _patch_gh(saga, monkeypatch, "[]")

    _, payload = _run_main(module, ["--repo", "core", "--issue", "1"], capsys, monkeypatch)

    assert payload["repo"] == "infiquetra/core"
    assert payload["rounds_seen"] == []
    assert payload["next_round"] == 1
    assert payload["prior_prs"] == []


def test_load_saga_context_gh_failure_returns_empty_prs(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    module = _load_module("load_saga_context.py")
    _patch_gh(saga, monkeypatch, "", returncode=1)

    _, payload = _run_main(module, ["--repo", "core", "--issue", "1"], capsys, monkeypatch)

    assert payload["prior_prs"] == []
    assert payload["rounds_seen"] == []
    assert payload["next_round"] == 1


def test_load_saga_context_resolves_renamed_saga_dir_by_filename(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """NEW: the issue's saga resolves via sagas/issue-N/ (latest filename), not
    a checkpoints/ mtime glob. ADR refs extracted from the saga body."""
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    # Older tick references ADR-0004; newer (by filename) references ADR 12.
    saga.save(tmp_path, _make_saga(saga, id="42", summary="ADR-0004 older"), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, id="42", summary="ADR 12 newer"), now=later)
    module = _load_module("load_saga_context.py")
    _patch_gh(saga, monkeypatch, "[]")

    _, payload = _run_main(module, ["--repo", "core", "--issue", "42"], capsys, monkeypatch)

    assert payload["checkpoint"] is not None
    # Latest tick by FILENAME wins.
    assert payload["checkpoint"]["name"] == "20260602-141233.md"
    assert "ADR 12 newer" in payload["checkpoint"]["content_preview"]
    assert payload["adr_refs"] == ["ADR-0012"]


def test_load_saga_context_journal_matches_issue_and_adr(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)
    journal_dir = tmp_path / "docs" / "engineering-journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "LEARNINGS.md").write_text(
        "# Learnings\n\n## Entry about #42 work\nSomething learned.\n", encoding="utf-8"
    )
    (journal_dir / "DECISIONS.md").write_text(
        "# Decisions\n\n## Unrelated\nNo refs here.\n", encoding="utf-8"
    )
    saga.save(tmp_path, _make_saga(saga, id="42", summary="ADR-0004 reference"), now=FIXED_NOW)
    module = _load_module("load_saga_context.py")
    _patch_gh(saga, monkeypatch, "[]")

    _, payload = _run_main(module, ["--repo", "core", "--issue", "42"], capsys, monkeypatch)

    learnings = payload["journal"]["learnings"]
    assert len(learnings) == 1
    assert learnings[0]["title"] == "Entry about #42 work"
    assert payload["journal"]["decisions"] == []


# ===========================================================================
# Engine: orchestration choice-vs-recommendation recording (U3 — R12)
# ===========================================================================


def test_older_saga_without_recommendation_fields_loads_with_defaults(saga: ModuleType) -> None:
    """An envelope that lacks orchestration_recommended / orchestration_operator_choice
    must still parse cleanly -- backward-compatible with pre-U3 sagas.

    Uses render_envelope on a saga WITHOUT the new fields set (relying on their
    empty-string defaults), then manually strips the two new fields from the rendered
    text to simulate an older envelope written before U3 existed.
    """
    # Build a saga with new fields at default (empty) and render it.
    s = _make_saga(saga, orchestration_mode="inline")
    rendered = saga.render_envelope(s)
    # Strip the two new lines to simulate a pre-U3 envelope.
    old_envelope_lines = [
        line
        for line in rendered.splitlines(keepends=True)
        if not line.startswith("orchestration_recommended:")
        and not line.startswith("orchestration_operator_choice:")
    ]
    old_envelope = "".join(old_envelope_lines)
    assert "orchestration_recommended" not in old_envelope
    assert "orchestration_operator_choice" not in old_envelope

    restored = saga.parse_envelope(old_envelope)
    # The saga_id / orchestration_mode must survive normally.
    assert restored.saga_id == "issue-42"
    assert restored.orchestration_mode == "inline"
    # New fields default to empty string when absent from the envelope.
    assert restored.orchestration_recommended == ""
    assert restored.orchestration_operator_choice == ""


def test_orchestration_fields_default_to_empty_string_in_saga(saga: ModuleType) -> None:
    """The new fields have empty-string defaults so callers need not supply them."""
    s = _make_saga(saga)
    assert s.orchestration_recommended == ""
    assert s.orchestration_operator_choice == ""


def test_orchestration_override_rate_fields_present_in_frontmatter_output(saga: ModuleType) -> None:
    """render_envelope emits both new fields into the frontmatter."""
    s = _make_saga(
        saga,
        orchestration_recommended="team-execution",
        orchestration_operator_choice="team-execution",
    )
    rendered = saga.render_envelope(s)
    assert "orchestration_recommended: team-execution" in rendered
    assert "orchestration_operator_choice: team-execution" in rendered


# ===========================================================================
# Suite guard: nothing writes a .claude/ under the repo root during the run.
# ===========================================================================


# Collection-time snapshot: real operator saga state already on this machine (the repo's
# .claude/saga is live, machine-local state on a dev box) is NOT test leakage. Only dirs
# that appear AFTER collection — i.e. created by this test run — count as leaks.
_PREEXISTING_SAGA_DIRS = (
    frozenset(p.name for p in (ROOT / SAGAS_DIR).iterdir())
    if (ROOT / SAGAS_DIR).exists()
    else frozenset()
)
# Same collection-time baseline for the legacy-checkpoint format (#314 AC#4): a legacy
# checkpoint that predates the run is real operator state, not leakage.
_PREEXISTING_LEGACY_CHECKPOINTS = (
    frozenset(p.name for p in (ROOT / LEGACY_CHECKPOINT_DIR).glob("issue-*-phase*.md"))
    if (ROOT / LEGACY_CHECKPOINT_DIR).exists()
    else frozenset()
)


def _leaked_children(current: frozenset[str], baseline: frozenset[str]) -> list[str]:
    """Names present now but absent from the collection-time baseline.

    Both guard branches share this: a name in ``current`` that was not in ``baseline``
    appeared *during* the run and is therefore test leakage. A pre-existing live saga (or
    legacy checkpoint) sits in the baseline and is ignored — the false positive #314 fixed.
    Returns a sorted list so failure messages are deterministic.
    """
    return sorted(current - baseline)


def test_suite_does_not_create_claude_dir_under_repo_root() -> None:
    """Every test must land its state in tmp_path; none under the repo's .claude/.

    ``.gitignore`` hides ``.claude/``, so a test that forgot to ``chdir`` (or
    passed the real cwd as ``root``) would silently pollute the working tree
    without ``git status`` noticing. This guard fails loudly instead — but only
    on dirs created during this run (baseline above), so live operator saga
    state on a dev machine does not false-positive the gate.
    """
    stray_sagas = ROOT / SAGAS_DIR
    if stray_sagas.exists():
        current = frozenset(p.name for p in stray_sagas.iterdir())
        leaked = _leaked_children(current, _PREEXISTING_SAGA_DIRS)
        assert leaked == [], f"saga tests leaked state under repo-root .claude/: {leaked}"
    stray_legacy = ROOT / LEGACY_CHECKPOINT_DIR
    if stray_legacy.exists():
        current_cp = frozenset(p.name for p in stray_legacy.glob("issue-*-phase*.md"))
        leaked_cp = _leaked_children(current_cp, _PREEXISTING_LEGACY_CHECKPOINTS)
        assert leaked_cp == [], f"saga tests leaked legacy checkpoints: {leaked_cp}"


# --- #314: leak-guard precision — helper logic + guard-wiring proofs -------


def test_leaked_children_flags_new_entries() -> None:
    """A name absent from the baseline is reported as leaked (R2: a new dir is caught)."""
    assert _leaked_children(frozenset({"issue-99"}), frozenset()) == ["issue-99"]


def test_leaked_children_ignores_preexisting_entries() -> None:
    """A name already in the baseline (a live saga) is not a leak — the #314 fix."""
    assert _leaked_children(frozenset({"issue-42"}), frozenset({"issue-42"})) == []


def test_leaked_children_flags_only_the_new_among_preexisting() -> None:
    """A new dir is caught even while a pre-existing live saga coexists (the #281 case)."""
    assert _leaked_children(frozenset({"issue-42", "issue-99"}), frozenset({"issue-42"})) == [
        "issue-99"
    ]


def test_guard_raises_on_new_saga_dir_under_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard itself (not just the helper) fails when a NEW saga dir appears.

    Redirect the guard's ROOT to tmp_path so a fresh saga dir can be created without
    polluting the real repo (honoring the guard's own contract), then prove the guard
    raises — the literal #314 AC#1 protection.
    """
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_PREEXISTING_SAGA_DIRS", frozenset())
    (tmp_path / SAGAS_DIR / "issue-99").mkdir(parents=True)
    with pytest.raises(AssertionError, match="leaked state"):
        test_suite_does_not_create_claude_dir_under_repo_root()


def test_guard_passes_when_only_preexisting_saga_dir_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The guard does NOT fire on a saga dir that existed before the run (baseline)."""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_PREEXISTING_SAGA_DIRS", frozenset({"issue-99"}))
    (tmp_path / SAGAS_DIR / "issue-99").mkdir(parents=True)
    # No raise: the pre-existing dir is baselined out (the false positive #314 fixed).
    test_suite_does_not_create_claude_dir_under_repo_root()


def test_guard_raises_on_new_legacy_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy-checkpoint branch parity: a NEW checkpoint file trips the guard (#314 AC#4)."""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_PREEXISTING_LEGACY_CHECKPOINTS", frozenset())
    (tmp_path / LEGACY_CHECKPOINT_DIR).mkdir(parents=True)
    (tmp_path / LEGACY_CHECKPOINT_DIR / "issue-1-phase2.md").write_text("x", encoding="utf-8")
    with pytest.raises(AssertionError, match="legacy checkpoints"):
        test_suite_does_not_create_claude_dir_under_repo_root()


def test_guard_passes_when_only_preexisting_legacy_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy branch: a pre-existing checkpoint in the baseline does not false-positive."""
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "_PREEXISTING_LEGACY_CHECKPOINTS", frozenset({"issue-1-phase2.md"}))
    (tmp_path / LEGACY_CHECKPOINT_DIR).mkdir(parents=True)
    (tmp_path / LEGACY_CHECKPOINT_DIR / "issue-1-phase2.md").write_text("x", encoding="utf-8")
    # No raise: baselined out.
    test_suite_does_not_create_claude_dir_under_repo_root()


# ===========================================================================
# U4: Display-label map — decouple presentation from wire contract (R8 / KTD5)
# ===========================================================================


def test_display_orchestration_mode_falls_back_on_miss(saga: ModuleType) -> None:
    """An unknown key falls back to the raw string — never raises."""
    assert saga.display_orchestration_mode("unknown-future-mode") == "unknown-future-mode"
    assert saga.display_orchestration_mode("") == ""


def test_orchestration_mode_labels_covers_all_modes(saga: ModuleType) -> None:
    """Every value in ORCHESTRATION_MODES has an explicit entry in the label map.

    A future ORCHESTRATION_MODES extension that forgets to add a label is caught
    here (the fallback is intentional, but unregistered modes shouldn't stay
    accidentally unlabelled forever).
    """
    for mode in saga.ORCHESTRATION_MODES:
        assert mode in saga.ORCHESTRATION_MODE_LABELS, (
            f"Mode {mode!r} is in ORCHESTRATION_MODES but has no entry in "
            "ORCHESTRATION_MODE_LABELS — add a display label or the offer will "
            "fall back to the raw enum string silently."
        )


# ===========================================================================
# U2: gate_verdicts — capture in saga envelope (KTD4 / R1)
# ===========================================================================


def test_gate_verdicts_round_trips_through_render_parse(saga: ModuleType) -> None:
    """gate_verdicts survives render -> parse and appears in frontmatter."""
    verdicts = ["tests:done:https://github.com/o/r/pull/9", "lint:failed:path/to/file:42"]
    s = _make_saga(saga, gate_verdicts=verdicts)
    rendered = saga.render_envelope(s)
    # Field is present in frontmatter.
    assert "gate_verdicts:" in rendered
    restored = saga.parse_envelope(rendered)
    assert restored.gate_verdicts == verdicts


def test_gate_verdicts_save_restore_round_trip(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gate_verdicts written through save() are readable via restore()."""
    _stub_no_git(saga, monkeypatch)
    verdicts = ["tests:done:https://github.com/o/r/pull/9"]
    saga.save(tmp_path, _make_saga(saga, gate_verdicts=verdicts), now=FIXED_NOW)
    restored = saga.restore(tmp_path, "issue-42")
    assert restored is not None
    assert restored.gate_verdicts == verdicts


def test_gate_verdicts_merge_full_snapshot_replace(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An incoming populated gate_verdicts list REPLACES the prior tick's list."""
    _stub_no_git(saga, monkeypatch)
    saga.save(
        tmp_path,
        _make_saga(saga, gate_verdicts=["tests:done:ref-a", "lint:done:ref-b"]),
        now=FIXED_NOW,
    )
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, gate_verdicts=["tests:failed:ref-c"]), now=later)
    restored = saga.restore(tmp_path, "issue-42")
    assert restored.gate_verdicts == ["tests:failed:ref-c"]  # replaced, not unioned


def test_gate_verdicts_merge_absent_carries_forward(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ABSENT (omitted) gate_verdicts carries the prior tick's list forward."""
    _stub_no_git(saga, monkeypatch)
    verdicts = ["tests:done:ref-a"]
    saga.save(tmp_path, _make_saga(saga, gate_verdicts=verdicts), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    # ABSENT default for gate_verdicts -> carry forward; bump only phase.
    saga.save(tmp_path, _make_saga(saga, phase=5), now=later)
    restored = saga.restore(tmp_path, "issue-42")
    assert restored.gate_verdicts == verdicts
    assert restored.phase == 5


def test_gate_verdicts_merge_empty_list_clears(
    saga: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit [] gate_verdicts clears the prior tick's list."""
    _stub_no_git(saga, monkeypatch)
    saga.save(tmp_path, _make_saga(saga, gate_verdicts=["tests:done:ref"]), now=FIXED_NOW)
    later = datetime(2026, 6, 2, 14, 12, 33, tzinfo=UTC)
    saga.save(tmp_path, _make_saga(saga, gate_verdicts=[]), now=later)
    assert saga.restore(tmp_path, "issue-42").gate_verdicts == []


def test_parse_gate_verdict_splits_on_first_two_colons(saga: ModuleType) -> None:
    """parse_gate_verdict preserves a colon-bearing ref intact."""
    gate, state, ref = saga.parse_gate_verdict("tests:done:https://github.com/o/r/pull/9")
    assert gate == "tests"
    assert state == "done"
    assert ref == "https://github.com/o/r/pull/9"


def test_parse_gate_verdict_all_valid_states(saga: ModuleType) -> None:
    """All six R1 states are accepted without raising."""
    for state in ("done", "in-progress", "blocked", "failed", "halted", "not-reached"):
        g, s, r = saga.parse_gate_verdict(f"gate:{state}:some-ref")
        assert s == state


def test_parse_gate_verdict_rejects_unknown_state(saga: ModuleType) -> None:
    """An unknown state raises ValueError."""
    with pytest.raises(ValueError, match="unknown gate state"):
        saga.parse_gate_verdict("tests:bogus:x")


def test_gate_verdict_cli_flag_is_repeatable(
    saga: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--gate-verdict is repeatable and entries with colon-bearing refs survive."""
    monkeypatch.chdir(tmp_path)
    _stub_no_git(saga, monkeypatch)

    rc, payload = _run_main(
        saga,
        [
            "save",
            "--kind",
            "issue",
            "--id",
            "42",
            "--gate-verdict",
            "tests:done:https://github.com/o/r/pull/9",
            "--gate-verdict",
            "lint:failed:src/foo.py:12",
        ],
        capsys,
        monkeypatch,
    )

    assert rc == 0
    restored = saga.restore(tmp_path, "issue-42")
    assert restored is not None
    assert "tests:done:https://github.com/o/r/pull/9" in restored.gate_verdicts
    assert "lint:failed:src/foo.py:12" in restored.gate_verdicts


def test_gate_verdicts_absent_by_default_on_new_saga(saga: ModuleType) -> None:
    """A freshly-built Saga has gate_verdicts == ABSENT (sentinel, not [])."""
    s = _make_saga(saga)
    assert s.gate_verdicts is saga.ABSENT
