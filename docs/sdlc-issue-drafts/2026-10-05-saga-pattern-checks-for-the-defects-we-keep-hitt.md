---
title: saga: pattern checks for the defects we keep hitting
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

# saga: pattern checks for the defects we keep hitting

### Objective

Saga carries its own Semgrep rules for the six recurring defects the correctness lens names. Each rule records the harm its defect does and blocks merge unless the builder records a reason for the match. Each comes with Semgrep rule tests that mark the lines that must match and the lines that must not, and this repository's CI installs the pinned Semgrep so those tests run on every pull request. C4a's Semgrep adapter runs the rules on every change, so a deterministic check reports these defects instead of a reviewer arguing them.

### Intent

This card implements plan.md, Change 4 ("Our own checks for the bugs we keep hitting"), for the six pattern checks in the correctness lens table. That table's row reads: "One of our pattern checks fires (...) | our checks | The result fixed when the check was written: blocks or fix later". The lens notes add: "Each pattern check carries its own consequence, so review never decides it."

What is true on origin/main today:

- Saga has no pattern rules. Semgrep is only named, and the build loop's check runner reports it as "not configured" (`plugins/saga/scripts/build_loop.py:159-162`; `plugins/saga/references/mechanical-baseline.md:97-105`).
- This repository's CI installs no Semgrep. Its plugin-tests job installs only `requirements-plugin-tests.txt` (`.github/workflows/ci.yml:63-66`), which does not list it.
- The nearest existing guards are saga's own tests for one repository-specific write path: no plugin writes a project-board field except through Mission Control (`plugins/saga/tests/test_saga_no_direct_write.py`, `plugins/saga/tests/test_saga_single_writer_guard.py`).
- The lifecycle repository seeds one of these defects as a review fixture (infiquetra-sdlc `config/lens-fixtures/correctness/naive_datetime_compare.py`).

What changes: one Semgrep rule per defect, in a rules folder at the package root. Each rule carries the harm below, from C1's closed consequence list, and blocks merge unless the builder record gives a reason for that match.

| Defect, as plan.md's correctness table names it | Harm it encodes | Rule file |
|---|---|---|
| A release sharing a cleanup block | two holders of one exclusive thing | `release-shares-cleanup-block.yaml` |
| A swallowed error | a wrong result reported as success | `swallowed-error.yaml` |
| A silent skip | a wrong result reported as success | `silent-skip.yaml` |
| A write that skips the shared update path | data lost or corrupted | `write-skips-shared-update-path.yaml` |
| A naive time comparison | a wrong result reported as success | `naive-time-comparison.yaml` |
| Money stored as floating point | money or resources wrongly moved | `money-as-floating-point.yaml` |

The first three are Change 4's "a lock or lease not released on every exit path", "success reported after a failure" and "an item dropped without a trace". The first rule catches a lock or lease release that shares a cleanup block with another step, so a failure in that step skips the release.

Each rule:

- carries metadata naming the correctness lens, the plan's defect, a one-sentence statement for the finding, its harm and its outcome;
- covers at least every language in which its defect has occurred in our fix history, with one Semgrep rule-test file per language, marked with `ruleid:` comments on lines that must match and `ok:` comments on lines that must not;
- runs through C4a's Semgrep adapter, so a match on a changed line becomes a correctness finding that cites C1's identifier for the "One of our pattern checks fires" row, and a match elsewhere is dropped;
- counts as one of "our checks" in C2's fingerprint: the rules folder joins C2's fingerprinted component list, in this card or in C2's, whichever lands second.

**The shared update path** differs per repository. This card owns a repository-profile key that names a repository's shared update paths, and the rule reads it. It adds the matching repository question to `/saga:setup` through the mechanism C3 provides for other cards' questions, so setup asks for the paths when the profile has none. Without the key, the rule runs degraded: C4a records a degraded input, and nothing the rule reports can block on its own.

**CI.** This card makes the plugin-tests job install Semgrep at the version pinned in C4a's default tool list, so the rule tests run on every pull request instead of skipping.

The operator reviews these harms and outcomes in the correctness lens's sitting with the question banks (C7, saga: policy questions and question banks for the four lenses, reviewed by the operator).

Depends on C1 (saga: review records, validation and the A–F formula) for the finding record, the closed consequence list and the builder record; C3 (saga: /saga:setup checks and prepares the machine and the repository) for the mechanism that registers the repository question; and C4a (saga: build-loop tool framework reporting only what a change introduces) for the Semgrep adapter, the changed-line filter and the default tool list.

### Risk

medium
A rule that matches correct code would block merges once the correctness lens clears calibration; the rule tests pin both directions, a builder can record a reason for a false match, and until calibration every lens only reports.

### Out-of-scope / non-goals

- The changed-name search for "a reader of a changed name left behind" (also in Change 4): C5b (saga: the scripted review checks no tool provides).
- Running Semgrep, the changed-line filter, the security rule packs and Semgrep's default version: C4a. The setup mechanism itself, installing Semgrep on a machine and pinning it in a profile: C3.
- The seeded corpus cases each rule needs (Change 4: "Each rule comes with seeded positive and negative cases in the corpus"): K1 (Corpus repository, case format and cases from our fix history) and K2 (Planted defects, builder records and public reference sets).
- The fingerprint check itself: C2 (saga: the calibration file decides which lenses may block). Sweep questions about the same defects, and the operator's sitting: C7.
- Capturing the builder's reasons: C11 (saga + agent-launcher: builder declarations and the build-loop review checks).
- Running Semgrep in other repositories' CI: X2 (CI standard: the pinned review tools per language as a required check).

### Files expected to change

- `plugins/saga/references/semgrep/release-shares-cleanup-block.yaml` (new)
- `plugins/saga/references/semgrep/swallowed-error.yaml` (new)
- `plugins/saga/references/semgrep/silent-skip.yaml` (new)
- `plugins/saga/references/semgrep/write-skips-shared-update-path.yaml` (new)
- `plugins/saga/references/semgrep/naive-time-comparison.yaml` (new)
- `plugins/saga/references/semgrep/money-as-floating-point.yaml` (new)
- `plugins/saga/references/semgrep/` rule-test files, one per rule and language (new)
- `plugins/saga/scripts/review_adapters_all_languages.py` (C4a's Semgrep adapter: reads the shared update paths from the profile, and writes the degraded input without them)
- The repository-question registration C3's setup reads, in the file C3's planning step names (the shared-update-path key and its wording)
- `plugins/saga/references/review-tools.md`
- `plugins/saga/references/repository-profile.md` (the shared-update-path key)
- `requirements-plugin-tests.txt` (Semgrep at its pinned version)
- `.github/workflows/ci.yml` (only if Semgrep needs an install step of its own)
- C2's fingerprinted component list, if C2 has landed (proposed in `plugins/saga/scripts/review_calibration.py`)
- `plugins/saga/tests/test_pattern_checks.py` (new)
- `plugins/saga/tests/fixtures/review_tools/` (recorded Semgrep output for each rule)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_pattern_checks.py` (new), in four parts:
  - Without Semgrep: each rule file parses with PyYAML and has an id, a message, its languages, and metadata naming the correctness lens, the plan's defect, the harm the table above gives it and the outcome "blocks unless the builder records a reason". Each language a rule lists has a test file with at least one `ruleid:` line and one `ok:` line. The Semgrep version CI installs equals the pin in C4a's default tool list.
  - With Semgrep at its pinned version: `semgrep --test` over the rules folder passes, with usage metrics and the version check off, so no network call is made. Without Semgrep at the pin, the test skips and names the version it found.
  - Through C4a's Semgrep adapter: recorded output for each rule becomes a correctness finding with that rule's harm and passes C1's validator. Through C1's formula it blocks, and with a reason in the builder record it does not. A match on an unchanged line yields nothing. With no shared-update-path key in the profile, that rule appears as a degraded input.
  - Through C3's mechanism: the shared-update-path question is registered with its key and wording, and setup run on a fixture profile without the key asks it and writes the answer under the key, keeping every other key.

### Context library links

- infiquetra-sdlc `config/lens-fixtures/correctness/naive_datetime_compare.py` (a seeded naive time comparison)
- `plugins/saga/tests/test_saga_no_direct_write.py` and `plugins/saga/tests/test_saga_single_writer_guard.py` (saga's own guards for one shared write path)
- `plugins/saga/references/review-tools.md` (from C4a: the adapter interface and outcome table)
- `plugins/saga/references/repository-profile.md`

### Acceptance criteria

- [ ] Six rules exist, one per defect in the table, each with its harm and the outcome "blocks unless the builder records a reason" in its metadata.
- [ ] Each rule has a rule-test file for every language the planning step listed for it from our fix history.
- [ ] `SEMGREP_ENABLE_VERSION_CHECK=0 semgrep --test --metrics=off plugins/saga/references/semgrep/` passes with Semgrep at its pinned version.
- [ ] CI's plugin-tests job installs Semgrep at the pinned version, and the Semgrep part of `test_pattern_checks.py` runs there instead of skipping.
- [ ] `python3 -m pytest plugins/saga/tests/test_pattern_checks.py -q --import-mode=importlib` passes.
- [ ] Through C4a, a rule firing on a changed line yields a correctness finding with its harm, which blocks unless the builder record gives a reason; a match outside the change yields nothing.
- [ ] The shared-update-path rule reads the profile key, and without the key it is a degraded input.
- [ ] `/saga:setup` asks for the shared update paths through C3's mechanism when the profile has none, and writes the answer under the key.
- [ ] `plugins/saga/references/review-tools.md` lists the six rules with their harm, outcome and languages, and `repository-profile.md` documents the key.
- [ ] C2's fingerprinted component list names the rules folder, added here or by C2 if it lands second.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_pattern_checks.py -q --import-mode=importlib
SEMGREP_ENABLE_VERSION_CHECK=0 semgrep --test --metrics=off plugins/saga/references/semgrep/
```

### Notes / conventions

- For the planning step: each rule's languages start from the languages in which its defect occurred in our fix history, and `review-tools.md` lists them. Rule-test code is written fresh, never copied from a private repository.
- For the planning step: rule identifiers follow the file names, and the metadata keys are proposals (`lens`, `defect`, `harm`, `outcome`, and `row` for C1's row identifier). The finding carries the rule identifier and harm, never a severity, which C1's validator refuses; C1's formula holds each pattern check's outcome by rule identifier, and a test keeps it in step with the rule's metadata.
- For the planning step: the profile key is a proposal (`review.shared_update_paths`), holding function, method or module names per language, with the question's wording registered beside it through C3's mechanism. C4a's adapter fills the rule's template with the names before running Semgrep (for example through `metavariable-regex`) and writes the degraded input when the key is absent.
- For the planning step: in this repository, one shared update path is the project-board write through Mission Control, which `test_saga_no_direct_write.py` and `test_saga_single_writer_guard.py` guard today; this repository's own profile (issue #114) is the first to name it.
- For the planning step: install Semgrep in CI through `requirements-plugin-tests.txt`, as the comment at `.github/workflows/ci.yml:58-62` asks, unless its dependencies clash with that file's pins; then a step in the plugin-tests job installs it into an environment of its own. Tests and the adapter run Semgrep with `--metrics=off` and `SEMGREP_ENABLE_VERSION_CHECK=0`.
- For the planning step: a reason for a pattern-check match sits in the builder record against C1's finding identity, so it survives line shifts between rounds.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C5-pattern-checks.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C5-pattern-checks.md
- Source type: brainstorm
- Source title: saga: pattern checks for the defects we keep hitting

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/154
- Number: 154
- Created at: 2026-10-05T19:10:55.960120+00:00
