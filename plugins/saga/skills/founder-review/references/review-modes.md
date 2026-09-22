# Review modes, ceremonies, the system audit, and Step 0 — how the review runs

This reference is the operational spine of `/founder-review`: the 4 scope modes, the adapted
pre-review system audit, the Step-0 sub-steps (with the **target-conditional** ceremonies), the
expansion-framing and opt-in ceremonies, and the scope-decision artifact format.

**Formatting contract.** The generated `docs/founder-reviews/` scope-decision artifact follows the shared
contract in `saga/references/formatting-style.md`: lead each
section with a one-line summary, keep the Scope Decisions data as a table (the format below), and keep
narrative fields (Vision, Premise findings, verdict) as short (≤3-sentence) blank-line-separated prose.

---

## The 4 scope modes

The user selects **one** mode in Step 0F. Once selected, **commit to it — no silent drift.** The
options differ in **kind** (review posture), not coverage — there is **no completeness score** across
them. Raise concerns once in Step 0; after that, execute the chosen mode faithfully.

- **SCOPE EXPANSION (cathedral).** The plan is good but could be great. Envision the platonic ideal,
  push scope UP. Ask "what would make this 10x better for 2x the effort?" Recommend
  *enthusiastically* — but every expansion is the user's explicit opt-in. Run the per-expansion
  opt-in ceremony.
- **SELECTIVE EXPANSION (hold + cherry-pick).** Hold the current scope as the bulletproof baseline.
  Separately surface every expansion opportunity and present each individually so the user can
  cherry-pick. **Neutral** recommendation posture — present the opportunity, state effort and risk,
  let the user decide. Accepted expansions join scope for the rest of the review; rejected go to
  "NOT in scope".
- **HOLD SCOPE (bulletproof).** The plan's scope is accepted. Make it bulletproof — name failure
  modes, edge cases, observability, error paths, as *scope*. Do not silently reduce OR expand.
- **SCOPE REDUCTION (surgeon).** The plan is overbuilt or wrong-headed. Find the minimum viable
  version that achieves the core outcome. Cut everything else. Be ruthless. Split the rest into
  follow-ups.

**Critical rule — user 100% in control.** In ALL modes, every scope change is an explicit opt-in.
Never silently add or remove scope. If EXPANSION is selected, do not argue for less work later. If
SELECTIVE EXPANSION is selected, surface expansions as individual decisions. If REDUCTION is
selected, do not sneak scope back in.

### Context-dependent defaults (suggestions, not verdicts)

- Greenfield feature -> default **EXPANSION**
- Feature enhancement / iteration on existing system -> default **SELECTIVE EXPANSION**
- Bug fix or hotfix -> default **HOLD SCOPE**
- Refactor -> default **HOLD SCOPE**
- Plan touching **>15 files** -> *suggest* **REDUCTION** unless the user pushes back
- User says "go big" / "ambitious" / "cathedral" -> EXPANSION, no question
- User says "hold scope but tempt me" / "show me options" / "cherry-pick" -> SELECTIVE EXPANSION

The `>15 files` line is the one heuristic with a number — present it as a suggestion the operator can
override, never a hardcoded too-big verdict (the no-false-precision posture).

---

## Adapted pre-review system audit (before Step 0)

This is **not** the review — it is the grounding context that makes the critique concrete instead of
vibes-y. Re-sourced for infiquetra (the `~/.gstack`/gbrain/remote-slug machinery is shed):

```bash
git log --oneline -30                               # recent history
git diff <base> --stat                              # what's already changed (if a base applies)
git stash list                                      # any stashed work
git log --since=30.days --name-only --format="" | sort | uniq -c | sort -rn | head -20  # hot files
grep -rl "TODO\|FIXME\|HACK\|XXX" --exclude-dir=.git . | head -30
```

Then read, in the repo (not `~/.gstack`):

- the **target** itself (the `/plan` artifact, `STRATEGY.md`, `/brainstorm` output, or the scope
  question);
- `docs/office-hours/` design notes (the infiquetra analog of gstack's office-hours design doc — the
  source of truth for the problem statement, constraints, and chosen approach);
- root `STRATEGY.md` for the durable direction;
- `docs/engineering-journal/` (DECISIONS / QUEUED for the relevant initiative — what's deferred, what
  this plan touches/blocks/unlocks);
- `CLAUDE.md` / architecture docs.

Then run the four audit lenses:

- **Retrospective check.** If the git log shows a prior review cycle for this area (review-driven
  refactors, reverts), be MORE aggressive — recurring problem areas are architectural smells, surface
  them as scope concerns.
- **Frontend/UI scope detection.** If the target involves any UI screens, user-facing flows,
  user-visible state, responsive/mobile, or design-system changes, note `DESIGN_SCOPE` (feeds the
  design-trust / hierarchy-as-service patterns and the closed-loop handback).
- **Taste calibration (EXPANSION + SELECTIVE only).** Identify 2-3 well-designed files/patterns as
  style references and 1-2 frustrating ones as anti-patterns to avoid.
- **Landscape check.** Before challenging scope, understand the landscape. `WebSearch` for
  "[category] landscape {year}", "[key feature] alternatives", "why [conventional approach]
  succeeds/fails". **If WebSearch is unavailable, skip gracefully** and note: "Search unavailable —
  proceeding with in-distribution knowledge only." Run the three-layer synthesis (tried-and-true /
  what search says / first-principles where conventional wisdom is wrong) and feed it into 0A and 0C.

Report audit findings before proceeding to Step 0.

---

## Step 0 — scope challenge + mode selection

### 0A. Premise challenge (always runs)

1. Is this the right problem to solve? Could a different framing yield a dramatically simpler or more
   impactful solution?
2. What is the actual user/business outcome? Is the plan the most direct path, or is it solving a
   proxy problem? (proxy skepticism)
3. What would happen if we did nothing? Real pain point or hypothetical one?

**Office-hours escape (mid-session detection).** During 0A, if the user can't articulate the
problem, keeps changing the problem statement, answers "I'm not sure", or is clearly *exploring*
rather than reviewing — offer the early exit:

> "It sounds like you're still figuring out *what* to build — that's exactly what `/office-hours` is
> for. Want to run `/office-hours` now? We'll pick up right where we left off." A) Yes, run
> `/office-hours`. B) No, keep going.

If they keep going, proceed — no guilt, no re-asking. If they choose A, note current 0A progress so
you don't re-ask answered questions, route to infiquetra `/office-hours`, and **on return re-read
`docs/office-hours/` notes** and resume. (This is a prose offer — the gstack
`{{INVOKE_SKILL:office-hours}}` inline hack is shed; the detection + offer behavior is kept.)

### 0B. Existing-code leverage (always runs)

1. What existing code already partially or fully solves each sub-problem? Map every sub-problem to
   existing code. Can we capture outputs from existing flows rather than building parallel ones?
2. Is this rebuilding anything that exists? If yes, why is rebuilding better than refactoring?

### 0C. Dream-state mapping (always runs)

Describe the ideal end state 12 months out. Does this plan move toward or away from it?

```
  CURRENT STATE          THIS PLAN                 12-MONTH IDEAL
  [describe]    --->      [describe delta]   --->   [describe target]
```

### 0C-bis. Implementation alternatives — **TARGET-CONDITIONAL**

- **target = plan** -> run faithfully: produce 2-3 distinct implementation approaches (one "minimal
  viable" / fewest files, one "ideal architecture" / best long-term — **equal weight**, don't default
  to minimal because it's smaller), each with Summary / Effort (S/M/L/XL) / Risk / Pros / Cons /
  Reuses, plus a one-line RECOMMENDATION mapped to an engineering preference. Get explicit user
  approval of the chosen approach before mode selection.
- **target = strategy / brainstorm / scope-question** -> **skip 0C-bis**, or downgrade to 2-3
  **strategic options** (not implementation approaches — hour-by-hour implementation detail is
  incoherent on a not-yet-a-plan target). In a **channel** session, collapse this to a single
  recommended-approach confirm to keep the UX usable.

### 0E. Temporal interrogation — **TARGET-CONDITIONAL**

- **target = plan** -> run faithfully: think ahead to implementation and surface the decisions that
  should be resolved NOW, not "figure it out later".

  ```
    HOUR 1 (foundations):   what does the implementer need to know?
    HOUR 2-3 (core logic):  what ambiguities will they hit?
    HOUR 4-5 (integration): what will surprise them?
    HOUR 6+ (polish/tests): what will they wish they'd planned for?
  ```

  These are human-team hours; with CC they compress ~10-20x (decisions identical, speed faster) —
  present both scales when discussing effort (no false precision).
- **target = strategy / brainstorm / scope-question** -> **recast** as "what must be resolved before
  this becomes a plan?" (the open WHAT/HOW questions that block planning), not hour-by-hour
  implementation interrogation.

### 0F. Mode selection (always runs)

Present the 4 modes via `AskUserQuestion` (channel session -> inline the options). Include a
RECOMMENDATION based on the context-defaults. State explicitly: **"options differ in kind, not
coverage — no completeness score."** Once selected, **commit fully; do not silently drift.** Confirm
which implementation approach (from 0C-bis, plan targets) applies under the chosen mode.

---

## Expansion framing — FLAT vs EXPANSIVE

Every expansion proposal in EXPANSION or SELECTIVE EXPANSION follows this framing:

- **FLAT (avoid):** "Add real-time notifications. Users see results faster — latency drops from ~30s
  polling to <500ms push. Effort: ~1 hour."
- **EXPANSIVE (aim for):** "Imagine the moment a workflow finishes — the user sees the result
  instantly, no tab-switching, no polling, no 'did it actually work?' anxiety. Real-time feedback
  turns a tool they check into a tool that talks to them. Concrete shape: a push channel + optimistic
  UI + notification fallback. Effort: human ~2 days / CC ~1 hour. Makes the product feel 10x more
  alive."

Both are outcome-framed. Only one makes the user *feel* the cathedral: **lead with the felt
experience, close with concrete effort and impact.** For SELECTIVE EXPANSION the posture is neutral —
present vivid options, then let the user decide. Evocative, not promotional ("feels 10x more alive" is
vivid; "this 10x's your revenue" is over-sell — and is false precision; don't).

---

## The opt-in / cherry-pick ceremony (capped) + the channel digest

For EXPANSION (opt-in, enthusiastic) and SELECTIVE EXPANSION (cherry-pick, neutral):

1. Describe the vision first (10x check, platonic ideal for EXPANSION).
2. Distill it into concrete scope proposals — individual features/components/improvements.
3. Present each proposal as its own `AskUserQuestion`, framed FLAT->EXPANSIVE, with effort (present
   the number, let the operator judge) and risk. Options for each:
   - **A) Add** to this plan's scope
   - **B) Defer** to the engineering journal / QUEUED (with context — never a vague intention, never a
     stray `TODOS.md`)
   - **C) Skip** (-> "NOT in scope")
4. **Cap:** if there are more than 8 candidates, present the **top 5-6** and note the remainder as
   lower-priority options the user can request.

**Channel session (`redis-channel` active) — digest path.** `AskUserQuestion` is unavailable, so do
**not** inline 5 serial choice blocks. Present a **digest** instead — e.g. "5 expansion
opportunities; want them one-at-a-time, or shall I recommend the top 2?" — and collapse 0C-bis to a
single recommended-approach confirm. Follow the canonical channel-inline convention in
`saga/skills/brainstorm/SKILL.md` (don't duplicate its wording). Keep the channel UX
usable; the per-expansion opt-in guarantee survives as a tight digest, not a serial barrage.

Accepted items become plan scope for the rest of the review. Rejected items go to "NOT in scope".

---

## The scope-decision artifact format

Write to `docs/founder-reviews/YYYY-MM-DD-<topic>-founder-review.md` — its **own** scope-decision
directory (NOT `docs/reviews/` = readiness, NOT `docs/code-reviews/` = code, and deliberately **not a
`mission-control` artifact source**). Adapted from gstack's CEO-plan format. Use repo-relative paths.

```markdown
---
status: ACTIVE
type: founder-review
date: YYYY-MM-DD
origin: <plan path | STRATEGY.md | brainstorm path | ad-hoc scope question>
---
# Founder Review: <Topic>

Mode: <SCOPE EXPANSION | SELECTIVE EXPANSION | HOLD SCOPE | SCOPE REDUCTION>
Target: <type + path>

## Vision   (EXPANSION + SELECTIVE only)
### 10x check
<the 10x-more-ambitious version, concretely>
### Platonic ideal   (EXPANSION only)
<what the best builder with perfect taste would make; what the user would feel>

## Scope Decisions

| # | Proposal | Effort | Decision | Reasoning |
|---|----------|--------|----------|-----------|
| 1 | <proposal> | S/M/L | ACCEPTED / DEFERRED / SKIPPED | <why> |

## Accepted Scope (now in this plan)
- <bullets>

## Deferred (-> engineering journal / QUEUED)
- <items with enough context to pick up cold>

## Premise findings
- <0A/0B/0C concrete findings: right problem? leverage gaps? dream-state delta?>

## Founder verdict
<ship as-is | sharpen first | scrap and rethink>  +  the concrete next-command handback
(e.g., "I wrote the expanded plan to docs/plans/<file> — run `/doc-review docs/plans/<file>` for
readiness depth, then `/work`")
```

HOLD and REDUCTION modes skip the Vision section. Deferred items route to the engineering journal /
QUEUED, never a stray TODOS.md — vague intentions are lies (Directive 7).
