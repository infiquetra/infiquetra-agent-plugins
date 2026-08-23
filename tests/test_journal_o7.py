"""O7: the matrix binding proves identity, not that the forty stages ran.

Cycle-two Ox Alpha finding F6, reconciled as consensus open item O7: matching
the recorded digest to ``plugins/unifi/`` identifies the shipped tree. It does
not prove placement, discovery, load, and invocation were actually executed
against that tree. The operator ruled this a non-blocking evidence limitation,
not a new gate.

This module reads the two journal files this unit owns the way a later session
reads them. A heading check that only asked whether the files exist would stay
green while the limitation disappeared, which is the same "guarantee that
cannot fail" defect the cycle-two review found. The claims below are the
limitation; deleting them fails the suite.

Standard library only, matching ``tests/test_unifi_readme.py``.
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEARNINGS = ROOT / "docs" / "engineering-journal" / "LEARNINGS.md"
QUEUED = ROOT / "docs" / "engineering-journal" / "QUEUED.md"

LEARNINGS_HEADING = (
    "A bound digest names the tree, not the forty stages that assessed it"
)
QUEUED_HEADING = (
    "Keep the matrix binding an identity check; do not add an execution-proof gate"
)
DIGEST_RECOMPUTE_HEADING = (
    "A digest in an evidence record proves nothing until something recomputes it"
)

# Phrases the O7 learning must carry. Each one is a claim that was absent
# from the journal before this record; the unfixed-tree run of this module
# is the proof they are not already satisfied by older entries.
LEARNINGS_CLAIMS = (
    "identity is not execution",
    "forty stages",
    "non-blocking evidence limitation",
    "not a new gate",
    "does not add a blocking check",
    "the identity check is not weakened",
    "hand-editing",
    "U11",
    "R22",
    "R43",
    "U9",
    "R40",
    "R41",
    "docs/evidence/2026-08-22-unifi-compatibility-matrix.md",
    "docs/evidence/2026-08-22-unifi-post-activation-readback.md",
    "operator-run",
)

QUEUED_CLAIMS = (
    "Recording only",
    "non-blocking evidence limitation",
    "not a new gate",
    "Do not add a blocking check",
    "Do not weaken",
    "identity is not execution",
    "U11",
    "R22",
    "R43",
    "U9",
    "R40",
    "R41",
    "docs/evidence/2026-08-22-unifi-compatibility-matrix.md",
    "docs/evidence/2026-08-22-unifi-post-activation-readback.md",
)


def markdown_h2(text: str, heading: str) -> str:
    """Return the body of an ``##`` section, excluding the heading line."""
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker) :]
    next_h2 = rest.find("\n## ")
    if next_h2 >= 0:
        rest = rest[:next_h2]
    return rest


def markdown_h3(text: str, heading: str) -> str:
    """Return the body of a ``###`` section, excluding the heading line."""
    marker = f"### {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    rest = text[start + len(marker) :]
    next_h3 = rest.find("\n### ")
    if next_h3 >= 0:
        rest = rest[:next_h3]
    return rest


def folded(text: str) -> str:
    """Collapse wrapping so a claim split across lines is still the same claim."""
    return " ".join(text.split()).casefold()


def missing_claims(text: str, claims: tuple[str, ...]) -> list[str]:
    haystack = folded(text)
    return [claim for claim in claims if folded(claim) not in haystack]


class JournalO7Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(LEARNINGS.is_file(), f"missing {LEARNINGS.relative_to(ROOT)}")
        self.assertTrue(QUEUED.is_file(), f"missing {QUEUED.relative_to(ROOT)}")
        self.learnings = LEARNINGS.read_text(encoding="utf-8")
        self.queued = QUEUED.read_text(encoding="utf-8")

    def test_learnings_records_that_identity_is_not_execution(self) -> None:
        """Ox Alpha F6 / consensus O7: the binding names the tree, not the run."""
        self.assertIn(
            f"### {LEARNINGS_HEADING}",
            self.learnings,
            "LEARNINGS.md dropped the O7 limitation heading",
        )
        section = markdown_h3(self.learnings, LEARNINGS_HEADING)
        missing = missing_claims(section, LEARNINGS_CLAIMS)
        self.assertEqual(
            missing,
            [],
            "LEARNINGS.md O7 section is missing required claims: " + ", ".join(missing),
        )

    def test_queued_records_the_limitation_without_authorizing_a_new_gate(self) -> None:
        """O7 is advisory. Maybe records it; P0-P3 must not schedule a gate."""
        for priority in ("P0", "P1", "P2", "P3"):
            with self.subTest(priority=priority):
                self.assertNotIn(
                    QUEUED_HEADING,
                    markdown_h2(self.queued, priority),
                    f"O7 was scheduled under {priority}; it is not a new gate",
                )
        maybe = markdown_h2(self.queued, "Maybe")
        self.assertIn(
            f"### {QUEUED_HEADING}",
            maybe,
            "QUEUED.md dropped the O7 recording from Maybe",
        )
        section = markdown_h3(self.queued, QUEUED_HEADING)
        missing = missing_claims(section, QUEUED_CLAIMS)
        self.assertEqual(
            missing,
            [],
            "QUEUED.md O7 section is missing required claims: " + ", ".join(missing),
        )

    def test_existing_digest_binding_learning_is_still_present(self) -> None:
        """O7 records a limitation of the binding; it does not replace the binding."""
        self.assertIn(
            f"### {DIGEST_RECOMPUTE_HEADING}",
            self.learnings,
            "O7 must not delete the learning that the matrix digest has to be recomputed",
        )

    def test_claim_checker_fails_when_the_o7_learning_is_stripped(self) -> None:
        """The regression must be able to fail: stripping O7 leaves claims missing."""
        heading_line = f"### {LEARNINGS_HEADING}"
        start = self.learnings.find(heading_line)
        if start < 0:
            stripped = self.learnings
        else:
            section = markdown_h3(self.learnings, LEARNINGS_HEADING)
            stripped = (
                self.learnings[:start]
                + self.learnings[start + len(heading_line) + len(section) :]
            )
        self.assertNotIn(heading_line, stripped)
        self.assertTrue(
            missing_claims(
                markdown_h3(stripped, LEARNINGS_HEADING),
                LEARNINGS_CLAIMS,
            ),
            "claim checker stayed green after the O7 learning was removed",
        )

    def test_claim_checker_fails_when_the_o7_queued_item_is_stripped(self) -> None:
        heading_line = f"### {QUEUED_HEADING}"
        start = self.queued.find(heading_line)
        if start < 0:
            stripped = self.queued
        else:
            section = markdown_h3(self.queued, QUEUED_HEADING)
            stripped = (
                self.queued[:start]
                + self.queued[start + len(heading_line) + len(section) :]
            )
        self.assertNotIn(heading_line, stripped)
        self.assertTrue(
            missing_claims(markdown_h3(stripped, QUEUED_HEADING), QUEUED_CLAIMS),
            "claim checker stayed green after the O7 queued record was removed",
        )


if __name__ == "__main__":
    unittest.main()
