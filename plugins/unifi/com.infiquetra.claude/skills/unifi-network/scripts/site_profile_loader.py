#!/usr/bin/env python3
"""Claude-adapter reader for the portable UniFi operator site-profile contract.

Why this file exists
--------------------
The ``unifi-network-ops`` agent used to carry one operator's lab topology in its own
prose: a controller address, four subnets, three host ranges, and a camera count. That
text was site knowledge frozen into a plugin every installation receives, and it was the
only place the agent could learn what a controller cannot report about itself — which
subjects are trusted, which are critical, who owns them, and which policies are meant to
hold.

The topology moved into an operator site profile. This module is how the Claude adapter
reads one. The portable package in ``infiquetra-agent-plugins`` carries its own loader for
the same contract; this repository carries this one, because the upstream agent cannot
depend on a file that lives only in the other repository.

The contract
------------
Schema ``urn:infiquetra:unifi:site-profile:1.0``, document ``schema_version`` ``"1.0"``,
released on branch ``orch/orch-2026-08-22-unifi-run-a`` at commit ``097909d7`` of
``infiquetra-agent-plugins``. This loader is pinned to that version and rejects any other
outright rather than applying part of a document it does not understand.

Three rules, each enforced in code rather than described in prose:

1. **The profile is optional.** A runtime with no profile anywhere loads successfully in
   discovery-only mode. Absence is a supported state, not an error.
2. **Resolution order is environment, then configuration, then none.** ``UNIFI_SITE_PROFILE``
   wins; otherwise the remembered configured path; otherwise no profile. This is the same
   environment-variable-then-default precedence ``UNIFI_HOST`` already uses in both clients,
   so the chain reads the same way to anyone who knows that code. A path an operator named
   explicitly must exist: a missing one fails loudly and never degrades to the next source,
   because answering quietly would describe the wrong site.
3. **Without a profile, no intent is inferred.** Every trust-role, criticality, ownership,
   or intended-policy query returns the explicit :data:`UNKNOWN` sentinel. Absent intent is
   reported as absent, never as a default and never as a guess.

The standard library is the only import, and the format is JSON, so a host with no
third-party parser can still read a profile.

Usage:
    python site_profile_loader.py
    python site_profile_loader.py --config-path /path/to/config.json
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- contract identifiers -------------------------------------------------

#: The environment variable that overrides every other profile source.
ENVIRONMENT_VARIABLE = "UNIFI_SITE_PROFILE"

CONFIG_HOME_VARIABLE = "XDG_CONFIG_HOME"
CONFIG_HOME_FALLBACK = Path(".config")
CONFIG_RELATIVE_DIRECTORY = Path("infiquetra") / "unifi"
CONFIG_FILENAME = "config.json"

#: Where a deployed runtime profile lives when nothing else is configured. A documented
#: default *path*, not a default *profile*: an absent file here still means discovery-only.
DEFAULT_PROFILE_FILENAME = "site-profile.json"

#: JSON Schema ``$id`` of the contract this loader reads. A URN rather than a URL, because
#: nothing here resolves a schema over the network and a fetchable identifier would imply
#: otherwise.
SCHEMA_IDENTIFIER = "urn:infiquetra:unifi:site-profile:1.0"

#: Document versions this loader understands.
SUPPORTED_SCHEMA_VERSIONS = ("1.0",)

# --- resolution outcomes --------------------------------------------------

PROFILE_MODE = "profile"
DISCOVERY_ONLY_MODE = "discovery-only"

ENVIRONMENT_SOURCE = "environment"
CONFIGURED_SOURCE = "configured"

# --- profile vocabulary ---------------------------------------------------

UNKNOWN_LITERAL = "unknown"

SUBJECT_KINDS = ("site", "network", "host", "device", "client")
TRUST_ROLES = ("trusted", "restricted", "untrusted", UNKNOWN_LITERAL)
CRITICALITY_LEVELS = ("critical", "important", "routine", UNKNOWN_LITERAL)

#: The four intent facets the no-inference rule covers.
INTENT_FIELDS = ("trust_role", "criticality", "ownership", "intended_policies")

#: Property-name fragments that make a field credential-shaped. A profile carries intent,
#: never a secret, so any property whose normalized name contains one of these is rejected
#: wherever it appears in the document.
CREDENTIAL_NAME_FRAGMENTS = (
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "passphrase",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)

TOP_LEVEL_FIELDS = (
    "schema_version",
    "site",
    "subjects",
    "intended_policies",
    "operational_constraints",
)
SITE_FIELDS = ("identifier", "description")
SUBJECT_FIELDS = ("kind", "identifier", "trust_role", "criticality", "ownership", "notes")
POLICY_FIELDS = ("identifier", "description", "applies_to")
CONSTRAINT_FIELDS = ("identifier", "description")

#: What a caller may not conclude while running without a profile. Rendered by
#: :meth:`SiteContext.describe` so a discovery-only run states its own limits rather than
#: leaving them to be remembered.
DISCOVERY_ONLY_LIMITS = (
    "No trust role is known for any subject.",
    "No criticality is known for any subject.",
    "No ownership is known for any subject.",
    "No intended policy or operational constraint is known.",
    "Controller state may be reported; operator intent may not be inferred from it.",
)


# --- errors ---------------------------------------------------------------


class SiteProfileError(Exception):
    """Base class for every site-profile failure."""


class ProfileConfigurationError(SiteProfileError):
    """The profile configuration itself is malformed."""


class ProfileNotFoundError(SiteProfileError):
    """A profile path was named by an operator but nothing is there."""


class ProfileUnreadableError(SiteProfileError):
    """A profile file exists but cannot be read or parsed."""


class ProfileInvalidError(SiteProfileError):
    """A profile parsed but violates the contract."""


class UnsupportedSchemaVersionError(ProfileInvalidError):
    """A profile declares a schema version this loader does not understand."""


# --- the explicit unknown -------------------------------------------------


class _Unknown:
    """The single explicit unknown returned instead of an inferred value.

    Falsy, so a caller cannot accidentally treat it as a populated value, and its string
    form is the literal ``unknown`` so rendering it produces the right word with no special
    case at every call site.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNKNOWN"

    def __str__(self) -> str:
        return UNKNOWN_LITERAL

    def __bool__(self) -> bool:
        return False


#: Returned by every intent query that has no operator-supplied answer.
UNKNOWN = _Unknown()


def is_unknown(value: object) -> bool:
    """True when ``value`` is the explicit unknown or the literal ``unknown``."""
    return value is UNKNOWN or value == UNKNOWN_LITERAL


# --- configuration file ---------------------------------------------------


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def config_directory(environ: Mapping[str, str] | None = None) -> Path:
    """Directory holding the portable configuration file and the default profile path."""
    env = _environ(environ)
    configured_home = (env.get(CONFIG_HOME_VARIABLE) or "").strip()
    if configured_home:
        base = Path(configured_home)
    else:
        base = Path(env.get("HOME") or Path.home()) / CONFIG_HOME_FALLBACK
    return base / CONFIG_RELATIVE_DIRECTORY


def config_file_path(environ: Mapping[str, str] | None = None) -> Path:
    return config_directory(environ) / CONFIG_FILENAME


def default_profile_path(environ: Mapping[str, str] | None = None) -> Path:
    return config_directory(environ) / DEFAULT_PROFILE_FILENAME


def read_config(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Read the remembered configuration, or ``{}`` when none has been written."""
    path = Path(config_path) if config_path is not None else config_file_path(environ)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileConfigurationError(f"unreadable configuration file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileConfigurationError(f"configuration file {path} does not contain an object")
    return payload


# --- resolution -----------------------------------------------------------


@dataclass(frozen=True)
class ProfileResolution:
    """Where the profile came from, or that there is deliberately none."""

    path: Path | None
    source: str | None

    @property
    def mode(self) -> str:
        return PROFILE_MODE if self.path is not None else DISCOVERY_ONLY_MODE


def resolve_profile_path(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> ProfileResolution:
    """Resolve the profile path: environment, then configuration, then none."""
    env = _environ(environ)
    if ENVIRONMENT_VARIABLE in env:
        candidate = (env[ENVIRONMENT_VARIABLE] or "").strip()
        if not candidate:
            raise ProfileConfigurationError(
                f"{ENVIRONMENT_VARIABLE} is set but empty; unset it to run without a profile"
            )
        path = Path(candidate).expanduser()
        if not path.is_file():
            raise ProfileNotFoundError(
                f"{ENVIRONMENT_VARIABLE} names a profile that does not exist: {path}"
            )
        return ProfileResolution(path=path, source=ENVIRONMENT_SOURCE)

    config = read_config(environ=environ, config_path=config_path)
    configured = config.get("site_profile_path")
    if configured is None or (isinstance(configured, str) and not configured.strip()):
        return ProfileResolution(path=None, source=None)
    if not isinstance(configured, str):
        raise ProfileConfigurationError(
            "configuration field site_profile_path must be a string or null, "
            f"found {type(configured).__name__}"
        )
    path = Path(configured).expanduser()
    if not path.is_file():
        resolved_config = (
            Path(config_path) if config_path is not None else config_file_path(environ)
        )
        raise ProfileNotFoundError(
            f"configuration file {resolved_config} names a profile that no longer exists: {path}"
        )
    return ProfileResolution(path=path, source=CONFIGURED_SOURCE)


# --- validation -----------------------------------------------------------


def _credential_field(value: object, trail: str = "") -> str | None:
    """Return the first credential-shaped property path found, or ``None``."""
    if isinstance(value, dict):
        for key in value:
            location = f"{trail}.{key}" if trail else str(key)
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            for fragment in CREDENTIAL_NAME_FRAGMENTS:
                if fragment in normalized:
                    return location
            found = _credential_field(value[key], location)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _credential_field(item, f"{trail}[{index}]")
            if found is not None:
                return found
    return None


def _require_object(value: object, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileInvalidError(f"{location} must be an object")
    return value


def _reject_unknown_fields(
    payload: Mapping[str, Any], allowed: Iterable[str], location: str
) -> None:
    permitted = set(allowed)
    for field in payload:
        if field not in permitted:
            raise ProfileInvalidError(f"unknown field in {location}: {field}")


def _require_text(payload: Mapping[str, Any], field: str, location: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProfileInvalidError(f"{location} requires a non-empty {field}")
    return value


def _optional_text(payload: Mapping[str, Any], field: str, location: str) -> str | None:
    if field not in payload:
        return None
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ProfileInvalidError(f"{location} field {field} must be a non-empty string")
    return value


def _optional_choice(
    payload: Mapping[str, Any], field: str, choices: tuple[str, ...], location: str
) -> str | None:
    value = _optional_text(payload, field, location)
    if value is None:
        return None
    if value not in choices:
        raise ProfileInvalidError(
            f"{location} field {field} must be one of {', '.join(choices)}; found {value!r}"
        )
    return value


def validate_profile(document: object) -> dict[str, Any]:
    """Validate a parsed profile document against the contract.

    The credential rule is checked first, so a profile that leaked a secret is reported as a
    credential violation naming the offending field rather than as a generic unknown-field
    error that reads like a typo.
    """
    payload = _require_object(document, "profile")

    offending = _credential_field(payload)
    if offending is not None:
        raise ProfileInvalidError(
            f"credential-shaped field is not permitted in a site profile: {offending}"
        )

    version = payload.get("schema_version")
    if not isinstance(version, str) or not version.strip():
        raise UnsupportedSchemaVersionError("profile requires a non-empty schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(
            f"unsupported profile schema_version {version!r}; this loader understands "
            f"{', '.join(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    _reject_unknown_fields(payload, TOP_LEVEL_FIELDS, "profile")

    site = _require_object(payload.get("site"), "profile.site")
    _reject_unknown_fields(site, SITE_FIELDS, "profile.site")
    _require_text(site, "identifier", "profile.site")
    _optional_text(site, "description", "profile.site")

    subjects = payload.get("subjects", [])
    if not isinstance(subjects, list):
        raise ProfileInvalidError("profile.subjects must be a list")
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(subjects):
        location = f"profile.subjects[{index}]"
        subject = _require_object(entry, location)
        _reject_unknown_fields(subject, SUBJECT_FIELDS, location)
        kind = _require_text(subject, "kind", location)
        if kind not in SUBJECT_KINDS:
            raise ProfileInvalidError(
                f"{location} field kind must be one of {', '.join(SUBJECT_KINDS)}; found {kind!r}"
            )
        identifier = _require_text(subject, "identifier", location)
        if (kind, identifier) in seen:
            raise ProfileInvalidError(f"{location} duplicates subject {kind}/{identifier}")
        seen.add((kind, identifier))
        _optional_choice(subject, "trust_role", TRUST_ROLES, location)
        _optional_choice(subject, "criticality", CRITICALITY_LEVELS, location)
        _optional_text(subject, "ownership", location)
        _optional_text(subject, "notes", location)

    policies = payload.get("intended_policies", [])
    if not isinstance(policies, list):
        raise ProfileInvalidError("profile.intended_policies must be a list")
    policy_identifiers: set[str] = set()
    for index, entry in enumerate(policies):
        location = f"profile.intended_policies[{index}]"
        policy = _require_object(entry, location)
        _reject_unknown_fields(policy, POLICY_FIELDS, location)
        identifier = _require_text(policy, "identifier", location)
        if identifier in policy_identifiers:
            raise ProfileInvalidError(f"{location} duplicates policy {identifier}")
        policy_identifiers.add(identifier)
        _require_text(policy, "description", location)
        applies_to = policy.get("applies_to", [])
        if not isinstance(applies_to, list) or not all(
            isinstance(item, str) and item.strip() for item in applies_to
        ):
            raise ProfileInvalidError(f"{location} field applies_to must be a list of identifiers")

    constraints = payload.get("operational_constraints", [])
    if not isinstance(constraints, list):
        raise ProfileInvalidError("profile.operational_constraints must be a list")
    constraint_identifiers: set[str] = set()
    for index, entry in enumerate(constraints):
        location = f"profile.operational_constraints[{index}]"
        constraint = _require_object(entry, location)
        _reject_unknown_fields(constraint, CONSTRAINT_FIELDS, location)
        identifier = _require_text(constraint, "identifier", location)
        if identifier in constraint_identifiers:
            raise ProfileInvalidError(f"{location} duplicates constraint {identifier}")
        constraint_identifiers.add(identifier)
        _require_text(constraint, "description", location)

    return payload


def load_profile_document(path: Path) -> dict[str, Any]:
    """Read and validate a profile file, failing loudly on every defect."""
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProfileNotFoundError(f"profile does not exist: {resolved}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ProfileUnreadableError(f"unreadable profile {resolved}: {exc}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProfileUnreadableError(f"unparseable profile {resolved}: {exc}") from exc
    return validate_profile(document)


# --- the loaded context ---------------------------------------------------


@dataclass(frozen=True)
class SiteProfile:
    """A validated profile, indexed for intent queries."""

    document: Mapping[str, Any]

    @property
    def site_identifier(self) -> str:
        return str(self.document["site"]["identifier"])

    @property
    def subjects(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.document.get("subjects", []))

    @property
    def policies(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.document.get("intended_policies", []))

    @property
    def constraints(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.document.get("operational_constraints", []))

    def subject(self, identifier: str, kind: str = "host") -> Mapping[str, Any] | None:
        for entry in self.subjects:
            if entry.get("identifier") == identifier and entry.get("kind") == kind:
                return entry
        return None


@dataclass(frozen=True)
class SiteContext:
    """The single object every caller receives, profile present or absent.

    The same query surface answers in both modes. In discovery-only mode, and for any
    subject the profile does not mention, every intent query returns :data:`UNKNOWN` rather
    than a default, which is how the no-inference rule survives contact with a caller that
    forgot to check the mode.
    """

    mode: str
    path: Path | None
    source: str | None
    profile: SiteProfile | None

    @property
    def has_profile(self) -> bool:
        return self.profile is not None

    def _intent(self, field: str, identifier: str, kind: str) -> Any:
        if self.profile is None:
            return UNKNOWN
        subject = self.profile.subject(identifier, kind=kind)
        if subject is None:
            return UNKNOWN
        value = subject.get(field)
        if value is None or is_unknown(value):
            return UNKNOWN
        return value

    def trust_role(self, identifier: str, kind: str = "host") -> Any:
        return self._intent("trust_role", identifier, kind)

    def criticality(self, identifier: str, kind: str = "host") -> Any:
        return self._intent("criticality", identifier, kind)

    def ownership(self, identifier: str, kind: str = "host") -> Any:
        return self._intent("ownership", identifier, kind)

    def intended_policies(self, identifier: str, kind: str = "host") -> Any:
        """Policies the profile says apply to a subject, or the explicit unknown."""
        if self.profile is None:
            return UNKNOWN
        if self.profile.subject(identifier, kind=kind) is None:
            return UNKNOWN
        return tuple(
            policy
            for policy in self.profile.policies
            if identifier in tuple(policy.get("applies_to", []))
        )

    def operational_constraints(self) -> Any:
        if self.profile is None:
            return UNKNOWN
        return self.profile.constraints

    def known_subjects(self, kind: str | None = None) -> tuple[Mapping[str, Any], ...]:
        """Subjects the profile names. An inventory query, not an intent query.

        Discovery-only mode returns an empty tuple: the profile names nothing because there
        is no profile, which is a complete and honest answer to "what does the operator's
        profile list?".
        """
        if self.profile is None:
            return ()
        if kind is None:
            return self.profile.subjects
        return tuple(entry for entry in self.profile.subjects if entry.get("kind") == kind)

    def describe(self) -> dict[str, Any]:
        """A JSON-serializable summary, including the limits of no-profile mode."""
        summary: dict[str, Any] = {
            "mode": self.mode,
            "profile_path": str(self.path) if self.path is not None else None,
            "profile_source": self.source,
            "schema_version": None,
            "site_identifier": None,
            "subject_count": 0,
            "policy_count": 0,
            "constraint_count": 0,
        }
        if self.profile is None:
            summary["limits"] = list(DISCOVERY_ONLY_LIMITS)
            summary["intent_fields"] = dict.fromkeys(INTENT_FIELDS, UNKNOWN_LITERAL)
            return summary
        summary["schema_version"] = self.profile.document.get("schema_version")
        summary["site_identifier"] = self.profile.site_identifier
        summary["subject_count"] = len(self.profile.subjects)
        summary["policy_count"] = len(self.profile.policies)
        summary["constraint_count"] = len(self.profile.constraints)
        return summary

    def render(self) -> dict[str, Any]:
        """The full resolved context an agent reads instead of embedded topology."""
        rendered = self.describe()
        rendered["subjects"] = [dict(entry) for entry in self.known_subjects()]
        if self.profile is None:
            rendered["intended_policies"] = []
            rendered["operational_constraints"] = []
            return rendered
        rendered["intended_policies"] = [dict(entry) for entry in self.profile.policies]
        rendered["operational_constraints"] = [dict(entry) for entry in self.profile.constraints]
        return rendered


def load_site_context(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> SiteContext:
    """Resolve and load the site profile, or return discovery-only mode.

    No profile anywhere is a supported outcome and never raises. A profile an operator named
    but that is missing, unreadable, or invalid does raise, because silently continuing would
    report one site's state under another site's assumptions.
    """
    resolution = resolve_profile_path(environ=environ, config_path=config_path)
    if resolution.path is None:
        return SiteContext(mode=DISCOVERY_ONLY_MODE, path=None, source=None, profile=None)
    document = load_profile_document(resolution.path)
    return SiteContext(
        mode=PROFILE_MODE,
        path=resolution.path,
        source=resolution.source,
        profile=SiteProfile(document=document),
    )


def main(argv: list[str] | None = None) -> int:
    """Report the resolved site context as JSON on standard output."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Report the resolved UniFi operator site-profile context."
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="Configuration file to read instead of the XDG default.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Report counts and mode only, omitting subjects, policies, and constraints.",
    )
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config_path) if arguments.config_path else None
    try:
        context = load_site_context(config_path=config_path)
    except SiteProfileError as exc:
        print(json.dumps({"error": True, "message": str(exc), "error_type": type(exc).__name__}))
        return 1
    payload = context.describe() if arguments.summary else context.render()
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
