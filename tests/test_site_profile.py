"""Tests for the portable UniFi operator site-profile contract.

Standard library only, so this suite runs in the repository's hermetic
validation job as well as under pytest in the dependency-bearing job.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIFI_SCRIPTS = ROOT / "plugins" / "unifi" / "scripts"
SCHEMA_PATH = ROOT / "plugins" / "unifi" / "schemas" / "site-profile.schema.json"
sys.path.insert(0, str(UNIFI_SCRIPTS))
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import site_profile  # noqa: E402


VALID_PROFILE = {
    "schema_version": "1.0",
    "site": {
        "identifier": "example-site",
        "description": "Inert example values only; no real site is described here.",
    },
    "subjects": [
        {
            "kind": "host",
            "identifier": "example-host",
            "trust_role": "trusted",
            "criticality": "critical",
            "ownership": "example-team",
            "notes": "Operator-supplied intent, not observed state.",
        },
        {
            "kind": "network",
            "identifier": "example-network",
            "trust_role": "restricted",
        },
    ],
    "intended_policies": [
        {
            "identifier": "example-policy",
            "description": "Example hosts stay off the guest network.",
            "applies_to": ["example-host"],
        }
    ],
    "operational_constraints": [
        {
            "identifier": "example-constraint",
            "description": "Changes are applied during the example maintenance window.",
        }
    ],
}


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


class TemporaryTreeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.config_path = self.root / "config.json"

    def write_profile(self, name: str = "site-profile.json", payload: object | None = None) -> Path:
        return write_json(self.root / name, VALID_PROFILE if payload is None else payload)

    def write_config(self, **fields: object) -> Path:
        payload = {"config_version": site_profile.CONFIG_VERSION}
        payload.update(fields)
        return write_json(self.config_path, payload)


class NoProfileTest(TemporaryTreeTest):
    def test_loading_without_any_profile_reports_discovery_only(self) -> None:
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.mode, site_profile.DISCOVERY_ONLY_MODE)
        self.assertIsNone(context.path)
        self.assertIsNone(context.source)
        self.assertFalse(context.has_profile)

    def test_intent_queries_without_a_profile_return_the_explicit_unknown(self) -> None:
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        for query in (
            context.trust_role("example-host"),
            context.criticality("example-host"),
            context.ownership("example-host"),
            context.intended_policies("example-host"),
            context.operational_constraints(),
        ):
            self.assertIs(query, site_profile.UNKNOWN)
            self.assertFalse(query)
            self.assertEqual(str(query), "unknown")

    def test_discovery_only_description_states_its_own_limits(self) -> None:
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        summary = context.describe()
        self.assertEqual(summary["mode"], site_profile.DISCOVERY_ONLY_MODE)
        self.assertEqual(
            summary["intent_fields"],
            {field: "unknown" for field in site_profile.INTENT_FIELDS},
        )
        self.assertTrue(summary["limits"])

    def test_known_subjects_without_a_profile_is_empty_rather_than_invented(self) -> None:
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.known_subjects(), ())


class ResolutionTest(TemporaryTreeTest):
    def test_environment_variable_overrides_the_remembered_configured_path(self) -> None:
        configured = self.write_profile("configured-profile.json")
        overriding = dict(VALID_PROFILE)
        overriding["site"] = {"identifier": "override-site"}
        override_path = self.write_profile("override-profile.json", overriding)
        self.write_config(site_profile_path=str(configured))

        context = site_profile.load_site_context(
            environ={site_profile.ENVIRONMENT_VARIABLE: str(override_path)},
            config_path=self.config_path,
        )
        self.assertEqual(context.source, site_profile.ENVIRONMENT_SOURCE)
        self.assertEqual(context.path, override_path)
        self.assertEqual(context.profile.site_identifier, "override-site")

    def test_environment_variable_naming_a_missing_file_fails_without_falling_back(self) -> None:
        configured = self.write_profile("configured-profile.json")
        self.write_config(site_profile_path=str(configured))
        missing = self.root / "absent-profile.json"

        with self.assertRaises(site_profile.ProfileNotFoundError) as raised:
            site_profile.load_site_context(
                environ={site_profile.ENVIRONMENT_VARIABLE: str(missing)},
                config_path=self.config_path,
            )
        message = str(raised.exception)
        self.assertIn(site_profile.ENVIRONMENT_VARIABLE, message)
        self.assertIn(str(missing), message)
        self.assertNotIn(str(configured), message)

    def test_present_but_empty_environment_variable_fails_loudly(self) -> None:
        with self.assertRaises(site_profile.ProfileConfigurationError) as raised:
            site_profile.load_site_context(
                environ={site_profile.ENVIRONMENT_VARIABLE: "   "},
                config_path=self.config_path,
            )
        self.assertIn(site_profile.ENVIRONMENT_VARIABLE, str(raised.exception))

    def test_configured_path_that_no_longer_exists_is_reported_clearly(self) -> None:
        vanished = self.root / "vanished-profile.json"
        self.write_config(site_profile_path=str(vanished))

        with self.assertRaises(site_profile.ProfileNotFoundError) as raised:
            site_profile.load_site_context(environ={}, config_path=self.config_path)
        message = str(raised.exception)
        self.assertIn(str(vanished), message)
        self.assertIn(str(self.config_path), message)

    def test_configuration_recording_discovery_only_loads_without_a_profile(self) -> None:
        self.write_config(setup_path="discovery-only", site_profile_path=None)
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.mode, site_profile.DISCOVERY_ONLY_MODE)

    def test_configured_path_is_used_when_no_environment_override_is_present(self) -> None:
        configured = self.write_profile("configured-profile.json")
        self.write_config(site_profile_path=str(configured))
        context = site_profile.load_site_context(environ={}, config_path=self.config_path)
        self.assertEqual(context.source, site_profile.CONFIGURED_SOURCE)
        self.assertEqual(context.path, configured)

    def test_config_and_profile_default_paths_follow_the_documented_locations(self) -> None:
        environ = {"XDG_CONFIG_HOME": "/example/config"}
        self.assertEqual(
            site_profile.config_file_path(environ),
            Path("/example/config/infiquetra/unifi/config.json"),
        )
        self.assertEqual(
            site_profile.default_profile_path(environ),
            Path("/example/config/infiquetra/unifi/site-profile.json"),
        )
        fallback = {"HOME": "/example/home"}
        self.assertEqual(
            site_profile.config_file_path(fallback),
            Path("/example/home/.config/infiquetra/unifi/config.json"),
        )


class ValidationTest(TemporaryTreeTest):
    def test_credential_shaped_field_is_rejected_naming_the_offending_field(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["api_token"] = "inert-example-value"
        path = self.write_profile("credential-profile.json", payload)

        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.load_profile_document(path)
        message = str(raised.exception)
        self.assertIn("credential", message)
        self.assertIn("api_token", message)

    def test_every_credential_name_fragment_is_rejected_wherever_it_appears(self) -> None:
        for fragment in site_profile.CREDENTIAL_NAME_FRAGMENTS:
            with self.subTest(fragment=fragment):
                payload = json.loads(json.dumps(VALID_PROFILE))
                field = f"site_{fragment}"
                payload["site"][field] = "inert-example-value"
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn(field, str(raised.exception))

    def test_credential_in_notes_is_rejected_naming_the_field_and_the_reason(self) -> None:
        """The proof both cycle-two reviewers ran, and it must now fail closed.

        Before the value rule this exact document validated successfully, which
        is what made the printed guarantee false: the field name ``notes`` is
        innocent and every guard in the contract read names only.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["notes"] = "controller password=hunter2"
        path = self.write_profile("leaked-notes.json", payload)

        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.load_profile_document(path)
        message = str(raised.exception)
        self.assertIn("credential value", message)
        self.assertIn("subjects[0].notes", message)
        self.assertIn("password", message)

    def test_credential_in_a_description_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["site"]["description"] = "Example site. api_key=A9f2Kd81LmQz47Rb"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("site.description", str(raised.exception))

    def test_credential_in_ownership_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["ownership"] = "example-team, token=Qa7Rm2Xp90Lt"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("subjects[0].ownership", str(raised.exception))

    def test_a_credential_value_is_rejected_wherever_a_string_may_appear(self) -> None:
        """Every free-text location in the contract, not just the ones reviewed."""
        secret = "controller password=hunter2"
        placements = {
            "site.description": lambda p: p["site"].__setitem__("description", secret),
            "subjects[0].notes": lambda p: p["subjects"][0].__setitem__("notes", secret),
            "subjects[0].ownership": lambda p: p["subjects"][0].__setitem__("ownership", secret),
            "intended_policies[0].description": (
                lambda p: p["intended_policies"][0].__setitem__("description", secret)
            ),
            "operational_constraints[0].description": (
                lambda p: p["operational_constraints"][0].__setitem__("description", secret)
            ),
        }
        for location, place in placements.items():
            with self.subTest(location=location):
                payload = json.loads(json.dumps(VALID_PROFILE))
                place(payload)
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn(location, str(raised.exception))

    def test_every_literal_credential_format_is_rejected_in_a_value(self) -> None:
        samples = {
            "AWS access key id": "AKIAIOSFODNN7EXAMPLE",
            "GitHub token": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
            "GitHub fine-grained token": "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0",
            "Slack token": "xoxb-1234567890-abcdefghij",
            "Stripe secret key": "sk_live_" + "A1b2C3d4E5f6G7h8",
            "Google API key": "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r",
            "Anthropic API key": "sk-ant-" + "A1b2C3d4E5f6G7h8I9j0K1l2",
            "OpenAI API key": "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
            "JSON web token": (
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27u"
            ),
            "private key block": "-----BEGIN RSA PRIVATE KEY-----",
            "credential embedded in a URL": "https://operator:s3cr3tvalue@controller.example",
        }
        declared = {label for label, _ in site_profile.CREDENTIAL_VALUE_FORMATS}
        self.assertEqual(set(samples), declared)
        for label, sample in samples.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = f"inert example: {sample}"
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn(label, str(raised.exception))

    def test_a_value_that_only_names_a_secret_is_accepted(self) -> None:
        """Pointing at where a credential lives is the profile's job, not a leak."""
        accepted = (
            "The controller password is held in the operator vault, never in this file.",
            "Rotate the API key with the team that owns this subject.",
            "api_key=vault:infiquetra/unifi/controller",
            "password=<redacted>",
            "token=${UNIFI_API_TOKEN}",
            "client_secret=redacted",
            "Secrets for this host are managed outside the profile.",
        )
        for note in accepted:
            with self.subTest(note=note):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = note
                self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_a_legitimate_sha256_digest_is_accepted(self) -> None:
        """A bare high-entropy scan would reject this, which is why there is none.

        Profiles carry digests and long identifiers as a matter of course. A rule
        that fires on them is a rule an operator switches off, so the value check
        is two narrow families and never bare entropy.
        """
        digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["notes"] = f"Configuration digest {digest}"
        payload["site"]["description"] = digest
        payload["operational_constraints"][0]["description"] = (
            f"Only the configuration whose sha256 is {digest} may be applied."
        )
        self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_a_short_low_entropy_literal_under_a_strict_key_is_refused(self) -> None:
        """The limit this used to admit is gone, and the reference says so.

        `password: secret` was accepted because it sat below an entropy floor.
        There is no floor now: under a strict key a lone substantive literal is a
        credential whatever it looks like. The guarantee in
        ``references/site-profile.md`` states the stronger rule, and this test
        exists so that wording stays true rather than aspirational.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["notes"] = "password=secret"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("credential value", str(raised.exception))

    def test_the_documented_prose_padding_limit_is_pinned(self) -> None:
        """The one limit the reference still admits, pinned so it stays honest.

        A literal padded out with prose under a strict key in a prose field is
        not reported. Recording it as a test is what keeps the documented limit
        and the shipped behaviour the same sentence.
        """
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["notes"] = "password: rainbowtrout is the controller value"
        self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_the_value_rule_applies_to_a_document_declaring_the_older_version(self) -> None:
        """A credential in a 1.0 profile is exactly as exposed as one in a 1.1."""
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["schema_version"] = "1.0"
        payload["subjects"][0]["notes"] = "controller password=hunter2"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("credential value", str(raised.exception))

    def test_a_credential_behind_an_auth_scheme_word_is_caught(self) -> None:
        """``authorization: Bearer <token>`` is the shape an operator actually pastes.

        The rule graded only the first token of the assigned value, which here is the
        word ``Bearer`` -- no entropy, so the credential standing behind it was cleared.
        ``Basic`` and ``Token`` are shorter than the length floor, so the pattern did not
        match at all and those values were never examined.
        """
        token = "qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890"
        for value in (
            f"authorization: Bearer {token}",
            f"authorization: Basic {token}",
            f"Authorization: Bearer {token}",
            f"token: Token {token}",
            f"authorization: Digest {token}",
            # A placeholder standing between the scheme word and the credential
            # used to end the search: a fixed two-token window graded the
            # placeholder, saw that it names a secret rather than being one, and
            # cleared the real credential behind it.
            f"authorization: Bearer <redacted> {token}",
            f"authorization: Bearer ${{UNIFI_API_KEY}} {token}",
            f"authorization: Bearer vault:infiquetra/unifi {token}",
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = value
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn("credential value", str(raised.exception))

    def test_a_digitless_literal_under_a_strict_key_is_refused(self) -> None:
        """The class the retired rule let through, in the copy operators load.

        A digit-free value had to reach twenty-four characters before it counted,
        so every one of these shipped accepted -- while ``oauth2``, which carries
        *less* entropy per character than ``rainbowtrout``, was refused. The rule
        graded the value and the value cannot tell you this.
        """
        for value in (
            "password: rainbowtrout",
            "password: sunshine",
            "api_key: correcthorsebattery",
            "passphrase: correcthorsebattery",
            "client_secret: managedvalue",
            "password: rainbowtrout <redacted>",
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = value
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn("credential value", str(raised.exception))

    def test_technical_prose_in_a_descriptive_field_is_accepted(self) -> None:
        """The class the retired rule refused, in the copy operators load.

        ``description`` and ``notes`` are the two fields the schema keeps for
        prose, so a strict key followed by several substantive words is a
        sentence about a credential rather than a credential.
        """
        for field, value in (
            ("notes", "credentials: oauth2 is configured at the controller"),
            ("notes", "token: base64 of the site identifier"),
            ("notes", "secret: sha256 checksum recorded in the manifest"),
            ("notes", "auth: vlan40 handles the guest network"),
            ("notes", "password: md5 is not used anywhere in this site"),
            ("notes", "the controller uses oauth2 for operator access"),
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0][field] = value
                self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_the_prose_allowance_does_not_reach_a_structured_field(self) -> None:
        """Only the two prose fields get the several-words allowance."""
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["site"]["identifier"] = "credentials: oauth2 is configured here"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("credential value", str(raised.exception))

    def test_the_established_safe_forms_still_pass(self) -> None:
        """Placeholders, references, schemes and prose, unchanged by this rewrite."""
        for value in (
            "password: <redacted>",
            "api_key: ${UNIFI_API_KEY}",
            "api_key: {{ lookup }}",
            "token: %(UNIFI_TOKEN)s",
            "api_key: vault:infiquetra/unifi#api_key",
            "password: env:UNIFI_API_KEY",
            "password: op://vault/item",
            "password: change-me",
            "authorization: Bearer <token>",
            "auth: see ticket ABC-1234 for rotation",
            "token: rotation happens quarterly",
            "secret: managed elsewhere",
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = value
                self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_an_innocent_key_does_not_swallow_a_strict_one(self) -> None:
        """Two assignments on one line: the scan must resume at the delimiter."""
        for value in (
            "notes: controller password=hunter2",
            "description: call it with bearer=aB9dEf2GhJ4kLm7Q",
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = value
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn("credential value", str(raised.exception))

    def test_the_descriptive_fields_are_declared_by_the_schema(self) -> None:
        """Derived from the contract, not remembered separately."""
        schema_fields = set(
            site_profile.SITE_FIELDS
            + site_profile.SUBJECT_FIELDS
            + site_profile.POLICY_FIELDS
            + site_profile.CONSTRAINT_FIELDS
        )
        self.assertLessEqual(site_profile.DESCRIPTIVE_FIELDS, schema_fields)
        self.assertEqual(site_profile.DESCRIPTIVE_FIELDS, {"description", "notes"})

    def test_the_strict_key_set_is_the_property_name_taxonomy(self) -> None:
        """One taxonomy grades property names and in-text keys alike."""
        for fragment in site_profile.CREDENTIAL_NAME_FRAGMENTS:
            self.assertTrue(site_profile._is_strict_credential_key(fragment))
            self.assertTrue(site_profile._is_strict_credential_key(fragment.upper()))
        for extra in site_profile.CREDENTIAL_KEY_EXACT_IN_TEXT:
            self.assertTrue(site_profile._is_strict_credential_key(extra))
        # Matched whole, not as a substring: `author` contains `auth`.
        for innocent in ("author", "description", "notes", "identifier", "kind"):
            self.assertFalse(site_profile._is_strict_credential_key(innocent))

    def test_prose_after_a_credential_key_is_not_graded(self) -> None:
        """Only the credential's own span is graded, never the sentence around it.

        Several ordinary English words clear the 2.5-bit floor on their own -- ``runbook``
        is 2.52 -- so a rule that graded every whitespace-separated token of the value
        would reject a profile for describing where the credential lives, which is exactly
        what a profile is supposed to do.
        """
        for value in (
            "auth: see the runbook for the rotation procedure",
            "authorization: Bearer token is stored in vault",
            "api_key: vault:infiquetra/unifi#api_key",
            "password: <redacted>",
            "api_key: ${UNIFI_API_KEY}",
            "the site uses certificate authentication end to end",
            # Prose whose FIRST token is a long English word. The earlier rule
            # graded token zero unconditionally, and entropy per character does
            # not separate English from a credential -- `rotation` scores 2.50
            # against a 2.50 floor -- so these were rejected as credentials.
            "auth: rotation procedure documented in the runbook",
            "token: rotation happens quarterly",
            "secret: managed elsewhere",
            "auth: Rotation Procedure Documented",
            # A ticket reference carries a digit. It is not graded because the
            # walk stops at the first substantive token rather than searching
            # the sentence for something that looks credential-shaped.
            "auth: see ticket ABC-1234 for rotation",
        ):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0]["notes"] = value
                self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_a_credential_shaped_name_is_reported_as_a_name_not_a_value(self) -> None:
        """Ordering matters: an inert value in a forbidden field is a field fault."""
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["api_token"] = "controller password=hunter2"
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("credential-shaped field", str(raised.exception))

    def test_both_supported_versions_load(self) -> None:
        for version in site_profile.SUPPORTED_SCHEMA_VERSIONS:
            with self.subTest(version=version):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["schema_version"] = version
                self.assertEqual(site_profile.validate_profile(payload), payload)

    def test_unrecognized_schema_version_is_rejected_rather_than_partially_applied(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["schema_version"] = "9.9"
        with self.assertRaises(site_profile.UnsupportedSchemaVersionError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("9.9", str(raised.exception))

    def test_missing_schema_version_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        del payload["schema_version"]
        with self.assertRaises(site_profile.UnsupportedSchemaVersionError):
            site_profile.validate_profile(payload)

    def test_unknown_top_level_field_is_rejected_by_name(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["controller_inventory"] = []
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("controller_inventory", str(raised.exception))

    def test_unknown_subject_kind_and_vocabulary_values_are_rejected(self) -> None:
        for field, value in (
            ("kind", "satellite"),
            ("trust_role", "mostly-trusted"),
            ("criticality", "urgent"),
        ):
            with self.subTest(field=field):
                payload = json.loads(json.dumps(VALID_PROFILE))
                payload["subjects"][0][field] = value
                with self.assertRaises(site_profile.ProfileInvalidError) as raised:
                    site_profile.validate_profile(payload)
                self.assertIn(value, str(raised.exception))

    def test_duplicate_subject_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"].append({"kind": "host", "identifier": "example-host"})
        with self.assertRaises(site_profile.ProfileInvalidError) as raised:
            site_profile.validate_profile(payload)
        self.assertIn("example-host", str(raised.exception))

    def test_unparseable_profile_fails_loudly_rather_than_degrading(self) -> None:
        path = self.root / "broken-profile.json"
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(site_profile.ProfileUnreadableError):
            site_profile.load_profile_document(path)

    def test_valid_profile_round_trips_through_the_loader(self) -> None:
        path = self.write_profile()
        document = site_profile.load_profile_document(path)
        self.assertEqual(document["site"]["identifier"], "example-site")


class ProfileQueryTest(TemporaryTreeTest):
    def context(self):
        path = self.write_profile()
        return site_profile.load_site_context(
            environ={site_profile.ENVIRONMENT_VARIABLE: str(path)},
            config_path=self.config_path,
        )

    def test_declared_intent_is_returned_verbatim(self) -> None:
        context = self.context()
        self.assertEqual(context.trust_role("example-host"), "trusted")
        self.assertEqual(context.criticality("example-host"), "critical")
        self.assertEqual(context.ownership("example-host"), "example-team")
        policies = context.intended_policies("example-host")
        self.assertEqual([policy["identifier"] for policy in policies], ["example-policy"])

    def test_subject_absent_from_the_profile_reports_unknown_rather_than_a_default(self) -> None:
        context = self.context()
        self.assertIs(context.trust_role("unlisted-host"), site_profile.UNKNOWN)
        self.assertIs(context.criticality("unlisted-host"), site_profile.UNKNOWN)
        self.assertIs(context.ownership("unlisted-host"), site_profile.UNKNOWN)
        self.assertIs(context.intended_policies("unlisted-host"), site_profile.UNKNOWN)

    def test_field_omitted_for_a_listed_subject_reports_unknown(self) -> None:
        context = self.context()
        self.assertIs(
            context.criticality("example-network", kind="network"), site_profile.UNKNOWN
        )
        self.assertEqual(
            context.trust_role("example-network", kind="network"), "restricted"
        )

    def test_literal_unknown_in_the_profile_is_the_explicit_unknown(self) -> None:
        payload = json.loads(json.dumps(VALID_PROFILE))
        payload["subjects"][0]["trust_role"] = "unknown"
        path = self.write_profile("unknown-profile.json", payload)
        context = site_profile.load_site_context(
            environ={site_profile.ENVIRONMENT_VARIABLE: str(path)},
            config_path=self.config_path,
        )
        self.assertIs(context.trust_role("example-host"), site_profile.UNKNOWN)

    def test_kind_is_part_of_subject_identity(self) -> None:
        context = self.context()
        self.assertIs(context.trust_role("example-network", kind="host"), site_profile.UNKNOWN)

    def test_describe_summarizes_a_loaded_profile(self) -> None:
        summary = self.context().describe()
        self.assertEqual(summary["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(summary["site_identifier"], "example-site")
        self.assertEqual(summary["subject_count"], 2)
        self.assertEqual(summary["policy_count"], 1)
        self.assertEqual(summary["constraint_count"], 1)


class StandardLibraryOnlyTest(TemporaryTreeTest):
    def test_loading_a_profile_needs_no_third_party_import(self) -> None:
        """Load a profile in an interpreter with no third-party path entries.

        ``-I`` isolates the interpreter from ``PYTHONPATH`` and the user site
        directory, and ``-S`` stops ``site-packages`` being added at all. The
        child asserts its own ``sys.path`` carries no third-party directory, so
        the test proves the absence rather than assuming it.
        """
        profile_path = self.write_profile()
        program = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(UNIFI_SCRIPTS)!r})\n"
            "import site_profile\n"
            "context = site_profile.load_site_context(\n"
            f"    environ={{'UNIFI_SITE_PROFILE': {str(profile_path)!r}}},\n"
            f"    config_path={str(self.config_path)!r},\n"
            ")\n"
            "third_party = [\n"
            "    entry for entry in sys.path\n"
            "    if 'site-packages' in entry or 'dist-packages' in entry\n"
            "]\n"
            "print(json.dumps({\n"
            "    'mode': context.mode,\n"
            "    'site': context.profile.site_identifier,\n"
            "    'trust_role': context.trust_role('example-host'),\n"
            "    'third_party_path_entries': third_party,\n"
            "}))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", program],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["third_party_path_entries"], [])
        self.assertEqual(report["mode"], site_profile.PROFILE_MODE)
        self.assertEqual(report["site"], "example-site")
        self.assertEqual(report["trust_role"], "trusted")


class SchemaDocumentTest(unittest.TestCase):
    """The published schema and the portable loader must agree.

    The loader is the enforcement point, because the repository's validation
    stays standard-library-only and Python ships no JSON Schema validator. The
    schema document is the contract third-party tooling reads, so the two are
    checked against each other rather than left to drift.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_schema_identifier_matches_the_loader(self) -> None:
        self.assertEqual(self.schema["$id"], site_profile.SCHEMA_IDENTIFIER)

    def test_schema_versions_match_the_loader(self) -> None:
        self.assertEqual(
            tuple(self.schema["properties"]["schema_version"]["enum"]),
            site_profile.SUPPORTED_SCHEMA_VERSIONS,
        )

    def test_vocabularies_match_the_loader(self) -> None:
        definitions = self.schema["$defs"]
        self.assertEqual(
            tuple(definitions["subject"]["properties"]["kind"]["enum"]),
            site_profile.SUBJECT_KINDS,
        )
        self.assertEqual(tuple(definitions["trustRole"]["enum"]), site_profile.TRUST_ROLES)
        self.assertEqual(
            tuple(definitions["criticality"]["enum"]), site_profile.CRITICALITY_LEVELS
        )

    def test_every_object_is_closed_and_guards_credential_property_names(self) -> None:
        candidates = [self.schema] + [
            definition
            for definition in self.schema["$defs"].values()
            if definition.get("type") == "object"
        ]
        self.assertGreater(len(candidates), 1)
        for definition in candidates:
            with self.subTest(title=definition.get("title") or definition.get("required")):
                self.assertIs(definition["additionalProperties"], False)
                self.assertEqual(
                    definition["propertyNames"],
                    {"$ref": "#/$defs/nonCredentialPropertyName"},
                )

    def test_credential_guard_names_every_fragment_the_loader_rejects(self) -> None:
        pattern = self.schema["$defs"]["nonCredentialPropertyName"]["not"]["pattern"]
        for fragment in site_profile.CREDENTIAL_NAME_FRAGMENTS:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, pattern)

    def test_every_free_text_value_is_guarded_against_credential_formats(self) -> None:
        """No string in the contract may be a plain unguarded string."""
        self.assertNotIn("nonEmptyText", json.dumps(self.schema))
        definitions = self.schema["$defs"]
        guarded = {"#/$defs/credentialFreeText", "#/$defs/identifier"}
        checked = 0
        for name, definition in definitions.items():
            if definition.get("type") != "object":
                continue
            for field, subschema in definition.get("properties", {}).items():
                with self.subTest(definition=name, field=field):
                    if "enum" in subschema:
                        # A closed vocabulary cannot hold a credential.
                        continue
                    reference = subschema.get("$ref") or subschema.get("items", {}).get("$ref")
                    self.assertIsNotNone(reference, "an unguarded inline string")
                    if "enum" in definitions[reference.rsplit("/", 1)[-1]]:
                        continue
                    self.assertIn(reference, guarded)
                    checked += 1
        self.assertGreater(checked, 5)

    def test_the_schema_rejects_the_same_literal_formats_as_the_loader(self) -> None:
        """The published contract and the enforcement point must not drift apart.

        A third-party validator reads the schema; the loader is what actually
        runs on an operator's machine. If one list grows a format the other does
        not, the contract quietly means two different things.
        """
        published = [
            entry["not"]["pattern"]
            for entry in self.schema["$defs"]["credentialFreeText"]["allOf"]
        ]
        enforced = [pattern.pattern for _, pattern in site_profile.CREDENTIAL_VALUE_FORMATS]
        self.assertEqual(published, enforced)


class CredentialRuleDriftTest(unittest.TestCase):
    """The portable loader and the repository gate must stay one rule.

    ``scripts/check_repo.py`` already solved credential-detection-by-value for
    the repository tree. The portable loader cannot import it: this module is
    package source that lands on an operator's machine and loads with the
    standard library alone, where that validator does not exist -- which is what
    :class:`StandardLibraryOnlyTest` proves. So the two families are re-stated in
    ``site_profile.py`` and pinned to the original here. A rule added to one copy
    and not the other fails this test rather than becoming a second dialect.
    """

    def test_the_literal_credential_formats_are_the_same_list(self) -> None:
        self.assertEqual(
            [(label, pattern.pattern) for label, pattern in check_repo.CREDENTIAL_FORMATS],
            [
                (label, pattern.pattern)
                for label, pattern in site_profile.CREDENTIAL_VALUE_FORMATS
            ],
        )

    def test_the_assignment_family_is_the_same_rule(self) -> None:
        self.assertEqual(
            check_repo.CREDENTIAL_PLACEHOLDER.pattern,
            site_profile.CREDENTIAL_VALUE_PLACEHOLDER.pattern,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_REFERENCE_PREFIX.pattern,
            site_profile.CREDENTIAL_VALUE_REFERENCE_PREFIX.pattern,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_SCHEME_WORDS,
            site_profile.CREDENTIAL_SCHEME_WORDS,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_NAME_FRAGMENTS,
            site_profile.CREDENTIAL_NAME_FRAGMENTS,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_KEY_EXACT_IN_TEXT,
            site_profile.CREDENTIAL_KEY_EXACT_IN_TEXT,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_TEMPLATE_EXPRESSION.pattern,
            site_profile.CREDENTIAL_TEMPLATE_EXPRESSION.pattern,
        )
        self.assertEqual(
            check_repo.CREDENTIAL_ASSIGNMENT_IN_TEXT.pattern,
            site_profile.CREDENTIAL_ASSIGNMENT_IN_TEXT.pattern,
        )

    def test_both_copies_reduce_a_value_to_the_same_tokens(self) -> None:
        """The token walk is what decides, so it is the likeliest half to drift."""
        spans = (
            "qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890",
            "Bearer qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890",
            "Basic  qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890",
            "Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890",
            "Bearer ${VAR} qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz1234567890",
            "{{ lookup }}",
            "%(UNIFI_TOKEN)s",
            "Bearer token is stored in vault",
            "see the runbook for the rotation procedure",
            "see ticket ABC-1234 for rotation",
            "rainbowtrout",
            "short",
            "",
        )
        for span in spans:
            with self.subTest(span=span):
                self.assertEqual(
                    check_repo._substantive_tokens(span),
                    site_profile._substantive_tokens(span),
                )

    def test_both_copies_agree_which_keys_are_strict(self) -> None:
        """One taxonomy, read by the gate and by the loader alike."""
        keys = (
            *site_profile.CREDENTIAL_NAME_FRAGMENTS,
            *site_profile.CREDENTIAL_KEY_EXACT_IN_TEXT,
            "API_KEY",
            "client_secret",
            "access-key",
            "author",
            "description",
            "notes",
            "identifier",
        )
        for key in keys:
            with self.subTest(key=key):
                self.assertEqual(
                    check_repo._is_strict_credential_key(key),
                    site_profile._is_strict_credential_key(key),
                )

    def test_both_copies_grade_the_same_values_the_same_way(self) -> None:
        samples = (
            "hunter2",
            "secret",
            "rainbowtrout",
            "AKIAIOSFODNN7EXAMPLE",
            "vault:infiquetra/unifi",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "<redacted>",
            "aaaaaaaa",
            "12345678",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(
                    check_repo._names_a_secret(sample),
                    site_profile._names_a_secret(sample),
                )

    def test_both_copies_reach_the_same_verdict_on_a_line(self) -> None:
        """The end-to-end pin: same line in, same verdict out, in both copies.

        The per-part pins above can all agree while the rules that read them
        disagree, so the verdict itself is pinned too.
        """
        lines = (
            "password: rainbowtrout",
            "password: sunshine",
            "api_key: correcthorsebattery",
            "password: secret",
            "password: hunter2",
            "authorization: Bearer <redacted> qY7vP2xK9rLm4aZbC8dEfGhJkNpQsTuWxYz12",
            "credentials: oauth2 is configured at the controller",
            "token: base64 of the site identifier",
            "secret: sha256 checksum recorded in the manifest",
            "auth: vlan40 handles the guest network",
            "auth: see ticket ABC-1234 for rotation",
            "password: env:UNIFI_API_KEY",
            "token: {{ lookup }}",
            "author: someone wrote this note",
        )
        for line in lines:
            with self.subTest(line=line):
                gate = bool(check_repo.credential_findings(line, include_assignments=True))
                loader = site_profile._credential_in_text(line, descriptive=True) is not None
                self.assertEqual(gate, loader)

    def test_the_portable_loader_does_not_import_the_repository_gate(self) -> None:
        """Prose may cite the gate; the module may not depend on it.

        Parsed rather than grepped, because the module deliberately *names*
        ``scripts/check_repo.py`` in a comment explaining why it re-states the
        rule instead of importing it.
        """
        tree = ast.parse(Path(site_profile.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("check_repo", imported)
        self.assertLessEqual(imported, set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
