# Mission-control migration run-plan document review

This Agent Plugins repository cannot safely execute the mission-control migration plan yet because five Priority 1 (P1) findings leave incompatible acceptance paths or an unowned source-custody change.

## Applied fixes

No plan fixes were applied. The operator requested one broad review artifact, so the reviewed plan remains unchanged and every actionable item is recorded below.

## Readiness summary

The plan is blocked until findings F1 through F5 are resolved and the two unnecessary additions in F6 and F7 are removed.

| review-result field | value |
| --- | --- |
| target path | `docs/plans/2026-08-24-mission-control-port-run-plan.md` |
| reviewed repository revision | `4d0a414eec8b08e5e61c44356113326309de950e` (the plan itself was added by `fe1f715fe4ea267efb615672b979045c6f0dfe08`) |
| origin contract | [parent issue infiquetra/infiquetra-agent-plugins#9](https://github.com/infiquetra/infiquetra-agent-plugins/issues/9) and child issues [#10](https://github.com/infiquetra/infiquetra-agent-plugins/issues/10) through [#19](https://github.com/infiquetra/infiquetra-agent-plugins/issues/19) |
| classification | issue-derived implementation plan; issue-phase rubrics applied |
| blocked | yes |
| finding counts | P0: 0; P1: 5 open; P2: 2 open; P3: 1 open |
| applied fixes | none |
| override rationale | none |
| review artifact | `docs/reviews/2026-08-24-mission-control-port-run-plan-doc-review.md` |

The core execution shape is faithful. The parent issue's dependency graph and landing order are reproduced at plan lines 53–58 and 644–662; the pinned source commit `84eaf042f0e350005f7eddf8e7d80da25c12119d` exists locally, and its `plugins/mission-control` tree still matches the current upstream checkout's tree; the Fleet Core blob comparisons at commits `3b5faa6c` and `84eaf042` confirm that `intent_envelope.py` and `tier_palette.py` match while `retry_backoff.py` differs. The upstream-repairs-go-upstream rule is preserved at plan lines 45–61 and 668–678.

All ten implementation units U0 through U9 contain the required smallest viable change, reused mechanism, new moving parts, rejected alternative, test scenarios, and verification record. The plan also carries Grok 4.6 at extra-high reasoning, one Saga Code Review process for each unit's frozen revision, a separate frozen integration review, typed consensus outcomes, and the three-cycle cap at lines 67–72 and 200–203.

## Formal issue-rubric results

The issue-phase rubric review blocks on acceptance contradictions and missing ownership, not on prose quality.

| rubric | result | evidence |
| --- | --- | --- |
| Acceptance criteria clarity | BLOCK | F3 and F4 give two incompatible ways to satisfy child issue #18. |
| Devil's advocate | REVISE | F6 and F7 add work that no current acceptance criterion needs. |
| Specification fidelity | BLOCK | F1 contradicts the repository's descriptor-version authority; F2 and F4 relax child contracts. |
| Context completeness | BLOCK | F5 does not define how to test the pinned revision without changing the authoritative checkout. |
| Issue sizing | REVISE | F2 leaks a custody redesign into the test-and-continuous-integration unit; F7 adds unrelated documentation churn to closeout. |
| Prerequisite mapping | BLOCK | F2 discovers a possible Lane A custody change only after Lane A has merged and been reviewed. |

## Remaining findings by priority

Every open finding is actionable; the table is the gate summary and the numbered sections carry the evidence and required disposition. Priorities use Saga's Priority 0 through Priority 3 (P0–P3) scale.

| finding | priority | status | class | summary |
| --- | --- | --- | --- | --- |
| F1 | P1 | open | issue rubric: specification fidelity | The plan adds a port-descriptor field while retaining schema version 2, contrary to the format authority. |
| F2 | P1 | open | issue rubrics: context and prerequisites | Unit U6 may change source custody after the synchronization unit has merged, but U6 owns neither the descriptor nor resynchronization. |
| F3 | P1 | open | issue rubric: acceptance criteria | The plan permits exactly one assessment run while child issue #18 requires a fresh evidence run after an accepted integration-review repair. |
| F4 | P1 | open question | issue rubrics: acceptance criteria and fidelity | The plan replaces child issue #18's operator-authored matrix reasons with worker-authored reasons without contract authority. |
| F5 | P1 | open | readiness: verification and custody | The plan does not define a non-mutating way to run the upstream suite at the pinned commit. |
| F6 | P2 | open | issue rubric: devil's advocate | The proposed continuous-integration path-agreement meta-check duplicates the chosen wildcard and has no remaining acceptance need. |
| F7 | P2 | open | issue rubric: devil's advocate | The optional architecture-brief edit is part of no closeout acceptance criterion. |
| F8 | P3 | open | readiness: factual clarity | The plan says the skill format permits seven frontmatter fields; the repository authority permits six. |

### F1. Use a new descriptor schema version for the new rule-selection field

The plan's Key Technical Decision 2 (KTD2) would give two incompatible descriptor shapes the same version number.

Plan lines 128–141 and 344–351 add a required per-path transform-rule name while keeping `schema_version` at `"2"`. The local format authority says the version is bumped when a field is added, removed, or reinterpreted (`scripts/port_config.py:54–63`), and its loader refuses any version other than the one it understands (`scripts/port_config.py:360–364`). The cited additive compatibility-matrix precedent governs a different document and does not override the port-descriptor rule.

This crosses the filesystem-custody boundary because the descriptor selects which transform rewrites each managed path. A schema-2 reader either rejects the new closed-object field or assigns the old meaning to a document that now drives different writes.

Required disposition: take schema version 3, because the repository authority makes that the defensible choice from the known alternatives. Update `scripts/port_config.py`, `ports/README.md`, every existing descriptor, and the derived tests in the same unit; do not preserve version 2 by analogy to an unrelated matrix format.

### F2. Move the prompt-alignment custody decision before synchronization

The plan allows the test-and-continuous-integration unit to make a descriptor-level custody decision after the synchronization unit has merged and been reviewed.

Plan lines 471–485 say unit U6 may drop `test_prompt_alignment.py` from source if its premises fail, and lines 706–710 make the U6 review the approval surface. However, the plan's ownership table at lines 655–662 gives `ports/mission-control.json` only to U1 and U3; U6 owns the continuous-integration workflow and root tests. U6 runs after U3, U4, and U5, so changing a test's custody then also requires regenerating `PROVENANCE.json`, rerunning synchronization, and invalidating the earlier U3 review.

This is a concrete filesystem-custody failure: following the plan literally either edits an unowned descriptor or leaves a byte-copied test whose premise is false. The parent issue's run-level stop condition already says a unit must stop when its acceptance criteria require work outside its owned surface.

Required disposition: verify the prompt-alignment premise during U1 entry criteria and finalize its custody in U1/U3 before synchronization. If the failure is first discovered in U6, stop U6 and return the change through the custody owner, resynchronization, affected verification, and a new frozen review; a U6 reviewer cannot approve an out-of-scope custody edit.

### F3. Define the evidence loop after an integration-review repair

The plan's one-run promise cannot coexist with the child's required repair loop.

Plan lines 565–586 say the complete Phase 3 sequence runs exactly once and promises one matrix run. Child issue [#18](https://github.com/infiquetra/infiquetra-agent-plugins/issues/18), under “Stop conditions,” instead requires one evidence rerun per review cycle after confirmed integration-review repairs. The runbook agrees: it says to batch repairs, rerun moved evidence, and preserve the superseded record with its reason (`docs/runbooks/portable-plugin-port.md:183–186`).

This is a concrete filesystem-custody and reliability failure. A review repair can change the package fingerprint or a mutation-proof-bound blob; merging with the old evidence violates the fingerprint gate, while creating a replacement violates the plan's “exactly once” instruction.

Required disposition: promise one current committed matrix, not one lifetime execution. Specify the loop as verify, freeze, capture evidence, review; after an accepted repair, verify again, freeze the successor revision, rerun only evidence whose binding moved, preserve the superseded record, and continue within the same three-cycle review cap.

### F4. Resolve who must author the matrix reasons

The plan silently changes an acceptance criterion whose two source issues disagree.

Child issue [#18](https://github.com/infiquetra/infiquetra-agent-plugins/issues/18) requires “operator-filled” reasons for every client status. Parent issue [#9](https://github.com/infiquetra/infiquetra-agent-plugins/issues/9), in its inputs inventory, says U8 requires no operator input. Plan lines 696–705 choose worker-authored reasons followed by operator review, but this is an unattended run and neither the matrix checker nor the Grok integration review can prove operator authorship.

The real question for the operator is: does “operator-filled” mean that the operator must author or explicitly approve every reason before U8 commits the matrix, or may the worker derive the reasons from stage evidence and rely on the normal integration review? This is not one of the unattended known-set choices, so the plan must not guess.

Required disposition: amend child issue #18 or the parent contract with the selected authorship rule, then make the plan and acceptance evidence match it. Until then, U8 has no unambiguous pass condition.

### F5. Run the pinned upstream suite from disposable bytes, not the authoritative checkout

The plan requires both exact-pin test evidence and zero upstream edits but does not say how to achieve both.

Plan lines 45–48 and 94–97 require the upstream checkout to remain unchanged; U1 at lines 253–260 and U8 at lines 565–569 require the upstream suite at commit `84eaf042f0e350005f7eddf8e7d80da25c12119d`. The current local upstream checkout is at `d82895133886e8843c8cf888eada3fed036ecb7e`, not the pin, and contains pre-existing untracked and ignored state. Its pytest configuration writes coverage data and a cache by default (`../infiquetra-claude-plugins/pyproject.toml:83–85`), so running in place is not read-only; checking out the pin in place also changes authoritative Git state.

This crosses both the subprocess/Git-execution boundary and the filesystem-custody boundary. An implementer can otherwise test the wrong revision, disturb the upstream checkout, or report a clean tracked diff while ignored test artifacts were written.

Required disposition: name a disposable scratch clone or export created from the local repository by a read-only Git operation, check out the full pinned commit there, and run the upstream suite with every cache and coverage output confined to scratch. Record the source checkout's revision and status before and after; do not use an in-place checkout, worktree registration, or pytest run as the proof.

### F6. Remove the continuous-integration path-agreement meta-check

The selected wildcard already removes the path list that the proposed meta-check would compare.

Child issue [#16](https://github.com/infiquetra/infiquetra-agent-plugins/issues/16) asks for a meta-check only if existing behavior does not already imply agreement. Plan lines 152–159 and 471–493 choose `plugins/*/tests`, which expands every current package test directory without per-package enumeration, and still mandate a second path-agreement test. No acceptance criterion requires a separate checker once the job executes both the root `tests` directory and that wildcard and the unit runs `plugins/mission-control/tests` directly.

Required disposition: keep the wildcard and the direct package-suite acceptance command, remove the extra meta-check from Key Technical Decision 4 (KTD4) and U6, and delete its premature journal claim. Add machinery only if a concrete shell-expansion or collection failure remains after the final command shape is written.

### F7. Remove the optional architecture-brief edit from U9

The closeout unit includes documentation churn that no current acceptance criterion needs.

Plan lines 612–622 include an optional dated pointer in `docs/cross-vendor-plugin-architecture-brief.md`. Child issue [#19](https://github.com/infiquetra/infiquetra-agent-plugins/issues/19) does not require that pointer in any acceptance criterion, and both the child and plan say architecture-brief adoption decisions remain out of scope.

Required disposition: remove the architecture-brief path and optional edit from U9. The matrix, readback, provenance, root README, `llms.txt`, required index, journal, upstream filings, and parent closeout comment already satisfy the closeout contract.

### F8. Correct the frontmatter field count

The proposed metadata placement is permitted, but the stated count is wrong.

Plan line 145 says `metadata` is one of seven permitted fields. `scripts/check_repo.py:121–130` defines exactly six: `name`, `description`, `license`, `compatibility`, `metadata`, and `allowed-tools`.

Required disposition: change “seven” to “six” in the plan and the plan-created decision entry at `docs/engineering-journal/DECISIONS.md:28–29`; the transform choice itself does not change.

## Review artifact path

This blocked review is recorded at `docs/reviews/2026-08-24-mission-control-port-run-plan-doc-review.md`.

## Residual risk from limited evidence

The review used the live GitHub issue bodies and the parent issue's opening preflight comment, the committed target repository, and the local upstream Git objects. It did not run implementation tests or mutate either repository because this was a plan-readiness review; repository checks can validate this Markdown artifact but cannot close the contract findings above.
