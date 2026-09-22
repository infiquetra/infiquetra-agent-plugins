"""Layer 3 — proof that each safeguard predicate reads the phrase it guards (R22).

Eight cases, one bit of information each: delete a safeguard's sentence and its predicate
flags. That establishes the predicates are not no-ops. It does NOT establish that any
safeguard's behaviour holds — a contradictory re-phrasing keeping the sentence is invisible
to a string predicate, which is why this file is named for wiring and not for proof.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]


# Import check predicates from the contract test modules via file load
def _load_module(name: str, path: Path):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cont = _load_module("cont_brainstorm", Path(__file__).resolve().parent / "test_brainstorm_continuity_contract.py")
judg = _load_module("judg_brainstorm", Path(__file__).resolve().parent / "test_brainstorm_judgment_contract.py")

BRAINSTORM_SKILL = ROOT / "plugins/saga/skills/brainstorm/SKILL.md"
REQUIREMENTS_SECTIONS = ROOT / "plugins/saga/skills/brainstorm/references/requirements-sections.md"
SANDBOX_SITES = ROOT / "plugins/saga/references/sandbox-spawn-sites.md"

# Declared-critical safeguards — eight total (U1 four + U2 four)
DECLARED_CRITICAL = [
    "ambiguity_stop",
    "fresh_confirmation",
    "route_gating",
    "no_deferred_save",
    "helper_ceiling",
    "map_privacy",
    "no_named_assurance_level",
    "helper_read_only",
]


def test_safeguard_drift_completeness_positive() -> None:
    assert len(DECLARED_CRITICAL) == 8
    # Meta-assertion: the case set below must cover every declared safeguard
    cases = _cases()
    case_names = {name for name, _, _, _ in cases}  # type: ignore[misc]
    assert case_names == set(DECLARED_CRITICAL), (
        f"mutation cases {case_names!r} != declared {set(DECLARED_CRITICAL)!r}"
    )


def _cases():  # type: ignore[no-untyped-def]
    """Eight (name, check_fn, file_path, needle) tuples — one per safeguard."""
    return [
        (
            "ambiguity_stop",
            cont.check_ambiguity_stop,
            BRAINSTORM_SKILL,
            "never by recency",
        ),
        (
            "fresh_confirmation",
            cont.check_revision,
            BRAINSTORM_SKILL,
            "without fresh confirmation is refused",
        ),
        (
            "route_gating",
            cont.check_artifact_free,
            BRAINSTORM_SKILL,
            "tied to declared maturity, not to file existence",
        ),
        (
            "no_deferred_save",
            cont.check_telemetry,
            BRAINSTORM_SKILL,
            "saga.py save",
        ),
        (
            "helper_ceiling",
            judg.check_helper_ceiling,
            BRAINSTORM_SKILL,
            "two helpers on the same question is one too many",
        ),
        (
            "map_privacy",
            judg.check_privacy_skill,
            BRAINSTORM_SKILL,
            "never written to the artifact",
        ),
        (
            "no_named_assurance_level",
            judg.check_no_named_tiers_rule,
            BRAINSTORM_SKILL,
            "No named tiers are used",
        ),
        (
            "helper_read_only",
            judg.check_helper_capability,
            BRAINSTORM_SKILL,
            "read-only by omission of `Edit`/`Write`/`NotebookEdit`",
        ),
    ]


def test_safeguard_drift_ambiguity_stop() -> None:
    _assert_mutation("ambiguity_stop")


def test_safeguard_drift_fresh_confirmation() -> None:
    _assert_mutation("fresh_confirmation")


def test_safeguard_drift_route_gating() -> None:
    _assert_mutation("route_gating")


def test_safeguard_drift_no_deferred_save() -> None:
    # no_deferred_save is a negative check (must be absent); mutation injects the forbidden string
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    # Unmutated must be clean
    assert cont.check_telemetry(text) == []
    # Injected must be flagged
    mutated = text + "\nsaga.py save\n"
    assert cont.check_telemetry(mutated) != []


def test_safeguard_drift_helper_ceiling() -> None:
    _assert_mutation("helper_ceiling")


def test_safeguard_drift_map_privacy() -> None:
    _assert_mutation("map_privacy")


def test_safeguard_drift_no_named_assurance_level() -> None:
    # This check is negative: injecting a level must be caught
    text = BRAINSTORM_SKILL.read_text(encoding="utf-8")
    assert judg.check_named_assurance_levels(text) == []
    mutated = text + "\nlow assurance test\n"
    assert judg.check_named_assurance_levels(mutated) != []
    assert judg.check_no_named_tiers_rule(text) == []
    mutated2 = text.replace("No named tiers are used", "")
    assert judg.check_no_named_tiers_rule(mutated2) != []


def test_safeguard_drift_helper_read_only() -> None:
    _assert_mutation("helper_read_only")


def _assert_mutation(name: str) -> None:
    cases = _cases()
    lookup: dict[str, tuple[Any, Any, Any]] = {n: (fn, p, nd) for n, fn, p, nd in cases}  # type: ignore[assignment]
    assert name in lookup, f"unknown safeguard {name!r}"
    fn, path, needle = lookup[name]  # type: ignore[assignment]
    text = path.read_text(encoding="utf-8")  # type: ignore[attr-defined, call-arg]
    # Unmutated must pass
    assert fn(text) == [], f"{name} unmutated: {fn(text)}"  # type: ignore[operator]
    # Special handling for no_deferred_save which is tested separately
    if name == "no_deferred_save":
        return
    # Deletion must fail. (No weakening probe: contradictory re-phrasings of a
    # safeguard while keeping its sentence are a semantic judgement, not
    # detectable by a string predicate — R22 as amended records this limit;
    # these cases prove only presence-plus-wiring, per the module docstring.)
    assert needle in text, f"needle {needle!r} not in {path}"
    # Remove EVERY occurrence — a safeguard stated twice (e.g. read-only by tool
    # omission for scout and verifier) is only deleted when both statements go.
    deleted = text.replace(needle, "")
    assert fn(deleted) != [], f"{name} deletion did not fail"  # type: ignore[operator]
