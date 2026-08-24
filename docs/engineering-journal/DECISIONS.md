# Decisions - infiquetra-agent-plugins

## 2026-08-24

### Mission-control port run plan: new transform rules stay single-shape, rule selection lives in the descriptor

**Author.** Jeff Cox and Claude (Saga Plan for issue #9)

**Decision.** The mission-control port run plan
([docs/plans/2026-08-24-mission-control-port-run-plan.md](../plans/2026-08-24-mission-control-port-run-plan.md))
fixes five plan-level choices inside the operator-approved contract of issue
#9: (1) the two mission-control entrypoint consumers get two **new** named
single-shape transform rules, each preserving exactly-one-match discipline, and
the existing `resolve-bundled-fleet-module` v1 stays byte-untouched; (2)
transform-rule selection becomes an explicit per-path field in the port
descriptor — additive within schema 2, with `ports/unifi.json` naming its rule
explicitly in the same commit; (3) the `when_to_use:` skill-frontmatter key is
folded under the permitted `metadata` key by a new `normalize-skill-frontmatter`
v1 transform, portable copies only; (4) CI package-test wiring uses the
`plugins/*/tests` glob plus a can-fail path-agreement meta-check rather than
per-package enumeration; (5) the card-validator verdict-agreement test derives
its authority live from the home-lab checkout and self-skips loudly when the
checkout is absent.

**Rationale.** Bumping the existing rule to a multi-shape v2 would loosen the
exactly-one-match discipline and change the transform identity UniFi's
committed provenance records; AGENTS.md places porting-tool package
configuration in the descriptor, never in a script constant; `metadata` is one
of the seven fields `check_repo.py` permits, so the fold is deterministic,
idempotent, and lossless; the glob plus meta-check means the next port cannot
silently ship uncollected tests; a copied-constant authority corpus cannot fail
when the authority moves.

**Rejected alternatives.** *One loosened multi-shape rule v2* and *first-match
semantics* (a #13 stop condition). *A script-internal path-to-rule registry*
(the custody violation AGENTS.md names). *A schema-3 bump for the rule-name
field*, per the precedent above that additive fields do not bump a schema
version. *Folding `when_to_use` into the skill body* (lossy placement, harder
idempotence) and *normalizing upstream* (the key is functional in Claude Code
listings). *Vendoring a second card-validator authority copy here* (a third
copy that can disagree).

**Revisit when** a third port needs a transform shape neither new rule covers
(that is the moment to consider a general rule grammar, not before), or when
fleet-core migrates onto a port descriptor and the descriptor-vs-PROVENANCE
custody split changes.

### A deadline-killed command is marked timed out, not given a fake exit status

**Author.** Jeff Cox and Grok

**Decision.** A command the harness kills at the stage deadline is recorded with
`timed_out: true` and no `exit_status`. A command that exited or was terminated by a
signal carries `exit_status` (the process wait status) and no `timed_out`. The two
fields are mutually exclusive. subprocess returncode is `-N` for termination by
signal N, so `-1` is SIGHUP and is recorded as `exit_status: -1`. The schema lists
both fields; `check_compatibility_matrix.py` refuses a command entry that has both,
neither, or `timed_out` set to anything other than true. Existing committed records
carry `exit_status` only and still validate.

This supersedes [A command that hit the deadline is recorded like any other
command](#a-command-that-hit-the-deadline-is-recorded-like-any-other-command),
which reserved `-1` for the deadline and claimed no real exit status can say that.
The "it ran, so it is in `commands` and is safety-graded" half of that decision
stands.

**Rationale.** A sentinel that collides with a real wait status is not a sentinel.
The previous form made "killed at the deadline" and "terminated by SIGHUP"
indistinguishable in every consumer of the public record and of the private
transcript. Omitting `exit_status` is no longer "not recorded": `timed_out: true`
is the positive marker that the command did not exit.

**Rejected alternatives.** *Keep `exit_status: -1` and add `timed_out` beside it*,
because then `-1` is still a lie about the wait status, and a reader who only
looks at `exit_status` still cannot tell SIGHUP from a deadline. *Record the
wait status after SIGKILL (`-9`) plus `timed_out`*, because that status describes
the harness's kill, not the client, and a failed wait still has no integer to
put there. *Use a non-integer `exit_status` (`null` or `"timed-out"`)*, because
the schema subset this repository interprets has no union types, and a string
status would invalidate the "integer wait status" reading of every existing
entry. *Bump to schema version 3*, because the new field is additive and every
committed record still validates as version 2.

**Consequence to expect.** A blocked stage's last `commands` entry is often
`{"command": "...", "timed_out": true}` with no `exit_status`. Operators filling
the public record from the private transcript will see the same shape there;
copying `-1` into a matrix as a deadline marker is now a validator failure only
when `timed_out` is also present, and is SIGHUP when it is not.

**Revisit when.** A command needs to record both that the deadline fired and the
wait status the kill actually produced.

**Refs.** `schemas/compatibility-matrix.schema.json`,
`scripts/assess_clients.py` (`StageCommand`, `CommandTranscript`),
`scripts/check_compatibility_matrix.py` (`_command_ending_problems`),
`tests/test_assess_clients.py` (`test_a_command_terminated_by_sighup_is_not_recorded_as_a_deadline`),
`tests/test_check_compatibility_matrix.py` (`PerCommandStatusRecordTest`).

### A supplied run directory is still a fresh run directory

**Author.** Jeff Cox and Grok

**Decision.** `assess` still takes an optional `run_directory` so the write path and
the announced path are one value. A supplied path must exist as a directory, must
be empty, and when a workspace is also given must be a subdirectory of it, not
the workspace itself. The caller still allocates; this check is the invariant
`allocate_run_directory` already established, applied to the parameter that used
to skip it.

**Rationale.** The parameter was added so two call sites would not derive one path.
Accepting any truthy path meant a caller could hand `assess` a directory that
already held a previous run's package copies and transcript, mix two assessments,
and overwrite the first transcript through `write_private`. That is the
one-run-one-directory evidence boundary, routed around.

**Rejected alternatives.** *Refuse a supplied path that already exists*, because
`allocate_run_directory` creates the directory before passing it in, so existence
is the happy path; emptiness is the freshness test. *Delete the parameter and
return the path from `assess`*, which is the alternative the previous decision
rejected, and which would churn every caller to fix a missing check. *Trust
`copytree` to fail if a per-client copy already exists*, because a second run
that assessed a different client would not collide on that copy and would still
overwrite the transcript.

**Consequence to expect.** Tests that pass `run_directory` must create an empty
directory first, matching `main`. A reused `--workspace` still accumulates
`run-NNN` directories; only a caller that names a dirty one is refused.

**Revisit when.** More than one artifact has to be announced, at which point a
small run-context object still beats a widening parameter list.

**Refs.** `scripts/assess_clients.py` (`require_fresh_run_directory`, `assess`),
`tests/test_assess_clients.py` (`WorkspaceFreshnessTest`),
[the caller-allocates decision](#the-caller-that-has-to-name-the-run-directory-is-the-caller-that-allocates-it),
[the one-run-one-directory decision](#every-assessment-run-gets-its-own-directory-and-every-client-its-own-package-copy).

## 2026-08-23

### A command that hit the deadline is recorded like any other command

**Author.** Jeff Cox and Claude

**Superseded 2026-08-24.** The command still goes in `commands` and is still
safety-graded. The representation is no longer `exit_status: -1`: that value is
SIGHUP. See [A deadline-killed command is marked timed out, not given a fake exit
status](#a-deadline-killed-command-is-marked-timed-out-not-given-a-fake-exit-status).

**Decision.** When a stage's command reaches its deadline, that command is appended to the
stage's `commands` list with `exit_status: -1`, alongside its entry in the private transcript.
It is therefore in the public version-2 record and is graded by the post-run safety rule like
every other recorded command. `-1` is reserved for "killed at the deadline, never exited"; no
real exit status can say that.

**Rationale.** The stage started it, so it ran. Keeping it only in the private transcript left
the public record naming fewer commands than the stage started — unreproducible — and left the
safety rule, which grades `commands`, blind to the single command most likely to have been doing
something unbounded. A record that omits the command that hung is a record that reads best
exactly when the run went worst.

**Rejected alternatives.** *Omitting `exit_status` for that entry*, because the schema requires
an integer and an absent field would read as "not recorded" rather than "did not exit".
*Recording it only when the stage is blocked for some other reason*, because the deadline is the
common case. *Grading safety only on `executed` stages*, because a blocked stage's commands
started.

**Consequence to expect.** A blocked stage can carry more `commands` entries than it has
`returncodes`; the per-command statuses are the reproducible record and the returncodes are what
classified the stage.

**Revisit when.** The schema gains a way to mark a command as terminated rather than exited.

**Refs.** `scripts/assess_clients.py`, `schemas/compatibility-matrix.schema.json`,
`tests/test_check_compatibility_matrix.py` (`PerCommandStatusRecordTest`).

### The caller that has to name the run directory is the caller that allocates it

**Author.** Jeff Cox and Claude

**Decision.** `assess` takes an optional `run_directory`. The command line allocates it and
passes it in, so the path the transcript is written to and the path the closing message
announces are the same value rather than two computations that agree by convention. `assess`
still allocates one itself when no caller supplies it, which is what every test relies on.

**Rationale.** The run-directory repair moved the transcript into `<workspace>/run-NNN/` and the
message went on naming `<workspace>/`, so every executed assessment sent the operator to a file
that did not exist — and the transcript is the only place the record's blank versions, reasons,
and evidence can be filled from. Two call sites deriving one path is the arrangement that
allowed them to disagree; passing the value removes the second derivation rather than fixing it.

**Rejected alternatives.** *Putting the run directory in the record*, because the record is
public evidence and a local filesystem path does not belong in it. *Returning a tuple from
`assess`*, because every caller and test would change to carry a value only one of them wants.
*Recomputing the newest `run-NNN` in the command line*, because it re-derives what was already
decided and is wrong the moment two runs share a workspace.

**Consequence to expect.** A caller that needs the path must allocate before assessing, which is
one line and makes the ordering explicit.

**Extended 2026-08-24.** Naming the directory does not exempt it from being a fresh one.
See [A supplied run directory is still a fresh run directory](#a-supplied-run-directory-is-still-a-fresh-run-directory).

**Revisit when.** More than one artifact has to be announced, at which point a small run-context
object beats a widening parameter list.

**Refs.** `scripts/assess_clients.py` (`assess`, `main`), `tests/test_assess_clients.py`
(`CommandLineTest`),
[the producer-and-consumer learning](LEARNINGS.md#both-regressions-updated-the-producer-and-left-the-consumer-behind).

### A mutation proof excludes its own binding test, and is never corrected by hand

**Author.** Jeff Cox and Claude

**Decision.** The mutation runner excludes `MutationProofBindingTest` from grading entirely —
at baseline and under every mutation — and counts a mutation killed only when it fails some
other test that was passing at baseline. It records the baseline failure set first and aborts
if anything outside that binding test is failing. The published proof states the exclusion in
its header. When an anchor no longer matches exactly once, the run aborts, the files are
restored, the anchor is rewritten to name the guard in its current form, and the whole set is
re-run; a pre-flight pass checks every anchor before the expensive run begins.

**Rationale.** Every mutation edits a graded file, which changes its digest, which fails the
binding test. Counting that as a kill made every mutation a kill by construction, and cycle
11's "0 survivors" was measuring the runner's own bookkeeping. Re-graded with the exclusion,
seven anchors had no test behind them. Separately, the binding test cannot pass until the run
it describes is published, so demanding a green baseline created exactly one route to one —
editing the previous cycle's recorded digests, which is the cycle-7 defect that test exists to
catch.

**Rejected alternatives.** *Excluding the binding test from the suite the runner invokes*,
because the exclusion then stops being visible in the published proof. *Writing the expected
digests into the evidence file before the run*, because a proof whose digest block was authored
rather than computed identifies nothing. *Publishing a partial pass and appending the remaining
mutations afterwards*, because the digests would name a tree no single run exercised.
*Excluding only the binding subtests that fail at baseline*, because that still lets the test
kill a mutation to any graded file whose digest currently matches — which is every graded file
the round did not change.

**Consequence to expect.** Every code change to a graded file costs a full re-run of the proof,
roughly forty minutes, before the suite can be green again. A survivor count above zero is now
a real finding rather than a broken run.

**Revisit when.** The suite grows a second test that cannot pass until the artifact it checks
is published, or the graded set grows enough that the run stops fitting in one sitting.

**Refs.** `tests/test_site_profile.py` (`MutationProofBindingTest`),
`docs/evidence/2026-08-23-cycle12-mutation-proof-portable-copies.txt`,
[the vacuous-proof learning](LEARNINGS.md#the-mutation-proof-counted-its-own-bookkeeping-as-a-kill).

### A client's real executable is supplied by the operator, never discovered

**Author.** Jeff Cox and Claude

**Decision.** Two of the ten clients launch through a local auto-trust wrapper that finds its
real binary through the client home, and that lookup fails under the isolated home the harness
gives it. `resolve_real_binary` takes the real path from `--real-binary NAME=PATH` for the run,
or from the wrapper's own documented override already exported in the operator's environment.
With neither, the client is `blocked` with the requirement named. The harness never searches
`PATH` for it, and refuses a supplied path that is the same file as the launcher on `PATH`.

**Rationale.** Nothing on disk distinguishes a launcher from the thing it launches. The first
version resolved the value with `which`, which returns the wrapper — the wrapper is what sits on
`PATH` under that name — so the wrapper exec'd itself and spawned descendants until the host ran
out. The repair took the first `PATH` entry that was not the *same file* as the wrapper, which a
second *copy* of the wrapper satisfies: the same defect one arrangement further out. Both
attempts guess which of several same-named executables is "the real one", and that guess cannot
be made correct — only made to look correct on the machine it was tried on.

**Rejected alternatives.** *Comparing file size or reading the first line*, because a wrapper
that grows or loses its shebang defeats it and nothing announces that it has. *Skipping the two
clients*, because their support status is exactly what the assessment exists to establish.
*Guessing and capping the recursion depth*, because a bounded process bomb is still a process
bomb and the record it produces describes the cap, not the client.

**Consequence to expect.** An operator who has never exported the override sees two clients
`blocked` naming the variable, not two clients silently assessed against a wrapper.

**Revisit when.** A wrapper ships a documented, machine-readable way to name its real target.

**Refs.** `scripts/assess_clients.py` (`resolve_real_binary`), `tests/test_assess_clients.py`
(`RealBinaryResolutionTest`),
[the wrapper learning](LEARNINGS.md#a-wrapper-resolved-by-name-resolves-to-itself).

### Every assessment run gets its own directory, and every client its own package copy

**Author.** Jeff Cox and Claude

**Decision.** `--workspace` names a place runs live in, not a place a run owns.
`allocate_run_directory` claims `run-001`, `run-002`, … inside it with `exist_ok=False`, and
each client's package copy is made unconditionally into that new directory. Copying is never
skipped because the destination already exists.

**Rationale.** The record binds itself to the shipped package fingerprint. An operator pointing
`--workspace` at the same place on every run is the normal case, and a conditional copy handed
the next run whatever the last one left — including a copy a client had installed into. That
tree then assessed as if it were the shipped package while the record went on naming the shipped
digest, which is a record that identifies the wrong bytes. Numbered rather than random so a
returning operator can tell which run is which.

Two guards cover one defect here, deliberately. The fresh directory makes the collision
impossible and the unconditional copy refuses it if it happens anyway; the second is what
survives someone changing the first.

**Rejected alternatives.** *Reusing a copy that still matches the fingerprint*, because it makes
the guarantee depend on a check that the reuse exists to skip. *Deleting the workspace at
start*, because it destroys the previous run's transcript, which is the only place raw client
output is kept. *A temporary directory per run*, because the operator cannot find it afterwards
and the transcript has to be found.

**Consequence to expect.** Repeated runs accumulate `run-NNN` directories the operator prunes
deliberately; disk is spent to keep every run's evidence separable.

**Revisit when.** The workspace layout has to be shared with another tool that expects a fixed
path.

**Refs.** `scripts/assess_clients.py` (`allocate_run_directory`),
`tests/test_assess_clients.py` (`WorkspaceFreshnessTest`).

### The port descriptor is closed, and its safety fields are stated rather than defaulted

**Author.** Jeff Cox and Claude

**Decision.** Every object in a port descriptor refuses keys the contract does not define, and the
four `assessment` fields that carry a safety decision — `credential_prefixes`, `package_scripts`,
`mutating_operations`, `entrypoints` — must each be stated. A package for which one is genuinely
empty writes it as an empty list *and* names it in `assessment.declared_none`. The descriptor version
advanced to `2`; version 1 is not accepted, because a descriptor written against it has exactly the
shape this closes.

`assessment.entrypoints` is also new, and is deliberately independent of the `custody` table: what
makes a file executable is that the package says it is, not how its bytes were obtained.

**Rationale.** Each of those four fields fails *open* when empty, and "absent" and "empty" were the
same state. `credential_prefix` for `credential_prefixes` validated, loaded, passed the repository
gate, and stripped nothing — the cheapest possible mistake buying the most expensive possible
outcome. Reading entrypoints out of `custody.entrypoint_transforms` had the narrower version of the
same problem: a package whose executable is an upstream byte copy had no assessable entrypoint, so
the "package-agnostic" harness only ever worked for one custody layout.

**Rejected alternatives.** *Warning on an unknown key*, because a warning in a tool nobody watches is
a comment. *Defaulting the safety fields and documenting that they matter*, because documentation is
not a gate and the failure is silent. *Inferring an empty field as deliberate*, because that is
indistinguishable from a typo, which is the whole defect. *Accepting version 1 leniently for
migration*, because the un-migrated package is precisely the one still carrying the hole.

**Consequence to expect.** Adding a package is more verbose: four safety fields must be written even
when three are empty. That verbosity is the point — the empty case is now something a person decided
and a reader can see.

**Revisit when.** A safety field is added or retired, or a package needs a per-field exemption the
`declared_none` list cannot express.

**Refs.** `scripts/port_config.py`, `ports/README.md`, `tests/test_port_config.py`,
[the learning](LEARNINGS.md#an-optional-safety-setting-is-a-safety-setting-that-is-off).

### A compatibility record stores every command a stage ran, beside its own exit status

**Author.** Jeff Cox and Claude

**Decision.** The compatibility-matrix record advances to `schema_version` 2. An executed stage
carries `commands`: every argv it ran, redacted, each with its own `exit_status`. `command` remains
the first of those, so a row still reads as version 1 did. Version 1 records stay valid and keep
being validated; a version 1 record carrying `commands` is refused, and a version 2 executed stage
without them is refused.

**Rationale.** A stage runs one command per skill unit, or one per entrypoint. Recording only the
first made the command and status cardinalities disagree: a reader saw `exit status 0, 7` with one
command and could neither tell which failed nor reproduce it. The nine committed matrices are
evidence and are not rewritten, so the version is what separates the two shapes rather than a
migration.

**Rejected alternatives.** *Keeping one command and listing statuses in prose*, which is the
disagreement itself. *Rewriting the committed matrices to the new shape*, because editing evidence to
match a moved tree is the anti-pattern the runbook names. *Making `commands` optional in version 2*,
because an optional record of what ran is a record that can omit the command that failed.

**Consequence to expect.** The matrix safety rule now grades every recorded command rather than the
first, so a mutating command in second position is caught.

**Extended 2026-08-24.** `command` remains the first of `commands` whenever both are present,
including on blocked stages; the validator used to skip that alias check on every
non-executed stage. A command that did not exit now carries `timed_out` instead of a
fake `exit_status`; see [A deadline-killed command is marked timed out, not given a
fake exit status](#a-deadline-killed-command-is-marked-timed-out-not-given-a-fake-exit-status).

**Revisit when.** A command entry needs a third ending besides `exit_status` and `timed_out`.

**Refs.** `schemas/compatibility-matrix.schema.json`,
`scripts/check_compatibility_matrix.py` (`check_record_version`), `scripts/assess_clients.py`.

### Raw client output is kept for the operator and kept out of the record

**Author.** Jeff Cox and Claude

**Decision.** Each command's stdout and stderr are retained, bounded at 64 KiB with truncation marked,
in a private `transcript.json` written into the run workspace. The public compatibility record never
quotes it and never names its path. The operator writes each row's `version`, `reason`, and `evidence`
from that transcript.

**Rationale.** The public record carries field names, counts, and comparisons — raw client output is
none of those and is not redacted. But discarding it left the operator nothing to write the record
*from*, which meant the scripted method could not produce the matrix the prose method did. Both
constraints are real; they are satisfied by two artifacts, not by one compromise.

**Rejected alternatives.** *Putting bounded output in the record*, because it is unredacted by
construction. *Printing it to the terminal only*, because a ten-client run's output does not survive
a scrollback. *Keeping it unbounded*, because one loud client should not fill the operator's disk.

**Consequence to expect.** The run workspace holds site-identifying text and must not be committed.
The runbook and `--workspace` help both say so.

**Revisit when.** A redaction pass over raw output becomes trustworthy enough to put a bounded
excerpt in the record itself.

**Refs.** `scripts/assess_clients.py` (`CommandTranscript`, `transcript_path`),
`docs/runbooks/portable-plugin-port.md`.

### Package identity is a descriptor under `ports/`, not a constant in a tool

**Author.** Jeff Cox and Claude

**Decision.** Every portable package carries one JSON descriptor at
`ports/<package>.json` holding its identity, its package root, its upstream source, its
custody table, its assessment settings, and the provenance notes its `PROVENANCE.json`
is generated from. `scripts/sync_vendor_source.py` takes `--package NAME`;
`scripts/check_compatibility_matrix.py` resolves the package from the record's own
`$.package.name`; `scripts/assess_clients.py` reads the entrypoints, skill units, and
credential prefixes from the same file. `scripts/port_config.py` is the single authority
for the format and validates it. `scripts/check_repo.py` fails when a descriptor does
not load or names a tree that does not exist.

This closes the revisit condition recorded under "Bind a current matrix to the tree it
assessed": the single `PACKAGE_ROOT` constant is now per-record.

**Rationale.** The pilot's runbook had to tell the next porter which constants to reach
into inside which two scripts. That is an instruction that rots, and it made "is this
tool generic?" a question about someone's diligence rather than about the code. As data,
the same information is validated on load, checked by the repository gate, and readable
by a third tool that did not exist when the first two were written.

The descriptors live *outside* `plugins/` deliberately. A compatibility matrix binds to a
fingerprint of the package tree, so a descriptor stored inside the tree it describes would
move that fingerprint whenever the tooling's configuration changed and invalidate
assessment evidence that is still true.

**Rejected alternatives.** *A second JSON schema file describing the descriptor*, because
a rule written twice is a rule that can disagree with itself; `port_config.py` validates
and `tests/test_port_config.py` derives its corpus from that module. *A descriptor inside
the package*, for the fingerprint reason above. *Defaulting `--package` to the first
package*, because a tool that overwrites a tree and deletes stale paths inside it should
name the tree out loud, and a default makes the first-ported package the silent one.
*Deriving the matrix's package root from a CLI flag rather than from the record*, because
the record already names the package it assessed and a flag lets the two disagree.

**Consequence to expect.** Porting a package is a new descriptor plus a review of it,
rather than edits inside two scripts. A descriptor with an empty
`assessment.package_scripts` would scope the mutating-operation safety rule to nothing,
which is a fail-open; a test asserts the shipped list names files the package carries.

**Revisit when.** A third tool needs package-specific settings that do not fit these
fields, or a package needs two descriptors (two upstream sources into one tree).

**Refs.** `scripts/port_config.py`, `ports/README.md`, `tests/test_port_config.py`,
[the queued Fleet Core target](QUEUED.md).

### The ten-client assessment is a program, and it refuses rather than guesses

**Author.** Jeff Cox and Claude

**Decision.** `scripts/assess_clients.py` carries the ten-client roster, the four stages,
and every client quirk. It runs nothing unless `--execute` is passed; it strips the
package's declared credential variables from every subprocess; it routes every stage argv
through `check_compatibility_matrix.command_safety_problems` *before* starting the
process; it gives every stage a deadline; it refuses a state-writing stage under the
operator's own home and refuses the isolated-only client a real home outright; and it
refuses to emit a record at all if the assessed tree moved during the run.

The record it emits is deliberately incomplete: each client's `reason` is empty, and
`check_compatibility_matrix.py` refuses a row with no concrete reason. A record no one
finished reading therefore cannot be committed as evidence.

**Rationale.** The status a harness computes is a proposal from stage results. The reason
is a claim about *why*, which only the person who watched it can make. Filling it in
automatically would produce records that pass every check and assert things nobody
observed — the precise failure the fingerprint binding exists to catch, moved one level up.

**Rejected alternatives.** *Executing by default*, because the first thing this program
does is install software into directories. *Deriving the overall status and stopping*,
because a status without a reason is not evidence. *Recording a client's actionable
refusal as `blocked`*, because the attempt ran and the client named the missing artifact;
that is the Codex row's entire value. *A second copy of the mutating-operation predicate
inside the harness*, because a rule enforced before the fact by one copy and after the
fact by another can be satisfied by neither when they disagree.

**Consequence to expect.** A stage whose client is not installed is `blocked` with the
binary named, never a package failure. A stage that hits its deadline is `blocked` with
the deadline named.

**Revisit when.** A client needs a stage vocabulary the four stages cannot express, or the
roster changes.

**Refs.** `scripts/assess_clients.py`, `tests/test_assess_clients.py`,
[the stdin learning](LEARNINGS.md#a-harness-that-inherits-stdin-behaves-differently-in-a-terminal-than-under-a-scheduler).

### Review rounds are bounded at three, and a round's repairs ship as one release

**Author.** Jeff Cox and Claude

**Decision.** A port under independent review gets at most three review rounds
against a frozen candidate. Every confirmed finding from a round is batched into a
single repair and a single release, and the fingerprint-bound evidence is re-run
once per round rather than once per defect. If the third round still returns
`repairs_requested`, work stops and the residual findings go to the operator with
their evidence, rather than a fourth round beginning on the coordinator's own
authority.

**Rationale.** The UniFi pilot ran nine rounds and shipped one defect per release.
Because the compatibility matrix and the post-activation readback are bound to the
package fingerprint by test, each release invalidated both: nine ten-client matrix
runs and eight readback captures for one port. Batching cycles 4 through 8 into
one repair per round would have produced roughly two of those runs instead of six.

The round bound is a separate lever from the batching and addresses a different
failure. Rounds four through nine were all one rule, and the coordinator kept
authorising its own next attempt because each round produced a real finding. A
real finding is not evidence that another unattended round is the right response;
after three, the operator is better placed to judge whether the rule needs a
different approach than another repair.

**Rejected alternatives.**

- *Leave both unbounded, as the pilot ran.* This is the status quo that produced
  the numbers above. Its one merit — every defect found is fixed immediately — is
  preserved by batching, which fixes them all, just together.
- *Bound the rounds but keep per-defect releases.* Keeps the evidence multiplier,
  which is where the mechanical time actually went.
- *Weaken the fingerprint binding so evidence survives a byte change.* Rejected
  outright. That binding caught stale evidence repeatedly across the pilot and is
  the reason the final record can be trusted. The cost is real and the answer is
  fewer releases, not weaker evidence.
- *Batch across rounds as well, reviewing only once at the end.* Discards the
  independent check on each repair, which is what caught the two class-level
  defects.

**Exception.** A confirmed fail-open in a security rule is repaired and re-reviewed
on its own, not batched. Holding a known-exploitable gap to fill a batch trades
the wrong thing.

**Revisit when.** A port hits the three-round bound twice, or a round's batch grows
large enough that a reviewer cannot attribute a regression to a specific repair. The
first says the bound is too tight for the work; the second says the batch is too
coarse, and the batch should split before the bound moves.


## 2026-08-22

### Compatibility evidence is captured on the floor interpreter, by explicit path

**Author.** Jeff Cox and Claude

**Decision.** Every command in the compatibility matrix's invocation stage and in
the post-activation readback runs on the interpreter the catalog declares as its
minimum — `python3.12` today — named by explicit path, never as `python3`. The
recorded commands say `python3.12` so a reader can see which interpreter produced
the numbers.

**Rationale.** The catalog declares `python>=3.12`. Evidence gathered on a later
interpreter supports a claim about that later interpreter and nothing about the
floor. This is not hypothetical here: the two superseded matrices ran on CPython
3.14 and recorded 29 and 21 lines of usage text, where the floor interpreter
prints 30 and 22 for the very same bytes. Had a floor break existed, the same
setup would have reported green.

**Rejected alternatives.**

- *Run on `python3` and note the version in prose.* This is what the earlier
  matrices did, and both had to add a paragraph saying the floor case was not
  shown. A limitation that has to be written down every time is a defect in the
  method, not a caveat.
- *Run on both the floor and the default interpreter.* Twice the stages for a
  claim nobody makes. Every later interpreter is in contract by construction; the
  interesting boundary is the minimum, and only the minimum is promised.
- *Add a `python_version` field to the matrix schema.* The schema is closed by
  design and its `method` object is closed too. The interpreter is recorded in
  `method.isolation` and in every invocation stage's evidence string, which keeps
  one schema rather than growing one per fact.

**Revisit when.** The declared floor moves. The floor lives in
`tests/test_python_floor.py` as `PYTHON_FLOOR`; when it changes, the interpreter
used to capture evidence changes with it, and the evidence has to be re-captured
rather than re-labelled.

### The portable catalog's minimum supported Python is `python>=3.12`

**Author.** Jeff Cox and Claude

**Decision.** The portable catalog declares a minimum supported Python of
`python>=3.12`. This is a minimum, not a pin: every later interpreter is in
contract, and nothing here promises 3.10 or 3.11 any more. Raising the floor
above 3.12 is a separate operator decision and is not taken here.

The floor is stated once, as the constant in
[`tests/test_python_floor.py`](../../tests/test_python_floor.py), and every
place the catalog declares it is checked against that constant: the
continuous-integration interpreter pin in
[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), the repository
[`README.md`](../../README.md), the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
the Fleet Core package [README](../../plugins/fleet-core/README.md) and
[changelog](../../plugins/fleet-core/CHANGELOG.md), and this entry. A portable
skill that declares a `compatibility` value must declare this one. The gate also
fails when any of those files stops stating a floor at all, so the check cannot
be defeated by deleting a declaration, and it fails on any `python>=` version
token anywhere in the repository that names a different version.

The ported-plugin continuous-integration job now pins `3.12` rather than `3.10`,
because a floor that is never exercised is not a floor and the only interpreter
that job can usefully prove is the lowest one the contract admits.

**Rejected alternatives.** *Keeping a 3.10 floor and repairing the import
upstream.* The one-line upstream repair is real and available, but it answers
the wrong question. Nothing ever proved a 3.10 floor: the ten-client
compatibility assessment ran every stage on an interpreter well above it, so the
3.10 case was never observed, and the claim rested on reading the lowest
interpreter the ported bytes happened to parse under. Repairing this import
would restore a promise the catalog still could not keep and would leave the
next 3.12-era API to break it again.

*Pinning exactly 3.12.* That would refuse interpreters the authoritative source
supports and would turn every later Python release into a catalog-wide edit.

*Moving the floor to 3.11, the minimum the broken import actually required.*
That is a floor derived from one accident of one byte copy rather than from the
source's own contract, and it would have to move again on the next one.

*Leaving the declarations as separate hand-maintained strings.* The floor was
already stated in at least five places and had already fallen out of agreement
with the code it described. Prose that is not checked is not a contract.

**Rationale.** The authoritative source repository,
`infiquetra-claude-plugins`, declares `requires-python = ">=3.12"` in its
project file and pins `python-version: "3.12"` in every one of its
continuous-integration jobs. Both statements were read at commit `ed72f439`,
the revision both packages in this catalog are derived from, and at the head of
that repository's default branch. A derived catalog must not promise more
compatibility than the source it is derived from. Where it does, the promise is
not merely unproven, it is unprovable: this repository does not own the bytes,
cannot test them on the interpreter it advertises, and inherits whatever
interpreter requirement upstream adopts on the next synchronization.

This cycle demonstrated the failure end to end. Re-synchronizing the Fleet Core
slice to 0.25.1 brought in `from datetime import UTC`, which exists only on
Python 3.11 and newer. The digest check passed, because the bytes really were
identical to their source; the derived package silently stopped running on the
floor its own documentation advertised. Aligning the floor with the source
removes the class of failure rather than the one instance of it.

**Supersedes.** The plan's KTD7 in its original form, which derived a 3.10 floor
from a bare union annotation evaluated at definition time. That reasoning is
preserved in the plan rather than deleted. It established a lower bound on what
the ported code parses under; it was never a statement of what the catalog
supports, and the two came apart on the first re-synchronization.

**Known gap, recorded rather than closed.** KTD7 also claimed the floor is
declared in the skills' `compatibility` frontmatter. It never was, and it cannot
be added here: both portable `SKILL.md` documents are classified
`upstream-byte-copy`, so an added field would break digest equality with their
source and would move the assessed package's tree fingerprint, retiring the
ten-client matrix bound to it. Nothing under `plugins/unifi/` was touched by
this decision for that reason. The declaration is
[queued as upstream work](QUEUED.md).

**Revisit when.** The authoritative source raises or lowers its own
`requires-python`, or this catalog acquires a package whose source declares a
different floor from the rest — at which point one catalog-wide floor stops
being the right shape and the check has to become per-package.

**Refs.** [Pilot plan KTD7](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[the floor gate](../../tests/test_python_floor.py),
[the learning this decision answers](LEARNINGS.md#a-byte-copy-imports-the-upstream-platform-floor-along-with-the-upstream-fix),
[the archived queue item](ARCHIVE.md#decide-the-python-floor-the-fleet-core-resync-raised)

---

### The ported test's pytest guard raises SkipTest instead of binding pytest to None

**Author.** Jeff Cox and Claude

**Decision.** The `guard-pytest-import` deterministic transform over
`tests/test_retry_backoff.py` moves to version 2. Where version 1 bound the name
`pytest` to `None` when the dependency was absent, version 2 raises
`unittest.SkipTest`. Everything else about the rule is unchanged: the upstream
module docstring is still replaced with one recording the port, and every line
from `class RateError(Exception):` to end of file is still copied byte for byte.

**Rejected alternatives.** Keeping version 1, because Fleet Core 0.25.1 brought
two tests carrying `@pytest.mark.parametrize` and a decorator is evaluated when
the module is imported: against `None` it raises `AttributeError`, so the
dependency-free baseline job would fail on a module it never intended to run.
Substituting a hand-written stub object exposing `mark.parametrize` and
`raises`, because a fake that silently absorbs whatever the upstream suite
reaches for is a lie in a file whose entire purpose is to be a faithful copy,
and it would need extending every time upstream uses one more pytest feature.
Dropping the ported test from the hermetic job by renaming it out of the
`test*.py` pattern, because the discovery pattern is not this package's to
redefine and a test nothing collects is a test nobody notices breaking.

**Rationale.** `unittest` catches `SkipTest` raised during module import and
records the module as one skipped test, so the baseline job stays green, exits
0, and says out loud why it collected nothing there — verified directly rather
than assumed. The plugin job, where pytest is installed, runs all eighteen test
functions unchanged, which pytest expands to twenty-five cases. The guard also
stops being a maintenance liability: it no longer has to be revisited each time
upstream reaches for another pytest feature at module scope.

**Revisit when.** The hermetic baseline job gains pytest, which would make the
guard dead code, or upstream splits its suite so the ported half no longer needs
pytest at all.

**Refs.** [`plugins/fleet-core/PROVENANCE.json`](../../plugins/fleet-core/PROVENANCE.json),
[the 0.25.1 changelog entry](../../plugins/fleet-core/CHANGELOG.md)

### A re-synchronization does not renumber the evidence it invalidates

**Author.** Jeff Cox and Claude

**Decision.** The Fleet Core 0.25.1 re-synchronization left
[`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../evidence/2026-08-22-unifi-compatibility-matrix.md)
and
[`docs/evidence/2026-08-22-unifi-post-activation-readback.md`](../evidence/2026-08-22-unifi-post-activation-readback.md)
untouched, and shipped with the eight binding tests over them failing. The
recorded fingerprints still name the tree those assessments actually ran
against.

**Rejected alternatives.** Writing the new tree digest into both documents,
because the matrix states the rule in its own text — "Refreshing the numbers
without re-running the assessment is precisely the failure this binding exists
to catch" — and doing it by hand rather than by a flag does not make it a
different act. It would turn forty observed stage results and ten client
readbacks into claims about bytes nobody ran. Marking the current matrix
superseded, because the supersession contract requires a named successor that is
itself current, and no successor exists until someone re-runs the ten clients.
Reverting the bundle regeneration to keep the digest still, because a consumer
carrying a stale copy of a repaired rate-limit primitive is the actual defect
this whole re-synchronization exists to remove.

**Rationale.** The binding is not misfiring. Bundling puts a stamped Fleet Core
module inside the UniFi package, so a Fleet Core release necessarily changes the
UniFi tree digest, and the document correctly reports that it no longer
describes what ships. Red is the accurate state, and a red check that names real
work still owed is worth more than a green one bought by editing the number
under comparison.

**Revisit when.** The operator authorizes the ten-client re-run and the
post-activation readback; the new matrix is published as current and the present
one is marked superseded by it, which is the only path that clears these eight
tests honestly.

**Refs.** [Queued evidence re-run](QUEUED.md#re-run-the-ten-client-matrix-and-the-readback-against-the-resynced-package),
[the learning](LEARNINGS.md#regenerating-a-build-artifact-retires-the-observational-evidence-bound-to-it)

### The portable UniFi README is target-owned, rewritten site-neutral

**Author.** Jeff Cox

**Decision.** `plugins/unifi/README.md` is target-owned portable source. It
describes this package: the Agent Plugins 1.0 layout, the
`com.infiquetra.claude/` client extension directory, the Fleet Core bundle,
site-profile resolution, and commands that run in this repository. It is not
an upstream byte copy of the Claude plugin README, and it is not produced by a
deterministic transform of that file.

**Rejected alternatives.** Keeping the file as `upstream-byte-copy`, because
that is the classification that shipped Cursor F-07: a consumer opening the
portable package's own documentation was told it was a Claude Code plugin and
was given pytest paths this repository does not contain. Authoring a
`portable-readme` transform in `scripts/sync_vendor_source.py`, because that
script is owned by the concurrent C8 repair (path-safety) and a transform
would still be defined over a Claude-specific source document whose subject is
the wrong package. Repairing the upstream README so a byte copy becomes
portable, because this run must not edit another repository.

**Rationale.** The pilot plan already assigned the README "portable core,
rewritten site-neutral". Claude-only installation belongs in the adapter
directory. A later `synchronize()` that still lists `README.md` in
`PORTABLE_BYTE_COPIES` would restore the Claude lede; `tests/test_unifi_readme.py`
fails closed on that restoration (lede identity, absent test modules, and the
provenance classification). Dropping the path from the sync table is queued
rather than taken here, because that tuple lives in a file this unit does not
own.

**Revisit when.** The next UniFi synchronization is authorized, or the C8 unit
(or a follow-up) removes `README.md` from `PORTABLE_BYTE_COPIES` so a
deliberate resync preserves the portable README instead of fighting the test.

**Refs.** [Queued sync-table residual](QUEUED.md#drop-readme-from-the-unifi-byte-copy-table-so-a-resync-keeps-the-portable-docs),
[byte-copy README learning](LEARNINGS.md#a-byte-copied-readme-describes-the-source-package-not-the-derived-one),
[pilot plan custody table](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Pause the pilot at the compatibility matrix and take no client-specific remediation

**Author.** Jeff Cox and Claude

**Decision.** The portability pilot stops at the completed ten-client compatibility
matrix. Two clients did not consume the portable package: OpenAI Codex is recorded as
works through an adapter, and Cursor Agent is recorded as failed. Neither is repaired
here. Whether a given client warrants a repair, an adapter, a different distribution path,
or an explicitly unsupported status is one operator decision per client, and each is taken
separately from this work. The package-side defect that leaves the assembled package with
no working entrypoint is recorded in the same way and is likewise not repaired here.

**Rejected alternatives.** Building the Codex marketplace manifest immediately, because
the matrix would then be reporting on a package that had been changed to make it pass, and
the assessment exists to say what was true of the package as assembled. Dropping the two
non-consuming clients from the matrix, because coverage was the deliverable and a client
recorded as unsupported or failed with its reason is a result, not a gap. Repairing the
missing bundle inside this unit, because a defect found by an assessment is scope the
assessment discovered, not scope it was granted.

**Rationale.** Implementation scope that expands itself the moment it finds a problem
stops being a scope. The matrix was built to inform a decision, and taking the decision
inside the same unit that produced the evidence removes the operator from a choice that is
theirs. Coverage was mandatory and passing was not, which is only true if failures end in
a pause rather than in a repair.

**Revisit when.** The operator has taken the per-client decisions, or the package
entrypoint defect is separately authorized for repair.

**Refs.** [Compatibility matrix](../evidence/2026-08-22-unifi-compatibility-matrix.md),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[per-client queued decision](QUEUED.md#decide-per-client-what-follows-the-compatibility-matrix),
[queued entrypoint repair](QUEUED.md#emit-the-declared-fleet-core-bundle-so-the-package-has-a-working-entrypoint)

---

### Leave the portable profile resolution order at two rungs and close the Infiquetra gap in deployment

**Author.** Jeff Cox and Claude

**Decision.** The portable site-profile contract keeps resolving exactly two rungs, the
`UNIFI_SITE_PROFILE` environment variable and then the path remembered in `config.json`,
followed by no profile at all. The documented deployed runtime default,
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json`, is not added as a
third rung by this work. The Infiquetra instance closes its own gap in the private
`home-lab` repository, where the Ansible deployment now also writes `config.json` so the
remembered rung resolves the file it just deployed. The general fix stays queued.

**Rejected alternatives.** Adding the default path as a final rung inside this pilot,
because it changes what an already-deployed host resolves and therefore touches the
portable contract, both consumers of it, and the Claude adapter's loader with their tests
— a contract change that deserves its own unit rather than a fix smuggled into a
documentation unit. Making the environment variable mandatory, which would delete the
optional-profile promise the contract exists to keep. Documenting the trap and leaving it
at that, because a documented trap is still a trap.

**Rationale.** The portable contract and the Infiquetra custody instance are separable on
purpose. This repository's normative documentation never presents the private `home-lab`
plus Ansible arrangement as required; it is one operator's deployment of an optional
profile. That separation is exactly what allows the operator's own gap to be closed in
their deployment today while the portable question stays open for a decision that affects
every other operator.

**Revisit when.** A second operator deploys a site profile on a host this repository does
not control, or the queued contract change is authorized.

**Refs.** [Queued contract change](QUEUED.md#the-documented-default-site-profile-runtime-path-is-never-read),
[seam learning](LEARNINGS.md#every-unit-passed-its-own-tests-and-the-defect-lived-in-the-seam-between-two-correct-units),
[site profile reference](../../plugins/unifi/references/site-profile.md)

---

### Keep a generated file's stamp outside the bytes it hashes

**Author.** Jeff Cox and Claude

**Decision.** A generated Fleet Core bundle carries two independent digests. The
source-payload digest covers the upstream module and detects a stale bundle whose source
has moved. The generated-output digest covers the generated file with its own stamp block
excluded, and detects a hand-edited output. `scripts/check_repo.py` reports the two as
different, deterministic failures.

**Rejected alternatives.** One digest over the whole generated file, which is
self-referential and cannot be computed, since the digest would have to appear inside the
bytes it covers. One digest over the source only, which would leave a hand-edited
generated file undetectable — the exact degradation that turns a generated artifact into
an unmaintained copy-paste fork.

**Rationale.** Stale source and tampered output are different problems with different
repairs. Collapsing them into one mismatch tells a maintainer that something is wrong
without telling them which thing, and a signal that needs investigation before it can be
acted on is a weak signal.

**Revisit when.** A second consumer bundles a Fleet Core module and the two-domain scheme
proves awkward, or a generated artifact appears that has no stable stamp location.

**Refs.** [Bundle declaration schema](../../schemas/fleet-bundle.schema.json),
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md)

---

### Keep repository validation standard-library-only and give the ported plugin tests their own job

**Author.** Jeff Cox and Claude

**Decision.** Continuous integration runs two jobs. The repository validation job installs
nothing and runs `python3 scripts/check_repo.py`, the unittest suite, and `git diff
--check`, so the repository's own baseline uses the standard library alone. A second job
pins the catalog's declared floor, `python>=3.12`, installs `requests`, `urllib3`, and
`pytest` on it, and runs the ported plugin tests. Neither job ever contacts a UniFi controller, and the compatibility matrix is
produced by an operator-run assessment rather than by continuous integration.

**Rejected alternatives.** Rewriting the existing pytest tests into unittest so a single
job could run everything, which would discard proven upstream coverage for no behavioral
gain. Installing dependencies in the one existing job, which would make a package index
outage able to break validation of documentation-only changes.

**Rationale.** The repository's fast hermetic baseline is worth protecting as its own
guarantee: it answers whether this repository is internally consistent, using nothing it
has to download. The ported plugin tests answer a different question and legitimately need
third-party packages, so they get a job whose failures mean what they say.

**Amended 2026-08-22.** The second job's interpreter was pinned to 3.10 when this decision
was written. It now pins the catalog's declared floor, `python>=3.12`, under
[the floor decision](#the-portable-catalogs-minimum-supported-python-is-python312). The
two-job structure this entry decided is unchanged; only the pinned version moved.

**Revisit when.** The ported packages acquire a dependency the second job cannot install,
or the repository grows a project file that makes a single job hermetic again.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[deferred Fleet Core inventory](../../plugins/fleet-core/DEFERRED.md)

---

### Reclassify both UniFi clients as a deterministic transform rather than a byte copy

**Author.** Jeff Cox and Claude

**Decision.** The two client scripts,
`skills/unifi-network/scripts/unifi_network_client.py` and
`skills/unifi-protect/scripts/unifi_protect_client.py`, move from **upstream byte copy**
to **deterministic transform** under requirement R4's three-way path classification. The
rule is `resolve-bundled-fleet-module`, version 1: it matches the single upstream block
that puts the client's own directory on `sys.path`, imports `fleet_commons_shim`, and
calls `fleet_commons_shim.load(NAME)`, and re-emits it as an insertion of the `_bundled/`
directory beside the client followed by a direct `import NAME`. The rule reads the module
name and the binding out of the source rather than assuming them, changes no other byte,
and raises rather than proceeding when the block is absent or appears more than once.
`plugins/unifi/fleet-bundle.json` declares a destination beside each client, which is
where the pilot plan's assembled-package tree already put the generated bundle.

**Rationale.** The portable package drops both `fleet_commons_shim.py` copies, because
their resolution ladder is Claude-specific runtime discovery the portable package must
not retain. A byte copy of a client that imports a module the package does not carry
aborts at module scope, so the package had no working entrypoint on any client. The
byte-copy rule is not a rule about bytes for their own sake: it exists so a downstream
edit cannot become an unrecorded second source. A versioned rule over the pinned upstream
bytes, with the source digest, the output digest, and the rule text in the provenance
manifest, satisfies that purpose exactly -- the output is reproducible from the source
alone, and re-synchronization re-applies the rule rather than silently restoring the
broken import.

**Rejected alternatives.**

- *Repair it upstream first, as the pilot does for every other divergence.* Upstream is
  a Claude package where `fleet_commons_shim` is present and correct. There is no
  upstream defect to repair, so this would mean degrading the Claude package to suit the
  portable one.
- *Copy `fleet_commons_shim.py` into the portable package.* Prohibited: the operator's
  Fleet Core amendment forbids retaining Claude-specific runtime discovery.
- *Require a `FLEET_COMMONS_ROOT` environment variable, or an Agent Plugins dependency
  field.* Both prohibited by the same amendment. The artifact must be complete at install
  time, with no separate Fleet Core installation.
- *Leave the clients as byte copies and document them as not executable.* This is what
  the package already did. A portable package with no runnable entrypoint is not a
  portability result.

**Revisit when.** Upstream stops importing `fleet_commons_shim` at module scope, or moves
to a mechanism the portable package can carry unchanged. The transform then has no input
to match and refuses to synchronize, which is the deliberate signal to revisit rather
than a failure to work around.

### Guard the join between the bundler and the synchronization in the validator, not only in tests

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` gains `check_fleet_bundle_outputs`, which rejects a
module a consumer's `fleet-bundle.json` declares but no generated bundle carries, and any
file under a `_bundled/` directory that no declaration accounts for. The presence half of
`scripts/bundle_fleet_module.py --check` is factored into `presence_errors` so both
commands report the same two conditions from one implementation. Alongside it,
`tests/test_client_entrypoints.py` runs each shipped client's `--help` in a subprocess,
with third-party transport stubbed and every `UNIFI_*` variable removed, and separately
asserts that deleting the generated bundle from a copy of the package breaks every
entrypoint.

**Rationale.** `check_bundled_files` reads bundles that exist, so a bundle that was never
generated is invisible to it. That is how the repository reported success while shipping
two clients importing a module nothing had written. A validator that only inspects
present files cannot catch an absent one; the declaration is the statement of what should
be present, so comparing the two is the missing assertion. The subprocess test is the
independent signal: it fails whether the cause is the declaration, the transform, or the
bundler.

**Rejected alternatives.**

- *Reuse `check_consumer` wholesale inside `check_repo`.* It also re-checks the stamps,
  which `check_bundled_files` already owns, so one tampered bundle would be reported
  twice in different vocabulary.
- *Rely on the entrypoint test alone.* A test proves the shipped tree works today; the
  validator states the invariant, and continuous integration runs it in the hermetic
  standard-library-only job.

**Revisit when.** A consumer needs a generated bundle outside a `_bundled/` directory,
which would make the directory name the wrong discriminator.

### Detect credentials by value with two narrow families, and never by bare entropy

**Author.** Jeff Cox and Claude

**Decision.** `scripts/check_repo.py` now rejects a credential written as a *value*
anywhere under `plugins/`, using exactly two detection families. The first is a list of
literal credential formats — AWS access key ids, GitHub and Slack and Stripe tokens,
Google and Anthropic and OpenAI API keys, JSON web tokens, private key blocks, and
credentials embedded in a URL — matched in every text file of a package including source,
because a real key committed into source is a leak whatever the surrounding code does with
it. The second is a credential-shaped key (`password`, `secret`, `token`, `api_key`,
`bearer`, `client_secret`, and their near neighbours) assigned a value of at least six
characters that clears 2.5 bits of entropy per character and is not a placeholder or a
reference to where the secret actually lives. The second family runs only on data and
documentation files, never on source.

**Rationale.** The reviewers' finding is that every existing guard — the site profile
loader, its schema, and the compatibility matrix redaction check — inspects field *names*,
so a password pasted into an allowed `notes`, `description`, or `ownership` value passes
all of them. Closing that needs value inspection, and value inspection is worth having
only if it is quiet enough to stay switched on. Measured against the live package tree,
this rule produces zero false positives while still reporting the reviewer's own example,
`notes: "controller password=hunter2"`.

**Rejected alternatives.** A third family scanning for bare high-entropy strings, which is
the usual approach and is unusable here: a provenance manifest is nothing but sha256
digests, so it would fire on every package in the catalog and the gate would be turned off
within a day. Running the credential-assignment family on source as well, which was
measured before being rejected — it produced five false positives on the shipped package,
every one of them credential-*handling* code such as `api_key = (api_key or "").strip()`
and `"X-Api-Key": self.api_key`, and none of them a secret. Scanning the whole repository
rather than `plugins/`, which would make `docs/reviews/` a continuous integration failure
surface; those two reviewer reports are immutable evidence with recorded digests, they
quote credential-shaped text on purpose, and a gate no one is allowed to satisfy is a gate
that gets deleted. `plugins/` is also the scope every other package check here already
uses, and it is the tree that actually leaves this repository.

**Accepted limits.** A short, low-entropy secret in a free-text value still passes:
`password: secret` is six characters of 2.25 bits and is below the floor by design. So
does a secret in a package file that is neither text nor a recognised data suffix. This
check is defense in depth against an accident, not a proof of absence, and the operator
guarantee should be worded as such.

**Revisit when.** A credential format in use by the fleet is not on the list, a real
credential reaches a package and this check does not report it, or the false-positive rate
stops being zero on the live tree.

**Scope note.** This closes the repository gate only. The same finding also implicates
`plugins/unifi/scripts/site_profile.py`, whose `validate_profile` accepts a credential in
a `notes` value at runtime, and `scripts/check_compatibility_matrix.py`, whose redaction
check is name-shaped. Neither file is owned by this unit and neither is changed here.

### Bind a current matrix to the tree it assessed, and make supersession the only exemption

**Author.** Jeff Cox

**Decision.** `scripts/check_compatibility_matrix.py` recomputes the fingerprint of
`plugins/unifi/` on every run — package name, version, file count, and a tree digest over
the sorted per-file digests *with their relative paths* — and fails when the record does
not match. A document may exempt itself only by declaring `<!-- matrix-status: superseded -->`
alongside a `superseded-by` naming an existing current matrix and a `superseded-reason`.
A superseded document whose fingerprint still identifies the shipped tree is rejected.
`matrix-status` defaults to `current`, so the binding is fail-closed. The no-argument run
validates every matrix document in `docs/evidence/`, superseded ones included.

**Rejected alternatives.** *Refreshing the numbers only*, because that leaves the identical
trap armed for the next package change and the review named this explicitly. *Adding a
`superseded` field to the record*, because `schemas/compatibility-matrix.schema.json` is
closed and owned by no unit in this run; HTML comment directives carry document-level
metadata without a schema change. *Dropping the JSON fence in the retired document so the
validator skips it*, because retiring a document withdraws its claim about the current
package, not the coverage and redaction rules it was published under. *Overwriting the
original matrix in place*, because the assessment happened and its record is evidence.
*A `--update` flag that rewrites the record from the tree*, because a one-keystroke refresh
would let a stale matrix pass by editing the evidence to match; there is a read-only
`--print-fingerprint` and nothing that writes. A test asserts no such flag is added.

**Rationale.** Hashing the per-file digests alone would leave a pure rename invisible, and
a rename is exactly the drift a binding exists to catch, so relative paths are inside the
hashed text. Checkout noise — `__pycache__`, `.pyc`, `.DS_Store` — is excluded, because a
fingerprint that moved when the test suite ran would be abandoned within a week. The digest
is defined in prose in the matrix itself so a third party can reproduce it from published
bytes.

**Consequence to expect.** Any future change under `plugins/unifi/` fails
`python3 scripts/check_compatibility_matrix.py` and the test suite until the assessment is
re-run and the record refreshed. That is the intended cost: the check is meant to be
noticed, and re-running forty credential-free stages is roughly an hour.

**Revisit when.** `schemas/public-evidence.schema.json` lands and can carry document status
as a schema field, or a second package joins the catalog and the single `PACKAGE_ROOT`
constant needs to become per-record.

**Refs.** [Digest learning](LEARNINGS.md#a-digest-in-an-evidence-record-proves-nothing-until-something-recomputes-it),
`scripts/check_compatibility_matrix.py`, `tests/test_check_compatibility_matrix.py`.

## 2026-08-21

### Choose UniFi plus a portable Fleet Core slice as the first portability pilot

**Author.** Jeff Cox and Claude

**Decision.** Port the Claude `unifi` plugin into a portable Agent Plugins 1.0 package
in this repository, together with a new portable Fleet Core source carrying only the
`retry_backoff` module. The Claude repository is repaired first, released second, and
synchronized from third. Custody does not move.

The load-bearing choices, each recorded in full in the
[pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md):

- The portable copy is derived and digest-verified, never a second writable source.
- The authoritative source is repaired before the port consumes it; downstream-only
  correction and intentional target divergence are both rejected.
- Extract means relocate, not delete: the embedded lab topology moves into an operator
  site profile, and the repaired release is gated on that replacement path being
  verified so the Claude agent never loses site context.
- Fleet Core becomes a first-class portable source, but only one vertical slice is
  ported; the required module is bundled into consuming artifacts at build time, since
  Agent Plugins 1.0 has no dependency mechanism.
- Compatibility coverage across all ten installed clients is mandatory; passing is not.
  The matrix is a deliverable ending in an operator pause, not a release gate.

**Rejected alternatives.** A hand-port with no drift detection; a subtree or submodule of
the vendor repository; porting the documentation defect verbatim; inlining the retry
primitive and reversing the fleet-wide shared-primitive decision; inventing an Agent
Plugins dependency field; and requiring an environment variable that would resolve to
nothing on a non-Claude host.

**Rationale.** UniFi is small enough to finish and real enough to exercise the actual
architecture boundary. Investigation found three problems the file listing could not
show — an undeclared cross-plugin dependency resolved through Claude-specific discovery,
documentation describing capabilities removed five months earlier, and one operator's
controller address hard-coded as a universal default — and each of them is exactly the
kind of thing a pilot exists to surface before a larger port inherits it.

**Revisit when.** The ten-client compatibility matrix is complete and the operator has
made the per-client decisions that follow it, or evidence shows the build-time bundling
model does not generalize to a second consumer.

**Refs.** [Pilot plan](../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md),
[architecture brief](../cross-vendor-plugin-architecture-brief.md),
[superseded parity decision](ARCHIVE.md#void-parity-baseline-recorded-in-error),
[archived pilot item](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

### Establish a public cross-vendor plugin source repository

**Author.** Jeff Cox and Codex

**Decision.** Use `infiquetra-agent-plugins` as the public repository for the
portable architecture, future shared plugin sources, and explicit vendor
adapters. Existing vendor repositories remain authoritative until a pilot is
proven and custody is moved by a later decision.

**Rejected alternatives.** `infiquetra-plugins` was too broad to distinguish
coding-agent capabilities from other plugin systems. Immediately replacing the
vendor repositories would create an unproved big-bang migration.

**Rationale.** The name identifies the domain, while the staged custody rule
allows shared sources to be proven without breaking current clients.

**Revisit when.** The first portable plugin passes its agreed compatibility
gate, or evidence shows the proposed repository boundary is wrong.

**Refs.** [Architecture brief](../cross-vendor-plugin-architecture-brief.md),
[archived pilot decision](ARCHIVE.md#choose-the-first-portability-pilot-and-custody-gate)

---

Keep newest entries first. When a decision is superseded, preserve the old text
in [ARCHIVE.md](ARCHIVE.md) and link the replacement.
