# Work session — agent-launcher portable port (issue #22)

Date: 2026-08-27. Branch: `port/agent-launcher`. Backend: inline. Plan:
`docs/plans/2026-08-27-agent-launcher-port-plan.md` (doc-review PROCEED at
`8daee79`, three cycles, zero findings on the final revision). Runbook:
`docs/runbooks/portable-plugin-port.md` v1.1.0.

## What was built

- **U1** — `ports/agent-launcher.json` (schema 3: byte copies for the contract
  script and changelog; README and SKILL superseded by target-owned docs; the
  upstream suite dropped with a recorded reason; assessment declares no
  credential prefixes via `declared_none`, names `launch`/`close` as mutating).
  Target-owned portable manifest, README, and portable SKILL.md; synchronized
  from upstream pin `8269f84b01065ac96d162431ce00ebd42003dd5f` (plugin 1.0.0).
  `sync --check` and `check_repo.py` green; entrypoint answers `--help` and
  `roster` credential-free. Commit `c642a01`.
- **U2** — target-owned suite inside the package: the portable half of the
  upstream contract tests re-proved from `parents[1]` (23 tests) plus
  class-based documentation guards for the superseded skill and README (21
  tests). README `tests/` row restored; PROVENANCE refreshed by re-sync.
  Commit `baa2dc8`.
- **U3** — repo-root guards: packaging smoke (relocated manifest agreement,
  portable manifest shape, no convention directories, marketplace absence
  lock), the assess-clients shape test (deliverable-entrypoint geometry, the
  UniFi pattern at `tests/test_assess_clients.py:1449`; the mission-control
  test at 1421 is the negative control), and the rule audit: custody
  classification, the doc-guard mutation corpus (eight mutation classes, zero
  survivors) with the proof bound to committed-blob digests in
  `docs/evidence/2026-08-27-agent-launcher-mutation-proof-portable-docs.txt`.
  Commit `29a2975` — the package tree freeze point (11 files,
  `65beaf76...`).
- **U4** — Phase-3 evidence. Floor verified from staged bytes on CPython
  3.12.13. Ten-client assessment executed from a disposable venv and scratch
  workspace: 37 of 40 stages executed; 7 clients work directly, 3 through an
  adapter, 0 failed, 0 unsupported. One earlier attempt missing the qwen
  wrapper override recorded four failed Qwen stages and was re-run rather than
  committed (no evidence was renumbered — nothing was committed yet). Matrix
  and post-activation readback committed current and fingerprint-bound.
  Commit `1c348a3`.
- **U5** — metadata closeout: README Status narrative + Key facts + Packages
  table + record of work; `llms.txt` Packages bullet; `docs/README.md` plan
  and evidence index entries; `tests/test_python_floor.py` declaration site
  for the new README; journal DECISIONS entry.

## Key decisions (mirror the plan KTDs)

Byte-copy custody for the contract (KTD1); supersession of the Claude-runtime
docs (KTD2); dropped upstream suite with a target-owned replacement (KTD3);
pin at upstream origin/main HEAD at sync time (KTD4); assessment safety
declarations (KTD5); derived version 1.0.0 (KTD6); no marketplace entry,
locked by test (KTD7); adapter limitations documented in three places (KTD8);
one branch / one squash PR (KTD9); content-bound evidence with
supersede-and-rerun, never renumber (KTD10).

## Deviations and judgment items

- The qwen launcher wrapper on this machine resolves its real binary through
  the client home (`QWEN_HERDR_REAL_BIN`), the same class as the Grok/Agy
  auto-trust wrappers the harness already documents. The harness's Qwen plan
  declares no override variable, so the run exported the wrapper's own
  documented override instead of passing `--real-binary`. Recorded in the
  matrix method prose; candidate for an upstream harness filing (deferred —
  see next steps).
- The issue body's `uv run pytest` verification block was stale for this
  repository (no pyproject.toml); the corrected check set was recorded on the
  issue and the issue body updated to it before execution.
- The front-loaded draft-PR ceremony offered by `/work` was declined in favor
  of the operator-sequenced PR after code review (operator instruction step 7).

## Checks run (final state)

`python3 scripts/check_repo.py` — passed.
`python3 scripts/check_compatibility_matrix.py` — passed (all matrices).
`python3 -m unittest discover -s tests` — 771 tests OK.
`python3 -m pytest plugins/agent-launcher/tests -q` — 44 passed.
`git diff --check` — clean.

## Next step

Submit the frozen implementation revision for code review through the Code
Review controller tab (`wCC:p6`, installed Saga `/code-review`), then PR,
CI, and merge per the operator sequence.

## Code-review cycle 1 → repair cycle (same day)

Cycle 1 at `60e30f5` returned `repairs_requested`: independent gates all
passed; six lenses failed the numeric floors on twelve findings. Eight were
actionable here (fix groups fix-2a9e5c55a826, fix-ea724133f0b8,
fix-2a0799d391f8, fix-d3fdc17756aa, fix-270dd854e004) and were validated
against the code before repair:

- F-1/F-2 (P1): the portable skill's launch example now carries `--prompt`,
  and the keep-list names the receipt keys launch actually prints
  (`tab_id`, `pane`, `agent_name`, `workspace`, `owned`, `reused`), guarded
  against the stale upstream names.
- F-3 (P2): the package README states roster's missing-wrapper stop.
- F-5/F-6 (P2): launch tests stub `list_tab_ids` (no live herdr), the
  cwd-mismatch close test proves ownership through the real herdr tab-close
  seam, and the failed-launch persist test asserts `owned`.
- F-7 (P2): the README mutation corpus gains the wrapper-and-Herdr class.
- F-8 (P2): the catalog's Grok adapter reason matches the matrix.
- F-12 (P3): the docs index states the doc-review cycles accurately.

F-4/F-9/F-10/F-11 sit in the byte-copied `launcher.py`; the reviewer routed
them advisory → human (upstream filing). They are recorded as residuals, not
patched downstream (custody rule), and become upstream filings in the
closeout follow-up.

The repairs moved the graded bytes and the package tree, so the runbook
evidence loop ran as the plan's KTD10 prescribes: the mutation proof was
re-run (now eleven classes, zero survivors) and republished with new footer
digests; the first matrix record was superseded to
`2026-08-27-agent-launcher-compatibility-matrix-pre-cycle2-repair.md` with
successor and reason; the assessment was re-executed against the repaired
tree (identical client behavior; fingerprint moved from `65beaf76…` to
`c9689c2f…`); the current matrix and the readback were re-bound to the
repaired tree at frozen candidate `6b7fc57`. Nothing was renumbered.

Checks after the repair batch: `check_repo.py` passed; matrix validator
passed (both records); 771 unittest OK; 46 package tests passed;
`git diff --check` clean.

## Next step (cycle 2)

Resubmit the repaired revision to the same Code Review controller; cycle 2
reruns the failing lenses only.
