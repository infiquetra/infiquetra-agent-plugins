import { describe, expect, mock, test } from 'claude-code/testing'
import { FLEET_PANE, REFRESH_MS, fleetLines, parseIssue } from './fleet-view.tsx'

const SURFACES = ['terminal', 'desktop'] as const

const STATUS = {
  schema: 'orchestrate.status.v1',
  issue: 7,
  run_id: 'r1',
  source: '#7 a test',
  base: 'abc',
  branch: 'issue/7',
  unresolvable_branch: null,
  companion_available: true,
  units: [
    {
      name: 'plan-claude',
      vendor: 'claude',
      model: 'opus',
      effort: 'high',
      state: 'running',
      herdr: 'working',
      branch: 'orch/r1-plan-claude',
      commits: 2,
      landed: 'no',
      waits_on: '',
      task: '/saga:plan #7',
      note: '',
      role: null,
      lifecycle: null,
      merge_state: 'ready',
      after: [],
      serialize: [],
    },
    {
      name: 'build-codex',
      vendor: 'codex',
      model: 'gpt-5.6-sol',
      effort: 'xhigh',
      state: 'pending',
      herdr: null,
      branch: null,
      commits: null,
      landed: null,
      waits_on: 'needs output from plan-claude',
      task: '/work',
      note: '',
      role: null,
      lifecycle: null,
      merge_state: 'ready',
      after: ['plan-claude'],
      serialize: [],
    },
  ],
  unrecorded: [{ name: 'stray', branch: 'orch/r1-stray' }],
  reviews: [],
  operator_actions: [],
}

type Ran = { exitCode: number; stdout: string; stderr: string }

/** The engine beneath the plugin: a clock, panes, commands, and a scripted process runner. */
function world(on: any, answer: () => Ran) {
  const clock = mock.clock(on)
  const runs: string[][] = []
  const opened: string[] = []
  let panes: { id: string; title: string; isShown: boolean; isFocused: boolean; isPlaced: boolean }[] = []
  on('session.start', (_$: any, e: any) => e)
  on('command.register', (_$: any, e: any) => ({ value: { command: e.name } }))
  on('tool.register', (_$: any, e: any) => ({ value: { tool: `mcp__orchestrate__${e.name}` } }))
  on('ui.open', (_$: any, e: any) => {
    opened.push(e.id)
    panes = [...panes.filter((p) => p.id !== e.id), { id: e.id, title: e.title ?? '', isShown: true, isFocused: false, isPlaced: true }]
    return { value: { isPlaced: true } }
  })
  on('ui.close', (_$: any, e: any) => {
    panes = panes.filter((p) => p.id !== e.id)
    return { value: undefined }
  })
  on('ui.panes', () => ({ value: panes }))
  on('process.run', (_$: any, e: any) => {
    runs.push([...e.argv])
    return { value: { ...answer(), isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return { clock, runs, opened }
}

const ok = (): Ran => ({ exitCode: 0, stdout: JSON.stringify(STATUS), stderr: '' })

async function start($: any) {
  await $.session.start({ source: 'startup', cwd: '/tmp', surface: 'terminal', isInteractive: true })
}

async function mountPane($: any, surface: (typeof SURFACES)[number]) {
  return $.ui.mount({
    plugin: 'orchestrate',
    surface,
    component: 'Pane',
    requestId: FLEET_PANE,
    props: { title: 'orchestrate #7', isFocused: false, bodyColumns: 160, placement: 'dock' },
  })
}

describe('fleet pane', () => {
  test('draws one row per unit from the status JSON, on terminal and desktop', async ($, on) => {
    world(on, ok)
    await start($)
    const ran: any = await $.command.run({ command: 'fleet-view', args: '#7' } as any)
    expect(ran.text).toContain('#7')
    for (const surface of SURFACES) {
      const ui = await mountPane($, surface)
      const rows = (await ui.findAll({ type: 'Text' })).map((t: any) => t.text)
      const plan = rows.find((r: string) => r.startsWith('plan-claude'))
      const build = rows.find((r: string) => r.startsWith('build-codex'))
      expect(plan).toBeDefined()
      expect(build).toBeDefined()
      for (const cell of ['claude', 'opus', 'high', 'running', 'working', 'orch/r1-plan-claude', '2', 'no']) {
        expect(plan).toContain(cell)
      }
      for (const cell of ['codex', 'gpt-5.6-sol', 'xhigh', 'pending', 'needs output from plan-claude']) {
        expect(build).toContain(cell)
      }
      expect(rows.some((r: string) => r.startsWith('run r1') && r.includes('issue/7'))).toBe(true)
      expect(rows.some((r: string) => r.includes('UNRECORDED stray'))).toBe(true)
      await ui.unmount()
    }
  })

  test('draws the refusal line when the script exits non-zero, without throwing', async ($, on) => {
    world(on, () => ({ exitCode: 2, stdout: '', stderr: 'the run record for issue 7 carries no orchestrate block\n' }))
    await start($)
    await $.command.run({ command: 'fleet-view', args: '7' } as any)
    for (const surface of SURFACES) {
      const ui = await mountPane($, surface)
      const error = await ui.find({ type: 'Text', text: 'the run record for issue 7 carries no orchestrate block' })
      expect(error?.props.color).toBe('red')
      await ui.unmount()
    }
  })

  test('says so when the script prints no JSON', async ($, on) => {
    world(on, () => ({ exitCode: 0, stdout: 'run r1 base abc\n', stderr: '' }))
    await start($)
    await $.command.run({ command: 'fleet-view', args: '7' } as any)
    const ui = await mountPane($, 'terminal')
    expect((await ui.find({ type: 'Text', text: 'orchestrate.py printed no JSON' }))?.props.color).toBe('red')
    await ui.unmount()
  })

  test('without an issue number it prints the usage and opens nothing', async ($, on) => {
    const { opened, runs } = world(on, ok)
    await start($)
    for (const args of ['', 'seven', '7 8', '-3', '0']) {
      const ran: any = await $.command.run({ command: 'fleet-view', args } as any)
      expect(ran.text).toBe('Usage: /fleet-view <issue>')
    }
    expect(opened).toEqual([])
    expect(runs).toEqual([])
  })

  test('refreshes on the timer only while the pane is open', async ($, on) => {
    const { clock, runs } = world(on, ok)
    await start($)
    await $.command.run({ command: 'fleet-view', args: '7' } as any)
    expect(runs.length).toBe(1)
    await clock.advance(REFRESH_MS)
    expect(runs.length).toBe(2)
    await clock.advance(REFRESH_MS)
    expect(runs.length).toBe(3)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'close' })
    await ui.unmount()
    await clock.advance(REFRESH_MS * 3)
    expect(runs.length).toBe(3)
  })

  test('the Refresh button re-reads status', async ($, on) => {
    const { runs } = world(on, ok)
    await start($)
    await $.command.run({ command: 'fleet-view', args: '7' } as any)
    const ui = await mountPane($, 'terminal')
    await ui.press({ key: 'refresh' })
    expect(runs.length).toBe(2)
    await ui.unmount()
  })

  test('runs only `status --json` and offers no launch, settle, merge or clean action', async ($, on) => {
    const { clock, runs } = world(on, ok)
    await start($)
    await $.command.run({ command: 'fleet-view', args: '7' } as any)
    await clock.advance(REFRESH_MS)
    for (const surface of SURFACES) {
      const ui = await mountPane($, surface)
      await ui.press({ key: 'refresh' })
      const buttons = await ui.findAll({ type: 'Button' })
      expect(buttons.map((b: any) => b.key)).toEqual(['refresh', 'close'])
      for (const button of buttons) {
        expect(`${button.key} ${String(button.props.label)}`).not.toMatch(/launch|\bgo\b|settle|merge|clean|start|expand/i)
      }
      await ui.unmount()
    }
    expect(runs.length).toBeGreaterThan(2)
    for (const argv of runs) {
      expect(argv[0]).toBe('python3')
      expect(argv[1].endsWith('/skills/orchestrate/scripts/orchestrate.py')).toBe(true)
      expect(argv.slice(2)).toEqual(['status', '--issue', '7', '--json'])
    }
  })
})

describe('pure helpers', () => {
  test('parseIssue reads 7 and #7 and nothing else', async () => {
    expect(parseIssue('7')).toBe(7)
    expect(parseIssue(' #12 ')).toBe(12)
    for (const bad of ['', 'x', '#', '1.5', '7 8', '0']) expect(parseIssue(bad)).toBe(null)
  })

  test('fleetLines pads columns and cuts each line to the width', async () => {
    const lines = fleetLines(STATUS as any, 40)
    expect(lines[0].startsWith('unit ')).toBe(true)
    for (const line of lines) expect(line.length <= 40).toBe(true)
    const wide = fleetLines(STATUS as any, 400)
    const header = wide[0]
    const plan = wide[2]
    expect(plan.slice(header.indexOf('commits'), header.indexOf('landed')).trim()).toBe('2')
    expect(wide[3].slice(header.indexOf('commits'), header.indexOf('landed')).trim()).toBe('-')
  })
})
