#!/usr/bin/env python3
"""The /qa strategy catalogue — selection, preflight, drivers, evidence and the verdict (#1039).

`/qa` is the lifecycle's functional-test step: it runs after the release step deploys to the
non-production destination and decides whether the shipped thing actually works. It was a nine-way
risk router that improvised its checks and reported a language-model-scored health number. It is
now a catalogue of ten prescribed strategies held as data, and every decision in this module is
arithmetic:

1. **Selection is computed, never judged.** The repository profile's file patterns against the
   change's file list give the required set, and each entry records the pattern that selected it.
2. **The boundary filters the selection.** The three proof boundaries are a ladder, widest last:
   ``hermetic < branch-preview < non-production``. A run at boundary B selects every strategy whose
   boundary is B or narrower and records the rest as out-of-boundary — a selection fact, never a
   result and never proof debt.
3. **The advisory judgment may only widen.** The floor is computed BEFORE the client is called and
   the answer is unioned, never intersected. Its absence, its timeout and its error all degrade to
   the declared set; no run fails because a judgment was unavailable.
4. **The preflight refuses whole or not at all.** Over the profile's ceiling, or missing a
   credential the operator holds, zero drivers run. Running the affordable subset and reporting a
   partial pass is the failure this design exists to remove.
5. **A driver returns one of three results.** ``passed``, ``failed``, ``blocked``. There is no
   fourth value and no silent skip. A driver that cannot start is ``blocked``, never an exception
   that ends the run.
6. **The verdict is counted, not scored.** No model assigns a severity here and nothing is weighted.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | the verdict is ``pass`` or ``pass-with-proof-debt`` |
| 1 | an internal error |
| 2 | a refusal — the preflight refused the whole selection, the profile proves nothing, or there is no profile |
| 3 | an unknown record version |
| 4 | the verdict is ``fail`` |
| 5 | a required strategy is ``blocked``; the run stops for the operator |

4 and 5 are separate on purpose: a failure re-enters the build loop and a required block does not.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import json
import os
import re
import shlex
import subprocess  # nosec B404
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import run_record  # noqa: E402  (after the sys.path shim, by design)

# ---------------------------------------------------------------------------
# Constants.
# ---------------------------------------------------------------------------

CATALOGUE_PATH = _SCRIPTS.parent / "references" / "qa-catalogue.yaml"
ENVELOPE_SCHEMA_PATH = _SCRIPTS.parent / "references" / "qa-envelope.schema.json"
PROFILE_SCHEMA_PATH = _SCRIPTS.parent / "references" / "qa-profile.schema.json"

#: The tracked per-repository profile. The qa block is an optional key inside it rather than a
#: file of its own, following ``branch_preview_command``'s precedent: an optional key leaves every
#: existing profile valid and does not move the ``repository_profile.v1`` token.
PROFILE_FILENAME = ".saga-profile.json"
PROFILE_KEY = "qa"
PROFILE_SCHEMA = "qa_profile.v1"
CATALOGUE_SCHEMA = "qa_catalogue.v1"
ENVELOPE_SCHEMA = "qa_evidence_envelope.v1"

#: The run record's top-level extension point for this step. The record preserves an unknown
#: top-level key unchanged across a read and a write and reports it by name, which is the
#: documented extension point; a unit row is the wrong home, because a functional test is a
#: property of the run after the merge rather than of one unit's working state.
RECORD_KEY = "qa"

#: The proof boundaries, narrowest first. Membership in this tuple IS the ladder.
BOUNDARIES: tuple[str, ...] = ("hermetic", "branch-preview", "non-production")
DEFAULT_BOUNDARY = "non-production"

RESULT_PASSED = "passed"
RESULT_FAILED = "failed"
RESULT_BLOCKED = "blocked"
RESULTS: tuple[str, ...] = (RESULT_PASSED, RESULT_FAILED, RESULT_BLOCKED)

VERDICT_PASS = "pass"
VERDICT_PROOF_DEBT = "pass-with-proof-debt"
VERDICT_FAIL = "fail"
VERDICT_BLOCKED = "blocked"

ROUTE_CLOSE = "close"
ROUTE_BUILD_LOOP = "build-loop"
ROUTE_OPERATOR = "operator-stop"

REASON_OUT_OF_BOUNDARY = "out-of-boundary"
REASON_JUDGMENT = "widened-by-judgment"

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3
EXIT_FAIL = 4
EXIT_OPERATOR_STOP = 5

DEFAULT_TIMEOUT_SECONDS = 900

#: The redaction floor this module adds on top of fleet-core's pattern set. The CAMPPS driver
#: model redacts at the driver boundary, before an envelope exists, and these are the two shapes
#: its own set names that a generic secret-word rule does not catch on its own.
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]{8,}=*")
_AUTH_HEADER = re.compile(r"(?i)\b(authorization|x-api-key|x-auth-token)\s*[:=]\s*\S+")
REDACTED = "[REDACTED]"


class QaStrategiesError(ValueError):
    """Something the caller handed in is wrong, and the message names what."""


class ProfileRefusalError(QaStrategiesError):
    """The profile is absent or proves nothing. A refusal, never an empty selection that passes."""


# ---------------------------------------------------------------------------
# Redaction — at the driver boundary, before an envelope exists.
# ---------------------------------------------------------------------------


def _fleet_redactor() -> Callable[[str], str] | None:
    """fleet-core's ``redact_text``, or ``None`` when fleet-core cannot be resolved.

    It carries secret-word patterns, hash runs and an entropy rule that are already in production
    use, so it is the floor rather than a fresh pattern set. Its absence degrades to the local
    patterns below: a driver still redacts, it just redacts less.
    """
    try:
        import bundled_fleet  # noqa: PLC0415

        client = bundled_fleet.load("typesafe_client")
    except Exception:  # noqa: BLE001 - any resolution failure is a degradation, never a crash
        return None
    redactor = getattr(client, "redact_text", None)
    return redactor if callable(redactor) else None


def redact(text: str) -> str:
    """Remove secrets from *text*. Called inside a driver, before the envelope exists."""
    if not text:
        return text
    redactor = _fleet_redactor()
    if redactor is not None:
        # A redactor that raises must not cost the local patterns below.
        with contextlib.suppress(Exception):
            text = redactor(text)
    text = _BEARER.sub(REDACTED, text)
    text = _AUTH_HEADER.sub(REDACTED, text)
    return text


def redact_value(value: Any) -> Any:
    """Redact every string reachable in *value*, whatever shape it has."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# The catalogue.
# ---------------------------------------------------------------------------

#: Every column a catalogue row must carry. A row missing one is refused naming both.
ROW_REQUIRED: tuple[str, ...] = (
    "id",
    "situation",
    "tool",
    "invocation",
    "file_patterns",
    "required_evidence",
    "proof_boundary",
    "threshold",
    "may_be_optional",
    "cost_estimate",
)


@dataclass(frozen=True)
class Strategy:
    """One catalogue row."""

    id: str
    situation: str
    tool: str
    invocation: str
    file_patterns: tuple[str, ...]
    required_evidence: tuple[str, ...]
    proof_boundary: str
    threshold: str
    may_be_optional: bool
    driver: str | None
    no_driver_reason: str | None
    revisit_when: str | None
    cost_estimate: dict[str, Any]


@dataclass(frozen=True)
class Catalogue:
    """The ten rows plus the judgment's declared band."""

    strategies: dict[str, Strategy]
    judgment: dict[str, Any]
    path: Path

    @property
    def act_band(self) -> float:
        return float(self.judgment.get("act_band", 0.6))

    @property
    def verb(self) -> str:
        return str(self.judgment.get("verb", "qa-strategies"))


def load_catalogue(path: Path | None = None) -> Catalogue:
    """Read and validate the catalogue. A malformed row is refused naming the row and the column."""
    target = path or CATALOGUE_PATH
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise QaStrategiesError(f"the catalogue is missing at {target}") from exc
    except yaml.YAMLError as exc:
        raise QaStrategiesError(f"the catalogue at {target} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise QaStrategiesError(f"the catalogue at {target} is not a mapping")
    if raw.get("schema") != CATALOGUE_SCHEMA:
        raise QaStrategiesError(
            f"the catalogue at {target} declares schema {raw.get('schema')!r}; "
            f"this module reads {CATALOGUE_SCHEMA!r}"
        )
    rows = raw.get("strategies")
    if not isinstance(rows, list) or not rows:
        raise QaStrategiesError(f"the catalogue at {target} carries no strategies")

    strategies: dict[str, Strategy] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise QaStrategiesError(f"catalogue row {index} is not a mapping")
        identifier = str(row.get("id") or f"row-{index}")
        for column in ROW_REQUIRED:
            if row.get(column) in (None, ""):
                raise QaStrategiesError(
                    f"catalogue row {identifier!r} is missing the column {column!r}"
                )
        boundary = str(row["proof_boundary"])
        if boundary not in BOUNDARIES:
            raise QaStrategiesError(
                f"catalogue row {identifier!r} declares proof boundary {boundary!r}; "
                f"the ladder is: {', '.join(BOUNDARIES)}"
            )
        driver = row.get("driver")
        if driver is None and not str(row.get("no_driver_reason") or "").strip():
            raise QaStrategiesError(
                f"catalogue row {identifier!r} ships no driver and names no reason; a strategy "
                "without a driver says out loud why it cannot run"
            )
        if identifier in strategies:
            raise QaStrategiesError(f"catalogue row {identifier!r} appears more than once")
        strategies[identifier] = Strategy(
            id=identifier,
            situation=str(row["situation"]),
            tool=str(row["tool"]),
            invocation=str(row["invocation"]),
            file_patterns=tuple(str(p) for p in row["file_patterns"]),
            required_evidence=tuple(str(e) for e in row["required_evidence"]),
            proof_boundary=boundary,
            threshold=str(row["threshold"]),
            may_be_optional=bool(row["may_be_optional"]),
            driver=str(driver) if driver else None,
            no_driver_reason=(
                str(row["no_driver_reason"]) if row.get("no_driver_reason") else None
            ),
            revisit_when=str(row["revisit_when"]) if row.get("revisit_when") else None,
            cost_estimate=dict(row["cost_estimate"]),
        )

    judgment = raw.get("judgment")
    if not isinstance(judgment, dict):
        raise QaStrategiesError(f"the catalogue at {target} declares no judgment block")
    band = judgment.get("act_band")
    if not isinstance(band, (int, float)) or isinstance(band, bool) or not 0.0 < float(band) < 1.0:
        raise QaStrategiesError(
            f"the catalogue's act band is {band!r}; it is a probability strictly between 0 and 1"
        )
    return Catalogue(strategies=strategies, judgment=dict(judgment), path=target)


# ---------------------------------------------------------------------------
# The profile.
# ---------------------------------------------------------------------------


def load_profile(
    repo_root: Path, *, profile_path: Path | None = None, catalogue: Catalogue | None = None
) -> dict[str, Any]:
    """The repository's ``qa`` block, or a refusal naming the file and the missing key.

    A missing profile is never an empty selection that reports a pass, and neither is a profile
    whose strategies are all optional: such a profile would let a run prove nothing and still say
    so cheerfully, which is the failure this design exists to remove.
    """
    target = profile_path or (repo_root / PROFILE_FILENAME)
    if not target.is_file():
        raise ProfileRefusalError(
            f"there is no repository profile at {target}, so no strategy is declared and nothing "
            "can be proved; the run is blocked rather than empty"
        )
    try:
        whole = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileRefusalError(
            f"the repository profile at {target} is not valid JSON: {exc}"
        ) from exc
    block = whole.get(PROFILE_KEY) if isinstance(whole, dict) else None
    if not isinstance(block, dict):
        raise ProfileRefusalError(
            f"the repository profile at {target} carries no {PROFILE_KEY!r} key, so no strategy "
            "is declared for this repository; the run is blocked rather than empty"
        )
    if block.get("schema") != PROFILE_SCHEMA:
        raise ProfileRefusalError(
            f"the {PROFILE_KEY!r} block of {target} declares schema {block.get('schema')!r}; "
            f"this module reads {PROFILE_SCHEMA!r}"
        )
    strategies = block.get("strategies")
    if not isinstance(strategies, dict) or not strategies:
        raise ProfileRefusalError(
            f"the {PROFILE_KEY!r} block of {target} declares no strategies; a repository that "
            "declares nothing proves nothing"
        )
    if not any(bool(entry.get("required")) for entry in strategies.values()):
        raise ProfileRefusalError(
            f"every strategy in the {PROFILE_KEY!r} block of {target} is optional, so a run could "
            "report a pass having proved nothing; at least one strategy must be required"
        )
    ceiling = block.get("ceiling")
    if not isinstance(ceiling, dict) or "max_duration_seconds" not in ceiling:
        raise ProfileRefusalError(
            f"the {PROFILE_KEY!r} block of {target} declares no ceiling; an absent ceiling is not "
            "an unlimited one, so the run is refused rather than assuming a budget"
        )
    if catalogue is not None:
        unknown = sorted(set(strategies) - set(catalogue.strategies))
        if unknown:
            raise ProfileRefusalError(
                f"the {PROFILE_KEY!r} block of {target} declares strategies the catalogue does not "
                f"carry: {', '.join(unknown)}"
            )
    return block


# ---------------------------------------------------------------------------
# Selection.
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    """One selected strategy and the reason it was selected."""

    strategy_id: str
    required: bool
    reason: str
    source: str = "profile"

    def as_record(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "required": self.required,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class Selection:
    """What will run, what the boundary excluded, and what the judgment contributed."""

    boundary: str
    entries: list[Entry] = field(default_factory=list)
    out_of_boundary: list[dict[str, Any]] = field(default_factory=list)
    judgment: dict[str, Any] = field(default_factory=dict)

    @property
    def ids(self) -> list[str]:
        return [entry.strategy_id for entry in self.entries]

    @property
    def required_ids(self) -> list[str]:
        return [entry.strategy_id for entry in self.entries if entry.required]

    def as_record(self) -> dict[str, Any]:
        return {
            "boundary": self.boundary,
            "entries": [entry.as_record() for entry in self.entries],
            "out_of_boundary": list(self.out_of_boundary),
            "judgment": dict(self.judgment),
        }


def boundary_rank(boundary: str) -> int:
    """Where *boundary* sits on the ladder. Raises on a rung that is not one."""
    try:
        return BOUNDARIES.index(boundary)
    except ValueError as exc:
        raise QaStrategiesError(
            f"{boundary!r} is not a proof boundary; the ladder is: {', '.join(BOUNDARIES)}"
        ) from exc


def within_boundary(strategy_boundary: str, run_boundary: str) -> bool:
    """True when a run at *run_boundary* can prove something at *strategy_boundary*."""
    return boundary_rank(strategy_boundary) <= boundary_rank(run_boundary)


def _patterns_for(strategy: Strategy, entry: Mapping[str, Any]) -> tuple[str, ...]:
    declared = entry.get("file_patterns")
    if isinstance(declared, list) and declared:
        return tuple(str(pattern) for pattern in declared)
    return strategy.file_patterns


def _matching_pattern(patterns: Sequence[str], changed_files: Sequence[str]) -> tuple[str, str]:
    """The first ``(pattern, file)`` pair that matches, or two empty strings."""
    for pattern in patterns:
        for path in changed_files:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"*/{pattern}"):
                return pattern, path
    return "", ""


def declared_selection(
    catalogue: Catalogue,
    profile: Mapping[str, Any],
    changed_files: Sequence[str],
    *,
    boundary: str = DEFAULT_BOUNDARY,
) -> Selection:
    """The floor: what the profile's patterns require, filtered by the boundary ladder.

    No judgment is called here, and none is consulted. This runs FIRST and completely, which is
    what makes the judgment's contribution a union rather than a negotiation.
    """
    boundary_rank(boundary)  # refuse an unknown rung before any work
    selection = Selection(boundary=boundary)
    declared: Mapping[str, Any] = profile.get("strategies", {})
    for strategy_id in sorted(declared):
        entry = declared[strategy_id]
        strategy = catalogue.strategies.get(strategy_id)
        if strategy is None:
            continue
        required = bool(entry.get("required"))
        if not within_boundary(strategy.proof_boundary, boundary):
            selection.out_of_boundary.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_boundary": strategy.proof_boundary,
                    "run_boundary": boundary,
                    "reason": REASON_OUT_OF_BOUNDARY,
                    "detail": (
                        f"{strategy_id} proves at {strategy.proof_boundary}, which a run at "
                        f"{boundary} cannot reach; this is a selection fact, not proof debt"
                    ),
                }
            )
            continue
        patterns = _patterns_for(strategy, entry)
        pattern, path = _matching_pattern(patterns, changed_files)
        if not pattern:
            if required:
                selection.entries.append(
                    Entry(
                        strategy_id=strategy_id,
                        required=True,
                        reason=(
                            "the profile marks this strategy required, so it runs whatever the "
                            "change touched"
                        ),
                    )
                )
            continue
        selection.entries.append(
            Entry(
                strategy_id=strategy_id,
                required=required,
                reason=f"the profile pattern {pattern!r} matched the changed file {path!r}",
            )
        )
    return selection


def widen_selection(
    selection: Selection,
    catalogue: Catalogue,
    profile: Mapping[str, Any],
    *,
    changed_files: Sequence[str],
    change_summary: str = "",
    widen: Callable[..., Any] | None = None,
) -> Selection:
    """Ask the advisory judgment and UNION its answer with the floor. Never an intersection.

    Every failure mode of the client — absent, raising, timing out, a non-ok status, an answer
    with no verdict — returns the floor unchanged with the reason recorded. No run fails because
    a judgment was unavailable.
    """
    declared: Mapping[str, Any] = profile.get("strategies", {})
    candidates = [
        strategy_id
        for strategy_id, strategy in sorted(catalogue.strategies.items())
        if strategy_id in declared and within_boundary(strategy.proof_boundary, selection.boundary)
    ]
    if not candidates:
        selection.judgment = {"asked": False, "note": "no candidate strategy at this boundary"}
        return selection

    floors = {strategy_id: strategy_id in selection.ids for strategy_id in candidates}
    caller = widen or _fleet_widen()
    if caller is None:
        selection.judgment = {
            "asked": False,
            "note": "fleet-core's widen-only union could not be resolved; the declared set stands",
            "threshold": catalogue.act_band,
        }
        return selection

    state = {
        "change": {"files": list(changed_files)[:200], "summary": change_summary},
        "strategies": {
            strategy_id: catalogue.strategies[strategy_id].situation for strategy_id in candidates
        },
    }
    try:
        result = caller(
            state,
            catalogue.verb,
            floors,
            decision_prefix=str(catalogue.judgment.get("decision_prefix", "qa-strategies")),
            threshold=catalogue.act_band,
            timeout=float(catalogue.judgment.get("timeout_seconds", 20)),
        )
    except Exception as exc:  # noqa: BLE001 - the floor must survive any judgment failure
        selection.judgment = {
            "asked": False,
            "note": f"the judgment raised {type(exc).__name__}; the declared set stands",
            "threshold": catalogue.act_band,
        }
        return selection

    unions: Mapping[str, bool] = result.unions()
    added: list[str] = []
    for strategy_id, union in sorted(unions.items()):
        if union and strategy_id not in selection.ids:
            entry = declared.get(strategy_id, {})
            selection.entries.append(
                Entry(
                    strategy_id=strategy_id,
                    required=bool(entry.get("required")),
                    reason=(
                        "the advisory judgment scored this strategy at or above the catalogue's "
                        f"declared act band of {catalogue.act_band}"
                    ),
                    source=REASON_JUDGMENT,
                )
            )
            added.append(strategy_id)
    record = result.to_dict() if hasattr(result, "to_dict") else {}
    record.update({"asked": bool(getattr(result, "asked", False)), "added": added})
    selection.judgment = record
    return selection


def _fleet_widen() -> Callable[..., Any] | None:
    """fleet-core's ``jev_widen.widen``, or ``None`` when it cannot be resolved."""
    try:
        import bundled_fleet  # noqa: PLC0415

        module = bundled_fleet.load("jev_widen")
    except Exception:  # noqa: BLE001 - any resolution failure degrades to the floor
        return None
    widen = getattr(module, "widen", None)
    return widen if callable(widen) else None


# ---------------------------------------------------------------------------
# Preflight.
# ---------------------------------------------------------------------------


def estimate(selection: Selection, catalogue: Catalogue, profile: Mapping[str, Any]) -> dict:
    """The selection's total duration and direct cost, profile overrides winning."""
    declared: Mapping[str, Any] = profile.get("strategies", {})
    duration = 0.0
    cost = 0.0
    for strategy_id in selection.ids:
        row = catalogue.strategies[strategy_id].cost_estimate
        override = declared.get(strategy_id, {}).get("cost_estimate") or {}
        duration += float(override.get("duration_seconds", row.get("duration_seconds", 0)))
        cost += float(override.get("direct_cost", row.get("direct_cost", 0)))
    return {"duration_seconds": duration, "direct_cost": cost}


def preflight(
    selection: Selection,
    catalogue: Catalogue,
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Decide whether the WHOLE selection may run. It never trims to what fits.

    A missing secret handle refuses the whole selection, because a credential is the operator's
    boundary. A missing environment VARIABLE does not: that is one strategy's ``blocked`` result
    at dispatch, because a run that can still prove four of five things should prove them and say
    which one it could not.
    """
    env = dict(environ if environ is not None else os.environ)
    declared: Mapping[str, Any] = profile.get("strategies", {})
    totals = estimate(selection, catalogue, profile)
    ceiling = profile.get("ceiling") or {}
    max_duration = float(ceiling.get("max_duration_seconds", 0))
    max_cost = float(ceiling.get("max_direct_cost", 0))

    missing_handles: list[str] = []
    for strategy_id in selection.ids:
        for handle in declared.get(strategy_id, {}).get("secret_handles") or []:
            if not env.get(str(handle)):
                missing_handles.append(f"{strategy_id}:{handle}")
    if missing_handles:
        return {
            "refused": True,
            "estimate": totals,
            "ceiling": {"max_duration_seconds": max_duration, "max_direct_cost": max_cost},
            "reason": (
                "the whole selection is refused: these operator-held credentials are not "
                f"available to this run — {', '.join(sorted(missing_handles))}. A credential is "
                "an approval boundary, so the run asks rather than proving part of the work"
            ),
        }
    if totals["duration_seconds"] > max_duration or totals["direct_cost"] > max_cost:
        return {
            "refused": True,
            "estimate": totals,
            "ceiling": {"max_duration_seconds": max_duration, "max_direct_cost": max_cost},
            "reason": (
                f"the whole selection is refused: it estimates {totals['duration_seconds']:.0f} "
                f"seconds and {totals['direct_cost']:.2f} in direct cost against a ceiling of "
                f"{max_duration:.0f} seconds and {max_cost:.2f}. The affordable subset is never "
                "run on its own, because a partial run reported as a pass is the failure this "
                "step exists to remove"
            ),
        }
    return {
        "refused": False,
        "estimate": totals,
        "ceiling": {"max_duration_seconds": max_duration, "max_direct_cost": max_cost},
        "reason": "",
    }


# ---------------------------------------------------------------------------
# The envelope.
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _envelope_schema() -> dict[str, Any]:
    loaded = json.loads(ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise QaStrategiesError(f"the envelope schema at {ENVELOPE_SCHEMA_PATH} is not an object")
    return loaded


_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "number": (int, float),
    "array": list,
    "object": dict,
}


def validate_envelope(envelope: Mapping[str, Any]) -> list[str]:
    """Check *envelope* against the schema FILE and return the problems, empty when it validates.

    Hand-written rather than ``jsonschema``, because ``jsonschema`` is a development dependency:
    importing it here would make the functional-test step fail on a machine that installed the
    package without its dev extra. The schema file is still the single source — the required list
    and the declared types are READ from it, and the tests validate the same envelopes with the
    real library, so this checker cannot quietly diverge from what it claims to enforce.
    """
    schema = _envelope_schema()
    problems: list[str] = []
    properties: Mapping[str, Any] = schema.get("properties", {})
    for name in schema.get("required", []):
        if envelope.get(name) in (None, ""):
            problems.append(f"the envelope is missing the required field {name!r}")
    for name, value in envelope.items():
        declared = properties.get(name)
        if declared is None:
            problems.append(f"the envelope carries the unknown field {name!r}")
            continue
        expected = _JSON_TYPES.get(str(declared.get("type", "")))
        if expected is not None and not isinstance(value, expected):
            problems.append(
                f"the envelope's {name!r} is {type(value).__name__}, not {declared['type']}"
            )
            continue
        if "const" in declared and value != declared["const"]:
            problems.append(f"the envelope's {name!r} is {value!r}, not {declared['const']!r}")
        if "enum" in declared and value not in declared["enum"]:
            problems.append(
                f"the envelope's {name!r} is {value!r}; the schema allows "
                f"{', '.join(repr(option) for option in declared['enum'])}"
            )
    return problems


def make_envelope(
    strategy: Strategy,
    *,
    result: str,
    status_reason: str,
    environment: str,
    profile_revision: str,
    scenario_id: str = "",
    started_at: str = "",
    completed_at: str = "",
    duration_seconds: float = 0.0,
    evidence: Mapping[str, Any] | None = None,
    artifact_pointers: Sequence[str] = (),
    proof_mode: str = "automated",
) -> dict[str, Any]:
    """Build one redacted envelope. Every string that reaches it goes through the redactor."""
    if result not in RESULTS:
        raise QaStrategiesError(
            f"{result!r} is not a result; a strategy ends in one of: {', '.join(RESULTS)}"
        )
    now = _utc_now()
    envelope: dict[str, Any] = {
        "envelope_id": uuid.uuid4().hex,
        "schema": ENVELOPE_SCHEMA,
        "scenario_id": scenario_id or f"{strategy.id}-default",
        "scenario_version": "1",
        "profile_revision": profile_revision or "unversioned",
        "environment": environment,
        "strategy_id": strategy.id,
        "proof_boundary": strategy.proof_boundary,
        "proof_mode": proof_mode,
        "result": result,
        "status_reason": redact(status_reason) or "no reason recorded",
        "started_at": started_at or now,
        "completed_at": completed_at or now,
        "duration_seconds": round(float(duration_seconds), 3),
        "estimated_cost": float(strategy.cost_estimate.get("direct_cost", 0.0)),
        "observed_cost": 0.0,
        "privacy_attestation": (
            "captured output was passed through the driver-boundary redactor before this envelope "
            "existed; artifact pointers carry paths, never captured values"
        ),
        "artifact_pointers": [str(pointer) for pointer in artifact_pointers],
    }
    if evidence:
        envelope["evidence"] = redact_value(dict(evidence))
    return envelope


# ---------------------------------------------------------------------------
# Drivers.
# ---------------------------------------------------------------------------

#: A runner takes an argument vector, a timeout and a working directory and returns
#: ``(exit_code, output)``. It raises ``FileNotFoundError`` when the program is absent and
#: ``subprocess.TimeoutExpired`` on a timeout, which is what the real one does and therefore what
#: a fake must do.
Runner = Callable[[Sequence[str], int, "Path | None"], "tuple[int, str]"]


def subprocess_runner(
    argv: Sequence[str], timeout: int, cwd: Path | None = None
) -> tuple[int, str]:
    """Run *argv* with no shell. The profile's entries are data, and data never reaches a shell."""
    proc = subprocess.run(  # nosec B603  (shell=False, argv from a tracked config, never a string)
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


@dataclass
class DriverContext:
    """Everything a driver is given. A driver reads this and nothing else."""

    strategy: Strategy
    entry: dict[str, Any]
    environment: dict[str, Any]
    profile_revision: str
    repo_root: Path
    runner: Runner
    environ: dict[str, str]
    timeout: int = DEFAULT_TIMEOUT_SECONDS


def _missing_environment(context: DriverContext) -> str:
    """The first declared environment variable that is unset, or an empty string."""
    for name in context.entry.get("environment_variables") or []:
        if not context.environ.get(str(name)):
            return str(name)
    return ""


def _run_commands(context: DriverContext) -> tuple[list[dict[str, Any]], bool]:
    """Run the profile's declared commands, returning their redacted results and whether all passed."""
    results: list[dict[str, Any]] = []
    ok = True
    for declared in context.entry.get("commands") or []:
        command = str(declared.get("command", ""))
        name = str(declared.get("name") or command)
        # ``shlex.split``, not ``str.split``: the profile's commands are written the way a person
        # writes them in a shell, so a quoted argument holding a space (``-k "not slow"``) is one
        # argument. ``str.split`` cut it into three and handed the program something it was never
        # asked to run, silently. ``build_loop.run_check`` has always parsed its baseline this way;
        # this is the same parsing for the same kind of value.
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            results.append(
                {
                    "name": name,
                    "command": command,
                    "exit_code": None,
                    "detail": redact(f"the command does not parse into an argument vector: {exc}"),
                }
            )
            ok = False
            continue
        started = time.monotonic()
        try:
            code, output = context.runner(argv, context.timeout, context.repo_root)
        except FileNotFoundError as exc:
            results.append(
                {"name": name, "command": command, "exit_code": None, "detail": redact(str(exc))}
            )
            ok = False
            continue
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": name,
                    "command": command,
                    "exit_code": None,
                    "detail": f"timed out after {context.timeout} seconds",
                }
            )
            ok = False
            continue
        results.append(
            {
                "name": name,
                "command": command,
                "exit_code": code,
                "duration_seconds": round(time.monotonic() - started, 3),
                "detail": redact(output)[-2000:],
            }
        )
        if code != 0:
            ok = False
    return results, ok


def driver_cli_smoke(context: DriverContext) -> dict[str, Any]:
    """Each declared invocation exits zero, and a declared version probe matches the marker."""
    missing = _missing_environment(context)
    if missing:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the environment variable {missing} is unset, so the command-line smoke could "
                "not run; nothing was proved and nothing is reported as passing"
            ),
            "evidence": {"missing_environment_variable": missing},
        }
    declared = context.entry.get("commands") or []
    if not declared:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                "the profile declares this strategy but names no command to run, so there is "
                "nothing to smoke"
            ),
            "evidence": {},
        }
    results, ok = _run_commands(context)
    marker = str(context.environment.get("version_marker") or "")
    version_ok = True
    if marker:
        version_ok = any(marker in str(item.get("detail", "")) for item in results)
    evidence = {
        "invocations": [item["command"] for item in results],
        "exit_codes": [item["exit_code"] for item in results],
        "reported_version": marker or "not declared",
    }
    if ok and version_ok:
        return {
            "result": RESULT_PASSED,
            "status_reason": f"{len(results)} declared invocation(s) exited zero",
            "evidence": evidence,
        }
    failed = [item["name"] for item in results if item.get("exit_code") != 0]
    reason = (
        f"these declared invocations did not exit zero: {', '.join(failed)}"
        if failed
        else f"the deployed version marker {marker!r} appeared in no invocation's output"
    )
    return {"result": RESULT_FAILED, "status_reason": reason, "evidence": evidence}


def driver_contract_check(context: DriverContext) -> dict[str, Any]:
    """The drift result is empty, or holds only the changes the profile marks permitted."""
    missing = _missing_environment(context)
    if missing:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the environment variable {missing} is unset, so the contract check could not run"
            ),
            "evidence": {"missing_environment_variable": missing},
        }
    declared = context.entry.get("commands") or []
    if not declared:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                "the profile declares this strategy but names no contract-diff command to run"
            ),
            "evidence": {},
        }
    results, ok = _run_commands(context)
    permitted = [str(item) for item in context.entry.get("permitted_changes") or []]
    evidence = {
        "baseline_reference": str(context.entry.get("entrypoint") or "profile-declared"),
        "drift_entries": [item.get("detail", "") for item in results if item.get("exit_code")],
        "permitted_changes": permitted,
    }
    if ok:
        return {
            "result": RESULT_PASSED,
            "status_reason": "the contract diff reported no drift",
            "evidence": evidence,
        }
    drift = " ".join(str(item.get("detail", "")) for item in results)
    if permitted and all(token in drift for token in permitted):
        return {
            "result": RESULT_PASSED,
            "status_reason": "the contract diff reported only changes the profile permits",
            "evidence": evidence,
        }
    return {
        "result": RESULT_FAILED,
        "status_reason": "the contract diff reported drift the profile does not permit",
        "evidence": evidence,
    }


def driver_deploy_boundary(context: DriverContext) -> dict[str, Any]:
    """The marker served at the edge equals the revision the release step recorded."""
    missing = _missing_environment(context)
    if missing:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the environment variable {missing} is unset, so the deployment boundary could "
                "not be probed"
            ),
            "evidence": {"missing_environment_variable": missing},
        }
    base_url = str(context.environment.get("base_url") or "")
    revision = str(context.environment.get("revision") or "")
    if not base_url or not revision:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                "the run record carries no base URL and deployed revision for this run, so there "
                "is no edge to probe; the release step records both when it deploys"
            ),
            "evidence": {"base_url": base_url, "recorded_revision": revision},
        }
    results, ok = _run_commands(context)
    served = " ".join(str(item.get("detail", "")) for item in results)
    evidence = {
        "base_url": base_url,
        "served_marker": redact(served)[-500:],
        "recorded_revision": revision,
    }
    if ok and revision in served:
        return {
            "result": RESULT_PASSED,
            "status_reason": f"the edge served the recorded revision {revision[:12]}",
            "evidence": evidence,
        }
    return {
        "result": RESULT_FAILED,
        "status_reason": (
            f"the edge did not serve the revision {revision[:12]} that the release step recorded"
        ),
        "evidence": evidence,
    }


def _plugin_roots(context: DriverContext) -> list[Path]:
    """Every installed plugin root, resolved rather than hard-coded.

    Two roots exist on this machine and a release has repeatedly updated one and not the other, so
    reading only the live one would have passed every such release. The roots are not the same on
    every machine, so they are resolved from the environment and the marketplace layout rather
    than written down.
    """
    roots: list[Path] = []
    override = context.environ.get("INFIQUETRA_PLUGIN_ROOTS")
    if override:
        return [Path(part).expanduser() for part in override.split(os.pathsep) if part]
    home = Path(context.environ.get("HOME", str(Path.home())))
    for candidate in (home / ".claude", home / ".claude-company"):
        marketplace = candidate / "plugins" / "marketplaces" / "infiquetra-plugins"
        if marketplace.is_dir():
            roots.append(marketplace)
    return roots


def _expected_surfaces(entry: Mapping[str, Any], plugin: str) -> list[str]:
    """The surfaces *plugin* must carry.

    Accepts either a flat list, which applies to every declared plugin, or a mapping keyed by
    plugin name, which is what a profile naming more than one plugin needs: ``commands/qa.md``
    belongs to exactly one of them, and demanding it of all of them reports a failure that is the
    profile's rather than the fleet's. The live run of 2026-09-20 reported exactly that.
    """
    declared = entry.get("expected_surfaces")
    if isinstance(declared, Mapping):
        return [str(surface) for surface in declared.get(plugin, [])]
    if isinstance(declared, list):
        return [str(surface) for surface in declared]
    return []


def driver_installed_surface(context: DriverContext) -> dict[str, Any]:
    """EVERY installed plugin root resolves the expected version and carries every surface."""
    expected = str(context.environment.get("version_marker") or "")
    roots = _plugin_roots(context)
    if not roots:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                "no installed plugin root could be resolved, so nothing could be read back; set "
                "INFIQUETRA_PLUGIN_ROOTS to name them explicitly"
            ),
            "evidence": {"roots": [], "resolved_versions": {}, "expected_version": expected},
        }
    plugins = [str(name) for name in context.entry.get("plugins") or []]
    if not plugins:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": "the profile declares this strategy but names no plugin to resolve",
            "evidence": {"roots": [str(root) for root in roots]},
        }
    resolved: dict[str, dict[str, str]] = {}
    missing: list[str] = []
    for root in roots:
        for plugin in plugins:
            manifest = root / "plugins" / plugin / ".claude-plugin" / "plugin.json"
            if not manifest.is_file():
                missing.append(f"{root}: {plugin} has no manifest")
                continue
            try:
                version = str(json.loads(manifest.read_text(encoding="utf-8")).get("version", ""))
            except (OSError, json.JSONDecodeError) as exc:
                missing.append(f"{root}: {plugin} manifest unreadable ({exc})")
                continue
            resolved.setdefault(str(root), {})[plugin] = version
            for surface in _expected_surfaces(context.entry, plugin):
                if not (root / "plugins" / plugin / str(surface)).exists():
                    missing.append(f"{root}: {plugin} is missing {surface}")
    evidence = {
        "roots": [str(root) for root in roots],
        "resolved_versions": resolved,
        "expected_version": expected or "not declared",
        "missing_surfaces": missing,
    }
    if missing:
        return {
            "result": RESULT_FAILED,
            "status_reason": f"{len(missing)} installed-surface problem(s): {'; '.join(missing)}",
            "evidence": evidence,
        }
    # Compare each plugin's version ACROSS the roots, never one plugin's against another's: two
    # plugins are released on their own numbers, so comparing them would report a disagreement on
    # every machine where the fleet is perfectly healthy.
    disagreements: list[str] = []
    for plugin in plugins:
        per_plugin = {per_root[plugin] for per_root in resolved.values() if per_root.get(plugin)}
        if len(per_plugin) > 1:
            disagreements.append(f"{plugin}: {', '.join(sorted(per_plugin))}")
        elif expected and per_plugin and expected not in per_plugin:
            disagreements.append(
                f"{plugin}: {', '.join(sorted(per_plugin))}, not the expected {expected}"
            )
    evidence["version_disagreements"] = disagreements
    if disagreements:
        return {
            "result": RESULT_FAILED,
            "status_reason": (
                "the installed plugin roots do not agree on a version — "
                + "; ".join(disagreements)
                + ". One root updating while another does not is a failure, not a warning"
            ),
            "evidence": evidence,
        }
    versions = {
        version for per_root in resolved.values() for version in per_root.values() if version
    }
    return {
        "result": RESULT_PASSED,
        "status_reason": (
            f"{len(roots)} installed plugin root(s) resolve {
                ', '.join(sorted(versions)) or 'a manifest'
            } and carry every expected surface"
        ),
        "evidence": evidence,
    }


def driver_delegated_canary(context: DriverContext) -> dict[str, Any]:
    """Hand the strategy to the executor the profile declares and ingest its envelope.

    This never issues its own requests. The CAMPPS end-to-end canary already owns this family,
    and reimplementing it here would be a second definition of the same proof.
    """
    entrypoint = str(context.entry.get("entrypoint") or "")
    if not entrypoint:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                "the profile declares this strategy but names no executor entrypoint to delegate "
                "to, and this driver never issues its own requests"
            ),
            "evidence": {},
        }
    missing = _missing_environment(context)
    if missing:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the environment variable {missing} is unset, so the declared executor could not "
                "be invoked"
            ),
            "evidence": {"missing_environment_variable": missing},
        }
    scenarios = [str(item) for item in context.entry.get("scenarios") or []]
    scenario = scenarios[0] if scenarios else "default"
    environment = str(context.environment.get("name") or context.environment.get("base_url") or "")
    # Same parsing as the declared commands above, and the same refusal when it does not parse: an
    # entrypoint with an unbalanced quote is a profile the operator has to fix, not a traceback.
    try:
        entrypoint_argv = shlex.split(entrypoint)
    except ValueError as exc:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the declared executor {entrypoint!r} does not parse into an argument vector: "
                f"{redact(str(exc))}"
            ),
            "evidence": {"entrypoint": entrypoint},
        }
    argv = [
        *entrypoint_argv,
        "run-scenario",
        "--scenario",
        scenario,
        "--environment",
        environment,
    ]
    try:
        code, output = context.runner(argv, context.timeout, context.repo_root)
    except FileNotFoundError as exc:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"the declared executor {entrypoint!r} is not present on this machine: "
                f"{redact(str(exc))}"
            ),
            "evidence": {"invocation": " ".join(argv)},
        }
    except subprocess.TimeoutExpired:
        return {
            "result": RESULT_BLOCKED,
            "status_reason": f"the declared executor timed out after {context.timeout} seconds",
            "evidence": {"invocation": " ".join(argv)},
        }
    ingested: dict[str, Any] = {}
    try:
        candidate = json.loads(output)
        if isinstance(candidate, dict):
            ingested = candidate
    except json.JSONDecodeError:
        ingested = {}
    evidence = {
        "environment": environment,
        "scenario_id": scenario,
        "invocation": " ".join(argv),
        "observed_status": ingested.get("result", code),
        "response_markers": ingested.get("evidence", {}),
        "ingested_envelope": ingested,
    }
    result = str(ingested.get("result") or "")
    if result in RESULTS:
        return {
            "result": result,
            "status_reason": (
                f"the declared executor reported {result}: "
                f"{redact(str(ingested.get('status_reason', ''))) or 'no reason given'}"
            ),
            "evidence": evidence,
        }
    if code == 0:
        return {
            "result": RESULT_PASSED,
            "status_reason": "the declared executor exited zero",
            "evidence": evidence,
        }
    return {
        "result": RESULT_FAILED,
        "status_reason": f"the declared executor exited {code}",
        "evidence": evidence,
    }


DRIVERS: dict[str, Callable[[DriverContext], dict[str, Any]]] = {
    "cli_smoke": driver_cli_smoke,
    "contract_check": driver_contract_check,
    "deploy_boundary": driver_deploy_boundary,
    "installed_surface": driver_installed_surface,
    "delegated_canary": driver_delegated_canary,
}


def run_strategy(
    strategy: Strategy,
    entry: Mapping[str, Any],
    *,
    environment: Mapping[str, Any],
    profile_revision: str,
    repo_root: Path,
    runner: Runner | None = None,
    environ: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Dispatch one strategy and return its envelope. A driver failure is blocked, never a crash."""
    started = _utc_now()
    clock = time.monotonic()
    context = DriverContext(
        strategy=strategy,
        entry=dict(entry),
        environment=dict(environment),
        profile_revision=profile_revision,
        repo_root=repo_root,
        runner=runner or subprocess_runner,
        environ=dict(environ if environ is not None else os.environ),
        timeout=timeout,
    )
    if strategy.driver is None:
        outcome = {
            "result": RESULT_BLOCKED,
            "status_reason": (
                f"{strategy.id} is declared in the catalogue and ships no driver: "
                f"{strategy.no_driver_reason}"
            ),
            "evidence": {"revisit_when": strategy.revisit_when or ""},
            "proof_mode": "manual" if strategy.id == "manual-runbook" else "automated",
        }
    else:
        driver = DRIVERS.get(strategy.driver)
        if driver is None:
            outcome = {
                "result": RESULT_BLOCKED,
                "status_reason": (
                    f"the catalogue names the driver {strategy.driver!r} for {strategy.id}, and "
                    "this module carries no such driver"
                ),
                "evidence": {},
            }
        else:
            try:
                outcome = driver(context)
            except Exception as exc:  # noqa: BLE001 - a driver that raises is blocked, not fatal
                outcome = {
                    "result": RESULT_BLOCKED,
                    "status_reason": (
                        f"the {strategy.id} driver raised {type(exc).__name__}: {redact(str(exc))}"
                    ),
                    "evidence": {},
                }
    scenarios = [str(item) for item in (entry.get("scenarios") or [])]
    return make_envelope(
        strategy,
        result=str(outcome["result"]),
        status_reason=str(outcome["status_reason"]),
        environment=str(environment.get("name") or environment.get("base_url") or "unnamed"),
        profile_revision=profile_revision,
        scenario_id=scenarios[0] if scenarios else "",
        started_at=started,
        completed_at=_utc_now(),
        duration_seconds=time.monotonic() - clock,
        evidence=evidence if isinstance(evidence := outcome.get("evidence"), Mapping) else None,
        proof_mode=str(outcome.get("proof_mode", "automated")),
    )


# ---------------------------------------------------------------------------
# The verdict and the route.
# ---------------------------------------------------------------------------


def verdict(envelopes: Sequence[Mapping[str, Any]], required_ids: Sequence[str]) -> str:
    """Count the statuses. Nothing is weighted, nothing is scored, no model is consulted."""
    required = set(required_ids)
    by_id = {str(envelope["strategy_id"]): str(envelope["result"]) for envelope in envelopes}
    for strategy_id in sorted(required):
        if by_id.get(strategy_id) != RESULT_PASSED:
            return VERDICT_FAIL
    optional_blocked = [
        strategy_id
        for strategy_id, result in by_id.items()
        if strategy_id not in required and result == RESULT_BLOCKED
    ]
    if optional_blocked:
        return VERDICT_PROOF_DEBT
    return VERDICT_PASS


def route(envelopes: Sequence[Mapping[str, Any]], required_ids: Sequence[str]) -> dict[str, Any]:
    """Where the run goes next, and the proof debt it carries.

    A required strategy that is BLOCKED does not re-enter the build loop: its causes are
    environment, credential and permission, which are the operator's approval boundaries and
    which no build loop can repair.
    """
    required = set(required_ids)
    by_id = {str(envelope["strategy_id"]): str(envelope["result"]) for envelope in envelopes}
    reasons = {
        str(envelope["strategy_id"]): str(envelope.get("status_reason", ""))
        for envelope in envelopes
    }
    blocked_required = sorted(
        strategy_id
        for strategy_id in required
        if by_id.get(strategy_id, RESULT_BLOCKED) == RESULT_BLOCKED
    )
    computed = verdict(envelopes, required_ids)
    if blocked_required:
        return {
            "verdict": VERDICT_FAIL,
            "route": ROUTE_OPERATOR,
            "blocked_required": blocked_required,
            "reason": (
                "these required strategies could not run, so nothing was proved about them: "
                + "; ".join(f"{sid} — {reasons.get(sid, '')}" for sid in blocked_required)
                + ". The causes of a block are environment, credential and permission, none of "
                "which the build loop can repair, so this stops for the operator"
            ),
            "proof_debt": [],
        }
    proof_debt = [
        {"strategy_id": strategy_id, "reason": reasons.get(strategy_id, ""), "revisit_when": ""}
        for strategy_id, result in sorted(by_id.items())
        if strategy_id not in required and result == RESULT_BLOCKED
    ]
    if computed == VERDICT_FAIL:
        failing = sorted(
            strategy_id for strategy_id in required if by_id.get(strategy_id) == RESULT_FAILED
        )
        return {
            "verdict": VERDICT_FAIL,
            "route": ROUTE_BUILD_LOOP,
            "blocked_required": [],
            "reason": (
                "these required strategies ran and did not meet their threshold: "
                + "; ".join(f"{sid} — {reasons.get(sid, '')}" for sid in failing)
            ),
            "proof_debt": proof_debt,
        }
    return {
        "verdict": computed,
        "route": ROUTE_CLOSE,
        "blocked_required": [],
        "reason": (
            "every required strategy passed"
            + (
                f"; {len(proof_debt)} optional strategy(ies) could not run and the debt is recorded"
                if proof_debt
                else ""
            )
        ),
        "proof_debt": proof_debt,
    }


def exit_code_for(decision: Mapping[str, Any]) -> int:
    """The process exit code for a routing decision."""
    if decision["route"] == ROUTE_OPERATOR:
        return EXIT_OPERATOR_STOP
    if decision["verdict"] == VERDICT_FAIL:
        return EXIT_FAIL
    return EXIT_OK


# ---------------------------------------------------------------------------
# The run record.
# ---------------------------------------------------------------------------


def environment_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """The base URL, deployed revision and version marker the release step recorded.

    Read, never written and never invented: a functional test that made up an environment would
    be proving something about nothing.
    """
    deploy = record.get("deploy") or {}
    release = record.get("release") or {}
    configuration = record.get("run_configuration") or {}
    destination = configuration.get("nonproduction_destination")
    name = destination.get("value") if isinstance(destination, dict) else destination
    return {
        "name": str(deploy.get("destination") or name or ""),
        "base_url": str(deploy.get("base_url") or ""),
        "revision": str(
            deploy.get("revision")
            or release.get("landed_commit")
            or release.get("reviewed_head")
            or ""
        ),
        "version_marker": str(deploy.get("version_marker") or ""),
    }


def require_record(store_root: Path, issue: int) -> run_record.RunRecord:
    """The run's record, or a refusal. A functional test never invents the run it tests."""
    record = run_record.load(store_root, issue)
    if record is None:
        raise ProfileRefusalError(
            f"issue {issue} has no run record under {store_root}, so there is no run to test and "
            "no environment identity to test it against; admission writes the record"
        )
    return record


def write_block(store_root: Path, issue: int, block: Mapping[str, Any]) -> Path:
    """Write the qa block under the record's top-level extension point."""
    record = require_record(store_root, issue)
    record.extra[RECORD_KEY] = dict(block)
    run_record.save(store_root, record)
    return run_record.record_path(store_root, issue)


# ---------------------------------------------------------------------------
# The whole procedure.
# ---------------------------------------------------------------------------


def changed_files(repo_root: Path, base_ref: str, *, runner: Runner | None = None) -> list[str]:
    """The change's file list, from git. An unreadable diff is an empty list, never a guess."""
    run = runner or subprocess_runner
    try:
        code, output = run(
            ["git", "-C", str(repo_root), "diff", "--name-only", base_ref], 120, None
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if code != 0:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def run_selection(
    catalogue: Catalogue,
    profile: Mapping[str, Any],
    selection: Selection,
    *,
    environment: Mapping[str, Any],
    profile_revision: str,
    repo_root: Path,
    runner: Runner | None = None,
    environ: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Run every selected strategy and return one envelope each, in selection order."""
    declared: Mapping[str, Any] = profile.get("strategies", {})
    envelopes: list[dict[str, Any]] = []
    for entry in selection.entries:
        strategy = catalogue.strategies[entry.strategy_id]
        envelopes.append(
            run_strategy(
                strategy,
                declared.get(entry.strategy_id, {}),
                environment=environment,
                profile_revision=profile_revision,
                repo_root=repo_root,
                runner=runner,
                environ=environ,
                timeout=timeout,
            )
        )
    return envelopes


def report(block: Mapping[str, Any]) -> str:
    """The comment body: the selection, the per-strategy statuses, and the artifact pointers."""
    selection = block.get("selection", {})
    lines = [
        # Frontmatter, so the status card's own projection reads the verdict, the boundary and the
        # route from a stable shape rather than from the prose beneath it.
        "---",
        "type: qa",
        f"verdict: {block.get('verdict', '')}",
        f"boundary: {selection.get('boundary', '')}",
        f"route: {block.get('route', '')}",
        "---",
        "",
        "## Functional test",
        "",
        f"**Verdict: `{block.get('verdict', '?')}`** — {block.get('reason', '')}",
        "",
        f"Boundary: `{selection.get('boundary', '?')}`. Route: `{block.get('route', '?')}`.",
        "",
        "### Selection",
        "",
        "| Strategy | Required | Why it was selected |",
        "|---|---|---|",
    ]
    for entry in selection.get("entries", []):
        lines.append(
            f"| `{entry['strategy_id']}` | {'yes' if entry['required'] else 'no'} | "
            f"{entry['reason']} |"
        )
    out_of_boundary = selection.get("out_of_boundary", [])
    if out_of_boundary:
        lines += ["", "### Out of boundary — not run, and not proof debt", ""]
        for item in out_of_boundary:
            lines.append(f"- `{item['strategy_id']}`: {item['detail']}")
    lines += [
        "",
        "### Results",
        "",
        "| Strategy | Result | What it proved, or why it did not |",
        "|---|---|---|",
    ]
    for envelope in block.get("envelopes", []):
        lines.append(
            f"| `{envelope['strategy_id']}` | `{envelope['result']}` | "
            f"{envelope['status_reason']} |"
        )
    pointers = [
        pointer
        for envelope in block.get("envelopes", [])
        for pointer in envelope.get("artifact_pointers", [])
    ]
    if pointers:
        lines += ["", "### Artifacts", ""] + [f"- `{pointer}`" for pointer in pointers]
    debt = block.get("proof_debt") or []
    if debt:
        lines += ["", "### Proof debt", ""]
        for item in debt:
            lines.append(f"- `{item['strategy_id']}`: {item['reason']}")
    return "\n".join(lines)


def execute(
    *,
    issue: int,
    repo_root: Path,
    store_root: Path,
    boundary: str = DEFAULT_BOUNDARY,
    base_ref: str = "origin/main",
    catalogue_path: Path | None = None,
    profile_path: Path | None = None,
    runner: Runner | None = None,
    environ: Mapping[str, str] | None = None,
    widen: Callable[..., Any] | None = None,
    dry_run: bool = False,
    change_summary: str = "",
) -> dict[str, Any]:
    """Select, preflight, dispatch, count and record. Returns the block written to the record."""
    catalogue = load_catalogue(catalogue_path)
    profile = load_profile(repo_root, profile_path=profile_path, catalogue=catalogue)
    record = require_record(store_root, issue)
    environment = environment_identity(run_record.to_dict(record))
    files = changed_files(repo_root, base_ref, runner=runner)

    selection = declared_selection(catalogue, profile, files, boundary=boundary)
    selection = widen_selection(
        selection,
        catalogue,
        profile,
        changed_files=files,
        change_summary=change_summary,
        widen=widen,
    )
    checks = preflight(selection, catalogue, profile, environ=environ)
    revision = str(profile.get("revision") or environment.get("revision") or "unversioned")

    block: dict[str, Any] = {
        "schema": "qa_run.v1",
        "issue": issue,
        "recorded_at": _utc_now(),
        "boundary": boundary,
        "environment": environment,
        "selection": selection.as_record(),
        "preflight": checks,
        "envelopes": [],
        "verdict": "",
        "route": "",
        "reason": "",
        "proof_debt": [],
    }

    if checks["refused"]:
        block["verdict"] = VERDICT_BLOCKED
        block["route"] = ROUTE_OPERATOR
        block["reason"] = checks["reason"]
        if not dry_run:
            write_block(store_root, issue, block)
        return block

    if dry_run:
        block["verdict"] = "not-run"
        block["route"] = "none"
        block["reason"] = "selection only; no driver was dispatched"
        return block

    envelopes = run_selection(
        catalogue,
        profile,
        selection,
        environment=environment,
        profile_revision=revision,
        repo_root=repo_root,
        runner=runner,
        environ=environ,
    )
    for envelope in envelopes:
        problems = validate_envelope(envelope)
        if problems:
            raise QaStrategiesError(
                f"the {envelope.get('strategy_id')} envelope does not validate: "
                + "; ".join(problems)
            )
    decision = route(envelopes, selection.required_ids)
    block["envelopes"] = envelopes
    block["verdict"] = decision["verdict"]
    block["route"] = decision["route"]
    block["reason"] = decision["reason"]
    block["proof_debt"] = decision["proof_debt"]
    block["blocked_required"] = decision["blocked_required"]
    write_block(store_root, issue, block)
    return block


# ---------------------------------------------------------------------------
# Command line.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa_strategies",
        description="The prescribed testing strategies: select, run, and count the verdict.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("select", "print the selection and its reasons; run no driver"),
        ("run", "run the whole procedure and record the verdict"),
        ("verdict", "recompute the verdict from what the record already holds"),
    ):
        target = sub.add_parser(name, help=help_text)
        target.add_argument("--issue", type=int, required=True)
        target.add_argument("--repo-root", default=None)
        target.add_argument("--store-root", default=None)
        target.add_argument(
            "--boundary",
            default=DEFAULT_BOUNDARY,
            choices=list(BOUNDARIES),
            help="which proof boundary this run can reach (default: %(default)s)",
        )
        target.add_argument("--base-ref", default="origin/main")
        target.add_argument("--json", action="store_true", help="print the block as JSON")
    return parser


def _repo_root(args: argparse.Namespace) -> Path:
    return Path(args.repo_root).resolve() if args.repo_root else Path.cwd()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = _repo_root(args)
    try:
        store_root = (
            Path(args.store_root).resolve()
            if args.store_root
            else run_record.resolve_store_root(repo_root)
        )
    except run_record.RunRecordError as exc:
        print(f"qa: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    try:
        if args.command == "verdict":
            record = require_record(store_root, args.issue)
            block = record.extra.get(RECORD_KEY)
            if not isinstance(block, dict):
                print("qa: this run's record carries no functional-test block", file=sys.stderr)
                return EXIT_REFUSED
            required = [
                entry["strategy_id"]
                for entry in block.get("selection", {}).get("entries", [])
                if entry.get("required")
            ]
            decision = route(block.get("envelopes", []), required)
            print(json.dumps(decision, indent=2) if args.json else report({**block, **decision}))
            return exit_code_for(decision)

        block = execute(
            issue=args.issue,
            repo_root=repo_root,
            store_root=store_root,
            boundary=args.boundary,
            base_ref=args.base_ref,
            dry_run=args.command == "select",
        )
    except ProfileRefusalError as exc:
        print(f"qa: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except run_record.UnknownRecordVersionError as exc:
        print(f"qa: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except QaStrategiesError as exc:
        print(f"qa: {exc}", file=sys.stderr)
        return EXIT_INTERNAL

    print(json.dumps(block, indent=2) if args.json else report(block))
    if args.command == "select":
        return EXIT_OK
    if block["verdict"] == VERDICT_BLOCKED or block["route"] == ROUTE_OPERATOR:
        return EXIT_OPERATOR_STOP
    if block["verdict"] == VERDICT_FAIL:
        return EXIT_FAIL
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
