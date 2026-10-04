import { describe, expect, test } from 'claude-code/testing'
import { AFK_REFUSAL, APPROVAL_PANE, APPROVAL_QUESTION, UNSEEN_TABLE, decisionFor } from './launch-approval.tsx'

const SURFACES = ['terminal', 'desktop'] as const
const TOOL = 'mcp__orchestrate__review_launch_table'

const TEXT = [
  'run r30   <- #48 deploy-guard remediation',
  'plan /tmp/plan.json   sha256 098e64187215',
  'vendors allowed: claude, codex   workspace: -   account: -',
  '',
  'unit        cap   agent  model effort perm   after serialize role task',
  '----------------------------------------------------------------------',
  'plan-claude /plan claude opus  high   bypass -     -         -    /saga:plan #48',
  '',
].join('\n')

const TABLE = {
  schema: 'orchestrate.launch_table.v1',
  issue: null,
  run_id: 'r30',
  source: '#48 deploy-guard remediation',
  plan: '/tmp/plan.json',
  plan_sha256: '098e64187215aaaa',
  vendors_allowed: ['claude', 'codex'],
  workspace: null,
  account: null,
  units: [],
  later_phases: [],
  text: TEXT,
}

type Ran = { exitCode: number; stdout: string; stderr: string }
type Asked = { result?: Record<string, unknown>; deny?: string }

/**
 * The engine beneath the plugin. `asked` answers the AskUserQuestion dialog the
 * way the engine would: `{ result: { answers } }`, or `{ deny }` for a dismissal.
 */
function world(
  on: any,
  asked: () => Asked | Promise<Asked>,
  ran: () => Ran = () => ({ exitCode: 0, stdout: JSON.stringify(TABLE), stderr: '' }),
  placed: () => Record<string, unknown> = () => ({ isPlaced: true }),
) {
  const runs: string[][] = []
  const questions: unknown[] = []
  const panes: string[] = []
  on('session.start', (_$: any, e: any) => e)
  on('command.register', (_$: any, e: any) => ({ value: { command: e.name } }))
  on('tool.register', (_$: any, e: any) => ({ value: { tool: `mcp__orchestrate__${e.name}` } }))
  on('ui.open', (_$: any, e: any) => {
    panes.push(`open ${e.id}`)
    return { value: placed() }
  })
  on('ui.close', (_$: any, e: any) => {
    panes.push(`close ${e.id}`)
    return { value: undefined }
  })
  on('process.run', (_$: any, e: any) => {
    runs.push([...e.argv])
    return { value: { ...ran(), isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('tool.call', { tool: 'AskUserQuestion' }, async (_$: any, e: any) => {
    questions.push(e.questions)
    return await asked()
  })
  return { runs, questions, panes }
}

const answering = (label: string, extra: Record<string, unknown> = {}) => (): Asked => ({
  result: { questions: [], answers: { [APPROVAL_QUESTION]: label }, ...extra },
})

async function start($: any) {
  await $.session.start({ source: 'startup', cwd: '/tmp', surface: 'terminal', isInteractive: true })
}

/** Nothing the mod ran can launch, land or close: only `launch-table`, read-only. */
function expectNoLaunch(runs: string[][]) {
  for (const argv of runs) {
    expect(argv[0]).toBe('python3')
    expect(argv[1].endsWith('/skills/orchestrate/scripts/orchestrate.py')).toBe(true)
    expect(argv[2]).toBe('launch-table')
    for (const word of ['go', 'start', 'expand', 'settle', 'merge', 'clean', 'wait', 'adopt']) {
      expect(argv.includes(word)).toBe(false)
    }
  }
}

describe('the operator answer reaches the model as the tool result', () => {
  test('Approve returns approval with the plan and its digest', async ($, on) => {
    const { runs, questions, panes } = world(on, answering('Approve'))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result).toEqual({ decision: 'approved', plan: '/tmp/plan.json', plan_sha256: '098e64187215aaaa' })
    expect(runs).toEqual([[runs[0][0], runs[0][1], 'launch-table', '--plan', '/tmp/plan.json', '--json']])
    expect(questions.length).toBe(1)
    const [question] = questions[0] as any[]
    expect(question.question).toBe(APPROVAL_QUESTION)
    expect(question.options.map((o: any) => o.label)).toEqual(['Change', 'Cancel', 'Approve'])
    expect(panes).toEqual([`open ${APPROVAL_PANE}`, `close ${APPROVAL_PANE}`])
    expectNoLaunch(runs)
  })

  test('the Change label returns a change with no request', async ($, on) => {
    const { runs } = world(on, answering('Change'))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result).toEqual({ decision: 'change', request: null })
    expectNoLaunch(runs)
  })

  test('text typed under Other returns a change carrying that request', async ($, on) => {
    const { runs } = world(on, answering('make plan-codex grok'))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result).toEqual({ decision: 'change', request: 'make plan-codex grok' })
    expectNoLaunch(runs)
  })

  test('Cancel returns cancelled', async ($, on) => {
    world(on, answering('Cancel'))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result).toEqual({ decision: 'cancelled' })
  })

  test('a dismissed dialog returns dismissed, never approved', async ($, on) => {
    const { runs, panes } = world(on, () => ({ deny: 'the person dismissed the dialog' }))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result.decision).toBe('dismissed')
    expect(panes).toEqual([`open ${APPROVAL_PANE}`, `close ${APPROVAL_PANE}`])
    expectNoLaunch(runs)
  })

  test('a dialog that resolved itself while the operator was away is dismissed, never approved', async ($, on) => {
    world(on, answering('Approve', { afkTimeoutMs: 60_000 }))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result.decision).toBe('dismissed')
    expect(r.result.reason).toContain(AFK_REFUSAL)
  })

  test('a plan the script refuses returns refused and asks nothing', async ($, on) => {
    const { questions, panes } = world(on, answering('Approve'), () => ({
      exitCode: 1,
      stdout: '',
      stderr: "permission not declared, inheriting auto: u1\nunit 'u1' waits on 'ghost', which is in no run\n",
    }))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result).toEqual({ decision: 'refused', reason: "unit 'u1' waits on 'ghost', which is in no run" })
    expect(questions).toEqual([])
    expect(panes).toEqual([])
  })

  test('a pane that waits undrawn asks nothing, approves nothing, and hands the table back', async ($, on) => {
    const reason = 'opened unasked below the 144-column floor; the terminal is 120 columns'
    const { runs, questions, panes } = world(on, answering('Approve'), undefined, () => ({ isPlaced: false, reason }))
    await start($)
    const r: any = await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    expect(r.result.decision).toBe('dismissed')
    expect(r.result.reason).toContain(UNSEEN_TABLE)
    expect(r.result.reason).toContain(reason)
    expect(r.result.text).toBe(TEXT)
    expect(questions).toEqual([])
    expect(panes).toEqual([`open ${APPROVAL_PANE}`, `close ${APPROVAL_PANE}`])
    expectNoLaunch(runs)
  })

  test('an expansion passes the issue to launch-table', async ($, on) => {
    const { runs } = world(on, answering('Approve'))
    await start($)
    await $.tool.call({ tool: TOOL, plan: '/tmp/expand.json', issue: 48 } as any)
    expect(runs.map((argv) => argv.slice(2))).toEqual([['launch-table', '--plan', '/tmp/expand.json', '--issue', '48', '--json']])
    expectNoLaunch(runs)
  })
})

describe('the AFK guard', () => {
  test('leaves an unrelated question, and its afkTimeoutMs, untouched', async ($, on) => {
    world(on, () => ({ result: { questions: [], answers: { 'Which file?': 'a.md' }, afkTimeoutMs: 60_000 } }))
    await start($)
    const r: any = await $.tool.call({
      tool: 'AskUserQuestion',
      questions: [{ question: 'Which file?', header: 'File', options: [{ label: 'a.md' }, { label: 'b.md' }], multiSelect: false }],
    } as any)
    expect(r.deny).toBeUndefined()
    expect(r.result.afkTimeoutMs).toBe(60_000)
    expect(r.result.answers).toEqual({ 'Which file?': 'a.md' })
  })
})

describe('the approval pane', () => {
  test('draws the script text line for line while the operator decides, on terminal and desktop', async ($, on) => {
    const drawn: Record<string, string[]> = {}
    // The dialog is open while the test draws the pane, as it is while the operator reads it.
    world(on, async () => {
      for (const surface of SURFACES) {
        const ui = await $.ui.mount({
          plugin: 'orchestrate',
          surface,
          component: 'Pane',
          requestId: APPROVAL_PANE,
          props: { title: 'Launch table', isFocused: false, bodyColumns: 160, placement: 'dock' },
        } as any)
        drawn[surface] = (await ui.findAll({ type: 'Text' })).map((t: any) => t.text)
        await ui.unmount()
      }
      return { result: { questions: [], answers: { [APPROVAL_QUESTION]: 'Cancel' } } }
    })
    await start($)
    await $.tool.call({ tool: TOOL, plan: '/tmp/plan.json' } as any)
    const want = TEXT.replace(/\n$/, '').split('\n').map((line) => (line === '' ? ' ' : line))
    for (const surface of SURFACES) expect(drawn[surface]).toEqual(want)
  })
})

describe('decisionFor', () => {
  test('only the exact Approve label approves', async () => {
    const table = { plan: 'p', plan_sha256: 's' }
    expect(decisionFor('Approve', table)).toEqual({ decision: 'approved', plan: 'p', plan_sha256: 's' })
    for (const near of ['approve', 'Approve ', 'Approve, Cancel', 'yes']) {
      expect(decisionFor(near, table).decision).toBe('change')
    }
  })
})
