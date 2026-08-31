"""Tests for the identity-preserving single-select option-set helper.

Acceptance selectors (match ``pytest -k`` from the plugins repository root):

  * option_identity — a retained option must carry its existing id, and
    dropping a live option from the submission is refused; both BEFORE the
    mutation leaves the process, because the API overwrites the whole option
    set and either slip clears item values.
  * option_set_complete_list — the submitted list must be the complete
    desired set (the naive one-option write is refused outright).

All GitHub/GraphQL calls are patched at the sdlc_manager-module level — no
network. The destructive mutation constant is `QUERY_UPDATE_FIELD_OPTIONS`;
every error-path assertion is that this constant is NEVER sent.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

FIELD_ID = "PVTF_status"


def _opt(opt_id: str, name: str, color: str = "GRAY", description: str | None = None):
    entry = {"id": opt_id, "name": name, "color": color}
    if description is not None:
        entry["description"] = description
    return entry


CURRENT = [
    _opt("OPT_idea", "Idea", "GRAY", "Captured but not shaped"),
    _opt("OPT_shaping", "Shaping", "YELLOW", "Being shaped by the operator"),
    _opt("OPT_ready", "Ready", "GREEN", "Ready for dispatch"),
]


def _mutation_calls(mock_graphql):
    return [
        c
        for c in mock_graphql.call_args_list
        if c.args[0] == sdlc_manager.QUERY_UPDATE_FIELD_OPTIONS
    ]


def _identity_error(match):
    return pytest.raises(sdlc_manager.OptionSetIdentityError, match=match)


def test_option_identity_rejects_submission_omitting_a_live_option() -> None:
    """Dropping a live option from the submission is refused before the write."""
    desired = [_opt("OPT_idea", "Idea"), _opt("OPT_shaping", "Shaping", "YELLOW")]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("omits live option"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_retained_option_without_existing_id() -> None:
    """A retained or renamed option submitted without its id is rejected: omitting
    the id mints a new option and clears every item value pointing at the old one."""
    retained_no_id = {"name": "Ready", "color": "GREEN"}
    desired = [
        _opt("OPT_idea", "Idea"),
        _opt("OPT_shaping", "Shaping", "YELLOW"),
        retained_no_id,
    ]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("already exists"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_set_complete_list_refuses_one_option_write() -> None:
    """The naive one-option add — the exact shape the removed unsafe reference page
    documented — is refused: it would replace the whole set with one option."""
    desired = [{"name": "new-initiative", "color": "PURPLE"}]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("omits live option"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_set_complete_list_refuses_empty_submission() -> None:
    """Empty input is ignored by the API — a silent no-op that must not read as success."""
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("empty option list"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, [], current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_unknown_id_not_on_live_field() -> None:
    """Only ids fetched from the live field may be submitted."""
    desired = list(CURRENT) + [_opt("OPT_bogus", "Phantom")]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("does not exist"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_duplicate_ids() -> None:
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("more than once"),
    ):
        sdlc_manager.update_field_single_select_options(
            FIELD_ID,
            [_opt("OPT_idea", "Idea"), _opt("OPT_idea", "Idea (again)")],
            current_options=CURRENT,
        )
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_case_insensitive_duplicate_names() -> None:
    """A same-name-same-casefold collision INSIDE the submission is caught —
    case-insensitively (cycle-1 finding F-9: this case previously hid behind a
    shared pytest.raises and never ran). The live-option-name variant of the
    same hazard is covered by ..._rejects_retained_option_without_existing_id."""
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("more than once"),
    ):
        sdlc_manager.update_field_single_select_options(
            FIELD_ID,
            [_opt("OPT_idea", "Idea"), _opt("OPT_shaping", "IDEA", "YELLOW")],
            current_options=CURRENT,
        )
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_out_of_enum_colour() -> None:
    desired = [
        _opt("OPT_idea", "Idea", "MAGENTA"),
        _opt("OPT_shaping", "Shaping", "YELLOW"),
        _opt("OPT_ready", "Ready", "GREEN"),
    ]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("allowed enum"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_option_identity_rejects_missing_colour() -> None:
    """A submission must be fully explicit — a colour-less retained option could
    silently drop its colour on the overwrite."""
    partial = [
        {"id": "OPT_idea", "name": "Idea"},
        _opt("OPT_shaping", "Shaping", "YELLOW"),
        _opt("OPT_ready", "Ready", "GREEN"),
    ]
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("allowed enum"),
    ):
        sdlc_manager.update_field_single_select_options(FIELD_ID, partial, current_options=CURRENT)
    assert _mutation_calls(mock_graphql) == []


def test_rename_round_trip_preserves_option_ids_and_values() -> None:
    """The migration's core write: same ids, new names, plus a genuinely new option —
    every current id survives in the submitted payload and in the readback, so no
    item value is cleared. The caller omits descriptions, so the composed payload
    copies each retained option's LIVE description (cycle-2 finding F-1)."""
    desired = [
        _opt("OPT_idea", "Capturing"),
        _opt("OPT_shaping", "Discovering", "YELLOW"),
        _opt("OPT_ready", "Ready for Active", "BLUE"),
        {"name": "Blocked", "color": "RED"},
    ]
    # the post-image the server would return: retained options keep the LIVE
    # description the helper copied for the caller, the new one got ""
    returned = [
        _opt("OPT_idea", "Capturing", "GRAY", "Captured but not shaped"),
        _opt("OPT_shaping", "Discovering", "YELLOW", "Being shaped by the operator"),
        _opt("OPT_ready", "Ready for Active", "BLUE", "Ready for dispatch"),
        _opt("OPT_new_1", "Blocked", "RED", ""),
    ]
    with patch.object(sdlc_manager, "_graphql") as mock_graphql:
        mock_graphql.return_value = {
            "updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}
        }
        field = sdlc_manager.update_field_single_select_options(
            FIELD_ID, desired, current_options=CURRENT
        )

    calls = _mutation_calls(mock_graphql)
    assert len(calls) == 1
    submitted_options = calls[0].args[1]["options"]
    _assert_option_input_coercible(submitted_options)
    submitted_by_id = {o["id"]: o for o in submitted_options if "id" in o}
    live_by_id = {o["id"]: o for o in CURRENT}
    # Every live option id survives the round trip — identity preserved, no value cleared.
    for cur in CURRENT:
        assert submitted_by_id[cur["id"]]["name"] == next(
            d["name"] for d in desired if d.get("id") == cur["id"]
        )
        # the LIVE description survives composition verbatim (F-1's wipe hazard)
        assert submitted_by_id[cur["id"]]["description"] == live_by_id[cur["id"]]["description"]
        assert any(o["id"] == cur["id"] for o in field["options"])
    # Only the genuinely new option omitted its id — and it defaulted to "".
    new_entries = [o for o in submitted_options if "id" not in o]
    assert len(new_entries) == 1
    assert new_entries[0]["description"] == ""


def _assert_option_input_coercible(entries: list[dict]) -> None:
    """Compile the composed payload against the LIVE input contract.

    `ProjectV2SingleSelectFieldOptionInput` as introspected live on 2026-08-29
    (cycle-2 F-1 controller proof): `id` String (optional), `name` String!,
    `color` ProjectV2SingleSelectFieldOptionColor!, `description` String! with
    NO default — omitting description is rejected at variable coercion, and a
    blind `""` would wipe the live description. This validator is what a
    mocked `_graphql` can never catch: any composed payload that GitHub would
    refuse at coercion fails HERE instead, offline.
    """
    enum = set(sdlc_manager.VALID_OPTION_COLORS)
    for entry in entries:
        assert isinstance(entry, dict), f"entry not an object: {entry!r}"
        assert set(entry) <= {"id", "name", "color", "description"}, (
            f"entry carries a key outside the live input's fields: {entry!r}"
        )
        assert isinstance(entry.get("name"), str) and entry["name"].strip(), (
            f"name is String! — missing or empty would fail coercion: {entry!r}"
        )
        assert entry.get("color") in enum, (
            f"color is enum! — value must be inside the eight-value enum: {entry!r}"
        )
        assert isinstance(entry.get("description"), str), (
            f"description is String! with no default — omitting it makes GitHub "
            f"reject the variables at coercion (cycle-2 F-1): {entry!r}"
        )
        if "id" in entry:
            assert isinstance(entry["id"], str) and entry["id"], f"bad id: {entry!r}"


def test_composed_payload_carries_description_on_every_entry() -> None:
    """The composed submission ALWAYS carries `description` — required String!

    with no default live, so omitting it means GitHub rejects the mutation at
    variable coercion and S8 cannot execute at all (cycle-2 finding F-1)."""
    desired = [
        _opt("OPT_idea", "Capturing", "GRAY"),
        _opt("OPT_shaping", "Discovering", "YELLOW", "explicit caller description"),
        _opt("OPT_ready", "Ready for Active", "BLUE"),  # description omitted
        {"name": "Blocked", "color": "RED", "description": "Cross-cutting"},
        {"name": "Backlog", "color": "PURPLE"},  # new, caller omits description
    ]
    submitted = sdlc_manager._validate_option_set_request(desired, CURRENT)
    assert len(submitted) == 5
    for entry in submitted:
        assert isinstance(entry.get("description"), str), (
            f"entry lacks the REQUIRED description: {entry!r}"
        )


def test_retained_option_live_description_survives_composition() -> None:
    """Live Asgard Status options carry non-empty descriptions. `description`
    is String! with no default, so a blind `""` on submit would WIPE them
    (V2 exactly). A retained option whose caller omits the description gets
    the live one copied verbatim."""
    submitted = sdlc_manager._validate_option_set_request(
        [
            _opt("OPT_idea", "Capturing", "GRAY"),  # renamed, description omitted
            _opt("OPT_shaping", "Shaping", "YELLOW"),  # retained, omitted
            _opt("OPT_ready", "Ready for Active", "BLUE"),
        ],
        CURRENT,
    )
    submitted_by_id = {o["id"]: o for o in submitted}
    live_by_id = {o["id"]: o for o in CURRENT}
    for opt_id in ("OPT_idea", "OPT_shaping", "OPT_ready"):
        assert submitted_by_id[opt_id]["description"] == live_by_id[opt_id]["description"], (
            f"live description of {opt_id} was not copied through — the naive "
            "empty-string fix would wipe it on submit"
        )
    # the explicit caller value still wins over the live copy
    explicit = sdlc_manager._validate_option_set_request(
        [
            _opt("OPT_idea", "Idea", "GRAY", "caller override"),
            _opt("OPT_shaping", "Shaping", "YELLOW"),
            _opt("OPT_ready", "Ready for Active", "BLUE"),
        ],
        CURRENT,
    )
    assert explicit[0]["description"] == "caller override"


def test_payload_compiles_against_live_option_input_shape() -> None:
    """Every composed payload validates against the LIVE input contract via
    `_assert_option_input_coercible` — the compile-the-real-shape check a
    mocked `_graphql` can never provide (cycle-2 F-1's root pattern). The
    S8-shaped mixed write — renames, retained options, genuinely new options —
    coerces cleanly under the live field/type contract."""
    desired = [
        _opt("OPT_idea", "Capturing", "GRAY"),  # rename, description omitted
        _opt("OPT_shaping", "Shaping", "YELLOW"),  # retained, omitted
        _opt("OPT_ready", "Ready for Active", "BLUE"),
        {"name": "Blocked", "color": "RED", "description": "Cross-cutting"},
        {"name": "Backlog", "color": "PURPLE"},  # new, no description
    ]
    submitted = sdlc_manager._validate_option_set_request(desired, CURRENT)
    _assert_option_input_coercible(submitted)


def test_retained_option_live_description_survives_a_mutating_round_trip() -> None:
    """End-to-end through the helper's live path: the server returns exactly
    what was composed; a retained option's live description arrives back
    unchanged — composition, not a wipe."""
    desired = [
        _opt("OPT_idea", "Capturing", "GRAY"),
        _opt("OPT_shaping", "Shaping", "YELLOW"),
        _opt("OPT_ready", "Ready for Active", "BLUE"),
        {"name": "Blocked", "color": "RED"},
    ]
    submitted = sdlc_manager._validate_option_set_request(desired, CURRENT)
    returned = [
        {**entry, "id": entry.get("id", f"OPT_new_{i}")} for i, entry in enumerate(submitted, 1)
    ]
    with patch.object(sdlc_manager, "_graphql") as mock_graphql:
        mock_graphql.return_value = {
            "updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}
        }
        field = sdlc_manager.update_field_single_select_options(
            FIELD_ID, desired, current_options=CURRENT
        )
    (mutation,) = _mutation_calls(mock_graphql)
    submitted_by_id = {o["id"]: o for o in mutation.args[1]["options"] if "id" in o}
    assert submitted_by_id["OPT_idea"]["description"] == "Captured but not shaped"
    returned_by_id = {o["id"]: o for o in field["options"]}
    assert returned_by_id["OPT_idea"]["description"] == "Captured but not shaped"
    assert returned_by_id["OPT_ready"]["description"] == "Ready for dispatch"


def test_rename_is_not_mistaken_for_a_new_option() -> None:
    """Same id + new name is accepted as a rename, not rejected as a collision."""
    desired = [
        _opt("OPT_idea", "Idea", "GRAY"),
        _opt("OPT_shaping", "Shaping", "YELLOW"),
        _opt("OPT_ready", "Ready for Active", "BLUE"),
    ]
    returned = [
        _opt("OPT_idea", "Idea", "GRAY", "Captured but not shaped"),
        _opt("OPT_shaping", "Shaping", "YELLOW", "Being shaped by the operator"),
        _opt("OPT_ready", "Ready for Active", "BLUE", "Ready for dispatch"),
    ]
    with patch.object(sdlc_manager, "_graphql") as mock_graphql:
        mock_graphql.return_value = {
            "updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}
        }
        field = sdlc_manager.update_field_single_select_options(
            FIELD_ID, desired, current_options=CURRENT
        )
    names = {o["name"] for o in field["options"]}
    assert "Ready for Active" in names
    assert len(_mutation_calls(mock_graphql)) == 1


def test_genuinely_new_option_without_id_is_accepted() -> None:
    new_opt = {"name": "Blocked", "color": "RED"}
    desired = list(CURRENT) + [new_opt]
    returned = list(CURRENT) + [_opt("OPT_new_1", "Blocked", "RED", "")]
    with patch.object(sdlc_manager, "_graphql") as mock_graphql:
        mock_graphql.return_value = {
            "updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}
        }
        field = sdlc_manager.update_field_single_select_options(
            FIELD_ID, desired, current_options=CURRENT
        )
    assert len(field["options"]) == 4


def test_post_write_readback_losing_an_id_is_refused() -> None:
    """The server returned fewer ids than submitted — refuse success, do not assume."""
    desired = list(CURRENT) + [{"name": "Blocked", "color": "RED"}]
    returned = list(CURRENT)  # the new option did not come back
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("readback"),
    ):
        mock_graphql.return_value = {
            "updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}
        }
        sdlc_manager.update_field_single_select_options(FIELD_ID, desired, current_options=CURRENT)


def test_live_fetch_seam_reads_field_before_validating() -> None:
    """Without explicit current_options the helper reads the live field first and
    still refuses a non-conforming submission before the mutation constant is sent."""

    def side_effect(query, variables=None):
        if query == sdlc_manager.QUERY_GET_SINGLE_SELECT_FIELD:
            return {"node": {"id": FIELD_ID, "name": "Status", "options": CURRENT}}
        raise AssertionError(f"unexpected query: {query[:80]}")

    with (
        patch.object(sdlc_manager, "_graphql", side_effect=side_effect) as mock_graphql,
        _identity_error("omits live option"),
    ):
        sdlc_manager.update_field_single_select_options(
            FIELD_ID, [{"name": "Blocked", "color": "RED"}]
        )
    assert _mutation_calls(mock_graphql) == []
    assert mock_graphql.call_count == 1


def test_fields_set_options_dry_run_writes_nothing(tmp_path) -> None:
    """The CLI verb validates and --dry-run stops before any write."""
    opts_file = tmp_path / "options.json"
    opts_file.write_text(
        '[{"id": "OPT_idea", "name": "Idea", "color": "GRAY"},'
        ' {"id": "OPT_shaping", "name": "Shaping", "color": "YELLOW"},'
        ' {"id": "OPT_ready", "name": "Ready for Active", "color": "BLUE"}]',
        encoding="utf-8",
    )
    project = {"number": 2, "id": "PVT_asgard"}
    field = {
        "id": FIELD_ID,
        "name": "Status",
        "options": [{"id": o["id"], "name": o["name"]} for o in CURRENT],
    }
    with (
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={"project_mappings": {"projects": {"asgard": project}}},
        ),
        patch.object(sdlc_manager, "get_project_config", return_value=project),
        patch.object(sdlc_manager, "get_project_fields", return_value=("PVT_asgard", [field])),
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
    ):
        sdlc_manager.fields_set_options("asgard", "Status", str(opts_file), dry_run=True)
    assert mock_graphql.call_count == 0


def test_fields_set_options_apply_sends_complete_identity_preserving_list(tmp_path) -> None:
    """The live S8 shape (cycle-1 finding F-8): fields set-options WITHOUT
    --dry-run sends QUERY_UPDATE_FIELD_OPTIONS carrying the complete desired
    set with every existing option id preserved."""
    opts_file = tmp_path / "options.json"
    opts_file.write_text(
        '[{"id": "OPT_idea", "name": "Capturing", "color": "GRAY"},'
        ' {"id": "OPT_shaping", "name": "Shaping", "color": "YELLOW"},'
        ' {"id": "OPT_ready", "name": "Ready for Active", "color": "BLUE"},'
        ' {"name": "Blocked", "color": "RED"}]',
        encoding="utf-8",
    )
    project = {"number": 2, "id": "PVT_asgard"}
    field = {
        "id": FIELD_ID,
        "name": "Status",
        "options": [{"id": o["id"], "name": o["name"], "color": o["color"]} for o in CURRENT],
    }
    returned = [
        _opt("OPT_idea", "Capturing", "GRAY", ""),
        _opt("OPT_shaping", "Shaping", "YELLOW", ""),
        _opt("OPT_ready", "Ready for Active", "BLUE", ""),
        _opt("OPT_new_1", "Blocked", "RED", ""),
    ]

    def side_effect(query, variables=None):
        assert query == sdlc_manager.QUERY_UPDATE_FIELD_OPTIONS
        return {"updateProjectV2Field": {"projectV2Field": {"id": FIELD_ID, "options": returned}}}

    with (
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={"project_mappings": {"projects": {"asgard": project}}},
        ),
        patch.object(sdlc_manager, "get_project_config", return_value=project),
        patch.object(sdlc_manager, "get_project_fields", return_value=("PVT_asgard", [field])),
        patch.object(sdlc_manager, "_graphql", side_effect=side_effect) as mock_graphql,
    ):
        sdlc_manager.fields_set_options("asgard", "Status", str(opts_file), dry_run=False)

    (mutation,) = _mutation_calls(mock_graphql)
    submitted = mutation.args[1]["options"]
    submitted_ids = {o["id"] for o in submitted if "id" in o}
    assert submitted_ids == {o["id"] for o in CURRENT}  # every live id resubmitted
    # the rename is by-id, never a new option
    assert next(o for o in submitted if o["id"] == "OPT_ready")["name"] == "Ready for Active"
    assert len([o for o in submitted if "id" not in o]) == 1
    # and the composed payload compiles against the LIVE input contract
    _assert_option_input_coercible(submitted)


def test_option_set_complete_list_refuses_empty_live_options() -> None:
    """A submission cannot be verified as the complete set against a field read
    as having NO options (an empty or truncated read) — refuse and demand the
    live option list first (cycle-1 finding F-8, the empty-current seam)."""
    with (
        patch.object(sdlc_manager, "_graphql") as mock_graphql,
        _identity_error("live option list is empty"),
    ):
        sdlc_manager.update_field_single_select_options(
            FIELD_ID, [{"name": "one-option", "color": "RED"}], current_options=[]
        )
    assert _mutation_calls(mock_graphql) == []


def test_unsafe_reference_query_removed_from_mission_control() -> None:
    """Regression for issue #94 M2/M3: the documented one-option mutation — which
    under the API's whole-set overwrite would clear every card value on a
    362-card field — must not survive anywhere in the plugin as guidance."""
    reference = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "board"
        / "references"
        / "graphql-queries.md"
    )
    text = reference.read_text(encoding="utf-8")
    # Composed at runtime so this test file itself never carries the forbidden
    # token — the acceptance grep over plugins/mission-control/ must return nothing.
    unsafe_constant = "QUERY_" + "CREATE" + "_FIELD_OPTION"
    assert unsafe_constant not in text
    assert "singleSelectOptions: [{ name: $name" not in text
    # The safe entry point is documented in its place.
    assert "QUERY_UPDATE_FIELD_OPTIONS" in text
    assert "update_field_single_select_options" in text
