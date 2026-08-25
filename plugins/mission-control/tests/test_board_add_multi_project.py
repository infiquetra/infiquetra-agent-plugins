"""Tests for `board add` explicit multi-project membership (U12).

The U12 live smoke test confirmed native Projects-v2 multi-membership
(KTD10): one issue node id added to two boards via separate
`addProjectV2ItemById` mutations carries INDEPENDENT per-board Status — it
is not a clone. These tests pin the tooling that exposes that behavior:

  * `board add --project A --project B` adds the SAME content/item id to the
    two DISTINCT project ids via exactly two add-to-project mutations
    (independent memberships, not a clone).
  * back-compat: a single `--project` still targets exactly that one
    project; no `--project` still resolves via `get_projects_for_repo`
    (the repo → project mapping).

All GitHub/GraphQL calls are patched at the sdlc_manager-module level — no
real network. `_graphql` is the single mutation funnel for both the
node-id lookup and each add-to-project call, so asserting on its call list
fully characterizes the membership behavior offline.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

# Item node id returned by the QUERY_GET_ITEM_NODE_ID lookup. The SAME id
# must be the contentId on every add-to-project mutation — that sameness is
# what proves multi-membership (one item, many boards) rather than cloning
# (a fresh item per board).
_ITEM_NODE_ID = "I_kwItemNode123"

# Distinct project node ids for the two boards. The add mutations must carry
# these two distinct projectIds — that distinctness is what proves the item
# lands on two SEPARATE boards.
_OLYMPUS_PROJECT_ID = "PVT_olympus"
_ASGARD_PROJECT_ID = "PVT_asgard"

_NODE_ID_RESPONSE = {
    "repository": {
        "issueOrPullRequest": {
            "__typename": "Issue",
            "id": _ITEM_NODE_ID,
            "number": 42,
            "title": "demo issue",
        },
    }
}

# Generic add-to-project mutation response (shape is irrelevant to board_add;
# it never reads it back, it only cares that the call did not raise).
_ADD_RESPONSE = {"addProjectV2ItemById": {"item": {"id": "PVTI_membership"}}}


def _multi_board_config() -> dict:
    """Config with two long-lived boards an item can be explicitly placed on.

    Note both projects intentionally list DIFFERENT `repositories` (and
    neither lists `demo-repo`) so that the explicit-project path cannot be
    silently satisfied by the repo-mapping fallback — the only way both
    boards get the item is via the explicit `--project A --project B` path.
    """
    return {
        "project_mappings": {
            "projects": {
                "mount-olympus": {
                    "number": 1,
                    "name": "Mount Olympus",
                    "id": _OLYMPUS_PROJECT_ID,
                    "repositories": ["athena-service"],
                },
                "asgard": {
                    "number": 2,
                    "name": "Asgard",
                    "id": _ASGARD_PROJECT_ID,
                    "repositories": ["campps-mvp"],
                },
            }
        }
    }


def _add_mutation_calls(mock_gql) -> list[dict]:
    """Return the variables dict of every QUERY_ADD_ITEM_TO_PROJECT call.

    Filters the _graphql call list down to the add-to-project mutation,
    ignoring the single up-front node-id lookup.
    """
    return [
        call.args[1]
        for call in mock_gql.call_args_list
        if call.args[0] == sdlc_manager.QUERY_ADD_ITEM_TO_PROJECT
    ]


def test_board_add_multi_project() -> None:
    """One issue + two explicitly-named projects → exactly two add-to-project
    mutations, SAME content/item id, two DISTINCT project ids.

    This is the U12 contract: independent multi-membership, not a clone."""
    config = _multi_board_config()

    with patch.object(sdlc_manager, "_graphql") as mock_gql:
        # Call 1: node-id lookup. Calls 2..N: one add per project.
        mock_gql.side_effect = [_NODE_ID_RESPONSE, _ADD_RESPONSE, _ADD_RESPONSE]

        sdlc_manager.board_add(
            "demo-repo",
            42,
            fmt="text",
            config=config,
            project_names=["mount-olympus", "asgard"],
        )

    add_calls = _add_mutation_calls(mock_gql)

    # Exactly two add mutations — one membership per named board.
    assert len(add_calls) == 2, (
        f"Expected exactly 2 add-to-project mutations, got {len(add_calls)}: {add_calls}"
    )

    # SAME item id on every membership → multi-membership, NOT a clone.
    content_ids = {c["contentId"] for c in add_calls}
    assert content_ids == {_ITEM_NODE_ID}, (
        f"All memberships must reuse the one item node id (not clone); got {content_ids}"
    )

    # Two DISTINCT project ids → the two separate boards.
    project_ids = {c["projectId"] for c in add_calls}
    assert project_ids == {_OLYMPUS_PROJECT_ID, _ASGARD_PROJECT_ID}, (
        f"Expected memberships on both distinct boards; got {project_ids}"
    )

    # And the node-id lookup happened exactly once (one item resolved, then
    # reused) — reinforces "one item, two memberships".
    node_lookups = [
        c for c in mock_gql.call_args_list if c.args[0] == sdlc_manager.QUERY_GET_ITEM_NODE_ID
    ]
    assert len(node_lookups) == 1


def test_board_add_multi_project_dedups_repeated_project() -> None:
    """A repeated `--project olympus --project olympus` collapses to a single
    membership — the order-preserving de-dup must not emit two identical
    add mutations for the same board."""
    config = _multi_board_config()

    with patch.object(sdlc_manager, "_graphql") as mock_gql:
        mock_gql.side_effect = [_NODE_ID_RESPONSE, _ADD_RESPONSE]

        sdlc_manager.board_add(
            "demo-repo",
            42,
            fmt="text",
            config=config,
            project_names=["mount-olympus", "mount-olympus"],
        )

    add_calls = _add_mutation_calls(mock_gql)
    assert len(add_calls) == 1, f"Repeated project must de-dup to one add; got {add_calls}"
    assert add_calls[0]["projectId"] == _OLYMPUS_PROJECT_ID


def test_board_add_single_project_back_compat() -> None:
    """A single explicit project (`project_name=...`, the pre-U12 call shape)
    still adds to exactly that one board — unchanged behavior."""
    config = _multi_board_config()

    with patch.object(sdlc_manager, "_graphql") as mock_gql:
        mock_gql.side_effect = [_NODE_ID_RESPONSE, _ADD_RESPONSE]

        sdlc_manager.board_add(
            "demo-repo",
            42,
            fmt="text",
            config=config,
            project_name="asgard",
        )

    add_calls = _add_mutation_calls(mock_gql)
    assert len(add_calls) == 1, f"Single project must add exactly once; got {add_calls}"
    assert add_calls[0]["projectId"] == _ASGARD_PROJECT_ID
    assert add_calls[0]["contentId"] == _ITEM_NODE_ID


def test_board_add_no_project_uses_repo_mapping() -> None:
    """No explicit project → fall back to `get_projects_for_repo` (the repo →
    project mapping). The repo is mapped to exactly one board here, so the
    item lands on that board and nowhere else — the precedence-3 path is
    unchanged."""
    config = _multi_board_config()
    # `athena-service` is in mount-olympus's repositories (and not asgard's),
    # so the repo-mapping fallback must resolve to mount-olympus only.

    with patch.object(sdlc_manager, "_graphql") as mock_gql:
        mock_gql.side_effect = [_NODE_ID_RESPONSE, _ADD_RESPONSE]

        sdlc_manager.board_add(
            "athena-service",
            42,
            fmt="text",
            config=config,
        )

    add_calls = _add_mutation_calls(mock_gql)
    assert len(add_calls) == 1, f"Repo-mapping fallback should add once here; got {add_calls}"
    assert add_calls[0]["projectId"] == _OLYMPUS_PROJECT_ID


def test_board_add_multi_project_fault_isolation() -> None:
    """If the add to the FIRST named project fails, the SECOND still gets its
    membership — per-project fault isolation (one board failing must not
    abort the others). Verified by asserting both add mutations were
    attempted despite the first raising."""
    config = _multi_board_config()

    def _graphql_side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_ITEM_NODE_ID:
            return _NODE_ID_RESPONSE
        # Fail the olympus add, succeed the asgard add.
        if variables and variables.get("projectId") == _OLYMPUS_PROJECT_ID:
            raise RuntimeError("simulated add failure for olympus")
        return _ADD_RESPONSE

    with patch.object(sdlc_manager, "_graphql", side_effect=_graphql_side_effect) as mock_gql:
        sdlc_manager.board_add(
            "demo-repo",
            42,
            fmt="text",
            config=config,
            project_names=["mount-olympus", "asgard"],
        )

    add_calls = _add_mutation_calls(mock_gql)
    # BOTH adds were attempted — the failing one did not abort the loop.
    project_ids = [c["projectId"] for c in add_calls]
    assert project_ids == [_OLYMPUS_PROJECT_ID, _ASGARD_PROJECT_ID], (
        f"Both memberships must be attempted despite the first failing; got {project_ids}"
    )
