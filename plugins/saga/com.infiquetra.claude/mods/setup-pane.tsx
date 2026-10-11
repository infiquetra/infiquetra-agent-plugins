// The setup pane (issue #165): C3's survey rows with a checkbox each, an
// Install button that runs the ticked tools, the survey's optional steps with
// a Run button each, and the first-session offer.
//
// The model calls the tool `mcp__saga__setup` with the checkout. The tool runs
// `saga_setup.py survey --format json` and draws the pane from that document
// alone: each tool's id, status, lens and pinned version with a checkbox,
// pre-ticked when the status is not installed. A row with no install command
// has no checkbox and shows the script's install sentence instead. Install
// runs one `install --tools <id>` call per ticked tool, in pane order,
// showing each row's progress, and stops at the first failure; a step runs
// one `step --name <name>` call from the saga plugin root with its own progress.
// Done returns the installed and failed lists to the model. Dismissed,
// timed-out and the error paths match the merge pane: closing records
// nothing, and a timeout returns timed-out with whatever already installed
// left installed. Every answer leaves as a JSON string (issue #218): the
// session rejects an object result.
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
//
// The command path (issue #221): `/setup-view`, registered beside the tool,
// opens this same pane with no tool call and no agent turn. One shared open
// helper reads the survey and probes the checkout for both openers; the pane
// state remembers which opener drew it (`openedBy`). The command hook answers
// `{text}` at once and never waits; closing a command-opened pane clears the
// state and leaves no pending tool call, while a tool-opened close still sets
// `dismissed` for the waiting call. After an Install run or a step settles,
// the shared runners re-survey so done states are current, and a failed row
// offers Ask Claude through the session prompt.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'
import type { SagaSetupOutcome, SagaSetupStep, SagaSetupSurvey, SagaSetupToolRow } from '../types/index.d.ts'
import { paneResult } from './pane-result.ts'
import {
  readOfferStatusWith,
  readSetupSurveyWith,
  setupInstallArgv,
  setupRecordOfferArgv,
  setupScriptExistsWith,
  setupStepArgv,
} from './run-record.ts'

/** The pane's id. */
export const PANE = 'saga-setup'

/** The tool's short name; the model calls it as `mcp__saga__setup`. */
export const TOOL = 'setup'

/** The setup command's name; the operator runs it as `/setup-view` (issue #221). */
export const COMMAND = 'setup-view'

/** The survey a command-opened pane carries when the survey failed: drawn never, read never. */
const EMPTY_SURVEY: SagaSetupSurvey = { schema: 'setup_survey.v1', tools: [], steps: [] }

/** How long the tool waits for the operator before it returns timed-out: thirty minutes. */
export const WAIT_CAP_SECONDS = 1800

/** How long one tool install may take. */
const INSTALL_TIMEOUT_MS = 300_000

/** How long one step run may take: past the script's own 30-second child timeout. */
const STEP_TIMEOUT_MS = 60_000

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
 * Which opener drew the active setup, set beside `active` so the close handler
 * reads it with no await. The pane state carries the same answer for the render.
 */
let activeOpener: 'tool' | 'command' | null = null

/**
 * The Install run's epoch. Each Install bumps it and orphans any older loop,
 * so a loop outlived by its pane can never mark another setup's rows.
 */
let installEpoch = 0

/**
 * The step runs' epoch, Install's for steps: bumped when the tool call ends,
 * so a run outlived by its pane can never mark another setup's steps.
 */
let stepEpoch = 0

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

/** The survey's optional steps: a missing or non-array field reads as none. */
export function surveySteps(survey: SagaSetupSurvey): SagaSetupStep[] {
  return Array.isArray(survey.steps) ? survey.steps : []
}

/** The last lines of a row's install output that the pane shows. */
export function shownOutput(output: string): string {
  return output.length > 2000 ? `\u2026${output.slice(-2000)}` : output
}

// ---------------------------------------------------------------------------
// Shared open: one survey read and checkout probe for both openers (issue #221)
// ---------------------------------------------------------------------------

/** What the shared open read: the survey and the step checkout, or why there is no pane. */
type SetupOpen =
  | { ok: true; survey: SagaSetupSurvey; checkout: string | null }
  | { ok: false; reason: string; empty: boolean }

/**
 * Read the survey and probe the step checkout for `repo`. Both the tool call
 * and the setup-view command open through this alone, so the survey
 * implementation is one function and its failure words are one string.
 */
async function prepareSetup($: EngineInterface, repo: string): Promise<SetupOpen> {
  const read = await readSetupSurveyWith((argv) => $.process.run(argv), $.plugin.root, repo)
  if (!read.ok) {
    return { ok: false, reason: `saga_setup survey failed (${read.reason}): ${read.detail}`, empty: false }
  }
  if (read.survey.tools.length === 0 && surveySteps(read.survey).length === 0) {
    return { ok: false, reason: 'the survey lists no tools and no steps', empty: true }
  }
  const runnable = await setupScriptExistsWith((path) => $.fs.exists(path), $.plugin.root)
  return { ok: true, survey: read.survey, checkout: runnable ? $.plugin.root : null }
}

/**
 * Clear a command-opened setup: no call waits on it, so `active`, the epochs
 * and the state go now. The tool path never calls this; its `finally` owns
 * that cleanup.
 */
async function clearCommandSetup($: EngineInterface): Promise<void> {
  active = false
  activeOpener = null
  installEpoch += 1
  stepEpoch += 1
  await update($, setup, () => null)
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
    await $.command.register({
      name: COMMAND,
      description: "Open the setup pane: survey this checkout's tools, install them, and run the optional steps",
      immediate: true,
    })
    const out = await next(e)
    await maybeOfferSetup($)
    return out
  })

  on('tool.call', { tool: 'mcp__saga__setup' }, async ($, e, next) => {
    if (active) {
      return { result: paneResult({ status: 'error', reason: 'a setup pane is already open' }) }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return {
        result: paneResult({ status: 'unavailable', reason: 'no terminal or desktop surface is attached to draw the pane' }),
      }
    }
    const cwd = await $.session.cwd()
    const input = (e as { repo?: unknown }).repo
    const repo = typeof input === 'string' && input !== '' ? input : cwd

    const prepared = await prepareSetup($, repo)
    if (!prepared.ok && prepared.empty) {
      return { result: paneResult({ status: 'nothing-to-review' }) }
    }
    if (!prepared.ok) {
      return { result: paneResult({ status: 'error', reason: prepared.reason }) }
    }

    active = true
    activeOpener = 'tool'
    outcome = undefined
    await update($, setup, () => ({
      repo,
      survey: prepared.survey,
      ticked: initialTicks(prepared.survey),
      progress: null,
      checkout: prepared.checkout,
      stepProgress: {},
      error: null,
      openedBy: 'tool',
      surveyError: null,
    }))
    try {
      const opened = await $.ui.open({ id: PANE, title: 'Setup', focus: true })
      if (!opened.isPlaced) {
        return { result: paneResult({ status: 'not-placed', reason: opened.reason }) }
      }
      let waited = 0
      while (outcome === undefined && !next.signal.aborted && waited < WAIT_CAP_SECONDS) {
        await $.process.run(['sleep', '1'])
        waited += 1
      }
      return { result: paneResult(outcome ?? { status: next.signal.aborted ? 'dismissed' : 'timed-out' }) }
    } catch (err) {
      return { result: paneResult({ status: 'error', reason: `the setup pane failed: ${String(err)}` }) }
    } finally {
      active = false
      activeOpener = null
      outcome = undefined
      installEpoch += 1
      stepEpoch += 1
      await $.ui.close({ id: PANE })
      await update($, setup, () => null)
    }
  })

  on('command.run', { command: 'setup-view' }, async ($, e) => {
    if (active) {
      return { text: 'setup-view: a setup pane is already open' }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return { text: 'setup-view: no terminal or desktop surface is attached to draw the pane' }
    }
    const repo = await $.session.cwd()
    const prepared = await prepareSetup($, repo)
    if (!prepared.ok && prepared.empty) {
      return { text: `setup-view: nothing to set up: ${prepared.reason}.` }
    }
    active = true
    activeOpener = 'command'
    outcome = undefined
    let openedPane = false
    try {
      if (!prepared.ok) {
        await update($, setup, () => ({
          repo,
          survey: EMPTY_SURVEY,
          ticked: {},
          progress: null,
          checkout: null,
          stepProgress: {},
          error: null,
          openedBy: 'command',
          surveyError: prepared.reason,
        }))
      } else {
        await update($, setup, () => ({
          repo,
          survey: prepared.survey,
          ticked: initialTicks(prepared.survey),
          progress: null,
          checkout: prepared.checkout,
          stepProgress: {},
          error: null,
          openedBy: 'command',
          surveyError: null,
        }))
      }
      const opened = await $.ui.open({ id: PANE, title: 'Setup', focus: true })
      if (!opened.isPlaced) {
        await $.ui.close({ id: PANE })
        return { text: `setup-view: the pane could not be placed: ${opened.reason}` }
      }
      openedPane = true
      if (!prepared.ok) {
        return { text: `setup-view: the survey failed: ${prepared.reason}` }
      }
      return {
        text: `setup-view: ${prepared.survey.tools.length} tools, ${surveySteps(prepared.survey).length} steps.`,
      }
    } catch (err) {
      return { text: `setup-view: the setup pane failed: ${String(err)}` }
    } finally {
      if (!openedPane) await clearCommandSetup($)
    }
  })

  on('ui.close', { id: PANE }, async ($, e, next) => {
    // Every close but the tool's own after an outcome: the operator's close mark or Escape.
    // A tool-opened close answers the waiting call; a command-opened close clears the
    // state, since no call waits on it. The tool call's own `finally` clears first.
    // The command branch clears synchronously, before the first await, so no later
    // opener answers "already open" for a pane that is already gone.
    if (active && outcome === undefined) {
      if (activeOpener === 'command') {
        active = false
        activeOpener = null
        installEpoch += 1
        stepEpoch += 1
        await update($, setup, () => null)
      } else {
        outcome = { status: 'dismissed' }
      }
    }
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
    const markStep = (name: string, progress: { state: 'running' | 'done' | 'failed'; output: string }) =>
      update($, setup, (current) => {
        if (!current) return current
        return { ...current, stepProgress: { ...current.stepProgress, [name]: progress } }
      })

    /**
     * Re-read the survey after an action, keeping the operator's ticks for surviving rows.
     * `stillCurrent` is the caller's epoch check, run again after the read: a close and a
     * reopen of the same checkout landing mid-read must not write into the new pane.
     */
    const refreshSurvey = async (stillCurrent: () => boolean) => {
      const before = await read($, setup)
      if (!before || before.repo !== repo) return
      const reread = await readSetupSurveyWith((argv) => $.process.run(argv), $.plugin.root, before.repo)
      if (!stillCurrent()) return
      const current = await read($, setup)
      if (!current || current.repo !== repo) return
      if (!reread.ok) {
        $.ui.toast(`setup-view: the survey refresh failed (${reread.reason}): ${reread.detail}`)
        return
      }
      await update($, setup, (shown) => {
        if (!shown || shown.repo !== repo) return shown
        const ticked: Record<string, boolean> = {}
        for (const row of reread.survey.tools) {
          ticked[row.id] = shown.ticked[row.id] ?? (row.has_install && row.status !== 'installed')
        }
        return { ...shown, survey: reread.survey, ticked }
      })
    }

    /** Hand a failed row to the session prompt: the row, the command as run, and the output tail. */
    const askClaude = async (id: string, command: string, output: string) => {
      const filled = await $.prompt.fill({ text: `setup ${id} failed: ${command}\n${shownOutput(output)}`, mode: 'insert' })
      if (!filled.isFilled) $.ui.toast('setup-view: the prompt cannot take text right now')
    }

    /** Close a command-opened pane: nothing waits on it, so the state goes with it. */
    const closePane = async () => {
      await clearCommandSetup($)
      await $.ui.close({ id: PANE })
    }

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
          if (epoch === installEpoch) await refreshSurvey(() => epoch === installEpoch)
          return
        }
        if (epoch !== installEpoch) return
        const output = `${ran.stdout}${ran.stderr}`.trim()
        if (ran.exitCode !== 0) {
          await markRow(id, { state: 'failed', output: output === '' ? `install exited ${ran.exitCode}` : output })
          if (epoch === installEpoch) await refreshSurvey(() => epoch === installEpoch)
          return
        }
        await markRow(id, { state: 'done', output })
      }
      if (epoch === installEpoch) await refreshSurvey(() => epoch === installEpoch)
    }
    const runStep = async (name: string) => {
      const current = await read($, setup)
      if (!current || current.repo !== repo || current.checkout === null) return
      if (!surveySteps(current.survey).some((step) => step.name === name)) return
      if (current.stepProgress[name]?.state === 'running') return
      const epoch = stepEpoch
      const cwd = current.checkout
      await markStep(name, { state: 'running', output: '' })
      let ran
      try {
        ran = await $.process.run(setupStepArgv($.plugin.root, name), { cwd, timeoutMs: STEP_TIMEOUT_MS })
      } catch (err) {
        if (epoch !== stepEpoch) return
        await markStep(name, { state: 'failed', output: String(err) })
        if (epoch === stepEpoch) await refreshSurvey(() => epoch === stepEpoch)
        return
      }
      if (epoch !== stepEpoch) return
      const output = `${ran.stdout}${ran.stderr}`.trim()
      if (ran.exitCode !== 0) {
        await markStep(name, { state: 'failed', output: output === '' ? `step exited ${ran.exitCode}` : output })
        if (epoch === stepEpoch) await refreshSurvey(() => epoch === stepEpoch)
        return
      }
      await markStep(name, { state: 'done', output })
      if (epoch === stepEpoch) await refreshSurvey(() => epoch === stepEpoch)
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

    if (state.surveyError !== null) {
      return (
        <Box flexDirection="column" width={e.props.bodyColumns}>
          <Text>The setup survey failed.</Text>
          <Text dimColor>{shownOutput(state.surveyError)}</Text>
          <Box key="actions" flexDirection="row" columnGap={2} marginTop={1}>
            <Button key="close" label="Close" onPress={() => closePane()} />
          </Box>
        </Box>
      )
    }

    const running = state.progress !== null && Object.values(state.progress).some((row) => row.state === 'installing' || row.state === 'queued')
    const installable = survey.tools.some((row) => row.has_install)
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
            {state.progress?.[row.id]?.state === 'failed' && (
              <Button
                key={`ask:${row.id}`}
                label="Ask Claude"
                plain
                onPress={async () => {
                  const current = await read($, setup)
                  await askClaude(row.id, setupInstallArgv($.plugin.root, row.id, repo).join(' '), current?.progress?.[row.id]?.output ?? '')
                }}
              />
            )}
          </Box>
        ))}
        {surveySteps(survey).length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Steps</Text>
            {surveySteps(survey).map((step) => (
              <Box key={`step:${step.name}`} flexDirection="column">
                <Text>{`${step.name}: ${step.done ? 'done' : 'not done'} — ${step.summary}`}</Text>
                {state.checkout !== null ? (
                  <Button key={`run-step:${step.name}`} label={`Run ${step.name}`} plain onPress={() => runStep(step.name)} />
                ) : (
                  <Text dimColor>Steps run only from a saga checkout.</Text>
                )}
                {state.stepProgress[step.name] && (
                  <Text key={`step-progress:${step.name}`} dimColor>
                    {`  ${state.stepProgress[step.name]?.state}: ${shownOutput(state.stepProgress[step.name]?.output ?? '')}`}
                  </Text>
                )}
                {state.stepProgress[step.name]?.state === 'failed' && (
                  <Button
                    key={`ask-step:${step.name}`}
                    label="Ask Claude"
                    plain
                    onPress={async () => {
                      const current = await read($, setup)
                      await askClaude(step.name, setupStepArgv($.plugin.root, step.name).join(' '), current?.stepProgress[step.name]?.output ?? '')
                    }}
                  />
                )}
              </Box>
            ))}
          </Box>
        )}
        <Box key="questions" marginTop={1}>
          <Text dimColor>The repository questions live in /saga:setup.</Text>
        </Box>
        {!installable && (
          <Box key="no-install" marginTop={1}>
            <Text wrap="wrap">Nothing here installs: no row has an install command.</Text>
          </Box>
        )}
        {state.error !== null && (
          <Box key="error" marginTop={1}>
            <Text color="red" wrap="wrap">
              {state.error}
            </Text>
          </Box>
        )}
        <Box key="actions" flexDirection="row" columnGap={2} marginTop={1}>
          {installable && (
            <Button key="install" label={running ? 'Installing…' : 'Install'} variant="primary" onPress={() => install()} />
          )}
          {state.openedBy === 'command' ? (
            <Button key="close" label="Close" onPress={() => closePane()} />
          ) : (
            <Button key="done" label="Done" hotkey="d" onPress={() => done()} />
          )}
          {state.openedBy === 'tool' && installable && <Button key="dismiss" label="Dismiss" role="dismiss" onPress={() => dismiss()} />}
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
