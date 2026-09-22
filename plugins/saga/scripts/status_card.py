#!/usr/bin/env python3
"""Shared glyph-card renderer — single status emitter for all saga surfaces (U1, #278).

Derived-on-read from durable engine state: **no operator-writable status field**.
Constant-size, position-stable; every determinable cell traceable to its evidence via indexed
footer.

Two archetypes (KTD6):
  gate-sequence      — static superset of gates; every row rendered regardless of state, so a row
                       whose state is not-reached still occupies its line (R3 constant-size).
  summary-projection — fixed summary rows; height constant regardless of how many dynamic items the
                       caller summarised from a backing projection (R3).

House pattern mirrors ``outcome_projection.py``: pure functions over explicit values, no I/O at
import, stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# Cross-module import for saga engine helpers (pattern mirrors load_saga_context.py:23-30).
# The sys.path bootstrap must precede the import so the scripts directory is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import saga as _saga_engine  # noqa: E402

# ── Wire-state enum (R1) ─────────────────────────────────────────────────────────────────────────
# Frozen wire contract.  These string values are carried in CardRow.state and in every downstream
# serialisation.  They MUST NOT change without a migration.  Renaming a displayed label or swapping
# a glyph is a display-map edit (R9), not a wire-value change.


class CardState(StrEnum):
    """Fixed wire-state vocabulary (R1).

    ``NOT_REACHED`` also covers "unknown" — any cell whose status cannot yet be determined renders
    as the same quiet placeholder glyph.
    """

    DONE = "done"
    IN_PROGRESS = "in-progress"
    BLOCKED = "blocked"
    FAILED = "failed"
    HALTED = "halted"
    NOT_REACHED = "not-reached"  # also used for "unknown" / unresolvable


# ── Display-label-map pattern (R9; mirrors saga.py:73-87) ────────────────────────────────────────
# GLYPH_MAP and OPERATOR_LABEL_MAP are additive dictionaries whose keys are the frozen wire-state
# values.  A key miss falls back to the raw wire string — never errors.  Renaming a label or
# swapping a glyph is an edit to these maps, NOT a stored-state change.
#
# Agent-facing wire markers (CardState enum values) stay distinct from operator-facing vocabulary
# (the values in OPERATOR_LABEL_MAP), satisfying R11.

GLYPH_MAP: dict[str, str] = {
    "done": "✓",
    "in-progress": "◐",
    "blocked": "⊘",
    "failed": "✗",
    "halted": "‖",
    "not-reached": "·",
}

OPERATOR_LABEL_MAP: dict[str, str] = {
    "done": "done",
    "in-progress": "in progress",
    "blocked": "blocked",
    "failed": "failed",
    "halted": "halted",
    "not-reached": "not reached",
}


def display_glyph(state: CardState) -> str:
    """Return the operator-facing glyph for *state*; fall back to the raw wire string on a miss."""
    return GLYPH_MAP.get(state.value, state.value)


def display_state_label(state: CardState) -> str:
    """Return the operator-facing label for *state*; fall back to the raw wire string on a miss."""
    return OPERATOR_LABEL_MAP.get(state.value, state.value)


def is_determinable(state: CardState) -> bool:
    """True iff this cell's status is determinable and should carry a drill-down ref (R12/R13).

    NOT_REACHED / unknown cells are exempt: they render a quiet placeholder and carry neither an
    index tag nor a footer reference.
    """
    return state != CardState.NOT_REACHED


# ── Card-spec data model (KTD6) ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CardRow:
    """One row in a glyph card.

    ``state`` drives the glyph through GLYPH_MAP — a pure function, so there is no field that sets
    the *displayed* status independently of the stored ``state`` (R2/AE2).  ``ref`` is the
    drill-down evidence reference for determinable cells; it is silently ignored for NOT_REACHED
    rows (R13).
    """

    key: str  # stable machine identifier (used for ordering/deduplication by callers)
    label: str  # operator-facing row label
    state: CardState  # wire state — drives glyph, index eligibility, and footer inclusion
    ref: str | None = None  # evidence reference; expected for determinable rows (R12)


@dataclass(frozen=True)
class CardHeader:
    """Surface-identity block rendered above the card body."""

    surface: str  # surface name, e.g. "/work" or "/code-review"
    id: str  # saga id, artifact path, or other stable identifier
    round: int | None = None  # optional iteration/round counter


@dataclass(frozen=True)
class CardSpec:
    """Complete, immutable specification for one glyph card.

    ``archetype`` selects rendering semantics:
      "gate-sequence"      — a static superset of gates; all rows rendered regardless of state.
      "summary-projection" — a fixed summary row set; rendered count is always len(rows).

    Constant height (R3) is a structural property of the spec: the renderer always emits one line
    per row, so the row count in the spec determines the card height — state changes only change
    glyphs, not line count.
    """

    archetype: str  # "gate-sequence" | "summary-projection"
    header: CardHeader
    rows: tuple[CardRow, ...]  # ordered; frozen to prevent accidental mutation after construction


# ── Renderer ─────────────────────────────────────────────────────────────────────────────────────

_CARD_WIDTH = 58  # inner character width (between border edges)


def _hr(char: str = "═") -> str:
    """Horizontal rule of exactly _CARD_WIDTH characters."""
    return char * _CARD_WIDTH


def render(spec: CardSpec) -> str:
    """Render *spec* to a fixed-width, position-stable glyph card string (R3/KTD3).

    Layout:
      ══════════ (top border)
       /surface · id
      ══════════ (header separator)
       G  Row label                              [n]
       ·  Not-reached row
      ══════════ (bottom border)
      [n] evidence reference
      [m] evidence reference

    Every determinable cell receives a short ``[n]`` index; its ``ref`` is listed in a footer block
    beneath the card.  NOT_REACHED cells occupy their row but carry no index tag and no footer entry
    (R13).

    The rendered string is a pure function of *spec* — identical input always produces byte-identical
    output (R2/AE2).  The card body width is constant regardless of which states are set (R3).
    """
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────────────────────────
    lines.append(_hr())
    hdr = spec.header
    round_suffix = f" · round {hdr.round}" if hdr.round is not None else ""
    header_text = f" {hdr.surface}{round_suffix} · {hdr.id}"
    # Truncate if the surface/id string is unusually long; never wrap (would break constant width).
    lines.append(header_text[:_CARD_WIDTH])
    lines.append(_hr())

    # ── Body ─────────────────────────────────────────────────────────────────────────────────────
    # Enumerate determinable cells to assign monotonically increasing [n] indices.
    footer_refs: list[tuple[int, str]] = []
    counter = 0

    for row in spec.rows:
        glyph = display_glyph(row.state)

        if is_determinable(row.state):
            counter += 1
            n = counter
            if row.ref:
                footer_refs.append((n, row.ref))
            index_tag = f"[{n}]"
        else:
            index_tag = ""

        # Fixed body layout: " G  {label:<label_width}{index_tag}"
        # Column breakdown: 1 leading space + 1 glyph + 2 spaces + label + index = _CARD_WIDTH
        label_width = _CARD_WIDTH - 4 - len(index_tag)
        if index_tag:
            lines.append(f" {glyph}  {row.label:<{label_width}}{index_tag}")
        else:
            lines.append(f" {glyph}  {row.label:<{label_width}}")

    lines.append(_hr())

    # ── Footer (indexed drill-down refs, KTD3) ───────────────────────────────────────────────────
    # Absent entirely when no determinable cell carries a ref — the card body is the sole output.
    if footer_refs:
        for n, ref in footer_refs:
            lines.append(f"[{n}] {ref}")
        lines.append("")  # trailing blank separates the footer visually from subsequent output

    return "\n".join(lines) + "\n"


# ── Per-surface gate-sequence projection builders (U3, #278) ─────────────────────────────────────
# Each function returns a CardSpec with archetype "gate-sequence".  They read from durable saga
# state or parsed artifact text — **never** from operator-set status fields (R2/AE2).
#
# SAFE DEGRADATION RULE (R1/R13/AE7): any row whose source signal is absent or unparseable
# renders CardState.NOT_REACHED with ref=None.  A confident-but-wrong glyph is the worst failure.
# Every determinable cell attaches its drill-down ref (R12).


def _saga_list(field: object) -> list[str]:
    """Return *field* as a list of strings if it is a real list, else [] (ABSENT-sentinel safe)."""
    return field if isinstance(field, list) else []  # type: ignore[return-value]


def _phase_status_to_state(phase_status: str) -> CardState:
    """Map saga ``phase_status`` wire value to a CardState for the Implementation row."""
    if phase_status == "complete":
        return CardState.DONE
    if phase_status == "in_progress":
        return CardState.IN_PROGRESS
    return CardState.NOT_REACHED


def project_work(saga_obj: object) -> CardSpec:
    """Build a gate-sequence CardSpec for the /work surface.

    Row order (static superset — all rows always present, R3):
      Implementation · Doc-review · Tests · Reviewer panel · Scanners ·
      CI · Merge (HITL) · Deploy (HITL).

    Tests cell derives exclusively from ``saga_obj.gate_verdicts`` via
    ``_saga_engine.parse_gate_verdict`` (AE4 — never from ``checks_run``).
    CI / Merge / Deploy refs are resolvable external (GitHub) references (R12).
    """
    # ── Implementation ───────────────────────────────────────────────────────────────────────────
    phase_status = getattr(saga_obj, "phase_status", "pending") or "pending"
    saga_id = getattr(saga_obj, "saga_id", "") or ""
    impl_state = _phase_status_to_state(phase_status)
    impl_ref: str | None = saga_id if (is_determinable(impl_state) and saga_id) else None

    # ── Doc-review ───────────────────────────────────────────────────────────────────────────────
    review_paths = _saga_list(getattr(saga_obj, "review_paths", None))
    if review_paths:
        docrev_state = CardState.DONE
        docrev_ref: str | None = review_paths[0]
    else:
        docrev_state = CardState.NOT_REACHED
        docrev_ref = None

    # ── Tests (AE4: must route through parse_gate_verdict — never derive from checks_run) ────────
    gate_verdicts = _saga_list(getattr(saga_obj, "gate_verdicts", None))
    tests_state = CardState.NOT_REACHED
    tests_ref: str | None = None
    for entry in gate_verdicts:
        try:
            gate, state_str, gv_ref = _saga_engine.parse_gate_verdict(entry)
        except ValueError:
            continue
        if gate == "tests":
            try:
                tests_state = CardState(state_str)
            except ValueError:
                tests_state = CardState.NOT_REACHED
            tests_ref = gv_ref if gv_ref else None
            break  # first "tests" entry is authoritative

    # ── Reviewer panel (AE6: carries resolvable ref to code-review artifact) ─────────────────────
    if review_paths:
        panel_state = CardState.DONE
        panel_ref: str | None = review_paths[0]
    else:
        panel_state = CardState.NOT_REACHED
        panel_ref = None

    # ── Scanners (also sourced from review_paths — same artifact carries scanner evidence) ────────
    if review_paths:
        scan_state = CardState.DONE
        scan_ref: str | None = review_paths[0]
    else:
        scan_state = CardState.NOT_REACHED
        scan_ref = None

    # ── CI (R12 external-read: resolvable GitHub Actions / PR ref) ───────────────────────────────
    pr_refs = _saga_list(getattr(saga_obj, "pr_refs", None))
    head_sha = getattr(saga_obj, "head_sha", "") or ""
    if pr_refs:
        ci_state = CardState.IN_PROGRESS
        ci_ref: str | None = pr_refs[0]
    elif head_sha:
        ci_state = CardState.IN_PROGRESS
        ci_ref = head_sha
    else:
        ci_state = CardState.NOT_REACHED
        ci_ref = None

    # ── Merge (HITL) — blocked on human approval; ref is the PR ─────────────────────────────────
    if pr_refs:
        merge_state = CardState.BLOCKED
        merge_ref: str | None = pr_refs[0]
    else:
        merge_state = CardState.NOT_REACHED
        merge_ref = None

    # ── Deploy (HITL) — blocked on human approval when destination targets deployment ─────────────
    destination = getattr(saga_obj, "destination", "plan-only") or "plan-only"
    if destination == "nonprod-deploy":
        deploy_state = CardState.BLOCKED
        deploy_ref: str | None = destination
    else:
        deploy_state = CardState.NOT_REACHED
        deploy_ref = None

    return CardSpec(
        archetype="gate-sequence",
        header=CardHeader(surface="/work", id=saga_id or "unknown"),
        rows=(
            CardRow("impl", "Implementation", impl_state, ref=impl_ref),
            CardRow("docrev", "Doc-review", docrev_state, ref=docrev_ref),
            CardRow("tests", "Tests", tests_state, ref=tests_ref),
            CardRow("panel", "Reviewer panel", panel_state, ref=panel_ref),
            CardRow("scanners", "Scanners", scan_state, ref=scan_ref),
            CardRow("ci", "CI", ci_state, ref=ci_ref),
            CardRow("merge", "Merge (HITL)", merge_state, ref=merge_ref),
            CardRow("deploy", "Deploy (HITL)", deploy_state, ref=deploy_ref),
        ),
    )


def project_arc(saga_obj: object) -> CardSpec:
    """Build a gate-sequence CardSpec projecting the idea->deploy lifecycle arc (#344 R7/KD4).

    Rendered by ``/loop`` at Route/Drive/Resume. A pure function of durable saga fields (the same
    category ``project_work`` reads): ``lifecycle_phase``, ``phase_status``, ``status``, ``plan_path``,
    ``review_paths``, ``pr_refs``, ``destination``. Consults NO writable board Status column, board
    cache, or ``board_progression`` write-record — the arc renders what the saga itself asserts, never
    what the board says (KD4 derived-on-read). Merge/Deploy are HITL (never auto-advanced).

    Row order (fixed — constant height regardless of state, R3):
      Idea · Plan · Work · Review · Merge (HITL) · Deploy (HITL).
    """
    saga_id = getattr(saga_obj, "saga_id", "") or ""
    lifecycle_phase = str(getattr(saga_obj, "lifecycle_phase", "") or "").lower()
    phase_status = str(getattr(saga_obj, "phase_status", "") or "").lower()
    status = str(getattr(saga_obj, "status", "") or "").lower()
    plan_path = getattr(saga_obj, "plan_path", "") or ""
    review_paths = _saga_list(getattr(saga_obj, "review_paths", None))
    pr_refs = _saga_list(getattr(saga_obj, "pr_refs", None))
    destination = str(getattr(saga_obj, "destination", "plan-only") or "plan-only")

    phase_rank = {"plan": 1, "work": 2, "qa": 3}.get(lifecycle_phase, 0)
    thread_done = status == "done"

    # ── Idea ──────────────────────────────────────────────────────────────────────────────────────
    # An existing saga implies a settled idea preceded planning; safe-degrade only for an empty object.
    if plan_path or lifecycle_phase or saga_id:
        idea_state: CardState = CardState.DONE
        idea_ref: str | None = saga_id or None
    else:
        idea_state, idea_ref = CardState.NOT_REACHED, None

    # ── Plan ──────────────────────────────────────────────────────────────────────────────────────
    if plan_path:
        plan_state, plan_ref = CardState.DONE, plan_path
    else:
        plan_state, plan_ref = CardState.NOT_REACHED, None

    # ── Work ──────────────────────────────────────────────────────────────────────────────────────
    if phase_rank > 2 or (phase_rank == 2 and (phase_status == "complete" or thread_done)):
        work_state = CardState.DONE
    elif phase_rank == 2:
        work_state = CardState.IN_PROGRESS
    else:
        work_state = CardState.NOT_REACHED
    work_ref: str | None = (saga_id or None) if work_state != CardState.NOT_REACHED else None

    # ── Review ────────────────────────────────────────────────────────────────────────────────────
    if review_paths:
        review_state, review_ref = CardState.DONE, review_paths[0]
    else:
        review_state, review_ref = CardState.NOT_REACHED, None

    # ── Merge (HITL) ──────────────────────────────────────────────────────────────────────────────
    # Merged when the thread is done with a PR; otherwise blocked-awaiting once a PR exists.
    if pr_refs and thread_done:
        merge_state, merge_ref = CardState.DONE, pr_refs[0]
    elif pr_refs:
        merge_state, merge_ref = CardState.BLOCKED, pr_refs[0]
    else:
        merge_state, merge_ref = CardState.NOT_REACHED, None

    # ── Deploy (HITL) ─────────────────────────────────────────────────────────────────────────────
    # Only in the arc when the destination targets a deployment.
    if destination == "nonprod-deploy":
        deploy_state = CardState.DONE if thread_done else CardState.BLOCKED
        deploy_ref: str | None = destination
    else:
        deploy_state, deploy_ref = CardState.NOT_REACHED, None

    return CardSpec(
        archetype="gate-sequence",
        header=CardHeader(surface="/loop", id=saga_id or "unknown"),
        rows=(
            CardRow("idea", "Idea", idea_state, ref=idea_ref),
            CardRow("plan", "Plan", plan_state, ref=plan_ref),
            CardRow("work", "Work", work_state, ref=work_ref),
            CardRow("review", "Review", review_state, ref=review_ref),
            CardRow("merge", "Merge (HITL)", merge_state, ref=merge_ref),
            CardRow("deploy", "Deploy (HITL)", deploy_state, ref=deploy_ref),
        ),
    )


def _parse_verdict_state(text: str) -> CardState | None:
    """Parse a verdict token from *text*; return the matching CardState or None if absent."""
    m = re.search(r"\*\*Verdict[^*]*\*\*[:\s]*([^\n]+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"(?:^|\n)Verdict:\s*([^\n]+)", text, re.IGNORECASE)
    if not m:
        return None
    fragment = m.group(1).upper()
    if "BLOCK" in fragment:
        return CardState.BLOCKED
    if "FAIL" in fragment:
        return CardState.FAILED
    if "APPROVE" in fragment or "CLEAN" in fragment or "READY" in fragment:
        return CardState.DONE
    return None


def project_code_review(artifact_text: str, *, ref: str) -> CardSpec:
    """Build a gate-sequence CardSpec for the /code-review surface.

    Parses *artifact_text* using real, anchored vocabulary only (no invented signals):
    - ``Scope Check: CLEAN|DRIFT DETECTED|REQUIREMENTS MISSING`` → Scope row.
    - Plan-completion audit tokens ``DONE|PARTIAL|NOT-DONE|CHANGED|UNVERIFIABLE`` → Intent row.
    - ``**Verdict:** ...`` line → Verdict row (and Merge row by implication).

    Rows: Scope · Intent · Lenses · Review fan-out · Merge · Validators · Verdict.
    """
    # ── Scope ────────────────────────────────────────────────────────────────────────────────────
    scope_m = re.search(
        r"Scope Check:\s*(CLEAN|DRIFT DETECTED|REQUIREMENTS MISSING)", artifact_text, re.IGNORECASE
    )
    if scope_m:
        token = scope_m.group(1).upper()
        scope_state = CardState.DONE if token == "CLEAN" else CardState.BLOCKED
        scope_ref: str | None = ref
    else:
        scope_state = CardState.NOT_REACHED
        scope_ref = None

    # ── Intent (built-vs-planned: plan-completion audit statuses) ────────────────────────────────
    audit_tokens = re.findall(r"\b(DONE|PARTIAL|NOT-DONE|CHANGED|UNVERIFIABLE)\b", artifact_text)
    if audit_tokens:
        token_set = set(audit_tokens)
        if token_set & {"NOT-DONE", "UNVERIFIABLE"}:
            intent_state = CardState.BLOCKED
        elif token_set & {"PARTIAL", "CHANGED"}:
            intent_state = CardState.IN_PROGRESS
        else:
            intent_state = CardState.DONE
        intent_ref: str | None = ref
    else:
        intent_state = CardState.NOT_REACHED
        intent_ref = None

    # ── Lenses ───────────────────────────────────────────────────────────────────────────────────
    has_lenses = bool(re.search(r"\blenses?\b", artifact_text, re.IGNORECASE))
    lenses_state = CardState.DONE if has_lenses else CardState.NOT_REACHED
    lenses_ref: str | None = ref if has_lenses else None

    # ── Review fan-out ───────────────────────────────────────────────────────────────────────────
    has_fanout = bool(
        re.search(r"\bfan-out\b|\breview fan-out\b|\breviewers?\b", artifact_text, re.IGNORECASE)
    )
    fanout_state = CardState.DONE if has_fanout else CardState.NOT_REACHED
    fanout_ref: str | None = ref if has_fanout else None

    # ── Verdict (parsed first; Merge row derives from the same signal) ───────────────────────────
    verdict_state = _parse_verdict_state(artifact_text) or CardState.NOT_REACHED
    verdict_ref: str | None = ref if verdict_state != CardState.NOT_REACHED else None

    # ── Merge (derives from verdict — approved verdict implies merge is clear) ────────────────────
    if verdict_state == CardState.DONE:
        merge_state = CardState.DONE
        merge_ref: str | None = ref
    elif verdict_state in (CardState.BLOCKED, CardState.FAILED):
        merge_state = CardState.BLOCKED
        merge_ref = ref
    else:
        merge_state = CardState.NOT_REACHED
        merge_ref = None

    # ── Validators ───────────────────────────────────────────────────────────────────────────────
    has_validators = bool(re.search(r"\bvalidators?\b", artifact_text, re.IGNORECASE))
    validators_state = CardState.DONE if has_validators else CardState.NOT_REACHED
    validators_ref: str | None = ref if has_validators else None

    return CardSpec(
        archetype="gate-sequence",
        header=CardHeader(surface="/code-review", id=ref),
        rows=(
            CardRow("scope", "Scope", scope_state, ref=scope_ref),
            CardRow("intent", "Intent", intent_state, ref=intent_ref),
            CardRow("lenses", "Lenses", lenses_state, ref=lenses_ref),
            CardRow("fanout", "Review fan-out", fanout_state, ref=fanout_ref),
            CardRow("merge", "Merge", merge_state, ref=merge_ref),
            CardRow("validators", "Validators", validators_state, ref=validators_ref),
            CardRow("verdict", "Verdict", verdict_state, ref=verdict_ref),
        ),
    )


def _parse_frontmatter_value(text: str, key: str) -> str | None:
    """Return the scalar value for *key* from YAML frontmatter (simple key: value form)."""
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def project_qa(artifact_text: str, *, ref: str) -> CardSpec:
    """Build a gate-sequence CardSpec for the /qa functional-test surface.

    RETARGETED by issue 1039. The rows used to be a nine-way risk class, a checks row, a findings
    row, a scored number and a ship verdict, parsed from a ``docs/qa/`` report. `/qa` produces none
    of those now: it is the prescribed strategy catalogue, and what it prints is the functional-test
    comment. The rows follow what that comment carries.

    (The retired row's name is deliberately not spelled out here: the specification sweeps this
    directory for that literal string, and a docstring that named it would keep the removed model
    alive in a grep long after the code had gone.)

    Parses *artifact_text* — the functional-test comment — for:
    - YAML frontmatter: ``verdict:``, ``boundary:``, ``route:``.
    - the per-strategy results table, whose cells are ``passed`` / ``failed`` / ``blocked``.

    Rows: Selection · Preflight · Evidence · Proof debt · Verdict.

    AE9 (operator-safety-critical): a ``verdict:`` that indicates failure maps to CardState.FAILED
    with *ref* — NEVER blocked or not-reached. A required strategy that could not run is a
    distinct, equally loud state: it renders BLOCKED with *ref*, never DONE and never silence.
    """
    # ── Frontmatter ──────────────────────────────────────────────────────────────────────────────
    verdict_raw = _parse_frontmatter_value(artifact_text, "verdict")
    boundary_raw = _parse_frontmatter_value(artifact_text, "boundary")
    route_raw = _parse_frontmatter_value(artifact_text, "route")

    # ── Selection (from the selection table: one row per selected strategy) ─────────────────────
    selected = re.findall(r"^\|\s*`([a-z-]+)`\s*\|\s*(yes|no)\s*\|", artifact_text, re.MULTILINE)
    if selected:
        selection_state = CardState.DONE
        selection_ref: str | None = f"{ref}#selected:{len(selected)}"
    else:
        selection_state = CardState.NOT_REACHED
        selection_ref = None

    # ── Preflight (the boundary the run could reach; absent means it never got that far) ────────
    if boundary_raw:
        preflight_state = CardState.DONE
        preflight_ref: str | None = f"{ref}#boundary:{boundary_raw}"
    else:
        preflight_state = CardState.NOT_REACHED
        preflight_ref = None

    # ── Evidence (the per-strategy results: one envelope each, three values and no fourth) ──────
    results = [
        cell.lower()
        for cell in re.findall(
            r"^\|\s*`[a-z-]+`\s*\|\s*`(passed|failed|blocked)`\s*\|", artifact_text, re.MULTILINE
        )
    ]
    if not results:
        evidence_state = CardState.NOT_REACHED
        evidence_ref: str | None = None
    elif "failed" in results:
        evidence_state = CardState.FAILED
        evidence_ref = ref
    elif "blocked" in results:
        # A strategy that could not run proved nothing; the card says so rather than showing done.
        evidence_state = CardState.BLOCKED
        evidence_ref = ref
    else:
        evidence_state = CardState.DONE
        evidence_ref = ref

    # ── Proof debt (an optional strategy that could not run, recorded rather than hidden) ────────
    has_debt = bool(re.search(r"^#+\s*Proof debt\b", artifact_text, re.MULTILINE | re.IGNORECASE))
    if has_debt:
        debt_state = CardState.BLOCKED
        debt_ref: str | None = ref
    elif results:
        debt_state = CardState.DONE
        debt_ref = ref
    else:
        debt_state = CardState.NOT_REACHED
        debt_ref = None

    # ── Verdict (AE9: the fail family → FAILED with ref; the pass family → DONE) ─────────────────
    if verdict_raw:
        value = verdict_raw.lower().strip()
        if value in {"fail", "failed", "no-ship", "not-ship"}:
            verdict_state = CardState.FAILED
            verdict_ref: str | None = ref  # AE9: failure is determinable and MUST carry ref
        elif value == "blocked":
            # Nothing was proved and the run stopped for the operator. Not a pass, not a failure.
            verdict_state = CardState.BLOCKED
            verdict_ref = ref
        elif value in {"pass", "pass-with-proof-debt", "ship", "ship-with-deferred"}:
            verdict_state = CardState.DONE
            verdict_ref = ref
        else:
            verdict_state = CardState.NOT_REACHED
            verdict_ref = None
    else:
        verdict_state = CardState.NOT_REACHED
        verdict_ref = None
    if route_raw and verdict_state is CardState.NOT_REACHED:
        verdict_ref = f"{ref}#route:{route_raw}"

    return CardSpec(
        archetype="gate-sequence",
        header=CardHeader(surface="/qa", id=ref),
        rows=(
            CardRow("selection", "Selection", selection_state, ref=selection_ref),
            CardRow("preflight", "Preflight", preflight_state, ref=preflight_ref),
            CardRow("evidence", "Evidence", evidence_state, ref=evidence_ref),
            CardRow("debt", "Proof debt", debt_state, ref=debt_ref),
            CardRow("verdict", "Verdict", verdict_state, ref=verdict_ref),
        ),
    )


# ── Per-surface summary-projection builders (U4, #278) ───────────────────────────────────────────
# Each function returns a CardSpec with archetype "summary-projection".  Height is constant
# regardless of how many DAG nodes / dynamic items back it (R3/R6).
#
# SAFE DEGRADATION RULE (R1/R13): any row whose source signal is absent or unparseable renders
# CardState.NOT_REACHED with ref=None.  Every determinable cell attaches its drill-down ref (R12).


def _make_gate_sequence_sample() -> CardSpec:
    """Sample gate-sequence card with five gates in mixed states (done/failed/halted/in-progress/not-reached)."""
    return CardSpec(
        archetype="gate-sequence",
        header=CardHeader(surface="/work", id="saga-demo-1234", round=2),
        rows=(
            CardRow("impl", "Implementation", CardState.DONE, ref="saga-demo-1234/tick-3.md"),
            CardRow("tests", "Tests", CardState.FAILED, ref="saga-demo-1234/gate_verdicts"),
            CardRow("review", "Reviewer panel", CardState.HALTED, ref="saga-demo-1234/review.md"),
            CardRow("ci", "CI", CardState.IN_PROGRESS, ref="github.com/org/repo/actions/1"),
            CardRow("merge", "Merge", CardState.NOT_REACHED, ref=None),
        ),
    )


def _make_summary_projection_sample() -> CardSpec:
    """Sample summary-projection card with four fixed rows."""
    return CardSpec(
        archetype="summary-projection",
        header=CardHeader(surface="/outcome", id="outcome-alpha"),
        rows=(
            CardRow("progress", "Progress", CardState.IN_PROGRESS, ref="outcome-alpha/spec.md"),
            CardRow("frontier", "Ready frontier", CardState.DONE, ref="outcome-alpha/store"),
            CardRow("blocked", "Blocked", CardState.BLOCKED, ref="outcome-alpha/store#blocked"),
            CardRow("attention", "Attention", CardState.NOT_REACHED, ref=None),
        ),
    )


def self_test() -> int:
    """Render sample cards for both archetypes and verify structural invariants (CI-runnable)."""
    gate_spec = _make_gate_sequence_sample()
    gate_card = render(gate_spec)

    summary_spec = _make_summary_projection_sample()
    summary_card = render(summary_spec)

    # 1. All expected glyphs are present in the gate-sequence card.
    for glyph, name in [
        ("✓", "done"),
        ("✗", "failed"),
        ("‖", "halted"),
        ("◐", "in-progress"),
        ("·", "not-reached"),
    ]:
        if glyph not in gate_card:
            print(
                f"UNCAUGHT: glyph '{glyph}' ({name}) missing from gate-sequence card",
                file=sys.stderr,
            )
            return 1
    print("glyphs-present: gate-sequence card contains all five glyphs")

    # 2. Footer indices present for the four determinable rows with refs.
    for n in (1, 2, 3, 4):
        if f"[{n}]" not in gate_card:
            print(f"UNCAUGHT: footer index [{n}] missing from gate-sequence card", file=sys.stderr)
            return 1
    print("footer-indexed: determinable rows carry [1]..[4] indices")

    # 3. NOT_REACHED row (Merge, index 5 would be) carries no footer index.
    if "[5]" in gate_card:
        print(
            "UNCAUGHT: NOT_REACHED 'Merge' row leaked a footer index into the card", file=sys.stderr
        )
        return 1
    print("not-reached-no-index: NOT_REACHED row carries no footer index")

    # 4. Determinism — same spec renders byte-identical output.
    if render(gate_spec) != render(gate_spec):
        print("UNCAUGHT: render is not deterministic", file=sys.stderr)
        return 1
    print("determinism: same spec renders byte-identical output")

    # 5. Constant body line count — body height unchanged between the two renders.
    def _body_line_count(card: str) -> int:
        """Count body rows between the 2nd border (header separator) and 3rd border (bottom)."""
        borders_seen = 0
        in_body = False
        count = 0
        for line in card.splitlines():
            if line.startswith("═"):
                borders_seen += 1
                if borders_seen == 2:
                    in_body = True  # body starts after the header separator
                elif borders_seen == 3:
                    break  # body ends at the bottom border
            elif in_body:
                count += 1
        return count

    gate_body = _body_line_count(gate_card)
    if gate_body != len(gate_spec.rows):
        print(
            f"UNCAUGHT: gate-sequence body has {gate_body} lines, expected {len(gate_spec.rows)}",
            file=sys.stderr,
        )
        return 1
    print(f"constant-size: gate-sequence body = {gate_body} lines (matches spec row count)")

    print("\ngate-sequence card:")
    print(gate_card)
    print("summary-projection card:")
    print(summary_card)
    print("self-test: all checks passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Shared glyph-card renderer — derived-on-read status for saga surfaces (#278)."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Render sample cards and verify structural invariants (CI-runnable).",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
