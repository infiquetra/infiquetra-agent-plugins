# Review records

Every source in saga's redesigned code review (tools, our own checks, the Jev sweep and the LLM
reviewer) writes the same records, and code computes what they mean. This document explains the
records, the rules the validator enforces, and the formula that turns them into outcomes, grades
and a merge answer. It was added by issue 148, card C1 of the review redesign (parent issue 147).

The machine-readable contract is [`review-records.schema.json`](review-records.schema.json). The
validator, the identity function and the writers are in `scripts/review_records.py`; the formula
is in `scripts/review_formula.py`. `scripts/review_command.py` (card C10a, issue 160) calls the
writers. The older `review_result.v2` shapes stay in place until card C10b deletes them.

## The six kinds

Every record names its `kind` and carries `schema: "review_records.v1"`.

| Kind | One per | Holds |
|---|---|---|
| `finding` | problem found | lens, the row and rule behind it, source, location, statement, closed-list labels, proof, flags, merge outcome; severity once computed |
| `measurement` | number a tool produced | lens, row, tool and version, metric, value, threshold, direction; `met` or `missed` once computed |
| `where_to_look` | classifier hit | lens, location, the questions that fired with their probabilities, classifier and model, and the LLM's answer: a finding, or cleared with a reason |
| `lens_grade` | lens per review | counts of blocking, fix-later and note items, the A–F grade, degraded inputs, and per language whether the lens may block |
| `review_run` | review | all of the above, plus card, repository, base and head commits, saga version, round, tool versions, usage (tokens, cost, seconds), an optional reviewers array (vendor, model, role, prompt and configuration fingerprints, and a note when the configuration differs), builder-record snapshots, the may-block answers, raw-output fingerprints and the merge answer |
| `builder_record` | unit | acceptance criteria and their checks, a declaration per policy question (applies or not, and the proving test), and every reason the builder gives |

Validate any of them with:

```bash
python3 plugins/saga/scripts/review_records.py validate <file>
```

Exit 0 accepts. Exit 1 refuses, printing one `<field path>: <why>` line per problem on standard
error (for example `location.lines: required when scope is "lines"` or
`findings.0.severity: ... the formula gives 'blocks'`). Exit 2 means the file is not JSON or names
no known kind.

## Finding fields

| Field | Values |
|---|---|
| `id` | the identity, `rf:` and 32 hex characters; see "Identity" |
| `subject` | `code` or `plan` |
| `lens` | `correctness`, `security`, `testing`, `architecture-maintainability` |
| `rule` | `{row, ref}`: the row identifier (below), or `judged` for an LLM finding; `ref` is the question or tool rule |
| `source` | `{kind: tool, name, version}`, `{kind: classifier, name, model}` or `{kind: llm, name, model}` |
| `location` | see "Locations" |
| `language` | `python`, `typescript`, `dart`, `rust`, `swift`, `markdown`, `shell`, `github-workflows`, `cloudformation`, `none` |
| `statement` | one sentence, on one line |
| `consequence`, `consequence_jev` | the closed list below, or `null`; required on an LLM finding |
| `trigger` | `normal-use`, `retry`, `interrupt`, `concurrency`, `old-data`, `other-caller`, `misuse-only`, or `null` |
| `evidence` | `reproduced`, `traced`, `suspected`, `tool-result` |
| `proof` | `test` or `output` when reproduced; `steps` (file-and-line) when traced; `raw_output`, a SHA-256 of the tool's raw output, for a tool result |
| `introduced` | whether this change introduced it |
| `degraded` | whether it was answered without the tool that should answer it |
| `unconfirmed` | true exactly when a reproduced LLM finding has no Jev consequence pick |
| `merge_outcome` | `null`, or `{outcome}` where outcome is `fixed`, `dismissed` (needs `reason`), `fixed-now`, `filed` (needs `issue`) or `left` |
| `severity`, `severity_basis`, `flags`, `enforced` | computed; refused on a finding handed in, required on one inside a stored review run |

Consequences come in three groups, most severe first:

- Harm: `data-lost-or-corrupted`, `money-or-resources-wrongly-moved`, `security-boundary-crossed`,
  `two-holders-of-one-exclusive-thing`, `wrong-result-reported-as-success`,
  `required-behaviour-missing`, `break-in-supported-use`.
- Visible: `fails-loudly-and-recoverably`, `misleads-a-person`.
- Upkeep: `costs-future-work`, `style`.

A secret-scanner finding (row `security.secret-in-diff`) carries its location, never the secret:
`secret`, `matched_text`, `excerpt` and `proof.output` are refused on it. Raw tool output stays on
the machine; records reference it by SHA-256.

## Locations

`location.scope` says what kind of location it is. Every scope needs `anchor`.

| Scope | Required | Allowed on |
|---|---|---|
| `lines` | `file`, `lines {start, end}`, `function` (`null` at module level or outside code) | any finding |
| `whole-project` | `file`; no `lines` | a whole-project tool result, such as a vulnerable dependency |
| `section` | `document`, `section` | a plan finding only |

The anchor is the flagged lines' text for a line location, the dependency or resource name for a
whole-project result, and the section heading for a plan finding.

## Identity

A finding's identity is a SHA-256 of its lens, `rule.row`, `rule.ref`, file or document, function
or section, and its anchor with whitespace collapsed. The line number is left out, so the identity
survives lines moving and re-indentation, and stays the same in a later round. Two rules on one
line, or one rule at two different anchors, get different identities. Everything it reads is on the
stored finding, so any reader can recompute it, and the validator refuses an `id` that does not
match. Builder reasons and where-to-look answers name findings by this identity.

## Outcomes

Each finding gets one of three outcomes, computed by code:

- **blocks**: one drops the lens to D, two or more to F; merge waits.
- **fix later**: one or two drop the lens to B, three or more to C, never lower; it never holds a
  merge.
- **note**: recorded; the grade does not move.

### Rows

Every fixed rule has an identifier, a base outcome, and sometimes a builder reason kind that
excuses it or a rule that reproduction makes it block. Tool adapters and our own checks cite these.

| Row | Base outcome | Excused by a builder reason of kind | Blocks when reproduced |
|---|---|---|---|
| `testing.uncovered-branch` | blocks | `coverage-gap` | |
| `testing.surviving-mutant` | blocks | `surviving-mutant` | |
| `testing.test-passes-before-change` | blocks | `test-passes-before-change` | |
| `testing.test-skipped-in-ci` | blocks | `test-skipped-in-ci` | |
| `testing.flaky-order-or-network` | fix later | | |
| `testing.fakes-code-under-test` | fix later | | |
| `testing.writes-live-system` | fix later | | yes |
| `security.scanner-high` | blocks | `scanner-false-positive` | |
| `security.scanner-medium-low` | fix later | | |
| `security.secret-in-diff` | blocks | | |
| `security.dependency-high` | blocks | `scanner-false-positive` | |
| `security.workflow-infra-high` | blocks | | |
| `security.required-test-missing` | blocks | | |
| `architecture-maintainability.structural-check-fails` | blocks | | |
| `architecture-maintainability.prose-rule-broken` | fix later | | yes (the LLM wrote a check that fails) |
| `architecture-maintainability.relocated-run-fails` | blocks | | |
| `architecture-maintainability.machine-specific-value` | fix later | | |
| `architecture-maintainability.undocumented-departure` | note | | |
| `architecture-maintainability.duplicate` | note | | |
| `architecture-maintainability.complexity-dead-code-naming` | note | | |
| `correctness.criterion-without-check` | blocks | | |
| `correctness.type-error` | blocks | | |
| `correctness.pattern.release-shares-cleanup` | blocks | `pattern-check` | |
| `correctness.pattern.swallowed-error` | blocks | `pattern-check` | |
| `correctness.pattern.silent-skip` | blocks | `pattern-check` | |
| `correctness.pattern.naive-time-comparison` | blocks | `pattern-check` | |
| `correctness.pattern.write-skips-shared-update` | blocks | `pattern-check` | |
| `correctness.pattern.money-as-float` | blocks | `pattern-check` | |
| `correctness.declared-question-untested` | blocks | | |
| `correctness.unupdated-mention` | blocks | `unaffected` | |
| `correctness.unupdated-mention-in-document` | fix later | | |
| `correctness.workflow-dead-end` | blocks | | |
| `correctness.ci-matrix-fails` | blocks | | |
| `<lens>.dispute`, for each lens | fix later, flagged for merge confirmation | | |

### Judged findings

An LLM finding cites `judged`, and code picks the row from its consequence, trigger and evidence.
These rows also serve the security and correctness tables' "an LLM finding it reproduced" and
"couldn't reproduce" rows, so on every lens a reproduced finding blocks only when it shows a harm.

| Row | When | Outcome |
|---|---|---|
| `judged.harm-reproduced` | harm, normal use or a legitimate condition, reproduced | blocks |
| `judged.harm-traced` | harm, normal use or a legitimate condition, traced or suspected | fix later |
| `judged.harm-misuse` | harm, misuse only | fix later |
| `judged.visible` | visible | fix later |
| `judged.upkeep` | upkeep | note |

For a reproduced LLM finding the LLM and Jev each pick the consequence. The lower group applies
(harm, then visible, then upkeep), and a disagreement is flagged for merge confirmation; between
two harms the LLM's pick stands, still flagged. When Jev cannot answer, the LLM's pick applies and
the finding is marked `unconfirmed`.

### The order of computation

`severity_basis.modifiers` names each step that changed the outcome:

1. The row's base outcome.
2. `reproduced`: a row that blocks when reproduced, and was.
3. `excused`: a builder reason of the row's kind, naming this finding's identity, makes it a note.
4. Caps that lower blocks to fix later: `degraded`; `classifier-only` (Jev never blocks);
   `unreproduced` (an LLM finding nobody reproduced).
5. `always-blocks`: a block that is a reproduced "data lost or corrupted" or "a security boundary
   crossed" harm.

`flags` holds `merge-confirmation` (a dispute), `consequence-disagreement` and `unconfirmed`.

### Grades, report-only lenses and merge

| Grade | When |
|---|---|
| A | no blocking and no fix-later items |
| B | one or two fix-later items |
| C | three or more fix-later items |
| D | one blocking item |
| F | two or more blocking items |

Notes never move a grade, and fix-later items never add up to a block. Measurements record `met`
or `missed` against their threshold but never move a grade; the gaps they summarise are counted
as findings.

The formula takes `may_block`, per lens and language, from the calibration file (card C2). A
lens or language with no answer only reports: it keeps its computed grade, and merge skips its
blocks (listed under `merge.report_only_blocks`). A reproduced "data lost or corrupted" or "a
security boundary crossed" finding blocks regardless. Merge is allowed when no block is enforced,
which is the same as every lens at C or better.

The formula is pure: the same inputs, in any order, give byte-identical output.

## The targeted reviewer's answer

The LLM reviewer (issue 158) does not write these records itself. It answers in its own shape,
[`targeted-reviewer-answer.schema.json`](targeted-reviewer-answer.schema.json), following
[`targeted-reviewer-prompt.md`](targeted-reviewer-prompt.md), and
`scripts/reviewer_answer.py` turns that answer into records:

```bash
python3 plugins/saga/scripts/reviewer_answer.py check --answer <answer> --items <where-to-look list> [--result <launch result>]
python3 plugins/saga/scripts/reviewer_answer.py records --answer <answer> --items <list> --result <launch result> [--no-jev]
```

`check` refuses the answer, one `<field>: <why>` line per problem, when it skips an item
(`items.2: where-to-look item 2 (src/sync/lease.py:5-30) has no answer`), carries any severity,
reproduces a finding without its test, command and output, or reports more open-search findings
than the cap. `records` fills each finding's identity, its `llm` source from the launch result and,
for a reproduced finding, Jev's consequence pick; when Jev cannot answer, `consequence_jev` is null
and `unconfirmed` is true. The proof keeps the reviewer's `command`, which the review command needs
to re-run the test.

## Storage

Records live in the issue's run record (`references/run-record.md`, "Review runs and builder
records"), written through `run_record.update` under the record's lock:

```bash
python3 plugins/saga/scripts/review_records.py record-builder --issue <N> --unit <U> <file>
python3 plugins/saga/scripts/review_records.py record-run --issue <N> <inputs-file>
```

`record-run` takes the findings and measurements in their input form, computes them, validates the
whole run and appends it to `review_cycles` with `loop: "review_run"`. When the inputs carry no
`builder_records`, the ones on the unit rows are used. A stored run embeds what the formula used,
so validating it recomputes every severity, grade and the merge answer and refuses any difference.
`python3 plugins/saga/scripts/review_formula.py compute <inputs-file>` prints the computation
without storing it.
