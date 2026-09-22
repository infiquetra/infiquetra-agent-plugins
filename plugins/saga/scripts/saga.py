#!/usr/bin/env python3
"""Unified Infiquetra-lifecycle saga engine.

A *saga* is the durable, resumable work-state envelope for a single thread of
lifecycle work (one issue or one ad-hoc task). It is the spine the four
execution-loop commands (``/work``, ``/resume``, ``/loop``, ``/plan``) read and
write against once they are rebuilt; this module is that engine.

Storage (under git-ignored ``.claude/saga/``)::

    sagas/
      issue-42/                  # one dir per derived saga_id
        20260602-140510.md       # tick 1 (append-only, immutable)
        20260602-141233.md       # tick 2 — newest FILENAME = current state
    state.json                   # DERIVED index (rebuildable from scan)
    checkpoints/                 # LEGACY pre-0.4.0 — scan reads as fallback

Canonical ordering is ALWAYS by filename string, never ``mtime`` — so that
rsync / backup / snapshot-restore preserve order deterministically. The
``state.json`` index is derived and best-effort: a corrupt index is never
fatal because ``scan`` rebuilds the picture from the envelope log.

House testability pattern (mirrors ``handoff_envelope.py``): every filesystem
function takes ``root: Path`` as its first argument, and ``now`` / ``runner``
are injectable so offline tests are deterministic and never shell out.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import re
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
STATE_DIR = Path(".claude/saga")
_LEGACY_STATE_DIR = Path(".claude/infiquetra-lifecycle")


def _migrate_legacy_state_dir() -> None:
    """One-time: the plugin was renamed infiquetra-lifecycle -> saga (0.19.0). Move pre-existing state."""
    if _LEGACY_STATE_DIR.exists() and not STATE_DIR.exists():
        with contextlib.suppress(OSError):
            _LEGACY_STATE_DIR.rename(STATE_DIR)


SAGAS_DIR = STATE_DIR / "sagas"
LEGACY_CHECKPOINT_DIR = STATE_DIR / "checkpoints"

# Default branch names a saved ``branch`` field must not be silently overwritten with once a real
# work branch is already recorded (issue #480). The ship ceremony this guard was written against
# checked ``main`` out before deleting the work branch, so a live-git refresh on that progress-save
# would otherwise erase the very branch the delete still needed. That ceremony was removed with
# issue #1027; the guard stays, because "a default branch name never overwrites a recorded work
# branch" is true of every caller and not only of the one that made it visible. Mirrors the
# ceremony's
# own hard-coded ``main`` checkout (``master`` included for older repos).
_DEFAULT_BRANCHES = frozenset({"main", "master"})

ENVELOPE_RE = re.compile(r"^(?P<ts>\d{8}-\d{6})(?:-(?P<seq>\d+))?\.md$")
ROUND_RE = re.compile(r"round-(\d+)", re.IGNORECASE)
LEGACY_CHECKPOINT_RE = re.compile(
    r"^(?P<kind>issue|task)-(?P<id>[a-zA-Z0-9_-]+?)"
    r"(?:-round-(?P<round>\d+))?"
    r"-phase(?P<phase>\d+)(?:-(?P<status>complete|pending|in_progress))?\.md$"
)

# Enum domains (the spec states each axis as a MUST).
LIFECYCLE_PHASES = ("ideation", "brainstorm", "plan", "review", "work", "qa", "retro")
PHASE_STATUSES = ("pending", "in_progress", "complete")
STATUSES = ("active", "blocked", "paused", "handed-off", "done", "abandoned")
DESTINATIONS = ("plan-only", "pr", "merge", "nonprod-deploy")
# Two values since issue #1030 archived the team-execution plugin. The strings are a frozen wire
# contract carried in persisted sagas, so a tick that recorded "team-execution" still reads back;
# it is simply no longer selectable, because the backend it named no longer exists.
ORCHESTRATION_MODES = ("inline",)

# Display-label map (R8 / KTD5).  Maps the stored enum string to the human-readable
# label surfaced in every offer.  The enum values in ORCHESTRATION_MODES are the
# frozen wire contract (carried in persisted sagas and CLI --orchestration-mode);
# this map is additive and never changes their meaning.  A key miss falls back to
# the raw enum string — never errors.
ORCHESTRATION_MODE_LABELS: dict[str, str] = {
    # Kept deliberately after issue #1030 archived the plugin: a persisted saga can still carry
    # this string, and a reader that fell back to the raw enum would show a worse label for a
    # historical tick than the one it was written with. The map is additive and never gates a choice.
    "team-execution": "team execution",
    "inline": "inline",
}


def display_orchestration_mode(mode: str) -> str:
    """Return the human-readable label for *mode*; fall back to the raw string on a miss."""
    return ORCHESTRATION_MODE_LABELS.get(mode, mode)


# maturity is DERIVED at /handoff time from lifecycle_phase — never stored and never
# surfaced by the generic engine (restore/scan). This is the contract mapping the future
# /handoff rebuild imports; see references/saga-spec.md §3.3.
PHASE_TO_MATURITY = {
    "ideation": "idea-ready",
    "brainstorm": "requirements-ready",
    "plan": "plan-ready",
    "review": "plan-ready",
    "work": "resume-ready",
    "qa": "resume-ready",
    "retro": "resume-ready",
}


class _Absent:
    """Sentinel for a list field the caller did not supply.

    Full-snapshot list semantics need three distinguishable states:
    ``ABSENT`` (carry the prior tick's list forward), ``[]`` (explicitly
    clear), and a populated list (replace). A bare default of ``[]`` cannot
    tell "carry forward" from "clear", so ``save`` defaults list fields to this
    sentinel. A persisted/parsed envelope always holds a concrete list (a
    stored tick is a full snapshot), never ``ABSENT``.
    """

    _instance: _Absent | None = None

    def __new__(cls) -> _Absent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "ABSENT"

    def __bool__(self) -> bool:
        return False


ABSENT = _Absent()
ListOrAbsent = list[Any] | _Absent


# ---------------------------------------------------------------------------
# Saga dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Saga:
    """One thread of lifecycle work. Frozen — ``save`` derives a new instance.

    ``extra`` preserves any unknown frontmatter keys read off disk so a
    round-trip (parse -> render) never drops a field a newer writer added.
    List fields use full-snapshot semantics at ``save`` time (a tick's list
    REPLACES the prior tick's). They default to the ``ABSENT`` sentinel so
    ``save`` can tell "carry forward" (``ABSENT``) from "clear" (``[]``); a
    persisted/parsed envelope always carries concrete lists, never ``ABSENT``.
    """

    # Identity (sticky, derived at birth).
    saga_id: str
    kind: str  # issue | task
    id: str  # issue number (as str) or task slug
    schema_version: str = SCHEMA_VERSION

    # Timestamps.
    created_at: str = ""
    updated_at: str = ""

    # The three stored state axes (one derived: maturity, not stored).
    lifecycle_phase: str = "ideation"  # CE-flow position
    phase_status: str = "pending"  # pending | in_progress | complete
    status: str = "active"  # active|blocked|paused|handed-off|done|abandoned

    # Resume anchor + orchestration.
    next_step: str = ""
    orchestration_mode: str = "inline"
    orchestration_ref: str = ""
    # Workflow run handle (#693): the TRANSIENT id the Workflow tool returns at launch.
    # Split out of orchestration_ref so the durable spec-path pointer and the run handle
    # coexist on one saga instead of clobbering each other (whichever was written last used
    # to win, and launch always ran after the spec read — so a launched saga lost its spec
    # path). /work records it post-launch via --orchestration-run-id and never overwrites
    # orchestration_ref. Empty on older sagas and on non-ultracode backends.
    orchestration_run_id: str = ""
    # Choice-vs-recommendation recording (R12 — enables override-rate computation in /retro+/optimize).
    # orchestration_recommended = what the recommender suggested;
    # orchestration_operator_choice = what the operator actually picked.
    # Either can differ from orchestration_mode when the operator overrides the recommendation.
    # Both default to "" so older sagas that lack these fields still parse without error.
    orchestration_recommended: str = ""
    orchestration_operator_choice: str = ""
    # Capability-portable degradation record (R11 / U12). On an off-host resume the
    # orchestration tier recompiles DOWN (Workflow tool unavailable); the one-line
    # downgrade note is recorded here so the degradation is durable, not silent. Empty
    # on a host that ran the authored tier; defaults to "" so older sagas still parse.
    orchestration_downgrade: str = ""

    # Pointers (link, never duplicate, another owner's state).
    issue_ref: str = ""  # owner/repo#N (empty for plan-only)
    destination: str = "plan-only"  # plan-only|pr|merge|nonprod-deploy
    # Operator-authored gate-or-auto posture for the saga -> deploy edge (issue #395, KTD3).
    # Captured once at /plan time (Phase 5.1, only when destination is nonprod-deploy) and read —
    # never re-asked — by deploy_handoff.offer. Carried forward like destination. Empty on older
    # sagas and on any destination that is not nonprod-deploy; deploy_handoff reads absent/empty as
    # the safe `gate` default (R5 — a missing posture can never auto-fire).
    deploy_autonomy: str = ""  # ""|gate|auto

    # Round / phase / progress.
    round: int = 0
    phase: int = 0
    progress_pct: int = 0

    # Artifact pointers.
    plan_path: str = ""
    work_session_paths: ListOrAbsent = ABSENT
    review_paths: ListOrAbsent = ABSENT
    qa_paths: ListOrAbsent = ABSENT
    artifact_pointers: ListOrAbsent = ABSENT

    # Git snapshot (cached for offline display; never the authority).
    branch: str = ""
    head_sha: str = ""
    last_commit_sha: str = ""
    files_modified: ListOrAbsent = ABSENT

    # Round history.
    rounds_seen: ListOrAbsent = ABSENT
    next_round: int = 1

    # Cross-owner pointers.
    pr_refs: ListOrAbsent = ABSENT
    adr_refs: ListOrAbsent = ABSENT
    journal_refs: ListOrAbsent = ABSENT

    # Disposition detail.
    blockers: str = ""
    open_questions: ListOrAbsent = ABSENT
    checks_run: ListOrAbsent = ABSENT
    gate_verdicts: ListOrAbsent = ABSENT
    gate_divergence: ListOrAbsent = ABSENT
    source: str = ""

    # Body sections (free-form prose).
    summary: str = ""
    decisions: str = ""
    remaining: str = ""
    notes: str = ""

    # Unknown-key round-trip preservation.
    extra: dict[str, Any] = field(default_factory=dict)


# Frontmatter machine fields, in stable render order. Body sections (summary,
# decisions, remaining, notes) and ``extra`` are handled separately.
FRONTMATTER_FIELDS: tuple[str, ...] = (
    "schema_version",
    "saga_id",
    "kind",
    "id",
    "created_at",
    "updated_at",
    "lifecycle_phase",
    "phase_status",
    "status",
    "next_step",
    "orchestration_mode",
    "orchestration_ref",
    "orchestration_run_id",
    "orchestration_recommended",
    "orchestration_operator_choice",
    "orchestration_downgrade",
    "issue_ref",
    "destination",
    "deploy_autonomy",
    "round",
    "phase",
    "progress_pct",
    "plan_path",
    "work_session_paths",
    "review_paths",
    "qa_paths",
    "artifact_pointers",
    "branch",
    "head_sha",
    "last_commit_sha",
    "files_modified",
    "rounds_seen",
    "next_round",
    "pr_refs",
    "adr_refs",
    "journal_refs",
    "blockers",
    "open_questions",
    "checks_run",
    "gate_verdicts",
    "gate_divergence",
    "source",
)

_BODY_FIELDS = ("summary", "decisions", "remaining", "notes")
_LIST_FIELDS = {
    "work_session_paths",
    "review_paths",
    "qa_paths",
    "artifact_pointers",
    "files_modified",
    "rounds_seen",
    "pr_refs",
    "adr_refs",
    "journal_refs",
    "open_questions",
    "checks_run",
    "gate_verdicts",
    "gate_divergence",
}

# List fields that render NO key at all when empty/absent (rather than the ``key: []`` the
# legacy list fields emit). This keeps a saga that never records artifact pointers byte-identical
# to a pre-field envelope — the same absent-emits-no-key contract #287's ``sandbox`` field adopted —
# while a populated value still round-trips through save/load.
_OMIT_WHEN_EMPTY_FIELDS = {"artifact_pointers"}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def slugify(value: str) -> str:
    """Lowercase, hyphen-join alphanumeric runs (stable, filesystem-safe)."""
    parts = re.findall(r"[a-z0-9]+", value.lower())
    return "-".join(parts) or "saga"


def derive_saga_id(kind: str, id_: str) -> str:
    """Mint the sticky, human-legible saga id: ``issue-<N>`` / ``task-<slug>``.

    Issue ids keep their number verbatim; task ids are slugified for a stable,
    filesystem-safe directory name. The id is derived from ``kind`` + ``id``
    only — ``round`` / ``phase`` are FIELDS, never part of identity.
    """
    if kind == "issue":
        return f"issue-{str(id_).strip()}"
    return f"task-{slugify(str(id_))}"


# ---------------------------------------------------------------------------
# Envelope render / parse (round-trip preserves extra)
# ---------------------------------------------------------------------------


def _yaml_scalar(value: Any) -> str:
    """Render a scalar for frontmatter; double-quote strings that need it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = "" if value is None else str(value)
    if text == "":
        return '""'
    needs_quote = (
        text != text.strip()
        or text[0] in "!&*?|>%@`\"'#-[]{},:"
        or ": " in text
        or text.endswith(":")
        or "\n" in text
        or text.lower() in {"null", "true", "false", "yes", "no", "~"}
    )
    if needs_quote:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def _render_value(key: str, value: Any) -> str:
    if isinstance(value, _Absent):
        value = []
    if isinstance(value, list):
        if not value:
            return f"{key}: []"
        lines = [f"{key}:"]
        lines.extend(f"  - {_yaml_scalar(item)}" for item in value)
        return "\n".join(lines)
    return f"{key}: {_yaml_scalar(value)}"


def render_envelope(saga: Saga) -> str:
    """Render a saga to a gstack-style frontmatter + body envelope (str)."""
    lines: list[str] = ["---"]
    for key in FRONTMATTER_FIELDS:
        value = getattr(saga, key)
        if key in _OMIT_WHEN_EMPTY_FIELDS and not _materialize(value):
            continue
        lines.append(_render_value(key, value))
    for key in sorted(saga.extra):
        lines.append(_render_value(key, saga.extra[key]))
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(saga.summary.strip())
    lines.append("")
    lines.append("## Decisions")
    lines.append("")
    lines.append(saga.decisions.strip())
    lines.append("")
    lines.append("## Remaining")
    lines.append("")
    lines.append(saga.remaining.strip())
    lines.append("")
    lines.append("## Notes / Tried")
    lines.append("")
    lines.append(saga.notes.strip())
    lines.append("")
    return "\n".join(lines)


def _coerce(name: str, raw: Any) -> Any:
    """Coerce a parsed frontmatter value to the dataclass field's type."""
    if name in _LIST_FIELDS:
        if raw is None:
            return []
        if isinstance(raw, list):
            if name == "rounds_seen":
                return [int(item) for item in raw]
            return [str(item) for item in raw]
        return [raw]
    if name in {"round", "phase", "progress_pct", "next_round"}:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    return "" if raw is None else str(raw)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block, body) splitting on the leading ``---`` fence."""
    stripped = text.lstrip("﻿")
    if not stripped.startswith("---"):
        return "", text
    rest = stripped[3:]
    if rest.startswith("\n"):
        rest = rest[1:]
    end = rest.find("\n---")
    if end == -1:
        return "", text
    front = rest[:end]
    body = rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    return front, body


def _parse_frontmatter(block: str) -> dict[str, Any]:
    """Parse a minimal YAML frontmatter block (scalars + ``- `` lists)."""
    parsed: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith(("  - ", "- ")) and current_key is not None:
            item = raw_line.split("- ", 1)[1].strip()
            existing = parsed.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(_unquote(item))
            continue
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            parsed[key] = []
            current_key = key
        elif value == "[]":
            parsed[key] = []
            current_key = None
        else:
            parsed[key] = _unquote(value)
            current_key = None
    return parsed


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_BODY_KEY_BY_HEADING = {
    "summary": "summary",
    "decisions": "decisions",
    "remaining": "remaining",
    "notes / tried": "notes",
    "notes": "notes",
}


def _parse_body(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        key = _BODY_KEY_BY_HEADING.get(heading)
        if key is None:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[key] = body[start:end].strip()
    return sections


def parse_envelope(text: str) -> Saga:
    """Parse an envelope back into a ``Saga``, preserving unknown keys in ``extra``."""
    front_block, body = _split_frontmatter(text)
    front = _parse_frontmatter(front_block)
    body_sections = _parse_body(body)

    known = {f.name for f in fields(Saga)}
    kwargs: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in front.items():
        if key in known and key not in _BODY_FIELDS and key != "extra":
            kwargs[key] = _coerce(key, value)
        else:
            extra[key] = value

    kwargs.setdefault("saga_id", str(front.get("saga_id", "")))
    kwargs.setdefault("kind", str(front.get("kind", "")))
    kwargs.setdefault("id", str(front.get("id", "")))
    for body_key in _BODY_FIELDS:
        kwargs[body_key] = body_sections.get(body_key, "")
    kwargs["extra"] = extra
    return Saga(**kwargs)


# ---------------------------------------------------------------------------
# Git snapshot (guarded; empty strings on any failure)
# ---------------------------------------------------------------------------


def current_git_state(root: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict[str, str]:
    """Best-effort git snapshot. Returns empty strings if git is unavailable."""

    def run(args: list[str]) -> str:
        try:
            result = runner(  # nosec B603
                args, cwd=root, capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if getattr(result, "returncode", 1) != 0:
            return ""
        return (result.stdout or "").strip()

    return {
        "branch": run(["git", "branch", "--show-current"]),
        "head": run(["git", "rev-parse", "--short", "HEAD"]),
        "last_commit": run(["git", "rev-parse", "HEAD"]),
    }


# ---------------------------------------------------------------------------
# save / update_index
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%d-%H%M%S")


def _next_phase(phase: int, phase_status: str) -> int:
    return phase + 1 if phase_status == "complete" else phase


def _materialize(value: ListOrAbsent) -> list[Any]:
    """Resolve a list-or-ABSENT field to a concrete list (ABSENT -> [])."""
    return [] if isinstance(value, _Absent) else list(value)


def _merge(
    prior: Saga | None,
    incoming: Saga,
    now: datetime,
    explicit_fields: frozenset[str] = frozenset(),
) -> Saga:
    """Full-snapshot merge: lists in ``incoming`` REPLACE prior; ABSENT carries forward.

    Scalar fields left at their dataclass default carry forward from the prior
    tick — UNLESS named in ``explicit_fields``, in which case the incoming value
    wins even when it equals the default. Default-equality alone cannot tell an
    omitted flag from an operator explicitly re-asserting the default value
    (e.g. ``--status active`` reactivating a paused saga), so the CLI passes the
    set of flags that were actually provided. List fields never union: an
    incoming populated list replaces, ``[]`` clears, and the ``ABSENT`` sentinel
    carries the prior tick's list forward. The persisted result always holds
    concrete lists (never ``ABSENT``).
    """
    created = prior.created_at if prior and prior.created_at else (incoming.created_at or "")
    if not created:
        created = now.isoformat()

    data: dict[str, Any] = {}
    defaults = {f.name: f.default for f in fields(Saga)}
    for f in fields(Saga):
        name = f.name
        inc_value = getattr(incoming, name)
        if name == "extra":
            merged_extra = dict(prior.extra) if prior else {}
            merged_extra.update(inc_value)
            data[name] = merged_extra
            continue
        if name in _LIST_FIELDS:
            if isinstance(inc_value, _Absent):
                # Carry the prior tick's list forward (or [] for a new saga).
                data[name] = _materialize(getattr(prior, name)) if prior else []
            else:
                # Snapshot-replace: populated list replaces, [] clears.
                data[name] = list(inc_value)
            continue
        if prior is None:
            data[name] = inc_value
            continue
        # Scalar carry-forward: if incoming left the default, inherit prior —
        # unless the caller marked the field explicit (a provided value that
        # happens to equal the default must win, not be read as "omitted").
        if name not in explicit_fields and inc_value == defaults.get(name):
            data[name] = getattr(prior, name)
        else:
            data[name] = inc_value

    data["created_at"] = created
    data["updated_at"] = now.isoformat()
    rounds = data["rounds_seen"]
    data["next_round"] = (max(rounds) + 1) if rounds else 1
    return Saga(**data)


def _allocate_envelope_path(saga_dir: Path, timestamp: str) -> Path:
    """Pick a non-colliding filename; same-second collision -> ``-1`` suffix."""
    candidate = saga_dir / f"{timestamp}.md"
    if not candidate.exists():
        return candidate
    seq = 1
    while True:
        candidate = saga_dir / f"{timestamp}-{seq}.md"
        if not candidate.exists():
            return candidate
        seq += 1


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class SagaSaveError(ValueError):
    """A save was rejected for violating a saga invariant (non-zero exit)."""


class SagaTickEnvelopeWriteError(OSError):
    """The tick envelope never reached disk: NO tick exists for this save.

    Whether the stranded-document remedy applies depends on the prior chain: only when
    no earlier tick references the plan document is it left on disk with nothing
    referencing it; when an earlier tick already records the plan path, the document
    stays tracked and only THIS save's tick is missing (cycle-2 C02/D04).
    """


class SagaTickIndexWriteError(OSError):
    """The tick envelope IS on disk; only the state.json index rewrite failed.

    ``restore`` reads the envelope directly and never opens state.json, so the tick
    is tracked. The message must not claim the plan lost its tick (review F05/F05u).
    Re-running the same save rebuilds the index but is NOT idempotent: each save
    allocates a fresh envelope, so the re-run appends one additional tick carrying the
    same state (cycle-2 C01/D03/P01/U09).
    """


def _orchestration_rank(mode: str) -> int | None:
    """Tier rank of an orchestration mode. One rung since issue #1030: ``inline``.

    Returns the index in ``ORCHESTRATION_MODES`` (a higher index is a richer/costlier tier),
    or ``None`` for an unrecognized value (the guard then can't reason about direction and is
    lenient). With one rung there is no upgrade or downgrade left to detect, and the function
    stays because the ladder is the shape the guard reads, not a count it assumes.

    That leniency is what keeps a saga written before issue #1030 readable: ``team-execution`` was
    the middle rung until that card archived the plugin, and a persisted tick still carrying the
    string ranks ``None`` rather than raising. The value is refused at the command line, where a
    new choice is made, and accepted on the way back in, where history is only being read.
    """
    try:
        return ORCHESTRATION_MODES.index(mode)
    except ValueError:
        return None


def _assert_orchestration_provenance(incoming: Saga, merged: Saga, prior: Saga | None) -> None:
    """Guard the orchestration-choice provenance at SAVE time only.

    Field semantics: ``orchestration_operator_choice`` is the AUTHORITATIVE operator
    pick; ``orchestration_mode`` is the EFFECTIVE backend that actually runs. The two
    diverge legitimately ONLY on a capability-portable DOWNGRADE — when an off-host
    resume recompiles the effective tier DOWN (to a cheaper tier than the operator picked)
    and records a one-line ``orchestration_downgrade`` note. A ``mode != operator_choice``
    save with NO downgrade note is the issue-38 shape (mode masquerading as a choice the
    operator never made) and is rejected.

    The divergence must be JUSTIFIED on the tick that asserts it — a stale note carried
    forward from a DIFFERENT prior divergence must not launder a fresh or changed one.
    ``_merge`` carries scalars forward, so the persisted (``merged``) divergence is
    allowed ONLY when (a) it is byte-identical to the prior tick's already-vetted
    divergence (an unchanged carry-forward — its note passed this guard when the prior
    tick saved), or (b) THIS tick (``incoming``) provides a fresh, non-blank
    ``orchestration_downgrade`` note AND the divergence is a genuine downgrade (effective
    ``mode`` is a LOWER tier than ``operator_choice``). A blank/whitespace note, or an
    "upgrade" (effective mode RICHER than the pick) labeled a downgrade, does not justify
    the divergence. This also catches a divergence introduced by asymmetric carry-forward
    (e.g. a partial tick that sets only ``operator_choice`` while ``mode`` carries forward).
    A recommendation override is a SEPARATE concern — the
    ``orchestration_recommended``-vs-``operator_choice`` pair — and is NOT guarded here.
    Lives in ``save()`` (not the dataclass or render/parse) so an unsaved render→parse
    round-trip with ``operator_choice != mode`` stays valid.
    """
    if not (
        merged.orchestration_operator_choice
        and merged.orchestration_mode != merged.orchestration_operator_choice
    ):
        return
    unchanged_carry_forward = (
        prior is not None
        and prior.orchestration_mode == merged.orchestration_mode
        and prior.orchestration_operator_choice == merged.orchestration_operator_choice
        and prior.orchestration_downgrade == merged.orchestration_downgrade
    )
    if unchanged_carry_forward:
        return
    note = incoming.orchestration_downgrade.strip()
    if note:
        mode_rank = _orchestration_rank(merged.orchestration_mode)
        choice_rank = _orchestration_rank(merged.orchestration_operator_choice)
        # A note justifies the divergence only for a genuine downgrade (mode tier < pick tier),
        # or when a tier is unrecognized and direction can't be judged (be lenient there).
        if mode_rank is None or choice_rank is None or mode_rank < choice_rank:
            return
        raise SagaSaveError(
            f"orchestration_mode ({merged.orchestration_mode!r}) is a RICHER tier than "
            f"orchestration_operator_choice ({merged.orchestration_operator_choice!r}); a "
            "downgrade note cannot justify an UPGRADE divergence. operator_choice must name the "
            "tier the operator actually picked (>= the effective mode), or record a real downgrade."
        )
    raise SagaSaveError(
        "orchestration_mode "
        f"({merged.orchestration_mode!r}) != orchestration_operator_choice "
        f"({merged.orchestration_operator_choice!r}) with no orchestration_downgrade note "
        "on this tick: the effective backend may differ from the operator's pick ONLY on a "
        "downgrade recorded WITH the divergence (a stale or blank note cannot justify "
        "a new one). Pass --orchestration-downgrade to record the reason, or align "
        "--orchestration-mode with the operator's choice."
    )


def save(
    root: Path,
    saga: Saga,
    *,
    now: datetime | None = None,
    runner: Callable[..., Any] = subprocess.run,
    explicit_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Persist a new immutable tick + refresh the derived index.

    Merges with the latest prior tick (full-snapshot list semantics, scalar
    carry-forward), captures git state (guarded), writes a new immutable
    ``sagas/<saga_id>/<YYYYMMDD-HHMMSS>.md`` (``-N`` suffix on same-second
    collision), and atomically rewrites ``state.json`` via ``update_index``.
    Scalar fields named in ``explicit_fields`` bypass the default-equality
    carry-forward in ``_merge`` (the caller vouches they were provided, not
    merely left at their default).
    """
    moment = now or _utc_now()
    prior = restore(root, saga.saga_id)
    # ``kind`` is a sticky identity field with no dataclass default, so _merge's default-equality
    # carry-forward cannot protect it: an omitted --kind would stamp its resolved value over the
    # prior tick's kind (issue-157 residual — a save with --saga-id but no --kind flipped a task
    # saga to "issue"). When kind was not explicitly provided (absent from explicit_fields),
    # inherit the prior tick's kind; an explicit kind that contradicts the prior is rejected,
    # because identity is fixed at birth and a save must never silently flip it.
    if prior is not None:
        if "kind" not in explicit_fields:
            saga = _replace(saga, kind=prior.kind)
        elif saga.kind != prior.kind:
            raise SagaSaveError(
                f"--kind {saga.kind!r} contradicts saga {saga.saga_id}'s recorded kind "
                f"{prior.kind!r}; kind is a sticky identity field fixed at birth"
            )
    merged = _merge(prior, saga, moment, explicit_fields)

    git = current_git_state(root, runner=runner)
    # ``branch`` refreshes from live git on EVERY save (issue #480), not just the first, so a saga
    # minted on ``main`` by ``/plan`` — before its work branch exists — starts tracking the real
    # branch as soon as ``/work`` re-saves on it, and any later reader sees the actual branch
    # instead of the mint-time ``main``. Two guards on the refresh: the
    # empty ``git["branch"]`` read (detached HEAD / no git) never clobbers a stored value, and a
    # save made back on the default branch never overwrites an already-recorded real work branch
    # (else the ceremony's own ``checkout_main`` progress-save would erase what ``branch_delete``
    # needs). ``head_sha``/``last_commit_sha`` refresh on every save too (they were the #480
    # follow-up): SHAs have no default-branch downgrade concern, so a plain non-empty guard
    # suffices, and the stored SHAs then track the current commit instead of freezing at the
    # mint-time HEAD (``status_card`` renders ``head_sha`` as its CI reference).
    live_branch = git["branch"]
    downgrades_work_branch = (
        live_branch in _DEFAULT_BRANCHES
        and bool(merged.branch)
        and merged.branch not in _DEFAULT_BRANCHES
    )
    if live_branch and not downgrades_work_branch:
        merged = _replace(merged, branch=live_branch)
    if git["head"]:
        merged = _replace(merged, head_sha=git["head"])
    if git["last_commit"]:
        merged = _replace(merged, last_commit_sha=git["last_commit"])

    _assert_orchestration_provenance(saga, merged, prior)

    saga_dir = root / SAGAS_DIR / merged.saga_id
    # Two distinct writes, two distinct failures (review F05): the envelope goes down
    # first, then the state.json index rewrite. Only an envelope-phase failure leaves
    # the plan document with no tick; an index-only failure still leaves a tracked tick
    # because ``restore`` reads the envelope directly and never opens state.json.
    try:
        saga_dir.mkdir(parents=True, exist_ok=True)
        envelope_path = _allocate_envelope_path(saga_dir, _timestamp(moment))
        envelope_path.write_text(render_envelope(merged), encoding="utf-8")
    except OSError as exc:
        raise SagaTickEnvelopeWriteError(str(exc)) from exc

    try:
        state_path = update_index(root, merged, now=moment)
    except OSError as exc:
        raise SagaTickIndexWriteError(
            f"tick envelope written to {envelope_path}, then: {exc}"
        ) from exc
    return {
        "saga_id": merged.saga_id,
        "envelope_path": str(envelope_path),
        "state_path": str(state_path),
        "phase": merged.phase,
        "status": merged.status,
        "next_phase": _next_phase(merged.phase, merged.phase_status),
        "next_round": merged.next_round,
    }


def _replace(saga: Saga, **changes: Any) -> Saga:
    data = {f.name: getattr(saga, f.name) for f in fields(Saga)}
    data.update(changes)
    return Saga(**data)


def _saga_summary(saga: Saga) -> dict[str, Any]:
    return {
        "saga_id": saga.saga_id,
        "kind": saga.kind,
        "id": saga.id,
        "lifecycle_phase": saga.lifecycle_phase,
        "phase_status": saga.phase_status,
        "status": saga.status,
        "phase": saga.phase,
        "round": saga.round,
        "next_phase": _next_phase(saga.phase, saga.phase_status),
        "next_round": saga.next_round,
        "destination": saga.destination,
        # deploy_autonomy + pr_refs travel in the derived index so deploy_handoff.offer can read
        # the gate-or-auto posture and merged PR refs from state.json["sagas"][saga_id] without
        # parsing the envelope (issue #395, KTD3 — precedent handoff_envelope.read_state).
        "deploy_autonomy": saga.deploy_autonomy,
        "pr_refs": _materialize(saga.pr_refs),
        "issue_ref": saga.issue_ref,
        "plan_path": saga.plan_path,
        "branch": saga.branch,
        "orchestration_mode": saga.orchestration_mode,
        "orchestration_ref": saga.orchestration_ref,
        # #693: the run handle rides beside the spec ref so both surfaces can report it.
        "orchestration_run_id": saga.orchestration_run_id,
        "next_step": saga.next_step,
        "updated_at": saga.updated_at,
    }


def _tick_snapshot(saga: Saga) -> dict[str, Any]:
    """A per-tick dict for the ``ticks`` reader: the summary fields PLUS the

    trajectory fields that differ across the chain (blockers / summary /
    open_questions / rounds_seen), so the full work-state evolution is visible
    where ``restore`` (latest-only) would only surface the final values. Builds
    on ``_saga_summary`` so the two readers share the machine-field shape.
    """
    snapshot = _saga_summary(saga)
    snapshot.update(
        {
            "blockers": saga.blockers,
            "summary": saga.summary,
            "open_questions": _materialize(saga.open_questions),
            "rounds_seen": _materialize(saga.rounds_seen),
        }
    )
    return snapshot


def update_index(root: Path, saga: Saga, *, now: datetime | None = None) -> Path:
    """Refresh the derived ``state.json`` index atomically.

    Shape::

        {last_updated, active_saga_id, sagas:{<saga_id>:{...summary...}},
         current_work:{...legacy fields..., saga_id}}

    ``current_work`` mirrors the most-recently-saved saga (carrying its
    ``saga_id`` so multi-saga readers can detect a mismatch) and keeps the
    legacy key set ``handoff_envelope`` and its test read unchanged.
    """
    moment = now or _utc_now()
    state_path = root / STATE_DIR / "state.json"
    state: dict[str, Any] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except json.JSONDecodeError:
            state = {}

    sagas = state.get("sagas")
    if not isinstance(sagas, dict):
        sagas = {}
    sagas[saga.saga_id] = _saga_summary(saga)

    state["last_updated"] = moment.isoformat()
    state["active_saga_id"] = saga.saga_id
    state["sagas"] = sagas
    work_sessions = _materialize(saga.work_session_paths)
    state["current_work"] = {
        "kind": saga.kind,
        "id": saga.id,
        "round": saga.round,
        "phase": saga.phase,
        "phase_status": saga.phase_status,
        "destination": saga.destination,
        "plan_path": saga.plan_path,
        "work_session_path": work_sessions[0] if work_sessions else "",
        "next_steps": [saga.next_step] if saga.next_step else [],
        "saga_id": saga.saga_id,
    }
    _atomic_write(state_path, json.dumps(state, indent=2) + "\n")
    return state_path


# ---------------------------------------------------------------------------
# restore / latest_envelope_for / scan
# ---------------------------------------------------------------------------


def envelope_sort_key(name: str) -> tuple[str, int]:
    """Structured FILENAME ordering key: ``(timestamp, seq)``.

    The base tick ``<ts>.md`` is seq 0; a same-second collision ``<ts>-N.md``
    is seq N, so the suffixed file always sorts AFTER its base (naive string
    compare would wrongly place ``<ts>-1.md`` before ``<ts>.md`` because ``-``
    < ``.``). Ordering is still derived purely from the filename — never mtime.
    """
    match = ENVELOPE_RE.match(name)
    if match is None:
        return (name, -1)
    return (match.group("ts"), int(match.group("seq") or 0))


def _envelope_files(saga_dir: Path) -> list[Path]:
    if not saga_dir.is_dir():
        return []
    return [p for p in saga_dir.iterdir() if p.is_file() and ENVELOPE_RE.match(p.name)]


def latest_envelope_for(root: Path, saga_id: str) -> Path | None:
    """Return the newest tick for a saga, ordered by FILENAME (never mtime)."""
    files = _envelope_files(root / SAGAS_DIR / saga_id)
    if not files:
        return None
    return max(files, key=lambda p: envelope_sort_key(p.name))


def restore(root: Path, saga_id: str) -> Saga | None:
    """Cold-reconstruct a saga from its latest tick. NEVER calls git/subprocess.

    Branch-agnostic: reads the envelope frontmatter + body only, so a saga
    restores identically regardless of the current checkout.
    """
    latest = latest_envelope_for(root, saga_id)
    if latest is None:
        return None
    return parse_envelope(latest.read_text(encoding="utf-8"))


def read_ticks(root: Path, saga_id: str) -> list[Saga]:
    """Return EVERY tick of a saga, oldest -> newest by FILENAME (never mtime).

    The full tick-chain trajectory that ``restore`` (latest-tick-only) cannot
    see: ``/resume``'s heavy forensic tier reads this to replay how the work
    state evolved (early ``next_step``s, blockers that later cleared, etc.).
    Reuses ``_envelope_files`` + ``envelope_sort_key`` + ``parse_envelope`` —
    same ordering contract as ``restore``, just the whole chain instead of the
    tail. Returns ``[]`` for an unknown/empty saga (NEVER calls git/subprocess).
    """
    files = sorted(
        _envelope_files(root / SAGAS_DIR / saga_id),
        key=lambda p: envelope_sort_key(p.name),
    )
    return [parse_envelope(p.read_text(encoding="utf-8")) for p in files]


def authoritative_next_step(
    root: Path,
    saga_id: str,
    *,
    store_root: Path | None = None,
) -> str:
    """Return the run's ``next_step``, preferring the run record over this envelope log (#1023).

    Both this engine and the run record carry a field of that name, so something has to say which
    wins. The RECORD wins (plan KTD8a): it is the one file every role reads, and the envelope log
    is append-only history whose older ticks are *meant* to hold stale values, so reconciling in
    the other direction would let a stale tick move a live run backwards.

    Falls back to the envelope's value when there is no record for the issue, when the saga is not
    issue-shaped, or when the record module is unavailable — a missing record means "no run record
    yet", never "no next step".
    """
    saga = restore(root, saga_id)
    envelope_value = saga.next_step if saga is not None else ""
    if saga is None or saga.kind != "issue" or not saga.id.isdigit():
        return envelope_value
    try:
        import run_record  # noqa: PLC0415  (optional at call time, by design)

        resolved = Path(store_root) if store_root is not None else run_record.resolve_store_root()
        recorded = run_record.get_next_step(resolved, int(saga.id))
    except Exception:
        return envelope_value
    return recorded or envelope_value


def mirror_next_step_to_record(
    saga: Saga,
    *,
    store_root: Path | None = None,
) -> Path | None:
    """Write *saga*'s ``next_step`` onto the issue's run record; return the path, or ``None``.

    The write direction that KTD8a allows: a tick that sets a next step updates the authority.
    Silent on every failure a caller cannot act on — a saga tick must not fail because the run
    record's store is unreachable, since the tick is the older and more fundamental artifact.

    **``save`` deliberately does not call this.** Mirroring automatically would resolve the real
    store — the primary checkout's live ``.claude/saga/runs`` — from every test in the suite that
    saves a tick against a temporary root, which is a live write from a unit test. A caller that
    wants the mirror asks for it and, in a test, names the store
    (``tests/test_run_record.py::test_saving_a_saga_tick_does_not_write_into_the_record_store_by_itself``
    pins that).
    """
    if saga.kind != "issue" or not saga.id.isdigit() or not saga.next_step:
        return None
    try:
        import run_record  # noqa: PLC0415  (optional at call time, by design)

        resolved = Path(store_root) if store_root is not None else run_record.resolve_store_root()
        return run_record.set_next_step(resolved, int(saga.id), saga.next_step)
    except Exception:
        return None


def _normalized_plan_path(root: Path, plan_path: str) -> Path:
    """Return a lexical absolute path for comparing recorded plan references."""
    path = Path(plan_path)
    if not path.is_absolute():
        path = root / path
    return Path(os.path.abspath(path))


def _scan_legacy(root: Path) -> list[dict[str, Any]]:
    """Read pre-0.4.0 ``checkpoints/`` as a low-priority, flagged fallback."""
    legacy_dir = root / LEGACY_CHECKPOINT_DIR
    if not legacy_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in legacy_dir.glob("*.md"):
        match = LEGACY_CHECKPOINT_RE.match(path.name)
        if not match:
            continue
        status = match.group("status") or "pending"
        phase = int(match.group("phase"))
        records.append(
            {
                "saga_id": derive_saga_id(match.group("kind"), match.group("id")),
                "path": str(path),
                "name": path.name,
                "kind": match.group("kind"),
                "id": match.group("id"),
                "round": int(match.group("round")) if match.group("round") else None,
                "phase": phase,
                "phase_status": status,
                "next_phase": _next_phase(phase, status),
                "legacy": True,
            }
        )
    return sorted(records, key=lambda r: r["name"], reverse=True)


def scan(root: Path, *, max_candidates: int | None = None) -> list[dict[str, Any]]:
    """List one candidate per saga (latest tick each), newest FIRST by filename.

    Groups per saga directory, reads the latest tick of each, sorts the group
    by envelope filename descending, then appends flagged legacy checkpoints
    (one version of back-compat). Non-matching files/dirs are skipped.
    """
    sagas_root = root / SAGAS_DIR
    candidates: list[dict[str, Any]] = []
    if sagas_root.is_dir():
        for saga_dir in sagas_root.iterdir():
            if not saga_dir.is_dir():
                continue
            latest = latest_envelope_for(root, saga_dir.name)
            if latest is None:
                continue
            saga = parse_envelope(latest.read_text(encoding="utf-8"))
            candidates.append(
                {
                    "saga_id": saga.saga_id or saga_dir.name,
                    "path": str(latest),
                    "name": latest.name,
                    "kind": saga.kind,
                    "id": saga.id,
                    "round": saga.round,
                    "phase": saga.phase,
                    "phase_status": saga.phase_status,
                    "status": saga.status,
                    "lifecycle_phase": saga.lifecycle_phase,
                    "next_phase": _next_phase(saga.phase, saga.phase_status),
                    "next_step": saga.next_step,
                    "updated_at": saga.updated_at,
                    "destination": saga.destination,
                    "issue_ref": saga.issue_ref,
                    "plan_path": saga.plan_path,
                    "branch": saga.branch,
                    "orchestration_mode": saga.orchestration_mode,
                    "orchestration_ref": saga.orchestration_ref,
                    "orchestration_run_id": saga.orchestration_run_id,
                    "legacy": False,
                }
            )
    candidates.sort(key=lambda c: envelope_sort_key(c["name"]), reverse=True)
    candidates.extend(_scan_legacy(root))
    if max_candidates is not None:
        return candidates[:max_candidates]
    return candidates


# ---------------------------------------------------------------------------
# spec-ref validation (#693)
# ---------------------------------------------------------------------------

# Workflow run handles minted by the Workflow tool are shaped ``wf_<hex>-<hex>`` (e.g.
# ``wf_7dbd5245-def``). Since #693 they live in ``orchestration_run_id``; finding one in
# ``orchestration_ref`` means the durable spec-path pointer was clobbered by the pre-#693
# overload (launch wrote the run id over the spec path the launch itself had just read).
_RUN_ID_RE = re.compile(r"^wf[_-][A-Za-z0-9-]+$")


def looks_like_run_id(value: str) -> bool:
    """True when ``value`` is shaped like a workflow run handle, not a file path."""
    return bool(_RUN_ID_RE.match(value.strip()))


def spec_ref_verdict(saga: Saga, root: Path) -> tuple[str, str]:
    """Classify the saga's ``orchestration_ref`` for a workflow launch/resume (#693).

    Returns ``(verdict, detail)``: ``ok`` (a spec path whose file exists), ``missing``
    (ref empty), ``run-id`` (a workflow run handle — the wrong kind of value), or
    ``file-missing`` (a plausible path whose file does not exist). Every verdict but
    ``ok`` is a HALT condition for ``/work``'s ultracode launch. The guard DISCRIMINATES
    rather than testing presence: a run handle held BESIDE the ref (in
    ``orchestration_run_id``) never satisfies it, so a saga that lost its spec path halts
    loudly instead of handing a workflow id to a script expecting a filename.
    """
    ref = saga.orchestration_ref.strip()
    if not ref:
        return "missing", "saga orchestration_ref is empty"
    if looks_like_run_id(ref):
        return (
            "run-id",
            f"saga orchestration_ref holds a workflow run handle ({ref!r}), not the spec "
            "path — the run handle belongs in orchestration_run_id (#693)",
        )
    if not (root / ref).is_file():
        return "file-missing", f"spec file does not exist at {ref!r}"
    return "ok", ref


# ---------------------------------------------------------------------------
# aggregate_context (lifted from load_saga_context.py)
# ---------------------------------------------------------------------------


def adr_refs_from_text(content: str | None) -> list[str]:
    """Extract normalized ``ADR-NNNN`` refs from free text."""
    if not content:
        return []
    matches = re.findall(r"\bADR[-\s]?(\d{2,4})\b", content, flags=re.IGNORECASE)
    return [f"ADR-{int(number):04d}" for number in matches]


def parse_repo(value: str) -> tuple[str, str]:
    """Split ``owner/repo`` (defaulting owner to ``infiquetra``)."""
    if "/" in value:
        owner, repo = value.split("/", 1)
        return owner, repo
    return "infiquetra", value


def prior_prs(
    owner: str, repo: str, issue: int, *, runner: Callable[..., Any] = subprocess.run
) -> list[dict[str, Any]]:
    """Round-tagged prior PRs for an issue (empty if ``gh`` missing/fails)."""
    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        f"{owner}/{repo}",
        "--state",
        "all",
        "--search",
        f"in:title #{issue} round",
        "--json",
        "number,title,state,mergedAt,url,reviewDecision,body",
        "--limit",
        "50",
    ]
    try:
        result = runner(cmd, capture_output=True, text=True, check=False)  # nosec B603
    except (FileNotFoundError, OSError):
        return []
    if getattr(result, "returncode", 1) != 0:
        return []
    records: list[dict[str, Any]] = []
    for pr in json.loads(result.stdout or "[]"):
        round_match = ROUND_RE.search(pr.get("title", "") or "")
        records.append(
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "mergedAt": pr.get("mergedAt"),
                "url": pr.get("url"),
                "reviewDecision": pr.get("reviewDecision"),
                "round": int(round_match.group(1)) if round_match else None,
                "body_preview": (pr.get("body") or "")[:500],
            }
        )
    return sorted(records, key=lambda record: int(record.get("round") or 0))


def journal_entries(root: Path, issue: int, adr_refs: list[str]) -> dict[str, list[dict[str, str]]]:
    """Find journal sections referencing the issue or its ADRs."""
    output: dict[str, list[dict[str, str]]] = {"learnings": [], "decisions": []}
    journal_dir = root / "docs" / "engineering-journal"
    if not journal_dir.exists():
        return output

    refs_to_search = [f"#{issue}", *adr_refs]
    for filename, key in (("LEARNINGS.md", "learnings"), ("DECISIONS.md", "decisions")):
        path = journal_dir / filename
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        sections = re.split(r"^## ", content, flags=re.MULTILINE)
        for section in sections[1:]:
            if any(ref in section for ref in refs_to_search):
                output[key].append(
                    {
                        "file": str(path),
                        "title": section.splitlines()[0].strip() if section else "",
                        "preview": section[:600],
                    }
                )
    return output


def aggregate_context(
    root: Path,
    owner: str,
    repo: str,
    issue: int,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Aggregate prior PRs, saga context, ADR refs, and journal entries.

    A missing ``gh`` never raises — ``prior_prs`` swallows ``FileNotFoundError``
    / ``OSError`` and returns an empty list, so offline resume still works.
    """
    saga_id = derive_saga_id("issue", str(issue))
    saga = restore(root, saga_id)
    prs = prior_prs(owner, repo, issue, runner=runner)

    saga_adrs = _materialize(saga.adr_refs) if saga is not None else []
    seed_text = ""
    if saga is not None:
        seed_text = "\n".join(
            [saga.summary, saga.decisions, saga.remaining, saga.notes, " ".join(saga_adrs)]
        )
    adrs = sorted(set(adr_refs_from_text(seed_text)) | set(saga_adrs))
    rounds_seen = sorted({int(pr["round"]) for pr in prs if pr.get("round") is not None})
    saga_summary = None
    if saga is not None:
        saga_summary = {
            "saga_id": saga.saga_id,
            "name": (latest := latest_envelope_for(root, saga_id)) and latest.name,
            "path": str(latest) if latest else None,
            "lifecycle_phase": saga.lifecycle_phase,
            "phase": saga.phase,
            "phase_status": saga.phase_status,
            "status": saga.status,
            "next_step": saga.next_step,
            "content_preview": render_envelope(saga)[:2000],
        }

    return {
        "repo": f"{owner}/{repo}",
        "issue": issue,
        "rounds_seen": rounds_seen,
        "next_round": (max(rounds_seen) + 1) if rounds_seen else 1,
        "saga": saga_summary,
        "prior_prs": prs,
        "adr_refs": adrs,
        "journal": journal_entries(root, issue, adrs),
    }


# ---------------------------------------------------------------------------
# Gate verdict helpers (R1 / KTD4 / U2)
# ---------------------------------------------------------------------------

# The six canonical R1 gate states (wire values — never change these).
_GATE_STATES: frozenset[str] = frozenset(
    {"done", "in-progress", "blocked", "failed", "halted", "not-reached"}
)


def parse_gate_verdict(entry: str) -> tuple[str, str, str]:
    """Parse a ``gate:state:ref`` entry into ``(gate, state, ref)``.

    Splits on the FIRST TWO colons only so a ref that contains colons
    (e.g. a GitHub URL ``https://github.com/o/r/pull/9`` or a ``path:line``
    citation) survives intact.  Raises ``ValueError`` when the state is not one
    of the six R1 canonical values.
    """
    first_colon = entry.find(":")
    if first_colon == -1:
        raise ValueError(f"gate_verdict entry has no colon separator: {entry!r}")
    second_colon = entry.find(":", first_colon + 1)
    if second_colon == -1:
        raise ValueError(
            f"gate_verdict entry has only one colon — expected gate:state:ref: {entry!r}"
        )
    gate = entry[:first_colon]
    state = entry[first_colon + 1 : second_colon]
    ref = entry[second_colon + 1 :]
    if state not in _GATE_STATES:
        raise ValueError(
            f"unknown gate state {state!r} in {entry!r}; "
            f"must be one of: {', '.join(sorted(_GATE_STATES))}"
        )
    return gate, state, ref


_GATE_DIVERGENCE_REQUIRED_KEYS = ("gate_id", "offered", "answer", "divergence")


def encode_gate_divergence_entry(
    gate_id: str,
    offered: str,
    answer: str,
    divergence: bool,
    latency_seconds: float | int | None = None,
) -> str:
    """Encode one gate-divergence interaction as a base64-wrapped JSON blob.

    Base64 (KTD1, docs/plans/2026-07-04-gate-divergence-telemetry-plan.md) so the entry never
    depends on ``_yaml_scalar``'s quoting/escaping being exercised correctly for arbitrary
    ``offered``/``answer`` free text (embedded newlines, a leading ``-``, an embedded ``: ``,
    etc.) — the field is a repeatable ``--gate-divergence`` CLI arg rendered as a plain YAML
    list item (``_render_value``), not a pipe-joined value passed through ``_split_list`` (that
    machinery is only used for single-flag multi-value fields like ``--artifact-pointers``).
    ``_yaml_scalar`` already quotes/escapes these characters correctly today, so this is
    defense-in-depth rather than a fix for a live corruption bug — but it means a future change
    to ``_yaml_scalar``'s escaping logic cannot silently corrupt ``gate_divergence`` entries,
    since base64's alphabet (``A-Za-z0-9+/=``) never needs the quoting path at all.
    """
    blob = json.dumps(
        {
            "gate_id": gate_id,
            "offered": offered,
            "answer": answer,
            "divergence": divergence,
            "latency_seconds": latency_seconds,
        }
    )
    return base64.b64encode(blob.encode("utf-8")).decode("ascii")


def parse_gate_divergence_entry(entry: str) -> dict[str, Any]:
    """Decode and validate one base64-wrapped ``gate_divergence`` JSON entry.

    Raises ``ValueError`` (echoing the offending entry) when the entry is not valid base64,
    not valid JSON, or missing a required key.
    """
    try:
        blob = base64.b64decode(entry.encode("ascii"), validate=True).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"gate_divergence entry is not valid base64: {entry!r}") from exc
    try:
        parsed = json.loads(blob)
    except (json.JSONDecodeError, RecursionError) as exc:
        # RecursionError is caught alongside JSONDecodeError: a maliciously deep-nested JSON
        # payload (e.g. thousands of nested ``[``) exhausts Python's recursion limit inside
        # json.loads rather than raising JSONDecodeError, and an uncaught RecursionError would
        # crash gate_divergence_reader.py's main() instead of skipping the malformed entry.
        raise ValueError(f"gate_divergence entry decoded to invalid JSON: {entry!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"gate_divergence entry must decode to a JSON object: {entry!r}")
    missing = [key for key in _GATE_DIVERGENCE_REQUIRED_KEYS if key not in parsed]
    if missing:
        raise ValueError(f"gate_divergence entry missing required key(s) {missing}: {entry!r}")
    latency = parsed.get("latency_seconds")
    if latency is not None and not isinstance(latency, (int, float)):
        raise ValueError(
            f"gate_divergence entry latency_seconds must be int, float, or null: {entry!r}"
        )
    return parsed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _split_list(value: str | None) -> ListOrAbsent:
    """A missing flag (``None``) -> ABSENT (carry forward); a value -> a list.

    An explicit empty string clears (``[]``), matching snapshot semantics.
    """
    if value is None:
        return ABSENT
    return [item.strip() for item in value.split("|") if item.strip()]


def _split_int_list(value: str | None) -> ListOrAbsent:
    parsed = _split_list(value)
    if isinstance(parsed, _Absent):
        return ABSENT
    return [int(item) for item in parsed]


# Scalar save flags whose meaningful value-space INCLUDES the dataclass default.
# Each argparse default is None so an omitted flag (carry the prior tick's value
# forward in _merge) stays distinguishable from an explicit value that happens to
# equal the default — e.g. ``--status active`` reactivating a paused saga, which
# a default of "active" silently swallowed (reproduced 2026-07-09, issue-157).
# Maps flag dest -> the dataclass default substituted when the flag is omitted.
_SAVE_SCALAR_DEFAULTS: dict[str, Any] = {
    "lifecycle_phase": "ideation",
    "phase_status": "pending",
    "status": "active",
    "destination": "plan-only",
    "deploy_autonomy": "",
    "phase": 0,
    "round": 0,
    "progress_pct": 0,
}


def _build_save_saga(args: argparse.Namespace) -> tuple[Saga, frozenset[str]]:
    """Build the incoming tick + the set of scalar fields the operator explicitly set."""
    # kind is a sticky identity field with no dataclass default; an omitted --kind resolves to
    # "issue" for a NEW saga (needed to derive the id) but is carried forward from the prior tick
    # for an existing --saga-id (resolved in save() via explicit_fields — issue-157 residual).
    kind = args.kind if args.kind is not None else "issue"
    saga_id = args.saga_id or derive_saga_id(kind, args.id)
    explicit = {name for name in _SAVE_SCALAR_DEFAULTS if getattr(args, name) is not None}
    if args.kind is not None:
        explicit.add("kind")
    scalars = {
        name: default if getattr(args, name) is None else getattr(args, name)
        for name, default in _SAVE_SCALAR_DEFAULTS.items()
    }
    # operator_choice = the AUTHORITATIVE operator pick; mode = the EFFECTIVE backend.
    # --orchestration-mode defaults to None (NOT "inline") so a progress tick that passes
    # NO orchestration signal leaves BOTH mode and operator_choice at their dataclass
    # defaults -> _merge carries the prior tick's real values forward. A progress tick must
    # not silently re-stamp an "inline" choice over a cc-workflows-ultracode saga, which
    # would manufacture a false mode != operator_choice divergence (rejected by the save-time
    # provenance guard). When --orchestration-mode IS given, the chosen backend IS the
    # operator's pick unless an explicit --orchestration-operator-choice overrides it (the
    # recorded-degrade / override case). A recommendation override is the SEPARATE
    # recommended-vs-choice pair below.
    mode_explicit = args.orchestration_mode is not None
    orchestration_mode = args.orchestration_mode if mode_explicit else "inline"
    orchestration_operator_choice = args.orchestration_operator_choice or (
        args.orchestration_mode if mode_explicit else ""
    )
    if mode_explicit:
        # An explicit mode wins in _merge even when it equals the "inline" dataclass
        # default: re-asserting inline over a richer prior tier is a real operator
        # action, and without this the carried-forward prior mode diverges from the
        # freshly stamped operator_choice and trips the provenance guard.
        explicit.add("orchestration_mode")
    return Saga(
        saga_id=saga_id,
        kind=kind,
        id=str(args.id),
        lifecycle_phase=scalars["lifecycle_phase"],
        phase_status=scalars["phase_status"],
        status=scalars["status"],
        next_step=args.next_step,
        orchestration_mode=orchestration_mode,
        orchestration_ref=args.orchestration_ref,
        orchestration_run_id=args.orchestration_run_id,
        orchestration_recommended=args.orchestration_recommended,
        orchestration_operator_choice=orchestration_operator_choice,
        orchestration_downgrade=args.orchestration_downgrade,
        issue_ref=args.issue_ref,
        destination=scalars["destination"],
        deploy_autonomy=scalars["deploy_autonomy"],
        round=scalars["round"],
        phase=scalars["phase"],
        progress_pct=scalars["progress_pct"],
        plan_path=args.plan_path,
        work_session_paths=_split_list(args.work_session_paths),
        review_paths=_split_list(args.review_paths),
        qa_paths=_split_list(args.qa_paths),
        artifact_pointers=_split_list(args.artifact_pointers),
        files_modified=_split_list(args.files_modified),
        rounds_seen=_split_int_list(args.rounds_seen),
        pr_refs=_split_list(args.pr_refs),
        adr_refs=_split_list(args.adr_refs),
        journal_refs=_split_list(args.journal_refs),
        blockers=args.blockers,
        open_questions=_split_list(args.open_questions),
        checks_run=_split_list(args.checks_run),
        gate_verdicts=ABSENT
        if args.gate_verdict is None
        else _validated_gate_verdicts(args.gate_verdict),
        gate_divergence=ABSENT if args.gate_divergence is None else list(args.gate_divergence),
        source=args.source,
        summary=args.summary,
        decisions=args.decisions,
        remaining=args.remaining,
        notes=args.notes,
    ), frozenset(explicit)


def _validated_gate_verdicts(verdicts: list[str]) -> list[str]:
    """Validate each ``gate:state:ref`` via ``parse_gate_verdict``; refuse on ValueError."""
    validated: list[str] = []
    for entry in verdicts:
        try:
            parse_gate_verdict(entry)
        except ValueError as exc:
            raise SagaSaveError(str(exc)) from exc
        validated.append(entry)
    return validated


def _add_save_parser(sub: Any) -> None:
    p = sub.add_parser("save", help="Write a new immutable saga tick")
    p.add_argument("--saga-id", default="", help="Override derived saga id")
    # default None (NOT "issue") so an omitted --kind on an existing --saga-id carries the prior
    # tick's kind forward in save() instead of stamping "issue" over a task saga (issue-157
    # residual). A new saga (no --saga-id) with no --kind resolves to "issue" in _build_save_saga.
    p.add_argument("--kind", choices=["issue", "task"], default=None)
    p.add_argument("--id", required=True, help="Issue number or task slug")
    # Scalar state flags default to None (NOT their dataclass defaults) so an omitted
    # flag carries the prior tick's value forward while an EXPLICIT value equal to the
    # default (e.g. --status active on a paused saga) still wins in _merge. Omission
    # resolves to the _SAVE_SCALAR_DEFAULTS value in _build_save_saga for a new saga.
    p.add_argument("--lifecycle-phase", choices=list(LIFECYCLE_PHASES), default=None)
    p.add_argument("--status", choices=list(STATUSES), default=None, help="thread disposition")
    p.add_argument(
        "--phase-status", choices=list(PHASE_STATUSES), default=None, help="phase completion"
    )
    p.add_argument("--phase", type=int, default=None)
    p.add_argument("--round", type=int, default=None)
    p.add_argument("--progress-pct", type=int, default=None)
    p.add_argument("--destination", choices=list(DESTINATIONS), default=None)
    # Optional gate-or-auto posture for the saga -> deploy edge (issue #395, KTD3). Captured once at
    # /plan Phase 5.1 (only when --destination nonprod-deploy); default=None (not "gate") so an
    # omitted flag carries the prior tick's value forward in _merge instead of restamping it. When
    # absent from the record entirely, deploy_handoff.offer reads the safe `gate` default (R5). There
    # is deliberately NO way to override this posture at deploy_handoff offer time (R2).
    p.add_argument("--deploy-autonomy", choices=["gate", "auto"], default=None)
    # default=None (not "inline") so a save with NO --orchestration-mode leaves the mode at
    # its dataclass default and carries the prior tick's mode/operator_choice forward (see
    # _build_save_saga); only an explicit flag stamps a new orchestration decision.
    p.add_argument("--orchestration-mode", choices=list(ORCHESTRATION_MODES), default=None)
    p.add_argument(
        "--orchestration-recommended",
        choices=list(ORCHESTRATION_MODES),
        default="",
        help="what recommend_execution_backend() suggested (R12; pairs with the chosen mode)",
    )
    p.add_argument(
        "--orchestration-operator-choice",
        choices=list(ORCHESTRATION_MODES),
        default="",
        help="the operator's explicit pick (R12; omit to derive from --orchestration-mode)",
    )
    p.add_argument("--orchestration-ref", default="")
    p.add_argument(
        "--orchestration-run-id",
        default="",
        help=(
            "transient workflow run handle returned by the Workflow tool at launch (#693); "
            "never record it via --orchestration-ref — that field stays the durable spec pointer"
        ),
    )
    p.add_argument(
        "--orchestration-downgrade",
        default="",
        help="one-line capability-portable downgrade note (R11; recorded on off-host resume)",
    )
    p.add_argument("--issue-ref", default="")
    p.add_argument("--next-step", default="")
    p.add_argument("--plan-path", default="")
    p.add_argument(
        "--work-session-paths", default=None, help="pipe-separated; omit = carry forward"
    )
    p.add_argument("--review-paths", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--qa-paths", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument(
        "--artifact-pointers",
        default=None,
        help="pipe-separated typed artifact-pointer JSON blocks; omit = carry forward",
    )
    p.add_argument("--files-modified", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--rounds-seen", default=None, help="pipe-separated ints; omit = carry forward")
    p.add_argument("--pr-refs", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--adr-refs", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--journal-refs", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--open-questions", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument("--checks-run", default=None, help="pipe-separated; omit = carry forward")
    p.add_argument(
        "--gate-verdict",
        action="append",
        default=None,
        metavar="GATE:STATE:REF",
        help="repeatable; each value is 'gate:state:ref' (omit = carry forward)",
    )
    p.add_argument(
        "--gate-divergence",
        action="append",
        default=None,
        metavar="BASE64_JSON",
        help=(
            "repeatable; each value is a base64-wrapped JSON blob "
            "{gate_id, offered, answer, divergence, latency_seconds} "
            "(see encode_gate_divergence_entry; omit = carry forward)"
        ),
    )
    p.add_argument("--blockers", default="")
    p.add_argument("--source", default="")
    p.add_argument("--summary", default="")
    p.add_argument("--decisions", default="")
    p.add_argument("--remaining", default="")
    p.add_argument("--notes", default="")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_save_parser(sub)

    restore_p = sub.add_parser("restore", help="Read the latest tick for a saga")
    restore_p.add_argument("--saga-id", required=True)

    ticks_p = sub.add_parser("ticks", help="Read EVERY tick for a saga (oldest->newest)")
    ticks_p.add_argument("--saga-id", required=True)

    scan_p = sub.add_parser("scan", help="List one candidate per saga (newest first)")
    scan_p.add_argument("--max-candidates", type=int, default=None)

    spec_check_p = sub.add_parser(
        "spec-check",
        help="Validate the saga's spec ref for a workflow launch/resume (#693)",
    )
    spec_check_p.add_argument("--saga-id", required=True)

    ctx_p = sub.add_parser("context", help="Aggregate issue/PR/journal context")
    ctx_p.add_argument("--repo", required=True)
    ctx_p.add_argument("--issue", type=int, required=True)

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    _migrate_legacy_state_dir()
    args = parse_args(argv)
    root = Path.cwd()

    if args.command == "save":
        try:
            incoming, explicit_fields = _build_save_saga(args)
            result = save(root, incoming, explicit_fields=explicit_fields)
        except SagaSaveError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except SagaTickIndexWriteError as exc:
            # The envelope landed BEFORE the index rewrite failed, so the tick EXISTS:
            # ``restore`` reads the envelope directly and never opens state.json. The
            # message must name the failure that actually occurred — never claim the
            # plan lost its tick (review F05/F05u/F05d) and never claim the re-run is
            # idempotent: a save always allocates a fresh envelope, so the re-run
            # appends one additional tick carrying the same state (cycle-2
            # C01/D03/P01/U09).
            message = f"error: failed to rewrite the saga state.json index: {exc}"
            if args.plan_path:
                message += (
                    f" — the plan document {args.plan_path} IS still referenced by the"
                    " tick envelope on disk (restore reads it directly). Once the write"
                    " failure is cleared, re-run the same save: it rebuilds the index"
                    " and appends one additional tick carrying the same state — harmless"
                    " to restore, but visible to saga.py ticks, which then report both."
                )
            print(message, file=sys.stderr)
            return 2
        except SagaTickEnvelopeWriteError as exc:
            # The envelope never reached disk, so THIS save's tick does NOT exist. Name
            # the stranded document only after scanning the full prior chain for the
            # normalized plan path; when any earlier tick records the document, only
            # this tick is missing (issue #923, plan KTD2; cycle-3 defect A2).
            message = f"error: failed to write the saga tick: {exc}"
            if args.plan_path:
                try:
                    prior_ticks = read_ticks(root, incoming.saga_id)
                except (OSError, ValueError, TypeError, KeyError) as read_exc:
                    message += (
                        " — this save's tick envelope was never written, and the prior"
                        f" tick chain could not be inspected ({read_exc}). Check whether"
                        f" it references the plan document {args.plan_path} before"
                        " treating the document as stranded."
                    )
                else:
                    requested_path = _normalized_plan_path(root, args.plan_path)
                    is_tracked = any(
                        tick.plan_path is not None
                        and _normalized_plan_path(root, tick.plan_path) == requested_path
                        for tick in prior_ticks
                    )
                    if is_tracked:
                        message += (
                            " — this save's tick envelope was never written, but an earlier"
                            f" tick still references the plan document {args.plan_path}; the"
                            " document is tracked. Re-run the save to append this tick."
                        )
                    else:
                        message += (
                            f" — the plan document {args.plan_path} now has NO saga tick"
                            " referencing it. Re-run the save before routing onward."
                        )
            print(message, file=sys.stderr)
            return 2
        except OSError as exc:
            # Any other filesystem failure: exit non-zero, but make no claim about
            # whether a tick exists — only the two writes above can say that.
            message = f"error: failed to write the saga tick: {exc}"
            if args.plan_path:
                message += (
                    f" — check whether a tick envelope was written for the plan document"
                    f" {args.plan_path} (saga.py restore) before treating it as stranded."
                )
            print(message, file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "restore":
        saga = restore(root, args.saga_id)
        if saga is None:
            print(json.dumps({"saga_id": args.saga_id, "found": False}, indent=2))
            return 0
        payload = {}
        for f in fields(saga):
            value = getattr(saga, f.name)
            payload[f.name] = _materialize(value) if f.name in _LIST_FIELDS else value
        payload["found"] = True
        # maturity is intentionally NOT emitted here: per saga-spec.md it is DERIVED
        # at /handoff time (via PHASE_TO_MATURITY) and never surfaced by the generic engine.
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "ticks":
        chain = read_ticks(root, args.saga_id)
        ticks = [_tick_snapshot(tick) for tick in chain]
        print(json.dumps({"ticks": ticks, "count": len(ticks)}, indent=2))
        return 0

    if args.command == "scan":
        candidates = scan(root, max_candidates=args.max_candidates)
        print(json.dumps({"candidates": candidates, "count": len(candidates)}, indent=2))
        return 0

    if args.command == "spec-check":
        saga = restore(root, args.saga_id)
        if saga is None:
            print(
                json.dumps(
                    {
                        "saga_id": args.saga_id,
                        "found": False,
                        "verdict": "missing",
                        "detail": f"no saga found for {args.saga_id!r}",
                    },
                    indent=2,
                )
            )
            return 2
        verdict, detail = spec_ref_verdict(saga, root)
        print(
            json.dumps(
                {
                    "saga_id": args.saga_id,
                    "found": True,
                    "verdict": verdict,
                    "detail": detail,
                    "orchestration_run_id": saga.orchestration_run_id,
                },
                indent=2,
            )
        )
        # Anything but ``ok`` is a HALT for /work's ultracode launch/resume (#693): a
        # non-zero exit lets the driving session gate mechanically instead of parsing prose.
        return 0 if verdict == "ok" else 2

    if args.command == "context":
        owner, repo = parse_repo(args.repo)
        print(json.dumps(aggregate_context(root, owner, repo, args.issue), indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
