"""Tests for prepared-issue source artifact resolution."""

# ruff: noqa: E402,I001

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


def _write(root: Path, rel_path: str, text: str) -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_from_local_brainstorm_infers_requirements_maturity(tmp_path) -> None:
    _write(
        tmp_path,
        "docs/brainstorms/example.md",
        "# Example Brainstorm\n\nRequirements and constraints.",
    )

    artifact = sdlc_manager.resolve_source_artifact("docs/brainstorms/example.md", tmp_path)

    assert artifact.kind == "brainstorm"
    assert artifact.title == "Example Brainstorm"
    assert artifact.inferred_maturity == "requirements-ready"
    assert artifact.path == "docs/brainstorms/example.md"


def test_natural_language_brainstorm_hint_resolves_single_match(tmp_path) -> None:
    _write(tmp_path, "docs/brainstorms/feature.md", "# Feature\n\nDo the thing.")

    source, artifact = sdlc_manager._resolve_prepare_source(
        ["handoff", "from", "the", "brainstorm"],
        source_file=None,
        from_ref=None,
        root=tmp_path,
    )

    assert artifact is not None
    assert artifact.ref == "docs/brainstorms/feature.md"
    assert artifact.inferred_maturity == "requirements-ready"
    assert "Do the thing" in source


def test_natural_language_plan_hint_reports_ambiguous_matches(tmp_path) -> None:
    _write(tmp_path, "docs/plans/a.md", "# Plan A\n")
    _write(tmp_path, "docs/plans/b.md", "# Plan B\n")

    with pytest.raises(RuntimeError, match="Ambiguous source artifact hint"):
        sdlc_manager.resolve_source_artifact("handoff the plan", tmp_path)


def test_github_issue_url_fetches_title_body_and_url() -> None:
    payload = {
        "title": "Issue handoff",
        "body": "Issue body",
        "url": "https://github.com/infiquetra/home-lab/issues/42",
    }

    with patch.object(sdlc_manager, "_gh", return_value=json.dumps(payload)) as mock_gh:
        artifact = sdlc_manager.resolve_source_artifact(
            "https://github.com/infiquetra/home-lab/issues/42"
        )

    mock_gh.assert_called_once_with(
        [
            "issue",
            "view",
            "42",
            "--repo",
            "infiquetra/home-lab",
            "--json",
            "title,body,url",
        ]
    )
    assert artifact.kind == "github-issue"
    assert artifact.title == "Issue handoff"
    assert artifact.inferred_maturity == "requirements-ready"
    assert "Issue body" in artifact.content


def test_branch_source_captures_resume_context(tmp_path) -> None:
    def fake_git(args: list[str], cwd: Path) -> str:
        assert cwd == tmp_path
        if args[:2] == ["git", "rev-parse"] and args[-1] == "feature/test":
            return "abc123"
        if args[:3] == ["git", "rev-parse", "--abbrev-ref"]:
            return "origin/feature/test"
        if args[:2] == ["git", "status"]:
            return "## feature/test"
        raise AssertionError(args)

    with patch.object(sdlc_manager, "_run_git_command", side_effect=fake_git):
        artifact = sdlc_manager.resolve_source_artifact("branch:feature/test", tmp_path)

    assert artifact.kind == "branch"
    assert artifact.branch == "feature/test"
    assert artifact.inferred_maturity == "resume-ready"
    assert "abc123" in artifact.content


def test_missing_source_reports_searched_locations(tmp_path) -> None:
    with pytest.raises(RuntimeError, match="Searched: docs/brainstorms"):
        sdlc_manager.resolve_source_artifact("from the brainstorm", tmp_path)
