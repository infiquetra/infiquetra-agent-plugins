"""Staged Saga version behavior requires Saga's provisioned import dependencies."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
import test_sync_marketplace as _marketplace

sm = _marketplace.sm


class ProvisionedStageMusePluginTests(unittest.TestCase):
    # Share only the original scratch-root fixture, not the root test classes.
    setUp = _marketplace.MarketplaceCase.setUp

    def test_a_staged_saga_still_reports_the_saga_version(self) -> None:
        """A staged copy drops the root manifest, so a reader of it must have a fallback."""
        staged = sm.stage_muse_plugin(ROOT / "plugins" / "saga", self.root / "staged" / "saga")
        self.assertFalse((staged / "plugin.json").exists())
        expected = json.loads((ROOT / "plugins/saga/plugin.json").read_text(encoding="utf-8"))
        program = (
            "import sys; sys.path.insert(0, sys.argv[1]); import review_command; "
            "print(review_command._saga_version())"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-c", program, str(staged / "scripts")],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), expected["version"])

