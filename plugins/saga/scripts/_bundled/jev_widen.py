# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.32.0
# source-commit: authored
# source-path: scripts/fleet_commons/jev_widen.py
# source-sha256: 6919690d131dede34e1dce455e8802039acbe6343841e5fec5145418a0abc311
# output-sha256: 6919690d131dede34e1dce455e8802039acbe6343841e5fec5145418a0abc311
# --- end generated bundle stamp ---
"""The widen-only union: a pattern floor a model may raise but never lower (issue 1036).

Two places in this fleet decide something with a hand-written regular expression
and decide it too narrowly.  This module is the one place that pairs such a
pattern with a yes/no model judgment and takes the union, so the model can only
ever turn a ``False`` into a ``True``.

Three properties this module exists to guarantee:

* **Widen-only.** ``union = floor or probability >= threshold``.  There is no
  code path in which a floor of ``True`` produces a union of ``False``, whatever
  the model answers and whatever goes wrong.
* **Fail open to the floor.** An error, a timeout, a malformed body, a missing
  key, a missing answer, a non-numeric probability: every one of them leaves the
  floors exactly as the caller supplied them and names the reason in ``note``.
  A caller that ignores ``note`` still behaves as it did before this module
  existed.
* **One call path, injectable.** ``ask`` defaults to ``typesafe_client.ask`` and
  is a parameter, so a test hands in a function returning a recorded answer map
  and cannot reach the network even by accident.

Loaded the house way::

    jev_widen = fleet_commons_shim.load("jev_widen")
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# The sibling modules, loaded the way ``typesafe_client`` loads its own so this
# file works both as an in-repository import and through an installed plugin.


def _load_sibling(name: str):
    """Load ``<this file's directory>/<name>.py``.

    Portable stand-in for ``fleet_commons_shim.load``. The shim's resolution
    ladder is specific to a Claude Code plugin install. This catalog bundles
    modules at build time, and a module is always read from the directory that
    holds this file, so the same source works in ``fleet_commons/`` and in any
    generated ``_bundled/`` copy.
    """
    import importlib.util
    import sys
    from pathlib import Path

    sibling_dir = Path(__file__).resolve().parent
    cache_key = f"_fleet_commons_{name}@{sibling_dir}"
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached
    module_path = sibling_dir / f"{name}.py"
    if not module_path.is_file():
        raise RuntimeError(f"fleet-commons: module {name!r} not found at {module_path}")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internal failure
        raise RuntimeError(f"fleet-commons: importlib could not load {module_path}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = loaded
    try:
        spec.loader.exec_module(loaded)
    except BaseException:
        sys.modules.pop(cache_key, None)
        raise
    return loaded

typesafe_client = _load_sibling("typesafe_client")
jev_verbs = _load_sibling("jev_verbs")

# Which side of the union produced a ``True``.  ``regex`` wins the label when the
# floor was already set, because the floor is what makes the union true there
# regardless of the answer -- attributing it to the model would misreport how
# often the model actually widened anything, which is the number the evaluation
# harness exists to measure.
SOURCE_REGEX = "regex"
SOURCE_MODEL = "model"
SOURCE_NONE = "none"


@dataclass(frozen=True)
class Judgment:
    """One category's floor, the model's probability, and the union of the two."""

    regex: bool
    probability: float | None
    union: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "regex": self.regex,
            "probability": self.probability,
            "union": self.union,
            "source": self.source,
        }


@dataclass(frozen=True)
class WidenResult:
    """Every category's judgment, plus why the model contributed nothing when it did not."""

    judgments: dict[str, Judgment]
    threshold: float
    note: str = ""
    resolved_model: str = ""

    @property
    def asked(self) -> bool:
        """True when a model answer actually contributed to at least one judgment."""
        return any(judgment.probability is not None for judgment in self.judgments.values())

    def unions(self) -> dict[str, bool]:
        return {key: judgment.union for key, judgment in self.judgments.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "judgments": {key: judgment.to_dict() for key, judgment in self.judgments.items()},
            "threshold": self.threshold,
            "note": self.note,
            "resolved_model": self.resolved_model,
        }


def _probability(answer: Any) -> float | None:
    """The yes/no probability of an answer, or None when there is not one.

    A yes/no answer carries a probability and no confidence field, verified
    against the live endpoint (LEARNINGS ``{#jev-noul-has-no-confidence-1032}``),
    so the probability is the only number to compare against a threshold.
    """
    if not isinstance(answer, Mapping):
        return None
    if answer.get("type") != "noul":
        return None
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _floors_only(floors: Mapping[str, bool], threshold: float, note: str) -> WidenResult:
    return WidenResult(
        judgments={
            key: Judgment(
                regex=bool(floor),
                probability=None,
                union=bool(floor),
                source=SOURCE_REGEX if floor else SOURCE_NONE,
            )
            for key, floor in floors.items()
        },
        threshold=threshold,
        note=note,
    )


def widen(
    state: Any,
    verb: str,
    floors: Mapping[str, bool],
    *,
    decision_prefix: str,
    threshold: float | None = None,
    ask: Callable[..., Any] | None = None,
    log: bool = True,
    log_dir: Any = None,
    timeout: float | None = None,
    max_attempts: int | None = None,
    total_deadline: float | None = None,
) -> WidenResult:
    """Ask ``verb``'s questions about ``state`` and union the answers with ``floors``.

    ``floors`` maps a question key to the pattern's verdict.  Every key it
    carries appears in the result, including keys the model had no answer for.
    """
    entry = jev_verbs.VERBS.get(verb)
    if entry is None:
        raise ValueError(f"no such verb in the registry: {verb}")
    if threshold is None:
        threshold = entry.confidence_floor

    questions = entry.question_set()
    caller = ask if ask is not None else typesafe_client.ask

    options: dict[str, Any] = {}
    if timeout is not None:
        options["timeout"] = timeout
    if max_attempts is not None:
        options["max_attempts"] = max_attempts
    if total_deadline is not None:
        options["total_deadline"] = total_deadline

    try:
        result = caller(state, questions, **options)
    except Exception as exc:  # noqa: BLE001 - a caller's floors must survive any failure
        return _floors_only(floors, threshold, f"the request raised {type(exc).__name__}")

    if getattr(result, "status", None) != typesafe_client.STATUS_OK:
        status = getattr(result, "status", "unknown")
        note = getattr(result, "note", "") or f"the request returned status {status}"
        return _floors_only(floors, threshold, note)

    answers = getattr(result, "answers", None) or {}
    resolved_model = str(getattr(result, "model", "") or "")

    judgments: dict[str, Judgment] = {}
    missing: list[str] = []
    for key, floor in floors.items():
        floor = bool(floor)
        probability = _probability(answers.get(key))
        if probability is None and key not in answers:
            missing.append(key)
        union = floor or (probability is not None and probability >= threshold)
        if floor:
            source = SOURCE_REGEX
        elif union:
            source = SOURCE_MODEL
        else:
            source = SOURCE_NONE
        judgments[key] = Judgment(regex=floor, probability=probability, union=union, source=source)

    note = ""
    if missing:
        note = f"the answer carried no verdict for {', '.join(sorted(missing))}"

    if log:
        _record(
            decision_prefix=decision_prefix,
            state=state,
            questions=questions,
            answers=answers,
            judgments=judgments,
            threshold=threshold,
            resolved_model=resolved_model,
            log_dir=log_dir,
        )

    return WidenResult(
        judgments=judgments, threshold=threshold, note=note, resolved_model=resolved_model
    )


def _record(
    *,
    decision_prefix: str,
    state: Any,
    questions: Mapping[str, Any],
    answers: Mapping[str, Any],
    judgments: Mapping[str, Judgment],
    threshold: float,
    resolved_model: str,
    log_dir: Any,
) -> None:
    """Append one verdict per answered question.

    Logging is best-effort by design: a full disk or an unwritable log directory
    must not turn an advisory judgment into a caller-visible failure, and the
    union has already been computed by the time this runs.
    """
    try:
        jev_log = _load_sibling("jev_log")
    except Exception:  # noqa: BLE001 - no log is not a caller's problem
        return

    for key, judgment in judgments.items():
        if judgment.probability is None:
            continue
        answer = answers.get(key)
        if not isinstance(answer, Mapping):
            continue
        try:
            jev_log.record_verdict(
                decision_id=f"{decision_prefix}:{key}",
                state=state,
                questions=questions,
                answer=dict(answer),
                confidence=typesafe_client.answer_confidence(answer),
                threshold=threshold,
                resolved_model=resolved_model,
                directory=log_dir,
            )
        except Exception:  # noqa: BLE001, PERF203 - see the docstring
            return


__all__: Sequence[str] = (
    "Judgment",
    "SOURCE_MODEL",
    "SOURCE_NONE",
    "SOURCE_REGEX",
    "WidenResult",
    "widen",
)
