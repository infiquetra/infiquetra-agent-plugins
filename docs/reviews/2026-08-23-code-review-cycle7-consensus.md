# Cycle-7 review reconciliation — UniFi portability pilot

- Reviewed revision: `0feecfa04966346d45391008b1a7b17422d79f2c` (`orch/orch-2026-08-22-unifi-cycle3`)
- Contract: `review_result.v1`, roster `lens_roster.v1`, acceptance `combiner: all`
  over `derived_overall >= 9.0` AND every `applicable_dimension >= 7.0`
- Reviewers: OpenCode Ox Alpha (max), OpenCode Muse Spark 1.2 (xhigh), both
  independent, both verified the full commit id and a clean tree before scoring
- Artifacts: 21,710 bytes (Ox) and 35,724 bytes (Muse), both with the completion
  marker absent

## Outcome: NOT accepted — `repairs_requested`

The panel split for the second cycle running. Muse returned `accepted` /
`continue`, all ten scored lenses at `derived_overall 9.00`. Ox returned
`repairs_requested` / `return_to_work` with three findings, all at confidence
100.

The numeric contract governs and one half of it fails, so the candidate is not
merged and not released.

## Why the two disagree — the same sentence, two different probes

Both reviewers checked the reference documentation's claim that *"an assignment
split across two lines is not matched by either the loader or the gate."*

Muse tested it with `notes: "password: rainbowtrout\nis the value"` — a split
*value*, where the credential and its key sit together on the first line. That
shape is not matched, so Muse recorded the sentence as true. Its own working note
carries a question mark mid-verification — "does not span lines as a key
delimiter?" — and then asserts the claim anyway.

Ox tested `password:\n  hunter2`, where the line break falls *between* the key
and the value, and `see notes:\npassword=hunter2`, where it falls between an
innocent key and a strict one. Those are the shapes the sentence is about, and
both behave the opposite of how it reads.

This is not a reviewer being wrong about the code. It is a reviewer confirming a
claim with an input that cannot test it — the same failure this pilot recorded
against its own test suite two cycles ago, when a must-not-fire case was filtered
by a length floor before it ever reached the rule.

## Independent validation of Ox's findings

Re-verified directly against the candidate, not accepted on the report:

| shape | loader | target copy | gate | agree |
|---|---|---|---|---|
| `see notes:\npassword=hunter2` | passes | passes | **fires** | no |
| `password:\n  hunter2` | **fires** | **fires** | passes | no |
| `notes: controller password=hunter2` | fires | fires | fires | yes |

### F-02 — cross-line fail-open — CONFIRMED, and the most serious of the three

The whitespace around the assignment delimiter was `\s*`, which spans a newline.
An innocent key at the end of a line therefore matched, consumed the line break
with it, and left the strict assignment on the next line with no preceding
character to begin a fresh match against. `see notes:\npassword=hunter2` is
accepted by both loaders and refused by the repository gate, which splits lines
before scanning.

This is fail-open in the copy operators actually load, and it is the residual
half of the swallow defect 2.0.4 repaired along a single line. The 2.0.4 fix
addressed the along-a-line case and left the across-a-line case standing.

### F-01 — the reference documents the weaker of the two copies — CONFIRMED

`references/site-profile.md:101` stated that a split assignment is matched by
neither copy. The loaders matched it; only the gate did not. The guarantee was
written in the direction that flattered the loader, which is the same defect
class as the cycle-6 blocker: a document claiming behaviour the code does not
have.

### F-03 — the mutation proof misidentifies the bytes it proved — CONFIRMED

`docs/evidence/2026-08-22-cycle7-mutation-proof-upstream-loader.txt` records a
pristine digest of `9e03ce93…`. That digest matches no committed loader blob in
either repository — checked against the last four upstream commits that touched
the file. The bytes released at upstream `a46714b8` and carried in candidate
`0feecfa0` are `80f2bc5d…`. The proof was run against an intermediate working
tree, after the formatter ran but before the nesting fix and the changelog
commit.

The mutation conclusions themselves were independently re-verified and hold. What
is wrong is the identification — which is exactly what this class of evidence
exists to establish, so a proof that names the wrong bytes is worth no more than
no proof at all.

## Advisories, carried and not repaired

Per the operator's routing, these stay advisory:

- **A-01** — the padded-literal allowance. Both reviewers reached it
  independently and both judged it acceptable as documented: a real secret
  followed by prose words under a strict key in a prose field is not reported.
  The regression against 2.0.3 is confined to that shape, it is disclosed
  verbatim in the reference, and it reaches only two fields.
- **A-02** — emptying `CREDENTIAL_KEY_EXACT_IN_TEXT` is a vacuous mutation: the
  test that reads it loops over the tuple, so an empty tuple makes the loop a
  no-op and the test passes. Only the function-side mutation is caught.
- **A-03** — the gate/loader split-line divergence generalises cycle-6's carried
  line-based-scan advisory, now with concrete shapes.

## Repair routed

One bounded set, at the custody boundary that owns each item: F-02 repaired
upstream first and resynced, F-01 corrected in the target-owned reference, F-03
re-run against bytes verified equal to the committed blob. A shared verdict
corpus now pins every shape in all three copies, because per-part agreement tests
passed while the verdicts differed — which is how this defect survived cycle 6
and cycle 7 both.
