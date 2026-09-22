"""Publication: exactly one comment, bound to the reviewed revision (child 935).

The rule this file guards is narrow and absolute: a review publishes **one
pull-request comment** and **no pull-request review of any kind**. An approving
review would carry an outcome forward onto commits the review never read, which is
child 937's finding; a review that moved the branch would break the caller's
freshness check, which is child 935's.

Nothing here reaches the network. The `gh` runner is injected and its argument
vectors are asserted, so a test fails on what would have been sent rather than on
what came back.
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess  # nosec B404 — only for its CompletedProcess type in a fake
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

REVISION = "0123456789abcdef0123456789abcdef01234567"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rr() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("review_result_for_publish", SCRIPTS / "review_result.py")


class _Runner:
    """A `gh` stand-in that records every argument vector it was handed."""

    def __init__(self, returncode: int = 0, stdout: str = "https://example/comment/1") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv: list[str], **_kwargs: Any) -> Any:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def _result(rr: ModuleType, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "revision": REVISION,
        "roster_hash": "sha256:test-roster",
        "outcome": "repairs_requested",
        "cycle": 1,
        "loop": rr.LOOP_CODE_REVIEW,
        "unit": "issue-1001",
    }
    fields.update(overrides)
    result = rr.ReviewResult(**fields)
    result.lens_results = [
        rr.LensResult(
            lens="correctness",
            strictness="standard",
            scorable=True,
            dimension_scores={"a": 9, "b": 8},
            threshold={"derived_overall_minimum": 9.0, "applicable_dimension_minimum": 7},
        )
    ]
    return result


# ---------------------------------------------------------------------------
# One comment, no review
# ---------------------------------------------------------------------------


def test_publication_issues_exactly_one_comment_and_zero_reviews(rr: ModuleType) -> None:
    runner = _Runner()

    outcome = rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)

    assert len(runner.calls) == 1
    assert runner.calls[0][:3] == ["gh", "pr", "comment"]
    assert outcome["comments"] == 1
    assert outcome["reviews"] == 0


def test_no_argument_vector_ever_submits_a_pull_request_review(rr: ModuleType) -> None:
    """The absolute rule, asserted against what would have been sent.

    `gh pr review` in any of its forms — approve, request-changes, comment — would
    attach an outcome to the pull request that a later commit inherits. Nothing
    here may produce one.
    """
    runner = _Runner()

    rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)

    for argv in runner.calls:
        assert "review" not in argv, f"an argument vector submits a review: {argv}"
        assert argv[:3] != ["gh", "pr", "review"]
        for flag in ("--approve", "--request-changes"):
            assert flag not in argv


def test_the_module_contains_no_pull_request_review_call_at_all(rr: ModuleType) -> None:
    """A mutation proof: re-adding the call must fail this test.

    The docstrings NAME the forbidden call, to say why it is forbidden. A blanket
    string search would therefore forbid the explanation, so this walks the parsed
    module and asserts no live string outside a docstring builds that command —
    which is the property that actually matters.
    """
    source = (SCRIPTS / "review_result.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))

    live_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ]
    assert "review" not in live_strings, (
        "a live string literal 'review' could be assembled into a `gh pr review` argument vector"
    )
    for text in live_strings:
        assert "pr review" not in text


# ---------------------------------------------------------------------------
# Bound to the reviewed revision
# ---------------------------------------------------------------------------


def test_the_comment_names_the_full_forty_character_revision(rr: ModuleType) -> None:
    runner = _Runner()

    rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)

    body = runner.calls[0][runner.calls[0].index("--body") + 1]
    assert REVISION in body
    # The abbreviation must not be what the reader sees instead.
    assert f"`{REVISION}`" in body


def test_the_result_and_the_comment_name_the_same_revision(rr: ModuleType) -> None:
    """One source for the revision, so the two can never disagree."""
    runner = _Runner()
    result = _result(rr)

    outcome = rr.publish(result, pull_request="1030", repo="infiquetra/x", runner=runner)

    body = runner.calls[0][runner.calls[0].index("--body") + 1]
    assert outcome["revision"] == result.revision
    assert result.revision in body


def test_the_comment_says_it_is_not_an_approval(rr: ModuleType) -> None:
    """A reader must not mistake the comment for a passing gate."""
    runner = _Runner()

    rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)

    body = runner.calls[0][runner.calls[0].index("--body") + 1]
    assert "not a review approval" in body
    assert "A later commit carries no outcome from this one." in body


def test_a_revision_that_is_not_a_full_commit_never_reaches_publication(
    rr: ModuleType,
) -> None:
    """The refusal is at construction, so no abbreviated revision can be published."""
    with pytest.raises(rr.ReviewResultError, match="forty-character"):
        _result(rr, revision="0123456")


# ---------------------------------------------------------------------------
# Publication changes nothing in the repository
# ---------------------------------------------------------------------------


def test_publication_runs_no_git_command_at_all(rr: ModuleType) -> None:
    """Nothing is committed and nothing is pushed, so `HEAD` does not move.

    Child 935 reports the opposite arrangement, where publishing the review
    artifact advanced the branch and invalidated the caller's freshness check.
    """
    runner = _Runner()

    rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)

    for argv in runner.calls:
        assert argv[0] != "git"
        assert "commit" not in argv
        assert "push" not in argv


def test_a_failed_publish_refuses_rather_than_reporting_success(rr: ModuleType) -> None:
    runner = _Runner(returncode=1)

    with pytest.raises(rr.ReviewResultError, match="could not publish"):
        rr.publish(_result(rr), pull_request="1030", repo="infiquetra/x", runner=runner)


# ---------------------------------------------------------------------------
# What the comment says
# ---------------------------------------------------------------------------


def test_the_comment_carries_the_outcome_the_roster_and_the_cycle(rr: ModuleType) -> None:
    body = rr.render_comment(_result(rr, outcome="review_incomplete", cycle=2))

    assert "review_incomplete" in body
    assert "sha256:test-roster" in body
    assert "Cycle.** 2 of the code review loop" in body


def test_residual_issue_numbers_appear_when_the_cap_was_reached(rr: ModuleType) -> None:
    result = _result(rr, outcome="cycle_cap_best_available", cycle=5)
    result.residual_issues = [1101, 1102]

    body = rr.render_comment(result)

    assert "#1101" in body
    assert "#1102" in body
    assert "Residuals filed at the cycle cap" in body


def test_a_review_with_no_findings_says_so_rather_than_printing_an_empty_table(
    rr: ModuleType,
) -> None:
    body = rr.render_comment(_result(rr, outcome="accepted"))

    assert "No findings were reported against this revision." in body


def test_a_lens_that_established_no_threshold_is_shown_as_unscored(rr: ModuleType) -> None:
    """Eleven of the catalogue's fifteen lenses carry no fixtures today.

    Such a lens reports findings and sets no bar. The comment must say so rather
    than showing a blank cell a reader would read as a pass.
    """
    result = _result(rr)
    result.lens_results = [
        rr.LensResult(lens="adversarial", strictness="baseline", scorable=False, scored=False)
    ]

    body = rr.render_comment(result)

    assert "| adversarial | baseline | — | — | no |" in body
