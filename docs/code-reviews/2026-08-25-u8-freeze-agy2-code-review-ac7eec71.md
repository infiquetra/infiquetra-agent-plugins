# Saga Code Review — U8 freeze Phase 3 evidence (`u8-freeze-agy2`)

This review covers the frozen evidence commit on `orch/mcport-9-resume1-u8-freeze-agy2` because child #18 requires one fingerprint-bound ten-client matrix and one readback on the successor frozen candidate after the U8a/U8b harness repair train.

## Outcome

- Typed Saga review result contract (`review_result.v1`): `accepted`
- Next action: `continue`
- Reviewed revision: `ac7eec716d58e58ad8d9b8053de815d92a419914` (`ac7eec7`, `docs(evidence): capture the frozen mission-control Phase 3 evidence (run unit U8)`)
- Parent: `e3780cd77bb15a1fd0e1f2c8582c4608e922751c` (freeze-successor record; one commit)
- Target: 3 files, +1121 / −0
- Review backend: `inline`
- Active findings: none
- Cycle: 1 of 3; no repairs requested

> **Verdict: revision `ac7eec7` is accepted.** The matrix binds to the pinned package fingerprint, records the U8a blocked-in-advance semantic for the four skill-scoped clients, and discloses the Cursor layout failure instead of remediating it. Cycle-16 is verified by digest re-check, not regenerated. All three judgment items are endorsed.

## Scope and built-versus-planned audit

**Scope Check: CLEAN**

- Intent (#18 Phase 3, comments 5404729199 / 5404848068 / 5405558745): verify suites at the successor freeze `e3780cd`; run exactly one credential-stripped ten-client `--execute`; commit the fingerprint-bound matrix with unit-authored reasons; commit the readback with cycle-16 digest re-check; do not edit package or graded files.
- Delivered: matrix (893 lines), readback (203 lines), one LEARNINGS capture of the Cursor finding. Diff versus parent is exactly those three files.

LEARNINGS is outside #18's "files expected to change" list (closeout owns journal curation) but matches the repository's always-on capture rule for a non-obvious finding, and the submission named it as owned surface. That is capture, not curation.

### Plan-completion (U8 evidence commit)

| Item | State | Evidence |
| --- | --- | --- |
| Suites green at frozen package state | DONE | `check_repo` passed; hermetic 741 OK skipped 1; package pytest 266 passed; package git tree `12433538e5b8…` identical to `e3780cd` |
| Upstream suite at pin | DONE | 275 passed at `84eaf042` in a disposable worktree |
| Floor from staged bytes on Python 3.12 | DONE | CPython 3.12.13 throwaway venv with PyYAML; 266 passed |
| `sync_vendor_source.py --check` | DONE | matches `infiquetra-claude-plugins` at `84eaf042` |
| Exactly one `--execute` assessment | DONE | schema-2 record, `assessed_on` 2026-08-25, checker green; private transcript uncommitted per #18 |
| Fingerprint-bound matrix | DONE | `file_count` 64, `tree_sha256` `651ac28a79b4e2e8823c5aa5960659bcd22903e2059afdb9544e13a071de1682`; `--print-fingerprint` equal; 10 clients, 40 stages (33 executed, 7 blocked, 0 not-applicable); statuses 1 / 8 / 1 |
| Unit-authored reasons (doc-review F4) | DONE | every row has a non-empty reason grounded in that row's stage evidence (ITEM 3) |
| Skill-scoped blocked-in-advance | DONE | OpenCode, Gemini CLI, Muse, Hermes invocation `blocked` naming all five package-root entrypoints |
| Readback + cycle-16 digest re-check | DONE | all five graded-file sha256 values match the cycle-16 footer at this revision; binding 3/3; disposition `verified_by_digest_recheck` |
| Package / graded files / UniFi / binding untouched | DONE | empty diff on `plugins/`, `scripts/`, `tests/` |
| Integration merge to main | not this revision | later U8 landing; this process reviews the evidence commit only |

COMPLETION: 10/10 DONE for this evidence commit; merge is out of this SHA.

## Judgments

### (ITEM 1) Endorse the failed Cursor row — do not request a local fix

Cursor: four stages `executed`; invocation five commands with exits `0, 0, 0, 0, 1`. The failing command is `<python> <package>/scripts/sync_template_docs.py --help`. Evidence names `FileNotFoundError` resolving `issue_contract_data.py` via `parents[3] / "plugins/mission-control/..."`.

That is the code. `plugins/mission-control/scripts/sync_template_docs.py:16-31` sets `REPO_ROOT = Path(__file__).resolve().parents[3]` and imports `CONTRACT_DATA_PATH` at module scope, so `--help` never reaches argparse. Independently reproduced from a package-as-root copy: `sync_template_docs.py` exit 1 with `FileNotFoundError` on `.../plugins/mission-control/config/generated/issue_contract_data.py`; the other four entrypoints exit 0. PROVENANCE classifies the script as an upstream byte-copy. #18 out-of-scope: "No per-client remediation… record status, decide separately." U9 owns upstream filings.

Claude Code's invocation stage records the same `0, 0, 0, 0, 1` FileNotFoundError, but overall status is `works-through-an-adapter` because load already failed `plugin details` on session-only plugins and user-scope install still needs a marketplace manifest. That adapter gap is independent of the layout bug. Cursor completed placement, discovery, and load on a supported session `--plugin-dir` path, then failed invocation on a package defect — the rubric's `failed`. LEARNINGS names both clients for the mechanism and does not pretend Claude's overall status is `failed`.

**Endorse. A killing repair here would be an out-of-scope local edit of byte-copied upstream.**

### (ITEM 2) Short wall-clock is consistent with the record — not infidelity

Schema 2 (and the UniFi current matrix) carries per-command `command` + `exit_status` (or `timed_out`), not timestamps or a run id. Judging timestamps that the schema does not store would be inventing a requirement.

What the record does store is internally consistent:

- Ten canonical clients, forty stages, 33 executed / 7 blocked / 0 not-applicable — matches the checker summary and the prose table.
- Every executed stage: `command == commands[0].command`; evidence `Ran N` equals `len(commands)`; listed exit lists equal the per-command `exit_status` values. Automated check: no problems.
- Seven blocked stages, each with a reason, none with `timed_out`: Codex load+invocation, Grok invocation, and the four skill-scoped invocations. Those four are the U8a blocked-in-advance path and start no process.
- Single identity: one `assessed_on`, one package fingerprint, schema 2, no second record. Public-evidence scan: no tokens, no `/Users/...` home paths.
- Invocation is `--help` only. Combined with seven blocked stages, a ~six-minute ten-client run does not imply missing work.

**Endorse the record's internal consistency.**

### (ITEM 3) Every reason is grounded in its row's stage evidence

| Client | Status | Reason vs evidence |
| --- | --- | --- |
| Claude Code | adapter | Load `plugin details` exit 1 "Session-only plugins cannot be inspected"; marketplace not at package root. FNFE is in invocation evidence, not used as the status driver. |
| Codex | adapter | Placement error `missing marketplace.json`; load/invocation blocked on absent adapter. |
| Cursor Agent | failed | Three stages exit 0; invocation `sync_template_docs.py` exit 1 / `parents[3]`. |
| Qwen | adapter | Placement/discovery/load exit 127 under isolated home; invocation exit 2 because scripts were never placed. |
| Grok | adapter | Place/discover/load exit 0; invocation blocked because `<plugin-id>` never resolved. |
| OpenCode | adapter | Seven skill dirs placed; invocation blocked naming all five package-root scripts. |
| Gemini CLI | adapter | Seven skills linked Enabled; invocation blocked naming the same five scripts. |
| Muse | adapter | Seven units installed with content digests; invocation blocked naming the same five scripts. |
| Agy | works directly | Five entrypoints exit 0 from the client-installed copy. |
| Hermes | adapter | Seven local skills in prompt index; invocation blocked naming the same five scripts. |

**Endorse. No reason contradicts its stage evidence.**

## Lens scores

The canonical lens roster accepts a lens only when its mean applicable-dimension score (`derived_overall`) is at least 9.0 and every applicable dimension is at least 7.0.

| Lens | Derived overall | Accepted | Failing dimensions with scores |
|---|---:|---|---|
| `architecture-maintainability` | 10.00 | `true` | none |
| `correctness` | 10.00 | `true` | none |
| `security` | 10.00 | `true` | none |
| `testing` | 10.00 | `true` | none |
| `documentation-clarity` | 10.00 | `true` | none |
| `adversarial` | 10.00 | `true` | none |

## What was verified

Disposable worktree at `ac7eec7`:

- `python3 scripts/check_compatibility_matrix.py` — passed; mission-control current row 10 / 33 / 7 / 1+8+1
- `python3 scripts/check_compatibility_matrix.py --print-fingerprint mission-control` — 64 files, `651ac28a…1682`
- `git rev-parse HEAD:plugins/mission-control` — `12433538e5b8aa9d88b573e695ef9bc6786549ab` (equal to `e3780cd`)
- Cycle-16 footer sha256 equals committed blobs for all five GRADED paths
- `python3 scripts/check_repo.py` — passed
- `python3 scripts/sync_vendor_source.py --check --package mission-control --source <upstream> --commit 84eaf042…` — passed
- `python3 -m unittest discover -s tests` — 741 ran, 0 failed, 1 skipped
- `python3 -m pytest plugins/mission-control/tests -q` — 266 passed
- Floor: CPython 3.12.13 venv with pytest/pyyaml/requests/urllib3 — 266 passed
- Upstream at `84eaf042` — 275 passed
- Binding 3/3; `git diff --check` clean; `plugins/unifi` empty in the diff
- Package-as-root reproduction of the Cursor invocation failure (one script exit 1 FileNotFoundError; four exit 0)

## Coverage

- Suppressed findings: 0.
- Residual risks, not findings:
  - JSON `method.isolation` is the UniFi boilerplate ("empty home… no assessment read or wrote the operator's real client configuration"). The markdown how-section documents the established Cursor real-HOME exception. Same split as the current UniFi matrix. Prose is the honest record.
  - Claude Code's overall `reason` does not mention the FileNotFoundError; invocation evidence and client-detail prose do. Using that error as the status driver would have mis-labelled an adapter client as `failed`.
  - The private `--execute` transcript is uncommitted per #18. `.pre-auto-trust` binaries exist on disk; their paths are not in the public record (public-evidence rules).
- Independent gates actually run at `ac7eec7`: matrix checker, fingerprint, `check_repo`, hermetic discover, package pytest, floor pytest, upstream pytest at pin, `sync --check`, cycle-16 digest re-check, UniFi no-churn, `git diff --check`. `evaluate_review_readiness` `can_proceed` is true.

## Findings

None.

## Routing

`accepted` — continue. No fix requests. ITEM 1–3 endorsed. The Cursor layout defect is named evidence for U9 upstream filing, not a repair on this unit.
