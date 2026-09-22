"""deploy_handoff.py + handoff_envelope.py tests (issue #395).

This file is the single home for every acceptance-criterion ``-k`` selector (KTD7 — direct lesson
from #347's P2, where an AC selector collected zero tests). U1 owns the schema/ack sections here:

* ``test_ack_envelope_schema_*`` — the offer envelope carries the KTD2 schema fields and survives a
  JSON round-trip (AC1).
* ``test_ack_round_trip_*`` — token + timestamp + identity survive save/load, and every write-once
  guard (double-accept, accept-without-offer, stale/superseded token, empty identity/evidence,
  malformed sidecar) fails loud with a named error (AC4, KTD4).

Supporting coverage: ``authorize_promotion`` gate/auto mechanics (KTD5) and a regression oracle
that the existing mission-control ``build_handoff_envelope`` output is byte-unchanged by the new
delegator (KTD1). The U2/U3 selectors (``gate_or_auto_propagation``,
``ownership_not_released_without_ack``, ``dropped_baton_detected``) land in their own sections.

Test design: an isolated ``tmp_path`` repo root per test — the sidecar lives under
``.claude/saga/sagas/<saga_id>/deploy_handoff.json`` and nothing touches the real state tree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY_HANDOFF_PATH = ROOT / "plugins" / "saga" / "scripts" / "deploy_handoff.py"
HANDOFF_ENVELOPE_PATH = ROOT / "plugins" / "saga" / "scripts" / "handoff_envelope.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


DH = _load("deploy_handoff", DEPLOY_HANDOFF_PATH)
HE = _load("handoff_envelope", HANDOFF_ENVELOPE_PATH)
SAGA = _load("saga", ROOT / "plugins" / "saga" / "scripts" / "saga.py")

SAGA_ID = "issue-395"


def _sidecar_path(root: Path, saga_id: str = SAGA_ID) -> Path:
    return root / ".claude" / "saga" / "sagas" / saga_id / "deploy_handoff.json"


def _write_saga_record(
    root: Path,
    saga_id: str = SAGA_ID,
    *,
    deploy_autonomy: str | None = None,
    pr_refs: list[str] | None = None,
) -> None:
    """Write a minimal derived ``state.json`` so ``deploy_handoff.offer`` can source the
    operator-authored posture from ``sagas[saga_id]`` (U2/KTD3), mirroring what ``saga.py save``
    persists. Omitting a key simulates an older saga that never carried it."""
    state_dir = root / ".claude" / "saga"
    state_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {"saga_id": saga_id}
    if deploy_autonomy is not None:
        summary["deploy_autonomy"] = deploy_autonomy
    if pr_refs is not None:
        summary["pr_refs"] = pr_refs
    (state_dir / "state.json").write_text(
        json.dumps({"sagas": {saga_id: summary}}), encoding="utf-8"
    )


class _NoGit:
    """A runner stub for ``saga.save`` so the integration tests never shell out to git."""

    returncode = 1
    stdout = ""

    def __call__(self, *args: object, **kwargs: object) -> _NoGit:
        return self


@pytest.fixture(autouse=True)
def _isolated_git_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep envelope and CLI persistence tests independent of the process repository."""
    monkeypatch.setattr(HE, "current_git_state", lambda root: {"branch": "", "head": ""})
    for name in ("save", "current_git_state", "aggregate_context", "prior_prs"):
        function = getattr(SAGA, name)
        defaults = dict(function.__kwdefaults__ or {})
        defaults["runner"] = _NoGit()
        monkeypatch.setattr(function, "__kwdefaults__", defaults)


# --------------------------------------------------------------------------- #
# ack_envelope_schema — KTD2 schema fields + JSON round-trip (AC1)
# --------------------------------------------------------------------------- #


def test_ack_envelope_schema_fields_present() -> None:
    envelope = DH.build_envelope(
        SAGA_ID,
        offered_by="work",
        pr_refs=["org/repo#12"],
        token="deadbeef",
        now="2026-07-12T00:00:00+00:00",
    )
    assert set(envelope) == {"token", "payload", "offered_at", "offered_by", "saga_id", "pr_refs"}
    assert envelope["token"] == "deadbeef"
    assert envelope["payload"] == DH.PAYLOAD_GATE  # safe default in this unit
    assert envelope["offered_by"] == "work"
    assert envelope["saga_id"] == SAGA_ID
    assert envelope["pr_refs"] == ["org/repo#12"]
    assert envelope["offered_at"] == "2026-07-12T00:00:00+00:00"


def test_ack_envelope_schema_default_payload_is_gate() -> None:
    # A missing posture can never auto-fire (R5): U1 mints `gate` unless explicitly told otherwise.
    envelope = DH.build_envelope(SAGA_ID)
    assert envelope["payload"] == "gate"
    assert envelope["pr_refs"] == []


def test_ack_envelope_schema_minted_token_is_random_hex() -> None:
    a = DH.build_envelope(SAGA_ID)["token"]
    b = DH.build_envelope(SAGA_ID)["token"]
    assert a != b
    assert len(a) == 32 and int(a, 16) >= 0  # secrets.token_hex(16) -> 32 hex chars


def test_ack_envelope_schema_json_round_trip(tmp_path: Path) -> None:
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work", pr_refs=["org/repo#7"])
    on_disk = json.loads(_sidecar_path(tmp_path).read_text(encoding="utf-8"))
    assert on_disk == record
    assert on_disk["envelope"]["saga_id"] == SAGA_ID
    assert on_disk["ack"] is None
    assert on_disk["superseded"] == []


def test_ack_envelope_schema_rejects_invalid_payload() -> None:
    with pytest.raises(DH.DeployHandoffError):
        DH.build_envelope(SAGA_ID, payload="yolo")


def test_ack_envelope_schema_rejects_traversal_saga_id(tmp_path: Path) -> None:
    with pytest.raises(DH.DeployHandoffError):
        DH.offer(tmp_path, "../escape")


# --------------------------------------------------------------------------- #
# ack_round_trip — token/timestamp/identity survive save/load + write-once guards (AC4, KTD4)
# --------------------------------------------------------------------------- #


def test_ack_round_trip_survives_save_load(tmp_path: Path) -> None:
    offered = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    token = offered["envelope"]["token"]
    updated = DH.accept(
        tmp_path,
        SAGA_ID,
        token,
        acknowledged_by="deploy-bot",
        evidence="promoted nonprod tag v1.2.3",
        now="2026-07-12T01:00:00+00:00",
    )
    reloaded = DH.read(tmp_path, SAGA_ID)
    assert reloaded == updated
    ack = reloaded["ack"]
    assert ack["token"] == token
    assert ack["acknowledged_by"] == "deploy-bot"
    assert ack["acknowledged_at"] == "2026-07-12T01:00:00+00:00"
    assert ack["evidence"] == "promoted nonprod tag v1.2.3"


def test_ack_round_trip_double_accept_refused(tmp_path: Path) -> None:
    offered = DH.offer(tmp_path, SAGA_ID)
    token = offered["envelope"]["token"]
    DH.accept(tmp_path, SAGA_ID, token, acknowledged_by="deploy", evidence="first ack")
    with pytest.raises(DH.AlreadyAcknowledgedError):
        DH.accept(tmp_path, SAGA_ID, token, acknowledged_by="deploy", evidence="second ack")
    # Prior ack intact — a refused second accept is never a silent overwrite.
    ack = DH.read(tmp_path, SAGA_ID)["ack"]
    assert ack["evidence"] == "first ack"


def test_ack_round_trip_accept_without_offer_refused(tmp_path: Path) -> None:
    with pytest.raises(DH.NoOfferError):
        DH.accept(tmp_path, SAGA_ID, "sometoken", acknowledged_by="deploy", evidence="e")


def test_ack_round_trip_token_mismatch_refused(tmp_path: Path) -> None:
    DH.offer(tmp_path, SAGA_ID)
    with pytest.raises(DH.TokenMismatchError):
        DH.accept(tmp_path, SAGA_ID, "not-the-token", acknowledged_by="deploy", evidence="e")
    assert DH.read(tmp_path, SAGA_ID)["ack"] is None


def test_ack_round_trip_stale_superseded_token_refused(tmp_path: Path) -> None:
    first = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    stale_token = first["envelope"]["token"]
    # Re-offer (F2 recovery) rotates the token and supersedes the prior envelope (KTD4).
    second = DH.offer(tmp_path, SAGA_ID, offered_by="work-retry")
    fresh_token = second["envelope"]["token"]
    assert fresh_token != stale_token
    assert second["superseded"][-1]["envelope"]["token"] == stale_token
    # The stale token can never ack the live envelope.
    with pytest.raises(DH.TokenMismatchError):
        DH.accept(tmp_path, SAGA_ID, stale_token, acknowledged_by="deploy", evidence="e")
    # The fresh token still works.
    DH.accept(tmp_path, SAGA_ID, fresh_token, acknowledged_by="deploy", evidence="ok")
    assert DH.read(tmp_path, SAGA_ID)["ack"]["token"] == fresh_token


@pytest.mark.parametrize(
    ("by", "evidence"),
    [("", "e"), ("   ", "e"), ("deploy", ""), ("deploy", "   ")],
)
def test_ack_round_trip_empty_identity_or_evidence_refused(
    tmp_path: Path, by: str, evidence: str
) -> None:
    offered = DH.offer(tmp_path, SAGA_ID)
    token = offered["envelope"]["token"]
    with pytest.raises(DH.EmptyAckFieldError):
        DH.accept(tmp_path, SAGA_ID, token, acknowledged_by=by, evidence=evidence)
    assert DH.read(tmp_path, SAGA_ID)["ack"] is None


def test_ack_round_trip_malformed_sidecar_raises_named_error(tmp_path: Path) -> None:
    path = _sidecar_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(DH.InvalidHandoffError):
        DH.read(tmp_path, SAGA_ID)
    with pytest.raises(DH.InvalidHandoffError):
        DH.accept(tmp_path, SAGA_ID, "t", acknowledged_by="deploy", evidence="e")


def test_ack_round_trip_reoffer_preserves_prior_ack_in_superseded(tmp_path: Path) -> None:
    first = DH.offer(tmp_path, SAGA_ID)
    DH.accept(
        tmp_path, SAGA_ID, first["envelope"]["token"], acknowledged_by="deploy", evidence="done"
    )
    second = DH.offer(tmp_path, SAGA_ID)
    # The prior acked envelope is carried forward, its ack preserved, and the new offer is fresh.
    assert second["ack"] is None
    assert second["superseded"][-1]["ack"]["evidence"] == "done"


# --------------------------------------------------------------------------- #
# authorize_promotion — gate honored mechanically (KTD5)
# --------------------------------------------------------------------------- #


def _record(payload: str) -> dict[str, object]:
    return {"envelope": {"payload": payload}, "ack": None, "superseded": []}


def test_authorize_promotion_auto_authorizes_nonprod() -> None:
    decision = DH.authorize_promotion(_record("auto"), "nonprod")
    assert decision["decision"] == DH.DECISION_AUTHORIZED


def test_authorize_promotion_gate_blocks_nonprod() -> None:
    decision = DH.authorize_promotion(_record("gate"), "nonprod")
    assert decision["decision"] == DH.DECISION_BLOCKED


@pytest.mark.parametrize("env", ["staging", "production"])
def test_authorize_promotion_higher_envs_always_confirm(env: str) -> None:
    # Even an `auto` payload can never authorize staging/production — always confirm (KTD5).
    assert DH.authorize_promotion(_record("auto"), env)["decision"] == DH.DECISION_BLOCKED
    assert DH.authorize_promotion(_record("gate"), env)["decision"] == DH.DECISION_BLOCKED


# --------------------------------------------------------------------------- #
# gate_or_auto_propagation — the posture is READ from the saga record, never an offer
# argument (R2), and drives authorize_promotion (KTD5); absent -> gate (R5). (U2, AC3)
# --------------------------------------------------------------------------- #


def test_gate_or_auto_propagation_auto_authorizes_nonprod(tmp_path: Path) -> None:
    # An operator who authored `auto` on the saga -> the offer payload is `auto` and nonprod
    # promotion is authorized without a further confirmation.
    _write_saga_record(tmp_path, deploy_autonomy="auto")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "auto"
    assert DH.authorize_promotion(record, "nonprod")["decision"] == DH.DECISION_AUTHORIZED


@pytest.mark.parametrize("env", ["staging", "production"])
def test_gate_or_auto_propagation_auto_still_blocks_higher_envs(tmp_path: Path, env: str) -> None:
    # Even an `auto` posture never authorizes staging/production — always confirm (KTD5).
    _write_saga_record(tmp_path, deploy_autonomy="auto")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "auto"
    assert DH.authorize_promotion(record, env)["decision"] == DH.DECISION_BLOCKED


def test_gate_or_auto_propagation_gate_blocks_pending_confirmation(tmp_path: Path) -> None:
    _write_saga_record(tmp_path, deploy_autonomy="gate")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "gate"
    assert DH.authorize_promotion(record, "nonprod")["decision"] == DH.DECISION_BLOCKED


def test_gate_or_auto_propagation_absent_field_defaults_gate(tmp_path: Path) -> None:
    # No state.json at all: a missing posture can never auto-fire (R5 safe direction).
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "gate"
    assert DH.authorize_promotion(record, "nonprod")["decision"] == DH.DECISION_BLOCKED


def test_gate_or_auto_propagation_empty_field_defaults_gate(tmp_path: Path) -> None:
    # A saga record whose deploy_autonomy is the empty-string default reads `gate`, never auto.
    _write_saga_record(tmp_path, deploy_autonomy="")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "gate"


def test_gate_or_auto_propagation_pr_refs_sourced_from_record(tmp_path: Path) -> None:
    _write_saga_record(tmp_path, deploy_autonomy="auto", pr_refs=["org/repo#9", "org/repo#10"])
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["pr_refs"] == ["org/repo#9", "org/repo#10"]


def test_gate_or_auto_propagation_absent_pr_refs_reads_empty(tmp_path: Path) -> None:
    _write_saga_record(tmp_path, deploy_autonomy="auto")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["pr_refs"] == []


def test_gate_or_auto_propagation_posture_from_record_not_offer_argument(tmp_path: Path) -> None:
    # The posture comes from the saga record — there is NO offer-time flag to widen it to auto (R2).
    # The CLI offer parser exposes neither --payload nor --deploy-autonomy nor --pr-ref: passing any
    # of them is a hard argparse error, and the record alone decides the payload.
    _write_saga_record(tmp_path, deploy_autonomy="auto", pr_refs=["org/repo#3"])
    for override in (["--payload", "gate"], ["--deploy-autonomy", "gate"], ["--pr-ref", "x#1"]):
        with pytest.raises(SystemExit):
            DH.main(["--repo-root", str(tmp_path), "offer", "--saga-id", SAGA_ID, *override])
    # With no override possible, the CLI offer reads the record's `auto` posture verbatim.
    assert DH.main(["--repo-root", str(tmp_path), "offer", "--saga-id", SAGA_ID]) == 0
    on_disk = DH.read(tmp_path, SAGA_ID)
    assert on_disk["envelope"]["payload"] == "auto"
    assert on_disk["envelope"]["pr_refs"] == ["org/repo#3"]


@pytest.mark.parametrize(
    ("autonomy", "expected"),
    [("auto", "auto"), ("gate", "gate"), (None, "gate")],
)
def test_gate_or_auto_propagation_end_to_end_through_saga_save(
    tmp_path: Path, autonomy: str | None, expected: str
) -> None:
    """saga.py save persists deploy_autonomy + pr_refs into state.json["sagas"][saga_id], and
    deploy_handoff.offer reads them straight back — the full intent-capture -> offer path (KTD3)."""
    incoming = SAGA.Saga(
        saga_id=SAGA_ID,
        kind="issue",
        id="395",
        destination="nonprod-deploy",
        deploy_autonomy="" if autonomy is None else autonomy,
        pr_refs=["org/repo#42"],
    )
    SAGA.save(tmp_path, incoming, runner=_NoGit())

    summary = json.loads((tmp_path / ".claude" / "saga" / "state.json").read_text())["sagas"][
        SAGA_ID
    ]
    assert summary["deploy_autonomy"] == ("" if autonomy is None else autonomy)
    assert summary["pr_refs"] == ["org/repo#42"]

    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == expected
    assert record["envelope"]["pr_refs"] == ["org/repo#42"]


# --------------------------------------------------------------------------- #
# ownership_not_released_without_ack / dropped_baton_detected — reconcile derives status on
# read, never a committed field (R4/KTD6, U3, AC2/AC5).
# --------------------------------------------------------------------------- #


def test_ownership_not_released_without_ack_reads_unacknowledged(tmp_path: Path) -> None:
    DH.offer(tmp_path, SAGA_ID, offered_by="work", now="2026-07-12T00:00:00+00:00")
    result = DH.reconcile_one(tmp_path, SAGA_ID, now="2026-07-12T01:00:00+00:00")
    assert result["status"] == DH.STATUS_UNACKNOWLEDGED
    # Never "deployed"/"done" — those are not vocabulary this module ever emits.
    assert result["status"] not in {"deployed", "done"}
    assert result["saga_id"] == SAGA_ID
    assert result["offered_by"] == "work"
    assert result["offer_age_seconds"] == pytest.approx(3600.0)


def test_ownership_not_released_without_ack_reads_accepted_once_acked(tmp_path: Path) -> None:
    offered = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    DH.accept(
        tmp_path,
        SAGA_ID,
        offered["envelope"]["token"],
        acknowledged_by="deploy-bot",
        evidence="promoted",
        now="2026-07-12T02:00:00+00:00",
    )
    result = DH.reconcile_one(tmp_path, SAGA_ID)
    assert result["status"] == DH.STATUS_ACCEPTED
    assert result["acknowledged_by"] == "deploy-bot"
    assert result["acknowledged_at"] == "2026-07-12T02:00:00+00:00"


def test_ownership_not_released_without_ack_no_sidecar_reads_no_handoff_not_error(
    tmp_path: Path,
) -> None:
    result = DH.reconcile_one(tmp_path, SAGA_ID)
    assert result == {"saga_id": SAGA_ID, "status": DH.STATUS_NO_HANDOFF}


def test_ownership_not_released_without_ack_cli_exit_codes(tmp_path: Path) -> None:
    # No handoff at all -> clean, exit 0 (the ship-receipt read precedent, removed in #1027:
    # 0 = clean or no-handoff).
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--saga-id", SAGA_ID]) == 0
    # Offered, not acked -> unacknowledged, exit 1.
    DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--saga-id", SAGA_ID]) == 1
    # Acked -> accepted, exit 0 again (clean).
    offered = DH.read(tmp_path, SAGA_ID)
    DH.accept(
        tmp_path,
        SAGA_ID,
        offered["envelope"]["token"],
        acknowledged_by="deploy-bot",
        evidence="promoted",
    )
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--saga-id", SAGA_ID]) == 0


def test_dropped_baton_detected_merged_then_silence_surfaces_on_reconcile(
    tmp_path: Path,
) -> None:
    # The merged-then-silence scenario (F2): work offers toward deploy, then nothing acks it. This
    # must surface on a reconcile read naming the saga and the offer's age — never vanish and never
    # silently read as deployed/done (AC5).
    DH.offer(tmp_path, SAGA_ID, offered_by="work", now="2026-07-12T00:00:00+00:00")
    result = DH.reconcile_one(tmp_path, SAGA_ID, now="2026-07-13T00:00:00+00:00")
    assert result["status"] == DH.STATUS_UNACKNOWLEDGED
    assert result["saga_id"] == SAGA_ID
    assert result["offer_age_seconds"] == pytest.approx(86400.0)


def test_dropped_baton_detected_all_sweep_finds_it_among_other_sagas(tmp_path: Path) -> None:
    # A sibling saga that was never offered toward deploy has no sidecar and must not appear in
    # the sweep — reconcile --all only surfaces sagas that WERE offered.
    other = "issue-100"
    (tmp_path / ".claude" / "saga" / "sagas" / other).mkdir(parents=True, exist_ok=True)

    DH.offer(tmp_path, SAGA_ID, offered_by="work")
    results = DH.reconcile_all(tmp_path)
    assert [r["saga_id"] for r in results] == [SAGA_ID]
    assert results[0]["status"] == DH.STATUS_UNACKNOWLEDGED


def test_dropped_baton_detected_all_sweep_mixed_statuses_and_exit_code(tmp_path: Path) -> None:
    acked_id = "issue-1"
    unacked_id = "issue-2"

    offered = DH.offer(tmp_path, unacked_id, offered_by="work")
    offered_acked = DH.offer(tmp_path, acked_id, offered_by="work")
    DH.accept(
        tmp_path,
        acked_id,
        offered_acked["envelope"]["token"],
        acknowledged_by="deploy-bot",
        evidence="promoted",
    )

    results = DH.reconcile_all(tmp_path)
    by_id = {r["saga_id"]: r["status"] for r in results}
    assert by_id[unacked_id] == DH.STATUS_UNACKNOWLEDGED
    assert by_id[acked_id] == DH.STATUS_ACCEPTED
    assert offered["envelope"]["saga_id"] == unacked_id  # sanity: offer sourced the right saga

    # Any unacknowledged handoff in the sweep exits 1 (dropped baton must not go unnoticed).
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 1


def test_dropped_baton_detected_no_sagas_dir_returns_empty(tmp_path: Path) -> None:
    assert DH.reconcile_all(tmp_path) == []
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 0


# --------------------------------------------------------------------------- #
# Regression — the mission-control envelope is byte-unchanged by the new delegator (KTD1)
# --------------------------------------------------------------------------- #


def test_build_handoff_envelope_output_unchanged(tmp_path: Path) -> None:
    envelope = HE.build_handoff_envelope("docs/plans/x.md", root=tmp_path)
    assert set(envelope) == {
        "schema_version",
        "created_at",
        "source",
        "lifecycle_phase",
        "handoff_maturity",
        "handoff_reason",
        "target_team",
        "target_repo",
        "issue_type",
        "blockers",
        "open_questions",
        "suggested_command",
        "lifecycle_owner",
        "issue_artifact_owner",
        "body_template_owner",
        "git",
    }
    assert envelope["schema_version"] == "1.1"
    assert envelope["lifecycle_owner"] == "saga"
    assert envelope["handoff_maturity"] == "plan-ready"


def test_build_deploy_handoff_envelope_delegates(tmp_path: Path) -> None:
    envelope = HE.build_deploy_handoff_envelope(
        SAGA_ID, offered_by="work", token="cafe", now="2026-07-12T00:00:00+00:00"
    )
    assert envelope["saga_id"] == SAGA_ID
    assert envelope["token"] == "cafe"
    assert envelope["payload"] == "gate"


# --------------------------------------------------------------------------- #
# Code-review fix round (#395): CLI end-to-end coverage, intent-capture
# carry-forward guard, and the invalid-sidecar sweep degrade (review P2).
# --------------------------------------------------------------------------- #


def test_ack_round_trip_accept_cli_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The accept CLI verb had zero end-to-end coverage (review P2) — this drives the argparse
    # wiring (--by -> acknowledged_by) and the success exit code through main().
    offered = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    token = offered["envelope"]["token"]
    rc = DH.main(
        [
            "--repo-root",
            str(tmp_path),
            "accept",
            "--saga-id",
            SAGA_ID,
            "--token",
            token,
            "--by",
            "deploy-bot",
            "--evidence",
            "tag nonprod-v1",
        ]
    )
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ack"]["acknowledged_by"] == "deploy-bot"
    assert out["ack"]["evidence"] == "tag nonprod-v1"


def test_ack_round_trip_accept_cli_error_exits_1_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The CLI error boundary (DeployHandoffError -> message + exit 1, never a traceback) was
    # unexercised by any test (review P2) — the module docstring headlines this contract.
    rc = DH.main(
        [
            "--repo-root",
            str(tmp_path),
            "accept",
            "--saga-id",
            SAGA_ID,
            "--token",
            "cafe",
            "--by",
            "deploy-bot",
            "--evidence",
            "tag",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "deploy_handoff:" in captured.err
    assert "Traceback" not in captured.err


def test_ack_round_trip_read_cli_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # read CLI verb incl. its no-handoff exit-1 path (review P3).
    assert DH.main(["--repo-root", str(tmp_path), "read", "--saga-id", SAGA_ID]) == 1
    assert "no deploy handoff" in capsys.readouterr().err
    DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert DH.main(["--repo-root", str(tmp_path), "read", "--saga-id", SAGA_ID]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["envelope"]["saga_id"] == SAGA_ID


def test_gate_or_auto_propagation_cli_flag_carries_forward_on_omit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Intent-capture regression guard (review P2): an authored `auto` posture must survive a later
    # flagless save — argparse default=None keeps the omitted flag out of explicit_fields so
    # _merge carries the prior tick's value forward instead of restamping it. A regression that
    # flips the default to "gate" would silently downgrade the operator's answered-once posture.
    monkeypatch.chdir(tmp_path)
    assert SAGA.main(["save", "--kind", "issue", "--id", "9395", "--deploy-autonomy", "auto"]) == 0
    assert (
        SAGA.main(["save", "--kind", "issue", "--id", "9395", "--next-step", "flag omitted"]) == 0
    )
    capsys.readouterr()
    state = json.loads((tmp_path / ".claude" / "saga" / "state.json").read_text(encoding="utf-8"))
    assert state["sagas"]["issue-9395"]["deploy_autonomy"] == "auto"
    # End-to-end: offer sources the carried-forward posture from the real persisted record.
    record = DH.offer(tmp_path, "issue-9395", offered_by="work")
    assert record["envelope"]["payload"] == "auto"


def test_gate_or_auto_propagation_cli_flag_explicit_restamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert SAGA.main(["save", "--kind", "issue", "--id", "9395", "--deploy-autonomy", "auto"]) == 0
    assert SAGA.main(["save", "--kind", "issue", "--id", "9395", "--deploy-autonomy", "gate"]) == 0
    capsys.readouterr()
    state = json.loads((tmp_path / ".claude" / "saga" / "state.json").read_text(encoding="utf-8"))
    assert state["sagas"]["issue-9395"]["deploy_autonomy"] == "gate"


def test_gate_or_auto_propagation_corrupt_state_json_defaults_gate(tmp_path: Path) -> None:
    # R5 self-heal (review P3): a present-but-CORRUPT state.json must degrade to the safe gate
    # default, never raise and never read auto.
    state_dir = tmp_path / ".claude" / "saga"
    state_dir.mkdir(parents=True)
    (state_dir / "state.json").write_text("{corrupt", encoding="utf-8")
    record = DH.offer(tmp_path, SAGA_ID, offered_by="work")
    assert record["envelope"]["payload"] == "gate"


def test_ack_round_trip_non_object_json_sidecar_raises_named_error(tmp_path: Path) -> None:
    # Valid JSON that is not an object ([]) trips the isinstance guard, distinct from the
    # JSONDecodeError branch the malformed-sidecar test covers (review P3).
    path = _sidecar_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(DH.InvalidHandoffError):
        DH.reconcile_one(tmp_path, SAGA_ID)


def test_dropped_baton_detected_corrupt_sidecar_degrades_not_aborts_sweep(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Review P2 (reproduced by the correctness lens): one corrupt sidecar must degrade to its own
    # invalid-sidecar entry, never abort the --all sweep and mask a sibling's dropped baton.
    corrupt_id, unacked_id = "issue-1", "issue-2"
    DH.offer(tmp_path, unacked_id, offered_by="work")
    bad = _sidecar_path(tmp_path, corrupt_id)
    bad.parent.mkdir(parents=True)
    bad.write_text("{corrupt", encoding="utf-8")

    results = DH.reconcile_all(tmp_path)
    by_id = {r["saga_id"]: r for r in results}
    assert by_id[unacked_id]["status"] == DH.STATUS_UNACKNOWLEDGED
    assert by_id[corrupt_id]["status"] == DH.STATUS_INVALID_SIDECAR
    assert by_id[corrupt_id]["note"]

    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert {r["saga_id"] for r in out} == {corrupt_id, unacked_id}


def test_dropped_baton_detected_invalid_sidecar_alone_is_not_clean(tmp_path: Path) -> None:
    # An unreadable sidecar with no other handoffs still exits 1 — invalid is never silently clean.
    bad = _sidecar_path(tmp_path, "issue-1")
    bad.parent.mkdir(parents=True)
    bad.write_text("[]", encoding="utf-8")
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 1


def test_dropped_baton_detected_directory_sidecar_degrades_not_aborts_sweep(
    tmp_path: Path,
) -> None:
    # Falsification re-review repro (#395): a sidecar that is a DIRECTORY raises IsADirectoryError
    # from open() before any JSON validation — an OSError, not InvalidHandoffError — and must
    # degrade to invalid-sidecar exactly like malformed JSON, never abort the sweep.
    DH.offer(tmp_path, "issue-2", offered_by="work")
    dir_sidecar = _sidecar_path(tmp_path, "issue-1")
    dir_sidecar.mkdir(parents=True)  # the sidecar path itself is a directory

    results = DH.reconcile_all(tmp_path)
    by_id = {r["saga_id"]: r for r in results}
    assert by_id["issue-2"]["status"] == DH.STATUS_UNACKNOWLEDGED  # sibling still visible
    assert by_id["issue-1"]["status"] == DH.STATUS_INVALID_SIDECAR
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 1


def test_dropped_baton_detected_unreadable_sidecar_degrades_not_aborts_sweep(
    tmp_path: Path,
) -> None:
    # PermissionError branch of the same falsification repro. Meaningless when running as root
    # (root reads through chmod 000), so skip there — CI and dev boxes run unprivileged.
    if os.geteuid() == 0:  # pragma: no cover - CI/dev never run as root
        pytest.skip("chmod 000 is not enforced for root")
    DH.offer(tmp_path, "issue-2", offered_by="work")
    unreadable = _sidecar_path(tmp_path, "issue-1")
    unreadable.parent.mkdir(parents=True)
    unreadable.write_text("{}", encoding="utf-8")
    unreadable.chmod(0)
    try:
        results = DH.reconcile_all(tmp_path)
        by_id = {r["saga_id"]: r for r in results}
        assert by_id["issue-2"]["status"] == DH.STATUS_UNACKNOWLEDGED
        assert by_id["issue-1"]["status"] == DH.STATUS_INVALID_SIDECAR
    finally:
        unreadable.chmod(0o644)  # so tmp_path teardown can remove it


def test_dropped_baton_detected_fifo_sidecar_degrades_without_hanging(tmp_path: Path) -> None:
    # Falsification round 2 (#395): a FIFO sidecar with no writer makes a blocking open() hang
    # FOREVER — nothing raised, so no except clause can save the sweep. The regular-file stat
    # check in _read_sidecar must refuse it before open(). SIGALRM guards this test against a
    # regression re-introducing the hang.
    import signal

    DH.offer(tmp_path, "issue-2", offered_by="work")
    fifo = _sidecar_path(tmp_path, "issue-1")
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)

    def _timeout(signum: int, frame: object) -> None:  # pragma: no cover - fires only on hang
        raise TimeoutError("reconcile_all hung on a FIFO sidecar (regression)")

    old = signal.signal(signal.SIGALRM, _timeout)
    signal.alarm(10)
    try:
        results = DH.reconcile_all(tmp_path)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

    by_id = {r["saga_id"]: r for r in results}
    assert by_id["issue-2"]["status"] == DH.STATUS_UNACKNOWLEDGED
    assert by_id["issue-1"]["status"] == DH.STATUS_INVALID_SIDECAR
    assert "not a regular file" in by_id["issue-1"]["note"]


def test_dropped_baton_detected_dangling_symlink_surfaces_as_invalid(tmp_path: Path) -> None:
    # Falsification round 2 (#395): a dangling-symlink sidecar was silently skipped (exists()
    # follows the link -> False -> read as never-offered). Something WAS there — a lost offer —
    # so it must surface as invalid-sidecar and make the sweep not-clean.
    DH.offer(tmp_path, "issue-2", offered_by="work")
    dangling = _sidecar_path(tmp_path, "issue-1")
    dangling.parent.mkdir(parents=True)
    dangling.symlink_to(tmp_path / "no-such-target.json")

    results = DH.reconcile_all(tmp_path)
    by_id = {r["saga_id"]: r for r in results}
    assert by_id["issue-2"]["status"] == DH.STATUS_UNACKNOWLEDGED
    assert by_id["issue-1"]["status"] == DH.STATUS_INVALID_SIDECAR
    assert "dangling symlink" in by_id["issue-1"]["note"]
    assert DH.main(["--repo-root", str(tmp_path), "reconcile", "--all"]) == 1


def test_ownership_not_released_without_ack_single_saga_oserror_is_message_not_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Falsification round 2 (#395): reconcile --saga-id on a directory-shaped sidecar escaped
    # main()'s DeployHandoffError boundary as a raw IsADirectoryError traceback, contradicting
    # the module's own 'never a traceback' contract. _read_sidecar now wraps every OSError class
    # into InvalidHandoffError, so the CLI reports a message and exits 1.
    dir_sidecar = _sidecar_path(tmp_path, "issue-1")
    dir_sidecar.mkdir(parents=True)
    rc = DH.main(["--repo-root", str(tmp_path), "reconcile", "--saga-id", "issue-1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "deploy_handoff:" in err
    assert "Traceback" not in err
