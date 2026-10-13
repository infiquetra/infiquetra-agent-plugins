# saga: how /work should build with sessions from other vendors and accept their work

### Research Question

How should saga's `/work` build a card when the builder is a session from another vendor (Muse, Grok,
Codex) rather than a Claude subagent? And how should it accept that work, and hand repairs back to the
same builder, under the operator's one-pass lifecycle? The aim is for programs like #147 to build
through `/work` instead of a coordinator procedure beside it.

### Context

The #147 program plan (`docs/plans/2026-10-06-saga-review-redesign-program-plan.md`) does not use
`/work` for any of its 29 child cards. Its coordinator protocol replaces `/work` because of these gaps.
Evidence is from `main` at 113458c:

1. **The builder can only be Claude.** The `implementation` work shape is `claude_only: true`
   (`plugins/fleet-core/scripts/fleet_commons/staffing.json:62`), and `/work` dispatches each unit as a
   Claude subagent, `saga:worker` or a generic agent with an effort rider
   (`plugins/saga/skills/work/SKILL.md:410-422`). There is no way to give a unit to a Muse or Grok
   session, which is how the program offloads Claude usage.
2. **`/work`'s review gate cannot pass today.** `/work` takes Code Review's outcome as the only
   acceptance, and `review_incomplete` blocks (`SKILL.md:85-89`). `/code-review` returns
   `review_incomplete` while the lifecycle repository's executor ledger is empty
   (`plugins/saga/scripts/review_consensus.py:2213-2216`), so every run stops there unless the
   operator overrides. C10b (#161) replaces that review.
3. **Repairs go to separate roles, not the builder.** Admission's default repair custody is
   "repairs go to dedicated repair roles chosen up front". The program wants the builder's own
   session, which holds the context, to make the one permitted repair.
4. **Its checks live on per-issue run-record rows.** The build loop reads each unit's functional checks
   from the run record that `/plan` writes (`plugins/saga/scripts/functional_checks.py`). A child card
   built under a parent program has no rows of its own.
5. **There is no step to accept work from outside saga.** The program's coordinator gate does this
   instead. It re-runs the card's Verification block in a fresh checkout, checks the changed files
   against the card's list, re-runs each command the builder's acceptance evidence cites and reads each
   cited line, and requires an answer to every review finding (V1 to V6 in the program plan). `/work`
   has nothing equivalent for a commit a foreign session produced.
6. **Muse has no saga plugin,** so a Muse builder cannot run `/work` itself.
7. **Program-level holds.** X2 and X1b are built early but held as approved pull requests until C10b.
   `/work`'s per-issue merge flow cannot express a hold that depends on another card.

The #147 pilot (#114 on Grok, #144 on Muse) produces the first evidence: how many coordinator turns
each card took, which gate steps caught something, and where a vendor's session stopped or drifted.

### Success Criteria

- Each of the seven gaps has a recommendation: change `/work`, change the staffing data, add a new
  acceptance step, or keep the coordinator protocol as documented practice. Each comes with its reason
  and the evidence it rests on.
- The recommendation on gap 1 says whether `claude_only` on `implementation` should change, and what
  quality evidence would justify it (the #147 pilot, and the reviewer bake-off in saga-review-corpus#3).
- Every accepted change is filed as a card through mission-control, with its dependencies on C10b
  (#161), C11 (#162) and C13 (#164) stated.

### Timebox

Two days of agent work, started after the #147 pilot (U2 in the program plan) has merged both cards.
Run it together with the `/plan` exploration (#178), which shares the same evidence.

### Deliverables

- A `/work` section in `docs/brainstorms/<date>-saga-plan-programs/findings.md`, the same findings
  document the `/plan` exploration writes: the seven gaps, the pilot evidence, and a recommendation for
  each.
- Follow-up cards filed through mission-control under the improve-agent-plugins objective.
- A `docs/engineering-journal/DECISIONS.md` entry for the direction chosen.

### Key Questions to Answer

- Should `/work` accept an external builder session as a unit's executor, launched through
  agent-launcher, with an acceptance gate like the program's V1 to V6 in place of trusting the
  session's report?
- Should the `implementation` work shape stop being Claude-only? If so, under what evidence, and with
  what tier mapping for Muse, Grok and Codex?
- Should repair custody allow "the builder's own session, once"?
- How does the build loop find checks for a child card planned under a parent program?
- How does `/work` reach a harness without the saga plugin, such as Muse?
- Can a merge be held on another card's merge, as X2 and X1b wait on C10b?
- Which gaps disappear once C10b (#161), C11 (#162) and C13 (#164) land?

### Related Issues

- #147, the program this came from, and its plan `docs/plans/2026-10-06-saga-review-redesign-program-plan.md`
- #178, the `/plan` exploration filed alongside this card
- #161 (C10b, the new code review), #162 (C11, builder declarations and build-loop checks), #164 (C13, review state)

### Intent

The operator wants multi-vendor building to offload Claude usage without losing quality, through the
lifecycle's own tools. `/work` is where building and acceptance happen, and today it cannot use another
vendor's builder. #147's coordinator protocol shows one working answer to compare against.

### Target repo / surface

`infiquetra-agent-plugins`: `plugins/saga/skills/work/`, `plugins/saga/scripts/build_loop.py`,
`plugins/fleet-core/scripts/fleet_commons/staffing.json`, admission's repair custody, and
`plugins/agent-launcher/`. The deliverables land under `docs/brainstorms/`.

### Mode

explore: research and a written recommendation, not an implementation.

### Constraints

Read-only on code. It uses the #147 pilot's evidence and does not change the running program. Any
change it recommends is filed as a separate card.

### Transfer notes

Adds a `/work` section to the shared `findings.md`, a DECISIONS.md entry, and follow-up cards under the
improve-agent-plugins objective. Related to #147, #178, #161, #162 and #164.

### Risk

low
Research only. It changes no code, and its recommendations become separate cards.
