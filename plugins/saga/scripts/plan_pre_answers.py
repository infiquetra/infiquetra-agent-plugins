#!/usr/bin/env python3
"""Saga Plan's versioned structured pre-answer carrier (#924, ``plan_pre_answers.v1``).

A caller that has already settled a decision hands it to ``/plan`` as a fenced JSON
block in the invocation text, instead of letting the conversation re-ask it:

```json
{
  "schema": "plan_pre_answers.v1",
  "caller": "orchestrate",
  "backend": "inline",
  "destination": "plan-only"
}
```

Intake, not a phase (plan KTD4): evaluated once, before the conversation begins. The
only visible effects a carrier may produce are narration of an applied value together
with its caller, and the absence of a question that would otherwise have been asked.

Contract shape (plan KTD5):

* ``schema`` — the version token ``plan_pre_answers.v1``. Two cases, stated as the code
  performs them: a non-v1 token INSIDE the ``plan_pre_answers`` family (case-insensitive,
  token boundary) is refused whole — no field from that carrier is applied; a FOREIGN
  schema family is not a carrier at all and is ignored.
* ``backend`` — decision field, from ``inline | team-execution | cc-workflows-ultracode``
  (the enum Phase 5.2 records into the plan-doc ``backend:`` field). Optional. Operator
  ruling (review F03, stricter than #808): the carrier applies ONLY ``inline``
  automatically; ``team-execution`` and ``cc-workflows-ultracode`` are legal plan values
  but require explicit operator invocation, so the carrier stops and surfaces instead of
  applying them.
* ``destination`` — decision field, from ``plan-only | pr | merge | nonprod-deploy``
  (the enum Phase 5.1 asks and the tick's ``--destination`` carries). Optional. Both
  omitted is a valid empty carrier.
* ``caller`` — envelope metadata naming the supplying capability for the narration.
  NOT a decision field: exactly two decision fields are admitted, and ``caller`` sits
  outside that admission limit.

Carrier discipline (reviews F08/F08a/F15/F30, cycle-2 C03/P02/S01): the block's fence
info string must be exactly ``json``; at most one carrier may be present — two carriers
stop the run rather than letting the first win silently; duplicate JSON keys stop the run
rather than applying the last value; and a ``json``-fenced block that fails to parse or
repeats a key is a malformed carrier — a stop — only when it is carrier-shaped (its raw
text names the ``plan_pre_answers`` family). An unrelated malformed JSON example is
prose, ignored exactly as a foreign schema already is: the stop must never over-fire on
invocation text that carries no carrier.

Pure functions: reads the text it is given, writes nothing, reads no file (KTD5).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_TOKEN = "plan_pre_answers.v1"
SCHEMA_FAMILY = "plan_pre_answers"

# The two admitted decision fields and their declared enums (R15). The backend enum is
# the one Phase 5.2 records (the plan-doc contract, saga-spec §14); the destination
# enum is the one Phase 5.1 asks (DESTINATIONS, saga-spec §4).
BACKEND_ENUM = ("inline",)
DESTINATION_ENUM = ("plan-only", "pr", "merge", "nonprod-deploy")
DECISION_ENUMS: dict[str, tuple[str, ...]] = {
    "backend": BACKEND_ENUM,
    "destination": DESTINATION_ENUM,
}
DECISION_FIELDS: tuple[str, ...] = tuple(DECISION_ENUMS)

# Operator ruling (review F03): inline is the only backend the carrier may apply
# automatically. Both richer backends are legal plan-document values, but they require
# explicit operator invocation — the carrier stops and surfaces instead of applying.
CARRIER_AUTO_APPLY_BACKENDS = ("inline",)
CARRIER_INVOCATION_ONLY_BACKENDS = tuple(
    b for b in BACKEND_ENUM if b not in CARRIER_AUTO_APPLY_BACKENDS
)

# Envelope keys that are not decision fields.
ENVELOPE_KEYS = frozenset({"schema", "caller", *DECISION_FIELDS})

_FENCE_RE = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)

# A block is carrier-shaped when its raw text names the ``plan_pre_answers`` family on a
# token boundary, case-insensitively — the same membership test ``_is_family_schema``
# performs on a parsed token (cycle-2 C03/P02/S01). Malformed-carrier stops are gated on
# this, so an unrelated malformed JSON example can never halt a run that carries no
# carrier; it is ignored exactly as a foreign schema already is.
_CARRIER_SHAPE_RE = re.compile(r"\bplan_pre_answers\b", re.IGNORECASE)


def _is_carrier_shaped(block: str) -> bool:
    return _CARRIER_SHAPE_RE.search(block) is not None


# Echoed caller-supplied values are truncated to a fixed width so a refusal message can
# never be inflated by unbounded input (review F24).
_ECHO_LIMIT = 40


class _DuplicateKeyError(ValueError):
    """A JSON object repeated a key (review F15)."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    if duplicates:
        raise _DuplicateKeyError(", ".join(sorted(duplicates)))
    return dict(pairs)


def _echo(value: Any) -> str:
    text = repr(value)
    if len(text) > _ECHO_LIMIT:
        return text[:_ECHO_LIMIT] + "…"
    return text


def _is_family_schema(schema: Any) -> bool:
    """Case-insensitive family match on a token boundary (review F23).

    ``plan_pre_answers.v2`` and ``PLAN_PRE_ANSWERS.v1`` are inside the family (refused
    whole downstream); ``plan_pre_answersx`` is a different name entirely (foreign,
    ignored — not a carrier).
    """
    if not isinstance(schema, str):
        return False
    normalized = schema.lower()
    return normalized == SCHEMA_FAMILY or normalized.startswith(SCHEMA_FAMILY + ".")


@dataclass(frozen=True)
class PreAnswerOutcome:
    """The result of one carrier evaluation.

    ``applied`` — decision field -> supplied value; each is narrated with ``caller``.
    ``omitted`` — decision fields left to the normal adaptive conversation: the ones
    the carrier omitted, or all of them when there is no carrier at all (review F36).
    Absence is never an error (R17).
    ``stop`` — when not None, the run stops and surfaces this reason; nothing is
    applied and nothing becomes a silent default (R18, R19).
    ``caller`` — the supplying capability for the narration (R16); None when the
    carrier supplied no caller.
    """

    applied: Mapping[str, str]
    omitted: tuple[str, ...]
    stop: str | None
    caller: str | None


def scan_carriers(invocation_text: str) -> tuple[list[dict[str, Any]], str | None]:
    """All candidate carriers in the invocation text, plus any carrier-discipline stop.

    A candidate is a fenced block whose info string is exactly ``json`` (review F08)
    and whose payload parses to an object declaring a ``plan_pre_answers`` family
    schema. Stops are returned instead of raising, and each is a distinct verdict:

    * a ``json``-fenced block that fails to parse is a malformed carrier (review F30) —
      indistinguishable from no carrier before that fix, a stop now — but only when the
      block is carrier-shaped; an unrelated malformed JSON example is prose, ignored
      (cycle-2 C03/P02/S01);
    * duplicate JSON keys stop rather than silently applying the last value (F15),
      under the same carrier-shape gate;
    * more than one carrier stops rather than letting the first win silently (F08a).
    """
    candidates: list[dict[str, Any]] = []
    for info, block in _FENCE_RE.findall(invocation_text):
        if info.strip() != "json":
            continue
        try:
            parsed = json.loads(block, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateKeyError as exc:
            if not _is_carrier_shaped(block):
                continue  # unrelated prose with a repeated key — not a carrier
            return [], (
                f"pre-answer carrier refused: duplicate JSON keys ({_echo(str(exc))}) — "
                "the last value must not silently win"
            )
        except json.JSONDecodeError:
            if not _is_carrier_shaped(block):
                continue  # an illustrative or truncated JSON example — not a carrier
            return [], (
                "pre-answer carrier refused: a ```json block in the invocation text "
                "failed to parse — a malformed carrier is a stop, not an absence"
            )
        if not isinstance(parsed, dict):
            continue
        if _is_family_schema(parsed.get("schema")):
            candidates.append(parsed)
    if len(candidates) > 1:
        return [], (
            f"pre-answer carrier refused: {len(candidates)} carriers present — at most "
            "one is admitted; conflicting carriers must never be resolved silently"
        )
    return candidates, None


def extract_carrier(invocation_text: str) -> dict[str, Any] | None:
    """The single admitted carrier in the invocation text, if any.

    Retained for callers that want the raw candidate; ``evaluate`` is the contract
    surface (it also returns the carrier-discipline stops).
    """
    candidates, _ = scan_carriers(invocation_text)
    return candidates[0] if candidates else None


def evaluate_carrier(
    carrier: Mapping[str, Any], established: Mapping[str, str] | None = None
) -> PreAnswerOutcome:
    """Validate one carrier object; return applied values, omissions, and any stop.

    A stop is a whole-carrier verdict: nothing is applied, so an invalid or
    contradictory value can never become a silent default and a refused carrier is
    never partially applied (R18, R19).
    """
    schema = carrier.get("schema")
    if schema != SCHEMA_TOKEN:
        return PreAnswerOutcome(
            applied={},
            omitted=(),
            stop=(
                f"pre-answer carrier refused whole: unrecognised schema token {_echo(schema)} "
                f"(expected {_echo(SCHEMA_TOKEN)}); no field was applied"
            ),
            caller=None,
        )

    unknown = sorted(set(carrier) - ENVELOPE_KEYS)
    if unknown:
        listed = ", ".join(f"`{key}`" for key in unknown)
        verb = "is" if len(unknown) == 1 else "are"
        return PreAnswerOutcome(
            applied={},
            omitted=(),
            stop=(
                f"pre-answer carrier refused: {listed} {verb} not admitted — exactly "
                "`backend` and `destination` are the decision fields (`caller` is "
                "envelope metadata, not a decision field)"
            ),
            caller=None,
        )

    caller = carrier.get("caller")
    if caller is not None and not isinstance(caller, str):
        return PreAnswerOutcome(
            applied={},
            omitted=(),
            stop="pre-answer carrier refused: `caller` must be a string naming the "
            "supplying capability",
            caller=None,
        )

    established = established or {}
    applied: dict[str, str] = {}
    for field_name, enum in DECISION_ENUMS.items():
        if field_name not in carrier:
            continue
        value = carrier[field_name]
        if not isinstance(value, str) or value not in enum:
            return PreAnswerOutcome(
                applied={},
                omitted=(),
                stop=(
                    f"pre-answer conflict: `{field_name}` value {_echo(value)} is not one of "
                    f"{' | '.join(enum)}; nothing was applied — surface the conflict, "
                    "never a silent default"
                ),
                caller=None,
            )
        if field_name == "backend" and value in CARRIER_INVOCATION_ONLY_BACKENDS:
            # Operator ruling (review F03): legal plan value, but never automatically
            # applicable from a carrier — it requires explicit operator invocation.
            return PreAnswerOutcome(
                applied={},
                omitted=(),
                stop=(
                    f"pre-answer stop: `{field_name}` value {_echo(value)} is legal in a "
                    "plan document but requires explicit operator invocation — the carrier "
                    "path never applies it automatically; surface it and let the operator "
                    "confirm"
                ),
                caller=None,
            )
        settled = established.get(field_name)
        if settled is not None and settled != value:
            return PreAnswerOutcome(
                applied={},
                omitted=(),
                stop=(
                    f"pre-answer conflict: supplied `{field_name}` value {_echo(value)} "
                    f"contradicts the already-established value {_echo(settled)}; neither "
                    "side is preferred — surface the conflict"
                ),
                caller=None,
            )
        applied[field_name] = value

    omitted = tuple(name for name in DECISION_FIELDS if name not in carrier)
    return PreAnswerOutcome(applied=applied, omitted=omitted, stop=None, caller=caller)


def evaluate(
    invocation_text: str, established: Mapping[str, str] | None = None
) -> PreAnswerOutcome:
    """Evaluate the carrier in one ``/plan`` invocation text, if any (Phase 0.7 intake).

    No carrier means nothing applied and no stop (R20); both decision fields simply
    follow the normal adaptive conversation (review F36). Carrier-discipline failures
    (malformed JSON, duplicate keys, multiple carriers) are stops, not absences.
    """
    candidates, stop = scan_carriers(invocation_text)
    if stop is not None:
        return PreAnswerOutcome(applied={}, omitted=(), stop=stop, caller=None)
    if not candidates:
        return PreAnswerOutcome(applied={}, omitted=DECISION_FIELDS, stop=None, caller=None)
    return evaluate_carrier(candidates[0], established)


def main(argv: Sequence[str] | None = None) -> int:
    """Runnable entry point (review F02u): stdin invocation text, JSON outcome on stdout.

    Exit 0 — no stop (the carrier applied cleanly, or there was no carrier). Exit 2 —
    the outcome carries a ``stop`` and the caller must surface it, never continue
    silently; an unreadable ``--invocation-file`` also exits 2 with the same JSON shape
    and a ``stop`` naming the unreadable path (cycle-2 U03/C10). A malformed command
    line exits 2 through argparse with a usage message and NO JSON — that, too, is a
    stop, never a clean apply.
    """
    parser = argparse.ArgumentParser(
        prog="plan_pre_answers.py",
        description="Evaluate a plan_pre_answers.v1 carrier in /plan invocation text.",
    )
    parser.add_argument(
        "--invocation-file",
        type=Path,
        default=None,
        help="read the invocation text from this file instead of stdin",
    )
    parser.add_argument(
        "--established",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help=(
            "repeatable; a decision already established in this thread "
            "(backend=<value> or destination=<value>). A carrier value contradicting "
            "it stops (cycle-2 C04/U04)."
        ),
    )
    args = parser.parse_args(argv)
    established: dict[str, str] = {}
    for entry in args.established:
        field, separator, value = entry.partition("=")
        if not separator or not value or field not in DECISION_ENUMS:
            parser.error(
                "--established takes FIELD=VALUE with FIELD one of "
                f"{' | '.join(DECISION_FIELDS)}; got {_echo(entry)}"
            )
        established[field] = value
    try:
        if args.invocation_file is not None:
            text = args.invocation_file.read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
    except (OSError, UnicodeDecodeError) as exc:
        # The run stops on the same JSON shape every other stop uses (cycle-2 U03/C10):
        # an unreadable invocation file must surface, never escape as a bare traceback.
        detail = getattr(exc, "strerror", None) or str(exc)
        outcome = PreAnswerOutcome(
            applied={},
            omitted=(),
            stop=(
                f"pre-answer validator stopped: the invocation file {args.invocation_file} "
                f"is unreadable ({_echo(detail)}) — surface this, never continue silently"
            ),
            caller=None,
        )
    else:
        outcome = evaluate(text, established or None)
    print(
        json.dumps(
            {
                "schema": SCHEMA_TOKEN,
                "applied": dict(outcome.applied),
                "omitted": list(outcome.omitted),
                "stop": outcome.stop,
                "caller": outcome.caller,
            },
            indent=2,
        )
    )
    return 2 if outcome.stop is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
