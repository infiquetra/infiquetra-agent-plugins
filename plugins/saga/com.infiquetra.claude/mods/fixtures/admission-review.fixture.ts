// A canned `admission.py --dry-run --render json` document (schema
// `admission_review.v1`) for the review pane's tests, and the answers the pane
// must hand to `admission.py --answers -` for the golden Submit.
//
// Two roles and nothing else to decide: admission no longer asks for a lens
// declaration or for repair allowances (issue #161), so the document carries no
// `lenses` table and the answers carry no `lens_declaration`. The palette
// leaves fable out on purpose: a Select listing exactly these models shows the
// choices come from the document, not from a list written in the mod.
//
// GOLDEN_ANSWERS is strict JSON between its two marker comments, because
// `plugins/saga/tests/test_admission.py` reads that same text and pushes it
// through the real script, so the two sides of the hand-off cannot drift.

import type { SagaAdmissionAnswers, SagaAdmissionReviewData } from '../../types/index.d.ts'

export const PALETTE = {
  vendor: 'claude',
  models: ['opus', 'sonnet', 'haiku'],
  efforts: ['low', 'medium', 'high', 'xhigh'],
  effort_ceilings: { opus: 'xhigh', sonnet: 'xhigh', haiku: 'high' },
  pairs: [
    { model: 'opus', effort: 'low' },
    { model: 'opus', effort: 'medium' },
    { model: 'opus', effort: 'high' },
    { model: 'opus', effort: 'xhigh' },
    { model: 'sonnet', effort: 'low' },
    { model: 'sonnet', effort: 'medium' },
    { model: 'sonnet', effort: 'high' },
    { model: 'sonnet', effort: 'xhigh' },
    { model: 'haiku', effort: 'low' },
    { model: 'haiku', effort: 'medium' },
    { model: 'haiku', effort: 'high' },
  ],
}

export const REVIEW_JSON: SagaAdmissionReviewData = {
  schema: 'admission_review.v1',
  issue: 103,
  repo: 'infiquetra/infiquetra-agent-plugins',
  record_path: null,
  pending_questions: ['risk_tier', 'staffing_overrides', 'change_shape'],
  questions: [],
  staffing: {
    source: 'staffing',
    status: 'ok',
    rows: [
      {
        role: 'planner',
        vendor: 'claude',
        default: { vendor: 'claude', model: 'opus', effort: 'high' },
        proposed: { vendor: 'claude', model: 'opus', effort: 'high' },
        jev: { cell: 'not configured', state: 'not-configured', band: null, suggested: null, confidence: null, reason: '' },
        why: 'staffing default (work shape judgment)',
      },
      {
        role: 'worker',
        vendor: 'claude',
        default: { vendor: 'claude', model: 'sonnet', effort: 'xhigh' },
        proposed: { vendor: 'claude', model: 'sonnet', effort: 'xhigh' },
        jev: {
          cell: 'opus/medium (0.72, raise to confirm)',
          state: 'suggested',
          band: 'confirm-raise',
          suggested: 'opus/medium',
          confidence: 0.72,
          reason: 'the change touches a gate',
        },
        why: 'staffing default (work shape implementation)',
      },
    ],
  },
  palette: PALETTE,
  tables_markdown: '',
}

/** What Submit sends after worker is set to opus/medium: the role map, and nothing else. */
export const GOLDEN_ANSWERS: SagaAdmissionAnswers =
/* BEGIN GOLDEN ANSWERS */
{
  "staffing_overrides": {
    "planner": {"vendor": "claude", "model": "opus", "effort": "high"},
    "worker": {"vendor": "claude", "model": "opus", "effort": "medium"}
  }
}
/* END GOLDEN ANSWERS */
