"""Structural tests for the roles library (issue 1022).

Globs ``plugins/agent-launcher/roles/*.md`` and holds every prompt to the contract the
directory's own README states: four required headings in order, four non-empty frontmatter keys,
an ``emits`` list whose entries are handoff contracts the lifecycle says this very role produces,
a ``role_id`` the lifecycle names, and no vocabulary from the retired ``team-execution`` plugin.

Three properties are worth naming because each one was got wrong first.

**Every rule is a named checker function, called by both the real test and its seeded fixture.**
A seeded fixture that re-types the production regex proves a property of ``re``, not that the rule
fires. When a checker changes, both callers change with it.

**The stop-rule check is anchored to a line start.** The README has to quote the heading it
mandates, so an unanchored substring search matches the README too and a search for files
*lacking* the heading comes back empty -- passing vacuously.

**``emits`` is checked for producership, not just membership.** Membership alone would accept
``product.md`` claiming ``run-record``. The lifecycle carries ``sender_role`` per contract, so the
test asserts the emitting role is the contract's sender of record.

**The prompts are always checked against a vendored snapshot of the lifecycle**, so the same
assertions run everywhere -- on a continuous-integration runner, which has no sibling checkout, and
on a developer machine, which does. An earlier form required the identifiers to have been read live
and was therefore green here and red on a runner, which is the worst direction for that asymmetry.
Drift between the snapshot and the lifecycle is a separate parity check that skips when no checkout
is reachable. This mirrors the pattern this repository already uses for lifecycle-generated data:
vendor a copy, pin it, and gate it, rather than checking the sibling repository out on a runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
CATALOG = pathlib.Path(__file__).resolve().parents[3]
ROLES_DIR = PACKAGE / "roles"

#: The ``infiquetra-sdlc`` revision the pinned fallbacks and the prompts' ``source:`` were taken
#: from. Asserted against every prompt, so a prompt cannot drift to another revision unnoticed.
SDLC_PIN = "5efc869f"

#: The one file exempt from the per-prompt rules, by name. The README is the directory's contract
#: document: it carries no stop rule and it is the only file allowed to name the retired plugin,
#: because it accounts for where each retired prompt went.
README_NAME = "README.md"

#: The only role allowed an empty ``emits`` list: its result is aggregated into the Review
#: Controller's contract rather than posted as its own. Keyed on the role identifier, not the
#: filename -- keying on the filename let any role become exempt by being renamed.
AGGREGATED_PROMPT = "lens-reviewer.md"
AGGREGATED_ROLE_ID = "lens_reviewer"

#: The machine-readable map, so a consumer never parses the README's Markdown table to select a
#: prompt or slice a lens section.
INDEX_NAME = "index.json"

#: The slicing rule is read from ``index.json`` rather than restated here. A consumer cuts by the
#: index; if the test cut by its own copy, the two would agree only by coincidence and the suite
#: would stay green while every lens session received a prompt nothing had checked.
LENS_INDEX = json.loads((ROLES_DIR / "index.json").read_text(encoding="utf-8"))["lens_reviewer"]
LENS_SHARED_HALF_ENDS_BEFORE = LENS_INDEX["shared_half_ends_before"]
LENS_SECTION_PREFIX = LENS_INDEX["section_heading_prefix"]
LENS_SECTION_TERMINATOR = re.compile(LENS_INDEX["section_terminator_pattern"])

#: The two roles the lifecycle licenses to reuse another role's contract. The
#: ``implementation-result`` contract's own ``sender_note`` says a repair implementer produces the
#: same contract for the batch it finishes.
REUSED_CONTRACT = "implementation-result"
REUSE_LICENSED_ROLES = ("standard_repair_implementer", "expert_repair_implementer")

REQUIRED_HEADINGS = (
    "## Role",
    "## Inputs from the run record",
    "## Output contract",
    "### Stop rule",
)

REQUIRED_FRONTMATTER_KEYS = ("role", "role_id", "emits", "source")

#: The four fields every handoff contract carries. Prompts render these as bold labels inside the
#: fenced handoff example, not as backticked identifiers, so the field-list check excludes them and
#: a separate check asserts the labels are present.
COMMON_HANDOFF_FIELDS = ("revision", "artifact_link", "assigned", "next_action")
COMMON_HANDOFF_LABELS = ("**Revision.**", "**Artifact.**", "**Assigned.**", "**Next.**")

#: The library's declared lifecycle inputs, vendored and pinned. It lives beside the prompts, not
#: under `tests/`, because it is product data: it states which roles and contracts exist, so adding
#: a role edits the library's own declaration rather than a verification fixture. Test data owning
#: product truth would make the only way to add a role a change to the thing that judges it.
#:
#: The suite checks the prompts against this file everywhere, including on a runner with no sibling
#: checkout; drift between it and the lifecycle is one explicit parity check.
SNAPSHOT_PATH = ROLES_DIR / "lifecycle-snapshot.json"
SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

#: Vocabulary the retired plugin invented, as discriminating tokens. "pass", "warn" and "blocked"
#: are deliberately absent -- they are ordinary English and would produce false failures.
FORBIDDEN_STATUS_WORDS = (
    "hard-fail",
    "soft-fail",
    "skipped-by-config",
    "skipped-by-policy",
    "team-execute",
    "appsec-audit",
    "validator-criteria",
    "review-criteria",
)

#: The lifecycle roles that get a prompt: all of them except the Human Operator, who is a person.
NON_STAFFABLE_ROLE = "operator"

#: The four lenses the roster always selects. The other eleven are conditional and, until the
#: lifecycle ships scoring fixtures for them, report findings without scoring.
ALWAYS_ON_LENSES = ("architecture-maintainability", "correctness", "security", "testing")

#: What may be a frontmatter key. A colon alone is not enough: prose inside the block that happens
#: to contain one would otherwise parse as a key.
KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

#: A strictness value from the catalogue's ladder, in any spelling. The catalogue owns the ladder;
#: a copy in a prompt would be a second source.
THRESHOLD_PATTERN = re.compile(r"\b(?:8|8\.0|8\.5|9|9\.0|9\.5|0\.8|0\.9)\b")

VENDORED_LENS_FLOORS: dict[str, str] = SNAPSHOT["lenses"]
VENDORED_LENS_IDS: tuple[str, ...] = tuple(VENDORED_LENS_FLOORS)
VENDORED_ROLE_NAMES: dict[str, str] = SNAPSHOT["roles"]
VENDORED_ROLE_IDS: tuple[str, ...] = tuple(VENDORED_ROLE_NAMES)
VENDORED_CONTRACT_SENDERS: dict[str, str] = {
    cid: row["sender_role"] for cid, row in SNAPSHOT["contracts"].items()
}
VENDORED_CONTRACT_NAMES: dict[str, str] = {
    cid: row["name"] for cid, row in SNAPSHOT["contracts"].items()
}
VENDORED_CONTRACT_FIELDS: dict[str, frozenset[str]] = {
    cid: frozenset(row["required_fields"]) for cid, row in SNAPSHOT["contracts"].items()
}
#: Per contract, the lifecycle's own one-line definition of each required field. A prompt that
#: enumerates a field's contents is checked against this rather than against a third hand copy.
VENDORED_FIELD_DESCRIPTIONS: dict[str, dict[str, str]] = {
    cid: dict(row["field_descriptions"]) for cid, row in SNAPSHOT["contracts"].items()
}


class FrontmatterError(ValueError):
    """A frontmatter block that cannot be parsed unambiguously.

    Raised rather than swallowed: a silently dropped list item turns a role that emits two
    contracts into one that appears to emit none, which every downstream check then accepts.
    """


def _sdlc_root() -> pathlib.Path | None:
    """Resolve the sibling lifecycle checkout, or None when there is not one.

    Order: the ``INFIQUETRA_SDLC_ROOT`` environment variable, then a directory named
    ``infiquetra-sdlc`` beside this repository or beside any of its ancestors.

    The ancestor walk matters in a git worktree: ``CATALOG`` is then
    ``<checkout>/.claude/worktrees/agent-XXX``, whose parent is ``worktrees/``, so looking only one
    level up finds nothing and the suite silently falls back to the pinned lists -- making the
    drift this design exists to catch invisible exactly where the gate runs.
    """
    candidates: list[pathlib.Path] = []
    from_env = os.environ.get("INFIQUETRA_SDLC_ROOT")
    if from_env:
        candidates.append(pathlib.Path(from_env))
    for ancestor in [CATALOG, *CATALOG.parents]:
        candidates.append(ancestor.parent / "infiquetra-sdlc")
    for candidate in candidates:
        if (candidate / "config" / "run-model.json").is_file():
            return candidate
    return None


def _live_lens_ids(root: pathlib.Path) -> tuple[str, ...] | None:
    path = root / "config" / "lens-catalogue.json"
    if not path.is_file():
        return None
    catalogue = json.loads(path.read_text(encoding="utf-8"))
    return tuple(lens["id"] for lens in catalogue["lenses"])


def _live_role_ids(root: pathlib.Path) -> tuple[str, ...] | None:
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    roles = model.get("roles")
    if not roles:
        return None
    return tuple(role["id"] for role in roles)


def _live_contract_senders(root: pathlib.Path) -> dict[str, str] | None:
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    contracts = model.get("contracts")
    if not contracts:
        return None
    return {contract["id"]: contract["sender_role"] for contract in contracts}


def _live_contract_names(root: pathlib.Path) -> dict[str, str] | None:
    """Per contract, the display name the lifecycle gives it."""
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    contracts = model.get("contracts")
    if not contracts:
        return None
    return {contract["id"]: contract["name"] for contract in contracts}


def _live_role_names(root: pathlib.Path) -> dict[str, str] | None:
    """Per role id, the readable name the lifecycle gives it."""
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    roles = model.get("roles")
    if not roles:
        return None
    return {role["id"]: role["name"] for role in roles}


def _live_contract_fields(root: pathlib.Path) -> dict[str, frozenset[str]] | None:
    """Per contract, the role-specific required field names.

    The four common fields are excluded: every contract carries them, and the prompts render them
    as bold labels in the handoff example rather than as backticked identifiers.
    """
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    contracts = model.get("contracts")
    if not contracts:
        return None
    return {
        contract["id"]: frozenset(
            field["name"]
            for field in contract["fields"]
            if field["status"] == "required" and field["name"] not in COMMON_HANDOFF_FIELDS
        )
        for contract in contracts
    }


def _live_field_descriptions(root: pathlib.Path) -> dict[str, dict[str, str]] | None:
    """Per contract, the lifecycle's description of each role-specific required field."""
    model = json.loads((root / "config" / "run-model.json").read_text(encoding="utf-8"))
    contracts = model.get("contracts")
    if not contracts:
        return None
    return {
        contract["id"]: {
            field["name"]: field["description"]
            for field in contract["fields"]
            if field["status"] == "required" and field["name"] not in COMMON_HANDOFF_FIELDS
        }
        for contract in contracts
    }


def _sibling_head(root: pathlib.Path) -> str | None:
    """The sibling checkout's current commit.

    Asks git rather than reading ``.git`` by hand. The hand-rolled reader returned None -- and the
    test that uses it then skipped, which is green -- whenever ``.git`` was a file rather than a
    directory (a worktree or a submodule) or the branch ref was packed. The one condition the
    revision gate exists to catch was the one it quietly declined to evaluate, and this repository
    is itself developed from a worktree.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _live_snapshot(root: pathlib.Path) -> dict | None:
    """The same shape as the vendored snapshot, read from a reachable checkout.

    Returns None when any reader fails -- a renamed key in the lifecycle's schema, or a moved
    file. That is reported as a parity failure rather than swallowed, because a per-reader
    fallback is how a check silently reverts to comparing the prompts against their own source.
    """
    lenses = _live_lens_ids(root)
    senders = _live_contract_senders(root)
    roles = _live_role_ids(root)
    fields = _live_contract_fields(root)
    names = _live_contract_names(root)
    role_names = _live_role_names(root)
    descriptions = _live_field_descriptions(root)
    if any(x is None for x in (lenses, senders, roles, fields, names, role_names, descriptions)):
        return None
    assert senders is not None and fields is not None
    assert names is not None and role_names is not None and descriptions is not None
    catalogue = json.loads((root / "config" / "lens-catalogue.json").read_text(encoding="utf-8"))
    return {
        "roles": dict(role_names),
        "contracts": {
            cid: {
                "name": names[cid],
                "sender_role": senders[cid],
                "required_fields": sorted(fields[cid]),
                "field_descriptions": dict(sorted(descriptions[cid].items())),
            }
            for cid in senders
        },
        "lenses": {x["id"]: x["floor_level"] for x in catalogue["lenses"]},
    }


#: The prompts are always checked against the vendored snapshot, so the suite asserts the same
#: things everywhere -- on a runner with no sibling checkout and on a machine with one. Drift
#: between the snapshot and the lifecycle is a separate, explicit parity check, which is the
#: pattern this repository already uses for lifecycle-generated data.
LENS_IDS = VENDORED_LENS_IDS
CONTRACT_SENDERS = VENDORED_CONTRACT_SENDERS
ROLE_IDS = VENDORED_ROLE_IDS
CONTRACT_FIELDS = VENDORED_CONTRACT_FIELDS
CONTRACT_NAMES = VENDORED_CONTRACT_NAMES
ROLE_NAMES = VENDORED_ROLE_NAMES
CONTRACT_IDS = tuple(CONTRACT_SENDERS)

#: Named in every assertion message, because a verdict that differs between a developer machine
#: and a continuous-integration runner has to say which source produced it.
ID_SOURCE = f"vendored snapshot @ {SDLC_PIN}"

ALL_ROLE_FILES: list[pathlib.Path] = sorted(ROLES_DIR.glob("*.md"))
PROMPT_FILES: list[pathlib.Path] = [p for p in ALL_ROLE_FILES if p.name != README_NAME]

#: Everything in the directory, at any depth and any extension -- used to catch a prompt hidden
#: in a subdirectory or under an extension the glob above does not see.
EVERY_FILE: list[pathlib.Path] = sorted(p for p in ROLES_DIR.rglob("*") if p.is_file())


# --- the parser -----------------------------------------------------------------------


def parse_frontmatter(path_or_text: pathlib.Path | str) -> dict[str, str | list[str]]:
    """Parse the ``---``-delimited frontmatter block into scalars and lists, strictly.

    Returns ``{}`` when the file carries no frontmatter block at all -- the absence is then
    caught by the required-key check, loudly. Inside a block, anything that is neither a
    ``key:`` line nor a list item raises, because the alternative is a silently truncated list.

    Deliberately not the scalar-only helper the agent-definition lints share: ``emits`` is a
    list, and a scalar parser reads it as an empty value.
    """
    if isinstance(path_or_text, pathlib.Path):
        text = path_or_text.read_text(encoding="utf-8")
        label = path_or_text.name
    else:
        text = path_or_text
        label = "<text>"

    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}
    block = text[4 : end + 1]

    parsed: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for lineno, raw in enumerate(block.splitlines(), start=2):
        if not raw.strip():
            continue

        stripped = raw.strip()
        if stripped.startswith("- "):
            if current_list_key is None:
                raise FrontmatterError(f"{label}:{lineno}: list item with no preceding key")
            target = parsed[current_list_key]
            assert isinstance(target, list)
            target.append(stripped[2:].strip())
            continue

        if ":" not in raw:
            raise FrontmatterError(f"{label}:{lineno}: not a key or a list item: {raw!r}")
        if raw != raw.lstrip():
            raise FrontmatterError(f"{label}:{lineno}: indented key; nesting is not supported")

        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        # A colon is not enough to make a line a key. Prose inside the block that happens to
        # contain one -- "note: see run-roles.md: the catalogue" -- otherwise became a key, and
        # nothing downstream objected because only `model` and `effort` were ever forbidden.
        if not KEY_PATTERN.fullmatch(key):
            raise FrontmatterError(f"{label}:{lineno}: not a key: {key!r}")
        if key in parsed:
            raise FrontmatterError(f"{label}:{lineno}: duplicate key {key!r}")

        if value == "[]":
            # An inline empty list. Without this it parses as the string "[]", and a role that
            # legitimately emits no contract of its own looks like a malformed scalar.
            parsed[key] = []
            current_list_key = None
        elif value:
            parsed[key] = value
            current_list_key = None
        else:
            parsed[key] = []
            current_list_key = key
    return parsed


def role_map() -> dict[str, tuple[str, str]]:
    """The README's ``## Role to file map`` table, as ``{filename: (role, role_id)}``.

    The first Markdown table after that heading, three columns: readable role name, role
    identifier, filename. A table that is not three columns raises rather than being skipped --
    skipping walks the reader on into the next table in the file and returns an unrelated map.
    """
    text = (ROLES_DIR / README_NAME).read_text(encoding="utf-8")
    _, marker, after = text.partition("## Role to file map")
    if not marker:
        raise AssertionError("the README must carry a '## Role to file map' heading")

    mapping: dict[str, tuple[str, str]] = {}
    started = False
    for line in after.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if started:
                break
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if cells[0] and set(cells[0]) <= {"-", ":"}:
            continue
        if not cells[0].strip():
            raise AssertionError(f"role map row with a blank Role cell: {cells}")
        if len(cells) != 3:
            raise AssertionError(
                f"the role map table must have exactly three columns, found {len(cells)}: {cells}"
            )
        if not started:
            if [c.lower() for c in cells] != ["role", "role_id", "file"]:
                raise AssertionError(f"unexpected role map header row: {cells}")
            started = True
            continue
        if cells[2] in mapping:
            raise AssertionError(f"duplicate role map row for {cells[2]!r}")
        mapping[cells[2]] = (cells[0], cells[1])
    if not started:
        raise AssertionError("no role map table found after the heading")
    return mapping


ROLE_MAP = role_map()


# --- the rules, each a named checker both callers use -----------------------------------


def strip_fenced_blocks(text: str) -> str:
    """Blank out fenced code blocks, keeping line count so positions stay meaningful.

    Every prompt embeds a fenced example of its handoff comment, and those examples contain
    heading-shaped lines. Without this, a heading that exists only inside an example would
    satisfy the structural check.
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        # Both fence spellings. Recognising only backticks left a heading inside a tilde-fenced
        # block counting as a real one.
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def missing_headings(text: str) -> list[str]:
    """Required headings absent, out of order, or present with nothing under them."""
    body = strip_fenced_blocks(text)
    spans: list[tuple[int, str]] = []
    missing: list[str] = []
    for heading in REQUIRED_HEADINGS:
        match = re.search(rf"^{re.escape(heading)}\s*$", body, re.MULTILINE)
        if match is None:
            missing.append(heading)
        else:
            spans.append((match.end(), heading))
    if missing:
        return missing
    if [s for s, _ in spans] != sorted(s for s, _ in spans):
        return ["<out of order>"]

    # Each section ends at the next heading of ANY level, not at the next *required* one. Bounding
    # the last required heading at end-of-file instead counted everything after it as its body --
    # so in the Lens Reviewer, where 170 lines of lens sections follow, the stop rule's body could
    # be deleted entirely and this still returned clean. The stop rule is the one thing that makes
    # an autonomous session terminate, so it was the worst possible section to leave unenforced.
    heading_starts = [m.start() for m in re.finditer(r"^#{1,6} ", body, re.MULTILINE)]

    empty: list[str] = []
    for start, heading in sorted(spans):
        following = [pos for pos in heading_starts if pos > start]
        end = following[0] if following else len(body)
        if len(body[start:end].strip()) < 40:
            empty.append(f"{heading} <empty>")
    return empty


def has_stop_rule_heading(text: str) -> bool:
    """A stop-rule *heading*, not a mention of one, and not one inside a fenced example."""
    return re.search(r"^### Stop rule\s*$", strip_fenced_blocks(text), re.MULTILINE) is not None


def retired_vocabulary(text: str) -> list[str]:
    """Names of the retired plugin or its gate-status words found in the text."""
    found = [word for word in FORBIDDEN_STATUS_WORDS if word in text]
    if "team-execution" in text:
        found.append("team-execution")
    return found


def missing_lens_sections(text: str, lens_ids: tuple[str, ...]) -> list[str]:
    """Catalogue lenses with no ``#### <lens-id>`` section."""
    return [
        lens
        for lens in lens_ids
        if re.search(rf"^#### {re.escape(lens)}\s*$", text, re.MULTILINE) is None
    ]


def emits_violations(role_id: str, emits: object, filename: str) -> list[str]:
    """Everything wrong with one prompt's ``emits``: shape, membership, producership, emptiness."""
    problems: list[str] = []
    if not isinstance(emits, list):
        return [f"emits must be a list, not {type(emits).__name__}"]
    if not emits and role_id != AGGREGATED_ROLE_ID:
        return [f"emits is empty; only {AGGREGATED_ROLE_ID} may emit nothing of its own"]
    if len(emits) != len(set(emits)):
        problems.append(f"emits repeats a contract: {emits}")
    for contract in emits:
        if contract not in CONTRACT_SENDERS:
            problems.append(f"{contract!r} is not a lifecycle handoff contract")
            continue
        sender = CONTRACT_SENDERS[contract]
        if sender == role_id:
            continue
        if contract == REUSED_CONTRACT and role_id in REUSE_LICENSED_ROLES:
            continue
        problems.append(f"{contract!r} is produced by {sender!r}, not by {role_id!r}")
    return problems


# --- the suite ------------------------------------------------------------------------


def test_roles_glob_finds_files() -> None:
    """Sanity: an empty glob would make every parametrized assertion vacuously true."""
    assert ALL_ROLE_FILES, f"no role files found under {ROLES_DIR}/*.md"
    assert PROMPT_FILES, "the roles directory holds a README but no role prompts"


def test_role_map_is_populated() -> None:
    """The README's map is the expected-set source; an unparsed table would disable the suite."""
    assert len(ROLE_MAP) >= 14, f"expected at least 14 mapped roles, parsed {len(ROLE_MAP)}"


def test_card_acceptance_prompt_count() -> None:
    """The card's floor, counted as the card means it: role prompts beside the README.

    Counted on ``PROMPT_FILES``, not on every file in the directory: the README is one of the
    files, so a floor of fourteen over the whole directory would still hold after a prompt was
    deleted.
    """
    assert len(PROMPT_FILES) >= 14


def test_map_and_files_agree_exactly() -> None:
    """Set equality in both directions, so neither an orphan file nor an orphan row survives."""
    assert {p.name for p in PROMPT_FILES} == set(ROLE_MAP), (
        f"role map {sorted(ROLE_MAP)} disagrees with files {sorted(p.name for p in PROMPT_FILES)}"
    )


def test_prompts_cover_every_staffable_lifecycle_role() -> None:
    """R7's first clause, and its converse: exactly the staffable roles, no more and no fewer.

    This is what stops a file the lifecycle does not name -- a scanner, a validator, a monitor --
    from passing by reusing a legitimate role identifier: the identifiers must be distinct and
    must cover the staffable set exactly.
    """
    declared = [parse_frontmatter(p)["role_id"] for p in PROMPT_FILES]
    assert len(declared) == len(set(declared)), f"duplicate role_id among prompts: {declared}"
    expected = {r for r in ROLE_IDS if r != NON_STAFFABLE_ROLE}
    assert set(declared) == expected, (
        f"prompts cover {sorted(set(declared))}, lifecycle staffable roles are {sorted(expected)}"
        f" (ids from {ID_SOURCE})"
    )


def test_roles_directory_holds_nothing_unexpected() -> None:
    """R7's second clause: no prompt hidden in a subdirectory or under another extension."""
    unexpected = sorted(str(p.relative_to(ROLES_DIR)) for p in EVERY_FILE if p.parent != ROLES_DIR)
    assert not unexpected, f"files nested below the roles directory: {unexpected}"
    allowed_data = {INDEX_NAME, SNAPSHOT_PATH.name}
    wrong_extension = sorted(
        p.name for p in EVERY_FILE if p.suffix != ".md" and p.name not in allowed_data
    )
    assert not wrong_extension, f"unexpected files in the roles directory: {wrong_extension}"


def test_index_agrees_with_the_files_and_the_readme() -> None:
    """The machine-readable map is the same map, so a helper never parses Markdown to select.

    A consumer that had to parse the README's table would be rewriting, in its own language, the
    bespoke pipe-splitter this test already needed. The index exists so it does not have to; this
    check is what stops the two drifting.
    """
    index = json.loads((ROLES_DIR / INDEX_NAME).read_text(encoding="utf-8"))
    assert index["schema"] == "roles_index.v1"
    assert index["sdlc_revision"] == SDLC_PIN

    by_file = {row["file"]: row for row in index["roles"]}
    assert set(by_file) == {p.name for p in PROMPT_FILES}, "index files disagree with the directory"
    assert set(by_file) == set(ROLE_MAP), "index files disagree with the README's map"
    for name, row in by_file.items():
        assert (row["role"], row["role_id"]) == ROLE_MAP[name], (
            f"index row for {name} disagrees with the README's map"
        )
        frontmatter = parse_frontmatter(ROLES_DIR / name)
        assert row["role_id"] == frontmatter["role_id"]
        assert row["emits"] == frontmatter["emits"]

    lens = index["lens_reviewer"]
    assert lens["lens_ids"] == list(LENS_IDS), "index lens ids disagree with the catalogue"
    assert lens["file"] == AGGREGATED_PROMPT

    # The slicing rule the index publishes must be the one this suite validates slices with.
    # Otherwise a consumer cuts by the index, the tests cut by their own copy, the two agree only
    # by coincidence, and changing either leaves the suite green over a prompt nothing checked.
    assert lens["shared_half_ends_before"] == LENS_SHARED_HALF_ENDS_BEFORE
    assert lens["section_heading_prefix"] == LENS_SECTION_PREFIX
    assert lens["section_terminator_pattern"] == LENS_SECTION_TERMINATOR.pattern


def test_release_surfaces_agree_and_advanced() -> None:
    """R9: the three release surfaces tell one story, and it is past the version before this."""
    manifest = json.loads(
        (PACKAGE / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    version = manifest["version"]
    marketplace = json.loads(
        (CATALOG / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entry = next(p for p in marketplace["plugins"] if p["name"] == "agent-launcher")
    assert entry["version"] == version, (
        f"marketplace says {entry['version']}, manifest says {version}"
    )
    changelog = (PACKAGE / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    assert re.search(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M
    ), f"CHANGELOG has no dated heading for {version}"
    assert tuple(int(p) for p in version.split(".")) > (1, 5, 2), (
        f"agent-launcher {version} does not advance past the version this work started from"
    )


def test_readme_accounts_for_every_retired_prompt_group() -> None:
    """R10: the accounting names each retired group and its destination, not just the plugin."""
    text = (ROLES_DIR / README_NAME).read_text(encoding="utf-8")
    for token in ("Reviewers", "Testers", "Scanners", "Monitors", "deploy watcher"):
        assert token in text, f"the README's retired-prompt accounting omits {token!r}"
    counted = [int(n) for n in re.findall(r"^\| [^|]+ \| (\d+) \|", text, re.MULTILINE)]
    assert sum(counted) == 25, (
        f"the retired-prompt accounting sums to {sum(counted)}, not the 25 prompts that existed"
    )


def test_every_contract_has_a_producing_prompt() -> None:
    """Consumer completeness in the other direction: no lifecycle contract is unowned."""
    claimed: set[str] = set()
    for path in PROMPT_FILES:
        emits = parse_frontmatter(path).get("emits", [])
        if isinstance(emits, list):
            claimed.update(emits)
    unowned = sorted(set(CONTRACT_SENDERS) - claimed)
    assert not unowned, f"lifecycle contracts no prompt produces: {unowned}"


def test_readme_carries_no_stop_rule_heading() -> None:
    """The README's exemption, asserted positively rather than read off an empty result."""
    assert not has_stop_rule_heading((ROLES_DIR / README_NAME).read_text(encoding="utf-8"))


def test_readme_may_name_the_retired_plugin() -> None:
    """The README's other exemption: it accounts for where the retired prompts went."""
    assert "team-execution" in (ROLES_DIR / README_NAME).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_has_required_headings(path: pathlib.Path) -> None:
    problems = missing_headings(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.name}: heading problems: {problems}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_has_stop_rule_heading(path: pathlib.Path) -> None:
    assert has_stop_rule_heading(path.read_text(encoding="utf-8")), (
        f"{path.name}: no '### Stop rule' heading at a line start"
    )


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_frontmatter(path: pathlib.Path) -> None:
    """Four non-empty keys, a lifecycle role id, and an ``emits`` this role really produces."""
    frontmatter = parse_frontmatter(path)
    for key in REQUIRED_FRONTMATTER_KEYS:
        assert key in frontmatter, f"{path.name}: missing frontmatter key {key!r}"
    for key in ("role", "role_id", "source"):
        assert frontmatter[key], f"{path.name}: frontmatter key {key!r} is empty"

    role_id = frontmatter["role_id"]
    assert isinstance(role_id, str)
    assert role_id in ROLE_IDS, f"{path.name}: role_id {role_id!r} is not a lifecycle role"

    mapped = ROLE_MAP.get(path.name)
    assert mapped is not None, f"{path.name} is not in the README's role map"
    assert mapped[1] == role_id, (
        f"{path.name}: role_id {role_id!r} disagrees with the README's map ({mapped[1]!r})"
    )

    problems = emits_violations(role_id, frontmatter["emits"], path.name)
    assert not problems, f"{path.name}: {problems}"


def test_every_revision_written_in_the_directory_is_the_pin() -> None:
    """No prose mention of a lifecycle revision may drift from the pin.

    The pin is written in twenty places. The frontmatter, the index and the snapshot were each
    gated; four prose mentions were not, and the worst of them is the revision every prompt's
    ladder tells a session to read at -- `git show <pin>:<path>`. On the next bump the mechanical
    copies move and a stale instruction stays behind, telling a session to read the wrong revision.
    """
    pattern = re.compile(r"\b[0-9a-f]{8}\b")
    stale: dict[str, set[str]] = {}
    for path in [*PROMPT_FILES, ROLES_DIR / README_NAME, ROLES_DIR / INDEX_NAME]:
        found = {
            token
            for token in pattern.findall(path.read_text(encoding="utf-8"))
            if token != SDLC_PIN and not token.isdigit()
        }
        if found:
            stale[path.name] = found
    assert not stale, f"revisions other than the pin {SDLC_PIN} appear in: {stale}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_source_names_the_pinned_revision(path: pathlib.Path) -> None:
    """A prompt cannot quietly claim a different lifecycle revision than the README does."""
    source = parse_frontmatter(path)["source"]
    assert isinstance(source, str)
    assert SDLC_PIN in source, f"{path.name}: source {source!r} does not name {SDLC_PIN}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_carries_no_retired_vocabulary(path: pathlib.Path) -> None:
    found = retired_vocabulary(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name} uses retired vocabulary: {found}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_declares_no_tier(path: pathlib.Path) -> None:
    """Staffing is decided elsewhere; a tier here would be a second source for one decision."""
    frontmatter = parse_frontmatter(path)
    assert frontmatter, f"{path.name}: no frontmatter block, so this check would be vacuous"
    assert "model" not in frontmatter, f"{path.name} declares a model"
    assert "effort" not in frontmatter, f"{path.name} declares an effort"


def test_vendored_snapshot_is_stamped_with_the_pin() -> None:
    """The snapshot says which revision it was taken from, and it is the one everything else names."""
    assert SNAPSHOT["schema"] == "lifecycle_snapshot.v1"
    assert SNAPSHOT["sdlc_revision"] == SDLC_PIN, (
        f"{SNAPSHOT_PATH.name} was taken from {SNAPSHOT['sdlc_revision']}, the prompts name"
        f" {SDLC_PIN}"
    )
    assert SNAPSHOT["roles"] and SNAPSHOT["contracts"] and SNAPSHOT["lenses"], (
        "an empty snapshot would make every check against it vacuous"
    )

    # Bound to something upstream, so the snapshot is not a free-floating assertion about itself.
    assert SNAPSHOT["source_repo"] == "https://github.com/infiquetra/infiquetra-sdlc"
    index = json.loads((ROLES_DIR / INDEX_NAME).read_text(encoding="utf-8"))
    assert index["sdlc_revision"] == SNAPSHOT["sdlc_revision"], (
        "the roles index and the vendored snapshot name different lifecycle revisions"
    )

    # Tamper-evidence, not integrity: this catches an edit that forgets to update the digest, and
    # it does not catch one that updates both -- the algorithm is right here. What makes the data
    # trustworthy is the parity check below, run wherever the lifecycle is reachable; this only
    # stops a careless edit from passing quietly in the places that check cannot run.
    payload = json.dumps(
        {k: SNAPSHOT[k] for k in ("roles", "contracts", "lenses")},
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert SNAPSHOT["content_sha256"] == digest, (
        f"{SNAPSHOT_PATH.name} was edited by hand: its content hash says"
        f" {SNAPSHOT['content_sha256'][:12]}, its contents hash to {digest[:12]}. Regenerate it"
        " from the lifecycle rather than editing it."
    )


def test_vendored_snapshot_matches_the_live_lifecycle() -> None:
    """The parity gate: vendored data against the lifecycle, wherever the lifecycle is reachable.

    This repository already vendors lifecycle-generated data and gates it with a pinned parity
    check rather than checking the sibling repository out on a runner. The prompts are therefore
    always checked against the snapshot -- the same assertions run in continuous integration and on
    a developer machine -- and drift between the snapshot and the lifecycle is caught here instead.

    Skipping when no checkout is reachable is correct and is not a hole: the snapshot is pinned
    data, so a run without the sibling still checks the prompts against a fixed, reviewed source.
    What it cannot do is notice that the source moved, which is what this test is for.
    """
    root = _sdlc_root()
    if root is None:
        pytest.skip("no sibling infiquetra-sdlc checkout reachable; parity not checkable here")

    head = _sibling_head(root)
    assert head is not None, (
        f"a checkout resolved at {root} but its HEAD could not be read; that is a failure, not a"
        " skip -- parity would otherwise be claimed against a revision nobody identified"
    )
    assert head.startswith(SDLC_PIN), (
        f"the checkout is at {head[:12]} and the snapshot is pinned at {SDLC_PIN}; regenerate the"
        " snapshot and re-pin the prompts together, or check the sibling out at the pin"
    )

    live = _live_snapshot(root)
    assert live is not None, (
        f"the lifecycle at {root} no longer exposes the keys this snapshot was built from; the"
        " schema moved, and the snapshot must be regenerated against the new shape"
    )

    for section in ("roles", "contracts", "lenses"):
        assert live[section] == SNAPSHOT[section], (
            f"vendored {section} differ from the lifecycle at {head[:12]};"
            f" regenerate {SNAPSHOT_PATH.name} and re-check the prompts against it"
        )


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_names_every_required_contract_field(path: pathlib.Path) -> None:
    """The largest transcription from the lifecycle, and the one nothing used to check.

    Each prompt restates its contract's required field names so a fresh session can produce a
    complete handoff. That is a copy of lifecycle-owned data, and the README's promise that the
    lifecycle wins where the two disagree is unenforceable unless something can tell they disagree.
    """
    frontmatter = parse_frontmatter(path)
    emits = frontmatter["emits"]
    assert isinstance(emits, list)
    if not emits:
        pytest.skip(f"{path.name} emits no contract of its own")

    required: set[str] = set()
    for contract in emits:
        fields = CONTRACT_FIELDS[contract]
        # An empty required set would make this check pass for every prompt while proving nothing.
        # The lifecycle spelling its status field differently is all it would take.
        assert fields, (
            f"the lifecycle reports no required fields for {contract!r}; the transcription check"
            " would be vacuous, so this is a failure rather than a pass"
        )
        required |= set(fields)

    # Scoped to the output-contract section, not the whole file, and anchored so the bounds cannot
    # be found inside a fenced example or a cross-reference. Over the whole file any backticked
    # snake_case token satisfied the check -- including one appearing only in a prohibition or a
    # rationale, and including the `stop_condition` every prompt mentions in its stop rule. A
    # mis-found bound can only widen the window, and a wider window can only make this greener.
    body = strip_fenced_blocks(path.read_text(encoding="utf-8"))
    opened = re.search(r"^## Output contract\s*$", body, re.MULTILINE)
    closed = re.search(r"^### Stop rule\s*$", body, re.MULTILINE)
    assert opened is not None and closed is not None, f"{path.name}: cannot bound output contract"
    named = set(re.findall(r"`([a-z][a-z0-9_]{3,})`", body[opened.end() : closed.start()]))

    missing = sorted(required - named)
    assert not missing, (
        f"{path.name} does not name required fields {missing} in its output-contract section"
    )


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_role_name_matches_the_lifecycle(path: pathlib.Path) -> None:
    """The ``role`` value is the lifecycle's readable name, compared without regard to case.

    Case is deliberately ignored because the lifecycle disagrees with itself: its run model spells
    eight of the fifteen in sentence case, its role catalogue in Title Case. These files follow the
    catalogue; the check is that the *words* match, not the capitalisation.
    """
    frontmatter = parse_frontmatter(path)
    role, role_id = frontmatter["role"], frontmatter["role_id"]
    assert isinstance(role, str) and isinstance(role_id, str)
    assert role.lower() == ROLE_NAMES[role_id].lower(), (
        f"{path.name}: role {role!r} is not the lifecycle's name for {role_id!r}"
        f" ({ROLE_NAMES[role_id]!r})"
    )


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_names_every_contract_it_emits(path: pathlib.Path) -> None:
    """Each emitted contract gets a header line carrying the lifecycle's name for it.

    A prompt that lists a contract's fields but never its name leaves a session unable to write a
    valid header, which is a malformed handoff -- and the prompt is the whole of its briefing.
    """
    emits = parse_frontmatter(path)["emits"]
    assert isinstance(emits, list)
    if not emits:
        pytest.skip(f"{path.name} posts no handoff comment of its own")
    text = path.read_text(encoding="utf-8")
    for contract in emits:
        expected = f"### Handoff: {CONTRACT_NAMES[contract]} ({contract})"
        assert expected in text, f"{path.name} never writes the header line {expected!r}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_prompt_shows_the_handoff_comment_shape(path: pathlib.Path) -> None:
    """The four common labels and the contract-naming header, in every emitting prompt.

    Shared boilerplate copied fourteen times with nothing holding it together is the drift this
    library exists to undo; the journal rejected copying the presentation preamble for exactly this
    reason, so the same reasoning has to bind the handoff block.
    """
    frontmatter = parse_frontmatter(path)
    emits = frontmatter["emits"]
    assert isinstance(emits, list)
    if not emits:
        pytest.skip(f"{path.name} posts no handoff comment of its own")

    # Per handoff block, not per file. A single well-formed example anywhere used to satisfy this,
    # so four of the Delivery Manager's five handoffs could have omitted every common field and the
    # suite stayed green -- while a session posting one without `next_action` is exactly the
    # malformed handoff this library exists to prevent.
    text = path.read_text(encoding="utf-8")
    headers = list(re.finditer(r"^### Handoff: .+ \([a-z-]+\)$", text, re.MULTILINE))
    assert len(headers) == len(emits), (
        f"{path.name} emits {len(emits)} contracts but shows {len(headers)} handoff headers"
    )
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[header.start() : end]
        for label in COMMON_HANDOFF_LABELS:
            assert label in block, (
                f"{path.name}: the handoff block {header.group(0)!r} omits {label}"
            )


def test_lens_reviewer_covers_every_catalogue_lens() -> None:
    text = (ROLES_DIR / AGGREGATED_PROMPT).read_text(encoding="utf-8")
    assert LENS_IDS, "the lens id list is empty, which would make this check vacuous"
    missing = missing_lens_sections(text, LENS_IDS)
    assert not missing, f"{AGGREGATED_PROMPT} has no section for: {missing}"


def lens_slice(lens_id: str) -> str:
    """Rebuild what a consumer actually sends for one lens: shared half plus one section.

    This is the artifact that matters. Checking the file as a whole hid a real defect: the block
    between ``# The lenses`` and the first grouping heading was in neither piece, so the permission
    for a conditional lens to report without scoring was dropped at the cut, leaving eleven of
    fifteen sessions with a stop rule demanding a score and no way to satisfy it.
    """
    text = (ROLES_DIR / AGGREGATED_PROMPT).read_text(encoding="utf-8")
    lines = text.splitlines()

    # Line-anchored, like the other two rules. An unanchored substring search would match the
    # phrase quoted anywhere earlier in the shared half and silently shorten it -- and a shared
    # half truncated after the stop rule still satisfies every heading check.
    cut = next(
        (i for i, line in enumerate(lines) if line.strip() == LENS_SHARED_HALF_ENDS_BEFORE), None
    )
    assert cut is not None, f"no {LENS_SHARED_HALF_ENDS_BEFORE!r} line to cut the shared half at"
    shared = "\n".join(lines[:cut]).rstrip("\n")

    heading = f"{LENS_SECTION_PREFIX}{lens_id}"
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    assert start is not None, f"no section for {lens_id}"

    # The terminator scan runs over fence-stripped lines, so a heading-shaped line inside a fenced
    # example cannot end a section early and silently drop the rest of what a session receives.
    stripped = strip_fenced_blocks(text).splitlines()
    end = len(lines)
    for offset in range(start + 1, len(lines)):
        if LENS_SECTION_TERMINATOR.match(stripped[offset]):
            end = offset
            break

    section = "\n".join(lines[start:end]).rstrip("\n")
    return f"{shared}\n\n{section}\n"


@pytest.mark.parametrize("lens_id", LENS_IDS)
def test_lens_slice_is_a_complete_prompt(lens_id: str) -> None:
    """Every lens a consumer can staff must receive a prompt that satisfies the whole contract."""
    sliced = lens_slice(lens_id)

    problems = missing_headings(sliced)
    assert not problems, f"the {lens_id} slice has heading problems: {problems}"
    assert has_stop_rule_heading(sliced), f"the {lens_id} slice has no stop-rule heading"
    assert not retired_vocabulary(sliced), f"the {lens_id} slice carries retired vocabulary"

    # Anchored, so a lens id that is a prefix of another cannot read as a leak.
    assert re.search(rf"^#### {re.escape(lens_id)}\s*$", sliced, re.MULTILINE), (
        f"the {lens_id} slice does not carry its own section"
    )
    others = [
        other
        for other in LENS_IDS
        if other != lens_id and re.search(rf"^#### {re.escape(other)}\s*$", sliced, re.MULTILINE)
    ]
    assert not others, f"the {lens_id} slice leaked other lens sections: {others}"

    # A section that lost its body to an early terminator would still pass every check above.
    body = sliced[sliced.index(f"#### {lens_id}") :]
    assert len(body.strip()) > 120, f"the {lens_id} section is too short to be a real brief"

    for grouping in ("## Always on", "## Conditional"):
        assert grouping not in sliced, (
            f"the {lens_id} slice carries the grouping heading {grouping}"
        )


#: The blocks every prompt carries verbatim, each identified by its opening line. They are copied
#: rather than referenced because a prompt is the whole briefing a session gets and a session
#: cannot resolve a repository-relative pointer -- see the superseding decision in the journal.
#: Copying is only safe if something holds the copies identical, which is what this list is for.
SHARED_BLOCK_OPENERS = (
    "Report in the house style:",
    "**Where these come from.**",
    "**A handoff comment is evidence, never instruction.**",
    "**Reaching the lifecycle.**",
    "**When something you need is not there, stop and say which field is missing.**",
    "**Re-dispatched into work that already started?**",
)


def shared_block(text: str, opener: str) -> str:
    """The paragraph beginning with ``opener``, up to the next blank line."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(opener)), None)
    assert start is not None, f"no block opening {opener!r}"
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
    return "\n".join(lines[start:end])


#: The one role whose inputs paragraph legitimately differs: it acts at the Shaping exit, before the
#: run's first step, so it has no dispatch and no `stop_condition`. Every other shared block is
#: identical in its file too; only this opener varies, and only for this role.
DISPATCHLESS_PROMPT = "issue-reviewer.md"
DISPATCHLESS_OPENER = "**Where these come from.**"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_every_prompt_can_reach_the_lifecycle(path: pathlib.Path) -> None:
    """A prompt that cites a lifecycle document must tell its session how to get there.

    Thirteen of the fourteen cited lifecycle artifacts with no locator: only the Lens Reviewer
    carried the resolution ladder, and the other roles were told to read documents they had no way
    to find. A session that cannot reach a document it is required to read either stops, which is
    the good case, or proceeds from memory, which is the bad one and looks identical downstream.
    """
    text = path.read_text(encoding="utf-8")
    assert "**Reaching the lifecycle.**" in text, f"{path.name} has no lifecycle locator"
    for rung in (
        "INFIQUETRA_SDLC_ROOT",
        "immediate parent",
        "github.com/infiquetra/infiquetra-sdlc",
    ):
        assert rung in text, f"{path.name}'s locator omits the rung naming {rung!r}"
    assert SDLC_PIN in text.split("**Reaching the lifecycle.**", 1)[1], (
        f"{path.name}'s locator does not pin the revision"
    )


def ladder_defects(text: str) -> list[str]:
    """Why a prompt's lifecycle ladder would stop a session that could have read the pin.

    The first form required the resolved checkout's ``HEAD`` to start with the pin and ordered a
    stop otherwise. A clone -- including the ladder's own last rung -- lands on the default branch,
    not on a detached pin, so the rule held only while the lifecycle's ``main`` happened to sit at
    the pin, and the first merge there would have stopped all fourteen prompts. The repaired ladder
    reads at the pin with ``git show <pin>:<path>``, which works from any ``HEAD`` and fails only
    when the object is absent; the stop is reserved for that case.
    """
    block = shared_block(text, "**Reaching the lifecycle.**")
    defects: list[str] = []
    if f"show {SDLC_PIN}:" not in block:
        defects.append(f"does not read at the pin with `git show {SDLC_PIN}:<path>`")
    if "fetch origin" not in block:
        defects.append("does not fetch once before declaring the pin unreachable")
    for phrase in ("must start with", "rev-parse HEAD"):
        if phrase in text:
            defects.append(f"still requires HEAD to be at the pin ({phrase!r})")
    return defects


@pytest.mark.parametrize("path", PROMPT_FILES, ids=[p.name for p in PROMPT_FILES])
def test_the_ladder_reads_at_the_pin_rather_than_requiring_head_there(path: pathlib.Path) -> None:
    defects = ladder_defects(path.read_text(encoding="utf-8"))
    assert not defects, f"{path.name}'s lifecycle ladder: " + "; ".join(defects)


def test_seeded_head_pinned_ladder_fires() -> None:
    seeded = (
        "**Reaching the lifecycle.** Find that checkout in this order: `INFIQUETRA_SDLC_ROOT`;"
        " the immediate parent. Whatever rung resolves, verify the revision before reading"
        f" anything from it: its `HEAD` must start with `{SDLC_PIN}`. A checkout at another"
        " revision is unusable -- treat it as unreachable and stop.\n"
    )
    defects = ladder_defects(seeded)
    assert any("must start with" in d for d in defects)
    assert any("show" in d for d in defects)
    repaired = (
        f"**Reaching the lifecycle.** Read each document at the pin: `git -C <checkout> show"
        f" {SDLC_PIN}:<path>`. If that fails, run `git -C <checkout> fetch origin` once and try"
        " again; stop only if it still fails.\n"
    )
    assert ladder_defects(repaired) == []


def test_implementer_does_not_invent_a_source_for_the_preview_declaration() -> None:
    """The lifecycle says a preview criterion applies where a repository declares one, and stops.

    It does not say where a repository declares it, nor which field of the implementation result
    carries the preview results. An earlier repair filled both gaps with plausible sentences --
    a dispatch field the contract does not have, and a result field the lifecycle defines as
    something else -- which is the exact class of invention every prompt forbids its session.
    """
    text = (ROLES_DIR / "implementer.md").read_text(encoding="utf-8")
    assert "Your dispatch names whether" not in text, "the dispatch contract has no such field"
    assert "ride in `unit_and_child_check_results`" not in text, (
        "the lifecycle defines that field as the unit's own and child-scoped checks"
    )
    stop_rule = text.split("### Stop rule", 1)[1]
    assert "no declared source" in stop_rule, (
        "the preview paragraph must say the lifecycle names no source, not supply one"
    )


def test_functional_tester_names_one_set_of_terminal_states() -> None:
    """Two sections, one field, one instruction.

    The output contract once told the session to record a scenario it could not run as "not run"
    while the stop rule said that is not a state it may hand back. The lifecycle's three terminal
    states are passed, failed, and blocked with a cause; both sections name exactly those.
    """
    text = strip_fenced_blocks((ROLES_DIR / "functional-tester.md").read_text(encoding="utf-8"))
    contract = text.split("## Output contract", 1)[1].split("### Stop rule", 1)[0]
    stop_rule = text.split("### Stop rule", 1)[1]
    for state in ("`passed`", "`failed`", "`blocked`"):
        assert state in contract, f"output contract does not name {state}"
        assert state in stop_rule, f"stop rule does not name {state}"
    # The state forms only: the prose may still say a scenario "could not run" when explaining why
    # it is `blocked`, which is the instruction, not the defect.
    for state_form in ('"Not run"', '"not run"', "as not run", "`not run`", "`not-run`"):
        assert state_form not in contract, (
            f"the output contract hands back {state_form}, a state the stop rule forbids"
        )


def test_plan_reviewer_points_at_the_document_that_holds_the_questions() -> None:
    """The checklist and the run-model questions live in `docs/reviewers/plan-review.md`.

    The two documents the prompt used to name both disclaim holding them: one says in terms that it
    states one layer and not the whole checklist, the other lists four questions where the contract
    requires three and defers to the reviewers page for the assembled list.
    """
    text = (ROLES_DIR / "plan-reviewer.md").read_text(encoding="utf-8")
    contract = text.split("## Output contract", 1)[1].split("### Stop rule", 1)[0]
    assert "docs/reviewers/plan-review.md" in contract
    for heading in ('"What to check"', '"What the run model adds"'):
        assert heading in contract, f"the pointer does not quote the heading {heading}"
    assert (
        "in `docs/process/planning-readiness.md` and `docs/lifecycle/run-model.md`" not in contract
    ), "the prompt still sends the reader to the two documents that disclaim the content"


#: Prompts that enumerate what a required field carries, and the field they enumerate. Each is
#: checked item by item against the lifecycle's own definition of that field, vendored in the
#: snapshot and held to the live lifecycle by the parity test.
ENUMERATED_FIELDS = (
    ("planner.md", "planner-to-orchestrator", "preflight_results"),
    ("review-controller.md", "code-review-result", "per_lens_results"),
)


def enumerated_items(description: str) -> list[str]:
    """The items a lifecycle field description lists after its colon, one per entry.

    ``"For each X: a, b, and c. More."`` gives ``["a", "b", "c"]``. The first sentence after the
    colon is the enumeration; a trailing sentence is commentary and is not an item.
    """
    _, _, rest = description.partition(": ")
    first_sentence = rest.split(". ", 1)[0].rstrip(".")
    items = [item.strip() for item in first_sentence.split(", ")]
    return [item[4:] if item.startswith("and ") else item for item in items if item]


@pytest.mark.parametrize(("filename", "contract", "field"), ENUMERATED_FIELDS)
def test_enumerated_field_items_match_the_lifecycle(
    filename: str, contract: str, field: str
) -> None:
    """A wrong enumeration is worse than none: it is a confidently malformed contract."""
    description = VENDORED_FIELD_DESCRIPTIONS[contract][field]
    items = enumerated_items(description)
    assert len(items) >= 4, f"{contract}.{field} does not read as an enumeration: {description!r}"
    text = strip_fenced_blocks((ROLES_DIR / filename).read_text(encoding="utf-8"))
    # Whitespace-normalised: the prose wraps at a hundred columns, and an item may break across a line.
    section = " ".join(text.split("## Output contract", 1)[1].split("### Stop rule", 1)[0].split())
    missing = [item for item in items if item not in section]
    assert not missing, (
        f"{filename} enumerates `{field}` without {missing}; the lifecycle lists {items}"
    )


def test_seeded_enumeration_splitter() -> None:
    assert enumerated_items("One row per check: the check, the time, and the outcome. Extra.") == [
        "the check",
        "the time",
        "the outcome",
    ]
    assert enumerated_items("No colon here") == []


def test_changelog_names_the_pin() -> None:
    """The release note says which lifecycle revision the prompts were written against."""
    changelog = (PACKAGE / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads(
        (PACKAGE / ".claude-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    entry = changelog.split(f"## [{manifest['version']}]", 1)[1].split("\n## [", 1)[0]
    assert SDLC_PIN in entry, f"the {manifest['version']} entry does not name the pin {SDLC_PIN}"
    stale = {
        tok
        for tok in re.findall(r"\b[0-9a-f]{8}\b", entry)
        if tok != SDLC_PIN and not tok.isdigit()
    }
    assert not stale, (
        f"the {manifest['version']} entry names a revision other than the pin: {stale}"
    )


def test_the_dispatchless_prompt_says_why_it_differs() -> None:
    """The one allowed variant has to explain itself, or it reads as drift."""
    text = (ROLES_DIR / DISPATCHLESS_PROMPT).read_text(encoding="utf-8")
    block = shared_block(text, DISPATCHLESS_OPENER)
    assert "no dispatch" in block, (
        f"{DISPATCHLESS_PROMPT} varies the shared inputs paragraph without saying it has no dispatch"
    )
    # And it must not also claim to have one, which is what made this file contradict itself.
    assert "Your dispatch names the issue" not in text, (
        f"{DISPATCHLESS_PROMPT} both denies and claims a dispatch"
    )


@pytest.mark.parametrize("opener", SHARED_BLOCK_OPENERS)
def test_shared_blocks_are_byte_identical_across_every_prompt(opener: str) -> None:
    """Copied text needs an enforcer, or it is fourteen chances to drift.

    The journal originally rejected copying a shared block into each prompt, on the ground that the
    twenty-five copies in the retired plugin were twenty-five chances to drift. Later review
    established that a prompt must be self-contained -- a session cannot resolve a
    repository-relative pointer -- so the copying is now deliberate and the decision is superseded.
    What makes it safe is this check, not the intention.
    """
    considered = [
        p
        for p in PROMPT_FILES
        if not (opener == DISPATCHLESS_OPENER and p.name == DISPATCHLESS_PROMPT)
    ]
    blocks = {p.name: shared_block(p.read_text(encoding="utf-8"), opener) for p in considered}
    distinct = set(blocks.values())
    assert len(distinct) == 1, (
        f"the block opening {opener!r} differs across prompts; it must be byte-identical in all"
        f" {len(PROMPT_FILES)}. Variants: "
        + "; ".join(
            sorted({name for name, text in blocks.items() if text != max(distinct, key=len)})
        )
    )


def test_shared_half_permits_reporting_without_a_score() -> None:
    """A conditional lens with no fixture must be told it may report findings and not score.

    Asserted once, on the shared half, because that is where the permission lives and where it has
    to live: a per-lens parametrization of this same string claimed eleven cases of coverage that
    did not exist, since every slice carries the identical shared text.
    """
    shared = lens_slice(LENS_IDS[0]).split(f"{LENS_SECTION_PREFIX}{LENS_IDS[0]}")[0]
    assert "without scores" in shared, (
        "the shared half never says a conditional lens may report without scoring; without it the"
        " stop rule demands a score for every applicable dimension and eleven of fifteen sessions"
        " either fabricate one or never terminate"
    )


@pytest.mark.parametrize("lens_id", LENS_IDS)
def test_lens_section_is_about_its_own_lens(lens_id: str) -> None:
    """Something genuinely per-lens: the section names its own lens and its own subject matter.

    This is what the conditional-permission test used to pretend to check. A section copied from
    another lens, or left as a stub, fails here.
    """
    sliced = lens_slice(lens_id)
    section = sliced[sliced.index(f"{LENS_SECTION_PREFIX}{lens_id}") :]
    assert VENDORED_LENS_FLOORS[lens_id] in section, (
        f"the {lens_id} section does not name its own floor level ({VENDORED_LENS_FLOORS[lens_id]})"
    )
    assert "Dimension" in section, f"the {lens_id} section lists no dimensions"


def test_lens_reviewer_states_no_thresholds() -> None:
    """The catalogue owns the strictness ladder; a copy here would be a second source.

    Matched as a pattern rather than three exact strings, so ``8``, ``8.5`` and ``0.8`` are
    caught too -- the earlier form checked only the three spellings the catalogue happens to use
    today.
    """
    text = (ROLES_DIR / AGGREGATED_PROMPT).read_text(encoding="utf-8")
    found = THRESHOLD_PATTERN.findall(text)
    assert not found, (
        f"{AGGREGATED_PROMPT} names strictness values {found}; the ladder lives in the catalogue"
    )


def test_planner_and_delivery_manager_emit_several_contracts() -> None:
    """The two roles that forced ``emits`` to be a list, asserted on the real files."""
    planner = parse_frontmatter(ROLES_DIR / "planner.md")["emits"]
    delivery_manager = parse_frontmatter(ROLES_DIR / "delivery-manager.md")["emits"]
    assert isinstance(planner, list) and len(planner) == 2
    assert isinstance(delivery_manager, list) and len(delivery_manager) == 5


def test_lens_reviewer_emits_nothing_of_its_own() -> None:
    assert parse_frontmatter(ROLES_DIR / AGGREGATED_PROMPT)["emits"] == []


# --- seeded fixtures: each one calls the same checker the real test calls ----------------


def test_seeded_missing_stop_rule_fires() -> None:
    assert not has_stop_rule_heading("---\nrole: X\n---\n\n## Role\n\nbody\n")


def test_seeded_quoted_heading_is_not_a_heading() -> None:
    """The anchoring that makes the stop-rule check mean what it says."""
    text = "---\nrole: X\n---\n\nSee `### Stop rule` above, and | `### Stop rule` | in a table.\n"
    assert "### Stop rule" in text
    assert not has_stop_rule_heading(text)


def test_seeded_headings_out_of_order_fires() -> None:
    text = "## Output contract\n\n### Stop rule\n\n## Role\n\n## Inputs from the run record\n"
    assert missing_headings(text) == ["<out of order>"]


def test_seeded_headings_in_order_pass() -> None:
    filler = "Enough prose under the heading to count as a real section, not a bare heading.\n"
    text = (
        f"## Role\n\n{filler}\n## Inputs from the run record\n\n{filler}\n"
        f"## Output contract\n\n{filler}\n### Stop rule\n\n{filler}"
    )
    assert missing_headings(text) == []


def test_seeded_empty_section_fires() -> None:
    """A file of four headings with nothing under them must not pass R2."""
    text = "## Role\n\n## Inputs from the run record\n\n## Output contract\n\n### Stop rule\n"
    assert missing_headings(text) == [
        "## Role <empty>",
        "## Inputs from the run record <empty>",
        "## Output contract <empty>",
        "### Stop rule <empty>",
    ]


def test_seeded_empty_last_section_fires_even_with_trailing_content() -> None:
    """The stop rule's body must be checked, not the whole remainder of the file.

    Bounding the last required heading at end-of-file counted every later section as its body, so
    a prompt with content after the stop rule -- which the Lens Reviewer has 170 lines of -- could
    have an empty stop rule and pass.
    """
    filler = "Enough prose here to clear the emptiness floor for this section, comfortably.\n"
    text = (
        f"## Role\n\n{filler}\n## Inputs from the run record\n\n{filler}\n"
        f"## Output contract\n\n{filler}\n### Stop rule\n\n"  # deliberately empty
        f"# The lenses\n\n#### correctness\n\n{filler}{filler}"
    )
    assert missing_headings(text) == ["### Stop rule <empty>"]


def test_seeded_heading_inside_a_fence_does_not_count() -> None:
    """Every prompt embeds a fenced handoff example; a heading there is not a real section."""
    text = "# Title\n\n```markdown\n### Stop rule\n```\n"
    assert "### Stop rule" in text
    assert not has_stop_rule_heading(text)


def test_seeded_retired_vocabulary_fires() -> None:
    assert retired_vocabulary("Report hard-fail on error.") == ["hard-fail"]
    assert retired_vocabulary("See the team-execution plugin.") == ["team-execution"]
    assert retired_vocabulary("A clean prompt that passes and warns.") == []


def test_seeded_missing_lens_section_fires() -> None:
    body = "".join(f"#### {lens}\n\ntext\n\n" for lens in LENS_IDS[:-1])
    assert missing_lens_sections(body, LENS_IDS) == [LENS_IDS[-1]]
    assert missing_lens_sections(body, LENS_IDS[:-1]) == []


def test_seeded_emits_rules_fire() -> None:
    """Shape, membership, producership and the empty-list rule, each proven to fire."""
    assert emits_violations("planner", "dispatch", "planner.md")[0].startswith("emits must be")
    assert emits_violations("planner", [], "planner.md")[0].startswith("emits is empty")
    assert emits_violations("lens_reviewer", [], AGGREGATED_PROMPT) == []
    # The exemption is the role's, not the filename's: renaming a file must not confer it.
    assert emits_violations("planner", [], AGGREGATED_PROMPT)[0].startswith("emits is empty")
    assert "not a lifecycle handoff contract" in emits_violations("planner", ["nope"], "p.md")[0]
    assert "produced by" in emits_violations("product", ["run-record"], "product.md")[0]
    assert "repeats a contract" in emits_violations("controller", ["dispatch", "dispatch"], "d")[0]
    assert emits_violations("planner", ["planner-to-orchestrator"], "planner.md") == []


def test_seeded_repair_reuse_is_licensed() -> None:
    """Both repair roles may claim the initial worker's contract; nobody else may."""
    for role in REUSE_LICENSED_ROLES:
        assert emits_violations(role, [REUSED_CONTRACT], "r.md") == []
    assert emits_violations("release_worker", [REUSED_CONTRACT], "r.md") != []


def test_seeded_parser_keeps_oddly_indented_list_items() -> None:
    """The defect that made a mis-indented list look like a legitimately empty one.

    The fix is to accept the item at any indent rather than to reject the file: dropping it
    silently turned a role that emits one contract into one that appears to emit none, and the
    empty-``emits`` rule then accepted it.
    """
    for spelling in ("---\nemits:\n    - a\n---\nb\n", "---\nemits:\n\t- a\n---\nb\n"):
        assert parse_frontmatter(spelling)["emits"] == ["a"]


def test_seeded_parser_rejects_a_list_item_with_no_key() -> None:
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\n- orphan\n---\nbody\n")


def test_seeded_parser_rejects_duplicate_key() -> None:
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nemits:\n  - a\nemits:\n  - b\n---\nbody\n")


def test_seeded_parser_rejects_junk_line() -> None:
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nrole: X\njust some prose\n---\nbody\n")


def test_seeded_parser_rejects_prose_containing_a_colon() -> None:
    """A colon does not make a line a key -- the shape the old guard could not see."""
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nrole: X\nsee run-roles.md: the catalogue\n---\nbody\n")


def test_only_the_parity_test_needs_a_sibling_checkout() -> None:
    """Continuous integration has no sibling lifecycle checkout, so nothing else may require one.

    An earlier form asserted the identifiers had been read live, which no runner can satisfy: the
    suite was green on a developer machine and red in continuous integration, which is the worst
    direction for that asymmetry. The prompts are now always checked against the vendored
    snapshot, and exactly one test reaches for the lifecycle itself.
    """
    # Asserted against the file on disk rather than against the constants five lines above it:
    # comparing two names assigned to each other cannot fail, and is a comment with assert syntax.
    on_disk = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert tuple(on_disk["roles"]) == ROLE_IDS
    assert on_disk["roles"] == ROLE_NAMES
    assert tuple(on_disk["lenses"]) == LENS_IDS
    assert set(CONTRACT_SENDERS) == set(on_disk["contracts"])
    for cid, row in on_disk["contracts"].items():
        assert CONTRACT_SENDERS[cid] == row["sender_role"]
        assert CONTRACT_NAMES[cid] == row["name"]
        assert CONTRACT_FIELDS[cid] == frozenset(row["required_fields"])
        assert VENDORED_FIELD_DESCRIPTIONS[cid] == row["field_descriptions"]
        assert set(row["field_descriptions"]) == set(row["required_fields"])


def test_parity_test_skips_rather_than_fails_without_a_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate the runner: no sibling checkout anywhere, and no environment variable.

    This is the condition that made an earlier form of the suite red in continuous integration
    while green on a developer machine. Proven by simulation rather than argued.
    """
    monkeypatch.delenv("INFIQUETRA_SDLC_ROOT", raising=False)
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self, *a, **k: False)
    assert _sdlc_root() is None

    # `pytest.skip` raises a BaseException subclass, so a bare `pytest.raises(Exception)` does not
    # catch it -- the skip escapes and marks THIS test skipped, which reads as green while proving
    # nothing. Catch BaseException and name the outcome.
    outcome = "returned normally"
    try:
        test_vendored_snapshot_matches_the_live_lifecycle()
    except BaseException as exc:  # noqa: BLE001 - the outcome type is the assertion
        outcome = type(exc).__name__
    assert outcome == "Skipped", (
        f"with no checkout reachable the parity test {outcome}; anything but a skip is a red"
        " continuous-integration run"
    )


def test_seeded_parser_accepts_both_empty_list_spellings() -> None:
    assert parse_frontmatter("---\nemits: []\n---\nb\n")["emits"] == []
    assert parse_frontmatter("---\nemits:\nsource: s\n---\nb\n")["emits"] == []


def test_seeded_parser_keeps_colons_in_values() -> None:
    parsed = parse_frontmatter("---\nsource: sdlc@5efc869f docs/a.md: the thing\n---\nb\n")
    assert parsed["source"] == "sdlc@5efc869f docs/a.md: the thing"


def test_seeded_parser_returns_empty_for_no_frontmatter() -> None:
    """Absence is not an error here -- the required-key check reports it, loudly."""
    assert parse_frontmatter("# Just a heading\n") == {}
