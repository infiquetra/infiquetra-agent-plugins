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
# Writing: atomic, no lock, round-trip stable (plan KTD4b)
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
