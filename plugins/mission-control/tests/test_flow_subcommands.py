"""Tests for the `flow` subcommand group helpers.

These tests focus on the *logic* of the flow helpers — argument validation,
idempotency handling, error classification — without making real GitHub or
GraphQL calls. The `_gh`, `_graphql`, `_rest_get`, `_rest_post`, `_rest_delete` helpers are
patched at the sdlc_manager-module level.

End-to-end tests (real `gh` calls against a fixture project) are tracked
as a P3 follow-up.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

# --- flow_link_sub_issue ----------------------------------------------------


def test_link_sub_issue_idempotent_on_already_exists() -> None:
    """A duplicate POST returns HTTP 422 with 'already exists'; we treat
    this as success, not failure (idempotency contract).

    Phase C foundation: the contract is now expressed via the typed
    `ApiAlreadyExists` exception (raised by `_classify_gh_error`), not
    string-matching. See test_typed_exceptions.py for the classifier tests."""
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_get.side_effect = [
            {"id": 12345},  # child
            {"id": 67890, "title": "parent issue"},  # parent (no pull_request key)
        ]
        mock_post.side_effect = sdlc_manager.ApiAlreadyExists(
            "API call failed: HTTP 422 sub-issue already exists",
            status_code=422,
        )

        sdlc_manager.flow_link_sub_issue("campps-context-library", 1, "campps-mvp", 42, fmt="text")

        # Should NOT have raised; should have called _out with idempotent message
        msgs = [c.args[0] for c in mock_out.call_args_list]
        assert any("Already linked" in m for m in msgs), (
            f"Expected idempotent success message; got: {msgs}"
        )


def test_link_sub_issue_raises_on_real_error() -> None:
    """A non-422 error (auth, server, network) must propagate, not get
    swallowed as 'already exists'."""
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
    ):
        mock_get.side_effect = [
            {"id": 12345},
            {"id": 67890},
        ]
        mock_post.side_effect = RuntimeError("API call failed: 500 Internal Server Error")

        with pytest.raises(RuntimeError, match="500"):
            sdlc_manager.flow_link_sub_issue(
                "campps-context-library", 1, "campps-mvp", 42, fmt="text"
            )


def test_link_sub_issue_rejects_pr_as_parent() -> None:
    """The sub-issue API requires an issue parent, not a PR. The flow
    helper must detect this before POSTing — error message points at it."""
    with patch.object(sdlc_manager, "_rest_get") as mock_get:
        mock_get.side_effect = [
            {"id": 12345},  # child
            {
                "id": 67890,
                "pull_request": {"url": "..."},
            },  # parent has pull_request key → it's a PR
        ]
        with pytest.raises(RuntimeError, match="parent.*PR.*not an issue|Parent.*is a PR"):
            sdlc_manager.flow_link_sub_issue("campps-mvp", 1, "campps-mvp", 42, fmt="text")


def test_link_sub_issue_rejects_missing_child_db_id() -> None:
    """If the child fetch returns no integer id (corrupt payload, network
    truncation), the helper must raise — never POST with a bad sub_issue_id."""
    with patch.object(sdlc_manager, "_rest_get") as mock_get:
        mock_get.return_value = {"id": None}
        with pytest.raises(RuntimeError, match="no integer 'id'|Cannot link"):
            sdlc_manager.flow_link_sub_issue("r", 1, "r", 2, fmt="text")


# --- flow_unlink_sub_issue --------------------------------------------------


def test_unlink_sub_issue_deletes_verified_relationship() -> None:
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_delete") as mock_delete,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_get.side_effect = [
            {"id": 12345},
            {"id": 67890, "title": "parent issue"},
        ]

        sdlc_manager.flow_unlink_sub_issue("parent", 1, "child", 2, fmt="text")

    mock_delete.assert_called_once_with(
        "repos/infiquetra/parent/issues/1/sub_issue",
        {"sub_issue_id": 12345},
    )
    assert any("Unlinked child#2 from parent#1" in c.args[0] for c in mock_out.call_args_list)


def test_unlink_sub_issue_is_idempotent_after_issue_verification() -> None:
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_delete") as mock_delete,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_get.side_effect = [{"id": 12345}, {"id": 67890}]
        mock_delete.side_effect = sdlc_manager.ApiNotFoundError(
            "relationship absent",
            status_code=404,
        )

        sdlc_manager.flow_unlink_sub_issue("parent", 1, "child", 2, fmt="text")

    assert any("Already unlinked" in c.args[0] for c in mock_out.call_args_list)


def test_unlink_sub_issue_rejects_missing_child_db_id() -> None:
    with (
        patch.object(sdlc_manager, "_rest_get", return_value={"id": None}),
        pytest.raises(RuntimeError, match="no integer 'id'|Cannot unlink"),
    ):
        sdlc_manager.flow_unlink_sub_issue("r", 1, "r", 2, fmt="text")


# --- flow_verify_label ------------------------------------------------------


def test_verify_label_no_op_when_label_exists() -> None:
    """Probe returns 200 → label exists → no POST, just a 'no-op' message."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_gh.return_value = '{"name":"high-priority","color":"D93F0B"}'
        sdlc_manager.flow_verify_label(
            "campps-mvp", "high-priority", "D93F0B", "High priority", fmt="text"
        )
        mock_post.assert_not_called()
        msgs = [c.args[0] for c in mock_out.call_args_list]
        assert any("already exists" in m for m in msgs)


def test_verify_label_creates_on_404() -> None:
    """Probe raises ApiNotFound (typed 404) → POST creates the label."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out"),
    ):
        mock_gh.side_effect = sdlc_manager.ApiNotFound(
            "API call failed: HTTP 404",
            status_code=404,
        )
        sdlc_manager.flow_verify_label(
            "campps-mvp", "high-priority", "D93F0B", "High priority", fmt="text"
        )
        mock_post.assert_called_once()
        body = mock_post.call_args.args[1]
        assert body["name"] == "high-priority"
        assert body["color"] == "D93F0B"  # leading '#' stripped if any
        assert body["description"] == "High priority"


def test_verify_label_strips_leading_hash_from_color() -> None:
    """Operators may pass '#D93F0B' (with leading hash). GitHub API rejects
    it; the helper strips it before POST."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
    ):
        mock_gh.side_effect = sdlc_manager.ApiNotFound(
            "API call failed: HTTP 404",
            status_code=404,
        )
        sdlc_manager.flow_verify_label("r", "label", "#ABCDEF", None, fmt="text")
        body = mock_post.call_args.args[1]
        assert body["color"] == "ABCDEF"


def test_verify_label_does_NOT_create_on_non_404_error() -> None:
    """Auth / rate-limit / server errors must propagate — silently treating
    them as 'missing' would mask real problems and create labels under wrong
    auth context. With the typed-exception refactor, ApiAuthError /
    ApiRateLimited / generic GhApiError propagate out of the `except
    ApiNotFound:` block."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
    ):
        mock_gh.side_effect = sdlc_manager.ApiAuthError(
            "API call failed: HTTP 401 Bad credentials",
            status_code=401,
        )
        with pytest.raises(sdlc_manager.ApiAuthError):
            sdlc_manager.flow_verify_label("r", "label", None, None, fmt="text")
        mock_post.assert_not_called()


# --- flow_field_options + flow_set_field -----------------------------------


def test_normalize_repo_arg_strips_matching_owner() -> None:
    assert sdlc_manager._normalize_repo_arg("infiquetra/team-freya") == "team-freya"
    assert sdlc_manager._normalize_repo_arg("team-freya") == "team-freya"


def test_normalize_repo_arg_rejects_foreign_owner() -> None:
    with (
        pytest.raises(SystemExit),
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "labels",
                "audit",
                "--repo",
                "not-infiquetra/team-freya",
            ],
        ),
    ):
        sdlc_manager.main()


def test_cli_repo_arg_normalizes_owner_before_dispatch() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "labels",
                "audit",
                "--repo",
                "infiquetra/infiquetra-claude-plugins",
            ],
        ),
        patch.object(sdlc_manager, "labels_audit") as labels_audit,
    ):
        sdlc_manager.main()

    labels_audit.assert_called_once_with("infiquetra-claude-plugins", "text")


def test_cli_link_sub_issue_normalizes_parent_and_child_repos() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "link-sub-issue",
                "--parent-repo",
                "infiquetra/parent-repo",
                "--parent-number",
                "1",
                "--child-repo",
                "infiquetra/child-repo",
                "--child-number",
                "2",
            ],
        ),
        patch.object(sdlc_manager, "flow_link_sub_issue") as link_sub_issue,
    ):
        sdlc_manager.main()

    link_sub_issue.assert_called_once_with("parent-repo", 1, "child-repo", 2, "text")


def test_cli_unlink_sub_issue_normalizes_parent_and_child_repos() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "unlink-sub-issue",
                "--parent-repo",
                "infiquetra/parent-repo",
                "--parent-number",
                "1",
                "--child-repo",
                "infiquetra/child-repo",
                "--child-number",
                "2",
            ],
        ),
        patch.object(sdlc_manager, "flow_unlink_sub_issue") as unlink_sub_issue,
    ):
        sdlc_manager.main()

    unlink_sub_issue.assert_called_once_with("parent-repo", 1, "child-repo", 2, "text")


def test_field_options_reads_live_from_graphql() -> None:
    """field-options is a live discovery — never cached. Call must hit
    QUERY_GET_PROJECT_FIELDS."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_load.return_value = {
            "project_mappings": {
                "projects": {"mount-olympus": {"number": 1, "name": "Olympus"}},
            }
        }
        mock_gql.return_value = {
            "organization": {
                "projectV2": {
                    "id": "PVT_kwx",
                    "fields": {
                        "nodes": [
                            {
                                "id": "FLD_kwabc",
                                "name": "Initiative",
                                "options": [
                                    {"id": "opt1", "name": "olympus-quality"},
                                    {"id": "opt2", "name": "olympus-performance"},
                                ],
                            }
                        ]
                    },
                }
            }
        }
        sdlc_manager.flow_field_options("mount-olympus", "Initiative", fmt="json")
        # Verify it called the GraphQL query (no caching)
        assert mock_gql.called
        # Verify output contains both options with their (live) IDs
        out_payload = mock_out.call_args.args[0]
        names = [o["name"] for o in out_payload]
        assert "olympus-quality" in names
        assert "olympus-performance" in names


def test_set_field_raises_with_helpful_message_on_unknown_option() -> None:
    """If the operator passes an option that doesn't exist on the field,
    the error must list the actual options so they can correct."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
    ):
        mock_load.return_value = {
            "project_mappings": {
                "projects": {"mount-olympus": {"number": 1, "name": "Olympus"}},
            }
        }
        mock_gql.return_value = {
            "organization": {
                "projectV2": {
                    "id": "PVT_kwx",
                    "fields": {
                        "nodes": [
                            {
                                "id": "FLD_kwabc",
                                "name": "Initiative",
                                "options": [
                                    {"id": "o1", "name": "olympus-quality"},
                                    {"id": "o2", "name": "olympus-performance"},
                                ],
                            }
                        ]
                    },
                }
            }
        }
        with pytest.raises(RuntimeError) as exc:
            sdlc_manager.flow_set_field(
                "mount-olympus",
                "campps-mvp",
                42,
                "Initiative",
                "nonexistent-option",
                fmt="text",
            )
        msg = str(exc.value)
        assert "nonexistent-option" in msg
        # Helpful: includes the actual options + the discovery command hint
        assert "olympus-quality" in msg or "olympus-performance" in msg
        assert "field-options" in msg


def test_field_write_resolves_or_fails_loud() -> None:
    """A board/field write must resolve the option's CURRENT live id every
    call, never a cached/stale one (#424, T14-F6-4 -- generalizing the
    schema-resolve-over-hardcode pattern landed for /outcome board status in
    71faf92 to mission-control's own board/field write surface).

    Simulates an upstream rename between two writes to the SAME field: the
    first write targets the option by its old name; after the rename, a
    write against the NEW name must resolve and succeed (proving live,
    uncached resolution), while a write still using the OLD name must fail
    loud with a helpful error (proving the write never silently falls back
    to a stale id) rather than mis-targeting an option that no longer
    exists."""

    def _status_response(option_name: str) -> dict:
        return {
            "organization": {
                "projectV2": {
                    "id": "PVT_kwx",
                    "fields": {
                        "nodes": [
                            {
                                "id": "FLD_status",
                                "name": "Status",
                                "options": [{"id": "opt_new", "name": option_name}],
                            }
                        ]
                    },
                }
            }
        }

    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
    ):
        mock_load.return_value = {
            "project_mappings": {"projects": {"campps": {"number": 4, "name": "CAMPPS"}}},
        }

        # W6: a Status write routes through the cross-board mutation — per
        # write: board discovery, then live field query, then the write.
        # Before the rename: live field query returns "Ready"; the write succeeds.
        mock_gql.side_effect = [
            _lifecycle_discovery(42, project_number=4, prior="Shaping"),
            _status_response("Ready"),
            {},
        ]
        sdlc_manager.flow_set_field("campps", "campps-mvp", 42, "Status", "Ready", fmt="text")

        # Upstream renames "Ready" -> "In Review". A write against the NEW
        # name must resolve live (no caching from the previous call) and
        # succeed.
        mock_gql.side_effect = [
            _lifecycle_discovery(42, project_number=4, prior="Ready"),
            _status_response("In Review"),
            {},
        ]
        sdlc_manager.flow_set_field("campps", "campps-mvp", 42, "Status", "In Review", fmt="text")

        # A write still using the OLD (now-removed) name must fail loud with
        # a retryable, helpful error -- never silently set a stale option id.
        mock_gql.side_effect = [
            _lifecycle_discovery(42, project_number=4, prior="In Review"),
            _status_response("In Review"),
        ]
        with pytest.raises(RuntimeError) as exc:
            sdlc_manager.flow_set_field("campps", "campps-mvp", 42, "Status", "Ready", fmt="text")
        msg = str(exc.value)
        assert "Ready" in msg
        assert "In Review" in msg


def _field_response() -> dict:
    return {
        "organization": {
            "projectV2": {
                "id": "PVT_kwx",
                "fields": {
                    "nodes": [
                        {
                            "id": "FLD_kwabc",
                            "name": "Status",
                            "options": [
                                {"id": "o1", "name": "Idea"},
                                {"id": "o2", "name": "Active"},
                            ],
                        },
                        {
                            "id": "FLD_obj",
                            "name": "Objective",
                            "options": [
                                {"id": "o3", "name": "defects-claude-plugins"},
                            ],
                        },
                    ]
                },
            }
        }
    }


def _project_item(number: int, item_id: str, repo: str = "infiquetra-claude-plugins") -> dict:
    return {
        "id": item_id,
        "content": {
            "number": number,
            "repository": {"name": repo},
        },
    }


def _lifecycle_discovery(
    number: int, project_number: int = 3, item_id: str | None = None, prior: str | None = "Idea"
) -> dict:
    """W6: the QUERY_GET_LIFECYCLE_FIELD_BOARDS response the cross-board
    mutation consumes — one carrying board for the given issue."""
    field_values: dict = {"nodes": []}
    if prior is not None:
        field_values["nodes"].append({"name": prior, "field": {"name": "Status"}})
    return {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        {
                            "id": item_id or f"PVTI_{number}",
                            "project": {"title": "Operations", "number": project_number},
                            "fieldValues": field_values,
                        }
                    ]
                }
            }
        }
    }


def test_set_field_bulk_reuses_discovery_and_updates_each_number() -> None:
    """W6: a Status bulk run discovers each issue's carrying boards and
    writes cross-board per issue (two discovery passes, one per issue)."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_load.return_value = {
            "project_mappings": {
                "projects": {"operations": {"number": 1, "name": "Operations"}},
            }
        }
        # Per issue: discovery, field preflight, write.
        mock_gql.side_effect = [
            _lifecycle_discovery(1, project_number=1, prior="Idea"),
            _field_response(),
            {},
            _lifecycle_discovery(2, project_number=1, prior="Idea"),
            _field_response(),
            {},
        ]

        sdlc_manager.flow_set_field_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1, 2],
            "Status",
            "Idea",
            fmt="json",
        )

    # Two discovery passes (one per issue), two field preflights, two writes.
    assert mock_gql.call_count == 6
    assert mock_gql.call_args_list[0].args[0] == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS
    assert mock_gql.call_args_list[3].args[0] == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS
    assert [
        call.args[0]
        for call in mock_gql.call_args_list
        if call.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE
    ] == [
        sdlc_manager.QUERY_SET_FIELD_VALUE,
        sdlc_manager.QUERY_SET_FIELD_VALUE,
    ]
    payload = mock_out.call_args.args[0]
    assert payload["assignments"] == [{"field": "Status", "option": "Idea"}]
    assert payload["updated"] == [
        {"repo": "infiquetra-claude-plugins", "number": 1, "field": "Status", "option": "Idea"},
        {"repo": "infiquetra-claude-plugins", "number": 2, "field": "Status", "option": "Idea"},
    ]
    assert payload["failed"] == []


def test_set_fields_bulk_reuses_discovery_for_multiple_fields_and_numbers() -> None:
    """W6 mixed bulk: Status routes cross-board per issue (its own discovery);
    Objective keeps the single-board shared-discovery legacy path for both
    numbers."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "get_project_items") as mock_items,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_load.return_value = {
            "project_mappings": {
                "projects": {"operations": {"number": 1, "name": "Operations"}},
            }
        }
        mock_items.return_value = (
            "PVT_kwx",
            [_project_item(1, "PVTI_1"), _project_item(2, "PVTI_2")],
        )
        # Lifecycle part: (discovery, fields, write) x 2 issues; legacy
        # Objective part: one field discovery, then two writes.
        mock_gql.side_effect = [
            _lifecycle_discovery(1, project_number=1, prior="Idea"),
            _field_response(),
            {},
            _lifecycle_discovery(2, project_number=1, prior="Idea"),
            _field_response(),
            {},
            _field_response(),
            {},
            {},
        ]

        sdlc_manager.flow_set_fields_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1, 2],
            [("Status", "Idea"), ("Objective", "defects-claude-plugins")],
            fmt="json",
        )

    assert mock_items.call_count == 1  # legacy Objective path only
    assert mock_gql.call_count == 9
    assert mock_gql.call_args_list[0].args[0] == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS
    field_discoveries = [
        c for c in mock_gql.call_args_list if c.args[0] == sdlc_manager.QUERY_GET_PROJECT_FIELDS
    ]
    assert len(field_discoveries) == 3  # two cross-board preflights + legacy Objective resolve
    board_writes = [
        c for c in mock_gql.call_args_list if c.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE
    ]
    assert len(board_writes) == 4
    payload = mock_out.call_args.args[0]
    assert payload["assignments"] == [
        {"field": "Status", "option": "Idea"},
        {"field": "Objective", "option": "defects-claude-plugins"},
    ]
    assert len(payload["updated"]) == 4
    assert payload["failed"] == []


def test_set_field_bulk_reports_partial_failure_and_continues() -> None:
    """Per-issue atomicity: issue 1's failed write is reported; issue 2 still
    writes its boards."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_load.return_value = {
            "project_mappings": {
                "projects": {"operations": {"number": 1, "name": "Operations"}},
            }
        }
        mock_gql.side_effect = [
            _lifecycle_discovery(1, project_number=1, prior="Idea"),
            _field_response(),
            RuntimeError("mutation failed"),
            _lifecycle_discovery(2, project_number=1, prior="Idea"),
            _field_response(),
            {},
        ]

        with pytest.raises(RuntimeError, match="failed for 1 of 2"):
            sdlc_manager.flow_set_field_bulk(
                "operations",
                "infiquetra-claude-plugins",
                [1, 2],
                "Status",
                "Idea",
                fmt="json",
            )

    # Issue 1's failed write needed no compensation (nothing yet written);
    # issue 2 wrote normally.
    assert mock_gql.call_count == 6
    payload = mock_out.call_args.args[0]
    assert payload["updated"] == [
        {"repo": "infiquetra-claude-plugins", "number": 2, "field": "Status", "option": "Idea"}
    ]
    assert len(payload["failed"]) == 1
    assert payload["failed"][0]["number"] == 1
    assert "mutation failed" in payload["failed"][0]["error"]


def test_cli_numbers_arg_routes_to_bulk_set_field() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "set-field",
                "--project",
                "operations",
                "--repo",
                "infiquetra/infiquetra-claude-plugins",
                "--numbers",
                "1, 2,3",
                "--field",
                "Status",
                "--option",
                "Idea",
            ],
        ),
        patch.object(sdlc_manager, "flow_set_fields_bulk") as set_fields_bulk,
    ):
        sdlc_manager.main()

    set_fields_bulk.assert_called_once_with(
        "operations",
        "infiquetra-claude-plugins",
        [1, 2, 3],
        [("Status", "Idea")],
        "text",
        correction=False,
        reason=None,
    )


def test_cli_repeated_field_option_pairs_route_to_bulk_set_field() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "set-field",
                "--project",
                "operations",
                "--repo",
                "infiquetra-claude-plugins",
                "--numbers",
                "1,2",
                "--field",
                "Status",
                "--option",
                "Idea",
                "--field",
                "Objective",
                "--option",
                "defects-claude-plugins",
            ],
        ),
        patch.object(sdlc_manager, "flow_set_fields_bulk") as set_fields_bulk,
    ):
        sdlc_manager.main()

    set_fields_bulk.assert_called_once_with(
        "operations",
        "infiquetra-claude-plugins",
        [1, 2],
        [("Status", "Idea"), ("Objective", "defects-claude-plugins")],
        "text",
        correction=False,
        reason=None,
    )


def test_cli_rejects_mismatched_repeated_field_option_pairs() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "set-field",
                "--project",
                "operations",
                "--repo",
                "infiquetra-claude-plugins",
                "--numbers",
                "1,2",
                "--field",
                "Status",
                "--option",
                "Idea",
                "--field",
                "Objective",
            ],
        ),
        pytest.raises(SystemExit),
    ):
        sdlc_manager.main()


# --- #812 correction set-field (field-named identity; Status/Stage only) ---


def _status_field_response() -> dict:
    return {
        "organization": {
            "projectV2": {
                "id": "PVT_kwx",
                "fields": {
                    "nodes": [
                        {
                            "id": "FLD_status",
                            "name": "Status",
                            "options": [
                                {"id": "o_verify", "name": "Verify"},
                                {"id": "o_active", "name": "Active"},
                            ],
                        },
                        {
                            "id": "FLD_init",
                            "name": "Initiative",
                            "options": [{"id": "o_init", "name": "platform-v1"}],
                        },
                    ]
                },
            }
        }
    }


def test_correction_set_field_round_trips_field_in_identity() -> None:
    """A Status correction carries the field name in operation, authorization, and retry.

    W6: the correction routes through the cross-board mutation — discovery,
    field preflight, then the write, whose variables still name FLD_status."""
    with (
        patch.object(sdlc_manager, "load_config") as mock_load,
        patch.object(sdlc_manager, "_graphql") as mock_gql,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_load.return_value = {
            "project_mappings": {"projects": {"operations": {"number": 3, "name": "Operations"}}},
        }
        mock_gql.side_effect = [
            _lifecycle_discovery(42, project_number=3, item_id="PVTI_42", prior="Idea"),
            _status_field_response(),
            {},
        ]
        sdlc_manager.flow_set_field(
            "operations",
            "infiquetra-claude-plugins",
            42,
            "Status",
            "Verify",
            fmt="json",
            correction=True,
        )

    payload = mock_out.call_args.args[0]
    assert payload["correction"] is True
    assert payload["field"] == "Status"
    identity = payload["identity"]
    assert identity["operation"] == "set-field:Status"
    assert identity["authorization"] == "correction-field:Status"
    # Byte-identical to reversibility_certificate.idempotency_key(...) so a mission-control
    # write and the saga ledger entry that submitted it correlate on one string (#812 repair).
    assert identity["retry"] == "set-field-status:infiquetra-claude-plugins#42:Status:Verify"
    mutation_vars = mock_gql.call_args_list[-1].args[1]
    assert mutation_vars["fieldId"] == "FLD_status"
    assert mutation_vars["itemId"] == "PVTI_42"


def test_correction_set_field_rejects_non_status_non_stage() -> None:
    """Initiative is a live operator field but is rejected as a correction submission."""
    with pytest.raises(RuntimeError, match="rejects field 'Initiative'"):
        sdlc_manager.flow_set_field(
            "operations",
            "infiquetra-claude-plugins",
            42,
            "Initiative",
            "platform-v1",
            fmt="json",
            correction=True,
        )


def test_correction_set_field_allows_stage_by_name() -> None:
    """Stage is authorized by name; live discovery (no such field) is a later failure."""
    assert sdlc_manager.assert_correction_field("Stage") == "Stage"
    identity = sdlc_manager.correction_identity(
        field_name="Stage",
        repo="x",
        number=1,
        option_name="n/a",
    )
    assert identity["operation"] == "set-field:Stage"
    assert identity["authorization"] == "correction-field:Stage"
    assert "Stage" in identity["retry"]


def test_correction_certificate_gate_stays_on_saga_write_path() -> None:
    """MC does not reimplement the reversibility certificate; it only names the field.

    The certificate still AUTHORIZES ``set-field-status`` in saga; this module
    has no ``authorize_write``. A correction write still goes through
    ``_set_project_field_value`` (the existing GraphQL mutation).
    """
    assert not hasattr(sdlc_manager, "authorize_write")
    assert callable(sdlc_manager._set_project_field_value)
    assert "set-field-stage" not in dir(sdlc_manager)


def test_cli_correction_flag_routes_to_flow_set_field() -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "set-field",
                "--project",
                "operations",
                "--repo",
                "infiquetra-claude-plugins",
                "--number",
                "42",
                "--field",
                "Status",
                "--option",
                "Verify",
                "--correction",
            ],
        ),
        patch.object(sdlc_manager, "flow_set_field") as set_field,
    ):
        sdlc_manager.main()

    set_field.assert_called_once_with(
        "operations",
        "infiquetra-claude-plugins",
        42,
        "Status",
        "Verify",
        "text",
        correction=True,
        reason=None,
    )


def test_cli_correction_rejects_objective_before_bulk_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
            sys,
            "argv",
            [
                "sdlc_manager.py",
                "flow",
                "set-field",
                "--project",
                "operations",
                "--repo",
                "infiquetra-claude-plugins",
                "--numbers",
                "1,2",
                "--field",
                "Objective",
                "--option",
                "defects-claude-plugins",
                "--correction",
            ],
        ),
        pytest.raises(SystemExit) as exc,
    ):
        sdlc_manager.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "rejects field 'Objective'" in err


def test_bulk_correction_rejects_non_status_non_stage_in_process() -> None:
    """The correction restriction lives in the function, not only in ``main()``.

    An in-process caller of the bulk path must not reach a wider field set than the CLI
    can, and the rejection must land before any project discovery or GraphQL mutation.
    """
    with (
        patch.object(sdlc_manager, "_resolve_project_fields") as resolve,
        pytest.raises(RuntimeError, match="rejects field 'Objective'"),
    ):
        sdlc_manager.flow_set_fields_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1, 2],
            [("Status", "Idea"), ("Objective", "defects-claude-plugins")],
            "json",
            correction=True,
        )
    resolve.assert_not_called()


def test_bulk_correction_marks_the_result_and_carries_per_card_identity() -> None:
    """A bulk correction is distinguishable from an operator write in the output stream.

    W6: Status corrections route through the cross-board mutation per issue;
    internals are mocked at the mutation's seams."""
    with (
        patch.object(sdlc_manager, "_lifecycle_field_boards") as boards,
        patch.object(sdlc_manager, "_resolve_project_field") as resolve_field,
        patch.object(sdlc_manager, "_resolve_field_option") as resolve_option,
        patch.object(sdlc_manager, "_set_project_field_value"),
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        boards.side_effect = lambda _repo, number, _field: [
            {
                "key": "operations",
                "title": "Operations",
                "project_number": 1,
                "item_id": f"PVTI_{number}",
                "field_present": True,
                "prior_value": "Idea",
            }
        ]
        resolve_field.return_value = {
            "id": "FLD_status",
            "_project_id": "PVT_kwx",
            "options": [{"id": "o_idea", "name": "Idea"}],
        }
        resolve_option.return_value = {"id": "o_idea", "name": "Idea"}
        sdlc_manager.flow_set_fields_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1, 2],
            [("Status", "Idea")],
            "json",
            correction=True,
        )

    result = mock_out.call_args.args[0]
    assert result["correction"] is True
    assert [row["operation"] for row in result["identity"]] == [
        "set-field:Status",
        "set-field:Status",
    ]
    assert result["identity"][0]["retry"] == (
        "set-field-status:infiquetra-claude-plugins#1:Status:Idea"
    )
    assert result["identity"][1]["retry"] == (
        "set-field-status:infiquetra-claude-plugins#2:Status:Idea"
    )


def test_bulk_correction_identity_omits_a_card_that_failed_to_write() -> None:
    """An identity block claims a write happened; a failed card must not appear in it."""

    def _fail_card_two(_project_id: str, _field: dict, _option: dict, item: dict) -> None:
        if item["id"] == "PVTI_2":
            raise RuntimeError("card 2 is not on the project")

    with (
        patch.object(sdlc_manager, "_lifecycle_field_boards") as boards,
        patch.object(sdlc_manager, "_resolve_project_field") as resolve_field,
        patch.object(sdlc_manager, "_resolve_field_option") as resolve_option,
        patch.object(sdlc_manager, "_set_project_field_value", side_effect=_fail_card_two),
        patch.object(sdlc_manager, "_out") as mock_out,
        pytest.raises(RuntimeError, match="failed for 1 of"),
    ):
        boards.side_effect = lambda _repo, number, _field: [
            {
                "key": "operations",
                "title": "Operations",
                "project_number": 1,
                "item_id": f"PVTI_{number}",
                "field_present": True,
                "prior_value": "Idea",
            }
        ]
        resolve_field.return_value = {
            "id": "FLD_status",
            "_project_id": "PVT_kwx",
            "options": [{"id": "o_idea", "name": "Idea"}],
        }
        resolve_option.return_value = {"id": "o_idea", "name": "Idea"}
        sdlc_manager.flow_set_fields_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1, 2],
            [("Status", "Idea")],
            "json",
            correction=True,
        )

    result = mock_out.call_args.args[0]
    assert [row["retry"] for row in result["identity"]] == [
        "set-field-status:infiquetra-claude-plugins#1:Status:Idea"
    ]
    assert [row["number"] for row in result["failed"]] == [2]


def test_bulk_without_correction_is_unmarked_and_unrestricted() -> None:
    """CONTROL: the operator bulk path still writes Objective and carries no correction block."""
    with (
        patch.object(sdlc_manager, "_resolve_project_fields") as resolve,
        patch.object(sdlc_manager, "_resolve_field_option") as resolve_option,
        patch.object(sdlc_manager, "_project_items_by_number") as items,
        patch.object(sdlc_manager, "_set_project_field_value"),
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        resolve.return_value = {"Objective": {"id": "FLD_obj", "_project_id": "PVT_kwx"}}
        resolve_option.return_value = {"id": "o_def", "name": "defects-claude-plugins"}
        items.return_value = {1: {"id": "PVTI_1"}}
        sdlc_manager.flow_set_fields_bulk(
            "operations",
            "infiquetra-claude-plugins",
            [1],
            [("Objective", "defects-claude-plugins")],
            "json",
        )

    result = mock_out.call_args.args[0]
    assert "correction" not in result
    assert "identity" not in result
