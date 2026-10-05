---
title: saga: build-loop tool framework reporting only what a change introduces
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

# saga: build-loop tool framework reporting only what a change introduces

### Objective

One saga script runs the pinned review tools on a change and reports only what the change introduces, as finding and measurement records. It reads the change through one diff reader, filters line findings to the changed lines, and compares base and head runs for whole-project results and for every type checker. It reads changed-line coverage from the three standard report formats, runs the tests once more from a different working directory and home directory, and marks every missing tool, version other than the pin and known gap as degraded. It holds the outcome rules for tool findings that no lens-table row names, and ships with the tools every language gets (Semgrep, gitleaks, osv-scanner, jscpd, lizard); C4b and C4c plug the language adapters into it.

### Intent

This card implements plan.md, Change 3 ("Tools per lens, reporting only what the change introduces") and Change 2's "How the tools run", with the tool outcomes the operator decided on 5 October 2026.

What is true on origin/main today:

- The build loop's check runner (`plugins/saga/scripts/build_loop.py`) runs each mechanical-baseline command as an argument vector, never through a shell (`build_loop.py:448-461`). It keeps an exit status and the last line of output (`build_loop.py:460-461`, `:486-531`). It reads no tool's findings, filters nothing to the change, and measures no coverage.
- It maps commands to four Python checks (`build_loop.py:136-157`) and reports pip-audit, gitleaks, detect-secrets and semgrep as "not configured" (`build_loop.py:159-162`, `:409-434`).
- bandit stayed out of the baseline because its findings on existing code would stop the loop ever going green. Scoping it to the unit's own change was the alternative not taken (`plugins/saga/references/mechanical-baseline.md:74-95`).
- Every check runs from the repository root (`mechanical-baseline.md:481-485`). Nothing runs the tests from another directory or home directory.

What changes:

1. **Runner.** A script takes the repository, a base commit, a head commit, the profile and an output directory. It needs no run record and no session, so the build loop (C11), the review command (C10a) and the corpus harness (K3) can all call it. It keeps the build loop's rules: no shell, a timeout per tool, and a missing program, timeout or unparseable command is never a pass and never a fail.
2. **Default tool list and pins.** A YAML (YAML Ain't Markup Language) file with one row per tool: its languages, the lens it serves, its default version and rule set, how to read the installed version, and how to install it. This card sets the format and adds the every-language rows; C4b and C4c add their languages' rows, C3 adds saga's own tools and C6 the sweep's parser. The build loop takes its checks from this list instead of the lifecycle repository's `mechanical_checks` map that `mechanical-baseline.md` cites, which X1b retires. The profile pins each tool's version and rule set in a block this card defines and C3 writes. The runner runs each tool at its pin, falls back to the list's default where nothing is pinned, and records the version it ran. A tool installed at a version other than its pin still runs, and its results are marked degraded.
3. **Adapter interface.** Each adapter names its tool, the files it applies to, how to invoke it and how to read its machine-readable output. Each result cites the identifier C1 gives the lens-table row it answers, or one of the rules in item 6. The adapter says whether its results sit on lines (changed-line filter) or describe the whole project (base and head comparison); a type checker is always whole-project. In the build loop a formatter adapter runs in its fixing mode and produces no review record (plan.md, Architecture lens). C5b's scripted checks plug into the same interface.
4. **One diff reader.** It reads the diff between base and head into changed files, hunks, and added or modified lines. The changed-line filter and the coverage adapter use it, and C6's sweep cuts its pieces with it, so every part of the review reads the change the same way. The changed-line filter keeps a finding only when it lies on a line the change added or modified; a file renamed without edits introduces nothing.
5. **One base and head comparison.** The tool runs on a temporary checkout of the base and on the head, and only results present at head and absent at base are kept. Dependency audits and duplication use it, and so does every type checker: a type error the change causes anywhere, including in a file the change did not touch, blocks (Correctness: "A type error the change introduces"). A whole-project result may omit the line, as C1's location rule allows.
6. **Outcomes for tool findings no lens-table row names.** This card adds these rules to C1's fixed rules:
   - A linter or checker finding at the tool's own error level blocks; its warnings are fix later; its style and information messages are notes. For a tool with no levels, the adapter maps its rule families to error, warning or style.
   - A tool that gives no severity has its findings treated as fix later, except rule identifiers on the adapter's curated list, which block.
   - A dependency vulnerability with no score counts as high, so it blocks unless the builder records a reason. Medium and low vulnerabilities are fix later, in new dependencies too, and so are medium and low workflow and infrastructure findings.
   - Two tools reporting the same vulnerability (pip-audit or cargo-deny beside osv-scanner), matched by advisory identifier or alias, make one finding. It takes its severity from a tool that gives a score; "no score counts as high" applies only when no tool scores it.
   - Each adapter states its level mapping and any curated list in `review-tools.md`. The operator reviews them lens by lens, in the same sitting as that lens's question banks (C7).
7. **Changed-line coverage.** One adapter reads LCOV (the Linux Test Project's coverage format), Cobertura and coverage.py's JSON (JavaScript Object Notation) report and matches each against the diff. It writes a measurement record for changed-line branch coverage and one finding per changed branch no test runs. A report with no branch data falls back to lines and is marked degraded.
8. **The relocated test run.** One extra run of the repository's tests from a different working directory, with an empty temporary home directory.
9. **The mutation cap.** Every mutation adapter draws on one 15-minute cap per review (plan.md, Testing lens). Whatever is unfinished is recorded as degraded.
10. **Records.** Every output becomes C1's finding or measurement records and passes C1's validator; a malformed record is a runner error, never silently dropped. Raw tool output stays on the machine, under the user's home directory with owner-only permissions, stored under a fingerprint of its content that the records cite (plan.md, Change 9).
11. **Degraded inputs.** A tool that is missing, at a version other than its pin, unsupported on this platform, cut by the cap, or that does not exist (a known gap) gives a degraded-input entry naming the tool, the lens-table row and the reason. A degraded answer cannot block on its own (plan.md, design rules).
12. **The every-language adapters**, with each outcome from plan.md's lens tables and item 6:

| Tool | Lens-table row in plan.md | Outcome |
|---|---|---|
| Semgrep with saga's own rules (C5) | Correctness: "One of our pattern checks fires" | the outcome fixed in each rule |
| Semgrep with a security rule set | Security: a scanner finding "rated high or critical", or "rated medium or low" | blocks unless the builder records a false positive with a reason; fix later |
| gitleaks | Security: "A secret in the diff" | blocks; the record carries the location, never the secret |
| osv-scanner, base and head | Security: "A new dependency with a known high or critical vulnerability" | blocks unless a reason is recorded; no score counts as high; medium and low are fix later |
| jscpd, base and head | Architecture: "A second copy of a value, list or rule" | note |
| lizard | Architecture: "Complexity, dead code, naming" | note |
| the coverage adapter | Testing: "A changed branch no test runs" | blocks unless the builder recorded it as unreachable, with a reason |
| the relocated test run | Architecture: "The tests fail when run from a different working directory and home directory" | blocks |

Semgrep runs with its usage metrics turned off, from rule packs pinned and cached locally; the cache is part of the calibration fingerprint. Its adapter states which of Semgrep's levels (ERROR, WARNING and INFO) count as "high or critical". osv-scanner reads the lockfiles it supports, pnpm's and Yarn's included, and leaves npm's own lockfile to npm audit (C4c). The "unless the builder records" exceptions read the builder record, which C1 defines and C11 captures.

13. **Fingerprint.** The paths this card adds (the runner, the diff reader, the adapters, the default tool list and the cached Semgrep rule packs) join the fingerprinted component list of C2 (saga: the calibration file decides which lenses may block), in whichever of the two cards lands second.

Depends on C1 (saga: review records, validation and the A–F formula) for the records, the row identifiers, the fixed rules and the validator. C3, C4b, C4c, C5, C5b, C6 and C11 build on this card. Until C3 writes pins, the runner uses the list's defaults.

### Risk

medium
It is new code that blocks nothing itself; blocking stays with C1's formula, C2's calibration file and C11's gates.

### Out-of-scope / non-goals

- Calling the runner from each unit's build loop and from the combined-branch pass: C11 (saga + agent-launcher: builder declarations and the build-loop review checks). Its gate uses this runner's results: a blocking tool finding fails the combined-branch pass before the LLM (large language model) step only for lenses C2 allows to block, plus a secret in the diff, which always fails it. C11 also retires the build loop's "not configured" scanner report.
- The scripted checks no tool provides (the two test runs, the check for tests CI skipped, the machine-specific value search, the changed-name search and the workflow graph check): C5b (saga: the scripted review checks no tool provides), which runs them through this runner.
- Outcomes and grades: C1. Which lens may block: C2. Sending records to Langfuse: C15 (fleet-core + saga: Langfuse review traces and outcomes at merge).
- The language adapters: C4b (saga: review tools for Python, CDK, shell, workflows and Markdown; CDK is Amazon's Cloud Development Kit) and C4c (saga: review tools for TypeScript, Dart, Rust and Swift). Saga's own Semgrep rules: C5 (saga: pattern checks for the defects we keep hitting). The sweep: C6 (fleet-core + saga: the Jev sweep says where to look in a change).
- Installing tools and writing a repository's pins: C3 (saga: /saga:setup checks and prepares the machine and the repository).
- Reviewing the level mappings and curated lists: the operator, in the lens sittings of C7 (saga: policy questions and question banks for the four lenses, reviewed by the operator).
- Running the same tools with the same outcomes in CI: X2 (CI standard: the pinned review tools per language as a required check).

### Files expected to change

- `plugins/saga/scripts/review_tools.py` (new)
- `plugins/saga/scripts/review_diff.py` (new: the diff reader)
- `plugins/saga/scripts/coverage_lines.py` (new)
- `plugins/saga/scripts/review_adapters_all_languages.py` (new)
- `plugins/saga/scripts/review_formula.py` (created by C1; this card adds the rules in item 6)
- `plugins/saga/references/review-tools.md` (new)
- `plugins/saga/references/review-tools.yaml` (new)
- `plugins/saga/references/repository-profile.md` (the profile's block of pinned versions and rule sets)
- C2's fingerprinted component list, if C2 has landed (proposed in `plugins/saga/scripts/review_calibration.py`)
- `plugins/saga/tests/test_review_tools.py` (new)
- `plugins/saga/tests/test_review_diff.py` (new)
- `plugins/saga/tests/test_coverage_lines.py` (new)
- `plugins/saga/tests/test_review_adapters_all_languages.py` (new)
- `plugins/saga/tests/test_review_formula.py` (created by C1; this card adds cases for the rules in item 6)
- `plugins/saga/tests/fixtures/review_tools/` (new: recorded tool outputs with inert values)
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `test_review_tools.py`, on a temporary git repository with a base and a head commit: a finding on an unchanged line is dropped and one on an added or modified line is kept; a whole-project result present at base and head is dropped and a new one is kept; a type error the change causes in an untouched file is kept and blocks; a missing program, a timeout, an unsupported platform and a tool at a version other than its pin each give a degraded input, and the off-pin tool's results are kept, marked degraded; the cap marks unfinished mutation work degraded; every record passes C1's validator; raw output is stored under its content fingerprint in a directory only its owner can read; every tool receives an argument vector, never a shell string; a pinned version overrides the list's default, and a malformed block of pinned versions is refused.
- `test_review_tools.py`, the relocated run: a fixture test that reads a file through a path relative to the caller's directory, or writes under the home directory, passes the normal run and fails the relocated one.
- `test_review_diff.py`: additions, modifications, deletions, a rename without edits and a binary file give the changed lines `git diff` reports, and the rename gives none; the changed-line filter and the coverage adapter read the change through it.
- `test_review_formula.py`: one case per rule in item 6: a finding at error, warning and style or information level; a finding from a tool with no severity, on and off its curated list; a dependency vulnerability with no score, and one rated medium; the same advisory from two tools, one unscored and one rated medium, as one fix-later finding.
- `test_coverage_lines.py`: one diff matched against an LCOV, a Cobertura and a coverage.py fixture gives the same uncovered changed branches; a report without branch data falls back to lines and is marked degraded.
- `test_review_adapters_all_languages.py`: recorded Semgrep, gitleaks, osv-scanner, jscpd and lizard outputs map to the rows and outcomes above; the gitleaks record holds no secret text; Semgrep's argument vector turns usage metrics off and names only the local rule cache; osv-scanner reads pnpm and Yarn lockfiles and not npm's; an osv-scanner vulnerability with no score blocks unless a reason is recorded.
- `plugins/saga/tests/test_entrypoints.py` covers the new script's `--help` through its existing discovery.

### Context library links

- infiquetra-context-library `docs/delivery/ci-cd-standards.md` and `docs/testing/quality-gates.md`
- infiquetra-context-library `docs/security/dependency-policy.md` and `docs/security/data-and-secrets.md`
- `plugins/saga/references/mechanical-baseline.md`

### Acceptance criteria

- [ ] `python3 plugins/saga/scripts/review_tools.py --help` exits 0, and the runner works from a repository, base, head, profile and output directory with no run record.
- [ ] Tests on a temporary repository prove that line findings outside the change are dropped, that whole-project results are kept only when new at head, and that a type error the change causes in an untouched file blocks.
- [ ] One diff reader serves the changed-line filter and the coverage adapter, and `review-tools.md` documents it as the reader C6's sweep uses.
- [ ] `test_review_formula.py` shows the rules in item 6: error level blocks, warning is fix later, style or information is a note; a finding from a tool with no severity is fix later unless its rule is on the curated list; a dependency vulnerability with no score blocks unless a reason is recorded; medium and low vulnerabilities and workflow and infrastructure findings are fix later; the same vulnerability from two tools is one finding with the scoring tool's severity.
- [ ] One coverage adapter reads LCOV, Cobertura and coverage.py reports and agrees across the three fixtures.
- [ ] The relocated test run runs once per call and its failure maps to the blocking architecture row.
- [ ] `build_loop.py` reads its checks from the default tool list; nothing in saga reads the lifecycle
      repository's `mechanical_checks` map.
- [ ] The every-language tools map to the rows and outcomes in the table above, and every record passes C1's validator.
- [ ] Missing tools, versions other than the pin, unsupported platforms, the mutation cap and known gaps appear as degraded inputs naming the tool, the row and the reason.
- [ ] Raw tool output sits under the user's home directory, readable by its owner only.
- [ ] Semgrep runs with usage metrics off, from the pinned rule packs cached locally.
- [ ] `review-tools.md` documents the adapter interface, the diff reader, both filtering rules, the rules in item 6, each every-language adapter's level mapping and the outcome table; `repository-profile.md` documents the block of pinned versions; the default tool list holds the every-language rows.
- [ ] C2's fingerprinted component list names this card's paths, added here or by C2 if it lands second.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network access.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 plugins/saga/scripts/review_tools.py --help
```

### Notes / conventions

- For the planning step: names are proposals (the scripts, the tests, the default tool list and the profile block's key).
- For the planning step: the profile block names the repository's test command for each language, which the relocated run, the coverage tools and the test-suite tools use, and C3 writes it; today's baseline is an unlabelled list (`repository-profile.md:36-41`). Choose between copying the checkout to another path and running from another directory.
- For the planning step: a pinned rule set is named by its rule pack or configuration file plus a fingerprint of its content.
- For the planning step: Semgrep's command-line reference documents `--metrics=off` and the levels ERROR, WARNING and INFO; draft their mapping onto "high or critical" and "medium or low" for the security sitting. Choose where the cached rule packs live so the calibration fingerprint covers them (committed in saga, or cached on the machine and checked against a fingerprint in the default tool list), and check the packs' licence before committing copies to this public repository.
- For the planning step: osv-scanner's rating comes from each vulnerability's severity data, with a CVSS (Common Vulnerability Scoring System) score mapped by the standard bands; settle the option that leaves npm's lockfile to npm audit.
- For the planning step: lizard's complexity threshold and jscpd's minimum copy size are stated in `review-tools.md` for the architecture sitting.
- For the planning step: type checkers need the project's dependencies installed at base too; reuse the head's environment when the lockfile is unchanged, and cache base results by base commit and tool version. Match results across base and head by C1's finding identity, which survives line shifts.
- For the planning step: keep each level mapping and curated list as data the adapter reads (in the default tool list), with `review-tools.md` presenting it and a test that keeps the two in step.
- For the planning step: the rules in item 6 enter C1's formula as rule identifiers per lens. The adapter records the tool's level and the formula computes the outcome, since C1's validator refuses a record handed in with a severity.
- For the planning step: the raw-output directory's path under the user's home, beside C3's machine record.
- For the planning step: scripts take no third-party package besides PyYAML, so the Cobertura reader uses the standard library's XML (Extensible Markup Language) parser, on reports the run itself produced.

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C4a-tool-framework.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C4a-tool-framework.md
- Source type: brainstorm
- Source title: saga: build-loop tool framework reporting only what a change introduces

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/151
- Number: 151
- Created at: 2026-10-05T19:09:51.691179+00:00
