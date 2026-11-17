// The admission review pane: staffing tiers, one control per role.
// Admission owns validation and records only the staffing answer.
//
// The model calls the tool `mcp__saga__review_admission` with an issue number.
// The tool runs `scripts/admission.py --dry-run --render json`, draws the pane
// from that document alone (schema `admission_review.v1`), and waits for the
// operator. Submit hands the answers to `admission.py --answers -` on standard
// input, so the script validates and records them; the tool then returns them
// to the model as its result. Closing the pane returns `dismissed`, and the plan
// skill prints admission's fixed tables instead.
//
// The mod decides nothing. Every choice a Select offers comes from the palette
// the script printed, never a list written here; the script is the one place an
// answer is checked, and a refusal it prints is shown in the pane as printed.
//
// Waiting for a person: a hook's own time is capped at ten seconds per
// dispatch, and the clock stops only while a `$` call is in flight. Awaiting a
// bare Promise therefore fails the hook at ten seconds; the tool waits on
// `$.process.run(['sleep', '1'])` instead, one second at a time, up to
// WAIT_CAP_SECONDS (LEARNINGS.md, 2026-10-04).

import { atom, read, update } from 'claude-code'
import type { On, ProcessRunResult } from 'claude-code'
import type {
  SagaAdmissionAnswers,
  SagaAdmissionPalette,
  SagaAdmissionReviewData,
  SagaAdmissionReviewOutcome,
  SagaAdmissionSelections,
  SagaAdmissionTier,
} from '../types/index.d.ts'
import { paneResult } from './pane-result.ts'
import { sagaScriptArgv } from './run-record.ts'

/** The pane's id. */
export const PANE = 'saga-admission'

/** The tool's short name; the model calls it as `mcp__saga__review_admission`. */
export const TOOL = 'review_admission'

/** The review document version this module reads; `REVIEW_SCHEMA` in `scripts/admission.py`. */
export const REVIEW_SCHEMA = 'admission_review.v1'

/** The staffing question the pane answers; otherwise there is nothing to review. */
export const REVIEWED_QUESTIONS = ['staffing_overrides'] as const

/** How long the tool waits for the operator before it returns `timed-out`: thirty minutes. */
export const WAIT_CAP_SECONDS = 1800

/** How long one admission run may take; it reads the issue with `gh`. */
const ADMISSION_TIMEOUT_MS = 120_000

const review = atom({ plugin: 'saga', key: 'admissionReview' } as const, null)

/**
 * The outcome of the review in flight, by issue. A module value, not `$.state`:
 * the waiting hook reads it between its sleeps, and a state read inside one
 * dispatch sees one frozen moment. A hot reload drops it with the pane.
 */
const outcomes = new Map<number, SagaAdmissionReviewOutcome>()

/** The issue whose review is open, or null. One review at a time. */
let active: number | null = null

// ---------------------------------------------------------------------------
// Pure helpers: no `$`, so a test calls them directly
// ---------------------------------------------------------------------------

/** The argv that prints the review document for an issue without writing the record. */
export function reviewArgv(pluginRoot: string, issue: number, repo: string | null): string[] {
  return sagaScriptArgv(pluginRoot, 'admission.py', [
    '--issue',
    String(issue),
    ...(repo ? ['--repo', repo] : []),
    '--dry-run',
    '--render',
    'json',
  ])
}

/** The argv that records the answers read from standard input. */
export function answersArgv(pluginRoot: string, issue: number, repo: string | null): string[] {
  return sagaScriptArgv(pluginRoot, 'admission.py', [
    '--issue',
    String(issue),
    ...(repo ? ['--repo', repo] : []),
    '--answers',
    '-',
  ])
}

type Ran = Pick<ProcessRunResult, 'exitCode' | 'stdout' | 'stderr' | 'isStdoutTruncated'>

/** Turn what `admission.py --render json` did into the review document, or why there is none. */
export function parseReview(
  ran: Ran,
): { ok: true; data: SagaAdmissionReviewData } | { ok: false; reason: string; exitCode?: number; stderr?: string } {
  const stderr = ran.stderr.trim()
  if (ran.exitCode !== 0) {
    return { ok: false, reason: `admission.py exited ${ran.exitCode}`, exitCode: ran.exitCode, stderr }
  }
  if (ran.isStdoutTruncated) {
    return { ok: false, reason: 'admission.py printed more than the engine keeps (4 MiB); the review was cut off' }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch (err) {
    return { ok: false, reason: `admission.py did not print JSON: ${String(err)}` }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, reason: 'admission.py did not print a JSON object' }
  }
  const schema = (parsed as { schema?: unknown }).schema
  if (schema !== REVIEW_SCHEMA) {
    return { ok: false, reason: `review version ${JSON.stringify(schema)} is not ${REVIEW_SCHEMA}` }
  }
  return { ok: true, data: parsed as SagaAdmissionReviewData }
}

/** The efforts the palette allows for one model, in palette order. */
export function effortsFor(palette: SagaAdmissionPalette, model: string): string[] {
  return palette.pairs.filter((pair) => pair.model === model).map((pair) => pair.effort)
}

/** A tier the palette allows: the effort kept when the model takes it, else the model's ceiling. */
export function clampTier(palette: SagaAdmissionPalette, model: string, effort: string | null): { model: string; effort: string } {
  const allowed = effortsFor(palette, model)
  if (effort !== null && allowed.includes(effort)) return { model, effort }
  const ceiling = palette.effort_ceilings[model]
  if (ceiling !== undefined && allowed.includes(ceiling)) return { model, effort: ceiling }
  return { model, effort: allowed[allowed.length - 1] ?? '' }
}

function pickFrom(palette: SagaAdmissionPalette, tier: SagaAdmissionTier | null): { model: string; effort: string } {
  if (tier && palette.models.includes(tier.model)) return clampTier(palette, tier.model, tier.effort)
  const first = palette.pairs[0]
  return first ? { model: first.model, effort: first.effort } : { model: '', effort: '' }
}

/** The proposed tier for each role when the pane opens. */
export function initialSelections(data: SagaAdmissionReviewData): SagaAdmissionSelections {
  const palette = data.palette
  const staffing: SagaAdmissionSelections['staffing'] = {}
  if (palette) {
    for (const row of data.staffing.rows) staffing[row.role] = pickFrom(palette, row.proposed ?? row.default)
  }
  return { staffing }
}

/** Accept every role's proposed tier. */
export function acceptAllSelections(
  data: SagaAdmissionReviewData,
  _current: SagaAdmissionSelections,
): SagaAdmissionSelections {
  return initialSelections(data)
}

/** Record the complete staffing map, with no other admission decisions. */
export function buildAnswers(data: SagaAdmissionReviewData, selections: SagaAdmissionSelections): SagaAdmissionAnswers {
  const vendor = data.palette?.vendor ?? ''
  const staffing_overrides: SagaAdmissionAnswers['staffing_overrides'] = {}
  for (const row of data.staffing.rows) {
    const pick = selections.staffing[row.role]
    if (!pick) continue
    staffing_overrides[row.role] = {
      vendor: row.vendor ?? row.proposed?.vendor ?? row.default?.vendor ?? vendor,
      model: pick.model,
      effort: pick.effort,
    }
  }
  return { staffing_overrides }
}

function tierText(tier: SagaAdmissionTier | null): string {
  if (!tier) return 'not configured'
  return `${tier.vendor ? `${tier.vendor} ` : ''}${tier.model}/${tier.effort ?? 'default'}`
}

function issueOf(input: unknown): number | null {
  const issue = (input as { issue?: unknown }).issue
  return typeof issue === 'number' && Number.isInteger(issue) && issue > 0 ? issue : null
}

function repoOf(input: unknown): string | null {
  const repo = (input as { repo?: unknown }).repo
  return typeof repo === 'string' && /^[\w.-]+\/[\w.-]+$/.test(repo) ? repo : null
}

// ---------------------------------------------------------------------------
// The hooks
// ---------------------------------------------------------------------------

export function registerAdmissionReview(on: On): void {
  on('session.start', async ($, e, next) => {
    await $.tool.register({
      name: TOOL,
      description:
        "Opens saga's admission review pane for an issue: the staffing table, with a model and " +
        "effort control per role. Answers are recorded through scripts/admission.py, which " +
        'validates them. Returns status submitted (with the answers recorded), dismissed, ' +
        'not-placed, unavailable, nothing-to-review, timed-out or error; on anything but ' +
        'submitted, print admission.py --render tables and collect the answers in the conversation.',
      inputSchema: {
        type: 'object',
        properties: {
          issue: { type: 'integer', minimum: 1, description: 'The issue number admission runs for.' },
          repo: { type: 'string', description: 'owner/name; defaults to the origin remote.' },
        },
        required: ['issue'],
      },
    })
    return next(e)
  })

  on('tool.call', { tool: 'mcp__saga__review_admission' }, async ($, e, next) => {
    const issue = issueOf(e)
    const repo = repoOf(e)
    if (issue === null) {
      return { result: paneResult({ status: 'error', reason: 'issue must be a positive whole number' }) }
    }
    if (active !== null) {
      return { result: paneResult({ status: 'error', reason: `the review pane is already open for issue ${active}` }) }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return {
        result: paneResult({ status: 'unavailable', reason: 'no terminal or desktop surface is attached to draw the pane' }),
      }
    }

    let ran: ProcessRunResult
    try {
      ran = await $.process.run(reviewArgv($.plugin.root, issue, repo), { timeoutMs: ADMISSION_TIMEOUT_MS })
    } catch (err) {
      return { result: paneResult({ status: 'error', reason: `admission.py did not run: ${String(err)}` }) }
    }
    const parsed = parseReview(ran)
    if (!parsed.ok) {
      const { ok: _ok, ...failure } = parsed
      return { result: paneResult({ status: 'error', ...failure }) }
    }
    const data = parsed.data
    if (!REVIEWED_QUESTIONS.some((question) => data.pending_questions.includes(question))) {
      return { result: paneResult({ status: 'nothing-to-review' }) }
    }
    if (data.palette === null) {
      return { result: paneResult({ status: 'error', reason: 'admission could not load the tier palette' }) }
    }
    if (data.staffing.rows.length === 0) {
      return { result: paneResult({ status: 'error', reason: 'admission could not reach the staffing component' }) }
    }

    active = issue
    outcomes.delete(issue)
    await update($, review, () => ({ issue, repo, data, selections: initialSelections(data), error: null }))
    let outcome: SagaAdmissionReviewOutcome | undefined
    try {
      const opened = await $.ui.open({ id: PANE, title: `Admission #${issue}: staffing`, focus: true })
      if (!opened.isPlaced) {
        return { result: paneResult({ status: 'not-placed', reason: opened.reason }) }
      }
      let waited = 0
      while (!outcomes.has(issue) && !next.signal.aborted && waited < WAIT_CAP_SECONDS) {
        await $.process.run(['sleep', '1'])
        waited += 1
      }
      outcome = outcomes.get(issue)
      return { result: paneResult(outcome ?? { status: next.signal.aborted ? 'dismissed' : 'timed-out' }) }
    } catch (err) {
      return { result: paneResult({ status: 'error', reason: `the review pane failed: ${String(err)}` }) }
    } finally {
      active = null
      outcomes.delete(issue)
      await $.ui.close({ id: PANE })
      await update($, review, () => null)
    }
  })

  on('ui.close', { id: PANE }, ($, e, next) => {
    // Every close but the tool's own after an outcome: the operator's close mark or Escape.
    if (active !== null && !outcomes.has(active)) outcomes.set(active, { status: 'dismissed' })
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const state = await read($, review)
    if (e.surface !== 'terminal' && e.surface !== 'desktop') {
      const { Text } = $.ui.resolve(e)
      return <Text>Answer the admission review in the terminal or the desktop app.</Text>
    }
    const { Box, Button, Select, Text } = $.ui.resolve(e)
    if (state === null || state.data.palette === null) {
      return <Text dimColor>No admission review is open.</Text>
    }
    const { data, selections } = state
    const palette = state.data.palette
    const issue = state.issue

    const pickModel = (role: string, model: string) =>
      update($, review, (current) => {
        if (!current || !palette.models.includes(model)) return current
        const effort = current.selections.staffing[role]?.effort ?? null
        const staffing = { ...current.selections.staffing, [role]: clampTier(palette, model, effort) }
        return { ...current, selections: { ...current.selections, staffing }, error: null }
      })
    const pickEffort = (role: string, effort: string) =>
      update($, review, (current) => {
        const pick = current?.selections.staffing[role]
        if (!current || !pick || !effortsFor(palette, pick.model).includes(effort)) return current
        const staffing = { ...current.selections.staffing, [role]: { model: pick.model, effort } }
        return { ...current, selections: { ...current.selections, staffing }, error: null }
      })
    const setError = (error: string) => update($, review, (current) => current && { ...current, error })

    const submit = async (acceptAll: boolean) => {
      const current = await read($, review)
      if (!current || current.issue !== issue) return
      const picks = acceptAll ? acceptAllSelections(current.data, current.selections) : current.selections
      if (acceptAll) await update($, review, (now) => now && { ...now, selections: picks })
      const answers = buildAnswers(current.data, picks)
      let ran: ProcessRunResult
      try {
        ran = await $.process.run(answersArgv($.plugin.root, issue, current.repo), {
          stdin: JSON.stringify(answers),
          timeoutMs: ADMISSION_TIMEOUT_MS,
        })
      } catch (err) {
        await setError(`admission.py did not run: ${String(err)}`)
        return
      }
      if (ran.exitCode !== 0) {
        await setError(ran.stderr.trim() || `admission.py exited ${ran.exitCode}`)
        return
      }
      outcomes.set(issue, { status: 'submitted', issue, answers, source: 'operator', summary: ran.stdout.trim() })
      await $.ui.close({ id: PANE })
    }
    const dismiss = async () => {
      outcomes.set(issue, { status: 'dismissed' })
      await $.ui.close({ id: PANE })
    }

    const modelOptions = palette.models.map((value) => ({ value }))

    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        <Text bold>Staffing (answer: staffing_overrides)</Text>
        {data.staffing.rows.map((row) => {
          const pick = selections.staffing[row.role] ?? { model: '', effort: '' }
          return (
            <Box flexDirection="column" marginTop={1}>
              <Text>
                <Text bold>{row.role}</Text> default {tierText(row.default)}, proposed {tierText(row.proposed)}
              </Text>
              <Box key={`staff:${row.role}:jev`}>
                <Text>Jev: {row.jev.cell}</Text>
              </Box>
              <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
                <Select
                  key={`staff:${row.role}:model`}
                  label="model "
                  options={modelOptions}
                  value={pick.model}
                  onSelect={(value) => pickModel(row.role, value)}
                />
                <Select
                  key={`staff:${row.role}:effort`}
                  label="effort "
                  options={effortsFor(palette, pick.model).map((value) => ({ value }))}
                  value={pick.effort}
                  onSelect={(value) => pickEffort(row.role, value)}
                />
              </Box>
              <Text dimColor wrap="wrap">
                {row.why}
              </Text>
            </Box>
          )
        })}
        {state.error !== null && (
          <Box key="error" marginTop={1}>
            <Text color="red" wrap="wrap">
              {state.error}
            </Text>
          </Box>
        )}
        <Box flexDirection="row" columnGap={2} marginTop={1}>
          <Button key="accept-all" label="Accept all" hotkey="a" onPress={() => submit(true)} />
          <Button key="submit" label="Submit" hotkey="s" variant="primary" onPress={() => submit(false)} />
          <Button key="dismiss" label="Dismiss" hotkey="d" role="dismiss" onPress={dismiss} />
        </Box>
      </Box>
    )
  })
}
