#!/usr/bin/env python3
"""Resolve one run's review roster by invoking the lifecycle repository's own generator.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT
=============================================

This module turns the lens declaration recorded at admission into a
``review_roster.v1`` document. It does that by **running**
``tools/docs/gen_review_roster.py`` from a checkout of ``infiquetra/infiquetra-sdlc``
(called "the lifecycle repository" throughout) as a subprocess, and carrying the
document it prints through unchanged.

It does **not** reimplement the resolution, and no copy of the generator is
vendored here. That is architecture decision record ADR-001's boundary: the
lifecycle repository owns what a lens means, which lenses exist, what strictness
applies and what threshold must be met; this plugin owns execution and nothing
else. A second implementation of the resolution would be a second policy owner,
whatever its author intended.

Invoking rather than porting is possible because the generator is self-contained:
it imports only the standard library and resolves the catalogue, the quality
profile and the executor-verification ledger relative to its own location. Issue
1001 carried a stop condition — stop if the generator cannot be invoked without
vendoring it — and it does not fire.

THE DECLARATION THIS MODULE BUILDS
==================================

The generator's input is an ``applicability_declaration.v1``. The run record has
no field of that shape: it carries the admission answer
``run_configuration.applicable_lenses``, which names the always-on lenses, the
conditional lenses that apply, and a reason for each conditional lens left out.
:func:`build_declaration` is the one place the two shapes meet, so they can be
compared rather than confused.

FINDING THE LIFECYCLE CHECKOUT
==============================

Through fleet-core's staffing component, whose order is an explicit path, then
``INFIQUETRA_SDLC_PATH``, then ``~/workspace/infiquetra/infiquetra-sdlc``.

**Two environment variables name the same thing in this tree right now.** The
staffing component and mission-control read ``INFIQUETRA_SDLC_PATH``; sixteen role
prompts under ``plugins/agent-launcher/roles/`` say ``INFIQUETRA_SDLC_ROOT``.
Setting one does not set the other, so a review whose controller resolved the
checkout one way would brief lens sessions that resolve it another way or not at
all. ``INFIQUETRA_SDLC_PATH`` wins here because it is the name the *code* reads;
``INFIQUETRA_SDLC_ROOT`` is accepted as a second-priority read so the mismatch
surfaces as a sentence rather than as an empty resolution, and
:func:`resolve_checkout` always reports which of the two it used. Repointing the
role prompts is issue 1022's file, and a follow-up.

WHEN THE CHECKOUT IS ABSENT
===========================

A named refusal, never a fallback roster. A fallback policy is still a policy, and
the whole point of ADR-001 is that this plugin owns none. The deleted
``references/lens-roster.json`` is never resurrected as one.

USAGE
=====

::

    review_roster.py --declaration decl.json
    review_roster.py --issue 1001 --revision <sha>
    review_roster.py --issue 1001 --revision <sha> --sdlc-path /path/to/checkout
    review_roster.py --declaration decl.json --propose

Exit codes: ``0`` the generator's validation report is ``ok``; ``1`` the report is
``refused`` (a run-setup fact the caller must see, not a crash); ``2`` a refusal
this module owns — no checkout, no generator, or a run record with no lens
declaration; ``3`` an unknown run-record version.

``--propose`` prints the advisory conditional-lens proposal for the declaration
and exits ``0`` without resolving a roster: the proposed additions with their
probabilities, the Planner's declaration as the floor, and a note when the
judgment contributed nothing. It needs no lifecycle checkout and leaves the
declaration's lenses intact — the Planner applies additions explicitly, through
:func:`apply_proposal`, before the roster resolves.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess  # nosec B404 — fixed argv, no shell, to a path this module resolves
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import review_consensus  # noqa: E402
import run_record  # noqa: E402

#: The catalogue's four always-on lenses, by way of the one module that names
#: them. No declaration can deselect one, so the proposal never questions one.
ALWAYS_ON_LENS_IDS = review_consensus.ALWAYS_ON_LENS_IDS

#: The schema this module builds for the generator, and the one it expects back.
DECLARATION_SCHEMA = "applicability_declaration.v1"
ROSTER_SCHEMA = "review_roster.v1"

#: The generator's path inside a lifecycle checkout.
GENERATOR_RELATIVE_PATH = Path("tools/docs/gen_review_roster.py")

#: The environment variable the code reads, and the one sixteen role prompts say instead.
#: Both are read; the first wins; whichever was used is reported. See the module docstring.
SDLC_PATH_ENV = "INFIQUETRA_SDLC_PATH"
SDLC_ROOT_ENV = "INFIQUETRA_SDLC_ROOT"
DEFAULT_SDLC_PATH = Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"

EXIT_OK = 0
EXIT_REFUSED_BY_GENERATOR = 1
EXIT_REFUSED = 2
EXIT_UNKNOWN_VERSION = 3


class RosterError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


@dataclass(frozen=True)
class CheckoutResolution:
    """Where the lifecycle checkout came from, and what state it was in.

    ``source`` names which rung resolved — an explicit path, one of the two
    environment variables by name, or the default location — so a reader can tell
    a deliberate override from a lucky default.
    """

    path: Path
    source: str
    head: str = "UNKNOWN"
    policy_dirs_clean: bool | None = None
    other_env_var_set: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "source": self.source,
            "head": self.head,
            "policy_dirs_clean": self.policy_dirs_clean,
            "other_env_var_set": self.other_env_var_set,
        }


@dataclass(frozen=True)
class RosterResolution:
    """One resolved roster, its validation report, and where its policy came from."""

    roster: dict[str, Any]
    validation: dict[str, Any]
    checkout: CheckoutResolution
    declaration: dict[str, Any] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.validation.get("status") != "ok"

    @property
    def roster_hash(self) -> str:
        """The generator's own hash field.

        The field is ``hash``, not ``content_hash``. Issue 1001's Verification
        block says ``jq -r '.schema, .content_hash'``, which prints two nulls
        against the real document: the generator emits ``{"roster": …,
        "validation": …}`` and the roster's hash field is ``hash``. The real name
        is used here and the card's example is corrected rather than a wrapper
        being invented to match it.
        """
        return str(self.roster.get("hash", "UNKNOWN"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "roster": self.roster,
            "validation": self.validation,
            "checkout": self.checkout.to_dict(),
        }


# ---------------------------------------------------------------------------
# Finding the lifecycle checkout
# ---------------------------------------------------------------------------


def _staffing_sdlc_root(explicit: Path | None) -> Path | None:
    """Ask fleet-core's staffing component, when it can be reached.

    Unreachable is not an error: the same resolution order is implemented below,
    so an absent sibling plugin degrades to doing the work here rather than
    refusing a review over a missing import.
    """
    try:
        import bundled_fleet  # noqa: PLC0415

        staffing = bundled_fleet.load("staffing")
    except Exception:  # noqa: BLE001 — any failure means "resolve it here instead"
        return None
    try:
        resolved = staffing.sdlc_root(explicit)
    except Exception:  # noqa: BLE001
        return None
    return Path(resolved) if resolved is not None else None


def _git(checkout: Path, *args: str) -> str | None:
    """Run one read-only git command in *checkout*, or return None if it fails."""
    try:
        completed = subprocess.run(  # nosec B603 B607 — fixed argv, no shell
            ["git", "-C", str(checkout), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _describe_checkout(path: Path, source: str, other_env: str | None) -> CheckoutResolution:
    """Record the checkout's revision and whether its policy directories are clean.

    The generator reads the checkout's *working tree*, not a pinned revision, so
    two runs a day apart can resolve different policy from the same instruction.
    Recording the revision and the clean state makes that visible instead of
    leaving a reader to assume it. A second pin is deliberately not introduced:
    the lifecycle repository's decision C1g makes the run-frozen roster hash the
    sole pinning point.
    """
    head = _git(path, "rev-parse", "HEAD") or "UNKNOWN"
    status = _git(path, "status", "--porcelain", "--", "config", "tools/docs")
    clean = None if status is None else status == ""
    return CheckoutResolution(
        path=path,
        source=source,
        head=head,
        policy_dirs_clean=clean,
        other_env_var_set=other_env,
    )


def resolve_checkout(explicit: Path | None = None) -> CheckoutResolution:
    """Resolve the lifecycle checkout, or raise a named refusal.

    Order: an explicit path, then ``INFIQUETRA_SDLC_PATH``, then
    ``INFIQUETRA_SDLC_ROOT``, then the default location. Every outcome names the
    rung it came from.
    """
    other_env: str | None = None

    if explicit is not None:
        if not explicit.is_dir():
            raise RosterError(
                f"review_roster: the lifecycle checkout {explicit} named on the command line is "
                "not a directory; the review resolves no roster and writes review_incomplete"
            )
        return _describe_checkout(explicit, "explicit path", None)

    configured = os.environ.get(SDLC_PATH_ENV)
    fallback = os.environ.get(SDLC_ROOT_ENV)

    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_dir():
            raise RosterError(
                f"review_roster: {SDLC_PATH_ENV} names {candidate}, which is not a directory; "
                "the review resolves no roster and writes review_incomplete"
            )
        if fallback and Path(fallback).expanduser() != candidate:
            other_env = f"{SDLC_ROOT_ENV}={fallback}"
        return _describe_checkout(candidate, SDLC_PATH_ENV, other_env)

    if fallback:
        candidate = Path(fallback).expanduser()
        if not candidate.is_dir():
            raise RosterError(
                f"review_roster: {SDLC_ROOT_ENV} names {candidate}, which is not a directory; "
                "the review resolves no roster and writes review_incomplete"
            )
        # Read, and said so. The role prompts use this name and the code uses the
        # other; honouring it here keeps a review working while the two are
        # reconciled, and naming it keeps the divergence visible.
        return _describe_checkout(candidate, SDLC_ROOT_ENV, f"{SDLC_PATH_ENV} is unset")

    through_staffing = _staffing_sdlc_root(None)
    if through_staffing is not None and through_staffing.is_dir():
        return _describe_checkout(through_staffing, "staffing component default", None)

    if DEFAULT_SDLC_PATH.is_dir():
        return _describe_checkout(DEFAULT_SDLC_PATH, "default checkout", None)

    raise RosterError(
        f"review_roster: no lifecycle checkout ({SDLC_PATH_ENV} and {SDLC_ROOT_ENV} are both "
        f"unset, and {DEFAULT_SDLC_PATH} is absent); the review resolves no roster and writes "
        "review_incomplete. There is no fallback roster."
    )


def generator_path(checkout: CheckoutResolution) -> Path:
    """The generator inside *checkout*, or a named refusal when it is missing."""
    path = checkout.path / GENERATOR_RELATIVE_PATH
    if not path.is_file():
        raise RosterError(
            f"review_roster: the lifecycle checkout at {checkout.path} (found via "
            f"{checkout.source}) has no {GENERATOR_RELATIVE_PATH}; this plugin invokes that "
            "generator and never reimplements it, so the review resolves no roster and writes "
            "review_incomplete"
        )
    return path


# ---------------------------------------------------------------------------
# Building the declaration the generator consumes
# ---------------------------------------------------------------------------


def _lens_entries(applicable: Any) -> dict[str, dict[str, Any]]:
    """Turn the admission answer into the generator's per-conditional-lens entries.

    The admission answer's shape is the one ``admission.py`` records: an
    ``always_on`` list, a ``conditional_applies`` mapping of lens to the reason it
    applies, and a ``conditional_does_not_apply`` mapping of lens to the reason it
    does not. Always-on lenses are deliberately not emitted: the catalogue selects
    them and no declaration can deselect one.
    """
    if not isinstance(applicable, dict):
        raise RosterError(
            "review_roster: the run record's applicable_lenses is not an object; admission "
            "records the lens declaration and the review never invents one"
        )
    entries: dict[str, dict[str, Any]] = {}
    applies = applicable.get("conditional_applies") or {}
    excluded = applicable.get("conditional_does_not_apply") or {}
    if isinstance(applies, dict):
        for lens in sorted(applies):
            entries[str(lens)] = {"applies": True}
    elif isinstance(applies, list):
        for lens in sorted(str(item) for item in applies):
            entries[lens] = {"applies": True}
    if isinstance(excluded, dict):
        for lens, reason in sorted(excluded.items()):
            entries[str(lens)] = {"applies": False, "reason": str(reason)}
    if not entries:
        raise RosterError(
            "review_roster: the lens declaration names no conditional lens; every conditional "
            "lens either applies or carries a recorded reason, so an empty set is a missing "
            "answer rather than a small one"
        )
    return entries


def build_declaration(
    record: run_record.RunRecord,
    *,
    revision: str,
    work_unit: str | None = None,
    resolved_at: str,
    stack: list[str] | None = None,
) -> dict[str, Any]:
    """Build an ``applicability_declaration.v1`` from the run record.

    ``resolved_at`` is supplied rather than read from the clock, because the
    generator hashes it: a roster that changed with the time of day could not be
    reproduced from its inputs, and reproducing it is the whole point of the hash.
    """
    configuration = record.run_configuration
    applicable = configuration.get("applicable_lenses", {}).get("value")
    if applicable is None:
        raise RosterError(
            "review_roster: the run record has no applicable_lenses; run admission for this "
            "issue first — the review reads the declaration and never invents one"
        )
    staffing = configuration.get("staffing_models_and_efforts", {}).get("value") or {}
    return {
        "schema": DECLARATION_SCHEMA,
        "resolved_at": resolved_at,
        "run": {
            "repository": record.repo,
            "issue": record.issue,
            "revision": revision,
        },
        "work_unit": work_unit or f"issue-{record.issue}",
        "declared_by": "planner",
        "stack": stack or ["python"],
        "standards_resolved": {},
        "lenses": _lens_entries(applicable),
        "executors": _executors_from_staffing(staffing),
        "concurrency_allocation": _concurrency(configuration),
    }


def _executors_from_staffing(staffing: Any) -> dict[str, Any]:
    """Per-lens staffing for the declaration.

    Empty by design today. The lifecycle repository's executor-verification ledger
    has no entries, so naming a scoring executor for a lens can only produce the
    generator's refusal: a scoring executor with no matching ledger entry is
    refused, because an unqualified model producing a number is not evidence.
    Leaving the lenses unstaffed for scoring produces the same honest refusal
    without claiming a qualification nobody ran. When the ledger gains entries,
    this is where the staffing plan is projected into the declaration.
    """
    if not isinstance(staffing, dict):
        return {}
    return {}


def _concurrency(configuration: dict[str, Any]) -> dict[str, Any]:
    allocation = configuration.get("concurrency_allocation", {}).get("value")
    if isinstance(allocation, int) and allocation > 0:
        return {"review": allocation}
    return {}


# ---------------------------------------------------------------------------
# Invoking the generator
# ---------------------------------------------------------------------------


def resolve_roster(
    declaration: dict[str, Any],
    *,
    checkout: CheckoutResolution,
    python: str | None = None,
) -> RosterResolution:
    """Run the generator over *declaration* and return what it printed.

    The document is carried through unchanged. Editing it here would make this
    module a policy owner by the back door.
    """
    generator = generator_path(checkout)
    import tempfile  # noqa: PLC0415 — only needed on this path

    with tempfile.TemporaryDirectory(prefix="review-roster-") as scratch:
        declaration_path = Path(scratch) / "declaration.json"
        declaration_path.write_text(
            json.dumps(declaration, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            completed = subprocess.run(  # nosec B603 — fixed argv, no shell
                [
                    python or sys.executable,
                    str(generator),
                    "--declaration",
                    str(declaration_path),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RosterError(
                f"review_roster: could not run the lifecycle generator at {generator}: {exc}"
            ) from exc

    if not completed.stdout.strip():
        raise RosterError(
            f"review_roster: the lifecycle generator at {generator} printed nothing "
            f"(exit {completed.returncode}); stderr: {completed.stderr.strip()[:400]}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RosterError(
            f"review_roster: the lifecycle generator at {generator} printed output this module "
            f"cannot parse: {exc}"
        ) from exc

    roster = document.get("roster")
    validation = document.get("validation")
    if not isinstance(roster, dict) or not isinstance(validation, dict):
        raise RosterError(
            "review_roster: the lifecycle generator printed a document with no roster or no "
            "validation report; this module refuses rather than guessing at its shape"
        )
    if roster.get("schema") != ROSTER_SCHEMA:
        raise RosterError(
            f"review_roster: the generator produced schema {roster.get('schema')!r}; this saga "
            f"consumes {ROSTER_SCHEMA} and refuses anything else rather than guessing"
        )
    return RosterResolution(
        roster=roster,
        validation=validation,
        checkout=checkout,
        declaration=declaration,
    )


def selected_lenses(roster: dict[str, Any]) -> list[dict[str, Any]]:
    """The roster's lens rows, in catalogue order."""
    lenses = roster.get("lenses")
    return [row for row in lenses if isinstance(row, dict)] if isinstance(lenses, list) else []


# ---------------------------------------------------------------------------
# The conditional-lens proposal (issue 1034)
# ---------------------------------------------------------------------------

#: The probability at or above which an excluded lens is proposed back in.
#: A proposal is shown to the Planner, not executed, so the bar is "the model
#: leans yes" rather than a confidence floor.
PROPOSAL_THRESHOLD = 0.5

#: Mirrors ``typesafe_client.STATUS_OK`` so the injected-``ask`` path interprets
#: answers without importing the client. A one-word string, not behaviour.
_STATUS_OK = "ok"


def _judgment_modules() -> tuple[Any | None, Any | None]:
    """fleet-core's TypeSafe client and verdict log, or ``(None, None)``.

    Unreachable is not an error: the proposal fails open to the Planner's
    declaration, the way an absent staffing component degrades to resolving the
    checkout here rather than refusing the review.
    """
    try:
        import bundled_fleet  # noqa: PLC0415

        return (
            bundled_fleet.load("typesafe_client"),
            bundled_fleet.load("jev_log"),
        )
    except Exception:  # noqa: BLE001 — any failure means "fail open" instead
        return None, None


def declared_applies(declaration: Mapping[str, Any]) -> list[str]:
    """The conditional lenses the declaration already applies, in order."""
    lenses = declaration.get("lenses")
    if not isinstance(lenses, Mapping):
        return []
    return sorted(
        str(lens_id)
        for lens_id, entry in lenses.items()
        if isinstance(entry, Mapping) and entry.get("applies") is True
    )


def proposal_candidates(declaration: Mapping[str, Any]) -> dict[str, str]:
    """The excluded lenses the proposal may question, with the Planner's reason.

    Always-on lenses are never candidates, even when a hand-written declaration
    lists one as excluded: no declaration can deselect one, so there is nothing
    to propose back.
    """
    lenses = declaration.get("lenses")
    if not isinstance(lenses, Mapping):
        return {}
    always_on = set(ALWAYS_ON_LENS_IDS)
    candidates: dict[str, str] = {}
    for lens_id in sorted(lenses):
        if str(lens_id) in always_on:
            continue
        entry = lenses[lens_id]
        if isinstance(entry, Mapping) and entry.get("applies") is False:
            reason = entry.get("reason", "")
            candidates[str(lens_id)] = str(reason or "")
    return candidates


def proposal_state(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """The change shape the proposal judges: the declaration's own account of it.

    The stack, the work unit and the Planner's exclusion reasons are what the
    declaration carries about the change, so they are what the model reads. No
    diff is attached: the proposal answers whether a lens applies to the change
    as declared, not what the diff contains line by line.
    """
    run = declaration.get("run")
    run = run if isinstance(run, Mapping) else {}
    return {
        "change": {
            "repository": str(run.get("repository", "UNKNOWN")),
            "work_unit": str(declaration.get("work_unit", "UNKNOWN")),
            "stack": list(declaration.get("stack", []) or []),
            "declared_by": str(declaration.get("declared_by", "planner")),
        },
        "already_applies": declared_applies(declaration),
        "excluded": proposal_candidates(declaration),
    }


def _proposal_questions(candidates: Mapping[str, str]) -> dict[str, Any]:
    """One yes/no question per candidate lens, keyed by the lens itself."""
    questions: dict[str, Any] = {}
    for lens_id, reason in candidates.items():
        sentence = f"Does the change described by `change` warrant the `{lens_id}` review lens?"
        if reason:
            sentence += f" The Planner excluded it, saying: {reason}"
        questions[lens_id] = {"type": "noul", "instructions": sentence}
    return questions


def _noul_probability(answer: Any) -> float | None:
    """The yes probability of a yes/no answer, or None when there is not one.

    A yes/no answer carries a probability and no confidence field, verified
    against the live endpoint, so the probability is the only number to compare
    against the threshold. Mirrors ``jev_widen`` so this module interprets its
    injected answers without importing the client.
    """
    if not isinstance(answer, Mapping):
        return None
    if answer.get("type") != "noul":
        return None
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _record_proposal(
    *,
    state: Mapping[str, Any],
    questions: Mapping[str, Any],
    answers: Mapping[str, Any],
    threshold: float,
    model: str,
    log_dir: Any,
) -> None:
    """Log one verdict per answered lens. Best-effort by design.

    An unwritable log directory is a problem with the fleet's measurement, not
    with the proposal the caller asked for, and the proposal has already been
    computed by the time this runs.
    """
    client, log = _judgment_modules()
    if client is None or log is None:
        return
    for lens_id, answer in answers.items():
        if not isinstance(answer, Mapping):
            continue
        try:
            log.record_verdict(
                decision_id=f"code-review:propose-lenses:{lens_id}",
                state=state,
                questions=questions,
                answer=dict(answer),
                confidence=client.answer_confidence(answer),
                threshold=threshold,
                resolved_model=model,
                directory=log_dir,
            )
        except Exception:  # noqa: BLE001 — see the docstring
            return


def propose_lenses(
    declaration: Mapping[str, Any],
    *,
    ask: Callable[..., Any] | None = None,
    threshold: float = PROPOSAL_THRESHOLD,
    log: bool = True,
    log_dir: Any = None,
) -> dict[str, Any]:
    """Propose excluded conditional lenses that may apply after all.

    Advisory and additive only. The Planner's declaration is the floor: every
    lens it applies stays applied, and the proposal can only name additions
    from the excluded set. On any failure — no client, no key, a timeout, a
    malformed body — the additions are empty and the note names the reason, so
    a caller that ignores the note behaves as it did before this existed.

    ``ask`` is the injection seam: tests hand in a fake and cannot reach the
    network even by accident.
    """
    applies = declared_applies(declaration)
    candidates = proposal_candidates(declaration)
    lenses = declaration.get("lenses")
    named = set(lenses) if isinstance(lenses, Mapping) else set()
    skipped_always_on = sorted(named & set(ALWAYS_ON_LENS_IDS))
    base: dict[str, Any] = {
        "judgment": "conditional-lens-proposal",
        "advisory": True,
        "threshold": threshold,
        "declared_applies": applies,
        "candidates": sorted(candidates),
        "skipped_always_on": skipped_always_on,
    }

    def _floor(ok: bool, note: str) -> dict[str, Any]:
        return {
            **base,
            "ok": ok,
            "note": note,
            "model": "",
            "probabilities": {},
            "proposed_additions": [],
            "proposed_lenses": list(applies),
        }

    if not isinstance(lenses, Mapping) or not lenses:
        return _floor(False, "the declaration names no conditional lens; nothing was asked")
    if not candidates:
        return _floor(True, "every declared conditional lens already applies; nothing was asked")

    state = proposal_state(declaration)
    questions = _proposal_questions(candidates)

    caller = ask
    if caller is None:
        client, _ = _judgment_modules()
        if client is None:
            return _floor(
                False,
                "fleet-core's TypeSafe client is unreachable; "
                "the Planner's declaration stands unchanged",
            )
        caller = client.ask

    try:
        result = caller(state, questions)
    except Exception as exc:  # noqa: BLE001 — the floor must survive any failure
        return _floor(False, f"the request raised {type(exc).__name__}")

    if getattr(result, "status", None) != _STATUS_OK:
        note = getattr(result, "note", "") or "the request failed"
        return _floor(False, note)

    answers = getattr(result, "answers", None) or {}
    model = str(getattr(result, "model", "") or "")
    probabilities: dict[str, float | None] = {}
    missing: list[str] = []
    for lens_id in candidates:
        probability = _noul_probability(answers.get(lens_id))
        probabilities[lens_id] = probability
        if probability is None and lens_id not in answers:
            missing.append(lens_id)
    additions = sorted(
        lens_id
        for lens_id, probability in probabilities.items()
        if probability is not None and probability >= threshold
    )

    if log:
        _record_proposal(
            state=state,
            questions=questions,
            answers=answers,
            threshold=threshold,
            model=model,
            log_dir=log_dir,
        )

    note = ""
    if missing:
        note = f"the answer carried no verdict for {', '.join(missing)}"
    return {
        **base,
        "ok": True,
        "note": note,
        "model": model,
        "probabilities": probabilities,
        "proposed_additions": additions,
        "proposed_lenses": sorted([*applies, *additions]),
    }


def apply_proposal(declaration: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    """A new declaration with the proposed additions flipped to applies.

    The input is never mutated. Only lenses the proposal names *and* the
    declaration excludes are touched; every other entry is carried over
    unchanged, so this can only add, never remove. The Planner applies it
    explicitly, before the roster resolves — the command line never does.
    """
    additions = set(proposal.get("proposed_additions", []) or [])
    lenses = declaration.get("lenses")
    lenses = lenses if isinstance(lenses, Mapping) else {}
    applied: dict[str, Any] = {}
    for lens_id, entry in lenses.items():
        if (
            str(lens_id) in additions
            and isinstance(entry, Mapping)
            and entry.get("applies") is False
        ):
            applied[lens_id] = {"applies": True}
        else:
            applied[lens_id] = copy.deepcopy(entry)
    return {**declaration, "lenses": applied}


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve a review roster by invoking the lifecycle repository's generator."
    )
    parser.add_argument("--declaration", type=Path, help="An applicability_declaration.v1 file.")
    parser.add_argument("--issue", type=int, help="Build the declaration from this issue's record.")
    parser.add_argument("--revision", default=None, help="The revision under review.")
    parser.add_argument("--work-unit", default=None, help="The work unit this review covers.")
    parser.add_argument(
        "--resolved-at",
        default="1970-01-01T00:00:00Z",
        help="The setup timestamp recorded in the declaration; never read from the clock.",
    )
    parser.add_argument("--sdlc-path", type=Path, default=None, help="The lifecycle checkout.")
    parser.add_argument("--store-root", type=Path, default=None, help="Run-record store override.")
    parser.add_argument(
        "--print-declaration",
        action="store_true",
        help="Also print the declaration that was built.",
    )
    parser.add_argument(
        "--propose",
        action="store_true",
        help=(
            "Print the advisory conditional-lens proposal for the declaration "
            "and exit without resolving a roster. The declaration's lenses are "
            "left intact; the Planner applies additions explicitly."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=PROPOSAL_THRESHOLD,
        help=(
            "The probability at or above which --propose names an excluded lens "
            f"(default {PROPOSAL_THRESHOLD})."
        ),
    )
    return parser


def _load_declaration(args: argparse.Namespace) -> dict[str, Any]:
    """The declaration from a file, or built from the issue's run record."""
    if args.declaration is not None:
        payload = json.loads(args.declaration.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RosterError("review_roster: the declaration file does not hold a JSON object")
        return payload
    store_root = (
        Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
    )
    record = run_record.load(store_root, args.issue, warn=None)
    if record is None:
        raise RosterError(
            f"review_roster: no run record for issue {args.issue} under {store_root}; "
            "run admission for this issue first"
        )
    return build_declaration(
        record,
        revision=args.revision or "UNKNOWN",
        work_unit=args.work_unit,
        resolved_at=args.resolved_at,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.declaration is None and args.issue is None:
        parser.error("one of --declaration or --issue is required")

    if args.propose:
        # The proposal needs no lifecycle checkout: it judges the declaration,
        # not the catalogue, and the declaration is already in hand.
        try:
            declaration = _load_declaration(args)
        except run_record.UnknownRecordVersionError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_UNKNOWN_VERSION
        except RosterError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_REFUSED
        except (OSError, json.JSONDecodeError) as exc:
            print(f"review_roster: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        print(
            json.dumps(
                propose_lenses(declaration, threshold=args.threshold),
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK

    try:
        checkout = resolve_checkout(args.sdlc_path)
        declaration = _load_declaration(args)
        resolution = resolve_roster(declaration, checkout=checkout)
    except run_record.UnknownRecordVersionError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except RosterError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED
    except (OSError, json.JSONDecodeError) as exc:
        print(f"review_roster: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    payload = resolution.to_dict()
    if args.print_declaration:
        payload["declaration"] = resolution.declaration
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_REFUSED_BY_GENERATOR if resolution.refused else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
