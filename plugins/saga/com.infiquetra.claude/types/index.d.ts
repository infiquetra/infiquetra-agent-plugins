// Saga's state contract for Claude Code mods.
//
// Saga's scripts own its state; a mod only reads it, by running
// `scripts/run_record.py show <issue>` and parsing the JSON it prints. These
// types describe that JSON. The authority is `plugins/saga/scripts/run_record.py`
// (`SCHEMA` and `TOP_LEVEL_KEYS`); when that file adds a record version, this
// contract and `mods/run-record.ts` change with it.
//
// It also declares the session state the saga mods keep (`PluginState`, at the
// end). Self-contained on purpose: no import and no reference, as the engine
// requires of a plugin's `types` file. Every exported name is led by `Saga`.

/** The one record version this contract reads. */
export type SagaRunRecordSchema = 'run_record.v1'

/**
 * One issue's saga run record, as `run_record.py show` prints it. `to_dict`
 * always writes all twelve keys, so every one is required here;
 * `plugins/saga/tests/test_mod_run_record_contract.py` checks this list against
 * `TOP_LEVEL_KEYS`. Fields a newer writer added are kept under the index
 * signature.
 */
export type SagaRunRecord = {
  schema: SagaRunRecordSchema
  issue: number
  repo: string
  created_at: string
  updated_at: string
  admission: Record<string, unknown>
  run_configuration: Record<string, unknown>
  approval_scope: Record<string, unknown>
  roster: unknown[]
  units: unknown[]
  review_cycles: unknown[]
  next_step: string
  [field: string]: unknown
}

/** Why a read did not produce a record. */
export type SagaRunReadFailure =
  /** The script ran and found no record for the issue. */
  | 'no-record'
  /** The record (or the script's loader) names a version this contract does not know. */
  | 'unknown-version'
  /** The script exited 0 but did not print one JSON object. */
  | 'unreadable'
  /** Any other failure, such as running outside a git repository. */
  | 'error'

/** The outcome of reading one run record. A mod shows `detail` rather than guessing. */
export type SagaRunRead =
  | { ok: true; record: SagaRunRecord }
  | { ok: false; reason: SagaRunReadFailure; detail: string }

/** The version token `scripts/run_status.py summary --json` prints. */
export type SagaRunStatusSchema = 'run_status.v1'

/**
 * Where a run's build loop stands (issue #105). One unit is described (`unit`
 * and the iteration fields set) when its worktree is the checkout or it is the
 * only unit that ran the loop; otherwise only the green count is.
 */
export type SagaRunBuildLoop = {
  unit: string | null
  /** The latest iteration's number. */
  pass: number | null
  failing: number | null
  /** Checks that could not execute, never counted as failing. */
  could_not_execute: number | null
  green: boolean | null
  units_total: number
  units_green: number
}

/**
 * The latest code review cycle against its allowance, and how many lenses met
 * their bar by the verdict's own rule (issue #105).
 */
export type SagaRunReviewProgress = {
  unit: string | null
  cycle: number | null
  standard_allowance: number
  escalated_allowance: number
  /** The cycle is past the standard allowance. */
  is_escalated: boolean
  outcome: string | null
  lenses_met: number
  lenses_total: number
  lenses_not_run: number
}

/**
 * One run as `run_status.py summary --json` prints it. The run record supplies
 * `next_step`, `updated_at`, `record_path`, `build_loop` and `review`; the saga
 * envelope supplies `phase`, `plan_path` (as recorded, relative to the
 * checkout) and `plan_file` (absolute). Each is null when its store does not
 * know the run. `band_line` is the status band's line, rendered by the script
 * so every harness shows the same words. `setup_notice` is the one admission
 * notice for missing tools and the reproduction sandbox, or null when the
 * record has none.
 */
export type SagaSetupNotice = {
  text: string
  missing_tools: string[]
  sandbox_unavailable: boolean
}

export type SagaRunStatus = {
  issue: number
  repo: string | null
  next_step: string
  updated_at: string | null
  record_path: string | null
  phase: string | null
  plan_path: string | null
  plan_file: string | null
  build_loop: SagaRunBuildLoop | null
  review: SagaRunReviewProgress | null
  setup_notice: SagaSetupNotice | null
  band_line: string
}

/** What `run_status.py summary --json` prints. */
export type SagaRunStatusView = {
  schema: SagaRunStatusSchema
  repo_root: string
  runs: SagaRunStatus[]
}

/**
 * One section of a plan as the plan viewer splits it: the frontmatter
 * (`level` 0), or a heading of level 1 to 3 and the text up to the next
 * heading of the same or a higher level. `text` starts with the heading line.
 */
export type SagaPlanSection = {
  level: 0 | 1 | 2 | 3
  title: string
  text: string
}

/** The plan the viewer pane shows: where it is, when it was read, its sections. */
export type SagaPlanView = {
  /** The path as the operator or the run named it. */
  path: string
  /** The file, every link resolved; what an edit's `file_path` is compared with. */
  absPath: string
  /** The checkout a `path:line` reference in the plan is relative to. */
  repoRoot: string
  mtimeMs: number
  sections: SagaPlanSection[]
}

// ---------------------------------------------------------------------------
// The admission review pane (issue #103)
// ---------------------------------------------------------------------------
//
// `scripts/admission.py --dry-run --render json` prints one document of schema
// `admission_review.v1`; the pane draws from it and nothing else. The authority
// is `review_data` in that script. A field the pane does not draw is left
// untyped under the index signatures.

/** The one review document version the pane reads. */
export type SagaAdmissionReviewSchema = 'admission_review.v1'

/** One tier as admission prints it: vendor, model and effort. */
export type SagaAdmissionTier = { vendor: string | null; model: string; effort: string | null }

/** A Jev cell: the text to show, and the state a pane branches on instead of the text. */
export type SagaAdmissionJevCell = {
  cell: string
  state: string
  [field: string]: unknown
}

/** One staffing row: a role, its default, Jev's cell, the tier proposed, and why. */
export type SagaAdmissionStaffingRow = {
  role: string
  vendor: string | null
  default: SagaAdmissionTier | null
  proposed: SagaAdmissionTier | null
  jev: SagaAdmissionJevCell
  why: string
}

/** One lens row. `include` is `always on`, `yes`, `no` or `undeclared`. */
export type SagaAdmissionLensRow = {
  lens: string
  always_on: boolean
  include: string
  reason: string
  /** `band` is `pre-checked`, `consider` or null (issue #110's lens proposal). */
  jev: SagaAdmissionJevCell & { probability: number | null; band?: string | null }
}

/** The tiers an operator may pick: models, efforts, and the pairs the palette allows. */
export type SagaAdmissionPalette = {
  vendor: string
  models: string[]
  efforts: string[]
  effort_ceilings: Record<string, string>
  pairs: { model: string; effort: string }[]
}

/** What `admission.py --render json` prints. */
export type SagaAdmissionReviewData = {
  schema: SagaAdmissionReviewSchema
  issue: number
  repo: string
  pending_questions: string[]
  staffing: { source: string; status: string; rows: SagaAdmissionStaffingRow[] }
  lenses: { source: string; status: string; catalogue_version: string | null; rows: SagaAdmissionLensRow[] }
  /** Null when the bundled tier palette could not be loaded. */
  palette: SagaAdmissionPalette | null
  [field: string]: unknown
}

/** The operator's picks while the pane is open: per role a tier, per conditional lens a decision. */
export type SagaAdmissionSelections = {
  staffing: Record<string, { model: string; effort: string }>
  lenses: Record<string, { include: 'yes' | 'no'; reason: string }>
}

/** The pane's session state: the document it draws, the picks, and the last refusal shown. */
export type SagaAdmissionReview = {
  issue: number
  repo: string | null
  data: SagaAdmissionReviewData
  selections: SagaAdmissionSelections
  error: string | null
}

/** The answers the pane hands to `admission.py --answers -`. */
export type SagaAdmissionAnswers = {
  staffing_overrides: Record<string, { vendor: string; model: string; effort: string }>
  lens_declaration: {
    always_on: string[]
    conditional_applies: Record<string, string>
    conditional_does_not_apply: Record<string, string>
  }
}

/** What `mcp__saga__review_admission` returns to the model. */
export type SagaAdmissionReviewOutcome =
  | { status: 'submitted'; issue: number; answers: SagaAdmissionAnswers; source: 'operator'; summary: string }
  | { status: 'dismissed' | 'timed-out' | 'nothing-to-review' }
  | { status: 'not-placed' | 'unavailable'; reason: string }
  | { status: 'error'; reason: string; exitCode?: number; stderr?: string }

/** The version token `scripts/run_status.py review --json` prints. */
export type SagaReviewViewSchema = 'review_view.v1'

/**
 * Where a lens stands against its bar. `not_run` (the lens did not execute, or
 * the result has no row for a selected lens) and `unscored` (it ran and
 * reported findings but sets no bar) carry no score, so neither can read as a
 * low one.
 */
export type SagaReviewLensState = 'met' | 'not_met' | 'not_run' | 'unscored'

/** One finding as `run_status.py review` prints it; `FINDING_FIELDS` there. */
export type SagaReviewFinding = {
  id: string
  severity: string
  path: string
  line: number | string
  category: string
  dimension: string
  evidence: string
  impact: string
  status: string
  confidence: string
}

/** One lens of the review: its state, why when it has no usable result, and its findings. */
export type SagaReviewLens = {
  lens: string
  state: SagaReviewLensState
  reason: string | null
  /** Only a `met` or `not_met` lens carries its score. */
  derived_overall: number | null
  finding_count: number
  /** The first few findings, most severe first. */
  top: SagaReviewFinding[]
  findings: SagaReviewFinding[]
}

/** The latest review result in one loop of the run record. */
export type SagaReview = {
  unit: string
  cycle: number
  loop: string
  revision: string
  outcome: string
  reason: string | null
  lenses: SagaReviewLens[]
  /** Findings whose lens is not one of `lenses`. */
  unattributed_findings: SagaReviewFinding[]
  advisory_count: number
  duplicate_count: number
}

/** What `run_status.py review --json` prints. `review` is null when no result is recorded. */
export type SagaReviewView = {
  schema: SagaReviewViewSchema
  repo_root: string
  issue: number | null
  record_path: string | null
  legacy_entries: number
  review: SagaReview | null
}

/**
 * The unit row a session is working, as `run_status.py --repo-root <cwd>
 * unit-for --json` prints it under `match` (issue #107). The token-capture mod
 * appends this session's usage to that row through `run_record.py usage add`.
 */
export type SagaUsageTarget = {
  issue: number
  /** The row's identity as `usage add --unit` takes it: `id`, else `name`, else `unit_id`. */
  unit: string
  /** The staffing role the session records: the row's `role`, else `worker` (`merging-worker` in a merge turn). */
  role: string
  /** How the row matched: its worktree, or only its branch. */
  matched_by: 'worktree' | 'branch'
  record_path: string
  /** The record store, passed back as `--store-root` so a write resolves nothing again. */
  store_root: string
  /** More than one row matched; this is the strongest, active and newest. */
  ambiguous: boolean
}

/** What `run_status.py unit-for --json` prints. */
export type SagaUnitForView = {
  schema: SagaRunStatusSchema
  repo_root: string
  branch: string
  match: SagaUsageTarget | null
}

/**
 * Token counts not yet written to the run record, summed per model session:
 * one bucket per session id (a subagent's loop is its own), role, model and
 * effort, the identity of a `usage add` entry. The four counts are the ones a
 * Claude Code `turn.step` result reports.
 */
export type SagaUsageBucket = {
  sessionId: string
  /** The subagent's id, or null on the main thread. */
  agentId: string | null
  role: string
  model: string
  effort: string
  uncachedInput: number
  cacheRead: number
  cacheWrite: number
  output: number
  /** How many model requests the counts sum. */
  steps: number
}

/** The raw run record pane: the record as JSON, cut into pages a Code block can hold. */
export type SagaRecordView = {
  issue: number
  pages: string[]
  page: number
}

/**
 * One role's agent type, as `scripts/role_agent_types.py` prints it: the role's
 * prompt (a saga hosting preamble, then the roles-library file's body) and the
 * model and effort the run is staffed at.
 */
export type SagaRoleAgentType = {
  /** The staffing role (`worker`); the registered type is `saga:<role>`. */
  role: string
  /** The roles library's id for it (`implementer`). */
  role_id: string
  readable_role: string
  prompt_path: string
  prompt: string
  model: string
  effort: string
  /** The resolver's tier source: `operator`, `overlay`, `jev-raise` or `policy`. */
  source: string
  description: string
}

/** What `scripts/role_agent_types.py --json` prints: `saga_role_agent_types.v1`. */
export type SagaRoleAgentTypes = {
  schema: 'saga_role_agent_types.v1'
  /** Whether this checkout has an active run; with none, `types` is empty. */
  active: boolean
  issue: number | null
  types: SagaRoleAgentType[]
  skipped: { role: string; reason: string }[]
  /** A hash of every type's role, tier and prompt; it changes only when one of them does. */
  fingerprint: string
  /** Why no types could be answered, when that is the case. */
  error?: string
}

/** One registered agent type's resolved tier, by its full name (`saga:worker`). */
export type SagaRegisteredAgentType = {
  role: string
  model: string
  effort: string
}

/** What the agent-types mod last registered, kept in the session's state. */
export type SagaAgentTypesState = {
  active: boolean
  issue: number | null
  fingerprint: string
  byType: Record<string, SagaRegisteredAgentType>
}

declare module 'claude-code' {
  interface PluginState {
    saga: {
      /** The plan the `/plan-view` pane shows, or null before one is loaded. */
      planView: SagaPlanView | null
      /** The section shown, by index into `planView.sections`; -1 is the section list. */
      planSelected: number
      /** The page of the shown section, from 0. */
      planPage: number
      /** The admission review pane's state (issue #103), or null when no review is open. */
      admissionReview: SagaAdmissionReview | null
      /** The review the `/review-view` pane shows, or null before one is loaded. */
      reviewView: SagaReviewView | null
      /** The lens whose findings are listed; null is the lens list. */
      reviewLens: string | null
      /** The run record's modification time when `reviewView` was read. */
      reviewMtimeMs: number
      /** The unit this session's usage goes to; null when it works none (or before it is resolved). */
      usageTarget: SagaUsageTarget | null
      /** Usage read from `turn.step` and not yet written through `usage add`. */
      usageQueue: SagaUsageBucket[]
      /** This checkout's active runs as the status band last read them (issue #105). */
      runStatus: SagaRunStatus[]
      /** The operator pressed the band's Hide; it stays hidden for the session. */
      bandHidden: boolean
      /** The raw run record the band's Record button opened, or null. */
      recordView: SagaRecordView | null
      /** What the agent-types mod last registered (issue #106). */
      agentTypes: SagaAgentTypesState
    }
  }
}
