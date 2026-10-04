"""The plan-review loop: /plan dispatches it, and /work still refuses without the override.

Issue 1026, units U1 through U4, and card 933. These cases pin instruction text, because what
changed is what the three skills instruct — there is no runtime module between the operator and
the behaviour. Each case therefore names the file and the contract sentence it guards, so a later
edit that drops the sentence fails here rather than silently removing a gate.

Issue #98 added the one exception: the acceptance-criteria mapping check is a script,
``functional_checks.py map``, that the review runs. Its cases below exercise the real module, and
the prose pins hold the two skills to running it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
PLAN_SKILL = SAGA / "skills" / "plan" / "SKILL.md"
WORK_SKILL = SAGA / "skills" / "work" / "SKILL.md"
DOC_REVIEW_SKILL = SAGA / "skills" / "doc-review" / "SKILL.md"
WORKFLOW_BACKEND_REF = SAGA / "references" / "workflow-backend.md"
ROSTER = ROOT / "plugins" / "agent-launcher" / "skills" / "agent-launcher" / "scripts" / "roster.py"
PLAN_REVIEWER_ROLE = ROOT / "plugins" / "agent-launcher" / "roles" / "plan-reviewer.md"
SCRIPTS = SAGA / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: The real mapping module, at module scope: the behavioural cases below run it, never a fake.
functional_checks = _load("functional_checks")


def _section(text: str, heading: str) -> str:
    """The body of one ``###`` section, up to the next heading of the same or higher level."""
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(r"\n#{1,3} ", rest)
    return rest[: end.start()] if end else rest


# --------------------------------------------------------------------------- U2


def test_plan_dispatches_the_review_without_an_operator_command() -> None:
    """/plan Phase 5.4 runs the review; it does not recommend that the operator run it."""
    text = PLAN_SKILL.read_text(encoding="utf-8")
    assert "### 5.4 Dispatch the plan review, and loop until it passes" in text
    body = _section(text, "### 5.4 Dispatch the plan review, and loop until it passes")
    assert "does not recommend the review; it runs it" in body

    # The retired routing bullet, in the shape it used to have: a recommendation that the
    # operator run the review before execution.
    assert "**`/doc-review`** (recommended next)" not in text


def test_reviewer_resolution_names_both_branches_and_reads_the_run_record() -> None:
    """The roster-pane branch and the same-session branch are both written, and the choice
    is read from the run record rather than probed from the environment."""
    body = _section(
        PLAN_SKILL.read_text(encoding="utf-8"),
        "### 5.4 Dispatch the plan review, and loop until it passes",
    )
    assert ".claude/saga/runs/issue-<N>.json" in body
    assert "roster" in body and "plan-reviewer" in body
    assert "review-only mode" in body
    assert "roster.py" in body
    # Exit 4 (outside a herdr pane) falls through; exit 5 (blocked) is reported, never answered.
    assert "exit 4" in body and "exit 5" in body


def test_the_roster_helper_and_role_prompt_the_dispatch_names_exist() -> None:
    """The two files Phase 5.4 dispatches through are present at the paths it names."""
    if not ROSTER.is_file() or not PLAN_REVIEWER_ROLE.is_file():
        pytest.skip(
            "agent-launcher's roster script and plan-reviewer role are not in this checkout; "
            "that package is imported on its own branch"
        )
    assert ROSTER.is_file()
    assert PLAN_REVIEWER_ROLE.is_file()
    assert "plan-reviewer" in ROSTER.read_text(encoding="utf-8")
    assert "role_id: plan_reviewer" in PLAN_REVIEWER_ROLE.read_text(encoding="utf-8")


def test_the_loop_bound_comes_from_the_run_record_not_a_literal() -> None:
    """The cycle allowance is read from the record, so a run can lower it without editing
    the skill. A literal count here would be a second copy of a settled number."""
    body = _section(
        PLAN_SKILL.read_text(encoding="utf-8"),
        "### 5.4 Dispatch the plan review, and loop until it passes",
    )
    assert "standard_cycle_allowance" in body
    assert "escalated_cycle_allowance" in body
    assert "review_cycles" in body
    assert re.search(r"\bthree cycles\b|\bthree standard cycles\b", body) is None


def test_exhausting_the_allowance_stops_rather_than_passing() -> None:
    body = _section(
        PLAN_SKILL.read_text(encoding="utf-8"),
        "### 5.4 Dispatch the plan review, and loop until it passes",
    )
    assert "stops and\n  reports" in body or "stops and reports" in body
    assert "it never passes" in body


def test_the_board_move_to_ready_for_active_follows_the_review() -> None:
    """A board move's trigger must be observable where the move is made: the card is Ready
    for Active because the review passed, so the submission sits after the loop."""
    text = PLAN_SKILL.read_text(encoding="utf-8")
    loop = text.index("### 5.4 Dispatch the plan review")
    move = text.index("### 5.5 Submit the card's move to `Planning` / `Ready for Active`")
    assert loop < move
    assert "§5.4's review loop recorded a **pass**" in text


# --------------------------------------------------------------------------- U3


def test_an_explicitly_submitted_path_is_reviewed_as_given() -> None:
    """Card 933: a document the caller names is reviewed, never redirected."""
    body = _section(DOC_REVIEW_SKILL.read_text(encoding="utf-8"), "## Target Resolution")
    assert "review that document, as given" in body
    assert "never redirect it" in body


def test_one_cycle_is_defined_as_a_result_followed_by_a_repair_batch() -> None:
    """The definition matches the lifecycle repository's at revision 5efc869f, so the two
    cannot mean different things by the same word."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "One cycle is one completed review result followed by one repair batch" in text
    assert "A re-read after no\nrepair is not a cycle" in text


def test_the_verdict_is_bound_to_the_revision_reviewed() -> None:
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "Bind the verdict to the revision you read" in text


def test_doc_review_is_dispatched_not_requested() -> None:
    """The retired arrangement: /doc-review explicit by default, /work asking whether to run it."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "`/doc-review` is explicit by default" not in text
    assert "`/work` should ask whether to run it" not in text
    assert "dispatched, not requested" in text


# --------------------------------------------------------------------------- U4


def test_work_refuses_on_an_open_p0_without_the_operator_override() -> None:
    """The floor gate stays blocking. This is the preservation case: if it ever passes on a
    weakened §1.3 the gate has been removed while still looking present."""
    body = _section(WORK_SKILL.read_text(encoding="utf-8"), "### 1.3 Doc-review gate")
    assert "block execution" in body
    assert "`P0` or `P1`" in body
    assert "operator explicitly overriding, in one word, with a rationale" in body


def test_the_work_gate_produces_no_override_from_any_condition() -> None:
    """No automatic override: not a finding count, not an exhausted allowance, not
    unattended mode. Card 1026's non-goal, written as an assertion."""
    body = _section(WORK_SKILL.read_text(encoding="utf-8"), "### 1.3 Doc-review gate")
    assert "Nothing else produces an override" in body
    for condition in ("finding count", "cycle allowance", "unattended mode"):
        assert condition in body, f"§1.3 must rule out {condition!r} as an override source"


def test_the_work_gate_declares_its_absence_contract() -> None:
    """The gate carries the marker ``lint_gate_absence_contract.py`` parses, with HALT."""
    text = WORK_SKILL.read_text(encoding="utf-8")
    marker = re.search(
        r"<!-- gate-record: id=work-doc-review-floor absence=(\w+) transport=([\w-]+) -->", text
    )
    assert marker is not None, "§1.3's gate-record marker is missing or unparseable"
    assert marker.group(1) == "HALT"


def test_the_work_gate_reads_the_durable_record_before_chat_memory() -> None:
    """Parse the ordered list itself, not the first occurrence of each phrase.

    A guard that searched the section for three substrings would pass while item 1 said
    "whatever this session remembers", because the later items still mention the record. So this
    reads the numbered items and asserts what each one is.
    """
    body = _section(WORK_SKILL.read_text(encoding="utf-8"), "### 1.3 Doc-review gate")
    items = re.findall(r"^\d+\. (.+?)(?=\n\d+\. |\n\n)", body, re.DOTALL | re.MULTILINE)
    assert len(items) == 3, f"§1.3's evidence order is not a three-item list: {items}"
    first, second, third = (" ".join(i.split()) for i in items)
    assert "review_cycles" in first and ".claude/saga/runs" in first, (
        f"the first source of truth must be the durable run record, not: {first!r}"
    )
    assert "ame-session" in second, second
    assert "docs/reviews/" in third, third
    for item in (first, second, third):
        assert "remember" not in item.lower(), (
            "chat memory is not durable evidence and must not appear in the evidence order"
        )


# --------------------------------------------------------------------------- U1


#: What a reader arriving at the backend decision must be told, now that there is only one value.
#: Until issue 1030 this tuple held issue #808's NARROW clauses -- "explicit invocation", "never a
#: default", "interchangeable", "never pre-select" -- and the section had to point at
#: ``references/workflow-backend.md``. Both backends those clauses gated are gone and that
#: reference file went with them, so the guard had come to REQUIRE a dangling pointer: the skills
#: kept citing a deleted file because this case failed if they stopped. What survives is the
#: reader's actual need, which is to learn the backend without opening anything.
ONE_BACKEND_CONTRACT = (
    "`inline`",
    "1030",
)


def _backend_section(skill: Path) -> str:
    """The one ``###`` section where the backend is stated.

    Scoped to that section on purpose. A guard that searched the whole file would pass on a
    sentence left behind somewhere else while the section a reader actually lands in said
    nothing -- and that section is the only one whose reader is deciding.
    """
    text = skill.read_text(encoding="utf-8")
    match = re.search(r"(?:There is one backend|The recorded enum has one value)", text)
    assert match is not None, f"{skill.name} no longer states which backend a run uses"
    anchor = match.start()
    start = text.rindex("\n### ", 0, anchor)
    end = re.search(r"\n#{1,3} ", text[anchor:])
    stop = anchor + end.start() if end else len(text)
    return text[start:stop].lower()


def test_the_skills_name_the_one_backend_where_the_choice_used_to_be_made() -> None:
    """A reader must learn the backend from the section they land in, without following a link."""
    for skill in (PLAN_SKILL, WORK_SKILL):
        section = _backend_section(skill)
        for clause in ONE_BACKEND_CONTRACT:
            assert clause.lower() in section, (
                f"{skill.name}'s backend section drops {clause!r}, so a reader cannot tell from "
                "the skill which backend runs the work or why there is only one"
            )


def test_no_skill_points_at_the_reference_file_that_was_deleted() -> None:
    """The reference file left with the `cc-workflows` plugin; a pointer to it resolves nowhere."""
    assert not WORKFLOW_BACKEND_REF.exists(), (
        "references/workflow-backend.md is back; this guard and its siblings assume it is gone"
    )
    for skill in (PLAN_SKILL, WORK_SKILL):
        text = skill.read_text(encoding="utf-8")
        assert "references/workflow-backend.md" not in text, (
            f"{skill.name} still sends the reader to a reference file that does not exist"
        )


# --------------------------------------------------------------------------- issue #98


ISSUE_BODY = """### Objective

Prove every criterion.

### Acceptance criteria

- [ ] The writer lists the checks.
- [ ] The reviewer blocks an unmapped criterion.
- [ ] The smoke covers the whole flow.

### Verification

- not a criterion
"""


def _plan(unit_proves: str, smoke_proves: str = "[AC-3]") -> str:
    return f"""# Plan

## Implementation Units

### U1. The only unit

```functional-checks
- name: unit-check
  command: python3 -m pytest tests/test_unit.py -q
  proves: {unit_proves}
  runs: local
```

## Scenario Smoke

```scenario-smoke
- name: flow-smoke
  command: ./smoke.sh
  proves: {smoke_proves}
  runs: environment
```

## Key Technical Decisions

KTD1: a fixture.
"""


def _map(
    tmp_path: Path, plan: str, *, record: dict[str, Any] | None = None, body: str = ISSUE_BODY
) -> list[str]:
    (tmp_path / "plan.md").write_text(plan, encoding="utf-8")
    (tmp_path / "body.md").write_text(body, encoding="utf-8")
    argv = [
        "map",
        "--plan",
        str(tmp_path / "plan.md"),
        "--body-file",
        str(tmp_path / "body.md"),
        "--repo-root",
        str(tmp_path),
        "--json",
    ]
    if record is not None:
        (tmp_path / "issue-98.json").write_text(json.dumps(record), encoding="utf-8")
        argv += ["--record", str(tmp_path / "issue-98.json")]
    return argv


def test_an_unmapped_acceptance_criterion_blocks_readiness(tmp_path: Path, capsys) -> None:
    """The card's named case: a criterion no check proves is named, with its text, and exit 1."""
    argv = _map(tmp_path, _plan("[AC-1]"))
    assert functional_checks.main(argv) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not-ready"
    assert result["unmapped"] == [
        {"id": "AC-2", "text": "The reviewer blocks an unmapped criterion."}
    ]


def test_the_text_report_names_the_unmapped_criterion_and_quotes_it(tmp_path: Path, capsys) -> None:
    argv = [arg for arg in _map(tmp_path, _plan("[AC-1]")) if arg != "--json"]
    assert functional_checks.main(argv) == 1
    out = capsys.readouterr().out
    assert "AC-2 NOT MAPPED: The reviewer blocks an unmapped criterion." in out


def test_every_criterion_mapped_one_only_through_the_smoke_is_ready(
    tmp_path: Path, capsys
) -> None:
    argv = _map(tmp_path, _plan("[AC-1, AC-2]"))
    assert functional_checks.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "ready"
    third = result["criteria"][2]
    assert third["id"] == "AC-3"
    assert third["mapped_by"] == [{"name": "flow-smoke", "unit": None, "runs": "environment"}]


def test_a_check_citing_a_criterion_the_issue_lacks_is_not_ready(tmp_path: Path, capsys) -> None:
    argv = _map(tmp_path, _plan("[AC-1, AC-2, AC-9]"))
    assert functional_checks.main(argv) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["unmapped"] == []
    assert result["unknown_refs"] == [{"ref": "AC-9", "check": "unit-check", "unit": "U1"}]


def test_a_repository_waiver_recorded_at_admission_skips_the_mapping(
    tmp_path: Path, capsys
) -> None:
    record = {
        "schema": "run_record.v1",
        "issue": 98,
        "admission": {
            "functional_test_environment": {
                "mode": "waived",
                "level": "repository",
                "reason": "documentation only: nothing here runs",
                "source": "operator",
            }
        },
        "units": [],
    }
    argv = _map(tmp_path, _plan("[AC-1]"), record=record)
    assert functional_checks.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "waived"
    assert result["waiver"]["reason"] == "documentation only: nothing here runs"
    assert result["waiver"]["level"] == "repository"


def test_a_run_level_waiver_in_the_plan_skips_the_mapping_and_says_so(
    tmp_path: Path, capsys
) -> None:
    plan = (
        "# Plan\n\n## Implementation Units\n\n### U1. Docs\n\n## Scenario Smoke\n\n"
        "```functional-test-waiver\nreason: documentation only, no code\n```\n"
    )
    argv = [arg for arg in _map(tmp_path, plan) if arg != "--json"]
    assert functional_checks.main(argv) == 0
    out = capsys.readouterr().out
    assert "waived for this run (run level: documentation only, no code)" in out
    assert "the mapping check was skipped" in out


def test_a_run_level_waiver_beside_checks_does_not_skip_the_mapping(
    tmp_path: Path, capsys
) -> None:
    """A plan carrying checks is code-bearing by its own evidence, so its waiver is not honoured."""
    plan = (
        "# Plan\n\n## Implementation Units\n\n### U1. The only unit\n\n"
        "```functional-checks\n- name: unit-check\n  command: python3 -m pytest -q\n"
        "  proves: [AC-1]\n  runs: local\n```\n\n## Scenario Smoke\n\n"
        "```functional-test-waiver\nreason: docs only\n```\n"
    )
    argv = [arg for arg in _map(tmp_path, plan) if arg != "--json"]
    assert functional_checks.main(argv) == 1
    out = capsys.readouterr().out
    assert "waived" not in out.splitlines()[0]
    assert "the plan carries a functional-test waiver and functional checks; keep one" in out
    assert "AC-2 NOT MAPPED" in out and "AC-3 NOT MAPPED" in out


def test_a_repository_waiver_does_not_hide_a_malformed_block(tmp_path: Path, capsys) -> None:
    record = {
        "schema": "run_record.v1",
        "issue": 98,
        "admission": {
            "functional_test_environment": {
                "mode": "waived",
                "level": "repository",
                "reason": "nothing here runs",
                "source": "operator",
            }
        },
        "units": [],
    }
    plan = _plan("[AC-1]").replace("  runs: local\n", "  runs: nowhere\n")
    argv = _map(tmp_path, plan, record=record)
    assert functional_checks.main(argv) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "not-ready"
    assert result["unmapped"] == []
    assert any("runs must be" in problem for problem in result["problems"])


def test_an_issue_with_no_acceptance_criteria_section_is_a_refusal(
    tmp_path: Path, capsys
) -> None:
    argv = _map(tmp_path, _plan("[AC-1]"), body="### Objective\n\nNo criteria here.\n")
    assert functional_checks.main(argv) == 2
    assert "Acceptance criteria" in capsys.readouterr().err


def test_doc_review_runs_the_mapping_check_and_makes_a_gap_blocking() -> None:
    body = _section(
        DOC_REVIEW_SKILL.read_text(encoding="utf-8"),
        "## Acceptance-criteria mapping — a blocking check",
    )
    assert "functional_checks.py map --plan <plan path> --issue <N>" in body
    assert "`P1` finding that names its `AC-<n>`" in body
    assert "the mapping check was skipped" in body
    assert "Exit 2 stops the review" in body
    assert "A run-level waiver on a code-bearing change is a" in body


def test_choosing_the_proving_test_is_never_a_safe_in_place_fix() -> None:
    body = _section(DOC_REVIEW_SKILL.read_text(encoding="utf-8"), "## Safe In-Place Fixes")
    assert "- choosing the test that proves an acceptance criterion" in body


def test_plan_writes_the_checks_onto_the_record_and_maps_before_dispatch() -> None:
    text = PLAN_SKILL.read_text(encoding="utf-8")
    start = text.index("#### 5.3a Write the functional checks onto the run record")
    section = text[start : text.index("### 5.4 ", start)]
    assert "functional_checks.py write --plan <plan path> --issue <N>" in section
    assert "re-run it after every §5.4 repair batch" in section
    body = _section(text, "### 5.4 Dispatch the plan review, and loop until it passes")
    assert "functional_checks.py map --plan <plan path> --issue <N>" in body
