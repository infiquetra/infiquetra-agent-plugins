# Ideation artifact template

The persisted markdown document `/ideate` writes to `docs/ideation/YYYY-MM-DD-<topic>-ideation.md`
(or `docs/ideation/YYYY-MM-DD-open-ideation.md` when no focus exists). Phase 5 of
`saga/skills/ideate/references/convergence-and-partnership.md` uses this template.

Field names here are IDENTICAL to the SURVIVOR SCHEMA and REVIVABLE-CUT SCHEMA in that file — keep
them aligned. Omit a clearly irrelevant field only when necessary. On resume, update in place and
preserve `Explored` markers, stable `R#` ids, and their statuses.

The visual shape of the generated artifact follows the canonical formatting contract,
`saga/references/formatting-style.md`: lead each ranked survivor with a one-line summary, keep
`description` / `rationale` / `downsides` as short blank-line-separated prose, and render the compact
fields (`basis` / `confidence` / `complexity` / `axis` / `status`) as a small two-column table.

The artifact carries `idea-ready` handoff maturity (feeds `mission-control` and `/plan` directly).

```markdown
---
date: YYYY-MM-DD
topic: <kebab-case-topic>
focus: <optional focus hint — omit when open ideation>
scope: <tactical | narrow | standard | broad>
repo: <current repo name>
maturity: idea-ready
---

# Ideation: <Title>

## Grounding Context

**Repo:** [project shape, conventions, pain points, leverage points, strategy summary — from the
Phase 1 current-repo scan + journal-learnings sources]

**Context-libraries:** [relevant `*-context-library` repos read in Phase 1 and what each contributed.
One line per library, or `None consulted` when the topic did not touch a library.]

**Named repos:** [other infiquetra repos consulted when the topic spanned repos, and what each
contributed. Omit this section when the run was single-repo.]

## Topic Axes

[3-5 axes from Phase 1.5, one per line. OR a single line `Decomposition skipped — atomic subject`
when Phase 1.5 was skipped. Omit this section entirely if not applicable.]

## Ranked Survivors

### 1. <Idea Title>

[One-line plain-language summary of the move, before any fields.]

[Concrete explanation of the move — the `description`. Short prose, ≤3 sentences.]

[How the basis connects to the move's significance — the `rationale` — then the `downsides`
(tradeoffs or costs), as a separate short paragraph. Blank-line separated, ≤3 sentences each.]

| field | value |
|-------|-------|
| basis | [`direct:` quoted file/line/issue/user-context \| `external:` named prior art/source \| `reasoned:` written-out first-principles argument] |
| source | [`frame-agent` \| `user-seed` \| `interview` \| `combined` \| `engine-generated`; provenance only, not a scoring rule] |
| confidence | [0-100] |
| complexity | [Low \| Med \| High] |
| axis | [Topic axis this idea targets — omit this row when decomposition was skipped] |
| status | [Unexplored \| Explored] |

### 2. <Idea Title>
[... same shape — summary, prose, then the field table — strongest-first by rubric score ...]

## Did not survive (revivable)

Explicit rejection is the quality mechanism. Cut ideas keep stable ids so they can be revived (which
re-enters the Phase 3 filter with new evidence). Never renumber on a status change.

| id | title | summary | reason | status |
|----|-------|---------|--------|--------|
| R1 | <short title> | <one-line summary> | <Phase 3 rejection reason> | rejected |
| R2 | <short title> | <one-line summary> | <Phase 3 rejection reason> | revisited |
| R3 | <short title> | <one-line summary> | displaced by revived R5 | rejected |

[status is one of: rejected | revived | revisited. A `revived` id is promoted into Ranked Survivors
above and may be omitted from this table or left with status `revived` for history. Append any
zero-survivor axis as its own row, e.g. `| - | axis: <name> | no survivors on this axis | deliberate
gap | — |`.]

## Co-ideation log

Records partnership provenance: which ideas came from the operator (seeds) vs. the frame agents, and
how each seed fared under the identical critique. Seeds were passed INTO the Phase 2 frame agents to
build on / challenge / combine, AND entered the merged pool — never rubber-stamped, never silently
dropped.

| source | entered | idea / seed | outcome |
|--------|---------|-------------|---------|
| user-seed | Phase 0 | <operator's seed idea> | survived as #2 (built on by frame 4) |
| user-seed | Phase 6 co-ideate | <added mid-run> | cut → R4 (basis did not support the move) |
| frame-agent | Phase 2 | <generated idea> | survived as #1 |
| engine-generated | Phase 2 | <external-engine generator idea> | survived as #3 (same basis gate) |
| interview | Phase 6 | <drawn-out idea> | cut → R6 (below ambition floor) |

[source is one of: user-seed | frame-agent | engine-generated | interview | combined. `entered` notes where it joined the run.
`outcome` records the survivor rank or the revivable `R#` and reason.]
```

## Notes

- Title case the H1; kebab-case the `topic` frontmatter.
- `scope` mirrors the Phase 0 adaptive-frame-count decision: tactical → 1 frame; narrow → 2-3;
  standard → 4; broad → full 6-frame fan-out.
- Keep the survivor count to 5-7 unless tactical scope or an honest under-5 result says otherwise.
- This is the only persistence destination — no Proof, no cloud doc-review.
