import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import type { SagaReview, SagaReviewFinding, SagaReviewLens, SagaStateReview } from '../types/index.d.ts'
import { GOLDEN_PAGE } from './fixtures/wide-table-plan.fixture.ts'
import { fitTables } from './plan-sections.ts'
import {
  costLine,
  FINDING_TEXT_LIMIT,
  findingText,
  gradeLabel,
  lensLabel,
  quoteText,
  roundLabel,
  stateFindingHeading,
  stateHeading,
  whereToLookLabel,
} from './review-findings.ts'
import { REVIEW_PANE, REVIEW_POLL_MS } from './review-pane.tsx'

const CWD = '/Users/operator/repo'
const RECORD = `${CWD}/.git/.claude/saga/runs/issue-108.json`
const REVISION = 'abcdef0123456789abcdef0123456789abcdef01'

const PANE = {
  component: 'Pane',
  requestId: REVIEW_PANE,
  props: {
    title: 'Review',
    isFocused: true,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const SURFACES = ['terminal', 'desktop'] as const

function finding(severity: string, path: string, line: number, category: string): SagaReviewFinding {
  return {
    id: `${path}:${line}:${category}`,
    severity,
    path,
    line,
    category,
    dimension: 'd',
    evidence: `${path}:${line} shows ${category}`,
    impact: `${category} matters`,
    status: 'open',
    confidence: 'medium',
  }
}

function lens(name: string, state: SagaReviewLens['state'], findings: SagaReviewFinding[], extra: Partial<SagaReviewLens> = {}): SagaReviewLens {
  return {
    lens: name,
    state,
    reason: null,
    derived_overall: null,
    finding_count: findings.length,
    top: findings.slice(0, 3),
    findings,
    ...extra,
  }
}

const SECURITY = [finding('P0', 'src/a.py', 12, 'injection'), finding('P2', 'src/b.py', 4, 'weak-check')]

/** The review_view.v1 fixture: one lens in each state, and a selected lens with no row. */
function reviewOf(outcome = 'review_incomplete', cycle = 2): SagaReview {
  return {
    unit: 'issue-108',
    cycle,
    loop: 'code_review',
    revision: REVISION,
    outcome,
    reason: null,
    lenses: [
      lens('correctness', 'met', [], { derived_overall: 9.5 }),
      lens('security', 'not_met', SECURITY, { derived_overall: 4.5 }),
      lens('testing', 'not_run', [], { reason: 'could not execute' }),
      lens('performance', 'unscored', [finding('P3', 'src/c.py', 1, 'slow-loop')], {
        reason: 'establishes no threshold: no fixtures, or no qualified executor',
      }),
      lens('docs', 'not_run', [], { reason: 'no result recorded' }),
    ],
    unattributed_findings: [],
    advisory_count: 0,
    duplicate_count: 0,
  }
}

function viewOf(review: SagaReview | SagaStateReview | null) {
  return { schema: 'review_view.v1', repo_root: CWD, issue: 108, record_path: RECORD, legacy_entries: 0, review }
}

/** The review_state.v1 fixture: two graded lenses, two where-to-look states, two rounds of deltas. */
const STATE_DOC = {
  schema: 'review_state.v1',
  card: 108,
  repo: 'infiquetra/example',
  round: 2,
  lenses: [
    { lens: 'testing', grade: 'A', blocking: 0, fix_later: 1 },
    { lens: 'security', grade: 'B', blocking: 1, fix_later: 0 },
  ],
  findings: [
    { id: 'rf:aaa', lens: 'testing', severity: 'fix-later', statement: 'a flaky test hides the suite', guard: false, merge_outcome: null },
    { id: 'rf:bbb', lens: 'security', severity: 'blocks', statement: 'a traced write to the live store', guard: true, merge_outcome: null },
  ],
  pending_choices: ['merge-blocking', 'fix-later:rf:aaa'],
  merge_blocking: ['rf:bbb'],
  merge: { waiting: true, reason: '1 blocking item left at the round limit awaits the operator' },
  disputes: [],
  consequence_disagreements: [],
  unconfirmed: [],
  where_to_look: [
    { lens: 'security', location: 'src/a.py:12-20', questions: ['q1'], state: 'answered', finding_id: 'rf:bbb' },
    { lens: 'testing', location: 'src/b.py:4-9', questions: [], state: 'cleared', reason: 'covered elsewhere' },
  ],
  tools: { ran: { ruff: '0.15.18' }, missing_notice: 'Missing mypy. Run /saga:setup.', missing_tools: ['mypy'] },
  degraded_inputs: [],
  rounds: [
    { round: 1, new_blocking: ['rf:bbb'], cleared_blocking: [] },
    { round: 2, new_blocking: [], cleared_blocking: [] },
  ],
  cost: { tokens_in: 10, tokens_out: 20, cost_usd: 0.05, seconds: 30 },
  unattended: false,
}

function stateOf(): SagaStateReview {
  return {
    state_schema: 'review_state.v1',
    round: 2,
    loop: 'review_run',
    revision: REVISION,
    outcome: 'blocked',
    lenses: STATE_DOC.lenses,
    pending_choices: STATE_DOC.pending_choices,
    merge: STATE_DOC.merge,
    state: STATE_DOC,
  } as SagaStateReview
}

type Fake = {
  opened: string[]
  closed: string[]
  toasts: string[]
  fills: string[]
  runs: string[][]
  mtimeMs: number
  isFilled: boolean
  clock: ReturnType<typeof mock.clock>
  review: { exitCode: number; stdout: string; stderr: string }
  summary: { exitCode: number; stdout: string; stderr: string }
}

function answer(review: SagaReview | SagaStateReview | null): Fake['review'] {
  return { exitCode: 0, stdout: JSON.stringify(viewOf(review)), stderr: '' }
}

function summaryAnswer(): Fake['summary'] {
  return {
    exitCode: 0,
    stdout: JSON.stringify({
      schema: 'run_status.v1',
      repo_root: CWD,
      runs: [{ issue: 108, next_step: 'review', phase: 'review', band_line: '#108 · review' }],
    }),
    stderr: '',
  }
}

/** Answer every engine call the pane makes. */
function fake(on: On): Fake {
  const state: Fake = {
    opened: [],
    closed: [],
    toasts: [],
    fills: [],
    runs: [],
    mtimeMs: 1,
    isFilled: true,
    clock: mock.clock(on),
    review: answer(reviewOf()),
    summary: { exitCode: 0, stdout: JSON.stringify({ schema: 'run_status.v1', repo_root: CWD, runs: [] }), stderr: '' },
  }
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('command.register', async ($, e) => ({ value: { command: e.name } }))
  // The admission review mod (issue #103) registers its tool from the same session.start chain.
  on('tool.register', async ($, e) => ({ value: { tool: e.name } }))
  on('session.cwd', async () => ({ value: CWD }))
  on('process.run', async ($, e) => {
    // The agent-types mod (issue #106) asks at session start which saga types to register: none here.
    if (e.argv.some((arg: string) => arg.endsWith('role_agent_types.py'))) {
      const none = JSON.stringify({ schema: 'saga_role_agent_types.v1', active: false, issue: null, types: [], skipped: [], fingerprint: 'none' })
      return { value: { exitCode: 0, stdout: none, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    // The token-capture mod asks at session start which unit this directory works: none here.
    if (e.argv.includes('unit-for')) {
      const none = JSON.stringify({ schema: 'run_status.v1', repo_root: CWD, branch: '', match: null })
      return { value: { exitCode: 0, stdout: none, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    // The run status band (issue #105) reads every active run on its own clock; it has none here.
    if (e.argv.includes('--all-active')) {
      return { value: { ...state.summary, isStdoutTruncated: false, isStderrTruncated: false } }
    }
    state.runs.push([...e.argv])
    return { value: { ...state.review, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('fs.stat', async ($, e) => {
    if (e.path !== RECORD) throw new Error(`ENOENT: ${e.path}`)
    return { value: { kind: 'file', size: 1, mtimeMs: state.mtimeMs, isLink: false, realPath: e.path } }
  })
  on('ui.open', async ($, e) => {
    state.opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.panes', async () => ({
    value: state.opened.length > state.closed.length
      ? [{ id: REVIEW_PANE, title: 'Review', isShown: true, isFocused: false, isPlaced: true }]
      : [],
  }))
  on('ui.toast', async ($, e) => {
    state.toasts.push(e.text)
    return { value: undefined }
  })
  on('prompt.fill', async ($, e) => {
    if (!state.isFilled) return { isFilled: false, refusal: 'dialog' }
    state.fills.push(e.text)
    return { isFilled: true }
  })
  return state
}

async function start($: Engine) {
  await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
}

/** `/review-view <args>` as the operator types it. */
function reviewView($: Engine, args: string) {
  return $.command.run({
    command: 'review-view',
    args,
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 120 },
  })
}

type Ui = { findAll: (q: { type: string }) => Promise<{ key: string | undefined; props: Record<string, unknown> }[]> }

/** Each lens row's label, keyed by lens. */
async function lensRows(ui: Ui): Promise<Record<string, string>> {
  const buttons = await ui.findAll({ type: 'Button' })
  const rows: Record<string, string> = {}
  for (const button of buttons) {
    if (button.key?.startsWith('lens-')) rows[button.key.slice('lens-'.length)] = String(button.props.label)
  }
  return rows
}

describe('/review-view', () => {
  test('lists one row per selected lens with its outcome and finding count, on terminal and desktop', async ($, on) => {
    const fakes = fake(on)
    await start($)
    const ran = await reviewView($, '#108')
    expect(ran.text).toBe('review-view: #108 cycle 2, review_incomplete, 5 lenses, 3 findings.')
    expect(fakes.opened).toEqual([REVIEW_PANE])
    expect(fakes.runs).toEqual([
      ['python3', expect.stringMatching(/\/scripts\/run_status\.py$/), '--repo-root', CWD, 'review', '--issue', '108', '--json'],
    ])
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      expect(await ui.find({ type: 'Text', text: /^#108 · issue-108 · cycle 2 · review_incomplete · abcdef012345$/ })).toBeDefined()
      const rows = await lensRows(ui)
      expect(Object.keys(rows)).toEqual(['correctness', 'security', 'testing', 'performance', 'docs'])
      expect(rows.correctness).toBe('correctness  met  0 findings')
      expect(rows.security).toBe('security  not met  2 findings')
      expect(rows.performance).toMatch(/^performance {2}unscored {2}1 finding {2}\(establishes no threshold/)
      expect(await ui.find({ type: 'Text', text: '  P0 src/a.py:12 injection' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  P2 src/b.py:4 weak-check' })).toBeDefined()
      await ui.unmount()
    }
  })

  test('a lens with no usable result reads "not run" and shows no score', async ($, on) => {
    fake(on)
    await start($)
    await reviewView($, '')
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      const rows = await lensRows(ui)
      expect(rows.testing).toBe('testing  not run  (could not execute)')
      expect(rows.docs).toBe('docs  not run  (no result recorded)')
      for (const label of [rows.testing, rows.docs, rows.performance]) {
        expect(label).not.toMatch(/\d+\.\d|\bscore\b/)
      }
      expect(rows.testing).not.toMatch(/\d/)
      expect(rows.docs).not.toMatch(/\d/)
      await ui.unmount()
    }
  })

  test('with no review recorded answers one line and opens no pane', async ($, on) => {
    const fakes = fake(on)
    fakes.review = answer(null)
    await start($)
    const ran = await reviewView($, '#108')
    expect(ran.text).toBe('review-view: no review result recorded for #108.')
    expect(fakes.opened).toEqual([])
  })

  test('an unknown view version is reported, not guessed at', async ($, on) => {
    const fakes = fake(on)
    fakes.review = { exitCode: 0, stdout: JSON.stringify({ ...viewOf(reviewOf()), schema: 'review_view.v9' }), stderr: '' }
    await start($)
    const ran = await reviewView($, '')
    expect(ran.text).toContain('unknown-version')
    expect(fakes.opened).toEqual([])
  })

  test('an argument that is not an issue is refused without running the script', async ($, on) => {
    const fakes = fake(on)
    await start($)
    const ran = await reviewView($, 'docs/plan.md')
    expect(ran.text).toContain('name an issue')
    expect(fakes.runs).toEqual([])
  })
})

describe('the live review pane', () => {
  test('draws grades, where-to-look, tools, round, cost and round deltas, on terminal and desktop', async ($, on) => {
    const fakes = fake(on)
    fakes.review = answer(stateOf())
    await start($)
    const ran = await reviewView($, '#108')
    expect(ran.text).toBe('review-view: #108 round 2, blocked, 2 lenses, 1 blocking, 1 fix later.')
    expect(fakes.opened).toEqual([REVIEW_PANE])
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      expect(await ui.find({ type: 'Text', text: /^#108 · round 2 · blocked · abcdef012345$/ })).toBeDefined()
      const rows = await lensRows(ui)
      expect(rows.testing).toBe('testing  A  0 blocking  1 fix later')
      expect(rows.security).toBe('security  B  1 blocking  0 fix later')
      expect(await ui.find({ type: 'Text', text: 'security  src/a.py:12-20  answered rf:bbb  questions: q1' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'testing  src/b.py:4-9  cleared: covered elsewhere' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'ruff 0.15.18' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'Missing mypy. Run /saga:setup.' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'Round 2' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'tokens 10 in / 20 out  $0.05  30s' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'round 1  1 new blocking  0 cleared' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'round 2  0 new blocking  0 cleared' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  + rf:bbb' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  nothing added or cleared' })).toBeDefined()
      await ui.unmount()
    }
  })

  test('choosing a grade lists the document findings, and Quote fills the prompt', async ($, on) => {
    const fakes = fake(on)
    fakes.review = answer(stateOf())
    await start($)
    await reviewView($, '')
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    await ui.press({ key: 'lens-security' })
    expect(await ui.find({ type: 'Text', text: 'blocks · security · rf:bbb · guard' })).toBeDefined()
    const text = await ui.find({ type: 'Markdown', key: 'text-0' })
    expect(text?.props.text).toBe('a traced write to the live store\n\n**Outcome:** unanswered')
    await ui.press({ key: 'quote-0' })
    expect(fakes.fills).toEqual(['> [blocks · security] rf:bbb — a traced write to the live store\n\n'])
    await ui.press({ key: 'back' })
    expect(Object.keys(await lensRows(ui))).toEqual(['testing', 'security'])
    await ui.unmount()
  })

  test('an unknown document version is reported, not guessed at', async ($, on) => {
    const fakes = fake(on)
    const newer = stateOf()
    const review = { ...newer, state_schema: 'review_state.v2', state: { ...STATE_DOC, schema: 'review_state.v2' } }
    fakes.review = { exitCode: 0, stdout: JSON.stringify(viewOf(review as SagaStateReview)), stderr: '' }
    await start($)
    const ran = await reviewView($, '')
    expect(ran.text).toContain('unknown-version')
    expect(ran.text).toContain('review_state.v2')
    expect(fakes.opened).toEqual([])
  })

  test("the band's Review button opens the pane for the band's run", async ($, on) => {
    const fakes = fake(on)
    fakes.review = answer(stateOf())
    fakes.summary = summaryAnswer()
    on('ui.status', async () => ({ value: undefined }))
    await start($)
    await fakes.clock.settle()
    const band = await $.ui.mount({
      plugin: 'saga',
      surface: 'terminal',
      component: 'AbovePrompt',
      props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 100, scroll: { offset: 0, bodyRows: 9 }, view: {} },
    })
    expect(await band.find({ type: 'Button', key: 'band-review-108' })).toBeDefined()
    await band.press({ key: 'band-review-108' })
    expect(fakes.opened).toEqual([REVIEW_PANE])
    expect(fakes.runs.filter((argv) => argv.includes('review'))).toEqual([
      ['python3', expect.stringMatching(/\/scripts\/run_status\.py$/), '--repo-root', CWD, 'review', '--issue', '108', '--json'],
    ])
    await band.unmount()
  })
})

describe('the review pane', () => {
  test('choosing a lens lists its findings with path:line, and Lenses goes back', async ($, on) => {
    fake(on)
    await start($)
    await reviewView($, '')
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'lens-security' })
      expect(await ui.find({ type: 'Text', text: 'P0 · src/a.py:12 · injection' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'P2 · src/b.py:4 · weak-check' })).toBeDefined()
      const text = await ui.find({ type: 'Markdown', key: 'text-0' })
      expect(text?.props.text).toBe('src/a.py:12 shows injection\n\n**Impact:** injection matters')
      await ui.press({ key: 'back' })
      expect(Object.keys(await lensRows(ui))).toHaveLength(5)
      await ui.unmount()
    }
  })

  test("Quote fills the prompt with the finding's place, severity and evidence", async ($, on) => {
    const fakes = fake(on)
    await start($)
    await reviewView($, '')
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'lens-security' })
      await ui.press({ key: 'quote-1' })
      await ui.press({ key: 'back' })
      await ui.unmount()
    }
    const quoted = '> [P2 · security] src/b.py:4 — weak-check\n> src/b.py:4 shows weak-check\n> impact: weak-check matters\n\n'
    expect(fakes.fills).toEqual([quoted, quoted])
  })

  test('a prompt that cannot take the text says so in a toast', async ($, on) => {
    const fakes = fake(on)
    fakes.isFilled = false
    await start($)
    await reviewView($, '')
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    await ui.press({ key: 'lens-security' })
    await ui.press({ key: 'quote-0' })
    expect(fakes.toasts).toEqual(['review-view: the prompt cannot take text right now'])
  })

  test('with nothing loaded the pane says how to load a review', async ($, on) => {
    fake(on)
    await start($)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      expect(await ui.find({ type: 'Text', text: /No review loaded/ })).toBeDefined()
      await ui.unmount()
    }
  })

  test("stacks a finding's wide table on the terminal and leaves it on the desktop", async ($, on) => {
    const fakes = fake(on)
    const wide = finding('P1', 'src/wide.py', 4, 'layout')
    wide.evidence = GOLDEN_PAGE
    wide.impact = 'the pane wraps the grid'
    const review = reviewOf()
    review.lenses = [lens('layout', 'not_met', [wide])]
    fakes.review = answer(review)
    await start($)
    await reviewView($, '')

    const terminal = await $.ui.mount({
      plugin: 'saga',
      surface: 'terminal',
      ...PANE,
      props: { ...PANE.props, bodyColumns: 71 },
    })
    await terminal.press({ key: 'lens-layout' })
    const stacked = await terminal.find({ type: 'Markdown', key: 'text-0' })
    expect(stacked?.props.text).toBe(fitTables(findingText(wide), 71))
    expect(String(stacked?.props.text)).toContain('**Option:** A')
    expect(String(stacked?.props.text)).not.toContain('|:---|')
    // reviewLens survives unmount, so return to the lens list first.
    await terminal.press({ key: 'back' })
    await terminal.unmount()

    const desktop = await $.ui.mount({
      plugin: 'saga',
      surface: 'desktop',
      ...PANE,
      props: { ...PANE.props, bodyColumns: 71 },
    })
    await desktop.press({ key: 'lens-layout' })
    const plain = await desktop.find({ type: 'Markdown', key: 'text-0' })
    expect(plain?.props.text).toBe(findingText(wide))
    await desktop.unmount()
  })
})

describe('refreshing the pane', () => {
  test('a change of the run record modification time reloads the open pane on the next poll', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await reviewView($, '')
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    fakes.review = answer(reviewOf('accepted', 3))
    await fakes.clock.advance(REVIEW_POLL_MS)
    expect(fakes.runs).toHaveLength(1)
    fakes.mtimeMs = 7
    await fakes.clock.advance(REVIEW_POLL_MS)
    expect(fakes.runs).toHaveLength(2)
    expect(await ui.find({ type: 'Text', text: /cycle 3 · accepted/ })).toBeDefined()
  })

  test('a poll with the pane closed reads nothing', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await reviewView($, '')
    fakes.closed.push(REVIEW_PANE)
    fakes.mtimeMs = 7
    await fakes.clock.advance(REVIEW_POLL_MS)
    expect(fakes.runs).toHaveLength(1)
  })

  test('a Bash call that ran review_result.py reloads the open pane; another command does not', async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Bash' }, async () => ({ result: {}, text: 'ran' }))
    await start($)
    await reviewView($, '')
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    fakes.review = answer(reviewOf('repairs_requested', 3))
    await $.tool.call({ tool: 'Bash', command: 'git status' })
    expect(fakes.runs).toHaveLength(1)
    await $.tool.call({ tool: 'Bash', command: 'python3 plugins/saga/scripts/review_result.py append --issue 108' })
    expect(fakes.runs).toHaveLength(2)
    expect(await ui.find({ type: 'Text', text: /cycle 3 · repairs_requested/ })).toBeDefined()
  })
})

describe('the pane words', () => {
  test('a finding longer than the limit is cut, and a quote prefixes every line', () => {
    const long = { ...finding('P1', 'x.py', 1, 'c'), evidence: 'e'.repeat(FINDING_TEXT_LIMIT * 2) }
    expect(findingText(long).length).toBe(FINDING_TEXT_LIMIT)
    const multi = { ...finding('P1', 'x.py', 1, 'c'), evidence: 'one\n\ntwo' }
    expect(quoteText('lens', multi)).toBe('> [P1 · lens] x.py:1 — c\n> one\n>\n> two\n> impact: c matters\n\n')
  })

  test('a not-run lens that somehow has findings still counts them', () => {
    expect(lensLabel(lens('x', 'not_run', [finding('P1', 'a', 1, 'c')], { reason: 'r' }))).toBe('x  not run  1 finding  (r)')
  })

  test('the live labels read grades, states, rounds and cost from the document', () => {
    const doc = stateOf().state
    expect(gradeLabel(doc.lenses[1]!)).toBe('security  B  1 blocking  0 fix later')
    expect(stateHeading(108, stateOf())).toBe('#108 · round 2 · blocked · abcdef012345')
    expect(whereToLookLabel(doc.where_to_look[0]!)).toBe('security  src/a.py:12-20  answered rf:bbb  questions: q1')
    expect(whereToLookLabel(doc.where_to_look[1]!)).toBe('testing  src/b.py:4-9  cleared: covered elsewhere')
    expect(roundLabel(doc.rounds[0]!)).toBe('round 1  1 new blocking  0 cleared')
    expect(costLine(doc.cost)).toBe('tokens 10 in / 20 out  $0.05  30s')
    expect(stateFindingHeading(doc.findings[1]!)).toBe('blocks · security · rf:bbb · guard')
  })
})
