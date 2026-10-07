// The setup pane (issue #165): C3's survey rows with a checkbox each, an
// Install button that runs the ticked tools, and the first-session offer.
//
// The model calls the tool `mcp__saga__setup` with the checkout. The tool runs
// `saga_setup.py survey --format json` and draws the pane from that document
// alone: each tool's id, status, lens and pinned version with a checkbox,
// pre-ticked when the status is not installed. A row with no install command
// has no checkbox and shows the script's install sentence instead. Install
// runs one `install --tools <id>` call per ticked tool, in pane order,
// showing each row's progress, and stops at the first failure; Done returns
// the installed and failed lists to the model. Dismissed, timed-out and the
// error paths match the merge pane: closing records nothing, and a timeout
// returns timed-out with whatever already installed left installed.
//
// The offer: when C3's machine record shows setup has never run — and neither
// the machine record nor the mod's `$.store` remembers the offer — the first
// session start toasts `Run /saga:setup to check this machine's tools.`, then
// records the offer in the machine record through `record-offer` and in the
// store, machine first. The offer check never runs `survey`: the survey
// persists the machine record with `ran` set, so checking with it would mark
// setup run. Any store failure suppresses the offer path without throwing, so
// a suite or build without the store stays silent and green.
//
// Waiting for a person: the tool waits on `$.process.run(['sleep', '1'])`, one
// second at a time, up to WAIT_CAP_SECONDS (LEARNINGS.md, 2026-10-04).

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'
import type { SagaSetupOutcome, SagaSetupSurvey, SagaSetupToolRow } from '../types/index.d.ts'
import {
  readOfferStatusWith,
  readSetupSurveyWith,
  setupInstallArgv,
  setupRecordOfferArgv,
} from './run-record.ts'

/** The pane's id. */
export const PANE = 'saga-setup'

/** The tool's short name; the model calls it as `mcp__saga__setup`. */
export const TOOL = 'setup'

/** How long the tool waits for the operator before it returns timed-out: thirty minutes. */
export const WAIT_CAP_SECONDS = 1800

/** How long one tool install may take. */
const INSTALL_TIMEOUT_MS = 300_000

/** The `$.store` key remembering the setup offer. */
export const OFFER_STORE_KEY = 'setup_offered'

/** The offer toasted once, on the first session of a machine setup never ran on. */
export const OFFER_TEXT = "Run /saga:setup to check this machine's tools."

const setup = atom({ plugin: 'saga', key: 'setupReview' } as const, null)

/**
 * The outcome of the setup in flight. A module value, not `$.state`: the
 * waiting hook reads it between its sleeps, and a state read inside one
 * dispatch sees one frozen moment. A hot reload drops it with the pane.
 */
let outcome: SagaSetupOutcome | undefined

/** Whether a setup pane is open. One setup at a time. */
let active = false

/**
 * The Install run's epoch. Each Install bumps it and orphans any older loop,
 * so a loop outlived by its pane can never mark another setup's rows.
 */
let installEpoch = 0

// ---------------------------------------------------------------------------
// Pure helpers: no `$`, so a test calls them directly
// ---------------------------------------------------------------------------

/** The ticks the pane opens with: every installable row whose status is not installed. */
export function initialTicks(survey: SagaSetupSurvey): Record<string, boolean> {
  const ticked: Record<string, boolean> = {}
  for (const row of survey.tools) {
    ticked[row.id] = row.has_install && row.status !== 'installed'
  }
  return ticked
}

/** The ticked installable ids, in survey order: exactly what Install passes, one argv each. */
export function tickedIds(survey: SagaSetupSurvey, ticked: Record<string, boolean>): string[] {
  return survey.tools.filter((row) => row.has_install && ticked[row.id] === true).map((row) => row.id)
}

/** One row's checkbox label: the tick box, id, status and lens. */
export function rowLabel(row: SagaSetupToolRow, ticked: boolean): string {
  return `${ticked ? '[x]' : '[ ]'} ${row.id}  ${row.status}  ${row.lens}`
}

/** The last lines of a row's install output that the pane shows. */
export function shownOutput(output: string): string {
  return output.length > 2000 ? `\u2026${output.slice(-2000)}` : output
}

// ---------------------------------------------------------------------------
// The hooks
// ---------------------------------------------------------------------------

export function registerSetupPane(on: On): void {
  // The matcher is load-bearing: the engine refuses a second matcher-less
  // `session.start` registration, and admission's holds that one slot.
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    await $.tool.register({
      name: TOOL,
      description:
        "Opens saga's setup pane for a checkout: C3's surveyed tool rows with a checkbox each, and an " +
        'Install button that runs the ticked tools through scripts/saga_setup.py and shows live progress. ' +
        'Returns status submitted (with the installed and failed ids), dismissed, not-placed, unavailable, ' +
        'nothing-to-review, timed-out or error; on anything but submitted, print the survey table and ask ' +
        'which tools to install instead.',
      inputSchema: {
        type: 'object',
        properties: {
          repo: { type: 'string', description: 'The checkout to set up; defaults to the session directory.' },
        },
      },
    })
    const out = await next(e)
    await maybeOfferSetup($)
    return out
  })

  on('tool.call', { tool: 'mcp__saga__setup' }, async ($, e, next) => {
    if (active) {
      return { result: { status: 'error', reason: 'a setup pane is already open' } }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return {
        result: { status: 'unavailable', reason: 'no terminal or desktop surface is attached to draw the pane' },
      }
    }
    const cwd = await $.session.cwd()
    const input = (e as { repo?: unknown }).repo
    const repo = typeof input === 'string' && input !== '' ? input : cwd

    const read = await readSetupSurveyWith((argv) => $.process.run(argv), $.plugin.root, repo)
    if (!read.ok) {
      return { result: { status: 'error', reason: `saga_setup survey failed (${read.reason}): ${read.detail}` } }
    }
    if (read.survey.tools.length === 0) {
      return { result: { status: 'nothing-to-review' } }
    }

    active = true
    outcome = undefined
    await update($, setup, () => ({
      repo,
      survey: read.survey,
      ticked: initialTicks(read.survey),
      progress: null,
      error: null,
    }))
    try {
      const opened = await $.ui.open({ id: PANE, title: 'Setup', focus: true })
      if (!opened.isPlaced) {
        return { result: { status: 'not-placed', reason: opened.reason } }
      }
      let waited = 0
      while (outcome === undefined && !next.signal.aborted && waited < WAIT_CAP_SECONDS) {
        await $.process.run(['sleep', '1'])
        waited += 1
      }
      return { result: outcome ?? { status: next.signal.aborted ? 'dismissed' : 'timed-out' } }
    } catch (err) {
      return { result: { status: 'error', reason: `the setup pane failed: ${String(err)}` } }
    } finally {
      active = false
      outcome = undefined
      installEpoch += 1
      await $.ui.close({ id: PANE })
      await update($, setup, () => null)
    }
  })

  on('ui.close', { id: PANE }, ($, e, next) => {
    // Every close but the tool's own after an outcome: the operator's close mark or Escape.
    if (active && outcome === undefined) outcome = { status: 'dismissed' }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const state = await read($, setup)
    if (e.surface !== 'terminal' && e.surface !== 'desktop') {
      const { Text } = $.ui.resolve(e)
      return <Text>Answer the setup pane in the terminal or the desktop app.</Text>
    }
    const { Box, Button, Text } = $.ui.resolve(e)
    if (state === null) {
      return <Text dimColor>No setup is open.</Text>
    }
    const { repo, survey } = state

    const toggle = (id: string) =>
      update($, setup, (current) => {
        if (!current || current.progress !== null) return current
        const row = current.survey.tools.find((one) => one.id === id)
        if (!row || !row.has_install) return current
        return { ...current, ticked: { ...current.ticked, [id]: current.ticked[id] !== true }, error: null }
      })
    const setError = (error: string) => update($, setup, (current) => current && { ...current, error })
    const markRow = (id: string, progress: { state: 'queued' | 'installing' | 'done' | 'failed'; output: string }) =>
      update($, setup, (current) => {
        if (!current || current.progress === null) return current
        return { ...current, progress: { ...current.progress, [id]: progress } }
      })

    const install = async () => {
      const current = await read($, setup)
      if (!current || current.repo !== repo || current.progress !== null) return
      // Bumped after the guards, so a second press that finds work started
      // returns without orphaning the loop already running.
      const epoch = ++installEpoch
      const ids = tickedIds(current.survey, current.ticked)
      if (ids.length === 0) {
        await setError('Tick at least one tool with an install command.')
        return
      }
      const progress: Record<string, { state: 'queued' | 'installing' | 'done' | 'failed'; output: string }> = {}
      for (const id of ids) progress[id] = { state: 'queued', output: '' }
      await update($, setup, (shown) => (shown ? { ...shown, progress, error: null } : shown))
      for (const id of ids) {
        if (epoch !== installEpoch) return
        await markRow(id, { state: 'installing', output: '' })
        let ran
        try {
          ran = await $.process.run(setupInstallArgv($.plugin.root, id, repo), { timeoutMs: INSTALL_TIMEOUT_MS })
        } catch (err) {
          if (epoch !== installEpoch) return
          await markRow(id, { state: 'failed', output: String(err) })
          return
        }
        if (epoch !== installEpoch) return
        const output = `${ran.stdout}${ran.stderr}`.trim()
        if (ran.exitCode !== 0) {
          await markRow(id, { state: 'failed', output: output === '' ? `install exited ${ran.exitCode}` : output })
          return
        }
        await markRow(id, { state: 'done', output })
      }
    }
    const done = async () => {
      const current = await read($, setup)
      if (!current) return
      const installed: string[] = []
      const failed: string[] = []
      for (const [id, row] of Object.entries(current.progress ?? {})) {
        if (row.state === 'done') installed.push(id)
        else if (row.state === 'failed') failed.push(id)
      }
      outcome = { status: 'submitted', installed, failed }
      await $.ui.close({ id: PANE })
    }
    const dismiss = async () => {
      outcome = { status: 'dismissed' }
      await $.ui.close({ id: PANE })
    }

    const running = state.progress !== null && Object.values(state.progress).some((row) => row.state === 'installing' || row.state === 'queued')
    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        <Text bold>Tools</Text>
        {survey.tools.map((row) => (
          <Box key={`row:${row.id}`} flexDirection="column">
            {row.has_install ? (
              <Button
                key={`tick:${row.id}`}
                label={rowLabel(row, state.ticked[row.id] === true)}
                plain
                onPress={() => toggle(row.id)}
              />
            ) : (
              <Text dimColor>{`${row.id}  ${row.status}  ${row.lens}`}</Text>
            )}
            <Text dimColor>
              {`  ${row.version ?? 'no version'}  pinned ${row.pinned_version}${row.has_install ? '' : `  ${row.install ?? 'no install command'}`}`}
            </Text>
            {state.progress?.[row.id] && (
              <Text key={`progress:${row.id}`} dimColor>
                {`  ${state.progress[row.id]?.state}: ${shownOutput(state.progress[row.id]?.output ?? '')}`}
              </Text>
            )}
          </Box>
        ))}
        {state.error !== null && (
          <Box key="error" marginTop={1}>
            <Text color="red" wrap="wrap">
              {state.error}
            </Text>
          </Box>
        )}
        <Box key="actions" flexDirection="row" columnGap={2} marginTop={1}>
          <Button key="install" label={running ? 'Installing…' : 'Install'} variant="primary" onPress={() => install()} />
          <Button key="done" label="Done" hotkey="d" onPress={() => done()} />
          <Button key="dismiss" label="Dismiss" role="dismiss" onPress={() => dismiss()} />
        </Box>
      </Box>
    )
  })
}

/**
 * Toast the setup offer once, on the first session of a machine setup never
 * ran on. The store is read first: when it remembers the offer the script is
 * never called. Any store failure suppresses the path without throwing.
 */
async function maybeOfferSetup($: EngineInterface): Promise<void> {
  let remembered: unknown
  try {
    remembered = await $.store.get(OFFER_STORE_KEY)
  } catch {
    return
  }
  if (remembered === true) return
  const read = await readOfferStatusWith((argv) => $.process.run(argv), $.plugin.root)
  if (!read.ok) {
    await $.ui.toast(`saga: could not read the machine record (${read.reason}): ${read.detail}`)
    return
  }
  if (read.status.ran || read.status.offered) return
  await $.ui.toast(OFFER_TEXT)
  let recorded
  try {
    recorded = await $.process.run(setupRecordOfferArgv($.plugin.root))
  } catch (err) {
    await $.ui.toast(`saga: could not record the setup offer: ${String(err)}`)
    return
  }
  if (recorded.exitCode !== 0) {
    const stderr = recorded.stderr.trim()
    await $.ui.toast(`saga: could not record the setup offer: ${stderr === '' ? `record-offer exited ${recorded.exitCode}` : stderr}`)
    return
  }
  try {
    await $.store.set(OFFER_STORE_KEY, true)
  } catch {
    // The machine record already remembers; a store that fails just costs one
    // offer-status call next session.
  }
}
