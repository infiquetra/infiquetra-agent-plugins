---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: review tools for Python, CDK, shell, workflows and Markdown

### Objective

Saga's tool runner from C4a gains adapters for Python, CloudFormation and Cloud Development Kit (CDK) code, shell scripts, GitHub workflows and Markdown. Each tool runs at its pinned version on a change. Each result becomes a record carrying the lens-table row and outcome plan.md fixes for it, or, where no row names the finding, the outcome C4a's rules give it from the tool's own level. Saga's default versions for these tools become the canonical pins, replacing the context library's ruff, mypy and bandit pins.

### Intent

This card implements the Python, CloudFormation and CDK, shell, GitHub workflows and Markdown rows of plan.md's "Default tools" table (Change 2), mapped onto the four lens tables in "Lens by lens", with the outcomes the operator decided on 5 October 2026 for findings those tables never named.

What is true on origin/main today:

- The build loop's check runner knows four Python checks by tool name: ruff, mypy, bandit and pytest coverage (`plugins/saga/scripts/build_loop.py:136-157`). It runs the profile's commands for pass or fail only and parses no output (`build_loop.py:486-531`).
- The baseline measures no coverage, and bandit is reported as uncovered (`plugins/saga/references/mechanical-baseline.md:61-95`). Nothing runs mutation testing, random-order runs or no-network runs.
- Shell scripts, workflow files, CloudFormation templates and Markdown get no tool at all.

What changes: one adapter per tool, plugged into C4a's interface. Each has an invocation at the pinned version and rule set, a parser for the tool's machine-readable output, a mapping onto C1's row identifiers or onto C4a's rules for findings no row names, a stated level mapping, and a fixture of recorded output. Each tool also gets its row in C4a's default tool list, with its default version and rule set.

| Tool | Lens-table row in plan.md, or none | Outcome |
|---|---|---|
| bandit | Security: a scanner finding "rated high or critical" (bandit's HIGH), or "rated medium or low" | blocks unless the builder records a false positive with a reason; fix later |
| pip-audit, base and head | Security: "A new dependency with a known high or critical vulnerability" | its output carries no score; a vulnerability osv-scanner also reports takes osv-scanner's score (C4a), and one no tool scores counts as high and blocks unless a reason is recorded |
| mypy, base and head over the whole project | Correctness: "A type error the change introduces" | blocks, wherever the error lands |
| coverage.py with branch measurement, through C4a's coverage adapter | Testing: "A changed branch no test runs" | blocks unless the builder recorded it as unreachable, with a reason |
| cosmic-ray, on changed lines, within the 15-minute cap per review | Testing: "A deliberate change the tests let through (a surviving mutant)" | blocks unless recorded as making no real difference, with a reason; unfinished work is degraded |
| pytest-randomly | Testing: "A test that fails in random order" | fix later |
| pytest-socket | Testing: a test that fails "with the network blocked" | fix later |
| vulture | Architecture: "Complexity, dead code, naming" | note |
| import-linter, base and head | Architecture: "A repository structural check fails" (import rules) | blocks |
| cdk-nag | Security: "A high-rated workflow or infrastructure finding" | an error counts as high and blocks; a warning counts as medium and is fix later |
| Checkov, run offline | Security: the same row | it gives no severity, so fix later, except rule identifiers on the curated list, which block |
| zizmor | Security: the same row ("an unpinned action in a publishing workflow") | high blocks; medium and low are fix later; informational is a note |
| ruff (lint) | none (Correctness column) | no levels: the adapter maps rule families to error (blocks), warning (fix later) or style (note) |
| actionlint | none (Correctness column) | no levels: the adapter maps each rule kind to error, warning or style |
| cfn-lint, ShellCheck | none (Correctness column) | error level blocks; warning is fix later; information and style levels are notes |
| markdownlint-cli2 | none (Correctness column): Markdown style | note |
| lychee | none (Architecture column): broken links | fix later |
| cspell | none (Architecture column): spelling | note |
| ruff format and shfmt | Architecture: the formatter fixes formatting in the build loop | fixed in the loop; no review record |

Further requirements:

- A row marked "none" takes C4a's rules for findings no lens-table row names: a tool's error level blocks, its warnings are fix later, and its style and information messages are notes. Its lens is the tool's column in plan.md's "Default tools" table. lychee, markdownlint-cli2 and cspell carry the outcomes the operator set for them directly.
- coverage.py, cosmic-ray, pytest-randomly and pytest-socket run the repository's own test suite, so they must load into its test environment.
- cosmic-ray limits mutation to the changed lines through its git filter, and stops when the review's shared cap runs out.
- For CDK code the security findings sit on synthesized templates, not on changed source lines, so Checkov and cdk-nag use C4a's base and head comparison there. Hand-written CloudFormation templates use the changed-line filter.
- cdk-nag runs inside `cdk synth`, as a check the repository's application adds. An application that does not add it gets a degraded input for the cdk-nag row, and C3's repository check names it.
- A security-scanner record carries its location and rule, never a secret it quotes (plan.md, Change 9).
- Saga's default versions in C4a's default tool list are the canonical pins for these tools. They replace the ruff, mypy and bandit pins in the context library's Python toolchain page, which X2 (CI standard: the pinned review tools per language as a required check) changes to link to saga's list.
- Each adapter states its level mapping and any curated list in `review-tools.md`: ruff's rule families, actionlint's rule kinds, Checkov's curated rule identifiers, and how bandit's, cfn-lint's, ShellCheck's, zizmor's and cdk-nag's levels map. The operator reviews them lens by lens in the sittings of C7 (saga: policy questions and question banks for the four lenses, reviewed by the operator).
- The paths this card adds (its adapters and its rows in the default tool list) join the fingerprinted component list of C2 (saga: the calibration file decides which lenses may block) in the same change, or C2 adds them if it lands later.

Depends on C4a (saga: build-loop tool framework reporting only what a change introduces). C3 (saga: /saga:setup checks and prepares the machine and the repository) installs these tools and pins them in the profile.

### Risk

medium
Twenty-one adapters each parse a third-party output format, and a wrong mapping would block or pass the wrong things once a lens clears calibration; until then every lens only reports.

### Out-of-scope / non-goals

- The runner, both filtering rules, the coverage reader, the mutation cap, record building and the rules for findings no lens-table row names: C4a.
- TypeScript, Dart, Rust and Swift: C4c (saga: review tools for TypeScript, Dart, Rust and Swift).
- Saga's own Semgrep rules: C5 (saga: pattern checks for the defects we keep hitting).
- Installing tools, writing a repository's pins and naming an application without cdk-nag: C3. Calling the tools from the build loop: C11 (saga + agent-launcher: builder declarations and the build-loop review checks). Grades: C1 (saga: review records, validation and the A–F formula). Which lens may block: C2.
- Reviewing the level mappings and the curated list: the operator, in C7's sittings.
- The same tools and outcomes as a required CI check, and moving the context library's pins: X2.

### Files expected to change

- `plugins/saga/scripts/review_adapters_python.py` (new)
- `plugins/saga/scripts/review_adapters_infrastructure.py` (new)
- `plugins/saga/scripts/review_adapters_shell.py` (new)
- `plugins/saga/scripts/review_adapters_workflows.py` (new)
- `plugins/saga/scripts/review_adapters_markdown.py` (new)
- `plugins/saga/references/review-tools.md`
- `plugins/saga/references/review-tools.yaml` (rows and default versions for these tools)
- `plugins/saga/scripts/review_calibration.py` (C2's fingerprinted component list, if C2 has landed)
- `plugins/saga/tests/test_review_adapters_python.py` (new)
- `plugins/saga/tests/test_review_adapters_infrastructure.py` (new)
- `plugins/saga/tests/test_review_adapters_shell_workflows_markdown.py` (new)
- `plugins/saga/tests/fixtures/review_tools/` (recorded outputs for these tools, with inert values)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- Each new test file feeds recorded tool output through its adapter and C4a's runner, with an injected runner and no network. It asserts that:
  - each record's lens, row or rule, and outcome match the table above, and each record passes C1's validator;
  - a line-located finding outside the change is dropped; a pip-audit, import-linter or mypy result already present at base is dropped; a mypy error the change causes in an untouched file is kept and blocks;
  - bandit's HIGH blocks unless a false positive is recorded, and its MEDIUM and LOW are fix later; a pip-audit vulnerability no tool scores blocks unless a reason is recorded, and one osv-scanner rates medium is a single fix-later finding;
  - ruff findings map by rule family, actionlint findings by rule kind, and ShellCheck and cfn-lint findings by level; zizmor's high blocks and its medium and low are fix later;
  - markdownlint-cli2 and cspell findings are notes, and a lychee broken link is fix later;
  - a cosmic-ray run cut by the cap is recorded as degraded; a random-order failure and a no-network failure are each fix later;
  - ruff format and shfmt leave no review record.
- `test_review_adapters_infrastructure.py` also checks that a CDK finding present in both the base and head synthesis is dropped; that a cdk-nag error blocks and a warning is fix later; that a Checkov finding blocks when its rule is on the curated list and is fix later otherwise; and that a CDK application without cdk-nag gives a degraded input for that row.
- A live check per local tool runs on a tiny fixture repository when the tool is installed at its pinned version, and skips otherwise. pip-audit and lychee use the network, so they get recorded-output tests only.

### Context library links

- infiquetra-context-library `docs/repositories/python-toolchain.md` (bandit, mypy and ruff configuration; X2 replaces its pins with a link to saga's list)
- infiquetra-context-library `docs/governance/adrs/adr-0003-python-service-toolchain-and-cdk-language.md`
- infiquetra-context-library `docs/delivery/ci-cd-standards.md` ("Python / CDK Repos") and `docs/testing/quality-gates.md`
- infiquetra-context-library `docs/security/dependency-policy.md`

### Acceptance criteria

- [ ] Every tool in the table has an adapter whose records carry the row or rule and the outcome shown, proven by `python3 -m pytest plugins/saga/tests/test_review_adapters_python.py plugins/saga/tests/test_review_adapters_infrastructure.py plugins/saga/tests/test_review_adapters_shell_workflows_markdown.py -q --import-mode=importlib`.
- [ ] mypy compares base and head over the whole project, and a type error the change causes in an untouched file blocks.
- [ ] pip-audit's vulnerabilities take osv-scanner's score when it reports the same advisory, and otherwise block unless a reason is recorded; cdk-nag's errors block and its warnings are fix later; Checkov's findings are fix later except rules on the curated list, which block; zizmor's medium and low findings are fix later.
- [ ] ruff's rule families and actionlint's rule kinds map to error, warning or style; cfn-lint's and ShellCheck's levels map by C4a's rules; markdownlint-cli2 and cspell give notes, and lychee gives fix later.
- [ ] cosmic-ray mutates changed lines only and stops at the review's 15-minute cap, recording the rest as degraded.
- [ ] pytest-randomly and pytest-socket failures are fix later, and the formatters leave no review record.
- [ ] A CDK application that does not apply cdk-nag gives a degraded input for the cdk-nag row.
- [ ] `plugins/saga/references/review-tools.md` carries the outcome table and each adapter's level mapping and curated list, for the operator's lens sittings in C7.
- [ ] The default tool list holds an exact default version for every tool in the table.
- [ ] C2's fingerprinted component list names this card's paths, added here or by C2 if it lands later.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network access.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_review_adapters_python.py plugins/saga/tests/test_review_adapters_infrastructure.py plugins/saga/tests/test_review_adapters_shell_workflows_markdown.py -q --import-mode=importlib
```

### Notes / conventions

- For the planning step: how the four test-suite tools load into the repository's test environment for a run, for example uv's `--with` option, which adds a package for one run without editing the repository. pytest-randomly reorders every pytest run in an environment where it is installed, and pytest's `-p no:randomly` turns it off for runs that need the usual order; pytest-socket blocks the network through its `--disable-socket` option.
- For the planning step: ruff's JSON (JavaScript Object Notation) output gives each finding's rule code, whose letter prefix names its family. A family's letter does not give its level (pycodestyle's `E` codes are mostly style), so draft the mapping for the correctness sitting.
- For the planning step: levels, from each tool's documentation. ShellCheck reports error, warning, info and style. cfn-lint's rule identifiers start with E (error), W (warning) or I (informational, off by default). actionlint reports a rule kind and no level. zizmor reports informational, low, medium and high, plus a confidence the adapter records. bandit reports HIGH, MEDIUM and LOW. pip-audit's JSON output carries an identifier, aliases, fix versions and a description, and no score.
- For the planning step: Checkov runs without a platform key, so its output carries no severity. Draft the curated list from the security row's examples (a wildcard IAM (Identity and Access Management) policy, public storage) for the security sitting.
- For the planning step: zizmor's `--offline` option skips the audits that need the network; settle whether review runs give it the machine's GitHub sign-in.
- For the planning step: cdk-nag's findings come from the report files it writes during synthesis or from the synthesis output. Checkov and cdk-nag synthesize base and head into separate output directories, and C3's repository check detects whether the application applies cdk-nag.
