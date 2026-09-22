"""Unit tests for the provenance manifest schema (U1, saga.manifest.v1)."""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "saga" / "scripts" / "provenance_manifest.py"


def _load():
    spec = importlib.util.spec_from_file_location("provenance_manifest", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["provenance_manifest"] = module
    spec.loader.exec_module(module)
    return module


pm = _load()


def _attribution(kind: str = "external-engine") -> Any:
    return pm.Attribution(kind=pm.ProducerKind(kind), identity="agy/gemini-3.1-pro", effort="high")


def _claim(
    claimed: str = "verified",
    adjudicated: str | None = None,
    mismatch_reason: str | None = None,
    source_ref: str = "plugins/saga/scripts/saga.py:42",
) -> Any:
    return pm.Claim(
        text="the guard rejects stale bases",
        claimed=pm.ClaimedStatus(claimed),
        source_ref=source_ref,
        source_revision="abc1234",
        adjudicated=pm.AdjudicatedStatus(adjudicated) if adjudicated else None,
        mismatch_reason=pm.MismatchReason(mismatch_reason) if mismatch_reason else None,
        adjudication=(
            pm.Adjudication(
                adjudicator="claude/fable-5",
                sources_read=("plugins/saga/scripts/saga.py",),
                scope="diff",
                revision="abc1234",
                decision=adjudicated or "",
            )
            if adjudicated
            else None
        ),
    )


def _manifest(**overrides: Any) -> Any:
    kwargs = {
        "execution_id": "exec-001",
        "saga_ref": "saga-2026-07-01-manifests",
        "attribution": _attribution(),
        "disposition": pm.Disposition.RAN_AS_REQUESTED,
        "created_at": "2026-07-01T00:00:00Z",
    }
    kwargs.update(overrides)
    return pm.Manifest(**kwargs)


def _full_manifest() -> Any:
    return _manifest(
        output_completeness=pm.OutputCompleteness.derive(
            declared_keys=["files_changed", "tests_added"],
            produced_keys=["files_changed"],
            target_count=None,
            produced_count=1,
        ),
        claim_provenance=pm.ClaimProvenance(
            claims=(_claim("verified", "verified"), _claim("inferred"))
        ),
    )


# --- envelope round trip (R1/R9) -----------------------------------------------------


def test_manifest_envelope_round_trip() -> None:
    """Full + lightweight manifests survive to_dict/from_dict; unknown keys rejected."""
    for m in (_manifest(), _full_manifest()):
        again = pm.Manifest.from_dict(m.to_dict())
        assert again == m
        assert again.schema == pm.SCHEMA_VERSION

    # Unknown keys are rejected (decision recorded in module docstring).
    bad = _manifest().to_dict()
    bad["surprise"] = True
    with pytest.raises(pm.ManifestError, match="unknown keys"):
        pm.Manifest.from_dict(bad)

    bad_sub = _full_manifest().to_dict()
    bad_sub["claim_provenance"]["claims"][0]["verdict"] = "ship"
    with pytest.raises(pm.ManifestError, match="unknown keys"):
        pm.Manifest.from_dict(bad_sub)


def test_rejected_offload_manifest_round_trip_requires_normalized_note() -> None:
    rejected = _manifest(
        disposition=pm.Disposition.REJECTED_OFFLOAD,
        disposition_note="Claude rejected an unsupported patch.",
    )
    assert pm.Manifest.from_dict(rejected.to_dict()) == rejected

    missing = rejected.to_dict()
    missing.pop("disposition_note")
    with pytest.raises(pm.ManifestError, match="non-empty disposition_note"):
        pm.Manifest.from_dict(missing)

    for invalid_note in ("", "   ", " not normalized ", "two\nlines", "bad\x00note"):
        payload = rejected.to_dict()
        payload["disposition_note"] = invalid_note
        with pytest.raises(pm.ManifestError, match="disposition_note"):
            pm.Manifest.from_dict(payload)


def test_manifest_round_trips_separate_bounded_tripwire_note() -> None:
    manifest = _manifest(tripwire_note="tripwire_unarmed: observer unavailable")
    assert pm.Manifest.from_dict(manifest.to_dict()) == manifest

    for invalid_note in (" not normalized ", "two\nlines", "bad\x00note"):
        with pytest.raises(pm.ManifestError, match="tripwire_note"):
            _manifest(tripwire_note=invalid_note)
    with pytest.raises(pm.ManifestError, match="exceeds"):
        _manifest(tripwire_note="x" * (pm.MAX_OPERATIONAL_NOTE_BYTES + 1))


def test_manifest_envelope_requires_attribution_and_disposition() -> None:
    """Envelope invalid without R2 attribution and R18 disposition fields."""
    good = _manifest().to_dict()

    no_attr = dict(good)
    no_attr["attribution"] = None
    with pytest.raises(pm.ManifestError, match="attribution"):
        pm.Manifest.from_dict(no_attr)

    empty_identity = dict(good)
    empty_identity["attribution"] = {"kind": "external-engine", "identity": "  "}
    with pytest.raises(pm.ManifestError, match="identity"):
        pm.Manifest.from_dict(empty_identity)

    bad_kind = dict(good)
    bad_kind["attribution"] = {"kind": "shadow-cabal", "identity": "x"}
    with pytest.raises(pm.ManifestError, match="kind"):
        pm.Manifest.from_dict(bad_kind)

    no_dispo = dict(good)
    no_dispo["disposition"] = None
    with pytest.raises(pm.ManifestError, match="disposition"):
        pm.Manifest.from_dict(no_dispo)

    bad_dispo = dict(good)
    bad_dispo["disposition"] = "went-rogue"
    with pytest.raises(pm.ManifestError, match="disposition"):
        pm.Manifest.from_dict(bad_dispo)


def test_manifest_economics_record_round_trips_and_rejects_unknown_keys() -> None:
    economics = pm.EconomicsRecord(
        engine_tokens_avoided=1000,
        chaperone_tokens_spent=200,
        net_savings_tokens=800,
        net_savings_status="positive",
        external_cost_usd=0.004,
    )
    manifest = _manifest(economics=economics)

    data = manifest.to_dict()
    assert data["economics"] == {
        "engine_tokens_avoided": 1000,
        "chaperone_tokens_spent": 200,
        "net_savings_tokens": 800,
        "net_savings_status": "positive",
        "external_cost_usd": 0.004,
    }
    assert pm.Manifest.from_dict(data).economics == economics
    assert pm.tier_of(manifest) is pm.Tier.FULL

    negative = dict(data)
    negative["economics"] = {
        "engine_tokens_avoided": 100,
        "chaperone_tokens_spent": 250,
        "net_savings_tokens": -150,
        "net_savings_status": "negative",
    }
    assert pm.Manifest.from_dict(negative).economics.net_savings_status == "negative"

    bad = dict(data)
    bad["economics"] = {**data["economics"], "provider_budget": 25.0}
    with pytest.raises(pm.ManifestError, match="unknown keys"):
        pm.Manifest.from_dict(bad)

    mismatched_status = dict(data)
    mismatched_status["economics"] = {
        **data["economics"],
        "net_savings_tokens": -800,
        "net_savings_status": "positive",
    }
    with pytest.raises(pm.ManifestError, match="net_savings_status"):
        pm.Manifest.from_dict(mismatched_status)


def test_manifest_envelope_rejects_wrong_schema_version() -> None:
    data = _manifest().to_dict()
    data["schema"] = "saga.manifest.v0"
    with pytest.raises(pm.ManifestError, match="schema"):
        pm.Manifest.from_dict(data)


# --- parroting taxonomy (KTD5/R7) ----------------------------------------------------


def test_parroting_taxonomy_refuted_and_unsupported_counted() -> None:
    """AE1: claimed-verified ∧ adjudicated ∈ {refuted, unsupported} counts as parroting."""
    refuted = _claim("verified", "refuted", "refuted")
    assert pm.is_parroting(refuted) is True

    unsupported = _claim("verified", "not-checked", "unsupported")
    assert pm.is_parroting(unsupported) is True

    honest = _claim("verified", "verified")
    assert pm.is_parroting(honest) is False

    # A claim never claimed-verified cannot parrot, even if refuted.
    humble_refuted = _claim("inferred", "refuted", "refuted")
    assert pm.is_parroting(humble_refuted) is False


def test_parroting_taxonomy_not_adjudicated_excluded() -> None:
    """AE2: an un-adjudicated claimed-verified claim is NOT parroting."""
    claim = _claim("verified", None, "not-adjudicated")
    assert pm.is_parroting(claim) is False
    assert (
        pm.mismatch_reason_for(pm.ClaimedStatus.VERIFIED, None) is pm.MismatchReason.NOT_ADJUDICATED
    )


def test_parroting_taxonomy_source_stale_excluded() -> None:
    """AE2: source-stale mismatches never count as parroting."""
    claim = _claim("verified", "not-checked", "source-stale")
    assert pm.is_parroting(claim) is False
    reason = pm.mismatch_reason_for(
        pm.ClaimedStatus.VERIFIED, pm.AdjudicatedStatus.NOT_CHECKED, source_stale=True
    )
    assert reason is pm.MismatchReason.SOURCE_STALE


def test_parroting_taxonomy_scope_excluded_excluded() -> None:
    claim = _claim("verified", "not-checked", "scope-excluded")
    assert pm.is_parroting(claim) is False
    reason = pm.mismatch_reason_for(
        pm.ClaimedStatus.VERIFIED, pm.AdjudicatedStatus.NOT_CHECKED, in_scope=False
    )
    assert reason is pm.MismatchReason.SCOPE_EXCLUDED


def test_parroting_taxonomy_mismatch_reason_derivation() -> None:
    """mismatch_reason_for covers the KTD5 enum from (claimed, adjudicated) pairs."""
    claimed, reason = pm.ClaimedStatus, pm.MismatchReason
    adj = pm.AdjudicatedStatus
    assert pm.mismatch_reason_for(claimed.VERIFIED, adj.REFUTED) is reason.REFUTED
    assert pm.mismatch_reason_for(claimed.VERIFIED, adj.INFERRED) is reason.UNSUPPORTED
    assert pm.mismatch_reason_for(claimed.VERIFIED, adj.NOT_CHECKED) is reason.UNSUPPORTED
    assert pm.mismatch_reason_for(claimed.VERIFIED, adj.VERIFIED) is None
    assert pm.mismatch_reason_for(claimed.INFERRED, adj.INFERRED) is None


def test_parroting_taxonomy_manifest_count() -> None:
    manifest = _manifest(
        claim_provenance=pm.ClaimProvenance(
            claims=(
                _claim("verified", "refuted", "refuted"),
                _claim("verified", "not-checked", "unsupported"),
                _claim("verified", "verified"),
                _claim("verified", None, "not-adjudicated"),
            )
        )
    )
    assert pm.parroting_count(manifest) == 2
    assert pm.parroting_count(_manifest()) == 0


# --- advisory-only / no verdict surface (R8/R12/R20) ---------------------------------


def test_advisory_never_blocks_no_verdict_field() -> None:
    """Schema exposes no verdict/authority surface (R20/AE7); lightweight tier valid
    with zero subrecords (R9/AE4); validate() reports, never raises (R8)."""
    forbidden = {"verdict", "authority", "gate", "blocking"}
    field_names = set(pm._no_verdict_surface())
    assert not field_names & forbidden

    light = _manifest()
    assert pm.tier_of(light) is pm.Tier.LIGHTWEIGHT
    assert pm.validate(light, pm.Tier.LIGHTWEIGHT) == []

    # Full tier with missing subrecords: advisory problems returned, nothing raised.
    problems = pm.validate(light, "full", gate_feeding=True, contract_bearing=True)
    assert any("claim_provenance" in p for p in problems)
    assert any("output_completeness" in p for p in problems)

    full = _full_manifest()
    assert pm.tier_of(full) is pm.Tier.FULL
    assert pm.validate(full, pm.Tier.FULL, gate_feeding=True, contract_bearing=True) == []


def test_advisory_never_blocks_schema_is_frozen_evidence() -> None:
    """Manifests are immutable evidence records — no mutation surface."""
    m = _manifest()
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.execution_id = "tampered"  # type: ignore[misc]


# --- claims: checkability + completeness diff (R3/R4) --------------------------------


def test_claim_without_source_ref_is_not_checkable() -> None:
    """R4: a claim without a source ref is in the not-checkable state."""
    assert pm.is_checkable(_claim(source_ref="")) is False
    assert pm.is_checkable(_claim(source_ref="   ")) is False
    assert pm.is_checkable(_claim()) is True


def test_output_completeness_derive_diffs_declared_vs_produced() -> None:
    oc = pm.OutputCompleteness.derive(
        declared_keys=["a", "b", "c"], produced_keys=["b"], produced_count=1
    )
    assert oc.missing_keys == ("a", "c")
    assert pm.OutputCompleteness.from_dict(oc.to_dict()) == oc


def test_team_execution_attribution_kind() -> None:
    """R2: team-execution worker attribution validates through the envelope."""
    m = _manifest(attribution=_attribution("team-execution"))
    again = pm.Manifest.from_dict(m.to_dict())
    assert again.attribution.kind is pm.ProducerKind.TEAM_EXECUTION
    assert pm.validate(again, "lightweight") == []


def test_claim_from_dict_rejects_unknown_enum_values() -> None:
    """Corrupt or future-schema enum payloads are rejected loudly, never silently accepted."""
    base = {"text": "t", "claimed": "verified"}
    with pytest.raises(pm.ManifestError, match="valid claimed status"):
        pm.Claim.from_dict({**base, "claimed": "not-a-status"})
    with pytest.raises(pm.ManifestError, match="invalid enum value"):
        pm.Claim.from_dict({**base, "adjudicated": "not-a-status"})
    with pytest.raises(pm.ManifestError, match="invalid enum value"):
        pm.Claim.from_dict({**base, "mismatch_reason": "not-a-reason"})
    with pytest.raises(pm.ManifestError, match="non-empty text"):
        pm.Claim.from_dict({"text": "   ", "claimed": "verified"})
