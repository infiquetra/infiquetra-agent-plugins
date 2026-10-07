---
title: "saga: build the review redesign (#147) across Claude, Muse and Grok sessions"
type: feat
status: active
date: 2026-10-06
origin: docs/brainstorms/2026-10-05-saga-review-redesign/plan.md
backend: inline
---

# saga: build the review redesign (#147) across Claude, Muse and Grok sessions

## Summary

This plan builds the 29 child cards of #147 (saga's measured, mostly deterministic code review). Each
card is built by one Herdr session: Claude, Muse or Grok. Each card's plan and code are reviewed once
by a session from a different vendor. The coordinator then checks the result against the card's own
acceptance criteria before the pull request merges. Seven cards stay on Claude. Muse and Grok build the
other 22, including the corpus work, which uses the most tokens.

The coordinator (this Claude session) drives every card through one protocol: worktrees,
agent-launcher sessions, a hand-off folder per card, and a deterministic validation gate. Nothing in
this plan has launched. Codex (`gpt-6.1-sol`, `xhigh`) reviewed it once on 6 October 2026, and this
revision answers that review (`.claude/plans/2026-10-06-issue-147/plan-review-codex.md`, outside the
repository).

---

## Problem Frame

The redesign (`docs/brainstorms/2026-10-05-saga-review-redesign/plan.md`) is filed as 29 children
across five repositories (`cards-index.md`, "Filed issues"). Building it on Claude alone would spend a
large share of the operator's Claude usage limit. That spend would include the corpus cards, which mine
our fix history, plant defects and run the review across the whole corpus. Muse and Grok are on
subscriptions the operator already pays for. The risk in moving work to them is quality: another
vendor's agent may finish less than a card asks while reporting that it is done. So every non-Claude
result must be checked against what its card asked for. The check is no stricter than the card, and no
looser.

---

## Requirements

- R1. Every child of #147 is built by exactly one named builder session, and its plan and its code are each reviewed once by a session from a different vendor.
- R2. No card merges until the coordinator has re-run the card's own Verification commands on the pushed branch and every acceptance criterion on the card has evidence (a command result or a `path:line`).
- R3. A check is bounded by its card: reviewers judge against the card's acceptance criteria, its Files expected to change, its Tests to add or update and the repository's rules. Anything beyond that is recorded as a later note and never blocks.
- R4. The operator can see every session: each is one tab in the coordinator's Herdr workspace, named `<card>-<role>-<vendor>` (for example `c1-build-claude`), never a split pane.
- R5. The operator approves each wave's session table, with agent-launcher's preview line for every session, before anything in that wave starts.
- R6. At most 10 agent sessions are live at once across the program, and the coordinator is not counted.
- R7. Muse runs at `max` effort and Grok runs `grok-4.7` at `xhigh`, both signed in through their subscriptions, never with an API key.
- R8. The run band shows #147 with this plan behind its Plan button for the life of the program.
- R9. Each wave ends with a short report: which cards landed, on which vendor, what the validation found, and the Grok usage that `grok usage` reports.

---

## Key Technical Decisions

- KTD1. **The coordinator drives each card itself, through agent-launcher sessions; orchestrate is not used.** Orchestrate's unit chain cannot carry this protocol today: a unit's worktree starts from the shared run branch, not from the unit it waits on (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py:2585-2608`); `go` refuses a dependency that committed nothing (`:3634-3637`), and a review writes findings, not commits; its fix routing needs declared owner roles and paths (`:1662-1706`); and a child plan's checks attach only to rows named by its U-IDs after `expand` (`plugins/saga/scripts/functional_checks.py:364-393`). The coordinator instead creates each card's worktrees, launches its two sessions with agent-launcher's verified launch (`plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py launch`, which records an ownership receipt), and moves every hand-off itself. Rejected: a four-row orchestrate run per card, which the Codex review showed would stall at the first hand-off.
- KTD2. **Each card follows one protocol (below) with two sessions: a builder and a reviewer.** The builder writes the child plan, answers the plan review once, builds, and answers the code review once, all in one session, so it keeps its context. The reviewer reviews the plan once and the code once, in one session, from a checkout pinned to the exact commit it reviews. Every card carries `needs-plan`, and a plan written by the builder costs the builder's tokens, not Claude's.
- KTD3. **One review pass is enforced by the protocol, and saga's own review phases are not invoked for child cards.** Saga's `/plan` dispatches its own plan review and re-reviews a repaired plan (`plugins/saga/skills/plan/SKILL.md`, section 5.4). Saga's `/code-review` runs one reviewer per lens and returns `review_incomplete` while the lifecycle repository's executor ledger is empty (`plugins/saga/scripts/review_consensus.py:2213-2216`). Neither can give one pass today. So builders follow the plan contract (`plugins/saga/skills/plan/references/plan-sections.md`) without running `/plan`'s sections 5.4 to 5.6, and never run `/work` or `/code-review`; the reviewer session is the only review. The protocol stays the same after C12 (one-pass plan review) and C10b (the new code review) land, because neither is used to build this program. A blocking finding still open after the one repair goes to the operator.
- KTD4. **Claude builds the seven cards whose defects would spread furthest:** X1a, C1, C8, C10b, C15, K3 and X3 (table below). X1a and C1 are the contracts and records nearly every other card builds on. C8, C10b, C15 and K3 are the four high-risk cards. X3 changes the home-lab's live Langfuse service. Rejected: all-Claude builds, which defeats the offload, and all non-Claude builds, which puts the foundations on the vendors whose work we are still learning to check.
- KTD5. **Grok builds the code-heavy middle; Muse builds long reading and writing work.** Grok `grok-4.7` at `xhigh` takes 11 cards that are mostly Python and tests. Muse `muse-spark-1.3-contributor` at `max` takes 11 cards that need long reading and writing: the corpus history, planted defects, question banks, pattern checks and skill text. The split also limits exposure to Grok's weekly limit, which has stopped a unit before (`docs/engineering-journal/LEARNINGS.md`, the Grok weekly-limit entry).
- KTD6. **Reviewers cross vendors.** Muse reviews Grok's work, Grok reviews Muse's and Claude's, and the plan reviewer and code reviewer of a card are never its builder. On four cards that the switch (C10b) depends on (C2, C9, C10a, C13), Claude Opus reviews the code. This spends some Claude usage where a missed defect would reach every later review.
- KTD7. **Validation is deterministic first.** The coordinator's gate (below) runs commands and reads files; it does not ask a model whether the work is good. The vendor reviewer reads the change against the card. Tests are the arbiter, and no finding is verified by a second model.
- KTD8. **Muse launches with `--yolo` (agent-launcher permission `bypass`); Grok launches with `auto`.** Muse's approval and sandbox modes are fixed at launch, and a Muse session started without `--yolo` stalled on a network prompt for every site (project memory, 5 October). No credentials live in any worktree or in the corpus checkout.
- KTD9. **A pilot wave goes first.** #114 is built on Grok and reviewed by Muse; #144 is built on Muse and reviewed by Grok. Both are small, and the pilot runs the whole loop on each vendor before 27 more cards depend on it. #114 also writes this repository's `.saga-profile.json`, which every later admission here reads.
- KTD10. **The corpus's token-heavy steps run on Muse and Grok.** K1 mining and proving history defects and K2 planting defects run on Muse. The second vendor that proposes corpus labels (plan.md, "Labels for corpus cases") is Grok. Which reviewer K3's harness measures is settled by D1's bake-off, because it decides who pays for every corpus run and every future review.
- KTD11. **The coordinator is this Claude session (Opus 5.5).** It records #147's admission, creates worktrees, launches and closes sessions, moves each hand-off, runs the validation gate, pushes branches, opens pull requests and asks the operator before each merge. It builds nothing and reviews nothing.
- KTD12. **Orchestrate's parent-branch lookup is filed as a defect, not fixed here.** `parent_branch_name` queries the archived `infiquetra-claude-plugins` repository (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py:2886`). This program does not use orchestrate (KTD1), so U1 files the defect and the fix is separate work.
- KTD13. **One run record, for #147; child cards are not admitted separately.** Admission's staffing accepts only the Claude tier palette and a role's own vendor (`plugins/saga/scripts/admission.py:868-923`), so it cannot record Muse or Grok builders, and nothing in this protocol reads a child's run record. #147's record holds the operator's approved answers (D5), with staffing `none`: its roles are saga's own Claude roles, none of which this protocol starts. Each card's builder, reviewer, models and efforts are recorded in this plan's table and in the card's hand-off folder. Child cards save no saga tick, so #147 stays the active saga and the run band keeps showing this plan (R8).

---

## Decisions the operator made before launch

The operator settled all five on 6 October 2026. Each section gives the decision and the reason.

### D1. Which reviewer K3's harness measures

**Decided (6 October):** a bake-off decides it, by a rule fixed now. It is the first step of K3
(saga-review-corpus#3, whose card now carries it).

**How it runs:** about 80 tuning cases, never held-out ones, spread across the four lenses and the main
languages. Three reviewers review the same cases, defect version and twin: Grok `grok-4.7` at `xhigh`,
Muse `muse-spark-1.3-contributor` at `max`, and Claude Opus as the baseline whose quality is known. Each repeats
the LLM step on the same 20 cases. Codex is not a contestant, because it will not be used afterwards.

**How it is scored:** from the cases' own answers, with no judge model.

- A catch is the case's known defect, found with a test that reproduces in the sandbox.
- A false alarm is a block on a clean twin.
- A flip is a repeat that changes a lens between blocking and passing.

**The rule:**

- The primary reviewer is whichever of Grok or Muse catches more, provided its false-alarm rate is no
  higher than Claude's, its flips stay within 1 in 10, and it catches at least 90% of what Claude
  catches on the same cases.
- The other one becomes the second reviewer on high-risk cards.
- If both fall short, Claude is primary and the better of the two is the second reviewer.

**Why:** the calibration file fingerprints the reviewer's model (plan.md, "The calibration file"), so
the vendor measured becomes the vendor that runs every corpus run and every later review. Those are
the redesign's largest token costs. The bake-off picks that vendor on measured quality instead of a
guess. Its report also gives each vendor's tokens per case and the projected cost of a full run, which
shows whether a full run fits that vendor's weekly allowance before it starts.

### D2. Which Muse model

**Decided (6 October):** `muse-spark-1.3-contributor`, now the Muse favourite in
`~/.config/orchestrate/models.json`, which orchestrate's and agent-launcher's rosters read.

**Why:** the operator's choice. `muse model-profile show muse-spark-1.3-contributor --effort max`
reports a measured tuning cell and trimmed base instructions.

### D3. Muse's effort

**Decided (6 October):** `max` for every Muse session, building and reviewing.

**Why:** the operator's choice, and the level Muse reports as tuned for `muse-spark-1.3-contributor`.
Effort is fixed when a Muse session starts. `ultra`, above `max`, is not used without evidence that it
does better. The pilot report (U2) records how far each Muse session got and whether it stopped on a
usage limit, because Muse has no usage command and its weekly allowance is unknown.

### D4. Private repositories on Muse and Grok

**Decided (6 October):** option A. Muse and Grok may read and receive anything from the operator's
private repositories, CAMPPS included: build sessions, reviews, the corpus and the bake-off. home-lab's
card (X3) stays on Claude.

**Why:** the operator has no objection to any vendor receiving private repository content, and the
corpus and the bake-off need the real history to measure real defects. Credentials are a separate rule
and are never sent. Because Muse's `--yolo` turns off its sandbox, a Muse session can read any file the
operator's account can, so no secret sits in plain files on this machine.

### D5. Admission answers

**Decided (6 October):** the template under "Admission answers", approved as written, including
declining the two tier raises Jev suggested for #147.

**Why:** the operator answers once here.

**Corrected after the Codex review (6 October):** the answers are recorded once, on #147's run record,
not on each card (KTD13). Admission cannot record Muse or Grok in its staffing (`admission.py:868-923`),
so question 4 is recorded as `none`, and each card's builder and reviewer live in this plan's table and
the card's hand-off folder. None of the operator's choices of vendor, model or effort changes.

---

## Sessions and workspace

Every session is one tab in the coordinator's Herdr workspace, named `<card>-<role>-<vendor>` (for
example `c1-build-claude`, `c1-review-grok`). agent-launcher creates tabs in the caller's workspace and
never splits a pane. The coordinator stays in the operator's current tab and closes a card's two tabs,
from their ownership receipts, after its pull request merges.

| Session kind | Vendor, model, effort | Launch posture | Used for |
|---|---|---|---|
| Coordinator | Claude Opus 5.5, this session | the operator's own tab | admissions, wave plans, validation gate, pull requests, merge requests to the operator |
| Claude builder | Claude `claude-opus-5-5`, `medium` (`high` on X1a and the four high-risk cards) | `auto` | the seven cards in KTD4 |
| Claude reviewer | Claude `claude-opus-5-5`, `high` | `auto` | code review of C2, C9, C10a, C13 |
| Grok builder or reviewer | Grok `grok-4.7`, `xhigh` | `auto` (`--permission-mode auto`) | 11 builds; reviews of Muse's and Claude's cards; corpus label proposals |
| Muse builder or reviewer | Muse `muse-spark-1.3-contributor`, `max` | `bypass` (`--yolo`) | 11 builds; reviews of Grok's cards |

At most four cards are in flight at once, and each card has at most two live sessions, so at most
eight agent sessions run (R6). A finished unit's tab stays until the card lands, so the operator can
read it.

**Launch commands.** The coordinator launches every session with agent-launcher's verified launch,
which previews first, checks the live tab, and writes an ownership receipt to the card's hand-off
folder:

```text
python3 <agent-launcher>/skills/agent-launcher/scripts/launcher.py launch --vendor <claude|muse|grok|codex> --task <tab> --cwd <worktree> --model <model> --effort <effort> --permission <auto|bypass> --prompt <brief>
```

The preview of each resolves to the vendor's own command, for example:

```text
agents --no-focus --current --herdr --herdr-control-only --task <tab> --cwd <worktree> muse --yolo --model muse-spark-1.3-contributor --reasoning-effort max
agents --no-focus --current --herdr --herdr-control-only --task <tab> --cwd <worktree> grok --permission-mode auto -m grok-4.7 --reasoning-effort xhigh
```

---

## Who builds and reviews each card

| Wave | Card | Issue | Repository | Risk | Builder | Plan review | Code review |
|---|---|---|---|---|---|---|---|
| 0 | profile | #114 | infiquetra-agent-plugins | low | Grok | Muse | Muse |
| 0 | stale review | #144 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 1 | X1a | infiquetra-sdlc#177 | infiquetra-sdlc | medium | Claude (high) | Grok | Grok |
| 1 | C1 | #148 | infiquetra-agent-plugins | medium | Claude | Grok | Grok |
| 1 | X3 | home-lab#464 | home-lab | medium | Claude | Grok | Grok |
| 2 | C4a | #151 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 2 | C8 | #158 | infiquetra-agent-plugins | high | Claude (high) | Grok | Grok |
| 2 | C12 | #163 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 3 | #151 follow-up | #188 | infiquetra-agent-plugins | high | Grok | Claude | Claude |
| 3 | #158 follow-up | #189 | infiquetra-agent-plugins | high | Claude (high) | Grok | Grok |
| 3 | C2 | #149 | infiquetra-agent-plugins | medium | Grok | Muse | Claude |
| 3 | C3 | #150 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 3 | C4b | #152 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 3 | C4c | #153 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 3 | C5b | #155 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 3 | C6 | #156 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 3 | C9 | #159 | infiquetra-agent-plugins | medium | Grok | Muse | Claude |
| 4 | C5 | #154 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 4 | C7 | #157 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 4 | C10a | #160 | infiquetra-agent-plugins | medium | Grok | Muse | Claude |
| 4 | X2 | infiquetra-context-library#96 | infiquetra-context-library | low | Muse | Grok | Grok |
| 5 | C11 | #162 | infiquetra-agent-plugins | medium | Grok | Muse | Muse |
| 5 | K1 | saga-review-corpus#1 | saga-review-corpus | medium | Muse | Grok | Grok |
| 5 | C13 | #164 | infiquetra-agent-plugins | medium | Muse | Grok | Claude |
| 5 | C15 | #166 | infiquetra-agent-plugins | high | Claude (high) | Grok | Grok |
| 6 | K2 | saga-review-corpus#2 | saga-review-corpus | medium | Muse | Grok | Grok |
| 6 | C14 | #165 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 6 | X1b | infiquetra-sdlc#178 | infiquetra-sdlc | medium | Muse | Grok | Grok |
| 7 | K3 | saga-review-corpus#3 | saga-review-corpus | high | Claude (high) | Grok | Grok |
| 7 | C16 | #167 | infiquetra-agent-plugins | medium | Muse | Grok | Grok |
| 8 | C10b | #161 | infiquetra-agent-plugins | high | Claude (high) | Grok | Grok |

Totals: Claude builds 8, Grok builds 12, Muse builds 11. Claude reviews the plan of 1 card and the code
of 5; Muse and Grok do the other 56 reviews. The two follow-ups (#188, #189) were added on 6 October
after a security review of the merged #186 and #187 found the reviewed change could configure,
silence or read past its own review; they run first in wave 3.

Waves follow `cards-index.md`, "Order and dependencies". A card starts when the cards it depends on
have merged, even if the rest of its wave has not; a unit's Dependencies line names those cards, not
the whole earlier unit. X2 and X1b are built before C10b but held as approved pull requests until it lands, so
no card waits on them. X2 starts once C4b has merged, because its Python versions and its link come
from the pin list C4a creates and C4b fills (decided 6 October, after Grok's wave 1 plan review). C10b lands with X1b and X2, as the index requires. Each
lens stays report-only until K3's calibration file shows it cleared its marks.

---

## The per-card protocol

Every card, whatever its builder, goes through these steps. The coordinator does each step marked
"coordinator"; the two sessions do only their own.

**Hand-off folder.** Each card has one folder in the coordinator's checkout,
`.claude/plans/2026-10-06-issue-147/cards/<card>/`, which git ignores. It holds the session receipts,
both review reports, the acceptance evidence, the gate log, and a `log.md` naming the builder, reviewer,
models, efforts and every commit reviewed. Inside each worktree, hand-off files live in `.program/`, which
the coordinator adds to that repository's `.git/info/exclude` so no session can commit them.

1. **Set up (coordinator).** Create the build worktree on a new branch `issue/<N>` from the repository's
   `origin/main`, and a review worktree, detached, beside it. Launch the builder in the build worktree
   and the reviewer in the review worktree, each with the brief for its first step.
2. **Plan (builder).** Read the card on GitHub, the sections of
   `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` it names, and the repository's `AGENTS.md`
   or `CLAUDE.md`. Write the child plan at `docs/plans/<date>-issue-<N>-plan.md` to the contract in
   `plugins/saga/skills/plan/references/plan-sections.md`, without running `/plan`'s review, board or
   `/work` steps (KTD3). Commit it, and stop.
3. **Check the plan (coordinator).** Run `plan_artifact_conformance.py` and `functional_checks.py map
   --plan <child plan> --issue <N>` on it. A failure goes back to the builder once, before any review.
   Then check out the plan commit in the review worktree.
4. **Review the plan (reviewer).** One pass, against the card only (the reviewer brief below). Write
   `.program/review-plan.md` in the review worktree, naming the commit reviewed. Edit nothing else.
5. **Hand over the findings (coordinator).** Copy the report to the hand-off folder and to the build
   worktree's `.program/`.
6. **Build (builder).** Answer every plan finding once, fixed or rejected with a reason, in
   `.program/answers-plan.md`. Build only what the card asks, within its Files expected to change, and
   name any other file in the commit message with the reason. Run the card's Verification block and
   the child plan's functional checks. Write `.program/acceptance.md`: each acceptance criterion of the
   card, the command or `path:line` that proves it, and the result seen. Commit, and stop. Builders
   never push, open pull requests or merge.
7. **Review the code (reviewer).** The coordinator checks out the build commit in the review worktree
   and copies `acceptance.md` beside it. One pass, against the card, checking each line of
   `acceptance.md`. Write `.program/review-code.md`, naming the commit reviewed.
8. **Repair once (builder).** The coordinator hands over the report. The builder fixes or rejects with
   a reason each P0, P1 and P2 finding in `.program/answers-code.md`, re-runs the Verification block,
   updates `acceptance.md`, and commits. There is no second review.
9. **Gate (coordinator).** Run the validation gate below on the final commit. A pass is pushed and
   opened as a pull request that closes the card's issue (`Closes #<N>` or the cross-repository
   form). The operator confirms each merge. The coordinator then closes both tabs from their receipts
   and removes the worktrees.

A finding the builder rejects, and any P0 or P1 the repair leaves open, is listed in the pull request
for the operator, who decides.

## Reviewer brief

Every review step's prompt points here. The reviewer:

1. Judges against the card's acceptance criteria, its Files expected to change, its Tests to add or update, and the repository's rules (`AGENTS.md`, `CLAUDE.md`; in this public repository, no private-repository figures, hosts or credentials), plus the security floor in rule 5.
2. Makes one pass on the commit named in its prompt. It writes findings with P0 to P3 severity and edits nothing but its report.
3. Records anything beyond the card as a P3 "later" note, which never blocks.
4. For a code review, checks each line of `acceptance.md` against the code and the test results.
5. Always checks a fixed security floor, whatever the card says, and reports what fails it at its real severity, not as a "later" note:
   - **Untrusted input:** does the code trust anything a reviewed change, a user, a repository or a remote can control (its working tree, settings files, a profile, a path, an environment variable, a cache) in a way that lets it switch off, forge or widen what the code checks or reads?
   - **Fail-open:** does a missing, empty, stale, errored or unreadable input count as clean or allowed instead of degraded or refused?
   - **Secrets:** can a credential be read, logged, recorded, or sent to a third party (Jev, Langfuse, a pull request)?
   - **Confinement:** do commands run for the code stay inside the paths, network and environment they need?
   This rule was added on 6 October, after #186 and #187 merged with flaws each of these questions would have caught (#188, #189).

---

## Validation gate

Run by the coordinator on every card, whatever its builder, at step 9, in a fresh checkout of the
final commit:

| Step | Check | Fails when |
|---|---|---|
| V1 | The unit branch has commits, and `git diff --name-only <base>..<branch>` lists the changed files | no commits; or a changed file is outside the card's Files expected to change and the commit message gives no reason |
| V2 | The card's Verification block and the child plan's functional checks, re-run by the coordinator in a fresh checkout of the final commit | any command exits non-zero |
| V3 | The repository's own checks (here: `python3 scripts/check_repo.py`, `python3 -m unittest discover -s tests -v`, `git diff --check`) | any fails |
| V4 | Every acceptance criterion on the card has a line in `acceptance.md`; the coordinator re-runs each cited command and reads each cited `path:line` | a criterion has no line, a cited command fails, or the cited code or test does not do what the line claims |
| V5 | `answers-code.md` answers every P0, P1 and P2 finding in `review-code.md` | a finding with no answer; an open P0 or P1 goes to the operator before the pull request |
| V6 | A session stopped by a usage limit has its uncommitted output treated as unverifiable | any work taken from a blocked session without a re-run |

A card that fails V1 to V4 goes back to its builder once, with the failing step's output. A second
failure is reported to the operator with a choice: rebuild on another vendor, or take it as is.

---

## Admission answers

Admission asks ten questions (`python3 plugins/saga/scripts/admission.py --issue 147 --dry-run
--render tables`). The operator approved these answers on 6 October 2026 (D5). The coordinator records
them once, on #147's run record, after #114 has merged: #114's `.saga-profile.json` answers this
repository's profile questions, so admission does not write a second one.

| # | Question | Template answer |
|---|---|---|
| 1 | Risk tier | high, because #147 replaces the code review every run depends on; each card's own risk is in the table above |
| 2 | Approval boundaries (seven) | `none` for all seven; X3 asks the operator separately for its production change to Langfuse |
| 3 | Destination | `plan-only` for #147; each card's pull request still merges only on the operator's word |
| 4 | Staffing | `none`: saga's own Claude roles, which this protocol does not start (KTD13); the builders and reviewers are in the table above |
| 5 | Lens declaration | the four always-on lenses, plus `privacy` (C15, K1 and X3 handle private data) and `deployment-infrastructure` (X2 and X3); every other conditional lens left out with "one-pass program review: the card's acceptance criteria are the bar" |
| 6 | Repair allowances | 1 standard, 0 escalated (KTD3) |
| 7 | When functional testing cannot finish | bring the result to the operator |
| 8 | Functional-test environment | this repository: `local`, `private`, test command `python3 scripts/check_repo.py && python3 -m unittest discover -s tests`, as #114's `.saga-profile.json` declares it |
| 9 | Is `main` consumed directly | this repository: yes, because Claude installs the marketplace from GitHub's `main` |
| 10 | Code, docs or mixed | mixed |

Admission's Jev tier judgment suggested raising the planner to Opus `xhigh` and the worker to Opus
`high` for #147, at confidence 0.65 (the band where saga asks the operator to confirm). Under this plan
neither role runs on Claude for most cards, so the recommendation is to decline both (`none` for the
two raises).

---

## Implementation Units

### U1. Set up the program

Make the tools, folders and sessions ready, without building any card.

**Goal:** the hand-off folders and checkouts ready; Muse and Grok confirmed to launch as R7 requires; the run band confirmed on this plan; the orchestrate defect filed.

**Requirements:** R4, R5, R7, R8

**Dependencies:** operator approval of this plan

**Files:** none in the repository. Outside it: `.claude/plans/2026-10-06-issue-147/cards/` and each repository's `.git/info/exclude`.

**Approach:** Clone `infiquetra/saga-review-corpus` beside the other checkouts. Add `.program/` to `.git/info/exclude` in all five repositories. Launch one Muse and one Grok session with the R7 settings through agent-launcher, confirm from the receipt and the tab that each started with the requested model, effort and permission and is signed in through its subscription (no Meta or xAI key in the environment), check Grok's weekly allowance, then close both from their receipts. File KTD12's orchestrate defect through mission-control. Confirm `run_status.py summary --all-active` lists #147 first with this plan's path, and that the band's Plan button opens it.

**Patterns to follow:** agent-launcher's "Verified launch" and "The only real preflight is a bounded live launch with a read-back" (`plugins/agent-launcher/skills/agent-launcher/SKILL.md`)

**Test expectation:** none -- setup only; nothing in any repository changes.

**Verification:** both probe sessions' receipts show the requested settings; the band shows #147 with this plan; the defect is filed.

### U2. Pilot: #114 on Grok, #144 on Muse

Run the whole protocol once on each vendor, on two small cards.

**Goal:** #114 and #144 merged through the per-card protocol and the validation gate, and #147's admission recorded.

**Requirements:** R1, R2, R3, R9

**Dependencies:** U1

**Files:** per card (#114: `.saga-profile.json`, `docs/engineering-journal/DECISIONS.md`; #144: as its card lists)

**Approach:** Run both cards through the per-card protocol, with the sessions in "Pilot sessions". After #114 merges, record #147's admission from the D5 answers. After both merge, the coordinator reports what each vendor's session missed or added beyond its card. The operator then decides whether waves 1 to 8 go ahead as staffed or with changes.

**Patterns to follow:** "The per-card protocol", "Reviewer brief", "Validation gate"

**Test scenarios:**
- Happy path: #114's three live-profile tests in `plugins/saga/tests/` run instead of skipping, and pass.
- Hand-off: each review report names the commit the coordinator checked out for it, and the builder's answers file answers every finding in the report it was given.
- Error path: before the pilot, on a scratch copy, a deliberately missing line in `acceptance.md` makes V4 fail.

**Verification:** both cards closed by merged pull requests; each card's hand-off folder holds both reports, both answers files, the acceptance evidence and the gate log; #147's run record exists; the wave report is written.

### U3. Wave 1: X1a, C1, X3

The foundations and the outside-repository cards with no dependencies. X2 started here and moved to
wave 4: its plan was written and reviewed on 6 October, and it resumes from those commits once C4b has
merged.

**Goal:** X1a, C1 and X3 merged.

**Requirements:** R1, R2

**Dependencies:** U2

**Files:** per card (C1: `plugins/saga/tests/test_review_records.py`, `plugins/saga/tests/test_review_formula.py` and the record schema files it lists)

**Approach:** Staffed as the table shows. X3's deploy and live checks run only after the operator approves the deploy.

**Test scenarios:** each card's Tests to add or update section; the child plan names inputs and outcomes.

**Verification:** V1 to V5 pass on each card.

### U4. Wave 2: C4a, C8, C12

The tool framework, the targeted reviewer and one-pass plan review.

**Goal:** the three cards merged.

**Requirements:** R1, R2

**Dependencies:** U3 (C1 for all three; X1a for C8 and C12)

**Files:** per card (C8: `plugins/saga/tests/test_reviewer_answer.py`, `plugins/agent-launcher/tests/test_launcher_contract.py`; C12: `plugins/saga/tests/test_plan_review.py`)

**Approach:** C12 changes how `/plan` reviews plans. Child plans written after it merges follow it.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card.

### U5. Wave 3: #188, #189, C2, C3, C4b, C4c, C5b, C6, C9

The calibration file, setup, the language tools, the scripted checks, the Jev sweep and orchestrate's reviewer transport.

**Goal:** the nine cards merged, at most four in flight at a time.

**Requirements:** R1, R2, R6

**Dependencies:** U4 (C4a for all but C9; C8 for C9). #188 runs first and must merge before C4b, C4c and C5b start, since they build on the runner it fixes; #189 must merge before C9, which carries the reviewer it confines.

**Files:** per card (C2: `plugins/saga/tests/test_review_calibration.py`, `tests/test_check_repo.py`; C6: `plugins/fleet-core/tests/test_jev_sweep.py`)

**Approach:** C2 and C9 get Claude code review (KTD6). C4b and C4c pin tool versions; the reviewer checks the pins against the card.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card.

### U6. Wave 4: C5, C7, C10a, X2

The pattern checks, the question banks, the review command, and the CI standard.

**Goal:** C5, C7 and C10a merged; X2 reviewed, gated and held as an approved pull request until C10b (U10).

**Requirements:** R1, R2

**Dependencies:** U5 (C3 and C4a for C5; C6 for C7; C2, C6 and C8 for C10a; C4b for X2)

**Files:** per card (C10a: `plugins/saga/tests/test_review_command.py`; C7: `plugins/saga/tests/test_question_banks.py`)

**Approach:** C7's question banks are reviewed by the operator, as its card says. C10a gets Claude code review. X2's builder updates its 6 October plan against the merged pin list, its plan is reviewed again, and it builds; its pull request waits, approved, until C10b lands.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card; the operator has approved C7's banks.

### U7. Wave 5: C11, K1, C13, C15

Builder declarations, the corpus's history cases, review state, and Langfuse traces.

**Goal:** the four cards merged.

**Requirements:** R1, R2

**Dependencies:** U6 (C7 for C11 and K1; C10a for C13 and C15; X3 for C15)

**Files:** per card (C13: `plugins/saga/tests/test_review_state.py`; C15: `plugins/saga/tests/test_review_trace.py`)

**Approach:** K1 runs on Muse. Grok proposes the labels beside Jev, and the operator approves the label list in one review (plan.md, "Labels for corpus cases"). C13 gets Claude code review. C15 keeps Langfuse keys out of output, as its card requires.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card; the operator has approved K1's label list.

### U8. Wave 6: K2, C14, X1b

Planted defects and public sets, the review mods, and retiring the old lens machinery in the lifecycle repository.

**Goal:** K2 and C14 merged; X1b reviewed, gated and held as an approved pull request until C10b (U10).

**Requirements:** R1, R2

**Dependencies:** U7 (K1, C10a and C11 for K2; C3 and C13 for C14; X1a and K1 for X1b)

**Files:** per card (C14: `plugins/saga/tests/test_mod_run_record_contract.py`)

**Approach:** C14 changes the run band. The coordinator checks that the band still shows #147 with this plan.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card.

### U9. Wave 7: K3, C16

The harness and its first full corpus run, then tying `/qa` and later defects back to reviews.

**Goal:** both cards merged, and one full corpus run recorded.

**Requirements:** R1, R2, R9

**Dependencies:** U8 (C2, C10a, C15, K1 and K2 for K3; C3, C13, C15 and K1 for C16)

**Files:** per card (K3 is in saga-review-corpus; C16's tests as its card lists)

**Approach:** Claude builds the harness. Its first run is D1's bake-off on about 80 tuning cases; the full corpus runs then use the primary and second reviewers the bake-off chose, so the token-heavy runs go to those vendors. `validate_cases.py --require-minimums` passes for both halves before the first full run (plan.md, CD37). The full run writes `plugins/saga/references/review-calibration.json` (C2's file) on a branch of this repository, as K3's card requires; the coordinator gates that branch like a card and lands it as its own pull request. `run_harness.py --verify-published` (added to K3's card on 6 October) then reads the run back from Langfuse and fails while the run is missing, queued or partial, or when its identifier, fingerprint, held-out totals or per-lens results differ from the committed file.

**Test scenarios:** each card's Tests to add or update section.

**Verification:** V1 to V5 pass on each card; the calibration file on `main` names a completed Langfuse dataset run, and `--verify-published` passes against it.

```functional-checks
- name: corpus-run-published-and-committed
  command: uv run --project ../saga-review-corpus python ../saga-review-corpus/scripts/run_harness.py --verify-published --calibration plugins/saga/references/review-calibration.json
  proves: [AC-3]
  runs: local
- name: fingerprint-rule-holds-with-a-recorded-run
  command: python3 scripts/check_repo.py
  proves: [AC-4]
  runs: local
```

### U10. Wave 8: C10b with X1b and X2

The switch: `/code-review` runs the new review command and the old review is deleted.

**Goal:** C10b merged in a saga release, with X1b and X2 landed in the same window.

**Requirements:** R1, R2

**Dependencies:** U9, and C1, C2, C9, C10a and C13 merged

**Files:** per card

**Approach:** Claude builds; Grok reviews. C10b's squash commit carries `Closes #161` (the check matches it as `Closes .161`, because the check parser treats `#` as a comment). The coordinator merges X1b and X2 straight after C10b, then makes the saga release commit (`chore(release): saga ...`) that the second acceptance criterion names.

**Test scenarios:** C10b's Tests to add or update section; the old review's entry points are gone and nothing imports them.

**Verification:** V1 to V5 pass; the saga release commit is on `main`; every child of #147 is closed.

```functional-checks
- name: every-child-closed
  command: gh api graphql -f query='query{repository(owner:"infiquetra",name:"infiquetra-agent-plugins"){issue(number:147){subIssues(first:50){nodes{state}}}}}' -q '[.data.repository.issue.subIssues.nodes[] | select(.state=="OPEN")] | length' | grep -qx 0
  proves: [AC-1]
  runs: local
- name: release-ships-the-switch
  command: git fetch -q origin && c=$(git log --format=%H -1 --grep='Closes .161' origin/main) && r=$(git log --format=%H -1 --grep='^chore.release...saga' origin/main) && test -n "$c" && git merge-base --is-ancestor "$c" "$r"
  proves: [AC-2]
  runs: local
```

---

## Scenario Smoke

```scenario-smoke
- name: repository-checks-on-the-combined-branch
  command: python3 scripts/check_repo.py && python3 -m unittest discover -s tests
  proves: [AC-4]
  runs: environment
```

This program plan carries no code of its own. Each child card's run carries its own scenario smoke.

---

## Pilot sessions

Four sessions, two per card. At approval (R5) the coordinator shows agent-launcher's preview line for
each, with its real worktree path; the preview creates nothing.

| Tab | Card | Role | Vendor, model, effort | Permission | Working directory |
|---|---|---|---|---|---|
| `i114-build-grok` | #114 | builder | Grok `grok-4.7`, `xhigh` | `auto` | the #114 build worktree |
| `i114-review-muse` | #114 | reviewer | Muse `muse-spark-1.3-contributor`, `max` | `bypass` | the #114 review worktree |
| `i144-build-muse` | #144 | builder | Muse `muse-spark-1.3-contributor`, `max` | `bypass` | the #144 build worktree |
| `i144-review-grok` | #144 | reviewer | Grok `grok-4.7`, `xhigh` | `auto` | the #144 review worktree |

---

## Risks

| Risk | Mitigation |
|---|---|
| A Muse or Grok session reports done while missing part of its card | V2 and V4 re-run the card's own commands and require evidence for every criterion; the pilot (U2) shows each vendor's habits before 27 cards depend on them |
| Grok's weekly limit stops a unit midway | the allowance is checked before each wave; a blocked unit's uncommitted output is discarded (V6), and the card is rebuilt on Muse or Claude |
| Muse cannot run saga commands | no step needs one: builders write plans to the contract file and run plain commands (protocol steps 2 and 6); the pilot's #144 tests this |
| Muse with `--yolo` approves its own actions and can read any file the operator's account can | no secret in plain files on this machine (keys come from the keychain); Muse never builds the home-lab card |
| Reviews loop and burn tokens | the protocol has one plan review and one code review per card and no re-review (KTD3); an open P0 or P1 goes to the operator |
| A hand-off misses: a reviewer reads the wrong commit, or a builder never sees its findings | the coordinator checks out the exact commit and copies each report itself; every report and answers file names its commit, and V5 checks every finding was answered |
| The bake-off picks a vendor whose full run will not fit its weekly allowance | the bake-off reports tokens per case and a projected full-run cost per vendor before any full run; the harness's spending cap refuses a run over its estimate |

---

## Scope Boundaries

- Out: #173 and its four cards (run cost and progress). They follow this program; #171 needs C1 and C10b.
- Out: any change to what a child card asks. A card that proves wrong is changed on GitHub through mission-control first, and then built.
- Out: measuring the Claude usage saved. O4 (#171) builds that. Until then, each wave report lists cards by vendor and Grok's own usage figures.

### Deferred to Follow-Up Work

- Moving more cards to Muse or Grok, or back to Claude, after the pilot report (U2), on the operator's decision.
