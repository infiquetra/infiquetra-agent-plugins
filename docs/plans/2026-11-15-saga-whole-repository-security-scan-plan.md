---
title: Saga whole-repository security scan
type: feat
status: active
date: 2026-11-15
origin: docs/brainstorms/2026-11-15-saga-whole-repository-security-scan/capability.md
backend: inline
---

# Saga whole-repository security scan

## Summary

Add one portable command that runs Saga's existing security adapters against one committed repository tree and prints readable findings while saving records outside the target.

The first usable checkpoint is U2: the complete command, output summary, and safety behavior work before U3 adds skill discovery and documentation. A separate test-writer commit precedes implementation; this plan PR contains no implementation.

## Problem Frame

Code review correctly excludes findings that predate a change; an operator's repository audit needs those findings too.

Issue [321](https://github.com/infiquetra/infiquetra-agent-plugins/issues/321) is the acceptance authority. Its [Architect technical-context handoff](https://github.com/infiquetra/infiquetra-agent-plugins/issues/321#issuecomment-6899032128) binds the context to source commit `ebc263ed91e1c50f2e90fbacd8ef0572232f3ffb`; the [snapshot and scratch-verification ruling](https://github.com/infiquetra/infiquetra-agent-plugins/issues/321#issuecomment-6899176443) and [pip-audit and version-policy ruling](https://github.com/infiquetra/infiquetra-agent-plugins/issues/321#issuecomment-6899222532) settle all four planning questions. The final issue-body revision is 2026-11-15T18:31:15Z, author-recorded SHA-256 `0da29876a1bf3e7f9ffc0dc13bfd2d0cc5d4d4af0cad2613f994c60c3fd5eac0` after stripping trailing whitespace; it supersedes the older filing documents where they differ, which are retained as filing history.

The security catalogue contains twelve rows: eleven executable adapters and the Swift dependency-audit gap. Nine executable rows work on source alone; two synthesize CDK templates and require explicit opt-in. Nine executable rows have pins; gitleaks and osv-scanner record `not-recorded`.

## Requirements

The R-IDs map directly to the issue's nine acceptance criteria.

- R1. Scan HEAD by default, or a named commit, using the catalogue's security rows; save records and a readable summary outside the target (AC-1).
- R2. Retain findings anywhere in the selected tree, including files untouched by the latest commit, for both line and base/head adapters (AC-2).
- R3. Leave the target's files, index, objects, refs, configuration, and worktree registrations unchanged on success and failure (AC-3).
- R4. Refuse output inside the target, including a path resolving there through a symlink, before scanning (AC-4).
- R5. Report every catalogue security row as ran, skipped, or degraded, with reason, actual version when observed, declared pin or its absence, and counts by finding level; identify advisory-service disclosures (AC-5).
- R6. Skip cdk-nag and checkov-cdk unless each is requested by name; do not execute target code by default (AC-6).
- R7. Return distinct statuses for a complete scan without findings, a complete scan with findings, and an incomplete scan; incompleteness takes precedence over findings (AC-7).
- R8. Preserve existing review-call behavior and every existing test in `plugins/saga/tests/test_review_tools.py` unchanged (AC-8).
- R9. Add the portable security-scan skill and descriptor entries, document usage and limits, and satisfy repository validation (AC-9).

Across R1–R9, disclose no matched secret text, use inert fixtures, add no dependency or version pin, and run no model. Findings remain local and are never automatically sent to reviewers, services, or issue trackers.

## First usable checkpoint

U2 delivers a command Jeff can run from the implementation checkout, with a scratch clone at the sibling path shown below.

```bash
python3 plugins/saga/scripts/security_scan.py --repo ../scratch-security-scan --output ../security-scan-results/run-001
```

This **single command** scans the scratch clone's committed HEAD, prints the summary and finding locations to the terminal, and writes `summary.md`, `summary.json`, and `findings.json` plus the existing record files under the external output directory. No follow-up command is required to read the findings; the summary includes rule, relative file, line when present, and level, without secret text.

The earliest usable revision is the future **U2 completion commit**, after the U1 test commit has been integrated and the U2 functional checks pass. This plan's commit and the deliberately failing U1 commit do not provide the command; the Lead records the actual U2 SHA when delivered, without inventing it during planning.

Use `--commit <commit>` to choose an earlier tree, repeat `--include-synthesized <adapter-id>` to allow a named CDK row, and optionally use `--timeout <positive-seconds>` to override each tool's scan timeout. Optional `--profile <path>` accepts an operator-supplied profile outside the resolved target only; without it, catalogue defaults and the existing machine rule-cache record apply. Output must be absent or an empty directory; a populated run directory is refused so an old result cannot look current.

Use a fresh run directory for every invocation. There is no option to enable pip dependency resolution.

## Key Technical Decisions

These choices reuse the proven runner while keeping audit policy in the new entrypoint.

1. **KTD1 — Scan a standalone snapshot repository with an empty orphan base.** Read the selected commit's tracked tree without creating a worktree or object in the target; materialize it into a private disposable repository with an empty-tree orphan base and one snapshot child commit. Preserve tracked paths, regular-file bytes, executable modes, symlinks and gitlink (`160000`) entries without dereferencing links outside the tree or checking out submodule working trees; carry each gitlink unchanged as a gitlink tree entry. Never copy the target's Git configuration, hooks, dependency environments, untracked files or history.

   Compare the snapshot tree ID with the original selected commit's tree ID **before any tool row runs**; a mismatch is incomplete, never clean, so export-ignore and similar omissions cannot silently shrink the scan. Every tracked gitlink/submodule is reported in the summary as an unscanned submodule gap and makes the scan incomplete with exit `2`, even when snapshot tree equality succeeds. Never read submodule content from the target's working tree or fetch it.

   This makes every source line new and gives base/head adapters an empty baseline while preventing gitleaks from traversing earlier target history. The summary always names the original selected commit, never the disposable snapshot commit.

2. **KTD2 — Select by catalogue lens and retain the existing invocation builders.** Resolve rows from `review-tools.yaml` and match them to `default_adapters()` by identity; select `lens: security`, never a second list of commands or nine hardcoded source-tool IDs. An unmatched future executable row is visibly degraded rather than silently dropped; a fixture adapter added with a security row is selected automatically. Keep explicit scan policy for the two code-executing CDK IDs, and retain the Swift gap as a reported row.

3. **KTD3 — Reuse `review_tools.run` with `framework=False`.** Supply the security adapters, a trusted external profile or empty external default, scan-owned output/cache locations and a process observer; never run profile test commands, coverage, mutation tools, dependency installs, or fix-mode adapters. Per-adapter observation distinguishes a successful zero-hit invocation from no invocation, missing tools and parser failures; merge records deterministically across rows. Pins and rule choices come only from the catalogue or that external profile, never the target `.saga-profile.json`; keep the runner's configuration-stripping behavior in force and do not let review-only profile-change notes masquerade as an unrun security tool.

4. **KTD4 — Preserve review defaults through a keyword-only seam.** The shared runner gains a keyword-only scan-policy seam whose default preserves today's review results; never edit an existing regression test to accommodate it. Resolve **every** row's pin using review's existing precedence, operator profile pin first and catalogue default second: a resolved `not-recorded` is unpinned and does not degrade the row by itself, while a recorded pin mismatch or unreadable version degrades it and makes the scan incomplete. Decide by resolved value rather than gitleaks/osv-scanner's names, and never author a new catalogue pin.

5. **KTD5 — Keep failures observable and bounded.** Reuse each row's current timeout (120–600 seconds among security rows), allowing the explicit positive scan-only override above; do not claim those review-sized bounds have been measured sufficient for arbitrary repositories. A timeout, missing applicable tool, real pin mismatch, unusable rule cache, known applicable gap, parser failure or execution failure makes the scan incomplete; every tracked gitlink/submodule is an unscanned submodule gap reported in the summary and requires exit `2`, without reading target submodule working trees or fetching content. Intentional synth opt-out and absent applicable input are skips with reasons, not claims of cleanliness and not execution failures.

6. **KTD6 — Publish a scan summary, not a review verdict.** Use exits `0` complete/no findings, `1` complete/findings and `2` incomplete, including invalid input or an operational failure; incomplete wins when findings also exist. Retain the existing normalized `review_records.v1` finding shape; use the existing computed `blocks`, `fix-later` and `note` severity levels for per-row summary counts and display, without manufacturing a new score or inferring health from `review_tools.run`'s exit `0`, which also permits all-degraded output. The summary states the original target commit, snapshot scope, row statuses, pin/version metadata, per-level counts, reasons and finding locations; `introduced` is relative to the synthetic empty base, not a claim the latest target commit introduced the finding.

7. **KTD7 — Protect local findings and credentials.** Resolve target/output paths before any copy or tool call, including linked-worktree Git storage, and refuse output inside target-controlled storage. Use private scan directories, a fresh tool HOME and the runner's environment allow-list; make no new credential, network, or permission grant. Read only the existing local Semgrep cache and its machine-record digest, stage validated rules into scan-owned storage if needed, and keep new raw reports/caches outside the target; sanitize gitleaks output before persistence or printing, including raw cache bytes, because the shared raw-output stabilizer retains match fields even though the normalized parser drops them.

8. **KTD8 — Gate source execution explicitly.** CDK synthesis is a per-row opt-in with its existing narrowed environment and timeout; absent opt-in, no synth process starts. Declare pip-audit's scan-only `--disable-pip --no-deps` arguments **beside its existing invocation in `review_adapters_python.py`**, never in `security_scan.py`: audit exactly pinned requirement files only, report any other file as degraded with the reason and an incomplete scan, and offer no resolution-enabling option. The summary explicitly says pip-audit audits only what the files list; preserve ordinary review's identical invocation and pin it in T25.

   Preserve the current advisory-service access and metric/offline flags; name osv-scanner, pip-audit and npm-audit when invoked as rows that can send package names and versions, distinguish this disclosure from uploading source or findings, and describe cargo-deny's advisory-database fetch separately. The new script owns no tool invocation; its role is selection, isolated execution policy and reporting.

## Grounding and seam evidence

The existing seams cover both comparison kinds without requiring a new whole-tree filter in review calls.

| Evidence at source commit `ebc263ed` | Planning observation | Limit |
|---|---|---|
| `plugins/saga/scripts/review_tools.py:442`, `:514`, `:1128` | Adapter selection, line filtering, `adapters=`, `runner=` and keyword-only `framework=False` already exist | Does not prove final CLI behavior |
| `plugins/saga/scripts/review_tools.py:1994` | Empty-base source scan exercised for all six real base/head invocation builders: osv-scanner, pip-audit, cdk-nag, checkov-cdk, npm-audit, cargo-deny; each retained one canned head finding | Process and parser were stubbed; no scanner binary or advisory service was called |
| `plugins/saga/scripts/review_tools.py:514` | Same disposable probe retained a line finding in the snapshot tree against an empty base | Permanent U1 tests also compare with an ordinary latest-commit diff |
| `plugins/saga/scripts/review_adapters_all_languages.py:273` | gitleaks uses `detect`; a history-bearing clone would violate selected-tree scope | U1 pins removed historical findings absent, current findings retained |
| `plugins/saga/scripts/review_adapters_all_languages.py:298`, `:346` | Normalized gitleaks records omit Match/Secret, while stable raw output preserves their bytes | U1 asserts absence across output, terminal and scan-owned caches |
| `plugins/saga/scripts/review_tools.py:1521`, `:3844` | Tools receive a fresh HOME and allow-listed environment; runner worktrees are created in the supplied repo | Supply only the disposable snapshot repo, never the target |
| `plugins/saga/scripts/review_adapters_python.py:663` | pip-audit reads requirements; ordinary invocation does not disable pip resolution | Scan-only no-resolution flags require explicit coverage |
| `plugins/saga/tests/test_review_tools.py` | 127 collected tests in 101 test functions; all 127 passed unchanged in 44.94 seconds during planning | Baseline evidence is not final implementation verification |
| `ports/saga.json` | `assessment.entrypoints` and `assessment.skill_units` declare runnable surfaces | Descriptor declaration alone is not compatibility proof |

The disposable probe used inert example content and was removed. It exposed `not-recorded` being treated as a mismatch by the ordinary review version logic; the scan must handle that case without changing review's default policy.

## Implementation Units

Scope class: Standard, with three implementation units. The execution order is U1 → U2 → U3; these are work units, not child issues.

### U1. Commit the independent test contract

The dedicated test writer commits the finite red suite before runtime implementation starts.

**Goal:** Fix the externally observable command contract and the review baseline independently of the implementation.

**Requirements:** R1–R9; AC-1–AC-9 are represented in the test inventory below, with AC-8 also checked on the unchanged runner.

**Dependencies:** Independent plan review has cleared; no implementation commit exists yet.

**Files:** Create `plugins/saga/tests/test_security_scan.py` only. Do not edit `plugins/saga/tests/test_review_tools.py` or create a placeholder entrypoint to make the test file import.

**Assignment and lanes:** `test-writer-1`, in the separate branch/worktree allocated by the Lead. The test writer supplies its commit SHA and observed red results; the Lead integrates that commit before U2 starts. No worker is spawned or staffed by this plan.

**Approach:** Exercise the public CLI in subprocesses with disposable Git repositories, fake tool binaries and canned inert reports. Import any not-yet-existing module inside individual tests rather than at collection time, so missing production code causes the named test failures rather than hiding the test set behind one collection error. Capture and validate structured output and terminal output; never call installed scanners, package indexes, private services or the real operator home in hermetic tests.

**Patterns to follow:** The fixture repository, fake process, isolated environment and no-network conventions in `plugins/saga/tests/test_review_tools.py`; runnable-entrypoint expectations in `tests/test_client_entrypoints.py`.

**Test scenarios:** The next section is the exhaustive initial test-writing assignment: 24 named expected-red feature tests and one passing review-baseline control, without hidden additional parameterized cases. Individual tests may loop over the finite subcases stated there. Stub outputs are evidence for program behavior, not proof that a real scanner detects a flaw.

**Verification:** Every test collects; the 24 feature tests fail for the absent feature, and the baseline control and unchanged review suite pass. Record exact failure counts and the separate branch/commit in the implementation handoff. Intentional red is the deliverable for this unit; do not send it to code review as a completed capability.

**Functional checks:**

```functional-checks
- name: review-baseline-before-implementation
  command: python3 -m pytest plugins/saga/tests/test_review_tools.py -q
  proves: [AC-8]
  runs: local
```

### U2. Deliver the usable whole-repository command

The runtime unit implements the full scan-to-readable-findings path and turns every runtime test green.

**Goal:** Deliver the first usable checkpoint command, including summary, exit semantics and machine/data protections.

**Requirements:** R1–R8; AC-1–AC-8.

**Dependencies:** U1's test commit is integrated, with its independent red evidence available.

**Files:** Create `plugins/saga/scripts/security_scan.py`; modify `plugins/saga/scripts/review_tools.py` for the default-preserving keyword-only scan-policy seam and `plugins/saga/scripts/review_adapters_python.py` to declare pip-audit's scan arguments beside its unchanged review invocation. Read the other existing adapter modules and catalogue without changing their commands, pins or dependencies; `plugins/saga/tests/test_security_scan.py` is the independent oracle, with test repairs routed to the Lead rather than weakened by the implementer.

**Assignment and lanes:** The Lead assigns the initial implementation worker; U2 is serial after U1. Shared-runner custody stays with this unit alone.

**Approach:** Follow KTD1–KTD8: validate inputs, resolve the original commit, construct the independent single-root snapshot plus empty base, select security rows, apply explicit scan policies, run/observe existing adapters, merge valid records, print/write the summary, and clean scratch state in failure paths. Carry each source gitlink (`160000`) unchanged as a gitlink tree entry so snapshot tree-ID equality holds before any row runs, without checking out a submodule working tree; report every tracked gitlink/submodule as an unscanned submodule gap in the summary and make the scan incomplete with exit `2`. Never read submodule content from the target's working tree or fetch it; do not treat an uninvoked row as ran or a failed row as zero findings, and keep rule-cache metadata tied to validated bytes.

**Patterns to follow:** `review_tools.run`, `default_adapters`, `_base_and_head`, `_tool_env`, `subprocess_runner`, `semgrep_cache`, and `review_records.validate`; `plugins/saga/scripts/review_diagnostics.py` for private directory handling.

**Test scenarios:** T01–T23 and the T25 regression control below. Error paths include missing/invalid commit, empty repository tree, inaccessible output, unknown or duplicate opt-in, nonpositive timeout, a populated output directory, malformed tool output, timeout, and a tool failure after scratch creation; each must refuse or report incomplete without touching the target. Small inert credential and filesystem sentinels prove no inherited credentials, no hook execution and no external-link reads by the new copy path.

**Verification:** The checkpoint command runs end to end with all runtime tests green, prints finding locations, produces the selected commit's records externally and leaves the target byte-for-byte unchanged. The only remaining red test is U3's skill/descriptor registration check; existing review tests stay untouched.

**Functional checks:**

```functional-checks
- name: whole-tree-runtime
  command: python3 -m pytest plugins/saga/tests/test_security_scan.py -q -k 'not skill_entrypoint_registered'
  proves: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
  runs: local
- name: user-command-help
  command: python3 plugins/saga/scripts/security_scan.py --help
  proves: [AC-1]
  runs: local
- name: unchanged-review-runner
  command: python3 -m pytest plugins/saga/tests/test_review_tools.py -q
  proves: [AC-8]
  runs: local
```

### U3. Make the command discoverable and record delivery limits

The final unit adds the skill and documentation without changing runtime behavior.

**Goal:** Let any shell-capable agent discover, run and interpret the scan using maintained source.

**Requirements:** R9 and explanatory coverage for R1, R5–R7; AC-9.

**Dependencies:** U2's command and output contract are working.

**Files:** Create `plugins/saga/skills/security-scan/SKILL.md`; update `plugins/saga/README.md`, `plugins/saga/references/review-tools.md`, `plugins/saga/CHANGELOG.md`, `ports/saga.json`, and the existing plan-related entries in `docs/engineering-journal/DECISIONS.md` and `docs/engineering-journal/LEARNINGS.md` when delivery adds empirical evidence. No installed copy, root marketplace, version pin or generated Fleet Core bundle changes are needed for the new skill/entrypoint declarations.

**Assignment and lanes:** The Lead assigns documentation custody. Drafting can occur beside U2 after the contract is frozen, but the final command examples and registration proof wait for U2; neither unit edits the other's files.

**Approach:** Document the single checkpoint command, HEAD/named-commit scope, external output, real finding locations, exit precedence, intentional skips, unpinned versions, advisory requests, opt-in synthesis risk and absence of history/uncommitted scanning. Explain that the tool is deterministic, independent of reasoning audits, and neither files nor uploads findings. Record the feature under the existing changelog convention without an unplanned release/version synchronization across root packaging.

**Patterns to follow:** Existing portable skills under `plugins/saga/skills/`, the Saga port descriptor, and `docs/public-safe-summary.md`.

**Test scenarios:** T24 checks that the skill exists, gives the executable entrypoint and output/exit guidance, and both descriptor arrays declare their surfaces. Repository validation proves packaging conventions; the smoke proves the documented command reaches the behavior it describes.

**Verification:** All 25 new tests and the unchanged review suite pass; descriptor validation accepts the surfaces, and the combined-branch smoke is recorded before code review. Do not claim live compatibility across clients or machines based on these local results.

**Functional checks:**

```functional-checks
- name: registered-security-scan-skill
  command: python3 -m pytest plugins/saga/tests/test_security_scan.py -q -k skill_entrypoint_registered
  proves: [AC-9]
  runs: local
- name: catalogue-repository-validation
  command: python3 scripts/check_repo.py
  proves: [AC-9]
  runs: local
```

## Finite independent test inventory

`test-writer-1` commits exactly these initial named tests in `plugins/saga/tests/test_security_scan.py`, on its separate Lead-assigned branch, before U2 begins.

| ID | Test name | Input, action and expected outcome | Criterion |
|---|---|---|---|
| T01 | `test_help` | Run the script's `--help` in a subprocess; exit 0 and document repository, commit and external-output arguments | AC-1 |
| T02 | `test_selection_catalogue_future_row` | Add a fixture security row and matching stub adapter plus a non-security adapter; automatically run the former, exclude the latter, and report an unmatched executable row as degraded | AC-1, AC-5 |
| T03 | `test_whole_repository_lines` | Make a finding file in an earlier local fixture commit, then touch another file; ordinary review omits the finding, scan retains it | AC-2 |
| T04 | `test_whole_repository_base_head` | Exercise the finite six base/head rows named in Grounding with canned head findings and an empty base; each finding survives without an empty-base failure | AC-2 |
| T05 | `test_named_commit_and_head` | Compare default HEAD and an earlier named commit with dirty/untracked files and a removed historical marker; only the selected committed tree is read, deleted historical content is absent; invalid commit returns 2 | AC-1, AC-2 |
| T06 | `test_target_untouched_success` | Snapshot target worktree bytes/modes, status, index, objects, refs, config and registrations; successful scan changes none; repeat for a linked worktree; a tracked export-ignore rule cannot omit files, and a deliberate snapshot tree-ID mismatch returns incomplete before any row runs. A commit containing a gitlink (`160000`) preserves that entry and passes snapshot tree-ID equality without checking out or reading target submodule content or fetching it; the summary reports the unscanned submodule gap and the scan exits `2` incomplete with the target unchanged | AC-1, AC-3, AC-5, AC-7 |
| T07 | `test_target_untouched_failure_cleanup` | Fail a stub tool after snapshot creation; target remains unchanged and disposable repositories/worktrees are removed | AC-3, AC-7 |
| T08 | `test_output_location_refuses_inside` | Select target root, nested paths and Git storage as output; refuse before any tool call or new target entry | AC-4 |
| T09 | `test_output_location_symlink` | Resolve an outside symlink back into the target, including a nonexistent child under it; refuse before a tool runs | AC-4 |
| T10 | `test_output_location_outside` | Use absent and empty external directories; receive records and summaries; inaccessible output returns 2 with no target changes | AC-1, AC-4 |
| T11 | `test_summary_states_and_levels` | Combine a clean invocation, multiple finding levels, no applicable input and the applicable Swift gap; every security row has status/reason/counts and the summary prints finding locations | AC-5 |
| T12 | `test_summary_versions_unpinned` | Fake actual versions for the two `not-recorded` rows and a differently named fixture row; resolved absent pin does not degrade by itself, explicit external profile pin takes precedence and source profile cannot change it; refuse an inside-target profile | AC-5 |
| T13 | `test_summary_missing_tools` | Hide an applicable binary from fixture PATH; row is degraded with missing reason, never ran/clean, and status is incomplete | AC-5, AC-7 |
| T14 | `test_summary_version_mismatch` | Fake a version different from an actual catalogue pin or external profile pin, plus an unreadable version; retain observed/expected values and reasons, with incomplete status even if findings exist | AC-5, AC-7 |
| T15 | `test_summary_semgrep_cache` | Test absent cache and mismatched digest in a fake machine home; preserve the two distinct rule-cache reasons, make no download, return incomplete | AC-5, AC-7 |
| T16 | `test_summary_timeout_or_bad_output` | Stub timeout, nonzero execution failure and malformed report; produce degraded reasons and incomplete status, never a clean zero-hit row | AC-5, AC-7 |
| T17 | `test_synthesized_default_skip` | Fixture has `cdk.json` whose command would write an inert sentinel; neither CDK row invokes it by default, and both summary skips explain opt-in | AC-6 |
| T18 | `test_synthesized_named_opt_in` | Request only cdk-nag, only checkov-cdk, then both by repeatable names; exactly the requested rows run; reject unknown names and tolerate duplicate names once | AC-6 |
| T19 | `test_exit_status` | Clean, findings-only, incomplete-only and incomplete-plus-findings fixtures produce 0, 1, 2 and 2; empty-tree behavior remains explicit, nonpositive timeout is refused | AC-7 |
| T20 | `test_end_to_end` | Real subprocess CLI with fake binaries/caches and a two-commit fixture produces validated records and both summaries externally, prints findings and reports advisory-service rows; no real scanner/network call | AC-1, AC-5 |
| T21 | `test_secret_redaction_all_surfaces` | Canned gitleaks JSON contains inert `Match`/`Secret` sentinel text; retain rule/file/line while the sentinel is absent from stdout, stderr and every saved result/raw-cache byte, including failure output | AC-5 |
| T22 | `test_source_only_no_hooks_credentials` | Fixture pip requirements include exact pins, unpinned entries, local paths and repository addresses; only fully pinned files are audited, others degrade/incomplete with a reason; scan flags live in the adapter and cannot enable resolution. Hooks/target profile try writing sentinels and an environment credential is inert; none executes or passes through, source config remains stripped, external copy-path symlinks are not dereferenced and the summary states pip-audit's listed-only scope | AC-3, AC-5, AC-6 |
| T23 | `test_repeated_run_output_refusal` | Scan twice with separate external outputs and once with an occupied output; keep stable finding identities for the two scans and refuse overwrite so old results cannot masquerade as a fresh run | AC-3, AC-7 |
| T24 | `test_skill_entrypoint_registered` | Read skill and descriptor; assert the executable entrypoint, external outputs, statuses and portable skill declaration are discoverable | AC-9 |
| T25 | `test_review_output_unchanged` | Before implementation, capture explicit expected normalized records for a fixture ordinary review and pip-audit's exact review argv using deterministic stubs; after U2, identical invocation/records remain identical, including the preexisting unpinned-version result, with existing review tests unedited | AC-8 |

T01–T24 are expected red at U1 because the command/skill is absent; T25 is an independent **passing control**, bound to the source revision above. Freeze its explicit expected data in the U1 commit rather than generating its oracle from the changed runner after implementation. The run's single code-review pass does not permit hiding failed or blocked scenarios as passed.

## Scenario Smoke

The combined branch runs the declared local/private environment suite and the executable scan scenario before code review.

```scenario-smoke
- name: combined-repository-functional-suite
  command: python3 -m pytest plugins/*/tests -q --import-mode=importlib
  proves: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9]
  runs: environment
- name: scanner-command-and-review-regression
  command: python3 -m pytest plugins/saga/tests/test_security_scan.py plugins/saga/tests/test_review_tools.py -q
  proves: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9]
  runs: environment
```

Also run `python3 -m unittest discover -s tests -v`, `python3 scripts/check_repo.py`, and `git diff --check` on the combined branch. These checks and the smoke are Active implementation evidence, not post-delivery Verify evidence. No unit is independently deployed or independently consumed, so no deployed per-child loop is prescribed.

The Functional Tester runs the checkpoint command in the **local maintainer-machine environment** against a disposable scratch clone of `infiquetra-agent-plugins`. Commit both plants in a scratch-only commit before scratch HEAD, then make HEAD touch neither planted file. The Architect's snapshot/scratch ruling permits these throwaway local commits; never push them or commit the plants/results here or to any maintained branch.

| Plant | Format and location | Required detecting row and maintainer-machine version |
|---|---|---|
| Known-vulnerable Python package version | An exact-pinned entry in `requirements.txt`, with every entry in that file pinned exactly | `pip-audit` 2.10.1, matching its pin; `osv-scanner` 2.6.0, whose resolved pin is `not-recorded`, may also report it |
| GitHub Actions workflow misconfiguration | A workflow under `.github/workflows/` with a planted misconfiguration covered by zizmor | `zizmor` 1.30.1, matching its pin |

The scenario **passes** when pip-audit reports the dependency plant (or osv-scanner reports it), zizmor reports the workflow plant, each required detecting row ran on its resolved pin or with a resolved `not-recorded` pin, and the scratch clone is byte-for-byte unchanged afterward, including complete file/Git state. Unrelated missing or off-pin host rows must still be reported honestly as degraded/skipped: for example, npm 11.19.1 differs from the npm-audit pin 12.0.2 and cdk-nag may be missing or intentionally skipped without opt-in. Such unrelated gaps can make the **overall scan exit `2` incomplete** while this two-plant scenario passes; they are not evidence that the whole scan completed.

If no on-pin/unpinned dependency-detecting row can exercise its required plant, or zizmor cannot run on-pin/unpinned, record the scenario as **blocked** and bring it to the operator under `unfinished_testing_response`. A required detecting row that runs but misses its plant is a failed scenario, never a pass. Retain private local result paths for the operator and only non-sensitive counts/status/commit evidence in the public handoff.

## Applicability declaration

This is the single per-unit declaration; every catalogue lens is named for U1, U2 and U3.

The operator selected the four always-on lenses plus agent-usability and documentation-clarity. Each included lens applies to each unit's contribution to the combined capability, including tests and documentation; all other exclusions below are operator-approved, and no rubric, dimension, anchor or threshold is authored here.

| Lens | U1 | U2 | U3 | Reason |
|---|---|---|---|---|
| architecture-maintainability | applies | applies | applies | Always on; tests, runner boundaries and portable packaging must follow repository architecture |
| correctness | applies | applies | applies | Always on; oracle, runtime and documented behavior must agree |
| security | applies | applies | applies | Always on; fixtures, process/data handling and operator guidance protect this machine |
| testing | applies | applies | applies | Always on; independent failing tests, executable checks and delivery evidence |
| agent-usability | applies | applies | applies | Tests pin agent-facing CLI behavior; runtime and skill make that behavior usable |
| documentation-clarity | applies | applies | applies | Test contract, command summary and usage documentation must be unambiguous |
| deployment-infrastructure | does not apply | does not apply | does not apply | The change adds no deployment |
| api-contract | does not apply | does not apply | does not apply | The change adds no network service or public interface |
| privacy | does not apply | does not apply | does not apply | The change adds no personal data |
| accessibility-human-usability | does not apply | does not apply | does not apply | The change adds no user interface |
| experience | does not apply | does not apply | does not apply | The change adds no user interface |
| reliability | does not apply | does not apply | does not apply | A local operator command, with no service to keep up |
| performance | does not apply | does not apply | does not apply | A local operator command, with no latency target |
| adversarial | does not apply | does not apply | does not apply | Security already covers hostile input to the scanner |
| previous-comments | does not apply | does not apply | does not apply | First review, with no earlier comments to check |

## Run configuration and possible lanes

The Lead owns staffing and dispatch; admission records the approved defaults without changing this crew's external session allocation.

Admission records medium risk with the operator's justification: it changes the runner every code review uses and runs third-party security tools over a whole repository, but touches no production system, secret, or permission. All seven approval-boundary scopes are `none`; destination is `merge`, staffing overrides are `none`, repair allowances are 3 standard/2 escalated, unfinished testing goes to the operator, and change shape is `mixed`. The profile declares local/private testing and directly consumed main; a merge is not authorized by this planning handoff.

Backend recommendation and chosen mode are `inline`. No per-unit model/effort is selected here because the Lead holds external staffing; automatic tier judgments were disabled for admission rather than changing approved staffing. This crew permits one code-review pass; the default repair allowances do not authorize extra passes, self-approval, or reviewer contact by this Planner.

U1 must finish and be integrated before U2. U3 prose can be drafted alongside U2 once the CLI contract is frozen, with disjoint file custody; final examples and validation depend on U2. The Lead determines actual concurrency and integration order; no new sessions or child issues are implied.

## Preflight results and deferred checks

Planning evidence is limited to the observed revision and environment; checks are rerun only when their validity requires it.

| Check | Environment | Observed UTC | Role | Outcome | Validity class | Validity window |
|---|---|---|---|---|---|---|
| Admission and card validation | Mac Studio, security-scan worktree, source `ebc263ed` | 2026-11-15T18:34Z | Planner | Revalidated against final issue context; eight approved answers, no pending questions; shared store used | Time-bound | 24 hours, invalidate on issue/profile change |
| Work branch exists and is not default | Same worktree | 2026-11-15T18:23Z | Planner | `docs/saga-whole-repository-security-scan`, distinct from main | Environment-bound | Until branch/worktree changes |
| Phase 0.6 submission | Issue 321 via Saga reconcile/Mission Control | 2026-11-15T18:20Z | Planner | `written`, field `Stage+Status`, Planning/Designing | Time-bound | Until another lifecycle event changes the card; re-read before relying on it |
| Empty-base comparison seam | Disposable local fixtures, source `ebc263ed` | 2026-11-15T18:23Z | Planner | One retained finding for line probe and each of six base/head invocations; stub process/parsers | Environment-bound | This source/runner revision; rerun permanent tests on implementation |
| Repository validation | Mac Studio, plan worktree | 2026-11-15T18:34Z | Planner | Baseline and authored plan files passed; diff whitespace check passed | Environment-bound | Until relevant files change |
| Unchanged review-runner regression suite | Mac Studio, source `ebc263ed` | 2026-11-15T18:28Z | Planner | 127 passed in 44.94 seconds, no test edited | Environment-bound | Until runner/dependency/host changes |

| Deferred check | Later step | Responsible role | Required evidence |
|---|---|---|---|
| Plan cleared doc-review with nothing above P3 open | Track A step 2, before U1 | Plan Reviewer, routed by Lead | Independent result at the exact plan revision; Planner does not self-review |
| Exact independent red suite and passing T25 control | U1, before U2 | `test-writer-1` | Test-only branch/commit, collection and finite expected failures |
| Final changed-code functional suite and safety tests | U2/U3 combined branch, before code review | Initial implementation worker | Runtime/packaging checks and declared environment suite pass |
| Real planted-flaw scenario and per-tool bounds | Combined functional run, then delivered version verification | Functional Tester | Both required detections, target unchanged, versions/gaps/timeouts reported; blocked prerequisites go to operator |
| Final source/artifact exists in consumption context | After separately authorized merge/delivery | Release Worker and Functional Tester | Delivered commit and actual consumable command/skill; no deployment is fabricated |

Stable run constraints are the operator's one-pass review rule and scope boundaries in this plan. Time-bound preflights expire rather than silently becoming current; a tool installed or pinned differently later is checked by the role about to use it.

## Scope Boundaries

This is private operator tooling maintained in a public repository, with tests protecting intended behavior, this machine, its credentials and its data.

Non-goals are review-output changes; history or uncommitted-file scanning; new scanners, dependencies or pins; packaging any third-party audit skill; automatically passing results to reasoning agents; findings uploads or issue filing; and installing a schedule. Do not add broad public-release infrastructure, a new sandbox service, audit orchestration or a second catalogue.

The implementation boundary is `plugins/saga/`, `ports/saga.json` and `docs/engineering-journal/`. The dispatch additionally authorizes this plan and the three existing filing documents under `docs/`; that planning exception does not expand runtime implementation scope. Shared gitignored Saga state is permitted; tracked main-checkout files and installed plugin copies are not edited.

Stop through the Lead for an Architect ruling if an existing review test/output must change, the scan cannot stay on a disposable copy, a new dependency/tool/pin or additional network capability is needed, target code would execute by default, repository validation would require a rule change, or implementation must leave the stated boundary. Bring scope changes involving history, results uploads, issue filing or external transmission of findings to the operator.

Deferred to Follow-Up Work: schedules, additional scanner rows and history auditing remain separate work only when requested; this plan creates no follow-up commitment or issue. No unresolved behavior may be hidden by marking an incomplete row clean.

## Planner handoff index

The issue comment binds these contract fields to this plan's commit, with the checklist maintained by the Delivery Manager.

| Required field | Artifact section |
|---|---|
| `work_units` | Implementation Units, including file custody, dependency order, assignment and checks |
| `possible_lanes` | Run configuration and possible lanes |
| `applicability_declaration` | Applicability declaration |
| `testing_expectations` | Finite independent test inventory and Scenario Smoke |
| `child_scoped_checks` | Each unit's functional-checks block, naming AC-IDs |
| `preflight_results` | Preflight results and deferred checks, seven columns per observation |
| `deferred_checks` | Deferred table, with later step and responsible role |
| `work_unit_checklist` | Issue handoff checklist for U1, U2, U3 |

Initial planning stops before Saga Phase 5.4 for independent plan review. In the Lead-dispatched plan-repair pass, answer the recorded findings, refresh functional checks, require `plan_review.py check` to exit `0`, and submit the authorized Phase 5.5 Ready for Active move through Saga/Mission Control; no second plan review is prescribed. Stop before Phase 5.6 (`/work`): the Lead merges the plan PR and dispatches the independent U1 test writer before implementation.
