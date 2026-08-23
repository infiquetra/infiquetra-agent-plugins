# Cycle-5 review consensus — UniFi portability pilot

**Candidate reviewed.** `orch/orch-2026-08-22-unifi-cycle3` at `08ab2de`, carrying UniFi
2.0.2 and Fleet Core 0.25.2. The tree was held unchanged for the duration of the panel.

**Panel.** Two independent OpenCode reviewers, different models, neither shown the other's
work. Both models were confirmed by live readback *before* either brief was sent — the first
launch put both sessions on the same model, which was caught and corrected rather than
allowed to stand as a silent substitution.

| Reviewer | Model | Effort | Artifact | sha256 |
|---|---|---|---|---|
| `scored-code-review-of-brief5-ox` | `opencode/x-preview-f-free` (Ox Alpha Free) | max | [cycle5-ox-alpha-max](2026-08-22-code-review-cycle5-ox-alpha-max.md) | `80562bf0…` |
| `brief5-muse-md-scored-code-revie` | `opencode/muse-spark-1.2-contributor-free` | xhigh | [cycle5-muse-spark-1.2-xhigh](2026-08-22-code-review-cycle5-muse-spark-1.2-xhigh.md) | `08eafd77…` |

## Gate outcome: `repairs_requested`

| | Ox Alpha (max) | Muse Spark 1.2 (xhigh) |
|---|---|---|
| Lenses scored | 11 | 10 |
| Failing `derived_overall >= 9.0` | **9** | **7** |
| `applicable_dimension >= 7.0` | **breached** — `documentation-clarity / shipped-behavior-parity` = 6 | held |
| Reviewer's own verdict | `repairs_requested` | `repairs_requested` |

Under `combiner: all` both rules must hold, and neither reviewer's scores satisfy the first.
Unlike cycle 4, neither wrote `accepted` over a failing number.

## Reconciled findings

| # | Finding | Ox | Muse | Class | Disposition |
|---|---|---|---|---|---|
| C5-1 | A placeholder between the scheme word and the credential ends the search, so `Bearer <redacted> <token>` passes | — | F-01 (P2, 100) | security | **Repaired** — unifi 2.0.3 |
| C5-2 | Grading the first token unconditionally rejects ordinary prose as a credential | F-01 (P2, 100) | F-02 (P2, 100) | security, correctness | **Repaired** — unifi 2.0.3 |
| C5-3 | Negative delta-seconds reaches the typed 429 surface as "Retry after -5 seconds" | F-02 (P3, 100) | — | correctness, reliability | **Deferred and recorded** — pre-existing, outside the bounded repair scope |
| C5-4 | `QUEUED.md` per-client entry contradicts the matrix it cites | F-03 (P3, 100) | — | doc parity | **Repaired** — the contradiction was created in the same cycle |
| C5-5 | `QUEUED.md` ported-test entry frames an answered custody question as open | F-04 (P3, 100) | — | doc parity | **Repaired** — marked resolved |
| C5-6 | `check_repo`'s line-based gate misses multi-line assignment shapes both loaders reject | A-01 (adv) | — | consistency | **Deferred** — advisory |
| C5-7 | The loader's restated rule is custody-pinned upstream, not drift-pinned to the local copies | A-02 (adv) | — | maintainability | **Deferred** — advisory |
| C5-8 | Committed `__pycache__/*.pyc` invisible to both gates | — | F-03 (adv) | security residual | **Deferred** — advisory |
| C5-9 | Short low-entropy secret still passes (`password=secret`) | — | F-04 (adv) | documented limit | **Accepted limit** |
| C5-10 | Binding proves identity, not that forty stages ran | — | F-05 (adv) | adversarial | **Queued as Maybe** |

### C5-1 and C5-2 were both introduced by the previous repair

The cycle-4 repair replaced a one-token window with a two-token window, and broke in both
directions at once. The bypass: `<redacted>` *names* a secret rather than being one, so it
was correctly skipped — and the window ended there, leaving the real credential in the third
slot unexamined. A separate truncation did the same by another route, because the captured
span excluded `}` and cut `Bearer ${VAR} <token>` off before the token. The false positive:
entropy per character cannot separate English from a credential, since `rotation` scores 2.50
against a 2.50 floor while `hunter2` scores 2.81, and character-class mixing separates them no
better because `Rotation` mixes case and `hunter2` does not.

The repair replaces the position with a predicate: walk the value, step over scheme words and
placeholders, grade the first token that is neither, and stop. Qualify that token with a
discriminator that does separate the populations — a digit, or 24 characters without one.
Stopping is load-bearing: a scan that kept looking would reach `ABC-1234` in
`auth: see ticket ABC-1234 for rotation` and grade the ticket number.

### The negative test that was blind to its own category

The cycle-4 must-not-fire set used `auth: see the runbook for the rotation procedure`. Its
first token is three characters and falls under the length floor, so the case passed for a
reason unrelated to the rule being correct. It reported coverage that did not exist. The
replacement set is chosen so each case would fail for the *right* reason if the rule were
wrong, and 28 assertions fail against the defective rule.

## Verification standard applied

No finding was repaired on a reviewer's assertion. C5-1 and C5-2 were reproduced against the
shipped code before any edit, C5-3 was reproduced and then deferred rather than quietly
dropped, and C5-4 was checked against the matrix it contradicts. The repair was then verified
across 21 must-fire and must-not-fire cases in all three copies of the rule, and a 12-case
probe confirms the Claude-path loader and the portable loader agree on every document.

## Next action

`return_to_work` is discharged for the in-scope findings. The candidate carries UniFi 2.0.3,
the ten-client matrix was re-run against the exact release candidate, and the evidence
documents were re-captured rather than edited. What remains open is recorded: C5-3 awaits an
operator decision, and the advisories are queued.
