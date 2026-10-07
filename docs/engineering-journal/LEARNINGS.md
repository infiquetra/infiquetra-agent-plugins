# Learnings - infiquetra-agent-plugins

## 2026-10-07

### Blocking a parent directory in Claude's sandbox and allowing paths back works; each toolchain still needs checking

**Evidence.** Issue #189. Live runs on 2026-10-06 and 2026-10-07 through the targeted reviewer's `claude -p` recipe on Claude Code 2.1.292 with Haiku, using only canary files and variables made for the run. `launcher.py reviewer-probe --vendor claude --model haiku` now repeats the checks, and passed all thirteen with the change in place.

**Mechanism.**
- Home blocking:
  - `denyRead: ["~"]` made every home canary unreadable, including one beside the scratch copy.
  - `allowRead` re-opened the copy and the packet inside it.
  - Under the merged #187 settings, canaries in `~`, `~/.config`, `~/.local/share`, `~/.cache` and `~/.local/bin` were all readable.
- Toolchain:
  - A binary under the blocked home still runs, but cannot read its own files, so an interpreter installed under home would fail to load its standard library.
  - Git exits 128 when it cannot read its global configuration, even for `git --version`; `GIT_CONFIG_GLOBAL=/dev/null` fixes it.
  - `git init` in the copy fails under both the old and the new settings.
  - A uv-managed Python 3.12 under home ran a real test with only its `bin` and `lib` allowed back.
  - With nothing allowed back, the shell silently fell through to the next `python3` on `PATH` (a Homebrew 3.14), so a missing allow-back can change the interpreter rather than fail.
  - A symlink in the allowed copy, committed or made at run time, could not read a blocked home canary: the sandbox checks the target.
- Environment:
  - Denying 155 names through `credentials.envVars` left Python tests and git working.
  - The commands still saw variables the sandbox itself sets, such as its network-proxy settings and `SANDBOX_RUNTIME`, which are outside the launch environment.
  - Claude's shell snapshot exported only `PATH`.
- Claude's Read tool, which is not a sandboxed command:
  - With the operator's user settings it read a home canary.
  - With `--setting-sources project` (measurement only) it was denied. Which user setting grants the read is not isolated.
- Scrubbing:
  - Fleet-core's high-entropy rule also matches long CamelCase identifiers, so the scrubber can over-scrub such a name in proof. This is the safe direction, and is accepted.
  - That rule leaves `/` out of its alphabet so paths survive, which let a base64 secret containing `/` (an AWS secret access key, a key body without its header) pass in short runs. A second pass scrubs a run of 40 or more that includes `/` when it mixes upper case, lower case and digits.

**Generalizable rule.** Confine by blocking the parent and allowing back named paths, then run a real test of each toolchain under the block before trusting it.

### The sweep points at code and leaves the answer for a later card

**Evidence.** Issue #156. `docs/plans/2026-10-06-issue-156-plan.md`. `plugins/fleet-core/scripts/fleet_commons/jev_sweep.py` returns a where-to-look item with no `answer`. `plugins/saga/scripts/sweep_pieces.py` reads the head blob with `git show` and runs `ctags --options=NONE`.

**Mechanism.** `review_records` requires `answer` on a where-to-look record. This card leaves it off because card C8 writes the finding or the cleared reason. The changed file is untrusted, so Ctags sees a `0o600` copy in a `0o700` directory and is invoked with `--options=NONE`, not the worktree and not the repository's Ctags config.

**Generalizable rule.** A record that a later card completes stays invalid until that card writes the missing field, and an untrusted blob is parsed from a private copy with the tool's own config turned off.

## 2026-10-06

### A gap on one side of a comparison is an empty set

**Evidence.** Issue #151 repair. `plugins/saga/scripts/review_tools.py` `_base_and_head` treats a base `ToolGap` as no findings and still scans head. `_identity` and the adapter loop turn `FormulaError` into exit 2. Tests: `test_a_base_npm_gap_still_scans_a_lockfile_added_at_head`, `test_an_unknown_tool_level_or_lens_is_a_refusal`.

**Mechanism.** osv-scanner declines an npm-only tree. That decline used to return before the head worktree existed, so a lockfile the change added was never scanned and the run reported only `known-gap`. The same boundary let an unknown tool level raise `FormulaError` past the refusal handler, which the command line reports as exit 1.

**Generalizable rule.** A missing side of a base-against-head comparison is an empty set of findings, and a documented refusal has to be the exception type the process boundary already catches.
### A sandbox's defaults are not its guarantees

**Evidence.** Issue #158. Probes run on 2026-10-06 while planning and building the targeted reviewer: `claude -p` on Claude Code 2.1.292, with Haiku, under the settings in `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py` (`reviewer_claude_settings`), and `codex sandbox` from codex-cli 0.160.1 in `workspace-write` with no model. `launcher.py reviewer-probe --vendor claude` now repeats the Claude probe, judging each denial from the command's own exit codes and the filesystem.

**Mechanism.** Under `--permission-mode dontAsk`, Bash was denied until an allow rule named it, even with `autoAllowBashIfSandboxed`. The sandbox sets `TMPDIR` to its own per-user directory under `/tmp`, which stays writable until a `denyWrite` names the root; `CLAUDE_CODE_TMPDIR` does not move it, and Python's `tempfile` then falls back to the working directory. Eleven variables with "token" in their names reached a sandboxed command until `sandbox.credentials.envVars` denied them. Codex's `workspace-write` sandbox read a file outside its workspace.

**Generalizable rule.** Before relying on a sandbox, probe each denial you need from outside it, and judge by what the command did, never by what the model says it did.

### In a Claude permission rule, one leading slash is not an absolute path

**Evidence.** Issue #158's code review (a P2 on `reviewer_claude_settings` in `plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`) asked for the packet rule `Read(//<packet>/**)` to lose a slash. Live runs on 2026-10-06, Claude Code 2.1.292 with Haiku, `--permission-mode dontAsk` and the reviewer's settings: a deny rule `Read(//<dir>/**)` stopped the Read tool reading a file in that directory, and `Read(/<dir>/**)` did not. With no allow rule for the directory at all, the Read tool still read the file. Paths in `sandbox.filesystem.denyRead`, spelled with `~` or absolute, were denied to both the Read tool and sandboxed Bash. After a session that wrote, edited and ran a test, the only thing Claude left under `.claude/` in its working directory was an empty `.cc-writes/` directory.

**Mechanism.** In a Read or Edit permission rule, `//path` is absolute, `~/path` is under the home directory and `/path` is relative to the settings file. `Path.resolve()` already starts with `/`, so `f"Read(/{path}/**)"` is the absolute form, and dropping the slash makes a rule that matches nothing. Under `dontAsk`, reads outside the working directory are not gated by allow rules, so the deny lists carry the confinement.

**Generalizable rule.** Check a permission rule's spelling with a deny rule and a live run. Deny rules show whether a path matches; allow rules can pass because nothing was gated.

### Herdr names a Muse session `maki`

**Evidence.** On 6 October 2026 two agent-launcher launches of Muse Code 1.4.3 for issue #147 stopped
with "herdr reports agent 'maki', requested 'muse'". `herdr agent explain` showed the `maki` manifest's
`prompt_box_idle` rule (`^❯ `) matching the pane. The launcher's identity check
(`plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py`, `verify_unit_identity`) compared
Herdr's kind to the vendor name exactly.

**Mechanism.** Muse and maki are the same agent; Herdr's detection reports it as `maki`. An exact
comparison treats that as a different agent and closes the session before the prompt.

**Generalizable rule.** Compare Herdr's agent kind to a vendor through an alias table, never by exact
string, and keep the table to names the operator has confirmed are one agent.

### A pane wraps each line of a table the engine laid out for the whole terminal

**Evidence.** Issue #175. `plugins/saga/com.infiquetra.claude/mods/plan-sections.ts` rewrites a table wider than the pane before `Markdown` sees it, and `plan-viewer.tsx` passes `e.props.bodyColumns`. The pull request that lands this change is the other half of the evidence; this build does not open one.

**Mechanism.** The engine lays out Markdown tables in a pane for the terminal's width, and the pane then wraps each line. In a docked pane, `e.viewport.columns` is the transcript column. Only `e.props.bodyColumns` is the pane's width.

**Generalizable rule.** Size what a pane draws to `e.props.bodyColumns`, and check what a pane paints, not just its tree, because the test kit cannot see paint.

### A one-dash delimiter is a table the engine draws

**Evidence.** Issue #175, from the live check of the docked pane. `DELIMITER_CELL` in `plugins/saga/com.infiquetra.claude/mods/plan-sections.ts`. The pull request that lands this change is the other half of the evidence; this build does not open one.

**Mechanism.** GitHub and the engine treat a delimiter cell as optional colons around one or more dashes. Requiring three dashes left a wide table written with a one-dash delimiter undetected, so the pane still wrapped its grid lines.

**Generalizable rule.** Match the delimiter the engine draws: one or more dashes, with optional colons on either side.

## 2026-10-05

### A shared short-name import cache silently runs one plugin's code as another's

**Evidence.** PR #174 (issue #111): 18 saga/orchestrate tier-judgment tests failed on CI while
every suite passed alone. Mission-control's `_fleet_commons` inserted its `_bundled` directory at
`sys.path[0]` and imported by short name; orchestrate's record test then cached
mission-control's `staffing.py` under `sys.modules["staffing"]`, and saga's consults ran against
a bundle without `jev_verbs` — failing open to "not-consulted" with no error. The fix loads by
path under a unique name (the `_load_bundled` pattern already in the same file) and completes
the bundle with `jev_verbs`; `tests/test_fleet_bundle.py` pins both.

**Mechanism.** `sys.path` order plus short-name imports make module identity depend on who ran
first in the process. The failure is silent twice over: the wrong copy is behavior-identical
until the one missing sibling is needed, and the consult fails open by design, so the symptom
lands far downstream as missing keys and absent files.

**Generalizable rule.** In a shared process, load bundled modules by path under a unique name —
never `sys.path.insert` plus a short import — and bundle every sibling the bundled code can
reach, not just the entry points.

### An append-only evidence log needs a retirement marker, not just writers

**Evidence.** Issue #111: `issue prepare` recorded the handoff source's file path as the card's
Objective and as the operator's chosen Objective in the verdict log. The cleanup could not rewrite
history, so `jev_log.record_invalidation` appends an `invalidation` marker and `jev_eval` drops
invalidated verdicts from scoring. Without the marker, the old path labels would have conflicted
with every future real label under the shared `mission-control/issue-prepare:objective` decision
id — the harness drops a twice-labeled id — and the objective judgment could never have been
scored again.

**Mechanism.** An append-only log accumulates corrupt entries alongside good ones, and a scorer
that cannot tell them apart either scores the corruption or discards the whole series. A marker
record naming the corrupt entry by hash lets the writer retire evidence with the same
append-only primitive, and lets the scorer report the exclusion instead of silently changing
what it measures.

**Generalizable rule.** When the evidence is append-only, ship the retirement marker with the
first writer: every recorded series eventually contains an entry that must stop counting.

## 2026-10-04

### Claude Code cannot change a marketplace's source in place

**Evidence.** The 2026-10-04 switch of this machine's `infiquetra-agent-plugins` marketplace from
the local checkout to GitHub, and the installer change that followed (`registration_is_catalog` in
`scripts/install_client.py`). Claude Code 2.1.289 offers `claude plugin marketplace add` and
`remove` and nothing that edits a source. The operator changed the entry by hand in both
`extraKnownMarketplaces` in `~/.claude/settings.json` and `~/.claude/plugins/known_marketplaces.json`.
After that, `claude plugin marketplace update infiquetra-agent-plugins` cloned from GitHub, and
`claude plugin update` kept each plugin's previous version folder for sessions still running.

**Mechanism.** Removing a marketplace uninstalls the plugins installed from it, so remove-then-add
is not a retarget; it is an uninstall and a reinstall. The registration is stored twice, and Claude
Code reads both, so editing one file leaves the other to restore or contradict it.

**Generalizable rule.** To retarget a Claude Code marketplace without losing its plugins, edit both
registration files together, then run `marketplace update` and `plugin update`.

### A count read before a wait is not proof that the earlier holder finished

**Evidence.** Issues #139 and #140, filed at #99's review cycle limit. `run_combined` in
`plugins/saga/scripts/build_loop.py` took its pass number once, before `--lease-wait`, and
`left_by_earlier_pass_of` in `plugins/saga/scripts/environment_lease.py` let a holder with a lower
number on the same host be replaced. A concurrent invocation that gave up and recorded a
could-not-execute pass bumped the count while the holder was still deploying. The fix removes
replacement entirely and reads the pass number when the lease is won;
`test_a_second_invocation_of_the_same_run_waits_on_a_lease_still_deploying` in
`plugins/saga/tests/test_build_loop.py` drives both invocations through the real command line.

**Mechanism.** The pass count measures how many passes were recorded by anyone, not whether the
lease holder recorded its own. Any writer to the record can advance it, so an inference from it is
true only while nobody else writes.

**Generalizable rule.** Decide lock ownership from the lock's own identity (its token or nonce),
never from a counter other writers can move.

### Two identical lease commits are one object, so both pushes "win"

**Evidence.** Issue #99, review cycle 1. `test_a_concurrent_invocation_of_the_same_pass_waits_on_a_live_lease`
in `plugins/saga/tests/test_environment_lease.py` first failed: two invocations wrote the same
holder within one second, `git commit-tree` produced the same object id for both, and the second
`--force-with-lease=<ref>:` push was accepted as already up to date. `GitRefLeaseBackend._commit`
now adds a random nonce paragraph to the commit message, and `read` parses only the first
paragraph as the holder. The same cycle stopped a second invocation of the same run from taking
a live lease (a holder is replaced only by a later pass on the same host) and stamped the
holder's start time at each acquire attempt, so a lease won after a wait is not reported stale.

**Mechanism.** Git objects are content-addressed. A compare-and-swap create guards against a
different value being there, not the same value, so identical content from two writers never
conflicts.

**Generalizable rule.** When a git push is a lock, make every attempt's object unique; equal
content from two contenders is not a conflict to git.

### In an orchestrate run, /plan runs before the rows its checks belong on exist

**Evidence.** Issue #98, review cycle 1. `functional_checks.py write` refused (exit 2) a record
carrying the `orchestrate` block when a plan unit had no row, and `/plan` §5.3a said to stop on
exit 2. But `/plan` runs inside a row `orchestrate start` created, and the `/work` rows arrive
later through `orchestrate expand` (`cmd_expand`), so every orchestrate-driven `/plan` would have
stopped. The writer now writes the rows that exist, lists the rest as `pending` and exits 5;
`/work` re-runs the write before its first build-loop iteration.
`test_write_after_expand_adds_the_rows_that_were_pending` covers the sequence.

**Mechanism.** The writer's refusal assumed the rows came first and the plan second. In the
orchestrate lifecycle the plan decides which rows exist, so the rows always come after it.

**Generalizable rule.** Before making a missing precondition a hard stop, check which step
creates it; if that step runs later, record the work as pending and re-run it at that step.

### A waiver short-circuit dropped the parser's own problems

**Evidence.** Issue #98, review cycle 1. `map_criteria` returned "waived" with no problems for
any waiver, so a plan carrying both a run-level waiver and a check that proved only AC-1 passed
the blocking `/doc-review` mapping check. A waiver now skips the mapping only for a well-formed
plan, and a run-level waiver is ignored beside any check or smoke.

**Mechanism.** The early return for the waiver ran before the problems `parse_plan` had already
found were consulted, so the check reported a state its own input contradicted.

**Generalizable rule.** An exemption short-circuit must still surface validation errors found
before it; exempt the judgement, never the input check.

### A dry run that cannot pick a unit reported the plan's checks as absent

**Evidence.** Issue #98. `build_loop.find_unit` (`plugins/saga/scripts/build_loop.py`) returns
`None` when no `--unit` is named and the record has more than one row, and `read_criterion` then
read an empty row: `build_loop.py --issue <N> --dry-run` printed "none prescribed in the run
record" for a two-unit record whose U1 carried a check. The dry run now lists every row's checks
under its id; `test_the_dry_run_of_a_record_with_several_units_lists_each_unit_s_checks` covers it.

**Mechanism.** `None` meant "no unit was chosen", and the reader treated it as "a unit with nothing
on it". Both print the same absence message, so a choice the caller never made looked like a fact
about the plan.

**Generalizable rule.** When a reader cannot resolve its subject, report that it could not, or
report every candidate; never let "not chosen" fall through to the empty case.
### `json.dumps` output is not shell-safe, so a skill must pipe JSON, not quote it

**Evidence.** Issue #133, a follow-up to #96 (PR #134). `staffing._probabilities_text` in
`plugins/fleet-core/scripts/fleet_commons/staffing.py` copied every probability key of the TypeSafe
answer into the tier judgment's `reason`; `staffing.jev_raise_from` copied that reason into
`jev_raise`; `tier_judgment.py raise` printed it with `json.dumps`; and `/work`'s skill text told the
agent to run `resolve-build-unit-tier --jev-raise '<json>'`. The reason now lists only the
direction choices (`staffing.DIRECTION_CHOICES`), and `--jev-raise -` reads the raise from stdin,
piped from `tier_judgment.py raise`. `test_a_probability_key_outside_the_choices_never_reaches_the_reason`
and `test_work_pipes_a_raise_whose_reason_holds_a_single_quote_into_the_resolver` cover both ends.

**Mechanism.** `json.dumps` escapes double quotes and control characters, never single quotes, so
JSON pasted between single quotes ends at the first `'` inside any string value. The TypeSafe client
passes answer mappings through unchecked, so the keys are vendor-controlled text, and three hops of
"copy the field along" carried that text from a network response to a shell command line.

**Generalizable rule.** Render only the keys your own question defined from a vendor answer, and
hand JSON between commands through stdin or a file, never through a quoted shell argument.

### A run resolved from the branch name is not an active run

**Evidence.** Issue #105, review cycle 1. `run_status.py summary --all-active` filtered only the
other issues by a non-empty `next_step`; the issue resolved from the checkout's `issue/N` branch
was always listed first. A checkout still on `issue/412` after the run closed (its record's
`next_step` cleared to `""`) kept a band line and the status-line entry `saga #412`. `summary` in
`plugins/saga/scripts/run_status.py` now drops that row when its record exists and its `next_step`
is empty; `test_all_active_leaves_out_a_closed_run_on_the_resolved_branch` covers it.

**Mechanism.** `next_step_context.resolve_issue` answers "which run would this checkout belong to",
not "is that run still going". A branch outlives its run, so the resolver keeps naming a closed run.
Only the record's `next_step` says whether it is active.

**Generalizable rule.** Apply the active filter to every row a display lists, including the one it
resolved from the checkout; resolving an issue never implies the run is open.

### A mod's own `$.command.run` never reaches its own command hook; a button press does

**Evidence.** Issue #105. The review findings pane's header (`plugins/saga/com.infiquetra.claude/mods/review-pane.tsx`,
from issue #108) said the run status band would open it with `$.command.run({ command:
'review-view' })`. Under `claude plugin test` on Claude Code 2.1.289 that call, made from a
Button's `onPress`, failed with "no implementation for command.run" even though saga registers a
`command.run` hook for `review-view`; from a `tool.call` hook it is refused outright ("it would wait
on the turn this hook is holding"). A probe plugin with one command hook and one button reproduced
both. The band's Plan and Review buttons now carry the keys `band-plan-<issue>` and
`band-review-<issue>`, and `plan-viewer.tsx` and `review-pane.tsx` each answer a `ui.press` for
their key with the same `openPlanView` / `openReviewView` function their slash command uses.

**Mechanism.** The engine runs a plugin's `$` call through the same hook chain with the calling
plugin's hooks skipped, so a plugin's call to its own command falls straight to what is beneath the
plugins. A `ui.press` is raised by the engine for the person's press, so every plugin's hook sees
it, and the module that owns a pane answers before the Button's own `onPress` would run.

**Generalizable rule.** To trigger one mod's behaviour from another mod in the same plugin, hook an
engine-raised event (`ui.press` on a known element key) in the owning module; never route through
`$.command.run` or another call to the plugin's own hooks.
### A staffing block's `source: operator` does not mean the operator wrote every row

**Evidence.** Issue #106, `plugins/saga/scripts/role_agent_types.py` `staffing_rows`. Review found
that the script read every row as the operator's answer whenever the block's `source` was
`operator`. Admission's per-role merge (`admission.py` `_merge_overrides`) sets that source on the
whole block but marks only the named roles with `operator_override: true`. An unmarked row then
reached the staffing resolver as an operator answer, which outranks everything, so its repository
overlay and its recorded Jev raise were dropped. The rule now lives once, in
`run_record.operator_answered_roles`, read by both the script and admission's staffing table;
`test_a_merged_operator_answer_marks_only_the_overridden_rows` and
`test_the_real_resolver_carries_a_recorded_raise_overlay_and_operator_rows_through` in
`plugins/saga/tests/test_role_agent_types.py` pin it.

**Mechanism.** The record carries two operator-answer shapes under one block source: a whole map
(no row marked) and a per-role merge (only the named rows marked). A reader that checks only the
block source cannot tell them apart.

**Generalizable rule.** When two readers must agree about whose value a record row is, put the
rule in the record's own module and have both call it, rather than letting each re-derive it.
### A judgment that recurs every run needs the run's identity in its decision id

**Evidence.** Before issue #96, `staffing.py` logged tier verdicts as `staffing/tier-suggest:<key>`,
where the key was a role or work-shape name. `jev_eval.py` joins answers to labels on
`decision_id`, skips a repeated id, and drops any id that carries more than one distinct label as
a conflict. The tier judgment now logs `staffing/tier-direction:<repo>#<issue>:role:<role>` and
`...:unit:<id>` (`plugins/saga/scripts/tier_judgment.py`, `decision_prefix`).

**Mechanism.** Thirty runs of the `worker` role produce thirty verdicts with one id. The harness
scores the first and skips the rest, and once two runs label it differently it drops the id
entirely. The "about thirty labeled verdicts" gate in house rule 10 could never be reached.

**Generalizable rule.** When a judgment is asked once per run about a recurring subject, put the
run's identity (repository and issue) in its decision id, and keep the subject as the suffix.

### A writer that does not own a shared list must not add entries to it

**Evidence.** Issue #96's first version of `tier_judgment.py plan` recorded each plan unit's
judgment on the run record's `units` rows and created a row holding only `id` when none matched.
Review reproduced the failure: on a record with an `orchestrate` block, orchestrate's `Run.load`
raised `TypeError: Unit.__init__() missing 3 required positional arguments: 'name', 'vendor', and
'task'`, and `Run.save` writes back only the rows its run holds, so a loadable row would still have
lost its judgment. The fix keeps the judgments in a top-level `tier_judgments` map keyed by plan
unit id (`plugins/saga/scripts/tier_judgment.py`, `PLAN_KEY`), which every writer preserves as an
unknown top-level field; `plugins/orchestrate/tests/test_orchestrate_record.py` now loads and saves
such a record through orchestrate.

**Mechanism.** Adding a key to a row someone else owns is safe, because the round-trip rule
carries it forward. Adding a row is not: row membership is the owner's decision, and the owner's
loader assumes the fields it creates rows with. Listing the new keys as "documented foreign row
keys" silenced the notice but hid that the row itself was foreign.

**Generalizable rule.** Annotate a shared list's existing entries if you must, but put state about
things the owner has not created yet under a key of your own.

### A command that is on by default makes its tests call out unless the test package switches it off

**Evidence.** Issue #96 made `admission.py`'s command line run the tier judgment by default. The
first run of `plugins/saga/tests/test_admission.py` afterwards made one live TypeSafe request from
`test_the_table_reads_the_overlay_admission_staffs_from_repo_root`, which drives `main()` with the
real bundled staffing component, because the operator's shell carried `TYPESAFE_API_KEY`. Only
fixture data was sent, and the dry run logged no verdict. The fix is the autouse fixture
`_no_live_tier_judgment` in `plugins/saga/tests/conftest.py`, which sets
`INFIQUETRA_TYPESAFE_TIERING=off` and removes the key, plus library defaults
(`admit(judge_tiers=False)`) that make no request unless asked.

**Mechanism.** Tests that inject a fake `ask` are safe, but a test that exercises the real command
line reaches the real client, and the client reads the key from the environment. An interactive
shell that exports credentials turns any such test into a live call.

**Generalizable rule.** When a network-backed behaviour becomes on by default, add an autouse
fixture that switches it off for the whole test package in the same change, and let the tests
that need it on pass an explicit switch and a fake client.

### A card filed from a pull request's follow-ups can be closed by that same pull request

**Evidence.** Issue #117 was filed on 2026-10-04 from issue #95's implementer follow-ups. It said four
saga writers (`admission.py`, `review_result.py`, `qa_strategies.py`, `build_loop.py`) still
replaced the run record without the lock. By the time #117 was picked up, the merged pull request
for #95 (#120, commit 245e3b0) had already moved all four onto `run_record.update` or `file_lock`,
added a concurrency test for each, and documented them in `plugins/saga/references/run-record.md`.
What #117 still added was enforcement: `test_no_saga_script_replaces_a_run_record_outside_the_lock`
and `test_save_takes_no_lock_so_a_caller_holding_it_can_save` in
`plugins/saga/tests/test_run_record.py`.

**Mechanism.** A follow-up describes the branch as it stood when the implementer wrote it, not as it
merged, because review rounds keep changing the branch after the follow-up is written. Also, a grep
for `run_record.save` misses the aliases saga already uses (`import run_record as _m` behind
`_run_record()` in `merge_turn.py`), so the guard parses each script and resolves those names.

**Generalizable rule.** Before building a card filed from follow-ups, diff its claims against
`origin/main`; when the code has already moved, turn the card's goal into a guard test that fails on
a regression.
### Read a Claude Code session's cost per request, not per turn

**Evidence.** Issue #107, `plugins/saga/com.infiquetra.claude/mods/usage-capture.ts`. Claude Code
2.1.289's declarations: `TurnUsage` (what `turn.complete` carries) is the four `ModelUsage` counts
plus the answering model, with no effort and no cache-write TTL split. `TurnStepInput` carries
`effort` (a level, a number, or absent) and `agentId` (absent on the main thread), and
`TurnStepResult.usage` is that one request's usage, null when no response arrived.
`usage-capture.test.ts` drives `turn.step` on the main thread and in a subagent loop and checks
the `usage add` argv each produces.

**Mechanism.** The effort is a property of the request, so the run record's entry identity
(session, role, vendor, model, effort) can only be filled where the request is made. A turn can
also mix models (a fallback) and a subagent's turns complete inside the parent's. Neither turn
events nor request events split cache writes by TTL; only the Agent tool's own result record
does, so the mod records them at the one-hour rate as an upper bound. The mod resolves its unit
once at session start through `run_status.py unit-for`, because orchestrate's unit branches are
`orch/<run>-<unit>`, not `issue/N`, so the issue cannot be read from the branch.

**Generalizable rule.** Capture cost at the event that names every attribute the ledger keys on,
and record an unsplittable count at its most expensive rate rather than guess a split.
### A display that re-asks a resolver must hand it the same inputs the real call got

**Evidence.** The third review of issue #93 found that admission's staffing table in
`plugins/saga/scripts/admission.py` (`_default_tier` and `_raise_outcome`) called the staffing
resolver with no root, while `fill_defaults` staffed with `root=repo_root` from `--repo-root`.
Fleet-core's `overlay_path` treats a missing root as the working directory, so a run from another
directory showed an applied Jev raise the checkout's overlay had outranked.
`test_the_table_reads_the_overlay_admission_staffs_from_repo_root` in
`plugins/saga/tests/test_admission.py` pins the fix.

**Mechanism.** The earlier repair moved the table onto the real resolver, but an optional
parameter with a silent default (the working directory) let the two calls read different overlays.
The table tests used a fake resolver that ignored `root`, so nothing could see the gap.

**Generalizable rule.** When a display re-derives what a real call decided, thread every input of
that call through, and test with the real component and a working directory that differs.

### Preserving unknown keys on load is not enough when the save writes back the copy it loaded

**Evidence.** Issue #113. Orchestrate's `read_unit`
(`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`) built each `Unit` from its
declared fields only, and `Run.save` rewrote the whole `units` array from those units, so a run
record row carrying `build_loop` and `usage` came back with neither after one `Run.load` and
`Run.save`. The run-record contract already promised a row's unknown keys are left alone, and the
top level was already safe through `run_record`'s `extra`. The new tests in
`plugins/orchestrate/tests/test_orchestrate_record.py` (class `TestKeysOrchestrateDoesNotOwn`)
fail on the old driver and pass on the fixed one.

**Mechanism.** Two separate losses. Dropping keys at read time loses what was on disk at load.
Writing back the loaded copy, even a key-preserving one, loses what another writer (the build
loop, a unit session adding `usage`) put on disk between the load and the save, because a run's
coordinator loads once and saves many times during a long `wait`. Only a re-read at save time,
under a lock every writer takes, closes the second gap: the save then takes every key it does not
own from the fresh copy and only its own keys from memory. The lock protects only writers that
take it, which is why issue #95 moved every saga writer onto it and #113 moved orchestrate's save.
A lock orders writes but does not merge them: `merge_state`, which orchestrate and `merge_turn`
both write, stays last-writer-wins under it. A test that held orchestrate's quiet-key list to
run-record.md by reading every backticked first column in the units section broke once issue #95
added the `usage` entry's field tables there; it now reads only the tables between
`<!-- BEGIN UNIT ROW KEYS -->` markers.

**Generalizable rule.** A whole-document writer that shares its file with other writers must
re-read under a shared lock at save time and merge its owned keys onto that fresh copy; keeping
unknown keys from the load is necessary but not sufficient.
### A Claude Code Markdown element answers presses only on links it drew itself

**Evidence.** The plan viewer pane (issue #104) in
`plugins/saga/com.infiquetra.claude/mods/plan-viewer.tsx`. Claude Code 2.1.289's declarations
(`MarkdownProps` in the build's `claude-code.d.ts`) say a `Markdown` element draws at most 10,000
characters, draws a link whose scheme is not `https:`, `http:` or `file:` as plain text, and raises
`ui.press` for a link only where the surface reports clicks (the fullscreen terminal); the
main-screen terminal opens the link instead. Saga plans cite files as backticked code, which is no
link at all. `plan-viewer.test.tsx` presses both routes on terminal and desktop.

**Mechanism.** `linkifyRefs` in `mods/plan-sections.ts` rewrites each backticked `path:line` into a
`file://` link and names it in `pressableLinks`, so a press quotes the reference into the prompt
instead of opening it. It stops adding links before the page would pass 10,000 characters, which
is why pages are cut at 9,000. The pane also draws one button per reference, because the keyboard
and the main screen never raise a link press.

**Generalizable rule.** A mod that makes text pressable must create the links itself, keep the
page under the element's limit after linking, and offer a button route for surfaces without clicks.
### "Accept all" must apply only the proposals that exist, and validate before it writes

**Evidence.** Review cycle 1 of issue #103 found that the admission pane's Accept all
(`plugins/saga/com.infiquetra.claude/mods/admission-review.tsx`, `submit(true)`) replaced the
operator's picks with `initialSelections` and wrote them to state before checking for lenses left
out with no reason. The fix is `acceptAllSelections`, and the check now runs first. The tests
`Accept all restores every proposal and keeps the operator's answer for a lens with none` and
`Accept all with a lens left out and no reason changes nothing in the pane` in
`admission-review.test.ts` fail against the earlier code.

**Mechanism.** Until issue #110 supplies Jev lens proposals, every undeclared conditional lens
opens as left out with an empty reason. Restoring the opening picks therefore discarded every
reason the operator had typed, and the reason check then refused. Accept all could never succeed
while the lens declaration was pending.

**Generalizable rule.** A bulk "accept" action overwrites only fields that have a proposal, and a
refused action leaves the form exactly as it was.

### A Claude Code mod that waits for a person must wait on `$` calls, never on a bare Promise

**Evidence.** Issue #103's tool `mcp__saga__review_admission`
(`plugins/saga/com.infiquetra.claude/mods/admission-review.tsx`) holds its `tool.call` open
until the operator submits the review pane. On Claude Code 2.1.289,
`the tool outlasts the ten-second hook budget while the operator decides` in
`admission-review.test.ts` waits twelve real seconds before Submit and passes when the hook
loops on `await $.process.run(['sleep', '1'])`. Swapping that one line for
`await new Promise((r) => setTimeout(r, 1000))` fails the same test, and the engine reports
`saga's tool.call hook was skipped: saga: exceeded 10000ms budget`.

**Mechanism.** A hook's budget is 10,000 ms of its own time per dispatch (`HookBudget.ms`). The
clock stops only while a `next(e)` or a `$` call is in flight, and a `$.clock` wait still counts,
so a bare Promise or `$.clock.sleep` spends the budget and the hook is skipped. A `$.process.run`
of `sleep 1` spends almost none. Two related findings from the same work: in the test kit, `key`
on a `Text` is not kept (put the key on a wrapping `Box` to find it), and a `ui.select` of a value
the Select does not list never reaches the chain or `onSelect` and resolves `undefined`.

**Generalizable rule.** Hold a mod's dispatch open with a loop of short `$` calls, capped, and
prove it with a test that waits past ten real seconds.
### A display copy of a rule drifts the moment the rule's real home lands

**Evidence.** Issue #93 built the one staffing resolver but left admission's display copy of the
tier precedence (`_one_step_raise` and `_raise_refusal` in `plugins/saga/scripts/admission.py`).
The copy stepped effort first; the resolver's `_validate_jev_raise` also accepts one model rung.
For the merging worker with a recorded raise to opus/medium, the resolver staffed opus/medium
while the admission table's Why cell said the raise was refused.
`test_the_table_shows_a_model_rung_raise_the_resolver_applied` in
`plugins/saga/tests/test_admission.py` now pins the resolver's answer.

**Mechanism.** The copy's own tests checked the copy, not the resolver, so they stayed green while
the two rules diverged. The repair has the table call `_resolve_one_role` (the call admission
staffs with) and word the decision's `source` and the resolver's refusal message.

**Generalizable rule.** When the change that builds a rule's real home lands, delete every interim
copy in the same change, and test the display against the real component, not a fake of the rule.

### `$.ui.ask` hides a dialog that answered itself, and a plugin gets one unmatched `session.start`

**Evidence.** Issue #109, `plugins/orchestrate/com.infiquetra.claude/mods/launch-approval.tsx`
and its test `a dialog that resolved itself while the operator was away is dismissed, never
approved` in `launch-approval.test.ts` (`claude plugin test plugins/orchestrate`, 2.1.286 and
2.1.289). AskUserQuestion's result carries `afkTimeoutMs` when the dialog resolved itself with the
operator away; `$.ui.ask` resolves to the label alone. Separately, `claude plugin validate --strict`
(2.1.289) refused the first layout, two mod files each hooking `session.start`: `on("session.start")
is registered twice without a matcher`.

**Mechanism.** `$.ui.ask` is a `tool.call` of AskUserQuestion through every hook but the caller's,
then reduced to the chosen label, so the auto-resolution flag never reaches the caller. A second
hook of the same plugin on `tool.call` for AskUserQuestion does see the full result, and answering
`{ deny }` there makes the caller's `$.ui.ask` reject. The validator allows one matcherless hook
per event per plugin, and it refuses `$` passed into a function imported from another file, so
start-time registration has to sit in one file and take plain data from the others.

**Generalizable rule.** Any approval built on `$.ui.ask` needs an AskUserQuestion hook that turns
an auto-resolved answer into a refusal. Put a plugin's one `session.start` in its entry module and
have each mod export its command and tool specs as data. In `claude plugin test`, a `Text`
element's `key` is not reported (find it by `text`), and the test's `$` has no `ui.close`; press
the pane's own Close button instead.

### A Claude Code subagent's effort can only be set by its agent type, and the call's model overrides the type's

**Evidence.** Claude Code 2.1.289, read from the build and its mod declarations while building
issue #106 (`plugins/saga/com.infiquetra.claude/mods/agent-types.ts`). The Agent tool's own
description says each agent type's model, reasoning effort and tool access are set in its
definition, and "the `model` parameter here overrides the definition for this one call". The
plugin agent loader reads `effort:` from a plugin agent file and warns on an invalid value, while it
warns that `permissionMode`, `hooks` and `mcpServers` are ignored for plugin agents. `TurnStepInput`
in `plugin-authoring/types/claude-code.d.ts` carries the request's resolved model id (such as
`claude-opus-5-5`), its effort and the subagent's `agentId`, but no agent type. In the test kit
(`claude plugin test`), a test hook on `session.append` is not reached, and a plugin's
`$.session.append` rejects with "no implementation for session.append".

**Mechanism.** Effort is part of an agent definition, not a dispatch argument, so a role that needs
a resolved effort needs a type of its own, and a dispatch that also passes `model` silently replaces
the type's model. A request names a full model id while a type names an alias, so a comparison has
to match the alias inside the id. The drift check finds the subagent's type through `$.agent.list()`
by `agentId`. The transcript line is written with `$.ui.log`, which draws a notice the model never
reads and which the test kit can stub.

**Generalizable rule.** To run a Claude subagent at a resolved effort, dispatch a registered type and
leave out `model`; check the outcome on `turn.step`, never assume it.
### A test suite that reads live configuration spends the operator's API budget, not CI's

**Evidence.** On 2026-10-04 the GitHub REST budget for the operator's account reached 0 of 5,000
at 03:44 UTC while several agents ran `plugins/mission-control/tests`. A sample after the reset
showed about 70 calls a minute, all `gh api repos/infiquetra/infiquetra-sdlc/contents/config/sdlc-schema.json`,
from a `pytest plugins/mission-control/tests` process. With a logging `gh` stub on the path, one
suite run on main attempted 291 such reads; after the fix it makes none (707 passed, 0 calls).

**Mechanism.** `_resolve_sdlc_schema` in `plugins/mission-control/scripts/sdlc_manager.py` tries
GitHub main first and only then the vendored copy, and every `load_config()` calls it. CI never
noticed: its runner has no `gh` login, so the read fails fast and falls back. On a developer
machine `gh` is logged in, so each test that loads config spends one REST call.

**Generalizable rule.** A suite that passes in CI can still be non-hermetic locally; give every
live read a test seam the suite's conftest turns on, and count calls with a stub to prove it.
### Retiring a machine-rendered body section must keep it in the revision strip list

**Evidence.** Issue #94 removed mission-control's issue-type tier band stamp.
`_strip_trailing_handoff_context` in
`plugins/mission-control/scripts/sdlc_manager.py` strips only trailing headings
listed in `_HANDOFF_CONTEXT_SECTIONS`, and every draft prepared before #94 ends
with the band. With the band dropped from that list,
`test_revision_of_a_pre_94_draft_drops_the_retired_band` in
`plugins/mission-control/tests/test_sdlc_draft_revision.py` fails with two
`### Source context` sections instead of one.

**Mechanism.** The strip loop walks back from the end of the body and stops at
the first heading it does not recognise. One unrecognised trailing section
therefore shields every machine-rendered section above it, and a `--from`
revision carries the stale handoff sections forward next to freshly rendered
ones.

**Generalizable rule.** When a renderer stops emitting a trailing section, keep
its header in the strip list for as long as old drafts can still be revised.
### Landing "only the keys this writer changed" is not lost-update safe without a compare

**Evidence.** Review cycle 2 of issue 95 found `land_merge_keys` in
`plugins/saga/scripts/merge_turn.py` wrote every merge key the turn changed between its unlocked
starting copy and its finished copy onto the record re-read under the lock. `holder()` releases a
stale `merging` row on that unlocked copy, so when the released unit finished its own merge in the
meantime, the landing wrote `ready` over its `merged`.

**Mechanism.** A diff between "before" and "after" tells a writer what it changed, not whether
anyone else changed the same key since "before". Re-reading under the lock protects keys this
writer did not touch; for keys it did touch, the fresh value must still equal "before"
(compare-and-set), or the writer is overwriting a newer value with one derived from a stale copy.
The fix lands a key only on that condition, except on the merged unit's own row, whose git outcome
is the truth.

**Generalizable rule.** A writer that does slow work unlocked and lands a delta later must
compare-and-set each key it lands against the value it started from.

### An open row key set is only open if every whole-row writer carries unknown keys forward

**Evidence.** The 2026-10-04 survey for issue 95 loaded a run record whose unit row carried
`usage` and `build_loop` with orchestrate's `Run.load` and saved it with `Run.save`: both keys were
gone, after a warning that orchestrate "ignores" the unknown key. `read_unit` in
`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py` keeps only the fields its `Unit`
type declares, and `Run.save` rewrites the whole `units` array from that in-memory copy.

**Mechanism.** `plugins/saga/references/run-record.md` says a consumer may add a key to a unit row
and that a key another consumer does not know is left alone. The first half is a promise to
writers of new keys; the second is an obligation on every writer of whole rows, and nothing
enforced it. A writer that reconstructs rows from its own type, or saves a copy it read before
someone else wrote, breaks the contract silently. Issue 113 fixes orchestrate. Issue 95 adds the
record lock and moves every saga writer onto it, which stops the stale-copy half for saga; the
lock is advisory, so it protects only the writers that take it, and a review of issue 95 found the
first draft had converted two writers while the reference said "every".

**Generalizable rule.** When a shared record promises an open key set, test the promise at every
writer that rewrites whole objects — round-trip a row carrying a key that writer does not own.
### A Claude Code mod can share parsing across files, but never the engine handle `$`
### A Claude Code mod cannot pass `$` across an import, but it can pass a closure over `$.process.run`

**Evidence.** Issue #101. `claude plugin validate` (2.1.289) refused a mod file
that passed `$` to a reader imported from a sibling file: `$ is passed to
"readRunRecord", imported from "./shared.ts": $ is followed only into a
function declared in this same file, never across an import`. The same reader
declared at the top level of the mod's own file validated, and the validator
reported `calls: $.process.run (via readRunRecord)`. In review cycle 2 a probe
copy of saga whose `session.start` hook called the imported
`readRunRecordWith((argv) => $.process.run(argv), $.plugin.root, 7)` passed
`claude plugin validate --strict` on 2.1.286 and 2.1.289 and reported `calls:
$.process.run`: the closure keeps `$` in the
mod's own file, so the validator follows it there. The test kit's `$` has no
`process` noun at all (`undefined is not an object (evaluating
'$.process.run')`), so a test body cannot call `$.process.run` itself. A test
can still drive a mod's hook that does: registering `on('process.run', async
(_$, e) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated:
false, isStderrTruncated: false } }))` stubs the engine's runner, and `e.argv`
is the argv the mod built (a probe plugin passed under `claude plugin test` on
2.1.289, 2026-10-04).

**Mechanism.** The validator lists which engine calls a module makes (the
`calls:` line) by following `$` through the module's source, and, as its own
message says, it follows `$` only into functions declared at the top of the same
file. A function in another file that takes `$` is refused, not followed. A
function in another file that takes a plain runner function is not about `$` at
all; the `$` use it wraps stays in the arrow function the mod writes, which the
validator sees.

**Generalizable rule.** Share guarded logic across mod files by passing it a
closure over the engine call (`(argv) => $.process.run(argv)`), never `$`
itself. Saga's `readRunRecordWith` in `mods/run-record.ts` holds the one
try/catch every mod relies on for its plain fallback; test it with fake
runners, test a mod end to end by stubbing `process.run` with
`on('process.run', ...)`, and pin the script's real exit codes and output with
a Python test (`plugins/saga/tests/test_mod_run_record_contract.py`).
### Preserving unknown keys on load is not enough when the save writes back the copy it loaded

**Evidence.** Issue #113. Orchestrate's `read_unit`
(`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`) built each `Unit` from its
declared fields only, and `Run.save` rewrote the whole `units` array from those units, so a run
record row carrying `build_loop` and `usage` came back with neither after one `Run.load` and
`Run.save`. The run-record contract already promised a row's unknown keys are left alone, and the
top level was already safe through `run_record`'s `extra`. The new tests in
`plugins/orchestrate/tests/test_orchestrate_record.py` (class `TestKeysOrchestrateDoesNotOwn`)
fail on the old driver and pass on the fixed one.

**Mechanism.** Two separate losses. Dropping keys at read time loses what was on disk at load.
Writing back the loaded copy, even a key-preserving one, loses what another writer (the build
loop, a unit session adding `usage`) put on disk between the load and the save, because a run's
coordinator loads once and saves many times during a long `wait`. Only a re-read at save time,
under a lock every writer takes, closes the second gap: the save then takes every key it does not
own from the fresh copy and only its own keys from memory. The lock protects only writers that take
it: saga's build loop, `merge_turn`, `review_result`, `qa_strategies` and `admission` still write a
whole stale copy without it, so they can still erase an orchestrate save until issue #95 (built in
parallel) moves them onto it; issue #117 covers only what #95 leaves. A lock orders writes but does
not merge them: `merge_state`, which orchestrate and `merge_turn` both write, stays
last-writer-wins under it.

**Generalizable rule.** A whole-document writer that shares its file with other writers must
re-read under a shared lock at save time and merge its owned keys onto that fresh copy; keeping
unknown keys from the load is necessary but not sufficient.
### Diagnosing a refusal by retrying without one input blames that input unless the retry changes the answer

**Evidence.** The second review of issue #93 found that `_resolve_one_role` in
`plugins/saga/scripts/admission.py` retried a refused role without its recorded Jev raise and, when
the retry was refused too, reported the first message as "its recorded raise was also refused". For
a Claude-only shape on a codex-pinned worker both calls fail with the same message before any layer
is read, so the error printed it twice and blamed the raise.
`test_admission_does_not_blame_a_raise_that_did_not_cause_the_refusal` and
`test_admission_names_a_refused_raise_beside_the_role_refusal` in
`plugins/saga/tests/test_admission.py` now pin both outcomes.

**Mechanism.** Removing an input and still failing proves only that the input was not sufficient
for the failure; the original error is attributable to it only if it differs from the retry's.

**Generalizable rule.** When you infer a cause by removing an input, name that input only if the
result changed when you removed it.

### A fail-open `except` around a resolver turns the resolver's new refusals into silent omissions

**Evidence.** Review of issue #93 found that `_resolve_staffing` in
`plugins/saga/scripts/admission.py` wrapped `staffing.resolve_role` in `except Exception: continue`.
The change made the resolver refuse a malformed recorded Jev raise and a Claude-only work shape on a
vendor-pinned role, and at admission both refusals made the role disappear from
`staffing_models_and_efforts` with no message. A recorded `{"model": "fable"}` raise dropped the
`worker` entirely. `test_admission_keeps_the_worker_and_shows_a_refused_raise` and
`test_admission_fails_loud_when_staffing_refuses_a_role` in `plugins/saga/tests/test_admission.py`
now pin the repaired behaviour.

**Mechanism.** The broad `except` was written for one known case, the lens reviewer that cannot
resolve without a lens. Every refusal added later to the callee inherited that skip, because a
`continue` cannot tell "this role needs a lens" from "this input is wrong".

**Generalizable rule.** When a callee gains a new refusal, read every caller's `except` around it,
and keep a fail-open skip narrowed to the one case it was written for.

### A caller that enters a layered resolver below its top layer drops every layer above it, silently

**Evidence.** Before issue #93, `resolve_build_unit_tier` in `plugins/saga/scripts/lifecycle_state.py`
called `tier_resolver.resolve(None, shape)` directly, while admission called
`staffing.resolve_role`, which reads the `.saga/tier-defaults.json` overlay first. With an overlay
naming `sonnet/high` for a shape, admission reported `sonnet/high` and `/work` launched at the
registry default, with no error from either. `test_admission_plan_and_work_agree_with_an_overlay`
in `plugins/saga/tests/test_admission.py` now pins the agreement. The same audit found that the
`/plan` tier table's marker had named `test_skill_registry_sync` as its guard since the table was
generated, and no test of that name existed until this change added it.

**Mechanism.** `tier_resolver.resolve` is a complete, valid-looking answer on its own: it returns a
palette member and never fails for a known shape. Nothing about its output says that the overlay
and raise layers above it were skipped, so a caller reaching it directly gets a plausible tier
that is wrong only when one of those layers is present.

**Generalizable rule.** Call the top of a layered resolver, never a layer inside it, and when a
document names the test that guards it, check that the test exists.

## 2026-09-22

### Two merge pipelines cannot run side by side under this repository's branch protection

**Evidence.** PR #83 was rebased onto main at 8a5040f and its checks passed while
PR #82 was merging ahead of it. Its squash merge was then refused with "the head
branch is not up to date with the base branch" (2026-09-22, about 19:55 local),
and `gh pr view` reported `mergeStateStatus: BEHIND`. Re-running the pipeline on
its own landed the same commit as d710c29.

**Mechanism.** The protection on main requires the head branch to contain the
current base commit. Every merge moves the base, so any second pipeline that
finished its rebase before the first merge landed is behind by construction,
whatever files it touches. Regenerated `marketplace.json` conflicts were never
the only reason merges had to be serial.

**Generalizable rule.** Run `merge_pipeline.sh` for one pull request at a time,
even when the pull requests touch disjoint files; the branch protection, not
the diff, sets the constraint.

### Grok's marketplace removal leaves its plugins registered, and a bare-name uninstall picks a random twin

**Evidence.** After cutover Grok's registry held two entries per name for
deploy, mission-control, orchestrate and saga: one under
`~/.grok/marketplace-cache/...` tagged `infiquetra-plugins`, one under this
repository's `plugins/` directory. `grok plugin marketplace remove
infiquetra-plugins` (Grok 1.0.40) dropped the source from `marketplace list`
and left all four cache-backed entries in `plugin list`. `grok plugin details
<name>` and `grok plugin uninstall <name>` resolved the same bare name to
different entries across calls, and the id that `plugin list` prints is not
accepted as a name. The entries were cleaned by observation: uninstall once,
read the registry to see which copy went, uninstall again only when the catalog
copy went, then re-place from the catalog with `install_client.py --client grok
--execute`. Final state on 2026-09-22: zero cache-backed entries, fourteen
catalog entries.

**Mechanism.** Grok keys registry entries by a generated id but resolves
commands by plugin name over an unordered collection, so with two same-named
entries the target is whichever the collection yields first. Marketplace
removal edits only the source list.

**Generalizable rule.** Never let a legacy and a catalog placement coexist under
one Grok plugin name. If they do, remove by observation (uninstall, read back,
repeat) and re-place from the catalog; never predict which twin a bare name
resolves to. `install_client.py --uninstall-legacy` refuses the ambiguous case
for this reason (PR #85).

### A file-level allowlist on a scanner goes stale silently

**Evidence.** The first revision of PR #86 allowlisted six files for the new
machine-path scanner. By review time PR #84 had scrubbed three of them, and the
allowlist still skipped those files whole, so a new real path in them would
never have been reported. The merged version has no allowlist: the three
remaining hits were documentation placeholder users (`example`, `op`, `test`),
now listed in `INERT_HOME_DIRECTORY_USERS` in `scripts/check_repo.py`, and the
committed tree reports zero hits.

**Mechanism.** Exempting a path exempts every future content of that path;
exempting a value exempts only that value.

**Generalizable rule.** Scanners exempt values, not files. If a file must be
exempt, the check has to fail when the exemption no longer matches anything.

### A Grok Herdr session can exhaust its weekly limit mid-unit with its work apparently finished

**Evidence.** The Grok session running the ten-client assessment showed "Task
completed" for its background runs and then presented "You hit your weekly
limit" (status bar: "Weekly limit left: 0%") with nothing committed and no pull
request; Herdr reported the agent `blocked`. The unit was re-run from scratch by
a Claude subagent (PR #87) instead of salvaging the untracked output the stopped
session had left under `/private/tmp`.

**Mechanism.** Background tasks inside the session keep running on local
compute, but the agent needs a model turn to act on their results, and that
turn is what the limit refuses.

**Generalizable rule.** Check the weekly allowance before assigning a long Grok
unit. When a Grok session goes `blocked` on a limit dialog, treat its
uncommitted output as unverifiable and re-run the unit under a session that can
still take turns.

### OpenCode 2.0.13 dropped the subcommand the assessment harness reads its inventory from

**Evidence.** Every package assessed on 2026-09-22 records the same OpenCode
result. Placement — `cp -R <package>/skills/<unit> <client-home>/.agents/skills/`
— exits 0, and both the discovery and the load stage then exit 1, because both
read the client through `opencode debug skill` and the client answers `Unknown
subcommand "skill" for "opencode debug"`. The same command is recorded at exit 0
in `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md`, against
OpenCode 1.18.25; this machine now runs 2.0.13. The invocation stage still runs,
so the rows read "engaged with the package and could not fully consume it".

**Mechanism.** The harness's OpenCode plan reads that client's state through one
of the client's own subcommands, chosen because it returns each skill's fully
parsed body and so proves load rather than inferring it from a directory
listing. The subcommand no longer exists. Placement is a copy into the
auto-loaded external skill directory and is unaffected, so the unit is placed
and then not observed. Nothing about any package changed between the two runs.

**Generalizable rule.** A compatibility harness that reads a client's state
through one of that client's subcommands inherits that subcommand's lifetime.
When a client's result changes across runs and no package byte moved, check the
client's version before the package's bytes — and record what the client
actually said, because "this subcommand is unknown" and "the package did not
load" are the same exit status.

### The ten-client harness refuses two package shapes its own descriptor format allows

**Evidence.** The 2026-09-22 run covered every package with a port descriptor.
Two never produced a record. `python3 scripts/assess_clients.py --package
house-style --execute --python "$(command -v python3)" --workspace <fresh dir>`
exits 1 with `ERROR: house-style: declares no assessment.entrypoints, so there
is nothing to invoke. A package with no executable entrypoint says so by naming
'entrypoints' in assessment.declared_none, and then carries no invocation
stage` — and `ports/house-style.json` already names `entrypoints` in
`declared_none`, which is the exemption that message asks for. A descriptor
written for `fleet-core`, which ships no skill unit, reached the sixth client
and raised `IndexError: tuple index out of range` at
`scripts/assess_clients.py:1167`, on `recorded = redact(" ".join(argvs[0]),
values)`; the plan printer fails the same way at `scripts/assess_clients.py:1794`.
Both outcomes are recorded in the run's pull request; neither package has a
matrix, and the harness was not edited to produce one.

**Mechanism.** Two separate gaps between what a descriptor may declare and what
the harness reads. `entrypoint_paths` raises whenever `assessment.entrypoints`
is empty, and its own message describes a behaviour — carrying no invocation
stage — that `assess` does not implement, so naming the field in `declared_none`
exempts the package from the validator and not from the harness. Separately,
`stage_argvs` returns an empty tuple for a per-skill stage when
`assessment.skill_units` is empty, and both `run_stage` and `describe_plan` then
index `argvs[0]` without checking; the four skill-scoped clients each carry a
per-skill placement stage, so a package with no skill unit crashes at the first
of them.

**Generalizable rule.** A declaration that a field is deliberately empty has to
be honoured by the code that reads the field, not only by the validator that
accepts it. And a function that fans one stage out over a declared list must
handle the empty list explicitly, because "there is nothing to run here" and
"the run crashed" are different results and only one of them can be recorded.

### Grok's invocation stage is blocked for every package, and the id it needs is one stage away

**Evidence.** Every package assessed on 2026-09-22 records Grok with placement,
discovery, and load executed at exit 0, and invocation blocked with `The command
still names <plugin-id>, which no earlier stage resolved.` Reading the run's
private transcript for one package: Grok's placement stage printed 192
characters and no install id; its discovery and load stages both printed the id
the invocation path needs. The harness's capture rule for that client,
`scripts/assess_clients.py:373`, reads the id out of the placement stage only.

**Mechanism.** Grok installs a local plugin under a generated id and the
invocation path is `<client-home>/.grok/installed-plugins/<plugin-id>/…`. The
harness captures that id from the output of the stage declared with `capture=`,
which is placement. This client no longer prints the id when it installs; it
prints it when it lists and when it shows details. With the placeholder
unresolved, `run_stage` blocks the stage rather than running a literal
`<plugin-id>` path — which is the right call, because that path does not exist
and the non-zero status would be charged to the package.

**Generalizable rule.** When a harness reads one client's generated identifier
out of one stage, that is a coupling to where the client chose to print it, and
the client can move it without changing anything the harness would notice. A
blocked row that repeats across every package is a property of the harness or
the client, not of the packages; check whether the value exists in a later
stage's output before reading the row as a package limit.

### A re-run of `install_client.py` failed on a package the previous run already placed

**Evidence.** `scripts/install_client.py --client qwen --execute` on a real
cutover failed with `Extension "agent-launcher" is already installed. Please
uninstall it first.`, and the failure aborted every later package for that
client. `plan_qwen`, `plan_grok`, and `plan_claude` built their install
command for every requested package with no check of whether that package was
already placed; `plan_agy` read back an existing placement's source but only
to decide when to refuse replacing someone else's copy, so a placement that
already matched the catalog still reached the install command a second time.
`tests/test_install_client.py` covered every client's `--check` reader and
every client's fresh-install path, but nothing called the install path twice
against a home a first run had already touched, so the gap had no failing
test to surface it.

**Mechanism.** Every placement command in this family (`qwen extensions
install`, `grok plugin install`, `claude plugin install`, `agy plugin
install`, `cursor-agent plugin marketplace add`) refuses to repeat a
placement it already made; a multi-package, multi-client run has no
transaction, so a single command failure partway through left every later
package unplaced and undiagnosed until the operator reran the exact command
that failed.

**Generalizable rule.** A script that wraps someone else's non-idempotent
CLI has to make the *wrapper* idempotent: read back that CLI's own state with
the same reader `--check` uses before building the placement command, and
skip with a message when the state already matches. Do this once, in the
planning function that builds each client's actions, not once per command
call site — `plan_agy`'s existing readback shows how easy it is to compute
the right answer and use it for the wrong decision.

---

### The Claude CLI validator takes a directory for `commands` but a list of files for `agents`

**Evidence.** `claude plugin install agy@infiquetra-agent-plugins` failed on
2026-09-22 with `invalid manifest file ... agents: Invalid input`; `claude
plugin validate` on a copy of the package passed once `agents` listed
`./com.infiquetra.claude/agents/<file>.md` entries, and passed with
`commands` left as a directory string. Seven imported packages carried the
directory form.

**Mechanism.** The CLI's manifest schema types `agents` as an array of file
paths; the import generator had written every relocated surface the same way
(a `./`-relative directory), and nothing in the repository ran the CLI's own
validator before the first real install.

**Generalizable rule.** A generated vendor manifest is checked with that
vendor's validator before it ships (`tests/test_claude_plugin_packaging.py`
now runs `claude plugin validate` per package when the CLI is present), and a
field's accepted form is read from the validator, not inferred from a
sibling field.

### Twelve branches that each regenerate one shared file serialize their merges

**Evidence.** Every package import regenerated `.claude-plugin/marketplace.json`
and appended to `requirements-plugin-tests.txt`; after the first merge every
other open pull request was `CONFLICTING` (PRs #64–#78, 2026-09-22), and the
GitHub merge refused each until it was rebased and the file regenerated.

**Mechanism.** A generated file is only conflict-free if it is regenerated
after the rebase, and GitHub's squash merge does not regenerate anything. So
the merge order is a queue: rebase, regenerate, re-run CI, merge, next.

**Generalizable rule.** When a fan-out touches one generated file, run the
merges through a serial pipeline that regenerates on rebase
(`rebase_pr.sh` / `merge_pipeline.sh` in this run), and do not start the next
rebase until the previous merge landed.

### A plugin resolver that walks the repository tree makes two imports depend on each other at CI

**Evidence.** PR #76 (mission-control) failed only on CI with
`plugin-resolution: could not resolve a 'saga' root`; PR #72 (saga) failed
only on CI with the same error for `mission-control`. Both passed locally.

**Mechanism.** Fleet Core's `plugin_resolution` ladder tries the environment
override, then a repository walk-up for `plugins/<name>` with required marker
files, then `~/.claude/plugins/installed_plugins.json`, then a cache-sibling
scan. Locally the third rung finds the installed Claude plugin; on CI only the
walk-up can succeed, and it needs the sibling's *new* layout (the root Claude
manifest) to be on the same branch.

**Generalizable rule.** A test that resolves a sibling package should point
the resolver at a fixture root, not at whatever the live tree or the machine
happens to carry; until it does, imports that resolve each other merge as one.

### A Herdr task name that already exists splits a pane inside that tab, and closing the tab closes both

**Evidence.** Relaunching `agents --task mg-cdx` while a session of that name
existed produced `mg-cdx-2` in the same tab (`w8A:tH`); `herdr tab close` on
it ended both sessions, and the Codex packaging unit had to be relaunched.

**Mechanism.** The `agents` wrapper reuses an existing tab label by splitting
a pane; tab-level close is not pane-level close.

**Generalizable rule.** Read `herdr agent list` before launching a name, and
close a finished unit by its own tab only after confirming no other agent
shares it.

### Two packages that bundle the same Fleet Core module cannot both import it by bare name in one process

**Evidence.** On the combined branch (PR #78) the full plugin suite failed one
mission-control test with `partially initialized module 'intent_envelope' has
no attribute 'SCHEMA_VERSION'`; each package's suite passed alone. Saga ships
`scripts/intent_envelope.py`, a CLI wrapper with the same bare name as the
Fleet Core module both packages bundle, and mission-control's
`_load_intent_envelope` did `import intent_envelope` after a `sys.path`
insert.

**Mechanism.** A bare import answers with whatever `sys.modules` already holds
under that name, so the first suite to import a module named
`intent_envelope` decides what every later bare import in the process gets.

**Generalizable rule.** A package loads its bundled Fleet Core modules by
path under a package-unique module name (mission-control's `_load_bundled`,
the same idea as Fleet Core's own `_load_sibling`), never by bare name; a
test that needs to patch such a module patches the object the loader returns.

### Codex accepts a Claude manifest beside its own, and marketplace add does not install a plugin

**Author.** Grok (custody-move unit U5b, branch `mg/codex-pkg`)

**Evidence.** Codex CLI 0.155.1 (`codex plugin marketplace add --help`,
`codex plugin add --help`). A temporary `CODEX_HOME` (not `~/.codex`) was
given a checkout that contained both `.claude-plugin/marketplace.json` and
`.agents/plugins/marketplace.json`, and a plugin directory that contained
both `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json`.
`codex plugin marketplace add <checkout> --json` exited 0 and wrote
`[marketplaces.infiquetra-agent-plugins]` with `source_type = "local"`.
`codex plugin list --available --json` then listed the plugin, including one
with no `skills` path and one with no `interface.defaultPrompt`.
`codex plugin add sample@infiquetra-agent-plugins --json` wrote
`[plugins."sample@infiquetra-agent-plugins"]` with `enabled = true`. The
installed cache copy of `google-cloud-developer` also contains both
`.claude-plugin/` and `.codex-plugin/`. The sha256 of
`~/.codex/config.toml` was the same before and after. The narrative is
`docs/engineering-journal/narratives/2026-09-22-codex-packaging.md`.

**Mechanism.** The dedicated repository's validator refuses `.claude-plugin`
inside a Codex plugin. That check is not what the CLI runs. The CLI selects
`.codex-plugin/plugin.json` when it is present and still loads the
marketplace when `.claude-plugin/` sits beside it. Marketplace add only
records the source. A plugin stays uninstalled until `plugin add`, which is
also the command that sets `enabled`.

**Generalizable rule.** *A sibling product's validator is not the CLI. Read
the config table the CLI writes, and treat marketplace registration and
plugin enablement as two records.*

**Refs.** `scripts/sync_codex_packaging.py`, `scripts/install_client.py`,
`tests/test_codex_plugin_packaging.py`.

### Package test suites need pytest's importlib import mode once two packages share a test basename

**Evidence.** CI run 35764030847 on PR #66 (redis-channel import): pytest
aborted collection with "import file mismatch" because
`plugins/home-lab-ops/tests/test_entrypoint.py` and
`plugins/redis-channel/tests/test_entrypoint.py` share a basename. Locally on
`main` at 7471527, `python3 -m pytest --import-mode=importlib plugins/*/tests -q`
collected all 1357 tests with the same two environment-dependent failures as
before.

**Mechanism.** Pytest's default `prepend` import mode registers each test
module under its bare basename in `sys.modules`, so two files named
`test_entrypoint.py` in different directories without `__init__.py` collide,
and the second one is refused at collection. The importlib mode imports each
file under a unique synthetic name and never touches `sys.path`.

**Generalizable rule.** A catalog whose packages each own a `tests/`
directory runs pytest with `--import-mode=importlib`; a test that needs a
sibling helper imports it by path, not by bare module name.
### A marketplace name is not a source, and a manifest this tree does not have is not a placement

**Author.** Grok (custody-move unit U5, branch `mg/installer`)

**Evidence.** `scripts/install_client.py` and
`docs/engineering-journal/narratives/2026-09-22-install-clients.md`.
On this machine Agy's marketplace named `infiquetra-plugins` records
`infiquetra/infiquetra-antigravity-plugins`, while Claude's marketplace of the
same name records `https://github.com/infiquetra/infiquetra-claude-plugins.git`.
Codex's working marketplaces (the OpenAI bundled marketplace and
`infiquetra-codex-plugins`) are `.agents/plugins/marketplace.json` plus a
`.codex-plugin/plugin.json` in each plugin directory. The sentence that the
directory must not also contain `.claude-plugin` was the dedicated
repository's validator, and it is corrected by the later learning "Codex
accepts a Claude manifest beside its own". The three compatibility matrices
record `codex plugin marketplace add <package>` refusing the package root
when that root had no Codex manifest.

**Mechanism.** Removing or generating by the short name would either delete
the Antigravity install or treat a marketplace name as a git URL. The
installer treats a recorded git URL or directory path as the source. The
Codex half of this entry, printing `unsupported` instead of writing a
manifest, is superseded by the later learning in this dated section.

**Generalizable rule.** *A placement is whatever the client's own record
says the bytes came from. A shared marketplace name, and a manifest format
the tree does not contain, are not that record.*

**Refs.** `scripts/install_client.py`, `tests/test_install_client.py`,
`docs/runbooks/install-clients.md`.

### A guard that fires on your own change is the procedure, not an obstacle

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Evidence.** `MutationProofBindingTest` in `tests/test_site_profile.py` records
a SHA-256 digest for each of five graded source files and fails when one is
edited without its mutation campaign being re-run. Unit U1 was required by its
own brief to change three of those five: `scripts/port_config.py` (schema
version 4), `scripts/check_compatibility_matrix.py` (version-bound evidence),
and `scripts/check_repo.py` (the marketplace staleness check). The brief also
said not to run a new mutation proof. Those two instructions cannot both be
satisfied, and the three ways out are not equal: editing the recorded digests
would make the evidence document claim a campaign exercised bytes it never saw,
which is the exact defect the binding test was added to prevent after a cycle-7
review found a proof recording a digest matching no committed state. Reported as
a blocker, the answer was to run the campaign scoped to the changed files. It
graded 33 anchors -- 21 re-covering cycle 16's anchors in those three files, 12
for the guards U1 added -- and is published as cycle 17.

**Mechanism.** An instruction to skip ceremony is written before anyone knows
which guards the work will trip. When a guard fires on the change that is
supposed to be routine, that is the guard doing its job: it has found a place
where the work is not routine. The cost of the procedure is bounded and known;
the cost of suppressing it is an evidence artifact that is confidently wrong,
which is worse than no evidence because it will be believed. The instruction to
avoid ceremony governs the cases where nothing fires.

**Generalizable rule.** *When a guard fires on your own change, run its
procedure or stop and ask; never edit the guard's record to match your bytes.* A
blanket "skip the ceremony" instruction cannot anticipate which guard will fire,
so a fired guard is new information the instruction did not account for.

**Refs.** `tests/test_site_profile.py` (`MutationProofBindingTest`),
`docs/evidence/2026-09-22-cycle17-mutation-proof-custody-move-tooling.txt`,
`docs/evidence/2026-08-25-cycle16-mutation-proof-portable-copies.txt` (the
superseded predecessor and the cycle-7 identification failure it records).

### A generated build declaration has to follow the client, not the package root

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Evidence.** `scripts/import_vendor_package.py` generates each package's
`fleet-bundle.json` from the `fleet_commons_shim.load("<module>")` calls it
finds in the upstream bytes. The schema documents the destination default as
`scripts/_bundled/<name>.py`, package-relative, which reads as "the bundle goes
at the package root". Taking that default would have been wrong for the first
package tried. The rewriting rule
(`sync_vendor_source.bundled_module_transform`) emits
`sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))` -- the
bundle directory *beside the rewritten file*, not beside the package. UniFi's
two clients sit at `skills/unifi-network/scripts/` and
`skills/unifi-protect/scripts/`, so the generator has to derive
`skills/unifi-network/scripts/_bundled/retry_backoff.py` and its sibling. It
does, and the generated declaration reproduces the committed
`plugins/unifi/fleet-bundle.json` destinations exactly, which is how this was
confirmed rather than assumed.

**Mechanism.** The schema's default is a convenience for the common case where
the client is at `scripts/`, and it is stated package-relative because every
path in that file is. The rewritten import is resolved *relative to the file
doing the importing*, so the two agree only when the client happens to sit at
the package root's `scripts/`. A generator that read the documented default as
the rule would declare a bundle the bundler duly writes at the package root,
where the client never looks. Nothing would fail at build time: the declaration
is satisfied, the file exists, and the package fails at first invocation with
`ModuleNotFoundError` -- the same shape as the defect AGENTS.md records against
the UniFi clients shipping an import nothing generated.

**Generalizable rule.** *When generating a declaration that a second tool will
act on, derive it from what the runtime resolution actually does, and check the
output against an artifact a human already got right.* A documented default
describes a common case; the rule is in the code that resolves the path.

**Refs.** `scripts/import_vendor_package.py` (`bundle_destination`),
`scripts/sync_vendor_source.py` (`bundled_module_transform`),
`schemas/fleet-bundle.schema.json` (the `destinations` default),
`plugins/unifi/fleet-bundle.json` (the artifact the generator was checked
against), `tests/test_import_vendor_package.py`
(`test_the_destination_follows_the_client_rather_than_the_package_root`).

### The field a plan says to add can already exist, and the real change is elsewhere

**Author.** Claude for Jeff Cox (custody-move unit U1, branch `mg/tooling`)

**Evidence.** The approved run plan's rule 4 and the unit brief both say a
compatibility matrix should record "the package `version` it assessed (add the
field to the schema)", and that existing live records should have it backfilled
"with the version they assessed". `schemas/compatibility-matrix.schema.json`
already carried `$.package.version`, already listed it in the `package` object's
`required` array, and all three live records
(`docs/evidence/2026-08-22-unifi-*`, `2026-08-27-agent-launcher-*`,
`2026-08-30-mission-control-*`) already stated the correct version. More than
that, `check_package_binding` already *failed* on a version mismatch. Adding the
field would have produced a duplicate, and backfilling would have rewritten
values that were already right.

**Mechanism.** The rule the decision wanted -- evidence binds to a released
version rather than to every tree -- is a change of *consequence*, not of
schema. Both halves of the desired behaviour were half-present: the version
already failed, and the fingerprint also failed. The work was demoting the
fingerprint to a non-failing report, not adding a field. A plan describes an
intent, and an intent expressed as "add X" can be satisfied by machinery that
predates it.

**Generalizable rule.** *Read the artifact before implementing the instruction
that describes it.* When a plan says to add a field, check whether it is there;
the gap between what a plan assumes and what the code holds is usually where
the actual change is.

**Refs.** `schemas/compatibility-matrix.schema.json` (the `package` object's
`required` array), `scripts/check_compatibility_matrix.py`
(`split_binding_problems`, `check_package_binding`),
`docs/plans/2026-09-22-custody-move-and-claude-plugins-retirement-plan.md`
(rule 4).

### A "current" matrix document and an assessment-free notice were indistinguishable to the checker

**Evidence.** `docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md`,
`2026-09-22-unifi-authored-cut.md`, and `2026-09-22-mission-control-compatibility-notice.md`
each explained that no ten-client run exists yet for the package's current
version, and each carried `<!-- matrix-status: current -->`. `python3
scripts/check_compatibility_matrix.py` printed `Compatibility matrix
validation passed.` regardless, because `is_matrix_document` -- the function
that decides which documents the run even looks at -- requires a
`$.package`/`$.clients` record and silently excludes anything without one.
Three documents that perform no assessment were marked current and nothing
ever checked that claim.

**Mechanism.** `matrix_documents()` filters by record *shape*, not by the
`matrix-status` directive, so a document could say "current" in its directive
and "no run happened" in its prose at the same time with no code path that
would ever notice the contradiction. Adding `STATUS_NOTICE` fixes the state
space (a document can now say "I am not an assessment" explicitly), but that
alone does not close the gap -- a fourth document could still be typo'd or
left with no directive at all (which defaults to `current`) and pass the same
way. The actual fix is `check_notice_discipline`, a second scan that is not
shape-filtered: it walks every evidence document and fails any whose resolved
status is `current` but whose record fails the shape test that
`is_matrix_document` uses to decide "is this even a matrix."

**Generalizable rule.** When a validator selects *which* documents to check
by testing their shape, a document that fails the shape test is invisible to
every rule that follows -- including a rule about what the document is
allowed to claim about itself. Closing that gap needs a second pass over the
documents the selector *rejected*, not just a stricter selector.

**Refs.** `scripts/check_compatibility_matrix.py` (`is_matrix_document`,
`check_notice_discipline`, `STATUS_NOTICE`), `tests/test_check_compatibility_matrix.py`
(`NoticeStatusTest`).

### A file that scans its own directory tree for a pattern can match its own explanatory comment

**Evidence.** `scripts/check_repo.py`'s new `check_machine_specific_paths`
scans `scripts/` (among other directories) for an absolute path under a real
user's home directory. The first version of its own docstring illustrated the
rule with the literal example `/Users/test/`, inside `scripts/check_repo.py`
itself -- which the function then flagged as a violation of the rule it
was defining, failing `python3 scripts/check_repo.py` on a file that had
never shipped a real path.

**Mechanism.** The scanner does not know the difference between a path that
documents the rule and a path that violates it; both are the same bytes on
disk. Any check whose scanned scope includes its own source file has to treat
its own comments and docstrings as untrusted input to itself.

**Generalizable rule.** When writing a pattern-matching validator, grep the
validator's own source (or just read it once with the finished regex in mind)
for anything that would self-trigger before considering the change done --
an illustrative example in a docstring is exactly the kind of text that
reads as a natural violation of the rule it is illustrating. The fix here was
to describe the pattern in prose rather than give a literal matching example.

**Refs.** `scripts/check_repo.py` (`check_machine_specific_paths`,
`MACHINE_SPECIFIC_PATH`).

### A function's default parameter is bound once at import, so patching the module attribute after import does not reach it

**Evidence.** Writing a CLI-level test for `check_compatibility_matrix.py`'s
`main()` calling `check_notice_discipline()` with no arguments, the natural
instinct was to `unittest.mock.patch` the module's `EVIDENCE_DIRECTORY`
constant and point it at a scratch directory. That has no effect on
`check_notice_discipline`, because its signature is
`def check_notice_discipline(directory: Path = EVIDENCE_DIRECTORY)` --
Python evaluates that default once, at function-definition time (module
import), and stores the resulting `Path` object in the function's
`__defaults__`. Reassigning the module-level name afterward changes what the
name refers to, not what the function's already-bound default is.

**Mechanism.** This is ordinary Python default-argument binding, but it is
easy to miss specifically in a validator module that exposes both a
default-parameter function (`check_notice_discipline(directory=...)`) and a
function that re-reads the module global inside its body
(`current_matrix_report`, which does `EVIDENCE_DIRECTORY if root is None else
...` at call time). The two look identical from the call site (`f()`) but
respond completely differently to patching the module attribute.

**Generalizable rule.** To test a function's behavior against a scratch
directory when it defaults to a module-level constant, pass the directory
explicitly rather than patching the module attribute -- and if the code under
test is only reachable with no arguments (as `main()` calling
`check_notice_discipline()` is), the only faithful test writes into (and
removes from, in `finally`) the real default location.

**Refs.** `scripts/check_compatibility_matrix.py` (`check_notice_discipline`,
`current_matrix_report`), `tests/test_check_compatibility_matrix.py`
(`CLIWiringTest`).


## 2026-08-31

### A green local suite is never evidence for a hermetic gate

**Author.** Claude for Jeff Cox (final repair pass of issue #50, branch `orch-agent-plugins-50`)

**Evidence.** The CI `validate` job declares itself the repository's hermetic
baseline that "runs the standard library only". It is not one:
`tests/test_mission_control_rule_audit.py` imports `sync_template_docs` at
module scope, which imports `yaml` at
`plugins/mission-control/scripts/sync_template_docs.py:14`. Measured on a
stdlib-only CPython 3.12.13: this branch reports `Ran 797 tests, FAILED
(errors=1)` with `ModuleNotFoundError: No module named 'yaml'`, losing 43
tests to the aborted module; origin/main reports `Ran 738 tests, FAILED
(errors=1)` with the identical error. So it is pre-existing on main, not a
regression from this run, and it does not break CI today because the GitHub
runner supplies PyYAML — it is a latent contract violation: the job's own
comment promises a stdlib-only baseline it does not have. Cycle 1's F03
repair guarded `import pytest` with `try/except ModuleNotFoundError` plus
`skipTest` in the same file, leaving the transitive yaml path unguarded —
the fix pattern already exists twenty lines away. This pass deliberately
does not fix it: it changes what the baseline covers and belongs in its own
change.

**Generalizable rule.** *A suite that passes locally proves nothing about a
hermetic gate.* A baseline claim must be measured on the interpreter the
baseline promises, and a module-scope transitive import behind a
dependency-free job comment is a contract violation even when every
runner happens to carry the dependency.

**Refs.** `.github/workflows/ci.yml` (the `validate` job's comment),
`tests/test_mission_control_rule_audit.py` (module-scope imports and the F03
pytest guard), `plugins/mission-control/scripts/sync_template_docs.py:14`.

## 2026-08-31

### A refusal message must not depend on a hash seed

**Author.** Claude for Jeff Cox (repair round 3 of issue #50, branch `orch-agent-plugins-50`)

**Evidence.** The marker rule's count-mismatch refusal iterated
`for site_class in expected_classes`, where `expected_classes` was a set —
so the class the message named first was chosen by the interpreter's hash
seed, and two runs of the same refusal could print different messages. The
repair iterates a fixed `SITE_CLASSES` tuple for the comparison while the
set remains only for the membership check.

**Generalizable rule.** *Anything a human or an auditor reads must be
deterministic in the order it prints.* Sets are for membership; iteration
order that reaches an error message, a manifest, or a transcript must come
from a sequence.

**Refs.** `scripts/sync_vendor_source.py` (`SITE_CLASSES`,
`package_root_marker_transform`), `tests/test_sync_vendor_source.py`
(`PackageRootMarkerRuleTests`).

## 2026-08-30

### The carried package suite has three grades, not one: authenticated, unauthenticated, and no-gh

**Author.** Claude for Jeff Cox (integrated code-review repair round, review
finding F01, issue #50, branch `orch-agent-plugins-50`)

**Evidence.** The integrated review controller measured `python3 -m pytest
plugins/mission-control/tests -q` with a recording `gh` shim first on PATH:
180 live invocations — 179 of the infiquetra-sdlc schema-content read and one
campps issue read — across five carried test files. Re-run in this round with
`gh` off PATH on the floor interpreter: `58 failed, 333 passed` — the failures
are `FileNotFoundError` on the `gh` binary in tests whose mocks reach
`sdlc_manager._gh` and expect its typed error contract. With `gh` present but
unauthenticated (the CI runner's state), the same paths degrade to the typed
auth errors and the suite passes with no request reaching GitHub.

**Mechanism.** `_resolve_sdlc_schema` puts the network first in its
"GitHub main → vendored → local" ladder and swallows every exception before
falling back, and the carried tests do not stub it; so an authenticated `gh`
grades the suite against whatever `infiquetra-sdlc` main holds at that
moment, and the U2 four-gate transcript was captured on the authenticated
side. The carried suite is not hermetic in either direction: it cannot be
run without a `gh` binary, and it makes live authenticated calls when it
finds one.

**Generalizable rule.** *A transcript of a carried suite states a claim only
about the machine it ran on.* Record which side of a resolver ladder the run
was on before citing it, and file the ladder inversion upstream — vendored
first, network opt-in — rather than patching the carried bytes; the filing is
tracked in `QUEUED.md`.

**Refs.** `plugins/mission-control/scripts/sdlc_manager.py`
(`_resolve_sdlc_schema`, `_gh`), the five carried test files named in the
review finding F01, `docs/engineering-journal/QUEUED.md` (filing 1).

## 2026-08-25

### `claude plugin update` compares versions, not commits

**Author.** Jeff Cox and Claude (voice stop-command follow-up)

**Context.** Immediately after merging the stop-keybinding fix, updating the
installed plugin so the operator would get it.

**Evidence.** `claude plugin marketplace update` succeeded, then
`claude plugin update voice@infiquetra-agent-plugins` answered "voice is
already at the latest version (0.1.0)" — and the cache still held the previous
content: `com.infiquetra.claude/scripts/install_launcher.py` was absent, the
cached `preflight.py` contained zero occurrences of `command_is_runnable`, and
`installed_plugins.json` recorded `gitCommitSha` `bb6d7c9` while `main` was at
`01fb2a4`.

**Mechanism.** The update check is a version comparison. The marketplace
refresh pulls new *marketplace* metadata, but the plugin is only re-copied when
its declared version differs from the installed one. A fix that changes
behaviour without bumping the version therefore lands on `main`, passes CI, and
never reaches the running plugin — while both commands report success. The
reported "latest version" is true and irrelevant, which is what makes it
expensive: it reads as confirmation.

**Generalizable rule.** A behaviour change to a published package is not
delivered until its version changes; treat the version bump as part of the fix,
not as release ceremony. Where the version is declared in more than one file,
check the copies against each other in the test suite rather than by hand.

### A probe that matches text instead of resolving it reports a false green

**Author.** Jeff Cox and Claude (voice stop-command follow-up, branch
`orch/voice-stop-launcher`)

**Context.** Voice preflight checks an operator-owned Herdr keybinding that
must invoke the package's stop path. The operator caught the defect before
acting on the documented instruction.

**Evidence.** `plugins/voice/scripts/preflight.py` tested
`if KEYBINDING_MARKER in command` — a substring match on `"voice stop"`. The
package README documented exactly that binding, and `command -v voice` returned
nothing: the installed `scripts/voice_cli.py` had no shebang and no executable
bit, and no `voice` existed on `PATH`. Following the documentation would have
produced a green preflight for a key that parsed, ran, and stopped nothing.

**Mechanism.** The probe and the requirement were about different things.
The requirement is *can this stop playback*; the probe asked *does this string
appear*. Those agree only while the documented spelling happens to be
executable, and nothing enforced that. The failure is worse than an absent
probe, because a green line retires the operator's own suspicion — the one
thing that actually caught it here. The same file already knew better:
`probe_executable`, twenty lines below, checked `os.access(path, os.X_OK)`.
The keybinding probe simply never adopted the standard its neighbour used.

**Compounding cause.** No stable path exists to bind to. Claude installs under
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, a version bump
creates a new directory (73 orphaned version directories on this host), and
there is no `current` or `latest` symlink. So the honest command could not be
written down at all until a launcher resolved the install at invocation time
from Claude's own registry, which Claude rewrites on every update.

**Generalizable rule.** A readiness check must resolve the thing it claims is
ready, not pattern-match the text that names it; and when a check reports on
something an operator configures, verify the configured value the way the
runtime will consume it.

### Claude Code runs Stop hooks synchronously — a hook that does real work must detach

**Author.** Jeff Cox and Qwen (voice run, #29/#34)

**Context.** Building the voice plugin's `Stop` hook, which speaks the bound
session's completed response; preflight P2 measured hook timing on this host
while planning the run.

**Evidence.** A blocking 8 s hook delayed turn settle by 8.19 s, while a
detaching hook returned in 0.030 s (run plan, Grounded facts — preflight P2).
Live acceptance re-confirmed the shape: four hook invocations returned in
0.04–0.05 s of wall time while their detached children synthesized (~5–14 s)
and played (~3–30 s) asynchronously afterwards
([`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md),
AE1/AE2/R1).

**Mechanism.** The harness executes `Stop` hooks synchronously as part of
turn settle, so every second a hook works is charged to the user's wait; the
harness-side timeout in the hook descriptor is a backstop against a wedged
hook, not a budget for doing work.

**Generalizable rule.** A hook that must do real work should read its payload
once, decide, hand the work to a fully detached child (its own session, stdin
closed, streams to devnull), and return 0 immediately — treating the harness
timeout as a backstop, never a budget. Anything the child needs travels by
file and argv, never by the hook's still-open streams.

**Refs.** `plugins/voice/com.infiquetra.claude/hooks/stop_hook.py`,
[run plan](../plans/2026-08-25-voice-plugin-implementation-plan.md) KTD2,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md).

### A probe's expected response shape is itself a wire contract — verify it against the live service, not just hermetic fakes

**Author.** Jeff Cox and Qwen (voice run U7 acceptance, #34)

**Context.** The voice plugin's preflight probes were built hermetically
(seams and fakes, as CI hermeticity requires) and merged green; U7 then ran
them against the live Voice Forge deployment and the live Hermes relay.

**Evidence.** The suite was green (243 plugin tests at the final commit) yet
the live preflight failed twice on assumed shapes: Voice Forge v0.3.0
`/health` answers `{"ok": true, "version", "registry_dir", "voices_count",
"backends_available", "backends_loaded"}` — no `status` or `backend` members
the probe required — and Hermes v0.20.4 `/api/profiles` entries carry no
`stt` surface at all, so the probe's `stt.provider == "xai"` assertion could
never resolve. Driving the same services directly succeeded: synthesis
played, and the transcription round trip returned the phrase verbatim with
`provider: xai`
([`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md),
findings F1/F2).

**Mechanism.** A hermetic fake and the probe that consumes it are written
together, so a shared wrong assumption about a remote contract gets confirmed
twice by one source; the suite can only prove the probe agrees with the fake,
never that either agrees with the service.

**Generalizable rule.** When a probe asserts the shape of a remote response,
treat that shape as a wire contract: verify it once against the live
endpoint, and when it cannot be verified live before merge, mark the
assumption in the probe so the first live run is read as a contract check,
not just a connectivity check.

**Refs.** `plugins/voice/scripts/preflight.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md)
findings F1/F2, voice-forge `server.py` `/health`, hermes
`web_routers/profiles.py`.

### A relay's silence mapping and a strict provider guard turn a quiet room into a provider alarm

**Author.** Jeff Cox and Qwen (voice run U7 acceptance, #34)

**Context.** Composing the voice plugin's no-substitution guard (R23: refuse
any transcription resolved by a provider other than the declared one) with
the Hermes relay's own handling of silent recordings.

**Evidence.** For audio with no speech, the live relay answered `{"ok":
true, "transcript": "", "provider": null}` — its `transcribe_recording` maps
silence, `no_speech`, and hallucination-filtered results onto an empty
success and omits `provider` on exactly those paths. The voice guard then
refused with `the relay resolved None, not the expected 'xai'; nothing
substitutes for the declared provider` — observed twice during acceptance.
The same call on audible audio returned `provider: xai` with a verbatim
transcript
([`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md),
finding F3).

**Mechanism.** Two locally-correct contracts compose into a confusing edge:
the relay folds "heard nothing" into an empty success without provider
attribution, while the consumer treats any attribution other than the
expected provider — including none — as substitution. Nothing unsafe happens
(nothing is delivered), but the operator sees a provider alarm for a quiet
room instead of a quiet no-op.

**Generalizable rule.** When consuming a relay that maps empty or silent
results onto success, distinguish "empty result with no attribution" from
"wrong provider" before refusing by name — otherwise silence and
substitution become indistinguishable at the operator surface.

**Refs.** hermes `tools/voice_mode.py` `transcribe_recording`, hermes
`web_server.py` `/api/audio/transcribe`, `plugins/voice/scripts/transcribe.py`,
[`docs/evidence/voice/acceptance.md`](../evidence/voice/acceptance.md)
finding F3.

### An async CLI agent's "done" status is a turn boundary, not completion

**Author.** Jeff Cox and Claude (mission-control migration retrospective,
[#9](https://github.com/infiquetra/infiquetra-agent-plugins/issues/9))

**Context.** Driving five Antigravity units unattended through Herdr during the
mcport-9-resume1 run.

**Evidence.** The U8 evidence unit showed `done` 75 seconds after launch while
its background runner was executing the ten-client assessment; the cycle-16 unit
ground 68 mutation anchors for ~47 minutes of `done` status punctuated by a
4-minute self-scheduled heartbeat; after each turn a CLI-feedback dialog
occupied the composer and could swallow a follow-up prompt
([retro §2.5](../retros/issue-9-2026-08-25.md)).

**Mechanism.** The CLI ends its interactive turn and self-schedules background
work; the session multiplexer reads turn state, so "done" means "not currently
conversing," and anything sent to the composer before the dialog is cleared is
captured by the dialog, not the agent.

**Generalizable rule.** Judge an async worker by durable side effects — commits,
artifacts, live processes — never by its conversational state, and clear its
composer before prompting into an existing session.

### Package-internal asset paths must avoid assuming fixed ancestor repository depth

**Author.** Jeff Cox and Antigravity

**Context.** In run unit U8 of `mission-control` porting (issue #18), ten-client compatibility
assessment revealed that `sync_template_docs.py` failed during `--help` invocation under
session-scoped placement (Cursor Agent and Claude Code).

**Evidence.** `python3 scripts/assess_clients.py --package mission-control --execute` recorded
exit status 1 on `<python> <package>/scripts/sync_template_docs.py --help` for Cursor Agent and
Claude Code, raising `FileNotFoundError: [Errno 2] No such file or directory: '.../plugins/mission-control/config/generated/issue_contract_data.py'`.

**Mechanism.** `sync_template_docs.py:16-25` resolves its contract data file using
`REPO_ROOT = Path(__file__).resolve().parents[3]` and `REPO_ROOT / "plugins/mission-control/config/generated/issue_contract_data.py"`.
This hardcodes a 4-level directory hierarchy (`<repo>/plugins/<package>/scripts/<script>.py`). When
a client installs or mounts the package as a top-level folder (`<session>/package/scripts/<script>.py`),
`parents[3]` steps outside the package into `<session>`, where `plugins/mission-control/` does not exist.
Because `issue_contract_data.py` is imported at module scope (line 27-31), the `FileNotFoundError` occurs
before `argparse` can parse `--help`.

**Generalizable rule.** Package-internal configuration and data files should be resolved relative
to the package root (`parents[1]`), never via assumed repository root nesting (`parents[3]`).

**Refs.** `plugins/mission-control/scripts/sync_template_docs.py:16-31`, `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md`.

### Package-root entrypoints must be blocked in advance for skill-scoped clients

**Author.** Jeff Cox and Antigravity

**Context.** In run unit U8a of `mission-control` porting (issue #18), `assess_clients.py` plan evaluation
raised `AssessmentError` because `mission-control`'s five declared entrypoints (`scripts/*.py`) sit at the
package root outside every declared skill unit (`skills/*`), whereas four client plans (OpenCode, Gemini CLI,
Muse, Hermes) are `skill_scoped=True` and install only individual skill units rather than the package root.

**Evidence.** `python3 scripts/assess_clients.py --package mission-control` raised `AssessmentError` at plan
evaluation (`scripts/assess_clients.py:1358-1372` pre-fix). In this unit, `scripts/assess_clients.py`
(`undeliverable_entrypoints`, `stage_blocked_reason`, lines 1084-1130) intercepts undeliverable entrypoints
and classifies the invocation stage as blocked in advance via `StageOutcome(stage, BLOCKED, reason=...)`
naming the client's design and the undeliverable entrypoint set.

**Mechanism.** A skill-scoped client copies or links only declared skill unit directories into the client's
skill registry, stripping the package root and everything above the skill directories. When entrypoints sit
at the package root outside any skill unit, they physically do not exist in the skill-scoped client's
environment. Hard-refusing the entire 10-client assessment at plan time prevented observing the 6 package-scoped
clients and the 3 runnable stages (placement, discovery, load) of the 4 skill-scoped clients. Blocking invocation
in advance for skill-scoped clients with undeliverable entrypoints accurately captures the client design boundary
without misrepresenting coverage or aborting the assessment.

**Generalizable rule.** When a client's placement model structurally precludes delivering certain package
surfaces, classify the affected downstream stage as blocked in advance with the structural reason rather
than aborting the multi-client assessment plan.

**Refs.** `scripts/assess_clients.py` (`undeliverable_entrypoints`, `stage_blocked_reason`),
`tests/test_assess_clients.py::EntrypointPathTest` (`test_skill_scoped_plan_with_package_root_entrypoints_blocks_invocation_in_advance`,
`test_skill_scoped_plan_with_mixed_entrypoints_blocks_and_names_undeliverable_subset`).

## 2026-08-24

### Dynamic module loading of dataclass-bearing authorities requires pre-execution sys.modules registration

**Author.** Jeff Cox and Antigravity

**Context.** In unit U7 (issue #17), the validation rule audit derived the authority
`card_validator.py` live from the external checkout `home-lab` at test time.

**Evidence.** Calling `spec.loader.exec_module(mod)` on a module containing `@dataclass`
without prior `sys.modules[mod.__name__] = mod` registration failed with
`AttributeError: 'NoneType' object has no attribute '__dict__'` under Python dataclass inspection
(`dataclasses.py:814`: `ns = sys.modules.get(cls.__module__).__dict__`).

**Mechanism.** Python's standard library `dataclasses` module inspects `sys.modules` for the
declaring module during `@dataclass` class decoration. When a module is loaded dynamically via
`importlib.util.module_from_spec(spec)` but not yet registered in `sys.modules`, `sys.modules.get(cls.__module__)`
returns `None`. Pre-populating `sys.modules[mod.__name__] = mod` before calling `exec_module(mod)`
satisfies the inspection cleanly across all Python versions.

**Generalizable rule.** When dynamically loading an external module that defines dataclasses,
always register the module in `sys.modules` before executing its spec.

**Refs.** `tests/test_mission_control_rule_audit.py` (`_load_home_lab_authority`),
`home-lab/ansible/roles/hermes_orchestrator/files/card_validator.py` (`ValidationResult`).


### A second home that does not inherit the first home's invariant is the same defect again

**Author.** Jeff Cox and Grok

**Context.** Three consecutive review rounds of PR #6 shipped the same defect shape: a
value acquired a second home and only one writer or reader learned about it. Round 2's
repairs caused two of round 3's findings; round 3's repairs caused two of round 4's.

**Evidence.** Round 3 added `run_directory` so the transcript write path and the
command-line announcement were one value, and `assess` accepted any truthy path —
skipping the emptiness and workspace-containment invariant `allocate_run_directory`
existed to enforce. Round 3 also started recording `commands` on blocked stages, and
`check_record_version` still skipped every non-executed stage before checking that
`command` equals `commands[0].command`, so a blocked row could name two different
first commands. Round 3 recorded a deadline kill as `exit_status: -1` in both the
public `StageCommand` and the private `CommandTranscript`; subprocess returncode is
`-N` for signal N, so SIGHUP is exactly `-1`.

**Mechanism.** Each repair created a new home for a value (a parameter, a list on a
newly eligible stage, a sentinel) and updated the site that motivated the repair.
The other homes — the freshness guard, the alias check, the wait-status meaning of
`-1`, the private transcript — kept their old assumptions. The tests that existed
each pinned one home.

**Generalizable rule.** Before writing a fix, enumerate every producer and every
consumer of the value — every writer, every reader, every validator, every document
that describes it — and check each one. A fix that updates the producer and leaves
a consumer stale is the failure mode, and it has a 100% recurrence rate in this PR
so far. Put the enumeration in the commit message so it is auditable.

**Refs.** `scripts/assess_clients.py` (`require_fresh_run_directory`, `StageCommand`),
`scripts/check_compatibility_matrix.py` (`check_record_version`),
`tests/test_assess_clients.py::WorkspaceFreshnessTest::test_a_supplied_run_directory_that_already_holds_a_run_is_refused`,
`tests/test_check_compatibility_matrix.py::PerCommandStatusRecordTest::test_a_non_executed_stage_command_must_still_match_its_first_status`.

### A published proof is annotated, not rewritten, when it overclaims a test

**Author.** Jeff Cox and Grok

**Context.** Cycle 13's evidence header said the escaped-descendant test "confirms the
descendant really does survive". The test's own docstring said it deliberately
asserts nothing about whether the descendant lived: it created a marker file and
never read it. Survival was observed by a separate uncommitted probe.

**Evidence.** `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt`
line 31 (as published). `tests/test_assess_clients.py::ProcessGroupTest::test_a_descendant_that_leaves_the_session_is_not_claimed_as_killed` as of cycle 13.

**Mechanism.** The proof header described the intent of the test, not the assertions
it contained. A reader of the evidence file, and a later mutation-proof summary,
would treat survival as something the suite established. The repository's rule that
a published proof is never hand-corrected to say something more convenient is about
digest blocks and manufactured green baselines, not about leaving a false claim in
place. The honest form keeps the original sentence and dates a correction beside it;
making the test assert the marker going forward does not make the cycle-13 sentence
true of that run.

**Generalizable rule.** A published proof may be annotated to say less than it did,
never silently rewritten to say something more convenient, and never left claiming
more than something checkable established. If the claim should be true, make the
test assert it, and say in the note that the assertion was not part of the original
run.

**Refs.** `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt`,
`tests/test_assess_clients.py::ProcessGroupTest::test_a_descendant_that_leaves_the_session_is_not_claimed_as_killed`,
[the grading decision](DECISIONS.md#a-mutation-proof-excludes-its-own-binding-test-and-is-never-corrected-by-hand).

## 2026-08-23

### Both regressions updated the producer and left the consumer behind

**Author.** Jeff Cox and Claude

**Context.** Round two repaired seven review findings. Round three's independent review found
three more, two of them introduced by those repairs.

**Evidence.** The deadline repair added the timed-out command to the private transcript and did
not add it to `commands`, so the public version-2 record named fewer commands than the stage
started — and the post-run safety rule, which grades `commands`, never saw the one command that
had been running unbounded. The run-directory repair moved the transcript to
`<workspace>/run-NNN/transcript.json` and left the closing message naming
`<workspace>/transcript.json`, so every executed assessment told the operator to open a file
that did not exist.

**Mechanism.** One shape twice: a value acquired a second home and only one writer learned
about it. Each call site still read correctly on its own — the transcript append is right, the
`commands` list is right, the write path is right, the message is right — and the defect lives
in the disagreement, which no single-site review sees. Both survived a fifty-one-anchor mutation
proof with zero survivors, because no anchor named the *relationship* between the two sites.

**Generalizable rule.** After changing where a value is produced or stored, enumerate its
consumers and check each one, rather than checking that the change itself is correct. And test
the relationship end to end: the test that catches the path defect runs the real command line
and opens the file it announces, which is the only form of the test that could not pass while
the two sites disagreed.

**Refs.** `scripts/assess_clients.py`,
`tests/test_assess_clients.py::CommandLineTest::test_an_executed_run_prints_a_transcript_path_that_exists`,
`tests/test_assess_clients.py::FailurePathTranscriptTest::test_the_timed_out_command_is_in_the_public_record_too`.

### The cleanup reported containment for a boundary the client can step outside

**Author.** Jeff Cox and Claude

**Context.** When a stage hits its deadline the harness kills the child's process group and
writes into the blocked row how thoroughly it cleaned up.

**Evidence.** The sentence read "The whole process group was terminated, so no client descendant
survived it." A probe: a launcher whose descendant calls `setsid` before sleeping. The
descendant left the group, the kill did not reach it, the probe did not see it, the row said no
descendant survived — and the descendant wrote its marker file three seconds later.

**Mechanism.** `killpg` acts on a process group, and group membership is something a process can
change. The sentence promised the goal — no client still running — while the mechanism delivered
something narrower: this group is empty. Every part of the implementation was correct; the claim
was wider than what the implementation could establish, and the gap only opens on the runs where
it matters, because a client that escapes its group is exactly the client still doing something.

**Generalizable rule.** State what the mechanism established, not what it was for. When the two
differ, the sentence is a defect even though the code is not — and the honest form usually has
to name the case it cannot cover, because a reader who is told "contained" will not go looking.

**Refs.** `scripts/assess_clients.py` (`terminate_process_group`),
`tests/test_assess_clients.py::ProcessGroupTest::test_a_descendant_that_leaves_the_session_is_not_claimed_as_killed`.

### Zero survivors over fifty-one anchors said nothing about the three defects found next

**Author.** Jeff Cox and Claude

**Context.** The mutation proof is the repository's evidence that a guard is tested: break the
guard, watch an authorized test fail, restore.

**Evidence.** Cycle 12 ran 51 anchors with 0 survivors on the exact revision an independent
review then returned three P1 findings against. The reviewer named the reason precisely: "none
of its mutation anchors exercises an escaped process session, the public representation of a
timed-out later command, or the command-line transcript-path handoff."

**Mechanism.** A mutation proof measures the anchors it has. Every anchor names a line someone
already thought was load-bearing, so the proof reports on the guards that exist and is silent
about the behaviour nobody wrote a guard for. Zero survivors is a statement about coverage of
the anchor set, not about the code — and the more thorough the proof looks, the more readily its
silence gets read as a clean bill.

**Generalizable rule.** Read "0 survivors" as "every guard I listed is tested", never as "this is
correct". The proof's value is bounded by the imagination of whoever wrote the anchor list, so
pair it with something that does not share that imagination — an independent reviewer, an
end-to-end probe, a run in an environment you do not control.

**Refs.** `docs/evidence/2026-08-23-cycle13-mutation-proof-portable-copies.txt`,
[the bookkeeping learning](LEARNINGS.md#the-mutation-proof-counted-its-own-bookkeeping-as-a-kill).

### The mutation proof counted its own bookkeeping as a kill

**Author.** Jeff Cox and Claude

**Context.** `MutationProofBindingTest` hashes the five files the mutation proof grades and
compares them to the digests published in the current proof, so a graded file cannot be edited
without its proof being re-run. The proof runner mutated one guard at a time and counted a
mutation killed when the suite went from green to failing.

**Evidence.** Cycle 11 published "38 mutations, 0 survivors". Re-graded with that binding test
excluded, seven of those same anchors turned out to have no test behind them at all — including
one whose guard could have been deleted outright, and the entire version-2 per-command-status
rule in the matrix validator, which shipped with no test of any of its three branches.

**Mechanism.** Every mutation edits a graded file. Editing a graded file changes its digest.
Changing its digest fails the binding test. So every mutation failed the suite whatever it did to
the guard, and the runner read that as a kill. The two mechanisms were built a cycle apart, each
correct alone: the binding test to stop a proof naming bytes that never shipped, the runner to
detect a guard nothing tests. Composed, the first one satisfied the second's success condition
for free.

The tell was there and went unread. Several mutations reported `killed (1)` — one failing test —
and that one test was always the binding test. A kill count of one is a claim that exactly one
test in six hundred covers a guard, which is worth looking at even when it is true.

**Generalizable rule.** When a check's own instrumentation is inside the system it measures, ask
what the measurement reads when the thing being measured does nothing. Here the answer was
"pass", which means the measurement was never about the guard. Any all-pass result from a
detector is a claim about the detector before it is a claim about the code.

**Refs.** `docs/evidence/2026-08-23-cycle12-mutation-proof-portable-copies.txt` (header),
`tests/test_site_profile.py::MutationProofBindingTest`.

### A green baseline was the one thing the proof could not honestly have

**Author.** Jeff Cox and Claude

**Context.** The mutation runner refused to start unless the suite was green, so that a mutation
that fails a test proves the mutation broke something rather than that something was already
broken.

**Evidence.** After the round-2 repairs changed three graded files, the suite failed three
subtests of `MutationProofBindingTest`. To reach a green baseline the previous cycle's evidence
file was edited: three recorded digests replaced with the current ones. That file's own header
warns against exactly this — "a proof whose digest is corrected by hand afterwards identifies
nothing, which is the cycle-7 defect this file's binding test exists to prevent."

**Mechanism.** The proof run is what computes those digests, so the binding test cannot pass
until the run it describes is published. A precondition that cannot be satisfied honestly does
not stop the work; it selects for whichever dishonest route is nearest, and the nearest one here
was retroactively editing evidence to describe a run that never happened.

**Generalizable rule.** When a check can only be satisfied by breaking a rule the project holds,
the check is wrong, not the rule. Fix the check rather than paying its price once and calling it
done — the price gets paid again by whoever comes next, and they may not notice what it cost.

**Refs.** `docs/evidence/2026-08-23-cycle12-mutation-proof-portable-copies.txt`,
[the grading decision](DECISIONS.md#a-mutation-proof-excludes-its-own-binding-test-and-is-never-corrected-by-hand).

### A mutation anchor that is a substring of another line grades the wrong guard

**Author.** Jeff Cox and Claude

**Context.** Each mutation names the guard it breaks by an exact source excerpt, and the runner
aborts if that excerpt does not appear exactly once.

**Evidence.** The anchor for "harness discards captured client output" was
`"        transcript.append("` — eight spaces. The repair that made the timeout path record its
transcript added `transcript.append(` at twelve spaces, and the eight-space excerpt is a
substring of the twelve-space line. The runner aborted after thirty-one minutes. A pre-flight
pass over all forty-eight anchors then found a second unusable one the aborted run had not yet
reached: the excerpt for "matrix safety rule reads only the first command" matched nothing at
all, because the duplicate-grading repair had restructured that loop.

**Mechanism.** Two independent hazards with one shape. An anchor is matched as a substring, so
indentation does not bound it and a deeper copy of the same call silently makes it ambiguous.
And an anchor is a claim about source that no longer exists once the source is edited — a repair
to the guarded line quietly retires the proof of that guard. Both are invisible until the run
reaches them, and the run reaches them one at a time, half an hour apart.

**Generalizable rule.** Validate the whole set of preconditions before the expensive pass, not
lazily as each is reached. The pre-flight here is thirty lines, runs in under a second, and turns
two serial half-hour aborts into one report.

**Refs.** the mutation runner and its anchor pre-flight (session scratchpad),
[the grading decision](DECISIONS.md#a-mutation-proof-excludes-its-own-binding-test-and-is-never-corrected-by-hand).

### Two repairs in a row fixed the instance and left the class

**Author.** Jeff Cox and Claude

**Context.** An independent review of the port-readiness change found a P0 — a launcher wrapper
resolved as its own real binary, so it would exec itself until the host gave out — and a reliability
defect where a stage's deadline did not contain the client's descendants. Both were repaired,
mutation-proved, and shipped. The next review round found both again.

**Evidence.**

| Round | Defect | Repair | Why it did not hold |
|---|---|---|---|
| 1 | `which` returns the wrapper | return the first PATH entry that is **not the same file** as the wrapper | a second *copy* of the wrapper has a different inode, so `samefile` passes it |
| 1 | `subprocess.run` kills only the direct child | `start_new_session=True`, then `os.getpgid(pid)` and signal the group | a launcher that exits leaves the descendant holding the pipes; `getpgid` on the exited leader raises, and the cleanup reported "the group had already exited" while the descendant kept writing |

Both repairs were covered by mutation anchors, and both anchors passed, because each anchor tested
the arrangement the repair was written against.

**Mechanism.** Each repair encoded the *example* rather than the *predicate*. The predicate for the
first is "which of several same-named executables is the launcher" — and nothing on disk answers it,
so every rule of the form "the one that differs from the first" is a guess that happens to be right
on the machine it was tried on. The predicate for the second is "signal the group", and resolving the
group *through the leader* silently made it "signal the group, if the leader is still alive" — a
precondition nobody stated and the probe did not vary.

A mutation proof does not catch this. It shows a guard is load-bearing for the cases in its corpus;
it says nothing about cases the corpus does not contain, and the corpus was written by the same
person who wrote the too-narrow guard.

**Fix.** Stop guessing and stop deriving. The real binary is now supplied by the operator
(`--real-binary NAME=PATH`, or the client's own exported override) and refused otherwise — a blocked
client with the requirement named is true, where a guessed path is a process bomb. The process group
is signalled by `process.pid` directly, which `start_new_session=True` guarantees *is* the group id,
with no lookup that can fail. Both corpora were widened to the class: a copied wrapper, a symlinked
wrapper, an override naming the launcher itself; a leader that exits before its descendant.

**Generalizable rule.** After repairing a defect, write down the predicate the repair now implements
and ask what else satisfies it. If the answer is "the case I tested", the repair is the example
again. And when a repair's predicate turns out to be unanswerable from the available evidence —
which of these identical files is the real one — the correct repair is to stop answering it and
require the input.

**Refs.** `scripts/assess_clients.py` (`resolve_real_binary`, `terminate_process_group`),
`tests/test_assess_clients.py::RealBinaryResolutionTest`, `::ProcessGroupTest`, cycle-12 mutation
proof.

### The zombie leader answered the question about its own descendants

**Author.** Jeff Cox and Claude

**Context.** When a stage hits its deadline the harness kills the child's whole process group
and then asks whether the group still holds anyone, so the blocked stage's reason can say how
thoroughly it was cleaned up.

**Evidence.** On macOS the reason read "the process group could not be signalled; a client
descendant may survive" while a probe showed the descendant was dead — its marker file never
appeared. Reading the errno, `SIGTERM` had killed the descendant and the following `SIGKILL`
raised `PermissionError` (EPERM) rather than `ProcessLookupError`. The first repair concluded
that EPERM meant "nothing left to signal" and treated it as success. That made the sentence
correct on macOS and the reasoning wrong, and CI said so: on Linux the same state answers the
signal with plain success, so every timed-out stage there reported that a descendant might have
survived. Two platforms, two errnos, one cause.

**Mechanism.** The probe ran before the direct child was reaped. An unreaped child is a zombie,
and a zombie is still a process entry that belongs to the group — so the group was never empty
at the moment it was asked, and the answer described the corpse of the process the harness had
just killed rather than any client. Which errno that produced is a platform detail; the ordering
is the defect. Reaping the leader first makes an empty group answer `ProcessLookupError`
everywhere, which is the only answer that means what it says.

**Generalizable rule.** Before reading an error code as evidence, ask what question the call
actually answered. Here the call was asked "is anything still running in this group" while the
thing that had just been killed was still in it — no errno interpretation could have fixed that,
and the one that appeared to was right by accident on the machine it was tried on. When two
platforms disagree about a result, suspect the question before the codes.

**Refs.** `scripts/assess_clients.py` (`terminate_process_group`),
`tests/test_assess_clients.py::ProcessGroupTest::test_the_leader_is_reaped_before_the_group_is_probed`.

### A wrapper resolved by name resolves to itself

**Author.** Jeff Cox and Claude

**Context.** Two of the ten assessed clients are launched through a local auto-trust wrapper that
finds its real binary through the client home. Under the assessment's isolated home that lookup
fails, so each run supplies the wrapper's own documented override naming the real executable.

**Evidence.** `scripts/assess_clients.py` resolved that override as
`shutil.which(plan.binary)` — which returns **the wrapper**, because the wrapper is what sits on
`PATH` under that name. The wrapper would then exec the value of its own override, which is itself,
and keep doing so: an unbounded chain of descendants that never reaches the client. An independent
review graded it P0 and proved the equality without executing the recursion.

**Mechanism.** "Find the real X" and "find X on `PATH`" are the same call when the thing shadowing
X is named X. The shadowing is the whole point of a wrapper, so the one lookup that feels obvious is
the one guaranteed to return the wrong answer — and the wrong answer is not an error, it is a
plausible path that fails only at runtime, in the most expensive way available.

**Fix.** `resolve_real_binary` walks every `PATH` entry, keeps the executables it finds, and returns
the first that is not the same file as the first match, comparing by `os.path.samefile` so a symlink
to the wrapper is caught too. With only the wrapper present it **refuses** — a stage blocked with the
reason named beats a host spawning processes until it dies.

**Generalizable rule.** When a program resolves a dependency *by the same name it is itself known
by*, resolution by name is a self-reference. Resolve by identity — compare the file, not the string —
and refuse when the only candidate is the caller.

**Refs.** `scripts/assess_clients.py` (`resolve_real_binary`),
`tests/test_assess_clients.py::RealBinaryResolutionTest`, cycle-11 mutation proof.

### A deadline is not a containment boundary unless it signals the group

**Author.** Jeff Cox and Claude

**Context.** Every assessment stage carries a timeout, added after a client that prompts on standard
input hung a run indefinitely.

**Evidence.** `subprocess.run(timeout=...)` kills and waits for the **direct** child. Several of
these clients are launched through a wrapper, so the direct child is the wrapper and the client is
its descendant. A probe confirmed a grandchild alive after the run timed out. The stage was recorded
`blocked` while the client it started kept installing and writing state.

A second-order detail worth keeping: the first fix reached for
`subprocess.TimeoutExpired.pid`, which does not exist. The cleanup silently took its
platform-fallback branch and reported "this platform has no process-group signal" on a platform that
has one — a guard reporting a reason that was not true.

**Mechanism.** A timeout bounds *the waiting*, not *the work*. Without a new session the child shares
the caller's process group, so there is no group to signal that would not also signal the harness;
with `start_new_session=True` the child leads its own group, but only a caller holding the `Popen`
still has the pid to signal it with. `subprocess.run` gives that pid away.

**Fix.** `run_contained` owns the `Popen`, mirrors `subprocess.run`'s signature so it drops into the
same injectable seam, and on timeout signals the child's session with `SIGTERM` then `SIGKILL`.

**Generalizable rule.** If a timeout is meant to stop work rather than stop waiting, the process must
lead its own group and the caller must keep the handle needed to signal it. Prove it with a child
that outlives its parent, not with the parent's exit.

**Refs.** `scripts/assess_clients.py` (`run_contained`, `terminate_process_group`),
`tests/test_assess_clients.py::ProcessGroupTest`.

### An optional safety setting is a safety setting that is off

**Author.** Jeff Cox and Claude

**Context.** The port descriptor introduced in this change carries the settings that scope the
assessment's safety rules: which environment variables to strip, which scripts the mutating-operation
rule applies to, which operations count as mutating.

**Evidence.** `custody` was closed against unknown keys; `assessment` was not, and every field in it
defaulted to empty. A descriptor writing `credential_prefix` instead of `credential_prefixes`
validated, loaded, passed the repository gate — and stripped nothing. The same typo in
`package_scripts` scoped the mutating-operation rule to no command, so every command passed the
safety check. An independent review found both, and my own earlier review had found only the narrower
version of the second.

**Mechanism.** Each of these fields fails **open** when empty, and "absent" and "empty" were the same
state. So the failure mode of a typo was not an error but a silently disabled control, and the
cheapest possible mistake bought the most expensive possible outcome.

**Fix.** Every object in the descriptor is closed against unknown keys, every safety field must be
stated, and a field that is genuinely empty is named in `assessment.declared_none` — a decision a
reader can see and a typo cannot produce.

**Generalizable rule.** A setting whose empty value disables a control must never be optional, and
"absent" must never mean "empty". Make the empty case a thing someone had to write down.

**Refs.** `scripts/port_config.py` (`_closed`, `SAFETY_FIELDS`),
`tests/test_port_config.py::ClosedContractTest`, [`ports/README.md`](../../ports/README.md).

### A test that asserts on the machine it runs on reports the machine, not the code

**Author.** Jeff Cox and Claude

**Context.** The port-readiness change added `scripts/assess_clients.py` and its test file. Three
separate tests in one change asserted something true of the author's machine rather than of the
code, and each passed locally while proving nothing, or proving it only there.

**Evidence.** All three, from one pull request:

| Test | Asserted | Actually depended on |
|---|---|---|
| `test_a_tree_that_moves_during_the_run_is_refused` | a stage reached the runner and moved the tree | whether `codex` was installed — all ten clients are on the author's machine, none on the continuous integration runner, so it passed locally and failed in CI |
| `test_a_real_execute_run_produces_a_recordable_row` | the entrypoints exited 0 | whether the interpreter running the tests had `requests` and `urllib3` — true on 3.14 locally, false on the 3.12 floor |
| `test_without_a_confirmation_the_same_process_reports_the_difference` | a prompting process exits 9 | whether the parent's stdin was a terminal, a pipe, or `/dev/null` |

**Mechanism.** Each test named a real behaviour and then reached for an ambient fact to observe it
— a binary on `PATH`, a package in the interpreter, a file descriptor inherited from the parent.
Ambient facts are inputs the test does not control, so the assertion silently becomes *"is this
machine configured the way I expect"*. When the answer is yes the test is green and mute; when it
is no the failure looks like a defect in the code under test.

The dangerous half is the passing case. A test that fails on a different machine gets fixed. A test
that *passes* on the author's machine for the wrong reason ships, and the guard it claims to hold
is not held anywhere.

**Fix.** Supply the ambient fact instead of assuming it. A fake executable in a scratch directory
prepended to `PATH`; `stdin=subprocess.DEVNULL` rather than whatever the parent had; an assertion
on *how many* statuses were recorded rather than on what they were. Where the fact genuinely
belongs to another test's subject — "do the entrypoints run" is
`tests/test_client_entrypoints.py`'s question, and it stubs the transport so the answer is the same
everywhere — assert the part this test actually owns and say so in the docstring.

**Generalizable rule.** Before asserting, ask what on this machine the assertion is reading. If the
answer is anything the test did not put there, either put it there or assert something else. A test
whose result changes with the machine is a machine report wearing a test's name.

**Refs.** `tests/test_assess_clients.py` (`RecordTest`, `SubprocessResultTest`), commit
`e8f342f`, [the code review](../evidence/adhoc-port-readiness-generic-tooling/).

### A guard added to fix one defect can hide the next one

**Author.** Jeff Cox and Claude

**Context.** The code-review gate on the port-readiness change found that an uncaptured client
install id fell back to the package name, so the assessment invoked a path no client uses and
blamed the package for the resulting exit status. The repair stopped seeding the placeholder and
blocked any stage whose command still named an unresolved one.

**Evidence.** Re-running the original probe after the repair returned `blocked`, with the reason
naming `<client-home>, <plugin-id>`. `<client-home>` was in the probe's own values and should have
been substituted. `scripts/assess_clients.py` `stage_argvs` substituted placeholders on two of its
three branches and returned the invocation branch's paths as raw templates, so *every* client's
invocation stage would have run a literal `<client-home>/…` path. The new guard turned that into a
clean, permanent, plausible-looking block.

**Mechanism.** The guard and the latent defect produce the same observable. Before the guard, the
defect showed up as a non-zero exit status that looked like a package failure; after it, as a
blocked stage that looked like correct caution. Neither reading is "the path was never
substituted", and the suite agreed with both: every unit test passed throughout, because nothing
drove `assess(execute=True)` end to end with processes that actually run.

**Fix.** Substitute on every branch, and add the end-to-end test whose absence let it through — one
client, real processes, asserting what lands in the record. The defect was found by re-running the
probe that had motivated the repair, which is the cheap habit: after fixing what a probe found,
run the probe again and read the *whole* output rather than the one field that changed.

**Generalizable rule.** A repair that converts a wrong answer into a refusal has not been verified
until something proves the refusal is not now the only answer. Re-run the original probe after the
fix, and cover the path end to end, not just the guard.

**Refs.** `scripts/assess_clients.py` (`stage_argvs`),
`tests/test_assess_clients.py::RecordTest::test_a_real_execute_run_produces_a_recordable_row`.

### A harness that inherits stdin behaves differently in a terminal than under a scheduler

**Author.** Jeff Cox and Claude

**Context.** `scripts/assess_clients.py` runs coding-agent clients as subprocesses.
Several of them prompt for confirmation on standard input, and the pilot's own runbook
records that one of them hangs rather than declining when stdin is closed.

**Evidence.** `tests/test_assess_clients.py` ran a fake client whose script is
`read answer; [ "$answer" = "y" ] || exit 9`, with no confirmation supplied, and expected
exit status 9. It got a 120-second timeout instead, and the whole test file went from
2.7 seconds to 122 seconds. `subprocess.run` was called with `input=None`, which does not
redirect stdin, so the child inherited the test runner's terminal and sat waiting for a
human to type. Fixed at `scripts/assess_clients.py` by passing
`stdin=subprocess.DEVNULL` whenever a stage supplies no confirmation.

**Mechanism.** `subprocess.run(input=None)` is not "no input" — it is "whatever the
parent has". Under a terminal that is a human; under a scheduler it is usually
`/dev/null`; under a test runner it depends on how the runner was invoked. So the same
stage produces a fast, deterministic exit status in one environment and an indefinite
block in another, and the environment that blocks is the interactive one where a person
is most likely to assume the program has crashed.

A second-order point: the timeout *did* fire, and the harness classified the stage
`blocked` with the deadline named, which is correct behaviour. The deadline turned an
unbounded hang into a bounded wrong answer. That is the deadline working, and it is still
not good enough, because the wrong answer was environment-dependent.

**Generalizable rule.** A subprocess a program starts on its own initiative should never
inherit the parent's standard input. Pass the input it needs, or close it; and give it a
deadline regardless, because closing stdin does not stop a program that ignores EOF.

**Refs.** `scripts/assess_clients.py` (`run_stage`),
`tests/test_assess_clients.py::SubprocessResultTest::test_a_stage_never_inherits_the_operators_terminal`.

### A verification step that reports success for an unrelated reason is worth less than none

**Author.** Jeff Cox and Claude

**Context.** The UniFi portability pilot ran nine review cycles. Across them the
same defect appeared six times, three times in the product and three times in the
coordinator's own verification tooling, and it was never recognised as one defect
until the retrospective. Each instance was fixed on its own terms and the class
went on producing new ones.

**Evidence.** Six instances, all from this pilot:

| Instance | Reported | Actually |
|---|---|---|
| A must-not-fire test whose subject was three characters long | the false-positive class is covered | filtered by a length floor before reaching the rule |
| A completion watcher testing `grep -c ... \|\| echo 1` | reviewers still working | the predicate could never be true, and only in the success case |
| A mutation run whose anchors held real characters, in a file storing them escaped | six guards proved | nothing was replaced; the runs were of unmutated code |
| A mutation run started from an already-failing baseline | eleven guards proved | every result unreadable against the noise |
| A "survived" detector matching the restored run's `OK` | one mutation survived | it had matched the wrong section |
| The repository gate's link check | repository links resolve | one resolved only via a sibling checkout on one machine |

**Mechanism.** Each is a check whose passing condition is satisfied by something
other than the property it claims to establish — a precondition, an exit status
that disagrees with its own output, an unmutated file, a noisy baseline, an
adjacent line of output, a neighbouring directory on disk. Reading the check does
not reveal this; every one of them reads correctly. Only running it against a
world where the claimed property is false does.

Two of them share a sharper property worth naming on its own: they failed *only*
in the success case. The watcher's predicate broke exactly when the artifacts
completed, and the link check passed exactly on the machine where the link was
wrong. A check that degrades gracefully announces itself; a check that fails only
when it matters is silent precisely when it is needed.

**Fix.** Three habits, each cheap:

1. **Make every check fail on demand.** Break the property on purpose and require
   the check to fail. For tests this is mutation; for a gate, feed it a violation;
   for a watcher, hand it the state it is waiting for and confirm it fires.
2. **Never let a success path depend on a command whose exit status disagrees with
   its output.** `grep -c` prints a count and exits non-zero on zero matches, so
   `$(grep -c X f || echo 1)` yields two lines on the success condition. Use
   `$(grep -c X f || true)`, or test the file with `! grep -q X f`.
3. **Require a green baseline before any differential run**, and assert on a
   missing mutation anchor rather than proceeding. Both failures above were
   invisible without these.

**What surprised.** The product bug and the tooling bugs are the same bug. Nine
review cycles hunted the first with increasing rigour while the harness doing the
hunting carried three instances of it. Reviewers scored the code; nothing scored
the scorer.

**Generalizable rule.** For every check — test, gate, watcher, proof — state the
property it establishes and the input that would make that property false, then
confirm the check fails on that input. If it cannot be made to fail, it is not
evidence, and counting it as coverage is worse than having none, because the gap
is now believed closed.

**Refs.** [The UniFi portability pilot retrospective](narratives/2026-08-23-unifi-portability-pilot-retrospective.md).
Two entries superseded by this one and preserved in
[`ARCHIVE.md`](ARCHIVE.md): the negative test that could not fail, and the
completion watcher that could not fire.

## 2026-08-22


### The credential detector read the wrong span, so `Bearer` cleared the token behind it

**Author.** Jeff Cox and Claude

**Context.** The site profile's secret-free guarantee has two families: literal credential
formats, and a credential-shaped key assigned a high-entropy value. The second family is what
catches `notes: "controller password=..."`. Two independent reviewers, on the fourth review
cycle, found the same hole in it at full confidence.

**Evidence.** `plugins/unifi/scripts/site_profile.py:169` and the identical copy at
`scripts/check_repo.py:184`. Probed live: `api_key=<45-char opaque token>` is REJECTED, while
`authorization: Bearer <the same token>` is ACCEPTED. Printing the match showed why — the
captured value group was `'Bearer'`. `authorization: Basic <token>` and `token: Token <token>`
did not match the pattern **at all**.

**Mechanism.** Two distinct faults from one decision. The value group was
`([^\s"',;)}\]]{6,})`, which stops at whitespace, so for `authorization: Bearer <token>` it
captured the scheme word and graded that: `Bearer` carries about 2.25 bits per character,
under the 2.5 floor, so the value was cleared and the credential after the space was never
examined. Worse, `Basic` and `Token` are five characters — below the `{6,}` floor — so the
pattern failed to match at that position and those values went wholly unexamined rather than
examined and cleared. Detection was pointed at the wrong span of the string.

**Fix.** The captured span now runs across whitespace, and a `_credential_candidates` helper
returns the first token plus, when that token is an auth scheme word, the one after it. Both
copies plus the cross-copy pin in one change (`site_profile.py` is `target-owned` and
`check_repo.py` is repository tooling, so neither needed an upstream trip). The same skew on
the Claude adapter path was repaired upstream as unifi `2.0.2`.

**What was rejected.** Grading *every* whitespace-separated token of the value. It closes the
same hole, but `runbook` alone scores 2.52 bits per character, so a profile saying
`auth: see the runbook for the rotation procedure` would be rejected for describing where the
credential lives — which is precisely what a profile is for. The rule must widen toward the
credential, not toward the sentence.

**Validation.** Twelve assertions fail against the pre-repair detector and pass after. A
must-not-fire set covers prose, `vault:` references, `${VAR}`, and `<redacted>`.

**Generalizable rule.** A detector is only as good as the *span* it grades, and a span
boundary chosen for one input shape silently mis-frames another. When a rule scores a
substring, test the shapes where the interesting part is not first — a prefix, a scheme word,
a wrapper — because those do not fail loudly; they pass, which reads exactly like safety. A
minimum-length floor applied to the whole span turns "examined and cleared" into "never
examined", and those two outcomes are indistinguishable from the caller.

**Refs.** Upstream contract repair in `infiquetra-claude-plugins` unifi `2.0.2`,
cycle-4 reviews in [`docs/reviews/`](../reviews/).

### Fixing a shared primitive does not fix the callers that pre-parse its input

**Author.** Jeff Cox and Claude

**Context.** Re-synchronizing the portable UniFi package from upstream release
`2.0.1` at commit `0d81dd9a`, one release after the portable Fleet Core slice
took the `Retry-After` repair from Fleet Core `0.25.1` at `ed72f439`.

**Evidence.** Fleet Core `0.25.1` taught `retry_with_backoff` and
`parse_retry_after` to read both RFC 7231 forms of the `Retry-After` header,
including the HTTP-date form. Both UniFi clients still did
`raise _RateLimited(int(resp.headers.get("Retry-After", 60)))` at their call
site, so the repaired primitive never saw a raw header at all — it saw whatever
`int()` produced, and on an HTTP-date `int()` raises `ValueError` before the
primitive is reached. A `ValueError` carries no `status_code`, so the primitive
judged it non-retryable and propagated it: one request, no backoff, and an
`Unexpected error: invalid literal for int()` for the operator. UniFi `2.0.1`
moved both call sites to `_retry_backoff.parse_retry_after(...)`, visible in
this repository at
[`plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:189`](../../plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py)
and
[`plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py:189`](../../plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py).

**Mechanism.** The primitive's contract is over the *raw* header. A caller that
normalizes the input before handing it over has silently narrowed that contract
to the subset it can already parse, and every later widening of the primitive is
invisible to it. Worse, the failure is not a wrong delay — it is a thrown
exception of a type the retry machinery cannot recognize, so the repair does not
degrade the retry, it removes it.

**Generalizable rule.** When a shared primitive is widened, audit the call sites
that pre-parse its input before declaring the defect fixed; a caller that
converts before it delegates does not inherit the repair, and its failure will
look like a different bug entirely.

### Two portable slices of one upstream repository can legitimately pin two revisions

**Author.** Jeff Cox and Claude

**Context.** After the UniFi `2.0.1` re-synchronization,
`plugins/unifi/PROVENANCE.json` (removed 2026-09-22; see [CHANGELOG.md](../../plugins/unifi/CHANGELOG.md)) pins
`0d81dd9a` while
`plugins/fleet-core/PROVENANCE.json` (removed 2026-09-22; see [CHANGELOG.md](../../plugins/fleet-core/CHANGELOG.md))
still pins `ed72f439`. The Fleet Core slice's own notes previously asserted that
the UniFi package pinned "this same revision", which stopped being true.

**Evidence.** `git diff --name-only ed72f439 0d81dd9a -- plugins/fleet-core`
returns nothing: the upstream subtree is byte-identical across the step. The
recorded byte-copy digest `5aea3be1…` matches the on-disk module and the
upstream bytes at `ed72f439`, and both generated bundles carry that same
`source-sha256` in their stamps.

**Mechanism.** Each slice pins the revision at which *its own* upstream subtree
last changed, which is what makes a pin name a derivation rather than an
unrelated later head. Two slices of one repository therefore diverge in pin
whenever one subtree moves and the other does not, and the pins are still
consistent as long as one is an ancestor of the other and the quieter subtree is
byte-identical between them. That last part is a check, not an assumption.

**Generalizable rule.** Do not treat "both slices pin one commit" as an
invariant; treat it as a coincidence that holds until one subtree moves. State
the ancestry and the byte-identity instead, and verify both rather than asserting
either.

### A default interpreter is not evidence for a declared floor

**Author.** Jeff Cox and Claude

**Context.** Refreshing the compatibility evidence after the catalog's minimum
supported Python was set to `python>=3.12`.

**Evidence.** On the machine this ran on, `python3` is CPython 3.14.6 and
`/opt/homebrew/bin/python3.12` is CPython 3.12.13. Both earlier matrices ran
their invocation stage on the default interpreter and recorded 29 and 21 lines of
argument-parser usage text. On `python3.12` the *same* 2.0.0 client prints 30 and
22, because `argparse` wraps its usage block differently there. The line count
moved without a single package byte changing.

**Mechanism.** A run on a later interpreter proves the later interpreter. It
cannot prove the floor, and it cannot even be assumed to produce the same
observable output, because the standard library differs between them. An
evidence document that records a number gathered above the floor and a floor
claim in the same page invites the reader to attach one to the other.

**Generalizable rule.** Run floor evidence on the floor interpreter by explicit
path, never on `python3`; and when a recorded number moves, prove the cause by
re-measuring the old artifact on the new interpreter before attributing it to the
change under test.

### A byte copy imports the upstream platform floor along with the upstream fix

**Author.** Jeff Cox and Claude

**Context.** Re-synchronizing the portable Fleet Core slice from Fleet Core
0.25.1, the upstream release that repairs RFC 7231 `Retry-After` HTTP-date
handling in the shared backoff primitive.

**Evidence.** The corrected module at
[`plugins/fleet-core/scripts/fleet_commons/retry_backoff.py:28`](../../plugins/fleet-core/scripts/fleet_commons/retry_backoff.py)
adds `from datetime import UTC`. `datetime.UTC` is an alias introduced in
Python 3.11; on Python 3.10 that line raises
`ImportError: cannot import name 'UTC' from 'datetime'`, verified directly
against a 3.10.20 interpreter. The repository's ported-plugin job pins Python
3.10 on purpose, at
[`.github/workflows/ci.yml:48`](../../.github/workflows/ci.yml), "because the
portable packages target Python 3.10 or newer and a floor that is never
exercised is not a floor."

**Mechanism.** A byte copy is a promise about bytes, not about behavior on the
consumer's platform. The two repositories do not share a support floor: the
upstream Claude Code plugin runs wherever Claude Code runs, while this catalog
publishes a declared floor of its own. Nothing in the synchronization contract
compares them, so an upstream author can raise the interpreter requirement in a
patch release and the derived package inherits it silently. The digest check
still passes, because the bytes really are identical; that is exactly the
property that makes the break invisible to every check the repository owns.

**The custody rule is what stops the obvious repair.** Replacing `UTC` with
`timezone.utc` here would fix the floor and destroy the guarantee: the path
would no longer equal its source, and `retry_backoff` would have a second
writable source, which is the failure the whole slice was designed to prevent.
So the choice is upstream repair or a moved floor, and both are decisions, not
edits.

**Generalizable rule.** When a derived package declares a platform floor, the
floor is part of the synchronization contract and has to be checked against the
source on every re-synchronization; a digest that matches proves nothing about
whether the new bytes still run where the package says they run.

**Outcome, 2026-08-22.** The operator answered this by making the floor the
source's floor rather than a separately maintained one. The catalog's minimum
supported Python is now `python>=3.12`, which is what
`infiquetra-claude-plugins` declares and tests, so there are no longer two
support floors to fall out of step. Everything recorded above stayed true as
written: the interpreter pin quoted here, `.github/workflows/ci.yml` at Python
3.10, was the configuration at the time and has since moved to the new floor.
The generalizable rule holds in a stronger form — a derived catalog should not
maintain a platform floor of its own at all, because the only floor it can
actually keep is the one its source keeps. See
[the decision](DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312).

**Refs.** [The floor decision](DECISIONS.md#the-portable-catalogs-minimum-supported-python-is-python312),
[the archived queue item](ARCHIVE.md#decide-the-python-floor-the-fleet-core-resync-raised),
[the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)

### Regenerating a build artifact retires the observational evidence bound to it

**Author.** Jeff Cox and Claude

**Context.** The same re-synchronization. It had to regenerate both
`skills/*/scripts/_bundled/retry_backoff.py` bundles so every consumer carries
the new Fleet Core stamp, and it re-pinned
`plugins/unifi/PROVENANCE.json` to the corrected revision.

**Evidence.** Those three files are inside `plugins/unifi/`, so the package's
tree digest moved from `6e6b57c1…` to `da46ca77…`. Eight tests in
[`tests/test_check_compatibility_matrix.py`](../../tests/test_check_compatibility_matrix.py)
went red at once: four holding the ten-client matrix at
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md)
to the tree it assessed, and four holding the post-activation readback at
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md` (superseded)](../evidence/2026-08-22-unifi-post-activation-readback.md)
to the release it read back. The file count did not change; only the digest did.

**Mechanism.** A Fleet Core release and a UniFi assessment look unrelated, and
the build step is what couples them: bundling puts a stamped copy of the Fleet
Core module inside the UniFi package, so any Fleet Core release changes the
UniFi tree digest even when no UniFi source byte moves. The matrix binding then
fires correctly. It is not a false alarm and it is not this unit's bug — it is
the binding doing the one job it was added to do, saying that the document no
longer describes what ships.

**The cheap fix is the exact failure the binding exists to catch.** The matrix
says so itself: "There is deliberately no flag that writes that fingerprint back
into this document. Refreshing the numbers without re-running the assessment is
precisely the failure this binding exists to catch." Editing `tree_sha256` by
hand is that same act with more keystrokes, and it would convert forty real
stage results into forty claims about bytes nobody ran. So the resync left both
documents untouched and the eight tests red, and queued the re-run.

**Generalizable rule.** A build-time bundle makes every upstream release a
change to the consuming package's identity. Any evidence document bound to that
identity has to be re-earned by re-running the assessment, so schedule the
re-run as part of the release, and never let a red binding be closed by editing
the number it compares.

**Refs.** [Queued evidence re-run](QUEUED.md#re-run-the-ten-client-matrix-and-the-readback-against-the-resynced-package),
[identity is not execution](LEARNINGS.md#a-bound-digest-names-the-tree-not-the-forty-stages-that-assessed-it)

### A bound digest names the tree, not the forty stages that assessed it

**Author.** Jeff Cox

**Context.** Cycle-two code review finding F6 from Ox Alpha, reconciled as
consensus open item O7. The matrix binding proves the recorded digest
identifies the shipped tree. The operator ruled the rest a
non-blocking evidence limitation, not a new gate. This unit records that
limitation. It does not add a blocking check, and the identity check is not weakened.

**Evidence.** The Ox Alpha review
([`docs/reviews/2026-08-22-code-review-cycle2-ox-alpha-max.md`](../reviews/2026-08-22-code-review-cycle2-ox-alpha-max.md),
finding F6) is exact: the fingerprint check makes accidental drift
impossible to miss, and it cannot prove the forty stages were actually
executed against the bound tree. Hand-editing the record's count and
digest after a package edit still passes every check. Ox Alpha's finding
is that identity is not execution. The same review
notes the code is honest about intent —
`scripts/check_compatibility_matrix.py` refuses a rewrite flag, "re-run,
not renumbered" — and that the guarantee is one-directional. The
cycle-two consensus records this as O7, advisory, routed to the operator
([`docs/reviews/2026-08-22-code-review-cycle2-consensus.md`](../reviews/2026-08-22-code-review-cycle2-consensus.md)).

The binding itself still bites. `check_package_binding` recomputes file
count and tree digest from `plugins/unifi/` and fails on mismatch.
Accidental drift remains a validation failure. What remains
undetectable is copying `--print-fingerprint` into the JSON record
without running a client.

**Mechanism.** Two claims were being read as one. Matching a digest says
which bytes the evidence names. It does not say that placement,
discovery, load, and invocation ran against those bytes. The approved
plan already split those claims. The binding is the identity half.
Runtime execution and readback already live in named plan places. This
record does not replace them with a broader gate.

**The plan already requires real runtime execution and readback here.**

1. Plan unit U11, with requirements R22 and R43: an operator-run
   ten-client assessment. Each of the ten clients has four stages —
   placement, discovery, load, and invocation — which is the forty
   stages. Continuous integration does not run that assessment. Record:
   [`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md).

2. Plan unit U9, requirement R40: after upstream release activation, an
   installed-version and digest readback confirms the running client is
   those bytes. Record:
   [`docs/evidence/2026-08-22-unifi-post-activation-readback.md` (superseded)](../evidence/2026-08-22-unifi-post-activation-readback.md).

3. Plan unit U9, requirement R41: a fresh client session proves all
   three profile states (present, absent, unreadable). Source-tree
   evidence alone does not satisfy R41, because a running client can
   hold a cached earlier version.

**Generalizable rule.** A fingerprint check proves identity. It does not
prove the process that produced the evidence ran against that artifact.
Keep the identity check; keep execution evidence in the places that
actually run and read back. Do not invent a gate that still cannot see
the clients.

**Refs.**
[Binding decision](DECISIONS.md#bind-a-current-matrix-to-the-tree-it-assessed-and-make-supersession-the-only-exemption),
[queued recording](QUEUED.md#keep-the-matrix-binding-an-identity-check-do-not-add-an-execution-proof-gate),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)
(U9, U11, R22, R40, R41, R43),
`scripts/check_compatibility_matrix.py` (`check_package_binding`).

---

### A path a manifest names is untrusted input, even when the manifest is ours

**Author.** Jeff Cox and Claude

**Context.** Repairing finding F-06 of the 2026-08-22 code review of the portable UniFi
package, raised independently by the Cursor reviewer and confirmed by the controller.

**Evidence.** `previously_managed()` in
[`scripts/sync_vendor_source.py`](../../scripts/sync_vendor_source.py) accepted any
non-blank `path` string recorded in `plugins/unifi/PROVENANCE.json`, and the stale-cleanup
step in `apply_plan()` then evaluated `plugin_dir / path` and called `unlink()` on it.
Replaying the three attack shapes against the pre-repair script deleted a file planted
outside the package in all three cases: an absolute path, `../../../outside/victim.txt`,
and `skills/escape/victim.txt` reached through a symlink inside the package. The
[Cursor review](../reviews/2026-08-22-code-review-cursor-gpt-5.6-sol-xhigh.md) records the
finding at `scripts/sync_vendor_source.py:635`.

**Mechanism.** Two separate assumptions failed together. First, `pathlib` join is not
containment: `Path("/a/b") / "/etc/hosts"` is `/etc/hosts`, so an absolute string silently
discards the prefix that was supposed to confine it. Second, the repository already
carried the lexical half of the rule — `check_repo.py` rejects absolute and `..`-bearing
provenance paths when it validates a manifest — but that check runs in a different command
than the one that deletes, so the deleting path had no guard at all. A rule enforced by a
validator nobody calls before the dangerous operation is not enforcement. The lexical half
would also not have been enough on its own: a symlink inside the package makes
`skills/escape/victim.txt` lexically innocent and still land outside, which only resolving
the path and comparing it against the resolved package root can see.

**Generalizable rule.** Validate untrusted paths at the operation that acts on them, not
only where they are authored, and validate them twice: lexically, then by resolving and
proving containment. A validator in a different command is documentation, not a control.

### A byte-copied README describes the source package, not the derived one

**Author.** Jeff Cox

**Context.** Consensus C5 (Cursor F-07, OpenCode F-07): the portable UniFi
package's own README introduced the tree as a Claude Code plugin and told
readers to run `pytest tests/test_unifi_network_client.py` and
`tests/test_unifi_protect_client.py`, neither of which exists in this
repository.

**Evidence.**
`plugins/unifi/README.md` at the reviewed commit opened "Claude Code plugin
for managing…". `plugins/unifi/PROVENANCE.json` classified that file as
`upstream-byte-copy` with digest `a3b3b056…`, matching the Claude plugin
README at the pinned source. The plan labelled the same path "portable core,
rewritten site-neutral". The two statements cannot both be true of one file.
Fixed in this repair: the README is rewritten for this package, the provenance
entry is `target-owned`, and `tests/test_unifi_readme.py` reads the shipped
file the way a consumer does.

**Mechanism.** Synchronization treats an upstream byte copy as a success when
the bytes match the source. That is the right rule for a skill or a client.
It is the wrong rule for package documentation whose subject is the derived
tree: the client extension directory, the Fleet Core bundle, the site-profile
contract, and the commands that run here. Copying the source README faithfully
is how the portable package documented a plugin it is not, and named tests it
does not ship.

**Generalizable rule.** A derived package whose identity differs from its
source cannot keep the source README as a byte copy. Package documentation is
about the assembled artifact; if that artifact is not the source, the README
is target-owned (or a named transform), not a digest match.
### A check that cannot be evaluated must not return the permissive answer

**Author.** Jeff Cox and Claude

**Context.** Two independent reviews of the portable UniFi package, reconciled in
[the review consensus](../reviews/2026-08-22-code-review-consensus.md), each found a
runtime defect in the discovery and drift scripts. The two look unrelated — one is a
false drift finding, the other a persistence deny-list — and they are the same mistake.

**Evidence.** Both reviewers independently reported the drift defect (consensus item C2,
Cursor F-03 and OpenCode F-03, both rated P1). `drift.report` compared the profile's
intended policies against `inventory["policies"]`, which `discover.py` assigned as an
unconditional empty list because the read-only catalog composes no policy list
operation. Every intended policy therefore produced a `missing-policy` finding on every
live run, including for policies that exist on the controller. The persistence defect
(consensus item C10, OpenCode F-06, P2) is in `refuse_repository_output`: it resolved the
working tree by walking up for a `.git` entry, and when that walk found nothing it
returned the output path unrefused, so discovery run from a copy of the package without a
checkout could write an unfiltered controller response into the package directory.

**Mechanism.** In both places a guard reached a state where it had no answer, and
returned the answer that permits. Drift asked "is this policy on the controller?" of a
list nothing had ever looked at, and read the empty list as "no". Persistence asked "is
this path inside the working tree?" with no working tree to compare against, and read the
unanswerable question as "no". Neither failure is visible from inside the guard: an empty
list and a `None` root are both ordinary values, and the permissive branch is the one
with no error to raise. Both were also locked in by tests, which asserted the false
`missing-policy` finding as expected output and exercised persistence only with an
injected repository root, so the defective branch was never reached.

**The repair.** Discovery now declares `policy_observation` alongside `policies`, so an
inventory says whether its policy set was observed at all; drift emits `missing-policy`
only for an inventory that observed one, and names the gap in `limits` rather than
dropping the comparison silently. An inventory from a policy-aware source still gets the
full comparison, including when it observed an empty set. Persistence refuses a path
inside the package's own directory with or without a checkout, and refuses outright when
no working tree can be determined, naming `--repository-root` as the way to say which
tree to protect.

**Generalizable rule.** A check that cannot be evaluated must refuse, not pass. When a
guard's input can be absent as well as empty, absence and emptiness need separate values,
because collapsing them makes the unexamined case indistinguishable from the examined
one. And a test that asserts a guarantee should be run once against the unfixed code: a
regression test that passes either way is the same defect in the test suite.

---

### A package can satisfy every structural check and still have no working entrypoint

**Author.** Jeff Cox and Claude

**Context.** Running the ten-client compatibility matrix against the assembled portable
UniFi package, after every preceding unit of the pilot had reported green.

**Evidence.** Every client that reached the invocation stage produced the same failure:
both `unifi_network_client.py` and `unifi_protect_client.py` abort during module import
with `ModuleNotFoundError` for `fleet_commons_shim`, before any argument is parsed. The
import is at `plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py:49`, and
no file of that name exists anywhere in the assembled package. The full record is in the
[ten-client compatibility matrix (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md).

**Mechanism.** Synchronization deliberately drops both copies of `fleet_commons_shim.py`,
because build-time bundling is meant to replace them, and
[`plugins/unifi/fleet-bundle.json`](../../plugins/unifi/fleet-bundle.json) duly declares
the `retry_backoff` module the package needs. Nothing ever emitted it. The repository
validator did not catch this, because its two bundle checks both validate
correctness-when-present rather than presence: `check_bundled_files` walks the bundle
files that exist and verifies their stamps, and `check_fleet_bundle_declarations`
validates the declaration's shape against a closed schema. A declaration naming a module
that was never written is well formed, so every gate stayed green while the package had
no runnable entrypoint at all.

**Generalizable rule.** A declaration that names a required artifact must be checked for
that artifact's presence, not only for its correctness when present. An absent file
produces no violation to report, so absence has to be asserted deliberately or it is
never noticed. This is a second instance of the seam defect recorded below, found the
same way: at the first end-to-end run.

---

### Every unit passed its own tests and the defect lived in the seam between two correct units

**Author.** Jeff Cox and Claude

**Context.** A correctly deployed operator site profile produced `mode=discovery-only`
with zero subjects during the pilot, on a machine where the profile file was present at
the documented path.

**Evidence.** The pilot's Run C follow-up commit. The deployment unit wrote a valid
profile to the documented runtime path, and the loader unit read the resolution contract
exactly as that contract is written. Neither unit was wrong, and both unit test suites
were green.

**Mechanism.** The contract resolves the `UNIFI_SITE_PROFILE` environment variable first,
then the path remembered in `config.json`, then no profile at all. Deploying a file to
the documented default runtime path registers it with neither rung. One unit owned
writing the file and another owned reading the contract; no unit owned making the
deployed path reachable by the resolution order. The capability was split across units,
and the seam between them belonged to nobody, so the end-to-end path did not work while
every unit-level check passed. The portable half of this gap remains open and is recorded
in [queued work](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read).

**Generalizable rule.** A plan that splits a capability across units must name which unit
owns the seam, and gate the release on an end-to-end check rather than on the union of
unit-level green. The union of green units is not evidence that the capability works.

---

### Two correct halves and no owner for the join ships a package that cannot run

**Author.** Jeff Cox and Claude

**Context.** The assembled portable UniFi package had no working entrypoint on any
client, while every validator in the repository reported success.

**Evidence.**
`python3 plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py --help`
exited 1 with `ModuleNotFoundError: No module named 'fleet_commons_shim'`, raised at
module scope before argparse ran; `unifi_protect_client.py` failed identically. The
ten-client compatibility matrix in
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md)
recorded the same abort for every client that reached the execution stage. Fixed by
`scripts/sync_vendor_source.py` transform `resolve-bundled-fleet-module`, the
per-client destinations in `plugins/unifi/fleet-bundle.json`, and
`check_repo.check_fleet_bundle_outputs`.

**Mechanism.** Two pieces of tooling each did their own job correctly. The bundler
(`scripts/bundle_fleet_module.py`) generates a Fleet Core module into the consuming
package and rejects a tampered or stale copy. The synchronization
(`scripts/sync_vendor_source.py`) reproduces upstream bytes exactly and refuses a
downstream edit. Between them sat one fact neither owned: the clients import
`fleet_commons_shim`, and the package deliberately ships no such module. The
synchronization classified both clients as upstream byte copies, so copying the broken
import verbatim was not merely permitted but required by its own rule; the bundler was
never asked to write anything the clients actually resolve, so no bundle was generated
at all. Each validator was correct about its half. Nothing asserted that the assembled
result would start.

The blind spot had a precise shape. `check_repo.check_bundled_files` reads the bundles
that are on disk, so a bundle that was never generated is invisible to it -- absence of
evidence read as evidence of absence of a problem. No test executed a shipped
entrypoint, so the one signal that would have caught it in a second was missing.

**Generalizable rule.** When two tools each own one half of an artifact, the join is
not covered by testing both halves. Add one test that runs the assembled thing the way
a user runs it, and one validator assertion that the two halves name the same files.

### Neutralizing an environment variable does not neutralize a fallback that reads a file

**Author.** Jeff Cox and Claude

**Context.** Two tests in `tests/test_drift.py` began failing on a branch whose
production code had not changed, once a real operator site profile was deployed on the
developer's machine.

**Evidence.** `tests/test_drift.py::PersistenceAndCliTest` called
`drift.main(..., environ={})` intending a run with no site profile.
`test_cli_writes_a_report_outside_the_tree` expected mode `discovery-only` and got
`profile`; `test_cli_with_injected_inventory_writes_nothing_inside_the_tree` expected
zero findings and got nine, the first being an `unprofiled-host` finding against a real
host. The same suite was green earlier in the same pilot, before any profile existed on
the machine.

**Mechanism.** The site-profile contract in
`plugins/unifi/scripts/site_profile.py:262` resolves a profile from two rungs: the
`UNIFI_SITE_PROFILE` environment variable first, and the path remembered in
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json` second. An empty `environ`
mapping suppresses only the first rung. The second is read from the real filesystem
through `Path.home()`, which no `environ` argument reaches. The tests were therefore
asserting a property of the developer's machine, not of the code. The fix pins
`XDG_CONFIG_HOME` into the test's temporary directory and passes the `--config-path`
seam the command line already offers, so both rungs land inside the temporary tree.
A companion test now deploys a profile through the configured rung on purpose and
asserts profile mode with the two findings it implies, which is the case the failing
tests had been exercising by accident.

**Generalizable rule.** When a lookup has more than one rung, isolating a test means
pinning every rung, not the first one; a rung that ends in a filesystem default is the
one that will silently read the developer's machine.

### A validator that only inspects what a manifest already declares cannot detect a deletion

**Author.** Jeff Cox and Claude

**Context.** Closing three of the seven findings that two independent reviewers reached
about commit `95de0d5` (pull request #3), recorded in
[the two-reviewer consensus](../reviews/2026-08-22-code-review-consensus.md) as C3, C4,
and C6. All three are validator gates in `scripts/check_repo.py` that report green in
the situation they exist to catch.

**Evidence.** Three repairs, and each one has a scenario that the pre-repair validator
let through. C3: `check_provenance_manifests` iterated `payload["files"]` and recomputed
the digest of each listed file, so adding `plugins/example/scripts/extra.py` to a package
returned no errors, and so did deleting a file's entry from the manifest while leaving
the file on disk, and so did listing one path twice with two different classifications.
C4: `_check_bundle_source_freshness` opened with `if not source_rel or not recorded:
return []`, so deleting the `source-path` and `source-sha256` lines from a generated
bundle's stamp removed the comparison with Fleet Core and returned no errors; the same
held for `generated-by`, `source-version`, and `source-commit`, none of which were read
at all. C6: no value-level credential check existed, so a package file containing
`"notes": "controller password=hunter2"` passed the whole gate. Ten of the eleven
scenarios came back with an empty error list against the validator at `95de0d5`.

**Mechanism.** Each of the three gates took its input from the artifact it was supposed
to be judging. The provenance check asked the manifest which files to verify, so a file
the manifest omitted was outside the question being asked. The bundle check asked the
stamp which comparisons to run, so a deleted stamp line deleted the comparison rather
than failing it. The secret check asked the schema which field *names* were forbidden, so
a credential written into a permitted field's *value* was never a candidate. In all three
the artifact under test controlled the scope of its own test, which means the defect and
the thing that would have reported it are removed by the same edit. The repairs close the
loop against a source the artifact does not control: the package tree on disk, a fixed
tuple of required stamp fields, and the byte content of the value itself.

**Generalizable rule.** A check that derives its own scope from the artifact it is
checking can only ever detect corruption, never omission. Enumerate the required set
independently — from the filesystem, from a constant, from the bytes — and compare, or
the guarantee disappears with whatever line an editor deletes.

### A digest in an evidence record proves nothing until something recomputes it

**Author.** Jeff Cox and Claude

**Context.** Repairing findings C1 and C9 of the 2026-08-22 code review of the portable
UniFi package. C1 was raised independently by both reviewers (Cursor F-01, OpenCode F-01
and F-02); C9 came from Cursor F-02 and matched the controller's own record.

**Evidence.** The ten-client compatibility matrix bound itself to `file_count: 21` and tree
digest `92ed5032…`. The package this repository ships holds 23 files, and both entrypoints
exit 0 and print usage where the matrix reported `ModuleNotFoundError` at all ten
invocation slots. `python3 scripts/check_compatibility_matrix.py` passed anyway, because
`check_public_evidence_rules` skipped `$.package.tree_sha256` as a non-leak and the schema
only asserted `^[0-9a-f]{64}$`. Nothing in the repository ever computed that digest. The
recomputed value for the shipped tree is `6e6b57c1…8415`.

**Mechanism.** A digest field creates the *appearance* of binding without the binding. The
schema constrains its shape, the leak scanner exempts it, the eye reads 64 hex characters
as proof — and no code path ever compares it with anything. The evidence and the artifact
then drift apart silently, and the failure does not present as a missing check. It presents
as a passing one. This is the same shape as the other eight findings in the review: a
guarantee that exists but does not bite.

**The escape hatch matters as much as the check.** Preserving the pre-repair matrix required
a way to exempt a retired document from the binding. That exemption is a second trap if it
is not itself constrained: anyone could mark the live matrix superseded and switch its
binding off. So a superseded document whose fingerprint *still* identifies the shipped tree
is rejected, and `matrix-status` defaults to `current` when absent, which makes the binding
fail-closed.

**One more trap, found while writing the fix.** The directive parser read
`<!-- matrix-status: superseded -->` out of the fenced code block that *documented* the
format, and the current matrix marked itself superseded. A document has to be able to
describe its own metadata language without the description taking effect, so fenced blocks
are blanked before directives are read.

**Generalizable rule.** A recorded fingerprint is inert unless a check recomputes it from
the live artifact and fails on mismatch; if an evidence field can only be validated for
shape, it is decoration, not evidence.

**Refs.** [Binding decision](DECISIONS.md#bind-a-current-matrix-to-the-tree-it-assessed-and-make-supersession-the-only-exemption),
`scripts/check_compatibility_matrix.py` (`package_fingerprint`, `check_package_binding`,
`check_document_status`), `tests/test_check_compatibility_matrix.py`
(`PackageBindingTest`, `DocumentStatusTest`, `FingerprintTest`),
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md` (superseded)](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[the superseded pre-repair matrix](../evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md),
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md` (superseded)](../evidence/2026-08-22-unifi-post-activation-readback.md).

## 2026-08-21

### A plugin's tracked file list does not reveal what it needs to run

**Author.** Jeff Cox and Claude

**Context.** Scoping the UniFi portability pilot from its thirteen tracked files.

**Evidence.** Both UniFi clients call a loader at module import time, not inside a
function, which reaches into a separate plugin the manifest never declares as a
dependency. The loader resolves that plugin four ways and three are host-specific: a
walk-up for the Claude marketplace manifest, a read of Claude Code's installed-plugin
registry, and a scan of a Claude-injected environment variable. Only one path is
host-neutral. Details and line citations are in the [pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md).

**Mechanism.** Because the call runs at import rather than at use, the failure lands
before argument parsing. On a host where the loader finds nothing, every command fails,
including read-only ones that never needed the dependency. Nothing in the file list, the
manifest, or the directory layout shows this; only reading the imports does.

**Generalizable rule.** Before scoping any port, read the target's import statements, not
its file list. An import-time dependency resolved through host-specific discovery is
invisible to packaging and fatal to portability, and a manifest that declares no
dependencies is not evidence that there are none.

---

### Documentation drifts in both directions, and the dangerous direction is over-promising

**Author.** Jeff Cox and Claude

**Context.** Building a behavior-parity inventory for the same pilot.

**Evidence.** A commit five months before the port removed four Protect capabilities
because the older API path rejects key-based authentication. Eighty-one references to
those capabilities survive across six documentation surfaces, including the plugin
manifest's own description. Separately, both API reference documents disagree with the
shipped code on multiple endpoint paths, and the network skill omits four capabilities
that do work.

**Mechanism.** Under-documentation costs a reader a discovery; over-documentation costs
an agent a failed invocation it was told would succeed. An agent loads the skill file,
not the source, so documentation that promises absent commands is not merely stale, it is
an instruction to do something impossible.

**Generalizable rule.** Derive a parity inventory from the code and treat every
documentation surface as a claim to be checked against it. When a port finds drift,
repair it in the authoritative source rather than in the copy, or the two diverge
permanently and neither can be trusted afterwards.

---

### Portable plugin standards do not replace vendor runtimes

**Author.** Jeff Cox and Codex

**Context.** Research compared the plugin and skill surfaces used by the coding
agent clients in the Infiquetra environment.

**Evidence.** The
[cross-vendor plugin architecture brief](../cross-vendor-plugin-architecture-brief.md)
links the Agent Skills and Agent Plugins specifications and records the client
compatibility findings.

**Mechanism.** Agent Skills can carry procedural instructions, and Agent
Plugins can package skills with Model Context Protocol servers. Commands,
hooks, native agent definitions, permissions, user interfaces, and marketplace
distribution remain client-specific.

**Generalizable rule.** Keep the shared behavioral contract portable, but use
explicit adapters for capabilities governed by a vendor runtime. Do not call an
installed or copied vendor package the shared source of truth.

---

Keep newest entries first. When evidence invalidates an entry, preserve the old
text in [ARCHIVE.md](ARCHIVE.md) and link the corrected learning.
