---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: policy questions and question banks for the four lenses, reviewed by the operator

### Objective

Saga publishes the policy's 30 questions as a public list that builders declare against, and beside it four Jev question banks, one per lens (security, correctness, testing, and architecture and maintainability), of 10 to 20 questions each, which saga passes to `jev sweep`. Questions folded in from the old optional lenses name the condition that switches them on. Each lens has one sitting with the operator, its approval is recorded in its bank file, and code refuses a set whose content differs from its approval.

### Intent

Today (infiquetra-agent-plugins at origin/main 1f7137d):

- No question bank exists. What a lens checks lives as dimensions and anchors in the lifecycle repository's lens catalogue, which each lens reviewer reads at a pinned revision (`plugins/agent-launcher/roles/lens-reviewer.md:84-98`).
- The only review question Jev asks is the `lenses` verb: five yes/no questions about a whole diff, used to propose optional lenses (`plugins/fleet-core/scripts/fleet_commons/jev_verbs.py:171-182`).
- The eleven optional lenses are chosen per run by the planner's declaration, each by a prose condition (`plugins/saga/skills/code-review/references/lens-execution.md:44-64`).
- The operator's code-review policy draft (private notes) holds the policy's 30 questions, among them correctness's 15 and security's 7 (plan.md, lens tables). Each says why it matters, how to check, what fails, what clears, examples, and what it is not for.

What changes (plan.md: Change 5 "Questions"; Change 8 "Optional lenses"; the lens tables under "Lens by lens"; Order of work, step 4):

- **The policy list.** The policy's 30 questions, rewritten in public-safe wording, as one JSON (JavaScript Object Notation) list in saga. Each names its lens, what fails, what clears, and the proving test the draft names for it, which a builder must supply wherever the question applies. Builders declare against this list (C11).
- **Four banks beside it,** one per lens, in the format the sweep defines (C6), starting at 10 to 20 questions each and tuned on the corpus like every other question. Saga passes each bank to `jev sweep`.
- **Three sources.** The policy's questions where no tool can answer them; the defects our reviews keep hitting; and public lists of common mistakes, used only where the corpus shows a gap.
- **What gets no question.** A row the lens tables give to a tool or a check (coverage, mutation testing, scanners, type checks, the functional-checks map) is not asked again. Rows the tables answer by "classifier, then the LLM" (the large language model reviewer) do get questions, for example the testing lens's "a test that fakes the code under test" and "a test that writes to a live or shared system".
- **The folded optional lenses** become questions inside the four, asked only when the change touches the matching kind of code: reliability, API contracts and performance in correctness; attacker-minded review and privacy in security; deployment and infrastructure in security and in architecture; documentation and agent usability in architecture. Each names its source lens and its switch-on condition, written in C6's condition format.
- **Each question** states one literal condition (house rule 4 in `plugins/fleet-core/references/typesafe.md:93`), options with definitions, at least one example, and not-for lines. Bank examples come from this repository's public history or are written fresh; nothing comes from private repositories, so the policy draft's examples are not copied.
- **One sitting per lens.** The operator reviews, one lens at a time, the lens's policy questions, its Jev questions with what each is for, the outcomes of C5's and C5b's checks for that lens, and the level mappings and curated rule lists C4a to C4c set for the tools that feed it. Examples shown in a sitting come from the corpus's tuning half only. The operator may confirm held-out planted cases and review question wording, but no question, threshold or outcome mapping changes because of an individual held-out result.
- **Approval, enforced.** Each lens's approval is recorded in its bank file with the date and a fingerprint of the approved content. Code refuses a set whose content differs from its approval: the loader saga uses to hand a bank to `jev sweep` and the policy list to builders refuses that lens, and a test fails while any shipped set differs from its approval.
- **Corpus runs.** These files join C2's fingerprinted component list, so once C2's rule is in force, a change to a bank or to the policy list needs a fresh corpus run before it merges.
- **Not questions.** Accessibility and user experience leave code review; their home is `/qa`'s app-interface strategy. "Previous comments" becomes a merge check (C10b).

Depends on C6 (fleet-core + saga: the Jev sweep says where to look in a change) for the bank and condition formats. Each sitting also reviews what C4a to C4c, C5 and C5b set for its lens, so it takes place once those are written. Tuning needs the corpus and harness (K1 to K3).

### Risk

medium
The policy list decides what builders must prove and the banks decide where every reviewer looks, so a gap misses defects quietly; no Jev answer can block, and every lens reports only until the calibration file shows it cleared its marks.

### Out-of-scope / non-goals

- The bank and condition formats, and the sweep itself (C6).
- Per-question thresholds and piece sizes, set on the corpus by K3 (The harness: run the review on the corpus and write the calibration file) and kept in C2's file (saga: the calibration file decides which lenses may block).
- Builder declarations and the declaration check: C11 (saga + agent-launcher: builder declarations and the build-loop review checks). The reviewer's prompt: C8 (saga + agent-launcher: the targeted LLM reviewer).
- Writing the tool mappings and check outcomes the sittings review: C4a to C4c, C5 (saga: pattern checks for the defects we keep hitting) and C5b (saga: the scripted review checks no tool provides).
- Accessibility and user-experience questions; building `/qa`'s app-interface driver.

### Files expected to change

- `plugins/saga/references/question-banks/policy-questions.json` (new)
- `plugins/saga/references/question-banks/security.json` (new)
- `plugins/saga/references/question-banks/correctness.json` (new)
- `plugins/saga/references/question-banks/testing.json` (new)
- `plugins/saga/references/question-banks/architecture-maintainability.json` (new)
- `plugins/saga/scripts/question_banks.py` (new)
- `plugins/saga/references/review-tools.md` and C5's rule files (only where a sitting changes a mapping or an outcome)
- C2's fingerprinted component list, if C2 has landed (proposed in `plugins/saga/scripts/review_calibration.py`)
- `plugins/saga/tests/test_question_banks.py` (new)
- `plugins/saga/CHANGELOG.md`
- `plugins/saga/plugin.json` (and the vendor manifests that repeat the version)

### Tests to add or update

- `plugins/saga/tests/test_question_banks.py` (new) asserts that:
  - each bank passes C6's format check, and each lens has between 10 and 20 questions, with identifiers unique across all four banks;
  - every question has options with definitions, at least one example and at least one not-for line;
  - every question folded from an optional lens names that lens and a switch-on condition in C6's format;
  - no question targets an input the lens tables give to a tool (checked against a fixed list);
  - the policy list holds 30 questions, each naming its lens and its proving test;
  - no text in the list or the banks names a private repository or its issues (a short deny-list, for example `infiquetra-sdlc` and the CAMPPS repository names);
  - each shipped bank's approval matches its current content, and the loader refuses a lens whose content was changed in a temporary copy, or that carries no approval.
- `plugins/saga/tests/test_entrypoints.py` covers the new script's `--help` through its existing discovery.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` ("Lens by lens", Change 5)
- `plugins/saga/skills/code-review/references/lens-execution.md` (today's optional-lens conditions)
- `plugins/fleet-core/references/typesafe.md` (house rule 4: one literal condition per question)
- `plugins/saga/references/review-tools.md` (from C4a: level mappings and curated lists)

### Acceptance criteria

- [ ] The policy list and the four banks exist, and `python3 -m pytest plugins/saga/tests/test_question_banks.py -q --import-mode=importlib` passes.
- [ ] The policy list holds 30 questions in public-safe wording, each with its lens and the proving test it requires.
- [ ] Every lens has 10 to 20 Jev questions, each with options, definitions, examples and not-for lines.
- [ ] Every question folded from an optional lens names its source lens and its switch-on condition in C6's format.
- [ ] No bank asks what a tool or check in the lens tables already answers.
- [ ] Each lens had one sitting covering its policy questions, its Jev questions, C5's and C5b's outcomes and C4a to C4c's mappings and curated lists for that lens, with examples from the tuning half only; each sitting is noted on this issue with its date.
- [ ] Each bank file records its lens's approval date and fingerprint, and the loader refuses a set whose content differs from its approval.
- [ ] `python3 plugins/saga/scripts/question_banks.py --help` exits 0.
- [ ] C2's fingerprinted component list names these files, added here or by C2 if it lands second.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_question_banks.py -q --import-mode=importlib
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 plugins/saga/scripts/question_banks.py --help
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

### Notes / conventions

- For the planning step: the folder, file and script names are proposals; JSON keeps the files readable by fleet-core's standard library when saga passes a bank to `jev sweep`.
- For the planning step: the policy list's fields (for example `id`, `lens`, `group`, `question`, `fails`, `clears`, `proving_test`, `not_for`); a bank question drawn from a policy question names that question's `id`.
- For the planning step: the approval block's keys (for example `approval.date` and `approval.fingerprint`); the fingerprint is a hash of the canonical JSON of the lens's bank and its entries in the policy list, leaving out the approval block itself.
- For the planning step: `question_banks.py approve --lens <lens>` writes the approval after the sitting, run only on the operator's word as noted on this issue; `question_banks.py load` is the loader that refuses a changed set.
- For the planning step: an outcome or mapping the operator changes in a sitting is edited in its own file (`review-tools.md`, or a C5 rule's metadata) in this card's change.
- For the planning step: sitting material shows each item with what it is for and its outcome or mapping, plus corpus examples from the tuning half where the corpus has them (K1, K2); held-out cases are never shown as examples.
