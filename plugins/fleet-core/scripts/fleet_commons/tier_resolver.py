#!/usr/bin/env python3
"""Dispatch-time tier resolver — maps a work shape to a ``{model, effort}`` tier (#362).

One callable seam for tier decisions that today live scattered across team-execution's 25
hardcoded agent ``model:`` literals, the prose-only heuristic table at
``plugins/saga/skills/plan/SKILL.md:298-304``, and assorted per-call literals. ``resolve()``
reads defaults from the ``work_shapes`` block of the machine-readable ``staffing.json`` registry
(U1, merged there by issue #1021) and never hardcodes a heuristic in code.

Imports ``MODELS``, ``EFFORTS``, ``model_rank``, ``effort_rank`` from ``tier_palette`` via
``fleet_commons_shim`` — never re-declaring the tuples (KTD1/KTD2).

``work_shape`` is the primary registry key; ``role_kind`` is an optional coarse refiner reserved
for a future v2 (unused today — v1 resolves purely from ``work_shape``). A ``role-tier:``
frontmatter value (KTD7) is a small alias that maps onto a ``work_shape`` registry row before
lookup, so migrated team-execution agents resolve through the same registry as everything else.

``resolve_for_runtime`` is a sibling, not a replacement: it keys on execution-class names from
``staffing.json`` and returns a runtime-owned
``{model, effort, fallbacks, workspace_boundary, effort_application}``.
``adapt_runtime_argv`` is the only place a resolved pair becomes vendor CLI flags.
``effort_application`` is the directive for *how* the collapsed effort is applied (launch
argv, or an in-session command). Confirming the directive took is U4 (session lifecycle,
``pane.output_matched``), not this unit. ``resolve()``'s signature and meaning are unchanged.

``cheaper_fallback`` steps exactly one rung down the ordered ladder (KTD3, ``{#tier-vocab-ordering}``):
weaken the model one ``MODELS`` rung first; once already at the weakest model, drop effort one
``EFFORTS`` rung instead. At the ladder floor (weakest model, lowest effort) the fallback equals
the resolved tier — a no-op floor, not an error.

The expensive-tier gate (KTD4, ``{#operator-choice-framework}``) sets ``needs_confirm`` when the
resolved tier is the strongest model (``fable``) or the highest effort (``xhigh``); the gate
itself is doc/CLI-driven and runtime-injected by the caller, not enforced here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_sibling(name: str):
    """Load ``<this file's directory>/<name>.py``.

    Portable stand-in for ``fleet_commons_shim.load``. The shim's resolution
    ladder is specific to a Claude Code plugin install. This catalog bundles
    modules at build time, and a module is always read from the directory that
    holds this file, so the same source works in ``fleet_commons/`` and in any
    generated ``_bundled/`` copy.
    """
    import importlib.util
    import sys
    from pathlib import Path

    sibling_dir = Path(__file__).resolve().parent
    cache_key = f"_fleet_commons_{name}@{sibling_dir}"
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached
    module_path = sibling_dir / f"{name}.py"
    if not module_path.is_file():
        raise RuntimeError(f"fleet-commons: module {name!r} not found at {module_path}")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internal failure
        raise RuntimeError(f"fleet-commons: importlib could not load {module_path}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = loaded
    try:
        spec.loader.exec_module(loaded)
    except BaseException:
        sys.modules.pop(cache_key, None)
        raise
    return loaded


_tier_palette = _load_sibling("tier_palette")
MODELS: tuple[str, ...] = _tier_palette.MODELS
EFFORTS: tuple[str, ...] = _tier_palette.EFFORTS
model_rank = _tier_palette.model_rank
effort_rank = _tier_palette.effort_rank

STAFFING_PATH = Path(__file__).resolve().parent / "staffing.json"
# Retained names: both blocks now live in the one staffing registry (issue #1021).
TIER_POLICY_PATH = STAFFING_PATH

# The strongest model / highest effort rungs (KTD4): resolving to either gates on operator confirm.
_EXPENSIVE_MODELS = frozenset({MODELS[0]})
_EXPENSIVE_EFFORTS = frozenset({EFFORTS[-1]})

# KTD7: role-tier is a small agent-facing vocabulary mapping onto work-shape registry keys.
# Migrating team-execution's 25 agents onto these preserves each agent's pre-migration model
# (adversarial-review->opus, contract-test->sonnet, mechanical-scan->haiku).
ROLE_TIER_ALIASES: dict[str, str] = {
    "adversarial-review": "judgment",
    "contract-test": "mechanical",
    "mechanical-scan": "purely-mechanical",
}

MODELS_JSON_PATH = STAFFING_PATH


class TierResolverError(ValueError):
    """Raised for an unresolvable work_shape/role_kind or an invalid override/ceiling."""


def _vendor_palette() -> dict[str, Any]:
    """Read the per-vendor palette from ``staffing.json`` (issue #1021).

    The palette used to be five module-level literals here. It is data now because the card
    asks for one data file and because a second table naming a vendor's models is exactly the
    drift ``tests/test_tier_vocab_single_source.py`` exists to prevent. The reading interface —
    the functions below — is unchanged.
    """
    document: Any = json.loads(STAFFING_PATH.read_text(encoding="utf-8"))
    block = document.get("vendors")
    if not isinstance(block, dict) or not block:
        raise TierResolverError("staffing.json is missing a non-empty vendors object")
    return block


_VENDORS: dict[str, Any] = _vendor_palette()

# Only the vendors whose launch arguments have been verified on a live host are runtimes this
# resolver will translate for. ``opencode`` is in the palette with ``runtime_supported`` false
# and its reason recorded in the data, so it is visible without being silently launchable.
SUPPORTED_RUNTIMES: tuple[str, ...] = tuple(
    name for name, row in _VENDORS.items() if row.get("runtime_supported")
)
STRONGEST_SUPPORTED = "strongest-supported"

# Runtime-owned translation of the portable execution_classes model names.
# Rank correspondence: sol = strongest, terra = default worker, 5.5 = older fallback.
# Verified on this host 2026-08-13 from each CLI's own catalog/config, not inferred
# across vendors. Two-rung catalogs share the weaker id for terra and 5.5.
_RUNTIME_MODELS: dict[str, dict[str, str]] = {
    name: dict(row["models"]) for name, row in _VENDORS.items() if row.get("runtime_supported")
}

# Per-vendor accepted effort rungs, verified on this host 2026-08-13.
# These are the values collapse may emit. See DECISIONS {#effort-collapse-max}.
_RUNTIME_ACCEPTED_EFFORTS: dict[str, tuple[str, ...]] = {
    name: tuple(row["accepted_efforts"])
    for name, row in _VENDORS.items()
    if row.get("runtime_supported")
}

# Explicit effort-collapse policy. A vendor with no row passes the scalar through.
# Muse accepts `ultra` on the CLI; it is never emitted (not a leaf scalar).
# See DECISIONS {#effort-collapse-max}.
_EFFORT_COLLAPSE: dict[str, dict[str, str]] = {
    name: dict(row["effort_collapse"])
    for name, row in _VENDORS.items()
    if row.get("runtime_supported") and row.get("effort_collapse")
}

# How the collapsed effort is applied. Verified 2026-08-13 from each runtime's
# own surface, not inferred. Four runtimes support both a launch flag and an
# in-session /effort; this resolver chooses argv so the first turn already uses
# the requested rung. Qwen has no launch flag (qwen --effort is "Unknown
# argument"), so it is the only in_session runtime. Confirming the directive
# took is U4 (session lifecycle, pane.output_matched), not this unit.
# See DECISIONS {#effort-collapse-max}.
_EFFORT_APPLICATION_MODE: dict[str, str] = {
    name: str(row["effort_application"])
    for name, row in _VENDORS.items()
    if row.get("runtime_supported")
}


@dataclass(frozen=True)
class Resolution:
    model: str
    effort: str
    because: str
    cheaper_fallback: tuple[str, str]
    needs_confirm: bool


@dataclass(frozen=True)
class RuntimeResolution:
    """Runtime-owned resolution of one execution class.

    ``fallbacks`` preserves declared order after translating each candidate through
    the same runtime policy as the preferred pair. ``workspace_boundary`` is copied
    from the class and is not runtime-specific. ``effort_application`` is the
    executable directive (``{"mode": "argv"}`` or
    ``{"mode": "in_session", "command": "/effort <rung>"}``). This unit produces
    the directive; U4 executes it and confirms it took.
    """

    model: str
    effort: str
    fallbacks: tuple[dict[str, str], ...]
    workspace_boundary: str
    effort_application: dict[str, str]


def load_policy(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load the work-shape -> tier registry (the ``work_shapes`` block of ``staffing.json``).

    Fails loud when the block is absent rather than returning the whole document: a
    caller that silently received the staffing registry would treat ``models`` and
    ``vendors`` as work shapes.
    """
    policy_path = path if path is not None else STAFFING_PATH
    document: Any = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise TierResolverError(f"staffing registry at {policy_path} must be a JSON object")
    data = document.get("work_shapes")
    if not isinstance(data, dict) or not data:
        raise TierResolverError(
            f"staffing registry at {policy_path} is missing a non-empty 'work_shapes' object"
        )
    return data


def canonical_work_shape(work_shape: str) -> str:
    """Map a ``role-tier:`` alias (KTD7) onto its registry work-shape key, else pass through.

    Public since issue #1021: ``fleet_commons.staffing`` checks work-shape membership before
    delegating here, so it needs the same alias vocabulary rather than a second copy of it.
    """
    return ROLE_TIER_ALIASES.get(work_shape, work_shape)


# Retained for any caller of the former private name.
_canonical_work_shape = canonical_work_shape


def cheaper_fallback(model: str, effort: str) -> tuple[str, str]:
    """One rung down the ladder (KTD3): weaken model first, then effort; floor is a no-op."""
    rung = model_rank(model)
    if rung < len(MODELS) - 1:
        return MODELS[rung + 1], effort
    tier = effort_rank(effort)
    if tier > 0:
        return model, EFFORTS[tier - 1]
    return model, effort


def resolve(
    role_kind: str | None,
    work_shape: str,
    envelope_ceiling: str | None = None,
    operator_override: dict[str, str] | None = None,
    *,
    policy: dict[str, dict[str, str]] | None = None,
) -> Resolution:
    """Resolve ``(role_kind, work_shape, envelope_ceiling, operator_override)`` to a tier.

    ``role_kind`` is accepted and validated shape-wise but unused in v1 (reserved coarse
    refiner). ``work_shape`` (after resolving any ``role-tier:`` alias) is the registry lookup
    key. ``envelope_ceiling``, when supplied, clamps the resolved model to no stronger than the
    ceiling (forward-compat for #366's spend envelope; ``None`` is honored as "no ceiling", never
    an error). ``operator_override`` replaces ``model``/``effort`` outright when supplied.
    """
    if role_kind is not None and not isinstance(role_kind, str):
        raise TierResolverError("role_kind must be a string or None")

    registry = policy if policy is not None else load_policy()
    key = _canonical_work_shape(work_shape)
    if key not in registry:
        raise TierResolverError(
            f"unknown work_shape {work_shape!r}; expected one of {sorted(registry)} "
            f"or a role-tier alias in {sorted(ROLE_TIER_ALIASES)}"
        )

    row = registry[key]
    model = str(row["default_model"])
    effort = str(row["default_effort"])
    because = str(row["rationale"])

    if operator_override:
        override_model = operator_override.get("model")
        override_effort = operator_override.get("effort")
        if override_model is not None:
            if override_model not in MODELS:
                raise TierResolverError(
                    f"operator_override model {override_model!r} not in {MODELS}"
                )
            model = override_model
        if override_effort is not None:
            if override_effort not in EFFORTS:
                raise TierResolverError(
                    f"operator_override effort {override_effort!r} not in {EFFORTS}"
                )
            effort = override_effort
        because = f"operator override ({model}/{effort}) of default: {because}"

    if envelope_ceiling is not None:
        if envelope_ceiling not in MODELS:
            raise TierResolverError(f"envelope_ceiling {envelope_ceiling!r} not in {MODELS}")
        if model_rank(model) < model_rank(envelope_ceiling):
            because = f"{because} (clamped to envelope_ceiling={envelope_ceiling})"
            model = envelope_ceiling

    needs_confirm = model in _EXPENSIVE_MODELS or effort in _EXPENSIVE_EFFORTS

    return Resolution(
        model=model,
        effort=effort,
        because=because,
        cheaper_fallback=cheaper_fallback(model, effort),
        needs_confirm=needs_confirm,
    )


def _load_models_registry(path: Path | None = None) -> dict[str, Any]:
    """Load ``staffing.json``; used by the execution-class sibling, not by ``resolve()``."""
    registry_path = path if path is not None else MODELS_JSON_PATH
    data: Any = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TierResolverError(f"models registry at {registry_path} must be a JSON object")
    return data


def _execution_classes(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    data = registry if registry is not None else _load_models_registry()
    classes = data.get("execution_classes")
    if not isinstance(classes, dict) or not classes:
        raise TierResolverError("staffing.json is missing a non-empty execution_classes object")
    return classes


def _translate_model(runtime: str, model: str) -> str:
    mapping = _RUNTIME_MODELS.get(runtime)
    if mapping is None:
        raise TierResolverError(
            f"unknown runtime {runtime!r}; expected one of {list(SUPPORTED_RUNTIMES)}"
        )
    try:
        return mapping[model]
    except KeyError:
        raise TierResolverError(
            f"runtime {runtime!r} has no mapping for portable model {model!r}"
        ) from None


def collapse_effort_for_runtime(runtime: str, effort: str) -> str:
    """Map an authoritative scalar (or ``strongest-supported``) onto a vendor CLI rung.

    This is the documented collapse. It is not a clamp buried in a lookup: an effort
    the vendor cannot represent becomes that vendor's strongest accepted rung, named
    in ``_EFFORT_COLLAPSE``, or raises if even that rung is absent.
    """
    if runtime not in _RUNTIME_ACCEPTED_EFFORTS:
        raise TierResolverError(
            f"unknown runtime {runtime!r}; expected one of {list(SUPPORTED_RUNTIMES)}"
        )
    accepted = _RUNTIME_ACCEPTED_EFFORTS[runtime]
    if effort == STRONGEST_SUPPORTED:
        return accepted[-1]
    collapsed = _EFFORT_COLLAPSE.get(runtime, {}).get(effort, effort)
    if collapsed not in accepted:
        raise TierResolverError(
            f"runtime {runtime!r} cannot represent effort {effort!r} "
            f"(collapsed to {collapsed!r}; accepted {accepted})"
        )
    return collapsed


def _effort_application(runtime: str, effort: str) -> dict[str, str]:
    """Return the executable effort directive for ``runtime`` at collapsed ``effort``.

    Confirming the directive took is U4, not this unit.
    """
    mode = _EFFORT_APPLICATION_MODE.get(runtime)
    if mode is None:
        raise TierResolverError(
            f"unknown runtime {runtime!r}; expected one of {list(SUPPORTED_RUNTIMES)}"
        )
    if mode == "in_session":
        # The command template lives in the data beside the mode (#1021). Reading it rather than
        # hardcoding the string is what stops a future edit to staffing.json doing nothing.
        template = str(_VENDORS[runtime].get("effort_command", "/effort {effort}"))
        return {"mode": "in_session", "command": template.format(effort=effort)}
    return {"mode": "argv"}


def resolve_for_runtime(work_shape: str, runtime: str) -> RuntimeResolution:
    """Resolve an execution class to a runtime-owned ``{model, effort, fallbacks}``.

    ``work_shape`` is an ``execution_classes`` name (the portable vocabulary).
    Existing ``work_shapes`` rows stay on ``resolve()``. Unknown class
    or runtime raises; nothing defaults.
    """
    if runtime not in SUPPORTED_RUNTIMES:
        raise TierResolverError(
            f"unknown runtime {runtime!r}; expected one of {list(SUPPORTED_RUNTIMES)}"
        )
    classes = _execution_classes()
    if work_shape not in classes:
        raise TierResolverError(
            f"unknown work_shape {work_shape!r}; expected one of {sorted(classes)}"
        )
    row = classes[work_shape]
    if not isinstance(row, dict):
        raise TierResolverError(f"execution class {work_shape!r} must be an object")
    preferred = row.get("preferred")
    if not isinstance(preferred, dict) or "model" not in preferred or "effort" not in preferred:
        raise TierResolverError(f"execution class {work_shape!r} is missing preferred model/effort")
    fallbacks_raw = row.get("fallbacks")
    if not isinstance(fallbacks_raw, list):
        raise TierResolverError(f"execution class {work_shape!r} fallbacks must be a list")
    workspace_boundary = row.get("workspace_boundary")
    if not isinstance(workspace_boundary, str) or not workspace_boundary:
        raise TierResolverError(f"execution class {work_shape!r} is missing workspace_boundary")

    preferred_effort = collapse_effort_for_runtime(runtime, str(preferred["effort"]))
    translated: list[dict[str, str]] = []
    for index, candidate in enumerate(fallbacks_raw):
        if not isinstance(candidate, dict) or "model" not in candidate or "effort" not in candidate:
            raise TierResolverError(
                f"execution class {work_shape!r} fallbacks[{index}] must have model and effort"
            )
        translated.append(
            {
                "model": _translate_model(runtime, str(candidate["model"])),
                "effort": collapse_effort_for_runtime(runtime, str(candidate["effort"])),
            }
        )

    return RuntimeResolution(
        model=_translate_model(runtime, str(preferred["model"])),
        effort=preferred_effort,
        fallbacks=tuple(translated),
        workspace_boundary=workspace_boundary,
        effort_application=_effort_application(runtime, preferred_effort),
    )


def adapt_runtime_argv(runtime: str, model: str, effort: str) -> list[str]:
    """Map a resolved ``{model, effort}`` to the vendor CLI's real flags.

    The ``agent`` wrapper passes tool arguments through unchanged, so this adapter
    is the only thing standing between a resolved tier and a malformed command line.
    Flags were verified on this host 2026-08-13 from each binary's own ``--help``.
    Qwen effort is not a launch flag; the caller executes
    ``RuntimeResolution.effort_application`` after launch. Confirming either
    path took is U4, not this unit.
    """
    if runtime not in SUPPORTED_RUNTIMES:
        raise TierResolverError(
            f"unknown runtime {runtime!r}; expected one of {list(SUPPORTED_RUNTIMES)}"
        )
    safe_effort = collapse_effort_for_runtime(runtime, effort)
    if runtime == "claude":
        return ["--model", model, "--effort", safe_effort]
    if runtime == "grok":
        return ["--model", model, "--reasoning-effort", safe_effort]
    if runtime == "muse":
        return ["--model", model, "--reasoning-effort", safe_effort]
    if runtime == "agy":
        return ["--model", model, "--effort", safe_effort]
    if runtime == "qwen":
        return ["--model", model]
    return ["--model", model, "-c", f"model_reasoning_effort={safe_effort}"]


def _cli_resolve(args: argparse.Namespace) -> int:
    operator_override: dict[str, str] | None = None
    if args.override_model or args.override_effort:
        operator_override = {}
        if args.override_model:
            operator_override["model"] = args.override_model
        if args.override_effort:
            operator_override["effort"] = args.override_effort

    try:
        result = resolve(
            args.role_kind,
            args.work_shape,
            envelope_ceiling=args.envelope_ceiling,
            operator_override=operator_override,
        )
    except TierResolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = {
        "model": result.model,
        "effort": result.effort,
        "because": result.because,
        "cheaper_fallback": {
            "model": result.cheaper_fallback[0],
            "effort": result.cheaper_fallback[1],
        },
        "needs_confirm": result.needs_confirm,
    }
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tier_resolver")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser(
        "resolve", help="Resolve a work_shape (or role-tier alias) to a {model, effort} tier"
    )
    resolve_parser.add_argument(
        "--role-kind", default=None, help="Reserved coarse refiner (v1: unused)"
    )
    resolve_parser.add_argument(
        "--work-shape", required=True, help="Registry key or role-tier alias"
    )
    resolve_parser.add_argument(
        "--envelope-ceiling", default=None, help="Clamp the resolved model to no stronger than this"
    )
    resolve_parser.add_argument("--override-model", default=None, help="Operator model override")
    resolve_parser.add_argument("--override-effort", default=None, help="Operator effort override")
    resolve_parser.set_defaults(func=_cli_resolve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
