"""What each staffed role of the active run runs as: role_agent_types.py (issue #106).

Every case uses a temporary git repository and a temporary record store, and stubs the staffing
resolver unless it says otherwise. Nothing here touches the primary checkout's live
`.claude/saga/runs` directory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA_SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
AGENT_LAUNCHER = ROOT / "plugins" / "agent-launcher"
ROLES = AGENT_LAUNCHER / "roles"
SCRIPT = SAGA_SCRIPTS / "role_agent_types.py"

sys.path.insert(0, str(SAGA_SCRIPTS))

import role_agent_types  # noqa: E402
import run_record  # noqa: E402

ISSUE = 123
CLAUDE_ROLES = ["functional-tester", "plan-reviewer", "planner", "release-worker", "worker"]


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git("init", "-q", "-b", f"issue/{ISSUE}-agent-types", cwd=path)
    return path


@pytest.fixture
def store(tmp_path: Path) -> Path:
    path = tmp_path / "runs"
    path.mkdir()
    return path


def _staff(
    store: Path,
    staffing: Any,
    *,
    next_step: str = "run /work on the plan",
    source: str = "operator",
) -> None:
    """Record *staffing* as the run's map; ``source="operator"`` is a ``staffing_overrides`` answer."""
    run_record.set_next_step(store, ISSUE, next_step)

    def change(record: run_record.RunRecord | None) -> run_record.RunRecord:
        assert record is not None
        configuration = {k: dict(v) for k, v in record.run_configuration.items()}
        configuration["staffing_models_and_efforts"]["value"] = staffing
        configuration["staffing_models_and_efforts"]["source"] = source
        return run_record.RunRecord(**{**record.__dict__, "run_configuration": configuration})

    run_record.update(store, ISSUE, change)


def _row(model: str, effort: str, vendor: str = "claude") -> dict[str, str]:
    return {"vendor": vendor, "model": model, "effort": effort}


FULL = {
    "planner": _row("opus", "high"),
    "plan-reviewer": _row("opus", "high"),
    "worker": _row("opus", "medium"),
    "functional-tester": _row("opus", "high"),
    "release-worker": _row("sonnet", "medium"),
    "merging-worker": _row("sonnet", "medium"),
}


class Resolver:
    """A stand-in for `staffing.resolve_role` that records what it was asked.

    It answers the operator's answer when given one, else the raise, else its default, the way
    the real resolver does when no overlay is present. The script under test must not apply that
    order itself; the stub is where it lives in these tests.
    """

    def __init__(self, answer: Mapping[str, str] | None = None) -> None:
        self.answer = dict(answer or _row("sonnet", "medium"))
        self.asked: list[tuple[str, Path]] = []
        self.inputs: dict[str, dict[str, Any]] = {}

    def __call__(
        self,
        role: str,
        cwd: Path,
        *,
        answer: Mapping[str, str] | None = None,
        jev_raise: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        self.asked.append((role, cwd))
        self.inputs[role] = {"answer": answer, "jev_raise": jev_raise}
        if answer is not None:
            return {**self.answer, **answer, "role": role, "source": "operator"}
        if jev_raise is not None:
            tier = {"model": jev_raise["model"], "effort": jev_raise["effort"]}
            return {**self.answer, **tier, "role": role, "source": "jev-raise"}
        return {**self.answer, "role": role, "source": "policy"}


def _answer(repo: Path, store: Path, resolver: Any = None, **kwargs: Any) -> dict[str, Any]:
    return role_agent_types.role_agent_types(
        repo,
        store_root=store,
        agent_launcher=kwargs.pop("agent_launcher", AGENT_LAUNCHER),
        resolver=resolver or Resolver(),
        **kwargs,
    )


def _by_role(answer: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["role"]: t for t in answer["types"]}


# --------------------------------------------------------------------------- active runs


def test_an_active_run_answers_every_briefed_role_at_its_recorded_tier(repo: Path, store: Path) -> None:
    _staff(store, FULL)
    resolver = Resolver()
    answer = _answer(repo, store, resolver)

    assert answer["schema"] == "saga_role_agent_types.v1"
    assert answer["active"] is True
    assert answer["issue"] == ISSUE
    types = _by_role(answer)
    assert sorted(types) == CLAUDE_ROLES
    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "medium")
    assert types["worker"]["role_id"] == "implementer"
    assert types["worker"]["readable_role"] == "Initial Implementation Worker"
    assert Path(types["worker"]["prompt_path"]) == ROLES / "implementer.md"
    assert types["worker"]["source"] == "operator"
    assert "opus/medium" in types["worker"]["description"]
    # The operator's map reaches the resolver as the operator's answer; the script applies none.
    assert resolver.inputs["worker"] == {
        "answer": {"model": "opus", "effort": "medium"},
        "jev_raise": None,
    }


def test_the_prompt_is_the_library_file_body_behind_the_hosting_preamble(repo: Path, store: Path) -> None:
    _staff(store, FULL)
    worker = _by_role(_answer(repo, store))["worker"]
    body = (ROLES / "implementer.md").read_text(encoding="utf-8")
    stripped = body[body.index("\n---\n", 4) + len("\n---\n") :].lstrip("\n")

    assert worker["prompt"] == role_agent_types.HOSTING_PREAMBLE + stripped
    assert (
        "plugins/saga/references/question-banks/policy-questions.json" in worker["prompt"]
    )
    assert not worker["prompt"].startswith("---")
    assert "role_id: implementer" not in worker["prompt"]
    assert "Do not post comments on the issue" in worker["prompt"]


def test_the_prompt_is_read_from_the_library_at_call_time_never_copied(
    repo: Path, store: Path, tmp_path: Path
) -> None:
    _staff(store, FULL)
    library = tmp_path / "roles"
    shutil.copytree(ROLES, library)
    first = _by_role(_answer(repo, store, roles_dir=library))["worker"]["prompt"]

    edited = library / "implementer.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nA line added for the test.\n")
    answer = _answer(repo, store, roles_dir=library)

    assert _by_role(answer)["worker"]["prompt"] == first + "\nA line added for the test.\n"
    assert Path(_by_role(answer)["worker"]["prompt_path"]) == edited


def test_the_fingerprint_moves_with_a_tier_and_with_a_prompt(repo: Path, store: Path) -> None:
    _staff(store, FULL)
    before = _answer(repo, store)["fingerprint"]
    assert _answer(repo, store)["fingerprint"] == before
    _staff(store, {**FULL, "worker": _row("opus", "high")})
    assert _answer(repo, store)["fingerprint"] != before


def test_the_mapping_is_rosters_own(repo: Path, store: Path) -> None:
    roster = role_agent_types.load_roster(AGENT_LAUNCHER)
    roles = set(roster.STAFFING_ROLE_TO_ROLE_ID) - set(role_agent_types.NO_TYPE_REASONS)
    _staff(store, FULL)
    assert set(_by_role(_answer(repo, store))) == roles
    # No second copy of the mapping: the script never spells a library role id itself.
    assert '"implementer"' not in SCRIPT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- skipped roles


def test_merging_worker_and_the_lens_reviewer_are_skipped_by_name(repo: Path, store: Path) -> None:
    _staff(store, {**FULL, "lens-reviewer": _row("opus", "high")})
    skipped = {s["role"]: s["reason"] for s in _answer(repo, store)["skipped"]}
    assert skipped["merging-worker"] == "no role prompt in the roles library"
    assert "sliced per lens" in skipped["lens-reviewer"]


def test_the_targeted_reviewer_gets_no_subagent_type(repo: Path, store: Path) -> None:
    """Issue #158: it runs headless through agent-launcher's reviewer launch, never in-session."""
    _staff(store, {**FULL, "targeted-reviewer": _row("opus", "high")})
    answer = _answer(repo, store)
    assert "targeted-reviewer" not in _by_role(answer)
    skipped = {s["role"]: s["reason"] for s in answer["skipped"]}
    assert "runs headless through agent-launcher's reviewer launch" in skipped["targeted-reviewer"]


def test_a_role_staffed_on_another_vendor_is_skipped_not_translated(repo: Path, store: Path) -> None:
    _staff(store, {**FULL, "worker": _row("gpt-5", "high", vendor="codex")})
    answer = _answer(repo, store)
    assert "worker" not in _by_role(answer)
    assert {"role": "worker", "reason": "staffed on codex"} in answer["skipped"]


def test_a_role_the_resolver_cannot_answer_is_skipped_with_its_reason(repo: Path, store: Path) -> None:
    _staff(store, {})

    def failing(role: str, cwd: Path, **_: Any) -> Mapping[str, Any]:
        if role == "planner":
            raise role_agent_types.RoleTypesError("error: unknown role")
        return {**_row("sonnet", "medium"), "role": role}

    answer = _answer(repo, store, failing)
    assert "planner" not in _by_role(answer)
    assert {
        "role": "planner",
        "reason": "its tier could not be resolved: error: unknown role",
    } in answer["skipped"]
    assert "worker" in _by_role(answer)


# --------------------------------------------------------------------------- the resolver


def test_unstaffed_roles_are_asked_of_the_resolver_from_the_checkout(repo: Path, store: Path) -> None:
    _staff(store, None)
    resolver = Resolver(_row("opus", "medium"))
    answer = _answer(repo, store, resolver)

    assert sorted(_by_role(answer)) == CLAUDE_ROLES
    assert all(t["source"] == "policy" for t in answer["types"])
    assert sorted(role for role, _ in resolver.asked) == CLAUDE_ROLES
    assert {cwd for _, cwd in resolver.asked} == {repo}


def test_a_partial_operator_answer_is_completed_by_the_resolver(repo: Path, store: Path) -> None:
    _staff(store, {"worker": {"model": "opus", "effort": "xhigh"}})
    resolver = Resolver(_row("sonnet", "medium"))
    types = _by_role(_answer(repo, store, resolver))

    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "xhigh")
    assert types["worker"]["source"] == "operator"
    assert (types["planner"]["model"], types["planner"]["source"]) == ("sonnet", "policy")


def test_an_admission_filled_row_is_answered_again_by_the_resolver(repo: Path, store: Path) -> None:
    _staff(store, FULL, source="staffing")
    resolver = Resolver(_row("sonnet", "high"))
    types = _by_role(_answer(repo, store, resolver))

    # Admission's row is the resolver's earlier answer, not an operator's: it is not passed in.
    assert resolver.inputs["worker"] == {"answer": None, "jev_raise": None}
    assert (types["worker"]["model"], types["worker"]["effort"]) == ("sonnet", "high")


def test_a_row_marked_operator_override_goes_in_as_the_operators_answer(
    repo: Path, store: Path
) -> None:
    worker = {**_row("opus", "xhigh"), "operator_override": True}
    _staff(store, {**FULL, "worker": worker}, source="staffing")
    resolver = Resolver()
    types = _by_role(_answer(repo, store, resolver))

    assert resolver.inputs["worker"]["answer"] == {"model": "opus", "effort": "xhigh"}
    assert resolver.inputs["planner"]["answer"] is None
    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "xhigh")


RAISE = {"model": "opus", "effort": "high", "confidence": 0.86, "reason": "r", "decision_id": "d"}


def test_a_merged_operator_answer_marks_only_the_overridden_rows(repo: Path, store: Path) -> None:
    # Admission's per-role merge (issue #103) sets the block's source to `operator` and marks
    # only the roles the answer named. The planner's row is not the operator's: it keeps its
    # recorded raise and goes to the resolver with no answer, exactly as admission reads it.
    planner = {**_row("opus", "medium"), "operator_override": False, "jev_raise": RAISE}
    worker = {**_row("opus", "xhigh"), "operator_override": True}
    _staff(store, {**FULL, "planner": planner, "worker": worker}, source="operator")
    resolver = Resolver(_row("opus", "medium"))
    types = _by_role(_answer(repo, store, resolver))

    assert resolver.inputs["worker"] == {
        "answer": {"model": "opus", "effort": "xhigh"},
        "jev_raise": None,
    }
    assert resolver.inputs["planner"] == {"answer": None, "jev_raise": RAISE}
    assert resolver.inputs["release-worker"]["answer"] is None
    assert (types["worker"]["effort"], types["worker"]["source"]) == ("xhigh", "operator")
    assert (types["planner"]["effort"], types["planner"]["source"]) == ("high", "jev-raise")
    assert types["release-worker"]["source"] == "policy"


def test_the_operator_rows_come_from_run_records_one_rule(repo: Path, store: Path) -> None:
    # Admission's staffing table reads the same record through run_record.operator_answered_roles,
    # so the registered type and the table cannot disagree about whose row it is.
    planner = {**_row("opus", "medium"), "operator_override": False, "jev_raise": RAISE}
    worker = {**_row("opus", "xhigh"), "operator_override": True}
    _staff(store, {**FULL, "planner": planner, "worker": worker}, source="operator")
    record = run_record.load(store, ISSUE, warn=None)
    rows, operator_roles = role_agent_types.staffing_rows(record)

    assert operator_roles == {"worker"}
    assert operator_roles == run_record.operator_answered_roles(
        record.run_configuration["staffing_models_and_efforts"]
    )
    assert "planner" in rows


def test_a_whole_map_operator_answer_is_the_operators_for_every_role(store: Path) -> None:
    _staff(store, FULL, source="operator")
    record = run_record.load(store, ISSUE, warn=None)
    _, operator_roles = role_agent_types.staffing_rows(record)
    assert operator_roles == set(FULL)


def test_the_real_resolver_carries_a_recorded_raise_overlay_and_operator_rows_through(
    repo: Path, store: Path
) -> None:
    # No stub: the bundled staffing resolver (issue #93's single precedence order) decides.
    # The planner is the operator's row, the worker records a one-step raise over its
    # implementation default, the release worker meets the repository overlay, and the
    # plan reviewer has nothing but the policy default.
    (repo / ".saga").mkdir()
    (repo / ".saga" / "tier-defaults.json").write_text(
        json.dumps({"mechanical": {"model": "sonnet", "effort": "high"}}), encoding="utf-8"
    )
    staffing = {
        **FULL,
        "planner": {**_row("opus", "xhigh"), "operator_override": True},
        "worker": {**_row("opus", "medium"), "operator_override": False, "jev_raise": RAISE},
    }
    _staff(store, staffing, source="operator")
    answer = role_agent_types.role_agent_types(repo, store_root=store, agent_launcher=AGENT_LAUNCHER)
    types = _by_role(answer)

    def tier(role: str) -> tuple[str, str, str]:
        return types[role]["model"], types[role]["effort"], types[role]["source"]

    assert tier("planner") == ("opus", "xhigh", "operator")
    assert tier("worker") == ("opus", "high", "jev-raise")
    assert tier("release-worker") == ("sonnet", "high", "overlay")
    assert tier("plan-reviewer") == ("opus", "high", "policy")



def test_a_recorded_jev_raise_reaches_the_registered_type(repo: Path, store: Path) -> None:
    worker = {**_row("opus", "medium"), "jev_raise": RAISE}
    _staff(store, {**FULL, "worker": worker}, source="staffing")
    resolver = Resolver(_row("opus", "medium"))
    types = _by_role(_answer(repo, store, resolver))

    assert resolver.inputs["worker"] == {"answer": None, "jev_raise": RAISE}
    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "high")
    assert types["worker"]["source"] == "jev-raise"
    assert "opus/high" in types["worker"]["description"]


def test_a_raise_the_resolver_refuses_skips_the_role_by_name(repo: Path, store: Path) -> None:
    bad = {**RAISE, "model": "fable", "effort": "max"}
    _staff(store, {**FULL, "worker": {**_row("opus", "medium"), "jev_raise": bad}}, source="staffing")

    def refusing(role: str, cwd: Path, *, answer: Any = None, jev_raise: Any = None) -> Any:
        if jev_raise is not None:
            raise role_agent_types.RoleTypesError("jev raise is not exactly one step above")
        return {**_row("opus", "medium"), "role": role, "source": "policy"}

    answer = _answer(repo, store, refusing)
    assert "worker" not in _by_role(answer)
    assert {
        "role": "worker",
        "reason": "its tier could not be resolved: jev raise is not exactly one step above",
    } in answer["skipped"]


class _FakeDecision:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    def as_dict(self) -> dict[str, Any]:
        return dict(self.record)


def test_the_default_resolver_hands_the_raise_to_staffing_resolve_role(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class Staffing:
        @staticmethod
        def resolve_role(role: str, *, root: Path, require_lens: bool, answer: Any = None,
                         jev_raise: Any = None) -> _FakeDecision:
            seen.update(role=role, root=root, require_lens=require_lens, answer=answer,
                        jev_raise=jev_raise)
            return _FakeDecision({**_row("opus", "high"), "source": "jev-raise"})

    monkeypatch.setattr(role_agent_types, "_load_staffing", lambda: Staffing)
    decision = role_agent_types.resolve_with_staffing("worker", repo, jev_raise=RAISE)
    assert seen == {"role": "worker", "root": repo, "require_lens": False, "answer": None,
                    "jev_raise": RAISE}
    assert (decision["model"], decision["effort"], decision["source"]) == ("opus", "high", "jev-raise")


def test_the_real_resolver_answers_a_role(repo: Path) -> None:
    decision = role_agent_types.resolve_with_staffing("worker", repo)
    assert decision["role"] == "worker"
    assert decision["vendor"] == "claude"
    assert decision["model"] and decision["effort"]


# --------------------------------------------------------------------------- no run


def test_no_resolvable_issue_is_inactive(tmp_path: Path, store: Path) -> None:
    path = tmp_path / "main-repo"
    path.mkdir()
    _git("init", "-q", "-b", "main", cwd=path)
    resolver = Resolver()
    answer = _answer(path, store, resolver)
    assert (answer["active"], answer["issue"], answer["types"]) == (False, None, [])
    assert resolver.asked == []


def test_no_record_is_inactive(repo: Path, store: Path) -> None:
    answer = _answer(repo, store)
    assert (answer["active"], answer["types"]) == (False, [])


def test_a_closed_run_is_inactive(repo: Path, store: Path) -> None:
    _staff(store, FULL, next_step="")
    answer = _answer(repo, store)
    assert (answer["active"], answer["types"]) == (False, [])


def test_a_missing_roles_library_is_a_named_error_naming_every_rung(
    repo: Path, store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _staff(store, FULL)
    nowhere = tmp_path / "nowhere"
    monkeypatch.setattr(role_agent_types, "SAGA_ROOT", tmp_path / "plugins" / "saga")
    answer = role_agent_types.role_agent_types(
        repo, store_root=store, agent_launcher=nowhere, resolver=Resolver(), env={}
    )
    assert (answer["active"], answer["types"]) == (True, [])
    assert answer["error"].startswith("the roles library was not found")
    assert str(nowhere) in answer["error"]
    assert str(tmp_path / "plugins" / "agent-launcher") in answer["error"]


def test_the_versioned_install_layout_finds_the_newest_agent_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "marketplace"
    for version in ("0.9.0", "0.10.0"):
        (cache / "agent-launcher" / version / "skills" / "agent-launcher" / "scripts").mkdir(
            parents=True
        )
        (cache / "agent-launcher" / version / role_agent_types.ROSTER_SUBPATH).write_text("")
    monkeypatch.setattr(role_agent_types, "SAGA_ROOT", cache / "saga" / "1.3.0")
    found = role_agent_types.locate_agent_launcher(env={})
    assert found == cache / "agent-launcher" / "0.10.0"


# --------------------------------------------------------------------------- the command line


def test_the_command_runs_from_a_foreign_directory_the_way_the_mod_runs_it(
    repo: Path, store: Path, tmp_path: Path
) -> None:
    _staff(store, FULL)
    foreign = tmp_path / "elsewhere"
    foreign.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--cwd",
            str(repo),
            "--store-root",
            str(store),
            "--json",
        ],
        cwd=str(foreign),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    answer = json.loads(result.stdout)
    types = _by_role(answer)
    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "medium")


def test_the_command_with_no_run_prints_an_inactive_answer(tmp_path: Path) -> None:
    path = tmp_path / "plain"
    path.mkdir()
    _git("init", "-q", "-b", "main", cwd=path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--cwd", str(path), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["active"] is False
