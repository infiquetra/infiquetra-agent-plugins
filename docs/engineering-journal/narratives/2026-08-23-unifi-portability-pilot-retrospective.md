# The UniFi portability pilot, and where its twenty-eight hours went

Date: 2026-08-23
Author: Jeff Cox and Claude
Related entries:

- [A verification step that reports success for an unrelated reason](../LEARNINGS.md) — the generalizable rule this pilot produced.
- [Bound review rounds, and batch a round's repairs into one release](../DECISIONS.md) — the convention adopted because of it.
- [Portable plugin port runbook](../../runbooks/portable-plugin-port.md) — the checklist that replaces re-deriving this.
- [The repository gate's link checker resolves against the filesystem](../QUEUED.md) — the one gap left open.

## Context

The pilot ported the Claude Code `unifi` plugin into a portable Agent Plugins 1.0
package. It merged as `558564cb` with both independent reviewers accepting. The
next port of a Claude plugin into this catalog starts from what this pilot built,
so the question worth answering is not whether it succeeded but which of its
twenty-eight hours the next one has to spend again.

The figures below come from commit timestamps, pull-request records, and the
preserved evidence. They are *elapsed* times spanning unattended agent runs and
operator-away periods, so they measure calendar cost, not effort.

## Narrative

### Where the time went

The repository spans `2026-08-22T02:29Z` to `2026-08-23T06:12Z` — 27 hours and 43
minutes, four pull requests, forty-six commits.

| Phase | Elapsed | Share | What happened |
|---|---|---|---|
| Plan and document review (PR #1–2) | ~2h | 7% | A 723-line plan with explicit non-goals, reviewed |
| Build and first assessment (PR #3) | ~11.5h | 41% | The port, the tooling, the first ten-client matrix, cycle-1 review |
| Review and repair (PR #4, 40 commits) | ~13.3h | 48% | Cycles 2 through 9 |

Nearly half the pilot was review and repair, and the dominant cost inside it was
a single validation rule. The credential-value rule first appears at `18:41Z` on
22 August and its last repair lands at `06:11Z` on 23 August: **eleven and a half
hours, 41% of the entire pilot, on one rule in one file.** Six of nine review
cycles and five of seven upstream releases were that rule.

A second figure explains why each repair cost so much. The compatibility matrix
and the post-activation readback are bound to the package fingerprint by test, so
any byte change invalidates both. The pilot produced **nine ten-client matrix runs
and eight readback captures**. That binding is correct — it caught stale evidence
repeatedly, which is exactly what it exists for — but repairs shipped one defect
per release, so the multiplier applied six times over.

### The one rule

The contract is a sentence: a site profile states intent and points at where a
secret lives; it never carries one. Implementing that sentence took five upstream
releases.

| Release | What the rule did | What it was |
|---|---|---|
| 2.0.2 | Credential-shaped key plus high-entropy value | Value grading |
| 2.0.3 | Window widened, then replaced by a walk with a digit-or-24 discriminator | Value grading, twice |
| **2.0.4** | **The key decides; the value is not graded** | **Class-level** |
| 2.0.5 | Assignment scoped to `\n` | Instance |
| **2.0.6** | **The line-break set named, derived from `splitlines()`** | **Class-level** |

Two insights ended two runs of defects, and both arrived only after several
instance repairs had failed. Everything between them was chasing the input that
had just broken.

The entropy phase deserves recording because it could not have worked. Separating
a credential from prose by properties of the literal string is not decidable, and
the heuristics were measurably anti-correlated with the target: every false
positive sat at 2.585 bits of entropy per character, every missed password
between 2.500 and 3.116. The rule fired on the lower-entropy inputs and passed the
higher-entropy ones. Changing the question — grade the key, not the value — made
the problem decidable in one move.

### Why instance fixes kept replacing class rules

Five causes, and they compound.

**The failing example was treated as the specification.** Each repair was derived
from the input that had just failed rather than from the predicate the contract
requires. *`oauth2` was refused* became *make `oauth2` pass*. *`\n` was swallowed*
became *handle `\n`*. The question that ended each run — what decision does this
rule have to make, and what is the authority for it? — was never asked until
cycles 6 and 8, and both times asking it closed the line of defects immediately.

**Each guard inherited the fix's scope.** The corpus added in cycle 7 was built
specifically to catch divergence between the three copies of the rule. It pinned
`\n` and nothing else, so it certified the very repair it existed to interrogate.
A guard scoped to the instance cannot detect the class.

**The brief propagated the narrowness to the reviewers.** The review briefs said,
in effect, *here is what I just fixed, verify it*. The reviewers verified it.
Cycle 8's brief was the first to say "probe them, do not reason about them" and to
enumerate candidate inputs, and it produced the class-level finding on the first
attempt. The reviewers were exactly as good as the question they were asked.

**Agreement was asserted where it was easy to observe, not where it mattered.**
Three copies of one rule, with drift tests comparing constants, compiled patterns
and helper outputs. Every part matched while the verdicts differed.

### Verification steps that reported success for unrelated reasons

The pilot's unifying defect appeared in the product and in the coordinator's own
tooling in the same form six times.

| Incident | Why it reported wrongly |
|---|---|
| Completion watcher never fired | `grep -c` prints `0` *and* exits non-zero, so the success branch and the `\|\| echo 1` fallback both fired. It failed only in the success case. |
| Mutation run invalid, twice over | Anchors written with real characters where the file stores them escaped, so nothing was replaced; and a baseline that was already failing. |
| Mutation "survived" detector | Matched the *restored* run's `OK` rather than the mutant's. |
| Repository gate green locally | A journal link resolved only because a sibling checkout exists on one machine. CI caught it. |
| Cursor recorded as failing | An isolated `HOME` stripped real authentication; the operator corrected a false result in the deliverable. |
| Grok and Agy recorded nothing | Auto-trust wrappers resolve the real binary through `$HOME`, which an isolated home does not contain. |

The last two share a cause with the third-from-last: **the test environment
differed from the environment the claim was about.** An isolated client home is
not the operator's client; one developer's disk is not CI's disk.

### What went right, and should not be re-litigated

Scope held. The plan carried explicit non-goals and they survived contact with
nine review cycles: the negative `Retry-After` defect was filed as
`infiquetra-claude-plugins#770` in the repository that owns it rather than fixed
in the pilot, the marketplace manifest stayed deferred, and three standing
advisories stayed advisory. The one drift risk was the coordinator's — closing an
advisory that had not been authorized — and it was stopped and raised instead.

Custody discipline held too. Every repair to a byte-copied or transformed path
went upstream first and came back through a resync, across seven upstream
releases. Not once did a repair get made in the derived copy for convenience.

And the fingerprint binding, which cost the most mechanical time, is the reason
the evidence is trustworthy. It is not a candidate for weakening.

## Outcome

The pilot's real deliverable is not the UniFi package. It is a porting platform:
a custody model, a sync engine, a repository gate, fingerprint-bound evidence, a
ten-client assessment method, and a review protocol. Roughly 2,400 of about 3,270
lines of tooling are already package-agnostic.

What this retrospective changes:

- One generalizable rule enters `LEARNINGS.md`, absorbing two entries that were
  instances of it. Recorded there, not repeated here.
- One convention enters `DECISIONS.md`: bounded review rounds, and a round's
  repairs batched into a single release.
- A versioned runbook at `docs/runbooks/portable-plugin-port.md` replaces
  re-deriving the method. It carries the checklist; this narrative carries the
  reasons.

A projection, offered as a projection rather than a measurement: a comparable
plugin should take six to nine hours on that path, because the tooling exists,
one matrix run replaces nine, and one or two review rounds replace nine.

## References

- Merge commit `558564cb`; pull requests `infiquetra-agent-plugins#1` through `#4`.
- Upstream releases `infiquetra-claude-plugins#765`, `#766`, `#767`, `#768`, `#769`, `#771`, `#774`, `#775`.
- [`docs/reviews/`](../../reviews/) — twenty-eight review artifacts across nine cycles, including each cycle's reconciliation.
- [`docs/evidence/2026-08-22-unifi-compatibility-matrix.md`](../../evidence/2026-08-22-unifi-compatibility-matrix.md) and its eight superseded predecessors.
- [`docs/evidence/2026-08-23-cycle9-mutation-proof-portable-copies.txt`](../../evidence/2026-08-23-cycle9-mutation-proof-portable-copies.txt) and the upstream loader proof beside it.
- [`docs/plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md`](../../plans/2026-08-21-unifi-fleet-core-portability-pilot-plan.md) — the plan whose non-goals held.
