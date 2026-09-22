"""The Claude adapter's site-profile loader.

The contract tests below use an inert documentation profile (RFC 5737
addresses, site identifier ``example-site``). The upstream module also
carried one operator's lab topology as a relocation record, and two tests
that existed to prove that record survived. Those tests and that record
are not in this package: a public repository does not republish one
site's addressing.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PACKAGE_ROOT
LOADER_PATH = (
    PLUGIN_ROOT
    / "com.infiquetra.claude"
    / "skills"
    / "unifi-network"
    / "scripts"
    / "site_profile_loader.py"
)
AGENT_DOC = PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / "unifi-network-ops.md"


def _load_module() -> ModuleType:
    """Import the loader by path; the plugin directory is not an importable package."""
    spec = importlib.util.spec_from_file_location("site_profile_loader", LOADER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because ``@dataclass`` resolves annotations through
    # ``sys.modules[cls.__module__]``; without this the decorator raises on an absent entry.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


loader = _load_module()


# --------------------------------------------------------------------------------------
# The relocated profile, and the prior agent text it came from
# --------------------------------------------------------------------------------------

#: An inert documentation profile. One operator's lab topology used to live
#: here as the relocation record. This package does not carry it.
RELOCATED_SITE_PROFILE: dict[str, Any] = {
    "schema_version": "1.0",
    "site": {
        "identifier": "example-site",
        "description": "Documentation site used by these tests. Not an operator network.",
    },
    "subjects": [
        {
            "kind": "device",
            "identifier": "192.0.2.1",
            "trust_role": "trusted",
            "notes": "Example controller. Documentation address, TEST-NET-1.",
        },
        {
            "kind": "device",
            "identifier": "example-cameras",
            "notes": "Example cameras, named so a subject can exist without a trust role.",
        },
        {
            "kind": "network",
            "identifier": "192.0.2.0/24",
            "trust_role": "trusted",
            "notes": "Example LAN. Documentation prefix, TEST-NET-1.",
        },
        {
            "kind": "network",
            "identifier": "198.51.100.0/24",
            "notes": "Example management network. Documentation prefix, TEST-NET-2.",
        },
        {
            "kind": "network",
            "identifier": "203.0.113.0/24",
            "notes": "Example isolated network. Documentation prefix, TEST-NET-3.",
        },
        {
            "kind": "network",
            "identifier": "203.0.113.128/25",
            "notes": "Example guest network. Documentation prefix, TEST-NET-3.",
        },
        {
            "kind": "host",
            "identifier": "192.0.2.10",
            "notes": "Example host on the documentation LAN.",
        },
        {
            "kind": "host",
            "identifier": "192.0.2.20-27",
            "notes": "Example host range on the documentation LAN.",
        },
        {
            "kind": "host",
            "identifier": "192.0.2.30-33",
            "notes": "Example host range on the documentation LAN.",
        },
    ],
    "intended_policies": [
        {
            "identifier": "iot-isolated",
            "description": "The example isolated network is isolated.",
            "applies_to": ["203.0.113.0/24"],
        },
        {
            "identifier": "guest-isolated-internet-only",
            "description": (
                "The example guest network is isolated and permitted internet access only."
            ),
            "applies_to": ["203.0.113.128/25"],
        },
    ],
}


_IPV4_RE = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")


@pytest.fixture()
def profile_file(tmp_path: Path) -> Path:
    path = tmp_path / "site-profile.json"
    path.write_text(json.dumps(RELOCATED_SITE_PROFILE), encoding="utf-8")
    return path


def _write_profile(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _valid_profile() -> dict[str, Any]:
    """A deep copy, so a test that seeds a defect cannot corrupt the relocation record."""
    copied: dict[str, Any] = json.loads(json.dumps(RELOCATED_SITE_PROFILE))
    return copied


# --------------------------------------------------------------------------------------
# 0. The loader enforces the 1.1 contract the package documents
# --------------------------------------------------------------------------------------

_OPAQUE_TOKEN = "qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890"


def _profile_with_notes(version: str, notes: str) -> dict[str, Any]:
    document = _valid_profile()
    document["schema_version"] = version
    document["subjects"][0]["notes"] = notes
    return document


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_both_contract_versions_load(version: str) -> None:
    """The package documents ``1.1``; this loader ships inside that package.

    It was published pinned to ``1.0`` while the portable half advanced to ``1.1``, so an
    operator who wrote the document the package documents had it rejected here — one
    package disagreeing with itself.
    """
    loader.validate_profile(_profile_with_notes(version, "rack B, spare uplink"))


def test_an_unknown_contract_version_is_still_refused_outright() -> None:
    with pytest.raises(loader.UnsupportedSchemaVersionError):
        loader.validate_profile(_profile_with_notes("1.2", "rack B"))


@pytest.mark.parametrize("version", ["1.0", "1.1"])
@pytest.mark.parametrize(
    "notes",
    [
        f"authorization: Bearer {_OPAQUE_TOKEN}",
        f"authorization: Basic {_OPAQUE_TOKEN}",
        f"api_key={_OPAQUE_TOKEN}",
        "controller password=hunter2",
    ],
)
def test_a_credential_written_into_a_free_text_value_is_refused(version: str, notes: str) -> None:
    """``1.1`` is the version that says the secret-free guarantee covers values.

    A ``1.0`` document is held to it too, because a credential in a ``1.0`` profile is
    exactly as exposed. The scheme-word shapes matter on their own: grading only the first
    token of the value graded the word ``Bearer``, which carries no entropy, and cleared
    the credential standing behind it.
    """
    with pytest.raises(loader.ProfileInvalidError) as caught:
        loader.validate_profile(_profile_with_notes(version, notes))
    assert "credential value is not permitted" in str(caught.value)


@pytest.mark.parametrize(
    "notes",
    [
        f"authorization: Bearer <redacted> {_OPAQUE_TOKEN}",
        f"authorization: Bearer ${{UNIFI_API_KEY}} {_OPAQUE_TOKEN}",
        f"authorization: Bearer vault:infiquetra/unifi {_OPAQUE_TOKEN}",
    ],
)
def test_a_credential_hidden_behind_a_placeholder_is_refused(notes: str) -> None:
    """A placeholder between the scheme word and the credential ended the search.

    A fixed two-token window graded the placeholder, saw it names a secret rather
    than being one, and cleared the real credential standing behind it. The walk
    steps over both scheme words and placeholders instead of stopping at them.
    """
    document = _valid_profile()
    document["schema_version"] = "1.1"
    document["subjects"][0]["notes"] = notes
    with pytest.raises(loader.ProfileInvalidError) as caught:
        loader.validate_profile(document)
    assert "credential value is not permitted" in str(caught.value)


@pytest.mark.parametrize(
    "notes",
    [
        "api_key: vault:infiquetra/unifi#api_key",
        "password: <redacted>",
        "api_key: ${UNIFI_API_KEY}",
        # A reference written across several whitespace-separated pieces. Split
        # naively this yields a bare inner word as the candidate, so the
        # expression is collapsed to one placeholder before the value is split.
        "api_key: {{ lookup }}",
        "password: {{ vault_lookup site }}",
        "token: %(UNIFI_TOKEN)s",
        "see the runbook for the rotation procedure",
        "the site uses certificate authentication end to end",
        # Prose whose first token is a long English word. Entropy per character
        # does not separate English from a credential -- `rotation` scores 2.50
        # against a 2.50 floor -- so grading token zero unconditionally rejected
        # these as credentials.
        "auth: rotation procedure documented in the runbook",
        "token: rotation happens quarterly",
        "secret: managed elsewhere",
        "auth: Rotation Procedure Documented",
        # Carries a digit, but is never graded: the walk stops at the first
        # substantive token rather than searching the sentence.
        "auth: see ticket ABC-1234 for rotation",
    ],
)
def test_a_value_that_names_where_a_secret_lives_is_accepted(notes: str) -> None:
    """A profile is expected to point at where the credential lives, so these must pass.

    Ordinary prose has to pass too: several English words clear the entropy floor on their
    own, so a rule that graded every token of a value would fire on a sentence.
    """
    loader.validate_profile(_profile_with_notes("1.1", notes))


@pytest.mark.parametrize(
    "notes",
    [
        # Digit-free, dictionary-word passwords. The retired rule required a
        # digit or twenty-four characters before a value counted, so every one of
        # these shipped accepted -- the rule refused technical prose and let real
        # passwords through, in that order.
        "password: rainbowtrout",
        "password: sunshine",
        "api_key: correcthorsebattery",
        "passphrase: correcthorsebattery",
        # Short and low entropy. Under a strict key there is no floor below which
        # a literal stops being a credential.
        "password: secret",
        "password: hunter2",
        # A lone English word is still a lone literal, which is what makes this
        # the one case the previous suite asserted the other way round.
        "secret: internationalization",
        # A literal padded with a placeholder must not be cleared by it.
        "password: rainbowtrout <redacted>",
        # A harmless key must not swallow a strict one standing inside its
        # value: the scan has to resume at the delimiter, not past the whole
        # value it just read.
        "notes: controller password=hunter2",
        "description: call it with bearer=aB9dEf2GhJ4kLm7Q",
    ],
)
def test_a_literal_under_a_strict_key_is_refused_whatever_it_looks_like(notes: str) -> None:
    """The key decides, not the value.

    Every value here was accepted by the entropy-and-digit rule this replaced.
    None of them is a placeholder or a reference, so under a key the contract
    calls secret-bearing each one is a credential.
    """
    with pytest.raises(loader.ProfileInvalidError) as caught:
        loader.validate_profile(_profile_with_notes("1.1", notes))
    assert "credential value is not permitted" in str(caught.value)


@pytest.mark.parametrize(
    "notes",
    [
        # Technical vocabulary carrying a digit. The retired rule read the digit
        # as proof of a credential and refused all of these in a `notes` field.
        "credentials: oauth2 is configured at the controller",
        "token: base64 of the site identifier",
        "secret: sha256 checksum recorded in the manifest",
        "auth: vlan40 handles the guest network",
        "password: md5 is not used anywhere in this site",
        "api_key: utf8 encoding is assumed throughout",
        # The same words with no assignment at all.
        "the controller uses oauth2 for operator access",
        "sha256 digests are recorded beside each export",
    ],
)
def test_technical_prose_in_a_descriptive_field_is_accepted(notes: str) -> None:
    """A sentence about a credential is not a credential.

    ``notes`` is one of the two fields the schema keeps for operator prose, so a
    strict key followed by several substantive words is a description. This is
    the class the digit test refused: `oauth2` carries a digit and 2.585 bits,
    which is *less* entropy than `rainbowtrout`, so grading the value grades the
    wrong thing.
    """
    loader.validate_profile(_profile_with_notes("1.1", notes))


def test_the_prose_allowance_does_not_reach_a_structured_field() -> None:
    """Only the prose fields get the several-words allowance.

    Every other field in the contract holds an identifier or an enumerated value,
    so a sentence there is not prose -- it is a value that should not be shaped
    like one, and the strict reading applies.
    """
    document = _valid_profile()
    document["schema_version"] = "1.1"
    document["site"]["identifier"] = "credentials: oauth2 is configured here"
    with pytest.raises(loader.ProfileInvalidError) as caught:
        loader.validate_profile(document)
    assert "credential value is not permitted" in str(caught.value)


def test_the_strict_key_set_is_the_property_name_taxonomy() -> None:
    """The two halves of one rule must not drift into two dialects.

    ``_credential_field`` grades property *names* and ``_credential_in_text``
    grades keys written inside a value. They read the same fragment list, and
    this fails if a later edit gives either one its own.
    """
    for fragment in loader.CREDENTIAL_NAME_FRAGMENTS:
        assert loader._is_strict_credential_key(fragment)
        assert loader._is_strict_credential_key(fragment.upper())
    for extra in loader.CREDENTIAL_KEY_EXACT_IN_TEXT:
        assert loader._is_strict_credential_key(extra)
    # Matched whole, not as a substring, or an ordinary metadata key becomes a
    # credential key: `author` contains `auth`.
    assert not loader._is_strict_credential_key("author")
    assert not loader._is_strict_credential_key("description")
    assert not loader._is_strict_credential_key("notes")


def test_the_descriptive_fields_are_declared_by_the_schema() -> None:
    """``DESCRIPTIVE_FIELDS`` is derived from the contract, not remembered.

    A field that stops being part of the schema must stop being a prose field in
    the same edit, which is what deriving it from the field tuples buys.
    """
    schema_fields = set(
        loader.SITE_FIELDS + loader.SUBJECT_FIELDS + loader.POLICY_FIELDS + loader.CONSTRAINT_FIELDS
    )
    assert schema_fields >= loader.DESCRIPTIVE_FIELDS
    assert {"description", "notes"} == loader.DESCRIPTIVE_FIELDS


# --------------------------------------------------------------------------------------
# 1. The agent carries no address, and the relocation lost nothing
# --------------------------------------------------------------------------------------


def test_agent_definition_contains_no_address_literal() -> None:
    """No IPv4 literal survives anywhere in the agent definition."""
    found = _IPV4_RE.findall(AGENT_DOC.read_text(encoding="utf-8"))
    assert found == [], f"agent definition still names addresses: {sorted(set(found))}"


def test_plugin_contains_no_controller_address_literal() -> None:
    """The operator's controller address appears nowhere under ``plugins/unifi``."""
    offenders = subprocess.run(
        ["grep", "-rIlF", "--exclude-dir=tests", "10.220.", str(PLUGIN_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert offenders == [], f"operator addressing survives in: {offenders}"


def test_agent_points_at_the_loader_it_must_read() -> None:
    """A contract nothing presents is not reachable, so the agent names the loader."""
    text = AGENT_DOC.read_text(encoding="utf-8")
    assert "site_profile_loader.py" in text
    assert loader.ENVIRONMENT_VARIABLE in text
    assert loader.DISCOVERY_ONLY_MODE in text


def test_relocated_profile_validates_against_the_loader() -> None:
    """The relocation target is a valid document under the contract it claims."""
    assert loader.validate_profile(_valid_profile()) is not None


def test_relocated_profile_infers_no_intent_it_was_not_given() -> None:
    """Only the one trust role the prior text stated is present; nothing else was invented."""
    subjects = RELOCATED_SITE_PROFILE["subjects"]
    assert not any("criticality" in subject for subject in subjects)
    assert not any("ownership" in subject for subject in subjects)
    with_trust = {
        subject["identifier"] for subject in subjects if subject.get("trust_role") is not None
    }
    assert with_trust == {"192.0.2.1", "192.0.2.0/24"}


# --------------------------------------------------------------------------------------
# 2. Resolution order: environment, then configuration, then none
# --------------------------------------------------------------------------------------


def test_no_profile_anywhere_loads_in_discovery_only_mode(tmp_path: Path) -> None:
    """Absence is a supported state, not an error."""
    context = loader.load_site_context(environ={}, config_path=tmp_path / "absent.json")

    assert context.mode == loader.DISCOVERY_ONLY_MODE
    assert context.has_profile is False
    assert context.path is None


def test_environment_variable_overrides_a_different_configured_path(
    tmp_path: Path, profile_file: Path
) -> None:
    """``UNIFI_SITE_PROFILE`` wins over the remembered configured path."""
    other = _write_profile(
        tmp_path / "other.json",
        {"schema_version": "1.0", "site": {"identifier": "somewhere-else"}},
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"site_profile_path": str(other)}), encoding="utf-8")

    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(profile_file)}, config_path=config
    )

    assert context.source == loader.ENVIRONMENT_SOURCE
    assert context.path == profile_file
    assert context.profile is not None
    assert context.profile.site_identifier == "example-site"


def test_environment_variable_naming_a_missing_path_fails_loudly(tmp_path: Path) -> None:
    """A named-but-missing profile never degrades to the configured path."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"site_profile_path": str(tmp_path / "real.json")}))

    with pytest.raises(loader.ProfileNotFoundError) as excinfo:
        loader.load_site_context(
            environ={loader.ENVIRONMENT_VARIABLE: str(tmp_path / "gone.json")},
            config_path=config,
        )

    assert loader.ENVIRONMENT_VARIABLE in str(excinfo.value)


def test_empty_environment_variable_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    """An empty override is a mistake, not a request for discovery-only mode."""
    with pytest.raises(loader.ProfileConfigurationError):
        loader.load_site_context(
            environ={loader.ENVIRONMENT_VARIABLE: "   "}, config_path=tmp_path / "config.json"
        )


def test_configured_path_is_used_when_the_environment_says_nothing(
    tmp_path: Path, profile_file: Path
) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"site_profile_path": str(profile_file)}), encoding="utf-8")

    context = loader.load_site_context(environ={}, config_path=config)

    assert context.source == loader.CONFIGURED_SOURCE
    assert context.mode == loader.PROFILE_MODE


def test_configured_path_that_no_longer_exists_is_reported(tmp_path: Path) -> None:
    """Reverting silently to discovery-only would hide a broken deployment."""
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"site_profile_path": str(tmp_path / "gone.json")}))

    with pytest.raises(loader.ProfileNotFoundError) as excinfo:
        loader.load_site_context(environ={}, config_path=config)

    assert "no longer exists" in str(excinfo.value)


def test_default_paths_follow_the_xdg_base_directory_specification() -> None:
    environ = {"XDG_CONFIG_HOME": "/xdg"}

    assert loader.config_file_path(environ) == Path("/xdg/infiquetra/unifi/config.json")
    assert loader.default_profile_path(environ) == Path("/xdg/infiquetra/unifi/site-profile.json")
    assert loader.config_file_path({"HOME": "/home/op"}) == Path(
        "/home/op/.config/infiquetra/unifi/config.json"
    )


# --------------------------------------------------------------------------------------
# 3. Validation: the schema version, closed fields, and the credential rule
# --------------------------------------------------------------------------------------


def test_loader_is_pinned_to_the_released_contract() -> None:
    assert loader.SCHEMA_IDENTIFIER == "urn:infiquetra:unifi:site-profile:1.1"
    assert loader.SUPPORTED_SCHEMA_VERSIONS == ("1.0", "1.1")


def test_unrecognized_schema_version_is_rejected_rather_than_partially_applied() -> None:
    document = _valid_profile()
    document["schema_version"] = "2.0"

    with pytest.raises(loader.UnsupportedSchemaVersionError) as excinfo:
        loader.validate_profile(document)

    assert "2.0" in str(excinfo.value)


@pytest.mark.parametrize(
    "field", ["api_key", "password", "authToken", "client_secret", "private_key"]
)
def test_credential_shaped_field_is_rejected_naming_the_offender(field: str) -> None:
    document = _valid_profile()
    document["subjects"][0][field] = "leaked"

    with pytest.raises(loader.ProfileInvalidError) as excinfo:
        loader.validate_profile(document)

    message = str(excinfo.value)
    assert "credential-shaped" in message
    assert field in message


def test_unknown_top_level_field_is_rejected() -> None:
    document = _valid_profile()
    document["discovered_inventory"] = []

    with pytest.raises(loader.ProfileInvalidError) as excinfo:
        loader.validate_profile(document)

    assert "discovered_inventory" in str(excinfo.value)


def test_subject_kind_outside_the_contract_is_rejected() -> None:
    document = _valid_profile()
    document["subjects"][0]["kind"] = "router"

    with pytest.raises(loader.ProfileInvalidError):
        loader.validate_profile(document)


def test_duplicate_subject_is_rejected() -> None:
    document = _valid_profile()
    document["subjects"].append(dict(document["subjects"][0]))

    with pytest.raises(loader.ProfileInvalidError) as excinfo:
        loader.validate_profile(document)

    assert "duplicates subject" in str(excinfo.value)


def test_unparseable_profile_is_reported_as_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(loader.ProfileUnreadableError):
        loader.load_profile_document(path)


# --------------------------------------------------------------------------------------
# 4. The no-inference rule
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["trust_role", "criticality", "ownership", "intended_policies"])
def test_discovery_only_mode_returns_the_explicit_unknown(tmp_path: Path, query: str) -> None:
    context = loader.load_site_context(environ={}, config_path=tmp_path / "absent.json")

    answer = getattr(context, query)("192.0.2.1", kind="device")

    assert answer is loader.UNKNOWN
    assert str(answer) == "unknown"
    assert not answer


def test_subject_the_profile_does_not_name_is_unknown_not_defaulted(profile_file: Path) -> None:
    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(profile_file)}, config_path=None
    )

    assert context.trust_role("203.0.113.9", kind="host") is loader.UNKNOWN
    assert context.criticality("203.0.113.9", kind="host") is loader.UNKNOWN


def test_named_subject_reports_the_operator_intent_it_was_given(profile_file: Path) -> None:
    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(profile_file)}, config_path=None
    )

    assert context.trust_role("192.0.2.1", kind="device") == "trusted"
    # Stated nowhere in the prior agent text, so still unknown rather than filled in.
    assert context.criticality("192.0.2.1", kind="device") is loader.UNKNOWN
    assert context.ownership("192.0.2.1", kind="device") is loader.UNKNOWN


def test_literal_unknown_in_a_document_reads_as_the_explicit_unknown(tmp_path: Path) -> None:
    document = _valid_profile()
    document["subjects"][0]["trust_role"] = "unknown"
    path = _write_profile(tmp_path / "site-profile.json", document)

    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(path)}, config_path=None
    )

    assert context.trust_role("192.0.2.1", kind="device") is loader.UNKNOWN


def test_intended_policies_resolve_for_a_named_subject(profile_file: Path) -> None:
    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(profile_file)}, config_path=None
    )

    policies = context.intended_policies("203.0.113.0/24", kind="network")

    assert [policy["identifier"] for policy in policies] == ["iot-isolated"]


def test_discovery_only_description_states_its_own_limits(tmp_path: Path) -> None:
    context = loader.load_site_context(environ={}, config_path=tmp_path / "absent.json")

    summary = context.describe()

    assert summary["mode"] == loader.DISCOVERY_ONLY_MODE
    assert summary["limits"] == list(loader.DISCOVERY_ONLY_LIMITS)
    assert set(summary["intent_fields"]) == set(loader.INTENT_FIELDS)
    assert set(summary["intent_fields"].values()) == {"unknown"}


def test_profile_mode_description_counts_what_it_holds(profile_file: Path) -> None:
    context = loader.load_site_context(
        environ={loader.ENVIRONMENT_VARIABLE: str(profile_file)}, config_path=None
    )

    summary = context.describe()

    assert summary["mode"] == loader.PROFILE_MODE
    assert summary["site_identifier"] == "example-site"
    assert summary["subject_count"] == len(RELOCATED_SITE_PROFILE["subjects"])
    assert summary["policy_count"] == len(RELOCATED_SITE_PROFILE["intended_policies"])
    assert "limits" not in summary


# --------------------------------------------------------------------------------------
# 5. The runtime promise: standard library only, and a usable command line
# --------------------------------------------------------------------------------------


def test_loader_imports_nothing_outside_the_standard_library(tmp_path: Path) -> None:
    """A host with no third-party parser can still read a profile.

    Asserted by executing the loader with every third-party path stripped from ``sys.path``,
    so an accidental dependency fails here rather than on a minimal runtime.
    """
    script = (
        "import sys;"
        "sys.path=[p for p in sys.path if 'site-packages' not in p and 'dist-packages' not in p];"
        "import importlib.util;"
        f"spec=importlib.util.spec_from_file_location('spl', {str(LOADER_PATH)!r});"
        "m=importlib.util.module_from_spec(spec);sys.modules['spl']=m;"
        "spec.loader.exec_module(m);"
        "print(m.SCHEMA_IDENTIFIER)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "urn:infiquetra:unifi:site-profile:1.1"


def test_command_line_reports_discovery_only_mode(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.delenv(loader.ENVIRONMENT_VARIABLE, raising=False)

    exit_code = loader.main(["--config-path", str(tmp_path / "absent.json")])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == loader.DISCOVERY_ONLY_MODE
    assert payload["subjects"] == []


def test_command_line_reports_a_resolved_profile(profile_file: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv(loader.ENVIRONMENT_VARIABLE, str(profile_file))

    exit_code = loader.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == loader.PROFILE_MODE
    assert len(payload["subjects"]) == len(RELOCATED_SITE_PROFILE["subjects"])
    assert len(payload["intended_policies"]) == len(RELOCATED_SITE_PROFILE["intended_policies"])


def test_command_line_reports_a_broken_profile_as_a_structured_error(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.setenv(loader.ENVIRONMENT_VARIABLE, str(tmp_path / "gone.json"))

    exit_code = loader.main([])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] is True
    assert payload["error_type"] == "ProfileNotFoundError"


# --------------------------------------------------------------------------------------
# One assignment is one line, and the gate must agree
# --------------------------------------------------------------------------------------

#: Lines whose verdict is pinned identically here and in the portable catalog's
#: two copies. A shared corpus exists because the three copies drifted apart on
#: shapes none of their individual suites carried: the loader read across a line
#: break and the repository gate did not, so one accepted a credential the other
#: refused. Per-part agreement tests could all pass while the verdicts differed.
CREDENTIAL_VERDICT_CORPUS = (
    # (text, fires)
    ("password: rainbowtrout", True),
    ("password: sunshine", True),
    ("api_key: correcthorsebattery", True),
    ("password: secret", True),
    ("password: hunter2", True),
    ("secret: internationalization", True),
    ("authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQ", True),
    ("password: abc123 <redacted>", True),
    ("notes: controller password=hunter2", True),
    ("description: call it with bearer=aB9dEf2GhJ4kLm7Q", True),
    # An innocent key must not eat the break and the strict assignment behind it.
    ("see notes:\npassword=hunter2", True),
    # Every key spelling that reaches the rule only through the exact in-text
    # set. `auth` and `accesskey` match no name fragment, so emptying that tuple
    # silently retires them; these entries are what makes that fail.
    ("auth: rainbowtrout", True),
    ("accesskey: rainbowtrout", True),
    ("access_key: rainbowtrout", True),
    ("access-key: rainbowtrout", True),
    ("clientsecret: rainbowtrout", True),
    ("client_secret: rainbowtrout", True),
    ("credentials: oauth2 is configured at the controller", False),
    ("token: base64 of the site identifier", False),
    ("secret: sha256 checksum recorded in the manifest", False),
    ("auth: vlan40 handles the guest network", False),
    ("token: rotation happens quarterly", False),
    ("auth: see ticket ABC-1234 for rotation", False),
    ("password: redacted", False),
    ("password: env:UNIFI_API_KEY", False),
    ("password: vault:kv/unifi", False),
    ("password: ${UNIFI_KEY}", False),
    ("api_key: {{ lookup }}", False),
    ("token: %(UNIFI_TOKEN)s", False),
    ("authorization: Bearer <token>", False),
    ("password: change-me", False),
    ("author: someone wrote this note", False),
    # An assignment split across a line break is matched by neither copy. The
    # reference documents exactly this, so it is pinned rather than described.
    ("password:\n  hunter2", False),
)


@pytest.mark.parametrize("text,fires", CREDENTIAL_VERDICT_CORPUS)
def test_the_verdict_corpus_is_the_rule(text: str, fires: bool) -> None:
    """Every corpus line, one verdict, pinned."""
    assert (loader._credential_in_text(text, descriptive=True) is not None) is fires


def test_an_innocent_key_does_not_eat_the_line_break_before_a_strict_one() -> None:
    """The residual half of the swallow defect, across a newline instead of along a line.

    `` \\s*`` around the delimiter spanned the line break, so ``see notes:`` matched,
    consumed the newline with it, and left ``password=hunter2`` with no preceding
    character to begin a fresh match against. The loader accepted the credential;
    the repository gate, which splits lines first, refused it. That divergence is
    the defect, and it is fail-open in the copy operators actually load.
    """
    document = _valid_profile()
    document["schema_version"] = "1.1"
    document["subjects"][0]["notes"] = "see notes:\npassword=hunter2"
    with pytest.raises(loader.ProfileInvalidError) as caught:
        loader.validate_profile(document)
    assert "credential value is not permitted" in str(caught.value)


def test_an_assignment_split_across_a_line_break_is_not_matched() -> None:
    """The reference says neither copy matches this, so it has to be true."""
    loader.validate_profile(_profile_with_notes("1.1", "password:\n  hunter2"))


#: Every boundary `str.splitlines()` recognises, plus the two-character sequence.
#: The rule's contract is "an assignment is one line", so both copies have to
#: agree on where a line ends. Naming only `\n` fixed one instance of that and
#: left nine, eight of them fail-open in the loader.
LINE_BREAKS = (
    ("newline", "\n"),
    ("carriage return", "\r"),
    ("CRLF", "\r\n"),
    ("vertical tab", "\x0b"),
    ("form feed", "\x0c"),
    ("file separator", "\x1c"),
    ("group separator", "\x1d"),
    ("record separator", "\x1e"),
    ("NEL", "\x85"),
    ("LINE SEPARATOR", "\u2028"),
    ("PARAGRAPH SEPARATOR", "\u2029"),
)


@pytest.mark.parametrize("name,character", LINE_BREAKS)
def test_an_innocent_key_never_eats_a_break_whichever_break_it_is(
    name: str, character: str
) -> None:
    """The swallow shape, once per boundary the gate recognises.

    Reachable through ordinary JSON: a carriage return survives as the standard
    `\r` escape, and LINE SEPARATOR is legal literally inside a JSON string.
    """
    text = f"see notes:{character}password=hunter2"
    assert loader._credential_in_text(text, descriptive=True) is not None, name


@pytest.mark.parametrize("name,character", LINE_BREAKS)
def test_a_split_assignment_is_matched_at_no_boundary(name: str, character: str) -> None:
    """The documented sentence, once per boundary."""
    text = f"password:{character}  hunter2"
    assert loader._credential_in_text(text, descriptive=True) is None, name


def test_the_break_set_is_exactly_what_splitlines_recognises() -> None:
    """Derived from the standard library's behaviour, not from memory.

    If a future Python adds a boundary, this fails rather than letting the two
    copies quietly disagree about where a line ends again.
    """
    recognised = {
        chr(code)
        for code in list(range(0x20)) + [0x85, 0x2028, 0x2029]
        if len(f"a{chr(code)}b".splitlines()) > 1
    }
    assert set(loader.CREDENTIAL_LINE_BREAKS) == recognised


def test_the_exact_key_set_cannot_be_emptied_without_failures() -> None:
    """A-02: the tuple must be load-bearing, not decorative.

    Iterating `CREDENTIAL_KEY_EXACT_IN_TEXT` to assert its members are strict is
    vacuous -- empty the tuple and the loop body never runs. These spellings are
    written out literally and checked by behaviour, so retiring the tuple retires
    a verdict and fails here.

    `auth` and `accesskey` match no name fragment and reach the rule only through
    that tuple. `clientsecret` normalises to contain `secret`, so it is covered by
    the fragment path as well; it is included because the contract names it, not
    because it proves the tuple.
    """
    for key in ("auth", "accesskey", "access_key", "access-key"):
        text = f"{key}: rainbowtrout"
        assert loader._credential_in_text(text, descriptive=True) is not None, key
        assert loader._is_strict_credential_key(key), key
    for key in ("clientsecret", "client_secret"):
        assert loader._is_strict_credential_key(key), key
    # And the derived half, so retiring a fragment fails here too.
    for fragment in loader.CREDENTIAL_NAME_FRAGMENTS:
        text = f"{fragment}: rainbowtrout"
        assert loader._credential_in_text(text, descriptive=True) is not None, fragment
