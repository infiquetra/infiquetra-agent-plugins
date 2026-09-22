"""Tests for release_step — the release, the functional test, and the close (issue 1028).

Nothing here reaches GitHub: every ``gh`` call goes through an injected fake runner. Nothing
deploys: the deploy handoff is an injected stub, and the one case that would call it needs a
temporary profile declaring a destination this repository does not have. Nothing writes the primary
checkout's live store.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
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


RS = _load("release_step")


class FakeGh:
    """Answers `gh` by verb, and records every argv so a test can assert what was bound."""

    def __init__(self, *, view: dict[str, Any], merge_ok: bool = True, merged: dict | None = None):
        self.view = view
        self.merge_ok = merge_ok
        self.merged = merged or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kw: Any) -> Any:
        self.calls.append(list(argv))
        if "merge" in argv:
            return SimpleNamespace(
                returncode=0 if self.merge_ok else 1,
                stdout="" if self.merge_ok else "Head branch was modified. Review and try again.",
                stderr="",
            )
        payload = (
            self.merged if self.calls.count(argv) and "mergeCommit" in " ".join(argv) else self.view
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")


def _clean_view(head: str = "a" * 40) -> dict[str, Any]:
    return {
        "headRefOid": head,
        "mergeStateStatus": "CLEAN",
        "mergeable": "MERGEABLE",
        "statusCheckRollup": [{"name": "gate", "conclusion": "SUCCESS"}],
        "url": "https://github.com/infiquetra/x/pull/7",
    }


class TestRelease:
    def test_a_clean_pull_request_merges_bound_to_the_head_it_checked(self) -> None:
        runner = FakeGh(view=_clean_view(), merged={"mergeCommit": {"oid": "b" * 40}, "url": "u"})
        state = RS.release(repo="infiquetra/x", number=7, runner=runner)
        assert state["status"] == "merged"
        assert state["reviewed_head"] == "a" * 40
        merge_argv = next(argv for argv in runner.calls if "merge" in argv)
        assert "--match-head-commit" in merge_argv
        assert merge_argv[merge_argv.index("--match-head-commit") + 1] == "a" * 40

    def test_a_squash_records_a_landed_commit_different_from_the_reviewed_head(self) -> None:
        runner = FakeGh(view=_clean_view(), merged={"mergeCommit": {"oid": "c" * 40}, "url": "u"})
        state = RS.release(repo="infiquetra/x", number=7, merge_method="squash", runner=runner)
        assert state["reviewed_head"] == "a" * 40
        assert state["landed_commit"] == "c" * 40
        assert state["reviewed_head"] != state["landed_commit"]
        assert state["merge_method"] == "squash"

    @pytest.mark.parametrize(
        ("merge_state", "phrase"),
        [
            ("UNSTABLE", "has not passed on this head"),
            ("BLOCKED", "not satisfied yet"),
            ("BEHIND", "behind its base"),
            ("DIRTY", "conflicts with its base"),
        ],
    )
    def test_a_merge_state_that_is_not_clean_waits_and_says_why(
        self, merge_state: str, phrase: str
    ) -> None:
        view = _clean_view()
        view["mergeStateStatus"] = merge_state
        runner = FakeGh(view=view)
        state = RS.release(repo="infiquetra/x", number=7, runner=runner)
        assert state["status"] == "waiting"
        assert phrase in state["reason"]
        assert not any("merge" in argv for argv in runner.calls)

    def test_a_check_that_failed_on_this_head_is_named_and_the_merge_is_not_attempted(self) -> None:
        view = _clean_view()
        view["statusCheckRollup"] = [
            {"name": "gate", "conclusion": "SUCCESS"},
            {"name": "Release Surface Parity", "conclusion": "FAILURE"},
        ]
        runner = FakeGh(view=view)
        state = RS.release(repo="infiquetra/x", number=7, runner=runner)
        assert state["status"] == "waiting"
        assert "Release Surface Parity (FAILURE)" in state["reason"]
        assert not any("merge" in argv for argv in runner.calls)

    def test_a_server_refusal_is_reported_and_never_reported_as_merged(self) -> None:
        runner = FakeGh(view=_clean_view(), merge_ok=False)
        state = RS.release(repo="infiquetra/x", number=7, runner=runner)
        assert state["status"] == "refused"
        assert "Head branch was modified" in state["reason"]

    def test_a_pull_request_with_no_head_is_refused(self) -> None:
        view = _clean_view()
        view["headRefOid"] = ""
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.release(repo="infiquetra/x", number=7, runner=FakeGh(view=view))
        assert "reports no head commit" in str(caught.value)


class TestDeploy:
    def test_this_repositorys_profile_records_no_destination_and_deploys_nothing(self) -> None:
        profile_path = REPO_ROOT / ".saga-profile.json"
        if not profile_path.is_file():
            pytest.skip("this catalog does not carry the upstream repository's .saga-profile.json")
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile["nonproduction_destination"] == "none"
        record = {
            "run_configuration": {
                "nonproduction_destination": {"value": profile["nonproduction_destination"]}
            }
        }
        called: list[Any] = []
        result = RS.deploy(
            record,
            saga_id="issue-1028",
            release_state={"status": "merged", "landed_commit": "b" * 40},
            handoff=lambda **kw: called.append(kw),
        )
        assert result["status"] == "no-destination"
        assert result["deployed"] is False
        assert "nothing was deployed" in result["reason"]
        assert called == []

    def test_a_declared_destination_hands_off_exactly_once(self) -> None:
        record = {"run_configuration": {"nonproduction_destination": {"value": "olympus-nonprod"}}}
        called: list[Any] = []

        def handoff(**kw: Any) -> dict[str, str]:
            called.append(kw)
            return {"token": "abc"}

        result = RS.deploy(
            record,
            saga_id="issue-1028",
            release_state={"status": "merged", "landed_commit": "b" * 40},
            handoff=handoff,
        )
        assert result["status"] == "handed-off"
        assert result["destination"] == "olympus-nonprod"
        assert result["revision"] == "b" * 40
        assert len(called) == 1

    def test_deploy_before_a_merge_is_refused(self) -> None:
        record = {"run_configuration": {"nonproduction_destination": {"value": "olympus-nonprod"}}}
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.deploy(
                record, saga_id="x", release_state={"status": "waiting"}, handoff=lambda **k: {}
            )
        assert "deploy follows the merge" in str(caught.value)

    def test_a_declared_destination_with_no_handoff_is_refused_not_skipped(self) -> None:
        record = {"run_configuration": {"nonproduction_destination": {"value": "olympus-nonprod"}}}
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.deploy(record, saga_id="x", release_state={"status": "merged"}, handoff=None)
        assert "never released without an acknowledgement" in str(caught.value)


class TestFunctionalTest:
    def _record(self, **extra: Any) -> dict[str, Any]:
        return {
            "run_configuration": {
                "standard_cycle_allowance": {"value": 3},
                "escalated_cycle_allowance": {"value": 2},
            },
            **extra,
        }

    def test_every_scenario_passing_is_a_pass(self) -> None:
        result = RS.record_functional_test(
            self._record(), [{"name": "a", "state": "passed"}, {"name": "b", "state": "passed"}]
        )
        assert result["status"] == "passed"
        assert result["post_merge_cycles"] == 0

    def test_a_failure_re_enters_the_loop_and_counts_against_the_post_merge_allowance(self) -> None:
        result = RS.record_functional_test(self._record(), [{"name": "a", "state": "failed"}])
        assert result["status"] == "re-enters-the-build-loop"
        assert result["post_merge_cycles"] == 1
        assert "cycle 1 of 5" in result["reason"]

    def test_the_spent_allowance_takes_the_one_recorded_extension(self) -> None:
        record = self._record(functional_test={"post_merge_cycles": 5, "extension_taken": False})
        result = RS.record_functional_test(record, [{"name": "a", "state": "failed"}])
        assert result["status"] == "re-enters-the-build-loop"
        assert result["extension_taken"] is True
        assert "one recorded extension" in result["reason"]

    def test_a_second_extension_is_never_granted(self) -> None:
        record = self._record(functional_test={"post_merge_cycles": 6, "extension_taken": True})
        result = RS.record_functional_test(record, [{"name": "a", "state": "failed"}])
        assert result["status"] == "exhausted"
        assert "goes to the operator" in result["reason"]

    def test_an_unrun_scenario_is_never_folded_into_a_pass(self) -> None:
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.record_functional_test(self._record(), [{"name": "a", "state": "not run"}])
        assert "ends in one of: passed, failed, blocked" in str(caught.value)

    def test_a_blocked_scenario_names_what_blocked_it(self) -> None:
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.record_functional_test(self._record(), [{"name": "a", "state": "blocked"}])
        assert "no cause named" in str(caught.value)

    def test_a_required_blocked_scenario_is_never_reported_as_a_pass(self) -> None:
        """The hazard issue 1039 found: the status was computed from the failed list alone.

        A scenario list holding nothing but ``blocked`` entries has proved nothing, and reporting
        it ``passed`` is exactly the silent skip the prescribed-testing design exists to remove.
        """
        result = RS.record_functional_test(
            self._record(),
            [{"name": "a", "state": "blocked", "cause": "QA_BASE_URL is unset", "required": True}],
        )
        assert result["status"] == "blocked"
        assert result["post_merge_cycles"] == 0
        assert "a" in result["reason"]
        assert "QA_BASE_URL is unset" in result["reason"]

    def test_a_blocked_scenario_does_not_re_enter_the_build_loop(self) -> None:
        """Its causes are environment, credential and permission; a build loop repairs none."""
        result = RS.record_functional_test(
            self._record(),
            [
                {"name": "a", "state": "passed"},
                {"name": "b", "state": "blocked", "cause": "no toolchain", "required": True},
            ],
        )
        assert result["status"] == "blocked"
        assert result["status"] != "re-enters-the-build-loop"

    def test_a_failure_beside_a_required_block_still_stops_for_the_operator(self) -> None:
        """A block the operator must clear outranks a failure the loop could repair."""
        result = RS.record_functional_test(
            self._record(),
            [
                {"name": "a", "state": "failed"},
                {"name": "b", "state": "blocked", "cause": "no credential", "required": True},
            ],
        )
        assert result["status"] == "blocked"

    def test_an_optional_blocked_scenario_passes_with_proof_debt(self) -> None:
        """Proof debt is recorded, not hidden — and it is not a pass with nothing said."""
        result = RS.record_functional_test(
            self._record(),
            [
                {"name": "a", "state": "passed"},
                {"name": "b", "state": "blocked", "cause": "no preview", "required": False},
            ],
        )
        assert result["status"] == "passed-with-proof-debt"
        assert result["proof_debt"] == [
            {"name": "b", "cause": "no preview"},
        ]

    def test_a_scenario_that_does_not_say_whether_it_is_required_is_treated_as_required(
        self,
    ) -> None:
        """The safe default: an unmarked scenario is a required one, so it cannot pass unproved."""
        result = RS.record_functional_test(
            self._record(), [{"name": "a", "state": "blocked", "cause": "unset"}]
        )
        assert result["status"] == "blocked"


class TestClose:
    def test_the_comment_carries_every_required_part(self) -> None:
        record = {
            "release": {"landed_commit": "b" * 40, "url": "https://example/pull/7"},
            "deployment": {"status": "no-destination", "reason": "the profile declares none"},
            "functional_test": {"scenarios": [{"name": "a", "state": "passed"}]},
            "documentation_status": "the plan and the journal shipped with the change",
            "cleanup": "the merge worktree was removed inside the turn",
        }
        comment = RS.closeout_comment(record, disposition="delivered")
        for part in RS.CLOSEOUT_PARTS:
            assert part in comment["parts"]
            assert comment["parts"][part]
        assert comment["closure_reason"] == "COMPLETED"
        assert "b" * 40 in comment["body"]

    def test_an_absent_practice_is_recorded_with_a_reason_not_left_blank(self) -> None:
        comment = RS.closeout_comment({}, disposition="delivered")
        assert "not applicable" in comment["parts"]["environment"]
        assert "not recorded" in comment["parts"]["delivered_revision"]
        assert "no functional-test result" in comment["parts"]["acceptance_results"]

    def test_no_environment_is_invented_when_nothing_was_deployed(self) -> None:
        record = {"deployment": {"status": "no-destination", "reason": "the profile declares none"}}
        comment = RS.closeout_comment(record, disposition="delivered")
        assert comment["parts"]["environment"].startswith("not applicable")
        assert "the profile declares none" in comment["parts"]["environment"]

    @pytest.mark.parametrize(
        ("disposition", "reason"),
        [
            ("delivered", "COMPLETED"),
            ("duplicate", "DUPLICATE"),
            ("superseded", "NOT_PLANNED"),
            ("declined", "NOT_PLANNED"),
            ("canceled", "NOT_PLANNED"),
        ],
    )
    def test_each_disposition_maps_to_its_fixed_closure_reason(
        self, disposition: str, reason: str
    ) -> None:
        comment = RS.closeout_comment({}, disposition=disposition, replacement="infiquetra/x#9")
        assert comment["closure_reason"] == reason

    def test_a_duplicate_without_a_replacement_link_is_refused(self) -> None:
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.closeout_comment({}, disposition="duplicate")
        assert "links its replacement before it closes" in str(caught.value)

    def test_an_unknown_disposition_is_refused_with_the_five(self) -> None:
        with pytest.raises(RS.ReleaseStepError) as caught:
            RS.closeout_comment({}, disposition="shipped")
        assert "unknown disposition 'shipped'" in str(caught.value)
        for known in RS.DISPOSITIONS:
            assert known in str(caught.value)


class TestNoProductionDeployment:
    """Card 1028 says no production deployment exists here — as a guard, not a promise.

    The reading is over the module's executable strings, never its prose: the docstrings SAY
    "no production deployment exists anywhere in this module", and a guard that trips on its own
    documentation is a guard that gets deleted.
    """

    @staticmethod
    def _executable_strings() -> list[str]:
        import ast

        tree = ast.parse((SCRIPTS / "release_step.py").read_text(encoding="utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]

    def test_no_executable_string_names_a_production_target(self) -> None:
        for text in self._executable_strings():
            cleaned = text.lower().replace("nonproduction", "").replace("non-production", "")
            assert "production" not in cleaned, f"release_step names a production target: {text!r}"

    def test_the_deploy_command_takes_no_environment_argument(self) -> None:
        """There is no argument that could point the deploy anywhere but the declared destination."""
        parser = RS.build_parser()
        actions = {
            action.dest
            for action in parser._subparsers._group_actions[0].choices["deploy"]._actions  # type: ignore[union-attr]
        }
        assert "env" not in actions and "environment" not in actions


class TestCommandLine:
    def test_the_release_dry_run_prints_and_calls_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = tmp_path / "issue-1028.json"
        record.write_text(json.dumps({"schema": "run_record.v1", "issue": 1028, "repo": "o/r"}))
        code = RS.main(["--record", str(record), "release", "--pull-request", "7", "--dry-run"])
        assert code == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed == {
            "dry_run": True,
            "repo": "o/r",
            "pull_request": 7,
            "merge_method": "merge",
        }

    def test_a_refusal_is_one_line_on_stderr_and_exit_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = tmp_path / "issue-1028.json"
        record.write_text(json.dumps({"schema": "run_record.v1", "issue": 1028}))
        code = RS.main(["--record", str(record), "close", "--disposition", "shipped"])
        assert code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("release_step: ")
        assert len(captured.err.strip().splitlines()) == 1
