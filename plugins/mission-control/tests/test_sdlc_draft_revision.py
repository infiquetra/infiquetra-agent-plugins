"""Tests for prepared issue draft revision, replacement semantics, and multi-fence validation.

Covers #785 / U19:
  1. Revise-twice draft preparation yields a single well-formed document (exactly two '---' fences).
  2. The revision path replaces draft content rather than appending prior content.
  3. Readiness evaluation of a deliberately doubled draft reports a blocking gap naming the multi-fence shape.
  4. Created issue body contains zero '---' front-matter fences and no duplicated section pairs.
  5. Duplicate H3 sections and H2/H3 duplicate section pairs are blocked by readiness.
  6. A body carrying the live leak shape is stripped before it reaches GitHub; mid-body
     contamination is stopped by readiness instead.
"""

# ruff: noqa: E402,I001

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


OLYMPUS_BODY = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] Drafts are written before GitHub mutation; `uv run pytest plugins/mission-control/tests/test_sdlc_draft_revision.py` exits 0

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_sdlc_draft_revision.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_sdlc_draft_revision.py
```

### Context library links
_none_
"""


def test_prepare_revision_twice_yields_single_document(tmp_path: Path) -> None:
    """AC1: Revise-twice yields a single-document draft (grep -c '^---$' == 2)."""
    # 1. Initial draft
    draft1 = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Initial draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    assert draft1.exists()
    assert len(re.findall(r"(?m)^---$", draft1.read_text())) == 2

    # 2. First revision via --from draft1
    source2, artifact2 = sdlc_manager._resolve_prepare_source(
        [], source_file=None, from_ref=str(draft1), root=tmp_path
    )
    draft2 = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=source2,
        title="First revision",
        status=None,
        risk="medium",
        mode=None,
        source_artifact=artifact2,
        draft_dir=tmp_path,
    )
    assert draft2.exists()
    assert draft2 != draft1
    assert len(re.findall(r"(?m)^---$", draft2.read_text())) == 2

    # 3. Second revision via --from draft2
    source3, artifact3 = sdlc_manager._resolve_prepare_source(
        [], source_file=None, from_ref=str(draft2), root=tmp_path
    )
    draft3 = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=source3,
        title="Second revision",
        status=None,
        risk="medium",
        mode=None,
        source_artifact=artifact3,
        draft_dir=tmp_path,
    )
    assert draft3.exists()
    assert draft3 != draft2

    # Assert exactly two '---' fences
    fence_count = len(re.findall(r"(?m)^---$", draft3.read_text()))
    assert fence_count == 2

    # Assert single H1 title and single body
    text3 = draft3.read_text()
    assert text3.count("# Second revision") == 1
    assert "First revision" not in text3
    assert "Initial draft" not in text3

    # Sidecar and readiness pass
    sidecar3 = json.loads(draft3.with_suffix(".json").read_text())
    assert sidecar3["readiness"]["passed"] is True
    assert sidecar3["title"] == "Second revision"


def test_revision_replaces_content_instead_of_appending(tmp_path: Path) -> None:
    """AC2: The revision path is shown to replace draft content rather than append."""
    initial_body = OLYMPUS_BODY.replace(
        "Add a prepared issue workflow.",
        "Initial unique objective alpha.",
    )
    draft1 = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=initial_body,
        title="Replacement test initial",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    assert "Initial unique objective alpha." in draft1.read_text()

    # Revise with modified content
    revised_source = draft1.read_text().replace(
        "Initial unique objective alpha.",
        "Replacement unique objective beta.",
    )
    draft2 = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=revised_source,
        title="Replacement test revised",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    text2 = draft2.read_text()

    # Replaced content is present; prior content is NOT appended
    assert "Replacement unique objective beta." in text2
    assert "Initial unique objective alpha." not in text2
    assert len(re.findall(r"(?m)^---$", text2)) == 2


def test_deliberately_doubled_draft_fails_readiness_with_multi_fence_gap(tmp_path: Path) -> None:
    """AC3: Readiness evaluation of a deliberately doubled draft reports a blocking gap naming multi-fence."""
    doubled_draft_content = """---
title: Initial Specimen
repo: hermes-claude-code-router
type: capability
team: campps
project: campps
status: Idea
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
---

# Initial Specimen

---
title: Doubled Specimen
repo: hermes-claude-code-router
type: capability
team: campps
project: campps
status: Idea
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
---

# Doubled Specimen

### Objective
Some objective.

### Intent
Some intent.

### Acceptance criteria
- [ ] Runnable check `pytest plugins/mission-control/tests/` exits 0

### Out-of-scope / non-goals
None

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_sdlc_draft_revision.py

### Verification
```bash
pytest
```

### Context library links
_none_
"""
    draft_file = tmp_path / "doubled-specimen.md"
    draft_file.write_text(doubled_draft_content, encoding="utf-8")
    sidecar_file = tmp_path / "doubled-specimen.json"
    sidecar_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "ready_to_create",
                "approval_state": "needs_operator_approval",
                "title": "Doubled Specimen",
                "repo": "hermes-claude-code-router",
                "issue_type": "capability",
                "team": "campps",
                "project": "campps",
                "status": "Idea",
                "labels": ["capability", "needs-plan"],
                "risk": "medium",
                "handoff_maturity": "requirements-ready",
                "draft_path": str(draft_file),
                "sidecar_path": str(sidecar_file),
                "readiness": {"passed": True, "blocking_gaps": [], "warnings": []},
            }
        ),
        encoding="utf-8",
    )

    issue = sdlc_manager._read_prepared_issue(draft_file)
    readiness = sdlc_manager._readiness_for_prepared_issue(issue)

    assert readiness.passed is False
    assert any("multi-fence" in gap for gap in readiness.blocking_gaps)

    # Attempting to create this draft refuses before any mutation
    with (
        patch.object(sdlc_manager, "load_config") as mock_config,
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        pytest.raises(RuntimeError, match="blocking readiness"),
    ):
        sdlc_manager.issue_create_prepared(
            draft_file, fmt="text", auto_confirm=True, skip_approval=True
        )

    mock_config.assert_not_called()
    mock_create.assert_not_called()


def test_created_issue_body_contains_zero_fences_and_no_duplicate_sections(tmp_path: Path) -> None:
    """Curation addition: created issue body contains 0 '---' fences and no duplicate sections."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Created body cleanliness test",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    issue = sdlc_manager._read_prepared_issue(draft)
    created_body = sdlc_manager._issue_body_for_github(issue)

    # Zero front-matter fences in the created issue body
    assert re.search(r"(?m)^---$", created_body) is None

    # Zero H1 headers in created body
    assert re.search(r"(?m)^#\s+", created_body) is None

    # No duplicated section headers
    h3_matches = re.findall(r"(?m)^###\s+(.+?)$", created_body)
    assert len(h3_matches) == len(set(h3_matches))
    assert len(h3_matches) >= 5

    # Check mock create receives the clean body
    with (
        patch.object(
            sdlc_manager,
            "load_config",
            return_value={
                "project_mappings": {
                    "projects": {"campps": {"repositories": ["hermes-claude-code-router"]}}
                }
            },
        ),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_gh",
            return_value="https://github.com/infiquetra/hermes-claude-code-router/issues/99",
        ) as mock_gh,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=True),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=True, skip_approval=True
        )

    assert result["created"] is True
    gh_call_args = mock_gh.call_args[0][0]
    body_idx = gh_call_args.index("--body") + 1
    body_passed_to_gh = gh_call_args[body_idx]
    assert re.search(r"(?m)^---$", body_passed_to_gh) is None
    assert "### Objective" in body_passed_to_gh


def test_created_body_strip_cleans_a_contaminated_body() -> None:
    """The #770/#772/#773 leak shape: a body carrying a leading front-matter block.

    `_issue_body_for_github` must publish neither the embedded fences nor the
    embedded H1. Mid-body contamination is out of the stripper's reach by design
    (it strips leading blocks only) and is caught by readiness instead — asserted
    here so the division of labour is pinned rather than assumed.
    """
    leading_contamination = (
        "---\ntitle: Leaked Draft\nrepo: hermes-claude-code-router\n---\n\n"
        "# Leaked Draft\n\n" + OLYMPUS_BODY
    )
    issue = sdlc_manager.PreparedIssue(
        title="Leak shape",
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        status="Idea",
        labels=["capability", "needs-plan"],
        risk="medium",
        mode=None,
        body=leading_contamination,
        handoff_maturity="requirements-ready",
    )
    created_body = sdlc_manager._issue_body_for_github(issue)
    assert re.search(r"(?m)^---$", created_body) is None
    assert "# Leaked Draft" not in created_body
    assert "### Objective" in created_body

    h3_matches = re.findall(r"(?m)^###\s+(.+?)$", created_body)
    assert len(h3_matches) == len(set(h3_matches))

    # Mid-body contamination survives the leading-only strip, so readiness is the
    # gate that stops it reaching GitHub.
    mid_contamination = (
        OLYMPUS_BODY + "\n---\ntitle: Leaked Draft\n---\n\n# Leaked Draft\n\n### Objective\nDup.\n"
    )
    mid_issue = sdlc_manager.PreparedIssue(
        title="Mid leak shape",
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        status="Idea",
        labels=["capability", "needs-plan"],
        risk="medium",
        mode=None,
        body=mid_contamination,
        handoff_maturity="requirements-ready",
    )
    assert re.search(r"(?m)^---$", sdlc_manager._issue_body_for_github(mid_issue)) is not None
    mid_readiness = sdlc_manager._readiness_for_prepared_issue(mid_issue)
    assert mid_readiness.passed is False
    assert any("multi-fence" in gap for gap in mid_readiness.blocking_gaps)


def test_readiness_blocks_duplicate_h3_and_h2_h3_section_pairs(tmp_path: Path) -> None:
    """Readiness blocks duplicate H3 sections and duplicate H2/H3 section pairs."""
    # 1. Duplicate H3 sections
    dup_h3_body = OLYMPUS_BODY + "\n\n### Objective\nDuplicated objective text.\n"
    issue_dup_h3 = sdlc_manager.PreparedIssue(
        title="Duplicate H3",
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        status="Idea",
        labels=["capability", "needs-plan"],
        risk="medium",
        mode=None,
        body=dup_h3_body,
        handoff_maturity="requirements-ready",
    )
    readiness_dup_h3 = sdlc_manager._readiness_for_prepared_issue(issue_dup_h3)
    assert readiness_dup_h3.passed is False
    assert any("Duplicate H3 sections" in gap for gap in readiness_dup_h3.blocking_gaps)

    # 2. Duplicate H2/H3 section pairs
    dup_h2_h3_body = "## Objective\nH2 objective text.\n\n" + OLYMPUS_BODY
    issue_dup_h2_h3 = sdlc_manager.PreparedIssue(
        title="Duplicate H2/H3",
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        status="Idea",
        labels=["capability", "needs-plan"],
        risk="medium",
        mode=None,
        body=dup_h2_h3_body,
        handoff_maturity="requirements-ready",
    )
    readiness_dup_h2_h3 = sdlc_manager._readiness_for_prepared_issue(issue_dup_h2_h3)
    assert readiness_dup_h2_h3.passed is False
    assert any("Duplicated section pairs" in gap for gap in readiness_dup_h2_h3.blocking_gaps)
