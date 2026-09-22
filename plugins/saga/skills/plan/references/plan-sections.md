# Plan Sections — the durable plan artifact contract

This reference describes WHAT a great Infiquetra implementation plan contains. The plan is written as
markdown only (the HTML output branch is not used here). Sections earn their place by serving one of
the plan's three audiences; omit padding.

**Formatting authority.** The generated plan's visual structure follows the shared formatting
contract in `saga/references/formatting-style.md` — that file is canonical for how saga documents
*look* (short paragraphs, lead-with-a-summary, comparative data as a table, never stack bold labels).
This reference governs WHAT a plan contains and how its units are shaped; the formatting contract
governs the render rules they share.

## The outcome — three audiences

A great plan enables three audiences to act:

- **The implementing agent** (`/work` or a human) starts from an informed baseline — load-bearing
  decisions are named, unit boundaries are clear, research breadcrumbs orient their own investigation.
  The plan is a starting point, not a substitute for the implementer's own work.
- **The reviewer** identifies the load-bearing decisions and the boundary of what's changing in one
  pass.
- **The future reader** traces why the work was done, what shaped it, and where the artifacts live.

## Decide whether a plan doc is warranted at all

Not every `/plan` invocation should produce a plan document. For genuinely atomic work the doc is
ceremony — the implementer can act directly without IDed units, KTDs, or Requirements.

**Bias toward producing a plan.** The risk asymmetry favors writing one: a thin plan for small work is
mild ceremony, but skipping a warranted plan costs the implementer real time (reinvented decisions,
lost unit boundaries, no IDed requirements to verify against). When unsure, write the plan.

**Skip plan creation only when ALL of these hold:**

- The work is **atomic** — fits in one commit, no meaningful unit boundaries to break out.
- There are **no Key Technical Decisions** worth recording. If the work needs the implementer to choose
  between two approaches, those approaches are KTDs and a plan is warranted.
- There are **no scope boundaries worth pinning** — scope is self-evident from the request.
- **No upstream artifact** (a brainstorm with R-IDs, an incident report, a deferred-follow-up from a
  prior plan) needs traceability through this plan.

**Stress-test the "looks atomic" case.** Many requests look atomic but hide design decisions:

- *"Add caching to this endpoint"* — TTL, invalidation, cache-key shape, backend selection are KTDs.
  Write the plan.
- *"Migrate from package A to package B"* — semantic differences between the packages create migration
  KTDs. Write the plan.
- *"Add rate limiting"* — algorithm, scope, configurability are KTDs. Write the plan.

vs. genuine skip cases:

- *"Fix typo in README line 47"* — atomic, no KTDs. Skip.
- *"Rename `oldFn` to `newFn` across the repo"* — mechanical, no design choices. Skip.
- *"Bump dependency X to v2.3.1"* — mechanical. Skip (unless the bump breaks things and warrants
  unit-by-unit migration).

When skipping, route directly to `/work` and let any decisions land in the commit message.

## Hard floor

When a plan doc is warranted, these sections are always present. They carry the contracts downstream
consumers (`/work`, `/doc-review`, the saga) depend on.

- **Summary** — what the plan proposes, in 1-3 lines. Forward-looking; orients the reader.
- **Problem Frame** — why the work is being done. Backward-looking / situational. May merge with
  Summary for compact plans where the motivation is a single sentence.
- **Requirements** (stable **R-IDs**) — what must be true after the work ships. The reviewer's
  checklist; downstream code review verifies against these.
- **Key Technical Decisions** (**KTDs**) — the load-bearing choices that constrain implementation.
  Each entry is `<decision>: <rationale>`. Without these, the implementer can't tell which design
  choices are open and which are pinned. KTDs mirror to the saga's `## Decisions` and to the
  engineering journal (the journal is canonical).
- **Implementation Units** (stable **U-IDs**) — the discrete units of work, each independently
  landable. `/work` consumes these. Each unit carries per-unit test scenarios and repo-relative
  test-file paths.
- **Scope Boundaries** — what is explicitly out of scope. Keep `Deferred to Follow-Up Work` (planned
  work for a later PR/issue) distinct from true non-goals.

## Include when material (Deep / warranted only)

Present only when they carry information not covered elsewhere. The test is *"does this specific plan
have content this section would surface?"* — never "is this a substantial plan?". Placeholder prose is
worse than omission.

- **High-Level Technical Design (HTD)** — when the approach has shape prose alone doesn't carry:
  architecture across components, sequencing across processes, state machines, branching gates.
  Mermaid diagrams (component topology, sequence, state, flowchart) live here. Skip when the approach
  is a one-paragraph pattern application.
- **Risks & Dependencies** — real risks worth flagging (external service churn, version pins,
  behavioral assumptions) or material upstream dependencies. Each risk carries a mitigation.
- **Alternatives Considered** — architecture/sequencing/boundary alternatives the plan rejected.
  Tiny implementation variants belong in KTDs; product-shape alternatives belong in `/brainstorm`.
- **Success Metrics** — measurable outcomes when the work has a performance/quality target.
- **Open Questions** — genuinely unresolved items that block planning or implementation. Skip when the
  plan is complete; an empty "Open Questions: none" signals false uncertainty.
- **System-Wide Impact** — cross-cutting concerns (data lifecycles, auth boundaries, shared infra).
- **Sources / Research** — code locations (`path:line`), external docs, prior plans that orient the
  implementer or justify a load-bearing choice. Omit process exhaust.

The catalog is a floor, not a ceiling. When content fits no catalog section, introduce a new one rather
than forcing the content where it doesn't belong.

## R-ID / KTD / U-ID specs

- **R-IDs** — `R1.`, `R2.` bullet prefixes on Requirements. Plain prefix, not bold. Group Requirements
  by concern when they span distinct logical areas (R-IDs stay continuous across groups — never restart
  at R1 per group).
- **KTDs** — each is `<decision>: <rationale>`. The rationale names the tradeoff or rejected
  alternative, not just the choice. A KTD that connects to no Requirement, scope boundary, or unit is
  a smell.
- **U-IDs** — each unit is a level-3 heading `### U1. [Name]`, numbered sequentially from U1. Do **not**
  render units as bulleted/checkbox list items — flush-left per-unit fields detach from list items in
  CommonMark renderers; headings render correctly everywhere and give each unit an anchor. Progress is
  derived from git by `/work`, never stored in the plan body.
- **Stability rule (all IDs).** Once assigned, an ID is never renumbered. Reordering leaves IDs in
  place (U1, U3, U5 reordered is correct; renumbering to U1, U2, U3 is not). Splitting keeps the
  original U-ID on the original concept and assigns the next unused number. Deletion leaves a gap; gaps
  are fine. This matters most during the deepening pass — the most likely accidental-renumber vector.
- **Repo-relative paths.** Always. Never absolute paths in plan content — they break portability across
  machines, worktrees, and teammates.

### Per implementation unit

**Lead with a one-liner.** Each unit (and each major plan section) opens with a one-line,
plain-language summary before any fields or detail — the reader grasps the unit's intent in a single
glance, then drops into the fields. This is rule 2 of `saga/references/formatting-style.md`.

**Field shape — blank-line-separated bold labels.** Per-unit fields render as `**label:**` lines under
the `### U<N>.` heading, each separated by a blank line — this is the contract's "prose-heavy per-unit
fields that don't tabularize" branch (`saga/references/formatting-style.md`, "Which structure to use").
Do **not** convert plan units to a table, and **never** stack two `**label:**` lines without a blank
line between them (the fatal CommonMark collapse — rule 7 of the formatting contract).

Each `### U<N>. [Name]` includes:

- **Goal** — what this unit accomplishes.
- **Requirements** — which R-IDs (and origin A/F/AE IDs when supplied) it advances.
- **Dependencies** — what must exist first, cited by U-ID (e.g. "U1, U3").
- **Files** — repo-relative paths to create, modify, or test (never absolute). Every feature-bearing
  unit includes its test-file path here.
- **Approach** — key decisions, data flow, component boundaries, integration notes.
- **Patterns to follow** — existing code or conventions to mirror (cite `path`).
- **Test scenarios** — enumerate the specific cases the implementer should write, right-sized to the
  unit's complexity. Each scenario names the **input, action, and expected outcome** so the implementer
  doesn't invent coverage. Cover every applicable category:
  - **Happy path** — core functionality with expected inputs/outputs.
  - **Edge cases** — boundary values, empty inputs, null/nil states, concurrent access.
  - **Error / failure paths** — invalid input, downstream failures, timeouts, permission denials.
    (This is where the Phase-2 failure-mode enumeration lands.)
  - **Integration scenarios** — behaviors mocks alone won't prove, for units crossing layers.
  - For units with **no behavioral change** (pure config, scaffolding, styling), use
    `Test expectation: none -- [reason]` instead of a blank field. This annotation is valid **only**
    for non-feature-bearing units; a feature-bearing unit with blank test scenarios is incomplete.
- **Verification** — how the implementer knows the unit is complete, expressed as observable outcomes,
  not shell-command scripts.

## Scope-class extensions

One planning philosophy across all depths; change the amount of detail, not the planning/execution
boundary.

- **Lightweight** — compact plan, ~2-4 units, omit optional sections. No `---` rules needed.
- **Standard** — full hard floor, ~3-6 units, include Risks / Open Questions / System-Wide Impact when
  relevant. Use `---` horizontal rules between top-level sections for scannability.
- **Deep** — full hard floor plus the warranted "include when material" sections, ~4-8 units, group
  units into phases when it improves clarity. Use `---` rules between sections.

## Plan-doc frontmatter contract

Every plan carries YAML frontmatter at the top of the file. These are the **plan-doc** fields — they
are NOT the saga frontmatter fields (the saga is recorded separately via `saga.py save`).

```yaml
---
title: <verbatim plan title; matches the H1 so metadata and heading don't drift>
type: <feat|fix|refactor|chore|docs|perf|test>
status: active            # active on creation; /work flips to completed on ship
date: YYYY-MM-DD          # ISO 8601, ASCII digits
origin: <repo-relative path to the upstream brainstorm/requirements doc; set when planning from one>
backend: inline          # the execution backend; `inline` is the only value since issue #1030
deepened: YYYY-MM-DD      # optional; added when the confidence pass substantively strengthened the plan
---
```

- **`title` / `type` / `status` / `date` / `backend`** are required on every newly created plan.
- **`backend:`** carries the execution decision to whoever executes. `/work` honours it and does
  not re-offer. The only value to write is `inline`: issue #1030 archived the `team-execution`
  plugin and removed the `cc-workflows` plugin, so `ORCHESTRATION_MODES` is `("inline",)` and there
  is nothing else to record. A plan written before that release may still carry one of the two
  archived strings, and `/work` reads it as history. This lives in the plan document rather than
  in the saga tick because the tick is untracked local state and does not survive a worktree
  boundary, a different machine, or a different vendor — while the plan document is committed and
  travels with the work. Newly created plans MUST record it; legacy plans that lack it stay
  compatible through the attended offer above — never rejected, never rewritten.
- **`origin:`** MUST be emitted whenever an upstream artifact exists — `/doc-review` and the review
  phase use it to trace the plan back to its source. When there is no upstream doc (cold-start
  ad-hoc), `origin:` may be omitted or left empty.
- Field names are stable — never rename `status` to `state` or `origin` to `source`; downstream
  consumers key on the exact names.

## Agent-consumable bar

A plan is ready when an unfamiliar implementer (human or `/work`) can start confidently without needing
the plan to write the code for them and without re-asking the operator. Concretely:

- Clear problem frame and scope boundary.
- Requirements traceable back to the request or origin doc (R-IDs).
- Repo-relative file paths for the work, and explicit test-file paths for feature-bearing units.
- Decisions with rationale (KTDs), not just tasks.
- Per-unit test scenarios specific enough that the implementer knows exactly what to test.
- Clear dependencies and sequencing (U-ID dependency cites).

---

## Confidence pass (deepening)

The condensed rubric for Phase 4. Run only when the deepening gate fires (Deep, high-risk, or thin
grounding). Goal: strengthen a structurally sound plan that still needs stronger grounding — distinct
from `/doc-review`, which fixes clarity / completeness / scope.

### Score the confidence gaps (checklist-first, risk-weighted)

For each section, compute a score:

- **Trigger count** — number of per-section checklist problems (below) that apply.
- **Risk bonus** — +1 if the topic is high-risk (auth, payments, data migration, external APIs,
  privacy) and the section is materially relevant to that risk.
- **Critical-section bonus** — +1 for Key Technical Decisions, Implementation Units, System-Wide
  Impact, or Risks & Dependencies in Standard / Deep plans.

A section is a **candidate** if it scores **2+ total**, or **1+ in a high-risk domain** and is
materially important. Choose only the **top 2-5 sections** by score (cap at **1-2** when deepening a
Lightweight plan under the high-risk exception). If the plan already has a `deepened:` date, prefer
sections not yet strengthened when scores are comparable.

### Per-section gap checklist

- **Requirements** — vague or disconnected from units; success criteria missing or not reflected
  downstream; units don't clearly advance the traced requirements; origin IDs not carried forward.
- **Key Technical Decisions** — a decision stated without rationale; rationale that doesn't explain the
  tradeoff or rejected alternative; an obvious design fork the plan never resolves.
- **Implementation Units** — dependency order unclear or wrong; missing file/test-file paths; units too
  large/vague or fragmented into micro-steps; thin approach notes; **vague test scenarios** (no named
  inputs/outcomes), skipped applicable categories (no error paths for a unit with failure modes, no
  integration scenarios for a cross-layer unit), or feature-bearing units with blank test scenarios
  (the `Test expectation: none` annotation is valid only for non-feature units); **renumbered U-IDs**.
- **System-Wide Impact** — affected interfaces / entry points / parity surfaces missing; failure
  propagation underexplored; state-lifecycle / data-integrity risks absent where relevant.
- **Risks & Dependencies** — risks listed without mitigation; rollout / monitoring / migration
  implications missing when warranted; external dependency assumptions weak or unstated.
- **Open Questions** — product blockers hidden as assumptions; planning-owned questions wrongly
  deferred to implementation; deferred items too vague to be useful later.

### Is this plan thin? (risk-weighted scoring summary)

Sum the candidate scores. A plan with multiple critical sections scoring 2+, or any high-risk section
scoring, is thin and warrants the pass. A plan where scoring finds nothing exits cheaply — report
"Confidence check passed."

### Strengthen, then stop (top-N cap)

Strengthen **only the selected top 2-5 sections** in place — clarify rationale, tighten requirements
trace, reorder/split units (never renumber existing U-IDs), add missing pattern/test-file paths, expand
risk/rollout treatment. Dispatch generic `Explore` / `Task` agents (not `ce-*` agents), at most ~1-3
per section. Do not rewrite the whole plan, do not add implementation code, do not invent new product
requirements (record a product-level ambiguity under Open Questions and recommend `/brainstorm`). Add
`deepened: YYYY-MM-DD` to frontmatter when the plan was substantively improved.
