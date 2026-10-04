// The admission review pane (issue #103): admission's staffing answer
// (question 4, `staffing_overrides`) and lens answer (question 5,
// `lens_declaration`) as two tables with a control per row.
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
import { sagaScriptArgv } from './run-record.ts'

/** The pane's id. */
export const PANE = 'saga-admission'

/** The tool's short name; the model calls it as `mcp__saga__review_admission`. */
export const TOOL = 'review_admission'

/** The review document version this module reads; `REVIEW_SCHEMA` in `scripts/admission.py`. */
export const REVIEW_SCHEMA = 'admission_review.v1'

/** The two questions the pane answers. With neither outstanding there is nothing to review. */
export const REVIEWED_QUESTIONS = ['staffing_overrides', 'lens_declaration'] as const

/** How long the tool waits for the operator before it returns `timed-out`: thirty minutes. */
export const WAIT_CAP_SECONDS = 1800

/** How long one admission run may take; it reads the issue with `gh`. */
const ADMISSION_TIMEOUT_MS = 120_000

/** The two decisions a conditional lens takes. */
const INCLUDE_CHOICES = ['yes', 'no'] as const

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

/**
 * The picks the pane opens with: each role's
 * proposed tier, and each conditional lens as declared; an undeclared lens is
 * included when Jev pre-checked it (issue #110) and left out, with no reason
 * yet, otherwise.
 */
export function initialSelections(data: SagaAdmissionReviewData): SagaAdmissionSelections {
  const palette = data.palette
  const staffing: SagaAdmissionSelections['staffing'] = {}
  if (palette) {
    for (const row of data.staffing.rows) staffing[row.role] = pickFrom(palette, row.proposed ?? row.default)
  }
  const lenses: SagaAdmissionSelections['lenses'] = {}
  for (const row of data.lenses.rows) {
    if (row.always_on) continue
    if (row.include === 'yes' || row.include === 'no') {
      lenses[row.lens] = { include: row.include, reason: row.reason }
    } else {
      lenses[row.lens] = { include: row.jev.band === 'pre-checked' ? 'yes' : 'no', reason: '' }
    }
  }
  return { staffing, lenses }
}

/**
 * The picks "Accept all" submits: every proposal that exists, applied over the
 * operator's current picks. Each role takes its proposed tier, and each lens
 * that is declared or that Jev pre-checked takes that answer; a lens with no
 * proposal keeps the operator's own include choice and reason.
 */
export function acceptAllSelections(
  data: SagaAdmissionReviewData,
  current: SagaAdmissionSelections,
): SagaAdmissionSelections {
  const proposed = initialSelections(data)
  const lenses: SagaAdmissionSelections['lenses'] = { ...proposed.lenses }
  for (const row of data.lenses.rows) {
    if (row.always_on) continue
    const hasProposal = row.include === 'yes' || row.include === 'no' || row.jev.band === 'pre-checked'
    const own = current.lenses[row.lens]
    if (!hasProposal && own) lenses[row.lens] = own
  }
  return { staffing: proposed.staffing, lenses }
}

/** The conditional lenses left out with no reason yet, in table order. */
export function unexplainedExclusions(selections: SagaAdmissionSelections): string[] {
  return Object.entries(selections.lenses)
    .filter(([, pick]) => pick.include === 'no' && pick.reason.trim() === '')
    .map(([lens]) => lens)
}

/**
 * The answers to record: the complete role map, so every role's source becomes
 * the operator, and the lens declaration in the shape the review reads.
 */
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
  const conditional_applies: Record<string, string> = {}
  const conditional_does_not_apply: Record<string, string> = {}
  for (const row of data.lenses.rows) {
    const pick = selections.lenses[row.lens]
    if (row.always_on || !pick) continue
    if (pick.include === 'yes') conditional_applies[row.lens] = pick.reason.trim()
    else conditional_does_not_apply[row.lens] = pick.reason.trim()
  }
  return {
    staffing_overrides,
    lens_declaration: {
      always_on: data.lenses.rows.filter((row) => row.always_on).map((row) => row.lens),
      conditional_applies,
      conditional_does_not_apply,
    },
  }
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
        "Opens saga's admission review pane for an issue: the staffing table (admission question 4, " +
        'staffing_overrides) and the lens table (question 5, lens_declaration), each row with its ' +
        "own control. The operator's answers are recorded through scripts/admission.py, which " +
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
      return { result: { status: 'error', reason: 'issue must be a positive whole number' } }
    }
    if (active !== null) {
      return { result: { status: 'error', reason: `the review pane is already open for issue ${active}` } }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return {
        result: { status: 'unavailable', reason: 'no terminal or desktop surface is attached to draw the pane' },
      }
    }

    let ran: ProcessRunResult
    try {
      ran = await $.process.run(reviewArgv($.plugin.root, issue, repo), { timeoutMs: ADMISSION_TIMEOUT_MS })
    } catch (err) {
      return { result: { status: 'error', reason: `admission.py did not run: ${String(err)}` } }
    }
    const parsed = parseReview(ran)
    if (!parsed.ok) {
      const { ok: _ok, ...failure } = parsed
      return { result: { status: 'error', ...failure } }
    }
    const data = parsed.data
    if (!REVIEWED_QUESTIONS.some((question) => data.pending_questions.includes(question))) {
      return { result: { status: 'nothing-to-review' } }
    }
    if (data.palette === null) {
      return { result: { status: 'error', reason: 'admission could not load the tier palette' } }
    }
    if (data.staffing.rows.length === 0) {
      return { result: { status: 'error', reason: 'admission could not reach the staffing component' } }
    }

    active = issue
    outcomes.delete(issue)
    await update($, review, () => ({ issue, repo, data, selections: initialSelections(data), error: null }))
    let outcome: SagaAdmissionReviewOutcome | undefined
    try {
      const opened = await $.ui.open({ id: PANE, title: `Admission #${issue}: staffing and lenses`, focus: true })
      if (!opened.isPlaced) {
        return { result: { status: 'not-placed', reason: opened.reason } }
      }
      let waited = 0
      while (!outcomes.has(issue) && !next.signal.aborted && waited < WAIT_CAP_SECONDS) {
        await $.process.run(['sleep', '1'])
        waited += 1
      }
      outcome = outcomes.get(issue)
      return { result: outcome ?? { status: next.signal.aborted ? 'dismissed' : 'timed-out' } }
    } catch (err) {
      return { result: { status: 'error', reason: `the review pane failed: ${String(err)}` } }
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
    const { Box, Button, Input, Select, Text } = $.ui.resolve(e)
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
    const setLens = (lens: string, change: { include?: string; reason?: string }) =>
      update($, review, (current) => {
        const pick = current?.selections.lenses[lens]
        if (!current || !pick) return current
        const include = change.include ?? pick.include
        if (include !== 'yes' && include !== 'no') return current
        const lenses = { ...current.selections.lenses, [lens]: { include, reason: change.reason ?? pick.reason } }
        return { ...current, selections: { ...current.selections, lenses }, error: null }
      })
    const setError = (error: string) => update($, review, (current) => current && { ...current, error })

    const submit = async (acceptAll: boolean) => {
      const current = await read($, review)
      if (!current || current.issue !== issue) return
      const picks = acceptAll ? acceptAllSelections(current.data, current.selections) : current.selections
      const missing = unexplainedExclusions(picks)
      if (missing.length > 0) {
        await setError(`Give a reason for each lens left out: ${missing.join(', ')}`)
        return
      }
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
    const includeOptions = INCLUDE_CHOICES.map((value) => ({ value }))

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
        <Box marginTop={1}>
          <Text bold>Lenses (answer: lens_declaration)</Text>
        </Box>
        {data.lenses.rows.map((row) => {
          if (row.always_on) {
            return (
              <Box flexDirection="row" columnGap={2}>
                <Text bold>{row.lens}</Text>
                <Box key={`lens:${row.lens}:always-on`}>
                  <Text>always on</Text>
                </Box>
              </Box>
            )
          }
          const pick = selections.lenses[row.lens] ?? { include: 'no', reason: '' }
          return (
            <Box flexDirection="column" marginTop={1}>
              <Box flexDirection="row" flexWrap="wrap" columnGap={2}>
                <Text bold>{row.lens}</Text>
                <Box key={`lens:${row.lens}:jev`}>
                  <Text>Jev: {row.jev.cell}</Text>
                </Box>
                <Select
                  key={`lens:${row.lens}:include`}
                  label="include "
                  options={includeOptions}
                  value={pick.include}
                  onSelect={(value) => setLens(row.lens, { include: value })}
                />
              </Box>
              <Input
                key={`lens:${row.lens}:reason`}
                label="reason "
                placeholder={pick.include === 'no' ? 'why it does not apply (required)' : 'why it applies'}
                value={pick.reason}
                onInput={(value) => setLens(row.lens, { reason: value })}
                onSubmit={(value) => setLens(row.lens, { reason: value })}
              />
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
