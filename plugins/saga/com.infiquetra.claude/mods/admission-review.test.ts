// The admission review pane (issue #103), driven through the engine's own `$`.
//
// The kit runs with no process access, so the test's `process.run` hook stands
// for the host: it answers `admission.py --render json` with the fixture,
// records the `--answers -` call's argv and standard input, and answers the
// tool's one-second `sleep` waits after a few real milliseconds. Every case that
// draws loops over the terminal and the desktop surfaces.

import { describe, expect, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { buildAnswers, clampTier, initialSelections, parseReview, PANE, WAIT_CAP_SECONDS } from './admission-review.tsx'
import { GOLDEN_ANSWERS, PALETTE, PRIVACY_REASON, REVIEW_JSON } from './fixtures/admission-review.fixture.ts'

const SURFACES = ['terminal', 'desktop'] as const
const TOOL = 'mcp__saga__review_admission'
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

type Run = { argv: string[]; stdin: string | undefined }
type World = {
  /** What the world answers; a test may change it between reviews. */
  setup: Setup
  runs: Run[]
  opens: number
  /** The `admission.py --answers -` calls. */
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
    answerRuns: () => w.runs.filter((run) => run.argv.includes('--answers')),
    sleeps: () => w.runs.filter((run) => run.argv[0] === 'sleep').length,
  }
  const hook = on as unknown as (event: string, hook: (...args: any[]) => unknown) => void
  hook('session.surfaces', () => ({ value: w.setup.surfaces ?? ['terminal'] }))
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
    if (e.argv.includes('--render')) {
      return ran(setup.reviewExit ?? 0, JSON.stringify(setup.review ?? REVIEW_JSON), setup.reviewStderr ?? '')
    }
    return ran(setup.answersExit ?? 0, 'Admission for issue 103', setup.answersStderr ?? '')
  })
  return w
}

/** Start the tool unawaited and wait until its pane is open (or the call has already settled). */
async function startReview($: any, w: World): Promise<{ pending: Promise<any> }> {
  const opensBefore = w.opens
  let settled = false
  const pending = $.tool.call({ tool: TOOL, issue: 103 }).finally(() => {
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

describe('the review pane', () => {
  test('draws the staffing and lens tables, with controls only where a row takes one', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      for (const role of ['planner', 'worker']) {
        expect(await ui.find({ key: `staff:${role}:model` }), `${surface} ${role} model`).toBeDefined()
        expect(await ui.find({ key: `staff:${role}:effort` }), `${surface} ${role} effort`).toBeDefined()
      }
      expect((await ui.find({ key: 'staff:planner:jev' }))?.text).toContain('not configured')
      expect((await ui.find({ key: 'staff:worker:jev' }))?.text).toContain('opus/medium (0.72, raise to confirm)')
      expect(await ui.find({ type: 'Text', text: 'staffing default (work shape implementation)' })).toBeDefined()
      for (const lens of ['correctness', 'security']) {
        expect((await ui.find({ key: `lens:${lens}:always-on` }))?.text).toBe('always on')
        expect(await ui.find({ key: `lens:${lens}:include` })).toBeUndefined()
        expect(await ui.find({ key: `lens:${lens}:reason` })).toBeUndefined()
      }
      for (const lens of ['performance', 'privacy']) {
        expect(optionValues(await ui.find({ key: `lens:${lens}:include` }))).toEqual(['yes', 'no'])
        expect(await ui.find({ key: `lens:${lens}:reason` })).toBeDefined()
      }
      expect((await ui.find({ key: 'lens:performance:jev' }))?.text).toContain('0.86 (pre-checked)')
      expect((await ui.find({ key: 'lens:privacy:jev' }))?.text).toContain('not configured')
      // Jev's pre-checked lens opens included; an undeclared one opens left out.
      expect((await ui.find({ key: 'lens:performance:include' }))?.props.value).toBe('yes')
      expect((await ui.find({ key: 'lens:privacy:include' }))?.props.value).toBe('no')
      await ui.press({ key: 'dismiss' })
      await pending
    }
  })

  test('a dropdown change and Submit hand the golden answers to admission.py on standard input', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      await ui.select({ key: 'staff:worker:model', value: 'opus' })
      await ui.select({ key: 'staff:worker:effort', value: 'medium' })
      await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
      await ui.press({ key: 'submit' })
      const result = await pending

      const [call] = w.answerRuns()
      expect(w.answerRuns()).toHaveLength(1)
      expect(call?.argv[0]).toBe('python3')
      expect(call?.argv[1]).toEndWith('/scripts/admission.py')
      expect(call?.argv.slice(2)).toEqual(['--issue', '103', '--answers', '-'])
      expect(JSON.parse(call?.stdin ?? 'null')).toEqual(GOLDEN_ANSWERS)
      expect(result.result).toEqual({
        status: 'submitted',
        issue: 103,
        answers: GOLDEN_ANSWERS,
        source: 'operator',
        summary: 'Admission for issue 103',
      })
    }
  })

  test('Accept all sends the proposed tiers as the complete role map with the declared lenses', async ($, on) => {
    const declared = clone(REVIEW_JSON)
    const [, , performance, privacy] = declared.lenses.rows
    Object.assign(performance!, { include: 'yes', reason: 'a hot loop' })
    Object.assign(privacy!, { include: 'no', reason: 'no personal data' })
    const w = world(on, { review: declared })
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      // A pick made before Accept all is put back to the proposed tier.
      await ui.select({ key: 'staff:planner:model', value: 'haiku' })
      await ui.press({ key: 'accept-all' })
      const result = await pending
      const answers = JSON.parse(w.answerRuns()[0]?.stdin ?? 'null')
      expect(answers).toEqual({
        staffing_overrides: {
          planner: { vendor: 'claude', model: 'opus', effort: 'high' },
          worker: { vendor: 'claude', model: 'sonnet', effort: 'xhigh' },
        },
        lens_declaration: {
          always_on: ['correctness', 'security'],
          conditional_applies: { performance: 'a hot loop' },
          conditional_does_not_apply: { privacy: 'no personal data' },
        },
      })
      expect(result.result.status).toBe('submitted')
    }
  })

  test('a lens left out with no reason keeps the pane open with a hint and runs nothing', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      await ui.press({ key: 'accept-all' })
      expect((await ui.find({ key: 'error' }))?.text).toContain('privacy')
      expect(w.answerRuns()).toHaveLength(0)
      await ui.press({ key: 'dismiss' })
      expect((await pending).result).toEqual({ status: 'dismissed' })
    }
  })

  test('Accept all restores every proposal and keeps the operator\'s answer for a lens with none', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      // performance is pre-checked, so leaving it out with no reason is the operator's
      // own unexplained exclusion; the privacy reason and the worker pick are theirs too.
      await ui.select({ key: 'lens:performance:include', value: 'no' })
      await ui.select({ key: 'lens:privacy:include', value: 'yes' })
      await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
      await ui.select({ key: 'staff:worker:model', value: 'opus' })
      await ui.press({ key: 'accept-all' })
      // Accept all restores performance to Jev's pre-check, so it submits; privacy has
      // no proposal and keeps the operator's yes and reason.
      await pending
      const answers = JSON.parse(w.answerRuns()[0]?.stdin ?? 'null')
      expect(answers.lens_declaration.conditional_applies).toEqual({ performance: '', privacy: PRIVACY_REASON })
      expect(answers.lens_declaration.conditional_does_not_apply).toEqual({})
      expect(answers.staffing_overrides.worker).toEqual({ vendor: 'claude', model: 'sonnet', effort: 'xhigh' })
    }
  })

  test('Accept all with a lens left out and no reason changes nothing in the pane', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      await ui.input({ key: 'lens:performance:reason', text: 'a hot loop' })
      await ui.select({ key: 'staff:worker:model', value: 'opus' })
      await ui.press({ key: 'accept-all' })
      expect((await ui.find({ key: 'error' }))?.text).toContain('privacy')
      expect(w.answerRuns()).toHaveLength(0)
      expect((await ui.find({ key: 'lens:performance:reason' }))?.props.value).toBe('a hot loop')
      expect((await ui.find({ key: 'staff:worker:model' }))?.props.value).toBe('opus')

      // A typed privacy reason survives a second Accept all, which now submits.
      await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
      await ui.press({ key: 'accept-all' })
      await pending
      const answers = JSON.parse(w.answerRuns()[0]?.stdin ?? 'null')
      expect(answers.lens_declaration.conditional_does_not_apply).toEqual({ privacy: PRIVACY_REASON })
    }
  })

  // Closing the pane as the person does: an inline plugin's `$.ui.close` of the
  // pane's id raises the same `ui.close` chain the close mark and Escape do.
  const closer = {
    name: 'closer',
    register: ((hookOn: On) => {
      hookOn('command.run', { command: 'close-review' } as never, async ($: any) => {
        // An inline plugin loads from its source text, so the id is written out here.
        await $.ui.close({ id: 'saga-admission' })
        return { text: 'closed' }
      })
    }) as never,
  }

  test('dismissing returns dismissed and records nothing, by the button or by closing the pane', { plugins: [closer] }, async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const byButton = await startReview($, w)
      const ui = await mountPane($, surface)
      await ui.press({ key: 'dismiss' })
      expect((await byButton.pending).result).toEqual({ status: 'dismissed' })

      const byClose = await startReview($, w)
      await mountPane($, surface)
      await ($ as any).command.run({ command: 'close-review' })
      expect((await byClose.pending).result).toEqual({ status: 'dismissed' })
      expect(w.answerRuns()).toHaveLength(0)
    }
  })

  test('an off-palette value cannot be selected', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      const ui = await mountPane($, surface)
      // The model choices are the document's palette exactly: this one has no fable.
      expect(optionValues(await ui.find({ key: 'staff:worker:model' }))).toEqual(PALETTE.models)
      expect(await ui.select({ key: 'staff:worker:model', value: 'fable' })).toBeUndefined()
      expect((await ui.find({ key: 'staff:worker:model' }))?.props.value).toBe('sonnet')

      // worker opens at sonnet/xhigh; haiku stops at high, so the effort clamps to it.
      await ui.select({ key: 'staff:worker:model', value: 'haiku' })
      const effort = await ui.find({ key: 'staff:worker:effort' })
      expect(optionValues(effort)).toEqual(['low', 'medium', 'high'])
      expect(effort?.props.value).toBe('high')
      expect(await ui.select({ key: 'staff:worker:effort', value: 'xhigh' })).toBeUndefined()
      expect((await ui.find({ key: 'staff:worker:effort' }))?.props.value).toBe('high')

      await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
      await ui.press({ key: 'submit' })
      await pending
      const answers = JSON.parse(w.answerRuns()[0]?.stdin ?? 'null')
      expect(answers.staffing_overrides.worker).toEqual({ vendor: 'claude', model: 'haiku', effort: 'high' })
    }
  })

  test('a refusal from admission.py is shown in the pane, which stays open until dismissed', async ($, on) => {
    const refusal = "admission: staffing_overrides['worker']: haiku does not take effort xhigh"
    const w = world(on, { answersExit: 2, answersStderr: `${refusal}\n` })
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startReview($, w)
      let settled = false
      void pending.then(() => {
        settled = true
      })
      const ui = await mountPane($, surface)
      await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
      await ui.press({ key: 'submit' })
      await delay(30)
      expect((await ui.find({ key: 'error' }))?.text).toBe(refusal)
      expect(settled).toBe(false)
      await ui.press({ key: 'dismiss' })
      expect((await pending).result).toEqual({ status: 'dismissed' })
    }
  })
})

describe('the tool without a pane', () => {
  test('a pane the surface would not place returns not-placed at once, without waiting', async ($, on) => {
    const w = world(on, { placed: false })
    const result = await ($ as any).tool.call({ tool: TOOL, issue: 103 })
    expect(result.result).toEqual({ status: 'not-placed', reason: 'narrow' })
    expect(w.sleeps()).toBe(0)
  })

  test('a failing admission dry run returns error with its stderr and opens no pane', async ($, on) => {
    const stderr = 'admission: the card is not ready and admission writes nothing: Missing Risk'
    const w = world(on, { reviewExit: 2, reviewStderr: `${stderr}\n` })
    const result = await ($ as any).tool.call({ tool: TOOL, issue: 103 })
    expect(result.result).toEqual({ status: 'error', reason: 'admission.py exited 2', exitCode: 2, stderr })
    expect(w.opens).toBe(0)
  })

  test('a review document of another version is refused', async ($, on) => {
    const w = world(on, { review: { ...REVIEW_JSON, schema: 'admission_review.v2' } })
    const result = await ($ as any).tool.call({ tool: TOOL, issue: 103 })
    expect(result.result.status).toBe('error')
    expect(result.result.reason).toContain('admission_review.v2')
    expect(w.opens).toBe(0)
  })

  test('with neither question outstanding there is nothing to review', async ($, on) => {
    const w = world(on, { review: { ...REVIEW_JSON, pending_questions: ['risk_tier'] } })
    expect((await ($ as any).tool.call({ tool: TOOL, issue: 103 })).result).toEqual({ status: 'nothing-to-review' })
    expect(w.opens).toBe(0)
  })

  test('with no terminal or desktop attached the tool is unavailable', async ($, on) => {
    const w = world(on, { surfaces: ['mobile'] })
    const result = await ($ as any).tool.call({ tool: TOOL, issue: 103 })
    expect(result.result.status).toBe('unavailable')
    expect(w.runs).toHaveLength(0)
  })

  test('an issue that is not a positive whole number is an error', async ($, on) => {
    const w = world(on)
    const result = await ($ as any).tool.call({ tool: TOOL, issue: 0 })
    expect(result.result.status).toBe('error')
    expect(w.runs).toHaveLength(0)
  })
})

// The hook's own-time budget is ten seconds per dispatch, and only a `$` call in
// flight stops that clock. Waiting twelve real seconds before Submit pins that
// the tool waits on `$.process.run`, not on a bare Promise. One surface: the
// budget belongs to the tool's dispatch, which no surface draws.
test('the tool outlasts the ten-second hook budget while the operator decides', { timeoutMs: 30000 }, async ($, on) => {
  const w = world(on, { sleepMs: 1000 })
  const { pending } = await startReview($, w)
  await delay(12_000)
  const ui = await mountPane($, 'terminal')
  await ui.input({ key: 'lens:privacy:reason', text: PRIVACY_REASON })
  await ui.press({ key: 'submit' })
  expect((await pending).result.status).toBe('submitted')
  expect(w.sleeps()).toBeLessThan(WAIT_CAP_SECONDS)
})

describe('the pure helpers', () => {
  test('clampTier keeps an allowed effort and drops a disallowed one to the model ceiling', async () => {
    expect(clampTier(PALETTE, 'opus', 'medium')).toEqual({ model: 'opus', effort: 'medium' })
    expect(clampTier(PALETTE, 'haiku', 'xhigh')).toEqual({ model: 'haiku', effort: 'high' })
    expect(clampTier(PALETTE, 'haiku', null)).toEqual({ model: 'haiku', effort: 'high' })
  })

  test('buildAnswers sends every role and every conditional lens, never an always-on one', async () => {
    const selections = initialSelections(REVIEW_JSON)
    selections.lenses.privacy = { include: 'no', reason: ` ${PRIVACY_REASON} ` }
    const answers = buildAnswers(REVIEW_JSON, selections)
    expect(Object.keys(answers.staffing_overrides)).toEqual(['planner', 'worker'])
    expect(answers.lens_declaration).toEqual({
      always_on: ['correctness', 'security'],
      conditional_applies: { performance: '' },
      conditional_does_not_apply: { privacy: PRIVACY_REASON },
    })
  })

  test('parseReview refuses output the engine cut off', async () => {
    const read = parseReview({ exitCode: 0, stdout: '{"schema"', stderr: '', isStdoutTruncated: true })
    expect(read.ok).toBe(false)
    if (!read.ok) expect(read.reason).toContain('cut off')
  })
})
