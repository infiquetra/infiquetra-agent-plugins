"""Review records: validation, identity and storage in the run record (issue 148)."""

from __future__ import annotations

import copy
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
SCHEMA_FILE = REPO_ROOT / "plugins" / "saga" / "references" / "review-records.schema.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_records"
CLI = SCRIPTS / "review_records.py"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RR = _load("run_record")
F = _load("review_formula")
R = _load("review_records")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every in-process test here runs with sockets refused, so a network call fails the test."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("review record tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / "valid" / f"{name}.json").read_text(encoding="utf-8"))


VALID = {kind: fixture(kind) for kind in R.KINDS}
SHA = "0" * 63 + "1"


def problems_for(record: dict[str, Any]) -> list[str]:
    return R.validate(record)


def names(record: dict[str, Any]) -> list[str]:
    return [line.split(":", 1)[0] for line in R.validate(record)]


def with_identity(finding: dict[str, Any]) -> dict[str, Any]:
    finding["id"] = R.finding_identity(finding["lens"], finding["rule"], finding["location"])
    return finding


def tool_finding(**over: Any) -> dict[str, Any]:
    finding = copy.deepcopy(VALID["finding"])
    finding.update(
        {
            "rule": {"row": "security.scanner-medium-low", "ref": "semgrep:example-rule"},
            "lens": "security",
            "source": {"kind": "tool", "name": "semgrep", "version": "1.90.0"},
            "consequence": None,
            "trigger": None,
            "evidence": "tool-result",
            "proof": {"raw_output": SHA},
            "consequence_jev": None,
            "unconfirmed": False,
        }
    )
    finding.update(over)
    return with_identity(finding)


# --- every kind validates, and each missing field is named -------------------------------------


@pytest.mark.parametrize("kind", R.KINDS)
def test_each_valid_fixture_validates(kind: str) -> None:
    assert problems_for(VALID[kind]) == []


@pytest.mark.parametrize(
    ("kind", "field"), [(kind, field) for kind in R.KINDS for field in R.REQUIRED[kind]]
)
def test_each_missing_field_is_refused_by_name(kind: str, field: str) -> None:
    record = copy.deepcopy(VALID[kind])
    del record[field]
    if field == "kind":
        assert names(record) == ["kind"]
        return
    assert field in names(record)


@pytest.mark.parametrize(
    ("kind", "field", "value"),
    [
        ("finding", "lens", "style"),
        ("finding", "consequence", "annoying"),
        ("finding", "trigger", "sometimes"),
        ("finding", "evidence", "vibes"),
        ("finding", "language", "cobol"),
        ("finding", "subject", "slides"),
        ("finding", "introduced", "yes"),
        ("finding", "schema", "review_records.v0"),
        ("measurement", "direction", "sideways"),
        ("measurement", "value", "high"),
        ("where_to_look", "classifier", "jev"),
        ("lens_grade", "grade", "E"),
        ("lens_grade", "blocks", -1),
        ("builder_record", "reasons", "none"),
        ("review_run", "round", 0),
        ("review_run", "card", "C1"),
    ],
)
def test_each_wrong_value_is_refused_by_name(kind: str, field: str, value: Any) -> None:
    record = copy.deepcopy(VALID[kind])
    record[field] = value
    assert field in names(record)


def test_a_probability_outside_zero_to_one_is_refused() -> None:
    record = copy.deepcopy(VALID["where_to_look"])
    record["questions"][0]["probability"] = 1.5
    assert names(record) == ["questions.0.probability"]


# --- severity is computed, never handed in -----------------------------------------------------


@pytest.mark.parametrize("key", ["severity", "severity_basis", "flags", "enforced"])
def test_a_lone_finding_with_a_computed_field_is_refused(key: str) -> None:
    record = copy.deepcopy(VALID["finding"])
    record[key] = "blocks"
    assert key in names(record)


def test_a_review_run_finding_must_carry_the_computed_severity() -> None:
    run = copy.deepcopy(VALID["review_run"])
    del run["findings"][0]["severity"]
    assert "findings.0.severity" in names(run)


def test_a_stored_severity_that_differs_from_the_formula_is_refused() -> None:
    run = copy.deepcopy(VALID["review_run"])
    run["findings"][0]["severity"] = "note"
    found = R.validate(run)
    assert any(
        line.startswith("findings.0.severity:") and run["findings"][0]["id"] in line
        for line in found
    )


def test_a_stored_grade_or_merge_that_differs_from_the_formula_is_refused() -> None:
    run = copy.deepcopy(VALID["review_run"])
    run["merge"]["allowed"] = not run["merge"]["allowed"]
    assert "merge" in names(run)


def test_build_run_refuses_a_handed_in_severity() -> None:
    finding = {**VALID["finding"], "severity": "note"}
    with pytest.raises(R.ReviewRecordError) as caught:
        R.build_run({"findings": [finding]})
    assert any(line.startswith("findings.0.severity:") for line in caught.value.problems)


# --- secrets and raw output --------------------------------------------------------------------


def test_a_secret_scanner_finding_never_carries_the_secret() -> None:
    secret = fixture("finding-secret")
    assert problems_for(secret) == []
    for field in R.SECRET_FIELDS:
        assert field in names({**secret, field: "EXAMPLE-NOT-A-SECRET"})
    leaked = copy.deepcopy(secret)
    leaked["proof"]["output"] = "EXAMPLE-NOT-A-SECRET"
    assert "proof.output" in names(leaked)


def test_a_tool_result_references_raw_output_by_fingerprint() -> None:
    assert "proof.raw_output" in names(tool_finding(proof={"raw_output": "not-a-sha"}))
    run = copy.deepcopy(VALID["review_run"])
    run["raw_outputs"][0]["sha256"] = SHA[:-1]
    assert names(run) == ["raw_outputs.0.sha256"]


# --- merge outcomes ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        None,
        {"outcome": "fixed"},
        {"outcome": "dismissed", "reason": "the path is unreachable in production"},
        {"outcome": "fixed-now"},
        {"outcome": "filed", "issue": 412},
        {"outcome": "left"},
    ],
)
def test_each_merge_outcome_is_accepted(outcome: Any) -> None:
    assert problems_for({**VALID["finding"], "merge_outcome": outcome}) == []


@pytest.mark.parametrize(
    ("outcome", "field"),
    [
        ({"outcome": "merged"}, "merge_outcome.outcome"),
        ({"outcome": "dismissed"}, "merge_outcome.reason"),
        ({"outcome": "dismissed", "reason": " "}, "merge_outcome.reason"),
        ({"outcome": "filed"}, "merge_outcome.issue"),
        ({"outcome": "filed", "issue": "412"}, "merge_outcome.issue"),
    ],
)
def test_a_bad_merge_outcome_is_refused(outcome: Any, field: str) -> None:
    assert names({**VALID["finding"], "merge_outcome": outcome}) == [field]


# --- locations ---------------------------------------------------------------------------------


def test_a_code_finding_needs_its_lines() -> None:
    finding = copy.deepcopy(VALID["finding"])
    del finding["location"]["lines"]
    assert "location.lines" in names(finding)


def test_a_code_finding_needs_its_function_key() -> None:
    finding = copy.deepcopy(VALID["finding"])
    del finding["location"]["function"]
    assert "location.function" in names(finding)
    finding["location"]["function"] = None
    assert problems_for(with_identity(finding)) == []


def test_a_whole_project_tool_result_may_omit_the_lines() -> None:
    finding = tool_finding(
        rule={"row": "security.dependency-high", "ref": "osv:EXAMPLE-0001"},
        location={"scope": "whole-project", "file": "uv.lock", "anchor": "examplepkg"},
    )
    assert problems_for(finding) == []
    finding["location"]["lines"] = {"start": 1, "end": 1}
    assert "location.lines" in names(finding)


def test_only_a_plan_finding_may_name_a_section() -> None:
    finding = copy.deepcopy(VALID["finding"])
    finding["evidence"] = "traced"
    finding["proof"] = {"steps": ["docs/plans/example.md: the Requirements section names no AC-3"]}
    finding["consequence_jev"] = None
    finding["location"] = {
        "scope": "section",
        "document": "docs/plans/example.md",
        "section": "Requirements",
        "anchor": "Requirements",
    }
    finding["subject"] = "plan"
    assert problems_for(with_identity(finding)) == []
    finding["subject"] = "code"
    assert "location.scope" in names(finding)


def test_lines_must_not_run_backwards() -> None:
    finding = copy.deepcopy(VALID["finding"])
    finding["location"]["lines"] = {"start": 50, "end": 40}
    assert "location.lines.end" in names(finding)


# --- "unconfirmed" -----------------------------------------------------------------------------


def test_a_reproduced_llm_finding_without_jev_must_be_unconfirmed() -> None:
    finding = {**VALID["finding"], "consequence_jev": None}
    assert names(finding) == ["unconfirmed"]
    assert problems_for({**finding, "unconfirmed": True}) == []


def test_unconfirmed_with_a_jev_answer_is_refused() -> None:
    assert names({**VALID["finding"], "unconfirmed": True}) == ["unconfirmed"]


def test_unconfirmed_on_a_traced_finding_is_refused() -> None:
    finding = {
        **VALID["finding"],
        "evidence": "traced",
        "proof": {"steps": ["src/billing/charge.py:44 calls charge twice"]},
        "consequence_jev": None,
        "unconfirmed": True,
    }
    assert names(finding) == ["unconfirmed"]


def test_proof_matches_evidence() -> None:
    assert "proof.test" in names({**VALID["finding"], "proof": {}})
    traced = {**VALID["finding"], "evidence": "traced", "proof": {"steps": []}}
    assert "proof.steps" in names(traced)


# --- identity ----------------------------------------------------------------------------------


def test_identity_survives_a_line_shift() -> None:
    finding = VALID["finding"]
    moved = copy.deepcopy(finding["location"])
    moved["lines"] = {"start": 52, "end": 64}
    assert R.finding_identity(finding["lens"], finding["rule"], moved) == finding["id"]


def test_identity_survives_reindentation_and_a_later_round() -> None:
    finding = VALID["finding"]
    later = copy.deepcopy(finding["location"])
    later["anchor"] = "    for attempt in range(3):\n        gateway.charge(card, amount)\n"
    assert R.finding_identity(finding["lens"], finding["rule"], later) == finding["id"]
    run = VALID["review_run"]
    round_two = R.build_run({**_inputs_from(run), "round": 2})
    assert [f["id"] for f in round_two["findings"]] == [f["id"] for f in run["findings"]]


def test_two_rules_on_one_line_get_different_identities() -> None:
    location = VALID["finding"]["location"]
    first = R.finding_identity("security", {"row": "security.scanner-high", "ref": "a"}, location)
    second = R.finding_identity("security", {"row": "security.scanner-high", "ref": "b"}, location)
    third = R.finding_identity(
        "security", {"row": "security.scanner-medium-low", "ref": "a"}, location
    )
    assert len({first, second, third}) == 3


def test_one_rule_twice_in_one_function_gets_two_identities() -> None:
    finding = VALID["finding"]
    other = {**finding["location"], "anchor": "refund = gateway.refund(card, amount)"}
    assert R.finding_identity(finding["lens"], finding["rule"], other) != finding["id"]


def test_identity_is_recomputed_from_the_stored_record() -> None:
    stored = json.loads(json.dumps(VALID["review_run"]))
    for finding in stored["findings"]:
        assert R.finding_identity(finding["lens"], finding["rule"], finding["location"]) == (
            finding["id"]
        )


def test_a_handed_in_identity_that_does_not_match_is_refused() -> None:
    assert names({**VALID["finding"], "id": "rf:" + "0" * 32}) == ["id"]


# --- the schema file and the validator agree ---------------------------------------------------


def test_schema_file_matches_the_validator() -> None:
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    for kind in R.KINDS:
        assert defs[kind]["required"] == list(R.REQUIRED[kind]), kind
        assert defs[kind]["properties"]["kind"] == {"const": kind}
        assert defs[kind]["properties"]["schema"] == {"const": R.SCHEMA}
    finding = defs["finding"]["properties"]
    assert finding["lens"]["enum"] == list(F.LENSES)
    assert finding["language"]["enum"] == list(F.LANGUAGES)
    assert finding["evidence"]["enum"] == list(F.EVIDENCE)
    assert finding["consequence"]["enum"] == [*F.CONSEQUENCES, None]
    assert finding["trigger"]["enum"] == [*F.TRIGGERS, None]
    assert finding["severity"]["enum"] == list(F.SEVERITIES)
    assert set(finding["rule"]["properties"]["row"]["enum"]) == {F.JUDGED} | {
        row for row, spec in F.ROWS.items() if spec.lens
    }
    assert finding["source"]["properties"]["kind"]["enum"] == list(F.SOURCE_KINDS)
    assert defs["merge_outcome"]["properties"]["outcome"]["enum"] == list(F.MERGE_OUTCOMES)
    assert defs["location"]["properties"]["scope"]["enum"] == list(R.SCOPES)
    reasons = defs["builder_record"]["properties"]["reasons"]["items"]["properties"]
    assert reasons["kind"]["enum"] == list(F.REASON_KINDS)
    assert defs["lens_grade"]["properties"]["grade"]["enum"] == list(F.GRADES)


# --- the command line --------------------------------------------------------------------------


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize("path", sorted((FIXTURES / "valid").glob("*.json")), ids=lambda p: p.stem)
def test_validate_cli_accepts_each_valid_fixture(path: Path) -> None:
    completed = _cli("validate", str(path))
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""


@pytest.mark.parametrize(
    "path", sorted((FIXTURES / "invalid").glob("*.json")), ids=lambda p: p.stem
)
def test_validate_cli_refuses_each_invalid_fixture_naming_the_field(path: Path) -> None:
    field = path.stem.split("--", 1)[1]
    completed = _cli("validate", str(path))
    assert completed.returncode == 1
    assert any(line.startswith(f"{field}:") for line in completed.stderr.splitlines()), (
        completed.stderr
    )


def test_every_kind_has_an_invalid_fixture() -> None:
    kinds = {path.stem.split("--", 1)[0] for path in (FIXTURES / "invalid").glob("*.json")}
    assert kinds == set(R.KINDS)


def test_validate_cli_exits_2_on_an_unknown_kind_or_bad_json(tmp_path: Path) -> None:
    unknown = tmp_path / "unknown.json"
    unknown.write_text('{"kind": "verdict"}', encoding="utf-8")
    assert _cli("validate", str(unknown)).returncode == 2
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert _cli("validate", str(broken)).returncode == 2


# --- storage -----------------------------------------------------------------------------------


def _inputs_from(run: dict[str, Any]) -> dict[str, Any]:
    inputs = {name: copy.deepcopy(run[name]) for name in R.RUN_FIELDS if name in run}
    inputs.update(R._formula_inputs(run))
    return inputs


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    RR.save(root, RR.RunRecord(issue=148, units=[{"id": "U1", "usage": {"entries": []}}]))
    return root


def test_review_run_round_trip_keeps_every_field(store: Path) -> None:
    stored = R.record_run(store, 148, _inputs_from(VALID["review_run"]))
    assert stored == VALID["review_run"]
    record = RR.load(store, 148)
    assert record is not None
    runs = R.runs_on(record)
    assert len(runs) == 1
    entry = runs[0]
    assert entry["loop"] == R.STORED_LOOP
    assert {key: value for key, value in entry.items() if key != "loop"} == VALID["review_run"]
    assert R.validate(entry) == []


def _full_builder_record(unit: str = "U1") -> dict[str, Any]:
    finding_id = VALID["finding"]["id"]
    return {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": unit,
        "acceptance_criteria": [
            {"id": "AC-1", "text": "A retry charges once.", "checks": ["charge-retry-check"]},
            {"id": "AC-2", "text": "A refund is idempotent.", "checks": ["refund-check", "smoke"]},
        ],
        "declarations": [
            {"question": "correctness.q-retry-safe", "applies": True,
             "proving_test": "tests/test_charge.py::test_retry_after_timeout_charges_once"},
            {"question": "security.q-file-permissions", "applies": False, "proving_test": None},
        ],
        "reasons": [
            {"kind": kind, "finding_id": finding_id, "text": f"the builder's {kind} reason"}
            for kind in F.REASON_KINDS
        ],
    }


def test_builder_record_round_trip_keeps_every_reason_kind(store: Path) -> None:
    builder = _full_builder_record()
    assert R.validate(builder) == []
    R.record_builder(store, 148, "U1", builder)
    record = RR.load(store, 148)
    assert record is not None
    assert R.builder_record_for(record, "U1") == builder
    assert {reason["kind"] for reason in builder["reasons"]} == set(F.REASON_KINDS)


def test_a_repair_update_replaces_the_builder_record_and_keeps_other_row_keys(
    store: Path,
) -> None:
    RR.update(
        store,
        148,
        lambda rec: RR.RunRecord(
            **{**rec.__dict__, "units": [{**rec.units[0], "build_loop": {"iterations": [1]}}]}
        ),
    )
    first = _full_builder_record()
    R.record_builder(store, 148, "U1", first)
    second = copy.deepcopy(first)
    second["reasons"] = second["reasons"][:1]
    R.record_builder(store, 148, "U1", second)
    record = RR.load(store, 148)
    assert record is not None
    row = record.units[0]
    assert row["builder_record"] == second
    assert row["build_loop"] == {"iterations": [1]}
    assert row["usage"] == {"entries": []}


def test_record_run_reads_builder_records_from_the_rows(store: Path) -> None:
    builder = _full_builder_record()
    R.record_builder(store, 148, "U1", builder)
    inputs = _inputs_from(VALID["review_run"])
    del inputs["builder_records"]
    stored = R.record_run(store, 148, inputs)
    assert stored["builder_records"] == [builder]


def test_a_builder_record_for_a_new_unit_adds_an_id_row(store: Path) -> None:
    R.record_builder(store, 148, "U2", _full_builder_record("U2"))
    record = RR.load(store, 148)
    assert record is not None
    assert [row.get("id") for row in record.units] == ["U1", "U2"]


def test_a_builder_record_never_adds_a_row_orchestrate_drives(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    record = RR.RunRecord(
        issue=148,
        units=[{"id": "U1", "name": "U1", "vendor": "claude", "task": "build"}],
        extra={"orchestrate": {"run_id": "example"}},
    )
    RR.save(root, record)
    path = RR.record_path(root, 148)
    before = path.read_bytes()
    builder = tmp_path / "builder.json"
    builder.write_text(json.dumps(_full_builder_record("U2")), encoding="utf-8")
    completed = _cli(
        "--store-root", str(root), "record-builder", "--issue", "148", "--unit", "U2",
        str(builder),
    )
    assert completed.returncode == 5
    assert "U2" in completed.stderr
    assert path.read_bytes() == before


def test_a_builder_record_naming_another_unit_is_refused(store: Path) -> None:
    with pytest.raises(R.ReviewRecordError, match="unit"):
        R.record_builder(store, 148, "U1", _full_builder_record("U9"))


def test_a_usage_entry_written_meanwhile_survives_the_lock(store: Path) -> None:
    holding = threading.Event()

    def add_usage(record: Any) -> Any:
        holding.set()
        time.sleep(0.3)  # record_run starts now and must wait for this lock
        return RR.add_usage(
            record, "U1", session_id="s-1", role="worker", vendor="claude",
            model="example-model", effort="medium", counts={"output": 5},
        )

    writer = threading.Thread(target=lambda: RR.update(store, 148, add_usage))
    writer.start()
    assert holding.wait(5)
    R.record_run(store, 148, _inputs_from(VALID["review_run"]))
    writer.join(5)
    record = RR.load(store, 148)
    assert record is not None
    assert len(record.units[0]["usage"]["entries"]) == 1
    assert len(R.runs_on(record)) == 1


def test_stored_run_edited_on_disk_is_refused_on_validate(store: Path, tmp_path: Path) -> None:
    R.record_run(store, 148, _inputs_from(VALID["review_run"]))
    record = RR.load(store, 148)
    assert record is not None
    run = copy.deepcopy(R.runs_on(record)[0])
    run["findings"][0]["severity"] = "fix-later"
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(run), encoding="utf-8")
    completed = _cli("validate", str(edited))
    assert completed.returncode == 1
    assert run["findings"][0]["id"] in completed.stderr


def test_record_run_cli_refuses_a_handed_in_severity_and_writes_nothing(
    store: Path, tmp_path: Path
) -> None:
    inputs = _inputs_from(VALID["review_run"])
    inputs["findings"][0]["severity"] = "note"
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(inputs), encoding="utf-8")
    before = RR.record_path(store, 148).read_bytes()
    completed = _cli("--store-root", str(store), "record-run", "--issue", "148", str(path))
    assert completed.returncode == 1
    assert "findings.0.severity:" in completed.stderr
    assert RR.record_path(store, 148).read_bytes() == before


def test_other_review_cycle_readers_ignore_a_stored_run(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release_step = _load("release_step")
    cost_report = _load("cost_report")
    run_status = _load("run_status")
    review_result = _load("review_result")
    saga_spore = _load("saga_spore")
    R.record_run(store, 148, _inputs_from(VALID["review_run"]))
    record = RR.load(store, 148)
    assert record is not None and len(record.review_cycles) == 1
    assert release_step._code_review_cycles(RR.to_dict(record)) == []
    assert cost_report._code_review_history(record, "U1") == []
    for loop in ("code_review", "review_run", "plan_review"):
        assert run_status.latest_review(record, loop=loop) is None
        assert review_result.history_for(record, "U1", loop) == []
    monkeypatch.setattr(sys.modules["run_record"], "resolve_store_root", lambda *_: store)
    frozen = saga_spore.freeze_run_record(REPO_ROOT, {"saga_id": "issue-148"})
    assert frozen is not None and frozen["review_cycles"] == 0
