from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402


# The compatibility value is the catalog's declared Python floor, held by
# tests/test_python_floor.py. A fixture is a declaration like any other: the
# floor gate scans this file too, so a stale value here fails that test rather
# than sitting in the suite contradicting the contract it helps validate.
CONFORMANT_SKILL = """---
name: unifi-network
description: Manage UniFi network infrastructure.
license: Apache-2.0
compatibility: python>=3.12
---

# UniFi network
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_plugin(root: Path, name: str = "example") -> Path:
    plugin = root / "plugins" / name
    write(
        plugin / "plugin.json",
        json.dumps(
            {
                "$schema": check_repo.PLUGIN_SCHEMA,
                "name": name,
                "version": "0.1.0",
                "description": "Example plugin",
            }
        ),
    )
    return plugin


def write_provenance(
    plugin: Path,
    files: list[dict[str, object]],
    *,
    classify_plugin_manifest: bool = True,
) -> Path:
    """Write a provenance manifest for ``plugin``.

    ``make_plugin`` always writes a ``plugin.json``, and a manifest is now closed
    over the package tree, so every manifest has to classify it. Classifying it
    here keeps each test's ``files`` list about the file that test is exercising.
    Pass ``classify_plugin_manifest=False`` to leave it deliberately unlisted.
    """
    entries: list[dict[str, object]] = []
    if classify_plugin_manifest:
        entries.append({"path": "plugin.json", "classification": check_repo.TARGET_OWNED})
    entries.extend(files)
    return write(
        plugin / check_repo.PROVENANCE_FILENAME,
        json.dumps(
            {
                "source_repository": "https://github.com/infiquetra/example",
                "source_commit": "0" * 40,
                "files": entries,
            }
        ),
    )


STAMP_FIELD_VALUES = {
    check_repo.BUNDLE_GENERATED_BY_FIELD: "scripts/bundle_fleet_module.py",
    check_repo.BUNDLE_SOURCE_VERSION_FIELD: "0.25.0",
    check_repo.BUNDLE_SOURCE_COMMIT_FIELD: "1" * 40,
    check_repo.BUNDLE_SOURCE_PATH_FIELD: "scripts/fleet_commons/retry_backoff.py",
    check_repo.BUNDLE_SOURCE_DIGEST_FIELD: "a" * 64,
}


def stamped_bundle(
    body: str,
    output_digest: str | None = None,
    omit: tuple[str, ...] = (),
) -> str:
    """A generated bundle carrying every required stamp field except ``omit``."""
    if output_digest is None:
        output_digest = check_repo.sha256_text(body)
    values = dict(STAMP_FIELD_VALUES)
    values[check_repo.BUNDLE_OUTPUT_DIGEST_FIELD] = output_digest
    lines = [
        f"# {field}: {values[field]}"
        for field in check_repo.BUNDLE_REQUIRED_STAMP_FIELDS
        if field not in omit
    ]
    return (
        "\n".join([check_repo.BUNDLE_STAMP_BEGIN, *lines, check_repo.BUNDLE_STAMP_END]) + "\n"
    ) + body


class RepositoryValidationTests(unittest.TestCase):
    def test_live_repository_has_required_baseline(self) -> None:
        self.assertEqual(check_repo.check_required_paths(ROOT), [])

    def test_live_repository_passes_every_check(self) -> None:
        self.assertEqual(check_repo.check_repo(ROOT), [])

    def test_broken_local_markdown_link_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("[missing](docs/missing.md)\n", encoding="utf-8")

            self.assertEqual(
                check_repo.check_markdown_links(root),
                ["broken local link in README.md: docs/missing.md"],
            )

    def test_valid_plugin_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_plugin(root)

            self.assertEqual(check_repo.check_plugin_manifests(root), [])

    def test_plugin_directory_requires_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugins" / "example").mkdir(parents=True)

            self.assertEqual(
                check_repo.check_plugin_manifests(root),
                ["missing plugin manifest: plugins/example/plugin.json"],
            )

    def test_repository_without_plugins_passes_the_new_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            self.assertEqual(check_repo.check_provenance_manifests(root), [])
            self.assertEqual(check_repo.check_bundled_files(root), [])
            self.assertEqual(check_repo.check_skill_frontmatter(root), [])


class PortDescriptorGateTests(unittest.TestCase):
    """The gate must actually run the descriptor check, not merely define it.

    `check_port_descriptors` had tests of its own and the aggregation that calls
    it had none, so deleting the one line that wires it into `check_repo` failed
    nothing: every descriptor test still passed while the gate no longer looked
    at a single descriptor.
    """

    @staticmethod
    def broken_descriptor(root: Path) -> None:
        (root / "ports").mkdir(parents=True, exist_ok=True)
        (root / "ports" / "example.json").write_text(
            json.dumps({"schema_version": "2", "package": "example"}), encoding="utf-8"
        )

    def test_the_gate_reports_a_descriptor_that_does_not_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.broken_descriptor(root)
            problems = check_repo.check_repo(root)
        self.assertTrue(
            any(problem.startswith("port descriptor") for problem in problems),
            f"check_repo did not run the descriptor check; it reported {problems}",
        )

    def test_the_descriptor_check_finds_it_on_its_own_too(self) -> None:
        """So a failure of the test above localizes to the wiring, not the check."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.broken_descriptor(root)
            self.assertTrue(check_repo.check_port_descriptors(root))


class GateWiringTests(unittest.TestCase):
    """Every check the gate defines must also be a check the gate runs.

    Same defect as `PortDescriptorGateTests` above, found the same way. The
    cycle-17 mutation campaign deleted each check's line from `check_repo` one
    at a time; the skill-frontmatter and fleet-bundle-output deletions were the
    two mutations no shipping test noticed. Both checks had thorough tests of
    their own, and the aggregation that calls them had none, so removing either
    wire left every one of those tests passing while the gate stopped looking.

    These are behavioural: each builds a tree the named check is the only thing
    that objects to, and asserts the aggregate objects. A test that asserted the
    source of `check_repo` contains a string would pass over a call that was
    wired in and then broken.
    """

    @staticmethod
    def broken_skill(root: Path) -> None:
        plugin = make_plugin(root)
        write(plugin / "skills" / "example" / "SKILL.md", "no frontmatter here\n")

    @staticmethod
    def undeclared_bundle(root: Path) -> None:
        plugin = make_plugin(root)
        write(
            plugin / check_repo.FLEET_BUNDLE_FILENAME,
            json.dumps(
                {
                    "schema_version": "1",
                    "modules": [{"name": "absent_module"}],
                }
            ),
        )

    def test_the_gate_reports_a_skill_with_no_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.broken_skill(root)
            problems = check_repo.check_repo(root)
        self.assertTrue(
            any("frontmatter" in problem for problem in problems),
            f"check_repo did not run the skill frontmatter check; it reported {problems}",
        )

    def test_the_frontmatter_check_finds_it_on_its_own_too(self) -> None:
        """So a failure of the test above localizes to the wiring, not the check."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.broken_skill(root)
            self.assertTrue(check_repo.check_skill_frontmatter(root))

    def test_the_gate_reports_a_declared_bundle_that_was_never_generated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.undeclared_bundle(root)
            problems = check_repo.check_repo(root)
        self.assertTrue(
            any("absent_module" in problem for problem in problems),
            f"check_repo did not run the fleet bundle output check; it reported {problems}",
        )

    def test_the_bundle_output_check_finds_it_on_its_own_too(self) -> None:
        """So a failure of the test above localizes to the wiring, not the check."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.undeclared_bundle(root)
            self.assertTrue(check_repo.check_fleet_bundle_outputs(root))

    @staticmethod
    def misplaced_module(root: Path) -> None:
        plugin = make_plugin(root)
        write(plugin / "skills" / "example" / "pane.ts", "export const x = 1\n")

    def test_the_gate_reports_a_module_source_outside_the_claude_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.misplaced_module(root)
            problems = check_repo.check_repo(root)
        self.assertTrue(
            any("pane.ts" in problem for problem in problems),
            f"check_repo did not run the Claude module source check; it reported {problems}",
        )

    def test_the_module_source_check_finds_it_on_its_own_too(self) -> None:
        """So a failure of the test above localizes to the wiring, not the check."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.misplaced_module(root)
            self.assertTrue(check_repo.check_claude_module_sources(root))


class ProvenanceManifestTests(unittest.TestCase):
    def test_package_without_provenance_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_plugin(root)

            self.assertEqual(check_repo.check_provenance_manifests(root), [])

    def test_matching_digests_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            copied = write(plugin / "skills" / "example" / "SKILL.md", "# ported\n")
            authored = write(plugin / "scripts" / "site_profile.py", "VALUE = 1\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "skills/example/SKILL.md",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": check_repo.sha256_path(copied),
                    },
                    {
                        "path": "scripts/site_profile.py",
                        "classification": check_repo.TARGET_OWNED,
                    },
                ],
            )
            self.assertTrue(authored.is_file())

            self.assertEqual(check_repo.check_provenance_manifests(root), [])

    def test_changed_content_produces_one_digest_mismatch_naming_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            ported = write(plugin / "scripts" / "client.py", "ORIGINAL = 1\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/client.py",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": check_repo.sha256_path(ported),
                    }
                ],
            )
            ported.write_text("EDITED = 1\n", encoding="utf-8")

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("provenance digest mismatch", errors[0])
            self.assertIn("plugins/example/scripts/client.py", errors[0])

    def test_missing_file_is_reported_rather_than_raising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/absent.py",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": "b" * 64,
                    }
                ],
            )

            self.assertEqual(
                check_repo.check_provenance_manifests(root),
                ["provenance file missing: plugins/example/scripts/absent.py"],
            )

    def test_unknown_classification_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            ported = write(plugin / "scripts" / "client.py", "VALUE = 1\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/client.py",
                        "classification": "vendored",
                        "sha256": check_repo.sha256_path(ported),
                    }
                ],
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("unknown provenance classification", errors[0])

    def test_transform_entry_requires_source_digest_and_transform_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            generated = write(plugin / "com.infiquetra.claude" / "plugin.json", "{}\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "com.infiquetra.claude/plugin.json",
                        "classification": check_repo.TRANSFORM,
                        "sha256": check_repo.sha256_path(generated),
                    }
                ],
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 2)
            self.assertTrue(any("missing source_sha256" in error for error in errors))
            self.assertTrue(any("missing transform_version" in error for error in errors))

    def test_target_owned_entry_must_not_pin_a_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            authored = write(plugin / "scripts" / "site_profile.py", "VALUE = 1\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/site_profile.py",
                        "classification": check_repo.TARGET_OWNED,
                        "sha256": check_repo.sha256_path(authored),
                    }
                ],
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("target-owned provenance entry must not record a digest", errors[0])

    def test_unsafe_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(
                plugin,
                [
                    {
                        "path": "../../etc/passwd",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": "c" * 64,
                    }
                ],
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("unsafe path", errors[0])

    def test_invalid_manifest_json_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(plugin / check_repo.PROVENANCE_FILENAME, "{not json")

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("invalid provenance manifest", errors[0])


class ProvenanceClosedSetTests(unittest.TestCase):
    """C3: the manifest must account for every file in the package, both ways."""

    def test_unlisted_package_file_is_reported(self) -> None:
        """An executable dropped into a package after synchronization must fail."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            ported = write(plugin / "scripts" / "client.py", "VALUE = 1\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/client.py",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": check_repo.sha256_path(ported),
                    }
                ],
            )
            write(plugin / "scripts" / "extra.py", "BACKDOOR = 1\n")

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("unlisted package file", errors[0])
            self.assertIn("plugins/example/scripts/extra.py", errors[0])

    def test_removing_a_managed_entry_from_the_manifest_is_reported(self) -> None:
        """The other direction: the file stays, its classification is deleted."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            kept = write(plugin / "scripts" / "client.py", "VALUE = 1\n")
            write(plugin / "scripts" / "discover.py", "VALUE = 2\n")
            write_provenance(
                plugin,
                [
                    {
                        "path": "scripts/client.py",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": check_repo.sha256_path(kept),
                    }
                ],
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("unlisted package file", errors[0])
            self.assertIn("plugins/example/scripts/discover.py", errors[0])

    def test_a_path_listed_twice_is_reported(self) -> None:
        """One path may carry exactly one classification, so a repeat is a defect."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            ported = write(plugin / "scripts" / "client.py", "VALUE = 1\n")
            entry: dict[str, object] = {
                "path": "scripts/client.py",
                "classification": check_repo.BYTE_COPY,
                "sha256": check_repo.sha256_path(ported),
            }
            write_provenance(plugin, [entry, dict(entry)])

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("duplicate provenance entry", errors[0])
            self.assertIn("plugins/example/scripts/client.py", errors[0])

    def test_the_plugin_manifest_is_not_exempt_from_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(plugin, [], classify_plugin_manifest=False)

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("unlisted package file", errors[0])
            self.assertIn("plugins/example/plugin.json", errors[0])

    def test_the_provenance_manifest_itself_is_exempt(self) -> None:
        """It cannot record its own digest, so it is the one deliberate exclusion."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(plugin, [])

            self.assertEqual(check_repo.check_provenance_manifests(root), [])

    def test_interpreter_artifacts_are_exempt(self) -> None:
        """Bytecode in the two places the interpreter writes it (PEP 3147)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(
                plugin,
                [{"path": "scripts/client.py", "classification": check_repo.TARGET_OWNED}],
            )
            write(plugin / "scripts" / "client.py", "print(1)\n")
            write(
                plugin / "scripts" / "__pycache__" / "client.cpython-312.pyc",
                "not source",
            )
            # The legacy sourceless layout: bytecode beside the .py it came from.
            write(plugin / "scripts" / "client.pyc", "not source")

            self.assertEqual(check_repo.check_provenance_manifests(root), [])

    def test_bytecode_with_no_source_beside_it_is_an_unlisted_package_file(self) -> None:
        """The closed set is closed against a file merely wearing a .pyo suffix.

        Before this, `PROVENANCE_UNMANAGED_SUFFIXES` exempted `.pyc`/`.pyo`
        anywhere in the tree at any depth, so a file holding arbitrary text
        passed this gate without appearing in any provenance manifest.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(plugin, [])
            write(
                plugin / "skills" / "unifi-network" / "scripts" / "smuggled.pyo",
                "this is not bytecode, it is arbitrary smuggled content",
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("unlisted package file", errors[0])
            self.assertIn(
                "plugins/example/skills/unifi-network/scripts/smuggled.pyo", errors[0]
            )

    def test_bytecode_beside_a_differently_named_source_is_not_exempt(self) -> None:
        """The sibling has to be *the* source: `client.py` does not cover `other.pyo`."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(
                plugin,
                [{"path": "scripts/client.py", "classification": check_repo.TARGET_OWNED}],
            )
            write(plugin / "scripts" / "client.py", "print(1)\n")
            write(plugin / "scripts" / "other.pyo", "smuggled")

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("plugins/example/scripts/other.pyo", errors[0])

    def test_an_unsafe_listed_path_does_not_satisfy_the_closed_set(self) -> None:
        """A traversal entry is reported once, and never counts as a classification."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write_provenance(
                plugin,
                [
                    {
                        "path": "../../etc/passwd",
                        "classification": check_repo.BYTE_COPY,
                        "sha256": "c" * 64,
                    }
                ],
                classify_plugin_manifest=False,
            )

            errors = check_repo.check_provenance_manifests(root)

            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(any("unsafe path" in error for error in errors))
            self.assertTrue(
                any("plugins/example/plugin.json" in error for error in errors)
            )


class BundleStampTests(unittest.TestCase):
    def test_matching_stamp_produces_no_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            body = "def retry():\n    return None\n"
            write(
                plugin / "skills" / "example" / "scripts" / "_bundled" / "retry_backoff.py",
                stamped_bundle(body),
            )

            self.assertEqual(check_repo.check_bundled_files(root), [])

    def test_stamp_that_disagrees_with_content_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            bundled = write(
                plugin / "skills" / "example" / "scripts" / "_bundled" / "retry_backoff.py",
                stamped_bundle("def retry():\n    return None\n"),
            )
            bundled.write_text(
                bundled.read_text(encoding="utf-8").replace("return None", "return 1"),
                encoding="utf-8",
            )

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("stale bundle", errors[0])
            self.assertIn(
                "plugins/example/skills/example/scripts/_bundled/retry_backoff.py",
                errors[0],
            )

    def test_unstamped_bundle_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "_bundled" / "retry_backoff.py",
                "def retry():\n    return None\n",
            )

            self.assertEqual(
                check_repo.check_bundled_files(root),
                ["unstamped generated bundle: plugins/example/scripts/_bundled/retry_backoff.py"],
            )

    def test_every_required_stamp_field_is_reported_by_name_when_omitted(self) -> None:
        """C4: any optional field is a comparison a hand-edit can switch off."""
        for field in check_repo.BUNDLE_REQUIRED_STAMP_FIELDS:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plugin = make_plugin(root)
                write(
                    plugin / "scripts" / "_bundled" / "retry_backoff.py",
                    stamped_bundle("def retry():\n    return None\n", omit=(field,)),
                )

                errors = check_repo.check_bundled_files(root)

                self.assertEqual(len(errors), 1, errors)
                self.assertIn(f"generated bundle stamp missing {field}", errors[0])
                self.assertIn(
                    "plugins/example/scripts/_bundled/retry_backoff.py", errors[0]
                )

    def test_dropping_both_source_provenance_fields_is_reported(self) -> None:
        """C4: the reviewed scenario — delete the two fields that reach Fleet Core."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "_bundled" / "retry_backoff.py",
                stamped_bundle(
                    "def retry():\n    return None\n",
                    omit=(
                        check_repo.BUNDLE_SOURCE_PATH_FIELD,
                        check_repo.BUNDLE_SOURCE_DIGEST_FIELD,
                    ),
                ),
            )

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 2, errors)
            self.assertTrue(
                any(check_repo.BUNDLE_SOURCE_PATH_FIELD in error for error in errors)
            )
            self.assertTrue(
                any(check_repo.BUNDLE_SOURCE_DIGEST_FIELD in error for error in errors)
            )

    def test_a_blank_stamp_field_counts_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            body = "def retry():\n    return None\n"
            write(
                plugin / "scripts" / "_bundled" / "retry_backoff.py",
                stamped_bundle(body, omit=(check_repo.BUNDLE_SOURCE_COMMIT_FIELD,)).replace(
                    check_repo.BUNDLE_STAMP_END,
                    f"# {check_repo.BUNDLE_SOURCE_COMMIT_FIELD}:\n"
                    f"{check_repo.BUNDLE_STAMP_END}",
                ),
            )

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn(
                f"generated bundle stamp missing {check_repo.BUNDLE_SOURCE_COMMIT_FIELD}",
                errors[0],
            )

    def test_output_digest_excludes_the_stamp_block(self) -> None:
        body = "def retry():\n    return None\n"
        self.assertEqual(
            check_repo.bundle_output_digest(stamped_bundle(body)),
            check_repo.sha256_text(body),
        )

    def test_interpreter_cache_under_a_bundle_directory_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "_bundled" / "__pycache__" / "retry_backoff.cpython-312.pyc",
                "not a stamped module",
            )

            self.assertEqual(check_repo.check_bundled_files(root), [])

    def test_missing_data_file_source_is_reported_as_stale_source(self) -> None:
        """A non-python bundled data file whose Fleet Core source is missing is reported."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "_bundled" / "models.json",
                '{"schema_version": 2}\n',
            )
            fleet_core = root / "plugins" / check_repo.FLEET_CORE_PLUGIN_NAME
            (fleet_core / "scripts" / "fleet_commons").mkdir(parents=True, exist_ok=True)

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("stale source: models.json", errors[0])
            self.assertIn("source file missing:", errors[0])



class SkillFrontmatterTests(unittest.TestCase):
    def test_conformant_frontmatter_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(plugin / "skills" / "unifi-network" / "SKILL.md", CONFORMANT_SKILL)

            self.assertEqual(check_repo.check_skill_frontmatter(root), [])

    def test_disallowed_field_is_reported_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "skills" / "unifi-network" / "SKILL.md",
                CONFORMANT_SKILL.replace(
                    "license: Apache-2.0",
                    "license: Apache-2.0\ntriggers: unifi, network",
                ),
            )

            self.assertEqual(
                check_repo.check_skill_frontmatter(root),
                [
                    "disallowed skill frontmatter field in "
                    "plugins/example/skills/unifi-network/SKILL.md: triggers"
                ],
            )

    def test_frontmatter_name_must_match_the_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "skills" / "unifi-network" / "SKILL.md",
                CONFORMANT_SKILL.replace("name: unifi-network", "name: unifi_network"),
            )

            errors = check_repo.check_skill_frontmatter(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("skill name mismatch", errors[0])
            self.assertIn("'unifi_network'", errors[0])
            self.assertIn("'unifi-network'", errors[0])

    def test_missing_frontmatter_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(plugin / "skills" / "unifi-network" / "SKILL.md", "# UniFi network\n")

            errors = check_repo.check_skill_frontmatter(root)

            self.assertEqual(len(errors), 1)
            self.assertIn("missing or unterminated frontmatter", errors[0])

    def test_missing_skill_document_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            (plugin / "skills" / "unifi-network").mkdir(parents=True)

            self.assertEqual(
                check_repo.check_skill_frontmatter(root),
                ["missing skill document: plugins/example/skills/unifi-network/SKILL.md"],
            )

    def test_client_extension_skills_are_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "com.infiquetra.claude" / "skills" / "unifi-network" / "SKILL.md",
                CONFORMANT_SKILL.replace("name: unifi-network", "name: unifi_network")
                + "\ntriggers: unifi\n",
            )

            self.assertEqual(check_repo.check_skill_frontmatter(root), [])

    def test_nested_frontmatter_values_are_not_read_as_top_level_fields(self) -> None:
        fields = check_repo.read_frontmatter(
            "---\n"
            "name: unifi-network\n"
            "metadata:\n"
            "  triggers:\n"
            "    - unifi\n"
            "---\n"
            "body\n"
        )

        self.assertEqual(sorted(fields or {}), ["metadata", "name"])


class SecretFreeValueTests(unittest.TestCase):
    """C6: the guarantee is about credential values, not credential field names."""

    def test_credential_in_an_allowed_free_text_field_is_reported(self) -> None:
        """The reviewed case: a password inside a `notes` string the schema allows."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "references" / "site-profile-example.json",
                json.dumps(
                    {
                        "site": "example",
                        "notes": "controller password=hunter2",
                        "ownership": "network team",
                    },
                    indent=2,
                ),
            )

            errors = check_repo.check_secret_free_values(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("credential value in", errors[0])
            self.assertIn("plugins/example/references/site-profile-example.json", errors[0])
            self.assertIn("credential-shaped value", errors[0])

    def test_bearer_token_in_a_description_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "references" / "site-profile.md",
                "# Site profile\n\ndescription: call it with bearer=aB9dEf2GhJ4kLm7Q\n",
            )

            errors = check_repo.check_secret_free_values(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("plugins/example/references/site-profile.md", errors[0])

    def test_a_well_known_credential_format_in_package_source_is_reported(self) -> None:
        """Family one runs on source too: a literal key is a leak wherever it sits."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "discover.py",
                'DEFAULT = "AKIAIOSFODNN7EXAMPLE"\n',
            )

            errors = check_repo.check_secret_free_values(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("AWS access key id", errors[0])
            self.assertIn("plugins/example/scripts/discover.py", errors[0])

    def test_a_private_key_block_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "references" / "setup.md",
                "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n",
            )

            errors = check_repo.check_secret_free_values(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("private key block", errors[0])

    def test_credential_handling_source_is_not_reported(self) -> None:
        """The false positives this rule was tuned against, taken from the package."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "discover.py",
                'api_key = (api_key or "").strip()\n'
                'headers = {"X-Api-Key": self.api_key, "Content-Type": "application/json"}\n'
                "return LiveTransport(host=resolved_host, api_key=resolved_key)\n",
            )

            self.assertEqual(check_repo.check_secret_free_values(root), [])

    def test_values_that_name_a_secret_rather_than_being_one_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "references" / "site-profile-example.json",
                json.dumps(
                    {
                        "password": "${VAULT_CONTROLLER_PASSWORD}",
                        "api_key": "REDACTED",
                        "token": "env:UNIFI_API_KEY",
                        "client_secret": "<your-client-secret>",
                        "access_key": "xxxxxxxxxxxx",
                        "notes": "ask the network owner for the controller credential",
                    },
                    indent=2,
                ),
            )

            self.assertEqual(check_repo.check_secret_free_values(root), [])

    def test_a_repository_without_packages_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check_repo.check_secret_free_values(Path(directory)), [])

    def test_a_strict_key_assigned_a_digitless_literal_is_reported(self) -> None:
        """The rule the entropy helper used to serve graded the wrong thing.

        ``rainbowtrout`` carries more entropy per character than ``oauth2`` and no
        digit, so the retired rule accepted the password and refused the word.
        """
        self.assertTrue(
            check_repo.credential_findings("password: rainbowtrout", include_assignments=True)
        )
        self.assertEqual(
            check_repo.credential_findings(
                "token: base64 of the site identifier", include_assignments=True
            ),
            [],
        )


def _fabricated_home(prefix: str, user: str, tail: str = "") -> str:
    """Build a ``/<prefix>/<user>/<tail>`` path from separate tokens.

    This test file is itself under ``tests/``, one of the directories the
    check under test scans. Writing the path as one contiguous string literal
    here would make this file trip its own rule; joining pieces with ``+`` at
    runtime keeps no single unbroken match sitting in the committed source.
    """
    pieces = ["/", prefix, "/", user, "/"]
    if tail:
        pieces.append(tail)
    return "".join(pieces)


class MachineSpecificPathTests(unittest.TestCase):
    """A real operator's home directory must never ship inside a package or its tooling."""

    def test_a_real_home_directory_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            home = _fabricated_home("Users", "jsmith", ".config/example")
            write(plugin / "scripts" / "discover.py", f'DEFAULT_HOME = "{home}"\n')

            errors = check_repo.check_machine_specific_paths(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn("plugins/example/scripts/discover.py", errors[0])
            self.assertIn(_fabricated_home("Users", "jsmith"), errors[0])

    def test_a_real_linux_home_directory_is_also_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            home = _fabricated_home("home", "jsmith", ".local/share/example")
            write(plugin / "README.md", f"Installs to {home}.\n")

            errors = check_repo.check_machine_specific_paths(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn(_fabricated_home("home", "jsmith"), errors[0])

    def test_the_operator_placeholder_is_never_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            users_operator = _fabricated_home("Users", "operator", ".example")
            home_operator = _fabricated_home("home", "operator", ".example")
            write(plugin / "README.md", f"Installs to {users_operator} and {home_operator}.\n")

            self.assertEqual(check_repo.check_machine_specific_paths(root), [])

    def test_the_documentation_placeholder_users_are_never_reported(self) -> None:
        """``example``, ``op``, and ``test`` are inert, not real accounts.

        These are the three placeholder usernames this repository's own
        fixtures already used before this check existed, named individually
        in ``INERT_HOME_DIRECTORY_USERS`` rather than allowlisted by file --
        an inert *name* cannot go stale the way an allowlisted *file* can.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            for prefix, user in (("home", "example"), ("home", "op"), ("Users", "test")):
                home = _fabricated_home(prefix, user, "share")
                write(plugin / "scripts" / f"{prefix}-{user}.py", f'PATH = "{home}"\n')

            self.assertEqual(check_repo.check_machine_specific_paths(root), [])

    def test_a_different_invented_username_is_not_inert(self) -> None:
        """Only the four named users are inert; a fifth invented one still trips."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            home = _fabricated_home("home", "example2", "share")
            write(plugin / "README.md", f"Installs to {home}.\n")

            errors = check_repo.check_machine_specific_paths(root)

            self.assertEqual(len(errors), 1, errors)
            self.assertIn(_fabricated_home("home", "example2"), errors[0])

    def test_docs_is_excluded_from_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = _fabricated_home("Users", "jsmith", "repo")
            write(root / "docs" / "evidence" / "capture.md", f"Captured at {home}.\n")

            self.assertEqual(check_repo.check_machine_specific_paths(root), [])

    def test_every_scanned_directory_is_covered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for directory_name in check_repo.MACHINE_SPECIFIC_PATH_SCAN_DIRECTORIES:
                home = _fabricated_home("Users", "jsmith", directory_name)
                write(root / directory_name / "hit.txt", f"{home}\n")

            errors = check_repo.check_machine_specific_paths(root)

            found = {error.split(":", 1)[0] for error in errors}
            self.assertEqual(
                found,
                {
                    f"{directory_name}/hit.txt"
                    for directory_name in check_repo.MACHINE_SPECIFIC_PATH_SCAN_DIRECTORIES
                },
            )

    def test_a_repository_without_the_scanned_directories_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check_repo.check_machine_specific_paths(Path(directory)), [])

    def test_a_word_that_merely_contains_users_is_not_mistaken_for_the_path(self) -> None:
        """A path segment ending in ``Users`` must not be read as the separator."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(plugin / "README.md", "See vendor/SubUsers/registry for the schema.\n")

            self.assertEqual(check_repo.check_machine_specific_paths(root), [])

    def test_the_gate_wires_this_check_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            home = _fabricated_home("Users", "jsmith", "example")
            write(plugin / "README.md", f"Captured on {home}.\n")

            self.assertTrue(
                any(
                    _fabricated_home("Users", "jsmith") in problem
                    for problem in check_repo.check_repo(root)
                )
            )

    def test_the_committed_repository_has_no_hits(self) -> None:
        """The real gate, against the real tree: no machine-specific path ships."""
        self.assertEqual(check_repo.check_machine_specific_paths(ROOT), [])


class ClaudeModuleSourceTests(unittest.TestCase):
    """A Claude Code mod is Claude-specific, so its source lives only in a Claude adapter."""

    ADAPTER = check_repo.CLAUDE_ADAPTER_DIRECTORY_NAME

    def findings(self, *relative_paths: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            make_plugin(root)
            for relative in relative_paths:
                write(root / relative, "export const x = 1\n")
            return check_repo.check_claude_module_sources(root)

    def test_a_module_inside_the_claude_adapter_is_accepted(self) -> None:
        self.assertEqual(
            self.findings(
                f"plugins/example/{self.ADAPTER}/mods/index.ts",
                f"plugins/example/{self.ADAPTER}/mods/index.test.ts",
                f"plugins/example/{self.ADAPTER}/types/index.d.ts",
                f"plugins/example/{self.ADAPTER}/mods/pane.tsx",
            ),
            [],
        )

    def test_typescript_outside_the_adapter_is_refused_and_named(self) -> None:
        misplaced = (
            "plugins/example/index.ts",
            "plugins/example/skills/example/pane.ts",
            "plugins/example/types/index.d.ts",
            "scripts/tool.ts",
            "tests/helper.mts",
        )
        problems = self.findings(*misplaced)
        self.assertEqual(len(problems), len(misplaced), problems)
        for relative in misplaced:
            with self.subTest(path=relative):
                self.assertTrue(
                    any(problem.startswith(f"{relative}:") for problem in problems), problems
                )
                self.assertTrue(any(self.ADAPTER in problem for problem in problems))

    #: Written out here rather than read from the gate, so narrowing the gate's
    #: list fails this test instead of shrinking it.
    ENGINE_SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

    def test_every_suffix_the_engine_loads_is_refused_outside_the_adapter(self) -> None:
        for suffix in self.ENGINE_SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertEqual(len(self.findings(f"plugins/example/mod{suffix}")), 1)

    def test_an_adapter_of_the_same_name_outside_a_package_is_not_an_adapter(self) -> None:
        # Only plugins/<package>/com.infiquetra.claude/ is a Claude adapter. A
        # directory that merely carries the name elsewhere does not launder a mod.
        self.assertEqual(len(self.findings(f"docs/{self.ADAPTER}/mods/index.ts")), 1)
        self.assertEqual(len(self.findings(f"vendor/example/{self.ADAPTER}/m.ts")), 1)
        self.assertEqual(len(self.findings(f"plugins/example/x/{self.ADAPTER}/m.ts")), 1)

    def test_engine_written_declarations_in_a_dot_directory_are_ignored(self) -> None:
        # ``claude --plugin-dir`` lays its API types into .claude-plugin/types/;
        # they ignore themselves in git and never ship.
        self.assertEqual(
            self.findings("plugins/example/.claude-plugin/types/claude-code/index.d.ts"), []
        )

    def test_committed_dot_directories_are_walked(self) -> None:
        # .claude-plugin/ and .codex-plugin/ are committed and ship, so a module
        # there is as misplaced as one at the package root; only the engine's
        # own .claude-plugin/types/ is skipped.
        misplaced = (
            "plugins/example/.claude-plugin/x.ts",
            "plugins/example/.claude-plugin/mods/index.ts",
            "plugins/example/.codex-plugin/x.ts",
            ".github/scripts/x.js",
        )
        problems = self.findings(
            *misplaced, "plugins/example/.claude-plugin/types/claude-code/index.d.ts"
        )
        self.assertEqual(len(problems), len(misplaced), problems)
        for relative in misplaced:
            with self.subTest(path=relative):
                self.assertTrue(any(p.startswith(f"{relative}:") for p in problems), problems)

    def test_a_types_directory_elsewhere_is_still_walked(self) -> None:
        self.assertEqual(len(self.findings("plugins/example/.codex-plugin/types/x.ts")), 1)

    def test_ignored_local_state_directories_are_not_walked(self) -> None:
        # Agent worktrees under .claude/ hold whole checkouts; walking them would
        # flag every adapter in them as outside an adapter.
        self.assertEqual(
            self.findings(
                ".git/hooks/x.js",
                ".claude/worktrees/w/plugins/saga/com.infiquetra.claude/mods/index.ts",
                ".venv/lib/x.js",
                ".saga/x.ts",
            ),
            [],
        )

    def test_cache_and_build_directories_are_ignored(self) -> None:
        self.assertEqual(
            self.findings(
                "plugins/example/__pycache__/x.js",
                "htmlcov/coverage_html_cb_6fb7b396.js",
                "dist/x.js",
                "build/x.js",
            ),
            [],
        )

    def test_a_dependency_directory_is_walked_because_git_does_not_ignore_it(self) -> None:
        misplaced = ("node_modules/pkg/index.js", "plugins/example/skills/node_modules/x.ts")
        problems = self.findings(*misplaced)
        self.assertEqual(len(problems), len(misplaced), problems)

    def test_the_engine_written_package_tsconfig_is_refused(self) -> None:
        problems = self.findings("plugins/example/tsconfig.json")
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("plugins/example/tsconfig.json:"), problems)
        # Inside the adapter, or deeper in the package, it is not the engine's file.
        self.assertEqual(
            self.findings(
                f"plugins/example/{self.ADAPTER}/tsconfig.json",
                "plugins/example/skills/example/tsconfig.json",
            ),
            [],
        )

    def test_every_pruned_directory_is_one_the_repository_ignores(self) -> None:
        # The walk without git restates part of .gitignore; it must never prune a
        # directory git would let a commit carry.
        ignored = {
            line.strip().strip("/")
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip().endswith("/") and not line.startswith("#")
        }
        unignored = set(check_repo.MODULE_SOURCE_PRUNED_DIRECTORY_NAMES) - ignored - {".git"}
        self.assertEqual(unignored, set())

    def test_the_repository_ignores_the_engine_written_package_tsconfig(self) -> None:
        self.assertIn(
            "plugins/*/tsconfig.json",
            (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines(),
        )


    def test_other_files_are_not_module_sources(self) -> None:
        self.assertEqual(
            self.findings("plugins/example/scripts/tool.py", "plugins/example/README.md"), []
        )

    def test_the_repository_itself_keeps_its_mods_in_the_adapters(self) -> None:
        self.assertEqual(check_repo.check_claude_module_sources(ROOT), [])


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class ClaudeModuleSourceGitTests(unittest.TestCase):
    """In a git work tree the candidates come from git, so .gitignore is the one authority."""

    ADAPTER = check_repo.CLAUDE_ADAPTER_DIRECTORY_NAME

    def repository(self, directory: str, gitignore: str) -> Path:
        root = Path(directory)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        make_plugin(root)
        write(root / ".gitignore", gitignore)
        return root

    def test_ignored_files_are_skipped_and_unignored_ones_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(directory, "htmlcov/\nplugins/*/tsconfig.json\n")
            for relative in (
                "htmlcov/coverage_html.js",
                "plugins/example/tsconfig.json",
                f"plugins/example/{self.ADAPTER}/mods/index.ts",
                "scripts/node_modules/hook.js",
                "plugins/example/skills/example/pane.ts",
            ):
                write(root / relative, "{}\n")
            problems = check_repo.check_claude_module_sources(root)
        self.assertEqual(
            sorted(problem.split(":")[0] for problem in problems),
            ["plugins/example/skills/example/pane.ts", "scripts/node_modules/hook.js"],
        )

    def test_a_force_added_package_tsconfig_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(directory, "plugins/*/tsconfig.json\n")
            write(root / "plugins/example/tsconfig.json", "{}\n")
            subprocess.run(
                ["git", "-C", str(root), "add", "-f", "plugins/example/tsconfig.json"], check=True
            )
            problems = check_repo.check_claude_module_sources(root)
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("plugins/example/tsconfig.json:"), problems)

    def test_a_root_below_the_top_of_some_other_work_tree_is_walked_instead(self) -> None:
        # A directory inside another checkout must not borrow that checkout's
        # .gitignore: here the outer repository ignores the whole root.
        with tempfile.TemporaryDirectory() as directory:
            outer = self.repository(directory, "inner/\n")
            root = outer / "inner"
            write(root / "scripts" / "hook.ts", "export const x = 1\n")
            problems = check_repo.check_claude_module_sources(root)
        self.assertEqual([problem.split(":")[0] for problem in problems], ["scripts/hook.ts"])


class ContinuousIntegrationTests(unittest.TestCase):
    """The CI workflow's test paths must match the repository's on-disk plugin test directories."""

    def test_ci_plugin_tests_glob_covers_all_on_disk_plugin_test_directories(self) -> None:
        ci_path = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_path.is_file(), f"missing {ci_path}")
        ci_text = ci_path.read_text(encoding="utf-8")

        on_disk_test_dirs = sorted(
            p.relative_to(ROOT).as_posix()
            for p in ROOT.glob("plugins/*/tests")
            if p.is_dir()
        )
        self.assertTrue(
            on_disk_test_dirs,
            "no plugin test directories found on disk to validate against CI",
        )
        self.assertIn(
            "pytest plugins/*/tests",
            ci_text,
            "ci.yml must invoke pytest with 'plugins/*/tests' to discover all ported plugin test suites",
        )

    def test_meta_check_fails_if_a_plugin_test_directory_is_not_matched_by_ci_pattern(self) -> None:
        """Control test: proves that meta-check fails if CI pattern does not match all test directories."""
        import fnmatch

        ci_pattern = "plugins/*/tests"
        covered = [
            d
            for d in ["plugins/mission-control/tests", "plugins/unifi/tests"]
            if fnmatch.fnmatch(d, ci_pattern)
        ]
        self.assertEqual(len(covered), 2)

        broken_pattern = "plugins/mission-control/tests"
        self.assertFalse(fnmatch.fnmatch("plugins/unifi/tests", broken_pattern))


class ReviewCalibrationTests(unittest.TestCase):
    """The repository check calls saga's one calibration implementation (issue 149)."""

    FORMULA = "plugins/saga/scripts/review_formula.py"

    def setUp(self) -> None:
        def refuse(*_args: object, **_kwargs: object) -> None:
            raise OSError("network blocked")

        self.enterContext(mock.patch.object(socket.socket, "connect", refuse))
        self.enterContext(mock.patch("socket.create_connection", refuse))

    def module(self):
        scripts = str(ROOT / "plugins" / "saga" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import review_calibration

        return review_calibration

    def copy_components(self, root: Path) -> None:
        for relative in self.module().COMPONENTS:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def write_no_run(self, root: Path) -> Path:
        self.copy_components(root)
        target = root / "plugins/saga/references/review-calibration.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / target.relative_to(root), target)
        return target

    def write_recorded(self, root: Path) -> None:
        module = self.module()
        self.copy_components(root)
        data = json.loads(
            (ROOT / "plugins/saga/references/review-calibration.json").read_text(encoding="utf-8")
        )
        data["corpus_run"] = "recorded"
        data["fingerprint"] = {
            relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
            for relative in module.COMPONENTS
        }
        overall = {
            "held_out_blocked": 0,
            "held_out_defects": 10,
            "held_out_false_blocks": 0,
            "held_out_clean": 10,
            "repeat_flips": 0,
            "repeat_cases": 10,
        }
        for row in data["lenses"].values():
            row["drift"] = "as-recorded"
            row["overall"] = dict(overall)
            row["languages"] = {}
        target = root / "plugins/saga/references/review-calibration.json"
        target.write_text(json.dumps(data), encoding="utf-8")

    def component_messages(self, problems: list[str]) -> list[str]:
        return [item for item in problems if "component:" in item]

    def test_no_run_accepts_a_changed_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_no_run(root)
            target = root / self.FORMULA
            target.write_bytes(target.read_bytes() + b"x")
            self.assertEqual(check_repo.check_review_calibration(root), [])

    def test_recorded_match_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_recorded(root)
            self.assertEqual(check_repo.check_review_calibration(root), [])

    def test_a_changed_component_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_recorded(root)
            target = root / self.FORMULA
            target.write_bytes(target.read_bytes() + b"x")
            expected = [f"changed component: {self.FORMULA}"]
            direct = check_repo.check_review_calibration(root)
            aggregate = check_repo.check_repo(root)
        self.assertEqual(self.component_messages(direct), expected)
        self.assertEqual(self.component_messages(aggregate), expected)

    def test_a_missing_component_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_recorded(root)
            (root / self.FORMULA).unlink()
            self.assertEqual(
                check_repo.check_review_calibration(root),
                [f"missing component: {self.FORMULA}"],
            )

    def test_an_unknown_key_is_named_without_a_recorded_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_no_run(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["comment"] = "x"
            path.write_text(json.dumps(data), encoding="utf-8")
            direct = check_repo.check_review_calibration(root)
            aggregate = check_repo.check_repo(root)
        self.assertTrue(any("comment" in item for item in direct), direct)
        self.assertTrue(any("comment" in item for item in aggregate), aggregate)

    def test_free_text_is_named_without_a_recorded_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.write_no_run(root)
            data = json.loads(path.read_text(encoding="utf-8"))
            data["langfuse_run_id"] = "a sentence with spaces"
            path.write_text(json.dumps(data), encoding="utf-8")
            problems = check_repo.check_review_calibration(root)
        self.assertTrue(any("langfuse_run_id" in item for item in problems), problems)

    def test_a_tree_without_saga_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check_repo.check_review_calibration(Path(directory)), [])

    def test_check_repo_surfaces_the_calibration_sentinel(self) -> None:
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(module, "check", return_value=["sentinel-calibration"]):
                problems = check_repo.check_repo(Path(directory))
        self.assertIn("sentinel-calibration", problems)

    def test_the_import_is_local_and_does_not_name_yaml(self) -> None:
        text = (ROOT / "scripts" / "check_repo.py").read_text(encoding="utf-8")
        self.assertNotIn("import yaml", text)
        lines = [line for line in text.splitlines() if "import review_calibration" in line]
        self.assertTrue(lines)
        for line in lines:
            self.assertTrue(line.startswith((" ", "\t")), line)

    def _yaml_free(self, target: Path) -> subprocess.CompletedProcess[str]:
        script = """
import sys
from pathlib import Path
live = Path(sys.argv[1])
target = Path(sys.argv[2])
sys.path.insert(0, str(live / "scripts"))
import check_repo
result = check_repo.check_review_calibration(target)
assert result == [], result
assert "yaml" not in sys.modules
"""
        return subprocess.run(
            [sys.executable, "-c", script, str(ROOT), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_the_live_check_does_not_import_yaml(self) -> None:
        completed = self._yaml_free(ROOT)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_the_recorded_compare_does_not_import_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_recorded(root)
            completed = self._yaml_free(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":

    unittest.main()
