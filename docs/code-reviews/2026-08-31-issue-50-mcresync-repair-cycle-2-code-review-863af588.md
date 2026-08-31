---
title: Saga Code Review — Agent Plugins #50 mission-control resynchronization, repair cycle 2
reviewed_revision: 863af5888e548b6c95f40d3fd571c9365d136dea
base_revision: 0eff36ef432d90e3ba046ab0ca464168932034da
previous_cycle_revision: 853411da75cc6499e4d8395e85d36a2b9fe81fbc
branch: orch-agent-plugins-50
issue_ref: infiquetra/infiquetra-agent-plugins#50
plan_path: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
previous_artifact: docs/code-reviews/2026-08-30-issue-50-mcresync-integration-code-review-853411da.md
result_path: docs/code-reviews/2026-08-31-issue-50-mcresync-repair-cycle-2-code-review-863af588-result.json
outcome: repairs_requested
cycle: 2
mode: interactive
---

# Saga Code Review — repair cycle 2

Cycle 1 reviewed `853411d`, returned `repairs_requested`, and raised 47 findings across 16
consolidated fix requests. Nine commits later this is the repaired revision. This cycle asks
three questions: did each claimed repair fix the thing it claims to fix, did any repair break
something, and are the deliberate non-repairs the right call.

- **Reviewed revision:** `863af5888e548b6c95f40d3fd571c9365d136dea` (`863af58`)
- **Base:** `0eff36ef432d90e3ba046ab0ca464168932034da` — the merge base, and `origin/main`
- **Repair diff:** `git diff 853411d..863af58` — 24 files, +5,897 / −97
- **Working tree:** clean at the frozen revision; nothing was mutated by this review

## Outcome

> **`repairs_requested`, cycle 2 of 3.** The repair round did real work: both cycle-1 blockers
> are genuinely fixed, every independent gate now passes where two failed before, and the
> weakest lens moved from 4.80 to 7.40. What holds acceptance open is that several repairs
> closed the symptom and left the cause, and the round's own records — the plan's freeze
> account, one journal filing, and the U5 decision entry — no longer describe what shipped.

- Typed Saga review result contract (`review_result.v1`): **`repairs_requested`**
- Next action: `dispatch_repairs` (the only allowed resume transition)
- Independent readiness: **`can_proceed: false`** — but for the first time this is *purely*
  numeric. All 13 independent gates pass; cycle 1 failed two.
- Findings: **P0=0, P1=2, P2=26, P3=21** (49 total; 31 attributable here, 18 pre-existing)
- Consolidated fix requests: 17
- **Score regressions recorded:** `architecture-maintainability` 6.71 → 6.43, and
  `agent-usability` 6.60 → 6.40. Both are honest: the repairs added coupling and new
  agent-facing text that is wrong.
- Suppressed by the confidence rule (below anchor 75): 0

### What the repair round actually fixed

Thirteen of the sixteen fix requests landed. I falsified the load-bearing ones rather than
reading them:

| Cycle-1 finding | Verdict | How it was checked |
|---|---|---|
| **F03** dependency-free CI job broken | **fixed** | bare 3.12 venv with only pip + PyYAML: `Ran 835 tests … OK (skipped=2)`, exit 0. The same interpreter gave `FAILED (errors=1)` at `853411d` |
| **F04** transform rule had no test | **fixed** | `PackageRootMarkerRuleTests` — 19 tests, every refusal branch, idempotence, reproducibility; all pass |
| **F19** hard-coded client directory | **fixed** (shape questioned — `F58`) | a mutated descriptor makes `plan_sync` refuse by name; the real one passes silently |
| **F20** site-count table unjoined | **fixed** (escape hatch broken — `F59`) | removing a row and adding an undeclared one each turn the join red |
| **F28** create-option guard one-sided | **fixed** | an injected write through `_graphql` **and** through `_gh` now each turn the guard red. Cycle 1's blind spot is closed |
| **F21, F40, F42, F43** transform refusals | **fixed** | residual scan on both paths; the raises capture opened; the incomplete-row check added; every finder classified and rewritten |
| **F23, F24, F29, F31, F35, F18, F05, F10, F22, F45, F47** | **fixed** | per-lens verification, recorded in the finding detail below |

### What still blocks

Nothing blocks on a gate any more. Acceptance is held open by the roster's numeric rule —
every lens needs a derived overall of 9.0 with no dimension below 7.0, and none reaches it.
The substantive residue is three groups:

1. **Repairs that closed the symptom and left the cause.** The `plan_sync` refusal has no test
   (`F60`), so it can be deleted silently. Its constant is not the one the rewrite emits
   (`F63`), so a rename decouples guard from output. The site-count join makes the docstring's
   own remedy unreachable (`F59`). The restored Results table is unbound prose (`F56`) — a
   mis-transcription in the table validates clean.
2. **Records that no longer describe what shipped.** The plan says the freeze is the last
   package change and carries no amendment for the repair round (`F49`). The U5 decision entry
   still names the retired fingerprint and the retired Qwen result (`F61`). One journal filing
   claims a hermetic run that fails (`F48`).
3. **New agent-facing text that is wrong.** The restored README disclosure is inaccurate about
   both `board wip` and the absent-config path (`F71`), and an undisclosed sibling degradation
   makes `rollout gap-analysis` a false all-clear (`F72`).

**One of those is mine.** `F71`'s sentence was adopted verbatim from the cycle-1 reviewer's
suggested fix, and that suggestion was wrong about `board wip`. The repair round applied it
faithfully. The finding stands against the shipped text, but the error originated in this
review, not in the work.

## What this review verified for itself

| Claim | Result at `863af58` |
|---|---|
|---|---|
| Frozen revision and clean tree | `HEAD` is `863af588…`; `git status --porcelain` empty; no untracked files |
| Package fingerprint | live `--print-fingerprint` → **71 files / `659f91f6eae524612ad8daf3046d083281e0e76a950de3600b4b2948c68a18bd`**, and both current evidence documents record exactly that |
| The five graded files are untouched | 0 changed files each across `0eff36e..863af58` |
| No byte copy was hand-edited | all 46 `custody.byte_copies` and all 5 `client_byte_copies` compared directly against upstream `3b2b7083` — 0 mismatches, 0 missing |
| No transform output was hand-edited | all twelve `entrypoint_transforms` re-derived by running their own rule against upstream bytes — 12/12 byte-identical to what ships |
| What moved the fingerprint | only `PROVENANCE.json` (generated) and `plugins/mission-control/README.md` (target-owned); no carried byte moved |
| Custody round-trip | `sync_vendor_source.py --check` exits 0 with the match line naming `3b2b7083…` |
| `check_repo.py` | `Repository validation passed.` |
| Root test suite | `Ran 834 tests … OK` |
| Package suite, Python 3.14 | `391 passed` |
| Package suite, Python 3.12 floor | `391 passed` |
| The whole `pytest plugins/*/tests` job, 3.12 floor | `917 passed, 333 subtests passed` |
| `git diff --check` | clean |
| Compatibility-matrix validation | `Compatibility matrix validation passed.` |
| **F03 repaired** — the dependency-free CI job | bare Python 3.12 venv with only pip + PyYAML: `Ran 835 tests … OK (skipped=2)`, exit 0. Was `FAILED (errors=1)` at the cycle-1 revision under the identical interpreter |
| **F04 repaired** — the transform rule now has tests | `PackageRootMarkerRuleTests` runs 19 tests covering every refusal branch, idempotence and reproducibility; all pass |
| **F19 repaired** — falsified | a descriptor naming a different `client_extension_dir` makes `plan_sync` refuse by name; the real descriptor passes silently |
| **F20 repaired** — falsified both ways | removing a site-count row and adding an undeclared one each turn the join red; as shipped it is green |
| **F28 repaired** — falsified both doors | an injected write through `_graphql` **and** one through `_gh` now each turn the guard red; as shipped it is green. Cycle 1's `_gh` blind spot is closed |
| Every unit-completion and repair commit | green, except three: `f4da07e` and `0ff932e` (one failure each) and `a1e84e0` (six), all re-run per commit |
| The cycle-1 review record | committed at `68906b8` unaltered — same reviewed revision, outcome, 47 findings, 16 fix requests — and never edited afterwards |

## Independent gates

All thirteen pass. Cycle 1 failed `built-vs-planned` and `ci-validate-job-dependency-free`;
both are now clean.

| Gate | Cycle 1 | Cycle 2 |
|---|---|---|
| `built-vs-planned` | **failed** | passed — R42, R30 and R35 are all met (below) |
| `ci-validate-job-dependency-free` | **failed** | passed — measured on a bare interpreter |
| `scanner-check-repo` | passed | passed |
| `tests-root-unittest-834` | passed (801) | passed (834) |
| `tests-package-pytest-3.14` | passed | passed (391) |
| `tests-package-pytest-3.12-floor` | passed | passed (391) |
| `tests-all-plugin-suites-3.12-floor` | — | passed (917) |
| `custody-round-trip-check` | passed | passed |
| `custody-no-hand-edited-carried-path` | — | passed — see below |
| `compatibility-matrix-validation` | passed | passed |
| `whitespace-git-diff-check` | passed | passed |
| `graded-file-mutation-proof-intact` | passed | passed |
| `operational-safety-no-live-mutation` | passed | passed |

### Custody, checked across the whole run rather than only at the tip

Only the synchronization commit `af322db` touched a carried path. `55a6511` touched
`README.md` and `plugin.json`; `a1e84e0` touched `PROVENANCE.json` and `README.md` — all
target-owned or generated, zero byte copies and zero transform outputs between them. Combined
with the byte-for-byte comparison against upstream and the twelve re-derived transform
outputs, nothing carried was hand-edited at any point in the run, not merely at the end.

## Built versus planned

**Cycle 1's three unmet requirements are now met.**

- **R42 — NOT-DONE → DONE.** `PackageRootMarkerRuleTests` covers the rule against upstream
  bytes, refuses a missing or duplicated definition, and proves the no-op on portable input.
- **R30 — PARTIAL → DONE.** All ten clients were exercised; none is recorded as never having
  run. The recording also got *more* honest: 7 stages are now `blocked` where the superseded
  matrix marked all 40 `executed`.
- **R35 — CHANGED → DONE.** The verifier is narrowed to the five graded paths by name and
  prints `0`.

R38 (unrelated worktrees and sessions preserved) remains structurally UNVERIFIABLE from a
single revision. Everything else is DONE. The gate passes.

What the plan no longer describes correctly is its own *record* — the freeze account, the
commit count in one section, the superseded-document count, and the absence of an amendment
for the repair round. Those are findings `F49`, `F09`, `F33` and `F34`, not unmet
requirements.

## On the three things you asked me to scrutinize

**The Qwen status change is disclosed honestly, and I am raising nothing against it.** The
matrix states outright "The package did not change between the two readings; the launcher
environment did." The exported-override mechanism is named in the method prose, the machine-
readable `method.isolation` block, the client's own reason field, the one-line outcomes table,
and the root README bullet. Nothing anywhere presents it as the package improving. The
recording is also stricter than its predecessor, which marked all forty stages `executed`
including four that exited 127.

**Your F01 measurements are exactly right**, all three reproduced independently. The mechanism
is that `_gh`'s `FileNotFoundError` handler calls `sys.exit(1)`, and `SystemExit` is not an
`Exception`, so `_resolve_sdlc_schema`'s deliberately broad `except Exception` never catches
it. The fallback works when `gh` exists and fails; the gap is the binary-absent path. The
57-failure delta against the base package is a regression this resync introduced. The
`LEARNINGS.md` entry records all of this accurately — **one journal filing does not** (`F48`).

**The deferrals are right, with two corrections.** Deferring the carried-upstream defects and
the two graded-file fixes is correct policy. But filing 7 routes a portable-path defect
upstream when all seven `SKILL.md` files are already *transforms*, not byte copies — so a
downstream remedy is in policy and the stated ground does not hold (`F70`). And filing 2's
remedy would send an agent onto a verb that overwrites the whole option set (`F74`).

## Findings

Ordered by severity, then confidence, then file, then line. Identifiers continue cycle 1's
stable sequence: a finding that persists keeps its number, new findings start at F48. The
Cycle 1 column names the finding this one descends from, or NEW.

### P2 — introduced by this change or by the repair round (15)

| # | File | Issue | Reviewer | Conf | Route | Cycle 1 |
|---|---|---|---|---|---|---|
| F61 | `docs/engineering-journal/DECISIONS.md:565` | U5 decision record still states the retired fingerprint | architecture,api-contract | 100 | manual -> review-fixer | NEW |
| F48 | `docs/engineering-journal/QUEUED.md:28` | Journal filing claims a hermetic run that fails | documentation | 100 | safe_auto -> review-fixer | NEW |
| F74 | `docs/engineering-journal/QUEUED.md:34` | Filing's remedy routes agents onto a destructive verb | agent-usability | 100 | safe_auto -> review-fixer | NEW |
| F73 | `docs/engineering-journal/QUEUED.md:35` | Filing undercounts the subcommands that ignore --format | agent-usability | 100 | safe_auto -> review-fixer | NEW |
| F70 | `docs/engineering-journal/QUEUED.md:56` | Filing routes a portable-path defect to the wrong owner | agent-usability | 100 | manual -> review-fixer | NEW |
| F50 | `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md:14` | Retired matrix banner links an already-superseded successor | documentation | 100 | safe_auto -> review-fixer | NEW |
| F51 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md:40` | Matrix claims no client authenticated; one was | security | 100 | safe_auto -> review-fixer | NEW |
| F49 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2164` | Plan's freeze record contradicts the landed branch | documentation | 100 | manual -> review-fixer | NEW |
| F71 | `plugins/mission-control/README.md:77` | Restored README disclosure contradicts measured behaviour | agent-usability,documentation | 100 | manual -> review-fixer | NEW |
| F66 | `ports/README.md:114` | Descriptor specification omits the new transform rule | api-contract | 100 | safe_auto -> review-fixer | NEW |
| F59 | `scripts/sync_vendor_source.py:49` | The site-count table's documented escape hatch cannot be used | architecture,api-contract | 100 | manual -> review-fixer | NEW |
| F58 | `scripts/sync_vendor_source.py:1140` | Generic planner hard-codes one transform rule's identity | architecture | 100 | manual -> review-fixer | NEW |
| F60 | `scripts/sync_vendor_source.py:1143` | The plan_sync descriptor refusal has no committed test | architecture,api-contract,correctness | 100 | manual -> review-fixer | NEW |
| F56 | `tests/test_check_compatibility_matrix.py:1364` | Matrix results table and summary are unbound prose | testing | 100 | manual -> review-fixer | NEW |
| F55 | `tests/test_check_compatibility_matrix.py:1639` | New superseded-link test walks gitignored directories | testing | 100 | manual -> review-fixer | NEW |

### P3 — introduced by this change or by the repair round (16)

| # | File | Issue | Reviewer | Conf | Route | Cycle 1 |
|---|---|---|---|---|---|---|
| F68 | `README.md:81` | Root README client-status counts have no gate | api-contract | 100 | gated_auto -> review-fixer | NEW |
| F78 | `docs/engineering-journal/QUEUED.md:11` | One repair round declared its red window; the other did not | documentation | 100 | safe_auto -> review-fixer | NEW |
| F32 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378` | Issue #52's line-claim count is still uncorrected | documentation | 100 | safe_auto -> review-fixer | F32 |
| F33 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:399` | Plan and acceptance still say two superseded documents | documentation | 100 | safe_auto -> review-fixer | F33 |
| F09 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2175` | Section 8.2 still records twelve landed commits | documentation | 100 | safe_auto -> review-fixer | F09 |
| F34 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2482` | Four amendments still cite one overwritten review file | documentation | 100 | manual -> review-fixer | F34 |
| F69 | `scripts/sync_vendor_source.py:11` | Sync tool docstring contradicts its own recorded exception | api-contract | 100 | safe_auto -> review-fixer | NEW |
| F62 | `scripts/sync_vendor_source.py:840` | Site-count refusal names a class chosen by hash seed | api-contract,architecture | 100 | safe_auto -> review-fixer | NEW |
| F65 | `scripts/sync_vendor_source.py:861` | zip truncation drops the definition-before-call check | correctness | 100 | safe_auto -> review-fixer | NEW |
| F63 | `scripts/sync_vendor_source.py:1141` | Marker guard compares a constant the rewrite ignores | correctness | 100 | safe_auto -> review-fixer | NEW |
| F76 | `scripts/sync_vendor_source.py:1149` | New sync refusal prescribes a wrong remedy | agent-usability | 100 | safe_auto -> review-fixer | NEW |
| F64 | `tests/test_port_config.py:596` | F18 count gate matches a substring, not the number | correctness | 100 | safe_auto -> review-fixer | NEW |
| F75 | `tests/test_sync_vendor_source.py:1027` | Prose-to-table join checks paths, never the counts | architecture | 100 | manual -> review-fixer | NEW |
| F46 | `tests/test_sync_vendor_source.py:1845` | PyYAML guard regex still matches any workflow line | testing | 100 | safe_auto -> review-fixer | F46 |
| F53 | `tests/test_sync_vendor_source.py:2048` | Verb-surface gate self-skips on a dependency it does not use | security | 100 | safe_auto -> review-fixer | NEW |
| F77 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md:1` | Evidence filenames invert the repository's supersession convention | agent-usability | 75 | manual -> human | NEW |

### Pre-existing (informational — this change did not introduce them)

**P1 (2)**

| # | File | Issue | Reviewer | Conf | Route | Cycle 1 |
|---|---|---|---|---|---|---|
| F01 | `plugins/mission-control/scripts/sdlc_manager.py:343` | Ported package suite reaches GitHub and needs a gh binary | security,testing | 100 | manual -> human | F01 |
| F02 | `plugins/mission-control/skills/labels/SKILL.md:116` | Five agent surfaces instruct creation via a no-op verb | agent-usability | 100 | manual -> human | F02 |

**P2 (11)**

| # | File | Issue | Reviewer | Conf | Route | Cycle 1 |
|---|---|---|---|---|---|---|
| F72 | `plugins/mission-control/README.md:105` | Undisclosed labels degradation makes gap-analysis a false all-clear | agent-usability | 100 | manual -> review-fixer | NEW |
| F12 | `plugins/mission-control/scripts/sdlc_manager.py:2026` | --format json silently ignored by twelve subcommands | agent-usability | 100 | manual -> human | F12 |
| F13 | `plugins/mission-control/scripts/sdlc_manager.py:2058` | No-op create-option exits zero, signalling success | agent-usability | 100 | manual -> human | F13 |
| F14 | `plugins/mission-control/scripts/sdlc_manager.py:5578` | Mapping pull-request route leaves orphan remote branches | api-contract | 100 | advisory -> downstream-resolver | F14 |
| F15 | `plugins/mission-control/skills/board/SKILL.md:40` | Board skill ships knowingly wrong Operations and Asgard ladders | agent-usability | 100 | manual -> human | F15 |
| F16 | `plugins/mission-control/skills/flow/SKILL.md:71` | Skill invocation paths do not resolve in a portable install | agent-usability | 100 | manual -> human | F16 |
| F54 | `scripts/assess_clients.py:314` | Real-home client is restrained only by prompt text | security | 100 | manual -> human | NEW |
| F25 | `tests/test_mission_control_rule_audit.py:75` | Root suite executes unpinned code from outside the repository | security,testing | 100 | manual -> human | F25 |
| F26 | `tests/test_mission_control_rule_audit.py:138` | Card-validator suite reports the machine, against the run's own rule | testing,security | 100 | manual -> human | F26 |
| F57 | `tests/test_mission_control_rule_audit.py:138` | Rule-audit module is 57 percent inert in CI | testing | 100 | advisory -> human | NEW |
| F27 | `tests/test_mission_control_rule_audit.py:493` | Two tests still write inside the fingerprinted package tree | testing | 100 | manual -> review-fixer | F27 |

**P3 (5)**

| # | File | Issue | Reviewer | Conf | Route | Cycle 1 |
|---|---|---|---|---|---|---|
| F30 | `.github/workflows/ci.yml:59` | CI installs plugin test dependencies unpinned | security | 100 | gated_auto -> release | F30 |
| F36 | `plugins/mission-control/PROVENANCE.json:21` | Every dropped-path entry repeats all three drop reasons | correctness | 100 | manual -> downstream-resolver | F36 |
| F67 | `ports/mission-control.json:139` | Mutating-operation contract is a bare action-token list | api-contract,security | 100 | manual -> human | NEW |
| F38 | `scripts/check_compatibility_matrix.py:940` | Evidence redaction check never reads document prose | security | 100 | gated_auto -> human | F38 |
| F44 | `tests/test_mission_control_readme.py:275` | No gate checks skill commands against the CLI surface | agent-usability | 100 | manual -> human | F44 |
## Finding detail

Failure mode first, then the evidence, then the proposed minimal fix.

### F01 — Ported package suite reaches GitHub and needs a gh binary

`P1` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `manual` -> `human` · *pre-existing* · cycle 1: `F01`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:343`

`_resolve_sdlc_schema` puts the network first and swallows every exception before falling back, so the carried suite grades itself against live upstream when an authenticated `gh` is present. The binary-absent path is worse: `_gh`'s FileNotFoundError handler calls sys.exit(1), and SystemExit is not an Exception, so the broad fallback never catches it and 58 tests fail. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- Measured by the controller at this revision: `gh` absent -> 58 failed, 333 passed; a non-network `gh` stub exiting 1 -> 391 passed with the stub called exactly 180 times (179 the same schema read); the base 2.12.2 package with `gh` absent -> 1 failed, 265 passed
- The 57-failure delta between the base package and this one is a regression this resync introduced, via the five carried test files it changed
- plugins/mission-control/scripts/sdlc_manager.py:721-723 - `except FileNotFoundError: _error(...); sys.exit(1)`, against the `except Exception: pass` at :358
- docs/engineering-journal/QUEUED.md filing 1 and docs/engineering-journal/LEARNINGS.md record it; the LEARNINGS entry states the 58 correctly

**Suggested fix.** File the ladder inversion upstream - vendored first, network opt-in - and a refusal when the gh binary is absent rather than a bare sys.exit inside a swallowed try.

### F02 — Five agent surfaces instruct creation via a no-op verb

`P1` · confidence 100 · `agent-usability` / `capability-parity-reachability` · `manual` -> `human` · *pre-existing* · cycle 1: `F02`  
**Where:** `plugins/mission-control/skills/labels/SKILL.md:116`

The package ships no verb that adds one option to a single-select field, and five agent-facing surfaces still instruct an agent to create one with `fields create-option`, which prints and exits 0. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/skills/labels/SKILL.md:116-125, :157, :189; labels/references/labels-reference.md:213; milestones/references/objective-workflow.md:34; com.infiquetra.claude/agents/sdlc-operator.md:319 and :330
- docs/engineering-journal/QUEUED.md filing 2 records it - but its remedy is unsafe as written; see F74

**Suggested fix.** Route 'create an option' onto `fields set-options --options-file` with the complete-list constraint stated, or the Projects UI.

### F61 — U5 decision record still states the retired fingerprint

`P2` · confidence 100 · `architecture-maintainability` / `significant-decision-documentation` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/DECISIONS.md:565`

The round's most consequential decision - moving the frozen fingerprint after the review freeze and re-running the assessment - is recorded nowhere in the journal, and the existing U5 entry now asserts facts the round retired. Its body twice binds the fresh evidence to the old tree and records Qwen as failed; the documents its Refs now point at record the new tree and Qwen as works-directly. Only the two Refs links were swapped. The entry's own revisit condition fired inside this run without the entry being revised.

**Evidence**

- docs/engineering-journal/DECISIONS.md:565 and :588 name the retired tree; :577-580 records Qwen failed
- Controller-confirmed: grep across the journal returns the retired digest twice and the live digest not at all
- The current matrix records Qwen works-directly and the new tree
- The repair diff shows the only change to that entry is the two Refs links

**Suggested fix.** Add a dated entry for the second U5 run - why the fingerprint was allowed to move, the rejected alternative of holding the corrections back, and a revisit condition - and amend or mark the existing entry as describing the superseded first run.

### F48 — Journal filing claims a hermetic run that fails

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/QUEUED.md:28`

Filing 1 ends 'the hermetic half was re-run with `gh` off PATH and passes'. It does not. With `gh` absent the package suite is 58 failed / 333 passed and the root suite is 1 failed - measured at this revision. The sentence sits in the same paragraph that calls itself 'the honest statement', and QUEUED.md is where someone acting on the upstream filing looks. The round's own LEARNINGS entry and commit 8d0b541's message both state the 58 correctly, so this one sentence contradicts two other records of the same measurement.

**Evidence**

- docs/engineering-journal/QUEUED.md:28 - the quoted sentence
- Measured by the controller: package suite with gh absent -> `58 failed, 333 passed`, exit 1; root suite with gh absent -> `Ran 834 tests ... FAILED (failures=1)`, exit 1
- docs/engineering-journal/LEARNINGS.md states it correctly: 'Re-run in this round with gh off PATH on the floor interpreter: 58 failed, 333 passed'
- Commit 8d0b541's message likewise says 'fails 58 tests'

**Suggested fix.** Replace the clause with what was measured: with gh absent the carried suite fails 58 tests because _gh's FileNotFoundError handler raises SystemExit past the swallowing except Exception; the suite passes only when a gh binary exists, authenticated or not.

### F74 — Filing's remedy routes agents onto a destructive verb

`P2` · confidence 100 · `agent-usability` / `safe-bounded-idempotent-resumable-context-cost` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/QUEUED.md:34`

Filing 2 tells upstream to route option creation onto `fields set-options --options-file` and says nothing about what that verb does. The GraphQL input overwrites the whole option set, so a file holding only the new option deletes every existing option and clears that field on every card. An upstream maintainer who edits the skill exactly as the filing asks produces a skill that walks an agent into project-wide field data loss. The package states the constraint in three other places; the omission is the filing's alone.

**Evidence**

- docs/engineering-journal/QUEUED.md:29-34 contains no occurrence of 'complete', 'overwrite', 'destructive' or 'id'
- plugins/mission-control/skills/board/references/graphql-queries.md:308-310 states the constraint
- The shipped create-option output already carries the warning at sdlc_manager.py:2056-2062
- fields_set_options' docstring requires the COMPLETE desired set with existing ids preserved

**Suggested fix.** Extend the filing to carry the constraint the replacement instruction must state, pointing the upstream fixer at the wording create-option already prints.

### F73 — Filing undercounts the subcommands that ignore --format

`P2` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/QUEUED.md:35`

Twelve subcommands ignore --format json, not ten. The filing's count matches only the handlers that take a fmt parameter and never use it; it misses `fields set-options` and `issue intent-envelope`, dispatched with no fmt at all. An upstream fixer implementing the filing's first option by finding the ten leaves the package's only destructive field verb emitting unparseable prose to an agent that asked for JSON.

**Evidence**

- AST walk finds ten fmt-taking handlers that never reference it
- fields_set_options is dispatched at :7257 and its signature takes no fmt; issue_render_intent_envelope at :7225 likewise, and prints markdown
- --format is defined once on the top-level parser, so all twelve accept it

**Suggested fix.** Change the count to twelve, name the two the fmt-parameter pattern misses, and put the parser-level refusal first since it closes all twelve.

### F70 — Filing routes a portable-path defect to the wrong owner

`P2` · confidence 100 · `agent-usability` / `capability-parity-reachability` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/QUEUED.md:56`

Six skills document their script at a path inside the upstream repository, which does not exist in a portable-only install. Filing 7 defers this upstream - but that path is correct upstream and wrong only here, so an upstream maintainer would either break their own operators or reject it. The filing's stated ground is also wrong for these files: all seven SKILL.md files are entrypoint transforms, not byte copies, so this repository already rewrites them and a downstream transform is the in-policy remedy.

**Evidence**

- Six hits for the upstream-repository path across the skills tree
- Controller-verified: all seven skills/*/SKILL.md are in custody.entrypoint_transforms under normalize-skill-frontmatter; zero are in custody.byte_copies
- docs/engineering-journal/QUEUED.md:14 states the ground as 'upstream bytes this repository may not patch'
- plugins/mission-control/README.md gives the shipped location as scripts/sdlc_manager.py

**Suggested fix.** Split filing 7: keep the missing flow Script Location section upstream, and move the six sibling paths to a downstream transform rewriting the fenced path to the package-relative script.

### F50 — Retired matrix banner links an already-superseded successor

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md:14`

The round updated the machine-readable superseded-by directive in both 2026-08-25 documents to name the current successor but left the human-readable banner three lines below pointing at the intermediate 2026-08-30 document, which is itself now superseded. The same file gives two different answers to 'what replaced this', and the visible one is wrong. The guard test added this round to catch exactly this exempts docs/evidence/, so it cannot see it.

**Evidence**

- docs/evidence/2026-08-25-mission-control-compatibility-matrix.md:14 names the intermediate document as 'the fresh assessment' while :2 names the -post-fingerprint-move successor
- The same split at docs/evidence/2026-08-25-mission-control-post-activation-readback.md:13
- tests/test_check_compatibility_matrix.py:1639-1641 begins its walk with `if EVIDENCE in path.parents: continue`
- Commit 863af58's message asserts the 2026-08-25 pair 'now names the final current successors', true only of the comment half

**Suggested fix.** Repoint both banners, and narrow the test's exemption to the file being scanned rather than the whole evidence directory.

### F51 — Matrix claims no client authenticated; one was

`P2` · confidence 100 · `security` / `secrets-cryptography-session-handling` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md:40`

The published record a third party reads to decide the assessment touched no live credential states universally that no client was authenticated - five lines after stating that Cursor Agent ran against the real authenticated home. The machine-readable method block repeats the universal verbatim, so an automated consumer inherits it, and the qualifier that reconciled the same exception in the 2026-08-25 predecessor was dropped rather than carried forward. The validator exits 0 on the self-contradiction because it never compares the two fields.

**Evidence**

- Same document, :35-37 'Cursor Agent ... was assessed against the real authenticated home' and :40 'No client was authenticated ... at any stage'
- The machine-readable method.credentials repeats the universal; method.isolation in the same JSON object contradicts it
- The predecessor carried the reconciling sentence this one drops - 'its authentication state recorded only as present, no credential created, changed, or read into this evidence, and no account identity published here'
- scripts/assess_clients.py sets home=REAL_HOME for the Cursor plan, so that client keeps the operator's live credential store

**Suggested fix.** Narrow both copies to 'No client was authenticated to GitHub and no GitHub credential was supplied; Cursor Agent ran under its own pre-existing authentication in the operator's real home', and restore the predecessor's qualifier.

### F49 — Plan's freeze record contradicts the landed branch

`P2` · confidence 100 · `documentation-clarity` / `shipped-behavior-parity` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2164`

The plan states in four places that the freeze is the last point any byte under the package changes, and the repair round then changed two bytes there, moving the fingerprint. The plan carries an amendment section for every prior review cycle and none for this repair round, so a reader taking it as the run's record is told the fingerprint U5 assessed is the one that ships, with no pointer to the second assessment that actually establishes it.

**Evidence**

- docs/plans/...-resync-plan.md:2164 - 'Last point at which any byte under plugins/mission-control/ changes'; the same claim unqualified at :1096 and :1722
- Controller-verified: `git diff --name-only 55a6511..863af58 -- plugins/mission-control` returns PROVENANCE.json and README.md, both from a1e84e0, which lands after the freeze point
- `grep -rn 'post-fingerprint-move|659f91f6' docs/plans/` returns nothing - the plan never names the move, the second assessment, or the two current documents

**Suggested fix.** Add an Amendment 6 recording that a1e84e0 moved the tree after the freeze for the F18/F11/F35 corrections, that U5 was re-run and re-bound at 863af58, and that 863af58 is issue #56's frozen commit; qualify the three freeze claims to point at it.

### F71 — Restored README disclosure contradicts measured behaviour

`P2` · confidence 100 · `agent-usability` / `context-constraints-acceptance-examples` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `plugins/mission-control/README.md:77`

The sentence this round added tells an agent that when the retired config is absent these subcommands degrade to {} 'rather than erroring'. Measured, absence does not degrade first: load_config falls through to a live gh api read, and with gh off PATH the FileNotFoundError handler exits 1. The claim about `board wip` is wrong too - _wip_limits falls back to hardcoded limits, not zeros, so it presents plausible numbers. An agent trusting this builds no error path for two subcommands the same README calls read-only, and budgets for no network round trips.

**Evidence**

- Controller-measured: with gh absent, `rollout status` and `config show` both exit 1 with 'ERROR: gh CLI not found'
- With a gh stub exiting 1, rollout status exits 0 after three live api reads - labels.json, beads-config.json and the schema
- plugins/mission-control/scripts/sdlc_manager.py:250-270 - the missing-file branch calls _gh before the except Exception
- _wip_limits returns {"Ready": 10, "In Progress": 5} when neither the schema nor the legacy config supplies limits
- This sentence is new text authored by this round - and it was adopted verbatim from the cycle-1 reviewer's suggested fix, which was itself wrong about board wip

**Suggested fix.** State the real ladder: absence triggers a live gh api read; only when that fails does the key degrade to {}; with gh absent the process exits 1. Describe board wip's hardcoded fallback separately.

### F72 — Undisclosed labels degradation makes gap-analysis a false all-clear

`P2` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `manual` -> `review-fixer` · *pre-existing* · new in cycle 2  
**Where:** `plugins/mission-control/README.md:105`

The label catalog has no vendored copy and no entry in the README's resolution-order list, yet it degrades through the same silent path as the retired config. When it degrades, rollout gap-analysis computes an empty required-label list, so nothing is missing and it prints 'All labels present' against a repository carrying none of them. An agent gating rollout work on gap-analysis records a clean verdict and skips deploy-labels, with no signal to distrust it.

**Evidence**

- Controller-verified: plugins/mission-control/config/ holds no labels.json, and the README never mentions it
- With a gh stub exiting 1, `config show` prints 'Labels: 0 defined' beside 'Projects: 3'
- Hermetic call with an empty labels config: rollout_gap_analysis prints '- All labels present'
- plugins/mission-control/scripts/sdlc_manager.py:2524 derives required_labels from the empty catalog

**Suggested fix.** Add labels.json to the resolution-order list and extend the degradation paragraph to say an empty catalog makes audit, deploy and gap-analysis treat 'no required labels' as 'all present'. File the missing refusal upstream.

### F12 — --format json silently ignored by twelve subcommands

`P2` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `manual` -> `human` · *pre-existing* · cycle 1: `F12`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:2026`

`--format` is a top-level flag every subcommand accepts; twelve print prose unconditionally, so an agent's json.loads raises with no signal the flag was unsupported. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- AST walk finds ten handlers taking `fmt` and never referencing it, plus `fields set-options` (:7257) and `issue intent-envelope` (:7225) dispatched with no fmt at all
- docs/engineering-journal/QUEUED.md filing 3 says ten; see F73

**Suggested fix.** Refuse json/markdown at the parser for subcommands that cannot honour them, which closes all twelve at once.

### F13 — No-op create-option exits zero, signalling success

`P2` · confidence 100 · `agent-usability` / `safe-bounded-idempotent-resumable-context-cost` · `manual` -> `human` · *pre-existing* · cycle 1: `F13`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:2058`

The documented no-op path falls off the end of the function, so an agent gating on exit status records success for a mutation never attempted. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/scripts/sdlc_manager.py:2026-2067 - sys.exit(1) appears only in the field-not-found arm
- docs/engineering-journal/QUEUED.md filing 4

**Suggested fix.** Exit non-zero, or emit a structured {"mutated": false, "next_command": ...} record under --format json.

### F14 — Mapping pull-request route leaves orphan remote branches

`P2` · confidence 100 · `api-contract` / `retry-idempotency-semantics` · `advisory` -> `downstream-resolver` · *pre-existing* · cycle 1: `F14`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:5578`

A failed `gh pr create` removes only the local worktree; the pushed branch is never deleted and its timestamped name means every retry mints another. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/scripts/sdlc_manager.py:5578 push precedes :5579 pr create; the finally at :5591-5597 removes only the worktree
- docs/engineering-journal/QUEUED.md filing 5

**Suggested fix.** Delete the pushed branch on failure and name it in the raised error.

### F15 — Board skill ships knowingly wrong Operations and Asgard ladders

`P2` · confidence 100 · `agent-usability` / `context-constraints-acceptance-examples` · `manual` -> `human` · *pre-existing* · cycle 1: `F15`  
**Where:** `plugins/mission-control/skills/board/SKILL.md:40`

Two of three board rows give a retired status ladder the shipped schema does not carry, with the correcting note eight lines below the table. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/skills/board/SKILL.md:40-41 and the caveat at :48
- plugins/mission-control/config/sdlc-schema.json gives all three boards workflow stage_flow
- docs/engineering-journal/QUEUED.md filing 6

**Suggested fix.** Replace both rows with the stage_flow list, or move the caveat above the table.

### F16 — Skill invocation paths do not resolve in a portable install

`P2` · confidence 100 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · *pre-existing* · cycle 1: `F16`  
**Where:** `plugins/mission-control/skills/flow/SKILL.md:71`

The flow skill has no Script Location section and every fenced example begins with a bare `sdlc_manager.py` nothing puts on PATH; the six sibling skills give a path inside the upstream repository a portable-only operator does not have. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for a future repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/skills/flow/SKILL.md contains no 'python3' and no location section; :71, :78, :83, :88, :94 are bare invocations
- The six siblings give $INFIQUETRA_SDLC_PATH/../infiquetra-claude-plugins/plugins/mission-control/scripts/sdlc_manager.py
- docs/engineering-journal/QUEUED.md filing 7 - but it routes the portable half to the wrong owner; see F70

**Suggested fix.** Split the filing: the missing flow section is upstream's; the six sibling paths are a downstream transform.

### F66 — Descriptor specification omits the new transform rule

`P2` · confidence 100 · `api-contract` / `specification-documentation-parity` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `ports/README.md:114`

ports/README.md names itself the only specification of the descriptor format, and its schema-3 section enumerates the rules a descriptor may select. That enumeration omits resolve-package-root-marker, which this run added and which the shipped descriptor selects for three paths. An author writing the next descriptor from the spec would conclude the rule three shipped entries already use is not selectable, and nothing fails when they get it wrong.

**Evidence**

- ports/README.md:114-117 lists four selectable rules
- scripts/sync_vendor_source.py:1002-1009 registers six, five of them selectable
- ports/mission-control.json selects the missing rule for three paths
- `git diff --stat 0eff36e..863af58 -- ports/README.md` is empty - the spec was never touched while the rule was added
- grep for ports/README across tests/ and scripts/ returns nothing

**Suggested fix.** Add the rule to the enumeration and add a test deriving the enumerated names from TRANSFORM_RULES so the next rule cannot be added without the spec moving.

### F54 — Real-home client is restrained only by prompt text

`P2` · confidence 100 · `security` / `authentication-authorization-tenant-isolation` · `manual` -> `human` · *pre-existing* · new in cycle 2  
**Where:** `scripts/assess_clients.py:314`

Three Cursor Agent stages launch a live authenticated coding agent inside the operator's own home with --trust, and the only restraint is a sentence appended to the prompt. That is an instruction to a model, not an enforced control, and both real controls miss it: refuse_unsafe_home enforces a declaration the Cursor stages never set, and refuse_unsafe_argv's mutating-verb half only applies when the command names a package script.

**Evidence**

- scripts/assess_clients.py:301-331 - home=REAL_HOME with --trust at :314, :321, :328
- scripts/assess_clients.py:228-237 - the whole restriction is 'Do not use filesystem, shell, network, or UniFi tools.'
- refuse_unsafe_home raises only for ISOLATED_ONLY plans or when writes_client_state is set, which defaults False and none of the three stages sets
- Measured: command_safety_problems on the Cursor argv returns [] while refusing an issue-close argv

**Suggested fix.** Add a real-home read-only declaration to StageSpec that refuse_unsafe_home enforces, and record in the matrix that the Cursor restriction is prompt-level. Both files are graded, so this follows the freeze alongside F36 and F38.

### F59 — The site-count table's documented escape hatch cannot be used

`P2` · confidence 100 · `architecture-maintainability` / `architectural-fit-ownership-single-sources` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:49`

The module docstring tells a maintainer that a second package selecting this rule 'must extend that table', and the join gate added this round makes that impossible: it asserts, per package, that the declared path set equals the whole table. Two packages with different path sets can never both be green - extending the table breaks mission-control's assertion, not extending it breaks the new package's. The only satisfiable outcome is that no second package ever uses the rule.

**Evidence**

- scripts/sync_vendor_source.py:46-52 - 'A second package that selects this rule must extend that table'
- tests/test_port_config.py:622-636 - per-config `assertEqual(declared, set(svs.PACKAGE_ROOT_MARKER_SITE_COUNTS))`; tests/test_sync_vendor_source.py:1793 repeats it
- The test's own docstring concedes it: 'a package that selects the rule anywhere must declare exactly the table'
- Controller-confirmed by reading both assertions; latent because only mission-control selects the rule today

**Suggested fix.** Key the table by package as well as path and compare each descriptor against its own slice, then correct the docstring.

### F58 — Generic planner hard-codes one transform rule's identity

`P2` · confidence 100 · `architecture-maintainability` / `dependency-direction` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:1140`

The F19 repair moved the Claude-specific coupling out of the rule and into plan_sync, the function every port's synchronization goes through, as an `if rule is PACKAGE_ROOT_MARKER_RULE` identity test. The coupling count went from one site to two: the rule still compiles in the marker and cannot read the descriptor, and the dispatcher now also knows this rule by name. Every future rule needing a descriptor precondition adds another branch to the same loop.

**Evidence**

- scripts/sync_vendor_source.py:1140-1151 - the identity test inside the entrypoint-transform loop
- scripts/sync_vendor_source.py:299-311 - TransformRule carries no precondition slot and apply receives no PortConfig
- The only identity comparison in the module is the new one

**Suggested fix.** Give TransformRule an optional precondition callable, attach the marker check at construction, and have plan_sync call it when present so the loop dispatches on the abstraction.

### F60 — The plan_sync descriptor refusal has no committed test

`P2` · confidence 100 · `architecture-maintainability` / `readability-naming-error-contracts` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:1143`

The refusal is the entire mechanism by which the F19 repair keeps the sync tool honest, and nothing exercises it. No test constructs a descriptor selecting the rule while naming a different client extension directory, and none asserts any substring of the message. The guard can be deleted, inverted, or weakened and check_repo plus all 834 tests stay green. Every other refusal branch of this rule got a test; the one that lives outside the rule got none.

**Evidence**

- grep for plan_sync across tests/ returns nothing
- The two tests that set client_extension_dir to a non-matching value assert on port_config.parse alone and never call plan_sync
- The synthetic descriptor that does reach synchronize selects only the split, guarded and frontmatter rules
- Controller-verified the guard does fire when driven directly - so it works today and is simply unguarded against regression

**Suggested fix.** Add a case building the synthetic descriptor with the marker rule selected and a non-matching client_extension_dir, asserting SyncError names both values, plus a companion proving the real descriptor does not raise.

### F56 — Matrix results table and summary are unbound prose

`P2` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `tests/test_check_compatibility_matrix.py:1364`

The F23 repair binds each client's JSON status to its JSON stages and it works. But the surface a human reads - the rendered Results table and the one-sentence summary the cycle-1 finding asked to have restored - is parsed by nothing in the checker or the tests. A mis-transcription between the record and the table, the likeliest hand-authoring error in a document carrying both, validates clean. The restoration bought a reader-facing surface with no gate behind it.

**Evidence**

- Falsified on a clean export: editing only the rendered OpenAI Codex row to works-directly and only the summary to '9 clients work directly' left `unittest tests.test_check_compatibility_matrix` at 160 tests OK and the checker printing 'validation passed' with exit 0, while the JSON stayed truthful
- Controller-confirmed: grep for table parsing in the checker and the tests returns nothing

**Suggested fix.** Parse the Results table in MissionControlMatrixBindingTest and assert each row's status, version and four stage cells equal the JSON record, plus assert the summary counts equal Counter(status).

### F55 — New superseded-link test walks gitignored directories

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `tests/test_check_compatibility_matrix.py:1639`

The guard added this round iterates ROOT.rglob('*.md') with no filter for untracked or gitignored paths. `.claude/` is gitignored but is a real subdirectory of the checkout and, in this repository's own agent workflow, holds a full repo copy per worktree. The test therefore fails or passes on content outside version control: green in CI, red on the developer machine the repository tells the developer to run it on. The unguarded read_text adds a second machine-dependent failure on any non-UTF-8 markdown.

**Evidence**

- Reproduced on a clean export: creating .claude/worktrees/sibling/docs/README.md from the cycle-1 revision makes the test fail naming that path
- The operator's main checkout holds 1,883 markdown files under .claude/, seven carrying the exact bare anchor the test rejects
- Controller-confirmed: .claude/ exists in this worktree with 2 markdown files
- tests/test_check_compatibility_matrix.py:1639-1641 - the walk and its single EVIDENCE exemption

**Suggested fix.** Enumerate from `git ls-files "*.md"`, or skip paths whose parts intersect {.claude, .git, .venv, node_modules, .saga, .serena}; add errors=replace on the read.

### F25 — Root suite executes unpinned code from outside the repository

`P2` · confidence 100 · `security` / `dependency-supply-chain` · `manual` -> `human` · *pre-existing* · cycle 1: `F25`  
**Where:** `tests/test_mission_control_rule_audit.py:75`

The mandated validation command exec_modules a card_validator found by searching HOME_LAB_PATH and two home paths; the verdict depends on that checkout's content. Dispositioned pre-existing/human and unchanged this round.

**Evidence**

- tests/test_mission_control_rule_audit.py:51-64 and :75 - spec.loader.exec_module on an out-of-repository file
- ports/mission-control.json:196 states the contrary rule for the dropped upstream twin

**Suggested fix.** Vendor a digest-pinned decision corpus under tests/fixtures/ and assert against that.

### F26 — Card-validator suite reports the machine, against the run's own rule

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `human` · *pre-existing* · cycle 1: `F26`  
**Where:** `tests/test_mission_control_rule_audit.py:138`

Twenty-three of the module's tests skip when the external checkout is absent, so they never run in CI and run against unpinned code locally. Dispositioned pre-existing/human; the disposition is right but the residual is filed nowhere. See F57.

**Evidence**

- Controller-confirmed: the class runs 23 tests with 0 skips on this machine; CI provisions no home-lab checkout
- docs/engineering-journal/LEARNINGS.md:689 - 'A test that asserts on the machine it runs on reports the machine, not the code'

**Suggested fix.** Record the CI-inert set in QUEUED.md, or vendor the corpus.

### F57 — Rule-audit module is 57 percent inert in CI

`P2` · confidence 100 · `testing` / `requirements-regression-coverage` · `advisory` -> `human` · *pre-existing* · new in cycle 2  
**Where:** `tests/test_mission_control_rule_audit.py:138`

Twenty-five of the module's forty-four tests skip when two external checkouts are absent, which is always in CI. The root README states without qualification that the audit runs class-first against live authority - true only on a machine carrying those checkouts. The run's own decision rationale rejects exactly this shape as grounds for dropping a test from the package, and no QUEUED item files the exception.

**Evidence**

- Measured with home patched to a nonexistent path: `Ran 44 tests ... OK (skipped=25)`; on the operator's machine the same module runs 44 with 0 skips
- README.md:80 carries the unqualified claim, and it predates this change
- grep for card_validator or home-lab in QUEUED.md returns no open item

**Suggested fix.** File the CI-inert set in QUEUED.md and qualify README.md:80. No test change is needed to close the disclosure gap.

### F27 — Two tests still write inside the fingerprinted package tree

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `review-fixer` · *pre-existing* · cycle 1: `F27`  
**Where:** `tests/test_mission_control_rule_audit.py:493`

PARTIAL. The repair redirected one of three in-tree write sites. Two parity-drift tests still append bytes directly to `config/generated/issue_contract_data.py` and `issue_contract_shim.py`, both inside the 71-file fingerprint, restoring only in a finally. During that window the live tree does not hash to the value every evidence document binds, and an interrupted run leaves a tracked file drifted. The repair commit states the fingerprinted tree is never written, which is false of the file as a whole.

**Evidence**

- Measured on a clean export: after a full suite run, `find . -newer marker` returned exactly those two files and nothing else
- Both are inside the fingerprint - the 71-file enumeration includes them; the restore is byte-exact so the digest recovers, but the write is real
- tests/test_mission_control_rule_audit.py:493 `data_path.write_bytes(original + b"\n# drift\n")`, repeated at :506

**Suggested fix.** Copy the two generated artifacts and their .sha256 sidecars into a TemporaryDirectory and patch the parity module's GENERATED path for the test's duration, matching the repaired template test.

### F30 — CI installs plugin test dependencies unpinned

`P3` · confidence 100 · `security` / `dependency-supply-chain` · `gated_auto` -> `release` · *pre-existing* · cycle 1: `F30`  
**Where:** `.github/workflows/ci.yml:59`

The plugin-tests job resolves four packages at run time with no constraint or hash pinning, then executes the ported suite. Dispositioned pre-existing/release; unchanged this round.

**Evidence**

- .github/workflows/ci.yml:59 - `python -m pip install --upgrade pip requests urllib3 pyyaml pytest`

**Suggested fix.** Pin with a hashed requirements file, matching the hermeticity standard the first job documents.

### F68 — Root README client-status counts have no gate

`P3` · confidence 100 · `api-contract` / `specification-documentation-parity` · `gated_auto` -> `review-fixer` · new in cycle 2  
**Where:** `README.md:81`

Every other derived number in the root README is recomputed by a test - the file count, the test count, the pin, the version. The per-status client tally is the one still retyped by hand, and it went stale inside this single review cycle: the round hand-edited it after the fingerprint move forced a re-assessment. The checker already computes exactly these counts, and the evidence link is gated, so the next re-assessment leaves a false published tally beside a correctly repointed link.

**Evidence**

- README.md:81 - '3 directly, 7 via adapter, 0 failed', with the breakdown at :84-91
- The repair diff shows the counts changing 2 to 3 and 1 to 0 by hand with no test change
- scripts/check_compatibility_matrix.py's summarize already derives them; the no-arg run prints exactly those numbers
- grep across tests/ finds nothing reading README.md for client statuses

**Suggested fix.** Extend RootReadmePinTests to run summarize over the current matrix and assert the README sentence matches, on the pattern the file-count derivation already uses.

### F78 — One repair round declared its red window; the other did not

`P3` · confidence 100 · `documentation-clarity` / `shipped-behavior-parity` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `docs/engineering-journal/QUEUED.md:11`

The round-2 commit declares its own red state in its message - 'the six evidence-binding tests are RED AS EXPECTED ... the evidence is not edited to match the moved tree' - which is exactly right. Two round-1 commits are also red, for two commits, and say nothing: a guard test lands before the document repoint it guards. Bisection across the branch therefore hits an undeclared red window in a run whose discipline is otherwise to declare them.

**Evidence**

- Controller-measured per commit: f4da07e and 0ff932e each FAILED (failures=1) on test_no_prose_outside_evidence_links_a_superseded_document; 8d0b541 lands the docs/README repoint and is green
- a1e84e0 is FAILED (failures=6) and its message declares exactly that
- Neither f4da07e's nor 0ff932e's message mentions a red suite

**Suggested fix.** Note the expected red in the commit that introduces a guard ahead of its fix, or order the repoint before the guard.

### F32 — Issue #52's line-claim count is still uncorrected

`P3` · confidence 100 · `documentation-clarity` / `completeness-audience-prerequisites` · `safe_auto` -> `review-fixer` · cycle 1: `F32`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378`

R12 requires four surviving line-number claims; issue #52 says three and its grep omits the _open_mapping_pr claim. Deferred because no issue mutation was permitted mid-run - the right call - but the deferral is recorded in neither of the two places a closer would look. See F50's sibling.

**Evidence**

- docs/plans/...-resync-plan.md:378 vs GitHub issue #52's acceptance criterion
- The plan's section 11.2 lists five brief-versus-issue differences and does not list this one; QUEUED.md's new section files only upstream defects

**Suggested fix.** Add a sixth item to section 11.2 recording the #52 discrepancy and the intended correction.

### F33 — Plan and acceptance still say two superseded documents

`P3` · confidence 100 · `documentation-clarity` / `completeness-audience-prerequisites` · `safe_auto` -> `review-fixer` · cycle 1: `F33`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:399`

PARTIAL. Four mission-control evidence documents now carry a superseded stamp, not two. R33's verifier column was repaired but the requirement text and the section 12 checklist still read 'Both superseded documents', so an operator working the list checks the 2026-08-25 pair and never checks the 2026-08-30 pair this round retired.

**Evidence**

- docs/plans/...-resync-plan.md:399 (R33) and :2473 (the checklist) both say 'Both superseded documents'
- Controller-verified: four of the six mission-control evidence documents carry matrix-status: superseded
- The substance is covered - MissionControlSupersededDocumentTest asserts the intermediate pair

**Suggested fix.** Say 'All four superseded mission-control documents - the 2026-08-25 pair and the 2026-08-30 pre-fingerprint-move pair' in both places, and correct U5's Files-owned list to the shipped filenames.

### F09 — Section 8.2 still records twelve landed commits

`P3` · confidence 100 · `documentation-clarity` / `terminology-cross-document-consistency` · `safe_auto` -> `review-fixer` · cycle 1: `F09`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2175`

PARTIAL. The repair corrected KTD15's table to fourteen and rewrote Q8's heading, but section 8.2 - the section whose subject is what is on the branch - still asserts twelve. The plan now answers the same question two ways, and 8.2 is the one a reader consults for branch state.

**Evidence**

- docs/plans/...-resync-plan.md:2175-2176 - 'All twelve child-scoped commits ... live on orch-agent-plugins-50'
- docs/plans/...-resync-plan.md:853-854 and :2393 both say fourteen as landed
- Controller-verified: the branch carries fourteen unit commits

**Suggested fix.** Replace 'All twelve child-scoped commits' with 'All fourteen child-scoped commits as landed (twelve by design; U0 shipped in three)'.

### F34 — Four amendments still cite one overwritten review file

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `manual` -> `review-fixer` · cycle 1: `F34`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2482`

NOT FIXED. Four sections each cite the same doc-review path as the artifact for a different cycle with a different bound revision and verdict; only one file exists there and it holds cycle 7. The round added review SHAs to four status paragraphs but left the four citations the finding named, and left the false closing sentence.

**Evidence**

- docs/plans/...-resync-plan.md:2482, :2627, :2679, :2785 all cite the same path with revisions 1e4da2b, b164026, 4083220, 02c8bed
- docs/plans/...-resync-plan.md:2487 - 'That is the last revision of this plan the document review examined', contradicted by cycles 3, 4, 6 and 7

**Suggested fix.** Append each cycle's review commit SHA to the four Artifact lines and delete the closing sentence.

### F36 — Every dropped-path entry repeats all three drop reasons

`P3` · confidence 100 · `correctness` / `state-data-invariants-transactions-concurrency` · `manual` -> `downstream-resolver` · *pre-existing* · cycle 1: `F36`  
**Where:** `plugins/mission-control/PROVENANCE.json:21`

The manifest builder stamps one concatenated string onto every removed_from_source entry, so no entry says why its own path was dropped. Deferred as needing a graded edit - but that ground is over-stated; see F65's sibling.

**Evidence**

- scripts/sync_vendor_source.py:1370-1375 emits config.dropped_reason for every dropped path
- plugins/mission-control/PROVENANCE.json:21, :25, :29 - three paths, one byte-identical reason

**Suggested fix.** Split the descriptor's existing '<path>: <reason>.' clauses in the emitter, which needs no graded edit.

### F67 — Mutating-operation contract is a bare action-token list

`P3` · confidence 100 · `api-contract` / `interface-contract-compatibility` · `manual` -> `human` · *pre-existing* · new in cycle 2  
**Where:** `ports/mission-control.json:139`

The single safety authority splits a command on whitespace and intersects bare tokens with the declared mutating set. The descriptor holds bare action tokens with no group qualifier, so neither the contract nor the predicate can distinguish `board move` from `flow move`. The upstream change that silently widens the read-only set is any new mutating verb whose token is already declared read-only - view, list, show, status, audit, discover, prepare, progress, wip. The new verb-surface gate has the same weakness, so such a verb passes end to end.

**Evidence**

- ports/mission-control.json:139-165 lists bare tokens with no group
- scripts/check_compatibility_matrix.py:882-887 tokenizes and intersects; scripts/assess_clients.py:647 names it the single authority
- Another reviewer falsified the gate: adding a `board status` parser left the gate green, while a novel token correctly failed it
- tests/test_mission_control_readme.py:83-117 declares view, list, show, status, audit, discover, prepare, progress and wip read-only

**Suggested fix.** Make each entry a group-qualified pair, bump the descriptor schema, and match adjacent token pairs. Until then record the collision hazard in QUEUED.md.

### F38 — Evidence redaction check never reads document prose

`P3` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `gated_auto` -> `human` · *pre-existing* · cycle 1: `F38`  
**Where:** `scripts/check_compatibility_matrix.py:940`

The public-evidence control walks only the strings inside the extracted JSON record, so narrative outside the fenced block is never scanned. Deferred because the fix touches a graded file; the disposition is right.

**Evidence**

- scripts/check_compatibility_matrix.py:940 walks only the parsed record
- Latent, not live: running the rules over each current document's whole text returns zero problems

**Suggested fix.** After the freeze lifts, scan the text outside the fenced record too.

### F69 — Sync tool docstring contradicts its own recorded exception

`P3` · confidence 100 · `api-contract` / `specification-documentation-parity` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:11`

The F39 repair added a paragraph disclosing the package-specific table but left standing, thirty-five lines above it, the absolute claim it contradicts. The module now says both 'Nothing about a particular package is compiled into this file' and 'One exception to the package-agnostic contract is recorded rather than hidden'. A reader who stops at the lede - which is where a porting author starts - carries away the false version.

**Evidence**

- scripts/sync_vendor_source.py:11-13 carries the absolute claim
- scripts/sync_vendor_source.py:46-52 carries the exception paragraph added this round
- The repair diff shows only the second paragraph was added

**Suggested fix.** Qualify the lede so the two agree - 'Nothing about a particular package is compiled into this file except the one exception recorded below.'

### F62 — Site-count refusal names a class chosen by hash seed

`P3` · confidence 100 · `api-contract` / `serialization-errors` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:840`

The repair that removed the bare KeyError also changed the site-class loop from a fixed tuple to a set. Set iteration over strings depends on PYTHONHASHSEED, so when a file mismatches on more than one class the tool names a different class on different runs. The rule's stated contract is that a refusal names the site class, and that its output is reproducible from the source bytes alone; a diagnostic that changes between two runs of the same input breaks both.

**Evidence**

- scripts/sync_vendor_source.py:840 iterates expected_classes, a set literal defined at :823
- Measured, same input and revision: PYTHONHASHSEED=0 named 'call'; PYTHONHASHSEED=3 named 'finder'
- Controller-measured independently across five default-seed runs: is_file, call, finder, raises, finder
- The committed tests are not flaky - each mismatches on a single class or asserts only 'found 0' - so nothing catches it

**Suggested fix.** Keep the set for the membership check and iterate a fixed SITE_CLASSES tuple for the count comparison.

### F65 — zip truncation drops the definition-before-call check

`P3` · confidence 100 · `correctness` / `boundary-types-serialization-numeric-time` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:861`

The F43 repair replaced the single-pair ordering check with `zip(finders, calls)`. zip stops at the shorter sequence, and the count check never requires the finder and call counts to be equal. A future row declaring unequal counts leaves the surplus definitions with no ordering check, so a file carrying a definition after the module-scope call - a shape the rule's own error text says it does not describe - is accepted silently instead of refused. The rewrite output stays correct, so this narrows a shape assertion rather than corrupting bytes.

**Evidence**

- Measured with a row declaring finder 2 / call 1 and a body ordered definition, call, definition: the transform returned OK and raised nothing
- Symmetric control with finder 2 / call 2 and a call before both definitions correctly raised SyncError naming the ordering
- scripts/sync_vendor_source.py:823 and :840-847 compare each class against its own count only; no cross-class constraint exists

**Suggested fix.** Require counts['call'] in (0, counts['finder']) in the row-shape check, or check each finder against the nearest following call by index.

### F63 — Marker guard compares a constant the rewrite ignores

`P3` · confidence 100 · `correctness` / `intent-behavior-completeness` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:1141`

The new refusal exists to stop shipping a package whose scripts and manifest live in different directories. It compares the descriptor against PORTABLE_PACKAGE_ROOT_MARKER, but the emissions never read that constant - they hardcode the literal. Rename the directory and the constant and descriptor move together, the guard passes, and the transform keeps anchoring carried scripts on the old name while the manifest relocates to the new one. --check cannot catch it: the stale literal is on both sides of the comparison.

**Evidence**

- Controller-reproduced: setting PORTABLE_PACKAGE_ROOT_MARKER to a renamed value still emits the old literal - 'emitted renamed? False', 'emitted the old literal? True'
- The constant is referenced only in classification and the guard, never in emission
- synchronize with check_only re-derives with the same stale literal, so the check goes green

**Suggested fix.** Build the three portable emissions from the constant with f-strings so a rename cannot decouple the guard from the output.

### F76 — New sync refusal prescribes a wrong remedy

`P3` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `scripts/sync_vendor_source.py:1149`

The guard added this round fires when a port selects the marker rule while naming a different client extension directory. Its remedy line offers, first, naming the descriptor's directory the Claude one - which instructs a non-Claude port to declare a Claude-named directory, precisely the vendor-neutrality defect the module's docstring was corrected to disclose. An agent running the synchronization for a second package and following the message produces a misconfigured port.

**Evidence**

- scripts/sync_vendor_source.py:1143-1151 - the message ends 'Name the descriptor's client_extension_dir ... or re-custody the path'
- scripts/sync_vendor_source.py:45-49, added by the same round, gives the correct remedy the message omits

**Suggested fix.** Replace the first branch with the docstring's remedy - extend the table and parameterize the rule's marker on the descriptor - and stop offering the rename.

### F44 — No gate checks skill commands against the CLI surface

`P3` · confidence 100 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · *pre-existing* · cycle 1: `F44`  
**Where:** `tests/test_mission_control_readme.py:275`

The fenced-command guard binds only the package README. The new verb-surface gate binds the parser to the declared verb tables, but nothing extracts commands from the seven SKILL.md files an agent invokes from. Dispositioned pre-existing/human.

**Evidence**

- tests/test_mission_control_readme.py:275-301 reads plugins/mission-control/README.md only
- The suite is green while skills/labels/SKILL.md:120 documents a verb the package classifies as a no-op

**Suggested fix.** Extend the extraction over skills/*/SKILL.md and their references.

### F64 — F18 count gate matches a substring, not the number

`P3` · confidence 100 · `correctness` / `state-data-invariants-transactions-concurrency` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `tests/test_port_config.py:596`

The new gate does recompute both carried-test counts from the custody arrays, then asserts with assertIn on a formatted string. A stale prose count whose recomputed replacement is a suffix of it passes - if the byte-copy count fell to 6 while the prose still read 26, the gate would pass on the stale text, reintroducing the defect it was written to close. The same round applied the stricter parse-and-compare pattern one file over and did not apply it here.

**Evidence**

- Measured: the real byte-copy test count is 26 and `'6 as byte copies' in notes` is True; likewise '2 as ... transforms' is a substring of '12 as ... transforms'
- tests/test_port_config.py:596 and :602 are the two assertIn calls; the docstring claims a stale prose count fails here
- tests/test_mission_control_rule_audit.py was changed this round to parse the README claim and compare the parsed value

**Suggested fix.** Replace both assertIn calls with a regex parse and an assertEqual on the integer.

### F75 — Prose-to-table join checks paths, never the counts

`P3` · confidence 100 · `architecture-maintainability` / `simplicity-abstraction-duplication-changeability` · `manual` -> `review-fixer` · new in cycle 2  
**Where:** `tests/test_sync_vendor_source.py:1027`

The F41 repair binds the rule prose to the count table by path membership only, but the contradiction the finding named is about counts. The prose states per-file counts in English, that string is copied verbatim into the shipped provenance record as each transform entry's rule text, and a third copy sits in the descriptor notes. Change a row and the prose still names every path, so the gate stays green while the shipped custody record describes a transform that no longer matches the code that produced the bytes.

**Evidence**

- tests/test_sync_vendor_source.py:1034-1043 - the whole assertion is a path-membership loop
- Measured: mutating a row's counts left 'all table paths still in prose' True and the prose still claiming the old shape
- The same prose is recorded as the transform_rule value in plugins/mission-control/PROVENANCE.json

**Suggested fix.** Assert the counted claims too - for each path, that the prose names each nonzero class and omits the zero ones - or render the count clauses from the table and assert the rendered sentence appears verbatim.

### F46 — PyYAML guard regex still matches any workflow line

`P3` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `safe_auto` -> `review-fixer` · cycle 1: `F46`  
**Where:** `tests/test_sync_vendor_source.py:1845`

PARTIAL. The repair replaced a file-global substring with `assertRegex(ci, r"pip install .*\bpyyaml\b")` and its docstring claims the check is now anchored on the install line. assertRegex still searches the whole file, so a comment mentioning a historical pip install satisfies it while the real run: line has dropped the dependency. The narrowing is genuine - the realistic drop case does go red - but the docstring claims more than the code does.

**Evidence**

- Falsified against the real workflow: replacing the install line with '# historical: we used to python -m pip install pyyaml here' plus a pyyaml-free install leaves the regex matching
- Control: replacing it with '# NOTE: pyyaml was dropped here' plus a pyyaml-free install does fail the test

**Suggested fix.** Require a line that both starts with run: after stripping and matches the pip-install pattern, so a comment cannot satisfy it.

### F53 — Verb-surface gate self-skips on a dependency it does not use

`P3` · confidence 100 · `security` / `authentication-authorization-tenant-isolation` · `safe_auto` -> `review-fixer` · new in cycle 2  
**Where:** `tests/test_sync_vendor_source.py:2048`

The new gate binding the declared verb split to the live CLI opens with a guarded yaml import and skips when it fails, so the one control disappears silently rather than failing. The guard is unnecessary: sdlc_manager builds its complete parser with PyYAML unavailable. Whether the gate executes therefore depends on what the runner image ships rather than on anything the repository declares - the same 'a gate that reports the machine' shape the repository files against itself.

**Evidence**

- tests/test_sync_vendor_source.py:2046-2050 - the try/except ModuleNotFoundError skipTest
- Measured with yaml blocked: the test reports skipped, while a parser walk under the same block printed 9 top-level groups, 48 group/action pairs and no unclassified actions
- The validate job installs nothing and is the only job that runs tests/

**Suggested fix.** Delete the guard - the test does not use yaml and the parser does not need it.

### F77 — Evidence filenames invert the repository's supersession convention

`P3` · confidence 75 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · new in cycle 2  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md:1`

Across the ten prior superseded documents the suffixed filename is the retired one. This round inverted that: the suffixed file is current and the unsuffixed one is superseded. An agent asked for the current compatibility record that lists the directory and applies the pattern the directory demonstrates picks the retired document. Both READMEs point at the right files and the retired ones open with a banner, so the cost is a wrong first open rather than a wrong answer.

**Evidence**

- The unifi and agent-launcher families all use the suffix for the retired document
- Controller-confirmed: the unsuffixed 2026-08-30 matrix carries matrix-status superseded and the suffixed one carries current
- The current readback carries no status directive at all, while the retired one does
- The convention is inferred from filenames, not written down anywhere

**Suggested fix.** Rename so the current pair is unsuffixed and the retired pair carries a -pre-fingerprint-move suffix, add a status directive to the current readback, and update the two README pointers and the hand-registered test paths.

## Consolidated fix requests

Grouped by owner, routing class and overlapping paths. All 17 are unresolved. Cycle 1's
fix identifiers do not carry forward: the consolidation is recomputed from the cycle-2
finding set, so a repaired finding is evidenced by its absence rather than by a resolved id.

| Fix id | Route | Findings | Paths |
|---|---|---|---|
| `fix-7bba1b703848` | manual -> human | F77 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md` |
| `fix-46dca44e4ee6` | gated_auto -> review-fixer | F68 | `README.md` |
| `fix-1f32ffa324f9` | manual -> review-fixer | F61 | `docs/engineering-journal/DECISIONS.md` |
| `fix-bd77f3efb731` | manual -> review-fixer | F70 | `docs/engineering-journal/QUEUED.md` |
| `fix-6767ccfca18e` | manual -> review-fixer | F34, F49 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-f3eb49a71c40` | manual -> review-fixer | F71 | `plugins/mission-control/README.md` |
| `fix-bddf2291754e` | manual -> review-fixer | F58, F59, F60 | `scripts/sync_vendor_source.py` |
| `fix-e821ff2254aa` | manual -> review-fixer | F55, F56 | `tests/test_check_compatibility_matrix.py` |
| `fix-1a26ae3dbb03` | manual -> review-fixer | F75 | `tests/test_sync_vendor_source.py` |
| `fix-73409235a365` | safe_auto -> review-fixer | F48, F73, F74, F78 | `docs/engineering-journal/QUEUED.md` |
| `fix-c781cca536a1` | safe_auto -> review-fixer | F50 | `docs/evidence/2026-08-25-mission-control-compatibility-matrix.md` |
| `fix-a883fd3fd2ac` | safe_auto -> review-fixer | F51 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-post-fingerprint-move.md` |
| `fix-3a726facf6c1` | safe_auto -> review-fixer | F09, F32, F33 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-74a8520ef735` | safe_auto -> review-fixer | F66 | `ports/README.md` |
| `fix-d32bf51ebf75` | safe_auto -> review-fixer | F62, F63, F65, F69, F76 | `scripts/sync_vendor_source.py` |
| `fix-e86ea646b124` | safe_auto -> review-fixer | F64 | `tests/test_port_config.py` |
| `fix-f94a0ef17b37` | safe_auto -> review-fixer | F46, F53 | `tests/test_sync_vendor_source.py` |

## Lens scores

Seven caller-supplied lenses, at most three concurrent. Acceptance requires a derived
overall of at least 9.0 **and** every applicable dimension at 7.0 or above; the derived
overall is the mean of the applicable dimension scores.

| Lens | Cycle 1 | Cycle 2 | Move | Dimensions below the 7.0 floor |
|---|---|---|---|---|
| `architecture-maintainability` | 6.71 | 6.43 | -0.29 | `dependency-direction`, `simplicity-abstraction-duplication-changeability`, `readability-naming-error-contracts`, `significant-decision-documentation` |
| `correctness` | 7.80 | 8.20 | +0.40 | — |
| `security` | 7.40 | 7.40 | 0.00 | `secrets-cryptography-session-handling` |
| `testing` | 4.80 | 7.40 | +2.60 | `determinism-isolation-diagnostics-maintainability` |
| `api-contract` | 7.86 | 8.14 | +0.29 | — |
| `agent-usability` | 6.60 | 6.40 | -0.20 | `capability-parity-reachability`, `context-constraints-acceptance-examples`, `machine-readable-output-actionable-errors` |
| `documentation-clarity` | 6.00 | 7.00 | +1.00 | `structure-navigation` |

Two regressions are recorded in the typed result: `architecture-maintainability`
6.71 → 6.43 and `agent-usability` 6.60 → 6.40.

### Per-dimension detail

**`architecture-maintainability`** — `architectural-fit-ownership-single-sources` 7, `separation-of-concerns` 7, `dependency-direction` 6, `simplicity-abstraction-duplication-changeability` 6, `readability-naming-error-contracts` 6, `conventions-portability-configuration` 7, `significant-decision-documentation` 6

**`correctness`** — `intent-behavior-completeness` 8, `state-data-invariants-transactions-concurrency` 8, `boundary-types-serialization-numeric-time` 8, `side-effects-errors-resource-lifecycle` 9, `caller-enum-consumer-completeness` 8

**`security`** — `authentication-authorization-tenant-isolation` 7, `input-trust-boundaries-injection` 9, `secrets-cryptography-session-handling` 6, `dependency-supply-chain` 7, `confidentiality-logs-errors-egress` 8

**`testing`** — `requirements-regression-coverage` 8, `negative-edge-state-concurrency-time` 8, `behavior-sensitive-assertions` 7, `realistic-seams-mocks-integration-evidence` 8, `determinism-isolation-diagnostics-maintainability` 6

**`api-contract`** — `interface-contract-compatibility` 7, `versioning-deprecation` 8, `serialization-errors` 8, `retry-idempotency-semantics` 9, `pagination-rate-limits` 9, `sdk-generated-client-impact` 9, `specification-documentation-parity` 7

**`agent-usability`** — `capability-parity-reachability` 6, `discoverability-invocation-schemas` 7, `context-constraints-acceptance-examples` 6, `machine-readable-output-actionable-errors` 6, `safe-bounded-idempotent-resumable-context-cost` 7

**`documentation-clarity`** — `shipped-behavior-parity` 7, `completeness-audience-prerequisites` 7, `structure-navigation` 6, `terminology-cross-document-consistency` 7, `runnable-examples-actionability` 8, `runbook-safety-rollback-links-generated-drift` 7

## Coverage

**Residual risks.**

- One cycle remains. A third scoring cycle is the last; if it does not accept, the outcome
  becomes `cycle_cap_best_available` and every residual is surfaced against that revision.
- The branch is still unpushed, so no continuous-integration run has ever exercised this work.
  The dependency-free job is now green on a controlled bare interpreter, which is the closest
  proxy available without pushing.
- Eight findings are carried upstream defects the runbook forbids patching here. They reach
  the catalog only through a future repin. Two of the seven filings need correcting before
  anyone acts on them (`F70`, `F74`), and a third undercounts its subject (`F73`).
- Two fixes remain blocked on the graded mutation-proof freeze (`F36`, `F38`), joined this
  cycle by a third (`F54`). All three are correctly deferred and correctly recorded.

**Testing gaps.**

- No CI job runs `sync_vendor_source.py --check`, so custody drift is caught only when a person
  runs it with an upstream clone on disk. Unchanged from cycle 1.
- The new superseded-link guard walks gitignored directories (`F55`), so its verdict depends on
  what is beside the checkout — green in CI, red on the machine the repository tells you to run
  it on.
- Twenty-five of the rule-audit module's forty-four tests are inert in CI (`F57`).

**Method.** Seven caller-supplied lenses, exactly as specified: architecture-maintainability,
correctness, security, testing, api-contract, agent-usability, documentation-clarity. Maximum
concurrency observed: **3**. Each ran read-only in a disposable worktree. The caller-supplied
selection was the approval record, reused from cycle 1 with applicability unchanged; no
lens-selection question was asked. Cycle 1 was replayed from its persisted `review_result.v1`
before cycle 2 was recorded, so the typed result carries real cycle history and genuine
regression detection rather than a fresh state. This review mutated no reviewed source and
created no commit, no pull request and no issue.

## Route

**`repairs_requested` → `dispatch_repairs`.** Seventeen consolidated fix requests go back to
the author or to `/work`. Suggested order:

1. **The records, first — they are cheap and they are what a reader trusts.** `F48` (the false
   hermetic claim), `F61` (the stale U5 decision entry), `F49` (the missing amendment), `F50`
   (the retired banners), `F09`, `F33`, `F34`, `F51` (the credentials contradiction).
2. **The guards that cannot fail.** `F60` (test the `plan_sync` refusal), `F63` (derive the
   emission from the constant), `F56` (bind the Results table), `F55` (stop walking gitignored
   paths), `F64`, `F46`.
3. **The shape work.** `F59` (key the table by package), `F58` (precondition on the
   abstraction), `F65`, `F62`, `F75`.
4. **The agent-facing text.** `F71` and `F72` — both are wrong about shipped behaviour today.
5. **The filings, before anyone acts on them.** `F70`, `F73`, `F74`.
6. **Deferred to the freeze lift or to a repin**, unchanged: `F01`, `F02`, `F12`–`F16`, `F25`,
   `F26`, `F30`, `F36`, `F38`, `F44`, `F54`, `F57`, `F67`.

Resubmit for cycle 3 only after the repairs land. The retained-lens delta check applies then:
a lens whose reviewed revision did not change keeps its score.
