// The run status band (issue #105): one line per active saga run above the
// prompt, and the issue and phase in saga's status-line entry.
//
// Read-only. Every word comes from `scripts/run_status.py summary --all-active`,
// whose `band_line` the script renders once for every harness: the build loop's
// latest pass, the review cycle against its allowance, and how many lenses met
// their bar by the verdict's own rule. The band never recomputes any of it and
// no button here changes the run. The plain fallback on every other harness is
// `run_status.py summary --band`.
//
// - Refreshes after the session starts, every minute, after each main-loop turn
//   completes, and after a Bash call that ran one of saga's or orchestrate's
//   state scripts. A refresh is queued on the clock so it never holds up a turn.
// - With no active run the band passes and the status line is cleared.
// - Plan and Review open the plan viewer (issue #104) and the review findings
//   pane (issue #108) for the first run; those modules answer the press. Record
//   shows the raw record as `run_record.py show` prints it; Hide hides the band
//   for the session.
// - This is the only saga mod that sets saga's status line: the engine keeps
//   one line per plugin, so a second writer would overwrite this one.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { SagaRunStatus } from '../types/index.d.ts'
import { readRunRecordWith, readRunStatusWith } from './run-record.ts'

/** The raw record pane's id, and the `requestId` its `ui.render` hook matches. */
export const RECORD_PANE = 'saga-record'

/** How often the band reads the runs again with nothing else prompting it. */
export const BAND_REFRESH_MS = 60_000

/** A Code block holds at most 10,000 characters; a page of the record stays under it. */
export const RECORD_PAGE_CHARS = 9_000

/** A Bash command that ran a script which writes saga run state. */
const WRITES_RUN_STATE = /\b(run_record|build_loop|review_result|admission|merge_turn|release_step|saga|orchestrate)\.py\b/

const runStatus = atom({ plugin: 'saga', key: 'runStatus' } as const, [])
const bandHidden = atom({ plugin: 'saga', key: 'bandHidden' } as const, false)
const recordView = atom({ plugin: 'saga', key: 'recordView' } as const, null)

/** Saga's status-line entry for the first run: the issue and its phase alone. */
export function statusText(runs: readonly SagaRunStatus[]): string | undefined {
  const run = runs[0]
  if (run === undefined) return undefined
  return run.phase ? `saga #${run.issue} · ${run.phase}` : `saga #${run.issue}`
}

/** A line cut to `columns` cells, an ellipsis marking the cut. */
export function fitLine(line: string, columns: number): string {
  if (columns <= 0) return ''
  const chars = [...line]
  return chars.length <= columns ? line : `${chars.slice(0, columns - 1).join('')}…`
}

/** A record's JSON cut into pages a Code block can hold, breaking at a newline where one is near. */
export function recordPages(json: string, limit = RECORD_PAGE_CHARS): string[] {
  const pages: string[] = []
  let rest = json
  while (rest.length > limit) {
    const cut = rest.lastIndexOf('\n', limit - 1)
    let end = cut > limit / 2 ? cut + 1 : limit
    // Never split a surrogate pair across two pages.
    if (end === limit && /[\uD800-\uDBFF]/.test(rest[end - 1] ?? '')) end -= 1
    pages.push(rest.slice(0, end))
    rest = rest.slice(end)
  }
  pages.push(rest)
  return pages
}

/**
 * Read the runs again and redraw. A read that fails keeps what the band showed:
 * a record caught mid-write must not blank it, and the next refresh retries.
 */
async function refreshBand($: EngineInterface): Promise<void> {
  const cwd = await $.session.cwd()
  const ran = await readRunStatusWith((argv) => $.process.run(argv), $.plugin.root, { repoRoot: cwd, allActive: true })
  if (!ran.ok) return
  const runs = ran.view.runs
  await update($, runStatus, () => runs)
  $.ui.status(statusText(runs))
}

/**
 * The Plan and Review buttons' keys. The plan viewer and the review pane answer
 * a press on these themselves (`BAND_PLAN_ELEMENT`, `BAND_REVIEW_ELEMENT`): a
 * plugin's own `$.command.run` never reaches its own command hook, while a
 * press is raised by the engine and reaches every hook.
 */
export function bandPlanKey(issue: number): string {
  return `band-plan-${issue}`
}

export function bandReviewKey(issue: number): string {
  return `band-review-${issue}`
}

/** The bottom of a press the pane modules answer; it runs only if neither is registered. */
function paneNotLoaded(): void {}

/** Load issue `issue`'s raw run record into the record pane and open it. */
async function openRecord($: EngineInterface, issue: number): Promise<void> {
  const loaded = await readRunRecordWith((argv) => $.process.run(argv), $.plugin.root, issue)
  if (!loaded.ok) {
    $.ui.toast(`saga: could not read the run record for #${issue} (${loaded.reason}): ${loaded.detail}`)
    return
  }
  const pages = recordPages(JSON.stringify(loaded.record, null, 2))
  await update($, recordView, () => ({ issue, pages, page: 0 }))
  await $.ui.open({ id: RECORD_PANE, title: `Run record · #${issue}` })
}

/** Whether a refresh is running, and whether another was asked for while it ran. */
let refreshing = false
let refreshAgain = false

/**
 * Queue a refresh on the clock, so the dispatch that asked is not held up. One
 * runs at a time; requests made meanwhile fold into one more read after it.
 */
function requestRefresh($: EngineInterface): void {
  $.clock.after(0, async () => {
    if (refreshing) {
      refreshAgain = true
      return
    }
    refreshing = true
    try {
      do {
        refreshAgain = false
        await refreshBand($)
      } while (refreshAgain)
    } finally {
      refreshing = false
    }
  })
}

export function registerRunBand(on: On): void {
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    requestRefresh($)
    $.clock.every(BAND_REFRESH_MS, () => {
      requestRefresh($)
    })
    return next(e)
  })

  // A subagent's turn ending is not the run moving; the main loop's is.
  on('turn.complete', { turnId: /^/ }, async ($, e, next) => {
    if (e.agentId === undefined) requestRefresh($)
    return next(e)
  })

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny === undefined && WRITES_RUN_STATE.test(e.command)) requestRefresh($)
    return ran
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey || (await read($, bandHidden))) return next(e)
    const runs = await read($, runStatus)
    const first = runs[0]
    if (first === undefined) return next(e)

    const { Box, Button, Text } = $.ui.resolve(e)
    const shown = runs.slice(0, Math.max(1, e.props.maxRows - 1))
    return (
      <Box flexDirection="column">
        {shown.map((run) => (
          <Text key={`run-${run.issue}`}>{fitLine(run.band_line, e.props.bodyColumns)}</Text>
        ))}
        <Box key="actions" flexDirection="row" gap={1}>
          <Button key={bandPlanKey(first.issue)} label="Plan" hotkey="p" onPress={paneNotLoaded} />
          <Button key={bandReviewKey(first.issue)} label="Review" hotkey="r" onPress={paneNotLoaded} />
          <Button key="record" label="Record" hotkey="o" onPress={() => openRecord($, first.issue)} />
          <Button key="hide" label="Hide" hotkey="h" onPress={() => update($, bandHidden, () => true)} />
        </Box>
      </Box>
    )
  })

  on('ui.render', { component: 'Pane', requestId: RECORD_PANE }, async ($, e) => {
    const { Box, Button, Code, Text } = $.ui.resolve(e)
    const view = await read($, recordView)
    if (view === null) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No run record loaded. Press Record on the saga run band.</Text>
        </Box>
      )
    }
    const page = Math.min(view.page, view.pages.length - 1)
    const turn = (to: number) => update($, recordView, (now) => (now === null ? now : { ...now, page: to }))
    return (
      <Box flexDirection="column">
        <Text dimColor>{`#${view.issue} · run_record.py show · page ${page + 1} of ${view.pages.length}`}</Text>
        <Code source={view.pages[page] ?? ''} language="json" />
        {view.pages.length > 1 && (
          <Box key="pages" flexDirection="row" gap={1}>
            {page > 0 && <Button key="prev" label="Prev" onPress={() => turn(page - 1)} />}
            {page < view.pages.length - 1 && <Button key="next" label="Next" onPress={() => turn(page + 1)} />}
          </Box>
        )}
      </Box>
    )
  })
}
