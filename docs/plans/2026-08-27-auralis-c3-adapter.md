---
title: Auralis C3 Claude adapter implementation plan
type: feat
status: active
date: 2026-08-27
origin: https://github.com/infiquetra/auralis/blob/b49de1ba4d39cbd8a1e582d72bddca85bf528f8a/docs/brainstorms/2026-08-26-auralis-v1-requirements.md
backend: inline
---

# Auralis C3 Claude adapter implementation plan

## Summary

Implementation plan for [infiquetra/infiquetra-agent-plugins#46](https://github.com/infiquetra/infiquetra-agent-plugins/issues/46),
capability slice C3 of the Auralis V1 hierarchy (lane D): the adapter end of the versioned
local bridge, built by extending the existing `plugins/voice` package in this repository.
Five implementation units (U1–U5) add a bridge wire client and adapter identity resolver, a
plain-spoken-text rendering gate, a voice-policy store, a Model Context Protocol (MCP)
authored-rendering surface, three Claude hooks (turn origin, PreToolUse capture, completion
reconciliation), and the packaging that ships it all as voice `0.3.0`. Everything is
standard-library Python at the repository floor `python>=3.12`, tested with `unittest`,
with no third-party dependency — the same constraints the voice package proved at `0.2.1`.

Base for the run: `f981ed4` on `origin/main`, re-resolved at planning preflight on
2026-08-27 and verified equal to `origin/main` at that time. Backend is **inline** for
every unit.

**Revised 2026-08-27** against the blocking document review at
[`docs/reviews/2026-08-27-auralis-c3-adapter-plan-doc-review.md`](../reviews/2026-08-27-auralis-c3-adapter-plan-doc-review.md);
all twelve findings (F1–F12) are repaired — the per-finding disposition table is at the
end of this document.

## Problem Frame

Auralis V1 is a private, single-operator macOS application that gives one bound,
Herdr-managed coding-agent session a spoken conversational loop. Its Core (repository
`infiquetra/auralis`, slice C10) exposes a loopback HTTP bridge; the agent side of that
bridge — the piece that runs inside the Claude Code process space — is this slice, and it
is the only Auralis V1 slice that lands outside the `auralis` repository. Without it, the
bound agent has no way to know a turn came in by voice, no instructions about how the
operator wants speech rendered, and no surface through which to submit the spoken rendering
it authors. The slice is complete on its own at this boundary: the plain-text submission
contract is observable at the surface with no audio (acceptance example AE26), and AE34
later proves interoperation with C10.

**R-ID namespace note.** Every R-number in this document (R20, R121, …) is an Auralis V1
requirements-document ID from
[`2026-08-26-auralis-v1-requirements.md`](https://github.com/infiquetra/auralis/blob/b49de1ba4d39cbd8a1e582d72bddca85bf528f8a/docs/brainstorms/2026-08-26-auralis-v1-requirements.md),
an immutable commit permalink at revision `b49de1ba4d39cbd8a1e582d72bddca85bf528f8a`
(verified present at that revision on 2026-08-27; the short form `b49de1b` used elsewhere
in run artifacts resolves to this full SHA). The voice package's own earlier plan and acceptance ledger use a
*different* R1–R33 numbering from the voice 0.2.x run; the two namespaces do not overlap in
meaning, and this plan never uses the voice-run numbering.

## Wire authority — the pin, and the one honest flag on it

The normative wire contract is **Auralis Bridge Contract v1**, authored by capability
slice C10 in `infiquetra/auralis`, whose Saga Code Review is accepted. Its authoritative
home is `docs/bridge/bridge-v1.md` in `infiquetra/auralis` at revision
`695cd0ecfddf44e0d6e3386da318bd5fde4a1926` (the accepted-review revision, currently on the
`auralis` run branch `orch/auralis-v1-phase1`). Because this repository's implementation
and CI run from clean checkouts that cannot see another repository's unmerged branch, a
**tracked byte-identical snapshot** of that exact revision is committed here at
[`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md). The snapshot carries no local
header or edit of any kind, so its integrity is checkable by hash alone:

- Snapshot SHA-256: `eb47d141e5c1b87bae0bd1c0799386a3aa8806635251db14fc806469b5db19eb`.
- Reproduction: `git -C <auralis checkout> show 695cd0ecfddf44e0d6e3386da318bd5fde4a1926:docs/bridge/bridge-v1.md | shasum -a 256`
  yields the same digest (verified 2026-08-27).

The contract defines discovery, authentication, the five routes, request/response bodies,
transport errors, processing precedence, the adjudication order and rejection vocabulary,
identifier semantics, retry rules, and extension rules, and it names C3 as its consumer.
Every contract citation in this plan (a "§" reference) is a section of that snapshot.

**Flag:** the contract has **not yet merged to `auralis` main**. This adapter's wire
assumptions are pinned to the accepted-review revision above, not to a released artifact.
Mitigations: every wire literal is centralized in one module (U1) and one stub fixture
(`plugins/voice/tests/bridge_stub.py`, U1), so a contract change before merge is a bounded
re-touch; the joint acceptance AE34 re-validates the wire against the real Core before the
run closes. If C10 amends the contract, the snapshot is refreshed by the same
extract-and-hash procedure and the new revision and digest are recorded here.

C10's own acceptance stub deliberately imports no production bridge library, so the wire is
provable from independent literals on both sides. This adapter's tests stand on the same
discipline (KTD9).

## Grounded facts (verified 2026-08-27 in this repository)

- Branch `orch/auralis-c3-adapter-plan-c3-adapter` is at `f981ed4`, equal to
  `origin/main` after `git fetch` at preflight.
- The voice package is the proven first thin adapter: its Stop hook detaches and speaks
  only for the one bound session
  ([`stop_hook.py:64`](../../plugins/voice/com.infiquetra.claude/hooks/stop_hook.py)), the
  binding store is atomic machine-local JSON
  ([`binding.py:110`](../../plugins/voice/scripts/binding.py)), and settings are a closed
  stated set ([`settings.py:81`](../../plugins/voice/scripts/settings.py)).
- The Claude packaging layout is pinned by the 2026-08-25 decision "Claude installs the
  package root" in [`DECISIONS.md`](../engineering-journal/DECISIONS.md) and enforced both
  ways by `tests/test_claude_plugin_packaging.py`, including four-site version agreement
  (`plugins/voice/plugin.json`, `plugins/voice/.claude-plugin/plugin.json`,
  `plugins/voice/com.infiquetra.claude/plugin.json`, `.claude-plugin/marketplace.json`).
- CI is the `Validate` workflow ([`ci.yml`](../../.github/workflows/ci.yml)): hermetic
  `scripts/check_repo.py` + repo `unittest` suite + `git diff --check`, plus a
  `plugin-tests` job that runs `pytest plugins/*/tests -q` on Python 3.12. New tests must
  pass under both runners; plain `unittest` suites satisfy both.
- `check_repo.py` also validates markdown link targets, plugin manifest `$schema`
  literals, skill frontmatter, and secret-free values — so this plan document itself, the
  new manifests, and every test fixture must use resolving links and inert example
  credentials (a bridge-token fixture must be an obviously fake value).
- Markdown-recognition precedent for the R121 gate already exists in the package: the
  speak path's cleanup pass defines exact regex classes for fences, headings, emphasis,
  links, inline code, lists, blockquotes, horizontal rules, and table pipes
  ([`text_cleanup.py:27`](../../plugins/voice/scripts/text_cleanup.py)). Its own module
  docstring bounds it as a small line-and-regex cleanup whose fidelity beyond the tested
  classes is not a goal — so it *seeds* the gate's overlapping detector classes but does
  not bound them: the gate owns a complete rejected-syntax contract of its own (KTD1,
  U2), and never the transformation (R121 forbids repair).
- Claude Code platform facts, verified against current documentation on 2026-08-27
  (plugins-reference and hooks pages at code.claude.com):
  - `.claude-plugin/plugin.json` `mcpServers` accepts a **string path** to a separate
    JSON config file, exactly like `hooks` — so the packaging manifest can stay pure
    distribution metadata and the server command can live inside the client extension.
  - `${CLAUDE_PLUGIN_ROOT}` expands inside MCP server `command`/`args`; plugin MCP
    servers start when the plugin is enabled and persist for the session (not respawned
    per call) — a long-lived adapter process exists for free (KTD2).
  - `UserPromptSubmit` hooks inject context via plain stdout on exit 0 or via
    `hookSpecificOutput.additionalContext`; stdin carries `session_id` and `prompt`.
  - `PreToolUse` stdin carries `tool_name`, `tool_input`, and `tool_use_id`; exit 0 with
    no output leaves the permission flow completely unchanged (observe-only is
    supported). This matches the X1 exploration finding, which reported no refutation.
  - `Stop` stdin carries `last_assistant_message` (already relied on at voice 0.2.1).
- X1 (the PreToolUse exploration gate) reported no refutation: exact `tool_name`,
  structured `tool_input`, immutable `tool_use_id`; an allow-list is matchable and
  compare-and-submit is expressible through the hook's own permissionDecision schema.
  Treated as given per the card.
- Open voice findings F6 (stray-capture sweep, #43) and F7 (`VOICE_RETENTION` never
  consulted at runtime, #44) do not intersect this slice's surfaces and stay untouched.

## Requirements

The slice owns nine of the run's 136 requirements. Each row states what must hold, what
part of it is observable at this slice boundary, and where it is traced.

| R-ID | Requirement (condensed) | At this boundary | Traced by |
|---|---|---|---|
| R20 | The bound agent authors the spoken rendering; Auralis and its adapter never compose, summarize, shorten, or rewrite response content | No code path in the adapter transforms rendering text; the gate rejects, never repairs; accepted text is forwarded byte-identical | `plugins/voice/tests/test_rendering_gate.py`, `plugins/voice/tests/test_mcp_server.py` |
| R21 | Auralis exposes an MCP surface through which the bound agent submits an authored spoken rendering for the current turn | The adapter *is* that surface in the agent's process space: an MCP stdio server with a `submit_spoken_rendering` tool that forwards to `POST /v1/rendering` | `plugins/voice/tests/test_mcp_server.py` |
| R22 | A turn completed without an authored rendering falls back to the cleaned full written response rather than silence | C3 owns this requirement, but its mechanism is C5's in-process `acceptFallback()` (see "The R22/R23 fallback seam"). The adapter's share: submit only gated plain text, never fabricate a submission, let the turn complete with no accepted authored rendering, and durably record that completion. Fallback initiation, content sourcing, and speech are Core/C5 (joint AE36) | `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_r122_end_to_end.py`; joint AE36 |
| R23 | A fallback turn is visibly marked as a fallback, distinguishable from an authored response | The distinguishing mark is Core's `fallback_accepted` turn state (contract §6.4), written when C5 calls `acceptFallback()`. The adapter's share: keep the two outcomes disjoint in its own record (`fallback` vs `authored`) so the adapter-side evidence agrees with the Core-side mark (joint AE36) | `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_turn_record.py`; joint AE36 |
| R25 | No persistent verbosity mode; preferences are carried to the agent as instructions; no adapter content decision | The policy module renders preferences to instruction text only; the adapter has no verbosity state that alters content and no transformation path | `plugins/voice/tests/test_voice_policy.py` |
| R106 | For every turn, tell the agent whether the turn originated through Auralis | UserPromptSubmit hook queries `GET /v1/current`, matches identity, and injects an explicit originated/not-originated signal on every turn while bound | `plugins/voice/tests/test_user_prompt_submit_hook.py` |
| R107 | Carry the operator's current voice policy and preferences, including an armed one-shot Brief Next Turn override, to the agent as instructions; transmit, never apply | Policy (with armed override) rides the same injection on Auralis-originated turns; the one-shot is consumed on transmission | `plugins/voice/tests/test_user_prompt_submit_hook.py`, `plugins/voice/tests/test_voice_policy.py` |
| R121 | The agent-facing surface accepts plain spoken text only; Markdown or fenced code is rejected at submission with a named reason; never silently cleaned or reformatted | The gate rejects with `fenced_code_block` or `markdown_formatting` before anything reaches the wire; resubmission of plain text is accepted (AE26) | `plugins/voice/tests/test_rendering_gate.py`, `plugins/voice/tests/test_mcp_server.py` |
| R122 | A rendering rejected under R121 with no acceptable replacement before turn completion falls back under R22, marked as a fallback | The turn record carries the rejection(s) with named reasons; completion capture then records outcome `fallback` — the full rejection-to-fallback path is observable in adapter state | `plugins/voice/tests/test_mcp_server.py`, `plugins/voice/tests/test_stop_hook.py` |

## High-level design

One walk of a voice turn, naming every new module. Auralis Core starts a voice turn (the
operator spoke); the operator's transcribed prompt reaches the bound Claude session. The
**UserPromptSubmit hook** (`user_prompt_submit_hook.py`, U4) reads `bridge.json` via the
**bridge client** (`bridge_client.py`, U1), resolves the adapter's three-part identity via
the **identity resolver** (`adapter_identity.py`, U1), calls `GET /v1/current`, and — when
an open turn exists and the bound identity is this session — writes the turn's
`(binding_id, turn_id)` into the **turn record** (`turn_record.py`, U2) and injects
context: this turn originated through Auralis, a spoken rendering is expected, and here are
the operator's current voice-policy instructions rendered by the **policy store**
(`voice_policy.py`, U2), including any armed one-shot Brief Next Turn override (consumed on
transmission). A turn with no open voice turn gets the explicit opposite signal while
bound, and no signal at all when the bridge or binding is absent.

During the turn, the **PreToolUse hook** (`pre_tool_use_hook.py`, U4) appends
`{tool_name, tool_input, tool_use_id}` observations to the same single-turn record —
observe-only, never a permission decision.

When the agent authors its spoken rendering, it calls the `submit_spoken_rendering` tool on
the **MCP server** (`mcp_server.py`, U3) — the plugin-declared stdio server that is also
the adapter's long-lived process, running the presence-renewal loop (`PUT /v1/presence` on
the lease cadence, `DELETE` on shutdown). The tool runs the **rendering gate**
(`rendering_gate.py`, U2): Markdown or fenced code is rejected with a named reason and
nothing touches the wire; plain text is forwarded byte-identical to `POST /v1/rendering`
using the *prompt-time captured* identifier pair, and Core's disposition (accepted, or a
wire rejection reason) is relayed verbatim. Every submission and disposition lands in the
turn record.

When the turn settles, the extended **Stop hook** (`stop_hook.py`, U4) reconciles: if this
session is wire-bound and the voice turn ended without an accepted authored rendering, it
records outcome `fallback`; if a rendering was accepted, outcome `authored`. While
wire-bound it suppresses the legacy local speak path — Auralis owns speech — and when not
wire-bound the 0.2.1 behaviour is byte-for-byte unchanged. The recorded outcome is
adapter-side *evidence* of the turn's disposition, not the fallback mechanism itself; the
mechanism is Core/C5's, per the seam below.

## The R22/R23 fallback seam — who does what

C3 owns requirements R22 and R23, but the mechanism that satisfies them lives in Auralis
Core: the contract's downstream-consumption table (§9) assigns `acceptFallback()` to
capability slice C5 (Audio), which calls it prior to fallback speech, exactly as it calls
`startTurn()` on recording and `cancelTurn()` on barge-in. `acceptFallback()` is an
in-process Core API. It is deliberately **not** one of the five wire routes, and this plan
neither invents a wire operation for it nor asks C10 for one. This section states the
ownership boundary explicitly so the split cannot be misread as a missing path.

**What the adapter (C3) is responsible for.**

- Rejecting a non-plain-text authored rendering at submission with a named reason under
  R121 (`fenced_code_block` / `markdown_formatting`), forwarding nothing to the wire, and
  never cleaning, rewriting, or substituting content.
- Never fabricating a submission: when no acceptable rendering is authored (including the
  R122 case — a named rejection with no replacement), the adapter lets the turn complete
  with **no accepted authored rendering**. On the wire this is simply the absence of an
  accepted `POST /v1/rendering` for the captured `(binding_id, turn_id)`; the turn slot
  Core holds for that pair stays in state `open` as far as C3's actions are concerned.
- Durably recording the adapter-side view: the turn record carries the named rejection(s)
  and the settled outcome (`fallback` vs `authored`, disjoint), which is the observable
  R122 evidence trail at this repository's boundary.
- Suppressing the legacy local speak path while wire-bound, so Core's fallback speech is
  never doubled by a local one.

**What Core and C5 are responsible for** (inside `infiquetra/auralis`, out of C3's
custody).

- Deciding the fallback moment for a turn that has no accepted authored rendering, and
  initiating fallback speech: C5 calls `acceptFallback()` prior to fallback speech (§9).
- Sourcing the fallback content — R22's "cleaned full written response". How Core obtains
  the completed written response is Core-side design inside C10/C5's custody; no committed
  wire route carries it, and the adapter neither can nor should supply it.
- Marking the fallback visibly: `acceptFallback()` transitions the turn to the
  `fallback_accepted` state (§6.4), the Core-side mark R23 requires, distinguishable from
  `authored_accepted`.

**How R22 and R23 are therefore discharged.** R22's condition ("turn completed without an
authored rendering") is jointly produced: the adapter guarantees no un-gated or fabricated
rendering is ever accepted, and Core observes the absence of an accepted rendering for the
turn. R22's action (speak the full written response instead of silence) and R23's mark
(`fallback_accepted`) are executed entirely by Core/C5 through `acceptFallback()`. The
adapter's `fallback` outcome record is the C3-side half of the evidence; the Core-side
half is the turn state. The two halves are joined at the acceptance boundary, not on the
wire.

**Named cross-slice dependency (satisfied at AE36, not by C3 alone).** C3 cannot alone
make a fallback audible or marked. For R22/R23 to hold end to end, C5 must (a) detect the
fallback moment for an unrendered completed turn, (b) obtain the turn's completed full
written response by a Core-side mechanism, and (c) call `acceptFallback()` so the turn is
spoken and marked `fallback_accepted`. That is a legitimate dependency on C5's slice — the
contract already assigns C5 the API — and the joint acceptance AE36 is where the
cross-boundary behaviour is proven. If C5's implementation cannot source the written
response, that is C5/C10's finding to surface in their slice; nothing in this plan papers
over it, and no adapter-local JSON label is claimed to substitute for the Core-side mark.

## Key Technical Decisions

### KTD1 — R121 enforcement lives in the adapter surface, with a three-class result vocabulary

**Decision.** The plain-spoken-text rule is enforced in the adapter's MCP surface, before
the wire. The tool result vocabulary has three disjoint classes: `rejected_content` with
adapter-owned reasons (`fenced_code_block`, `markdown_formatting`), `rejected_by_core`
relaying the wire's adjudication vocabulary verbatim (`no_binding` … `empty_rendering`),
and `unavailable` with a named operational condition (`bridge_unavailable`, `not_bound`,
`no_current_turn`, `transport_error`, `turn_record_busy`). Precedence for content reasons: any fence yields
`fenced_code_block`; otherwise any other detected class yields `markdown_formatting`, with
the detected classes and first offending line named in the detail. The gate enforces a
**complete, closed rejected-syntax contract owned by the gate itself** — the full class
list is enumerated in U2's design notes — not the narrower recognizer set of the speak
path's cleanup pass, whose documented scope (a small line-and-regex cleanup, fidelity
beyond its tested classes explicitly not a goal) is too small to prove R121.

**Rationale.** The bridge's adjudication order (contract §6.5) contains no plain-text
reason — Core accepts text verbatim — so the agent-facing surface is the only place R121
*can* live. Splitting the vocabulary keeps adapter judgments, Core judgments, and
availability states impossible to confuse, and rejection reasons are named so the agent can
resubmit (R121's whole point). Everything except content form is left to Core: a single
adjudicator for turn currency, duplicates, and emptiness avoids duplicated logic that could
drift.

**Rejected.** Cleaning the submission with the existing cleanup pass (R121 explicitly
forbids repair); asking C10 for a wire-level plain-text reason (Core endpoint is C10's
custody; adapter-side enforcement needs no cross-lane edit); pre-checking emptiness
adapter-side (duplicates Core's `empty_rendering` adjudication for no gain).

**Revisit when.** A bridge v2 adds content adjudication to the wire, or the run amends
R121's detection classes.

### KTD2 — The MCP server process is the adapter's long-lived process; hooks are one-shot clients

**Decision.** The presence lifecycle (discovery retry at the contract cadence,
`PUT /v1/presence` renewal at or before `renew_after_ms` as returned by Core, re-discovery
on credential rotation, best-effort `DELETE /v1/presence` on stdin EOF) lives in a
background thread of the plugin-declared MCP stdio server. Hooks are ephemeral processes
that each perform single cheap bridge reads and exit.

**Rationale.** Verified platform fact: plugin MCP servers start when the plugin is enabled
and persist for the whole session — a supervised long-lived process the package gets for
free, in exactly the process that also owns the submission tool. The lease cadence
(15,000 ms lease, renew at 5,000 ms) cannot be met by ephemeral hook processes.
Multiple concurrent Claude sessions each run their own server and register their own
identity; the contract's presence model is per-identity leases and Core's binding epoch
chooses one, so this is contract-clean.

**Rejected.** A separate daemon with its own installer and lifecycle (new operational
surface, nothing needs it); presence renewal from hooks (cannot hold the cadence); no
presence at all (the contract names C3 as running the presence renewal loop).

**Revisit when.** The client changes plugin-MCP lifecycle, or bridge v2 changes the lease
model.

### KTD3 — Turn origin is resolved at prompt time from `GET /v1/current`, explicit both ways while bound, silent otherwise

**Decision.** The UserPromptSubmit hook decides origin per turn: Auralis-originated if and
only if `GET /v1/current` shows an open turn whose binding identity equals this session's
resolved identity (byte-exact, all three components, and the hook payload's `session_id`
must equal the resolved `agent_session_id`). While a binding epoch for this session is
active, every turn gets an explicit signal — originated or not-originated (R106's "for
every turn"). When the bridge is unavailable, discovery fails, identity does not resolve,
or no binding epoch names this session, the hook stays silent: no expectation exists, and
injecting "not through Auralis" into every unbridged session forever would be noise.

**Rationale.** `GET /v1/current` is the contract's designated snapshot for exactly this
question, and the single-slot turn registry makes "open turn + my identity" a precise
definition of an Auralis-originated turn: a typed prompt while bound has no open voice
turn and reads not-originated.

**Rejected.** Always-explicit signalling even with no bridge (permanent noise in every
Claude session on the machine); Core marking the prompt text itself (Core-side change, not
in the committed contract; also fragile against prompt editing).

**Revisit when.** The bridge exposes an explicit turn-origin field, or R106's wording is
amended by the operator.

### KTD4 — Submissions use the prompt-time captured identifier pair, never a fresh read

**Decision.** The `(binding_id, turn_id)` pair captured by the UserPromptSubmit hook at
turn origin is stored in the turn record and used verbatim for `POST /v1/rendering`. The
MCP server never re-reads `GET /v1/current` to pick identifiers at submission time. No
captured pair (or a record from a different `session_id`) means there is nothing to submit:
the tool answers `unavailable` / `no_current_turn`.

**Rationale.** Contract §8: the adapter "obtains active identifiers from `GET /v1/current`,
verifies its identity match, and carries the exact pair through its agent surface." A fresh
read at submission time would silently retarget a late rendering at whatever turn is
current — the wrong-turn hazard. Using the captured pair makes Core's own adjudication
(`turn_not_current`, `turn_canceled`) the arbiter of staleness, which is exactly what the
vocabulary is for.

**Rejected.** Fresh `GET /v1/current` at submission (wrong-turn hazard); passing
identifiers through the injected context and making the agent echo them (leaks wire
plumbing into agent-visible instructions and trusts the agent to copy opaque strings
correctly).

**Revisit when.** Bridge v2 changes identifier custody.

### KTD5 — Voice policy is an adapter-local store; transmit-only; the one-shot override is consumed on transmission

**Decision.** Policy and preferences live in an adapter-owned JSON file in the package
state directory, managed by `voice_policy.py` with the package's atomic-write and
absent-vs-corrupt-reported conventions. The store carries free-form preference instructions
plus one boolean one-shot: Brief Next Turn. Rendering to instruction text is the only
consumer; nothing in the adapter ever applies a preference to content (R25). The one-shot
is consumed atomically when transmitted into a turn's injected instructions. Arming and
inspection get minimal CLI verbs on the existing `voice` CLI (`voice policy …`).

**Rationale.** No committed bridge route carries policy, and inventing an Auralis-owned
file or asking C10 for a route would cross custody. An adapter-local source keeps R107
fully demonstrable at this boundary — the named card test is "voice policy including an
armed override reaching the agent" — and the source hides behind one small module so a
future bridge extension can replace it without touching the transmission path.
Consume-on-transmission is the plain meaning of "one-shot for the next turn": it applies to
the next Auralis-originated turn's instructions, exactly once, even if that turn then falls
back.

**Rejected.** Reading Auralis-owned application files (custody violation, undocumented
surface); a new bridge route (C10's custody); consume-on-acceptance (would let one arming
apply to several turns if submissions keep failing, which is not "one-shot").

**Revisit when.** A `/v1/` policy route is published by Core — the store becomes a cache
of the wire value behind the same render function.

### KTD6 — A wire-bound completion suppresses the legacy local speak path; the legacy path is otherwise untouched

**Decision.** The Stop hook gains one early branch: when the completing `session_id`
resolves to this machine's adapter identity and the bridge currently shows a binding epoch
for that identity, the hook does not spawn the local speak child; instead it reconciles the
turn record (outcome `authored` if the captured turn reached an accepted authored
rendering, `fallback` otherwise) and exits 0. On any bridge doubt — discovery failure,
transport error, no epoch — the legacy 0.2.1 behaviour runs unchanged.

**Rationale.** Auralis owns speech custody; a bound session that also speaks locally would
double-speak every turn. Failing toward the legacy path keeps voice 0.2.1 users whole when
Auralis is absent or broken. The reconciliation half is C3's contribution to R22/R23/R122:
it is the adapter-side detector and durable marker of "completed without an accepted
rendering." It is evidence, not the fallback mechanism — fallback speech and the
`fallback_accepted` mark are Core/C5's through `acceptFallback()`, per "The R22/R23
fallback seam" above; the Stop hook hands nothing to Core and needs no wire route to do
its half.

**Rejected.** Removing the legacy speak path (breaks the shipped standalone voice loop);
suppressing on mere `bridge.json` existence (a stale file would silence a working local
loop; the epoch check is the honest signal).

**Revisit when.** Auralis reaches always-on daily use and the legacy path is retired by an
operator decision.

### KTD7 — PreToolUse capture is observe-only, scoped, and single-turn-retained

**Decision.** The PreToolUse hook records `{tool_name, tool_input, tool_use_id}`
observations into the current turn record only when that record shows an Auralis-originated
turn for this `session_id`. It always exits 0 with no output on every path — it never
emits `permissionDecision` or any hook decision field, so the permission flow is byte-for-
byte unchanged. An allow-list (a stated list in the policy store) selects which tool names
are recorded; empty list means record all. The turn record holds only the current turn and
is replaced at the next turn origin — no accumulating tool-input log exists.

**Rationale.** The card's objective is *capture*, X1 proved the payload shape, and
stop-condition 4 forbids touching permission boundaries — observe-only is the only
compliant posture, and the platform documents that exit 0 with no output leaves the flow
unchanged. Single-turn retention keeps the capture inside the package's ephemeral-state
posture: `tool_input` can contain sensitive content, and a growing log would be a new
privacy surface this slice has no mandate to open.

**Rejected.** Emitting `permissionDecision` (stop condition 4); recording every session's
every tool call (privacy surface, no requirement needs it); a persistent capture journal
(same).

**Revisit when.** The approvals slice (C8) lands a bridge surface that consumes tool-use
data — the capture shape here is its input.

### KTD8 — The MCP server is stdlib-only stdio JSON-RPC with a minimal method set

**Decision.** `mcp_server.py` implements the MCP stdio transport directly: UTF-8
newline-delimited JSON-RPC 2.0 messages; methods `initialize` (echoing the client's
protocol version when supported, else answering with the newest supported version),
`notifications/initialized`, `tools/list`, `tools/call`, `ping`; unknown methods answer
JSON-RPC method-not-found; nothing but protocol frames is ever written to stdout. One tool
is exposed: `submit_spoken_rendering`, input schema `{text: string}` (closed object). Tool
results carry a single text content block whose body is compact JSON with the KTD1
disposition vocabulary; `isError` stays false for adjudicated rejections — the submission
protocol worked and the verdict is data the agent acts on.

**Rationale.** The repository floor forbids third-party dependencies, and the package's
whole discipline is stdlib seams; the MCP subset needed for one tool is small and
testable. One tool keeps the agent surface minimal: origin and expectation arrive by
injection (KTD3), so no status/query tool is needed in V1.

**Rejected.** The official MCP Python SDK or FastMCP (third-party dependency, floor
violation); an HTTP-transport MCP server (more moving parts, no consumer needs it);
additional query tools (surface growth without a requirement).

**Revisit when.** A second consumer needs more of the protocol, or the MCP stdio framing
spec changes.

### KTD9 — Tests stand on independent contract literals; seams are parameters, not new settings

**Decision.** Bridge tests run against a stdlib `http.server` stub speaking the literal
shapes of [`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md) — the same
independent-literals discipline as C10's acceptance stub, with no shared helpers across
the repository boundary. The stub lives in one owned fixture module,
`plugins/voice/tests/bridge_stub.py` (U1). Token fixtures are inert example values (the
secret-free check in `check_repo.py` stays green). The bridge discovery path
(`~/Library/Application Support/Auralis/bridge.json`) is a module constant with a
parameter seam for tests — **no `VOICE_BRIDGE_FILE` override is added**, because the
contract fixes the location and an env override would just be a second way to break
discovery. The two environment values the contract's §5 identity rule mandates
(`HERDR_PANE_ID`, `HERDR_BIN_PATH`) are **read through `settings.py`, the package's sole
environment reader**: its closed `SETTING_NAMES` tuple
([`settings.py:81`](../../plugins/voice/scripts/settings.py)) is extended from eight to
ten stated names, both with no default (absent or empty → the module's named refusal,
which `adapter_identity.py` reports as "register and submit nothing" per §5). The set
stays closed and secret-free; no module outside `settings.py` reads the environment.

**Rationale.** Two ends proving one wire from two independent readings of the same
document is the run's stated bridge-acceptance design; parameter seams follow the
package's hermetic-seams decision (2026-08-25). Routing the contract-mandated identity
names through the settings module preserves the package's one-reader rule *and* the
closed-set rule — the set is extended in its owning module, not bypassed by a second
reader — and the refusal-by-name semantics of `_stated` are exactly the §5 failure
posture.

**Rejected.** Sharing stub or fixture code with `infiquetra/auralis` (the contract
explicitly forbids cross-repository test helpers); a `VOICE_BRIDGE_FILE` setting (opens a
misconfiguration class the contract exists to prevent); `adapter_identity.py` reading
`HERDR_PANE_ID` / `HERDR_BIN_PATH` directly (a second environment reader, violating the
settings module's stated contract).

**Revisit when.** The contract's discovery location changes (it would arrive as a v2).

### KTD10 — Packaging: `mcpServers` as a string path into the client extension; version 0.3.0 at all four sites

**Decision.** `plugins/voice/.claude-plugin/plugin.json` gains
`"mcpServers": "./com.infiquetra.claude/mcp/servers.json"` — a path, not an inline
object — and the server config (command `python3`,
`${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py`) lives in that new file inside the client
extension. The version becomes `0.3.0` at all four sites the packaging test binds
together, and `tests/test_claude_plugin_packaging.py` is extended to assert the
`mcpServers` declaration is a path that resolves into the client extension.

**Rationale.** The repository boundary rule says the packaging manifest carries paths and
no behaviour; the string-path form is documented and verified, so the command line (which
*is* behaviour wiring) stays inside `com.infiquetra.claude/`. Minor version bump: new
backward-compatible capability on a proven package.

**Rejected.** Inline `mcpServers` object in the packaging manifest (a command in a file
the repo rule requires to be metadata-only); a separate new plugin for the adapter (the
card mandates extending the voice package, and a second package would duplicate the core).

**Revisit when.** The Claude CLI changes manifest resolution (same revisit condition as
the 2026-08-25 packaging decision).

### KTD11 — Turn-record mutations are one locked transaction; atomic replace is only the torn-write defense

**Decision.** Four processes mutate one turn record (the UserPromptSubmit hook creates
it, the MCP server appends submissions, the PreToolUse hook appends observations, the
Stop hook settles the outcome). Every mutation goes through **one entrypoint**,
`turn_record.mutate(fn)`, which serializes writers with an exclusive `fcntl.flock` lock
on a sidecar lock file (`<record>.lock` beside the record in the state directory) and
performs the whole read-current → apply → atomic write-replace sequence *inside* the
critical section. Lock acquisition is a non-blocking attempt retried on a monotonic
deadline (budget in the timeout table below); an expired deadline is a named refusal
(`turn_record_busy`), never a blind write. No writer anywhere in the adapter performs its
own read-modify-replace on the record; atomic `os.replace` remains solely the torn-write
defense for readers.

**Rationale.** Atomic replacement makes each write complete but does nothing about two
writers reading the same prior document and each replacing it — the lost-update
interleaving that could erase a named R121 rejection or an accepted disposition and flip
the R122 result. An exclusive advisory lock held across read-apply-write is the smallest
standard-library construct that makes each mutation a transaction; `fcntl.flock` works on
both the macOS target and the Linux CI runner, and a sidecar lock file keeps the record
itself replaceable while locked. This is the same defect family that has bitten this run
twice in Core, which is why the mechanism is specified here rather than left to an
implementer's comment.

**Rejected.** Atomic replace alone with "one writer per field family" (two processes can
still interleave read-modify-replace on the whole file — the exact reviewed defect);
`O_CREAT|O_EXCL` lock files (stale-lock cleanup on crash becomes its own protocol; flock
releases with the process); an SQLite record (heavier machinery than one single-turn JSON
document warrants, and the package's stores are uniformly JSON files).

**Revisit when.** The record outgrows a single turn or gains cross-process readers with
consistency needs beyond one file.

## Timeout budget (normative numbers)

Every deadline in this plan is a number here; units cite this table instead of saying
"short" or "stated". All HTTP calls are loopback. Behaviours on expiry are named; no
expiry may surface as acceptance or as a broken turn.

| Operation | Owner | Budget | On expiry |
|---|---|---:|---|
| HTTP connect (any bridge call) | U1 `bridge_client.py` | 250 ms | Named `transport_error`; fail closed |
| `GET /v1/health`, `GET /v1/current` (overall per call) | U1 | 1,000 ms | Named `transport_error`; caller treats bridge as unavailable |
| `PUT /v1/presence`, `DELETE /v1/presence` (overall) | U1 (server presence thread) | 2,000 ms | Renewal failure → 1 Hz re-discovery per §8; never blocks the tool path |
| `POST /v1/rendering` (overall, per attempt) | U1 | 2,000 ms | Named `transport_error`; lost-response retry rules per §8 (single byte-equivalent retry) |
| Herdr `agent list` subprocess | U1 `adapter_identity.py` | 2,000 ms | Named identity refusal; register and submit nothing (§5) |
| Turn-record lock acquisition (`mutate`) | U2 `turn_record.py` | 500 ms (10 ms retry interval, monotonic clock) | Named `turn_record_busy`; per-writer behaviour below |
| UserPromptSubmit hook (hooks.json `timeout`) | U4 | 5 s (package convention, matches Stop) | Client kills the hook; no injection that turn |
| — internal budget: discovery read + identity + one GET + record write | U4 | ≤ 3,500 ms worst case (sum of rows above) | Any internal expiry → emit nothing, exit 0 |
| PreToolUse hook (hooks.json `timeout`) | U4 | 5 s | Client kills the hook; observation lost, permission flow untouched |
| Stop hook (hooks.json `timeout`, existing) | U4 | 5 s (unchanged) | Client kills the hook |
| — internal budget: one bridge snapshot on the KTD6 branch | U4 | 1,000 ms | Bridge doubt → legacy 0.2.1 path runs |
| Presence renewal cadence | U3 | at/before `renew_after_ms` (5,000 ms) per §6.2 | Missed renewal → re-registration path; lease expiry is Core's to enforce |

Per-writer behaviour on `turn_record_busy`: the UserPromptSubmit hook emits no injection
and exits 0 (an uncaptured turn later reads as `no_current_turn`); the PreToolUse hook
drops the observation and exits 0; the MCP server answers the tool call
`unavailable` / `turn_record_busy` without touching the wire; the Stop hook falls toward
the safe side — while wire-bound it still suppresses local speech (suppression is decided
by the binding epoch, not by the record) and leaves the outcome unsettled rather than
guessing. Deadline behaviour is tested with a stubbed clock at each owning boundary
(U1/U2 scenarios), never with wall-clock sleeps.

## Implementation Units

Waves: U1 and U2 are independent; U3 depends on U1+U2; U4 depends on U1+U2+U3 (its
end-to-end scenario launches U3's real server process); U5 lands last. All unit file
sets are disjoint. Backend is inline for every unit, so execution order is simply
U1 → U2 → U3 → U4 → U5.

### U1. Bridge wire client and adapter identity resolver

One portable-core module per side of the wire question: `bridge_client.py` speaks the
contract, `adapter_identity.py` answers who this adapter is.

**Files:** `plugins/voice/scripts/bridge_client.py` (new),
`plugins/voice/scripts/adapter_identity.py` (new),
`plugins/voice/scripts/settings.py` (edit: extend `SETTING_NAMES` with `HERDR_PANE_ID`
and `HERDR_BIN_PATH`, both no-default, per KTD9),
`plugins/voice/tests/bridge_stub.py` (new: the shared independent-literals bridge stub —
see below),
`plugins/voice/tests/test_bridge_client.py` (new),
`plugins/voice/tests/test_adapter_identity.py` (new),
`plugins/voice/tests/test_settings.py` (edit: the two new stated names' presence, refusal,
and closed-set scenarios).

**Shared stub fixture custody.** `plugins/voice/tests/bridge_stub.py` is the one stub
fixture every bridge-facing suite uses (U1's own suites, U3's server suites, U4's hook
suites, and the U4 end-to-end scenario). It is owned by U1 alone; no other unit edits it.
It is a plain module (no `test_` prefix, so neither `unittest` discovery nor the CI
`pytest` job collects it as a suite), holding the stdlib `http.server` stub that speaks
the contract literals plus its request-capture surface, and is imported by sibling suites
under the package's existing explicit `sys.path.insert` test convention. Wire literals
live in exactly two places: `bridge_client.py` (production) and `bridge_stub.py` (test) —
the two independent readings KTD9 requires.

**Requirements:** wire substrate for R21, R106, R122 — discovery (§2), authentication
(§3), wire rules (§4), identity (§5), the five routes (§6), transport errors and
precedence (§7), identifier/retry/fail-closed semantics (§8) of
[`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md).

**Depends on:** nothing.

**Backend:** inline.

**Design notes.** `bridge_client.py`: strict discovery (exact four keys, exact types,
literal host, port range, full token grammar — exactly 43 characters drawn only from the
base64url alphabet `[A-Za-z0-9_-]`, no `=` padding — file mode `0600`, any deviation reads
"unavailable" — never a default port or token); bearer header on every request; closed
JSON request bodies with `schema: 1`; the numeric deadlines of the timeout budget table on
every call (`http.client` over loopback, monotonic-clock deadline discipline); a total
error mapping of the §7 table; fail-closed on unknown status, unknown error code, or
malformed response; **Core-identifier grammar validation** — `binding_id` and `turn_id`
read from `GET /v1/current` must be opaque lowercase UUID v4 strings per §8, and a
malformed, uppercase, or wrong-version identifier means the snapshot is refused (treated
as bridge-unavailable) and the pair is never captured or carried; retry rules as
first-class behavior — 1 Hz re-discovery until registration, single byte-equivalent retry
after 500 only, never retry 4xx, byte-equivalent-only retry for lost rendering responses.
**Lost-response retry context (the `duplicate_rendering` reconciliation):** when a
rendering response is lost after the request may have reached Core, the client marks the
in-flight submission as a byte-equivalent retry; if that retry answers
`duplicate_rendering`, the contract's §8 sentence ("an earlier acceptance returns
`duplicate_rendering` while that turn remains current") makes the disposition decidable —
the earlier identical submission was accepted — so the client returns **accepted** with
detail `accepted_on_retry`, never a rejection. Outside that retry context,
`duplicate_rendering` relays verbatim as `rejected_by_core` (terminal for the pair per
§6.5 — the result detail states an authored rendering was already accepted, so the agent
is never invited to submit a replacement). `adapter_identity.py`: the §5 rule verbatim —
`HERDR_PANE_ID` and `HERDR_BIN_PATH` resolved **through `settings.py`'s extended stated
set** (KTD9), the executable run with `agent list` under the package's subprocess
discipline (`process.py`) inside its 2,000 ms deadline, envelope check
`result.type == "agent_list"`, exactly-one pane match, all three components non-empty, and
the never-copy-from-`GET /v1/current` rule stated in the module contract. Every failure is
a named refusal; any failure means register and submit nothing.

**Test scenarios** (`plugins/voice/tests/test_bridge_client.py`,
`plugins/voice/tests/test_adapter_identity.py`,
`plugins/voice/tests/test_settings.py`):

- Discovery: a valid file parses; each malformation (missing, partial JSON, wrong type
  per member, extra key, `schema: 2`, empty token, mode `0644`) independently reads
  unavailable, and no default is ever substituted.
- Token grammar (the §2 literal, one fixture per violation): a 42- and a 44-character
  token; a 43-character token containing a non-base64url character (`+`, `/`); a token
  carrying `=` padding — each reads unavailable, and **no presence or rendering request
  follows** (asserted against the stub's request capture).
- Core-identifier grammar (the §8 literal): a `GET /v1/current` snapshot whose
  `binding_id` or `turn_id` is uppercase, not a UUID at all, or a UUID of the wrong
  version — each refuses the snapshot, captures no pair, and no rendering request ever
  carries the malformed value.
- Auth: the header is `Authorization: Bearer <token>` byte-exact; a stub returning 401
  yields a named unauthorized condition and triggers re-discovery, never acceptance.
- Each of the five routes round-trips its documented 200 body against the stub; response
  parsing requires all documented members and ignores unknown ones.
- Transport errors: each §7 row maps to its named condition; an undocumented status and
  an unknown error code both fail closed.
- Deadlines: with a stubbed clock, a call exceeding its timeout-budget row yields the
  named `transport_error` (never acceptance, never a hang); the deadline values asserted
  are the table's numbers.
- Retry: after a stubbed 500 the client performs at most one byte-identical retry and
  only after a health re-check; a 400 is never retried; the rendering retry path resends
  byte-identical bodies with the same identifiers.
- Lost-response reconciliation (the F8 case): the stub accepts a rendering but drops the
  response; the client's single byte-equivalent retry answers `duplicate_rendering`; the
  client returns accepted with detail `accepted_on_retry`. The same
  `duplicate_rendering` reason *outside* retry context relays as `rejected_by_core`.
- Identity: the happy path copies the three components exactly; missing env var, missing
  executable, malformed envelope, zero matches, two matches, and an empty component each
  produce a named refusal.
- Settings: `HERDR_PANE_ID` and `HERDR_BIN_PATH` are stated members of `SETTING_NAMES`;
  absent and empty each produce the module's named refusal (no default); the closed-set
  regression (nothing outside the ten-name tuple is read) still holds.

Each grammar and validation guard above is **mutation-checked once during
implementation**: the guard is deliberately relaxed, the named test is observed failing,
and the guard is restored — recorded in the U5 acceptance note so a permanently green
suite cannot hide a vacuous guard.

**Verification:** `cd plugins/voice && python3 -m unittest discover -s tests -v`;
`python3 scripts/check_repo.py`; `git diff --check`.

### U2. Rendering gate, voice policy store, and turn record

The three small pure state-and-judgment modules everything else composes: R121's gate,
R107's policy source, and the per-turn record that makes R122's path observable.

**Files:** `plugins/voice/scripts/rendering_gate.py` (new),
`plugins/voice/scripts/voice_policy.py` (new),
`plugins/voice/scripts/turn_record.py` (new),
`plugins/voice/scripts/voice_cli.py` (edit: add `policy` verbs),
`plugins/voice/tests/test_rendering_gate.py` (new),
`plugins/voice/tests/test_voice_policy.py` (new),
`plugins/voice/tests/test_turn_record.py` (new).

**Requirements:** R121, R20 (gate: detect and name, never transform); R25, R107 (policy:
store, render to instructions, one-shot arming); R23, R122 substrate (turn record:
submissions, dispositions, outcome marking).

**Depends on:** nothing.

**Backend:** inline.

**Design notes.** `rendering_gate.py` owns the **complete R121 rejected-syntax
contract** — a closed, enumerated class list documented in the module as the boundary's
authority (KTD1). The paired-marker and line-anchor recognizers of
[`text_cleanup.py`](../../plugins/voice/scripts/text_cleanup.py) seed the overlapping
classes, but the cleanup pass's documented scope does not bound the gate: the gate adds
the Markdown forms the cleanup pass never needed. The full class list, with the reason
each class yields:

| Detected class | Reason |
|---|---|
| Fenced code block (``` ``` `` or `~~~`) | `fenced_code_block` |
| Indented code block (a line indented 4+ spaces or a tab, outside a continuation of plain prose) | `markdown_formatting` (class `indented_code_block` in the detail) |
| ATX heading (`#` … `######` + space) | `markdown_formatting` |
| Setext heading (a non-blank line followed by an underline of only `=` or `-`) | `markdown_formatting` |
| Emphasis / strong pairs (`*`, `**`, `_`, `__`, word-edge-guarded) | `markdown_formatting` |
| Inline code span (backticks) | `markdown_formatting` |
| Inline link / image (bracketed text followed immediately by a parenthesized destination, with or without a leading `!`) | `markdown_formatting` |
| Reference-style link (`[text][label]`, `[text][]`) and link-reference definition (`[label]: destination` at line start) | `markdown_formatting` |
| Autolink (`<scheme://…>` or `<name@host>` in angle brackets) | `markdown_formatting` |
| List marker (`-`/`+`/`*`/`1.`/`1)` + space at line start) | `markdown_formatting` |
| Blockquote marker (`>` at line start) | `markdown_formatting` |
| Horizontal rule | `markdown_formatting` |
| Table pipe row | `markdown_formatting` |

Stated non-classes (accepted as plain, each a named negative test): arithmetic asterisks
(`2 * 3`), identifier underscores (`snake_case`), mid-sentence hyphens, comparison angle
brackets (`x < y`), a bare bracketed aside (`[sic]` — without a matching reference
definition it is not a link, and definitions themselves are rejected), a colon-labelled
line (`note: …`), and a bare spoken URL (not an autolink without angle brackets; base
Markdown does not linkify bare URLs). The gate exports a verdict (`plain`, or a named
rejection with detected classes and first offending line) and has no transformation
function at all; the class table above is the module's documented contract and the test
suite's checklist. `voice_policy.py` follows the `binding.py` store pattern:
atomic write-replace, absent-vs-corrupt reported by name; fields are stated preference
instruction lines plus the `brief_next_turn` one-shot; `consume_brief_next_turn()` is
atomic; `render_instructions()` produces the injected text and applies nothing.
`turn_record.py`: one current-turn JSON file in the state directory, replaced at each turn
origin; carries `session_id`, the captured `(binding_id, turn_id)`, origin, submissions
with dispositions and reasons, tool-use observations, and the settled outcome
(`authored` / `fallback`); **all mutations run through the single `mutate(fn)`
entrypoint — the KTD11 flock transaction with the timeout table's 500 ms acquisition
budget — and the module exposes no other write path**. CLI: `voice policy show` and
`voice policy brief-next-turn` verbs on the existing parser in
[`voice_cli.py:156`](../../plugins/voice/scripts/voice_cli.py).

**Test scenarios** (`plugins/voice/tests/test_rendering_gate.py`,
`plugins/voice/tests/test_voice_policy.py`, `plugins/voice/tests/test_turn_record.py`):

- Gate rejects a fenced code block with reason `fenced_code_block`, and Markdown emphasis
  with reason `markdown_formatting`, each naming the detected class and line (the AE26
  core, both named-reason halves the card requires).
- **Every row of the class table has at least one rejecting scenario** — including the
  forms beyond the cleanup pass's scope: a setext heading, a reference-style link, a
  link-reference definition, an autolink, and an indented code block each yield their
  stated reason and class.
- **Every stated non-class has an accepting scenario**: arithmetic asterisks, identifier
  underscores, mid-sentence hyphens, `x < y`, a bare `[sic]`, a colon-labelled line, and
  a bare spoken URL each pass as `plain`.
- A submission containing both a fence and emphasis yields `fenced_code_block` (stated
  precedence).
- The gate exposes no function that returns modified text (R20 asserted structurally: the
  module's public surface is verdicts only); each detector class is mutation-checked once
  during implementation (relaxed → named test fails → restored), recorded in the U5
  acceptance note.
- Policy: arming `brief_next_turn` then consuming it yields the brief instruction exactly
  once; a second consume reports unarmed; corrupt and absent store states are reported by
  name; `render_instructions()` output contains the stated preferences verbatim and
  nothing derived from any response content.
- CLI: the `policy` verbs round-trip arming and showing through `main()`.
- Turn record: origin write replaces the previous turn's record; submissions and
  dispositions append; outcome settles once; a record for a different `session_id` is
  refused by name.
- **Interleaving (the KTD11 proof, deterministic — no sleeps, no luck):** two concurrent
  `mutate` calls from separate threads, each holding its own file descriptor, with an
  event-controlled pause injected inside the first writer's critical section; the second
  writer provably does not enter until the first completes, and the final record contains
  **both** updates (the lost-update case a bare read-modify-replace would produce is the
  failing assertion). A third scenario holds the lock past the 500 ms acquisition budget
  (stubbed clock) and observes the named `turn_record_busy` refusal, never a blind write.

**Verification:** same three commands as U1.

### U3. MCP authored-rendering surface with the presence lifecycle

The adapter's long-lived process: the MCP stdio server exposing `submit_spoken_rendering`,
gating locally, forwarding verbatim, relaying dispositions, and running presence.

**Files:** `plugins/voice/scripts/mcp_server.py` (new),
`plugins/voice/tests/test_mcp_server.py` (new).

**Requirements:** R21, R20, R121 (surface behavior), R122 (submission half).

**Depends on:** U1 (bridge client, identity), U2 (gate, turn record).

**Backend:** inline.

**Design notes.** Protocol per KTD8. Tool flow per submission: read the current turn
record; no captured pair for this session → `unavailable` / `no_current_turn`; gate the
text (KTD1) → `rejected_content` with the named reason, recorded, nothing on the wire;
otherwise `POST /v1/rendering` with the captured pair and byte-identical text →
`accepted` (including the U1 client's `accepted_on_retry` reconciliation for a lost
response answered `duplicate_rendering`) or `rejected_by_core` with the wire reason
relayed verbatim, recorded either way; transport failure → `unavailable` with the named
condition, fail-closed (never reported as accepted). All record writes go through
`turn_record.mutate` (KTD11); the server holds no other write path. Presence thread per
KTD2: discovery at 1 Hz until registered, renewal at the response's `renew_after_ms`,
re-discovery on 401 or connection refusal, best-effort `DELETE` on stdin EOF, and the
thread never writes to stdout.

**Two test layers, per the repository's executable-entrypoint rule** (`AGENTS.md`: a
package entrypoint must be run the way a user runs it — component tests alone have
shipped broken imports before; see `tests/test_client_entrypoints.py`). Fine-grained
scenarios drive the server loop in process over injected byte streams with the U1 stub.
On top of that, one **process-level scenario launches the exact declared argv** —
`python3 <installed-root>/scripts/mcp_server.py`, the byte-for-byte expansion of the
`servers.json` declaration (`${CLAUDE_PLUGIN_ROOT}` → the installed root) — as a real
subprocess from an installed-root-shaped directory (the `plugins/voice` tree copied to a
temporary directory, exercising imports as installed), with real stdin/stdout pipes.
Environment for the subprocess uses only existing stated seams: `VOICE_STATE_DIR` and the
two KTD9 identity names point at test fixtures, and `HOME` points at a temporary home
whose `Library/Application Support/Auralis/bridge.json` names the U1 stub's live port —
no new setting and no code-level seam is needed. U5's packaging test pins the
`servers.json` declaration to the same command/args literals this scenario launches, so
the declaration and the proof cannot drift apart (independent-literals discipline, KTD9).

**Test scenarios** (`plugins/voice/tests/test_mcp_server.py`):

- `initialize` → `tools/list` exposes exactly `submit_spoken_rendering` with the closed
  input schema; unknown methods get JSON-RPC method-not-found; stdout carries only
  protocol frames.
- AE26 end-to-end at the surface: a submission containing Markdown emphasis and a fenced
  code block is rejected with a named reason, nothing is forwarded, no cleaned variant
  exists anywhere in adapter state; a plain-text resubmission on the same turn is
  forwarded and accepted by the stub — proving reject-then-accept with no repair.
- The forwarded body is byte-identical to the submitted text (R20) and carries the
  prompt-time captured pair, not the stub's current turn (KTD4: with the stub's current
  turn advanced, the submission still targets the captured pair and the stub's
  `turn_not_current` is relayed verbatim as `rejected_by_core`).
- Each wire rejection reason in the §6.5 vocabulary relays verbatim; an unknown
  disposition or malformed response fails closed as `unavailable`, never `accepted`.
- With no turn record, and with a record for another session, the tool answers
  `unavailable` / `no_current_turn` without touching the wire.
- Presence: against the stub, the server registers with the resolved identity, renews on
  cadence (stubbed clock), re-registers after a token rotation (401 → re-discovery), and
  sends `DELETE` on shutdown; identity-resolution failure means no registration and the
  tool reports `unavailable` / `not_bound`.
- Lost-response reconciliation at the surface (the F8 case end to end at this layer): the
  stub accepts the first `POST /v1/rendering` but drops the response; the single
  byte-equivalent retry answers `duplicate_rendering`; the tool result is **accepted**
  with detail `accepted_on_retry`, the turn record's disposition is an authored
  acceptance (so KTD6 reconciliation must read `authored`, never `fallback`), and the
  result invites no replacement submission.
- **Executable entrypoint (the declared process, as Claude runs it):** launch the exact
  declared argv from the installed-root-shaped directory over real process pipes and
  complete, in order: MCP `initialize`, `tools/list` (exactly `submit_spoken_rendering`),
  a rejected `tools/call` (Markdown → named `rejected_content` reason), and an accepted
  `tools/call` (plain text → forwarded to the stub, `accepted` relayed). This scenario
  fails on a broken import, a wrong interpreter floor, a framing error, or stray stdout —
  none of which the in-process layer can catch.
- Every submission and disposition appears in the turn record (the R122 evidence trail),
  written through `turn_record.mutate` only.

**Verification:** same three commands as U1.

### U4. Claude hooks: turn origin and policy injection, PreToolUse capture, completion reconciliation

The client-extension half: two new hooks, the Stop-hook extension, and the hook wiring.

**Files:** `plugins/voice/com.infiquetra.claude/hooks/user_prompt_submit_hook.py` (new),
`plugins/voice/com.infiquetra.claude/hooks/pre_tool_use_hook.py` (new),
`plugins/voice/com.infiquetra.claude/hooks/stop_hook.py` (edit),
`plugins/voice/com.infiquetra.claude/hooks/hooks.json` (edit: add `UserPromptSubmit` and
`PreToolUse` entries, `timeout: 5` each, matching the existing Stop entry and the timeout
budget table),
`plugins/voice/tests/test_user_prompt_submit_hook.py` (new),
`plugins/voice/tests/test_pre_tool_use_hook.py` (new),
`plugins/voice/tests/test_stop_hook.py` (edit: bridged-branch scenarios),
`plugins/voice/tests/test_r122_end_to_end.py` (new: the cross-boundary
rejection-to-fallback proof below).

**Requirements:** R106, R107 (transmission), R22/R23 (adapter share per the fallback
seam), R122 (completion half and the end-to-end path), PreToolUse capture per X1.

**Depends on:** U1, U2, U3 (the end-to-end scenario launches U3's real server process).

**Backend:** inline.

**Design notes.** All three hooks keep the package's iron hook rule: every path exits 0,
a hook never breaks a turn. `user_prompt_submit_hook.py` implements KTD3/KTD4: resolve,
query, match; on an Auralis-originated turn write the captured pair to the turn record and
emit `hookSpecificOutput.additionalContext` containing the origin statement, the
rendering expectation, the submission-tool pointer, the plain-spoken-text rule, and the
rendered policy instructions with the one-shot consumed on transmission; on a bound but
non-originated turn emit the explicit negative; on any unavailable state emit nothing.
`pre_tool_use_hook.py` implements KTD7 (observe-only, scoped, allow-list filtered, no
output ever). `stop_hook.py` gains the KTD6 branch ahead of the legacy path, using only
cheap local reads plus one bridge snapshot (1,000 ms deadline; on expiry, bridge doubt →
legacy path), preserving the detach discipline. All three hooks mutate the turn record
only through `turn_record.mutate` (KTD11), with the per-writer `turn_record_busy`
behaviour of the timeout budget table. Hook internal deadlines are the timeout table's
rows; every expiry path still exits 0.

**Test scenarios** (`plugins/voice/tests/test_user_prompt_submit_hook.py`,
`plugins/voice/tests/test_pre_tool_use_hook.py`,
`plugins/voice/tests/test_stop_hook.py`,
`plugins/voice/tests/test_r122_end_to_end.py`):

- **R122 end to end, at the production boundaries** (`test_r122_end_to_end.py` — the
  scenario exists because a helper-level assertion cannot prove the path; it must fail if
  the submission record schema, the session/identifier join, the completion handoff, or
  the fallback marker drifts). Every boundary is the real one: the U1 stub bridge shows
  an open turn bound to the resolved identity; the **real `user_prompt_submit_hook.py`**
  runs as a subprocess with a real stdin payload and writes the captured pair into the
  turn record; the **real MCP server process** (U3's declared argv, real pipes) receives
  `tools/call submit_spoken_rendering` with Markdown and answers the named
  `rejected_content` reason — the stub's request capture proves **nothing was forwarded**
  to `POST /v1/rendering`; **no replacement is submitted**; the **real `stop_hook.py`**
  then runs as a subprocess with a Stop payload for the same `session_id`, and the
  assertion reads the turn record through the production module: the same turn —
  identified by the captured `(binding_id, turn_id)` — now carries outcome `fallback`,
  the earlier named rejection still present, no speak child spawned. The joined artifact
  was written by the production processes end to end, not assembled by the test.

- The card-named origin test: with the stub showing an open turn bound to this session,
  the injected context states the turn originated through Auralis and a rendering is
  expected; with the stub bound but no open turn, the context states the opposite; with
  no bridge, no binding, an identity mismatch, or a resolution failure, the hook emits
  nothing — origin signalling present only under a binding, explicit both ways there.
- The card-named policy test: stated preferences and an armed Brief Next Turn override
  appear verbatim in the injected instructions of the next Auralis-originated turn; the
  arming is consumed exactly once; the following turn's instructions omit the brief
  directive; a non-originated turn transmits no policy and consumes nothing.
- The captured pair lands in the turn record at origin (KTD4's source of truth).
- PreToolUse: on an Auralis-originated turn the record gains
  `{tool_name, tool_input, tool_use_id}` observations; allow-list filtering records only
  named tools when the list is non-empty; on non-originated turns and unbound sessions
  nothing is recorded; the hook writes no stdout on any path and exits 0 on malformed
  input (permission flow provably untouched at the hook contract level).
- Stop hook: wire-bound with the captured turn unaccepted → no speak spawn, outcome
  `fallback` recorded (R122's terminal half; with a prior gate rejection in the record,
  the record now shows the full named-rejection-then-fallback path); wire-bound with an
  accepted rendering → outcome `authored`, no speak spawn; unbound or bridge-unavailable
  → the existing 0.2.1 spawn behaviour, asserted by the existing suite continuing to
  pass unmodified in those scenarios.

**Verification:** same three commands as U1, plus one stated manual check at acceptance
time (recorded, and actually performed, per the card): in a live bound session, the
injected context is visible to the agent and no double-speech occurs on an authored turn.

### U5. Packaging, versions, docs, and journal

Ship it: the MCP declaration, the four-site version bump, README, packaging-test
extension, journal capture, and the slice's acceptance evidence note.

**Files:** `plugins/voice/plugin.json` (edit: version),
`plugins/voice/.claude-plugin/plugin.json` (edit: version, `mcpServers` path),
`plugins/voice/com.infiquetra.claude/plugin.json` (edit: version, description),
`plugins/voice/com.infiquetra.claude/mcp/servers.json` (new),
`.claude-plugin/marketplace.json` (edit: version, description),
`plugins/voice/README.md` (edit: adapter section),
`tests/test_claude_plugin_packaging.py` (edit: `mcpServers` path assertions),
`docs/evidence/voice/auralis-c3-acceptance.md` (new),
`docs/engineering-journal/DECISIONS.md` (edit),
`docs/engineering-journal/LEARNINGS.md` (edit, if the build surfaced a non-obvious
mechanism worth a dated entry).

**Requirements:** distribution rules (the packaging boundary and its enforcement),
version agreement, AE26 traceability, and the R-to-test trace table the card's closeout
needs.

**Depends on:** U3, U4.

**Backend:** inline.

**Design notes.** Version `0.3.0` per KTD10 at all four sites. The new
`servers.json` declares the stdio server with `${CLAUDE_PLUGIN_ROOT}`-anchored command;
the packaging test grows assertions that the declaration is a string path resolving into
`com.infiquetra.claude/`, that the declared script exists, and that the declared
command/args are byte-for-byte the literals U3's executable-entrypoint scenario launches
(the declaration and its proof cannot drift apart). The new acceptance note is
this slice's own ledger (separate file from the 0.2.x ledger to keep the two R-ID
namespaces apart): the AE26 test evidence, the R-to-test trace for all nine requirements,
the performed manual check from U4, AE34 joint-readiness status, the wire-pin provenance
(source revision `695cd0ecfddf44e0d6e3386da318bd5fde4a1926` and snapshot SHA-256) with the
not-yet-merged flag restated, the R22/R23 cross-slice dependency on C5 restated for the
AE36 closeout, and the record of the guard-mutation checks U1 and U2 performed (each
guard: relaxed, named failing test observed, restored).

**Test expectation:** the extended `tests/test_claude_plugin_packaging.py` scenarios
(version agreement at four sites including the new value; `mcpServers` is a path into the
client extension; every declared component path exists). No other new suite — the unit is
packaging and documentation; behavior is covered by U1–U4.

**Verification:** full card set — `cd plugins/voice && python3 -m unittest discover -s
tests -v`, `python3 scripts/check_repo.py`, repo-root
`python3 -m unittest discover -s tests -v`, `git diff --check`; plus
`claude plugin validate plugins/voice` as the installability probe the packaging decision
used.

## Scope Boundaries

Out of scope (true non-goals, from the card and the parent):

- Any change in `infiquetra/auralis` — the Core bridge endpoint is C10's. No new
  `/v1/` route is proposed anywhere in this plan.
- Any speech provider, audio capture, playback, or user interface. Fallback *speech* and
  its audible marking are Core/C5 (AE36); this adapter contributes detection and durable
  marking only.
- Cleaning, rewriting, or reformatting any authored rendering (R121 — the gate rejects).
- Any content decision from preferences (R25 — transmit only).
- Any permission decision from the PreToolUse hook (stop condition 4; KTD7).
- Sourcing the fallback's written-response text to Core, initiating fallback speech, or
  marking the turn `fallback_accepted`. Those are Core/C5's through the in-process
  `acceptFallback()` API (contract §9) — see "The R22/R23 fallback seam", which names the
  cross-slice dependency and where it is proven (AE36). No committed wire route carries
  the written response, and this plan neither implements nor invents one.
- Board writes, PR merge, issue closure — coordinator-owned per the card.
- The open voice findings F6 (#43) and F7 (#44) — tracked separately, untouched here.

Deferred to follow-up work (real work, later slices or extensions):

- Policy over the wire (KTD5's revisit): adapter store becomes a cache of a Core-published
  policy when such a route exists.
- Approvals consumption of the PreToolUse capture (C8's future bridge surface; KTD7's
  revisit).
- Retiring the legacy local speak path once Auralis is the daily driver (KTD6's revisit).

## Risks and pre-mortem

The most likely failure first: **the pinned contract moves before it merges.** The bridge
contract this adapter builds against is accepted at review but unmerged in `auralis`; if
C10 amends a literal (a reason string, a member name), the adapter would pass its own
tests and fail the joint acceptance. Contained by the tracked byte-pinned snapshot (a
divergence is detectable by hash, and a refresh is one extract-and-record step per the
wire-authority section) and by centralizing every literal in `bridge_client.py` plus the
one stub fixture `bridge_stub.py` (a contract diff is a bounded re-touch), and surfaced
honestly in the plan, the evidence note, and AE34.

- **Harness-behavior assumptions.** Context injection visibility and MCP server lifetime
  are platform behaviors verified against current documentation, not testable hermetically.
  Contained by U4's stated manual check in a live session, which the card requires to be
  performed, not merely stated.
- **Double-speech regression.** If the KTD6 suppression misfires, a bound turn speaks
  twice (Auralis and legacy path). Contained by both-ways tests in
  `test_stop_hook.py` and the U4 manual check.
- **False-positive plain-text rejections.** Over-eager detectors would reject honest
  spoken prose (an asterisk in "2 * 3", an underscore in a module name). Contained by
  reusing the 0.2.1-proven paired-marker recognizers and by explicit plain-prose
  acceptance scenarios in `test_rendering_gate.py`.
- **State races between hook processes and the MCP server.** Contained by KTD11: every
  turn-record mutation is a locked read-apply-write transaction through
  `turn_record.mutate`, proven by deterministic interleaving tests; atomic write-replace
  remains only the torn-write defense for readers (a torn read reads as absent, a named
  unavailable state). Field-family conventions (origin by the prompt hook, submissions by
  the server, outcome by the Stop hook) still describe who writes what, but the lock —
  not the convention — is what prevents lost updates.
- **Per-prompt latency.** The prompt hook adds one `bridge.json` read, at most one Herdr
  subprocess call, and one loopback GET, bounded by the timeout budget table (worst case
  ≤ 3,500 ms inside the 5 s hook timeout), with the cheap no-bridge-file exit first — a
  session with no Auralis pays one `stat()`.

## Acceptance mapping

| Acceptance | Where it lands |
|---|---|
| AE26 — Markdown rejected, not cleaned; plain resubmission accepted (covers R121, R20) | Runnable at this boundary: `test_rendering_gate.py` + the `test_mcp_server.py` AE26 scenario (in-process and at the declared executable), plus the R122 end-to-end proof in `test_r122_end_to_end.py`; evidence recorded in `docs/evidence/voice/auralis-c3-acceptance.md` (U5) |
| AE34 — joint bridge acceptance with C10 | Readiness from this side: U1/U3 green against the independent-literals stub; the joint run itself is coordinator-scheduled across repositories |
| AE19, AE23, AE35, AE36 — joint with C5/C10/C1 | Out of this slice's hands; the adapter contributions they consume (presence, origin, submission, fallback-outcome recording) are the tested surfaces above. AE36 in particular is where the named R22/R23 cross-slice dependency on C5's `acceptFallback()` path is proven end to end |

## Verification

```bash
cd plugins/voice && python3 -m unittest discover -s tests -v
cd ../.. && python3 scripts/check_repo.py
python3 -m unittest discover -s tests -v
git diff --check
```

## Unattended decisions log

Decisions taken without an operator in the loop, per the run's operating rule, each from a
known set with the most defensible option:

- **Backend: inline** — directed by the orchestrator for this run; recorded in the
  frontmatter. The saga recommender's suggestion (`team-execution`) is recorded on the
  saga tick as the recommendation alongside the directed choice.
- **Destination: `pr`** — the card's Done state requires a merged PR with the coordinator
  merging and closing; a worker never merges its own PR, so the saga destination is
  open-a-PR.
- **Board transitions: skipped** — the plan skill's phase would move the card to
  Shaping/Ready, but this card states the coordinator is the only board writer
  ("Never: … write the Operations board"). The card's custody rule wins.
- **Plan filename as given** — `docs/plans/2026-08-27-auralis-c3-adapter.md` exactly as
  the card directed, without the `-plan` suffix convention; review tooling recognizes the
  document by its section markers, not its name.
- **`origin:` frontmatter is the cross-repository requirements-document URL** — the
  upstream WHAT lives in `infiquetra/auralis`, so no repo-relative path exists; the URL
  is an immutable commit permalink at `b49de1ba4d39cbd8a1e582d72bddca85bf528f8a`, never a
  moving branch.
- **R22/R23 read as slice-owned requirements discharged across the C3/C5 seam** — the
  adapter share (submit only gated text, never fabricate, record the completion durably)
  is planned here; fallback initiation, content, speech, and the `fallback_accepted` mark
  are Core/C5's through `acceptFallback()`, proven jointly at AE36 (see "The R22/R23
  fallback seam"). The alternative reading — that C3 must make fallback audible — would
  require owning speech, which the card forbids.

Decisions taken during the 2026-08-27 plan repair (doc-review findings F1–F12), same
operating rule:

- **F1 pin mechanism: a tracked byte-identical snapshot** of the contract at the
  accepted-review revision, hash-verifiable against `infiquetra/auralis`
  (`695cd0e…`, SHA-256 recorded in the wire-authority section). Chosen over an
  external permalink alone because a clean checkout of *this* repository — including the
  hosted `Validate` CI — must resolve the plan's links and read the contract without
  access to another repository's unmerged branch; chosen over deleting the reference
  because the plan must stay traceable to a specific revision of a specific document.
- **F4 transaction mechanism: `fcntl.flock` on a sidecar lock file** (KTD11). Chosen
  over `O_CREAT|O_EXCL` lock files (crash-stale locks need their own cleanup protocol;
  flock releases with the process) and over SQLite (disproportionate to one single-turn
  JSON document).
- **F7 reconciliation: extend the closed `SETTING_NAMES` set inside `settings.py`**
  rather than adding a second environment reader — the sole-reader rule is the package's
  load-bearing invariant; the closed set is extended in its owning module (KTD9).
- **F5 classing: indented code blocks reject under `markdown_formatting`** with class
  `indented_code_block` named in the detail — the two-reason vocabulary is settled by
  KTD1/AE26, and `fenced_code_block` stays literally about fences.
- **F8 reconciliation source: the retry context plus the contract's §8 sentence**, not an
  extra `GET /v1/current` corroboration read — §8 makes `duplicate_rendering` on a
  byte-equivalent retry decisively mean the earlier acceptance, and an extra wire read
  would add failure modes without adding information.

## Doc-review disposition (2026-08-27)

Where each finding of
[`2026-08-27-auralis-c3-adapter-plan-doc-review.md`](../reviews/2026-08-27-auralis-c3-adapter-plan-doc-review.md)
was repaired in this document.

| Finding | Repair |
|---|---|
| F1 (wire pin not committed) | The snapshot `docs/bridge-v1-from-c10.md` is now a **tracked** file, byte-identical (SHA-256-verified) to `docs/bridge/bridge-v1.md` in `infiquetra/auralis` at accepted revision `695cd0e…`; the wire-authority section states the provenance, digest, and refresh procedure. Clean checkouts and CI resolve every link |
| F2 (no R22/R23 path) | New section "The R22/R23 fallback seam": C3 owns the requirements, C5's in-process `acceptFallback()` (contract §9) is the mechanism, responsibilities on each side are enumerated, and the cross-slice dependency on C5 is named and routed to AE36. R22/R23 table rows, KTD6, and scope boundaries rewritten to match |
| F3 (R122 proved only via fixtures) | New `plugins/voice/tests/test_r122_end_to_end.py` (U4, now depending on U3): real prompt hook, real MCP server process at the declared argv, real Stop hook, one production-written turn record asserted end to end |
| F4 (lost updates on the turn record) | New KTD11: every mutation is a locked read-apply-write transaction through `turn_record.mutate` (`fcntl.flock`, sidecar lock, 500 ms budget, named `turn_record_busy` refusal), with deterministic interleaving tests; atomic replace demoted to torn-write defense only |
| F5 (incomplete Markdown detector) | The gate owns a complete, closed rejected-syntax contract (class table in U2) including setext headings, reference links and definitions, autolinks, and indented code; stated non-classes get named negative tests; `text_cleanup.py` is a seed, not a bound |
| F6 (MCP server never run as declared) | U3 gains the executable-entrypoint scenario: the exact declared argv launched from an installed-root-shaped directory over real pipes through initialize / tools list / rejected call / accepted call; U5's packaging test pins `servers.json` to the same literals |
| F7 (identity reads outside `settings.py`) | `SETTING_NAMES` extended to ten names inside `settings.py` (sole reader preserved); `settings.py` and `test_settings.py` assigned to U1; KTD9 rewritten |
| F8 (`duplicate_rendering` after lost acceptance) | U1 defines the retry-context reconciliation (`accepted_on_retry`, never fallback, never a replacement invitation), grounded in §8; scenarios at both the client (U1) and the tool surface (U3) |
| F9 (stub with no owner) | `plugins/voice/tests/bridge_stub.py` named, owned by U1 alone, import contract stated |
| F10 (adjective timeouts) | Normative "Timeout budget" table: every HTTP, subprocess, lock, and hook deadline is a number with a named on-expiry behaviour; hooks.json entries state `timeout: 5`; clock/deadline scenarios assigned |
| F11 (token/identifier grammar untested) | U1 scenarios for base64url alphabet, padding, and length violations and for uppercase / non-UUID / wrong-version Core identifiers, each asserting no request follows; every guard mutation-checked once and recorded in the U5 acceptance note |
| F12 (moving-branch requirement links) | Frontmatter `origin:`, the namespace note, and the unattended-decisions log all use the immutable commit permalink at `b49de1ba4d39cbd8a1e582d72bddca85bf528f8a` |
