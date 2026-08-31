# Learnings - infiquetra-agent-plugins

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
[`plugins/unifi/PROVENANCE.json`](../../plugins/unifi/PROVENANCE.json) pins
`0d81dd9a` while
[`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json)
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
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md)
to the tree it assessed, and four holding the post-activation readback at
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md)
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
   [`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md).

2. Plan unit U9, requirement R40: after upstream release activation, an
   installed-version and digest readback confirms the running client is
   those bytes. Record:
   [`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md).

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
[ten-client compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md).

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
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md)
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
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[the superseded pre-repair matrix](../evidence/2026-08-22-unifi-compatibility-matrix-pre-repair.md),
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md).

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
