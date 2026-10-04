"""Orchestrate reads and writes saga's per-issue run record (issue #1025, U1).

The fixed-path run file is gone. What replaces it is one ``run_record.v1`` document per issue, so
two issues can be driven in one repository at once -- which is the card's fourth acceptance
criterion -- and so a unit's own worktree can see the same state the coordinator writes.

Every test here builds its own repository and its own record store under ``tmp_path``; none of
them resolves the real store, because that is the developer's live ``.claude/saga/runs``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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


BUILD_LOOP = {
    "criterion": "tests pass",
    "iterations": [{"iteration": 1, "revision": "a" * 40, "green": True}],
    "handed_to_code_review": {"revision": "a" * 40, "at": "2026-10-04T00:00:00+00:00"},
}
USAGE = {
    "entries": [
        {
            "session_id": "s1",
            "role": "worker",
            "vendor": "claude",
            "model": "opus",
            "effort": "medium",
            "counts": {"uncached_input": 10, "output": 5},
        }
    ]
}


def _rewrite_on_disk(store: Path, issue: int, change) -> None:
    """Stand in for another process: change the record on disk after orchestrate loaded it."""
    path = store / f"issue-{issue}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestKeysOrchestrateDoesNotOwn:
    """Issue #113: a load and save keeps every unit-row and top-level key orchestrate does not own,
    including one another writer put on disk between orchestrate's load and its save."""

    def test_build_loop_and_usage_survive_a_load_and_save(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store,
            20,
            units=[unit_row("u1", build_loop=BUILD_LOOP, usage=USAGE)],
            branch="issue/20",
        )
        r = orch.Run.load(20, store)
        unit = r.unit("u1")
        assert not hasattr(unit, "build_loop")
        assert not hasattr(unit, "usage")
        r.save()
        row = read_record(store, 20)["units"][0]
        assert row["build_loop"] == BUILD_LOOP
        assert row["usage"] == USAGE

    def test_a_usage_entry_written_between_load_and_save_survives(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 21, units=[unit_row("u1"), unit_row("u2")], branch="issue/21")
        r = orch.Run.load(21, store)

        def add_usage(payload: dict) -> None:
            payload["units"][1]["usage"] = USAGE

        _rewrite_on_disk(store, 21, add_usage)
        r.unit("u1").status = "running"
        r.save()
        rows = {row["name"]: row for row in read_record(store, 21)["units"]}
        assert rows["u2"]["usage"] == USAGE
        assert "usage" not in rows["u1"]
        assert rows["u1"]["status"] == "running"

    def test_a_key_added_after_an_earlier_save_survives_the_next_save(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A long ``wait`` saves many times from one load; each save re-reads the disk."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 22, units=[unit_row("u1")], branch="issue/22")
        r = orch.Run.load(22, store)
        r.save()

        def add_build_loop(payload: dict) -> None:
            payload["units"][0]["build_loop"] = BUILD_LOOP

        _rewrite_on_disk(store, 22, add_build_loop)
        r.save()
        assert read_record(store, 22)["units"][0]["build_loop"] == BUILD_LOOP

    def test_an_unknown_top_level_key_written_after_load_survives(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store,
            23,
            units=[unit_row("u1")],
            branch="issue/23",
            extra_top_level={"loaded_with": 1},
        )
        r = orch.Run.load(23, store)

        def add_top_level(payload: dict) -> None:
            payload["written_later"] = {"by": "another process"}
            payload["roster"] = [{"name": "worker-1", "state": "open"}]

        _rewrite_on_disk(store, 23, add_top_level)
        r.save()
        after = read_record(store, 23)
        assert after["loaded_with"] == 1
        assert after["written_later"] == {"by": "another process"}
        assert after["roster"] == [{"name": "worker-1", "state": "open"}]

    def test_orchestrates_own_keys_take_the_in_memory_value(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 24, units=[unit_row("u1", usage=USAGE)], branch="issue/24")
        r = orch.Run.load(24, store)

        def change_owned_keys(payload: dict) -> None:
            payload["units"][0]["status"] = "failed"
            payload["units"][0]["merge_state"] = "merging"
            payload["orchestrate"]["branch"] = "someone-else"

        _rewrite_on_disk(store, 24, change_owned_keys)
        r.unit("u1").status = "done"
        r.save()
        after = read_record(store, 24)
        row = after["units"][0]
        assert row["status"] == "done"
        assert row["merge_state"] == "ready"
        assert row["usage"] == USAGE
        assert after["orchestrate"]["branch"] == "issue/24"

    def test_start_writes_fresh_rows_that_carry_nothing_from_a_same_named_row(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``start`` replacing the planned units is unchanged: a row it creates starts clean."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
        monkeypatch.setattr(orch, "assert_vendors_available", lambda units: None)
        monkeypatch.setattr(orch, "assert_saga_reachable", lambda units: None)
        monkeypatch.setattr(orch, "parent_branch_name", lambda issue, **kw: (f"issue/{issue}", "t"))
        write_record(
            store, 25, units=[unit_row("u1", usage=USAGE, build_loop=BUILD_LOOP)], branch="old"
        )
        plan = tmp_path / "plan-25.json"
        plan.write_text(
            json.dumps(
                {"run_id": "25", "units": [{"name": "u1", "vendor": "claude", "task": "new work"}]}
            )
        )
        code = orch.cmd_start(args(25, store, plan=str(plan), base=None, branch=None))
        assert code == 0
        row = read_record(store, 25)["units"][0]
        assert row["name"] == "u1"
        assert row["task"] == "new work"
        assert "usage" not in row
        assert "build_loop" not in row

    def test_a_unit_created_in_this_process_keeps_a_key_added_after_its_first_save(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A replacement worker ``wait`` appends is saved, then another writer adds to its row."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 27, units=[unit_row("u1")], branch="issue/27")
        r = orch.Run.load(27, store)
        r.units.append(orch.Unit(name="u1-r1", vendor="claude", task="replacement"))
        assert "u1-r1" not in r.unit_passthrough
        r.save()

        def add_usage(payload: dict) -> None:
            payload["units"][1]["usage"] = USAGE

        _rewrite_on_disk(store, 27, add_usage)
        r.unit("u1-r1").status = "running"
        r.save()
        rows = {row["name"]: row for row in read_record(store, 27)["units"]}
        assert rows["u1-r1"]["usage"] == USAGE
        assert rows["u1-r1"]["status"] == "running"

    def test_a_loaded_row_gone_from_disk_is_written_back_with_its_loaded_keys(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store, 28, units=[unit_row("u1", build_loop=BUILD_LOOP), unit_row("u2")], branch="b"
        )
        r = orch.Run.load(28, store)

        def drop_u1(payload: dict) -> None:
            payload["units"] = [row for row in payload["units"] if row["name"] != "u1"]

        _rewrite_on_disk(store, 28, drop_u1)
        r.save()
        rows = {row["name"]: row for row in read_record(store, 28)["units"]}
        assert rows["u1"]["build_loop"] == BUILD_LOOP

    def test_a_record_gone_from_disk_is_written_back_from_the_loaded_copy(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        path = write_record(
            store,
            29,
            units=[unit_row("u1", usage=USAGE)],
            branch="issue/29",
            extra_top_level={"loaded_with": 1},
        )
        r = orch.Run.load(29, store)
        path.unlink()
        r.save()
        after = read_record(store, 29)
        assert after["units"][0]["usage"] == USAGE
        assert after["loaded_with"] == 1
        assert after["orchestrate"]["branch"] == "issue/29"

    def test_save_waits_for_the_shared_record_lock(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Another holder of ``<record>.lock`` makes the save wait, then the save sees its write."""
        import fcntl
        import os
        import threading

        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        path = write_record(store, 26, units=[unit_row("u1")], branch="issue/26")
        r = orch.Run.load(26, store)
        r.unit("u1").status = "running"
        lock_file = path.with_name(path.name + ".lock")
        errors: list[Exception] = []

        def save() -> None:
            try:
                r.save()
            except Exception as exc:  # noqa: BLE001 -- any failure is asserted below
                errors.append(exc)

        def add_usage(payload: dict) -> None:
            payload["units"][0]["usage"] = USAGE

        saver = threading.Thread(target=save, daemon=True)
        fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            saver.start()
            saver.join(timeout=0.5)
            assert saver.is_alive(), "save must wait while another writer holds the record lock"
            _rewrite_on_disk(store, 26, add_usage)
        finally:
            os.close(fd)
        saver.join(timeout=10)
        assert not saver.is_alive()
        assert errors == []
        row = read_record(store, 26)["units"][0]
        assert row["status"] == "running", "the save wrote after the lock was released"
        assert row["usage"] == USAGE, "the save re-read the record under the lock"
        assert lock_file.is_file(), "the lock file is never deleted"

    def test_save_takes_sagas_own_record_lock_when_saga_provides_one(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One definition of the lock file: saga's ``record_lock`` (issue 95) wins when present."""
        import contextlib

        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 30, units=[unit_row("u1")], branch="issue/30")
        r = orch.Run.load(30, store)
        module = orch._run_record_module()
        taken: list[tuple[Path, int]] = []

        @contextlib.contextmanager
        def saga_record_lock(store_root: Path, issue: int):
            taken.append((Path(store_root), issue))
            yield store_root

        monkeypatch.setattr(module, "record_lock", saga_record_lock, raising=False)
        r.save()
        assert taken == [(store, 30)]

    def test_documented_foreign_row_keys_load_without_a_notice(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(
            store,
            31,
            units=[unit_row("u1", build_loop=BUILD_LOOP, usage=USAGE, vibrance="high")],
            branch="issue/31",
        )
        orch.Run.load(31, store)
        err = capsys.readouterr().err
        assert "'build_loop'" not in err
        assert "'usage'" not in err
        assert "'vibrance'" in err, "an undocumented key still gets its notice"

    def test_sagas_plan_tier_judgment_survives_an_orchestrate_load_and_save(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Issue #96: ``/plan`` runs ``tier_judgment.py plan`` against a record orchestrate drives.

        The judgment must neither add a row orchestrate cannot load (one holding only ``id``) nor
        be lost by orchestrate's save, which writes back only the rows its run holds.
        """
        saga_scripts = Path(__file__).resolve().parents[3] / "plugins" / "saga" / "scripts"
        if not (saga_scripts / "tier_judgment.py").is_file():
            pytest.skip("saga's tier judgment is not beside this package")
        # tier_judgment.py puts saga's scripts on sys.path; keep that out of the other tests.
        monkeypatch.setattr(sys, "path", list(sys.path))
        tj = load_orchestrate("_tier_judgment_for_orchestrate", saga_scripts / "tier_judgment.py")
        staffing = tj.load_staffing()
        if staffing is None:
            pytest.skip("saga's bundled staffing component is not reachable")

        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        write_record(store, 34, units=[unit_row("u1")], branch="issue/34")

        def ask(_state: Any, questions: Any, **_options: Any) -> Any:
            answers = {
                key: {"type": "choice", "choice": "above", "confidence": 0.9} for key in questions
            }
            return SimpleNamespace(status="ok", answers=answers, model="jev-test", note="")

        result = tj.run_plan(
            34,
            "o/r",
            store_root=store,
            units=[{"id": "U1", "goal": "rotate the signing key", "files": ["a.py"]}],
            title="Rotate the key",
            body="Touches IAM.",
            staffing=staffing,
            root=repo,
            ask=ask,
            getenv=lambda _name: None,
        )
        assert result["status"] == "ok"
        assert [row["name"] for row in read_record(store, 34)["units"]] == ["u1"]

        r = orch.Run.load(34, store)
        assert [unit.name for unit in r.units] == ["u1"]
        r.save()

        on_disk = read_record(store, 34)
        assert [row["name"] for row in on_disk["units"]] == ["u1"]
        entry = on_disk["tier_judgments"]["U1"]
        assert entry["tier_judgment"]["band"] == "auto-raise"
        assert (entry["jev_raise"]["model"], entry["jev_raise"]["effort"]) == ("opus", "high")

    def test_a_save_refuses_a_record_that_became_unreadable_after_load(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The re-read under the lock refuses rather than clobbering a record it cannot read."""
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        path = write_record(store, 32, units=[unit_row("u1")], branch="issue/32")
        r = orch.Run.load(32, store)
        path.write_text("{ this is not json", encoding="utf-8")
        before = path.read_bytes()
        r.unit("u1").status = "running"
        with pytest.raises(orch.RecordError):
            r.save()
        assert path.read_bytes() == before, "a refused save leaves the record untouched"

    def test_a_save_refuses_a_record_moved_to_an_unknown_version_after_load(
        self, orch, tmp_path: Path, store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path)
        monkeypatch.chdir(repo)
        path = write_record(store, 33, units=[unit_row("u1")], branch="issue/33")
        r = orch.Run.load(33, store)

        def bump_schema(payload: dict) -> None:
            payload["schema"] = "run_record.v2"

        _rewrite_on_disk(store, 33, bump_schema)
        before = path.read_bytes()
        r.unit("u1").status = "running"
        with pytest.raises(orch.UnknownRecordVersionError):
            r.save()
        assert path.read_bytes() == before, "a refused save leaves the record untouched"


RUN_RECORD_REFERENCE = (
    Path(__file__).resolve().parents[3] / "plugins" / "saga" / "references" / "run-record.md"
)

_UNIT_ROW_KEY_BLOCK = re.compile(
    r"<!-- BEGIN UNIT ROW KEYS -->\n(.*?)<!-- END UNIT ROW KEYS -->", re.DOTALL
)


def _documented_row_keys(text: str | None = None) -> set[str]:
    """Every key the run-record contract lists as sitting directly on a unit row.

    Only the tables between ``<!-- BEGIN UNIT ROW KEYS -->`` and ``<!-- END UNIT ROW KEYS -->``
    count. The units section also holds tables of keys nested inside a row's block (a ``usage``
    entry's fields, the token categories), and those are not row keys.
    """
    if text is None:
        text = RUN_RECORD_REFERENCE.read_text(encoding="utf-8")
    keys: set[str] = set()
    for block in _UNIT_ROW_KEY_BLOCK.findall(text):
        keys.update(re.findall(r"^\| `([a-z_]+)` \|", block, re.MULTILINE))
    return keys


def test_only_marked_unit_row_key_tables_count_as_row_keys() -> None:
    """A field table of a nested block, even one headed ``| Key | Holds |``, is not a row key."""
    text = (
        "<!-- BEGIN UNIT ROW KEYS -->\n\n| Key | Holds |\n|---|---|\n| `usage` | the block |\n\n"
        "<!-- END UNIT ROW KEYS -->\n\n| Key | Holds |\n|---|---|\n| `session_id` | an entry field |\n"
    )
    assert _documented_row_keys(text) == {"usage"}


def test_the_contract_marks_no_usage_entry_field_as_a_row_key() -> None:
    documented = _documented_row_keys()
    assert {"build_loop", "usage", "merge_state"} <= documented
    assert not documented & {"session_id", "counts", "additions", "uncached_input", "output"}


def test_documented_foreign_row_keys_match_the_run_record_contract(orch) -> None:
    """The contract is the source of the quiet list: a documented row key orchestrate does not own
    must be in ``DOCUMENTED_FOREIGN_ROW_KEYS``, and nothing else may be (issue #113)."""
    import dataclasses

    owned = {field.name for field in dataclasses.fields(orch.Unit)}
    documented = _documented_row_keys()
    assert documented, "the run-record contract's marked unit-row key tables were not found"
    foreign = documented - owned
    assert foreign == orch.DOCUMENTED_FOREIGN_ROW_KEYS, (
        f"run-record.md's marked unit-row keys orchestrate does not own {sorted(foreign)} differ "
        f"from DOCUMENTED_FOREIGN_ROW_KEYS {sorted(orch.DOCUMENTED_FOREIGN_ROW_KEYS)}"
    )


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
