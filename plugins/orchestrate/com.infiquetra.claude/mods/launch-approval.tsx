// The launch-approval pane: the operator's answer to orchestrate's launch table.
//
// The model calls `mcp__orchestrate__review_launch_table` with the plan file it
// wrote. The mod runs `orchestrate.py launch-table --plan <file> [--issue <N>]
// --json`, shows the script's table in a pane exactly as printed, asks Approve,
// Change or Cancel in the engine's own question dialog, and returns that answer
// as the tool's result. It never launches anything: the only script it runs is
// `launch-table`, which creates nothing, and the model still runs `start` or
// `expand` itself once the answer is `approved`. Nothing launches until the
// operator approves the table.
//
// Why a dialog and not pane buttons: a hook's own time is capped (ten seconds),
// and only a wait inside a `$` call is free, so a tool call cannot wait on a
// press. `$.ui.ask` is that free wait. It returns only the label, though, and
// the engine's dialog resolves itself when the operator is away; the
// AskUserQuestion hook below turns such a resolution into a refusal, so an
// unattended dialog can never read as approval.

import { atom, read, update } from 'claude-code'
import type { On } from 'claude-code'
import type { OrchestrateDecision, OrchestrateLaunchTable } from '../types/index.d.ts'
import { launchTableArgs, readJsonWith } from './orchestrate-script.ts'

export const APPROVAL_PANE = 'orchestrate-launch'
export const APPROVAL_TOOL = 'review_launch_table'
export const APPROVAL_QUESTION = 'Approve this launch table?'
/** Approve is deliberately not first, so a reflexive Enter does not approve. */
export const APPROVAL_OPTIONS = ['Change', 'Cancel', 'Approve'] as const
const LAUNCH_TABLE_SCHEMA = 'orchestrate.launch_table.v1'
const LAUNCH_TABLE_TIMEOUT_MS = 60_000
export const AFK_REFUSAL = 'the dialog resolved itself while the operator was away; nothing was approved'

const launchTable = atom({ plugin: 'orchestrate', key: 'launchTable' } as const, null)

/** Map the dialog's answer to the decision the model receives. Only the exact label approves. */
export function decisionFor(answer: string, table: Pick<OrchestrateLaunchTable, 'plan' | 'plan_sha256'>): OrchestrateDecision {
  if (answer === 'Approve') return { decision: 'approved', plan: table.plan, plan_sha256: table.plan_sha256 }
  if (answer === 'Cancel') return { decision: 'cancelled' }
  if (answer === 'Change') return { decision: 'change', request: null }
  return { decision: 'change', request: answer }
}

type ApprovalInput = { plan?: unknown; issue?: unknown }

/** What `index.ts` registers at session start; the model sees it as `mcp__orchestrate__review_launch_table`. */
export const APPROVAL_TOOL_SPEC = {
  name: APPROVAL_TOOL,
  description:
    "Show orchestrate's launch table for a plan file to the operator and return their decision " +
    '(approved, change with their request, cancelled, dismissed, or refused when the plan does not validate). ' +
    'It runs `orchestrate.py launch-table` and launches nothing: on `approved`, run `start` (or `expand` ' +
    'with `issue`) on that same plan file yourself. Pass `issue` when the plan expands a run in flight.',
  inputSchema: {
    type: 'object',
    properties: {
      plan: { type: 'string', description: 'path of the plan JSON file' },
      issue: { type: 'integer', description: 'the run to expand, for a Phase 5 table' },
    },
    required: ['plan'],
  },
}

export function registerLaunchApproval(on: On): void {
  // The literal name, so `claude plugin validate` can read the matcher.
  on('tool.call', { tool: 'mcp__orchestrate__review_launch_table' }, async ($, e) => {
    const input = e as unknown as ApprovalInput
    const plan = typeof input.plan === 'string' ? input.plan : ''
    const issue = typeof input.issue === 'number' ? input.issue : undefined
    const table = await readJsonWith<OrchestrateLaunchTable>(
      (argv) => $.process.run(argv, { timeoutMs: LAUNCH_TABLE_TIMEOUT_MS }),
      $.plugin.root,
      () => launchTableArgs(plan, issue),
      LAUNCH_TABLE_SCHEMA,
    )
    if (!table.ok) {
      const refused: OrchestrateDecision = { decision: 'refused', reason: table.error }
      return { result: refused }
    }
    await update($, launchTable, () => table.value.text)
    await $.ui.open({ id: APPROVAL_PANE, title: `Launch table: ${table.value.run_id}` })
    let decision: OrchestrateDecision
    try {
      const answer = await $.ui.ask(APPROVAL_QUESTION, { options: APPROVAL_OPTIONS, header: 'Launch' })
      decision = decisionFor(answer, table.value)
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err)
      decision = { decision: 'dismissed', reason }
    }
    await $.ui.close({ id: APPROVAL_PANE })
    await update($, launchTable, () => null)
    return { result: decision }
  })

  // The engine's dialog resolves itself when the operator is away and says so
  // only in `afkTimeoutMs`, which `$.ui.ask` does not pass on. Refuse such a
  // resolution of this one question, so it reaches the mod as a dismissal.
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e, next) => {
    const questions = (e as unknown as { questions?: { question?: unknown }[] }).questions ?? []
    if (!questions.some((q) => q.question === APPROVAL_QUESTION)) return next(e)
    const ran = await next(e)
    const result = (ran as { result?: { afkTimeoutMs?: unknown } }).result
    if (result !== undefined && result !== null && result.afkTimeoutMs !== undefined) return { deny: AFK_REFUSAL }
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: APPROVAL_PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const text = await read($, launchTable)
    const lines = text === null ? ['No launch table is waiting.'] : text.replace(/\n$/, '').split('\n')
    // Line for line, never re-wrapped: the script's columns are the format the operator approves.
    return (
      <Box flexDirection="column">
        {lines.map((line, index) => (
          <Text key={`line-${index}`}>
            {line === '' ? ' ' : line}
          </Text>
        ))}
      </Box>
    )
  })
}
