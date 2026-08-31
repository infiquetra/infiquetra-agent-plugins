"""Tests for W6/U4 — AE3 field identity + idempotency (issue #87).

AE3: two mutations on the same issue — one setting Stage, one setting Status
to the same literal value — produce DIFFERENT idempotency keys and both
apply. The identity recipe is the existing ``correction_identity`` (KTD1):
byte-identical to saga's ledger key, so these tests assert the exact
expected strings rather than re-deriving them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

REPO = "demo-repo"
NUMBER = 42
VALUE = "Active"  # the SAME literal value for both fields

MAPPING_CONFIG = {
    "project_mappings": {
        "projects": {
            "operations": {"number": 3, "name": "Operations", "id": "PVT_operations"},
            "asgard": {"number": 2, "name": "Asgard", "id": "PVT_asgard"},
        }
    }
}


def _fields_response(project_id: str, statuses, stages):
    nodes = [
        {
            "id": f"F_{project_id}_Status",
            "name": "Status",
            "options": [{"id": f"opt_{project_id}_Status_{o}", "name": o} for o in statuses],
        },
        {
            "id": f"F_{project_id}_Stage",
            "name": "Stage",
            "options": [{"id": f"opt_{project_id}_Stage_{o}", "name": o} for o in stages],
        },
    ]
    return {
        "organization": {
            "projectV2": {
                "id": project_id,
                "fields": {"nodes": nodes, "pageInfo": {"hasNextPage": False}},
            }
        }
    }


def _discovery():
    return {
        "repository": {
            "issue": {
                "projectItems": {
                    "nodes": [
                        {
                            "id": "PVTI_a",
                            "project": {"title": "Asgard", "number": 2},
                            "fieldValues": {
                                "nodes": [{"name": "Idea", "field": {"name": "Status"}}]
                            },
                        },
                        {
                            "id": "PVTI_o",
                            "project": {"title": "Operations", "number": 3},
                            "fieldValues": {
                                "nodes": [{"name": "Idea", "field": {"name": "Status"}}]
                            },
                        },
                    ]
                }
            }
        }
    }


def _gql_side_effect():
    fields = [
        _fields_response("PVT_asgard", ["Idea", "Active"], ["Design", "Build", "Active"]),
        _fields_response("PVT_operations", ["Idea", "Active"], ["Design", "Active"]),
    ]

    def side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS:
            return _discovery()
        if query == sdlc_manager.QUERY_GET_PROJECT_FIELDS:
            return fields.pop(0)
        if query == sdlc_manager.QUERY_SET_FIELD_VALUE:
            return {}
        raise AssertionError(f"unexpected query: {query[:80]}")

    return side_effect


def test_field_identity_stage_and_status_differ_for_same_literal_value() -> None:
    """The identity part of AE3 at the recipe level: the field name segment
    separates the two retry identities."""
    stage_identity = sdlc_manager.correction_identity(
        field_name="Stage", repo=REPO, number=NUMBER, option_name=VALUE
    )
    status_identity = sdlc_manager.correction_identity(
        field_name="Status", repo=REPO, number=NUMBER, option_name=VALUE
    )

    assert stage_identity["retry"] == f"set-field-status:{REPO}#{NUMBER}:Stage:Active"
    assert status_identity["retry"] == f"set-field-status:{REPO}#{NUMBER}:Status:Active"
    assert stage_identity["retry"] != status_identity["retry"]
    # Field identity carried in the authorization decision and the evidence.
    assert stage_identity["authorization"] == "correction-field:Stage"
    assert status_identity["authorization"] == "correction-field:Status"
    assert stage_identity["operation"] == "set-field:Stage"
    assert status_identity["operation"] == "set-field:Status"


def test_mutation_idempotency_stage_and_status_both_apply() -> None:
    """AE3 end to end: both mutations apply to every carrying board, under
    DIFFERENT identity strings, from the same literal value."""
    identities = {}
    for field_name in ("Stage", "Status"):
        with (
            patch.object(sdlc_manager, "_graphql", side_effect=_gql_side_effect()) as gql,
            patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        ):
            evidence = sdlc_manager._set_lifecycle_field_cross_board(
                REPO, NUMBER, field_name, VALUE, reason="AE3"
            )
        identities[field_name] = evidence["identity"]["retry"]
        # Both apply: every carrying board receives the write.
        assert {b["project"] for b in evidence["boards"]} == {"asgard", "operations"}
        assert (
            len([c for c in gql.call_args_list if c.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE])
            == 2
        )

    assert identities["Stage"] != identities["Status"]


def test_mutation_idempotency_same_identity_on_repeat_write() -> None:
    """Re-running the SAME write yields the SAME identity strings — the
    idempotency half of the AE3 key."""
    seen = []
    for _ in range(2):
        with (
            patch.object(sdlc_manager, "_graphql", side_effect=_gql_side_effect()),
            patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        ):
            evidence = sdlc_manager._set_lifecycle_field_cross_board(
                REPO, NUMBER, "Status", VALUE, reason="AE3"
            )
        seen.append(evidence["identity"])
    assert seen[0] == seen[1]


def test_correction_fields_plugin_oracle_pins_stage_and_status() -> None:
    """F-2 regression (Code Review cycle 1): a hard-coded, literal oracle for
    the plugin's enforced CORRECTION_FIELDS set, independent of any generated
    or round-tripped value. KTD5's two-oracle rule: adding a third field name
    here must fail this test, not silently open a new cross-board writer
    while the sdlc-schema oracle still says Stage and Status."""
    assert frozenset({"Status", "Stage"}) == sdlc_manager.CORRECTION_FIELDS
