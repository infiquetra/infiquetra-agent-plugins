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


def _staff(store: Path, staffing: Any, *, next_step: str = "run /work on the plan") -> None:
    run_record.set_next_step(store, ISSUE, next_step)

    def change(record: run_record.RunRecord | None) -> run_record.RunRecord:
        assert record is not None
        configuration = {k: dict(v) for k, v in record.run_configuration.items()}
        configuration["staffing_models_and_efforts"]["value"] = staffing
        configuration["staffing_models_and_efforts"]["source"] = "staffing"
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
    """A stand-in for `staffing.py resolve --role <role> --json` that records what it was asked."""

    def __init__(self, answer: Mapping[str, str] | None = None) -> None:
        self.answer = dict(answer or _row("sonnet", "medium"))
        self.asked: list[tuple[str, Path]] = []

    def __call__(self, role: str, cwd: Path) -> Mapping[str, Any]:
        self.asked.append((role, cwd))
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
    assert types["worker"]["source"] == "run-record"
    assert "opus/medium" in types["worker"]["description"]
    assert resolver.asked == []  # the record staffed every role; the resolver was not asked


def test_the_prompt_is_the_library_file_body_behind_the_hosting_preamble(repo: Path, store: Path) -> None:
    _staff(store, FULL)
    worker = _by_role(_answer(repo, store))["worker"]
    body = (ROLES / "implementer.md").read_text(encoding="utf-8")
    stripped = body[body.index("\n---\n", 4) + len("\n---\n") :].lstrip("\n")

    assert worker["prompt"] == role_agent_types.HOSTING_PREAMBLE + stripped
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
    roles = set(roster.STAFFING_ROLE_TO_ROLE_ID) - {"lens-reviewer"}
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


def test_a_role_staffed_on_another_vendor_is_skipped_not_translated(repo: Path, store: Path) -> None:
    _staff(store, {**FULL, "worker": _row("gpt-5", "high", vendor="codex")})
    answer = _answer(repo, store)
    assert "worker" not in _by_role(answer)
    assert {"role": "worker", "reason": "staffed on codex"} in answer["skipped"]


def test_a_role_the_resolver_cannot_answer_is_skipped_with_its_reason(repo: Path, store: Path) -> None:
    _staff(store, {})

    def failing(role: str, cwd: Path) -> Mapping[str, Any]:
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
    assert all(t["source"] == "resolver" for t in answer["types"])
    assert sorted(role for role, _ in resolver.asked) == CLAUDE_ROLES
    assert {cwd for _, cwd in resolver.asked} == {repo}


def test_a_partial_operator_answer_is_completed_by_the_resolver(repo: Path, store: Path) -> None:
    _staff(store, {"worker": {"model": "opus", "effort": "xhigh"}})
    resolver = Resolver(_row("sonnet", "medium"))
    types = _by_role(_answer(repo, store, resolver))

    assert (types["worker"]["model"], types["worker"]["effort"]) == ("opus", "xhigh")
    assert types["worker"]["source"] == "run-record+resolver"
    assert (types["planner"]["model"], types["planner"]["source"]) == ("sonnet", "resolver")


def test_the_real_resolver_command_answers_a_role(repo: Path) -> None:
    decision = role_agent_types.resolve_with_script("worker", repo)
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
    monkeypatch.setattr(role_agent_types, "SAGA_ROOT", cache / "saga" / "1.2.2")
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
