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
import { COMMAND, initialTicks, OFFER_STORE_KEY, OFFER_TEXT, PANE, rowLabel, shownOutput, surveySteps, tickedIds, TOOL, WAIT_CAP_SECONDS } from './setup-pane.tsx'

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
  /** The slash commands registered this session, in order. */
  registered: { name: string; description?: string; immediate?: boolean }[]
  /** The texts handed to the session prompt. */
  fills: string[]
  /** How many survey reads the world has answered. */
  surveyCalls: number
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
  /** When false the prompt refuses filled text, like a dialog or headless session. */
  isFilled?: boolean
  /** Runs before the nth survey answers, so a test can close and reopen mid-read. */
  onSurveyCall?: (count: number, $: any) => Promise<void>
  /** When true `ui.open` throws, like a surface that cannot place the pane. */
  openThrows?: boolean
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
    registered: [],
    fills: [],
    surveyCalls: 0,
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
  hook('command.register', (_$: unknown, e: { name: string; description?: string; immediate?: boolean }) => {
    w.registered.push({ name: e.name, description: e.description, immediate: e.immediate })
    return { value: { command: e.name } }
  })
  hook('tool.register', (_$: unknown, e: { name: string }) => ({ value: { tool: e.name } }))
  hook('fs.stat', () => ({ value: { mtimeMs: 1 } }))
  hook('fs.exists', (_$: unknown, e: { path: string }) => ({ value: w.setup.exists?.(e.path) ?? false }))
  hook('ui.open', () => {
    if (w.setup.openThrows === true) throw new Error('the pane could not open')
    w.opens += 1
    return { value: w.setup.placed === false ? { isPlaced: false, reason: 'narrow' } : { isPlaced: true } }
  })
  hook('ui.close', () => ({ value: undefined }))
  hook('ui.panes', () => ({ value: [] }))
  hook('ui.toast', (_$: unknown, e: { text: string }) => {
    w.toasts.push(e.text)
    return { value: undefined }
  })
  hook('prompt.fill', (_$: unknown, e: { text: string }) => {
    if (w.setup.isFilled === false) return { isFilled: false, refusal: 'dialog' }
    w.fills.push(e.text)
    return { isFilled: true }
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
    if (e.argv.includes('survey')) {
      w.surveyCalls += 1
      // Snapshot the answer before the hook: like a real survey process, the
      // read returns what was there when it ran, not a later reassignment.
      const answer = ran(setup.surveyExit ?? 0, JSON.stringify(setup.survey ?? SURVEY), setup.surveyStderr ?? '')
      await w.setup.onSurveyCall?.(w.surveyCalls, _$)
      return answer
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

/** `/setup-view` as the operator types it at a wide fullscreen terminal. */
function setupView($: any) {
  return $.command.run({
    command: COMMAND,
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 160 },
  })
}

/**
 * Record every tool call made after this registers; the command path must make
 * none. Registered per test, never in `world`: it would swallow the tool-call
 * drives that open the tool path.
 */
function recordToolCalls(on: On): string[] {
  const calls: string[] = []
  const hook = on as unknown as (event: string, hook: (...args: any[]) => unknown) => void
  hook('tool.call', (_$: unknown, e: { tool: string }) => {
    calls.push(e.tool)
    return { value: {} }
  })
  return calls
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

describe('the setup-view command', () => {
  const STEPS = [
    { name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false },
    { name: 'second-step', summary: 'Another optional step.', done: true },
  ]

  /** The kit's plugin root, read back from the survey argv the opener ran. */
  const pluginRootOf = (w: World): string => {
    const survey = w.runs.find((run) => run.argv.includes('survey'))
    return (survey?.argv[1] ?? '').slice(0, -'/scripts/saga_setup.py'.length)
  }

  // Closing the pane as the person does, for the command path: an inline
  // plugin's `$.ui.close` of the pane's id raises the same `ui.close` chain.
  const closer = {
    name: 'command-closer',
    register: ((hookOn: On) => {
      hookOn('command.run', { command: 'close-setup' } as never, async ($: any) => {
        await $.ui.close({ id: 'saga-setup' })
        return { text: 'closed' }
      })
    }) as never,
  }

  test('registers setup-view immediate at session start with a collision-free name', async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const registration = w.registered.find((entry) => entry.name === COMMAND)
    expect(registration?.name).toBe('setup-view')
    expect(registration?.immediate).toBe(true)
    // Every saga skill, every adapter command stem, and the sibling mod commands.
    const sagaNames = [
      'brainstorm', 'code-review', 'doc-review', 'founder-review', 'ideate', 'investigate', 'office-hours',
      'plan', 'qa', 'retro', 'setup', 'spec', 'strategy', 'work', 'ceo-review', 'plan-view', 'review-view',
    ]
    expect(sagaNames).not.toContain(COMMAND)
  })

  test('opens the pane with no tool call and surveys the session checkout', async ($, on) => {
    const w = world(on)
    const toolCalls = recordToolCalls(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 0 steps.')
    expect(w.opens).toBe(1)
    const survey = w.runs.find((run) => run.argv.includes('survey'))
    expect(survey?.argv).toEqual([
      'python3', expect.stringMatching(/\/scripts\/saga_setup\.py$/), 'survey', '--repo', CWD, '--format', 'json',
    ])
    expect(toolCalls).toEqual([])
    const ui = await mountPane($, 'terminal')
    expect((await ui.find({ type: 'Button', key: 'tick:saga-ruff' }))?.props.label).toBe('[x] saga-ruff  missing  correctness')
    await ui.press({ key: 'close' })
    const again = await setupView($)
    expect(again.text).toBe('setup-view: 3 tools, 0 steps.')
    expect(w.opens).toBe(2)
    const ui2 = await mountPane($, 'terminal')
    await ui2.press({ key: 'close' })
  })

  test('renders every tool row and step done state, and runs steps from the plugin root', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, steps: STEPS },
      exists: (path) => path.endsWith('/scripts/saga_setup.py'),
    })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 2 steps.')
    const ui = await mountPane($, 'terminal')
    expect((await ui.find({ type: 'Button', key: 'tick:saga-ruff' }))?.props.label).toBe('[x] saga-ruff  missing  correctness')
    expect((await ui.find({ type: 'Button', key: 'tick:saga-mypy' }))?.props.label).toBe('[ ] saga-mypy  installed  correctness')
    expect(await ui.find({ type: 'Text', text: /Install it by hand\./ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /outcome-schedule: not done/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /second-step: done/ })).toBeDefined()
    const root = pluginRootOf(w)
    await ui.press({ key: 'run-step:outcome-schedule' })
    const [call] = w.stepRuns()
    expect(call?.argv).toEqual(['python3', `${root}/scripts/saga_setup.py`, 'step', '--name', 'outcome-schedule'])
    expect(call?.cwd).toBe(root)
    await ui.press({ key: 'close' })
  })

  test('both openers share one survey, install, and step implementation', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, steps: [STEPS[0]] },
      exists: () => true,
    })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'install' })
    await ui.press({ key: 'run-step:outcome-schedule' })
    const toolSurvey = w.runs.find((run) => run.argv.includes('survey'))?.argv
    const toolInstalls = w.installs().map((run) => run.argv)
    const toolSteps = w.stepRuns().map((run) => run.argv)
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result).status).toBe('submitted')
    w.runs.length = 0
    await setupView($)
    const ui2 = await mountPane($, 'terminal')
    await ui2.press({ key: 'install' })
    await ui2.press({ key: 'run-step:outcome-schedule' })
    expect(w.runs.find((run) => run.argv.includes('survey'))?.argv).toEqual(toolSurvey)
    expect(w.installs().map((run) => run.argv)).toEqual(toolInstalls)
    expect(w.stepRuns().map((run) => run.argv)).toEqual(toolSteps)
    await ui2.press({ key: 'close' })
  })

  test('a survey failure opens the pane with the plain message, never a crash', async ($, on) => {
    const w = world(on, { surveyExit: 2, surveyStderr: 'saga_setup: no such tool list' })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const ran = await setupView($)
    expect(ran.text).toContain('setup-view: the survey failed')
    expect(ran.text).toContain('no such tool list')
    expect(w.opens).toBe(1)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Text', text: /The setup survey failed\./ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /no such tool list/ })).toBeDefined()
    await ui.press({ key: 'close' })
  })

  test('closing the command-opened pane leaves nothing pending', async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    // The command answers at open, before any close: nothing waits on the pane.
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 0 steps.')
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'close' })
    // A tool call now proceeds normally: no outcome was recorded, nothing waits.
    const { pending } = await startSetup($, w)
    const ui2 = await mountPane($, 'terminal')
    await ui2.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
  })

  test('a second opener while a setup is open answers without opening', async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const { pending } = await startSetup($, w)
    expect(w.opens).toBe(1)
    const busy = await setupView($)
    expect(busy.text).toContain('already open')
    expect(w.opens).toBe(1)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
    await setupView($)
    expect(w.opens).toBe(2)
    const refused = await $.tool.call({ tool: `mcp__saga__${TOOL}` })
    expect(parseResult(refused.result)).toEqual({ status: 'error', reason: 'a setup pane is already open' })
    expect(w.opens).toBe(2)
    const ui2 = await mountPane($, 'terminal')
    await ui2.press({ key: 'close' })
  })

  test('with no drawable surface or refused placement the command answers as text', async ($, on) => {
    const w = world(on, { surfaces: ['mobile'] })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const unavailable = await setupView($)
    expect(unavailable.text).toContain('no terminal or desktop surface')
    expect(w.opens).toBe(0)
    w.setup.surfaces = ['terminal']
    w.setup.placed = false
    const unplaced = await setupView($)
    expect(unplaced.text).toContain('could not be placed')
    expect(unplaced.text).toContain('narrow')
    // The state was cleared with the refused open: a later command opens fresh.
    w.setup.placed = true
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 0 steps.')
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'close' })
  })

  test('a thrown open answers as text and leaves setup usable', async ($, on) => {
    const w = world(on, { openThrows: true })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const failed = await setupView($)
    expect(failed.text).toContain('the setup pane failed')
    expect(w.opens).toBe(0)
    w.setup.openThrows = false
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 0 steps.')
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'close' })
  })

  test('an empty survey answers nothing to set up and opens no pane', async ($, on) => {
    const w = world(on, { survey: { ...SURVEY, tools: [], steps: [] } })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    const ran = await setupView($)
    expect(ran.text).toContain('nothing to set up')
    expect(w.opens).toBe(0)
  })

  test('a survey refresh that lands after a reopen keeps the new pane', { plugins: [closer] }, async ($, on) => {
    const STALE = { ...SURVEY, tools: [{ ...SURVEY.tools[0]!, status: 'installed', version: '1.0' }, SURVEY.tools[1]!, SURVEY.tools[2]!] }
    const FRESH = { ...SURVEY, tools: [SURVEY.tools[0]!, SURVEY.tools[2]!] }
    // The refresh survey waits here; the test body closes and reopens first. The
    // stub only waits — the host refuses nested engine calls from inside a hook.
    let releaseRefresh!: () => void
    const refreshGate = new Promise<void>((resolve) => {
      releaseRefresh = resolve
    })
    const w = world(on, {
      onSurveyCall: async (count) => {
        if (count === 2) await refreshGate
      },
    })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    await setupView($)
    const ui = await mountPane($, 'terminal')
    w.setup.survey = STALE
    const installing = ui.press({ key: 'install' })
    for (let i = 0; i < 400 && w.surveyCalls < 2; i++) await delay(5)
    expect(w.surveyCalls).toBe(2)
    await ($ as any).command.run({ command: 'close-setup' })
    w.setup.survey = FRESH
    let ran = await setupView($)
    for (let i = 0; i < 40 && ran.text.includes('already open'); i++) {
      await delay(5)
      ran = await setupView($)
    }
    expect(ran.text).toBe('setup-view: 2 tools, 0 steps.')
    expect(w.opens).toBe(2)
    releaseRefresh()
    await installing
    // The stale refresh landed after the reopen: the pane shows the fresh survey.
    const ui2 = await mountPane($, 'terminal')
    expect((await ui2.find({ type: 'Button', key: 'tick:saga-ruff' }))?.props.label).toBe('[x] saga-ruff  missing  correctness')
    expect(await ui2.find({ type: 'Button', key: 'tick:saga-mypy' })).toBeUndefined()
    await ui2.press({ key: 'close' })
  })

  test('closing the command-opened pane as the person does clears it', { plugins: [closer] }, async ($, on) => {
    const w = world(on)
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    await setupView($)
    expect(w.opens).toBe(1)
    await ($ as any).command.run({ command: 'close-setup' })
    // The handler clears before its first await: the first answer opens fresh.
    const ran = await setupView($)
    expect(ran.text).toBe('setup-view: 3 tools, 0 steps.')
    expect(w.opens).toBe(2)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'close' })
  })
})

describe('shared refresh and Ask Claude', () => {
  test('an Install run re-surveys and renders the fresh states', async ($, on) => {
    const w = world(on)
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'tick:saga-mypy' })
    // Both installs succeed; the re-survey reports ruff installed and drops mypy.
    w.setup.survey = {
      ...SURVEY,
      tools: [{ ...SURVEY.tools[0]!, status: 'installed', version: '1.0' }, SURVEY.tools[2]!],
    }
    await ui.press({ key: 'install' })
    expect((await ui.find({ type: 'Button', key: 'tick:saga-ruff' }))?.props.label).toBe('[x] saga-ruff  installed  correctness')
    expect(await ui.find({ type: 'Button', key: 'tick:saga-mypy' })).toBeUndefined()
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: ['saga-ruff', 'saga-mypy'], failed: [] })
  })

  test('a step run re-surveys and renders the fresh done state', async ($, on) => {
    const FIRST = { ...SURVEY, steps: [{ name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false }] }
    const SECOND = { ...SURVEY, steps: [{ name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: true }] }
    const w = world(on, { survey: FIRST, exists: () => true })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    w.setup.survey = SECOND
    await ui.press({ key: 'run-step:outcome-schedule' })
    expect(await ui.find({ type: 'Text', text: /outcome-schedule: done/ })).toBeDefined()
    await ui.press({ key: 'dismiss' })
    expect(parseResult((await pending).result)).toEqual({ status: 'dismissed' })
  })

  test('a failed refresh toasts and keeps the shown survey', async ($, on) => {
    const w = world(on)
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    w.setup.surveyExit = 2
    w.setup.surveyStderr = 'saga_setup: the machine record cannot be read'
    await ui.press({ key: 'install' })
    expect(w.toasts).toEqual([expect.stringContaining('survey refresh failed')])
    expect((await ui.find({ type: 'Button', key: 'tick:saga-ruff' }))?.props.label).toBe('[x] saga-ruff  missing  correctness')
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: ['saga-ruff'], failed: [] })
  })

  test('a failed install offers Ask Claude with the row, the command, and the tail', async ($, on) => {
    const w = world(on, { installs: { 'saga-ruff': { exit: 1, stdout: '', stderr: 'no network' } } })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Button', key: 'ask:saga-ruff' })).toBeUndefined()
    await ui.press({ key: 'install' })
    expect((await ui.find({ type: 'Button', key: 'ask:saga-ruff' }))?.props.label).toBe('Ask Claude')
    await ui.press({ key: 'ask:saga-ruff' })
    expect(w.fills).toHaveLength(1)
    expect(w.fills[0]).toContain('saga-ruff')
    expect(w.fills[0]).toContain('install --tools saga-ruff')
    expect(w.fills[0]).toContain('no network')
    await ui.press({ key: 'done' })
    expect(parseResult((await pending).result)).toEqual({ status: 'submitted', installed: [], failed: ['saga-ruff'] })
  })

  test('Ask Claude toasts when the prompt cannot take text', async ($, on) => {
    const w = world(on, { installs: { 'saga-ruff': { exit: 1, stdout: '', stderr: 'no network' } }, isFilled: false })
    const { pending } = await startSetup($, w)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'install' })
    await ui.press({ key: 'ask:saga-ruff' })
    expect(w.fills).toHaveLength(0)
    expect(w.toasts).toEqual(['setup-view: the prompt cannot take text right now'])
    expect(await ui.find({ type: 'Text', text: /failed: no network/ })).toBeDefined()
    await ui.press({ key: 'done' })
    await pending
  })

  test('a failed step offers Ask Claude', async ($, on) => {
    const w = world(on, {
      survey: { ...SURVEY, steps: [{ name: 'outcome-schedule', summary: 'Run the review-outcome job daily at 06:17.', done: false }] },
      exists: () => true,
      steps: { 'outcome-schedule': { exit: 1, stdout: '', stderr: 'no launchctl' } },
      offer: { ran: true, offered: false },
    })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    await setupView($)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'run-step:outcome-schedule' })
    await ui.press({ key: 'ask-step:outcome-schedule' })
    expect(w.fills).toHaveLength(1)
    expect(w.fills[0]).toContain('outcome-schedule')
    expect(w.fills[0]).toContain('step --name outcome-schedule')
    expect(w.fills[0]).toContain('no launchctl')
    await ui.press({ key: 'close' })
  })

  test('the pane points at /saga:setup for the repository questions', async ($, on) => {
    const w = world(on, { offer: { ran: true, offered: false } })
    await $.session.start({ cwd: CWD, surface: 'terminal', isInteractive: true })
    await setupView($)
    const ui = await mountPane($, 'terminal')
    expect(await ui.find({ type: 'Text', text: /The repository questions live in \/saga:setup\./ })).toBeDefined()
    await ui.press({ key: 'close' })
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
