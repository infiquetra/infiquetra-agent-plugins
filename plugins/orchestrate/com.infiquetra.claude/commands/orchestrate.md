---
name: orchestrate
description: Plan work across herdr agent sessions and run it — one worktree per unit, any configured agent, any saga capability
argument-hint: "<prompt> | #<issue> | #<parent> --children | <path/to/doc.md>"
---

Spread one piece of work across several agent sessions, decide together how to split it, then run
it. Each unit gets its own git worktree and branch, so sessions cannot overwrite each other.

## The layers

```
/orchestrate <input>
  └── lifecycle       one per issue — one input can carry several
        └── phase     /plan, /doc-review, /work, /code-review — the umbrella steps
              └── unit    one session, one worktree, one branch
```

A single issue is one lifecycle. A parent issue with children is one lifecycle per child, each with
its own phases. A phase is not always one unit: three vendors writing competing plans is one phase
and three units, and `/work` is one phase and however many units the plan calls for. Code Review is
the exception: its phase is one top-level controller unit, and that controller owns its lens work.

**Choices are made at the layer that owns them and inherited downward.** The operator picks which
vendors may be used at all. `/work` takes its vendors and path ownership from the plan, and the one
`/code-review` controller takes its lenses and external-reviewer seat from Code Review's contract,
not from an Orchestrate interview.

**Code Review is one controller, not one unit per reviewer.** Orchestrate launches and resumes that
controller, persists its typed result verbatim, and routes only the result's owner, touched paths,
and outcome. It never scores a lens or rebuilds Code Review policy.

## Phase 1 — read the input

| Argument | What to read |
|---|---|
| free prose | the prose itself |
| `#123` | that issue: title, body, labels, linked issues |
| `#100 --children` | the parent, then every sub-issue — one lifecycle each |
| a path ending `.md` | the document — a plan, a requirements doc, a brainstorm |

Read it before asking anything. Come to the interview already knowing what the work is, and say so
in a few lines: what the work actually is, where the real seams are, and where you think it does
*not* split well. That framing is worth more than any question you could ask instead.

## Phase 2 — interview the operator

**Recommend.** Every question carries your recommendation and one line of why. The operator is
choosing between options you have already thought about, not doing the thinking.

**Ask one question per turn** with `AskUserQuestion`. For an abstract fork, put a small worked
picture in the `preview` field — a table, a before-and-after, an arrow chain. Labels alone lose.

**A note attached to an answer is an instruction, not a comment.** The operator can press `n` and
write "use grok for the second plan instead of codex", or "qwen not opencode", or "drop the third
reviewer". Apply it, say in one line what you changed, and carry it into the table. A note that
contradicts the option they picked wins — they wrote it after seeing the options.

**If a question is declined, do not stall and do not re-ask.** Take the most defensible answer, say
in one line which you took and why, and continue. The table is the real gate and every row is
editable there.

**Say only what you can show from this repository and this issue.** Do not bring in remembered
opinions about a vendor — that one went idle once, that one is unreliable — from other work or
recalled context. The operator did not ask for a reputation report, it is not checkable from here,
and it quietly steers a choice that is theirs. Vendor commentary is limited to what `roster`
reports: whether the agent takes model and effort flags.

**Do not presume the shape of the plan.** These are the questions that usually matter, in this
order — not a checklist, and stop as soon as the answers determine the table:

1. **Is the WHAT settled?** A thin issue or a bare prompt may want `/brainstorm` or `/spec` first. A
   reviewed plan document does not.
2. **Which phases?** `/plan`, `/doc-review`, `/work`, `/code-review`, `/qa`, `/investigate` — or a
   plain prompt with no saga command at all. This is the question that shapes everything after it.
3. **Which vendors may be used at all?** Get the list from `python3 "$S" roster` — never from
   `agents --crews`, which is the operator's own saved workspace layout and has nothing to do with
   orchestration. `roster` reports the vendors orchestrate knows how to drive **that are available
   on this machine**; it is an intersection, and both halves matter. One allow-list for the whole
   orchestration, **not one vendor per unit**.

   **`roster` briefs you on every vendor it lists — read it rather than recalling how one works.**
   Under each vendor it prints both permission modes as they will actually be passed, whether saga is
   installed and how that vendor invokes it, and any behaviour that has caught a run out before. Each
   of those notes exists because a run went wrong and the knowledge lived nowhere, so it was learned
   twice.

   **Most vendors can be given a model and an effort.** Where the command line has no flag for it,
   the unit's `setup` carries a slash command instead.

    **opencode tier control uses an interactive picker.** Its effort is a *variant* — Default,
    minimal, low, medium, high, xhigh, max — chosen through `/variants`. Orchestrate drives the
    picker post-launch inside the Herdr session, selects the requested exact variant or the highest
    actually offered variant from the live choices when maximum available is requested, waits until the
    session is task-ready, and verifies the effective model and variant before task submission.

   **Offer the operator's own favourites first.** `python3 "$S" roster --models` lists the operator's
   favourites from `~/.config/orchestrate/models.json` at the top when that file exists, followed by
   the vendor's full live model catalog. Offer preferred models at the top for convenience, but treat
   them strictly as preference ordering rather than an allowlist or the exclusive option set. Absence from
   favourites never makes a model unsupported, and reordering or truncating favourites never changes
   which models are reachable.
   opencode alone fronts 164 models across eight providers; listing favourites first avoids noise while
   leaving every live catalog model reachable.

   **Model authority boundary: live catalog, never stale tables.** External worker and reviewer
   availability, exact model names, and effort or variant controls come **only** from the installed
   `agents` wrapper and vendor-native live catalogs or help — **never** from Fleet Commons tier data
   (`fleet_commons.tier_resolver`) or `~/.config/orchestrate/models.json`.

   - **Interview-time model discovery:** Run `python3 "$S" roster` to verify installed wrapper tools
     and `python3 "$S" roster --models` to query live vendor models and favourites. This check inspects
     the live catalog without creating worktrees, git branches, Herdr sessions, or run state.
   - **Herdr verification bounds:** Herdr proves only workspace, pane, working-directory (`cwd`), and
     readiness facts (`herdr agent list`), never models.
   - **Internal tier decoupling:** Fleet Commons retains internal Team Execution tier ownership and must never
     gate external Herdr routes.
   - **Provider route preservation:** `opencode-go` is an OpenCode provider (e.g.,
     `opencode-go/muse-spark-1.2-contributor`), not an agent kind (`opencode`). Exact provider/model
     identities and advertised variants are preserved verbatim.
   - **Refusal and no substitution:** `start` and `expand` refuse unknown vendors (`assert_vendors_available`);
     interactive variant selection refuses unadvertised OpenCode variants (`resolve_opencode_variant`); and
     `agent_argv` emits exact requested parameters with no silent substitution of model, provider, effort,
     account, or agent kind.

   **Never write a model name from memory.** Run `python3 "$S" roster --models`, which asks each
   vendor that can answer. `grok`, `agy`, and `opencode` can; `claude` documents its aliases in
   `claude --help` (`fable`, `opus`, `sonnet`, and full names); the rest cannot answer, and for
   those you ask the operator rather than guessing. `opencode` needs `provider/model`, not a bare name.
4. **Does `/plan` want competing plans?** One vendor plans by default. The operator may instead have
   two or three vendors each write a plan independently, in their own worktrees, with no knowledge
   of each other. If so, **this session reads all of them and writes the merged plan itself** — no
   merge unit, no extra tab. Say which parts came from where.
5. **Which review shape applies?** Independent `/doc-review` passes may still be separate rows when
   the operator asks for them. A `/code-review` phase is always one row with
   `role: "review-controller"`, using a vendor other than the builders. Do not ask for a Code Review
   reviewer count and do not turn lenses into Orchestrate units; Code Review owns both.
6. **Anything out of scope?**

Do **not** ask about `/work` vendors or `/code-review` lenses. Those come from the plan.
Do **not** ask about inline versus a workflow backend — orchestrate is always inline, and the plan
carries `"backend": "inline"` so every `/work` unit is told rather than asked. A dispatched unit is
already one of several parallel sessions; nesting a workflow inside one is the
orchestration-of-orchestration this plugin exists to avoid.

### Reviewer seats live in the run, not engine-prefs

The `.saga/engine-prefs.json` seam is retired (#776). A plan that still carries `engine_prefs` is
refused. Represent an external reviewer as a named unit with `role: "external-reviewer"` and the
vendor/model/effort Herdr will launch. When a Saga Code Review phase is present, Orchestrate refuses
plain review prompts, direct reviewer launches, and duplicate review units. Halt rather than falling
back to the retired saga runner.

**A unit is also told, whatever its capability, never to stop on a question.** Saga still asks about
destination, scope class, resume-versus-mint — and every one of those in a background tab is a unit
lost. The dispatched task carries the rule: take the most defensible option from a known set and say
which; for a real question about the work, write it into the output and stop, so this session can
bring it to the operator instead of a tab swallowing it.

The one `/code-review` controller runs its own lens consensus. Its lenses, acceptance, external seat,
cycle state, and typed outcome are its business, not something to rebuild here. Additional reviewer
seats are named Herdr sessions on the same expand/go path as every other unit. The interview does
not ask Orchestrate to decide review policy.

## Phase 3 — hand over the table

Show phases and policy. **Later phases have no units yet** — what `/work` splits into is decided by
the plan, which does not exist when the operator is reading this. Say so rather than guessing:

```
run <run_id>   <-  <what the input was>
vendors allowed: claude, codex, grok, qwen        document reviewers: 2; Code Review controller: 1

 phase  what it does                    saga cap       agent     model         effort  after     serialize
 -----  -----------------------------   ------------   -------   -----------   ------  -----     ---------
 p1a    plan #48                        /plan          claude    opus          high    -         -
 p1b    plan #48, independently         /plan          codex     gpt-5.6-sol   xhigh   -         -
 (merge of p1a and p1b happens in this session — no unit)
 p2a    tear up the merged plan         /doc-review    grok      grok-4.6      xhigh   p1a p1b   -
 p2b    tear up the merged plan         /doc-review    qwen      qwen3-max     high*   p1a p1b   -
 p3     build it                        /work          <from the plan>                 p2a p2b   -
 p4     review the build                /code-review   one non-builder                 p3        -
```

Rules for the table:

- **Match the agent to the work, not to habit.** Judgement, design and adversarial review want a
  stronger model; mechanical and survey work does not. One line of why if it is not obvious.
- **A reviewing unit is never the agent that produced what it reviews.** Do not hand a session its
  own output to bless.
- **One Code Review row only.** Give it `role: "review-controller"`. Give every Work row that may
  receive repairs `role: "review-fixer"` or `role: "downstream-resolver"` plus its
  repository-relative `paths`. A directory owns its descendants. Owner role and path overlap are
  the complete worker routing key; a unit name is never one.
- **Two ordering edges, one gate.** `after` and `serialize` both hold a unit until every name they
  list is done; units with no dependency run at the same time. What differs is what they *claim*,
  and the claim is all a reader has — so pick the honest one:
  - **`after` — I build on what you produce.** Use it when this unit reads what the other one
    writes: a reviewer after the thing it reviews, a builder after the plan it implements.
  - **`serialize` — I must not run beside you, but I need nothing from you.** Use it when two
    units would edit the same file, or when one must wait for the other to land before it can
    rebase.

  Reaching for `after` in that second case is wrong: it asserts a dependency that does not exist,
  and a reader can no longer tell a real one from a scheduling one — the run looks blocked for a
  reason that is not real.
- **Name a unit for what it does and who does it** — `plan-claude`, `plan-codex`,
  `docreview-grok`, `build-guard`. Not `p1a`. That name becomes the herdr tab title, the branch
  (`orch/plan-claude`) and the worktree directory, and it is what you read in `herdr agent list`
  when you come back to a screen of tabs.
- **Units run at `permission: auto` by default** — enough to do their own work without stopping to
  ask in a tab nobody is watching. Set `"permission": "bypass"` on a unit that needs a free hand.
- **Every vendor in the table must be in the allow-list** from question 3.
- **Every row carries a model and an effort.** A `*` marks an effort delivered by a slash command
  in `setup` rather than a launch flag — same result, different door. Never leave a tier blank.

Then ask to approve, edit, or cancel. **Nothing launches before the operator says yes.**

**Editing is plain language, not a form.** "Make p1b grok", "swap the two document reviewers",
"drop p2b", "opus on the builder", "add a third plan from qwen" — take it, redraw the whole table,
and show it again. Any cell is fair game, including which vendor sits in a competing-plan row.
Redraw rather than describing the change, so what they approve is what runs.

### Workspaces: one per lifecycle, once a run outgrows a screen

A herdr workspace is the unit of *attention*, not of isolation — isolation is the worktree. Below
about six concurrent units one workspace is fine and a second is overhead. Above that, a single
workspace becomes a wall of tabs whose names are the only thing telling them apart, and the operator
loses the ability to answer "what is waiting on me" at a glance.

**One issue is one lifecycle, and a lifecycle is the natural workspace.** A parent issue with nine
children is nine lifecycles: give each its own workspace, named for the child, and keep the
orchestrator in the umbrella workspace beside them. Then a phase's sessions are the tabs of one
workspace, and closing that workspace when the child lands is one action rather than nine.

Create one with `herdr tab create --workspace <workspace_id>`, and note that the agent wrapper's
`--workspace` flag takes a **name** rather than an ID: handed an existing workspace ID it creates a
new workspace called that, instead of joining the one you meant.

The run JSON carries that name as `workspace`. A run-level value is the default every unit inherits;
a unit may set its own `workspace` and that wins — no other precedence. Orchestrate emits it as
`--workspace <name>` before the vendor token, alongside `--task` and `--cwd`. Absent both, the
session lands in the caller's workspace. Do not put `--workspace` in `launch_args`: that position is
after the vendor token, and the wrapper then treats the flag as the vendor's, so the session lands
in the wrong workspace.

Below the threshold, do not do this. A three-unit run in four workspaces is worse than a three-unit
run in one.

## Phase 4 — run it

Write only the units that can actually launch now — the `<from the plan>` rows are not units yet and
do not belong in the JSON. `task` is the literal text sent to the session.

```json
{
  "run_id": "orch-2026-08-16-a",
  "source": "#48 deploy-guard remediation",
  "workspace": "issue-48",
  "units": [
    {"name": "p1a", "vendor": "claude", "model": "opus", "effort": "high",
     "launch_args": ["--company-account"],
     "task": "/saga:plan #48 — write the plan to docs/plans/<date>-<slug>.md and commit it",
     "after": []},
    {"name": "p2a", "vendor": "grok", "model": "grok-4.6", "effort": "xhigh",
     "task": "/doc-review docs/plans/....md", "after": ["p1a"]},
    {"name": "p2b", "vendor": "qwen", "model": "qwen3-max", "setup": ["/effort high"],
     "task": "/doc-review docs/plans/....md", "after": ["p1a"]},
    {"name": "runbook-claude", "vendor": "claude", "model": "opus", "effort": "high",
     "task": "write the detection-rules section of docs/deploy-guard-runbook.md and commit it",
     "after": [], "serialize": []},
    {"name": "runbook-codex", "vendor": "codex", "model": "gpt-5.6-sol", "effort": "xhigh",
     "task": "write the rollback-drill section of docs/deploy-guard-runbook.md and commit it",
     "after": [], "serialize": ["runbook-claude"]}
  ]
}
```

**`after` and `serialize` are the two ordering edges, and they gate identically** — a unit does
not launch until every name in both lists is done. What differs is what they claim:

- **`after` — I build on what you produce.** This unit reads what the other one writes: a reviewer
  after the thing it reviews, a builder after the plan it implements. `go` refuses to launch it
  when the dependency committed nothing, because there would be nothing to build on.
- **`serialize` — I must not run beside you, but I need nothing from you.** Two units that would
  edit the same file, or one that must wait for the other to land before it can rebase.
  `runbook-codex` above is that case: it never reads a word of what `runbook-claude` wrote — it
  only refuses to edit the same document at the same time. `go` never asks whether a `serialize`
  dependency committed anything.

Using `after` for the second case is wrong: it asserts a dependency that does not exist, and a
reader can no longer tell a real one from a scheduling one. `status` prints which kind of edge
holds each pending unit.

**`launch_args`** carries extra arguments for the launcher, passed through untouched. `model` and
`effort` are what every vendor has in common; this is everything else the wrapper knows.
`--company-account` is the case that needs it: the wrapper intercepts that flag and swaps the
configuration directory before the tool starts, so it never appears in the tool's own `--help` and
cannot be expressed any other way. Orchestrate does not check these against a list of its own — the
wrapper releases on its own schedule, and it already rejects by name what it does not accept. Write
what the operator asked for; let the launcher answer.

**`account`** selects the account identity (`company` or `personal`). When set to `company` (at the plan
or unit level), Claude units emit `--company-account` after the vendor token. Before submitting the task
Orchestrate reads the account back off the session — its statusline first, the transcript root
(`~/.claude-company/projects/` vs `~/.claude/projects/`) as the fallback — and fails the unit loudly
(`account_mismatch`) on a wrong account, an unreadable one, or an account value it does not know.

**`merge`** defaults to `true`, and `false` means "this branch is to be read, not merged." Set it on
competing-plan rows: several planners writing their own version of the same document cannot be
merged by git without a conflict at best, and a silently interleaved plan at worst. `merge` then
skips them and says so by name, so a branch holding the only copy of something is never quietly left
behind.

Find the script first — the operator is rarely in this plugin's own repo, and `roster` in Phase 2
needs it too:

```bash
S="${CLAUDE_PLUGIN_ROOT:-.}/skills/orchestrate/scripts/orchestrate.py"
```

Then, from the operator's repo:

```bash
python3 "$S" roster                                # what this machine can launch
python3 "$S" start --plan .orchestrate/plan.json   # run branch, then a branch per unit
python3 "$S" go                                    # launch everything eligible
python3 "$S" wait                                  # block until one settles (herdr events)
python3 "$S" settle                                # sessions with branch evidence become done
python3 "$S" land                                  # finished units -> the run branch
python3 "$S" go                                    # the next phase, now able to see their work
python3 "$S" review-result --file <result.json>     # persist the controller result and route repairs
python3 "$S" clean --merged --branches             # close what has landed
```

**`check` before you `merge` (and `status` for live drift).** The run file is written only by this
script, and only for actions this script performed — so a session started by hand leaves a branch
nothing will ever land or reap, and nothing notices. `check` compares the record against git and
herdr and names every disagreement: a branch with no unit, a unit marked done that committed nothing,
a unit marked done whose work is not on the run branch, a session that vanished, a session still
working. `status` also reports unrecorded unit branches on every poll. They write nothing, and `check`
exits non-zero when it finds something.

```bash
python3 "$S" check                                 # does the record still describe reality?
python3 "$S" adopt                                 # what would it take back?
python3 "$S" adopt --yes                           # take it back
python3 "$S" park --unit <name> --evidence "<err>" # record push-succeeded / PR-blocked unit
python3 "$S" resume --unit <name>                  # open/adopt missing PR and continue run
```

`adopt` is the repair for a branch with no unit. It rebuilds the row from the branch, its worktree
and the session sitting in it, and leaves `task`, `after`, `serialize`, `model` and `effort` empty
rather than inventing them — the session already has its task, and nothing is ever sent to it
again. Once adopted, the work is visible to `merge` and `clean` like any other unit.

**`park` and `resume` for push-succeeded / PR-creation-blocked recovery.** When a worker pushes its
branch successfully but cannot create its pull request (e.g. rate-limited or blocked by session
permission mode), the coordinator records the unit in the typed `parked` state with
`park --unit <name> --evidence <text>`. The parked state is recorded only after the pushed commit is
verified on the remote branch (`git ls-remote`), capturing the verified remote head, authoritative
base, unit identity, frozen revision, and failure evidence. A failed push never enters this path. To
resume, run `resume --unit <name>`: it idempotently opens the missing PR or adopts an existing
matching one and advances the unit to `done`, continuing the original run without a second run or
rewritten evidence. A missing or changed remote head fails loudly without mutating the run record.

`python3`, not `uv run` — the script imports nothing outside the standard library, and the target
repo may not be a uv project at all.

**Append-only files conflict when a phase is wide.** Nine planners each adding an entry to the same
engineering journal is nine appends at the end of one file, and git calls that a conflict on every
land after the first — even though every entry is distinct and all of them should survive. Git has a
built-in answer, and it is local and uncommitted:

```bash
printf 'docs/engineering-journal/*.md merge=union\n' >> .git/info/attributes
```

Union merge keeps both sides of an append-only file with no markers. Use it for journals and
changelogs; do **not** use it for source, where keeping both sides of a conflict is how you get code
that compiles and means something nobody wrote.

**`clean --merged` belongs after every `merge`, not once at the end.** A phase's sessions are
finished the moment their work is on the run branch, and leaving them open for the rest of the run is how
a workspace ends up with a dozen idle tabs nobody can tell apart. `--merged` only ever closes a unit
whose work survived, so it is safe to run unattended — a unit that landed nothing keeps its tab and
its worktree, because those are the evidence.

**`merge` is not optional and it is not cleanup.** It is how a phase becomes real to the next one.
Units branch from the run branch, so a reviewer can only find a plan there if the planner's work was
landed first — the way a team pushes back to the feature branch rather than reading each other's
branches. Skip it and the next phase opens on nothing and writes something plausible about nothing.

`merge` also names any unit that finished without committing. That is the failure worth seeing: not a
missing merge, but a session that produced nothing and reported itself done.

Between `go` and `settle`, use `wait` — it blocks on herdr's event socket rather than polling, then
confirms idle the same way `settle` does (`--interval`, `--confirmations`, `--once`). A single
`idle` is the gap between turns, not a settlement. `blocked` returns promptly and is named.

## Phase 5 — expand at each phase boundary

When a phase finishes and it is the one that decides the next phase's units, read what it produced
and bring the operator a table for **those rows only**:

1. `settle`, then read the finished phase's output from its worktree — for `/plan`, the plan
   document it wrote.
2. Derive the next phase's units from it: what `/work` splits into, which vendor and tier each piece
   wants, what depends on what. The plan is human prose; read it and propose. If it is vague, say
   so and propose the best reading — the operator is about to edit it anyway.
3. Show that table alone. Approve or edit.
4. Append and launch:

```bash
python3 "$S" expand --plan .orchestrate/expand-p3.json
python3 "$S" go
```

`expand` refuses a name already in the run and a dependency that is in no run, so a bad table fails
before anything launches.

**Never create worktrees manually or invoke `agents` directly for a run unit.** Every unit — whether
in the initial plan or added at a later phase boundary — must be persisted through `start` or `expand`
before any worktree or session is created, and must launch only through `go` via the shared
`agent-launcher` `agent_argv` path. Bypassing `expand` or `go` by calling `agents` directly breaks run-record tracking,
omits background launch flags (`--no-focus --current --herdr --herdr-control-only`), and steals
operator focus. Unsupported post-launch setup (such as interactive OpenCode variant selection) is a
controlled post-launch step performed inside the launched session; it does not authorize bypassing
`expand` or `go`. A branch in the run's `orch/<run-id>-<unit>` series with no row in the table is
flagged as unrecorded drift by `status` and `check`, requiring explicit adoption with `adopt --yes`
or run-owned cleanup rather than being silently treated as valid expansion. That detection reads
branches and nothing else: a hand-made worktree or session named outside that series is invisible to
both commands, which is the second reason never to make one.

When the expansion includes Work and Code Review, make ownership executable in the rows themselves:

```json
{
  "units": [
    {"name": "build-api", "vendor": "claude", "task": "/saga:work docs/plans/x.md",
     "role": "review-fixer", "paths": ["src/api", "tests/api"], "after": ["docreview"]},
    {"name": "review-controller", "vendor": "grok", "task": "/saga:code-review the build",
     "role": "review-controller", "after": ["build-api"], "merge": false}
  ]
}
```

`start` and `expand` refuse a second Code Review controller. They also refuse a Work routing role
without owned paths, because a role alone cannot select the responsible worker.

### Collect and route the typed review result

The Code Review controller emits one complete typed result. Preserve its exact UTF-8 bytes in a file
and merge it by turn:

```bash
python3 "$S" review-result --file .orchestrate/review-result.json
```

The command stores the complete string in the per-issue run record before it reads any route. It reads only the
routing envelope: `outcome` plus each fix request's identity, `owner`, and `touched_paths`. It never
imports Code Review's scorer, derives an overall, applies an acceptance threshold, counts cycles, or
treats finding priority or confidence as another gate.

For `review-fixer` and `downstream-resolver`, role plus path overlap selects a still-live Work worker.
That worker is told to merge the current run branch first, receives the request in its existing
session, and is protected from cleanup until the repair lands. If no matching worker remains live,
Orchestrate creates a replacement from the matching role's approved vendor, model, effort, and
permission configuration; run `go` to launch it.
For `human` and `release`, the command prints and persists `OPERATOR ACTION` and creates no Work unit.

After every routed Work request has landed, `merge` resubmits the exact landed revision through the
same Code Review controller. Any outstanding human or release request prevents that resubmission;
Orchestrate never pretends operator-owned work was repaired.

**Competing plans are read, not merged by git.** When `/plan` ran in several vendors' worktrees, open
each one's plan document directly and write the merged plan yourself. Do not `merge` those
branches into each other. Say so in the plan — `"merge": false` on each of those rows — rather than
remembering it at `merge` time. `merge` has no other way to know, and it merges everything finished
that does not say otherwise.

## Board writeback — what `merge` and `announce` do to a card

A run file may carry an `issues` mapping (unit name to `owner/repo#N`) and an optional `status_map`.
With it, `merge` writes each unit it merged back to that unit's issue card, and `announce` is the
door for the boundaries `merge` does not cover. Without an `issues` mapping this is a no-op and
nothing about the run changes.

**Orchestrate never writes GitHub.** Every write is a submission through saga's
`reconcile_controller`, which owns the certificate gate and the replay key and stops at Mission
Control's `flow set-field --correction`. Mission Control alone executes.

**A move is a `(Stage, Status)` pair.** A unit's name prefix picks the rung: `plan` and `docreview`
land in `Planning`; `work`, `fix` and `codereview` in `Active`. That is all five. Nothing reaches
`Verify` or `Retro` — those begin only after conditions a run cannot observe — and a `status_map`
override naming either stage is refused at submission, not merely absent from the default map.

**Install saga 0.151.0 or later, mission-control 2.15.1 or later, and agent-launcher 1.4.0 or later before relying on this.**
Both floors are declared in `plugin.json`; saga's is enforced — a saga below its floor is
refused before any submission, because an older saga silently drops the `Stage` half and reports
success. The agent-launcher floor is enforced at runtime as a command-by-state matrix:
`--help` survives a stale or missing companion, `status` and `check` degrade to
liveness-unknown when it is missing or unusable, and the seven pane-write, session-create or
tab-close commands -- `start`, `expand`, `go`, `review-result`, `merge`, `clean`, and `go` (a relaunch builds a fresh worktree) --
refuse with an update or install remedy. `roster` and `saga` write nothing, so a stale companion still
serves them; only a missing or unusable one refuses them. The mission-control floor is a
declaration the installer reads.

Read the exit code, not the prose. `merge` and `announce` both exit **2** when a card was not
updated, and every failure prints its reason and whether a retry can clear it. `merge`'s full
exit-code table:

| Exit | Meaning |
|---|---|
| 0 | Every unit that was ready merged and any owed review resubmission was made. |
| 1 | The merge into the run branch could not complete: a conflict worktree is retained or the landing ref could not be updated; the reason and the retained path are printed and the unit is left untouched. |
| 3 | Merges landed but a landing worktree could not be removed. Not returned when exit 4 also applies. |
| 4 | A review resubmission that was owed was not made: the prompt failed, the controller's composer held staged input, or operator-owned fix requests held the resubmission. Outranks exit 3. |

The codes are pinned against the command's own return statements by a test. Exit 2 is retired: it
meant "merges landed but a board card was not updated", and this command no longer writes to a
board at all — saga submits each lifecycle boundary itself, through mission-control's constrained
mutation (issue 1028). Giving a retired code a new meaning would silently change what an existing
caller reads, so it is gone rather than reused.

## Phase 6 — report

What each unit produced, and what merged. If a session went idle without doing the work, say so
plainly — an idle session is not a finished one, and `status` shows both the recorded state and what
herdr says right now. A unit sitting at `blocked` is waiting on a question in its own tab.

## Things this command deliberately does not do

It does not verify that a session "really" finished, count anyone's tokens, enforce a budget,
reserve concurrency slots, run its own voting panel, or keep a durable register. If a unit went
wrong you have its worktree, its branch, and its tab — look at them.
