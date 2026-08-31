---
title: Saga Code Review — Agent Plugins #50 mission-control resynchronization, final cycle 3
reviewed_revision: 16d88906bee0cad8342b0509b080757d0d9b39fa
base_revision: 0eff36ef432d90e3ba046ab0ca464168932034da
previous_cycle_revision: 863af5888e548b6c95f40d3fd571c9365d136dea
branch: orch-agent-plugins-50
issue_ref: infiquetra/infiquetra-agent-plugins#50
plan_path: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
result_path: docs/code-reviews/2026-08-31-issue-50-mcresync-final-cycle-3-code-review-16d88906-result.json
outcome: cycle_cap_best_available
next_action: continue_with_best_available
cycle: 3
cycle_cap: 3
mode: interactive
---

# Saga Code Review — final cycle

This is round three. The runbook caps review at three, so there is no round four: the run
stops here and records what remains rather than looping. Everything below is sorted into
**blockers** — things that must be resolved before this merges — and **residuals**, which are
real, evidenced, and correctly carried forward.

- **Reviewed revision:** `16d88906bee0cad8342b0509b080757d0d9b39fa` (`16d8890`)
- **Base:** `0eff36ef432d90e3ba046ab0ca464168932034da` — the merge base, and `origin/main`
- **This round:** `git diff 863af58..16d8890` — 26 files, +6,264 / −326
- **Working tree:** clean at the frozen revision; nothing was mutated by this review

## Outcome

> **`cycle_cap_best_available`.** Not `repairs_requested` — at the third cycle the consensus
> module forces a terminal candidate, so the typed token is the cycle-cap one and its single
> allowed resume transition is `continue_with_best_available`. That is the correct terminal
> state for a capped run, and it is not a failure verdict: it means the review is out of
> rounds, not that the work is unsound.

- Typed contract (`review_result.v1`): **`cycle_cap_best_available`**, next action
  `continue_with_best_available`
- **All 13 independent gates pass.** Cycle 1 failed two; cycle 2 failed none; cycle 3 failed
  none. Readiness is held open purely by the numeric rule, which needs a 9.0 derived overall
  no lens reaches.
- Findings: **P0=0, P1=3, P2=14, P3=21** — 38 total, against 47 in cycle 1 and 49 in cycle 2
- **2 blockers, 36 residuals**
- Every one of the seven lenses posted its best score of the run. Six of seven now have **no
  dimension below the 7.0 floor**; in cycle 1 all seven had breaches.

| Lens | Cycle 1 | Cycle 2 | Cycle 3 | Below floor now |
|---|---|---|---|---|
| `correctness` | 7.80 | 8.20 | **8.60** | — |
| `api-contract` | 7.86 | 8.14 | **8.43** | — |
| `security` | 7.40 | 7.40 | **8.00** | — |
| `testing` | 4.80 | 7.40 | **7.80** | — |
| `architecture-maintainability` | 6.71 | 6.43 | **7.57** | — |
| `documentation-clarity` | 6.00 | 7.00 | **7.17** | — |
| `agent-usability` | 6.60 | 6.40 | **7.00** | 2 |

## The two blockers

**1. `rollout gap-analysis` reports a non-compliant repository as compliant (`F72`, P1).**
This is the one finding in the run that produces a false success signal an agent would act on.
The package vendors no `labels.json`, so the only source is a live `gh api` read of
`infiquetra/infiquetra-sdlc` — which I confirmed is **private**. Any consumer without that
scope gets a 404, `load_config` swallows it, `required_labels` becomes empty, and the command
prints "All labels present" against a repository carrying none. I reproduced it hermetically.
The asymmetry proves the hazard was already understood: the *mutating* path refuses the same
empty catalog (`sdlc_manager.py:1739`), while the *verification* path accepts it
(`:2545`). `labels audit` shares the defect.

The code lives in carried upstream bytes, so the code fix is correctly deferred. **The
disclosure is this repository's to make, and its absence is what blocks.** Both remedies are
free — an eighth upstream filing in `QUEUED.md`, and a sentence in the *root* README, which
sits outside `plugins/mission-control/` and therefore moves no fingerprint and forces no
fourth re-assessment.

**2. The plan names a two-generation-stale SHA as issue #56's frozen commit (`F80`, P2).**
Two section-level statements say `863af58` is #56's frozen commit. Amendment 6 in the same
document says the third generation — 2026-08-31, tree `5fc16652…` — is #56's current frozen
record, and the current readback binds to `143a71b`. Three answers, one issue. Landing step 17
instructs the operator to record each child's frozen commit at close, so following the section
text writes a stale SHA onto a GitHub issue permanently. Amendment 6 also claims all three
freeze claims were qualified to point at it; I measured that only one was.

Neither blocker touches a graded file or the fingerprinted package. Both are string edits.

## What this review verified for itself

| Claim | Result at `16d8890` |
|---|---|
| Frozen revision, clean tree | `HEAD` is `16d88906…`; `git status --porcelain` empty |
| Fingerprint | **71 files / `5fc1665252a0dc293b0a1e4e8328fb6ab6631dd669133e0eb54dd5ffd1611b13`**, and both current evidence documents record exactly that |
| Five graded files untouched | 0 changed files each across `0eff36e..16d8890` |
| No carried byte hand-edited, **anywhere in the run** | all 46 byte copies and 5 client byte copies byte-identical to upstream at the pin; all twelve transform outputs re-derive byte-identically by running their own rules; and across the whole run only the synchronization commit `af322db` touched a carried path — the three later package-touching commits touched only `README.md`, `plugin.json` and `PROVENANCE.json` |
| Custody round-trip | `--check` exits 0 with the match line |
| `check_repo.py` | `Repository validation passed.` |
| Root suite | `Ran 840 tests … OK` |
| Package suite, 3.14 | `391 passed` |
| Package suite, 3.12 floor | `391 passed` (also re-run on 3.12.13, the interpreter you named) |
| Matrix checker | `Compatibility matrix validation passed.` |
| `git diff --check` | clean |
| Dependency-free hermetic baseline | `Ran 841 tests … OK (skipped=2)`, exit 0 |

## The three-generation evidence chain

**Well-formed.** Eight mission-control documents: two current (plain-named, `5fc16652`), two
`-pre-beads-config-ladder` (`659f91f6`), two `-pre-fingerprint-move` (`1f49322e`), two
`2026-08-25` (`651ac28a`).

- **Every `superseded-by` names a document that is itself current.** Both middle generations
  point forward to the current pair, not at each other — the cycle-2 defect class is not
  reproduced.
- **No human-readable banner in any of the eight links a superseded document.**
- **The preservation tests pin all three retired fingerprints**, so superseded evidence cannot
  be quietly edited to match a moved tree.
- **The plain-name convention is restored**: current is unsuffixed, retired carries a
  `-pre-<reason>` suffix, matching the ten older retired documents elsewhere in the directory.

**The filename/run-date question you raised: it does not silently disagree.** Both current
documents state, in prose, "The filename prefix names the evidence family (the 2026-08-30
mission-control family); the body names the run date", and their machine-readable records
carry `assessed_on` / `captured_on` of `2026-08-31`. The disclosure is explicit.

**The 2026-08-25 narration gap is acceptable, and I am recording it as a residual, not a
defect.** Those two reasons narrate the chain as far as `659f91f6` and close with "The
successor chain ends at the current 2026-08-30 re-assessment" without naming `5fc16652`. Their
pointers resolve correctly to the current documents, and the claim they actually make — that
the record no longer identifies the tree it describes — remains true. A reader is not
misdirected; the narration is just one generation short.

**What I did find in the chain is adjacent to it** (`F79`, residual): the
`-pre-fingerprint-move` pair still *describes* its successor as being at tree `659f91f6` and
as having run on 2026-08-30. When `16d8890` repointed those files forward it updated the
pointer and not the prose. Two lenses split on this — documentation called it a blocker on the
wrong tree, api-contract called it a residual on the wrong date. I adjudicated **residual**:
every machine-readable pointer, status and preserved fingerprint is correct and gated, and
every *current* document is accurate, so nothing a checker or a reader following the chain
resolves to is wrong. It is stale prose inside a retired artifact. It is nonetheless the
highest-value residual on the list, and it costs four string edits with no fingerprint move.

## On the deliberate non-repairs

Every one of them is correctly dispositioned. Two are worth calling out.

**F01's recorded prose now matches the measurements exactly.** The corrected filing carries
all three grades — `gh` absent = 58 failed / 333 passed; a non-network stub exiting 1 = 391
passed with the stub called exactly 180 times, 179 the same schema read; the 2.12.2 package
with `gh` absent = 1 failed / 265 passed — names the `SystemExit`-escapes-`except Exception`
mechanism, states that the 57-failure delta is a regression this resync introduced, and draws
the conclusion that the fallback works when a `gh` binary exists and fails while the gap is the
binary-absent path. I reproduced all three independently in cycle 2 and re-read the prose here.

**One cycle-2 finding of mine was too harsh and I am correcting it.** F54 called the Cursor
Agent restraint "prompt-only". The vendor's own help documents `--mode ask` as a read-only
execution mode, which is stronger than a sentence in a prompt. The finding stands — the
harness passes `-p` alongside, which the same help says has write and shell access, and
nothing *enforces* the read-only claim — but the exposure is smaller than I credited.

## Findings

Sorted blockers first, then residuals by severity. Identifiers continue the stable sequence
across all three cycles; the From column names the finding this one descends from, or NEW.

### Blockers — must be resolved before merge (2)

| # | File | Issue | Reviewer | Sev | Conf | Route | From |
|---|---|---|---|---|---|---|---|
| F72 | `plugins/mission-control/scripts/sdlc_manager.py:2545` | Degraded label catalog makes gap-analysis report false compliance | agent-usability,security | P1 | 100 | manual -> review-fixer | F72 |
| F80 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:1725` | Plan names a two-generation-stale SHA as issue #56's frozen commit | documentation | P2 | 100 | safe_auto -> review-fixer | NEW |

### Residuals, P1 (2)

| # | File | Issue | Reviewer | Sev | Conf | Route | From |
|---|---|---|---|---|---|---|---|
| F01 | `plugins/mission-control/scripts/sdlc_manager.py:343` | Ported package suite reaches GitHub and needs a gh binary | security,testing | P1 | 100 | manual -> human | F01 |
| F02 | `plugins/mission-control/skills/labels/SKILL.md:116` | Five agent surfaces instruct creation via a no-op verb | agent-usability | P1 | 100 | manual -> human | F02 |

### Residuals, P2 (13)

| # | File | Issue | Reviewer | Sev | Conf | Route | From |
|---|---|---|---|---|---|---|---|
| F70 | `docs/engineering-journal/QUEUED.md:15` | Filing preamble routes the downstream skill fix upstream | agent-usability | P2 | 100 | manual -> review-fixer | F70 |
| F97 | `docs/engineering-journal/QUEUED.md:227` | Live P1 filing denies a marketplace manifest the repository ships | api-contract | P2 | 100 | manual -> human | NEW |
| F79 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-fingerprint-move.md:3` | Retired pair's prose still describes the previous successor | documentation,api-contract | P2 | 100 | safe_auto -> review-fixer | F50 |
| F91 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:9` | Matrix headline fingerprint prose is still unbound | testing | P2 | 100 | manual -> review-fixer | F56 |
| F89 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:51` | Cursor stages reach a hosted inference API undisclosed | security | P2 | 100 | manual -> review-fixer | NEW |
| F82 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2486` | Plan counts four superseded documents; six exist | documentation | P2 | 100 | safe_auto -> review-fixer | F33 |
| F84 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2495` | Cycle-1 review artifact cites an unrelated merge commit | documentation | P2 | 100 | safe_auto -> review-fixer | F34 |
| F71 | `plugins/mission-control/README.md:75` | Repaired beads sentence still misstates two of three commands | agent-usability,documentation | P2 | 100 | manual -> review-fixer | F71 |
| F16 | `plugins/mission-control/skills/flow/SKILL.md:71` | Skill invocation paths do not resolve in a portable install | agent-usability | P2 | 100 | manual -> human | F16 |
| F54 | `scripts/assess_clients.py:307` | Real-home write safety is asserted, never enforced | security | P2 | 100 | manual -> human | F54 |
| F59 | `scripts/sync_vendor_source.py:867` | Package-keyed site table still needs globally unique paths | correctness,architecture,api-contract | P2 | 100 | manual -> review-fixer | F59 |
| F60 | `scripts/sync_vendor_source.py:1220` | Planner's precondition dispatch has no test | architecture,correctness,api-contract | P2 | 100 | manual -> review-fixer | F60 |
| F27 | `tests/test_mission_control_rule_audit.py:493` | Two parity tests still write into the fingerprinted package | testing | P2 | 100 | manual -> review-fixer | F27 |

### Residuals, P3 (21)

| # | File | Issue | Reviewer | Sev | Conf | Route | From |
|---|---|---|---|---|---|---|---|
| F30 | `.github/workflows/ci.yml:59` | CI installs test dependencies unpinned and unhashed | security | P3 | 100 | gated_auto -> release | F30 |
| F85 | `docs/README.md:54` | Documentation index names one superseded predecessor of three | documentation,api-contract | P3 | 100 | safe_auto -> review-fixer | F33 |
| F94 | `docs/engineering-journal/DECISIONS.md:3` | No journal entry for the precondition extension point | architecture | P3 | 100 | manual -> review-fixer | F61 |
| F87 | `docs/engineering-journal/QUEUED.md:47` | Queued filing names a CLI verb that does not exist | documentation | P3 | 100 | safe_auto -> review-fixer | F73 |
| F96 | `docs/evidence/2026-08-27-agent-launcher-post-activation-readback.md:1` | A readback declares a status value the checker forbids | api-contract | P3 | 100 | manual -> review-fixer | F38 |
| F86 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-beads-config-ladder.md:5` | Newest retired pair puts its banner below the title | documentation | P3 | 100 | safe_auto -> review-fixer | NEW |
| F88 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:16` | Current matrix never names the middle generation's tree | documentation | P3 | 100 | safe_auto -> review-fixer | F61 |
| F90 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:41` | Authentication qualifier restored in JSON, not in prose | security | P3 | 100 | manual -> review-fixer | F51 |
| F32 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378` | Issue #52's line-claim count is still uncorrected | documentation | P3 | 100 | safe_auto -> review-fixer | F32 |
| F83 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:893` | Commit-table cross-references use pre-renumbering rows | documentation | P3 | 100 | safe_auto -> review-fixer | F09 |
| F81 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2877` | Amendment 6's section-5 qualification was never written | documentation | P3 | 100 | manual -> review-fixer | F49 |
| F36 | `plugins/mission-control/PROVENANCE.json:21` | Every dropped-path entry repeats all three drop reasons | correctness | P3 | 100 | manual -> downstream-resolver | F36 |
| F98 | `ports/README.md:117` | Spec's second-package claim omits the path-uniqueness requirement | api-contract,correctness | P3 | 100 | manual -> review-fixer | F59 |
| F38 | `scripts/check_compatibility_matrix.py:940` | Public-evidence leak gate misses prose and three ccTLDs | security | P3 | 100 | manual -> human | F38 |
| F93 | `scripts/sync_vendor_source.py:46` | Exception paragraph splits the three-classification list | architecture | P3 | 100 | safe_auto -> review-fixer | NEW |
| F95 | `scripts/sync_vendor_source.py:760` | Emission refactor raised the script's parse floor to 3.12 | architecture | P3 | 100 | safe_auto -> review-fixer | NEW |
| F65 | `scripts/sync_vendor_source.py:928` | Multi-finder rows pair definitions and calls positionally | correctness | P3 | 100 | manual -> review-fixer | F65 |
| F92 | `tests/test_check_compatibility_matrix.py:1738` | Superseded-link walk errors on a tracked, deleted file | testing | P3 | 100 | safe_auto -> review-fixer | F55 |
| F57 | `tests/test_mission_control_rule_audit.py:138` | Rule-audit module's CI-inert set is recorded nowhere | testing | P3 | 100 | advisory -> human | F57 |
| F75 | `tests/test_sync_vendor_source.py:1059` | Rule-prose join binds site classes, not counts | architecture | P3 | 100 | manual -> review-fixer | F75 |
| F67 | `ports/mission-control.json:139` | Mutating-operation contract cannot express behaviour change | api-contract,security | P3 | 75 | manual -> human | F67 |
## Finding detail

Failure mode first, then evidence, then the minimal fix, then the disposition and why.

### F72 — Degraded label catalog makes gap-analysis report false compliance  ·  **BLOCKER**

`P1` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `manual` -> `review-fixer` · *pre-existing* · from `F72`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:2545`

`rollout gap-analysis` is the package's documented compliance gate, and it prints 'All labels present' against a repository carrying zero SDLC labels whenever the label catalog degrades to {}. That degradation is the default path for anyone outside the org: the package vendors no labels.json, so the only source is a live gh api read of infiquetra/infiquetra-sdlc, which is private. A consumer without that scope gets a 404, load_config swallows it, required_labels becomes empty, and the else-branch fires. Nothing in the command's output, the rollout skill, or either README signals it, so an agent gating rollout work on gap-analysis records a clean verdict and skips deploy-labels. The mutating path already refuses the same empty catalog; the verification path accepts it.

**Evidence**

- Controller-verified: `gh api repos/infiquetra/infiquetra-sdlc --jq .visibility` returns `private`
- Controller-verified: plugins/mission-control/config/ holds board-schema.json, generated, project-mappings.json, sdlc-schema.json — no labels.json
- Controller-reproduced hermetically with an empty labels config: rollout_gap_analysis prints '  - All labels present' for a repository returning zero labels
- The asymmetry, both measured in the shipped file: sdlc_manager.py:1739 appends 'label taxonomy has no labels' on the mutating path; sdlc_manager.py:2545 appends 'All labels present' on the verification path
- `labels audit` shares the defect through the identical expression at sdlc_manager.py:1648
- This is cycle 2's F72 suggested fix verbatim, unapplied

**Suggested fix.** Two moves, neither of which touches a graded file or moves the fingerprint: add an eighth upstream filing to QUEUED.md for the missing refusal (gap-analysis and labels audit must refuse an empty catalog, matching _validate_label_taxonomy's existing guard), and state the degradation in the ROOT README — which sits outside plugins/mission-control — naming labels.json as a remote-only input from a private repository and saying an empty catalog makes both commands treat 'no required labels' as 'all present'.

**Disposition.** BLOCKER — a shipped, documented verification command reports a non-compliant repository as compliant with no signal an agent could act on. The code fix is upstream-owned and correctly deferred; the DISCLOSURE is this repository's to make and its absence is what blocks. The remedy moves no graded or fingerprinted file.

### F80 — Plan names a two-generation-stale SHA as issue #56's frozen commit  ·  **BLOCKER**

`P2` · confidence 100 · `documentation-clarity` / `shipped-behavior-parity` · `safe_auto` -> `review-fixer` · new in cycle 3  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:1725`

Two section-level statements assert that `863af58` is issue #56's frozen commit. Amendment 6 in the same document says the third generation — 2026-08-31, tree 5fc16652 — is #56's current frozen record, and the current readback binds to 143a71b. The plan therefore gives three different answers to which commit satisfies a child issue, and landing step 17 instructs the operator to record each child's frozen commit at close. Following the section text writes a two-generation-stale SHA onto #56 permanently.

**Evidence**

- docs/plans/...:1725 — 'U5 was re-run and re-bound at `863af58`, issue #56's frozen commit'; the same claim at :2168
- Amendment 6 at :2876 — 'the third generation (2026-08-31, tree `5fc16652…`) is issue #56's current frozen record'
- docs/evidence/2026-08-30-mission-control-post-activation-readback.md:11 binds the current readback to 143a71b8aec09c7605f57b860bcfa9179ca103e8
- docs/plans/...:2172 is landing step 17, which tells the operator to record each child's frozen commit at issue close
- Controller-verified: Amendment 6 also claims all three freeze claims were qualified to point at it; only the §8.1 table (line 2168) actually mentions it — line 1725 and the §5 dependency-graph block do not

**Suggested fix.** At :1725 and :2168 replace '`863af58`, issue #56's frozen commit' with the two-exception chain: a1e84e0 moved the tree and U5 was re-bound at 863af58, then 143a71b moved it again to 5fc16652 and the third assessment was published at 16d8890, which is issue #56's frozen commit. Correct Amendment 6's claim that §5 was qualified, or qualify §5.

**Disposition.** BLOCKER — the plan contradicts itself on a commit SHA, and landing step 17 turns that contradiction into a permanent, outward-facing record on a GitHub issue. The fix is four string edits outside the fingerprinted package.

### F01 — Ported package suite reaches GitHub and needs a gh binary  ·  residual

`P1` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `manual` -> `human` · *pre-existing* · from `F01`  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:343`

_resolve_sdlc_schema puts the network first and swallows every exception before falling back. The binary-absent path escapes that: _gh's FileNotFoundError handler calls sys.exit(1), and SystemExit is not an Exception. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for the next repin. Re-confirmed present at this revision.

**Evidence**

- Controller-measured across three grades: gh absent -> 58 failed / 333 passed; a non-network gh stub exiting 1 -> 391 passed with the stub called exactly 180 times, 179 the same schema read; the prior 2.12.2 package with gh absent -> 1 failed / 265 passed
- The 57-failure delta is a regression this resync introduced, via the five carried test files it changed
- Controller-verified the corrected QUEUED.md filing now carries all three measurements, names the SystemExit mechanism, states the delta is a regression this resync introduced, and draws the required conclusion — the fallback works when a gh binary exists and fails, and the gap is the binary-absent path

**Suggested fix.** File the ladder inversion upstream — vendored first, network opt-in — and a refusal when the gh binary is absent rather than a bare sys.exit inside a swallowed try.

**Disposition.** RESIDUAL — upstream-owned, correctly deferred, and the filing prose now matches the three measurements exactly.

### F02 — Five agent surfaces instruct creation via a no-op verb  ·  residual

`P1` · confidence 100 · `agent-usability` / `capability-parity-reachability` · `manual` -> `human` · *pre-existing* · from `F02`  
**Where:** `plugins/mission-control/skills/labels/SKILL.md:116`

The package ships no verb that adds one option to a single-select field, and five agent-facing surfaces still instruct an agent to create one with `fields create-option`. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for the next repin. Re-confirmed present at this revision.

**Evidence**

- plugins/mission-control/skills/labels/SKILL.md:116-125, :157, :189; labels/references/labels-reference.md:213; milestones/references/objective-workflow.md:34; com.infiquetra.claude/agents/sdlc-operator.md:319 and :330
- The corrected QUEUED.md filing now carries the constraint the replacement wording must state: the option-set mutation overwrites the whole set, so a one-option write deletes every other option and clears each item value

**Suggested fix.** Route 'create an option' onto `fields set-options --options-file` with the complete-list constraint stated, or the Projects UI.

**Disposition.** RESIDUAL — upstream-owned, correctly deferred, and cycle 2's unsafe-remedy defect in the filing is repaired.

### F70 — Filing preamble routes the downstream skill fix upstream  ·  residual

`P2` · confidence 100 · `agent-usability` / `capability-parity-reachability` · `manual` -> `review-fixer` · from `F70`  
**Where:** `docs/engineering-journal/QUEUED.md:15`

Item 7's body is now correctly split by owner, but the section preamble still declares all seven entries 'defects to upstream bytes this repository may not patch' reaching the catalog 'only through a future repin'. Item 7's downstream half is neither. A next-repin operator reading the section header routes the downstream transform to 'wait for upstream'.

**Evidence**

- docs/engineering-journal/QUEUED.md:15-17 carries the blanket preamble; item 7 at :69-75 carries the correct split
- Controller-verified all seven skills/*/SKILL.md are entrypoint transforms, so the downstream route is in policy

**Suggested fix.** Amend the preamble to say six of seven are upstream-owned while item 7 is split, its downstream half gated only on accepting the fingerprint move.

**Disposition.** RESIDUAL — the filing body carries the correct route, so an agent reading item 7 in full is not misled.

### F97 — Live P1 filing denies a marketplace manifest the repository ships  ·  residual

`P2` · confidence 100 · `api-contract` / `versioning-deprecation` · `manual` -> `human` · new in cycle 3  
**Where:** `docs/engineering-journal/QUEUED.md:227`

A live P1 queued entry states the repository has no marketplace manifest anywhere at root level and therefore cannot be registered as a catalog, and carries a guardrail forbidding one to be written without a separate operator decision. The manifest exists at the repository root and has since the voice package landed; a test asserts it. A maintainer planning the next repin from this backlog would duplicate it or hold back work on a retired constraint.

**Evidence**

- .claude-plugin/marketplace.json exists at the frozen revision and lists the voice package
- tests/test_agent_launcher_packaging.py asserts the manifest path exists
- git diff over the whole run on QUEUED.md shows no marketplace change, so this run neither introduced nor touched the entry

**Suggested fix.** Rewrite the entry to state what remains open — catalog registration was never assessed for any client — and drop the 'no manifest exists' premise and its guardrail.

**Disposition.** RESIDUAL — pre-existing, untouched by this run, human-owned, and it makes no shipped code, manifest or evidence document wrong.

### F79 — Retired pair's prose still describes the previous successor  ·  residual

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `safe_auto` -> `review-fixer` · from `F50`  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-fingerprint-move.md:3`

When 16d8890 published a third generation it repointed the -pre-fingerprint-move pair's superseded-by forward to the new current documents but never renarrated their prose. Both files now describe their successor as 'the re-assessment against the corrected package at tree 659f91f6' and as having run 'on 2026-08-30'. The document they point at is bound to 5fc16652 and ran on 2026-08-31. A reader following the chain from the middle generation, or comparing that banner against --print-fingerprint, is told the current record is stale.

**Evidence**

- Controller-verified: the -pre-fingerprint-move matrix banner at :15 reads 'the re-assessment against the corrected package at tree `659f91f6…`', while the successor records 5fc1665252a0dc29…
- Both -pre-fingerprint-move superseded-reason comments say 'on 2026-08-30 and is current'; the successor's record carries assessed_on/captured_on of 2026-08-31
- The third generation's own banner gets it right — the -pre-beads-config-ladder reason says 'on 2026-08-31 and is current' — so each reason was written at its own retirement and the middle one was never revisited
- Controller-verified the machine-readable half is sound: every superseded-by names a CURRENT document, no banner links a superseded one, and the preservation tests pin all three retired fingerprints
- Controller-verified both files sit outside plugins/mission-control, so correcting them moves no fingerprint

**Suggested fix.** In both -pre-fingerprint-move reasons and the matrix banner, name the full chain: retired to the second generation at 659f91f6, itself retired by the beads-config correction; the current successor was re-assessed on 2026-08-31 against 5fc16652.

**Disposition.** RESIDUAL — the documentation lens argued BLOCKER on the wrong tree and the api-contract lens argued RESIDUAL on the wrong date; they are one defect. Adjudicated RESIDUAL: every machine-readable pointer, status and preserved fingerprint is correct and gated, and every CURRENT document is accurate, so nothing a checker or a reader following the chain resolves to is wrong. It is stale prose inside a retired artifact. It is nonetheless the highest-value residual: four string edits, no fingerprint move, and it should be taken before merge if the audit trail is to read cleanly.

### F91 — Matrix headline fingerprint prose is still unbound  ·  residual

`P2` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `manual` -> `review-fixer` · from `F56`  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:9`

The F56 repair binds the rendered Results table and the summary sentence to the JSON record — both legs verified red when broken — but its docstring claims hand-edited prose cannot diverge from the JSON, which is broader than what landed. The document's opening claim, the file count and tree digest, is the most load-bearing human-readable statement in the run's evidence, and nothing parses it.

**Evidence**

- In a scratch copy, changing only the prose file count and tree digest while leaving the JSON truthful left check_repo, the matrix checker and the evidence test module all reporting no attributable failure
- grep for '71 files' across tests/ returns no match; check_document_status reads directives and the record only

**Suggested fix.** Assert that the record's file_count and full tree_sha256 both appear in the document text, on the pattern the summary-sentence assertion already uses.

**Disposition.** RESIDUAL — the prose at the frozen revision is truthful and matches the record, so this is a missing gate against a future edit rather than a wrong statement shipping today.

### F89 — Cursor stages reach a hosted inference API undisclosed  ·  residual

`P2` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `manual` -> `review-fixer` · *pre-existing* · new in cycle 3  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:51`

Three Cursor Agent stages ran the client in ask mode with -p and are recorded as returning a model answer at exit 0, which means the probe prompt and the loaded plugin's component names were transmitted to the vendor's hosted inference endpoint. The matrix's Network section accounts only for GitHub and for the invocation stage. Every sentence is true as scoped, but a reader taking that section as the assessment's egress account concludes nothing left the machine, in a public repository whose evidence convention is that egress is stated.

**Evidence**

- The three stage commands are recorded verbatim in the matrix; the load stage's outcome reads 'Session-context response at exit 0', so a model reply was obtained
- The assessed binary's own --help documents the endpoint default and the harness sets no override
- Not packet-captured: the egress is inferred from the vendor's documented default endpoint plus the recorded exit-0 model response

**Suggested fix.** Add one clause to the Network bullet and to method.network naming the hosted-inference egress as distinct from the GitHub surface, without the literal hostname.

**Disposition.** RESIDUAL — the Network prose is true under a strict reading and no safety declaration is falsified; this is an incompleteness in a disclosure, and the file sits outside the fingerprinted package.

### F82 — Plan counts four superseded documents; six exist  ·  residual

`P2` · confidence 100 · `documentation-clarity` / `terminology-cross-document-consistency` · `safe_auto` -> `review-fixer` · from `F33`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2486`

Four places in the plan say 'four superseded mission-control documents' and enumerate only the 2026-08-25 pair and the -pre-fingerprint-move pair. Six are superseded; the -pre-beads-config-ladder pair this round created is omitted everywhere. Line 2486 is the acceptance checklist an operator ticks to close #56, and line 399 is requirement R33. The prior round repaired this same wording from 'both' to 'four'; this round's last commit made it wrong again.

**Evidence**

- Controller-verified: eight mission-control evidence documents, two current and six superseded
- grep for 'four superseded' returns lines 399, 2051, 2072 and 2486, each enumerating only two of the three retired pairs
- The machine gate does cover all six — the superseded-document test class asserts the beads pair too — so only the prose undercounts

**Suggested fix.** Replace 'four' with 'six' and the enumeration with the three retired pairs by name at all four sites.

**Disposition.** RESIDUAL — the committed test class already asserts the directives on all six documents, so the shipped chain is correct and only the plan's count is stale.

### F84 — Cycle-1 review artifact cites an unrelated merge commit  ·  residual

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `safe_auto` -> `review-fixer` · from `F34`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2495`

The F34 repair annotated each doc-review amendment block with the commits holding that cycle's version of the overwritten review file. Three are right; the first names b4cc17b, a merge commit on a different run branch that touches an unrelated plan file and is not an ancestor of the frozen revision. Following the citation recovers nothing, for the one cycle whose artifact was overwritten first.

**Evidence**

- docs/plans/...:2495 reads '(cycles 1–2; commits `b4cc17b`, `4d2cbe0`)'
- git show --stat b4cc17b is a merge commit titled 'Merge run branch: cycle-3 F5 repair (0b02078) for cycle-4 review' touching only docs/plans/2026-08-27-auralis-c3-adapter.md
- git merge-base --is-ancestor b4cc17b 16d8890 returns non-zero
- The commit that created the doc-review file is 82dcb1c

**Suggested fix.** Change the citation to '(cycles 1–2; commits `82dcb1c`, `4d2cbe0`)'.

**Disposition.** RESIDUAL — a wrong SHA in a plan appendix used for post-hoc audit recovery; nothing shipped or gated depends on it.

### F71 — Repaired beads sentence still misstates two of three commands  ·  residual

`P2` · confidence 100 · `agent-usability` / `context-constraints-acceptance-examples` · `manual` -> `review-fixer` · *pre-existing* · from `F71`  
**Where:** `plugins/mission-control/README.md:75`

The ladder half of the repair is correct and matches load_config. The sentence is still wrong twice. `board wip` never reports rolled-out repositories — it prints WIP counts — and its only path to the legacy config is guarded by a project name argparse will not accept, so the read is unreachable from every invocable form. And the promise that these commands report zero 'rather than erroring' holds only when a gh binary exists and fails; with gh off PATH they exit 1.

**Evidence**

- Controller-measured with gh removed from PATH: `rollout status` and `config show` each print 'ERROR: gh CLI not found' and exit 1
- _wip_limits reaches legacy_rollout_config only under project_name == 'mount-olympus', a value board wip --project cannot accept because argparse restricts it to PROJECT_CHOICES
- _wip_limits otherwise returns hardcoded {'Ready': 10, 'In Progress': 5} — neither zero nor a repository count
- Controller-verified all consumers use .get(key, {}), so the never-set path is functionally {} with no latent KeyError
- The command list is not inherited: the base README said only 'reads degrade gracefully to {}' with no command names

**Suggested fix.** Drop board wip from the sentence, qualify the no-error promise as holding only when a gh binary is present and its read fails, and add labels to the resolution-order list.

**Disposition.** RESIDUAL — what an agent actually meets is a loud non-zero exit with an accurate message, so no data loss or false success follows; correcting it costs a package-tree edit and therefore a fourth ten-client re-assessment.

### F16 — Skill invocation paths do not resolve in a portable install  ·  residual

`P2` · confidence 100 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · *pre-existing* · from `F16`  
**Where:** `plugins/mission-control/skills/flow/SKILL.md:71`

The flow skill has no Script Location section and its examples are bare invocations; the six siblings give a path inside the upstream repository. The corrected filing now splits this by owner — the flow half upstream, the six sibling paths as a downstream transform. Carried upstream bytes; the runbook forbids a downstream patch. Filed in docs/engineering-journal/QUEUED.md for the next repin. Re-confirmed present at this revision.

**Evidence**

- Controller-verified: all seven skills/*/SKILL.md are in custody.entrypoint_transforms under normalize-skill-frontmatter; zero are in custody.byte_copies, so the downstream route is in policy
- QUEUED.md item 7 now names both owners and the transform route

**Suggested fix.** Write the portable-path transform when the operator accepts the fingerprint move it causes; file the flow-skill half upstream.

**Disposition.** RESIDUAL — the filing now routes correctly; the downstream half is deferred only because writing the transform moves the fingerprint and retires the just-published evidence pair.

### F54 — Real-home write safety is asserted, never enforced  ·  residual

`P2` · confidence 100 · `security` / `authentication-authorization-tenant-isolation` · `manual` -> `human` · *pre-existing* · from `F54`  
**Where:** `scripts/assess_clients.py:307`

Cursor Agent's plan declares home=REAL_HOME and asserts no stage writes client state; nothing checks it. refuse_unsafe_home only refuses a real-home stage whose writes_client_state flag is set, and the three Cursor stages do not set it, so the flag is the assertion rather than a test of it. Cycle 2 called the restraint prompt-only; that was too harsh — the vendor documents `--mode ask` as a read-only execution mode, though the same help says `-p` has access to write and shell tools, and the harness passes both.

**Evidence**

- scripts/assess_clients.py:300-333 — three StageSpecs carrying --trust, none passing writes_client_state=True
- refuse_unsafe_home refuses only for ISOLATED_ONLY plans or a set writes_client_state flag
- command_safety_problems returns early unless the command names a package script, so no cursor-agent argv reaches the mutating-verb half
- cursor-agent --help documents --mode ask as read-only and -p as having access to write and shell tools; the tension was not resolved because resolving it means launching a live agent in the operator's home

**Suggested fix.** At the next unfreeze, fingerprint the client-state directories before and after each real-home stage and refuse on any delta; meanwhile record the hazard and the --mode ask / -p tension in QUEUED.md.

**Disposition.** RESIDUAL — the file is inside the graded frozen set, the vendor documents the mode as read-only so the exposure is smaller than cycle 2 credited, and no shipped statement is demonstrably false.

### F59 — Package-keyed site table still needs globally unique paths  ·  residual

`P2` · confidence 100 · `correctness` / `caller-enum-consumer-completeness` · `manual` -> `review-fixer` · *pre-existing* · from `F59`  
**Where:** `scripts/sync_vendor_source.py:867`

The site-count table gained a package level, but its only runtime consumer flattens it: the transform receives just a path, so it searches every slice and demands exactly one match. Slices are therefore not independent — a second package naming a path mission-control already names breaks mission-control's own synchronization, not just the newcomer's. Both prose sites a future porter reads say a second package simply extends the table with its own slice.

**Evidence**

- Constructed both slices in memory: a second slice naming the same path produces 'declares no unique site-count row for this path (found 2 rows across the per-package slices)', and the refusal is keyed on the path alone so it reaches mission-control's own three paths
- The inline comment already concedes the ambiguity; ports/README.md and the module docstring do not
- The descriptor-to-table join passes in both directions for a duplicated path, so the repository gate does not catch it either

**Suggested fix.** Thread the package name into the lookup, or amend both prose sites to state that paths must be unique across all slices.

**Disposition.** RESIDUAL — no current input reaches it, and the safe direction is taken: it refuses loudly rather than silently inheriting another package's counts.

### F60 — Planner's precondition dispatch has no test  ·  residual

`P2` · confidence 100 · `architecture-maintainability` / `simplicity-abstraction-duplication-changeability` · `manual` -> `review-fixer` · from `F60`  
**Where:** `scripts/sync_vendor_source.py:1220`

The F60 repair extracted the descriptor refusal into a precondition function and tested that function, but the planner's two-line dispatch of it is covered by nothing. plan_sync has no direct test anywhere, so the new extension point's only production consumer can be deleted and every gate stays green — the same failure mode F60 named, relocated from the refusal body to the call site.

**Evidence**

- Mutation-tested: deleting the two dispatch lines leaves the full suite's result identical to the unmutated baseline in the same scratch tree
- grep for plan_sync across tests/ returns no hits; the only precondition references call the function directly

**Suggested fix.** Add one test driving plan_sync against a descriptor whose client_extension_dir does not match, asserting SyncError.

**Disposition.** RESIDUAL — the guard is correct and fires today; only its regression protection is missing, which makes no shipped bytes or evidence wrong.

### F27 — Two parity tests still write into the fingerprinted package  ·  residual

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `review-fixer` · *pre-existing* · from `F27`  
**Where:** `tests/test_mission_control_rule_audit.py:493`

Two parity-drift tests append bytes directly to two generated files inside the 71-file provenance closed set, restoring only in a finally. During the window the live tree does not hash to 5fc16652, an interrupted run leaves a tracked file drifted, the suite cannot run against a read-only checkout, and two concurrent runs race. The sibling template-sync test was already redirected to a TemporaryDirectory, so the convention exists.

**Evidence**

- Measured: after a full suite run, find -newer returns exactly those two paths and nothing else; git status is empty afterwards, so the restore is byte-exact but the write is real
- git diff --stat 863af58..16d8890 on that file is +28/-0, all of it a new README test — no repair was attempted this round

**Suggested fix.** Copy the two generated artifacts and their .sha256 sidecars into a TemporaryDirectory and patch the parity module's GENERATED path, as the template-sync test already does.

**Disposition.** RESIDUAL — the writes restore byte-exact, the tree is clean after a full run, and every gate passes at the frozen revision; this is isolation hardening.

### F30 — CI installs test dependencies unpinned and unhashed  ·  residual

`P3` · confidence 100 · `security` / `dependency-supply-chain` · `gated_auto` -> `release` · *pre-existing* · from `F30`  
**Where:** `.github/workflows/ci.yml:59`

The job that grades the carried package installs four distributions with no version constraint and no hash, so the bytes CI grades against are whatever the index served that minute. The two actions are pinned by mutable tag rather than commit digest.

**Evidence**

- .github/workflows/ci.yml:59 — `python -m pip install --upgrade pip requests urllib3 pyyaml pytest`
- The matrix records the same four names as the assessed environment

**Suggested fix.** Pin with a hashed requirements file and pin the two actions by commit digest.

**Disposition.** RESIDUAL — pre-existing, release-owned, unchanged by this run, and it falsifies no shipped statement.

### F85 — Documentation index names one superseded predecessor of three  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `safe_auto` -> `review-fixer` · from `F33`  
**Where:** `docs/README.md:54`

The index repoints correctly to the two current documents but closes 'The 2026-08-25 predecessor is superseded and kept as history', singular, when three generations are retired. A reader browsing the evidence directory after reading the index finds four files it gave them no account of, and no signal that the retired-suffix convention exists.

**Evidence**

- docs/README.md:54 carries the singular sentence
- Controller-verified six mission-control documents carry a superseded stamp

**Suggested fix.** Name all three retired generations by suffix and the tree each was bound to, and state the plain-name-is-current convention.

**Disposition.** RESIDUAL — every index link points at the current pair, so nothing routes a reader onto retired evidence; the sentence is incomplete rather than false.

### F94 — No journal entry for the precondition extension point  ·  residual

`P3` · confidence 100 · `architecture-maintainability` / `significant-decision-documentation` · `manual` -> `review-fixer` · from `F61`  
**Where:** `docs/engineering-journal/DECISIONS.md:3`

This round's evidence-run decisions are well recorded, but the same commit made two code-shape decisions with no journal entry: adding a precondition slot to TransformRule, which is the convention every future rule will follow, and re-keying the site-count table by package. The repository's always-on capture rule requires the entry in the same commit that ships the change, and the rejected alternative that matters — widening the shared apply signature — is recorded nowhere.

**Evidence**

- The journal diff for this round is only DECISIONS and QUEUED; LEARNINGS is untouched
- grep for 'precondition' across the journal returns only unrelated prose, and the added DECISIONS lines are entirely the evidence-run entries

**Suggested fix.** Add a DECISIONS entry for the precondition convention with its rejected alternative and a revisit condition, and a LEARNINGS entry for the hash-seed mechanism.

**Disposition.** RESIDUAL — an absent journal entry for a correct change; it slows the next contributor but makes nothing shipped wrong.

### F87 — Queued filing names a CLI verb that does not exist  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `runnable-examples-actionability` · `safe_auto` -> `review-fixer` · from `F73`  
**Where:** `docs/engineering-journal/QUEUED.md:47`

The corrected --format filing's count of twelve is right, but it names the twelfth as a Python function name minus its prefix rather than the CLI verb the parser registers. A maintainer grepping the parser for it finds nothing, and the filing's own remedy is keyed on subcommand names.

**Evidence**

- The parser registers the verb under a different spelling than the filing uses; the only occurrence of the filing's spelling in the package is the function definition

**Suggested fix.** Use the CLI verb and name the renderer function parenthetically.

**Disposition.** RESIDUAL — an upstream-bound filing whose surrounding description makes the target recoverable; the counted total of twelve is verified correct.

### F96 — A readback declares a status value the checker forbids  ·  residual

`P3` · confidence 100 · `api-contract` / `serialization-errors` · `manual` -> `review-fixer` · *pre-existing* · from `F38`  
**Where:** `docs/evidence/2026-08-27-agent-launcher-post-activation-readback.md:1`

The checker defines exactly two document statuses and rejects anything else, and one readback ships a third value. No gate ever sees it, because readback records use different keys and fall outside matrix discovery entirely. The consequence is not cosmetic: the supersession machinery classifies by this directive, so a readback carrying the third value could be retired and still be linked from live prose without the superseded-link guard firing.

**Evidence**

- The checker's status tuple has two members; the agent-launcher readback carries a third
- The no-argument checker run validates the matrix documents and prints no readback; six readback documents exist
- The evidence test module states the discovery hole in its own docstring and closes it only by hand-registering mission-control's chain

**Suggested fix.** Normalize that readback's status, or give readbacks their own discovery predicate — the latter needs the graded freeze lifted.

**Disposition.** RESIDUAL — the fix touches a graded file, and mission-control's own four readback documents are individually bound by tests, so no shipped mission-control evidence is unchecked.

### F86 — Newest retired pair puts its banner below the title  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `safe_auto` -> `review-fixer` · new in cycle 3  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-beads-config-ladder.md:5`

In the four older retired documents the superseded block is the first rendered content. In the -pre-beads-config-ladder pair the H1 comes first and the banner second, and that H1 is byte-identical to the current matrix's. The status directive above it is an HTML comment, invisible when rendered, so a reader opening the retired document in a renderer sees the same title as the current record before any retirement warning.

**Evidence**

- In the -pre-beads-config-ladder pair the H1 is at line 5 and the banner at line 7; in the -pre-fingerprint-move matrix the banner is at line 5 and the H1 at line 17

**Suggested fix.** Move the superseded block above the H1 in both -pre-beads-config-ladder documents.

**Disposition.** RESIDUAL — a placement inconsistency; the retirement statement is present and the machine directive is correct.

### F88 — Current matrix never names the middle generation's tree  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `completeness-audience-prerequisites` · `safe_auto` -> `review-fixer` · from `F61`  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:16`

The current matrix is the landing document for the chain and narrates it as 'the first assessed tree 1f49322e, the second a different tree, and this one 5fc16652'. The middle fingerprint is never named there and is named nowhere in the journal either, so a reader working from the current evidence plus the journal cannot map the middle generation to its file by fingerprint.

**Evidence**

- The current matrix says 'the second a different tree' where it names both others
- grep for the middle digest across the journal returns only a mention of the third generation's move

**Suggested fix.** Name the middle tree in the current matrix and in the second-run decision entry.

**Disposition.** RESIDUAL — an incomplete narration, not a false one; the retired document and the preservation tests both carry the digest.

### F90 — Authentication qualifier restored in JSON, not in prose  ·  residual

`P3` · confidence 100 · `security` / `secrets-cryptography-session-handling` · `manual` -> `review-fixer` · from `F51`  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:41`

Cycle 2's contradiction is genuinely gone — nothing now claims no client was authenticated. But the reassurance that closes the loop for a security reader appears only in the machine-readable credentials string. The human-readable Isolation and Credentials bullets say a live authenticated home was used and stop there, so the half a person reads carries the exposure without the mitigation. The predecessor kept the qualifier in its prose.

**Evidence**

- The prose Credentials bullet ends at the env-strip claim with no qualifier; the JSON method.credentials carries the full one
- The env-strip claim is true even for real-home stages, since the prefix pop happens before the home branch
- What the narrative omits is that stripping the environment does not make those stages credential-free — HOME is not redirected, so the operator's on-disk credential store stayed readable

**Suggested fix.** Copy the qualifier into the prose bullet and add a clause noting the real-home stages inherit the on-disk credential store.

**Disposition.** RESIDUAL — the false claim cycle 2 found is repaired and nothing published is now untrue; this is a completeness gap between two copies of the same account.

### F32 — Issue #52's line-claim count is still uncorrected  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `completeness-audience-prerequisites` · `safe_auto` -> `review-fixer` · from `F32`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378`

R12 requires four surviving line-number claims; issue #52 says three and its grep omits the _open_mapping_pr claim. Deferred because no issue mutation was permitted mid-run.

**Evidence**

- docs/plans/...:378 versus issue #52's acceptance criterion
- All five descriptor line claims verify correct against upstream at the pin

**Suggested fix.** Correct the issue text when #52 is next touched; no repository file needs changing.

**Disposition.** RESIDUAL — correctly deferred by the no-issue-mutation rule; the shipped claims are all correct.

### F83 — Commit-table cross-references use pre-renumbering rows  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `safe_auto` -> `review-fixer` · from `F09`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:893`

The commit table was renumbered from twelve rows to fourteen by the F09 repair, but the two sentences beneath it still index the old numbering. One says commits 10, 11 and 12 touch nothing under the package, while row 11 of the table above says that commit is the last edit inside the package root — and it is. A reader cross-checking the freeze argument against the table hits a direct contradiction.

**Evidence**

- docs/plans/...:893 versus the table row at :885, which the commit's own --stat confirms changed two package files
- git log -S on the sentence returns only the commit written when the table had twelve rows

**Suggested fix.** Renumber the two sentences to the current fourteen-row indices.

**Disposition.** RESIDUAL — internal plan bookkeeping; no shipped artifact or gate depends on the row numbers.

### F81 — Amendment 6's section-5 qualification was never written  ·  residual

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `manual` -> `review-fixer` · from `F49`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2877`

Amendment 6 states that the three freeze claims in the plan are qualified to point at it. Only one is. The section actually titled for the freeze still carries its original unqualified claim in the dependency diagram, with no reference to the amendment anywhere in the block. A reader who opens the plan at the freeze section reads retired text as current — the failure the amendment was written to close — and the amendment's own repair claim is false.

**Evidence**

- Controller-measured: of the three sites, only the §8.1 table line mentions Amendment 6 or §19; the §5 dependency-graph block and the other freeze line do not
- The §5 diagram still reads 'fingerprint final; nothing may touch plugins/mission-control/ after this point'

**Suggested fix.** Add one line under the §5 diagram pointing at Amendment 6, and correct the amendment's claim about which sites it qualified.

**Disposition.** RESIDUAL — a missing forward pointer in one of three amended locations; the correct answer is reachable from the amendment and the one qualified site.

### F36 — Every dropped-path entry repeats all three drop reasons  ·  residual

`P3` · confidence 100 · `correctness` / `state-data-invariants-transactions-concurrency` · `manual` -> `downstream-resolver` · *pre-existing* · from `F36`  
**Where:** `plugins/mission-control/PROVENANCE.json:21`

The manifest builder stamps one concatenated string onto every removed_from_source entry, so no entry says why its own path was dropped. Deferred as needing a graded edit; cycle 2 established a non-graded emitter route exists and the decision record was asked to say so.

**Evidence**

- scripts/sync_vendor_source.py emits config.dropped_reason for every dropped path
- plugins/mission-control/PROVENANCE.json:21, :25, :29 — three paths, one byte-identical reason

**Suggested fix.** Split the descriptor's existing '<path>: <reason>.' clauses in the emitter, which needs no graded edit.

**Disposition.** RESIDUAL — deferred by ruling; the record is complete and the workaround is documented.

### F98 — Spec's second-package claim omits the path-uniqueness requirement  ·  residual

`P3` · confidence 100 · `api-contract` / `specification-documentation-parity` · `manual` -> `review-fixer` · from `F59`  
**Where:** `ports/README.md:117`

Both the descriptor spec and the module docstring tell the next porter that a second package extends the table with its own slice rather than editing mission-control's. Because the transform sees only the path, that is true only when the new slice's paths are globally unique. The joining gate compares each package against its own slice in both directions, which a duplicated path satisfies twice over, so the collision passes the repository gate and fails later at synchronization.

**Evidence**

- The lookup flattens all slices and requires exactly one match; the inline comment records the hazard but neither prose site does
- The planner's own refusal text states a stricter remedy than the spec's sentence conveys

**Suggested fix.** Add the uniqueness requirement to both prose sites and a cross-package duplicate assertion to the join.

**Disposition.** RESIDUAL — no second package selects the rule today, the shipped descriptor synchronizes clean, and a collision fails loudly with a message naming the cause rather than producing a wrong byte.

### F38 — Public-evidence leak gate misses prose and three ccTLDs  ·  residual

`P3` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `manual` -> `human` · *pre-existing* · from `F38`  
**Where:** `scripts/check_compatibility_matrix.py:940`

The gate walks only the strings inside the extracted JSON record, never the surrounding narrative, and its hostname check exempts any token ending in a filename suffix — three of which (.sh, .md, .py) are live country-code top-level domains, so a host under them passes as a filename.

**Evidence**

- scripts/check_compatibility_matrix.py:940 iterates _record_strings(record); nothing scans the document text
- Measured: _is_inert_domain('api2.cursor.sh', ...) returns True, and check_public_evidence_rules on a record naming that host returns []
- Both current evidence documents are clean in fact under an independent scan for /Users/, /home/, operator names, token prefixes, dotted quads and localhost

**Suggested fix.** Take the document text as well as the record, and narrow the filename exemption to tokens in a path context.

**Disposition.** RESIDUAL — the fix edits a graded file the freeze forbids, and both current documents are clean under an independent scan.

### F93 — Exception paragraph splits the three-classification list  ·  residual

`P3` · confidence 100 · `architecture-maintainability` / `readability-naming-error-contracts` · `safe_auto` -> `review-fixer` · new in cycle 3  
**Where:** `scripts/sync_vendor_source.py:46`

The module docstring's central contract is a three-item bullet list, and the paragraph documenting the marker rule's exception now sits between the second and third bullets. A reader cannot tell whether the third bullet belongs to the classification list or to the exception. At the base commit the three bullets were contiguous.

**Evidence**

- At the base commit the three bullets are contiguous with no intervening paragraph; at the frozen revision the exception paragraph sits between bullets two and three

**Suggested fix.** Move the exception paragraph below the third bullet so the list reads as one list.

**Disposition.** RESIDUAL — a docstring layout defect; it misleads a reader but changes no behaviour and fails no gate.

### F95 — Emission refactor raised the script's parse floor to 3.12  ·  residual

`P3` · confidence 100 · `architecture-maintainability` / `conventions-portability-configuration` · `safe_auto` -> `review-fixer` · new in cycle 3  
**Where:** `scripts/sync_vendor_source.py:760`

Deriving the raises emission from the marker constant put a backslash inside an f-string expression, which only parses from Python 3.12. The whole module now fails to parse on 3.11 where it parsed at the cycle-2 revision. This breaks nothing — the declared floor is 3.12 and CI pins it — but the narrowing was an unremarked side effect of a readability change, so someone running the tooling on an older interpreter gets a SyntaxError in a file with no version marker.

**Evidence**

- Controller-measured: python3.11 -m py_compile on the frozen revision reports 'SyntaxError: f-string expression part cannot include a backslash'; the same command on the cycle-2 revision exits 0; python3.12 on the frozen revision exits 0
- The declared floor is python>=3.12 and CI pins python-version 3.12

**Suggested fix.** Hoist the escape out of the f-string onto its own line, restoring 3.11 parsing at no cost to the single-source property.

**Disposition.** RESIDUAL — within the repository's own declared floor and no gate fails; a recorded portability narrowing, not a defect.

### F65 — Multi-finder rows pair definitions and calls positionally  ·  residual

`P3` · confidence 100 · `correctness` / `intent-behavior-completeness` · `manual` -> `review-fixer` · from `F65`  
**Where:** `scripts/sync_vendor_source.py:928`

The F65 repair made the zip safe against truncation by refusing any row whose call count differs from its finder count, so the lists are provably equal length. What it still does not check is that each definition is adjacent to its own call: it compares the i-th definition against the i-th call. A file laid out definition, definition, call, call passes, though the rule's own text says the shape puts exactly one call beside each definition.

**Evidence**

- Measured: a row declaring two finders and two calls against a body ordered definition, definition, call, call is ACCEPTED and rewritten; the genuinely inverted ordering is still REFUSED
- The loop body is a positional comparison with no adjacency condition

**Suggested fix.** Require that no other finder starts between a definition's end and its paired call's start.

**Disposition.** RESIDUAL — unreachable at this revision: every shipped row declares a finder count of 0 or 1, and a committed test pins call count equal to finder count.

### F92 — Superseded-link walk errors on a tracked, deleted file  ·  residual

`P3` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `safe_auto` -> `review-fixer` · from `F55`  
**Where:** `tests/test_check_compatibility_matrix.py:1738`

The F55 repair replaced the filesystem walk with a git index listing, which correctly removes the gitignored-directory dependence, but the index is not the working tree. A tracked markdown file a developer has deleted or renamed without staging is still listed, and the read then raises a bare FileNotFoundError inside an unrelated evidence test with no diagnostic.

**Evidence**

- Measured: moving a tracked markdown file aside makes the guard end in FAILED (errors=1) with FileNotFoundError naming that path
- The repair is sound on its own terms — a gitignored file with a bare superseded link and invalid UTF-8 leaves the test OK, where the cycle-2 walk raised UnicodeDecodeError

**Suggested fix.** Skip entries that are not present in the working tree before reading.

**Disposition.** RESIDUAL — it only fires on a working tree the developer has already made dirty and that git status would report; CI checkouts and the hermetic baseline are unaffected.

### F57 — Rule-audit module's CI-inert set is recorded nowhere  ·  residual

`P3` · confidence 100 · `testing` / `requirements-regression-coverage` · `advisory` -> `human` · *pre-existing* · from `F57`  
**Where:** `tests/test_mission_control_rule_audit.py:138`

25 of the module's 45 tests never execute in CI because two external checkouts are absent there, and no shipped document says so. The root README states the audit runs class-first against live authority with no qualification, which is true only on a machine carrying a home-lab checkout.

**Evidence**

- An AST count gives 45 test methods across 8 classes; CardValidatorAuditTests holds 23 and skips wholesale when the authority is absent, TemplateSyncAuditTests holds 2 more
- Both CI jobs check out this repository only, with no repository: key
- Grepping QUEUED, DECISIONS, LEARNINGS, README and AGENTS for the count or the class name finds nothing

**Suggested fix.** Add one QUEUED.md paragraph naming the two preconditions and the 25-of-45 count, and qualify the root README sentence.

**Disposition.** RESIDUAL — pre-existing, human-owned, purely a disclosure gap; nothing that runs is wrong and no gate would fail.

### F75 — Rule-prose join binds site classes, not counts  ·  residual

`P3` · confidence 100 · `architecture-maintainability` / `architectural-fit-ownership-single-sources` · `manual` -> `review-fixer` · from `F75`  
**Where:** `tests/test_sync_vendor_source.py:1059`

The F75 repair replaced a path-membership check with a per-clause presence check, binding whether a site class is named but never how many. The rule string makes counted claims and is written verbatim into the shipped provenance record. When a future pin gives a file a second finder and the row moves from 1 to 2, the transform still succeeds, the join still passes, and the provenance describes a transform the code no longer performs.

**Evidence**

- Measured: setting a row's finder and call counts to 3 leaves the join test passing while the prose still says 'one definition and one call'
- The four assertions compare a bool against 'count > 0'; none reads the integer

**Suggested fix.** Bind the number as well as the class — spell counts as words and assert the matching word, or assert an occurrence count.

**Disposition.** RESIDUAL — the shipped provenance is accurate at this revision because the table matches the files; the gap bites only at a future repin.

### F67 — Mutating-operation contract cannot express behaviour change  ·  residual

`P3` · confidence 75 · `api-contract` / `interface-contract-compatibility` · `manual` -> `human` · *pre-existing* · from `F67`  
**Where:** `ports/mission-control.json:139`

assessment.mutating_operations is a flat token set and the safety predicate intersects whitespace-split tokens with it, so two shapes widen the read-only set with no gate firing: a verb already classified read-only that gains a write upstream — which is exactly what QUEUED filing 3 asks upstream to do to `fields create-option` — and a write route that is not a CLI verb at all. The verb-surface gate closes only the third shape, a genuinely new verb.

**Evidence**

- scripts/check_compatibility_matrix.py:882-887 compares bare tokens with no argument or flag context
- tests/test_sync_vendor_source.py:2080 and tests/test_mission_control_readme.py:267 are both name-level, not behaviour-level
- Nine read-only tokens (view, list, show, status, audit, discover, prepare, progress, wip) are available for a future mutating verb to hide behind
- grep for the hazard across QUEUED.md returns nothing; it is recorded only in the cycle-2 review artifact

**Suggested fix.** Add a QUEUED.md entry recording that mutating_operations is name-only and that a reclassified verb and a new internal write route both fail open, so the next repin re-audits create-option deliberately.

**Disposition.** RESIDUAL — the concrete widening needs an upstream behaviour change that has not landed, create-option's read-only claim is proven by a dedicated no-write guard, and closing it properly edits a graded file.

## Consolidated fix requests

| Fix id | Route | Findings | Paths |
|---|---|---|---|
| `fix-af41621a092f` | manual -> human | F97 | `docs/engineering-journal/QUEUED.md` |
| `fix-4ff2042c911a` | manual -> review-fixer | F94 | `docs/engineering-journal/DECISIONS.md` |
| `fix-bd77f3efb731` | manual -> review-fixer | F70 | `docs/engineering-journal/QUEUED.md` |
| `fix-27e9a6e677c2` | manual -> review-fixer | F90, F91 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md` |
| `fix-14baa39d161a` | manual -> review-fixer | F81 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-7ed1db65ab41` | manual -> review-fixer | F98 | `ports/README.md` |
| `fix-fce3bad7707c` | manual -> review-fixer | F60, F65 | `scripts/sync_vendor_source.py` |
| `fix-1a26ae3dbb03` | manual -> review-fixer | F75 | `tests/test_sync_vendor_source.py` |
| `fix-38fd4189ce8d` | safe_auto -> review-fixer | F85 | `docs/README.md` |
| `fix-81654da3fdeb` | safe_auto -> review-fixer | F87 | `docs/engineering-journal/QUEUED.md` |
| `fix-527f4bfe78f0` | safe_auto -> review-fixer | F86 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-beads-config-ladder.md` |
| `fix-29b4d8213b60` | safe_auto -> review-fixer | F79 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix-pre-fingerprint-move.md` |
| `fix-0de45eddb355` | safe_auto -> review-fixer | F88 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md` |
| `fix-ec0535b522e8` | safe_auto -> review-fixer | F32, F80, F82, F83, F84 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-cbe66540e0f7` | safe_auto -> review-fixer | F93, F95 | `scripts/sync_vendor_source.py` |
| `fix-0e7e2ee33e4a` | safe_auto -> review-fixer | F92 | `tests/test_check_compatibility_matrix.py` |

## Independent gates

| Gate | Passed |
|---|---|
| `built-vs-planned` | yes |
| `ci-validate-job-dependency-free` | yes |
| `scanner-check-repo` | yes |
| `tests-root-unittest-840` | yes |
| `tests-package-pytest-3.14` | yes |
| `tests-package-pytest-3.12-floor` | yes |
| `custody-round-trip-check` | yes |
| `custody-no-hand-edited-carried-path` | yes |
| `compatibility-matrix-validation` | yes |
| `evidence-supersession-chain-well-formed` | yes |
| `whitespace-git-diff-check` | yes |
| `graded-file-mutation-proof-intact` | yes |
| `operational-safety-no-live-mutation` | yes |

## Lens scores

| Lens | Cycle 1 | Cycle 2 | Cycle 3 | Below the 7.0 floor |
|---|---|---|---|---|
| `architecture-maintainability` | 6.71 | 6.43 | 7.57 | — |
| `correctness` | 7.80 | 8.20 | 8.60 | — |
| `security` | 7.40 | 7.40 | 8.00 | — |
| `testing` | 4.80 | 7.40 | 7.80 | — |
| `api-contract` | 7.86 | 8.14 | 8.43 | — |
| `agent-usability` | 6.60 | 6.40 | 7.00 | `context-constraints-acceptance-examples`, `machine-readable-output-actionable-errors` |
| `documentation-clarity` | 6.00 | 7.00 | 7.17 | — |

### Per-dimension detail

**`architecture-maintainability`** — `architectural-fit-ownership-single-sources` 7, `separation-of-concerns` 8, `dependency-direction` 8, `simplicity-abstraction-duplication-changeability` 7, `readability-naming-error-contracts` 8, `conventions-portability-configuration` 8, `significant-decision-documentation` 7

**`correctness`** — `intent-behavior-completeness` 9, `state-data-invariants-transactions-concurrency` 8, `boundary-types-serialization-numeric-time` 9, `side-effects-errors-resource-lifecycle` 9, `caller-enum-consumer-completeness` 8

**`security`** — `authentication-authorization-tenant-isolation` 8, `input-trust-boundaries-injection` 9, `secrets-cryptography-session-handling` 8, `dependency-supply-chain` 8, `confidentiality-logs-errors-egress` 7

**`testing`** — `requirements-regression-coverage` 8, `negative-edge-state-concurrency-time` 8, `behavior-sensitive-assertions` 8, `realistic-seams-mocks-integration-evidence` 8, `determinism-isolation-diagnostics-maintainability` 7

**`api-contract`** — `interface-contract-compatibility` 8, `versioning-deprecation` 8, `serialization-errors` 8, `retry-idempotency-semantics` 9, `pagination-rate-limits` 9, `sdk-generated-client-impact` 9, `specification-documentation-parity` 8

**`agent-usability`** — `capability-parity-reachability` 7, `discoverability-invocation-schemas` 8, `context-constraints-acceptance-examples` 6, `machine-readable-output-actionable-errors` 6, `safe-bounded-idempotent-resumable-context-cost` 8

**`documentation-clarity`** — `shipped-behavior-parity` 7, `completeness-audience-prerequisites` 7, `structure-navigation` 7, `terminology-cross-document-consistency` 7, `runnable-examples-actionability` 8, `runbook-safety-rollback-links-generated-drift` 7

## Coverage

**The run stops here.** Three cycles are recorded in the typed result with real history and
real regression detection; there is no fourth. The residual list above is the durable record,
with evidence preserved for each item so the next repin can act on it without re-deriving.

**Residual risks.**

- Eleven residuals are carried upstream defects the runbook forbids patching here. They reach
  the catalog only through a future repin. All are filed in `docs/engineering-journal/QUEUED.md`,
  and this cycle confirmed the filings are now accurate — cycle 2 found three that were wrong,
  and all three are repaired.
- Three residuals are blocked on the graded mutation-proof freeze (`F36`, `F38`, `F54`, plus
  `F67`'s proper fix and `F96`'s). All are correctly deferred and correctly recorded.
- The branch has still never been pushed, so no continuous-integration run has exercised this
  work. The dependency-free job is green on a controlled bare interpreter, which is the closest
  proxy without pushing.
- Correcting `F71` or `F72`'s README half would edit a file inside `plugins/mission-control/`
  and therefore move the fingerprint a fourth time, retiring the just-published evidence pair.
  That is why `F72`'s remedy is routed to the *root* README instead — same disclosure, no
  fingerprint move.

**Testing gaps.**

- No CI job runs `sync_vendor_source.py --check`, so custody drift is caught only when a person
  runs it with an upstream clone on disk. Unchanged across all three cycles.
- 25 of the rule-audit module's 45 tests are inert in CI (`F57`).
- Two parity tests still write inside the fingerprinted package during a run (`F27`), restoring
  byte-exact.

**Method.** Seven caller-supplied lenses, exactly as specified: architecture-maintainability,
correctness, security, testing, api-contract, agent-usability, documentation-clarity. Maximum
concurrency observed: **3**. Each ran read-only in a disposable worktree. Cycles 1 and 2 were
replayed from their persisted `review_result.v1` files before cycle 3 was recorded, so the
typed result carries genuine three-cycle history. This review mutated no reviewed source and
created no commit, no pull request and no issue.

## Route

**`cycle_cap_best_available` → `continue_with_best_available`.**

The merge decision is the operator's. My recommendation, stated plainly:

1. **Take the two blockers first.** Both are string edits, neither touches a graded file or the
   fingerprinted package, and neither forces another assessment. `F72` needs a `QUEUED.md`
   filing plus one sentence in the root README; `F80` needs four corrections in the plan. That
   discharges everything I would stop a merge for.
2. **Then take `F79`** — the `-pre-fingerprint-move` pair's stale successor prose. Also free,
   also outside the package, and it is what makes the audit trail read cleanly end to end.
3. **Merge, and carry the remaining 33 residuals** to the next repin. They are recorded above
   with evidence; nothing in them makes shipped code, shipped evidence, or a shipped manifest
   wrong at this revision.

If the operator would rather merge as-is and take all 36 residuals forward, that is a
defensible call for everything except `F72`: a documented verification command that reports a
non-compliant repository as compliant, with no disclosure anywhere, is the one item I would not
carry silently.
