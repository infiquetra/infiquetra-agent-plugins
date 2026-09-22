"""Orchestrate reads and writes saga's per-issue run record (issue #1025, U1).

The fixed-path run file is gone. What replaces it is one ``run_record.v1`` document per issue, so
two issues can be driven in one repository at once -- which is the card's fourth acceptance
criterion -- and so a unit's own worktree can see the same state the coordinator writes.

Every test here builds its own repository and its own record store under ``tmp_path``; none of
them resolves the real store, because that is the developer's live ``.claude/saga/runs``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orchestrate_support import (
    args,
    git,
    load_orchestrate,
    make_repo,
    read_record,
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
    return load_orchestrate("_orchestrate_record", ORCHESTRATE_SCRIPT)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    return root


class TestTwoIssuesCoexist:
    """The card's fourth acceptance criterion, proved through ``start`` alone."""

    def test_two_runs_for_two_issues_have_their_own_records(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
        monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
        monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
        monkeypatch.setattr(orch, "parent_branch_name", lambda issue, **kw: (f"issue/{issue}", "t"))

        paths = []
        for issue, unit_name in ((4001, "alpha"), (4002, "beta")):
            write_record(store, issue, units=None)
            plan = tmp_path / f"plan-{issue}.json"
            plan.write_text(
                json.dumps(
                    {
                        "run_id": str(issue),
                        "units": [{"name": unit_name, "vendor": "claude", "task": "do work"}],
                    }
                )
            )
            code = orch.cmd_start(args(issue, store, plan=str(plan), base=None, branch=None))
            assert code == 0
            paths.append(store / f"issue-{issue}.json")

        assert paths[0] != paths[1]
        assert all(path.is_file() for path in paths)
        first = read_record(store, 4001)
        second = read_record(store, 4002)
        assert [u["name"] for u in first["units"]] == ["alpha"]
        assert [u["name"] for u in second["units"]] == ["beta"]
        assert first["orchestrate"]["branch"] == "issue/4001"
        assert second["orchestrate"]["branch"] == "issue/4002"
        # Both branches exist side by side; neither run displaced the other.
        assert git(repo, "rev-parse", "--verify", "issue/4001")
        assert git(repo, "rev-parse", "--verify", "issue/4002")


class TestRecordContract:
    def test_an_unknown_schema_is_one_line_and_exit_three(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        path = write_record(store, 7, units=[unit_row("u1")])
        payload = json.loads(path.read_text())
        payload["schema"] = "run_record.v2"
        path.write_text(json.dumps(payload))

        code = orch.main(["status", "--issue", "7", "--store-root", str(store)])
        assert code == 3
        err = capsys.readouterr().err
        assert "unknown record version" in err
        assert "Traceback" not in err

    def test_an_unknown_top_level_field_survives_a_read_modify_write(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store,
            8,
            units=[unit_row("u1")],
            branch="issue/8",
            extra_top_level={"a_newer_field": {"kept": True}},
        )
        r = orch.Run.load(8, store)
        r.save()
        after = read_record(store, 8)
        assert after["a_newer_field"] == {"kept": True}
        assert "unknown top-level field 'a_newer_field'" in capsys.readouterr().err

    def test_this_plugins_own_block_is_not_warned_about(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """``orchestrate`` is unknown to the record and known here; warning trains blindness."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 9, units=[unit_row("u1")], branch="issue/9")
        orch.Run.load(9, store)
        assert "'orchestrate'" not in capsys.readouterr().err

    def test_a_missing_record_refuses_with_exit_two_and_names_the_path(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        code = orch.main(["status", "--issue", "404", "--store-root", str(store)])
        assert code == 2
        err = capsys.readouterr().err
        assert "no run record for issue 404" in err
        assert str(store) in err

    def test_the_orchestrate_block_round_trips_every_added_unit_key(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store,
            10,
            units=[
                unit_row(
                    "u1",
                    merge_state="merged",
                    launch_started_at="2026-09-19T01:02:03+00:00",
                    shared_blockers=[{"blocker_id": "b1", "owner_unit": "u2"}],
                )
            ],
            branch="issue/10",
        )
        r = orch.Run.load(10, store)
        r.save()
        row = read_record(store, 10)["units"][0]
        assert row["merge_state"] == "merged"
        assert row["launch_started_at"] == "2026-09-19T01:02:03+00:00"
        assert row["shared_blockers"] == [{"blocker_id": "b1", "owner_unit": "u2"}]

    def test_the_launch_receipt_is_never_persisted(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The receipt records go with issue #1025; the identity fields replace them."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 11, units=[unit_row("u1")], branch="issue/11")
        r = orch.Run.load(11, store)
        r.units[0].launch_receipt = {"provider": "claude", "pane": "w:1"}
        r.save()
        assert "launch_receipt" not in read_record(store, 11)["units"][0]


class TestStartRequiresTheRecord:
    def test_start_with_no_record_refuses_and_names_the_admission_command(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
        monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
        monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps({"run_id": "r", "units": [{"name": "u1", "vendor": "claude", "task": "t"}]})
        )

        code = orch.main(
            ["start", "--issue", "555", "--store-root", str(store), "--plan", str(plan)]
        )
        assert code == 2
        err = capsys.readouterr().err
        assert "admission.py --issue 555" in err
        assert not (store / "issue-555.json").exists()
        assert git(repo, "branch", "--list", "issue/555") == ""

    def test_start_leaves_the_admission_half_of_the_record_byte_identical(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
        monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
        monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
        monkeypatch.setattr(orch, "parent_branch_name", lambda issue, **kw: ("issue/12", "t"))
        write_record(store, 12, units=None)
        before = read_record(store, 12)
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps({"run_id": "r", "units": [{"name": "u1", "vendor": "claude", "task": "t"}]})
        )

        assert orch.cmd_start(args(12, store, plan=str(plan), base=None, branch=None)) == 0
        after = read_record(store, 12)
        for key in (
            "admission",
            "approval_scope",
            "run_configuration",
            "review_cycles",
            "roster",
        ):
            assert after[key] == before[key], key
        assert [u["name"] for u in after["units"]] == ["u1"]
