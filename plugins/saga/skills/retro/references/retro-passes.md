# Retro passes — the multi-pass procedure

The ordered procedure `/retro` runs. Every world-touching command here is **read-only**; every edit that
is not a pure-append new journal entry is **propose-diff-and-wait** (`self-edit-safety.md`).

---

## Pass 0 — Stale-base / wrong-today BLOCK guard (pre-flight, time-windowed mode only)

Ported from gstack `retro`'s Step 0.5. A time-windowed retro computes a window from "today" and queries
git over it; if "today" drifted or the local base is materially behind, the window returns near-zero
commits and the retro fabricates a confident narrative from nothing. Run the pre-flight in this exact
order — the first branch that matches wins:

1. **No `origin` remote?** → skip, disclosed: "base freshness not verified — proceeding".
2. **Detached HEAD / no current base?** → skip, disclosed: "detached HEAD, freshness not verified".
3. **`git fetch origin <default>` fails (offline)?** → warn, disclosed: "offline — proceeding against
   last-known origin/<default>".
4. **Fetch succeeded** → read the newest `origin/<default>` commit date and compare to the window.

```bash
git remote | grep -qx origin || echo "RETRO_GUARD: no origin — proceeding"
git symbolic-ref --quiet HEAD >/dev/null 2>&1 || echo "RETRO_GUARD: detached HEAD — proceeding"
git fetch origin <default> --quiet 2>/dev/null || echo "RETRO_GUARD: offline — last-known base"
git log -1 --format=%ci origin/<default> | awk '{print $1}'   # latest-commit ISO date
```

**Compute today from the session reminder's `## currentDate`, NEVER from `date`** — a containerized clock
can be hours off. If the latest-commit date is older than `(today − window)`, **BLOCK**: state the latest
commit date, the window bounds, the two likely causes (today is wrong in this session, or the base is
behind the remote), and `AskUserQuestion` (confirm today / re-fetch and re-run / proceed-anyway). If the
model cannot reliably compute "today", it **stops here and asks** rather than proceeding.

The disclosed skip paths all proceed, carrying their one-line reason into the retro narrative
("offline run, window not freshness-verified"). **Thread-scoped retros skip Pass 0** — they compute no
window; instead verify the saga / PR evidence is at the current HEAD (a stale-thread analogue).

---

## Pass 1 — Lean git metrics + diff-vs-last (solo-framed)

A **lean subset** of gstack's forensics. **Solo-framed** — the gstack team-performance framing
(leaderboard, praise, streaks, tweetable, global, week-over-week) is **SHED**. Report **in prose**, not a
metrics table. Keep:

```bash
# scope of the window (thread-scoped: use the branch / PR range instead of --since)
git log origin/<default> --since="<window>" --format="%h %s" --shortstat
# files / hotspots touched
git log origin/<default> --since="<window>" --name-only --format="" | grep -v '^$' | sort | uniq -c | sort -rn
# test-vs-prod balance (one ratio, not a per-author breakdown)
git log origin/<default> --since="<window>" --name-only --format="" | grep -E '(test|spec|_test)' | sort -u | wc -l
# PRs referenced in the window
git log origin/<default> --since="<window>" --format="%s" | grep -oE '#[0-9]+' | sort -u
```

**Diff-vs-last.** Read the most recent prior `docs/retros/*.md`; report the delta (what moved since the
last retro — new hotspots, resolved blockers, recurring friction). This is the compounding mechanism: the
retro accumulates instead of repeating.

---

## Pass 2 — Saga trajectory + gh evidence (READ-ONLY)

```bash
python3 plugins/saga/scripts/saga.py ticks --saga-id <issue-N|task-slug>   # whole tick chain
python3 plugins/saga/scripts/load_saga_context.py --repo <owner/repo> --issue <N>
gh pr view <N> --json title,state,reviewDecision,mergedAt   # read-only
gh pr checks <N>                                            # read-only
gh issue view <N> --json title,state,labels                # read-only
```

`ticks` shows how the phase advanced, when blockers cleared, which questions got answered. Use **only**
read subcommands of `gh` — never create / edit / merge.

---

## Pass 3 — Transcript-review fan-out (context-safe)

Reuse the transcript-forensics substrate, file-mediated. The orchestrator **never reads a raw `.jsonl` or a
skeleton file** — paths only.


**Fan-out (optional, offered).** When several sessions warrant parallel synthesis, **OFFER** a backend per
`../../../references/operator-choice.md` and dispatch **one generic agent per session** (`Explore` / `Task` —
this plugin has **no `agents/` dir**). Pass the scratch **paths** + guardrails as prompt text: read ONLY
these paths, never read raw `~/.claude/projects/`, never reproduce tool I/O or thinking blocks, synthesize
*what was tried / what didn't work / key decisions / related context*. This is CE `ce-compound`'s
parallel-research pattern applied to the transcript evidence.

---

## Pass 4 — Interview question bank (grounded in Pass 1-3 evidence)

Free-form for substance; `AskUserQuestion` for choices. Anchor every question in evidence. The bank:

- **What shipped?** — confirm the evidence's read of the outcome (what users / the system got).
- **What surprised you?** — the thing that was not in the original mental model.
- **What slowed the work?** — friction, dead ends, re-rounds (cross-check the saga's round count).
- **What evidence mattered?** — which signal actually drove a decision (steer future retros to it).
- **What should change?** — the lifecycle / directive / skill gap this thread exposed.
- **Recurring?** — has this friction shown up in a prior retro (diff-vs-last)? If so, it is a Pass 5(a)
  new-skill candidate.

---

## Pass 5 — Journal promotion + curation

**Promote (AUTO, pure-append):** new entries to `LEARNINGS.md` / `DECISIONS.md` / `QUEUED.md` /
`ARCHIVE.md` (templates in `retro-report.md`).

**Curate (PROPOSE-DIFF-AND-WAIT) — the gstack-`learn` sweeps:**

- **Staleness** — for each entry with a file / PR / SHA reference, check it still exists (Glob for files;
  `gh` for a PR; `git cat-file -e` for a SHA). Flag "STALE: [entry] references deleted [path]".
- **Contradiction** — two entries on the same topic / key with opposite insight. Flag
  "CONFLICT: [topic] — [insight A] vs [insight B]".
- **Dedup** (the **infiquetra addition** — in gstack this was a Stats *display* op, not a Prune sweep):
  near-duplicate entries collapsed into one.
- **Journal-rule enforcement** — `MEMORY.md` over the ~24.4KB size rule, an over-long index entry whose
  detail should move to a topic file, an entry missing the **Generalizable rule** line.

Each flagged item → a diff + `AskUserQuestion` (apply / skip / modify). A `QUEUED → ARCHIVE` move deletes
from `QUEUED.md`, so it is propose, not auto.

**Mark transcendence (PROPOSE-DIFF-AND-WAIT) — the cross-repo `promote` feeder.** Walk the
`**Generalizable rule.**` lines this retro touched (just-promoted entries + any the interview flagged as
cross-cutting). For each, strip the repo-specific nouns and test "would this rule still be true and useful
in a repo of a different stack or domain?" Mark only the **select few** that pass — the sparing declare
feeder; the `promote` recurrence net (legacy-rule clustering across repos) catches the rest. The proposed
edit inserts exactly one canonical line directly below the rule, gated (diff + `AskUserQuestion`
apply / skip / modify; channel session: inline the choice):

    **Generalizable rule.** <the rule, unchanged>
    **Transcendent.** <one line on why it holds in a repo of a different stack/domain>

- **Idempotent** — skip any rule already followed by a `**Transcendent.**` line (a human may have declared
  it; the contract lets both write it). Never double-mark.
- **Single-repo boundary** — writes the marker into **this** repo's journal only. No cross-repo read, no
  clustering, no `infiquetra-context-library` write — those are the `promote` skill. The marker waits in
  place for the next `promote` run.
- **Source of truth** — the canonical marker form + the drift-stable `<repo>:<hash>` source key are frozen
  by the promotability rule in `../SKILL.md`; the recurrence-net feeder and the gated upsert
  live in the `promote` skill (do not reimplement them here).

---

## Pass 6 — Meta-improvement passes (net-new; ALL propose-diff-and-wait)

The passes neither source had:

- **(a) new-skill / plugin detection** — repeated friction (esp. flagged recurring in Pass 4) that a new
  skill or plugin would remove → propose a `QUEUED.md` entry or a `mission-control` issue.
- **(b) refine-lifecycle** — propose diffs to the saga SKILLs when the thread exposed a
  gap or a wrong instruction (including `skills/retro/SKILL.md` itself — proposal only, never
  self-applied).
- **(c) refine-directives** — propose diffs to the **repo `CLAUDE.md`** (in-repo, repo-relative) or the
  **global `~/.claude` directives** (global / cross-project, carries the cross-project warning — see
  `self-edit-safety.md`).
- **(d) memory pruning** — propose curation of the `.claude` auto-memory (`MEMORY.md` + topic files) under
  the same staleness / contradiction / rule-enforcement sweeps as the journal.

A **big multi-file refactor** surfaced by any pass → **OFFER** a backend (operator-choice). **Never
auto-run** it, never auto-launch a destructive self-edit.

---

## Pass 7 — Route

Surfaced follow-ups → `mission-control` (becomes an SDLC issue) or `QUEUED.md` (durable backlog). Route per
No saga write; `/retro` is terminal and
saga READ-ONLY.
