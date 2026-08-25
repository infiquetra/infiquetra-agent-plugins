from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":

    unittest.main()
