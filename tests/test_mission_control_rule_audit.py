"""Class-first validation rule audit test suite for mission-control.

Unit U7 (runbook Phase 2): class-first rule auditing for all validation rules
the portable mission-control package carries, per the Phase 0 rule inventory in
docs/plans/2026-08-24-mission-control-port-u1-phase0-note.md:

  1. Card validator (sdlc_manager.validate_card_body): authority is
     home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py.
     Asserts verdict agreement across a class corpus of card bodies.
  2. Issue-contract parity (check_issue_contract_parity.py): offline digest
     equality and --live skip posture.
  3. Pagination lint (check_pagination.py): scans portable layout and enforces
     rejection of unguarded list/REST/GraphQL shapes.
  4. Prompt-alignment guard (test_prompt_alignment.py): records dropped custody
     limitations and asserts portable prompt invariants.
  5. Template-sync drift guard (sync_template_docs.py): template reference
     synchronization against canonical infiquetra-sdlc templates.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "mission-control"
SCRIPTS = PACKAGE / "scripts"
CONFIG = PACKAGE / "config"
GENERATED = CONFIG / "generated"

# Ensure package scripts can be imported
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_pagination  # noqa: E402
import sdlc_manager  # noqa: E402
import sync_template_docs  # noqa: E402


# ─── Authority Locators ───────────────────────────────────────────────────────


def _find_home_lab_card_validator() -> Path | None:
    """Locate home-lab card_validator.py authority checkout."""
    env_path = os.environ.get("HOME_LAB_PATH")
    candidates = [
        Path(env_path) if env_path else None,
        Path.home() / "workspace" / "infiquetra" / "home-lab",
        ROOT.parent / "home-lab",
    ]
    for candidate in candidates:
        if candidate is not None:
            target = candidate / "ansible" / "roles" / "hermes_orchestrator" / "files" / "card_validator.py"
            if target.exists():
                return target
    return None


def _load_home_lab_authority(authority_path: Path) -> Any:
    """Dynamically load home-lab card_validator.py authority module."""
    spec = importlib.util.spec_from_file_location("card_validator_authority", authority_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load authority spec at {authority_path}")
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so dataclasses decorator functions across Python versions
    sys.modules["card_validator_authority"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_parity_module() -> Any:
    """Load check_issue_contract_parity.py module."""
    parity_path = GENERATED / "check_issue_contract_parity.py"
    spec = importlib.util.spec_from_file_location("check_issue_contract_parity", parity_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load parity module at {parity_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─── Base Valid Card Fixture ─────────────────────────────────────────────────

VALID_CARD_CANONICAL = """### Objective
Add schema validator that gates plan-review on structured card fields.

### Intent
Cold agents waste planner rounds on malformed cards; gate at ingest so a card
either carries the contract or never reaches the planner.

### Acceptance criteria
- [ ] `pytest tests/test_card_validator.py` exits 0 on a well-formed card
- [ ] Cards missing required fields get a `needs-author-action` label

### Out-of-scope / non-goals
- Do NOT change the planner prompt in this card
- Do NOT add new required fields beyond those in the plan spec

### Files expected to change
ansible/roles/hermes_orchestrator/files/card_validator.py
ansible/roles/hermes_orchestrator/files/handlers.py

### Tests to add or update
tests/test_card_validator.py::test_accepts_fully_populated_card

### Verification
```bash
cd ansible/roles/hermes_orchestrator/files
pytest tests/test_card_validator.py -v
```

### Notes / conventions
- GitHub issue forms render fields as `### <Field Label>` headers

### Context library links
- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md
"""


# ─── 1. Card Validator Audit & Verdict Agreement ─────────────────────────────


class CardValidatorAuditTests(unittest.TestCase):
    """Audit and verdict-agreement tests for validate_card_body."""

    def setUp(self) -> None:
        self.authority_path = _find_home_lab_card_validator()
        if self.authority_path is None:
            self.skipTest("home-lab card_validator.py authority not found; skipping verdict agreement")
        self.authority = _load_home_lab_authority(self.authority_path)
        self.config = type("Config", (), {"authorized_authors": ["jefcox", "test-user"]})()

    def _eval_authority(self, body: str, labels: list[str] | None = None) -> tuple[bool, list[str]]:
        lbls = labels if labels is not None else ["capability"]
        issue = {"body": body, "user": {"login": "jefcox"}}
        res = self.authority.validate_card(issue, lbls, self.config)
        return res.passed, res.failures

    def _eval_portable(self, body: str) -> tuple[bool, list[str]]:
        return sdlc_manager.validate_card_body(body)

    def _eval_portable_context(self, body: str, issue_type: str, risk: str | None) -> tuple[bool, list[str]]:
        return sdlc_manager.validate_card_body_for_context(body, issue_type, risk)

    # ─── Corpus 1A: Valid Card Variants (Must Pass Both) ─────────────────────

    def test_verdict_agreement_canonical_card_passes(self) -> None:
        auth_passed, auth_fails = self._eval_authority(VALID_CARD_CANONICAL)
        port_valid, port_errs = self._eval_portable(VALID_CARD_CANONICAL)
        self.assertTrue(auth_passed, f"Authority failed canonical card: {auth_fails}")
        self.assertTrue(port_valid, f"Portable failed canonical card: {port_errs}")
        self.assertEqual(auth_passed, port_valid)

    def test_verdict_agreement_reordered_h3_headers(self) -> None:
        """Section ordering must not affect acceptance."""
        reordered = """### Verification
```bash
pytest -v
```

### Objective
Add feature with reordered sections.

### Intent
Prove parser does not depend on fixed header order.

### Acceptance criteria
- [ ] `pytest tests/test_foo.py` passes

### Out-of-scope / non-goals
- No changes to other tools

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
tests/test_foo.py

### Context library links
_none_
"""
        auth_passed, auth_fails = self._eval_authority(reordered)
        port_valid, port_errs = self._eval_portable(reordered)
        self.assertTrue(auth_passed, f"Authority failed reordered card: {auth_fails}")
        self.assertTrue(port_valid, f"Portable failed reordered card: {port_errs}")
        self.assertEqual(auth_passed, port_valid)

    def test_verdict_agreement_without_optional_notes(self) -> None:
        body = VALID_CARD_CANONICAL.replace("### Notes / conventions\n- GitHub issue forms render fields as `### <Field Label>` headers\n", "")
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertTrue(auth_passed)
        self.assertTrue(port_valid)

    def test_verdict_agreement_with_extra_unrecognized_headers(self) -> None:
        body = VALID_CARD_CANONICAL + "\n\n### Extra Context Section\nSome arbitrary author notes.\n"
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertTrue(auth_passed)
        self.assertTrue(port_valid)

    def test_verdict_agreement_context_library_none_markers(self) -> None:
        """_none_, none, and None are all valid whole-field declarations."""
        for marker in ("_none_", "none", "None", "_NONE_"):
            body = re.sub(
                r"### Context library links\n.*",
                f"### Context library links\n{marker}\n",
                VALID_CARD_CANONICAL,
                flags=re.DOTALL,
            )
            auth_passed, auth_fails = self._eval_authority(body)
            port_valid, port_errs = self._eval_portable(body)
            self.assertTrue(auth_passed, f"Authority rejected context marker {marker}: {auth_fails}")
            self.assertTrue(port_valid, f"Portable rejected context marker {marker}: {port_errs}")

    def test_verdict_agreement_acceptance_criteria_formats(self) -> None:
        """Checklist variants (- [ ], * [ ], - [x], * [X]) and runnable checks."""
        ac_variants = [
            "- [ ] `pytest tests/test_card_validator.py` exits 0\n* [X] `git diff --check` clean",
            "- [x] `python3 scripts/check_repo.py` passes\n- [ ] `make test` runs",
            "- [ ] Verifying suite:\n```\npytest -q\n```\n- [ ] Clean output",
        ]
        for ac in ac_variants:
            body = re.sub(
                r"### Acceptance criteria\n.*?\n\n###",
                f"### Acceptance criteria\n{ac}\n\n###",
                VALID_CARD_CANONICAL,
                flags=re.DOTALL,
            )
            auth_passed, auth_fails = self._eval_authority(body)
            port_valid, port_errs = self._eval_portable(body)
            self.assertTrue(auth_passed, f"Authority rejected valid AC variant:\n{ac}\nFailures: {auth_fails}")
            self.assertTrue(port_valid, f"Portable rejected valid AC variant:\n{ac}\nErrors: {port_errs}")

    def test_verdict_agreement_files_expected_formats(self) -> None:
        """Plausible path formats: directory/file, file.ext, bulleted paths."""
        file_variants = [
            "path/to/file.py",
            "ansible/roles/hermes_orchestrator/files/card_validator.py\nansible/roles/handlers.py",
            "- plugins/mission-control/scripts/sdlc_manager.py\n- tests/test_card_validator.py",
            "config.json",
        ]
        for fv in file_variants:
            body = re.sub(
                r"### Files expected to change\n.*?\n\n###",
                f"### Files expected to change\n{fv}\n\n###",
                VALID_CARD_CANONICAL,
                flags=re.DOTALL,
            )
            auth_passed, auth_fails = self._eval_authority(body)
            port_valid, port_errs = self._eval_portable(body)
            self.assertTrue(auth_passed, f"Authority rejected valid files variant: {fv}")
            self.assertTrue(port_valid, f"Portable rejected valid files variant: {fv}")

    def test_verdict_agreement_trailing_header_whitespace(self) -> None:
        """Headers with trailing whitespace must be parsed cleanly."""
        body = VALID_CARD_CANONICAL.replace("### Objective\n", "### Objective   \n")
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertTrue(auth_passed)
        self.assertTrue(port_valid)

    # ─── Corpus 1B: Missing Required Headers (Must Fail Both) ────────────────

    def test_verdict_agreement_missing_required_headers(self) -> None:
        required_headers = [
            "Objective",
            "Intent",
            "Out-of-scope / non-goals",
            "Files expected to change",
            "Tests to add or update",
            "Context library links",
            "Acceptance criteria",
            "Verification",
        ]
        for header in required_headers:
            body = VALID_CARD_CANONICAL.replace(f"### {header}\n", f"### Omitted {header}\n", 1)
            auth_passed, auth_fails = self._eval_authority(body)
            port_valid, port_errs = self._eval_portable(body)
            self.assertFalse(auth_passed, f"Authority unexpectedly passed card missing '{header}'")
            self.assertFalse(port_valid, f"Portable unexpectedly passed card missing '{header}'")
            self.assertEqual(auth_passed, port_valid)

    def test_verdict_agreement_h2_headers_rejected(self) -> None:
        """H2 headers do not satisfy H3 header requirements."""
        body = VALID_CARD_CANONICAL.replace("### Objective", "## Objective")
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_misspelled_header_rejected(self) -> None:
        """'Out-of-scope or non-goals' (with 'or') is rejected in favor of '/'."""
        body = VALID_CARD_CANONICAL.replace("### Out-of-scope / non-goals", "### Out-of-scope or non-goals")
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    # ─── Corpus 1C: Empty / Placeholder Sections (Must Fail Both) ────────────

    def test_verdict_agreement_empty_body_rejected(self) -> None:
        auth_passed, _ = self._eval_authority("")
        port_valid, _ = self._eval_portable("")
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_empty_section_rejected(self) -> None:
        body = VALID_CARD_CANONICAL.replace(
            "### Intent\nCold agents waste planner rounds on malformed cards; gate at ingest so a card\neither carries the contract or never reaches the planner.\n",
            "### Intent\n\n",
        )
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_placeholder_seeds_rejected(self) -> None:
        placeholders = [
            "_No response_",
            "<!-- placeholder -->",
            "- [ ]",
            "None",
        ]
        for ph in placeholders:
            body = re.sub(
                r"### Objective\n.*?\n\n###",
                f"### Objective\n{ph}\n\n###",
                VALID_CARD_CANONICAL,
                flags=re.DOTALL,
            )
            auth_passed, _ = self._eval_authority(body)
            port_valid, _ = self._eval_portable(body)
            self.assertFalse(auth_passed, f"Authority passed placeholder '{ph}' in Objective")
            self.assertFalse(port_valid, f"Portable passed placeholder '{ph}' in Objective")

    # ─── Corpus 1D: Semantic Violations (Must Fail Both) ─────────────────────

    def test_verdict_agreement_ac_missing_checklist(self) -> None:
        """Acceptance criteria with prose only and no `- [ ]` checklist."""
        body = re.sub(
            r"### Acceptance criteria\n.*?\n\n###",
            "### Acceptance criteria\nWe will test everything thoroughly.\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_ac_non_executable(self) -> None:
        """Checklist present but no runnable command in backticks or code block."""
        body = re.sub(
            r"### Acceptance criteria\n.*?\n\n###",
            "### Acceptance criteria\n- [ ] The feature works\n- [ ] Tests pass\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_files_expected_no_path(self) -> None:
        """Files expected has text but no path separator '/' or file extension."""
        body = re.sub(
            r"### Files expected to change\n.*?\n\n###",
            "### Files expected to change\nVarious modules across the codebase\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_verdict_agreement_verification_no_code_block(self) -> None:
        """Verification has text but no fenced code block."""
        body = re.sub(
            r"### Verification\n.*",
            "### Verification\nRun pytest in the main directory\n",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, _ = self._eval_authority(body)
        port_valid, _ = self._eval_portable(body)
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    # ─── Corpus 1E: Risk-Tier Sections (Context-Aware) ────────────────────────

    def test_verdict_agreement_low_risk_context_aware(self) -> None:
        """Low risk cards pass without high-blast sections."""
        auth_passed, _ = self._eval_authority(VALID_CARD_CANONICAL, ["capability", "risk:low"])
        port_valid, _ = self._eval_portable_context(VALID_CARD_CANONICAL, "capability", "low")
        self.assertTrue(auth_passed)
        self.assertTrue(port_valid)

    def test_verdict_agreement_high_risk_missing_sections(self) -> None:
        """High risk cards missing high-blast sections are rejected by both."""
        auth_passed, auth_fails = self._eval_authority(VALID_CARD_CANONICAL, ["capability", "risk:high"])
        port_valid, port_errs = self._eval_portable_context(VALID_CARD_CANONICAL, "capability", "high")
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)
        self.assertTrue(any("Inputs inventory" in f for f in auth_fails))
        self.assertTrue(any("Inputs inventory" in e for e in port_errs))

    def test_verdict_agreement_high_risk_populated_passes(self) -> None:
        """High risk cards with Inputs, Failure modes, and Stop conditions pass."""
        high_body = VALID_CARD_CANONICAL + """

### Inputs inventory
- config/sdlc-schema.json
- home-lab inventory

### Failure modes / pre-mortem
- network partition at ingest
- stale schema

### Stop conditions
- unrecoverable data loss detected
"""
        auth_passed, auth_fails = self._eval_authority(high_body, ["capability", "risk:high"])
        port_valid, port_errs = self._eval_portable_context(high_body, "capability", "high")
        self.assertTrue(auth_passed, f"Authority rejected populated high-risk card: {auth_fails}")
        self.assertTrue(port_valid, f"Portable rejected populated high-risk card: {port_errs}")

    def test_verdict_agreement_high_risk_placeholder_sections_rejected(self) -> None:
        """High risk cards with placeholder in risk sections are rejected."""
        high_body = VALID_CARD_CANONICAL + """

### Inputs inventory
_No response_

### Failure modes / pre-mortem
_No response_

### Stop conditions
_No response_
"""
        auth_passed, _ = self._eval_authority(high_body, ["capability", "risk:high"])
        port_valid, _ = self._eval_portable_context(high_body, "capability", "high")
        self.assertFalse(auth_passed)
        self.assertFalse(port_valid)

    def test_authority_derived_data_structures(self) -> None:
        """Direct assertion that authority field definitions agree with portable shim data."""
        self.assertEqual(
            tuple(self.authority.REQUIRED_FIELDS),
            (
                "objective",
                "intent",
                "non_goals",
                "files_expected",
                "tests_required",
                "context_library_links",
                "acceptance_criteria",
                "verification",
            ),
        )
        self.assertEqual(len(self.authority.FIELD_HEADERS), 13)


# ─── 2. Issue Contract Parity Audit ──────────────────────────────────────────


class IssueContractParityAuditTests(unittest.TestCase):
    """Audit of issue-contract parity checking rules."""

    def setUp(self) -> None:
        self.parity = _load_parity_module()

    def test_offline_digest_equality_holds(self) -> None:
        """Offline parity check: recomputed SHA256 matches pinned .sha256 sidecars."""
        errors = self.parity.parity_errors()
        self.assertEqual(errors, [], f"Offline parity check reported errors: {errors}")

    def test_injected_drift_in_data_is_caught(self) -> None:
        """Proving failure capability: modifying data artifact fails parity check."""
        data_path = GENERATED / "issue_contract_data.py"
        original = data_path.read_bytes()
        try:
            data_path.write_bytes(original + b"\n# drift\n")
            errors = self.parity.parity_errors()
            self.assertTrue(errors, "parity_errors() did not catch injected DATA drift")
            self.assertTrue(any("drifted" in e for e in errors))
        finally:
            data_path.write_bytes(original)
        self.assertEqual(self.parity.parity_errors(), [])

    def test_injected_drift_in_shim_is_caught(self) -> None:
        """Proving failure capability: modifying shim artifact fails parity check."""
        shim_path = GENERATED / "issue_contract_shim.py"
        original = shim_path.read_bytes()
        try:
            shim_path.write_bytes(original + b"\n# drift\n")
            errors = self.parity.parity_errors()
            self.assertTrue(errors, "parity_errors() did not catch injected SHIM drift")
            self.assertTrue(any("drifted" in e for e in errors))
        finally:
            shim_path.write_bytes(original)
        self.assertEqual(self.parity.parity_errors(), [])

    def test_live_leg_unavailable_raises_and_skips_loudly(self) -> None:
        """Live parity leg raises LiveParityUnavailableError when unauthenticated."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_schema = Path(tmp_dir) / "sdlc-schema.json"
            with self.assertRaises(self.parity.LiveParityUnavailableError):
                self.parity.live_status_option_errors(
                    schema_path=missing_schema,
                    fetch_fields_census=lambda _: {"fields": []},
                    project_mappings={},
                )


# ─── 3. Pagination Lint Audit ────────────────────────────────────────────────


class PaginationLintAuditTests(unittest.TestCase):
    """Audit of pagination lint rules and class corpus."""

    def test_portable_tree_passes_pagination_lint(self) -> None:
        """Scans the portable mission-control layout with zero violations."""
        violations = check_pagination.run_lint()
        self.assertEqual(violations, [], f"Pagination lint failed on portable tree: {violations}")

    def test_rejects_unguarded_raw_item_list(self) -> None:
        """Proving failure capability: raw item-list without --limit is rejected."""
        with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as f:
            f.write("```bash\ngh project item-list 4 --owner infiquetra\n```\n")
            temp_path = Path(f.name)
        try:
            violations = check_pagination.check_file(temp_path)
            self.assertTrue(violations)
            self.assertTrue(any("gh project item-list" in v for v in violations))
        finally:
            temp_path.unlink()

    def test_rejects_bare_rest_get_with_per_page(self) -> None:
        """Proving failure capability: bare _rest_get with per_page is rejected."""
        with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
            f.write('items = _rest_get("/repos/org/repo/issues?per_page=100")\n')
            temp_path = Path(f.name)
        try:
            violations = check_pagination.check_file(temp_path)
            self.assertTrue(violations)
            self.assertTrue(any("_rest_list_paginated" in v for v in violations))
        finally:
            temp_path.unlink()

    def test_rejects_graphql_first_without_has_next_page(self) -> None:
        """Proving failure capability: GraphQL first: without hasNextPage is rejected."""
        with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
            f.write('QUERY = """query { projectV2(number: 1) { items(first: 50) { nodes { id } } } }"""\n')
            temp_path = Path(f.name)
        try:
            violations = check_pagination.check_file(temp_path)
            self.assertTrue(violations)
            self.assertTrue(any("hasNextPage" in v for v in violations))
        finally:
            temp_path.unlink()

    def test_accepts_guarded_shapes(self) -> None:
        """Corpus of valid/guarded pagination call sites."""
        valid_cases = [
            ("```bash\ngh project item-list 4 --owner infiquetra --limit 1000\n```\n", ".md"),
            ("```bash\ngh project item-list 4 \\\n  --limit 500\n```\n", ".md"),
            ("# gh project item-list is a documented CLI command\n", ".py"),
            ('items = _rest_list_paginated("/repos/org/repo/issues")\n', ".py"),
            ('items = _rest_get("/url?per_page=50")  # pagination-lint: allow\n', ".py"),
            ('QUERY = """query { items(first: 50) { pageInfo { hasNextPage } } }"""\n', ".py"),
        ]
        for content, suffix in valid_cases:
            with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False) as f:
                f.write(content)
                temp_path = Path(f.name)
            try:
                violations = check_pagination.check_file(temp_path)
                self.assertEqual(violations, [], f"Valid pagination case falsely flagged: {content}")
            finally:
                temp_path.unlink()


# ─── 4. Prompt Alignment Guard Audit ─────────────────────────────────────────


class PromptAlignmentAuditTests(unittest.TestCase):
    """Audit of prompt alignment predicates and portable layout boundaries."""

    def test_prompt_alignment_dropped_custody_is_recorded(self) -> None:
        """Verify that test_prompt_alignment.py is recorded as dropped_from_source in descriptor and PROVENANCE."""
        desc = json.loads((ROOT / "ports" / "mission-control.json").read_text(encoding="utf-8"))
        self.assertIn("tests/test_prompt_alignment.py", desc.get("custody", {}).get("dropped_from_source", []))

        provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))
        removed_sources = [r["source_path"] for r in provenance.get("removed_from_source", [])]
        self.assertIn("plugins/mission-control/tests/test_prompt_alignment.py", removed_sources)

    def test_structural_premises_are_honestly_evaluated(self) -> None:
        """Verify the 6 structural reasons why prompt-alignment cannot run unmodified."""
        # 1. Claude manifest is relocated (not at package root .claude-plugin/plugin.json)
        self.assertFalse((PACKAGE / ".claude-plugin" / "plugin.json").exists())
        self.assertTrue((PACKAGE / "com.infiquetra.claude" / "plugin.json").exists())

        # 2. Mission Control is not published through a Claude marketplace.
        #    A repo-root marketplace exists since 2026-08-25, when the `voice`
        #    package became installable from this repository, so its mere
        #    presence no longer carries this premise. What matters for Mission
        #    Control is unchanged and is what is checked: no entry names it, so
        #    nothing here installs it as a Claude plugin.
        marketplace = ROOT / ".claude-plugin" / "marketplace.json"
        if marketplace.exists():
            listed = {
                entry.get("name")
                for entry in json.loads(marketplace.read_text(encoding="utf-8")).get(
                    "plugins", []
                )
            }
            self.assertNotIn("mission-control", listed)

        # 3. Client extensions are relocated under com.infiquetra.claude/
        self.assertFalse((PACKAGE / "agents" / "sdlc-operator.md").exists())
        self.assertTrue((PACKAGE / "com.infiquetra.claude" / "agents" / "sdlc-operator.md").exists())

        # 4. Commands are relocated
        self.assertFalse((PACKAGE / "commands" / "triage.md").exists())
        self.assertTrue((PACKAGE / "com.infiquetra.claude" / "commands" / "triage.md").exists())

        # 5. Package README is target-owned portable documentation
        readme_text = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("Portable Agent Plugins 1.0 package", readme_text)

        # 6. Saga plugin is absent from repo root
        self.assertFalse((ROOT / "plugins" / "saga").exists())

    def test_portable_prompts_and_references_carry_current_taxonomy(self) -> None:
        """Verify portable reference docs carry current template labels and taxonomy."""
        issue_types_doc = (PACKAGE / "skills" / "issues" / "references" / "issue-types.md").read_text(encoding="utf-8")
        self.assertIn("`capability`, `needs-plan`", issue_types_doc)
        self.assertIn("`enhancement`, `needs-plan`", issue_types_doc)
        self.assertIn("`defect`, `needs-plan`", issue_types_doc)
        self.assertNotIn("hermes-task", issue_types_doc)
        self.assertNotIn("hermes-not-actionable", issue_types_doc)

        operator_doc = (PACKAGE / "com.infiquetra.claude" / "agents" / "sdlc-operator.md").read_text(encoding="utf-8")
        self.assertIn("(capability/enhancement/defect)", operator_doc)
        self.assertNotIn("hermes-task", operator_doc)
        self.assertNotIn("hermes-not-actionable", operator_doc)


# ─── 5. Template Sync Drift Guard Audit ──────────────────────────────────────


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


# ─── 6. Create-Option No-Write Guard (operator ruling 4) ─────────────────────


class CreateOptionNoWriteGuardTests(unittest.TestCase):
    """`fields create-option` performs NO mutation — the guard proves the write
    path is never reached, in the style upstream's test_option_identity.py uses
    for its own error paths: the destructive mutation constant
    `QUERY_UPDATE_FIELD_OPTIONS` is asserted never sent."""

    FIELD_ID = "PVTF_status"

    @staticmethod
    def _mutation_calls(mock_graphql):
        return [
            c
            for c in mock_graphql.call_args_list
            if c.args[0] == sdlc_manager.QUERY_UPDATE_FIELD_OPTIONS
        ]

    def test_create_option_reaches_no_write_path(self) -> None:
        project = {"number": 2, "id": "PVT_asgard"}
        field = {
            "id": self.FIELD_ID,
            "name": "Status",
            "options": [{"id": "OPT_idea", "name": "Idea"}],
        }
        with (
            patch.object(
                sdlc_manager,
                "load_config",
                return_value={"project_mappings": {"projects": {"asgard": project}}},
            ),
            patch.object(sdlc_manager, "get_project_config", return_value=project),
            patch.object(sdlc_manager, "get_project_fields", return_value=("PVT_asgard", [field])),
            patch.object(sdlc_manager, "_graphql") as mock_graphql,
            patch.object(sdlc_manager, "_gh") as mock_gh,
        ):
            sdlc_manager.fields_create_option("asgard", "Status", "Idea", "json")
        self.assertEqual(
            self._mutation_calls(mock_graphql),
            [],
            "fields create-option reached the destructive mutation path "
            "(QUERY_UPDATE_FIELD_OPTIONS was sent)",
        )
        self.assertEqual(
            mock_graphql.call_count,
            0,
            "fields create-option issued a GraphQL call on the discover-and-print path",
        )
        self.assertEqual(
            mock_gh.call_count,
            0,
            "fields create-option reached the subprocess door (a live gh call would be a write)",
        )

    def test_create_option_still_prints_when_the_field_is_absent(self) -> None:
        """The no-write property must hold on the error path too: an absent field
        fails the command without any GraphQL call, mutation or otherwise."""
        project = {"number": 2, "id": "PVT_asgard"}
        with (
            patch.object(
                sdlc_manager,
                "load_config",
                return_value={"project_mappings": {"projects": {"asgard": project}}},
            ),
            patch.object(sdlc_manager, "get_project_config", return_value=project),
            patch.object(sdlc_manager, "get_project_fields", return_value=("PVT_asgard", [])),
            patch.object(sdlc_manager, "_graphql") as mock_graphql,
            patch.object(sdlc_manager, "_gh") as mock_gh,
        ):
            with self.assertRaises(SystemExit):
                sdlc_manager.fields_create_option("asgard", "Status", "Idea", "json")
        self.assertEqual(self._mutation_calls(mock_graphql), [])
        self.assertEqual(mock_graphql.call_count, 0)
        self.assertEqual(mock_gh.call_count, 0)


# ─── 7. Manifest-Version Derivation (KTD5) ───────────────────────────────────


class ManifestVersionDerivationTests(unittest.TestCase):
    """`plugins/mission-control/plugin.json`'s version is derived from
    `PROVENANCE.json`'s `source_version`, on the pattern shipped for
    agent-launcher in tests/test_agent_launcher_packaging.py — a hand-edited
    manifest that diverges from the provenance record fails here."""

    def test_manifest_version_equals_provenance_source_version(self) -> None:
        manifest = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["version"],
            provenance["source_version"],
            "the portable manifest version diverged from the provenance source_version; "
            "derive it deliberately, never retype it",
        )


# ─── 8. Root README Pin (KTD6) ────────────────────────────────────────────────


class RootReadmePinTests(unittest.TestCase):
    """The root README's Mission Control identity claims are recomputed from
    disk and derived from PROVENANCE.json rather than retyped, so a stale
    revision, version, or count fails instead of sitting there. The #9 run's
    only review finding was exactly this class: a hand-authored Packages row
    with no derivation and no pin test."""

    def test_the_packages_table_row_derives_from_provenance(self) -> None:
        provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))
        short_pin = provenance["source_commit"][:8]
        version = provenance["source_version"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            f"`{short_pin}` (v{version})",
            readme,
            "the root README's Mission Control Packages row names a revision or version "
            "that does not match the provenance manifest; derive it, never retype it",
        )

    def test_the_file_count_is_recomputed_from_disk(self) -> None:
        # The same exclusion set the compatibility checker's fingerprint uses
        # (its docstring documents them): tool cache directories and .DS_Store
        # are checkout noise; everything else counts.
        noise = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".DS_Store"}
        file_count = 0
        for path in PACKAGE.rglob("*"):
            if not path.is_file():
                continue
            parts = set(path.relative_to(PACKAGE).parts)
            if parts & noise:
                continue
            file_count += 1
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            f"{file_count}-file portable package",
            readme,
            "the root README's package file count was retyped and went stale; "
            "recompute it from disk",
        )
        self.assertIn(
            f"ships {file_count} portable files",
            readme,
            "the root README's package file count was retyped and went stale; "
            "recompute it from disk",
        )

    def test_the_test_file_count_is_recomputed_from_disk(self) -> None:
        """The README claim is parsed and compared, not searched for a
        rendering of the count: an out-of-table count fails explicitly instead
        of falling back to a substring that unrelated text could satisfy."""
        test_files = sorted((PACKAGE / "tests").glob("*.py"))
        number_word = {
            27: "Twenty-seven",
            28: "Twenty-eight",
            29: "Twenty-nine",
        }
        self.assertIn(
            len(test_files),
            number_word,
            "the package test-file count moved outside the word table; extend number_word "
            "deliberately rather than letting the guard fall back to a substring search",
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        claim = re.search(r"(\S+) test files \((\d+) tests\)", readme)
        self.assertIsNotNone(claim, "the root README's test-file sentence is missing")
        assert claim is not None
        self.assertEqual(
            claim.group(1),
            number_word[len(test_files)],
            "the root README's test-file count was retyped and went stale; "
            "recompute it from disk",
        )

    def test_the_test_count_is_recomputed_by_collection(self) -> None:
        import subprocess

        try:
            import pytest  # noqa: F401
        except ModuleNotFoundError as exc:  # pragma: no cover - hermetic baseline has no pytest
            self.skipTest(f"pytest not installed in this interpreter: {exc}")
        collected = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(PACKAGE / "tests"),
                "--collect-only",
                "-q",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(
            collected.returncode,
            0,
            f"pytest --collect-only failed:\nstdout:\n{collected.stdout}\nstderr:\n{collected.stderr}",
        )
        match = re.search(r"(\d+) tests collected", collected.stdout)
        self.assertIsNotNone(match, collected.stdout)
        assert match is not None
        test_count = int(match.group(1))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        claim = re.search(r"(\S+) test files \((\d+) tests\)", readme)
        self.assertIsNotNone(claim, "the root README's test-file sentence is missing")
        assert claim is not None
        self.assertEqual(
            int(claim.group(2)),
            test_count,
            "the root README's ported-test count was retyped and went stale; "
            "recompute it by collection",
        )
        self.assertIn(
            f"{test_count} CI tests",
            readme,
            "the root README's CI test count was retyped and went stale; "
            "recompute it by collection",
        )


if __name__ == "__main__":
    unittest.main()
