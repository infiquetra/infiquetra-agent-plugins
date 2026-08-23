# Cycle-8 review reconciliation — UniFi portability pilot

- Reviewed revision: `78c15449fd551fb27621855201fc07edae49d3ac`
- Contract: `review_result.v1`, roster `lens_roster.v1`, acceptance `combiner: all`
- Reviewers: Ox Alpha (max) 17,009 bytes; Muse Spark 1.2 (xhigh) 34,268 bytes.
  Both verified the full commit id and a clean tree; both artifacts complete.

## Outcome: NOT accepted — `repairs_requested`

Ox: three of eleven scored lenses below `derived_overall 9.0`. Muse: all ten
scored lenses at 9.00, `accepted`. The numeric contract fails, so the candidate
is not merged and not released.

## The cycle-7 repairs are confirmed by both reviewers

Both independently verified that the `\n` swallow is closed in all three copies,
that the split-assignment claim is now true everywhere, that the 27-line corpus
pins both shapes, and that the mutation proofs are bound to the real committed
blobs. Neither raised a defect in the F-01/F-02/F-03 repairs themselves.

## The blocker: line scoping names `\n`, and nothing else

**Both reviewers found the same divergence.** They agree on the facts and
disagree only on severity: Ox routes it P3 confidence 100, blocking; Muse routes
it advisory at confidence 75.

Python's `str.splitlines()` — which the repository gate uses — breaks on eleven
sequences. The repair scoped the loaders to `\n` alone. Probed across every one:

| shape | agreeing rows | divergent rows |
|---|---|---|
| `see notes:<BREAK>password=hunter2` (must fire) | `\n`, `\r\n` | 9 |
| `password:<BREAK>  hunter2` (must not fire) | `\n`, `\r\n` | 9 |

18 of 22 rows diverge. Nine of them are **fail-open**: with `\r`, `\v`, `\f`,
`\x1c`, `\x1d`, `\x1e`, NEL, U+2028 or U+2029 as the break, both loaders accept a
credential the gate refuses. That is the same fail-open class as cycle-7's F-02,
with different break characters.

Evidence: `docs/evidence/2026-08-23-cycle8-line-break-divergence-probe.py` and
its recorded output.

### Muse's severity argument, tested rather than arbitrated

Muse rated it advisory on the grounds that these characters "are not JSON
whitespace and would not survive `json.load`", and that no committed file
contains them. The first half is testable and does not hold:

- `"notes": "see notes:\rpassword=hunter2"` is ordinary, portable JSON. The
  escape decodes to a real carriage return, and the loader accepts the profile.
- U+2028 is legal *literally* inside a JSON string. It survives `json.load`, and
  the loader accepts that profile too.

Both are recorded in the probe output. The characters do not need to appear in a
committed repository file to matter: the loader's job is to validate an operator
profile from an arbitrary path, which is precisely the input this rule exists to
police. Muse's second point — that no committed file contains them — is true and
irrelevant to the loader.

Ox's routing is the correct one on the evidence.

## What this is, plainly

The cycle-7 repair fixed the newline instance by naming the newline, rather than
naming the concept the contract depends on. The commit's own claim is "an
assignment is one line"; the three copies do not agree on where a line ends. That
is the third occurrence of one shape in this pilot: a positional bug repaired by
adjusting the position instead of replacing it with the predicate the rule
actually means.

The fix Ox suggests, and the obvious one, is a single shared line-break class
covering everything `str.splitlines()` breaks on, defined once and used by all
three copies, with the corpus extended to pin every character in both shapes.

## Advisories, unchanged

- Emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` is a vacuous mutation. Both reviewers
  reached it; both accept the operator's advisory routing, and both note the
  hardening is two corpus entries.
- The padded-literal allowance, carried and judged acceptable as documented.
- Negative `Retry-After`, out of scope, `infiquetra-claude-plugins#770`.

## Disposition

Stopped. No merge, no release, no eighth repair started. The confirmed blocker is
reported for an operator decision, per the standing instruction not to begin an
unbounded additional cycle. The candidate remains at `78c15449` with a clean tree.
