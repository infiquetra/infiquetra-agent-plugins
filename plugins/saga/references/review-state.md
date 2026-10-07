# The review-state document — `review_state.v1`

One saga script writes a code review's state and pending choices as one
document. Every screen reads it, and every answer goes back through the
script. Added by issue 164, card C13 of the review redesign (parent
issue 147).

The script is `scripts/review_state.py`; this document is its contract. The
document is rendered on demand from the stored C1 review runs, the way
admission renders its tables — no file is kept, so the two prints cannot
drift. Grades, severities and the merge answer come from C1's stored values;
the script derives only presentation.

## The three verbs

```bash
python3 plugins/saga/scripts/review_state.py render --record <path> --envelope <env> [--render json|markdown]
python3 plugins/saga/scripts/review_state.py answers --record <path> --envelope <env> --answers - [--profile P] [--mission-control M]
python3 plugins/saga/scripts/review_state.py publish --record <path> --pr <N> --repo <R> [--round N]
```

`--record` names an explicit record file (tests); `--issue N` with
`--store-root` reads the run-record store instead. `--envelope` names a
validated intent-envelope JSON file; with `--issue N --repo R` and no
`--envelope`, the script reads the issue body's one fenced envelope block via
`gh`. Either way the envelope is validated through the closed key set — an
unknown field, a wrong version, run mode or merge gate is refused — and saga
asks no second run-start question.

Exit codes are the shared table: 0 ok, 2 any refusal (something that cannot
run, or an answer that cannot be recorded), 3 an unknown record version.

## The document

`render --render json` prints the `review_state.v1` document:

| Key | Holds |
|---|---|
| `schema` | the version token, `review_state.v1` |
| `card`, `repo`, `round` | the reviewed card, repository and newest round |
| `lenses` | one entry per lens: `lens`, A–F `grade`, `blocking` and `fix_later` counts |
| `findings` | the newest run's findings: `id`, `lens`, `severity`, `statement`, `guard`, `merge_outcome` |
| `pending_choices` | choice keys: `merge-blocking` when pending, then one `fix-later:<id>` per fix-later item |
| `merge_blocking` | the enforced blocking identities the merge question covers |
| `merge` | `{waiting, reason}`: whether the merge waits, and why |
| `disputes` | identities disputing a builder declaration |
| `consequence_disagreements` | `{id, llm, jev}` where the two consequence picks disagreed |
| `unconfirmed` | identities whose Jev pick never arrived |
| `where_to_look` | each item's location, state (`answered` with the finding identity, `cleared` with the reason) and fired questions |
| `tools` | `ran` tool versions, C3's `missing_notice` text verbatim, `missing_tools` |
| `degraded_inputs` | the newest run's degraded inputs |
| `rounds` | per round: `new_blocking` and `cleared_blocking` identities against the round before |
| `cost` | tokens, dollars and seconds summed across the stored runs |
| `unattended` | true, false, or null when no envelope was read |

With no review runs the document is the schema plus empty lists. `render
--render markdown` prints the same lenses, items and choices as fixed
Markdown: bold titles, never headings; one `**Items**` bullet per finding
starting with its identity; and the pending choices as numbered questions,
each ending in `(answer: <choice-key>)`.

## Pending choices and the merge display

The blocking question exists only over blocking items left at the round
limit (round 3) or an early stop (a round that leaves the same blocking
identities): merge with a recorded reason, or stop the card. Each fix-later
item carries its own choice. The merge waits when the blocking question is
pending — under either merge setting, since only the operator can answer it —
or when the envelope's merge gate says `gate`. With `auto` it is free to
proceed only once the newest run's merge answer allows it, so an unattended
merge never lands on open blocking items. Fix-later choices never hold a
merge. Without an envelope the setting is unknown, so the merge waits rather
than guessing.

## Answers

```json
{"answers": {"fix-later:<id>": "leave", "merge-blocking": {"decision": "stop-card"}}, "pane_timeout": false}
```

Fix-later choices are `fix-now`, `file-as-issue` or `leave`; the merge answer
is `merge-with-reason` with a non-blank reason, or `stop-card`. Validation
runs over the whole file before anything writes: an unknown key or choice, a
reasonless merge over blocking items, and a second answer contradicting a
recorded outcome are each refused unrecorded with exit 2 and one line naming
the key. Recording then applies answer by answer under the record lock.
Outcomes land on the finding's C1 `merge_outcome` — `fixed-now`, `filed`
with the issue number, `left` — with the stored run re-validated; the merge
decision is appended as a `review_cycles` entry with
`loop: "merge_confirmation"`, which C10b reads to carry out or hold the merge.

A pane that timed out sends `"pane_timeout": true` with an empty answers
map; the script applies the unattended rules itself. A timeout beside a
non-empty map is refused: the answers come from the harness, which this card
treats as untrusted. Unattended — the envelope's run mode, or a timeout —
files nothing apart from the security guard, and `file-as-issue` answers are
recorded `left` with the reason `unattended`. A `merge-blocking` answer under
an unattended envelope is refused unrecorded: only the operator can merge
with a reason or stop the card, and in an unattended run no operator is
present.

An empty answers map from an attended run means "nothing more to say": with
the `file` unattended default it files the follow-up bundle (below). Partial
answers never bundle, so the operator keeps choosing until confirmation.
Unless `--profile` names an explicit file, the unattended default comes from
the base commit's profile; a head change to the key is ignored and noted.

## Filing

`file-as-issue` files at once through mission-control in three steps, run
with a fresh temporary directory as the working directory: `issue prepare`
with a complete defect body, the `stage:` fill-in on the generated draft
(the value the filer's routing constants pin), then `issue create-prepared
--yes --skip-approval`. The created number is taken from the success JSON,
or re-read from the sidecar's `created_issue_number` on any other exit; a
call that already created an issue is recorded and never retried. Anything
else refuses the answer unrecorded with mission-control's message. The
routing (team asgard, project operations, and the stage and status this
program's own cards carry) is what the filer passes to prepare.

The security guard files a harm the security lens's large language model
traced but could not reproduce, attended or not, unless the operator chose
fix now for that item; a recorded `left` is upgraded to `filed` with the
new number, so the record reflects that an issue exists. With the `file`
unattended default, an attended confirmation files one follow-up issue
listing every fix-later item still unanswered or `left`, and records each as
`filed` with the bundle's number.

A process that dies between mission-control creating an issue and the
outcome landing on the record leaves that issue unrecorded; the next answers
call files it again. The window is milliseconds wide, and no quieter failure
exists: a refused filing always names its cause.

## Publication

`publish` posts one `gh pr comment` per round and never `gh pr review` in
any form. A round is final at all clear, at the round limit, or at an early
stop. Only the final comment opens with `<!-- saga:fix-later-checklist -->`
and carries one `- [ ] <finding-id> <statement>` checkbox per fix-later
item; C16's outcome job matches the marker and edits filed boxes to link
their issues. A failed post records nothing, so a retry posts once.
