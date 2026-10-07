"""Review state for every harness and fix-later choices (issue #164).

These cases exercise the real ``review_state.py`` against fixture records in
tmp directories — no network (sockets refused), no ``gh`` (an injected runner
records publication), no sibling checkout (mission-control arrives as an
injected fake, plus one offline run of the real ``issue prepare``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
SCRIPTS = SAGA / "scripts"
FIXTURES = SAGA / "tests" / "fixtures" / "review_state"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


review_state = _load("review_state")
review_records = _load("review_records")
run_record = _load("run_record")
run_status = _load("run_status")
saga_spore = _load("saga_spore")

FAKE_MC = Path("fake-mc-for-tests")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails it."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network call in a test that must not make one")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture()
def staged(tmp_path: Path) -> dict[str, Path]:
    """The record fixtures copied to a writable tmp directory."""
    for name in ("record.json", "record-clear.json"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return {
        "record": tmp_path / "record.json",
        "clear": tmp_path / "record-clear.json",
        "envelope": FIXTURES / "envelope.json",
        "unattended": FIXTURES / "unattended.json",
        "profile": FIXTURES / "profile.json",
    }


def _envelope(name: str = "envelope.json") -> dict[str, Any]:
    return review_state.load_envelope_file(FIXTURES / name)


def _record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _newest_findings(path: Path) -> list[dict[str, Any]]:
    runs = [
        e for e in _record(path)["review_cycles"]
        if isinstance(e, dict) and e.get("kind") == "review_run"
    ]
    return [f for f in runs[-1]["findings"] if isinstance(f, dict)]


def _outcome_of(path: Path, finding_id: str) -> dict[str, Any] | None:
    for finding in _newest_findings(path):
        if finding["id"] == finding_id:
            return finding.get("merge_outcome")
    raise AssertionError(f"no stored finding {finding_id}")


def _fix_later_ids(path: Path) -> list[str]:
    return [f["id"] for f in _newest_findings(path) if f.get("severity") == "fix-later"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeMissionControl:
    """Mission-control's prepare/create protocol, scripted per test.

    Success paths write real drafts and sidecars under the given working
    directory, so the stage fill-in and the sidecar re-read execute for real.
    """

    def __init__(self, mode: str = "success", number: int = 412) -> None:
        self.mode = mode
        self.number = number
        self.calls: list[tuple[list[str], Any]] = []

    def __call__(self, argv: Any, cwd: Any = None) -> SimpleNamespace:
        self.calls.append((list(argv), cwd))
        if "prepare" in list(argv):
            return self._prepare(argv, cwd)
        return self._create(argv, cwd)

    def _title(self, argv: list[str]) -> str:
        at = argv.index("--title")
        return argv[at + 1]

    def _prepare(self, argv: list[str], cwd: Any) -> SimpleNamespace:
        if self.mode == "prepare-refusal":
            return SimpleNamespace(returncode=1, stdout="", stderr="prepare refused: bad source")
        if self.mode == "prepare-unparsable":
            return SimpleNamespace(returncode=0, stdout="not json", stderr="")
        target = Path(cwd) / "docs" / "sdlc-issue-drafts"
        target.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() else "-" for c in self._title(argv).lower())[:40]
        draft = target / f"2000-01-01-{slug}.md"
        draft.write_text(
            "---\ntitle: canned\nrepo: r\ntype: defect\nteam: asgard\n"
            "project: operations\nstatus: Discovering\n---\n\n# canned\n",
            encoding="utf-8",
        )
        draft.with_suffix(".json").write_text(
            json.dumps({"state": "blocked", "approval_state": None}), encoding="utf-8"
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"draft": str(draft.relative_to(cwd)),
                               "sidecar": str(draft.with_suffix(".json").relative_to(cwd)),
                               "readiness": {"passed": False}}),
            stderr="",
        )

    def _create(self, argv: list[str], cwd: Any) -> SimpleNamespace:
        draft = Path(argv[argv.index("create-prepared") + 1])
        sidecar = draft.with_suffix(".json")
        if self.mode == "partial-create":
            sidecar.write_text(
                json.dumps({"state": "post_create_pending",
                            "created_issue_number": self.number}), encoding="utf-8"
            )
            return SimpleNamespace(
                returncode=1, stdout="",
                stderr=f"Created issue https://example.invalid/i/{self.number}, "
                       "but post-create steps failed: board-add down")
        if self.mode in ("create-refusal", "create-no-number"):
            return SimpleNamespace(
                returncode=1, stdout=json.dumps({"created": False}),
                stderr="Prepared issue has blocking readiness gaps")
        payload = {"state": "created", "created_issue_number": self.number,
                   "created_issue_url": f"https://example.invalid/i/{self.number}"}
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"created": True, "number": self.number,
                               "url": payload["created_issue_url"],
                               "mapping_pr_url": None}),
            stderr="")


class FakeGh:
    """``gh pr comment``: records argv, prints a URL. ``fail`` refuses."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, argv: Any, cwd: Any = None) -> SimpleNamespace:
        self.calls.append(list(argv))
        if self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr="oh no")
        return SimpleNamespace(
            returncode=0, stdout="https://example.invalid/o/r/pull/7#issuecomment-1\n",
            stderr="")


def _answers(record: Path, answers: dict[str, Any], mc: FakeMissionControl,
             envelope: str = "envelope.json", timeout: bool = False,
             profile: str = "leave") -> list[str]:
    return review_state.do_answers(
        record, None, None, answers, timeout, _envelope(envelope),
        profile, FAKE_MC, mc,
    )


def _document(staged: dict[str, Path], record: str = "record",
              envelope: str = "envelope.json") -> dict[str, Any]:
    return review_state.build_document(_record(staged[record]), _envelope(envelope))


# ---------------------------------------------------------------------------
# Render: one document, two prints
# ---------------------------------------------------------------------------


def test_render_json_carries_every_block_behind_the_version_token(
    staged: dict[str, Path],
) -> None:
    document = _document(staged)
    assert document["schema"] == "review_state.v1"
    assert [(lens["lens"], lens["grade"], lens["blocking"], lens["fix_later"])
            for lens in document["lenses"]] == [
        ("correctness", "D", 1, 2),
        ("security", "D", 1, 3),
        ("testing", "A", 0, 0),
        ("architecture-maintainability", "A", 0, 0),
    ]
    assert len(document["merge_blocking"]) == 2
    assert document["pending_choices"][0] == "merge-blocking"
    assert len(document["pending_choices"]) == 1 + 5
    assert document["where_to_look"][0]["state"] == "answered"
    assert document["where_to_look"][1]["state"] == "cleared"
    assert document["tools"]["ran"]["semgrep"] == "1.0.0"
    assert "muter" in document["tools"]["missing_notice"]
    assert document["cost"]["tokens_in"] == 6000
    assert document["unattended"] is False


def test_render_markdown_lists_the_same_lenses_items_and_choices(
    staged: dict[str, Path],
) -> None:
    import re

    document = _document(staged)
    markdown = review_state.render_markdown(document)
    assert sorted(lens["lens"] for lens in document["lenses"]) == sorted(
        re.findall(r"^\| ([a-z-]+) \|", markdown, re.M)
    )
    assert sorted(f["id"] for f in document["findings"]) == sorted(
        set(re.findall(r"rf:[0-9a-f]{32}", markdown))
    )
    questions = [line for line in markdown.splitlines() if re.match(r"^Q\d+\.", line)]
    assert len(questions) == len(document["pending_choices"])
    for key in document["pending_choices"]:
        assert f"(answer: {key})" in markdown


def test_render_marks_disputes_disagreements_and_unconfirmed_with_both_picks(
    staged: dict[str, Path],
) -> None:
    document = _document(staged)
    assert len(document["disputes"]) == 1
    assert document["consequence_disagreements"] == [
        {"id": document["consequence_disagreements"][0]["id"],
         "llm": "wrong-result-reported-as-success", "jev": "misleads-a-person"}
    ]
    assert len(document["unconfirmed"]) == 1
    markdown = review_state.render_markdown(document)
    assert "dispute" in markdown and "disagreement" in markdown and "unconfirmed" in markdown
    assert "wrong-result-reported-as-success" in markdown
    assert "misleads-a-person" in markdown


def test_render_round_deltas_name_new_and_cleared_blocking(
    staged: dict[str, Path],
) -> None:
    document = _document(staged)
    by_round = {entry["round"]: entry for entry in document["rounds"]}
    assert len(by_round[1]["new_blocking"]) == 2
    assert len(by_round[2]["new_blocking"]) == 1
    assert len(by_round[2]["cleared_blocking"]) == 1
    assert len(by_round[3]["new_blocking"]) == 1
    assert len(by_round[3]["cleared_blocking"]) == 1


def test_render_without_runs_is_schema_plus_empty_lists(staged: dict[str, Path]) -> None:
    raw = _record(staged["record"])
    raw["review_cycles"] = []
    document = review_state.build_document(raw, _envelope())
    assert document["schema"] == "review_state.v1"
    assert document["pending_choices"] == [] and document["lenses"] == []
    assert document["rounds"] == [] and document["findings"] == []
    assert "No questions are pending." in review_state.render_markdown(document)


def test_render_missing_setup_notice_still_renders(staged: dict[str, Path]) -> None:
    raw = _record(staged["record"])
    del raw["admission"]["setup_notice"]
    document = review_state.build_document(raw, _envelope())
    assert document["tools"]["missing_notice"] is None
    assert "No tools are missing." in review_state.render_markdown(document)


def test_envelope_validation_refuses_what_capture_would_never_write() -> None:
    good = {"schema_version": 1, "run_mode": "attended",
            "ceremony_gates": {"merge": "gate"}}
    assert review_state.validate_envelope(dict(good), "e") == {
        "run_mode": "attended", "merge": "gate"}
    for bad, why in [
        ({"run_mode": "attended", "extra": 1}, "unknown"),
        ({"schema_version": 2, "run_mode": "attended"}, "schema_version"),
        ({"run_mode": "sometimes"}, "run_mode"),
        ({"run_mode": "attended", "ceremony_gates": {"merge": "maybe"}}, "merge"),
        ({"run_mode": "attended", "ceremony_gates": []}, "ceremony_gates"),
        ("not an object", "object"),
    ]:
        with pytest.raises(review_state.ReviewStateError, match=why):
            review_state.validate_envelope(bad, "e")


def test_envelope_extraction_needs_exactly_one_fenced_block() -> None:
    block = '```intent-envelope\n{"run_mode": "attended"}\n```'
    assert review_state.extract_envelope_from_body(f"# t\n\n{block}\n", "b") == {
        "run_mode": "attended", "merge": "gate"}
    for body, why in [
        ("no block here", "no intent-envelope block"),
        (f"{block}\n{block}", "2 intent-envelope blocks"),
        ("```intent-envelope\n{\"a\": 1}\n", "unterminated"),
    ]:
        with pytest.raises(review_state.ReviewStateError, match=why):
            review_state.extract_envelope_from_body(body, "b")


# ---------------------------------------------------------------------------
# Answers: recorded only here, refusals unrecorded
# ---------------------------------------------------------------------------


def _guard_id(staged: dict[str, Path]) -> str:
    for finding in _newest_findings(staged["record"]):
        if review_state.is_guard(finding):
            return str(finding["id"])
    raise AssertionError("the fixture carries no guard item")


def test_answers_record_leave_fix_now_and_the_merge_decision(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    ids = [i for i in _fix_later_ids(staged["record"]) if i != _guard_id(staged)]
    lines = _answers(staged["record"], {
        f"fix-later:{ids[0]}": "leave",
        f"fix-later:{ids[1]}": "fix-now",
        "merge-blocking": {"decision": "merge-with-reason", "reason": "ship it"},
    }, mc)
    assert _outcome_of(staged["record"], ids[0]) == {"outcome": "left"}
    assert _outcome_of(staged["record"], ids[1]) == {"outcome": "fixed-now"}
    entries = [e for e in _record(staged["record"])["review_cycles"]
               if isinstance(e, dict) and e.get("loop") == "merge_confirmation"]
    assert len(entries) == 1
    assert entries[0]["decision"] == "merge-with-reason"
    assert entries[0]["reason"] == "ship it"
    assert len(entries[0]["blocking"]) == 2
    assert any("filed #412" in line for line in lines)  # the guard filed itself


def test_answers_stop_card_records_without_a_reason(staged: dict[str, Path]) -> None:
    _answers(staged["record"], {"merge-blocking": {"decision": "stop-card"}},
             FakeMissionControl())
    entries = [e for e in _record(staged["record"])["review_cycles"]
               if isinstance(e, dict) and e.get("loop") == "merge_confirmation"]
    assert entries[0]["decision"] == "stop-card"
    assert "reason" not in entries[0]


def test_answers_refusals_name_the_key_and_change_no_bytes(
    staged: dict[str, Path],
) -> None:
    blocking = next(f["id"] for f in _newest_findings(staged["record"])
                    if f.get("severity") == "blocks")
    cases = [
        ({"no-such-item": "leave"}, "no-such-item"),
        ({f"fix-later:{blocking}": "leave"}, blocking),
        ({"merge-blocking": {"decision": "merge-with-reason", "reason": ""}},
         "no reason"),
        ({"merge-blocking": {"decision": "merge-with-reason"}}, "no reason"),
        ({"merge-blocking": {"decision": "merge-eventually"}}, "merge-eventually"),
        ({"merge-blocking": {"decision": "stop-card", "extra": 1}}, "unknown fields"),
        ({"merge-blocking": "yes"}, "must be an object"),
    ]
    for answers, why in cases:
        before = _sha(staged["record"])
        with pytest.raises(review_state.ReviewStateError) as excinfo:
            review_state.do_answers(
                staged["record"], None, None, answers, False, _envelope(),
                "leave", FAKE_MC, FakeMissionControl())
        assert why in str(excinfo.value)
        assert _sha(staged["record"]) == before, why
    record_text = staged["record"].read_text(encoding="utf-8")
    assert "no-such-item" not in record_text


def test_answers_rejects_a_malformed_file_before_reading_the_record(
    staged: dict[str, Path],
) -> None:
    for payload, why in [
        ([], "object"),
        ({"answers": [], "pane_timeout": False}, "not an object"),
        ({"answers": {}, "pane_timeout": "yes"}, "pane_timeout"),
        ({"answers": {}, "surprise": 1}, "unknown fields"),
    ]:
        before = _sha(staged["record"])
        with pytest.raises(review_state.ReviewStateError, match=why):
            review_state.normalize_answers(payload, "f")
        assert _sha(staged["record"]) == before
    broken = staged["record"].parent / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    with pytest.raises(review_state.ReviewStateError, match="not valid JSON"):
        review_state.load_answers_file(str(broken))
    with pytest.raises(review_state.ReviewStateError, match="no answers"):
        review_state.load_answers_file(str(staged["record"].parent / "missing.json"))


def test_answers_contradiction_is_refused_and_repeats_are_idempotent(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    key = f"fix-later:{[i for i in _fix_later_ids(staged['record']) if i != _guard_id(staged)][0]}"
    _answers(staged["record"], {key: "leave"}, mc)
    before = _sha(staged["record"])
    with pytest.raises(review_state.ReviewStateError, match="already recorded"):
        _answers(staged["record"], {key: "fix-now"}, mc)
    assert _sha(staged["record"]) == before
    calls = len(mc.calls)
    _answers(staged["record"], {key: "leave"}, mc)
    assert len(mc.calls) == calls  # the repeat filed nothing more


def test_answers_merge_decision_disagrees_loudly(staged: dict[str, Path]) -> None:
    mc = FakeMissionControl()
    _answers(staged["record"], {"merge-blocking": {"decision": "stop-card"}}, mc)
    with pytest.raises(review_state.ReviewStateError, match="already recorded"):
        _answers(staged["record"],
                 {"merge-blocking": {"decision": "merge-with-reason", "reason": "x"}}, mc)
    lines = _answers(staged["record"], {"merge-blocking": {"decision": "stop-card"}}, mc)
    assert any("already recorded" in line for line in lines)


def test_answers_timeout_with_answers_is_refused_unrecorded(
    staged: dict[str, Path],
) -> None:
    key = f"fix-later:{_fix_later_ids(staged['record'])[0]}"
    before = _sha(staged["record"])
    with pytest.raises(review_state.ReviewStateError, match="pane_timeout"):
        _answers(staged["record"], {key: "leave"}, FakeMissionControl(), timeout=True)
    assert _sha(staged["record"]) == before


def test_answers_reader_isolation_and_spore_count(
    staged: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    mc = FakeMissionControl()
    _answers(staged["record"], {"merge-blocking": {"decision": "stop-card"}}, mc)
    record = run_record.from_dict(_record(staged["record"]), path="t", warn=None)
    assert run_status.latest_review(record, loop="code_review") is None
    assert review_state.review_runs(record) != []
    store = tmp_path / "store"
    store.mkdir()
    shutil.copy(staged["record"], store / "issue-164.json")
    # The live sys.modules copy: other test modules reload run_record, and the
    # spore's call-time import sees whichever copy is current (the
    # test_plan_review.py convention).
    monkeypatch.setattr(sys.modules["run_record"], "resolve_store_root", lambda *a, **k: store)
    frozen = saga_spore.freeze_run_record(tmp_path, {"saga_id": "issue-164"})
    assert frozen is not None and frozen["review_cycles"] == 0


def test_answers_concurrent_usage_write_survives(staged: dict[str, Path]) -> None:
    record = staged["record"]
    key = f"fix-later:{[i for i in _fix_later_ids(record) if i != _guard_id(staged)][0]}"
    with run_record.file_lock(record):
        loaded = review_state.load_record_file(record)
        loaded.units.append({"id": "U9", "usage": {"entries": []}})
        review_state.save_record_file(record, loaded)
    _answers(record, {key: "leave"}, FakeMissionControl())
    assert any(row.get("id") == "U9" for row in _record(record)["units"])


# ---------------------------------------------------------------------------
# Filing: prepare, then create, never twice
# ---------------------------------------------------------------------------


def _plain_id(staged: dict[str, Path]) -> str:
    return next(i for i in _fix_later_ids(staged["record"]) if i != _guard_id(staged))


def test_filing_runs_prepare_then_create_and_records_the_number(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    key = f"fix-later:{_plain_id(staged)}"
    _answers(staged["record"], {key: "file-as-issue"}, mc)
    assert _outcome_of(staged["record"], _plain_id(staged)) == {
        "outcome": "filed", "issue": 412}
    verbs = [call[0][call[0].index("issue") + 1] for call in mc.calls]
    assert verbs.count("prepare") >= 1 and verbs.count("create-prepared") >= 1
    prepare = next(call[0] for call in mc.calls if "prepare" in call[0])
    assert prepare[2:5] == ["--format", "json", "issue"]
    assert "--skip-approval" in next(call[0] for call in mc.calls if "create-prepared" in call[0])
    assert all(call[1] is not None for call in mc.calls)  # a temp working directory


def test_filing_real_prepare_offline_passes_readiness(
    staged: dict[str, Path], tmp_path: Path,
) -> None:
    findings = [f for f in _newest_findings(staged["record"]) if f["id"] == _guard_id(staged)]
    title, body = review_state.defect_body(
        findings, repo="infiquetra-agent-plugins", card=164, revision="0" * 40)
    mc = review_state.resolve_mission_control()
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / "body.md").write_text(body, encoding="utf-8")
    prepared = review_state._completed(
        [sys.executable, str(mc), "--format", "json", "issue", "prepare",
         "--repo", "infiquetra-agent-plugins", "--type", "defect", "--team", "asgard",
         "--project", "operations", "--title", title, "--status", "Discovering",
         "--risk", "high", "--source-file", "body.md"],
        cwd=workdir,
    )
    assert prepared.returncode == 0, prepared.stderr
    draft = workdir / json.loads(prepared.stdout)["draft"]
    review_state._add_stage(draft)
    import importlib.util as _ilu

    spec = _ilu.spec_from_file_location("sdlc_manager_probe", mc)
    assert spec is not None and spec.loader is not None
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    readiness = module._readiness_for_prepared_issue(module._read_prepared_issue(draft))
    assert readiness.passed, readiness.blocking_gaps


def test_filing_partial_creation_records_and_never_retries(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl(mode="partial-create", number=777)
    key = f"fix-later:{_plain_id(staged)}"
    _answers(staged["record"], {key: "file-as-issue"}, mc)
    assert _outcome_of(staged["record"], _plain_id(staged)) == {
        "outcome": "filed", "issue": 777}
    calls = len(mc.calls)
    _answers(staged["record"], {key: "file-as-issue"}, mc)
    assert len(mc.calls) == calls


def test_filing_failures_refuse_that_answer_unrecorded(staged: dict[str, Path]) -> None:
    for mode in ("prepare-refusal", "prepare-unparsable", "create-refusal", "create-no-number"):
        record = staged["record"].parent / f"record-{mode}.json"
        shutil.copy(staged["record"], record)
        mc = FakeMissionControl(mode=mode)
        key = f"fix-later:{_plain_id(staged)}"
        with pytest.raises(review_state.ReviewStateError, match="mission-control"):
            _answers(record, {key: "file-as-issue"}, mc)
        assert _outcome_of(record, _plain_id(staged)) is None


# ---------------------------------------------------------------------------
# The security guard
# ---------------------------------------------------------------------------


def test_guard_files_a_traced_harm_attended_and_unattended(
    staged: dict[str, Path],
) -> None:
    for envelope in ("envelope.json", "unattended.json"):
        record = staged["record"].parent / f"record-{envelope}.json"
        shutil.copy(staged["record"], record)
        mc = FakeMissionControl()
        _answers(record, {}, mc, envelope=envelope)
        assert _outcome_of(record, _guard_id(staged)) == {
            "outcome": "filed", "issue": 412}
        assert mc.calls, envelope


def test_guard_skips_what_the_operator_chose_to_fix_now(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    _answers(staged["record"], {f"fix-later:{_guard_id(staged)}": "fix-now"}, mc)
    assert mc.calls == []
    assert _outcome_of(staged["record"], _guard_id(staged)) == {"outcome": "fixed-now"}


def test_guard_upgrades_a_left_item_to_filed(staged: dict[str, Path]) -> None:
    _answers(staged["record"], {f"fix-later:{_guard_id(staged)}": "leave"},
             FakeMissionControl())
    assert _outcome_of(staged["record"], _guard_id(staged)) == {
        "outcome": "filed", "issue": 412}


def test_guard_leaves_reproduced_blocking_items_alone(staged: dict[str, Path]) -> None:
    _answers(staged["record"], {}, FakeMissionControl())
    for finding in _newest_findings(staged["record"]):
        if finding.get("severity") == "blocks":
            assert finding.get("merge_outcome") is None


# ---------------------------------------------------------------------------
# Unattended: the guard files, nothing else does
# ---------------------------------------------------------------------------


def test_unattended_envelope_files_only_guard_items(staged: dict[str, Path]) -> None:
    mc = FakeMissionControl()
    key = f"fix-later:{_plain_id(staged)}"
    _answers(staged["record"], {key: "file-as-issue"}, mc, envelope="unattended.json")
    assert _outcome_of(staged["record"], _plain_id(staged)) == {
        "outcome": "left", "reason": "unattended"}
    assert _outcome_of(staged["record"], _guard_id(staged))["outcome"] == "filed"
    creates = [c for c in mc.calls if "create-prepared" in c[0]]
    assert len(creates) == 1  # the guard's only


def test_unattended_timeout_with_empty_answers_files_only_guard_items(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    before = _sha(staged["record"])
    lines = _answers(staged["record"], {}, mc, timeout=True)
    assert _sha(staged["record"]) != before  # the guard's filing landed
    assert _outcome_of(staged["record"], _guard_id(staged))["outcome"] == "filed"
    assert all("guard" in line or "filed" in line for line in lines)


def test_unattended_merge_wait_follows_the_gate_and_the_round_rules(
    staged: dict[str, Path],
) -> None:
    gate = review_state.merge_display(
        review_state.review_runs(_record(staged["record"])), _envelope())
    assert gate == {"waiting": True, "reason": gate["reason"]} and "operator" in gate["reason"]
    auto_clear = review_state.merge_display(
        review_state.review_runs(_record(staged["clear"])), _envelope("unattended.json"))
    assert auto_clear["waiting"] is False
    auto_limit = review_state.merge_display(
        review_state.review_runs(_record(staged["record"])), _envelope("unattended.json"))
    assert auto_limit["waiting"] is True and "round limit" in auto_limit["reason"]
    early = [{"round": 1, "merge": {"blocking": ["a"]}}, {"round": 2, "merge": {"blocking": ["a"]}}]
    assert review_state.merge_display(early, _envelope("unattended.json"))["waiting"] is True
    assert review_state.merge_display(
        review_state.review_runs(_record(staged["clear"])), None)["waiting"] is True


def test_unattended_file_default_bundle_never_files(staged: dict[str, Path]) -> None:
    mc = FakeMissionControl()
    _answers(staged["record"], {"merge-blocking": {"decision": "stop-card"}}, mc,
             envelope="unattended.json", profile="file")
    creates = [c for c in mc.calls if "create-prepared" in c[0]]
    assert len(creates) == 1  # the guard's only; no bundle


# ---------------------------------------------------------------------------
# The profile default
# ---------------------------------------------------------------------------


def test_profile_default_reads_leave_file_or_absent(tmp_path: Path) -> None:
    missing = tmp_path / "absent.json"
    assert review_state.load_profile_default(missing) == "leave"
    for value in ("leave", "file"):
        profile = tmp_path / f"{value}.json"
        profile.write_text(json.dumps({"schema": "repository_profile.v1",
                                       "fix_later_unattended_default": value}),
                           encoding="utf-8")
        assert review_state.load_profile_default(profile) == value
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"fix_later_unattended_default": "sometimes"}), encoding="utf-8")
    with pytest.raises(review_state.ReviewStateError, match="fix_later_unattended_default"):
        review_state.load_profile_default(bad)


def test_profile_file_default_bundles_leftovers_once_at_confirmation(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    plain = _plain_id(staged)
    _answers(staged["record"], {
        f"fix-later:{plain}": "leave",
        "merge-blocking": {"decision": "merge-with-reason", "reason": "ship"},
    }, mc, profile="file")
    bundled = [f for f in _newest_findings(staged["record"])
               if (f.get("merge_outcome") or {}).get("outcome") == "filed"]
    assert len(bundled) >= 2  # the leftover plus the guard item
    numbers = {(f["merge_outcome"] or {}).get("issue") for f in bundled}
    assert numbers == {412}
    calls = len(mc.calls)
    _answers(staged["record"], {
        "merge-blocking": {"decision": "merge-with-reason", "reason": "ship"},
    }, mc, profile="file")
    assert len(mc.calls) == calls


def test_profile_partial_answers_do_not_bundle(staged: dict[str, Path]) -> None:
    mc = FakeMissionControl()
    _answers(staged["record"], {f"fix-later:{_plain_id(staged)}": "leave"}, mc, profile="file")
    creates = [c for c in mc.calls if "create-prepared" in c[0]]
    assert len(creates) == 1  # the guard's only
    leftovers = [f for f in _newest_findings(staged["record"])
                 if f.get("merge_outcome") is None and f.get("severity") == "fix-later"]
    assert leftovers


def test_profile_empty_answers_bundle_at_an_attended_confirmation(
    staged: dict[str, Path],
) -> None:
    mc = FakeMissionControl()
    record = staged["clear"]
    _answers(record, {}, mc, profile="file")
    for finding in _newest_findings(record):
        if finding.get("severity") == "fix-later":
            assert (finding.get("merge_outcome") or {}).get("outcome") == "filed"


# ---------------------------------------------------------------------------
# The ownership lane: saga files nothing itself
# ---------------------------------------------------------------------------


def _boundary_violations(text: str) -> list[str]:
    """Bare issue-creating commands: every mention needs a negation window."""
    import re

    bad = []
    for match in re.finditer(r"gh issue create", text):
        window = text[max(0, match.start() - 60): match.start()]
        if not re.search(r"\b(not|never|no)\b", window, re.IGNORECASE):
            bad.append(text[max(0, match.start() - 50): match.end() + 30])
    return bad


def test_ownership_saga_files_no_issue_itself() -> None:
    script = (SCRIPTS / "review_state.py").read_text(encoding="utf-8")
    assert "gh issue create" not in script
    for skill in ("code-review", "work"):
        text = (SAGA / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert _boundary_violations(text) == [], skill
    seeded = script + "\n# then run gh issue create --repo o/r --title x --body y\n"
    assert _boundary_violations(seeded) != []  # the seeded bare command fails


# ---------------------------------------------------------------------------
# Publication: one comment per round, the checklist on the final one
# ---------------------------------------------------------------------------


def test_publish_posts_exactly_one_comment_and_never_a_review(
    staged: dict[str, Path],
) -> None:
    gh = FakeGh()
    url = review_state.do_publish(_record(staged["record"]), 1, "7", "o/r", gh)
    assert url.startswith("https://")
    assert len(gh.calls) == 1
    assert gh.calls[0][1:4] == ["pr", "comment", "7"]
    assert "review" not in gh.calls[0]
    body = gh.calls[0][gh.calls[0].index("--body") + 1]
    assert "saga:fix-later-checklist" not in body
    assert "- [ ]" not in body


def test_publish_final_carries_one_checkbox_per_fix_later_item(
    staged: dict[str, Path],
) -> None:
    gh = FakeGh()
    review_state.do_publish(_record(staged["record"]), 3, "7", "o/r", gh)
    body = gh.calls[0][gh.calls[0].index("--body") + 1]
    assert body.splitlines()[0] == "<!-- saga:fix-later-checklist -->"
    boxes = [line[6:41] for line in body.splitlines() if line.startswith("- [ ] rf:")]
    assert boxes == sorted(_fix_later_ids(staged["record"]))


def test_publish_final_round_detection(staged: dict[str, Path]) -> None:
    runs = review_state.review_runs(_record(staged["record"]))
    assert review_state.is_final_round(runs, 1) is False
    assert review_state.is_final_round(runs, 3) is True
    clear = review_state.review_runs(_record(staged["clear"]))
    assert review_state.is_final_round(clear, 1) is True  # all clear ends it
    early = [{"round": 1, "merge": {"allowed": False, "blocking": ["a"]}},
             {"round": 2, "merge": {"allowed": False, "blocking": ["a"]}}]
    assert review_state.is_final_round(early, 2) is True
    with pytest.raises(review_state.ReviewStateError, match="no recorded round 9"):
        review_state.is_final_round(runs, 9)


def test_publish_failure_records_nothing(staged: dict[str, Path]) -> None:
    before = _sha(staged["record"])
    with pytest.raises(review_state.ReviewStateError, match="could not publish"):
        review_state.do_publish(_record(staged["record"]), 1, "7", "o/r", FakeGh(fail=True))
    assert _sha(staged["record"]) == before
    with pytest.raises(review_state.ReviewStateError, match="no recorded round 9"):
        review_state.do_publish(_record(staged["record"]), 9, "7", "o/r", FakeGh())



