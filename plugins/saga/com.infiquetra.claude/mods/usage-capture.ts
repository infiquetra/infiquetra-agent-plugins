// Live token capture (issue #107): what each model request of a unit session
// costs, appended to that unit's row of the run record as the session runs.
//
// Saga's scripts own the record; this mod only collects and hands over.
//
// - At session start it asks `run_status.py unit-for` which unit row the
//   session's directory is working: the row whose worktree it is, else the row
//   whose branch is checked out there. No row, and the mod records nothing:
//   no timer, no queue, no write. The coordinator in the primary checkout is
//   such a session.
// - Every model request (`turn.step`), on the main thread and in every
//   subagent's loop, adds its usage to a bucket in `$.state`: one bucket per
//   model session, role, model and effort, the identity of a `usage add` entry.
//   `turn.step` rather than `turn.complete`, because only the request carries
//   the effort it asked for, and a subagent's turns complete inside the
//   parent's.
// - Every minute, and at session end, each bucket is written through
//   `run_record.py usage add`, the one portable writer, which takes the
//   record's lock. One process per bucket per minute, never one per request.
//   A failed write keeps its bucket for the next tick; a written one is
//   subtracted, so requests that landed during the write are kept.
//
// Claude Code reports cache writes as one count, without the five-minute and
// one-hour split the record prices apart. They are recorded as one-hour writes,
// the dearer rate, so a report built on them can overstate cache-write spend
// but never understate it (`references/run-record.md`).
//
// The plain fallback on every other harness is the same writer, called by the
// harness's own integration with the counts it reads (`usage add --help`).

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { SagaUsageBucket, SagaUsageTarget } from '../types/index.d.ts'
import { KNOWN_RUN_STATUS_SCHEMA, sagaScriptArgv } from './run-record.ts'
import type { ProcessResult } from './run-record.ts'

/** How often the queue is written. */
export const USAGE_FLUSH_MS = 60_000

/** How long one timed write may run before it is abandoned and retried next tick. */
const FLUSH_TIMEOUT_MS = 10_000

/** One write at session end, inside the engine's 1.5-second budget for every hook. */
const END_TIMEOUT_MS = 1_000

/** The vendor every entry this mod writes names. */
export const USAGE_VENDOR = 'claude'

/** The `usage add` flag Claude Code's single cache-write count goes under (see the header). */
export const CACHE_WRITE_FLAG = '--cache-write-1h'

/** The effort a request recorded when its model takes none: `usage add` needs a name. */
export const NO_EFFORT = 'none'

/** A saga role registered as a Claude agent type (`saga:<role>`) records as that role. */
const SAGA_AGENT_TYPE = /^saga:([a-z][a-z0-9-]*)$/

const usageTarget = atom({ plugin: 'saga', key: 'usageTarget' } as const, null)
const usageQueue = atom({ plugin: 'saga', key: 'usageQueue' } as const, [])

/** One request's usage, as `addStep` folds it into the queue. */
export type UsageStep = {
  sessionId: string
  agentId: string | null
  role: string
  model: string
  effort: string
  uncachedInput: number
  cacheRead: number
  cacheWrite: number
  output: number
}

/** The argv that asks which unit row a session at `cwd` is working. */
export function unitForArgv(pluginRoot: string, cwd: string): string[] {
  return sagaScriptArgv(pluginRoot, 'run_status.py', ['--repo-root', cwd, 'unit-for', '--json'])
}

/**
 * The unit `run_status.py unit-for --json` matched, or null. Anything but a
 * clean match of the known view version is null: a mod that cannot tell which
 * unit a session works records nothing rather than guessing.
 */
export function parseUnitFor(ran: ProcessResult): SagaUsageTarget | null {
  if (ran.exitCode !== 0 || ran.isStdoutTruncated) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch {
    return null
  }
  if (typeof parsed !== 'object' || parsed === null) return null
  const view = parsed as { schema?: unknown; match?: unknown }
  if (view.schema !== KNOWN_RUN_STATUS_SCHEMA) return null
  const match = view.match as Partial<SagaUsageTarget> | null | undefined
  if (typeof match !== 'object' || match === null) return null
  const { issue, unit, role, store_root } = match
  if (!Number.isInteger(issue) || (issue as number) <= 0) return null
  if (typeof unit !== 'string' || unit === '' || typeof role !== 'string' || role === '') return null
  if (typeof store_root !== 'string' || store_root === '') return null
  return match as SagaUsageTarget
}

/** The effort a request asked for, as `usage add --effort` takes it. */
export function effortName(effort: string | number | undefined): string {
  return effort === undefined ? NO_EFFORT : String(effort)
}

/** The role a subagent's requests record: its saga role, else the session's. */
export function subagentRole(agentType: string | undefined, sessionRole: string): string {
  const saga = agentType === undefined ? null : SAGA_AGENT_TYPE.exec(agentType)
  return saga === null ? sessionRole : saga[1]
}

/** The session id an entry records: the session's own, or `<session>/<agent>` for a subagent's loop. */
export function entrySessionId(bucket: Pick<SagaUsageBucket, 'sessionId' | 'agentId'>): string {
  return bucket.agentId === null ? bucket.sessionId : `${bucket.sessionId}/${bucket.agentId}`
}

function sameEntry(a: Omit<UsageStep, 'uncachedInput' | 'cacheRead' | 'cacheWrite' | 'output'>, b: typeof a): boolean {
  return (
    a.sessionId === b.sessionId &&
    a.agentId === b.agentId &&
    a.role === b.role &&
    a.model === b.model &&
    a.effort === b.effort
  )
}

/** The queue with one request's usage summed into its bucket. */
export function addStep(queue: readonly SagaUsageBucket[], step: UsageStep): SagaUsageBucket[] {
  const at = queue.findIndex((bucket) => sameEntry(bucket, step))
  if (at < 0) return [...queue, { ...step, steps: 1 }]
  const was = queue[at]
  const sum: SagaUsageBucket = {
    ...was,
    uncachedInput: was.uncachedInput + step.uncachedInput,
    cacheRead: was.cacheRead + step.cacheRead,
    cacheWrite: was.cacheWrite + step.cacheWrite,
    output: was.output + step.output,
    steps: was.steps + 1,
  }
  return queue.map((bucket, i) => (i === at ? sum : bucket))
}

/**
 * The queue after `written` reached the record: its counts subtracted from its
 * bucket, which goes once nothing is left in it. What a request added while the
 * write ran stays.
 */
export function subtractWritten(queue: readonly SagaUsageBucket[], written: SagaUsageBucket): SagaUsageBucket[] {
  const out: SagaUsageBucket[] = []
  for (const bucket of queue) {
    if (!sameEntry(bucket, written)) {
      out.push(bucket)
      continue
    }
    const left: SagaUsageBucket = {
      ...bucket,
      uncachedInput: bucket.uncachedInput - written.uncachedInput,
      cacheRead: bucket.cacheRead - written.cacheRead,
      cacheWrite: bucket.cacheWrite - written.cacheWrite,
      output: bucket.output - written.output,
      steps: bucket.steps - written.steps,
    }
    if (left.steps > 0) out.push(left)
  }
  return out
}

/** The argv that appends one bucket to the target unit's usage block. */
export function usageAddArgv(pluginRoot: string, target: SagaUsageTarget, bucket: SagaUsageBucket): string[] {
  return sagaScriptArgv(pluginRoot, 'run_record.py', [
    '--store-root',
    target.store_root,
    'usage',
    'add',
    String(target.issue),
    '--unit',
    target.unit,
    '--session-id',
    entrySessionId(bucket),
    '--role',
    bucket.role,
    '--vendor',
    USAGE_VENDOR,
    '--model',
    bucket.model,
    '--effort',
    bucket.effort,
    '--uncached-input',
    String(bucket.uncachedInput),
    '--cache-read',
    String(bucket.cacheRead),
    CACHE_WRITE_FLAG,
    String(bucket.cacheWrite),
    '--output',
    String(bucket.output),
  ])
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

// Module variables, on purpose: a hot reload stops the module's timers and
// resets these with them, so the next request starts the timer again. The
// queue itself is in `$.state` and survives the reload.
let timerRunning = false
let flushChain: Promise<void> = Promise.resolve()
let flushPending = false
const agentRoles = new Map<string, string>()

/** Write every bucket in the queue, one `usage add` each, stopping at the first failure. */
async function writeQueue($: EngineInterface, timeoutMs: number): Promise<void> {
  const target = await read($, usageTarget)
  if (target === null) return
  const queue = await read($, usageQueue)
  for (const bucket of queue ?? []) {
    let ran: ProcessResult
    try {
      ran = await $.process.run(usageAddArgv($.plugin.root, target, bucket), { timeoutMs })
    } catch (err) {
      $.ui.log(`usage-capture: usage add did not run: ${errorText(err)}`, { to: 'debug' })
      return
    }
    if (ran.exitCode !== 0) {
      $.ui.log(`usage-capture: usage add exited ${ran.exitCode}: ${ran.stderr.trim()}`, { to: 'debug' })
      return
    }
    await update($, usageQueue, (now) => subtractWritten(now ?? [], bucket))
  }
}

/** Queue one write of the queue after any already running, so two never interleave. */
function flushUsage($: EngineInterface, timeoutMs: number): Promise<void> {
  flushPending = true
  flushChain = flushChain
    .then(() => {
      flushPending = false
      return writeQueue($, timeoutMs)
    })
    .catch((err) => $.ui.log(`usage-capture: flush failed: ${errorText(err)}`, { to: 'debug' }))
  return flushChain
}

function startTimer($: EngineInterface): void {
  if (timerRunning) return
  timerRunning = true
  $.clock.every(USAGE_FLUSH_MS, () => {
    // A tick while a write is still waiting adds nothing: that write takes the whole queue.
    if (!flushPending) void flushUsage($, FLUSH_TIMEOUT_MS)
  })
}

/** The role a subagent's requests record, looked up once per subagent. */
async function roleOf($: EngineInterface, agentId: string, sessionRole: string): Promise<string> {
  const known = agentRoles.get(agentId)
  if (known !== undefined) return known
  let agentType: string | undefined
  try {
    agentType = (await $.agent.list()).find((agent) => agent.id === agentId)?.type
  } catch {
    agentType = undefined
  }
  const role = subagentRole(agentType, sessionRole)
  agentRoles.set(agentId, role)
  return role
}

export function registerUsageCapture(on: On): void {
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    let target: SagaUsageTarget | null = null
    try {
      target = parseUnitFor(await $.process.run(unitForArgv($.plugin.root, e.cwd), { timeoutMs: FLUSH_TIMEOUT_MS }))
    } catch (err) {
      $.ui.log(`usage-capture: unit-for did not run: ${errorText(err)}`, { to: 'debug' })
    }
    await update($, usageTarget, () => target)
    if (target !== null) {
      if (target.ambiguous) {
        $.ui.log(`usage-capture: several unit rows match; recording to #${target.issue} ${target.unit}`, { to: 'debug' })
      }
      startTimer($)
    }
    return next(e)
  })

  on('turn.step', { model: /^/ }, async function* ($, e, next) {
    const result = yield* next(e)
    const usage = result.usage
    // No response, or one without usage (interrupted, an API error): nothing was billed to read.
    if (usage === null) return result
    const target = await read($, usageTarget)
    if (target === null) return result
    const agentId = e.agentId ?? null
    const step: UsageStep = {
      sessionId: await $.session.id(),
      agentId,
      role: agentId === null ? target.role : await roleOf($, agentId, target.role),
      model: usage.model,
      effort: effortName(e.effort),
      uncachedInput: usage.input_tokens,
      cacheRead: usage.cache_read_input_tokens,
      cacheWrite: usage.cache_creation_input_tokens,
      output: usage.output_tokens,
    }
    await update($, usageQueue, (queue) => addStep(queue ?? [], step))
    startTimer($)
    return result
  })

  on('session.end', { sessionId: /^/ }, async ($, e, next) => {
    await flushUsage($, END_TIMEOUT_MS)
    return next(e)
  })
}
