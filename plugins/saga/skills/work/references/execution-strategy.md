# Execution Strategy — how work gets executed

How `/work` sizes a build, turns a plan into a task list, picks an execution strategy, dispatches
subagents safely, commits incrementally, and recommends an execution backend. Adapted from CE
`ce-work`'s execution mechanics; the backend recommendation lands the deferred operator-choice helper.

## Complexity triage (Phase 0.5)

For a fresh build (no `pr_refs` on the saga), size the run before executing:

| Complexity | Signals | Action |
|---|---|---|
| **Trivial** | 1-2 files, no behavioral change (typo, config, rename) | Implement directly — no task list, no execution loop. Still apply Test Discovery if the change touches behavior-bearing code. |
| **Small / Medium** | Clear scope, under ~10 files | Build a task list from the plan's Implementation Units, then execute the loop. |
| **Large** | Cross-cutting, architectural decisions, 10+ files, touches auth/payments/migrations | If it arrived as a bare prompt, recommend `/plan` first to surface edge cases and scope boundaries; honor the operator's choice. If proceeding, build the task list and continue. |

A plan-doc input has already been through `/plan` and `/doc-review`, so it skips the bare-prompt bounce —
the triage here only sizes the execution strategy.

## Task list from U-IDs

Build the task list from the plan's `Implementation Units`. **Preserve each unit's U-ID as a task-subject
prefix** (e.g. "U3: add parser coverage"). This keeps blocker references, deferred-work notes, and the
final summary anchored to the same identifier the plan and the saga use, so traceability survives plan
edits and round bumps.

For each unit, carry:

- the **Goal** and **Approach** (what to build, how the plan framed it),
- the **Files** section (Create / Modify / Test paths — also feeds the Parallel Safety Check),
- the **Execution note** (test-first / characterization-first posture, when present),
- the **Patterns to follow** (specific files/conventions to mirror — read them before implementing),
- the **Verification** field (the primary "done" signal; also the already-shipped check),
- the **Test scenarios** (the starting point for Phase-3 scenario completeness).

Order tasks by dependency. Include test and quality-check tasks. Do not expect the plan to contain
implementation code, micro-step TDD instructions, or exact shell commands — the plan is decisions, not a
script. Do not re-scope plan units into human-time phases; agents execute at agent speed, and
context-window pressure is handled by subagent dispatch below, not by phased sessions.

## Execution-Strategy table

After the task list, pick how to execute from task count and dependency structure:

| Strategy | When to use |
|---|---|
| **Inline** | 1-2 small tasks, or tasks needing operator interaction mid-flight. The default for trivial and small builds. |
| **Serial subagents** | 3+ tasks with dependencies. Each subagent gets a fresh context window focused on one unit — prevents context degradation across many tasks. Requires plan-unit metadata. |
| **Parallel subagents** | 3+ tasks that pass the Parallel Safety Check below. Dispatch independent units simultaneously; run dependent units after their prerequisites complete. Requires plan-unit metadata. |

This strategy choice (inline / serial / parallel **subagent dispatch**) is the *mechanical* "how do I run
the units" decision and is independent of the recorded **backend** below, which is the
operator-choice contract for *which runtime owns the work*. Since issue #1030 that contract has one
value, `inline`, so the only live decision here is the mechanical one above.

## Parallel Safety Check (required before parallel dispatch)

1. Build a **file-to-unit mapping** from every candidate unit's `Files:` section (Create, Modify, Test).
2. Check for **intersection** — any file path appearing in 2+ units is an overlap.
3. **Overlap AND worktree isolation unavailable** → downgrade to serial subagents. Log the reason
   ("Units 2 and 4 share `config/routes.py` — using serial dispatch"). Serial still gives context-window
   isolation without shared-directory write races.
4. **Overlap AND worktree isolation available** → parallel is still safe; the overlap surfaces as a
   predictable merge conflict the orchestrator resolves in the post-batch merge. Log the predicted
   overlap so the post-batch flow knows which merges to expect conflicts on.

Even with no file overlap, parallel subagents sharing the orchestrator's working directory face git index
contention and test interference. Worktree isolation eliminates both; the shared-directory fallback
constraints below mitigate them.

## Subagent dispatch (U-ID preservation)

Use the generic `Explore` / `Task` agents for judgment and code-authoring units.  Do **not** reference
named `ce-*` agents.  For each unit, give the subagent: the full plan path (overall context), the
unit's Goal / Files / Approach / Execution note / Patterns / Test scenarios / Verification, any resolved
deferred-implementation questions, and the instruction to check the unit's test scenarios against all
four applicable categories (happy / edge / error / integration) and supplement gaps. **Preserve the
U-ID** in the dispatch and in everything the subagent reports back.

**Mechanical units (census, file-exist checks, JSON validation, grep counts, link checks) run
inline in this session.**  They were dispatched to a dedicated cheap-tier Bash-only agent until issue
1030 removed both saga agents; the work is a shell command and a read of its output, which costs less
run here than it costs to stand an agent up for it.  Run the command, read the result, and carry on —
the point of the old agent was to keep the tier cheap, and inline is cheaper still.  Example:

```
glob: plugins/*/agents/*.md
```

The mechanical executor is **inert until called** — it has no auto-trigger and takes no action without
an explicit dispatch from the calling skill.

- **Worktree-isolated:** subagents may stage, commit, and run their unit's tests inside their own worktree
  branch. After the batch, merge those branches in dependency order; on a merge conflict, abort
  (`git merge --abort`) and re-dispatch that unit serially against the merged tree (never hand-resolve
  silently — that discards one unit's intent). Then clean up: unlock, `git worktree remove`, `git branch
  -d`.
- **Shared-directory fallback:** instruct each subagent **not** to `git add`, commit, or run the project
  suite — the orchestrator handles staging/testing/committing after the whole batch completes. Cross-check
  the *actual* files each subagent modified (not just declared `Files:`); a shared-file collision means
  only the last writer survived — commit non-colliding files first, then re-run the colliding units
  serially.

Omit the `mode` parameter when dispatching so the operator's permission settings apply (do not pass
`mode: "auto"`).

## Incremental-commit heuristic

After each logical unit, decide whether to commit:

| Commit when… | Don't commit when… |
|---|---|
| A logical unit is complete (model, service, component) | It's a small part of a larger unit |
| Tests pass + meaningful progress | Tests are failing |
| About to switch contexts (backend → frontend) | Purely scaffolding with no behavior |
| About to attempt a risky/uncertain change | The message would be "WIP" or "partial X" |

**Heuristic:** "Can I write a commit message describing a complete, valuable change? If yes, commit. If
it would be 'WIP', wait." Use the plan's Implementation Units as a starting guide for commit boundaries,
adapting to what you find. Stage only the files for that logical unit (not `git add .`). Use clean
conventional messages with **no attribution footers**.

## Effort accounting — the run record, not an escrow ledger

The effort-escrow ledger and its policy file are **removed** (issue 1028). What replaced them is the
run record's `run_configuration.staffing_models_and_efforts`: the model and effort each role runs at,
decided once at admission and readable by every later step from one file.

Nothing accrues, refunds or escalates per unit any more. A unit whose work looks likely to need a
different tier is a staffing question, and it goes to the operator as one rather than through an
allocation arithmetic nobody was reading.

## Already shipped → verify, don't reimplement

Before implementing a unit, check whether its work is already present and matches the plan's intent —
files exist with the expected capability, or the unit's `Verification` is already satisfied. If so, the
work likely shipped on a prior branch/round/session. **Verify it matches, mark the task complete, and
move on. Do not silently reimplement.** This matters most on round-N re-entry, where earlier rounds
already landed some units.

## Backend recommendation — `recommend_execution_backend()` (Phase 1.4)

`/work` lands the deferred operator-choice helper (operator-choice §7). Since issue #1030 archived
the `team-execution` plugin and removed the `cc-workflows` plugin there is one backend, `inline`, so
the helper's job is no longer to choose between backends — it is to compute the work shape and
return the rationale the run records. Call the CLI:

```bash
python3 plugins/saga/scripts/lifecycle_state.py recommend-backend \
  --file-count <N> --phase-count <N> \
  [--has-security] [--has-infra] [--cross-repo] [--deployment-sensitive] \
  [--needs-consensus] [--broad-fanout] [--adversarial-confidence] \
  [--workflow-shape <understand|design|research|review|migrate>]... \
  [--release-surface-file-count <N>] \
  [--no-code-surface] [--no-workflow] \
  [--workflow-availability-source probed|asserted]
```

It returns JSON: `{recommended, rationale, alternatives, backends, workflow_availability}`.
`recommended` is always `inline` and `alternatives` is always empty, because issue #1030 archived
every other backend. `backends` is the full-enumeration payload — one ordered `{backend, status,
note}` entry for `inline` with `status` in `{recommended, alternative, unavailable}`; the enumeration
contract is that no backend is ever silently dropped, not that the list has a particular length.
`workflow_availability` echoes `{available, source}`, where `source` is `probed` or `asserted`
(KTD3) — kept because a caller that probed the host is entitled to see what the probe said, even
though nothing now turns on it.

The same signals are still computed — `should_offer_team_execution`'s thresholds (functional file
count — raw `--file-count` minus `--release-surface-file-count` — ≥ 8, phase_count ≥ 4, security,
infra, cross-repo, deployment-sensitive) or a gated needs-consensus signal — but since issue #1030
they select the `rationale` the run records rather than a different backend. An unknown
`--workflow-shape` value still raises loud (`ValueError`) — never a silent downgrade. Pass `--release-surface-file-count` for the count of
release-bookkeeping files (plugin.json, marketplace.json, CHANGELOGs, version drift pins) inside
`--file-count` — they carry no functional risk and must not trip the size trigger on their own. Pass
`--no-code-surface` for pure docs/spec/research output: it voids the code-shaped proxies (size, and the
`has_infra` / `has_security` keyword flags that false-positive on docs) so a big docs change isn't
counted as escalating on its size alone — only `--cross-repo` and gated `--needs-consensus` do that. Set
`--adversarial-confidence` ONLY on an explicit operator request for many-independent-attempt verification
(refute-N, a judge panel, perspective-diverse lenses) — not inferred from generic "make me more confident"
phrasing, and not when 1-3 review lenses would do; that bar keeps confidence work from over-routing to
ultracode. `alternatives` lists every reachable backend **independent of which one won precedence**, so
an overlap job (consensus AND fan-out) still offers both — escalation stays one step (operator-choice
§3.3).

**Do not surface a question.** With one backend there is nothing to ask and nothing to pre-select;
an offer whose only option is the default is ceremony. Record `inline` via the saga's
`--orchestration-mode` (Phase 1.4) — that is the durable home for the choice (operator-choice §6) —
and pass the helper's `recommended` value to `--orchestration-recommended` as the bare enum string,
since that flag takes `choices=ORCHESTRATION_MODES` rather than the JSON object. R12 telemetry still
sees recommended-vs-chosen, which is the point of writing both even when they agree.

## Build-unit tier resolution — `resolve_build_unit_tier()` (Phase 2)

When Work directly launches a build unit (an Implementation Unit executed as a direct build unit),
resolve its `{model, effort}` by running the resolver:

```bash
python3 plugins/saga/scripts/lifecycle_state.py resolve-build-unit-tier \
  --plan-model <model> --plan-effort <effort>      # explicit plan tier
python3 plugins/saga/scripts/lifecycle_state.py resolve-build-unit-tier \
  --work-shape <shape>                             # no explicit tier
```

An explicit `{model, effort}` on the plan unit wins on **precedence** — and is validated against the
same vocabulary the shape path resolves from, so a model or effort the registry does not carry is
refused rather than passed through to a spawn. Otherwise the work shape is selected and resolved
through the shared registry: the `work_shapes` block of
`plugins/fleet-core/scripts/fleet_commons/staffing.json` via
`tier_resolver` / `tier_defaults`. When a unit declares neither a tier nor a work shape, the selected
shape is `mechanical` — bounded, specified work per `/work`'s own execution context and the middle
rung that bounds either-direction error (KTD7) — so the resolver with neither argument resolves the
`mechanical` row from `staffing.json`, not a literal at the spawn site. Values stay in that
registry; this file only names the shape-selection rule — `resolve_build_unit_tier` in
`lifecycle_state.py` is the single delegation seam behind the subcommand. **The resolver takes no
host or session input at all**, which is what makes inheritance impossible: it cannot consult a host
tier it is never given. Record the resolved tier in the Phase-4 work-session execution evidence for
both the explicit and defaulted case.
