"""Versioned structured pre-answer carrier — issue #924 (unit U3).

Runtime tests against ``plugins/saga/scripts/plan_pre_answers.py`` (plan KTD5), plus
the rigidity pin on the Phase 0 intake subsection. None of these tests asserts a Plan
question, its wording, or the order of the conversation (R29): the guard is asserted
as the absence of rigid prose shapes in the subsection this unit adds, and as runtime
behaviour — applied and narrated, fall-through on absence, stop on conflict, an unknown
schema refused whole.

Mutation wiring (issue 924's mutation proof):

* removing the conflict stop from the validator fails the invalid-value and
  contradiction tests (they assert the stop and an empty ``applied``, so a fallback to
  any default fails them);
* removing the caller from the outcome fails the caller-recorded test;
* breaking the fence extraction fails every test that carries a block.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "saga"
SCRIPTS_DIR = PLUGIN_ROOT / "scripts"
PLAN_SKILL = PLUGIN_ROOT / "skills" / "plan" / "SKILL.md"

SCHEMA_TOKEN = "plan_pre_answers.v1"


def _load_module(script_name: str) -> ModuleType:
    """Load a script module by file path, registered in ``sys.modules``.

    Registration matters: ``plan_pre_answers.py`` defines a frozen ``@dataclass`` and
    (on Python 3.12+) dataclass processing looks the class's ``__module__`` up in
    ``sys.modules`` while building it — the same convention as
    ``test_saga_plan_save_and_routing.py``.
    """
    name = script_name.removesuffix(".py")
    path = SCRIPTS_DIR / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pre_answers() -> ModuleType:
    return _load_module("plan_pre_answers.py")


def _invocation(carrier: Mapping[str, object]) -> str:
    """A realistic ``/plan`` invocation text carrying the carrier in a fenced block."""
    payload = json.dumps(carrier, indent=2)
    return f"/plan work issue #924 — settle the plan for the carrier contract.\n\n```json\n{payload}\n```\n"


# --- positive: applied and narrated, with the caller ---------------------------------


def test_valid_backend_is_applied_with_its_caller(pre_answers: ModuleType) -> None:
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is None
    assert outcome.applied == {"backend": "inline"}
    # The narration contract (R16): the applied value and the supplying caller are
    # returned together. Dropping the caller from the outcome fails this assertion.
    assert outcome.caller == "orchestrate"


def test_omitted_destination_falls_through_without_stop(pre_answers: ModuleType) -> None:
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is None
    assert "destination" in outcome.omitted
    assert "destination" not in outcome.applied
    assert outcome.applied == {"backend": "inline"}


def test_empty_carrier_is_valid_and_omits_both(pre_answers: ModuleType) -> None:
    outcome = pre_answers.evaluate(_invocation({"schema": SCHEMA_TOKEN}))

    assert outcome.stop is None
    assert outcome.applied == {}
    assert set(outcome.omitted) == {"backend", "destination"}


def test_carrier_is_found_among_unrelated_fenced_blocks(pre_answers: ModuleType) -> None:
    # Inline: the only backend the carrier may apply automatically (operator ruling,
    # review F03) — team-execution/ultracode now stop, covered by their own tests.
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}
    text = (
        "/plan resume issue #924\n\n"
        "Prior state for context:\n\n"
        "```bash\npython3 plugins/saga/scripts/saga.py scan\n```\n\n"
        "The caller's settlement:\n\n"
        f"```json\n{json.dumps(carrier, indent=2)}\n```\n\n"
        "```\nnot json at all\n```\n"
    )

    outcome = pre_answers.evaluate(text)

    assert outcome.stop is None
    assert outcome.applied == {"backend": "inline"}
    assert outcome.caller == "orchestrate"


# --- negative: absence is not an error (R17, R20) ------------------------------------


def test_no_carrier_applies_nothing_and_leaves_everything_to_the_conversation(
    pre_answers: ModuleType,
) -> None:
    # Direct /plan: an issue reference with no carrier. Nothing applied, nothing
    # narrated (no caller), nothing stopped — and no-carrier is NOT conflated with
    # nothing-omitted: every decision field simply follows the normal adaptive
    # conversation (review F36).
    outcome = pre_answers.evaluate("/plan work issue #924 — plan the carrier contract.")

    assert outcome.applied == {}
    assert tuple(outcome.omitted) == pre_answers.DECISION_FIELDS
    assert outcome.stop is None
    assert outcome.caller is None


def test_other_schema_families_are_not_carriers(pre_answers: ModuleType) -> None:
    # Two-case rule (reviews F07/F07a/F07u): a FOREIGN schema family is not a carrier
    # and is ignored — no stop, and the decision fields stay with the conversation.
    text = (
        '/plan work issue #924\n\n```json\n{"schema": "intent.v1", "run_mode": "attended"}\n```\n'
    )

    outcome = pre_answers.evaluate(text)

    assert outcome.applied == {}
    assert tuple(outcome.omitted) == pre_answers.DECISION_FIELDS
    assert outcome.stop is None
    assert outcome.caller is None


# --- negative: conflict stops, never defaults (R18) ----------------------------------


@pytest.mark.parametrize("bad_value", ["claude-cloud", "Team-Execution", 42, None], ids=str)
def test_invalid_backend_stops_and_never_defaults(
    pre_answers: ModuleType, bad_value: object
) -> None:
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": bad_value}

    outcome = pre_answers.evaluate(_invocation(carrier))

    # The stop — and, as important, what does NOT happen: no value is applied, so an
    # invalid supply can never become a silent default. Removing the conflict stop
    # from the validator fails this test.
    assert outcome.stop is not None
    assert "backend" in outcome.stop
    assert outcome.applied == {}
    assert outcome.caller is None


def test_contradiction_stops_and_prefers_neither_side(pre_answers: ModuleType) -> None:
    # Destination: the carrier-applied field (a backend contradiction is gated earlier
    # by the explicit-invocation ruling, covered by its own tests).
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "destination": "merge"}

    outcome = pre_answers.evaluate(_invocation(carrier), established={"destination": "pr"})

    assert outcome.stop is not None
    assert outcome.applied == {}
    # The reason names both values — neither side is silently preferred.
    assert "merge" in outcome.stop
    assert "pr" in outcome.stop

    # A supplied value agreeing with the established one is applied, not stopped.
    agreeing = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}
    agreed = pre_answers.evaluate(_invocation(agreeing), established={"backend": "inline"})
    assert agreed.stop is None
    assert agreed.applied == {"backend": "inline"}


# --- negative: unknown schema refused whole (R19) -------------------------------------


def test_unknown_schema_token_is_refused_whole(pre_answers: ModuleType) -> None:
    carrier = {
        "schema": "plan_pre_answers.v2",
        "caller": "orchestrate",
        "backend": "inline",
        "destination": "plan-only",
    }

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is not None
    assert "plan_pre_answers.v2" in outcome.stop
    # Refused whole, asserted field by field: nothing is partially applied.
    assert "backend" not in outcome.applied
    assert "destination" not in outcome.applied
    assert outcome.applied == {}
    assert outcome.caller is None


# --- negative: the two-field admission limit (R15) ------------------------------------


def test_third_field_is_rejected_not_ignored(pre_answers: ModuleType) -> None:
    carrier = {
        "schema": SCHEMA_TOKEN,
        "caller": "orchestrate",
        "backend": "inline",
        "destination": "plan-only",
        "scope_class": "medium",
    }

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is not None
    assert "scope_class" in outcome.stop
    assert outcome.applied == {}


def test_inline_backend_still_applies_from_the_carrier(pre_answers: ModuleType) -> None:
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is None
    assert outcome.applied == {"backend": "inline"}


# --- carrier discipline (reviews F08/F08a/F15/F30) ------------------------------------


def test_two_carriers_stop_rather_than_first_winning(pre_answers: ModuleType) -> None:
    first = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}
    second = {"schema": SCHEMA_TOKEN, "caller": "work", "destination": "pr"}
    text = _invocation(first) + "\n" + _invocation(second)

    outcome = pre_answers.evaluate(text)

    assert outcome.applied == {}
    assert outcome.stop is not None
    assert "2" in outcome.stop


def test_only_json_fenced_blocks_are_carrier_candidates(pre_answers: ModuleType) -> None:
    # Same payload in a yaml fence is not a carrier (the info string must be exactly
    # json); the json-fenced carrier beside it is admitted alone.
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}
    text = (
        "/plan work issue #924\n\n"
        f"```yaml\n{json.dumps(carrier)}\n```\n\n"
        f"```json\n{json.dumps(carrier, indent=2)}\n```\n"
    )

    outcome = pre_answers.evaluate(text)

    assert outcome.stop is None
    assert outcome.applied == {"backend": "inline"}


def test_malformed_json_block_is_a_stop_not_an_absence(pre_answers: ModuleType) -> None:
    text = '/plan work issue #924\n\n```json\n{"schema": plan_pre_answers.v1,\n```\n'

    outcome = pre_answers.evaluate(text)

    assert outcome.applied == {}
    assert outcome.stop is not None
    assert "parse" in outcome.stop


def test_near_miss_schema_tokens_produce_the_documented_verdicts(
    pre_answers: ModuleType,
) -> None:
    # Case variant inside the family: refused whole (a documented stop), not ignored.
    upper = {"schema": "PLAN_PRE_ANSWERS.v1", "caller": "orchestrate", "backend": "inline"}
    refused = pre_answers.evaluate(_invocation(upper))
    assert refused.stop is not None
    assert refused.applied == {}

    # Token-boundary escape: "plan_pre_answersx" is a foreign name, not the family —
    # ignored as a non-carrier, decision fields left to the conversation.
    foreign = {"schema": "plan_pre_answersx.v1", "caller": "orchestrate", "backend": "inline"}
    ignored = pre_answers.evaluate(_invocation(foreign))
    assert ignored.stop is None
    assert ignored.applied == {}
    assert tuple(ignored.omitted) == pre_answers.DECISION_FIELDS


def test_refusal_messages_echo_bounded_values_only(pre_answers: ModuleType) -> None:
    # Review F24: the echoed caller-supplied value is truncated, so an unbounded input
    # cannot inflate the surfaced message. The token is inside the family (refused
    # whole), with an unbounded tail.
    huge = "plan_pre_answers." + "x" * 5000
    carrier = {"schema": huge, "caller": "orchestrate", "backend": "inline"}

    outcome = pre_answers.evaluate(_invocation(carrier))

    assert outcome.stop is not None
    assert len(outcome.stop) < 500
    assert "…" in outcome.stop


# --- runnable entry point (review F02u): proven as a real subprocess ------------------


def test_entry_point_runs_as_a_real_subprocess_and_prints_the_outcome(
    pre_answers: ModuleType, tmp_path: Path
) -> None:
    import subprocess

    script = SCRIPTS_DIR / "plan_pre_answers.py"
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}

    # stdin path: a clean carrier exits 0 with the applied value and its caller.
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=_invocation(carrier),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["applied"] == {"backend": "inline"}
    assert payload["caller"] == "orchestrate"
    assert payload["stop"] is None

    # --invocation-file path: a stop exits non-zero and surfaces the reason.
    invocation_file = tmp_path / "invocation.md"
    bad = {"schema": "plan_pre_answers.v9", "caller": "orchestrate", "backend": "inline"}
    invocation_file.write_text(_invocation(bad), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), "--invocation-file", str(invocation_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["applied"] == {}
    assert payload["stop"] is not None


def test_unrelated_malformed_json_is_prose_not_a_stop(pre_answers: ModuleType) -> None:
    # Cycle-2 C03/P02/S01: the malformed-carrier stop is gated on carrier shape. An
    # illustrative or truncated JSON example with no family token is prose — it must
    # not halt a run that carries no carrier (the over-fire stopped Plan against two
    # of this repository's own committed documents).
    blocks = (
        '{"name": "x", // a comment\n "port": 8080}',  # JSON-with-comments config sample
        '{"a": 1, "a": 2}',  # duplicate keys, but no family token anywhere
        "[1, 2,",  # truncated array
    )
    for block in blocks:
        text = f"/plan work issue #918\n\n```json\n{block}\n```\n"
        outcome = pre_answers.evaluate(text)
        assert outcome.stop is None, f"unrelated malformed fence over-fired: {block!r}"
        assert outcome.applied == {}
        assert tuple(outcome.omitted) == pre_answers.DECISION_FIELDS


def test_unrelated_malformed_json_before_a_valid_carrier_does_not_suppress_it(
    pre_answers: ModuleType,
) -> None:
    # The controller's reproduction: an unparseable non-carrier fence placed BEFORE a
    # well-formed carrier must not override it.
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "backend": "inline"}
    text = "/plan work issue #918\n\n```json\n{not json at all\n```\n\n" + _invocation(carrier)

    outcome = pre_answers.evaluate(text)

    assert outcome.stop is None
    assert dict(outcome.applied) == {"backend": "inline"}
    assert outcome.caller == "orchestrate"


def test_contradiction_rule_is_reachable_through_the_entry_point(
    pre_answers: ModuleType, tmp_path: Path
) -> None:
    # Cycle-2 C04/U04: the runnable validator performs the contradiction check itself —
    # ``--established`` supplies the settled decision, a contradicting carrier stops.
    import subprocess

    script = SCRIPTS_DIR / "plan_pre_answers.py"
    invocation_file = tmp_path / "invocation.md"
    carrier = {"schema": SCHEMA_TOKEN, "caller": "orchestrate", "destination": "merge"}
    invocation_file.write_text(_invocation(carrier), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--invocation-file",
            str(invocation_file),
            "--established",
            "destination=pr",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["applied"] == {}
    assert payload["stop"] is not None
    assert "contradicts" in payload["stop"]

    # The same flag is harmless when the values agree: the carrier applies.
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--invocation-file",
            str(invocation_file),
            "--established",
            "destination=merge",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["applied"] == {"destination": "merge"}
    assert payload["stop"] is None


def test_unreadable_invocation_file_stops_with_the_same_json_shape(
    pre_answers: ModuleType, tmp_path: Path
) -> None:
    # Cycle-2 U03/C10: a missing --invocation-file exits 2 with the same JSON shape and
    # a stop naming the unreadable path — never a bare traceback and exit 1.
    import subprocess

    script = SCRIPTS_DIR / "plan_pre_answers.py"
    missing_path = tmp_path / "missing.md"
    proc = subprocess.run(
        [sys.executable, str(script), "--invocation-file", str(missing_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["applied"] == {}
    assert payload["stop"] is not None
    assert "unreadable" in payload["stop"]
    assert str(missing_path) in payload["stop"], (
        "the stop itself must name the path; the subprocess argv cannot satisfy this assertion"
    )


# --- drift pins (reviews F14/F14a): the enums equal their canonical sources -----------


def test_phase0_intake_subsection_adds_no_rigidity_shapes() -> None:
    # Rigidity guard, scoped to the prose this unit adds: the Phase 0 intake
    # subsection must not introduce a question, a checklist, a questionnaire, or a
    # fixed sequence. Asserting the absence of new prose shapes — never a statement
    # about the conversation's questions, wording, or order, which R29 forbids. The
    # broader file legitimately uses some of these words outside the intake
    # subsection (Phase 1's "generic checklist", Phase 4's gap checklist, Phase 5's
    # questions), so the pin is scoped to the subsection's own text.
    text = PLAN_SKILL.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^### 0\.7 .*?(?=^## )", text)
    assert match is not None, "Phase 0 intake subsection missing from plan/SKILL.md"
    subsection = match.group(0)
    # Anchor: this is the pre-answer intake subsection, not some other 0.7.
    assert "plan_pre_answers.v1" in subsection
    lowered = subsection.lower()
    for banned in ("askuserquestion", "checklist", "questionnaire", "in order, ask", "answer each"):
        assert banned not in lowered, (
            f"the Phase 0 intake subsection introduced a rigidity shape: {banned!r}"
        )
