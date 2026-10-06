---
title: saga: the calibration file decides which lenses may block
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

# saga: the calibration file decides which lenses may block

### Objective

A calibration file in saga records, per lens and language, whether the lens cleared plan.md's pass
marks on the held-out corpus, under a fingerprint of every review component. `scripts/check_repo.py`
fails when that fingerprint no longer matches, so nothing that changes the review merges without a
fresh corpus run. At review time saga reads the verdicts to decide whether a lens may block in a
language. Until a first corpus run exists, every lens reports only.

### Intent

Today on origin/main (1f7137d):

- Whether a lens can block is decided outside this repository. The lifecycle repository's
  executor-verification ledger (`config/executor-verifications.json` in infiquetra-sdlc) is empty on
  purpose, so no lens sets a threshold and every code review ends `review_incomplete`
  (`plugins/saga/skills/code-review/SKILL.md:180-185`,
  `plugins/saga/scripts/review_consensus.py:2215-2216`).
- Nothing ties a change to the review's tools, rules or prompts to evidence that the review still
  works. `scripts/check_repo.py:1238-1254` runs fourteen checks, none about review calibration.

What changes (plan.md, "The harness: The calibration file", "How we'll know it works", and "Order of
work" step 3):

- **Pass marks.** Saga keeps plan.md's marks, fixed in advance, as data the harness reads:

  | Lens | Must block, of known blocking defects | May block, of clean changes |
  |---|---|---|
  | Security | at least 9 in 10 | at most 1 in 10 |
  | Testing | at least 9 in 10 | at most 1 in 10 |
  | Correctness | at least 8 in 10 | at most 1 in 10 |
  | Architecture and maintainability | at least 6 in 10 | at most 1 in 20 |

  With them go the per-language guard (a lens that clears overall but, in one language, catches
  fewer than 7 of 10 defects or blocks more than 2 of 10 clean changes reports only there), the
  repeat-run rule (a lens whose repeated large language model (LLM) runs flip between blocking and
  passing on more than 1 in 10 repeated cases reports only), and the rule that the deterministic
  part gives the same grade every time it sees the same input.
- **The file** holds the fingerprint; the corpus version; the TypeSafe Jev model version the run
  used; per lens and language, a verdict (cleared or report-only) and the numbers behind it
  (held-out results, the repeat-run result); the sweep's per-question thresholds and piece sizes (C6 applies them);
  the run's cost; and its Langfuse run ID. Numbers and identifiers only, so it can live in this
  public repository. The corpus harness (K3) compares its results with the marks and writes the
  file; nobody edits results by hand.
- **Before the first corpus run** the file records that no run exists: every lens reports only, the
  threshold list is empty (the sweep takes its 30 most likely items), and the fingerprint check
  accepts any fingerprint.
- **The fingerprint** has one implementation, in saga, over a listed set of component paths:
  question banks and the policy questions (C7), our checks (C5, C5b), the formula (C1), the default
  tool versions and rule sets with the locally cached Semgrep rule packs (C4a to C4c), and the
  reviewer's vendor, model, prompt and output schema (C8). The file also records, without
  fingerprinting, the reviewer configuration the run measured (a fingerprint of its instruction files
  and enabled plugins); a review whose configuration differs says so, and the next drift run measures
  it. `scripts/check_repo.py` calls it and, once a run exists, fails naming the changed component.
  A card that adds a review component adds its paths to the list in the same change.
- **At review time** saga answers "may this lens block in this language?" from the verdicts alone:
  yes where the verdict is "cleared" and the file's fingerprint matches the current components.
  Otherwise the lens reports only: no run yet, a stale fingerprint, no verdict for the language, a
  `.saga-profile.json` pinning a tool version or rule set other than the default for a tool that
  serves the lens, or a drift change setting the lens to report-only.
- **Drift.** The format lets the monthly drift run set one lens to report-only with a one-line change
  that the operator merges. K3 notices a Jev model change by comparing each sweep verdict's logged
  model version with the one this file records.

Depends on C1 (saga: review records, validation and the A–F formula), whose formula takes this
answer per lens and language, and on C4a. The pinned-version rule reads the default tool list and profile block
of pinned versions that C4a (saga: build-loop tool framework reporting only what a change
introduces) defines. K3 writes the file; C10a, the review command, asks the question.

### Risk

medium
A wrong fingerprint or reader could let an uncalibrated lens block; the default is report-only.

### Out-of-scope / non-goals

- Running the corpus, comparing results with the marks, writing verdicts, numbers and thresholds,
  and noticing a Jev model change (K3); the corpus itself (K1, K2).
- Setting or changing the pass marks: plan.md fixes them in advance; this card stores them.
- The formula (C1); the review command (C10a); the sweep (C6). Retiring the ledger (X1b).
- The components the fingerprint covers, each added to the list by its own card (C4a to C4c, C5,
  C5b, C7, C8).

### Files expected to change

- `plugins/saga/references/review-calibration.json` (new)
- `plugins/saga/references/review-calibration.md` (new)
- `plugins/saga/scripts/review_calibration.py` (new)
- `scripts/check_repo.py`
- `tests/test_check_repo.py`
- `plugins/saga/tests/test_review_calibration.py` (new)
- `plugins/saga/references/repository-profile.md`
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `tests/test_check_repo.py`: with no run recorded, any fingerprint passes; with a run recorded, a
  matching fingerprint passes, a one-byte change to a listed component fails and names it, and a
  missing listed path fails; keys outside the format, or free text outside its identifier fields,
  fail.
- `plugins/saga/tests/test_review_calibration.py`: the stored marks, guard and repeat-run rule equal
  plan.md's; a "cleared" verdict under the current fingerprint answers yes; report-only for a
  "report-only" verdict beside numbers that clear the marks, a stale fingerprint, no corpus run
  (every lens), a language with no verdict, a profile pinning another version or rule set of a
  tool serving the lens, and a drift change; thresholds read back, and are empty before a run.
- `plugins/saga/tests/test_entrypoints.py` picks up the new script's `--help` with no credentials.

### Context library links

- infiquetra-context-library `docs/testing/quality-gates.md`
- infiquetra-sdlc `config/executor-verifications.json` (the ledger this file replaces; X1b retires it)
- `plugins/saga/references/repository-profile.md`

### Acceptance criteria

- [ ] `review-calibration.md` documents every field and every kind of component the fingerprint
  covers, the reviewer's launch settings and the cached Semgrep rule packs included, and says a card
  adding a component adds its paths in the same change.
- [ ] The committed file records that no corpus run exists, with every lens report-only and no
  thresholds; a test shows the stored marks, guard and repeat-run rule equal plan.md's.
- [ ] `python3 scripts/check_repo.py` passes with any fingerprint while no run exists, and once one
  is recorded fails, naming the component, when a component changes and the fingerprint does not.
- [ ] `python3 plugins/saga/scripts/review_calibration.py may-block --lens security --language
  python` prints the answer and its reason.
- [ ] Every case under "Tests" answers as stated, with no network call; the review reads verdicts
  and never compares numbers with the marks itself.
- [ ] One fingerprint implementation serves both `check_repo.py` and saga; `check_repo.py` stays
  standard-library only and imports the saga module locally, like its other generated-file checks.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_check_repo -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: file, key and subcommand names are proposals (plan.md names none); the new
  script uses the standard library and PyYAML only. The marks sit in a section of
  `review-calibration.json` the harness reads and never changes, or in a file beside it.
- For the planning step: the first component list holds C1's formula and record schema
  (`plugins/saga/scripts/review_formula.py`, `plugins/saga/references/review-records.schema.json`).
- For the planning step: the fingerprint reaches the Semgrep rule cache offline, with the cache in
  the repository or a content fingerprint of each pack kept with its pin (C4a, C4b); the launch
  settings join by the path of the file C8 keeps them in.
- For the planning step: how the format spells "no run yet", and a per-lens line the drift change
  flips, so one line sets a lens to report-only in every language.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C2-calibration-file.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C2-calibration-file.md
- Source type: brainstorm
- Source title: saga: the calibration file decides which lenses may block

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/149
- Number: 149
- Created at: 2026-10-05T19:09:04.381299+00:00
