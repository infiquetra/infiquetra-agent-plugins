---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: review state for every harness, the pull request checklist and fix-later choices

### Objective

One saga script writes a code review's state and pending choices as one document. Every screen
reads it, every answer goes back through the script, and harnesses without mods get Markdown with
numbered questions. Each round posts one pull request comment, the final one with the fix-later
checklist. At merge confirmation each fix-later item is fixed now, filed or left, and its finding
record keeps the choice. An unattended run files only security-guard items, and its merge follows
the merge setting recorded at run start.

### Intent

Today (paths under `plugins/saga/`):

- No one document holds a review's state: `/review-view` reads `run_status.py review` (lines 471-517
  of `scripts/run_status.py`), the band reads its `summary` (657-739), and the pull request comment,
  one comment and never a review, has no checklist (`scripts/review_result.py:1036-1115`).
- Merge confirmation is prose: `/work` asks a question (`skills/work/SKILL.md:93-95`), and the merge
  stays explicitly confirmed (`:1074-1080`, pinned by `tests/test_work_gate_integrity.py:347`).
- No fix-later choice exists. Open findings become defect issues only at the cycle cap, through code
  that runs only in tests; filing is mission-control's (`review_result.py:992-1029`).
- The intent envelope (`plugins/fleet-core/scripts/fleet_commons/intent_envelope.py:116-131`)
  records at run start whether a run is attended, and whether merge waits for the operator (`gate`)
  or may proceed (`auto`); saga asks no second run-start question (`scripts/intent_envelope.py:29`).
- Admission has the pattern: `admission.py --render json` prints one document and `--render tables`
  the same rows as Markdown (`scripts/admission.py:1403-1406`, `:1871-1897`); answers return through
  `--answers -` (`:1900-1916`); its Claude Code pane waits at most 30 minutes.

What changes (plan.md, Change 10 except the mods; "Block, fix later and note"):

1. A new script builds the review-state document from the review command's records (C1, C10a):
   each lens's grade with its blocking and fix-later counts; the where-to-look list with each
   item's state; the tools that ran or were missing, with C3's missing-tools notice; degraded
   inputs; the round and the cost so far; and what each round found that the one before did not.
2. Its pending choices are merge confirmation's: over blocking items left at an early stop or the
   round limit, merge with a recorded reason or stop the card; and one choice per fix-later item.
   It also shows disputed "doesn't apply" and "unaffected" declarations, consequences the LLM
   (large language model) and TypeSafe's Jev classifier disagreed on, and those marked
   "unconfirmed" because Jev could not answer.
3. It also prints Markdown with numbered questions. Answers from any screen return through
   `--answers -`, which validates and records them; `run_status.py review` now reads the document.
4. Each round posts one pull request comment with the summary, never a review; the final round's
   lists every fix-later item as a checkbox, which C16's job later edits to link issues it files.
5. Each fix-later item takes one of three choices. **Fix now** sends it to a repair round before
   merge. **File as issue** files it at once through mission-control. **Leave** keeps it on the
   checklist. The finding record keeps the outcome: fixed now, filed with the issue number, or left.
6. The security guard: a harm the security lens's LLM traced but could not reproduce is filed as an
   issue, attended or not, unless the operator chose fix now.
7. Unattended means the run mode in the intent envelope; no new question is asked. Nothing is filed
   then apart from the security guard; C16's job files boxes ticked later. A Claude Code pane
   timeout (30 minutes, C14) counts as unattended; a question in a chat simply waits.
8. The document says what the merge waits on. An unattended merge follows the envelope's setting:
   `auto` merges once every lens is at C or better, `gate` waits for the operator. Fix-later choices
   never hold a merge. Blocking items at the round limit or an early stop wait for the operator
   whatever the setting, since only the operator can merge with a reason or stop the card.
9. The repository profile (`.saga-profile.json`) sets the unattended default: `leave` (the default)
   or `file`, which files one follow-up issue per pull request listing all its fix-later items.

Depends on C1 (saga: review records, validation and the A–F formula) and C10a (saga: one review
command from change to records). C14 draws this document in Claude Code; C10b switches
`/code-review` to it, carries out or holds the merge, and runs the fix-now round.

### Risk

medium
It changes what the operator is asked at merge and files issues for them, but adds no new block.

### Out-of-scope / non-goals

- The Claude Code panes, the band and the status line (C14).
- The fix-now round (outside the 3-round limit), carrying out the merge, and deleting
  `run_status.py`'s old-shape reader (C10b); filing boxes ticked later (C16).
- Each finding's fixed or dismissed fate, and posting outcomes to Langfuse (C15).
- Grades, outcomes and which lenses may block (C1, C2); the missing-tools notice itself (C3).

### Files expected to change

- `plugins/saga/scripts/review_state.py` (new)
- `plugins/saga/scripts/run_status.py`
- `plugins/saga/references/review-state.md` (new)
- `plugins/saga/references/repository-profile.md`
- `plugins/saga/skills/code-review/SKILL.md`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_review_state.py` (new), on fixture records (C1's shape) and envelopes,
  with an injected runner for GitHub's command-line tool `gh` and no network:
  - the document carries every item under "What changes" behind a checked version token, and the
    Markdown numbers every pending question and lists the same items;
  - an unknown item or choice, or a merge over blocking items with no reason, is refused unrecorded;
  - file as issue hands a prepared issue to mission-control and records "filed" with its number;
    fix now and leave land in the finding record; saga runs no `gh issue create`;
  - the security guard files attended and unattended, and nothing for an item fixed now; an
    unattended envelope or a pane's timed-out answer files nothing else;
  - `auto` needs no answer once every lens is at C or better, `gate` waits, and blocking items at
    the limit or an early stop wait under either;
  - the `file` default prepares one issue listing every fix-later item; no key means `leave`;
  - each round posts one `gh pr comment`, never `gh pr review`; only the final one has checkboxes.
- `plugins/saga/tests/test_run_status.py`: `run_status.py review` prints from the document.
- `plugins/saga/tests/test_entrypoints.py` covers the new script; `test_work_gate_integrity.py`
  passes unchanged.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` (Change 10; Block, fix later and note)
- `docs/engineering-journal/DECISIONS.md`, 2026-10-04: admission renders its Markdown tables itself
- `plugins/saga/references/run-record.md`, `repository-profile.md` and `intent-envelope.md`

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/review_state.py --help` exits 0 with no credentials set, and
      `python3 plugins/saga/scripts/run_status.py review` prints from the review-state document.
- [ ] For a fixture review, the document and its Markdown list the same lenses, items and choices,
      including disputes, consequence disagreements and "unconfirmed" consequences.
- [ ] Every answer, from a pane or a numbered question, is recorded only through `--answers -`, and
      a malformed answer is refused with a message naming what is wrong.
- [ ] Each fix-later item's finding record carries fixed now, filed with the issue number, or left;
      filing goes through mission-control at once, and saga's tree gains no `gh issue create`.
- [ ] Each round posts one pull request comment; the final one has a checkbox per fix-later item.
- [ ] An unattended envelope or a pane timeout files only security-guard items; the document shows
      the merge waiting or not as the envelope's merge setting and the round rules say.
- [ ] The profile reference documents the unattended-default key with `leave` and `file`; a profile
      without it stays valid and means `leave`.
- [ ] `python3 -m pytest plugins/saga/tests/test_review_state.py -q --import-mode=importlib` passes.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: new file names are proposals; the profile key's name; whether the script
  prints the document on demand from the run record, as admission does, or also keeps a file.
- For the planning step: the answer form a pane timeout takes, so the script and not the mod
  decides what is filed; and how the final round's comment is marked so C16's job finds it.
- For the planning step: the merge-outcome field and the "unconfirmed" mark are C1's, written
  through C1's writer. `run_status.py review` keeps its name as the code-review skill's fallback
  view (`skills/code-review/SKILL.md:349-351`).
