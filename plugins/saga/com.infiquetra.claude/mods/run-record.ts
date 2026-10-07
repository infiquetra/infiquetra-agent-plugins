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
  SagaMachineRecordSchema,
  SagaOfferStatus,
  SagaReview,
  SagaReviewStateSchema,
  SagaReviewView,
  SagaReviewViewSchema,
  SagaRunRead,
  SagaRunRecord,
  SagaRunRecordSchema,
  SagaRunStatusSchema,
  SagaRunStatusView,
  SagaSetupSurvey,
  SagaSetupSurveySchema,
  SagaStateReview,
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

// ---------------------------------------------------------------------------
// The review-state document embedded in `run_status.py review` (issue #165)
//
// For records with C1 review runs the review view carries the whole
// `review_state.v1` document under `state`. The panes read the document
// through this reader alone, never by running the review-state script.
// ---------------------------------------------------------------------------

/** The document version this module reads; `SCHEMA` in `scripts/review_state.py`. */
export const KNOWN_REVIEW_STATE_SCHEMA: SagaReviewStateSchema = 'review_state.v1'

/** The outcome of reading the state review. A mod shows `detail` rather than guessing. */
export type StateReviewRead =
  | { ok: true; view: SagaReviewView; review: SagaStateReview }
  | { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

/** Whether the review is a state review carrying the embedded document. */
export function isStateReview(review: SagaReview | SagaStateReview | null): review is SagaStateReview {
  return (
    review !== null &&
    typeof (review as SagaStateReview).state_schema === 'string' &&
    typeof (review as SagaStateReview).state === 'object' &&
    (review as SagaStateReview).state !== null
  )
}

/** Turn what `run_status.py review --json` did into the state review, or the reason there is none. */
export function parseRunStatusStateReview(ran: ProcessResult): StateReviewRead {
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
  const review = view.review as SagaStateReview | null | undefined
  if (review === null || review === undefined) {
    return { ok: false, reason: 'unreadable', detail: 'run_status review recorded no review' }
  }
  if (!isStateReview(review)) {
    return { ok: false, reason: 'unreadable', detail: 'run_status review printed no state review' }
  }
  if (review.state_schema !== KNOWN_REVIEW_STATE_SCHEMA || review.state.schema !== KNOWN_REVIEW_STATE_SCHEMA) {
    return {
      ok: false,
      reason: 'unknown-version',
      detail: `review-state document version ${JSON.stringify(review.state_schema)} is not ${KNOWN_REVIEW_STATE_SCHEMA}`,
    }
  }
  return { ok: true, view: view as unknown as SagaReviewView, review }
}

/** Read the state review through `run`. Never rejects, as `readRunRecordWith`. */
export async function readStateReviewWith(
  run: ProcessRunner,
  pluginRoot: string,
  query: ReviewViewQuery,
): Promise<StateReviewRead> {
  try {
    return parseRunStatusStateReview(await run(runStatusReviewArgv(pluginRoot, query)))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `run_status review did not run: ${detail}` }
  }
}

/**
 * Read the review in either shape through `run`, enforcing the document
 * version for a state review. One run, two parses: the legacy parse validates
 * the envelope for both shapes, and a state review is then checked against
 * the known document token before anything draws from it. Never rejects.
 */
export async function readEitherReviewWith(
  run: ProcessRunner,
  pluginRoot: string,
  query: ReviewViewQuery,
): Promise<ReviewViewRead> {
  let completed: ProcessResult
  try {
    completed = await run(runStatusReviewArgv(pluginRoot, query))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `run_status review did not run: ${detail}` }
  }
  const parsed = parseRunStatusReview(completed)
  if (!parsed.ok) return parsed
  const review = parsed.view.review
  if (review !== null && isStateReview(review)) {
    const checked = parseRunStatusStateReview(completed)
    if (!checked.ok) return checked
  }
  return parsed
}

// ---------------------------------------------------------------------------
// The setup survey and the machine offer (issue #165)
//
// The setup pane draws `saga_setup.py survey --format json` through these
// readers alone, and the first-session offer reads `offer-status` through one.
// Recording the offer rides `record-offer`'s exit code, which needs no reader.
// ---------------------------------------------------------------------------

/** The survey version this module reads; `SURVEY_SCHEMA` in `scripts/saga_setup.py`. */
export const KNOWN_SETUP_SURVEY_SCHEMA: SagaSetupSurveySchema = 'setup_survey.v1'

/** The machine-record version the offer reads; `MACHINE_SCHEMA` in `scripts/saga_setup.py`. */
export const KNOWN_MACHINE_RECORD_SCHEMA: SagaMachineRecordSchema = 'machine_record.v1'

/** The outcome of reading the setup survey. A mod shows `detail` rather than guessing. */
export type SetupSurveyRead =
  | { ok: true; survey: SagaSetupSurvey }
  | { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

/** The outcome of reading the machine offer status. */
export type OfferStatusRead =
  | { ok: true; status: SagaOfferStatus }
  | { ok: false; reason: 'unknown-version' | 'unreadable' | 'error'; detail: string }

/**
 * The argv that surveys the checkout's tools as JSON. The survey persists the
 * machine record with `ran` set, so it never serves as the offer check.
 */
export function setupSurveyArgv(pluginRoot: string, repo: string): string[] {
  return sagaScriptArgv(pluginRoot, 'saga_setup.py', ['survey', '--repo', repo, '--format', 'json'])
}

/** The argv that installs one tool. Install runs one call per ticked tool, in order. */
export function setupInstallArgv(pluginRoot: string, tool: string, repo: string): string[] {
  return sagaScriptArgv(pluginRoot, 'saga_setup.py', ['install', '--tools', tool, '--repo', repo])
}

/** The argv that prints the machine record's `ran` and `offered` without writing. */
export function setupOfferStatusArgv(pluginRoot: string): string[] {
  return sagaScriptArgv(pluginRoot, 'saga_setup.py', ['offer-status'])
}

/** The argv that stamps `offered` on the machine record. */
export function setupRecordOfferArgv(pluginRoot: string): string[] {
  return sagaScriptArgv(pluginRoot, 'saga_setup.py', ['record-offer'])
}

/** The JSON object one setup verb printed, or why there is none. */
function setupOutput(
  ran: ProcessResult,
  command: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; reason: 'unreadable' | 'error'; detail: string } {
  if (ran.exitCode !== 0) {
    const stderr = ran.stderr.trim()
    return { ok: false, reason: 'error', detail: stderr === '' ? `${command} exited ${ran.exitCode}` : stderr }
  }
  if (ran.isStdoutTruncated) {
    return { ok: false, reason: 'unreadable', detail: `${command} printed past the stdout cap` }
  }
  let value: unknown
  try {
    value = JSON.parse(ran.stdout)
  } catch {
    value = undefined
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { ok: false, reason: 'unreadable', detail: `${command} printed no JSON object` }
  }
  return { ok: true, value: value as Record<string, unknown> }
}

/** Turn what `saga_setup.py survey --format json` did into the survey, or the reason there is none. */
export function parseSetupSurvey(ran: ProcessResult): SetupSurveyRead {
  const parsed = setupOutput(ran, 'saga_setup survey')
  if (!parsed.ok) return parsed
  const survey = parsed.value
  if (survey.schema !== KNOWN_SETUP_SURVEY_SCHEMA) {
    return {
      ok: false,
      reason: 'unknown-version',
      detail: `setup survey version ${JSON.stringify(survey.schema)} is not ${KNOWN_SETUP_SURVEY_SCHEMA}`,
    }
  }
  if (!Array.isArray(survey.tools)) {
    return { ok: false, reason: 'unreadable', detail: 'saga_setup survey printed no tool rows' }
  }
  return { ok: true, survey: survey as unknown as SagaSetupSurvey }
}

/** Turn what `saga_setup.py offer-status` did into the offer status, or the reason there is none. */
export function parseOfferStatus(ran: ProcessResult): OfferStatusRead {
  const parsed = setupOutput(ran, 'saga_setup offer-status')
  if (!parsed.ok) return parsed
  const status = parsed.value
  if (status.schema !== KNOWN_MACHINE_RECORD_SCHEMA) {
    return {
      ok: false,
      reason: 'unknown-version',
      detail: `machine record version ${JSON.stringify(status.schema)} is not ${KNOWN_MACHINE_RECORD_SCHEMA}`,
    }
  }
  if (typeof status.ran !== 'boolean' || typeof status.offered !== 'boolean') {
    return { ok: false, reason: 'unreadable', detail: 'saga_setup offer-status printed no ran and offered flags' }
  }
  return { ok: true, status: status as unknown as SagaOfferStatus }
}

/** Read the setup survey through `run`. Never rejects, as `readRunRecordWith`. */
export async function readSetupSurveyWith(
  run: ProcessRunner,
  pluginRoot: string,
  repo: string,
): Promise<SetupSurveyRead> {
  try {
    return parseSetupSurvey(await run(setupSurveyArgv(pluginRoot, repo)))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `saga_setup survey did not run: ${detail}` }
  }
}

/** Read the machine offer status through `run`. Never rejects, as `readRunRecordWith`. */
export async function readOfferStatusWith(run: ProcessRunner, pluginRoot: string): Promise<OfferStatusRead> {
  try {
    return parseOfferStatus(await run(setupOfferStatusArgv(pluginRoot)))
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, reason: 'error', detail: `saga_setup offer-status did not run: ${detail}` }
  }
}
