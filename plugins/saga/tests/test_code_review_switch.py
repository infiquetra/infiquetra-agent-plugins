"""The /code-review cutover to the review command, with its round and merge rules (issue #161).

Canned answers only: every case builds C1 review runs with ``review_records.build_run`` and drives
the pure round and merge rules in ``review_state.py``. Mission-control arrives as an injected fake
runner, so nothing here reaches the network, ``gh`` or a sibling checkout.

The deletion invariants at the top are the card's acceptance greps, written as tests. They fail
until the old review is gone; every behavior case below them binds to the interfaces in
``spec-161-interfaces.md``.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
SCRIPTS = SAGA / "scripts"
FIXTURES = SAGA / "tests" / "fixtures" / "review_records" / "valid"

# The retired names are built from parts so that the acceptance greps, which scan every file under
# ``plugins``, never match this file.
LENS_ROLE = "lens" + "-reviewer"
LENS_ROLE_SNAKE = "lens" + "_reviewer"
EXPERT_REPAIR = "expert" + "_repair_implementer"
OLD_SCRIPTS = ("review_" + "roster", "review_" + "consensus", "review_" + "result")


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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network call in a test that must not make one")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ---------------------------------------------------------------------------
# The deletion invariants (the card's acceptance greps)
# ---------------------------------------------------------------------------

_SKIPPED_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _text_files(*roots: Path) -> Iterator[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for directory, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in _SKIPPED_DIRS]
            for name in filenames:
                yield Path(directory) / name


def _files_containing(needles: tuple[str, ...], *roots: Path, skip: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    for path in _text_files(*roots):
        if path.name in skip:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(needle in text for needle in needles):
            found.append(path.relative_to(ROOT).as_posix())
    return sorted(found)


def test_no_old_review_script_name_remains_in_saga_sources_or_the_port() -> None:
    roots = (
        SAGA / "scripts",
        SAGA / "skills",
        SAGA / "com.infiquetra.claude",
        ROOT / "ports" / "saga.json",
    )
    assert _files_containing(OLD_SCRIPTS, *roots) == []


def test_orchestrate_no_longer_reads_the_second_result_shape() -> None:
    needle = "review_" + "result" + ".v2"
    assert _files_containing((needle,), ROOT / "plugins" / "orchestrate", skip=("CHANGELOG.md",)) == []


def test_the_lens_role_and_the_expert_repair_role_are_gone_from_every_plugin() -> None:
    needles = (LENS_ROLE, LENS_ROLE_SNAKE, EXPERT_REPAIR)
    assert _files_containing(needles, ROOT / "plugins", skip=("CHANGELOG.md",)) == []


@pytest.mark.parametrize(
    "relative",
    [
        "plugins/saga/scripts/review_" + "roster.py",
        "plugins/saga/scripts/review_" + "consensus.py",
        "plugins/saga/scripts/review_" + "result.py",
        "plugins/saga/skills/code-review/references/lens-execution.md",
        "plugins/saga/skills/code-review/references/validator.md",
        "plugins/saga/skills/code-review/references/findings-schema.md",
        "plugins/agent-launcher/roles/" + "lens" + "-reviewer.md",
        "plugins/agent-launcher/roles/expert" + "-repair-implementer.md",
    ],
)
def test_each_deleted_script_reference_and_role_is_absent_on_disk(relative: str) -> None:
    assert not (ROOT / relative).exists()


def test_the_nine_old_review_tests_are_deleted_and_the_new_ones_stay() -> None:
    old = (
        "consensus", "consensus_cycles", "consensus_docs", "dry_run", "judgments",
        "publish", "result", "roster", "seats",
    )
    for name in old:
        assert not (SAGA / "tests" / f"test_review_{name}.py").exists(), name
    for name in ("calibration", "formula", "tools", "command", "state", "records", "checks_runner"):
        assert (SAGA / "tests" / f"test_review_{name}.py").is_file(), name


def test_the_calibration_file_still_runs_no_corpus() -> None:
    calibration = json.loads((SAGA / "references" / "review-calibration.json").read_text(encoding="utf-8"))
    assert calibration["corpus_run"] == "no-run"


# ---------------------------------------------------------------------------
# Review runs built by the real formula, never typed by hand
# ---------------------------------------------------------------------------

_BASE = json.loads((FIXTURES / "review_run.json").read_text(encoding="utf-8"))
_HEAD_A = "b" * 40
_HEAD_B = "c" * 40
_HEAD_C = "d" * 40
ATTENDED_GATE = {"run_mode": "attended", "merge": "gate"}
ATTENDED_AUTO = {"run_mode": "attended", "merge": "auto"}
UNATTENDED_AUTO = {"run_mode": "unattended", "merge": "auto"}
UNATTENDED_GATE = {"run_mode": "unattended", "merge": "gate"}
CARD = 161
REPO = "infiquetra/infiquetra-agent-plugins"


def finding(
    anchor: str,
    *,
    consequence: str = "wrong-result-reported-as-success",
    evidence: str = "reproduced",
    lens: str = "correctness",
    lines: tuple[int, int] = (10, 12),
    path: str = "src/billing/totals.py",
) -> dict[str, Any]:
    """One input finding, identified the way C1 identifies it (never by line)."""
    item = copy.deepcopy(
        json.loads((FIXTURES / "finding.json").read_text(encoding="utf-8"))
    )
    item["lens"] = lens
    item["consequence"] = consequence
    item["consequence_jev"] = consequence
    item["evidence"] = evidence
    item["statement"] = f"{anchor} goes wrong."
    item["location"] = {
        "scope": "lines",
        "file": path,
        "lines": {"start": lines[0], "end": lines[1]},
        "function": "total",
        "anchor": anchor,
    }
    item["proof"] = {"test": "tests/test_totals.py::test_total", "command": "pytest -q", "output": "FAILED"}
    item["id"] = review_records.finding_identity(lens, item["rule"], item["location"])
    return item


def make_run(
    findings: list[dict[str, Any]],
    *,
    round_no: int,
    head: str = _HEAD_A,
    may_block: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A C1 review run: grades, merge answer and stable finding IDs computed by the formula."""
    inputs = {name: copy.deepcopy(_BASE[name]) for name in review_records.RUN_FIELDS if name in _BASE}
    inputs.update(review_records._formula_inputs(_BASE))
    inputs.update(
        {
            "card": CARD,
            "repo": REPO,
            "head": head,
            "round": round_no,
            "findings": findings,
            "measurements": [],
            "builder_records": [],
            "where_to_look": [],
            "may_block": may_block if may_block is not None else {"correctness": {"python": True}},
        }
    )
    inputs.pop("reviewers", None)
    return review_records.build_run(inputs)


def make_record(*cycles: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "run_record.v1",
        "issue": CARD,
        "repo": REPO,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-01T00:00:00Z",
        "admission": {},
        "run_configuration": {},
        "approval_scope": {},
        "roster": [],
        "units": [],
        "review_cycles": [copy.deepcopy(item) for item in cycles],
        "next_step": "code_review",
    }


def store_record(path: Path, record: dict[str, Any]) -> Path:
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def stored(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def blocking_ids(run: dict[str, Any]) -> list[str]:
    return list(run["merge"]["blocking"])


def clear_run(round_no: int = 1, head: str = _HEAD_A) -> dict[str, Any]:
    return make_run([], round_no=round_no, head=head)


def two_blockers(round_no: int, *, head: str = _HEAD_A, shift: int = 0) -> dict[str, Any]:
    return make_run(
        [
            finding("total = round(total)", lines=(10 + shift, 12 + shift)),
            finding("rate = lookup(code)", lines=(30 + shift, 31 + shift)),
        ],
        round_no=round_no,
        head=head,
    )


def one_blocker(anchor: str, round_no: int, *, head: str = _HEAD_A) -> dict[str, Any]:
    return make_run([finding(anchor)], round_no=round_no, head=head)


def fix_later_only(
    round_no: int = 1, head: str = _HEAD_A, anchor: str = "log.debug(total)"
) -> dict[str, Any]:
    """Only fix-later items: a reproduced harm that a person sees, never a block."""
    return make_run(
        [finding(anchor, consequence="misleads-a-person")],
        round_no=round_no,
        head=head,
    )


def data_loss_in_a_report_only_lens(round_no: int, head: str = _HEAD_A) -> dict[str, Any]:
    """Reproduced data loss in a lens the calibration file has not yet allowed to block."""
    return make_run(
        [
            finding(
                "rows.truncate()",
                consequence="data-lost-or-corrupted",
                lens="correctness",
                path="src/store/rows.py",
            )
        ],
        round_no=round_no,
        head=head,
        may_block={"correctness": {"python": False}},
    )


def security_exposure_in_a_report_only_lens(round_no: int, head: str = _HEAD_A) -> dict[str, Any]:
    return make_run(
        [
            finding(
                "token = request.args['token']",
                consequence="security-boundary-crossed",
                lens="security",
                path="src/api/auth.py",
            )
        ],
        round_no=round_no,
        head=head,
        may_block={"security": {"python": False}},
    )


# ---------------------------------------------------------------------------
# What the runs the formula built say (guards for the rules below)
# ---------------------------------------------------------------------------


def test_the_run_builders_produce_the_merge_answers_the_rules_depend_on() -> None:
    assert clear_run()["merge"]["allowed"] is True
    blocked = two_blockers(1)
    assert blocked["merge"]["allowed"] is False and len(blocking_ids(blocked)) == 2
    later = fix_later_only()
    assert later["merge"]["allowed"] is True and later["merge"]["blocking"] == []
    assert [f["severity"] for f in later["findings"]] == ["fix-later"]
    loss = data_loss_in_a_report_only_lens(1)
    assert loss["merge"]["allowed"] is False
    assert len(blocking_ids(loss)) == 1
    exposure = security_exposure_in_a_report_only_lens(1)
    assert exposure["merge"]["allowed"] is False


def test_a_finding_keeps_its_identity_when_its_lines_move() -> None:
    before = two_blockers(1)
    after = two_blockers(2, shift=25)
    assert before["findings"][0]["location"]["lines"] != after["findings"][0]["location"]["lines"]
    assert sorted(blocking_ids(before)) == sorted(blocking_ids(after))


# ---------------------------------------------------------------------------
# Round rules: round_state and merge_display (existing contract, now the switch's rules)
# ---------------------------------------------------------------------------


def test_the_round_limit_is_three() -> None:
    assert review_state.ROUND_LIMIT == 3


def test_the_same_blocking_items_after_their_lines_moved_stop_the_loop_early() -> None:
    runs = [two_blockers(1), two_blockers(2, shift=25)]
    state = review_state.round_state(runs)
    assert state["early_stop"] is True
    assert state["at_limit"] is False
    assert state["deltas"] == [{"round": 2, "new_blocking": [], "cleared_blocking": []}]


def test_a_repair_round_that_clears_one_item_does_not_stop_early() -> None:
    runs = [two_blockers(1), one_blocker("total = round(total)", 2)]
    state = review_state.round_state(runs)
    assert state["early_stop"] is False and state["at_limit"] is False
    [delta] = state["deltas"]
    assert len(delta["cleared_blocking"]) == 1 and delta["new_blocking"] == []


def test_round_three_with_blocking_items_is_at_the_limit() -> None:
    runs = [
        one_blocker("a = 1", 1),
        one_blocker("b = 2", 2),
        one_blocker("c = 3", 3),
    ]
    state = review_state.round_state(runs)
    assert state["at_limit"] is True and state["early_stop"] is False


def test_merge_display_waits_for_the_operator_at_the_limit_whatever_the_envelope_says() -> None:
    runs = [one_blocker("a = 1", 1), one_blocker("b = 2", 2), one_blocker("c = 3", 3)]
    for envelope in (UNATTENDED_AUTO, ATTENDED_AUTO, UNATTENDED_GATE, ATTENDED_GATE):
        assert review_state.merge_display(runs, envelope)["waiting"] is True


def test_merge_display_waits_at_an_early_stop_even_unattended_at_auto() -> None:
    runs = [two_blockers(1), two_blockers(2, shift=7)]
    display = review_state.merge_display(runs, UNATTENDED_AUTO)
    assert display["waiting"] is True
    assert "early stop" in display["reason"]


def test_merge_display_lets_an_unattended_auto_run_merge_once_every_lens_is_at_c_or_better() -> None:
    assert review_state.merge_display([clear_run()], UNATTENDED_AUTO)["waiting"] is False
    assert review_state.merge_display([fix_later_only()], UNATTENDED_AUTO)["waiting"] is False


def test_merge_display_waits_at_gate_and_without_an_envelope() -> None:
    assert review_state.merge_display([clear_run()], UNATTENDED_GATE)["waiting"] is True
    assert review_state.merge_display([clear_run()], ATTENDED_GATE)["waiting"] is True
    assert review_state.merge_display([clear_run()], None)["waiting"] is True


def test_reproduced_data_loss_in_a_report_only_lens_holds_the_merge_at_auto() -> None:
    runs = [data_loss_in_a_report_only_lens(1)]
    assert review_state.merge_display(runs, UNATTENDED_AUTO)["waiting"] is True


def test_reproduced_security_exposure_in_a_report_only_lens_holds_the_merge_at_auto() -> None:
    runs = [security_exposure_in_a_report_only_lens(1)]
    assert review_state.merge_display(runs, UNATTENDED_AUTO)["waiting"] is True


# ---------------------------------------------------------------------------
# The one entry point: review_state.next_review_action
# ---------------------------------------------------------------------------


def action(record: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return review_state.next_review_action(record, **kwargs)


def test_a_card_with_no_review_runs_a_full_branch_review_at_round_one() -> None:
    result = action(make_record())
    assert (result["action"], result["round"], result["scope"]) == ("run-review", 1, "full-branch")


def test_every_lens_at_c_or_better_goes_to_merge_without_asking_for_more_rounds() -> None:
    record = make_record(clear_run())
    for run in (clear_run(), fix_later_only()):
        record = make_record(run)
        assert action(record, envelope=UNATTENDED_AUTO)["action"] == "auto-merge"
    assert action(make_record(clear_run()), envelope=UNATTENDED_AUTO)["round"] == 1
    assert action(record, envelope=UNATTENDED_AUTO)["waiting"] is False


def test_an_attended_run_confirms_the_merge_even_at_auto() -> None:
    result = action(make_record(clear_run()), envelope=ATTENDED_AUTO)
    assert result["action"] == "confirm-merge" and result["waiting"] is True


def test_a_gate_run_confirms_the_merge_even_when_unattended() -> None:
    result = action(make_record(clear_run()), envelope=UNATTENDED_GATE)
    assert result["action"] == "confirm-merge" and result["waiting"] is True


def test_a_missing_envelope_confirms_the_merge() -> None:
    result = action(make_record(clear_run()))
    assert result["action"] == "confirm-merge" and result["waiting"] is True


def test_fix_later_choices_never_hold_the_merge() -> None:
    record = make_record(fix_later_only())
    assert action(record, envelope=UNATTENDED_AUTO)["action"] == "auto-merge"
    assert action(record, envelope=ATTENDED_GATE)["action"] == "confirm-merge"


@pytest.mark.parametrize("round_no", [1, 2])
def test_blocking_items_in_round_one_or_two_trigger_a_repair_of_only_the_repaired_code(
    round_no: int,
) -> None:
    runs = [one_blocker("a = 1", n) for n in range(1, round_no)]
    runs.append(one_blocker("b = 2" if round_no == 2 else "a = 1", round_no))
    result = action(make_record(*runs), envelope=ATTENDED_GATE)
    assert result["action"] == "repair"
    assert result["round"] == round_no + 1
    assert result["scope"] == "repaired-only"
    assert result["blocking"]


def test_a_repair_round_that_leaves_the_same_blocking_items_stops_early() -> None:
    record = make_record(two_blockers(1), two_blockers(2, shift=25, head=_HEAD_B))
    result = action(record, envelope=ATTENDED_GATE)
    assert result["action"] == "await-operator"
    assert result["early_stop"] is True and result["at_limit"] is False
    assert result["round"] == 2


def test_round_three_with_blocking_items_stops_at_the_limit() -> None:
    record = make_record(
        one_blocker("a = 1", 1), one_blocker("b = 2", 2), one_blocker("c = 3", 3)
    )
    result = action(record, envelope=ATTENDED_GATE)
    assert result["action"] == "await-operator"
    assert result["at_limit"] is True and result["early_stop"] is False
    assert result["round"] == 3


def test_there_is_no_round_four() -> None:
    record = make_record(
        one_blocker("a = 1", 1), one_blocker("b = 2", 2), one_blocker("c = 3", 3)
    )
    for envelope in (None, ATTENDED_GATE, UNATTENDED_AUTO):
        kwargs = {} if envelope is None else {"envelope": envelope}
        result = action(record, **kwargs)
        assert result["action"] != "repair"
        assert result["round"] <= review_state.ROUND_LIMIT


@pytest.mark.parametrize("stop", ["early", "limit"])
def test_an_unattended_auto_run_never_merges_past_an_early_stop_or_the_limit(stop: str) -> None:
    if stop == "early":
        record = make_record(two_blockers(1), two_blockers(2, shift=3))
    else:
        record = make_record(
            one_blocker("a = 1", 1), one_blocker("b = 2", 2), one_blocker("c = 3", 3)
        )
    result = action(record, envelope=UNATTENDED_AUTO)
    assert result["action"] == "await-operator"
    assert result["action"] not in ("auto-merge", "ready-to-merge", "confirm-merge")
    runs = review_state.review_runs(record)
    assert review_state.merge_display(runs, UNATTENDED_AUTO)["waiting"] is True


def test_a_fix_now_round_does_not_count_against_the_limit() -> None:
    """Round 1 left only fix-later items; the operator chose fix now and the branch moved."""
    record = make_record(fix_later_only(1, _HEAD_A))
    result = action(record, envelope=ATTENDED_GATE, current_revision=_HEAD_B)
    assert result["counts_against_limit"] is False
    assert result["round"] == 1
    assert result["scope"] == "repaired-only"


def test_a_stale_review_after_a_blocking_round_counts_as_the_next_round() -> None:
    record = make_record(two_blockers(1))
    result = action(record, envelope=ATTENDED_GATE, current_revision=_HEAD_B)
    assert result["counts_against_limit"] is True
    assert result["round"] == 2
    assert result["scope"] == "repaired-only"


def test_a_review_of_the_current_revision_is_not_stale() -> None:
    record = make_record(clear_run(head=_HEAD_A))
    result = action(record, envelope=UNATTENDED_AUTO, current_revision=_HEAD_A)
    assert result["action"] == "auto-merge"


def test_fix_now_rounds_never_push_a_card_to_the_limit() -> None:
    """Three fix-now rounds leave the card repairable: the blocking counter never moved."""
    record = make_record(
        one_blocker("a = 1", 1),
        fix_later_only(2, _HEAD_B, "b = 2"),
    )
    result = action(record, envelope=ATTENDED_GATE, current_revision=_HEAD_C)
    assert result["counts_against_limit"] is False
    assert result["round"] == 2


def test_reproduced_data_loss_in_a_report_only_lens_is_a_blocking_item_that_cannot_merge() -> None:
    record = make_record(data_loss_in_a_report_only_lens(1))
    result = action(record, envelope=UNATTENDED_AUTO)
    assert result["action"] == "repair"
    assert result["action"] not in ("auto-merge", "confirm-merge", "ready-to-merge")


def test_reproduced_data_loss_at_an_early_stop_says_so() -> None:
    record = make_record(
        data_loss_in_a_report_only_lens(1), data_loss_in_a_report_only_lens(2, _HEAD_B)
    )
    result = action(record, envelope=UNATTENDED_AUTO)
    assert result["action"] == "await-operator"
    assert result["reproduced_critical"] is True


def test_reproduced_security_exposure_at_the_limit_says_so() -> None:
    record = make_record(
        security_exposure_in_a_report_only_lens(1),
        security_exposure_in_a_report_only_lens(2),
        security_exposure_in_a_report_only_lens(3),
    )
    result = action(record, envelope=ATTENDED_GATE)
    assert result["action"] == "await-operator"
    assert result["reproduced_critical"] is True and result["at_limit"] is True


def test_an_ordinary_early_stop_is_not_reproduced_critical() -> None:
    record = make_record(two_blockers(1), two_blockers(2, shift=2))
    assert action(record, envelope=ATTENDED_GATE)["reproduced_critical"] is False


# ---------------------------------------------------------------------------
# A run mid-review at the switch restarts on the new command
# ---------------------------------------------------------------------------

LEGACY_CYCLES = (
    {
        "schema": "review_" + "result" + ".v2",
        "loop": "code_review",
        "unit": "issue-161",
        "cycle": 2,
        "revision": "a" * 40,
        "outcome": "repairs_requested",
        "findings": [{"status": "open"}],
    },
    {"schema": "review_" + "result" + ".v1", "cycle": 1},
)


def test_a_record_with_only_legacy_review_cycles_restarts_the_review_at_round_one() -> None:
    record = make_record(*LEGACY_CYCLES)
    result = action(record, envelope=ATTENDED_GATE)
    assert result["action"] == "restart-review"
    assert result["round"] == 1
    assert result["scope"] == "full-branch"


def test_a_restart_keeps_the_legacy_entries_in_place_and_unread() -> None:
    record = make_record(*LEGACY_CYCLES)
    before = copy.deepcopy(record)
    action(record, envelope=UNATTENDED_AUTO)
    assert record == before
    assert review_state.review_runs(record) == []
    assert len(record["review_cycles"]) == len(LEGACY_CYCLES)


def test_legacy_entries_never_start_the_new_round_counter() -> None:
    record = make_record(*LEGACY_CYCLES)
    assert action(record, envelope=UNATTENDED_AUTO)["round"] == 1
    assert action(record)["round"] == 1


def test_a_legacy_code_review_loop_entry_restarts_even_unattended_at_auto() -> None:
    legacy = {"loop": "code_review", "unit": "u1", "cycle": 3, "outcome": "cycle_cap_best_available"}
    result = action(make_record(legacy), envelope=UNATTENDED_AUTO)
    assert result["action"] == "restart-review"


def test_a_plan_review_entry_does_not_restart_a_code_review() -> None:
    entry = {"loop": "plan_review", "unit": "u1", "round": 1}
    result = action(make_record(entry))
    assert result["action"] == "run-review"


def test_stored_review_runs_beside_legacy_entries_are_read_not_restarted() -> None:
    record = make_record(*LEGACY_CYCLES, clear_run())
    result = action(record, envelope=UNATTENDED_AUTO)
    assert result["action"] == "auto-merge"
    assert len(review_state.review_runs(record)) == 1


# ---------------------------------------------------------------------------
# The operator's way out at an early stop or the limit
# ---------------------------------------------------------------------------


class FakeMissionControl:
    """Mission-control's prepare then create protocol, scripted per call number."""

    def __init__(self, *, fail_create_calls: tuple[int, ...] = (), first_number: int = 500) -> None:
        self.fail_create_calls = fail_create_calls
        self.next_number = first_number
        self.calls: list[list[str]] = []
        self.created_numbers: list[int] = []
        self.create_attempts = 0
        self.titles: list[str] = []

    def __call__(self, argv: Any, cwd: Any = None) -> SimpleNamespace:
        argv = list(argv)
        self.calls.append(argv)
        if "prepare" in argv:
            return self._prepare(argv, Path(cwd))
        return self._create(argv)

    def _prepare(self, argv: list[str], cwd: Path) -> SimpleNamespace:
        title = argv[argv.index("--title") + 1]
        self.titles.append(title)
        folder = cwd / "docs" / "sdlc-issue-drafts"
        folder.mkdir(parents=True, exist_ok=True)
        draft = folder / f"2000-01-01-draft-{len(self.titles)}.md"
        draft.write_text(
            "---\ntitle: canned\nrepo: r\ntype: defect\nteam: asgard\nproject: operations\n"
            "status: Discovering\n---\n\n# canned\n",
            encoding="utf-8",
        )
        draft.with_suffix(".json").write_text(
            json.dumps({"state": "blocked", "approval_state": None}), encoding="utf-8"
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "draft": str(draft.relative_to(cwd)),
                    "sidecar": str(draft.with_suffix(".json").relative_to(cwd)),
                    "readiness": {"passed": False},
                }
            ),
            stderr="",
        )

    def _create(self, argv: list[str]) -> SimpleNamespace:
        self.create_attempts += 1
        if self.create_attempts in self.fail_create_calls:
            return SimpleNamespace(
                returncode=1, stdout=json.dumps({"created": False}), stderr="mission-control is down"
            )
        draft = Path(argv[argv.index("create-prepared") + 1])
        number = self.next_number
        self.next_number += 1
        self.created_numbers.append(number)
        draft.with_suffix(".json").write_text(
            json.dumps({"state": "created", "created_issue_number": number}), encoding="utf-8"
        )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"created": True, "number": number, "url": f"https://example.invalid/i/{number}"}
            ),
            stderr="",
        )


FAKE_MC_SCRIPT = Path("fake-mission-control-for-tests")


def answer(
    record_path: Path,
    answers: dict[str, Any],
    mc: FakeMissionControl,
    *,
    envelope: dict[str, Any] = ATTENDED_GATE,
) -> list[str]:
    return review_state.do_answers(
        record_path, None, None, answers, False, envelope, "leave", FAKE_MC_SCRIPT, mc
    )


def at_the_limit_record() -> dict[str, Any]:
    return make_record(
        two_blockers(1),
        make_run(
            [
                finding("total = round(total)", lines=(10, 12)),
                finding("rate = lookup(code)", lines=(30, 31)),
                finding("extra = 1"),
            ],
            round_no=2,
            head=_HEAD_B,
        ),
        two_blockers(3, head=_HEAD_C, shift=40),
    )


def test_the_merge_choice_is_pending_at_the_limit_and_at_an_early_stop(tmp_path: Path) -> None:
    for record in (at_the_limit_record(), make_record(two_blockers(1), two_blockers(2, shift=9))):
        document = review_state.build_document(record, ATTENDED_GATE)
        assert document["pending_choices"][0] == "merge-blocking"


def test_merge_with_reason_files_every_blocking_item_and_then_the_card_is_ready_to_merge(
    tmp_path: Path,
) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    mc = FakeMissionControl()
    answer(path, {"merge-blocking": {"decision": "merge-with-reason", "reason": "ship the rest"}}, mc)
    blocking = blocking_ids(review_state.review_runs(stored(path))[-1])
    assert len(blocking) == 2
    assert len(mc.created_numbers) == len(blocking)
    result = action(stored(path), envelope=ATTENDED_GATE)
    assert result["action"] == "ready-to-merge"
    assert result["via"] == "operator-merge-with-reason"


def test_stop_card_ends_the_review_without_filing_anything(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    mc = FakeMissionControl()
    answer(path, {"merge-blocking": {"decision": "stop-card"}}, mc)
    assert mc.calls == []
    assert action(stored(path), envelope=ATTENDED_GATE)["action"] == "stopped"


def test_merge_with_reason_needs_a_reason(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    with pytest.raises(review_state.ReviewStateError, match="no reason"):
        answer(path, {"merge-blocking": {"decision": "merge-with-reason", "reason": " "}}, FakeMissionControl())


def test_an_unattended_run_cannot_answer_the_merge_choice_itself(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    mc = FakeMissionControl()
    with pytest.raises(review_state.ReviewStateError, match="unattended"):
        answer(
            path,
            {"merge-blocking": {"decision": "stop-card"}},
            mc,
            envelope=UNATTENDED_AUTO,
        )
    assert mc.calls == []


def test_a_resumed_filing_step_never_files_an_item_twice(tmp_path: Path) -> None:
    """Mission-control fails on the second issue; the rerun files only what is still unfiled."""
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    decision = {"merge-blocking": {"decision": "merge-with-reason", "reason": "ship the rest"}}
    mc = FakeMissionControl(fail_create_calls=(2,))
    with pytest.raises(review_state.ReviewStateError):
        answer(path, decision, mc)
    assert len(mc.created_numbers) == 1
    answer(path, decision, mc)
    assert mc.create_attempts == 3
    assert len(mc.created_numbers) == 2
    assert len(set(mc.created_numbers)) == 2
    answer(path, decision, mc)
    assert mc.create_attempts == 3


def test_answering_the_same_merge_decision_again_files_nothing_more(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    decision = {"merge-blocking": {"decision": "merge-with-reason", "reason": "ship the rest"}}
    mc = FakeMissionControl()
    answer(path, decision, mc)
    attempts = mc.create_attempts
    assert attempts == 2
    answer(path, decision, mc)
    assert mc.create_attempts == attempts


# ---------------------------------------------------------------------------
# A report-only lens with reproduced data loss or security exposure blocks
# ---------------------------------------------------------------------------


def report_only_record(kind: str) -> dict[str, Any]:
    build = (
        data_loss_in_a_report_only_lens
        if kind == "data-loss"
        else security_exposure_in_a_report_only_lens
    )
    return make_record(build(1), build(2, _HEAD_B), build(3, _HEAD_C))


@pytest.mark.parametrize("kind", ["data-loss", "security"])
def test_reproduced_harm_in_a_report_only_lens_blocks_the_merge(kind: str) -> None:
    record = report_only_record(kind)
    run = review_state.review_runs(record)[-1]
    assert run["merge"]["allowed"] is False
    assert len(blocking_ids(run)) == 1
    assert all(grade["may_block"].get("python") is not True for grade in run["lens_grades"])


@pytest.mark.parametrize("kind", ["data-loss", "security"])
def test_merge_with_reason_is_refused_over_reproduced_harm_in_a_report_only_lens(
    tmp_path: Path, kind: str
) -> None:
    path = store_record(tmp_path / "record.json", report_only_record(kind))
    before = path.read_bytes()
    mc = FakeMissionControl()
    with pytest.raises(review_state.ReviewStateError):
        answer(path, {"merge-blocking": {"decision": "merge-with-reason", "reason": "ship it"}}, mc)
    assert path.read_bytes() == before
    assert mc.calls == []


@pytest.mark.parametrize("kind", ["data-loss", "security"])
def test_stop_card_stays_open_over_reproduced_harm_in_a_report_only_lens(
    tmp_path: Path, kind: str
) -> None:
    path = store_record(tmp_path / "record.json", report_only_record(kind))
    answer(path, {"merge-blocking": {"decision": "stop-card"}}, FakeMissionControl())
    assert action(stored(path), envelope=ATTENDED_GATE)["action"] == "stopped"


def test_merge_with_reason_stays_open_over_ordinary_blocking_items(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", at_the_limit_record())
    answer(
        path,
        {"merge-blocking": {"decision": "merge-with-reason", "reason": "known and filed"}},
        FakeMissionControl(),
    )
    assert action(stored(path), envelope=ATTENDED_GATE)["action"] == "ready-to-merge"


# ---------------------------------------------------------------------------
# The record the readers share
# ---------------------------------------------------------------------------


def test_the_stored_record_still_loads_with_legacy_entries_beside_review_runs(tmp_path: Path) -> None:
    path = store_record(tmp_path / "record.json", make_record(*LEGACY_CYCLES, clear_run()))
    loaded = review_state.load_record_file(path)
    assert len(loaded.review_cycles) == len(LEGACY_CYCLES) + 1
    assert len(review_state.review_runs(loaded)) == 1
    assert run_record.to_dict(loaded)["review_cycles"][: len(LEGACY_CYCLES)] == list(LEGACY_CYCLES)
