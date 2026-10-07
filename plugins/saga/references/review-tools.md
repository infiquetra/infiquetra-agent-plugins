# Review tools

The runner in `plugins/saga/scripts/review_tools.py` turns pinned tools into review records for what a change introduces. A caller passes a repository, a base commit, a head commit, a profile and an output directory. The command does not take a run record. C11 is what calls it from the build loop. This card does not.

Importing the module reads no tool and starts no process. `load_tool_list` reads `plugins/saga/references/review-tools.yaml`. The every-language adapters live in `plugins/saga/scripts/review_adapters_all_languages.py` and are imported only when a run asks for the default list.

## Level map and thresholds

The first fence is the same data as the yaml. A test parses both and fails when the values differ.

```yaml
semgrep_level_map:
  ERROR: security.scanner-high
  WARNING: security.scanner-medium-low
  INFO: security.scanner-medium-low
thresholds:
  jscpd:
    min_lines: 5
    min_tokens: 50
  lizard:
    cyclomatic: 15
```

Semgrep `ERROR` is `security.scanner-high` (blocks). `WARNING` and `INFO` are `security.scanner-medium-low` (fix later). jscpd keeps a duplicate only at 5 lines and 50 tokens, on `architecture-maintainability.duplicate` (note). lizard keeps a function at cyclomatic complexity 15, on `architecture-maintainability.complexity-dead-code-naming` (note).

## Adapter interface

An adapter is a frozen object. `invoke` builds an argument vector and does not run it. `parse` reads that tool's machine-readable output into hits. The runner supplies the process, the timeout and `shell=False`.

| Field | Meaning |
|---|---|
| `id` | The yaml row id. One binary may have several ids. |
| `tool` | The binary name. Empty for coverage and the relocated run, which are not baseline checks. |
| `invoke` | `(ScanContext) -> list[str]`. A string command is a programming error. |
| `parse` | `(str) -> ParseResult`. Hits, plus `unfinished` when a mutation run stopped early. |
| `comparison` | `lines` or `base-head`. |
| `type_checker` | Forces base against head and a whole-project result, even when `comparison` says otherwise. |
| `rows` | The lens-table rows this adapter may emit. |
| `level_map` | Tool level to a row id, when the hit does not already name a row. |
| `rules` | A pack plus sha256, or a path. A profile rules list replaces this; it does not merge. |
| `gap_path` | While this path is missing or empty, the run records a known gap and does not scan. |
| `mutation` | Shares the 900 second cap. An unfinished result is reason `cap` on `testing.surviving-mutant`. |
| `mode` | `report` or `fix`. `fix` writes no review record. |
| `platforms` | Empty means every platform. Otherwise the current platform must be listed. |

`ScanContext` carries `repo` and `root`, both the directory this scan reads (the head worktree, or the base worktree on a base scan), `home` (where raw output and the rule cache go) and `configs` (local rule directories only).

## The commit under review

The commit under review is untrusted. Pins, rules, the test command, and `coverage_report` come from `.saga-profile.json` at the base commit. Saga's Semgrep rules and the gitleaks config come from this plugin. Scanners read a detached worktree of the head commit after `.semgrepignore`, `.gitleaks.toml`, `.gitleaksignore`, `.jscpd.json`, `whitelizard.txt`, and `osv-scanner.toml` are removed. Semgrep is started with `--disable-nosem`. gitleaks is started with `--config` pointing at `plugins/saga/references/gitleaks.toml` and with `--ignore-gitleaks-allow`. Coverage bytes come only from the relocated command's directory. The base cache is used only when its stored key matches the resolved base commit. Empty standard output with exit 0 is reason `empty-output`. The relocated command's environment copies `PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, and `TZ` when they are set, and sets `HOME`, `TMPDIR`, `TMP`, and `TEMP` to fresh directories. The command must start from a binary on `PATH`. A relative token is rewritten only when that path exists in the head worktree. A changed line that contains `gitleaks:allow`, `jscpd:ignore`, `lizard forgives`, `noqa`, `ruff: ignore`, `nosec`, or `shellcheck disable` is a degraded input, and the file is not rewritten. cdk synth, checkov on a synthesized template, cosmic-ray, pytest-randomly, pytest-socket, and zizmor use that same allow-list. The version probe does not. A relative Semgrep rule path from the base profile, other than saga's own rules, is read from a base worktree that stays open until that adapter's scans finish.

A hit carries the rule id, path, statement, anchor, optional level, line range, function, advisory ids, score and row. The runner turns hits into findings. A finding is handed in without a severity. `review_formula.py` computes the severity, and `outcomes.json` is where a reader finds it.

## The diff reader

`review_diff.read(repo, base, head)` is the only diff reader. The changed-line filter and the coverage adapter both take the `Change` it returns. Neither parses a diff. C6's sweep uses this same reader when it cuts pieces; this card documents that and does not implement the sweep.

`git diff` is an implementation detail of `review_diff.read`. Callers use `Change.files` and `Change.lines_for`. A pure rename has no changed lines. A deletion is not an added or modified line. A binary file has no lines.

## Both filters

**Changed-line filter.** A line hit is kept only when one of its lines was added or modified. A hit on any other line is dropped. A whole-project hit is not line-filtered.

**Base against head.** A whole-project result, and every type checker, is compared by finding identity (lens, row, rule reference, file, function, anchor). The same identity at base and head is dropped. An identity that exists only at head is kept. A tool that declines at base is an empty baseline, and head is still scanned. A type error the change causes in a file the diff did not touch is kept, and its row is `correctness.type-error`.

Coverage is not a second tool run and not a base-against-head coverage comparison. One head report is matched to the one `Change`.

## Item 6

A tool hit that does not already name a row uses `review_formula.tool_row`. The row id is the lens, a dot, and one of these suffixes:

| Suffix | When | Outcome |
|---|---|---|
| `tool-error` | level `error` | blocks |
| `tool-warning` | level `warning` | fix later |
| `tool-style` | level `style`, `info` or `information` | note |
| `tool-curated` | no level, and the rule id is on the adapter's curated list | blocks |
| `tool-unscoped` | no level, and the rule id is not curated | fix later |

An unknown level or lens is a refusal. A dependency advisory with no score is `security.dependency-high` (blocks, excused by `scanner-false-positive`). Score 7.0 and above is the same row. Below 7.0, including 0.0, is `security.dependency-medium-low` (fix later). Workflow and infrastructure `critical` or `high` is `security.workflow-infra-high`. `medium`, `low` or `none` is `security.workflow-infra-medium-low` (fix later). The same advisory from two tools becomes one finding. The scoring hit wins, and its canonical id is the finding's rule reference.

## Outcome table

| Tool id | Comparison | Row | Outcome |
|---|---|---|---|
| `semgrep-security` | lines | `security.scanner-high` for ERROR; `security.scanner-medium-low` for WARNING and INFO | blocks; fix later |
| `semgrep-saga` | lines | the `correctness.pattern.*` row named in the rule's metadata | blocks, excused by `pattern-check` |
| `gitleaks` | lines | `security.secret-in-diff` | blocks |
| `osv-scanner` | base against head | `security.dependency-high` or `security.dependency-medium-low` | blocks; fix later |
| `jscpd` | base against head | `architecture-maintainability.duplicate` | note |
| `lizard` | lines | `architecture-maintainability.complexity-dead-code-naming` | note |
| `coverage` | lines, one `Change` | `testing.uncovered-branch` | blocks; a line fallback is degraded and so fix later |
| `relocated-test` | one extra run, not a line filter | `architecture-maintainability.relocated-run-fails` | blocks |

Every finding and measurement passes `review_records.py` validation before the four files are written. A missing tool, a timeout, an unsupported platform, a version other than the pin, the mutation cap and a known gap are degraded inputs. Each one names the tool, the row and the reason. Exit 0 still writes the files. Exit 2 is a refusal (a bad profile, a bad commit, a validator rejection, two coverage reports that disagree, a saga metadata row that is not a pattern row, an unknown tool level or lens). Exit 1 is an unexpected error.

## Semgrep

The security row pins pack `p/security-audit` and the sha256 of the cached bytes. The committed hash is a placeholder, not the registry digest: the Semgrep Rules License v1.0 forbids shipping the pack in this repository. The cache directory is `~/.saga/semgrep-rules/p--security-audit` (a `/` in the pack name becomes `--`). The argument vector is `semgrep scan --metrics=off --json --config <cache> <root>`. `--config` is only that local directory. A missing cache or a hash mismatch is reason `rule-cache-missing` and does not download.

The saga row reads `plugins/saga/references/semgrep-rules`. While that directory is missing or empty, the run records one `known-gap` per `correctness.pattern.*` row and does not invent a rule. When the directory is present, each result's `metadata.row` must be one of those rows.

## osv-scanner

`osv-scanner scan source --format json` with an explicit `--lockfile` for each supported lockfile the tree contains. The supported names are `pnpm-lock.yaml`, `yarn.lock`, `pubspec.lock`, `mix.lock`, `go.mod`, `composer.lock`, `Pipfile.lock`, `poetry.lock`, `pdm.lock`, `requirements.txt`, `renv.lock`, `Gemfile.lock`, `Cargo.lock`, `conan.lock`, `gradle.lockfile` and `buildscript-gradle.lockfile`. `package-lock.json` and `npm-shrinkwrap.json` are not scanned. A tree whose only JavaScript lockfile is one of those two, and which has nothing else to scan, is reason `known-gap` on `security.dependency-high`. When that is true of base and head has a supported lockfile, base contributes no findings and head is scanned.

A numeric CVSS score is used as the number, including the string `"9.0"`. A vector is not calculated: the word in `database_specific.severity` stands in (`CRITICAL` 9.0, `HIGH` 7.0, `MEDIUM` 4.0, `LOW` 0.1). No score at all is `security.dependency-high`.

## gitleaks

The parser reads `RuleID`, `File`, `StartLine` and `EndLine`. It drops `Match` and `Secret`. The statement is "A secret scanner reported a match in this file." The anchor is the rule id and the path. The raw bytes may contain the match. The record cites the sha256 and does not.

## Coverage and the relocated run

Coverage prefers branches. One finding per uncovered changed line on `testing.uncovered-branch`, plus one measurement, metric `changed-line branch coverage`, threshold 1.0, direction at-least. Zero changed lines measure 1.0 and produce no finding. A changed file with no branch data makes the report a line fallback: the findings are `degraded: true` and the degraded input reason is `no-branch-data`. No report is reason `no-report` and produces no finding. Two reports whose uncovered sets differ are exit 2.

The relocated run does not copy the checkout. It rewrites repository-relative tokens to absolute paths, then runs the command once with cwd a fresh empty directory and `HOME` a different fresh empty directory. Each `review_tools.languages.<language>.test_command` runs once per `run`. When the languages block is absent, `functional_test_environment.test_command` runs once, with language `none`. A non-zero exit is one finding on `architecture-maintainability.relocated-run-fails`. When no command exists, the reason is `known-gap` on that row.

## Raw output

Raw tool output is `~/.saga/review-output/<sha256>`, mode 0600. `~/.saga` is created mode 0700 when this runner creates it. `--home` overrides the parent for tests. The finding's `proof.raw_output` is that sha256.

## Fingerprint

`FINGERPRINT_COMPONENTS` in `review_tools.py` names the paths C2 includes in its calibration file:

- `plugins/saga/scripts/review_tools.py`
- `plugins/saga/scripts/review_diff.py`
- `plugins/saga/scripts/coverage_lines.py`
- `plugins/saga/scripts/review_adapters_all_languages.py`
- `plugins/saga/references/review-tools.yaml`
- `plugins/saga/scripts/review_adapters_python.py`
- `plugins/saga/scripts/review_adapters_infrastructure.py`
- `plugins/saga/scripts/review_adapters_shell.py`
- `plugins/saga/scripts/review_adapters_workflows.py`
- `plugins/saga/scripts/review_adapters_markdown.py`

This card does not create `review_calibration.py`. The Semgrep pack is not a repository path. The yaml sha256 is how a later fingerprint reaches the cache without a download.

## Profile

The optional `review_tools` block is documented in `plugins/saga/references/repository-profile.md`. Absent is valid.

## Python, CDK, shell, workflows and Markdown

Issue 152 adds these adapters. A formatter (`ruff-format`, `shfmt`) is `mode: fix` and the runner does not start it, so it writes no record. Settings come from the base commit or from a file the adapter writes under the runner home. A settings file in the reviewed tree is not an input. actionlint still reads `.github/actionlint.yaml` beside the workflows when `-config-file` points elsewhere, so it scans a copy of the workflows and that file is left out of the copy. ruff lint uses `--isolated`, `--ignore-noqa`, and `--select ALL`. mypy passes `--config-file` for the base commit's config and does not pass `--strict`. An error is `correctness.type-error` (blocks). A mypy note is level `style` (note). cdk-nag raises a known gap when a project has `cdk.json` and synthesis ran no validation plugin. A clean plugin report is not a gap. Reason `missing` is recorded when `cdk` itself is absent, for cdk-nag and for the checkov-cdk synth. The anchor keeps the logical resource id or the construct path, so the same rule on two resources stays two findings. A tree with no `cdk.json` does not degrade. Checkov blocks only the curated ids below. zizmor's copy command runs `--offline` and receives no GitHub token. lychee has no line number, so a broken link is a whole-project hit compared base against head. markdownlint-cli2 prints `path:line:col MDxxx/name message` with no severity word. cosmic-ray's module-path is the list of changed Python files.

| Adapter id | Comparison | Row the record cites | Computed severity |
|---|---|---|---|
| `bandit` | lines | `security.scanner-high` for HIGH; `security.scanner-medium-low` for MEDIUM and LOW | blocks, excused by `scanner-false-positive`; fix later |
| `pip-audit` | base against head | `security.dependency-high` when no tool scores the advisory | blocks unless `scanner-false-positive`; the scored severity when osv-scanner has one |
| `mypy` | base against head, type checker | `correctness.type-error` for an error; `correctness.tool-style` for a note | blocks; note |
| `coverage` | one head report | `testing.uncovered-branch` | blocks, excused by `coverage-gap` |
| `cosmic-ray` | lines | `testing.surviving-mutant` | blocks, excused by `surviving-mutant` |
| `pytest-randomly`, `pytest-socket` | lines | `testing.flaky-order-or-network` | fix later |
| `vulture` | lines | `architecture-maintainability.complexity-dead-code-naming` | note |
| `import-linter` | base against head | `architecture-maintainability.structural-check-fails` | blocks |
| `cdk-nag` | base against head | `security.workflow-infra-high` for an error; `security.workflow-infra-medium-low` for a warning | blocks; fix later |
| `checkov-cdk`, `checkov-cfn` | base against head; lines | `security.tool-curated` when the rule id is curated; `security.tool-unscoped` otherwise | blocks; fix later |
| `zizmor` | lines | `security.workflow-infra-high` for high; `security.workflow-infra-medium-low` for medium and low; `security.tool-style` for informational | blocks; fix later; note |
| `ruff-lint` | lines | `correctness.tool-error`, `correctness.tool-warning`, or `correctness.tool-style` from the family draft | blocks; fix later; note |
| `actionlint` | lines | the same three correctness rows, from the kind draft | blocks; fix later; note |
| `cfn-lint`, `shellcheck` | lines | the same three correctness rows, from the tool's level | blocks; fix later; note |
| `markdownlint-cli2` | lines | `correctness.tool-style` | note |
| `cspell` | lines | `architecture-maintainability.tool-style` | note |
| `lychee` | base against head | `architecture-maintainability.tool-warning` | fix later |
| `ruff-format`, `shfmt` | not scanned | none | no record |

The family draft, the kind draft, and the curated Checkov ids are the second fence. The first fence stays the semgrep map.

```yaml
ruff_family_draft:
  F: error
  B: error
  S: error
  C4: warning
  UP: warning
  SIM: warning
  RUF: warning
  E: style
  W: style
  N: style
  I: style
actionlint_kind_draft:
  syntax-check: error
  job-needs: error
  events: error
  workflow-call: error
  glob: error
  matrix: error
  id: error
  action: error
  shell-name: error
  env-var: error
  runner-label: error
  permissions: warning
  credentials: warning  # actionlint kind, not a stored login
  shellcheck: warning
  pyflakes: warning
  expression: warning
  if-cond: warning
  deprecated-commands: style
checkov_curated:
  - CKV_AWS_62
  - CKV_AWS_63
  - CKV_AWS_356
  - CKV_AWS_20
  - CKV_AWS_53
  - CKV_AWS_54
  - CKV_AWS_55
  - CKV_AWS_56
  - CKV_AWS_57
  - CKV_AWS_70
```
