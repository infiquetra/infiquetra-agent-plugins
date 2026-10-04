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
| `lens_proposal` | the Jev lens proposal issue #110 writes: `{probabilities: {<lens>: 0.0–1.0}, ...}`. `admission.py --render` reads `probabilities` for the lens table's Jev probability column: 0.8 and above reads pre-checked, 0.6 up to 0.8 reads consider, and lower is kept in the JSON only. Absent until #110 lands, and the column reads `not configured` |

### The two answers admission validates

Admission checks two answers before it records anything, and a refusal exits 2 with one line
naming the problem (issue #103). Whoever supplies them — the plan skill from the conversation, or
the Claude Code review pane through `admission.py --answers -` on standard input — goes through the
same check.

- **`staffing_overrides`** is `"none"` (or null, or `{}`) to take the defaults, or a map of role to
  `{vendor, model, effort}`, exactly those three keys. Every role is one the staffing component
  staffs, the vendor is that role's own, and the model and effort are a pair the tier palette lists
  (so `haiku` stops at `high`, and `max` is never one). A partial map is merged role by role onto
  `run_configuration.staffing_models_and_efforts`: a named role takes the answer and is marked
  `operator_override: true`, every other role keeps its recorded row, and the parameter's source
  becomes `operator`. The plan skill and the pane both send the complete role map.
- **`lens_declaration`** is `{always_on, conditional_applies, conditional_does_not_apply}` and lands
  as `run_configuration.applicable_lenses`: `always_on` a list, `conditional_applies` a map of lens
  to the reason it applies (a plain list is accepted), and `conditional_does_not_apply` a map of
  lens to a non-empty reason. No lens is in both maps and no always-on lens is in either. When the
  lens catalogue is readable, `always_on` is its always-on set and every conditional lens is in
  exactly one map; when it is not, only the shape is checked.

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

### The staffing rows the admission tables read

`staffing_models_and_efforts.value` maps each role to `{vendor, model, effort}`. A key that starts
with `_` is run-wide, not a role. `admission.py --render tables|json` reads these keys beside the
tier, and every writer must put them here so the staffing table can find them:

| Key | Where | Written by | Holds |
|---|---|---|---|
| `suggestion` | per role | `admission.py --suggest` today | the advisory Jev tier: `{suggested, confidence, usable, low_confidence, reason}` |
| `tier_judgment` | per role | issue #96 | `{band, confidence, default, proposed, applied, shown, reason}`; `band` is one of `agrees`, `auto-raise`, `confirm-raise`, `advisory-lower`, `raise-at-ceiling`, `log-only`, `not-consulted` |
| `jev_raise` | per role | issue #96 | `{model, effort, confidence, reason, decision_id}`; one step above the default, never fable or max |
| `operator_override` | per role | admission's per-role merge (issue #103) | `true` on a role the operator's answer named |
| `_tier_judgment` | run-wide | issue #96 | `{status, note}`; `status: "off"` means the judgment is switched off |

A `staffing_overrides` answer is merged per role (see "The two answers admission validates"
above), so `operator_override` marks exactly the roles the operator's answer named.

## `units` — the keys a unit row carries

The row's content is named above as "unit id, worktree, branch, merge-turn state, last
mechanical-check result". The key set is deliberately **not** fixed: a consumer may add a key
inside a row without a version bump, because a row is one consumer's working state rather than a
cross-consumer contract. What is fixed is that a key another consumer does not know is left alone.

Each key that sits directly on a unit row is listed in a table between `<!-- BEGIN UNIT ROW KEYS -->`
and `<!-- END UNIT ROW KEYS -->` markers below, one block per consumer. Tables outside those markers
describe keys nested inside a row's block (such as a `usage` entry's fields), not row keys.
Orchestrate's tests read these blocks to keep its list of quietly carried keys matched to this
contract, so a new row key belongs in a marked table.

**The round-trip rule for every whole-row writer.** A writer that rewrites a whole unit row, or the
whole `units` array, writes only the keys it owns from memory and carries every other key forward
from the row as it is on disk when it writes, re-read under the record lock (see "Writing" below).
Carrying them forward from the copy it loaded earlier is not enough: that copy misses whatever
another writer added since. The same holds for top-level keys: everything the writer does not own
comes from the fresh re-read. A writer that adds a key to one row in place follows the same
lock-and-re-read sequence, as the build loop does under `file_lock`. Orchestrate's `Run.save`
follows this rule since issue 113; before it, a load and save through orchestrate dropped
`build_loop`, `usage` and every other key its `Unit` did not declare. Orchestrate owns the keys its
`Unit` declares and which rows exist: a row `start` creates fresh carries nothing forward, and a row
orchestrate does not hold is not written back.

The orchestrate plugin is the first such consumer, and issue 1025 added three keys, documented here
so the two do not drift:

<!-- BEGIN UNIT ROW KEYS -->

| Key | Holds |
|---|---|
| `merge_state` | where the unit stands in the merge-turn sequence: `ready`, `merging` or `merged`. Ordinary execution state, with no owner token and no expiry — a row left at `merging` by a turn that died is checked against git and released, never trusted |
| `launch_started_at` | when the driver persisted this unit's launch, written **before** the launcher is called. This is what makes a repeated launch call launch the unit once; there is no reservation |
| `shared_blockers` | blockers this unit meets, each naming the one unit that owns the repair, so two units never both repair the same thing. The driver only reads these; the producer is whoever notices the blocker |

<!-- END UNIT ROW KEYS -->

The build loop is the second such consumer, and issue 1027 added one key under the same rule:

<!-- BEGIN UNIT ROW KEYS -->

| Key | Holds |
|---|---|
| `build_loop` | the written exit criterion as it was read, one entry per loop iteration with every check's result, and — on the green iteration only — the full forty-character revision handed to code review. Its full contract, the three check statuses and the exit-code table are in `plugins/saga/references/mechanical-baseline.md`, documented there so the two do not drift |

<!-- END UNIT ROW KEYS -->

Cost measurement is the third consumer, and issue 95 added one key, `usage`, owned by
`run_record.py` itself:

<!-- BEGIN UNIT ROW KEYS -->

| Key | Holds |
|---|---|
| `usage` | `{"entries": [...]}`, one entry per model session that worked the unit; the entry fields are in the next table |

<!-- END UNIT ROW KEYS -->

`run_record.py usage add` is the one portable write path: any harness integration calls it
with the counts it read from its own session, including the Claude Code token-capture mod. Build
loop passes and review cycles are not copied into it; the cost report reads them where they already
live (`build_loop.iterations` on the row, and `review_cycles` at the top level).

**Claude Code sessions write live (issue #107).** The saga adapter's token-capture mod
(`com.infiquetra.claude/mods/usage-capture.ts`) runs `run_status.py --repo-root <session directory>
unit-for --json` once at session start. It matches the unit row whose `worktree` is the session's
checkout (role: the row's `role`, else `worker`), whose `merge_worktree` is (role
`merging-worker`), or, failing both, whose `branch` is checked out there, across every record in
the store; a worktree match outranks a branch match, then an active record, then the newest. No
match, and the session records nothing. A matched session sums each model request's usage, main
thread and subagents alike, per session id (a subagent's loop is `<session>/<agent id>`), role,
model and effort, and every minute and at session end calls `usage add --store-root <store>` once
per sum. A sum is subtracted only after its `usage add` exits 0, so a failed write is retried with
whatever arrived since. A write killed by its timeout after the record was replaced would count
twice on the retry; the timeout (ten seconds) is far above the measured cost of one write. Claude
Code reports cache writes as one count with no five-minute or one-hour split, so the mod records
them under `cache_write_1h`, the dearer rate: the cost report can overstate cache-write spend from
these sessions, never understate it. A subagent whose agent type is `saga:<role>` records as that
role; any other subagent records as the session's role. A request with no effort records `none`.

An entry is identified by its session id, role, vendor, model and effort. The first `usage add`
for that identity appends an entry; a later one adds its counts into the same entry, increments
`additions` and moves `last_added_at`, so a harness may report a long session as several deltas.
A blind retry of the same delta therefore counts twice. Each entry records its own role, vendor,
model and effort because nothing else in the record says which role and tier worked a unit.

<!-- BEGIN USAGE ENTRY KEYS -->

| Key | Holds |
|---|---|
| `session_id` | the model session's identifier, as the harness names it |
| `role` | the staffing role that ran the session: `worker`, `lens-reviewer`, `functional-tester`, and so on |
| `vendor` | the vendor, e.g. `claude` |
| `model` | the model id, e.g. `claude-opus-5-5`, or a staffing alias such as `opus` |
| `effort` | the effort level the session ran at, e.g. `medium` |
| `counts` | an object holding all five categories below, each a non-negative integer |
| `first_added_at` | ISO-8601 timestamp in UTC of the first addition |
| `last_added_at` | ISO-8601 timestamp in UTC of the latest addition |
| `additions` | how many `usage add` calls have added into this entry |

<!-- END USAGE ENTRY KEYS -->

The five categories are billed at five different rates, so they are counted apart. The names carry
no "token" suffix on purpose: the repository's credential scanner reads any key containing that word
as a credential.

<!-- BEGIN TOKEN CATEGORIES -->

| Category | `usage add` flag | Messages API `usage` field | Pricing-page rate |
|---|---|---|---|
| `uncached_input` | `--uncached-input` | `input_tokens` | Base input |
| `cache_read` | `--cache-read` | `cache_read_input_tokens` | Cache hits and refreshes |
| `cache_write_5m` | `--cache-write-5m` | `cache_creation.ephemeral_5m_input_tokens` | 5m cache writes |
| `cache_write_1h` | `--cache-write-1h` | `cache_creation.ephemeral_1h_input_tokens` | 1h cache writes |
| `output` | `--output` | `output_tokens` | Output |

<!-- END TOKEN CATEGORIES -->

`usage add` refuses, with exit 2 and one line, an unknown category flag, a negative count, a
session id that is empty or holds whitespace or a control character, a vendor, model or effort that
is not a name (letters, digits and `. _ : / @ + -`, starting with a letter or digit), a role that is
not lowercase letters, digits and hyphens, a unit the record does not have (it names the units the
record does have, and never creates a row), a stored entry whose counts are not non-negative
integers, and an issue with no record. `--unit` takes the row's `id`, else its `name`, else its
`unit_id` (`run_record.unit_key`), the rule `build_loop.py --unit` and the cost report also use.
`merge_turn.py --unit` reads the same three keys in the order `name`, `unit_id`, `id`, so the two
rules name a row differently only when it carries both an `id` and a `name` that differ; give such
a row the same value in both. Every other key survives an addition: the row's other consumers'
keys, unknown keys inside the usage block, and every other row.

**What a completed unit is.** `scripts/cost_report.py` prices usage from the dated table in
`references/model-prices.yaml` and divides by completed units. A unit is completed when its build
loop went green (`build_loop.handed_to_code_review` is present) and its latest `review_result.v2`
code-review entry has the outcome `accepted` or `cycle_cap_best_available`. A review that ended
`review_incomplete` is terminal for the review controller but did not finish, so that unit is not
completed; the report shows its spend apart, with the reason.

The **all roles** line divides only over completed units whose usage is recorded and fully priced,
and names how many completed units it left out (no usage recorded, or some usage unpriced). Each
role-and-tier row does the same within the row: two models can share a tier while one is listed
without rates, so a row's per-unit figure divides only by the completed units whose spend in that
row is fully priced, and the report names any row that left units out. A unit whose spend is all
unpriced shows `unpriced`, never `$0.00`, and a total that leaves unpriced spend out is marked
`+ unpriced`.

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

Admission writes a next step only while it owns it: on a record with none, or over its own
`answer the N outstanding admission question(s), then plan`, which it recomputes on every pass so
answers given in two passes end at `plan`. A next step any later step set is never overwritten.

## Writing: atomic replace, under the record's lock

A write goes to a uniquely named temporary file in the same directory and is then moved into place
with `os.replace`, the same pattern `saga.py` uses for its envelopes. A reader therefore always sees
a whole record. The temporary name is unique per write, so two writers saving at once can never
move each other's half-written file. The write never widens the record's mode: an existing record
keeps its own, and a new one gets what the user's umask allows.

**Every read-modify-write takes the record's lock.** Issue 1018 shipped this record with no lock,
because one coordinator owned one record. Issue 95 ended that: unit sessions add their own `usage`
entries while the coordinator writes, and a writer that saves a copy it read earlier silently drops
every change made since. The convention, shared by saga and orchestrate:

1. Open the sibling file `<record path>.lock` (`issue-<N>.json.lock`), creating it if missing. It
   is never deleted: deleting it would let a second writer lock a fresh file while the first still
   holds the old one.
2. Take an exclusive advisory lock on it with `fcntl.flock(fd, LOCK_EX)`.
3. Re-read the record from disk while holding the lock. Never apply a change to a copy read before
   the lock was taken.
4. Apply the change and write through the atomic replace above.
5. Release the lock.

`run_record.update(store_root, issue, change)` does all five, and refuses a change that returns a
different issue's record, so the file written is always the file locked. `run_record.file_lock(path)`
is the same lock for a caller that names the record by path. The lock is advisory: it protects only
writers that take it, and `run_record.save` on its own writes whatever copy it is handed. A reader
that never writes needs no lock.

A writer whose work is slow does the work with no lock held, then takes the lock, re-reads the
record and lands only the keys it owns on that fresh copy. Holding the lock across minutes of checks
or git merges would stall every unit session's `usage add`.

| Writer | What it changes | How it follows the convention |
|---|---|---|
| `run_record.set_next_step`, `usage add` | `next_step`; one unit row's `usage` | `update` |
| `build_loop.py` | one unit row's `build_loop` | checks run unlocked; the iteration lands on a row re-read under `file_lock` |
| `review_result.py --issue` | `review_cycles` | `update` |
| `admission.py` | `repo`, `admission`, `run_configuration`, `approval_scope` | admission runs unlocked; those fields land on a fresh read through `update` |
| `qa_strategies.py` | the top-level `qa` block | `update` |
| `merge_turn.py status`, `take` | unit rows' merge keys | wholly under `update` |
| `merge_turn.py merge` | unit rows' `merge_state`, `merge_worktree`, `merged_tip` | git work runs unlocked; through `update`, each merge key it changed lands on a fresh read only if that row still holds the value the turn started from (the merged unit's own keys always land), and the keys it kept from another writer are listed as `kept_from_another_writer` |
| agent-launcher `roster.py` | `roster` | `update` |
| orchestrate `Run.save` | the keys its `Unit` declares on its unit rows; the top-level `orchestrate` block | under `record_lock` (issue 113): re-reads the record, writes its own keys from memory and carries every other row and top-level key forward from the fresh read |

The lock is not re-entrant: `flock` locks belong to an open file description, so a writer that
already holds it and opens the lock file again waits on itself forever. `run_record.save` therefore
never takes the lock itself; the caller of a read-modify-write does, once.

Two tests in `tests/test_run_record.py` hold these rules in place (issue 117). One parses every
saga script and fails on a `run_record.save` or `run_record.write_json_atomic` call outside
`run_record.py`, or on a `build_loop.save_record_file` call outside `file_lock`. The other fails if
`run_record.save` waits on a lock its caller already holds. A new writer therefore goes through
`update`, or takes `file_lock` for a record it names by path.

This is a lock on the file, not on any unit: it has no owner token, no expiry and no record of who
holds it, and it is held only for the length of one write. It is not the lease, reservation,
receipt or ledger mechanism the parent issue 1018 forbids, and nothing about a unit's execution
waits on it.

**`merge_state` has two writers, and the lock does not order them.** Orchestrate owns `merge_state`
and writes it from memory on every save; saga's `merge_turn.py` also sets it when a unit worker
takes or finishes the merge turn. The lock makes the two writes happen one after the other, but it
does not stop an older value from winning: orchestrate's `wait` loads the record, blocks for up to
its timeout, then saves the `merge_state` it loaded, which can put back a value `merge_turn.py`
replaced in the meantime. `merge_turn.py merge` guards its own writes by comparing against the
value its turn started from; orchestrate's save does not, so the key stays last-writer-wins on
orchestrate's side. This predates issue 113 and is not fixed by it.

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

# add one model session's counts to a unit's usage block, under the lock
python3 plugins/saga/scripts/run_record.py usage add <issue> --unit <id> --session-id <id> \
    --role worker --vendor claude --model claude-opus-5-5 --effort medium \
    --cache-read 98000 --output 4000

# cost per completed unit by role and tier, from every record in the store
python3 plugins/saga/scripts/cost_report.py [--issue <issue>] [--today YYYY-MM-DD] [--json]

# a read-only view of this checkout's runs: phase, next step and plan path
python3 plugins/saga/scripts/run_status.py [--repo-root <dir>] summary [--issue <issue>] [--all-active] [--json]
```

`run_status.py summary` is the display view the Claude Code mods and other harnesses read. It joins
this record (`next_step`, `updated_at`) with the per-worktree saga envelope (the lifecycle phase and
the plan path, which this record does not carry) and writes nothing. `--json` prints
`run_status.v1`; its exit codes match `show` above.

`--store-root <dir>` overrides the resolution above. It exists for the tests and for reading a
record that belongs to another checkout; every test that touches a store passes it, because nothing
in the test suite may write into the primary checkout's live store.

## Related

- `plugins/saga/references/repository-profile.md` — the per-repository defaults admission reads.
- `plugins/saga/scripts/admission.py` — the step that fills this record's front section.
