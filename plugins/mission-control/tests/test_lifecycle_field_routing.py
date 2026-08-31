"""Tests for W6/U3 — the KTD10 routing rule (issue #87, Plan Review finding D1).

The invariant under test: field identity — NOT the ``--correction`` flag, NOT
``--project`` — selects the writer. Any ``Stage``/``Status`` write from ANY
entry point (CLI verb, bulk verb, in-process callers) reaches the constrained
cross-board mutation; every other field keeps the single-board path only.
These tests fail if a parallel single-board writer for the two lifecycle
fields is left reachable.

Issue #87's own live verification command (``flow set-field --project
operations --repo <r> --number <N> --field Status --option Shaping``, no
added flags) is exercised verbatim and must route to the cross-board mutation.
All GitHub/GraphQL calls are patched at the sdlc_manager-module level — no
network.
"""

from __future__ import annotations

import json
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

REPO = "demo-repo"
NUMBER = 42


def _item(item_id: str, number: int, title: str, status_value):
    """Build one projectItems node. status_value may be _ABSENT (the field is
    not on the board), None (field present, unset), or a prior value string."""
    field_values: dict = {"nodes": []}
    if status_value is not _ABSENT:
        node = {"field": {"name": "Status"}}
        if status_value is not None:
            node["name"] = status_value
        field_values["nodes"].append(node)
    return {
        "id": item_id,
        "project": {"title": title, "number": number},
        "fieldValues": field_values,
    }


_ABSENT = ...


def _discovery(nodes) -> dict:
    return {"repository": {"issue": {"projectItems": {"nodes": list(nodes)}}}}


def _fields_response(project_id: str, *field_options):
    """field_options: (field_name, [option names]) pairs."""
    nodes = [
        {
            "id": f"F_{project_id}_{name}",
            "name": name,
            "options": [{"id": f"opt_{project_id}_{name}_{o}", "name": o} for o in opts],
        }
        for name, opts in field_options
    ]
    return {
        "organization": {
            "projectV2": {
                "id": project_id,
                "fields": {"nodes": nodes, "pageInfo": {"hasNextPage": False}},
            }
        }
    }


def _items_response():
    """The QUERY_GET_PROJECT_ITEMS response the legacy single-board path
    consumes via _project_items_by_number."""
    return {
        "organization": {
            "projectV2": {
                "items": {
                    "nodes": [
                        {
                            "id": "PVTI_legacy",
                            "content": {"number": NUMBER, "repository": {"name": REPO}},
                        }
                    ],
                    "pageInfo": {"hasNextPage": False},
                }
            }
        }
    }


def _gql_side_effect(discovery, field_responses, write_responses, items_responses=None):
    """One side_effect over the query kinds. Queue entries are returned; an
    Exception entry is raised; an exhausted write queue returns {}."""
    items_responses = list(items_responses) if items_responses is not None else []

    def _pop(queue, default=None):
        entry = queue.pop(0) if queue else (default if default is not None else {})
        if isinstance(entry, Exception):
            raise entry
        return entry

    def side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS:
            if discovery is None:
                raise AssertionError("lifecycle board discovery must not run in this test")
            return discovery
        if query == sdlc_manager.QUERY_GET_PROJECT_FIELDS:
            return _pop(field_responses)
        if query == sdlc_manager.QUERY_GET_PROJECT_ITEMS:
            return _pop(items_responses)
        if query == sdlc_manager.QUERY_SET_FIELD_VALUE:
            return _pop(write_responses)
        raise AssertionError(f"unexpected query routed to _graphql: {query[:80]}")

    return side_effect


def _set_field_calls(mock_gql):
    return [c for c in mock_gql.call_args_list if c.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE]


def _discovery_calls(mock_gql):
    return [
        c
        for c in mock_gql.call_args_list
        if c.args[0] == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS
    ]


# Uniform priors: since F-7 a call from ALREADY-divergent boards halts before
# the first write, so routing tests start from a consistent pre-call state.
_TWO_BOARD_DISCOVERY = _discovery(
    [
        _item("PVTI_a", 2, "Asgard", "Idea"),
        _item("PVTI_o", 3, "Operations", "Idea"),
    ]
)

_STATUS_FIELDS = [
    _fields_response(
        "PVT_asgard", ("Status", ["Shaping", "Active"]), ("Objective", ["platform-v1"])
    ),
    _fields_response(
        "PVT_operations", ("Status", ["Shaping", "Active"]), ("Objective", ["platform-v1"])
    ),
]


def _card_command(*extra):
    """Issue #87's verification command, verbatim modulo extra flags."""
    return [
        "sdlc_manager.py",
        "flow",
        "set-field",
        "--project",
        "operations",
        "--repo",
        REPO,
        "--number",
        str(NUMBER),
        "--field",
        "Status",
        "--option",
        "Shaping",
        *extra,
    ]


def _route_main(argv, gql_env):
    """Run main() with argv and a fully mocked GraphQL environment. Returns
    (gql_mock, exit_code); SystemExit from the CLI arms is captured, not
    raised out."""

    with (
        patch.object(sys, "argv", argv),
        patch.object(sdlc_manager, "_graphql", side_effect=gql_env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        try:
            sdlc_manager.main()
            code = 0
        except SystemExit as exc:
            code = exc.code
    return gql, code


def _out_json(capsys):
    return json.loads(capsys.readouterr().out)


# --- Routing: the card's own command -----------------------------------------


def test_route_card_command_reaches_cross_board_mutation(capsys):
    """The card's verification command verbatim — no --correction, no
    --reason, no new verb — reaches the cross-board mutation and emits one
    evidence record per carrying board."""
    gql, code = _route_main(
        _card_command(),
        _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}]),
    )
    assert code == 0
    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }
    evidence = _out_json(capsys)
    assert [b["project"] for b in evidence["boards"]] == ["asgard", "operations"]
    assert evidence["correction"] is False


def test_route_without_correction_routes_identically(capsys):
    """The direct D1 regression: the card's command minus --correction (it
    already has none) and another shape with the flag — the evidence carries
    one record per carrying board either way, proving entry is not gated on
    the flag."""
    argv = _card_command()  # no --correction
    gql, code = _route_main(
        argv, _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    )
    assert code == 0
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }


def test_route_with_correction_saga_argv_routes_identically(capsys):
    """Saga's deployed argv (board_progression.py:448-461): --project ...
    --field Status --option <v> --correction, no --reason — succeeds and
    routes through the same cross-board path. This pins that W6 did not break
    the deployed Saga writer."""
    argv = [
        "sdlc_manager.py",
        "flow",
        "set-field",
        "--project",
        "operations",
        "--repo",
        REPO,
        "--number",
        str(NUMBER),
        "--field",
        "Status",
        "--option",
        "Shaping",
        "--correction",
    ]
    gql, code = _route_main(
        argv, _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    )
    assert code == 0
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }
    evidence = _out_json(capsys)
    assert evidence["correction"] is True
    assert evidence["reason"] == sdlc_manager.REASON_NOT_SUPPLIED


def test_route_in_process_caller_routes_without_correction():
    """The :5050 issue-create post-step shape — an in-process call with no
    correction argument — routes cross-board (writes every carrying board)."""
    env = _gql_side_effect(
        _TWO_BOARD_DISCOVERY,
        [
            _fields_response("PVT_asgard", ("Status", ["Active"])),
            _fields_response("PVT_operations", ("Status", ["Active"])),
        ],
        [{}, {}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field("operations", REPO, NUMBER, "Status", "Active", "text")

    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }


# --- Routing: bulk and mixed -------------------------------------------------


def test_route_bulk_routes_cross_board_per_issue_and_stays_per_issue_atomic(capsys):
    """A two-issue ``--numbers`` run: issue 42 writes both of its boards;
    issue 43's write fails and is reported as a ``failed`` row — issue 42's
    boards stay written (per-issue atomicity, not per-invocation rollback)."""
    from collections import deque

    discoveries = deque(
        [
            _TWO_BOARD_DISCOVERY,
            _discovery(
                [
                    _item(
                        "PVTI_b",
                        2,
                        "Asgard",
                        "Shaping",
                    )
                ]
            ),
        ]
    )
    fields = [
        _fields_response("PVT_asgard", ("Status", ["Shaping", "Active"])),
        _fields_response("PVT_operations", ("Status", ["Shaping", "Active"])),
        _fields_response("PVT_asgard", ("Status", ["Shaping", "Active"])),
    ]
    write_queue = [{}, {}, RuntimeError("issue 43 board down")]

    def gql_side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS:
            return discoveries.popleft()
        if query == sdlc_manager.QUERY_GET_PROJECT_FIELDS:
            return fields.pop(0)
        if query == sdlc_manager.QUERY_SET_FIELD_VALUE:
            entry = write_queue.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return {}
        raise AssertionError(f"unexpected query: {query[:80]}")

    with (
        patch.object(sdlc_manager, "_graphql", side_effect=gql_side_effect) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match="failed for 1 of 2"),
    ):
        sdlc_manager.flow_set_fields_bulk(
            "operations", REPO, [42, 43], [("Status", "Shaping")], "json", reason="regroup"
        )

    writes = _set_field_calls(gql)
    assert {c.args[1]["itemId"] for c in writes[:2]} == {"PVTI_a", "PVTI_o"}
    assert len(_discovery_calls(gql)) == 2

    result = _out_json(capsys)
    assert result["updated"] == [
        {"repo": REPO, "number": 42, "field": "Status", "option": "Shaping"}
    ]
    assert result["failed"][0]["number"] == 43


def test_route_case_variant_status_lower_routes_cross_board(capsys):
    """F-1 regression (Code Review cycle 1): `--field status` — the exact
    spelling that slipped past exact-membership routing onto one board —
    reaches the cross-board mutation: board discovery runs, BOTH carrying
    boards are written, and the emitted evidence carries the CANONICAL field
    name. Failed before the `_canonical_lifecycle_field` fix."""
    argv = [
        "sdlc_manager.py",
        "flow",
        "set-field",
        "--project",
        "operations",
        "--repo",
        REPO,
        "--number",
        str(NUMBER),
        "--field",
        "status",
        "--option",
        "Shaping",
    ]
    gql, code = _route_main(
        argv, _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    )
    assert code == 0
    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }
    evidence = _out_json(capsys)
    assert evidence["field"] == "Status"  # canonicalized into the evidence
    assert [b["project"] for b in evidence["boards"]] == ["asgard", "operations"]


def test_route_case_variant_status_upper_routes_in_process(capsys):
    """F-1 regression: an in-process `STATUS` call routes cross-board with the
    canonical name — no exact-membership bypass."""
    env = _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field("operations", REPO, NUMBER, "STATUS", "Shaping", "json")

    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }
    evidence = _out_json(capsys)
    assert evidence["field"] == "Status"


def test_route_case_variant_mixed_case_routes_in_process(capsys) -> None:
    """F-1 normalization, not a two-spelling table: `StAtUs` routes too —
    one discovery pass, both carrying boards written, canonical field name."""
    env = _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field("operations", REPO, NUMBER, "StAtUs", "Shaping", "json")

    evidence = _out_json(capsys)

    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }
    assert evidence["field"] == "Status"


def test_route_bulk_case_variant_status_routes_cross_board(capsys):
    """F-1 regression at the bulk entry point: `("status", "Shaping")` routes
    per issue through the cross-board mutation."""
    env = _gql_side_effect(
        _TWO_BOARD_DISCOVERY,
        list(_STATUS_FIELDS),
        [{}, {}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_fields_bulk(
            "operations", REPO, [NUMBER], [("status", "Shaping")], "json"
        )

    assert len(_discovery_calls(gql)) == 1
    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }


def test_non_lifecycle_fields_keep_single_board_path():
    """The guard against over-routing: an Objective write — and a Priority
    write — take the single-board path only: ONE field-write mutation and NO
    lifecycle board-discovery query in the _graphql call list."""
    for field_name, option_name in (("Objective", "platform-v1"), ("Priority", "P1")):
        env = _gql_side_effect(
            None,  # lifecycle discovery must not run in this test
            [
                _fields_response(
                    "PVT_operations", (field_name, [option_name]), ("Status", ["Active"])
                )
            ],
            [{}],
            [_items_response()],
        )
        with (
            patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
            patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        ):
            sdlc_manager.flow_set_field("operations", REPO, NUMBER, field_name, option_name, "text")

        assert _discovery_calls(gql) == [], f"{field_name} must not trigger board discovery"
        writes = _set_field_calls(gql)
        assert len(writes) == 1
        assert writes[0].args[1]["fieldId"] == f"F_PVT_operations_{field_name}"
        assert writes[0].args[1]["itemId"] == "PVTI_legacy"


def test_mixed_bulk_routes_status_cross_board_and_objective_single_board(capsys):
    """One invocation setting Status AND Objective on one issue: the Status
    assignment routes cross-board, the Objective assignment single-board —
    KTD10 applies per assignment, not per invocation."""
    fields = [
        _fields_response("PVT_asgard", ("Status", ["Shaping"])),
        _fields_response("PVT_operations", ("Status", ["Shaping"])),
        _fields_response("PVT_operations", ("Objective", ["platform-v1"])),
    ]
    env = _gql_side_effect(
        _TWO_BOARD_DISCOVERY,
        fields,
        [{}, {}, {}],
        [_items_response()],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_fields_bulk(
            "operations",
            REPO,
            [NUMBER],
            [("Status", "Shaping"), ("Objective", "platform-v1")],
            "json",
        )

    writes = _set_field_calls(gql)
    assert len(writes) == 3
    assert len(_discovery_calls(gql)) == 1  # exactly one cross-board discovery pass
    objective_writes = [c for c in writes if c.args[1]["fieldId"] == "F_PVT_operations_Objective"]
    assert len(objective_writes) == 1
    assert objective_writes[0].args[1]["itemId"] == "PVTI_legacy"


# --- --project validation, --reason, halt propagation ------------------------


def test_project_not_carrying_raises_and_writes_nothing():
    """``--project campps`` on an issue carried only by Asgard raises before
    anything is written — --project is validated against the carrying boards,
    never silently ignored (KTD10)."""
    env = _gql_side_effect(
        _discovery([_item("PVTI_a", 2, "Asgard", "Shaping")]),
        [],  # preflight must never run
        [],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(SystemExit) as exc_info,
    ):
        _args = _card_command("--correction")
        _args[_args.index("operations")] = "campps"
        with patch.object(sys, "argv", _args):
            sdlc_manager.main()

    assert exc_info.value.code == 1
    assert _set_field_calls(gql) == []


def test_project_validated_not_obeyed_writes_both_carrying_boards():
    """``--project operations`` on a two-board issue writes BOTH boards —
    the flag validates, it never restricts (KTD10)."""
    env = _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field("operations", REPO, NUMBER, "Status", "Shaping", "json")

    assert {c.args[1]["projectId"] for c in _set_field_calls(gql)} == {
        "PVT_asgard",
        "PVT_operations",
    }


def test_reason_absent_records_explicit_sentinel(capsys):
    """No --reason supplied: the evidence records the KTD11 sentinel —
    asserted against its literal string so a future edit cannot quietly
    replace it with a fabricated justification."""
    env = _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field("operations", REPO, NUMBER, "Status", "Shaping", "json")

    evidence = _out_json(capsys)
    assert sdlc_manager.REASON_NOT_SUPPLIED == "reason-not-supplied"
    assert evidence["reason"] == "reason-not-supplied"


def test_reason_present_recorded_verbatim_on_every_board(capsys):
    """A caller's reason is recorded verbatim, per board record."""
    reason = "failed verify, returning to active"
    env = _gql_side_effect(_TWO_BOARD_DISCOVERY, list(_STATUS_FIELDS), [{}, {}])
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        sdlc_manager.flow_set_field(
            "operations", REPO, NUMBER, "Status", "Shaping", "json", reason=reason
        )

    evidence = _out_json(capsys)
    assert evidence["reason"] == reason
    assert all(b["reason"] == reason for b in evidence["boards"])


def _halt_env():
    """Issue 42 on two boards: asgard writes, operations' write fails, and
    asgard's restore ALSO fails — the R67 halt."""
    fields = [
        _fields_response("PVT_asgard", ("Status", ["Shaping", "Active"])),
        _fields_response("PVT_operations", ("Status", ["Shaping", "Active"])),
    ]
    write_queue = [{}, RuntimeError("operations board down"), RuntimeError("restore down")]

    def gql_side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_LIFECYCLE_FIELD_BOARDS:
            return _TWO_BOARD_DISCOVERY
        if query == sdlc_manager.QUERY_GET_PROJECT_FIELDS:
            return fields.pop(0)
        if query == sdlc_manager.QUERY_SET_FIELD_VALUE:
            entry = write_queue.pop(0)
            if isinstance(entry, Exception):
                raise entry
            return {}
        raise AssertionError(f"unexpected query: {query[:80]}")

    return gql_side_effect


def test_compensation_halt_not_swallowed_by_runtime_error_guard():
    """The prepared-issue field loop (:5514) guards every flow_set_field call
    with ``except RuntimeError: warn-then-continue``. W6 must not edit that
    loop, so the halt exception derives from Exception — a compensation
    failure survives the EXACT guard shape the loop uses, instead of being
    downgraded to a warning and leaving the divergence unreported (R67)."""
    assert not issubclass(sdlc_manager.LifecycleMutationHaltError, RuntimeError)

    def _guarded(call):
        try:
            call()
            return "completed"
        except RuntimeError as exc:  # the :5514 warn-and-continue shape
            return f"warned-and-continued: {exc}"

    with (
        patch.object(sdlc_manager, "_graphql", side_effect=_halt_env()),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):

        def _loop_body():
            sdlc_manager.flow_set_field("operations", REPO, NUMBER, "Status", "Shaping", "text")

        with pytest.raises(sdlc_manager.LifecycleMutationHaltError):
            _guarded(_loop_body)


def test_main_halt_arm_exits_one_with_named_divergence(capsys):
    """R67 + System-Wide-Impact machine-readability: a compensation failure
    through the CLI EXITS NON-ZERO, names the divergence, and does not present
    as an ordinary command failure."""
    with (
        patch.object(sys, "argv", _card_command()),
        patch.object(sdlc_manager, "_graphql", side_effect=_halt_env()),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(SystemExit) as exc_info,
    ):
        sdlc_manager.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "COMPENSATION FAILED" in err
    assert "asgard still shows 'Shaping'" in err
    assert capsys.readouterr().out == ""
