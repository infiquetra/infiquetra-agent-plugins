# Ideate — Convergence and Partnership (Phases 3-6)

Load this after Phase 2 (in `saga/skills/ideate/SKILL.md`) returns and the
orchestrator has merged, deduped, and cross-cut the frame-agent outputs plus the user seeds into one
candidate pool. Do not load before Phase 2 completes. The user seeds are already in the pool and were
already engaged by the frame agents — here they are critiqued by the identical rubric, never
rubber-stamped, never silently dropped.

The orchestrator runs Phases 3-6 directly. Do not dispatch sub-agents for critique, presentation, or
persistence.

## Phase 3 — Adversarial filtering

Review every candidate critically, one at a time. Generate no replacement ideas in this phase unless
the operator is explicitly refining (Phase 6). For each rejected idea, write a one-line reason.

### Rejection criteria (verbatim-adapted)

Reject an idea for any of:

- too vague
- not actionable
- duplicates a stronger idea
- not grounded in the stated context (repo + context-libraries + named repos from Phase 1)
- too expensive relative to likely value
- already covered by existing workflows, skills, or docs
- interesting but better handled as a `/brainstorm` variant or `/office-hours` thread, not a product
  or engineering improvement
- **unjustified — no articulated basis.** The basis contract is hard: a frame agent (or a user seed)
  failed to attach `direct:`, `external:`, or `reasoned:`, OR the stated basis does not actually
  support the claimed move. An idea with no articulated basis does NOT surface — cut it here.
- **below ambition floor (meeting-test).** Would not warrant team discussion. Waived only when Phase 0
  detected tactical / narrow focus signals, in which case this criterion does not apply.
- **subject-replacement.** Abandons or replaces the subject of ideation rather than operating on it
  (e.g., "pivot the repo to an unrelated domain," "rebuild as a different service"). Always reject.
- **scope overrun.** Expands beyond the asked scope rather than ideating within it (e.g., proposes
  changes to the whole platform when the operator asked about one flow, plugin, or stage). Allowed
  only when the basis explicitly justifies the expansion; default is reject or downgrade.

**Provenance is not a gate criterion.** A candidate tagged `engine-generated` is evaluated by the same
rejection criteria and the same survivor scoring rubric as every Claude frame-agent, user-seed,
interview, or combined candidate. The tag is informational provenance only; it does not relax basis
strength, change the survivor target, create a separate review path, or supply authority outside the
written `direct:` / `external:` / `reasoned:` basis.

### Survivor scoring rubric (verbatim-adapted)

Score every survivor on a consistent rubric weighing:

- groundedness in the stated context;
- **basis strength** — `direct:` > `external:` > `reasoned:`. None is excluded, but a direct-evidence
  idea (quoted file/line/issue/user-context) outscores an equally-good reasoned idea, all else equal;
- expected value;
- novelty;
- pragmatism;
- leverage on future work (compounding);
- implementation burden;
- overlap with stronger ideas;
- **axis spread** — when Phase 1.5 produced an axis list, survivor sets that cover the topic's surface
  outscore sets that cluster on one axis, all else equal.

**Advisory scores beside the verdicts.** The `rubric` judgment in
`plugins/saga/scripts/shaping_judgments.py` (see the skill's "Advisory typed judgments" section)
returns one score per **per-idea** dimension above, so survivors become comparable numbers and a
re-weighting needs no re-critique. It covers the eight per-idea dimensions only — never axis spread,
for the reason stated immediately below. The scores sit beside the critics' prose verdicts; they do
not replace a verdict, and nothing is promoted or cut on a score. It is advisory and fails open: when
the call fails, score in prose as this rubric already describes.

**Axis coverage is a list-level concern, not per-idea.** After per-idea filtering, inspect the survivor
set as a whole: if coverage is uneven and stronger candidates exist on under-represented axes, prefer
the spread when promoting borderline candidates. If an axis ends up with zero survivors, note it in the
rejection summary as a deliberate gap rather than letting it vanish silently.

### Survivor target

- Keep **5-7 survivors** by default.
- If too many survive, run a second, stricter pass.
- If fewer than 5 survive, report that honestly rather than lowering the bar.
- Tactical / narrow scope (Phase 0) may legitimately yield fewer survivors; that is not a failure.

Carry forward, for each survivor, the SURVIVOR SCHEMA fields populated in Phase 4. Assign every cut
idea worth keeping a stable REVIVABLE-CUT id (`R1`, `R2`, ...).

## Phase 4 — Present the survivors and the revivable cut

Checkpoint before presenting: write the survivor set plus key context (focus hint, grounding summary,
rejection summary, the `R#`-keyed revivable cut) to `.claude/saga/ideate/<run-id>/survivors.md`,
reusing the `<run-id>` and run directory created in Phase 2. Best-effort: if the write fails, log a
warning and proceed — the checkpoint is not load-bearing.

The terminal review loop is a complete ideation cycle in itself. Persistence is opt-in (Phase 5) and
refinement happens in conversation with no file cost (Phase 6). Keep the presentation concise; allow
brief follow-up questions and lightweight clarification.

### SURVIVOR SCHEMA

Present only the surviving ideas. The render follows the canonical formatting contract,
`saga/references/formatting-style.md`, and matches the artifact template in
`saga/skills/ideate/references/ideation-artifact.md` exactly (same field names). Each survivor takes
this shape:

- a `### N. <title>` heading — the **title** (short, concrete) lives in the heading, not a separate
  field;
- a one-line plain-language summary of the move;
- the **description** (concrete explanation of the move) as short prose, then **rationale** (how the
  basis connects to the move's significance) and **downsides** (tradeoffs or costs) as a separate
  short paragraph — blank-line-separated, ≤3 sentences each;
- a small two-column table for the compact fields:
  - **basis** — tagged exactly one of `direct:` (quoted file/line/issue/user-context), `external:`
    (named prior art / source), or `reasoned:` (written-out first-principles argument). This is the
    same basis contract the frame agents carried in Phase 2.
  - **source** — provenance only: `frame-agent`, `user-seed`, `interview`, `combined`, or
    `engine-generated`. Omit only when provenance is unknown.
  - **confidence** — 0-100.
  - **complexity** — Low / Med / High.
  - **axis** — the topic axis this idea targets. Include this row only when Phase 1.5 produced an axis
    list; omit it when decomposition was skipped.
  - **status** — `Unexplored` / `Explored`.

Order survivors by the rubric score (strongest first).

### REVIVABLE-CUT SCHEMA

After the survivors, present a **"Did not survive (revivable)"** section. Explicit rejection IS the
quality mechanism; cut ideas are first-class and kept visible so the operator can see what was
considered. Each cut idea worth recording uses this exact shape:

- **id** — stable `R1`, `R2`, ... (stable across the run; do not renumber when revival changes a
  status).
- **title** — short.
- **summary** — one line.
- **reason** — the Phase 3 rejection reason (one line).
- **status** — one of `rejected` / `revived` / `revisited`. Starts at `rejected`. A `revived` idea
  has been promoted into the survivor set above — render it under Ranked Survivors, and either omit it
  here or leave it with status `revived` for history; never present a `revived` idea as a current
  non-survivor.

Then a brief rejection summary so the operator sees the shape of what was cut, including any
zero-survivor axis noted as a deliberate gap.

## Phase 5 — Persist (opt-in)

Persistence is opt-in. The terminal review loop is already a complete cycle. Persist only when the
operator explicitly chooses to save, dig deeper, or hand off (selected in Phase 6). When a Phase 6
choice needs a durable record (dig-deeper → `/brainstorm`, handoff → `idea-ready`, save and end),
ensure a record exists first. When the operator keeps refining, write nothing unless asked.

To persist:

1. Ensure `docs/ideation/` exists.
2. Choose the path:
   - `docs/ideation/YYYY-MM-DD-<topic>-ideation.md`
   - `docs/ideation/YYYY-MM-DD-open-ideation.md` when no focus exists.
3. Write or update the ideation document using the template in
   `saga/skills/ideate/references/ideation-artifact.md`. The template's field names
   match the SURVIVOR SCHEMA and REVIVABLE-CUT SCHEMA above exactly — keep them aligned.

When resuming an existing run: update the file in place and preserve `Explored` markers and the
stable `R#` ids and their statuses.

There is no Proof / HITL path and no cloud doc-review in this skill. File save under `docs/ideation/`
is the only destination.

## Phase 6 — Refine, co-ideate, revive, interview, or hand off

Ask what should happen next. Use the platform's blocking question tool (`AskUserQuestion`; call
`ToolSearch` with `select:AskUserQuestion` first if its schema isn't loaded). If no blocking tool
exists or the call errors, fall back to numbered options in chat. Never silently skip the question.

**Question:** "What should ideate do next?"

Offer these routes:

1. **Refine in conversation (or stop here — no save)** — tighten, re-evaluate, or deepen analysis. No
   file side effects; ending the conversation after this pick is a valid no-save exit.
2. **Add an idea (co-ideate)** — fold a new operator seed into the pool.
3. **Revive a cut idea (`R#`)** — re-enter the Phase 3 filter with new evidence (state machine below).
4. **Dig deeper on a survivor → `/brainstorm`** — write a durable record first, mark the chosen idea
   `Explored`, then load `saga/skills/brainstorm/SKILL.md` with that idea as the seed.
5. **Re-evaluate / raise the bar** — return to Phase 3 and re-run the rubric, stricter.
6. **Interview me (I'm stuck)** — conditional tactic; see Interview below.
7. **Hand off → `idea-ready`** — write a durable record, then graduate to `mission-control`, which
   owns the issue, or to `/plan`. The ideation artifact is `idea-ready` maturity.

A no-save exit needs no dedicated option: pick route 1 and stop, or use the question tool's free-text
escape. Persistence stays opt-in.

### 6.1 Refine in conversation

Route refinement by intent:

- `add more ideas` / `explore new angles` → return to Phase 2 (re-dispatch frame agents, or a single
  targeted frame on the new angle).
- `re-evaluate` / `raise the bar` → return to Phase 3.
- `dig deeper on survivor #N` → expand only that idea's analysis in conversation.

No persistence triggers during refinement. Ending here — with or without refinement — is a valid
no-save exit that leaves no durable artifact, matching the opt-in contract.

### 6.2 Add an idea (co-ideate)

Partnership runs both ways through the whole run, not just at the start. A new operator seed offered in
Phase 6:

1. enters the candidate pool as a `user-seed` candidate with its provenance recorded;
2. must carry (or be helped to articulate) a basis under the same `direct:` / `external:` / `reasoned:`
   contract;
3. is critiqued by the **identical** Phase 3 rubric against the current survivor set — never
   rubber-stamped because it came from the operator, never silently dropped if it loses;
4. if it beats the bar, it joins survivors (displacing the weakest if the 5-7 cap is exceeded, same as
   revival Outcome B — the displaced survivor enters the cut with status `rejected` and a reason string
   recording its provenance, e.g. `"displaced by R#"`); if it does not, it lands in the revivable cut
   with a stable `R#`, status `rejected`, and reason.

Record the seed and its outcome in the co-ideation log when the run is persisted (Phase 5).

### 6.3 Revive a cut idea — the revival state machine

Revival re-enters the filter. An easy "revive" button would gut "explicit rejection is the quality
mechanism" and let pet ideas back in unexamined. The state machine is the anti-pet-idea guardrail.

To revive `R#`:

1. **New-evidence gate.** The operator MUST supply NEW evidence or a NEW perspective that the original
   critique did not weigh. If none is supplied, **DECLINE** the revival and ask for the specific angle
   the critique missed — name what the original rejection reason was so the operator can answer it. Do
   not re-score on the same evidence; that just relitigates the original verdict. **Adjudicate novelty
   yourself:** judge whether what the operator offered is genuinely new, not a restatement of what the
   critique already weighed dressed up as a new angle. The `revival` judgment in
   `plugins/saga/scripts/shaping_judgments.py` answers the same question as one advisory
   probability — it informs that adjudication and never makes it, and it fails open to your own
   reading. If it restates the original basis, decline as
   "same evidence" and name the original reason. The operator asserting "this is new" does not make it
   new — you decide.

2. **Re-run BOTH Phase 3 stages on `R#`, in order, incorporating the new evidence.** "The Phase 3
   rubric" means the full Phase 3, not just the scoring subheader — re-scoring alone is a soft-promote
   loophole that would let a categorically-cut idea back in unexamined.
   - **2a. Re-test the rejection criteria first (Phase 3 "Rejection criteria", above).** Re-apply the
     categorical gate with the new evidence. If `R#` still trips a categorical criterion — unjustified
     basis (no `direct:`/`external:`/`reasoned:`, or a basis that does not support the move),
     subject-replacement, scope overrun, or duplicates a stronger current survivor — it **cannot be
     promoted regardless of any score** and goes straight to Outcome A. Explicit rejection IS the
     quality mechanism: a high re-score does not make a subject-replacement or unjustified idea
     admissible. Only an idea that now *clears* the gate proceeds to 2b.
   - **2b. Re-score against the survivor rubric (Phase 3 "Survivor scoring rubric", above).** Only for
     `R#` ideas that cleared the gate in 2a, re-run the scoring rubric incorporating the new evidence,
     judged against the **CURRENT** survivor set (not the original pool — survivors may have changed
     since the cut).

3. **Outcome A — still excluded.** `R#` either still trips a categorical rejection criterion in 2a
   (cannot be promoted regardless of score) or cleared the gate but still scored below the bar in 2b.
   Either way, set `R#` status → `revisited`. Record what the gate or score turned on — which criterion
   it still trips, or how the new evidence was weighed and why it still falls short. `R#` stays in the
   revivable cut — it is never silently re-dropped, and its id and history persist.

4. **Outcome B — clears the gate and now beats the bar.** `R#` passed 2a and scored above the bar in
   2b. Set `R#` status → `revived`. Promote it into the survivor set with full SURVIVOR SCHEMA fields.
   If promotion would push the survivor set above 7 — growing 5→6 or 6→7 needs **no** displacement; 7
   is the ceiling — **DISPLACE the weakest survivor**: move it to the
   revivable cut with a fresh `R#` id, status `rejected`, and a reason string recording its provenance
   (`"displaced by revived R#"`). Status stays inside the closed enum `{rejected, revived, revisited}`;
   the provenance lives in the reason. The cap holds; the set never silently grows past 7.

Statuses are sticky on the stable id. A `revisited` idea can be revived again later if the operator
brings genuinely different new evidence the second time.

### 6.4 Re-evaluate / raise the bar

Return to Phase 3 and re-run the rubric with a stricter pass. Survivors that no longer clear the bar
move to the revivable cut with a stable `R#` id, status `rejected`, and a reason string recording the
provenance (e.g. `"fell below raised bar"`). Status stays inside the closed enum
`{rejected, revived, revisited}`; the demotion history lives in the reason. This is the inverse of
revival and uses the same schema.

### 6.5 Interview when stuck

Conditional tactic — NOT the default. The default engine generates; it does not interview. Fire the
interview only when:

- the operator's input is circling, stuck, or contradictory; or
- the operator explicitly asks for it; or
- it is offered as an optional final gate before handoff.

Run it as one open-ended question at a time (office-hours register). Every answer that produces a
concrete idea becomes a `user-seed` candidate and re-enters Phase 2/Phase 3 like any other seed —
drawn-out ideas do not bypass the filter. If the interview reveals the subject is genuinely unframed,
recommend `/office-hours` rather than forcing survivors out of a vibe.

### 6.6 Dig deeper → `/brainstorm`

1. Write or update the durable record (Phase 5).
2. Mark the chosen survivor `Explored` in the saved record.
3. Load `saga/skills/brainstorm/SKILL.md` with the chosen idea as the seed.

Do not skip `/brainstorm` and route a raw survivor straight to `/plan` — `/plan` wants
brainstorm-grounded, `requirements-ready` material. Ideation output is `idea-ready`, one rung below.

### 6.7 Hand off → `idea-ready`

1. Write or update the durable record (Phase 5).
2. Graduate to `mission-control`, which builds the handoff envelope and opens the issue; the
   `docs/ideation/` artifact carries `idea-ready` maturity. `/plan <issue>` also consumes `idea-ready`.

Leave the run scratch directory (`.claude/saga/ideate/<run-id>/`) in place on
completion; the OS handles eventual cleanup and the checkpoints are cheap to keep.

## Quality-bar self-check

Before finishing, verify (verbatim-adapted from CE — this is the only behavioral guard available, so
run it honestly):

- the idea set is **grounded in the stated context** (current repo + relevant `*-context-library`
  repos + any named infiquetra repos from Phase 1);
- **every survivor has an articulated basis** (`direct:` / `external:` / `reasoned:`) that actually
  supports the claimed move — speculation dressed as ambition was rejected, with reasons;
- **every survivor passes the meeting-test** unless Phase 0 detected tactical / narrow focus signals
  that waived the floor;
- **no survivor replaces the subject** rather than operating on it;
- when Phase 1.5 produced an axis list, the survivor set **spreads across axes** rather than clustering
  on one — and any zero-survivor axis is noted as a deliberate gap in the rejection summary, not
  silently absent;
- the **candidate list was generated before filtering** (many → critique → survivors), not curated
  into existence;
- the original **many-ideas → critique → survivors** mechanism was preserved;
- **every rejected idea has a reason** and a stable `R#` id if it is worth reviving;
- survivors are **materially better than a naive "give me ideas" list**;
- **persistence followed the operator's choice** — terminal-only sessions wrote no file;
- **USER SEEDS were engaged by the generators in Phase 2** (built on / challenged / combined inside the
  frame-agent reasoning), not merely judged at merge — and were critiqued by the identical rubric.

If any check fails, fix it before presenting or persisting — do not ship a degraded run.
