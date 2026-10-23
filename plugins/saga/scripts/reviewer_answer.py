#!/usr/bin/env python3
"""The targeted reviewer's answer: the check, the Jev consequence pick and the records (issue 158).

Saga's targeted reviewer answers every item on the review's where-to-look list, reproduces what it
believes with a sandboxed test, and runs one capped open search. Its instructions are
``references/targeted-reviewer-prompt.md`` and its answer's shape is
``references/targeted-reviewer-answer.schema.json``. Agent-launcher starts the session
(``launcher.py review``); saga never does.

This module does three things with an answer, and the review command (card C10a) calls it:

* ``check`` refuses an answer by naming each problem: a skipped or twice-answered item, a finding
  missing a location, statement or closed-list label, a reproduction without its test, command and
  output, any severity, too many open-search findings, or a scratch copy changed outside the
  reproduction tests. One exception is a warning, not a refusal: an added test file that no
  reproduced finding names. The file is never evidence, and the answer's findings stand.
* ``records`` turns an accepted answer into review_records.v1 findings and answered where-to-look
  records. It first replaces known secret formats in every free-text string a record stores (each
  finding's statement, dispute text, location and proof, and each cleared item's reason) with a
  marker naming their kind (``[scrubbed:github-token]``), so neither the record nor Jev's state
  carries what a test printed. For each reproduced finding it asks Jev (TypeSafe's classifier,
  through fleet-core's ``consequence`` verb) for the consequence. The lower of the two picks
  applies, which C1's formula computes; when Jev cannot answer, the finding is marked
  ``unconfirmed`` and the reviewer's pick applies.
* ``paths`` prints where saga's prompt and schema are, with their fingerprints, so the caller can
  hand them to agent-launcher without guessing where saga is installed.

The formula, the identity and the record validator are C1's (``review_formula.py``,
``review_records.py``); nothing here re-implements them.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import shlex
import sys
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import reproduction_match  # noqa: E402  (after the sys.path shim, by design)
import review_formula as formula  # noqa: E402
import review_records as records  # noqa: E402

REFERENCES = _SCRIPTS_DIR.parent / "references"
PROMPT_FILE = REFERENCES / "targeted-reviewer-prompt.md"
SCHEMA_FILE = REFERENCES / "targeted-reviewer-answer.schema.json"
LAUNCH_SETTINGS_FILE = REFERENCES / "targeted-reviewer-launch.json"

ANSWER_SCHEMA = "targeted_reviewer_answer.v1"
#: The most findings the open search may report, unless the review packet states another cap.
OPEN_SEARCH_CAP = 5
OPEN_SEARCH = "open-search"
#: The Jev verb that picks a reproduced finding's consequence (fleet-core's registry).
JEV_VERB = "consequence"

#: The evidence a reviewer may give; ``tool-result`` is reserved for tools.
REVIEWER_EVIDENCE: tuple[str, ...] = tuple(e for e in formula.EVIDENCE if e != "tool-result")
#: The rows a reviewer may cite: ``judged`` (code picks the judged row) or a lens's dispute row.
REVIEWER_ROWS: tuple[str, ...] = (formula.JUDGED,) + tuple(
    f"{lens}.dispute" for lens in formula.LENSES
)

ITEM_KEYS = frozenset({"index", "file", "answer"})
FINDING_REQUIRED: tuple[str, ...] = (
    "key",
    "origin",
    "lens",
    "row",
    "location",
    "language",
    "statement",
    "consequence",
    "trigger",
    "evidence",
    "proof",
    "introduced",
)
FINDING_KEYS = frozenset(FINDING_REQUIRED) | {"disputes"}
PROOF_KEYS = frozenset({"test", "command", "output", "steps"})
#: Keys that only code may write. Anywhere in an answer, each one refuses it.
COMPUTED_ANYWHERE = frozenset(
    {"severity", "severity_basis", "flags", "enforced", "priority", "grade", "score"}
)
#: Keys the record fills from the launch and Jev, never the reviewer.
FILLED_BY_CODE = frozenset(
    {"id", "kind", "subject", "source", "rule", "degraded", "consequence_jev", "unconfirmed",
     "merge_outcome"}
)

#: A reproduction's test file must look like a test by its path.
_TEST_DIR = re.compile(r"(^|/)(tests?|spec|__tests__)/")
_TEST_NAME = re.compile(r"(^test_[^/]*$)|(_test\.[^/]+$)|(\.test\.[^/]+$)|(\.spec\.[^/]+$)")
#: What Claude acts on outside its command sandbox; never a reproduction test, whatever its name.
_CLAUDE_CONFIG = (".claude", ".mcp.json")

#: A command that would need a shell to run: the shell itself, or ``env``.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "env"})
#: A leading POSIX environment assignment, ``NAME=value``. It is not an executable, and the
#: replay starts no shell that would read it as one.
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def reproduction_argv(command: Any) -> list[str] | None:
    """The direct argv a reproduction command runs as, or None when it is not one.

    The command is split as arguments, never run through a shell: a shell would expand
    what this must not. A command that is empty, not a string, malformed, names a shell
    or ``env``, or starts with a ``NAME=value`` environment assignment has no direct argv
    and is refused. The assignment is refused because the replay starts the program
    directly, so the assignment would be taken for the program's name.

    Everything else is returned exactly as it was written, quoted arguments and
    ``=`` inside an argument included.
    """
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    token = parts[0]
    name = Path(token).name if "/" in token or "\\" in token else token
    if name in _SHELLS:
        return None
    if _ENV_ASSIGNMENT.match(token):
        return None
    return parts


def is_claude_configuration(path: str) -> bool:
    """Whether *path* is in a ``.claude`` directory or is ``.mcp.json``, at any depth or case."""
    parts = str(path).replace("\\", "/").split("/")
    return any(unicodedata.normalize("NFKC", part).casefold() in _CLAUDE_CONFIG for part in parts)


# ---------------------------------------------------------------------------
# Scrubbing (issue 189)
# ---------------------------------------------------------------------------

#: Secret formats replaced in a finding's proof and statement before the record or Jev's state is
#: built, specific kinds first. A test the reviewed change carries can print what it read; the
#: sandbox has no network, so the record and the Jev state are where a secret would leave. Fleet-
#: core redacts the Jev state again on transport, but with one anonymous placeholder, and it does
#: not touch the record. This table covers fleet-core's formats and every literal format
#: ``scripts/check_repo.py`` bans; a test keeps that parity.
SCRUB_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # An unterminated block runs to the end: the output may have been cut.
    ("private-key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)",
        re.DOTALL,
    )),
    # Distinctive prefixes carry no word boundary: a token glued to ``_`` or a letter
    # (``KEY_ghp_...``) has none, and matching too much only scrubs more.
    ("github-token", re.compile(r"github_pat_[A-Za-z0-9_]{22,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws-access-key-id", re.compile(r"(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}")),
    ("slack-token", re.compile(r"xox[abposr]-[A-Za-z0-9\-]{10,}")),
    ("stripe-key", re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("google-api-key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("anthropic-api-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{24,}")),
    ("api-key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")),
    ("url-credentials", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@")),
    # Fleet-core's named assignment, with its bounded repeats (an unbounded prefix is quadratic).
    ("named-secret", re.compile(
        r"(?i)\b[A-Z0-9_\-]{0,32}(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)"
        r"[A-Z0-9_\-]{0,32}['\"]?\s*[=:]\s*['\"]?[^\s'\",;}\]]{6,}")),
)
#: Fleet-core's high-entropy rule (``typesafe_client.py``): a long run with real entropy, unless it
#: is a hex content hash. ``/`` is outside the alphabet, so file paths survive.
SCRUB_ENTROPY_MIN_RUN = 40
SCRUB_ENTROPY_MIN_BITS = 4.0
_SCRUB_ENTROPY_RUN = re.compile(rf"[A-Za-z0-9+=_\-]{{{SCRUB_ENTROPY_MIN_RUN},}}")
#: A base64 secret can hold ``/`` (an AWS secret access key, a key body without its header line),
#: which splits it into short runs the rule above never sees. A run that includes ``/`` is scrubbed
#: when it also mixes upper case, lower case and digits, as random base64 does and paths rarely do.
_SCRUB_SLASHED_RUN = re.compile(rf"[A-Za-z0-9+/=_\-]{{{SCRUB_ENTROPY_MIN_RUN},}}")
_SCRUB_HASH_RUN = re.compile(r"(?i)\A(?:(?:sha\d{3}|md5|sha)[-:])?[0-9a-f]{32,}=*\Z")


def _shannon_bits(text: str) -> float:
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    return -sum((n / len(text)) * math.log2(n / len(text)) for n in counts.values())


def scrub_text(text: str) -> tuple[str, list[str]]:
    """*text* with each secret replaced by ``[scrubbed:<kind>]``, and the kinds replaced."""
    kinds: list[str] = []

    def marker(kind: str) -> Callable[[re.Match[str]], str]:
        def replace(_match: re.Match[str]) -> str:
            kinds.append(kind)
            return f"[scrubbed:{kind}]"
        return replace

    for kind, pattern in SCRUB_PATTERNS:
        text = pattern.sub(marker(kind), text)

    def entropy(match: re.Match[str]) -> str:
        run = match.group(0)
        if _SCRUB_HASH_RUN.match(run) or _shannon_bits(run) < SCRUB_ENTROPY_MIN_BITS:
            return run
        kinds.append("high-entropy")
        return "[scrubbed:high-entropy]"

    def slashed(match: re.Match[str]) -> str:
        run = match.group(0)
        mixed = (any(c.isupper() for c in run) and any(c.islower() for c in run)
                 and any(c.isdigit() for c in run))
        if "/" not in run or not mixed or _shannon_bits(run) < SCRUB_ENTROPY_MIN_BITS:
            return run
        kinds.append("high-entropy")
        return "[scrubbed:high-entropy]"

    text = _SCRUB_ENTROPY_RUN.sub(entropy, text)
    return _SCRUB_SLASHED_RUN.sub(slashed, text), kinds


def scrub_finding(finding: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A copy of *finding* with every free-text string the record stores scrubbed, and the kinds.

    That is the statement, the dispute text, every location string (anchor, file, function and a
    plan's document and section) and every proof string. ``trigger`` and the location's ``scope``
    are left alone: the check holds each to a closed list, so neither can carry a secret.
    """
    scrubbed = copy.deepcopy(dict(finding))
    kinds: list[str] = []

    def clean(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text, found = scrub_text(value)
        kinds.extend(found)
        return text

    scrubbed["statement"] = clean(scrubbed.get("statement"))
    if "disputes" in scrubbed:
        scrubbed["disputes"] = clean(scrubbed["disputes"])
    location = scrubbed.get("location")
    if isinstance(location, dict):
        for key in location:
            if key != "scope":
                location[key] = clean(location[key])
    proof = scrubbed.get("proof")
    if isinstance(proof, dict):
        for key in ("test", "command", "output"):
            if key in proof:
                proof[key] = clean(proof[key])
        if isinstance(proof.get("steps"), list):
            proof["steps"] = [clean(step) for step in proof["steps"]]
    return scrubbed, kinds


class AnswerRefused(Exception):
    """An answer the check refused, with one ``<field path>: <why>`` line per problem."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def test_file_of(test: str) -> str:
    """The file part of a test reference such as ``tests/test_x.py::test_y``."""
    return test.split("::", 1)[0].strip()


def looks_like_a_test(path: str) -> bool:
    """Whether *path* names a test file, by its directory or its file name."""
    normal = path.replace("\\", "/").lstrip("./")
    name = normal.rsplit("/", 1)[-1]
    return bool(_TEST_DIR.search(normal) or _TEST_NAME.search(name))


def path_key(path: str) -> str:
    """The one comparison for a cited test and a scratch change: Unicode-folded, case-folded.

    A volume that ignores case opens ``tests/test_Changed.py`` for ``tests/test_changed.py``, so
    the two spellings are one file. Warning about the file and copying it into a re-run tree must
    both decide through this key, so the file a warning names is never the file that is copied.
    """
    return unicodedata.normalize("NFKC", str(path).lstrip("./")).casefold()


def is_plain_test_path(path: str) -> bool:
    """Whether *path* is a relative path as written that names a test, with nothing normalised.

    Unlike ``looks_like_a_test``, which forgives a leading ``./`` and reads a backslash as a
    separator, this refuses an absolute path, a backslash, and any empty, ``.`` or ``..``
    component, and reads the path exactly as written. ``.tests/x.py``, ``notatest\\test_x.py``,
    ``../tests/x.py`` and ``tests/../src/x.py`` are not tests.
    """
    text = str(path)
    if not text or "\\" in text or text.startswith("/") or re.match(r"[A-Za-z]:", text):
        return False
    if any(part in ("", ".", "..") for part in text.split("/")):
        return False
    return bool(_TEST_DIR.search(text) or _TEST_NAME.search(text.rsplit("/", 1)[-1]))


def _describe(item: Any) -> str:
    """``file:start-end`` for an item, from its C1 location; the file alone for whole-project."""
    location = item.get("location") if isinstance(item, Mapping) else None
    if not isinstance(location, Mapping):
        return "no location"
    where = str(location.get("file") or "no file")
    lines = location.get("lines")
    if isinstance(lines, Mapping) and "start" in lines and "end" in lines:
        return f"{where}:{lines['start']}-{lines['end']}"
    return where


def _computed_keys(value: Any, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in COMPUTED_ANYWHERE:
                found.append(here)
            found.extend(_computed_keys(inner, here))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            found.extend(_computed_keys(inner, f"{path}.{index}"))
    return found


def _check_items(
    check: records._Check, answers: Any, items: Sequence[Any], keys: set[str]
) -> dict[int, str]:
    """Each item answered exactly once; returns index -> the finding key it names."""
    named: dict[int, str] = {}
    seen: set[int] = set()
    if not check.array(answers, "items") or not isinstance(answers, list):
        return named
    for position, entry in enumerate(answers):
        if not isinstance(entry, Mapping):
            check.add(f"items[{position}]", "must be an object")
            continue
        index = entry.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
            check.add(
                f"items[{position}].index",
                f"{index!r} is not an item on the where-to-look list (0 to {len(items) - 1})",
            )
            continue
        path = f"items.{index}"
        if index in seen:
            check.add(path, f"where-to-look item {index} is answered more than once")
            continue
        seen.add(index)
        for extra in sorted(set(entry) - ITEM_KEYS):
            if extra not in COMPUTED_ANYWHERE:
                check.add(f"{path}.{extra}", "is not a field of an item's answer")
        item_file = (items[index].get("location") or {}).get("file")
        if entry.get("file") != item_file:
            check.add(
                f"{path}.file",
                f"{entry.get('file')!r} is not item {index}'s location.file {item_file!r}",
            )
        answer = entry.get("answer")
        if not check.mapping(answer, f"{path}.answer") or not isinstance(answer, Mapping):
            continue
        if not check.choice(answer.get("kind"), ("finding", "cleared"), f"{path}.answer.kind"):
            continue
        if answer["kind"] == "cleared":
            check.text(answer.get("reason"), f"{path}.answer.reason")
        else:
            key = answer.get("finding")
            if not isinstance(key, str) or key not in keys:
                check.add(f"{path}.answer.finding", f"{key!r} names no finding in this answer")
            else:
                named[index] = key
    for index in range(len(items)):
        if index not in seen:
            check.add(
                f"items.{index}",
                f"where-to-look item {index} ({_describe(items[index])}) has no answer",
            )
    return named


def _check_proof(check: records._Check, finding: Mapping[str, Any], path: str) -> None:
    proof = finding.get("proof")
    if not check.mapping(proof, f"{path}.proof") or not isinstance(proof, Mapping):
        return
    for extra in sorted(set(proof) - PROOF_KEYS):
        check.add(f"{path}.proof.{extra}", "is not a field of a proof")
    evidence = finding.get("evidence")
    if evidence == "reproduced":
        for name in ("test", "command", "output"):
            value = proof.get(name)
            if not isinstance(value, str) or not value.strip():
                check.add(
                    f"{path}.proof.{name}",
                    "a reproduced finding gives its failing test, the command that ran it, "
                    "and its output",
                )
        test = proof.get("test")
        if isinstance(test, str) and test.strip() and not looks_like_a_test(test_file_of(test)):
            check.add(f"{path}.proof.test", f"{test_file_of(test)} is not a test file")
        command = proof.get("command")
        if (
            isinstance(command, str)
            and command.strip()
            and reproduction_argv(command) is None
        ):
            check.add(
                f"{path}.proof.command",
                "must be a directly executable command with its arguments, without a shell, "
                "an environment assignment or a variable expansion: the re-run starts the "
                "program itself, so 'NAME=value command' and 'sh -c ...' are not commands it "
                "can run",
            )
    elif evidence == "traced":
        steps = proof.get("steps")
        if not isinstance(steps, list) or not steps or not all(
            isinstance(step, str) and step.strip() for step in steps
        ):
            check.add(f"{path}.proof.steps", "a traced finding gives its file-and-line steps")


def _check_finding(
    check: records._Check, finding: Mapping[str, Any], path: str, items: Sequence[Any]
) -> None:
    check.required(finding, FINDING_REQUIRED, f"{path}.")
    for extra in sorted(set(finding) - FINDING_KEYS):
        if extra in COMPUTED_ANYWHERE:
            continue  # reported once by the computed-key sweep
        why = (
            "code fills it from the launch and Jev; the reviewer never writes it"
            if extra in FILLED_BY_CODE
            else "is not a field of a finding"
        )
        check.add(f"{path}.{extra}", why)
    origin = finding.get("origin")
    if "origin" in finding and origin != OPEN_SEARCH:
        item = origin.get("item") if isinstance(origin, Mapping) else None
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item < len(items):
            check.add(f"{path}.origin", f"must be {OPEN_SEARCH!r} or an item on the list")
    lens = finding.get("lens")
    if "lens" in finding:
        check.choice(lens, formula.LENSES, f"{path}.lens")
    row = finding.get("row")
    if "row" in finding and check.choice(row, REVIEWER_ROWS, f"{path}.row"):
        if row != formula.JUDGED:
            if row != f"{lens}.dispute":
                check.add(f"{path}.row", f"{row!r} is another lens's dispute row")
            check.text(finding.get("disputes"), f"{path}.disputes")
        elif "disputes" in finding:
            check.add(f"{path}.disputes", "only a dispute row names what it disputes")
    if "location" in finding:
        records._check_location(
            check, finding["location"], f"{path}.location", subject="code",
            scopes=("lines", "whole-project"),
        )
    if "language" in finding:
        check.choice(finding["language"], formula.LANGUAGES, f"{path}.language")
    statement = finding.get("statement")
    if (
        "statement" in finding
        and check.text(statement, f"{path}.statement")
        and isinstance(statement, str)
        and "\n" in statement
    ):
        check.add(f"{path}.statement", "must be one sentence on one line")
    if "consequence" in finding:
        check.choice(finding["consequence"], formula.CONSEQUENCES, f"{path}.consequence")
    if "trigger" in finding:
        check.choice(finding["trigger"], formula.TRIGGERS, f"{path}.trigger")
    if "evidence" in finding:
        if finding["evidence"] == "tool-result":
            check.add(f"{path}.evidence", "'tool-result' is reserved for tools")
        elif (
            check.choice(finding["evidence"], REVIEWER_EVIDENCE, f"{path}.evidence")
            and finding["evidence"] == "suspected"
            and origin == OPEN_SEARCH
        ):
            check.add(
                f"{path}.evidence",
                "'suspected' is only for a where-to-look item you could neither clear nor "
                "trace; an open-search finding is traced or reproduced",
            )
    if "proof" in finding:
        _check_proof(check, finding, path)
    if "introduced" in finding:
        check.boolean(finding["introduced"], f"{path}.introduced")


def reproduction_tests(answer: Mapping[str, Any]) -> set[str]:
    """The test files the answer's reproduced findings name."""
    tests: set[str] = set()
    for finding in answer.get("findings") or ():
        if isinstance(finding, Mapping) and finding.get("evidence") == "reproduced":
            test = (finding.get("proof") or {}).get("test") if isinstance(
                finding.get("proof"), Mapping) else None
            if isinstance(test, str) and test.strip():
                tests.add(test_file_of(test).lstrip("./"))
    return tests


def cited_keys(answer: Mapping[str, Any]) -> set[str]:
    """``path_key`` of each test file the answer's reproduced findings name."""
    return {path_key(test) for test in reproduction_tests(answer)}


UNCITED_TEST = "is a test file no reproduced finding names; it is not evidence and was ignored"


def _check_scratch(
    check: records._Check, answer: Mapping[str, Any], result: Any, warnings: list[str],
) -> None:
    """The scratch copy differs from the head only by the reproduction tests.

    An added test file that no reproduced finding names is the one exception: it goes to
    *warnings*, because refusing it would throw away every finding in an otherwise good answer.
    """
    scratch = result.get("scratch") if isinstance(result, Mapping) else None
    changes = scratch.get("changes") if isinstance(scratch, Mapping) else None
    if not isinstance(changes, Mapping):
        check.add("scratch.changes", "the launch result does not list the scratch copy's changes")
        return
    allowed = cited_keys(answer)
    for path in changes.get("links") or ():
        check.add("scratch.changes", f"{path} (symlink) is a link the session made, never a test")
    for kind in ("added", "modified", "deleted"):
        for path in changes.get(kind) or ():
            if is_claude_configuration(str(path)):
                check.add(
                    "scratch.changes", f"{path} ({kind}) is Claude configuration, never a test"
                )
                continue
            cited = path_key(str(path)) in allowed
            if kind != "deleted" and cited and looks_like_a_test(str(path).lstrip("./")):
                continue
            if kind == "added" and not cited and is_plain_test_path(str(path)):
                warnings.append(f"scratch.changes: {path} (added) {UNCITED_TEST}")
                continue
            check.add("scratch.changes", f"{path} ({kind}) is not a reproduction test")


def check(
    answer: Any,
    items: Sequence[Any],
    *,
    open_search_cap: int = OPEN_SEARCH_CAP,
    result: Any = None,
    warnings: list[str] | None = None,
) -> list[str]:
    """Every problem with *answer* against *items*; empty when the answer is accepted.

    A warning is not a problem: when *warnings* is a list, each one is appended to it.
    """
    problems = records._Check()
    if not isinstance(answer, Mapping):
        problems.add("answer", "must be a JSON object")
        return problems.problems
    if not isinstance(items, list):
        problems.add("where-to-look", "must be a JSON array of where-to-look records")
        return problems.problems
    for path in _computed_keys(answer, ""):
        problems.add(path, "code computes it; the reviewer never writes one")
    if answer.get("schema") != ANSWER_SCHEMA:
        problems.add("schema", f"must be {ANSWER_SCHEMA!r}")
    for extra in sorted(set(answer) - {"schema", "items", "findings"}):
        if extra not in COMPUTED_ANYWHERE:
            problems.add(extra, "is not a field of an answer")

    findings = answer.get("findings")
    keys: dict[str, Mapping[str, Any]] = {}
    paths: list[tuple[str, Mapping[str, Any]]] = []
    if problems.array(findings, "findings") and isinstance(findings, list):
        for position, finding in enumerate(findings):
            if not isinstance(finding, Mapping):
                problems.add(f"findings.{position}", "must be an object")
                continue
            key = finding.get("key")
            path = f"findings.{key}" if isinstance(key, str) and key.strip() else (
                f"findings.{position}")
            if isinstance(key, str) and key in keys:
                problems.add(f"{path}.key", "is used by more than one finding")
            elif isinstance(key, str) and key.strip():
                keys[key] = finding
            paths.append((path, finding))

    named = _check_items(problems, answer.get("items"), items, set(keys))
    # The item's question is the rule behind its finding, so the finding must come from that item.
    for index, key in sorted(named.items()):
        origin = keys[key].get("origin")
        if not (isinstance(origin, Mapping) and type(origin.get("item")) is int
                and origin["item"] == index):
            problems.add(
                f"items.{index}.answer.finding",
                f"{key!r} is not item {index}'s finding: its origin is {origin!r}",
            )
    for path, finding in paths:
        _check_finding(problems, finding, path, items)
        origin = finding.get("origin")
        if isinstance(origin, Mapping) and isinstance(origin.get("item"), int):
            index = origin["item"]
            if named.get(index) != finding.get("key") and 0 <= index < len(items):
                problems.add(
                    f"{path}.origin",
                    f"item {index} does not answer with this finding",
                )
    open_search = sum(1 for _, finding in paths if finding.get("origin") == OPEN_SEARCH)
    if open_search > open_search_cap:
        problems.add(
            OPEN_SEARCH, f"{open_search} findings, the cap is {open_search_cap}"
        )
    if result is not None:
        _check_scratch(problems, answer, result, warnings if warnings is not None else [])
    return problems.problems


# ---------------------------------------------------------------------------
# Records and the Jev pick
# ---------------------------------------------------------------------------

Asker = Callable[[Any, Mapping[str, Any]], Any]


def _fleet(name: str) -> Any:
    import bundled_fleet  # noqa: PLC0415  (loaded only when Jev is asked)

    return bundled_fleet.load(name)


# What became of one Jev pick. ``accepted`` is the only status that yields a consequence.
PICK_ACCEPTED = "accepted"
PICK_NOT_ASKED = "not-asked"
PICK_REQUEST_FAILED = "request-failed"
PICK_NO_ANSWER = "no-answer"
PICK_OFF_LIST = "off-list"
PICK_BELOW_FLOOR = "below-floor"

_VALUE_LIMIT = 200


def _pick(
    status: str,
    reason: str,
    *,
    pick: str | None = None,
    request: str | None = None,
    value: Any = None,
    confidence: float | None = None,
    floor: float | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "pick": pick,
        "request": request,
        "value": None if value is None else scrub_text(str(value))[0][:_VALUE_LIMIT],
        "confidence": confidence,
        "floor": floor,
        "reason": reason,
    }


def jev_pick(finding: Mapping[str, Any], ask: Asker | None = None) -> dict[str, Any]:
    """Jev's consequence for a reproduced finding, with the reason when it has none.

    The result carries ``pick`` (the accepted consequence or ``None``), ``status`` (one of the
    ``PICK_*`` names), ``request`` (the client's status), Jev's own ``value`` and ``confidence``
    when it gave them, the verb's ``floor`` and a prose ``reason``.

    Jev cannot answer when the request fails (no key, timeout, malformed, error), when it gives no
    consequence from the closed list, or when its confidence is below the verb's floor. A value
    that is not accepted is still recorded, so a run can tell why a pick is missing.
    """
    client = _fleet("typesafe_client")
    verb = _fleet("jev_verbs").VERBS[JEV_VERB]
    proof = finding.get("proof") or {}
    # Scrubbed here as well as in ``to_records``, so any caller is safe; before the cut, never
    # after it, so no fragment of a secret survives at the 4,000th character.
    state = {
        "finding": scrub_text(str(finding.get("statement") or ""))[0],
        "trigger": finding.get("trigger"),
        "test": scrub_text(str(proof.get("test") or ""))[0],
        "output": scrub_text(str(proof.get("output") or ""))[0][:4000],
    }
    caller = ask if ask is not None else client.ask
    result = caller(state, verb.question_set())
    status = getattr(result, "status", client.STATUS_ERROR)
    floor = verb.confidence_floor
    if status != client.STATUS_OK:
        return _pick(
            PICK_REQUEST_FAILED,
            getattr(result, "note", "") or f"the request failed with status {status}",
            request=str(status), floor=floor,
        )
    answer = (getattr(result, "answers", {}) or {}).get(JEV_VERB)
    if not isinstance(answer, Mapping):
        return _pick(PICK_NO_ANSWER, "Jev gave no consequence", request=str(status), floor=floor)
    value = client.answer_value(answer)
    confidence = client.answer_confidence(answer)
    if value is None:
        return _pick(PICK_NO_ANSWER, "Jev gave no consequence", request=str(status), floor=floor)
    given = {"request": str(status), "value": value, "confidence": confidence, "floor": floor}
    if value not in formula.CONSEQUENCES:
        # The reason repeats Jev's answer, so it is scrubbed and cut like ``value``.
        shown = scrub_text(str(value))[0][:_VALUE_LIMIT]
        return _pick(PICK_OFF_LIST, f"Jev's answer {shown!r} is not on the closed list", **given)
    if confidence is None or confidence < floor:
        return _pick(
            PICK_BELOW_FLOOR,
            f"Jev chose {value!r} with confidence {confidence}, below the floor {floor}",
            **given,
        )
    return _pick(PICK_ACCEPTED, "", pick=str(value), **given)


def _reviewer_source(result: Mapping[str, Any]) -> dict[str, str]:
    vendor = str(result.get("vendor") or "unknown")
    model = result.get("model") if isinstance(result.get("model"), Mapping) else {}
    resolved = model.get("resolved") if isinstance(model, Mapping) else None
    name = (resolved[0] if isinstance(resolved, list) and resolved else None) or (
        model.get("requested") if isinstance(model, Mapping) else None)
    return {"kind": "llm", "name": f"targeted-reviewer:{vendor}", "model": str(name or "unknown")}


def _rule_ref(finding: Mapping[str, Any], items: Sequence[Any]) -> str:
    """The question behind a finding: its item's likeliest question, or the open search."""
    if finding.get("row") != formula.JUDGED:
        return str(finding.get("disputes"))
    origin = finding.get("origin")
    if isinstance(origin, Mapping):
        questions = items[origin["item"]].get("questions") or []
        best = max(
            (q for q in questions if isinstance(q, Mapping)),
            key=lambda q: q.get("probability", 0),
            default=None,
        )
        if best is not None and best.get("id"):
            return str(best["id"])
    return OPEN_SEARCH


def to_records(
    answer: Mapping[str, Any],
    items: Sequence[Any],
    result: Mapping[str, Any],
    *,
    ask: Asker | None = None,
    use_jev: bool = True,
    open_search_cap: int = OPEN_SEARCH_CAP,
    raw_proofs: dict[int, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """An accepted answer as review_records.v1 findings and answered where-to-look records.

    Everything returned is scrubbed. A caller that must replay a reproduction as the reviewer wrote
    it passes an empty *raw_proofs*, and gets each reproduced finding's unscrubbed ``command``,
    ``test`` and ``output`` filled in under its position in the returned findings; two findings can
    share an identity, so the position is the key. That dict is for the caller's memory
    only: it is never part of the returned records, so nothing here writes a raw value.
    """
    problems = check(answer, items, open_search_cap=open_search_cap, result=result)
    if problems:
        raise AnswerRefused(problems)
    source = _reviewer_source(result)
    built: list[dict[str, Any]] = []
    identities: dict[str, str] = {}
    picks: list[dict[str, Any]] = []
    for original in answer["findings"]:
        finding = scrub_finding(original)[0]
        rule = {"row": finding["row"], "ref": _rule_ref(finding, items)}
        record: dict[str, Any] = {
            "kind": "finding",
            "schema": records.SCHEMA,
            "subject": "code",
            "lens": finding["lens"],
            "rule": rule,
            "source": dict(source),
            "location": copy.deepcopy(finding["location"]),
            "language": finding["language"],
            "statement": finding["statement"],
            "consequence": finding["consequence"],
            "trigger": finding["trigger"],
            "evidence": finding["evidence"],
            "proof": copy.deepcopy(finding["proof"]),
            "introduced": finding["introduced"],
            "degraded": False,
            "consequence_jev": None,
            "unconfirmed": False,
            "merge_outcome": None,
        }
        record["id"] = records.finding_identity(record["lens"], rule, record["location"])
        identities[finding["key"]] = record["id"]
        if finding["evidence"] == "reproduced":
            if raw_proofs is not None:
                given = original.get("proof") or {}
                raw_proofs[len(built)] = {
                    name: given[name] for name in ("command", "test", "output")
                    if isinstance(given.get(name), str)
                }
            outcome = (
                jev_pick(finding, ask) if use_jev
                else _pick(PICK_NOT_ASKED, "Jev was not asked")
            )
            jev = outcome["pick"]
            record["consequence_jev"] = jev
            record["unconfirmed"] = jev is None
            applied = (
                finding["consequence"] if jev is None
                else formula.lower_consequence(finding["consequence"], jev)
            )
            flag = (
                "unconfirmed" if jev is None
                else "agreement" if jev == finding["consequence"]
                else "consequence-disagreement"
            )
            picks.append({
                "finding_id": record["id"],
                "llm": finding["consequence"],
                "jev": jev,
                "applied": applied,
                "flag": flag,
                "note": outcome["reason"],
                "jev_status": outcome["status"],
                "jev_request": outcome["request"],
                "jev_value": outcome["value"],
                "jev_confidence": outcome["confidence"],
                "jev_floor": outcome["floor"],
            })
        built.append(record)

    answered: list[dict[str, Any]] = []
    by_index = {entry["index"]: entry["answer"] for entry in answer["items"]}
    for index, item in enumerate(items):
        record = copy.deepcopy(dict(item))
        given = by_index[index]
        record["answer"] = (
            {"kind": "finding", "finding_id": identities[given["finding"]]}
            if given["kind"] == "finding"
            else {"kind": "cleared", "reason": scrub_text(given["reason"])[0]}
        )
        answered.append(record)

    invalid = [
        f"findings.{n}.{line}" for n, r in enumerate(built) for line in records.validate(r)
    ] + [
        f"where_to_look.{n}.{line}" for n, r in enumerate(answered) for line in records.validate(r)
    ]
    if invalid:
        raise AnswerRefused(invalid)
    return {"findings": built, "where_to_look": answered, "consequence_picks": picks}


# ---------------------------------------------------------------------------
# Paths and the command line
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths() -> dict[str, str]:
    """Where saga's reviewer prompt and answer schema are, with their SHA-256 fingerprints."""
    return {
        "prompt": str(PROMPT_FILE),
        "schema": str(SCHEMA_FILE),
        "prompt_sha256": _sha256(PROMPT_FILE),
        "schema_sha256": _sha256(SCHEMA_FILE),
    }


def _short(text: str, width: int = 100) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def _output_mismatch(code: int, captured: str, recorded: str, test: str) -> str:
    """Why *recorded* would not match a run that printed *captured*, from the matcher's parts."""
    match = reproduction_match
    if code == 0:
        return "the captured run exited 0; saga only matches a run that failed"
    text = match.strip_ansi(captured[: match._CAPTURE_LIMIT])
    recorded_text = match.strip_ansi(recorded[: match._CAPTURE_LIMIT])
    file, name = match._split_cited(test) if test else ("", "")
    hits = [item for item in match.failed_tests(text) if match._fits(item, file, name)]
    if not hits:
        return (
            f"the captured output shows no failure of {test or 'the test'}; capture the run "
            "of the command in the finding's proof, with the failure block included"
        )
    recorded_failures = match.failed_tests(recorded_text)
    recorded_hits = [item for item in recorded_failures if match._fits(item, file, name)]
    if recorded_hits and not any(item.body for item in recorded_hits):
        header = recorded_hits[0].name
        return (
            f"the recorded output names '{header}' as FAILED but has no failure body, so there "
            "is no failure message to compare; paste the whole failure block, from the "
            f"'---- {header} stdout ----' line through the panic and assertion lines"
        )
    if recorded_failures and not recorded_hits:
        return (
            "the recorded output has failures for other tests only; none of them is "
            f"{test or 'the cited test'}"
        )
    wanted = match._message_lines(hits[0])
    if not wanted:
        return "the captured failure carries no message lines to compare against"
    if not recorded_hits:
        flat = " ".join(match._message_lines(
            match.Failure(None, "", tuple(match._lines(recorded_text)))
        ))
        if sum(map(len, wanted)) < match._MESSAGE_FLOOR:
            return "the captured failure message is too short to identify the failure"
        shown = "; ".join(f"'{_short(part)}'" for part in [p for p in wanted if p not in flat][:3])
        return (
            "the recorded output has no runner failure block (it looks like a one line summary "
            "or a copied excerpt), so every message line of the failure must appear in it; "
            f"missing from the recorded output: {shown}. Paste the full failure block"
        )
    expected = match._message_lines(recorded_hits[0])
    own, joined = " ".join(wanted), " ".join(expected)
    differing = [p for p in expected if p not in own] + [p for p in wanted if p not in joined]
    detail = "; ".join(f"'{_short(part)}'" for part in differing[:3])
    return (
        "the recorded failure message and the captured one differ"
        + (f" (for example {detail})" if detail else "")
        + "; the recorded output must be this failure's message as the run prints it"
    )


def output_match(
    answer: Any, key: str, captured: str, code: int = 1,
) -> tuple[bool, str | None]:
    """Would finding *key*'s ``proof.output`` match a replay that printed *captured*?

    Advisory only. It runs nothing and shares ``reproduction_match.matches`` with saga's replay,
    comparing the recorded output with *captured* raw against raw. *code* is the exit code of
    the reviewer's own run (default 1, a failing run). Returns ``(matches, reason)``; the reason
    is None when it matches, and says why when it does not.
    """
    found = [
        item for item in (answer.get("findings") or ())
        if isinstance(item, Mapping) and item.get("key") == key
    ] if isinstance(answer, Mapping) else []
    if not found:
        return False, f"no finding with key '{key}' in the answer"
    item = found[0]
    proof = item.get("proof") if isinstance(item.get("proof"), Mapping) else {}
    if item.get("evidence") != "reproduced":
        return False, f"'{key}' is not a reproduced finding; only a reproduction is replayed"
    recorded, test = proof.get("output"), proof.get("test")
    if not isinstance(recorded, str) or not recorded.strip():
        return False, f"'{key}' records no proof.output to compare"
    test = test if isinstance(test, str) else ""
    if reproduction_match.matches(code, captured, recorded, test):
        return True, None
    try:
        return False, _output_mismatch(code, captured, recorded, test)
    except reproduction_match._ParseLimit as exc:
        # The matcher's parse limit: saga's replay gives up on output this large too.
        return False, f"the output is too large for saga's matcher to read ({exc})"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewer_answer.py",
        description=(
            "Check the targeted reviewer's answer and turn it into saga's review records. Exit 0 "
            "accepted; 1 refused, one '<field>: <why>' line per problem on standard error; 2 an "
            "unreadable file."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="Print saga's reviewer prompt and schema paths and SHA-256s.")
    match = sub.add_parser(
        "output-match",
        help="Advisory: would a reproduced finding's recorded output match saga's replay?",
        description=(
            "Advisory: say whether a reproduced finding's proof.output would match the output "
            "of a replay, using saga's own matcher. Give it the output you captured by running "
            "the finding's command yourself. It runs no command and changes nothing; saga's "
            "replay at finish still decides. Exit 0 would match; 1 would not, with the reason "
            "on standard error; 2 an unreadable file."
        ),
    )
    match.add_argument("--answer", type=Path, required=True, help="The draft answer JSON.")
    match.add_argument("--finding", required=True, help="The finding's key in the answer.")
    match.add_argument(
        "--output", type=Path, required=True,
        help="A file holding the complete output of your own run of the finding's command.",
    )
    match.add_argument(
        "--exit-code", type=int, default=1,
        help="The exit code of that run (default 1, a failing run).",
    )
    for name, text in (
        ("check", "Refuse an answer that skips an item or breaks the answer contract."),
        ("records", (
            "Check an answer, ask Jev for each reproduced finding's consequence, and print the "
            "review records."
        )),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--answer", type=Path, required=True, help="The answer JSON.")
        command.add_argument(
            "--items", type=Path, required=True,
            help="The where-to-look list: a JSON array of review_records.v1 where_to_look records.",
        )
        command.add_argument(
            "--result", type=Path, required=(name == "records"),
            help="agent-launcher's launch result (vendor, model, scratch-copy changes).",
        )
        command.add_argument(
            "--open-search-cap", type=int, default=OPEN_SEARCH_CAP,
            help=f"The most open-search findings allowed (default {OPEN_SEARCH_CAP}).",
        )
        if name == "records":
            command.add_argument(
                "--no-jev", action="store_true",
                help="Do not ask Jev; every reproduced finding is marked unconfirmed.",
            )
    return parser


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "paths":
        print(json.dumps(paths(), indent=2))
        return 0
    if args.command == "output-match":
        try:
            answer = _read(args.answer)
            captured = args.output.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            print(f"reviewer_answer: cannot read an input: {exc}", file=sys.stderr)
            return 2
        matched, reason = output_match(answer, args.finding, captured, args.exit_code)
        if matched:
            print(f"{args.finding}: the recorded output would match (advisory; saga decides)")
            return 0
        print(f"{args.finding}: the recorded output would not match: {reason}", file=sys.stderr)
        return 1
    try:
        answer = _read(args.answer)
        items = _read(args.items)
        result = _read(args.result) if args.result else None
    except (OSError, ValueError) as exc:
        print(f"reviewer_answer: cannot read an input: {exc}", file=sys.stderr)
        return 2
    try:
        if args.command == "check":
            problems = check(answer, items, open_search_cap=args.open_search_cap, result=result)
            if problems:
                raise AnswerRefused(problems)
            return 0
        output = to_records(
            answer, items, result or {}, use_jev=not args.no_jev,
            open_search_cap=args.open_search_cap,
        )
    except AnswerRefused as exc:
        for line in exc.problems:
            print(line, file=sys.stderr)
        return 1
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
