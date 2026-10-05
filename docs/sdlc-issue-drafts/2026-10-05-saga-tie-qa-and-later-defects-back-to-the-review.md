---
title: saga: tie /qa and later defects back to the review that passed the code
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

# saga: tie /qa and later defects back to the review that passed the code

### Objective

A review's misses become visible. `/qa`, saga's functional test after merge, names the review run that
passed the code it tests and posts its failures as that review's misses; the release step records the
merged commit, so `/qa`'s tested revision is never empty. A daily job links later defects and reverts
to the review runs that passed their code, queues them as corpus candidates, and files fix-later boxes
ticked after the review, linking each new issue into the pull request comment.

### Intent

Today (paths under `plugins/saga/`):

- `/qa` runs after the merge and the non-production deploy (`skills/qa/SKILL.md:8-10`). It writes a
  `qa_run.v1` block under the run record's top-level `qa` key, through the record's lock
  (`scripts/qa_strategies.py:1486-1505`, `:1649-1662`), naming no review run. It files no issues and
  edits no pull request (`skills/qa/SKILL.md:64-67`).
- `/qa` reads the tested revision from the record's `deploy` and `release` blocks
  (`scripts/qa_strategies.py:1451-1472`), but nothing writes either. `release_step.py release` works out
  the landed commit (`scripts/release_step.py:167-246`) and only prints it (`:651-678`); `deploy` and
  `close` read the missing block (`:299`, `:475-479`). `references/run-record.md`'s writers table (from
  line 500) has no release row.
- Nothing links a defect found after merge, or a revert, to the review that passed the code, and
  nothing in saga, orchestrate or mission-control runs on a schedule.
- Issues are filed through mission-control (`plugins/mission-control/scripts/sdlc_manager.py`), whose
  `defect` label marks defect issues. Saga's scripts file none (`scripts/review_result.py:992-1029`).

What changes (plan.md, Change 8 "After merge"; Change 9 "Who records outcomes, and when"; Change 10
"Fix-later items"):

1. `release_step.py release` writes its release state, including the merged commit, into the run record
   under the record's lock, keeping every key other writers own.
2. `/qa` records the review run that passed the tested code as `review_run_id` in its `qa_run.v1`
   block, and posts each failure to that run's trace as found by `/qa`.
3. A job runs once a day on the operator's Mac through launchd (macOS's job scheduler), which runs a
   missed job after sleep. It uses the Mac's GitHub sign-in and the `SAGA_LANGFUSE_*` keys, and posts
   only under C15's rules.
4. The job finds review runs in Langfuse. It treats mission-control `defect` issues as new defects and
   takes their file and line from the pull request that fixed them, traced by K1's method to the pull
   request that introduced those lines; reverts are traced the same way. It posts "found after merge"
   or "reverted" to the review run that passed that code.
5. It queues each later defect, from `/qa` or after merge, as a corpus candidate. K1's screening reads
   the queue at each monthly drift run.
6. Each review round posts one pull request comment; the final round's carries the fix-later checklist
   (C13). The job finds boxes there ticked after the review, from any harness or on GitHub, with no
   issue yet. It files each through mission-control's command line, edits that comment to link it, and
   changes the finding's outcome from "left" to "filed" with the issue number, in the run record and
   in Langfuse.
7. `/saga:setup` gains an optional machine step that installs the daily schedule, only on the
   operator's approval, through the mechanism C3 provides for other cards' machine steps.

Depends on C1 (saga: review records, validation and the A–F formula), C3 (saga: /saga:setup checks and
prepares the machine and the repository), C13 (saga: review state for every harness, the pull request
checklist and fix-later choices), C15 (fleet-core + saga: Langfuse review traces and outcomes at merge)
and K1 (Corpus repository, case format and cases from our fix history), whose tracing method the job
uses.

### Risk

medium
The job files issues and edits comments with no operator present, but it acts only on filed defects,
reverts and boxes the operator ticked, and sends nothing beyond what C15 already governs.

### Out-of-scope / non-goals

- The Langfuse client, the trace layout, the local queue and outcomes at merge (C15).
- The comment, its checklist, the choices at merge confirmation and the security guard's filing (C13).
- `/qa`'s selection, drivers and verdict, which stay as they are; the setup script and its machine-step
  mechanism (C3).
- Screening candidates into cases, and tracing fixes that only add lines or span pull requests (K1).
- Re-running full reviews on past changes (plan, Change 6), which waits until Langfuse holds enough data.
- Writing the `deploy` block, which the plan does not ask for; `/qa` falls back to the landed commit.

### Files expected to change

- `plugins/saga/scripts/release_step.py`
- `plugins/saga/scripts/qa_strategies.py`
- `plugins/saga/scripts/outcome_job.py` (new)
- `plugins/saga/scripts/saga_setup.py` (C3's script: the schedule step, added through C3's mechanism)
- `plugins/saga/references/outcome-job.md` (new)
- `plugins/saga/references/run-record.md`
- `plugins/saga/skills/qa/SKILL.md`
- `plugins/saga/skills/qa/references/qa-evidence-and-verdict.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

Test files sit in `plugins/saga/tests/`.

- `test_release_step.py`: a merged release writes the reviewed head, landed commit, pull request and
  merge method under the lock and keeps every other key; any other release writes no landed commit;
  `deploy` and `close` read the written block back.
- `test_qa_strategies.py`: after a recorded release, the tested revision is the landed commit; the block
  carries the `review_run_id` that passed it; each failed strategy posts one miss through an injected
  transport; with no review run found, nothing is posted and the block says why; an unreachable
  Langfuse leaves the verdict unchanged; `/qa` still files no issue.
- `test_outcome_job.py` (new), on a fixture git history with injected runners for GitHub's command-line
  tool `gh` and for mission-control, and an injected Langfuse transport:
  - a `defect` issue whose fix changed lines a reviewed pull request introduced is linked to that review
    run as found after merge; a revert is linked as reverted; each, and each `/qa` miss, is queued once;
  - a ticked box with no issue is filed, the final round's comment gains its link, and the finding's
    outcome changes from "left" to "filed" with the issue number; an unticked box
    is left alone; a second pass changes nothing.
- `test_saga_setup.py`: the schedule step installs nothing without approval; with approval it writes the
  launchd file under a temporary home, and the file holds no key.
- `test_entrypoints.py`: the new script answers `--help` with no credentials.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (Changes 8, 9 and 10)
- `plugins/saga/references/run-record.md` (the writers table and the lock convention)
- `plugins/saga/skills/qa/references/qa-evidence-and-verdict.md`

### Acceptance criteria

- [ ] After a merge through `release_step.py release`, `run_record.py show <issue>` prints a `release`
      block with the landed commit, and `references/run-record.md` lists the release step as a writer.
- [ ] `/qa`'s block carries `review_run_id`, and each `/qa` failure appears on that run's trace.
- [ ] The job links a new `defect` issue or a revert to the review run that passed the touched lines and
      posts "found after merge" or "reverted" to it.
- [ ] Each later defect, `/qa` misses included, is queued once as a corpus candidate where K1 reads it.
- [ ] The job files each ticked, unfiled box through mission-control, links the issue in the final
      round's comment, records the finding's outcome as "filed" with the issue number, and files nothing
      twice.
- [ ] `/saga:setup` offers the daily schedule and installs it only on approval; once installed,
      `launchctl list` shows the job's label.
- [ ] `python3 -m pytest plugins/saga/tests/test_outcome_job.py -q --import-mode=importlib` passes, and
      so do the release-step, `/qa` and setup tests in the full saga suite.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 plugins/saga/scripts/outcome_job.py --help
git diff --check
```

### Notes / conventions

For the planning step:
- `/qa` takes `review_run_id` from the run record: the review run whose head is the release block's
  reviewed head, or an ID the release step records beside it. The envelope schema stays as it is.
- The job lists review runs from Langfuse traces (repository, pull request, base and head commits) since
  its last pass, and keeps its own state under the user's home, owner-only.
- A defect issue is linked once a merged pull request closes it. The job traces that pull request's
  changed lines on its parent revision as K1's screening does, following K1's edge-case rules. Saga is
  public, so it carries its own code for the method and imports nothing from the corpus repository.
- Filing reuses the code C13 uses for "file as issue", so both produce the same issue through
  `sdlc_manager.py issue create`; the job finds mission-control's installed path at run time.
- The candidate queue is an owner-only file under the user's home, at the path and in the format K1's
  screening reads. A record names the review run, the source (`/qa`, defect issue or revert) and the
  fixing pull request where one exists. The job reads `/qa` misses from the scores `/qa` posted, so it
  is the queue's only writer.
- The schedule is a launchd agent in `~/Library/LaunchAgents` with `StartCalendarInterval`. It gets the
  `SAGA_LANGFUSE_*` keys through keychain-env at run time, never from the plist file; `gh` uses its
  stored sign-in. The step is offered only where launchd exists and records its result in C3's machine
  record.
- `/qa` and the job post through C15's `review_trace.py`, so its HTTPS rule, redaction and local queue
  apply. C15 also edits `release_step.py release`. New file names are proposals.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C16-qa-and-outcome-job.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C16-qa-and-outcome-job.md
- Source type: brainstorm
- Source title: saga: tie /qa and later defects back to the review that passed the code

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/167
- Number: 167
- Created at: 2026-10-05T19:15:37.278735+00:00
