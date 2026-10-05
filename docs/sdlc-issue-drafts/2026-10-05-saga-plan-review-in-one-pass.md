---
title: saga: plan review in one pass
repo: infiquetra-agent-plugins
type: enhancement
team: asgard
project: operations
labels: enhancement, needs-plan
risk: medium
handoff_maturity: requirements-ready
stage: Shaping
status: Discovering
approval_state: approved
---

# saga: plan review in one pass

### Objective

`/plan` §5.4 dispatches one plan reviewer for one pass, and the reviewer no longer edits the plan.
Its findings become finding records (C1), as standalone `/doc-review`'s do. The author answers every
finding, fixed or rejected with a reason; a script stops the run while any is unanswered or the
acceptance-criteria mapping fails, and lists rejections without holding the run on them. The repair
loop, its allowance and the one-word override are gone.

### Intent

Today on origin/main (1f7137d), paths under `plugins/saga/`:

- `/plan` §5.4 (`skills/plan/SKILL.md:730-787`) dispatches the plan reviewer, repairs the plan and
  dispatches again until no priority P0 or P1 finding remains, the operator overrides in one word,
  or the allowances (3 plus 2) run out (`:772-784`). The session writes `review_cycles` by hand, and
  a finding on a revision since changed needs a re-dispatch (`:786-787`).
- `/doc-review` describes the same loop (`skills/doc-review/SKILL.md:279-309`), reports findings as
  P0 to P3 (`:222-234`) and applies "safe" fixes in place (`:196-220`).
- `/work`'s doc-review gate blocks on an open P0 or P1 unless the operator overrides in one word
  (`skills/work/SKILL.md:235-259`). The override and the safe fixes reach the issue's progress
  comment through `scripts/issue_progress.py` (`skills/work/SKILL.md:670-702`).
- The plan reviewer writes findings "in the shared finding schema the lens catalogue defines"
  (`plugins/agent-launcher/roles/plan-reviewer.md:120-121`), as the lifecycle's plan-review result
  requires (vendored in `plugins/agent-launcher/roles/lifecycle-snapshot.json`).
- The acceptance-criteria mapping check is already a script (`scripts/functional_checks.py map`,
  `skills/doc-review/SKILL.md:119-144`).

What changes (plan.md, Change 8, "Plan review"):

- One reviewer (the plan reviewer, Opus at high effort, as today), one pass: no second dispatch,
  no allowance. The reviewer reports and never edits the plan in place. `/doc-review`'s cross-family
  reviewer seat and second-opinion step (`skills/doc-review/SKILL.md:146-195`) go with the loop.
- Findings are C1 finding records. A plan finding's location names a plan section instead of a
  file and line, as C1 allows. Standalone `/doc-review` on requirements, strategy and issue
  documents also reports finding records, in place of P0 to P3.
- A new script stores the findings in the run record and records the author's answer to each.
  **Fixed** names the plan section changed and is accepted only if the plan changed since the
  review. **Rejected** needs a reason. Its check exits non-zero while any finding is unanswered or
  the mapping fails, and `/work`'s doc-review gate runs it instead of looking for an open P0 or P1.
- Rejections are not a gate. The check prints each with its reason, and they are listed for the
  operator in the issue's progress comment and on the next attended screen.
- The one-word override goes, because nothing stays open after the pass. The mapping check stays
  and keeps blocking: a gap clears only by editing the plan until `functional_checks.py map`
  passes, never by a rejection.
- No TypeSafe Jev re-ranking of plan findings (it failed that test on a past plan review).
- Each plan review is posted to Langfuse as a trace through C15's client once C15 has landed.

Depends on C1 (saga: review records, validation and the A–F formula) and X1a (Record saga's new
review model and its contracts in the lifecycle repository), which makes saga's finding record the
plan-review result's finding format. It posts traces once C15 (fleet-core + saga: Langfuse review
traces and outcomes at merge) lands, and does not wait for it.

### Risk

medium
It changes the gate between planning and building for every run, and that gate must stay hard.

### Out-of-scope / non-goals

- Code review (C10a, C10b) and the A–F grades, which plan review does not use.
- The Langfuse client, the trace's shape and its posting rules (C15); the lifecycle's wording (X1a).
- The rubric review for blueprints, issues and specifications (`scripts/lifecycle_review.py`).
- Who staffs the plan reviewer: unchanged (the run record, then agent-launcher, then this session).

### Files expected to change

- `plugins/saga/scripts/plan_review.py` (new)
- `plugins/saga/scripts/issue_progress.py`
- `plugins/saga/skills/plan/SKILL.md`
- `plugins/saga/skills/doc-review/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/skills/work/references/test-and-gates.md`
- `plugins/saga/com.infiquetra.claude/commands/doc-review.md`
- `plugins/saga/docs/commands.md`
- `plugins/saga/references/run-record.md`
- `plugins/agent-launcher/roles/plan-reviewer.md`
- `plugins/agent-launcher/roles/{issue-reviewer.md,planner.md}` (finding-format wording, after X1a)
- `plugins/agent-launcher/roles/lifecycle-snapshot.json`
- `plugins/saga/CHANGELOG.md`
- `plugins/agent-launcher/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_plan_review.py` (new), no network: findings located by plan section pass
  C1's validator; the check names each unanswered finding and exits non-zero; a rejection without a
  reason, or "fixed" on an unchanged plan, is refused; with every finding answered and the mapping
  passing it exits 0 and prints every rejection; a mapping gap cannot be rejected; a second review
  of the same plan revision is refused; once C15 has landed, the trace goes to a fake C15 client.
- `plugins/saga/tests/test_doc_review_loop.py`: the loop and allowance assertions (`:102-150`) and
  the `/work` gate's P0 and P1 assertions (`:168-184`) become one-pass, answer-every-finding ones;
  the mapping tests (`:343-466`) stay, and `:468` drops its `P1` wording.
- `plugins/saga/tests/test_skill_continuation_endings.py`: doc-review's continuation condition
  (`:103-108`) names the check, not "no `P0` and no `P1` remains".
- `plugins/saga/tests/test_work_gate_integrity.py` (`:274-345`, `:393-401`) and
  `plugins/saga/tests/test_saga_plugin.py` (`:1208-1222`): the doc-review override and safe-fix
  assertions give way to rejections in the progress comment; the review-gate override stays.
- `plugins/saga/tests/test_entrypoints.py` covers the new script's `--help`;
  `plugins/agent-launcher/tests/test_roles_library.py` passes against the new snapshot.

### Context library links

- infiquetra-sdlc `docs/reviewers/plan-review.md` (the plan reviewer's checklist; unchanged)
- `plugins/saga/skills/plan/references/plan-sections.md` (the check grammar the mapping check reads)

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/plan_review.py check --issue <N>` exits non-zero while any
  finding is unanswered or the mapping fails, and 0 otherwise, printing every rejection and reason.
- [ ] A "fixed" answer names a plan section and is refused unless the plan changed since the review;
  a rejection without a reason is refused.
- [ ] `/plan` §5.4 dispatches once. No skill bounds plan review by `standard_cycle_allowance` or
  `escalated_cycle_allowance`, has the reviewer edit the plan, offers a one-word override, or starts
  a cross-family seat or a second opinion.
- [ ] The script, not the session, stores plan-review findings as C1 finding records; standalone
  `/doc-review` reports finding records; once C15 has landed, each plan review posts one trace.
- [ ] `/work`'s doc-review gate blocks on the check; the progress comment lists the rejections.
- [ ] `python3 -m pytest plugins/saga/tests plugins/agent-launcher/tests -q --import-mode=importlib`
  passes with no network call.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/agent-launcher/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: names are proposals (`plan_review.py` with `record`, `answer`, `check`);
  standard library and PyYAML only; the run-record key (inside `review_cycles` or a new one); how
  "changed since the review" is shown (a fingerprint of the plan file, or reviewed revision against
  current). Gate-record markers `plan-review-floor` and `work-doc-review-floor` describe the check.
- For the planning step: the check's printout is what `/plan` §5.4 and `/work`'s gate show an
  attending operator; `issue_progress.py` carries the rejections in place of `--doc-review-fixes`
  and `--doc-review-override`.
- For the planning step: the plan reviewer fills the finding record's fields as C1 defines them;
  no severity drives this gate. Standalone `/doc-review` keeps its artifact under `docs/reviews/`.
- For the planning step: regenerate `lifecycle-snapshot.json` at the lifecycle revision where X1a
  landed, by the roles README's method; whichever of C8, C11 and C12 lands first does it.
- For the planning step: if C15 has not landed, leave the trace call out; whichever of C12 and C15
  lands second adds it, under C15's posting rules (private repositories over HTTPS only; a local
  queue when Langfuse is unreachable; a review never fails because of it).

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C12-plan-review-one-pass.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C12-plan-review-one-pass.md
- Source type: brainstorm
- Source title: saga: plan review in one pass

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/163
- Number: 163
- Created at: 2026-10-05T19:14:10.453165+00:00
