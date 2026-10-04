"""The table the operator approves is printed by the script, in one fixed format (issue #109).

Before this, the launch table in ``commands/orchestrate.md`` was drawn by the model, so it came out
differently every run and could differ from the plan file ``start`` then read. ``launch-table``
prints it from the plan itself, validated by the same checks ``start`` (or, with ``--issue``,
``expand``) runs, and creates nothing. The golden string below is the format; a change to it is a
change to what every harness shows the operator.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from orchestrate_support import load_orchestrate, make_repo, read_record, unit_row, write_record

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
    return load_orchestrate("_orchestrate_launch_table", ORCHESTRATE_SCRIPT)


@pytest.fixture
def bed(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = make_repo(tmp_path, branch="issue/30")
    monkeypatch.chdir(repo)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(orch, "assert_agent_launcher_ingested", lambda: None)
    monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
    monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
    monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
    return repo, store


GOLDEN_UNITS = [
    {
        "name": "plan-claude",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "permission": "bypass",
        "task": "/saga:plan #48 -- write the plan to docs/plans/ and commit it",
    },
    {
        "name": "plan-codex",
        "vendor": "codex",
        "model": "gpt-5.6-sol",
        "effort": "xhigh",
        "permission": "auto",
        "task": "$saga:plan #48, independently",
    },
    {
        "name": "docreview-qwen",
        "vendor": "qwen",
        "model": "qwen3-max",
        "setup": ["/effort high"],
        "permission": "auto",
        "task": "/doc-review docs/plans/plan.md",
        "after": ["plan-claude", "plan-codex"],
    },
    {
        "name": "runbook-claude",
        "vendor": "claude",
        "model": "sonnet",
        "effort": "medium",
        "permission": "auto",
        "task": "write the detection-rules section of docs/runbook.md and commit it",
    },
    {
        "name": "runbook-codex",
        "vendor": "codex",
        "task": "write the rollback-drill section of docs/runbook.md",
        "serialize": ["runbook-claude"],
    },
]

GOLDEN_LATER = [
    {"phase": "build", "what": "build it", "cap": "/work", "after": ["docreview-qwen"]},
    {"phase": "review", "what": "review the build", "cap": "/code-review", "after": ["build"]},
]

GOLDEN = """\
run r30   <- #48 deploy-guard remediation
plan {plan}   sha256 {sha}
vendors allowed: claude, codex, qwen   workspace: issue-48   account: -

unit           cap         agent  model       effort perm           after                  serialize      role task
-----------------------------------------------------------------------------------------------------------------------------------------------------------
plan-claude    /plan       claude opus        high   bypass         -                      -              -    /saga:plan #48 -- write the plan to docs/pl…
plan-codex     /plan       codex  gpt-5.6-sol xhigh  auto           -                      -              -    $saga:plan #48, independently
docreview-qwen /doc-review qwen   qwen3-max   high*  auto           plan-claude plan-codex -              -    /doc-review docs/plans/plan.md
runbook-claude -           claude sonnet      medium auto           -                      -              -    write the detection-rules section of docs/r…
runbook-codex  -           codex  -           -      auto (default) -                      runbook-claude -    write the rollback-drill section of docs/ru…

later phases (no units yet):
phase  what             cap          after
---------------------------------------------------
build  build it         /work        docreview-qwen
review review the build /code-review build
"""


def write_plan(tmp_path: Path, name: str = "plan.json", **over) -> Path:
    plan = {
        "run_id": "r30",
        "source": "#48 deploy-guard remediation",
        "workspace": "issue-48",
        "vendors_allowed": ["claude", "codex", "qwen"],
        "units": GOLDEN_UNITS,
        "later_phases": GOLDEN_LATER,
    }
    plan.update(over)
    path = tmp_path / name
    path.write_text(json.dumps(plan, indent=2))
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestTheFixedFormat:
    def test_a_plan_renders_byte_for_byte_to_the_golden_table(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(tmp_path)
        assert orch.main(["launch-table", "--plan", str(plan)]) == 0
        assert capsys.readouterr().out == GOLDEN.format(plan=plan, sha=sha(plan)[:12])

    @pytest.mark.parametrize(
        ("task", "cap"),
        [
            ("/saga:plan #48", "/plan"),
            ("$saga:doc-review docs/x.md", "/doc-review"),
            ("  /work docs/plans/x.md", "/work"),
            ("write the runbook", None),
            ("see /plan later", None),
        ],
    )
    def test_the_cap_column_names_the_saga_capability_a_task_opens_with(
        self, orch, task: str, cap: str | None
    ) -> None:
        assert orch.task_capability(task) == cap

    def test_no_later_phases_prints_no_later_block(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(tmp_path, later_phases=[])
        assert orch.main(["launch-table", "--plan", str(plan)]) == 0
        assert "later phases" not in capsys.readouterr().out

    def test_the_digest_changes_when_one_byte_of_the_plan_changes(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(tmp_path)
        assert orch.main(["launch-table", "--plan", str(plan), "--json"]) == 0
        first = json.loads(capsys.readouterr().out)["plan_sha256"]
        plan.write_text(plan.read_text() + " ")
        assert orch.main(["launch-table", "--plan", str(plan), "--json"]) == 0
        second = json.loads(capsys.readouterr().out)["plan_sha256"]
        assert first != second
        assert second == sha(plan)

    def test_json_carries_the_exact_text_and_the_rows(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(tmp_path)
        assert orch.main(["launch-table", "--plan", str(plan)]) == 0
        text = capsys.readouterr().out
        assert orch.main(["launch-table", "--plan", str(plan), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["schema"] == "orchestrate.launch_table.v1"
        assert payload["text"] == text
        assert payload["plan"] == str(plan)
        assert payload["plan_sha256"] == sha(plan)
        assert [unit["name"] for unit in payload["units"]] == [u["name"] for u in GOLDEN_UNITS]
        qwen = payload["units"][2]
        assert (qwen["effort"], qwen["effort_via_setup"]) == ("high", True)
        assert payload["units"][4]["permission_declared"] is False

    def test_the_undeclared_permission_notice_goes_to_stderr_not_into_the_table(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(tmp_path)
        assert orch.main(["launch-table", "--plan", str(plan)]) == 0
        captured = capsys.readouterr()
        assert "permission not declared" not in captured.out
        assert "permission not declared, inheriting auto: runbook-codex" in captured.err


class TestRefusals:
    def test_a_plan_start_would_refuse_prints_no_table(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plan = write_plan(
            tmp_path, units=[{"name": "u1", "vendor": "claude", "task": "t", "after": ["ghost"]}]
        )
        with pytest.raises(SystemExit) as caught:
            orch.main(["launch-table", "--plan", str(plan)])
        assert "waits on 'ghost', which is in no run" in str(caught.value)
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize(
        ("over", "message"),
        [
            ({"vendors_allowed": "claude"}, "vendors_allowed"),
            ({"later_phases": [{"phase": "p3"}]}, "`phase` and a `what`"),
            ({"later_phases": [{"phase": "p3", "what": "w", "after": "p2"}]}, "`after`"),
        ],
    )
    def test_a_malformed_display_key_is_refused(
        self, orch, bed, tmp_path: Path, over: dict, message: str
    ) -> None:
        with pytest.raises(SystemExit) as caught:
            orch.main(["launch-table", "--plan", str(write_plan(tmp_path, **over))])
        assert message in str(caught.value)


def snapshot(repo: Path, store: Path) -> dict:
    from orchestrate_support import git

    return {
        "files": sorted(str(p.relative_to(repo)) for p in repo.rglob("*") if ".git" not in p.parts),
        "branches": git(repo, "branch", "--list", "--format=%(refname:short)"),
        "worktrees": git(repo, "worktree", "list", "--porcelain"),
        "status": git(repo, "status", "--porcelain"),
        "store": {p.name: p.read_bytes() for p in sorted(store.rglob("*")) if p.is_file()},
        "siblings": sorted(p.name for p in repo.parent.iterdir()),
    }


class TestAnExpansionAgainstARunningRun:
    def test_an_expansion_renders_against_the_run_and_creates_nothing(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo, store = bed
        write_record(store, 30, units=[unit_row("p1a")], branch="issue/30", run_id="r30")
        added = write_plan(
            tmp_path,
            name="expand.json",
            run_id="ignored",
            later_phases=[],
            units=[{"name": "build", "vendor": "codex", "task": "/work x", "after": ["p1a"]}],
        )
        before = snapshot(repo, store)

        code = orch.main(
            ["launch-table", "--plan", str(added), "--issue", "30", "--store-root", str(store)]
        )

        assert code == 0
        out = capsys.readouterr().out
        assert out.startswith("run r30   <- ")
        assert "build" in out and "p1a" in out
        assert snapshot(repo, store) == before

    def test_a_name_already_in_the_run_is_refused_as_expand_refuses_it(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _repo, store = bed
        write_record(store, 30, units=[unit_row("p1a")], branch="issue/30", run_id="r30")
        added = write_plan(
            tmp_path,
            name="expand.json",
            units=[{"name": "p1a", "vendor": "codex", "task": "again"}],
        )
        with pytest.raises(SystemExit) as caught:
            orch.main(
                ["launch-table", "--plan", str(added), "--issue", "30", "--store-root", str(store)]
            )
        assert "is already in this run" in str(caught.value)
        assert capsys.readouterr().out == ""

    def test_a_missing_run_exits_2(
        self, orch, bed, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _repo, store = bed
        plan = write_plan(tmp_path)
        code = orch.main(
            ["launch-table", "--plan", str(plan), "--issue", "31", "--store-root", str(store)]
        )
        assert code == 2
        assert capsys.readouterr().out == ""


class TestAFreshPlanCreatesNothing:
    def test_launch_table_leaves_the_world_identical(self, orch, bed, tmp_path: Path) -> None:
        repo, store = bed
        write_record(store, 30, units=[unit_row("live")], branch="issue/30")
        plan = write_plan(tmp_path)
        before = snapshot(repo, store)
        assert orch.main(["launch-table", "--plan", str(plan)]) == 0
        assert orch.main(["launch-table", "--plan", str(plan), "--json"]) == 0
        assert snapshot(repo, store) == before


class TestStartIgnoresTheDisplayKeys:
    def test_a_plan_carrying_display_keys_starts_and_records_none_of_them(
        self, orch, bed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _repo, store = bed
        write_record(store, 30, units=None)
        monkeypatch.setattr(orch, "parent_branch_name", lambda issue: ("issue/30", "test"))
        plan = write_plan(tmp_path)

        code = orch.main(
            ["start", "--plan", str(plan), "--issue", "30", "--store-root", str(store)]
        )

        assert code == 0
        record = read_record(store, 30)
        dumped = json.dumps(record)
        assert "later_phases" not in dumped
        assert "vendors_allowed" not in dumped
        assert [unit["name"] for unit in record["units"]] == [u["name"] for u in GOLDEN_UNITS]
