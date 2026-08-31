---
title: Saga Code Review — Agent Plugins #50 mission-control resynchronization (integrated run)
reviewed_revision: 853411da75cc6499e4d8395e85d36a2b9fe81fbc
base_revision: 0eff36ef432d90e3ba046ab0ca464168932034da
branch: orch-agent-plugins-50
issue_ref: infiquetra/infiquetra-agent-plugins#50
plan_path: docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md
doc_review_path: docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md
result_path: docs/code-reviews/2026-08-30-issue-50-mcresync-integration-code-review-853411da-result.json
outcome: repairs_requested
cycle: 1
mode: interactive
---

# Saga Code Review — Agent Plugins #50 mission-control resynchronization

This reviews the whole integrated run that moves this repository's **portable copy of the
mission-control plugin** from upstream commit `84eaf042` (plugin version 2.12.2) to upstream
commit `3b2b7083` (version 2.15.2). The copy lives at `plugins/mission-control/`; the
upstream original lives in a different repository, `infiquetra/infiquetra-claude-plugins`.
Every file in the copy is either an exact byte copy of its upstream file, a copy rewritten by
a named deterministic rule, or a file authored here — and `ports/mission-control.json` records
which class each file belongs to.

- **Reviewed revision:** `853411da75cc6499e4d8395e85d36a2b9fe81fbc` (`853411d`)
- **Base:** `0eff36ef432d90e3ba046ab0ca464168932034da` — the merge base, and `origin/main`
- **Scope:** `git diff 0eff36e..853411d` — 52 files, +12,841 / −588
- **Working tree:** clean at the frozen revision; no untracked files; nothing was mutated by
  this review

## Outcome

> **`repairs_requested`.** The synchronization itself is sound — custody, determinism and the
> package fingerprint all verify — but the safety net around it does not hold. Two things
> block: the repository's dependency-free continuous-integration job now fails, and the new
> transform rule, the one piece of machinery in this run that rewrites what tests assert,
> ships with no test of its own.

- Typed Saga review result contract (`review_result.v1`): **`repairs_requested`**
- Next action: `dispatch_repairs` (the only allowed resume transition from this outcome)
- Independent readiness (`ReviewReadiness.can_proceed`): **false** — two independent gates
  failed, and that blocks readiness on its own, separately from the numeric score
- Cycle 1 of a maximum of 3
- Findings: **P0=0, P1=4, P2=25, P3=18** (47 total; 29 introduced here, 18 pre-existing)
- Consolidated fix requests: 16, all unresolved
- Suppressed by the confidence rule (below anchor 75): 0

### The two blocking problems, in plain terms

**1. The repository's dependency-free CI job now fails (`F03`).** `.github/workflows/ci.yml`
runs a job whose comment calls it "the repository's hermetic baseline: it runs the standard
library only". A test added by this run shells out to `pytest --collect-only` with
`check=True` to count how many tests exist, so on an interpreter without pytest the job dies.
Measured, not inferred: in a bare Python 3.12 virtual environment carrying only pip and
PyYAML, the base commit reports `Ran 774 tests ... OK` and exits 0, while the reviewed
revision reports `Ran 802 tests ... FAILED (errors=1)` and exits 1 — the single error being
that new test. The branch has never been pushed (`git ls-remote --heads origin
orch-agent-plugins-50` is empty), so no CI run has ever seen this.

**2. The new transform rule has no test (`F04`).** `resolve-package-root-marker` is the rule
that rewrites what three carried tests assert. Its behaviour is correct today — this review
verified determinism, idempotence, and every refusal by executing them — but the only mention
of it anywhere under `tests/` is its name in a set-membership check. The plan's own
requirement **R42** states that `tests/test_sync_vendor_source.py` covers the rule. It does
not. Every sibling rule in the same module has a dedicated test class.

## What this review verified for itself

These are the load-bearing claims of the run. The controller re-ran each one rather than
accepting the coordinator's summary.

| Claim | Result |
|---|---|
| Frozen revision and clean tree | `HEAD` is `853411da…`; `git status --porcelain` empty; no untracked files |
| The five graded mutation-proof files are untouched | 0 changed files for each of `scripts/port_config.py`, `scripts/check_repo.py`, `scripts/check_compatibility_matrix.py`, `scripts/assess_clients.py`, `plugins/unifi/scripts/site_profile.py` |
| The package holds 71 files | `git ls-files plugins/mission-control \| wc -l` → `71` (64 at base + 7 added tests) |
| `tests/test_card_validator_agreement.py` is gone and recorded | absent from the package; present in `custody.dropped_from_source` with a stated reason |
| Every byte copy equals upstream at the pin | all 46 compared directly against the upstream clone at `3b2b7083` — 0 mismatches, 0 missing |
| The synchronization round-trips | `sync_vendor_source.py --check` prints the match line naming `3b2b7083…` and exits 0 |
| The three marker transforms are reproducible | each re-derived byte-identically from upstream bytes |
| The transform is idempotent | applying it to its own output returns the same bytes, for all three files |
| The transform refuses loudly | refusals reproduced for an undeclared path, a site-count mismatch, and a half-transformed file |
| The `create-option` no-write guard is real | falsified: a mutation through `_graphql` turns it red (positive control); a mutation through `_gh` does not (`F28`) |
| The fingerprint bindings are falsifiable | patching the recomputation red-lights both binding classes (2 and 8 failures); unpatched, both are green |
| The recorded fingerprint identifies the shipped package | live `--print-fingerprint` → 71 files, `1f49322e8412ac6b2ae0b1fbebf4a022ac2e53489be71aae674506a7613531f9`, matching both new evidence documents |
| `check_repo.py` | `Repository validation passed.` |
| Root test suite | `Ran 801 tests ... OK` |
| Package suite, Python 3.14 | `391 passed` |
| Package suite, Python 3.12 floor | `391 passed` |
| Compatibility-matrix validation | `Compatibility matrix validation passed.` |
| `git diff --check` | clean |
| Every unit-completion commit is green | re-run per commit: `dae34d9` OK(773), `8845cee` OK(795), `8c03898` OK(799), `853411d` OK(801); the three intermediates the plan predicted red are red, exactly as its table says |

## Independent gates

A failed independent gate blocks readiness even when the numeric score passes. Two failed.

| Gate | Passed | Note |
|---|---|---|
| `built-vs-planned` | **no** | R42 NOT-DONE, R30 PARTIAL, R35 CHANGED — see the completion audit |
| `ci-validate-job-dependency-free` | **no** | `F03`, measured base-green / head-red |
| `scanner-check-repo` | yes | |
| `tests-root-unittest-801` | yes | |
| `tests-package-pytest-3.14` | yes | |
| `tests-package-pytest-3.12-floor` | yes | |
| `custody-round-trip-check` | yes | |
| `compatibility-matrix-validation` | yes | |
| `whitespace-git-diff-check` | yes | |
| `graded-file-mutation-proof-intact` | yes | |
| `operational-safety-no-live-mutation` | yes | no live GitHub *write* was observed; 180 live *reads* were — `F01` |

## Scope check

**Scope Check: CLEAN.**

- **Intent:** resynchronize the portable mission-control package from upstream `84eaf042`
  (2.12.2) to `3b2b7083` (2.15.2), across six units U0–U5, without touching the five graded
  files and without moving the package fingerprint after the freeze.
- **Delivered:** exactly that. Seven new upstream tests carried, one excluded and recorded,
  three paths reclassified as transforms under a new rule, the package resynchronized to 71
  files at version 2.15.2, one verb reclassified read-only with a guard, and the ten-client
  evidence pair replaced and bound.

No file in the diff is unrelated to the stated intent. `scripts/sync_vendor_source.py` is the
one edit outside the package, and decision KTD14 requires it.

## The five risk areas the run was asked about

**1. The transform now rewrites what tests assert (KTD16).** *Single-purpose?* No longer — the
rule abandoned its one-universal-shape guarantee for a per-file site-count table, which the
decision record admits. *Refuses loudly on a count mismatch?* Yes, verified by execution, and
also on an undeclared path and a half-transformed file. *Idempotent?* Yes, verified. *Reproducible
from source bytes alone?* Yes, verified — all three files re-derive byte-identically.
*Does rewriting assertions weaken what the tests prove?* **No.** The rewrite re-targets each
assertion onto the marker the portable layout actually carries; leaving `.claude-plugin` would
make the tests assert on a directory that does not exist here. The real weaknesses are
elsewhere: the rule is untested (`F04`), it hard-codes one package's marker (`F19`), its
site-count table has no gate-time join (`F20`), an occurrence in an unmatched shape survives
silently (`F21`), and only the first finder site is ever rewritten (`F43`).

**2. `fields create-option` reclassified mutating → read-only.** The reclassification is
**correct**: the function discovers the field, prints its identifier and existing options, and
returns, with no write on any path including the error path. `fields set-options` remains
declared mutating and is protected. But **the guard is one-sided** (`F28`): it patches
`sdlc_manager._graphql` and asserts zero calls, while `sdlc_manager._gh` — a bare subprocess to
the real `gh` binary, the door `_open_mapping_pr` already writes through — is patched by nothing
in the repository. Falsified directly: an injected write through `_gh` left both guard tests
green. In a real regression `_gh` would not be mocked at all, so the test would issue a genuine
authenticated call against the live Asgard board during the suite.

**3. The superseded evidence and its fingerprint bindings.** **Genuinely falsifiable.** Both
new binding classes recompute the fingerprint from disk and compare; patching the recomputation
turns them red (2 and 8 failures) and they are green as shipped. Supersession hygiene is correct
on the retired pair. Two gaps remain: the matrix binding cannot catch a status that contradicts
its own stage results (`F23`, falsified — a client with two blocked stages can claim
`works-directly` and validate clean), and the readback binding skips the one client whose digest
is null (`F24`).

**4. Custody integrity.** **Fully verified.** All 46 byte copies are byte-identical to upstream
at the pin, checked directly rather than through the tool under review. The excluded test is
absent and recorded. The package holds exactly 71 files. No path appears in two custody classes.

**5. The graded mutation-proof set.** **Untouched** — zero changed files across all five. The
proof stands. Note that the plan's own verifier for this (R35) is over-broad and reports a false
breach (`F07`).

## Built versus planned

**COMPLETION: 41/46 DONE, 1 PARTIAL, 1 NOT-DONE, 1 CHANGED, 1 UNVERIFIABLE, 1 DONE-with-caveat.**

The five that are not clean DONE:

- **R42 — NOT-DONE.** The plan requires `tests/test_sync_vendor_source.py` to cover the new
  rule. It does not (`F04`).
- **R30 — PARTIAL.** A fresh ten-client assessment ran, but Qwen's four stages all exited 127
  because its wrapper was missing, so that client never actually ran. The evidence says so
  plainly; issue #56's "covering all ten clients" is not literally met.
- **R35 — CHANGED.** The substance holds — no graded file changed — but the stated verifier
  greps all of `scripts/` and prints `1` at this revision (`F07`).
- **R38 — UNVERIFIABLE.** Other worktrees, branches and sessions cannot be checked from this
  revision. The reviewed tree itself is clean.
- **R23 — DONE, one-sided.** The guard exists and is falsifiable through `_graphql`; it is
  blind to `_gh` (`F28`).

R37 ("no live GitHub mutation from any build, test, or assessment step") is met **as written** —
no write was observed. The requirement's wording is narrower than the risk: the package suite
makes 180 live authenticated *reads* (`F01`).

### Full requirement audit

| R | Unit | State | Evidence the controller ran |
|---|---|---|---|
| R1 | U0 | DONE | U0 note §1.1 carries the verbatim upstream transcript: `6927 passed, 7 skipped, 1 xfailed in 736.15s` |
| R2 | U0 | DONE | note:406-414; re-run here: `379d2350` → `0fdcea0d…`, `1111de33`/`3b2b7083` → `a851eabb…` |
| R3 | U0 | DONE | upstream `3b2b7083:…/.claude-plugin/plugin.json` reports `2.15.2` |
| R4 | U0 | DONE | upstream `3b2b7083:pyproject.toml` prints `requires-python = ">=3.12"` |
| R5 | U0 | DONE | note:454-455 records `{"mergeCommitAllowed":false,"rebaseMergeAllowed":true,"squashMergeAllowed":true}` |
| R6 | U0 | DONE | note §6 |
| R7 | U0 | DONE | note:6 names runbook v1.1.0; §7 lists the skipped entry-criteria steps with reasons |
| R8 | U1 | DONE | seven test paths added to `custody.byte_copies` (42 → 49, then 46 after U1b/U1c reclassified three) |
| R9 | U1 | DONE | `custody.dropped_from_source` 2 → 3, `provenance.dropped_reason` states the ruling |
| R10 | U1 | DONE | `--check` exits 0 with a match line, no unclassified-path refusal |
| R11 | U1 | DONE | notes name `3b2b7083…` / `2.15.2`; the module-scope PyYAML claim for `sdlc_manager.py` is corrected to the in-function import |
| R12 | U1 | DONE | all five line claims verified against upstream at the pin: `sdlc_manager.py:136`, `:3436`, `:5552`, `sync_template_docs.py:14`, `tests/test_template_sync.py:7` |
| R13 | U1 | DONE | `DECISIONS.md` U1 entry re-verifies the `test_prompt_alignment.py` drop at the new pin |
| R14 | U1 | DONE | same entry carries rejected alternatives and a revisit condition |
| R15 | U2 | DONE | round-trip prints the match line naming `3b2b7083…` and exits 0 |
| R16 | U2 | DONE | `PROVENANCE.json` → `3b2b7083fdda8e39e213b5f4acf9f8301d60dd52 2.15.2` |
| R17 | U2 | DONE | `git ls-files plugins/mission-control | wc -l` prints `71` |
| R18 | U2 | DONE | the agreement test is absent from the package |
| R19 | U2 | DONE | all 46 byte copies verified byte-identical to upstream directly, and the three marker transforms re-derived byte-identically from upstream bytes |
| R20 | U2 | DONE | fleet-core / bundle diff prints `0` |
| R21 | U3 | DONE | prints `True False` |
| R22 | U3 | DONE | README verb table lists `create-option` read-only, `set-options` mutating, and no `rollout update` |
| R23 | U3 | **DONE, but the guard is one-sided** | the guard exists and is genuinely falsifiable through `_graphql` (positive control went red); it is blind to `_gh` (falsified — see F09) |
| R24 | U3 | DONE | `plugin.json` `2.15.2` equals `PROVENANCE.json` `source_version`, bound by a test |
| R25 | U3 | DONE | root README states `3b2b7083` (v2.15.2), 71 files, 391 tests, twenty-eight test files — all recomputed live and matching |
| R26 | U4 | DONE | `MISSION_CONTROL_PIN` is the new pin; the seven shipped skills match the roster tuple |
| R27 | U4 | DONE | U4b touches no file under `plugins/mission-control/` |
| R28 | U4 | DONE | `.github/workflows/ci.yml:59` keeps `pyyaml`; two module-scope imports survive |
| R29 | U5 | DONE | recorded in the matrix prose: "fingerprinted before and after the run and identical both times" |
| R30 | U5 | **PARTIAL** | ten clients were attempted; Qwen's four stages all exited 127 because its wrapper was missing, so that client "never ran". The record says so plainly, but #56's "covering all ten clients" is not literally met |
| R31 | U5 | DONE | `Compatibility matrix validation passed.` |
| R32 | U5 | DONE | release block, all seven per-skill-unit fingerprints, and every client readback are present and bound |
| R33 | U5 | DONE | both retired documents carry status, successor and reason; each successor exists and is current |
| R34 | U5 | DONE | falsified by the controller: patching the recomputation red-lights both binding classes (2 and 8 failures); unpatched they are green |
| R35 | U5 | **CHANGED** | substance holds — all five graded files are untouched — but the stated verifier is over-broad and prints `1`, not `0` (F13) |
| R36 | all | DONE | check_repo passed; 801 unittest OK; 391 pytest on 3.14 and on the 3.12 floor; `git diff --check` clean — all re-run by the controller |
| R37 | all | DONE as written; the risk it names is wider | no live GitHub *mutation* was observed. 180 live authenticated *reads* were (F03), which the requirement's wording does not cover |
| R38 | all | UNVERIFIABLE | other worktrees, branches and sessions cannot be checked from this revision; the reviewed tree itself is clean |
| R39 | U3,U4 | DONE | `55a6511^` is `7c4925e` |
| R40 | U1,U2 | DONE | classified `deterministic-transform`; the portable copy imports cleanly |
| R41 | U2 | DONE | re-derivation from upstream bytes is byte-identical for all three files |
| R42 | U4 | **NOT-DONE** | the only reference to the rule anywhere in `tests/` is its name in a registry set. No test matches it against the upstream bytes, none exercises a refusal, none proves the no-op (F02) |
| R43 | U1,U3,U4,U5 | DONE | re-run per commit: `dae34d9` OK(773), `8845cee` OK(795), `8c03898` OK(799), `853411d` OK(801). The three intermediates the plan predicted red are red, exactly as tabled |
| R44 | U2,U4,U1 | DONE | `9781b0d` → `e5c9b5d` → `f343d58` in that order |
| R45 | U1,U2,U4 | DONE | both tests classified as transforms, both collect and pass on the floor interpreter, package holds 71 files |
| R46 | U2 | **DONE in behaviour, NOT in coverage** | the controller proved per-file counts, loud refusal, idempotence and reproducibility all hold today; no committed test holds them tomorrow (F02) |

## Findings

Ordered by severity, then confidence, then file, then line. Numbers are stable and are reused
wherever a finding reappears. Route is `<autofix_class> -> <owner>`.

### P1 — introduced by this change (2)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F03 | `tests/test_mission_control_rule_audit.py:847` | Hermetic CI baseline job now requires pytest | testing | 100 | gated_auto -> review-fixer |
| F04 | `tests/test_sync_vendor_source.py:930` | New transform rule ships with no test; R42 unmet | testing,architecture | 100 | manual -> review-fixer |

### P2 — introduced by this change (15)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F05 | `docs/README.md:49` | Retired matrix still indexed as live in the docs README | documentation | 100 | safe_auto -> review-fixer |
| F06 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:42` | New matrix drops the status rubric and the results table | documentation | 100 | manual -> review-fixer |
| F07 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:401` | Two acceptance verifiers are over-broad and fail at HEAD | documentation | 100 | safe_auto -> review-fixer |
| F08 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:1492` | Plan's U1 check expects 49 byte copies; the descriptor holds 46 | documentation | 100 | safe_auto -> review-fixer |
| F09 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2165` | Plan claims twelve commits; the branch carries fourteen | documentation | 100 | manual -> human |
| F10 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2718` | Two amendments still declare themselves unreviewed | documentation | 100 | safe_auto -> review-fixer |
| F11 | `plugins/mission-control/README.md:72` | README drops the rollout-status degradation disclosure | agent-usability | 100 | safe_auto -> review-fixer |
| F18 | `ports/mission-control.json:192` | Generated provenance claims 28 byte-copied tests; 26 ship | documentation,api-contract | 100 | gated_auto -> review-fixer |
| F19 | `scripts/sync_vendor_source.py:688` | Vendor-neutral sync tool hard-codes the Claude directory | architecture,correctness,api-contract | 100 | manual -> review-fixer |
| F20 | `scripts/sync_vendor_source.py:756` | Per-file site-count table is a second, unjoined custody table | architecture,correctness | 100 | manual -> review-fixer |
| F21 | `scripts/sync_vendor_source.py:902` | Transform silently emits half-transformed marker files | correctness | 100 | gated_auto -> review-fixer |
| F23 | `tests/test_check_compatibility_matrix.py:1333` | Matrix binding cannot catch a status contradicting its stages | testing | 100 | manual -> review-fixer |
| F24 | `tests/test_check_compatibility_matrix.py:1413` | Readback binding skips the one unverifiable client digest | testing | 100 | manual -> review-fixer |
| F28 | `tests/test_mission_control_rule_audit.py:716` | Create-option no-write guard watches only the GraphQL door | security,testing | 100 | safe_auto -> review-fixer |
| F29 | `tests/test_mission_control_rule_audit.py:830` | Test-file count guard is vacuous outside three values | testing,api-contract | 100 | safe_auto -> review-fixer |

### P3 — introduced by this change (12)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F31 | `docs/evidence/2026-08-30-mission-control-post-activation-readback.md:24` | Readback prose contradicts its own isolation record | documentation | 100 | safe_auto -> review-fixer |
| F32 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378` | Issue #52 undercounts the line claims it must verify | documentation | 100 | manual -> human |
| F33 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:399` | R33's verifier fails on one of the two documents it covers | documentation | 100 | safe_auto -> review-fixer |
| F34 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2469` | Four amendments cite one repeatedly overwritten review file | documentation | 100 | manual -> human |
| F35 | `plugins/mission-control/CHANGELOG.md:173` | Carried CHANGELOG names a marker the shipped script rejects | documentation | 100 | manual -> human |
| F39 | `scripts/sync_vendor_source.py:11` | Sync tool docstring claims no package specifics are compiled in | api-contract | 100 | safe_auto -> review-fixer |
| F40 | `scripts/sync_vendor_source.py:745` | Unknown marker at a raises site reports a misleading count | api-contract | 100 | safe_auto -> review-fixer |
| F41 | `scripts/sync_vendor_source.py:762` | Rule prose restates the count table with nothing joining them | architecture | 100 | manual -> review-fixer |
| F42 | `scripts/sync_vendor_source.py:827` | Incomplete site-count row raises a bare KeyError | architecture | 100 | safe_auto -> review-fixer |
| F43 | `scripts/sync_vendor_source.py:883` | Only the first finder site is classified and rewritten | correctness | 100 | gated_auto -> review-fixer |
| F46 | `tests/test_sync_vendor_source.py:1514` | PyYAML guard asserts a file-global substring, not the job | testing,architecture | 100 | safe_auto -> review-fixer |
| F47 | `docs/engineering-journal/DECISIONS.md:432` | KTD16 records two rejected alternatives, never the descriptor | architecture | 75 | advisory -> human |

## Pre-existing findings (informational — this change did not introduce them)

### P1 — pre-existing (2)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F01 | `plugins/mission-control/scripts/sdlc_manager.py:343` | Ported package suite makes 180 live GitHub API calls | security,testing | 100 | manual -> human |
| F02 | `plugins/mission-control/skills/labels/SKILL.md:116` | Five agent surfaces instruct creation via a no-op verb | agent-usability,correctness | 100 | manual -> human |

### P2 — pre-existing (10)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F12 | `plugins/mission-control/scripts/sdlc_manager.py:2026` | --format json silently ignored by ten subcommands | agent-usability | 100 | manual -> human |
| F13 | `plugins/mission-control/scripts/sdlc_manager.py:2058` | No-op create-option exits zero, signalling success | agent-usability | 100 | manual -> human |
| F14 | `plugins/mission-control/scripts/sdlc_manager.py:5578` | Mapping pull-request route leaves orphan remote branches | api-contract | 100 | advisory -> downstream-resolver |
| F15 | `plugins/mission-control/skills/board/SKILL.md:40` | Board skill ships knowingly wrong Operations and Asgard ladders | agent-usability | 100 | manual -> human |
| F16 | `plugins/mission-control/skills/flow/SKILL.md:71` | Flow skill examples are not runnable as written | agent-usability | 100 | manual -> human |
| F17 | `ports/mission-control.json:139` | No gate binds the declared verb split to the CLI parser | api-contract,security | 100 | manual -> review-fixer |
| F22 | `tests/test_check_compatibility_matrix.py:1078` | Evidence documents bound only by hand-registered classes | architecture | 100 | manual -> review-fixer |
| F25 | `tests/test_mission_control_rule_audit.py:75` | Root suite executes unpinned code from outside the repository | security,testing | 100 | manual -> human |
| F26 | `tests/test_mission_control_rule_audit.py:136` | Card-validator suite reports the machine, against the run's own rule | testing,security | 100 | manual -> human |
| F27 | `tests/test_mission_control_rule_audit.py:683` | A test writes inside the newly fingerprinted package tree | testing | 100 | manual -> review-fixer |

### P3 — pre-existing (6)

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---|---|
| F30 | `.github/workflows/ci.yml:59` | CI installs plugin test dependencies unpinned | security | 100 | gated_auto -> release |
| F36 | `plugins/mission-control/PROVENANCE.json:21` | Every dropped-path entry repeats all three drop reasons | correctness | 100 | manual -> downstream-resolver |
| F37 | `plugins/mission-control/README.md:12` | Package README's upstream version claim has no gate | api-contract | 100 | gated_auto -> review-fixer |
| F38 | `scripts/check_compatibility_matrix.py:940` | Evidence redaction check never reads document prose | security | 100 | gated_auto -> human |
| F44 | `tests/test_mission_control_readme.py:275` | No gate checks skill commands against the CLI surface | agent-usability | 100 | manual -> human |
| F45 | `tests/test_sync_vendor_source.py:1371` | No gate binds mission-control custody to its provenance record | correctness | 100 | manual -> review-fixer |
## Finding detail

Each entry states the failure mode first, then the evidence, then the proposed minimal fix.

### F01 — Ported package suite makes 180 live GitHub API calls

`P1` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:343`

`_resolve_sdlc_schema` puts the network first in its 'GitHub main -> vendored -> local' ladder and swallows every exception before falling back. The carried tests do not stub it, so on a machine with an authenticated `gh` the ported suite grades itself against whatever infiquetra-sdlc main holds at that moment; on a runner without credentials it grades against the vendored bytes. A green local run and a green CI run are therefore not the same claim, and the unit's four-gate transcript was captured on the authenticated side.

**Evidence**

- Measured by the review controller with a recording `gh` shim first on PATH that never reaches the network: `python3 -m pytest plugins/mission-control/tests -q` logged 180 invocations - 179 of `api repos/infiquetra/infiquetra-sdlc/contents/config/sdlc-schema.json?ref=main --jq .content` and 1 of `api repos/infiquetra/campps-mvp/issues/42`
- Attributed per file under the same shim, every one a file this diff changes: test_issue_create_prepared.py 100, test_issue_prepare.py 31, test_issue_prepare_compile_approve.py 27, test_sdlc_draft_revision.py 17, test_issue_create_interactive.py 5 (sum 180)
- plugins/mission-control/scripts/sdlc_manager.py:342 - docstring 'Resolve sdlc-schema.json via GitHub main -> vendored -> local fallback', with the vendored copy reached only after 'except Exception: pass'
- The repository's own root suite is clean by the same measurement: `python3 -m unittest discover -s tests` logged zero gh invocations over 801 tests
- The seven newly carried test files contribute none of the 180 - measured individually, all zero

**Suggested fix.** File the ladder inversion upstream so the vendored copy is preferred and the network read is opt-in; custody forbids editing the byte copies here. Until then, state plainly that the package-suite transcript proves the suite passes against live-schema-plus-fallback, not against the vendored bytes alone, and re-run it with `gh` off PATH to establish the hermetic half.

### F02 — Five agent surfaces instruct creation via a no-op verb

`P1` · confidence 100 · `agent-usability` / `capability-parity-reachability` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/skills/labels/SKILL.md:116`

The package ships no CLI verb that adds a single option to a project single-select field, and this run declared `fields create-option` read-only. Five agent-facing surfaces still instruct an agent to create an option with it. The command prints its options and exits 0, so an agent proceeds to the documented next step, `flow set-field --option <name>`, which then fails because the option was never created. The only working route, `fields set-options --options-file`, appears in no skill.

**Evidence**

- plugins/mission-control/skills/labels/SKILL.md:116-125, :157, :189 - 'Create a missing option with `fields create-option` when needed', inside a three-step workflow whose step 3 is `flow set-field`
- plugins/mission-control/skills/labels/references/labels-reference.md:213; plugins/mission-control/skills/milestones/references/objective-workflow.md:34; plugins/mission-control/com.infiquetra.claude/agents/sdlc-operator.md:319 and :330
- plugins/mission-control/scripts/sdlc_manager.py:2026-2067 - fields_create_option reaches only load_config, get_project_config, get_project_fields and print, and prints 'No mutation was performed.'
- Contradicted inside the same package by plugins/mission-control/skills/board/references/graphql-queries.md:310 and plugins/mission-control/README.md:62
- Verified byte-equal to upstream at the pin, so the text is upstream's and custody forbids a downstream patch; docs/engineering-journal/QUEUED.md records no filing for it

**Suggested fix.** File upstream against infiquetra/infiquetra-claude-plugins to route 'create an option' onto `fields set-options --options-file` (or the Projects UI) across all five surfaces, and record the filing in docs/engineering-journal/QUEUED.md, whose current entry states all eight prior filings are consumed and nothing remains open.

### F03 — Hermetic CI baseline job now requires pytest

`P1` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `gated_auto` -> `review-fixer`  
**Where:** `tests/test_mission_control_rule_audit.py:847`

The `validate` job installs nothing on purpose and runs `python3 -m unittest discover -s tests`. The new test shells out to `sys.executable -m pytest --collect-only` with `check=True`, so on any interpreter without pytest the subprocess exits 1, CalledProcessError propagates, and the repository's dependency-free baseline turns red on a README bookkeeping assertion. `capture_output=True` with `check=True` also swallows pytest's own message, so the failure text is only "returned non-zero exit status 1".

**Evidence**

- tests/test_mission_control_rule_audit.py:843-855 - subprocess.run([...,'-m','pytest',...,'--collect-only','-q'], capture_output=True, check=True)
- .github/workflows/ci.yml:24-33 - 'No dependency installation on purpose. This job is the repository's hermetic baseline: it runs the standard library only', then 'python3 -m unittest discover -s tests -v'
- Measured by the review controller in a bare python3.12 venv carrying only pip+PyYAML: at base 0eff36e the suite is 'Ran 774 tests ... OK (skipped=2)' exit 0; at 853411d it is 'Ran 802 tests ... FAILED (errors=1)' exit 1, the single error being ERROR: test_the_test_count_is_recomputed_by_collection
- tests/test_retry_backoff.py:41 - the repository's own established pattern for this hazard: 'except ModuleNotFoundError as exc:  # pragma: no cover - hermetic baseline has no pytest'

**Suggested fix.** Guard the subprocess the way tests/test_retry_backoff.py:39-46 already does - try `import pytest` and `self.skipTest(...)` on ModuleNotFoundError - and drop `check=True` in favour of asserting on returncode with stdout+stderr as the failure message.

### F04 — New transform rule ships with no test; R42 unmet

`P1` · confidence 100 · `testing` / `requirements-regression-coverage` · `manual` -> `review-fixer`  
**Where:** `tests/test_sync_vendor_source.py:930`

`resolve-package-root-marker` is the only rule in the repository that rewrites what carried tests assert, and no committed test exercises it. Its six refusal branches, the happy-path rewrite, and the idempotent return are all uncovered, so an edit that quietly changed which marker the three carried files assert on would ship green: `--check` re-derives from upstream with the same rule and compares against the tree that rule just produced, and CI never runs `--check` at all.

**Evidence**

- grep over tests/ for PACKAGE_ROOT_MARKER|package_root_marker|resolve-package-root returns exactly one line: tests/test_sync_vendor_source.py:930, the rule's name inside a set(svs.TRANSFORM_RULES) equality check
- docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:408 - requirement R42 states the file 'covers the new rule: it matches exactly once against the upstream bytes at the pin, refuses when the function is missing or duplicated, and is a no-op on already-portable input'
- Uncovered refusals, scripts/sync_vendor_source.py: unknown path :809; count mismatch :828; disagreeing markers :841; call-before-definition :848; unrecognized marker :863; mixed markers :874; idempotent return :872
- Every sibling rule has a dedicated class in the same file - SplitModuleRuleTests :599, GuardedModuleRuleTests :657, FrontmatterRuleTests :698 with an explicit idempotence case at :729
- .github/workflows/ci.yml runs check_repo.py, unittest discover, and pytest plugins/*/tests; it never clones the upstream repository, so sync_vendor_source.py --check runs in no automated gate

**Suggested fix.** Add a PackageRootMarkerRuleTests class beside FrontmatterRuleTests driving svs.package_root_marker_transform over small in-test fixtures: one happy-path rewrite per declared path, a second application proving the no-op, and one assertRaises(svs.SyncError) per branch at :809, :828, :841, :848, :863 and :874, each asserting that branch's distinguishing message substring.

### F05 — Retired matrix still indexed as live in the docs README

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `safe_auto` -> `review-fixer`  
**Where:** `docs/README.md:49`

The documentation index still points readers at the 2026-08-25 matrix in the present tense with no supersession marker. That document describes a 64-file package at a tree that no longer exists, and its body still reports the Cursor Agent failure this run fixed. The root README was repointed at the successor in five places, so the two indexes now disagree and the one a reader reaches from docs/ sends them to retired evidence. Nothing in the suite or check_repo.py catches an incoming link to a superseded document.

**Evidence**

- docs/README.md:49-52 links the 2026-08-25 matrix under '## Evidence' with no status note; git diff 0eff36e..853411d -- docs/README.md is empty
- docs/evidence/2026-08-25-mission-control-compatibility-matrix.md:1-3 carries matrix-status: superseded and superseded-by the 2026-08-30 successor
- README.md at HEAD was repointed to the 2026-08-30 matrix in the summary bullet, the reading-order list and the directory table

**Suggested fix.** Repoint docs/README.md:49 at the 2026-08-30 matrix, add the readback beside it as the agent-launcher entry does, and extend the supersession test class to assert no Markdown file outside docs/evidence/ links a document whose matrix-status is superseded.

### F06 — New matrix drops the status rubric and the results table

`P2` · confidence 100 · `documentation-clarity` / `completeness-audience-prerequisites` · `manual` -> `review-fixer`  
**Where:** `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md:42`

The replacement matrix carries two prose sections and then 683 lines of JSON. The document it supersedes and the sibling agent-launcher matrix both carry a status rubric defining works-directly, works-through-an-adapter, unsupported and failed, a Results table with a status column, and the summary count sentence. None of the three survives. So the ten status values exist only inside the JSON, and a reader of the prose cannot tell that Claude Code ('all five entrypoints exit 0') is recorded works-through-an-adapter while Cursor Agent reads identically and is recorded works-directly. The '2 directly, 7 adapter, 1 failed' summary the root README publishes appears nowhere in the evidence document meant to support it, and 'failed' - the word attached to Qwen - is left undefined in a document whose own reason field says that client never ran.

**Evidence**

- Headings in the new matrix are exactly lines 3, 18, 42, 62; the superseded matrix carries '## The status rubric' at :89 and '## Results' at :105, and the agent-launcher matrix carries the same
- The outcomes table header is '| Client | Version | Outcome |' with no status column; the ten status values appear only in the JSON
- Matrix JSON records Claude Code as works-through-an-adapter while its prose row reads 'all five entrypoints exit 0'
- README.md publishes 'Mission Control ten-client assessment: 2 directly, 7 via adapter, 1 failed'; no line of the matrix prose states those counts

**Suggested fix.** Restore the status rubric, a per-stage Results table with a Status column, and the one-sentence count summary from the superseded document, so the prose layer carries the same taxonomy the JSON and the root README rely on.

### F07 — Two acceptance verifiers are over-broad and fail at HEAD

`P2` · confidence 100 · `documentation-clarity` / `runnable-examples-actionability` · `safe_auto` -> `review-fixer`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:401`

Plan requirement R35 and the last acceptance criterion of GitHub issue #56 both certify 'no graded file changed' with a command that greps the whole of scripts/ and asserts the count is 0. The run legitimately edits scripts/sync_vendor_source.py, which is NOT one of the five graded files, so both commands print 1 at the reviewed revision. The substance holds - all five graded files are untouched - but anyone running the stated verifier reads a failure, and anyone who instead trusts the requirement as written has been handed a check that cannot pass.

**Evidence**

- docs/plans/...-resync-plan.md:401 - R35 'No graded file changed', verified by `git diff --name-only <base>..HEAD -- scripts/ plugins/unifi/scripts/site_profile.py | wc -l` prints `0`
- GitHub issue #56, final acceptance criterion - 'proven by `git diff --name-only <base>..HEAD -- scripts/ | wc -l` printing `0`'
- Run by the review controller at 853411d: the command prints 1, naming scripts/sync_vendor_source.py
- That file is not graded: the plan's own section 2.8 pins the five graded files as scripts/port_config.py, scripts/check_repo.py, scripts/check_compatibility_matrix.py, scripts/assess_clients.py and plugins/unifi/scripts/site_profile.py, and the controller confirmed 0 changed files for each
- KTD14 requires editing scripts/sync_vendor_source.py, so the requirement and the decision contradict each other as written

**Suggested fix.** Narrow both verifiers to the five graded paths by name, or to the mutation-proof footer's digest check, e.g. `git diff --name-only <base>..HEAD -- scripts/port_config.py scripts/check_repo.py scripts/check_compatibility_matrix.py scripts/assess_clients.py plugins/unifi/scripts/site_profile.py | wc -l`, which prints 0 at this revision.

### F08 — Plan's U1 check expects 49 byte copies; the descriptor holds 46

`P2` · confidence 100 · `documentation-clarity` / `runnable-examples-actionability` · `safe_auto` -> `review-fixer`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:1492`

U1's verification block carries a runnable command with an inline expected output of '49 3'; run as written against the shipped descriptor it prints '46 3'. R8's Verified-by column and U1's deliverable repeat the 49. Amendment 4 corrected the number 1,250 lines later, but did not propagate it back into the requirements table - the document's designed entry point for verification - so a reader runs a command whose stated answer is wrong.

**Evidence**

- docs/plans/...-resync-plan.md:1492 - '# expect: 49 3'; run at 853411d the same command prints '46 3'
- docs/plans/...-resync-plan.md:374 (R8) 'custody.byte_copies grows 42 -> 49' and :1390 'grows from 42 to 49 entries'
- docs/plans/...-resync-plan.md:2744 states the correct end state, 'byte copies 48 -> 46, entrypoint transforms 10 -> 12'
- Traced by the controller per commit: 12c889c 49, f343d58 48, dae34d9 46, 853411d 46 - the plan's 49 was true only at U1a
- docs/engineering-journal/DECISIONS.md:133 also records the superseded 42 -> 49 with no later correcting entry

**Suggested fix.** State the two-step outcome in R8, U1's deliverable and the inline comment - 42 -> 49 at U1a, then 49 -> 48 -> 46 as U1b and U1c reclassify three paths - and change the inline expectation to '46 3'.

### F09 — Plan claims twelve commits; the branch carries fourteen

`P2` · confidence 100 · `documentation-clarity` / `shipped-behavior-parity` · `manual` -> `human`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2165`

The plan states all twelve child-scoped commits live on the branch and KTD15 tables exactly twelve rows. The branch carries fourteen commits referencing child issues, because U0 landed in three rather than one. KTD15 names the middle of those three as U0's landed commit, and the plan makes the per-child frozen SHA an acceptance obligation - so issue #51's frozen SHA, taken from the plan, would be the wrong commit. Q8's heading still reads 'Eleven commits, not six' while its body says twelve, which the plan's own cycle-7 doc-review flagged as residual and did not repair.

**Evidence**

- git log --oneline 0eff36e..853411d shows fourteen unit commits: ab939ff, 0a19edb, f74bb7e (U0/#51); 12c889c, f343d58, dae34d9 (U1/#52); 9781b0d, af322db (U2/#53); e5c9b5d, 7c4925e, 853411d (U4/#55); 55a6511, 8c03898 (U3/#54); 8845cee (U5/#56)
- docs/plans/...-resync-plan.md:869 - '| 1 | `0a19edb`... | U0 | entry criteria and pin proof - landed | green |', while f74bb7e is U0's third and final commit
- docs/plans/...-resync-plan.md:851 - 'total twelve: U0 one, U1 three, U2 two, U3 two, U4 three, U5 one'
- docs/plans/...-resync-plan.md:2375 heading reads 'Q8 - Eleven commits, not six'

**Suggested fix.** Correct KTD15's table and the sections that cite it to fourteen, split row 1 into U0a/U0b/U0c with f74bb7e named as U0's frozen commit, and retitle Q8 to match its body.

### F10 — Two amendments still declare themselves unreviewed

`P2` · confidence 100 · `documentation-clarity` / `structure-navigation` · `safe_auto` -> `review-fixer`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2718`

Amendment 4 tells a reader in bold that it 'has not been reviewed. It requires its own review before it drives any work', and KTD16 repeats it. Both are false at this revision: doc-review cycle 6 examined Amendment 4 and returned blocked:false, and cycle 7 closed both of its findings. Amendment 1 carries the same stale instruction although cycle 3 judged it and all four of its findings were repaired. A reviewer who obeys these blocks re-reviews accepted material and, worse, concludes the run shipped work under an explicit 'do not act on this yet' caveat.

**Evidence**

- docs/plans/...-resync-plan.md:2718-2720 - 'Status: this amendment postdates doc-review cycle 5's PROCEED and has not been reviewed. It requires its own review before it drives any work.'
- Commit 384e52a recorded the cycle-6 doc-review of Amendment 4 with blocked: false
- docs/reviews/2026-08-30-issue-50-mission-control-resync-plan-doc-review.md at HEAD records cycles: 7, blocked: false, with D9 and D10 closed
- docs/plans/...-resync-plan.md:2540 and :916 carry the two other instances

**Suggested fix.** Replace each 'has not been reviewed' status block with the cycle that reviewed it and its verdict - Amendment 1 by cycle 3, Amendment 4 by cycle 6, both closed by cycle 7 - leaving the sections themselves unchanged.

### F11 — README drops the rollout-status degradation disclosure

`P2` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `safe_auto` -> `review-fixer`  
**Where:** `plugins/mission-control/README.md:72`

`rollout status` reads legacy_rollout_config, which maps to a beads-config.json the code comment records as removed upstream on 2026-04-26, and degrades to {} on missing-file. The command prints an all-zero dashboard, or literally `{}` under --format json, and exits 0, so a caller cannot distinguish 'nothing rolled out' from 'the tracking source no longer exists'. The base README disclosed exactly that; this diff rewrote the sentence to drop the parenthetical when it removed `rollout update`, so the warning is gone while the degradation remains. This README is target-owned, so it is a repository-authored regression, not carried bytes.

**Evidence**

- git show 0eff36e:plugins/mission-control/README.md:74 - '`beads-config.json` was retired; reads degrade gracefully to `{}`)'; grep for beads-config in the file at 853411d returns nothing
- plugins/mission-control/scripts/sdlc_manager.py:2472 - rollout_status reads config.get('legacy_rollout_config', {}); :228 and :247 record the retirement and the path
- Reproduced: INFIQUETRA_SDLC_PATH=<empty dir> ... --format json rollout status prints {} and exits 0
- ports/mission-control.json custody.superseded_by_target_owned lists README.md, so this file is authored here

**Suggested fix.** Restore the disclosure re-anchored on the surviving readers, e.g. '`rollout status`, `board wip`, and `config show` read the retired upstream beads-config.json; when it is absent they degrade to {} and report zero rolled-out repositories rather than erroring.'

### F12 — --format json silently ignored by ten subcommands

`P2` · confidence 100 · `agent-usability` / `machine-readable-output-actionable-errors` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:2026`

--format {text,json,markdown} is a global flag threaded into every handler, but ten handlers accept the fmt parameter and never reference it, printing prose unconditionally. An agent that passes --format json and calls json.loads raises JSONDecodeError with no indication that the flag was unsupported rather than the command having failed. `fields create-option` is the sharpest case at this revision, because this diff reclassified it as read-only inspection and inspection output is precisely what an agent requests as JSON.

**Evidence**

- An AST walk over plugins/mission-control/scripts/sdlc_manager.py finds fmt in the signature but no reference in the body of board_wip:1439, board_standup:1477, labels_deploy:1688, labels_auto_label:1775, fields_create_option:2026, metrics_wip_age:2293, metrics_column_time:2320, milestones_create:2366, milestones_link:2455, rollout_deploy_templates:2578
- plugins/mission-control/scripts/sdlc_manager.py:2055-2067 - ten bare print() calls with no _out(..., fmt) branch, unlike rollout_status at :2478 which does branch on fmt == 'json'
- The same AST walk at 0eff36e reports the identical set plus the since-removed rollout_update, so the gap predates this diff

**Suggested fix.** Upstream filing: either emit a JSON record from each of the ten handlers, or make the global --format parser reject json/markdown for subcommands that cannot honour it, so an agent gets a named refusal instead of unparseable prose.

### F13 — No-op create-option exits zero, signalling success

`P2` · confidence 100 · `agent-usability` / `safe-bounded-idempotent-resumable-context-cost` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:2058`

fields_create_option has no sys.exit on its success path and main's handler exits non-zero only for KeyboardInterrupt, LifecycleMutationHaltError and RuntimeError, so the command returns 0 after doing nothing. An agent gating on the exit code - the normal contract for 'did my mutation land' - records success for a mutation never attempted. The prose no-op explanation is the only signal, and it is unparseable.

**Evidence**

- plugins/mission-control/scripts/sdlc_manager.py:2026-2067 - sys.exit(1) appears only in the field-not-found arm at :2053; the documented no-op path at :2055-2067 falls off the end
- plugins/mission-control/scripts/sdlc_manager.py:7255 - dispatch is fields_create_option(...) with no return-value inspection, unlike board_move which returns bool
- Contrast fields set-options --dry-run at :2107, the package's other deliberate no-op, which is opt-in by an explicit flag the caller passed

**Suggested fix.** Upstream filing: have fields create-option exit non-zero, or emit a structured record such as {"mutated": false, "next_command": "fields set-options ..."} under --format json, so an exit-code check and a JSON parse both distinguish the refusal from a completed write.

### F14 — Mapping pull-request route leaves orphan remote branches

`P2` · confidence 100 · `api-contract` / `retry-idempotency-semantics` · `advisory` -> `downstream-resolver` · *pre-existing*  
**Where:** `plugins/mission-control/scripts/sdlc_manager.py:5578`

_open_mapping_pr is the one mutation route the descriptor declares that is not a CLI verb. It pushes a branch to origin and then calls gh pr create. If the create fails, the finally block removes only the local worktree - the pushed remote branch is never deleted. The branch name embeds a UTC timestamp to the second, so a retry never reuses it: each attempt leaves another abandoned remote branch, and the operator gets no signal that the mapping was pushed but never proposed.

**Evidence**

- plugins/mission-control/scripts/sdlc_manager.py:5578 - _run_git_command(['git','push','-u','origin',branch], cwd=temp_worktree) immediately precedes return _gh(['pr','create',...]) at :5579
- plugins/mission-control/scripts/sdlc_manager.py:5560-5563 - the branch name ends in datetime.now(UTC).strftime('%Y%m%d%H%M%S'), so no retry converges on the same ref
- plugins/mission-control/scripts/sdlc_manager.py:5591-5597 - the finally runs only git worktree remove --force, with no git push origin --delete
- This repository's own memory index records the same defect independently: '_open_mapping_pr pushes a branch then fails to open the PR'

**Suggested fix.** Upstream filing: wrap the gh pr create call so a failure runs git push origin --delete <branch> before re-raising, and name the pushed branch in the raised error so a partial run is recoverable.

### F15 — Board skill ships knowingly wrong Operations and Asgard ladders

`P2` · confidence 100 · `agent-usability` / `context-constraints-acceptance-examples` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/skills/board/SKILL.md:40`

The board skill's project table gives Operations and Asgard a status ladder the shipped schema does not carry, and the note added by this diff says outright that those rows 'still show the retired intent_flow ladder names; correcting them is tracked as a separate change and is not done here'. An agent that lifts the table - two of its three rows - and issues `board move --status "Ready"` sends a status the live field does not have. The correcting note sits eight lines below the table after two intervening paragraphs, so an agent that reads the table alone never sees it.

**Evidence**

- plugins/mission-control/skills/board/SKILL.md:40-41 - both rows read 'Idea -> Shaping -> Ready -> Active -> Verify -> Done'; :48 carries the caveat
- plugins/mission-control/config/sdlc-schema.json - operations, asgard and campps all carry "workflow": "stage_flow", whose stage_statuses are Capturing, Discovering, Designing, Implementing, Awaiting verification, Gathering evidence; Ready, Idea and Done are none of them
- plugins/mission-control/skills/board/references/kanban-workflow.md:31 repeats the retired ladder and :118 gives a review order in the same retired names
- plugins/mission-control/skills/issues/SKILL.md:222, added by this diff, names Idea, Shaping and Done as retired Status values that readiness refuses

**Suggested fix.** Upstream filing to replace both rows with the stage_flow stage list already given for CAMPPS; if the correction must wait, move the line-48 caveat directly above the table so it cannot be separated from the rows it invalidates.

### F16 — Flow skill examples are not runnable as written

`P2` · confidence 100 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · *pre-existing*  
**Where:** `plugins/mission-control/skills/flow/SKILL.md:71`

Six of the seven skills carry a Script Location section and an 'always use python3' instruction; the flow skill has neither, and every fenced example begins with a bare `sdlc_manager.py`. Nothing installs that on PATH, so an agent copying an example verbatim gets 'command not found' with no hint of the correct path. This diff extended the defect - the new lifecycle example it adds uses the same bare form. Separately, the six skills that do give a path give one inside the upstream repository, which an operator who installed only this portable package does not have.

**Evidence**

- plugins/mission-control/skills/flow/SKILL.md contains zero occurrences of 'python3' and zero of INFIQUETRA_SDLC_PATH, and has no location section
- plugins/mission-control/skills/flow/SKILL.md:71, :78, :83, :88, :94 - all bare 'sdlc_manager.py flow ...'; :78-80 are added by this diff
- plugins/mission-control/skills/board/SKILL.md:58 gives $INFIQUETRA_SDLC_PATH/../infiquetra-claude-plugins/plugins/mission-control/scripts/sdlc_manager.py, repeated in labels, issues, metrics, milestones and rollout
- plugins/mission-control/README.md:158 gives the path that actually resolves inside this package, python3 plugins/mission-control/scripts/sdlc_manager.py --help, which no skill mentions

**Suggested fix.** Upstream filing to give skills/flow/SKILL.md the same Script Location and python3 block the other six carry. For the upstream-repo path across all seven, add a portable-layout note to plugins/mission-control/README.md telling an agent to substitute the in-package script path, or record the divergence in the port descriptor as a known portability gap - it is recorded nowhere today.

### F17 — No gate binds the declared verb split to the CLI parser

`P2` · confidence 100 · `api-contract` / `interface-contract-compatibility` · `manual` -> `review-fixer` · *pre-existing*  
**Where:** `ports/mission-control.json:139`

`assessment.mutating_operations` is consumed at runtime by command_safety_problems, which assess_clients calls before starting a live client stage; a verb absent from the list is treated as read-only and permitted to run against real GitHub. Nothing in this repository enumerates sdlc_manager's argparse surface and checks the declaration for completeness. This resync moved that surface three ways - `rollout update` removed, `fields set-options` added, `fields create-option` reclassified - and every one was caught by hand. The upstream guard that would catch it lives outside the carried package path, so it is not carried here.

**Evidence**

- scripts/check_compatibility_matrix.py:882-887 - tokens are intersected with config.assessment.mutating_operations; a verb not in the set produces no problem and the stage runs
- tests/test_mission_control_readme.py:254-267 pins MUTATING_VERBS to the descriptor, but READ_ONLY_VERBS at :83 is a hand list bound to nothing and their union is never compared to the parser
- tests/test_sync_vendor_source.py:1656-1690 - CommandSurfaceTests builds a real parser and compares it to upstream, but its CLIENTS tuple names only the two UniFi clients; sdlc_manager.py has no equivalent
- git -C ../infiquetra-claude-plugins grep -l TestMissionControlRolloutSurfaceGuard 3b2b7083 returns tests/test_mission_control.py, outside plugins/mission-control/
- As shipped the declaration is complete: the parser's 47 distinct verbs are exactly covered by MUTATING_VERBS (24) plus READ_ONLY_VERBS (23)

**Suggested fix.** Add a test that builds sdlc_manager's parser using the command_surface interception already implemented at tests/test_sync_vendor_source.py:1586-1630 and asserts every group/action pair's action token lies in MUTATING_VERBS | READ_ONLY_VERBS, so an upstream verb arriving unclassified fails at resync time rather than defaulting to read-only.

### F18 — Generated provenance claims 28 byte-copied tests; 26 ship

`P2` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `gated_auto` -> `review-fixer`  
**Where:** `ports/mission-control.json:192`

The sync tool copies provenance notes verbatim into the generated PROVENANCE.json, and the note asserts 'The twenty-eight upstream test files are byte copies under plugins/mission-control/tests/'. Amendment 4 reclassified two of them as rule-rewritten transforms whose assertions differ from upstream, so 26 are byte copies and 2 are not - and one of the 26 is __init__.py. The provenance manifest is the artifact an auditor reads to learn which shipped bytes equal upstream and which do not; here its own prose contradicts its own files array, and no test binds the sentence. U1's pre-mortem in the plan named exactly this failure and it happened at U1c.

**Evidence**

- ports/mission-control.json:192 and plugins/mission-control/PROVENANCE.json:14 carry the sentence verbatim
- The descriptor's own arrays disagree: 26 tests/ paths in custody.byte_copies (including tests/__init__.py) and 2 in custody.entrypoint_transforms under resolve-package-root-marker
- PROVENANCE.json records both files with classification 'deterministic-transform', transform 'resolve-package-root-marker', transform_version '2'
- The 28 entered at the accepted cycle-1 fix, before Amendment 4 existed; no later amendment revisits it

**Suggested fix.** Rewrite the sentence to 'Twenty-eight upstream test files are carried: twenty-six as byte copies and two - tests/test_issue_contract_parity.py and tests/test_template_sync.py - as resolve-package-root-marker transforms', regenerate PROVENANCE.json, and add a test that recomputes both counts from the descriptor rather than trusting the prose.

### F19 — Vendor-neutral sync tool hard-codes the Claude directory

`P2` · confidence 100 · `architecture-maintainability` / `dependency-direction` · `manual` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:688`

`relocate-claude-manifest` reads the client extension directory from the port descriptor; `resolve-package-root-marker` bakes the literal `com.infiquetra.claude` into six places and reads nothing. Change `ports/<pkg>.json`'s `source.client_extension_dir` and the manifest lands at the new directory while the transformed entrypoint still walks for `com.infiquetra.claude/plugin.json`. Nothing joins the two, so synchronization reports a clean match and the breakage surfaces later as a RuntimeError from a carried test. `TransformRule.apply` is typed `(bytes, str) -> bytes`, so the rule cannot read the descriptor even if it wanted to.

**Evidence**

- scripts/sync_vendor_source.py:688 - PORTABLE_PACKAGE_ROOT_MARKER = "com.infiquetra.claude", with the same literal re-emitted rather than derived at :723, :726, :746, :890, :899
- scripts/sync_vendor_source.py:1121 - extension_dir = config.source.client_extension_dir, the descriptor-driven path the relocate rule uses for the very manifest this marker points at
- tests/test_port_config.py:384-385 sets client_extension_dir to 'com.example.client' and asserts it round-trips, so the schema is built for arbitrary values
- `git show 0eff36e:scripts/sync_vendor_source.py | grep -n com.infiquetra.claude` returns one hit, line 360, inside a docstring - before this diff the tool held the name in prose only
- grep for client_extension_dir across tests/ finds no test joining it to PORTABLE_PACKAGE_ROOT_MARKER

**Suggested fix.** In plan_sync, before dispatching a path to PACKAGE_ROOT_MARKER_RULE, raise SyncError when config.source.client_extension_dir != PORTABLE_PACKAGE_ROOT_MARKER, naming both values. That keeps the rule honest without changing the apply signature; deriving the marker from the descriptor is the fuller fix.

### F20 — Per-file site-count table is a second, unjoined custody table

`P2` · confidence 100 · `architecture-maintainability` / `architectural-fit-ownership-single-sources` · `manual` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:756`

`PACKAGE_ROOT_MARKER_SITE_COUNTS` records per-file custody knowledge inside a shared script, which AGENTS.md says belongs in the port descriptor. The repository already closes the equivalent loop for rule names, so a typo there fails at the gate; no equivalent join exists for this table. Add a fourth path to custody.entrypoint_transforms under this rule and forget the table row, and check_repo.py passes, the unittest suite passes, and the failure appears only when someone runs --check with an upstream clone - which CI never does. The keys are bare package-relative paths, so a second port carrying a same-named file would silently inherit mission-control's counts.

**Evidence**

- scripts/sync_vendor_source.py:756-761 - the table keyed on 'scripts/sync_template_docs.py', 'tests/test_issue_contract_parity.py', 'tests/test_template_sync.py'
- AGENTS.md:47 - 'package identity, the custody table, and assessment settings belong in that package's port descriptor under ports/, never as a constant inside a script'
- scripts/sync_vendor_source.py:1108-1110 passes the package-relative path as the target_path the table is keyed on, so no row is namespaced by package
- tests/test_port_config.py:561 is the existing precedent that joins every descriptor rule value to the registry across all packages
- grep for PACKAGE_ROOT_MARKER_SITE_COUNTS across tests/ and scripts/ returns only its own module

**Suggested fix.** Add a gate-time join in tests/test_port_config.py modelled on the existing rule-name join: for every package, assert that the set of descriptor paths whose rule is resolve-package-root-marker equals set(svs.PACKAGE_ROOT_MARKER_SITE_COUNTS), and that every row declares all four site classes.

### F21 — Transform silently emits half-transformed marker files

`P2` · confidence 100 · `correctness` / `intent-behavior-completeness` · `gated_auto` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:902`

The shipped rule text promises it re-anchors 'every package-root marker site a file carries' and refuses a file 'mixing the upstream and portable markers'. Neither holds. The four site detectors are exact-shape regexes, so any `.claude-plugin` occurrence in a shape none of them covers - a string literal, a docstring, the same assertion at a different indent - is invisible to the count check, invisible to the anchor classification, and left untouched by the rewrite. There is no post-rewrite residual scan, and a second application classifies the file as already-portable and returns it unchanged, so the mixed-marker refusal can never fire on it. `--check` stays green because the derived bytes and the shipped bytes agree on the residue.

**Evidence**

- Reproduced by the review controller against the real function: upstream tests/test_template_sync.py plus one eight-space copy of the marker assertion and one string literal naming the marker. package_root_marker_transform returned normally, the output still contained '.claude-plugin' twice, and re-applying the transform to that output returned it byte-identical.
- scripts/sync_vendor_source.py:735 - MARKER_ISFILE_ASSERTION is anchored on '^    assert' (exactly four spaces)
- scripts/sync_vendor_source.py:902-905 - the rewrite loop applies only the collected replacements and returns; grep for 'in rewritten' finds no residual scan
- The promise it breaks is shipped: plugins/mission-control/PROVENANCE.json:173 carries the rule text verbatim
- Latent, not live: grep for '.claude-plugin' across plugins/mission-control/ finds it only in CHANGELOG.md and PROVENANCE.json prose, never in a transformed Python file

**Suggested fix.** After building `rewritten`, raise SyncError when UPSTREAM_PACKAGE_ROOT_MARKER is still present, naming the file and the residual count. Equivalently, before rewriting, require body.count(UPSTREAM_PACKAGE_ROOT_MARKER) to equal what the detected sites account for (2 per finder, 1 per is_file, 1 per raises) so an unaccounted occurrence is a synchronization stop.

### F22 — Evidence documents bound only by hand-registered classes

`P2` · confidence 100 · `architecture-maintainability` / `architectural-fit-ownership-single-sources` · `manual` -> `review-fixer` · *pre-existing*  
**Where:** `tests/test_check_compatibility_matrix.py:1078`

The checker already has a general, discovery-based gate - matrix_documents() finds every matrix by record shape and check_matrix binds each one's fingerprint to the live tree - but nothing automated invokes it over the discovered set. Validation is hand-registered one document at a time, and this diff adds the third such family. The gap is already live for a sibling package, and readbacks are worse: the checker's discovery predicate rejects them outright because their record uses different keys.

**Evidence**

- grep for matrix_documents() in tests/test_check_compatibility_matrix.py returns only :1078 and :1083, both membership assertions
- check_matrix is called on committed documents at exactly four named paths: :1100, :1202, :1314, :1439
- scripts/check_compatibility_matrix.py:1015 - is_matrix_document requires record['package'] and record['clients'], so every readback classifies as not-a-matrix
- docs/evidence/2026-08-27-agent-launcher-compatibility-matrix.md and its superseded siblings are named by no test; the agent-launcher readback is referenced nowhere in tests/ or scripts/
- The new class states the gap in its own docstring at tests/test_check_compatibility_matrix.py:1356 - 'not discovered by the checker at all ... this class is the only thing that keeps it from drifting in silence'

**Suggested fix.** Replace per-document registration with one loop - `for path in ccm.matrix_documents(): self.assertEqual(ccm.check_matrix(path), [], path.name)` - which passes today (python3 scripts/check_compatibility_matrix.py exits 0 over every evidence document). For readbacks add a readback_documents() predicate keyed on release/readbacks plus a schema, and shrink the per-package classes to what is genuinely package-specific.

### F23 — Matrix binding cannot catch a status contradicting its stages

`P2` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `manual` -> `review-fixer`  
**Where:** `tests/test_check_compatibility_matrix.py:1333`

The binding asserts three cardinalities and two set-membership conditions and nothing else, and no rule in the checker relates a client's overall status to its own stage results. A client whose load and invocation stages are both recorded blocked can claim works-directly and the matrix validates clean. That is the failure the class docstring says it exists to prevent - a well-formed record that misstates what happened - and it is exactly the mistake a hand-transcribed ten-client assessment makes.

**Evidence**

- Falsification run: a scratch copy of the matrix with only the OpenAI Codex status changed from works-through-an-adapter to works-directly, stages left at load=blocked and invocation=blocked, returned [] from ccm.check_matrix, ccm.check_safety_rules and ccm.check_public_evidence_rules
- tests/test_check_compatibility_matrix.py:1333-1345 - the assertions are len(results)==40, set(results) <= STAGE_RESULTS, len(statuses)==10, set(statuses) <= STATUSES; no cross-check
- scripts/check_compatibility_matrix.py:660-701 - _check_clients verifies presence, stage keys, status membership and a non-empty reason, never status against stage results

**Suggested fix.** Add the one invariant the live record already satisfies and a mis-transcription would break: for each client, if any stage result is blocked, assert the status is not works-directly. The converse is not available - Qwen has four executed stages and status failed - so only the blocked-implies-not-direct direction is sound.

### F24 — Readback binding skips the one unverifiable client digest

`P2` · confidence 100 · `testing` / `realistic-seams-mocks-integration-evidence` · `manual` -> `review-fixer`  
**Where:** `tests/test_check_compatibility_matrix.py:1413`

The class docstring claims it asserts every readback entry, but the digest comparison is wrapped in `if readback.get('recomputed_tree_sha256') is not None:` and exactly one of the three recorded clients has that field null. For that client every digit of evidence - its seven per-skill-unit reported digests and its recomputed file count - is asserted by no test at all, so a fabricated or stale entry for a skill-directory client passes the whole suite. The entrypoint assertion was also loosened relative to the pre-existing class in the same file, so a missing key now passes where the older form raised.

**Evidence**

- docs/evidence/2026-08-30-mission-control-post-activation-readback.md - the Muse entry records install_unit 'skill-directory', recomputed_tree_sha256 null, recomputed_file_count 15 and a reported_digest object of seven per-skill digests; Agy and Grok both carry a non-null recomputed_tree_sha256
- tests/test_check_compatibility_matrix.py:1413 - the `is not None` guard around the only assertEqual against the release fingerprint
- tests/test_check_compatibility_matrix.py:1410 asserts `readback.get('entrypoints_exit_zero') is not False`, whereas the pre-existing ReadbackEvidenceTest at :1274 asserts assertTrue(readback['entrypoints_exit_zero']); a missing key passes the new form
- tests/test_check_compatibility_matrix.py:1405 - assertTrue(readbacks) pins no count, so a future readback recording one client instead of three passes unchanged
- The data itself is currently consistent: all seven Muse reported digests equal the corresponding release unit digests and the unit file counts sum to 15

**Suggested fix.** Branch on install_unit instead of on null: for package-root compare recomputed_tree_sha256 and recomputed_file_count to the release block as now; for skill-directory assert each reported_digest[unit] equals release['units'][unit]['tree_sha256'] for all seven units and that recomputed_file_count equals the sum of unit file counts. Tighten :1410 to assertTrue and pin len(readbacks).

### F25 — Root suite executes unpinned code from outside the repository

`P2` · confidence 100 · `security` / `dependency-supply-chain` · `manual` -> `human` · *pre-existing*  
**Where:** `tests/test_mission_control_rule_audit.py:75`

The repository's own mandated validation command executes about 27 KB of Python that this repository does not vendor, digest, or pin, at a path an environment variable can redirect. On a machine where the file is absent the class skips and the suite reports success with no coverage; where it is present the verdict depends on that file's current content.

**Evidence**

- tests/test_mission_control_rule_audit.py:51-64 builds candidates from os.environ['HOME_LAB_PATH'], ~/workspace/infiquetra/home-lab and ROOT.parent/home-lab; :75 - spec.loader.exec_module(mod)
- Confirmed live on this machine: the authority file exists and CardValidatorAuditTests runs 23 tests with zero skips, so the external module is executed rather than skipped
- ports/mission-control.json:196 states the contrary rule for the dropped upstream twin

**Suggested fix.** Vendor a digest-pinned copy of the authority corpus under tests/fixtures/ and compare against that, rather than importing an unpinned out-of-repository module.

### F26 — Card-validator suite reports the machine, against the run's own rule

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `human` · *pre-existing*  
**Where:** `tests/test_mission_control_rule_audit.py:136`

Thirty-seven verdict-agreement tests load their authority module from a home-lab checkout discovered on disk with exec_module, and skip silently when absent. CI checks out only this repository, so none of them ever runs there; they are green on the author's machine because a checkout happens to exist, at whatever revision and with whatever uncommitted edits it carries. This run cited the opposite rule as its stated reason for dropping the upstream twin, so the repository applies its own standard to the carried copy and not to its own.

**Evidence**

- tests/test_mission_control_rule_audit.py:51-64 - _find_home_lab_card_validator searches HOME_LAB_PATH, then ~/workspace/infiquetra/home-lab, then the sibling directory; :75 - spec.loader.exec_module(mod); :136-138 - skipTest when absent
- .github/workflows/ci.yml:21-22 and :42-43 - both jobs check out this repository only; no home-lab checkout is provisioned
- ports/mission-control.json:196 gives the exclusion rationale for the upstream twin: 'carrying it would make a test's verdict depend on what else happens to be on the machine's disk'
- docs/engineering-journal/LEARNINGS.md:689 - 'A test that asserts on the machine it runs on reports the machine, not the code'
- Live on this machine: the SessionStart repo-freshness report has the home-lab checkout 10 commits behind origin/main with 40 uncommitted files, and the class runs 23 tests with zero skips here
- No live regression is hidden behind it: the diff changes neither validate_card_body nor validate_card_body_for_context

**Suggested fix.** Either vendor a digest-pinned copy of the authority's decision corpus under tests/fixtures/ and assert against that, or apply the recorded rule to this class as it was applied to tests/test_card_validator_agreement.py and record the drop in the journal.

### F27 — A test writes inside the newly fingerprinted package tree

`P2` · confidence 100 · `testing` / `determinism-isolation-diagnostics-maintainability` · `manual` -> `review-fixer` · *pre-existing*  
**Where:** `tests/test_mission_control_rule_audit.py:683`

The template-sync drift test appends a marker to a tracked file inside plugins/mission-control/ and restores it in `finally`. Any interruption - a cancelled job, a Ctrl-C, a timeout kill - leaves the injected section on disk. This diff newly made that dangerous: the two new binding classes now recompute tree_sha256 over that same directory, so leftover text surfaces as a fingerprint mismatch against the compatibility matrix and the readback, pointing the investigator at U5's evidence and a suspected package drift rather than at the test that dirtied the tree.

**Evidence**

- tests/test_mission_control_rule_audit.py:683 - ref_path.write_text(original + '\n## Drift Injected Section\n'), where ref_path is sync_template_docs.REFERENCE_PATH
- REFERENCE_PATH resolves to plugins/mission-control/skills/issues/references/templates-reference.md, tracked and inside the fingerprinted package
- tests/test_check_compatibility_matrix.py:1319-1325 and :1391-1400 both call ccm.package_fingerprint(MISSION_CONTROL_PACKAGE_ROOT) and compare tree_sha256 against the recorded evidence
- The controller's own suite runs show the marker text '-## Drift Injected Section' reaching stdout, confirming the write happens on this machine

**Suggested fix.** Copy the reference file into a tempfile.TemporaryDirectory() and redirect the module constant with patch.object(sync_template_docs, 'REFERENCE_PATH', tmp_copy) for the test's duration, so the drift injection never touches the working tree.

### F28 — Create-option no-write guard watches only the GraphQL door

`P2` · confidence 100 · `security` / `authentication-authorization-tenant-isolation` · `safe_auto` -> `review-fixer`  
**Where:** `tests/test_mission_control_rule_audit.py:716`

`assessment.mutating_operations` is the only functioning half of the live-write gate for this package - no mission-control subcommand accepts --confirm, so the confirmation half never fires. This diff removes `create-option` from that list, and the whole evidence for the removal is a guard that patches `sdlc_manager._graphql` and asserts zero calls. `_gh` - a bare subprocess to the real `gh` binary, and the door `_open_mapping_pr` already writes through - is not patched by this test or by anything else in the repository. A future resync that writes through `_gh` passes the guard silently AND executes a real authenticated call during the suite. The declaration is correct at this pin; the mechanism that keeps it correct is not.

**Evidence**

- Falsified by the review controller: with fields_create_option replaced in memory by a version issuing a write through _gh, both guard tests still reported OK while the injected call was recorded - 'GUARD MISSED THE MUTATION'. The positive control through _graphql correctly went red (failures=1).
- tests/test_mission_control_rule_audit.py:716-724 - the with-block patches load_config, get_project_config, get_project_fields and _graphql; _gh is absent
- plugins/mission-control/scripts/sdlc_manager.py:694-708 - _gh builds ['gh'] + args and calls subprocess.run, with no seam to the real binary
- scripts/check_compatibility_matrix.py:872 gates on CONFIRM_FLAG = '--confirm', which no sdlc_manager subcommand accepts, leaving :883's mutating-verb token check as the sole gate
- `find . -name conftest.py` returns nothing, so no fixture intercepts _gh; the fixture names project number 2, and the command prints the live Asgard board URL

**Suggested fix.** Add `patch.object(sdlc_manager, "_gh") as mock_gh` to both with-blocks and assert `mock_gh.call_count == 0` beside the existing `mock_graphql.call_count == 0`, so the no-write claim covers the subprocess door too.

### F29 — Test-file count guard is vacuous outside three values

`P2` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `safe_auto` -> `review-fixer`  
**Where:** `tests/test_mission_control_rule_audit.py:830`

The guard maps the counted number of package test files onto an English word and asserts that word appears in the root README, but its table covers only 27, 28 and 29. Any other count falls back to a bare substring search for the digits, which the README satisfies from unrelated text - it carries four '2026-08-30' strings, so a count of 30 passes while the README still says 'Twenty-eight'. The guard therefore stops guarding for exactly the move it exists to catch: this diff moved the count from 21 to 28, a jump of seven, and a jump that size lands outside the window every time.

**Evidence**

- tests/test_mission_control_rule_audit.py:830-837 - number_word = {27: 'Twenty-seven', 28: 'Twenty-eight', 29: 'Twenty-nine'} then word = number_word.get(len(test_files), str(len(test_files))), asserted with a bare assertIn(word, readme)
- Simulated against the committed README: counts 21, 26 and 30 all PASS; only 27, 29, 35 and 36 fail. The README's only test-file claim is README.md:75, 'Twenty-eight test files (391 tests)'
- grep -n '30' README.md returns four hits, all 2026-08-30 evidence filenames at :82, :97, :145, :200
- git ls-tree over plugins/mission-control/tests gives 21 files at 0eff36e and 28 at 853411d

**Suggested fix.** Parse the claim out of the README instead of searching for a rendering of the count: capture with re.search(r"(\S+) test files \((\d+) tests\)", readme) and compare the captured word, or fail explicitly when the count is outside the table with assertIn(len(test_files), number_word, 'extend number_word deliberately').

### F30 — CI installs plugin test dependencies unpinned

`P3` · confidence 100 · `security` / `dependency-supply-chain` · `gated_auto` -> `release` · *pre-existing*  
**Where:** `.github/workflows/ci.yml:59`

The plugin-tests job resolves requests, urllib3, pyyaml and pytest at whatever version the index serves at run time, with no constraint and no hash pinning, then executes the ported plugin suite against the checked-out tree. A compromised or yanked release of any of the four runs arbitrary code in the job. The repository is deliberate about hermeticity for its first job and has no equivalent control here.

**Evidence**

- .github/workflows/ci.yml:59 - run: python -m pip install --upgrade pip requests urllib3 pyyaml pytest, followed at :62 by python -m pytest plugins/*/tests -q
- .github/workflows/ci.yml:24-27 - the first job's comment calls itself 'the repository's hermetic baseline'
- ports/mission-control.json:194 - 'PyYAML therefore remains a required dependency and the continuous-integration install line stays', so this diff re-affirms the posture

**Suggested fix.** Add a requirements-plugin-tests.txt with pinned versions and hashes and install with pip install --require-hashes -r, matching the hermeticity standard the first job already documents.

### F31 — Readback prose contradicts its own isolation record

`P3` · confidence 100 · `documentation-clarity` / `terminology-cross-document-consistency` · `safe_auto` -> `review-fixer`  
**Where:** `docs/evidence/2026-08-30-mission-control-post-activation-readback.md:24`

The 'held identical throughout' paragraph states each client ran in an isolated scratch home with empty configuration, while the machine-readable isolation field eleven lines below adds that Cursor ran against the real authenticated home. Both cannot be true of the same set, and the readbacks array holds only three clients, none of them Cursor - so no entry supports the exception the JSON names. A reader auditing whether any readback was taken against a real authenticated home gets one answer from the prose and a different one from the record.

**Evidence**

- docs/evidence/2026-08-30-mission-control-post-activation-readback.md:24-25 - 'isolated (each client ran in an isolated scratch home with empty configuration)'
- The same file's method.isolation adds 'Cursor ran against the real authenticated home with read-only rules.'
- The same file's readbacks array holds exactly three entries: Agy, Grok, Muse
- The superseded 2026-08-25 readback had no such split

**Suggested fix.** Drop the Cursor sentence from method.isolation - it describes the compatibility matrix's assessment, not this readback - or add the Cursor readback entry the sentence implies and qualify the prose to match.

### F32 — Issue #52 undercounts the line claims it must verify

`P3` · confidence 100 · `documentation-clarity` / `terminology-cross-document-consistency` · `manual` -> `human`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:378`

R12 requires four surviving line-number claims to be correct at the new pin; issue #52's corresponding acceptance criterion says three, and its verification grep omits the _open_mapping_pr claim entirely. Four is correct and the plan records the widening, but the issue was never updated. A unit satisfying #52 exactly as written would never check the claim that pins the internal mutation route assessment.mutating_operations depends on. The claims themselves all hold - this is a gap in the contract, not in the shipped bytes.

**Evidence**

- docs/plans/...-resync-plan.md:378 - 'The four surviving line-number claims are correct at the new pin'; :2529 records 'R12 widened from three surviving line-number claims to four'
- GitHub issue #52's criterion reads 'The three surviving line-number claims...' and its verification block greps only for the shim import, INFIQUETRA_SDLC_PATH and import yaml
- Verified by the controller against upstream at the pin: def _open_mapping_pr is at sdlc_manager.py:5552, and all five descriptor line claims check out

**Suggested fix.** When issue #52 is next touched, correct its criterion to four and extend its grep to `def _open_mapping_pr`; no repository file needs changing.

### F33 — R33's verifier fails on one of the two documents it covers

`P3` · confidence 100 · `documentation-clarity` / `runnable-examples-actionability` · `safe_auto` -> `review-fixer`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:399`

R33 requires both superseded documents to carry the three supersession directives, and names a single checker invocation against the matrix as the verifier. The checker cannot validate a readback - its record uses different keys - so running the same command on the superseded readback emits ten schema errors and exits 1. A reader who extends the stated verifier to the second named document reads a loud failure as a supersession defect. The substance is in fact covered by a test class; R33 points at the wrong instrument.

**Evidence**

- docs/plans/...-resync-plan.md:399 names only the checker against the 2026-08-25 matrix for a requirement about both documents
- Running that command on the superseded readback prints '10 problem(s) found' including "$: missing the required field 'package'" and exits 1
- tests/test_check_compatibility_matrix.py:1436 is what actually verifies the readback half, and its class docstring notes the readback 'is not discovered by the checker at all'

**Suggested fix.** Name both instruments in R33's verifier column - the checker for the matrix and the superseded-document test class for the pair - and say explicitly that the checker does not accept readback documents.

### F34 — Four amendments cite one repeatedly overwritten review file

`P3` · confidence 100 · `documentation-clarity` / `structure-navigation` · `manual` -> `human`  
**Where:** `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md:2469`

Four sections each name the same doc-review path as the artifact for a different review cycle, with a different bound revision and verdict. Only one file exists at that path and it holds cycle 7 alone; each cycle overwrote the last. The file defers back to the plan, so a reader verifying cycle 1's BLOCK verdict follows the citation to a cycle-7 PROCEED and is sent back to the plan. One closing sentence compounds it by naming a revision as 'the last revision of this plan the document review examined', which cycle 7 contradicts. The review trail is recoverable only from git history, not from either document.

**Evidence**

- docs/plans/...-resync-plan.md:2469, :2612, :2664, :2768 all name the same artifact path with bound revisions 1e4da2b, b164026, 4083220 and 02c8bed respectively
- The file at HEAD is 66 lines with cycles: 7, reviewed_revision 50af2593..., and states 'Cycles 1-3 and 6 applied plan edits as recorded earlier'
- docs/plans/...-resync-plan.md:2473-2475 - 'the review returned PROCEED at revision 82dcb1c. That is the last revision of this plan the document review examined.'

**Suggested fix.** Write each cycle to its own suffixed path, or at minimum cite the review commit SHA alongside the path in each amendment header, and delete the 'last revision the document review examined' sentence.

### F35 — Carried CHANGELOG names a marker the shipped script rejects

`P3` · confidence 100 · `documentation-clarity` / `runbook-safety-rollback-links-generated-drift` · `manual` -> `human`  
**Where:** `plugins/mission-control/CHANGELOG.md:173`

The 2.12.5 entry, new to the package in this range, says sync_template_docs.py resolves its package root by discovering .claude-plugin/plugin.json and fails loud when that file is missing. The script shipped two directories away does neither: this run's own transform rewrites both sites onto com.infiquetra.claude/plugin.json, and the portable package has no .claude-plugin/ directory at all. This is not an inherited upstream defect - the base copy of the changelog never mentions the finder - so the run's transform decision is what makes the carried prose wrong about the bytes beside it.

**Evidence**

- plugins/mission-control/CHANGELOG.md:173 and :175 name .claude-plugin/plugin.json
- plugins/mission-control/scripts/sync_template_docs.py:20 reads 'com.infiquetra.claude' / 'plugin.json' and :23 raises naming the same marker
- git show 0eff36e:plugins/mission-control/CHANGELOG.md | grep -c _find_package_root returns 0, so the claim entered the package with this diff
- CHANGELOG.md is classified an upstream byte copy, so the fix is a provenance note or an upstream filing, not a downstream edit

**Suggested fix.** Add a sentence to the resolve-package-root-marker paragraph in the descriptor's provenance notes stating that the carried CHANGELOG describes the upstream marker and that the portable copies use com.infiquetra.claude/plugin.json, so the generated provenance record carries the reconciliation beside the byte copy.

### F36 — Every dropped-path entry repeats all three drop reasons

`P3` · confidence 100 · `correctness` / `boundary-types-serialization-numeric-time` · `manual` -> `downstream-resolver` · *pre-existing*  
**Where:** `plugins/mission-control/PROVENANCE.json:21`

removed_from_source serializes as a list of {source_path, reason} objects, so the per-entry shape promises that reason explains that entry's path. It does not: the manifest builder writes the descriptor's single dropped_reason scalar into every entry, so all three carry the identical string concatenating the reasons for all three paths. A consumer reading one entry to learn why one path was dropped gets the reasons for all of them. This run made it worse only by degree, growing the shared string from 668 characters over two paths to 1326 over three.

**Evidence**

- scripts/sync_vendor_source.py:1328-1334 - the comprehension emits {'source_path': ..., 'reason': config.dropped_reason} for every dropped path, with one scalar shared across the loop
- plugins/mission-control/PROVENANCE.json:21, :25 and :29 - three entries, three different source_path values, one byte-identical 1326-character reason
- git show 0eff36e:ports/mission-control.json gives two dropped paths and a 668-character shared reason, so the shape predates this range

**Suggested fix.** Change provenance.dropped_reason from a string to an object keyed by dropped path, validate in scripts/port_config.py that its key set equals custody.dropped_from_source, and have the manifest builder look up the per-path reason.

### F37 — Package README's upstream version claim has no gate

`P3` · confidence 100 · `api-contract` / `versioning-deprecation` · `gated_auto` -> `review-fixer` · *pre-existing*  
**Where:** `plugins/mission-control/README.md:12`

Every other version-bearing site for this package is bound - the portable manifest to PROVENANCE.json's source_version, the root README's revision and version derived from the provenance record, CHANGELOG.md and the relocated Claude manifest by digest. The package README's own version claim is the one hand-retyped copy with nothing checking it. It is correct at this revision; the next resync can leave it naming 2.15.2 while the package ships something else, and this repository's review history records that exact class as a prior finding.

**Evidence**

- plugins/mission-control/README.md:12 - 'recorded in `PROVENANCE.json` (upstream plugin version 2.15.2)'
- grep for source_commit, source_version or 3b2b7083 in tests/test_mission_control_readme.py returns nothing
- tests/test_mission_control_rule_audit.py:788-790 - RootReadmePinTests reads the repository-root README, not the package README

**Suggested fix.** Add a test in tests/test_mission_control_readme.py asserting f"(upstream plugin version {provenance['source_version']})" appears in plugins/mission-control/README.md, mirroring the existing Packages-row derivation test.

### F38 — Evidence redaction check never reads document prose

`P3` · confidence 100 · `security` / `confidentiality-logs-errors-egress` · `gated_auto` -> `human` · *pre-existing*  
**Where:** `scripts/check_compatibility_matrix.py:940`

check_public_evidence_rules is the control that keeps addresses, hostnames and credential values out of committed evidence in a repository that may be public, but it walks only the strings inside the extracted JSON record. check_matrix validates a whole Markdown document, and every word of narrative outside the fenced record - the sections a human actually writes - is never scanned. The repository's other credential control is scoped to plugins/ by design and excludes docs/, so a hostname pasted into an evidence document's prose passes both gates.

**Evidence**

- scripts/check_compatibility_matrix.py:940 - the loop walks only the parsed record dictionary
- scripts/check_repo.py:904 - 'Scoped to ``plugins/`` on purpose', continuing that widening it 'would also make ``docs/reviews/`` a failure surface'
- Latent, not live: running the rules over each new document's entire text rather than its record returns zero problems for both, and python3 scripts/check_compatibility_matrix.py exits 0

**Suggested fix.** In check_matrix, call check_public_evidence_rules a second time over the document text outside the fenced record so narrative sections are held to the same address, hostname and credential rules.

### F39 — Sync tool docstring claims no package specifics are compiled in

`P3` · confidence 100 · `api-contract` / `specification-documentation-parity` · `safe_auto` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:11`

The module docstring states the design contract a maintainer relies on when porting the next plugin: 'Nothing about a particular package is compiled into this file, so porting a second plugin is a new descriptor rather than an edit here.' This diff breaks it. Every prior rule matches by shape or reads the descriptor; this is the first whose applicability is keyed by literal target path, and a path outside the table is refused outright. A maintainer following the docstring would write a descriptor naming the rule, hit 'declares no per-file site counts for this path', and have no way forward without editing the file the docstring says never needs editing.

**Evidence**

- scripts/sync_vendor_source.py:11-13 - the quoted contract
- scripts/sync_vendor_source.py:756-760 - PACKAGE_ROOT_MARKER_SITE_COUNTS keyed on three concrete package-relative paths
- scripts/sync_vendor_source.py:809-815 - an unlisted path raises SyncError rather than being handled generically

**Suggested fix.** Amend the docstring to record the exception explicitly - that resolve-package-root-marker carries a per-path site-count table which a second package using the rule must extend - so the stated contract matches the code.

### F40 — Unknown marker at a raises site reports a misleading count

`P3` · confidence 100 · `api-contract` / `serialization-errors` · `safe_auto` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:745`

The rule reports the same class of surprise two different ways. The .is_file() detector captures the marker openly, so an unrecognized value reaches the anchor loop and produces a message naming it. The raises detector instead closes its alternation to the two known markers, so an unrecognized value fails to match and surfaces as a count refusal claiming the file has zero raises sites - which it plainly does not. An operator resolving an upstream marker rename is told the wrong thing, and the site the rule could not read is never named.

**Evidence**

- scripts/sync_vendor_source.py:745-747 - the closed alternation (?P<marker>\\\.claude-plugin|com\\\.infiquetra\\\.claude)
- Reproduced with a third marker at the raises site only: 'declares exactly 1 raises site(s) in this file, found 0'
- Reproduced with the same third marker at the .is_file() site only: 'found a marker site anchored on com.example.claude, which this version does not describe'

**Suggested fix.** Open the capture to (?P<marker>[^/]+) in MARKER_RAISES_MATCH so an unknown marker reaches the anchor-validation loop and is reported by name, matching the .is_file() path.

### F41 — Rule prose restates the count table with nothing joining them

`P3` · confidence 100 · `architecture-maintainability` / `simplicity-abstraction-duplication-changeability` · `manual` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:762`

The per-file site counts exist twice in the same module: once as data and once narrated in English inside the rule string, which is copied verbatim into the shipped provenance record as the transform_rule of all three transformed files. Change the dict without editing the prose and the shipped provenance describes a rule that did not produce the bytes beside it, and no check notices, because --check compares bytes, not recorded rule text.

**Evidence**

- scripts/sync_vendor_source.py:756-761 holds the counts as data; :762-780 restates them in prose
- That prose is recorded three times in the shipped package, at plugins/mission-control/PROVENANCE.json:173, :355 and :455
- tests/test_port_config.py:577 is the existing precedent guarding a different constant named only in prose

**Suggested fix.** Render the per-file clauses of the rule string from PACKAGE_ROOT_MARKER_SITE_COUNTS at import time, or add a test asserting every path and count in the table appears in the rule string, so the recorded provenance cannot contradict the rule that produced the bytes.

### F42 — Incomplete site-count row raises a bare KeyError

`P3` · confidence 100 · `architecture-maintainability` / `readability-naming-error-contracts` · `safe_auto` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:827`

The rule's whole error contract is that a stop names the file, the rule, the site class and the counts. A table row omitting one of the four site classes bypasses it: the loop indexes counts[site_class] directly and the run dies with an unhandled KeyError naming neither the file nor the rule. That is the puzzle the surrounding refusals exist to prevent, and it is reachable by the most likely future edit - adding a row for a fourth carried file.

**Evidence**

- scripts/sync_vendor_source.py:826-833 iterates the literal tuple ('finder','call','is_file','raises') and reads counts[site_class] with no membership guard
- Reproduced against the shipped tree: registering {'finder': 1, 'call': 1} for a path and calling package_root_marker_transform raises KeyError('is_file') unhandled

**Suggested fix.** Validate the row's keys before the count loop and raise SyncError on a mismatch, e.g. if set(counts) != {'finder','call','is_file','raises'}: raise SyncError(f"{target_path}: rule ... declares an incomplete site-count row ({sorted(counts)}); every row states all four site classes").

### F43 — Only the first finder site is classified and rewritten

`P3` · confidence 100 · `correctness` / `intent-behavior-completeness` · `gated_auto` -> `review-fixer`  
**Where:** `scripts/sync_vendor_source.py:883`

The is_file and raises classes are handled uniformly - every match is classified and every match is rewritten - but the finder class is handled as finders[0] only, in both places, and the ordering guard compares finders[0] against calls[0] alone. The site-count table is the rule's declared extension point and accepts any integer, so a future row declaring finder: 2 would satisfy the count check, classify and rewrite only the first definition, and emit a file whose second finder still walks for .claude-plugin, with no error and beyond the reach of the mixed-marker refusal.

**Evidence**

- scripts/sync_vendor_source.py:836-853 - `if finders:` then finder = finders[0]; only that match's marker reaches anchors
- scripts/sync_vendor_source.py:883-884 - replacements.append((finders[0].start(), finders[0].end(), ...)), against the `for site in is_file_sites:` and `for site in raises_sites:` loops immediately below
- PACKAGE_ROOT_FINDER_BLOCK.finditer over a body holding two copies of the upstream block returns 2 matches, so the regex itself does not cap it
- Safe at this revision only because the shipped table caps finder at 1 for all three paths

**Suggested fix.** Loop `for finder in finders:` for both the anchor collection and the replacement append, and check ordering pairwise (finders[i].end() <= calls[i].start()), matching how is_file_sites and raises_sites are already handled.

### F44 — No gate checks skill commands against the CLI surface

`P3` · confidence 100 · `agent-usability` / `discoverability-invocation-schemas` · `manual` -> `human` · *pre-existing*  
**Where:** `tests/test_mission_control_readme.py:275`

The fenced-command guard parses every bash block in the package README and asserts each verb is in the audited read-only or mutating set. No equivalent guard exists for the seven SKILL.md files, which are the surface an agent actually invokes from, and check_repo.py touches SKILL.md only to require the document exists and its frontmatter parses. That is why removing `rollout update` from the CLI required a hand edit of the rollout skill rather than being caught, and why the create-option instructions survive with the suite green.

**Evidence**

- tests/test_mission_control_readme.py:275-301 - the guard binds only plugins/mission-control/README.md
- scripts/check_repo.py:805-811 - skill validation is a missing-document check plus a frontmatter read; no command extraction exists anywhere in scripts/ or tests/
- The full suite is green at this revision while plugins/mission-control/skills/labels/SKILL.md:120 documents a verb the package classifies as a no-op

**Suggested fix.** Extend the existing documented_bash_commands / sdlc_manager_verbs helpers over plugins/mission-control/skills/*/SKILL.md and their references/*.md, asserting every extracted verb is a live argparse subcommand. That alone would have caught the removed rollout update mechanically.

### F45 — No gate binds mission-control custody to its provenance record

`P3` · confidence 100 · `correctness` / `caller-enum-consumer-completeness` · `manual` -> `review-fixer` · *pre-existing*  
**Where:** `tests/test_sync_vendor_source.py:1371`

This run moved three files from byte copies to transforms, changing their provenance classification. The two tests that assert the descriptor's custody table agrees with the shipped provenance manifest are both bound to a different package, and the mission-control class has no equivalent. check_repo.py validates that a deterministic-transform entry carries non-empty digest and version fields, never which rule produced it. The only check that would catch a disagreement is --check, which needs an upstream clone and runs in no CI job.

**Evidence**

- tests/test_sync_vendor_source.py:48 - CONFIG = svs.load_config('unifi', ROOT), the fixture behind the custody-agreement test at :1219
- tests/test_port_config.py:471 - port_config.load('unifi', ROOT), the fixture behind the shipped-path custody test at :535
- grep for resolve-package-root-marker across tests/ returns a single hit that only pins the registry set
- Verified by hand at this revision that the classifications do agree: 46 byte copies + 5 client byte copies = 51 upstream-byte-copy; 12 entrypoint transforms + 1 relocated manifest = 13 deterministic-transform; 70 manifest entries + PROVENANCE.json = the 71 files on disk, no path in two classes

**Suggested fix.** Add a test to the mission-control shipped-package class mirroring the unifi custody-agreement test, asserting the full custody-class-to-classification map and that each of the three package-root paths records transform == PACKAGE_ROOT_MARKER_TRANSFORM_NAME at the registered version.

### F46 — PyYAML guard asserts a file-global substring, not the job

`P3` · confidence 100 · `testing` / `behavior-sensitive-assertions` · `safe_auto` -> `review-fixer`  
**Where:** `tests/test_sync_vendor_source.py:1514`

assertIn('pyyaml', ci, 'the CI install line dropped pyyaml') passes for the string anywhere in the workflow - a comment, a different job, a commented-out line - so it does not hold the property its message names. It also protects the wrong job: the dependency-free validate job needs PyYAML too, because it discovers a test module that imports sync_template_docs, which imports yaml at module scope, and that job has no install line for the test to check. Two unrelated contracts also share one method whose name says nothing about CI.

**Evidence**

- tests/test_sync_vendor_source.py:1513-1514 - the whole workflow file is read and searched
- grep -c pyyaml .github/workflows/ci.yml returns 1, on the plugin-tests install line; the assertion cannot distinguish that line from any other occurrence
- Measured by the controller: in a bare python3.12 venv with no PyYAML, `python3 -m unittest discover -s tests` fails with ModuleNotFoundError: No module named 'yaml' raised from plugins/mission-control/scripts/sync_template_docs.py:14 via tests/test_mission_control_rule_audit.py:46

**Suggested fix.** Anchor the assertion on the install line - require a line matching r"pip install .*\bpyyaml\b" - move it into its own test method, and separately decide whether the validate job's transitive PyYAML dependency should be made explicit or removed.

### F47 — KTD16 records two rejected alternatives, never the descriptor

`P3` · confidence 75 · `architecture-maintainability` / `significant-decision-documentation` · `advisory` -> `human`  
**Where:** `docs/engineering-journal/DECISIONS.md:432`

The decision that abandons the one-universal-shape guarantee records only two rejected alternatives - drop both tests from source, and file upstream and stop. It never considers the option the repository's own architecture rule points at: carrying the per-file site counts in the port descriptor. That option was in fact structurally unavailable, because the descriptor validates each transform entry as a closed object of exactly path and rule, so a parameterized rule cannot be expressed without a schema bump. None of that is written down, so a maintainer facing the next parameterized rule cannot tell whether the descriptor was weighed and rejected or simply not thought of.

**Evidence**

- docs/engineering-journal/DECISIONS.md:432 - 'Rejected alternatives. Drop both from source ... File upstream and stop'; the mirrored plan section lists the same two
- scripts/port_config.py:249 - _closed(entry, ENTRYPOINT_TRANSFORM_ENTRY_FIELDS, entry_where), with the surrounding docstring stating the rule name is validated as a name only
- AGENTS.md:47-51 names the port descriptor as the home for per-package custody data, which is what the site counts are

**Suggested fix.** Amend the KTD16 entry with a third rejected alternative recording that per-path rule parameters in ports/*.json would require a schema-4 bump of the closed {path, rule} entry, why that bump was not taken in this run, and a 'revisit when a second rule needs parameters' condition.

## Consolidated fix requests

Grouped by owner, routing class, and overlapping paths, so disjoint work can go to
different workers. All 16 are unresolved.

| Fix id | Route | Findings | Paths |
|---|---|---|---|
| `fix-a51913327e5c` | manual -> human | F09, F32, F34 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-07ae101ba7f9` | manual -> human | F35 | `plugins/mission-control/CHANGELOG.md` |
| `fix-c77fb632f03a` | gated_auto -> review-fixer | F18 | `ports/mission-control.json` |
| `fix-6dc8e0a1f009` | gated_auto -> review-fixer | F21, F43 | `scripts/sync_vendor_source.py` |
| `fix-7dc84f790a3a` | gated_auto -> review-fixer | F03 | `tests/test_mission_control_rule_audit.py` |
| `fix-986cabe796ba` | manual -> review-fixer | F06 | `docs/evidence/2026-08-30-mission-control-compatibility-matrix.md` |
| `fix-394d21c0f7b3` | manual -> review-fixer | F19, F20, F41 | `scripts/sync_vendor_source.py` |
| `fix-c4afaa54ec28` | manual -> review-fixer | F23, F24 | `tests/test_check_compatibility_matrix.py` |
| `fix-faedaeedae69` | manual -> review-fixer | F04 | `tests/test_sync_vendor_source.py` |
| `fix-cabf8331a97c` | safe_auto -> review-fixer | F05 | `docs/README.md` |
| `fix-5dc99edd4dd9` | safe_auto -> review-fixer | F31 | `docs/evidence/2026-08-30-mission-control-post-activation-readback.md` |
| `fix-eb09fd0f4150` | safe_auto -> review-fixer | F07, F08, F10, F33 | `docs/plans/2026-08-30-issue-50-mission-control-resync-plan.md` |
| `fix-4d99d5abe366` | safe_auto -> review-fixer | F11 | `plugins/mission-control/README.md` |
| `fix-df856eeccddf` | safe_auto -> review-fixer | F39, F40, F42 | `scripts/sync_vendor_source.py` |
| `fix-faa9aac1b201` | safe_auto -> review-fixer | F28, F29 | `tests/test_mission_control_rule_audit.py` |
| `fix-8ddc29606f0a` | safe_auto -> review-fixer | F46 | `tests/test_sync_vendor_source.py` |

## Lens scores

Seven caller-supplied lenses, at most three running concurrently. Acceptance requires a
derived overall of at least 9.0 **and** every applicable dimension at 7.0 or above; the
derived overall is the mean of a lens's applicable dimension scores. No lens met either rule.

| Lens | Derived overall | Accepted | Dimensions below the 7.0 floor |
|---|---|---|---|
| `architecture-maintainability` | 6.71 | no | `architectural-fit-ownership-single-sources`, `dependency-direction`, `simplicity-abstraction-duplication-changeability`, `conventions-portability-configuration` |
| `correctness` | 7.80 | no | — |
| `security` | 7.40 | no | `confidentiality-logs-errors-egress` |
| `testing` | 4.80 | no | `requirements-regression-coverage`, `negative-edge-state-concurrency-time`, `behavior-sensitive-assertions`, `realistic-seams-mocks-integration-evidence`, `determinism-isolation-diagnostics-maintainability` |
| `api-contract` | 7.86 | no | — |
| `agent-usability` | 6.60 | no | `discoverability-invocation-schemas`, `machine-readable-output-actionable-errors` |
| `documentation-clarity` | 6.00 | no | `shipped-behavior-parity`, `completeness-audience-prerequisites`, `structure-navigation`, `runnable-examples-actionability`, `runbook-safety-rollback-links-generated-drift` |

### Per-dimension detail

**`architecture-maintainability`** — `architectural-fit-ownership-single-sources` 6, `separation-of-concerns` 7, `dependency-direction` 6, `simplicity-abstraction-duplication-changeability` 6, `readability-naming-error-contracts` 8, `conventions-portability-configuration` 6, `significant-decision-documentation` 8

**`correctness`** — `intent-behavior-completeness` 7, `state-data-invariants-transactions-concurrency` 8, `boundary-types-serialization-numeric-time` 8, `side-effects-errors-resource-lifecycle` 9, `caller-enum-consumer-completeness` 7

**`security`** — `authentication-authorization-tenant-isolation` 7, `input-trust-boundaries-injection` 9, `secrets-cryptography-session-handling` 8, `dependency-supply-chain` 7, `confidentiality-logs-errors-egress` 6

**`testing`** — `requirements-regression-coverage` 5, `negative-edge-state-concurrency-time` 5, `behavior-sensitive-assertions` 5, `realistic-seams-mocks-integration-evidence` 5, `determinism-isolation-diagnostics-maintainability` 4

**`api-contract`** — `interface-contract-compatibility` 7, `versioning-deprecation` 8, `serialization-errors` 8, `retry-idempotency-semantics` 7, `pagination-rate-limits` 9, `sdk-generated-client-impact` 9, `specification-documentation-parity` 7

**`agent-usability`** — `capability-parity-reachability` 7, `discoverability-invocation-schemas` 6, `context-constraints-acceptance-examples` 7, `machine-readable-output-actionable-errors` 6, `safe-bounded-idempotent-resumable-context-cost` 7

**`documentation-clarity`** — `shipped-behavior-parity` 6, `completeness-audience-prerequisites` 6, `structure-navigation` 5, `terminology-cross-document-consistency` 7, `runnable-examples-actionability` 6, `runbook-safety-rollback-links-generated-drift` 6

## Coverage

**Residual risks.**

- The branch has never been pushed, so no continuous-integration run has ever exercised this
  work. `F03` is the concrete consequence; there may be others that only the runner's
  environment would surface.
- Six of the eleven pre-existing P2/P3 findings are in code carried verbatim from upstream and
  cannot be repaired here — custody forbids a downstream patch. They need upstream filings, and
  `docs/engineering-journal/QUEUED.md` currently states that all eight prior filings are
  consumed and nothing remains open, which is no longer true.
- The plan's per-commit red/green predictions were re-run and hold exactly, so bisection across
  the branch behaves as documented. The three intermediate red commits are intentional and
  belong to a unit whose acceptance criteria carry no suite requirement.

**Testing gaps.**

- No CI job runs `sync_vendor_source.py --check`, so custody drift between this repository and
  upstream is caught only when a person runs it with an upstream clone on disk.
- The seven-lens panel could not evaluate the GitHub-hosted runner image directly; `F03` rests
  on a measured base-green / head-red comparison in a controlled interpreter plus the
  workflow's own written contract, not on a runner observation.
- R38 (unrelated worktrees, branches and sessions preserved) is unverifiable from a single
  revision.

**Method.** Seven caller-supplied lenses, exactly as specified and with no judgment
substitution: architecture and maintainability, correctness, security, testing, API contract,
agent usability, documentation clarity. Maximum concurrency observed: **3**. Each lens ran as a
read-only agent in a disposable worktree. The caller-supplied selection was the approval record;
no lens-selection question was asked. This review mutated no reviewed source and created no
commit, no pull request and no issue.

## Route

**`repairs_requested` → `dispatch_repairs`.** The 16 consolidated fix requests go back to the
author or to `/work`, which owns repair changes and implementation commits. This gate does not
apply them.

Suggested order — the two blocking items first, then the cheap correctness repairs, then the
documentation set, then the upstream filings:

1. `fix-7dc84f790a3a` (`F03`) — restore the dependency-free CI job.
2. `fix-faedaeedae69` (`F04`) — test the transform rule.
3. `fix-df856eeccddf`, `fix-6dc8e0a1f009`, `fix-faa9aac1b201` (`F39`–`F43`, `F21`, `F28`,
   `F29`) — the transform's error contract, its residue and finder handling, and the two
   one-sided test guards.
4. `fix-eb09fd0f4150`, `fix-cabf8331a97c`, `fix-4d99d5abe366`, `fix-5dc99edd4dd9`,
   `fix-c77fb632f03a`, `fix-986cabe796ba` — the plan, descriptor, README and evidence
   corrections.
5. `fix-394d21c0f7b3`, `fix-c4afaa54ec28`, `fix-8ddc29606f0a`, `fix-a51913327e5c` — the
   structural work and the human judgment calls.
6. `fix-07ae101ba7f9` plus the pre-existing upstream-owned findings (`F01`, `F02`, `F12`–`F16`)
   — upstream filings against `infiquetra/infiquetra-claude-plugins`, recorded in
   `docs/engineering-journal/QUEUED.md`.

Resubmit for cycle 2 only after the repairs land. The retained-lens delta check applies at that
point: a lens whose reviewed revision did not change keeps its score.
