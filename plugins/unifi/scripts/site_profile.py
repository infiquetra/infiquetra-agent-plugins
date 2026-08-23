#!/usr/bin/env python3
"""Portable operator site-profile contract for the UniFi package.

An operator site profile carries *intended* meaning that a UniFi controller
cannot report about itself: which subjects are trusted, which are critical, who
owns them, which policies are meant to hold, and which operational constraints
apply. Everything a controller can already report is deliberately out of scope,
and credentials are excluded by validation rather than by convention -- by *value*
as well as by field name.

That guarantee has a precise shape, and it is worth stating exactly rather than
generously. A credential-shaped field *name* is rejected wherever it appears in
the document. A credential written as a *value* inside an ordinary field such as
``notes``, ``description``, or ``ownership`` is rejected too, by two narrow
families: literal well-known credential formats, and a credential-shaped key
assigned a value that clears an entropy floor. There is deliberately no bare
high-entropy scan, because a profile legitimately carries digests and long
identifiers and a check that fires on those gets switched off. Value detection is
therefore defense in depth against an accident, not a proof of absence: a short,
low-entropy secret in a free-text value still passes.

Three rules shape this module, and each is enforced in code rather than
described in prose:

1. The profile is optional. A runtime with no profile anywhere loads
   successfully in discovery-only mode; absence is a supported state, not an
   error.
2. Resolution order is the ``UNIFI_SITE_PROFILE`` environment variable, then
   the remembered configured path, then no profile at all. This is the same
   environment-variable-then-default precedence the UniFi clients already use
   for ``UNIFI_HOST``, so it reads the same way to anyone who knows that code.
3. Without a profile, no intent is inferred. A trust role, criticality,
   ownership, or intended-policy query returns the explicit :data:`UNKNOWN`
   sentinel, which callers must render as unknown. Absent intent is reported as
   absent, never as a default and never as a guess.

The module imports the standard library only. The profile format is JSON so a
host with no third-party parser can still read a profile, which is what keeps
the optional-profile promise true on a minimal runtime. An operator may author
in a friendlier format and render JSON at deployment time.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


# --- contract identifiers -------------------------------------------------

#: The environment variable that overrides every other profile source.
ENVIRONMENT_VARIABLE = "UNIFI_SITE_PROFILE"

#: Base directory variable for the portable configuration file, per the XDG
#: Base Directory specification. ``~/.config`` is the documented fallback.
CONFIG_HOME_VARIABLE = "XDG_CONFIG_HOME"
CONFIG_HOME_FALLBACK = Path(".config")
CONFIG_RELATIVE_DIRECTORY = Path("infiquetra") / "unifi"
CONFIG_FILENAME = "config.json"

#: Where a deployed runtime profile lives when nothing else is configured.
#: This is a documented default path, not an implied default *profile*: an
#: absent file at this path still means discovery-only mode.
DEFAULT_PROFILE_FILENAME = "site-profile.json"

#: JSON Schema ``$id`` of the profile contract. A URN rather than a URL,
#: because nothing here ever resolves a schema over the network and a
#: fetchable identifier would imply otherwise.
SCHEMA_IDENTIFIER = "urn:infiquetra:unifi:site-profile:1.1"
SCHEMA_FILENAME = "site-profile.schema.json"

#: Profile document versions this loader understands, oldest first. An
#: unrecognized version is rejected outright rather than partially applied.
#:
#: ``1.1`` adds no field and removes none. It records that the secret-free
#: guarantee now covers values as well as names, which is a change to the set of
#: documents the contract calls valid and therefore to the contract. A ``1.0``
#: document still loads, and the value rule is applied to it, because a
#: credential in a ``1.0`` profile is exactly as exposed as one in a ``1.1``
#: profile; refusing to read ``1.0`` would strand every deployed profile without
#: protecting anything.
#:
#: Ordered oldest first, which is what ``discover.py`` indexes into when it
#: stamps a generated proposal, so a proposal written today still declares
#: ``1.0``. That is valid and loads, and moving the generator to the newest
#: version it can produce is a change to that file rather than a reorder here.
SUPPORTED_SCHEMA_VERSIONS = ("1.0", "1.1")

#: Version of the configuration file this module reads and writes.
CONFIG_VERSION = 1


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

#: Property-name fragments that make a field credential-shaped. A profile
#: carries intent, never a secret, so any property whose normalized name
#: contains one of these is rejected wherever it appears in the document.
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

# Credential detection by *value*, which is the other half of the same promise.
# The fragment list above rejects a field called ``password``; it says nothing
# about a password pasted into a field called ``notes``. These two families close
# that gap, and they are deliberately the same two the repository's own gate uses
# in ``scripts/check_repo.py``.
#
# They are re-stated here rather than imported. This module is portable package
# source: it is copied onto an operator's machine and loaded with the standard
# library alone, where the repository's validator does not exist and never will.
# Importing it would make the portable loader depend on a development-time script
# and break the standard-library-only guarantee this module is built around.
# ``tests/test_site_profile.py`` pins the two copies to each other instead, so a
# rule added to one and not the other fails the suite rather than drifting into a
# second dialect.
#
# Family one: literal formats that are credentials wherever they appear.
CREDENTIAL_VALUE_FORMATS = (
    ("AWS access key id", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe secret key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    (
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("credential embedded in a URL", re.compile(r"://[^/\s:@]+:[^/\s@]{3,}@")),
)

# Family two: a strict secret-bearing key assigned a literal value. Which keys
# count as strict is not a second opinion invented here -- it is the property
# name taxonomy above, reused. A key is strict when its normalized spelling
# contains one of those fragments, plus the short and compound spellings below
# that occur inside free text but never as a schema property name. Deriving the
# in-text set from the property-name set is what stops the two halves of one
# rule drifting into two dialects.
#
# The extras match the whole normalized key rather than a substring of it, so a
# field called ``author`` is not mistaken for ``auth``.
CREDENTIAL_KEY_EXACT_IN_TEXT = ("auth", "accesskey", "clientsecret")

# The key is captured generically and graded by that taxonomy instead of being
# spelled out in the pattern, and the value floor is one character: under a
# strict key there is no length below which a literal stops being a credential.
# The value is captured by lookahead so the match itself ends at the delimiter.
# Consuming the value instead let an innocent key swallow a strict one standing
# inside it: in ``"notes": "controller password=hunter2"`` the scan matched
# ``notes``, found it harmless, and resumed *after* the password it had eaten.#
# An assignment is one line. The whitespace around the delimiter is horizontal
# only and the value stops at a newline, because ``\s*`` spanning a line break
# reopened the swallow across lines: ``see notes:\npassword=hunter2`` matched
# ``notes``, ate the newline with it, and left the password with no preceding
# character to start a fresh match against -- so the loader accepted a credential
# the gate, which reads line by line, refused.
CREDENTIAL_ASSIGNMENT_IN_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]{1,31})[\"']?[^\S\n]*[:=][^\S\n]*"
    r"[\"']?(?=([^\"',;\n]{1,200}))"
)

# An auth scheme word sits between the key and the credential in the shape an
# operator actually pastes: ``authorization: Bearer <token>``. Scheme words and
# placeholders are stepped over so the literal standing behind them is what gets
# graded, which is what catches ``authorization: Bearer <redacted> <token>``.
CREDENTIAL_SCHEME_WORDS = frozenset(
    {"bearer", "basic", "digest", "token", "apikey", "hmac", "negotiate"}
)

# A template expression is one reference written in several whitespace-separated
# pieces, so it is collapsed to a single placeholder before the value is split.
# Grading it as a whole value instead was wrong in a way worth recording: it
# cleared ``authorization: Bearer ${UNIFI_API_KEY} <token>`` outright, because a
# value that merely *contains* an expression is not a value that *is* one.
CREDENTIAL_TEMPLATE_EXPRESSION = re.compile(
    r"\$\{[^}]*\}|\{\{[^}]*\}\}|\{%[^%]*%\}|%\([^)]*\)s?|\$[A-Za-z_][A-Za-z0-9_]*"
)

# Values that name a secret rather than being one. A profile is expected to say
# where the credential lives, so these must never be reported.
CREDENTIAL_VALUE_PLACEHOLDER = re.compile(
    r"(?i)^(?:redacted|removed|omitted|none|null|true|false|unset|empty|"
    r"change[_-]?me|example|placeholder|your[_-].*|my[_-].*|"
    r"x{3,}|\*{3,}|\.{3,}|-{3,}|_{3,})$"
)
CREDENTIAL_VALUE_REFERENCE_PREFIX = re.compile(
    r"(?i)^(?:env|vault|op|aws|gcp|azure|secretref|ref)[:/]"
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

#: The schema fields that carry operator prose. Every other field in the
#: contract is an identifier or an enumerated value, so a sentence is not
#: expected in one and the prose allowance in :func:`_credential_in_text` does
#: not apply there. Derived from the field tuples above rather than restated, so
#: removing a field from the schema removes it from here too.
DESCRIPTIVE_FIELDS = frozenset(
    name
    for name in (*SITE_FIELDS, *SUBJECT_FIELDS, *POLICY_FIELDS, *CONSTRAINT_FIELDS)
    if name in ("description", "notes")
)

#: What a caller may not conclude while running without a profile. Rendered by
#: :meth:`SiteContext.describe` so a discovery-only run states its own limits
#: instead of leaving them to be remembered.
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

    It is falsy so a caller cannot accidentally treat it as a populated value,
    and its string form is the literal ``unknown`` so rendering it produces the
    right word without a special case at every call site.
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
    """Directory holding the portable configuration and default profile."""
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


def write_config(
    config: Mapping[str, Any],
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Path:
    """Write the remembered configuration so setup is not asked again."""
    path = Path(config_path) if config_path is not None else config_file_path(environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(config)
    payload.setdefault("config_version", CONFIG_VERSION)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


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
    """Resolve the profile path: environment, then configuration, then none.

    Every path an operator named explicitly must exist. A named path that is
    missing fails loudly and never silently degrades to the next source, since
    quietly falling back would answer a question about the wrong site.
    """
    env = _environ(environ)
    if ENVIRONMENT_VARIABLE in env:
        raw = env[ENVIRONMENT_VARIABLE]
        candidate = (raw or "").strip()
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
            f"configuration file {resolved_config} names a profile that no longer "
            f"exists: {path}"
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


def _names_a_secret(value: str) -> bool:
    """True when the value points at where a credential lives instead of being one."""
    if CREDENTIAL_VALUE_PLACEHOLDER.match(value):
        return True
    if CREDENTIAL_VALUE_REFERENCE_PREFIX.match(value):
        return True
    if value.startswith(("$", "<", "{{", "{%", "%(")) or value.endswith(">"):
        return True
    if "${" in value or "{{" in value:
        return True
    return len(set(value)) <= 2 or value.isdigit()


def _is_strict_credential_key(key: str) -> bool:
    """Whether an in-text assignment key is one a profile may never assign.

    Graded with the same fragment list :func:`_credential_field` uses on property
    names, so the rule has one taxonomy rather than two.
    """
    normalized = "".join(character for character in key.lower() if character.isalnum())
    if any(fragment in normalized for fragment in CREDENTIAL_NAME_FRAGMENTS):
        return True
    return normalized in CREDENTIAL_KEY_EXACT_IN_TEXT


def _substantive_tokens(assigned: str) -> list[str]:
    """The tokens of an assigned value that could be a credential themselves.

    Template expressions are collapsed first so that a reference spelled across
    several whitespace-separated pieces counts as the one placeholder it is,
    rather than contributing a bare inner word as a candidate.
    """
    collapsed = CREDENTIAL_TEMPLATE_EXPRESSION.sub(" <redacted> ", assigned)
    return [
        token
        for token in collapsed.split()
        if token.lower() not in CREDENTIAL_SCHEME_WORDS and not _names_a_secret(token)
    ]


def _credential_in_text(text: str, descriptive: bool = True) -> str | None:
    """Describe the credential in ``text``, or ``None`` when there is none.

    Which rule applies is decided by the *key*, not by what the value looks like.
    A strict secret-bearing key assigned a single substantive literal is a
    credential whatever that literal happens to be: ``rainbowtrout`` counts, and
    so does ``secret``. There is no entropy floor, no digit test and no length
    bar, because those graded the value and could not tell ``oauth2`` from a
    password in either direction -- they refused the technical word and let the
    digit-free password through.

    A strict key followed by several substantive words is a sentence *about* a
    credential rather than a credential, and in the fields the schema keeps for
    prose that is allowed: ``notes: "token: base64 of the site identifier"``
    stays. Everywhere else the contract carries identifiers and enumerated
    values, never sentences, so the allowance does not apply.

    The limit this leaves is deliberate, and the reference states it: a literal
    padded out with prose under a strict key in a prose field is not reported.
    """
    for label, pattern in CREDENTIAL_VALUE_FORMATS:
        if pattern.search(text):
            return label
    for match in CREDENTIAL_ASSIGNMENT_IN_TEXT.finditer(text):
        key, assigned = match.group(1), match.group(2)
        if not _is_strict_credential_key(key):
            continue
        tokens = _substantive_tokens(assigned)
        if not tokens:
            continue  # a placeholder, a reference, or a bare scheme word
        if len(tokens) == 1 or not descriptive:
            return f"{key!r} is assigned a credential-shaped value"
    return None


def _credential_value(
    value: object, trail: str = "", field: str = ""
) -> tuple[str, str] | None:
    """Return ``(property path, what fired)`` for the first credential value.

    Every string in the document is inspected, at any depth, because the point of
    the check is that a credential does not become acceptable by being written
    into a field whose name is innocent. Mapping *keys* are not inspected here:
    a credential-shaped key is :func:`_credential_field`'s job, and every object
    in the contract is closed, so a key that is itself a literal credential is
    rejected as an unknown field.
    """
    if isinstance(value, str):
        finding = _credential_in_text(value, descriptive=field in DESCRIPTIVE_FIELDS)
        return None if finding is None else (trail or "profile", finding)
    if isinstance(value, dict):
        for key in value:
            location = f"{trail}.{key}" if trail else str(key)
            found = _credential_value(value[key], location, str(key))
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _credential_value(item, f"{trail}[{index}]", field)
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

    The credential rules are checked first, both of them, so a profile that
    leaked a secret is reported as a credential violation naming the offending
    property, rather than as a generic unknown-field or version error that reads
    like a typo. The name rule runs before the value rule only so that a field
    called ``password`` is reported as a forbidden field even when what was put
    in it is inert.
    """
    payload = _require_object(document, "profile")

    offending = _credential_field(payload)
    if offending is not None:
        raise ProfileInvalidError(
            f"credential-shaped field is not permitted in a site profile: {offending}"
        )

    leaked = _credential_value(payload)
    if leaked is not None:
        location, reason = leaked
        raise ProfileInvalidError(
            f"credential value is not permitted in a site profile: {location} "
            f"({reason}); a profile states intent and points at where a secret "
            f"lives, it never carries one"
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

    The same query surface answers in both modes. In discovery-only mode, and
    for any subject the profile does not mention, every intent query returns
    :data:`UNKNOWN` rather than a default, which is how the no-inference rule
    survives contact with a caller that forgot to check the mode.
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
        matched = tuple(
            policy
            for policy in self.profile.policies
            if identifier in tuple(policy.get("applies_to", []))
        )
        return matched

    def operational_constraints(self) -> Any:
        if self.profile is None:
            return UNKNOWN
        return self.profile.constraints

    def known_subjects(self, kind: str | None = None) -> tuple[Mapping[str, Any], ...]:
        """Subjects the profile names. An inventory query, not an intent query.

        Discovery-only mode returns an empty tuple: the profile names nothing
        because there is no profile, which is a complete and honest answer to
        "what does the operator's profile list?".
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
            summary["intent_fields"] = {field: UNKNOWN_LITERAL for field in INTENT_FIELDS}
            return summary
        summary["schema_version"] = self.profile.document.get("schema_version")
        summary["site_identifier"] = self.profile.site_identifier
        summary["subject_count"] = len(self.profile.subjects)
        summary["policy_count"] = len(self.profile.policies)
        summary["constraint_count"] = len(self.profile.constraints)
        return summary


def load_site_context(
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> SiteContext:
    """Resolve and load the site profile, or return discovery-only mode.

    No profile anywhere is a supported outcome and never raises. A profile an
    operator named but that is missing, unreadable, or invalid does raise,
    because silently continuing would report one site's state under another
    site's assumptions.
    """
    resolution = resolve_profile_path(environ=environ, config_path=config_path)
    if resolution.path is None:
        return SiteContext(
            mode=DISCOVERY_ONLY_MODE, path=None, source=None, profile=None
        )
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
    arguments = parser.parse_args(argv)
    config_path = Path(arguments.config_path) if arguments.config_path else None
    try:
        context = load_site_context(config_path=config_path)
    except SiteProfileError as exc:
        print(json.dumps({"error": str(exc), "error_type": type(exc).__name__}, indent=2))
        return 1
    print(json.dumps(context.describe(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
