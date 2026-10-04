---
date: 2026-10-03
topic: saga-staffing-testing-mods
maturity: requirements-ready
---

# staffing U3 — Record cost per completed unit in the run record

### Objective

Give every unit in a saga run record a usage block, and add a report that compares cost per
completed unit by role and tier, so the Opus builder decision is checked against measured cost.

### Intent

**The record.** Each unit row in `run_record.v1` gains a `usage` block. It holds one entry per
model session that worked the unit: vendor, model, effort, and token counts by category (uncached
input, cache read, 5-minute cache write, 1-hour cache write, output). Build-loop passes and review
cycles are already in the record and are read, not copied. A row's key set is deliberately not
fixed in `plugins/saga/references/run-record.md`, so this needs no record version bump.

**The writer.** A `run_record.py usage add` subcommand appends one entry. It is the one portable
write path. Any harness integration can call it, including the Claude Code token-capture mod that
lives under the mods parent.

**The report.** A cost report reads run records and prints cost per completed unit grouped by role
and tier. It prices tokens from a dated price table and says how old that table is. It flags a
table older than 30 days rather than silently using it. A completed unit is one whose build loop
went green and whose review reached a terminal outcome.

### Risk

medium
It adds a block to a shared record that several consumers read, but the row's key set is open by
contract and the change is additive.

### Out-of-scope / non-goals

- No live capture inside Claude Code; that is a mod card.
- No capture for non-Claude vendors in this unit beyond what a caller passes to `usage add`.
- No budget enforcement or spend ceiling; this measures and reports.

### Files expected to change

- `plugins/saga/scripts/run_record.py`
- `plugins/saga/references/run-record.md`
- `plugins/saga/scripts/cost_report.py` (new)
- `plugins/saga/references/model-prices.yaml` (new, dated)
- `plugins/saga/CHANGELOG.md`

### Tests to add or update

- `plugins/saga/tests/test_run_record.py`: `usage add` appends, preserves other consumers' keys,
  and refuses an unknown token category.
- `plugins/saga/tests/test_cost_report.py` (new): grouping by role and tier, the completed-unit
  rule, and the stale price-table flag.

### Context library links

- `plugins/saga/references/run-record.md`

### Acceptance criteria

- [ ] `uv run python plugins/saga/scripts/run_record.py usage add --help` documents the token categories.
- [ ] `uv run python plugins/saga/scripts/cost_report.py --help` runs, and on a fixture record prints cost per completed unit grouped by role and tier.
- [ ] A price table older than 30 days produces a visible staleness warning in the report.

### Verification

```bash
uv run python plugins/saga/scripts/run_record.py usage add --help
uv run python plugins/saga/scripts/cost_report.py --help
python3 -m pytest plugins/saga/tests/test_run_record.py plugins/saga/tests/test_cost_report.py -q --import-mode=importlib
python3 scripts/check_repo.py
git diff --check
```
