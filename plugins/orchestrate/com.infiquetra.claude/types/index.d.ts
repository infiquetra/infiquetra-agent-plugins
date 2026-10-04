// Orchestrate's state contract for Claude Code mods.
//
// Orchestrate's script owns every run; a mod only reads it, by running
// `skills/orchestrate/scripts/orchestrate.py status --issue <N> --json` or
// `launch-table --plan <file> [--issue <N>] --json` and parsing the JSON that
// prints. These types describe that JSON. The authority is orchestrate.py
// (`status_snapshot`, `STATUS_SCHEMA`, `cmd_launch_table`,
// `LAUNCH_TABLE_SCHEMA`); when it changes a shape, it changes the schema name,
// and this contract and the mods change with it.
//
// Self-contained on purpose: no import and no reference, as the engine requires
// of a plugin's `types` file. Every exported name is led by `Orchestrate`.

/** The one `status --json` version this contract reads. */
export type OrchestrateStatusSchema = 'orchestrate.status.v1'

/** The one `launch-table --json` version this contract reads. */
export type OrchestrateLaunchTableSchema = 'orchestrate.launch_table.v1'

/** One unit of a run, as `status --json` prints it. */
export type OrchestrateStatusUnit = {
  name: string
  vendor: string
  model: string | null
  effort: string | null
  /** The unit's recorded state: pending, running, done, orphaned, parked, ... */
  state: string
  /** Herdr's live reading for a running unit, `unknown` without the companion, else null. */
  herdr: string | null
  branch: string | null
  /** Commits on the unit's branch; null where git could not count or there is no branch. */
  commits: number | null
  /** `yes`, `no`, `unknown` or `missing`; null when the unit has no branch. */
  landed: string | null
  /** What holds a pending unit (`needs output from x`, `serialized behind y`); empty otherwise. */
  waits_on: string
  task: string
  note: string
  role: string | null
  lifecycle: string | null
  merge_state: string
  after: string[]
  serialize: string[]
}

/** One Code Review controller's recorded result. */
export type OrchestrateStatusReview = {
  controller: string | null
  lifecycle: string | null
  outcome: string | null
  state: string
  recorded_unrouted: boolean
  note_contradicts: string | null
}

/** One run, as `status --json` prints it. */
export type OrchestrateStatus = {
  schema: OrchestrateStatusSchema
  issue: number
  run_id: string
  source: string
  base: string
  branch: string
  unresolvable_branch: string | null
  companion_available: boolean
  units: OrchestrateStatusUnit[]
  unrecorded: { name: string; branch: string }[]
  reviews: OrchestrateStatusReview[]
  operator_actions: { owner: string; fix_id: string; touched_paths: string[] }[]
}

/** One row of the launch table, as `launch-table --json` prints it. */
export type OrchestrateLaunchUnit = {
  name: string
  cap: string | null
  vendor: string
  model: string | null
  effort: string | null
  effort_via_setup: boolean
  permission: string
  permission_declared: boolean
  after: string[]
  serialize: string[]
  role: string | null
  task: string
}

/** The table the operator approves, as `launch-table --json` prints it. */
export type OrchestrateLaunchTable = {
  schema: OrchestrateLaunchTableSchema
  issue: number | null
  run_id: string
  source: string
  plan: string
  plan_sha256: string
  vendors_allowed: string[]
  workspace: string | null
  account: string | null
  units: OrchestrateLaunchUnit[]
  later_phases: { phase: string; what: string; cap: string | null; after: string[] }[]
  /** The fixed-format table exactly as the script prints it without `--json`. */
  text: string
}

/** The outcome of one script read. A mod shows `error` rather than guessing. */
export type OrchestrateRead<T> = { ok: true; value: T } | { ok: false; error: string }

/**
 * What `mcp__orchestrate__review_launch_table` returns to the model: the
 * operator's answer, never an action. `approved` carries the digest of the plan
 * file the operator saw, so the model starts exactly that file.
 */
export type OrchestrateDecision =
  | { decision: 'approved'; plan: string; plan_sha256: string }
  | { decision: 'change'; request: string | null }
  | { decision: 'cancelled' }
  | { decision: 'dismissed'; reason: string }
  | { decision: 'refused'; reason: string }

declare module 'claude-code' {
  interface PluginState {
    orchestrate: {
      /** The issue the fleet pane shows; null while it is closed. */
      fleetIssue: number | null
      /** The last `status --json` read for that issue. */
      fleet: OrchestrateRead<OrchestrateStatus> | null
      /** When that read finished, in the engine clock's milliseconds. */
      fleetRefreshedAt: number | null
      /** Whether a read is in flight, so the timer never stacks reads. */
      fleetBusy: boolean
      /** The launch-table text the approval pane shows while the operator decides. */
      launchTable: string | null
    }
  }
}
