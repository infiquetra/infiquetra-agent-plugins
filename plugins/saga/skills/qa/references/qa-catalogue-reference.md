# The strategy catalogue — ten situations, ten tools, ten thresholds

This replaces the nine-way risk taxonomy. The taxonomy asked "what kind of change is this?" and
left the checks to whoever was running. The catalogue asks "which proof does this change need?"
and answers it from data.

The rows themselves live in `saga/references/qa-catalogue.yaml`. This document explains them.
Where the two disagree, the YAML file wins — it is what the code reads.

## The shape of a row

| Field | Holds |
|---|---|
| `id` | the strategy identifier, used by the profile, the envelope and the judgment verb |
| `situation` | the change shape that selects it, in one sentence |
| `tool` | what runs it |
| `invocation` | the invocation shape, with the profile's values substituted |
| `file_patterns` | the patterns that select it, which a repository profile may override |
| `required_evidence` | the fields the envelope must carry for this strategy |
| `proof_boundary` | `hermetic`, `branch-preview`, or `non-production` |
| `threshold` | the mechanical rule code evaluates — never a judgment, never a score |
| `may_be_optional` | whether a repository may declare it optional |
| `driver` | the function that runs it, or `null` with a reason and a revisit condition |
| `cost_estimate` | the duration and direct cost the preflight sums against the ceiling |

A new strategy is a row plus a driver. It is never a rewrite of the skill.

## The proof boundary is a ladder

```
hermetic  ⊂  branch-preview  ⊂  non-production
```

A run at boundary B selects every strategy whose boundary is B **or narrower**, and records the
rest as `out-of-boundary` in the selection block. That is a fact about the selection, not a result
and not proof debt: a strategy the boundary excluded was never expected to run, so it owes nothing.

This is what lets one runner serve two boundaries. The build loop runs the same command at
`branch-preview` (issue 1027's scenario smoke); the functional test runs it at `non-production`.
One mechanism, two boundaries, one catalogue — the boundary is a flag, not a fork.

## The ten strategies

### `api-workflow` — non-production

A change to a deployed HTTP surface, handler, route, or authorization rule. It **delegates** to the
executor the profile declares, rather than issuing its own requests: the CAMPPS end-to-end canary
already owns this family, and a second implementation would be a second definition of the same
proof. Passes when the observed status or redirect class matches the declared expectation and every
declared response marker is present.

### `contract-check` — hermetic

A change to an OpenAPI document, event schema, generated client, or pinned contract package. Runs
the repository's declared contract-diff command. Passes when the drift result is empty, or holds
only changes the profile marks permitted.

### `app-ui` — branch-preview, declared without a driver

A change to application widget or screen behaviour, at a declared target variant. Ships no driver:
the repository that declares this catalogue has no application surface and no target to prove one
against, and an unexercised driver is worse than a strategy that says it cannot run. Reopens with
the first repository whose profile declares it.

### `hosted-surface` — non-production, declared without a driver

A change touching a non-application hosted page — identity provider, payment, marketing. Ships no
driver for the same reason and with the same revisit condition.

### `cli-smoke` — hermetic

A change to a command-line entry point, console script, or plugin script. Runs each invocation the
profile declares under the repository's own runner. Passes when each exits zero and, where the
profile declares a version probe, the reported version matches the deployed version marker.

### `deploy-boundary` — non-production

Any change that reaches a deployed environment. Probes the edge for the deployment marker. Passes
when what the edge serves equals the revision the release step recorded. With no recorded base URL
and revision it is `blocked`, because there is no edge to probe — never `passed`.

### `data-check` — non-production, declared without a driver

A change to a schema, migration, write path, or idempotency key. Which store it reads and with
which credential is an approval the operator owns, so the driver waits for that decision.

### `infrastructure-read-back` — non-production, declared without a driver

A change to infrastructure roles, cluster or network configuration. Reaching the cluster needs a
credential the operator owns, so the driver waits for that grant.

### `installed-surface` — hermetic

A change to a Claude plugin's skills, commands, agents, or metadata. Reads **every** installed
plugin root, not only the one the session runs from, and resolves them rather than hard-coding
them. Passes when every root resolves the expected version and carries every expected surface.

This repository's operating history is why "every root" is load-bearing: six consecutive releases
updated one installed root and not the other, and a check that read only the live root would have
passed every one of them. Roots that disagree on a version are a **failure**, not a warning.

### `manual-runbook` — non-production, no driver by definition

Automation is unavailable, unsafe, or needs operator-held credentials. A person runs the runbook
and records the evidence; there is nothing for a driver to execute. It is the escape hatch, and its
`blocked` result names the runbook rather than pretending a check ran.

## What is not in this catalogue

No visual regression and no golden-image comparison. No performance or load strategy. No paid
external service — no device farm, no hosted browser grid, no commercial monitor; local toolchains
and open-source tools only. No production target: the destination is non-production.

None of these is an oversight. Each is a decision recorded in
`docs/brainstorms/2026-09-19-qa-testing-strategies-requirements.md`, and a paid service in
particular is an external commitment only the operator may make.
