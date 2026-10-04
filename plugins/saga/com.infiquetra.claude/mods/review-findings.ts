// The words the review findings pane (issue #108) draws, kept apart from the
// pane so they are plain functions of the review view and test without an engine.
//
// Nothing here decides anything: whether a lens met its bar arrives from
// `scripts/run_status.py review`, which applies the verdict's own rule. These
// only turn that view into labels and prompt text.

import type { SagaReview, SagaReviewFinding, SagaReviewLens, SagaReviewLensState } from '../types/index.d.ts'

/** The engine refuses a Markdown block over 10,000 characters; a finding's text stays well under. */
export const FINDING_TEXT_LIMIT = 1_500

/** The pseudo-lens that lists findings whose lens is not in the review's lens list. */
export const OTHER_FINDINGS = '(other findings)'

/** How each state reads in the pane; `run_status.py`'s `STATE_WORDS` says the same. */
export const STATE_WORDS: Record<SagaReviewLensState, string> = {
  met: 'met',
  not_met: 'not met',
  not_run: 'not run',
  unscored: 'unscored',
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/**
 * One lens's row in the lens list. A lens with no usable result says why
 * instead of showing any number, so it cannot read as a low score; a lens that
 * did not run shows a finding count only when it somehow has findings.
 */
export function lensLabel(lens: SagaReviewLens): string {
  const parts = [lens.lens, STATE_WORDS[lens.state] ?? lens.state]
  if (lens.state !== 'not_run' || lens.finding_count > 0) parts.push(plural(lens.finding_count, 'finding'))
  if ((lens.state === 'not_run' || lens.state === 'unscored') && lens.reason) parts.push(`(${lens.reason})`)
  return parts.join('  ')
}

/** `P1 path:line category`, one dim line under a lens row. */
export function findingLine(finding: SagaReviewFinding): string {
  return `${finding.severity} ${finding.path}:${finding.line} ${finding.category}`
}

/** `P1 · path:line · category`, the heading of a finding in a lens's list. */
export function findingHeading(finding: SagaReviewFinding): string {
  return `${finding.severity} · ${finding.path}:${finding.line} · ${finding.category}`
}

/** `text`, cut at `limit` characters with an ellipsis. */
export function truncate(text: string, limit: number = FINDING_TEXT_LIMIT): string {
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`
}

/** A finding's evidence and impact as the Markdown drawn under its heading. */
export function findingText(finding: SagaReviewFinding): string {
  return truncate(`${finding.evidence}\n\n**Impact:** ${finding.impact}`)
}

function quoted(text: string): string {
  return text
    .split('\n')
    .map((line) => (line === '' ? '>' : `> ${line}`))
    .join('\n')
}

/** The text a finding's Quote button puts in the prompt: a block quote naming its lens and place. */
export function quoteText(lens: string, finding: SagaReviewFinding): string {
  const head = `[${finding.severity} · ${lens}] ${finding.path}:${finding.line} — ${finding.category}`
  return `${quoted(`${head}\n${finding.evidence}\nimpact: ${finding.impact}`)}\n\n`
}

/** The header line over the lens list: issue, cycle, outcome, and the reviewed revision. */
export function reviewHeading(issue: number | null, review: SagaReview): string {
  const parts = [`#${issue ?? '?'}`, review.unit, `cycle ${review.cycle}`, review.outcome, review.revision.slice(0, 12)]
  return parts.join(' · ')
}

/** The findings listed for `lens`, which may be `OTHER_FINDINGS`. */
export function findingsFor(review: SagaReview, lens: string): SagaReviewFinding[] {
  if (lens === OTHER_FINDINGS) return review.unattributed_findings
  return review.lenses.find((one) => one.lens === lens)?.findings ?? []
}
