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
