---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga mods: review pane, merge confirmation, run band and setup pane

### Objective

Inside Claude Code the operator watches a review live, confirms the merge in a pane, sees review
state and missing tools at a glance, and runs setup from a pane. Every screen draws from a document
a saga script prints and answers through that script. No mod computes a grade, a block or an
outcome, and a pane that times out files nothing and leaves the merge to the run's recorded setting.

### Intent

Today (paths under `plugins/saga/com.infiquetra.claude/`):

- Mods display state and collect answers; saga's scripts own state and policy (`mods/index.ts:1-6`).
- `/review-view`, a command the review-pane mod registers, shows the latest code review result lens
  by lens through `run_status.py review` (met, not met, not run or unscored, with finding counts),
  polling the run record every five seconds (`mods/review-pane.tsx:1-22`, `:127-174`).
- No merge-confirmation pane: `/work` asks a question (`plugins/saga/skills/work/SKILL.md:93-95`).
- The band above the prompt shows one line per run, rendered by `run_status.py` for every harness;
  its review part reads "review cycle N/3 (escalated)" and "lenses met" (`run_status.py:706-739`).
  The status line shows only the issue and phase, and the band is its only saga writer, since the
  engine keeps one status line per plugin (`mods/run-band.tsx:19-20`, `:44-49`).
- There is no setup pane or command; C3 adds the command. Claude Code has no install event (the
  nearest mod event is session start). No saga mod uses `$.store`, the engine's small key-value
  store that outlives a session.
- The admission pane is the pattern: a tool the mod registers draws from the script's document and
  hands answers to the script on standard input. It waits at most 30 minutes, one second at a time
  through the engine, and returns submitted, dismissed or timed-out; on anything but submitted the
  skill prints the script's Markdown (`mods/admission-review.tsx:1-21`, `:272-334`).

What changes (plan.md, Change 10 "Claude Code"; Change 2 "Screens" and "When it runs"):

1. **A live review pane, still opened by `/review-view`,** shows each lens's grade with its blocking
   and fix-later counts, the where-to-look list with each item's state, which tools ran or were
   missing, the round and cost so far, and a round-by-round view of what each round added. It reads
   C13's review-state document only, through `run_status.py review` as C13 rebuilds it.
2. **A merge-confirmation pane**, working like the admission pane, shows the grades; blocking items
   left at an early stop or the round limit, with a box for the merge reason and a choice to stop
   the card; disputed "doesn't apply" and "unaffected" declarations; consequences the LLM (large
   language model) and TypeSafe's Jev classifier disagreed on, and those marked "unconfirmed"; the
   fix-later list, each item fixed now, filed or left; degraded inputs; and the cost. Answers go to
   C13's script.
3. **Closing and timing out.** Closing the pane falls back to C13's numbered questions. A 30-minute
   timeout goes to C13's script as unattended: nothing is filed then apart from the security guard,
   and the merge follows the merge setting in the run's intent envelope (C10b carries it out).
4. **The band and the status line.** The band's review part shows the round and grades from C13's
   document; the status line adds C3's missing-tools notice, naming the tools and `/saga:setup`.
5. **A setup pane** lists each tool with its status, the lens it serves and a checkbox. Its Install
   button passes the ticked tools to C3's setup script and shows live progress.
6. **The first-session offer.** At session start, when C3's machine record (in the user's home,
   outside any repository) shows setup has never run, a mod offers `/saga:setup` once. The offer is
   remembered in the mod's `$.store` and in C3's machine record, so no later session repeats it.

Depends on C3 (saga: /saga:setup checks and prepares the machine and the repository) and C13 (saga:
review state for every harness, the pull request checklist and fix-later choices).

### Risk

medium
These are Claude-only screens over scripts that own every decision. A wrong pane can mislead or send
a wrong answer, but the script validates every answer, and nothing here changes a grade or a block.

### Out-of-scope / non-goals

- The document, its Markdown, answer checks, issue filing and rebuilding `run_status.py review`
  (C13); the fix-now round and carrying out the merge (C10b).
- Setup's checks, installs and machine record, and the one-line suggestion on other harnesses (C3).
- The band's second version (O1, saga mod: status band, second version): step, spend against
  budget, time in step, age of the last GitHub update, and spend in the status line.

### Files expected to change

- `plugins/saga/com.infiquetra.claude/mods/review-pane.tsx`
- `plugins/saga/com.infiquetra.claude/mods/review-findings.ts`
- `plugins/saga/com.infiquetra.claude/mods/merge-confirmation.tsx` (new)
- `plugins/saga/com.infiquetra.claude/mods/setup-pane.tsx` (new)
- `plugins/saga/com.infiquetra.claude/mods/run-band.tsx`
- `plugins/saga/com.infiquetra.claude/mods/run-record.ts`
- `plugins/saga/com.infiquetra.claude/mods/index.ts`
- `plugins/saga/com.infiquetra.claude/types/index.d.ts`
- `plugins/saga/scripts/run_status.py` (the band's review part)
- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

Mod tests sit beside the mods in `plugins/saga/com.infiquetra.claude/mods/`.

- `mods/review-pane.test.tsx`: from a fixture document the pane draws grades, counts, where-to-look
  states, tools, round and cost; the round view lists only what each round added; an unknown
  document version is reported, not guessed; `/review-view` and the band's Review button open it.
- `mods/merge-confirmation.test.tsx` (new): Submit hands the answers to C13's script on standard
  input (a stubbed process runner checks the call); a refusal the script prints is shown as
  printed; closing returns dismissed; the 30-minute wait returns timed-out and hands the timeout to
  C13's script, and the pane itself files and merges nothing; fix-later items offer only the three
  choices, and blocking items only a merge with a reason or stopping the card.
- `mods/setup-pane.test.tsx` (new): rows come from C3's output; Install passes only the ticked
  tools; the offer appears when C3's machine record shows setup never ran, and a later session
  start with the offer remembered in `$.store` shows nothing.
- `mods/run-band.test.tsx`: with tools missing, the status line names them and `/saga:setup`.
- `mods/run-record.test.ts`: new readers handle a wrong version, cut-off output and a failed exit.
- `plugins/saga/tests/test_mod_run_record_contract.py`: pins the version tokens and exit codes the
  new readers rely on against the real C13 and C3 scripts, as it does for `run_record.py show`.
- `plugins/saga/tests/test_run_status.py`: the band line's review part shows the round and grades.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (Change 10; Change 2 "Screens")
- `docs/engineering-journal/DECISIONS.md`, 2026-10-04: `run_status.py` renders the band's words
- `docs/engineering-journal/LEARNINGS.md`, 2026-10-04: a mod waiting for a person waits on `$` calls

### Acceptance criteria

- [ ] `claude plugin validate --strict plugins/saga` and `claude plugin test plugins/saga` pass on
      Claude Code 2.1.286 and 2.1.289 (CI's builds), as does `test_mod_run_record_contract.py`.
- [ ] `/review-view` opens the live review pane; it and the merge-confirmation pane read only C13's
      document, and no mod computes a grade, block or outcome.
- [ ] A merge confirmation answered in the pane is recorded through C13's script; closing it leaves
      the skill asking C13's numbered questions; a timeout files nothing beyond the security guard
      and leaves the merge to the run's merge setting.
- [ ] The status line names missing tools and `/saga:setup`; the band is still its only saga writer.
- [ ] The setup pane installs only what the operator ticked, and the setup offer appears only once.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
claude plugin validate --strict plugins/saga
claude plugin test plugins/saga
python3 -m unittest tests.test_claude_plugin_packaging -v
git diff --check
```

### Notes / conventions

- For the planning step: new file names are proposals. The merge-confirmation pane registers a tool
  the way admission's registers `mcp__saga__review_admission`; its name is chosen then.
- For the planning step: the `$.store` key for the offer; how the mod records the offer in C3's
  machine record (through C3's script, since saga's scripts own state); and the answer form C13
  defines for a timeout.
- For the planning step: O1 also shows the round on the band; whichever of C14 and O1 lands second
  rebases onto the other.
