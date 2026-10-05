---
title: fleet-core + saga: the Jev sweep says where to look in a change
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

# fleet-core + saga: the Jev sweep says where to look in a change

### Objective

Saga cuts each change into small pieces with C4a's diff reader, and fleet-core's new `jev sweep` asks each piece the four lenses' bank questions through a swappable classifier (TypeSafe Jev today). The result is a where-to-look list: each location with the questions that fired, highest probability first, within a cap of 30 items and $1 per review. Saga runs the sweep from a build-time bundle, so the build loop and the review command share one sweep, and fleet-core's TypeSafe policy allows the code the sweep sends.

### Intent

Today (infiquetra-agent-plugins at origin/main 1f7137d):

- `jev` is the command-line front door to the TypeSafe client. Its subcommands are `ask`, `eval` and one per registered verb (`plugins/fleet-core/scripts/jev.py:180-221`). Each verb is a fixed question set about one whole state (`scripts/fleet_commons/jev_verbs.py:100-394`). Nothing splits a change into pieces; the `lenses` verb asks five yes/no questions of a whole diff (lines 171-182).
- The TypeSafe client redacts state and questions before any transport sees them (`typesafe_client.py:420-469`), caches answers by prepared state, questions and requested model (lines 863-883), and returns token counts, latency and the resolved model, but no price (`AskResult`, lines 223-255).
- `plugins/fleet-core/references/typesafe.md` lets diffs leave the machine, not whole functions or files (lines 13-19). House rule 7 logs every verdict with the resolved model version (line 96); house rule 9 rules out "adversarial screening" (line 98).
- Saga gets fleet-core code only as bundled copies of the modules its `fleet-bundle.json` declares, loaded through `plugins/saga/scripts/bundled_fleet.py`. Saga's price table (`plugins/saga/references/model-prices.yaml`) lists Claude models only.

What changes (plan.md, Change 5 "A Jev sweep that says where to look"; Change 8 "Build loop"):

- **Two halves, one card.** Saga extracts the pieces and `jev sweep` classifies them. A new fleet_commons module, which saga's `fleet-bundle.json` declares, holds the sweep, and `jev.py` gains a `sweep` subcommand. fleet-core stays standard-library only.
- **Pieces (saga).** Saga reads the change through C4a's diff reader. A piece is the whole changed function by default: Python's comes from the standard library's parser, other languages' from an external parser. This card's planning step picks that parser and this card adds its row to C4a's default tool list, so setup (C3) checks and installs it like any other row. Without it, the piece is the changed block plus about 20 lines around it, marked degraded. A question may instead ask for the block plus about 20 lines, or for a small whole file.
- **The classifier contract.** Every classifier takes the question, its options with definitions, the piece, its path and its language, and returns a probability per option plus its name, model, cost and time. Answers are cached. A replacement for Jev takes over only if it scores at least as well on the corpus (K3 measures it). Code reaches TypeSafe only through `typesafe_client.ask`, which removes secrets first.
- **The bank format.** Each question carries its lens, an identifier, its kind (yes/no or multiple-choice), options with definitions, examples, not-for lines, the condition that switches it on, and its piece size. This card defines the format, including how a switch-on condition is written; C7 writes the banks in it as JSON (JavaScript Object Notation) files in saga, and saga passes a bank to `jev sweep`.
- **Thresholds, caps and option order.** A question fires at its threshold from the calibration file (C2), which the corpus harness (K3) sets; until the file holds thresholds, the sweep takes its 30 most likely items. The list holds at most 30 items, highest probability first. The sweep spends at most $1 per review, priced from the client's token counts at a TypeSafe rate this card adds to saga's price table; whatever a cap cuts is listed as degraded. Multiple-choice questions are asked in two option orders and averaged (Jev leans toward the first option); yes/no questions once.
- **Output.** One where-to-look item per hit, in C1's record shape: location, questions fired, their probabilities, the classifier and its resolved model version. The reviewer's answer is added later (C8). Every sweep verdict goes to the verdict log with its resolved model version (house rule 7); the run record keeps the version, and C15 posts it. If the classifier fails or no key is set, the sweep returns no items and marks itself degraded, and the review goes on.
- **`typesafe.md`.** The data rule also allows code from the files a change touches, after the client's redaction: the changed function, the changed block with about 20 lines around it, or a small whole file a question asks for. The file records that the sweep only points the reviewer at places and never blocks or clears anything, so house rule 9's "adversarial screening" does not cover it, and that house rule 7 holds for every sweep verdict. It states the sweep's caps and the side it fails open on (house rule 8). `docs/engineering-journal/DECISIONS.md` records the wider data rule.

Depends on C1 (saga: review records, validation and the A–F formula) for the where-to-look record, and C4a (saga: build-loop tool framework reporting only what a change introduces) for the diff reader and the default tool list. The sweep applies C2's thresholds when the calibration file holds them. Its paths join C2's fingerprinted component list, in this card or in C2's (saga: the calibration file decides which lenses may block), whichever lands second.

### Risk

medium
A wrong sweep changes only where reviewers look, never what blocks, but it sends code from the change to a vendor and spends money on every review.

### Out-of-scope / non-goals

- The banks' contents and the policy list: C7 (saga: policy questions and question banks for the four lenses, reviewed by the operator). Thresholds and piece sizes tuned on the corpus: K3 (The harness: run the review on the corpus and write the calibration file), held in C2's file.
- Running the sweep in the build loop (C11) or the review command (C10a). The large language model (LLM) reviewer's answers, including Jev's pick of a reproduced finding's consequence: C8 (saga + agent-launcher: the targeted LLM reviewer).
- The where-to-look record's schema and validator (C1); this card emits that shape.
- Checking and installing the parser on a machine: setup (C3, saga: /saga:setup checks and prepares the machine and the repository), from the row this card adds. A local classifier model.
- Posting verdicts and model versions to Langfuse: C15 (fleet-core + saga: Langfuse review traces and outcomes at merge).

### Files expected to change

- `plugins/fleet-core/scripts/fleet_commons/jev_sweep.py` (new)
- `plugins/fleet-core/scripts/jev.py`
- `plugins/fleet-core/references/typesafe.md`
- `plugins/fleet-core/README.md`
- `plugins/fleet-core/CHANGELOG.md`
- `plugins/fleet-core/plugin.json` (and `.codex-plugin/plugin.json`, which repeats the version)
- `plugins/fleet-core/tests/test_jev_sweep.py` (new)
- `plugins/fleet-core/tests/test_jev_cli.py`
- `plugins/fleet-core/tests/test_typesafe_reference_drift.py`
- `plugins/saga/scripts/sweep_pieces.py` (new)
- `plugins/saga/fleet-bundle.json`
- `plugins/saga/scripts/_bundled/jev_sweep.py` (new; written by the bundler, never by hand)
- `plugins/saga/references/review-tools.yaml` (the parser's row)
- `plugins/saga/references/model-prices.yaml` (the TypeSafe entry)
- C2's fingerprinted component list, if C2 has landed (proposed in `plugins/saga/scripts/review_calibration.py`)
- `plugins/saga/tests/test_sweep_pieces.py` (new)
- `plugins/saga/tests/test_jev_sweep_bundle.py` (new)
- `plugins/saga/tests/test_entrypoints.py`
- `plugins/saga/tests/test_cost_report.py`
- `plugins/saga/CHANGELOG.md`
- `docs/engineering-journal/DECISIONS.md`

### Tests to add or update

- `plugins/fleet-core/tests/test_jev_sweep.py` (new; fake classifier or transport, no network): multiple-choice questions are asked in both orders and averaged, yes/no once; with a threshold a question fires only at or above it, and with none the 30 most likely items return; 31 hits return 30, highest first, the cut one degraded; at a given rate the $1 cap stops asking and lists what went unasked as degraded; a switch-on condition keeps a question off a piece it does not match; a repeat sweep answers from the cache; a secret in a piece never reaches the request body; each item and each verdict-log line carries the resolved model version; a failing classifier returns no items and a degraded mark; the module imports the standard library only.
- `plugins/fleet-core/tests/test_jev_cli.py`: the subcommand pin (lines 176-182) adds `sweep`, and `jev.py sweep --help` runs as a subprocess and exits 0.
- `plugins/fleet-core/tests/test_typesafe_reference_drift.py`: the caps and the three piece kinds `typesafe.md` states match the module, and the note on house rule 9 is present.
- `plugins/saga/tests/test_sweep_pieces.py` (new): a changed Python function is one piece; with a fake external parser, so is a changed function in another language; without the parser, the piece is the changed block plus about 20 lines, degraded; a question that asks for a small whole file gets the file; a rename with no edits gives no piece.
- `plugins/saga/tests/test_jev_sweep_bundle.py` (new): runs the bundled module through `bundled_fleet.load` with a fake classifier and passes every item through C1's validator.
- `plugins/saga/tests/test_entrypoints.py`: `jev_sweep` joins the bundled modules in `INTERNAL`.
- `plugins/saga/tests/test_cost_report.py`: the TypeSafe entry passes the shipped table's token-category check (lines 637-640), and its rate is pinned the way the Claude rates are (lines 598-619).

### Context library links

- `plugins/fleet-core/references/typesafe.md` (the data rule, the house rules, the verdict log)
- `plugins/fleet-core/README.md` ("How a consumer gets a module")
- `plugins/saga/references/model-prices.yaml` (how a rate is verified and dated)

### Acceptance criteria

- [ ] `python3 plugins/fleet-core/scripts/jev.py sweep --help` exits 0 and names its inputs.
- [ ] Saga cuts one piece per changed Python function; without the external parser, a piece is the changed block plus about 20 lines, marked degraded.
- [ ] C4a's default tool list carries the parser's row, so setup checks and installs it like any other row.
- [ ] With a fake classifier the list holds at most 30 items, highest first, and cut items are degraded; with no thresholds the sweep returns its 30 most likely items.
- [ ] Multiple-choice questions are asked in two option orders and averaged, yes/no questions once.
- [ ] `model-prices.yaml` carries a TypeSafe entry with its source and date; the sweep's spend is priced from the client's token counts at that rate and stops at $1, listing what went unasked as degraded.
- [ ] Every sweep verdict is logged with its resolved model version, and every item carries it.
- [ ] No request body leaves the client unredacted (asserted in `test_jev_sweep.py`).
- [ ] `typesafe.md` allows the three piece kinds after redaction, records that the sweep never blocks or clears anything and so is not adversarial screening, and states the caps and the fail-open side; `DECISIONS.md` records the wider data rule.
- [ ] `python3 scripts/bundle_fleet_module.py --check` passes with `jev_sweep` in saga's bundle.
- [ ] C2's fingerprinted component list names the sweep's paths, added here or by C2 if it lands second.

### Verification

```bash
python3 scripts/bundle_fleet_module.py
python3 scripts/bundle_fleet_module.py --check
python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
python3 -m pytest plugins/fleet-core/tests -q --import-mode=importlib
python3 -m pytest plugins/saga/tests -q --import-mode=importlib
git diff --check
```

### Notes / conventions

- For the planning step: names are proposals: `jev_sweep` (after the existing `jev_*.py` modules), `jev.py sweep`, and saga's `sweep_pieces.py`.
- For the planning step: pick the external parser for languages other than Python, one whose command-line output gives function boundaries (for example tree-sitter's), and write its row in the default tool list's format: languages, default version, version check and install command.
- For the planning step: the switch-on condition format (for example path patterns and languages), and the line limit for "a small whole file", within the client's state budget of 32,000 tokens (`typesafe_client.py:109-112`).
- For the planning step: `jev sweep` takes the bank, the pieces, the thresholds and the TypeSafe rate as inputs, so fleet-core reads no YAML (YAML Ain't Markup Language) and no saga file. Saga reads the thresholds and tuned piece sizes from the calibration file (a bank's piece size is the default until K3 tunes one) and the rate from `model-prices.yaml`.
- For the planning step: find TypeSafe's current price and record it with its source and date, as `model-prices.yaml`'s header asks. The table carries one `verified_on` date (line 18), so either re-verify the table when adding the rate or give the entry a date of its own. Map the client's `input_tokens` and `output_tokens` onto the five token categories `test_cost_report.py:637-640` requires, or teach that test a set of categories per vendor.
- For the planning step: each piece's questions go in one request (house rule 5), the two option orders as two entries in it, split by lens where the client's token budget requires. Verdict-log decision IDs carry the repository, head commit, piece and question, as the tier judgment's IDs carry the run (`typesafe.md` section 7).

### Handoff maturity
requirements-ready

### Suggested next action
/plan docs/brainstorms/2026-10-05-saga-review-redesign/cards/C6-jev-sweep.md

### Source context
- Source: docs/brainstorms/2026-10-05-saga-review-redesign/cards/C6-jev-sweep.md
- Source type: brainstorm
- Source title: fleet-core + saga: the Jev sweep says where to look in a change

## Created Issue

- URL: https://github.com/infiquetra/infiquetra-agent-plugins/issues/156
- Number: 156
- Created at: 2026-10-05T19:11:38.699875+00:00
