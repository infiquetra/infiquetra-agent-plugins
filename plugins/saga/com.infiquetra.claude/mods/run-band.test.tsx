import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import type { SagaRunStatus } from '../types/index.d.ts'
import { PLAN_PANE } from './plan-viewer.tsx'
import { REVIEW_PANE } from './review-pane.tsx'
import {
  BAND_REFRESH_MS,
  bandPlanKey,
  bandReviewKey,
  fitLine,
  RECORD_PAGE_CHARS,
  RECORD_PANE,
  recordPages,
  statusText,
} from './run-band.tsx'

const CWD = '/Users/operator/repo'
const RECORD = `${CWD}/.git/.claude/saga/runs/issue-412.json`
const LINE = '#412 · work · build loop pass 3, 2 failing · review cycle 1/3 · 7/10 lenses met'

const SURFACES = ['terminal', 'desktop'] as const

function band(overrides: { hasSurvey?: boolean; maxRows?: number; bodyColumns?: number } = {}) {
  return {
    component: 'AbovePrompt',
    props: {
      hasSurvey: overrides.hasSurvey ?? false,
      isWorking: false,
      maxRows: overrides.maxRows ?? 10,
      bodyColumns: overrides.bodyColumns ?? 100,
      scroll: { offset: 0, bodyRows: 9 },
      view: {},
    },
  } as const
}

const PANE = {
  component: 'Pane',
  requestId: RECORD_PANE,
  props: {
    title: 'Run record',
    isFocused: true,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

/** One run as `run_status.py summary --json` prints it, from the script's band fixture. */
function run(issue = 412, line = LINE, phase: string | null = 'work'): SagaRunStatus {
  return {
    issue,
    repo: 'infiquetra/example',
    next_step: 'run /work on the plan',
    updated_at: '2026-10-04T12:00:00Z',
    record_path: RECORD,
    phase,
    plan_path: null,
    plan_file: null,
    build_loop: {
      unit: 'u1',
      pass: 3,
      failing: 2,
      could_not_execute: 0,
      green: false,
      units_total: 1,
      units_green: 0,
    },
    review: {
      unit: 'u1',
      cycle: 1,
      standard_allowance: 3,
      escalated_allowance: 2,
      is_escalated: false,
      outcome: 'repairs_requested',
      lenses_met: 7,
      lenses_total: 10,
      lenses_not_run: 0,
    },
    band_line: line,
  }
}

function summaryOf(runs: SagaRunStatus[]) {
  return JSON.stringify({ schema: 'run_status.v1', repo_root: CWD, runs })
}

function recordOf(nextStep = 'run /work on the plan') {
  return JSON.stringify({
    schema: 'run_record.v1',
    issue: 412,
    repo: 'infiquetra/example',
    created_at: '2026-10-04T11:00:00Z',
    updated_at: '2026-10-04T12:00:00Z',
    admission: {},
    run_configuration: {},
    approval_scope: {},
    roster: [],
    units: [],
    review_cycles: [],
    next_step: nextStep,
  })
}

/** What `run_status.py review --json` prints: one met lens, or no review at all. */
function reviewViewOf(hasReview: boolean) {
  const review = {
    unit: 'u1',
    cycle: 1,
    loop: 'code_review',
    revision: 'a'.repeat(40),
    outcome: 'repairs_requested',
    reason: null,
    lenses: [{ lens: 'correctness', state: 'met', reason: null, derived_overall: 9.5, finding_count: 0, top: [], findings: [] }],
    unattributed_findings: [],
    advisory_count: 0,
    duplicate_count: 0,
  }
  return JSON.stringify({
    schema: 'review_view.v1',
    repo_root: CWD,
    issue: 412,
    record_path: RECORD,
    legacy_entries: 0,
    review: hasReview ? review : null,
  })
}

type Answer = { exitCode: number; stdout: string; stderr: string }

type Fake = {
  runs: string[][]
  statuses: (string | undefined)[]
  toasts: string[]
  opened: string[]
  clock: ReturnType<typeof mock.clock>
  summary: Answer
  record: Answer
  /** The plan the run names, when it names one. */
  plan: { file: string; text: string } | null
  /** Whether the run has a code review result. */
  review: boolean
}

function ok(stdout: string): Answer {
  return { exitCode: 0, stdout, stderr: '' }
}

/** The band's summary reads: `--all-active` is the band's, and a plain `--issue` read is a pane's. */
function bandReads(fake: Fake): string[][] {
  return fake.runs.filter((argv) => argv.includes('summary') && argv.includes('--all-active'))
}

/** Answer every engine call the saga mods make. */
function fake(on: On): Fake {
  const state: Fake = {
    runs: [],
    statuses: [],
    toasts: [],
    opened: [],
    clock: mock.clock(on),
    summary: ok(summaryOf([run()])),
    record: ok(recordOf()),
    plan: null,
    review: false,
  }
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('command.register', async ($, e) => ({ value: { command: e.name } }))
  on('tool.register', async ($, e) => ({ value: { tool: e.name } }))
  on('session.cwd', async () => ({ value: CWD }))
  on('process.run', async ($, e) => {
    state.runs.push([...e.argv])
    const script = e.argv[1] ?? ''
    let answer: Answer
    if (script.endsWith('/run_record.py')) answer = state.record
    else if (e.argv.includes('review')) answer = ok(reviewViewOf(state.review))
    else if (e.argv.includes('--all-active')) answer = state.summary
    else {
      const plan = state.plan
      const at = e.argv.indexOf('--issue')
      const issue = at === -1 ? 412 : Number(e.argv[at + 1])
      const row = { ...run(issue), plan_path: 'docs/plans/p.md', plan_file: plan === null ? null : plan.file }
      answer = ok(summaryOf([plan === null ? { ...row, plan_path: null, plan_file: null } : row]))
    }
    return { value: { ...answer, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('fs.stat', async ($, e) => {
    if (state.plan === null || e.path !== state.plan.file) throw new Error(`ENOENT: ${e.path}`)
    return { value: { kind: 'file', size: state.plan.text.length, mtimeMs: 1, isLink: false, realPath: e.path } }
  })
  on('fs.read', async ($, e) => {
    if (state.plan === null || e.path !== state.plan.file) throw new Error(`ENOENT: ${e.path}`)
    return { value: state.plan.text }
  })
  on('turn.complete', async ($, e) => ({ text: e.answer }))
  on('ui.status', async ($, e) => {
    state.statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.toast', async ($, e) => {
    state.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.open', async ($, e) => {
    state.opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.panes', async () => ({ value: [] }))
  // Beneath the band: what the prompt site draws when no plugin does.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="beneath" />
  })
  return state
}

async function start($: Engine, fakes: Fake) {
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
  await fakes.clock.settle()
}

function turnComplete($: Engine, agentId?: string) {
  const turn = { answer: 'done', durationMs: 1, isAborted: false, turnId: 't1', reason: 'answer' } as const
  return $.turn.complete(agentId === undefined ? turn : { ...turn, agentId })
}

type Ui = { findAll: (q: { type: string }) => Promise<{ text: string }[]> }

async function texts(ui: Ui): Promise<string[]> {
  return (await ui.findAll({ type: 'Text' })).map((text) => text.text)
}

describe('the run status band', () => {
  test("given a fixture run, draws the run's line on terminal and desktop", async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    expect(bandReads(fakes)).toEqual([
      ['python3', expect.stringMatching(/\/scripts\/run_status\.py$/), '--repo-root', CWD, 'summary', '--all-active', '--json'],
    ])
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band() })
      expect(await ui.find({ type: 'Text', text: LINE })).toBeDefined()
      for (const key of ['band-plan-412', 'band-review-412', 'record', 'hide']) {
        expect(await ui.find({ type: 'Button', key })).toBeDefined()
      }
      await ui.unmount()
    }
  })

  test('with no run record, draws nothing and clears the status line', async ($, on) => {
    const fakes = fake(on)
    fakes.summary = ok(summaryOf([]))
    await start($, fakes)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band() })
      expect(await ui.find({ type: 'Box', key: 'beneath' })).toBeDefined()
      expect(await ui.findAll({ type: 'Text' })).toEqual([])
      expect(await ui.findAll({ type: 'Button' })).toEqual([])
      await ui.unmount()
    }
    expect(fakes.statuses).toEqual([undefined])
  })

  test('a run that closes while the checkout stays on its branch leaves the band and the status line', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    expect(fakes.statuses).toEqual(['saga #412 · work'])
    // run_status.py leaves a closed run (empty next step) out under --all-active, even the branch's own.
    fakes.summary = ok(summaryOf([]))
    await fakes.clock.advance(BAND_REFRESH_MS)
    expect(bandReads(fakes)).toHaveLength(2)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band() })
      expect(await ui.find({ type: 'Box', key: 'beneath' })).toBeDefined()
      expect(await ui.findAll({ type: 'Text' })).toEqual([])
      expect(await ui.findAll({ type: 'Button' })).toEqual([])
      await ui.unmount()
    }
    expect(fakes.statuses).toEqual(['saga #412 · work', undefined])
  })

  test('one line per active run, cut to the band width and its rows', async ($, on) => {
    const fakes = fake(on)
    fakes.summary = ok(summaryOf([run(412), run(500, '#500 · plan'), run(501, '#501 · plan')]))
    await start($, fakes)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band({ maxRows: 3, bodyColumns: 20 }) })
      expect(await texts(ui)).toEqual([fitLine(LINE, 20), '#500 · plan'])
      await ui.unmount()
    }
    expect(fitLine(LINE, 20)).toBe('#412 · work · build…')
  })

  test('Hide on the terminal leaves the band hidden on the desktop for the session', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    const terminal = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    await terminal.press({ key: 'hide' })
    expect(await terminal.find({ type: 'Text', text: LINE })).toBeUndefined()
    await terminal.unmount()
    await fakes.clock.advance(BAND_REFRESH_MS)
    const desktop = await $.ui.mount({ plugin: 'saga', surface: 'desktop', ...band() })
    expect(await desktop.find({ type: 'Box', key: 'beneath' })).toBeDefined()
    expect(await desktop.findAll({ type: 'Text' })).toEqual([])
    await desktop.unmount()
  })

  test('yields to a survey', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band({ hasSurvey: true }) })
      expect(await ui.find({ type: 'Box', key: 'beneath' })).toBeDefined()
      await ui.unmount()
    }
  })

  test('an unreadable read keeps the line it showed', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    fakes.summary = { exitCode: 0, stdout: JSON.stringify({ schema: 'run_status.v9', runs: [] }), stderr: '' }
    await fakes.clock.advance(BAND_REFRESH_MS)
    expect(bandReads(fakes)).toHaveLength(2)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    expect(await ui.find({ type: 'Text', text: LINE })).toBeDefined()
  })
})

describe("the band's buttons", () => {
  test('Plan and Review open the plan viewer and review pane for the run, saying why when there is nothing', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    for (const surface of SURFACES) {
      fakes.runs = []
      fakes.toasts = []
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...band() })
      await ui.press({ key: bandPlanKey(412) })
      await ui.press({ key: bandReviewKey(412) })
      // Each pane module read its own view for #412 and had nothing to open.
      expect(fakes.runs).toEqual([
        ['python3', expect.stringMatching(/run_status\.py$/), '--repo-root', CWD, 'summary', '--issue', '412', '--json'],
        ['python3', expect.stringMatching(/run_status\.py$/), '--repo-root', CWD, 'review', '--issue', '412', '--json'],
      ])
      expect(fakes.toasts).toEqual([
        'plan-view: #412 has no plan recorded yet. Name one: /plan-view docs/plans/<file>.md',
        'review-view: no review result recorded for #412.',
      ])
      expect(fakes.opened).toEqual([])
      await ui.unmount()
    }
  })

  test('Plan and Review open their panes when the run has a plan and a review', async ($, on) => {
    const fakes = fake(on)
    fakes.plan = { file: `${CWD}/docs/plans/p.md`, text: '# Plan\n\n## Step one\n\nDo it.\n' }
    fakes.review = true
    await start($, fakes)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    await ui.press({ key: bandPlanKey(412) })
    await ui.press({ key: bandReviewKey(412) })
    expect(fakes.opened).toEqual([PLAN_PANE, REVIEW_PANE])
    expect(fakes.toasts).toEqual([])
  })

  test('Record opens the raw record pane, paged under the Code limit', async ($, on) => {
    const fakes = fake(on)
    fakes.record = ok(recordOf('x'.repeat(25_000)))
    await start($, fakes)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    await ui.press({ key: 'record' })
    expect(fakes.opened).toEqual([RECORD_PANE])
    expect(fakes.runs.at(-1)).toEqual(['python3', expect.stringMatching(/\/scripts\/run_record\.py$/), 'show', '412'])
    for (const surface of SURFACES) {
      const pane = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      const first = await pane.find({ type: 'Code' })
      expect(String(first?.props.source).length).toBeLessThanOrEqual(10_000)
      expect(String(first?.props.source)).toMatch(/^\{\n {2}"schema": "run_record\.v1"/)
      expect(await pane.find({ type: 'Text', text: /page 1 of 3$/ })).toBeDefined()
      await pane.press({ key: 'next' })
      expect(await pane.find({ type: 'Text', text: /page 2 of 3$/ })).toBeDefined()
      await pane.press({ key: 'prev' })
      await pane.unmount()
    }
  })

  test('a record that cannot be read is said in a toast, and no pane opens', async ($, on) => {
    const fakes = fake(on)
    fakes.record = { exitCode: 2, stdout: '', stderr: 'run_record: no record for issue 412' }
    await start($, fakes)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    await ui.press({ key: 'record' })
    expect(fakes.opened).toEqual([])
    expect(fakes.toasts).toEqual(['saga: could not read the run record for #412 (no-record): run_record: no record for issue 412'])
  })
})

describe('the status line and refreshing', () => {
  test("the status line shows the first run's issue and phase alone", async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    expect(fakes.statuses).toEqual(['saga #412 · work'])
    expect(statusText([run(7, '#7', null)])).toBe('saga #7')
    expect(statusText([])).toBeUndefined()
  })

  test('the status line appends the missing-tools notice verbatim, naming the tools and /saga:setup', async ($, on) => {
    const fakes = fake(on)
    fakes.summary = ok(
      summaryOf([
        {
          ...run(),
          setup_notice: {
            text: 'Missing ruff, mypy. Run /saga:setup.',
            missing_tools: ['ruff', 'mypy'],
            sandbox_unavailable: false,
          },
        },
      ]),
    )
    await start($, fakes)
    expect(fakes.statuses).toEqual(['saga #412 · work · Missing ruff, mypy. Run /saga:setup.'])
    expect(statusText([{ ...run(), setup_notice: null }])).toBe('saga #412 · work')
    expect(statusText([{ ...run(), setup_notice: { text: '', missing_tools: [], sandbox_unavailable: false } }])).toBe(
      'saga #412 · work',
    )
  })

  test('the band still shows the active saga with its plan', async ($, on) => {
    const fakes = fake(on)
    fakes.summary = ok(
      summaryOf([
        {
          ...run(147, '#147 · work · build loop pass 2, green', 'work'),
          review: null,
          setup_notice: null,
          plan_path: 'docs/plans/program.md',
          plan_file: `${CWD}/docs/plans/program.md`,
        },
      ]),
    )
    fakes.plan = { file: `${CWD}/docs/plans/program.md`, text: '# Program\n\n## Step one\n\nDo it.\n' }
    await start($, fakes)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...band() })
    expect(await ui.find({ type: 'Text', text: '#147 · work · build loop pass 2, green' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: bandPlanKey(147) })).toBeDefined()
    await ui.press({ key: bandPlanKey(147) })
    expect(fakes.opened).toEqual([PLAN_PANE])
    expect(fakes.toasts).toEqual([])
    expect(fakes.statuses).toEqual(['saga #147 · work'])
  })

  test('refreshes at start, every minute, and after a main-loop turn but not a subagent turn', async ($, on) => {
    const fakes = fake(on)
    await start($, fakes)
    expect(bandReads(fakes)).toHaveLength(1)
    await fakes.clock.advance(BAND_REFRESH_MS)
    expect(bandReads(fakes)).toHaveLength(2)
    fakes.summary = ok(summaryOf([run(412, '#412 · code-review', 'code-review')]))
    await turnComplete($)
    await fakes.clock.settle()
    expect(bandReads(fakes)).toHaveLength(3)
    expect(fakes.statuses.at(-1)).toBe('saga #412 · code-review')
    await turnComplete($, 'agent-1')
    await fakes.clock.settle()
    expect(bandReads(fakes)).toHaveLength(3)
  })

  test("a Bash call that ran a saga state script refreshes; another command does not", async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Bash' }, async () => ({ result: {}, text: 'ran' }))
    await start($, fakes)
    await $.tool.call({ tool: 'Bash', command: 'git status' })
    await fakes.clock.settle()
    expect(bandReads(fakes)).toHaveLength(1)
    await $.tool.call({ tool: 'Bash', command: 'python3 plugins/saga/scripts/build_loop.py --issue 412' })
    await fakes.clock.settle()
    expect(bandReads(fakes)).toHaveLength(2)
  })
})

describe('the record pages', () => {
  test('every page fits a Code block and the pages join back to the record', () => {
    const json = JSON.stringify({ rows: Array.from({ length: 2_000 }, (_, i) => ({ i, text: 'y'.repeat(20) })) }, null, 2)
    const pages = recordPages(json)
    expect(pages.length).toBeGreaterThan(1)
    for (const page of pages) expect(page.length).toBeLessThanOrEqual(RECORD_PAGE_CHARS)
    expect(pages.join('')).toBe(json)
  })
})
