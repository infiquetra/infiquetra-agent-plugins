# Saga Code Review — U9 closeout documentation (`u9-closeout-agy1`)

This review covers the frozen closeout commit on `orch/mcport-9-resume1-u9-closeout-agy1` because child #19 requires repository documentation to describe the shipped mission-control package without contradicting committed evidence, and U0 established that README identity claims are a trust boundary.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `repairs_requested`
- Next action: `dispatch_repairs`
- Reviewed revision: `4648760cbe9064486254ffe0f81e3bf1a4ea87bf` (`4648760`, `docs(closeout): document the shipped mission-control package (run unit U9)`)
- Parent: `febb75be4c872b9c802e654e41622a5eac33597d` (U8 integration review persisted on the run tip; one commit)
- Target: 5 files, +166 / −33
- Review backend: `inline`
- Active findings: 1 (`F01`)
- Cycle: 1 of 3; next cycle reruns `documentation-clarity` only

> **Verdict: revision `4648760` is not accepted.** The named judgment item (the "distribution, not compatibility" sentence) is endorsed as written. A different README identity claim, introduced in this same commit, contradicts UniFi provenance: the new Packages table pins UniFi at `ed72f439` (v0.25.1). Repair that one cell. Do not touch `plugins/**`.

## Scope and built-versus-planned audit

**Scope Check: CLEAN** (owned files). Drift is inside README content, not extra files.

- Intent (#19): README Status + package table on U0's baseline; `llms.txt` Packages bullet; `docs/README.md` index if needed; architecture brief dated pointer only; DECISIONS curation. No `plugins/**`, no evidence files, no fingerprint move. Tests only if a new README claim is load-bearing enough to pin.
- Delivered: those five files, +166/−33. No tests added (card-allowed). Orchestrator-owned filings/board/closing comment are out of this SHA.

### Plan-completion (U9 documentation commit)

| Item | State | Evidence |
| --- | --- | --- |
| README Status names shipped mission-control | DONE | 64-file package, pin `84eaf042` v2.12.2, 266 CI tests, 7 skills, matrix 1/8/1 with Cursor `parents[3]` described, LEARNINGS link, cycle-16 68/0, runbook v1.0.0 |
| README package table | PARTIAL | mission-control and fleet-core pins match PROVENANCE; UniFi pin does not (`F01`) |
| `llms.txt` Packages bullet | DONE | one mission-control bullet; fleet-core description updated for intent envelope / tier palette |
| `docs/README.md` index | DONE | plan + matrix entries |
| Architecture brief dated pointer only | DONE | 4 lines on proof-sequence step 2; open questions untouched |
| DECISIONS curation | DONE | U9 closeout decision (runbook v1.0.0, stop at matrix) + U5 data-bundle decision; U6 already present |
| LEARNINGS curation | DONE / already shipped | `parents[3]` entry is at the top of `LEARNINGS.md` from U8; this commit correctly does not rewrite it |
| No `plugins/**` / fingerprint untouched | DONE | empty diff on `plugins/`; matrix checker still green, `651ac28a…` / 64 files |
| Suites green | DONE | `check_repo` pass; 741 OK; 266 pytest |
| Upstream filings / board / parent comment | UNVERIFIABLE here | orchestrator-owned; not in this diff |

COMPLETION: 8/10 DONE, 1 PARTIAL (table pin), 1 UNVERIFIABLE (orchestrator).

## Judgments

### ITEM — endorse "What remains open is distribution, not compatibility."

The sentence sits four lines after an honest Cursor **failed** row. A strict isolated reading ("compatibility is green") would clash with that row.

Read as a statement about **what remains open**, it is accurate. The compatibility *survey* is closed: ten clients, forty stages, one recorded failure. What is still open is the operator disposition of those results — repair, adapter, distribution path, or unsupported — "and none has been taken." The same paragraph lists "repair" as an option, which is the Cursor `parents[3]` finding. Codex's missing marketplace manifest and Cursor's git-URL-only marketplace are distribution facts, not a denial of the failed row.

This is the UniFi closeout sentence kept as the shared closer now that two packages have been assessed. It does not claim "zero failed." The failed row is named, linked to LEARNINGS (verified: mechanism and generalizable rule are the first 2026-08-25 entry), and #19's out-of-scope rule (no downstream patch of copied content) plus the U9 DECISIONS entry ("work stops at the completed matrix… remediations are filed upstream") match it.

**Endorse as written. Do not spend the repair cycle on this sentence.**

### F01 — repair the UniFi Packages-table pin

The new table's first row is `ed72f439` (v0.25.1). That SHA is Fleet Core 0.25.1, a superseded "both packages derived from `ed72f439`" fact from the original pilot. The shipped UniFi package is `818fd684` / **2.0.6** (`PROVENANCE.json`, `plugin.json`, current UniFi matrix). Child #19: "no claim a check or committed evidence contradicts." That is the U0 trust boundary.

Suggested fix: one cell, `818fd684` (v2.0.6). Leave fleet-core `3b5faa6c` (v0.25.2) and mission-control `84eaf042` (v2.12.2) — those match.

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 9.33 | `false` | `shipped-behavior-parity` 6.0 |
| `adversarial` | 10.00 | `true` | none |

## What was verified

At `4648760`:

- Diff vs `febb75b`: exactly the five owned files; `git diff --check` clean
- `check_repo.py` — pass
- `unittest discover -s tests` — 741 OK
- `pytest plugins/mission-control/tests -q` — 266 passed
- Matrix checker on the committed mission-control matrix — pass; fingerprint 64 / `651ac28a…` (untouched)
- LEARNINGS `parents[3]` entry present with Evidence / Mechanism / Generalizable rule
- Architecture brief: 4-line pointer; "Decisions for the next session" not rewritten
- UniFi PROVENANCE `818fd684` / 2.0.6 vs table `ed72f439` / v0.25.1
- 21 files under `plugins/mission-control/tests/` (20 `test_*.py` + `__init__.py`); 7 skill dirs; Claude adapter directory present

## Findings

**F01** (P1, `documentation-clarity` / `shipped-behavior-parity`, confidence 100, `manual` → `review-fixer`)

- File: `README.md:117`
- The new Packages table pins UniFi at `ed72f439` (v0.25.1). Shipped identity is `818fd684` (v2.0.6).
- Suggested fix: replace that cell only.

## Routing

`repairs_requested` — dispatch the one-cell README pin repair, then resubmit the new SHA for cycle 2 (`documentation-clarity` only). Do not edit `plugins/**`. Do not rewrite the endorsed "distribution, not compatibility" sentence as part of this fix unless the unit wants to; it is not `F01`.
