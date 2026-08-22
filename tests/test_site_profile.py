"""Tests for the portable UniFi operator site-profile contract.

Standard library only, so this suite runs in the repository's hermetic
validation job as well as under pytest in the dependency-bearing job.
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
