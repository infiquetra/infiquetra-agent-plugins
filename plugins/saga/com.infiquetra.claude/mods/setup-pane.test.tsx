// The setup pane and the first-session offer (issue #165), driven through the
// engine's own `$`.
//
// The kit runs with no process access, so the test's `process.run` hook stands
// for the host: it answers the survey with the fixture rows, records the
// per-tool installs, answers the offer verbs, and answers the tool's
// one-second `sleep` waits after a few real milliseconds. The `$.store` hooks
// stand for the engine's store.

import { describe, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'
import { initialTicks, OFFER_STORE_KEY, OFFER_TEXT, PANE, rowLabel, shownOutput, surveySteps, tickedIds, TOOL, WAIT_CAP_SECONDS } from './setup-pane.tsx'

const SURFACES = ['terminal', 'desktop'] as const
const CWD = '/Users/operator/repo'
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * The tool result as the session delivers it: a JSON string. The typeof line
 * fails a bare-object regression the kit's own call would let through.
 */
const parseResult = (result: unknown): any => {
  expect(typeof result).toBe('string')
  return JSON.parse(result as string)
}

/** The setup_survey.v1 fixture: one missing installable row, one installed, one manual; no steps. */
const SURVEY = {
  schema: 'setup_survey.v1',
  tools: [
    { id: 'saga-ruff', tool: 'ruff', lens: 'correctness', pinned_version: '1.0', status: 'missing', version: null, auth: 'not-applicable', has_install: true, install: null },
    { id: 'saga-mypy', tool: 'mypy', lens: 'correctness', pinned_version: '1.0', status: 'installed', version: '1.0', auth: 'not-applicable', has_install: true, install: null },
    { id: 'saga-manual', tool: 'manual-tool', lens: 'testing', pinned_version: '2.0', status: 'missing', version: null, auth: 'not-applicable', has_install: false, install: 'Install it by hand.' },
  ],
  steps: [],
}

type Run = { argv: string[]; cwd: string | undefined }
type World = {
  /** What the world answers; a test may change it between calls. */
  setup: Setup
  runs: Run[]
  toasts: string[]
  opens: number
  store: Record<string, unknown>
  /** The `saga_setup.py install` calls, in order. */
  installs: () => Run[]
  /** The `saga_setup.py step` calls, in order. */
  stepRuns: () => Run[]
  /** The offer verbs' calls. */
  offers: () => Run[]
  /** The tool's one-second waits. */
  sleeps: () => number
}
type Setup = {
  survey?: unknown
  surveyExit?: number
  surveyStderr?: string
  /** Per-tool install results; ids missing here install cleanly. */
  installs?: Record<string, { exit: number; stdout?: string; stderr?: string }>
  /** Per-step run results; steps missing here run cleanly. */
  steps?: Record<string, { exit: number; stdout?: string; stderr?: string }>
  /** Which paths exist for the checkout walk; everything else is absent. */
  exists?: (path: string) => boolean
  offer?: { ran: boolean; offered: boolean }
  offerExit?: number
  recordExit?: number
  /** When true the store hooks throw, like a build without the store. */
  storeThrows?: boolean
  placed?: boolean
  surfaces?: string[]
  /** How long one `sleep 1` takes here, in real milliseconds. */
  sleepMs?: number
}

const ran = (exitCode: number, stdout: string, stderr = '') => ({
  value: { exitCode, stdout, stderr, isStdoutTruncated: false, isStderrTruncated: false },
})

/**
 * The world beneath the plugin. Registered once per test, before its first
 * call on `$`. The sibling mods' session-start calls are answered and left in
 * `runs`; assertions filter for the argv they own.
 */
function world(on: On, initial: Setup = {}): World {
  const w: World = {
    setup: initial,
    runs: [],
    toasts: [],
    opens: 0,
    store: {},
    installs: () => w.runs.filter((run) => run.argv.includes('install')),
    stepRuns: () => w.runs.filter((run) => run.argv.includes('step')),
    offers: () => w.runs.filter((run) => run.argv.includes('offer-status') || run.argv.includes('record-offer')),
    sleeps: () => w.runs.filter((run) => run.argv[0] === 'sleep').length,
  }
  const hook = on as unknown as (event: string, hook: (...args: any[]) => unknown) => void
  mock.clock(on)
  hook('session.start', (_$: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  hook('session.surfaces', () => ({ value: w.setup.surfaces ?? ['terminal'] }))
  hook('session.cwd', () => ({ value: CWD }))
  hook('command.register', (_$: unknown, e: { name: string }) => ({ value: { command: e.name } }))
  hook('tool.register', (_$: unknown, e: { name: string }) => ({ value: { tool: e.name } }))
  hook('fs.stat', () => ({ value: { mtimeMs: 1 } }))
  hook('fs.exists', (_$: unknown, e: { path: string }) => ({ value: w.setup.exists?.(e.path) ?? false }))
  hook('ui.open', () => {
    w.opens += 1
    return { value: w.setup.placed === false ? { isPlaced: false, reason: 'narrow' } : { isPlaced: true } }
  })
  hook('ui.close', () => ({ value: undefined }))
  hook('ui.panes', () => ({ value: [] }))
  hook('ui.toast', (_$: unknown, e: { text: string }) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  hook('ui.status', () => ({ value: undefined }))
  hook('store.get', (_$: unknown, e: { key: string }) => {
    if (w.setup.storeThrows) throw new Error('no implementation for store.get')
    return { value: w.store[e.key] }
  })
  hook('store.set', (_$: unknown, e: { key: string; value: unknown }) => {
    if (w.setup.storeThrows) throw new Error('no implementation for store.set')
    w.store[e.key] = e.value
    return { value: undefined }
  })
  hook('process.run', async (_$: unknown, e: { argv: string[]; init?: { cwd?: string; stdin?: string } }) => {
    const setup = w.setup
    w.runs.push({ argv: [...e.argv], cwd: e.init?.cwd })
    if (e.argv[0] === 'sleep') {
      await delay(setup.sleepMs ?? 5)
      return ran(0, '')
    }
    if (e.argv[0] === 'role_agent_types.py' || e.argv.includes('unit-for') || e.argv.includes('--all-active')) {
      return ran(0, JSON.stringify({ schema: 'x', runs: [] }))
    }
    if (e.argv.includes('offer-status')) {
      if (setup.offerExit !== undefined && setup.offerExit !== 0) {
        return ran(setup.offerExit, '', 'saga_setup: the machine record cannot be read')
      }
      const offer = setup.offer ?? { ran: false, offered: false }
      return ran(0, JSON.stringify({ schema: 'machine_record.v1', ...offer }))
    }
    if (e.argv.includes('record-offer')) {
      if (setup.recordExit !== undefined && setup.recordExit !== 0) {
        return ran(setup.recordExit, '', 'saga_setup: home is read-only')
      }
      return ran(0, '/home/op/.saga/machine.json\n')
    }
    if (e.argv.includes('install')) {
      const id = e.argv[e.argv.indexOf('--tools') + 1] ?? ''
      const result = setup.installs?.[id] ?? { exit: 0, stdout: `installed ${id}\n` }
      return ran(result.exit, result.stdout ?? '', result.stderr ?? '')
    }
    if (e.argv.includes('step')) {
      const name = e.argv[e.argv.indexOf('--name') + 1] ?? ''
      const result = setup.steps?.[name] ?? { exit: 0, stdout: `ran ${name}\n` }
      return ran(result.exit, result.stdout ?? '', result.stderr ?? '')
    }
    return ran(setup.surveyExit ?? 0, JSON.stringify(setup.survey ?? SURVEY), setup.surveyStderr ?? '')
  })
  return w
}

/** Start the tool unawaited and wait until its pane is open (or the call has already settled). */
async function startSetup($: any, w: World, input: Record<string, unknown> = {}): Promise<{ pending: Promise<any> }> {
  const opensBefore = w.opens
  let settled = false
  const pending = $.tool.call({ tool: `mcp__saga__${TOOL}`, ...input }).finally(() => {
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

describe('the setup pane', () => {
  test('rows come from the survey with pre-ticks, and Done submits the installed lists', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startSetup($, w)
      const ui = await mountPane($, surface)
      const ruff = await ui.find({ type: 'Button', key: 'tick:saga-ruff' })
      const mypy = await ui.find({ type: 'Button', key: 'tick:saga-mypy' })
      expect(ruff?.props.label).toBe('[x] saga-ruff  missing  correctness')
      expect(mypy?.props.label).toBe('[ ] saga-mypy  installed  correctness')
      expect(await ui.find({ type: 'Button', key: 'tick:saga-manual' })).toBeUndefined()
      expect(await ui.find({ type: 'Text', text: /Install it by hand\./ })).toBeDefined()
      await ui.press({ key: 'install' })
      await ui.press({ key: 'done' })
      const result = parseResult((await pending).result)
      expect(result).toEqual({ status: 'submitted', installed: ['saga-ruff'], failed: [] })
      expect(w.installs().map((run) => run.argv)).toEqual([
        ['python3', expect.stringMatching(/\/scripts\/saga_setup\.py$/), 'install', '--tools', 'saga-ruff', '--repo', CWD],
      ])
    }
  })

  test('Install passes only the ticked tools, one call each in order, showing live progress', async ($, on) => {
    const w = world(on)
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'tick:saga-mypy' })
    await ui.press({ key: 'tick:saga-ruff' })
    await ui.press({ key: 'tick:saga-ruff' })
    await ui.press({ key: 'install' })
    expect(w.installs().map((run) => run.argv[run.argv.indexOf('--tools') + 1])).toEqual(['saga-ruff', 'saga-mypy'])
    expect(await ui.find({ type: 'Text', text: /done: installed saga-ruff/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /done: installed saga-mypy/ })).toBeDefined()
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: ['saga-ruff', 'saga-mypy'], failed: [] })
  })

  test('Install stops at the first failure and leaves later rows queued', async ($, on) => {
    const w = world(on, { installs: { 'saga-mypy': { exit: 1, stdout: '', stderr: 'no network' } } })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'tick:saga-mypy' })
    await ui.press({ key: 'install' })
    expect(w.installs().map((run) => run.argv[run.argv.indexOf('--tools') + 1])).toEqual(['saga-ruff', 'saga-mypy'])
    expect(await ui.find({ type: 'Text', text: /failed: no network/ })).toBeDefined()
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: ['saga-ruff'], failed: ['saga-mypy'] })
  })

  test('Install with nothing ticked runs nothing and says so', async ($, on) => {
    const w = world(on)
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'tick:saga-ruff' })
    await ui.press({ key: 'install' })
    expect((await ui.find({ key: 'error' }))?.text).toContain('Tick at least one tool')
    expect(w.installs()).toHaveLength(0)
    await ui.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
  })

  test('dismissing returns dismissed and installs nothing', async ($, on) => {
    const w = world(on)
    for (const surface of SURFACES) {
      w.runs.length = 0
      const { pending } = await startSetup($, w)
      const ui = await mountPane($, surface)
      await ui.press({ key: 'dismiss' })
      expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
      expect(w.installs()).toHaveLength(0)
    }
  })

  test('the thirty-minute wait returns timed-out with nothing installed', { timeoutMs: 120000 }, async ($, on) => {
    const w = world(on, { sleepMs: 1 })
    const { pending } = await startSetup($, w)
    await mountPane($, 'terminal')
    expect(parseResult((await pending).result)).toEqual({ status: 'timed-out' })
    expect(w.sleeps()).toBe(WAIT_CAP_SECONDS)
    expect(w.installs()).toHaveLength(0)
  })
})

describe('the setup steps', () => {
  const STEPS = [
    { name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false },
    { name: 'second-step', summary: 'Another optional step.', done: true },
  ]

  /** The kit's plugin root, read back from the survey argv the tool call ran. */
  const pluginRootOf = (w: World): string => {
    const survey = w.runs.find((run) => run.argv.includes('survey'))
    return (survey?.argv[1] ?? '').slice(0, -'/scripts/saga_setup.py'.length)
  }

  test('steps render with their done state and Run executes the step from the saga plugin root', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, steps: STEPS },
      exists: (path) => path.endsWith('/scripts/saga_setup.py'),
    })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Text', text: /outcome-schedule: not done/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /second-step: done/ })).toBeDefined()
    const root = pluginRootOf(w)
    await ui.press({ key: 'run-step:outcome-schedule' })
    const [call] = w.stepRuns()
    expect(call?.argv).toEqual(['python3', `${root}/scripts/saga_setup.py`, 'step', '--name', 'outcome-schedule'])
    expect(call?.cwd).toBe(root)
    expect(await ui.find({ type: 'Text', text: /done: ran outcome-schedule/ })).toBeDefined()
    // A step the survey marks done still offers Run.
    await ui.press({ key: 'run-step:second-step' })
    expect(w.stepRuns()).toHaveLength(2)
    await ui.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
  })

  test('steps without tools still open the pane with working runs', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, tools: [], steps: [STEPS[0]] },
      exists: () => true,
    })
    const { pending } = await startSetup($, w)
    expect(w.opens).toBe(1)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Text', text: /outcome-schedule: not done/ })).toBeDefined()
    await ui.press({ key: 'run-step:outcome-schedule' })
    expect(w.stepRuns()).toHaveLength(1)
    // No installable row, so the pane offers only Done.
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: [], failed: [] })
  })

  test('without a saga checkout the steps render unrunnable and run nothing', async ($, on) => {
    const w = world(on, { survey: { ...SURVEY, steps: STEPS } })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Button', key: 'run-step:outcome-schedule' })).toBeUndefined()
    expect(await ui.find({ type: 'Text', text: /Steps run only from a saga checkout/ })).toBeDefined()
    expect(w.stepRuns()).toHaveLength(0)
    await ui.press({ key: 'dismiss' })
    await pending
  })

  test('a failing step shows its stderr and Done still submits only the installs', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, steps: [STEPS[0]] },
      exists: () => true,
      steps: { 'outcome-schedule': { exit: 1, stdout: '', stderr: 'no launchctl' } },
    })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'run-step:outcome-schedule' })
    expect(await ui.find({ type: 'Text', text: /failed: no launchctl/ })).toBeDefined()
    await ui.press({ key: 'install' })
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: ['saga-ruff'], failed: [] })
  })

  test('a survey with no steps draws no Steps section', async ($, on) => {
    const w = world(on)
    for (const steps of [[], undefined, 'outcome-schedule'] as const) {
      w.setup.survey = { ...SURVEY, steps }
      const { pending } = await startSetup($, w)
      const ui = await mountPane($, 'terminal')
      expect(await ui.find({ type: 'Button', key: 'run-step:outcome-schedule' })).toBeUndefined()
      expect(await ui.find({ type: 'Text', text: /^Steps$/ })).toBeUndefined()
      await ui.press({ key: 'dismiss' })
      await pending
      w.runs.length = 0
    }
  })
})

describe('the empty-installable state', () => {
  const MANUAL = {
    ...SURVEY,
    tools: [
      { id: 'saga-manual', tool: 'manual-tool', lens: 'testing', pinned_version: '2.0', status: 'missing', version: null, auth: 'not-applicable', has_install: false, install: 'Install it by hand.' },
    ],
  }

  // Closing the pane as the person does: an inline plugin's `$.ui.close` of the
  // pane's id raises the same `ui.close` chain the close mark and Escape do.
  const closer = {
    name: 'closer',
    register: ((hookOn: On) => {
      hookOn('command.run', { command: 'close-setup' } as never, async ($: any) => {
        // An inline plugin loads from its source text, so the id is written out here.
        await $.ui.close({ id: 'saga-setup' })
        return { text: 'closed' }
      })
    }) as never,
  }

  test('with no installable row the pane explains, offers only Done, and submits empty lists', async ($, on) => {
    const w = world(on, { survey: MANUAL })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Text', text: /Nothing here installs/ })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'install' })).toBeUndefined()
    expect(await ui.find({ type: 'Button', key: 'dismiss' })).toBeUndefined()
    expect(await ui.find({ key: 'error' })).toBeUndefined()
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: [], failed: [] })
    expect(w.installs()).toHaveLength(0)
  })

  test('one installable row among manual rows keeps Install and Dismiss', async ($, on) => {
    const w = world(on, { survey: { ...MANUAL, tools: [SURVEY.tools[0], ...MANUAL.tools] } })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Button', key: 'install' })).toBeDefined()
    expect(await ui.find({ type: 'Button', key: 'dismiss' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Nothing here installs/ })).toBeUndefined()
    await ui.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
  })

  test('steps still run above the explainer when no row installs', async ($, on) => {
    const w = world(on, {
      survey: { ...MANUAL, steps: [{ name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false }] },
      exists: () => true,
    })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'run-step:outcome-schedule' })
    expect(w.stepRuns()).toHaveLength(1)
    expect(await ui.find({ type: 'Text', text: /Nothing here installs/ })).toBeDefined()
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: [], failed: [] })
  })

  test('closing the pane in this state still yields dismissed', { plugins: [closer] }, async ($, on) => {
    const w = world(on, { survey: MANUAL })
    const { pending } = await startSetup($, w)
    await mountPane($, 'terminal')
    await ($ as any).command.run({ command: 'close-setup' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
    expect(w.installs()).toHaveLength(0)
  })
})

describe('the tool without a pane', () => {
  test('a failing survey read returns error with its detail and opens no pane', async ($, on) => {
    const w = world(on, { surveyExit: 2, surveyStderr: 'saga_setup: no such tool list' })
    const { pending } = await startSetup($, w)
    const result = parseResult((await pending).result)
    expect(result.status).toBe('error')
    expect(result.reason).toContain('no such tool list')
    expect(w.opens).toBe(0)
  })

  test('a survey of another version is refused', async ($, on) => {
    const w = world(on, { survey: { ...SURVEY, schema: 'setup_survey.v2' } })
    const { pending } = await startSetup($, w)
    const result = parseResult((await pending).result)
    expect(result.status).toBe('error')
    expect(result.reason).toContain('setup_survey.v2')
    expect(w.opens).toBe(0)
  })

  test('an empty survey with no steps is nothing to review and opens no pane', async ($, on) => {
    const w = world(on, { survey: { ...SURVEY, tools: [], steps: [] } })
    const { pending } = await startSetup($, w)
    expect(parseResult((await pending).result)).toEqual({ status: 'nothing-to-review' })
    expect(w.opens).toBe(0)
  })

  test('with no terminal or desktop surface the tool is unavailable', async ($, on) => {
    const w = world(on, { surfaces: ['mobile'] })
    const { pending } = await startSetup($, w)
    expect(parseResult((await pending).result).status).toBe('unavailable')
    expect(w.opens).toBe(0)
  })

  test('a pane that cannot be placed returns not-placed', async ($, on) => {
    const w = world(on, { placed: false })
    const { pending } = await startSetup($, w)
    expect(parseResult((await pending).result).status).toBe('not-placed')
  })
})

describe('the first-session offer', () => {
  test('never-ran and unoffered toasts once and records the offer in both stores, never surveying', async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([OFFER_TEXT])
    expect(w.offers().map((run) => run.argv[run.argv.length - 1])).toEqual(['offer-status', 'record-offer'])
    expect(w.runs.some((run) => run.argv.includes('survey'))).toBe(false)
    expect(w.store[OFFER_STORE_KEY]).toBe(true)
  })

  test('a run setup shows nothing and records nothing', async ($, on) => {
    const w = world(on, { offer: { ran: true, offered: false } })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([])
    expect(w.offers().filter((run) => run.argv.includes('record-offer'))).toHaveLength(0)
  })

  test('an offered record shows nothing and records nothing', async ($, on) => {
    const w = world(on, { offer: { ran: false, offered: true } })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([])
    expect(w.offers().filter((run) => run.argv.includes('record-offer'))).toHaveLength(0)
  })

  test('a remembered store shows nothing and never calls the script', async ($, on) => {
    const w = world(on)
    w.store[OFFER_STORE_KEY] = true
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([])
    expect(w.offers()).toHaveLength(0)
  })

  test('a failed record-offer toasts the error and leaves the store unset', async ($, on) => {
    const w = world(on, { recordExit: 2 })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([OFFER_TEXT, expect.stringContaining('could not record the setup offer')])
    expect(w.store[OFFER_STORE_KEY]).toBeUndefined()
  })

  test('an unreadable machine record toasts the failure and never offers', async ($, on) => {
    const w = world(on, { offerExit: 2 })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toHaveLength(1)
    expect(w.toasts[0]).toContain('could not read the machine record')
    expect(w.offers().filter((run) => run.argv.includes('record-offer'))).toHaveLength(0)
  })

  test('a build without the store stays silent and runs nothing', async ($, on) => {
    const w = world(on, { storeThrows: true })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    expect(w.toasts).toEqual([])
    expect(w.offers()).toHaveLength(0)
  })
})

describe('the pure helpers', () => {
  test('initialTicks pre-ticks missing installable rows, and tickedIds keeps survey order', async () => {
    expect(initialTicks(SURVEY)).toEqual({ 'saga-ruff': true, 'saga-mypy': false, 'saga-manual': false })
    expect(tickedIds(SURVEY, { 'saga-ruff': true, 'saga-mypy': true, 'saga-manual': true })).toEqual(['saga-ruff', 'saga-mypy'])
    expect(tickedIds(SURVEY, {})).toEqual([])
  })

  test('rowLabel and shownOutput read the row and bound its output', async () => {
    expect(rowLabel(SURVEY.tools[0]!, true)).toBe('[x] saga-ruff  missing  correctness')
    expect(rowLabel(SURVEY.tools[1]!, false)).toBe('[ ] saga-mypy  installed  correctness')
    expect(shownOutput('short')).toBe('short')
    expect(shownOutput('x'.repeat(3000))).toBe(`…${'x'.repeat(2000)}`)
  })

  test('surveySteps reads the steps list and treats a missing or foreign field as none', async () => {
    const steps = [{ name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false }]
    expect(surveySteps({ ...SURVEY, steps })).toEqual(steps)
    expect(surveySteps(SURVEY)).toEqual([])
    expect(surveySteps({ ...SURVEY, steps: undefined })).toEqual([])
    expect(surveySteps({ ...SURVEY, steps: 'outcome-schedule' })).toEqual([])
  })
})
