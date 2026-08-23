# Cycle-2 consensus — integrated repair candidate b4418a1

Panel: OpenCode/Ox Alpha Free (Unlimited) at **max**, and OpenCode/Muse Spark 1.2 Free at **xhigh**.
Both OpenCode Zen, both verified by live readback before briefing, independent sessions, neither
primed. Cursor was not reused. Both returned **repairs_requested**.

## Repair verdicts — the panel agrees on 9 of 10

| # | Ox Alpha | Muse | Adjudicated |
|---|---|---|---|
| C1 matrix binding | FIXED | FIXED | **FIXED** — controller attack confirms: altering or adding a package file fails validation |
| C2 drift false missing-policy | FIXED | FIXED | **FIXED** |
| C3 provenance closed set | PARTIAL | FIXED | **PARTIAL — Ox Alpha correct** (see below) |
| C4 bundle stamp fields | FIXED | FIXED | **FIXED** — controller attack confirms all six fields required |
| C5 portable README | FIXED in tree | FIXED, queued residual | **FIXED for the shipped artifact, residual real** |
| C6 secret-free validation | PARTIAL | PARTIAL | **PARTIAL** — repo gate closed, site-profile runtime still name-only |
| C7 Retry-After HTTP-date | NOT FIXED | NOT FIXED | **NOT FIXED — expected**, deliberately excluded: upstream byte copy, custody does not move |
| C8 provenance unlink escape | FIXED, bites | FIXED | **FIXED** — controller attack confirms absolute, `..` and symlink all refused |
| C9 post-activation proof | EVIDENCED AND BOUND | FIXED | **FIXED** |
| C10 deny-list fail-open | FIXED | FIXED | **FIXED** |

## The one disagreement, adjudicated by the controller

Ox Alpha F2 claims the closed-set exemptions match by name and suffix at any depth. Two shapes were
probed on the integrated boundary:

- **Nested `PROVENANCE.json`** at `plugins/unifi/skills/nested/` — **CAUGHT**, exit 1. Ox Alpha's
  first shape does not reproduce here.
- **Arbitrary `.pyo` file** — **NOT CAUGHT**. `PROVENANCE_UNMANAGED_SUFFIXES = (".pyc", ".pyo")`
  (`scripts/check_repo.py:78`) exempts those suffixes anywhere in the tree at any depth. A file
  `plugins/unifi/skills/unifi-network/scripts/smuggled.pyo` containing arbitrary text passes
  `check_repo.py` **and** passes `check_compatibility_matrix.py`, so the tree fingerprint does not
  notice it either.

**Both gates miss it.** C3 is therefore PARTIAL, not FIXED, and Muse's verdict is too generous.
Ox Alpha's suggested fix stands: exempt bytecode only under `__pycache__/` or beside a matching
`.py` source per PEP 3147.

## Open items after cycle 2

| # | Issue | Severity | Route |
|---|---|---|---|
| O1 | `.pyc`/`.pyo` suffix exemption smuggles arbitrary content past both gates | P2 | review-fixer |
| O2 | Site-profile runtime `validate_profile` checks names, not values (C6 residual) | P2 | needs decision — portable contract change |
| O3 | `Retry-After` HTTP-date unhandled (C7) | P2 | needs decision — upstream custody, release cycle |
| O4 | `README.md` still in `PORTABLE_BYTE_COPIES`; next sync overwrites the portable README | P3 | review-fixer |
| O5 | Sync custody table contradicts the recorded custody decision (Ox F1) | P2 | review-fixer |
| O6 | Gitless-walk negative case untested (Ox F5) | P3 | review-fixer |
| O7 | Binding proves identity, not execution (Ox F6) | advisory | operator |

## Gate status

**The review gate has NOT passed.** Nothing is merged or released.
