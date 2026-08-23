# Cycle-9 review reconciliation — UniFi portability pilot

- Reviewed revision: `8e5847bc7b7608537688e24aa2bb419015386988`
- Contract: `review_result.v1`, roster `lens_roster.v1`, acceptance `combiner: all`
  over `derived_overall >= 9.0` AND every `applicable_dimension >= 7.0`
- Reviewers: Ox Alpha (max) 13,481 bytes; Muse Spark 1.2 (xhigh) 33,632 bytes.
  Both verified the full commit id and a clean tree; both artifacts complete with
  the marker absent.

## Outcome: accepted

Both reviewers return `accepted` / `continue`. This is the first cycle of nine in
which they agree.

- **Ox**: eleven of eleven scored lenses at or above `derived_overall 9.0`,
  minimum 9.00. No applicable dimension below the floor — the minimum scored is
  9.0, against a bar of 7.0.
- **Muse**: ten scored lenses, every applicable dimension at or above 9, every
  `derived_overall` 9.00.

Both rules of `combiner: all` hold on both reports. The arithmetic was re-checked
against each lens table rather than taken from the summary line.

## What both confirmed independently

- The `\n`-only scoping is replaced by the full boundary set in all three copies,
  and both vulnerable shapes now agree across the loader, the target copy and the
  repository gate at every boundary, including CRLF and sequences of breaks.
- The corpus pins every boundary in both shapes.
- The exact in-text key set is load-bearing: emptying it fails five tests. Muse
  records the standing advisory as closed by this change.
- The mutation proofs are bound to the real committed blobs and fail if a graded
  file changes without its proof being re-run.
- Every sentence of the reference was checked against the code and found true.

## Advisories carried, not repaired

- The padded-literal allowance under a strict key in a prose field: documented,
  and judged acceptable by both reviewers across three cycles.
- Identity-not-execution observations on evidence records.
- Negative HTTP `Retry-After`, out of scope, `infiquetra-claude-plugins#770`.

## The record this pilot should keep

Nine cycles turned on one rule. Three of them were positional repairs of the same
defect — the span was widened, then the newline was named, then the newline was
named again in a different place — and each time the guard added afterwards was
scoped to the instance just seen rather than to the class. The cycle-7 corpus,
built specifically to catch divergence between the copies, pinned only `\n` and
certified the repair it existed to interrogate.

What broke the pattern was not a better fix. It was deriving the rule's own
premise from the standard library at test time, so the set cannot be restated
wrongly, and pinning verdicts rather than parts, so agreement between copies is
asserted where it is actually observable. Both are recorded here because the
lesson is reusable and the sequence that produced it is not obvious from the
final diff.
