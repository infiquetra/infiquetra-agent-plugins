---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: review records, validation and the A–F formula

### Objective

Saga has one schema for the five review records (finding, measurement, where-to-look item, lens
grade, review run) and the builder record, a validator that sends back any malformed record, and a
formula in code that gives each input an outcome, each lens an A–F grade and the change a merge
answer. A writer stores the records in the run record with every field.

### Intent

Today on origin/main (1f7137d), paths under `plugins/saga/`:

- Two different shapes are both called `review_result.v2` (`scripts/review_consensus.py:868`,
  `scripts/review_result.py:813`); the command-line writer drops fields when it rebuilds one
  (`scripts/review_result.py:1140-1191`). Results carry no tokens, cost or time.
- Severity is a priority label, P0 to P3, that the reviewer writes (`scripts/review_result.py:120`,
  `:196`); `flag_severity` (`:598`) only suggests one, and only tests call it.
- A lens passes on 0–10 scores against a strictness ladder (`scripts/review_consensus.py:128`,
  `:2161`); one lens with no usable result makes the review `review_incomplete` (`:2215-2216`).

What changes (plan.md, Change 1, Change 7 and "Block, fix later and note"):

- **Records.** Finding: lens; the question or tool rule behind it; source (tool and version,
  classifier and model, or large language model (LLM) and model); location; a one-sentence
  statement; consequence, trigger and evidence from closed lists; proof (the failing test or
  command output when reproduced, file-and-line steps when traced); whether this change introduced
  it; whether it is degraded; severity; an "unconfirmed" mark; and its merge outcome (fixed;
  dismissed, with the reason; fixed now; filed, with the issue number; or left). A location is a
  file, lines and function; a plan finding may name a document section instead, and a whole-project
  tool result may omit the line. The other four records carry Change 1's fields; the lens grade says
  per language whether the lens may block, and the review run adds card, saga version and round
  (Change 8 "Watched"; Change 9).
- **Builder record.** One per unit, in the format a corpus case's builder record also uses (K1, K2):
  the unit's acceptance criteria and their checks; per policy question, whether it applies and its
  proving test; and every reason given (coverage gaps, surviving mutants, scanner false positives,
  "unaffected" marks, pattern-check reasons, explanations of where-to-look items). Repair
  implementers update it; the formula reads its reasons for each "unless the builder records" row.
- **Finding identity.** Each finding keeps one identity across rounds and line shifts; C10b's early
  stop (a repair round leaving the same blocking items) and C15's outcomes match findings by it.
- **Validator.** A finding handed in with a severity is refused: code computes it, never the
  reviewer. A secret-scanner finding carries its location, never the secret; raw tool output is
  referenced by a fingerprint of its content (Change 9).
- **Severity** means the outcome: blocks, fix later or note. A tool or check result takes it from the
  fixed rules (each lens-table row and each pattern check's own outcome); each row has an identifier
  in code that the tool adapters (C4a to C4c) and our checks (C5, C5b) cite. An LLM finding takes it
  from the judged-findings table, where only reproduced harm under normal use or a legitimate
  condition blocks. So an LLM finding counts as fix later (a note, for upkeep) until it is
  reproduced, which is what plan.md means by LLM answers being "inputs with a weight".
- **Modifiers.** A degraded input whose row would block counts as fix later, marked degraded. A
  dispute of the builder's "doesn't apply" or "unaffected" is fix later, flagged for merge
  confirmation. TypeSafe Jev, the classifier, never blocks. For a reproduced finding the LLM and Jev
  each pick the consequence (C8 asks Jev), the lower applies, and disagreement is flagged; when Jev
  cannot answer, the LLM's pick applies and the finding is marked "unconfirmed".
- **Grade and merge.** Per lens: A with no blocking or fix-later items; B with one or two fix-later;
  C with three or more; D with one blocking item; F with two or more. Notes never move the grade, and
  fix-later items never add up to a block. Merge needs every lens at C or better.
- **Report-only.** The formula takes, per lens and language, whether the lens may block; the
  calibration file answers (C2), and without it every lens reports only. A report-only lens keeps
  its computed grade and merge skips its blocks, except reproduced "data lost or corrupted" or "a
  security boundary crossed" (plan.md's "data loss or a security exposure"), which always blocks.
- **Storage.** The writer goes through `run_record.update` (`scripts/run_record.py:599`), which holds
  the record's lock, and round-trips every field. The old shapes stay until C10b deletes them.

Depends on no other card. C2 (saga: the calibration file decides which lenses may block), C4a, C5,
C5b, C6, C8, C9, C10a, C10b, C11, C12, C13, C15, C16, K1 and O4 build on it.

### Risk

medium
A mistake here grades every later review wrong, but nothing calls this code until C10a and C10b.

### Out-of-scope / non-goals

- The calibration file (C2). Capturing the builder record and checking it is complete (C11); adding
  it to the lifecycle's implementation-result contract (X1a).
- Turning tool output, our checks, the sweep or the LLM's answer into records (C4a to C4c, C5, C5b,
  C6, C8). The review command (C10a); deleting the old shapes, rounds and the merge flow (C10b).
- Recording merge outcomes, showing "unconfirmed" picks and disputes at merge, filing issues (the
  security guard's too) and the pull request checklist (C13); Langfuse (C15, C16).

### Files expected to change

- `plugins/saga/references/review-records.schema.json` (new)
- `plugins/saga/references/review-records.md` (new)
- `plugins/saga/scripts/review_records.py` (new)
- `plugins/saga/scripts/review_formula.py` (new)
- `plugins/saga/scripts/run_record.py` (only if the records get their own top-level key)
- `plugins/saga/references/run-record.md`
- `plugins/saga/tests/test_review_records.py` (new)
- `plugins/saga/tests/test_review_formula.py` (new)
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `plugins/saga/tests/test_review_records.py`: each record kind validates when well formed and
  refuses each missing or wrong field by name; a preset severity, a secret's matched text, a merge
  outcome outside the five, a dismissal without a reason and a filing without an issue number are
  refused; only plan findings and whole-project tool results may lack a file and line; write then
  read keeps every field, the builder record's included; a usage entry written meanwhile survives
  (the lock); a finding keeps its identity across a line shift and a later round, and findings from
  two different rules on one line get different identities.
- `plugins/saga/tests/test_review_formula.py`: one named case per row of the judged-findings table
  and each lens table, with and without a builder-recorded reason; grade boundaries; the merge rule;
  degraded, dispute, Jev-only, LLM-against-Jev and Jev-cannot-answer cases; a report-only lens with
  and without the always-blocking harms; the same input twice gives identical output; plan.md's
  three worked examples give its grades (correctness D; security and correctness B; testing B
  degraded).
- `plugins/saga/tests/test_entrypoints.py` picks up the new scripts' `--help` with no credentials.

### Context library links

- infiquetra-context-library `docs/testing/quality-gates.md`
- infiquetra-sdlc `docs/reviewers/verdicts-and-consensus.md` (today's verdict rules, replaced at C10b)

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/review_records.py validate <file>` exits 0 on each well-formed
  fixture, one per record kind, and non-zero on each malformed one, naming the field.
- [ ] Code computes every severity (no path accepts a reviewer-written one); every row of the
  judged-findings table and the four lens tables has a passing test; grades and merge match plan.md.
- [ ] An unreproduced LLM finding is never worse than fix later; when Jev cannot answer, the LLM's
  consequence pick applies and the finding is marked "unconfirmed".
- [ ] With no calibration answer every lens is report-only and keeps its computed grade; merge skips
  its blocks, except a reproduced "data lost or corrupted" or "a security boundary crossed" finding.
- [ ] A test shows a finding keeps one identity across a line shift and a later round.
- [ ] The location, merge-outcome and "unconfirmed" rules above hold in the validator, and the
  builder record round-trips through the writer with every reason kind.
- [ ] `grep -l "review_records\|review_formula" plugins/saga/scripts/*.py` lists only the new files.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network call.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: names are proposals (plan.md names none); lens identifiers reuse today's
  (`correctness`, `security`, `testing`, `architecture-maintainability`); scripts use the standard
  library and PyYAML only; fixtures go under `plugins/saga/tests/fixtures/`.
- For the planning step: the records inside `review_cycles` and the builder records inside `units`,
  or under a new top-level key (`scripts/run_record.py:78-91`).
- For the planning step: the identity's method (today's, a fingerprint of path, line and category at
  `scripts/review_result.py:183`, changes when lines move); how a record marks itself whole-project
  (C4a's adapters say whether results sit on lines); field names; row identifiers; the closed lists,
  taken from plan.md's judged-findings table.
