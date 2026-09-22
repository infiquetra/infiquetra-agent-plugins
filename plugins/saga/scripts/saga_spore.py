#!/usr/bin/env python3
"""Saga spore: the structured re-grounding cache for the mid-run compaction boundary (issue #281).

When a long ``/work`` / ``/loop`` / ``/outcome`` session fills the context window the harness
**auto-compacts** — it replaces the conversation with a prose summary and the *same* session keeps
running. The structured saga facts the run depends on (the OutcomeOrchestrator ready frontier, open
leaf ids, per-leaf state, the active saga's phase / ``next_step``) get blurred into that prose or
dropped. The **spore** guards exactly that boundary: a ``PreCompact`` hook freezes those facts here at
the boundary, and a ``SessionStart(source=compact)`` hook re-injects them so the continuing session
re-grounds on facts, not prose.

This module is the pure, offline-testable core — the two hooks (``precompact_spore_hook`` /
``compact_spore_session_hook``) are thin shells over it:

* :func:`build_spore` freezes the active saga box and the run record (issue 1030 removed the
  at the instant of the call — KTD3/KTD4) into a structured dict.
* :func:`serialize` renders that dict into the self-describing ``additionalContext`` block, applying the
  deterministic R5 byte budget with the **ready frontier never dropped**.
* :func:`dump` / :func:`load_and_validate` are the on-disk write / read seam (session-keyed JSON under
  ``<git-common-dir>/saga-spores/``, with the R9 ``saga_id`` + repo-root mismatch guard).

House pattern (mirrors ``outcome_store.py`` / ``saga.py``): pure-ish functions over explicit values, a
dependency-injected ``now``, a ``sys.path`` shim to import the sibling modules, and **no I/O at import**.
The spore is the *anchor, not the authority* (R11) — it AUGMENTS the post-compaction window beside the
harness summary; committed docs + GitHub stay authoritative on conflict about durable state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Import the sibling scripts by path so the spore reuses the single source of truth for the DAG
# (``outcome``), the git-common-dir cache mechanics (``outcome_store``), and the saga envelope
# (``saga``) rather than re-deriving any of them. Mirrors the shim ``outcome_store`` itself uses.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_record  # noqa: E402
import saga  # noqa: E402

SCHEMA = "saga.spore.v1"

# The subdirectory under the git common dir that holds every session's spore. Namespaced beside
# ``outcome_store``'s ``saga-outcomes`` so it is shared by every worktree but never committed (R6/KD3).
SPORE_NAMESPACE = "saga-spores"

# Byte budget for the *rendered block* (KTD2). The harness SessionStart ``additionalContext`` cap is
# 10,000 chars and spills to a file beyond it (GC1) — so this ~9k budget keeps the resumable core in the
# immediately-visible preview rather than behind a file read, while leaving headroom under the cap.
SPORE_BUDGET_CHARS = 9000

# The leading authority instruction (R10/KD6): structured facts win on *durable* conflict, but newer
# in-flight work in the prose summary is real — reconcile, do not regress.
_AUTHORITY = (
    "The preceding prose summary is lossy. The structured facts below are AUTHORITATIVE for durable "
    "state on conflict (open leaves, the ready frontier, the saga's phase/next_step) — but reconcile "
    "any newer in-flight progress from the summary; do not regress to this snapshot's floor."
)


# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------


def spore_path(common_dir: Path, session_id: str) -> Path:
    """``<common-dir>/saga-spores/<session_id>.json`` — session-keyed, worktree-stable (R6/R9).

    Uses :func:`_safe_name` so a hostile ``session_id`` cannot escape the directory.
    """
    safe = run_record._safe_session_name(session_id)
    return Path(common_dir) / SPORE_NAMESPACE / f"{safe}.json"


# ---------------------------------------------------------------------------
# Resolve the active saga (R2) + its outcome (R3/KTD4)
# ---------------------------------------------------------------------------


def resolve_active_saga(repo_root: Path) -> dict[str, Any] | None:
    """The active saga's box + pointer fields, or None when absent/malformed (never raises).

    ``state.json:active_saga_id`` (``saga.py`` per-worktree last-write) names *which* saga; ``saga.restore``
    cold-reconstructs it from its latest tick (no git/subprocess), giving the five index-resident R2
    fields PLUS ``blockers`` / ``open_questions`` (the C1 fields the ``state.json`` summary omits) and the
    R4 pointers in one read. ``checks_run`` is intentionally absent — it is persisted nowhere, so it
    cannot be carried (C1).
    """
    repo_root = Path(repo_root)
    state_path = repo_root / saga.STATE_DIR / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    active_id = state.get("active_saga_id")
    if not isinstance(active_id, str) or not active_id:
        return None
    try:
        restored = saga.restore(repo_root, active_id)
    except Exception:  # noqa: BLE001 — the spore never raises into a hook; absence is data
        return None
    if restored is None:
        return None
    box: dict[str, Any] = {
        "saga_id": restored.saga_id,
        "lifecycle_phase": restored.lifecycle_phase,
        "phase_status": restored.phase_status,
        "status": restored.status,
        "next_step": restored.next_step,
    }
    blockers = (getattr(restored, "blockers", "") or "").strip()
    if blockers:
        box["blockers"] = blockers
    open_qs = [str(q) for q in (getattr(restored, "open_questions", None) or [])]
    if open_qs:
        box["open_questions"] = open_qs
    # R4 pointers (paths/refs, never contents) — authority stays in committed docs + GitHub.
    box["_pointers"] = {
        "plan_path": getattr(restored, "plan_path", "") or "",
        "issue_ref": getattr(restored, "issue_ref", "") or "",
        "work_session_paths": [
            str(p) for p in (getattr(restored, "work_session_paths", None) or [])
        ],
    }
    return box


def freeze_run_record(repo_root: Path, box: dict[str, Any] | None) -> dict[str, Any] | None:
    """Freeze the active issue's run record for re-injection after compaction (#1023).

    The record is the authority on ``next_step``, so it is the fact the continuing session most
    needs back. This freezes a small READ of it — never a copy of the whole file and never a store
    of its own: the card's non-goal is explicit that the spore keeps no second store.

    Returns ``None`` whenever there is nothing to freeze: no active saga, a task rather than an
    issue, no record yet, or a record that cannot be read. A spore must never fail a compaction
    boundary, so every failure here is an absent block rather than an exception.
    """
    if not box:
        return None
    saga_id = str(box.get("saga_id") or "")
    if not saga_id.startswith("issue-"):
        return None
    number = saga_id.removeprefix("issue-")
    if not number.isdigit():
        return None
    try:
        import run_record  # noqa: PLC0415  (optional at call time, by design)

        store_root = run_record.resolve_store_root(repo_root)
        record = run_record.load(store_root, int(number), warn=None)
    except Exception:
        return None
    if record is None:
        return None
    return {
        "path": str(run_record.record_path(store_root, int(number))),
        "issue": record.issue,
        "next_step": record.next_step,
        "destination": record.admission.get("destination"),
        "pending_questions": list(record.admission.get("pending_questions") or []),
        "units": len(record.units),
        "review_cycles": len(record.review_cycles),
    }


def build_spore(repo_root: Path, session_id: str, *, now: str) -> dict[str, Any]:
    """Assemble the structured spore: ``{provenance, saga_box, pointers, run_record}``.

    single-saga case). ``now`` is an ISO timestamp injected by the caller (the hook passes
    ``datetime.now(UTC).isoformat()``; tests pass a fixed string) so the module stays wall-clock-free.
    """
    repo_root = Path(repo_root)
    box = resolve_active_saga(repo_root)
    active_id = box["saga_id"] if box else None
    pointers = box.pop("_pointers", {}) if box else {}

    source_tick = saga.latest_envelope_for(repo_root, active_id) if active_id else None
    provenance = {
        "schema": SCHEMA,
        "generated_at": now,
        "session_id": session_id,
        "repo_root": str(repo_root),
        "saga_id": active_id,
        "source_tick": _repo_relative(source_tick, repo_root),
    }
    return {
        "provenance": provenance,
        "saga_box": box,
        "pointers": pointers,
        "run_record": freeze_run_record(repo_root, box),
    }


def _repo_relative(path: Path | None, repo_root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).resolve().relative_to(Path(repo_root).resolve()))
    except (ValueError, OSError):
        return str(path)


def serialize(spore: dict[str, Any]) -> str:
    """Render the self-describing ``additionalContext`` block (R10) under the R5 byte budget.

    Ordering guarantees: the **resumable core** — authority + provenance + saga box + the full ready
    frontier — is emitted first and **never dropped**; per-leaf detail lines are appended in
    :func:`_leaf_priority` order and trimmed from the end (``done`` first, then waiting/terminal) with a
    counted ``(+K more …)`` pointer when over budget. If even the core exceeds budget it is emitted in
    full anyway (the F3 degenerate case — accept the harness spill-to-file rather than truncate the
    frontier), with the spill noted. Truncation is always logged in-band, never silent (no-silent-caps).
    """
    prov = spore.get("provenance", {})
    box = spore.get("saga_box")
    pointers = spore.get("pointers", {})

    head: list[str] = ["=== SAGA SPORE (structured re-grounding after compaction) ==="]
    head.append(f"AUTHORITY: {_AUTHORITY}")
    head.append("")
    head.append(
        "Provenance: generated_at={generated_at} · saga_id={saga_id}".format(
            generated_at=prov.get("generated_at", "?"),
            saga_id=prov.get("saga_id") or "(none)",
        )
    )
    refs = []
    if pointers.get("plan_path"):
        refs.append(f"plan={pointers['plan_path']}")
    if pointers.get("issue_ref"):
        refs.append(f"issue={pointers['issue_ref']}")
    if prov.get("source_tick"):
        refs.append(f"source_tick={prov['source_tick']}")
    if refs:
        head.append("Canonical refs: " + " · ".join(refs))

    if box:
        head.append("")
        head.append("ACTIVE SAGA")
        head.append(f"  saga_id: {box.get('saga_id')}")
        head.append(
            f"  phase: {box.get('lifecycle_phase')} ({box.get('phase_status')}) · status: {box.get('status')}"
        )
        head.append(f"  next_step: {box.get('next_step')}")
        if box.get("blockers"):
            head.append(f"  blockers: {box['blockers']}")
        if box.get("open_questions"):
            head.append("  open_questions: " + "; ".join(box["open_questions"]))
    else:
        head.append("")
        head.append("ACTIVE SAGA: (none resolved at the boundary)")

    # The run record is part of the resumable core: it is the AUTHORITY on next_step (#1023), so a
    # continuing session that loses it re-grounds on the envelope's possibly stale copy instead.
    # Suppression (#1029 KTD1/KTD5): an empty ``next_step`` means the step is done or the run is
    # closed, and re-injecting a finished step across a compaction boundary reads as an
    # instruction. The session-start hook applies the same rule from the same module, so the two
    # readers of this field cannot drift apart on what "done" looks like.
    record = spore.get("run_record")
    if record and not str(record.get("next_step") or "").strip():
        record = None
    if record:
        head.append("")
        head.append("RUN RECORD (authoritative on next_step)")
        head.append(f"  path: {record.get('path')}")
        head.append(f"  next_step: {record.get('next_step')}")
        head.append(
            f"  destination: {record.get('destination')} · units: {record.get('units')} · "
            f"review_cycles: {record.get('review_cycles')}"
        )
        if record.get("pending_questions"):
            head.append("  admission still to answer: " + ", ".join(record["pending_questions"]))

    # The outcome DAG block was rendered here from the frozen `dag` box, with a counted pointer
    # to the spec when the leaf list exceeded the budget. Issue 1030 removed the outcome
    # coordinator, so the spore freezes the active saga and the run record only, and neither is
    # ever trimmed: the core is now small enough to emit whole.
    frontier_block: list[str] = []
    leaf_lines: list[str] = []
    spec_ref = "the run record"
    # Assemble with the budget: head + frontier_block are the never-dropped core; leaf_lines trim.
    core = "\n".join(head + frontier_block)
    if not leaf_lines:
        tail = "\n=== END SPORE ==="
        out = core + tail
        return out

    leaf_header = "\n  Leaves:"
    fixed = core + leaf_header
    end = "\n=== END SPORE ==="
    # Greedily keep leaf lines while the whole block stays under budget, reserving room for a pointer.
    kept: list[str] = []
    dropped = 0
    pointer_tmpl = "\n    (+{k} more leaves — see {spec})"
    for i, line in enumerate(leaf_lines):
        remaining = len(leaf_lines) - i
        candidate = fixed + "\n" + "\n".join(kept + [line])
        pointer = pointer_tmpl.format(k=remaining - 1, spec=spec_ref) if remaining - 1 > 0 else ""
        if len(candidate + pointer + end) <= SPORE_BUDGET_CHARS:
            kept.append(line)
        else:
            dropped = len(leaf_lines) - len(kept)
            break

    body = fixed + ("\n" + "\n".join(kept) if kept else "")
    if dropped:
        body += pointer_tmpl.format(k=dropped, spec=spec_ref)
    out = body + end

    # F3 degenerate case: even the resumable core overflowed. Emit it in full anyway (the frontier is
    # never sacrificed); the harness spills to a file (GC1). Log the spill in-band, never silently.
    if len(out) > SPORE_BUDGET_CHARS and not kept:
        out += f"\n[spore note: resumable core exceeds {SPORE_BUDGET_CHARS} chars; emitted in full — harness spills to file]"
    return out


# ---------------------------------------------------------------------------
# On-disk seam: dump (write) / load_and_validate (read) — R8/R9/R13
# ---------------------------------------------------------------------------


def dump(spore: dict[str, Any]) -> str:
    """The on-disk JSON the PreCompact hook writes: validation fields + the pre-rendered block.

    The rendering (and the R5 budget) runs once here at PreCompact time — under the hook's wall-clock
    deadline — so the SessionStart read is a trivial validate-and-return and the block reflects the
    state *frozen at the boundary*.
    """
    prov = spore.get("provenance", {})
    payload = {
        "schema": SCHEMA,
        "session_id": prov.get("session_id"),
        "repo_root": prov.get("repo_root"),
        "saga_id": prov.get("saga_id"),
        "generated_at": prov.get("generated_at"),
        "block": serialize(spore),
    }
    return json.dumps(payload, indent=2)


def load_and_validate(text: str, expected_session_id: str, expected_repo_root: str) -> str | None:
    """Parse the on-disk spore and return its renderable block, or None on mismatch/corruption (R9).

    The filename already keys the spore to ``<session_id>``; this re-checks ``session_id`` and the
    ``repo_root`` from the payload (defense in depth) and requires a ``saga_id`` so a content mismatch is
    skipped rather than injected. Never raises — a malformed spore is treated as absent.
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != SCHEMA:
        return None
    if payload.get("session_id") != expected_session_id:
        return None
    if str(payload.get("repo_root")) != str(expected_repo_root):
        return None
    if not payload.get("saga_id"):
        return None
    block = payload.get("block")
    if not isinstance(block, str) or not block:
        return None
    return block
