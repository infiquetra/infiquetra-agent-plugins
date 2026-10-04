// The shared way a saga mod reads saga state and writes answers back.
//
// Saga's scripts own the run record. A mod never opens the files under
// `.claude/saga/runs/` and never parses prose: it runs
// `python3 <plugin root>/scripts/run_record.py show <issue>` and parses the
// JSON that prints. An answer goes back the same way, through a script's
// command line, built with `sagaScriptArgv`.
//
// Everything here is a pure function. The engine's validator follows `$` only
// into functions declared in the same file as the hook, never across an
// import, so a shared module cannot take `$` itself. Each mod file therefore
// declares its own small reader at its top level and calls these helpers:
//
//   import type { EngineInterface } from 'claude-code'
//   import { parseRunRecordShow, runRecordRunFailed, runRecordShowArgv } from './run-record.ts'
//
//   async function readRunRecord($: EngineInterface, issue: number) {
//     try {
//       return parseRunRecordShow(await $.process.run(runRecordShowArgv($.plugin.root, issue)))
//     } catch (err) {
//       return runRecordRunFailed(err)
//     }
//   }
//
// The catch matters: `$.process.run` rejects when the command cannot start
// (no `python3` on the session's PATH) or outlasts its timeout (30 seconds by
// default), and a mod must fall back to its plain behaviour then, not throw.
//
// That reader is testable too. A mod's test stubs the engine's process runner
// with `on('process.run', async (_$, e) => ({ value: { exitCode, stdout, stderr,
// isStdoutTruncated, isStderrTruncated } }))`, sees the argv the mod built in
// `e.argv`, and drives the mod's hook. `plugins/saga/tests/test_mod_run_record_contract.py`
// pins what the real script prints and exits with.

import type { ProcessRunResult } from 'claude-code'
import type { SagaRunRead, SagaRunRecord, SagaRunRecordSchema } from '../types/index.d.ts'

/** The record version this module reads; `SCHEMA` in `scripts/run_record.py`. */
export const KNOWN_SCHEMA: SagaRunRecordSchema = 'run_record.v1'

/** What `$.process.run` resolves to, narrowed to the fields the parser reads. */
export type ProcessResult = Pick<ProcessRunResult, 'exitCode' | 'stdout' | 'stderr' | 'isStdoutTruncated'>

/** `run_record.py show` exits 3 when its loader meets a record version it does not know. */
const EXIT_UNKNOWN_VERSION = 3

/** Exit 2 covers both "no record" and every other loader failure; stderr tells them apart. */
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
