---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: measured, mostly deterministic code review (review redesign)

### Objective

Saga's code review becomes mostly deterministic and measured. Tools, our own pattern checks and narrow
classifier questions produce outputs. One targeted LLM (large language model) reviewer confirms or
clears what they point at. A fixed formula turns everything into an A–F grade per lens. A lens may
block a merge only once a corpus of known defects shows that it catches them without blocking clean
changes, and every review is recorded in Langfuse with what later happened to its findings.

### Intent

Today's code review costs a lot and decides little:

- Each round runs one reviewer session per selected lens, 4 to 15 of them, and each re-reads the whole
  branch (`plugins/saga/skills/code-review/SKILL.md`, phases 1 and 2).
- A round is accepted only when every selected lens has a scorer qualified in the lifecycle
  repository's executor ledger. That ledger is empty on purpose, so rounds end `review_incomplete`
  (`plugins/saga/scripts/review_consensus.py:2213-2221`).
- Parts of it never run. No phase schedules the verifier (`references/validator.md`). Only tests call
  Jev's duplicate and severity checks. Two different result shapes share the name `review_result.v2`,
  and the command-line writer drops fields (`plugins/saga/scripts/review_result.py:1140-1191`).
- Plan review loops up to five times and lets lower-priority findings stay
  (`plugins/saga/skills/plan/SKILL.md:770-784`).

The decided plan (`docs/brainstorms/2026-10-05-saga-review-redesign/plan.md`) replaces this with ten
changes. The children of this card build them in this order (direct dependencies are in
`cards-index.md` and in each card):

1. **First:** the lifecycle repository records the new review model and its contracts (X1a).
2. **Before saga switches over, with every lens reporting only:**
   - the records and the formula (C1) and the calibration file (C2);
   - setup (C3), the tools (C4a to C4c), our pattern checks (C5) and the scripted checks (C5b);
   - the Jev sweep (C6) and the policy questions and question banks (C7), which the operator reviews
     lens by lens before they are used;
   - the targeted reviewer (C8) and its transport (C9);
   - the review command (C10a) and the builder declarations (C11);
   - the review state for every harness (C13), the Claude Code mods (C14) and the Langfuse traces (C15);
   - HTTPS for Langfuse (X3), before any private repository's code is sent.
3. **The switch** (C10b), with the lifecycle repository's retirements (X1b) and the CI standard (X2).
4. **Built alongside:** the corpus (K1, K2) and the harness (K3). Each lens starts blocking as the
   calibration file shows that it cleared its pass marks.
5. **Any time after their dependencies:** plan review in one pass (C12), and links from `/qa` and later
   defects back to the review that passed the code (C16).

The table mapping each card ID to its issue number is added here once the children exist.

### Risk

high
The switch changes what can block a merge in every repository that uses saga. The new reviewer runs
model-written tests, and review data leaves the machine for Langfuse.

### Inputs inventory

- The decided plan and the card index: `plan.md` and `cards-index.md` in
  `docs/brainstorms/2026-10-05-saga-review-redesign/`.
- Pass marks, measured on corpus cases never used for tuning:

  | Lens | Must block, of known blocking defects | May block, of clean changes |
  |---|---|---|
  | Security | at least 9 in 10 | at most 1 in 10 |
  | Testing | at least 9 in 10 | at most 1 in 10 |
  | Correctness | at least 8 in 10 | at most 1 in 10 |
  | Architecture | at least 6 in 10 | at most 1 in 20 |

- Existing issues this program absorbs or relies on: #144 (a stale review re-enters code review
  without the combined-branch functional run; C10b replaces that path) and #114 (this repository's own
  `.saga-profile.json`; the first user of C3).

### Failure modes / pre-mortem

- **The corpus doesn't look like real changes.** Planted defects are easier to find than real ones, and
  public sets sit in models' training data, so the measured numbers flatter the review. The guards:
  - cases come mostly from our own fix history;
  - the held-out half is never used for tuning;
  - every defect found later is added to the corpus;
  - every corpus run reports the share of history cases against planted ones.
- **The corpus slips and report-only becomes permanent,** while report-only results get skimmed at
  merge. The calibration file shows progress lens by lens, and the merge screen shows every lens's
  report.
- **Later rounds cost more than they find.** The operator doubts they are worth it. Each review run
  records what each later round added, and a Langfuse view of that number decides whether to move to
  one round.
- **Corpus runs grow too slow or costly to repeat,** and pressure builds to loosen the calibration
  check. Caching by fingerprint and the cost estimate before each run keep a rerun cheap.
- **The harness measures a different reviewer from the one in real reviews.** Real reviews always run
  with instruction files and plugins, so the harness starts the reviewer the same way, through
  agent-launcher, and turns a component off only where a comparison shows it has no effect. The
  calibration file records the configuration it measured, and a review whose configuration differs
  says so.

### Stop conditions

- Stop and ask the operator before any change lets a lens block without a calibration file showing that
  it cleared its marks.
- Stop before any private repository's code is sent to Langfuse while the server lacks HTTPS (X3).
- Stop if the switch (C10b) would ship without the review command (C10a), the records (C1) and the
  calibration file (C2) in the same release.

### Out-of-scope / non-goals

- Backstop gates; the operator deferred them on 4 October 2026.
- The status band's second version, the per-turn reminder, budget at admission and cost-report
  economics. Those are their own cards (O1 to O4), not children of this one.
- Accessibility and user-experience review. They leave code review. Their home is `/qa`'s
  app-interface strategy, which has no driver today; building one is not part of this plan.

### Files expected to change

- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/saga/scripts/` (the review command, records, formula and calibration file; see the children)
- `plugins/fleet-core/scripts/` (the Jev sweep and the Langfuse client)
- `plugins/agent-launcher/roles/`
- `plugins/orchestrate/skills/orchestrate/`
- `plugins/saga/com.infiquetra.claude/mods/`

### Tests to add or update

- Each child card names its own tests. This card adds none of its own.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md`
- `docs/brainstorms/2026-10-05-saga-review-redesign/cards-index.md`

### Acceptance criteria

- [ ] Every child card is closed.
- [ ] A saga release ships the switch (C10b) together with the review command, the records and the
      calibration file.
- [ ] The harness (K3) has completed one full corpus run recorded in Langfuse, and saga's calibration
      file carries that run's fingerprint and per-lens results.
- [ ] `python3 scripts/check_repo.py` passes with the calibration file's fingerprint rule in force.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```
