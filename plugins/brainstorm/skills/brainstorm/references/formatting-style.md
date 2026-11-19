# Document Formatting Style

The formatting contract for documents this skill writes.

It governs how those documents *look* — the visual structure that makes them scannable. It does not change what they *say*; analytical content, schemas, and section sets stay in the skill that owns them.

## Why this exists

Consecutive `**label:**` lines with no blank line between them collapse into a single paragraph in CommonMark — the "all jumbled together" failure. Compact fields belong in a table or under a heading, with blank lines between narrative paragraphs.

## The rules

Every generated document follows these.

1. **Short paragraphs.** ≤3 sentences each, separated by blank lines. No 4+ sentence blocks.

2. **Lead with a summary.** Each ranked item and each major section opens with a one-line, plain-language summary before any fields or detail.

3. **Comparative data is a table.** Ranked, scored, or compared data (survivors, options, findings, tradeoffs) renders as a table or a bullet list — never a prose wall.

4. **Machine fields stay distinct.** Engineer-facing schema fields stay present but visually separated from the narrative (a compact table or block), and keep stable field names so consumers stay reliable.

5. **Soft-wrap generated prose.** No hard line wrap inside a paragraph — let the viewer wrap it — with blank lines between paragraphs. This is a *generated-output* rule; the template source files in this repo stay editor-friendly and may hard-wrap.

6. **No redundant fields.** Drop a field the structure already carries — e.g. a `title:` field directly under a `### N. Title` heading.

7. **Never stack bold labels.** Two or more `**label:**` lines with no blank line between them collapse in CommonMark.

## Which structure to use

Pick the render shape by the *kind* of data, not by habit.

| Data kind | Use | Example |
|-----------|-----|---------|
| Compact, comparable, scored fields | A table | idea `basis`/`confidence`/`complexity`/`axis`/`status`; code-review finding `severity`/`file`/`line` |
| Narrative fields | Short prose paragraphs | `description`, `rationale`, `downsides`, problem framing |
| Prose-heavy per-unit fields that don't tabularize | Blank-line-separated `**label:**` lines under a `### heading` | plan unit `Goal` / `Files` / `Approach` / `Test scenarios` |

The table form solves three things at once: it never collapses in CommonMark, it scans at a glance, and — since the consumers are an LLM reading the doc plus a human, not a regex parser — it is *more* legible than a stacked-label run, not a parse risk.

## Worked example — the golden specimen

This is the shape a ranked item should take: a heading, a one-line summary, short prose, then a compact field table.

### 2. Render the schema as a table

One-line plain-language summary of the idea goes here, before any fields.

A short narrative paragraph carries the reasoning — rationale and downsides as prose, ≤3 sentences, soft-wrapped, blank-line separated.

| field | value |
|-------|-------|
| basis | direct: path/to/file.md:42 |
| confidence | 88 |
| complexity | Low |
| status | Unexplored |

And ranked or compared items render as one scannable table, not N prose blocks:

| # | item | confidence | complexity |
|---|------|:----------:|:----------:|
| 1 | First option | 90 | Low |
| 2 | Second option | 80 | Med |

## For skill authors

When you edit this skill's template, apply the render decision above — table the compact fields, keep narrative as short prose, and lead every ranked item or section with a one-liner.

Do not reflow this package's template *source* prose to satisfy rule 5 — the soft-wrap rule is for the documents the skill *generates*, not for the hard-wrapped reference files you are editing.
