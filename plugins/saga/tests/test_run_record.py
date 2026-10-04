"""Tests for the saga run record (issue #1023, plan U1, U2 and U4).

Every test that touches a store passes an explicit ``tmp_path`` store root. Nothing here may
create or modify anything under the primary checkout's ``.claude/saga/`` store — several card
drivers share this machine and that store is live state (plan R13, KTD9).
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "run-record.md"
PROFILE_REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "repository-profile.md"
SDLC_SCHEMA = REPO_ROOT / "plugins" / "mission-control" / "config" / "sdlc-schema.json"
LIFECYCLE_SNAPSHOT = REPO_ROOT / "plugins" / "agent-launcher" / "roles" / "lifecycle-snapshot.json"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rr() -> ModuleType:
    return _load("run_record")


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A throwaway store root. Never the primary checkout's (plan R13)."""
    root = tmp_path / "store" / "runs"
    root.mkdir(parents=True)
    return root


def _full_record(rr: ModuleType):
    """A record with every one of the twelve top-level keys populated."""
    run_configuration = rr.empty_run_configuration()
    for index, name in enumerate(rr.RUN_CONFIGURATION_PARAMETERS):
        run_configuration[name]["value"] = f"value-{index}"
        run_configuration[name]["source"] = "profile"
    approval_scope = dict.fromkeys(rr.APPROVAL_CATEGORIES, "none")
    admission = rr.empty_admission()
    admission["risk_tier"] = "medium"
    admission["risk_justification"] = "every other child reads this record"
    admission["destination"] = "pr"
    admission["branch_preview"] = False
    admission["main_consumed_directly"] = False
    admission["change_shape"] = "code"
    return rr.RunRecord(
        issue=1023,
        repo="infiquetra/infiquetra-claude-plugins",
        admission=admission,
        run_configuration=run_configuration,
        approval_scope=approval_scope,
        roster=[{"role": "planner", "pane": "wCA:p1", "state": "idle"}],
        units=[
            {
                "unit": "U1",
                "worktree": "/tmp/wt",
                "branch": "issue/1023",
                "merge_turn": "waiting",
                "mechanical_checks": "green",
            }
        ],
        review_cycles=[{"cycle": 1, "result": "accepted", "findings_ref": "none"}],
        next_step="U2 the schema reference",
    )


# ---------------------------------------------------------------------------
# The version token and its refusal (plan R3, KTD2)
# ---------------------------------------------------------------------------


def test_schema_token_is_run_record_v1(rr: ModuleType) -> None:
    assert rr.SCHEMA == "run_record.v1"


def test_unknown_record_version_raises_the_named_error_through_the_api(
    rr: ModuleType, store: Path
) -> None:
    path = rr.record_path(store, 1023)
    path.write_text(json.dumps({"schema": "run_record.v2", "issue": 1023}), encoding="utf-8")
    with pytest.raises(rr.UnknownRecordVersionError) as excinfo:
        rr.load(store, 1023)
    assert "run_record.v2" in str(excinfo.value)


def test_unknown_record_version_exits_3_with_exactly_one_line_and_no_stdout(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = rr.record_path(store, 1023)
    path.write_text(json.dumps({"schema": "run_record.v2", "issue": 1023}), encoding="utf-8")
    exit_code = rr.main(["--store-root", str(store), "show", "1023"])
    captured = capsys.readouterr()
    assert exit_code == 3
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err
    assert captured.err.startswith("run_record: unknown record version 'run_record.v2'")
    assert captured.err.rstrip().endswith("this saga writes run_record.v1")


def test_a_valid_record_shows_next_step_and_exits_0(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rr.save(store, _full_record(rr))
    exit_code = rr.main(["--store-root", str(store), "show", "1023"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["next_step"] == "U2 the schema reference"


# ---------------------------------------------------------------------------
# Unknown top-level fields (plan R4, KTD3)
# ---------------------------------------------------------------------------


def test_unknown_top_level_field_survives_a_read_and_write_round_trip(
    rr: ModuleType, store: Path
) -> None:
    rr.save(store, _full_record(rr))
    path = rr.record_path(store, 1023)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["a_field_a_newer_writer_added"] = {"kept": True}
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    rr.save(store, rr.load(store, 1023, warn=None))

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["a_field_a_newer_writer_added"] == {"kept": True}


def test_unknown_top_level_field_is_warned_about_by_name(rr: ModuleType, store: Path) -> None:
    path = rr.record_path(store, 1023)
    path.write_text(
        json.dumps({"schema": rr.SCHEMA, "issue": 1023, "a_newer_field": 1}), encoding="utf-8"
    )
    warnings: list[str] = []
    rr.load(store, 1023, warn=warnings.append)
    assert len(warnings) == 1
    assert "'a_newer_field'" in warnings[0]
    assert str(path) in warnings[0]
    assert rr.SCHEMA in warnings[0]


def test_a_missing_known_key_reads_back_as_its_empty_default(rr: ModuleType, store: Path) -> None:
    path = rr.record_path(store, 1023)
    path.write_text(json.dumps({"schema": rr.SCHEMA, "issue": 1023}), encoding="utf-8")
    record = rr.load(store, 1023, warn=None)
    assert record.next_step == ""
    assert list(record.run_configuration) == list(rr.RUN_CONFIGURATION_PARAMETERS)
    assert list(record.approval_scope) == list(rr.APPROVAL_CATEGORIES)


# ---------------------------------------------------------------------------
# The key set and the two sets of thirteen (plan KTD4, KTD4a)
# ---------------------------------------------------------------------------


def test_top_level_key_set_is_exactly_the_twelve(rr: ModuleType, store: Path) -> None:
    rr.save(store, _full_record(rr))
    written = list(json.loads(rr.record_path(store, 1023).read_text(encoding="utf-8")))
    assert written == list(rr.TOP_LEVEL_KEYS), (
        f"top-level keys drifted: written={written} declared={list(rr.TOP_LEVEL_KEYS)}"
    )
    assert len(rr.TOP_LEVEL_KEYS) == 12


def test_run_configuration_holds_the_run_model_thirteen_not_the_run_setup_contract_thirteen(
    rr: ModuleType,
) -> None:
    """The guard that tells the two sets of thirteen apart, by name and not by count.

    Both sets number thirteen and both live in the software-development-lifecycle repository at the
    same pinned revision, so a count check would pass on the wrong one. This asserts that no name
    belonging only to the ``orchestrator-to-controller`` run setup contract has been swapped in.
    """
    if not LIFECYCLE_SNAPSHOT.is_file():
        pytest.skip(
            "agent-launcher's lifecycle snapshot is not in this checkout; "
            "that package is imported on its own branch"
        )
    snapshot = json.loads(LIFECYCLE_SNAPSHOT.read_text(encoding="utf-8"))
    contract_fields = set(snapshot["contracts"]["orchestrator-to-controller"]["required_fields"])

    assert len(rr.RUN_CONFIGURATION_PARAMETERS) == 13
    assert len(contract_fields) == 13
    assert set(rr.RUN_CONFIGURATION_PARAMETERS) != contract_fields

    contract_only = contract_fields - set(rr.RUN_CONFIGURATION_PARAMETERS)
    assert contract_only == set(rr.RUN_SETUP_CONTRACT_ONLY_FIELDS)
    swapped_in = contract_only & set(rr.RUN_CONFIGURATION_PARAMETERS)
    assert not swapped_in, f"run setup contract field names swapped into the record: {swapped_in}"


def test_approval_scope_categories_match_the_vendored_lifecycle_schema(rr: ModuleType) -> None:
    schema = json.loads(SDLC_SCHEMA.read_text(encoding="utf-8"))
    declared = schema["human_approval_state"]["approval_required_for"]
    assert list(rr.APPROVAL_CATEGORIES) == list(declared)
    assert len(rr.APPROVAL_CATEGORIES) == 7


def test_every_parameter_names_who_chooses_it(rr: ModuleType) -> None:
    assert set(rr.PARAMETER_CHOSEN_BY) == set(rr.RUN_CONFIGURATION_PARAMETERS)
    chosen = list(rr.PARAMETER_CHOSEN_BY.values())
    assert chosen.count("delivery_manager") == 9
    assert chosen.count("planner") == 4


def test_the_two_destinations_are_separate_fields(rr: ModuleType) -> None:
    """Saga's routing intent and the lifecycle repository's lower environment are not one field."""
    assert "destination" in rr.empty_admission()
    assert "nonproduction_destination" in rr.empty_run_configuration()
    assert "destination" not in rr.empty_run_configuration()


# ---------------------------------------------------------------------------
# The store root: absolute, and the same from a worktree (plan R2, KTD1)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def test_the_resolved_record_path_is_absolute(rr: ModuleType, store: Path) -> None:
    assert rr.record_path(store, 1023).is_absolute()


def test_a_linked_worktree_resolves_the_same_absolute_store_root_as_the_primary_checkout(
    rr: ModuleType, tmp_path: Path
) -> None:
    """The card's third acceptance criterion, proved in a throwaway repository.

    Never against this repository's primary checkout: the point of the test is the resolution rule,
    and running it here would write into live state.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git("init", "-b", "main", cwd=primary)
    _git("config", "user.email", "test@example.invalid", cwd=primary)
    _git("config", "user.name", "Test", cwd=primary)
    (primary / "README.md").write_text("seed\n", encoding="utf-8")
    _git("add", "README.md", cwd=primary)
    _git("commit", "-m", "seed", cwd=primary)

    worktree = tmp_path / "linked"
    _git("worktree", "add", str(worktree), "-b", "unit", cwd=primary)

    from_primary = rr.resolve_store_root(primary)
    from_worktree = rr.resolve_store_root(worktree)

    assert from_primary == from_worktree
    assert from_primary.is_absolute()
    assert from_primary == (primary.resolve() / rr.STORE_SUBPATH)

    written = rr.save(from_primary, rr.RunRecord(issue=7, next_step="read me from the worktree"))
    assert rr.load(rr.resolve_store_root(worktree), 7).next_step == "read me from the worktree"
    assert written.is_absolute()


def test_a_common_directory_that_is_not_a_dot_git_refuses_with_one_line(
    rr: ModuleType, tmp_path: Path
) -> None:
    class _Result:
        returncode = 0
        stdout = str(tmp_path / "separate-git-dir")
        stderr = ""

    def _runner(*_args: object, **_kwargs: object) -> _Result:
        return _Result()

    with pytest.raises(rr.StoreRootError) as excinfo:
        rr.resolve_store_root(tmp_path, runner=_runner)
    assert "separate-git-dir" in str(excinfo.value)
    assert "\n" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Writing: atomic, round-trip stable (plan KTD4b)
# ---------------------------------------------------------------------------


def test_a_full_record_round_trips_byte_identically(rr: ModuleType, store: Path) -> None:
    """Content is preserved exactly. The clock is injected because ``updated_at`` moves by design."""
    from datetime import UTC, datetime

    frozen = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
    path = rr.save(store, _full_record(rr), now=frozen)
    first = path.read_bytes()
    rr.save(store, rr.load(store, 1023, warn=None), now=frozen)
    assert path.read_bytes() == first


def test_two_writes_leave_no_temporary_sibling_and_the_second_wins(
    rr: ModuleType, store: Path
) -> None:
    rr.save(store, rr.RunRecord(issue=1023, next_step="first"))
    rr.save(store, rr.RunRecord(issue=1023, next_step="second"))
    assert list(store.glob("*.tmp")) == []
    assert rr.load(store, 1023, warn=None).next_step == "second"


def test_created_at_is_kept_and_updated_at_moves(rr: ModuleType, store: Path) -> None:
    rr.save(store, rr.RunRecord(issue=1023))
    first = rr.load(store, 1023, warn=None)
    rr.save(store, rr.RunRecord(**{**first.__dict__, "next_step": "moved"}))
    second = rr.load(store, 1023, warn=None)
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


# ---------------------------------------------------------------------------
# next_step: the record wins over the envelope (plan R11, KTD8a)
# ---------------------------------------------------------------------------


def test_set_next_step_creates_the_record_when_there_is_none(rr: ModuleType, store: Path) -> None:
    rr.set_next_step(store, 1023, "U3 admission")
    assert rr.get_next_step(store, 1023) == "U3 admission"


def test_get_next_step_on_a_missing_record_is_empty_not_an_error(
    rr: ModuleType, store: Path
) -> None:
    assert rr.get_next_step(store, 4242) == ""


def test_saving_a_saga_tick_does_not_write_into_the_record_store_by_itself(
    rr: ModuleType, tmp_path: Path
) -> None:
    """The mirror is an explicit call, never a side effect of ``saga.save`` (plan KTD9, R13).

    If ``save`` mirrored automatically it would resolve the REAL store — the primary checkout's
    live `.claude/saga/runs` — from every test in the suite that saves a tick against a temporary
    root. That is a live write from a unit test, and it is why the write direction is a named
    function a caller opts into rather than something the engine does on its own.
    """
    saga = _load("saga")
    saga_root = tmp_path / "saga-root"
    saga_root.mkdir()
    live_store = rr.resolve_store_root(REPO_ROOT)
    before = sorted(p.name for p in live_store.glob("*.json")) if live_store.exists() else []

    saga.save(
        saga_root,
        saga.Saga(saga_id="issue-999999", kind="issue", id="999999", next_step="do not mirror me"),
    )

    after = sorted(p.name for p in live_store.glob("*.json")) if live_store.exists() else []
    assert after == before
    assert not (live_store / "issue-999999.json").exists()


def test_the_mirror_writes_only_when_a_caller_asks_and_names_the_store(
    rr: ModuleType, store: Path
) -> None:
    saga = _load("saga")
    tick = saga.Saga(saga_id="issue-1023", kind="issue", id="1023", next_step="mirrored")
    written = saga.mirror_next_step_to_record(tick, store_root=store)
    assert written is not None
    assert rr.get_next_step(store, 1023) == "mirrored"

    task = saga.Saga(saga_id="task-slug", kind="task", id="slug", next_step="not an issue")
    assert saga.mirror_next_step_to_record(task, store_root=store) is None


def test_the_record_is_authoritative_over_a_stale_saga_envelope_next_step(
    rr: ModuleType, store: Path, tmp_path: Path
) -> None:
    """A stale envelope tick must never move the run backwards (plan KTD8a)."""
    saga = _load("saga")
    saga_root = tmp_path / "saga-root"
    saga_root.mkdir()
    saga.save(
        saga_root,
        saga.Saga(saga_id="issue-1023", kind="issue", id="1023", next_step="stale"),
    )
    rr.set_next_step(store, 1023, "current")

    restored = saga.restore(saga_root, "issue-1023")
    assert restored.next_step == "stale"
    assert rr.get_next_step(store, 1023) == "current"
    assert saga.authoritative_next_step(saga_root, "issue-1023", store_root=store) == "current"


# ---------------------------------------------------------------------------
# U4: the record survives the compaction boundary (plan R12)
# ---------------------------------------------------------------------------


def test_the_frozen_spore_carries_the_records_next_step(rr: ModuleType, store: Path) -> None:
    spore = _load("saga_spore")
    rr.set_next_step(store, 1023, "U5 the plan skill")

    class _Stub:
        SCHEMA = rr.SCHEMA

        @staticmethod
        def resolve_store_root(_root: Path) -> Path:
            return store

        load = staticmethod(rr.load)
        record_path = staticmethod(rr.record_path)

    sys.modules["run_record"] = _Stub  # type: ignore[assignment]
    try:
        frozen = spore.freeze_run_record(Path("/anywhere"), {"saga_id": "issue-1023"})
    finally:
        sys.modules["run_record"] = rr
    assert frozen is not None
    assert frozen["next_step"] == "U5 the plan skill"
    assert Path(frozen["path"]).is_absolute()


def test_next_step_is_identical_on_both_sides_of_the_compaction_boundary(
    rr: ModuleType, store: Path
) -> None:
    """Freeze, render, and read the value back out of the injected block (plan R12)."""
    spore = _load("saga_spore")
    rr.set_next_step(store, 1023, "U6 release surfaces")
    frozen = {
        "path": str(rr.record_path(store, 1023)),
        "issue": 1023,
        "next_step": rr.get_next_step(store, 1023),
        "destination": "pr",
        "pending_questions": [],
        "units": 0,
        "review_cycles": 0,
    }
    rendered = spore.serialize(
        {
            "provenance": {"generated_at": "2026-09-19T00:00:00Z", "saga_id": "issue-1023"},
            "saga_box": None,
            "dag": None,
            "pointers": {},
            "run_record": frozen,
        }
    )
    assert "RUN RECORD (authoritative on next_step)" in rendered
    assert "next_step: U6 release surfaces" in rendered
    assert rr.get_next_step(store, 1023) == "U6 release surfaces"


def test_freezing_without_an_active_issue_saga_yields_nothing_rather_than_failing(
    rr: ModuleType,
) -> None:
    """A spore must never fail a compaction boundary (plan R12)."""
    spore = _load("saga_spore")
    assert spore.freeze_run_record(Path("/anywhere"), None) is None
    assert spore.freeze_run_record(Path("/anywhere"), {"saga_id": "task-some-slug"}) is None
    assert spore.freeze_run_record(Path("/nonexistent"), {"saga_id": "issue-1023"}) is None


def test_a_spore_without_a_run_record_renders_without_the_block(rr: ModuleType) -> None:
    spore = _load("saga_spore")
    rendered = spore.serialize(
        {
            "provenance": {"generated_at": "2026-09-19T00:00:00Z", "saga_id": None},
            "saga_box": None,
            "dag": None,
            "pointers": {},
            "run_record": None,
        }
    )
    assert "RUN RECORD" not in rendered


# ---------------------------------------------------------------------------
# U2: the reference document and the code agree
# ---------------------------------------------------------------------------


def test_the_run_record_reference_document_exists(rr: ModuleType) -> None:
    assert REFERENCE.is_file()
    assert PROFILE_REFERENCE.is_file()


def test_reference_document_names_exactly_the_twelve_top_level_keys(rr: ModuleType) -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    block = text.split("<!-- BEGIN TOP-LEVEL KEYS -->")[1].split("<!-- END TOP-LEVEL KEYS -->")[0]
    documented = re.findall(r"^\| `([a-z_]+)` \|", block, flags=re.MULTILINE)
    assert documented == list(rr.TOP_LEVEL_KEYS), (
        f"run-record.md and run_record.py disagree: documented={documented} "
        f"code={list(rr.TOP_LEVEL_KEYS)}"
    )


def test_reference_document_names_exactly_the_thirteen_parameters(rr: ModuleType) -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    block = text.split("<!-- BEGIN PARAMETERS -->")[1].split("<!-- END PARAMETERS -->")[0]
    documented = re.findall(r"^\| \d+ \| `([a-z_]+)` \|", block, flags=re.MULTILINE)
    assert documented == list(rr.RUN_CONFIGURATION_PARAMETERS), (
        f"run-record.md and run_record.py disagree on the thirteen parameters: "
        f"documented={documented} code={list(rr.RUN_CONFIGURATION_PARAMETERS)}"
    )


def test_reference_document_carries_the_version_token_the_code_writes(rr: ModuleType) -> None:
    assert rr.SCHEMA in REFERENCE.read_text(encoding="utf-8")


def test_reference_document_quotes_the_refusal_line_the_code_prints(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = rr.record_path(store, 1023)
    path.write_text(json.dumps({"schema": "run_record.v2", "issue": 1023}), encoding="utf-8")
    rr.main(["--store-root", str(store), "show", "1023"])
    printed = capsys.readouterr().err.strip()

    text = REFERENCE.read_text(encoding="utf-8")
    prefix = "run_record: unknown record version 'run_record.v2' in "
    suffix = "; this saga writes run_record.v1"
    assert printed.startswith(prefix) and printed.endswith(suffix)
    assert prefix in text, "run-record.md does not quote the refusal the code prints"
    assert suffix in text, "run-record.md does not quote the refusal the code prints"


def test_reference_document_states_the_exit_codes_the_code_uses(rr: ModuleType) -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    for line in ("exit 0", "exit 2", "exit 3"):
        assert line in text, f"run-record.md does not state {line}"


# ---------------------------------------------------------------------------
# Issue 95: the usage block, usage add, and the read-modify-write lock
# ---------------------------------------------------------------------------

USAGE_SCRIPT = SCRIPTS / "run_record.py"


def _units_record(rr: ModuleType):
    """A record with two unit rows carrying other consumers' keys, and an unknown top-level key."""
    return rr.RunRecord(
        issue=95,
        units=[
            {
                "id": "u1",
                "branch": "issue/95-u1",
                "merge_state": "ready",
                "build_loop": {"iterations": [{"iteration": 1, "green": True}]},
                "a_future_key": {"kept": True},
            },
            {"name": "u2", "merge_state": "merged"},
        ],
        extra={"orchestrate": {"run_branch": "orch/95"}},
    )


def _add(rr: ModuleType, record, unit: str = "u1", **overrides):
    arguments = {
        "session_id": "s-1",
        "role": "worker",
        "vendor": "claude",
        "model": "claude-opus-5-5",
        "effort": "medium",
        "counts": {"cache_read": 98000, "output": 4000},
    }
    arguments.update(overrides)
    return rr.add_usage(record, unit, **arguments)


def _usage_argv(store: Path, *extra: str, session: str = "s-1") -> list[str]:
    return [
        "--store-root",
        str(store),
        "usage",
        "add",
        "95",
        "--unit",
        "u1",
        "--session-id",
        session,
        "--role",
        "worker",
        "--vendor",
        "claude",
        "--model",
        "claude-opus-5-5",
        "--effort",
        "medium",
        *extra,
    ]


def test_usage_add_appends_one_entry_with_all_five_categories(rr: ModuleType, store: Path) -> None:
    rr.save(store, _units_record(rr))
    before = rr.load(store, 95, warn=None)
    assert rr.main(_usage_argv(store, "--cache-read", "98000", "--output", "4000")) == 0

    after = rr.load(store, 95, warn=None)
    entries = after.units[0]["usage"]["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert tuple(entry) == rr.USAGE_ENTRY_KEYS
    assert entry["counts"] == {
        "uncached_input": 0,
        "cache_read": 98000,
        "cache_write_5m": 0,
        "cache_write_1h": 0,
        "output": 4000,
    }
    assert entry["additions"] == 1
    assert entry["first_added_at"] == entry["last_added_at"]
    assert after.updated_at >= before.updated_at
    assert list(store.glob("*.tmp")) == []


def test_a_repeat_add_accumulates_and_a_new_session_appends(rr: ModuleType) -> None:
    from datetime import UTC, datetime

    first = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    later = datetime(2026, 10, 3, 13, 0, tzinfo=UTC)
    record = _add(rr, _units_record(rr), now=first)
    record = _add(rr, record, counts={"uncached_input": 10, "output": 6}, now=later)
    entries = record.units[0]["usage"]["entries"]
    assert len(entries) == 1
    assert entries[0]["additions"] == 2
    assert entries[0]["counts"]["output"] == 4006
    assert entries[0]["counts"]["uncached_input"] == 10
    assert entries[0]["first_added_at"] == first.isoformat()
    assert entries[0]["last_added_at"] == later.isoformat()

    record = _add(rr, record, session_id="s-2")
    assert [e["session_id"] for e in record.units[0]["usage"]["entries"]] == ["s-1", "s-2"]
    record = _add(rr, record, role="lens-reviewer", effort="high")
    assert len(record.units[0]["usage"]["entries"]) == 3


def test_usage_add_preserves_every_other_consumers_keys(rr: ModuleType, store: Path) -> None:
    original = _units_record(rr)
    original.units[0]["usage"] = {"entries": [], "a_usage_extension": [1, 2]}
    rr.save(store, original)
    path = rr.record_path(store, 95)
    before = json.loads(path.read_text(encoding="utf-8"))

    assert rr.main(_usage_argv(store, "--output", "1")) == 0
    after = json.loads(path.read_text(encoding="utf-8"))

    row_before, row_after = before["units"][0], after["units"][0]
    for key in ("branch", "merge_state", "build_loop", "a_future_key"):
        assert row_after[key] == row_before[key]
    assert row_after["usage"]["a_usage_extension"] == [1, 2]
    assert after["units"][1] == before["units"][1]
    assert after["orchestrate"] == before["orchestrate"]


def test_add_usage_does_not_mutate_the_record_it_was_given(rr: ModuleType) -> None:
    record = _units_record(rr)
    _add(rr, record)
    assert "usage" not in record.units[0]


def test_an_unknown_token_category_is_refused_through_the_api(rr: ModuleType) -> None:
    with pytest.raises(rr.RunRecordError) as excinfo:
        _add(rr, _units_record(rr), counts={"cache_write_2h": 5})
    message = str(excinfo.value)
    assert "cache_write_2h" in message
    for category in rr.TOKEN_CATEGORIES:
        assert category in message


def test_an_unknown_token_category_flag_is_refused_on_the_command_line(
    rr: ModuleType, store: Path
) -> None:
    rr.save(store, _units_record(rr))
    with pytest.raises(SystemExit) as excinfo:
        rr.main(_usage_argv(store, "--cache-write-2h", "5"))
    assert excinfo.value.code == 2
    assert "usage" not in rr.load(store, 95, warn=None).units[0]


@pytest.mark.parametrize(
    "overrides",
    [
        {"counts": {"output": -1}},
        {"counts": {"output": 1.5}},
        {"session_id": ""},
        {"model": "  "},
        {"role": "Worker"},
        {"role": "lens reviewer"},
        {"role": "worker\n"},
        {"model": "evil\n  forged line"},
        {"model": "claude-opus-5-5\n"},
        {"model": "\x1b[2Kclaude"},
        {"vendor": "claude anthropic"},
        {"effort": "medium\tx"},
        {"session_id": "s 1"},
        {"session_id": "s-1\n"},
    ],
)
def test_bad_usage_values_are_refused(rr: ModuleType, overrides: dict) -> None:
    with pytest.raises(rr.RunRecordError):
        _add(rr, _units_record(rr), **overrides)


def test_a_negative_count_is_refused_on_the_command_line(rr: ModuleType, store: Path) -> None:
    rr.save(store, _units_record(rr))
    with pytest.raises(SystemExit) as excinfo:
        rr.main(_usage_argv(store, "--output", "-3"))
    assert excinfo.value.code == 2


def test_a_unit_the_record_does_not_have_is_refused_naming_the_known_units(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rr.save(store, _units_record(rr))
    argv = _usage_argv(store)
    argv[argv.index("u1")] = "u9"
    assert rr.main(argv) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert "'u9'" in err and "u1, u2" in err
    assert all("usage" not in row for row in rr.load(store, 95, warn=None).units)


def test_usage_add_with_no_record_exits_2_with_one_line(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rr.main(_usage_argv(store, "--output", "1")) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert err.startswith("run_record: no record for issue 95")
    assert not rr.record_path(store, 95).exists()


def test_usage_add_on_an_unknown_record_version_exits_3_with_one_line(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = rr.record_path(store, 95)
    path.write_text(json.dumps({"schema": "run_record.v2", "issue": 95}), encoding="utf-8")
    assert rr.main(_usage_argv(store, "--output", "1")) == 3
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "Traceback" not in err


def test_usage_add_help_documents_the_five_categories() -> None:
    result = subprocess.run(
        [sys.executable, str(USAGE_SCRIPT), "usage", "add", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for flag in (
        "--uncached-input",
        "--cache-read",
        "--cache-write-5m",
        "--cache-write-1h",
        "--output",
    ):
        assert flag in result.stdout
    for category in ("uncached_input", "cache_read", "cache_write_5m", "cache_write_1h", "output"):
        assert category in result.stdout


def test_usage_add_runs_as_a_user_runs_it(rr: ModuleType, store: Path) -> None:
    """The real script, a real subprocess, an explicit store root (the AGENTS.md rule)."""
    rr.save(store, _units_record(rr))
    result = subprocess.run(
        [sys.executable, str(USAGE_SCRIPT), *_usage_argv(store, "--cache-write-1h", "7")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    entry = rr.load(store, 95, warn=None).units[0]["usage"]["entries"][0]
    assert entry["counts"]["cache_write_1h"] == 7


def _marked_table(name: str) -> list[str]:
    text = REFERENCE.read_text(encoding="utf-8")
    block = text.split(f"<!-- BEGIN {name} -->")[1].split(f"<!-- END {name} -->")[0]
    return re.findall(r"^\| `([a-z0-9_]+)` \|", block, flags=re.MULTILINE)


def test_reference_documents_the_flag_and_api_field_of_each_category(rr: ModuleType) -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    block = text.split("<!-- BEGIN TOKEN CATEGORIES -->")[1].split("<!-- END TOKEN CATEGORIES")[0]
    rows = re.findall(r"^\| `([a-z0-9_]+)` \| `([^`]+)` \| `([^`]+)` \|", block, flags=re.MULTILINE)
    assert tuple(rows) == rr.USAGE_FLAGS
    assert rr.TOKEN_CATEGORIES == tuple(category for category, _, _ in rr.USAGE_FLAGS)


def test_a_unit_is_named_by_its_name_only_when_the_row_has_no_id(
    rr: ModuleType, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = rr.RunRecord(issue=95, units=[{"id": "u1", "name": "first"}, {"name": "u2"}])
    rr.save(store, record)
    argv = _usage_argv(store, "--output", "1")
    assert rr.main([*argv[:6], "first", *argv[7:]]) == 2
    assert "no unit 'first'" in capsys.readouterr().err
    assert rr.main([*argv[:6], "u2", *argv[7:]]) == 0


def test_a_stored_count_that_is_not_an_integer_refuses_with_one_line(
    rr: ModuleType, store: Path
) -> None:
    record = _add(rr, _units_record(rr))
    record.units[0]["usage"]["entries"][0]["counts"]["output"] = "lots"
    rr.save(store, record)
    result = subprocess.run(
        [sys.executable, str(USAGE_SCRIPT), *_usage_argv(store, "--output", "1")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert result.stderr.count("\n") == 1 and "Traceback" not in result.stderr
    assert "'lots'" in result.stderr


@pytest.mark.parametrize(
    ("usage", "message"),
    [
        ([], "that is not an object"),
        ({"entries": {}}, "that is not a list"),
    ],
)
def test_a_malformed_usage_block_is_refused(rr: ModuleType, usage: object, message: str) -> None:
    record = _units_record(rr)
    record.units[0]["usage"] = usage
    with pytest.raises(rr.RunRecordError, match=message):
        _add(rr, record)


def test_update_refuses_a_change_that_returns_another_issues_record(
    rr: ModuleType, store: Path
) -> None:
    rr.save(store, _units_record(rr))
    with pytest.raises(rr.RunRecordError, match="refusing to write a record other than"):
        rr.update(store, 95, lambda current: rr.RunRecord(**{**current.__dict__, "issue": 7}))
    assert not rr.record_path(store, 7).exists()


def test_save_uses_a_unique_temporary_file_per_write(
    rr: ModuleType, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fixed ``<record>.tmp`` let two writers move each other's half-written file."""
    import os

    names: list[str] = []
    real_replace = os.replace

    def spy(src, dst):
        names.append(str(src))
        return real_replace(src, dst)

    monkeypatch.setattr(rr.os, "replace", spy)
    rr.save(store, rr.RunRecord(issue=95))
    rr.save(store, rr.RunRecord(issue=95))
    assert len(set(names)) == 2
    assert all(Path(name).parent == store and name.endswith(".tmp") for name in names)
    assert not any(name.endswith("issue-95.json.tmp") for name in names)


def test_reference_documents_exactly_the_usage_entry_keys_written(rr: ModuleType) -> None:
    entry = _add(rr, _units_record(rr)).units[0]["usage"]["entries"][0]
    assert _marked_table("USAGE ENTRY KEYS") == list(entry) == list(rr.USAGE_ENTRY_KEYS)


def test_reference_documents_exactly_the_token_categories(rr: ModuleType) -> None:
    assert _marked_table("TOKEN CATEGORIES") == list(rr.TOKEN_CATEGORIES)


def test_reference_documents_the_lock_convention(rr: ModuleType) -> None:
    text = REFERENCE.read_text(encoding="utf-8")
    assert "fcntl.flock(fd, LOCK_EX)" in text
    assert "<record path>.lock" in text
    assert rr.lock_path(Path("/s"), 95).name == "issue-95.json.lock"


def test_update_reads_the_record_only_after_the_lock_is_taken(rr: ModuleType, store: Path) -> None:
    """Deterministic: a write made while ``update`` waits for the lock is what its change sees."""
    import fcntl
    import os
    import threading

    rr.save(store, _units_record(rr))
    rr.lock_path(store, 95).touch()
    seen: dict = {}

    def change(current):
        seen["next_step"] = current.next_step
        return current

    fd = os.open(rr.lock_path(store, 95), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        worker = threading.Thread(target=rr.update, args=(store, 95, change))
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive(), "update must wait for the lock"
        assert seen == {}, "the change ran before the lock was free"
        rr.save(store, rr.RunRecord(**{**_units_record(rr).__dict__, "next_step": "while waiting"}))
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    worker.join(timeout=10)
    assert seen["next_step"] == "while waiting"


def test_update_holds_the_lock_and_rereads_inside_it(rr: ModuleType, store: Path) -> None:
    """A change sees the on-disk record as of lock time, and the lock is held while it runs."""
    import fcntl
    import os

    rr.save(store, _units_record(rr))
    seen: dict = {}

    def change(current):
        fd = os.open(rr.lock_path(store, 95), os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        seen["next_step"] = current.next_step
        return rr.RunRecord(**{**current.__dict__, "next_step": "after"})

    rr.set_next_step(store, 95, "written by another writer")
    rr.update(store, 95, change)
    assert seen["next_step"] == "written by another writer"
    assert rr.get_next_step(store, 95) == "after"
    assert rr.lock_path(store, 95).is_file(), "the lock file is never deleted"


def test_concurrent_usage_adds_lose_no_update(rr: ModuleType, store: Path) -> None:
    """Eight processes adding at once all land: the lock serialises the read-modify-writes."""
    rr.save(store, _units_record(rr))
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(USAGE_SCRIPT),
                *_usage_argv(store, "--output", "1", session=f"s-{n}"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(8)
    ]
    for process in processes:
        assert process.wait(timeout=60) == 0
    entries = rr.load(store, 95, warn=None).units[0]["usage"]["entries"]
    assert sorted(e["session_id"] for e in entries) == [f"s-{n}" for n in range(8)]
