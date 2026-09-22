# Strategy Template

Loaded by `SKILL.md` after the interview is complete. Fill it in using the captured answers and write
to the repository root `STRATEGY.md`. Locked template ported from Compound-Engineering `ce-strategy`.

## Rules for filling in

- Use the user's own language; do not paraphrase into generic PM-speak. Each section stays compact —
  the whole doc reads in under 5 minutes.
- **Section order is locked. Do not add new top-level sections.**
- Constraints: **3-5 metrics** and **2-4 tracks**. Stop at the ceiling; fold related items together.
- **Optional sections: delete the section entirely if unused. Never leave an empty header.**
- Set `last_updated` in the YAML frontmatter to today's ISO date (YYYY-MM-DD); do not duplicate it in
  prose. Set `name` to the product or initiative name (the same value used in the H1 title).
- **Formatting.** Follow the shared
  `saga/references/formatting-style.md`: keep each section a
  short (≤3-sentence) blank-line-separated paragraph, lead with the plain-language point, and render
  any comparative or enumerated data as the bullet lists the template already prescribes (`Key metrics`,
  `Milestones`, `Not working on`) rather than a prose wall.

## Template

The block below is the literal file to write (minus the fences). Replace every `{{placeholder}}` with
the captured answer; delete any optional section whose placeholder wasn't answered.

~~~markdown
---
name: {{product_name}}
last_updated: {{YYYY-MM-DD}}
---

# {{product_name}} Strategy

## Target problem

{{1-2 sentence diagnosis. Names the user situation and the crux that makes it hard. No solution
language.}}

## Our approach

{{1-2 sentence guiding policy. What this product commits to, so that the target problem becomes
tractable.}}

## Who it's for

**Primary:** {{Persona name}} - {{one-sentence JTBD. May be an AI-agent consumer when the product is
agent-facing — same jobs-to-be-done rigor.}}

<!-- Duplicate the block above for additional personas only if truly necessary. Fewer is better. -->

## Key metrics

- **{{metric 1 name}}** - {{one-line definition; where it's measured}}
- **{{metric 2 name}}** - {{...}}
- **{{metric 3 name}}** - {{...}}

<!-- 3-5 total. Stop at 5. -->

## Tracks

### {{Track 1 name}}

{{One line: what this track is - the investment area / domain of work, not a feature list and not an
actor.}}

_Why it serves the approach:_ {{one line}}

<!-- Duplicate the block above for 2-4 tracks total. If you can't keep it to 4, fold related tracks. -->

## Milestones

- **{{YYYY-MM-DD}}** - {{milestone}}

<!-- Optional (delete if unused). Only externally visible milestones: launches, fundraises, renewals. -->

## Not working on

- {{one line per item}}

<!-- Optional (delete if unused). Only things the team keeps being tempted by. -->

## Marketing

**One-liner:** {{single-sentence pitch}}

**Key message:** {{2-3 lines if useful}}

<!-- Optional (delete if unused). -->
~~~

## Post-write checklist

Before confirming the write, scan the draft for:

- [ ] Frontmatter present with `name` + `last_updated`; `last_updated` is today's ISO date (YYYY-MM-DD).
- [ ] No section over 4 sentences except Tracks (each track its own short block); no placeholders
  (`{{...}}`) remain.
- [ ] Optional sections with no content deleted, not left empty.
- [ ] Metric count 3-5; track count 2-4.
- [ ] Target problem and Our approach are connected — one clearly responds to the other.
- [ ] The file is written to the repository root as `STRATEGY.md` (repo-relative root path).
