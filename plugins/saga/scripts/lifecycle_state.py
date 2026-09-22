#!/usr/bin/env python3
"""Infiquetra lifecycle destination and escalation helpers."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

DESTINATION_ALIASES = {
    "plan": "plan-only",
    "plan only": "plan-only",
    "plan-only": "plan-only",
    "planning": "plan-only",
    "pr": "pr",
    "pull request": "pr",
    "pull-request": "pr",
    "merge": "merge",
    "merged": "merge",
    "nonprod": "nonprod-deploy",
    "nonprod deploy": "nonprod-deploy",
    "nonprod-deploy": "nonprod-deploy",
    "deploy": "nonprod-deploy",
}


def normalize_destination(value: str) -> str:
    """Normalize user-facing destination labels."""

    key = " ".join(value.strip().lower().replace("_", "-").split())
    key = key.replace("nonprod-deployment", "nonprod-deploy")
    if key in DESTINATION_ALIASES:
        return DESTINATION_ALIASES[key]
    raise ValueError("destination must be one of: plan-only, pr, merge, nonprod-deploy")


def destination_includes_deploy(destination: str) -> bool:
    """Return whether the selected destination needs deployment orchestration."""

    return normalize_destination(destination) == "nonprod-deploy"


def should_offer_team_execution(
    *,
    file_count: int,
    phase_count: int,
    has_security: bool,
    has_infra: bool,
    cross_repo: bool,
    deployment_sensitive: bool,
    has_code_surface: bool = True,
    release_surface_file_count: int = 0,
) -> bool:
    """Decide whether the loop should offer team-execution.

    ``has_code_surface`` defaults True, so every existing caller is unchanged.
    Set it False for pure docs/spec/research/journal work (no code, no IaC, no
    API contract, no deployable artifact). It neutralizes the OUTPUT-BLIND
    proxies — the ones that fire on the *mention* or *volume* of risk rather than
    a real ship/scanner surface that team-execution's gates can act on:

    * ``file_count`` / ``phase_count`` — volume and sequencing, not governance.
    * ``has_infra`` / ``has_security`` — ``parse_issue.py`` keyword regexes
      (terraform, lambda, auth, iam, ...) trip on infra/security DOCS that touch
      nothing deployable.
    * ``deployment_sensitive`` — cannot truthfully hold when there is no deploy.

    ``cross_repo`` SURVIVES the neutralizer: crossing a repo boundary crosses an
    OWNERSHIP boundary, a multi-party coordination/consensus need that holds even
    for docs. (``needs_consensus`` survives in ``recommend_execution_backend`` for
    the same reason.)

    ``release_surface_file_count`` (KTD1, default 0) is the count of release
    BOOKKEEPING files inside ``file_count`` — plugin.json, marketplace.json,
    CHANGELOGs, version drift-guard pins — that a behavior change must edit in
    lockstep but that carry no functional risk. The size trigger fires on
    FUNCTIONAL surface only (``file_count - release_surface_file_count >= 8``),
    so ``file_count`` keeps its stable meaning (raw touched files) and the default
    of 0 leaves every existing caller byte-identical. The #526 shape (3 functional
    + 6 bookkeeping files) therefore recommends inline; 8+ genuinely functional
    files still trips. A negative ``release_surface_file_count`` raises
    ``ValueError`` — it would inflate the functional count and silently
    over-escalate (fail loud on garbage-in).
    """

    if release_surface_file_count < 0:
        raise ValueError(
            f"release_surface_file_count must be >= 0, got {release_surface_file_count}"
        )
    functional_file_count = file_count - release_surface_file_count
    code_shaped = any(
        (
            functional_file_count >= 8,
            phase_count >= 4,
            has_security,
            has_infra,
            deployment_sensitive,
        )
    )
    return (code_shaped and has_code_surface) or cross_repo


def should_prompt_for_issue(*, has_issue: bool, is_trivial: bool, user_declined: bool) -> bool:
    """Ask whether to file an SDLC issue for non-trivial ad-hoc work."""

    return not has_issue and not is_trivial and not user_declined


def requires_hard_test_gate(change_kinds: Sequence[str]) -> bool:
    """Return whether a change kind requires explicit tests before shipping."""

    risky = {"behavior", "security", "infra", "api", "deployment", "data"}
    return bool(risky.intersection(kind.lower() for kind in change_kinds))


# KTD4: the fixed backend enumeration order the offer always renders, most-capable last. One
# entry since issue #1030 archived both of the others, so the "ladder" is a single rung; the
# tuple stays a tuple because the enumeration contract — every backend gets an entry, never a
# silent drop — is what callers read, not the length.
_ALL_BACKENDS = ("inline",)


def _availability_note(*, workflow_available: bool, workflow_availability_source: str) -> str:
    """Render the cc-workflows-ultracode availability note carrying KTD3 provenance."""

    if workflow_available:
        if workflow_availability_source == "probed":
            return "Workflow tool available (probed at offer time)."
        return "Workflow tool assumed available (asserted — probe before trusting)."
    if workflow_availability_source == "probed":
        return "Workflow tool unavailable (probed at offer time)."
    return "Workflow tool unavailable (asserted — unverified; probe before trusting)."


def _enumerate_backends(
    *,
    recommended: str,
    reachable: list[str],
    workflow_available: bool,
    workflow_availability_source: str,
) -> list[dict[str, str]]:
    """Build the full-enumeration ``backends`` payload (KTD4): every one, never a silent drop.

    Every backend gets a ``{backend, status, note}`` entry. ``status`` is
    ``recommended`` for the winner, ``alternative`` for a reachable non-winner, and
    ``unavailable`` for a backend the host cannot run (only ever
    ``cc-workflows-ultracode`` when ``workflow_available`` is False). The ultracode
    entry always carries the KTD3 provenance note.
    """

    backends: list[dict[str, str]] = []
    for backend in _ALL_BACKENDS:
        if backend == recommended:
            status = "recommended"
        elif backend in reachable:
            status = "alternative"
        else:
            status = "unavailable"

        if backend == "cc-workflows-ultracode":
            note = _availability_note(
                workflow_available=workflow_available,
                workflow_availability_source=workflow_availability_source,
            )
        else:
            note = "Always available (host-portable)."
        backends.append({"backend": backend, "status": status, "note": note})
    return backends


# KTD2: the frozen workflow-shape vocabulary the Workflow tool doc itself names. Any of these
# shapes, requested as a dynamic workflow, is an ultracode job beside broad fan-out and
# adversarial confidence. The tuple is the validated wire contract — an unknown shape raises
# ValueError (fail loud), never a silent inline.
WORKFLOW_SHAPES = ("understand", "design", "research", "review", "migrate")

# KTD3: the two honest provenance values for workflow availability. The recommender is pure
# Python and cannot call ToolSearch, so it records whether the caller PROBED (ToolSearch at
# offer time) or merely ASSERTED (default) the Workflow tool's presence.
WORKFLOW_AVAILABILITY_SOURCES = ("probed", "asserted")


def recommend_execution_backend(
    *,
    file_count: int = 0,
    phase_count: int = 0,
    has_security: bool = False,
    has_infra: bool = False,
    cross_repo: bool = False,
    deployment_sensitive: bool = False,
    needs_consensus: bool = False,
    consensus_is_gated: bool = True,
    broad_independent_fanout: bool = False,
    adversarial_confidence: bool = False,
    has_code_surface: bool = True,
    workflow_available: bool = True,
    workflow_shapes: Sequence[str] = (),
    workflow_availability_source: str = "asserted",
    release_surface_file_count: int = 0,
    ledger: Any = None,
    prior_n: int = 5,
) -> dict[str, object]:
    """Recommend an execution backend, mirroring operator-choice.md section 3.

    Per the operator ruling C5 (issue #840), ``recommend_execution_backend()`` never returns
    ``cc-workflows-ultracode`` with status ``recommended`` under any trigger. Since issue #1030
    archived team-execution, ``inline`` is therefore the only value this function recommends;
    Claude Code Workflows remain available only via explicit invocation or an already-approved
    recorded choice. ``should_offer_team_execution`` is still computed, and its result now selects
    the recorded rationale rather than a different backend.

    GATED vs ADVISORY consensus (R7 keystone). A ``needs_consensus`` signal is
    no longer an unconditional hard-force to team-execution. The governance axis
    (operator-choice section 3.1) splits it:

    * **gated** consensus (``consensus_is_gated=True``, the default) — the verdict
      must BLOCK a merge/deploy and PERSIST as standing evidence. Only
      team-execution offers a reviewer-CONSENSUS gate + named scanners + a guarded
      deploy, so gated consensus is a team-execution job even when small. Default
      True keeps every existing caller's behavior (a bare ``needs_consensus=True``
      still recommends team-execution).
    * **advisory** consensus (``consensus_is_gated=False``) — N throwaway
      in-session votes the operator acts on themselves; nothing is recorded or
      blocks. Leaves the default recommendation as ``inline`` while keeping
      ``team-execution`` and ``cc-workflows-ultracode`` in alternatives.

    ``has_code_surface`` (default True) neutralizes the code-shaped team-execution
    proxies for pure docs/spec/research work (see ``should_offer_team_execution``).

    ``adversarial_confidence`` (default False) and ``broad_independent_fanout``
    (default False) describe shapes for explicit workflow invocation; under C5
    they do not auto-recommend ultracode.

    ``alternatives`` lists every *reachable* backend (capability-gated by
    ``workflow_available``) computed INDEPENDENTLY of which backend won
    precedence, so escalation stays one keystroke (operator-choice section 3.3).

    ``workflow_shapes`` (KTD2, default empty) is a sequence of dynamic-workflow
    shapes drawn from the frozen :data:`WORKFLOW_SHAPES` vocabulary — understand /
    design / research / review / migrate, the shapes the Workflow tool doc names.
    An unknown shape raises ``ValueError`` (fail loud — a silent typo must never
    pass).

    ``workflow_availability_source`` (KTD3, default ``"asserted"``) records the
    provenance of ``workflow_available``: ``"probed"`` (the caller ran a ToolSearch
    probe at offer time) or ``"asserted"`` (assumed, unverified). It is echoed in
    ``workflow_availability`` as ``{available, source}`` and folded into the
    ultracode backend's availability note — an asserted absence renders as
    "unverified; probe before trusting". An unknown source raises ``ValueError``.

    ``release_surface_file_count`` (KTD1, default 0) is threaded to
    ``should_offer_team_execution`` so the size trigger fires on FUNCTIONAL surface
    only (``file_count - release_surface_file_count >= 8``).

    ``backends`` (KTD4) always enumerates ALL backends in a fixed order
    (``inline`` / ``cc-workflows-ultracode``; team-execution was the third until issue
    #1030 archived it) as ordered
    ``{backend, status, note}`` entries with
    ``status in {recommended, alternative, unavailable}`` — never a silent drop.
    The unavailable status only ever attaches to ``cc-workflows-ultracode`` when
    ``workflow_available`` is False; its note carries the KTD3 provenance.
    """

    shapes = tuple(workflow_shapes)
    unknown_shapes = [shape for shape in shapes if shape not in WORKFLOW_SHAPES]
    if unknown_shapes:
        raise ValueError(
            f"unknown workflow shape(s): {', '.join(unknown_shapes)}; "
            f"valid shapes are {', '.join(WORKFLOW_SHAPES)}"
        )
    if workflow_availability_source not in WORKFLOW_AVAILABILITY_SOURCES:
        raise ValueError(
            f"unknown workflow_availability_source: {workflow_availability_source!r}; "
            f"valid sources are {', '.join(WORKFLOW_AVAILABILITY_SOURCES)}"
        )

    # The size/risk and gated-consensus signals used to escalate to team-execution. Issue #1030
    # archived that plugin, and what it provided -- reviewer consensus and named scanners -- is now
    # the lensed code review and the build loop's mechanical baseline, both of which an inline run
    # already performs. So the signals no longer pick a different backend; they are computed and
    # reported, because the rationale a run records is still worth having.
    gated_consensus = needs_consensus and consensus_is_gated
    escalating = (
        should_offer_team_execution(
            file_count=file_count,
            phase_count=phase_count,
            has_security=has_security,
            has_infra=has_infra,
            cross_repo=cross_repo,
            deployment_sensitive=deployment_sensitive,
            has_code_surface=has_code_surface,
            release_surface_file_count=release_surface_file_count,
        )
        or gated_consensus
    )

    recommended = "inline"
    if escalating:
        rationale = (
            "size/risk or consensus signal -> the lensed code review and the mechanical baseline "
            "carry it inline"
        )
    else:
        rationale = "no escalation signal -> the agent does the work itself"

    # One reachable backend since issue #1030. The line that used to drop
    # ``cc-workflows-ultracode`` from this list when the Workflow tool was absent stayed behind
    # after the list shrank, and ``list.remove`` on an absent value raises: every call with
    # ``workflow_available=False`` died with ``ValueError: list.remove(x): x not in list``.
    # ``workflow_available`` is still echoed in the result, because a caller that probed the host
    # is entitled to see what the probe said, but it no longer removes anything.
    reachable = ["inline"]
    alternatives = [backend for backend in reachable if backend != recommended]

    result: dict[str, object] = {
        "recommended": recommended,
        "rationale": rationale,
        "alternatives": alternatives,
        "backends": _enumerate_backends(
            recommended=recommended,
            reachable=reachable,
            workflow_available=workflow_available,
            workflow_availability_source=workflow_availability_source,
        ),
        "workflow_availability": {
            "available": workflow_available,
            "source": workflow_availability_source,
        },
    }
    # #401 U5: surface a run-fact ledger prior ("last N runs averaged X tokens"). Read-only and
    # additive — the ``prior`` key appears ONLY when a ledger is supplied AND has data, so the
    # recommendation is byte-identical to today's for every existing caller (none pass a ledger) and
    # for an empty ledger (the no-data fallback). A ledger implies ``run_ledger`` is already imported
    # (the caller built the RunLedger from it), so this lazy import keeps ``lifecycle_state`` light.
    # A `ledger` argument used to add a prior from the run-fact ledger's spend series. Issue 1030
    # removed that ledger with the ceremony family, so the argument is accepted and ignored rather
    # than changed: every existing caller passes nothing, and the recommendation is unchanged.
    return result


# Orchestration tiers, ordered from the most-capable (dynamic workflows, Claude Code
# only) down to the always-runnable inline baseline. Capability-portable degradation
# (R11) only ever recompiles DOWN this ladder — a host that cannot run dynamic
# workflows falls to the inline/serial baseline. Both of the rungs above inline left with
# issue #1030, so the ladder is one rung and every degradation lands on it. The enum strings
# mirror saga.py ORCHESTRATION_MODES.
ORCHESTRATION_TIERS = ("inline",)

# Only the dynamic-workflow tier needs the Workflow tool. inline runs on any host, so an
# off-host resume only ever downgrades AWAY from this one tier.
_HOST_DEPENDENT_TIERS = frozenset({"cc-workflows-ultracode"})


def recheck_orchestration_capability(
    *,
    orchestration_mode: str,
    workflow_available: bool,
    fallback_mode: str = "inline",
) -> dict[str, object]:
    """Re-check host capability on resume and recompile ONLY the orchestration tier (R11).

    Capability-portable degradation. Every authored plan carries a runnable inline/serial
    baseline; the dynamic-workflow layer applies only on a capable host. On an off-host
    resume the Workflow tool is re-checked here; if the chosen tier is host-dependent
    (``cc-workflows-ultracode``) and the host cannot run it, this recompiles ONLY the
    orchestration tier DOWN the :data:`ORCHESTRATION_TIERS` ladder. The unit specs and
    per-unit ``{model, effort}`` tiers are NOT touched here — they survive the recompile
    untouched (that preservation is the emitter's job; this function decides the new
    orchestration tier and the human-readable downgrade note).

    ``fallback_mode`` is the preferred landing tier when a downgrade is needed (default
    ``inline``, which since issue #1030 is also the only rung there is).
    If the caller asks for a fallback that is itself host-dependent or unknown, this floors
    to ``inline`` — the always-runnable baseline — rather than picking another tier that
    might also be unavailable.

    AE3 contract — this NEVER errors and NEVER silently runs nothing:

    * **Host CAN run the chosen tier** (``workflow_available`` True, or the mode is not
      host-dependent): ``downgraded=False``, ``to == orchestration_mode`` — run as authored.
    * **Host CANNOT run the chosen tier**: ``downgraded=True``, ``to`` is a runnable tier
      (never empty), and ``note`` is a one-line, surfaceable downgrade message.
    * **Unknown / empty mode**: treated as the inline baseline — ``downgraded=False``,
      ``to == "inline"`` — never an exception, never an empty target.

    Returns a JSON-serializable dict::

        {
          "downgraded": bool,
          "from": <the mode as resumed>,       # echoed input
          "to": <the runnable orchestration tier>,   # NEVER empty
          "note": <one-line downgrade note, or ""> ,
          "workflow_available": bool,           # echoed capability probe
        }
    """

    resumed = orchestration_mode or "inline"

    # An unknown stored mode is floored to the inline baseline rather than trusted — a
    # host that cannot identify the tier still runs SOMETHING (AE3: never run nothing).
    if resumed not in ORCHESTRATION_TIERS:
        return {
            "downgraded": False,
            "from": resumed,
            "to": "inline",
            "note": "",
            "workflow_available": workflow_available,
        }

    host_can_run = workflow_available or resumed not in _HOST_DEPENDENT_TIERS
    if host_can_run:
        # The authored tier is runnable here — no downgrade, run as authored.
        return {
            "downgraded": False,
            "from": resumed,
            "to": resumed,
            "note": "",
            "workflow_available": workflow_available,
        }

    # Off-host: recompile the orchestration tier DOWN. Prefer the requested fallback, but
    # only if it is itself a runnable (host-portable, known) tier; otherwise floor to
    # inline — never land on another host-dependent tier that might also be unavailable.
    if fallback_mode in ORCHESTRATION_TIERS and fallback_mode not in _HOST_DEPENDENT_TIERS:
        target = fallback_mode
    else:
        target = "inline"

    note = (
        f"Downgraded orchestration {resumed} -> {target}: the Workflow tool is "
        f"unavailable on this host. Unit specs and per-unit tiers preserved; only "
        f"the orchestration tier recompiled."
    )
    return {
        "downgraded": True,
        "from": resumed,
        "to": target,
        "note": note,
        "workflow_available": workflow_available,
    }


def _assert_known_tier(model: str, effort: str, *, source: str) -> None:
    """Refuse a model, an effort, or a COMBINATION the shared tier vocabulary does not carry.

    The vocabulary is ``fleet_commons.tier_palette``'s ``MODELS`` / ``EFFORTS``, reached through the
    build-time Fleet Core bundle, so there is one authority rather than a second copy here.

    Membership in each list separately is not enough, and checking only that was the gap: every
    effort is a legal effort and every model a legal model, but not every pairing runs. ``haiku``
    tops out below ``xhigh``, so a plan naming that model at that effort passed two membership
    checks and named a tier no host can execute. The sibling path could never produce it -- an
    overlay entry goes through ``fleet_commons.staffing.validate_tier`` against the registry, and a registry
    default is runnable by construction -- so an explicit tier was the one door into this function
    that skipped the check its own alternative enforces.
    """
    from pathlib import Path as _Path  # noqa: PLC0415

    _scripts_dir = _Path(__file__).resolve().parent
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    import bundled_fleet  # noqa: PLC0415

    palette = bundled_fleet.load("tier_palette")
    if model not in palette.MODELS:
        raise ValueError(f"{source} model {model!r} is not one of {list(palette.MODELS)}")
    if effort not in palette.EFFORTS:
        raise ValueError(f"{source} effort {effort!r} is not one of {list(palette.EFFORTS)}")
    if not palette.supports_effort(model, effort):
        raise ValueError(
            f"{source} names {model!r} at {effort!r}, which that model cannot run; its ceiling is "
            f"{palette.effort_ceiling(model)!r}"
        )


def resolve_build_unit_tier(
    *,
    plan_tier: dict[str, str] | None = None,
    work_shape: str | None = None,
) -> dict[str, str]:
    """Resolve the tier for a directly launched build unit (WK3 #929).

    Precedence mirrors the shared tier chain: an explicit ``plan_tier`` wins; otherwise the work
    shape (default ``mechanical`` for an undeclared unit per
    ``references/execution-strategy.md``) is resolved through
    :mod:`fleet_commons.tier_resolver`, never a literal at the spawn site. The ``tier_defaults``
    rung that sat in front of it was removed with issue 1030.

    **An explicit tier is validated against the same vocabulary its sibling path resolves from.**
    It used to be returned after a key-presence check alone, so a plan naming ``{"model": "gpt-5"}``
    or ``{"effort": "maximum"}`` passed straight through to a spawn while the shape path could only
    ever produce a registry value. "Explicit wins" is about PRECEDENCE, not about skipping the
    check that the value exists.

    **There is no host or session input at all**, which is what makes inheritance impossible: the
    function cannot consult a host tier it is never given and never reads from the environment. An
    earlier form took a ``host_tier`` argument and discarded it so a test could "prove"
    non-inheritance — a parameter whose only purpose was to be ignored, which made that test
    unfailable by construction.
    """
    if plan_tier is not None:
        if "model" not in plan_tier or "effort" not in plan_tier:
            raise ValueError(f"plan_tier must contain model and effort, got {plan_tier!r}")
        model = str(plan_tier["model"])
        effort = str(plan_tier["effort"])
        _assert_known_tier(model, effort, source="plan_tier")
        return {"model": model, "effort": effort}
    shape = work_shape or "mechanical"
    # The repo-overlay chain in `tier_defaults.py` was removed by issue 1030; issue 1021 had already
    # moved the tier policy into fleet-core's staffing component, which is the single source now.
    from pathlib import Path as _Path  # noqa: PLC0415  (lazy to avoid top-level side effects)

    _scripts_dir = _Path(__file__).resolve().parent
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    import bundled_fleet  # noqa: PLC0415

    resolver = bundled_fleet.load("tier_resolver")
    resolved = resolver.resolve(None, shape)
    return {"model": resolved.model, "effort": resolved.effort}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    normalize = subparsers.add_parser("normalize", help="normalize a user-facing destination label")
    normalize.add_argument("destination")

    backend = subparsers.add_parser(
        "recommend-backend", help="recommend an execution backend as JSON"
    )
    backend.add_argument("--file-count", type=int, default=0)
    backend.add_argument("--phase-count", type=int, default=0)
    backend.add_argument("--has-security", action="store_true")
    backend.add_argument("--has-infra", action="store_true")
    backend.add_argument("--cross-repo", action="store_true")
    backend.add_argument("--deployment-sensitive", action="store_true")
    backend.add_argument("--needs-consensus", action="store_true")
    backend.add_argument(
        "--advisory-consensus",
        action="store_true",
        help="treat the consensus signal as ADVISORY (throwaway in-session votes; default remains inline)",
    )
    backend.add_argument(
        "--broad-fanout",
        action="store_true",
        help="indicate broad fan-out shape (recommends inline; does not change recommended under C5)",
    )
    backend.add_argument(
        "--adversarial-confidence",
        action="store_true",
        help="indicate adversarial-confidence shape (recommends inline; does not change recommended under C5)",
    )
    backend.add_argument("--no-code-surface", action="store_true")
    backend.add_argument("--no-workflow", action="store_true")
    backend.add_argument(
        "--release-surface-file-count",
        type=int,
        default=0,
        help="count of release-bookkeeping files inside --file-count to subtract from the size trigger (KTD1)",
    )
    backend.add_argument(
        "--workflow-shape",
        action="append",
        dest="workflow_shapes",
        default=[],
        choices=WORKFLOW_SHAPES,
        metavar="SHAPE",
        help=f"repeatable dynamic-workflow shape ({'|'.join(WORKFLOW_SHAPES)}) for explicit invocation (KTD2)",
    )
    backend.add_argument(
        "--workflow-availability-source",
        choices=WORKFLOW_AVAILABILITY_SOURCES,
        default="asserted",
        help="provenance of workflow availability: probed (ToolSearch) or asserted (default) (KTD3)",
    )

    build_tier = subparsers.add_parser(
        "resolve-build-unit-tier",
        help="resolve a directly launched build unit's {model, effort} as JSON (#929)",
    )
    build_tier.add_argument("--plan-model", help="explicit plan tier model; requires --plan-effort")
    build_tier.add_argument(
        "--plan-effort", help="explicit plan tier effort; requires --plan-model"
    )
    build_tier.add_argument(
        "--work-shape",
        help="work shape to resolve when no explicit plan tier is given (default: mechanical)",
    )

    recheck = subparsers.add_parser(
        "recheck-capability",
        help="re-check host capability on resume and recompile the orchestration tier (R11)",
    )
    recheck.add_argument(
        "--orchestration-mode",
        default="inline",
        help=(
            "the tier as resumed; a saga written before issue #1030 may still carry "
            "cc-workflows-ultracode or team-execution, and either is floored to inline"
        ),
    )
    recheck.add_argument(
        "--no-workflow",
        action="store_true",
        help="the Workflow tool is unavailable on this host (off-host resume)",
    )
    recheck.add_argument(
        "--fallback-mode",
        default="inline",
        help="preferred landing tier on a downgrade (default: inline, the only tier left)",
    )

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "normalize":
        print(normalize_destination(args.destination))
        return 0
    if args.command == "recommend-backend":
        result = recommend_execution_backend(
            file_count=args.file_count,
            phase_count=args.phase_count,
            has_security=args.has_security,
            has_infra=args.has_infra,
            cross_repo=args.cross_repo,
            deployment_sensitive=args.deployment_sensitive,
            needs_consensus=args.needs_consensus,
            consensus_is_gated=not args.advisory_consensus,
            broad_independent_fanout=args.broad_fanout,
            adversarial_confidence=args.adversarial_confidence,
            has_code_surface=not args.no_code_surface,
            workflow_available=not args.no_workflow,
            workflow_shapes=args.workflow_shapes,
            workflow_availability_source=args.workflow_availability_source,
            release_surface_file_count=args.release_surface_file_count,
        )
        print(json.dumps(result))
        return 0
    if args.command == "resolve-build-unit-tier":
        # The fleet's CLI contract for a bad input is a JSON `error` on stderr and exit 2, not a
        # traceback and not a bare SystemExit string. This subcommand is called from a skill
        # document by an agent that reads stdout as JSON: a traceback there is a parse failure with
        # no diagnosis in it, and `raise SystemExit(...)` exits 1, which the fleet uses for a
        # genuine failure rather than a rejected argument.
        if bool(args.plan_model) != bool(args.plan_effort):
            print(
                json.dumps({"error": "--plan-model and --plan-effort must be given together"}),
                file=sys.stderr,
            )
            return 2
        plan_tier = (
            {"model": args.plan_model, "effort": args.plan_effort} if args.plan_model else None
        )
        try:
            resolved = resolve_build_unit_tier(plan_tier=plan_tier, work_shape=args.work_shape)
        except (ValueError, KeyError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(resolved))
        return 0
    if args.command == "recheck-capability":
        result = recheck_orchestration_capability(
            orchestration_mode=args.orchestration_mode,
            workflow_available=not args.no_workflow,
            fallback_mode=args.fallback_mode,
        )
        print(json.dumps(result))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
