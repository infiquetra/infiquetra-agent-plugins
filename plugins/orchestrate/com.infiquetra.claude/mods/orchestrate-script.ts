// The one way an orchestrate mod reads orchestrate state.
//
// Orchestrate's script owns every run. A mod never opens the run record and
// never parses prose: it runs `python3 <plugin root>/skills/orchestrate/
// scripts/orchestrate.py <read-only subcommand> ... --json` and parses the JSON
// that prints. Only two subcommands are allowed here, `status` and
// `launch-table`, both read-only; `orchestrateArgv` refuses every other one, so
// no mod can reach `start`, `go`, `expand`, `merge`, `settle` or `clean`
// through this module.
//
// The engine's validator follows `$` only into functions declared in the same
// file as the hook, never across an import, so nothing here takes `$`. A mod's
// hook passes a closure over `$.process.run` instead:
//
//   const read = await readJsonWith<OrchestrateStatus>(
//     (argv) => $.process.run(argv, { timeoutMs: 60_000 }), $.plugin.root, statusArgs(issue), 'orchestrate.status.v1')

import type { ProcessRunResult } from 'claude-code'
import type { OrchestrateRead } from '../types/index.d.ts'

/** What `$.process.run` resolves to, narrowed to the fields the parser reads. */
export type ProcessResult = Pick<ProcessRunResult, 'exitCode' | 'stdout' | 'stderr' | 'isStdoutTruncated'>

/** Runs one argv and resolves to its result; a mod passes a closure over `$.process.run`. */
export type ProcessRunner = (argv: string[]) => Promise<ProcessResult>

/** The read-only subcommands a mod may run. Nothing that launches, lands or closes is here. */
export const READ_ONLY_SUBCOMMANDS = ['status', 'launch-table'] as const

/** Where the driver sits under the plugin root (`$.plugin.root`, the folder of `.claude-plugin/`). */
export const SCRIPT_PATH = 'skills/orchestrate/scripts/orchestrate.py'

/** The argv that runs one read-only subcommand of orchestrate.py; anything else throws. */
export function orchestrateArgv(pluginRoot: string, args: readonly string[]): string[] {
  const subcommand = args[0]
  if (!(READ_ONLY_SUBCOMMANDS as readonly string[]).includes(subcommand ?? '')) {
    throw new RangeError(`not a read-only orchestrate subcommand: ${subcommand}`)
  }
  return ['python3', `${pluginRoot}/${SCRIPT_PATH}`, ...args]
}

/** `status --issue <N> --json`, for a positive whole issue number. */
export function statusArgs(issue: number): string[] {
  if (!Number.isInteger(issue) || issue <= 0) throw new RangeError(`not an issue number: ${issue}`)
  return ['status', '--issue', String(issue), '--json']
}

/** `launch-table --plan <file> [--issue <N>] --json`. */
export function launchTableArgs(plan: string, issue?: number): string[] {
  if (plan.trim() === '') throw new RangeError('no plan file named')
  const args = ['launch-table', '--plan', plan]
  if (issue !== undefined) {
    if (!Number.isInteger(issue) || issue <= 0) throw new RangeError(`not an issue number: ${issue}`)
    args.push('--issue', String(issue))
  }
  args.push('--json')
  return args
}

/** The script's refusal: the last line it wrote to stderr (notices come first), or the exit. */
function refusal(ran: ProcessResult): string {
  const lines = ran.stderr.split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.at(-1) ?? `orchestrate.py exited ${ran.exitCode} without a message`
}

/** Turn what one `--json` run did into its value, or the reason there is none. */
export function parseJsonRun<T>(ran: ProcessResult, schema: string): OrchestrateRead<T> {
  if (ran.exitCode !== 0) return { ok: false, error: refusal(ran) }
  if (ran.isStdoutTruncated) {
    return { ok: false, error: 'orchestrate.py printed more than the engine keeps (4 MiB); the JSON was cut off' }
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(ran.stdout)
  } catch {
    return { ok: false, error: 'orchestrate.py printed no JSON' }
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return { ok: false, error: 'orchestrate.py printed no JSON object' }
  }
  const found = (parsed as { schema?: unknown }).schema
  if (found !== schema) {
    return { ok: false, error: `orchestrate.py printed ${JSON.stringify(found)}, not ${schema}` }
  }
  return { ok: true, value: parsed as T }
}

/**
 * Run one read-only subcommand through `run` and parse its JSON. Never rejects:
 * a run that could not start or timed out, and arguments that are not valid,
 * come back as `{ ok: false, error }`, so a mod draws the error instead of throwing.
 */
export async function readJsonWith<T>(
  run: ProcessRunner,
  pluginRoot: string,
  args: () => string[],
  schema: string,
): Promise<OrchestrateRead<T>> {
  try {
    return parseJsonRun<T>(await run(orchestrateArgv(pluginRoot, args())), schema)
  } catch (err) {
    return { ok: false, error: `orchestrate.py did not run: ${err instanceof Error ? err.message : String(err)}` }
  }
}
