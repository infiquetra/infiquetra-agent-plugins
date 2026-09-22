"""One review end to end, with the lens sessions replaced by a fake executor.

Issue 1001's fifth acceptance criterion — one real review on a pull request — is
deferred to the parent pull request that issue 1030 opens, because children of
parent 1018 open no pull request of their own. This file is what stands in for it
until then: the declaration is built from a run record, the roster is resolved by
the real lifecycle generator, a fake executor returns fixed per-lens results, the
verdict is computed from the catalogue's ladder, a `review_result.v2` is written
into a temporary run record, and the comment that would be posted is captured
rather than sent.

Nothing here reaches the network, launches a session, or writes outside `tmp_path`.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
def modules() -> dict[str, ModuleType]:
    sys.path.insert(0, str(SCRIPTS))
    return {
        "roster": _load("review_roster_dry", SCRIPTS / "review_roster.py"),
        "result": _load("review_result_dry", SCRIPTS / "review_result.py"),
        "consensus": _load("review_consensus_dry", SCRIPTS / "review_consensus.py"),
        "record": _load("run_record_dry", SCRIPTS / "run_record.py"),
    }


def _real_checkout() -> Path | None:
    configured = os.environ.get("INFIQUETRA_SDLC_PATH") or os.environ.get("INFIQUETRA_SDLC_ROOT")
    candidate = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"
    )
    return candidate if (candidate / "tools" / "docs" / "gen_review_roster.py").is_file() else None


def _record(record_module: ModuleType) -> Any:
    record = record_module.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=record_module.empty_run_configuration(),
        approval_scope=record_module.empty_approval_scope(),
        admission=record_module.empty_admission(),
    )
    record.run_configuration["applicable_lenses"] = {
        "value": {
            "always_on": [
                "architecture-maintainability",
                "correctness",
                "security",
                "testing",
            ],
            "conditional_applies": {
                "reliability": "the change owns lens-execution recovery",
                "api-contract": "the change authors two file-format contracts",
                "adversarial": "the change is the pre-merge gate itself",
                "documentation-clarity": "the skill and its references are rewritten",
                "agent-usability": "the skill is a surface an agent operates",
            },
            "conditional_does_not_apply": {
                "deployment-infrastructure": "no infrastructure or deployment changes",
                "performance": "no latency, throughput or cost path changes",
                "privacy": "no personal or sensitive data is touched",
                "previous-comments": "this card opens no pull request of its own",
                "accessibility-human-usability": "no human-operated visual surface changes",
                "experience": "no user-facing surface changes",
            },
        },
        "chosen_by": "planner",
        "source": "operator",
    }
    return record


class _FakeExecutor:
    """A lens executor that returns a fixed reading, and records what it was asked.

    It stands in for a roster session or a subagent. Injecting it is what makes this
    a test rather than a live review: no session is created, no vendor is called, and
    the dispatch it received can be asserted.
    """

    def __init__(self, *, score: int = 9) -> None:
        self.dispatches: list[dict[str, Any]] = []
        self.score = score

    def review(self, *, lens: str, revision: str, roster_hash: str, threshold: dict) -> dict:
        self.dispatches.append(
            {
                "lens": lens,
                "revision": revision,
                "roster_hash": roster_hash,
                "threshold": threshold,
            }
        )
        return {
            "dimension_scores": {f"{lens}-d1": self.score, f"{lens}-d2": self.score},
            "findings": [],
        }


class _Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_kwargs: Any) -> Any:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "https://example/comment/1", "")


def _run_review(modules: dict[str, ModuleType], checkout: Path, executor: _FakeExecutor) -> Any:
    """The whole chain: declaration, roster, lenses, verdict, result."""
    roster_module = modules["roster"]
    result_module = modules["result"]
    consensus = modules["consensus"]

    record = _record(modules["record"])
    declaration = roster_module.build_declaration(
        record, revision=REVISION, resolved_at="2026-09-19T00:00:00Z"
    )
    resolution = roster_module.resolve_roster(
        declaration, checkout=roster_module.resolve_checkout(checkout)
    )

    lens_results = []
    for row in roster_module.selected_lenses(resolution.roster):
        lens_id = row["id"]
        threshold = row.get("threshold", {})
        scorable = bool(row.get("scorable"))
        if not scorable:
            # A lens the catalogue marks unscorable has no fixtures, so no executor
            # can be qualified against it. It reports findings and sets no bar.
            lens_results.append(
                result_module.LensResult(
                    lens=lens_id,
                    strictness=threshold.get("strictness", "baseline"),
                    scorable=False,
                    scored=False,
                    threshold=threshold,
                )
            )
            continue
        reading = executor.review(
            lens=lens_id,
            revision=REVISION,
            roster_hash=resolution.roster_hash,
            threshold=threshold,
        )
        # Whether a scoring executor is QUALIFIED is the roster's answer, not this
        # code's: the generator refuses to assign one without a ledger entry, so a
        # lens with no scoring executor in the roster establishes no threshold.
        qualified = row.get("scoring_executor") is not None
        lens_results.append(
            result_module.LensResult(
                lens=lens_id,
                strictness=threshold.get("strictness", "standard"),
                scorable=True,
                scored=qualified,
                dimension_scores=reading["dimension_scores"] if qualified else {},
                threshold=threshold,
            )
        )

    draft = result_module.ReviewResult(
        revision=REVISION,
        roster_hash=resolution.roster_hash,
        outcome="review_incomplete",
        cycle=1,
        loop=result_module.LOOP_CODE_REVIEW,
        unit="issue-1001",
        lens_results=lens_results,
        provenance={
            "sdlc_head": resolution.checkout.head,
            "sdlc_source": resolution.checkout.source,
            "validation_status": resolution.validation["status"],
        },
    )
    draft.outcome = consensus.verdict_for_result(draft.to_dict())
    return draft, resolution, record


# ---------------------------------------------------------------------------
# The dry run
# ---------------------------------------------------------------------------


def test_the_whole_review_runs_end_to_end_against_the_real_generator(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    executor = _FakeExecutor()
    result, resolution, record = _run_review(modules, checkout, executor)

    # The result's roster hash is the generator's own, carried through unchanged.
    assert result.roster_hash == resolution.roster["hash"]
    assert result.roster_hash.startswith("sha256:")

    # Nine lenses: the four always-on, plus the five conditional ones the
    # declaration says apply.
    assert len(result.lens_results) == 9
    scored_lenses = {row.lens for row in result.lens_results if row.scorable}
    assert scored_lenses == {
        "architecture-maintainability",
        "correctness",
        "security",
        "testing",
    }


def test_the_verdict_is_review_incomplete_while_the_ledger_is_empty(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The honest answer today, asserted so a future change to it is visible.

    The lifecycle repository's `config/executor-verifications.json` has no entries,
    so the generator assigns no scoring executor and no lens establishes a
    threshold. That is not a failure of this code: a score from an unqualified model
    is not weak evidence, it is not evidence. When the first qualification lands,
    this assertion changes — deliberately, in a diff someone reads.
    """
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    result, resolution, _record = _run_review(modules, checkout, _FakeExecutor(score=10))

    assert result.outcome == "review_incomplete"
    assert resolution.validation["status"] == "refused"
    failing = {
        check["name"] for check in resolution.validation["checks"] if check["result"] == "fail"
    }
    assert "verification_presence" in failing


def test_every_lens_dispatch_names_its_revision_and_its_roster(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    """No dispatch inherits its revision or its policy from the host."""
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    executor = _FakeExecutor()
    _result, resolution, _record = _run_review(modules, checkout, executor)

    assert executor.dispatches, "no lens was dispatched"
    for dispatch in executor.dispatches:
        assert dispatch["revision"] == REVISION
        assert dispatch["roster_hash"] == resolution.roster["hash"]
        assert dispatch["lens"]


def test_the_result_lands_in_the_run_records_review_cycles(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    """A temporary store, never the primary checkout's."""
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    result_module = modules["result"]
    record_module = modules["record"]
    result, _resolution, record = _run_review(modules, checkout, _FakeExecutor())

    updated = result_module.append_result(record, result)
    store = tmp_path / "runs"
    store.mkdir()
    path = record_module.save(store, updated)

    written = json.loads(Path(path).read_text(encoding="utf-8"))
    assert len(written["review_cycles"]) == 1
    entry = written["review_cycles"][0]
    assert entry["schema"] == "review_result.v2"
    assert entry["revision"] == REVISION
    assert entry["loop"] == "code_review"
    assert entry["outcome"] == "review_incomplete"
    assert str(tmp_path) in str(path)


def test_the_would_be_comment_is_one_comment_and_no_review(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    result_module = modules["result"]
    result, _resolution, _record = _run_review(modules, checkout, _FakeExecutor())
    runner = _Runner()

    outcome = result_module.publish(
        result, pull_request="1030", repo="infiquetra/infiquetra-claude-plugins", runner=runner
    )

    assert len(runner.calls) == 1
    assert runner.calls[0][:3] == ["gh", "pr", "comment"]
    assert outcome["reviews"] == 0
    body = runner.calls[0][runner.calls[0].index("--body") + 1]
    assert REVISION in body

    # Written to the scratch directory rather than sent anywhere.
    captured = tmp_path / "would-be-comment.md"
    captured.write_text(body, encoding="utf-8")
    assert captured.read_text(encoding="utf-8") == body


def test_the_checkout_revision_is_recorded_with_the_result(
    modules: dict[str, ModuleType], tmp_path: Path
) -> None:
    """Which working tree the policy came from is on the record, not assumed."""
    checkout = _real_checkout()
    if checkout is None:
        pytest.skip("the lifecycle repository is not checked out on this machine")

    result, resolution, _record = _run_review(modules, checkout, _FakeExecutor())

    assert result.provenance["sdlc_head"] == resolution.checkout.head
    assert len(result.provenance["sdlc_head"]) == 40
    assert result.provenance["validation_status"] == "refused"


# ---------------------------------------------------------------------------
# The scripted acceptance criteria, as commands
# ---------------------------------------------------------------------------


def test_the_private_lens_roster_is_gone() -> None:
    """Issue 1001's third acceptance criterion, as a test."""
    assert not (ROOT / "plugins" / "saga" / "references" / "lens-roster.json").exists()


def test_the_verdict_command_prints_one_word_and_nothing_else(tmp_path: Path) -> None:
    """Issue 1001's second acceptance criterion, run as the card writes it."""
    result_file = tmp_path / "result.json"
    result_file.write_text(
        json.dumps(
            {
                "schema": "review_result.v2",
                "cycle": 1,
                "per_lens_results": [
                    {
                        "lens": "correctness",
                        "executed": True,
                        "scored": True,
                        "scorable": True,
                        "derived_overall": 9.5,
                        "dimension_scores": {"a": 9, "b": 10},
                        "threshold": {
                            "derived_overall_minimum": 9.0,
                            "applicable_dimension_minimum": 7,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(  # nosec B603
        [
            sys.executable,
            str(SCRIPTS / "review_consensus.py"),
            "--result",
            str(result_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "accepted"
    assert completed.stdout.count("\n") == 1, "exactly one line, and nothing else"


@pytest.mark.parametrize(
    ("scored", "overall", "cycle", "expected"),
    [
        (True, 9.5, 1, "accepted"),
        (True, 8.5, 1, "repairs_requested"),
        (True, 8.5, 5, "cycle_cap_best_available"),
        (False, None, 1, "review_incomplete"),
    ],
)
def test_the_command_prints_each_of_the_four_outcomes_and_no_others(
    tmp_path: Path, scored: bool, overall: float | None, cycle: int, expected: str
) -> None:
    result_file = tmp_path / f"result-{expected}-{cycle}.json"
    result_file.write_text(
        json.dumps(
            {
                "schema": "review_result.v2",
                "cycle": cycle,
                "per_lens_results": [
                    {
                        "lens": "correctness",
                        "executed": True,
                        "scored": scored,
                        "scorable": True,
                        "derived_overall": overall,
                        "dimension_scores": {"a": 9} if scored else {},
                        "threshold": {
                            "derived_overall_minimum": 9.0,
                            "applicable_dimension_minimum": 7,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(  # nosec B603
        [sys.executable, str(SCRIPTS / "review_consensus.py"), "--result", str(result_file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.stdout.strip() == expected
