# Strategy Interview

Loaded by `SKILL.md` at the start of Phase 1 and revisited per-section in Phase 2. Each section maps
one-to-one to a section in `strategy-template.md`. Pushback rulebook ported from Compound-Engineering
`ce-strategy`; the agent-as-customer and tracks-are-not-actors deltas are the Infiquetra adaptations.

For each section: ask the opening question, evaluate the answer against the quality bar, push back when
it falls into a named anti-pattern, and capture the final answer in the user's own language.

## Overall rules

1. **Ask, don't prescribe.** Free-form responses for the open answers (problem, approach, persona,
   metrics, tracks). Reserve single-select for routing decisions (which section to revisit).
2. **Push back once, maybe twice.** Weak first answer -> name the specific issue, ask a sharper
   question. Weak second answer -> capture what the user gave and note the section is worth revisiting.
   Do not let the interview spiral. **This two-round pushback is the core of the skill — do not skip
   it.** A passive transcription of weak answers is not a strategy doc.
3. **Quote the user back at them.** Challenge with the user's own words verbatim. Paraphrasing softens
   the challenge.
4. **Keep each answer to 1-3 sentences.** Longer answers usually hide something vague. If the user
   writes a paragraph, ask them to pick the sentence that matters most.
5. **Don't leak the anti-pattern names.** Just ask the sharper question that follows.

## 1. Target problem

**Opening:** "What's the core problem this product solves — and what makes that problem hard?"
**Quality bar:** names a specific user situation, identifies what makes it hard *right now* (a crux, a
constraint not easy to route around), and is falsifiable.

- **goal-as-problem** ("the problem is we need to grow revenue") -> "That's a goal, not a problem.
  What's in the world making that goal hard? Whose situation are you changing?"
- **vague-wish** ("people need better tools for X") -> "Whose situation specifically? Doing what? What
  do they try today, and why doesn't it work?"
- **symptom-not-cause** ("users churn after 30 days") -> "That's a symptom. What's the underlying
  condition that makes them stop caring?"
- **Too broad** ("communication at work is broken") -> "Narrow it to a situation you can affect — which
  users, doing what, when does it hurt most?"
- **Feature-shaped** ("there's no good way to do [workflow] with AI") -> "That's a missing feature.
  What outcome do users want that the feature would give them?"

**Capture:** One or two sentences naming the situation and the crux. No solution language.

## 2. Our approach

**Opening:** "Given that problem, what's your approach — the commitment or principle that makes it
tractable?"
**Quality bar:** a choice (implying alternatives *not* pursued), general enough to direct many
decisions but specific enough to rule things out; "we win by [doing X differently]", not "we do [a
list]".

- **fluff/values** ("we're customer-obsessed and move fast") -> "Those are values. What are you doing
  *differently* from the products users could pick instead? If it applies to any company, it's not your
  approach."
- **feature-list** ("we're building AI-powered X, Y, and Z") -> "That's a feature list. What's the
  underlying bet that makes you pick those over others?"
- **product-description-as-approach** ("we use AI to draft replies") -> "That's what the product does.
  What's the *choice* inside it that the obvious alternative isn't making — a grounding choice, a trust
  commitment, a workflow bet?"
- **Goal restated** ("be the market leader") -> "Still the goal. How does the product win? What choice
  are competitors not making?"
- **Multiple approaches** ("deep on enterprise, self-serve, and consumer") -> "Pick one as the guiding
  approach; the others may still get work, but one organizes the rest."
- **Doesn't connect to the problem** -> "How does that approach solve the problem you named? If there's
  no line between them, one of the two is wrong."

**Capture:** One or two sentences, ideally implying "...so that [outcome tied to the problem]".

## 3. Who it's for

**Opening:** "Who is the primary user, and what job are they hiring this product to do?"
**Quality bar:** one primary persona (others secondary), identified by role/situation not demographic,
with a concrete job as a verb phrase.

**Agent-as-customer prompt (Infiquetra delta).** For a product consumed by an AI agent rather than a
human (an agent-facing API, a tool an autonomous agent calls, an MCP server), the *primary* persona may
be the **AI-agent consumer** itself, framed with the same jobs-to-be-done rigor (its job is a concrete
verb phrase, not "use the API"). This is a **light prompt, NOT forced**: for a clearly human-facing
product, do not push an agent persona that isn't there.

- **Too many primary personas** ("founders, PMs, engineers, designers") -> "If it's for everyone, it's
  for no one. Who matters most?"
- **Demographic framing** ("25-45 year old professionals") -> "That's a demographic. What are they
  trying to do that makes them pick up this product?"
- **Role without situation** ("PMs") -> "PMs doing what? The situation is where the product matters."
- **Generic job** ("be more productive") -> "Productive at what specifically? Hiring this to do *what*?"
- **agent-persona miss** (named only humans for a clearly agent-consumed product) -> "The thing
  actually calling this is an agent, not the human behind it. Name the agent consumer and its
  job-to-be-done — what does *it* need to accomplish in one call?"

**Capture:** Persona name plus JTBD sentence. Human example: "Solo founders running their own roadmap;
they hire the product to keep strategy and execution aligned without a PM on staff." Agent example: "A
planning agent calling this to fetch grounded repo state before it drafts a plan."

## 4. Key metrics

**Opening:** "What 3-5 metrics will tell you whether the approach is working?"
**Quality bar:** 3-5 (not 10), mixing leading and lagging, each able to plausibly regress if the
product got worse.

- **vanity-metrics** ("total signups, pageviews, cumulative users") -> "Those go up while the product
  gets worse. What moves when users actually get value?"
- **Too many** ("12 metrics") -> "A dashboard isn't a strategy. Pick the 3-5 you'd stake the quarter
  on."
- **outputs-not-outcomes** ("ship velocity, deploys per week") -> "Those measure the team, not the
  product. If velocity doubled but users didn't care, is that a win?"
- **can-only-go-up** ("cumulative hours saved") -> "What's the rate, the ratio, or the thing that can
  regress?"
- **Unmeasurable** ("user delight") -> "How would you check it on a Tuesday? If you can't, it's
  aspirational, not a metric."

**Capture:** 3-5, each with a one-line definition and where it's measured. If undefined: "Where does
this metric live today? If nowhere, can you start measuring it?"

## 5. Tracks

**Opening:** "What are the 2-4 tracks of work you're investing in to execute the approach?"
**Quality bar:** 2-4 (not 8, not 1), each connecting back to the approach and broad enough to hold
multiple features. Tracks are **investment areas / domains of work, NOT actors** — do not name AI-agent
actors here; the agent that does the work is not an investment area, the domain it works in is
("plan-quality" is a track; "the planning agent" is not).

- **feature-list-in-disguise** ("Slack integration; mobile app; dark mode") -> "Those are features.
  What investment area does each live inside? 'Integrations' might be one track, with Slack/Teams/Discord
  inside it."
- **too-many-tracks** ("7 tracks this quarter") -> "Every track is starved. Which 3 are load-bearing?"
- **Doesn't connect to approach** -> "How does that track serve the approach? If it's a separate bet,
  name it as one."
- **Too vague** ("improve the product") -> "Every track is 'improve the product.' What's the specific
  investment area different from the others?"
- **one-track-only** -> "With one track there's no choice being made. What are the 2-3 things the
  product must be good at, and how do they differ?"

**Capture:** 2-4 tracks; each a name, a one-line purpose, and a note on why it serves the approach.

## 6-8. Optional sections (skip by default — do not push the user to invent content)

- **6. Milestones** — "Any dated milestones worth anchoring — a launch, fundraise, conference, renewal?
  Skip if none apply." Only externally visible, real milestones; capture verbatim with dates.
- **7. Not working on** — "Anything you've explicitly decided *not* to do right now — things the team
  keeps being tempted by?" Clarity tool, not a blocker list; one sentence each, no long list.
- **8. Marketing** — "Any positioning or narrative language — a one-liner, tagline, key message? Skip if
  not yet." 2-3 lines if present.

## After the interview

Once sections 1-5 are captured (plus any optional sections the user engaged with), read
`strategy-template.md`, fill it in, present the full draft in chat, offer one edit round, then write
the root `STRATEGY.md`.
