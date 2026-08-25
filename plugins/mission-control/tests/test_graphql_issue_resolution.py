"""Regression tests for issue/PR GraphQL node resolution."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


def _single_project_config() -> dict:
    return {
        "project_mappings": {
            "projects": {
                "campps": {
                    "id": "PVT_campps",
                    "number": 4,
                    "name": "CAMPPS",
                    "repositories": ["infiquetra-claude-plugins"],
                }
            }
        }
    }


def test_item_node_query_uses_issue_or_pull_request_union() -> None:
    assert "issueOrPullRequest(number: $number)" in sdlc_manager.QUERY_GET_ITEM_NODE_ID
    assert "... on Issue" in sdlc_manager.QUERY_GET_ITEM_NODE_ID
    assert "... on PullRequest" in sdlc_manager.QUERY_GET_ITEM_NODE_ID
    assert "issue(number: $number)" not in sdlc_manager.QUERY_GET_ITEM_NODE_ID
    assert "pullRequest(number: $number)" not in sdlc_manager.QUERY_GET_ITEM_NODE_ID


def test_label_query_uses_issue_or_pull_request_union() -> None:
    assert "issueOrPullRequest(number: $number)" in sdlc_manager.QUERY_GET_ITEM_LABELS
    assert "... on Issue" in sdlc_manager.QUERY_GET_ITEM_LABELS
    assert "... on PullRequest" in sdlc_manager.QUERY_GET_ITEM_LABELS
    assert "issue(number: $number)" not in sdlc_manager.QUERY_GET_ITEM_LABELS
    assert "pullRequest(number: $number)" not in sdlc_manager.QUERY_GET_ITEM_LABELS


def test_issue_union_node_resolves_to_content_id() -> None:
    repo_data = {
        "issueOrPullRequest": {
            "__typename": "Issue",
            "id": "I_issue",
            "number": 280,
            "title": "issue",
        }
    }

    assert sdlc_manager._issue_or_pull_request_node(repo_data) == repo_data["issueOrPullRequest"]


def test_pull_request_union_node_resolves_to_content_id() -> None:
    repo_data = {
        "issueOrPullRequest": {
            "__typename": "PullRequest",
            "id": "PR_node",
            "number": 42,
            "title": "pr",
        }
    }

    assert sdlc_manager._issue_or_pull_request_node(repo_data) == repo_data["issueOrPullRequest"]


def test_missing_union_node_returns_none() -> None:
    assert sdlc_manager._issue_or_pull_request_node({"issueOrPullRequest": None}) is None
    assert sdlc_manager._issue_or_pull_request_node({"repository": None}) is None


def test_get_item_labels_treats_null_repository_as_no_labels() -> None:
    with patch.object(sdlc_manager, "_graphql", return_value={"repository": None}):
        labels = sdlc_manager._get_item_labels("infiquetra-claude-plugins", 280)

    assert labels == []


def test_get_item_labels_reads_issue_union_node() -> None:
    response = {
        "repository": {
            "issueOrPullRequest": {
                "__typename": "Issue",
                "labels": {"nodes": [{"name": "hermes-task"}, {"name": "needs-plan"}]},
            }
        }
    }

    with patch.object(sdlc_manager, "_graphql", return_value=response):
        labels = sdlc_manager._get_item_labels("infiquetra-claude-plugins", 280)

    assert labels == ["hermes-task", "needs-plan"]


def test_get_item_labels_reads_pull_request_union_node() -> None:
    response = {
        "repository": {
            "issueOrPullRequest": {
                "__typename": "PullRequest",
                "labels": {"nodes": [{"name": "review"}]},
            }
        }
    }

    with patch.object(sdlc_manager, "_graphql", return_value=response):
        labels = sdlc_manager._get_item_labels("infiquetra-claude-plugins", 42)

    assert labels == ["review"]


def test_graphql_stays_strict_on_data_with_errors() -> None:
    envelope = {
        "data": {
            "updateProjectV2ItemFieldValue": None,
        },
        "errors": [{"type": "FORBIDDEN", "message": "field update denied"}],
    }

    with (
        patch.object(sdlc_manager, "_gh", return_value=json.dumps(envelope)),
        pytest.raises(RuntimeError, match="GraphQL errors"),
    ):
        sdlc_manager._graphql("mutation { updateProjectV2ItemFieldValue { id } }")


def test_graphql_stays_strict_on_null_data_with_errors() -> None:
    envelope = {
        "data": None,
        "errors": [{"type": "NOT_FOUND", "message": "repository unavailable"}],
    }

    with (
        patch.object(sdlc_manager, "_gh", return_value=json.dumps(envelope)),
        pytest.raises(RuntimeError, match="GraphQL errors"),
    ):
        sdlc_manager._graphql("query { repository { issueOrPullRequest { id } } }")


def test_graphql_re_raises_gh_error_with_partial_stdout() -> None:
    partial_error = {
        "data": {
            "repository": {
                "issue": {"id": "I_issue", "number": 280},
                "pullRequest": None,
            }
        },
        "errors": [
            {
                "type": "NOT_FOUND",
                "path": ["repository", "pullRequest"],
                "message": "Could not resolve to a PullRequest with the number of 280.",
            }
        ],
    }
    gh_error = sdlc_manager.GhApiError(
        "gh command failed: partial GraphQL error",
        stdout=json.dumps(partial_error),
    )

    with (
        patch.object(sdlc_manager, "_gh", side_effect=gh_error),
        pytest.raises(sdlc_manager.GhApiError) as exc_info,
    ):
        sdlc_manager._graphql("query { repository { issue { id } pullRequest { id } } }")

    assert exc_info.value is gh_error


@pytest.mark.parametrize("stdout", ["", "not json"])
def test_graphql_re_raises_gh_error_with_empty_or_malformed_stdout(stdout: str) -> None:
    gh_error = sdlc_manager.GhApiError("gh command failed", stdout=stdout)

    with (
        patch.object(sdlc_manager, "_gh", side_effect=gh_error),
        pytest.raises(sdlc_manager.GhApiError) as exc_info,
    ):
        sdlc_manager._graphql("query { repository { issueOrPullRequest { id } } }")

    assert exc_info.value is gh_error


def test_board_add_treats_null_repository_as_missing_issue(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(sdlc_manager, "_graphql", return_value={"repository": None}),
        pytest.raises(SystemExit) as exc_info,
    ):
        sdlc_manager.board_add(
            "infiquetra-claude-plugins",
            280,
            fmt="text",
            config=_single_project_config(),
            project_name="campps",
        )

    assert exc_info.value.code == 1
    assert "Could not find issue/PR #280" in capsys.readouterr().err
