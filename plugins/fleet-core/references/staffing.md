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
`plugins/fleet-core/tests/test_tier_vocab_single_source.py::test_no_bare_model_literals_outside_module`, fails the
build if a second vocabulary source appears in production Python.

## What the data file holds

| Block | What it answers |
|---|---|
| `models`, `efforts`, `scalar_efforts` | the Claude model and effort vocabulary, and the portable scalar superset; each model carries an `effort_ceiling` (what it can run) and may carry a lower `raise_ceiling` (the strongest effort an automatic raise lands on within it) |
| `work_shapes` | the tier default per work shape — the eleven rows `tier_resolver.resolve()` reads; a row may carry `claude_only` and `unattended_step_down` |
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
  --role targeted-reviewer
# the rated alternatives for a role
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py explain --role targeted-reviewer
# ask the tier judgment about this unit and print the band it would take in a run
# (the tier printed is the default; exit zero either way)
uv run python plugins/fleet-core/scripts/fleet_commons/staffing.py resolve --shape judgment --suggest
```

The default output is short and human, and its shape depends on what you asked:

| Command | Prints |
|---|---|
| `resolve --shape judgment` | `opus/high` |
| `resolve --role functional-tester` | `claude opus/high` |
| `resolve --shape targeted-review` | `sonnet/high` |
| `resolve --role targeted-reviewer` | `claude sonnet/high` |

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

**A Claude-only work shape is never translated.** A `work_shapes` row carrying `"claude_only": true`
refuses every non-Claude vendor before any tier layer is read: its tier was chosen for a Claude
model, and rendering it as another vendor's execution class would staff that vendor at a tier
nobody decided. `implementation` (the `worker` role's shape, `opus/medium`) is the one such row
today. A role pinned to another vendor through it fails loud, naming the vendor; pin that role to a
shape without the flag, or unpin the vendor. The flag lives outside the portable subset shared with
the Codex plugin repository, so it needs no schema version change.

**Targeted review has its own work shape and needs no lens argument.** `targeted-reviewer` uses `targeted-review`,
whose default is `sonnet/high` and whose `unattended_step_down` is false. Other judgment
and review roles retain their defaults. The shape remains portable: a pinned non-Claude
vendor follows the normal palette translation. Orchestrate's high-risk second reviewer
uses an already-recorded staffing trio from another vendor when one is available.

**The translation has a hole, and it is the weakest rung.** The portable vocabulary has three names
(`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5`) and the Claude palette has four, so `haiku` has nothing
to translate through. Five work shapes resolve to `haiku` — `purely-mechanical`, `mechanical`,
`read-only-survey`, `implementation-test-gated` and `offload-test-gated` — and a role pinning a
non-Claude vendor on any of them fails loud rather than guessing. Giving the vendor palettes a fourth execution class is what closes it.

**Precedence — written here and in `staffing.py`, nowhere else.** For a work shape,
`resolve_shape` takes the first of these that is present (`staffing.TIER_PRECEDENCE`):

1. `operator` — the operator's explicit answer, passed as `answer=`. Today the one caller is the
   tier a plan unit records after the operator confirmed it in `/plan`'s table (`/work` passes it
   as `--plan-model` / `--plan-effort`). Admission's `staffing_overrides` answer does not reach
   this layer yet: admission stores it with source `operator` and skips resolution for it, so it
   wins by admission's own rule and is not checked against the palette. Routing it through
   `answer=` is follow-up work.
2. `overlay` — the per-repository overlay at `.saga/tier-defaults.json`.
3. `jev-raise` — a raise the tier judgment applied, recorded in the run record and passed as
   `jev_raise=` (written by admission and `tier_judgment.py plan`, issue #96). The resolver refuses a
   recorded raise that is not exactly one step above the work shape's default — one model rung or
   one effort rung, not both — that names `fable`, or that lands above the target model's raise
   ceiling (`sonnet/xhigh`, `haiku/max`).
4. `policy` — the shared `work_shapes` default.

One modifier applies after this order, never inside it: on an unattended run,
`intent_envelope.recommend_tier` takes the resolved tier and steps it one rung cheaper, unless the
work shape's row says `"unattended_step_down": false` (see below). It is the only tier modifier
outside `resolve_shape`.

Every layer is validated whether or not it wins. Admission, `/plan` (through
`lifecycle_state.py resolve-build-unit-tier`), `/work` and `intent_envelope.recommend_tier` all call
this resolver; a skill or caller that restates the order is a second copy waiting to drift, so they
name the resolver instead. `tier_resolver.resolve()` is the `policy` layer alone: calling it for a
staffing answer skips the three layers above it without an error.

On the command line "per-repository" means *relative to the working directory* — there is no
upward walk, so running from a subdirectory silently skips an overlay that exists at the repository
root. The `source` field in `--json` is how you tell: it names the layer from the list above. A
Python caller should pass `root=` explicitly rather than rely on the working directory; admission
passes its `--repo-root`. For a role: the role's own entry, which names a work shape and may pin a
vendor; where it names only a work shape the work-shape precedence applies. A lens only ever
narrows the answer — it attaches a qualification status that can downgrade a scoring executor to
the documented-policy outcome, and can never promote one.

**An undeclared build unit runs at the worker's shape.** `staffing.unit_work_shape_default()`
returns the `worker` role's `work_shape`, so re-pointing that role moves every undeclared unit with
it. **An unattended run steps one rung cheaper** (`intent_envelope.recommend_tier`) unless the row
says `"unattended_step_down": false`; `implementation` says false, because the builder's default is
what the run's cost-per-unit measurement checks.

**Failing loud.** An unknown work shape, role, vendor or lens, an off-palette model, an effort above
a model's ceiling, and a malformed overlay each raise with the offending value named. This component
sits on a path every subagent spawn reads, so a silent default would be invisible and wrong
everywhere at once.

**The tier judgment (issue #96).** `consult_tier_suggestions` asks the `tier` judgment verb, in
one request for a batch of units, whether each unit needs a weaker, the same, or a stronger tier
than its default, given the issue (title, body and keyword flags) and the unit (description, goal,
expected files, work shape). `classify_judgment` sorts each answer into a band, using the verb's
confidence floor (0.6) and automatic floor (0.8):

- a raise at 0.8 or above, on a tier no operator set, is `auto-raise`: `one_step_raise` moves it
  one step, effort first (one effort rung while the model's ceiling allows, else one model rung
  with the effort unchanged), never to `fable` and never past the palette's top effort;
- a raise from 0.6 up to 0.8, or any raise over an operator-set tier, is `confirm-raise` and waits
  for the operator;
- a raise with no step left (`opus/xhigh`, any `fable` tier) is `raise-at-ceiling`, shown only;
- a lower tier is `advisory-lower` and is **never** applied;
- below 0.6 an answer is `log-only`: logged, not shown.

The consult itself changes nothing. Its callers (saga's admission for each role, and
`tier_judgment.py plan` in `/plan` for each unit) record an `auto-raise` as the role's or unit's
`jev_raise`, which `resolve_shape` honors as its `jev-raise` layer above, and log each verdict with
`record_tier_verdicts` once the operator's final tier gives it a label (`tier_direction`). Decision
ids are `staffing/tier-direction:<repo>#<issue>:role:<role>` or `...:unit:<id>`, so the evaluation
harness can score each run's judgment separately. `INFIQUETRA_TYPESAFE_TIERING=off` returns before
the client is loaded and makes no request; a failed request leaves every default standing with the
reason. The full rule is §7 of [`typesafe.md`](typesafe.md).

**On the command line**, bare `--suggest` asks the same question about the one unit being
resolved; `--suggest model/effort` still records that tier as an advisory suggestion and makes no
call. The command line has no run record to hold a raise, so the output is the `default:`, a
`judgment:` line with the direction, confidence, both floors and the band it would take in a run,
a `reason:` line, and `applies:`, which is always the default. `--json` adds a `consult` block
with the status, band, proposed tier and reason. The verdict is logged with no label. The
`resolve` path itself still never calls out, so a staffing question can never depend on a service
being reachable.

## To add a model

1. Add a row to `staffing.json` under `"models"` with an explicit integer `rank` and an
   `effort_ceiling` (the strongest effort the model actually runs). Add a `raise_ceiling` only
   when an effort the model can run is not worth reaching by an automatic raise: sonnet carries
   `raise_ceiling: high` because sonnet/xhigh costs more per task than opus/high and scores lower
   (Artificial Analysis snapshot, 2026-10-07), so a raise from sonnet/high moves to opus/high.
   haiku carries `raise_ceiling: xhigh` because haiku/max scores lower than haiku/xhigh on the
   Coding Agent Index; `max` is haiku's read-only survey default, never a raise target. A
   raise never lands above the target model's raise ceiling. **Ranks must stay contiguous
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
   so a vendor that names its command differently silently inherits the default. The grok row is
   the worked example:

   ```json
   "grok": {
     "runtime_supported": true,
     "models": {"gpt-5.6-sol": "grok-4.6", "gpt-5.6-terra": "grok-4.5",
                "gpt-5.5": "grok-4.5"},
     "accepted_efforts": ["low", "medium", "high", "xhigh"],
     "effort_collapse": {"max": "xhigh"},
     "effort_application": "argv"
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
   resolves to `haiku` cannot be rendered, and one on a `claude_only` shape (`implementation`) is
   refused outright.
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

This cascade is the order a team-execution spawn picks a teammate's effort in. It is applied by
the spawning skill, not by code, and it is not a second tier precedence. Its first layer is the
precedence above: a plan-authored unit tier is resolved through `staffing.resolve_shape(work_shape,
root=…, answer=…)` as the operator's answer, which wins over every other tier layer. The team
default and the agent frontmatter apply only to a teammate with no plan-authored tier; no code
passes either one to `resolve_shape`.

A Claude agent file (`plugins/*/com.infiquetra.claude/agents/*.md`, inside the plugin's Claude
adapter) may carry an `effort:` frontmatter field, and its value must be one of `EFFORTS`. No lint in
this repository checks that field yet: the `tests/test_agent_tier_lint.py` and
`scripts/lint_agent_tiers.py` an earlier version of this page named are not here, so an
out-of-vocabulary value is caught only by review and by the harness's own warning.

## Effort honoring

`effort_rider.py` left with the saga-family catalog (issue #332). Fleet-core no longer injects an
effort rider into a prompt, reconciles a reported effort after a run, or renders a tier table.
`staffing.resolve_shape` and `tier_resolver.resolve` are the resolvers that remain. A Claude agent
file may still carry `effort:` frontmatter, and its value must be one of `EFFORTS`.

## What stays in this package

`capability_ratings` live only in `staffing.json`. The engine registry that used to copy them left
with the saga package. `tier_palette.py` and `tier_resolver.py` read the same staffing file for
vocabulary and work-shape resolution. Grow the vocabulary in `staffing.json`, never in a second
table. The tier-token guards in
`plugins/fleet-core/tests/test_tier_vocab_single_source.py` still fail a second vocabulary source.

## Wiring a new consumer

Load the module through the build-time bundle, never by file path — a path import works in a
checkout and breaks under the installed-plugin layout, where fleet-core lives in a versioned cache
directory. `scripts/bundle_fleet_module.py` writes each consumer's bundle at build time, and each
consuming plugin carries a small `bundled_fleet.py` loader. Reviews keeps its copy at
`plugins/reviews/scripts/bundled_fleet.py`, which loads a module from
`plugins/reviews/runtime/_bundled`:

```python
import bundled_fleet

staffing = bundled_fleet.load("staffing")
decision = staffing.resolve_shape("judgment")
```

Consuming this module means depending on the fleet-core version that introduced it. Say so in the
plugin changelog, and fail with a message naming both versions if the module is absent. This
machine carries two installed plugin roots, and a release has updated one and not the other
before, so a consumer that assumes the newer fleet-core is present will fail in one root and not
the other.

## Where to look

- The data: `plugins/fleet-core/scripts/fleet_commons/staffing.json`
- The resolver: `plugins/fleet-core/scripts/fleet_commons/staffing.py`
- Vocabulary and ladder operations: `plugins/fleet-core/scripts/fleet_commons/tier_palette.py`
- Work-shape and runtime resolution: `plugins/fleet-core/scripts/fleet_commons/tier_resolver.py`
- A consumer loader: `plugins/reviews/scripts/bundled_fleet.py`
- The bundle writer: `scripts/bundle_fleet_module.py`
- Guards: `plugins/fleet-core/tests/test_tier_vocab_single_source.py`,
  `plugins/fleet-core/tests/test_tier_resolver.py`,
  `plugins/fleet-core/tests/test_staffing_suggest.py`
