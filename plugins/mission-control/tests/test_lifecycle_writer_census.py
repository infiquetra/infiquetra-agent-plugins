"""Tests for W6/U4 — the KTD12 writer census gate (issue #87, Plan Review D2).

The invariant: ``QUERY_SET_FIELD_VALUE`` (:874) is the ONE GraphQL mutation
that writes a project-field value in this plugin. The census anchors on that
CONSTANT — not on the ``_set_project_field_value`` helper, whose caller list
missed ``board_move`` (the D2 failure) — and is enforced as an AST allowlist
over every function whose body references it. A new function that starts
writing project fields fails this test on the next run.

With U6 shipped, the allowlist contains no lifecycle writers:
``_set_project_field_value`` serves the constrained mutation (and every
non-lifecycle field), and ``_sync_label_fields_for_item`` is inert unless a
project config declares ``label_fields``.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SOURCE_PATH = SCRIPTS / "sdlc_manager.py"
MAPPINGS_PATH = SCRIPTS.parent / "config" / "project-mappings.json"
TESTS_PATH = Path(__file__).resolve().parent

_MUTATION_CONST = "QUERY_SET_FIELD_VALUE"

# The complete allowlist of functions allowed to reference the project-field
# write mutation. NOT a lifecycle writer among them: U6 rerouted board_move,
# and it must never reappear here without rerouting again.
ALLOWED_WRITERS = frozenset({"_set_project_field_value", "_sync_label_fields_for_item"})

# Issue #87's six acceptance selectors. pytest -k on a name that matches
# nothing exits 0, reading as a passing gate — so each must be hit by at
# least one real test name.
REQUIRED_SELECTORS = (
    "mutation_idempotency",
    "field_identity",
    "cross_board_atomic",
    "compensation_failure",
    "backward_move",
    "skipped_stage",
)


def _referencing_functions(source: str, constant: str) -> set[str]:
    """Return the set of function names whose body references ``constant``."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == constant:
                    found.add(node.name)
    return found


def test_writer_census_allowlist_matches_exactly() -> None:
    """The D2 repair: the set of QUERY_SET_FIELD_VALUE-referencing functions
    equals the hard-coded allowlist. Asserted as a SET — a message naming the
    unexpected function is the whole value of this test."""
    found = _referencing_functions(SOURCE_PATH.read_text(encoding="utf-8"), _MUTATION_CONST)
    unexpected = found - ALLOWED_WRITERS
    missing = ALLOWED_WRITERS - found
    assert not unexpected and not missing, (
        f"project-field writer census changed: unexpected writers {sorted(unexpected)}, "
        f"missing {sorted(missing)}. Every new project-field writer must route "
        f"lifecycle fields through _set_lifecycle_field_cross_board."
    )


def test_writer_census_regression_detects_unlisted_writer() -> None:
    """The D2 shape, reproduced: the same helper that enforces the allowlist
    DETECTS a synthetic fourth writer — proving the gate finds an unlisted
    writer rather than passing because today's list happens to match."""
    synthetic = (
        f"{_MUTATION_CONST} = 'mutation {{ x }}'\n"
        "def known_writer():\n"
        f"    return {_MUTATION_CONST}\n"
        "def rogue_writer(graphql):\n"
        f"    graphql({_MUTATION_CONST})\n"
    )
    found = _referencing_functions(synthetic, _MUTATION_CONST)
    assert found == {"known_writer", "rogue_writer"}
    assert found - {"known_writer"} == {"rogue_writer"}


def test_lifecycle_writers_route_board_move_not_in_allowlist() -> None:
    """U6 landed: board_move's Status write goes through the constrained
    mutation, so it no longer references the mutation constant directly. The
    allowlist is the record of what is outstanding — it must not be
    outstanding and invisible at the same time."""
    found = _referencing_functions(SOURCE_PATH.read_text(encoding="utf-8"), _MUTATION_CONST)
    assert "board_move" not in found
    # ...and board_move still exists and delegates (its body names the mutation).
    board_move_src = SOURCE_PATH.read_text(encoding="utf-8")
    assert "def board_move(" in board_move_src
    assert "_set_lifecycle_field_cross_board(" in board_move_src


def test_single_write_primitive_mutation_constant() -> None:
    """The census anchor is sound only if there is exactly one project-field
    write mutation: no second constant wrapping
    updateProjectV2ItemFieldValue, and no clearProjectV2ItemFieldValue
    anywhere (KTD8's dependency — "restore to unset" must not silently
    become possible)."""
    source = SOURCE_PATH.read_text(encoding="utf-8")
    set_constants = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "updateProjectV2ItemFieldValue" in node.value
    ]
    assert len(set_constants) == 1, (
        f"expected exactly one updateProjectV2ItemFieldValue mutation constant, "
        f"found {len(set_constants)} — anchor the census on the real single primitive"
    )
    assert "clearProjectV2ItemFieldValue" not in source


def test_no_label_fields_target_lifecycle_fields() -> None:
    """Pin the latent leak at the old :1549: _sync_label_fields_for_item
    writes whatever field a project's label_fields map names. No project may
    declare an entry targeting Status or Stage — the configuration change
    fails here rather than silently opening an unconstrained lifecycle
    writer."""
    config = json.loads(MAPPINGS_PATH.read_text(encoding="utf-8"))
    projects = config.get("projects", {})
    for key, proj in projects.items():
        label_fields = proj.get("label_fields", {})
        for prefix, cfg in label_fields.items():
            subtree = json.dumps({"prefix": prefix, "config": cfg})
            assert "Status" not in subtree and "Stage" not in subtree, (
                f"project '{key}' label_fields entry '{prefix}' targets a lifecycle "
                f"field; lifecycle fields must only move through the constrained "
                f"lifecycle-field mutation"
            )


def test_acceptance_selectors_match_at_least_one_test() -> None:
    """Selector coverage guard: each of issue #87's six selector substrings
    matches at least one collected test name — the failure mode this
    prevents is a rename that leaves ``pytest -k`` green and empty on the
    card's verification commands."""
    names: list[str] = []
    for path in sorted(TESTS_PATH.glob("test_*.py")):
        for match in re.finditer(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.M):
            names.append(match.group(1))
    assert len(names) > 50, "selector guard lost sight of the suite"
    for selector in REQUIRED_SELECTORS:
        hits = [n for n in names if selector in n]
        assert hits, (
            f"selector {selector!r} matches no test name; issue #87's "
            f"verification command would exit 0 green and prove nothing"
        )
