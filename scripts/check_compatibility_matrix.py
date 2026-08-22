#!/usr/bin/env python3
"""Validate the ten-client compatibility matrix against its closed schema.

Standard library only, and no network access, matching ``check_repo.py``: this
repository's validators must keep passing when a package index is unreachable,
so the schema is read from disk and interpreted here rather than resolved by a
third-party validator.

The matrix lives inside a Markdown evidence document because the operator reads
prose and a machine reads the record. Both come from one file: the document
embeds the record as its first fenced ``json`` block, and everything the prose
claims is derived from that block.

What this validator exists to enforce, which prose cannot:

* **Coverage is real.** All ten named clients are present, asserted by set
  equality against the canonical list rather than by count, so a substituted or
  renamed client cannot pass as covered. Every client carries all four stage
  results; a row missing a stage fails even when it carries an overall status.
  That is the defect this check closes: a row that stops at its first failure
  and reports one status can otherwise be counted as covered while proving
  nothing about whether the package ever loaded.
* **Coverage is mandatory, passing is not.** ``unsupported`` and ``failed`` are
  accepted outcomes and never fail this check. Recording a failure accurately
  is the deliverable; repairing it is a separate decision the operator owns.
* **The safety boundary holds.** No recorded command may pass ``--confirm``, and
  no recorded invocation of the package's own scripts may name an operation the
  package classifies as mutating. The clients' own dry-run gate stays a second
  line of defence beneath this classification rather than the only one.
* **The public boundary holds.** This repository is public. No command,
  evidence, or reason string may carry an address, a hardware address, a
  site-identifying hostname, or a credential value.
* **A current matrix identifies the tree it assessed.** The record names a file
  count and a tree digest. Checking that the digest is *shaped* like a digest
  proves nothing: a matrix can carry a well-formed digest of a package that no
  longer exists and pass every other check while describing a different
  artifact. So the file count, the tree digest, and the package name and version
  are recomputed from ``plugins/unifi/`` on every run and compared. A matrix
  whose fingerprint does not identify this revision's tree fails.
* **Retiring a matrix is explicit, and cannot be used to dodge the binding.** A
  document may declare itself superseded, which exempts it from the binding and
  requires it to name its successor and the reason. A superseded document whose
  fingerprint *does* still identify the tree fails, because that would be the
  current matrix wearing a label that switches the binding off.

Document status directives
--------------------------

A matrix document declares its role with HTML comment directives placed before
its record::

    <!-- matrix-status: superseded -->
    <!-- superseded-by: 2026-08-22-unifi-compatibility-matrix.md -->
    <!-- superseded-reason: Re-run against the repaired package. -->

``matrix-status`` defaults to ``current`` when absent, so the binding is
fail-closed: a document has to say something to be let off it.

On the public evidence schema: the plan's unit assigns
``schemas/public-evidence.schema.json`` to a different unit, which has not
landed in this repository. Rather than create a file this unit does not declare,
the public-evidence constraints that apply to a matrix — redacted commands,
counts and digests in place of raw output, and no address, hostname, hardware
address, or credential — are carried by the matrix schema itself and enforced by
``check_public_evidence_rules`` below. When the public evidence schema lands,
this validator should defer to it rather than keep a second copy of the rule.

Usage::

    python3 scripts/check_compatibility_matrix.py [document]

Exits 0 when the record is clean, 1 with one line per problem otherwise.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIRECTORY = ROOT / "docs" / "evidence"
DEFAULT_DOCUMENT = EVIDENCE_DIRECTORY / "2026-08-22-unifi-compatibility-matrix.md"
SCHEMA_PATH = ROOT / "schemas" / "compatibility-matrix.schema.json"

#: The package every matrix in this repository assesses. The binding check
#: recomputes this tree's fingerprint and compares it with what the record
#: claims, which is the difference between a digest that is well formed and a
#: digest that identifies the artifact under assessment.
PACKAGE_ROOT = ROOT / "plugins" / "unifi"
PACKAGE_MANIFEST = "plugin.json"

#: Checkout noise that is not part of the package. Excluding it is what makes
#: the fingerprint reproducible: running the test suite leaves ``__pycache__``
#: beside the package's scripts, and a fingerprint that moved when tests ran
#: would be abandoned within a week.
#:
#: The exclusion is by *directory*, never by suffix. A blanket ``.pyc``/``.pyo``
#: suffix exclusion used to sit here too, and it meant this fingerprint could
#: not notice ``skills/unifi-network/scripts/smuggled.pyo`` being added to the
#: assessed tree — a file a fingerprint ignores is a file it cannot bind. The
#: reproducibility argument only ever covered the interpreter's own cache
#: directory, and the directory exclusion below already delivers exactly that.
FINGERPRINT_EXCLUDED_DIRECTORIES = frozenset(
    {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
FINGERPRINT_EXCLUDED_NAMES = frozenset({".DS_Store"})

#: The ten installed clients the assessment must cover. Set equality against
#: this tuple is the coverage assertion; a count is not, because a renamed or
#: substituted client keeps the count intact while losing the coverage.
CANONICAL_CLIENTS = (
    "Claude Code",
    "OpenAI Codex",
    "Cursor Agent",
    "Qwen",
    "Grok",
    "OpenCode",
    "Gemini CLI",
    "Muse",
    "Agy",
    "Hermes",
)

STAGES = ("placement", "discovery", "load", "invocation")
STAGE_RESULTS = ("executed", "blocked", "not-applicable")
STATUSES = (
    "works-directly",
    "works-through-an-adapter",
    "unsupported",
    "failed",
)

#: Operations the package's own skill documentation gates behind ``--confirm``,
#: plus the camera snapshot the discovery path refuses outright. This list is
#: derived from the package rather than invented here, so it stays one
#: classification rather than two that can drift apart.
MUTATING_OPERATIONS = frozenset(
    {
        "adopt",
        "block",
        "create",
        "delete",
        "forget",
        "kick",
        "locate",
        "reboot",
        "restart",
        "snapshot",
        "unblock",
        "update",
        "upgrade",
    }
)

#: The mutating-operation check applies to commands that invoke one of the
#: package's own scripts. Scoping it this way keeps it precise: a client's own
#: subcommand that happens to share a verb with a UniFi operation is not a
#: mutating controller call, and a safety gate that cries wolf gets disabled.
PACKAGE_SCRIPTS = (
    "unifi_network_client.py",
    "unifi_protect_client.py",
    "discover.py",
    "drift.py",
)

CONFIRM_FLAG = "--confirm"

# Sanitization patterns. These run against every command, evidence, and reason
# string in the record.
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Four or more colon-separated hexadecimal groups, or the compressed ``::``
# form. Three groups would also match a clock time such as ``15:13:17``, whose
# digits are all valid hexadecimal, so the threshold is four rather than two.
IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,}[0-9a-fA-F]{1,4}\b")
IPV6_COMPRESSED = re.compile(
    r"(?<![:\w])(?:[0-9a-fA-F]{1,4})?::"
    r"(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?(?![:\w])"
)
MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
MAC_DASHED = re.compile(r"\b[0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5}\b")

#: A domain-shaped token. Only inert example domains are permitted, so a real
#: controller hostname cannot reach the public record by being unremarkable.
DOMAIN = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}\b")
INERT_DOMAIN_SUFFIXES = (
    ".example",
    ".example.com",
    ".example.org",
    ".example.net",
    ".invalid",
    ".test",
    ".localhost",
)
INERT_DOMAINS = ("example.com", "example.org", "example.net", "localhost")

#: Domain-shaped tokens that are filenames, not hosts. A record naturally names
#: files such as ``SKILL.md`` and ``marketplace.json``; those are not hostnames.
FILENAME_SUFFIXES = (
    ".md",
    ".json",
    ".jsonc",
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".sh",
    ".txt",
    ".lock",
    ".sock",
)

#: Dotted identifiers that are names inside this package rather than hosts. The
#: client extension directory the Agent Plugins specification defines is spelled
#: in reverse-domain form and would otherwise read as a hostname.
NON_HOST_DOTTED_TOKENS = ("com.infiquetra.claude",)

CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|token|auth[_-]?token|bearer)\b"
    r"\s*[=:]\s*(?P<value>\S+)"
)
#: An assignment whose value is explicitly redacted is the shape we want, not a
#: leak. Anything else assigned to a credential-ish name is a leak.
REDACTED_VALUES = ("<redacted>", "redacted", "***", "<unset>", "unset", "none", "")


#: Document status directives, written as HTML comments so they survive
#: Markdown rendering without becoming prose a reader has to trust.
DIRECTIVE = re.compile(
    r"^<!--\s*(?P<key>[a-z][a-z0-9-]*)\s*:\s*(?P<value>.*?)\s*-->\s*$",
    re.MULTILINE,
)
STATUS_DIRECTIVE = "matrix-status"
SUPERSEDED_BY_DIRECTIVE = "superseded-by"
SUPERSEDED_REASON_DIRECTIVE = "superseded-reason"
STATUS_CURRENT = "current"
STATUS_SUPERSEDED = "superseded"
DOCUMENT_STATUSES = (STATUS_CURRENT, STATUS_SUPERSEDED)
SUPERSESSION_DIRECTIVES = (SUPERSEDED_BY_DIRECTIVE, SUPERSEDED_REASON_DIRECTIVE)


class MatrixError(Exception):
    """The document could not be read far enough to validate it."""


def load_schema(schema_path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def extract_record(text: str) -> dict[str, Any]:
    """Return the first fenced ``json`` block in the document, parsed.

    The document is the artifact an operator reads; the fenced block is the
    same content in the form a machine checks. Taking the first block rather
    than searching for a marker keeps the document readable and the rule
    obvious to whoever edits it next.
    """
    match = re.search(r"^```json\s*\n(.*?)^```\s*$", text, re.DOTALL | re.MULTILINE)
    if match is None:
        raise MatrixError("no fenced json block found in the evidence document")
    try:
        record = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise MatrixError(f"the fenced json block is not valid JSON: {error}") from error
    if not isinstance(record, dict):
        raise MatrixError("the fenced json block must hold a JSON object")
    return record


def _strip_fenced_blocks(text: str) -> str:
    """The document with every fenced code block blanked, line count preserved.

    A matrix document has to be able to *document* the directive format without
    the documentation being read as a directive. Blanking fenced blocks is what
    makes the example in the prose an example.
    """
    lines = text.split("\n")
    fence = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})")
    kept: list[str] = []
    closing: str | None = None
    for line in lines:
        match = fence.match(line)
        if closing is None:
            if match is not None:
                closing = match.group("marker")[0] * 3
                kept.append("")
                continue
            kept.append(line)
            continue
        kept.append("")
        if match is not None and match.group("marker").startswith(closing):
            closing = None
    return "\n".join(kept)


def read_directives(text: str) -> dict[str, str]:
    """Every ``<!-- key: value -->`` directive in the document, keyed by name.

    Directives inside a fenced code block are examples, not declarations, and
    are ignored. A later directive with the same key overwrites an earlier one,
    so the document cannot carry two different answers to the same question.
    """
    stripped = _strip_fenced_blocks(text)
    return {match.group("key"): match.group("value") for match in DIRECTIVE.finditer(stripped)}


def _fingerprint_includes(path: Path, package_root: Path) -> bool:
    if path.name in FINGERPRINT_EXCLUDED_NAMES:
        return False
    relative = path.relative_to(package_root)
    return not any(part in FINGERPRINT_EXCLUDED_DIRECTORIES for part in relative.parts)


def package_fingerprint(package_root: Path = PACKAGE_ROOT) -> tuple[int, str]:
    """The assessed tree's ``(file_count, tree_sha256)``, recomputed from disk.

    The digest is defined here rather than inherited from a tool, because a
    third party has to be able to recompute it from the published bytes:

    1. Walk the package root and keep every regular file, excluding checkout
       noise: anything under a tool cache directory (``__pycache__``, ``.git``,
       ``.mypy_cache``, ``.pytest_cache``, ``.ruff_cache``) and ``.DS_Store``.
       Nothing is excluded for its suffix alone, so compiled bytecode outside
       those directories counts as a package file and moves this digest.
    2. Sort the surviving paths by their POSIX form, relative to the root.
    3. For each, emit ``"<sha256 of the file's bytes>  <relative path>\\n"``.
    4. The tree digest is the SHA-256 of those lines concatenated, UTF-8.

    Naming each path inside the hashed text is deliberate: hashing the file
    digests alone would leave a pure rename invisible, and a rename is exactly
    the kind of drift a binding is supposed to catch.
    """
    if not package_root.is_dir():
        raise MatrixError(f"{package_root}: the assessed package directory does not exist")
    files = sorted(
        (path for path in package_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(package_root).as_posix(),
    )
    lines: list[str] = []
    for path in files:
        if not _fingerprint_includes(path, package_root):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(package_root).as_posix()}\n")
    tree = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    return len(lines), tree


def package_identity(package_root: Path = PACKAGE_ROOT) -> tuple[str, str]:
    """The assessed package's ``(name, version)``, read from its manifest."""
    manifest_path = package_root / PACKAGE_MANIFEST
    if not manifest_path.is_file():
        raise MatrixError(f"{manifest_path}: the assessed package has no manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise MatrixError(f"{manifest_path}: not valid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise MatrixError(f"{manifest_path}: the manifest must hold a JSON object")
    name = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise MatrixError(f"{manifest_path}: the manifest names no package name and version")
    return name, version


def check_package_binding(
    record: dict[str, Any],
    package_root: Path = PACKAGE_ROOT,
) -> list[str]:
    """The record's package fingerprint must identify the tree on disk.

    This is the check whose absence let a matrix describe a package that no
    longer existed: every other rule here was satisfied by a well-formed digest
    of the wrong artifact.
    """
    package = record.get("package")
    if not isinstance(package, dict):
        return ["$.package: missing or not an object, so nothing binds the record to a tree"]

    try:
        file_count, tree_sha256 = package_fingerprint(package_root)
        name, version = package_identity(package_root)
    except MatrixError as error:
        return [f"$.package: {error}"]

    problems: list[str] = []
    recorded_count = package.get("file_count")
    if recorded_count != file_count:
        problems.append(
            f"$.package.file_count: the record says {recorded_count!r} but "
            f"{package_root.name}/ holds {file_count} files; the assessment describes a "
            "package that is not the one in this revision, so it must be re-run rather "
            "than renumbered"
        )
    recorded_tree = package.get("tree_sha256")
    if recorded_tree != tree_sha256:
        problems.append(
            f"$.package.tree_sha256: the record says {recorded_tree!r} but "
            f"{package_root.name}/ fingerprints to {tree_sha256!r}; a digest that is merely "
            "well formed identifies nothing, so this matrix does not describe the shipped tree"
        )
    recorded_name = package.get("name")
    if recorded_name != name:
        problems.append(
            f"$.package.name: the record says {recorded_name!r} but the package manifest "
            f"names {name!r}"
        )
    recorded_version = package.get("version")
    if recorded_version != version:
        problems.append(
            f"$.package.version: the record says {recorded_version!r} but the package "
            f"manifest declares {version!r}"
        )
    return problems


def check_document_status(
    text: str,
    record: dict[str, Any],
    document: Path,
    package_root: Path = PACKAGE_ROOT,
) -> list[str]:
    """Bind a current matrix to the tree; hold a superseded one to its notice.

    Supersession is the only exemption from the binding, so it carries its own
    obligations: name the successor, say why, and prove the exemption is not
    being used to switch the binding off for the live matrix.
    """
    directives = read_directives(text)
    status = directives.get(STATUS_DIRECTIVE, STATUS_CURRENT)
    if status not in DOCUMENT_STATUSES:
        return [
            f"{document.name}: {STATUS_DIRECTIVE} is {status!r}, which is neither "
            f"{STATUS_CURRENT!r} nor {STATUS_SUPERSEDED!r}"
        ]

    problems: list[str] = []
    if status == STATUS_CURRENT:
        for directive in SUPERSESSION_DIRECTIVES:
            if directive in directives:
                problems.append(
                    f"{document.name}: carries {directive!r} while its {STATUS_DIRECTIVE} is "
                    f"{STATUS_CURRENT!r}; a document is either the current matrix or a "
                    "superseded one, never both"
                )
        problems.extend(check_package_binding(record, package_root))
        return problems

    successor = directives.get(SUPERSEDED_BY_DIRECTIVE, "").strip()
    if not successor:
        problems.append(
            f"{document.name}: declares itself superseded but names no {SUPERSEDED_BY_DIRECTIVE}; "
            "superseded evidence that does not say what replaced it is a dead end"
        )
    elif ".." in Path(successor).parts or Path(successor).is_absolute():
        problems.append(
            f"{document.name}: {SUPERSEDED_BY_DIRECTIVE} {successor!r} must be a plain relative "
            "name inside the evidence directory"
        )
    else:
        target = document.parent / successor
        if target.resolve() == document.resolve():
            problems.append(f"{document.name}: names itself as its own successor")
        elif not target.is_file():
            problems.append(
                f"{document.name}: {SUPERSEDED_BY_DIRECTIVE} names {successor!r}, which does "
                "not exist"
            )
        else:
            successor_status = read_directives(target.read_text(encoding="utf-8")).get(
                STATUS_DIRECTIVE, STATUS_CURRENT
            )
            if successor_status != STATUS_CURRENT:
                problems.append(
                    f"{document.name}: {SUPERSEDED_BY_DIRECTIVE} names {successor!r}, which is "
                    f"itself {successor_status!r}; a supersession chain has to end at a current "
                    "matrix"
                )

    if not directives.get(SUPERSEDED_REASON_DIRECTIVE, "").strip():
        problems.append(
            f"{document.name}: declares itself superseded but records no "
            f"{SUPERSEDED_REASON_DIRECTIVE}"
        )

    if not check_package_binding(record, package_root):
        problems.append(
            f"{document.name}: is marked {STATUS_SUPERSEDED!r} yet its fingerprint still "
            "identifies the package in this revision; supersession exempts a document from the "
            "binding, so marking the live matrix superseded would switch that binding off"
        )
    return problems


def _type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return True


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    """Follow a local ``$ref`` one level, which is all this schema uses."""
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema
    if not reference.startswith("#/"):
        raise MatrixError(f"unsupported non-local $ref {reference!r}")
    node: Any = root
    for part in reference[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise MatrixError(f"unresolvable $ref {reference!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise MatrixError(f"$ref {reference!r} does not name a schema object")
    return node


def validate_against_schema(
    value: object,
    schema: dict[str, Any],
    root: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Interpret the subset of JSON Schema this repository's schemas use.

    Supported: ``type``, ``const``, ``enum``, ``pattern``, ``minLength``,
    ``minimum``, ``minItems``, ``maxItems``, ``required``, ``properties``,
    ``additionalProperties: false``, ``items``, ``allOf``, ``if``/``then``, and
    local ``$ref``. That is deliberately the whole vocabulary: a validator that
    silently ignores a keyword it does not implement turns a closed schema back
    into an open one.
    """
    schema = _resolve(schema, root)
    problems: list[str] = []

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _type_matches(value, expected_type):
        return [f"{path}: expected {expected_type}, found {type(value).__name__}"]

    if "const" in schema and value != schema["const"]:
        problems.append(f"{path}: expected the constant {schema['const']!r}, found {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']!r}")

    if isinstance(value, str):
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            problems.append(f"{path}: {value!r} does not match {pattern!r}")
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            problems.append(f"{path}: shorter than the required {minimum_length} characters")

    if isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            problems.append(f"{path}: {value} is below the minimum {minimum}")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            problems.append(f"{path}: holds {len(value)} items, fewer than {minimum_items}")
        maximum_items = schema.get("maxItems")
        if isinstance(maximum_items, int) and len(value) > maximum_items:
            problems.append(f"{path}: holds {len(value)} items, more than {maximum_items}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                problems.extend(
                    validate_against_schema(item, item_schema, root, f"{path}[{index}]")
                )

    if isinstance(value, dict):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        for field in schema.get("required", []):
            if field not in value:
                problems.append(f"{path}: missing the required field {field!r}")
        if schema.get("additionalProperties") is False:
            for field in value:
                if field not in properties:
                    problems.append(
                        f"{path}: unknown field {field!r}; this schema is closed, so an "
                        "unrecognized field cannot acquire meaning by being ignored"
                    )
        for field, child_schema in properties.items():
            if field in value and isinstance(child_schema, dict):
                problems.extend(
                    validate_against_schema(value[field], child_schema, root, f"{path}.{field}")
                )

    for branch in schema.get("allOf", []):
        if not isinstance(branch, dict):
            continue
        condition = branch.get("if")
        consequence = branch.get("then")
        if isinstance(condition, dict) and isinstance(consequence, dict):
            if not validate_against_schema(value, condition, root, path):
                problems.extend(validate_against_schema(value, consequence, root, path))
        else:
            problems.extend(validate_against_schema(value, branch, root, path))

    return problems


def check_coverage(record: dict[str, Any]) -> list[str]:
    """Every named client present, every stage recorded, exactly one status."""
    problems: list[str] = []
    clients = record.get("clients")
    if not isinstance(clients, list):
        return ["$.clients: missing or not an array"]

    names = [client.get("name") for client in clients if isinstance(client, dict)]
    found = set(names)
    expected = set(CANONICAL_CLIENTS)
    for missing in sorted(expected - found):
        problems.append(f"$.clients: {missing!r} is named in the assessment but has no row")
    for extra in sorted(found - expected):
        problems.append(
            f"$.clients: {extra!r} is not one of the ten named clients; a substituted or "
            "renamed client cannot pass as covered"
        )
    duplicates = sorted({name for name in names if names.count(name) > 1 and name is not None})
    for duplicate in duplicates:
        problems.append(f"$.clients: {duplicate!r} appears more than once")

    for index, client in enumerate(clients):
        if not isinstance(client, dict):
            problems.append(f"$.clients[{index}]: expected an object")
            continue
        label = client.get("name", f"index {index}")
        stages = client.get("stages")
        if not isinstance(stages, dict):
            problems.append(f"{label}: has no stage results at all")
            continue
        for stage in STAGES:
            if stage not in stages:
                problems.append(
                    f"{label}: the {stage} stage is absent; a row missing a stage fails even "
                    "when it carries an overall status"
                )
                continue
            problems.extend(_check_stage(label, stage, stages[stage]))
        status = client.get("status")
        if status not in STATUSES:
            problems.append(f"{label}: {status!r} is not one of the four permitted statuses")
        if not str(client.get("reason") or "").strip():
            problems.append(f"{label}: carries no concrete reason for its status")
    return problems


def _check_stage(label: str, stage: str, value: object) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label}/{stage}: expected an object"]
    problems: list[str] = []
    result = value.get("result")
    if result not in STAGE_RESULTS:
        problems.append(f"{label}/{stage}: {result!r} is not executed, blocked, or not-applicable")
        return problems
    if result == "executed":
        if not str(value.get("command") or "").strip():
            problems.append(f"{label}/{stage}: executed but records no command")
        if not str(value.get("evidence") or "").strip():
            problems.append(f"{label}/{stage}: executed but records no evidence")
    else:
        if not str(value.get("reason") or "").strip():
            problems.append(f"{label}/{stage}: {result} but names no reason")
    return problems


def _recorded_commands(record: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Every recorded command as ``(client, stage, command)``."""
    found: list[tuple[str, str, str]] = []
    for client in record.get("clients", []):
        if not isinstance(client, dict):
            continue
        label = str(client.get("name", "?"))
        stages = client.get("stages")
        if not isinstance(stages, dict):
            continue
        for stage, value in stages.items():
            if isinstance(value, dict) and isinstance(value.get("command"), str):
                found.append((label, str(stage), value["command"]))
    return found


def check_safety_rules(record: dict[str, Any]) -> list[str]:
    """No confirmed command anywhere, no mutating package operation recorded."""
    problems: list[str] = []
    for label, stage, command in _recorded_commands(record):
        if CONFIRM_FLAG in command:
            problems.append(
                f"{label}/{stage}: the recorded command passes {CONFIRM_FLAG}; no test path "
                "may confirm a write, so the clients' own dry-run gate stays a second line "
                "of defence rather than the only one"
            )
        if not any(script in command for script in PACKAGE_SCRIPTS):
            continue
        tokens = {token.strip("'\"") for token in re.split(r"[\s=]+", command)}
        for operation in sorted(tokens & MUTATING_OPERATIONS):
            problems.append(
                f"{label}/{stage}: the recorded invocation names {operation!r}, which the "
                "package classifies as a mutating operation; live invocation is limited to "
                "read-only operations"
            )
    return problems


def _record_strings(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Every ``(path, string)`` in the record that a reader could leak through."""
    found: list[tuple[str, str]] = []

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            found.append((path, node))

    walk(record, "$")
    return found


def _is_inert_domain(token: str) -> bool:
    lowered = token.lower()
    if lowered in INERT_DOMAINS or lowered in NON_HOST_DOTTED_TOKENS:
        return True
    if any(lowered.endswith(suffix) for suffix in INERT_DOMAIN_SUFFIXES):
        return True
    return any(lowered.endswith(suffix) for suffix in FILENAME_SUFFIXES)


def check_public_evidence_rules(record: dict[str, Any]) -> list[str]:
    """No address, hardware address, hostname, or credential in the record.

    This repository is public and neither client filters nor redacts controller
    responses, so persistence of raw read output to a committable path is
    default-deny. What survives into the record is field names, counts, pass or
    fail comparisons, and digests.
    """
    problems: list[str] = []
    for path, value in _record_strings(record):
        if path.startswith("$.package.tree_sha256"):
            continue
        for pattern, kind in (
            (IPV4, "an address"),
            (IPV6, "an address"),
            (IPV6_COMPRESSED, "an address"),
            (MAC, "a hardware address"),
            (MAC_DASHED, "a hardware address"),
        ):
            match = pattern.search(value)
            if match is not None:
                problems.append(
                    f"{path}: contains {kind} ({match.group(0)!r}); the public record carries "
                    "counts and digests, never site-identifying values"
                )
        for match in DOMAIN.finditer(value):
            token = match.group(0)
            if _is_inert_domain(token):
                continue
            problems.append(
                f"{path}: contains the hostname {token!r}; only inert example domains may "
                "appear in a public evidence record"
            )
        credential = CREDENTIAL_ASSIGNMENT.search(value)
        if credential is not None:
            assigned = credential.group("value").strip("'\"").lower()
            if assigned not in REDACTED_VALUES:
                problems.append(
                    f"{path}: assigns a value to a credential field; a credential value is "
                    "never printed, logged, or persisted into an artifact"
                )
    return problems


def check_matrix(
    document: Path = DEFAULT_DOCUMENT,
    package_root: Path = PACKAGE_ROOT,
) -> list[str]:
    """Every problem with the matrix, or an empty list when it is clean."""
    if not document.is_file():
        return [f"{document}: the evidence document does not exist"]
    text = document.read_text(encoding="utf-8")
    try:
        record = extract_record(text)
    except MatrixError as error:
        return [f"{document}: {error}"]

    schema = load_schema()
    problems = validate_against_schema(record, schema, schema)
    problems.extend(check_coverage(record))
    problems.extend(check_safety_rules(record))
    problems.extend(check_public_evidence_rules(record))
    problems.extend(check_document_status(text, record, document, package_root))
    return problems


def is_matrix_document(text: str) -> bool:
    """Whether a document embeds a compatibility-matrix record.

    Other evidence documents live in the same directory and embed records of
    their own, so membership is decided by the record's shape rather than by
    the file's name.
    """
    try:
        record = extract_record(text)
    except MatrixError:
        return False
    return isinstance(record.get("package"), dict) and isinstance(record.get("clients"), list)


def matrix_documents(directory: Path = EVIDENCE_DIRECTORY) -> list[Path]:
    """Every matrix document in the evidence directory, current or superseded.

    A superseded matrix stays under validation. Retiring a document withdraws
    its claim about the current tree; it does not withdraw the public-evidence
    and coverage rules it was published under.
    """
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if is_matrix_document(text):
            found.append(path)
    return found


def summarize(record: dict[str, Any]) -> str:
    """The counts the unit's verification names, derived rather than asserted."""
    clients = [client for client in record.get("clients", []) if isinstance(client, dict)]
    stage_results = [
        stage.get("result")
        for client in clients
        for stage in (client.get("stages") or {}).values()
        if isinstance(stage, dict)
    ]
    statuses = [client.get("status") for client in clients]
    lines = [
        f"clients: {len(clients)}",
        f"stage results: {len(stage_results)}"
        f" (executed {stage_results.count('executed')},"
        f" blocked {stage_results.count('blocked')},"
        f" not-applicable {stage_results.count('not-applicable')})",
        f"overall statuses: {len(statuses)}",
    ]
    for status in STATUSES:
        lines.append(f"  {status}: {statuses.count(status)}")
    return "\n".join(lines)


FINGERPRINT_FLAG = "--print-fingerprint"


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    if FINGERPRINT_FLAG in arguments:
        # Read-only on purpose. There is no flag that rewrites the record from
        # the tree, because refreshing the numbers without re-running the
        # assessment is exactly the failure this binding exists to catch: it
        # would make a stale matrix pass by editing the evidence to match.
        try:
            file_count, tree_sha256 = package_fingerprint()
            name, version = package_identity()
        except MatrixError as error:
            print(str(error))
            return 1
        print(f"name: {name}")
        print(f"version: {version}")
        print(f"file_count: {file_count}")
        print(f"tree_sha256: {tree_sha256}")
        return 0

    documents = [Path(argument) for argument in arguments] or matrix_documents()
    if not documents:
        print(f"{EVIDENCE_DIRECTORY}: no compatibility matrix document found")
        return 1

    failed = 0
    for document in documents:
        problems = check_matrix(document)
        if problems:
            failed += 1
            print(f"{document}:")
            for problem in problems:
                print(f"  {problem}")
            print(f"\n{len(problems)} problem(s) found in {document}.\n")
            continue
        status = read_directives(document.read_text(encoding="utf-8")).get(
            STATUS_DIRECTIVE, STATUS_CURRENT
        )
        print(f"{document.name} ({status}):")
        print(summarize(extract_record(document.read_text(encoding="utf-8"))))
        print()
    if failed:
        return 1
    print("Compatibility matrix validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
