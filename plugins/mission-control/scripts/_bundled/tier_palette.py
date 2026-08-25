# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.25.2
# source-commit: 3b5faa6c1044a888e03cb7b8bbf2f71c6749489c
# source-path: scripts/fleet_commons/tier_palette.py
# source-sha256: b14ff89f155c0043e72bf028b937bdb6e3e7b4ebbfbf919683d88a8764ef9e28
# output-sha256: b14ff89f155c0043e72bf028b937bdb6e3e7b4ebbfbf919683d88a8764ef9e28
# --- end generated bundle stamp ---
#!/usr/bin/env python3
"""Canonical fleet tier palette — the model/effort vocabulary shared across plugins.

Moved verbatim from ``plugins/saga/scripts/execution_spec.py`` (fleet-commons first
mover, issue #463 / DECISIONS ``{#fleet-commons-mechanism-463}``), then made
registry-backed in #370: the ordered ``MODELS`` / ``EFFORTS`` tuples are **derived at
import** from the explicit ``rank`` / ``rung`` indices in ``models.json`` rather than
hand-ordered here. saga re-exports these names through its vendored
``fleet_commons_shim``; other consumers load this module the same way. Content changes
here are additive-only within fleet-core 0.x (KTD5): a consumer never breaks because
fleet-core updated.

ORDERING IS LOAD-BEARING (``{#tier-vocab-ordering}``): consumers merge tiers
upgrade-only via ``min(MODELS.index)`` / ``max(EFFORTS.index)``, so MODELS is
strongest-first and EFFORTS is weakest-first. Use ``model_rank()`` / ``effort_rank()``
(or the ``escalate`` / ``downgrade`` / ``clamp`` ladder ops) instead of re-deriving
index arithmetic. To add a model/effort, edit ``models.json`` — never a second bare
literal. See ``plugins/fleet-core/references/tier-palette.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

MODELS_REGISTRY_PATH = Path(__file__).resolve().parent / "models.json"


class TierPaletteError(ValueError):
    """Raised when ``models.json`` is malformed (bad rank/rung/ceiling)."""


def _load_registry(path: Path = MODELS_REGISTRY_PATH) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _derive_ordered(rows: dict, index_key: str, kind: str) -> tuple[str, ...]:
    """Return names ordered by their explicit integer index (0..n-1, contiguous, unique).

    A missing/duplicate/gapped/non-int index raises ``TierPaletteError`` at import —
    a silently mis-ordered tuple would corrupt every upgrade-only tier merge downstream.
    """
    indexed: list[tuple[int, str]] = []
    seen: set[int] = set()
    for name, row in rows.items():
        if index_key not in row:
            raise TierPaletteError(f"{kind} {name!r} missing {index_key!r} in models.json")
        idx = row[index_key]
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise TierPaletteError(f"{kind} {name!r} {index_key} must be an int, got {idx!r}")
        if idx in seen:
            raise TierPaletteError(f"{kind} {index_key} {idx} is duplicated in models.json")
        seen.add(idx)
        indexed.append((idx, name))
    if seen != set(range(len(indexed))):
        raise TierPaletteError(
            f"{kind} {index_key} values {sorted(seen)} are not contiguous 0..{len(indexed) - 1}"
        )
    return tuple(name for _, name in sorted(indexed))


def _derive_effort_ceilings(registry: dict, efforts: tuple[str, ...]) -> dict[str, str]:
    """Map each model to its ``effort_ceiling``; raise on a missing/unknown ceiling."""
    ceilings: dict[str, str] = {}
    for name, row in registry["models"].items():
        ceiling = row.get("effort_ceiling")
        if ceiling is None:
            raise TierPaletteError(f"model {name!r} missing 'effort_ceiling' in models.json")
        if ceiling not in efforts:
            raise TierPaletteError(
                f"model {name!r} effort_ceiling {ceiling!r} is not a known effort {efforts}"
            )
        ceilings[name] = ceiling
    return ceilings


_REGISTRY = _load_registry()

# Closed model vocabulary, strongest-first — derived from models.json ``rank``.
# Consumers validate authored tiers against this set so a typo ("opus-high") fails
# loudly instead of silently producing an un-runnable dispatch.
MODELS = _derive_ordered(_REGISTRY["models"], "rank", "model")

# Closed effort vocabulary, weakest-first — derived from models.json ``rung``.
EFFORTS = _derive_ordered(_REGISTRY["efforts"], "rung", "effort")

# Portable scalar ladder from the version-2 subset. Includes ``max``; does not
# include Codex ``ultra``. Existing ``EFFORTS`` stays the four-rung Claude set.
SCALAR_EFFORTS = _derive_ordered(_REGISTRY["scalar_efforts"], "rung", "scalar effort")

# Per-model effort ceiling: the strongest effort the model actually runs. haiku
# clamps below xhigh; the ladder ops and Tier.validate() consult this (#370).
_EFFORT_CEILINGS = _derive_effort_ceilings(_REGISTRY, EFFORTS)

# Models cheap enough that budget-discipline lessons (brevity, mandatory final
# emit, skim-don't-read, batch concurrency) MUST be baked into generated agent
# prompts. Public at the canonical home; saga's re-export keeps its private
# ``_CHEAP_MODELS`` alias.
CHEAP_MODELS = ("haiku",)

# Delegation-intent vocabulary for an engine/capability unit, ordered from the
# cheapest reconciliation posture to the strongest. ``offload`` wants a cheap
# chaperone (the delegation is net-negative otherwise); ``second-opinion`` and
# ``divergence`` want an expensive one (adversarial verification IS the product).
# The ordering is consumed upgrade-only when same-engine units share a segment.
ENGINE_INTENTS = ("offload", "second-opinion", "divergence")


def model_rank(model: str) -> int:
    """Rank of ``model`` with 0 the strongest; raises ValueError when unknown."""
    try:
        return MODELS.index(model)
    except ValueError:
        raise ValueError(f"unknown model {model!r}; expected one of {MODELS}") from None


def effort_rank(effort: str) -> int:
    """Rank of ``effort`` with 0 the weakest; raises ValueError when unknown."""
    try:
        return EFFORTS.index(effort)
    except ValueError:
        raise ValueError(f"unknown effort {effort!r}; expected one of {EFFORTS}") from None


def effort_ceiling(model: str) -> str:
    """The strongest effort ``model`` actually runs; raises ValueError when unknown."""
    try:
        return _EFFORT_CEILINGS[model]
    except KeyError:
        raise ValueError(f"unknown model {model!r}; expected one of {MODELS}") from None


# ---------------------------------------------------------------------------
# Ladder operations (#370). The two vocabularies run in OPPOSITE directions —
# MODELS is strongest-first (rank 0 strong), EFFORTS is weakest-first (rung 0
# weak) — so every op reasons in *strength* (higher = stronger) and a caller
# never touches raw ``.index()`` arithmetic ({#tier-vocab-ordering}).
# ---------------------------------------------------------------------------

_LADDERS: dict[str, tuple[str, ...]] = {"model": MODELS, "effort": EFFORTS}
_STRONGEST_FIRST: dict[str, bool] = {"model": True, "effort": False}


def _strength(kind: str, value: str) -> int:
    """Strength position on the ``kind`` ladder (higher = stronger), direction-agnostic."""
    if kind not in _LADDERS:
        raise ValueError(f"unknown ladder {kind!r}; expected 'model' or 'effort'")
    ladder = _LADDERS[kind]
    try:
        idx = ladder.index(value)
    except ValueError:
        raise ValueError(f"unknown {kind} {value!r}; expected one of {ladder}") from None
    return (len(ladder) - 1 - idx) if _STRONGEST_FIRST[kind] else idx


def _from_strength(kind: str, strength: int) -> str:
    ladder = _LADDERS[kind]
    strength = max(0, min(strength, len(ladder) - 1))
    idx = (len(ladder) - 1 - strength) if _STRONGEST_FIRST[kind] else strength
    return ladder[idx]


def escalate(kind: str, value: str, steps: int = 1, *, ceiling: str | None = None) -> str:
    """Return ``value`` moved ``steps`` stronger on the ``kind`` ladder.

    Escalating past the strongest rung (or past ``ceiling`` when given) is a no-op,
    never an error.
    """
    strength = _strength(kind, value)  # validates kind + value before any ladder access
    top = len(_LADDERS[kind]) - 1
    if ceiling is not None:
        top = min(top, _strength(kind, ceiling))
    # escalate only ever strengthens: a ceiling weaker than the current value is a no-op,
    # never a down-push (the outer max keeps the result >= the input strength).
    return _from_strength(kind, max(strength, min(strength + steps, top)))


def downgrade(kind: str, value: str, steps: int = 1, *, floor: str | None = None) -> str:
    """Return ``value`` moved ``steps`` weaker; past the weakest rung (or a floor stronger
    than ``value``) is a no-op, never an up-push."""
    strength = _strength(kind, value)  # validates kind + value before any ladder access
    bottom = 0
    if floor is not None:
        bottom = max(bottom, _strength(kind, floor))
    # downgrade only ever weakens: a floor stronger than the current value is a no-op.
    return _from_strength(kind, min(strength, max(strength - steps, bottom)))


def clamp(kind: str, value: str, *, floor: str | None = None, ceiling: str | None = None) -> str:
    """Clamp ``value`` between ``floor`` and ``ceiling`` (by strength) on the ``kind`` ladder."""
    strength = _strength(kind, value)
    if floor is not None:
        strength = max(strength, _strength(kind, floor))
    if ceiling is not None:
        strength = min(strength, _strength(kind, ceiling))
    return _from_strength(kind, strength)


def stronger(kind: str, a: str, b: str) -> str:
    """The stronger of two values on the ``kind`` ladder (upgrade-only merge primitive)."""
    return a if _strength(kind, a) >= _strength(kind, b) else b


def strongest(kind: str, values: object) -> str:
    """The strongest value among ``values`` on the ``kind`` ladder (upgrade-only merge)."""
    items = list(values)  # type: ignore[call-overload]
    if not items:
        raise ValueError("strongest() requires at least one value")
    best = items[0]
    for value in items[1:]:
        best = stronger(kind, best, value)
    return best


def supports_effort(model: str, effort: str) -> bool:
    """True iff ``model`` can run ``effort`` (effort at or below the model's ceiling)."""
    return effort_rank(effort) <= effort_rank(effort_ceiling(model))


def clamp_effort_to_model(model: str, effort: str) -> tuple[str, str | None]:
    """Return ``(effort_or_ceiling, note_or_None)`` — clamp ``effort`` to the model's ceiling.

    AC5: escalating a haiku unit toward xhigh resolves to haiku's real ceiling with the
    clamp surfaced as a note, rather than silently producing an un-runnable tier.
    """
    ceiling = effort_ceiling(model)
    if effort_rank(effort) > effort_rank(ceiling):
        return ceiling, f"effort {effort!r} exceeds {model!r} ceiling; clamped to {ceiling!r}"
    return effort, None
