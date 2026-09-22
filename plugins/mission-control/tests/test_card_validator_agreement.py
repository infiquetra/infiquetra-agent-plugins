"""Verdict agreement tests between mission-control and home-lab card validators (#830).

This module dynamically loads the authoritative home-lab card validator
(`home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py`) at test time
and asserts that `sdlc_manager.validate_card_body` (and `validate_card_body_for_context`)
returns the identical valid/invalid verdict across a comprehensive test corpus.

Operator ruling (C1, 2026-08-26):
  This is a local-only agreement guard. Drift between the two implementations is
  caught locally when the home-lab authority checkout is present -- NOT by this
  repository's CI. CI workflows in this repository do not check out the home-lab
  repository, and no second copy of the validator is vendored. When the authority
  checkout is absent, tests in this module skip loudly naming the expected path.

Known divergence on unclosed Verification fences:
  `sdlc_manager.validate_card_body` requires >=2 ``` markers (opening and closing
  fence), whereas home-lab `card_validator.py` checks `_CODE_BLOCK_RE.search(verification)`
  with pattern `^````, which accepts a single opening ``` with no closing fence.
  This known split is explicitly tracked by `test_verdict_agreement_unclosed_verification_code_block`
  (marked xfail) so a passing run is not misinterpreted as proof that fence-closing semantics match.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest


def _find_package_root(start: Path | None = None) -> Path:
    """Discover the mission-control package root containing .claude-plugin/plugin.json."""
    current = start or Path(__file__)
    for parent in current.resolve().parents:
        if (parent / ".claude-plugin" / "plugin.json").is_file():
            return parent
    raise RuntimeError(
        f"package root containing .claude-plugin/plugin.json not found from {current.resolve()}"
    )


PACKAGE_ROOT = _find_package_root()
SCRIPTS_DIR = PACKAGE_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sdlc_manager  # noqa: E402

EXPECTED_AUTHORITY_REL = Path("ansible/roles/hermes_orchestrator/files/card_validator.py")


def _find_home_lab_card_validator() -> tuple[Path | None, Path]:
    """Locate home-lab card_validator.py authority checkout or return default expected path."""
    env_path = os.environ.get("HOME_LAB_PATH") or os.environ.get("INFIQUETRA_HOME_LAB_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path) / EXPECTED_AUTHORITY_REL)

    workspace_dirs = [
        Path.home() / "workspace" / "infiquetra" / "home-lab",
        Path.home() / "workspace" / "home-lab",
    ]

    try:
        repo_root = PACKAGE_ROOT.parent.parent
        workspace_dirs.append(repo_root.parent / "home-lab")
        workspace_dirs.append(repo_root.parent / "infiquetra" / "home-lab")
    except Exception:
        pass

    for wd in workspace_dirs:
        candidates.append(wd / EXPECTED_AUTHORITY_REL)

    for candidate in candidates:
        if candidate.is_file():
            return candidate, candidate

    default_expected = (
        candidates[0]
        if candidates
        else Path.home() / "workspace" / "infiquetra" / "home-lab" / EXPECTED_AUTHORITY_REL
    )
    return None, default_expected


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


def _require_authority(override_path: Path | None = None) -> Any:
    """Load authority or skip loudly with expected path and C1 local-only ruling."""
    if override_path is not None:
        if not override_path.is_file():
            pytest.skip(
                f"Home-lab card_validator authority not found at expected path '{override_path}'. "
                "Drift between validate_card_body and the home-lab authority is caught locally "
                "when the home-lab checkout is present, not by this repository's CI (C1 ruling)."
            )
        return _load_home_lab_authority(override_path)

    found, expected = _find_home_lab_card_validator()
    if found is None:
        pytest.skip(
            f"Home-lab card_validator authority not found at expected path '{expected}'. "
            "Drift between validate_card_body and the home-lab authority is caught locally "
            "when the home-lab checkout is present, not by this repository's CI (C1 ruling)."
        )
    return _load_home_lab_authority(found)


# #1000 U2 dated divergence: mission-control's validate_card_body (the vendored
# shim) requires the common `### Risk` header, while the home-lab authority
# validator is still pre-Risk and keys risk off `risk:` labels. The canonical
# corpus therefore carries a valid Risk section -- an extra header passes BOTH
# validators, so the corpus stays agreed -- but "Risk" must NOT be added to the
# missing-headers corpus below, which asserts both validators FAIL on it.
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

### Risk
medium
The change is confined to the card validator gate.

### Notes / conventions
- GitHub issue forms render fields as `### <Field Label>` headers

### Context library links
- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md
"""


def _eval_authority(
    authority: Any, body: str, labels: list[str] | None = None
) -> tuple[bool, list[str]]:
    """Evaluate card body using home-lab authority validator."""
    lbls = labels if labels is not None else ["capability"]
    issue = {"body": body, "user": {"login": "jefcox"}}
    config = type("Config", (), {"authorized_authors": ["jefcox", "test-user"]})()
    res = authority.validate_card(issue, lbls, config)
    return res.passed, res.failures


def _eval_portable(body: str) -> tuple[bool, list[str]]:
    """Evaluate card body using mission-control validate_card_body."""
    valid, errors = sdlc_manager.validate_card_body(body)
    return valid, errors


def _eval_portable_context(body: str, issue_type: str, risk: str | None) -> tuple[bool, list[str]]:
    """Evaluate card body using mission-control validate_card_body_for_context."""
    valid, errors = sdlc_manager.validate_card_body_for_context(body, issue_type, risk)
    return valid, errors


def _assert_verdict_agreement(
    auth_passed: bool,
    port_passed: bool,
    case_name: str,
    auth_errors: list[str] | None = None,
    port_errors: list[str] | None = None,
) -> None:
    """Assert agreement on verdict only, naming case and both verdicts on disagreement."""
    assert auth_passed == port_passed, (
        f"Verdict disagreement on case '{case_name}': "
        f"authority passed={auth_passed} (errors={auth_errors}), "
        f"portable passed={port_passed} (errors={port_errors})"
    )


# ─── 1. Absent Authority Skip Contract ─────────────────────────────────────────


def test_absent_authority_skips_loudly_with_expected_path() -> None:
    """When authority checkout is absent, skip loudly naming path and C1 ruling."""
    nonexistent = Path("/nonexistent/workspace/infiquetra/home-lab/ansible/roles/card_validator.py")
    with pytest.raises(pytest.skip.Exception) as exc_info:
        _require_authority(override_path=nonexistent)
    msg = str(exc_info.value)
    assert str(nonexistent) in msg
    assert "locally" in msg
    assert "CI" in msg
    assert "C1" in msg


# ─── 2. Mutation Proof ────────────────────────────────────────────────────────


def test_mutation_proves_verdict_disagreement_fails() -> None:
    """Asserting verdict agreement on mismatched verdicts fails naming case and verdicts."""
    with pytest.raises(AssertionError) as exc_info:
        _assert_verdict_agreement(
            auth_passed=True,
            port_passed=False,
            case_name="mutation-mismatch-proof",
            auth_errors=[],
            port_errors=["'Objective' is empty"],
        )
    msg = str(exc_info.value)
    assert "mutation-mismatch-proof" in msg
    assert "authority passed=True" in msg
    assert "portable passed=False" in msg


# ─── 3. Valid Variants Corpus ──────────────────────────────────────────────────


def test_verdict_agreement_canonical_card_passes() -> None:
    """Canonical valid issue body passes both validators."""
    auth = _require_authority()
    auth_passed, auth_fails = _eval_authority(auth, VALID_CARD_CANONICAL)
    port_passed, port_errs = _eval_portable(VALID_CARD_CANONICAL)
    _assert_verdict_agreement(
        auth_passed, port_passed, "canonical-valid-card", auth_fails, port_errs
    )
    assert auth_passed is True
    assert port_passed is True


def test_verdict_agreement_reordered_h3_headers() -> None:
    """Reordered H3 sections must be accepted by both implementations."""
    auth = _require_authority()
    reordered = """### Verification
```bash
pytest -v
```

### Risk
medium
The change is confined to the card validator gate.

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
    auth_passed, auth_fails = _eval_authority(auth, reordered)
    port_passed, port_errs = _eval_portable(reordered)
    _assert_verdict_agreement(
        auth_passed, port_passed, "reordered-h3-headers", auth_fails, port_errs
    )
    assert auth_passed is True


def test_verdict_agreement_without_optional_notes() -> None:
    """Omitting optional Notes / conventions section passes both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace(
        "### Notes / conventions\n- GitHub issue forms render fields as `### <Field Label>` headers\n\n",
        "",
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "without-optional-notes", auth_fails, port_errs
    )
    assert auth_passed is True


def test_verdict_agreement_with_extra_unrecognized_headers() -> None:
    """Extra custom headers added by authors pass both validators."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL + "\n\n### Extra Context Section\nSome arbitrary author notes.\n"
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "extra-unrecognized-headers", auth_fails, port_errs
    )
    assert auth_passed is True


def test_verdict_agreement_context_library_none_markers() -> None:
    """Explicit none markers (_none_, none, None, _NONE_) pass both."""
    auth = _require_authority()
    for marker in ("_none_", "none", "None", "_NONE_"):
        body = re.sub(
            r"### Context library links\n.*",
            f"### Context library links\n{marker}\n",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"context-marker-{marker}", auth_fails, port_errs
        )
        assert auth_passed is True


def test_verdict_agreement_context_library_populated_links() -> None:
    """Populated single and multiple typed context links pass both."""
    auth = _require_authority()
    variants = [
        "- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md",
        "- architecture_decisions: https://github.com/infiquetra/blueprint/adr/042.md, "
        "https://github.com/infiquetra/blueprint/adr/043.md",
        "- system_architecture: https://github.com/infiquetra/docs/arch.md\n"
        "- security_baseline: https://github.com/infiquetra/docs/sec.md",
    ]
    for idx, ctx in enumerate(variants):
        body = re.sub(
            r"### Context library links\n.*",
            f"### Context library links\n{ctx}\n",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"context-links-variant-{idx}", auth_fails, port_errs
        )
        assert auth_passed is True


def test_verdict_agreement_acceptance_criteria_formats() -> None:
    """Various checklist markers and executable runnable checks pass both."""
    auth = _require_authority()
    ac_variants = [
        "- [ ] `pytest tests/test_card_validator.py` exits 0\n* [X] `git diff --check` clean",
        "- [x] `python3 scripts/check_repo.py` passes\n- [ ] `make test` runs",
        "- [ ] Verifying suite:\n```\npytest -q\n```\n- [ ] Clean output",
        "* [ ] `ruff check .` clean",
    ]
    for idx, ac in enumerate(ac_variants):
        body = re.sub(
            r"### Acceptance criteria\n.*?\n\n###",
            f"### Acceptance criteria\n{ac}\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"ac-variant-{idx}", auth_fails, port_errs
        )
        assert auth_passed is True


def test_verdict_agreement_files_expected_formats() -> None:
    """Plausible path formats pass both validators."""
    auth = _require_authority()
    file_variants = [
        "path/to/file.py",
        "ansible/roles/hermes_orchestrator/files/card_validator.py\nansible/roles/handlers.py",
        "- plugins/mission-control/scripts/sdlc_manager.py\n- tests/test_card_validator.py",
        "config.json",
        "card_validator.py",
    ]
    for idx, fv in enumerate(file_variants):
        body = re.sub(
            r"### Files expected to change\n.*?\n\n###",
            f"### Files expected to change\n{fv}\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"files-variant-{idx}", auth_fails, port_errs
        )
        assert auth_passed is True


def test_verdict_agreement_trailing_header_whitespace() -> None:
    """Trailing whitespace on H3 headers passes both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace("### Objective\n", "### Objective   \n")
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "trailing-header-whitespace", auth_fails, port_errs
    )
    assert auth_passed is True


# ─── 4. Missing and Reordered Headers Corpus ───────────────────────────────────


def test_verdict_agreement_missing_required_headers() -> None:
    """Missing each required H3 section individually fails both validators."""
    auth = _require_authority()
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
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"missing-header-{header}", auth_fails, port_errs
        )
        assert auth_passed is False
        assert port_passed is False


def test_verdict_agreement_h2_headers_rejected() -> None:
    """H2 header replacing required H3 header is rejected by both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace("### Objective", "## Objective")
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(auth_passed, port_passed, "h2-header-rejected", auth_fails, port_errs)
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_misspelled_header_rejected() -> None:
    """Misspelled header 'Out-of-scope or non-goals' is rejected by both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace(
        "### Out-of-scope / non-goals", "### Out-of-scope or non-goals"
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "misspelled-header-rejected", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


# ─── 5. Empty / Placeholder Sections Corpus ────────────────────────────────────


def test_verdict_agreement_empty_body_rejected() -> None:
    """Empty string body is rejected by both."""
    auth = _require_authority()
    auth_passed, auth_fails = _eval_authority(auth, "")
    port_passed, port_errs = _eval_portable("")
    _assert_verdict_agreement(auth_passed, port_passed, "empty-body", auth_fails, port_errs)
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_empty_section_rejected() -> None:
    """Empty required section is rejected by both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace(
        "### Intent\nCold agents waste planner rounds on malformed cards; gate at ingest so a card\n"
        "either carries the contract or never reaches the planner.\n",
        "### Intent\n\n",
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "empty-intent-section", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_whitespace_only_section_rejected() -> None:
    """Whitespace-only required section is rejected by both."""
    auth = _require_authority()
    body = VALID_CARD_CANONICAL.replace(
        "### Intent\nCold agents waste planner rounds on malformed cards; gate at ingest so a card\n"
        "either carries the contract or never reaches the planner.\n",
        "### Intent\n   \n\t  \n",
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "whitespace-only-intent-section", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_placeholder_seeds_rejected() -> None:
    """Placeholder text seeds in required sections are rejected by both."""
    auth = _require_authority()
    placeholders = [
        "_No response_",
        "<!-- placeholder -->",
        "- [ ]",
        "-",
        "* [ ]",
        "*",
        "None",
    ]
    for ph in placeholders:
        body = re.sub(
            r"### Objective\n.*?\n\n###",
            f"### Objective\n{ph}\n\n###",
            VALID_CARD_CANONICAL,
            flags=re.DOTALL,
        )
        auth_passed, auth_fails = _eval_authority(auth, body)
        port_passed, port_errs = _eval_portable(body)
        _assert_verdict_agreement(
            auth_passed, port_passed, f"placeholder-objective-{ph}", auth_fails, port_errs
        )
        assert auth_passed is False
        assert port_passed is False


# ─── 6. Semantic Violations Corpus ────────────────────────────────────────────


def test_verdict_agreement_ac_missing_checklist() -> None:
    """Acceptance criteria with prose only (no `- [ ]` checklist) fails both."""
    auth = _require_authority()
    body = re.sub(
        r"### Acceptance criteria\n.*?\n\n###",
        "### Acceptance criteria\nWe will test everything thoroughly.\n\n###",
        VALID_CARD_CANONICAL,
        flags=re.DOTALL,
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "ac-missing-checklist", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_ac_non_executable() -> None:
    """Acceptance criteria with checklist but no runnable code span/block fails both."""
    auth = _require_authority()
    body = re.sub(
        r"### Acceptance criteria\n.*?\n\n###",
        "### Acceptance criteria\n- [ ] The feature works\n- [ ] Tests pass\n\n###",
        VALID_CARD_CANONICAL,
        flags=re.DOTALL,
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(auth_passed, port_passed, "ac-non-executable", auth_fails, port_errs)
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_files_expected_no_path() -> None:
    """Files expected without path separator `/` or file extension fails both."""
    auth = _require_authority()
    body = re.sub(
        r"### Files expected to change\n.*?\n\n###",
        "### Files expected to change\nVarious modules across the codebase\n\n###",
        VALID_CARD_CANONICAL,
        flags=re.DOTALL,
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "files-expected-no-path", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_verification_no_code_block() -> None:
    """Verification without fenced code block fails both while keeping remaining sections."""
    auth = _require_authority()
    body = re.sub(
        r"### Verification\n.*?\n\n###",
        "### Verification\nRun pytest in the main directory\n\n###",
        VALID_CARD_CANONICAL,
        flags=re.DOTALL,
    )
    auth_passed, auth_fails = _eval_authority(auth, body)
    port_passed, port_errs = _eval_portable(body)
    _assert_verdict_agreement(
        auth_passed, port_passed, "verification-no-code-block", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


@pytest.mark.xfail(
    reason=(
        "Known fence-count divergence: sdlc_manager.validate_card_body requires >=2 ``` markers "
        "(open+close), while home-lab card_validator accepts a single opening ``` marker (^``` search)."
    ),
    strict=True,
)
def test_verdict_agreement_unclosed_verification_code_block() -> None:
    """Known divergence: unclosed code block (single opening ```) passes home-lab but fails portable."""
    auth = _require_authority()
    unclosed_body = re.sub(
        r"### Verification\n.*?\n\n###",
        "### Verification\n```bash\npytest -v\n\n###",
        VALID_CARD_CANONICAL,
        flags=re.DOTALL,
    )
    auth_passed, auth_fails = _eval_authority(auth, unclosed_body)
    port_passed, port_errs = _eval_portable(unclosed_body)
    _assert_verdict_agreement(
        auth_passed,
        port_passed,
        "unclosed-verification-code-block",
        auth_fails,
        port_errs,
    )


# ─── 7. Risk-Tier Context Variants Corpus ─────────────────────────────────────


def test_verdict_agreement_low_risk_context_aware() -> None:
    """Low risk card passes without high-blast sections in both."""
    auth = _require_authority()
    auth_passed, auth_fails = _eval_authority(
        auth, VALID_CARD_CANONICAL, ["capability", "risk:low"]
    )
    port_passed, port_errs = _eval_portable_context(VALID_CARD_CANONICAL, "capability", "low")
    _assert_verdict_agreement(
        auth_passed, port_passed, "low-risk-context-aware", auth_fails, port_errs
    )
    assert auth_passed is True
    assert port_passed is True


def test_verdict_agreement_high_risk_missing_sections() -> None:
    """High risk card missing high-blast sections is rejected by both."""
    auth = _require_authority()
    auth_passed, auth_fails = _eval_authority(
        auth, VALID_CARD_CANONICAL, ["capability", "risk:high"]
    )
    port_passed, port_errs = _eval_portable_context(VALID_CARD_CANONICAL, "capability", "high")
    _assert_verdict_agreement(
        auth_passed, port_passed, "high-risk-missing-sections", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False


def test_verdict_agreement_high_risk_populated_passes() -> None:
    """High risk card with Inputs, Failure modes, and Stop conditions passes both."""
    auth = _require_authority()
    high_body = (
        VALID_CARD_CANONICAL
        + """

### Inputs inventory
- config/sdlc-schema.json
- home-lab inventory

### Failure modes / pre-mortem
- network partition at ingest
- stale schema

### Stop conditions
- unrecoverable data loss detected
"""
    )
    auth_passed, auth_fails = _eval_authority(auth, high_body, ["capability", "risk:high"])
    port_passed, port_errs = _eval_portable_context(high_body, "capability", "high")
    _assert_verdict_agreement(
        auth_passed, port_passed, "high-risk-populated-passes", auth_fails, port_errs
    )
    assert auth_passed is True
    assert port_passed is True


def test_verdict_agreement_high_risk_placeholder_sections_rejected() -> None:
    """High risk card with placeholder in high-blast sections is rejected by both."""
    auth = _require_authority()
    high_body = (
        VALID_CARD_CANONICAL
        + """

### Inputs inventory
_No response_

### Failure modes / pre-mortem
_No response_

### Stop conditions
_No response_
"""
    )
    auth_passed, auth_fails = _eval_authority(auth, high_body, ["capability", "risk:high"])
    port_passed, port_errs = _eval_portable_context(high_body, "capability", "high")
    _assert_verdict_agreement(
        auth_passed, port_passed, "high-risk-placeholder-rejected", auth_fails, port_errs
    )
    assert auth_passed is False
    assert port_passed is False
