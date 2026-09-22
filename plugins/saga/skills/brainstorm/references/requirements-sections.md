# Requirements-Doc Section Contract

Loaded by `/brainstorm` Phase 3. Describes WHAT the requirements document contains and how to
right-size it by scope. The doc is always a single markdown file at
`docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md`.

The discipline of this contract: **resolve product decisions here; defer implementation to `/plan`.**
User-facing behavior, scope boundaries, and success criteria belong in this doc. Schemas, endpoints,
file layouts, and code-level design do not — unless the brainstorm is itself about that technical
decision, in which case those details are the subject and belong here.

**Formatting contract.** The generated requirements doc follows the shared
`saga/references/formatting-style.md`: open each section and
each ranked item with a one-line plain-language summary, keep narrative fields as short
(≤3-sentence) blank-line-separated paragraphs, and render any comparative, scored, or enumerated data
(option comparisons, requirement groups, tradeoffs) as a table or bullet list rather than a prose wall.

## The outcome

A great requirements doc lets three audiences act:

- **The planning agent** (`/plan` or a human) produces an implementation plan without inventing user
  behavior, scope boundaries, or success criteria — this doc answered those.
- **The reviewer** sees the framing choices, distinguishes pinned from open, and catches scope gaps
  before planning.
- **The future reader** traces why the proposed thing matters, who it's for, and what success is.

Sections earn their place by serving one of these audiences. Omit padding.

## Decide whether a doc is warranted at all

Not every brainstorm needs a durable doc. Skip it when **both** hold:

- The dialogue produced no novel scope, framing, or decision worth preserving in IDed shape — the
  operator needed only brief alignment.
- Any durable decision can flow straight to `/plan`, the commit message, or `docs/` without a
  brainstorm artifact in between.

Create the doc when the dialogue surfaced enough structural decisions, scope boundaries, or acceptance
criteria that the planner, reviewer, or future reader needs them in durable, IDed form — not just as
conversation.

**Stress test:** a brainstorm about a tiny bug fix where the operator asks "null check or upstream
validation?" and you confirm "upstream validation, here's why" does NOT need a doc — the decision
flows to `/plan` directly. A brainstorm about a multi-actor feature with contested scope and several
behavioral conditions probably does — the planner needs the structured content.

## Right-sizing by scope

Depth matches what the dialogue produced and the Phase 0.4 tier. A sparse brainstorm produces a sparse
doc; a rich one produces a rich doc. Do not add ceremony to make a slim brainstorm look substantial.

- **Lightweight** — Summary plus a short Requirements list, often without R-IDs. May be a handful of
  bullets. No actors, flows, or acceptance examples unless they genuinely apply.
- **Standard** — Hard floor plus the include-when-material sections the dialogue actually populated:
  typically Key Decisions, Requirements (grouped, R-IDs), Scope Boundaries, and Success Criteria.
- **Deep — feature** — Standard depth plus Key Flows, Acceptance Examples for conditional
  requirements, and Dependencies / Assumptions as warranted.
- **Deep — product** — Deep plus the product-shape sections: an explicit product thesis, Scope
  Boundaries split into "Deferred for later" and "Outside this product's identity", and the durability
  assumptions surfaced in the Phase 1.2 product probes.

## Metadata

The block is YAML delimited by a literal `---` first line and a closing `---` line. Every brainstorm artifact must start with that block at the file's first byte; a bullet list is not frontmatter and will not be recognized. Example:

```yaml
---
date: 2026-08-30
topic: saga-worktree-prune
capability: brainstorm
activity: brainstorm-saga-worktree-prune-20260830T143000Z
maturity: pending-confirmation
---
```

Field names are stable — never rename or repurpose them; adding new fields is fine.

- **`date`** — ISO 8601 (`YYYY-MM-DD`), ASCII digits. Used in the filename.
- **`topic`** — kebab-case slug identifying the subject (e.g. `surface-scope-earlier`), derived via the shipped slugify helper at `plugins/saga/scripts/saga.py:slugify` from the operator's free-form phrasing, and the same slug appears in the filename `YYYY-MM-DD-<topic>-requirements.md`; resume matches on `topic` plus `capability` when Phase 0.1 scans `docs/brainstorms/`, and
  a file carrying `topic` alone is a legacy artifact routed to tier 2 of the Phase 0.1 order, not a
  match. The filename's date `YYYY-MM-DD` is the same ISO date as the frontmatter `date` field.
- **`capability`** — the producing capability, fixed as `brainstorm` (one of the two producer facts).
- **`activity`** — the producing activity identity, formed as
  `brainstorm-<topic-slug>-<UTC timestamp YYYYMMDDTHHMMSSZ>` at the moment the artifact is first
  written, whether as a pending-confirmation artifact or a Path A document.
- **`run`** — optional run identity, the `.orchestrate/run.json` `run_id` when that file exists; a
  missing run identity is recorded as absent, never invented.
- **`maturity`** — `pending-confirmation` (boundary recorded, not confirmed, no durable route) or
  `requirements-ready` (confirmed, routes available).
- **`source`** — when the topic came from `/ideate`, the relative path of the ideation doc and the
  survivor reference (e.g. the survivor title or its `R#`), so provenance is traceable.

There is no `status` field — a requirements doc is a one-time output, not a lifecycle artifact.

## Hard floor

When a doc is warranted, these are always present.

- **Summary** — what is being proposed, in 1-3 lines. Forward-looking. Orients the reader before they
  invest in detail.
- **Requirements** (stable R-IDs) — what must be true about the proposed thing. For very sparse
  brainstorms (≤3 simple items where the bullets ARE the summary), plain bullets without IDs are fine;
  the trigger for R-IDs is whether downstream consumers will reference them. When requirements span
  distinct concerns, group them under bold inline headers — group by capability or concern, not by the
  order discussed. R-IDs stay continuous across groups (R1, R2 in the first group; R3, R4 in the
  second; never restart per group). A long flat list is a smell that subgroups were missed.

**A readiness suggestion over these sections.** The `readiness` judgment in
`plugins/saga/scripts/shaping_judgments.py` asks one yes/no question per readiness criterion over a
finished document — the criteria are drawn from the hard floor above and the material sections
below. It is advisory: it suggests whether the document is ready for the `/doc-review` handoff, and
`/doc-review` still decides. It fails open to offering the review with no suggestion.

## Include when material

Decide per brainstorm whether each section carries information not covered elsewhere. Placeholder
prose is worse than omission.

- **Problem Frame** — include when motivation is not obvious from Summary alone (the *why* needs
  paragraphs). Backward-looking / situational. Does NOT restate the proposal — the remedy lives in
  Summary.
- **Key Decisions** — include when the brainstorm produced opinionated framing choices (defaults,
  scope narrowings, foundational picks) that constrain Requirements / Flows / Scope below. Name each
  in bold with prose rationale. Sits high so readers meet the framing before the detail.
- **Actors** — include when the proposed thing has multi-party behavior (multiple humans, agents, or
  systems meaningfully involved). Skip for non-behavioral briefs.
- **Key Flows** — include when the proposed thing has multi-step behavior. Expected by default for
  behavioral brainstorms unless the thing is genuinely non-flow-shaped (pure API surface, policy,
  artifact output) and Actors / Requirements / Scope / Acceptance Examples together prevent downstream
  invention. When omitting from a behavioral brainstorm, note the reason.
- **Acceptance Examples** — include when any requirement has a state-dependent or conditional shape
  ("When X, Y") where prose alone leaves edge-case ambiguity. Always cover behavioral-conditional
  requirements — that is where ambiguity bites hardest. Skip when all requirements are unconditional
  and unambiguous.
- **Success Criteria** — include when there are quality / metric / handoff signals Requirements do not
  already carry: quantitative ("p95 under 200ms"), qualitative ("reads as one voice"), or handoff
  ("`/doc-review` can act on this without follow-ups"). Skip when Requirements ARE the success
  criteria.
- **Scope Boundaries** — include when scope is contested or there are tempting non-goals worth naming.
  At Deep-product, split into "Deferred for later" (eventually but not v1) and "Outside this product's
  identity" (a positioning decision). Otherwise a single list is fine.
- **Dependencies / Assumptions** — include when material upstream dependencies exist or load-bearing
  assumptions need surfacing — including any unverified-absence assumption from the Phase 1.1 scan and
  any durability assumption from the Phase 1.2 probes.
- **Outstanding Questions** — include when items are unresolved. Distinguish "Resolve before planning"
  (blocks `/plan`) from "Deferred to planning" (answered during planning or codebase exploration).
  Phase 4 hides Plan and Build-it-now while any "Resolve before planning" item remains.
- **Sources / Research** — surface research that orients the planner or justifies framing: code
  locations, `STRATEGY.md` direction, journal `LEARNINGS`/`DECISIONS` entries, context-library
  guidance, prior plans, external docs. Test: *would this breadcrumb help a planner reading cold?*
  Process exhaust (reading the prompt, glancing at obvious files) → omit.

## Agent agency

The catalog is a floor, not a ceiling. When content does not fit any catalog section, introduce a new
one — content drives section choices, not the reverse. You also pick whether Acceptance Examples render
as a separate section or embed in each requirement, and how much depth each present section gets.

## ID and content rules

- **Stable IDs.** R-IDs (Requirements), A-IDs (Actors), F-IDs (Flows), AE-IDs (Acceptance Examples).
  No other ID namespaces.
- **Plain prefix.** `R1.`, `A1.`, `F1.`, `AE1.` as bullet prefixes. Do not bold them.
- **Bold leader labels** inside Flows and Acceptance Examples (`**Trigger:**`, `**Covers R4, R8.**`)
  give structure without deeper heading levels.
- **Repo-relative paths.** Always. Never absolute paths — they break portability across machines and
  worktrees.
- **No process exhaust.** No "captured at Phase X" notes, no "## Next steps" pointing at `/plan`, no
  italic provenance lines in the body. Process metadata belongs in commit messages and tool output.
- **No implementation details by default.** Libraries, schemas, endpoints, file layouts, and code
  structure stay out unless the brainstorm is inherently about that technical or architectural change
  and those details are the subject of the decision.

## Minimum artifact

The minimum artifact carries exactly four parts — confirmed scope and material decisions, rationale,
intended acceptance outcome, and unresolved planning questions — and no architecture or implementation
plan.

## Summary vs Problem Frame

When both are present, they earn separate sections only by holding to different purposes:

| Section | Question it answers | Time direction | Length |
|---|---|---|---|
| `## Summary` | What is this doc proposing? | Forward-looking | 1-3 lines |
| `## Problem Frame` | Why does this proposal exist? | Backward-looking / situational | Paragraphs |

- **Summary** needs no problem context — a reader scanning it gets the proposal at a glance.
- **Problem Frame** does not restate the proposal. It establishes the situation, the moment of pain,
  and the cost shape, then stops. The remedy lives in Summary; restating it here is the duplication
  that makes the two sections feel redundant.
