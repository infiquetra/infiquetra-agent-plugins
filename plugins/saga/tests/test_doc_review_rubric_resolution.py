"""The rubric command resolves from any working directory and fails loud when a rubric is gone.

Issue 1026 unit U5, card 932. The central case runs the invocation the skill prints **from a
directory other than the repository root**: a test that only ever runs from the root cannot catch
the defect it is written for, because the defect is that the path was relative to the caller.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
DOC_REVIEW_SKILL = SAGA / "skills" / "doc-review" / "SKILL.md"
ENGINE = SAGA / "scripts" / "lifecycle_review.py"
ISSUE_PROGRESS = SAGA / "scripts" / "issue_progress.py"


def _skill_invocations() -> list[str]:
    """Every ``lifecycle_review.py`` command line the skill tells the reader to run."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    return re.findall(r"python3 (\S*lifecycle_review\.py[^`\n]*)", text)


def test_the_skill_invokes_the_engine_by_a_repository_root_relative_path() -> None:
    """No invocation may start with ``../``: that form resolves only from the skill's own
    directory, which is the one place a reviewer never runs."""
    invocations = _skill_invocations()
    assert invocations, "scan drifted: the skill prints no lifecycle_review.py invocation"
    for command in invocations:
        assert not command.startswith(".."), (
            f"caller-relative invocation {command!r}: from any directory but "
            "plugins/saga/skills/doc-review/ python cannot find the script"
        )
        assert command.startswith("plugins/saga/scripts/lifecycle_review.py"), command


def test_the_invocation_the_skill_prints_resolves_from_a_non_root_directory(
    tmp_path: Path,
) -> None:
    """The proof at the real boundary: run the printed command with the repository as an
    argument-free relative path from somewhere else entirely.

    A symlinked ``plugins`` tree keeps the shipped repo-relative path intact without writing
    anything into the checkout.
    """
    (tmp_path / "plugins").symlink_to(ROOT / "plugins", target_is_directory=True)
    command = _skill_invocations()[0]
    argv = command.replace("<idea|issue>", "issue").split()
    result = subprocess.run([sys.executable, *argv], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "acceptance_criteria_clarity" in result.stdout


def test_a_rubric_that_cannot_be_loaded_stops_the_review() -> None:
    """The skill must instruct a stop, not a degraded pass. The defect this guards was an
    instruction the skill gave itself, so the fix is the sentence, not only the path."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "**A rubric that cannot be loaded stops the review.**" in text
    assert "continue with the\nreadiness review where safe" not in text
    assert "continue with the readiness review where safe" not in text


def test_no_weaker_rubric_is_substituted_for_a_missing_one() -> None:
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "do not\ncontinue on the readiness pass\nalone" in text or (
        "do not continue on the readiness pass" in " ".join(text.split())
    )
    assert "substitute a different or weaker rubric" in " ".join(text.split())


def _engine_with_no_rubrics(tmp_path: Path) -> Path:
    fake_plugin = tmp_path / "saga"
    (fake_plugin / "scripts").mkdir(parents=True)
    shutil.copy(ENGINE, fake_plugin / "scripts" / "lifecycle_review.py")
    # references/rubrics/ deliberately absent: a broken install, not an empty phase.
    return fake_plugin / "scripts" / "lifecycle_review.py"


def test_every_rubric_subcommand_fails_loud_when_the_library_is_missing(tmp_path: Path) -> None:
    """At the boundary: with the rubric library absent, each subcommand exits non-zero with a
    message naming the missing library.

    ``list-cores`` and ``list-extras`` used to exit 0 printing nothing, which a reviewer reads
    as "no rubrics apply" -- the silent degradation card 932 is about, one layer below the
    skill sentence that described it.
    """
    engine = _engine_with_no_rubrics(tmp_path)
    invocations = (
        ["rubrics", "list-cores", "--phase", "issue"],
        ["rubrics", "list-extras", "--phase", "issue"],
        ["rubrics", "read", "--phase", "issue", "--slug", "acceptance_criteria_clarity"],
    )
    for argv in invocations:
        result = subprocess.run(
            [sys.executable, str(engine), *argv], cwd=tmp_path, capture_output=True, text=True
        )
        assert result.returncode != 0, (
            f"{' '.join(argv)} returned success with no rubric library: stdout={result.stdout!r}"
        )
        assert "ERROR" in result.stderr, f"{' '.join(argv)} failed without saying why"
        assert not result.stdout.strip(), (
            f"{' '.join(argv)} printed a result as well as failing, which a caller may consume"
        )


def test_the_listings_still_work_against_the_real_library() -> None:
    """The loud failure must not fire on a healthy install."""
    result = subprocess.run(
        [sys.executable, str(ENGINE), "rubrics", "list-cores", "--phase", "issue"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "acceptance_criteria_clarity" in result.stdout


def test_the_condition_is_read_before_the_selection_is_made() -> None:
    """Card 932: the extras instructions presented selection before the rule that governs it."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8")
    read_step = text.index("2. Read each listed rubric's content")
    select_step = text.index("3. Apply every `core` rubric for the phase")
    assert read_step < select_step
    assert "Read each rubric's applicability condition\nbefore deciding whether it applies" in text


def test_no_durable_lens_record_or_census_was_added() -> None:
    """Card 932's settled decision D-D4 defers both; lens selection stays adaptive."""
    text = DOC_REVIEW_SKILL.read_text(encoding="utf-8").lower()
    for forbidden in ("lens census", "applied-or-skipped lens record", "lens registry"):
        assert forbidden not in text


def test_doc_review_fixes_is_defined_forwarded_and_reaches_the_comment() -> None:
    """The parameter existed and the flag did not, so the CLI could never populate it."""
    source = ISSUE_PROGRESS.read_text(encoding="utf-8")
    assert '"--doc-review-fixes"' in source
    assert "doc_review_fixes=_split_pipe(args.doc_review_fixes)" in source

    result = subprocess.run(
        [
            sys.executable,
            str(ISSUE_PROGRESS),
            "--event",
            "phase",
            "--issue-ref",
            "owner/repo#1",
            "--destination",
            "pr",
            "--doc-review-fixes",
            "corrected the origin mapping|filled the missing gate",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "doc review fixes" in result.stdout
    assert "corrected the origin mapping" in result.stdout
    assert "filled the missing gate" in result.stdout


def test_the_work_skill_forwards_the_flag_it_now_has() -> None:
    work = (SAGA / "skills" / "work" / "SKILL.md").read_text(encoding="utf-8")
    assert "--doc-review-fixes" in work
