from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402


CONFORMANT_SKILL = """---
name: unifi-network
description: Manage UniFi network infrastructure.
license: Apache-2.0
compatibility: python>=3.10
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


def write_provenance(plugin: Path, files: list[dict[str, object]]) -> Path:
    return write(
        plugin / check_repo.PROVENANCE_FILENAME,
        json.dumps(
            {
                "source_repository": "https://github.com/infiquetra/example",
                "source_commit": "0" * 40,
                "files": files,
            }
        ),
    )


def stamped_bundle(body: str, output_digest: str | None = None) -> str:
    if output_digest is None:
        output_digest = check_repo.sha256_text(body)
    return (
        f"{check_repo.BUNDLE_STAMP_BEGIN}\n"
        "# generated-by: scripts/bundle_fleet_module.py\n"
        "# source-version: 0.25.0\n"
        "# source-sha256: " + "a" * 64 + "\n"
        f"# {check_repo.BUNDLE_OUTPUT_DIGEST_FIELD}: {output_digest}\n"
        f"{check_repo.BUNDLE_STAMP_END}\n"
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

    def test_stamp_without_an_output_digest_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = make_plugin(root)
            write(
                plugin / "scripts" / "_bundled" / "retry_backoff.py",
                f"{check_repo.BUNDLE_STAMP_BEGIN}\n"
                "# source-version: 0.25.0\n"
                f"{check_repo.BUNDLE_STAMP_END}\n"
                "def retry():\n    return None\n",
            )

            errors = check_repo.check_bundled_files(root)

            self.assertEqual(len(errors), 1)
            self.assertIn(f"missing {check_repo.BUNDLE_OUTPUT_DIGEST_FIELD}", errors[0])

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


if __name__ == "__main__":
    unittest.main()
