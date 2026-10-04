// Saga's state contract for Claude Code mods.
//
// Saga's scripts own its state; a mod only reads it, by running
// `scripts/run_record.py show <issue>` and parsing the JSON it prints. These
// types describe that JSON. The authority is `plugins/saga/scripts/run_record.py`
// (`SCHEMA` and `TOP_LEVEL_KEYS`); when that file adds a record version, this
// contract and `mods/run-record.ts` change with it.
//
// Self-contained on purpose: no import and no reference, as the engine requires
// of a plugin's `types` file. Every exported name is led by `Saga`.

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
