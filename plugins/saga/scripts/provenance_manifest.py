#!/usr/bin/env python3
"""Provenance manifest schema — the typed contract for delegated-output evidence.

One envelope per delegated execution (``schema: saga.manifest.v1``, KTD3), carrying two
optional subrecords:

- ``OutputCompleteness`` — declared vs produced (R3), field-compatible with what
  ``completeness_gate.Contract`` + ``classify()`` already compute.
- ``ClaimProvenance`` — source-attributed claims with the two-layer producer-*claimed* vs
  Claude-*adjudicated* tag (R4-R7), plus an attested ``Adjudication`` record (R6).

Design decisions recorded here (load-bearing for tests):

- **Unknown keys are REJECTED** by ``from_dict`` (raise ``ManifestError``). A versioned
  schema (``saga.manifest.v1``) prefers loud drift over silent key-dropping; forward
  compatibility is handled by minting ``v2``, not by tolerating strays.
- **No verdict or authority surface** (R20/R12): the schema records evidence only. No
  field on any dataclass is named ``verdict`` or ``authority``, no method mutates gates,
  and consumers treat every field as advisory (R8).
- **Parroting taxonomy** (KTD5/R7): a claim counts as parroting iff it was
  producer-claimed ``verified`` AND Claude adjudication lands in {``refuted``,
  ``unsupported``}. ``refuted`` is an adjudicated status; ``unsupported`` is expressed
  through ``mismatch_reason`` (a claimed-verified claim the adjudicator could not
  support). ``not-adjudicated``, ``scope-excluded``, and ``source-stale`` never count.
- **Tier sizing** (KTD9/R9): one schema, two tiers. ``lightweight`` is a valid envelope
  with zero subrecords; ``full`` (gate-feeding / contract-bearing outputs) must carry the
  relevant subrecord(s).

Pure Python, stdlib only, no I/O at import — same house pattern as
``completeness_gate.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "saga.manifest.v1"
MAX_OPERATIONAL_NOTE_BYTES = 1024


class ManifestError(ValueError):
    """A manifest payload violates the saga.manifest.v1 schema."""


class ProducerKind(StrEnum):
    """Who produced the delegated output (R2)."""

    EXTERNAL_ENGINE = "external-engine"
    TEAM_EXECUTION = "team-execution"
    CC_WORKFLOWS = "cc-workflows"


class Disposition(StrEnum):
    """How the delegation actually ran vs how it was requested (R18)."""

    RAN_AS_REQUESTED = "ran-as-requested"
    FELL_BACK_TO_CLAUDE = "fell-back-to-claude"
    SUBSTITUTED_ENGINE = "substituted-engine"
    # A dispatch reported "ok" but carried no schema-valid `bridge_receipt.v1` proof of
    # execution (plan `2026-07-06-...pair-plan.md` U6, KTD8, #383 DoD 2). Distinct from
    # `FELL_BACK_TO_CLAUDE` -- nothing fell back, the engine ran -- and distinct from
    # `RAN_AS_REQUESTED` -- derived truth must not assert proof that doesn't exist.
    UNPROVEN = "unproven"
    # Two-signal divergence (#384 U5, KTD6/R4): the engine's self-report and the independent
    # observer signal (bundle launch flag + schema-valid receipt) DISAGREE about whether the
    # delegation genuinely ran. Named at the dispatch/manifest layer -- the only place both
    # signals meet -- never silently resolved in either direction. Distinct from `UNPROVEN`
    # (single missing proof, no contradiction) and from `FELL_BACK_TO_CLAUDE` (an admitted
    # failure, not a disputed success).
    DELEGATION_INTEGRITY = "delegation-integrity"
    # A receipt exists and passes the base `bridge_receipt.v1` schema, but the stronger #388
    # proof contract fails: missing output attestation, hash mismatch, zero external tokens, or
    # producer/consumer liveness contradiction. This is distinct from `UNPROVEN` because the
    # bridge did emit a receipt; the receipt's proof claims are not trustworthy.
    PROOF_INTEGRITY = "proof-integrity"
    # The engine ran, but Claude's chaperone rejected its output after review. The rejection
    # remains advisory evidence for reviewers/validators; it is neither a dispatch fallback nor
    # an accepted run. Every such manifest must carry a normalized non-empty disposition note.
    REJECTED_OFFLOAD = "rejected-offload"


class ClaimedStatus(StrEnum):
    """Producer-claimed verification status (KTD4/R5)."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    NOT_CHECKED = "not-checked"


class AdjudicatedStatus(StrEnum):
    """Claude-adjudicated verification status (KTD5/R6)."""

    VERIFIED = "verified"
    INFERRED = "inferred"
    NOT_CHECKED = "not-checked"
    REFUTED = "refuted"


class MismatchReason(StrEnum):
    """Why claimed and adjudicated layers disagree (KTD5/R7)."""

    NOT_ADJUDICATED = "not-adjudicated"
    SCOPE_EXCLUDED = "scope-excluded"
    SOURCE_STALE = "source-stale"
    UNSUPPORTED = "unsupported"
    REFUTED = "refuted"


class Tier(StrEnum):
    """Payload sizing tier (KTD9/R9)."""

    LIGHTWEIGHT = "lightweight"
    FULL = "full"


@dataclass(frozen=True)
class Attribution:
    """Producer attribution: who/what emitted this output (R2)."""

    kind: ProducerKind
    identity: str
    effort: str = ""
    protocol: str = ""
    # The leaf's DECLARED sandbox (#287 U5/R7) -- pre-hoc scope beside the post-hoc record.
    # Optional and absent-tolerant: an empty value emits no key, so existing manifests round-trip
    # byte-identical and the schema stays saga.manifest.v1 (additive field, no SCHEMA_VERSION bump).
    sandbox: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind.value,
            "identity": self.identity,
            "effort": self.effort,
            "protocol": self.protocol,
        }
        if self.sandbox:
            out["sandbox"] = self.sandbox
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attribution:
        _reject_unknown_keys(
            data, {"kind", "identity", "effort", "protocol", "sandbox"}, "attribution"
        )
        try:
            kind = ProducerKind(data["kind"])
        except (KeyError, ValueError) as exc:
            raise ManifestError(f"attribution requires a valid kind: {exc}") from exc
        identity = data.get("identity", "")
        if not isinstance(identity, str) or not identity.strip():
            raise ManifestError("attribution requires a non-empty identity")
        return cls(
            kind=kind,
            identity=identity,
            effort=str(data.get("effort", "")),
            protocol=str(data.get("protocol", "")),
            sandbox=str(data.get("sandbox", "")),
        )


@dataclass(frozen=True)
class Adjudication:
    """Attested record of a Claude adjudication pass (D5/R6)."""

    adjudicator: str
    sources_read: tuple[str, ...] = ()
    scope: str = ""
    revision: str = ""
    decision: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjudicator": self.adjudicator,
            "sources_read": list(self.sources_read),
            "scope": self.scope,
            "revision": self.revision,
            "decision": self.decision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Adjudication:
        _reject_unknown_keys(
            data,
            {"adjudicator", "sources_read", "scope", "revision", "decision"},
            "adjudication",
        )
        adjudicator = data.get("adjudicator", "")
        if not isinstance(adjudicator, str) or not adjudicator.strip():
            raise ManifestError("adjudication requires a non-empty adjudicator")
        return cls(
            adjudicator=adjudicator,
            sources_read=tuple(str(s) for s in data.get("sources_read", [])),
            scope=str(data.get("scope", "")),
            revision=str(data.get("revision", "")),
            decision=str(data.get("decision", "")),
        )


@dataclass(frozen=True)
class Claim:
    """One source-attributed claim with the two-layer status tag (R4-R7)."""

    text: str
    claimed: ClaimedStatus
    source_ref: str = ""
    source_revision: str = ""
    adjudicated: AdjudicatedStatus | None = None
    mismatch_reason: MismatchReason | None = None
    adjudication: Adjudication | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "claimed": self.claimed.value,
            "source_ref": self.source_ref,
            "source_revision": self.source_revision,
            "adjudicated": self.adjudicated.value if self.adjudicated else None,
            "mismatch_reason": self.mismatch_reason.value if self.mismatch_reason else None,
            "adjudication": self.adjudication.to_dict() if self.adjudication else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        _reject_unknown_keys(
            data,
            {
                "text",
                "claimed",
                "source_ref",
                "source_revision",
                "adjudicated",
                "mismatch_reason",
                "adjudication",
            },
            "claim",
        )
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise ManifestError("claim requires non-empty text")
        try:
            claimed = ClaimedStatus(data["claimed"])
        except (KeyError, ValueError) as exc:
            raise ManifestError(f"claim requires a valid claimed status: {exc}") from exc
        adjudicated_raw = data.get("adjudicated")
        mismatch_raw = data.get("mismatch_reason")
        adjudication_raw = data.get("adjudication")
        try:
            adjudicated = AdjudicatedStatus(adjudicated_raw) if adjudicated_raw else None
            mismatch = MismatchReason(mismatch_raw) if mismatch_raw else None
        except ValueError as exc:
            raise ManifestError(f"claim has an invalid enum value: {exc}") from exc
        return cls(
            text=text,
            claimed=claimed,
            source_ref=str(data.get("source_ref", "") or ""),
            source_revision=str(data.get("source_revision", "") or ""),
            adjudicated=adjudicated,
            mismatch_reason=mismatch,
            adjudication=Adjudication.from_dict(adjudication_raw) if adjudication_raw else None,
        )


@dataclass(frozen=True)
class OutputCompleteness:
    """Declared-vs-produced subrecord (R3) — mirrors completeness_gate's Contract view."""

    declared_keys: tuple[str, ...] = ()
    target_count: int | None = None
    produced_keys: tuple[str, ...] = ()
    produced_count: int | None = None
    missing_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "declared_keys": list(self.declared_keys),
            "target_count": self.target_count,
            "produced_keys": list(self.produced_keys),
            "produced_count": self.produced_count,
            "missing_keys": list(self.missing_keys),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputCompleteness:
        _reject_unknown_keys(
            data,
            {"declared_keys", "target_count", "produced_keys", "produced_count", "missing_keys"},
            "output_completeness",
        )
        return cls(
            declared_keys=tuple(str(k) for k in data.get("declared_keys", [])),
            target_count=data.get("target_count"),
            produced_keys=tuple(str(k) for k in data.get("produced_keys", [])),
            produced_count=data.get("produced_count"),
            missing_keys=tuple(str(k) for k in data.get("missing_keys", [])),
        )

    @classmethod
    def derive(
        cls,
        *,
        declared_keys: list[str] | None = None,
        target_count: int | None = None,
        produced_keys: list[str] | None = None,
        produced_count: int | None = None,
    ) -> OutputCompleteness:
        """Compute the diff between declared and produced keys."""
        declared = tuple(declared_keys or [])
        produced = tuple(produced_keys or [])
        missing = tuple(k for k in declared if k not in produced)
        return cls(
            declared_keys=declared,
            target_count=target_count,
            produced_keys=produced,
            produced_count=produced_count,
            missing_keys=missing,
        )


@dataclass(frozen=True)
class ClaimProvenance:
    """Claim-provenance subrecord: the list of source-attributed claims (R4)."""

    claims: tuple[Claim, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"claims": [c.to_dict() for c in self.claims]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClaimProvenance:
        _reject_unknown_keys(data, {"claims"}, "claim_provenance")
        claims_raw = data.get("claims", [])
        if not isinstance(claims_raw, list):
            raise ManifestError("claim_provenance.claims must be a list")
        return cls(claims=tuple(Claim.from_dict(c) for c in claims_raw))


@dataclass(frozen=True)
class EconomicsRecord:
    """Typed net-savings economics record for an external-engine dispatch (#386)."""

    engine_tokens_avoided: int
    chaperone_tokens_spent: int
    net_savings_tokens: int
    net_savings_status: str
    external_cost_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "engine_tokens_avoided": self.engine_tokens_avoided,
            "chaperone_tokens_spent": self.chaperone_tokens_spent,
            "net_savings_tokens": self.net_savings_tokens,
            "net_savings_status": self.net_savings_status,
        }
        if self.external_cost_usd is not None:
            data["external_cost_usd"] = self.external_cost_usd
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EconomicsRecord:
        _reject_unknown_keys(
            data,
            {
                "engine_tokens_avoided",
                "chaperone_tokens_spent",
                "net_savings_tokens",
                "net_savings_status",
                "external_cost_usd",
            },
            "economics",
        )
        status = data.get("net_savings_status", "")
        if status not in {"positive", "zero", "negative"}:
            raise ManifestError("economics requires net_savings_status positive|zero|negative")
        net_savings_tokens = _required_int(data, "net_savings_tokens", "economics")
        if net_savings_tokens > 0:
            expected_status = "positive"
        elif net_savings_tokens == 0:
            expected_status = "zero"
        else:
            expected_status = "negative"
        if status != expected_status:
            raise ManifestError("economics net_savings_status must match net_savings_tokens")
        return cls(
            engine_tokens_avoided=_required_int(data, "engine_tokens_avoided", "economics"),
            chaperone_tokens_spent=_required_int(data, "chaperone_tokens_spent", "economics"),
            net_savings_tokens=net_savings_tokens,
            net_savings_status=str(status),
            external_cost_usd=_optional_number(data.get("external_cost_usd"), "external_cost_usd"),
        )


def _validate_normalized_note(note: Any, *, field: str, required: bool) -> None:
    """Validate bounded operational text before it can enter a durable manifest."""
    if not isinstance(note, str):
        raise ManifestError(f"{field} must be a string")
    normalized = " ".join(note.split())
    if required and not normalized:
        raise ManifestError(f"{field} requires a non-empty disposition_note")
    if not normalized:
        if note:
            raise ManifestError(f"{field} must use normalized whitespace")
        return
    if any(ord(char) < 32 for char in normalized):
        raise ManifestError(f"{field} must not contain control characters")
    if len(normalized.encode("utf-8")) > MAX_OPERATIONAL_NOTE_BYTES:
        raise ManifestError(f"{field} exceeds {MAX_OPERATIONAL_NOTE_BYTES} bytes")
    if note != normalized:
        raise ManifestError(f"{field} must use normalized whitespace")


@dataclass(frozen=True)
class Manifest:
    """The saga.manifest.v1 envelope — one per delegated execution (R1).

    Holds evidence only: no verdict field, no authority surface (R20/R12).
    """

    execution_id: str
    saga_ref: str
    attribution: Attribution
    disposition: Disposition
    created_at: str
    disposition_note: str = ""
    output_completeness: OutputCompleteness | None = None
    claim_provenance: ClaimProvenance | None = None
    economics: EconomicsRecord | None = None
    bridge_run_key: str = ""
    tripwire_note: str = ""
    schema: str = field(default=SCHEMA_VERSION)

    def __post_init__(self) -> None:
        if self.disposition is Disposition.REJECTED_OFFLOAD:
            _validate_normalized_note(
                self.disposition_note,
                field="rejected-offload disposition_note",
                required=True,
            )
        if self.tripwire_note:
            _validate_normalized_note(
                self.tripwire_note,
                field="tripwire_note",
                required=False,
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema": self.schema,
            "execution_id": self.execution_id,
            "saga_ref": self.saga_ref,
            "attribution": self.attribution.to_dict(),
            "disposition": self.disposition.value,
            "disposition_note": self.disposition_note,
            "created_at": self.created_at,
            "output_completeness": (
                self.output_completeness.to_dict() if self.output_completeness else None
            ),
            "claim_provenance": (
                self.claim_provenance.to_dict() if self.claim_provenance else None
            ),
            "economics": self.economics.to_dict() if self.economics else None,
        }
        if self.bridge_run_key:
            data["bridge_run_key"] = self.bridge_run_key
        if self.tripwire_note:
            data["tripwire_note"] = self.tripwire_note
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        _reject_unknown_keys(
            data,
            {
                "schema",
                "execution_id",
                "saga_ref",
                "attribution",
                "disposition",
                "disposition_note",
                "created_at",
                "output_completeness",
                "claim_provenance",
                "economics",
                "bridge_run_key",
                "tripwire_note",
            },
            "manifest",
        )
        schema = data.get("schema")
        if schema != SCHEMA_VERSION:
            raise ManifestError(f"unsupported manifest schema {schema!r} (want {SCHEMA_VERSION!r})")
        execution_id = data.get("execution_id", "")
        if not isinstance(execution_id, str) or not execution_id.strip():
            raise ManifestError("manifest requires a non-empty execution_id")
        attribution_raw = data.get("attribution")
        if not isinstance(attribution_raw, dict):
            raise ManifestError("manifest requires an attribution record (R2)")
        disposition_raw = data.get("disposition")
        if not isinstance(disposition_raw, str):
            raise ManifestError("manifest requires a disposition (R18)")
        try:
            disposition = Disposition(disposition_raw)
        except ValueError as exc:
            raise ManifestError(f"manifest requires a valid disposition (R18): {exc}") from exc
        oc_raw = data.get("output_completeness")
        cp_raw = data.get("claim_provenance")
        economics_raw = data.get("economics")
        return cls(
            execution_id=execution_id,
            saga_ref=str(data.get("saga_ref", "") or ""),
            attribution=Attribution.from_dict(attribution_raw),
            disposition=disposition,
            disposition_note=str(data.get("disposition_note", "") or ""),
            created_at=str(data.get("created_at", "") or ""),
            output_completeness=OutputCompleteness.from_dict(oc_raw) if oc_raw else None,
            claim_provenance=ClaimProvenance.from_dict(cp_raw) if cp_raw else None,
            economics=EconomicsRecord.from_dict(economics_raw) if economics_raw else None,
            bridge_run_key=str(data.get("bridge_run_key", "") or ""),
            tripwire_note=str(data.get("tripwire_note", "") or ""),
        )


# --- Pure predicates: parroting taxonomy (KTD5/R7) --------------------------------------


def is_checkable(claim: Claim) -> bool:
    """A claim without a source ref is not checkable (R4)."""
    return bool(claim.source_ref.strip())


def is_parroting(claim: Claim) -> bool:
    """Parroting iff producer-claimed verified AND adjudication refuted it or found it
    unsupported (KTD5/R7). not-adjudicated / scope-excluded / source-stale never count."""
    if claim.claimed is not ClaimedStatus.VERIFIED:
        return False
    if claim.adjudicated is AdjudicatedStatus.REFUTED:
        return True
    return claim.mismatch_reason is MismatchReason.UNSUPPORTED


def mismatch_reason_for(
    claimed: ClaimedStatus,
    adjudicated: AdjudicatedStatus | None,
    *,
    in_scope: bool = True,
    source_stale: bool = False,
) -> MismatchReason | None:
    """Derive the mismatch_reason for a (claimed, adjudicated) pair (KTD5)."""
    if adjudicated is None:
        return MismatchReason.NOT_ADJUDICATED
    if not in_scope:
        return MismatchReason.SCOPE_EXCLUDED
    if source_stale:
        return MismatchReason.SOURCE_STALE
    if adjudicated is AdjudicatedStatus.REFUTED:
        return MismatchReason.REFUTED
    if claimed is ClaimedStatus.VERIFIED and adjudicated in (
        AdjudicatedStatus.INFERRED,
        AdjudicatedStatus.NOT_CHECKED,
    ):
        return MismatchReason.UNSUPPORTED
    return None


def parroting_count(manifest: Manifest) -> int:
    """Count parroting claims in a manifest's claim_provenance (0 when absent)."""
    if manifest.claim_provenance is None:
        return 0
    return sum(1 for c in manifest.claim_provenance.claims if is_parroting(c))


# --- Tier sizing (KTD9/R9) ---------------------------------------------------------------


def tier_of(manifest: Manifest) -> Tier:
    """Derive the payload tier: full when any subrecord is present, else lightweight."""
    if (
        manifest.output_completeness is not None
        or manifest.claim_provenance is not None
        or manifest.economics is not None
    ):
        return Tier.FULL
    return Tier.LIGHTWEIGHT


def validate(
    manifest: Manifest,
    tier: Tier | str,
    *,
    gate_feeding: bool = False,
    contract_bearing: bool = False,
) -> list[str]:
    """Validate a manifest against a tier; returns a list of problems (empty = valid).

    Advisory by construction (R8): callers receive findings, never a raised gate.
    Lightweight manifests are valid with zero subrecords; full-tier gate-feeding
    outputs must carry claim_provenance, contract-bearing outputs output_completeness.
    """
    tier = Tier(tier)
    problems: list[str] = []
    if manifest.schema != SCHEMA_VERSION:
        problems.append(f"unsupported schema {manifest.schema!r}")
    if not manifest.execution_id.strip():
        problems.append("missing execution_id")
    if not manifest.attribution.identity.strip():
        problems.append("missing attribution identity (R2)")
    if tier is Tier.FULL:
        if gate_feeding and manifest.claim_provenance is None:
            problems.append("full-tier gate-feeding output requires claim_provenance (R9)")
        if contract_bearing and manifest.output_completeness is None:
            problems.append("full-tier contract-bearing output requires output_completeness (R9)")
    return problems


def _reject_unknown_keys(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(f"{where} has unknown keys: {', '.join(unknown)}")


def _required_int(data: dict[str, Any], field_name: str, where: str) -> int:
    value = data.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{where}.{field_name} must be an integer")
    return value


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ManifestError(f"economics.{field_name} must be a number")
    return float(value)


def _no_verdict_surface() -> list[str]:
    """Introspection helper for R20 tests: field names across all schema dataclasses."""
    names: list[str] = []
    for cls in (
        Manifest,
        Attribution,
        Adjudication,
        Claim,
        OutputCompleteness,
        ClaimProvenance,
        EconomicsRecord,
    ):
        names.extend(f.name for f in fields(cls))
    return names
