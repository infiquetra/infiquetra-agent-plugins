# Evidence, the profile, the verdict, and the route

This replaces the old report reference. The old one described a durable markdown artifact under
`docs/qa/`, a content-addressed write into the evidence-custody ledger, and a 0-100 number derived
from counting model-assigned severities. None of those exists now. The evidence lives in the run
record, the ledger is gone, and the verdict is counted from three values.

## The repository profile

One optional `qa` block inside the tracked `.saga-profile.json` at the repository root. It is a key
in the existing profile rather than a file of its own, on the same grounds that made
`branch_preview_command` an optional key: an optional key leaves every existing profile valid and
does not move the `repository_profile.v1` token. A repository should describe itself in one place.

```json
{
  "qa": {
    "schema": "qa_profile.v1",
    "ceiling": { "max_duration_seconds": 600, "max_direct_cost": 0 },
    "strategies": {
      "cli-smoke": {
        "required": true,
        "commands": [{ "name": "…", "command": "…" }],
        "scenarios": ["…"]
      }
    }
  }
}
```

| Key | Holds |
|---|---|
| `required` | a required strategy that is blocked stops the run; an optional one is proof debt |
| `file_patterns` | overrides the catalogue row's patterns for this repository |
| `environment_variables` | names only. An unset one makes that strategy `blocked`, naming it |
| `secret_handles` | operator-held credentials. A missing one refuses the **whole** selection |
| `commands` | the declared invocations, for the strategies whose driver runs commands |
| `scenarios` / `mandatory_scenarios` | the scenario identifiers the plan may name |
| `entrypoint` | the executor a delegated strategy hands off to |
| `targets` | the declared, installed target variants |
| `permitted_changes` | contract drift this repository accepts without failing |
| `plugins` / `expected_surfaces` | what `installed-surface` must find in every root |
| `cost_estimate` | overrides the catalogue row's estimate |
| `ceiling` | the per-run budget. **Absent is refused** — an absent ceiling is not an unlimited one |

The shape is `saga/references/qa-profile.schema.json`.

**Two refusals.** A repository with no `qa` block is `blocked`, naming the file and the missing
key. A profile whose strategies are all optional is `blocked`, because such a profile would let a
run report a pass having proved nothing.

**Who writes a scenario.** The Planner, at plan time, from the profile's declared set. `/qa` never
writes its own: a functional test that authored its own scenarios would be grading its own
homework. A scenario the plan names that the profile lacks blocks and asks the planner.

## The evidence envelope

Exactly one envelope per strategy run, appended to the run record. Sixteen required fields; the
shape is `saga/references/qa-envelope.schema.json`.

| Field | Holds |
|---|---|
| `envelope_id` | this envelope's identifier |
| `schema` | `qa_evidence_envelope.v1` |
| `scenario_id`, `scenario_version` | which scenario ran, and at which version |
| `profile_revision` | which revision of the profile selected it |
| `environment` | which environment it ran against |
| `strategy_id` | the catalogue row |
| `proof_boundary` | the row's boundary |
| `proof_mode` | `automated`, `manual`, or `hybrid` |
| `result` | `passed`, `failed`, or `blocked` — and there is no fourth value |
| `status_reason` | what it proved, or why it could not |
| `started_at`, `completed_at`, `duration_seconds` | when and how long |
| `estimated_cost`, `observed_cost` | against the ceiling |
| `privacy_attestation` | what the driver captured and what it removed |
| `artifact_pointers` | paths, never captured values |
| `evidence` | the row's `required_evidence` fields, redacted |

**Redaction happens inside the driver, before the envelope exists** — not at report time. A
redaction applied on the way out would mean the secret had already been written down once. The
pattern set is fleet-core's, which is already in production use, plus the bearer-token and
authorization-header shapes the CAMPPS driver model names.

**Artifact pointers carry paths, never values.** A pointer that embedded a response body would
carry the secret the redaction had just removed from the envelope.

## Where it is written

The run record, under the top-level `qa` key — the documented extension point for a key this
record's own module does not know, which it preserves unchanged across a read and a write and
reports by name. A unit row would be the wrong home: a functional test is a property of the run
after the merge, not of one unit's working state.

The block carries the selection with a reason per entry, the out-of-boundary list, the preflight
result, every envelope, the verdict, the route, and any proof debt.

## The verdict

Arithmetic over the envelopes, performed by code. Nothing is weighted and nothing is scored.

| Verdict | When |
|---|---|
| `pass` | every required strategy returned `passed` |
| `pass-with-proof-debt` | every required strategy returned `passed`, and at least one optional strategy returned `blocked` |
| `fail` | anything else |

A strategy the boundary excluded is not in this arithmetic at all: it is a selection fact, not a
result, so it is never proof debt either.

## The route

| Situation | Route | Exit code | Why |
|---|---|---|---|
| every required strategy passed | close | 0 | the shipped thing works |
| proof debt | close | 0 | the debt, its reason and its revisit condition are recorded and named in the closing comment |
| a required strategy failed | the build loop | 4 | a failure is something the loop can repair, under the post-merge repair allowance |
| a required strategy is blocked | the operator | 5 | its causes are environment, credential and permission — the operator's approval boundaries, which no loop repairs |
| the preflight refused, or the profile proves nothing | the operator | 2 | nothing ran, so nothing was proved |

The last two are why a failure and a block have different exit codes. Folding them together would
send a missing credential to a loop that cannot produce one.

## The comment

One comment per run, carrying the selection with its reasons, the per-strategy statuses, the
out-of-boundary list, the artifact pointers and any proof debt. The runner prints it; publishing it
is one `gh issue comment` with the printed body.

The comment exists because of a specific complaint: from the old report, the operator could not
tell which checks ran and which were quietly skipped. Every strategy the run selected appears in
this comment with its result, and every strategy the boundary excluded appears with its reason.
