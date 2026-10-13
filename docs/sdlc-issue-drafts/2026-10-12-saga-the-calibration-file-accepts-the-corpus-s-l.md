---
title: saga: the calibration file accepts the corpus's languages and records the measured reviewer's configuration
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

# saga: the calibration file accepts the corpus's languages and records the measured reviewer's configuration

### Objective

Let `plugins/saga/references/review-calibration.json` record what saga-review-corpus#3's harness measures: a verdict
for every language the corpus's cells cover, and the configuration of whichever reviewer the bake-off chose. Today
saga's schema rejects both, so the harness refuses to write the file.

### Intent

The corpus harness (saga-review-corpus#3, card K3 of #147) found two refusals in saga's calibration schema:

- **Languages.** `review_calibration._lens_problems` accepts only languages in `review_formula.LANGUAGES`, which has
  `github-workflows` (plural) and no `cdk` or `cloudformation`. The corpus's cells use `cdk`, `cloudformation` and
  `github-workflow`. The harness must not map one language onto another, so saga has to own the answer.
- **Reviewer configuration.** `document_problems` requires `reviewer_configuration` to be a 64-hex string or null and
  rejects other top-level keys. After the bake-off the measured reviewer may be Grok or Muse, which
  `targeted-reviewer-launch.json` (Claude, Opus, high) does not describe, and the card requires vendor, model,
  prompt fingerprint and configuration fingerprint, with the components a comparison cleared beside them.

### Out-of-scope / non-goals

- Renaming the corpus's language ids: the corpus's case files and its confirmed cells file stay as approved.
- The corpus harness itself, and the bake-off.
- Changing any threshold, question or outcome mapping.

### Files expected to change

- plugins/saga/scripts/review_formula.py
- plugins/saga/scripts/review_calibration.py
- plugins/saga/scripts/review_dataset.py
- plugins/saga/tests/test_review_calibration.py
- plugins/saga/tests/test_review_formula.py
- plugins/saga/references/review-calibration.md
- plugins/saga/CHANGELOG.md

### Tests to add or update

- `cdk` and `cloudformation` are accepted languages, and the workflow spelling is settled once: saga either renames
  its id to `github-workflow` everywhere it is used, or keeps `github-workflows` and owns a documented alias table that
  `document_problems`, `_lens_problems` and `may_block` all read. A test pins whichever is chosen, and a test proves
  `may_block` answers for every corpus language id.
- `reviewer_configuration` accepts the object `{vendor, model, effort, prompt_sha256, configuration_fingerprint,
  second, cleared_components}` with each field validated, still accepts null for a file with no recorded run, and
  rejects a malformed object field by field. Saga's review-time comparison reads `configuration_fingerprint`.
- `review_calibration.fingerprint(root)` returns the sha256 of every `COMPONENTS` path through `locate`, and the
  existing test helper uses it.
- `review_dataset.load_corpus` reads a case's `id` when `case_id` is absent.

### Context library links

_none_

### Acceptance criteria

- [ ] A calibration file holding verdicts for `cdk`, `cloudformation` and the corpus's workflow id validates, and
  `may_block` answers for each: `python3 -m pytest plugins/saga/tests/test_review_calibration.py` covers it.
- [ ] A calibration file whose `reviewer_configuration` is the documented object validates, a malformed one is
  refused with the field named, and a null one still validates.
- [ ] `python3 scripts/check_repo.py` passes, including the committed calibration file's fingerprint rule.

### Verification

```bash
python3 -m pytest plugins/saga/tests/test_review_calibration.py plugins/saga/tests/test_review_formula.py
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
claude plugin validate --strict plugins/saga
git diff --check
```

### Risk

medium

The calibration file decides which review lenses may block a merge, so a schema change must not let a malformed file
validate.

### Notes / conventions

Part of #147; it blocks saga-review-corpus#3's calibration file (AC-6). Do not bump the saga version; that belongs to
#147's saga release step.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-11-saga-calibration-corpus-schema/enhancement.md

### Source context
- Source: docs/brainstorms/2026-10-11-saga-calibration-corpus-schema/enhancement.md
- Source type: brainstorm
- Source title: saga: the calibration file accepts the corpus's languages and records the measured reviewer's configuration

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/224
- Number: 224
- Created at: 2026-10-12T00:35:44.373029+00:00
