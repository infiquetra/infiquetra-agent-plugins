// The plan viewer pane (issue #104): `/plan-view` reads a saga plan one
// section at a time inside Claude Code.
//
// Read-only. The plan file is the one thing it reads besides the run view
// `scripts/run_status.py summary` prints; the only thing it writes is the
// operator's own prompt, when they press a file reference or "Discuss this".
// The plain fallback on every other harness is the plan file itself, whose path
// `run_status.py summary` prints.
//
// - `/plan-view` opens the run's plan; `/plan-view #N` issue N's;
//   `/plan-view <path>` any Markdown file, relative to the session's directory.
// - The pane lists the sections by heading; choosing one draws it as Markdown,
//   paged under the engine's 10,000-character limit.
// - An Edit or Write of the plan file reloads it, and so does a change of its
//   modification time, polled every three seconds while the pane is open.
// - When `/plan` saves a plan tick, the pane opens unasked. The engine places
//   an unasked pane only from 144 columns; below that it is closed again and a
//   toast names the command instead.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { SagaPlanView } from '../types/index.d.ts'
import {
  discussPromptText,
  linkifyRefs,
  pageText,
  planSavePath,
  refFromHref,
  refPromptText,
  splitSections,
} from './plan-sections.ts'
import type { PlanRef } from './plan-sections.ts'
import { readRunStatusWith } from './run-record.ts'

/** The pane's id, and the `requestId` its `ui.render` hook matches. */
export const PLAN_PANE = 'saga-plan'

/** How often an open pane checks the plan file's modification time. */
export const PLAN_POLL_MS = 3_000

/** The most reference Buttons drawn under a page; the links in the page are all pressable. */
const MAX_REF_BUTTONS = 20

const planView = atom({ plugin: 'saga', key: 'planView' } as const, null)
const planSelected = atom({ plugin: 'saga', key: 'planSelected' } as const, -1)
const planPage = atom({ plugin: 'saga', key: 'planPage' } as const, 0)

type Loaded = { ok: true; view: SagaPlanView } | { ok: false; detail: string }

/** `path` taken from `cwd` unless it is absolute. */
export function absolutePath(cwd: string, path: string): string {
  return path.startsWith('/') ? path : `${cwd.replace(/\/+$/, '')}/${path.replace(/^\.\//, '')}`
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

/** Read and split the plan at `file`; a failure is a reason, never a throw. */
async function loadPlan($: EngineInterface, path: string, file: string, repoRoot: string): Promise<Loaded> {
  try {
    const stat = await $.fs.stat(file, { resolve: true })
    if (stat.kind !== 'file') return { ok: false, detail: `${path} is not a file` }
    const absPath = stat.realPath ?? file
    const text = await $.fs.read(absPath)
    return { ok: true, view: { path, absPath, repoRoot, mtimeMs: stat.mtimeMs, sections: splitSections(text) } }
  } catch (err) {
    return { ok: false, detail: `could not read ${path}: ${errorText(err)}` }
  }
}

/** Show `view` from its section list. */
async function showPlan($: EngineInterface, view: SagaPlanView): Promise<void> {
  await update($, planView, () => view)
  await update($, planSelected, () => -1)
  await update($, planPage, () => 0)
}

/** Read the shown plan again, keeping the reader on the section they were reading. */
async function reloadPlan($: EngineInterface, view: SagaPlanView): Promise<void> {
  const loaded = await loadPlan($, view.path, view.absPath, view.repoRoot)
  // A file caught mid-write or deleted keeps its last good version on screen.
  if (!loaded.ok) return
  const selected = await read($, planSelected)
  const was = view.sections[selected]
  const sections = loaded.view.sections
  let now = -1
  if (was !== undefined) {
    const same = sections.findIndex((one) => one.level === was.level && one.title === was.title)
    now = same >= 0 ? same : Math.min(selected, sections.length - 1)
  }
  await update($, planView, () => loaded.view)
  if (now !== selected) {
    await update($, planSelected, () => now)
    await update($, planPage, () => 0)
  }
}

/** Put text in the operator's prompt, saying so when the prompt cannot take it. */
async function fillPrompt($: EngineInterface, text: string): Promise<void> {
  const filled = await $.prompt.fill({ text, mode: 'insert' })
  if (!filled.isFilled) $.ui.toast('plan-view: the prompt cannot take text right now')
}

export function registerPlanViewer(on: On): void {
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    await $.command.register({
      name: 'plan-view',
      description: 'Read the saga plan one section at a time in a pane',
      argumentHint: '[path | #issue]',
      immediate: true,
    })

    // Catches what no tool call shows: an edit from another session, an editor, git.
    async function poll(): Promise<void> {
      const view = await read($, planView)
      if (view === null) return
      const panes = await $.ui.panes()
      if (!panes.some((pane) => pane.id === PLAN_PANE)) return
      try {
        const stat = await $.fs.stat(view.absPath)
        if (stat.mtimeMs === view.mtimeMs) return
      } catch {
        return
      }
      await reloadPlan($, view)
    }
    $.clock.every(PLAN_POLL_MS, () => {
      void poll()
    })

    return next(e)
  })

  on('command.run', { command: 'plan-view' }, async ($, e) => {
    const cwd = await $.session.cwd()
    const target = e.args.trim()
    let path: string
    let file: string
    let repoRoot = cwd

    const issueArg = /^#?(\d+)$/.exec(target)
    if (target === '' || issueArg !== null) {
      const issue = issueArg === null ? undefined : Number(issueArg[1])
      const ran = await readRunStatusWith((argv) => $.process.run(argv), $.plugin.root, { repoRoot: cwd, issue })
      if (!ran.ok) return { text: `plan-view: could not read the saga run (${ran.reason}): ${ran.detail}` }
      const run = ran.view.runs[0]
      if (run === undefined) {
        const which = issue === undefined ? 'for this checkout' : `for #${issue} in this checkout`
        return { text: `plan-view: no saga run ${which}. Name the plan instead: /plan-view docs/plans/<file>.md` }
      }
      if (run.plan_file === null || run.plan_path === null) {
        return { text: `plan-view: #${run.issue} has no plan recorded yet. Name one: /plan-view docs/plans/<file>.md` }
      }
      path = run.plan_path
      file = run.plan_file
      repoRoot = ran.view.repo_root
    } else {
      path = target
      file = absolutePath(cwd, target)
    }

    const loaded = await loadPlan($, path, file, repoRoot)
    if (!loaded.ok) return { text: `plan-view: ${loaded.detail}` }
    await showPlan($, loaded.view)
    await $.ui.open({ id: PLAN_PANE, title: `Plan · ${path.split('/').pop()}` })
    const count = loaded.view.sections.length
    return { text: `plan-view: ${path}, ${count} section${count === 1 ? '' : 's'}.` }
  })

  // An edit of the plan file reloads the pane.
  on('tool.call', { tool: 'Edit' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const view = await read($, planView)
    if (view === null) return ran
    try {
      const stat = await $.fs.stat(e.file_path, { resolve: true })
      if (stat.realPath === view.absPath) await reloadPlan($, view)
    } catch {
      // The poll catches what this misses.
    }
    return ran
  })

  on('tool.call', { tool: 'Write' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const view = await read($, planView)
    if (view === null) return ran
    try {
      const stat = await $.fs.stat(e.file_path, { resolve: true })
      if (stat.realPath === view.absPath) await reloadPlan($, view)
    } catch {
      // The poll catches what this misses.
    }
    return ran
  })

  // `/plan` saving a plan tick opens the pane unasked, where there is room.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const saved = planSavePath(e.command)
    if (saved === null) return ran
    const cwd = await $.session.cwd()
    const loaded = await loadPlan($, saved, absolutePath(cwd, saved), cwd)
    if (!loaded.ok) return ran
    await showPlan($, loaded.view)
    const opened = await $.ui.open({ id: PLAN_PANE, title: `Plan · ${saved.split('/').pop()}` })
    if (!opened.isPlaced) {
      // A pane that appears later, when the terminal widens, would be a surprise.
      await $.ui.close({ id: PLAN_PANE })
      $.ui.toast('Plan saved: run /plan-view to read it here')
    }
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PLAN_PANE }, async ($, e) => {
    const { Box, Button, Markdown, Text } = $.ui.resolve(e)
    const view = await read($, planView)
    if (view === null) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No plan loaded. Run /plan-view, /plan-view #issue or /plan-view path.</Text>
        </Box>
      )
    }

    const selected = await read($, planSelected)
    const section = view.sections[selected]
    if (section === undefined) {
      const count = view.sections.length
      return (
        <Box flexDirection="column">
          <Text dimColor>
            {view.path} · {count} section{count === 1 ? '' : 's'}
          </Text>
          {count === 0 && <Text>This plan has no headings.</Text>}
          {view.sections.map((one, i) => (
            <Button
              key={`sec-${i}`}
              label={`${'  '.repeat(Math.max(0, one.level - 1))}${one.title}`}
              plain
              onPress={async () => {
                await update($, planSelected, () => i)
                await update($, planPage, () => 0)
              }}
            />
          ))}
        </Box>
      )
    }

    const pages = pageText(section.text)
    const page = Math.min(Math.max(0, await read($, planPage)), pages.length - 1)
    const { text, refs } = linkifyRefs(pages[page] ?? '', view.repoRoot)
    const pressRef = async (ref: PlanRef | null) => {
      if (ref !== null) await fillPrompt($, refPromptText(ref))
    }

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          <Button key="back" label="Sections" onPress={() => update($, planSelected, () => -1)} />
          {page > 0 && <Button key="page-prev" label="Previous page" onPress={() => update($, planPage, () => page - 1)} />}
          {page < pages.length - 1 && (
            <Button key="page-next" label="Next page" onPress={() => update($, planPage, () => page + 1)} />
          )}
          <Button
            key="discuss"
            label="Discuss this"
            variant="primary"
            onPress={() => fillPrompt($, discussPromptText(view.path, section, page, pages.length))}
          />
        </Box>
        <Text dimColor>
          {section.title} · page {page + 1} of {pages.length}
        </Text>
        {refs.length > 0 ? (
          <Markdown
            key="section"
            text={text}
            pressableLinks={refs.map((ref) => ref.href)}
            onLinkPress={(link) => {
              void pressRef(refFromHref(link.href, view.repoRoot, refs))
            }}
          />
        ) : (
          <Markdown key="section" text={text} />
        )}
        {refs.slice(0, MAX_REF_BUTTONS).map((ref, k) => (
          <Button key={`ref-${k}`} label={ref.label} plain dimColor onPress={() => pressRef(ref)} />
        ))}
      </Box>
    )
  })
}
