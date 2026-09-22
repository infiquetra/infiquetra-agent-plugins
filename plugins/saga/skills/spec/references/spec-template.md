# Spec Template

Loaded by `SKILL.md` at Phase 5 after the interrogation is complete. Fill it in using the captured
answers and write to `docs/specs/<YYYY-MM-DD>-<slug>-spec.md`. Template structure ported from gstack
`spec`'s Standard issue body, reshaped as a durable lifecycle artifact.

## Rules for filling in

- Use the user's own language; do not paraphrase into generic PM-speak. Each section stays compact.
- **Section order is locked. Do not add new top-level sections.** Match the template to the content —
  a bug-shaped spec doesn't need an architecture sketch; a greenfield spec doesn't need a verified
  "Current State" baseline (say so rather than padding).
- Acceptance Criteria are **observable and measurable** — pass/fail, no subjective language.
- File references are **repo-relative and exact** (`path/to/file:line`), never "the auth module".
- Set `date` to today's ISO date (YYYY-MM-DD). Set `origin` to what Phase 0 captured (`direct`,
  `issue:#N`, or the repo-relative upstream doc path).
- **Optional sections (Open Questions): delete the section entirely if unused. Never leave an empty
  header.**
- **Formatting.** Follow the shared
  `saga/references/formatting-style.md`: open `Context`,
  `Proposed Change`, and each filled section with a one-line summary, keep narrative fields as short
  (≤3-sentence) blank-line-separated paragraphs, and render comparative or scored data as a table or
  bullets — the `Failure Modes & Rollback` and `Files Reference` tables and the numbered `Acceptance
  Criteria` already follow this.

## Template

The block below is the literal file to write (minus the fences). Replace every `{{placeholder}}` with
the captured answer.

~~~markdown
---
title: {{short imperative title}}
type: spec
status: draft
date: {{YYYY-MM-DD}}
origin: {{direct | issue:#N | docs/<path>}}
---

# {{short imperative title}}

## Context

{{2-3 sentences: what exists today, why it's insufficient, why now. Framed from the affected
stakeholder's perspective — who is affected and why they care.}}

## Current State

{{Verified description of current behavior, with file paths and line numbers. If greenfield with no
code surface, say "Greenfield — no existing behavior" rather than inventing one.}}

## Proposed Change

{{What the behavior should be instead. The WHAT, not the HOW — no architecture decisions, no method
names. Those are /plan's job.}}

## Acceptance Criteria

1. {{observable, measurable, pass/fail — no subjective language}}
2. {{...}}
3. {{...}}

## Scope Boundaries

**Out of scope:**

- {{thing that seems related but is explicitly NOT part of this spec}}

## Failure Modes & Rollback

| Failure mode | What happens if shipped wrong | Rollback |
|--------------|-------------------------------|----------|
| {{empty / null / huge / duplicate / wrong-role / called-twice / domain failure}} | {{behavior}} | {{undo}} |

## Files Reference

| File | What changes |
|------|--------------|
| `{{path/to/file:line}}` | {{the change at this site}} |

## Effort

{{Per-component breakdown — rough but quantified. "Unknown — measure by [method]" beats a vague size.}}

## Related

- {{#NNN — related issue/PR, or a docs/ artifact path}}

## Open Questions

- {{anything genuinely unresolved at spec time — name it rather than faking certainty}}
~~~

## Post-write checklist

Before confirming the write, scan the draft for:

- [ ] Frontmatter present with `title`, `type: spec`, `status`, `date` (today's ISO date), and `origin`.
- [ ] Every acceptance criterion is observable and pass/fail — no "works correctly" / "handles edge
  cases".
- [ ] `## Scope Boundaries` names at least one out-of-scope item (unless the work is genuinely trivial).
- [ ] Failure-mode register walked; each row has a rollback.
- [ ] Every file reference is repo-relative and exact — no "somewhere in X".
- [ ] No `{{placeholder}}` remains; `## Open Questions` deleted if empty, not left blank.
- [ ] The file is written to `docs/specs/<YYYY-MM-DD>-<slug>-spec.md` (repo-relative).

## Handoff routing note

This artifact is a **`mission-control` source** mapping to handoff maturity **`requirements-ready`** — the
sharp WHAT that `mission-control` -> issue -> `/work` points at. `/spec` produces the
source; **`mission-control` owns the issue body** (sections, labels, board placement). Do not copy SDLC
issue templates into this spec. When the WHAT is locked but a HOW must still be settled before
implementation, route to `/plan` instead; an optional `/doc-review` readiness pass can run on this spec
before handoff.
