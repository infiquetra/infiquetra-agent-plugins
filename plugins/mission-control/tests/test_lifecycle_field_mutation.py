"""Tests for W6/U3+U4 — the constrained cross-board lifecycle mutation (issue #87).

Acceptance examples proved here (selectors match ``pytest -k`` from the
plugins repository root, per ``pyproject.toml`` testpaths):

  * AE9  — cross_board_atomic / compensation_failure
  * AE27 — backward_move (with test_lifecycle_field_routing.py's
           cross_board_atomic rows)
  * AE37 — skipped_stage
  * AE3  — mutation_idempotency (with test_lifecycle_field_identity.py)

All GitHub/GraphQL calls are patched at the sdlc_manager-module level — no
network. Call-order assertions rely on the deterministic board order
(lowest project number first).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

_ABSENT = ...  # sentinel: board does not carry the field at all

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


def _item(item_id: str, number: int, title: str, status_value=_ABSENT):
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


def _discovery(nodes) -> dict:
    return {"repository": {"issue": {"projectItems": {"nodes": list(nodes)}}}}


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
    """One side_effect over the three query kinds. Queues are consumed in the
    deterministic call order; an Exception queue entry is raised. No entry for
    a SET_FIELD_VALUE call means "ordinary success" ({})."""

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
        raise AssertionError(f"unexpected query routed to _graphql: {query[:80]}")

    return side_effect


def _set_field_calls(mock_gql) -> list:
    return [c for c in mock_gql.call_args_list if c.args[0] == sdlc_manager.QUERY_SET_FIELD_VALUE]


def _two_board_env(
    *,
    # Uniform priors by default: since F-7, a call from ALREADY-divergent
    # boards halts before the first write, so behavior tests of the write/
    # compensate path start from a consistent pre-call state.
    prior_a="Idea",
    prior_o="Idea",
    field_responses=None,
    write_responses=None,
):
    """Backboarded two-board issue: Asgard (#2, item PVTI_a) then Operations
    (#3, item PVTI_o) — the deterministic write order."""
    board_a = _item("PVTI_a", 2, "Asgard", prior_a)
    board_o = _item("PVTI_o", 3, "Operations", prior_o)
    fields = (
        field_responses
        if field_responses is not None
        else [
            _fields_response("PVT_asgard", "Idea", "Shaping", "Active", "Verify", "Done"),
            _fields_response(
                "PVT_operations", "Idea", "Shaping", "Active", "Verify", "Ready to merge"
            ),
        ]
    )
    return _gql_side_effect(_discovery([board_a, board_o]), fields, write_responses or [])


def test_cross_board_atomic_write_reaches_every_carrying_board_with_evidence() -> None:
    """AE9 happy half: a two-board Status write produces the SAME semantic
    Status on both boards, plus one evidence record per board (AE9's first
    clause)."""
    write_responses: list = [{}, {}]
    with (
        patch.object(
            sdlc_manager, "_graphql", side_effect=_two_board_env(write_responses=write_responses)
        ) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(
            REPO, NUMBER, "Status", "Verify", reason="failed verify"
        )

    calls = _set_field_calls(gql)
    assert len(calls) == 2
    assert {c.args[1]["projectId"] for c in calls} == {"PVT_asgard", "PVT_operations"}
    assert {c.args[1]["optionId"] for c in calls} == {
        "opt_PVT_asgard_Verify",
        "opt_PVT_operations_Verify",
    }
    assert [(b["project"], b["prior_value"], b["new_value"]) for b in evidence["boards"]] == [
        ("asgard", "Idea", "Verify"),
        ("operations", "Idea", "Verify"),
    ]
    assert all(b["outcome"] == "written" for b in evidence["boards"])
    assert evidence["reason"] == "failed verify"


def test_cross_board_atomic_partial_write_failure_restores_prior_value() -> None:
    """AE9 middle clause: board 1 writes, board 2's write fails — board 1 is
    restored to its CAPTURED PRIOR value (never the target) and the failure is
    surfaced as an ordinary RuntimeError (the boards agree again)."""
    write_responses: list = [{}, RuntimeError("board 2 write failed")]
    with (
        patch.object(
            sdlc_manager, "_graphql", side_effect=_two_board_env(write_responses=write_responses)
        ) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match="restored"),
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    calls = _set_field_calls(gql)
    assert len(calls) == 3  # write asgard, write operations (fails), restore asgard
    restore_call = calls[-1]
    assert restore_call.args[1]["projectId"] == "PVT_asgard"
    assert restore_call.args[1]["optionId"] == "opt_PVT_asgard_Idea", (
        "the restore must carry board 1's PRIOR option id, not the target one"
    )


def test_cross_board_atomic_preflight_failure_writes_no_board() -> None:
    """AE9 first half of 'neither': one of the boards cannot resolve the
    target — halt before the first write, nothing changed anywhere."""
    fields = [
        _fields_response("PVT_asgard", "Shaping", "Active", "Verify"),
        _fields_response("PVT_operations", "Shaping", "Active"),  # Verify missing
    ]
    with (
        patch.object(
            sdlc_manager, "_graphql", side_effect=_two_board_env(field_responses=fields)
        ) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match="preflight failed .* operations"),
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    assert _set_field_calls(gql) == []


def test_compensation_failure_halts_with_named_reason_and_raises() -> None:
    """AE9 last clause: board 1 writes, board 2 fails, board 1's restore ALSO
    fails — halt with a named reason stating which board holds which value,
    and NO further write attempted (the no-silent-retry proof, asserted by
    call count)."""
    write_responses = [{}, RuntimeError("board 2 down"), RuntimeError("restore down")]
    with (
        patch.object(
            sdlc_manager, "_graphql", side_effect=_two_board_env(write_responses=write_responses)
        ) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(sdlc_manager.LifecycleMutationHaltError) as exc_info,
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    message = str(exc_info.value)
    assert "COMPENSATION FAILED" in message
    assert "asgard still shows 'Verify'" in message
    assert "operations" in message
    assert exc_info.value.board_state == [
        {"board": "asgard", "shows": "Verify"},  # restore failed, stuck at new value
        {"board": "operations", "shows": "Idea"},
    ]
    # Exactly discovery + 2 field preflights + 2 writes + 1 failed restore.
    # A silent retry (bounded or not) would add calls.
    calls = _set_field_calls(gql)
    assert len(calls) == 3
    assert gql.call_count == 6, "no call of any kind after the halt"


def test_compensation_failure_with_unset_prior_value_treats_restore_as_failed() -> None:
    """KTD8: the board's prior value was unset — there is no option id to
    write back and no clear primitive exists, so the restore is FAILED (R6
    halt), never a best-effort leave-it-at-the-new-value."""
    write_responses = [{}, RuntimeError("board 2 down")]
    # Asgard's prior value is None (field present, unset).
    env = _gql_side_effect(
        _discovery([_item("PVTI_a", 2, "Asgard", None), _item("PVTI_o", 3, "Operations", "Idea")]),
        [
            _fields_response("PVT_asgard", "Shaping", "Verify"),
            _fields_response("PVT_operations", "Shaping", "Active", "Idea", "Verify"),
        ],
        write_responses,
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(sdlc_manager.LifecycleMutationHaltError) as exc_info,
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    message = str(exc_info.value)
    assert "prior value was unset" in message
    assert "asgard" in message
    # No restore-write was even attempted for the unset board (nothing sane to
    # write): writes = asgard set + operations set(failed) = 2.
    assert len(_set_field_calls(gql)) == 2


def test_mutation_rejects_non_lifecycle_field_before_any_discovery() -> None:
    """R31 guard: naming any other field is rejected before a board is
    touched — asserted by ZERO graphql calls."""
    for field in ("Objective", "Priority", "Initiative"):
        with (
            patch.object(sdlc_manager, "_graphql") as gql,
            pytest.raises(RuntimeError, match="correction set-field rejects"),
        ):
            sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, field, "Anything")
        assert gql.call_count == 0, f"{field} must be rejected before discovery"


def test_mutation_idempotency_same_value_twice_same_identity_same_state() -> None:
    """Called twice with the same value: same final board state, same identity
    strings — the write is idempotent because the option resolves to the same
    id."""
    identities = []
    for _ in range(2):
        with (
            patch.object(sdlc_manager, "_graphql", side_effect=_two_board_env()) as gql,
            patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        ):
            evidence = sdlc_manager._set_lifecycle_field_cross_board(
                REPO, NUMBER, "Status", "Active", reason="tick"
            )
        identities.append(evidence["identity"]["retry"])
        assert len(_set_field_calls(gql)) == 2
    assert identities[0] == identities[1]
    assert identities[0] == f"set-field-status:{REPO}#{NUMBER}:Status:Active"


def test_backward_move_verify_to_active_accepted_with_recorded_reason() -> None:
    """AE27: a failed Verify returns the issue to Active with a recorded
    reason, and no legality check rejects the move. Asserted as BEHAVIOUR —
    the write lands on every carrying board; no code path compares target
    against prior."""
    with (
        patch.object(
            sdlc_manager,
            "_graphql",
            side_effect=_two_board_env(prior_a="Verify", prior_o="Verify"),
        ) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(
            REPO, NUMBER, "Status", "Active", reason="failed verify, returning to active"
        )

    assert len(_set_field_calls(gql)) == 2
    assert all(b["new_value"] == "Active" for b in evidence["boards"])
    assert evidence["reason"] == "failed verify, returning to active"
    assert all(b["prior_value"] == "Verify" for b in evidence["boards"])


def test_skipped_stage_intake_to_active_without_backfill() -> None:
    """AE37: Intake → Active without ever occupying Shaping (intermediate) is
    accepted, and NOTHING writes a value the caller did not name — the set of
    option ids in the call list is exactly the targets."""
    env = _gql_side_effect(
        _discovery([_item("PVTI_a", 2, "Asgard", None), _item("PVTI_o", 3, "Operations", None)]),
        [
            _fields_response(
                "PVT_asgard", "Intake", "Shaping", "Planning", "Active", "Ready to merge"
            ),
            _fields_response("PVT_operations", "Intake", "Shaping", "Planning", "Active"),
        ],
        [{}, {}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Active")

    option_ids = {c.args[1]["optionId"] for c in _set_field_calls(gql)}
    assert option_ids == {"opt_PVT_asgard_Active", "opt_PVT_operations_Active"}
    assert all(b["prior_value"] is None for b in evidence["boards"])


def test_skipped_stage_merge_to_ready_to_merge_without_review_ladder() -> None:
    """AE37 second clause: a merged change that never entered Code review or
    Repairing still reaches 'Ready to merge' — accepted, nothing back-filled."""
    env = _gql_side_effect(
        _discovery([_item("PVTI_a", 2, "Asgard", "Active")]),
        [
            _fields_response(
                "PVT_asgard", "Intake", "Active", "Code review", "Repairing", "Ready to merge"
            )
        ],
        [{}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(
            REPO, NUMBER, "Status", "Ready to merge", reason="merged"
        )

    calls = _set_field_calls(gql)
    assert [c.args[1]["optionId"] for c in calls] == ["opt_PVT_asgard_Ready to merge"]
    assert evidence["boards"][0]["prior_value"] == "Active"


def test_explicit_noop_when_issue_sits_on_no_board() -> None:
    """Edge: zero carrying boards reports the no-op explicitly — never
    success."""
    with (
        patch.object(
            sdlc_manager, "_graphql", side_effect=_gql_side_effect(_discovery([]), [], [])
        ),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match="explicit no-op"),
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Active")


def test_single_board_issue_takes_the_same_path() -> None:
    """A one-board issue: same path, no compensation possible, succeeds."""
    env = _gql_side_effect(
        _discovery([_item("PVTI_a", 2, "Asgard", "Idea")]),
        [_fields_response("PVT_asgard", "Shaping", "Active")],
        [{}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Active")

    assert len(_set_field_calls(gql)) == 1
    assert len(evidence["boards"]) == 1


def test_stage_field_writes_route_through_the_mutation_offline() -> None:
    """The mocked half of the Stage story (the live half is held until W13
    puts the field on real boards): a Stage write behaves exactly like a
    Status write — every carrying board, one prior/new evidence record each."""

    def _stage_fields_response(project_id: str, *options: str) -> dict:
        return {
            "organization": {
                "projectV2": {
                    "id": project_id,
                    "fields": {
                        "nodes": [
                            {
                                "id": f"PVTSSF_stage_{project_id}",
                                "name": "Stage",
                                "options": [
                                    {"id": f"opt_{project_id}_stage_{name}", "name": name}
                                    for name in options
                                ],
                            }
                        ],
                        "pageInfo": {"hasNextPage": False},
                    },
                }
            }
        }

    env = _gql_side_effect(
        _discovery(
            [
                _item("PVTI_a", 2, "Asgard", "Design"),
                _item("PVTI_o", 3, "Operations", "Design"),
            ]
        ),
        [
            _stage_fields_response("PVT_asgard", "Design", "Build"),
            _stage_fields_response("PVT_operations", "Design", "Build"),
        ],
        [{}, {}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
    ):
        evidence = sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Stage", "Build")

    calls = _set_field_calls(gql)
    assert len(calls) == 2
    assert {b["project"] for b in evidence["boards"]} == {"asgard", "operations"}
    assert evidence["identity"]["retry"] == f"set-field-status:{REPO}#{NUMBER}:Stage:Build"


def test_compensated_failure_message_names_failing_board() -> None:
    """F-3 regression (Code Review cycle 1): the recovered-partial-write
    RuntimeError names the board whose WRITE failed, not the last successfully
    written board. First write here succeeds on asgard; operations' write
    fails; the message must point at operations."""
    write_responses = [{}, RuntimeError("board 2 down")]
    env = _gql_side_effect(
        _discovery(
            [_item("PVTI_a", 2, "Asgard", "Idea"), _item("PVTI_o", 3, "Operations", "Idea")]
        ),
        [
            _fields_response("PVT_asgard", "Idea", "Shaping", "Verify", "Active"),
            _fields_response("PVT_operations", "Idea", "Shaping", "Verify", "Active"),
        ],
        write_responses,
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match=r"failed on board 'operations'") as exc_info,
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    message = str(exc_info.value)
    assert "operations" in message
    # The last SUCCESSFUL board is named only as restored, never as failed.
    assert "failed on board 'asgard'" not in message


def test_first_write_failure_message_names_first_board() -> None:
    """F-3 edge: `written` is empty — the message names the FIRST board, not
    the pre-fix "board '[]'" and similar blank output."""
    env = _gql_side_effect(
        _discovery(
            [_item("PVTI_a", 2, "Asgard", "Idea"), _item("PVTI_o", 3, "Operations", "Idea")]
        ),
        [
            _fields_response("PVT_asgard", "Shaping", "Active"),
            _fields_response("PVT_operations", "Shaping", "Active"),
        ],
        [RuntimeError("first board down")],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(RuntimeError, match=r"failed on board 'asgard'"),
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Active")


def test_mixed_prior_boards_halt_before_any_write() -> None:
    """F-7 regression (Code Review cycle 2): a call that STARTS from
    already-divergent carrying boards must raise LifecycleMutationHaltError
    and write NOTHING. At 4afc6ef4 this call proceeded: each board's
    divergent value became its "captured prior", the restore "succeeded",
    and the halt hid as an ordinary restore-success while the boards kept
    disagreeing — exactly what saga's live retry loop (max_attempts=3) and
    any operator retry hit after a first-attempt halt. On the unfixed
    revision this test fails with a plain RuntimeError (or success), never
    this halt.
    """
    # Pre-call state: asgard already shows Verify, operations already shows
    # Shaping — boards disagree BEFORE the call.
    env = _gql_side_effect(
        _discovery(
            [_item("PVTI_a", 2, "Asgard", "Verify"), _item("PVTI_o", 3, "Operations", "Shaping")]
        ),
        [
            _fields_response("PVT_asgard", "Idea", "Shaping", "Verify", "Active"),
            _fields_response("PVT_operations", "Idea", "Shaping", "Verify"),
        ],
        [{}, {}],  # both writes would succeed if the call were (wrongly) made
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env) as gql,
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(sdlc_manager.LifecycleMutationHaltError) as exc_info,
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Verify")

    message = str(exc_info.value)
    assert "ALREADY disagree" in message
    assert (
        "no board is written" in message
        or "do not write" in message.lower()
        or "REFUSING" in message
    )
    assert "asgard shows 'Verify'" in message
    assert "operations shows 'Shaping'" in message
    assert exc_info.value.board_state == [
        {"board": "asgard", "shows": "Verify"},
        {"board": "operations", "shows": "Shaping"},
    ]
    # The refusal happens BEFORE the first write — not even a retry-shaped
    # write attempt appears, and preflight never runs.
    assert gql.call_count == 1  # discovery only; zero field queries, zero writes
    assert _set_field_calls(gql) == []


def test_mixed_prior_refusal_does_not_describe_restore() -> None:
    """F-7 wording guard: the mixed-prior halt must not present itself as a
    completed restore / all-or-none success — the captured priors were the
    divergence itself."""
    env = _gql_side_effect(
        _discovery(
            [_item("PVTI_a", 2, "Asgard", "Verify"), _item("PVTI_o", 3, "Operations", "Shaping")]
        ),
        [
            _fields_response("PVT_asgard", "Idea", "Shaping", "Verify", "Active"),
            _fields_response("PVT_operations", "Idea", "Shaping", "Active"),
        ],
        [{}, {}],
    )
    with (
        patch.object(sdlc_manager, "_graphql", side_effect=env),
        patch.object(sdlc_manager, "load_config", return_value=MAPPING_CONFIG),
        pytest.raises(sdlc_manager.LifecycleMutationHaltError) as exc_info,
    ):
        sdlc_manager._set_lifecycle_field_cross_board(REPO, NUMBER, "Status", "Active")

    message = str(exc_info.value)
    assert "REFUSING to write" in message
    assert "were restored" not in message
    assert "restored to their prior values" not in message
