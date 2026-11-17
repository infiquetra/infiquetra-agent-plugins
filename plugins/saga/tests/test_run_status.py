"""The read-only run view the saga mods and other harnesses print (issue #104).

Every case uses a temporary git repository and a temporary record store. Nothing here touches the
primary checkout's live `.claude/saga` directories.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA_SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

sys.path.insert(0, str(SAGA_SCRIPTS))

import run_record  # noqa: E402
import run_status  # noqa: E402
import saga  # noqa: E402

PLAN = "docs/plans/2026-10-04-viewer-plan.md"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on branch `issue/104` with nothing in it."""
    path = tmp_path / "repo"
    path.mkdir()
    _git("init", "-q", "-b", "issue/104", cwd=path)
    return path.resolve()


@pytest.fixture
def store(tmp_path: Path) -> Path:
    path = tmp_path / "runs"
    path.mkdir()
    return path.resolve()


def _tick(repo: Path, issue: int, **fields: str) -> None:
    saga.save(repo, saga.Saga(saga_id=f"issue-{issue}", kind="issue", id=str(issue), **fields))


def _run(
    repo: Path, store: Path, *args: str, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    code = run_status.main(["--store-root", str(store), "--repo-root", str(repo), *args])
    out, err = capsys.readouterr()
    return code, out, err


def test_summary_for_an_issue_reads_phase_and_plan_from_the_envelope(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "run /work on the plan")
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    code, out, err = _run(repo, store, "summary", "--issue", "104", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    view = json.loads(out)
    assert view["schema"] == "run_status.v1"
    assert view["repo_root"] == str(repo)
    [row] = view["runs"]
    assert row["issue"] == 104
    assert row["next_step"] == "run /work on the plan"
    assert row["phase"] == "plan"
    assert row["plan_path"] == PLAN
    assert row["plan_file"] == str(repo / PLAN)
    assert row["record_path"] == str(run_record.record_path(store, 104))


def test_summary_without_an_issue_resolves_it_from_the_branch(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "plan")
    code, out, _ = _run(repo, store, "summary", "--json", capsys=capsys)
    assert code == 0
    [row] = json.loads(out)["runs"]
    assert row["issue"] == 104
    assert (row["phase"], row["plan_path"], row["plan_file"]) == (None, None, None)


def test_an_envelope_without_a_record_still_names_the_plan(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """/plan can save a plan before admission writes a record; the viewer still finds it."""
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    code, out, _ = _run(repo, store, "summary", "--json", capsys=capsys)
    assert code == 0
    [row] = json.loads(out)["runs"]
    assert (row["record_path"], row["next_step"], row["plan_path"]) == (None, "", PLAN)


def test_no_record_and_no_envelope_is_an_empty_list(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _run(repo, store, "summary", "--issue", "7", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    assert json.loads(out)["runs"] == []


def test_an_unknown_record_version_exits_3_with_one_line(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (store / "issue-104.json").write_text(json.dumps({"schema": "run_record.v9", "issue": 104}))
    code, out, err = _run(repo, store, "summary", "--issue", "104", "--json", capsys=capsys)
    assert (code, out) == (3, "")
    assert len(err.strip().splitlines()) == 1
    assert err.startswith("run_status: unknown record version")


def test_a_record_that_is_not_json_exits_2_with_one_line(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (store / "issue-104.json").write_text("{not json")
    code, out, err = _run(repo, store, "summary", "--issue", "104", capsys=capsys)
    assert (code, out) == (2, "")
    assert len(err.strip().splitlines()) == 1


def test_an_unresolvable_store_root_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_status.main(["--repo-root", str(tmp_path), "summary"])
    _, err = capsys.readouterr()
    assert code == 2
    assert len(err.strip().splitlines()) == 1


def test_all_active_lists_the_resolved_issue_first_and_skips_finished_runs(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "plan")
    run_record.set_next_step(store, 200, "review")
    run_record.set_next_step(store, 300, "work")
    run_record.set_next_step(store, 300, "")
    code, out, _ = _run(repo, store, "summary", "--all-active", "--json", capsys=capsys)
    assert code == 0
    assert [row["issue"] for row in json.loads(out)["runs"]] == [104, 200]


def test_all_active_leaves_out_a_closed_run_on_the_resolved_branch(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A checkout still on `issue/104` after its run closed draws no band line."""
    run_record.set_next_step(store, 104, "plan")
    run_record.set_next_step(store, 104, "")
    for args in (("--json",), ("--band",)):
        code, out, _ = _run(repo, store, "summary", "--all-active", *args, capsys=capsys)
        assert code == 0
        if args == ("--json",):
            assert json.loads(out)["runs"] == []
        else:
            assert "#104" not in out


def test_all_active_keeps_a_resolved_run_only_the_envelope_knows(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    code, out, _ = _run(repo, store, "summary", "--all-active", "--json", capsys=capsys)
    assert code == 0
    assert [row["issue"] for row in json.loads(out)["runs"]] == [104]


def test_a_closed_run_named_without_all_active_still_shows(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "plan")
    run_record.set_next_step(store, 104, "")
    code, out, _ = _run(repo, store, "summary", "--issue", "104", "--json", capsys=capsys)
    assert code == 0
    assert [row["issue"] for row in json.loads(out)["runs"]] == [104]


def test_all_active_skips_an_unreadable_record_with_a_warning(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 200, "review")
    (store / "issue-201.json").write_text(json.dumps({"schema": "run_record.v9"}))
    code, out, err = _run(
        repo, store, "summary", "--issue", "200", "--all-active", "--json", capsys=capsys
    )
    assert code == 0
    assert [row["issue"] for row in json.loads(out)["runs"]] == [200]
    assert "issue-201.json" in err


def test_text_form_prints_one_line_per_run(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "run /work on the plan")
    run_record.set_next_step(store, 200, "review")
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    code, out, _ = _run(repo, store, "summary", "--all-active", capsys=capsys)
    assert code == 0
    assert out.splitlines() == [
        f"#104 · plan · next: run /work on the plan · plan: {PLAN}",
        "#200 · no saga tick · next: review · no plan recorded",
    ]


def test_text_form_says_so_when_there_is_no_run(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(repo, store, "summary", "--issue", "7", capsys=capsys)
    assert code == 0
    assert out.strip() == "run_status: no saga run for this checkout"


def test_a_subdirectory_reads_the_checkout_envelopes(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    sub = repo / "docs"
    sub.mkdir(exist_ok=True)
    code, out, _ = _run(sub, store, "summary", "--issue", "104", "--json", capsys=capsys)
    assert code == 0
    assert json.loads(out)["runs"][0]["plan_file"] == str(repo / PLAN)


# --------------------------------------------------------------------------------------------
# `review`: the latest review run, from the review-state document (issues #108, #164, #161)
# --------------------------------------------------------------------------------------------

REVISION = "a" * 40

# The retired result shapes, as plain stored dicts. The module that wrote them is deleted, so a
# reader that still understood them would have nothing left to import.
_RETIRED = "review_" + "result"
LEGACY_V2 = {
    "schema": _RETIRED + ".v2",
    "loop": "code_review",
    "unit": "issue-108",
    "cycle": 2,
    "revision": REVISION,
    "outcome": "repairs_requested",
    "per_lens_results": [{"lens": "correctness", "derived_overall": 9}],
    "findings": [],
}
LEGACY_V1 = {"schema": _RETIRED + ".v1", "cycle": 1}


def _review(repo: Path, store: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> dict:
    code, out, err = _run(repo, store, "review", "--issue", "108", *args, "--json", capsys=capsys)
    assert (code, err) == (0, "")
    view = json.loads(out)
    assert view["schema"] == "review_view.v1"
    return view


STATE_FIXTURES = ROOT / "plugins" / "saga" / "tests" / "fixtures" / "review_state"


def _record_with_runs(store: Path) -> None:
    raw = json.loads((STATE_FIXTURES / "record.json").read_text(encoding="utf-8"))
    raw["issue"] = 108
    (store / "issue-108.json").write_text(json.dumps(raw), encoding="utf-8")


def test_review_prints_from_the_review_state_document(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with_runs(store)
    review = _review(repo, store, capsys=capsys)["review"]
    assert review["state_schema"] == "review_state.v1"
    assert (review["round"], review["outcome"]) == (3, "blocked")
    assert [lens["lens"] for lens in review["lenses"]] == [
        "correctness",
        "security",
        "testing",
        "architecture-maintainability",
    ]
    assert review["pending_choices"][0] == "merge-blocking"
    assert review["merge"]["waiting"] is True


def test_review_embeds_the_whole_document_for_state_records(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with_runs(store)
    review = _review(repo, store, capsys=capsys)["review"]
    state = review["state"]
    assert state["schema"] == "review_state.v1"
    for key in (
        "lenses",
        "findings",
        "pending_choices",
        "merge_blocking",
        "merge",
        "disputes",
        "consequence_disagreements",
        "unconfirmed",
        "where_to_look",
        "tools",
        "degraded_inputs",
        "rounds",
        "cost",
    ):
        assert key in state, key
    assert state["lenses"] and state["where_to_look"] and state["rounds"]
    assert state["lenses"] == review["lenses"]
    assert state["pending_choices"] == review["pending_choices"]
    assert state["merge"] == review["merge"]


def test_review_state_text_prints_numbered_questions(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with_runs(store)
    code, out, _ = _run(repo, store, "review", "--issue", "108", capsys=capsys)
    assert code == 0
    assert "Q1. merge-blocking" in out.splitlines()
    assert any(line.startswith("correctness") and " D " in f" {line} " for line in out.splitlines())


def test_review_is_null_without_a_review_run_or_a_record(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    view = _review(repo, store, capsys=capsys)
    assert (view["record_path"], view["review"]) == (None, None)
    code, out, _ = _run(repo, store, "review", "--issue", "108", capsys=capsys)
    assert code == 0
    assert out.strip() == "run_status: no review result recorded for #108"


def _legacy_only_record(store: Path, issue: int) -> None:
    run_record.set_next_step(store, issue, "review")
    record = run_record.load(store, issue)
    assert record is not None
    run_record.save(
        store,
        run_record.RunRecord(
            **{**record.__dict__, "review_cycles": [dict(LEGACY_V1), dict(LEGACY_V2)]}
        ),
    )


def test_review_never_reads_the_retired_result_shapes(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #161: a stored v1 or v2 entry is kept in the record and shows nothing."""
    _legacy_only_record(store, 108)
    view = _review(repo, store, capsys=capsys)
    assert view["review"] is None
    code, out, _ = _run(repo, store, "review", "--issue", "108", capsys=capsys)
    assert code == 0
    assert out.strip() == "run_status: no review result recorded for #108"


def test_the_band_never_reads_the_retired_result_shapes(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(store, units=[], cycles=(dict(LEGACY_V1), dict(LEGACY_V2)))
    _tick(repo, 412, lifecycle_phase="code-review")
    row = _band(repo, store, capsys)
    assert row["review"] is None
    assert "cycle" not in row["band_line"]


def test_the_status_reader_no_longer_imports_the_retired_modules() -> None:
    text = (SAGA_SCRIPTS / "run_status.py").read_text(encoding="utf-8")
    for name in ("review_" + "result", "review_" + "consensus", "review_" + "roster"):
        assert name not in text, name


def test_review_an_unknown_record_version_exits_3(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (store / "issue-108.json").write_text(json.dumps({"schema": "run_record.v9", "issue": 108}))
    code, out, err = _run(repo, store, "review", "--issue", "108", "--json", capsys=capsys)
    assert (code, out) == (3, "")
    assert len(err.strip().splitlines()) == 1


# --------------------------------------------------------------------------------------------
# unit-for: which unit row a session is working (issue #107, the token-capture mod)
# --------------------------------------------------------------------------------------------


def _units(
    store: Path, issue: int, units: list[dict[str, object]], next_step: str = "work"
) -> None:
    def change(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        record = existing or run_record.RunRecord(issue=issue)
        return run_record.RunRecord(**{**record.__dict__, "units": units, "next_step": next_step})

    run_record.update(store, issue, change)


def _unit_for(cwd: Path, store: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code, out, _ = _run(cwd, store, "unit-for", "--json", capsys=capsys)
    assert code == 0
    view = json.loads(out)
    assert view["schema"] == run_status.SCHEMA
    return view


def test_unit_for_matches_the_row_whose_worktree_is_the_checkout(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(
        store,
        412,
        [
            {"name": "u1", "worktree": "/elsewhere"},
            {"name": "u2", "worktree": str(repo)},
        ],
    )
    match = _unit_for(repo, store, capsys)["match"]
    assert match == {
        "issue": 412,
        "unit": "u2",
        "role": "worker",
        "matched_by": "worktree",
        "record_path": str(run_record.record_path(store, 412)),
        "store_root": str(store),
        "ambiguous": False,
    }


def test_unit_for_matches_from_a_subdirectory_of_the_worktree(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(store, 412, [{"name": "u2", "worktree": str(repo)}])
    sub = repo / "src"
    sub.mkdir()
    assert _unit_for(sub, store, capsys)["match"]["unit"] == "u2"


def test_unit_for_falls_back_to_the_branch_when_no_worktree_matches(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(
        store,
        412,
        [{"name": "u1", "branch": "orch/r1-u1"}, {"name": "u2", "branch": "issue/104"}],
    )
    view = _unit_for(repo, store, capsys)
    assert view["branch"] == "issue/104"
    assert (view["match"]["unit"], view["match"]["matched_by"]) == ("u2", "branch")


def test_unit_for_reads_unit_id_and_the_rows_own_staffing_role(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(
        store,
        412,
        [{"unit_id": "test-1", "role": "functional-tester", "worktree": str(repo)}],
    )
    match = _unit_for(repo, store, capsys)["match"]
    assert (match["unit"], match["role"]) == ("test-1", "functional-tester")


@pytest.mark.parametrize(
    ("review_loop_role", "staffing_role"),
    [
        ("review-fixer", "worker"),
        ("downstream-resolver", "worker"),
        ("review-controller", "targeted-reviewer"),
        ("external-reviewer", "targeted-reviewer"),
    ],
)
def test_unit_for_maps_orchestrates_review_loop_role_to_a_staffing_role(
    repo: Path,
    store: Path,
    capsys: pytest.CaptureFixture[str],
    review_loop_role: str,
    staffing_role: str,
) -> None:
    _units(store, 412, [{"unit_id": "r-1", "role": review_loop_role, "worktree": str(repo)}])
    assert _unit_for(repo, store, capsys)["match"]["role"] == staffing_role


def test_every_mapped_review_loop_role_lands_on_a_listed_staffing_role() -> None:
    assert set(run_status.REVIEW_LOOP_ROLES.values()) <= run_status.staffing_roles()


def test_unit_for_records_a_role_staffing_does_not_list_as_the_worker(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(store, 412, [{"name": "u2", "role": "made-up-role", "worktree": str(repo)}])
    assert _unit_for(repo, store, capsys)["match"]["role"] == "worker"


def test_unit_for_names_the_merging_worker_in_a_merge_turn_worktree(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(
        store,
        412,
        [{"name": "u2", "worktree": "/elsewhere", "merge_worktree": str(repo)}],
    )
    match = _unit_for(repo, store, capsys)["match"]
    assert (match["unit"], match["role"]) == ("u2", "merging-worker")


def test_unit_for_ignores_a_role_that_is_not_a_role_name(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(store, 412, [{"name": "u2", "role": "Bad Role\n", "worktree": str(repo)}])
    assert _unit_for(repo, store, capsys)["match"]["role"] == "worker"


def test_unit_for_prefers_a_worktree_match_then_an_active_record(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(store, 300, [{"name": "by-branch", "branch": "issue/104"}])
    _units(store, 301, [{"name": "finished", "worktree": str(repo)}], next_step="")
    _units(store, 302, [{"name": "active", "worktree": str(repo)}])
    match = _unit_for(repo, store, capsys)["match"]
    assert (match["issue"], match["unit"], match["ambiguous"]) == (302, "active", True)


def test_unit_for_is_null_for_an_unrelated_directory(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _units(store, 412, [{"name": "u2", "worktree": "/elsewhere", "branch": "orch/r1-u2"}])
    assert _unit_for(repo, store, capsys)["match"] is None


def test_unit_for_is_null_outside_a_git_checkout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code = run_status.main(["--repo-root", str(plain), "unit-for", "--json"])
    out, err = capsys.readouterr()
    assert (code, err) == (0, "")
    assert json.loads(out)["match"] is None


def test_unit_for_skips_an_unreadable_record_with_a_warning(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (store / "issue-201.json").write_text(json.dumps({"schema": "run_record.v9"}))
    _units(store, 412, [{"name": "u2", "worktree": str(repo)}])
    code, out, err = _run(repo, store, "unit-for", "--json", capsys=capsys)
    assert code == 0
    assert json.loads(out)["match"]["unit"] == "u2"
    assert "issue-201.json" in err


def test_unit_for_text_form_is_one_line(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(repo, store, "unit-for", capsys=capsys)
    assert (code, out.strip()) == (0, "run_status: no saga unit for this checkout")
    _units(store, 412, [{"name": "u2", "worktree": str(repo)}])
    _, out, _ = _run(repo, store, "unit-for", capsys=capsys)
    assert out.strip() == "#412 unit u2 (worker, by worktree)"


# --------------------------------------------------------------------------------------------
# The Claude Code mods read this output; nothing type-checks their TypeScript in continuous
# integration (DECISIONS.md, 2026-10-04), so these tie the contract to what the script prints.
# --------------------------------------------------------------------------------------------

ADAPTER = ROOT / "plugins" / "saga" / "com.infiquetra.claude"


def test_the_mod_reader_knows_the_version_the_script_prints() -> None:
    reader = (ADAPTER / "mods" / "run-record.ts").read_text(encoding="utf-8")
    assert f"KNOWN_RUN_STATUS_SCHEMA: SagaRunStatusSchema = '{run_status.SCHEMA}'" in reader
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    assert f"export type SagaRunStatusSchema = '{run_status.SCHEMA}'" in contract


def test_the_contract_declares_exactly_the_fields_a_run_row_carries(
    repo: Path, store: Path
) -> None:
    run_record.set_next_step(store, 104, "plan")
    row = run_status.run_view(store, repo, 104)
    assert row is not None
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    body = re.search(r"export type SagaRunStatus = \{(.*?)\n\}", contract, re.S)
    assert body, "the contract no longer declares SagaRunStatus"
    declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.MULTILINE))
    assert declared == set(row)


def test_the_review_mod_reader_knows_the_version_the_script_prints() -> None:
    reader = (ADAPTER / "mods" / "run-record.ts").read_text(encoding="utf-8")
    assert (
        f"KNOWN_REVIEW_VIEW_SCHEMA: SagaReviewViewSchema = '{run_status.REVIEW_SCHEMA}'" in reader
    )
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    assert f"export type SagaReviewViewSchema = '{run_status.REVIEW_SCHEMA}'" in contract
    assert (
        "export type SagaReviewLensState = "
        + " | ".join(f"'{state}'" for state in run_status.LENS_STATES)
        in contract
    )


def test_the_contract_declares_exactly_the_fields_a_review_finding_carries() -> None:
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    body = re.search(r"export type SagaReviewFinding = \{(.*?)\n\}", contract, re.S)
    assert body, "the contract no longer declares SagaReviewFinding"
    declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.MULTILINE))
    assert declared == set(run_status.FINDING_FIELDS)


def test_the_contract_declares_exactly_the_fields_unit_for_matches(repo: Path, store: Path) -> None:
    _units(store, 412, [{"name": "u2", "worktree": str(repo)}])
    match = run_status.unit_for(store, repo, "")
    assert match is not None
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    body = re.search(r"export type SagaUsageTarget = \{(.*?)\n\}", contract, re.S)
    assert body, "the contract no longer declares SagaUsageTarget"
    declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.MULTILINE))
    assert declared == set(match)


# --------------------------------------------------------------------------------------------
# The run status band's line (issue #105)
# --------------------------------------------------------------------------------------------

def _check(name: str, status: str) -> dict[str, object]:
    return {"name": name, "command": name, "catalogue_check": None, "status": status}


def _iteration(number: int, *statuses: str, green: bool = False) -> dict[str, object]:
    return {
        "iteration": number,
        "revision": REVISION,
        "green": green,
        "baseline": [_check(f"check-{i}", status) for i, status in enumerate(statuses)],
        "functional_checks": [],
        "scenario_smoke": [],
        "preview": {"declared": False, "status": "no-preview-declared"},
    }


def _unit(name: str, worktree: str, *iterations: dict[str, object]) -> dict[str, object]:
    return {"id": name, "worktree": worktree, "build_loop": {"iterations": list(iterations)}}


def _band_record(
    store: Path,
    *,
    units: list[dict[str, object]],
    cycles: tuple[dict[str, object], ...] = (),
    next_step: str = "run /work on the plan",
) -> None:
    run_record.set_next_step(store, 412, next_step)
    record = run_record.load(store, 412)
    assert record is not None
    run_record.save(
        store,
        run_record.RunRecord(
            **{**record.__dict__, "units": units, "review_cycles": list(cycles)}
        ),
    )


def _band(repo: Path, store: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code, out, err = _run(repo, store, "summary", "--issue", "412", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    [row] = json.loads(out)["runs"]
    return row


def test_band_line_shows_the_round_and_grades_for_state_records(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = json.loads((STATE_FIXTURES / "record.json").read_text(encoding="utf-8"))["review_cycles"]
    run_record.set_next_step(store, 412, "run /work on the plan")
    record = run_record.load(store, 412)
    assert record is not None
    run_record.save(
        store, run_record.RunRecord(**{**record.__dict__, "review_cycles": runs})
    )
    _tick(repo, 412, lifecycle_phase="code-review")
    row = _band(repo, store, capsys)
    assert row["band_line"] == (
        "#412 · code-review · review round 3 · "
        "correctness D, security D, testing A, architecture-maintainability A"
    )
    assert row["review"]["round"] == 3
    assert row["review"]["grades"] == [
        {"lens": "correctness", "grade": "D"},
        {"lens": "security", "grade": "D"},
        {"lens": "testing", "grade": "A"},
        {"lens": "architecture-maintainability", "grade": "A"},
    ]
    for retired in ("cycle", "standard_allowance", "escalated_allowance", "is_escalated"):
        assert retired not in row["review"], retired


def test_band_text_form_prints_the_band_line(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(store, units=[_unit("u1", str(repo), _iteration(1, "pass", green=True))])
    _tick(repo, 412, lifecycle_phase="work")
    code, out, _ = _run(repo, store, "summary", "--issue", "412", "--band", capsys=capsys)
    assert code == 0
    assert out.splitlines() == ["#412 · work · build loop pass 1, green"]


def test_band_line_leaves_out_the_review_when_none_is_recorded(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(store, units=[_unit("u1", str(repo), _iteration(1, "fail"))])
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert row["review"] is None
    assert row["band_line"] == "#412 · work · build loop pass 1, 1 failing"


def test_band_line_counts_green_units_when_the_checkout_is_none_of_them(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[
            _unit("u1", "/elsewhere/u1", _iteration(1, "pass", green=True)),
            _unit("u2", "/elsewhere/u2", _iteration(2, "pass", green=True)),
            _unit("u3", "/elsewhere/u3", _iteration(1, "fail")),
            {"id": "u4", "worktree": "/elsewhere/u4"},
        ],
    )
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert row["band_line"] == "#412 · work · build loop 2/3 units green"
    assert row["build_loop"]["unit"] is None


def test_band_line_picks_the_unit_whose_worktree_is_this_checkout(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[
            _unit("u1", "/elsewhere/u1", _iteration(5, "pass", green=True)),
            _unit("u2", str(repo), _iteration(2, "fail", "pass")),
        ],
    )
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert row["band_line"] == "#412 · work · build loop pass 2, 1 failing"


def test_band_line_counts_could_not_execute_apart_from_fail(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[_unit("u1", str(repo), _iteration(1, "fail", "could-not-execute", "pass"))],
    )
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert (row["build_loop"]["failing"], row["build_loop"]["could_not_execute"]) == (1, 1)
    assert row["band_line"] == "#412 · work · build loop pass 1, 1 failing, 1 could not run"


def test_band_line_falls_back_to_next_step_without_a_saga_envelope(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(store, units=[], next_step="address the review findings on the parser module")
    row = _band(repo, store, capsys)
    assert row["phase"] is None
    assert row["band_line"] == "#412 · address the review findings on the pars…"


def test_the_contract_declares_the_band_blocks_the_script_prints(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[_unit("u1", str(repo), _iteration(1, "fail"))],
        cycles=tuple(
            json.loads((STATE_FIXTURES / "record.json").read_text(encoding="utf-8"))[
                "review_cycles"
            ]
        ),
    )
    row = _band(repo, store, capsys)
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    for name, key in (("SagaRunBuildLoop", "build_loop"), ("SagaRunReviewProgress", "review")):
        body = re.search(rf"export type {name} = \{{(.*?)\n\}}", contract, re.S)
        assert body, f"the contract no longer declares {name}"
        declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.MULTILINE))
        assert declared == set(row[key]), name


def test_setup_notice_is_on_the_summary_row(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notice = {
        "text": "Missing saga-git and sandbox. Run /saga:setup.",
        "missing_tools": ["saga-git"],
        "sandbox_unavailable": True,
    }
    run_record.set_next_step(store, 150, "plan")

    def change(existing: run_record.RunRecord | None) -> run_record.RunRecord:
        assert existing is not None
        admission = dict(existing.admission)
        admission["setup_notice"] = notice
        return run_record.RunRecord(**{**existing.__dict__, "admission": admission})

    run_record.update(store, 150, change)
    _tick(repo, 150, lifecycle_phase="plan", plan_path=PLAN)
    code, out, err = _run(repo, store, "summary", "--issue", "150", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    view = json.loads(out)
    assert view["schema"] == "run_status.v1"
    assert view["repo_root"] == str(repo)
    [row] = view["runs"]
    assert row["setup_notice"] == notice


def test_setup_notice_is_null_when_the_record_has_none(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_record.set_next_step(store, 104, "plan")
    _tick(repo, 104, lifecycle_phase="plan", plan_path=PLAN)
    code, out, err = _run(repo, store, "summary", "--issue", "104", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    view = json.loads(out)
    assert view["schema"] == "run_status.v1"
    [row] = view["runs"]
    assert row["setup_notice"] is None
    assert row["issue"] == 104
    assert row["phase"] == "plan"
    assert row["next_step"] == "plan"
