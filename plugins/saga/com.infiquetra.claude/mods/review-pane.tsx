// The review findings pane (issue #108): `/review-view` shows the run's latest
// code review result, one row per selected lens, inside Claude Code.
//
// Read-only. It reads the review through `scripts/run_status.py review`, which
// picks the latest `review_result.v2` entry from the run record and applies the
// verdict's own per-lens rule; the pane shows that answer and never recomputes
// it. The only thing it writes is the operator's own prompt, when they press a
// finding's Quote. No acceptance decision and no finding edits happen here.
// The plain fallback on every other harness is `run_status.py review`'s table.
//
// - `/review-view` opens the checkout's run; `/review-view #N` issue N's.
// - Each lens row reads met, not met, not run or unscored, with its finding
//   count and its top findings. A lens that did not run, or has no recorded
//   result, says so; it never shows a number that could read as a low score.
// - Choosing a lens lists its findings with `path:line`; Quote puts one in the
//   prompt.
// - A Bash call that ran `review_result.py` reloads the open pane, and so does a
//   change of the run record's modification time, polled every five seconds
//   while the pane is open.
// - The run status band's Review button (issue #105) opens this pane: this
//   module answers the press on `band-review-<issue>` itself, because a
//   plugin's own `$.command.run` never reaches its own command hook.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, On } from 'claude-code'

import type { SagaReviewView } from '../types/index.d.ts'
import { fitTables } from './plan-sections.ts'
import {
  findingHeading,
  findingLine,
  findingsFor,
  findingText,
  lensLabel,
  OTHER_FINDINGS,
  quoteText,
  reviewHeading,
} from './review-findings.ts'
import { readReviewViewWith } from './run-record.ts'
import type { ReviewViewQuery } from './run-record.ts'

/** The pane's id, and the `requestId` its `ui.render` hook matches. */
export const REVIEW_PANE = 'saga-review'

/** The run status band's Review button, `band-review-<issue>` (issue #105). */
export const BAND_REVIEW_ELEMENT = /^band-review-\d+$/

/** How often an open pane checks the run record's modification time. */
export const REVIEW_POLL_MS = 5_000

/** A Bash command that ran the script which writes review results. */
const WRITES_REVIEW = /\breview_result\.py\b/

const reviewView = atom({ plugin: 'saga', key: 'reviewView' } as const, null)
const reviewLens = atom({ plugin: 'saga', key: 'reviewLens' } as const, null)
const reviewMtimeMs = atom({ plugin: 'saga', key: 'reviewMtimeMs' } as const, 0)

/** The run record's modification time, or 0 when it cannot be read. */
async function recordMtime($: EngineInterface, view: SagaReviewView): Promise<number> {
  if (view.record_path === null) return 0
  try {
    return (await $.fs.stat(view.record_path)).mtimeMs
  } catch {
    return 0
  }
}

/** Read the review again for the shown issue, keeping the reader on their lens when it is still there. */
async function reloadReview($: EngineInterface, shown: SagaReviewView): Promise<void> {
  const query: ReviewViewQuery = { repoRoot: shown.repo_root }
  if (shown.issue !== null) query.issue = shown.issue
  const ran = await readReviewViewWith((argv) => $.process.run(argv), $.plugin.root, query)
  // A record caught mid-write keeps its last good review on screen.
  if (!ran.ok || ran.view.review === null) return
  const view = ran.view
  await update($, reviewView, () => view)
  const mtime = await recordMtime($, view)
  await update($, reviewMtimeMs, () => mtime)
  const lens = await read($, reviewLens)
  const review = view.review
  if (lens !== null && review !== null && lens !== OTHER_FINDINGS && !review.lenses.some((one) => one.lens === lens)) {
    await update($, reviewLens, () => null)
  }
}

async function isOpen($: EngineInterface): Promise<boolean> {
  const panes = await $.ui.panes()
  return panes.some((pane) => pane.id === REVIEW_PANE)
}

/** Put text in the operator's prompt, saying so when the prompt cannot take it. */
async function fillPrompt($: EngineInterface, text: string): Promise<void> {
  const filled = await $.prompt.fill({ text, mode: 'insert' })
  if (!filled.isFilled) $.ui.toast('review-view: the prompt cannot take text right now')
}

/**
 * Open the pane on `args` as `/review-view` takes them: nothing or `#N`.
 * Says what it did; `isOpened` is false when there was nothing to open.
 */
async function openReviewView($: EngineInterface, args: string): Promise<{ text: string; isOpened: boolean }> {
  const cwd = await $.session.cwd()
  const target = args.trim()
  const issueArg = /^#?(\d+)$/.exec(target)
  if (target !== '' && issueArg === null) return { text: 'review-view: name an issue, as in /review-view #108', isOpened: false }
  const query: ReviewViewQuery = { repoRoot: cwd }
  if (issueArg !== null) query.issue = Number(issueArg[1])

  const ran = await readReviewViewWith((argv) => $.process.run(argv), $.plugin.root, query)
  if (!ran.ok) return { text: `review-view: could not read the review (${ran.reason}): ${ran.detail}`, isOpened: false }
  const view = ran.view
  const review = view.review
  if (view.issue === null) return { text: 'review-view: no saga run for this checkout. Name one: /review-view #N', isOpened: false }
  if (review === null) return { text: `review-view: no review result recorded for #${view.issue}.`, isOpened: false }

  await update($, reviewView, () => view)
  await update($, reviewLens, () => null)
  const mtime = await recordMtime($, view)
  await update($, reviewMtimeMs, () => mtime)
  await $.ui.open({ id: REVIEW_PANE, title: `Review · #${view.issue} cycle ${review.cycle}` })
  const findings = review.lenses.reduce((sum, lens) => sum + lens.finding_count, 0) + review.unattributed_findings.length
  return {
    text: `review-view: #${view.issue} cycle ${review.cycle}, ${review.outcome}, ${review.lenses.length} lenses, ${findings} findings.`,
    isOpened: true,
  }
}

export function registerReviewPane(on: On): void {
  on('session.start', { cwd: /^/ }, async ($, e, next) => {
    await $.command.register({
      name: 'review-view',
      description: 'Show the latest saga code review, lens by lens, in a pane',
      argumentHint: '[#issue]',
      immediate: true,
    })

    // Catches a review written by another session: a stat, never a read of the record.
    async function poll(): Promise<void> {
      const view = await read($, reviewView)
      if (view === null || view.record_path === null) return
      if (!(await isOpen($))) return
      const mtime = await recordMtime($, view)
      if (mtime === 0 || mtime === (await read($, reviewMtimeMs))) return
      await reloadReview($, view)
    }
    $.clock.every(REVIEW_POLL_MS, () => {
      void poll()
    })

    return next(e)
  })

  on('command.run', { command: 'review-view' }, async ($, e) => {
    const opened = await openReviewView($, e.args)
    return { text: opened.text }
  })

  // The run status band's Review button (issue #105): a press on `band-review-N` opens #N's review.
  on('ui.press', { plugin: 'saga', element: BAND_REVIEW_ELEMENT }, async ($, e) => {
    const issue = /(\d+)$/.exec(e.element)?.[1] ?? ''
    const opened = await openReviewView($, `#${issue}`)
    if (!opened.isOpened) $.ui.toast(opened.text)
    return { element: e.element }
  })

  // `review_result.py` writing a result reloads the open pane at once.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    if (!WRITES_REVIEW.test(e.command)) return ran
    const view = await read($, reviewView)
    if (view === null || !(await isOpen($))) return ran
    await reloadReview($, view)
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: REVIEW_PANE }, async ($, e) => {
    const { Box, Button, Markdown, Text } = $.ui.resolve(e)
    const view = await read($, reviewView)
    const review = view?.review ?? null
    if (view === null || review === null) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No review loaded. Run /review-view or /review-view #issue.</Text>
        </Box>
      )
    }

    const lens = await read($, reviewLens)
    if (lens === null) {
      const others = review.unattributed_findings
      return (
        <Box flexDirection="column">
          <Text dimColor>{reviewHeading(view.issue, review)}</Text>
          {review.lenses.length === 0 && <Text>This review has no lens results.</Text>}
          {review.lenses.map((one) => (
            <Box key={`row-${one.lens}`} flexDirection="column">
              <Button key={`lens-${one.lens}`} label={lensLabel(one)} plain onPress={() => update($, reviewLens, () => one.lens)} />
              {one.top.map((finding, i) => (
                <Text key={`top-${one.lens}-${i}`} dimColor>
                  {`  ${findingLine(finding)}`}
                </Text>
              ))}
            </Box>
          ))}
          {others.length > 0 && (
            <Button
              key="lens-other"
              label={`${OTHER_FINDINGS}  ${others.length} finding${others.length === 1 ? '' : 's'}`}
              plain
              onPress={() => update($, reviewLens, () => OTHER_FINDINGS)}
            />
          )}
        </Box>
      )
    }

    const findings = findingsFor(review, lens)
    const shown = review.lenses.find((one) => one.lens === lens)
    return (
      <Box flexDirection="column">
        <Button key="back" label="Lenses" onPress={() => update($, reviewLens, () => null)} />
        <Text bold>{shown === undefined ? lens : lensLabel(shown)}</Text>
        {findings.length === 0 && <Text dimColor>No findings.</Text>}
        {findings.map((finding, i) => (
          <Box key={`finding-${i}`} flexDirection="column">
            <Text key={`heading-${i}`}>{findingHeading(finding)}</Text>
            <Markdown
              key={`text-${i}`}
              text={e.surface === 'terminal' ? fitTables(findingText(finding), e.props.bodyColumns) : findingText(finding)}
            />
            <Button key={`quote-${i}`} label="Quote" onPress={() => fillPrompt($, quoteText(lens, finding))} />
          </Box>
        ))}
      </Box>
    )
  })
}
