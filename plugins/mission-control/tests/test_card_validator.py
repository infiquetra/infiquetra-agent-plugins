"""Tests for the card_validator shim.

The shim mirrors home-lab/.../card_validator.py's always-required, body-only
checks: the required H3 headers (incl. the U8 Intent + Context library links),
AC has >=1 checklist item AND names a runnable check (executable acceptance,
R2/KTD8), Verification has >=1 fenced code block, Files-expected has >=1 path-like
line, no placeholder-only sections (the Context library links `_none_`
declaration excepted). The risk-conditional matrix (R5-R7) is the home-lab gate's
job -- the shim has no Risk/issue-type input.
"""

import sys
from pathlib import Path

# Make scripts importable as a package: tests/ is sibling of scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

# Updated 2026-06-14 for the U8 context-package contract expansion: the card now
# carries the new always-required Intent (R1), the acceptance criteria name a
# runnable check (R2/KTD8 — `code spans`), and Context library links is required
# (R4). The shim validates the body alone (no Risk/issue-type), so it enforces
# the always-required headers + executable acceptance; the risk-conditional
# fields (R5-R7) are the home-lab gate's job.
VALID_BODY = """### Objective
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


def test_accepts_fully_populated_card() -> None:
    is_valid, errors = sdlc_manager.validate_card_body(VALID_BODY)
    assert is_valid, f"Expected valid; got errors: {errors}"
    assert errors == []


def test_rejects_missing_required_header() -> None:
    body = VALID_BODY.replace("### Verification\n", "### Removed\n", 1)
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Missing required H3 sections" in e and "Verification" in e for e in errors)


def test_rejects_missing_checklist_in_acceptance_criteria() -> None:
    body = VALID_BODY.replace(
        "- [ ] `pytest tests/test_card_validator.py` exits 0 on a well-formed card\n"
        "- [ ] Cards missing required fields get a `needs-author-action` label",
        "Validator runs on webhook events. Cards without required fields fail.",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Acceptance criteria" in e and "checklist" in e for e in errors)


def test_rejects_missing_code_block_in_verification() -> None:
    body = VALID_BODY.replace(
        "```bash\ncd ansible/roles/hermes_orchestrator/files\n"
        "pytest tests/test_card_validator.py -v\n```",
        "Run pytest in the orchestrator role directory.",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Verification" in e and "fenced code block" in e for e in errors)


def test_rejects_missing_path_line_in_files_expected() -> None:
    body = VALID_BODY.replace(
        "ansible/roles/hermes_orchestrator/files/card_validator.py\n"
        "ansible/roles/hermes_orchestrator/files/handlers.py",
        "TBD — will figure out at implementation time",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Files expected to change" in e and "path-like" in e for e in errors)


def test_rejects_placeholder_only_section() -> None:
    body = VALID_BODY.replace(
        "Add schema validator that gates plan-review on structured card fields.",
        "_No response_",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Objective" in e and "placeholder" in e for e in errors)


def test_rejects_empty_required_section() -> None:
    body = VALID_BODY.replace(
        "### Intent\n"
        "Cold agents waste planner rounds on malformed cards; gate at ingest so a card\n"
        "either carries the contract or never reaches the planner.\n\n",
        "### Intent\n\n",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Intent" in e and "empty" in e for e in errors)


def test_handles_empty_body() -> None:
    is_valid, errors = sdlc_manager.validate_card_body("")
    assert not is_valid
    # All 6 required sections missing
    assert any("Missing required H3" in e for e in errors)


def test_section_split_handles_h3_with_trailing_whitespace() -> None:
    # Some GitHub markdown renderers add trailing whitespace after the title;
    # the parser must accept it.
    body = VALID_BODY.replace("### Objective\n", "### Objective   \n", 1)
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert is_valid, f"Expected valid even with trailing whitespace; got: {errors}"


def test_h2_headers_do_not_match_h3_parser() -> None:
    # An H2 with the same name should NOT be treated as an H3 section
    body = VALID_BODY.replace("### Objective", "## Objective")
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Missing required H3 sections" in e and "Objective" in e for e in errors)


def test_optional_sections_not_required() -> None:
    # Strip the truly-optional Notes section — body should still validate.
    # Context library links is NOT optional anymore (U8/R4: required-or-`_none_`),
    # so it stays; only Notes is removed here.
    body = VALID_BODY.replace(
        "### Notes / conventions\n"
        "- GitHub issue forms render fields as `### <Field Label>` headers\n\n",
        "",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert is_valid, f"Expected valid without optional sections; got: {errors}"


def test_required_headers_match_actual_issue_templates() -> None:
    """Drift guard: the validator's _REQUIRED_H3_HEADERS list must match the
    `label:` fields in `infiquetra-sdlc/.github/ISSUE_TEMPLATE/{capability,
    enhancement,defect}.yml`. If a template adds/renames a section, this
    test fails so the validator can be updated in the same PR.

    This is the test that PR #114's review caught was missing — the original
    validator used 'Out-of-scope or non-goals' (with 'or') while the actual
    templates use 'Out-of-scope / non-goals' (with '/'), and no test was
    pinning the contract end-to-end."""
    import os

    sdlc_path = Path(
        os.environ.get("INFIQUETRA_SDLC_PATH", Path.home() / "workspace/infiquetra/infiquetra-sdlc")
    )
    template_dir = sdlc_path / ".github" / "ISSUE_TEMPLATE"
    if not template_dir.exists():
        # Skip if running outside the developer's workspace (e.g., on a
        # build agent without the sibling repo). The drift guard runs in
        # CI when the repos are checked out together.
        import pytest

        pytest.skip(f"Templates not at {template_dir}; skipping drift check")

    # Extract `label:` strings from the 3 actionable templates
    import re as _re

    template_headers: dict[str, set[str]] = {}
    for tmpl in ("capability.yml", "enhancement.yml", "defect.yml"):
        text = (template_dir / tmpl).read_text()
        labels = set(_re.findall(r"^\s+label:\s*(.+?)\s*$", text, _re.MULTILINE))
        template_headers[tmpl] = labels

    # Every required validator header must appear as a label in every
    # actionable template
    for tmpl, labels in template_headers.items():
        for required in sdlc_manager._REQUIRED_H3_HEADERS:
            assert required in labels, (
                f"Validator requires '{required}' but {tmpl} doesn't have a "
                f"matching `label:` field. Templates have: {sorted(labels)}"
            )


# ─── U8: context-package shim checks (Intent + executable AC + `_none_`) ──────
#
# The shim is a pre-flight on the body alone (no Risk/issue-type input), so it
# mirrors the home-lab validator's ALWAYS-required surface: the new Intent (R1)
# and Context library links (R4) headers + the executable-acceptance check
# (R2/KTD8). The risk-conditional matrix (R5-R7) is enforced by the home-lab gate.


def test_intent_now_required() -> None:
    """R1: Intent is an always-required header the shim enforces."""
    body = VALID_BODY.replace(
        "### Intent\n"
        "Cold agents waste planner rounds on malformed cards; gate at ingest so a card\n"
        "either carries the contract or never reaches the planner.\n\n",
        "",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Missing required H3 sections" in e and "Intent" in e for e in errors)


def test_context_links_now_required() -> None:
    """R4: Context library links is required (was optional)."""
    body = VALID_BODY.replace(
        "### Context library links\n"
        "- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md\n",
        "",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Missing required H3 sections" in e and "Context library links" in e for e in errors)


def test_context_links_bare_none_accepted() -> None:
    """R4: a whole-field `_none_` declaration satisfies the requirement (it is
    NOT flagged as placeholder-only)."""
    body = VALID_BODY.replace(
        "### Context library links\n"
        "- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md\n",
        "### Context library links\n_none_\n",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert is_valid, f"Expected `_none_` to satisfy context-links; got: {errors}"


def test_non_executable_acceptance_rejected() -> None:
    """R2/KTD8: a checklist whose items name no runnable check is rejected."""
    body = VALID_BODY.replace(
        "- [ ] `pytest tests/test_card_validator.py` exits 0 on a well-formed card\n"
        "- [ ] Cards missing required fields get a `needs-author-action` label",
        "- [ ] The validator works\n- [ ] Nothing regresses",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert not is_valid
    assert any("Acceptance criteria" in e and "executable" in e for e in errors)


def test_executable_acceptance_via_fenced_block_accepted() -> None:
    """A fenced ``` block inside the acceptance section is executable evidence."""
    body = VALID_BODY.replace(
        "- [ ] `pytest tests/test_card_validator.py` exits 0 on a well-formed card\n"
        "- [ ] Cards missing required fields get a `needs-author-action` label",
        "- [ ] Running the suite passes:\n```\npytest -q\n```\n- [ ] No regressions",
    )
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert is_valid, f"Expected fenced-block AC to be executable; got: {errors}"


def test_context_aware_validator_keeps_low_risk_body_compatible() -> None:
    is_valid, errors = sdlc_manager.validate_card_body_for_context(
        VALID_BODY, issue_type="capability", risk="low"
    )

    assert is_valid, f"Expected low-risk card to pass; got: {errors}"


def test_context_aware_validator_requires_high_risk_sections() -> None:
    is_valid, errors = sdlc_manager.validate_card_body_for_context(
        VALID_BODY, issue_type="capability", risk="high"
    )

    assert not is_valid
    assert any("Inputs inventory" in err for err in errors)
    assert any("Failure modes / pre-mortem" in err for err in errors)
    assert any("Stop conditions" in err for err in errors)


def test_context_aware_validator_rejects_empty_high_risk_section() -> None:
    body = (
        VALID_BODY
        + "\n\n### Inputs inventory\n\n### Failure modes / pre-mortem\n_No response_\n\n### Stop conditions\n_No response_\n"
    )

    is_valid, errors = sdlc_manager.validate_card_body_for_context(
        body, issue_type="capability", risk="high"
    )

    assert not is_valid
    assert any("Inputs inventory" in err and "empty" in err for err in errors)


# --- Recommended tier band (#368 AC5) --------------------------------------


def test_recommended_tier_band_field() -> None:
    """AC5: the validator accepts a card carrying the band, and the type map holds."""
    body = VALID_BODY + "\n\n### Recommended Tier Band\nopus/high\n"
    is_valid, errors = sdlc_manager.validate_card_body(body)
    assert is_valid, f"Expected valid with the band section; got errors: {errors}"

    assert sdlc_manager.derive_tier_band("defect") == {"model": "opus", "effort": "high"}
    assert sdlc_manager.derive_tier_band("context-update") == {
        "model": "sonnet",
        "effort": "medium",
    }
    assert sdlc_manager.derive_tier_band("exploration") == {"model": "sonnet", "effort": "low"}
    assert sdlc_manager.derive_tier_band("nonsense-type") is None


def test_tier_band_stamped_on_compiled_body() -> None:
    """AC5: the compile path stamps the band as an auto-populated section, idempotently."""
    body = sdlc_manager._source_to_issue_body(
        "Add a widget", "defect", "campps", "infiquetra/widgets", None, None
    )
    assert "### Recommended Tier Band\nopus/high" in body
    # Idempotent: re-compiling a body that already carries the band does not double-stamp.
    restamped = sdlc_manager._append_tier_band(body, "defect")
    assert restamped.count("### Recommended Tier Band") == 1


def test_tier_band_stamp_not_suppressed_by_mention() -> None:
    """Verifier P1: a prose or code-fence MENTION of the header must not suppress the stamp."""
    prose = (
        "### Objective\nDocument the ### Recommended Tier Band feature.\n\n"
        "### Acceptance criteria\n- [ ] done\n"
    )
    stamped = sdlc_manager._append_tier_band(prose, "defect")
    assert "\n### Recommended Tier Band\nopus/high" in stamped
    fenced = "### Verification\n```\n### Recommended Tier Band\nopus/high\n```\n"
    stamped_fenced = sdlc_manager._append_tier_band(fenced, "defect")
    assert stamped_fenced.rstrip().endswith("### Recommended Tier Band\nopus/high")
    # A REAL existing section still suppresses (idempotence intact).
    real = prose + "\n### Recommended Tier Band\nsonnet/low\n"
    assert sdlc_manager._append_tier_band(real, "defect") == real


def test_tier_band_stamp_after_unclosed_fence_roundtrips() -> None:
    """Verifier P2: an unclosed fence must not swallow the stamped band into code text."""
    body = "### Objective\nfoo\n```\nsome code without closing fence\n"
    stamped = sdlc_manager._append_tier_band(body, "defect")
    # The open fence was closed (render-neutral) before the band was appended...
    assert "```\n\n### Recommended Tier Band\nopus/high" in stamped
    # ...so the stamper's own guard now sees a real section (idempotent on re-stamp).
    assert sdlc_manager._has_tier_band_section(stamped)
    assert sdlc_manager._append_tier_band(stamped, "defect") == stamped
    # ~~~ fences close with the matching flavor.
    tilde = "### Objective\nfoo\n~~~\nunclosed tilde fence\n"
    stamped_tilde = sdlc_manager._append_tier_band(tilde, "defect")
    assert "~~~\n\n### Recommended Tier Band\nopus/high" in stamped_tilde
