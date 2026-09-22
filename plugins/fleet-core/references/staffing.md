# Staffing — one data file, one resolver

The fleet's answer to "role or work shape, and for review the lens, to vendor, model and effort".
This document supersedes `tier-palette.md` and `effort-convention.md`, which it absorbed in issue
1021 along with the data they described.

Everything below is authored in one file,
[`scripts/fleet_commons/staffing.json`](../scripts/fleet_commons/staffing.json).
[`scripts/fleet_commons/staffing.py`](../scripts/fleet_commons/staffing.py) is the resolver to ask
a staffing question of; `tier_palette.py` and `tier_resolver.py` read the same file directly for
the vocabulary and the work-shape and runtime resolution their existing importers already use.
Grow the vocabulary **there**, never with a second bare literal elsewhere — a repository-wide
guard,
`tests/test_tier_vocab_single_source.py::test_no_bare_model_literals_outside_module`, fails the
build if a second vocabulary source appears in production Python.

## What the data file holds

| Block | What it answers |
|---|---|
| `models`, `efforts`, `scalar_efforts` | the Claude model and effort vocabulary, and the portable scalar superset |
| `work_shapes` | the tier default per work shape — the eight rows `tier_resolver.resolve()` reads |
| `vendors` | the per-vendor palette: models, accepted efforts, effort collapse, effort application |
| `capability_ratings` | per model family and per engine variant, with trust tiers and cost-and-speed ranks |
| `roles` | per-role staffing defaults: the work shape a role's tier comes from, and the capability its candidates are ranked by |
| `execution_classes`, `root_orchestration_profiles` | the portable Codex version-2 subset |

## The load-bearing rule (`{#tier-vocab-ordering}`)

> A tuple used for **membership** *and* **ordering** has two contracts. Before extending a closed
> vocabulary, `grep` for `.index(` on it — a wrong insertion point silently mis-tiers every
> upgrade-only merge.

`MODELS` is **strongest-first** (rank 0 = strongest) and `EFFORTS` is **weakest-first** (rung 0 =
weakest) — the two run in *opposite* directions. That is exactly why callers must use `model_rank()`
/ `effort_rank()` or the `escalate` / `downgrade` / `clamp` / `stronger` ladder operations, which
reason in **strength**, and must never hand-roll `MODELS.index(...)` / `EFFORTS.index(...)`
arithmetic.

## Asking the resolver

A work-shape argument may also be one of three `role-tier:` aliases that map onto a registry row —
`adversarial-review` onto `judgment`, `contract-test` onto `mechanical`, `mechanical-scan` onto
`purely-mechanical`. Twenty-five agent definitions carry one in frontmatter, so both forms resolve
identically and the decision record names the row that answered, not the alias you typed.

```bash
# by work shape
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --shape judgment
# by role
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --role functional-tester
# by role and review lens
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve \
  --role lens-reviewer --lens security
# the rated alternatives for a role
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py explain --role lens-reviewer
# the tier judgment's suggestion beside the default (advisory; exit zero either way)
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --shape judgment --suggest
```

The default output is short and human, and its shape depends on what you asked:

| Command | Prints |
|---|---|
| `resolve --shape judgment` | `opus/high` |
| `resolve --role functional-tester` | `claude opus/high` |
| `resolve --role lens-reviewer --lens security` | `claude opus/high documented-policy` |

The third token is the qualification status, and it is one of three: `qualified`,
`documented-policy` (the lens is real and establishes no threshold), or `lens-unverified` (the
catalogue was unreadable, so the name itself was never checked). A host without the
software-development-lifecycle checkout sees the third, which is why the example above prints
`documented-policy` only where that checkout exists.

A work shape answers with the tier alone; a role answers with its vendor first, because a role's
tier is meaningless without knowing which vendor it was rendered for; a lens appends the
qualification status. **Do not parse these.** `--json` is the machine contract: it gives the
vendor, model and effort as separate fields, the layer that supplied them, the lens qualification
where one was asked for, and the advisory suggestion where one was passed in. The short form is a
projection of that record, never a separately computed answer.

**A pinned vendor is rendered for that vendor.** A role's tier resolves through the Claude-only
work-shape policy, so a role that pins another vendor has its model translated through the portable
execution-class names the vendor palette is keyed on, and its effort collapsed through the same
per-vendor table a launch would use. A pin naming a vendor whose `runtime_supported` is false is
refused rather than answered, because the answer would be a tier nobody can launch.

**The translation has a hole, and it is the weakest rung.** The portable vocabulary has three names
(`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5`) and the Claude palette has four, so `haiku` has nothing
to translate through. Two work shapes resolve to `haiku` — `purely-mechanical` and
`offload-test-gated` — and a role pinning a non-Claude vendor on either of them fails loud rather
than guessing. Giving the vendor palettes a fourth execution class is what closes it.

**Precedence.** For a work shape: the per-repository overlay at `.saga/tier-defaults.json` first,
then the shared `work_shapes` policy. On the command line "per-repository" means *relative to the
working directory* — there is no upward walk, so running from a subdirectory silently skips an
overlay that exists at the repository root. The `source` field in `--json` is how you tell: it
reads `overlay` or `policy`. A Python caller should pass `root=` explicitly rather than rely on the
working directory. For a role: the role's own entry, which names a work shape and
may pin a vendor; where it names only a work shape the work-shape precedence applies. A lens only
ever narrows the answer — it attaches a qualification status that can downgrade a scoring executor
to the documented-policy outcome, and can never promote one.

**Failing loud.** An unknown work shape, role, vendor or lens, an off-palette model, an effort above
a model's ceiling, and a malformed overlay each raise with the offending value named. This component
sits on a path every subagent spawn reads, so a silent default would be invisible and wrong
everywhere at once.

**The advisory suggestion.** Bare `--suggest` consults the `tier` judgment verb once about the
unit being resolved and records its suggestion beside the chosen tier; `--suggest model/effort`
records that tier as the suggestion instead, making no call. Either way the suggestion cannot
change the resolved tier. A suggestion below the verb's confidence floor, or one that fails
palette validation, is reported with its reason and left off the record; a failed request falls
open to the default the same way. Every scored suggestion is logged to the verdict log with the
chosen tier as its label, plus an override record where an operator-set tier differs from a
suggestion that cleared the floor. Admission's `--suggest` runs the same consult once per run,
batched over every staffed role.

With a bare `--suggest` the output is three lines instead of one — the `default:`, the
`suggestion:` with its confidence and floor, and `applies:` naming the tier that stands — and
`--json` adds a `consult` block with the request status and reason. `applies:` is always the
default: a suggestion is recorded beside the tier, never promoted over it. The `resolve` path
itself still never calls out, so a staffing question can never depend on a service being
reachable.

## To add a model

1. Add a row to `staffing.json` under `"models"` with an explicit integer `rank` and an
   `effort_ceiling` (the strongest effort the model actually runs). **Ranks must stay contiguous
   `0..n-1`** — inserting a new strongest model means renumbering the existing ranks, not squeezing
   in a duplicate or a gap. Import-time validation (`_derive_ordered`) rejects a duplicate, gapped
   or non-integer rank loudly.
2. Run `uv run pytest tests/test_tier_vocab_single_source.py` — the registry-order,
   ladder-monotonicity and effort-ceiling guards confirm the new row slots in without mis-tiering.
3. If the model needs the budget-discipline rider (a cheap model), add it to `CHEAP_MODELS` in
   `tier_palette.py`.

## To add an effort

1. Add a row to `staffing.json` under `"efforts"` with an explicit integer `rung` (0 = weakest),
   keeping the rungs contiguous.
2. Review every model's `effort_ceiling`: a new top effort is **not** automatically reachable by a
   weaker model — set each ceiling deliberately so an unsupported `{model, effort}` combination halts
   rather than running an unrunnable tier.
3. Run the guard suite.

## To add a vendor

1. Add a row under `"vendors"` naming its models, its accepted efforts, its effort collapse, and
   how effort is applied. Two keys carry that last part: `effort_application` is `argv` or
   `in_session`, and an `in_session` vendor **must** also carry `effort_command`, the template to
   send. Omitting `effort_command` does not fail — `tier_resolver` falls back to `/effort {effort}`,
   so a vendor that names its command differently silently inherits qwen's. The qwen row is the
   worked example:

   ```json
   "qwen": {
     "runtime_supported": true,
     "models": {"gpt-5.6-sol": "qwen3.8-max-preview", "gpt-5.6-terra": "qwen3.7-plus",
                "gpt-5.5": "qwen3.6-plus"},
     "accepted_efforts": ["low", "medium", "high", "xhigh", "max"],
     "effort_collapse": {},
     "effort_application": "in_session",
     "effort_command": "/effort {effort}"
   }
   ```

   A row that is not a supported runtime uses `"effort_application": "unverified"` and carries an
   `unsupported_reason` instead of efforts — `opencode` is the worked example of that.
2. Set `runtime_supported` true **only** once the launch arguments are verified on a live host. Until
   then set it false and record why in `unsupported_reason`: `SUPPORTED_RUNTIMES` derives from the
   rows whose flag is true, so an unverified vendor is visible without being silently launchable.
   Keep `accepted_efforts` **weakest-first** — `strongest-supported` resolves to its last entry, so
   a list written the other way round silently returns the weakest rung, and a guard in
   `tests/test_staffing.py` fails if it drifts.
3. The palette's vendor keys are compared as a set against the agent-launcher's own `VENDOR_FLAGS`
   table, so adding a kind there without adding it here reds `tests/test_staffing.py`.

`hermes` is the eighth agent kind the launcher skill names in prose and is deliberately absent: the
topology table describes it as reconciling a profile workspace and owning its own routing, so there
is no model or effort for this component to choose.

## To add a role

1. Add a row under `"roles"` naming the `work_shape` its tier comes from and the `capability` its
   candidates are ranked by. The capability must be one the ratings block actually rates — the
   registry rates ten, and none of them is called "testing", which is why `functional-tester` draws
   on `debug`.
2. Optionally add `"vendor"` to pin the role to a vendor other than `claude`. No shipped role does,
   so read the hole named under "Asking the resolver" first: a pinned vendor on a work shape that
   resolves to `haiku` cannot be rendered.
3. A role whose capability is `adversarial-review` is a *reviewing* role: `resolve` requires a lens
   for it, and `explain` accepts one optionally.
4. The role vocabulary itself belongs to the software-development-lifecycle repository (issue
   #1022). This block holds staffing defaults for the roles the run chain uses; an unknown role
   name fails loud rather than falling back to a work shape.

## Effort: the three-layer cascade

Most specific wins, in this order:

1. Plan-authored per-unit tier (from `/plan`'s per-unit tier authoring).
2. Team-level default (an optional team-wide effort override; usually absent today).
3. Per-teammate agent-frontmatter default (`effort:`).

The cascade wraps `tier_resolver.resolve(role_kind, work_shape, envelope_ceiling,
operator_override)` — it is not a fourth standalone resolver. A plan-unit tier maps to
`operator_override={"effort": …}` when present, short-circuiting the wrap.

Any `plugins/*/agents/*.md` file may carry an `effort:` frontmatter field, and its value must be one
of `EFFORTS`. A required lint (`tests/test_agent_tier_lint.py`, reused by
`scripts/lint_agent_tiers.py`) globs every agent file and fails the build on an out-of-vocabulary
`effort:` or `model:` value. A file opts out with `tiering_exempt: true`.

## Effort: honoring, one seam and three spawn kinds

`fleet_commons.effort_rider.inject_effort(prompt, effort, spawn_kind)` is the single seam that
decides *how* a resolved effort is honored. It understands three `spawn_kind` values:

| `spawn_kind` | Mechanism | Real knob? |
|---|---|---|
| `workflow` | Pass-through — effort already rides in `agent(prompt, {effort})` | Yes |
| `external-engine` | Pass-through — effort already passed as `effort=resolution.effort` | Yes |
| `agent` | An `EFFORT_RIDER[effort]` directive prepended to the prompt | No — a labeled proxy |

The `agent` branch exists because the native Agent-tool teammate path has no harness-level
reasoning-effort parameter today. When the harness ships one, only that branch changes — from
"prepend rider" to "pass real knob" — and nothing upstream needs to change. Calling
`inject_effort()` with an unknown effort or spawn kind raises rather than silently doing nothing.

Effort collapse for a vendor that cannot represent `max` is an **explicit table in the data**, not a
silent clamp (`{#effort-collapse-max}`). Do not read another program's configuration files to guess
what it will do.

**Chaperone workers are outside the cascade.** A worker dispatched with intent `offload` or
`second-opinion` takes an intent-driven default — `sonnet/medium` and `opus/high` respectively,
carried as `work_shapes` rows — and that is not a value to resolve or override. The cascade's three
layers do not apply to it.

## Effort: reconciliation after a run

`fleet_commons.effort_rider.reconcile_effort(resolved_effort, spawn_kind, manifest_effort=...,
spawn_prompt=...)` compares what a teammate was resolved to against what the run recorded for it. A
mismatch returns a named `tiering-drift[<spawn_kind>]` line; a match returns `None` and emits
nothing.

The comparison is honest per path, which is the whole point. On a real-knob path (`workflow`,
`external-engine`) pass `manifest_effort`: the manifest's value is what was actually handed to the
call, so a mismatch names both efforts. On the `agent` path pass `spawn_prompt` instead —
reconciliation can only confirm that the rider text for the resolved effort reached the constructed
prompt, so a mismatch names the compared quantity as `rider-text` and never as reasoning spend,
because that seam cannot observe reasoning spend at all.

## Review lenses and the qualification ledger

A lens's qualification is read from the software-development-lifecycle repository's
`config/executor-verifications.json`, through the same checkout ladder mission-control uses: an
explicit path, then `INFIQUETRA_SDLC_PATH`, then `~/workspace/infiquetra/infiquetra-sdlc`.

The resolution order is deliberately **not** a fall-through: an explicit path, or an
`INFIQUETRA_SDLC_PATH`, that does not name a directory returns "no checkout" rather than quietly
trying the next rung. A caller that names a wrong path gets the documented-policy outcome, never
the operator's real checkout.

There are three outcomes, not two. `qualified` requires all of it: an entry matching the lens, that
exact vendor, model and effort, the current lens-catalogue version, and every fixture passed. `lens-unverified` means the catalogue could not be read, so the lens
*name* was never checked — treat the name as untrusted rather than as a policy answer, because a
misspelling reaches you this way. Everything else is the catalogue's documented-policy outcome with
its reason named — an unscorable lens, an empty ledger, a partial
fixture pass, an entry against an older catalogue version, an unreadable ledger, and an absent
checkout. **Absence is data, not an exception**: the shipped ledger is empty on purpose, so raising
would fail every lens resolution on day one.

## Execution classes (the portable subset shared with Codex)

`staffing.json` also carries `schema_version`, `scalar_efforts`, `execution_classes` and
`root_orchestration_profiles`. Those keys are the subset shared with the Codex plugin repository,
whose own copy stays at its `schema_version` 2 while this file is at 3 — the subset is shared by
content, not by version number, and neither repository reads the other's file. They are
**additive**. Do not rename `models` / `efforts` to `lineage_models` / `lineage_efforts`, and do not
port those lineage tables as the live router.

`resolve_for_runtime(work_shape, runtime)` keys on an execution-class name (`review-max`,
`review-high`, `test-medium`, `scan-low`, `monitor-low`, `work-high`, `work-medium`) and returns a
runtime-owned `{model, effort, fallbacks, workspace_boundary, effort_application}`.
`adapt_runtime_argv` maps that pair to the vendor command line's real flags for the six supported
runtimes. `SCALAR_EFFORTS` derives from `scalar_efforts` the same way `EFFORTS` derives from
`efforts`; it includes `max` and not Codex `ultra`.

## What you do NOT touch

- The `/plan` tier table is **rendered** from the registry by `render_tier_table.py`, and the
  team-execution worker table is **validated** against it. A hand-edit that drifts fails
  `tests/test_tier_resolver.py::test_skill_registry_sync` and the tier-token guards in
  `tests/test_tier_vocab_single_source.py`. Change the registry, not the tables.
- `effort_ceiling` for engine-owned chaperone-dispatch workers — those stay pinned to their
  chaperone tiers and are excluded from the per-teammate ceiling halt.
- The capability ratings are **copied** from `plugins/saga/references/engine-registry.yaml`, and a
  parity test holds the two together while both exist. Nothing propagates automatically: edit the
  registry and the test goes red until someone re-copies. Issue 1030 deletes the registry and that
  test with it, at which point these ratings become the only copy and their `last_validated` dates
  have nothing left to check them against.

## Wiring a new consumer

Load the module through the fleet-commons shim, never by file path — a path import works in a
checkout and breaks under the installed-plugin layout, where fleet-core lives in a versioned cache
directory:

```python
import sys
from pathlib import Path

# The shim is a per-plugin file, not an installed package: put your plugin's own scripts/
# directory on the path first. Every real consumer does this; see
# plugins/saga/scripts/tier_defaults.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fleet_commons_shim  # noqa: E402  (after the sys.path insert, by design)

staffing = fleet_commons_shim.load("staffing")
decision = staffing.resolve_shape("judgment")
```

Consuming this module means depending on the fleet-core version that introduced it. Say so in your
plugin's changelog and fail with a message naming both versions if the module is absent;
`plugins/saga/scripts/tier_defaults.py` is the worked example. This machine carries two installed
plugin roots and a release has updated one and not the other before, so a consumer that assumes
the newer fleet-core is present will fail in one root and not the other.

## Where to look

- The data: `plugins/fleet-core/scripts/fleet_commons/staffing.json`
- The resolver: `plugins/fleet-core/scripts/fleet_commons/staffing.py`
- Vocabulary and ladder operations: `plugins/fleet-core/scripts/fleet_commons/tier_palette.py`
- Work-shape and runtime resolution: `plugins/fleet-core/scripts/fleet_commons/tier_resolver.py`
- The honoring seam: `plugins/fleet-core/scripts/fleet_commons/effort_rider.py`
- The per-repository overlay shim: `plugins/saga/scripts/tier_defaults.py`
- Guards: `tests/test_staffing.py`, `tests/test_tier_vocab_single_source.py`,
  `tests/test_tier_resolver.py`, `tests/test_agent_tier_lint.py`
