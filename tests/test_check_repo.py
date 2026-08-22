from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402


class RepositoryValidationTests(unittest.TestCase):
    def test_live_repository_has_required_baseline(self) -> None:
        self.assertEqual(check_repo.check_required_paths(ROOT), [])

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
            plugin = root / "plugins" / "example"
            plugin.mkdir(parents=True)
            (plugin / "plugin.json").write_text(
                json.dumps(
                    {
                        "$schema": check_repo.PLUGIN_SCHEMA,
                        "name": "example",
                        "version": "0.1.0",
                        "description": "Example plugin",
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(check_repo.check_plugin_manifests(root), [])

    def test_plugin_directory_requires_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugins" / "example").mkdir(parents=True)

            self.assertEqual(
                check_repo.check_plugin_manifests(root),
                ["missing plugin manifest: plugins/example/plugin.json"],
            )


if __name__ == "__main__":
    unittest.main()
