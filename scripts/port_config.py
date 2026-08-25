#!/usr/bin/env python3
"""The per-package port descriptor: one authority for what a package is.

Three tools in this repository used to answer "which package?" with a constant
compiled into their own source. `scripts/sync_vendor_source.py` named
`plugins/unifi` and carried the UniFi custody table; `scripts/check_compatibility_matrix.py`
named the same tree again and carried the UniFi script and operation lists; and
the client assessment existed only as a method written down in prose. Porting a
second plugin meant editing all three, and the pilot's own runbook had to tell
the next porter which constants to reach into.

A port descriptor replaces those constants with data. One JSON file per package
under `ports/`, named for the package, holding everything package-specific the
tooling needs:

* **identity** -- the package name and the tree it lives in, which is what binds
  a compatibility matrix to an artifact rather than to a well-formed digest;
* **source** -- the upstream repository, the path inside it, and the client
  extension directory the Claude adapter lands under;
* **custody** -- every upstream path classified exactly once, which is the table
  `classify_source_tree` refuses to run without;
* **assessment** -- the package's own entrypoint scripts and the operations it
  classifies as mutating, which is what keeps the matrix safety rule precise
  rather than a keyword search over every command;
* **provenance** -- the manifest notes and the reason each dropped path is
  dropped, so a derived tree explains itself in its own terms rather than in
  the first package's.

Validation lives here and nowhere else. There is no second schema file stating
the same shape, because a rule written twice is a rule that can disagree with
itself: this module is the authority, and `tests/test_port_config.py` derives
its expectations from it rather than restating them.

Standard library only, and no network access, matching the rest of this
repository's tooling.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


#: The directory holding one descriptor per portable package. Deliberately
#: outside `plugins/`: a compatibility matrix binds to a fingerprint of the
#: package tree, so a descriptor stored *inside* the tree it describes would
#: move that fingerprint every time the tooling's own configuration changed and
#: invalidate assessment evidence that is still perfectly true.
CONFIG_DIRECTORY_NAME = "ports"

CONFIG_SUFFIX = ".json"

#: Bumped when a descriptor field is added, removed, or reinterpreted. A
#: descriptor that does not carry the version this module understands is
#: refused rather than read with assumed defaults.
#:
#: Version 2 closes every object against unknown keys and requires the
#: load-bearing safety declarations to be stated rather than defaulted. Version 1
#: is not accepted: a descriptor written against it has exactly the shape this
#: change exists to refuse, so reading one leniently would keep the hole open for
#: whichever package had not been migrated yet.
#:
#: Version 3 reinterprets `custody.entrypoint_transforms`: every entry is an
#: object carrying the path and the name of the transform rule that rewrites
#: it, where version 2 carried bare path strings and the synchronization tool
#: applied its one rewriting rule to every one of them. With more than one rule
#: in play, selection has to be stated per path or it becomes a script-internal
#: registry constant -- the custody violation AGENTS.md names. Version 2 is not
#: accepted: both committed descriptors migrated in the same commit that bumped
#: the version, and an entry with no rule name is refused for the same reason a
#: bare string is -- reading either with an assumed default rule would select a
#: rewrite nobody named.
SCHEMA_VERSION = "3"

#: Package roots live under this directory. Enforced rather than assumed: the
#: descriptor is the input that decides which tree a synchronization overwrites
#: and which tree a matrix fingerprints, so a descriptor pointing anywhere else
#: is refused before either tool acts on it.
PACKAGE_PARENT = "plugins"

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "package",
    "package_root",
    "source",
    "custody",
    "assessment",
)

#: Every key the top level may carry. Closed, like every other object here: an
#: unknown key is a typo, and a typo in a descriptor is a setting that silently
#: did not take effect.
TOP_LEVEL_FIELDS = REQUIRED_TOP_LEVEL + ("package_manifest", "provenance")

REQUIRED_SOURCE_FIELDS = ("repository", "package_path")

SOURCE_FIELDS = REQUIRED_SOURCE_FIELDS + ("manifest_path", "client_extension_dir")

PROVENANCE_FIELDS = ("notes", "dropped_reason")

#: The assessment settings that carry a safety decision. Each one must be stated
#: rather than defaulted, because every one of them fails *open* when absent:
#:
#: * `credential_prefixes` empty means no variable is stripped from an assessment
#:   subprocess, so the operator's real credentials reach every client;
#: * `package_scripts` empty means the mutating-operation rule matches no command,
#:   so every recorded or about-to-run command passes the safety check;
#: * `mutating_operations` empty means the same rule has no verbs to match;
#: * `entrypoints` empty means the assessment invokes nothing and a package can
#:   be called compatible without any of its executables having run.
#:
#: A package for which one of these is genuinely empty says so in
#: `declared_none`, which is a decision a reader can see and a typo cannot
#: produce.
SAFETY_FIELDS = (
    "credential_prefixes",
    "package_scripts",
    "mutating_operations",
    "entrypoints",
)

ASSESSMENT_FIELDS = SAFETY_FIELDS + ("skill_units", "declared_none")

#: The five custody classes. Every upstream path a synchronization sees has to
#: fall in exactly one of them; the names are the descriptor's field names, and
#: `sync_vendor_source.classify_source_tree` reads them from here rather than
#: listing them again.
CUSTODY_FIELDS = (
    "byte_copies",
    "entrypoint_transforms",
    "client_byte_copies",
    "superseded_by_target_owned",
    "dropped_from_source",
)

#: The fields one `entrypoint_transforms` entry carries (schema version 3).
#: Closed like every other object here. `rule` names the transform the
#: synchronization tool applies to `path`; the tool refuses a name it does not
#: implement, so a typo in the entry fails at synchronization rather than
#: selecting a rewrite by default.
ENTRYPOINT_TRANSFORM_ENTRY_FIELDS = ("path", "rule")


class PortConfigError(Exception):
    """A descriptor could not be read, or could not be trusted once read."""


def config_directory(root: Path) -> Path:
    return root / CONFIG_DIRECTORY_NAME


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PortConfigError(message)


def _closed(document: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    """Refuse any key the contract does not define.

    Every object in a descriptor is closed. An unknown key is almost always a
    typo, and a typo in this file is not a syntax error -- it is a setting that
    silently did not take effect. The cost of that is asymmetric: a misspelled
    `credential_prefix` reads as "strip nothing", and the run that finds out is
    the one that hands the operator's real credentials to ten clients.
    """
    unknown = sorted(set(document) - set(allowed))
    _require(
        not unknown,
        f"{where}: unknown field(s): {', '.join(unknown)}. Every object in a port descriptor "
        f"is closed; the fields here are {', '.join(allowed)}",
    )


def _string_tuple(document: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    """A list-of-strings field, defaulting to empty, with every member checked.

    Absent means empty on purpose: a package with no dropped paths should not
    have to write ``"dropped_from_source": []`` to say so. Present-but-wrong is
    always an error, so a typo cannot read as an omission.
    """
    if key not in document:
        return ()
    value = document[key]
    _require(isinstance(value, list), f"{where}.{key} must be a list of strings")
    for item in value:
        _require(
            isinstance(item, str) and item.strip() != "",
            f"{where}.{key} holds a value that is not a non-empty string: {item!r}",
        )
    return tuple(value)


def _relative_path(value: str, where: str) -> str:
    """A package-relative POSIX path, refused if it could escape its package.

    The same rule `sync_vendor_source.resolve_managed_path` applies to a
    manifest it reads back, applied here to the descriptor that produced it. A
    descriptor is checked-in source rather than generated output, but it is
    still the input that decides which paths a synchronization writes and
    deletes, and a path rule that only guards the second half of that round
    trip guards nothing.
    """
    candidate = Path(value)
    _require(
        not candidate.is_absolute() and ".." not in candidate.parts,
        f"{where} must be a relative path with no parent-directory component: {value!r}",
    )
    return value


def _entrypoint_transform_entries(
    document: dict[str, Any], where: str
) -> tuple[tuple[str, ...], dict[str, str]]:
    """The schema-3 `entrypoint_transforms` entries: paths, and the rule each names.

    Absent means empty, like every other custody class. Present, every entry is
    an object stating both fields: a bare path string is the version-2 shape the
    version bump exists to replace, and an entry with no rule name would select
    a rewrite by assumed default -- the setting-that-silently-did-not-take-effect
    failure every closed object here prevents. The rule name is validated as a
    name only; which names exist is the synchronization tool's registry to say,
    and it refuses one it does not implement.
    """
    if "entrypoint_transforms" not in document:
        return (), {}
    value = document["entrypoint_transforms"]
    _require(
        isinstance(value, list), f"{where}.entrypoint_transforms must be a list of entries"
    )
    assert isinstance(value, list)
    paths: list[str] = []
    rules: dict[str, str] = {}
    for index, entry in enumerate(value):
        entry_where = f"{where}.entrypoint_transforms[{index}]"
        _require(
            isinstance(entry, dict),
            f"{entry_where} must be an object with the fields "
            f"{', '.join(ENTRYPOINT_TRANSFORM_ENTRY_FIELDS)}; a bare path string is the "
            f"schema-2 shape, and schema {SCHEMA_VERSION} names the transform rule every "
            "rewritten path carries",
        )
        assert isinstance(entry, dict)
        _closed(entry, ENTRYPOINT_TRANSFORM_ENTRY_FIELDS, entry_where)
        path = entry.get("path")
        rule = entry.get("rule")
        _require(
            isinstance(path, str) and path.strip() != "",
            f"{entry_where} is missing a non-empty path",
        )
        assert isinstance(path, str)
        _require(
            isinstance(rule, str) and rule.strip() != "",
            f"{entry_where} is missing a non-empty rule name: schema {SCHEMA_VERSION} "
            "selects the transform rule explicitly, so an entry without one would be "
            "read with an assumed default",
        )
        assert isinstance(rule, str)
        _relative_path(path, f"{entry_where}.path")
        paths.append(path)
        rules[path] = rule
    return tuple(paths), rules


class SourceConfig:
    """Where the derived tree comes from."""

    __slots__ = ("repository", "package_path", "manifest_path", "client_extension_dir")

    def __init__(
        self,
        repository: str,
        package_path: str,
        manifest_path: str | None,
        client_extension_dir: str | None,
    ) -> None:
        self.repository = repository
        self.package_path = package_path
        self.manifest_path = manifest_path
        self.client_extension_dir = client_extension_dir


class CustodyTable:
    """Every upstream path, classified exactly once.

    `entrypoint_transforms` stays a tuple of path strings -- that is what the
    classification, the assessment, and the regression tests iterate -- and the
    per-path rule name each schema-3 descriptor entry carries rides beside it
    in `entrypoint_rules`, complete for every path or the validator refused the
    descriptor.
    """

    __slots__ = CUSTODY_FIELDS + ("entrypoint_rules",)

    def __init__(
        self,
        byte_copies: tuple[str, ...],
        entrypoint_transforms: tuple[str, ...],
        client_byte_copies: tuple[str, ...],
        superseded_by_target_owned: tuple[str, ...],
        dropped_from_source: tuple[str, ...],
        *,
        entrypoint_rules: Mapping[str, str] | None = None,
    ) -> None:
        self.byte_copies = byte_copies
        self.entrypoint_transforms = entrypoint_transforms
        self.client_byte_copies = client_byte_copies
        self.superseded_by_target_owned = superseded_by_target_owned
        self.dropped_from_source = dropped_from_source
        #: The transform rule each entrypoint-transform path is rewritten by,
        #: keyed by path. Schema version 3 states it per entry; a table built
        #: without one (the pre-version-3 tests) carries no selection at all,
        #: which the synchronization tool reports as an unnamed rule rather
        #: than defaulting.
        self.entrypoint_rules = dict(entrypoint_rules) if entrypoint_rules else {}

    def declared(self) -> tuple[str, ...]:
        """Every upstream-relative path the table names, in declaration order.

        Order is preserved rather than sorted because the caller counts
        duplicates across the whole table, and a set cannot say a path was
        claimed by two different custody classes.
        """
        return tuple(name for field in CUSTODY_FIELDS for name in getattr(self, field))


class AssessmentConfig:
    """What a client assessment needs to know about this package.

    Both fields exist to keep the matrix safety rule precise. `package_scripts`
    scopes the mutating-operation check to commands that actually invoke this
    package, so a client's own subcommand sharing a verb is not read as a
    controller call. `mutating_operations` is the package's own classification
    of what writes, carried here rather than re-derived, so the rule and the
    package cannot drift into two different answers.
    """

    __slots__ = (
        "package_scripts",
        "mutating_operations",
        "credential_prefixes",
        "skill_units",
        "entrypoints",
        "declared_none",
    )

    def __init__(
        self,
        package_scripts: tuple[str, ...],
        mutating_operations: frozenset[str],
        credential_prefixes: tuple[str, ...],
        skill_units: tuple[str, ...],
        entrypoints: tuple[str, ...] = (),
        declared_none: tuple[str, ...] = (),
    ) -> None:
        self.package_scripts = package_scripts
        self.mutating_operations = mutating_operations
        self.credential_prefixes = credential_prefixes
        self.skill_units = skill_units
        #: The package's executable entrypoints, package-relative. Declared here
        #: rather than read from a custody class: what makes a file executable is
        #: that the package says it is, not how its bytes were obtained. A
        #: package whose entrypoint is an upstream byte copy or target-owned
        #: source is assessed on it exactly like a transformed one.
        self.entrypoints = entrypoints
        #: Safety fields this package deliberately leaves empty. Naming one here
        #: is what separates "this package has no mutating operations" from
        #: "somebody misspelled the key".
        self.declared_none = declared_none


class PortConfig:
    """One package's port descriptor, validated."""

    __slots__ = (
        "name",
        "package_root",
        "package_manifest",
        "source",
        "custody",
        "assessment",
        "notes",
        "dropped_reason",
        "root",
        "path",
    )

    def __init__(
        self,
        *,
        name: str,
        package_root: str,
        package_manifest: str,
        source: SourceConfig,
        custody: CustodyTable,
        assessment: AssessmentConfig,
        notes: tuple[str, ...],
        dropped_reason: str,
        root: Path,
        path: Path,
    ) -> None:
        self.name = name
        self.package_root = package_root
        self.package_manifest = package_manifest
        self.source = source
        self.custody = custody
        self.assessment = assessment
        self.notes = notes
        self.dropped_reason = dropped_reason
        self.root = root
        self.path = path

    @property
    def package_directory(self) -> Path:
        """The package tree on disk: the root a matrix fingerprints and a sync writes."""
        return self.root / self.package_root

    @property
    def manifest_path(self) -> Path:
        return self.package_directory / self.package_manifest

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"PortConfig(name={self.name!r}, package_root={self.package_root!r})"


def parse(document: object, *, root: Path, path: Path) -> PortConfig:
    """Validate a parsed descriptor and return it, or raise `PortConfigError`.

    Separate from `load` so a caller can validate a descriptor it constructed --
    which is what lets the tests build the class of malformed shapes without
    writing ten files to disk.
    """
    where = path.name
    _require(isinstance(document, dict), f"{where}: a port descriptor must be a JSON object")
    assert isinstance(document, dict)

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in document]
    _require(not missing, f"{where}: missing required field(s): {', '.join(missing)}")
    _closed(document, TOP_LEVEL_FIELDS, where)

    version = document["schema_version"]
    _require(
        version == SCHEMA_VERSION,
        f"{where}: schema_version is {version!r}, but this tooling reads {SCHEMA_VERSION!r}; "
        "a descriptor is refused rather than read with assumed defaults",
    )

    name = document["package"]
    _require(
        isinstance(name, str) and name.strip() != "",
        f"{where}: package must be a non-empty string",
    )
    assert isinstance(name, str)
    _require(
        path.stem == name,
        f"{where}: names package {name!r}, so the descriptor must be called "
        f"{name}{CONFIG_SUFFIX}; a descriptor whose filename and package disagree makes "
        "the two ways of naming a package resolve to different things",
    )

    package_root = document["package_root"]
    _require(
        isinstance(package_root, str) and package_root.strip() != "",
        f"{where}: package_root must be a non-empty string",
    )
    assert isinstance(package_root, str)
    _relative_path(package_root, f"{where}.package_root")
    parts = Path(package_root).parts
    _require(
        len(parts) == 2 and parts[0] == PACKAGE_PARENT,
        f"{where}: package_root must be {PACKAGE_PARENT}/<package>, not {package_root!r}; "
        "this descriptor decides which tree a synchronization overwrites",
    )
    _require(
        parts[1] == name,
        f"{where}: package_root {package_root!r} does not end in the package name {name!r}",
    )

    manifest = document.get("package_manifest", "plugin.json")
    _require(
        isinstance(manifest, str) and manifest.strip() != "",
        f"{where}: package_manifest must be a non-empty string",
    )
    assert isinstance(manifest, str)
    _relative_path(manifest, f"{where}.package_manifest")

    source_document = document["source"]
    _require(isinstance(source_document, dict), f"{where}.source must be an object")
    assert isinstance(source_document, dict)
    source_missing = [key for key in REQUIRED_SOURCE_FIELDS if key not in source_document]
    _require(
        not source_missing,
        f"{where}.source: missing required field(s): {', '.join(source_missing)}",
    )
    _closed(source_document, SOURCE_FIELDS, f"{where}.source")
    for key in REQUIRED_SOURCE_FIELDS:
        _require(
            isinstance(source_document[key], str) and source_document[key].strip() != "",
            f"{where}.source.{key} must be a non-empty string",
        )
    _relative_path(source_document["package_path"], f"{where}.source.package_path")

    manifest_path = source_document.get("manifest_path")
    if manifest_path is not None:
        _require(
            isinstance(manifest_path, str) and manifest_path.strip() != "",
            f"{where}.source.manifest_path must be a non-empty string when present",
        )
        _relative_path(manifest_path, f"{where}.source.manifest_path")

    extension_dir = source_document.get("client_extension_dir")
    if extension_dir is not None:
        _require(
            isinstance(extension_dir, str) and extension_dir.strip() != "",
            f"{where}.source.client_extension_dir must be a non-empty string when present",
        )
        _require(
            "/" not in extension_dir and extension_dir not in (".", ".."),
            f"{where}.source.client_extension_dir must be a single directory name: "
            f"{extension_dir!r}",
        )

    custody_document = document["custody"]
    _require(isinstance(custody_document, dict), f"{where}.custody must be an object")
    assert isinstance(custody_document, dict)
    unknown = sorted(set(custody_document) - set(CUSTODY_FIELDS))
    _require(
        not unknown,
        f"{where}.custody: unknown custody class(es): {', '.join(unknown)}; the classes are "
        f"{', '.join(CUSTODY_FIELDS)}",
    )
    custody_values = {
        field: _string_tuple(custody_document, field, f"{where}.custody")
        for field in CUSTODY_FIELDS
        if field != "entrypoint_transforms"
    }
    entrypoint_paths, entrypoint_rules = _entrypoint_transform_entries(
        custody_document, f"{where}.custody"
    )
    custody_values["entrypoint_transforms"] = entrypoint_paths
    for field, values in custody_values.items():
        if field == "entrypoint_transforms":
            continue  # each entry's path was validated with its rule above
        for value in values:
            _relative_path(value, f"{where}.custody.{field}")
    custody = CustodyTable(**custody_values, entrypoint_rules=entrypoint_rules)

    declared = custody.declared()
    duplicates = sorted({name for name in declared if declared.count(name) > 1})
    _require(
        not duplicates,
        f"{where}.custody: assigns more than one classification to: {', '.join(duplicates)}",
    )

    if custody.client_byte_copies and extension_dir is None:
        raise PortConfigError(
            f"{where}: names client-custody byte copies but no source.client_extension_dir "
            "to place them under"
        )
    if manifest_path is not None and extension_dir is None:
        # The relocation transform's whole output path is
        # `<client_extension_dir>/<manifest name>`. Without the directory,
        # `sync_vendor_source.plan_sync` interpolates the missing value and
        # plans a file at the literal path `None/plugin.json` -- a descriptor
        # that validates and then writes somewhere nobody named.
        raise PortConfigError(
            f"{where}: names source.manifest_path but no source.client_extension_dir. The "
            "manifest relocation has no destination without one, and the synchronization "
            "would plan it at a path built from the missing value"
        )

    assessment_document = document["assessment"]
    _require(isinstance(assessment_document, dict), f"{where}.assessment must be an object")
    assert isinstance(assessment_document, dict)
    _closed(assessment_document, ASSESSMENT_FIELDS, f"{where}.assessment")

    declared_none = _string_tuple(assessment_document, "declared_none", f"{where}.assessment")
    unknown_none = sorted(set(declared_none) - set(SAFETY_FIELDS))
    _require(
        not unknown_none,
        f"{where}.assessment.declared_none names field(s) that carry no safety decision: "
        f"{', '.join(unknown_none)}. The safety fields are {', '.join(SAFETY_FIELDS)}",
    )

    # Every safety field is stated, and a field that is genuinely empty says so.
    # Absent, each one fails open in its own way -- see SAFETY_FIELDS. Requiring
    # the declaration is what makes "this package has no mutating operations" a
    # decision a reader can see rather than a typo nobody noticed.
    for field in SAFETY_FIELDS:
        stated = field in assessment_document
        _require(
            stated or field in declared_none,
            f"{where}.assessment.{field} is a safety declaration and must be stated. If this "
            f"package genuinely has none, write it as an empty list and name {field!r} in "
            "assessment.declared_none",
        )
        values = _string_tuple(assessment_document, field, f"{where}.assessment")
        if field in declared_none:
            _require(
                not values,
                f"{where}.assessment.{field} is named in declared_none but is not empty",
            )
        else:
            _require(
                bool(values),
                f"{where}.assessment.{field} is empty. An empty safety declaration fails open, "
                f"so name {field!r} in assessment.declared_none to say the emptiness is meant",
            )

    assessment = AssessmentConfig(
        package_scripts=_string_tuple(assessment_document, "package_scripts", f"{where}.assessment"),
        mutating_operations=frozenset(
            _string_tuple(assessment_document, "mutating_operations", f"{where}.assessment")
        ),
        credential_prefixes=_string_tuple(
            assessment_document, "credential_prefixes", f"{where}.assessment"
        ),
        skill_units=_string_tuple(assessment_document, "skill_units", f"{where}.assessment"),
        entrypoints=_string_tuple(assessment_document, "entrypoints", f"{where}.assessment"),
        declared_none=declared_none,
    )
    for unit in assessment.skill_units:
        _relative_path(unit, f"{where}.assessment.skill_units")
    for entrypoint in assessment.entrypoints:
        _relative_path(entrypoint, f"{where}.assessment.entrypoints")

    provenance_document = document.get("provenance", {})
    _require(isinstance(provenance_document, dict), f"{where}.provenance must be an object")
    assert isinstance(provenance_document, dict)
    _closed(provenance_document, PROVENANCE_FIELDS, f"{where}.provenance")
    notes = _string_tuple(provenance_document, "notes", f"{where}.provenance")
    dropped_reason = provenance_document.get("dropped_reason", "")
    _require(
        isinstance(dropped_reason, str),
        f"{where}.provenance.dropped_reason must be a string",
    )
    assert isinstance(dropped_reason, str)
    if custody.dropped_from_source:
        _require(
            dropped_reason.strip() != "",
            f"{where}: drops upstream paths but records no provenance.dropped_reason; a "
            "derived tree has to say why a path it does not carry was left behind",
        )

    return PortConfig(
        name=name,
        package_root=package_root,
        package_manifest=manifest,
        source=SourceConfig(
            repository=source_document["repository"],
            package_path=source_document["package_path"],
            manifest_path=manifest_path,
            client_extension_dir=extension_dir,
        ),
        custody=custody,
        assessment=assessment,
        notes=notes,
        dropped_reason=dropped_reason,
        root=root,
        path=path,
    )


def descriptor_path(name: str, root: Path | None = None) -> Path:
    resolved = root or repository_root()
    _require(
        name.strip() != "" and "/" not in name and name not in (".", ".."),
        f"{name!r} is not a package name",
    )
    return config_directory(resolved) / f"{name}{CONFIG_SUFFIX}"


def load(name: str, root: Path | None = None) -> PortConfig:
    """The descriptor for `name`, validated.

    Raises `PortConfigError` when no descriptor exists, naming the ones that do:
    a caller that asked for the wrong package should be told which packages this
    repository actually ports, not handed a bare file-not-found.
    """
    resolved = root or repository_root()
    path = descriptor_path(name, resolved)
    if not path.is_file():
        known = ", ".join(available(resolved)) or "none"
        raise PortConfigError(
            f"no port descriptor for {name!r} at {CONFIG_DIRECTORY_NAME}/{name}{CONFIG_SUFFIX}; "
            f"this repository ports: {known}"
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PortConfigError(f"{path.name}: not valid JSON: {error}") from error
    except OSError as error:  # pragma: no cover - unreadable file
        raise PortConfigError(f"{path.name}: could not be read: {error}") from error
    return parse(document, root=resolved, path=path)


def available(root: Path | None = None) -> list[str]:
    """Every package this repository carries a descriptor for, sorted."""
    directory = config_directory(root or repository_root())
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob(f"*{CONFIG_SUFFIX}") if path.is_file())


def load_all(root: Path | None = None) -> list[PortConfig]:
    """Every descriptor, validated. Raises on the first one that is not."""
    resolved = root or repository_root()
    return [load(name, resolved) for name in available(resolved)]
