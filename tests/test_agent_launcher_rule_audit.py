"""Rule audit for the agent-launcher port (runbook Phase 2).

Three rules this port authored, audited class-first:

1. Custody classification — every upstream path at the pin carries exactly one
   classification, derived from the descriptor (the authority), never restated.
2. Documentation guards — the predicate lives in the package suite
   (``plugins/agent-launcher/tests/test_portable_docs.py``); this audit
   derives its corpus constants from that file at test time and asserts the
   guard verdict flips under every member of a mutation class corpus.
3. Mutation proof binding — the proof record in ``docs/evidence/`` must name
   the exact committed blobs it exercised, so an edit to a guarded file
   without re-running the proof fails loudly.

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import port_config  # noqa: E402

CONFIG = port_config.load("agent-launcher", ROOT)
PACKAGE = ROOT / "plugins" / "agent-launcher"
SKILL = PACKAGE / "skills" / "agent-launcher" / "SKILL.md"
README = PACKAGE / "README.md"
GUARD_SOURCE = PACKAGE / "tests" / "test_portable_docs.py"
PROOF_DOCUMENT = ROOT / "docs" / "evidence" / "2026-08-27-agent-launcher-mutation-proof-portable-docs.txt"

#: The six upstream paths at the pin (git ls-tree plugins/agent-launcher/),
#: each with the classification the port decided. Derived against, not in
#: place of, the descriptor authority.
EXPECTED_CLASSIFICATION = {
    "CHANGELOG.md": "byte_copies",
    "skills/agent-launcher/scripts/launcher.py": "byte_copies",
    "README.md": "superseded_by_target_owned",
    "skills/agent-launcher/SKILL.md": "superseded_by_target_owned",
    "tests/test_launcher_contract.py": "dropped_from_source",
    ".claude-plugin/plugin.json": "manifest_path",
}


class CustodyClassificationTest(unittest.TestCase):
    """The descriptor classifies every pinned upstream path exactly once."""

    def setUp(self) -> None:
        custody = CONFIG.custody
        self.declared = {path: "byte_copies" for path in custody.byte_copies}
        for entry in custody.entrypoint_transforms:
            self.declared[entry["path"]] = "entrypoint_transforms"
        for path in custody.client_byte_copies:
            self.declared[path] = "client_byte_copies"
        for path in custody.superseded_by_target_owned:
            self.declared[path] = "superseded_by_target_owned"
        for path in custody.dropped_from_source:
            self.declared[path] = "dropped_from_source"
        self.declared[CONFIG.source.manifest_path] = "manifest_path"

    def test_every_upstream_path_carries_exactly_one_classification(self) -> None:
        self.assertEqual(self.declared, EXPECTED_CLASSIFICATION)

    def test_no_path_is_declared_twice(self) -> None:
        classes = (
            list(CONFIG.custody.byte_copies)
            + [entry["path"] for entry in CONFIG.custody.entrypoint_transforms]
            + list(CONFIG.custody.client_byte_copies)
            + list(CONFIG.custody.superseded_by_target_owned)
            + list(CONFIG.custody.dropped_from_source)
        )
        self.assertEqual(len(classes), len(set(classes)))

    def test_the_dropped_suite_is_recorded_in_removed_from_source(self) -> None:
        provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))
        removed = {entry["source_path"] for entry in provenance["removed_from_source"]}
        self.assertIn("plugins/agent-launcher/tests/test_launcher_contract.py", removed)
        for entry in provenance["removed_from_source"]:
            self.assertTrue(entry["reason"])


def _guard_constants() -> dict[str, tuple[str, ...]]:
    """Derive the guard's corpus constants from its own source at test time.

    A test that restated the constants would keep passing when the guard's
    corpus shrank; deriving them from the guarded file means the audit and the
    guard agree on verdicts because they share one authority.
    """
    tree = ast.parse(GUARD_SOURCE.read_text(encoding="utf-8"))
    found: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in (
                "FORBIDDEN_CLAUDE_RUNTIME_PATHS",
                "STOP_CONDITION_MARKERS",
            ):
                values = [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                ]
                found[target.id] = tuple(values)
    if set(found) != {"FORBIDDEN_CLAUDE_RUNTIME_PATHS", "STOP_CONDITION_MARKERS"}:
        raise AssertionError(f"guard constants not derivable from {GUARD_SOURCE}: {sorted(found)}")
    return found


def _skill_guard_problems(text: str, constants: dict[str, tuple[str, ...]]) -> list[str]:
    """The skill guard's verdict, restated as a predicate for corpus grading."""
    problems = [f"forbidden:{marker}" for marker in constants["FORBIDDEN_CLAUDE_RUNTIME_PATHS"] if marker in text]
    problems += [f"missing:{marker}" for marker in constants["STOP_CONDITION_MARKERS"] if marker not in text]
    if "> receipt.json" not in text:
        problems.append("missing:receipt redirect")
    if "close --receipt-json receipt.json" not in text:
        problems.append("missing:receipt close form")
    if "close --tab-id <tab_id> --receipt-json <receipt.json>" in text:
        problems.append("forbidden:tab-id close form")
    if "canonical `herdr` skill" not in text or "does not ship a copy" not in text:
        problems.append("missing:herdr dependency declaration")
    return problems


def _readme_guard_problems(text: str) -> list[str]:
    problems = []
    if "Portable Agent Plugins 1.0 package" not in text:
        problems.append("missing:portable framing")
    if "Account verification applies only to `vendor claude`" not in text:
        problems.append("missing:claude-only account limitation")
    if "installed `agents` wrapper and Herdr" not in text:
        problems.append("missing:wrapper-and-herdr requirement")
    if "no vendor or model registry" not in text:
        problems.append("missing:no-registry limitation")
    return problems


class DocGuardMutationCorpusTest(unittest.TestCase):
    """Every mutation class flips the guard verdict; the committed bytes pass."""

    def setUp(self) -> None:
        self.constants = _guard_constants()
        self.skill = SKILL.read_text(encoding="utf-8")
        self.readme = README.read_text(encoding="utf-8")

    def test_the_committed_blobs_pass_every_guard(self) -> None:
        self.assertEqual(_skill_guard_problems(self.skill, self.constants), [])
        self.assertEqual(_readme_guard_problems(self.readme), [])

    def test_every_skill_mutation_class_flips_the_verdict(self) -> None:
        ladder = "~/.claude/plugins/cache/*/agent-launcher/*/skills/agent-launcher/scripts/launcher.py"
        mutations = {
            "claude cache ladder re-inserted": self.skill.replace(
                "Resolve the script from this package",
                f"Resolve the script from this package or fall back to {ladder}",
            ),
            "a stop condition removed": self.skill.replace(
                self.constants["STOP_CONDITION_MARKERS"][0], "", 1
            ),
            "receipt redirect removed": self.skill.replace("> receipt.json", "> /dev/null", 1),
            "forbidden close form re-inserted": self.skill
            + "\nclose --tab-id <tab_id> --receipt-json <receipt.json>\n",
            "herdr dependency declaration removed": self.skill.replace(
                "canonical `herdr` skill", "herdr skill"
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(mutation=name):
                self.assertNotEqual(mutated, self.skill)
                self.assertTrue(
                    _skill_guard_problems(mutated, self.constants),
                    f"guard did not fire on mutation: {name}",
                )

    def test_every_readme_mutation_class_flips_the_verdict(self) -> None:
        mutations = {
            "portable framing removed": self.readme.replace(
                "Portable Agent Plugins 1.0 package", "A package", 1
            ),
            "claude-only limitation removed": self.readme.replace(
                "Account verification applies only to `vendor claude`",
                "Account verification applies to every vendor",
                1,
            ),
            "registry limitation removed": self.readme.replace(
                "no vendor or model registry", "a vendor and model registry", 1
            ),
        }
        for name, mutated in mutations.items():
            with self.subTest(mutation=name):
                self.assertNotEqual(mutated, self.readme)
                self.assertTrue(
                    _readme_guard_problems(mutated),
                    f"guard did not fire on mutation: {name}",
                )


class MutationProofBindingTest(unittest.TestCase):
    """The published proof must name the exact committed blobs it exercised.

    Pattern: tests/test_site_profile.py MutationProofBindingTest. Edit a
    guarded file without re-running its proof and this fails, because the
    recorded digest no longer matches the committed bytes.
    """

    #: Every file the current proof grades, repository-relative. Listed here
    #: rather than derived from the document, so a proof that quietly stopped
    #: grading a file fails this test instead of shrinking in silence.
    GRADED = (
        "plugins/agent-launcher/skills/agent-launcher/SKILL.md",
        "plugins/agent-launcher/README.md",
    )

    def _recorded(self) -> dict[str, str]:
        digests: dict[str, str] = {}
        for line in PROOF_DOCUMENT.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                continue
            name, separator, value = line.partition(" sha256:")
            if separator:
                digests[name.strip()] = value.strip()
        return digests

    def test_the_proof_names_every_graded_file(self) -> None:
        self.assertEqual(set(self._recorded()), set(self.GRADED))

    def test_the_proof_names_the_bytes_that_ship(self) -> None:
        recorded = self._recorded()
        for relative in self.GRADED:
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(
                recorded[relative],
                actual,
                f"{relative} changed without its mutation proof being re-run",
            )


if __name__ == "__main__":
    unittest.main()
