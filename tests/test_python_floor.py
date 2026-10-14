"""The catalog's minimum supported Python is one value, and this module holds it.

``PYTHON_FLOOR`` below is the authority. Everywhere else in this repository that
states a floor -- the continuous-integration interpreter pin, the repository
README, the pilot plan, the Fleet Core package README and changelog, the
recorded decision, and a portable skill's ``metadata.compatibility`` frontmatter -- is
checked against it here rather than maintained by hand. Before this module
existed the floor was five independently typed strings, and they had already
fallen out of agreement with the code they described: the catalog documented a
3.10 floor while the re-synchronized Fleet Core module imported
``datetime.UTC``, which needs 3.11.

The floor is a *minimum*, not a pin. Every later interpreter is in contract. The
continuous-integration job pins the exact floor version because that is the one
interpreter the contract admits that a job can usefully prove; a floor nothing
ever runs is not a floor.

Why this value: the authoritative source repository ``infiquetra-claude-plugins``
declares ``requires-python = ">=3.12"`` and pins that version across its own
continuous-integration jobs, and a derived catalog must not promise more
compatibility than the source it is derived from. The reasoning, the rejected
alternatives, and the superseded rationale are recorded in
``docs/engineering-journal/DECISIONS.md``.

Three deliberate limits on what this module can catch:

1. It reads declarations, not prose narrative. A journal entry recounting the
   floor's history is history and is left alone; only the checked declaration
   sites and the ``python>=`` version token are contract.
2. ``docs/reviews/`` is excluded from every scan. Those reviewer reports are
   immutable evidence this repository does not edit, so a finding there could
   never be acted on. ``scripts/check_repo.py`` excludes them from its
   credential scan for the same reason.
3. Blockquoted lines and fenced code blocks are exempt from the prose check,
   because preserved superseded text quotes the old floor claim verbatim and
   must keep saying what it said.

Standard library only, matching the rest of this suite.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

#: The single authority for the catalog's minimum supported Python.
#:
#: Changing this tuple is the whole edit for a floor move: every check below
#: derives from it, and each one names the file it found disagreeing. Raising it
#: is an operator decision, not a maintenance step.
PYTHON_FLOOR = (3, 12)

#: The floor as a bare version, which is what an interpreter pin carries.
PYTHON_FLOOR_VERSION = "{}.{}".format(*PYTHON_FLOOR)

#: The floor as the catalog declares it in prose and in skill frontmatter. It is
#: written as a specifier rather than as a number so that a declaration reads as
#: the minimum it is, and so that a bare "3.12" somewhere in a sentence about
#: something else is never mistaken for a contract.
PYTHON_FLOOR_SPECIFIER = "python>=" + PYTHON_FLOOR_VERSION

#: Every file that must state the floor. Presence is checked as well as value:
#: a check that only compared the declarations it found could be satisfied by
#: deleting them all, which is the "guarantee that cannot fail" shape this
#: repository has rejected before.
DECLARATION_SITES = (
    ".github/workflows/ci.yml",
    "README.md",
    "docs/engineering-journal/DECISIONS.md",
    "docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md",
    "plugins/fleet-core/README.md",
    "plugins/fleet-core/CHANGELOG.md",
    "plugins/mission-control/README.md",
    "plugins/agent-launcher/README.md",
)

#: Suffixes worth scanning for a stale floor token. Anything else in the tree is
#: not a place a floor gets written.
SCANNED_SUFFIXES = (".md", ".yml", ".yaml", ".json", ".py", ".txt", ".toml", ".cfg")

#: Directories no scan enters. ``docs/reviews`` holds immutable reviewer reports;
#: the rest are tool caches and local agent state that are not repository source.
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".claude",
        ".serena",
        ".saga",
        ".hermes",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

#: Repository-relative directory prefixes excluded from every scan.
EXCLUDED_PREFIXES = ("docs/reviews/",)

#: A version token in a declaration: ``python>=3.12`` in any spacing or case.
FLOOR_SPECIFIER = re.compile(r"python\s*>=\s*(\d+)\.(\d+)", re.IGNORECASE)

#: A GitHub Actions interpreter pin.
CI_PYTHON_VERSION = re.compile(
    r"^\s*python-version:\s*['\"]?(\d+)\.(\d+)['\"]?\s*$", re.MULTILINE
)

#: The prose form the catalog used to state its floor in, before the floor
#: became a checked value. Reintroducing it would put an unchecked number
#: alongside the checked one, which is exactly how the declarations drifted.
PROSE_FLOOR = re.compile(r"Python\s+(\d+)\.(\d+)\s+or\s+newer", re.IGNORECASE)

#: Frontmatter delimiter and key form, matching ``scripts/check_repo.py``.
FRONTMATTER_DELIMITER = "---"
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")


def scanned_files() -> list[Path]:
    """Every repository file a floor could be written into."""
    files: list[Path] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(ROOT).parts):
            continue
        if relative.startswith(EXCLUDED_PREFIXES):
            continue
        files.append(path)
    return files


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def declaring_lines(text: str) -> list[tuple[int, str]]:
    """Lines that declare something, so quoted and fenced text is skipped.

    A blockquote is preserved superseded text and a fenced block is a literal,
    and neither is the repository speaking in its own voice.
    """
    lines: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or stripped.startswith(">"):
            continue
        lines.append((number, line))
    return lines


#: A double-quoted or single-quoted scalar at the start of a value.
QUOTED_SCALAR = re.compile(r"""^(?:"([^"]*)"|'([^']*)')""")


def _frontmatter_scalar(raw: str | None) -> str:
    """The scalar a value holds: quotes removed, and any trailing comment dropped."""
    if raw is None:
        return ""
    value = raw.strip()
    quoted = QUOTED_SCALAR.match(value)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    if value.startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def read_frontmatter(text: str) -> dict[str, object] | None:
    """Top-level keys of a YAML frontmatter block, or ``None``.

    Deliberately minimal, for the same reason as ``scripts/check_repo.py``: this suite
    stays standard-library-only and Python ships no YAML parser. It reads one level
    further down than that reader does, because the floor lives under ``metadata``.

    A top-level key with a scalar value maps to that string. A top-level key with no
    value, or with only a comment after it, opens a block. The first child line under a
    block sets the indentation of its children, and only lines at exactly that
    indentation are read as children. A block whose children are dash items maps to a
    list. Lines indented deeper are never read as children, which covers the bodies of
    literal and folded scalars. A flow mapping such as ``{compatibility: ...}`` stays a
    string.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    fields: dict[str, object] = {}
    owner: str | None = None
    child_indent: int | None = None
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return fields
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            owner, child_indent = None, None
            match = FRONTMATTER_KEY.match(line)
            if match is None:
                continue
            raw = match.group(2)
            if raw is None or not raw.strip() or raw.strip().startswith("#"):
                owner = match.group(1)
                fields[owner] = {}
            else:
                fields[match.group(1)] = _frontmatter_scalar(raw)
            continue
        if owner is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        child = line.strip()
        block = fields[owner]
        if child == "-" or child.startswith("- "):
            if isinstance(block, dict) and not block:
                block = fields[owner] = []
            if isinstance(block, list):
                block.append(_frontmatter_scalar(child[1:]))
            continue
        match = FRONTMATTER_KEY.match(child)
        if match and isinstance(block, dict):
            block[match.group(1)] = _frontmatter_scalar(match.group(2))
    return None


def declared_floor_problem(text: str) -> str | None:
    """What is wrong with a skill's declared floor, or ``None`` when it is right or absent.

    A ``metadata`` that is present but is not a block mapping is refused, not read as
    declaring nothing, so a flow mapping or a sequence cannot hide a wrong floor.
    """
    fields = read_frontmatter(text) or {}
    if "metadata" not in fields:
        return None
    metadata = fields["metadata"]
    if not isinstance(metadata, dict):
        return "metadata is not a block mapping; write its keys as indented lines under it"
    declared = metadata.get("compatibility")
    if declared is not None and declared != PYTHON_FLOOR_SPECIFIER:
        return f"declares metadata.compatibility {declared!r}"
    return None


def portable_skill_documents() -> list[Path]:
    """Every portable ``SKILL.md``. Client extension directories are out of scope."""
    documents: list[Path] = []
    plugins = ROOT / "plugins"
    if not plugins.is_dir():
        return documents
    for plugin in sorted(path for path in plugins.iterdir() if path.is_dir()):
        skills = plugin / "skills"
        if not skills.is_dir():
            continue
        for skill in sorted(path for path in skills.iterdir() if path.is_dir()):
            document = skill / "SKILL.md"
            if document.is_file():
                documents.append(document)
    return documents


class PythonFloorTests(unittest.TestCase):
    def test_every_declaration_site_states_the_floor(self) -> None:
        """A site that stops declaring the floor fails, not just one that lies."""
        silent = [
            site for site in DECLARATION_SITES if PYTHON_FLOOR_SPECIFIER not in read(site)
        ]
        self.assertEqual(
            silent,
            [],
            f"these files must state the catalog floor {PYTHON_FLOOR_SPECIFIER!r} "
            f"and do not: {silent}",
        )

    def test_no_file_names_a_different_floor(self) -> None:
        """One authority. Any ``python>=`` token anywhere must be this one."""
        disagreements: list[str] = []
        for path in scanned_files():
            relative = path.relative_to(ROOT).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                for match in FLOOR_SPECIFIER.finditer(line):
                    found = (int(match.group(1)), int(match.group(2)))
                    if found != PYTHON_FLOOR:
                        disagreements.append(
                            f"{relative}:{number} declares python>="
                            f"{found[0]}.{found[1]}"
                        )
        self.assertEqual(
            disagreements,
            [],
            f"the catalog floor is {PYTHON_FLOOR_SPECIFIER}; these disagree: "
            f"{disagreements}",
        )

    def test_continuous_integration_pins_the_floor_interpreter(self) -> None:
        """The pinned interpreter is the floor, so the floor is exercised."""
        workflow = read(".github/workflows/ci.yml")
        pins = [
            (int(match.group(1)), int(match.group(2)))
            for match in CI_PYTHON_VERSION.finditer(workflow)
        ]
        self.assertTrue(
            pins,
            ".github/workflows/ci.yml pins no interpreter, so nothing exercises "
            "the declared floor",
        )
        wrong = [f"{major}.{minor}" for major, minor in pins if (major, minor) != PYTHON_FLOOR]
        self.assertEqual(
            wrong,
            [],
            f"every python-version pin must be the floor {PYTHON_FLOOR_VERSION}; "
            f"found {wrong}",
        )

    def test_the_floor_job_names_the_version_it_pins(self) -> None:
        """The step name and the pin move together, or the step name lies."""
        workflow = read(".github/workflows/ci.yml")
        self.assertIn(
            f"Set up Python {PYTHON_FLOOR_VERSION}",
            workflow,
            "the setup step's name must name the version it pins",
        )

    def test_a_portable_skill_that_declares_compatibility_declares_the_floor(self) -> None:
        """Absence is allowed; disagreement is not.

        Every portable ``SKILL.md`` is authored in this repository, because custody
        of every package moved here on 2026-09-22, so its declaration is written and
        checked here. The declaration sits under ``metadata``, the one place
        ``check_repo`` admits it, and this test reads it there.
        """
        wrong: list[str] = []
        for document in portable_skill_documents():
            problem = declared_floor_problem(document.read_text(encoding="utf-8"))
            if problem is not None:
                wrong.append(f"{document.relative_to(ROOT).as_posix()}: {problem}")
        self.assertEqual(
            wrong,
            [],
            f"a portable skill's metadata.compatibility must be {PYTHON_FLOOR_SPECIFIER!r}; "
            f"{wrong}",
        )

    def test_no_declaration_site_states_the_floor_twice_in_prose(self) -> None:
        """A prose number beside the checked token is a second, unchecked floor.

        Quoted and fenced text is exempt: preserved superseded rationale has to
        keep saying what it originally said.
        """
        strays: list[str] = []
        for site in DECLARATION_SITES:
            for number, line in declaring_lines(read(site)):
                for match in PROSE_FLOOR.finditer(line):
                    strays.append(
                        f"{site}:{number} states a floor in prose as "
                        f"Python {match.group(1)}.{match.group(2)} or newer"
                    )
        self.assertEqual(
            strays,
            [],
            "state the floor as the checked specifier "
            f"{PYTHON_FLOOR_SPECIFIER!r} rather than as a second prose number: "
            f"{strays}",
        )

    def test_the_floor_equals_the_authoritative_source_floor(self) -> None:
        """The catalog floor is the source's floor, in both directions.

        Lower promises more compatibility than the source keeps, which is the
        failure this decision removed. Higher refuses interpreters the source
        supports, and the operator ruled that a separate decision rather than a
        maintenance step. Neither is a code change on its own: the source
        repository is not checked out here and is not fetched by a test, so
        moving this constant means re-reading ``requires-python`` in
        ``infiquetra-claude-plugins`` and recording a new decision. The value
        below was read there at commit ``ed72f439``, the revision both packages
        in this catalog are derived from.
        """
        source_declared_floor = (3, 12)
        self.assertEqual(
            PYTHON_FLOOR,
            source_declared_floor,
            "the catalog floor must equal the floor the authoritative source "
            f"declares, {source_declared_floor[0]}.{source_declared_floor[1]}; "
            "moving it in either direction is an operator decision that has to "
            "re-read the source and be recorded in the engineering journal",
        )


class FloorCheckRegressionTests(unittest.TestCase):
    """The checks above have to be able to fail, or they guarantee nothing."""

    def test_specifier_pattern_catches_a_stale_token(self) -> None:
        stale = "python>=3." + str(PYTHON_FLOOR[1] - 2)
        match = FLOOR_SPECIFIER.search(f"The catalog requires {stale} today.")
        assert match is not None
        self.assertNotEqual((int(match.group(1)), int(match.group(2))), PYTHON_FLOOR)

    def test_specifier_pattern_tolerates_spacing_and_case(self) -> None:
        spaced = "Python >= {}.{}".format(*PYTHON_FLOOR)
        match = FLOOR_SPECIFIER.search(spaced)
        assert match is not None
        self.assertEqual((int(match.group(1)), int(match.group(2))), PYTHON_FLOOR)

    def test_prose_pattern_catches_a_reintroduced_prose_floor(self) -> None:
        sentence = "The portable catalog targets Python 3." + str(PYTHON_FLOOR[1] - 2)
        self.assertIsNotNone(PROSE_FLOOR.search(sentence + " or newer."))

    def test_quoted_and_fenced_lines_are_exempt_from_the_prose_check(self) -> None:
        text = "live line\n> quoted line\n```\nfenced line\n```\ntrailing line\n"
        self.assertEqual(
            [line for _, line in declaring_lines(text)],
            ["live line", "trailing line"],
        )

    def test_ci_pattern_reads_a_quoted_and_an_unquoted_pin(self) -> None:
        workflow = "          python-version: '3.12'\n      python-version: 3.9\n"
        self.assertEqual(
            [(match.group(1), match.group(2)) for match in CI_PYTHON_VERSION.finditer(workflow)],
            [("3", "12"), ("3", "9")],
        )

    def test_declaration_sites_all_exist(self) -> None:
        missing = [site for site in DECLARATION_SITES if not (ROOT / site).is_file()]
        self.assertEqual(missing, [], f"declaration sites that do not exist: {missing}")


#: A wrong floor, split across literals so the scan above does not read it as a declaration.
WRONG_FLOOR = "python" ">=" "3.10"


def frontmatter(*lines: str) -> str:
    """A skill document whose frontmatter holds ``lines`` beside a ``name`` key."""
    return "\n".join(["---", "name: example", *lines, "---", "", "# Example", ""])


class FrontmatterReaderTests(unittest.TestCase):
    """The nested reader and the floor check, each on a fixture that names one edge case."""

    def test_a_plain_nested_compatibility_is_read(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {PYTHON_FLOOR_SPECIFIER}")
        self.assertEqual(
            read_frontmatter(text),
            {"name": "example", "metadata": {"compatibility": PYTHON_FLOOR_SPECIFIER}},
        )

    def test_a_commented_metadata_header_still_opens_a_mapping(self) -> None:
        text = frontmatter(
            "metadata: # the floor is declared below",
            f"  compatibility: {PYTHON_FLOOR_SPECIFIER}",
        )
        self.assertEqual(
            read_frontmatter(text)["metadata"], {"compatibility": PYTHON_FLOOR_SPECIFIER}
        )
        self.assertIsNone(declared_floor_problem(text))

    def test_a_trailing_comment_is_not_part_of_a_nested_value(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {PYTHON_FLOOR_SPECIFIER}  # minimum")
        self.assertEqual(
            read_frontmatter(text)["metadata"], {"compatibility": PYTHON_FLOOR_SPECIFIER}
        )

    def test_a_quoted_nested_value_is_unquoted(self) -> None:
        text = frontmatter("metadata:", f'  compatibility: "{PYTHON_FLOOR_SPECIFIER}"')
        self.assertIsNone(declared_floor_problem(text))

    def test_a_flow_mapping_under_metadata_is_refused(self) -> None:
        text = frontmatter(f"metadata: {{compatibility: {PYTHON_FLOOR_SPECIFIER}}}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn("not a block mapping", problem)

    def test_a_block_sequence_under_metadata_is_refused(self) -> None:
        text = frontmatter("metadata:", f"  - compatibility: {PYTHON_FLOOR_SPECIFIER}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn("not a block mapping", problem)

    def test_a_block_scalar_sibling_does_not_overwrite_the_child(self) -> None:
        text = frontmatter(
            "metadata:",
            f"  compatibility: {PYTHON_FLOOR_SPECIFIER}",
            "  notes: |",
            f"    compatibility: {WRONG_FLOOR}",
        )
        self.assertEqual(
            read_frontmatter(text)["metadata"]["compatibility"], PYTHON_FLOOR_SPECIFIER
        )
        self.assertIsNone(declared_floor_problem(text))

    def test_a_deeper_nested_key_does_not_overwrite_the_child(self) -> None:
        text = frontmatter(
            "metadata:",
            f"  compatibility: {PYTHON_FLOOR_SPECIFIER}",
            f"    compatibility: {WRONG_FLOOR}",
        )
        self.assertIsNone(declared_floor_problem(text))

    def test_a_wrong_nested_floor_fails(self) -> None:
        text = frontmatter("metadata:", f"  compatibility: {WRONG_FLOOR}")
        problem = declared_floor_problem(text)
        self.assertIsNotNone(problem)
        self.assertIn(WRONG_FLOOR, problem)

    def test_a_wrong_floor_behind_a_commented_header_fails(self) -> None:
        text = frontmatter("metadata: # req", f"  compatibility: {WRONG_FLOOR}")
        self.assertIn(WRONG_FLOOR, declared_floor_problem(text) or "")

    def test_an_absent_declaration_passes(self) -> None:
        self.assertIsNone(
            declared_floor_problem(frontmatter("metadata:", "  when_to_use: Use it."))
        )
        self.assertIsNone(declared_floor_problem(frontmatter("license: Apache-2.0")))


if __name__ == "__main__":
    unittest.main()
