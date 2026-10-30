"""Original independent root template audits, owned by the provisioned lane.

Keep each case's own canonical-template absence check; there is no module skip.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sync_template_docs


class TemplateSyncAuditTests(unittest.TestCase):
    """Audit of template-sync drift guard rules."""

    def test_template_sync_check_passes_when_templates_present(self) -> None:
        """When infiquetra-sdlc templates are present, check_reference must pass."""
        tmpl_dir = sync_template_docs.template_directory()
        if not tmpl_dir.exists():
            self.skipTest(f"infiquetra-sdlc templates not found at {tmpl_dir}; skipping sync check")
        self.assertTrue(sync_template_docs.check_reference())

    def test_template_sync_fails_on_drift(self) -> None:
        """Proving failure capability: drifted reference file fails check_reference.

        The injection happens in a temporary copy and the module constant is
        redirected for the test's duration, so the drift marker never touches
        the tracked file inside the fingerprinted package tree."""
        tmpl_dir = sync_template_docs.template_directory()
        if not tmpl_dir.exists():
            self.skipTest(f"infiquetra-sdlc templates not found at {tmpl_dir}; skipping drift check")

        real_path = sync_template_docs.REFERENCE_PATH
        original = real_path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_copy = Path(tmp) / "templates-reference.md"
            tmp_copy.write_text(original, encoding="utf-8")
            with patch.object(sync_template_docs, "REFERENCE_PATH", tmp_copy):
                tmp_copy.write_text(original + "\n## Drift Injected Section\n", encoding="utf-8")
                self.assertFalse(
                    sync_template_docs.check_reference(),
                    "check_reference() did not catch injected drift",
                )
                tmp_copy.write_text(original, encoding="utf-8")
                self.assertTrue(sync_template_docs.check_reference())
        self.assertNotIn(
            "Drift Injected Section",
            real_path.read_text(encoding="utf-8"),
            "the drift marker leaked into the tracked reference file",
        )

