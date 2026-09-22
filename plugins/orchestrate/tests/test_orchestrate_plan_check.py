"""A plan is validated completely, and nothing is created (issue 879, U4).

Every plan defect used to be discovered *after* worktrees existed and a run record was written,
because the only door to the validation was ``start``. ``plan-check`` is the first half of
``start`` exposed on its own -- not a copy, so a validator cannot quietly stop agreeing with the
``start`` it claims to match.

The mutation proof is the point of this module: asserting an exit status proves nothing about
whether the path wrote something on its way to that status.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orchestrate_support import (
    FakeProc,
    git,
    load_orchestrate,
    make_repo,
    unit_row,
    write_record,
)

#: The production driver this module drives. Constructed here, not imported from the shared
#: helper, so the module names on its own face the real file it crosses into.
ORCHESTRATE_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orch():
    return load_orchestrate("_orchestrate_plan_check", ORCHESTRATE_SCRIPT)


@pytest.fixture
def bed(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = make_repo(tmp_path, branch="issue/30")
    monkeypatch.chdir(repo)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(orch, "assert_agent_launcher_ingested", lambda: None)
    monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
    monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
    return repo, store


def write_plan(tmp_path: Path, **over) -> Path:
    plan = {
        "run_id": "r30",
        "units": [{"name": "u1", "vendor": "claude", "task": "do work"}],
    }
    plan.update(over)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def snapshot(repo: Path, store: Path) -> dict:
    return {
        "files": sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if ".git" not in p.parts),
        "branches": git(repo, "branch", "--list", "--format=%(refname:short)"),
        "worktrees": git(repo, "worktree", "list", "--porcelain"),
        "status": git(repo, "status", "--porcelain"),
        "store": sorted(str(p.name) for p in store.rglob("*")),
        "siblings": sorted(p.name for p in repo.parent.iterdir()),
    }


class TestAValidPlanCreatesNothing:
    def test_a_valid_plan_validates_clean_and_leaves_the_world_identical(
        self, orch, bed, tmp_path: Path
    ) -> None:
        repo, store = bed
        plan = write_plan(tmp_path)
        before = snapshot(repo, store)

        code = orch.main(["plan-check", "--plan", str(plan)])

        assert code == 0
        assert snapshot(repo, store) == before

    def test_it_is_safe_beside_an_active_run_and_leaves_that_record_untouched(
        self, orch, bed, tmp_path: Path
    ) -> None:
        repo, store = bed
        record = write_record(store, 30, units=[unit_row("live")], branch="issue/30")
        before = record.read_bytes()
        assert orch.main(["plan-check", "--plan", str(write_plan(tmp_path))]) == 0
        assert record.read_bytes() == before

    def test_exit_status_distinguishes_valid_from_invalid(self, orch, bed, tmp_path: Path) -> None:
        repo, store = bed
        assert orch.main(["plan-check", "--plan", str(write_plan(tmp_path))]) == 0
        bad = write_plan(
            tmp_path,
            units=[{"name": "u1", "vendor": "claude", "task": "t", "after": ["ghost"]}],
        )
        with pytest.raises(SystemExit):
            orch.main(["plan-check", "--plan", str(bad)])


class TestEveryAssertionIsReachable:
    def _refusal(self, orch, plan: Path) -> str:
        with pytest.raises(SystemExit) as caught:
            orch.main(["plan-check", "--plan", str(plan)])
        return str(caught.value)

    def test_an_unreachable_dependency_is_reported(self, orch, bed, tmp_path: Path) -> None:
        plan = write_plan(
            tmp_path,
            units=[{"name": "u1", "vendor": "claude", "task": "t", "after": ["ghost"]}],
        )
        assert "waits on 'ghost'" in self._refusal(orch, plan)

    def test_an_unsafe_unit_name_is_reported(self, orch, bed, tmp_path: Path) -> None:
        plan = write_plan(tmp_path, units=[{"name": "../escape", "vendor": "claude", "task": "t"}])
        assert "unit name" in self._refusal(orch, plan)

    def test_an_unsafe_run_id_is_reported(self, orch, bed, tmp_path: Path) -> None:
        plan = write_plan(tmp_path, run_id="../escape")
        assert "run id" in self._refusal(orch, plan)

    def test_a_retired_engine_preferences_key_is_reported(self, orch, bed, tmp_path: Path) -> None:
        plan = write_plan(tmp_path, engine_prefs={"reviewer": "codex"})
        assert "engine_prefs" in self._refusal(orch, plan)

    def test_an_unavailable_vendor_is_reported(
        self, orch, bed, unstubbed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The bed stubs this assertion out so the other tests do not depend on what this machine
        # has installed; here it is restored, with a fixed roster standing in for the wrapper.
        monkeypatch.setattr(unstubbed, "roster", lambda: [("claude", "model, effort")])
        monkeypatch.setattr(orch, "assert_vendors_available", unstubbed.assert_vendors_available)
        plan = write_plan(tmp_path, units=[{"name": "u1", "vendor": "nope", "task": "t"}])
        assert "cannot launch: nope" in self._refusal(orch, plan)

    def test_an_unreachable_saga_capability_is_reported(
        self, orch, bed, unstubbed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(unstubbed, "saga_capabilities", lambda vendor: [])
        monkeypatch.setattr(orch, "assert_saga_reachable", unstubbed.assert_saga_reachable)
        plan = write_plan(
            tmp_path, units=[{"name": "u1", "vendor": "claude", "task": "/saga:plan #1"}]
        )
        assert "saga is not installed for" in self._refusal(orch, plan)

    def test_a_duplicate_code_review_controller_is_reported(
        self, orch, bed, tmp_path: Path
    ) -> None:
        plan = write_plan(
            tmp_path,
            units=[
                {"name": "review", "vendor": "claude", "task": "/saga:code-review"},
                {"name": "review2", "vendor": "claude", "task": "/saga:code-review"},
            ],
        )
        assert "controller" in self._refusal(orch, plan)


@pytest.fixture(scope="module")
def unstubbed():
    """A second load of the driver, whose assertions the bed has not stubbed out.

    A function taken from here and rebound onto the module under test still resolves its own
    helpers through THIS module's globals, so a test that wants to steer one of them patches it
    here rather than on the module under test.
    """
    return load_orchestrate("_orchestrate_plan_check_helpers", ORCHESTRATE_SCRIPT)


class TestMutationProof:
    def test_a_seeded_write_inside_the_validation_path_fails_this_test(
        self, orch, bed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A validator asserted only by its exit status is not proven non-mutating.

        Every git command that writes, and every record save, raises here. The validation path
        must not reach one -- so seeding a write into it turns this test red, which is the
        property issue 879's acceptance criterion asks for.
        """
        repo, store = bed
        writing = {
            "worktree",
            "branch",
            "checkout",
            "commit",
            "add",
            "update-ref",
            "merge",
            "fetch",
            "push",
            "init",
        }

        def refusing_runner(cmd, **kw):
            if cmd[:1] == ["git"] and len(cmd) > 1 and cmd[1] in writing:
                raise AssertionError(f"the validation path ran a mutating git command: {cmd}")
            return FakeProc(0)

        def refusing_save(*a, **k):
            raise AssertionError("the validation path wrote a run record")

        monkeypatch.setattr(orch, "run", refusing_runner)
        monkeypatch.setattr(orch.Run, "save", refusing_save)

        assert orch.main(["plan-check", "--plan", str(write_plan(tmp_path))]) == 0
