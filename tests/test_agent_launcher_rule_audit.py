"""Rule audit for the agent-launcher package.

The 2026-09-22 import authors the package here, so the custody classification
applies only while a descriptor still carries a custody table. Documentation
guards stay: the predicate lives in
``plugins/agent-launcher/tests/test_portable_docs.py``, this audit derives
its corpus constants from that file at test time, and the mutation proof in
``docs/evidence/`` must name the exact bytes it graded.

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
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
PROOF_DOCUMENT = ROOT / "docs" / "evidence" / "2026-09-22-agent-launcher-mutation-proof-portable-docs.txt"

#: The launcher receipt must still name tab_id and then reused. The wrapper's
#: own JSON keep-list is a different list and may name pane_id.
KEEP_LIST_PATTERN = re.compile(r"receipt `tab_id`.*?`reused`", re.S)
NO_PANE_ID_SENTENCE = "There is no `pane_id` key"

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
        if CONFIG.is_authored:
            self.skipTest(
                "agent-launcher is authored here and carries no custody table or provenance manifest"
            )
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
    if "--prompt <text> > receipt.json" not in text:
        problems.append("missing:launch prompt example")
    if not KEEP_LIST_PATTERN.search(text):
        problems.append("missing:receipt keep-list")
    if NO_PANE_ID_SENTENCE not in text:
        problems.append("missing:no pane_id sentence")
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


def skill_mutations(skill: str, constants: dict[str, tuple[str, ...]]) -> dict[str, str]:
    """The skill mutation classes, in the order the proof records them.

    The on-disk campaign imports this table, so a class the proof runs and a
    class this audit grades cannot drift apart.
    """
    ladder = "~/.claude/plugins/cache/*/agent-launcher/*/skills/agent-launcher/scripts/launcher.py"
    return {
        "claude cache ladder re-inserted": skill.replace(
            "Resolve the script from this package",
            f"Resolve the script from this package or fall back to {ladder}",
        ),
        "a stop condition removed": skill.replace(constants["STOP_CONDITION_MARKERS"][0], "", 1),
        "receipt redirect removed": skill.replace("> receipt.json", "> /dev/null", 1),
        "forbidden close form re-inserted": skill
        + "\nclose --tab-id <tab_id> --receipt-json <receipt.json>\n",
        "herdr dependency declaration removed": skill.replace(
            "canonical `herdr` skill", "herdr skill"
        ),
        "launch prompt flag removed": skill.replace(
            "--prompt <text> > receipt.json", "> receipt.json", 1
        ),
        "receipt keep-list mangled": KEEP_LIST_PATTERN.sub(
            "receipt `agent` and `session`", skill, count=1
        ),
        "pane-id sentence removed": skill.replace(NO_PANE_ID_SENTENCE, "pane id", 1),
    }


def readme_mutations(readme: str) -> dict[str, str]:
    """The README mutation classes, in the order the proof records them."""
    return {
        "portable framing removed": readme.replace(
            "Portable Agent Plugins 1.0 package", "A package", 1
        ),
        "claude-only limitation removed": readme.replace(
            "Account verification applies only to `vendor claude`",
            "Account verification applies to every vendor",
            1,
        ),
        "registry limitation removed": readme.replace(
            "no vendor or model registry", "a vendor and model registry", 1
        ),
        "wrapper requirement removed": readme.replace(
            "installed `agents` wrapper and Herdr", "installed tooling", 1
        ),
    }


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
        for name, mutated in skill_mutations(self.skill, self.constants).items():
            with self.subTest(mutation=name):
                self.assertNotEqual(mutated, self.skill)
                self.assertTrue(
                    _skill_guard_problems(mutated, self.constants),
                    f"guard did not fire on mutation: {name}",
                )

    def test_every_readme_mutation_class_flips_the_verdict(self) -> None:
        for name, mutated in readme_mutations(self.readme).items():
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
