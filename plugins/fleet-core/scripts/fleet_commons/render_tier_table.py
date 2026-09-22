#!/usr/bin/env python3
"""Render `/plan`'s Step-1 tier table markdown from `staffing.json` (U3, #362 R6).

Replaces the prose-only heuristic table authored by hand at
``plugins/saga/skills/plan/SKILL.md`` (its Phase 5.2a) with a block rendered
straight from the registry, so a registry edit is the only way to change the table —
no second, hand-maintained copy to drift out of sync. ``tests/test_tier_resolver.py``
parses the live SKILL.md block and asserts it equals this renderer's output
(``skill_registry_sync``); a seeded divergence between the two fails the test.

Row order and prose labels mirror the original hand-authored table (R2's five
SKILL.md rows); the *tier* and *rationale* columns come from the registry, never
hardcoded here.
"""

from __future__ import annotations


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


_tier_resolver = _load_sibling("tier_resolver")

TIER_TABLE_BEGIN = (
    "<!-- BEGIN GENERATED TIER TABLE (rendered from staffing.json via "
    "render_tier_table.py — do not hand-edit; a seeded divergence fails "
    "tests/test_tier_resolver.py::test_skill_registry_sync) -->"
)
TIER_TABLE_END = "<!-- END GENERATED TIER TABLE -->"

# (row label, registry keys backing that row). "Mechanical" spans two registry
# rows (mechanical / purely-mechanical, R2) to preserve the sonnet-vs-haiku split
# the original prose table drew within a single row.
_ROW_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Judgment, design, adversarial review, architectural decisions",
        ("judgment",),
    ),
    (
        "Mechanical, deterministic, scripted transforms, scaffolding",
        ("mechanical", "purely-mechanical"),
    ),
    (
        "Read-only survey, search, grep, sampling, census",
        ("read-only-survey",),
    ),
    (
        "External-engine delegation, `intent=offload`, `verifiability=test-gated` (ratify-only)",
        ("offload-test-gated",),
    ),
    (
        "External-engine delegation, `intent=offload`, `verifiability=unverifiable` or absent",
        ("offload",),
    ),
    (
        "External-engine delegation, `intent=second-opinion` (U12)",
        ("second-opinion",),
    ),
    (
        "External-engine delegation, `intent=divergence` (adversarial review)",
        ("divergence",),
    ),
)


def _tier_cell(policy: dict[str, dict[str, str]], keys: tuple[str, ...]) -> str:
    rows = [policy[key] for key in keys]
    primary = f"`{rows[0]['default_model']} / {rows[0]['default_effort']}`"
    if len(rows) == 1:
        return primary
    extra = " (or ".join(f"`{row['default_model']} / {row['default_effort']}`" for row in rows[1:])
    return f"{primary} (or {extra} for purely mechanical)"


def _rationale_cell(policy: dict[str, dict[str, str]], keys: tuple[str, ...]) -> str:
    return "; ".join(policy[key]["rationale"] for key in keys)


def render_rows(policy: dict[str, dict[str, str]] | None = None) -> list[tuple[str, str, str]]:
    """Return ``(work_shape, tier, rationale)`` rows in SKILL.md table order."""
    registry = policy if policy is not None else _tier_resolver.load_policy()
    return [
        (label, _tier_cell(registry, keys), _rationale_cell(registry, keys))
        for label, keys in _ROW_SPECS
    ]


def render_table(policy: dict[str, dict[str, str]] | None = None) -> str:
    """Render the full markdown table (header + generated rows) as one string."""
    lines = ["| Work shape | Default tier | Rationale |", "|---|---|---|"]
    for work_shape, tier, rationale in render_rows(policy):
        lines.append(f"| {work_shape} | {tier} | {rationale} |")
    return "\n".join(lines)


def render_block(policy: dict[str, dict[str, str]] | None = None) -> str:
    """Render the full marker-delimited block as embedded in SKILL.md."""
    return "\n".join([TIER_TABLE_BEGIN, render_table(policy), TIER_TABLE_END])


def main(argv: list[str] | None = None) -> int:
    print(render_block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
