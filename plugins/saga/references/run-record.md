# The run record — `run_record.v1`

One JSON file per issue holds the whole state of that issue's run. It is written and read by
`plugins/saga/scripts/run_record.py`, and every later step of the run — plan review, the build loop,
code review, integrate, release, functional test, close, retro capture — reads it rather than
keeping state of its own.

This document is the contract. `tests/test_run_record.py` fails if the document and the code
disagree about the key set, the thirteen parameters, the version token or the refusal line, so the
two cannot drift apart silently.

**Source of the lifecycle vocabulary:** `infiquetra/infiquetra-sdlc` at revision `5efc869f` —
`docs/lifecycle/run-model.md` for the thirteen run-configuration parameters and
`docs/process/operator-escalations.md` for the seven approval boundaries.

## Where the file lives

```
<primary checkout>/.claude/saga/runs/issue-<N>.json
```

The path is **absolute** and is resolved from the git *common* directory, not from the process's
working directory:

```
git rev-parse --git-common-dir      # <primary>/.git, from the primary checkout AND from every linked worktree
```

The store root is that directory's parent plus `.claude/saga/runs`. This is the whole reason the
record is usable: a unit does its work in a worktree, `.claude/` is git-ignored, and a
repository-relative path would resolve to an empty directory inside that worktree. Issue 886's
fifth finding is that exact failure against the orchestrate plugin's `.orchestrate/` directory.

`resolve_store_root()` refuses, rather than guessing, when the common directory is not a `.git`
inside a checkout — a repository created with a separate git directory has no derivable checkout
root, and writing the record somewhere no later reader will look is worse than stopping.

## The version token

The top-level field is **`schema`** and its value is **`run_record.v1`**. The family name says which
artifact the file is, which a bare version number does not; it is the convention
`plan_pre_answers.v1`, `roles_index.v1` and `lifecycle_snapshot.v1` already follow.

Reading a record whose `schema` is anything else is refused with **one line** on standard error and
**exit 3** — never a Python traceback. Issue 975 (finding F124) reported precisely the opposite
arrangement in the orchestrate run file, where a known refusal reached the user as a six-frame
traceback because the command line called each subcommand bare while every subcommand opened with a
load. Here every loader call sits inside `main`'s single catch.

The line, exactly:

```
run_record: unknown record version 'run_record.v2' in /abs/path/.claude/saga/runs/issue-1023.json; this saga writes run_record.v1
```

### Exit codes

| Code | Meaning |
|---|---|
| exit 0 | success |
| exit 1 | an unexpected internal error |
| exit 2 | a refusal that is not a version mismatch: an unresolvable store root, a record that is not valid JSON, no record for that issue, or a card that fails the validator (`admission.py`) |
| exit 3 | an unknown record version |

## Unknown top-level fields

A top-level key this version does not know is **preserved unchanged** across a read and a write, and
is **reported by name** on read:

```
run_record: unknown top-level field 'a_newer_field' in <path>; preserved unchanged (this saga writes run_record.v1)
```

Issue 989 (finding F138) reported the silent-drop half of this: an unknown top-level key in the
orchestrate run file vanished on the next save, while an unknown *unit-row* key in the same file was
warned about by name. Preserving without warning would satisfy the letter of the rule and still
leave a reader unable to tell a newer writer from a typo.

A **missing** known key is not a refusal: it reads back as its empty default. That is how a record
written before a consumer landed presents, and refusing it would make every later child's first read
fail on a record this module wrote.

## The top-level keys

Twelve, in this write order. Anything else is an unknown field, handled as above.

<!-- BEGIN TOP-LEVEL KEYS -->

| Key | Type | Holds |
|---|---|---|
| `schema` | string | the version token, `run_record.v1` |
| `issue` | integer | the issue number |
| `repo` | string | `owner/name` of the repository the issue belongs to |
| `created_at` | string | ISO-8601 timestamp in UTC, set once at the first write |
| `updated_at` | string | ISO-8601 timestamp in UTC, refreshed on every write |
| `admission` | object | the questionnaire — see below |
| `run_configuration` | object | the thirteen parameters, each `{value, chosen_by, source}` |
| `approval_scope` | object | the seven approval boundaries, each with the scope granted or `none` |
| `roster` | array | one entry per staffed role: the role, its pane identifier, its session state |
| `units` | array | one entry per work unit: unit id, worktree, branch, merge-turn state, last mechanical-check result |
| `review_cycles` | array | one entry per cycle: cycle number, result, findings reference |
| `next_step` | string | the step the run is at |

<!-- END TOP-LEVEL KEYS -->

## `admission`

| Field | Holds |
|---|---|
| `card_validation` | `{performed, passed, errors}` from the card validator |
| `issue_review_checks` | which of the lifecycle repository's six issue-review checks were performed, and by whom; `not_performed` where no role was staffed |
| `answers` | every answered question: its id, the value, the source, and when it was answered |
| `pending_questions` | the questions still to put to the operator; empty means nothing is outstanding |
| `risk_tier` / `risk_justification` | the blast-radius tier and the one sentence saying why |
| `destination` | saga's routing intent: `plan-only`, `pr`, `merge` or `nonprod-deploy` |
| `branch_preview` | whether this repository has a branch preview deployment |
| `main_consumed_directly` | whether this repository's `main` branch is consumed directly |
| `change_shape` | `code`, `docs` or `mixed` |

### Two things called "destination"

`admission.destination` is saga's own four-value routing intent — the enum in
`plugins/saga/scripts/saga.py`. `run_configuration.nonproduction_destination` is the lifecycle
repository's parameter for *which lower environment* a run deploys to. They are different questions
that share an English word, and conflating them is the easiest mistake in this schema, so they are
separate fields in separate blocks and a test asserts that neither appears in the other's block.

## `run_configuration` — the thirteen parameters

These are the thirteen of the run model's "Run configuration — what is chosen before the work
starts": nine chosen by the Delivery Manager at orchestration setup, four by the Planner during
planning.

**They are not the thirteen `required_fields` of the `orchestrator-to-controller` contract.** That
is a handoff *message* shape, carrying `roster_hash`, `executors_and_topology`,
`session_reset_authority` and others that appear nowhere in the run model's table. Both sets number
thirteen, both live in the same repository at the same revision, and both look right — which is why
the test guards the distinction by **name** and not by count. The contract's shape is what the
roster helper and the close step *emit* from this block; it is not this block's key set.

<!-- BEGIN PARAMETERS -->

| # | Key | Chosen by | Where its default comes from |
|---|---|---|---|
| 1 | `staffing_models_and_efforts` | Delivery Manager | the staffing component in fleet-core |
| 2 | `concurrency_allocation` | Delivery Manager | the repository profile |
| 3 | `standard_cycle_allowance` | Delivery Manager | lifecycle default, 3 |
| 4 | `escalated_cycle_allowance` | Delivery Manager | lifecycle default, 2 |
| 5 | `escalation_trigger` | Delivery Manager | lifecycle default |
| 6 | `nonproduction_destination` | Delivery Manager | the repository profile |
| 7 | `unfinished_testing_response` | Delivery Manager | asked; a closed set of two |
| 8 | `applicable_lenses` | Planner | asked, with a proposal from the lens catalogue |
| 9 | `per_lens_score_threshold` | Planner | the lens catalogue's strictness ladder |
| 10 | `mechanical_tool_baseline` | Planner | the repository profile |
| 11 | `lens_execution_recovery` | Delivery Manager | lifecycle default |
| 12 | `repair_custody` | Delivery Manager | lifecycle default |
| 13 | `preflight_checks` | Planner | the repository profile |

<!-- END PARAMETERS -->

Each value is an object:

```json
{"value": 3, "chosen_by": "delivery_manager", "source": "lifecycle-default"}
```

`source` is one of `operator`, `profile`, `staffing`, `lifecycle-default` or `unset`, so a later
reader can tell an answer the operator gave from one a default filled.

## `units` — the keys a unit row carries

The row's content is named above as "unit id, worktree, branch, merge-turn state, last
mechanical-check result". The key set is deliberately **not** fixed: a consumer may add a key
inside a row without a version bump, because a row is one consumer's working state rather than a
cross-consumer contract. What is fixed is that a key another consumer does not know is left alone.

The orchestrate plugin is the first such consumer, and issue 1025 added three keys, documented here
so the two do not drift:

| Key | Holds |
|---|---|
| `merge_state` | where the unit stands in the merge-turn sequence: `ready`, `merging` or `merged`. Ordinary execution state, with no owner token and no expiry — a row left at `merging` by a turn that died is checked against git and released, never trusted |
| `launch_started_at` | when the driver persisted this unit's launch, written **before** the launcher is called. This is what makes a repeated launch call launch the unit once; there is no reservation |
| `shared_blockers` | blockers this unit meets, each naming the one unit that owns the repair, so two units never both repair the same thing. The driver only reads these; the producer is whoever notices the blocker |

The build loop is the second such consumer, and issue 1027 added one key under the same rule:

| Key | Holds |
|---|---|
| `build_loop` | the written exit criterion as it was read, one entry per loop iteration with every check's result, and — on the green iteration only — the full forty-character revision handed to code review. Its full contract, the three check statuses and the exit-code table are in `plugins/saga/references/mechanical-baseline.md`, documented there so the two do not drift |

Orchestrate also keeps its own run-level state under a top-level key named `orchestrate` — the run
branch, the base commit, the issue mapping and its review state. That key is unknown to this module
and is preserved unchanged across a read and a write, which is exactly the extension point the
"Unknown top-level fields" rule above describes. Orchestrate never writes `admission`,
`approval_scope`, `run_configuration`, `review_cycles` or `roster`.

## `approval_scope`

The seven categories, verbatim from the lifecycle repository's escalations chapter and from
`human_approval_state.approval_required_for` in the vendored
`plugins/mission-control/config/sdlc-schema.json`:

1. production changes
2. destructive operations
3. secrets or credential changes
4. IAM or permission changes
5. billing or cost-impacting actions
6. external commitments
7. major team or process authority changes

`null` means the category has not been answered. The string `"none"` means the operator granted
nothing in it. The two are deliberately distinguishable: the lifecycle repository treats an unscoped
grant as a **missing** boundary, not a wide one, and a role that meets one reports a blocker rather
than acting on it.

## `next_step`, and who wins

Both the run record and saga's envelope log carry a field called `next_step`. **The record wins.**

The record is the one file every role reads; the envelope log is append-only history whose older
ticks are *meant* to hold stale values. `saga.authoritative_next_step()` prefers the record and
falls back to the envelope only when there is no record. `saga.mirror_next_step_to_record()` is the
one write in the other direction: a tick that sets a next step updates the authority. Nothing
reconciles a stale tick back onto a live record.

## Writing: atomic replace, no lock

A write goes to a sibling temporary file and is then moved into place with `os.replace`, the same
pattern `saga.py` uses for its envelopes.

There is **no lock, no lease and no reservation**, and adding one is out of bounds: the parent issue
1018 forbids a new lease, reservation, receipt or ledger mechanism, and its stop conditions say to
stop and report if a child needs one to pass its own tests. One coordinator owns one run record and
the roles it dispatches report back to it, so simultaneous writers are not the normal case. A reader
that needs to know it holds the newest copy re-reads and compares `updated_at`.

## What this record replaces

Nothing in this table was deleted by the card that introduced the record. The record becomes the
place the state belongs; a module is deleted once every reader has moved, and the removals card
(issue 1030) takes the rest.

The **Status** column is what actually happened, so a reader can tell a plan from a fact. Issue 1028
removed one module and deferred three, each for a reason recorded here rather than left to be
rediscovered; issue 1027 removed a fifth with the ship ceremony.

| Store | Module | Replaced by | Status |
|---|---|---|---|
| Run-fact ledger | `run_ledger.py` | `units` and `review_cycles` | deferred to issue 1030 — sixteen production importers, fifteen of them modules that card deletes |
| Evidence-custody ledger | `evidence_ledger.py` | `review_cycles` and the functional-test state in `units` | deferred to issue 1030 — its sole production importer is `closure_gate.py`, whose whole subject is this ledger and which issue 1030 deletes along with its two dependents |
| Dispatch-settlement ledger | `dispatch_settlement.py` | `roster`, with its pane identifiers | deferred to issue 1030 — its importers are the outcome coordinator and the archived team-execution plugin, and it reads `run_ledger` |
| Effort ledger | `effort_ledger.py` | `run_configuration.staffing_models_and_efforts` | **removed by issue 1028**, with `effort-policy.yaml`; its only importer was its own test |
| Envelope tokens | `envelope_token.py` | `approval_scope` and the merge-turn field in `units` | issue 1030 |
| Ship receipts | `ship_receipt.py` | the merge and release state in `units` | **removed by issue 1027**, with the ship ceremony |

Two things stay and are not replaced at all: the saga envelope log under `.claude/saga/sagas/`,
which is the append-only history this single mutable file deliberately does not keep, and the spore
file under `<git-common-dir>/saga-spores/`, which is a transport across one compaction boundary
rather than a store.

## Command line

```bash
python3 plugins/saga/scripts/run_record.py show <issue>   # print the record as JSON
python3 plugins/saga/scripts/run_record.py path <issue>   # print the record's absolute path
```

`--store-root <dir>` overrides the resolution above. It exists for the tests and for reading a
record that belongs to another checkout; every test that touches a store passes it, because nothing
in the test suite may write into the primary checkout's live store.

## Related

- `plugins/saga/references/repository-profile.md` — the per-repository defaults admission reads.
- `plugins/saga/scripts/admission.py` — the step that fills this record's front section.
