# Two-reviewer consensus — UniFi portability pilot, commit 95de0d5

Reviewers, independent, neither primed with controller findings and neither able to see the other:
- Cursor Agent, GPT-5.6 Sol Extra High — 32.6 KB, 12 lenses, 9 findings, outcome `repairs_requested`
- OpenCode Zen, Muse Spark 1.2 Contributor Free, xhigh — 18.7 KB, 8 lenses, 9 findings, outcome `repairs_requested`

Both reached `repairs_requested` independently. Both confirm the code surfaces validate:
`check_repo.py` passes, `bundle --check` passes, 280 tests pass, both entrypoints run.

## Found by BOTH, independently — highest confidence

| # | Issue | Cursor | OpenCode | Consensus severity |
|---|---|---|---|---|
| C1 | Compatibility matrix describes the pre-repair package, not the shipped tree | F-01 P1 | F-01 + F-02 P1 | **P1** |
| C2 | Drift reports every profiled network as a missing policy | F-03 P1 | F-03 P1 | **P1** |
| C3 | Provenance validation is not closed over package files | F-04 P1 | F-04 P2 | **P1** |
| C4 | Bundle provenance fields optional, so a stale bundle can pass CI | F-05 P1 | F-05 P2 | **P1** |
| C5 | Portable README is Claude-specific / references missing docs | F-07 P2 | F-07 P3 | **P2** |
| C6 | Secret-free / redaction validation is partial | F-08 P2 | F-08 P3 | **P2** |
| C7 | `Retry-After` HTTP-date form not handled | F-09 P2 | F-09 P3 | **P2** |

## Found by ONE reviewer — verified by the controller before routing

| # | Issue | Source | Controller verification | Severity |
|---|---|---|---|---|
| C8 | Malicious/corrupt `PROVENANCE.json` can unlink files outside the package | Cursor F-06 | **CONFIRMED.** `previously_managed()` accepts any non-blank path string with no containment check; caller does `plugin_dir / stale` then `path.unlink()`. Proved `plugin_dir / '/etc/hosts'` resolves to `/etc/hosts`. `check_repo.py:186-208` has an unsafe-path guard that `synchronize()` never calls. | **P1** |
| C9 | Post-activation proof was never performed | Cursor F-02 | Consistent with the controller's own record: U9 held activation, U9a closed the tri-lock, but no fresh-install readback was captured. | **P1** |
| C10 | Discovery persistence deny-list fails open without a `.git` directory | OpenCode F-06 | Plausible; `repository_root_from` returning None leaves `refuse_repository_output` non-refusing. To be confirmed by the fixer. | **P2** |

## Controller findings, for completeness

| # | Issue | Status |
|---|---|---|
| CF1 | Upstream docs-match-code suite misses advertising prose in a skill body | OPEN. In `infiquetra-claude-plugins`, outside both reviewers' scope. |
| CF2 | Documented default runtime path is never read | QUEUED by operator decision; journal entry filed. |
| CF3 | Drift tests were not hermetic | FIXED and verified. |
| CF4 | Assembled package had no working entrypoint | FIXED and verified. Both reviewers independently confirm the fix works AND that the matrix was never re-run against it — which is C1. |

## The pattern across all three sources

Nine of the twelve issues are guarantees that exist but do not bite: a provenance gate that passes
with files missing from the manifest, bundle fields that are optional so a stale bundle survives CI,
a redaction check that inspects field names rather than values, an unsafe-path guard that is never
invoked, a deny-list that fails open, and a matrix validator that checks digest shape rather than
whether the digest identifies the package. The controller's own CF3 and CF4 are the same shape.
The package is not under-tested; it is under-enforced.

## Immutability anchors

The two reviewer reports are preserved byte-identical as delivered. Neither may be edited; repairs
are recorded against them, never inside them.

| Report | SHA-256 | Bytes |
|---|---|---|
| `2026-08-22-code-review-cursor-gpt-5.6-sol-xhigh.md` | `75da1077034ece8526fdecdd1b0759fefef35f292d630751aeccbc921ad3f0ed` | 33333 |
| `2026-08-22-code-review-opencode-muse-spark-1.2-xhigh.md` | `5e8a5204de9a94ecbd4df533a3a135ae530a0306be48cb19c375140c846db92d` | 18707 |

Reviewed artifact: commit `95de0d5` (pull request #3), diffed against `8824fea`.
