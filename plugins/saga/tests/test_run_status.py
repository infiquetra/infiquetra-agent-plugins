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

import review_result  # noqa: E402
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
# `review`: the latest code review result, lens by lens (issue #108)
# --------------------------------------------------------------------------------------------

REVISION = "a" * 40
SELECTED = {
    "always_on": ["correctness", "security", "testing"],
    "conditional_applies": {"performance": "hot path", "docs": "public API"},
}


def _lens(
    name: str,
    *,
    scores: dict[str, int] | None = None,
    scorable: bool = True,
    executed: bool = True,
) -> object:
    return review_result.LensResult(
        lens=name,
        strictness="standard",
        scorable=scorable,
        executed=executed,
        dimension_scores=scores or {},
    )


def _finding(lens: str, severity: str, path: str, line: int, category: str) -> object:
    return review_result.Finding(
        path=path,
        line=line,
        category=category,
        lens=lens,
        dimension="d",
        severity=severity,
        evidence=f"{path}:{line} shows {category}",
        impact=f"{category} matters",
    )


def _result(*, cycle: int = 1, unit: str = "issue-108", loop: str = "code_review") -> object:
    return review_result.ReviewResult(
        revision=REVISION,
        roster_hash="sha256:test",
        outcome="review_incomplete",
        cycle=cycle,
        loop=loop,
        unit=unit,
        lens_results=[
            _lens("correctness", scores={"a": 10, "b": 9}),
            _lens("security", scores={"a": 5, "b": 4}),
            _lens("testing", executed=False),
            _lens("performance", scorable=False),
        ],
        findings=[
            _finding("security", "P2", "src/b.py", 4, "weak-check"),
            _finding("security", "P0", "src/a.py", 12, "injection"),
            _finding("performance", "P3", "src/c.py", 1, "slow-loop"),
            _finding("retired-lens", "P1", "src/d.py", 2, "orphan"),
        ],
    )


def _record_with(store: Path, *results: object, legacy: int = 0) -> None:
    run_record.set_next_step(store, 108, "review")
    record = run_record.load(store, 108)
    assert record is not None
    configuration = dict(record.run_configuration)
    configuration["applicable_lenses"] = {"value": SELECTED, "source": "operator"}
    cycles = [{"schema": "review_result.v1", "cycle": n} for n in range(1, legacy + 1)]
    cycles += [result.to_dict() for result in results]  # type: ignore[attr-defined]
    run_record.save(
        store,
        run_record.RunRecord(
            **{**record.__dict__, "run_configuration": configuration, "review_cycles": cycles}
        ),
    )


def _review(repo: Path, store: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> dict:
    code, out, err = _run(repo, store, "review", "--issue", "108", *args, "--json", capsys=capsys)
    assert (code, err) == (0, "")
    view = json.loads(out)
    assert view["schema"] == "review_view.v1"
    return view


def test_review_reads_the_latest_code_review_entry_and_counts_legacy_ones(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with(
        store,
        _result(cycle=1),
        _result(cycle=1, loop="post_merge"),
        _result(cycle=2),
        legacy=2,
    )
    view = _review(repo, store, capsys=capsys)
    assert view["issue"] == 108
    assert view["record_path"] == str(run_record.record_path(store, 108))
    assert view["legacy_entries"] == 2
    review = view["review"]
    assert (review["cycle"], review["loop"], review["revision"]) == (2, "code_review", REVISION)
    assert _review(repo, store, "--loop", "post_merge", capsys=capsys)["review"]["loop"] == (
        "post_merge"
    )


def test_review_maps_each_selected_lens_to_its_state(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with(store, _result())
    lenses = _review(repo, store, capsys=capsys)["review"]["lenses"]
    states = {lens["lens"]: (lens["state"], lens["reason"]) for lens in lenses}
    assert states == {
        "correctness": ("met", None),
        "security": ("not_met", None),
        "testing": ("not_run", "could not execute"),
        "performance": (
            "unscored",
            "establishes no threshold: no fixtures, or no qualified executor",
        ),
        "docs": ("not_run", "no result recorded"),
    }
    # A lens with no usable result never carries a score that could read as a low one.
    overall = {lens["lens"]: lens["derived_overall"] for lens in lenses}
    assert overall == {
        "correctness": 9.5,
        "security": 4.5,
        "testing": None,
        "performance": None,
        "docs": None,
    }


def test_review_groups_findings_by_lens_most_severe_first(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with(store, _result())
    review = _review(repo, store, capsys=capsys)["review"]
    by_lens = {lens["lens"]: lens for lens in review["lenses"]}
    security = by_lens["security"]
    assert security["finding_count"] == 2
    assert [(f["severity"], f["path"], f["line"]) for f in security["findings"]] == [
        ("P0", "src/a.py", 12),
        ("P2", "src/b.py", 4),
    ]
    assert security["top"] == security["findings"]
    assert set(security["findings"][0]) == set(run_status.FINDING_FIELDS)
    assert by_lens["performance"]["finding_count"] == 1
    assert by_lens["correctness"]["finding_count"] == 0
    assert [f["category"] for f in review["unattributed_findings"]] == ["orphan"]


def test_review_unit_filters_to_that_units_history(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with(store, _result(cycle=1, unit="u1"), _result(cycle=3, unit="u2"))
    assert _review(repo, store, "--unit", "u1", capsys=capsys)["review"]["unit"] == "u1"
    assert _review(repo, store, capsys=capsys)["review"]["unit"] == "u2"
    assert _review(repo, store, "--unit", "u9", capsys=capsys)["review"] is None


def test_review_is_null_without_a_v2_entry_or_a_record(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    view = _review(repo, store, capsys=capsys)
    assert (view["record_path"], view["review"]) == (None, None)
    _record_with(store, legacy=1)
    view = _review(repo, store, capsys=capsys)
    assert (view["legacy_entries"], view["review"]) == (1, None)
    code, out, _ = _run(repo, store, "review", "--issue", "108", capsys=capsys)
    assert code == 0
    assert out.strip() == "run_status: no review result recorded for #108"


def test_review_text_form_is_a_fixed_width_table(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _record_with(store, _result())
    code, out, _ = _run(repo, store, "review", "--issue", "108", capsys=capsys)
    assert code == 0
    assert out.splitlines() == [
        f"#108 · issue-108 · cycle 1 · code_review · review_incomplete · {REVISION[:12]}",
        "lens         state     findings",
        "correctness  met       0",
        "security     not met   2",
        "  P0 src/a.py:12 injection",
        "  P2 src/b.py:4 weak-check",
        "testing      not run   0  (could not execute)",
        "performance  unscored  1  (establishes no threshold: no fixtures, or no qualified executor)",
        "  P3 src/c.py:1 slow-loop",
        "docs         not run   0  (no result recorded)",
        "other findings: 1",
    ]


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
        ("review-controller", "lens-reviewer"),
        ("external-reviewer", "lens-reviewer"),
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

BAND_LENSES = [f"lens-{n}" for n in range(1, 11)]


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


def _band_result(*, cycle: int, unit: str = "u1", met: int = 7) -> object:
    return review_result.ReviewResult(
        revision=REVISION,
        roster_hash="sha256:test",
        outcome="repairs_requested",
        cycle=cycle,
        loop="code_review",
        unit=unit,
        lens_results=[
            _lens(lens, scores={"a": 10, "b": 9} if i < met else {"a": 5, "b": 4})
            for i, lens in enumerate(BAND_LENSES)
        ],
        findings=[],
    )


def _band_record(
    store: Path,
    *,
    units: list[dict[str, object]],
    results: tuple[object, ...] = (),
    configuration: dict[str, object] | None = None,
    next_step: str = "run /work on the plan",
) -> None:
    run_record.set_next_step(store, 412, next_step)
    record = run_record.load(store, 412)
    assert record is not None
    config = dict(record.run_configuration)
    config["applicable_lenses"] = {"value": {"always_on": BAND_LENSES}, "source": "operator"}
    config.update(configuration or {})
    run_record.save(
        store,
        run_record.RunRecord(
            **{
                **record.__dict__,
                "run_configuration": config,
                "units": units,
                "review_cycles": [result.to_dict() for result in results],  # type: ignore[attr-defined]
            }
        ),
    )


def _band(repo: Path, store: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    code, out, err = _run(repo, store, "summary", "--issue", "412", "--json", capsys=capsys)
    assert (code, err) == (0, "")
    [row] = json.loads(out)["runs"]
    return row


def test_band_line_reads_build_loop_review_cycle_and_lenses_met(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[
            _unit(
                "u1",
                str(repo),
                _iteration(1, "fail", "fail", "fail"),
                _iteration(2, "fail", "fail", "pass"),
                _iteration(3, "fail", "pass", "fail"),
            )
        ],
        results=(_band_result(cycle=1),),
    )
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert (
        row["band_line"]
        == "#412 · work · build loop pass 3, 2 failing · review cycle 1/3 · 7/10 lenses met"
    )
    assert row["build_loop"] == {
        "unit": "u1",
        "pass": 3,
        "failing": 2,
        "could_not_execute": 0,
        "green": False,
        "units_total": 1,
        "units_green": 0,
    }
    assert row["review"] == {
        "unit": "u1",
        "cycle": 1,
        "standard_allowance": 3,
        "escalated_allowance": 2,
        "is_escalated": False,
        "outcome": "repairs_requested",
        "lenses_met": 7,
        "lenses_total": 10,
        "lenses_not_run": 0,
    }


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


def test_band_line_marks_a_cycle_past_the_standard_allowance_as_escalated(
    repo: Path, store: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _band_record(
        store,
        units=[],
        results=(_band_result(cycle=3), _band_result(cycle=4, met=10)),
        configuration={
            "standard_cycle_allowance": {"value": 3},
            "escalated_cycle_allowance": 2,
        },
    )
    _tick(repo, 412, lifecycle_phase="code-review")
    row = _band(repo, store, capsys)
    assert row["build_loop"] is None
    assert (
        row["band_line"] == "#412 · code-review · review cycle 4/5 (escalated) · 10/10 lenses met"
    )


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
        results=(_band_result(cycle=2, unit="u2", met=4), _band_result(cycle=1, unit="u1")),
    )
    _tick(repo, 412, lifecycle_phase="work")
    row = _band(repo, store, capsys)
    assert row["band_line"] == (
        "#412 · work · build loop pass 2, 1 failing · review cycle 2/3 · 4/10 lenses met"
    )


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
        results=(_band_result(cycle=1),),
    )
    row = _band(repo, store, capsys)
    contract = (ADAPTER / "types" / "index.d.ts").read_text(encoding="utf-8")
    for name, key in (("SagaRunBuildLoop", "build_loop"), ("SagaRunReviewProgress", "review")):
        body = re.search(rf"export type {name} = \{{(.*?)\n\}}", contract, re.S)
        assert body, f"the contract no longer declares {name}"
        declared = set(re.findall(r"^\s+(\w+):", body.group(1), re.MULTILINE))
        assert declared == set(row[key]), name
