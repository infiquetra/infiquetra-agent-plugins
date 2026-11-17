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
    """Answers `gh` by verb, and records every argv so a test can assert what was bound.

    ``threads`` is the pull request's review threads, as one page of ``isResolved`` flags;
    ``thread_pages`` gives several pages instead, each flagged as having a next page until the
    last. The default is a pull request with no review threads at all.
    """

    def __init__(
        self,
        *,
        view: dict[str, Any],
        merge_ok: bool = True,
        merged: dict | None = None,
        threads: list[bool] | None = None,
        thread_pages: list[list[bool]] | None = None,
        threads_ok: bool = True,
    ):
        self.view = view
        self.merge_ok = merge_ok
        self.merged = merged or {}
        self.pages = thread_pages if thread_pages is not None else [list(threads or [])]
        self.threads_ok = threads_ok
        self.calls: list[list[str]] = []
        self.thread_calls = 0

    def _threads(self) -> Any:
        if not self.threads_ok:
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 502")
        index = min(self.thread_calls, len(self.pages) - 1)
        self.thread_calls += 1
        last = index == len(self.pages) - 1
        payload = {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "pageInfo": {
                                "hasNextPage": not last,
                                "endCursor": None if last else f"cursor-{index}",
                            },
                            "nodes": [{"isResolved": resolved} for resolved in self.pages[index]],
                        }
                    }
                }
            }
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    def __call__(self, argv: list[str], **_kw: Any) -> Any:
        self.calls.append(list(argv))
        if "graphql" in argv:
            return self._threads()
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


class TestUnresolvedReviewThreads:
    """Issue #161: an unresolved review thread, bot or human, holds the merge."""

    def _release(self, runner: FakeGh, **kwargs: Any) -> dict[str, Any]:
        return RS.release(repo="infiquetra/x", number=7, runner=runner, **kwargs)

    def test_unresolved_threads_are_counted_through_the_graphql_api(self) -> None:
        runner = FakeGh(view=_clean_view(), threads=[True, False, False, True, False])
        assert RS.unresolved_review_threads("infiquetra/x", 7, runner=runner) == 3
        [call] = [argv for argv in runner.calls if "graphql" in argv]
        assert call[:2] == ["gh", "api"]
        joined = " ".join(call)
        assert "reviewThreads" in joined and "isResolved" in joined
        assert "infiquetra" in joined and "7" in joined

    def test_a_pull_request_with_every_thread_resolved_has_none(self) -> None:
        runner = FakeGh(view=_clean_view(), threads=[True, True])
        assert RS.unresolved_review_threads("infiquetra/x", 7, runner=runner) == 0
        assert RS.unresolved_review_threads(
            "infiquetra/x", 7, runner=FakeGh(view=_clean_view())
        ) == 0

    def test_every_page_of_threads_is_read(self) -> None:
        runner = FakeGh(view=_clean_view(), thread_pages=[[True, False], [True], [False, False]])
        assert RS.unresolved_review_threads("infiquetra/x", 7, runner=runner) == 3
        assert runner.thread_calls == 3

    def test_an_unresolved_thread_holds_the_release_before_any_merge_call(self) -> None:
        runner = FakeGh(view=_clean_view(), threads=[True, False])
        state = self._release(runner)
        assert state["status"] == "waiting"
        assert state["unresolved_threads"] == 1
        assert "unresolved review thread" in state["reason"]
        assert not any("merge" in argv for argv in runner.calls)

    def test_unresolved_threads_on_a_later_page_still_hold_the_release(self) -> None:
        runner = FakeGh(view=_clean_view(), thread_pages=[[True] * 3, [True], [False]])
        state = self._release(runner)
        assert state["status"] == "waiting" and state["unresolved_threads"] == 1
        assert not any("merge" in argv for argv in runner.calls)

    def test_a_pull_request_with_all_threads_resolved_still_merges_bound_to_its_head(self) -> None:
        runner = FakeGh(
            view=_clean_view(), threads=[True, True], merged={"mergeCommit": {"oid": "b" * 40}}
        )
        state = self._release(runner)
        assert state["status"] == "merged"
        merge_argv = next(argv for argv in runner.calls if "merge" in argv)
        assert merge_argv[merge_argv.index("--match-head-commit") + 1] == "a" * 40
        graphql_at = next((i for i, argv in enumerate(runner.calls) if "graphql" in argv), None)
        merge_at = next(i for i, argv in enumerate(runner.calls) if "merge" in argv)
        assert graphql_at is not None, "the review threads were never read"
        assert graphql_at < merge_at

    def test_threads_are_read_whatever_the_merge_method(self) -> None:
        runner = FakeGh(view=_clean_view(), threads=[False])
        state = self._release(runner, merge_method="squash")
        assert state["status"] == "waiting" and state["unresolved_threads"] == 1

    def test_a_thread_read_that_fails_never_leads_to_a_merge(self) -> None:
        runner = FakeGh(view=_clean_view(), threads_ok=False)
        try:
            state = self._release(runner)
        except RS.ReleaseStepError:
            state = {"status": "refused-by-error"}
        assert state["status"] != "merged"
        assert not any("merge" in argv for argv in runner.calls)

    def test_a_failing_check_still_waits_without_asking_about_threads_first(self) -> None:
        view = _clean_view()
        view["mergeStateStatus"] = "UNSTABLE"
        runner = FakeGh(view=view, threads=[False])
        state = self._release(runner)
        assert state["status"] == "waiting"
        assert not any("merge" in argv for argv in runner.calls)


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
        return {**extra}

    def test_every_scenario_passing_is_a_pass(self) -> None:
        result = RS.record_functional_test(
            self._record(), [{"name": "a", "state": "passed"}, {"name": "b", "state": "passed"}]
        )
        assert result["status"] == "passed"
        assert result["post_merge_cycles"] == 0

    def _round(self, record: dict[str, Any], *names: str) -> dict[str, Any]:
        """One failing functional pass, recorded the way the caller stores it."""
        result = RS.record_functional_test(
            record, [{"name": name, "state": "failed"} for name in names]
        )
        record["functional_test"] = result
        return result

    def test_a_first_failure_re_enters_the_loop(self) -> None:
        result = self._round(self._record(), "a")
        assert result["status"] == "re-enters-the-build-loop"
        assert result["post_merge_cycles"] == 1
        assert result.get("early_stop") is False

    def test_a_second_failure_of_different_scenarios_re_enters_for_round_three(self) -> None:
        record = self._record()
        self._round(record, "a")
        result = self._round(record, "b")
        assert result["status"] == "re-enters-the-build-loop"
        assert result["post_merge_cycles"] == 2
        assert result.get("early_stop") is False and result.get("at_limit") is not True

    def test_the_same_failing_scenarios_in_round_two_stop_the_loop_early(self) -> None:
        record = self._record()
        self._round(record, "a", "b")
        result = self._round(record, "b", "a")
        assert result["status"] == "exhausted"
        assert result["early_stop"] is True
        assert result["post_merge_cycles"] == 2
        assert result.get("at_limit") is not True

    def test_a_subset_or_superset_of_the_failures_is_not_the_same_set(self) -> None:
        record = self._record()
        self._round(record, "a", "b")
        assert self._round(record, "a")["status"] == "re-enters-the-build-loop"
        record = self._record()
        self._round(record, "a")
        assert self._round(record, "a", "b")["status"] == "re-enters-the-build-loop"

    def test_round_three_stops_at_the_limit_with_no_fourth_round(self) -> None:
        record = self._record()
        self._round(record, "a")
        self._round(record, "b")
        result = self._round(record, "c")
        assert result["status"] == "exhausted"
        assert result["at_limit"] is True
        assert result["post_merge_cycles"] == 3
        assert "goes to the operator" in result["reason"] or "operator" in result["reason"]

    def test_round_three_failing_the_same_way_is_both_early_and_at_the_limit(self) -> None:
        record = self._record()
        self._round(record, "a")
        self._round(record, "b")
        result = self._round(record, "b")
        assert result["status"] == "exhausted"
        assert result["at_limit"] is True and result["early_stop"] is True

    def test_there_is_no_escalation_and_no_extension(self) -> None:
        record = self._record()
        for names in (("a",), ("b",), ("c",)):
            result = self._round(record, *names)
            assert result.get("extension_taken") is not True
        assert result["status"] == "exhausted"
        again = self._round(record, "d")
        assert again["status"] == "exhausted"
        assert again["post_merge_cycles"] <= RS.POST_MERGE_ROUND_LIMIT

    def test_the_round_limit_is_three_and_no_allowance_model_remains(self) -> None:
        assert RS.POST_MERGE_ROUND_LIMIT == 3
        assert not hasattr(RS, "post_merge_allowance")

    def test_a_generous_run_configuration_cannot_buy_more_post_merge_rounds(self) -> None:
        record: dict[str, Any] = {
            "run_configuration": {
                "standard_cycle_allowance": {"value": 9},
                "escalated_cycle_allowance": {"value": 9},
            }
        }
        for names in (("a",), ("b",)):
            self._round(record, *names)
        assert self._round(record, "c")["status"] == "exhausted"

    def test_a_pass_between_failures_is_a_pass_and_blocked_never_counts_a_round(self) -> None:
        record = self._record()
        self._round(record, "a")
        blocked = RS.record_functional_test(
            record,
            [{"name": "x", "state": "blocked", "cause": "no credential", "required": True}],
        )
        assert blocked["status"] == "blocked"
        assert blocked["post_merge_cycles"] == 1

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


REVIEWED = "c" * 40


def _combined(revision: str = REVIEWED, *, green: bool = True, waiver: str = "") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "pass": 2,
        "revision": revision,
        "status": "pass" if green else "fail",
        "green": green,
        "deploy": {"status": "pass"},
        "test": {"status": "pass" if green else "fail"},
        "teardown": {"status": "pass"},
    }
    if waiver:
        entry["waiver"] = {"level": "repository", "reason": waiver}
    return {
        "environment": {"kind": "ephemeral-stack", "scope": "private"},
        "passes": [entry],
        **({"handed_to_code_review": {"revision": revision, "pass": 2}} if green else {}),
    }


def _run(
    *,
    round_no: int = 3,
    blocking: tuple[str, ...] = (),
    filed: list[int] | None = None,
    decision: str = "merge-with-reason",
    revision: str = REVIEWED,
) -> dict:
    """A stored C1 review run, as ``review_run`` entries sit in ``review_cycles``.

    The reviewed revision is stored under every name a reader may use for it.
    """
    entry: dict[str, Any] = {
        "kind": "review_run",
        "schema": "review_records.v1",
        "card": 1028,
        "round": round_no,
        "head": revision,
        "revision": revision,
        "subject": {"head_sha": revision},
        "merge": {"allowed": not blocking, "blocking": list(blocking), "report_only_blocks": []},
    }
    if filed is not None:
        entry["merge_decision"] = {
            "decision": decision,
            "reason": "known and filed",
            "filed_issues": list(filed),
        }
    return entry


def _legacy_cap(*, residuals: list[int] | None = None, open_findings: int = 0) -> dict:
    """An entry of the retired result shape, kept in the record and never read."""
    return {
        "schema": "review_" + "result" + ".v2",
        "loop": "code_review",
        "unit": "issue-1028",
        "cycle": 5,
        "revision": REVIEWED,
        "outcome": "cycle_cap_best_available",
        "findings": [{"status": "open"} for _ in range(open_findings)],
        "residual_issues": residuals or [],
    }


class TestCloseCitesTheFunctionalEvidence:
    """The closeout cites the pre-review functional run and the residual issues (#100, #161).

    It reads C1 review runs and the operator's merge decision, never the retired result shape.
    """

    def _close(self, tmp_path: Path, record: dict[str, Any], capsys: Any) -> tuple[int, Any, str]:
        path = tmp_path / "issue-1028.json"
        path.write_text(json.dumps({"schema": "run_record.v1", "issue": 1028, **record}))
        code = RS.main(["--record", str(path), "close", "--disposition", "delivered"])
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err

    def test_the_delivered_closeout_cites_the_combined_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {"combined_branch": _combined(), "review_cycles": [_run(round_no=1)]}
        code, comment, err = self._close(tmp_path, record, capsys)
        assert code == 0, err
        line = comment["parts"]["pre_review_functional_evidence"]
        assert line == (
            f"pass 2 at {REVIEWED} (ephemeral-stack, private): deploy pass, test pass, "
            "teardown pass"
        )
        assert line in comment["body"]
        assert comment["parts"]["residual_issues"].startswith("none")

    def test_a_waived_run_prints_the_waiver_and_its_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {"combined_branch": _combined(waiver="docs only")}
        code, comment, err = self._close(tmp_path, record, capsys)
        assert code == 0, err
        assert comment["parts"]["pre_review_functional_evidence"].startswith("waived: docs only")
        assert "waived: docs only" in comment["body"]

    def test_the_operators_merge_with_reason_lists_the_filed_residual_issues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {
            "combined_branch": _combined(),
            "review_cycles": [_run(blocking=("rf:1", "rf:2"), filed=[301, 302])],
        }
        code, comment, err = self._close(tmp_path, record, capsys)
        assert code == 0, err
        assert comment["parts"]["residual_issues"] == "#301, #302"
        assert "#301, #302" in comment["body"]
        assert REVIEWED in comment["parts"]["pre_review_functional_evidence"]

    def test_the_closeout_reads_the_newest_review_runs_revision(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        older = _run(round_no=1, blocking=("rf:1",), revision="e" * 40)
        record = {"combined_branch": _combined(), "review_cycles": [older, _run(round_no=2)]}
        code, comment, err = self._close(tmp_path, record, capsys)
        assert code == 0, err
        assert REVIEWED in comment["parts"]["pre_review_functional_evidence"]

    def test_delivered_is_refused_when_the_merged_over_revision_has_no_functional_run(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for block in (None, _combined("d" * 40), _combined(green=False)):
            record: dict[str, Any] = {
                "review_cycles": [_run(blocking=("rf:1",), filed=[301])]
            }
            if block is not None:
                record["combined_branch"] = block
            code, _, err = self._close(tmp_path, record, capsys)
            assert code == 2
            assert REVIEWED in err
            assert "no passing combined-branch functional run and no waiver" in err

    def test_delivered_is_refused_when_blocking_items_outnumber_the_filed_issues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {
            "combined_branch": _combined(),
            "review_cycles": [_run(blocking=("rf:1", "rf:2"), filed=[301])],
        }
        code, _, err = self._close(tmp_path, record, capsys)
        assert code == 2
        assert REVIEWED in err

    def test_a_review_run_that_stopped_the_card_is_not_a_merge_over_blocking_items(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {
            "combined_branch": _combined(),
            "review_cycles": [_run(blocking=("rf:1",), filed=[], decision="stop-card")],
        }
        path = tmp_path / "issue-1028.json"
        path.write_text(json.dumps({"schema": "run_record.v1", "issue": 1028, **record}))
        code = RS.main(["--record", str(path), "close", "--disposition", "canceled"])
        assert code == 0, capsys.readouterr().err

    def test_legacy_entries_are_kept_in_the_record_and_never_read(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record = {
            "combined_branch": _combined(),
            "review_cycles": [_legacy_cap(residuals=[301], open_findings=3)],
        }
        code, comment, err = self._close(tmp_path, record, capsys)
        assert code == 0, err
        assert comment["parts"]["residual_issues"].startswith("none")
        assert comment["parts"]["pre_review_functional_evidence"].startswith("not recorded")

    def test_a_record_with_no_combined_run_records_the_absence_with_a_reason(self) -> None:
        comment = RS.closeout_comment({}, disposition="delivered")
        assert comment["parts"]["pre_review_functional_evidence"].startswith("not recorded: ")
        reviewed_only = {"review_cycles": [_run(round_no=1)]}
        line = RS.closeout_comment(reviewed_only, disposition="delivered")["parts"][
            "pre_review_functional_evidence"
        ]
        assert line == f"not recorded: no combined-branch functional pass at {REVIEWED}"

    def test_a_non_delivered_close_is_not_refused_over_blocking_items(self) -> None:
        record = {"review_cycles": [_run(blocking=("rf:1", "rf:2", "rf:3"), filed=[])]}
        comment = RS.closeout_comment(record, disposition="canceled")
        assert comment["closure_reason"] == "NOT_PLANNED"

    def test_the_cycle_cap_outcome_of_the_retired_result_shape_is_gone(self) -> None:
        assert not hasattr(RS, "CYCLE_CAP_OUTCOME")

    def test_the_evidence_parts_follow_the_required_ones_and_leave_them_unchanged(self) -> None:
        assert set(RS.EVIDENCE_PARTS).isdisjoint(RS.CLOSEOUT_PARTS)
        keys = list(RS.closeout_comment({}, disposition="delivered")["parts"])
        assert keys[-2:] == list(RS.EVIDENCE_PARTS)


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


# --- merge outcomes to Langfuse (issue 166) ------------------------------------------------------


@pytest.fixture
def lf_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Fake saga keys, a temporary home, and no operator Langfuse variables."""
    import os

    for name in list(os.environ):
        if name.startswith(("SAGA_LANGFUSE_", "LANGFUSE_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("SAGA_LANGFUSE_PUBLIC_KEY", "pk-lf-SENTINEL-public")
    monkeypatch.setenv("SAGA_LANGFUSE_SECRET_KEY", "sk-lf-SENTINEL-secret")
    monkeypatch.setenv("SAGA_LANGFUSE_HOST", "https://langfuse.example.test")
    home = tmp_path / "operator-home"
    monkeypatch.setenv("HOME", str(home))
    return home


class _LfOpener:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float | None = None) -> Any:
        self.requests.append(request)
        return _LfResponse()


class _LfResponse:
    status = 200

    def read(self) -> bytes:
        return b"{}"

    def getcode(self) -> int:
        return 200

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _outcome_record(tmp_path: Path) -> Path:
    fixture = REPO_ROOT / "plugins/saga/tests/fixtures/review_records/valid/review_run.json"
    run = json.loads(fixture.read_text(encoding="utf-8"))
    run["loop"] = "review_run"
    run["findings"][0]["merge_outcome"] = {"outcome": "dismissed", "reason": "false positive"}
    path = tmp_path / "record.json"
    path.write_text(json.dumps({"issue": 7, "repo": "example/repo", "review_cycles": [run]}),
                    encoding="utf-8")
    return path


def _merged_gh() -> FakeGh:
    return FakeGh(view=_clean_view(), merged={"mergeCommit": {"oid": "b" * 40}, "url": "u"})


def test_release_merged_posts_outcomes_once(
    tmp_path: Path, lf_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _outcome_record(tmp_path)
    gh = _merged_gh()
    opener = _LfOpener()
    code = RS.main(["--record", str(record), "release", "--pull-request", "5",
                    "--repo-path", str(tmp_path)], runner=gh, trace_opener=opener)
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "merged"
    assert gh.calls and all(argv[0] == "gh" for argv in gh.calls)
    scores = [json.loads(r.data.decode()) for r in opener.requests]
    assert len(scores) == 1
    assert (scores[0]["name"], scores[0]["value"], scores[0]["comment"]) == (
        "merge-outcome", "dismissed", "false positive")


def test_release_waiting_or_refused_posts_nothing(
    tmp_path: Path, lf_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    trace = _load("review_trace")
    monkeypatch.setattr(trace, "post_outcomes", lambda *a, **k: calls.append(a) or {})
    record = _outcome_record(tmp_path)
    blocked = FakeGh(view={**_clean_view(), "mergeStateStatus": "BLOCKED"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=blocked) == 0
    refused = FakeGh(view=_clean_view(), merge_ok=False)
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=refused) == 0
    assert calls == []


def test_release_outcome_failure_keeps_output(
    tmp_path: Path, lf_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    record = _outcome_record(tmp_path)
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=_merged_gh(), trace_opener=_LfOpener()) == 0
    good = capsys.readouterr().out

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("posting bug")

    trace = _load("review_trace")
    monkeypatch.setattr(trace, "post_outcomes", broken)
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=_merged_gh()) == 0
    out = capsys.readouterr()
    assert out.out == good
    assert "langfuse: outcomes not posted (RuntimeError)" in out.err


def test_release_dry_run_posts_nothing(tmp_path: Path, lf_env: Path) -> None:
    record = _outcome_record(tmp_path)
    opener = _LfOpener()
    gh = _merged_gh()
    assert RS.main(["--record", str(record), "release", "--pull-request", "5", "--dry-run"],
                   runner=gh, trace_opener=opener) == 0
    assert opener.requests == [] and gh.calls == []


def _stored_record(tmp_path: Path, *, repo: str | None = "example/repo",
                   heads: tuple[str, ...] = ()) -> Path:
    """A record whose review runs sit at *heads*, round 1 first. No ``repo`` when None."""
    fixture = REPO_ROOT / "plugins/saga/tests/fixtures/review_records/valid/review_run.json"
    runs = []
    for position, head in enumerate(heads, start=1):
        run = json.loads(fixture.read_text(encoding="utf-8"))
        run["loop"] = "review_run"
        run["round"] = position
        run["head"] = head
        runs.append(run)
    record: dict[str, Any] = {"issue": 7, "review_cycles": runs}
    if repo is not None:
        record["repo"] = repo
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_a_merged_release_writes_the_reviewed_head_landed_commit_pull_request_and_method(
    tmp_path: Path, lf_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head, landed = "b" * 40, "c" * 40
    record = _stored_record(tmp_path, heads=(head,))
    gh = FakeGh(view=_clean_view(head), merged={"mergeCommit": {"oid": landed}, "url": "u"})
    code = RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=gh, trace_opener=_LfOpener())
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["reviewed_head"] == head
    assert stored["landed_commit"] == landed
    assert stored["pull_request"] == 5
    assert stored["merge_method"] == "merge"
    assert stored == {**printed, "review_run_id": stored["review_run_id"],
                      "review_run_reason": stored["review_run_reason"]}
    trace = _load("review_trace")
    run = json.loads(record.read_text(encoding="utf-8"))["review_cycles"][0]
    assert stored["review_run_id"] == trace.review_trace_id(run, "example/repo")
    assert stored["review_run_reason"] is None


def test_a_waiting_and_a_refused_release_write_no_landed_commit(tmp_path: Path) -> None:
    record = _stored_record(tmp_path, heads=("b" * 40,))
    blocked = FakeGh(view={**_clean_view(), "mergeStateStatus": "BLOCKED"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=blocked) == 0
    waiting = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert waiting["status"] == "waiting" and "landed_commit" not in waiting
    refused = FakeGh(view=_clean_view(), merge_ok=False)
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=refused) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["status"] == "refused" and "landed_commit" not in stored


def test_a_dry_run_writes_nothing_to_the_record(tmp_path: Path) -> None:
    record = _stored_record(tmp_path, heads=("b" * 40,))
    before = record.read_bytes()
    assert RS.main(["--record", str(record), "release", "--pull-request", "5", "--dry-run"],
                   runner=_merged_gh()) == 0
    assert record.read_bytes() == before


def test_a_release_keeps_keys_other_writers_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head, landed = "b" * 40, "c" * 40
    record = _stored_record(tmp_path, heads=(head,))
    raw = json.loads(record.read_text(encoding="utf-8"))
    raw["qa"] = {"verdict": "pass"}
    record.write_text(json.dumps(raw), encoding="utf-8")
    real_release = RS.release

    def release_then_usage(**kwargs: Any) -> dict[str, Any]:
        state = real_release(**kwargs)
        concurrent = json.loads(record.read_text(encoding="utf-8"))
        concurrent["units"] = [{"usage": {"worker": {"output": 3}}}]
        record.write_text(json.dumps(concurrent), encoding="utf-8")
        return state

    monkeypatch.setattr(RS, "release", release_then_usage)
    gh = FakeGh(view=_clean_view(head), merged={"mergeCommit": {"oid": landed}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))
    assert stored["release"]["landed_commit"] == landed
    assert stored["qa"] == {"verdict": "pass"}
    assert stored["units"] == [{"usage": {"worker": {"output": 3}}}]


def test_the_review_link_matches_the_latest_round_at_the_reviewed_head(tmp_path: Path) -> None:
    head = "b" * 40
    record = _stored_record(tmp_path, heads=("a" * 40, head, head))
    gh = FakeGh(view=_clean_view(head), merged={"mergeCommit": {"oid": "c" * 40}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    trace = _load("review_trace")
    runs = json.loads(record.read_text(encoding="utf-8"))["review_cycles"]
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["review_run_id"] == trace.review_trace_id(runs[2], "example/repo")
    assert runs[2]["round"] == 3


def test_no_matching_run_records_null_with_a_reason(tmp_path: Path) -> None:
    record = _stored_record(tmp_path, heads=("a" * 40,))
    gh = FakeGh(view=_clean_view("b" * 40), merged={"mergeCommit": {"oid": "c" * 40}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["review_run_id"] is None
    assert stored["review_run_reason"] == "no-matching-run"


def test_an_unresolvable_slug_records_null_with_a_reason(tmp_path: Path) -> None:
    record = _stored_record(tmp_path, repo=None, heads=("b" * 40,))
    gh = FakeGh(view=_clean_view("b" * 40), merged={"mergeCommit": {"oid": "c" * 40}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["review_run_id"] is None
    assert stored["review_run_reason"] == "slug-unknown"


def test_a_broken_trace_module_still_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _stored_record(tmp_path, heads=("b" * 40,))
    monkeypatch.setitem(sys.modules, "review_trace", None)
    gh = FakeGh(view=_clean_view("b" * 40), merged={"mergeCommit": {"oid": "c" * 40}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["review_run_id"] is None
    assert stored["review_run_reason"] == "review-trace-unavailable"


def test_deploy_and_close_read_the_written_block_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head, landed = "b" * 40, "c" * 40
    record = _stored_record(tmp_path, heads=(head,))
    gh = FakeGh(view=_clean_view(head), merged={"mergeCommit": {"oid": landed}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"], runner=gh) == 0
    capsys.readouterr()
    assert RS.main(["--record", str(record), "deploy", "--saga-id", "s7"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no-destination"
    assert RS.main(["--record", str(record), "close", "--disposition", "delivered"]) == 0
    comment = json.loads(capsys.readouterr().out)
    assert comment["parts"]["delivered_revision"] == landed


def test_a_release_with_no_review_runs_still_writes_the_block_with_null_link(
    tmp_path: Path,
) -> None:
    """Merging with empty review cycles writes the block; the link is null with a reason."""
    record = _stored_record(tmp_path, heads=())
    gh = FakeGh(view=_clean_view("a" * 40),
                merged={"mergeCommit": {"oid": "b" * 40}, "url": "u"})
    assert RS.main(["--record", str(record), "release", "--pull-request", "5"],
                   runner=gh, trace_opener=None) == 0
    stored = json.loads(record.read_text(encoding="utf-8"))["release"]
    assert stored["landed_commit"] == "b" * 40
    assert "review_run_id" in stored and "review_run_reason" in stored
    assert stored["review_run_id"] is None
    assert stored["review_run_reason"] == "no-matching-run"
