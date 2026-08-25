# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.25.2
# source-commit: 3b5faa6c1044a888e03cb7b8bbf2f71c6749489c
# source-path: scripts/fleet_commons/intent_envelope.py
# source-sha256: c4e9b522c73e23a875ae85baa5e45687f4bfaae84fa3ead11af1d4c730d50b98
# output-sha256: c4e9b522c73e23a875ae85baa5e45687f4bfaae84fa3ead11af1d4c730d50b98
# --- end generated bundle stamp ---
#!/usr/bin/env python3
"""Canonical fleet IntentEnvelope — the one committed run-start posture schema (#380).

Run-start posture — attended vs. unattended, which ceremony gates apply, what spend
posture follows — used to be asked (or silently assumed) independently at five-plus
sites across the fleet. This module is the single shared primitive they all resolve
through instead: one schema (:class:`IntentEnvelope`), one composed run-start
interview (:data:`INTERVIEW`, the registry the fleet drift-guard test checks against),
one mode-keyed defaults matrix (:func:`recommend_tier` / :func:`self_select_posture`),
and one spend-posture resolver (:func:`spend_posture` / :func:`resolve_spend_action`).

Canonical home: ``plugins/fleet-core/scripts/fleet_commons/`` (the fleet-commons
mechanism, DECISIONS ``{#fleet-commons-mechanism-463}``) because the envelope has
consumers in three plugins — saga (``/outcome`` start, ``OutcomeSpec.intent``,
``ExecutionSpec.intent``), team-execution (Step B1 posture check), and
mission-control (issue-capture validation). saga re-exports this module through
``plugins/saga/scripts/intent_envelope.py`` (the issue's proposed path), exactly as
``execution_spec.py`` re-exports ``tier_palette``.

Vocabulary discipline: the schema is CLOSED at each ``SCHEMA_VERSION`` — an unknown
top-level key, an off-vocabulary value, or a foreign schema version is an error,
never a pass (fail closed, never enumerate-and-shrug). Extensions are made by
EDITING this module — never by consumers tolerating keys they do not understand.
#373 landed its extension here as OPTIONAL, additive keys of schema v1
(``backends_permitted`` / ``degrade_policy`` / ``spend_envelope``): an absent key
means "posture not captured" and every pre-#373 v1 envelope round-trips
byte-identical with unchanged meaning, so no committed envelope is force-migrated.
The closed-schema rule is unchanged — the three keys are now part of v1's closed
key set, and anything outside it remains an error. Future extensions (#449's
envelope tokens, #372/#433's mid-run amendment verbs) follow the same rule: edit
here, additive-optional where the old meaning is preserved, version-bump where it
is not.

Threat model (read before trusting a field):

* ``source`` / ``authored_by`` / ``authored_at`` are **self-attested** provenance
  labels. Nothing here verifies that the named author really answered the interview
  or that the stated source is genuine — a forged envelope on an issue body is
  syntactically indistinguishable from a real one. Consumers must treat the envelope
  as *the operator's recorded intent*, not as an authorization credential.
* The envelope **authorizes nothing by itself**. ``ceremony_gates`` values only ever
  make a consumer MORE conservative than its own default or record an operator
  choice the consumer separately enforces; the ``AUTONOMOUS_UNDER_ENVELOPE`` write
  class with real token check + revocation is #449's separate mechanism, not this
  schema. In particular ``merge: "auto"`` / ``deploy_nonprod: "auto"`` here are a
  recorded operator decision that downstream gate machinery (the reversibility
  certificate, which today always GATEs merge/deploy) may consult — this module
  grants no write path.
* :func:`resolve_spend_action`'s ``approval_token`` is an opaque presence check
  (was an explicit operator approval supplied alongside the spend increase?) — it is
  not validated against an issuer or a revocation list in v1; #449 owns that.
* The #373 dispatch-seam fields only ever NARROW what a dispatch may do relative to
  the uncaptured default: ``backends_permitted`` intersects with (never extends) the
  host's runtime-available set, ``degrade_policy`` restricts the existing
  presence-conditional degrade to at most one ladder rung (or forbids it outright),
  and ``spend_envelope`` adds a HALT-only pre-dispatch gate. None of them grants a
  write path or capability the consumer did not already have.
* :func:`authorize_spend` reads **leaf-produced, self-attested actuals** (the
  ``outcome_costs`` ledger): a leaf that under-reports or never reports its cost is
  not measured against the ceiling. The gate bounds honest spend drift; it is not a
  defense against a lying leaf.

No I/O at import; the only file the module reads is via the sibling tier registry
(``tier_resolver`` -> ``tier_policy.json``), loaded lazily on first tier lookup.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_sibling(name: str) -> ModuleType:
    """Load ``<this directory>/<name>.py`` — portable fleet-commons resolution.

    Installed by transform ``resolve-fleet-commons-sibling`` v1 in place of the
    upstream fleet-commons discovery shim, whose resolution ladder is specific to
    Claude Code plugin installs. Sibling resolution is placement-independent by
    construction: the identical file works in ``plugins/fleet-core/scripts/
    fleet_commons/`` and in any generated ``_bundled/`` copy a consuming plugin
    carries, because the module is always read from this file's own directory.

    Lazy and cached, mirroring the shim's load contract: repeated loads return the
    same module object, keyed by ``(name, directory)`` in ``sys.modules`` so a
    relocated copy never serves a stale module. A name with no sibling file (a
    deferred module such as ``tier_resolver``) raises at CALL time naming the
    missing sibling path, never at import.
    """
    sibling_dir = Path(__file__).resolve().parent
    cache_key = f"_fleet_commons_{name}@{sibling_dir}"
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached
    module_path = sibling_dir / f"{name}.py"
    if not module_path.is_file():
        raise RuntimeError(
            f"fleet-commons: module {name!r} not found at {module_path} "
            "(absent from this portable Fleet Core slice; the deferred modules are "
            "named in the fleet-core package's DEFERRED.md)."
        )
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


SCHEMA_VERSION = 1

# Closed run-mode vocabulary. ATTENDED means an operator is present to answer gates
# mid-run; UNATTENDED means the run self-selects defaults and never blocks on a prompt.
ATTENDED = "attended"
UNATTENDED = "unattended"
RUN_MODES = (ATTENDED, UNATTENDED)

# Closed ceremony-gate settings. GATE = the ceremony pauses for the operator (the safe
# default, matching the fleet's HALT-not-degrade posture); AUTO = the operator has
# pre-declared, once, at run start, that the consumer's own automation may proceed.
GATE = "gate"
AUTO = "auto"
GATE_SETTINGS = (GATE, AUTO)

# The three pre-declared ceremony gates (T7-F3-2). Pre-declared envelope fields,
# never interactive re-asks: a consumer reads the value; it does not ask again.
CEREMONY_GATE_FIELDS = ("reviews_required", "merge", "deploy_nonprod")

_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "run_mode",
        "ceremony_gates",
        "source",
        "authored_at",
        "authored_by",
        # #373 dispatch-seam posture — optional additive keys of schema v1 (absent =
        # "posture not captured"; every pre-#373 envelope round-trips byte-identical).
        "backends_permitted",
        "degrade_policy",
        "spend_envelope",
    }
)

# #373: the run-start degrade posture vocabulary (closed). Deliberately the SAME strings as
# saga's per-node ``outcome_spec.DEGRADE_POLICIES`` axis so the operator learns one vocabulary:
# ``halt`` — an unmet backend prerequisite always HALTs, never substitutes; ``operator_away_one_rung``
# — the existing presence-conditional mechanism may degrade, but AT MOST one ladder rung
# (never a silent cascade past the immediate rung). An uncaptured policy ("" / absent key)
# means: when a backend posture is otherwise engaged, HALT by default.
INTENT_DEGRADE_HALT = "halt"
INTENT_DEGRADE_ONE_RUNG = "operator_away_one_rung"
INTENT_DEGRADE_POLICIES = (INTENT_DEGRADE_HALT, INTENT_DEGRADE_ONE_RUNG)

# #373: the spend-envelope sub-schema (closed keys). ``tier_ceiling`` is a model name from the
# fleet tier ladder (``tier_palette.MODELS``); ``cost_ceiling_tokens`` is a cumulative
# leaf-produced token budget. At least one must be set — an empty object is an authoring error.
SPEND_ENVELOPE_FIELDS = ("tier_ceiling", "cost_ceiling_tokens")

# Spend-posture vocabulary (T12-F3-7): machinery, not prose. The default posture names
# how the run spends; the approval rule names when a spend increase needs the operator.
POSTURE_CACHE_TIGHT = "cache-tight"
POSTURE_INTERACTIVE = "interactive"
RULE_SILENT = "silent"
RULE_ASK_ON_SPEND_INCREASE = "ask-on-spend-increase"

# resolve_spend_action verdicts (closed).
ACTION_PROCEED_DEFAULT = "proceed-default"
ACTION_PROCEED_INCREASE = "proceed-increase"
ACTION_HOLD_AT_DEFAULT = "hold-at-default"

# The fenced-block marker for an issue-carried envelope (G-hybrids-4 / H-F2-9 / S-22):
# schema-validated JSON inside a ```intent-envelope fence, never prose.
ISSUE_BLOCK_FENCE = "intent-envelope"
ISSUE_BLOCK_HEADING = "### Intent envelope"
# \r?\n: GitHub web-UI authoring submits textarea content with CRLF line endings, so a
# byte-identical envelope must extract identically on LF and CRLF bodies — a CRLF-blind fence
# regex silently degrades the ask-once contract (and blinds the capture-side validity gate).
_ISSUE_BLOCK_RE = re.compile(r"```intent-envelope[ \t]*\r?\n(.*?)```", re.DOTALL)


class IntentEnvelopeError(ValueError):
    """Raised for a malformed envelope, answer set, or issue block (fail closed)."""


class PostureError(IntentEnvelopeError):
    """Raised when a spend increase needs an operator approval token and none was given."""


def _tier_resolver() -> ModuleType:
    return _load_sibling("tier_resolver")


def _tier_palette() -> ModuleType:
    return _load_sibling("tier_palette")


def _require_str(value: Any, *, where: str) -> str:
    if not isinstance(value, str):
        raise IntentEnvelopeError(f"{where} must be a string, got {type(value).__name__} {value!r}")
    return value


@dataclass(frozen=True)
class CeremonyGates:
    """The pre-declared ceremony-gate block (T7-F3-2). Unset fields default to GATE."""

    reviews_required: str = GATE
    merge: str = GATE
    deploy_nonprod: str = GATE

    def validate(self, where: str = "ceremony_gates") -> None:
        for field_name in CEREMONY_GATE_FIELDS:
            value = getattr(self, field_name)
            if value not in GATE_SETTINGS:
                raise IntentEnvelopeError(f"{where}.{field_name}: {value!r} not in {GATE_SETTINGS}")

    @classmethod
    def from_dict(cls, data: Any, *, where: str = "ceremony_gates") -> CeremonyGates:
        if data is None:
            return cls()  # absent block -> every gate defaults to GATE (T7-F3-2)
        if not isinstance(data, Mapping):
            raise IntentEnvelopeError(f"{where} must be an object, got {data!r}")
        unknown = sorted(set(data) - set(CEREMONY_GATE_FIELDS))
        if unknown:
            raise IntentEnvelopeError(
                f"{where}: unknown field(s) {unknown} — the gate vocabulary is closed "
                f"({list(CEREMONY_GATE_FIELDS)}); extend the schema here, never ad hoc"
            )
        gates = cls(
            **{
                name: _require_str(data[name], where=f"{where}.{name}")
                for name in CEREMONY_GATE_FIELDS
                if name in data
            }
        )
        gates.validate(where)
        return gates

    def to_dict(self) -> dict[str, str]:
        # Every field is emitted explicitly so the committed artifact is self-describing:
        # a reader never has to know the default to know the posture.
        return {name: getattr(self, name) for name in CEREMONY_GATE_FIELDS}


@dataclass(frozen=True)
class SpendEnvelope:
    """The #373 run-start spend ceiling (T8-F5-7): a tier ceiling and/or a cost ceiling.

    ``tier_ceiling`` is a model name from the ordered fleet ladder (``tier_palette.MODELS``);
    a dispatch requesting a STRONGER model is tier-escalating. ``cost_ceiling_tokens`` is the
    cumulative leaf-produced token budget; recorded actuals at or past it exhaust the budget.
    At least one field must be set — capture a ceiling or omit the envelope, never an empty
    object. Enforcement is HALT-only (:func:`authorize_spend`): an unauthorized dispatch halts
    for explicit step-up, it never silently degrades to a cheaper tier.
    """

    tier_ceiling: str = ""
    cost_ceiling_tokens: float | None = None

    def validate(self, where: str = "spend_envelope") -> None:
        if not self.tier_ceiling and self.cost_ceiling_tokens is None:
            raise IntentEnvelopeError(
                f"{where}: at least one of {list(SPEND_ENVELOPE_FIELDS)} must be set — "
                f"capture a ceiling or omit the field, never an empty envelope"
            )
        if self.tier_ceiling:
            models = _tier_palette().MODELS
            if self.tier_ceiling not in models:
                raise IntentEnvelopeError(
                    f"{where}.tier_ceiling: {self.tier_ceiling!r} not in the fleet tier "
                    f"ladder {models}"
                )
        if self.cost_ceiling_tokens is not None:
            value = self.cost_ceiling_tokens
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise IntentEnvelopeError(
                    f"{where}.cost_ceiling_tokens must be a finite number > 0, got {value!r}"
                )

    @classmethod
    def from_dict(cls, data: Any, *, where: str = "spend_envelope") -> SpendEnvelope:
        if not isinstance(data, Mapping):
            raise IntentEnvelopeError(f"{where} must be an object, got {data!r}")
        unknown = sorted(set(data) - set(SPEND_ENVELOPE_FIELDS))
        if unknown:
            raise IntentEnvelopeError(
                f"{where}: unknown field(s) {unknown} — the spend-envelope vocabulary is "
                f"closed ({list(SPEND_ENVELOPE_FIELDS)}); extend the schema here, never ad hoc"
            )
        raw_ceiling = data.get("cost_ceiling_tokens")
        if raw_ceiling is not None and (
            isinstance(raw_ceiling, bool) or not isinstance(raw_ceiling, (int, float))
        ):
            raise IntentEnvelopeError(
                f"{where}.cost_ceiling_tokens must be a number or absent, got {raw_ceiling!r}"
            )
        envelope = cls(
            tier_ceiling=_require_str(data.get("tier_ceiling", ""), where=f"{where}.tier_ceiling"),
            cost_ceiling_tokens=float(raw_ceiling) if raw_ceiling is not None else None,
        )
        envelope.validate(where)
        return envelope

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.tier_ceiling:
            out["tier_ceiling"] = self.tier_ceiling
        if self.cost_ceiling_tokens is not None:
            out["cost_ceiling_tokens"] = self.cost_ceiling_tokens
        return out


def _backends_permitted_from(
    value: Any, *, where: str = "backends_permitted"
) -> tuple[str, ...] | None:
    """Parse the #373 ``backends_permitted`` list — type-strict, fail closed.

    ``None``/absent means "not captured" (dispatch-time availability resolution, exactly
    today's behavior). When present it must be a non-empty list of unique, non-empty strings.
    This module owns only the SHAPE; the backend VOCABULARY belongs to the consuming dispatch
    seam (saga's ``outcome_spec.NODE_BACKENDS`` check at spec-validate time), because the
    fleet schema does not own the outcome executor menu.
    """
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise IntentEnvelopeError(
            f"{where} must be a list of backend names, got {type(value).__name__} {value!r}"
        )
    entries: list[str] = []
    for i, item in enumerate(value):
        name = _require_str(item, where=f"{where}[{i}]")
        if not name:
            raise IntentEnvelopeError(f"{where}[{i}]: backend name must be non-empty")
        if name in entries:
            raise IntentEnvelopeError(f"{where}: duplicate backend {name!r}")
        entries.append(name)
    if not entries:
        raise IntentEnvelopeError(
            f"{where}: an empty permitted set is an authoring error — capture at least one "
            f"backend or omit the field (use the adjustment envelope to stop dispatch)"
        )
    return tuple(entries)


@dataclass(frozen=True)
class IntentEnvelope:
    """One committed run-start posture: run mode + pre-declared ceremony gates.

    ``source`` / ``authored_at`` / ``authored_by`` are self-attested provenance (see the
    module threat model) — carried for the audit trail, trusted for nothing.

    The #373 dispatch-seam fields (``backends_permitted`` / ``degrade_policy`` /
    ``spend_envelope``) are OPTIONAL: absent means "posture not captured" and the consuming
    dispatch seam behaves exactly as it did before #373. When captured they only ever narrow
    dispatch (see the module threat model) and are enforced at saga's ``/outcome`` seam
    (``outcome_dispatcher`` + ``outcome._reconcile_once``), never here.
    """

    run_mode: str
    ceremony_gates: CeremonyGates = CeremonyGates()
    schema_version: int = SCHEMA_VERSION
    source: str = ""
    authored_at: str = ""
    authored_by: str = ""
    # #373 run-start dispatch posture (all optional; absent = not captured).
    backends_permitted: tuple[str, ...] | None = None
    degrade_policy: str = ""
    spend_envelope: SpendEnvelope | None = None

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise IntentEnvelopeError(
                f"intent envelope schema_version {self.schema_version!r} is not the supported "
                f"{SCHEMA_VERSION} — this module is the single schema authority; migrate the "
                f"envelope, do not guess"
            )
        if self.run_mode not in RUN_MODES:
            raise IntentEnvelopeError(f"run_mode {self.run_mode!r} not in {RUN_MODES}")
        self.ceremony_gates.validate()
        if self.degrade_policy and self.degrade_policy not in INTENT_DEGRADE_POLICIES:
            raise IntentEnvelopeError(
                f"degrade_policy {self.degrade_policy!r} not in {INTENT_DEGRADE_POLICIES} "
                f"(or absent for 'not captured')"
            )
        if self.spend_envelope is not None:
            self.spend_envelope.validate()

    @classmethod
    def from_dict(cls, data: Any) -> IntentEnvelope:
        if not isinstance(data, Mapping):
            raise IntentEnvelopeError(f"intent envelope must be an object, got {data!r}")
        unknown = sorted(set(data) - _ENVELOPE_KEYS)
        if unknown:
            raise IntentEnvelopeError(
                f"intent envelope: unknown field(s) {unknown} — the schema is closed at "
                f"version {SCHEMA_VERSION}; extend intent_envelope.py, never a consumer"
            )
        if "run_mode" not in data:
            raise IntentEnvelopeError("intent envelope needs a run_mode")
        raw_version = data.get("schema_version", SCHEMA_VERSION)
        if not isinstance(raw_version, int) or isinstance(raw_version, bool):
            raise IntentEnvelopeError(f"schema_version must be an integer, got {raw_version!r}")
        raw_spend = data.get("spend_envelope")
        envelope = cls(
            run_mode=_require_str(data["run_mode"], where="run_mode"),
            ceremony_gates=CeremonyGates.from_dict(data.get("ceremony_gates")),
            schema_version=raw_version,
            source=_require_str(data.get("source", ""), where="source"),
            authored_at=_require_str(data.get("authored_at", ""), where="authored_at"),
            authored_by=_require_str(data.get("authored_by", ""), where="authored_by"),
            backends_permitted=_backends_permitted_from(data.get("backends_permitted")),
            degrade_policy=_require_str(data.get("degrade_policy", ""), where="degrade_policy"),
            spend_envelope=SpendEnvelope.from_dict(raw_spend) if raw_spend is not None else None,
        )
        envelope.validate()
        return envelope

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_mode": self.run_mode,
            "ceremony_gates": self.ceremony_gates.to_dict(),
        }
        # Self-attested provenance emits only when present (round-trip fidelity without
        # noise on minimally-authored envelopes).
        if self.source:
            out["source"] = self.source
        if self.authored_at:
            out["authored_at"] = self.authored_at
        if self.authored_by:
            out["authored_by"] = self.authored_by
        # #373 posture fields emit only when captured, so every pre-#373 envelope
        # round-trips byte-identical (the OutcomeSpec.intent / Node.sandbox convention).
        if self.backends_permitted is not None:
            out["backends_permitted"] = list(self.backends_permitted)
        if self.degrade_policy:
            out["degrade_policy"] = self.degrade_policy
        if self.spend_envelope is not None:
            out["spend_envelope"] = self.spend_envelope.to_dict()
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"


# ---------------------------------------------------------------------------
# The composed run-start interview — THE single asker (G-negative-space-1).
# A bounded challenge-response manifest (T1-F5-8): a fixed question set with
# typed, closed-vocabulary answers. Free-form prose is rejected, never coerced.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostureQuestion:
    """One registry entry: a typed question with a closed option set."""

    qid: str
    prompt: str
    options: tuple[str, ...]
    default: str | None
    required: bool


INTERVIEW: tuple[PostureQuestion, ...] = (
    PostureQuestion(
        qid="run_mode",
        prompt=(
            "Will an operator be present to answer gates during this run "
            "(attended), or must the run self-select defaults and never block "
            "on a prompt (unattended)?"
        ),
        options=RUN_MODES,
        default=None,
        required=True,
    ),
    PostureQuestion(
        qid="reviews_required",
        prompt=(
            "Reviews ceremony: gate each leaf's done transition on recorded review "
            "evidence (gate), or let the leaf's own pipeline vouch for itself (auto)?"
        ),
        options=GATE_SETTINGS,
        default=GATE,
        required=False,
    ),
    PostureQuestion(
        qid="merge",
        prompt=(
            "Merge ceremony: pause for the operator's keystroke on every merge (gate), "
            "or record a pre-declared auto-merge posture for this run (auto)?"
        ),
        options=GATE_SETTINGS,
        default=GATE,
        required=False,
    ),
    PostureQuestion(
        qid="deploy_nonprod",
        prompt=(
            "Nonprod-deploy ceremony: pause for the operator on nonprod deploys (gate), "
            "or record a pre-declared auto posture for this run (auto)?"
        ),
        options=GATE_SETTINGS,
        default=GATE,
        required=False,
    ),
)

_QUESTIONS_BY_QID = {q.qid: q for q in INTERVIEW}


@dataclass(frozen=True)
class Stakes:
    """Computed DAG stakes shown in the interview prompt (T4-F4-2) — data, not guesswork.

    ``parallel_width`` is the widest concurrent wave; ``critical_path_estimate`` is the
    longest dependency chain (unit-weight ``critical_path_wall``, the emitter's existing
    A7-table logic). Compute via saga's ``intent_envelope.compute_stakes`` over a spec.
    """

    parallel_width: int
    critical_path_estimate: float


def interview_manifest(stakes: Stakes | None = None) -> dict[str, Any]:
    """The machine-parseable interview manifest: fixed questions, typed answers."""
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "run-start-posture-interview",
        "questions": [
            {
                "qid": q.qid,
                "prompt": q.prompt,
                "options": list(q.options),
                "default": q.default,
                "required": q.required,
            }
            for q in INTERVIEW
        ],
    }
    if stakes is not None:
        manifest["stakes"] = {
            "parallel_width": stakes.parallel_width,
            "critical_path_estimate": stakes.critical_path_estimate,
        }
    return manifest


def render_interview(stakes: Stakes | None = None) -> str:
    """Render the single run-start posture interview as an operator-facing manifest.

    When ``stakes`` are supplied the prompt shows the computed ``parallel_width`` and
    ``critical_path_estimate`` so the operator decides against data, not prose guesswork.
    """
    lines = [
        f"# Run-start posture interview (intent-envelope v{SCHEMA_VERSION})",
        "",
        "Answers are typed against each question's closed options; free-form prose is",
        "rejected. Capture answers as JSON {qid: option} and apply via apply_answers().",
    ]
    if stakes is not None:
        lines += [
            "",
            "Stakes (computed from the DAG):",
            f"- parallel_width: {stakes.parallel_width} (widest concurrent wave)",
            (
                f"- critical_path_estimate: {stakes.critical_path_estimate:g} "
                "(longest dependency chain, unit-weight critical_path_wall)"
            ),
        ]
    for i, q in enumerate(INTERVIEW, start=1):
        required = "required" if q.required else f"default: {q.default}"
        lines += [
            "",
            f"[{i}] qid={q.qid} ({required}; options: {' | '.join(q.options)})",
            f"    {q.prompt}",
        ]
    return "\n".join(lines) + "\n"


def apply_answers(
    answers: Mapping[str, Any],
    *,
    source: str = "interview",
    authored_at: str = "",
    authored_by: str = "",
) -> IntentEnvelope:
    """Turn a typed answer set into a validated envelope — the interview's only exit.

    Unknown qids, missing required answers, and off-vocabulary values all fail closed.
    """
    if not isinstance(answers, Mapping):
        raise IntentEnvelopeError(f"answers must be an object of qid: option, got {answers!r}")
    unknown = sorted(set(answers) - set(_QUESTIONS_BY_QID))
    if unknown:
        raise IntentEnvelopeError(
            f"answers: unknown qid(s) {unknown} — the interview is a fixed manifest; "
            f"valid qids: {sorted(_QUESTIONS_BY_QID)}"
        )
    resolved: dict[str, str] = {}
    for q in INTERVIEW:
        if q.qid in answers:
            value = _require_str(answers[q.qid], where=f"answers[{q.qid}]")
            if value not in q.options:
                raise IntentEnvelopeError(
                    f"answers[{q.qid}]: {value!r} not in {q.options} — typed answers only"
                )
            resolved[q.qid] = value
        elif q.required:
            raise IntentEnvelopeError(f"answers: required qid {q.qid!r} is unanswered")
        elif q.default is None:  # unreachable by construction: optional questions declare defaults
            raise IntentEnvelopeError(f"registry bug: optional qid {q.qid!r} has no default")
        else:
            resolved[q.qid] = q.default
    return IntentEnvelope(
        run_mode=resolved["run_mode"],
        ceremony_gates=CeremonyGates(
            reviews_required=resolved["reviews_required"],
            merge=resolved["merge"],
            deploy_nonprod=resolved["deploy_nonprod"],
        ),
        source=source,
        authored_at=authored_at,
        authored_by=authored_by,
    )


def unanswered_questions(envelope: IntentEnvelope | None) -> tuple[str, ...]:
    """The qids a consumer may still ask — the no-reprompt contract (H-F2-9).

    A valid envelope answers every interview question (gates resolve to explicit values),
    so the result is empty and a consumer that asks anyway is re-asking an answered
    question — exactly what the fleet drift-guard test forbids. ``None`` (no envelope)
    returns every qid: the interview is still owed.
    """
    if envelope is None:
        return tuple(q.qid for q in INTERVIEW)
    envelope.validate()
    return ()


# ---------------------------------------------------------------------------
# Mode-keyed machinery: tier recommendation + spend posture (T12-F3-7/F6-7,
# T1-F6-8). One matrix — the unattended self-selection reads the SAME functions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TierRecommendation:
    model: str
    effort: str
    because: str


def recommend_tier(work_shape: str, run_mode: str) -> TierRecommendation:
    """The mode-aware tier default for a work shape (T12-F6-7).

    ``attended`` recommends the registry default (throughput); ``unattended`` recommends
    exactly one rung cheaper via the ladder ops (cheapest-defensible), respecting the
    ordered escalation ladders (``{#tier-vocab-ordering}``) — at the ladder floor the
    fallback equals the default (a no-op floor, never an error).
    """
    if run_mode not in RUN_MODES:
        raise IntentEnvelopeError(f"run_mode {run_mode!r} not in {RUN_MODES}")
    resolver = _tier_resolver()
    resolution = resolver.resolve(None, work_shape)
    if run_mode == ATTENDED:
        return TierRecommendation(
            model=resolution.model,
            effort=resolution.effort,
            because=f"attended default: {resolution.because}",
        )
    model, effort = resolver.cheaper_fallback(resolution.model, resolution.effort)
    return TierRecommendation(
        model=model,
        effort=effort,
        because=(
            f"unattended: one rung cheaper than the attended default "
            f"{resolution.model}/{resolution.effort} (cheapest-defensible)"
        ),
    )


def spend_posture(run_mode: str) -> tuple[str, str]:
    """The mode-keyed ``(default_posture, approval_rule)`` pair (T12-F3-7).

    ``unattended`` -> (cache-tight, silent): spend the cheap default, never prompt.
    ``attended`` -> (interactive, ask-on-spend-increase): cheapening and steady-state
    proceed silently; a spend INCREASE requires an explicit operator approval token.
    """
    if run_mode not in RUN_MODES:
        raise IntentEnvelopeError(f"run_mode {run_mode!r} not in {RUN_MODES}")
    if run_mode == UNATTENDED:
        return (POSTURE_CACHE_TIGHT, RULE_SILENT)
    return (POSTURE_INTERACTIVE, RULE_ASK_ON_SPEND_INCREASE)


@dataclass(frozen=True)
class SpendDecision:
    """One resolved spend action: what the consumer does, silently or not."""

    run_mode: str
    posture: str
    approval_rule: str
    action: str
    silent: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode,
            "posture": self.posture,
            "approval_rule": self.approval_rule,
            "action": self.action,
            "silent": self.silent,
            "reason": self.reason,
        }


def resolve_spend_action(
    envelope_or_run_mode: IntentEnvelope | str,
    *,
    spend_increase: bool = False,
    approval_token: str | None = None,
) -> SpendDecision:
    """Resolve one spend decision through the envelope — the shared fan-out primitive
    (T4-F4-1) team-execution's Step B1 posture check imports.

    * unattended: always returns the cache-tight default silently — a requested spend
      increase resolves to ``hold-at-default`` (the increase is NOT taken; the run
      proceeds at the default and the decision is recorded), never a prompt.
    * attended + no increase: proceed at the default silently.
    * attended + spend increase + approval token: proceed with the increase.
    * attended + spend increase + NO token: raise :class:`PostureError` — the ask is
      structural, not a prompt convention a consumer can forget.
    """
    if isinstance(envelope_or_run_mode, IntentEnvelope):
        envelope_or_run_mode.validate()
        run_mode = envelope_or_run_mode.run_mode
    else:
        run_mode = envelope_or_run_mode
    posture, rule = spend_posture(run_mode)

    if run_mode == UNATTENDED:
        action = ACTION_HOLD_AT_DEFAULT if spend_increase else ACTION_PROCEED_DEFAULT
        reason = (
            "unattended run: spend increase held at the cache-tight default (no prompt)"
            if spend_increase
            else "unattended run: cache-tight default, silent"
        )
        return SpendDecision(run_mode, posture, rule, action, True, reason)

    if not spend_increase:
        return SpendDecision(
            run_mode,
            posture,
            rule,
            ACTION_PROCEED_DEFAULT,
            True,
            "attended run: no spend increase requested — proceeds silently",
        )
    if approval_token is None:
        raise PostureError(
            "attended run: a spend increase requires an explicit operator approval token "
            "(approval_token) — refusing to escalate spend silently"
        )
    return SpendDecision(
        run_mode,
        posture,
        rule,
        ACTION_PROCEED_INCREASE,
        False,
        f"attended run: spend increase approved by token {approval_token!r} (self-attested)",
    )


@dataclass(frozen=True)
class SpendAuthorization:
    """One pre-dispatch spend decision (#373 T8-F5-7): authorized or step-up-required.

    ``authorized=False`` means the dispatch must HALT for explicit step-up authorization —
    it is NEVER a degrade verdict (spend gating has no lower rung). The checked inputs are
    echoed so the receipt/report can show exactly what was compared.
    """

    authorized: bool
    reason: str
    tier_ceiling: str = ""
    cost_ceiling_tokens: float | None = None
    requested_tier: str | None = None
    actual_tokens: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorized": self.authorized,
            "reason": self.reason,
            "tier_ceiling": self.tier_ceiling,
            "cost_ceiling_tokens": self.cost_ceiling_tokens,
            "requested_tier": self.requested_tier,
            "actual_tokens": self.actual_tokens,
        }


def authorize_spend(
    spend: SpendEnvelope,
    *,
    actual_tokens: float | None = None,
    requested_tier: str | None = None,
) -> SpendAuthorization:
    """The #373 pre-dispatch spend-authorization decision — pure, HALT-only, never a degrade.

    * **Tier gate** (per leaf): with a ``tier_ceiling`` captured and a ``requested_tier``
      declared, a tier STRONGER than the ceiling (``model_rank`` smaller — MODELS is
      strongest-first) is denied; a tier not on the fleet ladder is denied (fail closed —
      an un-rankable tier cannot be proven within the ceiling). A dispatch that declares
      no tier is not tier-escalating and is not tier-gated.
    * **Cost gate** (run-cumulative): with a ``cost_ceiling_tokens`` captured and recorded
      ``actual_tokens`` supplied, dispatch is authorized only while actuals remain STRICTLY
      below the ceiling — actuals at or past it exhaust the budget and deny. ``None``
      actuals mean no telemetry has been recorded yet ("no data yet", the ``outcome_costs``
      honesty stance): nothing is measured against the ceiling, so the cost gate does not
      engage. Actuals are leaf-produced and self-attested (see the module threat model).

    A wrong-TYPED ``actual_tokens`` (bool, non-number, NaN/inf) is a caller error and
    raises — never a silent pass or a coerced comparison.
    """
    spend.validate()
    if actual_tokens is not None and (
        isinstance(actual_tokens, bool)
        or not isinstance(actual_tokens, (int, float))
        or not math.isfinite(float(actual_tokens))
    ):
        raise IntentEnvelopeError(
            f"authorize_spend: actual_tokens must be a finite number or None, got {actual_tokens!r}"
        )
    if requested_tier is not None and not isinstance(requested_tier, str):
        raise IntentEnvelopeError(
            f"authorize_spend: requested_tier must be a string or None, got {requested_tier!r}"
        )
    if spend.tier_ceiling and requested_tier is not None:
        palette = _tier_palette()
        if requested_tier not in palette.MODELS:
            return SpendAuthorization(
                authorized=False,
                reason=(
                    f"requested tier {requested_tier!r} is not on the fleet tier ladder "
                    f"{palette.MODELS} — it cannot be proven within the captured ceiling "
                    f"{spend.tier_ceiling!r}; HALT for step-up authorization (fail closed)"
                ),
                tier_ceiling=spend.tier_ceiling,
                cost_ceiling_tokens=spend.cost_ceiling_tokens,
                requested_tier=requested_tier,
                actual_tokens=actual_tokens,
            )
        if palette.model_rank(requested_tier) < palette.model_rank(spend.tier_ceiling):
            return SpendAuthorization(
                authorized=False,
                reason=(
                    f"tier-escalating dispatch: requested tier {requested_tier!r} is stronger "
                    f"than the captured ceiling {spend.tier_ceiling!r} — HALT for explicit "
                    f"step-up authorization, never a silent degrade to a lower tier"
                ),
                tier_ceiling=spend.tier_ceiling,
                cost_ceiling_tokens=spend.cost_ceiling_tokens,
                requested_tier=requested_tier,
                actual_tokens=actual_tokens,
            )
    if (
        spend.cost_ceiling_tokens is not None
        and actual_tokens is not None
        and float(actual_tokens) >= spend.cost_ceiling_tokens
    ):
        return SpendAuthorization(
            authorized=False,
            reason=(
                f"over-ceiling dispatch: recorded leaf-produced actuals "
                f"({float(actual_tokens):g} tokens) have reached the captured cost "
                f"ceiling ({spend.cost_ceiling_tokens:g} tokens) — HALT for explicit "
                f"step-up authorization, never a silent degrade"
            ),
            tier_ceiling=spend.tier_ceiling,
            cost_ceiling_tokens=spend.cost_ceiling_tokens,
            requested_tier=requested_tier,
            actual_tokens=float(actual_tokens),
        )
    return SpendAuthorization(
        authorized=True,
        reason="within the captured spend envelope (checked against leaf-produced actuals)",
        tier_ceiling=spend.tier_ceiling,
        cost_ceiling_tokens=spend.cost_ceiling_tokens,
        requested_tier=requested_tier,
        actual_tokens=float(actual_tokens) if actual_tokens is not None else None,
    )


@dataclass(frozen=True)
class SelfSelectedPosture:
    """An unattended run's self-selected posture (T1-F6-8): envelope + tier, one matrix."""

    envelope: IntentEnvelope
    tier: TierRecommendation


def self_select_posture(
    work_shape: str, *, source: str = "defaults:unattended", authored_at: str = ""
) -> SelfSelectedPosture:
    """Select an unattended run's posture from the ``(work_shape, run_mode)`` matrix.

    No interactive answer is required: the envelope takes every ceremony gate's safe
    default (GATE) and the tier comes from the SAME :func:`recommend_tier` matrix the
    interview-seeded path uses — one matrix, two entry points.
    """
    envelope = IntentEnvelope(
        run_mode=UNATTENDED,
        ceremony_gates=CeremonyGates(),
        source=source,
        authored_at=authored_at,
    )
    envelope.validate()
    return SelfSelectedPosture(envelope=envelope, tier=recommend_tier(work_shape, UNATTENDED))


# ---------------------------------------------------------------------------
# Issue-carried envelope (G-hybrids-4 / H-F2-9 / S-22): authored once at
# mission-control issue capture, read by `/outcome start`, never re-asked.
# ---------------------------------------------------------------------------


def render_issue_block(envelope: IntentEnvelope) -> str:
    """Render the schema-validated issue-body block mission-control writes at capture."""
    envelope.validate()
    return (
        f"{ISSUE_BLOCK_HEADING}\n\n```{ISSUE_BLOCK_FENCE}\n"
        + json.dumps(envelope.to_dict(), indent=2, sort_keys=False)
        + "\n```\n"
    )


def extract_issue_block(body: str | None) -> str | None:
    """The raw JSON text of the issue body's envelope block; ``None`` when absent.

    More than one block is ambiguous authorship — an error, never a silent first-wins.
    """
    if not body:
        return None
    matches = _ISSUE_BLOCK_RE.findall(body)
    if not matches:
        return None
    if len(matches) > 1:
        raise IntentEnvelopeError(
            f"issue body carries {len(matches)} intent-envelope blocks — exactly one is "
            "the contract; remove the extras"
        )
    return str(matches[0])


def envelope_from_issue_body(body: str | None) -> IntentEnvelope | None:
    """Parse + validate the issue-carried envelope; absent -> ``None``, invalid -> raise."""
    raw = extract_issue_block(body)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntentEnvelopeError(f"intent-envelope block is not valid JSON: {exc}") from exc
    return IntentEnvelope.from_dict(data)


@dataclass(frozen=True)
class StartDecision:
    """`/outcome start`'s envelope decision: skip the interview or fall back to asking."""

    envelope: IntentEnvelope | None
    interview_required: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope": self.envelope.to_dict() if self.envelope is not None else None,
            "interview_required": self.interview_required,
            "reason": self.reason,
        }


def outcome_start_decision(issue_body: str | None) -> StartDecision:
    """Decide whether `/outcome start` may skip the run-start interview (S-22).

    A valid issue-carried envelope skips the interview (ask-once: the operator already
    answered at issue capture). Absent or invalid falls back to asking — an invalid
    envelope is surfaced and NEVER adopted (fail closed), but it does not brick the
    start; the interview simply runs.
    """
    try:
        envelope = envelope_from_issue_body(issue_body)
    except IntentEnvelopeError as exc:
        return StartDecision(None, True, f"issue envelope invalid — interview required: {exc}")
    if envelope is None:
        return StartDecision(None, True, "no intent envelope on the issue — interview required")
    return StartDecision(
        envelope,
        False,
        "valid intent envelope authored at issue capture — interview skipped",
    )
