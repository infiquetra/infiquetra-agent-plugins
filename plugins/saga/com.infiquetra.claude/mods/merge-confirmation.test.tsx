// The merge-confirmation pane (issue #165), driven through the engine's own `$`.
//
// The kit runs with no process access, so the test's `process.run` hook stands
// for the host: it answers `run_status.py review` with the fixture document,
// records the `review_state.py answers` call's argv and standard input, and
// answers the tool's one-second `sleep` waits after a few real milliseconds.

import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import {
  answersArgv,
  buildAnswers,
  FIX_LATER_CHOICES,
  fixLaterIds,
  initialSelections,
  MERGE_DECISIONS,
  mergeQuestionPending,
  PANE,
  WAIT_CAP_SECONDS,
} from './merge-confirmation.tsx'

const SURFACES = ['terminal', 'desktop'] as const
const TOOL = 'mcp__saga__review_merge'
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T

/** The review_view.v1 fixture with a review_state.v1 document embedded. */
const VIEW = {
  schema: 'review_view.v1',
  repo_root: '/repo',
  issue: 103,
  record_path: '/repo/.git/.claude/saga/runs/issue-103.json',
  legacy_entries: 0,
  review: {
    state_schema: 'review_state.v1',
    round: 3,
    loop: 'review_run',
    revision: 'abcdef0123456789abcdef0123456789abcdef01',
    outcome: 'blocked',
    lenses: [
      { lens: 'testing', grade: 'A', blocking: 0, fix_later: 1 },
      { lens: 'security', grade: 'B', blocking: 1, fix_later: 1 },
    ],
    pending_choices: ['merge-blocking', 'fix-later:rf:aaa', 'fix-later:rf:bbb'],
    merge: { waiting: true, reason: '1 blocking item left at the round limit awaits the operator' },
    state: {
      schema: 'review_state.v1',
      card: 103,
      repo: 'infiquetra/example',
      round: 3,
      lenses: [
        { lens: 'testing', grade: 'A', blocking: 0, fix_later: 1 },
        { lens: 'security', grade: 'B', blocking: 1, fix_later: 1 },
      ],
      findings: [
        { id: 'rf:aaa', lens: 'testing', severity: 'fix-later', statement: 'a flaky test hides the suite', guard: false, merge_outcome: null },
        { id: 'rf:bbb', lens: 'security', severity: 'fix-later', statement: 'an unconfirmed write', guard: false, merge_outcome: null },
        { id: 'rf:ccc', lens: 'security', severity: 'blocks', statement: 'a traced write to the live store', guard: true, merge_outcome: null },
      ],
      pending_choices: ['merge-blocking', 'fix-later:rf:aaa', 'fix-later:rf:bbb'],
      merge_blocking: ['rf:ccc'],
      merge: { waiting: true, reason: '1 blocking item left at the round limit awaits the operator' },
      disputes: ['rf:ddd'],
      consequence_disagreements: [{ id: 'rf:eee', llm: 'harm', jev: 'visible' }],
      unconfirmed: ['rf:bbb'],
      where_to_look: [],
      tools: { ran: { ruff: '0.15.18' }, missing_notice: null, missing_tools: [] },
      degraded_inputs: ['coverage gap in src/a.py'],
      rounds: [{ round: 3, new_blocking: ['rf:ccc'], cleared_blocking: [] }],
      cost: { tokens_in: 10, tokens_out: 20, cost_usd: 0.05, seconds: 30 },
      unattended: false,
    },
  },
}

type Run = { argv: string[]; stdin: string | undefined }
type World = {
  /** What the world answers; a test may change it between confirmations. */
  setup: Setup
  runs: Run[]
  opens: number
  /** The `review_state.py answers` calls. */
  answerRuns: () => Run[]
  /** The tool's one-second waits. */
  sleeps: () => number
}
type Setup = {
  review?: unknown
  reviewExit?: number
  reviewStderr?: string
  answersExit?: number
  answersStderr?: string
  answersStdout?: string
  placed?: boolean
  surfaces?: string[]
  /** How long one `sleep 1` takes here, in real milliseconds. */
  sleepMs?: number
}

const ran = (exitCode: number, stdout: string, stderr = '') => ({
  value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false },
})

/**
 * The world beneath the plugin: surfaces, the pane's placement, and the host's
 * processes. Registered once per test, before its first call on `$`.
 */
function world(on: On, initial: Setup = {}): World {
  const w: World = {
    setup: initial,
    runs: [],
    opens: 0,
    answerRuns: () => w.runs.filter((run) => run.argv.includes('answers')),
    sleeps: () => w.runs.filter((run) => run.argv[0] === 'sleep').length,
  }
  const hook = on as unknown as (event: string, hook: (...args: any[]) => unknown) => void
  hook('session.surfaces', () => ({ value: w.setup.surfaces ?? ['terminal'] }))
  hook('session.cwd', () => ({ value: '/repo' }))
  hook('ui.open', () => {
    w.opens += 1
    return { value: w.setup.placed === false ? { isPlaced: false, reason: 'narrow' } : { isPlaced: true } }
  })
  hook('ui.close', () => ({ value: undefined }))
  hook('process.run', async (_$: unknown, e: { argv: string[]; init?: { stdin?: string } }) => {
    const setup = w.setup
    w.runs.push({ argv: [...e.argv], stdin: e.init?.stdin })
    if (e.argv[0] === 'sleep') {
      await delay(setup.sleepMs ?? 5)
      return ran(0, '')
    }
    if (e.argv.includes('answers')) {
      return ran(setup.answersExit ?? 0, setup.answersStdout ?? 'Recorded 2 answers for issue 103', setup.answersStderr ?? '')
    }
    return ran(setup.reviewExit ?? 0, JSON.stringify(setup.review ?? VIEW), setup.reviewStderr ?? '')
  })
  return w
}

/** Start the tool unawaited and wait until its pane is open (or the call has already settled). */
async function startConfirm($: any, w: World, input: Record<string, unknown> = {}): Promise<{ pending: Promise<any> }> {
  const opensBefore = w.opens
  let settled = false
  const pending = $.tool.call({ tool: TOOL, issue: 103, ...input }).finally(() => {
    settled = true
  })
  for (let i = 0; i < 400 && w.opens === opensBefore && !settled; i++) await delay(5)
  return { pending }
}

/** The drawing mounted last; a new mount lets it go first, as a surface drops a closed pane. */
let mounted: { unmount: () => Promise<void> } | null = null

async function mountPane($: any, surface: (typeof SURFACES)[number]): Promise<any> {
  await mounted?.unmount().catch(() => undefined)
  mounted = await $.ui.mount({ plugin: 'saga', surface, component: 'Pane', requestId: PANE, props: { bodyColumns: 100 } })
  return mounted
}

const optionValues = (found: { props: Record<string, unknown> } | undefined) =>
  ((found?.props.options as { value: string }[] | undefined) ?? []).map((option) => option.value)

describe('the merge pane', () => {
  test('draws grades, blocking, disputes, disagreements, fix-later, degraded inputs and cost', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startConfirm($, w)
      const ui = await mountPane($, surface)
      expect(await ui.find({ type: 'Text', text: 'testing  A  0 blocking  1 fix later' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: 'security  B  1 blocking  1 fix later' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /rf:ccc/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  rf:ddd' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  rf:eee: model harm, classifier visible' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: '  rf:bbb' })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /rf:aaa — a flaky test/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /coverage gap/ })).toBeDefined()
      expect(await ui.find({ type: 'Text', text: /tokens 10 in/ })).toBeDefined()
      await ui.press({ key: 'dismiss' })
      await pending
    }
  })

  test('Submit hands the answers to review_state.py on standard input, with issue and repository', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startConfirm($, w, { repo: 'infiquetra/example' })
      const ui = await mountPane($, surface)
      await ui.select({ key: 'fix:rf:aaa:choice', value: 'fix-now' })
      await ui.select({ key: 'fix:rf:bbb:choice', value: 'leave' })
      await ui.select({ key: 'merge:decision', value: 'merge-with-reason' })
      await ui.input({ key: 'merge:reason', text: 'the trace cannot reproduce' })
      await ui.press({ key: 'submit' })
      const result = (await pending).result
      expect(result.status).toBe('submitted')
      expect(w.answerRuns()).toHaveLength(1)
      const [call] = w.answerRuns()
      expect(call?.argv).toEqual([
        'python3',
        expect.stringMatching(/\/scripts\/review_state\.py$/),
        'answers',
        '--issue',
        '103',
        '--repo',
        'infiquetra/example',
        '--answers',
        '-',
      ])
      expect(JSON.parse(call?.stdin ?? 'null')).toEqual({
        answers: {
          'fix-later:rf:aaa': 'fix-now',
          'fix-later:rf:bbb': 'leave',
          'merge-blocking': { decision: 'merge-with-reason', reason: 'the trace cannot reproduce' },
        },
        pane_timeout: false,
      })
      expect(result.summary).toBe('Recorded 2 answers for issue 103')
    }
  })

  test('a tool input without a repository still qualifies the call from the document', async ($, on) => {
    const w = world(on)
    const { pending } = await startConfirm($, w)
    const ui = await mountPane($, 'terminal')
    await ui.select({ key: 'fix:rf:aaa:choice', value: 'leave' })
    await ui.press({ key: 'submit' })
    expect((await pending).result.status).toBe('submitted')
    expect(w.answerRuns()).toHaveLength(1)
    expect(w.answerRuns()[0]?.argv).toEqual(expect.arrayContaining(['--repo', 'infiquetra/example']))
  })

  test('fix-later items offer only the three choices, and blocking only a merge or stopping', async ($, on) => {
    const w = world(on)
    const { pending } = await startConfirm($, w)
    const ui = await mountPane($, 'terminal')
    expect(optionValues(await ui.find({ key: 'fix:rf:aaa:choice' }))).toEqual([...FIX_LATER_CHOICES])
    expect(optionValues(await ui.find({ key: 'fix:rf:bbb:choice' }))).toEqual([...FIX_LATER_CHOICES])
    expect(optionValues(await ui.find({ key: 'merge:decision' }))).toEqual([...MERGE_DECISIONS])
    await ui.press({ key: 'dismiss' })
    await pending
  })

  test('a merge with a blank reason never submits; stop-card needs no reason', async ($, on) => {
    const w = world(on)
    const { pending } = await startConfirm($, w)
    const ui = await mountPane($, 'terminal')
    await ui.select({ key: 'merge:decision', value: 'merge-with-reason' })
    await ui.press({ key: 'submit' })
    expect((await ui.find({ key: 'error' }))?.text).toContain('Give a reason')
    expect(w.answerRuns()).toHaveLength(0)
    await ui.select({ key: 'merge:decision', value: 'stop-card' })
    await ui.press({ key: 'submit' })
    expect((await pending).result.status).toBe('submitted')
    expect(JSON.parse(w.answerRuns()[0]?.stdin ?? 'null')).toEqual({
      answers: { 'merge-blocking': { decision: 'stop-card' } },
      pane_timeout: false,
    })
  })

  test('a refusal from review_state.py is shown as printed, and the pane keeps every pick', async ($, on) => {
    const w = world(on, { answersExit: 2, answersStderr: 'merge-blocking: a reason is required' })
    const { pending } = await startConfirm($, w)
    const ui = await mountPane($, 'terminal')
    await ui.select({ key: 'fix:rf:aaa:choice', value: 'fix-now' })
    await ui.select({ key: 'merge:decision', value: 'merge-with-reason' })
    await ui.input({ key: 'merge:reason', text: 'x' })
    await ui.press({ key: 'submit' })
    expect((await ui.find({ key: 'error' }))?.text).toBe('merge-blocking: a reason is required')
    expect((await ui.find({ key: 'fix:rf:aaa:choice' }))?.props.value).toBe('fix-now')
    expect((await ui.find({ key: 'merge:reason' }))?.props.value).toBe('x')
    await ui.press({ key: 'dismiss' })
    expect((await pending).result).toEqual({ status: 'dismissed' })
  })

  // Closing the pane as the person does: an inline plugin's `$.ui.close` of the
  // pane's id raises the same `ui.close` chain the close mark and Escape do.
  const closer = {
    name: 'closer',
    register: ((hookOn: On) => {
      hookOn('command.run', { command: 'close-merge' } as never, async ($: any) => {
        // An inline plugin loads from its source text, so the id is written out here.
        await $.ui.close({ id: 'saga-merge' })
        return { text: 'closed' }
      })
    }) as never,
  }

  test('dismissing returns dismissed and records nothing, by the button or by closing the pane', { plugins: [closer] }, async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const byButton = await startConfirm($, w)
      const ui = await mountPane($, surface)
      await ui.press({ key: 'dismiss' })
      expect((await byButton.pending).result).toEqual({ status: 'dismissed' })

      const byClose = await startConfirm($, w)
      await mountPane($, surface)
      await ($ as any).command.run({ command: 'close-merge' })
      expect((await byClose.pending).result).toEqual({ status: 'dismissed' })
      expect(w.answerRuns()).toHaveLength(0)
    }
  })

  test('the thirty-minute wait returns timed-out and hands the timeout to the script', { timeoutMs: 120000 }, async ($, on) => {
    const w = world(on, { sleepMs: 1 })
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startConfirm($, w)
      await mountPane($, surface)
      expect((await pending).result).toEqual({ status: 'timed-out' })
      expect(w.sleeps()).toBe(WAIT_CAP_SECONDS)
      expect(w.answerRuns()).toHaveLength(1)
      const [call] = w.answerRuns()
      expect(call?.argv).toEqual(expect.arrayContaining(['--issue', '103', '--repo', 'infiquetra/example', '--answers', '-']))
      expect(JSON.parse(call?.stdin ?? 'null')).toEqual({ answers: {}, pane_timeout: true })
    }
  })

  test('a timeout the script refuses returns an error naming the failure', { timeoutMs: 120000 }, async ($, on) => {
    const w = world(on, { sleepMs: 1, answersExit: 2, answersStderr: 'record is locked' })
    const { pending } = await startConfirm($, w)
    await mountPane($, 'terminal')
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(result.reason).toContain('record is locked')
  })
})

test('the tool outlasts the ten-second hook budget while the operator decides', { timeoutMs: 30000 }, async ($, on) => {
  const w = world(on, { sleepMs: 1000 })
  const { pending } = await startConfirm($, w)
  await delay(12_000)
  const ui = await mountPane($, 'terminal')
  await ui.select({ key: 'fix:rf:aaa:choice', value: 'leave' })
  await ui.press({ key: 'submit' })
  expect((await pending).result.status).toBe('submitted')
  expect(w.sleeps()).toBeLessThan(WAIT_CAP_SECONDS)
})

describe('the tool without a pane', () => {
  test('a failing review read returns error with its detail and opens no pane', async ($, on) => {
    const w = world(on, { reviewExit: 2, reviewStderr: 'run_status: git failed' })
    const { pending } = await startConfirm($, w)
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(w.opens).toBe(0)
  })

  test('a review document of another version is refused', async ($, on) => {
    const newer = clone(VIEW)
    newer.review.state_schema = 'review_state.v2'
    newer.review.state.schema = 'review_state.v2'
    const w = world(on, { review: newer })
    const { pending } = await startConfirm($, w)
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(result.reason).toContain('review_state.v2')
    expect(w.opens).toBe(0)
  })

  test('an old-shape review without the document is refused by name', async ($, on) => {
    const old = {
      schema: 'review_view.v1',
      repo_root: '/repo',
      issue: 103,
      record_path: null,
      legacy_entries: 0,
      review: { unit: 'u1', cycle: 1, loop: 'code_review', revision: 'a', outcome: 'x', reason: null, lenses: [], unattributed_findings: [], advisory_count: 0, duplicate_count: 0 },
    }
    const w = world(on, { review: old })
    const { pending } = await startConfirm($, w)
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(result.reason).toContain('no state review')
    expect(w.opens).toBe(0)
  })

  test('with no pending choice there is nothing to review', async ($, on) => {
    const clear = clone(VIEW)
    clear.review.pending_choices = []
    clear.review.state.pending_choices = []
    const w = world(on, { review: clear })
    const { pending } = await startConfirm($, w)
    expect((await pending).result).toEqual({ status: 'nothing-to-review' })
    expect(w.opens).toBe(0)
  })

  test('with no terminal or desktop surface the tool is unavailable', async ($, on) => {
    const w = world(on, { surfaces: ['mobile'] })
    const { pending } = await startConfirm($, w)
    const result = (await pending).result
    expect(result.status).toBe('unavailable')
    expect(w.opens).toBe(0)
  })

  test('a pane that cannot be placed returns not-placed', async ($, on) => {
    const w = world(on, { placed: false })
    const { pending } = await startConfirm($, w)
    const result = (await pending).result
    expect(result.status).toBe('not-placed')
  })

  test('an issue that is not one is refused without running the script', async ($, on) => {
    const w = world(on)
    const pending = $.tool.call({ tool: TOOL, issue: -2 })
    expect((await pending).result.status).toBe('error')
    expect(w.runs).toHaveLength(0)
  })

  test('a tool repository that differs from the document is refused before the pane opens', async ($, on) => {
    const w = world(on)
    const pending = $.tool.call({ tool: TOOL, issue: 103, repo: 'elsewhere/other' })
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(result.reason).toMatch(/does not match the review document/)
    expect(w.opens).toBe(0)
    expect(w.answerRuns()).toHaveLength(0)
  })

  test('a malformed tool repository is refused rather than silently ignored', async ($, on) => {
    const w = world(on)
    const pending = $.tool.call({ tool: TOOL, issue: 103, repo: 'not a repo' })
    const result = (await pending).result
    expect(result.status).toBe('error')
    expect(result.reason).toMatch(/does not match the review document/)
    expect(w.opens).toBe(0)
    expect(w.answerRuns()).toHaveLength(0)
  })
})

describe('the pure helpers', () => {
  test('answersArgv qualifies the call with issue and repository', async () => {
    expect(answersArgv('/root', 103, 'o/r')).toEqual([
      'python3',
      '/root/scripts/review_state.py',
      'answers',
      '--issue',
      '103',
      '--repo',
      'o/r',
      '--answers',
      '-',
    ])
  })

  test('initialSelections restores recorded choices and leaves the merge undecided', async () => {
    const recorded = clone(VIEW.review.state)
    recorded.findings[0].merge_outcome = { outcome: 'left' }
    expect(initialSelections(recorded)).toEqual({
      fix_later: { 'rf:aaa': 'leave', 'rf:bbb': '' },
      merge_blocking: { decision: '', reason: '' },
    })
  })

  test('buildAnswers sends only the answered keys, and stop-card carries no reason', async () => {
    expect(buildAnswers({ fix_later: { 'rf:aaa': 'fix-now', 'rf:bbb': '' }, merge_blocking: { decision: '', reason: '' } })).toEqual({
      answers: { 'fix-later:rf:aaa': 'fix-now' },
      pane_timeout: false,
    })
    expect(buildAnswers({ fix_later: {}, merge_blocking: { decision: 'stop-card', reason: 'anything' } })).toEqual({
      answers: { 'merge-blocking': { decision: 'stop-card' } },
      pane_timeout: false,
    })
  })

  test('mergeQuestionPending and fixLaterIds read the pending choices', async () => {
    expect(mergeQuestionPending(VIEW.review.state)).toBe(true)
    expect(fixLaterIds(VIEW.review.state)).toEqual(['rf:aaa', 'rf:bbb'])
    const clear = clone(VIEW.review.state)
    clear.pending_choices = []
    expect(mergeQuestionPending(clear)).toBe(false)
    expect(fixLaterIds(clear)).toEqual([])
  })
})
