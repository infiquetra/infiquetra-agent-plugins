---
date: 2026-10-05
topic: saga-review-redesign
maturity: requirements-ready
---

# saga: review tools for TypeScript, Dart, Rust and Swift

### Objective

Saga's tool runner from C4a gains adapters for TypeScript, Dart, Rust and Swift. Each tool runs at its pinned version on a change, and each result becomes a record carrying the lens-table row and outcome plan.md fixes for it, or, where no row names the finding, the outcome C4a's rules give it from the tool's own level. Tests run in random order through each runner's own shuffle option where one exists. The known gaps run degraded, never as a pass: Swift dependency audits, Flutter branch coverage, Rust branch coverage on a stable toolchain, Muter on Linux, random test order in Rust and Swift, and blocking the network in tests outside Python.

### Intent

This card implements the TypeScript, Dart, Rust and Swift rows of plan.md's "Default tools" table (Change 2) and its list of known gaps, mapped onto the four lens tables in "Lens by lens", with the outcomes the operator decided on 5 October 2026 for findings those tables never named.

What is true on origin/main today: saga runs no tool for these languages. The build loop's check runner maps baseline commands to checks for the Python stack only (`plugins/saga/scripts/build_loop.py:136-157`). It runs commands for pass or fail and parses no output (`build_loop.py:486-531`). The build loop measures no coverage and runs no mutation testing in any language (`plugins/saga/references/mechanical-baseline.md:61-73`).

What changes: one adapter per tool, plugged into C4a's interface. Each has an invocation at the pinned version, a parser for the tool's machine-readable output, a mapping onto C1's row identifiers or onto C4a's rules for findings no row names, a stated level mapping, and a fixture of recorded output. Each tool also gets its row in C4a's default tool list, with its default version and rule set.

| Language | Tool | Lens-table row in plan.md, or none | Outcome |
|---|---|---|---|
| TypeScript | npm audit on npm's lockfile, base and head | Security: "A new dependency with a known high or critical vulnerability" | blocks unless a reason is recorded; medium and low are fix later |
| TypeScript | osv-scanner on pnpm and Yarn lockfiles, through C4a's adapter | Security: the new-dependency row | as for npm audit; no score counts as high |
| TypeScript | the TypeScript compiler, `tsc`, in strict mode, base and head over the whole project | Correctness: "A type error the change introduces" | blocks, wherever the error lands |
| TypeScript | ESLint with typescript-eslint | none (Correctness column) | error level blocks; warning is fix later |
| TypeScript | Vitest or Jest coverage, through C4a's coverage adapter | Testing: "A changed branch no test runs" | blocks unless the builder recorded it as unreachable, with a reason |
| TypeScript | StrykerJS | Testing: "A deliberate change the tests let through (a surviving mutant)" | blocks unless recorded as making no real difference, with a reason |
| TypeScript | Vitest's or Jest's own shuffle option | Testing: "A test that fails in random order" | fix later |
| TypeScript | knip | Architecture: "Complexity, dead code, naming" | note |
| TypeScript | dependency-cruiser, base and head | Architecture: "A repository structural check fails" (import rules) | blocks |
| Dart | osv-scanner on `pubspec.lock`, through C4a's adapter | Security: the new-dependency row | blocks unless a reason is recorded; medium and low are fix later; no score counts as high |
| Dart | `dart analyze`, base and head over the whole project | Correctness: the type-error row for its errors; none for the rest | errors block, wherever they land; warnings are fix later; information diagnostics, most lints among them, are notes |
| Dart | `package:coverage` | Testing: the changed-branch row | blocks unless recorded as unreachable |
| Dart | mutate4dart | Testing: the surviving-mutant row | blocks unless recorded as making no real difference |
| Dart | `dart test`'s own shuffle option | Testing: the random-order row | fix later |
| Rust | cargo-deny advisories, base and head | Security: the new-dependency row | blocks unless a reason is recorded; medium and low are fix later; an advisory no tool scores counts as high, and one osv-scanner also reports is one finding with its score (C4a) |
| Rust | the compiler's errors (`cargo check`), base and head over the whole project | Correctness: the type-error row | blocks, wherever the error lands |
| Rust | clippy's lints | none (Correctness column) | error level blocks; warning is fix later |
| Rust | cargo-llvm-cov | Testing: the changed-branch row | blocks unless recorded as unreachable; on a stable toolchain, line coverage marked degraded |
| Rust | cargo-mutants | Testing: the surviving-mutant row | blocks unless recorded as making no real difference |
| Rust | cargo-machete | Architecture: "Complexity, dead code, naming" (unused dependencies) | note |
| Rust | nextest | none: the test runner the other Rust test tools call | no record of its own |
| Swift | the compiler with strict concurrency checking, base and head over the whole project | Correctness: the type-error row | blocks, wherever it lands; strict-concurrency diagnostics count as type errors, whatever level the compiler gives them |
| Swift | SwiftLint | none (Correctness column) | error level blocks; warning is fix later |
| Swift | llvm-cov | Testing: the changed-branch row | blocks unless recorded as unreachable |
| Swift | Muter, macOS only | Testing: the surviving-mutant row | blocks unless recorded as making no real difference |
| All four | Prettier, `dart format`, rustfmt, swift-format | Architecture: the formatter fixes formatting in the build loop | fixed in the loop; no review record |

Further requirements:

- A row marked "none" takes C4a's rules for findings no lens-table row names: a tool's error level blocks, its warnings are fix later, and its style and information messages are notes. The pinned rule set sets each lint's level. Saga does not turn clippy's warnings into errors, because under those rules a warning is fix later (plan.md's table said "warnings as errors").
- Every mutation adapter stays within the review's shared 15-minute cap, and unfinished work is recorded as degraded. Where a tool cannot limit itself to the changed lines, C4a's changed-line filter applies to its results.
- Random test order uses each runner's own shuffle option. Rust and Swift have no stable one, so their random-order input is degraded.
- TypeScript dependency audits: npm audit reads npm's own lockfile, and C4a's osv-scanner adapter reads pnpm's and Yarn's.
- The known gaps, each a degraded input naming the tool, the row and the reason. The review command (C10a, saga: one review command from change to records) then hands the question to the large language model (LLM) reviewer (C8, saga + agent-launcher: the targeted LLM reviewer), whose answer cannot block on its own:
  - Swift dependency vulnerabilities: no tool exists, so the new-dependency row is degraded for Swift.
  - Flutter branch coverage: Flutter's coverage report carries no branch data (upstream Flutter issue 171580), so C4a's line fallback applies and is marked degraded.
  - Rust branch coverage on a stable toolchain: cargo-llvm-cov measures branches only on a nightly toolchain, so a stable toolchain gets the same line fallback, marked degraded.
  - Muter runs only on macOS, and its last release was in 2023. On Linux the surviving-mutant row is degraded for Swift.
  - Random test order in Rust and Swift: neither has a stable shuffle option.
  - Blocking the network in tests: no tool outside Python, so the no-network input is degraded for these four languages.
- Each adapter states its level mapping in `review-tools.md`: ESLint's, `dart analyze`'s, clippy's, SwiftLint's and cargo-deny's levels, and npm audit's ratings. The operator reviews them lens by lens in the sittings of C7 (saga: policy questions and question banks for the four lenses, reviewed by the operator).
- The paths this card adds (its adapters and its rows in the default tool list) join the fingerprinted component list of C2 (saga: the calibration file decides which lenses may block) in the same change, or C2 adds them if it lands later.

Depends on C4a (saga: build-loop tool framework reporting only what a change introduces). C3 (saga: /saga:setup checks and prepares the machine and the repository) installs these tools and pins them in the profile.

### Risk

medium
The adapters parse formats from four tool ecosystems, and each gap must read as degraded, never as a pass; every lens only reports until it clears calibration.

### Out-of-scope / non-goals

- The runner, both filtering rules, the coverage reader, the mutation cap, record building, the rules for findings no lens-table row names and the osv-scanner adapter: C4a.
- Python, CloudFormation and Cloud Development Kit (CDK) code, shell, workflows and Markdown: C4b (saga: review tools for Python, CDK, shell, workflows and Markdown).
- Saga's own Semgrep rules: C5 (saga: pattern checks for the defects we keep hitting).
- Installing tools and writing a repository's pins: C3. Calling the tools from the build loop: C11 (saga + agent-launcher: builder declarations and the build-loop review checks). The LLM's degraded answers: C8 and C10a. Which lens may block in which language: C2.
- Reviewing the level mappings: the operator, in C7's sittings.
- Building a network-blocking tool, a Swift dependency audit or a stable shuffle for Rust or Swift: these gaps are accepted and run degraded.

### Files expected to change

- `plugins/saga/scripts/review_adapters_typescript.py` (new)
- `plugins/saga/scripts/review_adapters_dart.py` (new)
- `plugins/saga/scripts/review_adapters_rust.py` (new)
- `plugins/saga/scripts/review_adapters_swift.py` (new)
- `plugins/saga/references/review-tools.md`
- `plugins/saga/references/review-tools.yaml` (rows and default versions for these tools)
- `plugins/saga/scripts/review_calibration.py` (C2's fingerprinted component list, if C2 has landed)
- `plugins/saga/tests/test_review_adapters_typescript.py` (new)
- `plugins/saga/tests/test_review_adapters_dart.py` (new)
- `plugins/saga/tests/test_review_adapters_rust.py` (new)
- `plugins/saga/tests/test_review_adapters_swift.py` (new)
- `plugins/saga/tests/fixtures/review_tools/` (recorded outputs for these tools, with inert values)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- Each new test file feeds recorded output through its adapters and C4a's runner, with an injected runner and no network. It asserts that:
  - each record's lens, row or rule, and outcome match the table and pass C1's validator, and line findings outside the change are dropped;
  - npm audit, cargo-deny and dependency-cruiser results already present at base are dropped;
  - a `tsc`, `dart analyze`, Rust compiler or Swift compiler error the change causes in an untouched file is kept and blocks, and a Swift strict-concurrency diagnostic the compiler reports as a warning blocks;
  - ESLint's, clippy's, SwiftLint's and `dart analyze`'s error level blocks and their warning level is fix later, and `dart analyze`'s information diagnostics are notes;
  - npm audit's high and critical ratings block unless a reason is recorded and its lower ratings are fix later; a cargo-deny advisory with no score blocks unless a reason is recorded;
  - a failure in a shuffled Vitest, Jest or `dart test` run is fix later; a mutation run cut by the cap is degraded; formatters and nextest leave no record of their own.
- The gap tests: a Swift change gives a degraded dependency-audit input; a Flutter report without branch data and a Rust report from a stable toolchain each give degraded line coverage; Muter on a reported Linux platform gives a degraded input; the Rust and Swift random-order inputs and each language's no-network input are degraded. None reads as a pass or a fail.
- A live check per local tool runs on a tiny fixture project when the tool is installed at its pinned version, and skips otherwise. npm audit and cargo-deny's advisory download use the network, so they get recorded-output tests only.

### Context library links

- infiquetra-context-library `docs/delivery/ci-cd-standards.md` ("Flutter Repos") and `docs/testing/quality-gates.md`
- infiquetra-context-library `docs/security/dependency-policy.md`
- `plugins/saga/references/mechanical-baseline.md`

### Acceptance criteria

- [ ] Every tool in the table has an adapter whose records carry the row or rule and the outcome shown, proven by `python3 -m pytest plugins/saga/tests/test_review_adapters_typescript.py plugins/saga/tests/test_review_adapters_dart.py plugins/saga/tests/test_review_adapters_rust.py plugins/saga/tests/test_review_adapters_swift.py -q --import-mode=importlib`.
- [ ] `tsc`, `dart analyze`, the Rust compiler and the Swift compiler compare base and head over the whole project; a type error the change causes in an untouched file blocks, and Swift strict-concurrency diagnostics block whatever level the compiler reports.
- [ ] ESLint, `dart analyze`, clippy and SwiftLint findings take their outcome from their own level, and clippy's warnings are fix later.
- [ ] npm audit reads npm's lockfile and osv-scanner reads pnpm's and Yarn's; a dependency vulnerability with no score, a cargo-deny advisory included, counts as high.
- [ ] Vitest, Jest and `dart test` run in random order through their own shuffle options, and a failure there is fix later.
- [ ] Each of the six known gaps appears as a degraded input naming the tool, the row and the reason, and never as a pass or a fail.
- [ ] Every mutation adapter stays within the review's 15-minute cap and records unfinished work as degraded.
- [ ] `plugins/saga/references/review-tools.md` carries the outcome table, the gap list and each adapter's level mapping, for the operator's lens sittings in C7.
- [ ] C2's fingerprinted component list names this card's paths, added here or by C2 if it lands later.
- [ ] `python3 -m pytest plugins/saga/tests -q --import-mode=importlib` passes with no network access.

### Verification

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests/test_review_adapters_typescript.py plugins/saga/tests/test_review_adapters_dart.py plugins/saga/tests/test_review_adapters_rust.py plugins/saga/tests/test_review_adapters_swift.py -q --import-mode=importlib
```

### Notes / conventions

- For the planning step: shuffle options, from each tool's documentation: Vitest's `--sequence.shuffle`; Jest's `--randomize`, which shuffles the tests within each file and needs Jest's default jest-circus runner; `dart test --test-randomize-ordering-seed=random`. Record the seed so a failure can be re-run.
- For the planning step: cargo-llvm-cov's `--branch` option is unstable and needs a nightly toolchain (its README), and its `nextest` subcommand runs the tests through nextest; detect the toolchain to choose between branch data and the line fallback. Settle how cargo-mutants calls nextest.
- For the planning step: cargo-deny reports every vulnerability advisory as an error, whatever its score (its documentation), so the adapter takes the rating from the advisory's own score. Its advisories that are not vulnerabilities (an unmaintained, unsound or yanked crate) get a stated mapping for the security sitting.
- For the planning step: npm audit rates "moderate" where the security rows say medium, and has an "info" rating below low; state both in the adapter's mapping for the security sitting.
- For the planning step: ESLint's JSON (JavaScript Object Notation) output gives severity 2 for an error and 1 for a warning; clippy's, `dart analyze`'s and the Swift compiler's machine-readable output carries each diagnostic's level.
- For the planning step: the Swift compiler setting that turns on complete strict-concurrency checking; how the adapter tells strict-concurrency diagnostics from the compiler's other warnings, which take C4a's rules; how base and head builds share a build cache.
- For the planning step: which mutation tools can limit themselves to the changed lines, and which rely on C4a's changed-line filter.
