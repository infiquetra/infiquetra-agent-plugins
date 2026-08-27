---
title: Auralis C3 Claude adapter implementation plan
type: feat
status: active
date: 2026-08-27
origin: https://github.com/infiquetra/auralis/blob/main/docs/brainstorms/2026-08-26-auralis-v1-requirements.md
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
[`2026-08-26-auralis-v1-requirements.md`](https://github.com/infiquetra/auralis/blob/main/docs/brainstorms/2026-08-26-auralis-v1-requirements.md)
pinned at `b49de1b`. The voice package's own earlier plan and acceptance ledger use a
*different* R1–R33 numbering from the voice 0.2.x run; the two namespaces do not overlap in
meaning, and this plan never uses the voice-run numbering.

## Wire authority — and the one honest flag on it

The normative wire contract is **Auralis Bridge Contract v1**, authored by C10, whose Code
Review is accepted. A verbatim working copy is committed in this repository at
[`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md); it defines discovery,
authentication, the five routes, request/response bodies, transport errors, processing
precedence, the adjudication order and rejection vocabulary, identifier semantics, retry
rules, and extension rules, and it names C3 as its consumer.

**Flag:** that contract currently lives on the `auralis` run branch and has **not yet
merged to `auralis` main**. This adapter's wire assumptions are therefore pinned to the
committed document copy above, not to a released artifact. Mitigations: every wire literal
is centralized in one module (U1) and one stub fixture, so a contract change before merge
is a bounded re-touch; the joint acceptance AE34 re-validates the wire against the real
Core before the run closes.

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
  ([`text_cleanup.py:27`](../../plugins/voice/scripts/text_cleanup.py)). The gate reuses
  the *recognizer* class definitions and never the transformation (R121 forbids repair).
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
| R22 | A turn completed without an authored rendering falls back to the cleaned full written response rather than silence | Adapter half: completion capture detects "turn completed while still open" and records the fallback outcome; fallback speech itself is Core/C5 (joint AE36) | `plugins/voice/tests/test_stop_hook.py`; joint AE36 |
| R23 | A fallback turn is visibly marked as a fallback, distinguishable from an authored response | Adapter half: the turn record marks outcome `fallback` distinctly from `authored`; the audible/visible marking is Core-side (`fallback_accepted` turn state) | `plugins/voice/tests/test_stop_hook.py`, `plugins/voice/tests/test_turn_record.py` |
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
wire-bound the 0.2.1 behaviour is byte-for-byte unchanged.

## Key Technical Decisions

### KTD1 — R121 enforcement lives in the adapter surface, with a three-class result vocabulary

**Decision.** The plain-spoken-text rule is enforced in the adapter's MCP surface, before
the wire. The tool result vocabulary has three disjoint classes: `rejected_content` with
adapter-owned reasons (`fenced_code_block`, `markdown_formatting`), `rejected_by_core`
relaying the wire's adjudication vocabulary verbatim (`no_binding` … `empty_rendering`),
and `unavailable` with a named operational condition (`bridge_unavailable`, `not_bound`,
`no_current_turn`, `transport_error`). Precedence for content reasons: any fence yields
`fenced_code_block`; otherwise any other detected class yields `markdown_formatting`, with
the detected classes and first offending line named in the detail.

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
rendering."

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
the repository boundary. Token fixtures are inert example values (the secret-free check in
`check_repo.py` stays green). The bridge discovery path
(`~/Library/Application Support/Auralis/bridge.json`) is a module constant with a
parameter seam for tests; **no new environment settings are added** — the closed
`SETTING_NAMES` set in [`settings.py:81`](../../plugins/voice/scripts/settings.py) is
untouched, because the contract fixes the location and an env override would just be a
second way to break discovery.

**Rationale.** Two ends proving one wire from two independent readings of the same
document is the run's stated bridge-acceptance design; parameter seams follow the
package's hermetic-seams decision (2026-08-25) and keep the settings surface closed.

**Rejected.** Sharing stub or fixture code with `infiquetra/auralis` (the contract
explicitly forbids cross-repository test helpers); a `VOICE_BRIDGE_FILE` setting (opens a
misconfiguration class the contract exists to prevent).

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

## Implementation Units

Waves: U1 and U2 are independent; U3 and U4 both depend on U1+U2 and touch disjoint
files; U5 lands last. Backend is inline for every unit, so execution order is simply
U1 → U2 → U3 → U4 → U5. No two units edit the same file.

### U1. Bridge wire client and adapter identity resolver

One portable-core module per side of the wire question: `bridge_client.py` speaks the
contract, `adapter_identity.py` answers who this adapter is.

**Files:** `plugins/voice/scripts/bridge_client.py` (new),
`plugins/voice/scripts/adapter_identity.py` (new),
`plugins/voice/tests/test_bridge_client.py` (new),
`plugins/voice/tests/test_adapter_identity.py` (new).

**Requirements:** wire substrate for R21, R106, R122 — discovery (§2), authentication
(§3), wire rules (§4), identity (§5), the five routes (§6), transport errors and
precedence (§7), identifier/retry/fail-closed semantics (§8) of
[`docs/bridge-v1-from-c10.md`](../bridge-v1-from-c10.md).

**Depends on:** nothing.

**Backend:** inline.

**Design notes.** `bridge_client.py`: strict discovery (exact four keys, exact types,
literal host, port range, 43-char token shape, file mode `0600`, any deviation reads
"unavailable" — never a default port or token); bearer header on every request; closed
JSON request bodies with `schema: 1`; stated short timeouts on every call (`http.client`
over loopback, deadline discipline per the package convention); a total error mapping of
the §7 table; fail-closed on unknown status, unknown error code, or malformed response;
retry rules as first-class behavior — 1 Hz re-discovery until registration, single
byte-equivalent retry after 500 only, never retry 4xx, byte-equivalent-only retry for lost
rendering responses. `adapter_identity.py`: the §5 rule verbatim — `HERDR_PANE_ID` from
the environment, `HERDR_BIN_PATH` executed with `agent list` under the package's
subprocess discipline (`process.py`), envelope check `result.type == "agent_list"`,
exactly-one pane match, all three components non-empty, and the never-copy-from-
`GET /v1/current` rule stated in the module contract. Every failure is a named refusal;
any failure means register and submit nothing.

**Test scenarios** (`plugins/voice/tests/test_bridge_client.py`,
`plugins/voice/tests/test_adapter_identity.py`):

- Discovery: a valid file parses; each malformation (missing, partial JSON, wrong type
  per member, extra key, `schema: 2`, empty token, mode `0644`) independently reads
  unavailable, and no default is ever substituted.
- Auth: the header is `Authorization: Bearer <token>` byte-exact; a stub returning 401
  yields a named unauthorized condition and triggers re-discovery, never acceptance.
- Each of the five routes round-trips its documented 200 body against the stub; response
  parsing requires all documented members and ignores unknown ones.
- Transport errors: each §7 row maps to its named condition; an undocumented status and
  an unknown error code both fail closed.
- Retry: after a stubbed 500 the client performs at most one byte-identical retry and
  only after a health re-check; a 400 is never retried; the rendering retry path resends
  byte-identical bodies with the same identifiers.
- Identity: the happy path copies the three components exactly; missing env var, missing
  executable, malformed envelope, zero matches, two matches, and an empty component each
  produce a named refusal.

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

**Design notes.** `rendering_gate.py` reuses the recognizer regex classes of
[`text_cleanup.py`](../../plugins/voice/scripts/text_cleanup.py) (fences, ATX headings,
emphasis/strong pairs, inline code, links/images, list markers, blockquotes, horizontal
rules, table pipes) as *detectors* with the KTD1 reason precedence; it exports a verdict
(`plain`, or a named rejection with detected classes and first offending line) and has no
transformation function at all. `voice_policy.py` follows the `binding.py` store pattern:
atomic write-replace, absent-vs-corrupt reported by name; fields are stated preference
instruction lines plus the `brief_next_turn` one-shot; `consume_brief_next_turn()` is
atomic; `render_instructions()` produces the injected text and applies nothing.
`turn_record.py`: one current-turn JSON file in the state directory, replaced at each turn
origin; carries `session_id`, the captured `(binding_id, turn_id)`, origin, submissions
with dispositions and reasons, tool-use observations, and the settled outcome
(`authored` / `fallback`). CLI: `voice policy show` and
`voice policy brief-next-turn` verbs on the existing parser in
[`voice_cli.py:156`](../../plugins/voice/scripts/voice_cli.py).

**Test scenarios** (`plugins/voice/tests/test_rendering_gate.py`,
`plugins/voice/tests/test_voice_policy.py`, `plugins/voice/tests/test_turn_record.py`):

- Gate rejects a fenced code block with reason `fenced_code_block`, and Markdown emphasis
  with reason `markdown_formatting`, each naming the detected class and line (the AE26
  core, both named-reason halves the card requires).
- A submission containing both a fence and emphasis yields `fenced_code_block` (stated
  precedence).
- Plain spoken text — including text with underscores in identifiers, arithmetic
  asterisks avoided by the paired-marker rules, and ordinary hyphens mid-sentence — passes
  as `plain`; the gate exposes no function that returns modified text (R20 asserted
  structurally: the module's public surface is verdicts only).
- Policy: arming `brief_next_turn` then consuming it yields the brief instruction exactly
  once; a second consume reports unarmed; corrupt and absent store states are reported by
  name; `render_instructions()` output contains the stated preferences verbatim and
  nothing derived from any response content.
- CLI: the `policy` verbs round-trip arming and showing through `main()`.
- Turn record: origin write replaces the previous turn's record; submissions and
  dispositions append; outcome settles once; a record for a different `session_id` is
  refused by name.

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
`accepted` or `rejected_by_core` with the wire reason relayed verbatim, recorded either
way; transport failure → `unavailable` with the named condition, fail-closed (never
reported as accepted). Presence thread per KTD2: discovery at 1 Hz until registered,
renewal at the response's `renew_after_ms`, re-discovery on 401 or connection refusal,
best-effort `DELETE` on stdin EOF, and the thread never writes to stdout. In-process
tests drive the server loop over injected byte streams; the bridge side is the U1 stub.

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
- Every submission and disposition appears in the turn record (the R122 evidence trail).

**Verification:** same three commands as U1.

### U4. Claude hooks: turn origin and policy injection, PreToolUse capture, completion reconciliation

The client-extension half: two new hooks, the Stop-hook extension, and the hook wiring.

**Files:** `plugins/voice/com.infiquetra.claude/hooks/user_prompt_submit_hook.py` (new),
`plugins/voice/com.infiquetra.claude/hooks/pre_tool_use_hook.py` (new),
`plugins/voice/com.infiquetra.claude/hooks/stop_hook.py` (edit),
`plugins/voice/com.infiquetra.claude/hooks/hooks.json` (edit: add `UserPromptSubmit` and
`PreToolUse` entries with stated timeouts),
`plugins/voice/tests/test_user_prompt_submit_hook.py` (new),
`plugins/voice/tests/test_pre_tool_use_hook.py` (new),
`plugins/voice/tests/test_stop_hook.py` (edit: bridged-branch scenarios).

**Requirements:** R106, R107 (transmission), R22/R23 (adapter half), R122 (completion
half), PreToolUse capture per X1.

**Depends on:** U1, U2.

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
cheap local reads plus one bridge snapshot, preserving the detach discipline.

**Test scenarios** (`plugins/voice/tests/test_user_prompt_submit_hook.py`,
`plugins/voice/tests/test_pre_tool_use_hook.py`,
`plugins/voice/tests/test_stop_hook.py`):

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
`com.infiquetra.claude/` and that the declared script exists. The new acceptance note is
this slice's own ledger (separate file from the 0.2.x ledger to keep the two R-ID
namespaces apart): the AE26 test evidence, the R-to-test trace for all nine requirements,
the performed manual check from U4, AE34 joint-readiness status, and the wire-pin flag
from this plan restated.

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
- Sourcing the fallback's written-response text to Core. No committed route carries it;
  how Core obtains the text it speaks on fallback is Core-side design inside C10/C5's
  custody, and this plan neither implements nor invents it.
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
document this adapter builds against is accepted at review but unmerged in `auralis`; if
C10 amends a literal (a reason string, a member name), the adapter would pass its own
tests and fail the joint acceptance. Contained by centralizing every literal in
`bridge_client.py` plus one stub fixture (a contract diff is a one-module re-touch), and
surfaced honestly in the plan, the evidence note, and AE34.

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
- **State races between hook processes and the MCP server.** All shared state uses the
  package's atomic write-replace pattern; records are single-turn and single-writer per
  field family (origin by the prompt hook, submissions by the server, outcome by the Stop
  hook). A torn read reads as absent, which every consumer treats as a named unavailable
  state.
- **Per-prompt latency.** The prompt hook adds one `bridge.json` read, at most one Herdr
  subprocess call, and one loopback GET, all deadline-bounded, with the cheap
  no-bridge-file exit first — a session with no Auralis pays one `stat()`.

## Acceptance mapping

| Acceptance | Where it lands |
|---|---|
| AE26 — Markdown rejected, not cleaned; plain resubmission accepted (covers R121, R20) | Runnable at this boundary: `test_rendering_gate.py` + the `test_mcp_server.py` AE26 scenario; evidence recorded in `docs/evidence/voice/auralis-c3-acceptance.md` (U5) |
| AE34 — joint bridge acceptance with C10 | Readiness from this side: U1/U3 green against the independent-literals stub; the joint run itself is coordinator-scheduled across repositories |
| AE19, AE23, AE35, AE36 — joint with C5/C10/C1 | Out of this slice's hands; the adapter contributions they consume (presence, origin, submission, fallback marking) are the tested surfaces above |

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
  pinned at `b49de1b` is the honest trace.
- **R22/R23 read as split requirements** — the adapter half (detect completion without an
  accepted rendering, mark the outcome durably) is planned here; the speaking half is
  Core/C5's, proven jointly at AE36. The alternative reading — that C3 must make fallback
  audible — would require owning speech, which the card forbids.
