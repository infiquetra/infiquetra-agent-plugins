"""Two decisions a unit carries that nothing else can recover: how it launches, and whether it lands.

Both exist because the live run for issue 48 lost them. The launcher needed an argument the unit had
no field for, so a whole review phase was started by hand and never entered the run record; and
``land`` merges every finished unit, which is the one thing the command's own documentation forbids
for competing plans, so every merge in that run was done by hand instead.

The landing tests drive ``cmd_land`` against a real git repository rather than a stand-in for one.
Merging is the behaviour under test, so a fake that reports a merge proves nothing about whether one
happened.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import orchestrate_support as _support
import pytest

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
    spec = importlib.util.spec_from_file_location("_orchestrate_launch_land", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a launcher where ``agent_argv`` will find one.

    ``agent_argv`` resolves the wrapper for real rather than trusting a name, so on a machine
    without it every one of these fails on the lookup instead of on the thing under test. Giving it
    a real file keeps that resolution in the test rather than stubbing it out -- the check is the
    reason a renamed wrapper stopped launching Cursor by mistake.
    """
    (tmp_path / "agents").write_text("#!/bin/sh\n")
    (tmp_path / "agents").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)


@pytest.mark.usefixtures("launcher_on_path")
class TestLauncherArgumentsArePassedThrough:
    """The plugin carries what the operator asked for; the launcher decides whether it is valid."""

    def test_extra_arguments_reach_the_command_line(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="reviewer",
            vendor="claude",
            task="/saga:code-review the build",
            model="opus",
            launch_args=["--company-account"],
        )
        argv = orchestrate.agent_argv(unit)
        assert "--company-account" in argv

    def test_they_follow_the_vendor_token(self, orchestrate: ModuleType) -> None:
        """The wrapper reads its own flags out of the arguments after the vendor name."""
        unit = orchestrate.Unit(
            name="reviewer", vendor="claude", task="x", launch_args=["--company-account"]
        )
        argv = orchestrate.agent_argv(unit)
        assert argv.index("--company-account") > argv.index("claude")

    def test_nothing_is_added_when_none_are_asked_for(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x")
        plain = orchestrate.agent_argv(unit)
        unit.launch_args = ["--company-account"]
        assert orchestrate.agent_argv(unit) == plain + ["--company-account"]

    def test_an_unknown_argument_is_not_rejected_here(self, orchestrate: ModuleType) -> None:
        """No allow-list: a stale one in this file is the same closed vocabulary one level up."""
        unit = orchestrate.Unit(
            name="reviewer", vendor="qwen", task="x", launch_args=["--not-a-real-flag"]
        )
        assert "--not-a-real-flag" in orchestrate.agent_argv(unit)


@pytest.mark.usefixtures("launcher_on_path")
class TestWorkspaceIsALauncherField:
    """``--workspace`` only works before the vendor token, so it is a field, not a passthrough."""

    def test_a_unit_workspace_is_emitted_before_the_vendor_token(
        self, orchestrate: ModuleType
    ) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x", workspace="issue-48")
        argv = orchestrate.agent_argv(unit)
        assert argv[argv.index("--workspace") + 1] == "issue-48"
        assert argv.index("--workspace") < argv.index("claude")

    def test_launch_args_still_follow_the_vendor_token(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="reviewer",
            vendor="claude",
            task="x",
            workspace="issue-48",
            launch_args=["--company-account"],
        )
        argv = orchestrate.agent_argv(unit)
        assert argv.index("--workspace") < argv.index("claude")
        assert argv.index("--company-account") > argv.index("claude")

    def test_a_unit_with_no_workspace_produces_today_s_argv(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x")
        argv = orchestrate.agent_argv(unit)
        assert "--workspace" not in argv
        with_args = orchestrate.Unit(
            name="reviewer", vendor="claude", task="x", launch_args=["--company-account"]
        )
        assert orchestrate.agent_argv(with_args) == argv + ["--company-account"]

    def test_a_run_default_is_inherited_when_the_unit_has_none(
        self, orchestrate: ModuleType
    ) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x")
        argv = orchestrate.agent_argv(unit, default_workspace="issue-48")
        assert argv[argv.index("--workspace") + 1] == "issue-48"
        assert argv.index("--workspace") < argv.index("claude")

    def test_a_unit_workspace_wins_over_the_run_default(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x", workspace="child-9")
        argv = orchestrate.agent_argv(unit, default_workspace="issue-48")
        assert argv[argv.index("--workspace") + 1] == "child-9"

    def test_absent_both_does_not_emit_the_flag(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="reviewer", vendor="claude", task="x")
        assert "--workspace" not in orchestrate.agent_argv(unit, default_workspace=None)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name + "\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A run branch plus two unit branches, each with one commit of its own."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
    for unit in ("alpha", "beta"):
        _git(r, "checkout", "-b", f"orch/r1-{unit}", "orch/r1")
        _commit(r, f"{unit}.txt")
        _git(r, "checkout", "main")
    # A record straight out of admission, with no orchestrate block: `start` requires one and
    # never creates one (issue #1025), so every repository here has been admitted.
    _support.write_record(r.parent / "orch-test-store", _support.TEST_ISSUE, units=None)
    return r


TEST_ISSUE = _support.TEST_ISSUE


def test_store(repo: Path) -> Path:
    """This test's record store, beside the repository rather than resolved (issue #1025)."""
    return repo.parent / "orch-test-store"


def _ns(repo: Path, **fields: object) -> argparse.Namespace:
    """A command Namespace carrying this test's issue and store."""
    defaults: dict[str, object] = {"remote": "origin", "compare": "main"}
    defaults.update(fields)
    return argparse.Namespace(issue=TEST_ISSUE, store_root=str(test_store(repo)), **defaults)


def _read_record(repo: Path) -> dict[str, Any]:
    """The record as it is on disk, in the shape the old run file was read in."""
    raw = _support.read_record(test_store(repo), TEST_ISSUE)
    return {**raw["orchestrate"], "units": raw["units"]}


def _write_run(repo: Path, units: list[dict[str, Any]], **overrides: Any) -> None:
    _support.ensure_origin(repo)
    base = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    _support.write_record(
        test_store(repo),
        TEST_ISSUE,
        units=[_support.fill_unit_row(u) for u in units],
        run_id="r1",
        source="a test",
        base=base,
        **{"branch": "orch/r1", **overrides},
    )


def _unit(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": "x",
        "branch": f"orch/r1-{name}",
        "status": "done",
        **over,
    }


def _claude_composer_pane(composer_line: str) -> str:
    rule = "\x1b[2m──────────────────────────────\x1b[0m"
    return f"{rule}\n{composer_line}\n{rule}\n"


def _staged_go_harness(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    *,
    existing_tabs: tuple[str, ...],
    agent_prompt_ok: bool,
    pane_dumps: list[str],
    accepted: list[bool] | None = None,
) -> list[list[str]]:
    """Stub only the Herdr boundary under cmd_go and record every command.

    The wrapper create returns tab w1:t1 / pane w1:p1; `herdr tab list` reports
    `existing_tabs`, which decides tab ownership; the ANSI pane read serves `pane_dumps`
    in order, one per inspection; `herdr agent prompt` succeeds or is refused per
    `agent_prompt_ok`, which decides whether a send types into the pane. `accepted` feeds
    took_the_task in order (default: always True). Returns every recorded command.
    """
    receipt = {"tab_id": "w1:t1", "agent_name": "alpha-2", "pane_id": "w1:p1", "reused": False}
    dumps = iter(pane_dumps)
    take = iter(accepted) if accepted is not None else None
    recorded: list[list[str]] = []

    def fake_run(cmd: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        if cmd[:3] == ["herdr", "tab", "list"]:
            tabs = {"result": {"tabs": [{"tab_id": t, "label": t} for t in existing_tabs]}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(tabs), "")
        if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
            return subprocess.CompletedProcess(cmd, 0, next(dumps), "")
        if cmd[:3] == ["herdr", "pane", "current"]:
            pane = {"result": {"pane": {"workspace_id": "w1"}}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pane), "")
        if cmd[:3] == ["herdr", "agent", "prompt"]:
            detail = "" if agent_prompt_ok else "not interactive ready"
            return subprocess.CompletedProcess(cmd, 0 if agent_prompt_ok else 1, "", detail)
        if cmd[0] == "agents":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(receipt), "")
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, f"{repo}\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def took(*_a: object, **_k: object) -> bool:
        return next(take) if take is not None else True

    monkeypatch.setattr(orchestrate, "run", fake_run)
    monkeypatch.setattr(orchestrate, "launcher", lambda: "agents")
    monkeypatch.setattr(orchestrate, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(orchestrate, "took_the_task", took)
    monkeypatch.setattr(
        orchestrate,
        "agent_row",
        lambda *_a, **_k: {
            "agent_status": "idle",
            "pane_id": "w1:p1",
            "workspace_id": "w1",
            "interactive_ready": True,
            "agent": "claude",
        },
    )
    monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)
    return recorded


def _on(repo: Path, branch: str, path: str) -> bool:
    got = subprocess.run(
        ["git", "cat-file", "-e", f"{branch}:{path}"], cwd=repo, capture_output=True
    )
    return got.returncode == 0


class TestLandHonoursMergeIntent:
    def test_a_unit_that_says_no_is_not_merged(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta", merge=False)])
        monkeypatch.chdir(repo)
        assert orchestrate.cmd_merge(_ns(repo, clean=False)) == 0

        assert _on(repo, "orch/r1", "alpha.txt"), "a plain unit should have landed"
        assert not _on(repo, "orch/r1", "beta.txt"), "merge=false should have been honoured"

    def test_the_skipped_unit_is_named(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Silence would read as 'everything landed', which is how a branch gets left behind."""
        _write_run(repo, [_unit("alpha"), _unit("beta", merge=False)])
        monkeypatch.chdir(repo)
        orchestrate.cmd_merge(_ns(repo, clean=False))

        out = capsys.readouterr().out
        assert "NOT MERGED BY REQUEST" in out
        assert "beta" in out

    def test_merging_is_the_default(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A plan written before this field existed must behave exactly as it did."""
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)
        orchestrate.cmd_merge(_ns(repo, clean=False))

        assert _on(repo, "orch/r1", "alpha.txt")
        assert _on(repo, "orch/r1", "beta.txt")
        assert "NOT MERGED BY REQUEST" not in capsys.readouterr().out

    def test_an_unfinished_unit_is_not_reported_as_skipped(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The report is about finished work held back, not about work still running."""
        _write_run(repo, [_unit("alpha"), _unit("beta", merge=False, status="running")])
        monkeypatch.chdir(repo)
        orchestrate.cmd_merge(_ns(repo, clean=False))

        assert "NOT MERGED BY REQUEST" not in capsys.readouterr().out

    def test_the_working_branch_is_restored(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha", merge=False)])
        monkeypatch.chdir(repo)
        orchestrate.cmd_merge(_ns(repo, clean=False))

        on = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert on == "main"


class TestCleanCanReapDuringARun:
    """`clean --merged` measured against the operator's tree, which sees nothing until `collect`.

    So the only mode safe to run unattended closed nothing for the whole run — exactly when sessions
    pile up — and the only way to reap mid-run was bare `clean`, which also discards the worktree of
    a unit that failed.
    """

    def test_a_landed_unit_is_reapable_before_collect(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git(repo, "checkout", "orch/r1")
        _git(repo, "merge", "--no-ff", "--no-edit", "orch/r1-alpha")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha")])
        monkeypatch.chdir(repo)
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))

        assert orchestrate.landed("orch/r1-alpha", r) is True

    def test_an_unlanded_unit_is_kept(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Its worktree is the evidence you look at when it went wrong."""
        _write_run(repo, [_unit("beta")])
        monkeypatch.chdir(repo)
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))

        assert orchestrate.landed("orch/r1-beta", r) is False

    def test_a_unit_that_never_merges_is_never_reaped(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A competing-plan branch holds the only copy of its plan, so it keeps its worktree."""
        _write_run(repo, [_unit("alpha", merge=False)])
        monkeypatch.chdir(repo)
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))

        assert orchestrate.landed("orch/r1-alpha", r) is False

    def test_a_run_with_no_run_branch_falls_back_to_the_operator_tree(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Old run files predate `land`; there is nothing else to measure against."""
        _write_run(repo, [_unit("alpha")], branch="")
        monkeypatch.chdir(repo)
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))

        assert orchestrate.landed("orch/r1-alpha", r) is False


@pytest.mark.usefixtures("launcher_on_path")
class TestRunWorkspaceIsInheritedAtLaunch:
    """A run default is stored on the run, copied onto a unit only when that unit has none."""

    def test_start_records_the_run_workspace(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        plan = repo / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "run_id": "r2",
                    "source": "a test",
                    "workspace": "issue-48",
                    "units": [{"name": "alpha", "vendor": "claude", "task": "x"}],
                }
            )
        )
        assert orchestrate.cmd_start(_ns(repo, plan=str(plan), base=None, branch=None)) == 0
        raw = _read_record(repo)
        assert raw["workspace"] == "issue-48"
        assert raw["units"][0].get("workspace") in (None, "")

    def test_go_copies_the_run_default_onto_a_unit_that_has_none(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(
            repo,
            [_unit("alpha", status="pending", branch=None, workspace=None)],
            workspace="issue-48",
        )
        monkeypatch.chdir(repo)
        seen: list[str | None] = []

        def fake_launch(
            unit: Any, backend: str = "inline", *, review_elsewhere: bool = False
        ) -> None:
            seen.append(unit.workspace)
            unit.status = "running"

        monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)
        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        assert seen == ["issue-48"]

    def test_go_does_not_overwrite_a_unit_workspace(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(
            repo,
            [_unit("alpha", status="pending", branch=None, workspace="child-9")],
            workspace="issue-48",
        )
        monkeypatch.chdir(repo)
        seen: list[str | None] = []

        def fake_launch(
            unit: Any, backend: str = "inline", *, review_elsewhere: bool = False
        ) -> None:
            seen.append(unit.workspace)
            unit.status = "running"

        monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)
        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        assert seen == ["child-9"]

    def test_staged_input_stop_returns_the_unit_to_retryable_pending(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """REL-01: both invariants of the staged-input stop, with the real ingested launch()
        and only the Herdr boundary stubbed. The first go stops on a staged composer and
        keeps the tab, pane and receipt; the second go, with the composer cleared,
        re-prompts the same pane and creates nothing. At the frozen revision the second go
        prints 'already has tab' and records no prompt."""
        _write_run(repo, [_unit("alpha", status="pending", branch=None)])
        monkeypatch.chdir(repo)
        recorded = _staged_go_harness(
            orchestrate,
            monkeypatch,
            repo,
            existing_tabs=("w1:t1",),
            agent_prompt_ok=True,
            pane_dumps=[
                _claude_composer_pane("❯ operator draft that was never sent"),
                _claude_composer_pane("❯ "),
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        saved = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")
        assert saved.status == orchestrate.PENDING
        assert saved.tab_id == "w1:t1"
        assert saved.pane_id == "w1:p1"
        assert saved.agent_name == "alpha-2"
        assert sum(1 for c in recorded if c[0] == "agents") == 1
        assert "already holds staged input" in saved.note
        assert "w1:p1" in saved.note
        assert "staged input withheld" in saved.note

        # The redelivery cycle that used to follow went with `_staged_input_stop` and `redrive`
        # (issue #1025): a unit that already holds a tab is now skipped and named, and the repair
        # is the launcher's own `redeliver`, by hand. The persisted-receipt assertion went with
        # the receipt records. What survives -- the stop returns the unit to PENDING, keeps its
        # identifiers, and says why -- is asserted above.
        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        saved = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")
        assert saved.status == orchestrate.PENDING
        assert saved.tab_id == "w1:t1"
        assert sum(1 for c in recorded if c[0] == "agents") == 1, "never a second launch"
        assert "already has tab w1:t1" in capsys.readouterr().out

    def test_repeated_staged_stop_keeps_identifiers_and_dedupes_the_note(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A retry that finds text again keeps the unit PENDING and its identifiers; an
        identical stop message appends nothing to the note, a differing one appends once."""
        _write_run(repo, [_unit("alpha", status="pending", branch=None)])
        monkeypatch.chdir(repo)
        _staged_go_harness(
            orchestrate,
            monkeypatch,
            repo,
            existing_tabs=("w1:t1",),
            agent_prompt_ok=True,
            pane_dumps=[
                _claude_composer_pane("❯ operator draft that was never sent"),
                _claude_composer_pane("❯ operator draft that was never sent"),
                _claude_composer_pane("❯ a longer operator draft that was still never sent"),
            ],
        )

        for _ in range(2):
            assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        saved = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")
        assert saved.status == orchestrate.PENDING
        assert saved.tab_id == "w1:t1"
        assert saved.pane_id == "w1:p1"
        assert saved.note.count("already holds staged input") == 1
        assert saved.note.count("staged input withheld") == 1

        # A third `go` no longer re-enters the stop: the unit holds a tab and is skipped, so the
        # note cannot grow. The dedupe rule itself -- an identical stop message appends nothing --
        # is what the counts above prove, and it is unchanged.
        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        saved = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")
        assert saved.status == orchestrate.PENDING
        assert saved.tab_id == "w1:t1"
        assert saved.note.count("already holds staged input") == 1
        assert saved.note.count("staged input withheld") == 1

    def test_already_has_tab_still_skips_a_pending_unit_without_the_staged_marker(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The direction not fixed: a PENDING unit carrying a tab AND a pane with no staged
        marker is an ordinary already-launched unit and is skipped, never redelivered. The
        unit carries a pane on purpose (terminal review F28): without one the stop predicate
        returned False on the pane check and this counter-case never reached the input_box
        clause it exists to observe."""
        _write_run(
            repo,
            [
                _unit(
                    "alpha",
                    status="pending",
                    branch=None,
                    tab_id="w1:t-old",
                    pane_id="w1:p-old",
                    launch_receipt={"input_box": "empty", "owned": False},
                )
            ],
        )
        monkeypatch.chdir(repo)
        launched: list[str] = []
        monkeypatch.setattr(
            orchestrate,
            "launch",
            lambda unit, *a, **k: launched.append(unit.name),
        )
        monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        saved = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")
        assert saved.status == "pending"
        assert launched == []
        assert "already has tab w1:t-old" in capsys.readouterr().out

    def test_a_pending_unit_with_a_pane_and_an_empty_receipt_is_skipped_not_redelivered(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Terminal review F28, second counter-case: a pane and a receipt with no input_box
        at all. Widening the clause so an empty receipt also routes to redelivery would
        re-prompt an already-launched unit into its live pane; this observes that edge."""
        _write_run(
            repo,
            [
                _unit(
                    "alpha",
                    status="pending",
                    branch=None,
                    tab_id="w1:t-old",
                    pane_id="w1:p-old",
                    launch_receipt={},
                )
            ],
        )
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orchestrate, "launch", lambda *_a, **_k: pytest.fail("launch was run"))
        monkeypatch.setattr(
            orchestrate, "redeliver", lambda *_a, **_k: pytest.fail("redeliver was run")
        )
        monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        assert orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha").status == "pending"
        assert "already has tab w1:t-old" in capsys.readouterr().out

    def test_a_fresh_pending_unit_goes_through_launch_never_redeliver(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The direction not fixed: a fresh PENDING unit without a tab is launched through
        the wrapper, never redelivered."""
        _write_run(repo, [_unit("alpha", status="pending", branch=None)])
        monkeypatch.chdir(repo)
        launched: list[str] = []
        redelivered: list[str] = []

        def fake_launch(unit: Any, *_a: object, **_k: object) -> None:
            launched.append(unit.name)
            unit.status = "running"

        def fake_redeliver(unit: Any, *_a: object, **_k: object) -> None:
            redelivered.append(unit.name)

        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        monkeypatch.setattr(orchestrate, "redeliver", fake_redeliver)
        monkeypatch.setattr(orchestrate, "make_worktree", lambda *_a, **_k: None)

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        assert launched == ["alpha"]
        assert redelivered == []
        assert orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha").status == "running"


def _git_branch_exists(repo: Path, branch: str) -> bool:
    res = subprocess.run(["git", "rev-parse", "--verify", branch], cwd=repo, capture_output=True)
    return res.returncode == 0


@pytest.mark.usefixtures("launcher_on_path")
class TestBackgroundNoFocusLaunchFlags:
    """The central agent_argv path must always lock the background no-focus invariant."""

    EXPECTED_FLAGS = ("--no-focus", "--current", "--herdr", "--herdr-control-only")

    @pytest.mark.parametrize(
        "vendor",
        ["claude", "codex", "grok", "muse", "agy", "qwen", "opencode"],
    )
    def test_complete_background_flags_emitted_before_vendor_token(
        self, orchestrate: ModuleType, vendor: str
    ) -> None:
        unit = orchestrate.Unit(name="worker", vendor=vendor, task="do work")
        argv = orchestrate.agent_argv(unit)
        vendor_idx = argv.index(vendor)
        for flag in self.EXPECTED_FLAGS:
            assert flag in argv, f"flag {flag!r} missing from agent_argv for vendor {vendor!r}"
            assert argv.index(flag) < vendor_idx, (
                f"flag {flag!r} emitted after vendor token {vendor!r}"
            )

    def test_background_flag_ordering_and_completeness(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree="/tmp/wt-worker",
            workspace="ws-1",
            model="opus",
            effort="high",
            launch_args=["--company-account"],
        )
        argv = orchestrate.agent_argv(unit)
        launcher_bin = orchestrate.launcher()
        expected_prefix = [
            launcher_bin,
            "--no-focus",
            "--current",
            "--herdr",
            "--herdr-control-only",
            "--task",
            "worker",
            "--cwd",
            "/tmp/wt-worker",
            "--workspace",
            "ws-1",
            "claude",
        ]
        assert argv[: len(expected_prefix)] == expected_prefix
        assert "--company-account" in argv
        assert argv.index("--company-account") > argv.index("claude")


@pytest.mark.usefixtures("launcher_on_path")
class TestExpansionAndCentralLauncher:
    """Expansion units must be persisted before creation and launched via central launcher."""

    def test_post_plan_expansion_persists_before_launch_and_uses_central_launcher(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        plan_file = repo / "initial-plan.json"
        plan_file.write_text(
            json.dumps(
                {
                    "run_id": "r1",
                    "source": "expansion test",
                    "workspace": "issue-773",
                    "units": [{"name": "planner", "vendor": "claude", "task": "plan"}],
                }
            )
        )
        assert orchestrate.cmd_start(_ns(repo, plan=str(plan_file), base=None, branch=None)) == 0

        # Expand with new units at later phase boundary
        expand_file = repo / "expand-plan.json"
        expand_file.write_text(
            json.dumps(
                {
                    "units": [
                        {
                            "name": "builder-1",
                            "vendor": "claude",
                            "task": "build 1",
                            "after": ["planner"],
                        },
                        {
                            "name": "builder-2",
                            "vendor": "grok",
                            "task": "build 2",
                            "after": ["planner"],
                        },
                    ]
                }
            )
        )
        assert orchestrate.cmd_expand(_ns(repo, plan=str(expand_file))) == 0

        # Assert persisted before any worktree or session is created
        run_data = _read_record(repo)
        unit_names = [u["name"] for u in run_data["units"]]
        assert unit_names == ["planner", "builder-1", "builder-2"]
        for u in run_data["units"]:
            if u["name"] in ("builder-1", "builder-2"):
                assert u["status"] == "pending"
                assert u.get("worktree") in (None, "")
                assert u.get("tab_id") in (None, "")

        # Create branch and commit for planner so 'after' dependency is satisfied
        _commit_file = repo / "planner.txt"
        _commit_file.write_text("plan doc\n")
        subprocess.run(
            ["git", "checkout", "-b", "orch/r1-planner", "orch/r1"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "add", "planner.txt"], cwd=repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "plan commit"],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)

        # Mark planner done in run.json
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        r.units[0].status = "done"
        r.units[0].branch = "orch/r1-planner"
        r.save()

        # Track launches via cmd_go
        launched_argvs: list[list[str]] = []
        original_run = orchestrate.run

        def intercept_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                launched_argvs.append(cmd)
                unit_name = cmd[cmd.index("--task") + 1]
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": f"tab-{unit_name}",
                            "pane_id": f"pane-{unit_name}",
                            "agent_name": unit_name,
                        }
                    )
                    + "\n",
                    stderr="",
                )
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", intercept_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(orchestrate, "send", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {"pane_id": "pane-builder-1", "agent": "claude", "interactive_ready": True},
                {"pane_id": "pane-builder-2", "agent": "grok", "interactive_ready": True},
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Verify that both expanded units launched through central launcher with no-focus flags
        assert len(launched_argvs) == 2
        for argv in launched_argvs:
            assert "--no-focus" in argv
            assert "--current" in argv
            assert "--herdr" in argv
            assert "--herdr-control-only" in argv

        # Verify run record completeness
        updated_run = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        for u in updated_run.units[1:]:
            assert u.status == "running"
            assert u.tab_id == f"tab-{u.name}"
            assert u.pane_id == f"pane-{u.name}"
            assert u.agent_name == u.name
            assert u.branch == f"orch/r1-{u.name}"
            assert u.worktree is not None and Path(u.worktree).exists()
            assert u.workspace == "issue-773"


@pytest.mark.usefixtures("launcher_on_path")
class TestNoFocusInvariantIntegration:
    """Integration test: operator focused pane is preserved before and after run-owned launches."""

    def test_operator_focused_pane_preserved_across_multiple_launches(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        # Create run with 3 pending units
        _write_run(
            repo,
            [
                _unit("unit1", status="pending", branch=None),
                _unit("unit2", status="pending", branch=None),
                _unit("unit3", status="pending", branch=None),
            ],
        )

        focused_pane = "pane-operator-main"
        original_run = orchestrate.run

        # Mock herdr / launcher interaction:
        # A launcher with --no-focus preserves the operator's active focused pane.
        # Without --no-focus it would switch focus to the new pane.
        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal focused_pane
            if cmd and cmd[0] == orchestrate.launcher():
                unit_name = cmd[cmd.index("--task") + 1]
                new_pane = f"pane-{unit_name}"
                if "--no-focus" not in cmd:
                    focused_pane = new_pane
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": f"tab-{unit_name}",
                            "pane_id": new_pane,
                            "agent_name": unit_name,
                        }
                    )
                    + "\n",
                    stderr="",
                )
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(orchestrate, "send", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {"pane_id": f"pane-{name}", "agent": "claude", "interactive_ready": True}
                for name in ("unit1", "unit2", "unit3")
            ],
        )

        pane_before = focused_pane
        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0
        pane_after = focused_pane

        assert pane_before == "pane-operator-main"
        assert pane_after == "pane-operator-main"

        # Verify run record contains every created worktree, branch, workspace, tab, pane, agent
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        for u in r.units:
            assert u.status == "running"
            assert u.worktree is not None and Path(u.worktree).exists()
            assert u.branch == f"orch/r1-{u.name}"
            assert u.tab_id == f"tab-{u.name}"
            assert u.pane_id == f"pane-{u.name}"
            assert u.agent_name == u.name


class TestScopedCleanup:
    """Cleanup remains limited to run-owned resources and never removes foreign resources."""

    def test_cleanup_only_touches_run_owned_resources(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        # Land run-owned alpha unit
        _git(repo, "checkout", "orch/r1")
        _git(repo, "merge", "--no-ff", "--no-edit", "orch/r1-alpha")
        _git(repo, "checkout", "main")

        wt_alpha = repo / ".orchestrate" / "wt-alpha"
        wt_alpha.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "add", "--detach", str(wt_alpha), "orch/r1-alpha")

        # Create foreign/unrelated worktree, branch, and tab
        foreign_wt = repo / "foreign-worktree"
        foreign_wt.mkdir(parents=True, exist_ok=True)
        _git(repo, "branch", "foreign-feature", "main")
        _git(repo, "worktree", "add", "--detach", str(foreign_wt), "foreign-feature")

        _write_run(
            repo,
            [
                _unit(
                    "alpha",
                    status="done",
                    branch="orch/r1-alpha",
                    worktree=str(wt_alpha),
                    tab_id="tab-run-alpha",
                    launch_receipt={"tab_id": "tab-run-alpha", "owned": True},
                ),
            ],
        )

        closed_tabs: list[str] = []
        original_run = orchestrate.run

        def track_tab_close(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["herdr", "tab", "close"]:
                closed_tabs.append(cmd[3])
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", track_tab_close)

        assert orchestrate.cmd_clean(_ns(repo, merged=True, branches=True, all=False)) == 0

        # Verify run-owned alpha tab and worktree were closed
        assert "tab-run-alpha" in closed_tabs
        assert not wt_alpha.exists()
        assert not _git_branch_exists(repo, "orch/r1-alpha")

        # Verify foreign resources were NOT touched
        assert foreign_wt.exists()
        assert _git_branch_exists(repo, "foreign-feature")

    def test_cleanup_does_not_close_a_tab_the_launch_did_not_own(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """cmd_clean must not issue herdr tab close when the receipt does not own the tab."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "operator",
                    status="running",
                    branch=None,
                    tab_id="tab-operator",
                    launch_receipt={"tab_id": "tab-operator", "owned": False},
                )
            ],
        )
        closed_tabs: list[str] = []
        original_run = orchestrate.run

        def track_tab_close(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd[:3] == ["herdr", "tab", "close"]:
                closed_tabs.append(cmd[3])
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", track_tab_close)
        assert orchestrate.cmd_clean(_ns(repo, merged=False, branches=False, all=False)) == 0
        assert closed_tabs == []


class TestStatusSurfacesUnrecordedDrift:
    """Status reports unrecorded unit branches matching the run prefix."""

    def test_status_reports_unrecorded_unit_branches(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        _git(repo, "branch", "orch/r1-untracked", "orch/r1")
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_status(_ns(repo)) == 0
        output = capsys.readouterr().out
        assert (
            "UNRECORDED untracked -- branch orch/r1-untracked is not a unit in this run" in output
        )


@pytest.mark.usefixtures("launcher_on_path")
class TestOpenCodeLaunchAndVariantRecipe:
    """OpenCode launch recipe, interactive /variants picker driving, and preflight verification."""

    def test_opencode_launches_through_agents_and_drives_variants_recipe(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Complete OpenCode recipe: agents launch, /variants driven, xhigh selected for max, verified receipt."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "mimir-builder",
                    vendor="opencode",
                    model="opencode/muse-spark-1.2-contributor-free",
                    effort="max",
                    task="/work build feature",
                    status="pending",
                    branch=None,
                )
            ],
        )

        executed_cmds: list[list[str]] = []
        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            executed_cmds.append(cmd)
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-mimir",
                            "pane_id": "pane-mimir",
                            "agent_name": "mimir-builder",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:4] == ["herdr", "pane", "read", "pane-mimir"]:
                # Live picker output offering up to xhigh (Team Mimir scenario).
                # After the select keystroke, the session row (not the typed echo) confirms.
                picker_output = (
                    "Select a variant:\n> Default\n  minimal\n  low\n  medium\n  high\n  xhigh\n"
                )
                selected = any(
                    c[:4] == ["herdr", "pane", "run", "pane-mimir"] and c[-1] == "xhigh"
                    for c in executed_cmds
                )
                stdout = "variant: xhigh\n" if selected else picker_output
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=stdout, stderr="")
            if cmd[:3] == ["herdr", "pane", "run"]:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-mimir",
                    "agent": "opencode",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Verify launch command passed through central launcher with model
        launcher_calls = [c for c in executed_cmds if c and c[0] == orchestrate.launcher()]
        assert len(launcher_calls) == 1
        launcher_argv = launcher_calls[0]
        assert "--no-focus" in launcher_argv
        assert "opencode" in launcher_argv
        assert "-m" in launcher_argv
        assert "opencode/muse-spark-1.2-contributor-free" in launcher_argv

        # Verify /variants was opened
        variant_open_calls = [
            c
            for c in executed_cmds
            if c[:4] == ["herdr", "pane", "run", "pane-mimir"] and c[4] == "/variants"
        ]
        assert len(variant_open_calls) == 1

        # Verify xhigh was selected (Team Mimir resolution for 'max' request)
        variant_select_calls = [
            c
            for c in executed_cmds
            if c[:4] == ["herdr", "pane", "run", "pane-mimir"] and c[4] == "xhigh"
        ]
        assert len(variant_select_calls) == 1

        # Verify task was submitted
        assert any("build feature" in p for p in sent_prompts)

        # Verify unit state and receipt
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "running"
        assert unit.variant == "xhigh"
        # The receipt is filled in memory by the launcher and is no longer PERSISTED (issue
        # #1025 removes the receipt records), so what a reload can be asked about is the state
        # that outlives the launch: the verified variant, and the note that says it was verified.
        # What the launcher was actually told is asserted against the argv above.
        assert "variant verified" in unit.note

    def test_non_opencode_vendor_does_not_send_variants(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-OpenCode vendors retain native controls and never receive /variants."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "claude-worker",
                    vendor="claude",
                    model="opus",
                    effort="high",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        executed_cmds: list[list[str]] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            executed_cmds.append(cmd)
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-claude",
                            "pane_id": "pane-claude",
                            "agent_name": "claude-worker",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "pane", "read"] and "--format" in cmd:
                empty = (
                    "\x1b[2m──────────────────────────────\x1b[0m\n"
                    "❯ \n"
                    "\x1b[2m──────────────────────────────\x1b[0m\n"
                )
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=empty, stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-claude",
                    "agent": "claude",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Verify no /variants commands were sent
        for cmd in executed_cmds:
            assert "/variants" not in cmd

        # Verify launch receipt recorded
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "running"
        # As above: the receipt is in-memory only now. The argv assertions above are what prove
        # this vendor was launched without the variant recipe, which is this test's subject.
        assert unit.variant in (None, "high")

    def test_opencode_picker_failure_fails_loudly_before_task_submission(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Picker read failure marks unit failed and never submits the task."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "mimir-builder",
                    vendor="opencode",
                    model="opencode/muse-spark-1.2-contributor-free",
                    effort="max",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-mimir",
                            "pane_id": "pane-mimir",
                            "agent_name": "mimir-builder",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:4] == ["herdr", "pane", "read", "pane-mimir"]:
                # Empty output simulates picker failure
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "pane", "run"]:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-mimir",
                    "agent": "opencode",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Verify task was NOT sent
        assert sent_prompts == []

        # Verify unit marked failed with clear note
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "failed"
        assert "unable to read live picker options" in unit.note

    def test_opencode_unavailable_variant_fails_loudly_before_task_submission(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Requesting an unavailable exact variant stops before task submission."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "mimir-builder",
                    vendor="opencode",
                    model="opencode/muse-spark-1.2-contributor-free",
                    effort="ultra",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-mimir",
                            "pane_id": "pane-mimir",
                            "agent_name": "mimir-builder",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:4] == ["herdr", "pane", "read", "pane-mimir"]:
                picker_output = "> Default\n  minimal\n  low\n  medium\n  high\n  xhigh\n"
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout=picker_output, stderr=""
                )
            if cmd[:3] == ["herdr", "pane", "run"]:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-mimir",
                    "agent": "opencode",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Verify task was NOT sent
        assert sent_prompts == []

        # Verify unit marked failed
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "failed"
        assert "ultra" in unit.note
        assert "options the live picker offered" in unit.note

    def test_mismatched_working_directory_stops_before_task_submission(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Working directory mismatch closes run session and fails loudly before task submission."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "worker",
                    vendor="claude",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        closed_tabs: list[str] = []
        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-bad-cwd",
                            "pane_id": "pane-bad-cwd",
                            "agent_name": "worker",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:3] == ["herdr", "pane", "current"]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps({"result": {"pane": {"workspace_id": "w80"}}}),
                    stderr="",
                )
            if cmd[:3] == ["herdr", "tab", "list"]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps({"result": {"tabs": []}}),
                    stderr="",
                )
            if cmd[:3] == ["herdr", "tab", "close"]:
                closed_tabs.append(cmd[3])
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [{"pane_id": "pane-bad-cwd", "cwd": "/wrong/worktree/dir", "agent": "claude"}],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # Session closed and task never sent
        assert "tab-bad-cwd" in closed_tabs
        assert sent_prompts == []

        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "failed"
        assert "differs from unit worktree" in unit.note

    def test_selection_that_the_session_never_reports_stops_before_task_submission(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A picker that closed on its old value is a silent substitution, so the task is withheld."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "mimir-builder",
                    vendor="opencode",
                    model="opencode/muse-spark-1.2-contributor-free",
                    effort="max",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        sent_prompts: list[str] = []
        selection_sent = False
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal selection_sent
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-mimir",
                            "pane_id": "pane-mimir",
                            "agent_name": "mimir-builder",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:4] == ["herdr", "pane", "read", "pane-mimir"]:
                # After the selection is typed the session shows no sign of having taken it.
                body = (
                    "waiting for input\n"
                    if selection_sent
                    else "> Default\n  minimal\n  low\n  medium\n  high\n  xhigh\n"
                )
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=body, stderr="")
            if cmd[:3] == ["herdr", "pane", "run"]:
                if len(cmd) > 4 and cmd[4] == "xhigh":
                    selection_sent = True
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-mimir",
                    "agent": "opencode",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        assert sent_prompts == []
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "failed"
        assert "does not report it" in unit.note

    def test_pre_picker_pane_output_is_not_mistaken_for_the_option_list(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A boot banner parses to tokens the ladder does not know, so the read is polled again."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "mimir-builder",
                    vendor="opencode",
                    model="opencode/muse-spark-1.2-contributor-free",
                    effort="xhigh",
                    task="do work",
                    status="pending",
                    branch=None,
                )
            ],
        )

        reads = 0
        executed_cmds: list[list[str]] = []
        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal reads
            executed_cmds.append(cmd)
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-mimir",
                            "pane_id": "pane-mimir",
                            "agent_name": "mimir-builder",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:4] == ["herdr", "pane", "read", "pane-mimir"]:
                reads += 1
                if reads == 1:
                    # The banner still on screen: bulleted, but nothing the variant ladder knows.
                    body = "- Loading plugins\n- Connecting session\n"
                else:
                    body = "> Default\n  minimal\n  low\n  medium\n  high\n  xhigh\n"
                return subprocess.CompletedProcess(cmd, returncode=0, stdout=body, stderr="")
            if cmd[:3] == ["herdr", "pane", "run"]:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-mimir",
                    "agent": "opencode",
                    "interactive_ready": True,
                }
            ],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        # The banner's own word was never typed into the session as a variant.
        typed = [c[4] for c in executed_cmds if c[:4] == ["herdr", "pane", "run", "pane-mimir"]]
        assert "Loading" not in typed
        assert typed == ["/variants", "xhigh"]

        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "running"
        assert unit.variant == "xhigh"
        assert any("do work" in p for p in sent_prompts)

    def test_workspace_mismatch_closes_the_run_session_and_withholds_the_task(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The plan names a workspace; herdr reports an id, so the two are joined before comparing."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "worker",
                    vendor="claude",
                    task="do work",
                    status="pending",
                    branch=None,
                    workspace="defects-a",
                )
            ],
        )

        closed_tabs: list[str] = []
        sent_prompts: list[str] = []
        original_run = orchestrate.run

        def mocked_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "tab_id": "tab-elsewhere",
                            "pane_id": "pane-elsewhere",
                            "agent_name": "worker",
                        }
                    )
                    + "\n",
                    stderr="",
                )
            if cmd[:3] == ["herdr", "pane", "current"]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps({"result": {"pane": {"workspace_id": "w80"}}}),
                    stderr="",
                )
            if cmd[:3] == ["herdr", "tab", "list"]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps({"result": {"tabs": []}}),
                    stderr="",
                )
            if cmd[:3] == ["herdr", "workspace", "list"]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "result": {
                                "workspaces": [
                                    {"label": "defects-a", "workspace_id": "w99"},
                                    {"label": "somewhere else", "workspace_id": "w01"},
                                ]
                            }
                        }
                    ),
                    stderr="",
                )
            if cmd[:3] == ["herdr", "tab", "close"]:
                closed_tabs.append(cmd[3])
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            if cmd[:3] == ["herdr", "agent", "prompt"]:
                sent_prompts.append(cmd[4] if len(cmd) > 4 else "")
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return cast(subprocess.CompletedProcess[str], original_run(cmd, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mocked_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [{"pane_id": "pane-elsewhere", "workspace_id": "w01", "agent": "claude"}],
        )

        assert orchestrate.cmd_go(_ns(repo, limit=0)) == 0

        assert "tab-elsewhere" in closed_tabs
        assert sent_prompts == []
        r = orchestrate.Run.load(TEST_ISSUE, test_store(repo))
        unit = r.units[0]
        assert unit.status == "failed"
        assert "does not match requested workspace" in unit.note

    def test_receipt_separates_what_herdr_confirmed_from_what_was_only_requested(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """herdr reports no model, so a receipt must not record one as verified."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [
                _unit(
                    "worker", vendor="claude", model="opus", task="x", status="pending", branch=None
                )
            ],
        )
        unit = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).units[0]
        unit.worktree = str(repo)
        unit.pane_id = "pane-1"
        unit.tab_id = "tab-1"
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-1",
                    "cwd": str(repo),
                    "interactive_ready": True,
                    "agent": "claude",
                }
            ],
        )

        receipt = orchestrate.verify_unit_preflight(unit, "pane-1", ready=True)

        assert "model" in receipt["requested_only"]
        assert "variant" in receipt["requested_only"]
        assert "working_directory" in receipt["confirmed_against_herdr"]
        assert "readiness" in receipt["confirmed_against_herdr"]
        assert receipt["readiness"] is True

    def test_readiness_in_the_receipt_is_observed_not_assumed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A session that never reported ready is recorded as such rather than stamped ready."""
        monkeypatch.chdir(repo)
        _write_run(
            repo,
            [_unit("worker", vendor="qwen", task="x", status="pending", branch=None)],
        )
        unit = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).units[0]
        unit.worktree = str(repo)
        unit.pane_id = "pane-1"
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-1",
                    "cwd": str(repo),
                    "interactive_ready": False,
                    "agent": "qwen",
                }
            ],
        )

        receipt = orchestrate.verify_unit_preflight(unit, "pane-1", ready=False)

        assert receipt["readiness"] is False


class TestRunFileCompatibility:
    """Issue 907 U9 (API-05): run files tolerate unknown unit keys, so a run written by a
    newer Orchestrate loads with a named notice instead of a TypeError."""

    def test_an_unknown_unit_key_loads_with_a_named_notice(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        row = _unit("alpha", status="pending", branch=None)
        row["vibrance"] = "high"
        _write_run(repo, [row])
        monkeypatch.chdir(repo)

        loaded = orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha")

        assert loaded.name == "alpha"
        assert not hasattr(loaded, "vibrance"), "the unknown key must not reach the unit"
        notice = capsys.readouterr()
        combined = notice.out + notice.err
        assert "alpha" in combined
        assert "vibrance" in combined
        module_path = orchestrate.__file__
        assert module_path is not None
        version = json.loads(
            (
                orchestrate._plugin_root(Path(module_path)) / ".claude-plugin" / "plugin.json"
            ).read_text()
        )["version"]
        assert version in combined

    def test_a_known_key_set_loads_silently(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha", status="pending", branch=None)])
        monkeypatch.chdir(repo)

        assert orchestrate.Run.load(TEST_ISSUE, test_store(repo)).unit("alpha").name == "alpha"
        assert capsys.readouterr().out == ""
        assert capsys.readouterr().err == ""

    def test_the_plugin_layout_helper_names_both_layouts(self, orchestrate: ModuleType) -> None:
        """ARCH-07: one helper owns the plugin layout depth, and it resolves the same
        relative depth in the repository layout and the installed cache."""
        repo_script = SCRIPT
        assert orchestrate._plugin_root(Path(repo_script)) == SCRIPT.parents[3]
        cache_script = (
            Path("/cache/marketplace/agent-launcher/1.10.0")
            / "skills"
            / "agent-launcher"
            / "scripts"
            / "launcher.py"
        )
        assert orchestrate._plugin_root(cache_script) == Path(
            "/cache/marketplace/agent-launcher/1.10.0"
        )
