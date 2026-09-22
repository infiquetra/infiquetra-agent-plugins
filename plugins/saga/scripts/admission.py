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

Exit codes are the run record's (see ``references/run-record.md``): 0 success, 2 a refusal —
including a card that fails the validator — and 3 an unknown record version.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess  # nosec B404
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

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

#: The two admission answers a profile can settle, because they are facts about a repository
#: rather than choices about a run.
PROFILE_ADMISSION_ANSWERS: tuple[str, ...] = ("branch_preview", "main_consumed_directly")

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
    Question("branch_preview", "Does this repository have a branch preview deployment?"),
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
) -> run_record.RunRecord:
    """Fill every defaultable parameter, recording where each value came from (plan R7).

    Never overwrites a value already carrying an ``operator`` source: an answer the operator gave
    outranks any default, and re-deriving it would be the re-asking this whole module exists to
    stop.

    ``suggest`` asks the staffing component for one batched tier suggestion per role and records
    each beside its default. Advisory and fail-open: a suggestion never changes a value, and a
    component without a consult entry point — or a failed request — leaves the defaults exactly
    as they would have been.
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

    if (
        staffing is not None
        and configuration["staffing_models_and_efforts"]["source"] != "operator"
    ):
        resolved = _resolve_staffing(
            staffing, suggest=suggest, suggest_ask=suggest_ask, suggest_log_dir=suggest_log_dir
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
    suggest: bool = False,
    suggest_ask: Callable[..., Any] | None = None,
    suggest_log_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Ask the staffing component for each role's vendor, model and effort.

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
    for role in sorted(roles):
        try:
            decision = staffing.resolve_role(role)
        except Exception:
            continue
        resolved[role] = {
            "vendor": getattr(decision, "vendor", None),
            "model": getattr(decision, "model", None),
            "effort": getattr(decision, "effort", None),
        }
        operator_set[role] = getattr(decision, "source", "policy") == "overlay"
    if suggest and resolved:
        _attach_suggestions(staffing, resolved, operator_set, suggest_ask, suggest_log_dir)
    return resolved or None


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


def _is_answered(record: run_record.RunRecord, key: str) -> bool:
    """Has *key* already been answered? Used to decide what NOT to ask (plan R9)."""
    admission = record.admission
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
    """The questions still to put to the operator, in order. Empty means nothing is outstanding."""
    return [question for question in QUESTIONS if not _is_answered(record, question.key)]


def apply_answers(record: run_record.RunRecord, answers: dict[str, Any]) -> run_record.RunRecord:
    """Record *answers*, which outrank every default (plan R9)."""
    admission = json.loads(json.dumps(record.admission))
    configuration = {name: dict(block) for name, block in record.run_configuration.items()}
    approval_scope = dict(record.approval_scope)
    known = {question.key for question in QUESTIONS}

    unknown = sorted(set(answers) - known - {"risk_justification"})
    if unknown:
        raise AdmissionError(f"not admission questions: {', '.join(unknown)}")

    for key, value in answers.items():
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
            if value not in (None, "none", {}):
                _fill(configuration, "staffing_models_and_efforts", value, "operator")
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
    )
    if answers:
        record = apply_answers(record, answers)

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
        **{**record.__dict__, "admission": admission, "next_step": record.next_step or next_step}
    )
    return record, outstanding


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admission.py",
        description="Run the admission questionnaire for one issue.",
    )
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--repo", default=None, help="owner/name; defaults to the origin remote.")
    parser.add_argument("--store-root", default=None, help="Override the resolved store directory.")
    parser.add_argument("--repo-root", default=None, help="Where to look for .saga-profile.json.")
    parser.add_argument("--answers", default=None, help="A JSON file of answers to record.")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
        repo = args.repo or default_repo(repo_root)
        store_root = (
            Path(args.store_root).resolve() if args.store_root else run_record.resolve_store_root()
        )
        answers = None
        if args.answers:
            answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))

        issue_payload = fetch_issue(args.issue, repo)
        record, outstanding = admit(
            args.issue,
            repo,
            store_root=store_root,
            repo_root=repo_root,
            body=issue_payload.get("body") or "",
            validator=load_card_validator(),
            staffing=load_staffing(),
            answers=answers,
            suggest=args.suggest,
        )
        path = None if args.dry_run else run_record.save(store_root, record)
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
