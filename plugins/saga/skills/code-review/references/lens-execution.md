# Lens execution

How Code Review **executes** a resolved roster. It carries no lens catalogue of its own and restates
no numeric policy.

**Why this file is named the way it is.** It used to be `lens-catalog.md`, one letter away from
`config/lens-catalogue.json` in the lifecycle repository. Two documents a letter apart, one of them a
prose guide and the other the policy itself, is a collision a reader resolves wrongly at least some
of the time — issue 939 reported exactly that. The word "catalogue" now belongs to one document in
the system, and it is not this one.

## Where the lenses come from

Not from this plugin. `infiquetra/infiquetra-sdlc` — the lifecycle repository — owns
`config/lens-catalogue.json`: every lens, its dimensions, its anchors, the strictness ladder, the
acceptance shape, the finding schema and the status vocabulary. An application's quality profile may
raise a lens above its floor and may never lower one, redefine a lens, or shrink the always-on set.

A run's roster is resolved once, from five inputs, into one content-addressed document:

```bash
uv run python plugins/saga/scripts/review_roster.py --issue <N> --revision <full-sha> \
  --resolved-at <iso-8601>
```

That hash is the run's **only** pinning point. Every review and repair cycle of the run uses the same
roster unchanged; the next run resolves afresh.

## Reading a roster row

Each selected lens arrives as a row carrying what execution needs and nothing it should decide:

| Field | What execution does with it |
|---|---|
| `id` | Dispatches one reviewer for it, and records it on the result. |
| `always_on` | Nothing: the generator already selected it. A declaration cannot deselect one. |
| `scorable` | `false` means the lens reports findings and establishes no threshold. |
| `threshold` | The pair this lens must clear — `derived_overall_minimum` and `applicable_dimension_minimum`. Read, never computed. |
| `dimensions` | The dimensions the reviewer must account for, each scored or excluded with a cause. |
| `scoring_executor` | The one executor that owns the lens this cycle, with the verification entry that qualified it. `null` means no qualified executor, so no threshold. |
| `advisory_executors` | Further perspectives that report findings and never score. |
| `hosting` | The session and isolation the run recorded for this lens. |

## The four always-on lenses, and the eleven conditional ones

Four are always on and floor at `standard`: `architecture-maintainability`, `correctness`,
`security`, `testing`. The other eleven are selected by the Planner's declaration and floor at
`baseline`.

The eleven conditional lenses, by identifier, with the condition that selects each:

| Lens | Selected when the change... |
|---|---|
| `deployment-infrastructure` | alters infrastructure, deployment configuration, a migration or backfill, rollout or rollback order, or how deployed state is verified |
| `reliability` | alters failure handling, asynchronous work, concurrency, retries, cancellation, health signals, or recovery |
| `performance` | can materially affect latency, throughput, computational cost, query or index behaviour, input and output, memory, caching, capacity, or monetary cost |
| `api-contract` | alters a hypertext-transfer-protocol, event, command-line, configuration, exported-type or file-format contract, or anything that consumes one |
| `adversarial` | carries load-bearing assumptions, abuse potential, money, mutation, an external integration, a lifecycle or state-machine change, a policy or a gate, a deployment, agent orchestration, or a large or complex diff |
| `privacy` | alters personal or sensitive data collection, use, sharing, retention, deletion, residency, telemetry, or artificial-intelligence processing |
| `documentation-clarity` | changes documentation, specifications, runbooks, examples or help text, or requires them to change |
| `agent-usability` | adds or alters a capability, prompt, skill, command, tool schema, machine-readable result, or workflow an agent must discover or operate |
| `previous-comments` | is on a pull request carrying prior review comments or unresolved threads that still apply |
| `accessibility-human-usability` | materially affects a human-operated visual, interactive, content or command surface |
| `experience` | alters a user-facing surface or the path a person takes through one |

A conditional lens left out carries **one recorded line** saying why it does not apply to the work
unit. An empty section never satisfies the check — "not applicable" with no reason is a missing
answer, not a small one.

**The eleven report findings without scores today.** They carry no fixtures in the lifecycle
repository, so no executor can be qualified against them and no score of theirs would establish that
a threshold was met. A reviewer staffing one reports what it found and says plainly that it did not
score. That is a complete result.

## Dispatching a lens

Five things, and nothing else: the issue, the one lens identifier, the frozen revision, the roster
hash, and the vendor, model, effort and prompt hash the roster names.

The rubric is **not** copied into the brief. `plugins/agent-launcher/roles/lens-reviewer.md` tells the
session how to reach the lifecycle repository and read the catalogue for itself, so a brief names the
lens rather than restating it — which is what keeps one lens's brief free of another's findings.

Every dispatch names vendor, model and effort explicitly. An omitted model silently inherits the
host's, and an inherited configuration is an unverified configuration whose score establishes
nothing.

## What a lens returns

- A score for every applicable dimension, on the catalogue's integer 0-to-10 scale, against the
  catalogue's anchors.
- A recorded cause for every dimension it did not score. Silence is not a valid non-applicable.
- Findings, each with evidence at `path:line` on the reviewed revision.
- On a repeat cycle, a verdict on each prior finding — resolved, not resolved, or no longer
  applicable, with the evidence either way.

A reviewer reports what it did not examine in the same breath as what it did. An unexamined area
described confidently is worse than an admitted gap, because the reader cannot tell the two apart.

## Current score and repair accounting stay separate

Two different things, never combined. The current score is the implementation's score under that
lens's rubric, over the whole assigned scope. Repair accounting is a separate record of the previous
cycle's concerns: verified fixed, still unresolved, or newly found.

A worker's claim that something is fixed does not establish it. When the evidence is insufficient the
finding is `unresolved`, never `fixed-verified`. Repair counts never fold into the rubric score and
never become a second acceptance gate beside it.

## Persistent findings

A finding still unresolved through **two consecutive review results** is persistent, and the Planner
puts it in exactly one of four classes before another repair batch runs:

| Classification | Route |
|---|---|
| `out-of-scope` | A linked residual issue, opened immediately rather than at the end of the run. |
| `repairable-first` | It leads the next batch; a failed targeted repair escalates rather than being retried in place. |
| `evidence-gap` | The batch supplies the missing proof. |
| `disputed` | To the Architect, with the counterevidence. |

Persistence alone never interrupts the operator; a change to the issue's recorded intent does.

## What this plugin must never do

- Author, edit, or cache a lens catalogue.
- Compute a threshold, or apply one the roster did not carry.
- Score a lens the catalogue marks unscorable.
- Accept a result from an executor with no verification entry.
- Accept a result citing a roster other than the one frozen for this run.
- Add, drop, or reselect a lens mid-run. If a repair genuinely makes an unselected lens applicable,
  the Planner records it, the Delivery Manager brings it to the operator, and only operator approval
  produces a recorded amended frozen roster.
