"""Prose mention extraction keeps identifiers and drops ordinary English (issue 261)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "reviews" / "scripts"

REMOVED_SENTENCE = "The skip button is the way to leave."
ADDED_SENTENCE = "A different sentence remains here."
REMOVED_SPANS = "See `review-setup` and `check_plan.py` before you skip the step."
ADDED_SPANS = "See the updated notes before you leave the step."


def _load(name: str):
    key = f"infiquetra_reviews.{name}"
    spec = importlib.util.spec_from_file_location(key, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


review_checks = _load("review_checks")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _commit_pair(tmp: Path, base_files: dict[str, str], head_files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-checks@example.com")
    _git(repo, "config", "user.name", "review-checks")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo, base_files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _write(repo, head_files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    return repo, base


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_markdown_sentence_edits_report_no_plain_english_words(tmp_path: Path) -> None:
    """Removing ordinary words from Markdown, reStructuredText, and text reports nothing."""
    removed = [REMOVED_SENTENCE]
    added = [ADDED_SENTENCE]
    for path in ("notes.md", "notes.rst", "notes.txt"):
        assert review_checks._text_names(removed, added, path) == []
    assert "skip" in review_checks._text_names(removed, added, "notes.py")

    prose = REMOVED_SENTENCE + "\n"
    edited = ADDED_SENTENCE + "\n"
    repo, base = _commit_pair(
        tmp_path,
        {
            "notes.md": prose,
            "notes.rst": prose,
            "notes.txt": prose,
            "caller.py": "the skip button is still described here\n",
        },
        {
            "notes.md": edited,
            "notes.rst": edited,
            "notes.txt": edited,
            "caller.py": "the skip button is still described here\n",
        },
    )
    assert review_checks.changed_names(repo, base)["hits"] == []


def test_markdown_removed_code_span_identifier_still_reports_mentions(tmp_path: Path) -> None:
    """A backticked ``review-setup`` or ``check_plan.py`` removed from Markdown is still a name."""
    names = review_checks._text_names([REMOVED_SPANS], [ADDED_SPANS], "notes.md")
    assert "review-setup" in names
    assert "check_plan.py" in names
    assert "skip" not in names
    assert "the" not in names
    assert "before" not in names

    repo, base = _commit_pair(
        tmp_path,
        {
            "notes.md": REMOVED_SPANS + "\n",
            "caller.py": "invoke review-setup and check_plan.py\n",
        },
        {
            "notes.md": ADDED_SPANS + "\n",
            "caller.py": "invoke review-setup and check_plan.py\n",
        },
    )
    hits = review_checks.changed_names(repo, base)["hits"]
    assert {hit["rule_id"] for hit in hits} == {"review-setup", "check_plan.py"}
    assert {hit["path"] for hit in hits} == {"caller.py"}
