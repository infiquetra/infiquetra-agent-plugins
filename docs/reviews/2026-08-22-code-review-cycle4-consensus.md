# Cycle-4 review consensus — UniFi portability pilot

**Candidate.** `orch/orch-2026-08-22-unifi-cycle3` at `2bd0faf`, the resynchronized portable
catalog carrying UniFi 2.0.1 and Fleet Core 0.25.1.

**Panel.** Two independent OpenCode reviewers, different models, neither primed by the
coordinator and neither shown the other's report:

| Reviewer | Model | Effort | Artifact | sha256 |
|---|---|---|---|---|
| `review4-ox-alpha` | `opencode/x-preview-f-free` (Ox Alpha Free) | max | [cycle4-ox-alpha-max](2026-08-22-code-review-cycle4-ox-alpha-max.md) | `6bf2abe5…47d0e` |
| `review4-muse-spark` | `opencode/muse-spark-1.2` | xhigh | [cycle4-muse-spark-1.2-xhigh](2026-08-22-code-review-cycle4-muse-spark-1.2-xhigh.md) | `76942f14…3028d` |

Both artifacts are immutable evidence and are recorded here byte-for-byte as delivered.

## Gate outcome: `repairs_requested`

The roster's acceptance rule (`lens-roster.json`) is `combiner: all` over two rules —
`derived_overall >= 9.0` and `applicable_dimension >= 7.0`. Both must hold. Neither reviewer's
scores satisfy the first, and Ox's do not satisfy the second.

| | Ox Alpha (max) | Muse Spark 1.2 (xhigh) |
|---|---|---|
| Lenses scored | 9 of 14 | 10 of 14 |
| Lenses at `derived_overall >= 9.0` | 2 | 3 |
| Lenses below 9.0 | **7** | **7** |
| Lowest single dimension | `documentation-clarity / shipped-behavior-parity` = **6** | `security / secrets` = 7 |
| Reviewer's own verdict | `repairs_requested`, `next_action: return_to_work` | prose `accepted` |

Muse's report states the tension in its own words before writing past it: *"Outcome is
therefore `accepted` on dimension floor but `repairs_requested` if the roster's overall
threshold is applied literally."* The threshold is applied literally. A failing numeric
contract is not overridden by prose describing it as an excellence bar; the roster does not
carry that distinction, and a gate that yields to the argument that its own number does not
matter is not a gate. **Consensus outcome is `repairs_requested`.**

Ox additionally breaches the hard dimension floor at `shipped-behavior-parity = 6`, driven by
queued entries that contradicted the shipped tree. That is a floor breach, not a shortfall
against an excellence bar, and on its own it settles the outcome.

## Reconciled findings

The two reviewers overlap on exactly **one** finding. Every other item was found by one and
missed by the other, which is the case for running a panel of different models rather than one
reviewer twice.

| # | Finding | Ox | Muse | Class | Disposition |
|---|---|---|---|---|---|
| C4-1 | Credential-value rule grades the auth scheme word, so `authorization: Bearer <token>` passes | F-02 (P2, 100) | F-01 (P2, 75) | security | **Repaired** — `367d9b6` |
| C4-2 | Claude-path loader pinned to schema 1.0 while the package documents 1.1, and carries no credential-value rule | F-01 (P2, 100) | — | compatibility + security | **Repaired upstream** — unifi 2.0.2, PR #768 |
| C4-3 | Non-finite `Retry-After` (`inf`, `nan`, `1e400`) destroys the caller's typed 429 surface | F-05 (P3, 100, new) | — | reliability regression | **Repaired upstream** — fleet-core 0.25.2, `3b5faa6c` |
| C4-4 | Stale P0 "Emit the declared Fleet Core bundle" still reads "No repair has begun" | F-03 (P3, 100) | — | doc parity | **Repaired** — archived, `367d9b6` |
| C4-5 | Stale P2 "Drop README.md from the byte-copy table" already shipped | F-04 (P3, 100) | — | doc parity | **Repaired** — archived, `367d9b6` |
| C4-6 | `sync_vendor_source` suffix exclusion disagrees with `check_repo` placement rule | — | F-02 (P3, 75) | consistency | **Deferred** — operator scope; still fails closed |
| C4-7 | Ported Fleet Core test pins the pre-2.0.1 caller shape | — | F-03 (P3, 75) | testing | **Deferred** — already queued; Muse marks it "not a defect" |
| C4-8 | A short low-entropy secret in free text passes (`password=secret`, 2.25 bits) | — | F-04 (adv, 100) | security limit | **Accepted limit** — documented, defense in depth not proof of absence |
| C4-9 | Matrix binding proves identity, not that forty stages ran | — | F-05 (adv, 100) | adversarial | **Queued as Maybe** — correctly non-blocking |
| C4-10 | A committed `__pycache__/payload.pyc` is invisible to both gates; only `.gitignore` protects | — | F-06 (adv, 75) | security residual | **Deferred** — operator scope |
| C4-11 | This host's `TMPDIR` carries a malformed `.git` skeleton the bare-`.git` walk counts as a root | A-01 (adv, 100) | — | environment | **No action** — errs toward more refusal; shipped test unaffected |

### On C4-1, the reviewers' suggested fix was not taken

Both proposed grading every whitespace-separated token of the assigned value. That closes the
hole and introduces a worse one: ordinary English clears the 2.5-bit floor — `runbook` scores
2.52 — so `auth: see the runbook for the rotation procedure` would be rejected for describing
where the credential lives, which is what a profile exists to do. The rule instead widens
toward the credential: the first token, plus the token after it when the first is an auth
scheme word. A must-not-fire set covering prose, `vault:` references, `${VAR}`, and
`<redacted>` is pinned alongside the must-fire set.

### On C4-2, the finding was larger than either reviewer framed it

Ox reported the version skew and the missing value rule as one undisclosed defect on the
Claude path. Reading both halves side by side showed the shape underneath: this pilot
published the Claude-side loader pinned to `1.0`, then advanced its own portable contract to
`1.1`, and nothing bound the two. The portable package ships both halves, so it disagreed with
itself — an operator authoring the documented `1.1` document had it rejected by their own
integration, and a credential in free text was refused on one path and accepted on the other.
Both halves were internally consistent and fully green throughout.

## Verification standard applied

No finding was repaired on a reviewer's assertion. Each was reproduced first:

- **C4-1** — live probe of both copies; the captured group printed as `'Bearer'`, and
  `Basic`/`Token` did not match the pattern at all, so those values were never examined rather
  than examined and cleared.
- **C4-2** — nine-case probe running the Claude-side and portable loaders over identical
  documents; they now agree on every one.
- **C4-3** — end-to-end against the real client with `requests.request` replaced, so no call
  left the machine. `1e400` is the shape that matters: an ordinary overlarge integer.
- **C4-4, C4-5** — checked against the tree before archiving; both were genuinely shipped.

Every repair is pinned by tests proven to fail against the unrepaired code: 12 assertions for
C4-1, 14 for C4-2, 11 for C4-3.

## Next action

`return_to_work` is discharged. The repairs are landed or in flight; the candidate returns for
a final bounded validation, a fresh independent review, and a rerun of the ten-client
compatibility matrix against the exact release candidate before any merge or release.
