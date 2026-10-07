# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.33.0
# source-commit: authored
# source-path: scripts/fleet_commons/jev_sweep.py
# source-sha256: 8dfe6004b98ef0776d3d334fe0c157641ca91580b5db3f7d6280de043c2eb5a7
# output-sha256: 8dfe6004b98ef0776d3d334fe0c157641ca91580b5db3f7d6280de043c2eb5a7
# --- end generated bundle stamp ---
"""Classify pieces into a where-to-look list (issue 156).

The sweep asks a question bank about pieces it is given. It does not read a diff,
a price table, or a calibration file. Saga cuts the pieces and passes the
thresholds and the rate in as data.

Loaded the house way, from the directory that holds this file, so the same source
works in ``fleet_commons/`` and in a generated ``_bundled/`` copy. ``jev.py``'s
loader is the wrong pattern here: that file lives one directory up.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any


def _load_sibling(name: str):
    """Load ``<this file's directory>/<name>.py``."""
    import importlib.util
    import sys

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
jev_log = _load_sibling("jev_log")

ITEM_CAP = 30
SPEND_CAP_USD = Decimal("1")
PIECE_KINDS = ("function", "block", "file")
BLOCK_CONTEXT_LINES = 20
SMALL_FILE_MAX_LINES = 400

REQUESTED_MODEL = "jev-latest"
CLASSIFIER_NAME = "jev"
BANK_SCHEMA = "question_bank.v1"
RATE_KEYS = (
    "uncached_input",
    "cache_read",
    "cache_write_5m",
    "cache_write_1h",
    "output",
)
LENSES = ("correctness", "security", "testing", "architecture-maintainability")
LANGUAGES = (
    "python",
    "typescript",
    "dart",
    "rust",
    "swift",
    "markdown",
    "shell",
    "github-workflows",
    "cloudformation",
    "none",
)
QUESTION_KEYS = {"id", "lens", "kind", "options", "examples", "not_for", "when", "piece"}
_NO_KEY_NOTE = (
    f"{typesafe_client.KEY_ENV} is not set in the environment; no request was attempted"
)


class SweepInputError(ValueError):
    """The bank, pieces, thresholds or rate are not the shape this command accepts."""


def sweep(
    bank: Any,
    pieces: Any,
    thresholds: Any,
    rate: Any,
    *,
    repo: str = "local",
    head: str = "unknown",
    cache_dir: Any = None,
    log_dir: Any = None,
    ask: Callable[..., Any] | None = None,
    getenv: Callable[[str], str | None] | None = None,
    urlopen: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return at most 30 where-to-look items for ``pieces``.

    ``ask`` defaults to the TypeSafe client. Tests pass a fake, or a ``urlopen``,
    so the suite makes no network call. Verdict lines are buffered and written
    only when every request was ok, so a later failure leaves no partial log.
    """
    questions = _bank(bank)
    threshold_map = _thresholds(thresholds)
    prices = _rate(rate)
    prepared_pieces = _pieces(pieces)
    caller = ask if ask is not None else typesafe_client.ask
    store = cache_dir if cache_dir is not None else jev_log.log_dir()

    exclusive = {
        piece["only_question"]
        for piece in prepared_pieces
        if piece.get("only_question")
    }
    ordered = sorted(prepared_pieces, key=_piece_order)
    hits: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    spend = Decimal(0)
    seconds = Decimal(0)
    stopped = False
    last_model = ""

    for piece in ordered:
        matched = [question for question in questions if _eligible(question, piece, exclusive)]
        sendable: list[dict[str, Any]] = []
        for question in matched:
            if question["kind"] == "yes-no" and not _yes_no_ordered(question):
                degraded.append(_mark("unreadable-answer", piece["id"], question["id"]))
            else:
                sendable.append(question)
        if not sendable:
            continue
        if stopped:
            degraded.extend(_mark("spend", piece["id"], question["id"]) for question in sendable)
            continue

        state = _state(piece)
        batches, unfit = _batches(state, sendable)
        degraded.extend(_mark("budget", piece["id"], question["id"]) for question in unfit)
        for group, mapping, meta in batches:
            if stopped:
                degraded.extend(_mark("spend", piece["id"], question["id"]) for question in group)
                continue
            result = _call(caller, state, mapping, store, getenv, urlopen)
            seconds += Decimal(int(getattr(result, "latency_ms", 0) or 0)) / Decimal(1000)
            if not _ok(result):
                note = str(getattr(result, "note", "") or "")
                reason = "no-key" if note == _NO_KEY_NOTE else "classifier"
                return _payload([], [{"reason": reason}], True, "", spend, seconds)
            last_model = str(getattr(result, "model", "") or "") or last_model
            cost, unpriced = _live_cost(result, prices)
            spend += cost
            if unpriced or spend >= SPEND_CAP_USD:
                stopped = True
            _collect(
                piece, state, mapping, meta, result, threshold_map, hits, degraded, pending,
                repo, head,
            )

    items = _items(hits)
    if len(items) > ITEM_CAP:
        for dropped in items[ITEM_CAP:]:
            top = max(dropped["questions"], key=lambda question: question["probability"])
            degraded.append(_mark("cap", dropped.pop("_piece"), top["id"]))
        items = items[:ITEM_CAP]
    for item in items:
        item.pop("_piece", None)
    for entry in pending:
        kwargs = dict(entry)
        if log_dir is not None:
            kwargs["directory"] = log_dir
        jev_log.record_verdict(**kwargs)
    model = items[0]["classifier"]["model"] if items else last_model
    return _payload(items, degraded, False, model, spend, seconds)


def _call(ask, state, questions, cache_dir, getenv, urlopen):
    kwargs: dict[str, Any] = {"model": REQUESTED_MODEL, "cache_dir": cache_dir}
    if getenv is not None:
        kwargs["getenv"] = getenv
    if urlopen is not None:
        kwargs["urlopen"] = urlopen
        kwargs["transport"] = typesafe_client.TRANSPORT_URLLIB
    return ask(state, questions, **kwargs)


def _ok(result: Any) -> bool:
    flag = getattr(result, "ok", None)
    if flag is not None:
        return bool(flag)
    return getattr(result, "status", "") == typesafe_client.STATUS_OK


def _live_cost(result: Any, rate: Mapping[str, Decimal]) -> tuple[Decimal, bool]:
    """The dollars a live response added, and whether the usage was unpriced.

    A cache hit spent nothing. A live response with no ``input_tokens`` is not
    priced as zero: the caller stops, and the answers already in hand are kept.
    """
    if str(getattr(result, "transport", "") or "") == "cache":
        return Decimal(0), False
    usage = getattr(result, "usage", None) or {}
    if not isinstance(usage, Mapping) or "input_tokens" not in usage:
        return Decimal(0), True
    incoming = usage["input_tokens"]
    outgoing = usage.get("output_tokens", 0)
    if _bad_count(incoming) or _bad_count(outgoing):
        return Decimal(0), True
    cost = (
        Decimal(int(incoming)) / Decimal(1_000_000) * rate["uncached_input"]
        + Decimal(int(outgoing)) / Decimal(1_000_000) * rate["output"]
    )
    return cost, False


def _bad_count(value: Any) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value < 0


def _collect(
    piece, state, mapping, meta, result, thresholds, hits, degraded, pending, repo, head,
) -> None:
    answers = getattr(result, "answers", None) or {}
    model = str(getattr(result, "model", "") or "")
    for question, spec in meta:
        read = _probability(question, spec, answers)
        if read is None:
            degraded.append(_mark("unreadable-answer", piece["id"], question["id"]))
            continue
        probability, confidence = read
        threshold = thresholds.get(question["id"])
        pending.append({
            "decision_id": f"sweep:{repo}@{head}:{piece['id']}:{question['id']}",
            "state": state,
            "questions": mapping,
            "answer": {"probability": _number(probability)},
            "confidence": None if confidence is None else _number(confidence),
            "threshold": None if threshold is None else _number(threshold),
            "resolved_model": model,
        })
        if threshold is not None and probability < threshold:
            continue
        hits.append({
            "question_id": question["id"],
            "probability": _number(probability),
            "lens": question["lens"],
            "location": copy.deepcopy(piece["location"]),
            "language": piece["language"],
            "piece_id": piece["id"],
            "degraded": bool(piece["degraded"]),
            "model": model,
        })


def _probability(question, spec, answers):
    if spec[0] == "noul":
        answer = answers.get(spec[1])
        if not isinstance(answer, Mapping):
            return None
        value = answer.get("noul")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        probability = Decimal(str(value))
        if probability < 0 or probability > 1:
            return None
        return probability, None
    forward = _distribution(answers.get(spec[1]), [opt["id"] for opt in question["options"]])
    reverse = _distribution(answers.get(spec[2]), [opt["id"] for opt in question["options"]])
    if forward is None or reverse is None:
        return None
    first = question["options"][0]["id"]
    averaged = (forward[0][first] + reverse[0][first]) / Decimal(2)
    confidences = [item for item in (forward[1], reverse[1]) if item is not None]
    confidence = sum(confidences, Decimal(0)) / Decimal(len(confidences)) if confidences else None
    return averaged, confidence


def _distribution(answer, option_ids):
    if not isinstance(answer, Mapping):
        return None
    raw = answer.get("probabilities")
    if isinstance(raw, Mapping):
        parsed: dict[str, Decimal] = {}
        for option_id in option_ids:
            value = raw.get(option_id)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            number = Decimal(str(value))
            if number < 0 or number > 1:
                return None
            parsed[option_id] = number
        return parsed, _confidence(answer)
    return _confidence_spread(answer, option_ids)


def _confidence_spread(answer, option_ids):
    confidence = _confidence(answer)
    chosen = answer.get("choice")
    if confidence is None or chosen not in option_ids:
        return None
    others = [option_id for option_id in option_ids if option_id != chosen]
    if not others:
        return None
    share = (Decimal(1) - confidence) / Decimal(len(others))
    parsed = {
        option_id: confidence if option_id == chosen else share
        for option_id in option_ids
    }
    return parsed, confidence


def _confidence(answer: Mapping[str, Any]) -> Decimal | None:
    value = answer.get("confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = Decimal(str(value))
    if number < 0 or number > 1:
        return None
    return number


def _batches(state, questions):
    mapping, meta = _question_map(questions)
    if _fits(state, mapping):
        return [(questions, mapping, meta)], []
    groups: dict[str, list] = {}
    order: list[str] = []
    for question in questions:
        groups.setdefault(question["lens"], [])
        if question["lens"] not in order:
            order.append(question["lens"])
        groups[question["lens"]].append(question)
    batches = []
    unfit = []
    for lens in order:
        group = groups[lens]
        group_map, group_meta = _question_map(group)
        if _fits(state, group_map):
            batches.append((group, group_map, group_meta))
        else:
            unfit.extend(group)
    return batches, unfit


def _fits(state, questions) -> bool:
    if not questions:
        return True
    try:
        prepared = typesafe_client.prepare_state(state, questions)
    except typesafe_client.TypeSafeClientError:
        return False
    return not prepared.truncation


def _question_map(questions):
    mapping: dict[str, Any] = {}
    meta = []
    for question in questions:
        if question["kind"] == "yes-no":
            key = f"n{len(mapping)}"
            mapping[key] = {"type": "noul", "instructions": _instructions(question)}
            meta.append((question, ("noul", key)))
            continue
        forward = {opt["id"]: opt["definition"] for opt in question["options"]}
        reverse = {opt["id"]: opt["definition"] for opt in reversed(question["options"])}
        key_forward = f"c{len(mapping)}"
        mapping[key_forward] = {
            "type": "choice",
            "instructions": _instructions(question),
            "criteria": forward,
        }
        key_reverse = f"c{len(mapping)}"
        mapping[key_reverse] = {
            "type": "choice",
            "instructions": _instructions(question),
            "criteria": reverse,
        }
        meta.append((question, ("choice", key_forward, key_reverse)))
    return mapping, meta


def _instructions(question: Mapping[str, Any]) -> str:
    lines = [str(question["id"])]
    for option in question["options"]:
        lines.append(f"{option['id']}: {option['definition']}")
    if question.get("examples"):
        lines.append("Examples: " + "; ".join(str(item) for item in question["examples"]))
    if question.get("not_for"):
        lines.append("Not for: " + "; ".join(str(item) for item in question["not_for"]))
    return "\n".join(lines)


def _items(hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list] = {}
    for hit in hits:
        key = (json.dumps(hit["location"], sort_keys=True), hit["lens"])
        groups.setdefault(key, []).append(hit)
    items = []
    for group in groups.values():
        best = max(group, key=lambda hit: hit["probability"])
        items.append({
            "kind": "where_to_look",
            "schema": "review_records.v1",
            "lens": best["lens"],
            "location": copy.deepcopy(best["location"]),
            "language": best["language"],
            "questions": [
                {"id": hit["question_id"], "probability": hit["probability"]} for hit in group
            ],
            "classifier": {"name": CLASSIFIER_NAME, "model": best["model"]},
            "degraded": any(bool(hit["degraded"]) for hit in group),
            "_piece": best["piece_id"],
        })
    items.sort(key=lambda item: (
        -max(question["probability"] for question in item["questions"]),
        item["location"]["file"],
        item["location"]["lines"]["start"],
        item["lens"],
    ))
    return items


def _eligible(question, piece, exclusive) -> bool:
    only = piece.get("only_question")
    if only and question["id"] != only:
        return False
    if question["id"] in exclusive and not only:
        return False
    if question["piece"] != piece["kind"]:
        return False
    when = question.get("when") or {}
    languages = when.get("languages")
    if languages is not None and piece["language"] not in languages:
        return False
    paths = when.get("paths")
    if paths is not None and not any(_wildmatch(pattern, piece["path"]) for pattern in paths):
        return False
    return True


def _wildmatch(pattern: str, path: str) -> bool:
    """``*`` is one path segment. ``**`` crosses segments. No third-party matcher."""
    return re.fullmatch(_wild_regex(pattern), path.replace("\\", "/")) is not None


def _wild_regex(pattern: str) -> str:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return "".join(parts)


def _yes_no_ordered(question: Mapping[str, Any]) -> bool:
    options = question["options"]
    return (
        len(options) >= 2
        and options[0].get("id") == "yes"
        and options[1].get("id") == "no"
    )


def _state(piece: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": piece["path"],
        "language": piece["language"],
        "piece": piece["text"],
        "piece_kind": piece["kind"],
    }


def _piece_order(piece: Mapping[str, Any]):
    return (piece["path"], piece["location"]["lines"]["start"], piece["id"])


def _mark(reason: str, piece_id: str, question_id: str) -> dict[str, str]:
    return {"reason": reason, "piece": piece_id, "question": question_id}


def _number(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001")))


def _payload(items, degraded, failed, model, spend, seconds) -> dict[str, Any]:
    return {
        "items": items,
        "degraded": degraded,
        "failed": failed,
        "model": model,
        "spend": format(spend, "f"),
        "seconds": format(seconds, "f"),
    }


def _bank(bank: Any) -> list[dict[str, Any]]:
    if not isinstance(bank, Mapping) or bank.get("schema") != BANK_SCHEMA:
        raise SweepInputError("bank schema must be question_bank.v1")
    raw = bank.get("questions")
    if not isinstance(raw, list):
        raise SweepInputError("bank questions must be a list")
    questions = []
    for index, question in enumerate(raw):
        questions.append(_question(question, index))
    return questions


def _question(question: Any, index: int) -> dict[str, Any]:
    if not isinstance(question, Mapping):
        raise SweepInputError(f"questions[{index}] is not an object")
    extra = set(question) - QUESTION_KEYS
    if extra:
        raise SweepInputError(
            f"questions[{index}] has unexpected keys: {', '.join(sorted(extra))}"
        )
    for field in ("id", "lens", "kind", "options", "piece"):
        if field not in question:
            raise SweepInputError(f"questions[{index}] is missing {field}")
    if not isinstance(question["id"], str) or not question["id"]:
        raise SweepInputError(f"questions[{index}].id must be a non-empty string")
    if question["lens"] not in LENSES:
        raise SweepInputError(f"questions[{index}].lens is not a review lens")
    if question["kind"] not in {"yes-no", "choice"}:
        raise SweepInputError(f"questions[{index}].kind must be yes-no or choice")
    if question["piece"] not in PIECE_KINDS:
        raise SweepInputError(f"questions[{index}].piece is not a piece kind")
    options = _options(question["options"], index)
    if question["kind"] == "choice" and len(options) < 2:
        raise SweepInputError(f"questions[{index}] needs at least two options")
    when = question.get("when", {})
    if when is None:
        when = {}
    if not isinstance(when, Mapping):
        raise SweepInputError(f"questions[{index}].when must be an object")
    _when(when, index)
    for field in ("examples", "not_for"):
        if field in question and not isinstance(question[field], list):
            raise SweepInputError(f"questions[{index}].{field} must be a list")
    return dict(question)


def _options(options: Any, index: int) -> list[Any]:
    if not isinstance(options, list) or not options:
        raise SweepInputError(f"questions[{index}].options must be a non-empty list")
    seen = set()
    for option in options:
        if not isinstance(option, Mapping):
            raise SweepInputError(f"questions[{index}] has an option that is not an object")
        if set(option) - {"id", "definition"}:
            raise SweepInputError(f"questions[{index}] has an option with an unexpected key")
        if not isinstance(option.get("id"), str) or not option["id"]:
            raise SweepInputError(f"questions[{index}] has an option with no id")
        if not isinstance(option.get("definition"), str):
            raise SweepInputError(f"questions[{index}] has an option with no definition")
        if option["id"] in seen:
            raise SweepInputError(f"questions[{index}] repeats option {option['id']!r}")
        seen.add(option["id"])
    return options


def _when(when: Mapping[str, Any], index: int) -> None:
    extra = set(when) - {"languages", "paths"}
    if extra:
        raise SweepInputError(
            f"questions[{index}].when has unexpected keys: {', '.join(sorted(extra))}"
        )
    languages = when.get("languages")
    if languages is not None:
        if not isinstance(languages, list) or any(item not in LANGUAGES for item in languages):
            raise SweepInputError(f"questions[{index}].when.languages is not a language list")
    paths = when.get("paths")
    if paths is not None:
        if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
            raise SweepInputError(f"questions[{index}].when.paths must be a list of patterns")


def _thresholds(thresholds: Any) -> dict[str, Decimal]:
    if not isinstance(thresholds, Mapping):
        raise SweepInputError("thresholds must be an object")
    parsed: dict[str, Decimal] = {}
    for key, value in thresholds.items():
        if not isinstance(key, str):
            raise SweepInputError("a threshold key must be a question id")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SweepInputError(f"threshold for {key} must be a number")
        number = Decimal(str(value))
        if number < 0 or number > 1:
            raise SweepInputError(f"threshold for {key} must be from 0 to 1")
        parsed[key] = number
    return parsed


def _rate(rate: Any) -> dict[str, Decimal]:
    if not isinstance(rate, Mapping) or set(rate) != set(RATE_KEYS):
        raise SweepInputError(
            "rate must carry exactly " + ", ".join(RATE_KEYS)
        )
    parsed = {}
    for key in RATE_KEYS:
        value = rate[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise SweepInputError(f"rate.{key} must be a number")
        try:
            number = Decimal(str(value))
        except Exception as exc:
            raise SweepInputError(f"rate.{key} must be a number") from exc
        if number < 0:
            raise SweepInputError(f"rate.{key} must be a non-negative number")
        parsed[key] = number
    return parsed


def _pieces(pieces: Any) -> list[dict[str, Any]]:
    if not isinstance(pieces, list):
        raise SweepInputError("pieces must be a list")
    parsed = []
    for index, piece in enumerate(pieces):
        parsed.append(_piece(piece, index))
    return parsed


def _piece(piece: Any, index: int) -> dict[str, Any]:
    if not isinstance(piece, Mapping):
        raise SweepInputError(f"pieces[{index}] is not an object")
    for field in ("id", "path", "language", "kind", "text", "degraded", "location"):
        if field not in piece:
            raise SweepInputError(f"pieces[{index}] is missing {field}")
    if piece["kind"] not in PIECE_KINDS:
        raise SweepInputError(f"pieces[{index}].kind is not a piece kind")
    if piece["language"] not in LANGUAGES:
        raise SweepInputError(f"pieces[{index}].language is not a review language")
    if not isinstance(piece["text"], str) or not isinstance(piece["degraded"], bool):
        raise SweepInputError(f"pieces[{index}] has a text or degraded field of the wrong type")
    only = piece.get("only_question")
    if only is not None and (not isinstance(only, str) or not only):
        raise SweepInputError(f"pieces[{index}].only_question must be a question id")
    location = piece["location"]
    if not isinstance(location, Mapping):
        raise SweepInputError(f"pieces[{index}].location is not an object")
    lines = location.get("lines")
    if location.get("scope") != "lines" or not isinstance(lines, Mapping):
        raise SweepInputError(f"pieces[{index}].location must be a lines scope")
    if "function" not in location:
        raise SweepInputError(f"pieces[{index}].location.function is required")
    for field in ("start", "end"):
        if not isinstance(lines.get(field), int) or isinstance(lines.get(field), bool):
            raise SweepInputError(f"pieces[{index}].location.lines.{field} must be an integer")
    copied = dict(piece)
    copied["location"] = copy.deepcopy(dict(location))
    copied["location"]["lines"] = dict(lines)
    return copied
