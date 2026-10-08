#!/usr/bin/env python3
"""The one staffing resolver — "role or work shape, and for review the lens, to a tier" (#1021).

Choosing a subagent's model, a workflow unit's tier, and a herdr role's vendor and model are
one decision whose inputs used to sit in four places: the work-shape tier policy and model
palette here in fleet-core, the per-repository tier overlay saga's ``tier_defaults.py`` read, the
capability ratings and trust tiers in saga's ``references/engine-registry.yaml``, and the
software-development-lifecycle repository's ledger of which executor has been qualified against
which review lens. ``staffing.json`` now carries all four, and this module is the only thing that
reads them for a staffing answer.

It answers three resolve questions:

* ``resolve_shape(work_shape)`` — the tier for a work shape, through every tier layer.
* ``resolve_role(role)`` — the vendor, model and effort for a named role.
* ``resolve_role(role, lens=...)`` — the same, plus the lens's qualification status.

**Tier precedence is written once, in** :func:`resolve_shape` **and** :data:`TIER_PRECEDENCE`.
The operator's answer wins; then the repository overlay; then a Jev-applied raise recorded in the
run record; then the work shape's registry default. Admission, ``/plan`` and ``/work`` all reach a
tier through this module (issue #93), so no skill or caller restates that order.

It composes ``tier_palette`` and ``tier_resolver`` rather than replacing them (KTD2), and it
dispatches nothing: every call returns a :class:`StaffingDecision` describing the answer, the
layer that supplied it, and any advisory suggestion the caller passed in. Persisting that record
belongs to the run record (KTD8), not here.

``resolve_shape`` and ``resolve_role`` never call out, so a staffing question can never depend on
a service being reachable. The tier judgment (issue #96) is a separate, explicit consult:
``consult_tier_suggestions`` asks the ``tier`` judgment verb, in one request for a whole batch of
units, whether each unit needs a weaker, the same, or a stronger tier than its default, given the
real issue and the unit. ``classify_judgment`` turns each answer into a band. Only a raise at the
verb's automatic floor may apply without the operator: one step, effort first, never to the
strongest model, never over an operator-set tier. The caller records that raise in the run record,
and ``resolve_shape`` honors it as its ``jev-raise`` layer. A suggestion to lower a tier is never
applied. ``INFIQUETRA_TYPESAFE_TIERING=off`` switches the consult off before anything is loaded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
_tier_resolver = _load_sibling("tier_resolver")

MODELS: tuple[str, ...] = _tier_palette.MODELS
EFFORTS: tuple[str, ...] = _tier_palette.EFFORTS

STAFFING_PATH = Path(__file__).resolve().parent / "staffing.json"

#: The committed-per-repository tier overlay, relative to the repository root. In this
#: repository ``.saga/`` is gitignored, so the file is local to one checkout; the resolver
#: reads a path and does not care whether git tracks it.
OVERLAY_PATH = Path(".saga/tier-defaults.json")

#: The software-development-lifecycle checkout holding the qualification ledger, resolved the
#: way ``plugins/mission-control/scripts/sdlc_manager.py`` resolves it: the environment variable
#: first, then the default checkout (KTD4).
SDLC_PATH_ENV = "INFIQUETRA_SDLC_PATH"
DEFAULT_SDLC_PATH = Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"
LEDGER_RELATIVE_PATH = Path("config/executor-verifications.json")
LENS_CATALOGUE_RELATIVE_PATH = Path("config/lens-catalogue.json")

#: The outcome for a lens that establishes no threshold — because no executor is qualified for
#: it, because the catalogue marks it unscorable, or because the ledger could not be read. The
#: lens still reports findings; it just cannot set a bar (R12, R13).
DOCUMENTED_POLICY = "documented-policy"
QUALIFIED = "qualified"

#: The lens name could not be checked, because the catalogue that defines the vocabulary was not
#: readable. Distinct from ``documented-policy`` on purpose: that one means "this lens establishes
#: no threshold", a legitimate answer, and folding an unverifiable name into it let a typo pass as
#: a real lens at exit zero. A caller seeing this has a name it cannot trust, not a policy outcome.
LENS_UNVERIFIED = "lens-unverified"

#: Rating strength, strongest first. The registry's own three-value vocabulary.
RATINGS: tuple[str, ...] = ("STRONG", "MODERATE", "WEAK")

DEFAULT_VENDOR = "claude"

#: The tier layers :func:`resolve_shape` consults, first match wins. Each name is also the
#: ``source`` a decision reports. ``operator`` is the operator's explicit answer (today the tier a
#: plan unit records after the operator confirmed it; admission's ``staffing_overrides`` answer is
#: stored as-is and does not pass through here yet); ``overlay`` is the
#: repository's ``.saga/tier-defaults.json``; ``jev-raise`` is a raise the tier judgment applied
#: and the run record keeps (written by staffing U4, issue #96); ``policy`` is the work shape's
#: registry default. This tuple and ``resolve_shape`` are the only places the order is written.
TIER_PRECEDENCE: tuple[str, ...] = ("operator", "overlay", "jev-raise", "policy")

#: The role whose work shape an undeclared build unit runs at. ``/work`` derives its default from
#: this role's row rather than carrying a second work-shape literal (issue #93).
BUILD_UNIT_ROLE = "worker"

#: The named judgment verb consulted for the tier judgment (issues 1033 and #96). The verb supplies
#: the question criteria, the policy text, the confidence floor and the automatic floor, so this
#: module carries none of those as literals.
TIER_SUGGEST_VERB = "tier"

#: The verb question the staffing consult asks: below, same or above the unit's default.
DIRECTION_QUESTION = "direction"
DIRECTION_BELOW = "below"
DIRECTION_SAME = "same"
DIRECTION_ABOVE = "above"

#: Decision-id namespace for tier-judgment verdicts, so ``jev eval`` scores this judgment point
#: apart from every other, and apart from the retired absolute-tier verdicts logged under
#: ``staffing/tier-suggest``. A run-scoped caller appends ``<repo>#<issue>`` before the unit key:
#: ``jev eval`` skips a repeated decision id and drops one that carries two labels, so an id
#: without the run's identity could be scored once in total, not once per run.
JUDGMENT_DECISION_PREFIX = "staffing/tier-direction"

#: The switch that turns the tier judgment off. Any of the off values skips the consult before the
#: client is even loaded, so no request is made. Unset, empty, or anything else leaves it on; the
#: client then fails open on its own when ``TYPESAFE_API_KEY`` is absent.
TIERING_ENV = "INFIQUETRA_TYPESAFE_TIERING"
_TIERING_OFF_VALUES = frozenset({"off", "0", "false", "no"})

#: The bands :func:`classify_judgment` sorts an answer into. Admission's staffing table and the
#: run record name them; ``applied`` is true only for ``auto-raise``.
BAND_NOT_CONSULTED = "not-consulted"
BAND_LOG_ONLY = "log-only"
BAND_AGREES = "agrees"
BAND_ADVISORY_LOWER = "advisory-lower"
BAND_AUTO_RAISE = "auto-raise"
BAND_CONFIRM_RAISE = "confirm-raise"
BAND_RAISE_AT_CEILING = "raise-at-ceiling"

#: Argparse sentinel for a bare ``--suggest``: consult the client. A MODEL/EFFORT value keeps its
#: issue-1021 meaning (record the parameter, make no call). An object rather than a string so no
#: value a caller could type collides with it.
CONSULT = object()


class StaffingError(ValueError):
    """Raised for an unknown work shape, role, vendor or lens, or an off-palette tier.

    Every one of those is a caller mistake that a silent default would hide on a path every
    spawn reads, so the resolver fails loud with the offending value in the message (R14).
    """


@dataclass(frozen=True)
class Qualification:
    """Whether a lens's resolved executor may establish a threshold, and why."""

    status: str
    reason: str
    lens: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "lens": self.lens}


@dataclass(frozen=True)
class StaffingDecision:
    """One staffing answer, with the inputs and the layer that supplied it.

    ``source`` names where the *tier* came from, one of :data:`TIER_PRECEDENCE`: ``operator``
    for an explicit answer, ``overlay`` for the per-repository file, ``jev-raise`` for a recorded
    raise, or ``policy`` for the shared work-shape registry. A vendor pinned on a role is not a
    tier, so it is reported separately in ``vendor_pinned_by_role`` rather than overwriting that
    provenance.
    ``suggestion`` is the advisory tier the caller passed in, recorded whether or not it agrees
    with the chosen tier and never able to change it.
    """

    vendor: str
    model: str
    effort: str
    source: str
    work_shape: str
    role: str | None = None
    vendor_pinned_by_role: bool = False
    qualification: Qualification | None = None
    suggestion: dict[str, str] | None = None
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def tier(self) -> str:
        """The model and effort as one ``model/effort`` token, e.g. ``opus/high``.

        This is the whole short output only for a work-shape answer; a role answer prints its
        vendor first and a lens appends the qualification status. ``_short_form`` composes those.
        """
        return f"{self.model}/{self.effort}"

    def as_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "vendor": self.vendor,
            "model": self.model,
            "effort": self.effort,
            "tier": self.tier,
            "source": self.source,
            "work_shape": self.work_shape,
        }
        if self.role is not None:
            record["role"] = self.role
            record["vendor_pinned_by_role"] = self.vendor_pinned_by_role
        if self.qualification is not None:
            record["qualification"] = self.qualification.as_dict()
        if self.suggestion is not None:
            record["suggestion"] = self.suggestion
        if self.candidates:
            record["candidates"] = list(self.candidates)
        return record


# --------------------------------------------------------------------------- registry


#: A staffing registry far larger than the real one (26 KB) is a corrupted or hostile file, not
#: a legitimate edit. Reading it whole into memory on a path meant for every spawn is the cost
#: this ceiling avoids.
MAX_REGISTRY_BYTES = 4 * 1024 * 1024

_REGISTRY_CACHE: dict[Path, tuple[int, int, dict[str, Any]]] = {}


def load_staffing(path: Path | None = None) -> dict[str, Any]:
    """Load the whole staffing registry, memoized on the file's size and modification time.

    One ``resolve_role`` call used to read and re-parse this file five times, because every
    block accessor reloaded it. The cache key is ``(st_size, st_mtime_ns)``, so an edit on disk
    is picked up on the next call and a test that rewrites the registry still sees its own bytes.
    """
    registry_path = path if path is not None else STAFFING_PATH
    try:
        stat = registry_path.stat()
    except OSError as exc:
        raise StaffingError(f"staffing registry at {registry_path} is unreadable: {exc}") from exc
    if stat.st_size > MAX_REGISTRY_BYTES:
        raise StaffingError(
            f"staffing registry at {registry_path} is {stat.st_size} bytes, above the "
            f"{MAX_REGISTRY_BYTES}-byte ceiling"
        )

    cached = _REGISTRY_CACHE.get(registry_path)
    if cached is not None and cached[0] == stat.st_size and cached[1] == stat.st_mtime_ns:
        return cached[2]

    try:
        document: Any = json.loads(registry_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise StaffingError(
            f"staffing registry at {registry_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise StaffingError(f"staffing registry at {registry_path} must be a JSON object")
    _REGISTRY_CACHE[registry_path] = (stat.st_size, stat.st_mtime_ns, document)
    return document


def _block(name: str, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    document = registry if registry is not None else load_staffing()
    block = document.get(name)
    if not isinstance(block, dict) or not block:
        raise StaffingError(f"staffing registry is missing a non-empty {name!r} object")
    return block


def work_shapes(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    return _block("work_shapes", registry)


def vendors(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    return _block("vendors", registry)


def roles(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    return _block("roles", registry)


def capability_ratings(registry: dict[str, Any] | None = None) -> dict[str, Any]:
    return _block("capability_ratings", registry)


# --------------------------------------------------------------------------- overlay


def overlay_path(root: Path | None = None) -> Path:
    """Where the per-repository overlay lives, relative to ``root`` or the working directory.

    Public because a writer of the overlay and this reader must agree on one path; a second copy
    would let them drift onto different files silently. Saga's ``tier_defaults`` was that writer
    until issue 1030 removed it, and the path stays public because the overlay is an operator-
    committed file that anything may write.
    """
    return (root or Path.cwd()) / OVERLAY_PATH


def load_overlay(root: Path | None = None) -> dict[str, dict[str, str]]:
    """Return the per-repository overlay; absent means ``{}``, malformed raises.

    This is the one implementation of the read and its validation. Saga's ``tier_defaults``
    delegated here until issue 1030 removed it; callers now read this directly. An unknown work shape, an off-palette model or effort, and a model-effort pair
    above the model's ceiling are each a loud failure rather than a silent fall-through to the
    policy default.
    """
    path = overlay_path(root)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StaffingError(f"{path}: unreadable ({exc})") from exc
    except ValueError as exc:
        raise StaffingError(f"{path}: not valid JSON ({exc})") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        # ValueError, not JSONDecodeError: a file with non-UTF-8 bytes raises UnicodeDecodeError,
        # which is a ValueError and not a decode error, so the narrower clause let it escape.
        raise StaffingError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise StaffingError(f"{path}: top level must be an object of work-shape to tier")
    registry = work_shapes()
    return {
        str(shape): validate_tier(str(shape), tier, registry=registry, where=f"{path}[{shape}]")
        for shape, tier in data.items()
    }


def validate_tier(
    work_shape: str,
    tier: object,
    *,
    registry: dict[str, Any] | None = None,
    where: str = "tier",
) -> dict[str, str]:
    """Validate one ``{work_shape: {model, effort}}`` pair against the palette.

    Public because a writer validating an operator-confirmed override before persisting it must
    use the same check the overlay reader uses — two copies is how a write starts accepting a pair
    the read would refuse. Saga's ``tier_defaults.write_tier_default`` was that writer until issue
    1030 removed it.
    """
    registry = registry if registry is not None else work_shapes()
    if work_shape not in registry:
        raise StaffingError(
            f"{where}: unknown work-shape {work_shape!r}; expected one of {sorted(registry)}"
        )
    if not isinstance(tier, dict) or "model" not in tier or "effort" not in tier:
        raise StaffingError(f"{where}: tier must be {{'model', 'effort'}}, got {tier!r}")
    model, effort = str(tier["model"]), str(tier["effort"])
    if model not in MODELS:
        raise StaffingError(f"{where}: model {model!r} not in {MODELS}")
    if effort not in EFFORTS:
        raise StaffingError(f"{where}: effort {effort!r} not in {EFFORTS}")
    if not _tier_palette.supports_effort(model, effort):
        raise StaffingError(
            f"{where}: {model}/{effort} is unrunnable ({model}'s ceiling is "
            f"{_tier_palette.effort_ceiling(model)!r})"
        )
    return {"model": model, "effort": effort}


def _validate_suggestion(suggestion: dict[str, str] | None) -> dict[str, str] | None:
    """Validate an advisory tier suggestion without ever letting it change the answer."""
    if suggestion is None:
        return None
    if not isinstance(suggestion, dict) or "model" not in suggestion or "effort" not in suggestion:
        raise StaffingError(f"suggestion must be {{'model', 'effort'}}, got {suggestion!r}")
    model, effort = str(suggestion["model"]), str(suggestion["effort"])
    if model not in MODELS:
        raise StaffingError(f"suggestion model {model!r} not in {MODELS}")
    if effort not in EFFORTS:
        raise StaffingError(f"suggestion effort {effort!r} not in {EFFORTS}")
    if not _tier_palette.supports_effort(model, effort):
        raise StaffingError(
            f"suggestion {model}/{effort} is unrunnable ({model}'s ceiling is "
            f"{_tier_palette.effort_ceiling(model)!r})"
        )
    return {"model": model, "effort": effort}


# --------------------------------------------------------------------------- shape


def _claude_only(work_shape: str, row: Mapping[str, Any]) -> bool:
    """Whether a work-shape row refuses every non-Claude vendor; a non-boolean flag fails loud."""
    flag = row.get("claude_only", False)
    if not isinstance(flag, bool):
        raise StaffingError(
            f"work shape {work_shape!r} has a non-boolean claude_only {flag!r} in the registry"
        )
    return flag


def unattended_step_down(work_shape: str) -> bool:
    """Whether an unattended run may step this work shape one rung cheaper (``recommend_tier``).

    True unless the registry row says ``unattended_step_down: false``. The implementation work
    shape says false: the builder's ``opus/medium`` default is what staffing U3 measures, and a
    posture heuristic quietly moving unattended builders back to Sonnet would hide that test.
    """
    registry = work_shapes()
    work_shape = _tier_resolver.canonical_work_shape(work_shape)
    if work_shape not in registry:
        raise StaffingError(
            f"unknown work-shape {work_shape!r}; expected one of {sorted(registry)}"
        )
    flag = registry[work_shape].get("unattended_step_down", True)
    if not isinstance(flag, bool):
        raise StaffingError(
            f"work shape {work_shape!r} has a non-boolean unattended_step_down {flag!r}"
        )
    return flag


def unit_work_shape_default() -> str:
    """The work shape an undeclared build unit runs at: the ``worker`` role's own shape.

    ``/work`` and ``/plan`` call this instead of naming a shape, so re-pointing the worker role in
    the registry moves every undeclared unit with it.
    """
    row = roles().get(BUILD_UNIT_ROLE)
    if not isinstance(row, dict) or "work_shape" not in row:
        raise StaffingError(
            f"role {BUILD_UNIT_ROLE!r} is missing from the registry or has no work_shape"
        )
    return str(row["work_shape"])


def _validate_jev_raise(
    work_shape: str,
    raise_: object,
    *,
    base: Mapping[str, str],
    registry: dict[str, Any],
) -> dict[str, str]:
    """Validate a recorded Jev raise against the work shape's default it raises.

    A raise is exactly one step above its base: one model rung with the effort unchanged, or one
    effort rung with the model unchanged. It never names the strongest model, and never lands
    above the target model's raise ceiling (``sonnet/xhigh``, ``haiku/max``), the same bound
    :func:`one_step_raise` keeps. Anything else is refused rather than
    applied, so a recorded lowering, a two-step jump, or a hand-edited record cannot reach a
    spawn through this layer. The recorded ``confidence``, ``reason`` and ``decision_id`` ride
    along in the run record; the resolver reads only the tier.
    """
    where = f"jev raise for {work_shape!r}"
    tier = validate_tier(work_shape, raise_, registry=registry, where=where)
    strongest_model = MODELS[0]
    if tier["model"] == strongest_model:
        raise StaffingError(f"{where}: a recorded raise never reaches {strongest_model!r}")
    model_steps = _tier_palette.model_rank(base["model"]) - _tier_palette.model_rank(tier["model"])
    effort_steps = _tier_palette.effort_rank(tier["effort"]) - _tier_palette.effort_rank(
        base["effort"]
    )
    if sorted((model_steps, effort_steps)) != [0, 1]:
        raise StaffingError(
            f"{where}: {tier['model']}/{tier['effort']} is not exactly one step above the "
            f"default {base['model']}/{base['effort']} (one model rung or one effort rung)"
        )
    ceiling = _tier_palette.raise_ceiling(tier["model"])
    if _tier_palette.effort_rank(tier["effort"]) > _tier_palette.effort_rank(ceiling):
        raise StaffingError(
            f"{where}: {tier['model']}/{tier['effort']} is above {tier['model']!r}'s raise "
            f"ceiling {ceiling!r}"
        )
    return tier


def resolve_shape(
    work_shape: str,
    *,
    root: Path | None = None,
    suggestion: dict[str, str] | None = None,
    vendor: str = DEFAULT_VENDOR,
    answer: Mapping[str, str] | None = None,
    jev_raise: Mapping[str, Any] | None = None,
) -> StaffingDecision:
    """Resolve a work shape to a tier through every layer of :data:`TIER_PRECEDENCE`.

    First match wins: the operator's ``answer``; the repository overlay under ``root`` (the
    working directory when ``root`` is None); a recorded ``jev_raise``; the work shape's
    registry default. Every layer is validated against the palette whether or not it wins, so a
    malformed raise fails loud even when the overlay hides it.

    A work shape whose row says ``claude_only`` refuses any non-Claude ``vendor`` before any
    layer is read: its tier was chosen for a Claude model, and translating it into another
    vendor's execution class would staff that vendor at a tier nobody decided.
    """
    registry = work_shapes()
    # Canonicalise first: a role-tier alias is a legal input that maps onto a registry key, and
    # checking membership before mapping silently lost the three aliases the team-execution agent
    # definitions carry. The mapper is the resolver's, so there is one alias vocabulary.
    work_shape = _tier_resolver.canonical_work_shape(work_shape)
    if work_shape not in registry:
        raise StaffingError(
            f"unknown work-shape {work_shape!r}; expected one of {sorted(registry)} "
            f"or an alias of one ({sorted(_tier_resolver.ROLE_TIER_ALIASES)})"
        )
    if _claude_only(work_shape, registry[work_shape]) and vendor != DEFAULT_VENDOR:
        raise StaffingError(
            f"work shape {work_shape!r} is Claude-only; vendor {vendor!r} cannot inherit its "
            "tier through translation. Pin the role to a work shape without claude_only, or "
            "unpin the vendor."
        )
    recorded = _validate_suggestion(suggestion)
    # Pass the already-loaded block: tier_resolver.load_policy() re-reads and re-parses the whole
    # registry on every call, which is the read the memoized loader exists to avoid.
    resolution = _tier_resolver.resolve(None, work_shape, policy=registry)
    default = {"model": resolution.model, "effort": resolution.effort}
    layers: dict[str, dict[str, str] | None] = {
        "operator": (
            validate_tier(work_shape, answer, registry=registry, where="operator answer")
            if answer is not None
            else None
        ),
        "overlay": load_overlay(root).get(work_shape),
        "jev-raise": (
            _validate_jev_raise(work_shape, jev_raise, base=default, registry=registry)
            if jev_raise is not None
            else None
        ),
        "policy": default,
    }
    source = next(name for name in TIER_PRECEDENCE if layers[name] is not None)
    tier = layers[source] or default
    model, effort = translate_for_vendor(vendor, tier["model"], tier["effort"])
    return StaffingDecision(
        vendor=vendor,
        model=model,
        effort=effort,
        source=source,
        work_shape=work_shape,
        suggestion=recorded,
    )


def translate_for_vendor(vendor: str, model: str, effort: str) -> tuple[str, str]:
    """Render a Claude-palette tier as a model and effort the given vendor can actually run.

    The route is the portable execution-class vocabulary the vendor palette is already keyed on:
    Claude's own row maps each portable name to a Claude model, so inverting it turns ``opus``
    into ``gpt-5.6-terra``, which every other vendor's row then maps to its own model. The effort
    collapses through the same per-vendor table a launch would use.

    ``claude`` passes through unchanged. A vendor whose launch arguments are unverified
    (``runtime_supported`` false) is refused rather than answered, because an answer naming it
    would be a tier nobody can launch.
    """
    palette = vendors()
    if vendor not in palette:
        raise StaffingError(f"unknown vendor {vendor!r}; expected one of {sorted(palette)}")
    if vendor == DEFAULT_VENDOR:
        return model, effort
    row = palette[vendor]
    if not row.get("runtime_supported"):
        raise StaffingError(
            f"vendor {vendor!r} is in the palette but not a supported runtime "
            f"({row.get('unsupported_reason', 'no reason recorded')})"
        )

    claude_models = palette[DEFAULT_VENDOR]["models"]
    portable = {target: name for name, target in claude_models.items()}
    if model not in portable:
        # The portable vocabulary has three rungs and the Claude palette has four, so the
        # weakest Claude model has no portable equivalent to translate through. Say that, and
        # say what to do about it, rather than failing with a bare lookup message.
        raise StaffingError(
            f"{model!r} has no portable execution-class name, so it cannot be rendered for "
            f"{vendor!r}: {DEFAULT_VENDOR}'s palette maps {sorted(portable)} and the portable "
            "vocabulary has no fourth rung. Pin this role to a work shape whose tier is one of "
            "those, or give the vendor palettes a fourth execution class first."
        )
    vendor_model = row["models"].get(portable[model])
    if not vendor_model:
        raise StaffingError(f"vendor {vendor!r} has no model for {portable[model]!r}")

    accepted = row["accepted_efforts"]
    collapsed = row.get("effort_collapse", {}).get(effort, effort)
    if collapsed not in accepted:
        raise StaffingError(
            f"vendor {vendor!r} accepts {accepted}, and {effort!r} collapses to {collapsed!r}"
        )
    return str(vendor_model), str(collapsed)


# --------------------------------------------------------------------------- role


def _role_row(role: str) -> dict[str, Any]:
    table = roles()
    if role not in table:
        raise StaffingError(f"unknown role {role!r}; expected one of {sorted(table)}")
    return dict(table[role])


def _rating_strength(rating: str) -> int:
    """Strength as a sort key: STRONG above MODERATE above WEAK, an unknown rating last."""
    try:
        return RATINGS.index(rating)
    except ValueError:
        return len(RATINGS)


def candidates_for(role: str) -> tuple[dict[str, Any], ...]:
    """Executors that rate the role's capability, strongest rating first.

    Ties break on the cheaper cost-and-speed rank, which is the tie-break rule the engine
    registry's own header states: rating dominates first, and ``cost_speed_rank`` only separates
    variants that rate the requested capability equally.
    """
    row = _role_row(role)
    if "capability" not in row:
        raise StaffingError(f"role {role!r} is missing a capability")
    capability = str(row["capability"])
    ratings = capability_ratings()
    found: list[dict[str, Any]] = []
    engines = ratings.get("engines")
    if not isinstance(engines, dict):
        raise StaffingError("staffing registry's capability_ratings is missing an engines object")
    for key, engine in engines.items():
        profile = engine.get("capability_profile") or {}
        rated = profile.get(capability)
        if not rated:
            continue
        try:
            found.append(
                {
                    "executor": key,
                    "engine_id": engine["engine_id"],
                    "variant": engine["variant"],
                    "model_identity": engine["model_identity"],
                    "capability": capability,
                    "rating": rated["rating"],
                    "note": rated.get("note", ""),
                    "trust_tier": engine["trust_tier"],
                    "cost_speed_rank": engine["cost_speed_rank"],
                    "last_validated": engine["last_validated"],
                }
            )
        except (KeyError, TypeError) as exc:
            raise StaffingError(f"capability_ratings row {key!r} is malformed: {exc}") from exc
    found.sort(
        key=lambda candidate: (_rating_strength(candidate["rating"]), candidate["cost_speed_rank"])
    )
    return tuple(found)


def resolve_role(
    role: str,
    *,
    lens: str | None = None,
    root: Path | None = None,
    suggestion: dict[str, str] | None = None,
    checkout: Path | None = None,
    require_lens: bool = True,
    answer: Mapping[str, str] | None = None,
    jev_raise: Mapping[str, Any] | None = None,
) -> StaffingDecision:
    """Resolve a role to a vendor, model and effort, and for a reviewing role its lens status.

    The tier comes from the role's work shape through :func:`resolve_shape`, so ``answer``, the
    per-repository overlay and ``jev_raise`` apply in the one precedence order written there. A
    role may pin a vendor; the pin is reported in ``vendor_pinned_by_role`` and does not change
    ``source``, which names only where the tier came from.

    A lens only ever narrows the answer: it attaches the qualification status read from the
    ledger, which can downgrade a scoring executor to the documented-policy outcome but never
    promote one.
    """
    row = _role_row(role)
    if "work_shape" not in row:
        raise StaffingError(f"role {role!r} is missing a work_shape")
    work_shape = str(row["work_shape"])
    vendor = str(row.get("vendor", DEFAULT_VENDOR))
    if vendor not in vendors():
        raise StaffingError(f"role {role!r} pins unknown vendor {vendor!r}")
    base = resolve_shape(
        work_shape,
        root=root,
        suggestion=suggestion,
        vendor=vendor,
        answer=answer,
        jev_raise=jev_raise,
    )
    model, effort = base.model, base.effort

    qualification: Qualification | None = None
    if lens is None:
        if require_lens and _is_reviewing_role(role):
            raise StaffingError(
                f"role {role!r} reviews, so it needs a lens: pass one to learn whether this "
                "executor may establish a threshold for it"
            )
    else:
        if not _is_reviewing_role(role):
            raise StaffingError(
                f"a lens applies to a reviewing role; {role!r} reviews nothing "
                f"(its capability is {row['capability']!r})"
            )
        qualification = qualify_lens(
            lens, vendor=vendor, model=model, effort=effort, checkout=checkout
        )

    return StaffingDecision(
        vendor=vendor,
        model=model,
        effort=effort,
        source=base.source,
        work_shape=work_shape,
        role=role,
        vendor_pinned_by_role="vendor" in row,
        qualification=qualification,
        suggestion=base.suggestion,
    )


def _is_reviewing_role(role: str) -> bool:
    """A role reviews when its capability is the registry's adversarial-review one."""
    row = _role_row(role)
    if "capability" not in row:
        raise StaffingError(f"role {role!r} is missing a capability")
    return str(row["capability"]) == "adversarial-review"


# --------------------------------------------------------------------------- lens


def sdlc_root(checkout: Path | None = None) -> Path | None:
    """Resolve the software-development-lifecycle checkout, or report its absence.

    The resolution order is the one ``plugins/mission-control/scripts/sdlc_manager.py`` uses: an
    explicit path, then the ``INFIQUETRA_SDLC_PATH`` environment variable, then the default
    checkout. It deliberately does **not** fall through: an explicit path or a configured variable
    that is not a directory returns ``None`` rather than quietly resolving somewhere the caller
    did not name. (Mission Control's own helper returns the configured path unchecked; this one
    checks, because its ``None`` is a meaningful answer rather than an error.)

    ``None`` means no checkout is there — a documented-policy outcome for a lens, never an error,
    because a missing sibling repository must not break every spawn.
    """
    if checkout is not None:
        return checkout if checkout.is_dir() else None
    configured = os.environ.get(SDLC_PATH_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_dir() else None
    return DEFAULT_SDLC_PATH if DEFAULT_SDLC_PATH.is_dir() else None


def _read_json(path: Path) -> Any | None:
    """Read a JSON document, or ``None`` when it is absent or unreadable.

    ``ValueError`` rather than ``json.JSONDecodeError``: a file with non-UTF-8 bytes raises
    ``UnicodeDecodeError``, which is a ``ValueError`` and neither an ``OSError`` nor a decode
    error, so a narrower clause let a corrupted file escape the handler written to absorb it.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def lens_catalogue(checkout: Path | None = None) -> tuple[dict[str, Any], str | None]:
    """Return ``{lens id: entry}`` and the catalogue version, or ``({}, None)`` when unreadable.

    Takes a lifecycle *checkout*, not a repository root. The two were both called ``root``, and
    passing the wrong one degraded silently to the documented-policy outcome rather than failing,
    because any directory satisfies the resolution.
    """
    checkout = sdlc_root(checkout)
    if checkout is None:
        return {}, None
    document = _read_json(checkout / LENS_CATALOGUE_RELATIVE_PATH)
    if not isinstance(document, dict):
        return {}, None
    entries = document.get("lenses")
    if not isinstance(entries, list):
        return {}, None
    catalogue = {
        str(entry["id"]): entry for entry in entries if isinstance(entry, dict) and "id" in entry
    }
    return catalogue, document.get("version")


def verification_ledger(checkout: Path | None = None) -> list[dict[str, Any]]:
    """Return the ledger's entries, or ``[]`` when the checkout or the file is unreadable.

    Takes a lifecycle *checkout*, not a repository root.
    """
    checkout = sdlc_root(checkout)
    if checkout is None:
        return []
    document = _read_json(checkout / LEDGER_RELATIVE_PATH)
    if not isinstance(document, dict):
        return []
    entries = document.get("entries")
    return entries if isinstance(entries, list) else []


def qualify_lens(
    lens: str,
    *,
    vendor: str,
    model: str,
    effort: str,
    checkout: Path | None = None,
) -> Qualification:
    """Whether this executor may establish a threshold for this lens, and why.

    ``qualified`` needs an entry matching the lens, that exact vendor, model and effort, the
    current catalogue version, and every fixture passed. Every other case is the catalogue's
    documented-policy outcome with the reason named: a lens the catalogue marks unscorable, an
    empty ledger, a partial fixture pass, an entry recorded against an older catalogue version,
    an unreadable ledger, and an absent checkout. The ledger can only ever downgrade a scoring
    executor; it never promotes one.
    """
    checkout = sdlc_root(checkout)
    if checkout is None:
        return Qualification(
            LENS_UNVERIFIED,
            f"no software-development-lifecycle checkout ({SDLC_PATH_ENV} is unset or does not "
            "name a directory, and the default checkout is absent), so the lens name could not "
            f"be checked and no threshold can be established for {lens!r}",
            lens,
        )

    catalogue, version = lens_catalogue(checkout)
    if len(catalogue) == 0:
        # Explicitly the empty case, not a falsiness test: falling through from here reaches the
        # unknown-lens raise below, on a path whose whole contract is that it never raises. The
        # status says the name went unchecked rather than implying the lens exists and qualifies
        # nobody.
        return Qualification(
            LENS_UNVERIFIED,
            "the lens catalogue in the software-development-lifecycle checkout is absent, "
            f"unreadable or holds no lenses, so {lens!r} could not be checked",
            lens,
        )
    if lens not in catalogue:
        raise StaffingError(f"unknown lens {lens!r}; expected one of {sorted(catalogue)}")
    entry_for_lens = catalogue[lens]
    if not isinstance(entry_for_lens, dict) or not entry_for_lens.get("scorable"):
        return Qualification(
            DOCUMENTED_POLICY,
            f"the catalogue marks {lens!r} unscorable, so there are no fixtures to qualify "
            "against and the ledger is not consulted",
            lens,
        )

    entries = verification_ledger(checkout)
    if not entries:
        return Qualification(
            DOCUMENTED_POLICY,
            "the executor-verification ledger is empty, so no executor has been qualified "
            "against this catalogue and the lens establishes no threshold",
            lens,
        )

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not (
            entry.get("lens") == lens
            and entry.get("vendor") == vendor
            and entry.get("model") == model
            and entry.get("effort") == effort
        ):
            continue

        # Everything below must be present and well formed before the entry can grant. Comparing
        # two absent values with != is how a partial entry used to qualify: None != None is false,
        # so an entry with no evidence fields at all satisfied both guards. Each field is now
        # checked for presence and type first, and the failure direction is closed.
        recorded_version = entry.get("catalogue_version")
        if version is None or recorded_version is None:
            return Qualification(
                DOCUMENTED_POLICY,
                "the entry or the catalogue does not state a catalogue version, so the "
                "qualification cannot be bound to the fixtures it ran against",
                lens,
            )
        if recorded_version != version:
            return Qualification(
                DOCUMENTED_POLICY,
                f"the entry was recorded against catalogue version {recorded_version!r}, not "
                f"the current {version!r}; qualification is re-run, never carried forward",
                lens,
            )

        passed, total = entry.get("fixtures_passed"), entry.get("fixtures_total")
        if not isinstance(passed, int) or not isinstance(total, int) or isinstance(passed, bool):
            return Qualification(
                DOCUMENTED_POLICY,
                "the entry does not state integer fixture counts, so there is no evidence a "
                "qualification run happened",
                lens,
            )
        if total <= 0:
            return Qualification(
                DOCUMENTED_POLICY,
                "the entry records no fixtures, and zero of zero is not a passing run",
                lens,
            )
        if passed != total:
            return Qualification(
                DOCUMENTED_POLICY,
                f"partial qualification ({passed} of {total} fixtures) is recorded and "
                "refused, not rounded up",
                lens,
            )
        return Qualification(
            QUALIFIED,
            f"{vendor} {model}/{effort} passed {passed} of {total} fixtures at catalogue "
            f"version {version}",
            lens,
        )

    return Qualification(
        DOCUMENTED_POLICY,
        f"no ledger entry qualifies {vendor} {model}/{effort} for {lens!r}",
        lens,
    )


# --------------------------------------------------------------------------- tier judgment


def _load_commons(module: str) -> Any:
    """Load a sibling fleet-commons module, lazily.

    The resolve path never calls this: asking this module a staffing question keeps exactly the
    dependency graph it had before the tier judgment (KTD9). Only the consult entry points below
    reach it, and a load failure there falls open to the defaults rather than raising.
    """
    return _load_sibling(module)


def tiering_enabled(getenv: Callable[[str], str | None] | None = None) -> bool:
    """Whether the tier judgment may run: true unless :data:`TIERING_ENV` holds an off value.

    It reads only the switch. Whether a credential is configured is the client's question, and the
    client is the one reader of ``TYPESAFE_API_KEY``; without it the consult fails open with the
    client's own note and makes no request.
    """
    read = getenv if getenv is not None else os.environ.get
    value = read(TIERING_ENV)
    return str(value or "").strip().lower() not in _TIERING_OFF_VALUES


def one_step_raise(model: str, effort: str) -> dict[str, str] | None:
    """The tier one step above ``model/effort``, or ``None`` when no automatic raise exists.

    Effort first: one effort rung, while the model's raise ceiling allows it. At the raise ceiling,
    one model rung with the effort unchanged, unless that rung is the strongest model, which an
    automatic raise never reaches, or the effort is above the new model's raise ceiling. The
    palette has no ``max`` effort, so a raise can never land on it. Every result is one that :func:`resolve_shape` accepts as a
    ``jev_raise`` over the same default.
    """
    if (
        model not in MODELS
        or effort not in EFFORTS
        or not _tier_palette.supports_effort(model, effort)
    ):
        return None
    if model == MODELS[0]:
        # The strongest model is never reached by an automatic raise, and never raised within.
        return None
    ceiling = _tier_palette.raise_ceiling(model)
    if _tier_palette.effort_rank(effort) < _tier_palette.effort_rank(ceiling):
        return {"model": model, "effort": _tier_palette.escalate("effort", effort, 1)}
    stronger = _tier_palette.escalate("model", model, 1)
    if stronger == MODELS[0] or _tier_palette.effort_rank(effort) > _tier_palette.effort_rank(
        _tier_palette.raise_ceiling(stronger)
    ):
        return None
    return {"model": stronger, "effort": effort}


def one_step_lower(model: str, effort: str) -> dict[str, str] | None:
    """The tier one step below ``model/effort``, effort first, for display only.

    Nothing applies it: a lower tier stays advisory until the harness has measured the judgment.
    ``None`` at the palette floor.
    """
    if model not in MODELS or effort not in EFFORTS:
        return None
    lower_effort = _tier_palette.downgrade("effort", effort, 1)
    if lower_effort != effort:
        return {"model": model, "effort": lower_effort}
    weaker = _tier_palette.downgrade("model", model, 1)
    if weaker == model:
        return None
    clamped, _note = _tier_palette.clamp_effort_to_model(weaker, effort)
    return {"model": weaker, "effort": clamped}


def tier_direction(default: Mapping[str, str], final: Mapping[str, str]) -> str:
    """Whether ``final`` is below, the same as, or above ``default``: the verdict's label.

    Model strength decides; effort breaks a tie on the same model.
    """
    base_model = _tier_palette.model_rank(str(default["model"]))
    final_model = _tier_palette.model_rank(str(final["model"]))
    if final_model != base_model:
        # MODELS is strongest first, so a smaller rank is the stronger model.
        return DIRECTION_ABOVE if final_model < base_model else DIRECTION_BELOW
    base_effort = _tier_palette.effort_rank(str(default["effort"]))
    final_effort = _tier_palette.effort_rank(str(final["effort"]))
    if final_effort == base_effort:
        return DIRECTION_SAME
    return DIRECTION_ABOVE if final_effort > base_effort else DIRECTION_BELOW


def _tier_token(tier: Mapping[str, str] | None) -> str:
    return f"{tier['model']}/{tier['effort']}" if tier else "none"


#: The direction question's own choices, in the order the reason lists their probabilities.
DIRECTION_CHOICES = (DIRECTION_BELOW, DIRECTION_SAME, DIRECTION_ABOVE)


def _probabilities_text(probabilities: Any) -> str:
    """Render the answer's probabilities for the direction question's own choices only.

    The keys come from the vendor's response, and the TypeSafe client passes answer mappings
    through without checking them. The reason this text joins is recorded in ``jev_raise`` and
    printed for ``/work``, so a key that is not one of :data:`DIRECTION_CHOICES` is dropped rather
    than copied: vendor-controlled text never reaches the recorded reason (issue #133).
    """
    if not isinstance(probabilities, Mapping):
        return ""
    parts = []
    for choice in DIRECTION_CHOICES:
        value = probabilities.get(choice)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{choice} {float(value):.2f}")
    return f" (probabilities: {', '.join(parts)})" if parts else ""


def classify_judgment(
    direction: str | None,
    confidence: float | None,
    *,
    default: Mapping[str, str],
    operator_set: bool = False,
    floor: float,
    auto_floor: float,
    criterion: str = "",
    probabilities: Any = None,
) -> dict[str, Any]:
    """Sort one direction answer into a band, and say what it proposes and whether it applies.

    Returns ``{band, proposed, applied, shown, reason}``. Jev returns no free-text reason, so the
    reason is composed here from the chosen criterion, the confidence and the step taken.

    * Below ``floor``, or with no confidence: ``log-only``, never shown, never applied.
    * ``same``: ``agrees``.
    * ``below``: ``advisory-lower``, shown with the one-step-lower tier, **never applied**.
    * ``above`` at ``auto_floor`` or higher on a tier no operator set: ``auto-raise``, applied,
      one step, effort first (:func:`one_step_raise`).
    * ``above`` from ``floor`` up to ``auto_floor``, or at any confidence over an operator-set tier:
      ``confirm-raise``, shown for the operator to confirm, not applied.
    * ``above`` where no automatic step exists: ``raise-at-ceiling``, shown, not applied.
    """
    base = {"model": str(default["model"]), "effort": str(default["effort"])}
    because = f": {criterion}" if criterion else ""
    odds = _probabilities_text(probabilities)
    if confidence is None or direction not in DIRECTION_CHOICES:
        return {
            "band": BAND_LOG_ONLY,
            "proposed": None,
            "applied": False,
            "shown": False,
            "reason": f"no usable direction or confidence; the default {_tier_token(base)} stands",
        }
    if confidence < floor:
        return {
            "band": BAND_LOG_ONLY,
            "proposed": None,
            "applied": False,
            "shown": False,
            "reason": (
                f"'{direction}' at confidence {confidence:.2f}, below the floor {floor:.2f}; "
                f"logged, not shown{odds}"
            ),
        }
    if direction == DIRECTION_SAME:
        return {
            "band": BAND_AGREES,
            "proposed": dict(base),
            "applied": False,
            "shown": True,
            "reason": f"the default fits at confidence {confidence:.2f}{because}{odds}",
        }
    if direction == DIRECTION_BELOW:
        lower = one_step_lower(base["model"], base["effort"])
        return {
            "band": BAND_ADVISORY_LOWER,
            "proposed": lower,
            "applied": False,
            "shown": True,
            "reason": (
                f"a weaker tier ({_tier_token(lower)}) at confidence {confidence:.2f}{because}; "
                f"advisory only, a lower tier is never applied automatically{odds}"
            ),
        }
    raised = one_step_raise(base["model"], base["effort"])
    if raised is None:
        return {
            "band": BAND_RAISE_AT_CEILING,
            "proposed": None,
            "applied": False,
            "shown": True,
            "reason": (
                f"a stronger tier at confidence {confidence:.2f}{because}; "
                f"{_tier_token(base)} is already the strongest an automatic raise may reach{odds}"
            ),
        }
    step = "one effort step" if raised["model"] == base["model"] else "one model step"
    if confidence >= auto_floor and not operator_set:
        return {
            "band": BAND_AUTO_RAISE,
            "proposed": raised,
            "applied": True,
            "shown": True,
            "reason": (
                f"raised {step}, {_tier_token(base)} to {_tier_token(raised)}, at confidence "
                f"{confidence:.2f}{because}{odds}"
            ),
        }
    why_not = (
        "the operator set this tier, so a raise waits for the operator"
        if operator_set
        else f"below the automatic floor {auto_floor:.2f}, so it waits for the operator"
    )
    return {
        "band": BAND_CONFIRM_RAISE,
        "proposed": raised,
        "applied": False,
        "shown": True,
        "reason": (
            f"proposes {step}, {_tier_token(base)} to {_tier_token(raised)}, at confidence "
            f"{confidence:.2f}{because}; {why_not}{odds}"
        ),
    }


def judgment_unit(
    task: str | Mapping[str, Any],
    default: Mapping[str, str],
    *,
    operator_set: bool = False,
) -> dict[str, Any]:
    """One unit for :func:`consult_tier_suggestions`.

    ``task`` is what Jev judges: a description string, or a mapping that may carry
    ``description``, ``work_shape``, ``goal`` and ``files`` (a plan unit). ``default`` is the tier
    the unit runs at without a raise. ``operator_set`` marks a tier an operator chose, such as one
    from the repository overlay, which an automatic raise never overrides.
    """
    try:
        model, effort = str(default["model"]), str(default["effort"])
    except (KeyError, TypeError) as exc:
        raise StaffingError(
            f"judgment unit needs a default {{'model', 'effort'}}, got {default!r}"
        ) from exc
    described = dict(task) if isinstance(task, Mapping) else {"description": str(task)}
    return {
        "task": described,
        "default": {"model": model, "effort": effort},
        "operator_set": bool(operator_set),
    }


#: The pre-#96 name, kept so an older caller still builds a unit.
suggestion_unit = judgment_unit


def describe_unit(label: str, decision: StaffingDecision) -> str:
    """The task text one resolved decision is consulted as: the unit, its default, and why."""
    kind = f"role '{label}'" if decision.role is not None else f"work shape '{label}'"
    rationale = str(work_shapes().get(decision.work_shape, {}).get("rationale") or "")
    text = (
        f"{kind} (work shape '{decision.work_shape}', "
        f"staffing default {decision.vendor} {decision.tier})"
    )
    return f"{text}: {rationale}" if rationale else text


def consult_tier_suggestions(
    units: Mapping[str, Mapping[str, Any]],
    *,
    issue: Mapping[str, Any] | None = None,
    decision_prefix: str = JUDGMENT_DECISION_PREFIX,
    floor: float | None = None,
    auto_floor: float | None = None,
    ask: Callable[..., Any] | None = None,
    client: Any = None,
    verbs: Any = None,
    log_module: Any = None,
    getenv: Callable[[str], str | None] | None = None,
    cache: bool = False,
    timeout: float | None = None,
    max_attempts: int | None = None,
    total_deadline: float | None = None,
) -> dict[str, Any]:
    """Ask the tier verb's direction question about every unit in one request.

    ``units`` maps a key to :func:`judgment_unit`. ``issue`` is the issue the units serve, as
    ``{title, body, flags}``; it travels once, beside the units, as the state's ``issue``. The
    state is the issue plus each unit's task and default tier, all permitted by the data rule in
    ``references/typesafe.md``. Each key comes back as one judgment block carrying the answer's
    ``direction``, ``confidence`` and ``probabilities``, the band from :func:`classify_judgment`,
    and everything a later :func:`record_tier_verdicts` call needs to log the verdict once its
    label is known (``decision_id``, ``state_hash``, ``questions_hash``, ``threshold``,
    ``resolved_model`` and the raw ``answer``). Nothing is logged here: the label is the
    operator's final answer, which arrives later.

    Properties, mirroring the sibling advisory paths:

    * **Off means no request.** With :data:`TIERING_ENV` off, it returns status ``off`` before the
      client is loaded.
    * **Fail open.** A client failure, a timeout, a malformed body, or an unloadable client returns
      every unit at band ``not-consulted`` with the reason in ``note``. The only raise is a
      malformed ``units`` mapping, which is the caller's bug.
    * **Raises only.** ``applied`` is true only for band ``auto-raise``; nothing lowers a tier.
    * **One call path, injectable.** ``ask`` defaults to the client's, so a test hands in a fake.

    ``cache`` passes the verdict-log directory to the client as its answer cache, so a dry run and
    the answers run that follows it get identical answers from one request.
    """
    normalized = {
        key: judgment_unit(
            unit.get("task", key),
            unit.get("default", {}),
            operator_set=bool(unit.get("operator_set", False)),
        )
        if isinstance(unit, Mapping)
        else judgment_unit(key, {})
        for key, unit in units.items()
    }

    if not tiering_enabled(getenv):
        return _consult_failure(
            normalized,
            "off",
            f"the tier judgment is switched off ({TIERING_ENV}=off); no request was made",
            floor,
            auto_floor,
        )

    try:
        client = client if client is not None else _load_commons("typesafe_client")
        verbs = verbs if verbs is not None else _load_commons("jev_verbs")
        log_module = log_module if log_module is not None else _load_commons("jev_log")
    except Exception as exc:  # noqa: BLE001 - a missing fleet-core is not a broken default
        return _consult_failure(
            normalized,
            "error",
            f"the TypeSafe client could not be loaded ({exc})",
            floor,
            auto_floor,
        )

    try:
        verb = verbs.VERBS[TIER_SUGGEST_VERB]
        floor = float(verb.confidence_floor) if floor is None else float(floor)
        auto_floor = float(verb.auto_floor) if auto_floor is None else float(auto_floor)
    except (AttributeError, KeyError, TypeError, ValueError):
        return _consult_failure(
            normalized,
            "error",
            f"the {TIER_SUGGEST_VERB!r} verb carries no confidence floor or automatic floor",
            None,
            None,
        )

    if not normalized:
        return _consult_outcome("ok", "", "", floor, auto_floor, {})

    try:
        questions = _suggest_questions(normalized, verbs)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return _consult_failure(
            normalized,
            "error",
            f"the {TIER_SUGGEST_VERB!r} verb question set is unusable ({exc})",
            floor,
            auto_floor,
        )

    state: dict[str, Any] = {}
    if issue:
        state["issue"] = dict(issue)
    state["tasks"] = {
        key: {**unit["task"], "default_tier": _tier_token(unit["default"])}
        for key, unit in normalized.items()
    }
    options: dict[str, Any] = {}
    if timeout is not None:
        options["timeout"] = timeout
    if max_attempts is not None:
        options["max_attempts"] = max_attempts
    if total_deadline is not None:
        options["total_deadline"] = total_deadline
    if cache:
        try:
            options["cache_dir"] = log_module.log_dir()
        except Exception:  # noqa: BLE001 - no cache is a slower consult, not a failed one
            pass
    try:
        caller = ask if ask is not None else client.ask
        result = caller(state, questions, **options)
    except Exception as exc:  # noqa: BLE001 - a caller's defaults must survive any failure
        return _consult_failure(
            normalized, "error", f"the request raised {type(exc).__name__}", floor, auto_floor
        )

    status = getattr(result, "status", "error")
    if status != getattr(client, "STATUS_OK", "ok"):
        note = getattr(result, "note", "") or f"the request returned status {status}"
        return _consult_failure(normalized, status, note, floor, auto_floor)

    answers = dict(getattr(result, "answers", None) or {})
    resolved_model = str(getattr(result, "model", "") or "")
    try:
        state_hash = str(log_module.digest(state))
        questions_hash = str(log_module.digest(dict(questions)))
    except Exception:  # noqa: BLE001 - without hashes the verdict cannot be logged later
        state_hash = questions_hash = ""
    criteria = {
        key: question.get("criteria", {})
        for key, question in questions.items()
        if isinstance(question, Mapping)
    }
    judgments = {}
    for key, unit in normalized.items():
        block = _shape_judgment(key, unit, answers, client, criteria, floor, auto_floor)
        block.update(
            decision_id=f"{decision_prefix}:{key}",
            state_hash=state_hash,
            questions_hash=questions_hash,
            resolved_model=resolved_model,
        )
        judgments[key] = block
    return {
        **_consult_outcome("ok", "", resolved_model, floor, auto_floor, judgments),
        "state_hash": state_hash,
        "questions_hash": questions_hash,
    }


def _consult_outcome(
    status: str,
    note: str,
    resolved_model: str,
    floor: float | None,
    auto_floor: float | None,
    judgments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": status,
        "note": note,
        "resolved_model": resolved_model,
        "floor": floor,
        "auto_floor": auto_floor,
        "judgments": judgments,
    }


def _consult_failure(
    units: Mapping[str, Mapping[str, Any]],
    status: str,
    note: str,
    floor: float | None,
    auto_floor: float | None,
) -> dict[str, Any]:
    """The fall-open result: every unit keeps its default, with the reason why."""
    judgments = {
        key: {
            "direction": None,
            "confidence": None,
            "probabilities": None,
            "band": BAND_NOT_CONSULTED,
            "default": dict(unit["default"]),
            "proposed": None,
            "applied": False,
            "shown": False,
            "reason": note,
            "threshold": floor,
            "auto_floor": auto_floor,
            "answer": None,
        }
        for key, unit in units.items()
    }
    return _consult_outcome(status, note, "", floor, auto_floor, judgments)


def _suggest_questions(units: Mapping[str, Mapping[str, Any]], verbs: Any) -> dict[str, Any]:
    """One direction question per unit, from the tier verb's own set.

    The criteria and policy text are the verb's verbatim; only the task reference is retargeted
    from the verb's single-task ```task``` onto this unit's entry in the batched ``tasks`` state.
    """
    base = verbs.VERBS[TIER_SUGGEST_VERB].question_set()[DIRECTION_QUESTION]
    questions: dict[str, Any] = {}
    for key in units:
        question = dict(base)
        question["instructions"] = _retarget_instructions(base["instructions"], f"`tasks.{key}`")
        questions[f"{key}__{DIRECTION_QUESTION}"] = question
    return questions


def _retarget_instructions(instructions: Any, ref: str) -> Any:
    if isinstance(instructions, str):
        return instructions.replace("`task`", ref)
    if isinstance(instructions, Mapping):
        retargeted = dict(instructions)
        question = retargeted.get("question")
        if isinstance(question, str):
            retargeted["question"] = question.replace("`task`", ref)
        return retargeted
    return instructions


def _safe_confidence(client: Any, answer: Any) -> float | None:
    if not isinstance(answer, Mapping):
        return None
    try:
        value = client.answer_confidence(answer)
    except Exception:  # noqa: BLE001 - an unreadable answer reads as no confidence
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _safe_value(client: Any, answer: Mapping[str, Any]) -> Any:
    try:
        return client.answer_value(answer)
    except Exception:  # noqa: BLE001 - an unreadable answer reads as no value
        return None


def _shape_judgment(
    key: str,
    unit: Mapping[str, Any],
    answers: Mapping[str, Any],
    client: Any,
    criteria: Mapping[str, Any],
    floor: float,
    auto_floor: float,
) -> dict[str, Any]:
    """One unit's answer into the judgment block the caller records."""
    question_key = f"{key}__{DIRECTION_QUESTION}"
    answer = answers.get(question_key)
    default = dict(unit["default"])
    if not isinstance(answer, Mapping):
        return {
            "direction": None,
            "confidence": None,
            "probabilities": None,
            "band": BAND_NOT_CONSULTED,
            "default": default,
            "proposed": None,
            "applied": False,
            "shown": False,
            "reason": f"the answer carried no judgment for '{key}'; the default stands",
            "threshold": floor,
            "auto_floor": auto_floor,
            "answer": None,
        }
    direction = _safe_value(client, answer)
    direction = direction if isinstance(direction, str) else None
    confidence = _safe_confidence(client, answer)
    probabilities = answer.get("probabilities")
    described = criteria.get(question_key, {})
    criterion = str(described.get(direction, "")) if isinstance(described, Mapping) else ""
    classified = classify_judgment(
        direction,
        confidence,
        default=default,
        operator_set=bool(unit.get("operator_set")),
        floor=floor,
        auto_floor=auto_floor,
        criterion=criterion,
        probabilities=probabilities,
    )
    return {
        "direction": direction,
        "confidence": confidence,
        "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else None,
        "default": default,
        **classified,
        "threshold": floor,
        "auto_floor": auto_floor,
        "answer": dict(answer),
    }


def jev_raise_from(block: Mapping[str, Any]) -> dict[str, Any] | None:
    """The run-record ``jev_raise`` for an applied raise, or ``None`` for every other band.

    The shape :func:`resolve_shape` reads (its tier) plus what the record keeps beside it:
    ``{model, effort, confidence, reason, decision_id}``.
    """
    if block.get("band") != BAND_AUTO_RAISE or not block.get("applied"):
        return None
    proposed = block.get("proposed")
    if not isinstance(proposed, Mapping):
        return None
    return {
        "model": proposed.get("model"),
        "effort": proposed.get("effort"),
        "confidence": block.get("confidence"),
        "reason": block.get("reason", ""),
        "decision_id": block.get("decision_id", ""),
    }


def record_tier_verdicts(
    blocks: Mapping[str, Mapping[str, Any]],
    labels: Mapping[str, str | None],
    *,
    log_module: Any = None,
    log_dir: Path | None = None,
) -> dict[str, str]:
    """Log one verdict per judgment block that carries an answer; return each verdict's hash.

    ``labels`` maps the same keys to the verdict's label (:func:`tier_direction` of the default
    and the tier the operator finally accepted), or ``None`` where none is known. A block without
    an answer (not consulted, failed, switched off) has nothing to score and writes nothing.
    Best-effort like every verdict writer: evidence is never worth failing a staffing answer for,
    so a log that cannot be written returns what was logged so far.
    """
    written: dict[str, str] = {}
    try:
        log_module = log_module if log_module is not None else _load_commons("jev_log")
    except Exception:  # noqa: BLE001 - see the docstring
        return written
    for key, block in blocks.items():
        answer = block.get("answer")
        if not isinstance(answer, Mapping) or not block.get("state_hash"):
            continue
        try:
            record = log_module.record_verdict(
                decision_id=str(block.get("decision_id") or f"{JUDGMENT_DECISION_PREFIX}:{key}"),
                state_hash=str(block["state_hash"]),
                questions_hash=str(block.get("questions_hash") or ""),
                answer=dict(answer),
                confidence=block.get("confidence"),
                threshold=block.get("threshold"),
                resolved_model=str(block.get("resolved_model") or ""),
                label=labels.get(key),
                directory=log_dir,
            )
        except Exception:  # noqa: BLE001, PERF203 - see the docstring
            return written
        written[key] = str(record.get("verdict_hash", "")) if isinstance(record, Mapping) else ""
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="staffing.py",
        description="Resolve a work shape, a role, or a role and review lens to a tier.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="resolve one staffing question")
    resolve.add_argument("--shape", help="a work shape from the staffing registry")
    resolve.add_argument("--role", help="a role from the staffing registry")
    resolve.add_argument("--lens", help="a review lens; only meaningful for a reviewing role")
    resolve.add_argument(
        "--suggest",
        nargs="?",
        const=CONSULT,
        metavar="MODEL/EFFORT",
        help=(
            "bare: ask the tier judgment once whether this unit needs a weaker, the same, or a "
            "stronger tier, and print the band it would take in a run; with MODEL/EFFORT: record "
            "that tier as the advisory suggestion instead. Neither changes the tier this command "
            f"resolves. {TIERING_ENV}=off makes no request"
        ),
    )
    resolve.add_argument(
        "--json", action="store_true", help="print the whole decision record instead of the tier"
    )

    explain = sub.add_parser("explain", help="list a role's candidate executors in rating order")
    explain.add_argument("--role", required=True, help="a role from the staffing registry")
    explain.add_argument(
        "--lens",
        help="a review lens; attaches its qualification status to a reviewing role's listing",
    )
    explain.add_argument("--json", action="store_true", help="print the candidates as JSON")

    return parser


def _parse_suggestion(raw: str | None) -> dict[str, str] | None:
    if raw is None:
        return None
    if raw.count("/") != 1:
        raise StaffingError(f"--suggest must be MODEL/EFFORT, got {raw!r}")
    model, effort = raw.split("/")
    return {"model": model, "effort": effort}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except StaffingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "resolve":
        return _cli_resolve(args)
    return _cli_explain(args)


def _cli_resolve(args: argparse.Namespace) -> int:
    if bool(args.shape) == bool(args.role):
        raise StaffingError("pass exactly one of --shape or --role")
    if args.suggest is CONSULT:
        return _cli_consult(args)
    suggestion = _parse_suggestion(args.suggest)
    if args.shape:
        if args.lens:
            raise StaffingError("a lens applies to a reviewing role, not a work shape")
        decision = resolve_shape(args.shape, suggestion=suggestion)
    else:
        decision = resolve_role(args.role, lens=args.lens, suggestion=suggestion)
    if args.json:
        print(json.dumps(decision.as_dict(), indent=2, sort_keys=True))
    else:
        print(_short_form(decision))
    return 0


def _cli_consult(args: argparse.Namespace) -> int:
    """Resolve the default, ask the tier judgment once, and print both.

    The command line has no run record to hold a raise, so ``applies:`` is always the default; the
    judgment line names the band the answer would take in a run, where admission or ``/plan``
    records an automatic raise. A client failure still exits zero: the default it falls open to is
    a complete answer. The verdict is logged with no label, because no operator answer follows.
    """
    if args.shape:
        if args.lens:
            raise StaffingError("a lens applies to a reviewing role, not a work shape")
        decision = resolve_shape(args.shape)
        label = decision.work_shape
    else:
        decision = resolve_role(args.role, lens=args.lens)
        label = decision.role or args.role
    outcome = consult_tier_suggestions(
        {
            label: judgment_unit(
                {"description": describe_unit(label, decision), "work_shape": decision.work_shape},
                {"model": decision.model, "effort": decision.effort},
                operator_set=decision.source in ("operator", "overlay"),
            )
        },
        decision_prefix=f"{JUDGMENT_DECISION_PREFIX}:cli",
    )
    entry = outcome["judgments"][label]
    if outcome["status"] == "ok":
        record_tier_verdicts({label: entry}, {})
    if args.json:
        payload = decision.as_dict()
        payload["consult"] = {
            "status": outcome["status"],
            "note": outcome["note"],
            "resolved_model": outcome["resolved_model"],
            "floor": outcome["floor"],
            "auto_floor": outcome["auto_floor"],
            "direction": entry.get("direction"),
            "confidence": entry.get("confidence"),
            "band": entry.get("band"),
            "proposed": entry.get("proposed"),
            "reason": entry.get("reason"),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\n".join(_format_consult(decision, entry, outcome)))
    return 0


def _format_consult(
    decision: StaffingDecision, entry: Mapping[str, Any], outcome: Mapping[str, Any]
) -> list[str]:
    """The short human form: the default, the judgment and its band, and what applies here."""
    lines = [f"default: {_short_form(decision)} ({decision.source})"]
    direction = entry.get("direction")
    confidence = entry.get("confidence")
    if direction is None or not isinstance(confidence, (int, float)):
        lines.append(f"judgment: none ({entry.get('reason', 'no judgment')})")
    else:
        floor, auto_floor = outcome.get("floor"), outcome.get("auto_floor")
        floor_shown = f"{floor:.2f}" if isinstance(floor, (int, float)) else "n/a"
        auto_shown = f"{auto_floor:.2f}" if isinstance(auto_floor, (int, float)) else "n/a"
        proposed = entry.get("proposed")
        lines.append(
            f"judgment: {direction} at confidence {confidence:.2f} "
            f"(floor {floor_shown}, auto {auto_shown}); in a run: {entry.get('band')}"
            + (f" -> {_tier_token(proposed)}" if isinstance(proposed, Mapping) else "")
        )
        lines.append(f"reason: {entry.get('reason', '')}")
    lines.append(f"applies: {_short_form(decision)}")
    return lines


def _cli_explain(args: argparse.Namespace) -> int:
    rows = candidates_for(args.role)
    # The lens is optional here, as this subcommand's help says: explain's subject is the
    # candidate list, and a reviewing role asked without one simply has no status to attach.
    # resolve_role requires a lens for a reviewing role, so ask it only when one was given.
    if args.lens is None and _is_reviewing_role(args.role):
        decision = resolve_role(args.role, lens=None, require_lens=False)
    else:
        decision = resolve_role(args.role, lens=args.lens)
    if args.json:
        listed = replace(decision, candidates=rows)
        print(json.dumps(listed.as_dict(), indent=2, sort_keys=True))
        return 0

    print(f"{args.role}: {_short_form(decision)} (work shape {decision.work_shape})")
    if not rows:
        capability = _role_row(args.role)["capability"]
        print(
            f"  no executor rates {capability!r}; the role runs on the resolved tier "
            "with no rated alternative"
        )
        return 0
    resolved = f"{decision.vendor} {decision.model}/{decision.effort}"
    listed_resolved = any(row["executor"].startswith(f"{decision.vendor}/") for row in rows)
    print(
        f"  rated alternatives for {_role_row(args.role)['capability']!r}"
        + ("" if listed_resolved else f" — none of them the resolved executor, {resolved}")
        + ":"
    )
    for row in rows:
        print(
            f"  {row['rating']:<9} {row['executor']:<28} "
            f"trust {row['trust_tier']:<9} cost/speed rank {row['cost_speed_rank']} "
            f"validated {row['last_validated']}"
        )
    return 0


def _short_form(decision: StaffingDecision) -> str:
    """The short human form the card's acceptance criteria assert, character for character."""
    if decision.role is None:
        return decision.tier
    line = f"{decision.vendor} {decision.model}/{decision.effort}"
    if decision.qualification is not None:
        line += f" {decision.qualification.status}"
    return line


if __name__ == "__main__":
    raise SystemExit(main())
