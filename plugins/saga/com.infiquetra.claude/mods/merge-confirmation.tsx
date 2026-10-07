// The merge-confirmation pane (issue #165): the grades, the blocking items
// left at an early stop or the round limit, disputed declarations,
// consequence disagreements, the fix-later list, degraded inputs and the cost.
//
// The model calls the tool `mcp__saga__review_merge` with an issue number and
// the repository. The tool reads the `review_state.v1` document through
// `scripts/run_status.py review` and draws the pane from that document alone.
// Submit hands the answers to `review_state.py answers` on standard input, so
// the script validates and records them; the tool then returns them to the
// model as its result. Closing the pane returns `dismissed`, and the work
// skill prints the script's numbered questions instead. A thirty-minute wait
// submits `{"answers": {}, "pane_timeout": true}` to the script — the
// unattended rules file only security-guard items — and returns `timed-out`,
// which the skill never re-asks.
//
// The mod decides nothing. Every choice a Select offers is one of the script's
// fixed answers; the script is the one place an answer is checked, and a
// refusal it prints is shown in the pane as printed. The pane itself files and
// merges nothing: every durable effect is the script's.
//
// Waiting for a person: a hook's own time is capped at ten seconds per
// dispatch, and the clock stops only while a `$` call is in flight. The tool
// waits on `$.process.run(['sleep', '1'])` instead, one second at a time, up
// to WAIT_CAP_SECONDS (LEARNINGS.md, 2026-10-04).

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'
import type {
  SagaMergeAnswers,
  SagaMergeReviewOutcome,
  SagaMergeSelections,
  SagaReviewState,
} from '../types/index.d.ts'
import { costLine, gradeLabel } from './review-findings.ts'
import { readStateReviewWith, sagaScriptArgv } from './run-record.ts'

/** The pane's id. */
export const PANE = 'saga-merge'

/** The tool's short name; the model calls it as `mcp__saga__review_merge`. */
export const TOOL = 'review_merge'

/** How long the tool waits for the operator before it submits the timeout: thirty minutes. */
export const WAIT_CAP_SECONDS = 1800

/** How long one answers run may take; it reads the issue and may file through mission-control. */
const ANSWERS_TIMEOUT_MS = 120_000

/** The blocking question's choice key in `pending_choices`. */
export const MERGE_CHOICE = 'merge-blocking'

/** The fix-later choice keys start with this prefix, then the finding identity. */
export const FIX_LATER_PREFIX = 'fix-later:'

/** The only choices a fix-later item takes; the script refuses anything else. */
export const FIX_LATER_CHOICES = ['fix-now', 'file-as-issue', 'leave'] as const

/** The only merge decisions; the script refuses anything else. */
export const MERGE_DECISIONS = ['merge-with-reason', 'stop-card'] as const

const merge = atom({ plugin: 'saga', key: 'mergeReview' } as const, null)

/**
 * The outcome of the confirmation in flight, by issue. A module value, not
 * `$.state`: the waiting hook reads it between its sleeps, and a state read
 * inside one dispatch sees one frozen moment. A hot reload drops it with the pane.
 */
const outcomes = new Map<number, SagaMergeReviewOutcome>()

/** The issue whose confirmation is open, or null. One confirmation at a time. */
let active: number | null = null

// ---------------------------------------------------------------------------
// Pure helpers: no `$`, so a test calls them directly
// ---------------------------------------------------------------------------

/**
 * The argv that records the answers read from standard input. The repository
 * always rides along: the script refuses answers without both issue and
 * repository.
 */
export function answersArgv(pluginRoot: string, issue: number, repo: string): string[] {
  return sagaScriptArgv(pluginRoot, 'review_state.py', [
    'answers',
    '--issue',
    String(issue),
    '--repo',
    repo,
    '--answers',
    '-',
  ])
}

/** Whether the document still has the blocking question pending. */
export function mergeQuestionPending(data: SagaReviewState): boolean {
  return data.pending_choices.includes(MERGE_CHOICE)
}

/** The fix-later finding identities with pending choices, in document order. */
export function fixLaterIds(data: SagaReviewState): string[] {
  return data.pending_choices
    .filter((key) => key.startsWith(FIX_LATER_PREFIX))
    .map((key) => key.slice(FIX_LATER_PREFIX.length))
}

/** A recorded outcome back to the choice that made it, or '' when unanswered. */
function choiceForOutcome(outcome: Record<string, unknown> | null): string {
  switch (outcome?.outcome) {
    case 'fixed-now':
      return 'fix-now'
    case 'filed':
      return 'file-as-issue'
    case 'left':
      return 'leave'
    default:
      return ''
  }
}

/**
 * The picks the pane opens with: each pending fix-later item's recorded
 * choice, or unanswered; re-sending a recorded choice is idempotent and never
 * refiles. The merge decision always opens unanswered: only the operator can
 * merge with a reason or stop the card.
 */
export function initialSelections(data: SagaReviewState): SagaMergeSelections {
  const byId = new Map(data.findings.map((finding) => [finding.id, finding]))
  const fix_later: SagaMergeSelections['fix_later'] = {}
  for (const id of fixLaterIds(data)) {
    fix_later[id] = choiceForOutcome(byId.get(id)?.merge_outcome ?? null)
  }
  return { fix_later, merge_blocking: { decision: '', reason: '' } }
}

/**
 * The answers to record: only the answered keys. A fix-later pick of '' is
 * unanswered and left out; the merge answer rides only when the operator
 * chose a decision. `pane_timeout` is always false here; the wait, not the
 * pane, sends the timeout.
 */
export function buildAnswers(selections: SagaMergeSelections): SagaMergeAnswers {
  const answers: SagaMergeAnswers['answers'] = {}
  for (const [id, choice] of Object.entries(selections.fix_later)) {
    if (choice !== '') answers[`${FIX_LATER_PREFIX}${id}`] = choice
  }
  const { decision, reason } = selections.merge_blocking
  if (decision === 'merge-with-reason') answers[MERGE_CHOICE] = { decision, reason: reason.trim() }
  else if (decision === 'stop-card') answers[MERGE_CHOICE] = { decision }
  return { answers, pane_timeout: false }
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

export function registerMergeConfirmation(on: On): void {
  // The matcher is load-bearing: the engine refuses a second matcher-less
  // `session.start` registration, and admission's holds that one slot.
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    await $.tool.register({
      name: TOOL,
      description:
        "Opens saga's merge-confirmation pane for an issue: the lens grades, blocking items left at an " +
        'early stop or the round limit, disputed declarations, consequence disagreements, the fix-later ' +
        "list with three choices per item, degraded inputs and the cost. The operator's answers are recorded " +
        'through scripts/review_state.py, which validates them. Returns status submitted (with the answers ' +
        'recorded), dismissed, not-placed, unavailable, nothing-to-review, timed-out or error; on timed-out ' +
        "the unattended rules already ran and the merge follows the run's merge setting, so do not re-ask; " +
        'on anything but submitted or timed-out, run review_state.py render --render markdown and collect ' +
        'the answers in the conversation.',
      inputSchema: {
        type: 'object',
        properties: {
          issue: { type: 'integer', minimum: 1, description: 'The issue number to confirm the merge for.' },
          repo: { type: 'string', description: "owner/name; defaults to the review document's repository." },
        },
        required: ['issue'],
      },
    })
    return next(e)
  })

  on('tool.call', { tool: 'mcp__saga__review_merge' }, async ($, e, next) => {
    const issue = issueOf(e)
    if (issue === null) {
      return { result: { status: 'error', reason: 'issue must be a positive whole number' } }
    }
    if (active !== null) {
      return { result: { status: 'error', reason: `a merge confirmation is already open for issue ${active}` } }
    }
    const surfaces = await $.session.surfaces()
    if (!surfaces.some((surface) => surface === 'terminal' || surface === 'desktop')) {
      return {
        result: { status: 'unavailable', reason: 'no terminal or desktop surface is attached to draw the pane' },
      }
    }

    const cwd = await $.session.cwd()
    const read = await readStateReviewWith((argv) => $.process.run(argv), $.plugin.root, { repoRoot: cwd, issue })
    if (!read.ok) {
      return { result: { status: 'error', reason: `run_status review failed (${read.reason}): ${read.detail}` } }
    }
    const data = read.review.state
    if (data.pending_choices.length === 0) {
      return { result: { status: 'nothing-to-review' } }
    }
    const repo = repoOf(e) ?? repoOf({ repo: data.repo })
    if (repo === null) {
      return { result: { status: 'error', reason: 'could not determine the owner/name repository for the answers call' } }
    }

    active = issue
    outcomes.delete(issue)
    await update($, merge, () => ({ issue, repo, data, selections: initialSelections(data), error: null }))
    let outcome: SagaMergeReviewOutcome | undefined
    try {
      const opened = await $.ui.open({ id: PANE, title: `Merge confirmation · #${issue}`, focus: true })
      if (!opened.isPlaced) {
        return { result: { status: 'not-placed', reason: opened.reason } }
      }
      let waited = 0
      while (!outcomes.has(issue) && !next.signal.aborted && waited < WAIT_CAP_SECONDS) {
        await $.process.run(['sleep', '1'])
        waited += 1
      }
      outcome = outcomes.get(issue)
      if (outcome === undefined && !next.signal.aborted) {
        outcome = await submitTimeout($, issue, repo)
      }
      return { result: outcome ?? { status: next.signal.aborted ? 'dismissed' : 'timed-out' } }
    } catch (err) {
      return { result: { status: 'error', reason: `the merge confirmation failed: ${String(err)}` } }
    } finally {
      active = null
      outcomes.delete(issue)
      await $.ui.close({ id: PANE })
      await update($, merge, () => null)
    }
  })

  on('ui.close', { id: PANE }, ($, e, next) => {
    // Every close but the tool's own after an outcome: the operator's close mark or Escape.
    if (active !== null && !outcomes.has(active)) outcomes.set(active, { status: 'dismissed' })
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const state = await read($, merge)
    if (e.surface !== 'terminal' && e.surface !== 'desktop') {
      const { Text } = $.ui.resolve(e)
      return <Text>Answer the merge confirmation in the terminal or the desktop app.</Text>
    }
    const { Box, Button, Input, Select, Text } = $.ui.resolve(e)
    if (state === null) {
      return <Text dimColor>No merge confirmation is open.</Text>
    }
    const { data, selections } = state
    const issue = state.issue
    const repo = state.repo

    const setFixLater = (id: string, choice: string) =>
      update($, merge, (current) => {
        if (!current || !(FIX_LATER_CHOICES as readonly string[]).includes(choice)) return current
        return { ...current, selections: { ...current.selections, fix_later: { ...current.selections.fix_later, [id]: choice } }, error: null }
      })
    const setDecision = (decision: string) =>
      update($, merge, (current) => {
        if (!current || !(MERGE_DECISIONS as readonly string[]).includes(decision)) return current
        const blocking = { ...current.selections.merge_blocking, decision }
        return { ...current, selections: { ...current.selections, merge_blocking: blocking }, error: null }
      })
    const setReason = (reason: string) =>
      update($, merge, (current) => {
        if (!current) return current
        const blocking = { ...current.selections.merge_blocking, reason }
        return { ...current, selections: { ...current.selections, merge_blocking: blocking }, error: null }
      })
    const setError = (error: string) => update($, merge, (current) => current && { ...current, error })

    const submit = async () => {
      const current = await read($, merge)
      if (!current || current.issue !== issue) return
      const picks = current.selections
      if (picks.merge_blocking.decision === 'merge-with-reason' && picks.merge_blocking.reason.trim() === '') {
        await setError('Give a reason for the merge, or stop the card instead.')
        return
      }
      const answers = buildAnswers(picks)
      let ran
      try {
        ran = await $.process.run(answersArgv($.plugin.root, issue, repo ?? ''), {
          stdin: JSON.stringify(answers),
          timeoutMs: ANSWERS_TIMEOUT_MS,
        })
      } catch (err) {
        await setError(`review_state.py did not run: ${String(err)}`)
        return
      }
      if (ran.exitCode !== 0) {
        await setError(ran.stderr.trim() || `review_state.py exited ${ran.exitCode}`)
        return
      }
      outcomes.set(issue, { status: 'submitted', issue, answers, source: 'operator', summary: ran.stdout.trim() })
      await $.ui.close({ id: PANE })
    }
    const dismiss = async () => {
      outcomes.set(issue, { status: 'dismissed' })
      await $.ui.close({ id: PANE })
    }

    const byId = new Map(data.findings.map((finding) => [finding.id, finding]))
    const disagreements = data.consequence_disagreements
    return (
      <Box flexDirection="column" width={e.props.bodyColumns}>
        <Text bold>Grades</Text>
        {data.lenses.map((lens) => (
          <Box key={`grade:${lens.lens}`}>
            <Text>{gradeLabel(lens)}</Text>
          </Box>
        ))}
        {mergeQuestionPending(data) && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Blocking items (answer: merge-blocking)</Text>
            {data.merge_blocking.map((id) => (
              <Box key={`blocking:${id}`}>
                <Text>{`  ${id} — ${byId.get(id)?.statement ?? '(no statement recorded)'}`}</Text>
              </Box>
            ))}
            <Select
              key="merge:decision"
              label="Decision"
              value={selections.merge_blocking.decision}
              options={MERGE_DECISIONS.map((value) => ({ value }))}
              onSelect={(value: string) => setDecision(value)}
            />
            <Input
              key="merge:reason"
              label="reason "
              placeholder="why the merge is safe (required)"
              value={selections.merge_blocking.reason}
              onInput={setReason}
              onSubmit={setReason}
            />
          </Box>
        )}
        {data.disputes.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Disputed declarations</Text>
            {data.disputes.map((id) => (
              <Box key={`dispute:${id}`}>
                <Text>{`  ${id}`}</Text>
              </Box>
            ))}
          </Box>
        )}
        {disagreements.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Consequence disagreements</Text>
            {disagreements.map((row) => (
              <Box key={`disagreement:${row.id}`}>
                <Text>{`  ${row.id}: model ${row.llm}, classifier ${row.jev}`}</Text>
              </Box>
            ))}
          </Box>
        )}
        {data.unconfirmed.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Unconfirmed consequences</Text>
            {data.unconfirmed.map((id) => (
              <Box key={`unconfirmed:${id}`}>
                <Text>{`  ${id}`}</Text>
              </Box>
            ))}
          </Box>
        )}
        <Box flexDirection="column" marginTop={1}>
          <Text bold>Fix later</Text>
          {fixLaterIds(data).map((id) => (
            <Box key={`fix:${id}`} flexDirection="column">
              <Text>{`${id} — ${byId.get(id)?.statement ?? '(no statement recorded)'}`}</Text>
              <Select
                key={`fix:${id}:choice`}
                label="Choice"
                value={selections.fix_later[id] ?? ''}
                options={FIX_LATER_CHOICES.map((value) => ({ value }))}
                onSelect={(value: string) => setFixLater(id, value)}
              />
            </Box>
          ))}
        </Box>
        {data.degraded_inputs.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold>Degraded inputs</Text>
            {data.degraded_inputs.map((input, i) => (
              <Box key={`degraded:${i}`}>
                <Text>{`  ${JSON.stringify(input)}`}</Text>
              </Box>
            ))}
          </Box>
        )}
        <Box marginTop={1}>
          <Text dimColor>{costLine(data.cost)}</Text>
        </Box>
        {state.error !== null && (
          <Box key="error" marginTop={1}>
            <Text color="red" wrap="wrap">
              {state.error}
            </Text>
          </Box>
        )}
        <Box key="actions" flexDirection="row" columnGap={2} marginTop={1}>
          <Button key="submit" label="Submit" hotkey="s" variant="primary" onPress={() => submit()} />
          <Button key="dismiss" label="Dismiss" hotkey="d" role="dismiss" onPress={() => dismiss()} />
        </Box>
      </Box>
    )
  })
}

/**
 * Submit the timeout the wait expired on: empty answers with the sentinel, so
 * the script applies the unattended rules itself. A failed submit returns an
 * error the skill falls back from, never a timed-out the script never saw.
 */
async function submitTimeout($: EngineInterface, issue: number, repo: string): Promise<SagaMergeReviewOutcome> {
  let ran
  try {
    ran = await $.process.run(answersArgv($.plugin.root, issue, repo), {
      stdin: JSON.stringify({ answers: {}, pane_timeout: true }),
      timeoutMs: ANSWERS_TIMEOUT_MS,
    })
  } catch (err) {
    return { status: 'error', reason: `the timeout submit did not run: ${String(err)}` }
  }
  if (ran.exitCode !== 0) {
    return { status: 'error', reason: ran.stderr.trim() || `the timeout submit exited ${ran.exitCode}` }
  }
  return { status: 'timed-out' }
}
