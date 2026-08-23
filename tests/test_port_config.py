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
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import port_config  # noqa: E402


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
        for config in port_config.load_all(ROOT):
            with self.subTest(package=config.name):
                self.assertTrue(config.package_directory.is_dir())

    def test_the_repository_gate_checks_every_descriptor(self) -> None:
        self.assertEqual(check_repo.check_port_descriptors(ROOT), [])

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
