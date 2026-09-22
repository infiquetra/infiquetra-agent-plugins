"""The operator is the transport, the prohibition names no script, and the reference resolves.

Issue 1026 unit U6, card 931 — the Document Review half of closed issue 776, which Code Review
completed and Document Review did not.

The cross-reference case is the one that matters. Its predecessor asserted a *path string*, so it
passed while the reference was broken: the cited file existed and defined neither of the two
fields cited from it. A test that asserts a string is a test that will pass forever regardless of
the truth, so this one resolves the target and reads it.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
DOC_REVIEW = SAGA / "skills" / "doc-review" / "SKILL.md"
CODE_REVIEW = SAGA / "skills" / "code-review" / "SKILL.md"
ENGINE_REGISTRY = SAGA / "references" / "engine-registry.yaml"

#: The two scripts issue 776 retired. Neither exists; prohibiting either by name is worse than
#: saying nothing, because it implies the file could exist and protects nothing against a
#: differently-named equivalent.
RETIRED_SCRIPTS = ("engine_session_runner.py", "engine_offer.py")

#: The clause itself, matched case- and punctuation-tolerantly. Document Review and Code Review
#: state it in their own words -- issue 1026 wrote one, issue 1001's rewrite wrote the other -- and
#: what has to agree is the rule, not the sentence. Pinning one file's exact wording onto the other
#: would fail the next time either is edited for reasons that have nothing to do with transport.
TRANSPORT_CLAUSE = re.compile(r"the operator is the transport", re.IGNORECASE)

#: Each file's general prohibition, pinned by the phrase that carries the quantifier. Both forbid
#: *any* script rather than a named one; they differ in how they say so, and both are recorded here
#: so that dropping either one fails rather than silently weakening to a by-name rule.
GENERAL_PROHIBITIONS = {
    "doc-review": "prohibited whatever it is called",
    "code-review": "through any saga",
}


def test_the_retired_scripts_really_are_absent() -> None:
    """The premise of the general-prohibition rule, checked rather than assumed."""
    for name in RETIRED_SCRIPTS:
        assert not (SAGA / "scripts" / name).exists(), (
            f"{name} exists after all: the general prohibition rests on it being gone"
        )


def test_no_script_is_prohibited_by_name() -> None:
    for skill in (DOC_REVIEW, CODE_REVIEW):
        text = skill.read_text(encoding="utf-8")
        for name in RETIRED_SCRIPTS:
            assert name not in text, (
                f"{skill.name} prohibits {name} by name; the prohibition must be general, "
                "so that a differently-named equivalent is covered too"
            )


def test_both_capabilities_carry_the_operator_is_the_transport_clause() -> None:
    """Checked between the two files so the rule cannot drift out of one of them."""
    for skill in (DOC_REVIEW, CODE_REVIEW):
        assert TRANSPORT_CLAUSE.search(skill.read_text(encoding="utf-8")), (
            f"{skill.name} is missing the standalone operator-is-the-transport clause"
        )


def test_both_capabilities_state_a_prohibition_that_quantifies_over_scripts() -> None:
    """The prohibition must cover *any* script, not a list of names.

    A by-name prohibition goes stale the day the named file is deleted -- it then reads as
    satisfied whatever the code does -- and it never covered a differently-named equivalent.
    """
    for name, skill in (("doc-review", DOC_REVIEW), ("code-review", CODE_REVIEW)):
        flat = " ".join(skill.read_text(encoding="utf-8").split())
        assert GENERAL_PROHIBITIONS[name] in flat, (
            f"{skill.name} no longer states the general form of the prohibition"
        )


def test_the_registry_is_capability_metadata_and_never_launch_authority() -> None:
    for skill in (DOC_REVIEW, CODE_REVIEW):
        flat = " ".join(skill.read_text(encoding="utf-8").split())
        assert "capability metadata" in flat
        assert "launch authority" in flat


def _cross_references(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """(relative path, cited identifiers) for each backtick path the skill cites fields from."""
    found: list[tuple[str, tuple[str, ...]]] = []
    for match in re.finditer(
        r"`(external_opinion)` and\s+`(claude_adjudication)`[^.]*?`([^`]+\.md)`", text, re.DOTALL
    ):
        found.append((match.group(3), (match.group(1), match.group(2))))
    return found


def test_every_cross_reference_target_defines_what_is_cited() -> None:
    """Resolve the target file and read it. A reference to a file that does not define the
    fields cited from it is a dangling reference even though the file exists."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    for relative, identifiers in _cross_references(text):
        target = (DOC_REVIEW.parent / relative).resolve()
        assert target.is_file(), f"cross-reference target {relative} does not exist"
        body = target.read_text(encoding="utf-8")
        for identifier in identifiers:
            assert identifier in body, (
                f"{relative} is cited for {identifier!r} and does not define it — "
                "the reference resolves to a file but not to the contract"
            )


def test_the_cross_reference_check_fails_against_a_missing_target(tmp_path: Path) -> None:
    """Mutation proof for the case above: point the same check at a target that is absent and
    it must fail. Without this, a check that never sees a broken target proves nothing."""
    absent = tmp_path / "nowhere" / "findings-schema.md"
    assert not absent.is_file()
    text = (
        "Reuse the exact optional `external_opinion` and\n"
        "`claude_adjudication` contracts in `nowhere/findings-schema.md`, but keep the rest."
    )
    references = _cross_references(text)
    assert references, "the cross-reference scanner did not match its own fixture"
    relative, _ = references[0]
    assert not (tmp_path / relative).is_file()


def test_no_reviewer_dispatch_path_survives_in_document_review() -> None:
    """Issue 776 retired the external-engine dispatch; the panel section described one."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    assert "engine_resolver.resolve_role" not in text
    assert "via agy" not in text
    assert "The only representable external seat is a named" in " ".join(text.split())


def test_document_review_stays_single_pass_within_a_cycle() -> None:
    """Card 931's boundary: this unit does not change Document Review's single-pass behaviour.
    The loop issue 1026 adds is around the review, not inside it."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    assert "One cycle is one completed review result followed by one repair batch" in text
    assert "re-review within the same pass" not in text
