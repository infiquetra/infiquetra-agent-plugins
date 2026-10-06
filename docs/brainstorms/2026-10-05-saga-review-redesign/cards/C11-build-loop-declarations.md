---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga + agent-launcher: builder declarations and the build-loop review checks

### Objective

Builders see the policy questions before they build, and each unit keeps a builder record: per
question, whether it applies and the test that proves it, plus every reason the review reads. The
build loop runs the review tools, our checks and the Jev sweep (TypeSafe's classifier saying where
to look) on each unit's changes. A unit hands off only when a declaration check passes. On the
combined branch, a blocking tool finding in a lens allowed to block, or any secret, stops the run.

### Intent

Today (infiquetra-agent-plugins at origin/main 1f7137d):

- The builder's role lists "the review expectations that will be applied to what you build" as an
  input (`plugins/agent-launcher/roles/implementer.md:78-79`); nothing fills it. Claude Code's
  `saga:worker` type reads that file at call time.
- The implementer and both repair implementers emit the lifecycle's implementation result, and each
  prompt must name its required fields (`plugins/agent-launcher/tests/test_roles_library.py:863`,
  against the vendored `roles/lifecycle-snapshot.json`). No field holds declarations.
- `/work` gives a build subagent only the unit's plan fields
  (`plugins/saga/skills/work/references/execution-strategy.md:71-82`), and orchestrate's notes on a
  `/saga:work` task say nothing about review questions
  (`plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py:119-166`, 2967-2994).
- A unit iteration of `plugins/saga/scripts/build_loop.py` runs the profile's baseline and the
  plan's unit checks (lines 599-669); a green one records `handed_to_code_review` (672-702). The
  combined pass runs the baseline, deploy, test and teardown (1172-1200), and `--handoff` admits a
  revision to code review only after a green pass (1532-1577). Neither runs a sweep.

What changes (plan.md, Change 8 "Build loop" and the design rule on builder declarations):

- **The questions.** Builders declare against the policy's 30 questions, which C7 publishes as a
  public list in saga. They reach builders through agent-launcher's implementer and both
  repair-implementer roles, `/work`'s dispatch and orchestrate's dispatch of a `/saga:work` unit.
- **The builder record.** One per unit, kept in the run record, in C1's schema (also the format of a
  corpus case's builder record). It holds each question's declaration (applies or not, and the
  proving test) and every reason: coverage gaps, surviving mutants, scanner false positives,
  "unaffected" marks, pattern-check reasons and the explanation of each where-to-look item. A
  repair implementer declares too and updates the record. The implementation result carries the
  record in the field X1a adds, and the three implementer prompts name that field.
- **The declaration check.** A script that needs no run: given a builder record and a revision, it
  fails while any question lacks a declaration or any named test is missing or failing at that
  revision. K2 runs it on every corpus case.
- **The unit loop.** Each iteration also runs C4a's runner (the tools, plus C5's pattern checks and
  C5b's scripted checks registered in it) and the sweep (C6, over C7's banks) on the unit's
  changes, so the builder sees the where-to-look list first and fixes or explains each item. It
  stays not green (exit 4, the loop's "not yet" code) until the declaration check passes.
- **The combined pass** reruns the tools on the whole branch. A blocking tool finding fails it only
  in a lens the calibration file lets block in that language (C2); a secret in the diff always
  fails it. Then `--handoff` refuses, and the review's LLM (large language model) step never starts.

Depends on C1 (saga: review records, validation and the A–F formula), C2 (saga: the calibration
file decides which lenses may block), C4a (saga: build-loop tool framework reporting only what a
change introduces), C7 (saga: policy questions and question banks
for the four lenses, reviewed by the operator) and X1a (Record saga's new review model and its
contracts in the lifecycle repository).

### Risk

medium
It changes when a unit hands off and when review starts; a mistake stalls a run visibly.

### Out-of-scope / non-goals

- The tool runner and adapters (C4a to C4c), our checks (C5, C5b), the sweep (C6), the questions
  and banks (C7), the record's schema (C1) and the lifecycle's contract field (X1a).
- The review command reading the record (C10a); corpus records (K2); merge screens (C13, C14).

### Files expected to change

- `plugins/agent-launcher/roles/implementer.md`
- `plugins/agent-launcher/roles/standard-repair-implementer.md`
- `plugins/agent-launcher/roles/expert-repair-implementer.md`
- `plugins/agent-launcher/roles/lifecycle-snapshot.json`
- `plugins/saga/skills/work/SKILL.md`
- `plugins/saga/skills/work/references/execution-strategy.md`
- `plugins/saga/scripts/build_loop.py`
- `plugins/saga/scripts/builder_record.py` (new)
- `plugins/saga/references/mechanical-baseline.md`
- `plugins/saga/references/run-record.md`
- `plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py`
- `plugins/saga/CHANGELOG.md`
- `plugins/agent-launcher/CHANGELOG.md`
- `plugins/orchestrate/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_builder_record.py` (new), no network: a record missing a question, or
  naming a test absent or failing at the revision, fails the check and names the question; a
  complete record with passing tests passes with no run record present; a record C1's validator
  rejects is refused and nothing is stored; a repair implementer's update keeps earlier entries.
  `test_entrypoints.py` checks the new script answers `--help` with no credentials.
- `plugins/saga/tests/test_build_loop.py`, with fakes: a failing declaration check keeps the
  iteration not green (exit 4); a passing one records `handed_to_code_review`; an iteration records
  tool, check and sweep results; on the combined pass a blocking tool finding in a lens allowed to
  block fails it, `--handoff` refuses and no review step is called, the same finding in a
  report-only lens does not, and a secret fails it in any lens; key-set tests cover the new keys.
- `plugins/agent-launcher/tests/test_roles_library.py`: the three implementer prompts name the
  policy questions, the declaration duty and the builder-record field, against the new snapshot.
- `plugins/orchestrate/tests/test_orchestrate_task_dispatch.py`: a `/saga:work` unit's task carries
  the policy questions, or where to read them.
- `plugins/saga/tests/test_role_agent_types.py`: the worker's prompt is still the role file's body.

### Context library links

- `plugins/saga/references/mechanical-baseline.md` (the exit criterion, the combined pass, the gate)
- `plugins/agent-launcher/roles/README.md` (the lifecycle snapshot is regenerated, never edited)
- infiquetra-context-library `docs/testing/quality-gates.md` (the CI standard that X2 extends)

### Acceptance criteria

- [ ] `python3 -m pytest plugins/saga/tests/test_build_loop.py -q --import-mode=importlib` passes,
      and so does the same command on `test_builder_record.py`.
- [ ] A unit with an undeclared question, or a named test missing or failing, is not handed off and
      the question is named; `python3 plugins/saga/scripts/builder_record.py check` gives the same
      verdict on a record file with no run record present, as K2 calls it.
- [ ] Each unit's builder record sits in the run record and passes C1's validator; a repair
      implementer's update is kept.
- [ ] A blocking tool finding in a lens allowed to block, or a secret in the diff, makes
      `build_loop.py --handoff` refuse; a blocking finding in a report-only lens does not.
- [ ] The three implementer roles, `/work`'s dispatch and orchestrate's `/saga:work` task carry the
      questions, and the roles name the builder-record field.
- [ ] `build_loop.py --dry-run` lists the tools, checks, sweep and declarations an iteration needs.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/agent-launcher/tests plugins/orchestrate/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: names are proposals (`builder_record.py`, with `write` and `check`); the
  run-record key; how the builder writes its record (a subcommand that validates and stores it
  under the run record's lock, or a file the loop reads); and the check's inputs.
- For the planning step: read the policy-question list from the path C7 publishes; carry it into
  each dispatch route, repairs included, by path or by content.
- For the planning step: regenerate `lifecycle-snapshot.json` at the lifecycle revision where X1a
  landed, by the roles README's method; whichever of C8, C11 and C12 lands first does it.
- For the planning step: the gate reads C1's outcome on each tool finding and C2's per-lens,
  per-language verdict; the secret rule keys on the secret scanner's (gitleaks) findings alone.
