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
| U1 | #28 | Package foundation, provider declaration contract, retention setting, subprocess discipline | G1 | — | R20, R21, R23, R24, R28, R29, R30, R31, R32 | `plugins/voice/{__init__.py,plugin.json,README.md,providers.py,settings.py,process.py}` |
| U2 | #29 | Claude adapter: `Stop` hook, binding store, single-speaker guard | G2 | U1 | R1, R2, R3 | `plugins/voice/binding.py`, `plugins/voice/adapters/claude/**` |
| U3 | #30 | Speak path: Markdown cleanup, code-block omission, synthesis invocation | G2 | U1 | R5, R6, R7 | `plugins/voice/text_cleanup.py`, `plugins/voice/speak.py` |
| U4 | #31 | Listen path: toggle recording, hosted transcription, audio deletion, no log, no telemetry | G2 | U1 | R10, R12, R25, R26, R27 | `plugins/voice/record.py`, `plugins/voice/transcribe.py` |
| U5 | #32 | Deliver path: unsubmitted insertion, bound-only target, blocked refusal, transient retention | G3 | U1, U2, U4 | R16, R17, R18, R19 | `plugins/voice/deliver.py` |
| U6 | #33 | Voice pane and preflight: identity and recording display, stop key, barge-in, provider and keybinding preflight | G3 | U1, U2, U3, U4 | R4, R8, R9, R11, R13, R14, R15, R22 | `plugins/voice/{pane.py,cli.py,preflight.py}` |
| U7 | #34 | Acceptance evidence, README truth statement, journal closeout | G4 | U1–U6 | R33 | `docs/evidence/voice/**`, `plugins/voice/README.md` (final), `docs/engineering-journal/**` |

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
          ├───────▶│ U3 │───────┐   │                ├───▶┌────┐
          │        └────┘       │   │                │    │ U7 │
          │        ┌────┐       │   │      ┌────┐    │    └────┘
          └───────▶│ U4 │───────┴───┴─────▶│ U6 │────┘
                   └────┘                  └────┘

U1 → everything (package root, provider contract, subprocess helper)
U5 ← U2 (binding target) + U4 (transcript)
U6 ← U2 (identity display) + U3 (stop playback) + U4 (indicator, barge-in)
U7 ← all six (end-to-end acceptance)
```

**Shared-file collision rules.** Every path below has exactly one writing owner for
the whole run. A unit that believes it must edit another unit's surface stops and
raises the conflict instead of editing.

| Surface | Sole writer | Rule for everyone else |
| --- | --- | --- |
| `plugins/voice/` package root, `plugin.json` | U1 | Add new modules only; never edit U1's files |
| `plugins/voice/providers.py`, `settings.py`, `process.py` | U1 | Import and consume; never modify |
| `plugins/voice/binding.py` | U2 | Read the binding through U2's interface |
| `plugins/voice/README.md` | U1 creates, **U7 finalizes** | Serialized: no other unit writes it |
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

- `plugins/voice/__init__.py`
- `plugins/voice/plugin.json`
- `plugins/voice/README.md`
- `plugins/voice/providers.py`
- `plugins/voice/settings.py`
- `plugins/voice/process.py`
- `plugins/voice/binding.py`
- `plugins/voice/adapters/claude/stop_hook.py`
- `plugins/voice/text_cleanup.py`
- `plugins/voice/speak.py`
- `plugins/voice/record.py`
- `plugins/voice/transcribe.py`
- `plugins/voice/deliver.py`
- `plugins/voice/pane.py`
- `plugins/voice/cli.py`
- `plugins/voice/preflight.py`
- `plugins/voice/tests/`
- `docs/evidence/voice/`
- `docs/engineering-journal/DECISIONS.md`
- `docs/engineering-journal/LEARNINGS.md`

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

### Stop conditions

The run halts and asks the operator when any of these occurs:

- A unit concludes it must edit `.github/workflows/ci.yml`.
- A unit needs a provider credential, a billing decision, or a paid endpoint.
- A unit proposes writing Herdr configuration, which R15 forbids outright.
- Microphone permission cannot be granted to the terminal non-interactively.
- A Saga Code Review is still below the consensus threshold after three cycles.
- Any destructive action, deployment, production mutation, or credential change.
- Unexplained drift between the recorded source pin and the live repository.
- Two units contend for the same owned surface.

### Acceptance criteria

- [ ] All seven child issues are closed with a truthful terminal state: `gh issue list --repo infiquetra/infiquetra-agent-plugins --state open --label capability` lists no `voice` child.
- [ ] The package exists with its portable core and Claude adapter separated: `test -d plugins/voice/adapters/claude && test -f plugins/voice/providers.py` exits 0.
- [ ] Repository validation passes at the final merged commit: `python3 scripts/check_repo.py` prints `Repository validation passed.`
- [ ] The whole suite passes including the new package: `python3 -m unittest discover -s tests` reports `OK`.
- [ ] The package's own tests pass under the CI collector: `python3 -m pytest plugins/voice/tests -q` reports no failures.
- [ ] No whitespace defects are introduced: `git diff --check` produces no output.
- [ ] Every requirement R1–R33 maps to a merged unit and a passing test, evidenced in `docs/evidence/voice/`: `ls docs/evidence/voice/` lists the acceptance record.
- [ ] The end-to-end loop is manually verified per R33 and recorded: `grep -c "R33" docs/evidence/voice/acceptance.md` returns at least 1.
- [ ] The multi-session silence check passes per AE1, recorded in the same acceptance evidence.
- [ ] The README states the absent provenance manifest and port descriptor plainly per R30: `grep -iE "provenance|port descriptor" plugins/voice/README.md` returns a match.

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

These are genuine human gates. The run parks the affected unit in a draft pull
request linked with `Relates to`, continues independent lanes, and records the ruling
as a durable comment. No unit invents an answer.

| # | Decision | Why it cannot be inferred | If no ruling arrives |
| --- | --- | --- | --- |
| D1 | Which text-to-speech provider to declare, and its egress class | R20 and R24 put provider choice, credentials, and billing outside the plugin | U3 lands with the declaration contract and no declared provider; the loop stays unproven |
| D2 | Which hosted speech-to-text provider to declare | Same; "hosted" also makes egress external by design, which R21 requires be stated | U4 lands unproven; U7 acceptance cannot complete |
| D3 | Which capture tool records audio, and confirmation that the terminal holds microphone permission | The requirements assume the terminal grants microphone access and inherits it; that assumption is stated, not verified | U4 parks; recording cannot be exercised |
| D4 | Whether the operator adds the Herdr-wide `voice stop` keybinding | R14 preflights its presence; R15 forbids Voice writing Herdr config, so only the operator can add it | U6 reports the absence, which satisfies R14; the third stop form stays unavailable |
| D5 | The retention setting's written default | R28 requires the empty case be something a person wrote down, not a silent default | U1 parks the setting rather than choosing for the operator |

### Authority

Granted for this run: create and manage run branches, worktrees, and pull requests;
perform reviewed merges; update issues and the Operations board; and perform
evidence-based cleanup of run-owned resources only.

Withheld: destructive actions, deployments, production mutations, and credential
changes. Cleanup happens only after the evidence it would remove is durable
elsewhere. Pre-existing artifacts and unrelated sessions are never touched.

### Run posture

Intended to run unattended, but only after the operator approves this completed
contract and a fresh preflight passes. Unattended means it does not need routine
supervision; it does not mean the decision gates above are answered by an agent.

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

opus/high

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
