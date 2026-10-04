import type { On } from 'claude-code'
import { describe, expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

import { MARKDOWN_LIMIT } from './plan-sections.ts'
import { PLAN_PANE, PLAN_POLL_MS } from './plan-viewer.tsx'

const CWD = '/Users/operator/repo'
const PLAN_PATH = 'docs/plans/2026-10-04-viewer-plan.md'
const PLAN_FILE = `${CWD}/${PLAN_PATH}`

const PLAN = [
  '---',
  'date: 2026-10-04',
  '---',
  '# Viewer plan',
  '',
  'Intro.',
  '',
  '## Problem',
  '',
  'Plans are read in another tool. See `plugins/saga/scripts/run_status.py:12`.',
  '',
  '## Units',
  '',
  '### U1 split',
  '',
  'Split it.',
  '',
  '### U2 page',
  '',
  'Page it.',
].join('\n')

const PANE = {
  component: 'Pane',
  requestId: PLAN_PANE,
  props: {
    title: 'Plan',
    isFocused: true,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const SURFACES = ['terminal', 'desktop'] as const

type Fake = {
  files: Map<string, { text: string; mtimeMs: number }>
  opened: string[]
  closed: string[]
  toasts: string[]
  fills: string[]
  runs: string[][]
  placed: boolean
  isFilled: boolean
  clock: ReturnType<typeof mock.clock>
  runStatus: { exitCode: number; stdout: string; stderr: string }
}

function runStatusOf(runs: object[]): Fake['runStatus'] {
  return { exitCode: 0, stdout: JSON.stringify({ schema: 'run_status.v1', repo_root: CWD, runs }), stderr: '' }
}

const RUN = {
  issue: 104,
  repo: 'infiquetra/infiquetra-agent-plugins',
  next_step: 'run /work',
  updated_at: '2026-10-04T00:00:00+00:00',
  record_path: `${CWD}/.claude/saga/runs/issue-104.json`,
  phase: 'plan',
  plan_path: PLAN_PATH,
  plan_file: PLAN_FILE,
}

/** Answer every engine call the viewer makes from an in-memory file system. */
function fake(on: On): Fake {
  const state: Fake = {
    files: new Map([[PLAN_FILE, { text: PLAN, mtimeMs: 1 }]]),
    opened: [],
    closed: [],
    toasts: [],
    fills: [],
    runs: [],
    placed: true,
    isFilled: true,
    clock: mock.clock(on),
    runStatus: runStatusOf([RUN]),
  }
  on('session.start', async ($, e) => ({ cwd: e.cwd }))
  on('command.register', async ($, e) => ({ value: { command: e.name } }))
  on('session.cwd', async () => ({ value: CWD }))
  on('process.run', async ($, e) => {
    state.runs.push([...e.argv])
    return { value: { ...state.runStatus, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('fs.stat', async ($, e) => {
    const file = state.files.get(e.path)
    if (file === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: { kind: 'file', size: file.text.length, mtimeMs: file.mtimeMs, isLink: false, realPath: e.path } }
  })
  on('fs.read', async ($, e) => {
    const file = state.files.get(e.path)
    if (file === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: file.text }
  })
  on('ui.open', async ($, e) => {
    state.opened.push(e.id)
    return { value: state.placed ? { isPlaced: true } : { isPlaced: false, reason: 'unasked below 144 columns (now 100)' } }
  })
  on('ui.close', async ($, e) => {
    state.closed.push(e.id)
    return { value: undefined }
  })
  on('ui.panes', async () => ({
    value: state.opened.length > state.closed.length
      ? [{ id: PLAN_PANE, title: 'Plan', isShown: true, isFocused: false, isPlaced: true }]
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

/** `/plan-view <args>` as the operator types it at a wide fullscreen terminal. */
function planView($: Engine, args: string) {
  return $.command.run({
    command: 'plan-view',
    args,
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 160 },
  })
}

async function sectionLabels(ui: { findAll: (q: { type: string }) => Promise<{ key: string | undefined; props: Record<string, unknown> }[]> }) {
  const buttons = await ui.findAll({ type: 'Button' })
  return buttons.filter((b) => b.key?.startsWith('sec-')).map((b) => String(b.props.label).trim())
}

describe('/plan-view', () => {
  test('opens the pane on a named plan and lists its headings on terminal and desktop', async ($, on) => {
    const fakes = fake(on)
    await start($)
    const ran = await planView($, PLAN_PATH)
    expect(ran.text).toBe(`plan-view: ${PLAN_PATH}, 6 sections.`)
    expect(fakes.opened).toEqual([PLAN_PANE])
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      expect(await sectionLabels(ui)).toEqual(['Frontmatter', 'Viewer plan', 'Problem', 'Units', 'U1 split', 'U2 page'])
      await ui.unmount()
    }
  })

  test('with no argument opens the plan run_status.py names for the run', async ($, on) => {
    const fakes = fake(on)
    await start($)
    const ran = await planView($, '')
    expect(ran.text).toContain(PLAN_PATH)
    expect(fakes.runs).toEqual([['python3', expect.stringMatching(/\/scripts\/run_status\.py$/), '--repo-root', CWD, 'summary', '--json']])
    expect(fakes.opened).toEqual([PLAN_PANE])
  })

  test('#N asks run_status.py for that issue', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await planView($, '#104')
    expect(fakes.runs[0]).toContain('--issue')
    expect(fakes.runs[0]).toContain('104')
  })

  test('with no run and no path says so in one line and opens no pane', async ($, on) => {
    const fakes = fake(on)
    fakes.runStatus = runStatusOf([])
    await start($)
    const ran = await planView($, '')
    expect(ran.text).toBe('plan-view: no saga run for this checkout. Name the plan instead: /plan-view docs/plans/<file>.md')
    expect(fakes.opened).toEqual([])
  })

  test('a run with no plan recorded says so and opens no pane', async ($, on) => {
    const fakes = fake(on)
    fakes.runStatus = runStatusOf([{ ...RUN, plan_path: null, plan_file: null }])
    await start($)
    const ran = await planView($, '')
    expect(ran.text).toContain('#104 has no plan recorded yet')
    expect(fakes.opened).toEqual([])
  })

  test('an unknown run view version is reported, not guessed at', async ($, on) => {
    const fakes = fake(on)
    fakes.runStatus = { exitCode: 3, stdout: '', stderr: 'run_status: unknown record version' }
    await start($)
    const ran = await planView($, '')
    expect(ran.text).toContain('unknown-version')
    expect(fakes.opened).toEqual([])
  })

  test('a missing file is reported and opens no pane', async ($, on) => {
    const fakes = fake(on)
    await start($)
    const ran = await planView($, 'docs/plans/missing.md')
    expect(ran.text).toContain('could not read docs/plans/missing.md')
    expect(fakes.opened).toEqual([])
  })
})

describe('the plan pane', () => {
  test('selecting a section draws it as Markdown and Sections goes back', async ($, on) => {
    fake(on)
    await start($)
    await planView($, PLAN_PATH)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'sec-3' })
      const shown = await ui.find({ type: 'Markdown', key: 'section' })
      expect(shown?.props.text).toBe('## Units\n\n### U1 split\n\nSplit it.\n\n### U2 page\n\nPage it.')
      expect(await ui.find({ type: 'Text', text: /Units · page 1 of 1/ })).toBeDefined()
      await ui.press({ key: 'back' })
      expect(await ui.find({ type: 'Markdown', key: 'section' })).toBeUndefined()
      expect(await sectionLabels(ui)).toHaveLength(6)
      await ui.unmount()
    }
  })

  test('a section longer than 10,000 characters is paged, never refused', async ($, on) => {
    const fakes = fake(on)
    const paragraph = 'Long plan text that goes on. '.repeat(30).trim()
    const long = ['## Long', ...Array.from({ length: 30 }, () => paragraph)].join('\n\n')
    expect(long.length).toBeGreaterThan(2 * MARKDOWN_LIMIT)
    fakes.files.set(PLAN_FILE, { text: long, mtimeMs: 1 })
    await start($)
    await planView($, PLAN_PATH)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'sec-0' })
      expect(await ui.find({ type: 'Text', text: /Long · page 1 of 3/ })).toBeDefined()
      expect(await ui.find({ key: 'page-prev' })).toBeUndefined()
      const seen: string[] = []
      for (let page = 0; page < 3; page++) {
        await ui.drawn()
        const shown = await ui.find({ type: 'Markdown', key: 'section' })
        const text = String(shown?.props.text)
        expect(text.length).toBeLessThanOrEqual(MARKDOWN_LIMIT)
        seen.push(text)
        if (page < 2) await ui.press({ key: 'page-next' })
      }
      expect(await ui.find({ type: 'Text', text: /page 3 of 3/ })).toBeDefined()
      expect(await ui.find({ key: 'page-next' })).toBeUndefined()
      expect(seen.join('\n\n')).toBe(long)
      await ui.press({ key: 'page-prev' })
      expect(await ui.find({ type: 'Text', text: /page 2 of 3/ })).toBeDefined()
      await ui.press({ key: 'back' })
      await ui.unmount()
    }
  })

  test('pressing a file link fills the prompt with the file and line, and so does its Button', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await planView($, PLAN_PATH)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'sec-2' })
      const shown = await ui.find({ type: 'Markdown', key: 'section' })
      const href = `file://${CWD}/plugins/saga/scripts/run_status.py#L12`
      expect(shown?.props.text).toContain(`[\`plugins/saga/scripts/run_status.py:12\`](${href})`)
      expect(shown?.props.pressableLinks).toEqual([href])
      await ui.press({ key: 'section', link: { href } })
      await ui.press({ key: 'ref-0' })
      await ui.press({ key: 'back' })
      await ui.unmount()
    }
    expect(fakes.fills).toEqual(Array(4).fill('`plugins/saga/scripts/run_status.py:12` '))
  })

  test('"Discuss this" quotes the shown section into the prompt', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await planView($, PLAN_PATH)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      await ui.press({ key: 'sec-4' })
      await ui.press({ key: 'discuss' })
      await ui.press({ key: 'back' })
      await ui.unmount()
    }
    const quoted = `From the plan ${PLAN_PATH}, section "U1 split":\n\n> ### U1 split\n>\n> Split it.\n\n`
    expect(fakes.fills).toEqual([quoted, quoted])
  })

  test('a prompt that cannot take the text says so in a toast', async ($, on) => {
    const fakes = fake(on)
    fakes.isFilled = false
    await start($)
    await planView($, PLAN_PATH)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    await ui.press({ key: 'sec-4' })
    await ui.press({ key: 'discuss' })
    expect(fakes.toasts).toEqual(['plan-view: the prompt cannot take text right now'])
  })

  test('with nothing loaded the pane says how to load a plan', async ($, on) => {
    fake(on)
    await start($)
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({ plugin: 'saga', surface, ...PANE })
      expect(await ui.find({ type: 'Text', text: /No plan loaded/ })).toBeDefined()
      await ui.unmount()
    }
  })
})

describe('refreshing the pane', () => {
  test('an Edit of the plan path reloads it; an Edit of another path does not', async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Edit' }, async () => ({ result: {}, text: 'edited' }))
    await start($)
    await planView($, PLAN_PATH)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })

    fakes.files.set(PLAN_FILE, { text: `${PLAN}\n\n## Risks\n\nNone.`, mtimeMs: 2 })
    fakes.files.set(`${CWD}/README.md`, { text: '# Readme', mtimeMs: 2 })
    await $.tool.call({ tool: 'Edit', file_path: `${CWD}/README.md`, old_string: 'a', new_string: 'b' })
    expect(await sectionLabels(ui)).toHaveLength(6)

    await $.tool.call({ tool: 'Edit', file_path: PLAN_FILE, old_string: 'a', new_string: 'b' })
    expect((await sectionLabels(ui)).at(-1)).toBe('Risks')
  })

  test('a Write of the plan path reloads it and keeps the reader on their section', async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Write' }, async () => ({ result: {}, text: 'written' }))
    await start($)
    await planView($, PLAN_PATH)
    const terminal = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    await terminal.press({ key: 'sec-2' })
    await terminal.unmount()
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'desktop', ...PANE })
    const edited = PLAN.replace('# Viewer plan', '# Viewer plan\n\n## Added first').replace('Plans are read', 'Plans were read')
    fakes.files.set(PLAN_FILE, { text: edited, mtimeMs: 2 })
    await $.tool.call({ tool: 'Write', file_path: PLAN_FILE, content: edited })
    const shown = await ui.find({ type: 'Markdown', key: 'section' })
    expect(String(shown?.props.text)).toContain('Plans were read')
    expect(String(shown?.props.text)).toMatch(/^## Problem/)
  })

  test('a change of modification time reloads the open pane on the next poll', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await planView($, PLAN_PATH)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    fakes.files.set(PLAN_FILE, { text: `${PLAN}\n\n## Risks\n\nNone.`, mtimeMs: 5 })
    await fakes.clock.advance(PLAN_POLL_MS)
    expect((await sectionLabels(ui)).at(-1)).toBe('Risks')
  })

  test('a poll with the pane closed reads nothing', async ($, on) => {
    const fakes = fake(on)
    await start($)
    await planView($, PLAN_PATH)
    fakes.closed.push(PLAN_PANE)
    fakes.files.set(PLAN_FILE, { text: `${PLAN}\n\n## Risks\n\nNone.`, mtimeMs: 5 })
    await fakes.clock.advance(PLAN_POLL_MS)
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    expect(await sectionLabels(ui)).toHaveLength(6)
  })
})

describe('opening after /plan saves', () => {
  const SAVE = `python3 plugins/saga/scripts/saga.py save --kind issue --id 104 --lifecycle-phase plan --phase-status complete --plan-path '${PLAN_PATH}' --destination pr`

  test('opens the pane unasked when the engine places it', async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Bash' }, async () => ({ result: {}, text: 'saved' }))
    await start($)
    await $.tool.call({ tool: 'Bash', command: SAVE })
    expect(fakes.opened).toEqual([PLAN_PANE])
    expect(fakes.closed).toEqual([])
    expect(fakes.toasts).toEqual([])
    const ui = await $.ui.mount({ plugin: 'saga', surface: 'terminal', ...PANE })
    expect(await sectionLabels(ui)).toHaveLength(6)
  })

  test('below 144 columns closes the waiting pane and names the command in a toast', async ($, on) => {
    const fakes = fake(on)
    fakes.placed = false
    on('tool.call', { tool: 'Bash' }, async () => ({ result: {}, text: 'saved' }))
    await start($)
    await $.tool.call({ tool: 'Bash', command: SAVE })
    expect(fakes.closed).toEqual([PLAN_PANE])
    expect(fakes.toasts).toEqual(['Plan saved: run /plan-view to read it here'])
  })

  test('other commands, other phases and failed saves open nothing', async ($, on) => {
    const fakes = fake(on)
    on('tool.call', { tool: 'Bash' }, async ($, e) =>
      e.command.includes('fails') ? { result: {}, text: 'boom', isError: true } : { result: {}, text: 'ok' },
    )
    await start($)
    await $.tool.call({ tool: 'Bash', command: 'git status' })
    await $.tool.call({ tool: 'Bash', command: SAVE.replace('--lifecycle-phase plan', '--lifecycle-phase work') })
    await $.tool.call({ tool: 'Bash', command: `${SAVE} && fails` })
    expect(fakes.opened).toEqual([])
  })
})
