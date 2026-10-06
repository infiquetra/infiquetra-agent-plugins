---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# Saga review redesign: card index

Every card goes on the Operations board (GitHub project 3) with Objective `improve-agent-plugins`,
Stage `Shaping`, Status `Discovering`. The design source is `plan.md` in this folder; a card restates
only what it needs from it and never adds design decisions of its own. "Change N" refers to the
numbered changes in `plan.md`.

Cards C1 to C16 (with C4a to C4c, C5b, C10a and C10b), X1a, X1b, X2, X3 and K1 to K3 are children of
P0. Cards O1 to O4 are top-level.

| ID | File | Repository | Type | Risk | Title |
|---|---|---|---|---|---|
| P0 | `P0-saga-review-redesign.md` | infiquetra-agent-plugins | capability | high | saga: measured, mostly deterministic code review (review redesign) |
| C1 | `C1-review-records-and-formula.md` | infiquetra-agent-plugins | enhancement | medium | saga: review records, validation and the A–F formula |
| C2 | `C2-calibration-file.md` | infiquetra-agent-plugins | enhancement | medium | saga: the calibration file decides which lenses may block |
| C3 | `C3-saga-setup.md` | infiquetra-agent-plugins | enhancement | medium | saga: /saga:setup checks and prepares the machine and the repository |
| C4a | `C4a-tool-framework.md` | infiquetra-agent-plugins | enhancement | medium | saga: build-loop tool framework reporting only what a change introduces |
| C4b | `C4b-tools-python-cdk-shell-workflows-markdown.md` | infiquetra-agent-plugins | enhancement | medium | saga: review tools for Python, CDK, shell, workflows and Markdown |
| C4c | `C4c-tools-typescript-dart-rust-swift.md` | infiquetra-agent-plugins | enhancement | medium | saga: review tools for TypeScript, Dart, Rust and Swift |
| C5 | `C5-pattern-checks.md` | infiquetra-agent-plugins | enhancement | medium | saga: pattern checks for the defects we keep hitting |
| C5b | `C5b-scripted-checks.md` | infiquetra-agent-plugins | enhancement | medium | saga: the scripted review checks no tool provides |
| C6 | `C6-jev-sweep.md` | infiquetra-agent-plugins | enhancement | medium | fleet-core + saga: the Jev sweep says where to look in a change |
| C7 | `C7-question-banks.md` | infiquetra-agent-plugins | enhancement | medium | saga: policy questions and question banks for the four lenses, reviewed by the operator |
| C8 | `C8-targeted-reviewer.md` | infiquetra-agent-plugins | enhancement | high | saga + agent-launcher: the targeted LLM reviewer |
| C9 | `C9-orchestrate-reviewer-transport.md` | infiquetra-agent-plugins | enhancement | medium | orchestrate: one targeted reviewer per review, two on high-risk cards |
| C10a | `C10a-review-command.md` | infiquetra-agent-plugins | enhancement | medium | saga: one review command from change to records |
| C10b | `C10b-switch-code-review.md` | infiquetra-agent-plugins | enhancement | high | saga: switch /code-review to the review command, with the new round and merge rules |
| C11 | `C11-build-loop-declarations.md` | infiquetra-agent-plugins | enhancement | medium | saga + agent-launcher: builder declarations and the build-loop review checks |
| C12 | `C12-plan-review-one-pass.md` | infiquetra-agent-plugins | enhancement | medium | saga: plan review in one pass |
| C13 | `C13-review-state-and-fix-later.md` | infiquetra-agent-plugins | enhancement | medium | saga: review state for every harness, the pull request checklist and fix-later choices |
| C14 | `C14-review-mods.md` | infiquetra-agent-plugins | enhancement | medium | saga mods: review pane, merge confirmation, run band and setup pane |
| C15 | `C15-langfuse-review-traces.md` | infiquetra-agent-plugins | enhancement | high | fleet-core + saga: Langfuse review traces and outcomes at merge |
| C16 | `C16-qa-and-outcome-job.md` | infiquetra-agent-plugins | enhancement | medium | saga: tie /qa and later defects back to the review that passed the code |
| X1a | `X1a-sdlc-review-model-decision.md` | infiquetra-sdlc | enhancement | medium | Record saga's new review model and its contracts in the lifecycle repository |
| X1b | `X1b-sdlc-retire-lens-machinery.md` | infiquetra-sdlc | enhancement | medium | Retire the lens roster, executor ledger and lens catalogue in the lifecycle repository |
| X2 | `X2-ci-standard-review-tools.md` | infiquetra-context-library | context-update | low | CI standard: the pinned review tools per language as a required check |
| X3 | `X3-langfuse-https.md` | home-lab | enhancement | medium | Langfuse: serve over HTTPS before review data includes private code |
| K1 | `K1-corpus-repository-and-history.md` | saga-review-corpus (new, private) | enhancement | medium | Corpus repository, case format and cases from our fix history |
| K2 | `K2-planted-defects-and-public-sets.md` | saga-review-corpus (new, private) | enhancement | medium | Planted defects, builder records and public reference sets |
| K3 | `K3-harness.md` | saga-review-corpus (new, private) | enhancement | high | The harness: run the review on the corpus and write the calibration file |
| O0 | `O0-run-cost-and-progress.md` | infiquetra-agent-plugins | capability | medium | saga: see what a run costs and where it stands |
| O1 | `O1-status-band-v2.md` | infiquetra-agent-plugins | enhancement | low | saga mod: status band, second version |
| O2 | `O2-step-reminder-and-update-cadence.md` | infiquetra-agent-plugins | enhancement | low | saga: per-turn step reminder and issue update cadence |
| O3 | `O3-budget-at-admission.md` | infiquetra-agent-plugins | enhancement | medium | saga: budget and proportionality at admission, as guidance |
| O4 | `O4-cost-report-economics.md` | infiquetra-agent-plugins | enhancement | low | saga: run and review economics in the cost report |

## Filed issues

All 32 cards were filed on 5 October 2026, and O0 on 6 October. P0
([#147](https://github.com/infiquetra/infiquetra-agent-plugins/issues/147)) is the parent of the 27 other redesign
cards and of two earlier issues: #114 (this repository's saga profile, which the review command reads) and #144
(the stale-review path, which C10b keeps). O0 ([#173](https://github.com/infiquetra/infiquetra-agent-plugins/issues/173)) is the parent of O1 to O4. The seven cards for private repositories (X1a, X1b, X2, X3, K1, K2, K3) are filed there and are
not in this folder.

| Card | Issue |
| --- | --- |
| P0 | [#147](https://github.com/infiquetra/infiquetra-agent-plugins/issues/147) |
| C1 | [#148](https://github.com/infiquetra/infiquetra-agent-plugins/issues/148) |
| C2 | [#149](https://github.com/infiquetra/infiquetra-agent-plugins/issues/149) |
| C3 | [#150](https://github.com/infiquetra/infiquetra-agent-plugins/issues/150) |
| C4a | [#151](https://github.com/infiquetra/infiquetra-agent-plugins/issues/151) |
| C4b | [#152](https://github.com/infiquetra/infiquetra-agent-plugins/issues/152) |
| C4c | [#153](https://github.com/infiquetra/infiquetra-agent-plugins/issues/153) |
| C5 | [#154](https://github.com/infiquetra/infiquetra-agent-plugins/issues/154) |
| C5b | [#155](https://github.com/infiquetra/infiquetra-agent-plugins/issues/155) |
| C6 | [#156](https://github.com/infiquetra/infiquetra-agent-plugins/issues/156) |
| C7 | [#157](https://github.com/infiquetra/infiquetra-agent-plugins/issues/157) |
| C8 | [#158](https://github.com/infiquetra/infiquetra-agent-plugins/issues/158) |
| C9 | [#159](https://github.com/infiquetra/infiquetra-agent-plugins/issues/159) |
| C10a | [#160](https://github.com/infiquetra/infiquetra-agent-plugins/issues/160) |
| C10b | [#161](https://github.com/infiquetra/infiquetra-agent-plugins/issues/161) |
| C11 | [#162](https://github.com/infiquetra/infiquetra-agent-plugins/issues/162) |
| C12 | [#163](https://github.com/infiquetra/infiquetra-agent-plugins/issues/163) |
| C13 | [#164](https://github.com/infiquetra/infiquetra-agent-plugins/issues/164) |
| C14 | [#165](https://github.com/infiquetra/infiquetra-agent-plugins/issues/165) |
| C15 | [#166](https://github.com/infiquetra/infiquetra-agent-plugins/issues/166) |
| C16 | [#167](https://github.com/infiquetra/infiquetra-agent-plugins/issues/167) |
| X1a | [infiquetra-sdlc#177](https://github.com/infiquetra/infiquetra-sdlc/issues/177) |
| X1b | [infiquetra-sdlc#178](https://github.com/infiquetra/infiquetra-sdlc/issues/178) |
| X2 | [infiquetra-context-library#96](https://github.com/infiquetra/infiquetra-context-library/issues/96) |
| X3 | [home-lab#464](https://github.com/infiquetra/home-lab/issues/464) |
| K1 | [saga-review-corpus#1](https://github.com/infiquetra/saga-review-corpus/issues/1) |
| K2 | [saga-review-corpus#2](https://github.com/infiquetra/saga-review-corpus/issues/2) |
| K3 | [saga-review-corpus#3](https://github.com/infiquetra/saga-review-corpus/issues/3) |
| O0 | [#173](https://github.com/infiquetra/infiquetra-agent-plugins/issues/173) |
| O1 | [#168](https://github.com/infiquetra/infiquetra-agent-plugins/issues/168) |
| O2 | [#169](https://github.com/infiquetra/infiquetra-agent-plugins/issues/169) |
| O3 | [#170](https://github.com/infiquetra/infiquetra-agent-plugins/issues/170) |
| O4 | [#171](https://github.com/infiquetra/infiquetra-agent-plugins/issues/171) |

## Order and dependencies

- **First:** X1a, the lifecycle repository's decision record and contracts. C3, C8, C11 and C12 need it.
- **Before the switch (C10b), every lens reporting only:** C1, C2, C3, C4a to C4c, C5, C5b, C6, C7,
  C8, C9, C10a, C11, C13, C14, C15. X3 lands before any private repository's code is sent to Langfuse.
- **The switch:** C10b, together with X1b and X2.
- **Built alongside:** K1 to K3. Each lens starts blocking when K3's calibration file (C2) shows it
  cleared its marks.
- **Any time after their dependencies:** C12 and C16.
- **Direct dependencies:** C2: C1, C4a. C3: X1a, C4a. C4a: C1. C4b, C4c: C4a. C5: C1, C3, C4a. C5b: C1, C4a.
  C6: C1, C4a.
  C7: C6. C8: C1, X1a. C9: C1, C8. C10a: C1, C2, C4a, C6, C8. C10b: C1, C2, C9, C10a, C13. C11: C1,
  C2, C4a, C7, X1a. C12: C1, X1a. C13: C1, C10a. C14: C3, C13. C15: C1, C10a (and X3 for private
  repositories). C16: C1, C3, C13, C15, K1. X1b: X1a, K1 (lands with C10b). K1: C1, C7. K2: K1, C10a, C11. K3: C2, C10a, C15, K1, K2.
  O1: O3. O4: C1, C10b.
- Existing related issues: #144 (a stale review re-enters code review without the combined-branch
  functional run; C10b replaces that path), #114 (this repository's own `.saga-profile.json`; first
  user of C3).

## Scope per card

Each bullet list is what the card covers. Everything comes from `plan.md`; the section to read is named.

**P0** — the umbrella. Goal, the ten changes, order of work, the children list, how we will know it
works. Drafted by the coordinator.

**C1** (Change 1, Change 7, "Block, fix later and note") — the records (finding, measurement,
where-to-look item, lens grade, review run, and the builder record) as one schema with a validator that
rejects malformed records; severity computed by code from consequence, trigger and evidence plus the
fixed per-input rules of the four lens tables; a finding identity that survives rounds and line shifts;
the merge outcome and the "unconfirmed" mark on each finding; the A–F grade per lens and the merge rule
(every lens at C or better); degraded marking; report-only marking from the calibration file (a
report-only lens keeps its grade); storage in the run record replacing both shapes now called
`review_result.v2`, with a writer that keeps every field.

**C2** (The harness: calibration file; "How we'll know it works") — the calibration file's format; the
fingerprint over every review component (policy questions and question banks, our checks, the formula,
default tool versions, rule sets and curated lists, the reviewer's prompt, model and launch settings);
the pass marks kept in saga; a `scripts/check_repo.py` rule that fails when the fingerprint does not
match, and accepts any fingerprint before the first corpus run; saga reading K3's per-lens,
per-language verdicts and per-question thresholds at review time; profiles pinning other tool versions
get report-only for the affected lenses.

**C3** (Change 2) — `/saga:setup` as its own command and script, usable from any harness: machine
checks (command-line tools saga uses, review tools per detected language, the sweep's parser, the
reproduction sandbox, presence of the TypeSafe and saga Langfuse keys without printing them),
repository profile (languages, visibility, pinned tool versions and rule sets, shared update paths,
functional-test environment, `/qa` strategies); installs only on approval; optional machine steps
other cards add (C16's daily job); records the machine result in the user's home; degraded signal once
per run naming missing tools and `/saga:setup`; admission asks only for what setup has not recorded.
The Claude pane and the first-session offer are C14. The command surface tests pin 14 commands and 13
skills; this card changes those pins deliberately.

**C4a** (Change 3, Change 2 "How the tools run") — the runner that executes pinned tools in the build
loop; filtering findings to the changed lines; base and head comparison for whole-project results
(dependencies, duplication, type checkers); the outcome rules for levels, severity-less tools and
unscored vulnerabilities; one changed-line coverage adapter over LCOV, Cobertura and coverage.py JSON;
the relocated test run; the one diff reader; turning outputs into C1 records; the tools every language
gets (Semgrep, gitleaks, osv-scanner, jscpd, lizard); version mismatches and known gaps marked degraded.

**C4b** (Change 2 default tools table; lens tables) — adapters for Python, CloudFormation and CDK,
shell, GitHub workflows and Markdown, each mapped to its lens table row and outcome, with level
mappings and curated lists in `review-tools.md`.

**C4c** (same sections) — adapters for TypeScript, Dart, Rust and Swift, with the same mappings; known
gaps run degraded.

**C5** (Change 4; correctness table) — Semgrep rules for the recurring defects, each blocking unless the
builder records a reason, with the harm it encodes, and `ruleid`/`ok` rule tests that run in CI.

**C5b** (lens tables) — the scripted checks no tool provides: the two test runs, tests skipped in CI,
the machine-specific value search, the changed-name search and the workflow graph check.

**C6** (Change 5) — the edit to TypeSafe's data rule; saga's piece extraction and fleet-core's
`jev sweep`: the swappable classifier contract, pieces, the question bank format and switch-on
conditions, thresholds read from the calibration file (30 most likely items until they exist), caps,
two option orders, caching, redaction, verdicts logged with the model version; the where-to-look
records (C1).

**C7** (Change 5 "Questions"; Change 8 "Optional lenses"; lens tables) — the policy's 30 questions as
a public list builders declare against; 10 to 20 Jev questions per lens with options, definitions,
examples, not-for lines and switch-on conditions; the folded optional lenses; one operator sitting per
lens, recorded in the bank file, covering the lens's questions, check outcomes and curated tool lists.

**C8** (Change 6; Decisions added 5 October) — the reviewer prompt file and output schema in saga;
agent-launcher's targeted-reviewer role for any vendor, with its normal configuration recorded; answering every where-to-look item;
reproduction with a sandboxed test in a scratch copy; one open search with a cap; the consequence picked
separately by the LLM and Jev, the lower one applying, "unconfirmed" when Jev cannot answer; disputes of
"doesn't apply". Agent-launcher starts the reviewer on its staffed vendor; orchestrate (C9) and the
harness (K3) call that launch, and saga never starts it. The review-controller role's rewrite lands
with the switch (C10b).

**C9** (Decisions added 5 October; Change 8) — orchestrate starts one targeted reviewer per review, and
on high and very-high risk cards a second one, blind to the first; packets and answers as files;
orchestrate's readers moved to the new records, falling back to the old shape until the switch, and the
test that loads saga's consensus code moved with them.

**C10a** (Change 8; The harness "One review command") — one script from change to records: inputs
(repository, base and head commits, profile, builder record, reviewer usage), tools and checks, sweep,
reviewer packet, answer validation, merging two reviewers' findings, sandboxed re-runs of reproduction
tests, formula, records; a deterministic part that runs alone; runs without a session.

**C10b** (Change 8; "Block, fix later and note") — `/code-review` calls the review command; deleted in
the same change: the lens roster, consensus scoring, the verifier, both result shapes, the unused Jev
checks, the lens-reviewer roles, the post-merge cycles; the round and merge rules, unattended merges
following the intent envelope; reproduced data loss or security exposure blocks even while its lens
reports only; unresolved pull request review threads block merge; admission loses the lens and
round-allowance questions. Replaces the path in #144.

**C11** (Change 8 "Build loop"; design rule on declarations) — the builder declares against the policy
questions in the unit's builder record, repair implementers too; a unit cannot hand off until every
question has a declaration and every named test exists and passes; the check is callable outside a run;
the combined-branch gate fails on a blocking tool finding only for lenses allowed to block, and always
on a secret in the diff.

**C12** (Change 8 "Plan review") — `/doc-review` and `/plan` 5.4: one reviewer, one pass, findings as C1
finding records; the author fixes or rejects each with a reason; rejections listed for the operator;
the acceptance-criteria mapping check stays blocking; the loop and the one-word override go.

**C13** (Change 10, except the mods) — the review-state document; a Markdown rendering and numbered
questions for harnesses without mods; one pull request comment per round, the last with the fix-later
checklist; fix now, file or leave at merge confirmation; unattended runs from the intent envelope; the
profile's unattended default; the security guard; `run_status.py review` rebuilt on the document.

**C14** (Change 10 mods; Change 2 "Screens") — Claude Code mods reading the C13 document: the live review
pane (keeping `/review-view`), the merge-confirmation pane with its 30-minute fallback, the band, the
status-line entry for missing tools, the setup pane and the first-session offer.

**C15** (Change 9) — a standard-library Langfuse client in fleet-core with saga's own key names; one
trace per review run, posted by the review command; outcomes at merge; plan-review traces; the rounds
view; the local queue; private repositories only over HTTPS; held-out results as totals; the "Saga
Reviews" project and the corpus dataset with code evaluators.

**C16** (Change 9 "Who records outcomes"; Change 8 "After merge"; Change 10 fix-later) — `/qa` records
the review run it tests; the release step writes the merged commit; a daily job on this Mac links later
defects to the review runs that passed the code, files fix-later items ticked later, and queues
defects as corpus candidates; its schedule installed by `/saga:setup` on approval.

**X1a** (Change 8; whole plan) — in infiquetra-sdlc: the DECISIONS entry for the new review model,
superseding the 2026-09-06 decision and settling the older decisions it touches; the targeted-reviewer
role name; the builder-record field in the implementation-result contract; saga's finding record as the
finding format; `/saga:setup` in the command classification.

**X1b** (Change 8) — in infiquetra-sdlc, with the switch: the lens catalogue, the review roster
generator, the executor-verification ledger and the lens and escalation parameters retired; lens
fixtures moved to the corpus or deleted; the site views updated.

**X2** (Change 2 "The same checks in CI") — in infiquetra-context-library: the pinned review tools per
language as a required CI check on what a change introduces, linking saga's pins as the source.

**X3** (Change 9 "HTTPS first") — in home-lab: a publicly trusted certificate for the Langfuse server,
every client moved to the HTTPS name, plain HTTP closed to the network.

**K1** (The corpus) — the new private repository `infiquetra/saga-review-corpus`: layout, `case.json`
schema (with risk tier and the old review's link), code by reference plus patches, the split rule
(history cases held-out, public ones tuning, planted ones by a hash of their pull request), the screening
scripts that turn fix commits into cases with sandboxed proof runs, the labelling rule, relabelling, the
candidate queue, archiving referenced repositories.

**K2** (The corpus) — planted defects with proof and operator confirmation, builder records for every
case, public sets as pinned download scripts, the cells file, filling the tuning half to the minimums
and the held-out half where history falls short.

**K3** (The harness) — the runner calling saga's review command per case, reviewer sessions started through
agent-launcher with their normal configuration in scratch copies, trials on other vendors, comparisons of
what has an effect, caching by fingerprint, the cost estimate and cap, repeat runs and the variation limit,
held-out hygiene, per-lens and per-language results with the guard, Langfuse dataset runs, writing the
calibration file (verdicts, numbers and thresholds), the drift runs, the like-for-like summary, the
second-reviewer measurement, and checking both halves' minimums before the first full run.

**O0** (added 5 October, after filing) — the parent of O1 to O4: while a run works the operator sees its
step and its spend against a budget, and afterwards what each step, role and round cost.

**O1 to O4** (from the 4 October enhancement plan, outside the review redesign) — O1: the status band's
second version. O2: a per-turn step reminder and an issue update cadence. O3: budget and plan size at
admission, as guidance. O4: cost by step and role, review rounds and findings by outcome in the cost
report.
