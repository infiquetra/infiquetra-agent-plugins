// The shared way a saga mod reads saga state and writes answers back.
//
// Saga's scripts own the run record. A mod never opens the files under
// `.claude/saga/runs/` and never parses prose: it runs
// `python3 <plugin root>/scripts/run_record.py show <issue>` and parses the
// JSON that prints. (One pinned stderr prefix is the single exception; see
// `EXIT_RECORD_ERROR`.) An answer goes back the same way, through a script's
// command line, built with `sagaScriptArgv`.
//
// The engine's validator follows `$` only into functions declared in the same
// file as the hook, never across an import, so nothing here takes `$` itself.
// A closure over `$.process.run` can cross the import, though, so the guarded
// reader lives here once and a mod's hook passes it the runner:
//
//   import { readRunRecordWith } from './run-record.ts'
//
//   const read = await readRunRecordWith((argv) => $.process.run(argv), $.plugin.root, issue)
//
// `readRunRecordWith` owns the catch: `$.process.run` rejects when the command
// cannot start (no `python3` on the session's PATH) or outlasts its timeout (30
// seconds by default), and the reader turns that into reason 'error' so the mod
// falls back to its plain behaviour instead of throwing. No mod writes its own
// try/catch around the run.
//
// A mod's test can drive the real path too: stub the engine's process runner
// with `on('process.run', async (_$, e) => ({ value: { exitCode, stdout, stderr,
// isStdoutTruncated, isStderrTruncated } }))`, see the argv the reader built in
// `e.argv`, and drive the mod's hook. `plugins/saga/tests/test_mod_run_record_contract.py`
// pins what the real script prints and exits with.

import type { ProcessRunResult } from 'claude-code'
import type {
  SagaReviewView,
  SagaReviewViewSchema,
  SagaRunRead,
  SagaRunRecord,
  SagaRunRecordSchema,
  SagaRunStatusSchema,
  SagaRunStatusView,
} from '../types/index.d.ts'

/** The record version this module reads; `SCHEMA` in `scripts/run_record.py`. */
export const KNOWN_SCHEMA: SagaRunRecordSchema = 'run_record.v1'

/** What `$.process.run` resolves to, narrowed to the fields the parser reads. */
export type ProcessResult = Pick<ProcessRunResult, 'exitCode' | 'stdout' | 'stderr' | 'isStdoutTruncated'>

/** `run_record.py show` exits 3 when its loader meets a record version it does not know. */
const EXIT_UNKNOWN_VERSION = 3

/**
 * Exit 2 covers both "no record" and every other loader failure, and the script
 * has no exit code of its own for a missing record, so the start of its stderr
 * message tells them apart. This is the one place the reader matches script
 * text; `test_mod_run_record_contract.py` pins the prefix against the real
 * script (DECISIONS.md, 2026-10-04).
 */
const EXIT_RECORD_ERROR = 2
const NO_RECORD_PREFIX = 'run_record: no record for issue '

/** A script under `scripts/` is named by its file name alone. */
const SCRIPT_NAME = /^[A-Za-z0-9_][A-Za-z0-9_.-]*\.py$/

function requireIssue(issue: number): void {
  if (!Number.isInteger(issue) || issue <= 0) {
    throw new RangeError(`not an issue number: ${issue}`)
  }
}

/**
 * The argv that runs one of saga's scripts. `$.process.run` takes argv with no
 * shell, so nothing here is quoted; a script name that could leave `scripts/`
 * is refused.
 */
export function sagaScriptArgv(pluginRoot: string, script: string, args: readonly string[]): string[] {
  if (!SCRIPT_NAME.test(script) || script.includes('..')) {
    throw new RangeError(`not a saga script name: ${script}`)
  }
  return ['python3', `${pluginRoot}/scripts/${script}`, ...args]
}

/** The argv that prints one issue's run record as JSON. */
export function runRecordShowArgv(pluginRoot: string, issue: number): string[] {
  requireIssue(issue)
  return sagaScriptArgv(pluginRoot, 'run_record.py', ['show', String(issue)])
}

/** The read a mod reports when `$.process.run` rejected, so the script never ran to an exit. */
export function runRecordRunFailed(err: unknown): SagaRunRead {
  const detail = err instanceof Error ? err.message : String(err)
  return { ok: false, reason: 'error', detail: `run_record show did not run: ${detail}` }
}

/** Turn what `run_record.py show` did into a record, or the reason there is none. */
export function parseRunRecordShow(ran: ProcessResult): SagaRunRead {
  const detail = ran.stderr.trim()
  if (ran.exitCode === EXIT_UNKNOWN_VERSION) return { ok: false, reason: 'unknown-version', detail }
  if (ran.exitCode === EXIT_RECORD_ERROR && detail.startsWith(NO_RECORD_PREFIX)) {
    return { ok: false, reason: 'no-record', detail }
  }
  if (ran.exitCode !== 0) return { ok: false, reason: 'error', detail }
  if (ran.isStdoutTruncated) {
    // The engine keeps only the first 4 MiB of standard output; the JSON is cut.
    return { ok: false, reason: 'unreadable', detail: 'run_record show printed more than the engine keeps (4 MiB); the record was cut off' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch (err) {
    return { ok: false, reason: 'unreadable', detail: String(err) }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, reason: 'unreadable', detail: 'run_record show did not print a JSON object' }
  }
  const schema = (parsed as { schema?: unknown }).schema
  if (schema !== KNOWN_SCHEMA) {
    return { ok: false, reason: 'unknown-version', detail: `record version ${JSON.stringify(schema)} is not ${KNOWN_SCHEMA}` }
  }
  return { ok: true, record: parsed as SagaRunRecord }
}

/** Runs one argv and resolves to its result; a mod passes `(argv) => $.process.run(argv)`. */
export type ProcessRunner = (argv: string[]) => Promise<ProcessResult>

/**
 * Read one issue's run record through `run`. Never rejects: a run that could
 * not start or timed out, and an issue number that is not one, come back as
 * reason 'error', so every mod keeps its plain fallback without a catch of its own.
 */
export async function readRunRecordWith(run: ProcessRunner, pluginRoot: string, issue: number): Promise<SagaRunRead> {
  try {
    return parseRunRecordShow(await run(runRecordShowArgv(pluginRoot, issue)))
  } catch (err) {
    return runRecordRunFailed(err)
  }
}

// ---------------------------------------------------------------------------
// `run_status.py summary`: the read-only run view (issue #104)
//
// The run record has no plan path and no lifecycle phase; the saga envelope
// does. `scripts/run_status.py summary --json` joins the two, so a mod reads
// both through one script, the same guarded way it reads the record.
// ---------------------------------------------------------------------------

/** The view version this module reads; `SCHEMA` in `scripts/run_status.py`. */
export const KNOWN_RUN_STATUS_SCHEMA: SagaRunStatusSchema = 'run_status.v1'

/** Which runs `run_status.py summary` reports, and from which checkout. */
export type RunStatusQuery = {
  /** The checkout whose saga envelopes are read: the session's directory. */
  repoRoot: string
  /** One issue; left out, the issue the checkout's active saga or `issue/N` branch names. */
  issue?: number
  /** Every run with a next step, the resolved issue first. */
  allActive?: boolean
}

/** The outcome of reading the run view. A mod shows `detail` rather than guessing. */
export type RunStatusRead =
  | { ok: true; view: SagaRunStatusView }
  | { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

/** The argv that prints the run view as JSON. */
export function runStatusSummaryArgv(pluginRoot: string, query: RunStatusQuery): string[] {
  const args = ['--repo-root', query.repoRoot, 'summary']
  if (query.issue !== undefined) {
    requireIssue(query.issue)
    args.push('--issue', String(query.issue))
  }
  if (query.allActive === true) args.push('--all-active')
  args.push('--json')
  return sagaScriptArgv(pluginRoot, 'run_status.py', args)
}

/** Why a `run_status.py` command produced no view. */
type RunStatusFailure = { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

type RunStatusObjectRead = { ok: true; value: Record<string, unknown> } | RunStatusFailure

/**
 * The JSON object a `run_status.py` command printed, or why there is none.
 * `command` names it in every detail, as in "run_status summary".
 */
function parseRunStatusObject(ran: ProcessResult, command: string): RunStatusObjectRead {
  const detail = ran.stderr.trim()
  if (ran.exitCode === EXIT_UNKNOWN_VERSION) return { ok: false, reason: 'unknown-version', detail }
  if (ran.exitCode !== 0) return { ok: false, reason: 'error', detail }
  if (ran.isStdoutTruncated) {
    return { ok: false, reason: 'unreadable', detail: `${command} printed more than the engine keeps (4 MiB)` }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch (err) {
    return { ok: false, reason: 'unreadable', detail: String(err) }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, reason: 'unreadable', detail: `${command} did not print a JSON object` }
  }
  return { ok: true, value: parsed as Record<string, unknown> }
}

/** Turn what `run_status.py summary --json` did into the view, or the reason there is none. */
export function parseRunStatusSummary(ran: ProcessResult): RunStatusRead {
  const parsed = parseRunStatusObject(ran, 'run_status summary')
  if (!parsed.ok) return parsed
  const view = parsed.value
  if (view.schema !== KNOWN_RUN_STATUS_SCHEMA) {
    return {
      ok: false,
      reason: 'unknown-version',
      detail: `run view version ${JSON.stringify(view.schema)} is not ${KNOWN_RUN_STATUS_SCHEMA}`,
    }
  }
  if (!Array.isArray(view.runs)) {
    return { ok: false, reason: 'unreadable', detail: 'run_status summary printed no runs list' }
  }
  return { ok: true, view: view as unknown as SagaRunStatusView }
}

/** Read the run view through `run`. Never rejects, as `readRunRecordWith`. */
export async function readRunStatusWith(
  run: ProcessRunner,
  pluginRoot: string,
  query: RunStatusQuery,
): Promise<RunStatusRead> {
  try {
    return parseRunStatusSummary(await run(runStatusSummaryArgv(pluginRoot, query)))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `run_status summary did not run: ${detail}` }
  }
}

// ---------------------------------------------------------------------------
// `run_status.py review`: the latest code review, lens by lens (issue #108)
//
// Whether a lens met its bar is the verdict's own rule
// (`review_consensus.lens_outcomes_for_result`); the script applies it and a
// mod shows the answer, never recomputing it.
// ---------------------------------------------------------------------------

/** The view version this module reads; `REVIEW_SCHEMA` in `scripts/run_status.py`. */
export const KNOWN_REVIEW_VIEW_SCHEMA: SagaReviewViewSchema = 'review_view.v1'

/** Which review `run_status.py review` reports, and from which checkout. */
export type ReviewViewQuery = {
  /** The checkout whose run is read: the session's directory. */
  repoRoot: string
  /** One issue; left out, the issue the checkout's active saga or `issue/N` branch names. */
  issue?: number
}

/** The outcome of reading the review view. A mod shows `detail` rather than guessing. */
export type ReviewViewRead =
  | { ok: true; view: SagaReviewView }
  | { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

/** The argv that prints the latest code review as JSON. */
export function runStatusReviewArgv(pluginRoot: string, query: ReviewViewQuery): string[] {
  const args = ['--repo-root', query.repoRoot, 'review']
  if (query.issue !== undefined) {
    requireIssue(query.issue)
    args.push('--issue', String(query.issue))
  }
  args.push('--json')
  return sagaScriptArgv(pluginRoot, 'run_status.py', args)
}

/** Turn what `run_status.py review --json` did into the view, or the reason there is none. */
export function parseRunStatusReview(ran: ProcessResult): ReviewViewRead {
  const parsed = parseRunStatusObject(ran, 'run_status review')
  if (!parsed.ok) return parsed
  const view = parsed.value
  if (view.schema !== KNOWN_REVIEW_VIEW_SCHEMA) {
    return {
      ok: false,
      reason: 'unknown-version',
      detail: `review view version ${JSON.stringify(view.schema)} is not ${KNOWN_REVIEW_VIEW_SCHEMA}`,
    }
  }
  const review = view.review as { lenses?: unknown } | null | undefined
  if (review === undefined || (review !== null && !Array.isArray(review.lenses))) {
    return { ok: false, reason: 'unreadable', detail: 'run_status review printed no lens list' }
  }
  return { ok: true, view: view as unknown as SagaReviewView }
}

/** Read the review view through `run`. Never rejects, as `readRunRecordWith`. */
export async function readReviewViewWith(
  run: ProcessRunner,
  pluginRoot: string,
  query: ReviewViewQuery,
): Promise<ReviewViewRead> {
  try {
    return parseRunStatusReview(await run(runStatusReviewArgv(pluginRoot, query)))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `run_status review did not run: ${detail}` }
  }
}
