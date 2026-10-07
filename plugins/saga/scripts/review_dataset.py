#!/usr/bin/env python3
"""The corpus as one Langfuse dataset, and the code evaluators that score a harness run.

Issue 166, card C15. ``sync`` posts the corpus as the dataset ``saga-review-corpus``: one item
per case, its split in metadata. A held-out item carries its case ID and nothing else. The corpus
counts as private, so it posts only over ``https``.

``score`` reads one harness result file (its shape is in ``plugins/fleet-core/references/
langfuse.md``), computes the agreed numbers in plain code, and posts them as scores on one trace
per harness run: per-lens hits and false blocks, per-question precision, grade stability, and
cost. Every score is a total over a split; nothing is posted per case. ``--dry-run`` prints the
scores and sends nothing. K1 builds the corpus and K3 records harness runs; both use this.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import review_trace  # noqa: E402

DATASET_NAME = "saga-review-corpus"
SPLITS = ("tuning", "held-out")
EXPECTED = ("defect", "clean")
PLACES = 4


class DatasetError(ValueError):
    """Refused input. ``problems`` names each case or field."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# ---------------------------------------------------------------------------
# The dataset
# ---------------------------------------------------------------------------


def load_corpus(corpus: Path) -> list[dict[str, Any]]:
    """Every ``<case>/case.json`` under ``corpus``. A case without an ID or a split is refused."""
    cases: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in sorted(Path(corpus).glob("*/case.json")):
        name = path.parent.name
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append(f"{name}: case.json is not readable JSON")
            continue
        if not isinstance(case, dict):
            problems.append(f"{name}: case.json is not an object")
            continue
        if not isinstance(case.get("case_id"), str) or not case["case_id"].strip():
            problems.append(f"{name}: no case_id")
        if case.get("split") not in SPLITS:
            problems.append(f"{name}: split must be one of {', '.join(SPLITS)}")
        cases.append(case)
    if problems:
        raise DatasetError(problems)
    return cases


def item_id(case_id: str) -> str:
    return "case-" + review_trace._hex(f"{DATASET_NAME}:{case_id}", 32)


def dataset_item(case: Mapping[str, Any]) -> dict[str, Any]:
    """One item. A held-out item's input is its case ID only; its content never leaves."""
    split = str(case["split"])
    if split == "held-out":
        content: dict[str, Any] = {"case_id": case["case_id"]}
    else:
        content = dict(case)
    return {
        "id": item_id(str(case["case_id"])),
        "datasetName": DATASET_NAME,
        "input": content,
        "metadata": {"split": split},
    }


def dataset_items(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dataset_item(case) for case in cases]


def sync(corpus: Path, *, home: Path, **transport: Any) -> dict[str, Any]:
    """Post the dataset and its items, always as private."""
    cases = load_corpus(corpus)
    items: list[review_trace.Item] = [(
        "datasets",
        {"name": DATASET_NAME, "description": "Saga review corpus (issue 166). Counts as private.",
         "metadata": {"visibility": "private"}},
        "private",
    )]
    items.extend(("dataset-items", item, "private") for item in dataset_items(cases))
    return review_trace.post(items, home=home, **transport)


# ---------------------------------------------------------------------------
# The evaluators (plain code; LLM evaluators wait for hand labels)
# ---------------------------------------------------------------------------


def _round(value: float) -> float:
    return round(value, PLACES)


def _in_split(results: Sequence[Mapping[str, Any]], split: str) -> list[Mapping[str, Any]]:
    return [case for case in results if case.get("split") == split]


def lens_hits(results: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Per lens: blocked defect cases over defect cases."""
    totals: dict[str, list[int]] = {}
    for case in results:
        if case.get("expected") == "defect":
            pair = totals.setdefault(str(case.get("lens")), [0, 0])
            pair[0] += 1 if case.get("blocked") is True else 0
            pair[1] += 1
    return {lens: _round(hit / count) for lens, (hit, count) in sorted(totals.items()) if count}


def lens_false_blocks(results: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Per lens: blocked clean cases over clean cases."""
    totals: dict[str, list[int]] = {}
    for case in results:
        if case.get("expected") == "clean":
            pair = totals.setdefault(str(case.get("lens")), [0, 0])
            pair[0] += 1 if case.get("blocked") is True else 0
            pair[1] += 1
    return {lens: _round(hit / count) for lens, (hit, count) in sorted(totals.items()) if count}


def question_precision(results: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Per question: correct hits over all its hits."""
    totals: dict[str, list[int]] = {}
    for case in results:
        for hit in case.get("question_hits") or []:
            if not isinstance(hit, Mapping) or not isinstance(hit.get("question"), str):
                continue
            pair = totals.setdefault(hit["question"], [0, 0])
            pair[0] += 1 if hit.get("correct") is True else 0
            pair[1] += 1
    return {question: _round(good / count) for question, (good, count) in sorted(totals.items()) if count}


def grade_stability(results: Sequence[Mapping[str, Any]]) -> float | None:
    """The share of repeated cases whose second run made the same blocking decision."""
    repeated = [case for case in results if isinstance(case.get("repeat_blocked"), bool)]
    if not repeated:
        return None
    same = sum(1 for case in repeated if case["repeat_blocked"] == case.get("blocked"))
    return _round(same / len(repeated))


def cost(results: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    """USD and seconds per review, over every case in the split."""
    if not results:
        return None
    usd = sum(review_trace._number(case.get("cost_usd")) for case in results)
    seconds = sum(review_trace._number(case.get("seconds")) for case in results)
    return {"usd": _round(usd / len(results)), "seconds": _round(seconds / len(results))}


def evaluate(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every score as ``{name, value}``: totals per split, never one per case."""
    scores: list[dict[str, Any]] = []
    for split in SPLITS:
        cases = _in_split(results, split)
        if not cases:
            continue
        for lens, value in lens_hits(cases).items():
            scores.append({"name": f"{split}.{lens}.hit-rate", "value": value})
        for lens, value in lens_false_blocks(cases).items():
            scores.append({"name": f"{split}.{lens}.false-block-rate", "value": value})
        for question, value in question_precision(cases).items():
            scores.append({"name": f"{split}.question.{question}.precision", "value": value})
        stability = grade_stability(cases)
        if stability is not None:
            scores.append({"name": f"{split}.grade-stability", "value": stability})
        spend = cost(cases)
        if spend is not None:
            scores.append({"name": f"{split}.cost-usd-per-review", "value": spend["usd"]})
            scores.append({"name": f"{split}.seconds-per-review", "value": spend["seconds"]})
    return scores


def load_results(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, Mapping) else data
    if not isinstance(cases, list):
        raise DatasetError(["results: expected a list of cases, or an object with a cases list"])
    problems = []
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            problems.append(f"cases.{index}: not an object")
        elif case.get("split") not in SPLITS:
            problems.append(f"cases.{index}.split: must be one of {', '.join(SPLITS)}")
        elif case.get("expected") not in EXPECTED:
            problems.append(f"cases.{index}.expected: must be defect or clean")
    if problems:
        raise DatasetError(problems)
    return [dict(case) for case in cases]


def score_items(results: Sequence[Mapping[str, Any]], run_id: str, *, now_ns: int | None = None) -> list[review_trace.Item]:
    """One ``corpus-run`` trace for the harness run, then its scores, all private."""
    end = now_ns if now_ns is not None else time.time_ns()
    trace = review_trace.trace_id({"subject": "corpus-run", "dataset": DATASET_NAME, "run": run_id})
    counts = {split: len(_in_split(results, split)) for split in SPLITS}
    span = review_trace._span(trace, review_trace.span_id(trace, "corpus-run"), None, "corpus-run",
                              end, end, {
        "langfuse.trace.name": "corpus-run",
        "langfuse.observation.type": "evaluator",
        "langfuse.trace.metadata.dataset": DATASET_NAME,
        "langfuse.trace.metadata.run_id": run_id,
        "langfuse.trace.metadata.cases": counts,
    })
    items: list[review_trace.Item] = [
        ("otel-traces", body, "private") for body in review_trace._otel_bodies([span], "corpus-run")
    ]
    for score in evaluate(results):
        items.append(("scores", review_trace._score(
            trace, "corpus-run", score["name"], score["value"], "NUMERIC",
        ), "private"))
    return items


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_dataset.py",
        description="Post the review corpus as a Langfuse dataset, and score a harness run.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    syncing = sub.add_parser("sync", help="Post the corpus dataset and its items.")
    syncing.add_argument("--corpus", type=Path, required=True)
    syncing.add_argument("--home", type=Path, default=None)
    scoring = sub.add_parser("score", help="Compute and post a harness run's evaluator scores.")
    scoring.add_argument("--results", type=Path, required=True)
    scoring.add_argument("--run-id", required=True)
    scoring.add_argument("--dry-run", action="store_true", help="Print the scores; send nothing.")
    scoring.add_argument("--home", type=Path, default=None)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    urlopen: Callable[..., Any] | None = None,
    getenv: Callable[[str], str | None] = os.environ.get,
) -> int:
    """0 done (posted or queued), 2 refused input. Langfuse problems never change the code."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    home = Path(args.home or Path.home())
    transport = {"urlopen": urlopen, "getenv": getenv}
    try:
        if args.command == "sync":
            summary = sync(args.corpus, home=home, **transport)
            print(review_trace.summary_line(summary), file=sys.stderr)
            return 0
        results = load_results(args.results)
        if args.dry_run:
            print(json.dumps({"scores": evaluate(results)}, indent=2))
            return 0
        summary = review_trace.post(score_items(results, args.run_id), home=home, **transport)
        print(review_trace.summary_line(summary), file=sys.stderr)
        return 0
    except DatasetError as exc:
        print("review_dataset: " + "\n  ".join(exc.problems), file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"review_dataset: {exc.__class__.__name__}: unreadable input", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
