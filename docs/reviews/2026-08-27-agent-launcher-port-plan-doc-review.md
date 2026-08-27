---
date: 2026-08-27
kind: doc-review
target: docs/plans/2026-08-27-agent-launcher-port-plan.md
reviewed_revision: ae9ce84849dcf4d4d216049454718753cfdf00c1
branch: port/agent-launcher
classification: issue-derived implementation plan
blocked: true
cycles: 1
---

# Doc Review — Agent-launcher port plan

The plan is blocked: R6, KTD10, and U4 promise one lifetime matrix run, which contradicts R11's runbook and the repository's per-round evidence loop.

## Applied fixes

No plan or code edits were applied. The brief required review-only mode, so every actionable item is recorded below.

## Readiness summary

This plan cannot safely drive `/work` until D1 is repaired. An implementer who freezes, captures the matrix once, then accepts a Code Review repair that moves `plugins/agent-launcher/` would either keep a stale fingerprint (the runbook anti-pattern) or invent a rerun the plan forbids.

| review-result field | value |
| --- | --- |
| target path | `docs/plans/2026-08-27-agent-launcher-port-plan.md` |
| reviewed repository revision | `ae9ce84849dcf4d4d216049454718753cfdf00c1` (branch HEAD; `git rev-parse HEAD` matched the brief) |
| origin contract | [infiquetra/infiquetra-agent-plugins#22](https://github.com/infiquetra/infiquetra-agent-plugins/issues/22) |
| classification | issue-derived implementation plan; issue-phase rubrics applied |
| rubric phase | issue (three cores; three extras applied by judgment) |
| blocked | yes |
| finding counts | P0: 0; P1: 1 open; P2: 6 open; P3: 4 open |
| applied fixes | none |
| override rationale | none |
| review artifact | `docs/reviews/2026-08-27-agent-launcher-port-plan-doc-review.md` |
| linked issue / plan | #22; reviewed plan at `ae9ce84` |

The core port shape is faithful. Schema version 3, relocate-claude-manifest, SKILL/README supersession, and dropping `tests/test_launcher_contract.py` all match the current descriptor authority and the mission-control drop of `tests/test_prompt_alignment.py`. The start gate is real: infiquetra-claude-plugins#777 is CLOSED (2026-08-25T13:32:07Z). Upstream `origin/main` is `8269f84b`; the six listed paths are exact; only the test file moved after `28a881b3` (`844c133b`, `0d019597`, `48a15f05`). This repository's `origin/main` is `f981ed4`. Merge policy is squash and rebase, no merge commits. There is no `pyproject.toml`. The marketplace exists and lists only `voice`.

`launcher.py` is stdlib-only, 1387 numbered lines, vendor-gated for Claude account checks, and `VENDOR_FLAGS` names exactly the seven vendors U2 cites. `--help` is argparse-only. `CLAUDE_PERSONAL_PROJECTS` / `CLAUDE_COMPANY_PROJECTS` are transcript roots. The issue comment records the corrected CI check set in place of `uv run pytest`.

## Formal issue-rubric results

The issue-phase rubric review blocks on an acceptance contradiction, not on missing structure.

Cores applied: `acceptance_criteria_clarity`, `devils_advocate_issue`, `spec_fidelity`. Extras applied by judgment: `context_completeness` (non-trivial repo, named files required), `issue_sizing` (five units, descriptor plus package plus tests plus evidence plus metadata), `prerequisite_mapping` (start gate, runbook, two existing ports).

| rubric | result | evidence |
| --- | --- | --- |
| Acceptance criteria clarity | BLOCK | D1: R6/KTD10/U4 require one lifetime matrix run; R11 requires runbook v1.1.0, which re-runs fingerprint-bound evidence after a repair that moves the tree. |
| Devil's advocate | REVISE | The slice is the smallest useful port; D6 is leftover portable-test coverage, not extra product scope. |
| Specification fidelity | REVISE | Issue #22 constraints are inherited. D1 loses the runbook evidence-loop constraint that R11 claims to carry. D2 leaves a runbook entry criterion unmapped. |
| Context completeness | REVISE | Paths and tools are named. D4, D5, and D7 leave an implementer to invent sync order, a pytest invocation, or the wrong assess-clients precedent. |
| Issue sizing | PASS | Five serial units and one squash-merged PR match a single-issue inline port. |
| Prerequisite mapping | REVISE | #777 is closed and evidenced. D2 does not schedule or waive "upstream suite green at the pin." |

Rubric findings are the D-series below. They are not reclassified as a separate readiness list.

## Remaining findings by priority

Finding IDs are this review's, sorted by priority, then source anchor, then title. Priorities use Saga's P0–P3 scale. Every open finding is actionable.

| id | priority | status | anchor (at `ae9ce84`) | class | summary |
| --- | --- | --- | --- | --- | --- |
| D1 | P1 | open | R6 / KTD10 / U4 | issue rubric: acceptance criteria | One lifetime matrix run cannot coexist with the runbook's per-round evidence loop. |
| D2 | P2 | open | R11 / Grounded evidence | issue rubric: prerequisites | Runbook entry criterion "upstream suite green at the pin" is neither run nor waived. |
| D3 | P2 | open | Implementation Units | plan-sections / requirement mapping | Units do not own R-IDs, so R1–R11 have no exact-once mapping. |
| D4 | P2 | open | U1 Mechanism | readiness: completeness | The stated sync-then-`--check` sequence fails once target-owned files exist unless they were present at the writing sync. |
| D5 | P2 | open | U1 Verification | readiness: verification | `pytest plugins/agent-launcher/tests` does not "collect nothing" when that directory is absent. |
| D6 | P2 | open | U2 Files | issue rubric: acceptance criteria | The adapted-subset list omits portable-relevant upstream tests. |
| D7 | P2 | open | U3 Files | readiness: verification | The cited mission-control assess-clients test is the blocked-in-advance case, not the not-blocked case. |
| D8 | P3 | open | Requirements | plan-sections polish | R-IDs are bold prefixes; the plan contract wants a plain `R1.` prefix. |
| D9 | P3 | open | KTD4 | readiness: factual clarity | "Never an earlier revision" is not in `ports/README.md`. |
| D10 | P3 | open | U1 Mechanism | plan-sections polish | The source checkout is an absolute machine path. |
| D11 | P3 | open | KTD9 / U5 | readiness: factual clarity | Phase-boundary board Status and a single merge comment are left to fight. |

### D1. Promise one current matrix, not one lifetime run

R6, KTD10, and U4 would keep a stale fingerprint after an accepted repair.

Plan lines 94–97, 198–202, and 321–333 say the matrix "runs once," evidence is "run-once," and assess-clients `--execute` is "one run." R11 (lines 116–117) makes runbook v1.1.0 phases and stop conditions this run's contract. That runbook's Phase 3 and anti-patterns require one current fingerprint-bound record, a rerun when the tree moves, and preservation of the superseded record. The journal decision on round bounds re-runs fingerprint-bound evidence once per review round, with a three-round cap.

Following the plan literally after a Code Review repair that changes `plugins/agent-launcher/` either commits a matrix whose `tree_sha256` no longer identifies the shipped tree, or invents a rerun the "exactly once" language forbids. U5's metadata edits do not move the package fingerprint; a package-byte repair does.

Required disposition: rewrite R6, KTD10, and U4 to promise one current committed matrix bound to `(file_count, tree_sha256)`. After an accepted repair that moves that pair, freeze the successor, rerun only evidence whose binding moved, keep the superseded document with its reason, and stay inside the three-round cap. Name the installed `/code-review` controller as Phase 4.

`external_opinion`: state `recommended`; requester `claude` (engine_offer default for judgment doc-review: opus / high); reason: this is the blocking acceptance contradiction. Report-only: not dispatched.

### D2. Schedule or waive the upstream suite at the pin

R11 claims the runbook is followed, but the first entry checkbox is never executed.

Runbook v1.1.0 entry criteria require the upstream plugin at a pinned commit with its own suite green there before porting begins. The plan verifies file identity and the three post-release test-only commits, then drops that suite. It never runs the suite at `8269f84b` (or at the later sync pin) and never records a waiver.

An implementer who treats R11 as load-bearing stops before U1 with no named disposable-clone procedure. An implementer who treats the plan's silence as a waiver starts without the runbook's source-health gate. Those are different runs.

Required disposition: either add a U1 entry step that exports the pin to a disposable scratch clone, runs the upstream suite there, and confines caches to scratch while the authoritative checkout stays at `origin/main` with a before/after status record; or waive that entry line in the plan with the reason that the five carried files are unchanged since `28a881b3` and the suite is `dropped_from_source`.

### D3. Give each unit exact-once R-ID ownership

The plan-sections contract requires a Requirements field on every unit. These units do not have one.

R1–R11 are listed once at the top. U1–U5 name files and commands but not which R-IDs they close. `/work` and later Code Review then invent the mapping, which is how ownership overlaps or a closeout requirement is left for "someone."

Required disposition: add a **Requirements** line on each unit. The mapping already implied by the prose is U1: R2, R3; U2: R4; U3: R7; U4: R6; U5: R8, R10, R11; R1 already evidenced; R5 and R9 run-wide. Also add the other required per-unit fields the plan skill names (Goal, Dependencies, Approach, Patterns to follow) so the unit headings match the contract this repository's `/plan` emits.

### D4. Write target-owned files before the writing sync

`--check` rebuilds the expected `PROVENANCE.json` from the files on disk and writes nothing.

U1 Mechanism (lines 245–248) is: sync, then `--check`, then `check_repo.py`. `scripts/sync_vendor_source.py` discovers target-owned paths at write time and at check time. If README, SKILL.md, portable `plugin.json`, and `.gitignore` are written after the only writing sync, `--check` reports a provenance mismatch and `check_repo.py`'s closed-set check fails for the opposite order.

Required disposition: state the order as write `ports/agent-launcher.json` and the target-owned core surface, run sync so `PROVENANCE.json` records those paths, then `--check`, then `check_repo.py`. A sync, write, re-sync, `--check` sequence is also honest. Do not leave "sync then `--check`" as the only ordered procedure.

### D5. Drop the U1 package-pytest line

`python3 -m pytest plugins/agent-launcher/tests` is not a no-op when that directory is missing.

U1 Verification (lines 256–259) says that command "collects nothing yet (no tests dir)" and that CI's glob tolerates it. The CI job runs `python -m pytest plugins/*/tests`, which simply omits a package with no `tests/` directory (fleet-core has none). The named U1 command is a concrete path: pytest exits non-zero when the path does not exist. Creating an empty directory to satisfy the sentence yields pytest's no-tests-collected exit.

Required disposition: remove the package pytest command from U1 verification. Say that CI's glob omits a missing `tests/` directory, and that `python3 -m pytest plugins/agent-launcher/tests` is a U2 gate.

### D6. Name the remaining portable upstream tests in U2

U2's adapted-subset list is almost the portable half, not all of it.

Upstream `tests/test_launcher_contract.py` at `8269f84b` has portable cases the plan does not list: `test_cwd_mismatch_on_preexisting_tab_does_not_close` (cwd mismatch must not close a tab this process does not own), `test_ownership_is_tab_id_not_in_prelaunch_snapshot` (the ownership definition), and `test_skill_cleanup_example_redirects_receipt` (`> receipt.json`; the form `close --tab-id <tab_id> --receipt-json <receipt.json>` is forbidden). The Orchestrate-ingestion and marketplace-dependency tests are correctly dropped.

Required disposition: add those three names to U2's file and test-scenario lists, resolved from `Path(__file__).resolve().parents[1]`. Keep citing upstream test names in the module docstring.

### D7. Cite the UniFi not-blocked assess-clients test

U3 points at the mission-control test that proves the opposite geometry.

Lines 305–308 want a shape test that skill-scoped clients are not blocked because the entrypoint sits inside `skills/agent-launcher`. The cited range `tests/test_assess_clients.py:1421-1544` starts with `test_skill_scoped_plan_with_package_root_entrypoints_blocks_invocation_in_advance`, which loads mission-control and asserts OpenCode, Gemini CLI, Muse, and Hermes are blocked because those entrypoints sit at `scripts/`. The not-blocked case is `test_skill_scoped_plan_with_all_deliverable_entrypoints_is_not_blocked` at line 1449, against UniFi.

An implementer who copies 1421 will assert blocked and then either fail the test or move `launcher.py` out of the skill unit, which is the defect KTD5 exists to prevent.

Required disposition: cite line 1449 (UniFi, not blocked). Use 1421 only as the negative control that agent-launcher must not resemble.

### D8. Use plain R-ID prefixes

Plan-sections require `R1.` as a plain prefix, not a bold label.

Lines 73–117 emit `**R1.**` through `**R11.**`. That is polish; IDs stay stable.

Required disposition: write `R1.` through `R11.` without bold on the ID token.

### D9. Cite the sync tool, not `ports/README.md`, for the pin rule

KTD4's "never an earlier revision" pointer is wrong.

Line 157 cites `ports/README.md`. That file defines descriptor fields and does not contain that rule. The words are the `--commit` help in `scripts/sync_vendor_source.py` ("the corrected revision, never an earlier one"). UniFi provenance notes say the same thing for that package only.

Required disposition: retarget the citation. The pin policy itself (current `origin/main` HEAD at sync time, SHA in `PROVENANCE.json`) stays.

### D10. Do not freeze a machine-local absolute source path

Plan-sections forbid absolute paths in plan content.

U1 Mechanism line 246 hard-codes `/Users/jefcox/workspace/infiquetra/infiquetra-claude-plugins`. That path is this machine's checkout; it breaks in a worktree or on another host, and `sync_vendor_source.py` already takes `--source`.

Required disposition: write `--source <infiquetra-claude-plugins checkout>` and keep the cleanliness check.

### D11. Separate board Status moves from the closeout comment

KTD9 and U5 describe two different cadences as if they were one.

KTD9 (lines 193–196) moves board Status at each real phase boundary. U5 Verification (lines 373–375) posts "a single status comment when the PR merges, not per-step chatter."

Required disposition: say the project Status field may move at phase boundaries, and the GitHub issue comment is one closeout comment on merge.

## Invalid candidates

These were checked and rejected. They are not findings.

| id | candidate | reason invalid |
| --- | --- | --- |
| N1 | Schema version 3 is a mismatch | `scripts/port_config.py` `SCHEMA_VERSION` is `"3"`; both existing descriptors use it. |
| N2 | `PROVENANCE.json` field `removed_from_source` is a typo | Descriptor custody uses `dropped_from_source`; generated provenance uses `removed_from_source`. U3 uses both correctly. |
| N3 | The marketplace does not exist, so KTD7 is ungrounded | `.claude-plugin/marketplace.json` exists and lists only `voice`. The mission-control absence test already allows that shape. `QUEUED.md` P1 still withholds widening distribution. |
| N4 | Pin `28a881b3` instead of `origin/main` HEAD | The five carried files are unchanged; the sync tool's rule is the corrected revision, not an earlier one. |
| N5 | Remapping `uv run pytest` is a spec violation | The 2026-08-27 issue comment records the corrected CI commands. This repository has no `pyproject.toml`. |
| N6 | SKILL.md must use `normalize-skill-frontmatter` | Upstream frontmatter is already `name` + `description`. The Claude defect is the body cache ladder, which supersession is the honest class for. |
| N7 | Hermes is an eighth contract vendor | `VENDOR_FLAGS` has seven keys. Hermes is a skill-scoped client, not a launcher vendor. |
| N8 | `launcher.py --help` launches a session | Subparsers are required; `--help` is answered by argparse. `test_client_entrypoints.py` will run that path once U1 lands `PROVENANCE.json`. |

## Engine offer

Report-only. `engine_offer.py offer --stage doc-review --attended` returned `intent=second-opinion`, `model=opus`, `effort=high`, `prompt_required=true`, reason "doc-review unit classified judgment."

The brief forbids substitute reviewers and dispatch. No panel was launched. D1 carries `external_opinion.state=recommended` for an advisory second opinion if the operator names it.

`/founder-review` is not recommended. Product scope is locked by #22.

## Review artifact path

This blocked review is recorded at `docs/reviews/2026-08-27-agent-launcher-port-plan-doc-review.md`.

## Residual risk from limited evidence

The review used the live #22 body and its 2026-08-27 evidence comment, the committed target at `ae9ce84`, `origin/main` at `f981ed4`, and the local upstream checkout at `8269f84b` (clean tracked tree). It did not re-run the 755 / 551 recorded baseline suites, did not execute `assess_clients.py --execute`, and did not mutate either repository.

Issue #22's body still lists `uv run pytest` as an acceptance criterion. The plan and the evidence comment supersede that for this run. A reviewer who reads only the issue body can still fail the shipping PR for the wrong check set; repairing the issue body is outside this review-only pass.
