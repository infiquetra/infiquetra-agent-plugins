---
date: 2026-08-25
kind: code-review
target: git diff dd10d9b2b6b33f52f85971bf720df43065349a07..9c194fdfb1dc06bc28e634d078bc19b7c0e9f143
reviewed_revision: 9c194fdfb1dc06bc28e634d078bc19b7c0e9f143
branch: orch/orch-2026-08-25-voice-codereview-grok
frozen_branch: orch/orch-2026-08-25-voice
outcome: accepted
cycles: 1
---

# Saga Code Review — Voice plugin frozen build

This is the Infiquetra agent-plugins repository (`infiquetra-agent-plugins`), Voice plugin run `orch-2026-08-25-voice`. The reviewed object is the frozen merge of units U1–U7 at commit `9c194fdfb1dc06bc28e634d078bc19b7c0e9f143` (`9c194fd`, `Merge branch 'orch/orch-2026-08-25-voice-work-u7' into HEAD`) versus base `dd10d9b2b6b33f52f85971bf720df43065349a07` (`dd10d9b`, `origin/main`). The diff is 36 files, 9296 insertions, all additive. This session did not rebase, amend, push, open a pull request, merge, or write GitHub project-board state.

> **Typed outcome: `accepted`.** Next action: `continue`. Cycle 1 of 3. Every selected lens derived-overall is at least 9.0 and no applicable dimension is below 7. Independent gates passed. Four small NEW repairs are available as structured fix requests; they do not fail numeric acceptance. Known acceptance findings F1–F9 were validated or rejected below and were not re-filed as new discoveries.

Typed contract: [`2026-08-25-voice-plugin-code-review-9c194fd-result.json`](2026-08-25-voice-plugin-code-review-9c194fd-result.json) (`review_result.v1`). `outcome` is the only decision field.

## Unattended choices taken

This session was unattended. Where saga would have asked, the following were taken and why:

| Gate | Choice | Why |
|---|---|---|
| Review mode / persistence | Write under `docs/reviews/` and commit on this review branch | Caller instruction. Skill default is evidence-ledger or programmatic zero-writes; the coordinator said a review that is not committed does not exist. |
| Conditional lenses | `caller_selection` source `orchestrate` — the predeclared set | Plan table "Review lenses per unit (predeclared)" plus the run brief. `question_asked: false`. |
| Backend | `inline` | This session already owns fan-out, scoring, and the typed outcome. |
| Resume vs mint | Scan, then skip the saga write; never mint | `saga.py scan` returned zero candidates. |
| Engine / external-reviewer seat | None | No Orchestrate external-reviewer handle was supplied. Code Review does not invent a seat. |
| Destination | `docs/reviews/` | Caller path. Not `docs/evidence/<saga>/artifacts/` because there is no work-thread saga. |
| Scope | Full launch set of 11 lenses | Always-on four plus the seven predeclared conditionals. `deployment-infrastructure` and `performance` were not launched (plan: not applicable run-wide). |

## Launch set

`resolve_lens_selection` + `launch_approved_lenses` at reviewed commit `9c194fd`, cycle 1:

Always-on: `architecture-maintainability`, `correctness`, `security`, `testing`.

Conditionals (orchestrate-approved): `api-contract`, `reliability`, `privacy`, `documentation-clarity`, `adversarial`, `agent-usability`, `accessibility-human-usability`.

Not launched: `deployment-infrastructure` (CI untouched by hard rule; nothing deploys), `performance` (no latency or throughput requirement).

Lens agents ran as `saga:readonly-verifier` in disposable worktrees, three at a time. Scoring, consensus, and `review_result.v1` stayed in this controller.

## Independent gates

| Gate | Result | Evidence |
|---|---|---|
| `python3 scripts/check_repo.py` | pass | `Repository validation passed.` |
| `python3 -m unittest discover -s tests` | pass | `Ran 741 tests in 45.187s` / `OK` |
| `git diff --check dd10d9b..9c194fd` | pass | clean |
| `python3 -m pytest plugins/voice/tests -q` | pass | `243 passed, 190 subtests passed in 0.96s` (plan verification command; not a roster scoring input) |
| Built-versus-planned | pass (informational PARTIALs below) | All owned paths exist; R22/R25/R28/R33 are PARTIAL for recorded residuals, not missing units |
| Hard boundaries | pass | All ten holds, cited below |
| `git diff --shortstat dd10d9b..9c194fd` | 36 files, 9296 insertions | matches the freeze |

`evaluate_review_readiness`: `review_accepted=true`, `independent_gates_passed=true`, `can_proceed=true`.

## Lens scores

Derived overall is the mean of applicable dimensions. Never averaged across lenses. Floor on each applicable dimension is 7. Acceptance threshold on derived overall is 9.

| Lens | Cycle | Reviewed revision | Derived overall | Accepted | Weakest applicable dimension |
|---|---:|---|---:|---|---|
| `architecture-maintainability` | 1 | `9c194fd` | 9.29 | true | significant-decision-documentation 8 |
| `correctness` | 1 | `9c194fd` | 9.00 | true | side-effects-errors-resource-lifecycle 8 |
| `security` | 1 | `9c194fd` | 9.25 | true | confidentiality-logs-errors-egress 8 |
| `testing` | 1 | `9c194fd` | 9.00 | true | realistic-seams-mocks-integration-evidence 8 |
| `api-contract` | 1 | `9c194fd` | 9.00 | true | interface-contract-compatibility 8 |
| `reliability` | 1 | `9c194fd` | 9.00 | true | graceful-degradation-cancellation-cleanup 8 |
| `privacy` | 1 | `9c194fd` | 9.00 | true | retention-deletion-all-copies 8 |
| `documentation-clarity` | 1 | `9c194fd` | 9.00 | true | shipped-behavior-parity 8 |
| `adversarial` | 1 | `9c194fd` | 9.57 | true | recovery 8 |
| `agent-usability` | 1 | `9c194fd` | 9.00 | true | context-constraints-acceptance-examples 8 |
| `accessibility-human-usability` | 1 | `9c194fd` | 9.00 | true | labels-forms-loading-empty-error-states 8 |

Non-applicable dimensions (each with a named absent precondition) live on `security` (no authn/tenant surface), `api-contract` (no versioning, pagination, or generated SDK), `reliability` (no job queue), `privacy` (no regulatory residency requirement), and `accessibility-human-usability` (no graphical UI; no locale-sensitive pane parsing).

## Built versus planned

**Scope Check: CLEAN**

- **Intent:** implement the portable `voice` plugin as units U1–U7 (issues #28–#34) from `docs/plans/2026-08-25-voice-plugin-implementation-plan.md`, owning R1–R33 exactly once.
- **Delivered:** the 36-file additive diff at `9c194fd`: package root, Claude Stop hook, speak/listen/deliver/pane/preflight/CLI/skill, tests, acceptance evidence, and journal closeout. The plan file and its doc-review are on the same branch from the planning units; they are in-run, not creep.
- **Out of scope not taken:** no CI edit, no MCP server, no `herdr pane run`, no `auth.json` / `XAI_API_KEY`, no third-party HTTP client.

**COMPLETION: 29/33 DONE, 4 PARTIAL, 0 NOT-DONE, 0 CHANGED, 2 UNVERIFIABLE**

PARTIAL (diff-verifiable code exists; live or runtime consult is incomplete):

| Item | State | Evidence |
|---|---|---|
| R22 preflight names prerequisites | PARTIAL | Probes exist (`plugins/voice/scripts/preflight.py`) but fail live Voice Forge `/health` and Hermes `/api/profiles` (acceptance F1, F2) |
| R25 ephemeral audio | PARTIAL | Success/failure deletion holds; pane quit leaves a live recorder (new F01); F6 is a narrow post-unlink flush residual |
| R28 retention stated | PARTIAL | `settings.retention()` exists and is tested; no runtime caller (acceptance F7) |
| R33 live acceptance | PARTIAL | AE1–AE8 recorded; AE5 unattended-gap F4; live preflight red F1/F2/F8 |

UNVERIFIABLE (external-state / human-shaped):

- AE5 blocked-state live branch (F4) — no agent was `blocked` during unattended acceptance; hermetic `test_deliver.py` covers the code path.
- Acoustic voice into `:0` (F5) — D3 pins AVFoundation `:0`; on this host that device is the iPhone Continuity microphone.

All other R1–R21, R23, R24, R26, R27, R29–R32 classify DONE against the diff (Stop-hook detach, sticky bind, send-text-only delivery, stdlib `python>=3.12`, no MCP, R30 package README provenance paragraph intact).

## Hard boundaries (verified, not assumed)

| Boundary | Result | Evidence |
|---|---|---|
| Never read `auth.json` | hold | no matches under `plugins/voice/`; `plugins/voice/tests/test_transcribe.py:347` |
| Never copy the xAI OAuth bearer | hold | `plugins/voice/scripts/transcribe.py:29-33` — loopback session token only |
| Never import Hermes internals | hold | `plugins/voice/scripts/transcribe.py:36-50`; tests forbid `import hermes` / `from hermes` |
| Never require `XAI_API_KEY` | hold | `plugins/voice/scripts/settings.py:81-90` closed `SETTING_NAMES` |
| Never persist or log the Hermes session token | hold | `plugins/voice/scripts/transcribe.py:8-9,103-124`; header only |
| Never expose the token in argv or evidence | hold | `plugins/voice/scripts/transcribe.py:136-149`; preflight asserts token absent from URLs |
| Never disable Hermes authentication | hold | `plugins/voice/scripts/preflight.py:20-22,321-324` — `auth_required: false` is not treated as anonymous |
| Provider lifecycle / OAuth refresh / credentials stay outside Voice | hold | `plugins/voice/scripts/providers.py:3-20`; 401 path refreshes only the loopback session token once |
| Delivery is `herdr pane send-text` only | hold | `plugins/voice/scripts/deliver.py:273-279`; `plugins/voice/tests/test_deliver.py:138-146` |
| `herdr pane run` must never appear | hold | zero matches under `plugins/voice/` |
| No MCP server | hold | `plugins/voice/tests/test_skill_entrypoint.py:111-115` (needle split so the package stays grep-clean) |

`herdr pane send-text --help` on this host is `Usage: herdr pane send-text <PANE_ID> <TEXT>`. Dashes in a transcript are remaining argv, not flags after the subcommand path (adversarial lens).

## Known acceptance findings F1–F9

Read first from `docs/evidence/voice/acceptance.md`. Disposition:

| Id | Disposition | Notes |
|---|---|---|
| F1 Voice Forge health probe contract drift | **validated** | `probe_forge_health` at `preflight.py:188-203` requires `status` plus `backend`. Live v0.3.0 `/health` is `ok: true` plus `backends_loaded`. Hermetic fixture `HEALTHY_FORGE_HEALTH` locks the invented shape (`test_preflight.py:41`). Routed as advisory F05. |
| F2 Hermes profile probe expects `stt` | **validated** | `probe_hermes_profile` at `preflight.py:450-458` requires `stt.provider == xai`. Live v0.20.4 profile objects have no `stt` surface. SKILL.md:57-61 still tells an agent that preflight proves that fact. Routed as advisory F06. |
| F3 silence maps to provider-mismatch | **validated** | `transcribe.py:225-232` refuses any `provider` other than `"xai"`, including `None`. Empty-transcript tests only use `provider="xai"` (`test_transcribe.py:44,262`). Routed as advisory F07. |
| F4 AE5 blocked branch not live | **rejected as a code defect** | `deliver.py:129-136` and `test_deliver.py` cover blocked → nothing sent, hold file, audible refusal. Unattended environment had no `blocked` agent. Residual for an attended re-run, not a missing implementation. |
| F5 capture device `:0` is Continuity mic | **rejected as a code defect** | D3 pins `-f avfoundation -i :0`. Environment fact. Not a product bug. |
| F6 millisecond flush race orphan wav | **validated; not inflated** | Distinct from new F01 (live recorder after pane quit). Narrow post-unlink header flush. Routed as advisory F09 (P3). |
| F7 `VOICE_RETENTION` unread at runtime | **validated** | `settings.retention()` at `settings.py:161-176`; production callers: none. Routed as advisory F08. |
| F8 D4 operator keybinding not added | **rejected as a code defect** | Preflight reports the absence by name (R14 working). Operator config, not a missing probe. |
| F9 `docs/README.md` derived-artifact claim | **validated; same defect on root README** | `docs/README.md:72-73` and `README.md:15-39` still describe every `plugins/` package as a derived pin. Package README R30 paragraph is intact. U7 did not own those catalog paths. Routed as advisory F10. Not a new finding. |

## Findings

Operator-validator (this session) confirmed every NEW finding by reading the cited lines. Confidence below 75 was not admitted. No P0.

### P2

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---:|---|
| F01 | `plugins/voice/scripts/pane.py:265` | Pane quit leaves the detached ffmpeg capture running (and the recording indicator gone). Distinct from F6. | reliability, privacy, security, testing, accessibility-human-usability | 100 | gated_auto -> review-fixer |
| F02 | `plugins/voice/scripts/deliver.py:159` | `use_refused` unlinks the hold before `deliver`; a non-blocked send failure loses the only copy. | adversarial, reliability | 100 | gated_auto -> review-fixer |
| F05 | `plugins/voice/scripts/preflight.py:188` | Known F1 — Forge `/health` probe vs live v0.3.0. | api-contract, testing | 100 | advisory -> downstream-resolver |
| F06 | `plugins/voice/scripts/preflight.py:450` | Known F2 — profile `stt.provider` vs live `/api/profiles`; SKILL.md first-use gate repeats the claim. | api-contract, agent-usability, documentation-clarity | 100 | advisory -> downstream-resolver |
| F07 | `plugins/voice/scripts/transcribe.py:226` | Known F3 — silence `{transcript:"", provider:null}` refused as substitution. | correctness | 100 | advisory -> downstream-resolver |
| F08 | `plugins/voice/scripts/settings.py:161` | Known F7 — `VOICE_RETENTION` reader has no runtime caller. | architecture-maintainability | 100 | advisory -> downstream-resolver |

### P3

| # | File | Issue | Reviewer | Confidence | Route |
|---|---|---|---|---:|---|
| F03 | `plugins/voice/com.infiquetra.claude/hooks/stop_hook.py:76` | Stop hook leaves `speak-<uuid>.json` if `spawn_detached` fails. | reliability | 100 | gated_auto -> review-fixer |
| F04 | `plugins/voice/README.md:26` | Package README inventory still lists only the U1 trio. | documentation-clarity, architecture-maintainability | 100 | safe_auto -> review-fixer |
| F09 | `plugins/voice/scripts/transcribe.py:169` | Known F6 — header-only orphan wav after unlink. | correctness | 100 | advisory -> downstream-resolver |
| F10 | `docs/README.md:72` | Known F9 — catalog still says every `plugins/` package is a derived pin (root README same class). | documentation-clarity | 100 | advisory -> downstream-resolver |

### F01 — Pane quit leaves the detached capture running

`pane.run` at `plugins/voice/scripts/pane.py:265-274` breaks on `q` or EOF, swallows KeyboardInterrupt, prints `pane stopped`, and returns 0. It never calls `record.stop`, `_abandon`, or `speak.stop_playback`. `record.start` spawns ffmpeg via `process.spawn_detached` (`start_new_session=True`, `-t 600`). Acceptance AE4 already watched this: pane stdin closed while recording, ffmpeg kept capturing.

A later pane starts with `VoicePane.recording = False` and paints `recording: idle`. The next `t` sees the leftover live pid and treats that press as an explicit stop, so post-quit room audio can be transcribed and delivered.

This is not F6. F6 is a millisecond header flush after unlink. F01 is a live microphone after the UI is gone.

Smallest compatible fix: on pane exit, abandon any active recorder without transcribing, and stop playback. Restore liveness from `recording.json` on pane start. Add a run-loop test that `t` then `q` does not leave a live recorder. Leave CLI `toggle` start-and-exit unchanged.

### F02 — `use_refused` drops the hold on send failure

`deliver.use_refused` at `plugins/voice/scripts/deliver.py:152-160` reads the hold, unlinks it, then calls `deliver`. Only the blocked branch of `deliver` re-writes the hold. A timeout, `CalledProcessError`, or unbound agent after the unlink consumes the only remaining copy of a refused transcript.

Tests cover success-clear and still-blocked-rewrite (`test_deliver.py:342-370`), not a send failure after unlink.

Smallest compatible fix: unlink only after a successful send.

## Fix requests (actionable only)

`consolidate_fix_requests` produced four requests. Known F1–F9 are advisory and are not in this list.

| fix_id | findings | class | paths | summary |
|---|---|---|---|---|
| `fix-c833265a7e2b` | F01 | gated_auto | `pane.py`, `record.py`, `test_pane.py` | Pane quit leaves the detached capture running |
| `fix-46388b8b1c23` | F02 | gated_auto | `deliver.py`, `test_deliver.py` | `use_refused` drops the hold on send failure |
| `fix-7dc84f790a3a` | F03 | gated_auto | `stop_hook.py`, `test_stop_hook.py` | Stop hook leaves the speak payload if spawn fails |
| `fix-3dc51f50a987` | F04 | safe_auto | `plugins/voice/README.md` | Package README inventory is frozen at U1 |

`/code-review` does not apply these. They are offered to Work. Numeric acceptance does not require them before the caller's next independent gate.

## Coverage

- **Suppressed:** findings below confidence 75; none admitted then dropped.
- **Validator:** unattended session acted as the operator-validator. F01–F04 were re-read at the cited lines in this worktree. Conservative bias: F4/F5/F8 were dropped as code defects rather than externalized.
- **Residual risks:** check-then-send blocked race remains the stated U5 residual; F6 stray-capture sweep is absent; F7 retention reader is decorative; live preflight stays red until F1/F2 are aligned; F8 is an operator keybinding.
- **Testing gaps:** no run-loop case for `q` while a recording is active; empty-transcript tests never use `provider: null`; hermetic Forge/Hermes fixtures lock the invented probe shapes (the test-side of F1/F2). KTD12 holds: `plugins/voice/tests/` has no `__init__.py`, unique basenames, no `import pytest`.
- **External advisory seat:** none. Not invented.

## Architecture notes (not findings)

Layering holds. `settings` / `providers` / `process` sit at the base. `speak` / `record` / `transcribe` sit above them. `deliver` depends on `speak` and `binding`. `pane` sequences listen with a lazy `import deliver` (KTD16). The Stop hook never imports `speak`; it hands a unique payload file on argv. Stdlib only; `urllib.request`; argv lists; stdin closed; deadlines required on `process.run`. Portable core has no `*hook*` file. Nested Claude `plugin.json` matches the UniFi and Mission Control client-extension shape (no catalog `$schema`).

Proportionality was applied: no enterprise discovery, failover, authentication, retries-as-orchestration, service management, multi-tenancy, HA, or regulatory machinery was required. Credential, shell, filesystem, Git, privacy/retention, destructive-action, and production boundaries were scored at full strength.

## Routing

- **`accepted`** — continue to the caller's next independent gate.
- Saga: **no work-thread saga found** (`saga.py scan` count 0). Skipping the saga write; never minting one from code-review.
- Board: **not written**. The coordinator is the sole board writer.
- Git: this artifact is committed on `orch/orch-2026-08-25-voice-codereview-grok`. Frozen build `9c194fd` is not amended. No push, no pull request, no merge.

Review complete.
