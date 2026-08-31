"""Fail-loud tests for mission-control ``board move`` (#609).

W6/U6 rerouted the Status write through the constrained cross-board mutation
(KTD13): ``board_move`` keeps its ``bool`` return and the CLI arm still turns
``False`` into ``SystemExit(1)``; a LifecycleMutationHaltError propagates
instead of degrading to an ordinary failed move. The per-project
except-and-continue that the pre-W6 body used is gone. The final two tests
preserve the original #609 contract verbatim: an ordinary failure reports and
returns ``False``, and the CLI exits 1 ONLY after the move reported failure.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

REPO = "demo-repo"
NUMBER = 609


def _item(item_id: str, number: int, title: str, status_value):
    field_values: dict = {"nodes": []}
    if status_value is not ...:
        node = {"field": {"name": "Status"}}
        if status_value is not None:
            node["name"] = status_value
        field_values["nodes"].append(node)
    return {
        "id": item_id,
        "project": {"title": title, "number": number},
        "fieldValues": field_values,
    }


def _fields_response(project_id: str, *options: str) -> dict:
    return {
        "organization": {
            "projectV2": {
                "id": project_id,
                "fields": {
                    "nodes": [
                        {
                            "id": f"PVTSSF_status_{project_id}",
                            "name": "Status",
                            "options": [
                                {"id": f"opt_{project_id}_{name}", "name": name} for name in options
                            ],
                        }
                    ],
                    "pageInfo": {"hasNextPage": False},
                },
            }
        }
    }


def _gql_side_effect(discovery, field_responses, write_responses):
    def _pop(queue):
        entry = queue.pop(0) if queue else {}
        if isinstance(entry, Exception):
            raise entry
        return entry

    def side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS:
            return discovery
        if query == sdlc_manager.QUERY_GET_PROJECT_FIELDS:
            return _pop(field_responses)
        if query == sdlc_manager.QUERY_SET_FIELD_VALUE:
            return _pop(write_responses)
        raise AssertionError(f"unexpected query: {query[:80]}")

    return side_effect


def _set_field_calls(mock_graphql):
    return [
        c for c in mock_graphql.call_args_list if c.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE
    ]


def test_board_move_success_returns_true() -> None:
    """A move writes through the cross-board mutation and returns True."""
    discovery = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        _item("PVTI_x", 3, "Operations", "Idea"),
                    ]
                }
            }
        }
    }
    with (
        patch.object(sdlc_manager, "load_config", return_value={}),
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                discovery,
                [_fields_response("PVT_operations", "Idea", "Active")],
                [{}],
            ),
        ) as mock_graphql,
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {"operations": {"number": 3, "name": "Operations"}}
                }
            },
        ),
    ):
        result = sdlc_manager.board_move(REPO, NUMBER, "Active", "text")

    assert result is True
    assert _set_field_calls(mock_graphql) == [
        call(
            sdlc_manager.QUERY_SET_FIELD_VALUE,
            {
                "projectId": "PVT_operations",
                "itemId": "PVTI_x",
                "fieldId": "PVTSSF_status_PVT_operations",
                "optionId": "opt_PVT_operations_Active",
            },
        )
    ]


def test_unavailable_status_returns_false_and_does_not_mutate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    discovery = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        _item("PVTI_x", 3, "Operations", "Idea"),
                    ]
                }
            }
        }
    }
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                discovery,
                [_fields_response("PVT_operations", "Idea", "Active")],
                [],
            ),
        ) as mock_graphql,
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {"operations": {"number": 3, "name": "Operations"}}
                }
            },
        ),
    ):
        result = sdlc_manager.board_move(REPO, NUMBER, "Unavailable", "text")

    assert result is False
    output = capsys.readouterr().out
    assert "Option 'Unavailable' not found" in output
    assert "'Idea', 'Active'" in output
    assert _set_field_calls(mock_graphql) == []


def test_issue_on_no_board_returns_false_and_writes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Zero carrying boards is an explicit no-op: reported (#609 shape) and
    returned as an ordinary failure — never success."""
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                {"repository": {"issue": {"projectItems": {"nodes": []}}}}, [], []
            ),
        ),
        patch.object(sdlc_manager, "load_config", return_value={}),
    ):
        result = sdlc_manager.board_move("demo-repo", 609, "Active", "text")

    assert result is False
    output = capsys.readouterr().out
    assert "sits on no project board" in output
    assert "explicit no-op" in output


def test_mutation_failure_returns_false_after_reporting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """#609: an ordinary write failure (fully compensated) returns False and
    is reported, not raised."""
    discovery = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        _item("PVTI_x", 3, "Operations", "Idea"),
                    ]
                }
            }
        }
    }
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                discovery,
                [_fields_response("PVT_operations", "Idea", "Active")],
                [RuntimeError("mutation failed")],
            ),
        ) as mock_graphql,
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {"operations": {"number": 3, "name": "Operations"}}
                }
            },
        ),
    ):
        result = sdlc_manager.board_move(REPO, NUMBER, "Active", "text")

    assert result is False
    assert "Failed to move" in capsys.readouterr().out
    assert len(_set_field_calls(mock_graphql)) == 1


def test_no_best_effort_continue_two_board_move_is_all_or_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The pre-W6 per-project except-and-continue is GONE: an injected failure
    on the second of two boards leaves NEITHER board written — the first is
    restored to its prior value by the mutation's compensation."""
    discovery = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        _item("PVTI_a", 2, "Asgard", "Idea"),
                        _item("PVTI_o", 3, "Operations", "Idea"),
                    ]
                }
            }
        }
    }
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                discovery,
                [
                    _fields_response("PVT_asgard", "Idea", "Active"),
                    _fields_response("PVT_operations", "Idea", "Active"),
                ],
                [{}, RuntimeError("second board down")],
            ),
        ) as mock_graphql,
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {
                        "asgard": {"number": 2, "name": "Asgard"},
                        "operations": {"number": 3, "name": "Operations"},
                    }
                }
            },
        ),
    ):
        result = sdlc_manager.board_move(REPO, NUMBER, "Active", "text")

    assert result is False
    calls = _set_field_calls(mock_graphql)
    assert [c.args[1]["optionId"] for c in calls] == [
        "opt_PVT_asgard_Active",  # the doomed write to board 1
        "opt_PVT_operations_Active",  # the failed write to board 2
        "opt_PVT_asgard_Idea",  # board 1's PRIOR value restored
    ]


def test_compensation_halt_propagates_not_downgraded() -> None:
    """KTD13 carve-out: when the restore ALSO fails, the halt propagates out
    of board_move by TYPE instead of collapsing into a bool False — a
    divergent-boards halt must never present as an ordinary move failure."""
    discovery = {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        _item("PVTI_a", 2, "Asgard", "Idea"),
                        _item("PVTI_o", 3, "Operations", "Idea"),
                    ]
                }
            }
        }
    }
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_gql_side_effect(
                discovery,
                [
                    _fields_response("PVT_asgard", "Idea", "Active"),
                    _fields_response("PVT_operations", "Idea", "Active"),
                ],
                [{}, RuntimeError("second board down"), RuntimeError("restore down")],
            ),
        ),
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {
                        "asgard": {"number": 2, "name": "Asgard"},
                        "operations": {"number": 3, "name": "Operations"},
                    }
                }
            },
        ),
        pytest.raises(sdlc_manager.LifecycleMutationHaltError),
    ):
        sdlc_manager.board_move(REPO, NUMBER, "Active", "text")


def test_cli_exits_one_only_after_board_move_reports_failure() -> None:
    """The original #609 contract, verbatim: the CLI arm turns a False move
    into SystemExit(1)."""
    argv = [
        "sdlc_manager.py",
        "board",
        "move",
        "--project",
        "operations",
        "--repo",
        "demo-repo",
        "--number",
        "609",
        "--status",
        "Unavailable",
    ]
    with (
        patch.object(sys, "argv", argv),
        patch.object(sdlc_manager, "board_move", return_value=False) as move,
        pytest.raises(SystemExit) as exc_info,
    ):
        sdlc_manager.main()

    assert exc_info.value.code == 1
    move.assert_called_once_with("demo-repo", 609, "Unavailable", "text", project_name="operations")
