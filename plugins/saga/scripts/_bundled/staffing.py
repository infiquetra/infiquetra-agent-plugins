# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.32.0
# source-commit: authored
# source-path: scripts/fleet_commons/staffing.py
# source-sha256: 60381d20344fde43bbcdf97cbeb7cc5af4a45bdcfca0c661ca4b9f83a4d1ba62
# output-sha256: 60381d20344fde43bbcdf97cbeb7cc5af4a45bdcfca0c661ca4b9f83a4d1ba62
# --- end generated bundle stamp ---
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

* ``resolve_shape(work_shape)`` — the tier for a work shape, honouring the repository overlay.
* ``resolve_role(role)`` — the vendor, model and effort for a named role.
* ``resolve_role(role, lens=...)`` — the same, plus the lens's qualification status.

It composes ``tier_palette`` and ``tier_resolver`` rather than replacing them (KTD2), and it
dispatches nothing: every call returns a :class:`StaffingDecision` describing the answer, the
layer that supplied it, and any advisory suggestion the caller passed in. Persisting that record
belongs to the run record (KTD8), not here.

The advisory tier suggestion (KTD9) arrives two ways. ``resolve_shape`` and ``resolve_role`` take
it as a parameter and never call out, so a staffing question can never depend on a service being
reachable. ``consult_tier_suggestions`` (issue 1033) is the explicit consult: it asks the tier
judgment verb about a batch of units in one request, validates each answer like any tier, and logs
one verdict per suggested unit. Either way the suggestion is recorded beside the chosen tier and
can never change it.
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

#: The named judgment verb consulted for tier suggestions (issue 1033). The verb supplies the
#: question criteria, the policy text, and the confidence floor, so this module carries none of
#: those as literals.
TIER_SUGGEST_VERB = "tier"

#: Decision-id namespace for suggestion verdicts, so ``jev eval`` can score this judgment point
#: separately from every other.
SUGGEST_DECISION_PREFIX = "staffing/tier-suggest"

#: Scalar effort names the tier verb may suggest that are not Claude-palette rungs, mapped onto
#: the palette top they read as. The verb's effort question offers low/medium/high/max while
#: EFFORTS tops out at xhigh; without this map a "max" suggestion — the honest answer for a
#: consequential decision — would be unusable on arrival.
SUGGESTED_EFFORT_ALIASES: dict[str, str] = {"max": "xhigh"}

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

    ``source`` names where the *tier* came from: ``overlay`` for the per-repository file, or
    ``policy`` for the shared work-shape registry. A vendor pinned on a role is not a tier, so it
    is reported separately in ``vendor_pinned_by_role`` rather than overwriting that provenance.
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


def resolve_shape(
    work_shape: str,
    *,
    root: Path | None = None,
    suggestion: dict[str, str] | None = None,
    vendor: str = DEFAULT_VENDOR,
) -> StaffingDecision:
    """Resolve a work shape to a tier: the repository overlay first, then the shared policy."""
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
    recorded = _validate_suggestion(suggestion)
    overlay = load_overlay(root)
    if work_shape in overlay:
        tier = overlay[work_shape]
        source = "overlay"
    else:
        # Pass the already-loaded block: tier_resolver.load_policy() re-reads and re-parses the
        # whole registry on every call, which is the read the memoized loader exists to avoid.
        resolution = _tier_resolver.resolve(None, work_shape, policy=registry)
        tier = {"model": resolution.model, "effort": resolution.effort}
        source = "policy"
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
) -> StaffingDecision:
    """Resolve a role to a vendor, model and effort, and for a reviewing role its lens status.

    The tier comes from the role's work shape, so the per-repository overlay still wins where it
    names that shape. A role may pin a vendor; the pin is reported in ``vendor_pinned_by_role``
    and does not change ``source``, which names only where the tier came from.

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
    base = resolve_shape(work_shape, root=root, suggestion=suggestion, vendor=vendor)
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


# --------------------------------------------------------------------------- tier suggestion


def _load_commons(module: str) -> Any:
    """Load a sibling fleet-commons module, lazily.

    The resolve path never calls this: asking this module a staffing question keeps exactly the
    dependency graph it had before the suggestion (KTD9). Only the consult entry points below
    reach it, and a load failure there falls open to the defaults rather than raising.
    """
    return _load_sibling(module)


def suggestion_unit(
    task: str, default: Mapping[str, str], *, operator_set: bool = False
) -> dict[str, Any]:
    """One unit for :func:`consult_tier_suggestions`: its description, the default tier that
    stands whatever the model says, and whether an operator set that tier.

    ``operator_set`` is what makes an override record meaningful: when an operator-set tier differs
    from a suggestion that cleared the floor, the difference is logged as an override of that
    suggestion (mission-control's rule: the author's value is the decision, a difference is the
    override). A policy default standing over a suggestion is the standing rule, not an override.
    """
    try:
        model, effort = str(default["model"]), str(default["effort"])
    except (KeyError, TypeError) as exc:
        raise StaffingError(
            f"suggestion unit needs a default {{'model', 'effort'}}, got {default!r}"
        ) from exc
    return {
        "task": task,
        "default": {"model": model, "effort": effort},
        "operator_set": bool(operator_set),
    }


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
    decision_prefix: str = SUGGEST_DECISION_PREFIX,
    floor: float | None = None,
    ask: Callable[..., Any] | None = None,
    client: Any = None,
    verbs: Any = None,
    log_module: Any = None,
    log_verdicts: bool = True,
    log_dir: Path | None = None,
    timeout: float | None = None,
    max_attempts: int | None = None,
    total_deadline: float | None = None,
) -> dict[str, Any]:
    """Ask the tier verb about every unit in one request; the defaults stand regardless.

    ``units`` maps a label to :func:`suggestion_unit`. The whole batch goes out as one ``ask``
    call over one ``{"tasks": ...}`` state (the house batching rule), and each label comes back
    as one entry carrying the ``suggested`` tier, its ``confidence`` (the weaker of the model's
    and the effort's), the ``floor``, and ``chosen`` — the default that stands. A suggestion
    below the floor, or one that fails palette validation, is reported with its reason and is
    never carried onto a decision. A client failure, a timeout, a malformed body, or an
    unloadable client falls open the same way, with the reason in ``note``.

    Three properties, mirroring the sibling advisory paths (``jev_widen``, mission-control's
    ``issue prepare --suggest``):

    * **Advisory.** Nothing here returns a tier to run. The caller records a suggestion beside
      its own answer; the answer is computed without consulting.
    * **Fail open.** Every failure mode returns a result whose entries carry ``chosen`` and a
      reason. The only raise is a malformed ``units`` mapping, which is the caller's bug.
    * **One call path, injectable.** ``ask`` defaults to the client's and is a parameter, so a
      test hands in a fake and cannot reach the network even by accident.
    """
    normalized = {
        key: suggestion_unit(
            str(unit.get("task", key)),
            unit.get("default", {}),
            operator_set=bool(unit.get("operator_set", False)),
        )
        if isinstance(unit, Mapping)
        else suggestion_unit(key, {})
        for key, unit in units.items()
    }

    try:
        client = client if client is not None else _load_commons("typesafe_client")
        verbs = verbs if verbs is not None else _load_commons("jev_verbs")
        log_module = log_module if log_module is not None else _load_commons("jev_log")
    except Exception as exc:  # noqa: BLE001 - a missing fleet-core is not a broken default
        return _consult_failure(
            normalized, "error", f"the TypeSafe client could not be loaded ({exc})", floor
        )

    if floor is None:
        try:
            floor = float(verbs.VERBS[TIER_SUGGEST_VERB].confidence_floor)
        except (AttributeError, KeyError, TypeError, ValueError):
            floor = None
    if floor is None:
        return _consult_failure(
            normalized,
            "error",
            f"the {TIER_SUGGEST_VERB!r} verb carries no confidence floor",
            None,
        )

    if not normalized:
        return {"status": "ok", "note": "", "resolved_model": "", "floor": floor, "suggestions": {}}

    try:
        questions = _suggest_questions(normalized, verbs)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return _consult_failure(
            normalized,
            "error",
            f"the {TIER_SUGGEST_VERB!r} verb question set is unusable ({exc})",
            floor,
        )

    state = {"tasks": {key: unit["task"] for key, unit in normalized.items()}}
    options: dict[str, Any] = {}
    if timeout is not None:
        options["timeout"] = timeout
    if max_attempts is not None:
        options["max_attempts"] = max_attempts
    if total_deadline is not None:
        options["total_deadline"] = total_deadline
    try:
        caller = ask if ask is not None else client.ask
        result = caller(state, questions, **options)
    except Exception as exc:  # noqa: BLE001 - a caller's defaults must survive any failure
        return _consult_failure(
            normalized, "error", f"the request raised {type(exc).__name__}", floor
        )

    status = getattr(result, "status", "error")
    if status != getattr(client, "STATUS_OK", "ok"):
        note = getattr(result, "note", "") or f"the request returned status {status}"
        return _consult_failure(normalized, status, note, floor)

    answers = dict(getattr(result, "answers", None) or {})
    resolved_model = str(getattr(result, "model", "") or "")
    suggestions = {
        key: _shape_suggestion(key, unit, answers, client, floor)
        for key, unit in normalized.items()
    }
    if log_verdicts:
        _record_suggest_verdicts(
            log_module,
            decision_prefix=decision_prefix,
            units=normalized,
            state=state,
            questions=questions,
            answers=answers,
            suggestions=suggestions,
            floor=floor,
            resolved_model=resolved_model,
            log_dir=log_dir,
        )
    return {
        "status": "ok",
        "note": "",
        "resolved_model": resolved_model,
        "floor": floor,
        "suggestions": suggestions,
    }


def _consult_failure(
    units: Mapping[str, Mapping[str, Any]], status: str, note: str, floor: float | None
) -> dict[str, Any]:
    """The fall-open result: every unit keeps its default, with the reason why."""
    return {
        "status": status,
        "note": note,
        "resolved_model": "",
        "floor": floor,
        "suggestions": {
            key: {
                "suggested": None,
                "confidence": None,
                "model_confidence": None,
                "effort_confidence": None,
                "floor": floor,
                "low_confidence": False,
                "usable": False,
                "problem": None,
                "chosen": dict(unit["default"]),
                "reason": note,
            }
            for key, unit in units.items()
        },
    }


def _suggest_questions(units: Mapping[str, Mapping[str, Any]], verbs: Any) -> dict[str, Any]:
    """One model and one effort question per unit, from the tier verb's own set.

    The criteria and policy text are the verb's verbatim; only the task reference is retargeted
    from the verb's single-task ```task``` onto this unit's entry in the batched ``tasks`` state.
    """
    base = verbs.VERBS[TIER_SUGGEST_VERB].question_set()
    questions: dict[str, Any] = {}
    for key in units:
        ref = f"`tasks.{key}`"
        for name in ("model", "effort"):
            question = dict(base[name])
            question["instructions"] = _retarget_instructions(base[name]["instructions"], ref)
            questions[f"{key}__{name}"] = question
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


def _unusable_reason(model: str, effort: str) -> str | None:
    """Why a suggested pair may not stand beside a tier, or None when it may."""
    if model not in MODELS:
        return f"suggested model {model!r} is not in the palette {MODELS}"
    if effort not in EFFORTS:
        return f"suggested effort {effort!r} is not in the palette {EFFORTS}"
    if not _tier_palette.supports_effort(model, effort):
        return (
            f"suggested tier {model}/{effort} is unrunnable "
            f"({model}'s ceiling is {_tier_palette.effort_ceiling(model)!r})"
        )
    return None


def _shape_suggestion(
    key: str,
    unit: Mapping[str, Any],
    answers: Mapping[str, Any],
    client: Any,
    floor: float,
) -> dict[str, Any]:
    """One unit's answers into the entry the caller records: what was suggested, how confident,
    and the default that stands."""
    chosen = dict(unit["default"])
    model_answer = answers.get(f"{key}__model")
    effort_answer = answers.get(f"{key}__effort")
    model_conf = _safe_confidence(client, model_answer)
    effort_conf = _safe_confidence(client, effort_answer)
    base: dict[str, Any] = {
        "model_confidence": model_conf,
        "effort_confidence": effort_conf,
        "floor": floor,
        "chosen": chosen,
    }
    if not isinstance(model_answer, Mapping) or not isinstance(effort_answer, Mapping):
        missing = ", ".join(
            name
            for name, answer in (("model", model_answer), ("effort", effort_answer))
            if not isinstance(answer, Mapping)
        )
        return {
            **base,
            "suggested": None,
            "confidence": None,
            "low_confidence": False,
            "usable": False,
            "problem": None,
            "reason": f"the answer carried no suggestion for '{key}' (missing {missing}); "
            "the default stands",
        }
    model = _safe_value(client, model_answer)
    effort_raw = _safe_value(client, effort_answer)
    if not isinstance(model, str) or not isinstance(effort_raw, str):
        return {
            **base,
            "suggested": None,
            "confidence": None,
            "low_confidence": False,
            "usable": False,
            "problem": "the answer has no usable tier value",
            "reason": f"the answer for '{key}' has no usable tier value; the default stands",
        }
    effort = SUGGESTED_EFFORT_ALIASES.get(effort_raw, effort_raw)
    suggested = {"model": model, "effort": effort}
    confidence = (
        min(model_conf, effort_conf) if model_conf is not None and effort_conf is not None else None
    )
    problem = _unusable_reason(model, effort)
    if problem is not None:
        return {
            **base,
            "suggested": suggested,
            "confidence": confidence,
            "low_confidence": False,
            "usable": False,
            "problem": problem,
            "reason": f"{problem}; the default stands",
        }
    if confidence is None or confidence < floor:
        if confidence is None:
            reason = "no confidence was reported; the default stands"
        else:
            reason = (
                f"confidence {confidence:.2f} is below the floor {floor:.2f}; the default stands"
            )
        return {
            **base,
            "suggested": suggested,
            "confidence": confidence,
            "low_confidence": True,
            "usable": True,
            "problem": None,
            "reason": reason,
        }
    if suggested == chosen:
        reason = "agrees with the default; recorded beside it"
    else:
        reason = "differs from the default; advisory only, the default stands"
    return {
        **base,
        "suggested": suggested,
        "confidence": confidence,
        "low_confidence": False,
        "usable": True,
        "problem": None,
        "reason": reason,
    }


def _record_suggest_verdicts(
    log_module: Any,
    *,
    decision_prefix: str,
    units: Mapping[str, Mapping[str, Any]],
    state: Any,
    questions: Mapping[str, Any],
    answers: Mapping[str, Any],
    suggestions: Mapping[str, dict[str, Any]],
    floor: float,
    resolved_model: str,
    log_dir: Path | None,
) -> None:
    """Append one verdict per suggested unit, plus an override where an operator-set tier differs
    from a suggestion that cleared the floor.

    The verdict's answer is the combined ``model/effort`` choice so the evaluation harness can
    join it against the ``chosen`` label; the two raw answers ride along as ``parts`` for audit.
    A unit with no suggestion to score — missing answers, unusable values — writes nothing, and a
    failed request never reaches here. Best-effort like jev_widen's: evidence is never worth
    failing a staffing answer for.
    """
    for key, entry in suggestions.items():
        suggested = entry.get("suggested")
        if not isinstance(suggested, dict):
            continue
        tier = f"{suggested.get('model')}/{suggested.get('effort')}"
        chosen = entry["chosen"]
        label = f"{chosen['model']}/{chosen['effort']}"
        try:
            record = log_module.record_verdict(
                decision_id=f"{decision_prefix}:{key}",
                state=state,
                questions=questions,
                answer={
                    "type": "choice",
                    "choice": tier,
                    "confidence": entry.get("confidence"),
                    "parts": {
                        "model": answers.get(f"{key}__model"),
                        "effort": answers.get(f"{key}__effort"),
                    },
                },
                confidence=entry.get("confidence"),
                threshold=floor,
                resolved_model=resolved_model,
                label=label,
                directory=log_dir,
            )
        except Exception:  # noqa: BLE001, PERF203 - see the docstring
            return
        try:
            if (
                entry.get("usable")
                and not entry.get("low_confidence")
                and units.get(key, {}).get("operator_set")
                and suggested != entry.get("chosen")
            ):
                log_module.record_override(
                    verdict_hash=record["verdict_hash"],
                    chosen=label,
                    rationale=(
                        f"the operator's tier for '{key}' is {label}; the suggestion was {tier}"
                    ),
                    directory=log_dir,
                )
        except Exception:  # noqa: BLE001 - see the docstring
            return


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
            "bare: consult the tier judgment once and record its suggestion beside the answer; "
            "with MODEL/EFFORT: record that tier as the advisory suggestion instead. "
            "Neither can change the resolved tier"
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
    """Resolve the default, consult the tier judgment once, and print both.

    The suggestion is carried onto the decision only when it is usable and clears the floor; the
    resolved tier is the default's whatever the model says. A client failure still exits zero:
    the consult is advisory, and the default it falls open to is a complete answer.
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
            label: suggestion_unit(
                describe_unit(label, decision),
                {"model": decision.model, "effort": decision.effort},
                operator_set=decision.source == "overlay",
            )
        }
    )
    entry = outcome["suggestions"][label]
    if entry.get("usable") and not entry.get("low_confidence") and entry.get("suggested"):
        decision = replace(decision, suggestion=dict(entry["suggested"]))
    if args.json:
        payload = decision.as_dict()
        payload["consult"] = {
            "status": outcome["status"],
            "note": outcome["note"],
            "resolved_model": outcome["resolved_model"],
            "floor": outcome["floor"],
            "confidence": entry.get("confidence"),
            "reason": entry.get("reason"),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("\n".join(_format_consult(decision, entry, outcome["floor"])))
    return 0


def _format_consult(
    decision: StaffingDecision, entry: dict[str, Any], floor: float | None
) -> list[str]:
    """The short human form: the default, the suggestion with its confidence, and what applies."""
    lines = [f"default: {_short_form(decision)} ({decision.source})"]
    suggested = entry.get("suggested")
    if not isinstance(suggested, dict):
        lines.append(f"suggestion: none ({entry.get('reason', 'no suggestion')})")
    else:
        confidence = entry.get("confidence")
        shown = f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "n/a"
        floor_shown = f"{floor:.2f}" if isinstance(floor, (int, float)) else "n/a"
        lines.append(
            f"suggestion: {suggested.get('model')}/{suggested.get('effort')} "
            f"at confidence {shown} (floor {floor_shown}); {entry.get('reason', '')}"
        )
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
