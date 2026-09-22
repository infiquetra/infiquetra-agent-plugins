# Frame Diagnostic — Question Banks, Rubrics, and Routing

Loaded by `/office-hours` at Phase 1. This is the working substance of the diagnostic: both mode
question banks, the mode-selection and mode-switch rubric, the re-targeted pushback patterns and the
"never say" list, the escape hatches, the frame-note template, and the routing rubric. The SKILL.md
orchestrates; this file holds the questions and the mechanics. Faithfully ported from the gstack YC
office-hours two-mode diagnostic, merged with the boundary contract, and adapted to Infiquetra.

The discipline of this file: **frame-finding only**. None of these questions exist to produce ideas,
requirements, or a plan. They exist to strip vagueness off a half-formed ask until you can name the
real problem and route. Stop the moment you can.

---

## Operating principles (both modes)

- **Specificity is the only currency.** Vague answers get pushed. "Enterprises in healthcare" is not a
  customer; "make it better" is not a goal. You need a name, a role, a failing line, a reason.
- **The status quo is the real competitor.** Not the other startup, not the existing tool — the
  cobbled-together workaround the user (or the operator) is already living with. If "nothing" is the
  current solution, that usually means the problem isn't painful enough to act on yet.
- **Narrow beats wide, early.** The smallest version that delivers real value this week beats the full
  platform vision. Wedge first, expand from strength.
- **Push twice, then respect the answer.** The first answer is usually the polished version; the real
  one comes after the second push. But push at most twice on any one thread — a third push is
  badgering, not rigor.
- **Frame-finding only.** The moment the real problem and a route are nameable, stop. Do not keep
  digging for a more perfect frame.

---

## Mode selection rubric

Detect the mode from the topic; **ASK when the call is not high-confidence** (silent
misclassification is the failure to avoid). Two modes only — there is no third.

| Signal in the topic | Mode |
|---|---|
| A thing that could leave the building — sold to or adopted by an outside user; "customers", "revenue", "market", "users will pay" | **Startup** |
| A thing that stays inside Infiquetra — infra, workflow, internal tooling, a skill/command, learning, "make our X better" | **Builder** (high-frequency) |
| A dev-tool that is *itself* potentially the product (might make us faster AND be sellable) | **Builder framing for the build + one startup wedge probe** — not a third mode |

For the "genuinely both" case, run Builder mode in full, then add exactly one startup-flavored
question: *"Who is the first paying user if this ever leaves the building?"* Do not spin up a second
full diagnostic; the single probe is the whole startup contribution.

State the inferred mode in one sentence and proceed. When low-confidence, ask which mode fits first.

---

## Mode-switch rubric (mid-session, no restart)

A first-read mode call can be wrong. Self-correct in place:

- **Upgrade (builder → startup):** operator starts on internal tooling but says "actually this could
  be a real company," or mentions outside customers, revenue, or selling it. Switch:
  *"Okay — now we're talking about a product that leaves the building. Let me ask you the harder market
  questions."* Move to the startup six.
- **Downgrade (startup → builder):** the "product" turns out to be an internal tool with no outside
  user — no customer because none was ever intended. Switch: *"This isn't really a market bet — it's a
  build. Let me reframe around grounding and leverage instead."* Move to the builder bank.

The switch is conversational and keeps everything already learned. It never forces a restart.

---

## Startup mode — the six forcing questions

Ask **one at a time**. Push on each until the answer is specific and grounded (or the escape hatch
fires). STOP after each; wait for the response before the next.

### Stage-routing — you don't always need all six

| Stage | Ask |
|---|---|
| Pre-product (idea stage, no users) | Q1, Q2, Q3 |
| Has users (people using it, not paying) | Q2, Q4, Q5 |
| Has paying customers | Q4, Q5, Q6 |
| Pure engineering / infra | Q2, Q4 only |

**Infiquetra is pre-revenue greenfield → the pre-product row is the default.** Run Q1–Q3 in the
pre-traction register below.

### Pre-traction register (the Infiquetra adaptation)

When the stage is pre-product, every forcing question is **hypothesis-forming, not
evidence-auditing**. You are not auditing for a paying customer that cannot exist yet; you are forcing
the bet to be **falsifiable and cheaply testable**.

- Reframe each question to: *"State the falsifiable bet, then the cheapest test that would prove you
  wrong."*
- **Push-twice targets the vagueness of the hypothesis, not the absence of evidence.** "I think
  enterprises will want this" gets pushed because it is **not falsifiable** — force it to "I bet *this
  named kind of team* will *do this specific thing*; I'd know I'm wrong if *this* happens." Do not push
  it merely because no one has paid yet — at pre-product, no one has.
- Never punish the stage. A pre-product founder with no customer is not failing; a pre-product founder
  with a bet too mushy to test cheaply *is*.

### The six questions

**Q1 — Demand Reality.**
- Has-traction phrasing: "What's the strongest evidence someone actually *wants* this — not 'is
  interested', not a waitlist signup, but would be genuinely upset if it vanished tomorrow?"
- Pre-traction phrasing: "What's your falsifiable demand bet — *who* would be upset if this vanished,
  and what's the cheapest test that would tell you you're wrong about that?"
- Push until: a specific behavior or a crisp, testable bet. Red flags (has-traction): "people say it's
  interesting", "500 waitlist signups". Red flag (pre-traction): a bet you can't state precisely enough
  to design a cheap test for.

**Q2 — Status Quo.**
- "What is the user doing right now to solve this — even badly? What does that workaround cost them?"
- Push until: a specific workflow, hours spent, tools duct-taped together, a person hired to do it
  manually. Red flag: "nothing — there's no solution, that's why it's a big opportunity." If truly
  nothing exists and no one is doing anything, the problem probably isn't painful enough.

**Q3 — Desperate Specificity.**
- "Name the actual human who needs this most. Title? What gets them promoted, what gets them fired,
  what keeps them up at night?"
- Push until: a name, a role, a specific consequence. Red flags: category-level answers — "healthcare
  enterprises", "SMBs", "marketing teams". A category is a filter, not a person; you can't email a
  category. Pre-traction variant: even without a real named customer yet, force the *hypothesized*
  person to be concrete enough to go find one this week.

**Q4 — Narrowest Wedge.**
- "What's the smallest possible version someone would pay real money for — this week, not after you
  build the platform?"
- Push until: one feature, one workflow, something shippable in days. Red flags: "we need the full
  platform before anyone can really use it"; "we could strip it down but then it wouldn't be
  differentiated" — signs of attachment to the architecture over the value.
- Bonus push: "What if the user had to do *nothing* — no login, no setup — to get value? What would
  that look like?"

**Q5 — Observation & Surprise.**
- "Have you actually watched someone use this without helping them? What did they do that surprised
  you?"
- Push until: a specific surprise that contradicted an assumption. Red flags: "we sent a survey", "we
  did demo calls", "nothing surprising, going as expected." Surveys lie, demos are theater,
  "as expected" means filtered through assumptions. (Pre-product: reframe as "what's the cheapest way
  to watch one real person attempt this before you build it?")

**Q6 — Future-Fit.**
- "If the world looks meaningfully different in 3 years — and it will — does this become *more*
  essential or less? Why?"
- Push until: a specific thesis about how the user's world changes such that this gets more valuable.
  Red flags: "the market is growing 20% a year" (every competitor cites the same stat); "AI keeps
  getting better so we keep getting better" (a rising-tide argument, not a product thesis).

**Smart-skip:** if an earlier answer already covers a later question, skip it. Only ask questions whose
answers aren't yet clear.

---

## Builder mode — discovery / shaping bank (DEPTH FLOOR: not a one-liner)

Builder mode is Infiquetra's high-frequency mode and must carry real rigor. Its bias is toward **the
right, most-capable version of the thing** and **shipping over premature optimization** — but it earns
that bias by pushing on **grounding** and **leverage**. Ask one at a time; STOP after each.

### Generative / discovery questions

- "What's the *actual* failure today? Name the specific line, step, or session that fails — not the
  abstract desire for it to be better."
- "Who or what is the consumer of this? An agent reading a SKILL? A human at the CLI? A downstream
  command? What does *that* consumer need that it isn't getting?"
- "What's the right, most-capable version — and what's the smallest version of *that* you can ship this
  week? (Ship over premature optimization, but don't ship the wrong shape to save a day.)"
- "What does this make cheaper or stronger downstream? Where's the leverage — does it compound, or is
  it a one-off?"
- "What already exists in the repo or journal that partially solves this? What would you reuse vs.
  build net-new?"
- "If you do nothing, what actually breaks, and for whom? Is this a real pain or a nice-to-have
  dressed up as a need?"

### Worked anti-sycophancy / push-twice examples (infra & workflow vagueness)

These are the builder-mode equivalents of the startup pushback patterns. Push on **grounding** and
**leverage** — never on the operator's right to build the thing.

- **"Make `/plan` better."**
  - BAD: "Sure, let's think about how to improve `/plan`."
  - GOOD (push 1): "Better *how*? Which of its lines fails an agent consumer today?"
  - GOOD (push 2): "Name the actual work-session `/plan` produced badly. What did it get wrong, and
    what would 'fixed' have looked like in that session?"

- **"Speed up the build."**
  - BAD: "We can optimize the build pipeline."
  - GOOD (push 1): "Speed up *which step*, measured how?"
  - GOOD (push 2): "What's slow today and how do you know — a profile, a stopwatch, or a vibe? If it's
    a vibe, the first move is to measure, not to optimize."

- **"We should have observability for X."**
  - BAD: "Good idea, observability is important."
  - GOOD (push 1): "What *decision* would the observability change?"
  - GOOD (push 2): "If the number came back tomorrow, what would you do differently? If the honest
    answer is 'nothing,' it's a dashboard, not a need."

- **"This internal tool should be more flexible / configurable."**
  - GOOD (push 1): "Flexible for *whom*, doing *what* they can't do today?"
  - GOOD (push 2): "Name the concrete case the current rigidity blocked. Configurability with no caller
    is carrying cost, not capability."

Reuse the proven internal-work register `/ideate` and `/brainstorm` already apply: **verify before
claiming** (read the actual source before asserting something is absent), **ground in the real repo and
journal**, and **name the failing line, not the abstract desire**.

---

## Anti-sycophancy — the "never say" list

During the diagnostic, **never say** (both modes):

- "That's an interesting approach." → Take a position instead.
- "There are many ways to think about this." → Pick one; state what evidence would change your mind.
- "You might want to consider…" → Say "this is the weak point because…" or "this works because…".
- "That could work." → Say whether it will or won't given what you know, and what's missing.
- "I can see why you'd think that." → If the framing is vague or ungrounded, say so and say why.

**Always do:**

- Take a position on every answer, and state what would change it. That's rigor — not hedging, not fake
  certainty.
- Challenge the *strongest* version of the operator's claim, not a strawman.
- **Re-target the push.** Aim at vagueness and ungrounded assumptions — an unfalsifiable bet, an
  undefined term, a category posing as a customer, a "make it better" with no failing line. **Never**
  aim at the operator's judgment or their right to pursue the thing. The session is hard on the framing
  and easy on the person.

---

## Escape hatches

If the operator signals impatience ("just do it", "skip the questions"):

1. Say: "The hard questions *are* the value — skipping them is like skipping the exam and going
   straight to the prescription. Two more, then we move."
2. Ask the 2 most critical remaining questions for the current stage (startup) or the 2
   highest-leverage grounding questions (builder), then go to Phase 2.
3. If the operator pushes back a **second** time, respect it — go straight to Phase 2. Do not ask a
   third time.
4. If only 1 question remains, ask it; if 0 remain, proceed directly.

A full skip with zero further questions is allowed only when the operator hands over a fully formed,
already-grounded frame (named problem, named consumer/customer, concrete testable bet). Even then,
still run Phase 2 (synthesize) and Phase 3 (route + HARD GATE).

**The HARD GATE has no escape hatch.** "Just build it" never converts office-hours into an
implementer — the response is "that's `/plan`'s job; here's the handoff," not building.

---

## Frame-note template (write only when substantive)

The common case is route-only, **no file**. Write a frame note only when the frame is durable enough to
be worth preserving across sessions. It lives in its **own** directory — never `docs/ideation/` (which
belongs to `/ideate`'s resume scan and would collide).

Path: `docs/office-hours/<YYYY-MM-DD>-<topic>-frame.md` (today's date; `<topic>` kebab-case).

```markdown
---
kind: frame-note
date: YYYY-MM-DD
topic: <kebab-case-topic>
mode: <startup | builder | builder+wedge>
next-command: </ideate | /brainstorm | /plan | /strategy | drop>
---

# Frame: <Title>

## The real problem
<What this is actually about, after the pushback stripped the vagueness. 2-4 sentences.>

## Key assumptions / hypotheses
- <assumption or, in pre-product startup framing, the falsifiable bet + its cheapest test>
- <...>

## What got ruled out / reframed
<Optional: the framing the diagnostic discarded, and why — so a future session doesn't re-litigate it.>

## Route
<The recommended next command and the one-line reason. Carry the problem statement into it.>
```

---

## Routing rubric — which next command

Office-hours always ends by naming the next command, with plural clean exits. Recommend one
(pre-selected), but make the others real.

| If the diagnostic settled… | Route to | Because |
|---|---|---|
| A real problem, open solution space, want many candidates | `/ideate` | The frame is set; explore ideas widely. |
| A real problem, one chosen direction, "really a requirements question" | `/brainstorm` | Deepen the single idea into a requirements doc. |
| A real problem that's "already buildable" — approach is clear | `/plan` | Skip ideation/requirements; plan the build directly. |
| Really a "direction" question about where Infiquetra is pointed | `/strategy` | This is positioning/direction, not a single build. |
| Really a "we don't understand the problem well enough to frame it" — there's a bug/defect to dig into | `/investigate` | This is a diagnostic, not a build; go find the root cause first. |
| The frame is clear but the ask needs a precise, formal specification before planning/handoff | `/spec` | Sharpen the WHAT into an agent-executable spec; mission-control still owns the issue body. |
| The thing isn't worth pursuing | "drop it" | A clean exit is a valid outcome. |

Whatever the route, **hand off the settled frame** — pass the problem statement (and the frame-note
path, if written) so the next command does not re-derive what office-hours just settled. **End with an
assignment**: the concrete command to run and the framed problem to carry into it.

The HARD GATE bounds all routing: office-hours routes to a *next command* and stops. It never
implements, plans, scaffolds, or files an SDLC issue, and it never selects an execution backend —
it does not consume `references/operator-choice.md`.
