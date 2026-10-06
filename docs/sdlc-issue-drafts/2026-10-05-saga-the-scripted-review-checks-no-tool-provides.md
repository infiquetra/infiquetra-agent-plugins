---
title: saga: the scripted review checks no tool provides
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

# saga: the scripted review checks no tool provides

### Objective

Saga gains five scripted checks for the lens-table rows that no off-the-shelf tool answers: two test runs that show whether the change's new tests test it, a check for new tests CI skipped or never collected, a search for machine-specific values, a search for readers of a renamed or removed name, and a check for workflow states with no way out. Each plugs into C4a's runner, reports only what the change introduces, and maps to the outcome its row in plan.md's lens tables gives.

### Intent

This card implements five rows of plan.md's lens tables ("Lens by lens") and the part of Change 4 that names "a reader of a changed name left behind"; Change 3 lists "a search for every reader of a changed name" among the correctness lens's tools.

What is true on origin/main today:

- The build loop runs the profile's commands and keeps an exit status and the last line of output (`plugins/saga/scripts/build_loop.py:448-461`). The release step reads only each CI check's conclusion on the pull request (`plugins/saga/scripts/release_step.py:153-164`). Nothing in saga runs a change's new tests against the code before the change, reads which tests a CI run skipped, searches for readers of a renamed name, or checks a workflow definition.
- This repository's own `scripts/check_repo.py` refuses a real home directory in shipped files (`check_machine_specific_paths`, `scripts/check_repo.py:1011-1050`, with its pattern at `:267` and its inert placeholder names at `:279`). That covers one kind of machine-specific value in one repository. Nothing covers user names, host names, account IDs or URLs, or other repositories.
- The lifecycle repository seeds a machine-specific path as a review fixture (infiquetra-sdlc `config/lens-fixtures/architecture-maintainability/hardcoded_environment_path.py`).
- This repository's CI runs pytest in quiet mode (`.github/workflows/ci.yml:69`), so its log does not name each test it ran.

What changes: one script holding five checks. Each is an adapter on C4a's interface, registered in C4a's runner, and reads the change through C4a's diff reader. Outcomes, from plan.md:

| Check | Lens-table row in plan.md | Outcome |
|---|---|---|
| The two test runs | Testing: "A new test that passes on the code before the change, or a regression test that passes before its fix" | blocks unless the builder records a reason |
| Tests CI skipped | Testing: "A new test CI skipped or never collected, with no reason" | blocks unless a reason is given, as a skip reason the log shows or in the builder record |
| Machine-specific value search | Architecture: "A machine-specific value (absolute path, home directory, user name, hostname, account ID, URL) that doesn't come from configuration" | the reviewer judges each hit; a confirmed hit is fix later, and blocks when C4a's relocated test run fails |
| Changed-name search | Correctness: "A mention from the changed-name search the builder neither updated nor marked 'unaffected'" | blocks; a mention in a document is fix later at most |
| Workflow graph check | Correctness: "A workflow state with no way out, where the workflow is data" | blocks |

The two testing rows follow the testing lens's rule, "Every gap blocks unless the builder records a reason". The changed-name outcome follows the correctness lens's note: "documents and agent instructions are included, and a stale document is fix later at most".

1. **The two test runs.** The new tests are those present at head and absent at base. The check runs them at head, then against the code at base with the head's test files in place. A new test that passes on the code before the change does not test it. The same run catches a regression test that passes before its fix, because the base is the code before the fix: the pull request's base, or in a later round the previous round's head.
2. **Tests CI skipped.** For each new test, the check reads the finished CI run for the head commit. A new test the log shows as skipped, or never shows at all, needs a reason. With no finished run for the head commit, or a log that does not name each test, the row is degraded.
3. **Machine-specific value search.** On the lines the change adds, the check finds absolute paths, home directories, user names, host names, account IDs and URLs, leaving out inert placeholders. Each hit goes to the LLM (large language model) reviewer, C8, which confirms it with a finding or clears it with a reason: plan.md's "search script, then the LLM judges each hit".
4. **Changed-name search.** The check finds each name the change renames or removes, then searches the repository at head for mentions outside the change: code, tests, documents and agent instructions. Each mention the builder record does not mark "unaffected" is a finding. Python names come from the standard library's parser. Where a language cannot be parsed, the check compares removed and added lines as text and marks its results degraded.
5. **Workflow graph check.** Where the change touches a workflow defined as data (states and transitions in a file), the check builds the graph and reports each state from which no end state can be reached, kept only when new at head.

Every result becomes C1's records, citing C1's row identifier, and passes C1's validator. C4a's rules apply: no shell, a timeout per check, and a missing program, timeout or unsupported runner gives a degraded input that cannot block on its own. The operator reviews these outcomes in the testing, architecture and correctness sittings of C7 (saga: policy questions and question banks for the four lenses, reviewed by the operator). The script joins C2's fingerprinted component list, in this card or in C2's (saga: the calibration file decides which lenses may block), whichever lands second.

Depends on C1 (saga: review records, validation and the A–F formula) for the records, the row identifiers, the builder record and the formula, and C4a (saga: build-loop tool framework reporting only what a change introduces) for the runner, the adapter interface, the diff reader, the base checkout and the relocated test run.

### Risk

medium
A check that misfires would block correct changes once its lens clears calibration; each check is pinned by tests in both directions, the builder can record reasons and "unaffected" marks, and until calibration every lens only reports.

### Out-of-scope / non-goals

- The runner, the changed-line filter, the base and head comparison, the relocated test run and degraded entries: C4a.
- Judging the machine-specific hits, disputing "unaffected" marks, and answering a degraded row in a check's place: C8 (saga + agent-launcher: the targeted LLM reviewer). Putting the hits in the reviewer's packet: C10a (saga: one review command from change to records).
- The builder record's schema: C1. Capturing reasons and "unaffected" marks, and running these checks in each unit's build loop: C11 (saga + agent-launcher: builder declarations and the build-loop review checks).
- Saga's Semgrep rules: C5 (saga: pattern checks for the defects we keep hitting). The sweep: C6 (fleet-core + saga: the Jev sweep says where to look in a change).
- Seeded corpus cases for each check: K1 (Corpus repository, case format and cases from our fix history) and K2 (Planted defects, builder records and public reference sets).
- Changing any repository's CI so its log names each test.

### Files expected to change

- `plugins/saga/scripts/review_checks.py` (new)
- `plugins/saga/references/review-tools.md` (the five checks, their rows and outcomes)
- `plugins/saga/references/review-tools.yaml` (only if C4a's runner registers adapters there)
- C2's fingerprinted component list, if C2 has landed (proposed in `plugins/saga/scripts/review_calibration.py`)
- `plugins/saga/tests/test_review_check_two_runs.py` (new)
- `plugins/saga/tests/test_review_check_ci_skips.py` (new)
- `plugins/saga/tests/test_review_check_machine_values.py` (new)
- `plugins/saga/tests/test_review_check_changed_names.py` (new)
- `plugins/saga/tests/test_review_check_workflow_graph.py` (new)
- `plugins/saga/tests/fixtures/review_checks/` (new: recorded CI logs and workflow definitions, with inert values)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

Each runs on a temporary git repository with a base and a head commit, makes no network call, and passes every record through C1's validator.

- `test_review_check_two_runs.py`: a new test that fails at base and passes at head yields nothing; one that passes at base yields a blocking testing finding, which a reason in the builder record clears through C1's formula; with base set to a previous round's head, a regression test that passes before the repair is reported; a runner that cannot list or select tests gives a degraded input.
- `test_review_check_ci_skips.py` (recorded logs, `gh` faked): a new test skipped without a reason, and one the log never shows, each yield a blocking finding; a skip reason in the log, or a reason in the builder record, clears it; no finished run for the head commit, and a quiet log that names no test, each give a degraded input.
- `test_review_check_machine_values.py` (the machine's own user name and host name injected as fake values): an added line with each kind of value yields one hit for the reviewer; the same values on unchanged lines, and inert placeholders, yield nothing; a confirmed hit is fix later, and blocks when the relocated test run failed.
- `test_review_check_changed_names.py`: a renamed Python function with a caller left in an untouched file yields a blocking correctness finding, and nothing once the builder record marks it "unaffected"; a mention in a document is fix later, and one in an agent instruction blocks; a mention on a line the change edited yields nothing; a language with no parser gives degraded results.
- `test_review_check_workflow_graph.py`: an added state with no outgoing transition, and an added loop with no exit, each yield a blocking finding; end states are never reported; a dead end already present at base yields nothing.
- `plugins/saga/tests/test_entrypoints.py` covers the new script's `--help` through its existing discovery.

### Context library links

- `docs/brainstorms/2026-10-05-saga-review-redesign/plan.md` ("Lens by lens": the five rows)
- `scripts/check_repo.py` (`check_machine_specific_paths`, this repository's own home-directory check)
- infiquetra-sdlc `config/lens-fixtures/architecture-maintainability/hardcoded_environment_path.py` (a seeded machine-specific path)
- `plugins/saga/references/review-tools.md` (from C4a: the adapter interface and outcome table)

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/review_checks.py --help` exits 0 and names the five checks.
- [ ] Each check runs through C4a's runner from a repository, base, head, profile and output directory, with no run record.
- [ ] Each check maps to the row and outcome in the table above, and every record passes C1's validator.
- [ ] A new test that passes on the code before the change, or before its fix, blocks unless the builder records a reason.
- [ ] A new test CI skipped or never collected blocks unless a reason is given; with no finished CI run, or a log that names no test, the row is degraded.
- [ ] Each machine-specific hit reaches the reviewer to confirm or clear; a confirmed hit is fix later, and blocks when the relocated test run failed.
- [ ] A mention of a renamed or removed name outside the change blocks unless marked "unaffected", and a mention in a document is fix later at most.
- [ ] A workflow state the change adds with no way out blocks.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network access.
- [ ] `review-tools.md` documents the five checks, and C2's fingerprinted component list names the script, added here or by C2 if it lands second.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 plugins/saga/scripts/review_checks.py --help
```

### Notes / conventions

- For the planning step: names are proposals (`review_checks.py` with one subcommand per check, and the test files). Register the checks with C4a's runner the way C4a's planning settles.
- For the planning step: find the new tests with each runner's own listing at base and head (for example `pytest --collect-only -q`, `cargo test -- --list`, `swift test list`), and run them with the language's test command from C4a's profile block. Build the base run on C4a's temporary checkout of the base with the head's test files copied in; a test that cannot import there counts as failing at base. A runner with no way to list or select tests runs degraded.
- For the planning step: read the CI result through `gh run list --commit <head>` and `gh run view --log`, or through a per-test report the run uploads (for example a JUnit report in XML, the Extensible Markup Language). Because this repository's quiet pytest log names no test, the row stays degraded here until its CI reports each test.
- For the planning step: the patterns for machine-specific values (Unix-style and Windows absolute paths, home directories, an Amazon Web Services account ID's twelve digits, `http` and `https` URLs), plus the machine's own user name and host name read at run time; the inert placeholders start from `INERT_HOME_DIRECTORY_USERS` in `scripts/check_repo.py` and documentation hosts such as `example.com`.
- For the planning step: hand each machine-specific hit to the reviewer as one of C1's where-to-look items, with this search as its classifier and a probability of 1, so the builder explains it in the build loop (C11) and C8's check that no item goes unanswered covers it. These hits are not part of the sweep's 30-item list.
- For the planning step: the kinds of names the changed-name search covers start from the stale-reader defects in our fix history (definitions, files and modules, command-line flags, configuration keys). Outside Python, use the parser in the row C6 adds to the default tool list, where it is installed. Mentions sit on unchanged lines, so the adapter reports in C4a's whole-project mode.
- For the planning step: list which paths count as agent instructions (skills, commands, agent and role files, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) and which as documents.
- For the planning step: the workflow formats the graph check reads start from the workflows our repositories define as data; for each format, name how it marks its start state, its end states and its transitions.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C5b-scripted-checks.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C5b-scripted-checks.md
- Source type: brainstorm
- Source title: saga: the scripted review checks no tool provides

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/155
- Number: 155
- Created at: 2026-10-05T19:11:17.629174+00:00
