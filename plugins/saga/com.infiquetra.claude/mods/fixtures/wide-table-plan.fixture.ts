// A plan whose tables the viewer must draw at the pane's width (issue #175).
// GOLDEN_PAGE and GOLDEN_STACKED are copied from the issue. They are the oracle:
// nothing here is produced by fitTables.

// The Decisions table is 80 columns as written and 150 after linkifyRefs turns
// `plugins/saga/scripts/run_status.py:12` into a file link at repo root
// /Users/operator/repo. Both widths are above a 71-column pane and 150 is within
// a 160-column viewport, so a test that stacks at bodyColumns 71 still shows a
// grid if the code reads viewport.columns. A cell of 200 characters would be
// wider than that viewport, and both widths would stack.

const DECISIONS_TABLE = [
  '| Decision | Detail | Owner | Call |',
  '| --- | --- | --- | --- |',
  '| alpha | Keep the gate beside the combined branch | saga | yes |',
  '| bravo | See `plugins/saga/scripts/run_status.py:12` now | saga | High ✅ |',
  '| charlie | Record the operator answer beside staffing | saga | yes |',
  '| delta | Leave desktop and mobile renderers alone | saga | yes |',
  '| echo | Repeat the header when a page boundary hits | saga | yes |',
  '| foxtrot | Stack only when the pane is narrower than it | saga | yes |',
].join('\n')

export const GOLDEN_PAGE = [
  'Pick the review shape.',
  '',
  '| Option | What it does | Cost |',
  '|:---|:---|---:|',
  '| A | Runs **every** lens and reports each finding with its file. | High ✅ |',
  '| B | Runs only the lenses `plugins/saga/scripts/review_roster.py` names. |',
  '| C \\| D | Skips review. | None |',
  '',
  'Then record the choice.',
].join('\n')

export const GOLDEN_STACKED = [
  'Pick the review shape.',
  '',
  '**Option:** A',
  '',
  '**What it does:** Runs **every** lens and reports each finding with its file.',
  '',
  '**Cost:** High ✅',
  '',
  '* * *',
  '',
  '**Option:** B',
  '',
  '**What it does:** Runs only the lenses `plugins/saga/scripts/review_roster.py` names.',
  '',
  '**Cost:** —',
  '',
  '* * *',
  '',
  '**Option:** C \\| D',
  '',
  '**What it does:** Skips review.',
  '',
  '**Cost:** None',
  '',
  'Then record the choice.',
].join('\n')

const STATUS_TABLE = ['| State | Note |', '| --- | --- |', '| open | short |', '| done | clean |'].join('\n')

export const WIDE_TABLE_PLAN = [
  '# Wide table plan',
  '',
  'A fixture plan for the pane.',
  '',
  '## Decisions',
  '',
  DECISIONS_TABLE,
  '',
  '## Shape',
  '',
  GOLDEN_PAGE,
  '',
  '## Status',
  '',
  STATUS_TABLE,
  '',
  '## Example',
  '',
  '```markdown',
  DECISIONS_TABLE,
  '```',
  '',
].join('\n')
