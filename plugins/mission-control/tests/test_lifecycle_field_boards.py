"""Tests for W6/U2 board discovery — ``_lifecycle_field_boards`` (issue #87).

The helper must answer "which boards actually carry this issue" from the
issue's OWN projectItems (KTD2 — the repo→board map deliberately has empty
``repositories`` arrays), returning the mapping key, project identity, the
project-item node id the write primitive needs, and the field's current
value — the value KTD3's compensation restores, read in the same query as
discovery.

``_graphql`` is patched at the sdlc_manager-module level — no network.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

MAPPING_CONFIG = {
    "project_mappings": {
        "projects": {
            "operations": {"number": 3, "name": "Operations", "id": "PVT_operations"},
            "asgard": {"number": 2, "name": "Asgard", "id": "PVT_asgard"},
            "campps": {"number": 4, "name": "CAMPPS", "id": "PVT_campps"},
        }
    }
}

_STATUS = "Status"


def _item(item_id: str, number: int, title: str, status_value=...):
    """Build one projectItems node. status_value ... (sentinel) = field absent,
    None = field present with no value, str = field present with that value."""
    field_values: dict = {"nodes": []}
    if status_value is not ...:
        node = {"field": {"name": _STATUS}}
        if status_value is not None:
            node["name"] = status_value
        field_values["nodes"].append(node)
    return {
        "id": item_id,
        "project": {"title": title, "number": number},
        "fieldValues": field_values,
    }


def _discovery_response(nodes) -> dict:
    return {"repository": {"issue": {"projectItems": {"nodes": list(nodes)}}}}


def test_two_board_issue_returns_one_record_per_board_with_prior_values() -> None:
    response = _discovery_response(
        [
            _item("PVTI_a", 2, "Asgard", "Active"),
            _item("PVTI_o", 3, "Operations", None),
        ]
    )
    with (
        patch.object(sdlc_manager, "_graphql", return_value=response) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        records = sdlc_manager._lifecycle_field_boards("demo-repo", 42, _STATUS)

    gql.assert_called_once()
    assert [r["key"] for r in records] == ["asgard", "operations"]  # sorted by project number
    assert [r["project_number"] for r in records] == [2, 3]
    assert [r["title"] for r in records] == ["Asgard", "Operations"]
    assert [r["item_id"] for r in records] == ["PVTI_a", "PVTI_o"]
    # One board carries a value, the other has the field present but unset.
    assert records[0]["prior_value"] == "Active"
    assert records[0]["field_present"] is True
    assert records[1]["prior_value"] is None
    assert records[1]["field_present"] is True


def test_issue_on_zero_boards_returns_empty_list() -> None:
    response = _discovery_response([])
    with (
        patch.object(sdlc_manager, "_graphql", return_value=response),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        records = sdlc_manager._lifecycle_field_boards("demo-repo", 42, _STATUS)

    assert records == []


def test_field_present_unset_distinct_from_field_absent() -> None:
    """Mixed: two of three boards carry the named field; the third has no
    Status fieldValues node at all. The helper must distinguish the two cases
    so the mutation's preflight can halt on the third."""
    response = _discovery_response(
        [
            _item("PVTI_a", 2, "Asgard", "Idea"),
            _item("PVTI_o", 3, "Operations", None),  # field present, unset
            _item("PVTI_c", 4, "CAMPPS"),  # field absent entirely
        ]
    )
    with (
        patch.object(sdlc_manager, "_graphql", return_value=response),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        records = sdlc_manager._lifecycle_field_boards("demo-repo", 42, _STATUS)

    assert [r["key"] for r in records] == ["asgard", "operations", "campps"]
    by_key = {r["key"]: r for r in records}
    assert by_key["asgard"]["field_present"] is True
    assert by_key["asgard"]["prior_value"] == "Idea"
    assert by_key["operations"]["field_present"] is True
    assert by_key["operations"]["prior_value"] is None
    assert by_key["campps"]["field_present"] is False
    assert by_key["campps"]["prior_value"] is None


def test_missing_issue_node_raises_runtime_error_naming_issue() -> None:
    with (
        patch.object(sdlc_manager, "_graphql", return_value={"repository": {}}),
        pytest.raises(RuntimeError) as exc_info,
    ):
        sdlc_manager._lifecycle_field_boards("demo-repo", 42, _STATUS)

    assert "demo-repo#42" in str(exc_info.value)


def test_non_dict_project_item_nodes_are_skipped() -> None:
    """Guard style matching _mimir_objective_fields: malformed entries in
    projectItems.nodes are skipped without raising."""
    response = {
        "repository": {
            "issue": {
                "projectItems": {"nodes": [None, "junk", _item("PVTI_a", 2, "Asgard", "Active")]}
            }
        }
    }
    with (
        patch.object(sdlc_manager, "_graphql", return_value=response),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        records = sdlc_manager._lifecycle_field_boards("demo-repo", 42, _STATUS)

    assert len(records) == 1
    assert records[0]["item_id"] == "PVTI_a"
