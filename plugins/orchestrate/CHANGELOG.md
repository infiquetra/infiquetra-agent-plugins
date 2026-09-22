# Changelog

## [6.0.1] - 2026-09-22

6.0.1 — imported from infiquetra-claude-plugins@acc99fe7 (upstream 6.0.0); authored here from this commit; no provenance manifest from now on.

### Changed

- The agent-launcher companion defaults to the sibling package `plugins/agent-launcher`. `AGENT_LAUNCHER_ROOT` overrides that package root. The search of a Claude plugin cache is gone.
- The companion version floor is read from the manifest that states `dependencies`. After this import that is the Claude adapter manifest, `com.infiquetra.claude/plugin.json`. The root `.claude-plugin/plugin.json` carries paths and the version only.
- A companion's own version is read from its portable `plugin.json`, then its adapter manifest, then `.claude-plugin/plugin.json`.
- `skills/orchestrate/scripts/orchestrate.py` mentions `fleet_commons_shim` only in a comment explaining why the saga-install resolver does not call it. The import reported that comment as an unresolved import. The file loads no Fleet Core module, and this package ships no `fleet-bundle.json`.
- The portable skill and the Claude command resolve the driver from the package root (`CLAUDE_PLUGIN_ROOT` when Claude sets it). They no longer fall back to `~/.claude/plugins/cache`.
- The skill no longer teaches the board-writeback procedure. Release 6.0.0 removed it, including `announce` and `merge` exit status 2.

### Tests

- Upstream `tests/test_orchestrate*.py`, `tests/orchestrate_support.py`, and `tests/test_review_loop_end_to_end.py` now live under `plugins/orchestrate/tests/`. The triage table omitted `test_orchestrate_review_loop.py` and `test_orchestrate_review_transport.py`; the package note `tests/test_orchestrate*.py` includes them, so they are carried.
- The suite pins `ORCHESTRATE_RUN_RECORD` at a frozen copy of saga's `run_record.py` from acc99fe7 while `plugins/saga` is absent. Production still prefers the sibling `plugins/saga/scripts/run_record.py` when the variable is unset.
- The suite pins `AGENT_LAUNCHER_ROOT` at a frozen agent-launcher 1.7.0 from the same commit, plus its `composer.py`. This catalog's `plugins/agent-launcher` is 1.0.0 and does not define the names Orchestrate execs, so an unset variable degrades instead of ingesting it. Production resolution is unchanged: sibling, then the variable.
- `tests/test_review_loop_end_to_end.py` skips until `plugins/saga/scripts/review_consensus.py` exists. It drives saga's review engine and Orchestrate together.
- `test_stage_skills_do_not_invoke_retired_transport_as_launch_path` skips until saga's stage skills are in this catalog. Its premise is those files in the upstream repository layout, and it does not call the driver.
- `test_fleet_commons_internal_team_execution_routing_unaffected` skips when `fleet_commons.tier_resolver` cannot be imported. This branch's fleet-core slice does not ship that module, and the test does not exercise Orchestrate.
- Dropped tests: none.

## [6.0.0] - 2026-09-20

**Bumped from 5.0.0**, the orchestrate version on `origin/parent/1018` at commit `25619cd1`.

**A major, not a minor.** This card first took 5.1.0 and that was wrong by the plugin's own
precedent: 5.0.0 was a major bump *because* it removed the `redrive`, `collect` and `land`
subcommands, under a heading that reads "Changed -- BREAKING". Removing `announce` from the command
surface is the same class of change, and retiring `merge`'s exit status 2 changes the answer a
caller already reads.

### Removed -- BREAKING

- The board-writeback path (issue #1028): about 850 lines covering the schema-vocabulary resolver,
  the rung mapping, the reconcile-controller shell-out, the announcement bodies, the writeback
  failure reporting, and the `announce` subcommand. Saga submits each of the run's lifecycle
  boundaries itself now, through mission-control's constrained lifecycle-field mutation, so this
  driver has no board write to make. `tests/test_orchestrate_board_writeback.py` (1,278 lines) and
  `tests/test_orchestrate_status_map_contract.py` are deleted with the behaviour they pinned.
- `merge`'s exit status **2** ("merges landed but a board card was not updated"). No state produces
  it any more; giving a retired code a new meaning would silently change what an existing caller
  reads, so it is retired rather than reused.

### Kept

- The plugin-resolution helpers that lived inside the removed block — the version regex, the
  version ranking, the install-root patterns and the candidate lister — because the run-record
  lookup still uses them.
- `fetch_default_branch` and `main_regression_files`, deliberately, rather than importing
  fleet-core's shared `merge_guard`. This file documents at its resolver why it must not take a
  resolution dependency on another plugin for something it needs when that plugin is absent, and a
  safety guard is exactly that. `tests/test_merge_guard.py` drives both implementations through one
  case table so the two cannot drift apart.
- The `status_map` run-file field, loaded and saved unchanged so a run file written before this
  release still round-trips.

## [5.0.0] - 2026-09-19

Orchestrate slims to the run driver: it keeps the worktree, launch, wait, merge and clean half,
and loses the protective layer built around it (issue #1025).

### Removed

- **`redrive`.** Recovery is a relaunch from the unit's branch, into a fresh worktree. The
  `prompt_undelivered` state and its one-door-out state machine go with it. A launch that stops on
  staged input keeps its recorded tab and is reported; clear the composer and use
  `launcher.py redeliver` by hand, never a second launch.
- **`collect`.** It merged a run branch into whatever the operator had checked out, with no
  currency check, so on a per-unit-pull-request run it could silently revert work on `main`
  (issue #875). The concern survives as a rule of the merge turn instead -- see below.
- **`land`.** Replaced by `merge`, which takes one merge turn at a time onto the run's parent
  branch. What went with the name is the bookkeeping around the merge, not the merge: the retained
  conflict pointer that outlived an invocation, the numbered landing-path fallback and its
  preserved-path reporting, and the retained-merge recovery that inspected an earlier run's
  worktree and decided whether to publish it.
- **The fixed-path run file** `.orchestrate/run.json`, its contract key, its `info/exclude` rule,
  and the task-spill mechanism that existed because that file was rewritten whole on every save.
- **The receipt and writeback records**: `record_writeback_outcome`, the persisted
  `writeback_failed` map, the outstanding-writeback report, and the persisted launch receipt. A
  failed board write is reported with its reason and its exit code, and re-running `announce` is
  the retry.

### Changed -- BREAKING

- **State moves to saga's per-issue run record** (`run_record.v1`, under the primary checkout's
  `.claude/saga/runs/issue-<N>.json`). Every stateful subcommand now takes `--issue <N>`. One
  record per issue means two issues can be driven in one repository at once, and the store root is
  resolved from the git *common* directory, so a unit's own worktree reads the same file the
  coordinator writes. **`start` requires the record and never creates one** -- saga's admission
  step writes it -- and refuses with exit 2 naming the admission command when there is none.
- **The companion version floor warns instead of refusing.** A below-floor agent-launcher still
  defines every name orchestrate calls, so the call is made and the operator is told the install is
  behind; a missing or unusable companion still refuses.
- **Upgrade obligation.** An `.orchestrate/run.json` from 4.x is not read by this release. Finish
  or abandon an in-flight 4.x run before upgrading; there is no migration.

### Added

- **A fresh worktree on every launch**, on the unit's own branch, never a reused path (card #886).
  A stale worktree is released first -- refusing on uncommitted or unpushed work and naming what is
  at risk -- so "fresh" never means "discarded".
- **A virtual-environment step in the worktree helper**: `ORCHESTRATE_WORKTREE_SETUP` when set,
  otherwise `uv sync --locked --extra dev` when the repository has a `uv.lock`, otherwise nothing.
  A failing step is named on the unit and the unit is not launched.
- **The launch is persisted before the launcher is called** (cards #900, #990), and the wrapper
  identity is written the moment the session exists, so a repeated `go` launches the unit once and
  an interrupt in the launch window never orphans a real tab. No lock, lease, reservation or
  receipt: issue #1018 forbids one and none is needed.
- **`plan-check`**, a non-mutating plan validator running exactly the assertions `start` runs, with
  an exit status usable as a gate step (card #879).
- **The width number bounds launches across calls** (card #901). The cap is the record's
  `concurrency_allocation`, and it counts open roster rows as well as running units, because a role
  session is an agent session and the number exists for the account's rate limit. `--limit` stays a
  per-call slice and its help says so.
- **A parent branch for a parent issue**, with children merging onto it by merge turn. `start`
  reads the issue's sub-issue count once and names the branch `parent/<N>` or `issue/<N>`.
- **The guard against reverting a newer `main`** (card #875), as a rule of the merge turn: the turn
  fetches the comparison ref first and refuses when that fetch fails, then refuses by name any
  merge that would take a file backwards relative to `origin/main`.
- **Worktree release at the merge turn** (issue #876), so a merged unit's branch becomes deletable
  where GitHub needs it to be.
- **Workspace retirement in `clean`** (issue #876), with ownership read from the record rather than
  from a name pattern, plus the one useful check from the retired fleet-doctor command: a managed
  worktree with no live session, reported by path.
- **Cleanup that runs for every unit** and names every leftover with git's own message, from a
  reporting block that is exception-proof (issues #960, #979). `clean` exits 3 when something was
  left behind.
- **One repair owner per shared blocker**, as a record field. Orchestrate only reads it: a unit
  whose row names a blocker another unit owns is reported rather than taking a turn for it.

### Fixed

- **The protected-reference denylist strips and casefolds before peeling `refs/heads/`**
  (issue #874), so ` refs/heads/main`, `refs/HEADS/main`, `Refs/Heads/main` and a tab-prefixed
  spelling all classify as protected. The same normalisation applies to the run-branch,
  resolved-branch and base comparisons; the membership set is unchanged.
- **The launcher's close-failure record survives a launch failure** (issue #944): the handler
  appends to the unit's note rather than replacing it.
- **A multi-unit wait records every settlement it observes** into the record's unit rows, under the
  existing caller timeout, and reports a blocked session rather than answering it (issue #891).
- **The cleanup-failure tests inject the failure at the command runner** (issue #991), so the same
  code path runs on every machine and nothing undeletable is left on disk.

### Carried forward from 4.6.0

Issue 1001's move to `review_result.v2` landed on the integration branch first and is carried
here unchanged; its own section follows below.

## [4.6.0] - 2026-09-19

### Consume `review_result.v2` (issue #1001)

`REVIEW_RESULT_SCHEMA` moves from `review_result.v1` to `review_result.v2`, following Saga's code
review as it became a policy-free executor of the lifecycle repository's lens catalogue. The pair
of schema identifiers is the only persistent compatibility contract across that boundary, so this
is a named constant rather than an inline string: a consumer handed an identifier it does not
recognise refuses rather than guessing.

No routing behaviour changes. The four typed outcomes and the fix-request routing are unchanged.

## [4.5.0] - 2026-09-16

### Fixed

- **Review-slot migration on late lifecycle assignment (#898).** Assigning a `lifecycle` after an unscoped review copies `review_result`, `review_outcome`, `review_resubmit_pending`, and `operator_fix_requests` into the named slot. A conflicting named slot is a stop, not an overwrite.
- **Replacement identity (#902).** A scoped mint names the controller's lifecycle and uses `{lifecycle}-repair` as the workspace. Template `-fix-` stems are not compounded. Lineage stays in the unit note.
- **Terminal-unit routing (#892).** `failed`, `orphaned`, `account_mismatch`, and `parked` workers are not reused and are not flipped back to `running`. A request whose only match is terminal mints a replacement.
- **Terminal and cycle-regressed ingest (#893).** `review-result` refuses a non-identical ingest into `accepted` or `cycle_cap_best_available`, and refuses a shorter `cycle_history` than the slot already stored. Byte-identical replay is unchanged.
- **Faithful status (#895).** A stored result with unset outcome prints `recorded-but-unrouted`. A note that contradicts the typed outcome is named and does not displace it.
- **Lifecycle-scoped resubmit (#884, #956).** `land` resubmits only controllers whose own lifecycle landed repairs in this invocation, never a controller already `running`. A non-staged write failure on one controller does not abort later controllers.
- **Land exit 4 (#959, #974).** An owed unmade resubmission, including operator-hold, exits 4 and outranks leftover-landing-path exit 3.
- **Dispatch-once retry (#976).** `dispatched_fix_ids` on the controller slot skips a worker that already took its repair when `review-result` is retried after a partial dispatch.

## [4.4.0] - 2026-09-16

### Changed

- **Companion ingest classifies missing, below-floor, ingested-but-unusable, and usable once (#1003).** A floor-satisfying tree that dropped a bound name, or a name-only stub whose `guard_pane_before_write` does not call `pane_input_inspection`, is not exec'd as a live companion. `status` degrades when a read-path name is missing instead of dying in `SystemExit`. `check` records `LIVENESS UNCHECKED` and exits 1 when herdr was not asked, instead of printing `the record agrees with the repository`.
- **`REQUIRED_LAUNCHER_NAMES` includes `ComposerState` and is cross-checked against SKILL.md (#1003).** The `land` and `review-result` gate comments name `PaneWriter`. The bolded install sentence names the agent-launcher floor.

## [4.3.0] - 2026-09-02

### Added

- **`redrive --unit <name>` (#907).** The one door back for a unit recorded
  `prompt_undelivered`: once its session is idle, the unit is re-prompted through the
  launcher's inspected writer; a session that has visibly started is refused with its tab
  named. Gated on the companion floor like the other write commands, which are now seven.

### Changed

- **The agent-launcher floor is `>=1.4.0` (#907).** That release carries `PaneWriter`, the
  single pane-write door this version's senders construct, and the retry door `redrive` uses.
- **Review dispatch and land resubmission write through the launcher's `PaneWriter` (#907).**
  Orchestrate owns no pane-write door of its own.
- **`land` exits 4 when a review resubmission is withheld on staged input (#907).** The stop
  reaches the failure handler again; with several controllers, each still gets its turn and
  the withheld ones are raised together. The command document carries `land`'s full exit-code
  table, pinned against the command's return statements.
- **After ingest, Orchestrate verifies every launcher name it binds (#907).** A launcher whose
  manifest satisfies the floor but whose source lacks a required name refuses the write side
  by name with the update remedy instead of a NameError at the first pane write.
- **`permission_declared` defaults to false (#907).** A legacy unit row without the key reads
  as not declared; only the plan parser sets it true.
- **`land --clean` no longer says it merged nothing when every merged unit was kept, and a
  keep reason names the tab the same pass already closed (#907).**
- **The skill scopes the run-file downgrade refusal (#907):** 4.0.0 through 4.1.x refuse by
  name; older than 4.0.0 opens the file blind.

## [4.2.0] - 2026-09-02

### Changed

- **Run files carry contract `2026-09-02.permission-declared` (#907).** `Unit` gained
  `permission_declared` in 4.1.0 under an unchanged contract string, so an installed 4.0.1
  accepted the file and died in a bare `TypeError` instead of the named refusal. An Orchestrate
  older than 4.2.0 now refuses a run file this version writes, by name, with the update remedy;
  this version still opens every older run file. The contract string is bound to the `Unit`
  field set by a test, so the next added field cannot ship without a bump.
- **The agent-launcher floor is `>=1.3.0` (#907).** That release carries the guarded
  redelivery door and the shared `should_guard_pane_write` predicate this version calls.
- **Review dispatch and land resubmission inspect owned panes too (#907).** Every unit those
  senders reach was prompted by its launch hours or days earlier, so ownership exempts nothing
  there; the predicate is the launcher's, called with the write half true.
- **A staged-input stop on one Code Review controller no longer aborts the multi-controller
  resubmit loop (#907).** It is recorded on that controller, printed with its name, and left
  pending for the next `land`; the other controllers are still resubmitted.
- **`roster` and `saga` run against a companion below the floor (#907).** They write nothing.
  Only the six commands that write a pane, create a session or worktree, or close a tab --
  `start`, `expand`, `go`, `review-result`, `land`, `clean` -- gate on the floor; the two
  informational commands refuse only when no companion was ingested at all.
- **`clean --merged` prints the true keep reason for two more shapes (#907).** A done unit
  with no branch of its own reads "done, with no branch of its own to measure", not "not
  done"; a branch git cannot compare reads as a git failure, not "not on the run branch".
- **`reap` checks `git worktree remove` (#907).** A removal that fails and leaves the directory
  behind keeps the unit with the reason, so `clean --all` no longer deletes the only record
  naming that worktree.

### Fixed

- **`SKILL.md` names both permission fields and the run-file reader floor; the README and the
  command document name the floor-gated commands by bucket (#907).**

## [4.1.0] - 2026-09-02

### Changed

- **The agent-launcher floor is a command-by-state matrix, not an import-time side
  effect (#907).** Eight commands — `roster`, `saga`, `start`, `expand`, `go`,
  `review-result`, `land`, and `clean` — refuse a companion below the declared
  `>=1.2.2` floor, or a missing or unusable companion, before any pane write,
  session or worktree creation, or tab close. `--help` survives either fault.
  `status` and `check` degrade to liveness-unknown when the companion is missing
  or unusable. `wait`, `settle`, and `adopt` refuse without Herdr reads.
- **A staged-input stop retries the same pane (#907).** The unit stays `PENDING`
  with its tab, pane, and receipt; a later `go` re-prompts that pane and creates
  no session. `already has tab` does not apply to a staged unit.
- **Run files tolerate unknown unit keys with a named notice (#907).** An older
  Orchestrate still cannot read a file this version writes; the compatibility
  floor for a reader of this run-file shape is 4.1.0.

## [4.0.2] - 2026-08-31

### Fixed

- **Companion-plugin faults are deferred to commands that require Agent Launcher (#907).** The
  manifest is the single source of the `agent-launcher >=1.2.1` floor; cache discovery is numeric,
  and stale, partial, or internally inconsistent installs no longer kill read-only Orchestrate
  commands at import. Mutating launch commands receive one named failure with remediation.
- **Stopped launches and cleanup failures retain durable recovery evidence (#907).** A staged-input
  stop preserves the created session identifiers and receipt, while failed tab closes are saved
  once to the run record and printed with the actual keep reason.

## [4.0.1] - 2026-08-31

### Fixed

- **A reconcile-controller timeout now actually reports itself as unretryable.** 4.0.0 added a
  safety record for this case and it could never execute. The branch was written as
  `except subprocess.TimeoutExpired` around the controller call, but the runner catches the timeout
  itself and, under `check=False`, returns `CompletedProcess(returncode=124)` rather than raising —
  so nothing crossed that frame and a real timeout fell through to a bare `failed` record with no
  `retryable` key, which every reader defaults to retryable. That is the one failure where a retry
  is worst: `subprocess` kills the direct child only, so the Mission Control process saga launched
  survives and may still be writing the card. The case is now detected on the return code, and a
  test drives a real timeout rather than asserting about one.

### Documentation

- **Stop claiming all three dependency floors are enforced.** `plugin.json` declares floors for
  saga, mission-control and agent-launcher; only saga's is checked at runtime. `README.md`,
  `commands/orchestrate.md` and the 4.0.0 note above each said or implied otherwise. They now name
  saga's as the enforced one and say plainly that the other two are read by the installer and
  checked by nothing.

## [4.0.0] - 2026-08-31

### Why this is a MAJOR bump

`{#removed-default-is-breaking}` in this repository's `DECISIONS.md` sets the test as whether a
caller can observe the change; where none can, a minor bump is defensible. Callers **can** observe
several of these, so the precedent points the other way and this release follows it. Four
independently qualify: an existing run file whose `status_map` holds a pre-pair single string made
`land` exit 0 before and exits 2 now; the progress comment's rendered body gained a `board stage:`
line; `STATUS_LADDER` was deleted outright; and `mapped_status` was retyped from `str | None` to
`tuple[str, str] | None` and now raises where it used to return. Two hard install obligations are
added on top. Downgrading is now refused rather than silently misread — see the run-file contract
below.

### Upgrade order — read this before relying on board writeback

**Install saga 0.151.0 or later, and mission-control 2.15.1 or later, BEFORE this version.**
Orchestrate does not execute board writes; it shells out to whichever saga
`reconcile_controller.py` resolves on the machine, which is not necessarily the saga in your
checkout. A saga older than the `(Stage, Status)` pair contract accepts the call, ignores the
`Stage` assignment, writes the `Status` half alone and reports success. Orchestrate now catches that
by reading the record's own field identity and fails the writeback rather than posting a progress
comment that claims both halves moved — but catching it leaves the card half-moved. Both
requirements are now declared in `plugin.json`.

The resolver also picks the **newest installed version**, not the first one a glob returns. Sorting
the glob's raw strings is lexicographic, which put `0.136.0` ahead of every later release; on a
machine with sixty installed saga copies across two plugin roots it selected a saga from well before
any of this existed. `~/.claude-company` is searched too — it is a second plugin tree beside
`~/.claude`, not a symlink to it, and it had been omitted.

The ranking is **global across every install root**, and the version is read from the directory
directly beneath the plugin's own name. Ranking within each root and then concatenating meant root
order decided the winner before version did, so a stale copy in the first root beat a newer one in
the second; and taking the highest dotted-numeric segment anywhere in the path let a marketplace
directory such as `cache/infiquetra-9.9.9/` outrank every real release. Saga's declared floor is
now **enforced**, not merely declared: a resolved saga below the `plugin.json` floor is refused
before any submission is made, naming the install path and the version it found. The
mission-control and agent-launcher floors declared beside it are read by the installer and
nothing checks them at runtime.

### Fixed

- **`codereview` no longer maps to `Verify` (#927).** Closed `infiquetra/infiquetra-sdlc` #89 (W8),
  requirement R69, puts pre-merge continuous integration, tests, code review and merge readiness all
  in the `Active` stage; `Verify` begins only after merge plus the applicable non-production
  deployment, or after installed or published artifact verification when nothing deploys. The Saga
  half of that repair shipped and this half did not, because the guard test enforcing it scanned
  `plugins/saga/` only. The key is remapped to `Active`/`Code review`, not deleted: deleting it
  would silently stop announcing at a boundary that announces today.
- **Every board write this plugin made was halting, and now lands.** `STATUS_LADDER` was a
  hard-coded second copy of the board's Status vocabulary and had gone stale — not one of its six
  values is a live `Status` option, so `_set_lifecycle_field_cross_board` halted before the first
  write, every time. The ladder is replaced by the `workflows.stage_flow` block resolved from the
  Mission Control schema document.
- **Three silent no-ops are now loud.** An off-ladder rung used to be dropped with a `skipped`
  record — precisely how six stale rungs stayed invisible. An unresolvable Mission Control schema
  did the same, and worse: `report_announcements` prints a skip only under `verbose`, both `land`
  call sites pass the default, and `_failed_writebacks` excludes skips by design, so `land` wrote
  nothing, printed nothing and exited 0. And a writeback failure's reason was built and never
  printed, so a failure read as the single word `failed`. All three now produce a failure record
  with its reason on the operator's line, and the schema case also prints to stderr the way the
  sibling missing-saga branch always did.
- **`announce` exits 2 on a hard writeback failure**, as `land` already did. It is the retry door,
  so a green exit from it was a direct claim that the card is now right — read by an operator who
  ran it precisely because the card was wrong.
- **No rung reaches `Verify` or `Retro`, from any source.** The default map is pinned against both
  stages by test, and a run file's `status_map` override never passed through that pin — an
  override is validated for liveness alone, and `("Verify", "Awaiting verification")` is a
  perfectly live pair, so the rule had one door closed and a second open. The restriction now sits
  on the submission itself, which every rung reaches by every door.
- **A malformed `issues` reference is a failure, not a skip.** A reference that is not
  `owner/repo#N` recorded a skip, which prints only under `verbose` and is excluded from the
  failure report by design — so a typo meant the card was never written, nothing said so, and
  `land` exited 0. "This unit has no issue" is a designed no-op; "this unit has an issue and the
  reference to it is broken" is a configuration defect, and the two are no longer conflated.
- **A failed writeback outlives the invocation that saw it.** `land` announces only the units it
  merged in that invocation, so a second `land` merged nothing, attempted no write, found no
  failure and exited 0 while the card was still wrong. Outstanding units are recorded in the run
  file, reported by every later `land`, and cleared when an `announce` converges them.
- **The controller's timeout is derived from saga's own budget rather than guessed.** saga takes up
  to `60s x assignments x 3 attempts` — 360 seconds for a pair — and the outer cap was a flat 180,
  so a slow board truncated the controller mid-retry. `subprocess` kills only the direct child, so
  that left the Mission Control process saga had launched still writing the card while the operator
  was told the write failed and to retry. The timeout is now computed from the same constants, and
  a genuine timeout says explicitly that a write may still be in flight.
- **Every writeback names its provenance.** Which saga executed the submission and which Mission
  Control schema validated the rung are printed on stderr and carried on every record. Several
  copies of each are typically installed; without this, a write executed against a stale one was
  indistinguishable from a correct one.
- **A run file names the contract it was written under.** `status_map` becoming a `(Stage, Status)`
  pair is exactly the kind of change an older Orchestrate misreads rather than ignores — it sees an
  unmapped prefix and announces nothing, silently. A run file carrying a contract this version does
  not know is now refused rather than read. This protects run files written from here on; an
  Orchestrate older than 4.0.0 does not read the key, which is why the upgrade order above is an
  obligation rather than a note.
- **The retry door is named only when a retry can clear the failure.** `announce` is
  idempotency-keyed and safe to repeat, but repeating it cannot fix a stale install, an unresolvable
  schema, or a run file whose override is not a pair. Those now report their cause instead.
- **The `landed` rung is RETIRED, and no rung reaches the `Verify` stage by any door.** `Verify` is
  entered only after merge plus the applicable non-production deployment — or, when nothing deploys,
  after installed or published artifact verification. Orchestrate can check **neither** conjunct:
  `land` merges unit branches onto the run branch `orch/<run-id>` rather than the default branch, so
  a `landed` boundary is not a merge in that rule's sense at all; and every occurrence of
  `deployment` / `deployed` / `non-production` / `nonprod` in the module is prose inside one
  comment, with no code reading, computing or receiving any of them, so there is no signal to gate
  on. A gate would therefore be permanently false — a dead key with extra code around it rather than a
  safeguard — so the key is removed instead. Remapping it to `Active`/`Integrating` would be better
  behaviour and was considered: it is not made here because issue #919's approved board transition
  contract carries no `Integrating` row, and adding one extends a contract the operator approved,
  whereas retiring only removes a violation. **Nothing that ever worked is lost:** before this
  change `landed` mapped to `Done`, which is not a live `Status` option, so every write it made
  halted before reaching a card, and no unit in the repository is named `landed-*`. A `landed` unit
  now produces a **failure record naming the retirement**, not a skip: retiring the key without
  that would have converted its loud "not a live rung" failure into `mapped_status` returning
  `None`, which is a designed no-op that `land` exits 0 on — turning a visible error into silence,
  which is the opposite of the point. An operator who maps `landed` explicitly in the run file gets
  the ordinary rules instead. **Reversible: the operator may restore it as a remap at any time
  before merge.**

### Changed

- **`DEFAULT_STATUS_MAP` and `Run.status_map` carry a `(Stage, Status)` pair.** `mapped_status`
  returns that pair, the announce discriminator renders it as `Stage/Status`, and the progress
  comment names both halves. The six rungs are `plan` → `Planning`/`Designing`, `docreview` →
  `Planning`/`Ready for Active`, `work` and `fix` → `Active`/`Implementing`, `codereview` →
  `Active`/`Code review`. All five are live and stage-monotonic. There is no sixth: `landed` is
  retired, as described above.
- **A `status_map` override is a pair and is validated against the resolved vocabulary.** A run
  file carrying the older single-string override fails loud rather than half-submitting.
- **Two observable changes for an existing run file, stated rather than implied.** A run file whose
  `status_map` holds a pre-pair single string made `land` exit **0** before and exits **2** now; the
  fail-loud direction is deliberate, and nothing that previously *worked* stops working, because
  none of the retired ladder's values was a live option and every such write was already halting at
  Mission Control. And the progress comment now carries a `board stage:` line above its
  `board status:` line, so its rendered body differs from the pre-3.1.0 shape.
- **The announce path is unchanged in what it announces and in that it dedups** — one progress
  comment per boundary, and the same silent degradation when saga's reconcile controller is absent.
  **The discriminator's shape did change**, and an earlier draft of this entry said it had not: it
  renders the rung, so `orchestrate:{run}:{unit}:{status}` became
  `orchestrate:{run}:{unit}:{Stage}/{Status}`. A boundary announced under the old shape and
  re-announced under the new one therefore mints a different key and posts a second comment. Two
  other things changed and are listed above: the exit code on a hard failure, and the reporting of
  a failure's reason. The drift half of the
  submission path also changed, in saga rather than here (see saga 0.151.0).
- **Where the vocabulary comes from, precisely.** Orchestrate keeps no board vocabulary of its own,
  which is the property that matters: a value that stops being live stops validating here as soon as
  the plugin updates. It reads Mission Control's *shipped* schema document, which is that resolver's
  offline source rather than its only one — `_resolve_sdlc_schema` prefers the copy on GitHub `main`
  — so a live schema newer than the installed plugin is not visible, and a rung that is
  live-but-newer fails loud here rather than being submitted blind. Reading the document instead of
  importing `sdlc_manager` is deliberate: that resolver reaches GitHub through a `gh` child, and a
  land must never wait on the network.
## [3.2.0] - 2026-08-30

### Fixed

- **Unowned-pane stops are retryable and cleanup retains evidence on close failure (#907).** A
  staged-input stop returns its unit to pending after clearing stale session identity. Cleanup now
  keeps the worktree when an owned tab cannot be closed instead of force-removing the evidence.
- **The Agent Launcher dependency floor is enforced, not only declared (#907).** Orchestrate
  requires Agent Launcher 1.2.0 at runtime and chooses cached versions numerically, matching the
  skill's `sort -V` lookup.

## [3.1.0] - 2026-08-30

### Added

- **A declared permission is carried visibly, and an undeclared one says so (#896).** The unit
  model records whether the plan row that produced it named `permission` explicitly
  (`permission_declared`), and plan loading prints one line naming every unit that omitted the
  field and inherited the `auto` default — a run that declared a posture and a plan that never
  mentioned one are no longer indistinguishable on screen. The dependency floor rises to
  `agent-launcher >=1.1.0` in the same release because Orchestrate's permission behaviour now
  consumes the launcher's `resolve_permission`; installed beside launcher 1.0.0 it would silently
  get the old fallback to auto, which is the defect itself.

## [3.0.8] - 2026-08-27

### Added

- **Several independent Code Review controllers in one run, each scoped to its own child lifecycle
  (#877).** A run reviewing several ready frozen targets can now declare one controller per target
  by giving each a `lifecycle`. Each keeps its own typed state — `review_outcome`,
  `review_resubmit_pending`, `operator_fix_requests` — in `review_states`, which every consumer
  reads through `review_slot`, so one target's state can never be read as another's. `land`, `reap`,
  `status` and `resubmit` all read the slot; repair routing, worker matching and replacement are
  confined to the selected controller's lifecycle; and each pending controller resubmits
  independently, so one controller's operator hold cannot block another's recovery.
  Replacement Work units inherit their controller's lifecycle, fix parking and assignment are
  confined to it, and a lifecycle-less Work unit remains reachable as a documented fallback.
  A lifecycle-less Work unit is a mint template rather than a shared live holder -- for every scoped
  controller, not only when several exist -- so no two controllers park on one session, landing it
  cannot discharge another target's repairs, and a controller added later by `expand` cannot orphan
  an earlier one's already-parked bag.
  Lifecycles are normalised at load, the ceiling is validated on load as well as at start and
  expand, and `review_states` is the single live authority with the run-level fields mirrored only
  so an older Orchestrate can still read the record. `review-result` gains `--controller <name-or-lifecycle>`, required when
  several controllers exist; omitting it is refused rather than guessed, and a result aimed at a unit
  that is not a controller is refused outright. `review_controller_ceiling` caps how many controllers
  run at once, holding the surplus at the eligibility gate rather than refusing it at load.

### Fixed

- **The single-controller guard no longer misreads a path as an invocation (#877).**
  `is_code_review_task` matched any `/code-review` occurrence, so an ordinary Document Review or Work
  unit was classified as a Code Review controller merely for naming the directory where committed
  typed results live. The match is now anchored to a command position — start of text or after
  whitespace — so a path segment cannot read as an invocation, and an operator hitting the
  one-controller error can tell a real second controller from a false positive.

### Unchanged

- One review phase is still one controller. An **unscoped** second controller fails exactly as
  before, with the same message, as does a partially scoped set or two controllers claiming the same
  lifecycle. Relaunching one controller for successive cycles against one advancing target is
  untouched. Code Review's consensus protocol and lens selection are not modified, controllers share
  no verdict state, and no cross-controller coordination was added.

## [3.0.7] - 2026-08-27

### Fixed

- **`dependencies` is declared as an array so the plugin loads again (#871).** The manifest
  declared `dependencies` as a JSON object (`{"agent-launcher": ">=1.0.0"}`). The live Claude Code
  plugin loader requires an array and rejects the entire manifest rather than ignoring the field,
  so no part of Orchestrate loaded and `/orchestrate` was unavailable. The same
  `agent-launcher >=1.0.0` floor is now expressed as `[{"name": "agent-launcher", "version":
  ">=1.0.0"}]`, which the loader accepts under `--strict`. The object form dated to 2.0.0
  (commit `28a881b3`, pull request 827 for issue 777), so every release from 2.0.0 through 3.0.6
  failed to load; 1.20.8 and earlier omitted the key and were unaffected. Added
  `tests/test_plugin_manifest_loader_contract.py`, which fails against the 3.0.6 object form and
  validates every packaged manifest against the live loader contract. Also corrected
  `marketplace/validator/schema.json`, which declared `dependencies` as an object and so
  actively enforced the unloadable shape, and the two tests that asserted it.

## [3.0.6] - 2026-08-26

### Fixed

- **Opt-in remote branch cleanup for merged run-owned branches (#844).** `clean --branches`
  now extends branch cleanup with an opt-in remote pass. Remote branch cleanup considers only
  exact branch names recorded by the current run (`run.json`), deleting a remote branch only after
  merged-PR proof (via `gh pr list`) or committed ancestry proof that the head is contained in
  the authoritative branch (`r.branch`, `main`, or base). Every deletion is read back via
  `git ls-remote` to confirm removal. Open (`RUNNING`/`PENDING`), diverged, unknown, or
  operator-retained branches are refused with clear reasons and retained evidence. Repeated
  cleanup passes are idempotent and report already-absent branches cleanly without error. Local
  cleanup behavior and normal `clean --merged` remain unchanged.

## [3.0.5] - 2026-08-26

### Fixed

- **Typed parked state and idempotent resume for push-succeeded / PR-blocked units (#843).**
  Orchestrate now records a distinct typed `parked` state and `parked_state` dictionary on units
  when a worker's `git push` succeeded but pull request creation was blocked (e.g. by session
  permission mode or API rate limits). The parked state is recorded via `park --unit <name> --evidence <text>`
  only after the pushed commit is verified on the remote branch via `git ls-remote` (capturing
  verified remote head, authoritative base, unit identity, frozen revision, and failure evidence);
  failed pushes never enter this path. A coordinator-owned `resume --unit <name>` operation verifies
  that the remote head is unchanged, then idempotently opens the missing pull request or adopts an
  existing matching one and advances the unit to `done`, continuing the original run without a
  second run or rewritten evidence. Missing or changed remote heads fail loudly without mutating the
  run record.

## [3.0.4] - 2026-08-26

### Fixed

- **Task spill never clobbers hand-authored task briefs (#845).** `spill_unit()` now stamps
  generated `.orchestrate/tasks/<unit>.task.md` spill files with a stable Orchestrate ownership
  marker carrying run and unit identity (`<!-- orchestrate:owner json={"run_id": "...", "unit": "..."} -->`)
  and writes files atomically. When saving a spilled task, Orchestrate refuses to overwrite an existing
  unmarked file (such as a hand-authored brief) or a file owned by a different run or unit, failing
  loudly with `SystemExit`, identifying the conflicting path, and leaving original bytes untouched.
  Same-owner rewrites remain idempotent, multi-unit saves pre-validate before writing, and loading
  unmarked hand-authored briefs remains fully supported.

## [3.0.3] - 2026-08-26

### Fixed

- **Distinguish explicit Saga capabilities from bespoke review prompts (#837).**
  `is_standalone_review_prompt()` now recognizes leading explicit non-Code-Review Saga
  capabilities (such as `/saga:plan`, `$saga:doc-review`, `/doc-review`, `/founder-review`,
  `/work`, etc.) before evaluating bare-word review patterns. Incidental mentions of the word
  `review` within planning or document review tasks no longer cause false-positive
  rejections when a single typed `review-controller` is appended to the run. Genuine untyped
  review prompts (such as `review this PR for bugs`) remain strictly rejected before any session
  launches, preserving the single-controller and reviewer-seat contracts.

## [3.0.2] - 2026-08-26

### Fixed

- **Model authority boundary: live catalog, never stale tables (#848).** External worker and
  reviewer availability, exact model names, and effort or variant controls come only from the
  installed `agents` wrapper and vendor-native live catalogs or help — never from Fleet Commons tier
  data (`fleet_commons.tier_resolver`) or `~/.config/orchestrate/models.json`. Favourites provide
  ordering only and never act as an allowlist or reachability constraint. `opencode-go` is documented
  and handled as an OpenCode provider route, not an agent kind (`opencode`). Launch receipts separate
  requested-only model facts from Herdr-confirmed runtime facts, and launch / variant validation refuses
  unsupported vendors and unadvertised variants with no silent substitution.

## [3.0.1] - 2026-08-26

### Fixed

- **Fail fast on unresolvable Agent Launcher companion (#841).** When Orchestrate is installed
  without its required `agent-launcher` companion, `roster`, `start`, `expand`, and `go` fail
  preflight before creating any git worktree or Herdr session. The error message names the missing
  companion and provides the exact supported remediation
  (`claude plugin install agent-launcher@infiquetra-plugins`) without machine-specific paths.

## [3.0.0] - 2026-08-25

### Removed

- **BREAKING: `.saga/engine-prefs.json` seam retired (#776).** Plans no longer carry
  `engine_prefs`; `start` and `expand` refuse a plan that still does. Reviewer
  seats are named units (`role: review-controller` / `role: external-reviewer`)
  launched through `expand`/`go`. When a Saga Code Review phase is present,
  Orchestrate refuses plain review prompts, direct reviewer launches, and
  duplicate review units before any session is created. Halt, never fall back
  to the retired saga runner. Older run files that still contain `engine_prefs`
  load and drop the field.

## [2.0.0] - 2026-08-25

### Changed

- **Launch seam moved to the agent-launcher plugin (#777).** Breaking: Orchestrate now
  depends on `agent-launcher >=1.0.0` (`plugin.json` `dependencies`). Vendor flag tables,
  wrapper resolution, argv assembly, launch, Herdr preflight, prompt delivery, and owned
  cleanup live in `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`.
  Orchestrate ingests that module and keeps run-scheduling, landing, review policy, and
  the run ledger. A missing agent-launcher plugin no longer kills every subcommand at
  import; launch/roster/go fail with a clear error, and git-backed commands still run.

## [1.20.8] - 2026-08-25

### Added

- **Per-run worker-pool declarations and reintegration practice.** `SKILL.md` now documents the
  two run practices proven in orch-2026-08-24-787: a per-run worker-pool table (priority order,
  per-pool cap, launch template, exercised-or-not at closeout) and immediate reintegration of
  the run's declared authoritative integration branch after every serialized landing, with
  release-surface versions re-resolved before continuing. Reintegration is a merge, never a
  rebase: a surviving branch carries an open pull request, and rewriting its commits strands the
  revision-bound review records that name the reviewed SHA. Vendors, models, efforts, caps, and
  the integration target are per-run operator inputs, never hard-coded. Guidance only — no
  scheduler or driver change.

## [1.20.7] - 2026-08-24

### Changed

- **Waiting patterns and execution guard guidance.** Pre-teach supported waiting mechanisms across
  three common waiting shapes in `SKILL.md` (`## Waiting, and empty dependencies`) to prevent
  guard-blocked sleep polling attempts. Documents: (1) sibling Herdr agent output and unit settlement
  via `orchestrate.py wait`, `herdr agent wait`, and `herdr pane wait-output`; (2) pull request checks
  and external asynchronous state via `gh pr checks --watch` run detached under `Monitor` or
  `run_in_background`; and (3) session-started commands via `run_in_background` with log redirection
  and a completion notification, never a foreground `wait "$PID"`. Includes copy-pasteable examples
  for each shape and an explicit "never chained sleep in a foreground turn" rule.

## [1.20.6] - 2026-08-24

### Fixed

- **Company-account propagation and post-launch verification.** Orchestrate now propagates the
  operator's account selection through the central launch seam and verifies it after launch.
  Plan- and unit-level `account` fields (`company` or `personal`) are added to the run schema;
  selecting `company` emits `--company-account` after the vendor token for Claude units, ensuring
  the wrapper swaps configuration directories (`~/.claude-company`) before the agent starts.
  Before any task is submitted, preflight reads the account back off the session: its statusline
  first — the wrapper exports `CLAUDE_ACCOUNT_LABEL` into the pane and the statusline renders it as
  `operator [company]` — falling back to which transcript root (`~/.claude-company/projects` vs
  `~/.claude/projects`) holds the session on a machine that does not print it. A worker on the wrong
  account, an account value other than `company` or `personal`, and an account that cannot be read at
  all within `ACCOUNT_SETTLE_SECONDS` all close the run-owned session and mark the unit failed with
  the distinct named state `account_mismatch` (`ACCOUNT_MISMATCH`). The transcript alone is not
  enough at that moment: Claude writes `projects/<slug>/<id>.jsonl` when the first prompt arrives,
  which is after preflight runs. A unit that names no account is not checked and is unaffected.

## [1.20.5] - 2026-08-24

### Fixed

- **OpenCode variant recipe through interactive Herdr picker.** Orchestrate supplies and enforces
  the complete launch recipe for OpenCode units: creates a named visible Herdr session through the
  `agents` wrapper via the single launch seam, drives `/variants` inside the session post-launch,
  reads live picker choices, selects the requested exact variant or highest actually offered variant
  when maximum available is requested (resolving `xhigh` for Muse rather than guessing `max`), and
  waits until the session is task-ready. The selection is then read back out of the pane: a picker
  that closed on its previous value stops the unit instead of submitting work at a variant nobody
  asked for, and pane output that parses to nothing the variant ladder recognises is polled again
  rather than mistaken for the option list. Preflight checks the effective working directory,
  workspace and readiness against `herdr agent list`, closing only the run-owned tab and failing the
  unit before submission when either disagrees; the workspace name in the plan is resolved to a
  herdr workspace id first, because the two never compare directly. The `launch_receipt` records
  provider, model, variant, working directory, worktree, workspace, pane and observed readiness,
  and names in `confirmed_against_herdr` / `requested_only` which of those herdr could actually
  confirm — a model is always the latter, since `herdr agent list` publishes none. Prose in
  `commands/orchestrate.md`, `SKILL.md`, and `VENDOR_NOTES["opencode"]` updated to document the
  enforced per-agent recipe.

## [1.20.4] - 2026-08-24

### Fixed

- **Single launch seam and no-focus background invariant.** Every run unit, including units added at
  a later phase boundary via `expand`, is persisted before creation and launched strictly through
  `go` and the central `agent_argv()` path. Regression tests lock the complete background launch
  flag set (`--no-focus --current --herdr --herdr-control-only`) ahead of the vendor token across all
  supported vendors, and verify that operator focused pane is preserved across multi-unit launches.
  Coordinator instructions explicitly prohibit manual worktree creation or direct `agents` wrapper
  invocations, and treat unsupported post-launch setup as a controlled post-launch step rather than
  an expansion bypass. `status` now surfaces unrecorded unit branches discovered via
  `discover_unrecorded`, ensuring coordinator-created drift is visible and requires explicit adoption
  (`adopt --yes`) or run-owned cleanup.

## [1.20.3] - 2026-08-24

### Fixed

- **Settlement requires branch completion evidence instead of pane idleness.** `orchestrate.py settle`
  now gates completion on `produced_anything`. A session that is merely idle without commits on its
  branch stays running, preventing stale `done` states or stuck/suspended processes from falsely
  settling done. A closed Herdr session with commits on its branch settles `done` (never `failed`),
  while a session gone without commits transitions to the distinct `orphaned` state.
  The gate is a reading of a branch and is applied only where one can be read: a unit with no
  branch of its own (the review controller, `merge: false`) is not commit-gated, and an
  unresolvable run branch leaves the count unknown rather than zero — that unit stays running and
  is told why, and a gone session's note says the commits could not be checked rather than
  asserting there were none.

## [1.20.2] - 2026-08-24

### Fixed

- **Dispatch confirms prompt delivery before marking units running.** Orchestrate now checks
  acceptance via `took_the_task` after dispatching a unit's initial prompt. If the prompt is swallowed
  while Herdr reports `interactive_ready` (e.g. by vendor startup or trust dialogs), Orchestrate
  retries delivery up to 2 times while the session remains continuously idle. If still unaccepted, the
  unit transitions to the named failure state `prompt_undelivered` with `DELIVERY_WARNING`, rather than
  being left silently running.

## [1.20.1] - 2026-08-21

### Fixed

- **Grok units received their permission mode as their first prompt.** `VENDOR_PERMISSION` mapped
  Grok's two permission levels onto `--always-approve`, which is a value-less switch, and Grok's
  usage is `grok [OPTIONS] [PROMPT]` -- so the bare `auto` or `bypassPermissions` bound to the
  positional prompt. Every dispatched Grok session spent its first turn on a permission enum and
  received its real task only afterwards. Nothing errored and nothing reported it. Both levels now
  emit `--permission-mode`, which Grok documents as accepting exactly those values. Native launcher
  passthrough is unchanged: `launch_args` still go last and verbatim.

## [1.20.0] - 2026-08-20

### Added

- **Review phases now run through one Code Review controller and an opaque typed result.** Orchestrate
  persists the result without recomputing review policy, routes `review-fixer` and
  `downstream-resolver` requests to matching live Work workers by role and touched paths, creates a
  replacement worker when needed, and resubmits the landed revision through the same controller.
  Requests owned by `human` or `release` remain visible operator actions and are never dispatched as
  Work.

## [1.19.0] - 2026-08-20

Group A combines the first three run-integrity repairs with the documentation-and-hygiene unit.

### Fixed

- **U1 — `land` no longer touches or refuses the operator's working tree.** Unit branches merge in
  a detached throwaway worktree, the run branch advances explicitly, successful worktrees are
  removed, and conflicting worktrees are retained and named for recovery. After the operator
  resolves and commits a conflict there, a rerun publishes only an exact two-parent merge of the
  current run tip and current unit tip, using the same guarded reference advance as the ordinary
  path. Once that merge is published, its conflict pointer is cleared before cleanup; a cleanup
  failure no longer blocks later units, and a clean exact merge already in run-branch history is
  cleaned up on retry. Missing landing directories have stale Git registrations pruned before
  reuse even when `clean` already cleared the record pointer. Retained-worktree refusals now
  distinguish unresolved changes, a non-merge `HEAD`, a missing unit match, and a moved run-branch
  base without weakening the publication gate. `clean --all` preserves any recovery work it
  reports as kept, and its help names that retention. The checked-out-run-branch warning names the
  staged-deletion hazard and recovery command, and cleanup failure reports completed merges under
  its own exit status instead of calling the land a merge failure. A pre-existing canonical landing
  path is never reused for merges. If it is not a proven separate linked worktree, does not contain
  an exact published merge, or cannot be removed, `land` preserves and names it, then creates the
  lowest unused numbered detached worktree. The new path is exact by construction. The housekeeping
  proof reads the linked-worktree metadata without running `git -C` against an unverified path, and
  `check` and `clean` discover both canonical and numbered cleanup paths. Plain `clean` now applies
  that proof to a recorded conflict path too; an unproven path and its record pointer are reported
  as kept, so a planted symlink cannot remove another registered worktree or its uncommitted files.
  Across Group A's landing paths, partial removal performed by Git itself, a gitfile rewritten to
  the primary Git directory, plain or stale directories, and symlinks cannot become merge targets
  or cleanup targets.
- **U2 — a missing run branch fails loudly instead of producing false unit results.** The branch is
  resolved once when a run loads; `status`, `check`, and `clean` remain available for diagnosis,
  while `go` and `land` refuse with the missing branch named, even when no unit is eligible. `adopt`
  also remains available: it names the missing branch and conservatively marks a stranded unit
  without a live session as failed when commit-based classification is unavailable.
- **U3 — delivery warnings and unit status are honest and readable.** Warnings append to existing
  notes, clear after a commit, and appear in `status` and `check`; the status table now handles long
  model names and multiline tasks while showing commit counts and landed state. Pane handover notes
  and pane-fallback diagnostics both append, including when a long task has no setup lines. Task and
  note columns are both bounded, and one run-branch history walk classifies every unit's landed
  state instead of repeating that walk for each row; the unused single-unit wrapper is removed.
- **U11 — local state and documentation match the plugin that ships.** `start` idempotently excludes
  `.orchestrate/` through the driven repository's local Git exclude file, hand-authored briefs use
  `.orchestrate/tasks/`, and the README documents only `orchestrate.py` and `herdr_events.py`. The
  exclude path is resolved from the repository root even when `start` runs in a subdirectory, and
  an existing final rule without a newline is preserved correctly.
- **Run and adoption paths use Git's real path and ref shapes.** A run identifier must be one safe
  path component before the run branch or landing directory is created. `adopt` now matches Git's
  `refs/heads/` worktree output to a stored short branch name, so it recovers the live worktree and
  Herdr session instead of rebuilding an incomplete unit row.

## [1.18.0] - 2026-08-19

Sixteen fixes found by watching real runs rather than by anything erroring. The unifying shape:
work reported as done that was never attempted, and predicates that measured the wrong thing.

### Fixed

- **`clean --merged` reaped units that were still working.** `landed()` counted commits ahead of the
  run branch and answered yes at zero -- which is also exactly what a unit that has not committed
  *yet* looks like -- and `cmd_clean` never consulted `unit.status`. It closed the tabs and removed
  the worktrees of two builds and two reviews that were mid-flight. `landed()` now distinguishes
  three states, and nothing-to-land is no longer the same answer as landed; `--merged` requires
  `DONE` as well. `land --clean` reaps only the units that invocation merged, so work an earlier
  invocation deliberately kept stays kept.

- **`settle` treated a single idle sample as finished, and `wait` did the same.** An agent is also
  idle *between* turns. One sample marked a unit done while it was still working: it had two commits
  at the time and finished with ten. Both now require agreeing observations, `--interval` apart.
  `wait` has no single-sample escape hatch: `--once` is gone and a confirmation count below two is
  rejected, because a deliberate single-sample wait is the defect with a flag on it.

- **`wait`'s fallback path leaked processes and ignored its own timeout.** It discarded the child's
  exit status and restarted with a fresh full budget -- `wait --timeout 1` ran for 1.505 seconds and
  launched 31 child processes. It now enforces one monotonic deadline across restarts. The fallback
  also waits on `blocked`, which it never did: an agent stuck on a question was invisible until the
  helper timed out, thirty minutes at the default.

- **Launcher flags were emitted where the vendor sees them.** `launch_args` was appended after the
  vendor token, so `--workspace` reached the agent as a native argument and a live session landed in
  the caller's workspace. The two positions turn out to be mutually exclusive -- `--workspace` works
  only before the vendor token, `--company-account` only after it -- so workspace placement is now a
  first-class `workspace` field that the plugin positions itself. `launch_args` keeps its position
  and meaning unchanged.

- **`produced_anything` counted other units' commits.** It measured from the run's original base, so
  any unit created after the first land inherited the landed commits and read as productive before
  its session wrote a line. That silently disabled the `NO COMMITS` warning and defeated the
  dependency gate that exists because a doc-review unit once reviewed a plan document that was never
  written.

- **A land that hit a conflict discarded the announcements for merges that had already succeeded.**
  Units are announced the moment their own merge lands, so a later conflict cannot un-announce an
  earlier success.

- **A failed board writeback reported a successful land.** The comment was attempted even when the
  status write had failed, and `land` returned success either way -- and since the unit was by then
  merged, no later land retried. `land`'s exit status is now three-way, so a caller can tell a land
  that failed to merge from a land whose merges worked but whose writeback did not.

- **A unit name could write outside the task directory.** The spill path was built straight from the
  name, so an absolute name discarded the directory and `..` traversed out of it. Names are
  validated as a single path component, and every task file must resolve beneath the task directory
  on save and on load. One over-broad `except OSError` is narrowed to `FileNotFoundError`: a
  directory standing where the spill file should be was absorbed as "the file is gone", and that
  path also cleared the pointer, making the loss permanent.

- **A legacy run with no stored run branch stopped recognising its own merged work**, so `check`
  reported `NO COMMITS` against work that had landed and `clean` would not reap it.

- **A land finished by hand is no longer guessed at.** A conflicted land tells the operator to
  finish with `git merge --no-ff`, which produces the shape every helper reads correctly. Inferring
  a fast-forward land from a recorded branch point was tried and reverted: it let an empty unit that
  merged the advanced run branch read as landed, which reached `clean --merged` and would have
  released its dependents. The conservative false negative -- a hand-finished fast-forward reads as
  empty -- is the deliberate tradeoff.

### Added

- **The lifecycle writes back to GitHub.** A run may carry an `issues` mapping, and `land` moves the
  card and posts one progress comment at each phase boundary, through saga's reconcile controller so
  the existing allowlist and idempotency keys apply. A run without the mapping writes nothing, and a
  missing saga never fails a land. `announce` is the operator's door for a boundary land did not
  cover. This closes a gap where nine phases across six vendors left a card on `Idea`, still
  labelled `needs-plan`, with zero comments.

- **`serialize`, an ordering edge that claims no output.** `after` means "I build on what you
  produce"; `serialize` means "do not run beside me" without asserting a dependency that does not
  exist. Both gate launch identically and `status` names which kind of wait holds a unit. The
  command and skill document when to use each, and a contract test fails if either forgets.

- **`diff`**, which shows what a unit itself changed, measured from its merge base and naming that
  base in the output. Diffing a unit against the run branch reports its siblings' work as its own
  deletions -- in one run it showed a 391-line test file as deleted by a unit that never touched it.

- **`check` reports `LOOKS DONE`** -- a unit the record calls running whose session is idle and whose
  branch has commits. That is the drift that quietly stalls a run.

- **`start` validates dependency names**, which only `expand` did. A typo in the first plan produced
  a unit that was never eligible, forever.

- **Long unit tasks spill out of the run record.** On a real 75-unit run, 83% of a 268 KB `run.json`
  was task prose, rewritten on every save and unreadable by anyone. Callers see no difference.

## [1.17.0] - 2026-08-17

### Added

- **`roster` now briefs every vendor it lists.** Under each one it prints both permission modes as
  they will actually be passed, whether saga is installed and how that vendor invokes it, and any
  behaviour that has caught a run out before. All of it resolved at the moment of asking rather than
  recalled.

  This is the answer to a recurring failure rather than a nicety: a vendor's behaviour was split
  across five separate tables, so where a table had a gap the orchestrator improvised — plausibly,
  and only found out a phase later. In one week that produced a builder reviewing its own work, a
  planner blocked on a question nobody could see, a task delivered as an attachment, and a unit
  prompted while still booting.

  Notes are carried for the quirks no table had room for: qwen never reports interactive readiness
  and its `--safe-mode` is not a permission flag; muse's `--yolo` disables the sandbox as well as
  approval, so it is bypass rather than auto; opencode's effort is a picker that cannot be answered
  from an unwatched tab; agy's saga plugin is a symlink into the operator's own checkout; codex ships
  saga as skills and prefixes with `$`.

### Note on what was deliberately not built

An earlier plan was to have `roster --probe` verify every claimed flag by trying it. Testing the
method first killed it: every vendor short-circuits `--help` before validating arguments, so the
cheap trial cannot tell an accepted flag from a rejected one, and the only trial that works is a real
prompt-mode run — whose invocation differs per vendor, which is the same stale vocabulary the probe
was meant to escape. A non-existent flag is already caught at launch by the delivery check added in
1.16.0, and a flag that exists but means the wrong thing — muse's `--yolo` — is caught by no probe at
all. Reading the vendor's own semantics is the only thing that catches that class, which is what
these notes are.

## [1.16.0] - 2026-08-17

### Fixed

- **A session was given its task before it could read one.** `launch` sent the moment the wrapper
  returned, but the wrapper returns when the *tab* exists, which is earlier than the agent being able
  to read anything. Sending into that gap does not fail: `herdr agent prompt` reports success, the
  agent finishes booting, and the prompt is gone. Observed three times across two vendors on a single
  live run — twice on qwen, once on agy — always with the same tell: a unit idle immediately after
  launch, having consumed nothing. `settle` reads that idle as **done**, and only `land` notices a
  phase later that it committed nothing.

  `launch` now waits for the agent to report it can take a prompt before sending, and checks
  afterwards that the session actually started. An agent that never reports readiness at all — qwen —
  has nothing to wait for, so the window is simply spent, which is still later than sending
  instantly.

  The check **reports rather than repairs**: a resend risks handing a unit its task twice, and a unit
  that quietly did nothing is worth a line in `status` more than it is worth a guess.

### Added

- **When to give a run more than one workspace.** A workspace is the unit of attention, not of
  isolation — that is the worktree. Below about six concurrent units, one workspace is right and a
  second is overhead; above it, one workspace becomes a wall of tabs and the operator can no longer
  see what is waiting on them. One issue is one lifecycle and a lifecycle is the natural workspace,
  so a parent with nine children is nine workspaces plus the umbrella the orchestrator sits in.

  Including the sharp edge: the agent wrapper's `--workspace` takes a **name**, so handing it an
  existing workspace ID creates a new workspace called that rather than joining the one you meant.

- **The remedy for append-only files conflicting on a wide phase.** Nine planners each appending to
  the same engineering journal is a conflict on every land after the first, though every entry is
  distinct and all should survive. Git's built-in union merge driver, set locally in
  `.git/info/attributes`, keeps both sides with no markers — noted for journals and changelogs, and
  explicitly not for source.

## [1.15.0] - 2026-08-17

### Fixed

- **muse's constrained mode was full bypass.** Both `auto` and `bypass` were `--yolo`, which muse's
  own help defines as "disable approval and sandboxing and trust this workspace for this run". So a
  unit asking for the constrained mode ran unsandboxed — a safety claim backwards. `auto` is now
  `--approval-mode never`, which stops muse asking without dropping the sandbox; `bypass` stays
  `--yolo`.

- **qwen had no way to escalate at all.** Both modes were empty. `--yolo` is absent from
  `qwen --help` and works anyway — verified by running it, against a control showing qwen rejects an
  unknown flag with "Unknown arguments". Its own warning names the equivalent: "running headless
  with `--yolo` / approval-mode=yolo and no sandbox".

- **agy could not be given saga work.** Orchestrate reported zero capabilities for it, so any
  `/saga:` unit aimed at agy was refused outright. agy is Antigravity and its home is the Gemini
  config directory, where the plugin is a **symlink** into the operator's own checkout rather than a
  fetched cache — so a search for directories named `saga` finds only the saga *state*. With the
  path added, agy reports 24 capabilities including `plan`, `doc-review` and `code-review`.

### Changed

- **opencode's effort is recorded as unreachable rather than implied.** It is a variant — Default,
  high, max — chosen through `/variants`, which opens a picker rather than taking an argument, and a
  picker cannot be answered from a `setup` line in an unwatched tab. The command document now says
  to offer opencode on its model and leave the variant to the operator.

- A note against ever mapping qwen's `--safe-mode` to a permission mode: it reads like the opposite
  of `--yolo` and actually disables every customization, including the extensions saga loads.

## [1.14.0] - 2026-08-17

### Fixed

- **`clean --merged` could not reap anything until the very end of a run.** It asked whether a unit's
  branch was already in the operator's tree. Units land on the *run branch* as each phase finishes,
  and the operator's tree sees none of it until `collect`, once, at the end — so the answer was "no"
  for every unit for the whole run, and the only mode safe to run unattended closed nothing at
  exactly the time sessions pile up. The only way to reap mid-run was bare `clean`, which closes
  everything regardless of whether the work survived, including the worktree that is the evidence a
  unit failed.

  Reapability is now measured against the run branch, which is where `land` puts things. A unit is
  reapable as soon as its phase lands, so `clean --merged` belongs after every `land` rather than
  once at the end — and the command document now says so. A unit that landed nothing still keeps its
  tab and its worktree, and a unit marked `merge: false` is never reaped at all, because its branch
  holds the only copy of its work.

## [1.13.0] - 2026-08-17

### Fixed

- **A real task is too long to type into a pane, and arrived as an attachment nobody acted on.**
  For any vendor that will not take `herdr agent prompt` — qwen today — orchestrate types the task
  into the pane instead. Measured against qwen 0.21.13: 859 characters arrive as typed text, 1660
  arrive as `[Pasted Content N chars]`. The paste is submitted and the agent knows its size; it
  simply does not treat it as the instruction. Verbatim, to a 6402-character task: *"I can see
  you've pasted some content (6402 characters), but I'm not sure what you'd like me to do with it."*

  So the unit launched, the keystrokes were delivered, orchestrate recorded success, and the session
  sat waiting for an instruction it believed it had never been given. It went idle, `settle` marked
  it **done**, and only `land` reported — a phase later — that it had committed nothing. Since a real
  task runs to thousands of characters, that door was unusable for real work.

  Past 800 characters the task is written to `.orchestrate/tasks/<unit>.md` and the typed line points
  at it by absolute path. The leading saga command stays typed, because that is what makes the vendor
  load the skill — inside a file it is just prose. The handover is recorded in the unit's note.

  Verified end to end against a live qwen session: the same task that produced "I'm not sure what
  you'd like me to do with it" as a 6402-character paste is read from the file and answered
  correctly from a 212-character line.

## [1.12.0] - 2026-08-17

### Fixed

- **A dispatched unit no longer stops on a question nobody will see.** Saga's `/plan` names the
  family in its own `SKILL.md`: "Use `AskUserQuestion` for choices from a known set (destination,
  execution backend, scope class, resume-vs-mint)". Orchestrate pre-answered exactly one of those
  four, and the next live run stopped on the destination within minutes of starting — a planner
  sitting blocked in a background tab with the whole run queued behind it, which is the same failure
  the backend note had already fixed once.

  Every dispatched saga task now carries one rule instead: for a choice from a known set, take the
  most defensible option, say which, and continue. Pre-deciding each of the four instead would make
  this plugin model saga's entire question vocabulary and go stale the moment saga adds a fifth —
  the same closed vocabulary that sent a whole review phase around the plugin.

  The other half matters as much: a unit is told **not** to guess a real question about the work.
  "Should this also cover X" is the operator's call, and a confident answer to it produces confident
  work on the wrong thing. The unit writes the question into its output and stops, which is exactly
  what `settle` and the orchestrator are already watching for.

## [1.11.0] - 2026-08-17

### Added

- **`check` — report where the run record and the repository disagree.** Read-only; exits non-zero
  when it finds anything. The record is one JSON file and the truth is git plus herdr, and nothing
  watches the gap between them: on the live run for issue 48 a whole review phase was created
  outside the record and neither `land` nor `clean` could see it. Five shapes, each a comparison
  rather than a rule:

  | Finding | Compares |
  |---|---|
  | `UNRECORDED` | a run-owned branch against the unit table |
  | `NO COMMITS` | a unit marked done against its branch |
  | `NOT LANDED` | a unit marked done and set to merge against the run branch |
  | `SESSION GONE` | a unit marked running against herdr |
  | `STILL WORKING` | a unit marked done against herdr |

  `NOT LANDED` is gated on the unit's `merge` intent. Without that gate it fires on every correctly
  handled competing-plan branch, which was measured on the real run: six of seven properly recorded
  units also had unlanded commits.

- **`adopt [--yes]` — put stranded unit branches back into the record.** Rebuilds a unit from what
  is still true: name and branch from the ref, worktree from git, and vendor, pane and tab from the
  live session matched on its working directory. Without `--yes` it writes nothing.

  `task`, `after`, `model`, `effort` and `permission` are left at their defaults rather than guessed.
  They cannot be recovered, and the session has already been given its task, so nothing here is ever
  sent to it again.

### Fixed

- **A command that is not installed is now a result, not a traceback.** `run(..., check=False)`
  promised that every failure comes back as a return code, but `subprocess.run` raises rather than
  returning when the program does not exist — so `check` and `adopt`, which had already decided
  herdr was optional, crashed on any machine without it. Missing now surfaces as return code 127,
  the shell's own "command not found", and `check=True` callers get one sentence instead of a
  traceback. `poll` carried the same latent fault and is fixed by the same change.

### Changed

- `poll` accepts an already-fetched agent list, so a caller looking at every unit pays one herdr
  round trip for the run instead of one per row — an unresponsive herdr costs the timeout once.


## [1.10.0] - 2026-08-16

### Added

- **`launch_args` on a unit — extra arguments for the launcher, carried through untouched.**
  `model` and `effort` are what every vendor has in common; this is everything else the wrapper
  knows and this plugin does not. `--company-account` is the case that forced it: the wrapper
  intercepts that flag and swaps the configuration directory before the tool starts, so it never
  appears in the tool's own `--help` and could not be expressed through a unit at all. On the live
  run for issue 48 the operator asked for it, the plugin could not carry it, and an entire review
  phase was launched by hand — outside the run record, where `land` and `clean` cannot reach it.

  Nothing is validated here on purpose. An allow-list of acceptable flags kept in this file would be
  the same closed vocabulary one level up, going stale silently as the wrapper releases on its own
  schedule. The wrapper already rejects what it does not accept, by name.

- **`merge` on a unit — defaults to `true`; `false` means the branch is to be read, not merged.**
  `land` previously merged every finished unit, which is the one thing the command's own
  documentation forbids for competing plans: several planners writing their own version of one
  document cannot be merged by git without a conflict at best and a silently interleaved plan at
  worst. On the issue-48 run that made `land` unusable, and every merge was done by hand.

  The plugin does not work out which units conflict by comparing branches for overlapping paths.
  That is real work, wrong in both directions, and it decides something the person who wrote the
  phase already knows.

### Changed

- **`land` names the finished units it held back**, alongside the units that committed nothing. A
  branch holding the only copy of something is never quietly left behind — silence would read as
  "everything landed."


## [1.9.0] - 2026-08-16

### Fixed

- **A builder no longer reviews its own work when the run has a review phase.** Saga's `/work`
  Phase 5 calls `/code-review` programmatically as its own pre-PR gate. In a single session that is
  right; under orchestration it is a self-review by the builder's own vendor, which is exactly what
  the roster rule forbids — and the wasted pass is the smaller problem. Phase 5.3 blocks on any P0
  or P1 finding and its only documented exit is an operator override with a recorded rationale:
  a question, in a background tab, waiting forever, after an hour of build work. The observed run
  came back clean and so survived it.

  A `work` unit is now told to skip that gate, but **only when the run actually has a code-review
  phase of its own** — read off the unit table, in any vendor's spelling. Without one, the in-loop
  gate is the only review there is, and suppressing it would remove the review rather than move it.

### Added

- Tests covering what a dispatched saga unit is actually told: vendor spelling, the two
  backend notes, and the new review-elsewhere note including the case where it must not fire.


## [1.8.0] - 2026-08-16

### Fixed

- **The planner is told the backend too, not just the builder.** 1.7.0 told `/work`, but `/plan`
  §5.2 offers the backend as well — so under orchestration the planner would hang before the builder
  was ever reached. Both stages now get a note, and they differ because the jobs differ: `/plan` is
  told to record `backend:` in the plan's frontmatter, `/work` is told the plan already says so.
  Together with saga's matching change, the decision now travels on the committed document rather
  than in an untracked saga tick that never crosses a worktree boundary.


## [1.7.0] - 2026-08-16

### Fixed

- **A `/work` unit no longer stops to ask which execution backend to use.** Saga's `/work` offers the
  backend unconditionally — its contract has no skip-if-already-decided path — and an
  `AskUserQuestion` in a background tab waits forever. It was caught only because the operator
  happened to be watching that tab; unattended, the unit would hang.

  The backend is a property of the run, not of a unit, so it is decided up front: the plan carries
  `"backend": "inline"` and orchestrate appends the decision to every saga `work` task when it
  sends. Always inline — a dispatched unit is already one of several parallel sessions, and nesting
  a workflow inside one is the orchestration-of-orchestration this plugin exists to avoid.

  Unlike saga's engine offer there is no stored preference to pre-seed, and the archived
  implementation never handled this either, so the task text is the only lever saga exposes today.
  The durable fix belongs in saga: `/work` should honour an already-recorded
  `orchestration_operator_choice` instead of re-offering.


## [1.6.0] - 2026-08-16

### Added

- **`~/.config/orchestrate/models.json` — the models the operator actually uses.** A vendor's model
  list is a fact worth asking for; deciding which of them matters is a preference, and a preference
  belongs in a file the operator owns. opencode alone fronts 164 models across eight providers, so
  offering four of them is noise — and it was wrong three rounds running. `roster --models` now
  leads with the favourites and shows the vendor's full list beneath. Absent or unreadable, nothing
  changes: it is a convenience, never a constraint, and a model not listed is still usable.

### Fixed

- **Model listing no longer times out inconsistently.** `agy models` can take most of a minute on a
  cold start, and the 20-second bound made it report "cannot list its models" on one run and
  enumerate them on the next. An answer that changes run to run is worse than a slow one for a
  command the operator invoked deliberately.


## [1.5.1] - 2026-08-16

### Fixed

- **The saga command is translated per vendor when it is sent, not left to the interview.** 1.5.0
  documented that codex takes `$saga:plan` and grok, qwen and opencode take `/plan`, then relied on
  the interview to render each unit's task correctly. It did not: a live run dispatched `/saga:plan`
  — claude's form — to a codex unit, which reads it as prose and does something of its own. Silent,
  like every other wrong-prefix failure here. `normalize_task` now rewrites an explicitly namespaced
  saga command into the receiving vendor's form at the moment of sending, so the interview writes
  `/saga:<cap>` once for everybody and cannot get it wrong.

  Only an explicitly namespaced command (`/saga:x` or `$saga:x`) is rewritten. Plain prose, file
  paths and bare slash commands are left exactly alone — guessing at what is and is not a command is
  how this goes wrong in the other direction.

### Added

- **Whether a vendor has saga at all is now resolved from disk, not believed.** `saga <cap>` locates
  each vendor's install and reports what it finds: claude under its plugin cache, codex as skills
  with no commands directory, grok in its marketplace cache, qwen as an extension, opencode as flat
  command files. **agy and muse have no saga install** — only a stale backup in agy's case — so a
  saga task sent to either does nothing whatever prefix it carries. That was invisible before.
- **`start` and `expand` refuse a saga task aimed at a vendor without saga**, naming the unit and
  the vendor, before a tab opens. The prefix was never the only way this failed.


## [1.5.0] - 2026-08-16

### Changed

- **A run now has a shared branch, and units land on it — the way a team uses a feature branch.**
  Previously each unit branched from its predecessor's branch, so a reviewer read the planner's
  branch directly. When the planner committed nothing, the reviewer opened on an empty tree, found
  no plan, and wrote a confident review of a document that had never existed. Now `start` creates
  `orch/<run-id>`, every unit branches from it, `land` merges finished units back onto it between
  phases, and `collect` merges that one branch home at the end. A reviewer sees a plan because the
  plan was landed, not because it guessed which branch to read.
- **`land` names any unit that finished without committing.** That is the failure worth surfacing —
  not a missing merge, but a session that produced nothing and reported itself done.

### Fixed

- **Untracked files no longer block `land` or `collect`.** The dirty-tree check counted untracked
  files, and `.orchestrate/` is untracked in every real repository, so both would have refused on
  every run. Only tracked modifications block a merge.
- **Unit branches are `orch/<run>-<unit>`, not `orch/<run>/<unit>`.** Git cannot hold both
  `orch/<run>` and `orch/<run>/<unit>` as branches — one ref would have to be a file and a directory
  at once, and worktree creation failed outright.
- **A unit still will not run against a dependency that produced nothing**, as a backstop. A dependent unit opens on
  its dependency's branch; if that branch is still at the base commit there is nothing to work on.
  Launching anyway does not fail loudly — the session finds no plan, no diff, no artifact, and
  writes something plausible about nothing. That happened: a doc-review unit on grok reviewed a plan
  document that had never been written, and produced a confident review of it. `go` now checks each
  dependency for commits and skips the unit with a plain reason instead of opening that tab.

### Changed

- **`wait` is told by herdr instead of asking it.** Salvaged `herdr_events.py` from the archived
  implementation: a newline-delimited JSON client for herdr's event socket, subscribing to
  `pane.agent_status_changed` and blocking in the kernel until a line arrives. Two pieces of
  protocol knowledge came with the salvage and are the reason it was not rewritten from the schema —
  subscriptions use the dotted vocabulary rather than the underscored broadcast names, and the
  first line back is a `subscription_started` handshake that must not be read as an event.
  A third was found by testing against the live socket: **subscriptions are per pane**, so a request
  without `pane_id` is rejected outright. Units therefore record their `pane_id` at launch.
  Dropped from the salvage as unneeded here: reconnect-with-catch-up, threading, and connection
  accounting. `herdr agent wait` remains as the fallback when the socket is unreachable.


## [1.4.0] - 2026-08-16

Round four, from the first run that reached dispatch. Two competing plans were produced at xhigh
over twelve minutes and both were lost.

### Fixed

- **Units could not write the worktree they were given.** Orchestrate passed no permission flag, so
  every unit ran at its vendor's default: codex answered "I can't write", claude sat in plan mode.
  Zero commits from either planner; both plans existed only as terminal scrollback. Each vendor is
  now launched with a permission level: `auto` by default — enough to get on with its own work
  without stopping to ask — and `bypass` per unit for a free hand. All seven vendors are covered,
  not just claude and codex; claude and grok turn out to share the same mode vocabulary. The
  worktree is the blast radius either way.
- **A bare `/plan` is a command nowhere.** Saga is installed for every vendor but invoked
  differently: `/saga:plan` for claude, `$saga:plan` for codex, `/plan` for grok, qwen and opencode.
  Sent bare it arrives as prose and the agent does something of its own — which is how a `/plan`
  unit produced claude's built-in plan mode. `orchestrate.py saga <cap>` renders the right form.

### Added

- **Unit names are descriptive.** `plan-claude`, not `p1a` — the name becomes the herdr tab title,
  the branch and the worktree directory, and it is what the operator reads in a screen of tabs.
- **`wait` — block until a running unit settles, driven by herdr's events rather than polling.**
  `herdr agent wait` is level-triggered: it returns at once if the agent has already settled
  (measured at 0.010s) and otherwise blocks inside the server. So there is no race between checking
  and waiting, and no loop burning cycles. Replaces the previous advice to watch with a poll loop.
- **`clean --merged` — close only units whose branch is already in the tree.** That is the one case
  where closing is free: the work is in HEAD, so the tab and worktree are pure overhead. Everything
  unmerged is kept, because its worktree is the evidence you look at when a unit went wrong.


## [1.3.0] - 2026-08-16

Round three of live operator use. Every vendor can now be given a tier, and the vendor list means
what it says.

### Fixed

- **The tier flag table was stale in four places, silently.** `claude` grew `--effort` and was being
  launched with no effort control at all — as the default planner. `agy` and `muse` were absent
  entirely despite both taking `--model` and an effort flag. Read from each tool's own `--help`.
- **`roster` is now `known vendors ∩ available here`, not everything the wrapper lists.** Orchestrate
  has to know how to drive a vendor before offering it, so Hermes profiles and provider variants are
  reported separately rather than presented as choices. Both halves of the intersection matter: a
  vendor this plugin understands is useless on a machine without it.

### Added

- **`roster --models` asks each vendor which models it actually has.** Model names were the last
  thing still taken from memory — the same source that got the crew list and the flag table wrong.
  `grok` and `opencode` can answer; `claude` documents its aliases in its own help; the rest cannot,
  and for those the operator supplies the name rather than anyone guessing. Bounded by a timeout,
  because `agy models` can hang and a frozen interview is the failure this plugin keeps fixing.
- **Notes on an interview answer are instructions.** "Use grok for the second plan instead of codex"
  is applied and carried into the table, and beats the option it was attached to. The table is
  edited in plain language and redrawn in full, so what is approved is what runs.
- **`setup` on a unit — slash commands sent into the session before its task.** `["/effort high"]`
  for a vendor whose command line has no effort flag. Every vendor can therefore be given a model
  and an effort: through the command line where one exists, through the session where one does not.
  No vendor is presented as untierable.
- **`roster --probe` compares the flag table against each tool's own help and reports drift.** It
  tests the token orchestrate actually passes, so codex's `-c model_reasoning_effort=` config
  override is not mistaken for a missing flag. This check caught a regression in the same change
  that introduced it: `opencode` really does take `-m/--model` on its interactive session, and had
  been wrongly removed.


## [1.2.0] - 2026-08-16

Round two of live operator use. Three corrections, all from watching the interview run.

### Added

- **`roster` — the agents this machine can launch, asked of the wrapper every time.** Reads the
  `Tools:` section of `agents --help`. The interview was using `agents --crews`, which is the
  operator's own saved workspace layout and has nothing to do with orchestration: it offered three
  agents when seventeen were available, silently dropping qwen and every other installed agent. That
  was a quiet wrong answer, so it is now code rather than an instruction.
- **`start` and `expand` refuse a unit naming an agent the wrapper cannot launch**, so a typo fails
  before any worktree exists rather than as a per-unit launch failure afterwards.

### Changed

- **A review phase is a panel, not a seat.** The interview asked which single vendor would do
  doc-review and which would do code-review. It now asks how many reviewers a phase gets and turns
  each into its own unit, tab, worktree and vendor — three reviewers is three rows. The count is a
  default for unattended runs; the operator re-confirms the actual rows at the expansion gate, in
  the session they are actually watching.
- **`engine_prefs` defaults to `none` for review stages.** The panel is orchestrate's job; letting
  each panel member also take a saga second opinion doubles the sessions without being asked. The
  stored answer still does its real job of stopping a dispatched tab hanging on the offer.
- **No remembered vendor opinions in the interview.** It volunteered that a vendor had gone idle in
  unrelated work — not checkable from the repository in front of it, not asked for, and it steers a
  choice that belongs to the operator. Vendor commentary is now limited to what `roster` reports.

## [1.1.1] - 2026-08-16

### Fixed

- **The agent-session wrapper is `agents`, not `agent`.** The operator renamed it because `agent`
  now belongs to another tool on the machine. Orchestrate hardcoded the old name in `agent_argv`,
  and the failure would not have been a missing command — it would have launched the other tool with
  flags it has never heard of. The name is now resolved and checked before use, overridable with
  `ORCHESTRATE_AGENT_LAUNCHER`, and a wrapper that is not on `PATH` produces one clear sentence
  instead of a confusing wrong-program run. `agents --crews` corrected in the command and the skill.

## [1.1.0] - 2026-08-16

### Added

- **`expand` — append units to a run already in flight.** The up-front table can only name the later
  phases, never their units: what `/work` splits into is decided by the plan, which does not exist
  when the operator approves. A phase that names the next phase's units is now read when it
  finishes, the operator approves those rows alone, and they join the same run — so `after` still
  reaches back and one `collect` covers everything. Refuses a duplicate name or a dependency that is
  in no run.
- **`engine_prefs` — saga's external-engine offer, answered before dispatch.** A `/doc-review` or
  `/code-review` session with nothing stored stops and asks the operator, in a background tab nobody
  is watching, and waits forever. The plan's `engine_prefs` block is now written to
  `<worktree>/.saga/engine-prefs.json` when the worktree is made; saga reads it and skips the
  question. Verified end to end against saga's own `engine_offer.py`, which returns
  `prompt_required=False, source=stored` for a worktree orchestrate prepared.

### Changed

- **The interview asks at the right layer.** Vendors are chosen once for the whole orchestration as
  an allow-list, not one per unit. `/plan` is asked whether it wants competing independent plans
  from several vendors, which this session then merges itself rather than dispatching a merge unit.
  The reviews are asked once for their second-opinion policy, applied across every lifecycle.
  `/work` and `/code-review` are asked nothing — their vendors and lenses come from the plan.
- **Every question carries a recommendation**, and a declined question no longer stalls the run: the
  command takes the most defensible answer, says which it took, and continues to the table, which is
  the real gate and fully editable.
- **The command documents the layering** — orchestration, lifecycle, phase, unit — so a parent issue
  with children reads as one lifecycle per child rather than one flat list.

## [1.0.1] - 2026-08-16

### Fixed

- **The command told the session to run a script path that only exists in this repo.** Both
  `commands/orchestrate.md` and the skill printed
  `S=plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`, which resolves only when the
  operator happens to be inside `infiquetra-claude-plugins`. `/orchestrate` is for running work in
  *other* repositories, so every real use would have failed at dispatch with a missing file. Both
  documents now resolve the installed script through `$CLAUDE_PLUGIN_ROOT`, falling back to the
  plugin cache.
- **`uv run python` required the operator's repository to be a uv project.** The script imports
  nothing outside the standard library, so both documents now call `python3` directly.

Found by the first real operator run, against issue 48 of `campps-e2e-canary`, before it reached
dispatch.

## [1.0.0] - 2026-08-16

### Changed

- **`/orchestrate` exists.** The command reads a prompt, an issue, a parent issue's children, or a
  document; interviews the operator for what it cannot infer; and hands back an editable table of
  unit, saga capability, agent, model, effort and dependency. Nothing launches until that table is
  approved.
- Each unit runs in its own git worktree and branch, in its own herdr session, with any agent
  configured on the machine. A unit with dependencies branches from the last one it names, so a
  `/work` unit opens on top of its `/plan` unit's output.
- State is a single `.orchestrate/run.json`.

### Removed

- The durable register with column ownership, per-column writers and generation locks; the
  completion evidence gate; the mirror worker; admission slot reservations; the consensus panel and
  bounded review loop; token accounting and spend ceilings; and the composed runner's crash
  reconciliation and claim transactions — 14,875 lines of production code and roughly 15,700 lines
  of tests.
- None of it defended against a failure that can happen to one operator on one machine. The full
  implementation is preserved on `origin` at `archive/orchestrate-full-implementation`, so any
  individual piece can be pulled back if a real run ever justifies it.

### Notes

- qwen does not report interactive readiness, so `herdr agent prompt` refuses it; the dispatcher
  falls back to typing into the session's pane.

## [0.13.0] - 2026-08-16

### Changed

- The durable register keeps authored intent and outcomes only. Where a child is running -- its
  pane, tab, working directory, process id, observed state and vendor -- is no longer copied into
  columns that cannot know when the world moved on. One named function per question asks the
  terminal control plane at the moment the answer is used, with no cache and no per-read facts
  object behind it.
- A complete answer that contains the thing, a complete answer that contains nothing, and a query
  that could not be completed are three distinct outcomes, and only the third fails closed. A
  failed, partial, ambiguous or malformed query raises; it never degrades into an empty answer.
- Launch recovery resolves through the same complete-snapshot parser as every other reader, so a
  partial answer can no longer be read as "no session exists" and start a second live session for
  work already running.
- An admission slot held by an expired owner is reclaimed on confirmed absence, retained on
  confirmed presence, and left untouched when the query fails, so the concurrency limit no longer
  ratchets in one direction until the process restarts.
- The subscriber considers a row for its owner-missing signal only when a snapshot could place that
  row, so an unrelated tab closing on the host no longer wakes the orchestrator.
- A register file written before this change is normalised on read and rewritten in the new shape on
  its next ordinary write.

### Removed

- The seven live-session columns, from the schema and from every writer. A guard walks every
  module's syntax tree rather than naming the writers that exist today.

## [0.12.1] - 2026-08-16

### Fixed

- Vendor identity comparisons now normalise compatibility forms, remove Unicode format characters,
  collapse whitespace, and fold case. Cross-script confusables remain distinct because vendor names
  are trusted caller input, not text from which identity is inferred.
- Every unusable answer is recorded in the panel outcome, including excluded, unknown, duplicate,
  wrong-type, and unidentifiable answers. Invalid answers halt a panel without discarding blocking
  evidence already returned by a voting seat.
- A plan rigor report no longer calls composed edits applied when their net result is byte-identical
  to the reviewed plan. Those edits return as recommended remainders instead.

## [0.12.0] - 2026-08-16

### Added

- A consensus panel whose roster excludes the unit builder's vendor. An external-only roster also
  excludes the home vendor. The decision boundary rebuilds the layer policy and immutable
  denominator, then checks roster self-consistency against the identities the roster declares.
- One independent vendor per voting seat, explicit configuration-to-roster layer linkage, and panel
  outcomes that retain structural exclusions and name malformed responses.
- Asymmetric panel authority: one blocking gate rank halts, while proceeding requires a complete,
  non-blocking response from every constructed voting seat. Missing seats never shrink the
  denominator, an under-strength roster cannot satisfy its original quorum, and malformed responses
  cannot discard blocking evidence returned by another seat.
- Per-dimension instruments. Gate dimensions use a blocking rank and refuse numeric thresholds;
  score dimensions use a numeric convergence threshold and refuse ranks. Scores report convergence
  without deciding whether work proceeds. Every enabled panel includes a gate, every score is paired
  with its seat, and an empty score series never reports convergence.
- A single-voter rigor pass for orchestration plans. It atomically applies evidence-backed edits
  whose anchors are unique in the reviewed bytes and do not overlap. It preserves unrelated line
  endings, records each replacement, refuses symlinks and stale digests, and hands ambiguous or
  judgment-dependent findings to the operator. Its slotted report type has no decision field.

## [0.11.1] - 2026-08-16

### Fixed

- The last allowed iteration escalates for a recurring class, an earlier class that remains
  undisposed, an explicitly blocking finding, or an unperformed review. New non-blocking findings
  close the review without escalation.
- Blocking is a required keyword-only boolean on each finding. The loop does not infer it from the
  finding's free-form rank.
- Every verdict produced from a performed report returns that report's findings, including findings
  filed when the last allowed iteration closes.

## [0.11.0] - 2026-08-15

### Added

- A bounded review loop for the orchestration lifecycle. At most three iterations per unit over its
  lifetime, a re-review scoped to the change since the previous iteration, recurrence tracked by a
  defect class the reviewer declares rather than one inferred from prose, and three verdicts:
  `pass`, `halt-and-repair`, `halt-and-escalate`.
- Findings still open on the last allowed iteration escalate mechanically, regardless of the rank
  they carry. There is no remaining iteration in which to repair, so instructing a caller to repair
  would be untrue whether the class is new or recurring.
- Resolution must be authored. A report carries the classes it disposes of, and `pass` is refused
  while a class raised in an earlier iteration is still open, so a reviewer's silence about an
  unchanged path is no longer read as a fix. Disposing a class that was never open is refused, as is
  disposing and re-raising one class in the same report.
- A review that could not be performed is recorded separately from one that found nothing, emits no
  verdict, does not consume the iteration, and has an explicit conclusion that is never `pass`.
- Unit identifiers and defect classes are canonicalised once at a single site each, so surrounding
  whitespace can no longer split one unit into two or hide a recurring class.

## [0.10.0] - 2026-08-15

### Fixed

- An unparseable usage line marks the row and returns. The spend gate refuses,
  and a later parseable sample does not clear the mark. An ordinary output
  line containing the word token no longer kills the subscriber that holds
  the run's event stream.
- A completion verdict and the phase it justifies are one register write. A
  reap records `reaped` and `expected_state=exited` as one write.
- A writer-less upsert of `agent` cannot change what the run is charged.
  Spend excludes supervising rows by the owned `role` column, not by
  matching an `agent` name. `tokens_reserved` is owned by admission's write
  gateway, so a writer-less upsert cannot lower the charge.
- The mirror's owned-column seam names the `role` writer on the same write
  that records the rest of the mirror identity. The column stays owned; the
  identity stays one write.

## [0.9.3] - 2026-08-15

### Fixed

- An owned register column arriving at the generic merger without that
  column's writer is refused. Production writers of `phase` and
  `observed_state` go through the named setters. The reservation record is
  owned by the admission write gateway, not by reserve alone.
- Equal delta usage lines add. A content hash is not a delivery identity.
  A line matching both usage grammars is refused. Unparseable telemetry
  after a prior sample fails the spend gate closed.
- `commit_plan` writes the reservation, generation, phase, and plan row
  under one admission-then-generation critical section. Retirement takes
  the admission lock first, so it cannot split a reserved verdict from its
  reservation.
- A child is charged zero only when its phase is `planned`. A missing
  phase is unknown and fails closed.
- The generation sidecar is written atomically under the generation lock.
  An empty or unreadable sidecar is absent; a generation already stamped
  on the register is restored rather than minting a second one.

## [0.9.2] - 2026-08-15

### Fixed

- Shared register columns name one writer. `phase="planned"` cannot replace a
  terminal phase. `artifact_path` is written only when the artifact is settled.
  Admission writes only the row fields it owns.
- Re-planning a finished child is refused, including when its reservation is
  still held. `activate_slot` refuses a terminal row.
- An inferred snapshot absence is not immediate death. Reclaim of a held slot
  still requires a directly observed exit, an expired holder lease, or a
  terminal phase.
- A silent vendor is charged its declared `tokens_max` once launched. An
  observed value cannot lower that ceiling.
- `commit_plan` no longer accepts per-call limits the rendered plan does not
  own. The durable host policy must still equal the bounds the operator was
  shown. The presentation receipt is bound to a generation and is forgotten
  with the register.
- Queue promotion takes the globally oldest eligible entry by enqueue time.

### Changed

- A planned or queued child has spent zero. A launched metered child with no
  telemetry still fails closed.
- Usage replay is deduplicated by event identity. Cumulative totals keep a
  monotonic maximum; input/output samples add.
- Child `scope` is a sequence of bounded repository-relative paths.
  `tokens_max` is an exact positive integer.
- An absent host policy file still defaults. Every other unreadable or
  malformed file is an admission error that names the path.

## [0.9.1] - 2026-08-14

### Fixed

- Admission owns reservations, the queue, and the host policy. It no longer
  writes `phase`. Occupancy for the bound is the reservation set on every live
  run. Active phases without a reservation are evidence, not enforcement.
- A queued child that has already finished is dropped from the queue rather
  than promoted back to `planned`.
- Host bounds count every live run. An optional `admission.policy` file is
  the durable operator-set rule; reserve never writes it. Absent file means
  the documented defaults. A write still binds a run to its own stored work
  location.
- Reusing a row id for a different vendor or shape is a refusal.
- A planned reservation is not reclaimed because it has no pane yet. An
  observed `exited` holder is reclaimable even if the pane id remains.
- Every planned child declares a positive `tokens_max`. A silent vendor is
  charged that declaration, not an unlabeled estimate. The run-level spend
  gate no longer skips an unaccounted child.
- `commit_plan` requires a presentation receipt whose digest matches the
  rendered plan, which now includes scope, artifact, predicate, and
  integration mode.
- Observed-token writes hold the generation lock across read and write. A
  redelivered usage line is not counted twice. `context left` and token rates
  are not spend.

## [0.9.0] - 2026-08-14

### Added

- Planning decides the split and the route and then stops. `planning.py` never
  imports or calls `launch_child`. The operator is shown the plan before
  `commit_plan` writes a reservation. A plan that has not been presented is
  refused.
- Routing maps a work shape through `tier_policy.json` and the shared tier
  resolver's `resolve_for_runtime`. An unavailable preferred vendor walks
  `claude`, `codex`, `grok`, `qwen`, `muse`, `agy` and records the
  substitution. An explicit operator vendor, model, or effort is recorded as
  an override. See `references/routing.md`.
- Register-owned admission: per-vendor and aggregate work-in-progress bounds,
  a durable FIFO queue at the document root, an atomic reservation under a
  host-wide admission lock taken before the per-run generation lock, a
  release that advances the queue, and reclaim of a dead holder's slot.
  Exceeding a per-vendor bound queues even when aggregate room remains.
- Spend accounting. `tokens_reserved` is produced by `reserve_slot` and
  consumed by `check_spend` when the vendor has no usage line. `tokens_observed`
  is produced from a `pane.output_matched` usage line (the subscriber is the
  writer) and consumed by `check_spend` when the vendor reports usage. Missing
  telemetry fails closed. `authorize_spend` is never passed `None` to mean a
  silent vendor.
- `canonical_work_location` bounds the git subprocess at five seconds. A
  timeout, a missing git, or a non-repository is `intended.resolve()`, not the
  nearest existing ancestor. Two missing siblings of one parent no longer
  compare equal.
## [0.8.0] - 2026-08-15

### Fixed

- **The scanner's bounds now have exactly one way to end, and it is the honest one.** The
  structure walk returned a bare "not found" when it hit its depth limit, and the caller could
  not tell that answer from "no declaration present" — so a nine-level JSON object whose
  innermost `argv` was bound to a proper sequence was accepted, with the scan reporting that it
  had finished cleanly. Depth 7 refused; depth 9 did not.

  This was the third appearance of one shape, once per review round, each with a different
  constant: a decode budget reported clean on exhaustion, then a line sweep did, then the walk
  did. Each was repaired alone while the next one waited. The repair this time is structural
  rather than another remembered rule — every bound (walk depth, walk size, encoding layers,
  decoded bytes, embedded regions) is consumed through a single budget object, and the scan
  builds its one and only result from that budget at a single return point. A bound cannot be
  reached and reported as a clean scan because there is no second place where completeness is
  decided, and a test asserts that single decision point structurally.

- **Three bounds were refusing the reading work the mirror exists to do.** A 201-line
  comparison of two children's reports — the example this unit uses for work that must leave the
  operator's channel — was refused as unexaminable. So was a one-line question naming seventeen
  `*args`-style identifiers, and thirty-three short Base64 notes. Fail-closed is right; failing
  closed at a threshold ordinary prose crosses is a defect in the same way an accepted
  declaration is.

  The line cap is gone: parsing every line of a worst-case instruction at the byte cap measures
  0.083s, so the byte cap was already the real bound. The decoded-payload cap is now measured in
  bytes rather than in a count of payloads, because a count is not a measure of work. The walk
  depth is raised well above anything a real document reaches, which it can be safely now that
  reaching it refuses.

- **Alias amplification is bounded by the walk, not by counting alias-looking text.** The
  previous guard counted `*name` occurrences, which fired on Python `*args` and markdown
  `*emphasis*` — shapes this repository's own source produces dozens of times per file — and did
  not recognise YAML's numeric aliases (`*1`) at all. A 424-byte document using numeric anchors
  took over nine seconds to scan. The structure walk now visits each shared node once, which
  brings the same document under three milliseconds and makes the count unnecessary; the guard
  that was not protecting anything has been removed rather than tuned.

- **A declaration after a `---` separator was parsed by nothing.** `yaml.safe_load` returns
  only the first document of a multi-document stream, so a second or third document was never
  examined while the scan reported that it had finished — the same shape as the bounds above,
  in a loader rather than a budget. Every document in the stream is now loaded. Found by this
  unit's own adversarial pass rather than by a review.

- **A Python mapping whose `argv` is a tuple, written after a prose prefix, reached the pane.**
  `Run this: {'argv': ('uv', 'run', 'pytest', '-q')}` is not valid YAML, is not the whole text,
  and the textual fallback does not recognise `(`. Balanced `{...}` and `[...]` regions are now
  parsed individually, so the declaration is found by a loader. Locating the region is textual;
  deciding what it means is not.

## [0.7.0] - 2026-08-15

### Changed

- **The predicate detector parses and inspects the result; it no longer pattern-matches
  serialized text.** Matching text was unsound and imprecise at the same time, for one reason.
  YAML can bind the exact key `argv` without those four letters ever standing next to a
  separator — through an escape, or through an anchor and an alias — so a text detector missed
  real declarations. The same pattern fired on `sys.argv:` in an ordinary sentence, so it
  refused requests to read this repository's own source, which is the mirror's whole job.
  Parsing closes both directions with one change: after a safe parse an escaped key **is**
  `argv` and an alias-bound key **is** `argv`, and a sentence mentioning `argv` does not parse
  into a mapping with an `argv` key at all.

  The detector now unwraps Base64 and hexadecimal runs — repeatedly, until they stop decoding,
  so layered wrapping is followed rather than capped — resolves `\uXXXX` escapes, and parses
  under `json`, `yaml.safe_load`, `tomllib`, and `ast.literal_eval`, applying each to the whole
  text, to each individual line, and to string leaves inside a parsed structure. It refuses
  when a result is **a mapping with an `argv` key bound to a sequence**, which is the predicate
  schema's own shape: `PredicateSpec` rejects an `argv` that is a command string, so binding
  the rule to the schema is what lets a type annotation (`argv: list[str]`, an `argv` bound to
  a *string*) survive.

  Every loader is a safe loader — `yaml.safe_load`, never `yaml.load` — because a parser that
  executed untrusted input would be a worse defect than the one being fixed. Alias expansion is
  the one resource risk a safe loader still carries, so text carrying an unusual number of YAML
  aliases is refused as unexaminable rather than expanded. A textual fallback remains for
  material no loader can parse at all, and is documented as a heuristic rather than the
  guarantee.
  *The alias count is superseded in 0.8.0: it counted a text shape this repository's own source
  produces and missed YAML's numeric aliases entirely. A memoised walk bounds the amplification
  instead.*

  Refused now and not before: a YAML escaped key, a YAML anchor and alias, layered Base64, and
  hexadecimal. Accepted now and not before: `argv = permission_argv(runtime)`,
  `argv: list[str]`, `sys.argv:`, `def main(*argv: str)`, an annotation block, and a list of
  seventeen commit identifiers. A mirror that refuses ordinary synthesis is as broken as one
  that accepts a predicate.

- **Every published claim now states the same boundary.** The reference, this changelog, the
  skill page, the module docstring and the test names had drifted apart: the docstring
  disclosed an encoding depth limit while four other places said Base64 was caught. The
  contract is now written in two halves in `references/operator-channel.md` — what is
  mechanically refused (machine-readable declarations), what is not detectable (an English
  request, for which no general detector is achievable), and what makes the undetectable case
  survivable (a mirror opinion cannot become `verified`, because completion requires a dispatch
  receipt the mirror is never issued).

- **The skill page no longer says nothing distinguishes a thinking mirror from a dead one.**
  That sentence was retracted in 0.6.0 and survived in one place fifteen lines from its own
  correction.

### Fixed

- **The first look at a pane's revision counter no longer advances the clock.** A counter is
  only evidence of emission when there is a previous one to compare it against, so the first
  observation now records a baseline and leaves the reference where it was. Treating it as an
  advance let a supervision loop that started late report a long-dead mirror as `working` with
  the pane-revision feed named as the source — health the counter had not established. It
  delayed a hang rather than suppressing one, but it made calling the reader strictly worse
  than not calling it, because the dispatch clock would already have tripped.
- **A revision counter that goes backwards re-baselines instead of sticking.** A herdr
  reconnect restarts the series; previously a decrease wrote nothing at all, so real output
  stayed invisible until the new series climbed past the old maximum. The safe direction is
  kept — a restarted counter is not evidence of emission — while letting the feed recover.
- **A failed subscription acknowledgement retracts the previous one.** The acknowledgement is
  durable and the subscriber process is not, so a replacement subscriber could inherit a dead
  process's confirmation, turning the distinct missing-wire state back into a working-or-hung
  report. A caller presenting a list without the mirror's subscription is evidence the wire is
  gone, and is now treated as such.
- **A request to summarise commit identifiers is no longer refused.** Base64 candidates were
  counted before being decoded, so seventeen hexadecimal identifiers exhausted a budget and the
  scan reported itself incomplete. Only runs that decode to valid UTF-8 are payloads now.

## [0.6.0] - 2026-08-15

### Changed

- **A published guarantee was false and is now accurate.** The mirror's documentation stated
  that a predicate never reaches it. A predicate did reach it, three ways, and the claim has
  been narrowed to what the mechanism actually does while the mechanism itself has been made as
  strong as it honestly can be. The honest sentence is that the mirror is never *asked* for a
  verdict through this API. An instruction that describes a check in ordinary English is not
  detectable by any scanner, and the live agent beyond the pane is itself a program executor.
  Column ownership was previously offered as the containment for this and does not contain it:
  it stops a mirror's opinion becoming a `verified` row, not a claimed verdict being produced,
  and a claimed verdict with no second reader is the failure the requirement names.
- **Hang detection can now tell a thinking mirror from a dead one, and the earlier claim that
  nothing could was too strong.** The subscriber advances `last_event_at` only on a matched
  sentinel and the mirror's only subscribed sentinel is its return marker, so that feed alone
  makes the clock a per-request tolerance. `observe_pane_activity` reads herdr's pane-output
  `revision` counter from a `session.snapshot` — the feed the register names for this, naming
  this unit as its reader — and records it on the mirror's own row, so a pane still emitting
  keeps the clock fed and a pane that has stopped lets it trip. It is a snapshot read rather
  than a heartbeat subscription because the subscriber wakes the orchestrator on every handled
  event, so a heartbeat would wake the operator's channel on a timer. `MirrorLiveness` now
  reports which feed the answer rested on, so "working" from a stale clock and "working" from a
  live one are not the same word.

### Fixed

- **The predicate-declaration scan keys on the declaration's signature, not on one
  serialisation.** A predicate is the name `argv` bound to a value; JSON, a YAML block or flow
  mapping, TOML, a Python literal, a string nested inside another object, unicode-escaped
  braces, and Base64 are the same declaration in different clothes, and all are refused.
  Enumerating serialisations is a race the enumerator loses.
  *Superseded in 0.7.0, which replaces text matching with parsing — see that entry for why
  matching a signature in serialized text was still both unsound and imprecise.*
- **The scan fails closed.** An instruction it cannot finish examining within its budget is
  refused rather than passed. Reporting "clean" on exhaustion had turned a denial-of-service
  bound into the bypass: a real declaration parked behind 512 decoy braces was never inspected
  and was accepted, while 511 decoys were correctly refused.
- **Dispatch re-runs the request's checks on the object it is handed.** Every load-bearing
  check lived in a constructor while the one function that talks to the pane read attributes
  off whatever arrived, so any object with the right attribute names bypassed the closed kind
  vocabulary and the scan together. This closes the class rather than an instance of it.
- **Every clock input must be finite.** A NaN threshold passed validation because every ordered
  comparison with NaN is false, and positive infinity passed honestly; either made a dead
  mirror report `working` forever, reaching the affirmative state the unarmed error exists to
  prevent by a different door. Thresholds, dispatch instants, observed instants and the
  supplied `now` are all now required to be finite, and a non-finite threshold is refused at
  creation.
- **A zero or negative default return bound is refused at creation.** It is interpolated into
  the charter as the session's standing default, so zero told the mirror its default budget was
  nothing, which would make every return that honoured the charter oversized.

### Added

- **`resume_mirror` rebuilds a live session from the register alone.** The mirror's nonce and
  return markers previously existed only in an in-memory session object, so an orchestrator
  that died could not collect from a mirror that was still running — which contradicts the
  requirement that the mirror is persistent for the life of the orchestration. The row now
  carries them, and the identity is written before the launch side effect alongside the row
  itself. The run's single mirror is located by its `role` column when no row id is given, and
  two mirrors in one run are refused rather than guessed.
- **A missing subscriber wire is loud instead of silent.** The mirror's row records the
  `pane.output_matched` subscription its returns require. `acknowledge_subscription` compares
  it against the list the subscriber was actually given and refuses a mismatch; until something
  confirms it, `check_liveness` raises a distinct unconfirmed-subscription error rather than
  reporting a state. A mirror nobody is listening to and a hung mirror produce identical
  silence, and reporting the first as the second sends the operator hunting a hang that is not
  there.
- **Repository-visible change over a request window is observed and recorded.** The mirror is
  read-only by contract and nothing prevents it writing — `mutating=False` keeps it in the
  ambient checkout but is not a write fence, and because the mirror declares no artifact it
  never reaches the post-hoc scope check, so a violation was previously not merely unprevented
  but unobserved. The observation is reported on the return and recorded durably; escalation is
  opt-in through `assert_no_repository_change`, because this session reads the operator's live
  working tree, so the operator's own edit lands in the same window and attribution is not
  established. Isolation was rejected deliberately: a worktree would give the mirror a tree
  nobody is working in.

## [0.5.0] - 2026-08-15

### Added

- **The mirror**: a persistent paired session that performs the orchestrator's own work —
  synthesis, comparison, bulk reading — so the operator's channel stays answerable while work
  happens. Children do the outcome's work; the mirror does the orchestrator's. It is launched
  through the same session path as any child (dry-run preview, write-ahead label, trust-prompt
  check, nonce-bound readiness sentinel) and holds an ordinary register row, written **before**
  the launch side effect so a mirror whose launch failed is visible rather than absent.
- **A distilled return under an enforced byte bound.** A return larger than its request's
  declared bound is rejected whole rather than truncated, because a truncated return is an
  oversized one wearing the appearance of success. The rejection carries the byte count and
  never the material — an error that quoted the return would perform the absorption it reports
  — and it is recorded durably, so a rejection is distinguishable from a return that never
  happened. The bound a request may declare is itself capped at 16 KiB (default 4 KiB): this
  contract does not erode by being deleted, it erodes by being raised. A rejected return leaves
  the mirror ready and holding its context, so the cost is one round trip rather than the
  session.
- **The validity predicate never runs in the mirror.** Routing it there would turn verification
  back into a claim: the mirror reports a pass, the orchestrator never sees the bytes and cannot
  re-check, and the evidence-failure class reappears one layer up with no second reader. Three
  independent guards — a closed vocabulary of reading request kinds with deciding kinds refused
  by name; refusal of any instruction carrying a predicate declaration; and a module that
  contains no program-execution route and does not import the completion module. What no guard
  catches is an instruction that describes a check in prose; the containment for that is the
  written routing rule plus the fact that the mirror writes no `phase`, so its opinion cannot
  become a verified row.
- **Clock-based hang detection**, because nothing else reaches this failure. Every other failure
  in this system appears as a disagreement between two values; a hung mirror's expected and
  observed states agree perfectly, every child still looks healthy, and the operator's channel
  is dead. `check_liveness` therefore compares silence against the row's declared
  `max_quiet_seconds`, taking the current instant as an argument rather than reading the system
  clock. It reads and raises: it writes nothing, closes nothing, and demotes nothing, because
  what to do about a quiet mirror is a decision. A row with no declared tolerance raises a
  distinct "not armed" error rather than reporting health, and an idle mirror is never alarmed,
  because a mirror between requests is legitimately silent forever.
- **Non-blocking dispatch.** No subscription is held open, no pane is polled, and there is no
  timeout parameter. The outstanding request is durable before the line is sent, so a failed
  send leaves an armed clock rather than an idle-looking mirror. A second request while one is
  outstanding is refused explicitly with the outstanding id, never silently dropped.
- **Checkable column ownership.** Every register write in the mirror module passes through one
  seam that refuses, at runtime, any column outside `role`, `max_quiet_seconds`,
  `mirror_request` and `mirror_last_return`, and only on the mirror's own row. It does not write
  `artifact_path`, does not write `observed_state` (the subscriber owns that and rewrites it on
  every catch-up pass), and never promotes its own phase. The mirror row is identified by `role`
  rather than by `agent`, because `agent` carries the launcher's actual agent name for every
  launched row and a second writer of a shared column is a defect this codebase has paid for.
- **`references/operator-channel.md`**: the routing rule in writing. Work goes to the mirror by
  default; the exception list is five entries, each with the reason it is bounded by
  construction; anything not on the list goes to the mirror even when it looks trivial. It also
  states plainly what the clock does not establish — nothing distinguishes a mirror quiet
  because it is thinking from one quiet because it is dead, and the within-request heartbeat
  that would narrow the gap is deliberately not built, because the subscriber wakes the
  orchestrator on every matched event and a heartbeat would wake the operator's channel on a
  timer.
  *Half superseded in 0.6.0: the heartbeat reasoning holds, but pane revision does distinguish
  the two, and 0.6.0 builds that feed.*
- **Deliberate context management.** The mirror is persistent for prompt-cache benefit and
  continuity, and a mirror that has silently degraded is worse than no mirror because the
  orchestrator will still believe its answers. Its context is compacted or cleared on
  instruction, refused while a request is outstanding, and refused outright for runtimes whose
  context commands are not established here rather than guessed — an unrecognised slash command
  is a silent no-op that looks like a reset.

## [0.4.0] - 2026-08-13

### Added

- The live register is one JSON document per run, addressed by `run_id` in an
  orchestrator-owned host-local directory (default `~/.orchestrate/registers/<run_id>.json`,
  relocatable by `ORCHESTRATE_REGISTER_DIR`). A child cannot write it by working in its
  landing. A `run_id` is host-global: two callers that name the same id share one live
  document in one checkout. Two checkouts of one `run_id` are a collision. Every
  decision and mutation API requires `run_id`. `retire_run` forgets the per-run secret
  first, then archives the document into the recorded work location, then deletes the
  live file and the recorded-root sidecar, so a reused id is a new authentication
  identity. Sidecar create, key mint, key delete, and retirement share one per-run lock,
  so a concurrent mint cannot complete while retirement still holds it. Forgetting the
  key requires the coordinator-recorded work location, including when the live file is
  already gone. Both sides of a work-location comparison are canonicalized to the git
  top level. Claude and Muse have no
  workspace-write flag; mode `0600` does not exclude a child running as this account, so
  the seal does not defend that residual.
- Completion is the only path to `verified`. A child reaches it when its predicate's dependency
  closure is unchanged, its artifact was settled by the orchestrator's own rename, that artifact
  carries this dispatch's pre-established run binding, the predicate passes, the repository
  boundary is clean, the recorded destination has actually changed, and — for judgment-shaped work
  — a claimed independent verifier's depth sample is on record. A failure records a verdict when
  the landing belongs to the receipt's git repository; a landing in a different repository raises
  rather than records, because neither register is then a store this evaluation may write. A
  row's phase is `verified` if and only if its latest verdict is a pass: a first failure leaves
  the phase alone, and a failing re-evaluation demotes a previously verified row so the reap
  gate cannot consume a contradiction as a pass.
- The receipt binds **every input the verdict depends on**, not the labels that name the dispatch.
  The specification, landing, baseline and receipt arrive as four independent arguments. A landing
  that belongs to the receipt's git repository has its outcome recorded under the specification's
  row in that register; a landing that does not raises rather than records. So the run, row,
  landing, work shape, mutability, declared scope, base commit, ambient root and changed-paths
  baseline must all agree with the receipt before anything else is read. Otherwise a
  receipt issued for judgment work verified under a mechanical shape, which skips the depth gate
  entirely, and an out-of-scope write verified under a widened scope. `runtime`, `integration_mode`
  and `destination` are also compared, but as consistency fields rather than deciding inputs:
  evaluation reads them from the receipt, never from the supplied arguments, so a mismatch is a
  muddled caller rather than a substitution. `write_scope` is sealed and deliberately **not**
  compared — it is a pure function of inputs that are each compared individually, so a comparison
  against it could never be the check that catches anything.
- **The repository is derived, not supplied.** It is the work location the receipt binds —
  where git runs, where artifacts settle, where retirement archives — not the address of the
  live register. The live register is addressed by `run_id`. A caller who could name a
  second repository could still bind a landing in one tree to a receipt sealed for another;
  that is why issuance derives the work location from the landing and compares it to the
  recorded run root. The per-run secret does not cover this: it is named for the run alone
  and lives outside every repository, so it is shared by `run_id` on this host. R12 is
  one checkout: a second checkout cannot write the register. The secret is still shared,
  which is why it cannot stand in for a work-location check.
  Comparing a supplied root against the receipt was not enough, because the receipt's copy was made
  from that same supplied value at issue time — that catches a caller who changes it in between and
  cannot catch one that was wrong to begin with. So `issue_receipt` derives it from
  `landing.ambient_root`, refuses a landing that fails git identity or containment, and compares
  the derived store to the run root recorded at launch — a value whose provenance is not the
  landing. `evaluate_completion`, `settle_artifact` and `settlement_record` take it from the
  sealed receipt; none of the four accepts it as an argument. Git identity and containment are
  two properties: a nested repository shares ancestry and not identity; a sibling worktree
  shares identity and not ancestry. The live register is addressed by run id, not by working
  tree. Evaluation raises rather than records when the landing does not belong in the receipt's
  store.
  A landing that does not name its repository is refused rather than defaulted to its working
  directory. `read_receipt` is
  the one function that still takes a repository, because it is handed one with a row id and has no
  receipt yet — it checks the sealed root against the register it read, which is what stops an
  authentic verifier dispatch copied from another checkout of the same run from satisfying the
  depth gate here.
- The changed-paths baseline is bound by digest, because it is the one deciding input with no label:
  a baseline is repository state at an instant, and the same landing has different valid snapshots
  before and after a write, so binding the landing says nothing about when the snapshot was taken.
  Without it, an out-of-scope write verified against a baseline taken after the write. The snapshot
  is still produced once by the readiness path and passed in, rather than re-taken at issue, because
  two producers of one snapshot is the shape that hid a defect in the previous round.
- The predicate runs in its own process group, and the group is killed and waited out before the
  evidence is re-observed — on every exit path, success included. Waiting for the direct process
  only established that *that* process finished: a descendant outlived it, was reparented away, and
  rewrote the artifact after the snapshot that certified it, leaving a recorded pass whose durable
  digest did not match the file. A group that will not drain is `predicate_descendants`, a refusal.
  Group membership is the whole of that claim: a descendant that leaves the group with its own
  `setsid` is not reached by the kill, and `references/predicates.md` enumerates every actor the
  control does and does not cover.
- A `reaped` row keeps its terminal phase whichever way a later verdict goes. Demotion on a failing
  re-evaluation already worked; a *passing* re-evaluation wrote `verified` over `reaped`, and needed
  no forgery to do it — catch-up re-evaluates run-bound artifacts on startup and settlement replays
  cleanly, so a closed tab returned as a live verified child.
- The durable records the register holds are authenticated. The live file sits outside every
  landing, so a sandboxed child cannot rewrite it by address. Claude and Muse have no
  workspace-write flag, so the dispatch receipt and settlement record each carry a keyed
  digest under a per-run orchestrator secret held outside every landing. A digest that
  does not match this run's key authenticates against nothing and is refused. A
  same-account child that can read the key can produce a matching digest; the seal does
  not establish authorship against that residual. An added field is a mismatch rather
  than an ignored key, and a secret directory inside the repository is refused outright.
- Evaluation is safe to re-run for one dispatch. Settlement is recorded and replayed rather than
  re-attempted, which is what makes the restart path and judgment work reachable at all: the rename
  is one-shot, so without a record a second evaluation of a correct child fails as though it had
  written its destination directly.
- Predicates are a typed, closed schema: a fixed argument vector with a bounded timeout and output
  cap. Shell text, an `argv` string, a shell program, an inline-source flag, an unknown key, and an
  out-of-range limit are all rejected rather than clamped or ignored. The check runs inline in the
  orchestrator's process tree; a non-zero exit, a hang, an unlaunchable program, and output past
  the cap are each a failure and never a pass, with output streamed so an unbounded predicate is
  killed while still writing rather than buffered.
- A predicate cannot be weakened by the child it certifies. Its resolved import closure — not only
  its entry-point path — must lie outside everything the child may write, and a digest over that
  closure's contents is captured before dispatch and re-checked before evaluation, so a change to
  any statically known dependency fails even when that file sits outside the child's declared
  scope. The closure includes every parent package initializer along a dotted import, because Python
  executes those before the leaf module. The analysis is bounded and fails closed, and every route
  to other code it does *not* follow — dynamic import, `sys.path` insertion, installed distributions,
  native extensions' own imports, data files, non-Python entry points — is enumerated member by
  member in `references/predicates.md`.
- Settlement is performed rather than inferred, because a file on disk does not record whether it
  arrived by rename or by direct write. The child writes only an in-flight sibling of its
  destination; the orchestrator requires the destination to be byte-for-byte its pre-dispatch state
  and then renames the in-flight file into place itself. The predicate therefore reads only a
  renamed path. A directly written artifact, a missing deliverable, and an in-flight symlink are
  each refused with a real observation.
- Run binding is established before the child runs and stored in the register, never read from a
  file beside the artifact. An artifact from another run, another child, or another attempt is
  rejected, and the failure names the binding it does carry.
- Every child's deliverable lands in a directory that is exclusively its own and required to be
  invisible to the repository boundary. That is asked as the stronger question than "matched by an
  ignore rule": a tracked path stays visible to the boundary whatever the ignore rules say, so an
  artifact tree someone force-added is refused at dispatch with an actionable message rather than
  failing every later child on a control firing on the orchestrator's own rename. A read-only child's declared scope is a read scope, not a repository
  write allowlist. Concurrent read-only children with disjoint scopes therefore both complete
  cleanly, which they previously did not, while a read-only child that does write into the shared
  checkout still fails.
- The completion evaluator is held to the same boundary it enforces. Three surfaces are snapshotted
  immediately before the predicate runs and compared after it: the landing, the ambient checkout,
  and the artifact directory itself. The third is not redundant — that directory is required to be
  invisible to Git, so a predicate that rewrote the settled artifact after its digest was taken was
  previously a clean pass with a recorded digest that no longer matched the file. Any
  predicate-authored change fails as a predicate defect rather than being attributed to the child.
- Integration to the recorded destination is verified before reaping is possible — a `branch` tip
  that has not advanced and a `path` whose content has not changed both block verification, while
  `none` states that read-only work integrates nowhere instead of silently skipping the check.
- Judgment-shaped work, classified through fleet-core's authoritative work-shape vocabulary
  including its role-tier aliases, cannot reach `verified` on mechanical coverage alone. A depth
  sample records verifier identity, the digest binding it to this artifact, sampled claims, evidence
  locations, and dispositions from a closed set, and all of it is persisted to the register so a
  child that was genuinely sampled and one whose sample certified nothing are not the same green row.
  The named verifier must be a dispatch this orchestrator issued: an authenticated receipt for the
  verifier row, sealed under this repository, whose run matches and whose sealed runtime matches the
  sample's vendor, plus a phase that is one of the phases past launch and a matching recorded model.
  A register row alone is something a child can write. **What that establishes is that a verifier was
  dispatched in this repository, for this run, with this vendor — not that it ran.** The phase and
  model are register columns, not sealed fields, so moving a receipt-bearing verifier's phase from
  `planned` to `working` presents a session that never read anything; the phase check refuses the
  honest never-started case and not a planted one. It asks for membership in `launched`, `ready`,
  `working`, `verified`, `reaped` rather than refusing `planned` and `launching` by name, because a
  refusal written as exclusions accepts every value nobody thought of, including ones that are not
  phases at all. Sealing it needs post-launch evidence that lives in other units, and it is the same
  defect as the accepted residual on a child's own `phase` column, against a different column of the
  same untrusted store. A sample from the child
  itself, one recorded against another artifact, one with no claims, any unsupported claim, and a
  sample with no supported claim at all each block verification. Malformed external depth data is
  recorded as a closed failure rather than raised, because a control that raises instead of recording
  leaves the register showing a working child with no verdict.
- `references/predicates.md` states the completion contract, including for every control what it
  does **not** establish — notably that settlement does not prove how the child produced its
  in-flight file, that closure analysis does not follow dynamic imports, and that a depth sample
  cannot prove the verifier was blind.

### Changed

- Every child is launched with its runtime's ordinary workspace-write posture, mutating or not.
  A read-only flag forbade the artifact every child is required to write, and no supported CLI
  accepts a repository-relative path allowlist, so it never contained a read-only child — it only
  made its dispatch impossible to satisfy. That posture contains writes *outside* the workspace and
  nothing inside it; the boundary check is post-hoc, partial, repository-visible change detection
  that fails a child's completion rather than preventing its write, and a read-only child's
  repository write allowlist is empty.
- `GitLanding` answers two further boundary questions it already owned: whether a revision exists,
  and whether a path is genuinely invisible to the boundary — ignored *and* untracked. The scope
  helpers it shares with completion are now part of its public surface.
- A child's default environment command is `uv sync --locked --extra dev`, matching how this
  repository's CI provisions. A bare `uv sync` leaves a fresh worktree with no pytest, ruff or mypy,
  which is the set of programs a predicate is most likely to be, and that field exists precisely
  because a worktree cannot otherwise run its predicate at all.

### Not in this release

- Planning and vendor routing, admission control, spend and concurrency bounds, hang detection,
  mirror behavior, and the `/orchestrate` command.

## [0.3.0] - 2026-08-13

### Added

- Launch children through the `agent` wrapper's control-only path after validating its dry-run
  working directory and Herdr workspace. Launch intent and a run-bound task label are durable
  before the side effect, interrupted launches recover by discovering that label, and executable
  adapter tests pin every Herdr command to the default session and the installed argument grammar.
- Resolve model and effort through fleet-core's runtime adapter. Qwen's in-session effort command
  is sent after launch and accepted only after its own acknowledgement is observed; a timeout or
  disabled-thinking acknowledgement records a distinct not-ready source.
- Classify readiness through a nonce-bound `pane.output_matched` interaction whose complete
  sentinel never appears in echoed dispatch input. Trust prompts are surfaced before dispatch,
  dry-run routing mismatches fail before launch, and silent or continuously chatty panes remain
  bounded by the readiness deadline.
- Repair the subscriber's inert cross-counter revision guard. A captured live output-match event
  proves protocol 19 reports `read.revision=0`; the event envelope is now schema-validated through
  the production decoder instead of being discarded as stale.
- Provision mutating children in branch worktrees with an explicit environment-setup step; keep
  read-only children in the ambient checkout. Every child records a launch commit. Isolated child
  changes are compared with the current upstream merge base after merges or rebases, and any
  attributed ambient-checkout change by a mutating child violates the landing boundary regardless
  of its relative path. Shared-checkout violations state that authorship is not established, and the
  Git repository must contain a commit so committed-change observation cannot silently disable.
  Repository-visible changes are checked independently of predicate success; Git-ignored paths are
  documented as outside this control.
- Record reaping before closing a Herdr tab and distinguish a recorded reap from an unexplained
  disappearance.

### Not in this release

- Predicate implementations, the integration gate that authorizes live reaping, spend and
  concurrency admission, hang detection, mirror behavior, and the `/orchestrate` command.

## [0.2.2] - 2026-08-13

### Fixed

- Reject output-match subscriptions that cannot produce a complete substring sentinel instead of
  starting a subscriber that can only discard their events. Multiple valid sentinel interactions
  for the same pane remain independently matchable.
- Report catch-up failures without closing an accepted event stream, and count every accepted
  subscription toward reconnect limits even when its catch-up fails.
- Record how each lifecycle state was learned, including explicit inference labels for a missing
  snapshot pane and a closed tab.
- Avoid register locking for an empty catch-up batch and avoid waking for registered events that
  make no register change.
- Exercise schema-valid pane and agent payloads through the response parser and catch-up consumer.

## [0.2.1] - 2026-08-13

### Fixed

- Unwrap `session.snapshot` from Herdr's real `result.snapshot` response shape, now validated
  end-to-end against the committed success-response schema through a Unix-socket test.
- Resolve `tab_closed` through registered `tab_id` values, and record pane/tab terminal events as
  `exited` before waking the orchestrator.
- Fail fast when the subscriber's first socket connection cannot open; its register row now records
  `exited` and the command returns non-zero instead of retrying forever as `working`.
- Compare sentinel purpose and nonce as well as run and child identity, so an earlier dispatch or a
  readiness marker cannot satisfy a later completion interaction.
- Batch reconnect catch-up updates into one register rewrite and reset once-only diagnostics at
  each accepted connection.
- Clarify that the three subscription-event broadcasts remain dotted even though the 26 general
  broadcast events are underscored.

## [0.2.0] - 2026-08-13

### Added

- A strict protocol 19 event client for `~/.config/herdr/herdr.sock`. It emits dotted
  `events.subscribe` request types, rejects underscored broadcast names and malformed entries, and
  verifies the `subscription_started` acknowledgement before dispatching events.
- A single-purpose tracked subscriber process that holds the socket across turns and wakes the
  orchestrator pane through `agent.prompt`.
- Startup and reconnect catch-up through `session.snapshot`. It records `expected_state` versus
  `observed_state` disagreement and checks run-bound `artifact_path` presence without adding
  predicate wiring before predicate evaluation exists.
- `dispatch_revision_baseline`, the optional register column holding the pane revision sampled at
  dispatch. Run-and-child sentinels are honoured only at a later revision, preventing stale
  scrollback from satisfying a new interaction.
- A schema fixture captured from the installed herdr binary plus real Unix-socket tests for stream
  closure, reconnect, missed child exit recovery, and the remaining event-client error cases.

### Not in this release

- Session launching, readiness or reap transitions, predicate evaluation, routing, mirror
  behaviour, spend gating, hang detection, and the `/orchestrate` command.

## [0.1.0] - 2026-08-13

### Added

Initial scaffold (U2 of `docs/plans/2026-08-12-orchestrate-plugin-plan.md`). This ships the
plugin shape and the register only — the state model for a herdr-driven multi-vendor run, plus
the Claude<->Codex handoff seam (R12). Nothing else in the plan ships yet.

- `scripts/register.py`: a flat, global, `run_id`-keyed JSON register at
  `.orchestrate/register.json`, with atomic durable writes (temp sibling file, `fsync`, then
  `os.replace` — matching `run_ledger.py` and `manifest_store.py` elsewhere in this repository),
  an exclusive advisory lock around read-modify-write cycles so concurrent writers never lose
  each other's row, and a schema-version gate that halts with a durable receipt at
  `.orchestrate/halt-receipt.json` rather than mutating the register on an unsupported version
  (C3). Columns are grouped Identity / Substrate / Work / Lifecycle / Time / Accounting,
  documented in the module docstring.
- **Forward compatibility (C4) at both levels.** A key written by one runtime and unknown to the
  other survives a write by the other, whether it sits **inside a child row** or **at the
  document root**. Both matter to the handoff: rows are merged rather than replaced, and the
  loader preserves the document it read instead of rebuilding a known envelope, on both the
  upsert and the retire path. Genuinely optional columns stay absent rather than being seeded, so
  "unknown key" remains distinguishable from "known but unset" across the seam.
- **Retirement is idempotent.** Retiring a run moves its rows to
  `.orchestrate/runs/<run-id>/register-final.json` and leaves other runs untouched; retiring the
  same run again returns the existing archive rather than overwriting it. The durable copy is
  written before the live register is rewritten, so an interrupted retirement duplicates rows
  rather than losing them — and re-running it, which is the documented recovery, is safe.
- `skills/orchestrate/SKILL.md`: documents the register contract for later units to build against.
- `plugin.json` manifest and `README.md`.

### Not in this release

- The subscriber, `events.subscribe` client, session launching, predicate evaluation, spend
  gating, hang detection, routing, or the `/orchestrate` command itself. Those are later units
  (U3-U10) of the same plan.
