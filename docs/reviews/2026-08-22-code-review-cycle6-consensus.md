# Cycle-6 review reconciliation — UniFi portability pilot

- Reviewed revision: `9ad24f29fe3c7290123b0434ce1e3c37330343f6` (`orch/orch-2026-08-22-unifi-cycle3`)
- Contract: `review_result.v1`, roster `lens_roster.v1`, acceptance `combiner: all`
  over `derived_overall >= 9.0` AND every `applicable_dimension >= 7.0`
- Reviewers: OpenCode Ox Alpha (max), OpenCode Muse Spark 1.2 (xhigh) — both
  independent, both verified the full commit id and a clean tree before scoring
- Repository gate at this commit: `check_repo.py` passes, 420 tests pass

## Outcome: NOT accepted — `repairs_requested`

The panel split. Muse returned `accepted` (10 scored lenses, all `derived_overall
9.00`). Ox returned `repairs_requested`: three of eleven scored lenses fall below
the 9.0 overall minimum — correctness 8.80, api-contract 8.67,
documentation-clarity 8.50. No applicable dimension breaches the 7.0 floor.

Under `combiner: all` both rules must hold, and one fails. The numeric contract
governs; it is not overridden by prose. The split is not a contradiction: Muse
tested the six false-positive shapes named in the brief and found them fixed.
Ox tested a class the brief did not name and found it broken. Muse's statement
that no legitimate prose is falsely rejected is scoped to the examples it ran.

## Independent validation of Ox's findings

Every finding below was re-verified directly against the code at this commit,
not accepted on the reviewer's report. Probe and output are preserved at
`docs/evidence/2026-08-22-cycle6-credential-rule-probe.py` and
`…-probe-output.txt`. All three copies of the rule behave identically.

### F-01 — false-positive class, introduced by the cycle-5 repair — CONFIRMED

Ordinary technical prose in the first substantive position is refused as a
credential value, in the portable loader, the target copy, and the repository
gate:

| Input | Candidate | Result |
|---|---|---|
| `credentials: oauth2 is configured at the controller` | `oauth2` | fires |
| `token: base64 of the site identifier` | `base64` | fires |
| `secret: sha256 checksum recorded in the manifest` | `sha256` | fires |
| `auth: vlan40 handles the guest network` | `vlan40` | fires |

No tracked file currently carries such a sentence, so the gate is green today.
This is a latent trap rather than a live break: the first operator note or
tracked document using this routine vocabulary fails the gate or is refused by
the loader.

### A-01 — recall regression, introduced by the cycle-5 repair — CONFIRMED

Digit-free secrets shorter than 24 characters now pass undetected regardless of
entropy. These are exactly what family 2 exists to catch, and the cycle-4
entropy-only rule caught all three:

| Input | Candidate | Entropy | Cycle-4 rule | Now |
|---|---|---:|---|---|
| `password: rainbowtrout` | `rainbowtrout` | 3.085 | rejected | **passes** |
| `password: sunshine` | `sunshine` | 2.500 | rejected | **passes** |
| `api_key: correcthorsebattery` | `correcthorsebattery` | 3.116 | rejected | **passes** |

Ox routed this advisory on the grounds that the CHANGELOG discloses the
mechanism. That understates it. This is lost detection in a security rule, not a
disclosure gap.

### The root defect the two findings share

The digit-or-24-character discriminator is anti-correlated with secret-ness.
Every false positive above sits at 2.585 bits of entropy; every missed secret
sits at 2.500–3.116. The discriminator fires on the *lower*-entropy inputs and
passes the *higher*-entropy ones — it inverts the signal it replaced. Cycle-4
used entropy alone and produced prose false positives; cycle-5 replaced entropy
with a digit proxy and produced technical-prose false positives plus a recall
loss. Neither rule separates the two populations, and no test pins either class.

### F-02 — operator contract documents the retired rule — CONFIRMED

`plugins/unifi/references/site-profile.md:48-51` still states that a
credential-shaped key assigned "a value of at least six characters that clears
2.5 bits of entropy per character is rejected." The code has not done that since
this commit. `password: sunshine` satisfies both stated conditions exactly (8
characters, 2.500 bits) and ships accepted. The "deliberately does not do"
section does not disclose the digit-or-24 limit or the walk-and-stop behaviour.

The document's own standard, three lines below the stale claim, is "Stating this
precisely matters more than stating it generously." An operator auditing this
guarantee reads a stronger contract than the code delivers. This is not legacy
documentation cleanup — the commit under review is what made it false.

## Carried advisories (unchanged, pre-existing)

- A-02 — the repository gate is line-based and misses multi-line assignment
  shapes that both loaders reject.
- A-03 — the loader rule is custody-pinned to upstream bytes, not drift-pinned
  to the local pair.
- Negative HTTP `Retry-After` handling — out of scope here, tracked as
  `infiquetra-claude-plugins#770`.

## Disposition

Merge, release, and the final compatibility matrix are **not** executed. Per the
governing instruction, no seventh review cycle was started; the confirmed
blockers are reported for an operator decision. The candidate remains at
`9ad24f2` with a clean tree; this evidence is uncommitted so the reviewed tree is
unchanged.
