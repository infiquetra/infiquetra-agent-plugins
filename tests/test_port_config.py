"""Tests for the per-package port descriptor.

The descriptor is the input that decides which tree a synchronization
overwrites and deletes inside, and which tree a compatibility matrix binds
itself to. Both of those are answers that used to be constants in a script,
where a wrong value was a code change someone reviewed. As data it is a file
someone edits, so the validator is what stands between a typo and a tool
writing into the wrong directory.

These tests derive their expectations from `port_config` rather than restating
them: the required-field lists, the custody class names, and the schema version
are read from the module, so adding a field fails here until the corpus covers
it rather than passing silently.

Standard library only, matching the validator and the repository baseline.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import port_config  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


def minimal(**overrides: object) -> dict:
    """The smallest descriptor that validates, with one field replaced."""
    document: dict = {
        "schema_version": port_config.SCHEMA_VERSION,
        "package": "example",
        "package_root": "plugins/example",
        "source": {
            "repository": "https://example.com/upstream",
            "package_path": "plugins/example",
        },
        "custody": {},
        # Every safety field is stated. A package with none of a given kind says
        # so in declared_none rather than leaving the field out, because an
        # absent safety field fails open.
        "assessment": {
            "credential_prefixes": ["EXAMPLE_"],
            "package_scripts": ["example.py"],
            "mutating_operations": ["delete"],
            "entrypoints": ["scripts/example.py"],
            "declared_none": [],
        },
    }
    document.update(overrides)
    return document


def parse(document: dict, name: str = "example") -> port_config.PortConfig:
    return port_config.parse(
        document,
        root=Path("/nowhere"),
        path=Path("/nowhere") / port_config.CONFIG_DIRECTORY_NAME / f"{name}.json",
    )


class ShapeTest(unittest.TestCase):
    def test_the_minimal_descriptor_validates(self) -> None:
        config = parse(minimal())
        self.assertEqual(config.name, "example")
        self.assertEqual(config.package_manifest, "plugin.json")

    def test_every_required_field_is_required(self) -> None:
        """The corpus is the module's own list, so a new required field is covered."""
        for field in port_config.REQUIRED_TOP_LEVEL:
            with self.subTest(field=field):
                document = minimal()
                del document[field]
                with self.assertRaises(port_config.PortConfigError) as caught:
                    parse(document)
                self.assertIn(field, str(caught.exception))

    def test_every_required_source_field_is_required(self) -> None:
        for field in port_config.REQUIRED_SOURCE_FIELDS:
            with self.subTest(field=field):
                document = minimal()
                del document["source"][field]
                with self.assertRaises(port_config.PortConfigError) as caught:
                    parse(document)
                self.assertIn(field, str(caught.exception))

    def test_a_descriptor_that_is_not_an_object_is_refused(self) -> None:
        for value in ([], "unifi", 3, None):
            with self.subTest(value=value):
                with self.assertRaises(port_config.PortConfigError):
                    parse(value)  # type: ignore[arg-type]

    def test_an_unreadable_schema_version_is_refused_rather_than_assumed(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(schema_version="99"))
        self.assertIn("refused rather than read with assumed defaults", str(caught.exception))


class PathSafetyTest(unittest.TestCase):
    """The descriptor names the paths a synchronization writes and deletes.

    `sync_vendor_source.resolve_managed_path` refuses an unsafe path when it
    reads one back out of a generated manifest. The same rule has to hold on the
    way in, because a rule that guards only the second half of a round trip
    guards nothing: the manifest is written *from* this file.
    """

    def test_an_absolute_package_root_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError):
            parse(minimal(package_root="/etc"))

    def test_a_traversing_package_root_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError):
            parse(minimal(package_root="plugins/../../etc"))

    def test_a_package_root_outside_the_plugins_directory_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(package_root="scripts/example"))
        self.assertIn(port_config.PACKAGE_PARENT, str(caught.exception))

    def test_a_package_root_that_does_not_end_in_the_package_name_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError):
            parse(minimal(package_root="plugins/somethingelse"))

    def test_a_traversing_custody_path_is_refused(self) -> None:
        for field in port_config.CUSTODY_FIELDS:
            with self.subTest(field=field):
                document = minimal(custody={field: ["../../../etc/passwd"]})
                if field == "client_byte_copies":
                    document["source"]["client_extension_dir"] = "com.example.client"
                if field == "dropped_from_source":
                    document["provenance"] = {"dropped_reason": "because"}
                with self.assertRaises(port_config.PortConfigError):
                    parse(document)

    def test_an_absolute_source_package_path_is_refused(self) -> None:
        document = minimal()
        document["source"]["package_path"] = "/plugins/example"
        with self.assertRaises(port_config.PortConfigError):
            parse(document)

    def test_a_client_extension_directory_may_not_be_a_path(self) -> None:
        document = minimal()
        document["source"]["client_extension_dir"] = "../outside"
        with self.assertRaises(port_config.PortConfigError):
            parse(document)


class CustodyTest(unittest.TestCase):
    def test_a_path_claimed_by_two_custody_classes_is_refused(self) -> None:
        document = minimal(
            custody={"byte_copies": ["README.md"], "superseded_by_target_owned": ["README.md"]}
        )
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(document)
        self.assertIn("more than one classification", str(caught.exception))

    def test_an_unknown_custody_class_is_refused_by_name(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(custody={"byte_copes": ["README.md"]}))
        self.assertIn("byte_copes", str(caught.exception))

    def test_client_custody_without_an_extension_directory_is_refused(self) -> None:
        """Copies with nowhere to land are a descriptor that cannot be executed."""
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(custody={"client_byte_copies": ["commands/x.md"]}))
        self.assertIn("client_extension_dir", str(caught.exception))

    def test_dropping_a_path_without_saying_why_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(custody={"dropped_from_source": ["shim.py"]}))
        self.assertIn("dropped_reason", str(caught.exception))

    def test_a_custody_class_that_is_not_a_list_of_strings_is_refused(self) -> None:
        for value in ("README.md", [3], [""], {"a": 1}):
            with self.subTest(value=value):
                with self.assertRaises(port_config.PortConfigError):
                    parse(minimal(custody={"byte_copies": value}))

    def test_declared_preserves_duplicates_so_they_can_be_counted(self) -> None:
        table = port_config.CustodyTable(("a",), ("a",), (), (), ())
        self.assertEqual(table.declared().count("a"), 2)


class EntrypointTransformRuleTest(unittest.TestCase):
    """Schema 3: every entrypoint-transform entry states the rule rewriting it.

    With more than one transform rule in play, selection has to be data a
    reader can see: an entry with no rule name would be rewritten by an
    assumed default, which is the setting-that-silently-did-not-take-effect
    failure every closed object in the descriptor prevents.
    """

    def entry(self, **overrides: object) -> dict:
        entry: dict = {"path": "scripts/example.py", "rule": "resolve-bundled-fleet-module"}
        entry.update(overrides)
        return entry

    def parsed(self, entries: list) -> port_config.PortConfig:
        return parse(minimal(custody={"entrypoint_transforms": entries}))

    def test_an_object_entry_records_its_path_and_rule(self) -> None:
        config = self.parsed([self.entry()])
        self.assertEqual(config.custody.entrypoint_transforms, ("scripts/example.py",))
        self.assertEqual(
            config.custody.entrypoint_rules,
            {"scripts/example.py": "resolve-bundled-fleet-module"},
        )
        self.assertEqual(config.custody.declared(), ("scripts/example.py",))

    def test_an_absent_field_is_empty_and_carries_no_rules(self) -> None:
        """Absent means empty, like every other custody class -- never an error."""
        config = parse(minimal())
        self.assertEqual(config.custody.entrypoint_transforms, ())
        self.assertEqual(config.custody.entrypoint_rules, {})

    def test_a_bare_path_string_entry_is_refused_as_the_schema_2_shape(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            self.parsed(["scripts/example.py"])
        self.assertIn("schema-2 shape", str(caught.exception))

    def test_an_entry_without_a_rule_is_refused_rather_than_defaulted(self) -> None:
        entry = self.entry()
        del entry["rule"]
        with self.assertRaises(port_config.PortConfigError) as caught:
            self.parsed([entry])
        self.assertIn("rule", str(caught.exception))
        self.assertIn("assumed default", str(caught.exception))

    def test_an_entry_without_a_path_is_refused(self) -> None:
        entry = self.entry()
        del entry["path"]
        with self.assertRaises(port_config.PortConfigError) as caught:
            self.parsed([entry])
        self.assertIn("path", str(caught.exception))

    def test_an_entry_with_an_unknown_field_is_refused(self) -> None:
        """The closed-object discipline holds on the new entry object too."""
        with self.assertRaises(port_config.PortConfigError) as caught:
            self.parsed([self.entry(version="1")])
        self.assertIn("unknown field", str(caught.exception))

    def test_an_empty_or_non_string_rule_is_refused(self) -> None:
        for value in ("", "   ", 3, None):
            with self.subTest(value=value):
                with self.assertRaises(port_config.PortConfigError):
                    self.parsed([self.entry(rule=value)])

    def test_a_traversing_entry_path_is_refused(self) -> None:
        with self.assertRaises(port_config.PortConfigError):
            self.parsed([self.entry(path="../../../etc/passwd")])

    def test_two_entries_may_not_claim_the_same_path(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            self.parsed([self.entry(), self.entry(rule="normalize-skill-frontmatter")])
        self.assertIn("more than one classification", str(caught.exception))


class ClosedContractTest(unittest.TestCase):
    """Every object is closed, and every safety field is stated.

    An unknown key in a descriptor is not a syntax error -- it is a setting that
    silently did not take effect. `credential_prefix` for `credential_prefixes`
    read as "strip nothing", and the run that found out was the one that handed
    the operator's real credentials to ten clients.
    """

    def test_an_unknown_key_is_refused_at_every_level(self) -> None:
        for path, mutate in (
            ("top level", lambda d: d.update({"pacakge_root": "plugins/example"})),
            ("source", lambda d: d["source"].update({"repositry": "x"})),
            ("assessment", lambda d: d["assessment"].update({"credential_prefix": ["X_"]})),
            ("provenance", lambda d: d.update({"provenance": {"note": ["x"]}})),
        ):
            with self.subTest(object=path):
                document = minimal()
                mutate(document)
                with self.assertRaises(port_config.PortConfigError) as caught:
                    parse(document)
                self.assertIn("unknown field", str(caught.exception))

    def test_a_misspelled_safety_field_is_refused_rather_than_read_as_empty(self) -> None:
        """The exact typo that produced the fail-open."""
        document = minimal()
        del document["assessment"]["credential_prefixes"]
        document["assessment"]["credential_prefix"] = ["EXAMPLE_"]
        with self.assertRaises(port_config.PortConfigError):
            parse(document)

    def test_every_safety_field_must_be_stated(self) -> None:
        for field in port_config.SAFETY_FIELDS:
            with self.subTest(field=field):
                document = minimal()
                del document["assessment"][field]
                with self.assertRaises(port_config.PortConfigError) as caught:
                    parse(document)
                self.assertIn(field, str(caught.exception))
                self.assertIn("declared_none", str(caught.exception))

    def test_a_missing_field_is_named_as_missing_rather_than_as_empty(self) -> None:
        """Two guards refuse the same descriptor; only their diagnostics differ.

        A field left out is read as empty downstream, so the emptiness guard
        refuses it too and the descriptor is rejected either way. That made the
        stated-field guard deletable without any test failing. What it actually
        contributes is the diagnostic: `credential_prefixes` left out is a typo
        or an oversight, and `credential_prefixes: []` is a decision. Telling the
        author which one the file has is the whole point of asking for it.
        """
        for field in port_config.SAFETY_FIELDS:
            with self.subTest(field=field):
                absent = minimal()
                del absent["assessment"][field]
                with self.assertRaises(port_config.PortConfigError) as missing:
                    parse(absent)

                empty = minimal()
                empty["assessment"][field] = []
                with self.assertRaises(port_config.PortConfigError) as stated_empty:
                    parse(empty)

                self.assertIn("must be stated", str(missing.exception))
                self.assertNotIn(
                    "is empty",
                    str(missing.exception),
                    f"{field} left out was reported as empty, which sends the author "
                    "looking for a value they never wrote",
                )
                self.assertIn("is empty", str(stated_empty.exception))

    def test_an_empty_safety_field_needs_an_explicit_declaration(self) -> None:
        for field in port_config.SAFETY_FIELDS:
            with self.subTest(field=field):
                document = minimal()
                document["assessment"][field] = []
                with self.assertRaises(port_config.PortConfigError) as caught:
                    parse(document)
                self.assertIn("fails open", str(caught.exception))

    def test_an_explicitly_declared_empty_field_is_accepted(self) -> None:
        """A package that genuinely has none says so, and a typo cannot say it."""
        document = minimal()
        document["assessment"]["mutating_operations"] = []
        document["assessment"]["declared_none"] = ["mutating_operations"]
        config = parse(document)
        self.assertEqual(config.assessment.mutating_operations, frozenset())
        self.assertIn("mutating_operations", config.assessment.declared_none)

    def test_declaring_a_field_none_while_it_is_populated_is_refused(self) -> None:
        document = minimal()
        document["assessment"]["declared_none"] = ["mutating_operations"]
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(document)
        self.assertIn("not empty", str(caught.exception))

    def test_declared_none_may_only_name_a_safety_field(self) -> None:
        document = minimal()
        document["assessment"]["declared_none"] = ["skill_units"]
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(document)
        self.assertIn("no safety decision", str(caught.exception))


class ManifestDestinationTest(unittest.TestCase):
    """A relocation with no destination plans a path built from a missing value."""

    def test_a_manifest_path_without_an_extension_directory_is_refused(self) -> None:
        document = minimal()
        document["source"]["manifest_path"] = ".claude-plugin/plugin.json"
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(document)
        self.assertIn("client_extension_dir", str(caught.exception))

    def test_the_pair_together_is_accepted(self) -> None:
        document = minimal()
        document["source"]["manifest_path"] = ".claude-plugin/plugin.json"
        document["source"]["client_extension_dir"] = "com.example.client"
        self.assertEqual(parse(document).source.client_extension_dir, "com.example.client")

    def test_no_synchronization_can_plan_a_path_from_a_missing_value(self) -> None:
        """The property, not the instance: no accepted descriptor can produce it."""
        document = minimal()
        document["source"]["manifest_path"] = ".claude-plugin/plugin.json"
        document["source"]["client_extension_dir"] = "com.example.client"
        config = parse(document)
        self.assertIsNotNone(config.source.client_extension_dir)
        self.assertNotIn("None", f"{config.source.client_extension_dir}/plugin.json")


class EntrypointDeclarationTest(unittest.TestCase):
    """Entrypoints are declared, not inferred from how the bytes were obtained."""

    def test_entrypoints_are_independent_of_custody(self) -> None:
        for custody_class in port_config.CUSTODY_FIELDS:
            with self.subTest(custody=custody_class):
                document = minimal()
                if custody_class == "entrypoint_transforms":
                    entry = {"path": "scripts/example.py", "rule": "resolve-bundled-fleet-module"}
                else:
                    entry = "scripts/example.py"
                document["custody"] = {custody_class: [entry]}
                if custody_class == "client_byte_copies":
                    document["source"]["client_extension_dir"] = "com.example.client"
                if custody_class == "dropped_from_source":
                    document["provenance"] = {"dropped_reason": "replaced at build time"}
                config = parse(document)
                self.assertEqual(config.assessment.entrypoints, ("scripts/example.py",))

    def test_a_package_with_no_custody_at_all_still_declares_entrypoints(self) -> None:
        """Target-owned source has no custody entry, and is still runnable."""
        config = parse(minimal())
        self.assertEqual(config.custody.declared(), ())
        self.assertTrue(config.assessment.entrypoints)

    def test_a_traversing_entrypoint_is_refused(self) -> None:
        document = minimal()
        document["assessment"]["entrypoints"] = ["../../etc/passwd"]
        with self.assertRaises(port_config.PortConfigError):
            parse(document)


class NamingTest(unittest.TestCase):
    def test_the_filename_and_the_package_must_agree(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            parse(minimal(), name="something-else")
        self.assertIn("descriptor must be called", str(caught.exception))

    def test_a_package_name_that_is_a_path_is_refused(self) -> None:
        for name in ("../escape", "a/b", "", ".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(port_config.PortConfigError):
                    port_config.descriptor_path(name, ROOT)


class LoadingTest(unittest.TestCase):
    def test_an_unported_package_names_the_ones_that_exist(self) -> None:
        with self.assertRaises(port_config.PortConfigError) as caught:
            port_config.load("not-a-package", ROOT)
        message = str(caught.exception)
        self.assertIn("no port descriptor", message)
        for name in port_config.available(ROOT):
            self.assertIn(name, message)

    def test_a_malformed_descriptor_is_reported_not_crashed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / port_config.CONFIG_DIRECTORY_NAME).mkdir()
            (root / port_config.CONFIG_DIRECTORY_NAME / "broken.json").write_text(
                "{not json", encoding="utf-8"
            )
            with self.assertRaises(port_config.PortConfigError) as caught:
                port_config.load("broken", root)
            self.assertIn("not valid JSON", str(caught.exception))

    def test_available_is_empty_when_the_directory_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(port_config.available(Path(directory)), [])


class CommittedDescriptorTest(unittest.TestCase):
    """The shipped UniFi descriptor is the regression fixture for all of this."""

    def setUp(self) -> None:
        self.config = port_config.load("unifi", ROOT)

    def test_it_names_the_package_that_ships(self) -> None:
        self.assertTrue(self.config.package_directory.is_dir())
        manifest = json.loads(self.config.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], self.config.name)

    def test_every_descriptor_in_the_repository_loads(self) -> None:
        self.assertIn("unifi", port_config.available(ROOT))
        gate_errors = check_repo.check_port_descriptors(ROOT)
        for config in port_config.load_all(ROOT):
            with self.subTest(package=config.name):
                if config.package_directory.is_dir():
                    continue
                # The run plan's landing model lets a descriptor land on the
                # integration branch before the package tree it names does.
                # That interim state is legitimate only while the repository
                # gate reports it -- never as a silent pass.
                self.assertTrue(
                    any(config.name in error for error in gate_errors),
                    f"{config.name} has no package tree and the gate does not report it",
                )

    def test_the_repository_gate_checks_every_descriptor(self) -> None:
        """The gate is green exactly when every descriptor's package is complete.

        A descriptor lands before its package tree on an integration branch
        (the run plan's landing model). The gate must report every such
        incomplete descriptor and nothing else, and it must be green once
        every named tree, manifest, and entrypoint is present.
        """
        errors = check_repo.check_port_descriptors(ROOT)
        incomplete = [
            config.name
            for config in port_config.load_all(ROOT)
            if not (
                config.package_directory.is_dir()
                and config.manifest_path.is_file()
                and all(
                    (config.package_directory / relative).is_file()
                    for relative in config.assessment.entrypoints
                )
            )
        ]
        if not incomplete:
            self.assertEqual(errors, [])
            return
        for name in incomplete:
            self.assertTrue(any(name in error for error in errors), name)
        for error in errors:
            self.assertTrue(any(name in error for name in incomplete), error)

    def test_the_gate_reports_a_descriptor_naming_an_absent_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / port_config.CONFIG_DIRECTORY_NAME).mkdir()
            (root / port_config.CONFIG_DIRECTORY_NAME / "ghost.json").write_text(
                json.dumps(minimal(package="ghost", package_root="plugins/ghost")),
                encoding="utf-8",
            )
            errors = check_repo.check_port_descriptors(root)
            self.assertTrue(errors)
            self.assertIn("plugins/ghost", errors[0])

    def test_the_custody_table_accounts_for_every_shipped_managed_path(self) -> None:
        """The descriptor and the shipped provenance manifest must agree.

        A path the manifest records as an upstream byte copy while the
        descriptor no longer names it is a package whose own derivation tool
        would drop it on the next run.
        """
        manifest = json.loads(
            (self.config.package_directory / check_repo.PROVENANCE_FILENAME).read_text(
                encoding="utf-8"
            )
        )
        recorded = {entry["path"]: entry["classification"] for entry in manifest["files"]}
        extension = self.config.source.client_extension_dir
        for relative in self.config.custody.byte_copies:
            self.assertEqual(recorded.get(relative), check_repo.BYTE_COPY, relative)
        for relative in self.config.custody.client_byte_copies:
            path = f"{extension}/{relative}"
            self.assertEqual(recorded.get(path), check_repo.BYTE_COPY, path)
        for relative in self.config.custody.entrypoint_transforms:
            self.assertEqual(recorded.get(relative), check_repo.TRANSFORM, relative)
        for relative in self.config.custody.superseded_by_target_owned:
            self.assertEqual(recorded.get(relative), check_repo.TARGET_OWNED, relative)
        for relative in self.config.custody.dropped_from_source:
            self.assertNotIn(relative, recorded)

    def test_every_entrypoint_transform_entry_names_a_rule_the_sync_tool_implements(self) -> None:
        """The schema-3 selection is a name; the registry is what names exist.

        The validator checks the entry's shape only, so a typo'd rule name
        would otherwise survive repository validation and fail in the middle of
        a synchronization. Joining the two here fails at the gate instead.
        """
        for config in port_config.load_all(ROOT):
            for relative in config.custody.entrypoint_transforms:
                with self.subTest(package=config.name, path=relative):
                    rule = config.custody.entrypoint_rules.get(relative)
                    self.assertTrue(
                        rule, f"{config.name}: {relative} carries no rule name"
                    )
                    self.assertIn(rule, svs.TRANSFORM_RULES)

    def test_the_provenance_note_recomputes_the_carried_test_counts(self) -> None:
        """F18/F64: the provenance prose states the byte-copied and transform
        test counts. Both counts are recomputed from the descriptor's own
        custody arrays, and the prose number is parsed out and compared as an
        integer — never matched as a substring, which a count like 6 would
        satisfy inside "26 as byte copies"."""
        config = port_config.load("mission-control", ROOT)
        byte_copy_tests = [
            path for path in config.custody.byte_copies if path.startswith("tests/")
        ]
        transform_tests = [
            path
            for path in config.custody.entrypoint_transforms
            if path.startswith("tests/")
            and config.custody.entrypoint_rules.get(path)
            == svs.PACKAGE_ROOT_MARKER_TRANSFORM_NAME
        ]
        notes = "\n".join(config.notes)
        byte_count = re.search(r"(\d+) as byte copies", notes)
        self.assertIsNotNone(byte_count, "the provenance note states no byte-copy count")
        assert byte_count is not None
        self.assertEqual(
            int(byte_count.group(1)),
            len(byte_copy_tests),
            "the provenance note's byte-copy count disagrees with the custody arrays; "
            "recompute it, never retype it",
        )
        transform_count = re.search(
            r"(\d+) as resolve-package-root-marker transforms", notes
        )
        self.assertIsNotNone(
            transform_count, "the provenance note states no transform count"
        )
        assert transform_count is not None
        self.assertEqual(
            int(transform_count.group(1)),
            len(transform_tests),
            "the provenance note's transform count disagrees with the custody arrays; "
            "recompute it, never retype it",
        )
        for path in transform_tests:
            self.assertIn(
                path,
                notes,
                f"the provenance note does not name the transform path {path}",
            )

    def test_the_marker_rules_site_table_joins_every_descriptor_selection(self) -> None:
        """F20/F59/F65: `PACKAGE_ROOT_MARKER_SITE_COUNTS` is per-package custody
        data compiled into the shared script, so each package's descriptor
        paths and its table slice are joined in both directions, every row
        states all four site classes, and every row's call count equals its
        finder count so the definition-before-call check can pair them."""
        for config in port_config.load_all(ROOT):
            declared = {
                path
                for path in config.custody.entrypoint_transforms
                if config.custody.entrypoint_rules.get(path)
                == svs.PACKAGE_ROOT_MARKER_TRANSFORM_NAME
            }
            slice_rows = svs.PACKAGE_ROOT_MARKER_SITE_COUNTS.get(config.name, {})
            if declared or slice_rows:
                with self.subTest(package=config.name):
                    self.assertEqual(
                        declared,
                        set(slice_rows),
                        "a descriptor path selects resolve-package-root-marker without "
                        "a matching site-count row in its package slice, or the slice "
                        "names a path no descriptor selects",
                    )
        for package, slice_rows in svs.PACKAGE_ROOT_MARKER_SITE_COUNTS.items():
            config = next(
                candidate
                for candidate in port_config.load_all(ROOT)
                if candidate.name == package
            )
            declared = {
                path
                for path in config.custody.entrypoint_transforms
                if config.custody.entrypoint_rules.get(path)
                == svs.PACKAGE_ROOT_MARKER_TRANSFORM_NAME
            }
            self.assertEqual(declared, set(slice_rows), package)
            for path, row in slice_rows.items():
                with self.subTest(package=package, path=path):
                    self.assertEqual(
                        set(row),
                        set(svs.SITE_CLASSES),
                        f"{path} declares an incomplete site-count row",
                    )
                    self.assertEqual(
                        row["call"],
                        row["finder"],
                        f"{path} declares {row['call']} calls for {row['finder']} finders; "
                        "the definition-before-call check cannot pair them",
                    )

    def test_the_marker_precondition_refuses_a_mismatched_client_extension_dir(self) -> None:
        """F60: the descriptor-level refusal the planner runs before dispatching
        the marker rule. The real descriptor passes; a synthetic one whose
        client_extension_dir does not name the marker directory refuses,
        naming both values."""
        svs._package_root_marker_precondition(port_config.load("mission-control", ROOT))
        document = minimal()
        document["source"]["client_extension_dir"] = "com.example.client"
        synthetic = parse(document)
        with self.assertRaises(svs.SyncError) as caught:
            svs._package_root_marker_precondition(synthetic)
        message = str(caught.exception)
        self.assertIn("com.example.client", message)
        self.assertIn(svs.PORTABLE_PACKAGE_ROOT_MARKER, message)

    def test_the_descriptor_spec_names_every_selectable_transform_rule(self) -> None:
        """F66: the ports/README.md enumeration of selectable rules is derived
        from TRANSFORM_RULES, so a rule added to the registry without the spec
        moving fails at the gate."""
        spec = (ROOT / "ports" / "README.md").read_text(encoding="utf-8")
        for name in sorted(svs.TRANSFORM_RULES):
            if name == svs.MANIFEST_TRANSFORM_NAME:
                continue  # never selected by a descriptor entry, the spec says so
            self.assertIn(
                f"`{name}`",
                spec,
                f"ports/README.md does not enumerate the selectable rule {name}",
            )

    def test_the_provenance_notes_name_the_real_bundle_directory(self) -> None:
        """The note is prose in a data file, so its one live reference is checked.

        The bundle directory name is owned by `check_repo.BUNDLE_DIRECTORY_NAME`.
        The manifest note names it in prose, and prose in a JSON file has no
        compiler; this is what fails if the directory is ever renamed.
        """
        joined = " ".join(self.config.notes)
        self.assertIn(f"{check_repo.BUNDLE_DIRECTORY_NAME}/", joined)

    def test_the_declared_skill_units_exist_in_the_shipped_package(self) -> None:
        self.assertTrue(self.config.assessment.skill_units)
        for unit in self.config.assessment.skill_units:
            with self.subTest(unit=unit):
                self.assertTrue((self.config.package_directory / unit).is_dir())

    def test_every_entrypoint_sits_under_a_declared_skill_unit(self) -> None:
        """Skill-scoped clients resolve an entrypoint relative to its unit.

        An entrypoint under no declared unit has no path on those clients, so
        the assessment could not invoke it. Catching that here is cheaper than
        catching it in the middle of a ten-client run.
        """
        for relative in self.config.custody.entrypoint_transforms:
            with self.subTest(entrypoint=relative):
                self.assertTrue(
                    any(
                        relative.startswith(f"{unit}/")
                        for unit in self.config.assessment.skill_units
                    ),
                    relative,
                )

    def test_the_descriptor_declares_the_credential_variables_to_strip(self) -> None:
        """An empty prefix list strips nothing, which is a fail-open.

        `scripts/assess_clients.py` removes every variable matching these
        prefixes from every assessment subprocess. A descriptor that declares
        none hands the operator's real credentials to every client it runs, and
        the harness has no other way to know what this package's credentials are
        called. Same guard, same reason, as the package-scripts test below.
        """
        prefixes = self.config.assessment.credential_prefixes
        self.assertTrue(
            prefixes,
            "the descriptor declares no credential_prefixes, so the assessment would strip "
            "nothing from its subprocess environments",
        )
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                self.assertTrue(prefix.strip())

    def test_the_declared_package_scripts_are_files_the_package_carries(self) -> None:
        """The safety rule is scoped by these names, so they must name real scripts.

        An empty or wrong list would scope the mutating-operation check to
        nothing, which is a fail-open: every recorded command would pass.
        """
        self.assertTrue(self.config.assessment.package_scripts)
        shipped = {
            path.name
            for path in self.config.package_directory.rglob("*.py")
            if "__pycache__" not in path.parts
        }
        for script in self.config.assessment.package_scripts:
            with self.subTest(script=script):
                self.assertIn(script, shipped)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
