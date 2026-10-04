"""The plan's functional checks: read, written onto the run record, and mapped (issue #98).

Every test that touches a record writes it under ``tmp_path`` and names it with ``--record``.
Nothing here may create or modify anything under the primary checkout's ``.claude/saga/`` store,
which is live state. The modules under test are the real ones, loaded at module scope, because
``scripts/lint_test_shape.py`` rejects a suite whose production module is a fake.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


functional_checks = _load("functional_checks")
build_loop = _load("build_loop")
parse_issue = _load("parse_issue")


PLAN = """---
title: Fixture plan
type: feat
status: active
date: 2026-10-04
backend: inline
---

# Fixture plan

## Implementation Units

### U1. The writer

Writes the checks.

**Functional checks:**

```functional-checks
- name: writer-lists-checks
  command: python3 -m pytest tests/test_writer.py -q
  proves: [AC-1]
  runs: local
- name: writer-on-the-stack
  command: ./scripts/check-writer.sh --env
  proves: [AC-1, AC-2]
  runs: environment
```

### U2. The reviewer

```functional-checks
- name: map-blocks
  command: python3 scripts/map.py --plan plan.md
  proves: AC-2
  runs: local
```

## Scenario Smoke

```scenario-smoke
- name: end-to-end
  command: ./smoke.sh
  proves: [AC-3]
  runs: environment
```

## Key Technical Decisions

KTD1: a fixture.
"""

ISSUE_BODY = """### Objective

Build the writer.

### Acceptance criteria

- [ ] The writer lists the checks.
- [x] The reviewer blocks an unmapped criterion.
- [ ] The sentence is removed.

### Verification

- not a criterion
"""


def _record(units: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "schema": "run_record.v1",
        "issue": 98,
        "repo": "infiquetra/infiquetra-agent-plugins",
        "created_at": "2026-10-04T00:00:00Z",
        "updated_at": "2026-10-04T00:00:00Z",
        "admission": {},
        "run_configuration": {},
        "approval_scope": {},
        "roster": [],
        "units": units if units is not None else [],
        "review_cycles": [],
        "next_step": "plan",
        **extra,
    }


def _write(path: Path, payload: dict[str, Any] | str) -> Path:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(text, encoding="utf-8")
    return path


def _units(path: Path) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["units"]
    return units


# ---------------------------------------------------------------------------
# Reading the plan.
# ---------------------------------------------------------------------------


def test_parse_plan_reads_each_unit_and_the_smoke_in_the_written_shape() -> None:
    plan = functional_checks.parse_plan(PLAN)
    assert plan.problems == []
    assert list(plan.units) == ["U1", "U2"]
    assert plan.units["U1"][0] == {
        "name": "writer-lists-checks",
        "command": "python3 -m pytest tests/test_writer.py -q",
        "proves": ["AC-1"],
        "runs": "local",
    }
    # A single criterion written as a string is normalised to a one-item list.
    assert plan.units["U2"][0]["proves"] == ["AC-2"]
    assert plan.smoke == [
        {"name": "end-to-end", "command": "./smoke.sh", "proves": ["AC-3"], "runs": "environment"}
    ]
    assert plan.waiver is None


def test_a_unit_with_no_block_is_named_with_no_checks() -> None:
    unit = "### U3. Config only\n\nNo behaviour.\n\n## Scenario Smoke"
    text = PLAN.replace("## Scenario Smoke", unit)
    plan = functional_checks.parse_plan(text)
    assert plan.units["U3"] == []
    assert plan.units["U2"][0]["name"] == "map-blocks"


def test_a_heading_inside_a_fence_is_not_a_unit() -> None:
    text = PLAN.replace(
        "Writes the checks.", "Writes the checks.\n\n```markdown\n### U9. Not a unit\n```"
    )
    assert "U9" not in functional_checks.parse_plan(text).units


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("  command: python3 scripts/map.py --plan plan.md\n", "", "needs a command"),
        ("  proves: AC-2\n", "", "needs proves"),
        ("proves: AC-2", "proves: R1", "not AC-<n>"),
        ("  runs: local\n```\n\n## Scenario", "  runs: somewhere\n```\n\n## Scenario", "runs"),
        ("- name: map-blocks\n", "- command2: x\n  name: map-blocks\n", "unexpected keys"),
    ],
)
def test_a_malformed_entry_is_a_problem_naming_the_unit(old: str, new: str, expected: str) -> None:
    text = PLAN.replace(old, new, 1)
    assert text != PLAN
    problems = functional_checks.parse_plan(text).problems
    assert any(expected in problem and "unit U2" in problem for problem in problems), problems


def test_a_smoke_entry_must_run_against_the_environment() -> None:
    text = PLAN.replace("  proves: [AC-3]\n  runs: environment", "  proves: [AC-3]\n  runs: local")
    problems = functional_checks.parse_plan(text).problems
    assert any("scenario smoke" in problem for problem in problems)


def test_a_checks_block_outside_a_unit_is_a_problem() -> None:
    text = PLAN.replace(
        "## Key Technical Decisions",
        "## Key Technical Decisions\n\n```functional-checks\n- name: x\n  command: y\n"
        "  proves: [AC-1]\n  runs: local\n```",
    )
    problems = functional_checks.parse_plan(text).problems
    assert any("outside a `### U<N>.` unit" in problem for problem in problems)


def test_duplicate_check_names_are_a_problem() -> None:
    text = PLAN.replace("name: map-blocks", "name: end-to-end")
    assert any("unique" in p for p in functional_checks.parse_plan(text).problems)


def test_a_run_level_waiver_is_read_and_cannot_sit_beside_checks() -> None:
    waiver_only = (
        "# P\n\n## Implementation Units\n\n### U1. Docs\n\n## Scenario Smoke\n\n"
        "```functional-test-waiver\nreason: documentation only, no code\n```\n"
    )
    plan = functional_checks.parse_plan(waiver_only)
    assert plan.problems == []
    assert plan.waiver == {"reason": "documentation only, no code"}

    both = PLAN.replace(
        "## Scenario Smoke\n",
        "## Scenario Smoke\n\n```functional-test-waiver\nreason: no code\n```\n",
    )
    assert any("keep one" in p for p in functional_checks.parse_plan(both).problems)


def test_a_waiver_without_a_reason_is_a_problem() -> None:
    text = (
        "# P\n\n## Implementation Units\n\n### U1. Docs\n\n## Scenario Smoke\n\n"
        "```functional-test-waiver\nreason: ''\n```\n"
    )
    assert any("needs a reason" in p for p in functional_checks.parse_plan(text).problems)


# ---------------------------------------------------------------------------
# Writing onto the run record, in the shape build_loop reads.
# ---------------------------------------------------------------------------


def test_write_creates_rows_build_loop_reads_and_the_dry_run_lists_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The card's writer test: the saved checks reach the record, and the dry run lists them."""
    plan = _write(tmp_path / "plan.md", PLAN)
    record = _write(tmp_path / "issue-98.json", _record())

    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 0
    units = _units(record)
    assert [row["id"] for row in units] == ["U1", "U2"]
    assert units[0]["functional_checks"] == functional_checks.parse_plan(PLAN).units["U1"]
    assert units[1]["scenario_smoke"] == functional_checks.parse_plan(PLAN).smoke

    # Exactly the shape build_loop reads: its own reader keeps every written key.
    loaded = build_loop.load_record_file(record)
    criterion = build_loop.read_criterion(loaded, loaded.units[0], {})
    assert list(criterion.functional_checks) == units[0]["functional_checks"]

    capsys.readouterr()
    dry_run = ["--record", str(record), "--repo-root", str(tmp_path), "--dry-run"]
    assert build_loop.main(dry_run) == 0
    out = capsys.readouterr().out
    assert "none prescribed in the run record" not in out
    assert "Unit U1:" in out and "Unit U2:" in out
    assert "writer-lists-checks: python3 -m pytest tests/test_writer.py -q" in out
    assert "map-blocks: python3 scripts/map.py --plan plan.md  (proves AC-2; runs locally)" in out
    # The smoke is the same on every unit, so it is listed once.
    assert out.count("end-to-end: ./smoke.sh") == 1


def test_write_updates_matched_rows_in_place_and_keeps_every_other_key(tmp_path: Path) -> None:
    rows = [
        {"name": "U1", "build_loop": {"iterations": [1]}, "merge_state": "ready"},
        {"unit_id": "U2", "usage": {"entries": []}, "functional_checks": ["stale"]},
        {"id": "U7", "note": "not in the plan"},
    ]
    plan = _write(tmp_path / "plan.md", PLAN)
    record = _write(tmp_path / "issue-98.json", _record(units=rows, extra_top={"kept": True}))

    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 0
    raw = json.loads(record.read_text(encoding="utf-8"))
    units = raw["units"]
    assert len(units) == 3
    assert units[0]["build_loop"] == {"iterations": [1]} and units[0]["merge_state"] == "ready"
    assert units[0]["functional_checks"][0]["name"] == "writer-lists-checks"
    assert units[1]["usage"] == {"entries": []}
    assert units[1]["functional_checks"][0]["name"] == "map-blocks"
    assert units[2] == {"id": "U7", "note": "not in the plan"}
    assert raw["extra_top"] == {"kept": True}


def test_a_second_write_of_the_same_plan_leaves_the_record_byte_identical(tmp_path: Path) -> None:
    plan = _write(tmp_path / "plan.md", PLAN)
    record = _write(tmp_path / "issue-98.json", _record())
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 0
    first = record.read_bytes()
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 0
    assert record.read_bytes() == first


def test_write_on_an_absent_record_refuses_naming_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _write(tmp_path / "plan.md", PLAN)
    missing = tmp_path / "issue-404.json"
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(missing)]) == 2
    assert str(missing) in capsys.readouterr().err
    assert not missing.exists()


def test_write_of_a_malformed_plan_refuses_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _write(tmp_path / "plan.md", PLAN.replace("  proves: AC-2\n", ""))
    record = _write(tmp_path / "issue-98.json", _record())
    before = record.read_bytes()
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 2
    err = capsys.readouterr().err
    assert "unit U2" in err and "proves" in err
    assert record.read_bytes() == before


def test_write_refuses_to_add_rows_to_a_record_orchestrate_drives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = [{"name": "U1", "vendor": "claude", "task": "/work #98"}]
    plan = _write(tmp_path / "plan.md", PLAN)
    record = _write(tmp_path / "issue-98.json", _record(units=rows, orchestrate={"run_id": "r"}))
    before = record.read_bytes()
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 2
    assert "U2" in capsys.readouterr().err
    assert record.read_bytes() == before


def test_write_lands_on_orchestrate_rows_named_by_their_unit(tmp_path: Path) -> None:
    rows = [
        {"name": "U1", "vendor": "claude", "task": "t1"},
        {"name": "U2", "vendor": "claude", "task": "t2"},
    ]
    plan = _write(tmp_path / "plan.md", PLAN)
    record = _write(tmp_path / "issue-98.json", _record(units=rows, orchestrate={"run_id": "r"}))
    assert functional_checks.main(["write", "--plan", str(plan), "--record", str(record)]) == 0
    assert [row["task"] for row in _units(record)] == ["t1", "t2"]
    assert all(row["functional_checks"] for row in _units(record))


def test_extract_prints_the_plan_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = _write(tmp_path / "plan.md", PLAN)
    assert functional_checks.main(["extract", "--plan", str(plan)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"units", "scenario_smoke", "waiver", "problems"}
    assert payload["units"]["U2"][0]["name"] == "map-blocks"


# ---------------------------------------------------------------------------
# The issue's acceptance criteria.
# ---------------------------------------------------------------------------


def test_acceptance_criteria_are_numbered_in_order_checked_boxes_included() -> None:
    criteria = parse_issue.acceptance_criteria(ISSUE_BODY)
    assert criteria == [
        {"id": "AC-1", "text": "The writer lists the checks."},
        {"id": "AC-2", "text": "The reviewer blocks an unmapped criterion."},
        {"id": "AC-3", "text": "The sentence is removed."},
    ]


def test_plain_bullets_are_read_when_the_section_has_no_checkboxes() -> None:
    body = "### Acceptance criteria\n\n- one\n* two\n\n## Next\n\n- not this\n"
    assert [c["text"] for c in parse_issue.acceptance_criteria(body)] == ["one", "two"]


def test_a_missing_section_has_no_criteria_and_extract_is_unchanged() -> None:
    assert parse_issue.acceptance_criteria("### Objective\n\n- a bullet\n") == []
    assert set(parse_issue.extract(ISSUE_BODY)) == {
        "adr_refs",
        "ac_refs",
        "round_refs",
        "flags",
        "handoff",
        "test_naming_pattern",
        "first_line",
    }
