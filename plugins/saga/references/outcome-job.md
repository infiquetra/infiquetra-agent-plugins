# The review-outcome job — `outcome_job.py`

A daily launchd agent links later defects and reverts to the review runs that passed their
lines, queues them where the corpus screening reads, files fix-later boxes ticked after
review, and posts each completed run's addressed rate. Issue #167.

The job never runs from a repository under review: every pass changes to its state directory
first and reaches each checkout through explicit paths. Keys come only from the process
environment at fire time, through `keychain-env emit`; the installed agent holds no key.

## State and the checkout map

`<home>/.saga/outcome-job/` holds `state.json` (`outcome_job_state.v1`), `repos.json`
(`outcome_job_repos.v1`) and the launchd logs. Both files are owner-only, written through a
same-directory temporary file that is flushed and moved over the target, so a crash leaves
the previous journal intact. The full in-memory state persists after each side effect as
well as at pass end.

`state.json`:

| Key | Meaning |
|---|---|
| `last_pass` | The previous pass's start, Zulu. The window reaches 24 hours past it. |
| `index` | The accumulated trace index: trace id to `repo`, `base`, `head`, `card`, `round`, `timestamp`. |
| `processed_defects` | `repo#issue` keys already linked. |
| `processed_reverts` | `repo:sha` keys already linked. |
| `queued_qa` | `trace:revision` keys already queued. |
| `pending_qa` | `/qa` misses waiting for their repair to land. |
| `claimed` | Filings journalled before mission-control answered, by `repo#card:finding`. |
| `filed` | Filings journalled done, by `repo#card:finding` to issue number. |
| `addressed_posted` | Trace ids carrying an addressed-rate score. |
| `failures` | This pass's per-key failures. |

`repos.json` maps each `owner/name` slug to its `checkout` path and `added` time. `register
--repo-root PATH` validates the checkout and its GitHub origin and upserts the mapping, so a
moved repository re-registers cleanly; `register --remove --repo-root PATH` drops a mapping
whose remote is permanently dead so it stops pinning the window.

## The seven stages, in order

`run` executes fetch checkouts, refresh the trace index, link defects, link reverts, resolve
`/qa` misses, file ticked boxes, post addressed rates. Listing and fetch failures never abort
the pass: every other stage runs on best-available data. The window advances only when every
listing and fetch completed; anything less leaves `last_pass` where it was, and the overlap
plus the processed sets make the retry safe. A second concurrent pass exits 2 on the state
lock.

1. **Fetch** each mapped checkout's default branch (`origin/HEAD`, else `main`, else
   `master`). A failure skips that repository and blocks the window.
2. **Refresh the trace index** from the Langfuse trace listing, accumulated across passes.
   Only code-review traces (repo, head, card, round all present) ever receive scores.
3. **Link defects**: closed `defect` issues updated in the window, paged until a page
   is short or older than the window, through their closing pull requests. Each link posts
   one `found-after-merge` miss and appends one queue record.
4. **Link reverts** from `git log --no-merges` on each default branch over the window,
   matching the revert subject rule case-insensitively, then following the defect path from
   tracing on. Each link posts one `reverted` miss and appends one queue record.
5. **Resolve `/qa` misses**: `found-by-qa` scores pend until the record's merged release
   descends from the tested revision, then queue with the release's pull request or commit.
6. **File ticked boxes** (below).
7. **Post addressed rates** (below).

The run prints a summary of counts and skip reasons, and exits 1 when the window held or
anything failed.

## Tracing and its skip reasons

A fix is traced by K1's removed-line method, reimplemented here without importing corpus
code: blame the fix's removed lines on the fix's parent and resolve each blamed commit to a
pull request by `(#N)` subject or `gh pr list --search`. A fix links only when every traced
commit agrees on one introducing pull request that is not the closing pull request.

- A merge-commit fix resolves to its non-merge branch range; a commit with nothing to
  blame casts no vote, and the fix skips as add-only only when no commit traced at all.
- A squash tip whose subject carries its own pull request number traces itself; anything
  else reads the pull request's commits from `gh` and needs every one resolvable locally.
- The introducing pull request's reviewed head comes from the stored run, cross-checked
  against the final review comment. With no stored release there is no trusted head: a
  comment alone never attributes a miss.
- Only the review-posting account's checklist counts: the account that posted the earliest
  marker comment is pinned, and later marker comments from anyone else are ignored.

Routine skips, each named in the summary: `closed-without-pr`, `closing-pr-unmerged`,
`add-only`, `spans-pull-requests`, `pr-unknown`, `in-pr-repair`, `fix-partially-visible`,
`no-reviewed-head`, `head-mismatch`, `ambiguous-release`, `no-matching-trace`. Infrastructure
(`defect-list-failed`, `fetch-failed`, `comments-unreadable`, `blame-failed`, `pr-lookup-failed`
and the other listing faults) blocks the window and exits 1 instead.

## The queue

Each link appends one JSON object per line to K1's
`~/.local/share/saga-review-corpus/queued-candidates.jsonl` (`--queue` overrides it for
tests): `source` (`/qa`, `defect issue` or `revert`), `repository`, `review_run_id`, and the
fixing pull request as an integer and/or the fixing commit — a merge fix queues with the
closing pull request number only. Every line is validated against the mirrored reader rules
before writing, and an identical line already present skips instead of duplicating, so a
re-derived append after a crash never duplicates. One malformed line aborts K1's whole
screening read, so an invalid record is refused loudly instead.

## Filing crash order

For each mapped record with a release pull request, the job reads the newest stored run's
fix-later findings still `left` and the pull request's final checklist comment from the
review-posting account (see above). Each ticked, unlinked finding files through
mission-control with C13's title, body and risk, then the finding flips to `filed` under
the record lock, its `merge-outcome` score posts, and the comment gains `→ #<n>` on the box
line.

The journal order is crash-proof: journal `claimed`, file, journal `done` with the issue
number immediately. A refused filing records nothing and the run exits 1 at the end. Stale
claims reconcile at pass start by exact-title issue search: the hit whose body carries the
finding identifier is adopted, a clean miss refiles, and a failed search holds the finding
for the pass. A journalled finding whose record is still `left` flips, posts and links
without refiling; a box already carrying a link flips and posts with the linked number; a
record already `filed` is skipped silently.

## The addressed rate

Each round's trace whose run carries a finding outcome on every finding — from the run
record, which alone shows a missing outcome — gets one NUMERIC `addressed-rate` score: fixed
plus fixed-now plus filed over all findings, rounded to four places, with the per-outcome
counts and the total in metadata. Runs with a missing outcome or no findings get none. A
filing on the newest run reposts that run's score through the same derived identifier,
replacing it; older rounds never change after posting. No grade, pass mark or calibration
reader references the score; the suite pins that statically.

## The schedule and key handling

`/saga:setup` offers the `outcome-schedule` step only on macOS where `launchctl` exists, and
runs it only when the operator names it. `install-schedule` refuses without `launchctl` or
`keychain-env` on `PATH`, naming which. It writes
`<home>/Library/LaunchAgents/com.infiquetra.saga.outcome-job.plist` firing daily at 06:17,
unloads any previous copy, bootstraps the new one, and registers the installing checkout
when it is a git checkout with a GitHub origin. Reinstalling replaces in place.

The agent runs `/bin/sh -c` with a fixed body over positional parameters — keychain helper,
interpreter, script, home — so no path is interpolated into shell text. The body evaluates
`keychain-env emit --quiet` and executes the job; the plist holds no key and no
`EnvironmentVariables`. The working directory is the state directory, and the launchd logs
sit beside the state files. There is no `RunAtLoad`: the first scheduled fire is the job's
first run.

## Status and the launchd log

`status` prints one counts line — repositories, last pass, indexed traces, pending `/qa`
misses, filed boxes, posted rates, failures — plus one line per mapped repository, without
touching the network. Each pass appends its summary to the launchd logs in the state
directory: `skipped N (reason)` lines for routine attribution outcomes, `failed key (reason)`
lines for faults, and `window-advanced=yes/no` for the window.
