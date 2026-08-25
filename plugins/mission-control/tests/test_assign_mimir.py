"""Contract tests for the fail-closed ``flow assign-mimir`` operator command."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402, I001


REPO = "mimir-pilot-claude-plugins"
ISSUE = {
    "state": "open",
    "html_url": f"https://github.com/infiquetra/{REPO}/issues/10",
    "labels": [],
}
TRIGGERED_ISSUE = {**ISSUE, "labels": [{"name": "intake:mimir"}]}
COVERAGE = {
    "policy_version": "repository-coverage/v1",
    "repository": f"infiquetra/{REPO}",
    "route": "pilot",
}


def _coverage_document(
    repository: str = f"infiquetra/{REPO}",
    *,
    state: str = "active",
    policy_version: str = "repository-coverage/v1",
    events: str = "[issues, pull_request]",
) -> str:
    text = f"""repository_coverage:
  schema_version: 1
  policy_version: {policy_version}
  default_disposition: quarantine
  repositories:
    - repository: {repository}
      state: {state}
      route: pilot
      events: {events}
"""
    return base64.b64encode(text.encode()).decode()


def _assign_rest_reads(*, initial: dict = ISSUE, readback: dict = TRIGGERED_ISSUE):
    return [
        initial,
        {"permission": "admin", "role_name": "admin"},
        {"name": "intake:mimir"},
        readback,
    ]


def test_live_coverage_requires_one_active_exact_issue_route() -> None:
    with patch.object(sdlc_manager, "_gh", return_value=_coverage_document()):
        assert sdlc_manager._load_live_mimir_coverage(REPO) == COVERAGE


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_coverage_document("infiquetra/other"), "not uniquely covered"),
        (_coverage_document(state="quarantine"), "not active"),
        (
            _coverage_document(policy_version="repository-coverage/v2"),
            "policy is unsupported",
        ),
        (_coverage_document(events="not-a-list"), "not active"),
        (base64.b64encode(b"not: [valid").decode(), "unreadable"),
    ],
)
def test_live_coverage_rejects_uncovered_inactive_or_malformed(payload: str, message: str) -> None:
    with (
        patch.object(sdlc_manager, "_gh", return_value=payload),
        pytest.raises(RuntimeError, match=message),
    ):
        sdlc_manager._load_live_mimir_coverage(REPO)


def test_assign_mimir_applies_trigger_once_and_reports_live_state() -> None:
    objectives = [{"project": "Operations", "project_number": 3, "value": "team-mimir"}]
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(sdlc_manager, "_rest_get", side_effect=_assign_rest_reads()),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        patch.object(sdlc_manager, "_mimir_objective_fields", return_value=objectives),
        patch.object(sdlc_manager, "_out") as out,
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")

    rest_post.assert_called_once_with(
        f"repos/infiquetra/{REPO}/issues/10/labels", {"labels": ["intake:mimir"]}
    )
    result = out.call_args.args[0]
    assert result["issue_url"] == ISSUE["html_url"]
    assert result["trigger"] == {"label": "intake:mimir", "state": "applied"}
    assert result["objective_fields"] == objectives
    assert result["expected_team_mimir_route"] == "pilot"
    assert result["authority"] == "admin"


def test_assign_mimir_is_idempotent_when_trigger_already_present() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(
            sdlc_manager,
            "_rest_get",
            side_effect=_assign_rest_reads(initial=TRIGGERED_ISSUE),
        ),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        patch.object(sdlc_manager, "_mimir_objective_fields", return_value=[]),
        patch.object(sdlc_manager, "_out") as out,
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")

    rest_post.assert_not_called()
    assert out.call_args.args[0]["trigger"]["state"] == "already-triggered"


def test_assign_mimir_uses_effective_permission_for_custom_repository_role() -> None:
    reads = _assign_rest_reads(initial=TRIGGERED_ISSUE)
    reads[1] = {"permission": "write", "role_name": "custom-issue-operator"}
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(sdlc_manager, "_rest_get", side_effect=reads),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        patch.object(sdlc_manager, "_mimir_objective_fields", return_value=[]),
        patch.object(sdlc_manager, "_out") as out,
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")

    rest_post.assert_not_called()
    assert out.call_args.args[0]["authority"] == "write"


def test_assign_mimir_rejects_closed_issue_before_authority_or_mutation() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_rest_get", return_value={**ISSUE, "state": "closed"}),
        patch.object(sdlc_manager, "_fetch_gh_login") as login,
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        pytest.raises(RuntimeError, match="not open"),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    login.assert_not_called()
    rest_post.assert_not_called()


@pytest.mark.parametrize("role", ["read", None])
def test_assign_mimir_rejects_insufficient_authority_without_mutation(role: str | None) -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="viewer"),
        patch.object(sdlc_manager, "_rest_get", side_effect=[ISSUE, {"permission": role}]),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        pytest.raises(RuntimeError, match="insufficient authority"),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    rest_post.assert_not_called()


def test_assign_mimir_rejects_unverified_principal_without_mutation() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value=None),
        patch.object(sdlc_manager, "_rest_get", return_value=ISSUE),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        pytest.raises(RuntimeError, match="principal could not be verified"),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    rest_post.assert_not_called()


def test_assign_mimir_reports_missing_trigger_label_without_creating_it() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(
            sdlc_manager,
            "_rest_get",
            side_effect=[
                ISSUE,
                {"permission": "write"},
                sdlc_manager.ApiNotFoundError("missing", status_code=404),
            ],
        ),
        patch.object(sdlc_manager, "_rest_post") as rest_post,
        pytest.raises(RuntimeError, match="Required trigger label.*missing"),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    rest_post.assert_not_called()


def test_assign_mimir_propagates_mutation_failure_without_success_output() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(sdlc_manager, "_rest_get", side_effect=_assign_rest_reads()[:3]),
        patch.object(
            sdlc_manager,
            "_rest_post",
            side_effect=sdlc_manager.ApiAuthError("forbidden", status_code=403),
        ),
        patch.object(sdlc_manager, "_out") as out,
        pytest.raises(sdlc_manager.ApiAuthError),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    out.assert_not_called()


def test_assign_mimir_fails_when_label_is_absent_from_readback() -> None:
    with (
        patch.object(sdlc_manager, "_load_live_mimir_coverage", return_value=COVERAGE),
        patch.object(sdlc_manager, "_fetch_gh_login", return_value="operator"),
        patch.object(
            sdlc_manager,
            "_rest_get",
            side_effect=_assign_rest_reads(readback=ISSUE),
        ),
        patch.object(sdlc_manager, "_rest_post"),
        patch.object(sdlc_manager, "_out") as out,
        pytest.raises(RuntimeError, match="refusing success"),
    ):
        sdlc_manager.flow_assign_mimir(REPO, 10, "json")
    out.assert_not_called()


def test_objective_fields_reports_only_live_objective_values() -> None:
    response = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        {
                            "project": {"title": "Operations", "number": 3},
                            "fieldValues": {
                                "nodes": [
                                    {"name": "Active", "field": {"name": "Status"}},
                                    {"name": "team-mimir", "field": {"name": "Objective"}},
                                ]
                            },
                        }
                    ]
                }
            }
        }
    }
    with patch.object(sdlc_manager, "_graphql", return_value=response):
        assert sdlc_manager._mimir_objective_fields(REPO, 10) == [
            {"project": "Operations", "project_number": 3, "value": "team-mimir"}
        ]


def test_cli_dispatches_assign_mimir_with_normalized_repo() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "--format",
                "json",
                "flow",
                "assign-mimir",
                "--repo",
                f"infiquetra/{REPO}",
                "--number",
                "10",
            ],
        ),
        patch.object(sdlc_manager, "flow_assign_mimir") as assign,
    ):
        sdlc_manager.main()
    assign.assert_called_once_with(REPO, 10, "json")
