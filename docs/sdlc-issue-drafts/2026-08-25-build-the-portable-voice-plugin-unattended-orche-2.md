---
title: Build the portable voice plugin — unattended orchestration contract
repo: infiquetra-agent-plugins
type: capability
team: asgard
project: operations
status: Shaping
labels: capability, needs-plan
risk: medium
handoff_maturity: requirements-ready
---

# Build the portable voice plugin — unattended orchestration contract

### Objective

Deliver the portable Agent Plugins package `voice` to its version-one acceptance
loop, as an unattended Orchestrate run of seven executable child issues.

**The product requirement, which no unit may narrow.** A single explicitly bound,
Herdr-managed Claude session speaks its completed response — taken from the `Stop`
hook's `last_assistant_message`, after Markdown cleanup, with the contents of fenced
code blocks omitted. The operator toggles recording in the Voice pane, speaks, and
toggles again. A hosted speech-to-text provider transcribes the audio, and Voice
returns the text into that same bound session's input box, unsubmitted and editable.

This is a two-way conversational loop. It is explicitly **not** an alert-only or
notification product. Blocked-session alerting is deferred supporting functionality
and must not be substituted for the loop. A run that ships notifications without the
speak/listen/deliver cycle has not delivered this objective.

Authoritative sources, all merged on `main` at `794fe46`:

- `docs/brainstorms/2026-08-25-voice-plugin-requirements.md` — the 33 requirements
  (R1–R33), 8 acceptance examples, and scope boundaries. Governs scope.
- `docs/ideation/2026-08-25-voice-plugin-ideation.md` — provenance and the rejections
  retained with reasons. Evidence only; not a scope authority.
- `docs/reviews/2026-08-25-voice-plugin-requirements-doc-review.md` — the accepted
  Saga Document Review at frozen revision `a8fa3b9`.
- `docs/reviews/2026-08-25-voice-plugin-requirements-post-integration-freshness-review.md`
  — the post-integration freshness review at frozen revision `c90de14`.

### Intent

Run seven child issues through a four-lane dependency graph so that every one of the
33 requirements is implemented, reviewed, merged, and evidenced exactly once.

Each requirement is owned by exactly one unit. The mapping below is complete and
non-overlapping: all 33 requirements appear once, and no requirement appears twice.

| Unit | Child | Purpose | Lane | Depends on | Requirements owned | Owned surface |
| --- | --- | --- | --- | --- | --- | --- |
| U1 | #28 | Package foundation, provider declaration contract, retention posture, subprocess discipline. **Implements R30.** | G1 | — | R20, R21, R23, R24, R28, R29, R30, R31, R32 | `plugins/voice/{plugin.json,README.md}`, `plugins/voice/scripts/{providers,settings,process}.py` |
| U2 | #29 | Claude client extension: `Stop` hook, binding store, single-speaker guard | G2 | U1 | R1, R2, R3 | `plugins/voice/com.infiquetra.claude/**`, `plugins/voice/scripts/binding.py` |
| U3 | #30 | Speak path: Markdown cleanup, code-block omission, Voice Forge synthesis | G2 | U1 | R5, R6, R7 | `plugins/voice/scripts/{text_cleanup,speak}.py` |
| U4 | #31 | Listen path: toggle recording, Hermes relay transcription, ephemeral retention | G2 | U1 | R10, R12, R25, R26, R27 | `plugins/voice/scripts/{record,transcribe}.py` |
| U5 | #32 | Deliver path: unsubmitted `herdr pane send-text`, bound-only target, **audible** blocked refusal, transient retention | G3 | U1, U2, **U3**, U4 | R16, R17, R18, R19 | `plugins/voice/scripts/deliver.py` |
| U6 | #33 | Agent Skill entrypoint, Voice pane controls, provider and keybinding preflight | G3 | U1, U2, U3, U4 | R4, R8, R9, R11, R13, R14, R15, R22 | `plugins/voice/skills/voice/SKILL.md`, `plugins/voice/scripts/{voice_cli,pane,preflight}.py` |
| U7 | #34 | Acceptance evidence, README **verification**, journal closeout | G4 | U1–U6 | R33 | `docs/evidence/voice/**`, `plugins/voice/README.md` (finalize only), `docs/engineering-journal/**` |

All seven child issues exist and are linked as native sub-issues of this issue.

**Dependency graph.** Lanes are real data and ownership dependencies, not ordering
decoration. Maximum true concurrency is three, in lane G2; the worker pool cap of
four is therefore never the binding constraint, and no concurrency is manufactured
to fill it.

```text
        G1            G2                    G3                G4
       ┌────┐      ┌────┐
       │ U1 │─────▶│ U2 │───────────┬─────▶┌────┐
       └────┘      └────┘           │      │ U5 │────┐
          │        ┌────┐           │      └────┘    │
          ├───────▶│ U3 │───────┬───┤                ├───▶┌────┐
          │        └────┘       │   │                │    │ U7 │
          │        ┌────┐       │   │      ┌────┐    │    └────┘
          └───────▶│ U4 │───────┴───┴─────▶│ U6 │────┘
                   └────┘                  └────┘

U1 → everything (portable package root, provider contract, subprocess helper)
U5 ← U2 (sticky binding) + U3 (audible refusal, R18) + U4 (transcript)
U6 ← U2 (identity display) + U3 (stop playback) + U4 (indicator, barge-in)
U7 ← all six (end-to-end acceptance)
```

**Shared-file collision rules.** Every path below has exactly one writing owner for
the whole run. A unit that believes it must edit another unit's surface stops and
raises the conflict instead of editing.

| Surface | Sole writer | Rule for everyone else |
| --- | --- | --- |
| `plugins/voice/` package root, `plugin.json` | U1 | Add new modules only; never edit U1's files |
| `plugins/voice/com.infiquetra.claude/**` (Claude client extension) | U2 | Portable core never writes here; `plugins/voice/adapters/**` must not exist |
| `plugins/voice/skills/voice/**`, `scripts/voice_cli.py` | U6 | The portable Agent Skill entrypoint and its CLI |
| `plugins/voice/scripts/{providers,settings,process}.py` | U1 | Import and consume; never modify |
| `plugins/voice/scripts/binding.py` | U2 | Read the binding through U2's interface |
| `plugins/voice/README.md` | **U1 implements R30**; U7 verifies and finalizes | Serialized. U7 verifies the R30 truth; it never re-owns R30 |
| `plugins/voice/tests/**` | Per-unit test files, named for the module under test | Never edit another unit's test file |
| `docs/engineering-journal/DECISIONS.md`, `LEARNINGS.md` | **U7 only** | Hard rule: these files are newest-first inserts, so two writers guarantee a conflict and displace every line anchor below |
| `.github/workflows/ci.yml` | **Nobody** | CI already globs `plugins/*/tests`; a unit that thinks it needs a CI edit has hit a stop condition |
| Repository root `README.md`, `docs/README.md` | U7, only if a claim became untrue | Not a routine surface |

### Out-of-scope / non-goals

Governed by the requirements document's own Scope Boundaries section. Not in this run:

- Generalisation to non-Claude Herdr-managed agents. The loop is proven for Claude first.
- Blocked-session alerts across the fleet. Deferred supporting functionality; it must
  never be delivered in place of the conversational loop.
- Apple `SpeechAnalyzer` as a provider. Deferred, not rejected: it needs a compiled,
  signed, permission-bearing binary and must not reopen version one's toolchain.
- Local `whisper.cpp` or an operator-managed local-network speech service. Legitimate
  declared providers later; not prerequisites now.
- True press-and-hold recording. Requires unverified key-release forwarding.
- Response-length management of any kind, including truncation and summarisation.
- Provider installation, credentials, billing, and service lifecycle.
- Multi-session speech arbitration, queues, priorities, automatic opt-in.
- Any resident daemon or background listener.
- Continuous listening and wake-word activation.
- A Model Context Protocol listening tool.
- Terminal-output scraping and terminal-input injection.
- Modifying Herdr or vendoring any part of it.

**Proportionality guardrails.** `voice` is a private, single-user developer tool in a
personal plugin catalog. Prefer the smallest compatible implementation. Do not
introduce multi-tenant, internet-scale, high-availability, regulatory, or
over-defensive machinery without an in-scope requirement or a demonstrated failure
mode. Standard-library Python at the repository floor of `>=3.12`, tested with
`unittest`, per R31.

Do not relax real boundaries in the name of that smallness: credential handling,
shell execution, filesystem writes, Git operations, privacy and retention,
destructive actions, and production safety all keep their full strength. R32's
subprocess discipline — standard input explicitly closed, deadline attached — is a
safety requirement, not ceremony.

### Files expected to change

- `plugins/voice/plugin.json`
- `plugins/voice/README.md`
- `plugins/voice/scripts/providers.py`
- `plugins/voice/scripts/settings.py`
- `plugins/voice/scripts/process.py`
- `plugins/voice/scripts/binding.py`
- `plugins/voice/com.infiquetra.claude/plugin.json`
- `plugins/voice/com.infiquetra.claude/hooks/hooks.json`
- `plugins/voice/com.infiquetra.claude/hooks/stop_hook.py`
- `plugins/voice/scripts/text_cleanup.py`
- `plugins/voice/scripts/speak.py`
- `plugins/voice/scripts/record.py`
- `plugins/voice/scripts/transcribe.py`
- `plugins/voice/scripts/deliver.py`
- `plugins/voice/skills/voice/SKILL.md`
- `plugins/voice/scripts/voice_cli.py`
- `plugins/voice/scripts/pane.py`
- `plugins/voice/scripts/preflight.py`
- `plugins/voice/tests/`
- `docs/evidence/voice/`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/LEARNINGS.md`

**Package layout, derived from this repository — not invented.** Portable core lives at
`plugins/voice/` with vendor-neutral `scripts/` and `skills/`, matching
`plugins/unifi/` and `plugins/mission-control/`. The Claude client extension is exactly
`plugins/voice/com.infiquetra.claude/`, carrying its own `plugin.json` like the other
two packages, with the `Stop` hook declared in a `hooks/hooks.json` descriptor at that
extension root per the current Claude plugin contract. `plugins/voice/adapters/**` is
wrong and must never be created.

**Portable runnable surface.** The accepted ideation requires runnable portable
behaviour to be reached through an Agent Skill or a Model Context Protocol server, and
version one rejects a listening MCP tool. The entrypoint is therefore the smallest
Agent Skill — `plugins/voice/skills/voice/SKILL.md` — plus its bundled CLI at
`plugins/voice/scripts/voice_cli.py`, giving the installed package a discoverable way
to start the Voice pane. No MCP server is added.


No change is expected to `.github/workflows/ci.yml`; the existing `plugins/*/tests`
glob already collects a new package's tests.

### Tests to add or update

- `plugins/voice/tests/test_providers.py` — declaration contract, closed egress-class
  set, credential variable name recorded without its value, no silent substitution.
- `plugins/voice/tests/test_settings.py` — retention is a stated setting; absent never
  means empty.
- `plugins/voice/tests/test_process.py` — every spawned subprocess has standard input
  closed and a deadline attached.
- `plugins/voice/tests/test_binding.py` — exactly one binding; persists until changed.
- `plugins/voice/tests/test_stop_hook.py` — unbound session produces no sound; hook
  returns without stalling the turn.
- `plugins/voice/tests/test_text_cleanup.py` — Markdown syntax removed; fenced code
  block contents omitted entirely; no length gate applied.
- `plugins/voice/tests/test_speak.py` — speaks supplied text verbatim; stop interrupts.
- `plugins/voice/tests/test_record.py` — toggle semantics; nothing transcribed before
  the second press; audio deleted after success and after failure.
- `plugins/voice/tests/test_transcribe.py` — hosted provider invoked per declaration;
  no transcript log written; no telemetry emitted.
- `plugins/voice/tests/test_deliver.py` — text arrives unsubmitted; only the bound
  agent is targeted; blocked agent produces refusal and transient retention.
- `plugins/voice/tests/test_pane.py` — bound identity and recording state displayed;
  stop key and barge-in behaviour.
- `plugins/voice/tests/test_preflight.py` — missing provider named rather than
  substituted; Herdr keybinding absence reported; Herdr config never written.

### Context library links

- source_context: docs/brainstorms/2026-08-25-voice-plugin-requirements.md
- ideation: docs/ideation/2026-08-25-voice-plugin-ideation.md
- accepted review: docs/reviews/2026-08-25-voice-plugin-requirements-doc-review.md
- freshness review: docs/reviews/2026-08-25-voice-plugin-requirements-post-integration-freshness-review.md
- runbook: infiquetra-agent-operations `docs/operations/unattended-orchestration.md`

### Per-run inputs (operator-decided 2026-08-25)

Vendor, model, effort, account, and concurrency are per-run operator decisions and are
not inherited from any previous orchestration. Launch templates are **not yet
validated**; a fresh preflight validates every one before dispatch.

| Role | Priority | Vendor and model | Effort | Account | Cap | Template validated? |
| --- | ---: | --- | --- | --- | ---: | --- |
| Saga Plan | — | Claude `claude-fable-5` | maximum | default / personal | 1 | preflight-pending |
| Saga Document Review (of the plan) | — | Grok `grok-4.6` | xhigh | grok.com login | 1 | preflight-pending |
| Work pool 1 | 1 | Qwen `qwen3.8-max-preview` | xhigh | ModelStudio token plan | 4 | preflight-pending |
| Work pool 2 | 2 | Antigravity `gemini-3.7-flash-high` | encoded in the model id | Antigravity login | 4 | preflight-pending |
| Saga Code Review | — | Grok `grok-4.6` | xhigh | grok.com login | 6 | preflight-pending |

Pool selection is deterministic: take the highest-priority pool with free capacity;
never manufacture concurrency to fill a cap. Work pool 2 is a fallback — if it never
runs, the closeout must disclose it as configured capacity, not validated capability.

**Code review.** Exactly one Saga Code Review session owns each frozen work-unit
revision. The reviewed commit is named in the durable typed result. A stale or dirty
revision never merges as reviewed, and reviewer idleness is never acceptance.

**Review consensus.** Every applicable declared lens must score at least 9, with no
lens below 7. Scores are never averaged. Every genuine finding is validated before
repair and then repaired. Maximum three cycles; if the threshold is still unmet, the
best result is retained and the shortfall disclosed. The plan declares the applicable
lenses per unit with a one-line reason; lenses are never invented dynamically at
review time.

**Herdr.** Run-specific workspace names, maximum six simultaneous sessions per
workspace, with deterministic numbered overflow (`voice-run`, `voice-run-2`, …).
Workspace names are fixed at preflight and recorded in the opening run comment.

### Board progression and write ownership

The coordinator is the **only** writer to the Operations board, through Mission
Control's `flow set-field`. No worker or reviewer writes board state.

| Stage | Board status | Trigger |
| --- | --- | --- |
| Contract under operator review | `Shaping` (parent) | now |
| Approved and preflight green | `Active` (parent) | operator approval + fresh preflight |
| Dependencies satisfied | `Ready` (child) | predecessor lane merged |
| Dispatched to a worker | `Active` (child) | unit brief delivered |
| Pull request open, review passed | `Verify` (child) | typed review outcome names the reviewed commit |
| Merged with CI green | `Done` (child) | merge commit + green CI at that commit |
| All children Done, acceptance evidenced | `Done` (parent) | closeout checks below |

Objective field on the parent and on every executable child: `improve-agent-plugins`
(live option id `f39edb7a`, discovered from the live board, never a label).

### Fresh-preflight proof gates

Planning may not rely on any of these until preflight proves it live. Each is a
named, observable proof, not an assumption. **Stop the run on a failed or unexplained
proof** — do not repair a launcher or redesign the run during preflight.

| # | Must be proven | How it is proven | If it fails |
| --- | --- | --- | --- |
| P1 | The current Claude `Stop` hook event fires and supplies `last_assistant_message` | Register a throwaway `Stop` hook and observe the field arrive with the completed response | U2 and U3 are unbuildable as specified; stop and re-derive the hook contract |
| P2 | Hook execution is asynchronous and does not stall the turn | Observe the session continue while a deliberately slow hook runs | R1's non-stalling guarantee is unmet; stop |
| P3 | The Claude hook session identifier joins to Herdr `agent_session.value` | Compare the hook's session id against `herdr agent list` output for the same pane | The binding cannot be resolved; stop — this is the join the whole product rests on |
| P4 | `herdr agent get <agent>` resolves a bound agent to its `pane_id` | Run it against a live agent and read `pane_id` | U5 cannot address a delivery target; stop |
| P5 | `herdr pane send-text <pane_id> "<text>"` delivers literal text **without** Enter | Send text to a live pane and confirm it sits unsubmitted and editable | R16 is unmet and the loop cannot close; stop |
| P6 | Terminal microphone permission is granted (decision D3) | Capture a short sample with `/opt/homebrew/bin/ffmpeg` via AVFoundation | U4 parks; recording cannot be exercised |
| P7 | Every launch template in the per-run vendor table dry-runs cleanly | `agents --dry-run …` for each row | Stop; the affected role has no validated launcher |
| P8 | **Voice Forge text-to-speech is reachable and can actually synthesize** (decision D1) | Resolve `VOICE_FORGE_BASE_URL` from the Home Lab deployment receipt; `GET /health` and require a **usable backend**, not merely a healthy process; `GET /v1/audio/voices` and require the configured `VOICE_FORGE_VOICE_ID` to be present; then `POST /v1/audio/speech` with a short real phrase and verify the response is non-empty, playable audio | **Stop. Do not substitute another text-to-speech provider.** A healthy process with no available backend fails this gate |
| P9 | **Hermes relay speech-to-text resolves xAI and actually transcribes** (decision D2) | `GET {VOICE_HERMES_BASE_URL}/api/health` and require healthy — noting that `auth_required: false` disables only the external OAuth/cookie gate and is **not** proof that protected routes accept anonymous requests. Obtain the loopback session token in memory from `GET {VOICE_HERMES_BASE_URL}/`, then prove `/api/profiles` is callable with `X-Hermes-Session-Token` (HTTP 200) and that the configured `VOICE_HERMES_PROFILE` is present. Verify the profile resolves `stt.provider` = `xai` **without exposing any credential** — the transcription response's own `provider` field is the authoritative resolution. Then `POST /api/audio/transcribe?profile=mimir-engineer` with the same header and a short real audio sample, requiring `provider` = `xai` and the expected non-empty transcript. Confirm `voice` never read `auth.json` and never persisted or logged the session token | **Stop. Do not substitute another speech-to-text provider, and never disable Hermes authentication.** |

Preflight is run once, immediately before dispatch, even though this contract already
records earlier receipts. Record the results in the opening run comment on this issue.

### Stop conditions

The run halts and asks the operator when any of these occurs:

- A unit concludes it must edit `.github/workflows/ci.yml`.
- A unit needs a provider credential, a billing decision, or a paid endpoint. `voice`
  holds no credential of its own: Hermes owns the xAI OAuth token, and any unit that
  finds itself reading `auth.json`, copying a bearer, or wanting `XAI_API_KEY` has hit
  this condition.
- Voice Forge preflight (P8) or Hermes speech-to-text preflight (P9) fails. Stop rather
  than substituting a different provider — R23 forbids silent substitution, and these
  two are decided.
- A unit proposes writing Herdr configuration, which R15 forbids outright.
- Microphone permission cannot be granted to the terminal non-interactively.
- A Saga Code Review is still below the consensus threshold after three cycles.
- Any destructive action, deployment, production mutation, or credential change.
- Unexplained drift between the recorded source pin and the live repository.
- Two units contend for the same owned surface.

### Acceptance criteria

- [ ] All seven child issues are closed with a truthful terminal state: `gh issue list --repo infiquetra/infiquetra-agent-plugins --state open --label capability` lists no `voice` child.
- [ ] Portable core and the Claude client extension are separated at the conventional paths: `test -d plugins/voice/com.infiquetra.claude && test -f plugins/voice/scripts/providers.py && ! test -d plugins/voice/adapters` exits 0.
- [ ] Repository validation passes at the final merged commit: `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] The whole suite passes including the new package: `python3 -m unittest discover -s tests` reports `OK`.
- [ ] The package's own tests pass under the CI collector: `python3 -m pytest plugins/voice/tests -q` reports no failures.
- [ ] No whitespace defects are introduced: `git diff --check` produces no output.
- [ ] Every requirement R1–R33 maps to a merged unit and a passing test, evidenced in `docs/evidence/voice/`: `ls docs/evidence/voice/` lists the acceptance record.
- [ ] The end-to-end loop is manually verified per R33 and recorded: `grep -c "R33" docs/evidence/voice/acceptance.md` returns at least 1.
- [ ] The multi-session silence check passes per AE1, recorded in the same acceptance evidence.
- [ ] The README states the absent provenance manifest and port descriptor plainly per R30, implemented by U1 and verified by U7: `grep -iE "provenance|port descriptor" plugins/voice/README.md` returns a match.
- [ ] The portable Agent Skill entrypoint exists and no MCP server was added: `test -f plugins/voice/skills/voice/SKILL.md && ! grep -riq "mcpServers" plugins/voice/` exits 0.
- [ ] No credential is read or stored by the package: `grep -riE "auth\.json|XAI_API_KEY|Bearer " plugins/voice/scripts/` returns no output.
- [ ] The Hermes session token is never persisted or logged: `grep -riE "HERMES_SESSION_TOKEN.*(open\(|write|log|print)" plugins/voice/scripts/` returns no output.
- [ ] No Hermes internals are imported and no HTTP dependency was added: `grep -riE "^import hermes|from hermes|import requests|import httpx" plugins/voice/scripts/` returns no output.
- [ ] No provider endpoint is hard-coded to an IP address: `grep -rE "https?://[0-9]{1,3}(\.[0-9]{1,3}){3}" plugins/voice/scripts/` returns no output.

### Verification

Run from the repository root at the final merged commit:

```bash
python3 scripts/check_repo.py
python3 -m unittest discover -s tests
python3 -m pytest plugins/voice/tests -q
git diff --check
gh pr checks <final-merge-pr>
```

Expected: validation passes, the suite reports `OK`, the package tests report no
failures, `git diff --check` is silent, and GitHub CI is green at the final merged
commit — not only on the last pull request.

Closeout additionally requires: every merged pull request and reviewed commit named
in the parent's closing comment; per-lane outcomes, residual risks, and operator
rulings recorded; the Operations board objective and status fields passing a closing
readback; run-owned branches, worktrees, and sessions removed only after evidence is
durable; and any pool that never ran disclosed as unexercised.

### Operator decision table

**All six decisions are settled. There is no remaining provider decision gate.** The
run continues unattended and pauses only for a genuine stop condition outside its
authority.

| # | Decision | Status | Ruling |
| --- | --- | --- | --- |
| D1 | Text-to-speech provider and egress class | **RESOLVED** | **Voice Forge on the Mac mini**, reached over the local network. Egress class **`local-network`** — not `on-device`. Configured through non-secret `VOICE_FORGE_BASE_URL` (from the Home Lab deployment receipt) and `VOICE_FORGE_VOICE_ID` (a registered Voice Forge voice). No IP address is hard-coded. Synthesis uses `POST /v1/audio/speech` with Voice Forge's OpenAI-compatible request shape |
| D2 | Speech-to-text provider, credential owner, and egress declaration | **RESOLVED** | **xAI Grok speech-to-text through the local Hermes relay.** `voice` calls `POST {VOICE_HERMES_BASE_URL}/api/audio/transcribe?profile={VOICE_HERMES_PROFILE}`, acceptance values `http://127.0.0.1:8765` and `mimir-engineer`, attaching the in-memory loopback `X-Hermes-Session-Token` read from the local dashboard root. **No new credential environment variable.** Credential owner: Hermes xAI OAuth. **Effective audio egress: `external`**, because Hermes forwards the audio to xAI |
| D3 | Audio capture tool and microphone permission | **RESOLVED** | `/opt/homebrew/bin/ffmpeg` using the macOS AVFoundation input device. Terminal microphone permission is confirmed during preflight (gate P6), not assumed at run time |
| D4 | The Herdr-wide `voice stop` keybinding | **RESOLVED — yes** | The operator adds the documented keybinding. `voice` only preflights and reports its presence (R14) and never writes Herdr configuration (R15) |
| D5 | Retention posture | **RESOLVED — ephemeral** | Temporary audio deleted after both success and failure; no `voice` transcript log; no telemetry. Planning chooses the smallest clear setting *name*; the behaviour is settled and written down rather than defaulted (R28) |

**Provider boundary — what stays outside `voice`.** Provider installation, OAuth
refresh, service management, billing, and credentials all remain outside the plugin
(R24). Hermes owns the xAI OAuth token and the xAI request; `voice` must never read
`auth.json`, copy a bearer, import Hermes internals, or require an `XAI_API_KEY`. The
Home Lab System Update session owns upgrading the Mac mini Voice Forge installation and
making it reachable; this run neither modifies Home Lab nor waits on that session.

**Loopback session token — how `voice` calls the relay.** `auth_required: false` on
`/api/health` means Hermes' external OAuth/cookie gate is disabled. It does **not** make
protected API routes anonymous: the running dashboard requires its rotating loopback
session token on non-public routes, and an anonymous call returns `401`.

`voice` uses the same supported client flow as Hermes Desktop:

1. `GET {VOICE_HERMES_BASE_URL}/` and read the injected `window.__HERMES_SESSION_TOKEN__`
   value from the served page.
2. Hold it **in process memory only** and send it as the `X-Hermes-Session-Token` header
   on `/api/audio/transcribe` requests.
3. On `401`, refresh the token once from the local root page and retry **once**, because
   the token rotates when Hermes restarts. **One refresh, one retry — never a loop.**

The token is a transport detail, not a declared credential: no new environment variable
is introduced, and `VOICE_HERMES_BASE_URL` and `VOICE_HERMES_PROFILE` are unchanged.
`voice` must never read `auth.json`, copy the xAI OAuth bearer, persist or log the
session token, pass it in command arguments or evidence, or disable Hermes
authentication.

Both providers are reached over plain HTTP behind the U1 declaration contract, so the
provider boundary stays replaceable. `voice` depends on no Hermes Python module and no
Hermes repository code.

**Runtime proofs are not yet run.** D1 and D2 are *decided*, not *proven*. Gates P8 and
P9 above are the proofs, and they belong to the fresh preflight after Home Lab finishes
the Mac mini deployment.


### Authority

Granted for this run: create and manage run branches, worktrees, and pull requests;
perform reviewed merges; update issues and the Operations board; and perform
evidence-based cleanup of run-owned resources only.

Withheld: destructive actions, deployments, production mutations, and credential
changes. Cleanup happens only after the evidence it would remove is durable
elsewhere. Pre-existing artifacts and unrelated sessions are never touched.

### Run posture

**This becomes an unattended run only after the operator approves this contract and a
fresh preflight passes green.** Both conditions are required; neither is assumed.

Once running, it continues without routine supervision. **Every operator decision gate
is now resolved**, so it pauses for exactly one thing: a genuine stop condition outside
its authority. It does not pause to confirm work it is already authorized to do, and it
never answers an operator decision gate on the operator's behalf.

**The coordinator is the sole Operations-board writer**, and keeps parent and child
Status fields current as dependencies satisfy, units dispatch, reviews pass, pull
requests merge, and closeout completes. Workers and reviewers never write board state.

### Handoff maturity

requirements-ready

### Suggested next action

Operator review of this contract. On approval, run a fresh preflight, then `/plan`
covering all seven units before any dispatch.

### Source context

- Source: docs/brainstorms/2026-08-25-voice-plugin-requirements.md
- Source type: brainstorm
- Source title: Voice Plugin — Requirements
- Source pin: `main` at `794fe46` (PR #26 merge commit)

### Recommended Tier Band

`opus/high` — **generated default, NOT authoritative.** The per-run vendor table above
is the authority: Saga Plan runs on Claude Fable 5 (`claude-fable-5`) at maximum
effort. Ignore this generated band wherever the two disagree.

### Intent envelope

```intent-envelope
{
  "schema_version": 1,
  "run_mode": "unattended",
  "ceremony_gates": {
    "reviews_required": "auto",
    "merge": "auto",
    "deploy_nonprod": "gate"
  },
  "source": "issue-capture",
  "authored_at": "2026-08-25T15:08:50Z",
  "authored_by": "jeff"
}
```
