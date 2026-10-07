# Review calibration

`plugins/saga/references/review-calibration.json` records whether a lens may block in a language. `plugins/saga/scripts/review_calibration.py` reads it. The corpus harness writes the verdicts. This file stores the pass marks and does not change them. K3 writes the verdicts and does not edit `marks`.

`schema` is `review_calibration.v1`. No other top-level key is accepted.

| Key | No run yet | After a run is recorded |
|---|---|---|
| `corpus_run` | `no-run` | `recorded` |
| `fingerprint` | `{}` | one sha256 per component path |
| `corpus_version` | `null` | an identifier |
| `jev_model_version` | `null` | an identifier |
| `cost_usd` | `null` | a number, zero or greater |
| `langfuse_run_id` | `null` | an identifier |
| `reviewer_configuration` | `null` | 64 hex characters, or it stays `null` |
| `marks` | the fixed object below | the same object |
| `lenses` | every lens, drift `report-only`, no languages | overall numbers and language verdicts |
| `thresholds` | `[]` | question rows |

An identifier matches `^[A-Za-z0-9][A-Za-z0-9._:/-]*$`. A sha256 is 64 lowercase hex characters. Counts are JSON numbers, not numeric strings. Free text is refused.

## Marks

`marks` is data the harness reads. `may-block` does not compare a verdict's numbers with these fractions.

| Lens | Must block | May block of clean changes |
|---|---|---|
| `security` | 9 / 10 | 1 / 10 |
| `testing` | 9 / 10 | 1 / 10 |
| `correctness` | 8 / 10 | 1 / 10 |
| `architecture-maintainability` | 6 / 10 | 1 / 20 |

`language_guard` is `must_catch` 7 / 10 and `may_block_clean` 2 / 10. `repeat_run` is `may_flip` 1 / 10. `deterministic` is `identical`: the deterministic part gives the same grade every time it sees the same input.

## Lenses

A no-run lens has `drift` `report-only`, no `overall`, and `languages` `{}`. A recorded lens requires `overall` (six counts: held-out blocked, defects, false blocks and clean changes, plus repeat flips and repeat cases). `languages` may omit a language. `drift` is `report-only` or `as-recorded`. One `report-only` line makes every language of that lens report only. A language object has `verdict` (`cleared` or `report-only`) and the same six counts.

## Thresholds

A threshold row is `question` (an identifier), `threshold` (a number) and `piece_size` (a positive integer). An empty `thresholds` list means the sweep takes its 30 most likely items. This card only stores the list.

## Component paths

The fingerprint is a sha256 of each of these files, in order. `scripts/check_repo.py` calls the one implementation in `review_calibration.py`. While `corpus_run` is `no-run`, the bytes are not compared. Once a run is recorded, a changed or missing file fails the repository check and names that path.

A component is a file. A directory is a missing component.

The kinds on the list today:

- The formula and the record schema (C1).
- The default tool list, its diff and coverage helpers, and the Semgrep pack's content hash. The cached Semgrep rule packs are not a repository path. The pack's sha256 sits beside the pin in `review-tools.yaml`, and that yaml is on the list, so a pin change changes the fingerprint.
- The reviewer's prompt, answer schema, and launch settings. The launch settings are `targeted-reviewer-launch.json` (vendor and model).
- The sweep: `sweep_pieces.py`, `model-prices.yaml`, and fleet-core's `jev_sweep.py` (C6).
- The Python, CDK, shell, workflow, and Markdown adapters (C4b).
- The scripted checks (issue 155): `scripts/review_checks.py`.
- Our checks: the six saga pattern rules, listed as files (C5).

Not on the list yet: question banks and the policy questions, and the review command. The scripted checks in `review_checks.py` are on the list. A card that adds a review component adds its paths in the same change.

Instruction files are recorded in `reviewer_configuration` and are not fingerprinted. `may-block` does not read that field. `review_records.py` is not a component. The record schema is the contract; the validator is held to that schema by its own drift test. `reviewer_answer.py` is not a component either. It refuses an answer and caps an open-search finding; the prompt, the answer schema and the launch settings are the fingerprinted parts, and the module is held by its own tests.

```
plugins/saga/scripts/review_formula.py
plugins/saga/references/review-records.schema.json
plugins/saga/scripts/review_tools.py
plugins/saga/scripts/review_diff.py
plugins/saga/scripts/coverage_lines.py
plugins/saga/scripts/review_adapters_all_languages.py
plugins/saga/references/review-tools.yaml
plugins/saga/scripts/review_adapters_python.py
plugins/saga/scripts/review_adapters_infrastructure.py
plugins/saga/scripts/review_adapters_shell.py
plugins/saga/scripts/review_adapters_workflows.py
plugins/saga/scripts/review_adapters_markdown.py
plugins/saga/references/targeted-reviewer-prompt.md
plugins/saga/references/targeted-reviewer-answer.schema.json
plugins/saga/references/targeted-reviewer-launch.json
plugins/fleet-core/scripts/fleet_commons/jev_sweep.py
plugins/saga/scripts/sweep_pieces.py
plugins/saga/references/model-prices.yaml
plugins/saga/scripts/review_checks.py
plugins/saga/references/semgrep/release-shares-cleanup-block.yaml
plugins/saga/references/semgrep/swallowed-error.yaml
plugins/saga/references/semgrep/silent-skip.yaml
plugins/saga/references/semgrep/write-skips-shared-update-path.yaml
plugins/saga/references/semgrep/naive-time-comparison.yaml
plugins/saga/references/semgrep/money-as-floating-point.yaml
```

## The answer

`python3 plugins/saga/scripts/review_calibration.py may-block --lens security --language python` prints one line and exits 0. On the committed file the line is `report-only no-run`.

The calibration file and the component bytes come from the installed saga, the directory that contains this script. `--root` does not select that file. The profile is the base commit's `.saga-profile.json`, passed as `--profile` or as `--root`. A review never passes the reviewed head as `--root`, `--file` or `--profile`: a head can turn its own lenses to report-only.

The first matching reason wins: no run, a stale fingerprint (the path is the third word), drift, no verdict for the language, a profile pin of another version or rule set on a tool that serves the lens, a report-only verdict, then `yes cleared`. An unknown lens, an unknown language, a malformed file, or a malformed profile exits 2 and prints no answer. An unreadable profile is a malformed profile. The default is never `yes`.
