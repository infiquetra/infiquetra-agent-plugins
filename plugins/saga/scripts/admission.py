#!/usr/bin/env python3
"""The admission questionnaire — asked once, at the front of a run (issue #1023).

The software-development-lifecycle repository already enumerates what has to be settled before
work starts: the card contract, the Risk tier, the seven approval boundaries, the six issue-review
checks, and thirteen run-configuration parameters. Nothing implemented any of it, so the operator
answered those questions by hand, in prose, every time. This module implements it:

1. Run the card validator. A card that fails stops the step, names the missing fields, and writes
   nothing — planning against a half-formed card is the failure the lifecycle repository's Shaping
   exit exists to prevent.
2. Fill every defaultable run-configuration parameter from the per-repository profile, the
   lifecycle repository's decided defaults, and fleet-core's staffing component, recording where
   each value came from.
3. Print the questions that remain — and only those. An answer already in the run record is never
   asked again.

**This module never prompts.** It emits a question set and consumes an answers file (plan KTD6).
Putting the one message to the operator is the ``/plan`` skill's job, because the skill is what has
a conversation; keeping interactive input out of here is what makes "the operator is asked exactly
once" a property a test can check rather than something a human has to observe.

It writes one file besides the run record (issue #97): when the operator answers the
functional-test environment question, the answer is written to the tracked ``.saga-profile.json``
under ``--repo-root``, so the next run in that repository is not asked again. ``--dry-run`` writes
neither.

Exit codes are the run record's (see ``references/run-record.md``): 0 success, 2 a refusal —
including a card that fails the validator — and 3 an unknown record version.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import functional_environment  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402  (after the sys.path shim, by design)

#: The tracked per-repository profile. Tracked, at the repository root, because `.saga/` is
#: git-ignored here and a profile a fresh worktree cannot see would make admission re-ask questions
#: that are already answered — see ``references/repository-profile.md``.
PROFILE_FILENAME = ".saga-profile.json"

MISSION_CONTROL_PLUGIN = "mission-control"
MISSION_CONTROL_MARKERS = (
    ".claude-plugin/plugin.json",
    "scripts/sdlc_manager.py",
)
MISSION_CONTROL_ENV_VAR = "INFIQUETRA_MISSION_CONTROL_PATH"

#: The lifecycle repository's decided defaults, at revision 5efc869f. Five parameters whose value
#: the lifecycle settled once for everyone, so no run is asked for them.
LIFECYCLE_DEFAULTS: dict[str, Any] = {
    "standard_cycle_allowance": 3,
    "escalated_cycle_allowance": 2,
    "escalation_trigger": (
        "exhausting the standard-tier allowance without every selected lens meeting its "
        "acceptance, or two consecutive standard cycles with no progress on the same "
        "below-threshold lens"
    ),
    "lens_execution_recovery": (
        "two backoff retries on the same verified executor, after 30 seconds and then 120 "
        "seconds, then one substitution to a pre-declared verified fallback; none consumes a "
        "review cycle"
    ),
    "repair_custody": "repairs go to dedicated repair roles chosen up front",
}

#: Which profile key fills which parameter.
PROFILE_PARAMETERS: dict[str, str] = {
    "concurrency_allocation": "concurrency_allocation",
    "nonproduction_destination": "nonproduction_destination",
    "mechanical_tool_baseline": "mechanical_tool_baseline",
    "preflight_checks": "preflight_checks",
}

#: The admission answers a profile settles as they stand, because they are facts about a repository
#: rather than choices about a run. The functional-test environment is the other repository fact;
#: it is checked before it is used, so it is read through ``functional_environment`` instead.
PROFILE_ADMISSION_ANSWERS: tuple[str, ...] = ("main_consumed_directly",)

#: The functional-test environment question's key, which is also where admission records the
#: resolved declaration or waiver (``admission.functional_test_environment``).
FUNCTIONAL_TEST_KEY = functional_environment.PROFILE_KEY

#: The answers-file key for a repository-level waiver: the alternative to the environment block.
FUNCTIONAL_TEST_WAIVER_KEY = functional_environment.WAIVER_KEY

#: The lens catalogue supplies these two; the staffing component reads the catalogue, so they are
#: filled from the same call that fills staffing.
CATALOGUE_PARAMETERS: tuple[str, ...] = ("applicable_lenses", "per_lens_score_threshold")


@dataclass(frozen=True)
class Question:
    """One question admission may put to the operator, exactly once."""

    key: str
    prompt: str
    default: Any = None


#: The ten questions the card names as not defaultable, in the order they are asked. Two of them —
#: the two repository facts — drop out when a profile answers them.
QUESTIONS: tuple[Question, ...] = (
    Question("risk_tier", "Risk tier (low, medium, high, very-high) and one sentence saying why"),
    Question(
        "approval_scope",
        "For each of the seven approval boundaries, the scope granted, or 'none': "
        + "; ".join(run_record.APPROVAL_CATEGORIES),
    ),
    Question("destination", "Destination: plan-only, pr, merge, or nonprod-deploy"),
    Question(
        "staffing_overrides", "Any staffing override, per role, or 'none' to take the defaults"
    ),
    Question(
        "lens_declaration",
        "The lens declaration: the four always-on lenses plus the conditional ones that apply, "
        "with a reason for each conditional lens left out",
    ),
    Question(
        "repair_allowances",
        "Repair allowances: 3 standard cycles and 2 escalated unless you lower them",
        default={"standard": 3, "escalated": 2},
    ),
    Question(
        "unfinished_testing_response",
        "When prescribed functional testing cannot finish: bring the result to the operator, or "
        "continue repair toward the prescribed tests",
    ),
    Question(
        FUNCTIONAL_TEST_KEY,
        "How is a change in this repository functionally tested before code review? Name the "
        "kind: local (built and started on this host), emulator (a local emulation of its cloud "
        "services, such as LocalStack), ephemeral-stack (a stack created for the branch alone) or "
        "shared-nonprod (the shared non-production stack). Give the deploy-or-start command "
        "(optional for local), the test command that runs the functional suite (required), an "
        "optional teardown command, and whether the environment is private or shared "
        "(shared-nonprod is always shared). Or give a reason to waive functional testing for the "
        "whole repository, for example documentation only. The answer is written to "
        ".saga-profile.json, so it is asked once per repository",
    ),
    Question("main_consumed_directly", "Is this repository's main branch consumed directly?"),
    Question("change_shape", "Is this change code, docs, or mixed?"),
)


class AdmissionError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


class CardNotReadyError(AdmissionError):
    """The issue's card failed the validator. Exit 2, with the missing fields named."""


# ---------------------------------------------------------------------------
# Reaching the siblings: the card validator and the staffing component
# ---------------------------------------------------------------------------


def _mission_control_root() -> Path:
    """Locate the mission-control plugin through the shared resolution ladder (plan KTD7).

    Never a path guess. ``<repo_root>/plugins/mission-control/`` is correct only inside this
    monorepo, which is why ``board_progression.py`` already resolves it this way.
    """
    import bundled_fleet  # noqa: PLC0415

    try:
        resolution = bundled_fleet.load("plugin_resolution")
    except RuntimeError as exc:
        raise AdmissionError(
            f"the resolved fleet-core cannot provide plugin_resolution ({exc}); the card validator "
            "cannot be reached, and admission never skips validation"
        ) from exc
    try:
        root, _rung = resolution.resolve_plugin_root(
            MISSION_CONTROL_PLUGIN,
            markers=MISSION_CONTROL_MARKERS,
            env_var=MISSION_CONTROL_ENV_VAR,
        )
    except RuntimeError as exc:
        raise AdmissionError(f"the mission-control plugin could not be located: {exc}") from exc
    return root


def load_card_validator() -> Callable[[str], tuple[bool, list[str]]]:
    """Return mission-control's ``validate_card_body``."""
    path = _mission_control_root() / "scripts" / "sdlc_manager.py"
    spec = importlib.util.spec_from_file_location("sdlc_manager", path)
    if spec is None or spec.loader is None:
        raise AdmissionError(f"could not load the card validator from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sdlc_manager"] = module
    spec.loader.exec_module(module)
    return module.validate_card_body


def load_staffing() -> Any:
    """Return fleet-core's staffing component, or ``None`` when it cannot be reached.

    Unlike the validator, staffing is not a gate: a run whose staffing cannot be resolved still has
    a question to ask about it, so an unreachable component degrades to "ask" rather than refusing.
    """
    try:
        import bundled_fleet  # noqa: PLC0415

        return bundled_fleet.load("staffing")
    except Exception:
        return None


def fetch_issue(
    issue: int,
    repo: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Read the issue with ``gh``. Raises :class:`AdmissionError` when it cannot be read."""
    result = runner(  # nosec B603 — fixed argv, no shell
        ["gh", "issue", "view", str(issue), "--repo", repo, "--json", "title,body,number"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if getattr(result, "returncode", 1) != 0:
        raise AdmissionError(
            f"could not read {repo}#{issue}: {(getattr(result, 'stderr', '') or '').strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AdmissionError(
            f"gh returned output that is not JSON for {repo}#{issue}: {exc}"
        ) from exc


def default_repo(start: Path | None = None, *, runner: Callable[..., Any] = subprocess.run) -> str:
    """Return ``owner/name`` from the checkout's ``origin`` remote, or the empty string."""
    try:
        result = runner(  # nosec B603 — fixed argv, no shell
            ["git", "remote", "get-url", "origin"],
            cwd=str(start or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return ""
    if getattr(result, "returncode", 1) != 0:
        return ""
    url = (result.stdout or "").strip().removesuffix(".git")
    if ":" in url and "//" not in url:
        url = url.split(":", 1)[1]
    parts = [part for part in url.split("/") if part]
    return "/".join(parts[-2:]) if len(parts) >= 2 else ""


def load_profile(repo_root: Path) -> dict[str, Any]:
    """Read ``.saga-profile.json`` from *repo_root*; an absent profile is an empty one."""
    path = Path(repo_root) / PROFILE_FILENAME
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdmissionError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise AdmissionError(f"{path} does not hold a JSON object")
    return loaded


# ---------------------------------------------------------------------------
# Filling and asking
# ---------------------------------------------------------------------------


def _fill(configuration: dict[str, Any], name: str, value: Any, source: str) -> None:
    configuration[name]["value"] = value
    configuration[name]["source"] = source


def fill_defaults(
    record: run_record.RunRecord,
    profile: dict[str, Any],
    staffing: Any = None,
    *,
    suggest: bool = False,
    suggest_ask: Callable[..., Any] | None = None,
    suggest_log_dir: Path | None = None,
    repo_root: Path | None = None,
) -> run_record.RunRecord:
    """Fill every defaultable parameter, recording where each value came from (plan R7).

    Never overwrites a value already carrying an ``operator`` source: an answer the operator gave
    outranks any default, and re-deriving it would be the re-asking this whole module exists to
    stop.

    ``suggest`` asks the staffing component for one batched tier suggestion per role and records
    each beside its default. Advisory and fail-open: a suggestion never changes a value, and a
    component without a consult entry point — or a failed request — leaves the defaults exactly
    as they would have been.

    ``repo_root`` is the checkout whose repository tier overlay staffing reads; ``None`` reads it
    from the working directory.
    """
    configuration = {name: dict(block) for name, block in record.run_configuration.items()}
    admission = json.loads(json.dumps(record.admission))

    for name, value in LIFECYCLE_DEFAULTS.items():
        if configuration[name]["source"] != "operator":
            _fill(configuration, name, value, "lifecycle-default")

    for parameter, profile_key in PROFILE_PARAMETERS.items():
        if profile_key in profile and configuration[parameter]["source"] != "operator":
            _fill(configuration, parameter, profile[profile_key], "profile")

    for answer in PROFILE_ADMISSION_ANSWERS:
        if answer in profile and admission.get(answer) is None:
            admission[answer] = profile[answer]
            admission.setdefault("answers", {})[answer] = {
                "value": profile[answer],
                "source": "profile",
            }

    if not _environment_answered(admission):
        try:
            resolved = functional_environment.resolve(profile)
        except functional_environment.DeclarationError as exc:
            raise AdmissionError(f"{PROFILE_FILENAME}: {exc}") from exc
        if resolved is not None:
            # An incomplete (legacy branch_preview) declaration is recorded too, so the question
            # can offer it as the default; only a declared or waived one answers the question.
            admission[FUNCTIONAL_TEST_KEY] = resolved
            if resolved["mode"] in functional_environment.ANSWERED_MODES:
                key, value = functional_environment.profile_entry(resolved)
                admission.setdefault("answers", {})[FUNCTIONAL_TEST_KEY] = {
                    "value": {key: value} if key != FUNCTIONAL_TEST_KEY else value,
                    "source": "profile",
                }

    if (
        staffing is not None
        and configuration["staffing_models_and_efforts"]["source"] != "operator"
    ):
        resolved = _resolve_staffing(
            staffing,
            root=repo_root,
            recorded=configuration["staffing_models_and_efforts"].get("value"),
            suggest=suggest,
            suggest_ask=suggest_ask,
            suggest_log_dir=suggest_log_dir,
        )
        if resolved is not None:
            _fill(configuration, "staffing_models_and_efforts", resolved, "staffing")
            catalogue = _resolve_catalogue(staffing)
            for parameter in CATALOGUE_PARAMETERS:
                # The operator guard every other fill site applies, and that this
                # function's own docstring promises. It was missing here and could
                # not be observed: `_resolve_catalogue` returned an empty mapping for
                # every checkout because of the shape defect above, so this loop never
                # filled anything. Repairing the read made the clobber reachable — a
                # re-run of admission replaced an operator's lens declaration with the
                # catalogue's always-on proposal, discarding the conditional lenses and
                # their recorded reasons.
                if (
                    catalogue.get(parameter) is not None
                    and configuration[parameter]["source"] != "operator"
                ):
                    _fill(configuration, parameter, catalogue[parameter], "staffing")

    return run_record.RunRecord(
        **{**record.__dict__, "run_configuration": configuration, "admission": admission}
    )


def _resolve_staffing(
    staffing: Any,
    *,
    root: Path | None = None,
    recorded: Any = None,
    suggest: bool = False,
    suggest_ask: Callable[..., Any] | None = None,
    suggest_log_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Ask the staffing component for each role's vendor, model and effort.

    The staffing component owns the tier precedence; this function restates none of it. It hands
    over the repository root for the overlay and, for each role, any ``jev_raise`` already
    recorded on that role's entry in ``recorded`` (the previous staffing value), and keeps that
    raise on the entry it returns so a re-run does not drop it. A raise the resolver refuses is
    kept too, beside a ``jev_raise_refused`` message, and the role falls back to its default; any
    other refusal stops admission (see :func:`_resolve_one_role`).

    With ``suggest``, one batched tier consult covers every resolved role, and each role's
    suggestion is recorded beside its default. The consult is best-effort: a component without
    the consult entry point, or a request that fails, leaves the defaults untouched.
    """
    try:
        roles = staffing.roles()
    except Exception:
        return None
    resolved: dict[str, Any] = {}
    operator_set: dict[str, bool] = {}
    previous = recorded if isinstance(recorded, dict) else {}
    for role in sorted(roles):
        entry = previous.get(role)
        jev_raise = entry.get("jev_raise") if isinstance(entry, dict) else None
        decision, refused = _resolve_one_role(staffing, role, root=root, jev_raise=jev_raise)
        if decision is None:
            continue
        resolved[role] = {
            "vendor": getattr(decision, "vendor", None),
            "model": getattr(decision, "model", None),
            "effort": getattr(decision, "effort", None),
            "source": getattr(decision, "source", None),
        }
        if jev_raise is not None:
            resolved[role]["jev_raise"] = jev_raise
        if refused is not None:
            resolved[role]["jev_raise_refused"] = refused
        operator_set[role] = getattr(decision, "source", "policy") == "overlay"
    if suggest and resolved:
        _attach_suggestions(staffing, resolved, operator_set, suggest_ask, suggest_log_dir)
    return resolved or None


def _is_refusal(staffing: Any, exc: Exception) -> bool:
    """Whether ``exc`` is the staffing resolver refusing an input, not a missing component."""
    refusal = getattr(staffing, "StaffingError", None)
    return isinstance(refusal, type) and isinstance(exc, refusal)


def _resolve_one_role(
    staffing: Any, role: str, *, root: Path | None, jev_raise: Any
) -> tuple[Any, str | None]:
    """Resolve one role, failing loud on every refusal except the known lens-reviewer skip.

    Returns ``(decision, refused)``. ``decision`` is None only for a role admission cannot staff
    without a lens (the lens reviewer), or for a staffing component that is missing or too old to
    take these arguments, which stays fail-open as before.

    A recorded ``jev_raise`` the resolver refuses (a lowering, a two-step jump, a raise to the
    strongest model or off the palette) does not drop the role: the role resolves without the
    raise, and ``refused`` carries the resolver's message so the record shows the refusal beside
    the raise it kept. Any other refusal, such as a Claude-only work shape on a role pinned to
    another vendor, raises :class:`AdmissionError` naming the role; the raise is named there only
    when the resolver refused it with a message of its own, so a refusal the raise did not cause
    is never blamed on it.
    """
    try:
        return staffing.resolve_role(role, root=root, jev_raise=jev_raise), None
    except Exception as exc:
        if not _is_refusal(staffing, exc):
            return None, None
        first = exc
    refused: str | None = None
    if jev_raise is not None:
        try:
            return staffing.resolve_role(role, root=root), str(first)
        except Exception as exc:
            if not _is_refusal(staffing, exc):
                return None, None
            # Dropping the raise did not clear the refusal, so the raise was not its cause. Name
            # it only when it was refused for a reason of its own, never by repeating the message.
            if str(exc) != str(first):
                refused = str(first)
            first = exc
    try:
        staffing.resolve_role(role, root=root, require_lens=False)
    except Exception as exc:
        if not _is_refusal(staffing, exc):
            return None, None
        reason = f"; its recorded raise was also refused: {refused}" if refused else ""
        raise AdmissionError(f"staffing refused role {role!r}: {first}{reason}") from first
    # Only the lens requirement stood in the way: the lens reviewer is staffed per lens later.
    return None, None


def _attach_suggestions(
    staffing: Any,
    resolved: dict[str, Any],
    operator_set: dict[str, bool],
    suggest_ask: Callable[..., Any] | None,
    suggest_log_dir: Path | None,
) -> None:
    """Consult the tier judgment once for every role and record each suggestion beside its
    default. Never raises and never alters a default: anything unexpected leaves ``resolved``
    exactly as it was."""
    consult = getattr(staffing, "consult_tier_suggestions", None)
    if not callable(consult):
        return
    units = {
        role: {
            "task": (f"role '{role}' (staffing default {tier.get('model')}/{tier.get('effort')})"),
            "default": {"model": tier.get("model"), "effort": tier.get("effort")},
            "operator_set": operator_set.get(role, False),
        }
        for role, tier in resolved.items()
    }
    try:
        outcome = consult(units, ask=suggest_ask, log_dir=suggest_log_dir)
    except Exception:
        return
    if not isinstance(outcome, dict):
        return
    entries = outcome.get("suggestions") or {}
    if not isinstance(entries, dict):
        return
    for role, entry in entries.items():
        if role not in resolved or not isinstance(entry, dict):
            continue
        suggested = entry.get("suggested")
        resolved[role]["suggestion"] = {
            "suggested": (
                f"{suggested.get('model')}/{suggested.get('effort')}"
                if isinstance(suggested, dict)
                else None
            ),
            "confidence": entry.get("confidence"),
            "floor": entry.get("floor"),
            "low_confidence": entry.get("low_confidence", False),
            "usable": entry.get("usable", False),
            "problem": entry.get("problem"),
            "reason": entry.get("reason", ""),
        }


def _resolve_catalogue(staffing: Any) -> dict[str, Any]:
    """Read the always-on lens names and the threshold ladder through the staffing component.

    ``staffing.lens_catalogue()`` returns a **pair**: a mapping keyed by lens
    identifier, and the catalogue's version string. It does not return the
    catalogue document, so the mapping has no ``lenses`` key and no
    ``strictness_ladder`` key — reading those off it yields ``None`` for every
    checkout, which is how ``per_lens_score_threshold`` came to be unfillable by
    any path. Issue 1023 owns ``lens_catalogue``; this is the consumer's half of
    the repair, and ``tests/test_admission.py`` pins the real function's shape
    rather than a fake's.

    The ladder is not in that return value at all, so it is read from the same
    checkout the staffing component resolves, through that component's own public
    ``sdlc_root``. Resolving the path here independently would put a second copy
    of the resolution order in the tree, which is the thing that made the two
    environment-variable names diverge in the first place.
    """
    try:
        catalogue, _version = staffing.lens_catalogue()
    except Exception:
        return {}
    if not isinstance(catalogue, dict):
        return {}

    # The mapping is {lens identifier: catalogue entry}. A lens identifier is the
    # key, never an entry's "name" field, which carries the human-readable title.
    always_on = sorted(
        str(lens_id)
        for lens_id, row in catalogue.items()
        if isinstance(row, dict) and row.get("always_on")
    )

    result: dict[str, Any] = {}
    if always_on:
        result["applicable_lenses"] = {"always_on": always_on, "conditional": "proposed at review"}

    ladder = _resolve_strictness_ladder(staffing)
    if ladder is not None:
        result["per_lens_score_threshold"] = ladder
    return result


def _resolve_strictness_ladder(staffing: Any) -> Any | None:
    """The catalogue's strictness ladder, or ``None`` when the checkout is unreadable.

    Absent is a fact about the machine, not an error: an unfilled parameter leaves
    a question to ask, and a missing sibling repository must not stop admission.
    """
    try:
        checkout = staffing.sdlc_root()
    except Exception:
        return None
    if checkout is None:
        return None
    path = Path(checkout) / "config" / "lens-catalogue.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    ladder = document.get("strictness_ladder")
    return ladder if ladder is not None else None


def _environment_answered(admission: dict[str, Any]) -> bool:
    """Is a declared environment or a waiver recorded? An incomplete migration is not an answer."""
    recorded = admission.get(FUNCTIONAL_TEST_KEY)
    return (
        isinstance(recorded, dict) and recorded.get("mode") in functional_environment.ANSWERED_MODES
    )


def _is_answered(record: run_record.RunRecord, key: str) -> bool:
    """Has *key* already been answered? Used to decide what NOT to ask (plan R9)."""
    admission = record.admission
    if key == FUNCTIONAL_TEST_KEY:
        return _environment_answered(admission)
    if key in admission.get("answers", {}):
        return True
    if key in admission and admission[key] is not None:
        return True
    if key == "approval_scope":
        return all(value is not None for value in record.approval_scope.values())
    if key == "unfinished_testing_response":
        return record.run_configuration[key]["source"] == "operator"
    return False


def outstanding_questions(record: run_record.RunRecord) -> list[Question]:
    """The questions still to put to the operator, in order. Empty means nothing is outstanding.

    A profile migrated from the legacy ``branch_preview`` keys is incomplete, so the
    functional-test question is still asked, with the migrated values as its default: the operator
    confirms or changes them, and the plugin chooses nothing (parent ruling 2).
    """
    outstanding: list[Question] = []
    for question in QUESTIONS:
        if _is_answered(record, question.key):
            continue
        if question.key == FUNCTIONAL_TEST_KEY:
            migrated = record.admission.get(FUNCTIONAL_TEST_KEY)
            if isinstance(migrated, dict) and migrated.get("mode") == "incomplete":
                default = {
                    field: migrated[field]
                    for field in functional_environment.FIELDS
                    if migrated.get(field) is not None
                }
                question = replace(question, default=default)
        outstanding.append(question)
    return outstanding


#: The vendor the tier palette staffs. A run is Claude-only (issue #90, ruling 5), so an override
#: names it or the role's own default vendor, never another.
PALETTE_VENDOR = "claude"

#: The keys one staffing-override row may carry.
_OVERRIDE_KEYS: tuple[str, ...] = ("vendor", "model", "effort")

#: The keys a lens declaration may carry: the shape ``review_roster._lens_entries`` reads.
_DECLARATION_KEYS: tuple[str, ...] = (
    "always_on",
    "conditional_applies",
    "conditional_does_not_apply",
)


def _no_override(value: Any) -> bool:
    """``none``, null and an empty mapping all mean "take the defaults"."""
    return value is None or value == "none" or value == {}


def _load_tier_palette() -> Any:
    import bundled_fleet  # noqa: PLC0415

    try:
        return bundled_fleet.load("tier_palette")
    except Exception as exc:
        raise AdmissionError(
            f"the tier palette could not be loaded ({exc}), so a staffing override cannot be "
            "checked; admission never records an unchecked tier"
        ) from exc


def _known_roles(record: run_record.RunRecord, staffing: Any) -> set[str] | None:
    """The roles a run staffs: the staffing component's, else the recorded map's, else unknown."""
    roles: Any = None
    if staffing is not None:
        try:
            roles = staffing.roles()
        except Exception:
            roles = None
    if roles:
        return {str(role) for role in roles}
    value = record.run_configuration["staffing_models_and_efforts"].get("value")
    if isinstance(value, dict):
        roles = {str(role) for role in value if not str(role).startswith("_")}
        if roles:
            return roles
    return None


def _default_vendor(record: run_record.RunRecord, staffing: Any, role: str) -> str:
    """The vendor *role* is staffed with: a fresh resolve, else the recorded row, else Claude."""
    if staffing is not None:
        try:
            vendor = getattr(staffing.resolve_role(role), "vendor", None)
        except Exception:
            vendor = None
        if vendor:
            return str(vendor)
    value = record.run_configuration["staffing_models_and_efforts"].get("value")
    row = value.get(role) if isinstance(value, dict) else None
    if isinstance(row, dict) and row.get("vendor"):
        return str(row["vendor"])
    return PALETTE_VENDOR


def validate_staffing_overrides(
    value: Any, record: run_record.RunRecord, staffing: Any = None
) -> None:
    """Refuse a staffing override the run could not staff (issue #103).

    Every row must name a role the run staffs, that role's own vendor, and a model and effort the
    tier palette lists together. Raises :class:`AdmissionError` naming the first problem.
    """
    if _no_override(value):
        return
    if not isinstance(value, dict):
        raise AdmissionError(
            "staffing_overrides must be 'none' or a mapping of role to {vendor, model, effort}"
        )
    palette = _load_tier_palette()
    roles = _known_roles(record, staffing)
    for role, row in value.items():
        role = str(role)
        if roles is not None and role not in roles:
            raise AdmissionError(
                f"staffing_overrides names an unknown role {role!r}; the run staffs "
                + ", ".join(sorted(roles))
            )
        if not isinstance(row, dict):
            raise AdmissionError(
                f"staffing_overrides[{role!r}] must be an object of {', '.join(_OVERRIDE_KEYS)}"
            )
        missing = [key for key in _OVERRIDE_KEYS if not row.get(key)]
        extra = sorted(set(row) - set(_OVERRIDE_KEYS))
        if missing or extra:
            raise AdmissionError(
                f"staffing_overrides[{role!r}] must carry exactly {', '.join(_OVERRIDE_KEYS)}"
                + (f"; missing {', '.join(missing)}" if missing else "")
                + (f"; unexpected {', '.join(extra)}" if extra else "")
            )
        model, effort, vendor = str(row["model"]), str(row["effort"]), str(row["vendor"])
        if model not in palette.MODELS:
            raise AdmissionError(
                f"staffing_overrides[{role!r}]: model {model!r} is not in the tier palette "
                f"({', '.join(palette.MODELS)})"
            )
        if effort not in palette.EFFORTS:
            raise AdmissionError(
                f"staffing_overrides[{role!r}]: effort {effort!r} is not in the tier palette "
                f"({', '.join(palette.EFFORTS)})"
            )
        if not palette.supports_effort(model, effort):
            raise AdmissionError(
                f"staffing_overrides[{role!r}]: {model} does not take effort {effort} "
                f"(its ceiling is {palette.effort_ceiling(model)})"
            )
        expected = _default_vendor(record, staffing, role)
        if vendor != expected:
            raise AdmissionError(
                f"staffing_overrides[{role!r}]: vendor {vendor!r} is not the role's vendor "
                f"{expected!r}; an override changes the model and effort only"
            )


def _catalogue_lenses(staffing: Any) -> tuple[set[str], set[str]] | None:
    """The catalogue's ``(always-on, conditional)`` lenses, or ``None`` when it is unreadable."""
    if staffing is None:
        return None
    try:
        catalogue, _version = staffing.lens_catalogue()
    except Exception:
        return None
    if not isinstance(catalogue, dict) or not catalogue:
        return None
    always_on = {
        str(lens)
        for lens, row in catalogue.items()
        if isinstance(row, dict) and row.get("always_on")
    }
    return always_on, {str(lens) for lens in catalogue} - always_on


def validate_lens_declaration(value: Any, staffing: Any = None) -> None:
    """Refuse a lens declaration the review would misread (issue #103).

    The shape is the one ``review_roster._lens_entries`` reads: ``always_on``, a list;
    ``conditional_applies``, a mapping of lens to reason (or a plain list); and
    ``conditional_does_not_apply``, a mapping of lens to a non-empty reason. No lens is in both
    maps and no always-on lens is in either. When the lens catalogue is readable, ``always_on`` is
    its always-on set and every conditional lens is declared exactly once; when it is not, only
    the shape is checked.
    """
    if not isinstance(value, dict):
        raise AdmissionError(
            "lens_declaration must be an object of " + ", ".join(_DECLARATION_KEYS)
        )
    extra = sorted(set(value) - set(_DECLARATION_KEYS))
    if extra:
        raise AdmissionError(
            f"lens_declaration has unexpected keys ({', '.join(extra)}); it carries "
            + ", ".join(_DECLARATION_KEYS)
        )
    always_on = value.get("always_on")
    if not isinstance(always_on, list) or not all(isinstance(lens, str) for lens in always_on):
        raise AdmissionError("lens_declaration.always_on must be a list of lens identifiers")
    applies = value.get("conditional_applies") or {}
    if not isinstance(applies, (dict, list)):
        raise AdmissionError(
            "lens_declaration.conditional_applies must map each lens to the reason it applies"
        )
    excluded = value.get("conditional_does_not_apply") or {}
    if not isinstance(excluded, dict):
        raise AdmissionError(
            "lens_declaration.conditional_does_not_apply must map each lens to the reason it "
            "does not apply"
        )
    unexplained = sorted(
        str(lens) for lens, reason in excluded.items() if not str(reason or "").strip()
    )
    if unexplained:
        raise AdmissionError(
            "lens_declaration: a lens left out needs a reason: " + ", ".join(unexplained)
        )
    applied = {str(lens) for lens in applies}
    left_out = {str(lens) for lens in excluded}
    both = sorted(applied & left_out)
    if both:
        raise AdmissionError(
            "lens_declaration names a lens as both applying and not applying: " + ", ".join(both)
        )

    catalogue = _catalogue_lenses(staffing)
    always = set(always_on) | (catalogue[0] if catalogue else set())
    deselected = sorted((applied | left_out) & always)
    if deselected:
        raise AdmissionError(
            "lens_declaration lists an always-on lens as conditional: "
            + ", ".join(deselected)
            + "; no declaration can deselect one"
        )
    if catalogue is None:
        return
    catalogue_always, catalogue_conditional = catalogue
    if set(always_on) != catalogue_always:
        raise AdmissionError(
            "lens_declaration.always_on must be the catalogue's always-on lenses: "
            + ", ".join(sorted(catalogue_always))
        )
    unknown = sorted((applied | left_out) - catalogue_conditional)
    if unknown:
        raise AdmissionError(
            "lens_declaration names lenses the catalogue does not have: " + ", ".join(unknown)
        )
    undeclared = sorted(catalogue_conditional - applied - left_out)
    if undeclared:
        raise AdmissionError(
            "lens_declaration leaves conditional lenses undeclared: "
            + ", ".join(undeclared)
            + "; each one applies or carries the reason it does not"
        )


def _merge_overrides(current: Any, overrides: dict[str, Any]) -> dict[str, Any]:
    """Lay *overrides* onto the recorded staffing map, role by role.

    A role the answer names takes its vendor, model and effort, is marked
    ``operator_override`` and records ``source`` ``operator`` (the staffing resolver's top
    layer, issue #93), so a tier source the resolver recorded for the default never outlives the
    answer that replaced it; every other role, and every run-wide ``_`` key, keeps what the
    staffing component recorded. A partial answer therefore never drops a role.
    """
    merged = json.loads(json.dumps(current)) if isinstance(current, dict) else {}
    for role, row in overrides.items():
        kept = merged.get(role) if isinstance(merged.get(role), dict) else {}
        merged[str(role)] = {
            **kept,
            **{key: row[key] for key in _OVERRIDE_KEYS},
            "source": "operator",
            "operator_override": True,
        }
    return merged


def apply_answers(
    record: run_record.RunRecord, answers: dict[str, Any], staffing: Any = None
) -> run_record.RunRecord:
    """Record *answers*, which outrank every default (plan R9).

    The staffing override and the lens declaration are validated first (issue #103), against the
    staffing component and its lens catalogue when *staffing* is given; a refusal records nothing.
    """
    admission = json.loads(json.dumps(record.admission))
    configuration = {name: dict(block) for name, block in record.run_configuration.items()}
    approval_scope = dict(record.approval_scope)
    known = {question.key for question in QUESTIONS}

    unknown = sorted(set(answers) - known - {"risk_justification", FUNCTIONAL_TEST_WAIVER_KEY})
    if unknown:
        raise AdmissionError(f"not admission questions: {', '.join(unknown)}")
    if "staffing_overrides" in answers:
        validate_staffing_overrides(answers["staffing_overrides"], record, staffing)
    if "lens_declaration" in answers:
        validate_lens_declaration(answers["lens_declaration"], staffing)
    environment = functional_environment_answer(answers)

    if environment is not None:
        admission[FUNCTIONAL_TEST_KEY] = environment
        key, value = functional_environment.profile_entry(environment)
        admission.setdefault("answers", {})[FUNCTIONAL_TEST_KEY] = {
            "value": {key: value} if key != FUNCTIONAL_TEST_KEY else value,
            "source": "operator",
        }
    for key, value in answers.items():
        if key in (FUNCTIONAL_TEST_KEY, FUNCTIONAL_TEST_WAIVER_KEY):
            continue
        admission.setdefault("answers", {})[key] = {"value": value, "source": "operator"}
        if key == "approval_scope" and isinstance(value, dict):
            for category in run_record.APPROVAL_CATEGORIES:
                if category in value:
                    approval_scope[category] = value[category]
        elif key == "unfinished_testing_response":
            _fill(configuration, key, value, "operator")
        elif key == "repair_allowances" and isinstance(value, dict):
            if "standard" in value:
                _fill(configuration, "standard_cycle_allowance", value["standard"], "operator")
            if "escalated" in value:
                _fill(configuration, "escalated_cycle_allowance", value["escalated"], "operator")
        elif key == "lens_declaration":
            _fill(configuration, "applicable_lenses", value, "operator")
        elif key == "staffing_overrides":
            if not _no_override(value):
                current = configuration["staffing_models_and_efforts"].get("value")
                merged = _merge_overrides(current, value)
                _fill(configuration, "staffing_models_and_efforts", merged, "operator")
        elif key in admission:
            admission[key] = value

    return run_record.RunRecord(
        **{
            **record.__dict__,
            "admission": admission,
            "run_configuration": configuration,
            "approval_scope": approval_scope,
        }
    )


def functional_environment_answer(answers: dict[str, Any]) -> dict[str, Any] | None:
    """The operator's functional-test environment or waiver, checked, or ``None`` if not answered.

    Refuses an unknown kind, a missing test command, a missing deploy command outside ``local``, a
    scope that contradicts the kind, a waiver without a reason, and both answers at once.
    """
    try:
        return functional_environment.from_answers(answers)
    except functional_environment.DeclarationError as exc:
        raise AdmissionError(str(exc)) from exc


def validate_card(body: str, validator: Callable[[str], tuple[bool, list[str]]]) -> dict[str, Any]:
    """Run the card validator and return the block the record stores. Raises when it fails."""
    passed, errors = validator(body)
    block = {"performed": True, "passed": bool(passed), "errors": list(errors)}
    if not passed:
        raise CardNotReadyError(
            "the card is not ready and admission writes nothing: " + "; ".join(errors)
        )
    return block


#: The lifecycle repository's six issue-review checks. Only the first is mechanical; the other five
#: are the Issue Reviewer role's judgment, and no role is staffed for them yet.
ISSUE_REVIEW_CHECKS: tuple[str, ...] = (
    "the card validator passes",
    "the product content is complete and testable",
    "the technical claims are spot-checked against the repository and the context library links",
    "no UNKNOWN is outstanding",
    "the approval boundaries are named per category",
    "Risk carries a real tier with its one-sentence justification",
)


def issue_review_block(card_passed: bool) -> dict[str, str]:
    """Record which of the six checks ran. Honest about the five that did not."""
    block = dict.fromkeys(ISSUE_REVIEW_CHECKS, "not_performed")
    block[ISSUE_REVIEW_CHECKS[0]] = "passed" if card_passed else "failed"
    return block


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def admit(
    issue: int,
    repo: str,
    *,
    store_root: Path,
    repo_root: Path,
    body: str,
    validator: Callable[[str], tuple[bool, list[str]]],
    staffing: Any = None,
    answers: dict[str, Any] | None = None,
    suggest: bool = False,
    suggest_ask: Callable[..., Any] | None = None,
    suggest_log_dir: Path | None = None,
) -> tuple[run_record.RunRecord, list[Question]]:
    """Validate, fill, apply any answers, and return the record with what is still outstanding."""
    existing = run_record.load(store_root, issue, warn=None)
    record = existing or run_record.RunRecord(issue=int(issue), repo=repo)
    if repo and not record.repo:
        record = run_record.RunRecord(**{**record.__dict__, "repo": repo})

    card_block = validate_card(body, validator)
    admission = json.loads(json.dumps(record.admission))
    admission["card_validation"] = card_block
    admission["issue_review_checks"] = issue_review_block(card_block["passed"])
    record = run_record.RunRecord(**{**record.__dict__, "admission": admission})

    record = fill_defaults(
        record,
        load_profile(repo_root),
        staffing,
        suggest=suggest,
        suggest_ask=suggest_ask,
        suggest_log_dir=suggest_log_dir,
        repo_root=repo_root,
    )
    if answers:
        record = apply_answers(record, answers, staffing)

    outstanding = outstanding_questions(record)
    admission = json.loads(json.dumps(record.admission))
    admission["pending_questions"] = [question.key for question in outstanding]
    # Leave the record saying what happens next, so a session that reads it cold — or one the spore
    # re-grounds after compaction — knows where the run is without being told.
    next_step = (
        f"answer the {len(outstanding)} outstanding admission question(s), then plan"
        if outstanding
        else "plan"
    )
    record = run_record.RunRecord(
        **{
            **record.__dict__,
            "admission": admission,
            "next_step": _next_step(record.next_step, next_step),
        }
    )
    return record, outstanding


#: The next step admission itself writes while questions are outstanding. Only a next step of this
#: form is admission's to replace: answering in two passes (the review pane records questions 4 and
#: 5, the rest follow) must not leave the first pass's count on the record (issue #103).
_ADMISSION_NEXT_STEP = re.compile(r"answer the \d+ outstanding admission question\(s\), then plan")


def _next_step(current: str, fresh: str) -> str:
    """Keep a next step a later step set; replace an empty one or one admission wrote."""
    if current and not _ADMISSION_NEXT_STEP.fullmatch(current):
        return current
    return fresh


#: The record fields ``admit`` writes. Everything else on the record belongs to another writer.
ADMISSION_FIELDS: tuple[str, ...] = ("repo", "admission", "run_configuration", "approval_scope")


def save_admission(store_root: Path, admitted: run_record.RunRecord) -> Path:
    """Write what ``admit`` decided onto the record, under its lock (issue 95).

    ``admit`` can consult the tier judgment, so it runs with no lock held. The write then re-reads
    the record under the lock and lands only the admission-owned fields on that fresh copy, so a
    unit row, a review result or a usage entry written meanwhile survives. A fresh ``next_step``
    wins over admission's suggestion, the same rule ``admit`` applies to the copy it read; one
    admission itself wrote earlier is replaced (``_next_step``).
    """

    def change(current: run_record.RunRecord | None) -> run_record.RunRecord:
        if current is None:
            return admitted
        owned = {name: getattr(admitted, name) for name in ADMISSION_FIELDS}
        return run_record.RunRecord(
            **{
                **current.__dict__,
                **owned,
                "next_step": _next_step(current.next_step, admitted.next_step),
            }
        )

    return run_record.update(store_root, admitted.issue, change)


def render(record: run_record.RunRecord, outstanding: list[Question], path: Path | None) -> str:
    """The operator-facing summary: what was filled, and the one message still to answer."""
    lines: list[str] = []
    lines.append(f"Admission for issue {record.issue} ({record.repo or 'repository unknown'})")
    lines.append("")
    lines.append("Filled without asking:")
    for name in run_record.RUN_CONFIGURATION_PARAMETERS:
        block = record.run_configuration[name]
        if block["source"] == "unset":
            continue
        lines.append(f"  {name} = {json.dumps(block['value'])}  [{block['source']}]")
    filled = sum(
        1
        for name in run_record.RUN_CONFIGURATION_PARAMETERS
        if record.run_configuration[name]["source"] != "unset"
    )
    lines.append(f"  ({filled} of {len(run_record.RUN_CONFIGURATION_PARAMETERS)} parameters)")
    lines.append("")
    recorded = record.admission.get(FUNCTIONAL_TEST_KEY)
    environment = recorded if isinstance(recorded, dict) else None
    source = f"  [{environment.get('source')}]" if environment else ""
    lines.append(f"Functional-test environment:{source}")
    lines.extend(f"  {line}" for line in functional_environment.describe(environment))
    lines.append("")
    if outstanding:
        lines.append(f"Questions to answer, once ({len(outstanding)}):")
        for index, question in enumerate(outstanding, start=1):
            suffix = f"  [default: {json.dumps(question.default)}]" if question.default else ""
            lines.append(f"  {index}. {question.key}: {question.prompt}{suffix}")
    else:
        lines.append("Questions to answer: none — every answer is already in the record.")
    lines.append("")
    lines.append(f"Record: {path}" if path else "Record: not written (--dry-run)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The staffing and lens tables, in one fixed format (issue #102)
# ---------------------------------------------------------------------------
#
# The operator answers staffing_overrides and lens_declaration against a table. Left to the model,
# that table came out in a different shape every run, so admission renders it itself: one set of
# rows (``review_data``) feeds both the fixed Markdown (``render_tables``) every harness prints
# verbatim and the JSON a Claude Code pane reads. Nothing here changes the record.

#: What ``--render`` can print.
RENDER_CHOICES: tuple[str, ...] = ("summary", "tables", "json")

#: The schema of ``--render json``.
REVIEW_SCHEMA = "admission_review.v1"

#: The two tables' titles and column orders. Bold text, never a Markdown heading: the plan skill
#: quotes the block, and a heading line inside a skill splits its gate-record sections.
STAFFING_TITLE = "**Staffing (answer: staffing_overrides)**"
STAFFING_COLUMNS: tuple[str, ...] = ("Role", "Default", "Jev suggestion", "Proposed", "Why")
LENS_TITLE = "**Lenses (answer: lens_declaration)**"
LENS_COLUMNS: tuple[str, ...] = ("Lens", "Include", "Reason", "Jev probability")

#: The text of an empty Jev cell. A cell is never left blank.
NOT_CONFIGURED = "not configured"
NO_SUGGESTION = "no suggestion"

#: The probability bands a lens proposal is read in: pre-checked at 0.8 and above, worth
#: considering from 0.6 up to 0.8. Below 0.6 a probability is logged and not shown (issue #110,
#: Intent item 2), so the cell reads "no suggestion" and only the JSON row keeps the value.
#: Interim copies: import them from review_roster once issue #110 defines them there.
LENS_PRE_CHECKED_AT = 0.8
LENS_CONSIDER_AT = 0.6

#: How each tier-judgment band (the per-role block issue #96 writes) reads in the Jev cell. The
#: band names are an interim copy of fleet-core's ``classify_judgment`` vocabulary (issue #96);
#: import them from the staffing component once that lands. ``raise-at-ceiling`` carries no
#: proposed tier, so it is rendered separately (``_AT_CEILING``); ``log-only`` is never shown.
_BAND_NOTES: dict[str, str] = {
    "agrees": "agrees",
    "auto-raise": "raise applied",
    "confirm-raise": "raise to confirm",
    "advisory-lower": "advisory lower",
}
_AT_CEILING = "raise-at-ceiling"

#: The staffing-table and lens-table states a pane branches on instead of matching display text.
STAFFING_UNREACHABLE = "unreachable"
LENS_CATALOGUE_UNREADABLE = "catalogue-unreadable"
_STAFFING_PLACEHOLDER = "(staffing component unreachable)"
_LENS_PLACEHOLDER = "(lens catalogue unreadable)"


def _tier_text(tier: Any, *, with_vendor: bool = True) -> str | None:
    """``vendor model/effort`` for a tier mapping, or ``None`` when it names no model."""
    if not isinstance(tier, dict) or not tier.get("model"):
        return None
    text = f"{tier['model']}/{tier.get('effort') or 'default'}"
    if with_vendor and tier.get("vendor"):
        text = f"{tier['vendor']} {text}"
    return text


def _tier(vendor: Any, model: Any, effort: Any) -> dict[str, Any] | None:
    if not model:
        return None
    return {"vendor": vendor, "model": model, "effort": effort}


def _default_tier(
    staffing: Any, role: str, repo_root: Path | None = None
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """A fresh staffing resolve for *role*: its default tier, its work shape, and where the tier
    came from (``overlay`` for ``.saga/tier-defaults.json``, ``policy`` for the shared work-shape
    registry), or ``None``s. *repo_root* is the checkout whose overlay is read, the same root
    :func:`fill_defaults` staffs with; ``None`` reads the working directory's."""
    if staffing is None:
        return None, None, None
    try:
        decision = staffing.resolve_role(role, root=repo_root)
    except Exception:
        return None, None, None
    tier = _tier(
        getattr(decision, "vendor", None),
        getattr(decision, "model", None),
        getattr(decision, "effort", None),
    )
    shape = getattr(decision, "work_shape", None)
    if not shape:
        try:
            shape = (staffing.roles().get(role) or {}).get("work_shape")
        except Exception:
            shape = None
    source = getattr(decision, "source", None)
    return tier, shape, source if isinstance(source, str) else None


def _raise_outcome(
    staffing: Any,
    role: str,
    row: dict[str, Any],
    raise_: dict[str, Any],
    repo_root: Path | None = None,
) -> tuple[Any, str | None]:
    """What the staffing resolver makes of a recorded Jev raise for *role*.

    Returns ``(decision, refused)`` from :func:`_resolve_one_role`, the same call admission staffs
    with, so the table reads the precedence and the raise rules from the resolver and restates
    neither. ``decision.source`` names the rung that won (``jev-raise`` when the raise applied);
    ``refused`` is the resolver's own message when it refused the raise. With the resolver
    unreachable, the row's recorded ``source`` and ``jev_raise_refused`` (written by
    :func:`_resolve_staffing` from the same resolver) stand in. *repo_root* is the overlay root
    admission staffed with, so the table and the staffed tier read the same overlay.
    """
    if staffing is not None:
        try:
            decision, refused = _resolve_one_role(staffing, role, root=repo_root, jev_raise=raise_)
        except AdmissionError:
            decision, refused = None, None
        if decision is not None or refused is not None:
            return decision, refused
    refused = row.get("jev_raise_refused")
    if isinstance(refused, str) and refused:
        return None, refused
    source = row.get("source")
    if isinstance(source, str):
        recorded = {key: row.get(key) for key in ("vendor", "model", "effort")}
        return SimpleNamespace(source=source, **recorded), None
    return None, None


def _proposed_and_why(
    row: dict[str, Any],
    shape: str | None,
    default_source: str | None,
    *,
    operator: bool,
    staffing: Any = None,
    role: str = "",
    repo_root: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Which tier wins for one role, and the Why cell that names where it came from.

    The precedence and the raise rules are the staffing resolver's (issue #93); this function
    only words its answer. An operator answer is shown as recorded. Otherwise a recorded Jev raise
    is handed to the resolver: the decision's ``source`` says whether the raise applied
    (``jev-raise``) or a higher rung outranked it (``overlay``), and a refused raise is shown with
    the resolver's own message beside the default it fell back to.
    """
    recorded = _tier(row.get("vendor"), row.get("model"), row.get("effort"))
    shape_note = f"work shape {shape}" if shape else None
    if operator:
        return recorded, "operator answer"
    overlay_why = "repository overlay (.saga/tier-defaults.json" + (
        f", {shape_note})" if shape_note else ")"
    )
    base_why = f"staffing default ({shape_note})" if shape_note else "staffing default"
    raise_ = row.get("jev_raise") if isinstance(row.get("jev_raise"), dict) else {}
    if not raise_.get("model"):
        return recorded, overlay_why if default_source == "overlay" else base_why
    decision, refused = _raise_outcome(staffing, role, row, raise_, repo_root)
    source = getattr(decision, "source", None) if decision is not None else default_source
    layer_why = overlay_why if source == "overlay" else base_why
    if refused is not None:
        shown = _tier_text(raise_, with_vendor=False)
        return recorded, f"{layer_why}; recorded Jev raise to {shown} refused: {refused}"
    if source == "jev-raise":
        proposed = _tier(
            row.get("vendor") or getattr(decision, "vendor", None),
            getattr(decision, "model", None),
            getattr(decision, "effort", None),
        )
        return proposed, f"Jev raise: {raise_.get('reason') or 'no reason recorded'}"
    if source == "overlay":
        return recorded, f"{overlay_why}; the overlay outranks the recorded Jev raise"
    return recorded, base_why


def _confidence_text(confidence: Any) -> str | None:
    return f"{confidence:.2f}" if isinstance(confidence, (int, float)) else None


def _jev_staffing_cell(row: dict[str, Any], consult: Any) -> dict[str, Any]:
    """The Jev cell for one role.

    Reads, in order: the per-role ``tier_judgment`` block (issue #96), then the advisory
    ``suggestion`` that ``--suggest`` records. With neither, the run-wide consult note
    (``value['_tier_judgment']``) says whether the judgment was switched off or failed.
    """
    judgment = row.get("tier_judgment")
    if isinstance(judgment, dict):
        band = str(judgment.get("band") or "")
        confidence = _confidence_text(judgment.get("confidence"))
        shown = judgment.get("shown", True) is not False
        tier = judgment.get("proposed") if band != "agrees" else judgment.get("default")
        if band == "not-consulted":
            state = "not-configured"
        elif band == _AT_CEILING and shown and confidence:
            # No proposed tier exists: the default is already the strongest a raise may reach.
            return {
                "cell": f"at ceiling ({confidence})",
                "state": "at-ceiling",
                "band": band,
                "suggested": None,
                "confidence": judgment.get("confidence"),
                "reason": judgment.get("reason") or "",
            }
        elif band in _BAND_NOTES and shown and confidence and _tier_text(tier, with_vendor=False):
            cell = f"{_tier_text(tier, with_vendor=False)} ({confidence}, {_BAND_NOTES[band]})"
            return {
                "cell": cell,
                "state": "suggested",
                "band": band,
                "suggested": _tier_text(tier, with_vendor=False),
                "confidence": judgment.get("confidence"),
                "reason": judgment.get("reason") or "",
            }
        else:
            state = "no-suggestion"
        return {
            "cell": NOT_CONFIGURED if state == "not-configured" else NO_SUGGESTION,
            "state": state,
            "band": band or None,
            "suggested": None,
            "confidence": judgment.get("confidence"),
            "reason": judgment.get("reason") or "",
        }

    suggestion = row.get("suggestion")
    if isinstance(suggestion, dict):
        suggested = suggestion.get("suggested")
        confidence = _confidence_text(suggestion.get("confidence"))
        if (
            suggestion.get("usable")
            and not suggestion.get("low_confidence")
            and suggested
            and confidence
        ):
            return {
                "cell": f"{suggested} ({confidence})",
                "state": "suggested",
                "band": None,
                "suggested": suggested,
                "confidence": suggestion.get("confidence"),
                "reason": suggestion.get("reason") or "",
            }
        return {
            "cell": NO_SUGGESTION,
            "state": "no-suggestion",
            "band": None,
            "suggested": None,
            "confidence": suggestion.get("confidence"),
            "reason": suggestion.get("reason") or suggestion.get("problem") or "",
        }

    consulted = isinstance(consult, dict) and consult.get("status") not in (None, "off")
    return {
        "cell": NO_SUGGESTION if consulted else NOT_CONFIGURED,
        "state": "no-suggestion" if consulted else "not-configured",
        "band": None,
        "suggested": None,
        "confidence": None,
        "reason": (consult or {}).get("note", "") if isinstance(consult, dict) else "",
    }


def _staffing_rows(
    record: run_record.RunRecord, staffing: Any, repo_root: Path | None = None
) -> dict[str, Any]:
    """One row per role the record holds, in sorted order. *repo_root* is the overlay root
    admission staffed with (``--repo-root``); ``None`` reads the working directory's."""
    block = record.run_configuration["staffing_models_and_efforts"]
    value = block.get("value")
    source = block.get("source", "unset")
    if not isinstance(value, dict) or not any(not str(key).startswith("_") for key in value):
        # No placeholder row in the data: a pane reads ``status``, and ``render_tables`` draws
        # the placeholder line from it.
        return {"source": source, "status": STAFFING_UNREACHABLE, "rows": []}

    consult = value.get("_tier_judgment")
    # An operator answer either replaced the whole map (no row carries ``operator_override``) or
    # was merged per role (the overridden rows carry it).
    merged = any(isinstance(row, dict) and "operator_override" in row for row in value.values())
    rows: list[dict[str, Any]] = []
    for role in sorted(key for key in value if not str(key).startswith("_")):
        row = value[role] if isinstance(value[role], dict) else {}
        default, shape, default_source = _default_tier(staffing, role, repo_root)
        if default is None and source == "staffing":
            default = _tier(row.get("vendor"), row.get("model"), row.get("effort"))
        operator = row.get("operator_override") is True or (source == "operator" and not merged)
        proposed, why = _proposed_and_why(
            row,
            shape,
            default_source,
            operator=operator,
            staffing=staffing,
            role=role,
            repo_root=repo_root,
        )
        rows.append(
            {
                "role": role,
                "vendor": (proposed or {}).get("vendor"),
                "default": default,
                "proposed": proposed,
                "jev": _jev_staffing_cell(row, consult),
                "why": why,
            }
        )
    return {"source": source, "status": "ok", "rows": rows}


def _lens_proposal(record: run_record.RunRecord) -> dict[str, Any] | None:
    """The Jev lens proposal admission records (issue #110), or ``None`` when absent."""
    proposal = record.admission.get("lens_proposal")
    return proposal if isinstance(proposal, dict) else None


def _jev_lens_cell(lens: str, always_on: bool, proposal: dict[str, Any] | None) -> dict[str, Any]:
    """The Jev cell for one lens. ``band`` (``pre-checked``, ``consider`` or ``None``) is what a
    pane branches on, so it never reads the cell's display text."""
    if proposal is None:
        return {
            "cell": NOT_CONFIGURED,
            "state": "not-configured",
            "probability": None,
            "band": None,
        }
    probabilities = proposal.get("probabilities")
    probability = probabilities.get(lens) if isinstance(probabilities, dict) else None
    if always_on or not isinstance(probability, (int, float)):
        return {"cell": NO_SUGGESTION, "state": "no-suggestion", "probability": None, "band": None}
    if probability < LENS_CONSIDER_AT:
        # Logged, not shown (issue #110): the JSON row keeps the value for the record.
        return {
            "cell": NO_SUGGESTION,
            "state": "below-threshold",
            "probability": probability,
            "band": None,
        }
    band = "pre-checked" if probability >= LENS_PRE_CHECKED_AT else "consider"
    return {
        "cell": f"{probability:.2f} ({band})",
        "state": "suggested",
        "probability": probability,
        "band": band,
    }


def _declared(value: Any, key: str) -> dict[str, str]:
    """A lens declaration's ``conditional_applies`` or ``conditional_does_not_apply``, as
    ``{lens: reason}``. Matches ``review_roster._lens_entries``, the declaration's consumer: a
    plain list is accepted for ``conditional_applies`` only, so the table never shows an
    exclusion the review would not honour."""
    entries = value.get(key) if isinstance(value, dict) else None
    if isinstance(entries, dict):
        return {str(lens): str(reason) for lens, reason in entries.items()}
    if isinstance(entries, list) and key == "conditional_applies":
        return {str(lens): "" for lens in entries}
    return {}


def _lens_rows(record: run_record.RunRecord, staffing: Any) -> dict[str, Any]:
    """One row per catalogue lens, in catalogue order."""
    block = record.run_configuration["applicable_lenses"]
    declaration = block.get("value") if block.get("source") == "operator" else None
    applies = _declared(declaration, "conditional_applies")
    excluded = _declared(declaration, "conditional_does_not_apply")
    proposal = _lens_proposal(record)

    catalogue: Any = None
    version: Any = None
    if staffing is not None:
        try:
            catalogue, version = staffing.lens_catalogue()
        except Exception:
            catalogue = None
    if isinstance(catalogue, dict) and catalogue:
        lenses = [
            (str(lens), isinstance(entry, dict) and bool(entry.get("always_on")))
            for lens, entry in catalogue.items()
        ]
    elif isinstance(declaration, dict):
        lenses = [(str(lens), True) for lens in declaration.get("always_on") or []]
        # A lens in both maps is listed once (a malformed answer; the exclusion wins below).
        lenses += [(lens, False) for lens in dict.fromkeys([*applies, *excluded])]
    else:
        lenses = []

    rows: list[dict[str, Any]] = []
    for lens, always_on in lenses:
        if always_on:
            include, reason = "always on", "always-on lens"
        elif lens in excluded:
            # Checked first: review_roster._lens_entries writes the excluded map last, so a lens
            # in both maps is excluded from the review, and the table must say so.
            include, reason = "no", excluded[lens] or "no reason recorded"
        elif lens in applies:
            include, reason = "yes", applies[lens] or "included"
        else:
            include, reason = "undeclared", "undeclared"
        rows.append(
            {
                "lens": lens,
                "always_on": always_on,
                "include": include,
                "reason": reason,
                "jev": _jev_lens_cell(lens, always_on, proposal),
            }
        )
    read = isinstance(catalogue, dict) and bool(catalogue)
    return {
        "catalogue_version": version if read else None,
        "source": block.get("source", "unset"),
        # Unreadable with an operator declaration: the rows are the declaration's lenses.
        "status": "ok" if read else LENS_CATALOGUE_UNREADABLE,
        "rows": rows,
    }


def _palette() -> dict[str, Any] | None:
    """The tiers an operator may pick from, from the bundled ``tier_palette``; ``None`` when it
    cannot be loaded. Claude's palette only: it is the one the staffing component staffs."""
    try:
        import bundled_fleet  # noqa: PLC0415

        palette = bundled_fleet.load("tier_palette")
        models = list(palette.MODELS)
        efforts = list(palette.EFFORTS)
        return {
            "vendor": PALETTE_VENDOR,
            "models": models,
            "efforts": efforts,
            "effort_ceilings": {model: palette.effort_ceiling(model) for model in models},
            "pairs": [
                {"model": model, "effort": effort}
                for model in models
                for effort in efforts
                if palette.supports_effort(model, effort)
            ],
        }
    except Exception:
        return None


def _cell(value: Any) -> str:
    """One table cell: ``|`` escaped, newlines folded, and never empty."""
    text = " ".join(str(value if value is not None else "").split())
    return text.replace("|", "\\|") or NOT_CONFIGURED


def _table(columns: tuple[str, ...], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return lines


def render_tables(data: dict[str, Any]) -> str:
    """The staffing and lens tables, in their fixed Markdown format, built from ``data`` alone."""
    staffing_rows = [
        [
            row["role"],
            _tier_text(row["default"]) or NOT_CONFIGURED,
            row["jev"]["cell"],
            _tier_text(row["proposed"]) or NOT_CONFIGURED,
            row["why"],
        ]
        for row in data["staffing"]["rows"]
    ] or [[_STAFFING_PLACEHOLDER, NOT_CONFIGURED, NOT_CONFIGURED, NOT_CONFIGURED, NOT_CONFIGURED]]
    lens_rows = [
        [row["lens"], row["include"], row["reason"], row["jev"]["cell"]]
        for row in data["lenses"]["rows"]
    ] or [[_LENS_PLACEHOLDER, "undeclared", "the lens catalogue could not be read", NOT_CONFIGURED]]
    lines = [STAFFING_TITLE, "", *_table(STAFFING_COLUMNS, staffing_rows), ""]
    lines += [LENS_TITLE, "", *_table(LENS_COLUMNS, lens_rows)]
    return "\n".join(lines)


def review_data(
    record: run_record.RunRecord,
    outstanding: list[Question],
    staffing: Any,
    path: Path | None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Everything the two tables show, machine-readable (schema ``admission_review.v1``).

    *repo_root* must be the root admission staffed with, so the staffing table resolves tiers
    against the same ``.saga/tier-defaults.json`` overlay as the recorded rows."""
    data: dict[str, Any] = {
        "schema": REVIEW_SCHEMA,
        "issue": record.issue,
        "repo": record.repo,
        "record_path": str(path) if path else None,
        "pending_questions": [question.key for question in outstanding],
        "questions": [
            {"key": question.key, "prompt": question.prompt, "default": question.default}
            for question in outstanding
        ],
        "staffing": _staffing_rows(record, staffing, repo_root),
        "lenses": _lens_rows(record, staffing),
        "palette": _palette(),
    }
    data["tables_markdown"] = render_tables(data)
    return data


def read_answers(source: str) -> dict[str, Any]:
    """The answers JSON from a file, or from standard input when *source* is ``-``.

    Standard input is how the Claude Code review pane hands its answers over (issue #103): the
    answers never touch a temporary file, and the script stays the one writer.
    """
    try:
        text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise AdmissionError(f"could not read the answers from {source}: {exc}") from exc
    try:
        answers = json.loads(text)
    except json.JSONDecodeError as exc:
        where = "standard input" if source == "-" else source
        raise AdmissionError(f"the answers in {where} are not JSON: {exc}") from exc
    if not isinstance(answers, dict):
        raise AdmissionError("the answers must be one JSON object of question key to answer")
    return answers


def _write_profile(repo_root: Path, environment: dict[str, Any]) -> Path:
    """Write the operator's declaration or waiver into the tracked profile (issue #97)."""
    try:
        return functional_environment.write_declaration(repo_root, environment)
    except (OSError, functional_environment.DeclarationError) as exc:
        raise AdmissionError(
            f"could not write the functional-test declaration to "
            f"{Path(repo_root) / PROFILE_FILENAME}: {exc}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admission.py",
        description="Run the admission questionnaire for one issue.",
    )
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--repo", default=None, help="owner/name; defaults to the origin remote.")
    parser.add_argument("--store-root", default=None, help="Override the resolved store directory.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Where .saga-profile.json is read from, and where an answered functional-test "
            "declaration is written."
        ),
    )
    parser.add_argument(
        "--answers",
        default=None,
        help="A JSON file of answers to record, or '-' to read the JSON from standard input.",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help=(
            "Consult the tier judgment once for every staffed role and record each suggestion "
            "beside its default. Advisory: a suggestion never changes a value."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the questions and the filled defaults; write nothing.",
    )
    parser.add_argument(
        "--render",
        choices=RENDER_CHOICES,
        default="summary",
        help=(
            "What to print. summary (default): the filled defaults and the questions. tables: "
            "the summary, then the staffing (staffing_overrides) and lens (lens_declaration) "
            "tables in their fixed Markdown format, to show the operator exactly as printed. "
            f"json: the same data, machine-readable (schema {REVIEW_SCHEMA})."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
        repo = args.repo or default_repo(repo_root)
        store_root = (
            Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
        )
        answers = read_answers(args.answers) if args.answers else None

        issue_payload = fetch_issue(args.issue, repo)
        staffing = load_staffing()
        record, outstanding = admit(
            args.issue,
            repo,
            store_root=store_root,
            repo_root=repo_root,
            body=issue_payload.get("body") or "",
            validator=load_card_validator(),
            staffing=staffing,
            answers=answers,
            suggest=args.suggest,
        )
        path = None
        if not args.dry_run:
            environment = functional_environment_answer(answers or {})
            if environment is not None:
                # The profile first: a failed write leaves the record unsaved, so the question is
                # still outstanding on the next run rather than recorded as answered.
                written = _write_profile(repo_root, environment)
                print(
                    f"Wrote the functional-test declaration to {written}; commit it with this "
                    "run's changes.",
                    file=sys.stderr,
                )
            path = save_admission(store_root, record)
        if args.render == "json":
            data = review_data(record, outstanding, staffing, path, repo_root)
            print(json.dumps(data, indent=2, sort_keys=True))
        elif args.render == "tables":
            data = review_data(record, outstanding, staffing, path, repo_root)
            print(render(record, outstanding, path) + "\n\n" + data["tables_markdown"])
        else:
            print(render(record, outstanding, path))
        return 0
    except run_record.UnknownRecordVersionError as exc:
        print(f"admission: {exc}", file=sys.stderr)
        return 3
    except (AdmissionError, run_record.RunRecordError) as exc:
        print(f"admission: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
