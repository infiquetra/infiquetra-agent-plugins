"""Account propagation and mismatch detection for Orchestrate worker launches.

An explicit operator account selection survives into every worker launch and is verified after
launch. For Claude units, selecting company account translates into `--company-account` passed after
the vendor token. After launch, Orchestrate probes the worker's transcript root
(~/.claude-company/projects vs ~/.claude/projects); an account mismatch closes the run-owned session
and marks the unit failed with the named state `account_mismatch` -- never a silently personal worker.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
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
    spec = importlib.util.spec_from_file_location("_orchestrate_account", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A stub wrapper the module resolves instead of the machine's real one.

    `launcher()` refuses to go on when it cannot resolve the wrapper, so any command that reaches
    it dies on a runner that has no `agents` installed. Pointing `ORCHESTRATE_AGENT_LAUNCHER` at a
    stub the test wrote makes the resolution succeed identically with and without a real wrapper
    on PATH, which is the whole point: these tests are about account plumbing, not about what this
    machine happens to have installed.

    The stub answers `--help` in the wrapper's own shape because `assert_vendors_available` reads
    the `Tools:` block at `start` and `expand`. A stub that printed nothing would leave the roster
    empty and that check would return without checking anything -- passing for the wrong reason.
    """
    launcher = tmp_path / "agents"
    launcher.write_text(
        "#!/bin/sh\n"
        "cat <<'HELP'\n"
        "Usage: agents [options] <tool>\n"
        "\n"
        "Tools:\n"
        "  claude    Claude Code\n"
        "  codex     Codex CLI\n"
        "  grok      Grok CLI\n"
        "  opencode  OpenCode\n"
        "  qwen      Qwen CLI\n"
        "HELP\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("ORCHESTRATE_AGENT_LAUNCHER", str(launcher))


@pytest.fixture
def pane_reads_nothing(monkeypatch: pytest.MonkeyPatch, orchestrate: ModuleType) -> None:
    """No statusline to read, so the account falls through to the transcript-root probe.

    Without this the pane read reaches whatever `herdr` the machine has, which answers one way on
    a workstation and another on a runner. The tests that plant a transcript are about that probe,
    so the statusline is made to say nothing rather than left to the environment.
    """
    monkeypatch.setattr(orchestrate, "pane_account_label", lambda pane_id: None)


@pytest.fixture
def fake_claude_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    personal = tmp_path / "personal_claude" / "projects"
    company = tmp_path / "company_claude" / "projects"
    personal.mkdir(parents=True, exist_ok=True)
    company.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_PERSONAL_PROJECTS", str(personal))
    monkeypatch.setenv("CLAUDE_COMPANY_PROJECTS", str(company))
    return personal, company


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


def _unit(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": "do work",
        "branch": f"orch/r1-{name}",
        "status": "pending",
        **over,
    }


@pytest.mark.usefixtures("launcher_on_path")
class TestAccountArgvEmission:
    """Argv emission includes the account flag when company is selected; omitted when absent."""

    def test_unit_with_company_account_emits_flag_after_vendor(
        self, orchestrate: ModuleType
    ) -> None:
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="/plan #1",
            account="company",
        )
        argv = orchestrate.agent_argv(unit)
        assert "--company-account" in argv
        assert argv.index("--company-account") > argv.index("claude")

    def test_unit_with_company_account_variants(self, orchestrate: ModuleType) -> None:
        for acc in ("company", "company-account", "--company-account", "COMPANY"):
            unit = orchestrate.Unit(
                name="worker",
                vendor="claude",
                task="/plan #1",
                account=acc,
            )
            argv = orchestrate.agent_argv(unit)
            assert "--company-account" in argv

    def test_run_default_account_is_inherited_by_claude_units(
        self, orchestrate: ModuleType
    ) -> None:
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #1")
        argv = orchestrate.agent_argv(unit, default_account="company")
        assert "--company-account" in argv
        assert argv.index("--company-account") > argv.index("claude")

    def test_unit_account_wins_over_run_default(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #1", account="personal")
        argv = orchestrate.agent_argv(unit, default_account="company")
        assert "--company-account" not in argv

    def test_no_account_selection_omits_flag(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #1")
        argv = orchestrate.agent_argv(unit, default_account=None)
        assert "--company-account" not in argv

    def test_non_claude_vendor_does_not_emit_company_account(self, orchestrate: ModuleType) -> None:
        for vendor in ("grok", "codex", "qwen", "opencode"):
            unit = orchestrate.Unit(
                name="worker", vendor=vendor, task="/plan #1", account="company"
            )
            argv = orchestrate.agent_argv(unit, default_account="company")
            assert "--company-account" not in argv

    def test_does_not_duplicate_existing_launch_args(self, orchestrate: ModuleType) -> None:
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="/plan #1",
            account="company",
            launch_args=["--company-account"],
        )
        argv = orchestrate.agent_argv(unit)
        assert argv.count("--company-account") == 1

    def test_workspace_precedes_vendor_while_account_follows_vendor(
        self, orchestrate: ModuleType
    ) -> None:
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="/plan #1",
            workspace="lane-a",
            account="company",
        )
        argv = orchestrate.agent_argv(unit)
        assert argv.index("--workspace") < argv.index("claude")
        assert argv.index("--company-account") > argv.index("claude")


@pytest.mark.usefixtures("launcher_on_path")
class TestAccountSchemaAndLifecycle:
    """Plan schema serialization, start, expand, and replacement preserve account."""

    def test_start_loads_plan_account(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plan = {
            "run_id": "test-run",
            "source": "#781",
            "account": "company",
            "units": [{"name": "u1", "vendor": "claude", "task": "/plan #781"}],
        }
        plan_file = repo / "plan.json"
        plan_file.write_text(json.dumps(plan))
        monkeypatch.chdir(repo)

        # `start` requires the record and never creates one (issue #1025).
        _support.write_record(test_store(), _support.TEST_ISSUE, units=None)
        orchestrate.cmd_start(NS(plan=str(plan_file), base=None, branch=None))
        r = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        assert r.account == "company"
        assert r.units[0].name == "u1"

    def test_expand_updates_run_account(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_run(repo, [_unit("u1")])
        expand_plan = {
            "account": "company",
            "units": [{"name": "u2", "vendor": "claude", "task": "/work #781"}],
        }
        plan_file = repo / "expand.json"
        plan_file.write_text(json.dumps(expand_plan))
        monkeypatch.chdir(repo)

        orchestrate.cmd_expand(NS(plan=str(plan_file)))
        r = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        assert r.account == "company"
        assert len(r.units) == 2

    def test_replacement_worker_preserves_template_account(self, orchestrate: ModuleType) -> None:
        template = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="/saga:work",
            account="company",
        )
        req = {
            "fix_id": "req-1",
            "owner": "review-fixer",
            "touched_paths": ["plugins/orchestrate/file.py"],
            "instruction": "fix something",
        }
        rep = orchestrate._replacement_worker(template, req, None, set())
        assert rep.account == "company"

    def test_save_and_load_round_trip(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_run(
            repo,
            [_unit("u1", account="company"), _unit("u2", account="personal")],
            account="company",
        )
        monkeypatch.chdir(repo)
        r = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        assert r.account == "company"
        assert r.units[0].account == "company"
        assert r.units[1].account == "personal"

        r.save()
        reloaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        assert reloaded.account == "company"
        assert reloaded.units[0].account == "company"
        assert reloaded.units[1].account == "personal"


@pytest.mark.usefixtures("launcher_on_path", "pane_reads_nothing")
class TestPostLaunchAccountVerification:
    """Post-launch verification validates transcript root; mismatch marks named failure."""

    def test_matching_company_transcript_confirms_account(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, company_root = fake_claude_roots
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-1",
            pane_id="pane-1",
        )

        slug = orchestrate.claude_project_slug(repo)
        proj_dir = company_root / slug
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "session.jsonl").write_text('{"type":"session"}\n')

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
        assert "account" not in receipt["confirmed_against_herdr"]
        assert receipt["confirmed_outside_herdr"] == ["account"]
        assert receipt["account"] == "company"

    def test_mismatch_worker_transcript_under_personal_root_raises_and_closes_session(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        personal_root, _ = fake_claude_roots
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-1",
            pane_id="pane-1",
        )

        # Worker landed on personal account
        slug = orchestrate.claude_project_slug(repo)
        proj_dir = personal_root / slug
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "session.jsonl").write_text('{"type":"session"}\n')

        closed_tabs: list[str] = []
        monkeypatch.setattr(
            orchestrate,
            "close_run_session",
            lambda u: closed_tabs.append(u.tab_id),
        )
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

        with pytest.raises(orchestrate.AccountMismatchError) as excinfo:
            orchestrate.verify_unit_preflight(unit, "pane-1", ready=True)

        assert "account mismatch" in str(excinfo.value)
        assert closed_tabs == ["tab-1"]
        assert unit.status == orchestrate.ACCOUNT_MISMATCH
        assert "account mismatch" in unit.note

    def test_mismatch_personal_requested_but_company_transcript_found(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, company_root = fake_claude_roots
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="personal",
            tab_id="tab-2",
            pane_id="pane-2",
        )

        slug = orchestrate.claude_project_slug(repo)
        proj_dir = company_root / slug
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "session.jsonl").write_text('{"type":"session"}\n')

        closed_tabs: list[str] = []
        monkeypatch.setattr(
            orchestrate,
            "close_run_session",
            lambda u: closed_tabs.append(u.tab_id),
        )
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-2",
                    "cwd": str(repo),
                    "interactive_ready": True,
                    "agent": "claude",
                }
            ],
        )

        with pytest.raises(orchestrate.AccountMismatchError):
            orchestrate.verify_unit_preflight(unit, "pane-2", ready=True)

        assert closed_tabs == ["tab-2"]
        assert unit.status == orchestrate.ACCOUNT_MISMATCH

    def test_newer_transcript_under_wrong_root_detected_as_mismatch(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        personal_root, company_root = fake_claude_roots
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-3",
            pane_id="pane-3",
        )

        slug = orchestrate.claude_project_slug(repo)
        (company_root / slug).mkdir(parents=True, exist_ok=True)
        (personal_root / slug).mkdir(parents=True, exist_ok=True)

        company_file = company_root / slug / "old.jsonl"
        personal_file = personal_root / slug / "new.jsonl"
        company_file.write_text('{"type":"old"}\n')
        personal_file.write_text('{"type":"new"}\n')

        # Make personal file newer
        os.utime(company_file, (time.time() - 100, time.time() - 100))
        os.utime(personal_file, (time.time(), time.time()))

        monkeypatch.setattr(
            orchestrate,
            "close_run_session",
            lambda u: None,
        )
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-3",
                    "cwd": str(repo),
                    "interactive_ready": True,
                    "agent": "claude",
                }
            ],
        )

        with pytest.raises(orchestrate.AccountMismatchError):
            orchestrate.verify_unit_preflight(unit, "pane-3", ready=True)

        assert unit.status == orchestrate.ACCOUNT_MISMATCH


@pytest.mark.usefixtures("launcher_on_path", "pane_reads_nothing")
class TestCmdGoAccountIntegration:
    """`orchestrate go` emits `--company-account` for claude units under selection and stops on mismatch."""

    def test_cmd_go_emits_company_account_for_claude_units(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(
            repo,
            [
                _unit("claude-worker", vendor="claude"),
                _unit("grok-worker", vendor="grok"),
            ],
            account="company",
        )
        monkeypatch.chdir(repo)

        recorded_argvs: list[list[str]] = []
        real_run = orchestrate.run

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                recorded_argvs.append(list(cmd))
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout='{"tab_id":"tab-1","agent_name":"worker","pane_id":"pane-1"}\n',
                    stderr="",
                )
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda *args, **kwargs: True)
        # Both herdr readings a launch takes, pinned: the ownership snapshot and the agent list.
        # Unpinned, fake_run passed them through to the herdr on PATH (issue 907, U34).
        monkeypatch.setattr(orchestrate, "list_tab_ids", lambda *args, **kwargs: frozenset())
        monkeypatch.setattr(orchestrate, "live_agents", lambda *args, **kwargs: [])
        monkeypatch.setattr(orchestrate, "took_the_task", lambda *args, **kwargs: True)
        monkeypatch.setattr(orchestrate, "check_unit_account", lambda *args, **kwargs: (True, None))

        ret = orchestrate.cmd_go(NS(limit=None))
        assert ret == 0

        assert len(recorded_argvs) == 2
        claude_argv = recorded_argvs[0]
        grok_argv = recorded_argvs[1]

        assert "--company-account" in claude_argv
        assert claude_argv.index("--company-account") > claude_argv.index("claude")
        assert "--company-account" not in grok_argv

    def test_cmd_go_marks_unit_account_mismatch_on_verified_mismatch(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        personal_root, _ = fake_claude_roots
        _write_run(
            repo,
            [_unit("worker", vendor="claude")],
            account="company",
        )
        monkeypatch.chdir(repo)

        sent_tasks: list[str] = []
        real_run = orchestrate.run
        worker_worktree: list[str] = []

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if cmd and cmd[0] == orchestrate.launcher():
                if "--cwd" in cmd:
                    wt = cmd[cmd.index("--cwd") + 1]
                    worker_worktree.append(wt)
                    slug = orchestrate.claude_project_slug(wt)
                    (personal_root / slug).mkdir(parents=True, exist_ok=True)
                    (personal_root / slug / "session.jsonl").write_text('{"type":"session"}\n')
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout='{"tab_id":"tab-1","agent_name":"worker","pane_id":"pane-1"}\n',
                    stderr="",
                )
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setattr(orchestrate, "await_ready", lambda *args, **kwargs: True)
        # The ownership snapshot, pinned so it never asks the herdr on PATH (issue 907, U34). An
        # empty snapshot makes tab-1 owned, so the mismatch below closes it -- and that close is
        # recorded here rather than sent to whatever herdr the host has.
        monkeypatch.setattr(orchestrate, "list_tab_ids", lambda *args, **kwargs: frozenset())
        closed: list[str] = []
        monkeypatch.setattr(
            orchestrate, "close_run_session", lambda unit: closed.append(unit.tab_id)
        )
        # The prompt door is observed at the Herdr boundary inside fake_run above; the writer
        # is real.
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "pane_id": "pane-1",
                    "cwd": worker_worktree[0] if worker_worktree else str(repo),
                    "interactive_ready": True,
                    "agent": "claude",
                }
            ],
        )

        orchestrate.cmd_go(NS(limit=None))

        r = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        worker = r.unit("worker")
        assert worker.status == orchestrate.ACCOUNT_MISMATCH
        assert "account mismatch" in worker.note
        # Task was never sent to the worker on the wrong account
        assert sent_tasks == []
        # The mismatch closed the tab this launch owned, and nothing else.
        assert closed == ["tab-1"]


@pytest.mark.usefixtures("launcher_on_path")
class TestStatuslineAccountEvidence:
    """The account is read off the session's own statusline, which exists at preflight time.

    Claude writes ``projects/<slug>/<id>.jsonl`` when the first prompt arrives, and preflight runs
    before the task is sent, so a transcript-only check has nothing to read at the moment it runs.
    """

    @staticmethod
    def _pane(monkeypatch: pytest.MonkeyPatch, orchestrate: ModuleType, text: str | None) -> None:
        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
            if cmd[:3] == ["herdr", "pane", "read"]:
                if text is None:
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such pane")
                return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")
            raise AssertionError(f"unexpected command {cmd}")

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setenv("USER", "operator")

    def test_company_statusline_is_read_as_company(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._pane(
            monkeypatch,
            orchestrate,
            "  operator [company]:/infiquetra/rev-781 (review/781)   /rc\n",
        )
        assert orchestrate.pane_account_label("pane-1") == "company"

    def test_plain_statusline_is_read_as_personal(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._pane(monkeypatch, orchestrate, "  operator:/infiquetra/rev-781 (review/781)   /rc\n")
        assert orchestrate.pane_account_label("pane-1") == "personal"

    def test_unreadable_pane_reports_nothing(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._pane(monkeypatch, orchestrate, None)
        assert orchestrate.pane_account_label("pane-1") is None

    def test_statuslineless_pane_reports_nothing(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._pane(monkeypatch, orchestrate, "some agent output with no statusline row\n")
        assert orchestrate.pane_account_label("pane-1") is None

    def test_ansi_coloured_statusline_is_read(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._pane(
            monkeypatch,
            orchestrate,
            "\x1b[0;36moperator\x1b[0m\x1b[0;35m [company]\x1b[0m:/infiquetra/rev-781\n",
        )
        assert orchestrate.pane_account_label("pane-1") == "company"

    def test_statusline_wins_over_a_stale_transcript_under_the_other_root(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        personal_root, _ = fake_claude_roots
        slug = orchestrate.claude_project_slug(repo)
        (personal_root / slug).mkdir(parents=True, exist_ok=True)
        (personal_root / slug / "old.jsonl").write_text("{}\n")
        self._pane(monkeypatch, orchestrate, "operator [company]:/x (main)\n")
        unit = orchestrate.Unit(
            name="worker", vendor="claude", task="do work", worktree=str(repo), account="company"
        )
        assert orchestrate.check_unit_account(unit, "pane-1", seconds=0) == (True, None)

    def test_no_transcript_yet_and_personal_statusline_is_a_loud_mismatch(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The 2026-08-23 incident, at the moment preflight actually runs: no transcript exists."""
        self._pane(monkeypatch, orchestrate, "operator:/infiquetra/orch-u5 (orch/r1-u5)\n")
        unit = orchestrate.Unit(
            name="worker", vendor="claude", task="do work", worktree=str(repo), account="company"
        )
        ok, error = orchestrate.check_unit_account(unit, "pane-1", seconds=0)
        assert ok is False
        assert error is not None and "on the personal account when company was required" in error

    def test_unreadable_account_is_a_stop_not_a_pass(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._pane(monkeypatch, orchestrate, None)
        unit = orchestrate.Unit(
            name="worker", vendor="claude", task="do work", worktree=str(repo), account="company"
        )
        ok, error = orchestrate.check_unit_account(unit, "pane-1", seconds=0)
        assert ok is False
        assert error is not None and "account unverified" in error

    def test_unknown_account_value_is_rejected_rather_than_ignored(
        self, orchestrate: ModuleType, repo: Path
    ) -> None:
        unit = orchestrate.Unit(
            name="worker", vendor="claude", task="do work", worktree=str(repo), account="compnay"
        )
        ok, error = orchestrate.check_unit_account(unit, "pane-1", seconds=0)
        assert ok is False
        assert error is not None and "unknown account selection" in error

    def test_no_account_requested_is_not_checked(self, orchestrate: ModuleType, repo: Path) -> None:
        unit = orchestrate.Unit(name="worker", vendor="claude", task="do work", worktree=str(repo))
        assert orchestrate.check_unit_account(unit, "pane-1", seconds=0) == (None, None)

    def test_dotted_worktree_slug_matches_claudes_own(self, orchestrate: ModuleType) -> None:
        """``/Users/operator/.claude`` is stored as ``-Users-operator--claude``: dots become dashes."""
        assert orchestrate.claude_project_slug("/Users/operator/.claude") == "-Users-operator--claude"

    def test_non_claude_unit_naming_an_account_is_recorded_as_requested_not_confirmed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A vendor with no account to read must not have one stamped as confirmed."""
        unit = orchestrate.Unit(
            name="worker",
            vendor="grok",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-9",
            pane_id="pane-9",
        )
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {"pane_id": "pane-9", "cwd": str(repo), "interactive_ready": True, "agent": "grok"}
            ],
        )

        receipt = orchestrate.verify_unit_preflight(unit, "pane-9", ready=True)
        assert "account" in receipt["requested_only"]
        assert "account" not in receipt["confirmed_against_herdr"]


@pytest.mark.usefixtures("launcher_on_path")
class TestNoSilentAccountSubstitution:
    """Proof that Orchestrate never silently substitutes personal or company accounts (#848)."""

    @staticmethod
    def _pane(monkeypatch: pytest.MonkeyPatch, orchestrate: ModuleType, text: str | None) -> None:
        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
            if cmd[:3] == ["herdr", "pane", "read"]:
                if text is None:
                    return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no such pane")
                return subprocess.CompletedProcess(cmd, 0, stdout=text, stderr="")
            raise AssertionError(f"unexpected command {cmd}")

        monkeypatch.setattr(orchestrate, "run", fake_run)
        monkeypatch.setenv("USER", "operator")

    def test_unverified_company_account_raises_and_never_substitutes_personal(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When company account cannot be verified, fail loudly rather than defaulting to personal."""
        self._pane(monkeypatch, orchestrate, None)
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-1",
            pane_id="pane-1",
        )

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

        with pytest.raises(orchestrate.AccountMismatchError) as excinfo:
            orchestrate.verify_unit_account(unit, "pane-1")

        assert "account unverified" in str(excinfo.value)
        assert unit.status == orchestrate.ACCOUNT_MISMATCH

    def test_mismatched_personal_statusline_refuses_launch_without_silent_override(
        self,
        orchestrate: ModuleType,
        repo: Path,
        fake_claude_roots: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Detected personal account when company was requested closes session and stops."""
        self._pane(monkeypatch, orchestrate, "operator:/infiquetra/repo (main)\n")

        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="company",
            tab_id="tab-1",
            pane_id="pane-1",
        )

        with pytest.raises(orchestrate.AccountMismatchError) as excinfo:
            orchestrate.verify_unit_account(unit, "pane-1")

        assert "on the personal account when company was required" in str(excinfo.value)
        assert unit.status == orchestrate.ACCOUNT_MISMATCH

    def test_unknown_account_value_rejected_without_default_substitution(
        self, orchestrate: ModuleType, repo: Path
    ) -> None:
        """An unknown account name fails fast and is never silently mapped to personal or company."""
        unit = orchestrate.Unit(
            name="worker",
            vendor="claude",
            task="do work",
            worktree=str(repo),
            account="enterprise-tier",
        )

        ok, error = orchestrate.check_unit_account(unit, "pane-1", seconds=0)
        assert ok is False
        assert error is not None
        assert "unknown account selection 'enterprise-tier'" in error
