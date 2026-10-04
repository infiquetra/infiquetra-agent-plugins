import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import type { SagaUsageBucket } from '../types/index.d.ts'
import {
  CACHE_WRITE_FLAG,
  USAGE_FLUSH_MS,
  addStep,
  effortName,
  parseUnitFor,
  subagentRole,
  subtractWritten,
  usageAddArgv,
} from './usage-capture.ts'

const WORKTREE = '/Users/operator/wt/agent-plugins-u2'
const STORE = '/Users/operator/repo/.claude/saga/runs'
const SESSION = 'sess-1'

const TARGET = {
  issue: 412,
  unit: 'u2',
  role: 'worker',
  matched_by: 'worktree',
  record_path: `${STORE}/issue-412.json`,
  store_root: STORE,
  ambiguous: false,
} as const

type Usage = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
  model: string
}

type Fake = {
  clock: ReturnType<typeof mock.clock>
  /** Every argv the mod ran, in order. */
  runs: string[][]
  /** What `run_status.py unit-for` prints as its match. */
  match: object | null
  /** The exit code `usage add` answers with. */
  addExit: number
  /** The usage the next model request reports. */
  usage: Usage | null
  agents: { id: string; type: string }[]
}

/** The usage-add runs, each as its flags read into a map. */
function adds(fakes: Fake): Map<string, string>[] {
  return fakes.runs
    .filter((argv) => argv.includes('usage') && argv.includes('add'))
    .map((argv) => {
      const flags = new Map<string, string>()
      const at = argv.indexOf('add')
      flags.set('issue', argv[at + 1])
      for (let i = at + 2; i < argv.length; i += 2) flags.set(argv[i], argv[i + 1])
      flags.set('--store-root', argv[argv.indexOf('--store-root') + 1])
      return flags
    })
}

function usage(input: number, output = 1, cacheRead = 0, cacheWrite = 0, model = 'claude-opus-5-5'): Usage {
  return { input_tokens: input, output_tokens: output, cache_read_input_tokens: cacheRead, cache_creation_input_tokens: cacheWrite, model }
}

/** Answer every engine call the mod makes from memory. */
function fake(on: On): Fake {
  const state: Fake = {
    clock: mock.clock(on),
    runs: [],
    match: TARGET,
    addExit: 0,
    usage: usage(100),
    agents: [],
  }
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('session.end', async ($, e) => ({ sessionId: e.sessionId }))
  on('session.id', async () => ({ value: SESSION }))
  on('command.register', async ($, e) => ({ value: { command: e.name } }))
  // The admission review mod (issue #103) registers its tool from the same session.start chain.
  on('tool.register', async ($, e) => ({ value: { tool: e.name } }))
  on('agent.list', async () => ({ value: state.agents.map((a) => ({ ...a, description: '', status: 'running' })) }))
  on('ui.log', async () => ({ value: undefined }))
  on('process.run', async ($, e) => {
    state.runs.push([...e.argv])
    if (e.argv.includes('unit-for')) {
      const view = { schema: 'run_status.v1', repo_root: WORKTREE, branch: 'orch/r1-u2', match: state.match }
      return { value: { exitCode: 0, stdout: JSON.stringify(view), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
    }
    const stderr = state.addExit === 0 ? '' : 'run_record: no record for issue 412'
    return { value: { exitCode: state.addExit, stdout: '', stderr, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('turn.step', async function* ($, e) {
    return { turnId: e.turnId, index: e.index, answer: '', toolUses: [], stopReason: state.usage ? 'end_turn' : null, usage: state.usage }
  })
  return state
}

async function start($: Engine, cwd = WORKTREE) {
  await $.session.start({ cwd, surface: 'terminal', isInteractive: true })
}

/** One model request, on the main thread or in subagent `agentId`'s loop. */
async function step($: Engine, options: { agentId?: string; effort?: 'low' | 'medium' | 'high' | number } = {}) {
  const input = {
    turnId: 't1',
    index: 0,
    model: 'claude-opus-5-5',
    messageCount: 1,
    ...(options.effort === undefined ? { effort: 'medium' as const } : { effort: options.effort }),
    ...(options.agentId === undefined ? {} : { agentId: options.agentId }),
  }
  for await (const _ of $.turn.step(input)) {
    // drain the stream; the mod reads the usage from its result
  }
}

async function end($: Engine) {
  await $.session.end({ reason: 'prompt_input_exit', sessionId: SESSION, resume: { id: SESSION } })
}

describe('usage capture', () => {
  test('main-thread and subagent usage land on the matched unit through run_record.py usage add', async ($, on) => {
    const fakes = fake(on)
    fakes.agents = [{ id: 'a1', type: 'general-purpose' }]
    await start($)
    expect(fakes.runs[0]).toEqual([
      'python3',
      expect.stringMatching(/\/scripts\/run_status\.py$/),
      '--repo-root',
      WORKTREE,
      'unit-for',
      '--json',
    ])
    fakes.usage = usage(100, 20, 3000, 400)
    await step($)
    fakes.usage = usage(7, 5, 50, 0, 'claude-sonnet-5-5')
    await step($, { agentId: 'a1', effort: 'low' })
    await fakes.clock.advance(USAGE_FLUSH_MS)

    const written = adds(fakes)
    expect(written.length).toBe(2)
    for (const flags of written) {
      expect(fakes.runs.find((argv) => argv.includes('add'))?.[1]).toMatch(/\/scripts\/run_record\.py$/)
      expect(flags.get('issue')).toBe('412')
      expect(flags.get('--unit')).toBe('u2')
      expect(flags.get('--store-root')).toBe(STORE)
      expect(flags.get('--vendor')).toBe('claude')
      expect(flags.get('--role')).toBe('worker')
    }
    const [main, sub] = written
    expect(main.get('--session-id')).toBe(SESSION)
    expect(main.get('--model')).toBe('claude-opus-5-5')
    expect(main.get('--effort')).toBe('medium')
    expect([main.get('--uncached-input'), main.get('--cache-read'), main.get(CACHE_WRITE_FLAG), main.get('--output')]).toEqual([
      '100',
      '3000',
      '400',
      '20',
    ])
    expect(sub.get('--session-id')).toBe(`${SESSION}/a1`)
    expect(sub.get('--model')).toBe('claude-sonnet-5-5')
    expect(sub.get('--effort')).toBe('low')
    expect([sub.get('--uncached-input'), sub.get('--cache-read'), sub.get('--output')]).toEqual(['7', '50', '5'])
  })

  test('a session in a directory that works no unit runs nothing after unit-for and writes nothing', async ($, on) => {
    const fakes = fake(on)
    fakes.match = null
    await start($, '/Users/operator/unrelated')
    await step($)
    await step($, { agentId: 'a1' })
    await fakes.clock.advance(10 * USAGE_FLUSH_MS)
    await end($)
    expect(fakes.runs.length).toBe(1)
    expect(fakes.runs[0]).toContain('unit-for')
    expect(adds(fakes)).toEqual([])
  })

  test('writes are batched: three requests write nothing until the tick, then one summed usage add', async ($, on) => {
    const fakes = fake(on)
    await start($)
    for (const input of [10, 20, 30]) {
      fakes.usage = usage(input, 2)
      await step($)
    }
    expect(adds(fakes)).toEqual([])
    await fakes.clock.advance(USAGE_FLUSH_MS - 1)
    expect(adds(fakes)).toEqual([])
    await fakes.clock.advance(1)
    const written = adds(fakes)
    expect(written.length).toBe(1)
    expect([written[0].get('--uncached-input'), written[0].get('--output')]).toEqual(['60', '6'])
    // Nothing new: the next tick writes nothing.
    await fakes.clock.advance(USAGE_FLUSH_MS)
    expect(adds(fakes).length).toBe(1)
  })

  test('session end flushes what the timer has not written yet', async ($, on) => {
    const fakes = fake(on)
    await start($)
    fakes.usage = usage(42, 9)
    await step($)
    expect(adds(fakes)).toEqual([])
    await end($)
    const written = adds(fakes)
    expect(written.length).toBe(1)
    expect([written[0].get('--uncached-input'), written[0].get('--output')]).toEqual(['42', '9'])
  })

  test('a failed write keeps the usage and the next tick writes it, with what came since', async ($, on) => {
    const fakes = fake(on)
    await start($)
    fakes.addExit = 2
    fakes.usage = usage(5)
    await step($)
    await fakes.clock.advance(USAGE_FLUSH_MS)
    expect(adds(fakes).length).toBe(1)
    fakes.addExit = 0
    fakes.usage = usage(6)
    await step($)
    await fakes.clock.advance(USAGE_FLUSH_MS)
    const written = adds(fakes)
    expect(written.length).toBe(2)
    expect(written[1].get('--uncached-input')).toBe('11')
  })

  test('a request that reported no usage records nothing', async ($, on) => {
    const fakes = fake(on)
    await start($)
    fakes.usage = null
    await step($)
    await end($)
    expect(adds(fakes)).toEqual([])
  })

  test("a saga agent type records its own role; the row's role names the main thread", async ($, on) => {
    const fakes = fake(on)
    fakes.match = { ...TARGET, role: 'functional-tester' }
    fakes.agents = [{ id: 'r1', type: 'saga:lens-reviewer' }]
    await start($)
    await step($)
    await step($, { agentId: 'r1' })
    await end($)
    expect(adds(fakes).map((flags) => flags.get('--role'))).toEqual(['functional-tester', 'lens-reviewer'])
  })
})

describe('pure helpers', () => {
  const ran = (exitCode: number, stdout: string) => ({ exitCode, stdout, stderr: '', isStdoutTruncated: false })
  const view = (match: object | null, schema = 'run_status.v1') => JSON.stringify({ schema, repo_root: WORKTREE, branch: '', match })

  test('parseUnitFor takes a clean match and refuses everything else', async () => {
    expect(parseUnitFor(ran(0, view(TARGET)))).toEqual(TARGET)
    expect(parseUnitFor(ran(0, view(null)))).toBe(null)
    expect(parseUnitFor(ran(0, view(TARGET, 'run_status.v2')))).toBe(null)
    expect(parseUnitFor(ran(2, view(TARGET)))).toBe(null)
    expect(parseUnitFor(ran(0, 'not json'))).toBe(null)
    expect(parseUnitFor(ran(0, view({ ...TARGET, issue: 0 })))).toBe(null)
    expect(parseUnitFor(ran(0, view({ ...TARGET, unit: '' })))).toBe(null)
    expect(parseUnitFor(ran(0, view({ ...TARGET, store_root: undefined })))).toBe(null)
    expect(parseUnitFor({ ...ran(0, view(TARGET)), isStdoutTruncated: true })).toBe(null)
  })

  test('effortName names an absent effort and stringifies a numeric one', async () => {
    expect(effortName(undefined)).toBe('none')
    expect(effortName('xhigh')).toBe('xhigh')
    expect(effortName(32)).toBe('32')
  })

  test("subagentRole reads a saga agent type and otherwise keeps the session's role", async () => {
    expect(subagentRole('saga:functional-tester', 'worker')).toBe('functional-tester')
    expect(subagentRole('general-purpose', 'worker')).toBe('worker')
    expect(subagentRole('saga:Bad Role', 'worker')).toBe('worker')
    expect(subagentRole(undefined, 'merging-worker')).toBe('merging-worker')
  })

  const step = { sessionId: 's', agentId: null, role: 'worker', model: 'm', effort: 'high', uncachedInput: 1, cacheRead: 2, cacheWrite: 3, output: 4 }

  test('addStep sums a repeat entry and starts a bucket for a new one', async () => {
    let queue: SagaUsageBucket[] = []
    queue = addStep(queue, step)
    queue = addStep(queue, step)
    queue = addStep(queue, { ...step, agentId: 'a1' })
    expect(queue.length).toBe(2)
    expect(queue[0]).toEqual({ ...step, uncachedInput: 2, cacheRead: 4, cacheWrite: 6, output: 8, steps: 2 })
    expect(queue[1].steps).toBe(1)
  })

  test('subtractWritten keeps what arrived during the write and drops an emptied bucket', async () => {
    const written = addStep([], step)[0]
    const grown = addStep(addStep([], step), step)
    expect(subtractWritten(grown, written)).toEqual([{ ...step, steps: 1 }])
    expect(subtractWritten([written], written)).toEqual([])
  })

  test('usageAddArgv passes the record store and every count to run_record.py usage add', async () => {
    const bucket = { ...step, agentId: 'a9', steps: 1 }
    expect(usageAddArgv('/root', TARGET, bucket)).toEqual([
      'python3',
      '/root/scripts/run_record.py',
      '--store-root',
      STORE,
      'usage',
      'add',
      '412',
      '--unit',
      'u2',
      '--session-id',
      's/a9',
      '--role',
      'worker',
      '--vendor',
      'claude',
      '--model',
      'm',
      '--effort',
      'high',
      '--uncached-input',
      '1',
      '--cache-read',
      '2',
      '--cache-write-1h',
      '3',
      '--output',
      '4',
    ])
  })
})
